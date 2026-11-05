//go:build !js

package main

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"strconv"
	"strings"
	"testing"
	"time"

	abci "github.com/cometbft/cometbft/abci/types"
)

func preparePublicCandidate(t *testing.T, count int) (*Ledger, *financialNativeApplication, []byte, time.Time, map[string]ed25519.PrivateKey, string) {
	t.Helper()
	app, backend, keys, producers, root := publicProtocolSDKFixture(t)
	payer := keys[app.genesis.FinancialAccounts.Allocations[0].Address]
	payments := make([]Envelope, count)
	for index := range payments {
		payments[index] = publicFixturePayment(backend.current, payer, publicFixtureAddress(publicFixtureKey("cache-recipient:"+strconv.Itoa(index))), uint64(index), "7")
	}
	_, block, _ := publicFixtureBlock(t, backend.current, producers[0], publicFixtureKey("cache-independent-worker"), payments)
	raw := publicFixtureBatch(t, backend.current, nil, block)
	when := time.Unix(0, backend.store.timeNs+1000000)
	prepared, err := app.PrepareProposal(context.Background(), &abci.RequestPrepareProposal{Height: 1, Time: when, MaxTxBytes: 48 << 20, Txs: [][]byte{raw}})
	if err != nil || len(prepared.Txs) != 1 || !bytes.Equal(prepared.Txs[0], raw) {
		t.Fatal("exact single valid package changed or rejected", err)
	}
	if backend.candidate.entry == nil {
		t.Fatalf("ordinary %d-payment candidate unexpectedly bypassed bounded cache; wire=%d", count, len(raw))
	}
	if backend.candidate.entry.estimated > financialTransitionRetainedLimit {
		t.Fatal("retained candidate exceeded actual-walk budget")
	}
	return app, backend, prepared.Txs[0], when, keys, root
}

func TestFinancialCandidate5000ActualPaymentsReusePendingReceiptsAndColdReplay(t *testing.T) {
	app, backend, raw, when, keys, root := preparePublicCandidate(t, 5000)
	entry := backend.candidate.entry
	full := entry.execution
	if full.provisional || len(full.pending) != 1 || full.applied != 5000 || app.state.Height != 0 {
		t.Fatal("cached native candidate published or lost actual execution")
	}
	var identifier string
	for id, record := range full.pending {
		identifier = id
		if len(record.Receipts) != 5000 || record.Summary.Applied != 5000 {
			t.Fatal("full candidate lost originals or receipts")
		}
	}
	processed, err := app.ProcessProposal(context.Background(), &abci.RequestProcessProposal{Height: 1, Time: when, Txs: [][]byte{raw}})
	if err != nil || processed.Status != abci.ResponseProcessProposal_ACCEPT || backend.candidate.entry != entry || app.state.Height != 0 {
		t.Fatal("Process did not reuse private candidate without publishing it", err)
	}
	finalized, err := app.FinalizeBlock(context.Background(), &abci.RequestFinalizeBlock{Height: 1, Time: when, Txs: [][]byte{raw}})
	if err != nil || len(finalized.AppHash) != 32 || backend.staged != full || backend.candidate.entry != nil || app.state.Height != 0 {
		t.Fatal("Finalize failed to TAKE the full candidate", err)
	}
	if _, err := app.Commit(context.Background(), &abci.RequestCommit{}); err != nil {
		t.Fatal(err)
	}
	if app.state.FinancialDAG.Applied != 5000 || len(backend.current.pending) != 0 || backend.candidate.entry != nil {
		t.Fatal("commit lost payments or kept transient cache/originals")
	}
	before := canonical(app.state)
	if err := app.Close(); err != nil {
		t.Fatal(err)
	}
	reopened, err := newDagEnabledLedger(app.genesis, app.anchor, root, false)
	if err != nil {
		t.Fatal(err)
	}
	defer reopened.Close()
	cold := reopened.financial.(*financialNativeApplication)
	if cold.candidate.entry != nil || !bytes.Equal(before, canonical(reopened.state)) {
		t.Fatal("cache serialized or cold cryptographic replay changed state")
	}
	receipt, err := cold.Receipt(context.Background(), reopened.state, financialReceiptSelector{Block: identifier, Index: 4999})
	if err != nil || receipt.Receipt.Leaf.Outcome != "APPLIED" || checkFinancialCertifiedReceipt(receipt, reopened.state, reopened.genesis) != nil {
		t.Fatal("pending selected receipt was lost by cache reuse", err)
	}
	packet := publicFixturePacket(t, reopened, keys)
	packet.FinancialReceipt = &receipt
	index := 4999
	packet.ExpectedFinancialReceipt = &financialReceiptExpectation{Block: identifier, Index: &index, TransactionID: receipt.Receipt.Leaf.TransactionID}
	if result, err := verifyInput(packet); err != nil || result["financial_receipt_verified"] != true {
		t.Fatal("actual cold receipt and SDK certificate did not verify", err)
	}
	t.Logf("cache admitted real5000: wire=%d conservative-retained=%d limit=%d", len(raw), entry.estimated, financialTransitionRetainedLimit)
}

func TestFinancialCandidateIdentityUsesFullRootClockHeightGenesisSourceAndExactBytes(t *testing.T) {
	_, backend, raw, _, _, _ := preparePublicCandidate(t, 1)
	entry := *backend.candidate.entry
	for _, field := range []string{"genesis", "source", "state-root", "height", "time", "wire"} {
		backend.candidate.entry = &entry
		key := entry.key
		switch field {
		case "genesis":
			key.genesis = strings.Repeat("e", 64)
		case "source":
			key.source = strings.Repeat("e", 64)
		case "state-root":
			key.before = strings.Repeat("e", 64)
		case "height":
			key.height++
		case "time":
			key.when++
		case "wire":
			key.wire = strings.Repeat("e", 64)
		}
		if backend.candidate.matches(key, raw) || backend.candidate.entry != nil {
			t.Fatal("different candidate identity reused", field)
		}
	}
	backend.candidate.entry = &entry
	changed := append([]byte(nil), raw...)
	changed[len(changed)-1] ^= 1
	// Even a deliberately forced equal digest cannot authorize other bytes.
	if backend.candidate.matches(entry.key, changed) {
		t.Fatal("digest-only candidate match")
	}
	backend.candidate.entry = &entry
	if got := backend.candidate.take(entry.key, raw); got != entry.execution || backend.candidate.entry != nil {
		t.Fatal("TAKE leaked or cloned full pending execution")
	}
}

func TestFinancialCandidateProposalByteAliasDoesNotChangePrivateOriginal(t *testing.T) {
	_, backend, raw, _, _, _ := preparePublicCandidate(t, 1)
	owned := append([]byte(nil), backend.candidate.entry.raw...)
	raw[len(raw)-1] ^= 1
	if !bytes.Equal(backend.candidate.entry.raw, owned) || backend.candidate.matches(backend.candidate.entry.key, raw) {
		t.Fatal("proposal caller mutated a cached original or hit its key")
	}
}

func TestFinancialCandidateNeverReusesProvisionalMempoolEvaluation(t *testing.T) {
	app, backend, raw, when, _, _ := preparePublicCandidate(t, 1)
	backend.candidate.clear()
	checked, err := app.CheckTx(context.Background(), &abci.RequestCheckTx{Tx: raw})
	if err != nil || checked.Code != 0 || backend.candidate.entry != nil {
		t.Fatal("CheckTx cached a provisional outcome", err)
	}
	provisional, err := financialTransition(context.Background(), backend.current, raw, 0)
	key, ok := financialCandidateIdentity(backend.current, app.state, raw, when.UnixNano())
	if err != nil || !ok || !provisional.provisional || backend.candidate.retain(context.Background(), key, raw, provisional) {
		t.Fatal("provisional transition admitted to definitive cache", err)
	}
	if _, ok := financialCandidateIdentity(backend.current, app.state, raw, 0); ok {
		t.Fatal("zero consensus clock entered definitive identity")
	}
	processed, err := app.ProcessProposal(context.Background(), &abci.RequestProcessProposal{Height: 1, Time: when, Txs: [][]byte{raw}})
	if err != nil || processed.Status != abci.ResponseProcessProposal_ACCEPT || backend.candidate.entry == nil || backend.candidate.entry.execution.provisional {
		t.Fatal("independent definitive Process evaluation failed", err)
	}
}

func TestFinancialCandidateCancellationAndFailedFinalizeClearPrivateState(t *testing.T) {
	for _, phase := range []string{"prepare", "process", "finalize", "height", "close"} {
		t.Run(phase, func(t *testing.T) {
			app, backend, raw, when, _, _ := preparePublicCandidate(t, 1)
			ctx, cancel := context.WithCancel(context.Background())
			cancel()
			switch phase {
			case "prepare":
				if _, err := app.PrepareProposal(ctx, &abci.RequestPrepareProposal{Height: 1, Time: when, MaxTxBytes: 48 << 20, Txs: [][]byte{raw}}); err == nil {
					t.Fatal("cancelled prepare accepted")
				}
			case "process":
				response, err := app.ProcessProposal(ctx, &abci.RequestProcessProposal{Height: 1, Time: when, Txs: [][]byte{raw}})
				if err == nil && response.Status == abci.ResponseProcessProposal_ACCEPT {
					t.Fatal("cancelled Process accepted cached candidate")
				}
			case "finalize":
				if _, err := app.FinalizeBlock(ctx, &abci.RequestFinalizeBlock{Height: 1, Time: when, Txs: [][]byte{raw}}); err == nil {
					t.Fatal("cancelled finalize accepted")
				}
			case "height":
				if _, err := app.FinalizeBlock(context.Background(), &abci.RequestFinalizeBlock{Height: 2, Time: when, Txs: [][]byte{raw}}); err == nil {
					t.Fatal("wrong-height finalize accepted")
				}
			case "close":
				if err := app.Close(); err != nil {
					t.Fatal(err)
				}
			}
			if backend.candidate.entry != nil || backend.staged != nil || app.staged != nil || app.state.Height != 0 {
				t.Fatal("cancel/failure/close retained a candidate or published state")
			}
		})
	}
}

func TestFinancialCandidateHitStillChecksStoreAndExactDurableOriginals(t *testing.T) {
	for _, phase := range []string{"health", "process-stage", "finalize-stage"} {
		t.Run(phase, func(t *testing.T) {
			app, backend, raw, when, _, _ := preparePublicCandidate(t, 1)
			if phase == "health" {
				backend.store.failed = true
			} else if err := backend.store.db.Delete([]byte("c/"+hashHex(raw)), nil); err != nil {
				t.Fatal(err)
			}
			if phase == "finalize-stage" {
				if _, err := app.FinalizeBlock(context.Background(), &abci.RequestFinalizeBlock{Height: 1, Time: when, Txs: [][]byte{raw}}); err == nil {
					t.Fatal("cache bypassed missing durable original")
				}
			} else if _, err := app.ProcessProposal(context.Background(), &abci.RequestProcessProposal{Height: 1, Time: when, Txs: [][]byte{raw}}); err == nil {
				t.Fatal("cache bypassed store health or exact staged original")
			}
			if backend.candidate.entry != nil || backend.staged != nil || app.state.Height != 0 {
				t.Fatal("failed store published cached money")
			}
		})
	}
}

func TestFinancialCandidateChangedGenesisIsRevalidatedBeforeCacheHit(t *testing.T) {
	app, backend, raw, when, _, _ := preparePublicCandidate(t, 1)
	app.genesis.Protocol.MaxWorkHeights++
	response, err := app.ProcessProposal(context.Background(), &abci.RequestProcessProposal{Height: 1, Time: when, Txs: [][]byte{raw}})
	if err == nil && response.Status == abci.ResponseProcessProposal_ACCEPT || backend.candidate.entry != nil || app.state.Height != 0 {
		t.Fatal("mutated pinned genesis escaped entry validation")
	}
}

func TestFinancialCandidateResourceAndOperationsBypassChangeCostOnly(t *testing.T) {
	app, backend, raw, when, keys, _ := preparePublicCandidate(t, 1)
	entry := backend.candidate.entry
	backend.candidate.clear()
	if backend.candidate.retain(context.Background(), entry.key, make([]byte, financialTransitionWireLimit+1), entry.execution) {
		t.Fatal("oversize wire entered private cache")
	}
	var id string
	var record financialDagRecord
	for key, value := range entry.execution.pending {
		id, record = key, value
	}
	original := record.Raw
	record.Raw = make([]byte, financialTransitionRetainedLimit+1)
	entry.execution.pending[id] = record
	if backend.candidate.retain(context.Background(), entry.key, raw, entry.execution) {
		t.Fatal("large retained backing buffer bypassed actual memory walk")
	}
	record.Raw = original
	entry.execution.pending[id] = record
	if _, ok := financialCandidateIdentity(backend.current, app.state, []byte(`{"before":"cut"}`), when.UnixNano()); ok {
		t.Fatal("CUT entered ordinary-block cache")
	}
	payer := keys[app.genesis.FinancialAccounts.Allocations[0].Address]
	operation := protocolOperation{Schema: "gg.financial.protocol-operation.v1", Cancel: &protocolCancelBody{
		Genesis: app.anchor, Nonce: 0, Replaces: strings.Repeat("e", 64), Schema: "gg.financial.nonce-cancel.v1", Sender: publicFixtureAddress(payer)}}
	operation = publicFixtureAuthorize(t, backend.current, operation, payer, 0)
	opRaw := publicFixtureBatch(t, backend.current, []protocolOperation{operation})
	prepared, err := app.PrepareProposal(context.Background(), &abci.RequestPrepareProposal{Height: 1, Time: when, MaxTxBytes: 48 << 20, Txs: [][]byte{opRaw}})
	if err != nil || len(prepared.Txs) != 1 || backend.candidate.entry != nil {
		t.Fatal("ordinary operation changed validity or entered block cache", err)
	}
}
