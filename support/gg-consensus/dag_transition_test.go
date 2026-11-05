//go:build !js

package main

import (
	"context"
	"crypto/ed25519"
	"encoding/base64"
	"errors"
	"runtime"
	"strings"
	"testing"
	"time"

	abci "github.com/cometbft/cometbft/abci/types"
	"github.com/syndtr/goleveldb/leveldb"
)

func transitionCandidate(t *testing.T, app *Ledger, keys []ed25519.PrivateKey) (*DagExecution, []byte) {
	t.Helper()
	batch := dagBatchWire(t, app.dag, dagWire(t, app.dag, keys, 0, 1))
	next, err := applyDagBatch(app.dag, batch, time.Unix(1700000002+app.state.Height, 0).UnixNano())
	if err != nil {
		t.Fatal(err)
	}
	return next, batch
}

func TestDagTransitionEveryCommittedPrefixMatchesIndependentFullOracle(t *testing.T) {
	app, keys, _ := dagLedgerFixture(t)
	store := app.store.(*dagStore)
	for i := 0; i < 129; i++ {
		candidate, batch := transitionCandidate(t, app, keys)
		before := *store.prefix
		transition, err := store.validateTransition(candidate)
		order := orderFixture(t, candidate)
		if err != nil || !transition.selected || len(transition.leaves) != 1 || transition.leaves[0] != order[len(order)-1] ||
			store.validPublicOrder(order, publicSnapshot(candidate)) != nil || dagRoot(order[:len(order)-1], dagOrderDomain) != store.selected.OrderRoot || *store.prefix != before {
			t.Fatal("incremental result differs from independent full reference", i, err)
		}
		height := app.state.Height + 1
		if _, err = app.FinalizeBlock(context.Background(), &abci.RequestFinalizeBlock{Height: height, Time: time.Unix(1700000001+height, 0), Txs: [][]byte{batch}}); err != nil {
			t.Fatal(err)
		}
		if *store.prefix != before {
			t.Fatal("prepared candidate published a new prefix")
		}
		if _, err = app.Commit(context.Background(), &abci.RequestCommit{}); err != nil {
			t.Fatal(err)
		}
		if store.prefix.commitment != *app.state.DAG || store.prefix.historyRoot != store.meta.HistoryRoot || store.prefix.frontier.root() != app.state.DAG.OrderRoot {
			t.Fatal("Sync publication did not bind one exact prefix")
		}
	}
	if len(app.dag.pending) != 0 || app.dag.history.root.node != nil {
		t.Fatal("canonical prefix retained payload or complete metadata")
	}
}

// An independent owned test rewriter can create a malformed keyed history;
// production never allows replacement of an existing immutable entry.
func rewriteTransitionHistory(t *testing.T, execution *DagExecution, change func(*DagOrderLeaf, *dagHistoryRecord)) {
	t.Helper()
	order := orderFixture(t, execution)
	tree := dagHistory{}
	seen := map[string]bool{}
	for _, original := range order {
		stored := recordFixture(t, execution, original.Hash)
		leaf := original
		record := dagHistoryRecord{Hash: stored.Hash, Index: stored.Index, Rank: stored.Rank, WireBytes: stored.WireBytes, WireHash: stored.WireHash}
		change(&leaf, &record)
		var err error
		if !seen[record.Hash] {
			copy := record
			tree, err = tree.put("b/"+record.Hash, dagHistoryValue{Record: &copy})
			if err != nil {
				t.Fatal(err)
			}
			seen[record.Hash] = true
		}
		copy := leaf
		tree, err = tree.put(historyOrderKey(leaf.Index), dagHistoryValue{Order: &copy})
		if err != nil {
			t.Fatal(err)
		}
	}
	execution.history = tree
}

func TestDagTransitionRejectsIndependentOldHistoryNewMetadataAndCounterChanges(t *testing.T) {
	app, keys, _ := dagLedgerFixture(t)
	store := app.store.(*dagStore)
	for i := 0; i < 6; i++ {
		commitPublicFixture(t, app, keys, i, 1)
	}
	base, batch := transitionCandidate(t, app, keys)
	_ = batch
	for _, mode := range []string{"old-order", "old-record", "new-record", "frontier", "heads", "sequence", "nonce", "bytes", "account-nonce", "account-supply", "manifest-wire", "pending-raw", "attached-child", "missing-prefix", "wrong-prefix-root", "same-commitment-counters", "read-only-proof"} {
		t.Run(mode, func(t *testing.T) {
			candidate := base.clone()
			originalPrefix := store.prefix
			defer func() { store.prefix = originalPrefix }()
			switch mode {
			case "old-order":
				corruptOrderFixture(t, candidate, 0)
			case "old-record":
				rewriteTransitionHistory(t, candidate, func(leaf *DagOrderLeaf, record *dagHistoryRecord) {
					if leaf.Index == 1 {
						record.Rank++
					}
				})
			case "new-record":
				rewriteTransitionHistory(t, candidate, func(leaf *DagOrderLeaf, record *dagHistoryRecord) {
					if leaf.Index == candidate.Commitment.Blocks {
						record.Rank++
					}
				})
			case "frontier":
				candidate.orderRoot.peaks[0] = strings.Repeat("f", 64)
			case "heads":
				candidate.heads[0] = strings.Repeat("f", 64)
			case "sequence":
				candidate.sequences[0]++
			case "nonce":
				candidate.nonces[0]++
			case "bytes":
				candidate.bytes++
			case "account-nonce":
				candidate.Accounts[0].Nonce++
				candidate.seal()
			case "account-supply":
				candidate.Accounts[0].Balance = "0"
				candidate.seal()
			case "manifest-wire":
				candidate.Manifest.Blocks[0] = strings.Repeat("f", 64)
				candidate.seal()
			case "pending-raw":
				for hash, record := range candidate.pending {
					record.Raw = []byte("owned changed payload")
					candidate.pending[hash] = record
				}
			case "attached-child":
				// Keep the body and its cached hash intact but change the RAM edge.
				node := *candidate.history.root.node
				node.left = dagHistoryRef{hash: DagZero}
				candidate.history.root.node = &node
			case "missing-prefix":
				store.prefix = nil
			case "wrong-prefix-root":
				copy := *store.prefix
				copy.historyRoot = strings.Repeat("f", 64)
				store.prefix = &copy
			case "same-commitment-counters":
				candidate = app.dag.clone()
				candidate.sequences[0]++
			case "read-only-proof":
				candidate = proofFixture(t, candidate)
			}
			before := store.meta
			if err := store.prepare(candidate); err == nil || store.meta != before {
				t.Fatal("altered candidate was acknowledged or wrote metadata", mode, err)
			}
		})
	}
}

func TestDagTransitionPrefixNeverPublishesUnknownSyncOutcomeAndReopensExactly(t *testing.T) {
	for _, after := range []bool{false, true} {
		t.Run(map[bool]string{false: "before_sync", true: "lost_return_after_sync"}[after], func(t *testing.T) {
			app, keys, root := dagLedgerFixture(t)
			commitPublicFixture(t, app, keys, 0, 3)
			store := app.store.(*dagStore)
			old := *store.prefix
			candidate, batch := transitionCandidate(t, app, keys)
			if _, err := app.FinalizeBlock(context.Background(), &abci.RequestFinalizeBlock{Height: 2, Time: time.Unix(1700000003, 0), Txs: [][]byte{batch}}); err != nil {
				t.Fatal(err)
			}
			write := store.write
			store.write = func(batch *leveldb.Batch) error {
				if after {
					if err := write(batch); err != nil {
						return err
					}
				}
				return errors.New("owned unknown Sync completion")
			}
			if _, err := app.Commit(context.Background(), &abci.RequestCommit{}); err == nil || *store.prefix != old || !store.failed {
				t.Fatal("unknown Sync published prefix")
			}
			_ = app.Close()
			restored, err := newDagEnabledLedger(app.genesis, app.anchor, root, false)
			if err != nil {
				t.Fatal(err)
			}
			defer restored.Close()
			want := old.commitment
			if after {
				want = candidate.Commitment
			}
			prefix := restored.store.(*dagStore).prefix
			if prefix == nil || prefix.commitment != want || restored.dag.Commitment != want || prefix.historyRoot != restored.dag.history.root.id() {
				t.Fatal("reopen invented a prefix or rewound durable selection")
			}
		})
	}
}

func TestDagTransitionColdMaximumHistoryUsesOnlyChangedPathsAndBoundedSuffix(t *testing.T) {
	app, keys, _ := dagLedgerFixture(t)
	ctx := context.Background()
	for app.dag.Commitment.Blocks < DagMaxRecords-1 {
		base := app.dag
		builder := base.clone()
		wires := []string{}
		for len(wires) < DagMaxBatchBlocks && builder.orderCount() < DagMaxRecords-1 {
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
		batch := canonical(DagBatch{Blocks: wires, GenesisHash: app.anchor, Previous: base.Commitment.ManifestHash, Schema: "gg.dag.checkpoint.batch.v1", Sequence: base.Manifest.Checkpoint + 1})
		height := app.state.Height + 1
		if _, err := app.FinalizeBlock(ctx, &abci.RequestFinalizeBlock{Height: height, Time: time.Unix(1700000001+height, 0), Txs: [][]byte{batch}}); err != nil {
			t.Fatal(err)
		}
		if _, err := app.Commit(ctx, &abci.RequestCommit{}); err != nil {
			t.Fatal(err)
		}
	}
	candidate, _ := transitionCandidate(t, app, keys)
	store := app.store.(*dagStore)
	before := *store.prefix
	newObjects := 0
	if err := candidate.history.newNodes(map[string]bool{}, func(string, dagHistoryBody) error { newObjects++; return nil }); err != nil {
		t.Fatal(err)
	}
	reads := 0
	store.beforeHistoryRead = func(string) { reads++ }
	defer func() { store.beforeHistoryRead = nil }()
	measure := func(incremental bool) (uint64, int) {
		store.metadataCache.clear()
		runtime.GC()
		reads = 0
		var a, b runtime.MemStats
		runtime.ReadMemStats(&a)
		if incremental {
			transition, err := store.validateTransition(candidate)
			if err != nil || !transition.selected || len(transition.leaves) != 1 || cap(transition.leaves) != 1 {
				t.Fatal("unbounded suffix or invalid transition", err)
			}
		} else {
			order := orderFixture(t, candidate)
			if store.validPublicOrder(order, publicSnapshot(candidate)) != nil || dagRoot(order[:len(order)-1], dagOrderDomain) != store.selected.OrderRoot {
				t.Fatal("full oracle rejected valid candidate")
			}
		}
		runtime.ReadMemStats(&b)
		return b.TotalAlloc - a.TotalAlloc, reads
	}
	previous, oldReads := measure(false)
	current, newReads := measure(true)
	t.Logf("GG_DAG_TRANSITION_COST old_alloc=%d new_alloc=%d old_reads=%d new_reads=%d prefix=%d suffix=1 new_objects=%d", previous, current, oldReads, newReads, DagMaxRecords-1, newObjects)
	// The full oracle visits every order leaf, but path-copied candidate nodes
	// are already RAM objects. Only the other leaves necessarily require Get.
	if oldReads < candidate.orderCount()-newObjects || newReads > 512 || newReads*8 >= oldReads || current*2 >= previous || *store.prefix != before {
		t.Fatal("validation still scans/copies historical leaves or mutates committed prefix")
	}
}

func TestDagTransitionUntouchedDiskDamageIsNeverRepairedAndStopsOnAccessOrReopen(t *testing.T) {
	app, keys, root := dagLedgerFixture(t)
	for i := 0; i < 33; i++ {
		commitPublicFixture(t, app, keys, i%6, 1)
	}
	store := app.store.(*dagStore)
	candidate, _ := transitionCandidate(t, app, keys)
	current := map[string]dagHistoryBody{}
	var collect func(string)
	collect = func(hash string) {
		if hash == DagZero {
			return
		}
		body, err := store.readHistoryNode(hash)
		if err != nil {
			t.Fatal(err)
		}
		current[hash] = body
		collect(body.Left)
		collect(body.Right)
	}
	collect(store.meta.HistoryRoot)
	store.metadataCache.clear()
	touched := map[string]bool{}
	store.beforeHistoryRead = func(hash string) { touched[hash] = true }
	if _, err := store.validateTransition(candidate); err != nil {
		t.Fatal(err)
	}
	store.beforeHistoryRead = nil
	victim := ""
	for hash, body := range current {
		if !touched[hash] && strings.HasPrefix(body.Key, "o/") {
			victim = hash
			break
		}
	}
	if victim == "" {
		t.Fatal("fixture has no untouched historical leaf")
	}
	if err := store.db.Delete([]byte("hx/"+victim), nil); err != nil {
		t.Fatal(err)
	}
	store.metadataCache.clear()
	// Incremental validation is not a physical full-disk audit. It authenticates
	// the changed paths; accessing any damaged old node latches unavailability.
	if _, err := store.validateTransition(candidate); err != nil {
		t.Fatal("unrelated node was unexpectedly needed by the chosen paths", err)
	}
	store.metadataCache.clear()
	if _, err := store.readHistoryNode(victim); !errors.Is(err, errDagHistoryUnavailable) {
		t.Fatal("missing old node became authenticated absence")
	}
	if err := store.prepare(candidate); !errors.Is(err, errDagHistoryUnavailable) {
		t.Fatal("metadata fault did not stop future acknowledgements")
	}
	_ = app.Close()
	if reopened, err := newDagEnabledLedger(app.genesis, app.anchor, root, false); err == nil {
		reopened.Close()
		t.Fatal("damaged history was rebuilt or accepted on open")
	}
}
