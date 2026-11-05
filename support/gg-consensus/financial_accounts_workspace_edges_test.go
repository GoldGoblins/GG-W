//go:build !js

package main

// Exact kernel differentials, not evidence of network execution or throughput.
// Equal-height rotation ties are tested at the balance helper's intermediate
// topology: valid insertion/update alone does not require deletion-style ties.
import (
	"bytes"
	"context"
	"errors"
	"sort"
	"strconv"
	"testing"
)

func workspaceEdgeKeys(start, count int) []string {
	keys := make([]string, count)
	for index := range keys {
		keys[index] = financialAccountTestAddress(start + index)
	}
	sort.Strings(keys)
	return keys
}

func TestAccountWorkspaceExplicitLLLRRRRLAfterEverySetAndFrozenAlias(t *testing.T) {
	ctx := context.Background()
	keys := workspaceEdgeKeys(970000, 3)
	for _, value := range []struct {
		name  string
		order []int
	}{
		{"LL", []int{2, 1, 0}}, {"LR", []int{2, 0, 1}},
		{"RR", []int{0, 1, 2}}, {"RL", []int{0, 2, 1}},
	} {
		t.Run(value.name, func(t *testing.T) {
			base, err := newFinancialAccountTree(financialAccountTestRules())
			if err != nil {
				t.Fatal(err)
			}
			work, err := newFinancialAccountWorkspace(base, financialAccountWorkspaceBytes)
			if err != nil {
				t.Fatal(err)
			}
			reference := base
			frozen := []financialAccountTree{}
			frozenRoots := []financialAccountLink{}
			frozenBytes := []map[string][]byte{}
			for step, index := range value.order {
				account := Account{Address: keys[index], Balance: strconv.Itoa(100 + step), Nonce: uint64(step)}
				reference, err = reference.set(ctx, account)
				if err != nil {
					t.Fatal(step, err)
				}
				if err = work.set(ctx, account); err != nil {
					t.Fatal(step, err)
				}
				actual, err := work.freeze(ctx)
				if err != nil {
					t.Fatal(step, err)
				}
				compareWorkspaceTrees(t, actual, reference)
				for old, snapshot := range frozen {
					if snapshot.root.link != frozenRoots[old] {
						t.Fatal("old frozen root changed")
					}
					after := workspaceNodeBytes(t, snapshot)
					for hash, raw := range frozenBytes[old] {
						if !bytes.Equal(after[hash], raw) {
							t.Fatal("COW reused mutable state after freeze", step, old)
						}
					}
				}
				frozen = append(frozen, actual)
				frozenRoots = append(frozenRoots, actual.root.link)
				frozenBytes = append(frozenBytes, workspaceNodeBytes(t, actual))
				if base.root.link.Count != 0 {
					t.Fatal("immutable base changed")
				}
			}
			actual, err := work.freeze(ctx)
			if err != nil {
				t.Fatal(err)
			}
			if actual.root.node.Account.Address != keys[1] {
				t.Fatal("wrong explicit rotation root", value.name)
			}
			// A later replacement must preserve topology while updating only exact
			// account/aggregate bytes. Earlier published roots must remain unchanged.
			account := actual.root.node.Account.account()
			account.Nonce++
			reference, err = reference.set(ctx, account)
			if err != nil {
				t.Fatal(err)
			}
			if err = work.set(ctx, account); err != nil {
				t.Fatal(err)
			}
			replacement, err := work.freeze(ctx)
			if err != nil {
				t.Fatal(err)
			}
			compareWorkspaceTrees(t, replacement, reference)
			for old, snapshot := range frozen {
				after := workspaceNodeBytes(t, snapshot)
				for hash, raw := range frozenBytes[old] {
					if !bytes.Equal(after[hash], raw) {
						t.Fatal("replacement mutated a frozen checked value")
					}
				}
			}
		})
	}
}

func TestAccountWorkspaceExplicitEqualHeightRotationTiesMatchImmutableBalance(t *testing.T) {
	ctx := context.Background()
	keys := workspaceEdgeKeys(971000, 5)
	for _, leftHeavy := range []bool{true, false} {
		name := "right-heavy-equal-children"
		if leftHeavy {
			name = "left-heavy-equal-children"
		}
		t.Run(name, func(t *testing.T) {
			base, err := newFinancialAccountTree(financialAccountTestRules())
			if err != nil {
				t.Fatal(err)
			}
			empty := financialAccountRef{link: financialAccountEmpty(base.rulesHash)}
			leaf := func(index int) financialAccountRef {
				ref, err := base.make(Account{Address: keys[index], Balance: "10"}, empty, empty)
				if err != nil {
					t.Fatal(err)
				}
				return ref
			}
			var account Account
			var left, right financialAccountRef
			var expectedRoot string
			if leftHeavy {
				left, err = base.make(Account{Address: keys[1], Balance: "10"}, leaf(0), leaf(2))
				account = Account{Address: keys[3], Balance: "10"}
				right = empty
				expectedRoot = keys[1]
			} else {
				right, err = base.make(Account{Address: keys[3], Balance: "10"}, leaf(2), leaf(4))
				account = Account{Address: keys[1], Balance: "10"}
				left = empty
				expectedRoot = keys[3]
			}
			if err != nil {
				t.Fatal(err)
			}
			heavy := left
			if !leftHeavy {
				heavy = right
			}
			if heavy.node.Left.Height != heavy.node.Right.Height {
				t.Fatal("fixture does not exercise equal-height branch")
			}
			originalHeavy := canonical(*heavy.node)
			expected, err := base.balance(ctx, account, left, right)
			if err != nil {
				t.Fatal(err)
			}
			reference := base
			reference.root = expected
			work, err := newFinancialAccountWorkspace(base, financialAccountWorkspaceBytes)
			if err != nil {
				t.Fatal(err)
			}
			node, err := work.allocate(account, financialAccountWorkspaceRef{base: left}, financialAccountWorkspaceRef{base: right})
			if err != nil {
				t.Fatal(err)
			}
			work.root, err = work.balance(ctx, node)
			if err != nil {
				t.Fatal(err)
			}
			actual, err := work.freeze(ctx)
			if err != nil {
				t.Fatal(err)
			}
			compareWorkspaceTrees(t, actual, reference)
			if actual.root.node.Account.Address != expectedRoot {
				t.Fatal("equal-height tie chose a different single rotation")
			}
			if !bytes.Equal(originalHeavy, canonical(*heavy.node)) || base.root.link.Count != 0 {
				t.Fatal("tie rotation mutated authenticated input")
			}
		})
	}
}

func TestAccountWorkspaceDenseAndSparseMixedExistingNewAfterEachSet(t *testing.T) {
	ctx := context.Background()
	keys := workspaceEdgeKeys(972000, 256)
	for _, dense := range []bool{true, false} {
		name := "sparse"
		if dense {
			name = "dense"
		}
		t.Run(name, func(t *testing.T) {
			base, err := newFinancialAccountTree(financialAccountTestRules())
			if err != nil {
				t.Fatal(err)
			}
			for index := 0; index < len(keys); index += 2 {
				base, err = base.set(ctx, Account{Address: keys[index], Balance: "1000"})
				if err != nil {
					t.Fatal(err)
				}
			}
			before := workspaceNodeBytes(t, base)
			beforeRoot := base.root.link
			work, err := newFinancialAccountWorkspace(base, financialAccountWorkspaceBytes)
			if err != nil {
				t.Fatal(err)
			}
			reference := base
			for step := 0; step < 48; step++ {
				index := step
				if !dense {
					index = (step*37 + 11) % len(keys)
				}
				account := Account{Address: keys[index], Balance: strconv.Itoa(100 + step), Nonce: uint64(step + 1)}
				reference, err = reference.set(ctx, account)
				if err != nil {
					t.Fatal(step, err)
				}
				if err = work.set(ctx, account); err != nil {
					t.Fatal(step, err)
				}
				actual, err := work.freeze(ctx)
				if err != nil {
					t.Fatal(step, err)
				}
				compareWorkspaceTrees(t, actual, reference)
				if base.root.link != beforeRoot {
					t.Fatal("base root changed")
				}
			}
			after := workspaceNodeBytes(t, base)
			for hash, raw := range before {
				if !bytes.Equal(after[hash], raw) {
					t.Fatal("dense/sparse update changed immutable base bytes")
				}
			}
		})
	}
}

func TestAccountWorkspaceExactByteEligibilityAndAllocationBoundary(t *testing.T) {
	ctx := context.Background()
	charge := financialAccountWorkspaceNodeCharge()
	capacity := (financialAccountWorkspaceBytes - financialAccountWorkspaceReserve) / charge
	if capacity < 5008 || capacity > 2*financialMaxTransactions {
		t.Fatal("private quota no longer covers documented fixture or bounded test", capacity, charge)
	}
	tree, err := newFinancialAccountTree(financialAccountTestRules())
	if err != nil {
		t.Fatal(err)
	}
	var fits, overflow financialAccountTree
	for index := uint64(0); index <= capacity; index++ {
		tree, err = tree.set(ctx, Account{Address: financialAccountTestAddress(973000 + int(index)), Balance: "1000"})
		if err != nil {
			t.Fatal(err)
		}
		if index+1 == capacity {
			fits = tree
		}
	}
	overflow = tree
	makeBatch := func(base financialAccountTree, count uint64) *protocolMoneyBatch {
		batch := newProtocolMoneyBatch(base)
		for index := uint64(0); index < count; index++ {
			address := financialAccountTestAddress(973000 + int(index))
			account, exists, err := base.get(ctx, address)
			if err != nil || !exists {
				t.Fatal(index, exists, err)
			}
			balance, _ := financialAccountAmount(account.Balance, base.rules.MaxTotal)
			batch.rows[address] = &protocolAccountDelta{address: address, balance: balance, originalBalance: balance, nonce: account.Nonce + 1, exists: true, wasPresent: true, dirty: true}
		}
		return batch
	}
	batch := makeBatch(fits, capacity)
	addresses := workspaceAddresses(batch)
	exact := financialAccountWorkspaceReserve + capacity*charge
	for _, value := range []struct {
		limit uint64
		want  bool
	}{
		{exact - 1, false}, {exact, true}, {financialAccountWorkspaceBytes, true},
	} {
		eligible, bound, err := batch.workspaceEligibility(ctx, addresses, value.limit)
		if err != nil || eligible != value.want || bound != capacity {
			t.Fatal("off-by-one preflight", value, eligible, bound, err)
		}
	}
	tooMany := makeBatch(overflow, capacity+1)
	if eligible, bound, err := tooMany.workspaceEligibility(ctx, workspaceAddresses(tooMany), financialAccountWorkspaceBytes); err != nil || eligible || bound != capacity+1 {
		t.Fatal("one-too-many bound admitted", eligible, bound, err)
	}
	before := fits.root.link
	work, err := newFinancialAccountWorkspace(fits, exact)
	if err != nil {
		t.Fatal(err)
	}
	for _, address := range addresses {
		row := batch.rows[address]
		if err = work.set(ctx, Account{Address: address, Balance: strconv.FormatUint(row.balance, 10), Nonce: row.nonce}); err != nil {
			t.Fatal("exact boundary failed early", err)
		}
	}
	if uint64(work.nodes) != capacity || work.bytes != exact {
		t.Fatal("actual ownership did not exercise exact byte boundary", work.nodes, work.bytes, capacity, exact)
	}
	actual, err := work.freeze(ctx)
	if err != nil {
		t.Fatal(err)
	}
	expected, err := workspaceReferenceFinish(ctx, batch)
	if err != nil {
		t.Fatal(err)
	}
	compareWorkspaceTrees(t, actual, expected)
	// The next absent account needs one additional owned node. It must hit only
	// the private budget and leave the original immutable base unchanged.
	if err = work.set(ctx, Account{Address: financialAccountTestAddress(980000), Balance: "1"}); !errors.Is(err, errFinancialAccountWorkspaceBudget) {
		t.Fatal("allocation quota did not stop next node", err)
	}
	if fits.root.link != before {
		t.Fatal("budget failure mutated immutable base")
	}
	compareWorkspaceTrees(t, actual, expected)
	fallback, err := batch.finishWithWorkspaceLimit(ctx, exact-1)
	if err != nil {
		t.Fatal(err)
	}
	compareWorkspaceTrees(t, fallback, expected)
	// Conservative rejection also applies to large-base DENSE updates. This is
	// an intentional optimization miss, not a generally scalable capacity path.
	// The direct private helper below demonstrates why the bound can miss: it
	// does not bypass the production preflight or increase the allocation cap.
	dense := newProtocolMoneyBatch(overflow)
	keys := workspaceEdgeKeys(973000, int(capacity+1))
	for _, address := range keys[:64] {
		account, exists, err := overflow.get(ctx, address)
		if err != nil || !exists {
			t.Fatal(err)
		}
		balance, _ := financialAccountAmount(account.Balance, overflow.rules.MaxTotal)
		dense.rows[address] = &protocolAccountDelta{address: address, balance: balance, originalBalance: balance, nonce: account.Nonce + 1, exists: true, wasPresent: true, dirty: true}
	}
	denseAddresses := workspaceAddresses(dense)
	eligible, bound, err := dense.workspaceEligibility(ctx, denseAddresses, financialAccountWorkspaceBytes)
	if err != nil || eligible || bound != capacity+1 {
		t.Fatal("large dense false miss contract changed", eligible, bound, err)
	}
	denseExpected, err := workspaceReferenceFinish(ctx, dense)
	if err != nil {
		t.Fatal(err)
	}
	denseFallback, err := dense.finish(ctx)
	if err != nil {
		t.Fatal(err)
	}
	compareWorkspaceTrees(t, denseFallback, denseExpected)
	direct, err := newFinancialAccountWorkspace(overflow, financialAccountWorkspaceBytes)
	if err != nil {
		t.Fatal(err)
	}
	for _, address := range denseAddresses {
		row := dense.rows[address]
		if err = direct.set(ctx, Account{Address: address, Balance: strconv.FormatUint(row.balance, 10), Nonce: row.nonce}); err != nil {
			t.Fatal(err)
		}
	}
	if uint64(direct.nodes) >= capacity {
		t.Fatal("dense fixture no longer demonstrates conservative miss", direct.nodes, capacity)
	}
	denseResult, err := direct.freeze(ctx)
	if err != nil {
		t.Fatal(err)
	}
	compareWorkspaceTrees(t, denseResult, denseExpected)
}

func TestAccountWorkspaceEmptyAndReadonlyFinishCancellation(t *testing.T) {
	for _, readonly := range []bool{false, true} {
		name := "empty"
		if readonly {
			name = "existing-readonly"
		}
		t.Run(name, func(t *testing.T) {
			ctx := context.Background()
			base := financialAccountTestTree(t, 7)
			before := workspaceNodeBytes(t, base)
			batch := newProtocolMoneyBatch(base)
			var row *protocolAccountDelta
			var original protocolAccountDelta
			if readonly {
				var err error
				row, err = batch.account(ctx, base.root.node.Account.Address)
				if err != nil || !row.exists || row.dirty {
					t.Fatal("readonly lookup changed admission state", row, err)
				}
				original = *row
			}
			if len(workspaceAddresses(batch)) != 0 {
				t.Fatal("fixture unexpectedly contains a dirty account")
			}
			cancelled, cancel := context.WithCancel(ctx)
			cancel()
			actual, err := batch.finish(cancelled)
			if !errors.Is(err, context.Canceled) || actual.root.link != base.root.link {
				t.Fatal("empty/readonly cancellation must return the original tree and context error", err)
			}
			compareWorkspaceTrees(t, actual, base)
			// The old finish has no loop iteration for either fixture. The
			// earlier cancellation check is an intentional stricter contract.
			legacy, err := workspaceReferenceFinish(cancelled, batch)
			if err != nil {
				t.Fatal("reference no-dirty behavior changed", err)
			}
			compareWorkspaceTrees(t, legacy, base)
			actual, err = batch.finish(ctx)
			if err != nil {
				t.Fatal(err)
			}
			expected, err := workspaceReferenceFinish(ctx, batch)
			if err != nil {
				t.Fatal(err)
			}
			compareWorkspaceTrees(t, actual, expected)
			compareWorkspaceTrees(t, actual, base)
			if readonly && *row != original {
				t.Fatal("finish mutated the existing readonly overlay row")
			}
			after := workspaceNodeBytes(t, base)
			if len(after) != len(before) {
				t.Fatal("no-dirty finish changed immutable base node count")
			}
			for hash, raw := range before {
				if !bytes.Equal(raw, after[hash]) {
					t.Fatal("no-dirty finish mutated original canonical base bytes", hash)
				}
			}
		})
	}
}
