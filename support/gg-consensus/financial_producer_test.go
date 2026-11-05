//go:build !js

package main

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"encoding/json"
	abci "github.com/cometbft/cometbft/abci/types"
	"os"
	"strconv"
	"strings"
	"testing"
)

func financialSessionSDKFixture(t *testing.T) (*Ledger, *financialNativeApplication, []ed25519.PrivateKey, []ed25519.PrivateKey, string) {
	t.Helper()
	model, accounts, producers := financialDagFixture(t)
	source := model.source
	source.Schema = "gg.financial-dag.source.v2"
	source.NetworkID = strings.Repeat("b", 64)
	genesis := model.genesis
	genesis.FinancialDAG = &source
	genesis.Schema = "gg.native.genesis.v5"
	root := t.TempDir()
	app, err := newFinancialLedger(genesis, hashHex(canonical(genesis)), root, true)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = app.Close() })
	return app, app.financial.(*financialNativeApplication), accounts, producers, root
}

func financialContextBlock(t *testing.T, app *Ledger, keys []ed25519.PrivateKey, producer int, inputs [][]byte) ([]byte, financialProducerContext) {
	t.Helper()
	backend := app.financial.(*financialNativeApplication)
	proof, err := backend.ProducerContext(context.Background(), app.state, producer)
	if err != nil {
		t.Fatal(err)
	}
	wire, _ := financialDagSignedBlock(t, backend.current, keys, producer, inputs, func(body *financialDagBlockBody) {
		body.Parents = []string{proof.Parent}
		body.Rank = proof.ParentRank + 1
		body.Sequence = proof.Sequence
	})
	return financialDagBatchWire(t, backend.current, wire), proof
}

func TestFinancialProducerContextCertifiesActualParentAndCutRank(t *testing.T) {
	app, backend, accounts, keys, _ := financialSessionSDKFixture(t)
	raw, first := financialContextBlock(t, app, keys, 0, [][]byte{testTx(app.genesis, app.anchor, accounts, 0, 1, "3", 0)})
	if first.Parent != backend.current.epochAnchor || first.ParentRank != 0 || first.Sequence != 1 || len(first.ParentPath) != 0 {
		t.Fatal("initial creator context not bound to financial genesis")
	}
	commitFinancialSDK(t, app, raw)
	parent, err := backend.ProducerContext(context.Background(), app.state, 0)
	if err != nil || parent.Parent != app.state.FinancialDAG.Authors[0].Head || parent.ParentRank != 1 || parent.Sequence != 2 || len(parent.ParentPath) == 0 {
		t.Fatal("real creator head not proved", err)
	}
	packet := segmentedSDKPacket(t, app)
	packet.FinancialProducer = &parent
	verified, err := verifyInput(packet)
	if err != nil || verified["financial_producer_verified"] != true || verified["financial_parent"] != parent.Parent {
		t.Fatal("creator context not authenticated by SDK certificate", err)
	}
	if target := os.Getenv("GG_PUBLIC_FINANCIAL_PRODUCER_OUTPUT"); target != "" {
		output, err := os.OpenFile(target, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
		if err != nil {
			t.Fatal(err)
		}
		_, writeErr := output.Write(canonical(packet))
		closeErr := output.Close()
		if writeErr != nil || closeErr != nil {
			t.Fatal("public producer proof export failed")
		}
	}
	for _, mutate := range []func(*financialProducerContext){
		func(p *financialProducerContext) { p.Parent = DagZero }, func(p *financialProducerContext) { p.ParentRank++ },
		func(p *financialProducerContext) { p.Sequence++ }, func(p *financialProducerContext) { p.Epoch++ },
		func(p *financialProducerContext) { p.Producer = 1 }, func(p *financialProducerContext) { p.SourceHash = DagZero },
		func(p *financialProducerContext) { p.ParentPath[0].Value.Record = nil },
	} {
		var changed financialProducerContext
		_ = json.Unmarshal(canonical(parent), &changed)
		mutate(&changed)
		if checkFinancialProducerContext(changed, app.state, app.genesis) == nil {
			t.Fatal("forged producer context accepted")
		}
	}
	cut, err := backend.current.prepareCut()
	if err != nil {
		t.Fatal(err)
	}
	commitFinancialSDK(t, app, cut)
	if app.state.FinancialDAG.Authors[0].Epoch != "1" || app.state.FinancialDAG.EpochBaseRank != "1" {
		t.Fatal("cut erased creator epoch or rank")
	}
	// Another producer may run far ahead. The idle creator starts at the CUT's
	// rank, never an unproved current global rank or an archived old parent.
	for index := 0; index < 5; index++ {
		raw, _ = financialContextBlock(t, app, keys, 1, nil)
		commitFinancialSDK(t, app, raw)
	}
	raw, slow := financialContextBlock(t, app, keys, 0, [][]byte{testTx(app.genesis, app.anchor, accounts, 0, 1, "5", 1)})
	if slow.Parent != app.state.FinancialDAG.LastCut || slow.ParentRank != 1 || slow.Sequence != 2 || len(slow.ParentPath) != 0 || app.state.FinancialDAG.LastRank != 6 {
		t.Fatal("slow producer was forced onto fast creator's rank")
	}
	commitFinancialSDK(t, app, raw)
	if app.state.FinancialDAG.Applied != 2 || app.state.FinancialDAG.Authors[0].Epoch != "2" {
		t.Fatal("certified slow branch did not execute real payments")
	}
}

func TestFinancialProducerHistoryMembershipSurvivesAVLRotations(t *testing.T) {
	app, backend, _, keys, _ := financialSessionSDKFixture(t)
	for index := 0; index < 130; index++ {
		raw, _ := financialContextBlock(t, app, keys, index%6, nil)
		commitFinancialSDK(t, app, raw)
		if index%13 == 0 {
			for producer := 0; producer < 6; producer++ {
				proof, err := backend.ProducerContext(context.Background(), app.state, producer)
				if err != nil || checkFinancialProducerContext(proof, app.state, app.genesis) != nil {
					t.Fatal("rotated history context invalid", index, producer, err)
				}
			}
		}
	}
	proof, err := backend.ProducerContext(context.Background(), app.state, 0)
	if err != nil {
		t.Fatal(err)
	}
	changed := proof
	changed.ParentPath = append(append([]dagHistoryBody{}, proof.ParentPath...), proof.ParentPath[len(proof.ParentPath)-1])
	if checkFinancialProducerContext(changed, app.state, app.genesis) == nil {
		t.Fatal("extra membership frames accepted")
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := backend.ProducerContext(ctx, app.state, 0); err == nil {
		t.Fatal("canceled context produced authority")
	}
}

func TestFinancialProducerRetainedContextIsBoundedAndRebuiltByColdReplay(t *testing.T) {
	app, backend, _, keys, root := financialSessionSDKFixture(t)
	var old State
	for index := 0; index < financialProducerViewLimit+3; index++ {
		raw, _ := financialContextBlock(t, app, keys, 0, nil)
		commitFinancialSDK(t, app, raw)
		if index == 0 {
			old = copyState(app.state)
		}
	}
	if len(backend.store.producerViews) != financialProducerViewLimit {
		t.Fatal("creator proof retention unbounded")
	}
	if _, err := backend.ProducerContext(context.Background(), old, 0); err == nil {
		t.Fatal("evicted creator view silently substituted current context")
	}
	current, err := backend.ProducerContext(context.Background(), app.state, 0)
	if err != nil {
		t.Fatal(err)
	}
	_ = app.Close()
	reopened, err := newFinancialLedger(app.genesis, app.anchor, root, false)
	if err != nil {
		t.Fatal(err)
	}
	defer reopened.Close()
	restored, err := reopened.financial.ProducerContext(context.Background(), reopened.state, 0)
	if err != nil || !bytes.Equal(canonical(current), canonical(restored)) {
		t.Fatal("cold creator context differs", err)
	}
	legacy, _, _, _, _ := financialSDKFixture(t)
	if _, err := legacy.financial.ProducerContext(context.Background(), legacy.state, 0); err == nil {
		t.Fatal("unbound v1 source silently gained production context")
	}
}

func TestFinancialProducerVersionedMetadataCannotBeStrippedOrReinterpreted(t *testing.T) {
	app, _, _, keys, _ := financialSessionSDKFixture(t)
	raw, _ := financialContextBlock(t, app, keys, 0, nil)
	commitFinancialSDK(t, app, raw)
	for _, mutate := range []func(*financialDagCommitment){
		func(v *financialDagCommitment) { v.EpochBaseRank = "" }, func(v *financialDagCommitment) { v.EpochBaseRank = "01" },
		func(v *financialDagCommitment) { v.Authors[0].Epoch = "" }, func(v *financialDagCommitment) { v.Authors[0].Epoch = "0" },
		func(v *financialDagCommitment) { v.Schema = "gg.financial-dag.commitment.v1" },
	} {
		state := copyState(app.state)
		mutate(state.FinancialDAG)
		sealState(&state)
		if validateState(state, app.genesis, app.anchor) == nil {
			t.Fatal("required source-v2 metadata stripped")
		}
	}
	query, err := app.Query(context.Background(), &abci.RequestQuery{Path: "/gg/financial-dag/producer-context", Data: []byte(`{"producer_index":0}`)})
	if err != nil || query.Code != 0 {
		t.Fatal("real producer query failed", err)
	}
}

func TestFinancialSourceAcceptsIndependentPythonSignedFinancialSession(t *testing.T) {
	target := os.Getenv("GG_PUBLIC_FINANCIAL_SESSION_FIXTURE")
	if target == "" {
		t.Skip("requires explicit public financial session fixture")
	}
	raw, err := os.ReadFile(target)
	if err != nil {
		t.Fatal(err)
	}
	var fixture struct {
		Genesis     Genesis `json:"genesis"`
		GenesisHash string  `json:"genesis_hash"`
		SourceHash  string  `json:"source_hash"`
	}
	if decodeStrict(raw, &fixture) != nil || validateGenesis(fixture.Genesis, fixture.GenesisHash) != nil || fixture.Genesis.FinancialDAG == nil || fixture.Genesis.FinancialDAG.Schema != "gg.financial-dag.source.v2" {
		t.Fatal("independent signed financial membership not valid")
	}
	if fixture.Genesis.FinancialDAG.hash() != fixture.SourceHash {
		t.Fatal("Python/Go source domain disagreed")
	}
	state := initialState(fixture.Genesis, fixture.GenesisHash)
	if validateState(state, fixture.Genesis, fixture.GenesisHash) != nil || state.FinancialDAG.Schema != "gg.financial-dag.commitment.v2" || state.FinancialDAG.EpochBaseRank != "0" {
		t.Fatal("financial session state not versioned correctly")
	}
	for _, author := range state.FinancialDAG.Authors {
		if author.Epoch != "0" || strconv.FormatUint(author.Sequence, 10) != "0" {
			t.Fatal("new creator has prior authority")
		}
	}
}
