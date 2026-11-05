//go:build !js

package main

import (
	"bytes"
	"context"
	"path/filepath"
	"testing"

	"github.com/syndtr/goleveldb/leveldb"
	"github.com/syndtr/goleveldb/leveldb/opt"
)

func TestCapacityAccountCacheKeeps5008WorkingNodesAndExactProofBytes(t *testing.T) {
	ctx := context.Background()
	tree := financialAccountTestTree(t, 5008)
	nodes := map[string]financialAccountNode{}
	var cache financialAccountCache
	if err := tree.stage(ctx, financialAccountStageMaxNodes, func(hash string, raw []byte) error {
		node, err := decodeFinancialStoredAccount(hash, raw, tree.rules)
		if err != nil {
			return err
		}
		nodes[hash] = node
		cache.put(hash, node)
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	if len(nodes) != 5008 || len(cache.entries) != len(nodes) {
		t.Fatal("configured cache cannot retain representative current working set", len(nodes), len(cache.entries))
	}
	if cache.bytes+financialAccountCacheFixedBytes > financialAccountCacheByteBudget || len(cache.entries) > financialAccountCacheNodes {
		t.Fatal("working-set cache exceeds a bound")
	}
	cold, err := tree.freeze(func(hash string) (financialAccountNode, error) {
		node, ok := cache.get(hash)
		if !ok {
			t.Fatal("unexpected working-set miss", hash)
		}
		return node, nil
	})
	if err != nil {
		t.Fatal(err)
	}
	for _, index := range []int{0, 1, 127, 2504, 5007, 9999} {
		address := financialAccountTestAddress(index)
		expected, err := tree.proof(ctx, address)
		if err != nil {
			t.Fatal(err)
		}
		actual, err := cold.proof(ctx, address)
		if err != nil || !bytes.Equal(canonical(expected), canonical(actual)) {
			t.Fatal("cache changed authenticated proof bytes", index, err)
		}
	}
	// Retained witnesses must not alias the caller's private checked record.
	original := nodes[tree.root.link.Hash]
	original.checked.value.Account.Nonce++
	retained, ok := cache.get(tree.root.link.Hash)
	if !ok || !retained.checked.matches(retained, tree.root.link, cold.checked) {
		t.Fatal("cache retained a mutable caller witness alias")
	}
	cache.clear()
	if cache.entries != nil || cache.bytes != 0 || cache.order != [financialAccountCacheNodes]string{} {
		t.Fatal("clear retained node/witness/string references")
	}
}

func TestCapacityAccountCacheBudgetEvictionNeverAcceptsUncertifiedNodes(t *testing.T) {
	tree := financialAccountTestTree(t, 1)
	node := *tree.root.node
	var cache financialAccountCache
	first, last := "", ""
	for index := 0; index < financialAccountCacheNodes+1000; index++ {
		node.Account.Nonce = uint64(index)
		checked, _, err := checkFinancialAccountNodeValue(node, tree.checked)
		if err != nil {
			t.Fatal(err)
		}
		hash := checked.link.Hash
		if first == "" {
			first = hash
		}
		last = hash
		cache.put(hash, checked.public())
		if cache.bytes+financialAccountCacheFixedBytes > financialAccountCacheByteBudget || len(cache.entries) > financialAccountCacheNodes {
			t.Fatal("admission exceeded byte/entry budget", index, cache.bytes, len(cache.entries))
		}
	}
	if _, ok := cache.get(first); ok {
		t.Fatal("unbounded history retention")
	}
	if _, ok := cache.get(last); !ok {
		t.Fatal("newest admissible record missing")
	}
	before := cache.bytes
	uncertified := node
	uncertified.checked = nil
	cache.put(tree.root.link.Hash, uncertified)
	if cache.bytes != before {
		t.Fatal("unverified public value acquired cache authority")
	}
	forged := *tree.root.node
	forged.Account.Nonce++
	cache.put(tree.root.link.Hash, forged)
	if cache.bytes != before {
		t.Fatal("modified value reused a checked handle")
	}
}

func TestCapacityWarmCachesCloseThenColdCorruptionStillRejects(t *testing.T) {
	for _, kind := range []string{"account", "registry"} {
		t.Run(kind, func(t *testing.T) {
			app, backend, _, _, root := publicProtocolSDKFixture(t)
			accountHash := app.state.AccountTree.Hash
			registryHash := app.state.Protocol.RoleRoot.Hash
			if _, err := backend.store.readAccountNode(accountHash); err != nil {
				t.Fatal(err)
			}
			if _, err := backend.store.readProtocolNode(registryHash); err != nil {
				t.Fatal(err)
			}
			if len(backend.store.accountCache.entries) == 0 || len(backend.store.protocolCache.entries) == 0 {
				t.Fatal("fixture never warmed caches")
			}
			if err := app.Close(); err != nil {
				t.Fatal(err)
			}
			if backend.store.accountCache.entries != nil || backend.store.protocolCache.entries != nil {
				t.Fatal("closed store retained cache records")
			}
			if _, err := backend.store.readAccountNode(accountHash); err == nil {
				t.Fatal("closed account cache bypassed store lease")
			}
			if _, err := backend.store.readProtocolNode(registryHash); err == nil {
				t.Fatal("closed registry cache bypassed store lease")
			}
			db, err := leveldb.OpenFile(filepath.Join(root, "gg-financial-dag.leveldb"), &opt.Options{ErrorIfMissing: true, Strict: opt.StrictAll})
			if err != nil {
				t.Fatal(err)
			}
			key := financialAccountPrefix + accountHash
			if kind == "registry" {
				key = protocolRegistryPrefix + registryHash
			}
			writeErr := db.Put([]byte(key), []byte(`{}`), &opt.WriteOptions{Sync: true})
			closeErr := db.Close()
			if writeErr != nil || closeErr != nil {
				t.Fatal(writeErr, closeErr)
			}
			reopened, err := newDagEnabledLedger(app.genesis, app.anchor, root, false)
			if err == nil {
				_ = reopened.Close()
				t.Fatal("warm records masked actual cold disk corruption")
			}
		})
	}
}
