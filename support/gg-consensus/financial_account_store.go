//go:build !js

package main

// Account nodes share the selected-original journal's synchronous DB batch.
// Reads hold an independent lifetime lease, not the application/store mutex.
import (
	"bytes"
	"context"
	"os"
	"path/filepath"
	"strings"
	"sync"

	"github.com/syndtr/goleveldb/leveldb"
	"github.com/syndtr/goleveldb/leveldb/opt"
)

const financialAccountPrefix = "fa/"

// Conservative RETAINED-ALLOCATION accounting, not a claim about total Go RSS.
// The native 512MiB process limit is unchanged. Each store/scratch owns a cache.
// On native 64-bit targets reserve512 bytes per maximum map member (including
// growth/allocator slack),16 per ring string header, plus fixed headers. Charge
// 1024 per retained node/checked-node/rules object graph plus rounded string
// allocations separately, deliberately charging shared strings more than once.
// No unsafe.Sizeof, architecture-dependent wire value or external budget knob.
const financialAccountCacheNodes = 8192
const financialAccountCacheByteBudget uint64 = 16 << 20
const financialAccountCacheFixedBytes uint64 = financialAccountCacheNodes*(512+16) + 256

type financialAccountCachedNode struct {
	node   financialAccountNode
	charge uint64
}
type financialAccountCache struct {
	mu         sync.Mutex
	entries    map[string]financialAccountCachedNode
	order      [financialAccountCacheNodes]string
	next, tail int
	bytes      uint64 // variable charge; fixed map/ring reserve is added separately
}

func financialAccountCacheStringCharge(value string) uint64 {
	return 32 + ((uint64(len(value)) + 15) &^ uint64(15))
}
func financialAccountCacheNodeCharge(hash string, node financialAccountNode) uint64 {
	charge := uint64(1024)
	for _, value := range []string{hash, node.Account.Address, node.Account.Balance,
		node.Left.Hash, node.Left.Total, node.Right.Hash, node.Right.Total,
		node.Rules, node.Schema, node.Total, node.checked.link.Hash,
		node.checked.link.Total, node.checked.rules.value.Genesis,
		node.checked.rules.value.Schema, node.checked.rules.hash} {
		charge += financialAccountCacheStringCharge(value)
	}
	return charge
}
func ownFinancialAccountCacheNode(hash string, node financialAccountNode) (financialAccountNode, bool) {
	// Only already checked exact values may carry a witness into this cache.
	// Skipping cache insertion never changes the caller's validated DB result.
	checked := node.checked
	if checked == nil || checked.rules == nil || checked.link.Hash != hash ||
		!checked.matches(node, checked.link, checked.rules) {
		return financialAccountNode{}, false
	}
	node.checked = nil
	node.Account.Address = strings.Clone(node.Account.Address)
	node.Account.Balance = strings.Clone(node.Account.Balance)
	node.Left.Hash, node.Left.Total = strings.Clone(node.Left.Hash), strings.Clone(node.Left.Total)
	node.Right.Hash, node.Right.Total = strings.Clone(node.Right.Hash), strings.Clone(node.Right.Total)
	node.Rules, node.Schema, node.Total = strings.Clone(node.Rules), strings.Clone(node.Schema), strings.Clone(node.Total)
	rules := *checked.rules
	rules.value.Genesis, rules.value.Schema = strings.Clone(rules.value.Genesis), strings.Clone(rules.value.Schema)
	rules.hash = strings.Clone(rules.hash)
	link := checked.link
	link.Hash, link.Total = strings.Clone(link.Hash), strings.Clone(link.Total)
	owned := &checkedFinancialAccountNode{value: node, link: link, rules: &rules}
	return owned.public(), true
}
func (cache *financialAccountCache) get(hash string) (financialAccountNode, bool) {
	cache.mu.Lock()
	defer cache.mu.Unlock()
	entry, ok := cache.entries[hash]
	return entry.node, ok
}
func (cache *financialAccountCache) put(hash string, node financialAccountNode) {
	if node.checked == nil || node.checked.rules == nil {
		return
	}
	charge := financialAccountCacheNodeCharge(hash, node)
	if charge > financialAccountCacheByteBudget-financialAccountCacheFixedBytes {
		return
	}
	cache.mu.Lock()
	defer cache.mu.Unlock()
	if _, ok := cache.entries[hash]; ok {
		return
	}
	owned, ok := ownFinancialAccountCacheNode(hash, node)
	if !ok {
		return
	}
	if cache.entries == nil {
		cache.entries = make(map[string]financialAccountCachedNode, financialAccountCacheNodes)
	}
	// FIFO has no hit-side allocation and a fixed maximum ring. Evict before
	// admission; both constraints hold even if the byte budget fills first.
	for len(cache.entries) >= financialAccountCacheNodes || cache.bytes+charge > financialAccountCacheByteBudget-financialAccountCacheFixedBytes {
		victim := cache.order[cache.next]
		if entry, exists := cache.entries[victim]; exists {
			delete(cache.entries, victim)
			cache.bytes -= entry.charge
		}
		cache.order[cache.next] = ""
		cache.next = (cache.next + 1) % financialAccountCacheNodes
	}
	// Eviction and insertion advance separate FIFO positions: no O(N) scan
	// as the working set fills, and no hit-side age mutation/allocation.
	slot := cache.tail
	key := strings.Clone(hash)
	cache.entries[key] = financialAccountCachedNode{node: owned, charge: charge}
	cache.bytes += charge
	cache.order[slot] = key
	cache.tail = (slot + 1) % financialAccountCacheNodes
}
func (cache *financialAccountCache) clear() {
	cache.mu.Lock()
	defer cache.mu.Unlock()
	cache.entries = nil
	cache.order = [financialAccountCacheNodes]string{}
	cache.next, cache.tail, cache.bytes = 0, 0, 0
}
func decodeFinancialStoredAccount(hash string, raw []byte, rules financialAccountRules) (financialAccountNode, error) {
	if !canonicalFinancialHex(hash) {
		return financialAccountNode{}, errFinancialAccount
	}
	node, link, err := decodeOwnedFinancialAccountNode(raw, rules)
	if err != nil || link.Hash != hash {
		return node, errFinancialAccount
	}
	return node, nil
}
func stageFinancialAccounts(ctx context.Context, execution *financialDagExecution, save func(string, []byte) error) error {
	if !execution.source.hasGeneralAccounts() {
		return nil
	}
	if execution.money.Tree == nil {
		return errFinancialAccount
	}
	return execution.money.Tree.stage(ctx, financialAccountStageMaxNodes, func(hash string, raw []byte) error { return save(financialAccountPrefix+hash, raw) })
}
func freezeFinancialAccounts(execution *financialDagExecution, read func(string) (financialAccountNode, error)) error {
	if !execution.source.hasGeneralAccounts() {
		return nil
	}
	if execution.money.Tree == nil {
		return errFinancialAccount
	}
	tree, err := execution.money.Tree.freeze(read)
	if err != nil {
		return err
	}
	execution.money.Tree = &tree
	return nil
}
func (store *financialStore) readAccountNode(hash string) (financialAccountNode, error) {
	store.mu.Lock()
	if store.db == nil || store.failed || store.history.failed.Load() || !store.accountRules.valid() {
		store.mu.Unlock()
		return financialAccountNode{}, errFinancialAccount
	}
	history := store.history
	store.readers.Add(1)
	store.mu.Unlock()
	defer store.readers.Done()
	if node, ok := store.accountCache.get(hash); ok {
		return node, nil
	}
	raw, err := history.get(context.Background(), financialAccountPrefix+hash)
	var node financialAccountNode
	if err == nil {
		node, err = decodeFinancialStoredAccount(hash, raw, store.accountRules)
	}
	if err != nil {
		_ = history.rejectRecord(context.Background(), err)
		store.mu.Lock()
		store.failed = true
		store.mu.Unlock()
		return financialAccountNode{}, errFinancialAccount
	}
	store.accountCache.put(hash, node)
	return node, nil
}

// Caller owns store.mu, or is the exclusive cold replay before publication.
// A nil batch checks the exact independently rederived nodes without repairing.
func (store *financialStore) stageAccounts(ctx context.Context, execution *financialDagExecution, batch *leveldb.Batch) error {
	return stageFinancialAccounts(ctx, execution, func(key string, expected []byte) error {
		actual, err := store.history.get(ctx, key)
		if err == nil {
			if !bytes.Equal(actual, expected) {
				return store.history.rejectRecord(ctx, errFinancialAccount)
			}
			return nil
		}
		if err != leveldb.ErrNotFound || batch == nil {
			return store.history.rejectRecord(ctx, errFinancialAccount)
		}
		batch.Put([]byte(key), expected)
		return nil
	})
}
func (store *financialStore) accountProof(ctx context.Context, state State, genesis Genesis, address string) (financialCertifiedAccount, error) {
	if !generalFinancialAccounts(genesis) || state.AccountTree == nil || !financialAccountAddress(address) {
		return financialCertifiedAccount{}, errFinancialAccount
	}
	if err := ctx.Err(); err != nil {
		return financialCertifiedAccount{}, err
	}
	// An empty-tree absence needs no node/cache read. This is a proof entry,
	// not an already locked reader callback, so health safely owns store.mu.
	if err := store.health(); err != nil {
		return financialCertifiedAccount{}, err
	}
	select {
	case store.receiptSlots <- struct{}{}:
		defer func() { <-store.receiptSlots }()
	default:
		return financialCertifiedAccount{}, errDagCandidateCredit
	}
	rules, err := financialAccountRulesFor(genesis, state.GenesisHash)
	if err != nil {
		return financialCertifiedAccount{}, err
	}
	tree, err := newFinancialAccountTree(rules)
	if err != nil {
		return financialCertifiedAccount{}, err
	}
	tree.root = financialAccountRef{link: *state.AccountTree}
	tree.read = store.readAccountNode
	proof, err := tree.proof(ctx, address)
	if err != nil {
		return financialCertifiedAccount{}, store.history.rejectRecord(ctx, err)
	}
	packet := financialCertifiedAccount{GenesisHash: state.GenesisHash, Height: state.Height, Proof: proof, Schema: "gg.financial-dag.account-proof.v1", StateRoot: state.StateRoot}
	if _, _, err := checkFinancialCertifiedAccount(ctx, packet, state, genesis); err != nil {
		return financialCertifiedAccount{}, store.history.rejectRecord(ctx, err)
	}
	return packet, nil
}

// Cold verification and archive replay retain their independently reconstructed
// account index on private scratch disk, not the entire global tree in RAM.
type financialAccountScratch struct {
	db           *leveldb.DB
	rules        financialAccountRules
	root, parent string
	cache        financialAccountCache
}

func newFinancialAccountScratch(rules financialAccountRules) (*financialAccountScratch, error) {
	if !rules.valid() {
		return nil, errFinancialAccount
	}
	parent, err := filepath.Abs(os.TempDir())
	if err != nil {
		return nil, err
	}
	parent, err = filepath.EvalSymlinks(parent)
	if err != nil {
		return nil, err
	}
	root, err := os.MkdirTemp(parent, "gg-financial-accounts-")
	if err != nil {
		return nil, err
	}
	scratch := &financialAccountScratch{rules: rules, root: root, parent: parent}
	db, err := leveldb.OpenFile(filepath.Join(root, "index"), &opt.Options{ErrorIfExist: true, Strict: opt.StrictAll, Compression: opt.NoCompression, BlockCacheCapacity: 4 << 20, WriteBuffer: 4 << 20, OpenFilesCacheCapacity: 16})
	if err != nil {
		_ = scratch.close()
		return nil, err
	}
	scratch.db = db
	return scratch, nil
}
func (scratch *financialAccountScratch) read(hash string) (financialAccountNode, error) {
	if scratch.db == nil {
		return financialAccountNode{}, errFinancialAccount
	}
	if node, ok := scratch.cache.get(hash); ok {
		return node, nil
	}
	raw, err := scratch.db.Get([]byte(financialAccountPrefix+hash), nil)
	if err != nil {
		return financialAccountNode{}, errFinancialAccount
	}
	node, err := decodeFinancialStoredAccount(hash, raw, scratch.rules)
	if err != nil {
		return node, err
	}
	scratch.cache.put(hash, node)
	return node, nil
}
func (scratch *financialAccountScratch) stage(ctx context.Context, execution *financialDagExecution) error {
	if scratch.db == nil {
		return errFinancialAccount
	}
	batch := new(leveldb.Batch)
	err := stageFinancialAccounts(ctx, execution, func(key string, expected []byte) error {
		actual, err := scratch.db.Get([]byte(key), nil)
		if err == nil {
			if !bytes.Equal(actual, expected) {
				return errFinancialAccount
			}
			return nil
		}
		if err != leveldb.ErrNotFound {
			return errFinancialAccount
		}
		batch.Put([]byte(key), expected)
		return nil
	})
	if err != nil {
		return err
	}
	if err := ctx.Err(); err != nil {
		return err
	}
	if batch.Len() == 0 {
		return nil
	}
	return scratch.db.Write(batch, &opt.WriteOptions{Sync: false, NoWriteMerge: true})
}
func (scratch *financialAccountScratch) count(ctx context.Context) (uint64, error) {
	if scratch.db == nil {
		return 0, errFinancialAccount
	}
	iter := scratch.db.NewIterator(nil, nil)
	defer iter.Release()
	count := uint64(0)
	for iter.Next() {
		if err := ctx.Err(); err != nil {
			return 0, err
		}
		key := string(iter.Key())
		if !strings.HasPrefix(key, financialAccountPrefix) || !canonicalFinancialHex(strings.TrimPrefix(key, financialAccountPrefix)) || count == dagSegmentCounterMax {
			return 0, errFinancialAccount
		}
		count++
	}
	if iter.Error() != nil {
		return 0, errFinancialAccount
	}
	return count, nil
}
func (scratch *financialAccountScratch) close() error {
	var closeErr error
	if scratch.db != nil {
		closeErr = scratch.db.Close()
		scratch.db = nil
	}
	scratch.cache.clear()
	if scratch.root == "" {
		return closeErr
	}
	info, err := os.Lstat(scratch.root)
	if err != nil {
		if os.IsNotExist(err) {
			scratch.root = ""
			return closeErr
		}
		return err
	}
	absolute, err := filepath.Abs(scratch.root)
	if err != nil {
		return err
	}
	resolved, err := filepath.EvalSymlinks(absolute)
	if err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 || resolved != absolute || filepath.Dir(absolute) != scratch.parent || !strings.HasPrefix(filepath.Base(absolute), "gg-financial-accounts-") {
		return errFinancialAccount
	}
	if err := os.RemoveAll(absolute); err != nil {
		return err
	}
	scratch.root = ""
	return closeErr
}
