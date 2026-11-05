package main

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"encoding/hex"
	"encoding/json"
	"sort"
	"strconv"
	"strings"
	"testing"
)

// Pure transition tests use real account/producer signatures, not SDK proofs.
func financialLineageFixture(t *testing.T) (*financialDagExecution, []ed25519.PrivateKey, []ed25519.PrivateKey) {
	t.Helper()
	old, accounts, producers := financialDagFixture(t)
	source := old.source
	source.Schema = financialLineageSourceSchema
	source.NetworkID = strings.Repeat("c", 64)
	source.Policy = source.rules()
	genesis := old.genesis
	genesis.Schema = "gg.native.genesis.v5"
	genesis.FinancialDAG = &source
	execution, err := newFinancialDagExecution(genesis, hashHex(canonical(genesis)), source)
	if err != nil {
		t.Fatal(err)
	}
	return execution, accounts, producers
}

func financialLineageBlock(t *testing.T, base *financialDagExecution, keys []ed25519.PrivateKey, producer int, inputs [][]byte, change func(*financialDagBlockBody)) ([]byte, string) {
	t.Helper()
	parent := base.heads[producer]
	rank := uint64(0)
	if parent != financialDagOrigin(base.source, base.anchor) {
		leaf, exists, err := base.lineage.get("b/" + parent)
		if err != nil || !exists || leaf.Record == nil {
			t.Fatal("missing selected lineage", err)
		}
		rank = uint64(leaf.Record.Rank)
	}
	body := financialDagBlockBody{CreatedAtNs: uint64(base.timeNs), Epoch: base.epoch, GenesisHash: base.anchor, Parents: []string{parent}, Payments: []Envelope{}, Producer: producer, Rank: rank + 1,
		Schema: "gg.financial-dag.block.v1", Sequence: base.authors[producer].Sequence + 1, SourceHash: base.source.hash()}
	for _, raw := range inputs {
		var row Envelope
		if decodeStrict(raw, &row) != nil {
			t.Fatal("invalid account input")
		}
		body.Payments = append(body.Payments, row)
	}
	if change != nil {
		change(&body)
	}
	sort.Strings(body.Parents)
	body.PaymentRoot = financialDagPaymentRoot(body.Payments)
	raw := canonical(financialDagBlock{Body: body, Signature: hex.EncodeToString(ed25519.Sign(keys[producer], append([]byte(financialDomain+"DAG-BLOCK-SIGN\x00"), canonical(body)...)))})
	return raw, hashHex(append([]byte(financialDomain+"DAG-BLOCK\x00"), raw...))
}

func financialLineageSelect(t *testing.T, base *financialDagExecution, raws ...[]byte) *financialDagExecution {
	t.Helper()
	next, err := base.applyBatch(context.Background(), financialDagBatchWire(t, base, raws...), base.timeNs)
	if err != nil {
		t.Fatal(err)
	}
	return next
}

func financialLineageCut(t *testing.T, base *financialDagExecution) *financialDagExecution {
	t.Helper()
	cut, err := base.prepareCut()
	if err != nil {
		t.Fatal(err)
	}
	next, err := base.applyCut(context.Background(), cut, base.timeNs)
	if err != nil {
		t.Fatal(err)
	}
	return next
}

func TestFinancialLineageSameOriginalsRemainEligibleAcrossThreeCuts(t *testing.T) {
	base, accounts, keys := financialLineageFixture(t)
	first, id1 := financialLineageBlock(t, base, keys, 0, [][]byte{testTx(base.genesis, base.anchor, accounts, 0, 1, "3", 0)}, nil)
	planned := financialLineageSelect(t, base, first)
	second, id2 := financialLineageBlock(t, planned, keys, 0, [][]byte{testTx(base.genesis, base.anchor, accounts, 0, 1, "3", 1)}, nil)
	for turn := 0; turn < 3; turn++ {
		fast, _ := financialLineageBlock(t, base, keys, 1, [][]byte{testTx(base.genesis, base.anchor, accounts, 1, 2, "1", uint64(turn))}, nil)
		base = financialLineageCut(t, financialLineageSelect(t, base, fast))
	}
	if base.epoch != 4 || base.authors[0].Sequence != 0 {
		t.Fatal("unexpected baseline")
	}
	base = financialLineageSelect(t, base, first, second)
	if base.applied != 5 || base.rejected != 0 || base.authors[0].Epoch != "1" || base.authors[0].Head != id2 || base.lastRank != 3 {
		t.Fatal("changed late-original semantics")
	}
	for _, id := range []string{id1, id2} {
		record := base.pending[id]
		if record.Context.Epoch != 4 {
			t.Fatal("origin epoch confused with execution epoch")
		}
	}
	base = financialLineageCut(t, base)
	state, err := financialNativeState(initialState(base.genesis, base.anchor), base, int64(base.checkpoint))
	if err != nil {
		t.Fatal(err)
	}
	views, err := financialProducerViews(nil, base)
	if err != nil {
		t.Fatal(err)
	}
	proof, err := makeFinancialProducerContext(context.Background(), state, base.genesis, 0, views)
	if err != nil || proof.Parent != id2 || proof.ParentRank != 2 || proof.Epoch != 5 || len(proof.ParentPath) == 0 {
		t.Fatal("lost old creator after cut", err)
	}
	if _, err = base.applyBatch(context.Background(), financialDagBatchWire(t, base, first), base.timeNs); err == nil {
		t.Fatal("selected original replayed after cut")
	}
}

func TestFinancialLineageRetainsOlderNonCreatorParentsAndRejectsUnknownOrFuture(t *testing.T) {
	base, accounts, keys := financialLineageFixture(t)
	other, otherID := financialLineageBlock(t, base, keys, 2, [][]byte{testTx(base.genesis, base.anchor, accounts, 2, 3, "1", 0)}, nil)
	base = financialLineageSelect(t, base, other)
	delayed, _ := financialLineageBlock(t, base, keys, 0, [][]byte{testTx(base.genesis, base.anchor, accounts, 0, 1, "1", 0)}, func(body *financialDagBlockBody) { body.Parents = append(body.Parents, otherID); body.Rank = 2 })
	for turn := 1; turn < 4; turn++ {
		fast, _ := financialLineageBlock(t, base, keys, 2, [][]byte{testTx(base.genesis, base.anchor, accounts, 2, 3, "1", uint64(turn))}, nil)
		base = financialLineageCut(t, financialLineageSelect(t, base, fast))
	}
	for _, change := range []func(*financialDagBlockBody){
		func(body *financialDagBlockBody) {
			body.Parents = append(body.Parents, strings.Repeat("e", 64))
			body.Rank = 2
		},
		func(body *financialDagBlockBody) { body.Epoch = base.epoch + 1 },
		func(body *financialDagBlockBody) { body.Rank++ },
	} {
		invalid, _ := financialLineageBlock(t, base, keys, 0, [][]byte{testTx(base.genesis, base.anchor, accounts, 0, 1, "1", 0)}, change)
		if _, err := base.applyBatch(context.Background(), financialDagBatchWire(t, base, invalid), base.timeNs); err == nil {
			t.Fatal("invalid lineage parent/epoch/rank accepted")
		}
	}
	selected := financialLineageSelect(t, base, delayed)
	if selected.authors[0].Epoch != "1" || selected.applied != 5 {
		t.Fatal("old non-creator dependency lost")
	}
}

func TestFinancialLineageIndependentParallelRanksNeedNotExceedCutCount(t *testing.T) {
	base, accounts, keys := financialLineageFixture(t)
	raws := [][]byte{}
	for producer := 0; producer < 6; producer++ {
		raw, _ := financialLineageBlock(t, base, keys, producer, [][]byte{testTx(base.genesis, base.anchor, accounts, 0, 1, "1", uint64(producer))}, nil)
		raws = append(raws, raw)
	}
	for _, raw := range raws {
		base = financialLineageCut(t, financialLineageSelect(t, base, raw))
	}
	value, err := base.commitment()
	if err != nil || base.epoch != 7 || base.lastRank != 1 || base.applied != 6 || value.LineageRoot == DagZero || value.IndexRoot != DagZero {
		t.Fatal("cut count reintroduced global rank dependency", err)
	}
	if validateFinancialCommitment(value, base.genesis, base.anchor) != nil {
		t.Fatal("valid independent ranks rejected")
	}
}

func TestFinancialLineagePolicyAndCommitmentVersionsCannotBeMixed(t *testing.T) {
	base, _, _ := financialLineageFixture(t)
	bad := base.source
	bad.Policy = financialDagRules()
	if bad.validate(base.genesis, base.anchor) == nil {
		t.Fatal("new rules activated under legacy policy")
	}
	value, _ := base.commitment()
	value.LineageRoot = ""
	if validateFinancialCommitment(value, base.genesis, base.anchor) == nil {
		t.Fatal("source-v3 without lineage commitment")
	}
	old, _, _ := financialDagFixture(t)
	old.source.Schema = "gg.financial-dag.source.v2"
	old.source.NetworkID = strings.Repeat("b", 64)
	value.Schema = "gg.financial-dag.commitment.v2"
	value.LineageRoot = DagZero
	if validateFinancialVersionFields(value, old.source) == nil {
		t.Fatal("source-v2 accepted source-v3 root")
	}
}

func TestFinancialLineageCanonicalCommitmentMatchesPublicSortedJSON(t *testing.T) {
	base, accounts, keys := financialLineageFixture(t)
	check := func(value any) {
		t.Helper()
		raw := canonical(value)
		var generic any
		if json.Unmarshal(raw, &generic) != nil || !bytes.Equal(raw, canonical(generic)) {
			t.Fatal("Go financial encoding differs from the sorted public/Python JSON encoding")
		}
	}
	value, err := base.commitment()
	if err != nil {
		t.Fatal(err)
	}
	check(value)
	raw, _ := financialLineageBlock(t, base, keys, 0, [][]byte{testTx(base.genesis, base.anchor, accounts, 0, 1, "1", 0)}, nil)
	base = financialLineageCut(t, financialLineageSelect(t, base, raw))
	value, err = base.commitment()
	if err != nil {
		t.Fatal(err)
	}
	check(value)
	state, err := financialNativeState(initialState(base.genesis, base.anchor), base, int64(base.checkpoint))
	if err != nil {
		t.Fatal(err)
	}
	check(state)
}

func TestFinancialLineageProofsRemainIndexedPastTheActiveWindow(t *testing.T) {
	base, accounts, keys := financialLineageFixture(t)
	oldID := ""
	for number := 0; number < 4100; number++ {
		raw, id := financialLineageBlock(t, base, keys, 0, [][]byte{testTx(base.genesis, base.anchor, accounts, 0, 1, "1", uint64(number))}, nil)
		base = financialLineageSelect(t, base, raw)
		if number == 0 {
			oldID = id
		}
		if number%32 == 31 {
			base = financialLineageCut(t, base)
		}
	}
	path, err := financialHistoryWitness(context.Background(), base.lineage, "b/"+oldID)
	if err != nil || len(path) > 32 {
		t.Fatal("global parent lookup is not indexed", err, len(path))
	}
	value, _ := base.commitment()
	leaf, err := checkFinancialHistoryWitness(value.LineageRoot, "b/"+oldID, path)
	if err != nil || leaf.Record == nil || leaf.Record.Hash != oldID || base.applied != 4100 {
		t.Fatal("lost retained lineage", err)
	}
	if strconv.FormatUint(base.authors[0].Sequence, 10) != "4100" {
		t.Fatal("producer sequence restarted")
	}
}
