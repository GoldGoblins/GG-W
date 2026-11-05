package main

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"os"
	"sort"
	"strconv"
	"strings"
	"testing"
)

func financialDagFixture(t *testing.T) (*financialDagExecution, []ed25519.PrivateKey, []ed25519.PrivateKey) {
	t.Helper()
	genesis, anchor, accounts, _ := testGenesis()
	source := financialDagSource{AllowedProducers: []int{0, 1, 2, 3, 4, 5}, NativeChainID: genesis.ChainID,
		Policy: financialDagRules(), Schema: "gg.financial-dag.source.v1", SignatureProfile: TransactionSignatureProfile,
		StartedAtNs: strconv.FormatInt(genesis.GenesisTime*1000000000, 10)}
	producers := make([]ed25519.PrivateKey, 6)
	for index := range producers {
		seed := sha256.Sum256([]byte("GG PUBLIC financial DAG producer " + strconv.Itoa(index)))
		producers[index] = ed25519.NewKeyFromSeed(seed[:])
		source.Producers = append(source.Producers, hex.EncodeToString(producers[index].Public().(ed25519.PublicKey)))
	}
	execution, err := newFinancialDagExecution(genesis, anchor, source)
	if err != nil {
		t.Fatal(err)
	}
	return execution, accounts, producers
}

func financialDagSignedBlock(t *testing.T, base *financialDagExecution, keys []ed25519.PrivateKey, producer int, inputs [][]byte, update func(*financialDagBlockBody)) ([]byte, string) {
	t.Helper()
	body := financialDagBlockBody{CreatedAtNs: uint64(base.timeNs), Epoch: base.epoch, GenesisHash: base.anchor,
		Parents: []string{base.heads[producer]}, Payments: []Envelope{}, Producer: producer, Rank: base.lastRank + 1,
		Schema: "gg.financial-dag.block.v1", Sequence: base.authors[producer].Sequence + 1, SourceHash: base.source.hash()}
	if base.heads[producer] != base.epochAnchor {
		value, exists, err := base.history.get("b/" + base.heads[producer])
		if err != nil || !exists {
			t.Fatal("fixture missing own financial parent")
		}
		body.Rank = uint64(value.Record.Rank) + 1
	} else {
		body.Rank = base.rankBase + 1
	}
	for _, raw := range inputs {
		var envelope Envelope
		if decodeStrict(raw, &envelope) != nil {
			t.Fatal("fixture envelope encoding")
		}
		body.Payments = append(body.Payments, envelope)
	}
	if update != nil {
		update(&body)
	}
	body.PaymentRoot = financialDagPaymentRoot(body.Payments)
	signature := ed25519.Sign(keys[producer], append([]byte(financialDomain+"DAG-BLOCK-SIGN\x00"), canonical(body)...))
	raw := canonical(financialDagBlock{Body: body, Signature: hex.EncodeToString(signature)})
	return raw, hashHex(append([]byte(financialDomain+"DAG-BLOCK\x00"), raw...))
}

func financialDagBatchWire(t *testing.T, base *financialDagExecution, blocks ...[]byte) []byte {
	t.Helper()
	previous, err := base.commitmentHash()
	if err != nil {
		t.Fatal(err)
	}
	encoded := make([]string, len(blocks))
	for index, raw := range blocks {
		encoded[index] = base64.StdEncoding.EncodeToString(raw)
	}
	return canonical(financialDagBatch{Blocks: encoded, GenesisHash: base.anchor, Previous: previous,
		Schema: "gg.financial-dag.batch.v1", Sequence: base.checkpoint + 1, SourceHash: base.source.hash()})
}

func TestFinancialDagSessionNamespaceSeparatesAnchorsAndSignedPayments(t *testing.T) {
	model, accounts, producers := financialDagFixture(t)
	if bytes.Contains(canonical(model.source), []byte("network_id")) {
		t.Fatal("legacy source bytes changed")
	}
	makeExecution := func(network string) *financialDagExecution {
		source := model.source
		source.Schema = "gg.financial-dag.source.v2"
		source.NetworkID = network
		genesis := model.genesis
		genesis.FinancialDAG = &source
		genesis.Schema = "gg.native.genesis.v5"
		anchor := hashHex(canonical(genesis))
		next, err := newFinancialDagExecution(genesis, anchor, source)
		if err != nil {
			t.Fatal(err)
		}
		return next
	}
	first := makeExecution(strings.Repeat("b", 64))
	second := makeExecution(strings.Repeat("c", 64))
	if first.anchor == second.anchor || first.source.hash() == second.source.hash() || first.epochAnchor == second.epochAnchor {
		t.Fatal("session identity did not reach all signing anchors")
	}
	payment := testTx(first.genesis, first.anchor, accounts, 0, 1, "3", 0)
	wire, _ := financialDagSignedBlock(t, first, producers, 0, [][]byte{payment}, nil)
	if _, err := first.applyBatch(context.Background(), financialDagBatchWire(t, first, wire), first.timeNs); err != nil {
		t.Fatal(err)
	}
	if _, err := second.applyBatch(context.Background(), financialDagBatchWire(t, second, wire), second.timeNs); err == nil {
		t.Fatal("prior-session block replay accepted")
	}
	wrapped, _ := financialDagSignedBlock(t, second, producers, 0, [][]byte{payment}, nil)
	if _, err := second.applyBatch(context.Background(), financialDagBatchWire(t, second, wrapped), second.timeNs); err == nil {
		t.Fatal("prior-session payment rewrapped under new producer signature")
	}
	for _, source := range []financialDagSource{
		func() financialDagSource { v := model.source; v.NetworkID = strings.Repeat("b", 64); return v }(),
		func() financialDagSource { v := first.source; v.NetworkID = ""; return v }(),
		func() financialDagSource { v := first.source; v.NetworkID = "not-a-network-id"; return v }(),
	} {
		if source.validateShape(model.genesis) == nil {
			t.Fatal("unbound or ambiguous source version accepted")
		}
	}
}

func TestFinancialDag5000ActualPaymentsBindProducerCausalOrderAndReceipts(t *testing.T) {
	base, accounts, producers := financialDagFixture(t)
	before, _ := base.commitmentHash()
	inputs := make([][]byte, 5000)
	for index := range inputs {
		inputs[index] = testTx(base.genesis, base.anchor, accounts, 0, 1, "1", uint64(index))
	}
	wire, identifier := financialDagSignedBlock(t, base, producers, 0, inputs, nil)
	batch := financialDagBatchWire(t, base, wire)
	next, err := base.applyBatch(context.Background(), batch, base.timeNs)
	if err != nil {
		t.Fatal(err)
	}
	after, _ := base.commitmentHash()
	state, err := next.commitment()
	if err != nil || before != after || state.Blocks != 1 || state.Attempts != 5000 || state.Applied != 5000 || state.Rejected != 0 || state.Authors[0].Head != identifier || state.Authors[0].Sequence != 1 || state.Authors[0].Attempts != 5000 {
		t.Fatal("actual signed financial block did not bind complete ordered monetary execution", err)
	}
	for _, account := range next.money.Accounts {
		if account.Address == base.genesis.Accounts[0] && (account.Balance != "249999995000" || account.Nonce != 5000) ||
			account.Address == base.genesis.Accounts[1] && account.Balance != "250000005000" {
			t.Fatal("financial DAG count did not represent actual money movement")
		}
	}
	record := next.pending[identifier]
	binding := financialExecutionContext{BlockHash: identifier, Checkpoint: 1, Epoch: 1, Genesis: base.anchor, OrderIndex: 1,
		Schema: "gg.financial.execution-context.v1", SourceHash: base.source.hash()}
	proof, err := makeFinancialReceiptProof(record.Receipts, 4999)
	if err != nil || !checkFinancialReceiptInclusion(binding, record.Summary, proof) || record.Summary.AccountRootAfter != state.AccountRoot {
		t.Fatal("financial block receipt is detached from actual block/account transition", err)
	}
	if _, err := next.applyBatch(context.Background(), financialDagBatchWire(t, next, wire), next.timeNs); err == nil {
		t.Fatal("same producer block admitted twice")
	}
}

func TestFinancialDagConflictingPaymentsDoNotFreezeProducerHistory(t *testing.T) {
	base, accounts, producers := financialDagFixture(t)
	payment := testTx(base.genesis, base.anchor, accounts, 0, 1, "9", 0)
	a, aid := financialDagSignedBlock(t, base, producers, 0, [][]byte{payment}, nil)
	b, bid := financialDagSignedBlock(t, base, producers, 1, [][]byte{payment}, nil)
	blocks := []struct {
		raw []byte
		id  string
	}{{a, aid}, {b, bid}}
	sort.Slice(blocks, func(i, j int) bool { return blocks[i].id < blocks[j].id })
	next, err := base.applyBatch(context.Background(), financialDagBatchWire(t, base, blocks[0].raw, blocks[1].raw), base.timeNs)
	if err != nil {
		t.Fatal(err)
	}
	state, _ := next.commitment()
	if state.Attempts != 2 || state.Applied != 1 || state.Rejected != 1 || state.Authors[0].Sequence != 1 || state.Authors[1].Sequence != 1 {
		t.Fatal("double spend or producer freeze on an authentic competing payment")
	}
	last, _ := financialDagSignedBlock(t, next, producers, 1, [][]byte{testTx(base.genesis, base.anchor, accounts, 0, 1, "4", 1)}, nil)
	continued, err := next.applyBatch(context.Background(), financialDagBatchWire(t, next, last), next.timeNs)
	if err != nil {
		t.Fatal("producer could not continue after rejected payment", err)
	}
	state, _ = continued.commitment()
	if state.Applied != 2 || state.Rejected != 1 || state.Authors[1].Sequence != 2 {
		t.Fatal("subsequent valid payment not applied")
	}
}

func TestFinancialDagRejectsForgedProducerPaymentAndWrongContextWithoutMutation(t *testing.T) {
	base, accounts, producers := financialDagFixture(t)
	before, _ := base.commitmentHash()
	payment := testTx(base.genesis, base.anchor, accounts, 0, 1, "1", 0)
	valid, _ := financialDagSignedBlock(t, base, producers, 0, [][]byte{payment}, nil)
	var forged financialDagBlock
	json.Unmarshal(valid, &forged)
	forged.Signature = strings.Repeat("0", 128)
	wrongPayment := append([]byte(nil), payment...)
	var envelope Envelope
	json.Unmarshal(wrongPayment, &envelope)
	envelope.Signature = strings.Repeat("0", 128)
	badPayment, _ := financialDagSignedBlock(t, base, producers, 0, [][]byte{canonical(envelope)}, nil)
	for index, invalid := range [][]byte{canonical(forged), badPayment,
		append([]byte(" "), valid...), bytes.Replace(valid, []byte(`"rank":"1"`), []byte(`"rank":"01"`), 1)} {
		if _, err := base.applyBatch(context.Background(), financialDagBatchWire(t, base, invalid), base.timeNs); err == nil {
			t.Fatalf("forged/noncanonical financial block%d accepted", index)
		}
	}
	for _, update := range []func(*financialDagBlockBody){
		func(body *financialDagBlockBody) { body.GenesisHash = strings.Repeat("f", 64) },
		func(body *financialDagBlockBody) { body.SourceHash = strings.Repeat("e", 64) },
		func(body *financialDagBlockBody) { body.Epoch++ },
		func(body *financialDagBlockBody) { body.Sequence++ },
		func(body *financialDagBlockBody) { body.Rank++ },
		func(body *financialDagBlockBody) { body.Parents = []string{strings.Repeat("a", 64)} },
		func(body *financialDagBlockBody) { body.CreatedAtNs += 5000000001 }} {
		invalid, _ := financialDagSignedBlock(t, base, producers, 0, [][]byte{payment}, update)
		if _, err := base.applyBatch(context.Background(), financialDagBatchWire(t, base, invalid), base.timeNs); err == nil {
			t.Fatal("wrong signed financial context accepted")
		}
	}
	after, _ := base.commitmentHash()
	if before != after || len(base.pending) != 0 {
		t.Fatal("rejected block mutated authoritative base")
	}
}

func TestFinancialDagRejectsInvalidLaterBlockAtomically(t *testing.T) {
	base, accounts, producers := financialDagFixture(t)
	first, _ := financialDagSignedBlock(t, base, producers, 0, [][]byte{testTx(base.genesis, base.anchor, accounts, 0, 1, "1", 0)}, nil)
	stage, err := base.applyBatch(context.Background(), financialDagBatchWire(t, base, first), base.timeNs)
	if err != nil {
		t.Fatal(err)
	}
	second, _ := financialDagSignedBlock(t, stage, producers, 0, nil, nil)
	var corrupted financialDagBlock
	json.Unmarshal(second, &corrupted)
	corrupted.Signature = strings.Repeat("0", 128)
	before, _ := base.commitmentHash()
	if _, err := base.applyBatch(context.Background(), financialDagBatchWire(t, base, first, canonical(corrupted)), base.timeNs); err == nil {
		t.Fatal("batch with bad second producer signature accepted")
	}
	after, _ := base.commitmentHash()
	if before != after || base.money.AccountRoot != stage.pending[firstFinancialPendingID(stage)].Summary.AccountRootBefore {
		t.Fatal("invalid later block published partial money transition")
	}
}

func firstFinancialPendingID(execution *financialDagExecution) string {
	for identifier := range execution.pending {
		return identifier
	}
	return ""
}

func TestFinancialDagCutPreservesMoneyIdentitiesCountersAndCompleteReplay(t *testing.T) {
	base, accounts, producers := financialDagFixture(t)
	first, _ := financialDagSignedBlock(t, base, producers, 0, [][]byte{testTx(base.genesis, base.anchor, accounts, 0, 1, "7", 0)}, nil)
	batchOne := financialDagBatchWire(t, base, first)
	one, err := base.applyBatch(context.Background(), batchOne, base.timeNs)
	if err != nil {
		t.Fatal(err)
	}
	before, _ := one.commitmentHash()
	cut, err := one.prepareCut()
	if err != nil {
		t.Fatal(err)
	}
	afterPrepare, _ := one.commitmentHash()
	if before != afterPrepare {
		t.Fatal("cut preparation changed live state")
	}
	two, err := one.applyCut(context.Background(), cut, one.timeNs)
	if err != nil {
		t.Fatal(err)
	}
	meta, _ := two.commitment()
	if meta.Epoch != 2 || meta.ActiveBlocks != 0 || meta.Blocks != 1 || meta.Applied != 1 || meta.Attempts != 1 || !streamCanonicalEqual(canonical(meta.Authors), one.authors) || two.money.AccountRoot != one.money.AccountRoot || meta.ReceiptsRoot == "" {
		t.Fatal("cut reset money, identity or canonical history")
	}
	second, _ := financialDagSignedBlock(t, two, producers, 0, [][]byte{testTx(base.genesis, base.anchor, accounts, 0, 1, "2", 1)}, nil)
	batchTwo := financialDagBatchWire(t, two, second)
	three, err := two.applyBatch(context.Background(), batchTwo, two.timeNs)
	if err != nil {
		t.Fatal(err)
	}
	replay, _, _ := financialDagFixture(t)
	replay, err = replay.applyBatch(context.Background(), batchOne, replay.timeNs)
	if err == nil {
		replay, err = replay.applyCut(context.Background(), cut, replay.timeNs)
	}
	if err == nil {
		replay, err = replay.applyBatch(context.Background(), batchTwo, replay.timeNs)
	}
	if err != nil {
		t.Fatal("original signed financial history did not replay", err)
	}
	left, _ := three.commitmentHash()
	right, _ := replay.commitmentHash()
	if left != right || !bytes.Equal(canonical(three.money.Accounts), canonical(replay.money.Accounts)) {
		t.Fatal("financial archive replay produced different commitments or money")
	}
	if _, err := two.applyCut(context.Background(), cut, two.timeNs); err == nil {
		t.Fatal("stale cut reused across financial epochs")
	}
	if _, err := two.applyBatch(context.Background(), financialDagBatchWire(t, two, first), two.timeNs); err == nil {
		t.Fatal("old financial epoch block replayed after cut")
	}
}

func TestFinancialLegacyCutUsesEpochHeadAndCannotBeReusedBySameCreator(t *testing.T) {
	for _, schema := range []string{"gg.financial-dag.source.v1", "gg.financial-dag.source.v2"} {
		t.Run(schema, func(t *testing.T) {
			base, _, producers := financialDagFixture(t)
			if schema != base.source.Schema {
				source := base.source
				source.Schema, source.NetworkID = schema, strings.Repeat("b", 64)
				genesis := base.genesis
				genesis.Schema, genesis.FinancialDAG = "gg.native.genesis.v5", &source
				var err error
				base, err = newFinancialDagExecution(genesis, hashHex(canonical(genesis)), source)
				if err != nil {
					t.Fatal(err)
				}
			}
			ctx := context.Background()
			for _, producer := range []int{0, 1} {
				wire, _ := financialDagSignedBlock(t, base, producers, producer, nil, nil)
				next, err := base.applyBatch(ctx, financialDagBatchWire(t, base, wire), base.timeNs)
				if err != nil {
					t.Fatal(err)
				}
				base = next
			}
			previousAuthors := canonical(base.authors)
			cut, err := base.prepareCut()
			if err != nil {
				t.Fatal(err)
			}
			base, err = base.applyCut(ctx, cut, base.timeNs)
			if err != nil || !bytes.Equal(canonical(base.authors), previousAuthors) || base.heads[0] != base.epochAnchor || base.authors[0].Head == base.heads[0] {
				t.Fatal("legacy cut changed archived author or lost its epoch parent", err)
			}
			wire, first := financialDagSignedBlock(t, base, producers, 0, nil, nil)
			next, err := base.applyBatch(ctx, financialDagBatchWire(t, base, wire), base.timeNs)
			if err != nil || next.heads[0] != first || next.authors[0].Sequence != 2 {
				t.Fatal("actual signed post-cut continuation rejected", err)
			}
			base = next
			// This is independently producer-signed with the next sequence and
			// the correct rank for its stated cut parent. The cut is nevertheless
			// no longer this creator's head and cannot replace its actual branch.
			stale, _ := financialDagSignedBlock(t, base, producers, 0, nil, func(body *financialDagBlockBody) {
				body.Parents, body.Rank = []string{base.epochAnchor}, base.rankBase+1
			})
			if _, err := base.applyBatch(ctx, financialDagBatchWire(t, base, stale), base.timeNs); err == nil || err.Error() != "GG_FINANCIAL_DAG_CAUSAL_SEQUENCE" {
				t.Fatal("same creator reused cut parent after selecting its continuation", err)
			}
			// The other creator remains entitled to start from that exact cut,
			// independently of the first creator's global progress.
			slow, _ := financialDagSignedBlock(t, base, producers, 1, nil, nil)
			if _, err := base.applyBatch(ctx, financialDagBatchWire(t, base, slow), base.timeNs); err != nil {
				t.Fatal("unadvanced creator lost its authentic cut parent", err)
			}
		})
	}
}

func TestFinancialDagMempoolPreviewCannotBecomeOrderedBaseOrCut(t *testing.T) {
	base, _, producers := financialDagFixture(t)
	wire, _ := financialDagSignedBlock(t, base, producers, 0, nil, nil)
	preview, err := base.applyBatch(context.Background(), financialDagBatchWire(t, base, wire), 0)
	if err != nil || !preview.provisional {
		t.Fatal("missing explicit mempool-only transition", err)
	}
	if _, err := preview.prepareCut(); err == nil {
		t.Fatal("mempool preview allowed cut preparation")
	}
	if _, err := preview.applyBatch(context.Background(), financialDagBatchWire(t, preview, wire), base.timeNs); err == nil {
		t.Fatal("mempool preview became an ordered financial base")
	}
	if base.blocks != 0 || base.attempts != 0 {
		t.Fatal("preview changed authoritative state")
	}
}

func TestFinancialDagBoundSourceRejectsRoleSubstitutionAndCopiesCallerInputs(t *testing.T) {
	base, _, producers := financialDagFixture(t)
	for _, mutate := range []func(*financialDagSource){
		func(source *financialDagSource) { source.Policy.Execution = "PREVIEW_COUNTS_ONLY" },
		func(source *financialDagSource) { source.NativeChainID = "ggnet:" + strings.Repeat("c", 24) },
		func(source *financialDagSource) { source.Producers[0] = base.genesis.Accounts[0] },
		func(source *financialDagSource) { source.Producers[0] = base.genesis.Validators[0] },
		func(source *financialDagSource) { source.AllowedProducers = []int{1, 0} },
		func(source *financialDagSource) { source.SignatureProfile = "UNVERIFIED" }} {
		source := base.source
		source.Producers = append([]string(nil), source.Producers...)
		source.AllowedProducers = append([]int(nil), source.AllowedProducers...)
		mutate(&source)
		if _, err := newFinancialDagExecution(base.genesis, base.anchor, source); err == nil {
			t.Fatal("substituted financial authority/policy accepted")
		}
	}
	genesis := base.genesis
	genesis.Accounts = append([]string(nil), genesis.Accounts...)
	source := base.source
	source.Producers = append([]string(nil), source.Producers...)
	source.AllowedProducers = append([]int(nil), source.AllowedProducers...)
	owned, err := newFinancialDagExecution(genesis, base.anchor, source)
	if err != nil {
		t.Fatal(err)
	}
	before, _ := owned.commitmentHash()
	genesis.Accounts[0], source.Producers[0], source.AllowedProducers[0] = "mutated", "mutated", 5
	after, _ := owned.commitmentHash()
	if before != after {
		t.Fatal("caller mutation changed financial source or allocation")
	}
	denied := base.source
	denied.AllowedProducers = []int{1}
	reader, err := newFinancialDagExecution(base.genesis, base.anchor, denied)
	if err != nil {
		t.Fatal(err)
	}
	wire, _ := financialDagSignedBlock(t, reader, producers, 0, nil, nil)
	if _, err := reader.applyBatch(context.Background(), financialDagBatchWire(t, reader, wire), reader.timeNs); err == nil {
		t.Fatal("valid signature bypassed producer permission")
	}
}

func TestFinancialDagStaleParentBranchDoesNotGateFasterProducers(t *testing.T) {
	base, _, producers := financialDagFixture(t)
	one, _ := financialDagSignedBlock(t, base, producers, 0, nil, nil)
	fast, err := base.applyBatch(context.Background(), financialDagBatchWire(t, base, one), base.timeNs)
	if err != nil {
		t.Fatal(err)
	}
	two, _ := financialDagSignedBlock(t, fast, producers, 0, nil, nil)
	fast, err = fast.applyBatch(context.Background(), financialDagBatchWire(t, fast, two), fast.timeNs)
	if err != nil {
		t.Fatal(err)
	}
	slow, _ := financialDagSignedBlock(t, base, producers, 1, nil, nil) // its real parent/rank is still genesis
	next, err := fast.applyBatch(context.Background(), financialDagBatchWire(t, fast, slow), fast.timeNs)
	if err != nil {
		t.Fatal("slow producer required equal global rank/baseline", err)
	}
	meta, _ := next.commitment()
	if meta.Blocks != 3 || meta.LastRank != 2 || meta.Applied != 0 || meta.Attempts != 0 || meta.Authors[0].Sequence != 2 || meta.Authors[1].Sequence != 1 {
		t.Fatal("real stale-parent branch or zero-payment counters wrong")
	}
}

func TestFinancialDagCancellationAndBadBatchNeverPublishPartialMoney(t *testing.T) {
	base, accounts, producers := financialDagFixture(t)
	wire, _ := financialDagSignedBlock(t, base, producers, 0, [][]byte{testTx(base.genesis, base.anchor, accounts, 0, 1, "1", 0)}, nil)
	batch := financialDagBatchWire(t, base, wire)
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := base.applyBatch(ctx, batch, base.timeNs); !errors.Is(err, context.Canceled) {
		t.Fatal("pre-canceled DAG execution continued")
	}
	for _, invalid := range [][]byte{append([]byte(" "), batch...), bytes.Replace(batch, []byte(`"sequence":"1"`), []byte(`"sequence":"2"`), 1),
		bytes.Replace(batch, []byte(base.anchor), []byte(strings.Repeat("f", 64)), 1)} {
		if _, err := base.applyBatch(context.Background(), invalid, base.timeNs); err == nil {
			t.Fatal("invalid financial batch accepted")
		}
	}
	if base.blocks != 0 || len(base.pending) != 0 {
		t.Fatal("bad batch or cancellation mutated base")
	}
}

func TestFinancialDagCannotOmitOwnRealParentOrForkCommittedSequence(t *testing.T) {
	base, _, producers := financialDagFixture(t)
	one, oneID := financialDagSignedBlock(t, base, producers, 0, nil, nil)
	two, twoID := financialDagSignedBlock(t, base, producers, 1, nil, nil)
	blocks := []struct {
		raw []byte
		id  string
	}{{one, oneID}, {two, twoID}}
	sort.Slice(blocks, func(i, j int) bool { return blocks[i].id < blocks[j].id })
	next, err := base.applyBatch(context.Background(), financialDagBatchWire(t, base, blocks[0].raw, blocks[1].raw), base.timeNs)
	if err != nil {
		t.Fatal(err)
	}
	missingOwn, _ := financialDagSignedBlock(t, next, producers, 0, nil, func(body *financialDagBlockBody) { body.Parents = []string{twoID}; body.Rank = 2 })
	forked, _ := financialDagSignedBlock(t, base, producers, 0, nil, func(body *financialDagBlockBody) { body.CreatedAtNs++ })
	for _, wire := range [][]byte{missingOwn, forked} {
		if _, err := next.applyBatch(context.Background(), financialDagBatchWire(t, next, wire), next.timeNs); err == nil {
			t.Fatal("valid producer signature bypassed real causal ownership/sequence")
		}
	}
}

func TestFinancialDagRejectsWrongCanonicalOrderAndUnavailableHistory(t *testing.T) {
	base, _, producers := financialDagFixture(t)
	a, aid := financialDagSignedBlock(t, base, producers, 0, nil, nil)
	b, bid := financialDagSignedBlock(t, base, producers, 1, nil, nil)
	if aid < bid {
		a, b = b, a
	}
	if _, err := base.applyBatch(context.Background(), financialDagBatchWire(t, base, a, b), base.timeNs); err == nil {
		t.Fatal("noncanonical same-rank order accepted")
	}
	one, _ := financialDagSignedBlock(t, base, producers, 0, nil, nil)
	next, err := base.applyBatch(context.Background(), financialDagBatchWire(t, base, one), base.timeNs)
	if err != nil {
		t.Fatal(err)
	}
	two, _ := financialDagSignedBlock(t, next, producers, 0, nil, nil)
	missing := *next
	missing.history.root = dagHistoryRef{hash: next.history.root.id()}
	missing.history.read = nil
	if _, err := missing.applyBatch(context.Background(), financialDagBatchWire(t, &missing, two), missing.timeNs); !errors.Is(err, errDagHistoryUnavailable) {
		t.Fatal("missing authenticated financial history treated as absence/new history", err)
	}
}

func TestFinancialDagFullActiveSegmentRequiresCutThenResumesSameProducer(t *testing.T) {
	base, _, producers := financialDagFixture(t)
	for index := 0; index < DagMaxRecords; index++ {
		wire, _ := financialDagSignedBlock(t, base, producers, 0, nil, nil)
		next, err := base.applyBatch(context.Background(), financialDagBatchWire(t, base, wire), base.timeNs)
		if err != nil {
			t.Fatalf("active financial record%d failed: %v", index, err)
		}
		base = next
	}
	wire, _ := financialDagSignedBlock(t, base, producers, 0, nil, nil)
	before, _ := base.commitmentHash()
	if _, err := base.applyBatch(context.Background(), financialDagBatchWire(t, base, wire), base.timeNs); err == nil {
		t.Fatal("unbounded active financial segment accepted")
	}
	after, _ := base.commitmentHash()
	if before != after {
		t.Fatal("quota rejection changed authoritative financial state")
	}
	cut, err := base.prepareCut()
	if err != nil {
		t.Fatal(err)
	}
	next, err := base.applyCut(context.Background(), cut, base.timeNs)
	if err != nil {
		t.Fatal(err)
	}
	resumed, _ := financialDagSignedBlock(t, next, producers, 0, nil, nil)
	next, err = next.applyBatch(context.Background(), financialDagBatchWire(t, next, resumed), next.timeNs)
	if err != nil {
		t.Fatal("financial producer could not continue across full segment cut", err)
	}
	meta, _ := next.commitment()
	if meta.Epoch != 2 || meta.Blocks != uint64(DagMaxRecords+1) || meta.ActiveBlocks != 1 || meta.Authors[0].Sequence != uint64(DagMaxRecords+1) || meta.Attempts != 0 || meta.Applied != 0 {
		t.Fatal("cut reset identity/sequence or manufactured payment throughput")
	}
}

func TestFinancialMoneyViewPreservesUnrelatedNativeDagMetadata(t *testing.T) {
	genesis, _ := segmentedSDKGenesis(t)
	anchor := hashHex(canonical(genesis))
	_, _, accounts, _ := testGenesis()
	state := initialState(genesis, anchor)
	before := canonical(*state.DAGSegmented)
	result, err := executeFinancialTransactions(context.Background(), genesis, anchor, state, financialTestContext(anchor),
		[][]byte{testTx(genesis, anchor, accounts, 0, 1, "7", 0)})
	if err != nil || !bytes.Equal(before, canonical(*result.State.DAGSegmented)) || result.State.AccountRoot == state.AccountRoot || validateState(result.State, genesis, anchor) != nil {
		t.Fatal("monetary account view rewrote unrelated DAG state or failed atomic composition", err)
	}
}

func TestFinancialDagPythonSignedBlockAndIndependentMoneyReceiptCommitment(t *testing.T) {
	path := os.Getenv("GG_PUBLIC_FINANCIAL_DAG_FIXTURE")
	if path == "" {
		t.Skip("independent public Python financial DAG block not supplied")
	}
	info, err := os.Stat(path)
	if err != nil || info.Size() > 16*1024*1024 {
		t.Fatal("public financial block fixture missing or oversized")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var fixture struct {
		Accounts []Account          `json:"accounts"`
		Anchor   string             `json:"anchor"`
		Block    string             `json:"block"`
		Genesis  Genesis            `json:"genesis"`
		Source   financialDagSource `json:"source"`
		Summary  financialSummary   `json:"summary"`
	}
	if decodeStrictLimited(raw, &fixture, financialMaxTransactions, 64) != nil {
		t.Fatal("financial block fixture encoding")
	}
	base, err := newFinancialDagExecution(fixture.Genesis, fixture.Anchor, fixture.Source)
	if err != nil {
		t.Fatal(err)
	}
	wire, err := base64.StdEncoding.Strict().DecodeString(fixture.Block)
	if err != nil {
		t.Fatal(err)
	}
	next, err := base.applyBatch(context.Background(), financialDagBatchWire(t, base, wire), base.timeNs)
	if err != nil {
		t.Fatal("real Python producer/account signatures or financial block context rejected", err)
	}
	meta, err := next.commitment()
	if err != nil || meta.Applied != 5000 || meta.Rejected != 0 || meta.Attempts != 5000 ||
		!bytes.Equal(canonical(next.money.Accounts), canonical(fixture.Accounts)) ||
		!bytes.Equal(canonical(next.pending[firstFinancialPendingID(next)].Summary), canonical(fixture.Summary)) {
		t.Fatal("authenticated Python block disagrees with Go money/receipt execution", err)
	}
}
