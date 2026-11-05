//go:build !js

package main

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"encoding/base64"
	"errors"
	"strings"
	"sync"
	"testing"
	"time"

	abci "github.com/cometbft/cometbft/abci/types"
	"github.com/syndtr/goleveldb/leveldb"
	"github.com/syndtr/goleveldb/leveldb/util"
)

func commitPublicFixture(t *testing.T, app *Ledger, keys []ed25519.PrivateKey, producer, txs int) State {
	t.Helper()
	height := app.state.Height + 1
	batch := dagBatchWire(t, app.dag, dagWire(t, app.dag, keys, producer, txs))
	if _, err := app.FinalizeBlock(context.Background(), &abci.RequestFinalizeBlock{Height: height, Time: time.Unix(1700000001+height, 0), Txs: [][]byte{batch}}); err != nil {
		t.Fatal(err)
	}
	if _, err := app.Commit(context.Background(), &abci.RequestCommit{}); err != nil {
		t.Fatal(err)
	}
	return copyState(app.state)
}

func assertPublicQueries(t *testing.T, app *Ledger, expected State, block string) {
	t.Helper()
	paths := []struct {
		path string
		data []byte
	}{
		{"/gg/dag/account-proof", []byte(app.genesis.DAG.Accounts[0])},
		{"/gg/dag/block-proof", []byte(block)},
		{"/gg/dag/order-page", canonical(map[string]int{"start": 0})},
	}
	for _, item := range paths {
		response, err := app.Query(context.Background(), &abci.RequestQuery{Path: item.path, Height: expected.Height, Data: item.data})
		if err != nil || response.Code != 0 || response.Height != expected.Height {
			t.Fatalf("%s: %v %v", item.path, response, err)
		}
		var verifyErr error
		switch item.path {
		case "/gg/dag/account-proof":
			var proof DagAccountProof
			if decodeStrict(response.Value, &proof) != nil {
				t.Fatal("decode account proof")
			}
			verifyErr = verifyDagAccountProof(proof, expected, *app.genesis.DAG)
		case "/gg/dag/block-proof":
			var proof DagBlockProof
			if decodeStrict(response.Value, &proof) != nil {
				t.Fatal("decode block proof")
			}
			verifyErr = verifyDagBlockProof(proof, expected, *app.genesis.DAG)
		default:
			var proof DagOrderPage
			if decodeStrict(response.Value, &proof) != nil {
				t.Fatal("decode order page")
			}
			verifyErr = verifyDagOrderPage(proof, expected, *app.genesis.DAG)
		}
		if verifyErr != nil {
			t.Fatal("proof failed verification", verifyErr)
		}
	}
}

func TestDagPublicIndexHistoricalProofsAndNoopRootsSurviveRestart(t *testing.T) {
	app, keys, root := dagLedgerFixture(t)
	first := commitPublicFixture(t, app, keys, 0, 3)
	block := orderFixture(t, app.dag)[0].Hash
	second := commitPublicFixture(t, app, keys, 1, 7)
	store := app.store.(*dagStore)
	head, err := store.publicHead()
	if err != nil {
		t.Fatal(err)
	}
	if _, err = app.FinalizeBlock(context.Background(), &abci.RequestFinalizeBlock{Height: 3}); err != nil {
		t.Fatal(err)
	}
	if _, err = app.Commit(context.Background(), &abci.RequestCommit{}); err != nil {
		t.Fatal(err)
	}
	after, err := store.publicHead()
	if err != nil || head != after {
		t.Fatal("empty native block duplicated index", err)
	}
	assertPublicQueries(t, app, first, block)
	assertPublicQueries(t, app, second, block)
	if err = app.Close(); err != nil {
		t.Fatal(err)
	}
	restored, err := newDagEnabledLedger(app.genesis, app.anchor, root, false)
	if err != nil {
		t.Fatal(err)
	}
	defer restored.Close()
	assertPublicQueries(t, restored, first, block)
	assertPublicQueries(t, restored, second, block)
}

func TestDagPublicIndexQueriesReadOnlyDerivedLeavesButRecoveryRequiresEveryPayload(t *testing.T) {
	app, keys, root := dagLedgerFixture(t)
	first := commitPublicFixture(t, app, keys, 0, 3)
	block, wire := orderFixture(t, app.dag)[0].Hash, app.dag.Manifest.Blocks[0]
	commitPublicFixture(t, app, keys, 1, 7)
	store := app.store.(*dagStore)
	reads := 0
	store.beforePublicRead = func(key string) {
		reads++
		if !strings.HasPrefix(key, "pub/") {
			t.Errorf("public query read executable history: %s", key)
		}
	}
	// Owned corruption after startup demonstrates that proof production does
	// not secretly replay payload. Restart must still refuse the damaged store.
	if err := store.db.Delete([]byte("r/"+wire), nil); err != nil {
		t.Fatal(err)
	}
	assertPublicQueries(t, app, first, block)
	if reads != 6 {
		t.Fatalf("expected six small derived reads, got %d", reads)
	}
	_ = app.Close()
	if restored, err := newDagEnabledLedger(app.genesis, app.anchor, root, false); err == nil {
		restored.Close()
		t.Fatal("missing signed payload accepted during recovery")
	}
}

func TestDagPublicIndexSlowHistoricalQueryCannotHoldConsensusOrStoreMutex(t *testing.T) {
	app, keys, _ := dagLedgerFixture(t)
	first := commitPublicFixture(t, app, keys, 0, 3)
	commitPublicFixture(t, app, keys, 1, 7)
	store := app.store.(*dagStore)
	entered, release := make(chan struct{}), make(chan struct{})
	var once, releaseOnce sync.Once
	unblock := func() { releaseOnce.Do(func() { close(release) }) }
	defer unblock()
	store.beforePublicRead = func(string) { once.Do(func() { close(entered); <-release }) }
	queryDone := make(chan *abci.ResponseQuery, 1)
	go func() {
		v, _ := app.Query(context.Background(), &abci.RequestQuery{Path: "/gg/dag/order-page", Height: first.Height, Data: canonical(map[string]int{"start": 0})})
		queryDone <- v
	}()
	select {
	case <-entered:
	case <-time.After(2 * time.Second):
		t.Fatal("query did not reach isolated read")
	}
	committed := make(chan error, 1)
	go func() {
		_, err := app.Info(context.Background(), &abci.RequestInfo{})
		if err == nil {
			_, err = app.FinalizeBlock(context.Background(), &abci.RequestFinalizeBlock{Height: 3})
		}
		if err == nil {
			_, err = app.Commit(context.Background(), &abci.RequestCommit{})
		}
		committed <- err
	}()
	select {
	case err := <-committed:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("blocked proof read stopped native consensus")
	}
	unblock()
	select {
	case response := <-queryDone:
		var page DagOrderPage
		if response == nil || response.Code != 0 || decodeStrict(response.Value, &page) != nil || verifyDagOrderPage(page, first, *app.genesis.DAG) != nil {
			t.Fatal("query lost its original pinned checkpoint")
		}
	case <-time.After(2 * time.Second):
		t.Fatal("query failed after release")
	}
}

func TestDagPublicIndexCloseWaitsForPinnedReadersAndRejectsNewOnes(t *testing.T) {
	app, keys, _ := dagLedgerFixture(t)
	state := commitPublicFixture(t, app, keys, 0, 1)
	store := app.store.(*dagStore)
	entered, release := make(chan struct{}), make(chan struct{})
	var once, releaseOnce sync.Once
	unblock := func() { releaseOnce.Do(func() { close(release) }) }
	defer unblock()
	store.beforePublicRead = func(string) { once.Do(func() { close(entered); <-release }) }
	readDone := make(chan error, 1)
	go func() { _, err := store.publicExecution(context.Background(), *state.DAG); readDone <- err }()
	<-entered
	closeDone := make(chan error, 1)
	go func() { closeDone <- store.close() }()
	deadline := time.After(2 * time.Second)
	for {
		store.mu.Lock()
		closed := store.db == nil
		store.mu.Unlock()
		if closed {
			break
		}
		select {
		case <-deadline:
			t.Fatal("close did not stop admitting readers")
		default:
			time.Sleep(time.Millisecond)
		}
	}
	if _, err := store.publicExecution(context.Background(), *state.DAG); err == nil {
		t.Fatal("closed store admitted reader")
	}
	select {
	case <-closeDone:
		t.Fatal("database closed underneath pinned reader")
	default:
	}
	unblock()
	if err := <-readDone; err != nil {
		t.Fatal(err)
	}
	if err := <-closeDone; err != nil {
		t.Fatal(err)
	}
}

func TestDagPublicIndexCancellationAndWrongContextFailClosed(t *testing.T) {
	app, keys, _ := dagLedgerFixture(t)
	state := commitPublicFixture(t, app, keys, 0, 1)
	store := app.store.(*dagStore)
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := store.publicExecution(ctx, *state.DAG); !errors.Is(err, context.Canceled) {
		t.Fatal("cancelled query did work", err)
	}
	ctx, cancel = context.WithCancel(context.Background())
	defer cancel()
	reads := 0
	store.beforePublicRead = func(string) {
		reads++
		if reads == 2 {
			cancel()
		}
	}
	if _, err := store.publicExecution(ctx, *state.DAG); !errors.Is(err, context.Canceled) || reads != 2 {
		t.Fatal("mid-query cancellation ignored", err, reads)
	}
	store.beforePublicRead = nil
	wrong := *state.DAG
	wrong.NetworkID = strings.Repeat("e", 64)
	if _, err := store.publicExecution(context.Background(), wrong); err == nil {
		t.Fatal("foreign context accepted")
	}
	wrong = *state.DAG
	wrong.OrderRoot = strings.Repeat("e", 64)
	if _, err := store.publicExecution(context.Background(), wrong); err == nil {
		t.Fatal("modified commitment accepted")
	}
}

func TestDagPublicIndexConcurrentWorkIsBoundedWithoutQueuingConsensus(t *testing.T) {
	app, keys, _ := dagLedgerFixture(t)
	state := commitPublicFixture(t, app, keys, 0, 1)
	store := app.store.(*dagStore)
	entered, release := make(chan struct{}, dagPublicMaxReaders), make(chan struct{})
	var releaseOnce sync.Once
	unblock := func() { releaseOnce.Do(func() { close(release) }) }
	defer unblock()
	store.beforePublicRead = func(string) {
		select {
		case entered <- struct{}{}:
		default:
		}
		<-release
	}
	done := make(chan error, dagPublicMaxReaders)
	for i := 0; i < dagPublicMaxReaders; i++ {
		go func() { _, err := store.publicExecution(context.Background(), *state.DAG); done <- err }()
	}
	for i := 0; i < dagPublicMaxReaders; i++ {
		select {
		case <-entered:
		case <-time.After(2 * time.Second):
			t.Fatal("reader did not enter")
		}
	}
	if _, err := store.publicExecution(context.Background(), *state.DAG); err == nil || err.Error() != "GG_DAG_PUBLIC_BUSY" {
		t.Fatal("unbounded public work was admitted", err)
	}
	response, err := app.Query(context.Background(), &abci.RequestQuery{Path: "/gg/state"})
	if err != nil || response.Code != 0 {
		t.Fatal("public saturation blocked state query", err)
	}
	unblock()
	for i := 0; i < dagPublicMaxReaders; i++ {
		if err := <-done; err != nil {
			t.Fatal(err)
		}
	}
	store.mu.Lock()
	active := store.activeReaders
	store.mu.Unlock()
	if active != 0 {
		t.Fatal("reader slot leaked", active)
	}
}

func TestDagPublicIndexMalformedSelectorsAreRejectedBeforeDiskWork(t *testing.T) {
	app, keys, _ := dagLedgerFixture(t)
	commitPublicFixture(t, app, keys, 0, 1)
	store := app.store.(*dagStore)
	reads := 0
	store.beforePublicRead = func(string) { reads++ }
	for _, item := range []struct {
		path string
		data []byte
	}{
		{"/gg/dag/account-proof", []byte(strings.Repeat("x", 64))},
		{"/gg/dag/block-proof", make([]byte, 1024*1024)},
		{"/gg/dag/order-page", []byte(`{"start":-1}`)},
		{"/gg/dag/order-page", []byte(`{"start":1}`)},
		{"/gg/dag/order-page", []byte(`{"start":32}`)},
		{"/gg/dag/order-page", []byte(`{"start":0,"count":1}`)},
	} {
		response, err := app.Query(context.Background(), &abci.RequestQuery{Path: item.path, Data: item.data})
		if err != nil || response.Code != 3 {
			t.Fatal("malformed selector accepted", response, err)
		}
	}
	if reads != 0 {
		t.Fatal("malformed public selector triggered disk work", reads)
	}
}

func TestDagPublicIndexVersionedCorruptionIsNeverRebuilt(t *testing.T) {
	for _, kind := range []string{"head_missing", "head_changed", "snapshot_missing", "leaf_missing", "leaf_changed", "alien_key", "historical_accounts_rehashed"} {
		t.Run(kind, func(t *testing.T) {
			app, keys, root := dagLedgerFixture(t)
			first := commitPublicFixture(t, app, keys, 0, 3)
			commitPublicFixture(t, app, keys, 1, 7)
			store := app.store.(*dagStore)
			batch := new(leveldb.Batch)
			switch kind {
			case "head_missing":
				batch.Delete([]byte("pub/head"))
			case "head_changed":
				batch.Put([]byte("pub/head"), []byte("{}"))
			case "snapshot_missing":
				batch.Delete([]byte(publicSnapshotKey(*first.DAG)))
			case "leaf_missing":
				batch.Delete([]byte(publicOrderKey(1)))
			case "leaf_changed":
				leaf := orderFixture(t, app.dag)[0]
				leaf.Hash = strings.Repeat("e", 64)
				batch.Put([]byte(publicOrderKey(1)), canonical(leaf))
			case "alien_key":
				batch.Put([]byte("pub/unbounded/anything"), []byte("x"))
			case "historical_accounts_rehashed":
				key := publicSnapshotKey(*first.DAG)
				raw, err := store.db.Get([]byte(key), nil)
				if err != nil {
					t.Fatal(err)
				}
				var value dagPublicSnapshot
				if decodePublic(raw, &value) != nil {
					t.Fatal("decode")
				}
				// Keep a canonical, conserved, self-consistent account tree. It
				// must still fail equality against authenticated original replay.
				value.Accounts[0].Balance = "1000000001"
				value.Accounts[1].Balance = "999999999"
				for i := 2; i < len(value.Accounts); i++ {
					value.Accounts[i].Balance = "1000000000"
				}
				value.Commitment.AccountRoot = dagRoot(value.Accounts, "GG-DAG-ACCOUNT-v1\x00")
				changed := canonical(value)
				head, err := store.publicHead()
				if err != nil {
					t.Fatal(err)
				}
				head.Bytes = head.Bytes - publicEntryBytes(key, raw) + publicEntryBytes(key, changed)
				batch.Put([]byte(key), changed)
				batch.Put([]byte("pub/head"), canonical(head))
			}
			if err := store.db.Write(batch, nil); err != nil {
				t.Fatal(err)
			}
			_ = app.Close()
			if restored, err := newDagEnabledLedger(app.genesis, app.anchor, root, false); err == nil {
				restored.Close()
				t.Fatal("versioned corrupt index was accepted/repaired")
			}
		})
	}
}

func TestDagPublicIndexLegacyMigrationRequiresAuthenticatedReplayAndPreservesHistory(t *testing.T) {
	for _, corrupt := range []bool{false, true} {
		t.Run(map[bool]string{false: "valid", true: "payload_missing"}[corrupt], func(t *testing.T) {
			app, keys, root := dagLedgerFixture(t)
			first := commitPublicFixture(t, app, keys, 0, 3)
			block := orderFixture(t, app.dag)[0].Hash
			commitPublicFixture(t, app, keys, 1, 7)
			store := app.store.(*dagStore)
			history, err := store.history()
			if err != nil {
				t.Fatal(err)
			}
			batch := new(leveldb.Batch)
			iterator := store.db.NewIterator(util.BytesPrefix([]byte("pub/")), nil)
			for iterator.Next() {
				batch.Delete(append([]byte(nil), iterator.Key()...))
			}
			err = iterator.Error()
			iterator.Release()
			if err != nil {
				t.Fatal(err)
			}
			meta := store.meta
			meta.PublicIndex = 0
			batch.Put([]byte("meta"), canonical(meta))
			if corrupt {
				batch.Delete([]byte("r/" + app.dag.Manifest.Blocks[0]))
			}
			if err = store.db.Write(batch, nil); err != nil {
				t.Fatal(err)
			}
			_ = app.Close()
			restored, err := newDagEnabledLedger(app.genesis, app.anchor, root, false)
			if corrupt {
				if err == nil {
					restored.Close()
					t.Fatal("migration skipped missing payload")
				}
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			defer restored.Close()
			current, err := restored.store.history()
			if err != nil || !bytes.Equal(history, current) {
				t.Fatal("migration rewrote native history", err)
			}
			if restored.store.(*dagStore).meta.PublicIndex != 2 {
				t.Fatal("legacy index was not persisted")
			}
			assertPublicQueries(t, restored, first, block)
		})
	}
}

func TestDagPublicIndexCommitFailureHasOneAtomicDurableOutcome(t *testing.T) {
	for _, after := range []bool{false, true} {
		t.Run(map[bool]string{false: "before_sync", true: "lost_return_after_sync"}[after], func(t *testing.T) {
			app, keys, root := dagLedgerFixture(t)
			first := commitPublicFixture(t, app, keys, 0, 3)
			batch := dagBatchWire(t, app.dag, dagWire(t, app.dag, keys, 1, 7))
			if _, err := app.FinalizeBlock(context.Background(), &abci.RequestFinalizeBlock{Height: 2, Time: time.Unix(1700000003, 0), Txs: [][]byte{batch}}); err != nil {
				t.Fatal(err)
			}
			selected := app.stagedDag.Commitment
			store := app.store.(*dagStore)
			write := store.write
			store.write = func(batch *leveldb.Batch) error {
				if after {
					if err := write(batch); err != nil {
						return err
					}
				}
				return errors.New("owned commit failure")
			}
			if _, err := app.Commit(context.Background(), &abci.RequestCommit{}); err == nil || app.state.Height != first.Height {
				t.Fatal("uncertain write published state")
			}
			if _, err := store.publicExecution(context.Background(), *first.DAG); err == nil {
				t.Fatal("faulted writer served new reader")
			}
			_ = app.Close()
			restored, err := newDagEnabledLedger(app.genesis, app.anchor, root, false)
			if err != nil {
				t.Fatal(err)
			}
			defer restored.Close()
			want := *first.DAG
			if after {
				want = selected
			}
			head, err := restored.store.(*dagStore).publicHead()
			if err != nil || head.Commitment != want || *restored.state.DAG != want {
				t.Fatal("index and native history recovered different outcomes", err)
			}
			if _, err = restored.store.publicExecution(context.Background(), want); err != nil {
				t.Fatal(err)
			}
			if !after {
				if _, err = restored.store.publicExecution(context.Background(), selected); err == nil {
					t.Fatal("prepared fork entered public index")
				}
			}
		})
	}
}

func TestDagPublicIndexMaximumBoundStoresEachOrderedLeafOnce(t *testing.T) {
	app, keys, _ := dagLedgerFixture(t)
	ctx := context.Background()
	for app.dag.Commitment.Blocks < DagMaxRecords {
		base := app.dag
		builder := base.clone()
		wires := []string{}
		for len(wires) < DagMaxBatchBlocks && builder.orderCount() < DagMaxRecords {
			raw := dagWire(t, builder, keys, 0, 1)
			record, err := decodeDagBlock(raw, builder.Source, 1700000002000000000)
			if err != nil {
				t.Fatal(err)
			}
			if err = builder.admit(record); err != nil {
				t.Fatal(err)
			}
			wires = append(wires, base64.StdEncoding.EncodeToString(raw))
		}
		batch := canonical(DagBatch{Blocks: wires, GenesisHash: app.anchor, Previous: base.Commitment.ManifestHash, Schema: "gg.dag.checkpoint.batch.v1", Sequence: base.Commitment.Checkpoint + 1})
		height := app.state.Height + 1
		if _, err := app.FinalizeBlock(ctx, &abci.RequestFinalizeBlock{Height: height, Time: time.Unix(1700000001+height, 0), Txs: [][]byte{batch}}); err != nil {
			t.Fatal(err)
		}
		if _, err := app.Commit(ctx, &abci.RequestCommit{}); err != nil {
			t.Fatal(err)
		}
	}
	store := app.store.(*dagStore)
	head, err := store.publicHead()
	if err != nil {
		t.Fatal(err)
	}
	if head.Commitment.Blocks != DagMaxRecords || head.Commitment.Transactions != DagMaxRecords || head.Bytes > 2*1024*1024 {
		t.Fatal("maximum index is not linearly bounded")
	}
	iterator := store.db.NewIterator(util.BytesPrefix([]byte("pub/o/")), nil)
	count := 0
	for iterator.Next() {
		count++
	}
	err = iterator.Error()
	iterator.Release()
	if err != nil || count != DagMaxRecords {
		t.Fatal("ordered history duplicated or omitted", count, err)
	}
	if err = store.checkPublicContents(); err != nil {
		t.Fatal(err)
	}
	public, err := store.publicExecution(ctx, *app.state.DAG)
	if err != nil || public.orderCount() != DagMaxRecords || len(public.pending) != 0 {
		t.Fatal("maximum derived view failed", err)
	}
	page, err := dagOrderPageFor(public, app.state, 4064)
	if err != nil || len(page.Items) != 31 || !page.Complete || verifyDagOrderPage(page, app.state, *app.genesis.DAG) != nil {
		t.Fatal("maximum terminal page failed", err)
	}
	for _, query := range []struct {
		path  string
		data  []byte
		limit int
	}{
		{"/gg/dag/account-proof", []byte(app.dag.Accounts[0].Address), 1},
		{"/gg/dag/block-proof", []byte(orderFixture(t, app.dag)[0].Hash), 32},
		{"/gg/dag/block-proof", []byte(orderFixture(t, app.dag)[2048].Hash), 32},
		{"/gg/dag/block-proof", []byte(orderFixture(t, app.dag)[4094].Hash), 32},
		{"/gg/dag/order-page", canonical(map[string]int{"start": 0}), 128},
		{"/gg/dag/order-page", canonical(map[string]int{"start": 2048}), 128},
		{"/gg/dag/order-page", canonical(map[string]int{"start": 4064}), 128},
	} {
		reads := 0
		store.beforePublicRead = func(key string) {
			reads++
			if !strings.HasPrefix(key, "pub/") {
				t.Fatal("indexed query fetched executable payload")
			}
		}
		response, err := app.Query(ctx, &abci.RequestQuery{Path: query.path, Data: query.data})
		if err != nil || response.Code != 0 || reads > query.limit || len(response.Value) > 65536 {
			t.Fatal("indexed query did not remain bounded at maximum history", query.path, reads, err)
		}
		t.Logf("GG_DAG_INDEX_READS path=%s blocks=%d reads=%d response_bytes=%d", query.path, DagMaxRecords, reads, len(response.Value))
	}
}
