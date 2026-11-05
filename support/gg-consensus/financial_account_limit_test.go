package main

import (
	"context"
	"testing"
)

// Capacity is a deterministic state-dependent rejection, not corrupt storage.
// One authentic payment to a new account must not abort the remaining batch.
func TestFinancialAccountTreeAccountLimitKeepsExistingTransfersAvailable(t *testing.T) {
	ctx := context.Background()
	rules := financialAccountTestRules()
	rules.MaxAccounts = 2
	tree, err := newFinancialAccountTree(rules)
	if err != nil {
		t.Fatal(err)
	}
	a, b, c := financialAccountTestAddress(0), financialAccountTestAddress(1), financialAccountTestAddress(2)
	tree, err = tree.set(ctx, Account{Address: a, Balance: "100"})
	if err != nil {
		t.Fatal(err)
	}
	tree, _, err = tree.transfer(ctx, a, b, 1, 0)
	if err != nil {
		t.Fatal(err)
	}
	before := tree.root.link
	next, outcome, err := tree.transfer(ctx, a, c, 1, 1)
	if err != nil || outcome != "REJECTED_ACCOUNT_LIMIT" || next.root.link != before {
		t.Fatal("account-cap conflict must be a nonmutating outcome", outcome, err)
	}
	tree, outcome, err = next.transfer(ctx, a, b, 2, 1)
	if err != nil || outcome != "APPLIED" || tree.root.link.Count != 2 || tree.root.link.Total != "100" {
		t.Fatal("existing-account traffic did not continue", outcome, err)
	}
	from, _, err := tree.get(ctx, a)
	if err != nil || from.Balance != "97" || from.Nonce != 2 {
		t.Fatal(from, err)
	}
}
