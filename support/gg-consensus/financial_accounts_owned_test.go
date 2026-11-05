//go:build !js

package main

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"math/rand"
	"sort"
	"strconv"
	"strings"
	"testing"
)

func compareOwnedAccountTreeToBaseline(t *testing.T, current financialAccountTree, reference baselineFinancialAccountTree) {
	t.Helper()
	if !bytes.Equal(canonical(current.root.link), canonical(reference.root.link)) {
		t.Fatal("pre-change AVL root/metadata changed", current.root.link, reference.root.link)
	}
	actual, expected := map[string][]byte{}, map[string][]byte{}
	if err := current.stage(context.Background(), financialAccountStageMaxNodes, func(hash string, raw []byte) error {
		actual[hash] = append([]byte(nil), raw...)
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	if err := reference.stage(context.Background(), baselineFinancialAccountStageMaxNodes, func(hash string, raw []byte) error {
		expected[hash] = append([]byte(nil), raw...)
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	if len(actual) != len(expected) {
		t.Fatal("reachable staged-node count changed", len(actual), len(expected))
	}
	for hash, raw := range expected {
		if !bytes.Equal(actual[hash], raw) {
			t.Fatal("pre-change canonical account-node bytes changed", hash)
		}
	}
}

func baselineAccountRules(rules financialAccountRules) baselineFinancialAccountRules {
	return baselineFinancialAccountRules{Genesis: rules.Genesis, MaxAccounts: rules.MaxAccounts, MaxTotal: rules.MaxTotal, Schema: rules.Schema}
}

func TestOwnedAccountNodesKeepEveryPrechangeAVLRootAndStagedByte(t *testing.T) {
	ctx := context.Background()
	rules := financialAccountTestRules()
	current, err := newFinancialAccountTree(rules)
	if err != nil {
		t.Fatal(err)
	}
	reference, err := baselineNewFinancialAccountTree(baselineAccountRules(rules))
	if err != nil {
		t.Fatal(err)
	}
	addresses := make([]string, 63)
	for index := range addresses {
		addresses[index] = financialAccountTestAddress(index + 40000)
	}
	sort.Strings(addresses)
	// Ordered insertion, alternating extremes and random existing-account
	// updates force rotation/rebalancing and overlapping old immutable paths.
	order := append([]string(nil), addresses...)
	for left, right := 0, len(addresses)-1; left <= right; left, right = left+1, right-1 {
		order = append(order, addresses[right])
		if left != right {
			order = append(order, addresses[left])
		}
	}
	rng := rand.New(rand.NewSource(90210))
	for index := 0; index < 126; index++ {
		order = append(order, addresses[rng.Intn(len(addresses))])
	}
	for index, address := range order {
		before, beforeReference := current, reference
		account := Account{Address: address, Balance: strconv.Itoa(1000 + index%37), Nonce: uint64(index)}
		current, err = current.set(ctx, account)
		if err != nil {
			t.Fatal(index, err)
		}
		reference, err = reference.set(ctx, account)
		if err != nil {
			t.Fatal(index, err)
		}
		compareOwnedAccountTreeToBaseline(t, current, reference)
		// Updating a new path must leave each preceding immutable tree intact.
		compareOwnedAccountTreeToBaseline(t, before, beforeReference)
	}
}

func TestOwnedAccountNodesKeepOverlappingPaymentBatchAndDebitFirstRoot(t *testing.T) {
	ctx := context.Background()
	rules := financialAccountTestRules()
	current, _ := newFinancialAccountTree(rules)
	reference, _ := baselineNewFinancialAccountTree(baselineAccountRules(rules))
	addresses := make([]string, 31)
	model, original := map[string]Account{}, map[string]uint64{}
	for index := range addresses {
		address := financialAccountTestAddress(index + 50000)
		addresses[index] = address
		account := Account{Address: address, Balance: "100000"}
		model[address], original[address] = account, 100000
		var err error
		current, err = current.set(ctx, account)
		if err != nil {
			t.Fatal(err)
		}
		reference, err = reference.set(ctx, account)
		if err != nil {
			t.Fatal(err)
		}
	}
	batch := newProtocolMoneyBatch(current)
	cap := "7"
	for index := 0; index < 217; index++ {
		from, to := addresses[index%len(addresses)], addresses[(index*7+1)%len(addresses)]
		if from == to {
			to = addresses[(index+1)%len(addresses)]
		}
		sender, receiver := model[from], model[to]
		amount := uint64(index%13 + 1)
		envelope := Envelope{Body: Body{Sender: from, Recipient: to, Amount: strconv.FormatUint(amount, 10), MaxFee: &cap, Nonce: sender.Nonce, Version: 2}}
		outcome, err := batch.apply(ctx, envelope, 7)
		if err != nil || outcome != "APPLIED" {
			t.Fatal(index, outcome, err)
		}
		balance, _ := strconv.ParseUint(sender.Balance, 10, 64)
		target, _ := strconv.ParseUint(receiver.Balance, 10, 64)
		sender.Balance, sender.Nonce = strconv.FormatUint(balance-amount-7, 10), sender.Nonce+1
		receiver.Balance = strconv.FormatUint(target+amount, 10)
		model[from], model[to] = sender, receiver
	}
	actual, err := batch.finish(ctx)
	if err != nil {
		t.Fatal(err)
	}
	sort.Strings(addresses)
	// The reference retains the pre-change sorted debit/nonincreasing-first
	// update schedule. Rebuilding a differently balanced tree is not permitted.
	for phase := 0; phase < 2; phase++ {
		for _, address := range addresses {
			value := model[address]
			balance, _ := strconv.ParseUint(value.Balance, 10, 64)
			debit := balance <= original[address]
			if phase == 0 && !debit || phase == 1 && debit {
				continue
			}
			reference, err = reference.set(ctx, value)
			if err != nil {
				t.Fatal(err)
			}
		}
	}
	compareOwnedAccountTreeToBaseline(t, actual, reference)
	if actual.root.link.Total != strconv.Itoa(31*100000-217*7) {
		t.Fatal("fees or supply ceiling changed")
	}
	for address, expected := range model {
		account, exists, err := actual.get(ctx, address)
		if err != nil || !exists || account != expected {
			t.Fatal(address, account, expected, err)
		}
	}
}

func TestOwnedAccountNodeHandlesRejectAliasParentRulesAndBoundsChanges(t *testing.T) {
	ctx := context.Background()
	tree := financialAccountTestTree(t, 7)
	loaded, _, _, err := tree.load(ctx, tree.root, "", "")
	if err != nil || loaded.checked == nil || tree.root.node.checked == nil {
		t.Fatal("locally constructed node missing private validation handle", err)
	}
	original := *tree.root.node
	loaded.Account.Nonce++
	if *tree.root.node != original {
		t.Fatal("load exposed mutable cache/original node alias")
	}
	bad := tree.root
	bad.node = loaded
	if _, _, _, err := tree.load(ctx, bad, "", ""); err == nil {
		t.Fatal("changed node copy reused immutable validation snapshot")
	}
	for name, mutate := range map[string]func(*financialAccountRef){
		"hash":   func(ref *financialAccountRef) { ref.link.Hash = strings.Repeat("f", 64) },
		"count":  func(ref *financialAccountRef) { ref.link.Count++ },
		"height": func(ref *financialAccountRef) { ref.link.Height++ },
		"total":  func(ref *financialAccountRef) { ref.link.Total = "1" },
		"child": func(ref *financialAccountRef) {
			left := *ref.left
			left.link.Hash = strings.Repeat("e", 64)
			ref.left = &left
		},
	} {
		t.Run(name, func(t *testing.T) {
			ref := tree.root
			mutate(&ref)
			if _, _, _, err := tree.load(ctx, ref, "", ""); err == nil {
				t.Fatal("mismatched expected/child link accepted")
			}
		})
	}
	changed := tree
	changed.rules.MaxTotal++
	if _, _, _, err := changed.load(ctx, changed.root, "", ""); err == nil {
		t.Fatal("modified tree rules reused a validation handle")
	}
	rules := tree.rules
	rules.MaxTotal++
	other, _ := newFinancialAccountTree(rules)
	if _, _, _, err := other.load(ctx, tree.root, "", ""); err == nil {
		t.Fatal("independently valid different rules accepted old node handle")
	}
	for _, bounds := range [][2]string{{original.Account.Address, ""}, {"", original.Account.Address}} {
		if _, _, _, err := tree.load(ctx, tree.root, bounds[0], bounds[1]); err == nil {
			t.Fatal("owned node skipped path ordering bound")
		}
	}
	cancelled, cancel := context.WithCancel(ctx)
	cancel()
	if _, _, _, err := tree.load(cancelled, tree.root, "", ""); !errors.Is(err, context.Canceled) {
		t.Fatal("owned node skipped cancellation", err)
	}
	if _, _, _, err := tree.load(ctx, tree.root, "", ""); err != nil {
		t.Fatal("rejected copies changed original node", err)
	}
}

func TestOwnedAccountNodeRawDecodeCacheAndUncertifiedReaderStayStrict(t *testing.T) {
	ctx := context.Background()
	tree := financialAccountTestTree(t, 7)
	raw := canonical(*tree.root.node)
	decoded, err := decodeFinancialStoredAccount(tree.root.link.Hash, raw, tree.rules)
	if err != nil || decoded.checked == nil {
		t.Fatal(err)
	}
	var cache financialAccountCache
	cache.put(tree.root.link.Hash, decoded)
	copy, ok := cache.get(tree.root.link.Hash)
	if !ok {
		t.Fatal("checked node not cached")
	}
	copy.Account.Nonce++
	retained, ok := cache.get(tree.root.link.Hash)
	if !ok || retained.Account != decoded.Account {
		t.Fatal("cache returned mutable body alias")
	}
	for name, candidate := range map[string][]byte{
		"space":        append([]byte(" "), raw...),
		"oversize":     make([]byte, financialAccountNodeMaxBytes+1),
		"private_flag": append(append([]byte(nil), raw[:len(raw)-1]...), []byte(`,"checked":true}`)...),
		"bad_balance":  bytes.Replace(raw, []byte(`"balance_atomic":"1000"`), []byte(`"balance_atomic":"1001"`), 1),
	} {
		t.Run(name, func(t *testing.T) {
			if _, err := decodeFinancialStoredAccount(tree.root.link.Hash, candidate, tree.rules); err == nil {
				t.Fatal("raw bytes bypassed strict decoding/hash validation")
			}
		})
	}
	forged := decoded
	forged.checked = nil
	forged.Account.Nonce++
	cold, err := tree.freeze(func(string) (financialAccountNode, error) { return forged, nil })
	if err != nil {
		t.Fatal(err)
	}
	if _, _, _, err := cold.load(ctx, cold.root, "", ""); err == nil {
		t.Fatal("ordinary reader callback was treated as trusted")
	}
	// A carried local handle does not make a public proof authoritative.
	proof, err := tree.proof(ctx, decoded.Account.Address)
	if err != nil || len(proof.Path) != 1 {
		t.Fatal(err)
	}
	proof.Path[0].Account.Nonce++
	if _, _, err := verifyFinancialAccountProof(ctx, proof, tree.root.link, tree.rules); err == nil {
		t.Fatal("changed public proof reused private local validation handle")
	}
	if _, err := decodeFinancialStoredAccount(fmt.Sprintf("%064x", 1), raw, tree.rules); err == nil {
		t.Fatal("wrong expected storage hash accepted")
	}
}
