//go:build !js

package main

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"

	abci "github.com/cometbft/cometbft/abci/types"
	"github.com/syndtr/goleveldb/leveldb"
)

func TestDagClosedTreePathMatchesActualAccumulatorAtOddAndPeakBoundaries(t *testing.T) {
	tree := dagClosedSegments{}
	nodes := map[string][]byte{}
	cuts := []string{}
	for count := uint64(1); count <= 129; count++ {
		hash := hashHex([]byte("public closed cut " + strconv.FormatUint(count, 10)))
		value := dagDigest(dagClosedSegmentDomain+"L\x00", hash)
		for level := 0; level < 63; level++ {
			nodes[closedNodeKey(level, tree.count>>level)] = []byte(value)
			if tree.count&(uint64(1)<<level) == 0 {
				break
			}
			value = closedSegmentJoin(tree.peaks[level], value)
		}
		if err := tree.append(hash); err != nil {
			t.Fatal(err)
		}
		cuts = append(cuts, hash)
		root, _ := tree.root()
		for epoch := uint64(1); epoch <= count; epoch++ {
			reads := 0
			path, err := closedTreePath(context.Background(), epoch, count, func(key string) ([]byte, error) {
				reads++
				raw, ok := nodes[key]
				if !ok {
					return nil, errors.New("missing actual tree node")
				}
				return raw, nil
			})
			if err != nil || reads > 128 || verifyClosedCutPath(cuts[epoch-1], path, epoch, count, root) != nil {
				t.Fatal("accumulator/path disagreement", count, epoch, reads, err)
			}
		}
	}
}

func TestDagClosedTreeGlobalCountUsesUint64WithoutWASMNarrowing(t *testing.T) {
	// Arithmetic-only witness with opaque complete-subtree digests; this is
	// not a claim to have generated or SDK-selected 2^62 original segments.
	count := uint64(1)<<62 + 3
	epoch := count
	hash := hashHex([]byte("public large-count cut"))
	leaf := dagDigest(dagClosedSegmentDomain+"L\x00", hash)
	path, err := closedTreePath(context.Background(), epoch, count, func(key string) ([]byte, error) {
		if key == closedNodeKey(0, count-1) {
			return []byte(leaf), nil
		}
		return []byte(hashHex([]byte(key))), nil
	})
	if err != nil {
		t.Fatal(err)
	}
	value, at := leaf, epoch-1
	for _, step := range path {
		if at&1 == 1 {
			value = closedSegmentJoin(step.Hash, value)
		} else {
			value = closedSegmentJoin(value, step.Hash)
		}
		at /= 2
	}
	if verifyClosedCutPath(hash, path, epoch, count, value) != nil {
		t.Fatal("global count narrowed")
	}
	bad := append([]PathItem{}, path...)
	bad[0].Hash = hashHex([]byte("wrong duplicate"))
	if verifyClosedCutPath(hash, bad, epoch, count, value) == nil {
		t.Fatal("odd-duplicate witness accepted")
	}
}

func closedSDKFixture(t *testing.T) (*Ledger, *dagSegmentedNativeApplication, string, [][]byte) {
	t.Helper()
	app, backend, keys, root := segmentedSDKFixture(t)
	wires := [][]byte{}
	for epoch := 1; epoch <= 3; epoch++ {
		count := epoch
		if epoch == 1 {
			count = 5000
		}
		wire := segmentedWire(t, backend.current.active, keys, epoch-1, count)
		wires = append(wires, wire)
		commitSegmentedSDK(t, app, segmentedBatch(t, backend.current.active, wire))
		if epoch == 1 {
			child := segmentedWire(t, backend.current.active, keys, 0, 1)
			commitSegmentedSDK(t, app, segmentedBatch(t, backend.current.active, child))
		}
		cut, err := backend.current.cutTransaction()
		if err != nil {
			t.Fatal(err)
		}
		commitSegmentedSDK(t, app, canonical(cut))
	}
	wire := segmentedWire(t, backend.current.active, keys, 0, 1)
	commitSegmentedSDK(t, app, segmentedBatch(t, backend.current.active, wire))
	return app, backend, root, wires
}

func closedPagePacket(t *testing.T, app *Ledger, epoch string) VerifyInput {
	t.Helper()
	response, err := app.Query(context.Background(), &abci.RequestQuery{Path: "/gg/dag/closed-page", Height: app.state.Height, Data: canonical(dagClosedSelector{Epoch: epoch})})
	if err != nil || response.Code != 0 || len(response.Value) > 65536 {
		t.Fatal("actual closed page", err, response)
	}
	page := &dagSegmentedClosedPage{}
	if decodeStrict(response.Value, page) != nil {
		t.Fatal("page encoding")
	}
	packet := segmentedSDKPacket(t, app)
	packet.DAGSegmentedClosedPage = page
	if _, err := verifyInput(packet); err != nil {
		t.Fatal("actual SDK closed proof", err)
	}
	return packet
}

func TestDagClosedActual5000TXOriginalAfterThreeCutsAndRestart(t *testing.T) {
	app, backend, root, wires := closedSDKFixture(t)
	packets := map[string]VerifyInput{}
	for epoch := 1; epoch <= 3; epoch++ {
		packets[strconv.Itoa(epoch)] = closedPagePacket(t, app, strconv.Itoa(epoch))
	}
	leaf := packets["1"].DAGSegmentedClosedPage.Items[0].Leaf
	var recovered []byte
	for offset := 0; offset < len(wires[0]); offset += DagPayloadChunkBytes {
		response, err := app.Query(context.Background(), &abci.RequestQuery{Path: "/gg/dag/closed-payload-chunk", Height: app.state.Height,
			Data: canonical(dagClosedPayloadSelector{Epoch: "1", Hash: leaf.Hash, Index: leaf.Index, Offset: offset})})
		var chunk dagClosedPayloadChunk
		if err != nil || response.Code != 0 || decodeStrict(response.Value, &chunk) != nil || len(response.Value) > 65536 || chunk.Epoch != "1" || chunk.Hash != leaf.Hash || chunk.Offset != offset || chunk.Total != len(wires[0]) || chunk.WireHash != hashHex(wires[0]) || chunk.Height != app.state.Height || chunk.StateRoot != app.state.StateRoot {
			t.Fatal("closed selected chunk", err, response)
		}
		part, err := base64.StdEncoding.DecodeString(chunk.Data)
		if err != nil || len(part) != min(DagPayloadChunkBytes, len(wires[0])-offset) {
			t.Fatal("chunk bound")
		}
		recovered = append(recovered, part...)
	}
	if !bytes.Equal(recovered, wires[0]) {
		t.Fatal("cold original changed")
	}
	if len(backend.store.proofViews) != dagSegmentProofViews {
		t.Fatal("fixture did not exceed active proof view retention")
	}
	if path := os.Getenv("GG_PUBLIC_SEGMENTED_CLOSED_FIXTURE"); path != "" {
		value := map[string]any{"packets": packets, "first_original": base64.StdEncoding.EncodeToString(wires[0])}
		if err := os.WriteFile(path, canonical(value), 0600); err != nil {
			t.Fatal(err)
		}
	}
	if err := app.Close(); err != nil {
		t.Fatal(err)
	}
	restored, err := newDagEnabledLedger(app.genesis, app.anchor, root, false)
	if err != nil {
		t.Fatal("original-derived index restart", err)
	}
	defer restored.Close()
	again := closedPagePacket(t, restored, "1")
	if !bytes.Equal(canonical(again.DAGSegmentedClosedPage), canonical(packets["1"].DAGSegmentedClosedPage)) {
		t.Fatal("restart changed proof context")
	}
}

func TestDagClosedManipulatedProofsNeverVerify(t *testing.T) {
	app, _, _, _ := closedSDKFixture(t)
	packet := closedPagePacket(t, app, "1")
	for _, kind := range []string{"cut_epoch", "cut_accounts", "cut_missing", "cut_extra_account", "closed_hash", "closed_side", "closed_missing", "closed_extra", "leaf_hash", "leaf_creator", "leaf_global", "leaf_sequence", "leaf_index", "order_hash", "order_side", "start", "complete", "height", "state_root", "anchor", "commitment_epoch"} {
		t.Run(kind, func(t *testing.T) {
			var bad VerifyInput
			if decodeStrict(canonical(packet), &bad) != nil {
				t.Fatal("fixture")
			}
			page := bad.DAGSegmentedClosedPage
			switch kind {
			case "cut_epoch", "cut_accounts":
				var cut dagHistoryCutBody
				_ = decodeStrict(page.Cut, &cut)
				if kind == "cut_epoch" {
					cut.Before.Epoch++
				} else {
					cut.Accounts[0].Balance = "0"
				}
				page.Cut = canonical(cut)
			case "cut_missing":
				page.Cut = json.RawMessage("null")
			case "cut_extra_account":
				var cut map[string]any
				_ = json.Unmarshal(page.Cut, &cut)
				cut["accounts"] = append(cut["accounts"].([]any), cut["accounts"].([]any)[0])
				page.Cut = canonical(cut)
			case "closed_hash":
				page.ClosedPath[0].Hash = DagZero
			case "closed_side":
				page.ClosedPath[0].Side = "left"
			case "closed_missing":
				page.ClosedPath = page.ClosedPath[:len(page.ClosedPath)-1]
			case "closed_extra":
				page.ClosedPath = append(page.ClosedPath, page.ClosedPath[0])
			case "leaf_hash":
				page.Items[0].Leaf.Hash = DagZero
			case "leaf_creator":
				page.Items[0].Leaf.CreatorKey = app.genesis.DAGSegmented.Genesis.Producers[5]
			case "leaf_global":
				page.Items[0].Leaf.GlobalIndex = "2"
			case "leaf_sequence":
				page.Items[0].Leaf.Sequence = "2"
			case "leaf_index":
				page.Items[0].Leaf.Index = 2
			case "order_hash":
				page.Items[0].Path[0].Hash = DagZero
			case "order_side":
				page.Items[0].Path[0].Side = "left"
			case "start":
				page.Start = 32
			case "complete":
				page.Complete = !page.Complete
			case "height":
				page.Height++
			case "state_root":
				page.StateRoot = DagZero
			case "anchor":
				page.GenesisHash = DagZero
			case "commitment_epoch":
				page.Commitment.Epoch++
			}
			if _, err := verifyInput(bad); err == nil {
				t.Fatal("mutated closed witness verified")
			}
		})
	}
}

func TestDagClosedCorruptPersistentIndexOrArchiveFailsClosed(t *testing.T) {
	for _, kind := range []string{"missing_node", "extra_node", "metadata_offset", "metadata_cut", "archive_original"} {
		t.Run(kind, func(t *testing.T) {
			app, backend, root, _ := closedSDKFixture(t)
			packet := closedPagePacket(t, app, "1")
			leaf := packet.DAGSegmentedClosedPage.Items[0].Leaf
			raw, _ := backend.store.db.Get([]byte(closedIndexKey(1)), nil)
			var index dagClosedIndex
			_ = decodeStrict(raw, &index)
			if kind == "archive_original" {
				cut, hash, err := checkedClosedCut(index.Cut, backend.current.source, app.anchor)
				_ = cut
				if err != nil {
					t.Fatal(err)
				}
				file, err := os.OpenFile(filepath.Join(root, "gg-dag-segments", hash+".ggseg"), os.O_RDWR, 0)
				if err != nil {
					t.Fatal(err)
				}
				_, err = file.WriteAt([]byte("x"), index.Payloads[0].Offset)
				if err != nil {
					t.Fatal(err)
				}
				_ = file.Close()
				backend.store.payloadCache.clear()
				_, err = backend.store.publicClosedPayload(context.Background(), app.state, dagClosedPayloadSelector{Epoch: "1", Hash: leaf.Hash, Index: 1})
				if err == nil || backend.store.health() == nil {
					t.Fatal("changed cold original accepted")
				}
				return
			}
			switch kind {
			case "missing_node":
				_ = backend.store.db.Delete([]byte(closedNodeKey(0, 0)), nil)
			case "extra_node":
				_ = backend.store.db.Put([]byte(closedNodeKey(0, 100)), []byte(DagZero), nil)
			case "metadata_offset":
				index.Payloads[0].Offset++
				_ = backend.store.db.Put([]byte(closedIndexKey(1)), canonical(index), nil)
			case "metadata_cut":
				index.Cut = json.RawMessage("null")
				_ = backend.store.db.Put([]byte(closedIndexKey(1)), canonical(index), nil)
			}
			_ = app.Close()
			restored, err := newDagEnabledLedger(app.genesis, app.anchor, root, false)
			if err == nil {
				_ = restored.Close()
				t.Fatal("resealed/missing index bypassed full original startup provenance")
			}
		})
	}
}

func TestDagClosedCutPublishesReferenceIndexNodesAndSDKHistoryInOneWrite(t *testing.T) {
	app, backend, keys, _ := segmentedSDKFixture(t)
	wire := segmentedWire(t, backend.current.active, keys, 0, 1)
	commitSegmentedSDK(t, app, segmentedBatch(t, backend.current.active, wire))
	cut, _ := backend.current.cutTransaction()
	seen := false
	backend.store.write = func(batch *leveldb.Batch) error {
		dump := batch.Dump()
		for _, key := range []string{closedIndexKey(1), closedNodeKey(0, 0), segmentArchiveReferenceKey(1), "history", "meta"} {
			if !bytes.Contains(dump, []byte(key)) {
				t.Error("cut batch missing", key)
			}
		}
		seen = true
		return errors.New("public injected disk failure")
	}
	_, err := app.FinalizeBlock(context.Background(), &abci.RequestFinalizeBlock{Height: app.state.Height + 1, Txs: [][]byte{canonical(cut)}, Time: time.Unix(1700000003, 0)})
	if err == nil {
		_, err = app.Commit(context.Background(), &abci.RequestCommit{})
	}
	if err == nil || !seen || backend.store.health() == nil || app.state.DAGSegmented.Epoch != 1 {
		t.Fatal("failed atomic cut became observable", err, seen)
	}
}

func TestDagClosedOldIndexlessStoreRequiresExplicitTransitionAndPreservesBytes(t *testing.T) {
	app, backend, _, root := segmentedSDKFixture(t)
	meta := backend.store.meta
	meta.Schema = "gg.dag.segmented-store.v1"
	raw := canonical(meta)
	if err := backend.store.db.Put([]byte("meta"), raw, nil); err != nil {
		t.Fatal(err)
	}
	_ = app.Close()
	restored, err := newDagEnabledLedger(app.genesis, app.anchor, root, false)
	if err == nil {
		_ = restored.Close()
		t.Fatal("old candidate store silently rebound")
	}
	if !strings.Contains(err.Error(), "INDEX_TRANSITION_REQUIRED") {
		t.Fatal("missing concrete transition error", err)
	}
	db, err := leveldb.OpenFile(filepath.Join(root, "gg-dag-segmented.leveldb"), nil)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	still, _ := db.Get([]byte("meta"), nil)
	if !bytes.Equal(still, raw) {
		t.Fatal("old store changed by rejected open")
	}
}

func TestDagClosedRequestsRejectAmbiguousSelectorsAndBoundReaders(t *testing.T) {
	app, backend, _, _ := closedSDKFixture(t)
	for _, raw := range []string{`{"epoch":"0","start":0}`, `{"epoch":"4","start":0}`, `{"epoch":"01","start":0}`, `{"epoch":true,"start":0}`, `{"epoch":"1","start":true}`, `{"epoch":"1","start":1}`, `{"epoch":"1","start":4096}`, `{"epoch":"1","start":0,"verified":true}`, `{"epoch":"1","start":0} `} {
		response, err := app.Query(context.Background(), &abci.RequestQuery{Path: "/gg/dag/closed-page", Height: app.state.Height, Data: []byte(raw)})
		if err != nil || response.Code == 0 {
			t.Fatal("invalid selector accepted", raw, err)
		}
	}
	for i := 0; i < cap(backend.store.proofSlots); i++ {
		backend.store.proofSlots <- struct{}{}
	}
	if _, err := backend.store.publicClosedPage(context.Background(), app.state, dagClosedSelector{Epoch: "1"}); err == nil || err.Error() != "GG_DAG_PROOF_BUSY" {
		t.Fatal("unbounded proof readers", err)
	}
	for i := 0; i < cap(backend.store.proofSlots); i++ {
		<-backend.store.proofSlots
	}
	for i := 0; i < cap(backend.store.payloadSlots); i++ {
		backend.store.payloadSlots <- struct{}{}
	}
	if _, err := backend.store.publicClosedPayload(context.Background(), app.state, dagClosedPayloadSelector{Epoch: "1", Hash: DagZero, Index: 1}); err == nil || err.Error() != "GG_DAG_PAYLOAD_BUSY" {
		t.Fatal("unbounded payload readers", err)
	}
	for i := 0; i < cap(backend.store.payloadSlots); i++ {
		<-backend.store.payloadSlots
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	reads := 0
	if _, err := closedTreePath(ctx, 1, 2, func(string) ([]byte, error) { reads++; return nil, nil }); err == nil || reads != 0 {
		t.Fatal("cancelled tree query touched DB")
	}
	if backend.store.health() != nil {
		t.Fatal("invalid caller request poisoned healthy store")
	}
}

func TestDagClosedPinnedPageSurvivesAnotherCutWithoutConsensusLock(t *testing.T) {
	app, backend, _, _ := closedSDKFixture(t)
	before := copyState(app.state)
	entered, release := make(chan struct{}), make(chan struct{})
	backend.store.beforeProofRead = func() { close(entered); <-release }
	type result struct {
		page dagSegmentedClosedPage
		err  error
	}
	read := make(chan result, 1)
	go func() {
		page, err := backend.store.publicClosedPage(context.Background(), before, dagClosedSelector{Epoch: "1"})
		read <- result{page, err}
	}()
	select {
	case <-entered:
	case <-time.After(3 * time.Second):
		t.Fatal("closed read never reached isolated hook")
	}
	committed := make(chan struct{})
	go func() {
		cut, _ := backend.current.cutTransaction()
		commitSegmentedSDK(t, app, canonical(cut))
		close(committed)
	}()
	select {
	case <-committed:
	case <-time.After(3 * time.Second):
		close(release)
		t.Fatal("closed query held consensus/store lock")
	}
	close(release)
	value := <-read
	if value.err != nil || verifySegmentedClosedPage(value.page, before, backend.current.source) != nil || value.page.Height != before.Height {
		t.Fatal("closed query rebound to newer SDK state", value.err)
	}
}

func TestDagClosedCloseWaitsForSnapshotAndCancelledReaderReleasesIt(t *testing.T) {
	app, backend, _, _ := closedSDKFixture(t)
	state := copyState(app.state)
	entered, release := make(chan struct{}), make(chan struct{})
	backend.store.beforeProofRead = func() { close(entered); <-release }
	ctx, cancel := context.WithCancel(context.Background())
	read := make(chan error, 1)
	go func() {
		_, err := backend.store.publicClosedPage(ctx, state, dagClosedSelector{Epoch: "1"})
		read <- err
	}()
	<-entered
	closed := make(chan error, 1)
	go func() { closed <- backend.store.close() }()
	deadline := time.Now().Add(3 * time.Second)
	for {
		backend.store.mu.Lock()
		stopped := backend.store.db == nil
		backend.store.mu.Unlock()
		if stopped {
			break
		}
		if time.Now().After(deadline) {
			close(release)
			t.Fatal("close did not stop new snapshot ingress")
		}
		time.Sleep(time.Millisecond)
	}
	select {
	case <-closed:
		close(release)
		t.Fatal("DB closed before reader released snapshot")
	default:
	}
	cancel()
	close(release)
	if err := <-read; err == nil {
		t.Fatal("cancelled closed read published a proof")
	}
	if err := <-closed; err != nil {
		t.Fatal(err)
	}
}

func TestDagClosedRetainsExactSelectedManifestClockAllowance(t *testing.T) {
	app, backend, keys, _ := segmentedSDKFixture(t)
	wires := [][]byte{}
	for sequence := 1; sequence <= 2; sequence++ {
		raw := segmentedWire(t, backend.current.active, keys, 0, 1)
		var block DagBlock
		if decodeStrict(raw, &block) != nil {
			t.Fatal("fixture")
		}
		// First manifest is at second2, the second at second3. Both originals
		// remain valid with their original selected +5s allowance.
		block.Body.CreatedAtNs = int64(1700000002+sequence-1)*1000000000 + 5000000000
		block.Signature = hex.EncodeToString(ed25519.Sign(keys[0], streamCanonicalDomainBytes("GG-DAG-PROPOSAL-SIGN-v1\x00", block.Body)))
		raw = canonical(block)
		wires = append(wires, raw)
		commitSegmentedSDK(t, app, segmentedBatch(t, backend.current.active, raw))
	}
	cut, err := backend.current.cutTransaction()
	if err != nil {
		t.Fatal(err)
	}
	commitSegmentedSDK(t, app, canonical(cut))
	packet := closedPagePacket(t, app, "1")
	for position, witness := range packet.DAGSegmentedClosedPage.Items {
		chunk, err := backend.store.publicClosedPayload(context.Background(), app.state, dagClosedPayloadSelector{Epoch: "1", Hash: witness.Leaf.Hash, Index: position + 1})
		if err != nil {
			t.Fatal("SDK-selected future clock original became unavailable", position, err)
		}
		raw, err := base64.StdEncoding.DecodeString(chunk.Data)
		if err != nil || !bytes.Equal(raw, wires[position]) {
			t.Fatal("clock-correct original changed")
		}
	}
	if backend.store.health() != nil {
		t.Fatal("valid selected timestamp poisoned the store")
	}
}
