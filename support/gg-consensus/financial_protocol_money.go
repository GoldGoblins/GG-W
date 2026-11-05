package main

// Account transitions and economic epochs compose in one immutable money view.
// The existing synchronous selected-original store publishes their roots and
// metadata together; proposal checks never write balances or issuance.
import (
	"bytes"
	"context"
	"strconv"
)

func financialMaximumSupply(genesis Genesis) uint64 {
	if publicFinancialProtocol(genesis) {
		value, ok := economicAmount(genesis.Protocol.Economics.MaxSupply)
		if ok {
			return value
		}
		return 0
	}
	return Supply
}

func financialInitialSupply(genesis Genesis) uint64 {
	if publicFinancialProtocol(genesis) {
		value, ok := economicAmount(genesis.Protocol.Economics.InitialSupply)
		if ok {
			return value
		}
		return 0
	}
	return Supply
}

func protocolAccountIsReserved(ctx context.Context, protocol *financialProtocolExecution, address string) (bool, error) {
	if protocol == nil {
		return false, errFinancialProtocol
	}
	raw, exists, err := protocol.roles.get(ctx, address)
	if err != nil || !exists {
		return exists, err
	}
	var role protocolReservedRole
	if decodeStrict(raw, &role) != nil || !bytes.Equal(raw, canonical(role)) || role.Schema != "gg.financial.reserved-role.v1" {
		return false, errFinancialProtocol
	}
	return role.Role != "GOVERNANCE", nil
}

func protocolEnsureRewardAccounts(ctx context.Context, tree financialAccountTree, genesis Genesis) (financialAccountTree, error) {
	addresses := protocolSortedRewardAddresses(genesis)
	for _, member := range genesis.Protocol.Committee.Members {
		addresses = append(addresses, member.AccountKey)
	}
	for _, address := range addresses {
		_, exists, err := tree.get(ctx, address)
		if err != nil {
			return tree, err
		}
		if !exists {
			if tree.root.link.Count >= tree.rules.MaxAccounts {
				return tree, errFinancialAccount
			}
			tree, err = tree.set(ctx, Account{Address: address, Balance: "0"})
			if err != nil {
				return tree, err
			}
		}
	}
	return tree, nil
}

func validateProtocolMoney(money financialMoneyState, genesis Genesis, anchor string) error {
	if !publicFinancialProtocol(genesis) || money.Protocol == nil || money.Tree == nil {
		return errFinancialProtocol
	}
	p := money.Protocol
	state := p.commitment()
	rules, err := economicRulesHash(genesis.Protocol.Economics, anchor)
	issued, validIssued := economicAmount(state.Economics.Issued)
	fees, validFees := economicAmount(state.FeePot)
	total, validTotal := economicAmount(money.Tree.root.link.Total)
	if err != nil || state.Schema != "gg.financial.protocol-state.v1" || state.Economics.Schema != "gg.financial.economic-state.v1" || state.Economics.RulesHash != rules ||
		!validIssued || !validFees || !validTotal || issued < financialInitialSupply(genesis) || issued > financialMaximumSupply(genesis) || fees > issued || total != issued-fees ||
		!state.Committee.valid() || len(state.Committee.Members) > 64 || !pubPattern.MatchString(state.LastSettlement) || !pubPattern.MatchString(state.WorkAnchorRoot) ||
		state.WorkAnchorHeight > dagSegmentCounterMax || state.WorkBlocks > dagSegmentCounterMax || !pubPattern.MatchString(state.WorkTarget) ||
		state.WorkTarget < genesis.Protocol.MinWorkTarget || state.WorkTarget > genesis.Protocol.MaxWorkTarget || state.Settlements != p.rewards.root.link.Count ||
		p.producers.root.link.Count < uint64(len(genesis.Protocol.InitialProducers)) || state.WorkBlocks < p.work.root.link.Count {
		return errFinancialProtocol
	}
	for _, row := range []struct {
		tree      protocolRegistryTree
		namespace string
	}{{p.producers, "producers"}, {p.roles, "roles"}, {p.work, "epoch_work"}, {p.rewards, "rewards"}, {p.operations, "operations"}} {
		expected, err := protocolRegistryRulesFor(genesis, anchor, row.namespace)
		if err != nil || row.tree.rules != expected || row.tree.rulesHash != expected.hash() || !validProtocolRegistryLink(row.tree.root.link, expected, expected.hash()) {
			return errFinancialProtocol
		}
	}
	if state.PendingCommittee != nil {
		pending := state.PendingCommittee
		planned, err := planCommitteeChange(state.Committee, pending.Next, anchor, pending.DecidedHeight, genesis.Protocol.MaxCommitteeChangeBPS)
		if err != nil || !bytes.Equal(canonical(planned), canonical(*pending)) {
			return errFinancialProtocol
		}
	}
	return nil
}

func protocolTransferWithFee(ctx context.Context, tree financialAccountTree, envelope Envelope, fee uint64) (financialAccountTree, string, error) {
	body := envelope.Body
	from, exists, err := tree.get(ctx, body.Sender)
	if err != nil {
		return tree, "", err
	}
	if !exists {
		return tree, "REJECTED_FUNDS", nil
	}
	if from.Nonce != body.Nonce {
		return tree, "REJECTED_NONCE", nil
	}
	if from.Nonce == economicMaxUint {
		return tree, "REJECTED_NONCE_EXHAUSTED", nil
	}
	if body.MaxFee == nil {
		return tree, "", errFinancialProtocol
	}
	maximum, ok := economicAmount(*body.MaxFee)
	if !ok {
		return tree, "", errFinancialProtocol
	}
	if maximum < fee {
		return tree, "REJECTED_FEE_LIMIT", nil
	}
	amount, ok := economicAmount(body.Amount)
	if !ok || amount == 0 {
		return tree, "", errFinancialProtocol
	}
	available, ok := economicAmount(from.Balance)
	if !ok || amount > available || fee > available-amount {
		return tree, "REJECTED_FUNDS", nil
	}
	updated, outcome, err := tree.transfer(ctx, body.Sender, body.Recipient, amount+fee, body.Nonce)
	if err != nil || outcome != "APPLIED" {
		return tree, outcome, err
	}
	if fee > 0 {
		recipient, exists, err := updated.get(ctx, body.Recipient)
		if err != nil || !exists {
			return tree, "", errFinancialAccount
		}
		balance, valid := economicAmount(recipient.Balance)
		if !valid || balance < fee {
			return tree, "", errFinancialAccount
		}
		recipient.Balance = strconv.FormatUint(balance-fee, 10)
		updated, err = updated.set(ctx, recipient)
		if err != nil {
			return tree, "", err
		}
	}
	before, _ := economicAmount(tree.root.link.Total)
	after, _ := economicAmount(updated.root.link.Total)
	if fee > before || after != before-fee {
		return tree, "", errFinancialAccount
	}
	return updated, "APPLIED", nil
}

func executeFinancialProtocolMoney(ctx context.Context, genesis Genesis, anchor string, money financialMoneyState, binding financialExecutionContext, inputs [][]byte) (financialMoneyResult, error) {
	return executeFinancialProtocolMoneyWithDecoded(ctx, genesis, anchor, money, binding, inputs, nil)
}

func executeFinancialProtocolMoneyWithDecoded(ctx context.Context, genesis Genesis, anchor string, money financialMoneyState, binding financialExecutionContext, inputs [][]byte, decoded *financialDecodedPayments) (financialMoneyResult, error) {
	if !binding.valid(anchor) || validateFinancialMoney(money, genesis, anchor) != nil {
		return financialMoneyResult{}, errFinancialProtocol
	}
	envelopes, err := financialEnvelopesWithDecoded(ctx, inputs, genesis, anchor, decoded)
	if err != nil {
		return financialMoneyResult{}, err
	}
	next := *money.Tree
	protocol := money.Protocol.clone()
	contextHash := financialContextHash(binding)
	batch := newProtocolMoneyBatch(next)
	result := financialMoneyResult{Receipts: make([]financialReceipt, 0, len(inputs))}
	result.Summary = financialSummary{AccountRootBefore: money.AccountRoot, ContextHash: contextHash, Fees: "0", InputHash: financialInputHash(contextHash, inputs), Schema: "gg.financial.summary.v3", Transactions: len(inputs)}
	feeTotal := uint64(0)
	feePot, _ := economicAmount(protocol.state.FeePot)
	reserved := map[string]bool{}
	for index, envelope := range envelopes {
		if err := ctx.Err(); err != nil {
			return financialMoneyResult{}, err
		}
		roleConflict := false
		for _, address := range []string{envelope.Body.Sender, envelope.Body.Recipient} {
			blocked, known := reserved[address]
			if !known {
				blocked, err = protocolAccountIsReserved(ctx, protocol, address)
				if err != nil {
					return financialMoneyResult{}, err
				}
				reserved[address] = blocked
			}
			if blocked {
				roleConflict = true
			}
		}
		fee, err := economicMinimumFee(genesis.Protocol.Economics, uint64(len(inputs[index])))
		if err != nil {
			return financialMoneyResult{}, err
		}
		outcome := "REJECTED_OPERATIONAL_KEY"
		if !roleConflict {
			outcome, err = batch.apply(ctx, envelope, fee)
			if err != nil {
				return financialMoneyResult{}, err
			}
		}
		charged := uint64(0)
		if outcome == "APPLIED" {
			if fee > economicMaxUint-feeTotal || fee > economicMaxUint-feePot {
				return financialMoneyResult{}, errFinancialProtocol
			}
			feeTotal += fee
			feePot += fee
			charged = fee
			result.Summary.Applied++
		} else {
			result.Summary.Rejected++
		}
		result.Receipts = append(result.Receipts, financialReceipt{ContextHash: contextHash, Fee: strconv.FormatUint(charged, 10), Index: index, Outcome: outcome, Schema: "gg.financial.receipt.v3", TransactionID: financialIntentID(inputs[index])})
	}
	next, err = batch.finish(ctx)
	if err != nil {
		return financialMoneyResult{}, err
	}
	if batch.fees != feeTotal {
		return financialMoneyResult{}, errFinancialProtocol
	}
	protocol.state.FeePot = strconv.FormatUint(feePot, 10)
	result.Money = financialMoneyState{AccountRoot: next.root.link.Hash, GenesisHash: anchor, Protocol: protocol, Tree: &next}
	if validateFinancialMoney(result.Money, genesis, anchor) != nil {
		return financialMoneyResult{}, errFinancialProtocol
	}
	result.Summary.Fees = strconv.FormatUint(feeTotal, 10)
	result.Summary.AccountRootAfter = next.root.link.Hash
	result.Summary.ReceiptsRoot = sealFinancialReceiptRoot(result.Summary, financialReceiptTreeRoot(result.Receipts))
	return result, ctx.Err()
}

func protocolCreditAccounts(ctx context.Context, tree financialAccountTree, credits []economicCredit) (financialAccountTree, error) {
	previous := ""
	for _, credit := range credits {
		if err := ctx.Err(); err != nil {
			return tree, err
		}
		amount, valid := economicAmount(credit.Amount)
		if !valid || amount == 0 || !financialAccountAddress(credit.Address) || credit.Address <= previous {
			return tree, errFinancialProtocol
		}
		account, exists, err := tree.get(ctx, credit.Address)
		if err != nil {
			return tree, err
		}
		// Registration/genesis reserve the reward account before it can accrue
		// work. Closing an epoch cannot discover a new account-limit failure.
		if !exists {
			return tree, errFinancialProtocol
		}
		balance, valid := economicAmount(account.Balance)
		if !valid || amount > tree.rules.MaxTotal-balance {
			return tree, errFinancialAccount
		}
		account.Balance = strconv.FormatUint(balance+amount, 10)
		tree, err = tree.set(ctx, account)
		if err != nil {
			return tree, err
		}
		previous = credit.Address
	}
	return tree, nil
}

func advanceFinancialProtocol(ctx context.Context, genesis Genesis, anchor string, money financialMoneyState, before State, whenNs int64) (financialMoneyState, error) {
	if !publicFinancialProtocol(genesis) || whenNs == 0 {
		return money, nil
	}
	if whenNs < 0 || before.Height < 0 || before.Height >= int64(dagSegmentCounterMax) || validateFinancialMoney(money, genesis, anchor) != nil {
		return money, errFinancialProtocol
	}
	protocol := money.Protocol.clone()
	next := *money.Tree
	protocol.height = uint64(before.Height) + 1
	protocol.state.TimeNs = strconv.FormatInt(whenNs, 10)
	if pending := protocol.state.PendingCommittee; pending != nil && before.Height >= 0 && uint64(before.Height)+1 >= pending.EffectiveHeight {
		if uint64(before.Height)+1 != pending.EffectiveHeight {
			return money, errFinancialProtocol
		}
		protocol.state.Committee = pending.Next
		protocol.state.PendingCommittee = nil
	}
	epoch, err := economicEpochAt(genesis.Protocol.Economics, uint64(genesis.GenesisTime), uint64(whenNs/1000000000))
	if err != nil {
		return money, err
	}
	if epoch < protocol.state.Economics.NextEpoch {
		return money, errFinancialProtocol
	}
	if epoch > protocol.state.Economics.NextEpoch {
		weights, err := protocol.weights(ctx, genesis.Protocol.MaxEpochParticipants)
		if err != nil {
			return money, err
		}
		fees, valid := economicAmount(protocol.state.FeePot)
		if !valid {
			return money, errFinancialProtocol
		}
		carriedFees := uint64(0)
		if len(weights) == 0 {
			carriedFees, fees = fees, 0
		}
		settled, err := settleEconomicEpoch(genesis.Protocol.Economics, anchor, protocol.state.Economics, protocol.state.Economics.NextEpoch, epoch, fees, weights)
		if err != nil {
			return money, err
		}
		next, err = protocolCreditAccounts(ctx, next, settled.Credits)
		if err != nil {
			return money, err
		}
		if protocol.state.Settlements >= 1<<32 {
			return money, errFinancialProtocol
		}
		receipt := protocolRewardReceipt{BeforeIssued: protocol.state.Economics.Issued, ClosedThrough: epoch - 1, Credits: settled.Credits,
			CreditsCount: len(settled.Credits), CreditsRoot: protocolCreditRoot(settled.Credits),
			Epoch: protocol.state.Economics.NextEpoch, Fees: settled.Fees, Genesis: anchor, Index: protocol.state.Settlements + 1, Minted: settled.Minted,
			NextIssued: settled.Next.Issued, Schema: "gg.financial.reward-receipt.v1", WorkRoot: protocol.work.root.link}
		identifier := protocolRewardReceiptID(receipt)
		protocol.rewards, err = protocol.rewards.set(ctx, protocolRewardKey(receipt.Index), []byte(identifier))
		if err != nil {
			return money, err
		}
		protocol.pendingRewards[identifier] = receipt
		target, err := protocolRetarget(protocol.state.WorkTarget, protocol.state.WorkBlocks, *genesis.Protocol)
		if err != nil {
			return money, err
		}
		protocol.state.Economics = settled.Next
		// Inactive epochs issue nothing. Registration/governance fees await
		// an epoch with selected network work instead of halting settlement.
		protocol.state.Economics.NextEpoch = epoch
		protocol.state.FeePot = strconv.FormatUint(carriedFees, 10)
		protocol.state.LastSettlement = identifier
		protocol.state.Settlements++
		protocol.state.WorkBlocks = 0
		protocol.state.WorkTarget = target
		protocol.state.WorkAnchorHeight = uint64(before.Height)
		protocol.state.WorkAnchorRoot = before.StateRoot
		protocol.work, err = newProtocolRegistry(protocol.work.rules)
		if err != nil {
			return money, err
		}
	}
	if protocol.height > protocol.state.WorkAnchorHeight+genesis.Protocol.MaxWorkHeights/2 {
		protocol.state.WorkAnchorHeight = uint64(before.Height)
		protocol.state.WorkAnchorRoot = before.StateRoot
	}
	result := money
	result.Tree = &next
	result.AccountRoot = next.root.link.Hash
	result.Protocol = protocol
	if err = validateFinancialMoney(result, genesis, anchor); err != nil {
		return money, err
	}
	return result, nil
}

func advanceFinancialExecution(ctx context.Context, execution *financialDagExecution, before State, whenNs int64) (*financialDagExecution, error) {
	if !execution.source.hasProtocol() {
		return execution, nil
	}
	derived, err := financialNativeState(before, execution, before.Height)
	if err != nil || derived.StateRoot != before.StateRoot {
		return nil, errFinancialProtocol
	}
	money, err := advanceFinancialProtocol(ctx, execution.genesis, execution.anchor, execution.money, before, whenNs)
	if err != nil {
		return nil, err
	}
	updated := execution.clone()
	updated.money = money
	return updated, nil
}
