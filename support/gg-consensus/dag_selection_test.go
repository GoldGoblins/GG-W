//go:build !js

package main

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"strings"
	"sync"
	"testing"
	"time"

	abci "github.com/cometbft/cometbft/abci/types"
	"github.com/syndtr/goleveldb/leveldb"
	"github.com/syndtr/goleveldb/leveldb/opt"
	"github.com/syndtr/goleveldb/leveldb/util"
)

func selectionRows(t *testing.T, db *leveldb.DB) int {
	t.Helper()
	iterator := db.NewIterator(util.BytesPrefix([]byte("sel/")), nil)
	defer iterator.Release()
	count := 0
	for iterator.Next() {
		count++
	}
	if iterator.Error() != nil {
		t.Fatal(iterator.Error())
	}
	return count
}

func selectionImage(t *testing.T, db *leveldb.DB) string {
	t.Helper()
	raw, err := db.Get([]byte("meta"), nil)
	if err != nil {
		t.Fatal(err)
	}
	image := append([]byte{}, raw...)
	iterator := db.NewIterator(util.BytesPrefix([]byte("sel/")), nil)
	defer iterator.Release()
	for iterator.Next() {
		image = append(image, iterator.Key()...)
		image = append(image, 0)
		image = append(image, iterator.Value()...)
		image = append(image, 0)
	}
	if iterator.Error() != nil {
		t.Fatal(iterator.Error())
	}
	return hashHex(image)
}

func TestDagSelectionKeepsOnlyUnselectedCatalogAcross129CommitsAndReopen(t *testing.T) {
	app, keys, root := dagLedgerFixture(t)
	store := app.store.(*dagStore)
	for i := 0; i < 129; i++ {
		commitPublicFixture(t, app, keys, i%6, 1)
		if len(store.candidates) != 0 || store.meta.SelectionIndex != 1 || store.meta.SelectedRecords != i+1 || store.meta.SelectedManifests != i+2 || selectionRows(t, store.db) != 2*(i+1)+1 {
			t.Fatal("selected history accumulated in the unselected RAM catalog or duplicated markers")
		}
	}
	candidate, _ := transitionCandidate(t, app, keys)
	if err := store.prepare(candidate); err != nil {
		t.Fatal(err)
	}
	if len(store.candidates) != 2 || store.meta.SelectedRecords != 129 || selectionRows(t, store.db) != 259 {
		t.Fatal("prepared data manufactured selection")
	}
	state := copyState(app.state)
	_ = app.Close()
	restored, err := newDagEnabledLedger(app.genesis, app.anchor, root, false)
	if err != nil {
		t.Fatal(err)
	}
	defer restored.Close()
	index := restored.store.(*dagStore)
	if len(index.candidates) != 2 || !bytes.Equal(canonical(state), canonical(restored.state)) || index.meta.SelectedRecords != 129 {
		t.Fatal("indexed startup retained historical selected keys or changed state")
	}
	if _, err = index.load(candidate.Commitment); err != nil {
		t.Fatal("unselected preparation was lost on reopen", err)
	}
	height := restored.state.Height + 1
	if _, err = restored.FinalizeBlock(context.Background(), &abci.RequestFinalizeBlock{Height: height, Time: time.Unix(1700000001+height, 0)}); err != nil {
		t.Fatal(err)
	}
	if _, err = restored.Commit(context.Background(), &abci.RequestCommit{}); err != nil {
		t.Fatal(err)
	}
	if len(index.candidates) != 0 || selectionRows(t, index.db) != 259 || *restored.state.DAG != *state.DAG {
		t.Fatal("empty height did not retire only losing preparations")
	}
	if _, err = index.load(candidate.Commitment); err == nil {
		t.Fatal("retired preparation stayed loadable")
	}
	t.Logf("GG_DAG_SELECTION_BOOKKEEPING selected_payloads=%d selected_manifests=%d candidate_RAM_keys=%d", index.meta.SelectedRecords, index.meta.SelectedManifests, len(index.candidates))
}

func TestDagSelectionCommitUnknownSyncKeepsOldMemoryAndExactPinnedDiskOutcome(t *testing.T) {
	for _, after := range []bool{false, true} {
		t.Run(map[bool]string{false: "before_sync", true: "lost_return_after_sync"}[after], func(t *testing.T) {
			app, keys, root := dagLedgerFixture(t)
			commitPublicFixture(t, app, keys, 0, 3)
			store := app.store.(*dagStore)
			candidate, batch := transitionCandidate(t, app, keys)
			wire := candidate.Manifest.Blocks[0]
			selectedBefore := store.meta.SelectedRecords
			if _, err := app.FinalizeBlock(context.Background(), &abci.RequestFinalizeBlock{Height: 2, Time: time.Unix(1700000003, 0), Txs: [][]byte{batch}}); err != nil {
				t.Fatal(err)
			}
			before := store.meta
			if before.SelectedRecords != selectedBefore {
				t.Fatal("payload preparation published selected counters")
			}
			pinned, err := store.db.GetSnapshot()
			if err != nil {
				t.Fatal(err)
			}
			defer pinned.Release()
			if _, found, err := readSelection(pinned, "r/"+wire); err != nil || found {
				t.Fatal("prepared object already marked selected")
			}
			write := store.write
			store.write = func(batch *leveldb.Batch) error {
				if after {
					if err := write(batch); err != nil {
						return err
					}
				}
				return errors.New("owned uncertain selection Sync")
			}
			if _, err = app.Commit(context.Background(), &abci.RequestCommit{}); err == nil || !store.failed || store.meta != before {
				t.Fatal("unknown completion published selected counters")
			}
			if _, found, err := readSelection(pinned, "r/"+wire); err != nil || found {
				t.Fatal("new selection changed a pinned old snapshot")
			}
			pinned.Release()
			_ = app.Close()
			restored, err := newDagEnabledLedger(app.genesis, app.anchor, root, false)
			if err != nil {
				t.Fatal(err)
			}
			defer restored.Close()
			index := restored.store.(*dagStore)
			want := before.SelectedRecords
			if after {
				want++
			}
			_, found, err := readSelection(index.db, "r/"+wire)
			if err != nil || found != after || index.meta.SelectedRecords != want || index.prefix.commitment != restored.dag.Commitment {
				t.Fatal("restart invented or lost the atomic selected outcome")
			}
		})
	}
}

func legacySelection(t *testing.T, store *dagStore) {
	t.Helper()
	batch := new(leveldb.Batch)
	iterator := store.db.NewIterator(util.BytesPrefix([]byte("sel/")), nil)
	for iterator.Next() {
		batch.Delete(append([]byte{}, iterator.Key()...))
	}
	err := iterator.Error()
	iterator.Release()
	if err != nil {
		t.Fatal(err)
	}
	meta := store.meta
	meta.SelectionIndex = 0
	meta.SelectedBytes = 0
	meta.SelectedRecords = 0
	meta.SelectedManifests = 0
	batch.Put([]byte("meta"), canonical(meta))
	if err = store.db.Write(batch, &opt.WriteOptions{Sync: true}); err != nil {
		t.Fatal(err)
	}
	store.meta = meta
}

func TestDagSelectionLegacyMigrationAuthenticatesHistoryAndHasOneAtomicOutcome(t *testing.T) {
	for _, after := range []bool{false, true} {
		t.Run(map[bool]string{false: "before_sync", true: "lost_return_after_sync"}[after], func(t *testing.T) {
			app, keys, root := dagLedgerFixture(t)
			for i := 0; i < 3; i++ {
				commitPublicFixture(t, app, keys, i, 1)
			}
			expected := copyState(app.state)
			legacySelection(t, app.store.(*dagStore))
			_ = app.Close()
			opened, err := newDagStore(app.dag.Source, app.anchor, root, false)
			if err != nil {
				t.Fatal(err)
			}
			if opened.retentionReady || selectionRows(t, opened.db) != 0 {
				t.Fatal("legacy store served before authentication")
			}
			var snapshots []dagPublicSnapshot
			execution, err := opened.replay(*expected.DAG, func(execution *DagExecution) { snapshots = append(snapshots, publicSnapshot(execution)) })
			if err != nil {
				t.Fatal(err)
			}
			write := opened.write
			writes := 0
			opened.write = func(batch *leveldb.Batch) error {
				writes++
				if after {
					if err := write(batch); err != nil {
						return err
					}
				}
				return errors.New("owned migration Sync outcome")
			}
			if err = opened.verifyOrMigratePublic(execution, snapshots); err == nil || writes != 1 || !opened.failed || opened.retentionReady || opened.meta.SelectionIndex != 0 {
				t.Fatal("migration published ambiguous readiness")
			}
			rows := selectionRows(t, opened.db)
			if after && rows != 7 || !after && rows != 0 {
				t.Fatal("partial membership migration")
			}
			_ = opened.close()
			restored, err := newDagEnabledLedger(app.genesis, app.anchor, root, false)
			if err != nil {
				t.Fatal(err)
			}
			defer restored.Close()
			index := restored.store.(*dagStore)
			if index.meta.SelectionIndex != 1 || index.meta.SelectedRecords != 3 || index.meta.SelectedManifests != 4 || len(index.candidates) != 0 || !bytes.Equal(canonical(expected), canonical(restored.state)) {
				t.Fatal("authenticated migration changed identity, nonces or selection")
			}
		})
	}
	t.Run("corrupt_original_payload", func(t *testing.T) {
		app, keys, root := dagLedgerFixture(t)
		commitPublicFixture(t, app, keys, 0, 1)
		store := app.store.(*dagStore)
		wire := app.dag.Manifest.Blocks[0]
		legacySelection(t, store)
		if err := store.db.Put([]byte("r/"+wire), []byte("owned changed original"), &opt.WriteOptions{Sync: true}); err != nil {
			t.Fatal(err)
		}
		before := selectionImage(t, store.db)
		_ = app.Close()
		if restored, err := newDagEnabledLedger(app.genesis, app.anchor, root, false); err == nil {
			restored.Close()
			t.Fatal("corrupt original payload gained selected markers")
		}
		db, err := leveldb.OpenFile(root+"/gg-dag-public.leveldb", nil)
		if err != nil {
			t.Fatal(err)
		}
		defer db.Close()
		if selectionImage(t, db) != before || selectionRows(t, db) != 0 {
			t.Fatal("failed authentication wrote a derived index")
		}
	})
}

func TestDagSelectionVersionedMissingChangedAndExtraMarkersAreNeverRepaired(t *testing.T) {
	modes := []string{"missing", "missing_compensated", "changed_size", "noncanonical", "string_size", "empty", "oversize", "unknown_version", "extra_unselected_compensated", "extra_unknown", "wrong_counter", "alien_kind", "legacy_flag_with_rows"}
	for _, mode := range modes {
		t.Run(mode, func(t *testing.T) {
			app, keys, root := dagLedgerFixture(t)
			commitPublicFixture(t, app, keys, 0, 1)
			commitPublicFixture(t, app, keys, 1, 2)
			store := app.store.(*dagStore)
			wire := app.dag.Manifest.Blocks[0]
			marker := selectionKey("r/" + wire)
			raw, err := store.db.Get([]byte("r/"+wire), nil)
			if err != nil {
				t.Fatal(err)
			}
			meta := store.meta
			batch := new(leveldb.Batch)
			switch mode {
			case "missing":
				batch.Delete([]byte(marker))
			case "missing_compensated":
				batch.Delete([]byte(marker))
				meta.SelectedRecords--
				meta.SelectedBytes -= uint64(len(raw))
			case "changed_size":
				batch.Put([]byte(marker), canonical(len(raw)+1))
			case "noncanonical":
				batch.Put([]byte(marker), []byte("01"))
			case "string_size":
				batch.Put([]byte(marker), []byte(`"12"`))
			case "empty":
				batch.Put([]byte(marker), nil)
			case "oversize":
				batch.Put([]byte(marker), canonical(DagMaxWire+1))
			case "unknown_version":
				meta.SelectionIndex = 2
			case "extra_unselected_compensated":
				candidate, _ := transitionCandidate(t, app, keys)
				if err := store.prepare(candidate); err != nil {
					t.Fatal(err)
				}
				meta = store.meta
				wire = candidate.Manifest.Blocks[0]
				blob, err := store.db.Get([]byte("r/"+wire), nil)
				if err != nil {
					t.Fatal(err)
				}
				batch.Put([]byte(selectionKey("r/"+wire)), canonical(len(blob)))
				meta.SelectedRecords++
				meta.SelectedBytes += uint64(len(blob))
			case "extra_unknown":
				batch.Put([]byte(selectionKey("r/"+strings.Repeat("f", 64))), canonical(12))
			case "wrong_counter":
				meta.SelectedBytes--
			case "alien_kind":
				batch.Put([]byte(selectionKey("x/"+strings.Repeat("f", 64))), canonical(12))
			case "legacy_flag_with_rows":
				meta.SelectionIndex = 0
				meta.SelectedRecords = 0
				meta.SelectedManifests = 0
				meta.SelectedBytes = 0
			}
			batch.Put([]byte("meta"), canonical(meta))
			if err = store.db.Write(batch, &opt.WriteOptions{Sync: true}); err != nil {
				t.Fatal(err)
			}
			before := selectionImage(t, store.db)
			_ = app.Close()
			if restored, err := newDagEnabledLedger(app.genesis, app.anchor, root, false); err == nil {
				restored.Close()
				t.Fatal("versioned bad selection index accepted", mode)
			}
			db, err := leveldb.OpenFile(root+"/gg-dag-public.leveldb", nil)
			if err != nil {
				t.Fatal(err)
			}
			defer db.Close()
			if selectionImage(t, db) != before {
				t.Fatal("bad versioned index was silently repaired", mode)
			}
		})
	}
}

func TestDagSelectionPinnedSDKReadCannotHoldCommitAndCloseDrainsCancelledReaders(t *testing.T) {
	for _, mode := range []string{"commit", "close"} {
		t.Run(mode, func(t *testing.T) {
			app, keys, _ := dagLedgerFixture(t)
			first := commitPublicFixture(t, app, keys, 0, 3)
			leaf := orderFixture(t, app.dag)[0]
			commitPublicFixture(t, app, keys, 1, 1)
			store := app.store.(*dagStore)
			store.payloadCache.clear()
			entered, release := make(chan struct{}), make(chan struct{})
			var once, safeRelease sync.Once
			unblock := func() { safeRelease.Do(func() { close(release) }) }
			defer unblock()
			store.beforeSelectionRead = func(string) { once.Do(func() { close(entered); <-release }) }
			creator := newLedgerClientCreator(app)
			query, err := creator.NewABCIClient()
			if err != nil {
				t.Fatal(err)
			}
			consensus, err := creator.NewABCIClient()
			if err != nil {
				t.Fatal(err)
			}
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			done := make(chan error, 1)
			go func() {
				response, err := query.Query(ctx, &abci.RequestQuery{Path: "/gg/dag/payload-chunk", Height: first.Height, Data: canonical(DagPayloadSelector{Hash: leaf.Hash, Index: 1})})
				if err == nil && response.Code != 0 {
					err = errors.New("owned query failed")
				}
				done <- err
			}()
			select {
			case <-entered:
			case <-time.After(2 * time.Second):
				t.Fatal("SDK reader never pinned selection snapshot")
			}
			if mode == "commit" {
				batch := dagBatchWire(t, app.dag, dagWire(t, app.dag, keys, 2, 1))
				committed := make(chan error, 1)
				go func() {
					_, err := consensus.FinalizeBlock(context.Background(), &abci.RequestFinalizeBlock{Height: 3, Time: time.Unix(1700000004, 0), Txs: [][]byte{batch}})
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
					t.Fatal("selection-reader IO held a consensus/store lock")
				}
				unblock()
				if err := <-done; err != nil {
					t.Fatal("old pinned payload read changed across commit", err)
				}
			} else {
				closed := make(chan error, 1)
				go func() { closed <- app.Close() }()
				select {
				case <-closed:
					t.Fatal("closed DB underneath pinned membership reader")
				case <-time.After(20 * time.Millisecond):
				}
				cancel()
				unblock()
				select {
				case err := <-done:
					if err == nil {
						t.Fatal("cancelled SDK read published payload")
					}
				case <-time.After(2 * time.Second):
					t.Fatal("cancelled reader did not drain")
				}
				select {
				case err := <-closed:
					if err != nil {
						t.Fatal(err)
					}
				case <-time.After(2 * time.Second):
					t.Fatal("Close did not drain selection reader")
				}
				if store.payloadReaders != 0 {
					t.Fatal("selection reader leaked its capacity")
				}
			}
		})
	}
}

func TestDagSelectionHotPayloadCacheCannotBypassMembershipAndUnselectedRequestsDoNotFault(t *testing.T) {
	for _, mode := range []string{"missing", "malformed", "changed_size", "unselected"} {
		t.Run(mode, func(t *testing.T) {
			app, keys, _ := dagLedgerFixture(t)
			commitPublicFixture(t, app, keys, 0, 1)
			store := app.store.(*dagStore)
			wire := app.dag.Manifest.Blocks[0]
			raw, err := store.db.Get([]byte("r/"+wire), nil)
			if err != nil {
				t.Fatal(err)
			}
			if mode == "unselected" {
				candidate, _ := transitionCandidate(t, app, keys)
				if err = store.prepare(candidate); err != nil {
					t.Fatal(err)
				}
				wire = candidate.Manifest.Blocks[0]
				raw, err = store.db.Get([]byte("r/"+wire), nil)
				if err != nil {
					t.Fatal(err)
				}
			}
			store.payloadCache.put(wire, append([]byte{}, raw...))
			if mode == "missing" {
				err = store.db.Delete([]byte(selectionKey("r/"+wire)), nil)
			}
			if mode == "malformed" {
				err = store.db.Put([]byte(selectionKey("r/"+wire)), []byte("not an index"), nil)
			}
			if mode == "changed_size" {
				err = store.db.Put([]byte(selectionKey("r/"+wire)), canonical(len(raw)+1), nil)
			}
			if err != nil {
				t.Fatal(err)
			}
			if returned, err := store.readPayload(context.Background(), wire, len(raw)); err == nil || returned != nil {
				t.Fatal("hot bytes bypassed membership")
			}
			if mode == "unselected" && store.metadataFault.Load() {
				t.Fatal("unselected request faulted valid storage")
			}
			if mode != "unselected" && !store.metadataFault.Load() {
				t.Fatal("damaged committed index did not latch local unavailability")
			}
		})
	}
}

type selectionFixtureReader map[string][]byte

func (reader selectionFixtureReader) Get(key []byte, _ *opt.ReadOptions) ([]byte, error) {
	raw, found := reader[string(key)]
	if !found {
		return nil, leveldb.ErrNotFound
	}
	return raw, nil
}

func TestDagSelectionStrictMarkerShapeAndFixedUnselectedCatalogBudget(t *testing.T) {
	key := "r/" + strings.Repeat("a", 64)
	for i, raw := range [][]byte{nil, []byte("0"), []byte("-1"), []byte("01"), []byte("1.0"), []byte("1e1"), []byte("true"), []byte(`"1"`), []byte("1 2"), []byte(" 1"), canonical(DagMaxWire + 1), []byte("99999999999999999")} {
		t.Run(fmt.Sprint(i), func(t *testing.T) {
			if _, _, err := readSelection(selectionFixtureReader{selectionKey(key): raw}, key); err == nil {
				t.Fatal("bad marker accepted")
			}
		})
	}
	if size, found, err := readSelection(selectionFixtureReader{selectionKey(key): canonical(12)}, key); err != nil || !found || size != 12 {
		t.Fatal("valid marker rejected")
	}
	store := &dagStore{candidates: map[string]uint64{}}
	for i := 0; i < dagCandidateCatalogRecords; i++ {
		store.candidates[fmt.Sprintf("r/%064x", i)] = 1
	}
	if store.candidateCacheBound() != nil {
		t.Fatal("fixed catalog boundary rejected")
	}
	store.candidates["r/overflow"] = 1
	if store.candidateCacheBound() == nil {
		t.Fatal("unselected catalog grew beyond its independent fixed bound")
	}
}
