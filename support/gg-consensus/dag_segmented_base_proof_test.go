//go:build !js

package main

import (
	"bytes"
	"context"
	"encoding/json"
	"os"
	"strconv"
	"testing"
	"time"

	abci "github.com/cometbft/cometbft/abci/types"
)

func epochBasePacket(t *testing.T, app *Ledger, state State) VerifyInput {
	t.Helper()
	packet := segmentedProofPacket(t, app, state, "", 0)
	response, err := app.Query(context.Background(), &abci.RequestQuery{Path: "/gg/dag/base-proof", Height: state.Height})
	packet.DAGSegmentedBaseProof = &dagSegmentedBaseProof{}
	if err != nil || response.Code != 0 || decodeStrict(response.Value, packet.DAGSegmentedBaseProof) != nil {
		t.Fatal("actual selected base query", err, response)
	}
	return packet
}

func epochBaseFixture(t *testing.T) (*Ledger, *dagSegmentedNativeApplication, string, map[string]VerifyInput) {
	t.Helper()
	app, backend, keys, root := segmentedSDKFixture(t)
	packets := map[string]VerifyInput{"genesis": epochBasePacket(t, app, copyState(app.state))}
	commitSegmentedSDK(t, app, segmentedBatch(t, backend.current.active, segmentedWire(t, backend.current.active, keys, 0, 5000)))
	packets["before_cut"] = epochBasePacket(t, app, copyState(app.state))
	cut, _ := backend.current.cutTransaction()
	commitSegmentedSDK(t, app, canonical(cut))
	packets["after_cut"] = epochBasePacket(t, app, copyState(app.state))
	commitSegmentedSDK(t, app, segmentedBatch(t, backend.current.active, segmentedWire(t, backend.current.active, keys, 1, 3)))
	cut, _ = backend.current.cutTransaction()
	commitSegmentedSDK(t, app, canonical(cut))
	packets["second_cut"] = epochBasePacket(t, app, copyState(app.state))
	commitSegmentedSDK(t, app, segmentedBatch(t, backend.current.active, segmentedWire(t, backend.current.active, keys, 0, 1)))
	packets["after_next"] = epochBasePacket(t, app, copyState(app.state))
	return app, backend, root, packets
}

func TestDagSegmentedBaseDerivesGenesisAndTwoSelectedCutsWithoutSnapshotTrust(t *testing.T) {
	app, backend, root, packets := epochBaseFixture(t)
	for name, packet := range packets {
		result, err := verifyInput(packet)
		if err != nil || result["dag_segmented_base_proof_verified"] != true || result["dag_history_replay_verified"] != false || result["dag_segmented_base_scope"] != dagSegmentedBaseScope {
			t.Fatal(name, err)
		}
		base := result["dag_segmented_epoch_base"].(*dagVerifiedEpochBase)
		if base.Commitment.Active.Blocks != 0 || base.Commitment.Epoch != packet.State.DAGSegmented.Epoch ||
			base.Commitment.Blocks != packet.State.DAGSegmented.Blocks-uint64(packet.State.DAGSegmented.Active.Blocks) {
			t.Fatal("not the exact empty selected epoch base", name)
		}
	}
	packet := packets["after_next"]
	base, err := verifySegmentedBaseProof(*packet.DAGSegmentedBaseProof, packet.State, *app.genesis.DAGSegmented)
	if err != nil || base.Commitment.Transactions != 5003 || base.Commitment.Authors[0].Nonce != "5000" || base.Commitment.Authors[1].Nonce != "3" || base.Commitment.Epoch != 3 {
		t.Fatal("base rewound nonce or confused active account", err)
	}
	if path := os.Getenv("GG_PUBLIC_SEGMENTED_BASE_FIXTURE"); path != "" {
		if err := os.WriteFile(path, canonical(packets), 0600); err != nil {
			t.Fatal(err)
		}
	}
	if err := app.Close(); err != nil {
		t.Fatal(err)
	}
	restored, err := newDagEnabledLedger(app.genesis, app.anchor, root, false)
	if err != nil {
		t.Fatal("full original history restart", err)
	}
	defer restored.Close()
	for _, name := range []string{"second_cut", "after_next"} {
		packet := packets[name]
		again := epochBasePacket(t, restored, packet.State)
		if !bytes.Equal(canonical(again), canonical(packet)) {
			t.Fatal("base proof was not reconstructed from original replay", name)
		}
	}
	if len(backend.store.proofViews) > 4 {
		t.Fatal("base metadata unbounded")
	}
}

func TestDagSegmentedBaseRejectsCutPeakAccountAndCertificateContextMutations(t *testing.T) {
	_, _, _, packets := epochBaseFixture(t)
	for _, kind := range []string{"cut_balance", "cut_nonce", "cut_author", "cut_history_root", "cut_epoch", "cut_old_context", "cut_extra_account", "cut_whitespace",
		"cut_null", "peak_changed", "peak_unset", "peak_missing", "peak_extra", "peak_null", "context_epoch", "native_height", "native_root", "anchor", "unknown_schema"} {
		t.Run(kind, func(t *testing.T) {
			var bad VerifyInput
			if decodeStrict(canonical(packets["after_next"]), &bad) != nil {
				t.Fatal("fixture")
			}
			proof := bad.DAGSegmentedBaseProof
			var cut dagHistoryCutBody
			if decodeStrict(proof.Cut, &cut) != nil {
				t.Fatal("fixture")
			}
			switch kind {
			case "cut_balance":
				cut.Accounts[0].Balance = "0"
			case "cut_nonce":
				cut.Accounts[0].Nonce++
			case "cut_author":
				cut.Before.Authors[0].Key = cut.Before.Authors[1].Key
			case "cut_history_root":
				cut.HistoryRoot = DagZero
			case "cut_epoch":
				cut.Before.Epoch++
			case "cut_old_context":
				proof.Cut = packets["after_cut"].DAGSegmentedBaseProof.Cut
			case "cut_null":
				proof.Cut = json.RawMessage("null")
			case "cut_whitespace":
				proof.Cut = append([]byte(" "), proof.Cut...)
			case "cut_extra_account":
				var raw map[string]json.RawMessage
				if json.Unmarshal(proof.Cut, &raw) != nil {
					t.Fatal("fixture")
				}
				accounts := append([]Account{}, cut.Accounts[:]...)
				accounts = append(accounts, accounts[0])
				raw["accounts"] = canonical(accounts)
				proof.Cut = canonical(raw)
			case "peak_changed":
				proof.PreviousClosed[0] = DagZero
			case "peak_unset":
				proof.PreviousClosed[2] = DagZero
			case "peak_missing":
				proof.PreviousClosed = proof.PreviousClosed[:63]
			case "peak_extra":
				proof.PreviousClosed = append(proof.PreviousClosed, "")
			case "peak_null":
				proof.PreviousClosed = nil
			case "context_epoch":
				proof.Commitment.Epoch++
			case "native_height":
				proof.Height++
			case "native_root":
				proof.StateRoot = DagZero
			case "anchor":
				proof.GenesisHash = DagZero
			case "unknown_schema":
				proof.Schema += ".unknown"
			}
			switch kind {
			case "cut_balance", "cut_nonce", "cut_author", "cut_history_root", "cut_epoch":
				proof.Cut = canonical(cut)
			}
			if result, err := verifyInput(bad); err == nil || result != nil {
				t.Fatal("invalid certified base accepted")
			}
		})
	}
	for _, kind := range []string{"cut", "peaks", "null_peaks", "missing_cut"} {
		var bad VerifyInput
		if decodeStrict(canonical(packets["genesis"]), &bad) != nil {
			t.Fatal("fixture")
		}
		switch kind {
		case "cut":
			bad.DAGSegmentedBaseProof.Cut = json.RawMessage("{}")
		case "peaks":
			bad.DAGSegmentedBaseProof.PreviousClosed = []string{""}
		case "null_peaks":
			bad.DAGSegmentedBaseProof.PreviousClosed = nil
		case "missing_cut":
			bad.DAGSegmentedBaseProof.Cut = nil
		}
		if result, err := verifyInput(bad); err == nil || result != nil {
			t.Fatal("irrelevant genesis proof content accepted", kind)
		}
	}
}

func TestDagSegmentedBaseOddClosedTreeFrontierAndNoSharedMutableQueryBytes(t *testing.T) {
	app, backend, keys, _ := segmentedSDKFixture(t)
	for index := 0; index < 7; index++ {
		commitSegmentedSDK(t, app, segmentedBatch(t, backend.current.active, segmentedWire(t, backend.current.active, keys, index%6, 1)))
		cut, _ := backend.current.cutTransaction()
		commitSegmentedSDK(t, app, canonical(cut))
		packet := epochBasePacket(t, app, copyState(app.state))
		if result, err := verifyInput(packet); err != nil || result["dag_segmented_base_proof_verified"] != true {
			t.Fatal(index, err)
		}
	}
	packet := epochBasePacket(t, app, copyState(app.state))
	original := canonical(packet.DAGSegmentedBaseProof)
	packet.DAGSegmentedBaseProof.Cut[0] ^= 1
	packet.DAGSegmentedBaseProof.PreviousClosed[0] = "changed"
	again := epochBasePacket(t, app, copyState(app.state))
	if !bytes.Equal(original, canonical(again.DAGSegmentedBaseProof)) {
		t.Fatal("query caller changed retained metadata")
	}
}

func TestDagSegmentedBaseSlowCapturedQueryCannotStopCutCommitOrReturnNewEpoch(t *testing.T) {
	app, backend, keys, _ := segmentedSDKFixture(t)
	commitSegmentedSDK(t, app, segmentedBatch(t, backend.current.active, segmentedWire(t, backend.current.active, keys, 0, 1)))
	old := copyState(app.state)
	entered, release := make(chan struct{}), make(chan struct{})
	finished := make(chan *abci.ResponseQuery, 1)
	backend.store.beforeProofRead = func() { close(entered); <-release }
	go func() {
		response, _ := app.Query(context.Background(), &abci.RequestQuery{Path: "/gg/dag/base-proof", Height: old.Height})
		finished <- response
	}()
	select {
	case <-entered:
	case <-time.After(3 * time.Second):
		close(release)
		t.Fatal("no metadata capture")
	}
	cut, _ := backend.current.cutTransaction()
	committed := make(chan struct{}, 1)
	go func() { commitSegmentedSDK(t, app, canonical(cut)); committed <- struct{}{} }()
	select {
	case <-committed:
	case <-time.After(3 * time.Second):
		close(release)
		t.Fatal("held base query blocked commit")
	}
	close(release)
	response := <-finished
	var proof dagSegmentedBaseProof
	if response == nil || response.Code != 0 || decodeStrict(response.Value, &proof) != nil || proof.Commitment != *old.DAGSegmented {
		t.Fatal("captured old context changed")
	}
	if base, err := verifySegmentedBaseProof(proof, old, *app.genesis.DAGSegmented); err != nil || base.Commitment.Epoch != 1 || app.state.DAGSegmented.Epoch != 2 {
		t.Fatal(err)
	}
}

func TestDagSegmentedBaseRejectsSelectorsAndRequiresRetainedContext(t *testing.T) {
	app, backend, keys, _ := segmentedSDKFixture(t)
	old := copyState(app.state)
	response, _ := app.Query(context.Background(), &abci.RequestQuery{Path: "/gg/dag/base-proof", Data: []byte("not-a-selector")})
	if response.Code == 0 {
		t.Fatal("base query accepted external selector")
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if value, err := backend.store.publicProof(ctx, old, "/gg/dag/base-proof", "", 0); err == nil || value != nil {
		t.Fatal("cancelled proof published")
	}
	for index := 0; index < 5; index++ {
		commitSegmentedSDK(t, app, segmentedBatch(t, backend.current.active, segmentedWire(t, backend.current.active, keys, 0, 0)))
	}
	if value, err := backend.store.publicProof(context.Background(), old, "/gg/dag/base-proof", "", 0); err == nil || value != nil {
		t.Fatal("evicted context replaced with current base")
	}
}

func TestDagSegmentedBaseAuthorDecoderRejectsCardinalityBeforeTypedDiscard(t *testing.T) {
	_, _, _, packets := epochBaseFixture(t)
	var packet map[string]json.RawMessage
	if json.Unmarshal(canonical(packets["after_next"]), &packet) != nil {
		t.Fatal("fixture")
	}
	var state map[string]json.RawMessage
	if json.Unmarshal(packet["state"], &state) != nil {
		t.Fatal("fixture")
	}
	var commitment map[string]json.RawMessage
	if json.Unmarshal(state["dag_segmented"], &commitment) != nil {
		t.Fatal("fixture")
	}
	var authors []json.RawMessage
	if json.Unmarshal(commitment["authors"], &authors) != nil {
		t.Fatal("fixture")
	}
	for _, count := range []int{0, 5, 7, 128} {
		t.Run(strconv.Itoa(count), func(t *testing.T) {
			values := []json.RawMessage{}
			for i := 0; i < count; i++ {
				values = append(values, authors[i%6])
			}
			commitment["authors"] = canonical(values)
			state["dag_segmented"] = canonical(commitment)
			packet["state"] = canonical(state)
			var decoded VerifyInput
			if decodeStrictLimited(canonical(packet), &decoded, 128, 64) == nil {
				t.Fatal("fixed array silently discarded or filled authors")
			}
		})
	}
}
