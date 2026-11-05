//go:build !js

package main

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"math/rand"
	"strings"
	"testing"
)

func capacityRegistryRules(namespace string) protocolRegistryRules {
	return protocolRegistryRules{Genesis: strings.Repeat("a", 64), MaxEntries: 8192,
		MaxValueBytes: 2048, Namespace: namespace, Schema: "gg.protocol.registry-rules.v1"}
}
func capacityRegistryTree(t *testing.T, count int) protocolRegistryTree {
	t.Helper()
	tree, err := newProtocolRegistry(capacityRegistryRules("roles"))
	if err != nil {
		t.Fatal(err)
	}
	for index := 0; index < count; index++ {
		tree, err = tree.set(context.Background(), fmt.Sprintf("%064x", index+1), []byte(fmt.Sprintf("value:%d", index)))
		if err != nil {
			t.Fatal(err)
		}
	}
	return tree
}
func compareCapacityRegistryBytes(t *testing.T, tree protocolRegistryTree, old capacityReferenceRegistryTree) {
	t.Helper()
	if !bytes.Equal(canonical(tree.root.link), canonical(old.root.link)) {
		t.Fatal("prechange root/topology changed", tree.root.link, old.root.link)
	}
	actual, expected := map[string][]byte{}, map[string][]byte{}
	if err := tree.stage(context.Background(), func(hash string, raw []byte) error { actual[hash] = append([]byte(nil), raw...); return nil }); err != nil {
		t.Fatal(err)
	}
	if err := old.stage(context.Background(), func(hash string, raw []byte) error { expected[hash] = append([]byte(nil), raw...); return nil }); err != nil {
		t.Fatal(err)
	}
	if len(actual) != len(expected) {
		t.Fatal("staged membership changed")
	}
	for hash, raw := range expected {
		if !bytes.Equal(actual[hash], raw) {
			t.Fatal("canonical staged bytes changed", hash)
		}
	}
}

func TestOwnedRegistryEveryNamespaceKeepsPrechangeAVLRootsAndProofBytes(t *testing.T) {
	ctx := context.Background()
	for _, namespace := range []string{"producers", "roles", "epoch_work", "membership", "rewards", "operations"} {
		t.Run(namespace, func(t *testing.T) {
			rules := capacityRegistryRules(namespace)
			tree, err := newProtocolRegistry(rules)
			if err != nil {
				t.Fatal(err)
			}
			oldRules := capacityReferenceRegistryRules{Genesis: rules.Genesis, MaxEntries: rules.MaxEntries,
				MaxValueBytes: rules.MaxValueBytes, Namespace: rules.Namespace, Schema: rules.Schema}
			old, err := newCapacityReferenceRegistry(oldRules)
			if err != nil {
				t.Fatal(err)
			}
			order := []int{}
			for index := 1; index <= 63; index++ {
				order = append(order, index)
			}
			for lo, hi := 1, 63; lo <= hi; lo, hi = lo+1, hi-1 {
				order = append(order, hi, lo)
			}
			rng := rand.New(rand.NewSource(74019))
			for index := 0; index < 63; index++ {
				order = append(order, 1+rng.Intn(63))
			}
			for step, index := range order {
				key := fmt.Sprintf("%064x", index)
				value := []byte(fmt.Sprintf("%s:revision:%d", namespace, step))
				before, oldBefore := tree, old
				tree, err = tree.set(ctx, key, value)
				if err != nil {
					t.Fatal(step, err)
				}
				old, err = old.set(ctx, key, value)
				if err != nil {
					t.Fatal(step, err)
				}
				compareCapacityRegistryBytes(t, tree, old)
				compareCapacityRegistryBytes(t, before, oldBefore)
			}
			for _, index := range []int{0, 1, 2, 17, 31, 63, 64} {
				key := fmt.Sprintf("%064x", index)
				actual, err := tree.proof(ctx, key)
				if err != nil {
					t.Fatal(err)
				}
				expected, err := old.proof(ctx, key)
				if err != nil {
					t.Fatal(err)
				}
				if !bytes.Equal(canonical(actual), canonical(expected)) {
					t.Fatal("wire proof changed", index)
				}
				a, ae, err := verifyProtocolRegistryProof(ctx, actual, tree.root.link, rules, key)
				if err != nil {
					t.Fatal(err)
				}
				b, be, err := verifyCapacityReferenceRegistryProof(ctx, expected, old.root.link, oldRules, key)
				if err != nil || ae != be || !bytes.Equal(a, b) {
					t.Fatal("proof semantics changed", index, err)
				}
			}
		})
	}
}

func TestOwnedRegistryValueCopiesCannotMutateTreesCacheOrProofAuthority(t *testing.T) {
	ctx := context.Background()
	tree := capacityRegistryTree(t, 7)
	key := tree.root.node.public.Key
	original, exists, err := tree.get(ctx, key)
	if err != nil || !exists {
		t.Fatal(err)
	}
	before := canonical(tree.root.link)
	loaded, _, _, err := tree.load(ctx, tree.root, "", "")
	if err != nil {
		t.Fatal(err)
	}
	loaded.Value[0] ^= 1
	loaded.Key = strings.Repeat("f", 64)
	after, exists, err := tree.get(ctx, key)
	if err != nil || !exists || !bytes.Equal(original, after) || !bytes.Equal(before, canonical(tree.root.link)) {
		t.Fatal("load exposed mutable private node", err)
	}
	input := []byte("owned original")
	changed, err := tree.set(ctx, key, input)
	if err != nil {
		t.Fatal(err)
	}
	input[0] ^= 1
	value, _, err := changed.get(ctx, key)
	if err != nil || string(value) != "owned original" {
		t.Fatal("set retained caller Value alias", err)
	}
	node, err := decodeProtocolRegistryNode(canonical(tree.root.node.public), tree.root.link, tree.rules)
	if err != nil || node.checked == nil {
		t.Fatal(err)
	}
	var cache protocolRegistryCache
	cache.put(tree.root.link.Hash, node)
	node.Value[0] ^= 1
	retained, ok := cache.get(tree.root.link.Hash)
	if !ok || !bytes.Equal(retained.Value, original) {
		t.Fatal("cache put retained caller Value alias")
	}
	retained.Value[0] ^= 1
	retained, ok = cache.get(tree.root.link.Hash)
	if !ok || !bytes.Equal(retained.Value, original) {
		t.Fatal("cache get exposed retained Value alias")
	}
	proof, err := tree.proof(ctx, key)
	if err != nil {
		t.Fatal(err)
	}
	proof.Path[0].Value[0] ^= 1
	if _, _, err := verifyProtocolRegistryProof(ctx, proof, tree.root.link, tree.rules, key); err == nil {
		t.Fatal("carried private witness blessed forged public proof")
	}
	after, _, err = tree.get(ctx, key)
	if err != nil || !bytes.Equal(original, after) {
		t.Fatal("proof retained tree Value alias", err)
	}
	cache.clear()
	if cache.entries != nil || cache.order != [protocolRegistryCacheEntries]string{} {
		t.Fatal("cache clear retained witness/payload")
	}
}

func TestOwnedRegistryRejectsChangedParentRulesBoundsAndOrdinaryReaderForgery(t *testing.T) {
	ctx := context.Background()
	tree := capacityRegistryTree(t, 7)
	raw := canonical(tree.root.node.public)
	decoded, err := decodeProtocolRegistryNode(raw, tree.root.link, tree.rules)
	if err != nil {
		t.Fatal(err)
	}
	for name, change := range map[string]func(*protocolRegistryLink){
		"hash":   func(link *protocolRegistryLink) { link.Hash = strings.Repeat("f", 64) },
		"height": func(link *protocolRegistryLink) { link.Height++ },
		"count":  func(link *protocolRegistryLink) { link.Count++ },
	} {
		t.Run(name, func(t *testing.T) {
			ref := tree.root
			change(&ref.link)
			if _, _, _, err := tree.load(ctx, ref, "", ""); err == nil {
				t.Fatal("unchecked parent link")
			}
		})
	}
	for _, bounds := range [][2]string{{decoded.Key, ""}, {"", decoded.Key}} {
		if _, _, _, err := tree.load(ctx, tree.root, bounds[0], bounds[1]); err == nil {
			t.Fatal("owned witness skipped search bound")
		}
	}
	for name, mutate := range map[string]func(*protocolRegistryRules){
		"namespace":   func(r *protocolRegistryRules) { r.Namespace = "producers" },
		"genesis":     func(r *protocolRegistryRules) { r.Genesis = strings.Repeat("b", 64) },
		"entries":     func(r *protocolRegistryRules) { r.MaxEntries++ },
		"value_limit": func(r *protocolRegistryRules) { r.MaxValueBytes++ },
	} {
		t.Run(name, func(t *testing.T) {
			bad := tree
			mutate(&bad.rules)
			if _, _, _, err := bad.load(ctx, bad.root, "", ""); err == nil {
				t.Fatal("changed rules retained witness authority")
			}
		})
	}
	other, err := newProtocolRegistry(capacityRegistryRules("operations"))
	if err != nil {
		t.Fatal(err)
	}
	other.root = tree.root
	if _, _, _, err := other.load(ctx, other.root, "", ""); err == nil {
		t.Fatal("new valid namespace accepted old checked node")
	}
	forged := decoded
	forged.Value = append([]byte(nil), decoded.Value...)
	forged.Value[0] ^= 1
	for _, carry := range []bool{false, true} {
		candidate := forged
		if !carry {
			candidate.checked = nil
		}
		cold, err := tree.freeze(func(string) (protocolRegistryNode, error) { return candidate, nil })
		if err != nil {
			t.Fatal(err)
		}
		if _, _, _, err := cold.load(ctx, cold.root, "", ""); err == nil {
			t.Fatal("ordinary/certified callback forgery accepted", carry)
		}
	}
	private := *tree.root.node
	private.left.link.Hash = strings.Repeat("f", 64)
	ref := tree.root
	ref.node = &private
	if _, _, _, err := tree.load(ctx, ref, "", ""); err == nil {
		t.Fatal("child ref/body mismatch accepted")
	}
}

func TestOwnedRegistryStrictDecodeCancellationAndErrorsRemainObservable(t *testing.T) {
	ctx := context.Background()
	tree := capacityRegistryTree(t, 7)
	raw := canonical(tree.root.node.public)
	rulesIndex := map[string]protocolRegistryRules{tree.rulesHash: tree.rules}
	for name, candidate := range map[string][]byte{
		"space":        append([]byte(" "), raw...),
		"private_flag": append(append([]byte(nil), raw[:len(raw)-1]...), []byte(`,"checked":true}`)...),
		"corrupt":      []byte(`{}`),
		"huge":         make([]byte, 2*16384+2049),
	} {
		t.Run(name, func(t *testing.T) {
			if _, err := decodeStoredProtocolRegistry(tree.root.link.Hash, candidate, rulesIndex); err == nil {
				t.Fatal("strict cold decode bypassed")
			}
		})
	}
	if _, err := decodeStoredProtocolRegistry(strings.Repeat("f", 64), raw, rulesIndex); err == nil {
		t.Fatal("cold body/hash mismatch accepted")
	}
	if _, err := decodeStoredProtocolRegistry(tree.root.link.Hash, raw, map[string]protocolRegistryRules{}); err == nil {
		t.Fatal("unknown namespace rules accepted")
	}
	cancelled, cancel := context.WithCancel(ctx)
	cancel()
	if _, _, _, err := tree.load(cancelled, tree.root, "", ""); !errors.Is(err, context.Canceled) {
		t.Fatal(err)
	}
	if _, _, err := tree.get(cancelled, tree.root.node.public.Key); !errors.Is(err, context.Canceled) {
		t.Fatal(err)
	}
	if _, err := tree.set(cancelled, tree.root.node.public.Key, []byte("new")); !errors.Is(err, context.Canceled) {
		t.Fatal(err)
	}
	empty, err := newProtocolRegistry(tree.rules)
	if err != nil {
		t.Fatal(err)
	}
	if _, _, err := empty.get(cancelled, tree.root.node.public.Key); !errors.Is(err, context.Canceled) {
		t.Fatal("empty fast path swallowed cancel", err)
	}
	sentinel := errors.New("owned read failure")
	cold, err := tree.freeze(func(string) (protocolRegistryNode, error) { return protocolRegistryNode{}, sentinel })
	if err != nil {
		t.Fatal(err)
	}
	if _, _, err := cold.get(ctx, tree.root.node.public.Key); !errors.Is(err, sentinel) {
		t.Fatal("read error became success", err)
	}
	if err := tree.stage(ctx, func(string, []byte) error { return sentinel }); !errors.Is(err, sentinel) {
		t.Fatal("save error became success", err)
	}
}

func TestOwnedRegistryDynamicRoleRootChangesDoNotReuseEarlierAbsence(t *testing.T) {
	ctx := context.Background()
	model, _, _ := publicProtocolFixture(t)
	address := model.genesis.FinancialAccounts.Allocations[0].Address
	before := model.money.Protocol
	reserved, err := protocolAccountIsReserved(ctx, before, address)
	if err != nil || reserved {
		t.Fatal("payer fixture role", err)
	}
	changed := before.clone()
	changed.roles, err = changed.roles.set(ctx, address, canonical(protocolReservedRole{Owner: address, Role: "PRODUCER", Schema: "gg.financial.reserved-role.v1"}))
	if err != nil {
		t.Fatal(err)
	}
	reserved, err = protocolAccountIsReserved(ctx, changed, address)
	if err != nil || !reserved {
		t.Fatal("changed immutable root reused earlier absence", err)
	}
	reserved, err = protocolAccountIsReserved(ctx, before, address)
	if err != nil || reserved {
		t.Fatal("new role mutated old root", err)
	}
	changed.roles, err = changed.roles.set(ctx, address, canonical(protocolReservedRole{Owner: address, Role: "GOVERNANCE", Schema: "gg.financial.reserved-role.v1"}))
	if err != nil {
		t.Fatal(err)
	}
	reserved, err = protocolAccountIsReserved(ctx, changed, address)
	if err != nil || reserved {
		t.Fatal("changed role value reused earlier reserved result", err)
	}
}
