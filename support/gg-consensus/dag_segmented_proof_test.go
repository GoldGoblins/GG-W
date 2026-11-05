//go:build !js

package main

import (
	"bytes"
	"context"
	"encoding/hex"
	"encoding/json"
	"os"
	"runtime"
	"strconv"
	"strings"
	"testing"
	"time"

	abci "github.com/cometbft/cometbft/abci/types"
	cmtjson "github.com/cometbft/cometbft/libs/json"
	"github.com/cometbft/cometbft/types"
)

func segmentedProofPacket(t *testing.T, app *Ledger, state State, block string, start int) VerifyInput {
	t.Helper()
	_, _, _, validators := testGenesis()
	header := signedFixture(app.genesis, validators, state.Height+1, state.StateRoot, nil, types.BlockID{})
	raw, err := cmtjson.Marshal(header)
	if err != nil {
		t.Fatal(err)
	}
	packet := VerifyInput{Schema: "gg.consensus.proof.v1", Genesis: app.genesis, GenesisHash: app.anchor, State: state, SignedHeader: raw}
	query := func(path string, data []byte, target any) {
		response, err := app.Query(context.Background(), &abci.RequestQuery{Path: path, Data: data, Height: state.Height})
		if err != nil || response.Code != 0 || decodeStrict(response.Value, target) != nil {
			t.Fatal("genuine selected query", path, err, response)
		}
	}
	account, _ := hex.DecodeString(app.genesis.DAGSegmented.Genesis.Producers[0])
	packet.DAGSegmentedAccountProof = &dagSegmentedAccountProof{}
	query("/gg/dag/account-proof", account, packet.DAGSegmentedAccountProof)
	packet.DAGSegmentedOrderPage = &dagSegmentedOrderPage{}
	query("/gg/dag/order-page", []byte("{\"start\":"+strconv.Itoa(start)+"}"), packet.DAGSegmentedOrderPage)
	if block != "" {
		packet.DAGSegmentedBlockProof = &dagSegmentedBlockProof{}
		query("/gg/dag/block-proof", []byte(block), packet.DAGSegmentedBlockProof)
	}
	return packet
}

func segmentedProofFixture(t *testing.T) (*Ledger, *dagSegmentedNativeApplication, string, map[string]VerifyInput) {
	t.Helper()
	app, backend, keys, root := segmentedSDKFixture(t)
	first := segmentedBatch(t, backend.current.active, segmentedWire(t, backend.current.active, keys, 0, 5000), segmentedWire(t, backend.current.active, keys, 1, 3))
	commitSegmentedSDK(t, app, first)
	before := copyState(app.state)
	order, _ := backend.current.active.orderList()
	oldBlock := order[0].Hash
	cut, _ := backend.current.cutTransaction()
	commitSegmentedSDK(t, app, canonical(cut))
	afterCut := copyState(app.state)
	commitSegmentedSDK(t, app, segmentedBatch(t, backend.current.active, segmentedWire(t, backend.current.active, keys, 0, 1)))
	after := copyState(app.state)
	order, _ = backend.current.active.orderList()
	packets := map[string]VerifyInput{
		"before_cut": segmentedProofPacket(t, app, before, oldBlock, 0),
		"after_cut":  segmentedProofPacket(t, app, afterCut, "", 0),
		"after_next": segmentedProofPacket(t, app, after, order[0].Hash, 0),
	}
	return app, backend, root, packets
}

func TestDagSegmentedMembershipRealAccountsCreatorsGlobalIndexAcrossCutAndRestart(t *testing.T) {
	app, backend, root, packets := segmentedProofFixture(t)
	for name, packet := range packets {
		result, err := verifyInput(packet)
		if err != nil || result["dag_segmented_account_proof_verified"] != true || result["dag_segmented_order_page_verified"] != true ||
			result["dag_history_replay_verified"] != false || result["dag_account_proof_verified"] != false {
			t.Fatal("actual segmented membership", name, err)
		}
	}
	if packets["after_cut"].DAGSegmentedAccountProof.Leaf.Nonce != 5000 || len(packets["after_cut"].DAGSegmentedOrderPage.Items) != 0 {
		t.Fatal("cut erased account or invented a block")
	}
	proof := packets["after_next"].DAGSegmentedBlockProof
	if proof.Leaf.CreatorKey != app.genesis.DAGSegmented.Genesis.Producers[0] || proof.Leaf.Index != 1 || proof.Leaf.GlobalIndex != "3" || proof.Leaf.Sequence != "2" ||
		packets["after_next"].DAGSegmentedAccountProof.Leaf.Nonce != 5001 {
		t.Fatal("identity, nonce or local/global counter conflated")
	}
	if len(backend.store.proofViews) > dagSegmentProofViews {
		t.Fatal("proof cache grew without bound")
	}
	if path := os.Getenv("GG_PUBLIC_SEGMENTED_MEMBERSHIP_FIXTURE"); path != "" {
		if err := os.WriteFile(path, canonical(packets), 0600); err != nil {
			t.Fatal(err)
		}
	}
	if err := app.Close(); err != nil {
		t.Fatal(err)
	}
	restored, err := newDagEnabledLedger(app.genesis, app.anchor, root, false)
	if err != nil {
		t.Fatal(err)
	}
	defer restored.Close()
	for name, packet := range packets {
		block := ""
		if packet.DAGSegmentedBlockProof != nil {
			block = packet.DAGSegmentedBlockProof.Leaf.Hash
		}
		replayed := segmentedProofPacket(t, restored, packet.State, block, 0)
		if !bytes.Equal(canonical(replayed), canonical(packet)) {
			t.Fatal("restart trusted or changed proof metadata", name)
		}
	}
}

func TestDagSegmentedMembershipRejectsCrossEpochCreatorIndexOmissionAndContext(t *testing.T) {
	_, _, _, packets := segmentedProofFixture(t)
	packet := packets["after_next"]
	for _, kind := range []string{"account_balance", "account_nonce", "account_index", "block_creator", "global_index", "sequence", "epoch", "old_block",
		"page_omit", "page_duplicate", "page_complete", "page_start", "page_creator", "height", "native_root", "null_path"} {
		t.Run(kind, func(t *testing.T) {
			var bad VerifyInput
			if decodeStrict(canonical(packet), &bad) != nil {
				t.Fatal("fixture")
			}
			switch kind {
			case "account_balance":
				bad.DAGSegmentedAccountProof.Leaf.Balance = "0"
			case "account_nonce":
				bad.DAGSegmentedAccountProof.Leaf.Nonce--
			case "account_index":
				bad.DAGSegmentedAccountProof.Index = (bad.DAGSegmentedAccountProof.Index + 1) % 6
			case "block_creator":
				bad.DAGSegmentedBlockProof.Leaf.CreatorKey = bad.Genesis.DAGSegmented.Genesis.Producers[1]
			case "global_index":
				bad.DAGSegmentedBlockProof.Leaf.GlobalIndex = "1"
			case "sequence":
				bad.DAGSegmentedBlockProof.Leaf.Sequence = "1"
			case "epoch":
				bad.DAGSegmentedBlockProof.Commitment.Epoch--
			case "old_block":
				bad.DAGSegmentedBlockProof = packets["before_cut"].DAGSegmentedBlockProof
			case "page_omit":
				bad.DAGSegmentedOrderPage.Items = bad.DAGSegmentedOrderPage.Items[:0]
			case "page_duplicate":
				bad.DAGSegmentedOrderPage.Items = append(bad.DAGSegmentedOrderPage.Items, bad.DAGSegmentedOrderPage.Items[0])
			case "page_complete":
				bad.DAGSegmentedOrderPage.Complete = false
			case "page_start":
				bad.DAGSegmentedOrderPage.Start = 32
			case "page_creator":
				bad.DAGSegmentedOrderPage.Items[0].Leaf.CreatorKey = bad.Genesis.DAGSegmented.Genesis.Producers[1]
			case "height":
				bad.DAGSegmentedAccountProof.Height--
			case "native_root":
				bad.DAGSegmentedAccountProof.StateRoot = DagZero
			case "null_path":
				bad.DAGSegmentedBlockProof.Path = nil
			}
			if result, err := verifyInput(bad); err == nil || result != nil {
				t.Fatal("manipulated membership accepted")
			}
		})
	}
}

func TestDagSegmentedMembershipSlowCapturedQueryCannotBlockCommitOrChangeOldBalance(t *testing.T) {
	app, backend, keys, _ := segmentedSDKFixture(t)
	commitSegmentedSDK(t, app, segmentedBatch(t, backend.current.active, segmentedWire(t, backend.current.active, keys, 0, 1)))
	old := copyState(app.state)
	entered, release, finished := make(chan struct{}), make(chan struct{}), make(chan *abci.ResponseQuery, 1)
	backend.store.beforeProofRead = func() { close(entered); <-release }
	go func() {
		response, _ := app.Query(context.Background(), &abci.RequestQuery{Path: "/gg/dag/account-proof", Data: []byte(app.genesis.DAGSegmented.Genesis.Producers[0]), Height: old.Height})
		finished <- response
	}()
	select {
	case <-entered:
	case <-time.After(3 * time.Second):
		close(release)
		t.Fatal("query did not capture metadata")
	}
	committed := make(chan error, 1)
	tx := segmentedBatch(t, backend.current.active, segmentedWire(t, backend.current.active, keys, 0, 1))
	go func() {
		_, err := app.FinalizeBlock(context.Background(), &abci.RequestFinalizeBlock{Height: 2, Txs: [][]byte{tx}, Time: time.Unix(1700000003, 0)})
		if err == nil {
			_, err = app.Commit(context.Background(), &abci.RequestCommit{})
		}
		committed <- err
	}()
	select {
	case err := <-committed:
		if err != nil {
			close(release)
			t.Fatal(err)
		}
	case <-time.After(3 * time.Second):
		close(release)
		t.Fatal("cold proof held consensus or store lock")
	}
	close(release)
	response := <-finished
	var proof dagSegmentedAccountProof
	if response == nil || response.Code != 0 || decodeStrict(response.Value, &proof) != nil || proof.Leaf.Nonce != 1 || proof.Commitment != *old.DAGSegmented ||
		verifySegmentedAccountProof(proof, old, *app.genesis.DAGSegmented) != nil || app.state.DAGSegmented.Transactions != 2 {
		t.Fatal("captured proof changed to new live state")
	}
}

func TestDagSegmentedMembershipCacheAndConcurrentReaderCreditsAreBounded(t *testing.T) {
	app, backend, keys, _ := segmentedSDKFixture(t)
	var first State
	for index := 0; index < 6; index++ {
		commitSegmentedSDK(t, app, segmentedBatch(t, backend.current.active, segmentedWire(t, backend.current.active, keys, 0, 1)))
		if index == 0 {
			first = copyState(app.state)
		}
	}
	if len(backend.store.proofViews) != dagSegmentProofViews {
		t.Fatal("unbounded/unused proof cache")
	}
	response, err := app.Query(context.Background(), &abci.RequestQuery{Path: "/gg/dag/account-proof", Data: []byte(app.genesis.DAGSegmented.Genesis.Producers[0]), Height: first.Height})
	if err != nil || response.Code == 0 || response.Log != errDagSegmentProofUnavailable.Error() {
		t.Fatal("evicted context silently substituted current state", err)
	}
	for index := 0; index < dagPublicMaxReaders; index++ {
		backend.store.proofSlots <- struct{}{}
	}
	_, err = backend.store.publicProof(context.Background(), app.state, "/gg/dag/order-page", "", 0)
	if err == nil || err.Error() != "GG_DAG_PROOF_BUSY" {
		t.Fatal("query reader credit bypass")
	}
	for index := 0; index < dagPublicMaxReaders; index++ {
		<-backend.store.proofSlots
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := backend.store.publicProof(ctx, app.state, "/gg/dag/order-page", "", 0); err == nil {
		t.Fatal("cancelled proof query succeeded")
	}
}

func TestDagSegmentedMembershipGlobalCounterWireRetainsIntegerPrecision(t *testing.T) {
	// Serialization vector only, not a replay of this number of real blocks.
	sequence := uint64(9007199254740993)
	state := dagSegmentedState{Blocks: sequence, Active: DagCommitment{Blocks: 1}}
	source := dagSegmentedSource{}
	source.Genesis.Producers = []string{hashHex([]byte("public precision fixture"))}
	leaf, err := segmentedPublicLeaf(DagOrderLeaf{Hash: DagZero, Index: 1, Producer: 0, Sequence: sequence}, state, source)
	if err != nil {
		t.Fatal(err)
	}
	raw := canonical(leaf)
	var generic map[string]any
	if json.Unmarshal(raw, &generic) != nil || generic["sequence"] != "9007199254740993" || generic["global_index"] != "9007199254740993" {
		t.Fatal("JS/JSON counter rounded before verification")
	}
	var decoded dagSegmentedOrderLeaf
	if decodeStrict(raw, &decoded) != nil || decoded != leaf {
		t.Fatal("decimal string counter roundtrip changed")
	}
}

func TestDagSegmentedMembershipCompletePagesKeepGlobalOrderAndOddSiblingRule(t *testing.T) {
	app, backend, _, _ := segmentedProofFixture(t)
	_, keys := segmentedSDKGenesis(t)
	base := backend.current
	cursor := base
	wires := [][]byte{}
	for index := 0; index < 65; index++ {
		raw := segmentedWire(t, cursor.active, keys, 0, 0)
		wires = append(wires, raw)
		next, err := cursor.apply(segmentedBatch(t, cursor.active, raw), 1700000010000000000)
		if err != nil {
			t.Fatal(err)
		}
		cursor = next
	}
	commitSegmentedSDK(t, app, segmentedBatch(t, base.active, wires...))
	// The fixture already selected one block in this epoch; pages cover all66.
	for _, start := range []int{0, 32, 64} {
		packet := segmentedProofPacket(t, app, copyState(app.state), "", start)
		result, err := verifyInput(packet)
		if err != nil || result["dag_segmented_order_page_verified"] != true {
			t.Fatal("complete page rejected", start, err)
		}
		for index, item := range packet.DAGSegmentedOrderPage.Items {
			if item.Leaf.GlobalIndex != strconv.Itoa(start+index+3) || item.Leaf.CreatorKey != app.genesis.DAGSegmented.Genesis.Producers[0] {
				t.Fatal("wrong global order or author")
			}
		}
		if start == 64 {
			if len(packet.DAGSegmentedOrderPage.Items) != 2 || !packet.DAGSegmentedOrderPage.Complete {
				t.Fatal("wrong final page")
			}
			// At least one ancestor of the last two leaves is odd-duplicated.
			packet.DAGSegmentedOrderPage.Items[1].Path[1].Hash = DagZero
			if _, err := verifyInput(packet); err == nil {
				t.Fatal("changed odd-node proof accepted")
			}
		}
	}
}

func TestDagSegmentedMembershipRejectsProofCollectionAmplificationBeforeAllocation(t *testing.T) {
	// Fits the public256KiB envelope yet must not allocate tens of thousands
	// of typed witnesses before discovering the missing/invalid context.
	raw := []byte(`{"dag_segmented_order_page":{"items":[` + strings.Repeat(`{},`, 60000) + `{}]}}`)
	if len(raw) > 256*1024 {
		t.Fatal("fixture exceeds public proof envelope")
	}
	var before, after runtime.MemStats
	runtime.ReadMemStats(&before)
	err := runVerify(raw)
	runtime.ReadMemStats(&after)
	allocated := after.TotalAlloc - before.TotalAlloc
	t.Logf("public_proof_raw_bytes=%d allocated_bytes=%d", len(raw), allocated)
	if err == nil || allocated > 1024*1024 {
		t.Fatal("typed proof collection allocated before bounded shape rejection")
	}
}
