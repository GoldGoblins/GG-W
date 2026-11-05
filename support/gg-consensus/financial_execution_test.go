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
	"runtime"
	"strconv"
	"strings"
	"testing"
	"time"
)

func financialTestContext(anchor string) financialExecutionContext {
	return financialExecutionContext{BlockHash: strings.Repeat("b", 64), Checkpoint: 1, Epoch: 1, Genesis: anchor,
		OrderIndex: 1, Schema: "gg.financial.execution-context.v1", SourceHash: strings.Repeat("c", 64)}
}

func TestFinancial5000SignedTransfersExecuteRealBalancesAndNonces(t *testing.T) {
	genesis, anchor, keys, _ := testGenesis()
	state := initialState(genesis, anchor)
	before := canonical(state)
	inputs := make([][]byte, 5000)
	nonces := [4]uint64{}
	reference := copyState(state)
	for index := range inputs {
		source := index % 4
		inputs[index] = testTx(genesis, anchor, keys, source, (source+1)%4, strconv.Itoa(index%7+1), nonces[source])
		nonces[source]++
		envelope, err := parseEnvelope(inputs[index], genesis, anchor)
		if err != nil || applyEnvelope(&reference, envelope, false) != nil {
			t.Fatal("public signed financial fixture failed")
		}
	}
	sealState(&reference)
	binding := financialTestContext(anchor)
	old := runtime.GOMAXPROCS(1)
	defer runtime.GOMAXPROCS(old)
	serial, err := executeFinancialTransactions(context.Background(), genesis, anchor, state, binding, inputs)
	if err != nil {
		t.Fatal(err)
	}
	runtime.GOMAXPROCS(2)
	parallel, err := executeFinancialTransactions(context.Background(), genesis, anchor, state, binding, inputs)
	if err != nil || !bytes.Equal(canonical(serial), canonical(parallel)) {
		t.Fatal("parallel signature admission changed ordered monetary execution", err)
	}
	if !bytes.Equal(before, canonical(state)) || !bytes.Equal(canonical(reference), canonical(parallel.State)) ||
		parallel.Summary.Applied != 5000 || parallel.Summary.Rejected != 0 || parallel.Summary.Transactions != 5000 ||
		len(parallel.Receipts) != 5000 || parallel.State.AccountRoot == state.AccountRoot {
		t.Fatal("5000 financial transfers did not produce the exact independently executed balances")
	}
	for _, account := range parallel.State.Accounts {
		if account.Nonce != 1250 {
			t.Fatal("monetary sender nonce did not advance for every actual transfer")
		}
	}
	for index, receipt := range parallel.Receipts {
		if receipt.Index != index || receipt.Outcome != "APPLIED" || index > 0 && receipt.AccountRootBefore != parallel.Receipts[index-1].AccountRootAfter {
			t.Fatal("receipt chain does not follow actual monetary order")
		}
	}
	for _, index := range []int{0, 1, 2499, 4998, 4999} {
		proof, err := makeFinancialReceiptProof(parallel.Receipts, index)
		if err != nil || !checkFinancialReceiptInclusion(binding, parallel.Summary, proof) {
			t.Fatal("actual financial receipt inclusion failed", err)
		}
	}
	secondBinding := binding
	secondBinding.BlockHash, secondBinding.OrderIndex = strings.Repeat("d", 64), 2
	replay, err := executeFinancialTransactions(context.Background(), genesis, anchor, parallel.State, secondBinding, inputs)
	if err != nil || replay.Summary.Applied != 0 || replay.Summary.Rejected != 5000 || !bytes.Equal(canonical(replay.State), canonical(parallel.State)) {
		t.Fatal("repeated signed monetary intents spent twice", err)
	}
	if replay.Receipts[0].TransactionID != parallel.Receipts[0].TransactionID || replay.Summary.ReceiptsRoot == parallel.Summary.ReceiptsRoot {
		t.Fatal("intent identity and occurrence/context commitments conflated")
	}
}

func TestFinancialConflictsProduceReceiptsAndDoNotFreezeLaterValidPayments(t *testing.T) {
	genesis, anchor, keys, _ := testGenesis()
	state := initialState(genesis, anchor)
	first := testTx(genesis, anchor, keys, 0, 1, "10", 0)
	inputs := [][]byte{first, first, testTx(genesis, anchor, keys, 0, 2, strconv.FormatUint(Supply, 10), 1),
		testTx(genesis, anchor, keys, 0, 2, "1", 3), testTx(genesis, anchor, keys, 0, 2, "1", 1), testTx(genesis, anchor, keys, 2, 0, "50", 0)}
	result, err := executeFinancialTransactions(context.Background(), genesis, anchor, state, financialTestContext(anchor), inputs)
	if err != nil {
		t.Fatal(err)
	}
	expected := []string{"APPLIED", "REJECTED_NONCE", "REJECTED_FUNDS", "REJECTED_NONCE", "APPLIED", "APPLIED"}
	for index, receipt := range result.Receipts {
		if receipt.Outcome != expected[index] || receipt.Outcome != "APPLIED" && receipt.AccountRootBefore != receipt.AccountRootAfter {
			t.Fatal("conflict outcome or rejected-state preservation is wrong")
		}
		proof, err := makeFinancialReceiptProof(result.Receipts, index)
		if err != nil || !checkFinancialReceiptInclusion(financialTestContext(anchor), result.Summary, proof) {
			t.Fatal("conflict receipt not committed", err)
		}
	}
	if result.Summary.Applied != 3 || result.Summary.Rejected != 3 || validateState(result.State, genesis, anchor) != nil {
		t.Fatal("financial conflicts changed supply or prevented later valid execution")
	}
}

func TestFinancialNonceExhaustionCannotWrapOrDebit(t *testing.T) {
	genesis, anchor, keys, _ := testGenesis()
	state := initialState(genesis, anchor)
	for index := range state.Accounts {
		if state.Accounts[index].Address == genesis.Accounts[0] {
			state.Accounts[index].Nonce = ^uint64(0)
		}
	}
	sealState(&state)
	result, err := executeFinancialTransactions(context.Background(), genesis, anchor, state, financialTestContext(anchor),
		[][]byte{testTx(genesis, anchor, keys, 0, 1, "1", ^uint64(0))})
	if err != nil || result.Summary.Applied != 0 || result.Receipts[0].Outcome != "REJECTED_NONCE_EXHAUSTED" || !bytes.Equal(canonical(state), canonical(result.State)) {
		t.Fatal("exhausted nonce mutated balances or wrapped", err)
	}
}

func TestFinancialBadSignedContextOrEncodingRejectsWholeInput(t *testing.T) {
	genesis, anchor, keys, _ := testGenesis()
	state := initialState(genesis, anchor)
	before := canonical(state)
	first := testTx(genesis, anchor, keys, 0, 1, "3", 0)
	var envelope Envelope
	json.Unmarshal(testTx(genesis, anchor, keys, 0, 1, "5", 1), &envelope)
	changed := func(update func(*Body)) []byte {
		value := envelope
		update(&value.Body)
		value.Signature = hex.EncodeToString(ed25519.Sign(keys[0], canonical(value.Body)))
		return canonical(value)
	}
	wrongSignature := envelope
	wrongSignature.Signature = strings.Repeat("0", 128)
	for index, invalid := range [][]byte{canonical(wrongSignature),
		changed(func(body *Body) { body.GenesisHash = strings.Repeat("d", 64) }),
		changed(func(body *Body) { body.ChainID = "ggnet:" + strings.Repeat("b", 24) }),
		changed(func(body *Body) { body.Recipient = body.Sender }),
		changed(func(body *Body) { body.Amount = "01" }),
		changed(func(body *Body) { body.Recipient = strings.Repeat("f", 64) }),
		append([]byte(" "), canonical(envelope)...),
		bytes.Replace(canonical(envelope), []byte(`"nonce":1`), []byte(`"nonce":1,"nonce":1`), 1)} {
		result, err := executeFinancialTransactions(context.Background(), genesis, anchor, state, financialTestContext(anchor), [][]byte{first, invalid})
		if err == nil || len(result.Receipts) != 0 || len(result.State.Accounts) != 0 || !bytes.Equal(canonical(state), before) {
			t.Fatalf("invalid item%d allowed partial monetary execution", index)
		}
	}
}

func TestFinancialExecutionRequiresExactHealthyStateAndBinding(t *testing.T) {
	genesis, anchor, keys, _ := testGenesis()
	state := initialState(genesis, anchor)
	inputs := [][]byte{testTx(genesis, anchor, keys, 0, 1, "1", 0)}
	for _, change := range []func(*financialExecutionContext){
		func(value *financialExecutionContext) { value.Genesis = strings.Repeat("d", 64) },
		func(value *financialExecutionContext) { value.SourceHash = "" },
		func(value *financialExecutionContext) { value.BlockHash = strings.Repeat("B", 64) },
		func(value *financialExecutionContext) { value.Epoch = 0 },
		func(value *financialExecutionContext) { value.Checkpoint = dagSegmentCounterMax + 1 },
		func(value *financialExecutionContext) { value.OrderIndex = 0 }} {
		binding := financialTestContext(anchor)
		change(&binding)
		if _, err := executeFinancialTransactions(context.Background(), genesis, anchor, state, binding, inputs); err == nil {
			t.Fatal("malformed or substituted execution context accepted")
		}
	}
	badState := copyState(state)
	badState.Accounts[0].Balance = "0"
	if _, err := executeFinancialTransactions(context.Background(), genesis, anchor, badState, financialTestContext(anchor), inputs); err == nil {
		t.Fatal("unverified monetary state executed")
	}
}

func TestFinancialReceiptProofBindsOrderContextCountAndOutcomeSummary(t *testing.T) {
	genesis, anchor, keys, _ := testGenesis()
	state := initialState(genesis, anchor)
	binding := financialTestContext(anchor)
	inputs := [][]byte{testTx(genesis, anchor, keys, 0, 1, "1", 0), testTx(genesis, anchor, keys, 1, 2, "2", 0), testTx(genesis, anchor, keys, 2, 3, "3", 0)}
	result, err := executeFinancialTransactions(context.Background(), genesis, anchor, state, binding, inputs)
	if err != nil {
		t.Fatal(err)
	}
	proof, _ := makeFinancialReceiptProof(result.Receipts, 2) // odd padding must be checked
	if !checkFinancialReceiptInclusion(binding, result.Summary, proof) {
		t.Fatal("valid padded receipt proof rejected")
	}
	for _, mutate := range []func(*financialSummary){
		func(value *financialSummary) { value.Transactions = 4; value.Applied = 4 },
		func(value *financialSummary) { value.Applied = 2; value.Rejected = 1 },
		func(value *financialSummary) { value.InputHash = strings.Repeat("0", 64) },
		func(value *financialSummary) { value.AccountRootBefore = strings.Repeat("0", 64) }} {
		changed := result.Summary
		mutate(&changed)
		if checkFinancialReceiptInclusion(binding, changed, proof) {
			t.Fatal("receipt tree authenticated a substituted summary/count")
		}
	}
	for _, mutate := range []func(*financialReceiptProof){
		func(value *financialReceiptProof) { value.Leaf.TransactionID = strings.Repeat("0", 64) },
		func(value *financialReceiptProof) { value.Leaf.Index = 1 },
		func(value *financialReceiptProof) { value.Leaf.Outcome = "FINALIZED" },
		func(value *financialReceiptProof) {
			value.Leaf.AccountRootAfter = value.Leaf.AccountRootBefore
			value.Leaf.Outcome = "REJECTED_FUNDS"
		},
		func(value *financialReceiptProof) { value.Path[0].Side = "left" },
		func(value *financialReceiptProof) { value.Path[0].Hash = strings.Repeat("0", 64) },
		func(value *financialReceiptProof) { value.Path = value.Path[:len(value.Path)-1] },
		func(value *financialReceiptProof) { value.Path = append(value.Path, value.Path[0]) }} {
		changed := financialReceiptProof{Leaf: proof.Leaf, Path: append([]PathItem(nil), proof.Path...)}
		mutate(&changed)
		if checkFinancialReceiptInclusion(binding, result.Summary, changed) {
			t.Fatal("mutated financial receipt proof accepted")
		}
	}
	other := binding
	other.Epoch++
	if checkFinancialReceiptInclusion(other, result.Summary, proof) {
		t.Fatal("receipt moved across execution epoch")
	}
}

func TestFinancialCanonicalOrderResolvesDoubleSpendAndBindsIndependentOrder(t *testing.T) {
	genesis, anchor, keys, _ := testGenesis()
	state := initialState(genesis, anchor)
	binding := financialTestContext(anchor)
	first, second := testTx(genesis, anchor, keys, 0, 1, "7", 0), testTx(genesis, anchor, keys, 0, 2, "9", 0)
	a, errA := executeFinancialTransactions(context.Background(), genesis, anchor, state, binding, [][]byte{first, second})
	b, errB := executeFinancialTransactions(context.Background(), genesis, anchor, state, binding, [][]byte{second, first})
	if errA != nil || errB != nil || a.Summary.Applied != 1 || b.Summary.Applied != 1 || a.Summary.Rejected != 1 || b.Summary.Rejected != 1 || a.State.AccountRoot == b.State.AccountRoot {
		t.Fatal("conflicting payments ignored canonical order")
	}
	independent := testTx(genesis, anchor, keys, 2, 3, "3", 0)
	a, errA = executeFinancialTransactions(context.Background(), genesis, anchor, state, binding, [][]byte{first, independent})
	b, errB = executeFinancialTransactions(context.Background(), genesis, anchor, state, binding, [][]byte{independent, first})
	if errA != nil || errB != nil || a.State.AccountRoot != b.State.AccountRoot || a.Summary.ReceiptsRoot == b.Summary.ReceiptsRoot {
		t.Fatal("independent financial results or distinct ordered transcript are wrong")
	}
	proof, _ := makeFinancialReceiptProof(a.Receipts, 0)
	if checkFinancialReceiptInclusion(binding, b.Summary, proof) {
		t.Fatal("receipt moved into a different transaction order")
	}
}

func TestFinancialAdmissionBoundsBeforeCryptographicWork(t *testing.T) {
	genesis, anchor, _, _ := testGenesis()
	maximum := bytes.Repeat([]byte{' '}, MaxTxBytes)
	totalExcess := make([][]byte, financialMaxInputBytes/MaxTxBytes+1)
	for index := range totalExcess {
		totalExcess[index] = maximum
	}
	for _, inputs := range [][][]byte{make([][]byte, financialMaxTransactions+1), {nil}, {bytes.Repeat([]byte{' '}, MaxTxBytes+1)}, totalExcess} {
		if _, err := financialEnvelopes(context.Background(), inputs, genesis, anchor); err == nil || err.Error() != "GG_FINANCIAL_BATCH_LIMIT" {
			t.Fatal("invalid size reached encoding or cryptographic admission", err)
		}
	}
}

func TestFinancialCanceledWorkReturnsNoPartialState(t *testing.T) {
	genesis, anchor, keys, _ := testGenesis()
	state := initialState(genesis, anchor)
	before := canonical(state)
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := executeFinancialTransactions(ctx, genesis, anchor, state, financialTestContext(anchor), nil); !errors.Is(err, context.Canceled) {
		t.Fatal("pre-canceled monetary execution accepted")
	}
	inputs := make([][]byte, 5000)
	for index := range inputs {
		inputs[index] = testTx(genesis, anchor, keys, 0, 1, "1", uint64(index))
	}
	ctx, cancel = context.WithCancel(context.Background())
	defer cancel()
	timer := time.AfterFunc(time.Millisecond, cancel)
	defer timer.Stop()
	result, err := executeFinancialTransactions(ctx, genesis, anchor, state, financialTestContext(anchor), inputs)
	if !errors.Is(err, context.Canceled) || len(result.Receipts) != 0 || len(result.State.Accounts) != 0 || !bytes.Equal(before, canonical(state)) {
		t.Fatal("canceled financial work published or mutated partial results", err)
	}
}

func TestFinancialEmptyExecutionCreatesNoMoneyOrTransferReceipt(t *testing.T) {
	genesis, anchor, _, _ := testGenesis()
	state := initialState(genesis, anchor)
	binding := financialTestContext(anchor)
	result, err := executeFinancialTransactions(context.Background(), genesis, anchor, state, binding, nil)
	if err != nil || !bytes.Equal(canonical(state), canonical(result.State)) || result.Summary.Transactions != 0 || result.Summary.Applied != 0 || result.Summary.Rejected != 0 || len(result.Receipts) != 0 || !pubPattern.MatchString(result.Summary.ReceiptsRoot) {
		t.Fatal("empty ordered execution manufactured monetary work", err)
	}
	if _, err := makeFinancialReceiptProof(nil, 0); err == nil || checkFinancialReceiptInclusion(binding, result.Summary, financialReceiptProof{}) {
		t.Fatal("empty execution manufactured an inclusion proof")
	}
}

func TestFinancialPythonSignedFixtureAndIndependentReceiptRoot(t *testing.T) {
	path := os.Getenv("GG_PUBLIC_FINANCIAL_EXECUTION_FIXTURE")
	if path == "" {
		t.Skip("independent public Python fixture not supplied")
	}
	info, err := os.Stat(path)
	if err != nil || info.Size() > 16*1024*1024 {
		t.Fatal("public Python financial fixture missing or oversized")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var fixture struct {
		Accounts []Account                 `json:"accounts"`
		Anchor   string                    `json:"anchor"`
		Binding  financialExecutionContext `json:"binding"`
		Genesis  Genesis                   `json:"genesis"`
		Inputs   []string                  `json:"inputs"`
		Summary  financialSummary          `json:"summary"`
	}
	if decodeStrictLimited(raw, &fixture, financialMaxTransactions, 64) != nil || len(fixture.Inputs) != 5000 {
		t.Fatal("independent public fixture is not 5000 real signed payments")
	}
	inputs := make([][]byte, len(fixture.Inputs))
	for index, encoded := range fixture.Inputs {
		inputs[index], err = base64.StdEncoding.Strict().DecodeString(encoded)
		if err != nil || base64.StdEncoding.EncodeToString(inputs[index]) != encoded {
			t.Fatal("noncanonical public payment fixture encoding")
		}
	}
	result, err := executeFinancialTransactions(context.Background(), fixture.Genesis, fixture.Anchor,
		initialState(fixture.Genesis, fixture.Anchor), fixture.Binding, inputs)
	if err != nil || !bytes.Equal(canonical(result.State.Accounts), canonical(fixture.Accounts)) ||
		!bytes.Equal(canonical(result.Summary), canonical(fixture.Summary)) {
		t.Fatal("native execution disagrees with independently signed/calculated Python payments or receipt commitment", err)
	}
}
