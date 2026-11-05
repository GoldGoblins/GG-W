//go:build !js

package main

// Source-only actual SDK local-client boundary: no direct app mutable call.
import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	abci "github.com/cometbft/cometbft/abci/types"
	"os"
	"strings"
	"testing"
	"time"
)

func TestOwnedSDKCrashGapContextAndColdCutFreezeUseActualLocalClient(t *testing.T) {
	app, _, root, _ := historyPublicFixture(t)
	genesis, anchor := app.genesis, app.anchor
	if err := app.Close(); err != nil {
		t.Fatal(err)
	}
	app, err := newFinancialLedger(genesis, anchor, root, false)
	if err != nil {
		t.Fatal(err)
	}
	defer app.Close()
	backend := app.financial.(*financialNativeApplication)
	coldCut := backend.store.verifiedThrough
	input, output, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	defer input.Close()
	defer output.Close()
	var frames bytes.Buffer
	readDone := make(chan struct{})
	observed := make(chan []byte, 16)
	go func() {
		defer close(readDone)
		reader := bufio.NewReader(input)
		for {
			line, err := reader.ReadBytes('\n')
			if len(line) > 0 {
				_, _ = frames.Write(line)
				observed <- append([]byte(nil), line...)
			}
			if err != nil {
				return
			}
		}
	}()
	lifetime, cancel := context.WithCancel(context.Background())
	defer cancel()
	recovery := &ownedRecovery{output: output, root: root, anchor: anchor, attempt: strings.Repeat("b", 32), phase: "SDK_START", cancel: cancel}
	recovery.lastCompleted.Store(time.Now().UnixNano())
	recovery.sdkRecoveryActive.Store(true)
	owned := context.WithValue(lifetime, ownedRecoveryKey{}, recovery)
	creator := newOwnedLedgerClientCreator(app, owned)
	first, err := creator.NewABCIClient()
	if err != nil {
		t.Fatal(err)
	}
	second, err := creator.NewABCIClient()
	if err != nil {
		t.Fatal(err)
	}
	execute := func() {
		t.Helper()
		height := app.state.Height + 1
		when := time.Unix(0, backend.store.timeNs+1000000)
		if _, err := first.FinalizeBlock(context.TODO(), &abci.RequestFinalizeBlock{Height: height, Time: when}); err != nil {
			t.Fatal("SDK TODO FinalizeBlock", err)
		}
		if _, err := second.Commit(context.TODO(), &abci.RequestCommit{}); err != nil {
			t.Fatal("SDK TODO Commit", err)
		}
	}
	// The SDK caller's TODO must still reach the owned real completed-work cell.
	execute()
	if recovery.work == 0 || recovery.processed != nil {
		t.Fatal("SDK replay lost real work or claimed cold processed height")
	}
	if err = recovery.sealSDKRecovery(coldCut); err != nil {
		t.Fatal(err)
	}
	workAtConstructor := recovery.work
	// Hold the app work lock while the SDK's actual local client enters its
	// normal mutable-call path. Freeze progress concurrently with that live
	// post-constructor call, then let it finish through the same SDK mutex.
	runtimeRequest := &abci.RequestFinalizeBlock{Height: app.state.Height + 1, Time: time.Unix(0, backend.store.timeNs+1000000)}
	app.mu.Lock()
	entered := make(chan struct{})
	runtimeDone := make(chan error, 1)
	go func() {
		close(entered)
		_, err := first.FinalizeBlock(context.TODO(), runtimeRequest)
		if err == nil {
			_, err = second.Commit(context.TODO(), &abci.RequestCommit{})
		}
		runtimeDone <- err
	}()
	<-entered
	if err = recoveryWork(owned, 1, &coldCut); err != nil {
		app.mu.Unlock()
		t.Fatal(err)
	}
	if err = recovery.freezeProgress(owned); err != nil {
		app.mu.Unlock()
		t.Fatal(err)
	}
	app.mu.Unlock()
	if err = <-runtimeDone; err != nil {
		t.Fatal("live SDK call across PREPARED freeze", err)
	}
	if app.state.Height <= coldCut || backend.store.verifiedThrough != coldCut || recovery.work != workAtConstructor+1 {
		t.Fatal("fresh runtime head changed cold audit progress")
	}
	if cut, err := recovery.auditedColdCut(); err != nil || cut != coldCut {
		t.Fatal("audited cut followed newest runtime head", err)
	}
	// Wait for the final complete coldcut frame to be consumed before closing
	// its real pipe; this is an IO barrier, not a progress heartbeat.
	for {
		line := <-observed
		var frame map[string]json.RawMessage
		if json.Unmarshal(line, &frame) != nil {
			t.Fatal("frame")
		}
		if string(frame["processed_height"]) == fmt.Sprint(coldCut) {
			break
		}
	}
	if err = input.Close(); err != nil {
		t.Fatal(err)
	}
	<-readDone
	frozenBytes := append([]byte(nil), frames.Bytes()...)
	// A closed public observation pipe must not cancel live SDK work after the
	// atomic PREPARED boundary. No recovery progress write is now permitted.
	execute()
	if lifetime.Err() != nil || !bytes.Equal(frames.Bytes(), frozenBytes) {
		t.Fatal("runtime SDK callback wrote after PREPARED or cancelled live owner")
	}
	state, _, err := backend.LocalHistoryStatus(context.Background())
	if err != nil || state["verified_through"] != fmt.Sprint(coldCut) {
		t.Fatal("native status cold cut disagrees", err)
	}
	for _, line := range bytes.Split(bytes.TrimSpace(frozenBytes), []byte{'\n'}) {
		var frame map[string]json.RawMessage
		if json.Unmarshal(line, &frame) != nil {
			t.Fatal("progress frame")
		}
		raw := frame["processed_height"]
		if string(raw) != "null" && string(raw) != fmt.Sprint(coldCut) {
			t.Fatal("fresh SDK runtime height promoted to cold audit", string(raw))
		}
	}
	before := canonical(app.state)
	cancel()
	if _, err = first.FinalizeBlock(context.TODO(), &abci.RequestFinalizeBlock{Height: app.state.Height + 1, Time: time.Unix(0, backend.store.timeNs+1000000)}); !errors.Is(err, context.Canceled) {
		t.Fatal("SDK TODO call lost owned cancellation", err)
	}
	if !bytes.Equal(before, canonical(app.state)) {
		t.Fatal("cancelled SDK call mutated state")
	}
}

func TestOwnedSDKCallPreservesCallerCancellationAndOwnedDeadlineIndependently(t *testing.T) {
	owned, cancelOwned := context.WithCancel(context.Background())
	defer cancelOwned()
	caller, cancelCaller := context.WithCancel(context.Background())
	joined, done := ownedLedgerCallContext(caller, owned)
	defer done()
	cancelCaller()
	if !errors.Is(joined.Err(), context.Canceled) {
		t.Fatal("caller cancellation lost")
	}
	caller2, cancelCaller2 := context.WithTimeout(context.Background(), time.Second)
	defer cancelCaller2()
	joined2, done2 := ownedLedgerCallContext(caller2, owned)
	defer done2()
	cancelOwned()
	select {
	case <-joined2.Done():
	case <-time.After(time.Second):
		t.Fatal("owned cancellation lost")
	}
	if deadline, ok := joined2.Deadline(); !ok || deadline.IsZero() {
		t.Fatal("caller deadline lost")
	}
}
