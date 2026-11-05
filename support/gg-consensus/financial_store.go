//go:build !js

package main

// A separate, explicit v5 store. All selected SDK heights (including empty
// ones), original signed financial batches and cuts survive in one journal.
// There is no snapshot-only recovery, history pruning, permissive DB repair,
// or legacy protocol migration. Exact logical history may be repacked only
// after full semantic replay. Original candidates sync before a proposal vote;
// journal + head select atomically. Replay retains only the bounded active DAG.
import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"github.com/syndtr/goleveldb/leveldb"
	"github.com/syndtr/goleveldb/leveldb/opt"
	"math/bits"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
)

var errFinancialStore = errors.New("GG_FINANCIAL_STORE_UNAVAILABLE")

const financialCandidateLimit = 2
const financialJournalMaxWire = financialDagMaxBatchWire + 8192
const financialStoreHeadMaxWire = dagArchiveHeaderLimit + 65536

type financialJournalEntry struct {
	After       string          `json:"after"`
	Height      int64           `json:"height"`
	Previous    string          `json:"previous"`
	Schema      string          `json:"schema"`
	TimeNs      string          `json:"time_ns"`
	Transaction json.RawMessage `json:"transaction"`
}

type financialStoreHead struct {
	Anchor   string                  `json:"anchor"`
	Journal  string                  `json:"journal"`
	Schema   string                  `json:"schema"`
	Source   string                  `json:"source"`
	State    State                   `json:"state"`
	TimeNs   string                  `json:"time_ns"`
	Recovery *financialStoreRecovery `json:"recovery,omitempty"`
}

// Recovery is local application-store bookkeeping, never a consensus proof or
// private validator signing state. Incomplete stores cannot start normally.
type financialStoreRecovery struct {
	Archive     string                 `json:"archive_sha256"`
	Block       string                 `json:"certificate_block"`
	Height      int64                  `json:"certificate_height"`
	Complete    bool                   `json:"complete"`
	Certificate *dagArchiveCertificate `json:"certificate"`
	SDKCommit   json.RawMessage        `json:"sdk_commit,omitempty"`
}

func validFinancialStoreRecovery(head financialStoreHead, genesis Genesis, anchor string, allowIncomplete bool) bool {
	if head.Schema == "gg.financial-dag.store.v1" {
		return head.Recovery == nil
	}
	r := head.Recovery
	if !(head.Schema == "gg.financial-dag.store.v2" && r != nil && r.Certificate != nil && pubPattern.MatchString(r.Archive) &&
		pubPattern.MatchString(r.Block) && r.Height > 0 && r.Height <= int64(dagSegmentCounterMax) &&
		(allowIncomplete || r.Complete) && ((!r.Complete && head.State.Height < r.Height) || (r.Complete && head.State.Height >= r.Height-1))) {
		return false
	}
	if len(r.SDKCommit) > financialSDKCommitMaxWire || len(r.SDKCommit) > 0 && !r.Complete {
		return false
	}
	certificate, block, err := checkedFinancialArchiveCertificate(*r.Certificate, financialArchiveCommand{Genesis: genesis, GenesisHash: anchor})
	return err == nil && block == r.Block && certificate.State.Height == r.Height-1
}

type financialStore struct {
	history         *financialHistory
	verifiedThrough int64
	recoverySDK     *financialSDKRecovery // owned full replay only; never decoded from disk
	mu              sync.Mutex
	closeMu         sync.Mutex
	readers         sync.WaitGroup
	receiptSlots    chan struct{}
	tree            dagClosedSegments
	producerViews   []financialProducerView
	lineageCache    dagMetadataCache
	accountCache    financialAccountCache
	accountRules    financialAccountRules
	protocolRules   map[string]protocolRegistryRules
	protocolCache   protocolRegistryCache
	execution       *financialDagExecution
	db              *leveldb.DB
	head            financialStoreHead
	timeNs          int64
	failed          bool
	candidates      map[string]int
	write           func(*leveldb.Batch) error // owned fault injection wraps synchronous IO
}

func (store *financialStore) health() error {
	store.mu.Lock()
	defer store.mu.Unlock()
	if store.db == nil || store.failed || store.history.failed.Load() {
		return errFinancialStore
	}
	return nil
}

func (store *financialStore) syncWrite(batch *leveldb.Batch) error {
	if store.db == nil || store.failed || store.history.failed.Load() {
		return errFinancialStore
	}
	nextActive, err := store.history.trackBatch(batch)
	if err != nil {
		store.failed = true
		return err
	}
	if store.write(batch) != nil {
		store.failed = true
		return errFinancialStore
	}
	if store.history.failed.Load() {
		store.failed = true
		return errFinancialHistory
	}
	store.history.activeBytes = nextActive
	store.history.hasHead = true
	return nil
}

func (store *financialStore) close() error {
	store.closeMu.Lock()
	defer store.closeMu.Unlock()
	store.mu.Lock()
	if store.db == nil {
		store.mu.Unlock()
		return nil
	}
	db := store.db
	store.db = nil
	store.mu.Unlock()
	store.readers.Wait()
	store.lineageCache.clear()
	store.accountCache.clear()
	store.protocolCache.clear()
	return db.Close()
}

func financialJournalHash(raw []byte) string {
	return hashHex(append([]byte(financialDomain+"JOURNAL\x00"), raw...))
}

func openFinancialStore(ctx context.Context, genesis Genesis, anchor, root string, create bool) (*financialStore, []State, *financialDagExecution, error) {
	return openFinancialStoreMode(ctx, genesis, anchor, root, create, false)
}

func openFinancialStoreMode(ctx context.Context, genesis Genesis, anchor, root string, create, allowIncomplete bool) (*financialStore, []State, *financialDagExecution, error) {
	return openFinancialStoreModeFault(ctx, genesis, anchor, root, create, allowIncomplete, nil)
}

// Native owned fault seam, never enabled by persisted JSON or commands.
func openFinancialStoreModeFault(ctx context.Context, genesis Genesis, anchor, root string, create, allowIncomplete bool, fault func(string) error) (opened *financialStore, snapshots []State, ready *financialDagExecution, failure error) {
	if ctx.Err() != nil {
		return nil, nil, nil, ctx.Err()
	}
	if validateGenesis(genesis, anchor) != nil || genesis.FinancialDAG == nil || !filepath.IsAbs(root) || !realArchiveDirectory(root) {
		return nil, nil, nil, errFinancialStore
	}
	resolved, err := filepath.EvalSymlinks(root)
	if err != nil {
		return nil, nil, nil, errFinancialStore
	}
	for _, name := range []string{"gg-public-state.json", "gg-dag-public.leveldb", "gg-dag-segmented.leveldb"} {
		if _, err := os.Lstat(filepath.Join(resolved, name)); !os.IsNotExist(err) {
			return nil, nil, nil, errFinancialStore
		}
	}
	path := filepath.Join(resolved, "gg-financial-dag.leveldb")
	if info, err := os.Lstat(path); err == nil {
		if create || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
			return nil, nil, nil, errFinancialStore
		}
	} else if !os.IsNotExist(err) || !create {
		return nil, nil, nil, errFinancialStore
	}
	db, err := leveldb.OpenFile(path, &opt.Options{ErrorIfExist: create, ErrorIfMissing: !create, Strict: opt.StrictAll,
		Compression: opt.NoCompression, WriteBuffer: 4 * 1024 * 1024, BlockCacheCapacity: 4 * 1024 * 1024, OpenFilesCacheCapacity: 32})
	if err != nil {
		return nil, nil, nil, errFinancialStore
	}
	valid := false
	defer func() {
		if !valid {
			_ = db.Close()
		}
	}()
	execution, err := newFinancialDagExecution(genesis, anchor, *genesis.FinancialDAG)
	if err != nil {
		return nil, nil, nil, err
	}
	state := initialState(execution.genesis, anchor)
	history := []State{state}
	store := &financialStore{db: db, timeNs: execution.timeNs, candidates: map[string]int{}, receiptSlots: make(chan struct{}, 2)}
	store.protocolRules, err = protocolRulesIndex(genesis, anchor)
	if err != nil {
		return nil, nil, nil, err
	}
	if execution.source.hasGeneralAccounts() {
		store.accountRules, err = financialAccountRulesFor(genesis, anchor)
		if err != nil {
			return nil, nil, nil, err
		}
	}
	freezeFinancialLineage(execution, store.readLineageNode)
	store.producerViews, err = financialProducerViews(nil, execution)
	if err != nil {
		return nil, nil, nil, err
	}
	store.head = financialStoreHead{Anchor: anchor, Journal: DagZero, Schema: "gg.financial-dag.store.v1", Source: execution.source.hash(), State: state, TimeNs: strconv.FormatInt(store.timeNs, 10)}
	store.write = func(batch *leveldb.Batch) error {
		return db.Write(batch, &opt.WriteOptions{Sync: true, NoWriteMerge: true})
	}
	if create {
		store.history, err = openFinancialHistory(ctx, db, resolved, anchor, execution.source.hash(), true)
		if err != nil {
			return nil, nil, nil, err
		}
		store.history.fault = fault
		store.history.syncWrite = func(batch *leveldb.Batch) error { return store.write(batch) }
		batch := new(leveldb.Batch)
		if err = store.stageAccounts(ctx, execution, batch); err != nil {
			return nil, nil, nil, err
		}
		if err = store.stageProtocol(ctx, execution, batch); err != nil {
			return nil, nil, nil, err
		}
		batch.Put([]byte("head"), canonical(store.head))
		if ctx.Err() != nil {
			return nil, nil, nil, ctx.Err()
		}
		if store.syncWrite(batch) != nil {
			return nil, nil, nil, errFinancialStore
		}
		if err = freezeFinancialAccounts(execution, store.readAccountNode); err != nil {
			return nil, nil, nil, err
		}
		if err = freezeFinancialProtocol(execution, store.readProtocolNode); err != nil {
			return nil, nil, nil, err
		}
		if execution.source.hasProtocol() {
			store.execution = execution.clone()
		}
		if err = store.history.initialize(ctx); err != nil {
			return nil, nil, nil, err
		}
		valid = true
		return store, history, execution, nil
	}
	raw, err := db.Get([]byte("head"), nil)
	var saved financialStoreHead
	if err != nil || len(raw) > financialStoreHeadMaxWire || decodeStrict(raw, &saved) != nil || !bytes.Equal(raw, canonical(saved)) ||
		!validFinancialStoreRecovery(saved, genesis, anchor, allowIncomplete) || saved.Anchor != anchor || saved.Source != store.head.Source ||
		!pubPattern.MatchString(saved.Journal) || validateState(saved.State, execution.genesis, anchor) != nil {
		return nil, nil, nil, errFinancialStore
	}
	store.history, err = openFinancialHistory(ctx, db, resolved, anchor, execution.source.hash(), true)
	if err != nil {
		return nil, nil, nil, err
	}
	store.history.fault = fault
	store.history.syncWrite = func(batch *leveldb.Batch) error { return store.write(batch) }
	store.history.retainedThrough.Store(saved.State.Height)
	// Strict inventory catches missing, extra and nonconsecutive selected entries
	// before replay. Candidate leftovers are bounded and never selected by startup.
	iter := store.history.iterator(ctx)
	count, heads := int64(0), 0
	receipts, nodes, lineageNodes, accountNodes := uint64(0), uint64(0), uint64(0), uint64(0)
	blockOrderRows := uint64(0)
	protocolNodes, protocolRewards := uint64(0), uint64(0)
	committeeStates := uint64(0)
	headers, expectedHeaders := int64(0), int64(0)
	if saved.Recovery != nil {
		expectedHeaders = saved.Recovery.Height
		if !saved.Recovery.Complete {
			expectedHeaders = saved.State.Height + 1
		}
	}
	inventoryErr := error(nil)
	for iter.Next() {
		if ctx.Err() != nil {
			inventoryErr = ctx.Err()
			break
		}
		if err := recoveryWork(ctx, uint64(len(iter.Key())+len(iter.Value())+1), nil); err != nil {
			inventoryErr = err
			break
		}
		key := string(iter.Key())
		if key == "head" {
			heads++
			continue
		}
		if strings.HasPrefix(key, "j/") {
			if count == int64(dagSegmentCounterMax) {
				inventoryErr = errFinancialStore
				break
			}
			count++
			if key != financialHeightKey(count) || len(iter.Value()) > financialJournalMaxWire {
				inventoryErr = errFinancialStore
				break
			}
		} else if height, ok := financialSDKHeaderHeight(key); ok && expectedHeaders > 0 {
			headers++
			if height != headers || headers > expectedHeaders || len(iter.Value()) > dagArchiveHeaderLimit {
				inventoryErr = errFinancialStore
				break
			}
		} else if strings.HasPrefix(key, "c/") && len(store.candidates) < financialCandidateLimit {
			value := iter.Value()
			if len(value) == 0 || len(value) > financialDagMaxBatchWire || key != "c/"+hashHex(value) {
				inventoryErr = errFinancialStore
				break
			}
			store.candidates[key] = len(value)
		} else if strings.HasPrefix(key, "p/") && pubPattern.MatchString(strings.TrimPrefix(key, "p/")) && len(iter.Value()) <= financialReceiptArchiveMaxWire {
			receipts++
		} else if publicFinancialProtocol(genesis) && validFinancialBlockOrderKey(key, saved.State.FinancialDAG.Blocks) && pubPattern.Match(iter.Value()) {
			blockOrderRows++
		} else if strings.HasPrefix(key, "t/") && validFinancialSummaryNodeKey(key, saved.State.FinancialDAG.Blocks) && pubPattern.Match(iter.Value()) {
			nodes++
		} else if genesis.FinancialDAG.hasLineage() && strings.HasPrefix(key, financialLineagePrefix) && lineageNodes < dagSegmentCounterMax {
			if _, err := decodeFinancialLineageNode(strings.TrimPrefix(key, financialLineagePrefix), iter.Value()); err != nil {
				inventoryErr = err
				break
			}
			lineageNodes++
		} else if genesis.FinancialDAG.hasGeneralAccounts() && strings.HasPrefix(key, financialAccountPrefix) && accountNodes < dagSegmentCounterMax {
			if _, err := decodeFinancialStoredAccount(strings.TrimPrefix(key, financialAccountPrefix), iter.Value(), store.accountRules); err != nil {
				inventoryErr = err
				break
			}
			accountNodes++
		} else if publicFinancialProtocol(genesis) && strings.HasPrefix(key, protocolRegistryPrefix) && protocolNodes < dagSegmentCounterMax {
			if _, err := decodeStoredProtocolRegistry(strings.TrimPrefix(key, protocolRegistryPrefix), iter.Value(), store.protocolRules); err != nil {
				inventoryErr = err
				break
			}
			protocolNodes++
		} else if publicFinancialProtocol(genesis) && strings.HasPrefix(key, protocolRewardPrefix) && protocolRewards < 1<<32 {
			var receipt protocolRewardReceipt
			if len(iter.Value()) > protocolRewardMaxWire || decodeStrictLimited(iter.Value(), &receipt, economicMaxRecipients, 64) != nil ||
				!streamCanonicalEqual(iter.Value(), receipt) || !validProtocolRewardReceipt(receipt, genesis, anchor) || key != protocolRewardPrefix+protocolRewardReceiptID(receipt) {
				inventoryErr = errFinancialProtocol
				break
			}
			protocolRewards++
		} else if publicFinancialProtocol(genesis) && strings.HasPrefix(key, "vc/") && committeeStates < dagSegmentCounterMax {
			var decision State
			committeeStates++
			if key != financialCommitteeStateKey(committeeStates) || len(iter.Value()) > 256*1024 || decodeStrictLimited(iter.Value(), &decision, 128, 64) != nil ||
				!streamCanonicalEqual(iter.Value(), decision) || validateState(decision, genesis, anchor) != nil || decision.Protocol == nil || decision.Protocol.PendingCommittee == nil ||
				decision.Protocol.PendingCommittee.Next.Epoch != committeeStates || decision.Protocol.PendingCommittee.DecidedHeight != uint64(decision.Height) {
				inventoryErr = errCommittee
				break
			}
		} else {
			inventoryErr = errFinancialStore
			break
		}
	}
	if iter.Error() != nil {
		inventoryErr = errFinancialStore
	}
	iter.Release()
	if inventoryErr != nil {
		return nil, nil, nil, inventoryErr
	}
	if heads != 1 || headers != expectedHeaders || count != saved.State.Height || receipts != saved.State.FinancialDAG.Blocks || nodes != 2*receipts-uint64(bits.OnesCount64(receipts)) {
		return nil, nil, nil, errFinancialStore
	}
	if publicFinancialProtocol(genesis) {
		if blockOrderRows != saved.State.FinancialDAG.Blocks {
			return nil, nil, nil, errFinancialStore
		}
		expected := saved.State.Protocol.Committee.Epoch
		if saved.State.Protocol.PendingCommittee != nil {
			expected = saved.State.Protocol.PendingCommittee.Next.Epoch
		}
		if committeeStates != expected {
			return nil, nil, nil, errCommittee
		}
	}
	sdkReplay, err := newFinancialStoredSDKReplay(func(key string) ([]byte, error) {
		return store.history.requiredRead(ctx, func(key string) ([]byte, error) { return store.history.get(ctx, key) }, key)
	}, genesis, saved.Recovery, state)
	if err != nil {
		return nil, nil, nil, store.history.rejectRecord(ctx, errFinancialStore)
	}
	var lineageReplay *financialLineageScratch
	if genesis.FinancialDAG.hasLineage() {
		lineageReplay, err = newFinancialLineageScratch()
		if err != nil {
			return nil, nil, nil, err
		}
		defer func() {
			if err := lineageReplay.close(); err != nil {
				opened, snapshots, ready, failure = nil, nil, nil, err
				valid = false
			}
		}()
	}
	var accountReplay *financialAccountScratch
	if genesis.FinancialDAG.hasGeneralAccounts() {
		accountReplay, err = newFinancialAccountScratch(store.accountRules)
		if err != nil {
			return nil, nil, nil, err
		}
		defer func() {
			if err := accountReplay.close(); err != nil {
				opened, snapshots, ready, failure = nil, nil, nil, err
				valid = false
			}
		}()
		if err = store.stageAccounts(ctx, execution, nil); err != nil {
			return nil, nil, nil, err
		}
		if err = accountReplay.stage(ctx, execution); err != nil {
			return nil, nil, nil, err
		}
		if err = freezeFinancialAccounts(execution, accountReplay.read); err != nil {
			return nil, nil, nil, err
		}
	}
	var protocolReplay *financialProtocolScratch
	if execution.source.hasProtocol() {
		protocolReplay, err = newFinancialProtocolScratch(genesis, anchor)
		if err != nil {
			return nil, nil, nil, err
		}
		defer func() {
			if err := protocolReplay.close(); err != nil {
				opened, snapshots, ready, failure = nil, nil, nil, err
				valid = false
			}
		}()
		if err = store.stageProtocol(ctx, execution, nil); err != nil {
			return nil, nil, nil, err
		}
		if err = protocolReplay.stage(ctx, execution); err != nil {
			return nil, nil, nil, err
		}
		if err = freezeFinancialProtocol(execution, protocolReplay.read); err != nil {
			return nil, nil, nil, err
		}
	}
	cuts, err := newFinancialHistoryCutCursor(store.history)
	if err != nil || cuts.check(0, state.StateRoot, DagZero) != nil {
		return nil, nil, nil, errFinancialHistory
	}
	for height := int64(1); height <= count; height++ {
		if ctx.Err() != nil {
			return nil, nil, nil, ctx.Err()
		}
		raw, err := store.history.requiredRead(ctx, func(key string) ([]byte, error) { return store.history.get(ctx, key) }, financialHeightKey(height))
		var entry financialJournalEntry
		if err != nil || len(raw) > financialJournalMaxWire || decodeStrictLimited(raw, &entry, DagMaxBatchBlocks, 64) != nil || !streamCanonicalEqual(raw, entry) ||
			entry.Schema != "gg.financial-dag.journal-entry.v1" || entry.Height != height || entry.Previous != store.head.Journal {
			return nil, nil, nil, errFinancialStore
		}
		when, ok := dagDecimalNs(entry.TimeNs)
		if !ok || when < store.timeNs || when > int64(dagSegmentCounterMax)-5000000000 {
			return nil, nil, nil, errFinancialStore
		}
		execution, err = advanceFinancialExecution(ctx, execution, state, when)
		if err != nil {
			return nil, nil, nil, err
		}
		if !bytes.Equal(entry.Transaction, []byte("null")) {
			execution, err = financialTransition(ctx, execution, entry.Transaction, when)
			if err != nil {
				return nil, nil, nil, errFinancialStore
			}
		}
		state, err = financialNativeState(state, execution, height)
		if err != nil || state.StateRoot != entry.After {
			return nil, nil, nil, errFinancialStore
		}
		if state.Protocol != nil && state.Protocol.PendingCommittee != nil && state.Protocol.PendingCommittee.DecidedHeight == uint64(height) {
			actual, readErr := store.history.requiredRead(ctx, func(key string) ([]byte, error) { return store.history.get(ctx, key) }, financialCommitteeStateKey(state.Protocol.PendingCommittee.Next.Epoch))
			if readErr != nil || !bytes.Equal(actual, canonical(state)) {
				return nil, nil, nil, store.history.rejectRecord(ctx, errCommittee)
			}
		}
		if sdkErr := sdkReplay.apply(entry, state); sdkErr != nil {
			return nil, nil, nil, store.history.rejectRecord(ctx, errFinancialStore)
		}
		store.tree, err = financialReceiptEntries(ctx, store.tree, execution, height, func(key string, expected []byte) error {
			actual, readErr := store.history.requiredRead(ctx, func(key string) ([]byte, error) { return store.history.get(ctx, key) }, key)
			if readErr != nil || !bytes.Equal(actual, expected) {
				return store.history.rejectRecord(ctx, errFinancialStore)
			}
			return nil
		})
		if err != nil {
			return nil, nil, nil, err
		}
		if err = store.stageLineage(ctx, execution, nil); err != nil {
			return nil, nil, nil, err
		}
		if err = store.stageAccounts(ctx, execution, nil); err != nil {
			return nil, nil, nil, err
		}
		if err = store.stageProtocol(ctx, execution, nil); err != nil {
			return nil, nil, nil, err
		}
		if protocolReplay != nil {
			if err = protocolReplay.stage(ctx, execution); err != nil {
				return nil, nil, nil, err
			}
			if err = freezeFinancialProtocol(execution, protocolReplay.read); err != nil {
				return nil, nil, nil, err
			}
		}
		if accountReplay != nil {
			if err = accountReplay.stage(ctx, execution); err != nil {
				return nil, nil, nil, err
			}
			if err = freezeFinancialAccounts(execution, accountReplay.read); err != nil {
				return nil, nil, nil, err
			}
		}
		if lineageReplay != nil {
			if err = lineageReplay.stage(ctx, execution); err != nil {
				return nil, nil, nil, err
			}
		}
		freezeFinancialLineage(execution, store.readLineageNode)
		store.producerViews, err = financialProducerViews(store.producerViews, execution)
		if err != nil {
			return nil, nil, nil, err
		}
		execution = execution.clone()
		store.head.Journal, store.timeNs = financialJournalHash(raw), when
		if err := cuts.check(height, state.StateRoot, store.head.Journal); err != nil {
			return nil, nil, nil, err
		}
		if err := recoveryWork(ctx, 1, &height); err != nil {
			return nil, nil, nil, err
		}
		history = append(history, state)
		if len(history) > HistoryLimit {
			history = append([]State(nil), history[len(history)-HistoryLimit:]...)
		}
	}
	if cuts.next != nil {
		return nil, nil, nil, errFinancialHistory
	}
	if !bytes.Equal(canonical(state), canonical(saved.State)) || store.head.Journal != saved.Journal || saved.TimeNs != strconv.FormatInt(store.timeNs, 10) {
		return nil, nil, nil, errFinancialStore
	}
	store.head = saved
	if lineageReplay != nil {
		expected, err := lineageReplay.count(ctx)
		if err != nil || expected != lineageNodes {
			return nil, nil, nil, errFinancialStore
		}
	}
	if accountReplay != nil {
		expected, err := accountReplay.count(ctx)
		if err != nil || expected != accountNodes {
			return nil, nil, nil, errFinancialStore
		}
		if err = freezeFinancialAccounts(execution, store.readAccountNode); err != nil {
			return nil, nil, nil, err
		}
	}
	if protocolReplay != nil {
		nodes, rewards, err := protocolReplay.counts(ctx)
		if err != nil || nodes != protocolNodes || rewards != protocolRewards {
			return nil, nil, nil, errFinancialStore
		}
		if err = freezeFinancialProtocol(execution, store.readProtocolNode); err != nil {
			return nil, nil, nil, err
		}
		store.execution = execution.clone()
	}
	if err = store.history.resolvePending(ctx, store.head); err != nil {
		return nil, nil, nil, err
	}
	if err = store.history.initialize(ctx); err != nil {
		return nil, nil, nil, err
	}
	if store.history.activeBytes >= financialHistoryActiveTarget {
		if err := store.history.drainTo(ctx, store.head, financialHistoryLowWatermark); err != nil {
			return nil, nil, nil, err
		}
	}
	if err := recoveryWork(ctx, 1, nil); err != nil {
		return nil, nil, nil, err
	}
	store.verifiedThrough = saved.State.Height
	valid = true
	if sdkReplay != nil && saved.Recovery != nil && saved.Recovery.Complete {
		store.recoverySDK = sdkReplay.sdk
	}
	return store, history, execution, nil
}

func (store *financialStore) stage(ctx context.Context, raw []byte) error {
	store.mu.Lock()
	defer store.mu.Unlock()
	if ctx.Err() != nil {
		return ctx.Err()
	}
	if store.db == nil || store.failed || store.history.failed.Load() || len(raw) == 0 || len(raw) > financialDagMaxBatchWire {
		return errFinancialStore
	}
	key := "c/" + hashHex(raw)
	if _, ok := store.candidates[key]; ok {
		saved, err := store.db.Get([]byte(key), nil)
		if err != nil || !bytes.Equal(saved, raw) {
			store.failed = true
			return errFinancialStore
		}
		return nil
	}
	if len(store.candidates) >= financialCandidateLimit {
		return errDagCandidateCredit
	}
	batch := new(leveldb.Batch)
	batch.Put([]byte(key), raw)
	if store.syncWrite(batch) != nil {
		return errFinancialStore
	}
	store.candidates[key] = len(raw)
	return nil
}

func (store *financialStore) commit(ctx context.Context, state State, execution *financialDagExecution, raw []byte, when int64) error {
	return store.commitWithSDKHeader(ctx, state, execution, raw, when, nil)
}

func (store *financialStore) commitWithSDKHeader(ctx context.Context, state State, execution *financialDagExecution, raw []byte, when int64, sdkHeader []byte) error {
	var protocolBase *financialDagExecution
	var protocolBefore State
	if execution.source.hasProtocol() {
		store.mu.Lock()
		if store.db == nil || store.failed || store.history.failed.Load() || store.execution == nil {
			store.mu.Unlock()
			return errFinancialStore
		}
		protocolBefore = copyState(store.head.State)
		base := store.execution
		store.mu.Unlock()
		var err error
		protocolBase, err = advanceFinancialExecution(ctx, base, protocolBefore, when)
		if err != nil {
			return err
		}
	}
	store.mu.Lock()
	defer store.mu.Unlock()
	if ctx.Err() != nil {
		return ctx.Err()
	}
	if store.db == nil || store.failed || store.history.failed.Load() || store.head.State.Height == int64(dagSegmentCounterMax) || state.Height != store.head.State.Height+1 ||
		when < store.timeNs || when > int64(dagSegmentCounterMax)-5000000000 || len(raw) > financialDagMaxBatchWire {
		return errFinancialStore
	}
	if protocolBase != nil && protocolBefore.StateRoot != store.head.State.StateRoot {
		return errFinancialStore
	}
	if protocolBase != nil && len(raw) == 0 {
		expected, err := financialNativeState(store.head.State, protocolBase, state.Height)
		if err != nil || !bytes.Equal(canonical(expected), canonical(state)) {
			return errFinancialStore
		}
	}
	expected, err := financialNativeState(store.head.State, execution, state.Height)
	if err != nil || !bytes.Equal(canonical(expected), canonical(state)) {
		return errFinancialStore
	}
	// Archive only already committed immutable records, before this new commit.
	// Drain to low watermark; fixed per-segment memory, context-cancellable IO.
	// The active footprint is below trigger plus one existing bounded commit.
	if store.history.activeBytes >= financialHistoryActiveTarget {
		if err := store.history.drainTo(ctx, store.head, financialHistoryLowWatermark); err != nil {
			store.failed = true
			return err
		}
	}
	before := *store.head.State.FinancialDAG
	if protocolBase != nil {
		var err error
		before, err = protocolBase.commitment()
		if err != nil {
			return err
		}
	}
	after := *state.FinancialDAG
	if len(raw) == 0 && !bytes.Equal(canonical(before), canonical(after)) || len(raw) > 0 && (before.Checkpoint == dagSegmentCounterMax || after.Checkpoint != before.Checkpoint+1 ||
		after.Previous != dagDigest(financialDomain+"DAG-COMMITMENT\x00", before) || after.TimeNs != strconv.FormatInt(when, 10) ||
		after.Epoch != before.Epoch && after.Epoch != before.Epoch+1) {
		return errFinancialStore
	}
	tx := json.RawMessage(nil)
	if len(raw) > 0 {
		key := "c/" + hashHex(raw)
		saved, err := store.db.Get([]byte(key), nil)
		if _, ok := store.candidates[key]; !ok || err != nil || !bytes.Equal(saved, raw) {
			store.failed = true
			return errFinancialStore
		}
		tx = raw
	}
	entry := financialJournalEntry{After: state.StateRoot, Height: state.Height, Previous: store.head.Journal, Schema: "gg.financial-dag.journal-entry.v1", TimeNs: strconv.FormatInt(when, 10), Transaction: tx}
	encoded := canonical(entry)
	head := financialStoreHead{Anchor: store.head.Anchor, Journal: financialJournalHash(encoded), Schema: store.head.Schema, Source: store.head.Source, State: copyState(state), TimeNs: entry.TimeNs, Recovery: store.head.Recovery}
	batch := new(leveldb.Batch)
	if err = store.stageLineage(ctx, execution, batch); err != nil {
		store.failed = true
		return err
	}
	if err = store.stageAccounts(ctx, execution, batch); err != nil {
		store.failed = true
		return err
	}
	if err = store.stageProtocol(ctx, execution, batch); err != nil {
		store.failed = true
		return err
	}
	if state.Protocol != nil && state.Protocol.PendingCommittee != nil && state.Protocol.PendingCommittee.DecidedHeight == uint64(state.Height) {
		key := []byte(financialCommitteeStateKey(state.Protocol.PendingCommittee.Next.Epoch))
		present, readErr := store.db.Has(key, nil)
		if readErr != nil || present {
			return store.history.rejectRecord(ctx, errCommittee)
		}
		batch.Put(key, canonical(state))
	}
	if store.head.Recovery != nil && !store.head.Recovery.Complete {
		previousRaw, readErr := store.history.requiredRead(ctx, func(key string) ([]byte, error) { return store.history.get(ctx, key) }, financialSDKHeaderKey(state.Height))
		if readErr != nil {
			return errFinancialSDKBinding
		}
		previous, readErr := checkedFinancialSDKHeader(previousRaw, execution.genesis, state.Height)
		if readErr != nil {
			return store.history.rejectRecord(ctx, errFinancialSDKBinding)
		}
		next, nextErr := checkedFinancialSDKHeader(sdkHeader, execution.genesis, state.Height+1)
		if readErr != nil || nextErr != nil || financialSDKJournalBinding(previous, next, entry, state) != nil {
			return errFinancialSDKBinding
		}
		batch.Put([]byte(financialSDKHeaderKey(state.Height+1)), sdkHeader)
	} else if len(sdkHeader) != 0 {
		return errFinancialSDKBinding
	}
	tree, err := financialReceiptEntries(ctx, store.tree, execution, state.Height, func(key string, value []byte) error {
		present, readErr := store.db.Has([]byte(key), nil)
		if readErr != nil || present {
			return store.history.rejectRecord(ctx, errFinancialStore)
		}
		batch.Put([]byte(key), value)
		return nil
	})
	if err != nil {
		return err
	}
	batch.Put([]byte(financialHeightKey(state.Height)), encoded)
	views, err := financialProducerViews(store.producerViews, execution)
	if err != nil {
		return err
	}
	batch.Put([]byte("head"), canonical(head))
	for key := range store.candidates {
		batch.Delete([]byte(key))
	}
	if ctx.Err() != nil {
		return ctx.Err()
	}
	if store.syncWrite(batch) != nil {
		return errFinancialStore
	}
	store.head, store.timeNs, store.candidates = head, when, map[string]int{}
	store.history.retainedThrough.Store(head.State.Height)
	store.tree = tree
	freezeFinancialLineage(execution, store.readLineageNode)
	if err = freezeFinancialAccounts(execution, store.readAccountNode); err != nil {
		store.failed = true
		return err
	}
	if err = freezeFinancialProtocol(execution, store.readProtocolNode); err != nil {
		store.failed = true
		return err
	}
	if execution.source.hasProtocol() {
		store.execution = execution.clone()
	}
	freezeFinancialLineageViews(views, store.readLineageNode)
	store.producerViews = views
	return nil
}
