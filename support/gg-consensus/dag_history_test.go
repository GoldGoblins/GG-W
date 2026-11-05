//go:build !js

package main

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"sync/atomic"
	"testing"
	"time"

	abci "github.com/cometbft/cometbft/abci/types"
	"github.com/syndtr/goleveldb/leveldb"
	"github.com/syndtr/goleveldb/leveldb/util"
)

func orderFixture(t *testing.T, execution *DagExecution) []DagOrderLeaf {
	t.Helper()
	order, err := execution.orderList()
	if err != nil {
		t.Fatal(err)
	}
	return order
}

// A test oracle owns its complete original leaf list before the storage it is
// comparing is closed or changed. It is explicitly a non-executable view.
func proofFixture(t *testing.T, execution *DagExecution) *DagExecution {
	t.Helper()
	view := execution.clone()
	view.proofOrder = orderFixture(t, execution)
	view.history = dagHistory{}
	view.pending = nil
	view.payloadReader = nil
	return view
}
func recordFixture(t *testing.T, execution *DagExecution, hash string) dagRecord {
	t.Helper()
	record, found, err := execution.historyRecord(hash)
	if err != nil || !found {
		t.Fatalf("missing fixture record: %v", err)
	}
	return record
}
func rankFixture(t *testing.T, execution *DagExecution, hash string) int64 {
	t.Helper()
	rank, found, err := execution.historyRank(hash)
	if err != nil || !found {
		t.Fatalf("missing fixture rank: %v", err)
	}
	return rank
}
func corruptOrderFixture(t *testing.T, execution *DagExecution, index int) {
	t.Helper()
	order := orderFixture(t, execution)
	order[index].Transactions++
	tree := dagHistory{}
	for _, leaf := range order {
		record := recordFixture(t, execution, leaf.Hash)
		info := dagHistoryRecord{Hash: record.Hash, Index: record.Index, Rank: record.Rank, WireBytes: record.WireBytes, WireHash: record.WireHash}
		var err error
		tree, err = tree.put("b/"+record.Hash, dagHistoryValue{Record: &info})
		if err != nil {
			t.Fatal(err)
		}
		copy := leaf
		tree, err = tree.put(historyOrderKey(leaf.Index), dagHistoryValue{Order: &copy})
		if err != nil {
			t.Fatal(err)
		}
	}
	execution.history = tree
}

func TestDagImmutableHistoryAVLIsolationAndAuthenticatedLazyLookup(t *testing.T) {
	tree := dagHistory{}
	roots := []dagHistory{}
	for i := 1; i <= 1024; i++ {
		leaf := DagOrderLeaf{Hash: fmt.Sprintf("%064x", i), Index: i, Producer: i % 6, Sequence: uint64(i), Transactions: 1}
		var err error
		tree, err = tree.put(historyOrderKey(i), dagHistoryValue{Order: &leaf})
		if err != nil {
			t.Fatal(err)
		}
		if i == 31 || i == 512 {
			roots = append(roots, tree)
		}
	}
	var validate func(dagHistoryRef, string, string) int
	validate = func(ref dagHistoryRef, low, high string) int {
		node, err := tree.load(ref)
		if err != nil {
			t.Fatal(err)
		}
		if node == nil {
			return 0
		}
		if node.body.Key <= low || node.body.Key >= high || !validHistoryBody(node.body) || historyDigest(node.body) != ref.id() {
			t.Fatal("noncanonical ordered tree")
		}
		a, b := validate(node.left, low, node.body.Key), validate(node.right, node.body.Key, high)
		maximum := a
		if b > maximum {
			maximum = b
		}
		if a-b > 1 || b-a > 1 || node.body.Height != maximum+1 {
			t.Fatal("unbalanced tree")
		}
		return maximum + 1
	}
	if validate(tree.root, "", "z") > 16 {
		t.Fatal("linear tree depth")
	}
	for i, old := range roots {
		bound := []int{31, 512}[i]
		if _, found, err := old.get(historyOrderKey(bound + 1)); found || err != nil {
			t.Fatal("candidate mutated old root")
		}
	}
	nodes := map[string]dagHistoryBody{}
	if err := tree.newNodes(map[string]bool{}, func(hash string, body dagHistoryBody) error { nodes[hash] = body; return nil }); err != nil {
		t.Fatal(err)
	}
	reads := 0
	disk := dagHistory{root: dagHistoryRef{hash: tree.root.id()}, read: func(hash string) (dagHistoryBody, error) { reads++; return nodes[hash], nil }}
	for _, i := range []int{1, 511, 1024, 1025} {
		reads = 0
		value, found, err := disk.get(historyOrderKey(i))
		if err != nil || found != (i <= 1024) || reads > 16 || found && value.Order.Index != i {
			t.Fatal("lazy lookup changed authenticated membership")
		}
	}
	delete(nodes, tree.root.id())
	if _, found, err := disk.get(historyOrderKey(1)); found || !errors.Is(err, errDagHistoryUnavailable) {
		t.Fatal("missing node became authenticated absence")
	}
}

func TestDagNativeMetadataArchivedRootReopensAndCloneSharesOnlyRoot(t *testing.T) {
	app, keys, root := dagLedgerFixture(t)
	for i := 0; i < 24; i++ {
		commitPublicFixture(t, app, keys, i%6, 1)
	}
	store := app.store.(*dagStore)
	if len(app.dag.pending) != 0 || app.dag.history.root.node != nil || store.meta.HistoryIndex != 1 || store.meta.HistoryNodes < 48 {
		t.Fatal("canonical history still resides in RAM")
	}
	before := app.dag.history.root.id()
	clone := app.dag.clone()
	if clone.history.root.id() != before || clone.history.root.node != nil || len(clone.pending) != 0 {
		t.Fatal("clone copied history")
	}
	store.metadataCache.clear()
	reads := 0
	store.beforeHistoryRead = func(string) { reads++ }
	leaf := orderFixture(t, app.dag)[0]
	store.metadataCache.clear()
	reads = 0
	record := recordFixture(t, app.dag, leaf.Hash)
	if record.Index != 1 || reads < 1 || reads > 32 {
		t.Fatal("metadata lookup did not use bounded disk path")
	}
	state := copyState(app.state)
	app.Close()
	restored, err := newDagEnabledLedger(app.genesis, app.anchor, root, false)
	if err != nil {
		t.Fatal(err)
	}
	defer restored.Close()
	if !bytes.Equal(canonical(state), canonical(restored.state)) || restored.dag.history.root.id() != before || restored.dag.history.root.node != nil {
		t.Fatal("replayed metadata/state changed")
	}
	commitPublicFixture(t, restored, keys, 0, 1)
}

func TestDagMissingLocalMetadataReturnsUnavailableInsteadOfConsensusReject(t *testing.T) {
	app, keys, _ := dagLedgerFixture(t)
	commitPublicFixture(t, app, keys, 0, 1)
	raw := dagBatchWire(t, app.dag, dagWire(t, app.dag, keys, 1, 1))
	store := app.store.(*dagStore)
	hash := app.dag.history.root.id()
	if err := store.db.Delete([]byte("hx/"+hash), nil); err != nil {
		t.Fatal(err)
	}
	store.metadataCache.clear()
	response, err := app.ProcessProposal(context.Background(), &abci.RequestProcessProposal{Height: 2, Time: time.Unix(1700000003, 0), Txs: [][]byte{raw}})
	if response != nil || !errors.Is(err, errDagHistoryUnavailable) {
		t.Fatalf("local metadata failure became protocol verdict: %v %v", response, err)
	}
	if !errors.Is(store.health(), errDagHistoryUnavailable) {
		t.Fatal("metadata fault did not latch")
	}
}

func TestDagMetadataSlowLookupDoesNotHoldConsensusMutex(t *testing.T) {
	app, keys, _ := dagLedgerFixture(t)
	first := commitPublicFixture(t, app, keys, 0, 1)
	leaf := orderFixture(t, app.dag)[0]
	store := app.store.(*dagStore)
	store.metadataCache.clear()
	entered, release := make(chan struct{}), make(chan struct{})
	var used atomic.Bool
	store.beforeHistoryRead = func(string) {
		if used.CompareAndSwap(false, true) {
			close(entered)
			<-release
		}
	}
	released := false
	defer func() {
		if !released {
			close(release)
		}
	}()
	creator := newLedgerClientCreator(app)
	query, err := creator.NewABCIClient()
	if err != nil {
		t.Fatal(err)
	}
	consensus, err := creator.NewABCIClient()
	if err != nil {
		t.Fatal(err)
	}
	done := make(chan error, 1)
	go func() {
		response, err := query.Query(context.Background(), &abci.RequestQuery{Path: "/gg/dag/payload-chunk", Height: first.Height, Data: canonical(DagPayloadSelector{Hash: leaf.Hash, Index: 1})})
		if err == nil && response.Code != 0 {
			err = errors.New(response.Log)
		}
		done <- err
	}()
	select {
	case <-entered:
	case <-time.After(2 * time.Second):
		t.Fatal("query did not reach metadata IO")
	}
	committed := make(chan error, 1)
	batch := dagBatchWire(t, app.dag, dagWire(t, app.dag, keys, 1, 1))
	go func() {
		_, err := consensus.FinalizeBlock(context.Background(), &abci.RequestFinalizeBlock{Height: 2, Time: time.Unix(1700000003, 0), Txs: [][]byte{batch}})
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
		t.Fatal("metadata IO held consensus mutex")
	}
	close(release)
	released = true
	select {
	case err := <-done:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("old query did not recover its immutable metadata")
	}
}

func legacyMetadataFixture(t *testing.T, store *dagStore) {
	t.Helper()
	batch := new(leveldb.Batch)
	iterator := store.db.NewIterator(util.BytesPrefix([]byte("hx/")), nil)
	for iterator.Next() {
		batch.Delete(append([]byte(nil), iterator.Key()...))
	}
	if iterator.Error() != nil {
		t.Fatal(iterator.Error())
	}
	iterator.Release()
	meta := store.meta
	meta.HistoryIndex = 0
	meta.HistoryRoot = ""
	meta.HistoryNodes = 0
	meta.HistoryBytes = 0
	batch.Put([]byte("meta"), canonical(meta))
	if store.write(batch) != nil {
		t.Fatal("legacy fixture write")
	}
	store.meta = meta
	store.metadataPersisted.Store(false)
	store.metadataCache.clear()
}

func TestDagMetadataLegacyMigrationReplaysSignedHistoryAtomically(t *testing.T) {
	for _, kind := range []string{"normal", "before-sync", "after-sync"} {
		t.Run(kind, func(t *testing.T) {
			app, keys, root := dagLedgerFixture(t)
			for i := 0; i < 9; i++ {
				commitPublicFixture(t, app, keys, i%6, 2)
			}
			state := copyState(app.state)
			originalRoot := app.dag.history.root.id()
			legacyMetadataFixture(t, app.store.(*dagStore))
			app.Close()
			if kind != "normal" {
				store, err := newDagStore(*app.genesis.DAG, app.anchor, root, false)
				if err != nil {
					t.Fatal(err)
				}
				var snapshots []dagPublicSnapshot
				execution, err := store.replay(*state.DAG, func(value *DagExecution) { snapshots = append(snapshots, publicSnapshot(value)) })
				if err != nil {
					store.close()
					t.Fatal(err)
				}
				write := store.write
				store.write = func(batch *leveldb.Batch) error {
					if kind == "after-sync" {
						if err := write(batch); err != nil {
							return err
						}
					}
					return errors.New("owned metadata Sync failure")
				}
				if store.verifyOrMigratePublic(execution, snapshots) == nil || !store.failed {
					store.close()
					t.Fatal("unknown migration completion was published")
				}
				store.close()
				check, err := newDagStore(*app.genesis.DAG, app.anchor, root, false)
				if err != nil {
					t.Fatal(err)
				}
				want := 0
				if kind == "after-sync" {
					want = 1
				}
				if check.meta.HistoryIndex != want {
					check.close()
					t.Fatal("migration root/nodes were partially committed")
				}
				check.close()
			}
			restored, err := newDagEnabledLedger(app.genesis, app.anchor, root, false)
			if err != nil {
				t.Fatal(err)
			}
			defer restored.Close()
			store := restored.store.(*dagStore)
			if store.meta.HistoryIndex != 1 || store.meta.HistoryRoot != originalRoot || restored.dag.history.root.node != nil || !bytes.Equal(canonical(state), canonical(restored.state)) {
				t.Fatal("migration changed authenticated execution")
			}
			commitPublicFixture(t, restored, keys, 2, 1)
		})
	}
}

func TestDagVersionedMetadataMissingChangedExtraAndWrongRootAreNeverRepaired(t *testing.T) {
	for _, kind := range []string{"missing", "changed", "extra", "root"} {
		t.Run(kind, func(t *testing.T) {
			app, keys, root := dagLedgerFixture(t)
			for i := 0; i < 5; i++ {
				commitPublicFixture(t, app, keys, i%6, 1)
			}
			store := app.store.(*dagStore)
			meta := store.meta
			batch := new(leveldb.Batch)
			key := "hx/" + meta.HistoryRoot
			raw, err := store.db.Get([]byte(key), nil)
			if err != nil {
				t.Fatal(err)
			}
			switch kind {
			case "missing":
				batch.Delete([]byte(key))
				meta.HistoryNodes--
				meta.HistoryBytes -= uint64(len(key) + len(raw))
			case "changed":
				body, err := decodeHistoryNode(meta.HistoryRoot, raw)
				if err != nil {
					t.Fatal(err)
				}
				body.Height++
				changed := canonical(body)
				batch.Put([]byte(key), changed)
				meta.HistoryBytes = meta.HistoryBytes - uint64(len(raw)) + uint64(len(changed))
			case "extra":
				leaf := DagOrderLeaf{Hash: fmt.Sprintf("%064x", 91), Index: 1, Producer: 0, Sequence: 1, Transactions: 1}
				tree, err := (dagHistory{}).put(historyOrderKey(1), dagHistoryValue{Order: &leaf})
				if err != nil {
					t.Fatal(err)
				}
				extra := canonical(tree.root.node.body)
				batch.Put([]byte("hx/"+tree.root.id()), extra)
				meta.HistoryNodes++
				meta.HistoryBytes += uint64(67 + len(extra))
			case "root":
				meta.HistoryRoot = fmt.Sprintf("%064x", 92)
			}
			batch.Put([]byte("meta"), canonical(meta))
			if store.write(batch) != nil {
				t.Fatal("corruption fixture")
			}
			app.Close()
			if restored, err := newDagEnabledLedger(app.genesis, app.anchor, root, false); err == nil {
				restored.Close()
				t.Fatal("versioned corruption was accepted or repaired")
			}
			// Failed startup must leave the exact persisted corruption untouched.
			db, err := leveldb.OpenFile(root+"/gg-dag-public.leveldb", nil)
			if err != nil {
				t.Fatal(err)
			}
			defer db.Close()
			actual, err := db.Get([]byte("meta"), nil)
			if err != nil || !bytes.Equal(actual, canonical(meta)) {
				t.Fatal("failed startup silently changed metadata")
			}
		})
	}
}

func TestDagMetadataCacheHasFixedEntryBound(t *testing.T) {
	cache := dagMetadataCache{}
	for i := 1; i <= 2*dagMetadataCacheNodes; i++ {
		leaf := DagOrderLeaf{Hash: fmt.Sprintf("%064x", i), Index: i, Producer: 0, Sequence: 1, Transactions: 0}
		tree, err := (dagHistory{}).put(historyOrderKey(i), dagHistoryValue{Order: &leaf})
		if err != nil {
			t.Fatal(err)
		}
		cache.put(tree.root.id(), tree.root.node.body)
	}
	if len(cache.entries) != dagMetadataCacheNodes || len(cache.order) != dagMetadataCacheNodes {
		t.Fatal("metadata cache grew with history")
	}
	cache.clear()
	if len(cache.entries) != 0 || len(cache.order) != 0 {
		t.Fatal("metadata cache was retained after close")
	}
}

func TestDagMetadataCloseDrainsInFlightReadsAndRejectsNewOnes(t *testing.T) {
	app, keys, _ := dagLedgerFixture(t)
	commitPublicFixture(t, app, keys, 0, 1)
	store := app.store.(*dagStore)
	hash := app.dag.history.root.id()
	store.metadataCache.clear()
	entered, release := make(chan struct{}), make(chan struct{})
	var first atomic.Bool
	store.beforeHistoryRead = func(string) {
		if first.CompareAndSwap(false, true) {
			close(entered)
			<-release
		}
	}
	released := false
	defer func() {
		if !released {
			close(release)
		}
	}()
	readDone := make(chan error, 1)
	go func() { _, err := store.readHistoryNode(hash); readDone <- err }()
	select {
	case <-entered:
	case <-time.After(2 * time.Second):
		t.Fatal("metadata read did not start")
	}
	closeDone := make(chan error, 1)
	go func() { closeDone <- store.close() }()
	deadline := time.After(2 * time.Second)
	for !store.metadataClosed.Load() {
		select {
		case <-deadline:
			t.Fatal("close admitted new readers")
		default:
			time.Sleep(time.Millisecond)
		}
	}
	if _, err := store.readHistoryNode(hash); !errors.Is(err, errDagHistoryUnavailable) {
		t.Fatal("closing store admitted new metadata read")
	}
	select {
	case <-closeDone:
		t.Fatal("DB closed underneath metadata IO")
	default:
	}
	close(release)
	released = true
	select {
	case err := <-readDone:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("in-flight metadata read did not complete")
	}
	select {
	case err := <-closeDone:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("metadata close did not drain")
	}
	if _, err := store.readHistoryNode(hash); !errors.Is(err, errDagHistoryUnavailable) {
		t.Fatal("closed store served cached metadata")
	}
}
