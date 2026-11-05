//go:build !js

package main

// Source candidate only: NOT_EXECUTED. These are meaningful native component
// boundaries; CLI/UI/quorum and an actual >180s replay remain separate gates.
import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	cmted "github.com/cometbft/cometbft/crypto/ed25519"
	cmtproto "github.com/cometbft/cometbft/proto/tendermint/types"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func nativeRecoveryTestContext(t *testing.T, output io.Writer, phase string) (context.Context, *ownedRecovery) {
	t.Helper()
	ctx, cancel := context.WithCancel(context.Background())
	t.Cleanup(cancel)
	r := &ownedRecovery{output: output, root: t.TempDir(), anchor: strings.Repeat("a", 64), attempt: strings.Repeat("b", 32), phase: phase, cancel: cancel}
	r.lastCompleted.Store(time.Now().UnixNano())
	return context.WithValue(ctx, ownedRecoveryKey{}, r), r
}

func TestOwnedRecoveryActualRetained4097SegmentsColdReplayAndLateCorruption(t *testing.T) {
	app, backend, root, block := historyPublicFixture(t)
	// Each iteration commits an actual valid SDK-bound empty original, and seals
	// precisely its real immutable journal/header/index entries. No padding or
	// increased parser/segment/batch constant supplies the retained files.
	for i := 0; i < 4097; i++ {
		commitFinancialSDK(t, app, nil)
		historySealAll(t, backend.store)
	}
	if backend.store.history.head.Segments <= 4096 {
		t.Fatal("fixture lacks real retained files")
	}
	state := canonical(app.state)
	genesis, anchor := app.genesis, app.anchor
	selector := financialReceiptSelector{Block: block, Index: 0}
	receipt, err := backend.Receipt(context.Background(), app.state, selector)
	if err != nil {
		t.Fatal(err)
	}
	address := publicFixtureAddress(publicFixtureKey("history-recipient"))
	account, err := backend.Account(context.Background(), app.state, address)
	if err != nil {
		t.Fatal(err)
	}
	if err = app.Close(); err != nil {
		t.Fatal(err)
	}
	ctx, r := nativeRecoveryTestContext(t, io.Discard, "INVENTORY")
	if err = inventoryOwnedNativeRoot(ctx, root); err != nil {
		t.Fatal("valid >4096 native inventory", err)
	}
	if r.work < 4097 {
		t.Fatal("actual inventory not observed")
	}
	if err = recoveryPhase(ctx, "VERIFY_HISTORY"); err != nil {
		t.Fatal(err)
	}
	cold, err := newFinancialLedgerContext(ctx, genesis, anchor, root, false)
	if err != nil {
		t.Fatal("actual complete cold replay", err)
	}
	checked := cold.financial.(*financialNativeApplication)
	afterReceipt, e := checked.Receipt(context.Background(), cold.state, selector)
	if e != nil || !bytes.Equal(canonical(afterReceipt), canonical(receipt)) {
		t.Fatal("receipt bytes changed", e)
	}
	afterAccount, e := checked.Account(context.Background(), cold.state, address)
	if e != nil || !bytes.Equal(canonical(afterAccount), canonical(account)) {
		t.Fatal("balance/nonce/proof changed", e)
	}
	if !bytes.Equal(canonical(cold.state), state) || checked.store.verifiedThrough != cold.state.Height {
		t.Fatal("full audit did not reach exact final state")
	}
	if r.verified != nil {
		t.Fatal("provisional progress became verified")
	}
	last := filepath.Join(checked.store.history.directory(), historySegmentName(checked.store.history.head.Segments))
	if err = cold.Close(); err != nil {
		t.Fatal(err)
	}
	file, e := os.OpenFile(last, os.O_RDWR, 0)
	if e != nil {
		t.Fatal(e)
	}
	info, e := file.Stat()
	if e != nil {
		t.Fatal(e)
	}
	var tail [1]byte
	if _, e = file.ReadAt(tail[:], info.Size()-1); e != nil {
		t.Fatal(e)
	}
	tail[0] ^= 1
	if _, e = file.WriteAt(tail[:], info.Size()-1); e != nil {
		t.Fatal(e)
	}
	if e = file.Close(); e != nil {
		t.Fatal(e)
	}
	if bad, e := newFinancialLedgerContext(ctx, genesis, anchor, root, false); e == nil {
		_ = bad.Close()
		t.Fatal("corruption after4096 genuine files passed full replay")
	}
}

func TestOwnedRecoveryProgressS63AndStallIsRealWorkOnly(t *testing.T) {
	var output bytes.Buffer
	_, r := nativeRecoveryTestContext(t, &output, "INVENTORY")
	r.work = 1<<53 - 1
	if err := r.complete(2, nil); err != nil || r.work != 1<<53+1 {
		t.Fatal("legal S63 progress narrowed to JS-safe", err)
	}
	before := r.lastCompleted.Load()
	if r.stalled(time.Unix(0, before).Add(179 * time.Second)) {
		t.Fatal("real completed work expired early")
	}
	if !r.stalled(time.Unix(0, before).Add(181 * time.Second)) {
		t.Fatal("unchanged work extended lease")
	}
	// Synthetic time checks lease arithmetic only. They do not claim an actual
	// >180s replay or an actual180s blocked-read acceptance result.
	r.work = ownedRecoveryCounterMax - 1
	r.sent = time.Time{}
	height := int64(ownedRecoveryCounterMax)
	if err := r.complete(1, &height); err != nil {
		t.Fatal("maximum legal S63 rejected", err)
	}
	if err := r.complete(1, nil); err == nil {
		t.Fatal("S63 overflow accepted")
	}
	scanner := bufio.NewScanner(bytes.NewReader(output.Bytes()))
	scanner.Buffer(make([]byte, 1024), ownedRestoreFrameMax)
	for scanner.Scan() {
		var frame map[string]json.RawMessage
		if json.Unmarshal(scanner.Bytes(), &frame) != nil {
			t.Fatal("frame invalid")
		}
		if string(frame["verified_through"]) != "null" {
			t.Fatal("provisional verification claim")
		}
	}
	if scanner.Err() != nil {
		t.Fatal(scanner.Err())
	}
}

func TestOwnedRecoveryCancelledBeforeInventoryOrColdOpen(t *testing.T) {
	app, _, root, _ := historyPublicFixture(t)
	genesis, anchor := app.genesis, app.anchor
	if err := app.Close(); err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if err := inventoryOwnedNativeRoot(ctx, root); !errors.Is(err, context.Canceled) {
		t.Fatal("inventory ignored cancellation", err)
	}
	if cold, err := newFinancialLedgerContext(ctx, genesis, anchor, root, false); err == nil {
		_ = cold.Close()
		t.Fatal("cold open ignored cancellation")
	}
}

func TestOwnedRecoveryUnknownContentHardlinkAndRootReplacement(t *testing.T) {
	// Pinned goleveldb writes these precise CURRENT variants; foreign suffixes
	// still fail layout admission before any semantic DB/fullcold readiness.
	for _, item := range []struct {
		name  string
		allow bool
	}{
		{"CURRENT", true}, {"CURRENT.bak", true}, {"CURRENT.0", true}, {"CURRENT.123", true},
		{"CURRENT.backup", false}, {"CURRENT.bak.tmp", false}, {"CURRENT.123.tmp", false},
		{"CURRENT.-1", false}, {"CURRENT.+1", false}, {"CURRENT.", false}, {"CURRENT.xyz", false},
	} {
		t.Run("leveldb_"+item.name, func(t *testing.T) {
			if got := ownedNativeLayout(filepath.Join("gg-financial-dag.leveldb", item.name), false); got != item.allow {
				t.Fatal("exact pinned LevelDB filename policy", item.name, got)
			}
		})
	}

	ctx, _ := nativeRecoveryTestContext(t, io.Discard, "INVENTORY")
	root := t.TempDir()
	if err := os.WriteFile(filepath.Join(root, "foreign.bin"), []byte("foreign"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := inventoryOwnedNativeRoot(ctx, root); err == nil {
		t.Fatal("unknown root content accepted")
	}
	if err := os.Remove(filepath.Join(root, "foreign.bin")); err != nil {
		t.Fatal(err)
	}
	data := filepath.Join(root, "data")
	if err := os.Mkdir(data, 0700); err != nil {
		t.Fatal(err)
	}
	state := filepath.Join(data, "priv_validator_state.json")
	if err := os.WriteFile(state, []byte("{}"), 0600); err != nil {
		t.Fatal(err)
	}
	link := filepath.Join(t.TempDir(), "external-link")
	if err := os.Link(state, link); err != nil {
		t.Skip("hardlink unavailable on this host: " + err.Error())
	}
	if err := inventoryOwnedNativeRoot(ctx, root); err == nil {
		t.Fatal("external hardlink accepted")
	}
	if err := os.Remove(link); err != nil {
		t.Fatal(err)
	}
	anchor, err := openOwnedRecoveryRoot(root)
	if err != nil {
		t.Fatal(err)
	}
	defer anchor.close()
	bound := context.WithValue(ctx, ownedRecoveryRootKey{}, anchor)
	// Legitimate content changes cannot invalidate this root identity.
	if err = os.WriteFile(filepath.Join(data, "priv_validator_state.json"), []byte(`{"height":0}`), 0600); err != nil {
		t.Fatal(err)
	}
	if err = recoveryRootCurrent(bound, root); err != nil {
		t.Fatal("legitimate root content change rejected", err)
	}

	moved := root + "-moved"
	if err = os.Rename(root, moved); err != nil {
		t.Fatal(err)
	}
	defer os.RemoveAll(moved)
	if err = os.Mkdir(root, 0700); err != nil {
		t.Fatal(err)
	}
	if err = recoveryRootCurrent(bound, root); err == nil {
		t.Fatal("root epoch replacement accepted")
	}
}

func TestOwnedRecoverySafePVOriginalJournalRemainsClosedUntilSDKGate(t *testing.T) {
	key := cmted.PrivKey(publicFixtureKey("owned-recovery-signer"))
	path := filepath.Join(t.TempDir(), "priv_validator_state.json")
	pv, err := initializeSafePV(key, path, "owned-recovery")
	if err != nil {
		t.Fatal(err)
	}
	original, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	pv.recovery = ctx
	pv.recoveryReady = false
	if err = pv.SignVote("owned-recovery", &cmtproto.Vote{}); err == nil {
		t.Fatal("recovering validator signed vote")
	}
	if err = pv.SignProposal("owned-recovery", &cmtproto.Proposal{}); err == nil {
		t.Fatal("recovering validator signed proposal")
	}
	after, err := os.ReadFile(path)
	if err != nil || !bytes.Equal(original, after) {
		t.Fatal("recovery rewrote signer state", err)
	}
	if _, err = newSafePV(key, path, "owned-recovery"); err != nil {
		t.Fatal("original signer floor not reusable", err)
	}
	pv.recoveryReady = true
	cancel()
	if err = pv.SignVote("owned-recovery", &cmtproto.Vote{}); err == nil {
		t.Fatal("cancelled validator signed")
	}
}

func TestOwnedRecoveryPreparedACKBindsExactEpochAndRejectsExtraFrame(t *testing.T) {
	for _, change := range []string{"valid", "attempt", "pid", "root", "profile", "extra"} {
		t.Run(change, func(t *testing.T) {
			ctx, r := nativeRecoveryTestContext(t, io.Discard, "SDK_START")
			input, writer, err := os.Pipe()
			if err != nil {
				t.Fatal(err)
			}
			defer input.Close()
			r.input = input
			r.reader = bufio.NewReaderSize(input, ownedRestoreFrameMax)
			ack := map[string]any{"schema": "gg.native.owned-recovery-start-ack.v1", "attempt": r.attempt, "pid": os.Getpid(), "genesis_hash": r.anchor, "root": r.root, "resource_profile": r.profile}
			switch change {
			case "attempt":
				ack["attempt"] = strings.Repeat("c", 32)
			case "pid":
				ack["pid"] = os.Getpid() + 1
			case "root":
				ack["root"] = r.root + "-other"
			case "profile":
				ack["resource_profile"] = map[string]any{"foreign": true}
			}
			sent := make(chan error, 1)
			go func() {
				err := writeOwnedRestoreFrame(writer, ack)
				if err == nil && change == "extra" {
					err = writeOwnedRestoreFrame(writer, ack)
				}
				_ = writer.Close()
				sent <- err
			}()
			err = r.acknowledgePrepared(ctx)
			if change == "valid" && err != nil || change != "valid" && err == nil {
				t.Fatal("exact prepared ACK boundary", change, err)
			}
			_ = input.Close()
			<-sent
		})
	}
}

func TestOwnedRecoveryCanonicalWirePhasesAndS63Golden(t *testing.T) {
	for _, phases := range [][]string{{"INVENTORY", "VERIFY_HISTORY", "VERIFY_SDK_BINDINGS", "SDK_START"}, {"INVENTORY", "ARCHIVE_AUDIT", "ARCHIVE_RESTORE", "VERIFY_HISTORY", "VERIFY_SDK_BINDINGS", "SDK_START"}} {
		var output bytes.Buffer
		ctx, r := nativeRecoveryTestContext(t, &output, "")
		for _, phase := range phases {
			if err := recoveryPhase(ctx, phase); err != nil {
				t.Fatal(err)
			}
		}
		r.work = 1 << 53
		r.sent = time.Time{}
		height := int64(ownedRecoveryCounterMax)
		if err := recoveryWork(ctx, 1, &height); err != nil {
			t.Fatal(err)
		}
		scanner := bufio.NewScanner(bytes.NewReader(output.Bytes()))
		scanner.Buffer(make([]byte, 1024), ownedRestoreFrameMax)
		seen := []string{}
		for scanner.Scan() {
			var frame map[string]json.RawMessage
			if json.Unmarshal(scanner.Bytes(), &frame) != nil {
				t.Fatal("invalid canonical frame")
			}
			var phase string
			if json.Unmarshal(frame["phase"], &phase) != nil {
				t.Fatal("phase type")
			}
			seen = append(seen, phase)
			if len(frame) != 11 || string(frame["schema"]) != `"gg.native.owned-recovery-progress.v1"` || string(frame["native_node_ready"]) != "false" || string(frame["verified_through"]) != "null" {
				t.Fatal("wire keys/schema/provisional boundary")
			}
		}
		if scanner.Err() != nil {
			t.Fatal(scanner.Err())
		}
		if len(seen) != len(phases)+1 {
			t.Fatal("empty phase was skipped")
		}
		for i, phase := range phases {
			if seen[i] != phase {
				t.Fatal("phase order")
			}
		}
		lines := bytes.Split(bytes.TrimSpace(output.Bytes()), []byte{'\n'})
		last := lines[len(lines)-1]
		if !bytes.Contains(last, []byte(`"work_done":9007199254740993`)) || !bytes.Contains(last, []byte(`"processed_height":9223372036854775807`)) {
			t.Fatal("S63 precision narrowed", string(last))
		}
	}
}
