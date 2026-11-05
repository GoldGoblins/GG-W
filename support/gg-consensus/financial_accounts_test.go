package main

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"math/rand"
	"sort"
	"strconv"
	"strings"
	"testing"
)

func TestFinancialAccountTreeIntegerBoundariesAndWire(t *testing.T) {
	ctx := context.Background()
	rules := financialAccountTestRules()
	rules.MaxTotal = ^uint64(0)
	tree, err := newFinancialAccountTree(rules)
	if err != nil {
		t.Fatal(err)
	}
	a, b := financialAccountTestAddress(0), financialAccountTestAddress(1)
	nonce := uint64(1<<53) + 17
	tree, err = tree.set(ctx, Account{Address: a, Balance: "18446744073709551615", Nonce: nonce})
	if err != nil {
		t.Fatal(err)
	}
	next, outcome, err := tree.transfer(ctx, a, b, ^uint64(0), nonce)
	if err != nil || outcome != "APPLIED" || next.root.link.Total != "18446744073709551615" {
		t.Fatal(outcome, err)
	}
	from, _, err := next.get(ctx, a)
	if err != nil || from.Balance != "0" || from.Nonce != nonce+1 {
		t.Fatal(from, err)
	}
	exhausted, err := tree.set(ctx, Account{Address: a, Balance: "18446744073709551615", Nonce: ^uint64(0)})
	if err != nil {
		t.Fatal(err)
	}
	raw := canonical(*exhausted.root.node)
	if !bytes.Contains(raw, []byte(`"nonce":"18446744073709551615"`)) {
		t.Fatal("nonce lost exact decimal-string encoding")
	}
	decoded, err := decodeFinancialAccountNode(raw, exhausted.root.link, rules)
	if err != nil || decoded.Account.Nonce != ^uint64(0) {
		t.Fatal(decoded, err)
	}
	numeric := bytes.Replace(raw, []byte(`"nonce":"18446744073709551615"`), []byte(`"nonce":18446744073709551615`), 1)
	if _, err := decodeFinancialAccountNode(numeric, exhausted.root.link, rules); err == nil {
		t.Fatal("numeric nonce accepted in new account encoding")
	}
	for _, bad := range []string{"", "-1", "+1", "01", "18446744073709551616", strings.Repeat("9", 2049)} {
		if _, ok := financialAccountAmount(bad, ^uint64(0)); ok {
			t.Fatal("invalid/unbounded amount accepted")
		}
	}
}

func financialAccountTestAddress(index int) string {
	seed := sha256.Sum256([]byte(fmt.Sprintf("PUBLIC-FINANCIAL-ACCOUNT-DICTIONARY-TEST-%d", index)))
	return hex.EncodeToString(ed25519.NewKeyFromSeed(seed[:]).Public().(ed25519.PublicKey))
}
func financialAccountTestRules() financialAccountRules {
	return financialAccountRules{Genesis: strings.Repeat("a", 64), MaxAccounts: 8192, MaxTotal: Supply, Schema: "gg.financial.account-rules.v1"}
}
func financialAccountTestTree(t *testing.T, count int) financialAccountTree {
	t.Helper()
	tree, err := newFinancialAccountTree(financialAccountTestRules())
	if err != nil {
		t.Fatal(err)
	}
	for index := 0; index < count; index++ {
		tree, err = tree.set(context.Background(), Account{Address: financialAccountTestAddress(index), Balance: "1000"})
		if err != nil {
			t.Fatal(index, err)
		}
	}
	return tree
}
func financialAccountTestDisk(t *testing.T, tree financialAccountTree) (financialAccountTree, map[string][]byte) {
	t.Helper()
	disk := map[string][]byte{}
	err := tree.stage(context.Background(), financialAccountStageMaxNodes, func(hash string, raw []byte) error { disk[hash] = append([]byte(nil), raw...); return nil })
	if err != nil {
		t.Fatal(err)
	}
	if uint64(len(disk)) != tree.root.link.Count {
		t.Fatal("stage must retain exactly reachable nodes")
	}
	cold, err := tree.freeze(func(hash string) (financialAccountNode, error) {
		raw, ok := disk[hash]
		if !ok {
			return financialAccountNode{}, errors.New("missing test disk node")
		}
		var node financialAccountNode
		if decodeStrict(raw, &node) != nil {
			return node, errFinancialAccount
		}
		return decodeFinancialAccountNode(raw, financialAccountNodeLink(node), tree.rules)
	})
	if err != nil {
		t.Fatal(err)
	}
	return cold, disk
}

func TestFinancialAccountTreeRulesAndEmptyAbsence(t *testing.T) {
	ctx := context.Background()
	rules := financialAccountTestRules()
	for name, change := range map[string]func(*financialAccountRules){
		"schema": func(v *financialAccountRules) { v.Schema = "unknown" }, "genesis": func(v *financialAccountRules) { v.Genesis = "bad" },
		"zero_count": func(v *financialAccountRules) { v.MaxAccounts = 0 }, "count_overflow": func(v *financialAccountRules) { v.MaxAccounts = 1<<32 + 1 }, "zero_total": func(v *financialAccountRules) { v.MaxTotal = 0 },
	} {
		t.Run(name, func(t *testing.T) {
			bad := rules
			change(&bad)
			if _, err := newFinancialAccountTree(bad); err == nil {
				t.Fatal("accepted invalid rules")
			}
		})
	}
	tree, err := newFinancialAccountTree(rules)
	if err != nil {
		t.Fatal(err)
	}
	proof, err := tree.proof(ctx, financialAccountTestAddress(0))
	if err != nil {
		t.Fatal(err)
	}
	if proof.Exists || len(proof.Path) != 0 || tree.root.link.Count != 0 {
		t.Fatal("empty state created account")
	}
	if _, exists, err := verifyFinancialAccountProof(ctx, proof, tree.root.link, rules); err != nil || exists {
		t.Fatal(exists, err)
	}
	other := rules
	other.Genesis = strings.Repeat("b", 64)
	if _, _, err := verifyFinancialAccountProof(ctx, proof, tree.root.link, other); err == nil {
		t.Fatal("foreign empty context accepted")
	}
}

func TestFinancialAccountTreeRotationsAndImmutableRoots(t *testing.T) {
	ctx := context.Background()
	addresses := []string{financialAccountTestAddress(0), financialAccountTestAddress(1), financialAccountTestAddress(2)}
	sort.Strings(addresses)
	for _, order := range [][]int{{0, 1, 2}, {2, 1, 0}, {2, 0, 1}, {0, 2, 1}} {
		t.Run(fmt.Sprint(order), func(t *testing.T) {
			tree, _ := newFinancialAccountTree(financialAccountTestRules())
			snapshots := []financialAccountTree{tree}
			for _, index := range order {
				next, err := tree.set(ctx, Account{Address: addresses[index], Balance: "1"})
				if err != nil {
					t.Fatal(err)
				}
				tree = next
				snapshots = append(snapshots, tree)
			}
			if tree.root.link.Count != 3 || tree.root.link.Height != 2 || tree.root.link.Total != "3" || tree.root.node.Account.Address != addresses[1] {
				t.Fatal("AVL rotation/result", tree.root.link)
			}
			for count, old := range snapshots {
				if old.root.link.Count != uint64(count) || old.root.link.Total != strconv.Itoa(count) {
					t.Fatal("old root mutated")
				}
			}
			cold, _ := financialAccountTestDisk(t, tree)
			for _, address := range addresses {
				value, exists, err := cold.get(ctx, address)
				if err != nil || !exists || value.Balance != "1" {
					t.Fatal(value, exists, err)
				}
			}
		})
	}
}

func TestFinancialAccountTreeCanonicalNodesAndProofAttacks(t *testing.T) {
	ctx := context.Background()
	tree := financialAccountTestTree(t, 31)
	for _, index := range []int{0, 1, 15, 30, 100} {
		proof, err := tree.proof(ctx, financialAccountTestAddress(index))
		if err != nil {
			t.Fatal(err)
		}
		_, exists, err := verifyFinancialAccountProof(ctx, proof, tree.root.link, tree.rules)
		if err != nil || exists != (index < 31) {
			t.Fatal(index, exists, err)
		}
		for name, change := range map[string]func(*financialAccountProof){
			"schema": func(v *financialAccountProof) { v.Schema = "other" }, "rules": func(v *financialAccountProof) { v.Rules = strings.Repeat("f", 64) },
			"address": func(v *financialAccountProof) { v.Address = "00" }, "exists": func(v *financialAccountProof) { v.Exists = !v.Exists },
			"missing_path": func(v *financialAccountProof) { v.Path = v.Path[:len(v.Path)-1] }, "extra_path": func(v *financialAccountProof) { v.Path = append(v.Path, v.Path[len(v.Path)-1]) },
			"balance": func(v *financialAccountProof) { v.Path[0].Account.Balance = "01" }, "nonce": func(v *financialAccountProof) { v.Path[0].Account.Nonce++ },
			"count": func(v *financialAccountProof) { v.Path[0].Count++ }, "total": func(v *financialAccountProof) { v.Path[0].Total = "0" },
			"height": func(v *financialAccountProof) { v.Path[0].Height++ }, "left": func(v *financialAccountProof) { v.Path[0].Left.Hash = strings.Repeat("f", 64) },
		} {
			t.Run(fmt.Sprintf("%d/%s", index, name), func(t *testing.T) {
				bad := proof
				bad.Path = append([]financialAccountNode(nil), proof.Path...)
				change(&bad)
				if _, _, err := verifyFinancialAccountProof(ctx, bad, tree.root.link, tree.rules); err == nil {
					t.Fatal("forged proof accepted")
				}
			})
		}
		wrong := tree.root.link
		wrong.Hash = strings.Repeat("f", 64)
		if _, _, err := verifyFinancialAccountProof(ctx, proof, wrong, tree.rules); err == nil {
			t.Fatal("untrusted root accepted")
		}
	}
	raw := canonical(*tree.root.node)
	if _, err := decodeFinancialAccountNode(raw, tree.root.link, tree.rules); err != nil {
		t.Fatal(err)
	}
	for _, bad := range [][]byte{append([]byte(" "), raw...), append(append([]byte(nil), raw...), byte(' ')), []byte(`{"schema":"bad"}`), make([]byte, financialAccountNodeMaxBytes+1)} {
		if _, err := decodeFinancialAccountNode(bad, tree.root.link, tree.rules); err == nil {
			t.Fatal("noncanonical node accepted")
		}
	}
}

func TestFinancialAccountTreeFunding5000DistinctRecipients(t *testing.T) {
	ctx := context.Background()
	tree, _ := newFinancialAccountTree(financialAccountTestRules())
	sender := financialAccountTestAddress(10000)
	var err error
	tree, err = tree.set(ctx, Account{Address: sender, Balance: strconv.FormatUint(Supply, 10)})
	if err != nil {
		t.Fatal(err)
	}
	initial := tree
	for index := 0; index < 5000; index++ {
		old := tree
		var outcome string
		tree, outcome, err = tree.transfer(ctx, sender, financialAccountTestAddress(index), 1, uint64(index))
		if err != nil || outcome != "APPLIED" || tree.root.link.Count != uint64(index+2) || tree.root.link.Total != initial.root.link.Total {
			t.Fatal(index, outcome, err)
		}
		if old.root.link.Count != uint64(index+1) {
			t.Fatal("old tree mutated")
		}
	}
	cold, disk := financialAccountTestDisk(t, tree)
	if len(disk) != 5001 || cold.root.node != nil || cold.root.left != nil || cold.root.right != nil {
		t.Fatal("cold tree retains transient graph")
	}
	from, exists, err := cold.get(ctx, sender)
	if err != nil || !exists || from.Nonce != 5000 || from.Balance != strconv.FormatUint(Supply-5000, 10) {
		t.Fatal(from, exists, err)
	}
	for _, index := range []int{0, 2499, 4999, 5000} {
		proof, err := cold.proof(ctx, financialAccountTestAddress(index))
		if err != nil {
			t.Fatal(err)
		}
		value, exists, err := verifyFinancialAccountProof(ctx, proof, cold.root.link, cold.rules)
		if err != nil || exists != (index < 5000) || exists && value.Balance != "1" {
			t.Fatal(index, value, exists, err)
		}
	}
	if original, _, err := initial.get(ctx, sender); err != nil || original.Nonce != 0 || original.Balance != strconv.FormatUint(Supply, 10) {
		t.Fatal("initial root changed", original, err)
	}
	t.Logf("pure dictionary only:5000 transfers,5001 accounts,height%d,exact reachable staged nodes%d; no signature/SDK/network throughput claim", tree.root.link.Height, len(disk))
}

func TestFinancialAccountTreeTransferOutcomesAndLimits(t *testing.T) {
	ctx := context.Background()
	base := financialAccountTestTree(t, 2)
	a, b, c := financialAccountTestAddress(0), financialAccountTestAddress(1), financialAccountTestAddress(2)
	for _, test := range []struct {
		name, sender, recipient string
		amount, nonce           uint64
		outcome                 string
	}{
		{"nonce", a, b, 1, 1, "REJECTED_NONCE"}, {"funds", a, b, 1001, 0, "REJECTED_FUNDS"}, {"unknown_sender", c, b, 1, 0, "REJECTED_FUNDS"},
	} {
		t.Run(test.name, func(t *testing.T) {
			next, outcome, err := base.transfer(ctx, test.sender, test.recipient, test.amount, test.nonce)
			if err != nil || outcome != test.outcome || next.root.link != base.root.link {
				t.Fatal(outcome, err)
			}
		})
	}
	for _, test := range []struct {
		sender, recipient string
		amount            uint64
	}{{a, a, 1}, {a, b, 0}, {a, b, Supply + 1}, {"00", b, 1}, {a, strings.Repeat("0", 64), 1}} {
		if next, _, err := base.transfer(ctx, test.sender, test.recipient, test.amount, 0); err == nil || next.root.link != base.root.link {
			t.Fatal("invalid transfer changed state", err)
		}
	}
	exhausted, err := base.set(ctx, Account{Address: a, Balance: "1000", Nonce: ^uint64(0)})
	if err != nil {
		t.Fatal(err)
	}
	if next, outcome, err := exhausted.transfer(ctx, a, b, 1, ^uint64(0)); err != nil || outcome != "REJECTED_NONCE_EXHAUSTED" || next.root.link != exhausted.root.link {
		t.Fatal(outcome, err)
	}
	rules := base.rules
	rules.MaxAccounts = 2
	limited, _ := newFinancialAccountTree(rules)
	limited, err = limited.set(ctx, Account{Address: a, Balance: "2000"})
	if err != nil {
		t.Fatal(err)
	}
	limited, _, err = limited.transfer(ctx, a, b, 1, 0)
	if err != nil {
		t.Fatal(err)
	}
	if next, outcome, err := limited.transfer(ctx, a, c, 1, 1); err != nil || outcome != "REJECTED_ACCOUNT_LIMIT" || next.root.link != limited.root.link {
		t.Fatal("account cap partially debited sender")
	}
	if _, exists, err := limited.get(ctx, c); err != nil || exists {
		t.Fatal("rejected funding created an account")
	}
	if next, err := base.set(ctx, Account{Address: c, Balance: strconv.FormatUint(Supply, 10)}); err == nil || next.root.link != base.root.link {
		t.Fatal("total overflow published")
	}
}

func TestFinancialAccountTreeRandomizedTransfersAgainstIndependentMap(t *testing.T) {
	ctx := context.Background()
	tree := financialAccountTestTree(t, 127)
	model := map[string]Account{}
	addresses := []string{}
	for i := 0; i < 127; i++ {
		address := financialAccountTestAddress(i)
		addresses = append(addresses, address)
		model[address] = Account{Address: address, Balance: "1000"}
	}
	rng := rand.New(rand.NewSource(67202))
	for turn := 0; turn < 1500; turn++ {
		a, b := addresses[rng.Intn(len(addresses))], addresses[rng.Intn(len(addresses))]
		if a == b {
			continue
		}
		from, to := model[a], model[b]
		amount := uint64(rng.Intn(97) + 1)
		nonce := from.Nonce
		if turn%7 == 0 {
			nonce++
		}
		balance, _ := strconv.ParseUint(from.Balance, 10, 64)
		destination, _ := strconv.ParseUint(to.Balance, 10, 64)
		expected := "APPLIED"
		if nonce != from.Nonce {
			expected = "REJECTED_NONCE"
		} else if amount > balance {
			expected = "REJECTED_FUNDS"
		}
		next, outcome, err := tree.transfer(ctx, a, b, amount, nonce)
		if err != nil || outcome != expected {
			t.Fatal(turn, outcome, expected, err)
		}
		if expected == "APPLIED" {
			from.Balance = strconv.FormatUint(balance-amount, 10)
			from.Nonce++
			to.Balance = strconv.FormatUint(destination+amount, 10)
			model[a], model[b] = from, to
		} else if next.root.link != tree.root.link {
			t.Fatal("rejection changed root")
		}
		tree = next
		if tree.root.link.Total != "127000" || tree.root.link.Count != 127 {
			t.Fatal("supply/count changed")
		}
	}
	for address, expected := range model {
		actual, exists, err := tree.get(ctx, address)
		if err != nil || !exists || actual != expected {
			t.Fatal(address, actual, expected, err)
		}
	}
}

func TestFinancialAccountTreeMissingCorruptDiskAndStaging(t *testing.T) {
	ctx := context.Background()
	tree := financialAccountTestTree(t, 63)
	cold, disk := financialAccountTestDisk(t, tree)
	address := financialAccountTestAddress(0)
	root := tree.root.link.Hash
	saved := disk[root]
	delete(disk, root)
	if _, _, err := cold.get(ctx, address); err == nil {
		t.Fatal("missing node treated as absence")
	}
	disk[root] = []byte(`{}`)
	if _, _, err := cold.get(ctx, address); err == nil {
		t.Fatal("corrupt node accepted")
	}
	disk[root] = saved
	updated, err := cold.set(ctx, Account{Address: address, Balance: "1000", Nonce: 1})
	if err != nil {
		t.Fatal(err)
	}
	staged := map[string][]byte{}
	if err := updated.stage(ctx, financialAccountStageMaxNodes, func(hash string, raw []byte) error { staged[hash] = raw; return nil }); err != nil {
		t.Fatal(err)
	}
	if len(staged) < 1 || len(staged) > financialAccountPathMax {
		t.Fatal("single-account update rewrote unrelated disk tree", len(staged))
	}
	for _, limit := range []int{0, 1, financialAccountStageMaxNodes + 1} {
		if err := tree.stage(ctx, limit, func(string, []byte) error { return nil }); err == nil {
			t.Fatal("stage bound ignored", limit)
		}
	}
	failed := errors.New("test storage write failed")
	if err := updated.stage(ctx, financialAccountStageMaxNodes, func(string, []byte) error { return failed }); !errors.Is(err, failed) {
		t.Fatal(err)
	}
	if _, err := tree.freeze(nil); err == nil {
		t.Fatal("nonempty cold graph without reader")
	}
	if value, _, err := cold.get(ctx, address); err != nil || value.Nonce != 0 {
		t.Fatal("failed/staged work modified old committed root", value, err)
	}
}

func TestFinancialAccountTreeCancellation(t *testing.T) {
	tree := financialAccountTestTree(t, 31)
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	address := financialAccountTestAddress(0)
	if next, err := tree.set(ctx, Account{Address: address, Balance: "1"}); !errors.Is(err, context.Canceled) || next.root.link != tree.root.link {
		t.Fatal(err)
	}
	if _, _, err := tree.get(ctx, address); !errors.Is(err, context.Canceled) {
		t.Fatal(err)
	}
	proof, err := tree.proof(context.Background(), address)
	if err != nil {
		t.Fatal(err)
	}
	if _, _, err := verifyFinancialAccountProof(ctx, proof, tree.root.link, tree.rules); !errors.Is(err, context.Canceled) {
		t.Fatal(err)
	}
	if err := tree.stage(ctx, 100, func(string, []byte) error { return nil }); !errors.Is(err, context.Canceled) {
		t.Fatal(err)
	}
	cold, disk := financialAccountTestDisk(t, tree)
	targetProof, err := cold.proof(context.Background(), financialAccountTestAddress(100))
	if err != nil {
		t.Fatal(err)
	}
	sourcePath := map[string]bool{}
	for _, node := range proof.Path {
		sourcePath[financialAccountDigest(node)] = true
	}
	targetOnly := ""
	for _, node := range targetProof.Path {
		hash := financialAccountDigest(node)
		if !sourcePath[hash] {
			targetOnly = hash
			break
		}
	}
	if targetOnly == "" {
		t.Fatal("fixture needs a separate recipient search branch")
	}
	active, abort := context.WithCancel(context.Background())
	hits := 0
	cold.read = func(hash string) (financialAccountNode, error) {
		if hash == targetOnly {
			hits++
			// The first read is recipient lookup. The second is recipient
			// update, after the new sender debit exists in the private tree.
			if hits == 2 {
				abort()
			}
		}
		var node financialAccountNode
		err := decodeStrict(disk[hash], &node)
		return node, err
	}
	next, _, err := cold.transfer(active, address, financialAccountTestAddress(100), 1, 0)
	if hits != 2 || !errors.Is(err, context.Canceled) || next.root.link != cold.root.link {
		t.Fatal("cancellation after private debit before recipient publication", hits, err)
	}
	active, abort = context.WithCancel(context.Background())
	if err := tree.stage(active, 100, func(string, []byte) error { abort(); return nil }); !errors.Is(err, context.Canceled) {
		t.Fatal("cancellation after final writer callback ignored", err)
	}
}
