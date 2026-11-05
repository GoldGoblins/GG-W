//go:build !js

package main

import (
	"bytes"
	"context"
	"errors"
	"strings"
	"sync"
	"testing"
	"time"

	abci "github.com/cometbft/cometbft/abci/types"
	"github.com/syndtr/goleveldb/leveldb"
	"github.com/syndtr/goleveldb/leveldb/util"
)

func assertIndexedProofEqual(t *testing.T, app *Ledger, execution *DagExecution, state State, path, identifier string, start int) {
	t.Helper()
	store := app.store.(*dagStore)
	actual, err := store.publicProof(context.Background(), state, path, identifier, start)
	if err != nil {
		t.Fatal("indexed proof", path, state.DAG.Blocks, start, err)
	}
	var expected any
	switch path {
	case "/gg/dag/account-proof":
		expected, err = dagAccountProofFor(execution, state, identifier)
	case "/gg/dag/block-proof":
		expected, err = dagBlockProofFor(execution, state, identifier)
	case "/gg/dag/order-page":
		expected, err = dagOrderPageFor(execution, state, start)
	}
	if err != nil || !bytes.Equal(canonical(actual), canonical(expected)) {
		t.Fatal("indexed witness differs from independent original complete-tree oracle", path, state.DAG.Blocks, start, err)
	}
}

func TestDagMerkleIndexMatchesOriginalProofBytesAtEveryPrefixAndHistoricalOddBoundary(t *testing.T) {
	app, keys, root := dagLedgerFixture(t)
	type view struct {
		execution *DagExecution
		state     State
	}
	views := []view{{proofFixture(t, app.dag), copyState(app.state)}}
	for i := 0; i < 129; i++ {
		state := commitPublicFixture(t, app, keys, i%6, i%3)
		views = append(views, view{proofFixture(t, app.dag), state})
	}
	for _, old := range views {
		assertIndexedProofEqual(t, app, old.execution, old.state, "/gg/dag/account-proof", old.execution.Accounts[0].Address, 0)
		for start := 0; start < old.execution.orderCount() || start == 0; start += DagOrderPageSize {
			assertIndexedProofEqual(t, app, old.execution, old.state, "/gg/dag/order-page", "", start)
		}
		if old.execution.orderCount() > 0 {
			for _, index := range []int{0, old.execution.orderCount() / 2, old.execution.orderCount() - 1} {
				assertIndexedProofEqual(t, app, old.execution, old.state, "/gg/dag/block-proof", orderFixture(t, old.execution)[index].Hash, 0)
			}
		}
	}
	first := views[3]
	app.Close()
	restored, err := newDagEnabledLedger(app.genesis, app.anchor, root, false)
	if err != nil {
		t.Fatal(err)
	}
	defer restored.Close()
	assertIndexedProofEqual(t, restored, first.execution, first.state, "/gg/dag/block-proof", orderFixture(t, first.execution)[0].Hash, 0)
	assertIndexedProofEqual(t, restored, first.execution, first.state, "/gg/dag/order-page", "", 0)
}

// Fixture conversion to the exact previous derived index schema. Original
// signed payload, native history and all account snapshots remain unchanged.
func downgradePublicIndexFixture(t *testing.T, app *Ledger) {
	t.Helper()
	store := app.store.(*dagStore)
	head, err := store.publicHead()
	if err != nil {
		t.Fatal(err)
	}
	batch := new(leveldb.Batch)
	iterator := store.db.NewIterator(util.BytesPrefix([]byte("pub/")), nil)
	for iterator.Next() {
		key := string(iterator.Key())
		if strings.HasPrefix(key, "pub/h/") || strings.HasPrefix(key, "pub/n/") {
			head.Bytes -= publicEntryBytes(key, iterator.Value())
			batch.Delete(append([]byte(nil), iterator.Key()...))
		}
	}
	err = iterator.Error()
	iterator.Release()
	if err != nil {
		t.Fatal(err)
	}
	head.Schema = "gg.dag.public-head.v1"
	batch.Put([]byte("pub/head"), canonical(head))
	meta := store.meta
	meta.PublicIndex = 1
	batch.Put([]byte("meta"), canonical(meta))
	if err = store.db.Write(batch, nil); err != nil {
		t.Fatal(err)
	}
}

func TestDagMerkleIndexV1MigrationAuthenticatesHistoryAndHasOneAtomicFailureOutcome(t *testing.T) {
	for _, outcome := range []string{"success", "before_sync", "after_sync", "missing_payload"} {
		t.Run(outcome, func(t *testing.T) {
			app, keys, root := dagLedgerFixture(t)
			first := commitPublicFixture(t, app, keys, 0, 2)
			commitPublicFixture(t, app, keys, 1, 3)
			current := copyState(app.state)
			oracle := proofFixture(t, app.dag)
			history, err := app.store.history()
			if err != nil {
				t.Fatal(err)
			}
			downgradePublicIndexFixture(t, app)
			if outcome == "missing_payload" {
				if err = app.store.(*dagStore).db.Delete([]byte("r/"+app.dag.Manifest.Blocks[0]), nil); err != nil {
					t.Fatal(err)
				}
			}
			app.Close()
			if outcome == "before_sync" || outcome == "after_sync" {
				store, err := newDagStore(*app.genesis.DAG, app.anchor, root, false)
				if err != nil {
					t.Fatal(err)
				}
				snapshots := []dagPublicSnapshot{}
				execution, err := store.replay(*current.DAG, func(value *DagExecution) { snapshots = append(snapshots, publicSnapshot(value)) })
				if err != nil {
					store.close()
					t.Fatal(err)
				}
				write := store.write
				store.write = func(batch *leveldb.Batch) error {
					if outcome == "after_sync" {
						if err := write(batch); err != nil {
							return err
						}
					}
					return errors.New("owned migration completion loss")
				}
				if err = store.verifyOrMigratePublic(execution, snapshots); err == nil || !store.failed {
					store.close()
					t.Fatal("unknown migration completion did not latch")
				}
				store.close()
				inspect, err := newDagStore(*app.genesis.DAG, app.anchor, root, false)
				if err != nil {
					t.Fatal(err)
				}
				want := 1
				if outcome == "after_sync" {
					want = 2
				}
				if inspect.meta.PublicIndex != want {
					inspect.close()
					t.Fatal("migration has a partial durable outcome")
				}
				inspect.close()
			}
			restored, err := newDagEnabledLedger(app.genesis, app.anchor, root, false)
			if outcome == "missing_payload" {
				if err == nil {
					restored.Close()
					t.Fatal("index migration bypassed original signed history")
				}
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			defer restored.Close()
			if restored.store.(*dagStore).meta.PublicIndex != 2 {
				t.Fatal("v1 index was not durably migrated")
			}
			got, err := restored.store.history()
			if err != nil || !bytes.Equal(got, history) || !bytes.Equal(canonical(current), canonical(restored.state)) {
				t.Fatal("migration changed original history, identity or roots")
			}
			assertIndexedProofEqual(t, restored, oracle, current, "/gg/dag/order-page", "", 0)
			assertPublicQueries(t, restored, first, orderFixture(t, oracle)[0].Hash)
		})
	}
}

func TestDagMerkleIndexCorruptNodesRefsAndCanonicalRehashAreNeverRepaired(t *testing.T) {
	for _, kind := range []string{"node_missing", "node_hash", "node_encoding", "node_key", "ref_missing", "ref_index", "ref_encoding", "ref_key"} {
		t.Run(kind, func(t *testing.T) {
			app, keys, root := dagLedgerFixture(t)
			for i := 0; i < 3; i++ {
				commitPublicFixture(t, app, keys, i, 1)
			}
			store := app.store.(*dagStore)
			leaf := orderFixture(t, app.dag)[0]
			batch := new(leveldb.Batch)
			key := publicNodeKey(0, 1)
			switch kind {
			case "node_missing":
				batch.Delete([]byte(key))
			case "node_hash":
				batch.Put([]byte(key), canonical(strings.Repeat("e", 64)))
			case "node_encoding":
				batch.Put([]byte(key), []byte("{}"))
			case "node_key":
				batch.Put([]byte("pub/n/01/00000001"), canonical(strings.Repeat("e", 64)))
			case "ref_missing":
				batch.Delete([]byte(publicRefKey(leaf.Hash)))
			case "ref_index":
				batch.Put([]byte(publicRefKey(leaf.Hash)), canonical(2))
			case "ref_encoding":
				batch.Put([]byte(publicRefKey(leaf.Hash)), []byte("1.0"))
			case "ref_key":
				batch.Put([]byte("pub/h/"+strings.Repeat("X", 64)), canonical(1))
			}
			if err := store.db.Write(batch, nil); err != nil {
				t.Fatal(err)
			}
			value, err := store.publicProof(context.Background(), app.state, "/gg/dag/block-proof", leaf.Hash, 0)
			if (kind == "node_missing" || kind == "node_hash" || kind == "node_encoding" || kind == "ref_missing" || kind == "ref_index" || kind == "ref_encoding") && err == nil {
				t.Fatal("corrupt selected witness served as valid", value)
			}
			app.Close()
			restored, err := newDagEnabledLedger(app.genesis, app.anchor, root, false)
			if err == nil {
				restored.Close()
				t.Fatal("versioned missing/changed derived index was accepted or rebuilt")
			}
		})
	}
}

func TestDagMerkleIndexQueryCancellationReaderLimitAndCloseUseBoundedPins(t *testing.T) {
	app, keys, _ := dagLedgerFixture(t)
	state := commitPublicFixture(t, app, keys, 0, 1)
	store := app.store.(*dagStore)
	ctx, cancel := context.WithCancel(context.Background())
	reads := 0
	store.beforePublicRead = func(string) {
		reads++
		if reads == 2 {
			cancel()
		}
	}
	_, err := store.publicProof(ctx, state, "/gg/dag/block-proof", orderFixture(t, app.dag)[0].Hash, 0)
	if !errors.Is(err, context.Canceled) || reads != 2 {
		t.Fatal("query ignored bounded cancellation", reads, err)
	}
	entered, release := make(chan struct{}, dagPublicMaxReaders), make(chan struct{})
	var releaseOnce sync.Once
	unblock := func() { releaseOnce.Do(func() { close(release) }) }
	defer unblock()
	store.beforePublicRead = func(string) { entered <- struct{}{}; <-release }
	done := make(chan error, dagPublicMaxReaders)
	for i := 0; i < dagPublicMaxReaders; i++ {
		go func() {
			_, err := store.publicProof(context.Background(), state, "/gg/dag/account-proof", app.dag.Accounts[0].Address, 0)
			done <- err
		}()
		select {
		case <-entered:
		case <-time.After(2 * time.Second):
			t.Fatal("bounded query did not pin")
		}
	}
	if _, err = store.publicProof(context.Background(), state, "/gg/dag/account-proof", app.dag.Accounts[0].Address, 0); err == nil || err.Error() != "GG_DAG_PUBLIC_BUSY" {
		t.Fatal("unbounded public query readers")
	}
	closed := make(chan error, 1)
	go func() { closed <- app.Close() }()
	select {
	case <-closed:
		t.Fatal("Close did not drain pinned proofs")
	case <-time.After(20 * time.Millisecond):
	}
	unblock()
	for i := 0; i < dagPublicMaxReaders; i++ {
		select {
		case err := <-done:
			if err != nil {
				t.Fatal(err)
			}
		case <-time.After(2 * time.Second):
			t.Fatal("reader failed to release")
		}
	}
	select {
	case err := <-closed:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("Close deadlocked")
	}
	if _, err = store.publicProof(context.Background(), state, "/gg/dag/account-proof", state.Accounts[0].Address, 0); err == nil {
		t.Fatal("closed store served proof")
	}
}

func TestDagMerkleIndexHistoricalReadThroughActualSDKClientCannotBlockCommit(t *testing.T) {
	app, keys, _ := dagLedgerFixture(t)
	first := commitPublicFixture(t, app, keys, 0, 1)
	commitPublicFixture(t, app, keys, 1, 1)
	store := app.store.(*dagStore)
	entered, release := make(chan struct{}), make(chan struct{})
	var once, releaseOnce sync.Once
	unblock := func() { releaseOnce.Do(func() { close(release) }) }
	defer unblock()
	store.beforePublicRead = func(string) { once.Do(func() { close(entered); <-release }) }
	creator := newLedgerClientCreator(app)
	query, err := creator.NewABCIClient()
	if err != nil {
		t.Fatal(err)
	}
	consensus, err := creator.NewABCIClient()
	if err != nil {
		t.Fatal(err)
	}
	done := make(chan *abci.ResponseQuery, 1)
	go func() {
		response, _ := query.Query(context.Background(), &abci.RequestQuery{Path: "/gg/dag/order-page", Height: first.Height, Data: canonical(map[string]int{"start": 0})})
		done <- response
	}()
	select {
	case <-entered:
	case <-time.After(2 * time.Second):
		t.Fatal("indexed SDK query did not reach isolated read")
	}
	committed := make(chan error, 1)
	go func() {
		_, err := consensus.FinalizeBlock(context.Background(), &abci.RequestFinalizeBlock{Height: 3})
		if err == nil {
			_, err = consensus.Commit(context.Background(), &abci.RequestCommit{})
		}
		committed <- err
	}()
	select {
	case err := <-committed:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("indexed proof query held actual SDK consensus mutex")
	}
	unblock()
	response := <-done
	var page DagOrderPage
	if response == nil || response.Code != 0 || decodeStrict(response.Value, &page) != nil || verifyDagOrderPage(page, first, *app.genesis.DAG) != nil {
		t.Fatal("indexed query lost historical SDK state pin")
	}
}
