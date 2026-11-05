//go:build !js

package main

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"encoding/json"
	"errors"
	abci "github.com/cometbft/cometbft/abci/types"
	"github.com/syndtr/goleveldb/leveldb"
	"os"
	"path/filepath"
	"strconv"
	"testing"
	"time"
)

func financialLineageSDKFixture(t *testing.T) (*Ledger, *financialNativeApplication, []ed25519.PrivateKey, []ed25519.PrivateKey, string) {
	t.Helper()
	model, accounts, producers := financialLineageFixture(t)
	root := t.TempDir()
	app, err := newFinancialLedger(model.genesis, model.anchor, root, true)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = app.Close() })
	return app, app.financial.(*financialNativeApplication), accounts, producers, root
}

func TestFinancialLineageStoreColdReopenRetainsOldParentsAndNoTreeInRAM(t *testing.T) {
	app, backend, accounts, keys, root := financialLineageSDKFixture(t)
	raw, id := financialLineageBlock(t, backend.current, keys, 0, [][]byte{testTx(app.genesis, app.anchor, accounts, 0, 1, "1", 0)}, nil)
	commitFinancialSDK(t, app, financialDagBatchWire(t, backend.current, raw))
	old, _ := financialLineageBlock(t, backend.current, keys, 0, [][]byte{testTx(app.genesis, app.anchor, accounts, 0, 1, "1", 1)}, nil)
	for turn := 0; turn < 3; turn++ {
		fast, _ := financialLineageBlock(t, backend.current, keys, 1, [][]byte{testTx(app.genesis, app.anchor, accounts, 1, 2, "1", uint64(turn))}, nil)
		commitFinancialSDK(t, app, financialDagBatchWire(t, backend.current, fast))
		cut, err := backend.current.prepareCut()
		if err != nil {
			t.Fatal(err)
		}
		commitFinancialSDK(t, app, cut)
	}
	if backend.current.lineage.root.node != nil || backend.current.lineage.read == nil {
		t.Fatal("committed global topology retained in RAM")
	}
	before := canonical(app.state)
	retained := backend.current.lineage
	if _, exists, err := retained.get("b/" + id); err != nil || !exists {
		t.Fatal("lost selected parent", err)
	}
	if err := app.Close(); err != nil {
		t.Fatal(err)
	}
	if _, _, err := retained.get("b/" + id); err == nil {
		t.Fatal("cache bypassed closed store lifetime")
	}
	reopened, err := newFinancialLedger(app.genesis, app.anchor, root, false)
	if err != nil {
		t.Fatal(err)
	}
	defer reopened.Close()
	if !bytes.Equal(before, canonical(reopened.state)) {
		t.Fatal("cold state changed")
	}
	backend = reopened.financial.(*financialNativeApplication)
	if backend.current.lineage.root.node != nil || len(backend.store.lineageCache.entries) > dagMetadataCacheNodes {
		t.Fatal("unbounded lineage memory")
	}
	proof, err := backend.ProducerContext(context.Background(), reopened.state, 0)
	if err != nil || proof.Parent != id || len(proof.ParentPath) == 0 || proof.ParentRank != 1 {
		t.Fatal("cold old-parent witness unavailable", err)
	}
	commitFinancialSDK(t, reopened, financialDagBatchWire(t, backend.current, old))
	if backend.current.applied != 5 || backend.current.authors[0].Epoch != "1" {
		t.Fatal("exact delayed original could not follow restored parent")
	}
}

func TestFinancialLineageStoreMissingOrCorruptDerivedNodeIsNotRepaired(t *testing.T) {
	for _, kind := range []string{"missing", "corrupt", "extra"} {
		t.Run(kind, func(t *testing.T) {
			app, backend, accounts, keys, root := financialLineageSDKFixture(t)
			raw, _ := financialLineageBlock(t, backend.current, keys, 0, [][]byte{testTx(app.genesis, app.anchor, accounts, 0, 1, "1", 0)}, nil)
			commitFinancialSDK(t, app, financialDagBatchWire(t, backend.current, raw))
			key := financialLineagePrefix + app.state.FinancialDAG.LineageRoot
			if err := app.Close(); err != nil {
				t.Fatal(err)
			}
			db, err := leveldb.OpenFile(filepath.Join(root, "gg-financial-dag.leveldb"), nil)
			if err != nil {
				t.Fatal(err)
			}
			var changed []byte
			if kind == "extra" {
				original, readErr := db.Get([]byte(key), nil)
				if readErr != nil {
					t.Fatal(readErr)
				}
				var body dagHistoryBody
				if decodeStrict(original, &body) != nil {
					t.Fatal("fixture node")
				}
				body.Value.Record.WireBytes++
				changed = canonical(body)
				key = financialLineagePrefix + historyDigest(body)
				err = db.Put([]byte(key), changed, nil)
			} else if kind == "missing" {
				err = db.Delete([]byte(key), nil)
			} else {
				changed = []byte("corrupt owned lineage node")
				err = db.Put([]byte(key), changed, nil)
			}
			if err != nil {
				t.Fatal(err)
			}
			if err = db.Close(); err != nil {
				t.Fatal(err)
			}
			reopened, err := newFinancialLedger(app.genesis, app.anchor, root, false)
			if err == nil {
				_ = reopened.Close()
				t.Fatal("missing/corrupt indexed history adopted")
			}
			db, err = leveldb.OpenFile(filepath.Join(root, "gg-financial-dag.leveldb"), nil)
			if err != nil {
				t.Fatal(err)
			}
			defer db.Close()
			saved, readErr := db.Get([]byte(key), nil)
			if kind == "missing" && readErr != leveldb.ErrNotFound || kind != "missing" && (readErr != nil || !bytes.Equal(saved, changed)) {
				t.Fatal("cold failure repaired evidence")
			}
		})
	}
}

func TestFinancialLineageStoreUncertainCommitRecoversExactOldOrNewRoot(t *testing.T) {
	for _, durable := range []bool{false, true} {
		t.Run(strconv.FormatBool(durable), func(t *testing.T) {
			app, backend, accounts, keys, root := financialLineageSDKFixture(t)
			before := canonical(app.state)
			block, _ := financialLineageBlock(t, backend.current, keys, 0, [][]byte{testTx(app.genesis, app.anchor, accounts, 0, 1, "1", 0)}, nil)
			raw := financialDagBatchWire(t, backend.current, block)
			_, err := app.FinalizeBlock(context.Background(), &abci.RequestFinalizeBlock{Height: 1, Time: time.Unix(0, backend.store.timeNs+1000000), Txs: [][]byte{raw}})
			if err != nil {
				t.Fatal(err)
			}
			after := canonical(*app.staged)
			write := backend.store.write
			backend.store.write = func(batch *leveldb.Batch) error {
				if durable {
					if err := write(batch); err != nil {
						return err
					}
				}
				return errors.New("owned uncertain lineage IO")
			}
			if _, err = app.Commit(context.Background(), &abci.RequestCommit{}); err == nil || !bytes.Equal(before, canonical(app.state)) || backend.store.health() == nil {
				t.Fatal("uncertain root was published or stayed usable")
			}
			_ = app.Close()
			reopened, err := newFinancialLedger(app.genesis, app.anchor, root, false)
			if err != nil {
				t.Fatal(err)
			}
			defer reopened.Close()
			expected := before
			if durable {
				expected = after
			}
			if !bytes.Equal(expected, canonical(reopened.state)) {
				t.Fatal("partial lineage/journal commit recovered")
			}
			if reopened.financial.(*financialNativeApplication).current.lineage.root.node != nil {
				t.Fatal("reopened root retained full tree")
			}
		})
	}
}

func TestFinancialLineageArchiveScratchIsIndexedBoundedAndCleaned(t *testing.T) {
	model, accounts, keys := financialLineageFixture(t)
	cursor, err := newFinancialArchiveReplay(model.genesis, model.anchor)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = cursor.close() })
	scratch := cursor.lineageScratch
	if scratch == nil {
		t.Fatal("archive replay omitted scratch index")
	}
	privateRoot := scratch.root
	for number := 0; number < 1050; number++ {
		raw, _ := financialLineageBlock(t, cursor.execution, keys, 0, [][]byte{testTx(model.genesis, model.anchor, accounts, 0, 1, "1", uint64(number))}, nil)
		transaction := financialDagBatchWire(t, cursor.execution, raw)
		when := cursor.when + 1000000
		next, err := cursor.execution.applyBatch(context.Background(), transaction, when)
		if err != nil {
			t.Fatal(err)
		}
		state, err := financialNativeState(cursor.state, next, cursor.state.Height+1)
		if err != nil {
			t.Fatal(err)
		}
		entry := financialJournalEntry{After: state.StateRoot, Height: state.Height, Previous: cursor.journal, Schema: "gg.financial-dag.journal-entry.v1", TimeNs: strconv.FormatInt(when, 10), Transaction: json.RawMessage(transaction)}
		if _, err = cursor.apply(context.Background(), canonical(entry)); err != nil {
			t.Fatal(err)
		}
		nodes := 0
		err = cursor.execution.lineage.newNodes(map[string]bool{}, func(string, dagHistoryBody) error { nodes++; return nil })
		if err != nil || nodes > 128 || len(scratch.cache.entries) > dagMetadataCacheNodes {
			t.Fatal("archive retained more than bounded checkpoint delta/cache", err, nodes)
		}
	}
	freezeFinancialLineage(cursor.execution, scratch.read)
	if cursor.execution.lineage.root.node != nil || cursor.execution.applied != 1050 {
		t.Fatal("scratch altered execution")
	}
	retained := cursor.execution.lineage
	if err = cursor.close(); err != nil {
		t.Fatal(err)
	}
	if _, err = os.Stat(privateRoot); !os.IsNotExist(err) {
		t.Fatal("private scratch directory remained", err)
	}
	if _, _, err = retained.get("b/" + cursor.execution.authors[0].Head); err == nil {
		t.Fatal("closed scratch accepted cached parent")
	}
}
