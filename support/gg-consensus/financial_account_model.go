package main

// Explicit private-test general accounts. The completed genesis is bound at
// runtime, after its source/policy have been encoded; there is no circular hash.
// This does not add public membership, fees, issuance or voting power.
import (
	"context"
	"errors"
	"strconv"
)

const financialGeneralSourceSchema = "gg.financial-dag.source.v4"

type financialAccountAllocation struct {
	Address string `json:"address"`
	Balance string `json:"balance_atomic"`
}
type financialAccountGenesis struct {
	Allocations []financialAccountAllocation `json:"allocations"`
	MaxAccounts uint64                       `json:"max_accounts,string"`
	Schema      string                       `json:"schema"`
}

func generalFinancialAccounts(genesis Genesis) bool {
	return genesis.FinancialAccounts != nil && genesis.FinancialDAG != nil && genesis.FinancialDAG.hasGeneralAccounts()
}
func financialReservedAccountKey(genesis Genesis, address string) bool {
	if genesis.checked != nil && genesis.checked.reserved != nil {
		return genesis.checked.reserved[address]
	}
	if genesis.Protocol != nil {
		for _, member := range genesis.Protocol.Committee.Members {
			if address == member.ValidatorKey || address == member.NodeKey || address == member.OwnerPeerKey {
				return true
			}
		}
		for _, invite := range genesis.Protocol.InitialProducers {
			if address == invite.Body.ProducerKey || address == invite.Body.NodeKey || address == invite.Body.OwnerPeerKey {
				return true
			}
		}
	}
	for _, key := range genesis.Validators {
		if key == address {
			return true
		}
	}
	if genesis.FinancialDAG != nil {
		for _, key := range genesis.FinancialDAG.Producers {
			if key == address {
				return true
			}
		}
	}
	if genesis.Membership != nil {
		for _, invite := range genesis.Membership.Validators {
			body := invite.Body
			if address == body.ValidatorKey || address == body.NodeKey || address == body.OwnerPeerKey {
				return true
			}
		}
	}
	return false
}

func checkedGenesisReservedKeys(genesis Genesis) map[string]bool {
	keys := map[string]bool{}
	for _, key := range genesis.Validators {
		keys[key] = true
	}
	if genesis.FinancialDAG != nil {
		for _, key := range genesis.FinancialDAG.Producers {
			keys[key] = true
		}
	}
	if genesis.Membership != nil {
		for _, invite := range genesis.Membership.Validators {
			body := invite.Body
			keys[body.ValidatorKey] = true
			keys[body.NodeKey] = true
			keys[body.OwnerPeerKey] = true
		}
	}
	if genesis.Protocol != nil {
		for _, member := range genesis.Protocol.Committee.Members {
			keys[member.ValidatorKey] = true
			keys[member.NodeKey] = true
			keys[member.OwnerPeerKey] = true
		}
		for _, invite := range genesis.Protocol.InitialProducers {
			body := invite.Body
			keys[body.ProducerKey] = true
			keys[body.NodeKey] = true
			keys[body.OwnerPeerKey] = true
		}
	}
	return keys
}
func validateFinancialAccountGenesis(genesis Genesis) error {
	policy := genesis.FinancialAccounts
	maximum, initial := financialMaximumSupply(genesis), financialInitialSupply(genesis)
	minimumAllocations := 1
	if publicFinancialProtocol(genesis) && initial == 0 {
		minimumAllocations = 0
	}
	if !generalFinancialAccounts(genesis) || genesis.Accounts != nil || genesis.DAG != nil || genesis.DAGSegmented != nil ||
		policy.Schema != "gg.financial.account-genesis.v1" || policy.MaxAccounts < 1 || policy.MaxAccounts > 1<<32 ||
		policy.Allocations == nil || len(policy.Allocations) < minimumAllocations || len(policy.Allocations) > MaxBlockTxs || uint64(len(policy.Allocations)) > policy.MaxAccounts || maximum == 0 {
		return errFinancialAccount
	}
	total, previous := uint64(0), ""
	for _, allocation := range policy.Allocations {
		balance, ok := financialAccountAmount(allocation.Balance, maximum)
		if !ok || balance == 0 || total > maximum-balance || !financialAccountAddress(allocation.Address) ||
			allocation.Address <= previous || financialReservedAccountKey(genesis, allocation.Address) {
			return errFinancialAccount
		}
		total += balance
		previous = allocation.Address
	}
	if total != initial {
		return errFinancialAccount
	}
	return nil
}
func financialAccountRulesFor(genesis Genesis, anchor string) (financialAccountRules, error) {
	if validateFinancialAccountGenesis(genesis) != nil || !pubPattern.MatchString(anchor) {
		return financialAccountRules{}, errFinancialAccount
	}
	rules := financialAccountRules{Genesis: anchor, MaxAccounts: genesis.FinancialAccounts.MaxAccounts, MaxTotal: financialMaximumSupply(genesis), Schema: "gg.financial.account-rules.v1"}
	if !rules.valid() {
		return rules, errFinancialAccount
	}
	return rules, nil
}
func validateFinancialAccountRoot(root *financialAccountLink, genesis Genesis, anchor string, applied uint64) error {
	rules, err := financialAccountRulesFor(genesis, anchor)
	if publicFinancialProtocol(genesis) {
		if err != nil || root == nil || !validFinancialAccountLink(*root, rules, rules.hash()) {
			return errFinancialAccount
		}
		return nil
	}
	if err != nil || root == nil || !validFinancialAccountLink(*root, rules, rules.hash()) || root.Total != genesis.SupplyAtomic ||
		root.Count < uint64(len(genesis.FinancialAccounts.Allocations)) || root.Count-uint64(len(genesis.FinancialAccounts.Allocations)) > applied {
		return errFinancialAccount
	}
	return nil
}
func initialFinancialMoney(genesis Genesis, anchor string) (financialMoneyState, error) {
	if !generalFinancialAccounts(genesis) {
		accounts := initialNativeAccounts(genesis)
		return financialMoneyState{AccountRoot: nativeAccountRoot(accounts), Accounts: accounts, GenesisHash: anchor}, nil
	}
	rules, err := financialAccountRulesFor(genesis, anchor)
	if err != nil {
		return financialMoneyState{}, err
	}
	tree, err := newFinancialAccountTree(rules)
	if err != nil {
		return financialMoneyState{}, err
	}
	for _, allocation := range genesis.FinancialAccounts.Allocations {
		tree, err = tree.set(context.Background(), Account{Address: allocation.Address, Balance: allocation.Balance})
		if err != nil {
			return financialMoneyState{}, err
		}
	}
	var protocol *financialProtocolExecution
	if publicFinancialProtocol(genesis) {
		protocol, err = initialFinancialProtocol(context.Background(), genesis, anchor)
		if err != nil {
			return financialMoneyState{}, err
		}
		tree, err = protocolEnsureRewardAccounts(context.Background(), tree, genesis)
		if err != nil {
			return financialMoneyState{}, err
		}
	}
	return financialMoneyState{AccountRoot: tree.root.link.Hash, GenesisHash: anchor, Tree: &tree, Protocol: protocol}, nil
}
func validateFinancialMoney(money financialMoneyState, genesis Genesis, anchor string) error {
	if money.GenesisHash != anchor {
		return errFinancialAccount
	}
	if !generalFinancialAccounts(genesis) {
		if money.Tree != nil {
			return errFinancialAccount
		}
		return validateNativeAccountState(money.Accounts, genesis, money.AccountRoot)
	}
	rules, err := financialAccountRulesFor(genesis, anchor)
	if err != nil || money.Accounts != nil || money.Tree == nil || money.Tree.rules != rules || money.Tree.rulesHash != rules.hash() ||
		money.AccountRoot != money.Tree.root.link.Hash || !validFinancialAccountLink(money.Tree.root.link, rules, rules.hash()) {
		return errFinancialAccount
	}
	if publicFinancialProtocol(genesis) {
		return validateProtocolMoney(money, genesis, anchor)
	}
	if money.Protocol != nil || money.Tree.root.link.Total != genesis.SupplyAtomic {
		return errFinancialAccount
	}
	return nil
}
func financialReceiptSchemas(general bool) (string, string) {
	if general {
		return "gg.financial.summary.v2", "gg.financial.receipt.v2"
	}
	return "gg.financial.summary.v1", "gg.financial.receipt.v1"
}
func executeFinancialAccountMoney(ctx context.Context, genesis Genesis, anchor string, money financialMoneyState, binding financialExecutionContext, inputs [][]byte) (financialMoneyResult, error) {
	return executeFinancialAccountMoneyWithDecoded(ctx, genesis, anchor, money, binding, inputs, nil)
}

func executeFinancialAccountMoneyWithDecoded(ctx context.Context, genesis Genesis, anchor string, money financialMoneyState, binding financialExecutionContext, inputs [][]byte, decoded *financialDecodedPayments) (financialMoneyResult, error) {
	if !binding.valid(anchor) || validateFinancialMoney(money, genesis, anchor) != nil {
		return financialMoneyResult{}, errFinancialAccount
	}
	if publicFinancialProtocol(genesis) {
		return executeFinancialProtocolMoneyWithDecoded(ctx, genesis, anchor, money, binding, inputs, decoded)
	}
	envelopes, err := financialEnvelopesWithDecoded(ctx, inputs, genesis, anchor, decoded)
	if err != nil {
		return financialMoneyResult{}, err
	}
	next := *money.Tree
	contextHash := financialContextHash(binding)
	summarySchema, receiptSchema := financialReceiptSchemas(true)
	result := financialMoneyResult{Receipts: make([]financialReceipt, 0, len(inputs))}
	result.Summary = financialSummary{AccountRootBefore: money.AccountRoot, ContextHash: contextHash, InputHash: financialInputHash(contextHash, inputs), Schema: summarySchema, Transactions: len(inputs)}
	for index, envelope := range envelopes {
		if err := ctx.Err(); err != nil {
			return financialMoneyResult{}, err
		}
		amount, err := strconv.ParseUint(envelope.Body.Amount, 10, 64)
		if err != nil {
			return financialMoneyResult{}, errFinancialAccount
		}
		before := next.root.link.Hash
		updated, outcome, err := next.transfer(ctx, envelope.Body.Sender, envelope.Body.Recipient, amount, envelope.Body.Nonce)
		if err != nil {
			return financialMoneyResult{}, err
		}
		next = updated
		if outcome == "APPLIED" {
			result.Summary.Applied++
		} else {
			result.Summary.Rejected++
		}
		result.Receipts = append(result.Receipts, financialReceipt{AccountRootAfter: next.root.link.Hash, AccountRootBefore: before, ContextHash: contextHash, Index: index, Outcome: outcome, Schema: receiptSchema, TransactionID: financialIntentID(inputs[index])})
	}
	result.Money = financialMoneyState{AccountRoot: next.root.link.Hash, GenesisHash: anchor, Tree: &next}
	if validateFinancialMoney(result.Money, genesis, anchor) != nil {
		return financialMoneyResult{}, errors.New("GG_FINANCIAL_EXECUTION_STATE")
	}
	result.Summary.AccountRootAfter = next.root.link.Hash
	result.Summary.ReceiptsRoot = sealFinancialReceiptRoot(result.Summary, financialReceiptTreeRoot(result.Receipts))
	if err := ctx.Err(); err != nil {
		return financialMoneyResult{}, err
	}
	return result, nil
}
