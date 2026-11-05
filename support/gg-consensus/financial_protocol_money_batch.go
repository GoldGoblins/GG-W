package main

// Ordered account execution with a bounded block-local overlay. All individual
// signatures are checked upstream. Only final dirty account values update the
// authenticated tree, in deterministic debit-then-credit order. Receipts bind
// each outcome to the block summary rather than inventing per-transaction
// intermediate global roots.
import (
	"context"
	"sort"
	"strconv"
)

type protocolAccountDelta struct {
	address                         string
	balance, nonce, originalBalance uint64
	exists, wasPresent, dirty       bool
}

type protocolMoneyBatch struct {
	tree        financialAccountTree
	rows        map[string]*protocolAccountDelta
	count, fees uint64
}

func newProtocolMoneyBatch(tree financialAccountTree) *protocolMoneyBatch {
	return &protocolMoneyBatch{tree: tree, rows: map[string]*protocolAccountDelta{}, count: tree.root.link.Count}
}

func (batch *protocolMoneyBatch) account(ctx context.Context, address string) (*protocolAccountDelta, error) {
	if row := batch.rows[address]; row != nil {
		return row, nil
	}
	if len(batch.rows) >= 2*financialMaxTransactions {
		return nil, errFinancialAccount
	}
	account, exists, err := batch.tree.get(ctx, address)
	if err != nil {
		return nil, err
	}
	row := &protocolAccountDelta{address: address, exists: exists, wasPresent: exists}
	if exists {
		balance, ok := financialAccountAmount(account.Balance, batch.tree.rules.MaxTotal)
		if !ok {
			return nil, errFinancialAccount
		}
		row.balance, row.originalBalance, row.nonce = balance, balance, account.Nonce
	}
	batch.rows[address] = row
	return row, nil
}

func (batch *protocolMoneyBatch) apply(ctx context.Context, envelope Envelope, fee uint64) (string, error) {
	if err := ctx.Err(); err != nil {
		return "", err
	}
	body := envelope.Body
	if body.Sender == body.Recipient || body.MaxFee == nil {
		return "", errFinancialProtocol
	}
	from, err := batch.account(ctx, body.Sender)
	if err != nil {
		return "", err
	}
	if !from.exists {
		return "REJECTED_FUNDS", nil
	}
	if from.nonce != body.Nonce {
		return "REJECTED_NONCE", nil
	}
	if from.nonce == economicMaxUint {
		return "REJECTED_NONCE_EXHAUSTED", nil
	}
	maximum, ok := economicAmount(*body.MaxFee)
	if !ok {
		return "", errFinancialProtocol
	}
	if maximum < fee {
		return "REJECTED_FEE_LIMIT", nil
	}
	amount, ok := economicAmount(body.Amount)
	if !ok || amount == 0 {
		return "", errFinancialProtocol
	}
	if amount > from.balance || fee > from.balance-amount {
		return "REJECTED_FUNDS", nil
	}
	to, err := batch.account(ctx, body.Recipient)
	if err != nil {
		return "", err
	}
	if !to.exists && batch.count >= batch.tree.rules.MaxAccounts {
		return "REJECTED_ACCOUNT_LIMIT", nil
	}
	if to.balance > batch.tree.rules.MaxTotal || amount > batch.tree.rules.MaxTotal-to.balance {
		return "REJECTED_FUNDS", nil
	}
	if fee > economicMaxUint-batch.fees {
		return "", errFinancialProtocol
	}
	if !to.exists {
		to.exists = true
		batch.count++
	}
	from.balance -= amount + fee
	from.nonce++
	from.dirty = true
	to.balance += amount
	to.dirty = true
	batch.fees += fee
	return "APPLIED", nil
}

func (batch *protocolMoneyBatch) finish(ctx context.Context) (financialAccountTree, error) {
	return batch.finishWithWorkspaceLimit(ctx, financialAccountWorkspaceBytes)
}

func (batch *protocolMoneyBatch) finishWithWorkspaceLimit(ctx context.Context, limit uint64) (financialAccountTree, error) {
	addresses := make([]string, 0, len(batch.rows))
	for address, row := range batch.rows {
		if row.dirty {
			addresses = append(addresses, address)
		}
	}
	sort.Strings(addresses)
	next, usedWorkspace, err := batch.finishWorkspace(ctx, addresses, limit)
	if err != nil {
		return batch.tree, err
	}
	// Debit/nonincreasing leaves first preserve the tree's supply ceiling even
	// when the credited address sorts before its funding account.
	if !usedWorkspace {
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
	}
	before, bok := economicAmount(batch.tree.root.link.Total)
	after, aok := economicAmount(next.root.link.Total)
	if !bok || !aok || batch.fees > before || after != before-batch.fees || next.root.link.Count != batch.count {
		return batch.tree, errFinancialAccount
	}
	return next, nil
}
