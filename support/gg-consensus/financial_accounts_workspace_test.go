//go:build !js

package main

// Exact account-tree, receipt and cold-store differential regressions.
// The SDK case uses actual signatures/certificates, not trusted flags.
import (
	"bytes"
	"context"
	"errors"
	"math/rand"
	"sort"
	"strconv"
	"sync"
	"testing"
	"time"

	abci "github.com/cometbft/cometbft/abci/types"
	"github.com/syndtr/goleveldb/leveldb"
)

func workspaceNodeBytes(t *testing.T, tree financialAccountTree) map[string][]byte {
	t.Helper()
	nodes := map[string][]byte{}
	if err := tree.stage(context.Background(), financialAccountStageMaxNodes, func(hash string, raw []byte) error {
		nodes[hash] = append([]byte(nil), raw...)
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	return nodes
}
func compareWorkspaceTrees(t *testing.T, actual, expected financialAccountTree) {
	t.Helper()
	if actual.root.link != expected.root.link {
		t.Fatal("exact AVL root/link changed", actual.root.link, expected.root.link)
	}
	a, b := workspaceNodeBytes(t, actual), workspaceNodeBytes(t, expected)
	if len(a) != len(b) {
		t.Fatal("reachable node count changed", len(a), len(b))
	}
	for hash, raw := range b {
		if !bytes.Equal(a[hash], raw) {
			t.Fatal("canonical full-node bytes changed", hash)
		}
	}
}
func workspaceAddresses(batch *protocolMoneyBatch) []string {
	values := []string{}
	for address, row := range batch.rows {
		if row.dirty {
			values = append(values, address)
		}
	}
	sort.Strings(values)
	return values
}

func TestAccountWorkspaceRandomNewExistingAndAllRotationOrders(t *testing.T) {
	ctx := context.Background()
	rng := rand.New(rand.NewSource(947131))
	for round := 0; round < 12; round++ {
		tree, err := newFinancialAccountTree(financialAccountTestRules())
		if err != nil {
			t.Fatal(err)
		}
		addresses := make([]string, 95)
		for index := range addresses {
			addresses[index] = financialAccountTestAddress(91000 + round*100 + index)
		}
		rng.Shuffle(len(addresses), func(i, j int) { addresses[i], addresses[j] = addresses[j], addresses[i] })
		for _, address := range addresses[:19] {
			tree, err = tree.set(ctx, Account{Address: address, Balance: "10000"})
			if err != nil {
				t.Fatal(err)
			}
		}
		original := workspaceNodeBytes(t, tree)
		batch := newProtocolMoneyBatch(tree)
		fee := "1"
		for index := 0; index < 900; index++ {
			sender := addresses[rng.Intn(len(addresses))]
			recipient := addresses[rng.Intn(len(addresses))]
			if sender == recipient {
				continue
			}
			row, err := batch.account(ctx, sender)
			if err != nil {
				t.Fatal(err)
			}
			nonce := row.nonce
			if index%11 == 0 {
				nonce++
			}
			_, err = batch.apply(ctx, Envelope{Body: Body{Sender: sender, Recipient: recipient, Amount: strconv.Itoa(index%9 + 1), MaxFee: &fee, Nonce: nonce, Version: 2}}, 1)
			if err != nil {
				t.Fatal(err)
			}
		}
		expected, err := workspaceReferenceFinish(ctx, batch)
		if err != nil {
			t.Fatal(err)
		}
		actual, used, err := batch.finishWorkspace(ctx, workspaceAddresses(batch), financialAccountWorkspaceBytes)
		if err != nil || !used {
			t.Fatal("bounded mixed case did not exercise workspace", round, used, err)
		}
		compareWorkspaceTrees(t, actual, expected)
		for hash, raw := range original {
			if !bytes.Equal(workspaceNodeBytes(t, tree)[hash], raw) {
				t.Fatal("base tree mutated")
			}
		}
		finished, err := batch.finish(ctx)
		if err != nil {
			t.Fatal(err)
		}
		compareWorkspaceTrees(t, finished, expected)
	}
}

func TestAccountWorkspaceFiveThousandNewRecipientsActuallyFitsPrivateBudget(t *testing.T) {
	ctx := context.Background()
	tree, _ := newFinancialAccountTree(financialAccountTestRules())
	sender := financialAccountTestAddress(700000)
	var err error
	tree, err = tree.set(ctx, Account{Address: sender, Balance: "6000"})
	if err != nil {
		t.Fatal(err)
	}
	batch := newProtocolMoneyBatch(tree)
	cap := "0"
	for index := 0; index < 5000; index++ {
		outcome, err := batch.apply(ctx, Envelope{Body: Body{Sender: sender, Recipient: financialAccountTestAddress(710000 + index), Amount: "1", MaxFee: &cap, Nonce: uint64(index), Version: 2}}, 0)
		if err != nil || outcome != "APPLIED" {
			t.Fatal(index, outcome, err)
		}
	}
	actual, used, err := batch.finishWorkspace(ctx, workspaceAddresses(batch), financialAccountWorkspaceBytes)
	if err != nil || !used {
		t.Fatal("5000-new-recipient batch silently bypassed workspace", used, err)
	}
	expected, err := workspaceReferenceFinish(ctx, batch)
	if err != nil {
		t.Fatal(err)
	}
	compareWorkspaceTrees(t, actual, expected)
	if tree.root.link.Count != 1 || tree.root.link.Total != "6000" {
		t.Fatal("base root mutated")
	}
	t.Logf("private workspace eligible: final accounts=%d charge/node=%d limit=%d; not a throughput result", actual.root.link.Count, financialAccountWorkspaceNodeCharge(), financialAccountWorkspaceBytes)
}

func TestAccountWorkspaceAccountLimitDebitCreditAndNonceConflictSemantics(t *testing.T) {
	ctx := context.Background()
	rules := financialAccountTestRules()
	rules.MaxAccounts = 3
	tree, _ := newFinancialAccountTree(rules)
	a, b, c, d := financialAccountTestAddress(1), financialAccountTestAddress(2), financialAccountTestAddress(3), financialAccountTestAddress(4)
	tree, _ = tree.set(ctx, Account{Address: a, Balance: "100"})
	batch := newProtocolMoneyBatch(tree)
	fee := "1"
	cases := []struct {
		from, to, amount string
		nonce            uint64
		outcome          string
	}{
		{b, c, "1", 0, "REJECTED_FUNDS"}, {a, b, "10", 0, "APPLIED"}, {a, c, "10", 1, "APPLIED"},
		{a, d, "1", 2, "REJECTED_ACCOUNT_LIMIT"}, {b, a, "1", 0, "APPLIED"}, {a, b, "1", 1, "REJECTED_NONCE"},
		{a, b, "1", 2, "APPLIED"},
	}
	for _, value := range cases {
		outcome, err := batch.apply(ctx, Envelope{Body: Body{Sender: value.from, Recipient: value.to, Amount: value.amount, Nonce: value.nonce, MaxFee: &fee, Version: 2}}, 1)
		if err != nil || outcome != value.outcome {
			t.Fatal(value, outcome, err)
		}
	}
	expected, err := workspaceReferenceFinish(ctx, batch)
	if err != nil {
		t.Fatal(err)
	}
	actual, err := batch.finish(ctx)
	if err != nil {
		t.Fatal(err)
	}
	compareWorkspaceTrees(t, actual, expected)
}

type workspaceCancelContext struct {
	context.Context
	remaining int
	mu        sync.Mutex
}

func (value *workspaceCancelContext) Err() error {
	value.mu.Lock()
	defer value.mu.Unlock()
	value.remaining--
	if value.remaining <= 0 {
		return context.Canceled
	}
	return nil
}

func TestAccountWorkspaceCancellationBudgetFallbackAndCorruptionNeverMutateBase(t *testing.T) {
	ctx := context.Background()
	tree := financialAccountTestTree(t, 31)
	before := workspaceNodeBytes(t, tree)
	batch := newProtocolMoneyBatch(tree)
	for index := 0; index < 31; index++ {
		address := financialAccountTestAddress(index)
		account, exists, err := tree.get(ctx, address)
		if err != nil {
			t.Fatal(err)
		}
		if !exists {
			continue
		}
		balance, _ := financialAccountAmount(account.Balance, tree.rules.MaxTotal)
		batch.rows[address] = &protocolAccountDelta{address: address, balance: balance, originalBalance: balance, nonce: account.Nonce + 1, exists: true, wasPresent: true, dirty: true}
	}
	// Ensure the cancellation path has real writes even if fixture key ranges
	// evolve: the currently authenticated root account is always present.
	root := tree.root.node.Account
	balance, _ := financialAccountAmount(root.Balance, tree.rules.MaxTotal)
	batch.rows[root.Address] = &protocolAccountDelta{address: root.Address, balance: balance, originalBalance: balance, nonce: root.Nonce + 1, exists: true, wasPresent: true, dirty: true}
	addresses := workspaceAddresses(batch)
	for _, cut := range []int{1, 3, 9, 21, 60} {
		controlled := &workspaceCancelContext{Context: ctx, remaining: cut}
		actual, _, err := batch.finishWorkspace(controlled, addresses, financialAccountWorkspaceBytes)
		if err != nil && !errors.Is(err, context.Canceled) {
			t.Fatal(err)
		}
		if err != nil && actual.root.link != tree.root.link {
			t.Fatal("cancelled workspace escaped")
		}
	}
	expected, err := workspaceReferenceFinish(ctx, batch)
	if err != nil {
		t.Fatal(err)
	}
	fallback, err := batch.finishWithWorkspaceLimit(ctx, financialAccountWorkspaceReserve)
	if err != nil {
		t.Fatal(err)
	}
	compareWorkspaceTrees(t, fallback, expected)
	// A validation/IO failure is not a resource fallback: do not retry it on
	// an old tree path or hide a bad base behind a different evaluation.
	calls := 0
	cold, err := tree.freeze(func(string) (financialAccountNode, error) {
		calls++
		return financialAccountNode{}, errFinancialAccount
	})
	if err != nil {
		t.Fatal(err)
	}
	bad := *batch
	bad.tree = cold
	result, err := bad.finishWithWorkspaceLimit(ctx, financialAccountWorkspaceBytes)
	if err == nil || calls != 1 || result.root.link != tree.root.link {
		t.Fatal("corruption retried or published", calls, err)
	}
	after := workspaceNodeBytes(t, tree)
	for hash, raw := range before {
		if !bytes.Equal(after[hash], raw) {
			t.Fatal("base checked node changed", hash)
		}
	}
}

func TestAccountWorkspaceFreezeCancellationRulesAndPublicAliasesStayStrict(t *testing.T) {
	ctx := context.Background()
	tree := financialAccountTestTree(t, 17)
	before := workspaceNodeBytes(t, tree)
	work, err := newFinancialAccountWorkspace(tree, financialAccountWorkspaceBytes)
	if err != nil {
		t.Fatal(err)
	}
	account := tree.root.node.Account.account()
	account.Nonce++
	if err = work.set(ctx, account); err != nil {
		t.Fatal(err)
	}
	cancelled, cancel := context.WithCancel(ctx)
	cancel()
	result, err := work.freeze(cancelled)
	if !errors.Is(err, context.Canceled) || result.root.link != tree.root.link {
		t.Fatal("cancelled freeze escaped", err)
	}
	// Root-only edit: calls 1/2/3 visit root/unchanged children; call4
	// cancels after immutable make but before publishing the new root.
	late := &workspaceCancelContext{Context: ctx, remaining: 4}
	result, err = work.freeze(late)
	if !errors.Is(err, context.Canceled) || result.root.link != tree.root.link {
		t.Fatal("late freeze cancellation published an immutable partial result", err)
	}
	result, err = work.freeze(ctx)
	if err != nil {
		t.Fatal(err)
	}
	copy := *result.root.node
	copy.Account.Nonce++
	if _, _, _, err = result.load(ctx, financialAccountRef{link: result.root.link, node: &copy}, "", ""); err == nil {
		t.Fatal("mutated public node reused checked handle")
	}
	result.rules.MaxTotal++
	if _, _, _, err = result.load(ctx, result.root, "", ""); err == nil {
		t.Fatal("changed rules reused node handle")
	}
	after := workspaceNodeBytes(t, tree)
	for hash, raw := range before {
		if !bytes.Equal(after[hash], raw) {
			t.Fatal("old immutable value mutated")
		}
	}
	work.base.rules.MaxTotal++
	if _, err = work.freeze(ctx); err == nil {
		t.Fatal("changed workspace base rules accepted")
	}
}

func TestAccountWorkspaceActualSDKReceiptRootColdAndUncertainStore(t *testing.T) {
	for _, fault := range []bool{false, true} {
		t.Run(map[bool]string{false: "cold-receipt", true: "write-fail-closed"}[fault], func(t *testing.T) {
			ctx := context.Background()
			app, backend, keys, producers, root := publicProtocolSDKFixture(t)
			payer := keys[app.genesis.FinancialAccounts.Allocations[0].Address]
			payments := make([]Envelope, 96)
			expectedBatch := newProtocolMoneyBatch(*backend.current.money.Tree)
			for index := range payments {
				payments[index] = publicFixturePayment(backend.current, payer, publicFixtureAddress(publicFixtureKey("workspace-sdk-recipient:"+strconv.Itoa(index))), uint64(index), "7")
				fee, err := economicMinimumFee(app.genesis.Protocol.Economics, uint64(len(canonical(payments[index]))))
				if err != nil {
					t.Fatal(err)
				}
				if outcome, err := expectedBatch.apply(ctx, payments[index], fee); err != nil || outcome != "APPLIED" {
					t.Fatal(index, outcome, err)
				}
			}
			expected, err := workspaceReferenceFinish(ctx, expectedBatch)
			if err != nil {
				t.Fatal(err)
			}
			_, block, _ := publicFixtureBlock(t, backend.current, producers[0], publicFixtureKey("workspace-sdk-worker"), payments)
			raw := publicFixtureBatch(t, backend.current, nil, block)
			when := time.Unix(0, backend.store.timeNs+1000000)
			prepared, err := app.PrepareProposal(ctx, &abci.RequestPrepareProposal{Height: 1, Time: when, MaxTxBytes: 48 << 20, Txs: [][]byte{raw}})
			if err != nil || len(prepared.Txs) != 1 || backend.candidate.entry == nil {
				t.Fatal(err)
			}
			execution := backend.candidate.entry.execution
			compareWorkspaceTrees(t, *execution.money.Tree, expected)
			var identifier string
			for id, record := range execution.pending {
				identifier = id
				summary := record.Summary
				summary.AccountRootAfter = expected.root.link.Hash
				receipts := make([]financialReceipt, len(payments))
				for index, envelope := range payments {
					fee, _ := economicMinimumFee(app.genesis.Protocol.Economics, uint64(len(canonical(envelope))))
					receipts[index] = financialReceipt{ContextHash: summary.ContextHash, Fee: strconv.FormatUint(fee, 10), Index: index, Outcome: "APPLIED", Schema: "gg.financial.receipt.v3", TransactionID: financialIntentID(canonical(envelope))}
				}
				if !bytes.Equal(canonical(record.Receipts), canonical(receipts)) || record.Summary.ReceiptsRoot != sealFinancialReceiptRoot(summary, financialReceiptTreeRoot(receipts)) {
					t.Fatal("receipt originals/root differ from old immutable-finish semantics")
				}
			}
			if _, err = app.FinalizeBlock(ctx, &abci.RequestFinalizeBlock{Height: 1, Time: when, Txs: [][]byte{raw}}); err != nil {
				t.Fatal(err)
			}
			before := canonical(app.state)
			if fault {
				backend.store.write = func(*leveldb.Batch) error { return errors.New("PUBLIC-unit uncertain storage fault") }
			}
			_, err = app.Commit(ctx, &abci.RequestCommit{})
			if fault {
				if err == nil || !bytes.Equal(before, canonical(app.state)) || backend.store.health() == nil {
					t.Fatal("uncertain store published workspace state")
				}
				_ = app.Close()
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			committed := canonical(app.state)
			genesis, anchor := app.genesis, app.anchor
			if err = app.Close(); err != nil {
				t.Fatal(err)
			}
			cold, err := newDagEnabledLedger(genesis, anchor, root, false)
			if err != nil {
				t.Fatal(err)
			}
			defer cold.Close()
			if !bytes.Equal(committed, canonical(cold.state)) {
				t.Fatal("cold state root changed")
			}
			receipt, err := cold.financial.(*financialNativeApplication).Receipt(ctx, cold.state, financialReceiptSelector{Block: identifier, Index: 95})
			if err != nil || receipt.Receipt.Leaf.Outcome != "APPLIED" || checkFinancialCertifiedReceipt(receipt, cold.state, genesis) != nil {
				t.Fatal("cold original/receipt invalid", err)
			}
			packet := publicFixturePacket(t, cold, keys)
			packet.FinancialReceipt = &receipt
			index := 95
			packet.ExpectedFinancialReceipt = &financialReceiptExpectation{Block: identifier, Index: &index, TransactionID: receipt.Receipt.Leaf.TransactionID}
			if verified, err := verifyInput(packet); err != nil || verified["financial_receipt_verified"] != true {
				t.Fatal("real SDK receipt failed", err)
			}
		})
	}
}

// workspaceReferenceFinish preserves the original sorted debit/credit
// finish as an independent differential reference.

func workspaceReferenceFinish(ctx context.Context, batch *protocolMoneyBatch) (financialAccountTree, error) {
	addresses := make([]string, 0, len(batch.rows))
	for address, row := range batch.rows {
		if row.dirty {
			addresses = append(addresses, address)
		}
	}
	sort.Strings(addresses)
	next := batch.tree
	// Debit/nonincreasing leaves first preserve the tree's supply ceiling even
	// when the credited address sorts before its funding account.
	for phase := 0; phase < 2; phase++ {
		for _, address := range addresses {
			if err := ctx.Err(); err != nil {
				return batch.tree, err
			}
			row := batch.rows[address]
			debit := row.wasPresent && row.balance <= row.originalBalance
			if phase == 0 && !debit || phase == 1 && debit {
				continue
			}
			var err error
			next, err = next.set(ctx, Account{Address: address, Balance: strconv.FormatUint(row.balance, 10), Nonce: row.nonce})
			if err != nil {
				return batch.tree, err
			}
		}
	}
	before, bok := economicAmount(batch.tree.root.link.Total)
	after, aok := economicAmount(next.root.link.Total)
	if !bok || !aok || batch.fees > before || after != before-batch.fees || next.root.link.Count != batch.count {
		return batch.tree, errFinancialAccount
	}
	return next, nil
}

func TestAccountWorkspaceInternalGetKeepsPublicProofSearchAndBounds(t *testing.T) {
	ctx := context.Background()
	tree := financialAccountTestTree(t, 67)
	for index := 0; index < 140; index++ {
		address := financialAccountTestAddress(index)
		proof, proofErr := tree.proof(ctx, address)
		account, exists, err := tree.get(ctx, address)
		if !errors.Is(err, proofErr) || exists != proof.Exists {
			t.Fatal(index, exists, err, proof.Exists, proofErr)
		}
		if exists && account != proof.Path[len(proof.Path)-1].Account.account() {
			t.Fatal("lookup returned different leaf")
		}
	}
	cancelled, cancel := context.WithCancel(ctx)
	cancel()
	if _, _, err := tree.get(cancelled, tree.root.node.Account.Address); !errors.Is(err, context.Canceled) {
		t.Fatal(err)
	}
	changed := tree
	changed.rules.MaxTotal++
	if _, _, err := changed.get(ctx, tree.root.node.Account.Address); err == nil {
		t.Fatal("lookup skipped bound rules")
	}
	copy := *tree.root.node
	copy.Account.Nonce++
	changed = tree
	changed.root.node = &copy
	if _, _, err := changed.get(ctx, tree.root.node.Account.Address); err == nil {
		t.Fatal("lookup skipped immutable checked value binding")
	}
}

func TestAccountWorkspacePreflightBoundsKeep5000SmallBaseCasesEligible(t *testing.T) {
	for _, value := range []struct{ base, dirty, newCount uint64 }{
		{5008, 5000, 0}, {8, 5001, 5000}, {0, 5000, 5000},
	} {
		bound, ok := financialAccountWorkspaceNodeBound(value.base, value.dirty, value.newCount)
		if !ok || bound > (financialAccountWorkspaceBytes-financialAccountWorkspaceReserve)/financialAccountWorkspaceNodeCharge() {
			t.Fatal("small-base 5000 case declined by conservative preflight", value, bound)
		}
	}
	if _, ok := financialAccountWorkspaceNodeBound(1, 2*financialMaxTransactions+1, 0); ok {
		t.Fatal("unbounded dirty count admitted")
	}
	if _, ok := financialAccountWorkspaceNodeBound(1, 1, 2); ok {
		t.Fatal("new count exceeds dirty count")
	}
	// The original 5000-new-recipient differential case requires actual used=true.
	// The following separate real tree checks reused accounts, not just arithmetic.
	ctx := context.Background()
	tree := financialAccountTestTree(t, 5008)
	batch := newProtocolMoneyBatch(tree)
	for index := 0; index < 5000; index++ {
		address := financialAccountTestAddress(index)
		account, exists, err := tree.get(ctx, address)
		if err != nil || !exists {
			t.Fatal(index, err)
		}
		balance, _ := financialAccountAmount(account.Balance, tree.rules.MaxTotal)
		batch.rows[address] = &protocolAccountDelta{address: address, balance: balance, originalBalance: balance,
			nonce: account.Nonce + 1, exists: true, wasPresent: true, dirty: true}
	}
	eligible, bound, err := batch.workspaceEligibility(ctx, workspaceAddresses(batch), financialAccountWorkspaceBytes)
	if err != nil || !eligible || bound != 5008 {
		t.Fatal("real5008 base was not eligible", eligible, bound, err)
	}
	actual, used, err := batch.finishWorkspace(ctx, workspaceAddresses(batch), financialAccountWorkspaceBytes)
	if err != nil || !used {
		t.Fatal("5000 reused accounts bypassed workspace", used, err)
	}
	expected, err := workspaceReferenceFinish(ctx, batch)
	if err != nil {
		t.Fatal(err)
	}
	compareWorkspaceTrees(t, actual, expected)
}

func TestAccountWorkspacePreflightLargeSparseNewUsesOldPathWithoutCOWTraversal(t *testing.T) {
	ctx := context.Background()
	tree := financialAccountTestTree(t, 6000)
	cold, disk := financialAccountTestDisk(t, tree)
	original := map[string][]byte{}
	for hash, raw := range disk {
		original[hash] = append([]byte(nil), raw...)
	}
	reads := 0
	read := cold.read
	cold.read = func(hash string) (financialAccountNode, error) { reads++; return read(hash) }
	batch := newProtocolMoneyBatch(cold)
	sender := financialAccountTestAddress(0)
	cap := "0"
	for index := 0; index < 128; index++ {
		outcome, err := batch.apply(ctx, Envelope{Body: Body{Sender: sender, Recipient: financialAccountTestAddress(950000 + index),
			Amount: "1", MaxFee: &cap, Nonce: uint64(index), Version: 2}}, 0)
		if err != nil || outcome != "APPLIED" {
			t.Fatal(index, outcome, err)
		}
	}
	reads = 0
	addresses := workspaceAddresses(batch)
	eligible, bound, err := batch.workspaceEligibility(ctx, addresses, financialAccountWorkspaceBytes)
	if err != nil || eligible || bound != 6128 || reads != 0 {
		t.Fatal("large sparse base did not decline before reads", eligible, bound, reads, err)
	}
	declined, used, err := batch.finishWorkspace(ctx, addresses, financialAccountWorkspaceBytes)
	if err != nil || used || reads != 0 || declined.root.link != cold.root.link {
		t.Fatal("ineligible path built/traversed a COW tree", used, reads, err)
	}
	expected, err := workspaceReferenceFinish(ctx, batch)
	if err != nil {
		t.Fatal(err)
	}
	oldReads := reads
	reads = 0
	actual, err := batch.finish(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if reads != oldReads {
		t.Fatal("fallback performed extra base-node reads", reads, oldReads)
	}
	compareWorkspaceTrees(t, actual, expected)
	if cold.root.link != tree.root.link {
		t.Fatal("preflight/fallback changed original root")
	}
	for hash, raw := range original {
		if !bytes.Equal(raw, disk[hash]) {
			t.Fatal("original backing bytes mutated", hash)
		}
	}
}
