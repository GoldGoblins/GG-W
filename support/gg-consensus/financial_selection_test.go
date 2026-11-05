//go:build !js

package main

import (
	"bytes"
	"context"
	"encoding/base64"
	abci "github.com/cometbft/cometbft/abci/types"
	"sort"
	"strings"
	"testing"
	"time"
)

func orderedFinancialPackage(t *testing.T, base *financialDagExecution, wires ...[]byte) []byte {
	t.Helper()
	sort.Slice(wires, func(i, j int) bool {
		a, ea := decodeFinancialDagBlock(context.Background(), wires[i], base.source, base.anchor, base.epoch, 0)
		b, eb := decodeFinancialDagBlock(context.Background(), wires[j], base.source, base.anchor, base.epoch, 0)
		if ea != nil || eb != nil {
			t.Fatal(ea, eb)
		}
		return a.Block.Body.Rank < b.Block.Body.Rank || a.Block.Body.Rank == b.Block.Body.Rank && a.Hash < b.Hash
	})
	return financialDagBatchWire(t, base, wires...)
}

func TestFinancialSDKCombinesFourIndependent5000PaymentCreatorsAndColdReplays(t *testing.T) {
	app, backend, accounts, producers, root := financialSDKFixture(t)
	txs := make([][]byte, 4)
	originals := map[string][]byte{}
	for creator := 0; creator < 4; creator++ {
		inputs := make([][]byte, 5000)
		for index := range inputs {
			inputs[index] = testTx(app.genesis, app.anchor, accounts, creator, (creator+1)%4, "1", uint64(index))
		}
		wire, id := financialDagSignedBlock(t, backend.current, producers, creator, inputs, nil)
		originals[id] = wire
		txs[creator] = financialDagBatchWire(t, backend.current, wire)
	}
	before := canonical(app.state)
	when := time.Unix(0, backend.store.timeNs+1000000)
	prepared, err := app.PrepareProposal(context.Background(), &abci.RequestPrepareProposal{Time: when, MaxTxBytes: 64 * 1024 * 1024, Txs: txs})
	if err != nil || len(prepared.Txs) != 1 {
		t.Fatal("independent packages were not combined", err)
	}
	var selected financialDagBatch
	if decodeStrict(prepared.Txs[0], &selected) != nil || len(selected.Blocks) != 4 {
		t.Fatal("lost independent creator")
	}
	for _, encoded := range selected.Blocks {
		wire, err := base64.StdEncoding.Strict().DecodeString(encoded)
		id := hashHex(append([]byte(financialDomain+"DAG-BLOCK\x00"), wire...))
		if err != nil || !bytes.Equal(originals[id], wire) {
			t.Fatal("changed creator original")
		}
	}
	checked, err := app.ProcessProposal(context.Background(), &abci.RequestProcessProposal{Time: when, Txs: prepared.Txs})
	if err != nil || checked.Status != abci.ResponseProcessProposal_ACCEPT || !bytes.Equal(before, canonical(app.state)) {
		t.Fatal("verification bypass or premature state", err)
	}
	commitFinancialSDK(t, app, prepared.Txs[0])
	value := app.state.FinancialDAG
	if value.Blocks != 4 || value.Applied != 20000 || value.Rejected != 0 || value.Checkpoint != 1 {
		t.Fatal("not four real blocks in one SDK selection", value)
	}
	for _, account := range app.state.Accounts {
		if account.Nonce != 5000 || account.Balance != "250000000000" {
			t.Fatal("wrong monetary result", account)
		}
	}
	for block := range originals {
		proof, err := backend.Receipt(context.Background(), app.state, financialReceiptSelector{Block: block, Index: 4999})
		if err != nil || checkFinancialCertifiedReceipt(proof, app.state, app.genesis) != nil {
			t.Fatal("combined receipt failed", err)
		}
	}
	saved := canonical(app.state)
	_ = app.Close()
	reopened, err := newDagEnabledLedger(app.genesis, app.anchor, root, false)
	if err != nil {
		t.Fatal(err)
	}
	defer reopened.Close()
	if !bytes.Equal(saved, canonical(reopened.state)) {
		t.Fatal("combined original history did not replay")
	}
}

func TestFinancialSDKSelectionDeduplicatesAndResolvesCreatorEquivocationWithoutArrivalOrder(t *testing.T) {
	app, backend, accounts, producers, _ := financialSDKFixture(t)
	base := backend.current
	ctx := context.Background()
	first, firstID := financialDagSignedBlock(t, base, producers, 0, [][]byte{testTx(app.genesis, app.anchor, accounts, 0, 1, "1", 0)}, nil)
	second, secondID := financialDagSignedBlock(t, base, producers, 0, [][]byte{testTx(app.genesis, app.anchor, accounts, 0, 1, "2", 0)}, nil)
	winner, loser := first, second
	if secondID < firstID {
		winner, loser = second, first
	}
	losing, err := base.applyBatch(ctx, financialDagBatchWire(t, base, loser), base.timeNs+1000000)
	if err != nil {
		t.Fatal(err)
	}
	child, _ := financialDagSignedBlock(t, losing, producers, 0, [][]byte{testTx(app.genesis, app.anchor, accounts, 0, 1, "1", 1)}, nil)
	other, _ := financialDagSignedBlock(t, base, producers, 1, [][]byte{testTx(app.genesis, app.anchor, accounts, 1, 2, "3", 0)}, nil)
	a, b, c := financialDagBatchWire(t, base, winner), orderedFinancialPackage(t, base, loser, child), financialDagBatchWire(t, base, other)
	var chosen []byte
	for _, inputs := range [][][]byte{{a, b, c, a}, {c, b, a}, {b, a, c}} {
		raw, err := selectFinancialProposal(ctx, base, inputs, base.timeNs+2000000, 64*1024*1024)
		if err != nil || len(raw) == 0 {
			t.Fatal(err)
		}
		if chosen != nil && !bytes.Equal(raw, chosen) {
			t.Fatal("arrival order chose a different creator signature")
		}
		chosen = raw
		next, err := base.applyBatch(ctx, raw, base.timeNs+2000000)
		if err != nil || next.blocks != 2 || next.authors[0].Sequence != 1 || next.authors[1].Sequence != 1 || next.applied != 2 {
			t.Fatal("equivocation or missing descendant entered selection", err)
		}
	}
	if backend.current.blocks != 0 {
		t.Fatal("selection published state")
	}
}

func TestFinancialSDKSelectionNeverSalvagesAnUnauthenticatedPaymentPackage(t *testing.T) {
	app, backend, accounts, producers, _ := financialSDKFixture(t)
	base := backend.current
	valid, _ := financialDagSignedBlock(t, base, producers, 0, [][]byte{testTx(app.genesis, app.anchor, accounts, 0, 1, "1", 0)}, nil)
	badInput := testTx(app.genesis, app.anchor, accounts, 1, 2, "1", 0)
	var envelope Envelope
	if decodeStrict(badInput, &envelope) != nil {
		t.Fatal("fixture")
	}
	envelope.Signature = strings.Repeat("0", 128)
	invalid, _ := financialDagSignedBlock(t, base, producers, 1, [][]byte{canonical(envelope)}, nil)
	other, _ := financialDagSignedBlock(t, base, producers, 2, [][]byte{testTx(app.genesis, app.anchor, accounts, 2, 3, "1", 0)}, nil)
	raw, err := selectFinancialProposal(context.Background(), base, [][]byte{orderedFinancialPackage(t, base, valid, invalid), financialDagBatchWire(t, base, other)}, base.timeNs+1000000, 64*1024*1024)
	if err != nil {
		t.Fatal(err)
	}
	next, err := base.applyBatch(context.Background(), raw, base.timeNs+1000000)
	if err != nil || next.blocks != 1 || next.applied != 1 || next.authors[0].Sequence != 0 || next.authors[1].Sequence != 0 || next.authors[2].Sequence != 1 {
		t.Fatal("unauthenticated package leaked a block", err)
	}
}

func TestFinancialSDKSelectionHonorsWireAndInputScanBoundsAndCancellation(t *testing.T) {
	app, backend, accounts, producers, _ := financialSDKFixture(t)
	base := backend.current
	large := make([][]byte, 50)
	for index := range large {
		large[index] = testTx(app.genesis, app.anchor, accounts, 0, 1, "1", uint64(index))
	}
	first, _ := financialDagSignedBlock(t, base, producers, 0, large, nil)
	small, _ := financialDagSignedBlock(t, base, producers, 1, [][]byte{testTx(app.genesis, app.anchor, accounts, 1, 2, "1", 0)}, nil)
	a, b := financialDagBatchWire(t, base, first), financialDagBatchWire(t, base, small)
	raw, err := selectFinancialProposal(context.Background(), base, [][]byte{a, b}, base.timeNs+1000000, int64(len(b)+8))
	if err != nil || !bytes.Equal(raw, b) {
		t.Fatal("byte budget lost the fitting creator", err)
	}
	raw, err = selectFinancialProposal(context.Background(), base, [][]byte{b}, base.timeNs+1000000, int64(len(b)+7))
	if err != nil || len(raw) != 0 {
		t.Fatal("exceeded request byte budget", err)
	}
	flooded := make([][]byte, DagMaxBatchBlocks+1)
	for index := range flooded {
		flooded[index] = []byte("x")
	}
	flooded[DagMaxBatchBlocks] = b
	raw, err = selectFinancialProposal(context.Background(), base, flooded, base.timeNs+1000000, 64*1024*1024)
	if err != nil || len(raw) != 0 {
		t.Fatal("unbounded input scan", err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err = selectFinancialProposal(ctx, base, [][]byte{b}, base.timeNs+1000000, 64*1024*1024); err != context.Canceled {
		t.Fatal("cancellation lost", err)
	}
}

func TestFinancialSDKAutomaticallyCutsARealFullCreatorWindowAndReplaysOriginals(t *testing.T) {
	app, backend, accounts, producers, root := financialSDKFixture(t)
	ctx := context.Background()
	target := DagMaxRecords - DagMaxBatchBlocks + 1
	firstID := ""
	for backend.current.activeBlocks < target {
		base := backend.current
		draft := base.clone()
		draft.previous, _ = base.commitmentHash()
		draft.checkpoint = base.checkpoint + 1
		draft.timeNs = base.timeNs + 1000000
		wires := make([][]byte, 0, DagMaxBatchBlocks)
		for len(wires) < DagMaxBatchBlocks && draft.activeBlocks < target {
			var inputs [][]byte
			if draft.blocks == 0 {
				inputs = [][]byte{testTx(app.genesis, app.anchor, accounts, 0, 1, "1", 0)}
			}
			wire, id := financialDagSignedBlock(t, draft, producers, 0, inputs, nil)
			if firstID == "" {
				firstID = id
			}
			record, err := decodeFinancialDagBlock(ctx, wire, draft.source, draft.anchor, draft.epoch, draft.timeNs)
			if err != nil {
				t.Fatal(err)
			}
			if err = draft.admit(ctx, record); err != nil {
				t.Fatal(err)
			}
			wires = append(wires, wire)
		}
		commitFinancialSDK(t, app, financialDagBatchWire(t, base, wires...))
	}
	if backend.current.activeBlocks != target || app.state.FinancialDAG.Applied != 1 {
		t.Fatal("real signed window not filled")
	}
	before := canonical(app.state)
	when := time.Unix(0, backend.store.timeNs+1000000)
	proposal, err := app.PrepareProposal(ctx, &abci.RequestPrepareProposal{Time: when, MaxTxBytes: 64 * 1024 * 1024})
	if err != nil || len(proposal.Txs) != 1 || isDagBatch(proposal.Txs[0]) {
		t.Fatal("full window did not schedule a cut", err)
	}
	processed, err := app.ProcessProposal(ctx, &abci.RequestProcessProposal{Time: when, Txs: proposal.Txs})
	if err != nil || processed.Status != abci.ResponseProcessProposal_ACCEPT || !bytes.Equal(before, canonical(app.state)) {
		t.Fatal("uncertified cut changed state", err)
	}
	commitFinancialSDK(t, app, proposal.Txs[0])
	value := app.state.FinancialDAG
	if value.Epoch != 2 || value.ActiveBlocks != 0 || value.Blocks != uint64(target) || value.Authors[0].Sequence != uint64(target) || value.Applied != 1 {
		t.Fatal("cut lost original creator, money or counts", value)
	}
	proof, err := backend.Receipt(ctx, app.state, financialReceiptSelector{Block: firstID, Index: 0})
	if err != nil || checkFinancialCertifiedReceipt(proof, app.state, app.genesis) != nil {
		t.Fatal("old monetary receipt lost at automatic cut", err)
	}
	saved := canonical(app.state)
	_ = app.Close()
	reopened, err := newDagEnabledLedger(app.genesis, app.anchor, root, false)
	if err != nil {
		t.Fatal(err)
	}
	defer reopened.Close()
	if !bytes.Equal(saved, canonical(reopened.state)) {
		t.Fatal("automatic cut original history did not replay")
	}
}
