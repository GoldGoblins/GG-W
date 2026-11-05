//go:build !js

package main

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"errors"
	abci "github.com/cometbft/cometbft/abci/types"
	"github.com/syndtr/goleveldb/leveldb"
	"github.com/syndtr/goleveldb/leveldb/opt"
	"path/filepath"
	"testing"
	"time"
)

func financialSDKFixture(t *testing.T) (*Ledger, *financialNativeApplication, []ed25519.PrivateKey, []ed25519.PrivateKey, string) {
	t.Helper()
	model, accounts, producers := financialDagFixture(t)
	genesis := model.genesis
	source := model.source
	genesis.FinancialDAG, genesis.Schema = &source, "gg.native.genesis.v5"
	anchor := hashHex(canonical(genesis))
	root := t.TempDir()
	app, err := newDagEnabledLedger(genesis, anchor, root, true)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = app.Close() })
	return app, app.financial.(*financialNativeApplication), accounts, producers, root
}

func commitFinancialSDK(t *testing.T, app *Ledger, raw []byte) {
	t.Helper()
	backend := app.financial.(*financialNativeApplication)
	txs := [][]byte{}
	if raw != nil {
		txs = append(txs, raw)
	}
	when := time.Unix(0, backend.store.timeNs+1000000)
	before := canonical(app.state)
	finalized, err := app.FinalizeBlock(context.Background(), &abci.RequestFinalizeBlock{Height: app.state.Height + 1, Time: when, Txs: txs})
	if err != nil || !bytes.Equal(before, canonical(app.state)) || len(finalized.AppHash) != 32 {
		t.Fatal("finalize published or failed", err)
	}
	if _, err := app.Commit(context.Background(), &abci.RequestCommit{}); err != nil {
		t.Fatal(err)
	}
}

func TestFinancialSDK5000PaymentsAreProposedCommittedAndColdReplayed(t *testing.T) {
	app, backend, accounts, producers, root := financialSDKFixture(t)
	inputs := make([][]byte, 5000)
	for index := range inputs {
		inputs[index] = testTx(app.genesis, app.anchor, accounts, 0, 1, "1", uint64(index))
	}
	wire, _ := financialDagSignedBlock(t, backend.current, producers, 0, inputs, nil)
	batch := financialDagBatchWire(t, backend.current, wire)
	before := canonical(app.state)
	ctx := context.Background()
	checked, err := app.CheckTx(ctx, &abci.RequestCheckTx{Tx: batch})
	if err != nil || checked.Code != 0 {
		t.Fatal(err, checked)
	}
	native := testTx(app.genesis, app.anchor, accounts, 0, 1, "1", 0)
	denied, err := app.CheckTx(ctx, &abci.RequestCheckTx{Tx: native})
	if err != nil || denied.Code == 0 {
		t.Fatal("standalone money escaped complete financial journal")
	}
	when := time.Unix(0, backend.store.timeNs+1000000)
	proposal, err := app.PrepareProposal(ctx, &abci.RequestPrepareProposal{Time: when, MaxTxBytes: 64 * 1024 * 1024, Txs: [][]byte{native, batch}})
	if err != nil || len(proposal.Txs) != 1 || !bytes.Equal(proposal.Txs[0], batch) {
		t.Fatal("proposal did not select exact financial batch", err)
	}
	processed, err := app.ProcessProposal(ctx, &abci.RequestProcessProposal{Time: when, Txs: proposal.Txs})
	if err != nil || processed.Status != abci.ResponseProcessProposal_ACCEPT || !bytes.Equal(before, canonical(app.state)) {
		t.Fatal("proposal changed money before commit", err)
	}
	commitFinancialSDK(t, app, batch)
	if app.state.FinancialDAG.Applied != 5000 || app.state.FinancialDAG.Attempts != 5000 || app.state.AccountRoot == initialState(app.genesis, app.anchor).AccountRoot {
		t.Fatal("SDK selected counters without real money")
	}
	packet := segmentedSDKPacket(t, app)
	result, err := verifyInput(packet)
	if err != nil || result["verified"] != true || result["financial_receipt_verified"] != false {
		t.Fatal("financial SDK root certificate rejected or overclaimed", err)
	}
	snapshot := canonical(app.state)
	if app.Close() != nil {
		t.Fatal("close failed")
	}
	reopened, err := newDagEnabledLedger(app.genesis, app.anchor, root, false)
	if err != nil {
		t.Fatal(err)
	}
	defer reopened.Close()
	if !bytes.Equal(snapshot, canonical(reopened.state)) {
		t.Fatal("cold original-signed financial replay changed money or commitment")
	}
	if _, err := newLedger(app.genesis, app.anchor, t.TempDir()); err == nil {
		t.Fatal("financial mode used legacy snapshot store")
	}
}

func TestFinancialSDKCompleteCutEmptyHeightAndConflictingPaymentReplay(t *testing.T) {
	app, backend, accounts, producers, root := financialSDKFixture(t)
	payment := testTx(app.genesis, app.anchor, accounts, 0, 1, "7", 0)
	wire, _ := financialDagSignedBlock(t, backend.current, producers, 0, [][]byte{payment}, nil)
	commitFinancialSDK(t, app, financialDagBatchWire(t, backend.current, wire))
	beforeEmpty := app.state.StateRoot
	commitFinancialSDK(t, app, nil)
	if app.state.StateRoot != beforeEmpty {
		t.Fatal("empty SDK height changed money")
	}
	cut, err := backend.current.prepareCut()
	if err != nil {
		t.Fatal(err)
	}
	checked, err := app.CheckTx(context.Background(), &abci.RequestCheckTx{Tx: cut})
	if err != nil || checked.Code != 0 {
		t.Fatal("cut mempool check failed", err)
	}
	commitFinancialSDK(t, app, cut)
	wire, _ = financialDagSignedBlock(t, backend.current, producers, 0, [][]byte{payment, testTx(app.genesis, app.anchor, accounts, 0, 1, "9", 1)}, nil)
	commitFinancialSDK(t, app, financialDagBatchWire(t, backend.current, wire))
	if app.state.FinancialDAG.Applied != 2 || app.state.FinancialDAG.Rejected != 1 || app.state.FinancialDAG.Authors[0].Sequence != 2 || app.state.FinancialDAG.Epoch != 2 {
		t.Fatal("cut lost funds, rejection, identity or sequence")
	}
	// SDK query retention is bounded, but every original earlier payment remains
	// mandatory for replay after it leaves the retained public state window.
	for index := 0; index < HistoryLimit+1; index++ {
		commitFinancialSDK(t, app, nil)
	}
	if len(app.history) != HistoryLimit {
		t.Fatal("query history unbounded")
	}
	snapshot := canonical(app.state)
	_ = app.Close()
	reopened, err := newDagEnabledLedger(app.genesis, app.anchor, root, false)
	if err != nil {
		t.Fatal(err)
	}
	defer reopened.Close()
	if !bytes.Equal(snapshot, canonical(reopened.state)) {
		t.Fatal("full pre-cut originals did not survive retained-query window")
	}
}

func TestFinancialSDKWriteFaultAndAmbiguousCommitNeverPublishUncertainMoney(t *testing.T) {
	for _, durable := range []bool{false, true} {
		t.Run(map[bool]string{false: "no_write", true: "durable_then_error"}[durable], func(t *testing.T) {
			app, backend, accounts, producers, root := financialSDKFixture(t)
			wire, _ := financialDagSignedBlock(t, backend.current, producers, 0, [][]byte{testTx(app.genesis, app.anchor, accounts, 0, 1, "17", 0)}, nil)
			raw := financialDagBatchWire(t, backend.current, wire)
			before := canonical(app.state)
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
				return errors.New("owned injected uncertain IO")
			}
			if _, err := app.Commit(context.Background(), &abci.RequestCommit{}); err == nil || !bytes.Equal(before, canonical(app.state)) || backend.store.health() == nil {
				t.Fatal("ambiguous commit published or remained healthy")
			}
			if _, err := app.CheckTx(context.Background(), &abci.RequestCheckTx{Tx: raw}); err == nil {
				t.Fatal("failed store continued accepting")
			}
			_ = app.Close()
			reopened, err := newDagEnabledLedger(app.genesis, app.anchor, root, false)
			if err != nil {
				t.Fatal(err)
			}
			defer reopened.Close()
			expected := before
			if durable {
				expected = after
			}
			if !bytes.Equal(expected, canonical(reopened.state)) {
				t.Fatal("uncertain commit did not recover exact old or new journal head")
			}
		})
	}
}

func TestFinancialSDKMissingCorruptOrExtraJournalFailsClosed(t *testing.T) {
	for _, kind := range []string{"missing", "changed", "extra", "head"} {
		t.Run(kind, func(t *testing.T) {
			app, _, _, _, root := financialSDKFixture(t)
			commitFinancialSDK(t, app, nil)
			commitFinancialSDK(t, app, nil)
			_ = app.Close()
			db, err := leveldb.OpenFile(filepath.Join(root, "gg-financial-dag.leveldb"), &opt.Options{ErrorIfMissing: true})
			if err != nil {
				t.Fatal(err)
			}
			switch kind {
			case "missing":
				err = db.Delete([]byte(financialHeightKey(1)), &opt.WriteOptions{Sync: true})
			case "changed":
				err = db.Put([]byte(financialHeightKey(1)), []byte(`{}`), &opt.WriteOptions{Sync: true})
			case "extra":
				err = db.Put([]byte(financialHeightKey(3)), []byte(`{}`), &opt.WriteOptions{Sync: true})
			case "head":
				err = db.Put([]byte("head"), []byte(`{}`), &opt.WriteOptions{Sync: true})
			}
			if err != nil {
				t.Fatal(err)
			}
			_ = db.Close()
			if reopened, err := newDagEnabledLedger(app.genesis, app.anchor, root, false); err == nil {
				reopened.Close()
				t.Fatal("damaged originals recreated or trusted snapshot")
			}
		})
	}
}

func TestFinancialSDKCandidateLeaseBoundsAndPrepareIOFailure(t *testing.T) {
	app, backend, _, producers, root := financialSDKFixture(t)
	wire, _ := financialDagSignedBlock(t, backend.current, producers, 0, nil, nil)
	raw := financialDagBatchWire(t, backend.current, wire)
	if second, err := newDagEnabledLedger(app.genesis, app.anchor, root, false); err == nil {
		second.Close()
		t.Fatal("two writers acquired financial store")
	}
	if err := backend.store.stage(context.Background(), raw); err != nil {
		t.Fatal(err)
	}
	_ = app.Close()
	app2, err := newDagEnabledLedger(app.genesis, app.anchor, root, false)
	if err != nil {
		t.Fatal(err)
	}
	defer app2.Close()
	backend2 := app2.financial.(*financialNativeApplication)
	if app2.state.Height != 0 || backend2.current.blocks != 0 || len(backend2.store.candidates) != 1 {
		t.Fatal("unselected candidate became committed on restart")
	}
	commitFinancialSDK(t, app2, nil)
	if len(backend2.store.candidates) != 0 {
		t.Fatal("empty commit did not release bounded candidate credit")
	}
	backend2.store.write = func(*leveldb.Batch) error { return errors.New("owned staging IO fault") }
	if _, err := app2.PrepareProposal(context.Background(), &abci.RequestPrepareProposal{Time: time.Unix(0, backend2.store.timeNs+1000000), MaxTxBytes: 64 * 1024 * 1024, Txs: [][]byte{raw}}); err == nil || app2.state.Height != 1 {
		t.Fatal("vote preparation escaped failed original-byte sync")
	}
}

func TestFinancialSDKInvalidFinalizeAndSubstitutedPublicCommitmentsRejected(t *testing.T) {
	app, backend, accounts, producers, _ := financialSDKFixture(t)
	wire, _ := financialDagSignedBlock(t, backend.current, producers, 0, [][]byte{testTx(app.genesis, app.anchor, accounts, 0, 1, "5", 0)}, nil)
	raw := financialDagBatchWire(t, backend.current, wire)
	ctx := context.Background()
	when := time.Unix(0, backend.store.timeNs+1000000)
	for _, request := range []*abci.RequestFinalizeBlock{
		{Height: 2, Time: when, Txs: [][]byte{raw}}, {Height: 1, Time: when, Txs: [][]byte{raw, raw}},
		{Height: 1, Time: time.Unix(0, backend.store.timeNs-1), Txs: [][]byte{raw}},
		{Height: 1, Time: when, Txs: [][]byte{testTx(app.genesis, app.anchor, accounts, 0, 1, "5", 0)}},
	} {
		if _, err := app.FinalizeBlock(ctx, request); err == nil || app.staged != nil || app.state.Height != 0 {
			t.Fatal("invalid finalize staged or published money")
		}
	}
	commitFinancialSDK(t, app, raw)
	for _, mutate := range []func(*financialDagCommitment){
		func(value *financialDagCommitment) { value.SourceHash = DagZero },
		func(value *financialDagCommitment) { value.Authors[0].Sequence++ },
		func(value *financialDagCommitment) { value.Applied++ },
		func(value *financialDagCommitment) { value.Epoch++ },
		func(value *financialDagCommitment) { value.AccountRoot = DagZero },
	} {
		state := copyState(app.state)
		mutate(state.FinancialDAG)
		sealState(&state)
		if validateState(state, app.genesis, app.anchor) == nil {
			t.Fatal("substituted public financial shape accepted")
		}
	}
	query, err := app.Query(ctx, &abci.RequestQuery{Path: "/gg/dag/commitment"})
	if err != nil || query.Code != 0 || !bytes.Equal(query.Value, canonical(app.state.FinancialDAG)) {
		t.Fatal("common DAG query did not report real financial commitment")
	}
}
