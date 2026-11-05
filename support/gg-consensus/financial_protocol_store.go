//go:build !js

package main

// Protocol dictionaries/reward records join the same synchronous LevelDB batch
// as selected originals, account nodes, receipts and the authoritative head.
// Cold/archive replay reconstructs an independent disk index and rejects extra
// or missing records; it never repairs an unverified store.
import (
	"bytes"
	"context"
	"strings"
	"sync"

	"github.com/syndtr/goleveldb/leveldb"
	"github.com/syndtr/goleveldb/leveldb/opt"
)

const protocolRegistryPrefix = "pr/"
const protocolRewardPrefix = "er/"
const protocolRewardMaxWire = 16 * 1024 * 1024
const protocolRegistryCacheEntries = 512

func (store *financialStore) registryProof(ctx context.Context, state State, genesis Genesis, selector protocolRegistrySelector) (financialCertifiedRegistry, error) {
	if !publicFinancialProtocol(genesis) || !canonicalFinancialHex(selector.Key) {
		return financialCertifiedRegistry{}, errFinancialProtocol
	}
	if err := ctx.Err(); err != nil {
		return financialCertifiedRegistry{}, err
	}
	// Empty namespaces never invoke readProtocolNode. Reject NEW proof requests
	// at the owned store boundary too; callers here do not hold store.mu.
	if err := store.health(); err != nil {
		return financialCertifiedRegistry{}, err
	}
	select {
	case store.receiptSlots <- struct{}{}:
		defer func() { <-store.receiptSlots }()
	default:
		return financialCertifiedRegistry{}, errDagCandidateCredit
	}
	root, err := protocolRegistryRootFor(state, selector.Namespace)
	if err != nil {
		return financialCertifiedRegistry{}, err
	}
	rules, err := protocolRegistryRulesFor(genesis, state.GenesisHash, selector.Namespace)
	if err != nil {
		return financialCertifiedRegistry{}, err
	}
	tree, err := newProtocolRegistry(rules)
	if err != nil {
		return financialCertifiedRegistry{}, err
	}
	tree.root = protocolRegistryRef{link: root}
	tree.read = store.readProtocolNode
	path, err := tree.proof(ctx, selector.Key)
	if err != nil {
		return financialCertifiedRegistry{}, store.history.rejectRecord(ctx, err)
	}
	proof := financialCertifiedRegistry{GenesisHash: state.GenesisHash, Height: state.Height, Namespace: selector.Namespace, Proof: path, Schema: "gg.financial.registry-proof.v1", StateRoot: state.StateRoot}
	if _, _, err = checkFinancialCertifiedRegistry(ctx, proof, state, genesis, selector); err != nil {
		return financialCertifiedRegistry{}, store.history.rejectRecord(ctx, err)
	}
	return proof, nil
}

type protocolRegistryCache struct {
	mu      sync.Mutex
	entries map[string]protocolRegistryNode
	order   [protocolRegistryCacheEntries]string
	next    int
}

func (cache *protocolRegistryCache) get(hash string) (protocolRegistryNode, bool) {
	cache.mu.Lock()
	defer cache.mu.Unlock()
	node, ok := cache.entries[hash]
	node.Value = append([]byte(nil), node.Value...)
	return node, ok
}

func (cache *protocolRegistryCache) put(hash string, node protocolRegistryNode) {
	cache.mu.Lock()
	defer cache.mu.Unlock()
	if cache.entries == nil {
		cache.entries = map[string]protocolRegistryNode{}
	}
	if _, exists := cache.entries[hash]; exists {
		return
	}
	if len(cache.entries) == protocolRegistryCacheEntries {
		delete(cache.entries, cache.order[cache.next])
	}
	node.Value = append([]byte(nil), node.Value...)
	cache.entries[hash] = node
	cache.order[cache.next] = hash
	cache.next = (cache.next + 1) % protocolRegistryCacheEntries
}

func (cache *protocolRegistryCache) clear() {
	cache.mu.Lock()
	defer cache.mu.Unlock()
	cache.entries = nil
	cache.order = [protocolRegistryCacheEntries]string{}
	cache.next = 0
}

func protocolRulesIndex(genesis Genesis, anchor string) (map[string]protocolRegistryRules, error) {
	index := map[string]protocolRegistryRules{}
	if !publicFinancialProtocol(genesis) {
		return index, nil
	}
	for _, namespace := range []string{"producers", "roles", "epoch_work", "rewards", "operations"} {
		rules, err := protocolRegistryRulesFor(genesis, anchor, namespace)
		if err != nil {
			return nil, err
		}
		index[rules.hash()] = rules
	}
	return index, nil
}

func decodeStoredProtocolRegistry(hash string, raw []byte, index map[string]protocolRegistryRules) (protocolRegistryNode, error) {
	var node protocolRegistryNode
	if !canonicalFinancialHex(hash) || len(raw) == 0 || len(raw) > 2*16384+2048 || decodeStrict(raw, &node) != nil {
		return node, errProtocolRegistry
	}
	rules, known := index[node.Rules]
	if !known {
		return node, errProtocolRegistry
	}
	checkedRules, err := checkProtocolRegistryRules(rules)
	if err != nil {
		return node, err
	}
	checked, encoded, err := checkProtocolRegistryNodeValue(node, checkedRules)
	if err != nil || checked.link.Hash != hash || !bytes.Equal(raw, encoded) {
		return node, errProtocolRegistry
	}
	return checked.public(), nil
}

func validProtocolRewardReceipt(receipt protocolRewardReceipt, genesis Genesis, anchor string) bool {
	before, bok := economicAmount(receipt.BeforeIssued)
	next, nok := economicAmount(receipt.NextIssued)
	minted, mok := economicAmount(receipt.Minted)
	fees, fok := economicAmount(receipt.Fees)
	if !publicFinancialProtocol(genesis) || receipt.Schema != "gg.financial.reward-receipt.v1" || receipt.Genesis != anchor || !bok || !nok || !mok || !fok ||
		before > financialMaximumSupply(genesis) || minted > financialMaximumSupply(genesis)-before || next != before+minted || fees > before ||
		receipt.Epoch > receipt.ClosedThrough || receipt.Index == 0 || receipt.Index > 1<<32 || receipt.CreditsCount != len(receipt.Credits) ||
		len(receipt.Credits) > economicMaxRecipients || receipt.CreditsRoot != protocolCreditRoot(receipt.Credits) {
		return false
	}
	previous := ""
	total := uint64(0)
	for _, credit := range receipt.Credits {
		amount, ok := economicAmount(credit.Amount)
		if !ok || amount == 0 || !financialAccountAddress(credit.Address) || credit.Address <= previous || amount > next-total {
			return false
		}
		total += amount
		previous = credit.Address
	}
	rules, err := protocolRegistryRulesFor(genesis, anchor, "epoch_work")
	return err == nil && validProtocolRegistryLink(receipt.WorkRoot, rules, rules.hash()) && total == fees+minted
}

func stageFinancialProtocol(ctx context.Context, execution *financialDagExecution, save func(string, []byte) error) error {
	if !execution.source.hasProtocol() {
		return nil
	}
	protocol := execution.money.Protocol
	if protocol == nil {
		return errFinancialProtocol
	}
	for _, tree := range []protocolRegistryTree{protocol.producers, protocol.roles, protocol.work, protocol.rewards, protocol.operations} {
		if err := tree.stage(ctx, func(hash string, raw []byte) error { return save(protocolRegistryPrefix+hash, raw) }); err != nil {
			return err
		}
	}
	for identifier, receipt := range protocol.pendingRewards {
		if err := ctx.Err(); err != nil {
			return err
		}
		raw := canonical(receipt)
		if len(raw) > protocolRewardMaxWire || identifier != protocolRewardReceiptID(receipt) || !validProtocolRewardReceipt(receipt, execution.genesis, execution.anchor) {
			return errFinancialProtocol
		}
		if err := save(protocolRewardPrefix+identifier, raw); err != nil {
			return err
		}
	}
	return nil
}

func freezeFinancialProtocol(execution *financialDagExecution, read func(string) (protocolRegistryNode, error)) error {
	if !execution.source.hasProtocol() {
		return nil
	}
	p := execution.money.Protocol
	if p == nil {
		return errFinancialProtocol
	}
	for _, tree := range []*protocolRegistryTree{&p.producers, &p.roles, &p.work, &p.rewards, &p.operations} {
		frozen, err := tree.freeze(read)
		if err != nil {
			return err
		}
		*tree = frozen
	}
	p.pendingRewards = map[string]protocolRewardReceipt{}
	return nil
}

func (store *financialStore) readProtocolNode(hash string) (protocolRegistryNode, error) {
	store.mu.Lock()
	if store.db == nil || store.failed || store.history.failed.Load() {
		store.mu.Unlock()
		return protocolRegistryNode{}, errProtocolRegistry
	}
	history := store.history
	store.readers.Add(1)
	store.mu.Unlock()
	defer store.readers.Done()
	if node, ok := store.protocolCache.get(hash); ok {
		return node, nil
	}
	raw, err := history.get(context.Background(), protocolRegistryPrefix+hash)
	var node protocolRegistryNode
	if err == nil {
		node, err = decodeStoredProtocolRegistry(hash, raw, store.protocolRules)
	}
	if err != nil {
		_ = history.rejectRecord(context.Background(), err)
		store.mu.Lock()
		store.failed = true
		store.mu.Unlock()
		return node, errProtocolRegistry
	}
	store.protocolCache.put(hash, node)
	return node, nil
}

func (store *financialStore) stageProtocol(ctx context.Context, execution *financialDagExecution, batch *leveldb.Batch) error {
	return stageFinancialProtocol(ctx, execution, func(key string, expected []byte) error {
		actual, err := store.history.get(ctx, key)
		if err == nil {
			if !bytes.Equal(actual, expected) {
				return store.history.rejectRecord(ctx, errFinancialProtocol)
			}
			return nil
		}
		if err != leveldb.ErrNotFound || batch == nil {
			return store.history.rejectRecord(ctx, errFinancialProtocol)
		}
		batch.Put([]byte(key), expected)
		return nil
	})
}

type financialProtocolScratch struct {
	base  *financialAccountScratch
	index map[string]protocolRegistryRules
	cache protocolRegistryCache
}

func newFinancialProtocolScratch(genesis Genesis, anchor string) (*financialProtocolScratch, error) {
	rules, err := financialAccountRulesFor(genesis, anchor)
	if err != nil {
		return nil, err
	}
	base, err := newFinancialAccountScratch(rules)
	if err != nil {
		return nil, err
	}
	index, err := protocolRulesIndex(genesis, anchor)
	if err != nil {
		_ = base.close()
		return nil, err
	}
	return &financialProtocolScratch{base: base, index: index}, nil
}

func (scratch *financialProtocolScratch) close() error {
	if scratch == nil || scratch.base == nil {
		return nil
	}
	scratch.cache.clear()
	return scratch.base.close()
}

func (scratch *financialProtocolScratch) read(hash string) (protocolRegistryNode, error) {
	if scratch.base == nil || scratch.base.db == nil {
		return protocolRegistryNode{}, errProtocolRegistry
	}
	if node, ok := scratch.cache.get(hash); ok {
		return node, nil
	}
	raw, err := scratch.base.db.Get([]byte(protocolRegistryPrefix+hash), nil)
	if err != nil {
		return protocolRegistryNode{}, errProtocolRegistry
	}
	node, err := decodeStoredProtocolRegistry(hash, raw, scratch.index)
	if err != nil {
		return node, err
	}
	scratch.cache.put(hash, node)
	return node, nil
}

func (scratch *financialProtocolScratch) stage(ctx context.Context, execution *financialDagExecution) error {
	if scratch.base == nil || scratch.base.db == nil {
		return errProtocolRegistry
	}
	batch := new(leveldb.Batch)
	err := stageFinancialProtocol(ctx, execution, func(key string, expected []byte) error {
		actual, err := scratch.base.db.Get([]byte(key), nil)
		if err == nil {
			if !bytes.Equal(actual, expected) {
				return errProtocolRegistry
			}
			return nil
		}
		if err != leveldb.ErrNotFound {
			return errProtocolRegistry
		}
		batch.Put([]byte(key), expected)
		return nil
	})
	if err != nil {
		return err
	}
	if err = ctx.Err(); err != nil {
		return err
	}
	return scratch.base.db.Write(batch, &opt.WriteOptions{Sync: false, NoWriteMerge: true})
}

func (scratch *financialProtocolScratch) counts(ctx context.Context) (uint64, uint64, error) {
	if scratch.base == nil || scratch.base.db == nil {
		return 0, 0, errProtocolRegistry
	}
	iter := scratch.base.db.NewIterator(nil, nil)
	defer iter.Release()
	nodes, rewards := uint64(0), uint64(0)
	for iter.Next() {
		if err := ctx.Err(); err != nil {
			return 0, 0, err
		}
		key := string(iter.Key())
		if strings.HasPrefix(key, protocolRegistryPrefix) && canonicalFinancialHex(strings.TrimPrefix(key, protocolRegistryPrefix)) {
			nodes++
		} else if strings.HasPrefix(key, protocolRewardPrefix) && canonicalFinancialHex(strings.TrimPrefix(key, protocolRewardPrefix)) {
			rewards++
		} else {
			return 0, 0, errProtocolRegistry
		}
	}
	if iter.Error() != nil {
		return 0, 0, errProtocolRegistry
	}
	return nodes, rewards, nil
}
