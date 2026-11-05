//go:build !js

package main

// Explicit v4 SDK storage. Proposal originals are synced before a vote. A
// canonical head, native history and the archive reference switch atomically.
// Startup derives DAG state by replay, never by trusting a saved account image.
import (
	"bytes"
	"context"
	"encoding/base64"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"

	"github.com/syndtr/goleveldb/leveldb"
	"github.com/syndtr/goleveldb/leveldb/opt"
	"github.com/syndtr/goleveldb/leveldb/util"
)

var errDagSegmentStore = errors.New("GG_DAG_SEGMENTED_STORE_UNAVAILABLE")

type dagSegmentStoreMeta struct {
	Anchor     string `json:"anchor"`
	Bytes      uint64 `json:"bytes"`
	Manifests  int    `json:"manifests"`
	Records    int    `json:"records"`
	Schema     string `json:"schema"`
	SourceHash string `json:"source_hash"`
}

type dagSegmentArchiveReference struct {
	ArchiveHash string `json:"archive_sha256"`
	Cut         string `json:"cut"`
	Epoch       uint64 `json:"epoch,string"`
	Schema      string `json:"schema"`
}

type dagSegmentStore struct {
	mu                sync.Mutex
	closeMu           sync.Mutex
	payloadReaders    sync.WaitGroup
	payloadSlots      chan struct{}
	payloadCache      dagPayloadCache
	db                *leveldb.DB
	root              string
	meta              dagSegmentStoreMeta
	selected          *dagSegmentedExecution
	ready             *dagSegmentArchiveReceipt
	failed            bool
	closedEntries     uint64
	transition        *dagIndexTransitionProgress
	transitionSaved   bool
	proofViews        []dagSegmentProofView
	proofSlots        chan struct{}
	beforeProofRead   func()                     // owned test hook, set before concurrent queries
	beforePayloadRead func()                     // owned test hook, outside consensus/store locks
	write             func(*leveldb.Batch) error // owned test hook wraps real synchronous IO
}

func segmentStateHash(execution *dagSegmentedExecution) (string, error) {
	state, err := execution.state()
	if err != nil {
		return "", err
	}
	return dagDigest("GG-DAG-SEGMENTED-STATE-v1\x00", state), nil
}

func (store *dagSegmentStore) syncWrite(batch *leveldb.Batch) error {
	if store.db == nil || store.failed {
		return errDagSegmentStore
	}
	if err := store.write(batch); err != nil {
		store.failed = true
		return errDagSegmentStore
	}
	return nil
}

func (store *dagSegmentStore) health() error {
	store.mu.Lock()
	defer store.mu.Unlock()
	if store.failed || store.db == nil || store.meta.Schema != "gg.dag.segmented-store.v2" {
		return errDagSegmentStore
	}
	return nil
}

func (store *dagSegmentStore) close() error {
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
	// No new snapshot can enter after db=nil. Existing readers release their
	// database leases outside the store/consensus locks before the DB closes.
	store.payloadReaders.Wait()
	store.payloadCache.clear()
	return db.Close()
}

func openDagSegmentStore(genesis Genesis, anchor, root string, create bool) (*dagSegmentStore, []State, *dagSegmentedExecution, error) {
	return openDagSegmentStoreMode(genesis, anchor, root, create, false)
}

// Public export acquires the same OS database lease, with writes disabled.
// It cannot inspect or alter a running validator's database.
func openDagSegmentStoreMode(genesis Genesis, anchor, root string, create, readOnly bool) (*dagSegmentStore, []State, *dagSegmentedExecution, error) {
	mode := dagSegmentOpenNormal
	if readOnly {
		mode = dagSegmentOpenPublicRead
	}
	return openDagSegmentStoreContext(context.Background(), genesis, anchor, root, create, mode)
}

type dagSegmentOpenMode uint8

const (
	dagSegmentOpenNormal dagSegmentOpenMode = iota
	dagSegmentOpenPublicRead
	dagSegmentOpenIndexTransition
)

// Only the local maintenance command selects transition mode. RPC, normal
// startup and public export never accept partial/indexless stores as writable
// consensus authorities or substitute a caller's already-verified flag.
func openDagSegmentStoreContext(ctx context.Context, genesis Genesis, anchor, root string, create bool, mode dagSegmentOpenMode) (*dagSegmentStore, []State, *dagSegmentedExecution, error) {
	if ctx == nil || ctx.Err() != nil || mode > dagSegmentOpenIndexTransition || create && mode == dagSegmentOpenIndexTransition {
		return nil, nil, nil, errDagSegmentStore
	}
	readOnly := mode == dagSegmentOpenPublicRead
	if create && readOnly || validateGenesis(genesis, anchor) != nil || genesis.DAGSegmented == nil || !filepath.IsAbs(root) || !realArchiveDirectory(root) {
		return nil, nil, nil, errDagSegmentStore
	}
	resolved, err := filepath.EvalSymlinks(root)
	if err != nil {
		return nil, nil, nil, errDagSegmentStore
	}
	path := filepath.Join(resolved, "gg-dag-segmented.leveldb")
	if info, err := os.Lstat(path); err == nil {
		if create || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
			return nil, nil, nil, errDagSegmentStore
		}
	} else if !os.IsNotExist(err) || !create {
		return nil, nil, nil, errDagSegmentStore
	}
	db, err := leveldb.OpenFile(path, &opt.Options{ReadOnly: readOnly, ErrorIfExist: create, ErrorIfMissing: !create, Strict: opt.StrictAll,
		Compression: opt.NoCompression, WriteBuffer: 4 * 1024 * 1024, BlockCacheCapacity: 4 * 1024 * 1024, OpenFilesCacheCapacity: 32})
	if err != nil {
		return nil, nil, nil, errDagSegmentStore
	}
	store := &dagSegmentStore{db: db, root: resolved, proofSlots: make(chan struct{}, dagPublicMaxReaders), payloadSlots: make(chan struct{}, dagPayloadMaxReaders)}
	store.write = func(batch *leveldb.Batch) error {
		return db.Write(batch, &opt.WriteOptions{Sync: true, NoWriteMerge: true})
	}
	valid := false
	defer func() {
		if !valid {
			_ = db.Close()
		}
	}()
	initial, err := newDagSegmentedExecution(*genesis.DAGSegmented, anchor)
	if err != nil {
		return nil, nil, nil, err
	}
	state, _ := initial.state()
	store.meta = dagSegmentStoreMeta{Anchor: anchor, Schema: "gg.dag.segmented-store.v2", SourceHash: state.SourceHash}
	if create {
		history := []State{initialState(genesis, anchor)}
		manifest := canonical(initial.active.Manifest)
		store.meta.Manifests, store.meta.Bytes = 1, uint64(len(manifest))
		batch := new(leveldb.Batch)
		batch.Put([]byte("meta"), canonical(store.meta))
		batch.Put([]byte("m/"+initial.startManifest), manifest)
		batch.Put([]byte("history"), canonical(persisted{GenesisHash: anchor, History: history, Schema: "gg.native.public-history.v3"}))
		if store.syncWrite(batch) != nil {
			return nil, nil, nil, errDagSegmentStore
		}
		store.selected = initial
		if err := store.retainReplayProof(initial); err != nil {
			return nil, nil, nil, err
		}
		valid = true
		return store, history, store.view(initial), nil
	}
	raw, err := db.Get([]byte("meta"), nil)
	var savedMeta dagSegmentStoreMeta
	legacy := err == nil && len(raw) <= 1024 && decodeStrict(raw, &savedMeta) == nil && bytes.Equal(raw, canonical(savedMeta)) && savedMeta.Schema == "gg.dag.segmented-store.v1"
	if legacy && mode != dagSegmentOpenIndexTransition {
		return nil, nil, nil, errors.New("GG_DAG_SEGMENTED_INDEX_TRANSITION_REQUIRED")
	}
	wantedSchema := store.meta.Schema
	if legacy {
		wantedSchema = "gg.dag.segmented-store.v1"
	}
	if err != nil || len(raw) > 1024 || decodeStrict(raw, &savedMeta) != nil || !bytes.Equal(raw, canonical(savedMeta)) ||
		savedMeta.Anchor != anchor || savedMeta.Schema != wantedSchema || savedMeta.SourceHash != store.meta.SourceHash ||
		savedMeta.Bytes > dagStoreMaxBytes || savedMeta.Records < 0 || savedMeta.Records > dagStoreMaxObjects ||
		savedMeta.Manifests < 1 || savedMeta.Manifests > dagStoreMaxObjects {
		return nil, nil, nil, errDagSegmentStore
	}
	store.meta = savedMeta
	if legacy {
		if err := store.loadIndexTransition(); err != nil {
			return nil, nil, nil, err
		}
	}
	if err := store.checkInventory(); err != nil {
		return nil, nil, nil, err
	}
	raw, err = db.Get([]byte("history"), nil)
	var saved persisted
	if err != nil || len(raw) > dagHistoryMaxBytes || decodeStrict(raw, &saved) != nil || !bytes.Equal(raw, canonical(saved)) ||
		saved.Schema != "gg.native.public-history.v3" || saved.GenesisHash != anchor || len(saved.History) < 1 || len(saved.History) > HistoryLimit {
		return nil, nil, nil, errDagSegmentStore
	}
	if store.transition != nil {
		if store.transitionSaved && store.transition.HistoryHash != hashHex(raw) {
			return nil, nil, nil, errDagIndexTransition
		}
		store.transition.HistoryHash = hashHex(raw)
	}
	for index, state := range saved.History {
		if validateState(state, genesis, anchor) != nil {
			return nil, nil, nil, errDagSegmentStore
		}
		if index > 0 && !validSegmentSDKLink(saved.History[index-1], state) {
			return nil, nil, nil, errDagSegmentStore
		}
	}
	expected := *saved.History[len(saved.History)-1].DAGSegmented
	if store.closedEntries != expected.Epoch-1 {
		return nil, nil, nil, errDagSegmentStore
	}
	// Historical query snapshots also need original-history provenance. A
	// self-consistent re-sealed intermediate snapshot is not a replay proof.
	requiredStates := map[string]bool{}
	for _, state := range saved.History {
		requiredStates[dagDigest("GG-DAG-SEGMENTED-STATE-v1\x00", *state.DAGSegmented)] = true
	}
	proofStates := map[string]bool{}
	for key := range requiredStates {
		proofStates[key] = true
	}
	retain := func(execution *dagSegmentedExecution) error {
		value, err := execution.state()
		if err != nil {
			return err
		}
		if !proofStates[dagDigest("GG-DAG-SEGMENTED-STATE-v1\x00", value)] {
			return nil
		}
		return store.retainReplayProof(execution)
	}
	observe := func(state dagSegmentedState) {
		delete(requiredStates, dagDigest("GG-DAG-SEGMENTED-STATE-v1\x00", state))
	}
	cursor := initial
	initialState, _ := cursor.state()
	observe(initialState)
	if err := retain(cursor); err != nil {
		return nil, nil, nil, err
	}
	for epoch := uint64(1); epoch < expected.Epoch; epoch++ {
		if ctx.Err() != nil {
			return nil, nil, nil, ctx.Err()
		}
		raw, err := db.Get([]byte(segmentArchiveReferenceKey(epoch)), nil)
		var reference dagSegmentArchiveReference
		if err != nil || len(raw) > 512 || decodeStrict(raw, &reference) != nil || !bytes.Equal(raw, canonical(reference)) ||
			reference.Schema != "gg.dag.segment-reference.v1" || reference.Epoch != epoch || !pubPattern.MatchString(reference.Cut) || !pubPattern.MatchString(reference.ArchiveHash) {
			return nil, nil, nil, errDagSegmentStore
		}
		file, _, err := checkedSegmentFile(filepath.Join(resolved, "gg-dag-segments", reference.Cut+".ggseg"), false, dagSegmentArchiveMaxBytes)
		if err != nil {
			return nil, nil, nil, err
		}
		replayed, replayErr := readDagHistorySegmentObserved(ctx, file, cursor, observe, retain)
		closeErr := file.Close()
		if replayErr != nil || closeErr != nil || replayed.plan.hash != reference.Cut || replayed.archiveHash != reference.ArchiveHash {
			return nil, nil, nil, errDagSegmentStore
		}
		if store.transition == nil || epoch <= store.transition.Indexed {
			if err := store.verifyClosedIndex(replayed.index, cursor.closed); err != nil {
				return nil, nil, nil, err
			}
		}
		cursor = replayed.plan.next
	}
	chain := []string{}
	identifier := expected.Active.ManifestHash
	for {
		manifest, err := store.readManifest(identifier)
		if err != nil {
			return nil, nil, nil, err
		}
		if manifest.Checkpoint == 0 {
			if identifier != cursor.startManifest || !bytes.Equal(canonical(manifest), canonical(cursor.active.Manifest)) {
				return nil, nil, nil, errDagSegmentStore
			}
			break
		}
		if len(chain) >= DagMaxRecords || manifest.Checkpoint != uint64(expected.Active.Checkpoint)-uint64(len(chain)) {
			return nil, nil, nil, errDagSegmentStore
		}
		chain = append(chain, identifier)
		identifier = manifest.Previous
	}
	for index := len(chain) - 1; index >= 0; index-- {
		if ctx.Err() != nil {
			return nil, nil, nil, ctx.Err()
		}
		manifest, err := store.readManifest(chain[index])
		if err != nil {
			return nil, nil, nil, err
		}
		cursor, err = store.replayManifest(cursor, manifest)
		if err != nil {
			return nil, nil, nil, err
		}
		state, _ := cursor.state()
		observe(state)
		if err := retain(cursor); err != nil {
			return nil, nil, nil, err
		}
	}
	actual, err := cursor.state()
	if err != nil || actual != expected || len(requiredStates) != 0 {
		return nil, nil, nil, errDagSegmentStore
	}
	if ctx.Err() != nil {
		return nil, nil, nil, ctx.Err()
	}
	store.selected = cursor
	valid = true
	return store, saved.History, store.view(cursor), nil
}

func validSegmentSDKLink(before, after State) bool {
	if after.Height != before.Height+1 || before.DAGSegmented == nil || after.DAGSegmented == nil {
		return false
	}
	a, b := *before.DAGSegmented, *after.DAGSegmented
	if a.Epoch == b.Epoch {
		if a.Active.Checkpoint == b.Active.Checkpoint {
			return a == b
		}
		return b.Active.Checkpoint == a.Active.Checkpoint+1 && b.Active.Previous == a.Active.ManifestHash && b.Blocks > a.Blocks &&
			b.Transactions >= a.Transactions && b.ClosedRoot == a.ClosedRoot && b.LastCut == a.LastCut
	}
	if b.Epoch != a.Epoch+1 || a.Active.Blocks == 0 || b.Active.Blocks != 0 || b.Active.Checkpoint != 0 ||
		b.Blocks != a.Blocks || b.Transactions != a.Transactions || b.RawBytes != a.RawBytes || b.LastRank != a.LastRank || b.Authors != a.Authors {
		return false
	}
	return b.Active.AccountRoot == a.Active.AccountRoot && b.LastCut != a.LastCut && b.ClosedRoot != a.ClosedRoot
}

func segmentArchiveReferenceKey(epoch uint64) string { return fmt.Sprintf("c/%020d", epoch) }

func (store *dagSegmentStore) checkInventory() error {
	meta := dagSegmentStoreMeta{}
	closedIndexes, closedNodes := uint64(0), uint64(0)
	iter := store.db.NewIterator(nil, nil)
	defer iter.Release()
	for iter.Next() {
		key, raw := string(iter.Key()), iter.Value()
		switch {
		case key == "meta" || key == "history":
		case key == dagIndexTransitionKey:
			if store.transition == nil || !store.transitionSaved || !bytes.Equal(raw, canonical(store.transition)) {
				return errDagIndexTransition
			}
		case strings.HasPrefix(key, "r/"):
			if len(raw) < 1 || len(raw) > DagMaxWire || !pubPattern.MatchString(key[2:]) || hashHex(raw) != key[2:] {
				return errDagSegmentStore
			}
			meta.Records++
			meta.Bytes += uint64(len(raw))
		case strings.HasPrefix(key, "m/"):
			if _, err := checkedSegmentManifest(raw, key[2:], store.meta.Anchor, store.meta.SourceHash); err != nil {
				return errDagSegmentStore
			}
			meta.Manifests++
			meta.Bytes += uint64(len(raw))
		case strings.HasPrefix(key, "c/"):
			epoch, err := strconv.ParseUint(key[2:], 10, 64)
			var reference dagSegmentArchiveReference
			if err != nil || epoch != store.closedEntries+1 || epoch >= dagSegmentCounterMax || key != segmentArchiveReferenceKey(epoch) || len(raw) > 512 ||
				decodeStrict(raw, &reference) != nil || !bytes.Equal(raw, canonical(reference)) || reference.Epoch != epoch ||
				reference.Schema != "gg.dag.segment-reference.v1" || !pubPattern.MatchString(reference.Cut) || !pubPattern.MatchString(reference.ArchiveHash) {
				return errDagSegmentStore
			}
			store.closedEntries++
		case strings.HasPrefix(key, "t/"):
			limit := store.closedEntries
			if store.transition != nil {
				limit = store.transition.Indexed
			}
			if !validClosedNodeKey(key, limit) || !pubPattern.Match(raw) {
				return errDagSegmentStore
			}
			closedNodes++
		case strings.HasPrefix(key, "x/"):
			epoch, err := strconv.ParseUint(key[2:], 10, 64)
			limit := store.closedEntries
			if store.transition != nil {
				limit = store.transition.Indexed
			}
			if err != nil || epoch != closedIndexes+1 || key != closedIndexKey(epoch) || epoch > limit || len(raw) == 0 || len(raw) > dagClosedIndexMaxBytes {
				return errDagSegmentStore
			}
			closedIndexes++
		default:
			return errDagSegmentStore
		}
		if meta.Bytes > dagStoreMaxBytes || meta.Records > dagStoreMaxObjects || meta.Manifests > dagStoreMaxObjects {
			return errDagSegmentStore
		}
	}
	limit := store.closedEntries
	if store.transition != nil {
		limit = store.transition.Indexed
	}
	if limit > store.closedEntries || iter.Error() != nil || meta.Bytes != store.meta.Bytes || meta.Records != store.meta.Records || meta.Manifests != store.meta.Manifests || closedIndexes != limit || closedNodes != closedIndexNodeCount(limit) {
		return errDagSegmentStore
	}
	return nil
}

func (store *dagSegmentStore) readManifest(identifier string) (DagManifest, error) {
	if !pubPattern.MatchString(identifier) {
		return DagManifest{}, errDagSegmentStore
	}
	raw, err := store.db.Get([]byte("m/"+identifier), nil)
	if err != nil {
		return DagManifest{}, errDagSegmentStore
	}
	return checkedSegmentManifest(raw, identifier, store.meta.Anchor, store.meta.SourceHash)
}

func checkedSegmentManifest(raw []byte, identifier, anchor, sourceHash string) (DagManifest, error) {
	var value DagManifest
	if len(raw) == 0 || len(raw) > dagManifestMaxBytes || decodeStrict(raw, &value) != nil || !bytes.Equal(raw, canonical(value)) {
		return value, errDagSegmentStore
	}
	if value.Checkpoint != 0 {
		return checkedDagManifest(raw, identifier, anchor, sourceHash)
	}
	if value.Schema != "gg.dag.execution.manifest.v1" || value.GenesisHash != anchor || value.SourceHash != sourceHash ||
		!pubPattern.MatchString(value.Previous) || value.Blocks == nil || len(value.Blocks) != 0 || dagDigest("GG-DAG-CHECKPOINT-MANIFEST-v1\x00", value) != identifier {
		return value, errDagSegmentStore
	}
	if value.Previous == DagZero {
		if value.TimeNs != "0" {
			return value, errDagSegmentStore
		}
	} else if _, ok := dagDecimalNs(value.TimeNs); !ok {
		return value, errDagSegmentStore
	}
	return value, nil
}

func (store *dagSegmentStore) readPayload(ctx context.Context, wire string, size int) ([]byte, error) {
	store.mu.Lock()
	defer store.mu.Unlock()
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	if store.db == nil || store.failed || size < 1 || size > DagMaxWire || !pubPattern.MatchString(wire) {
		return nil, errDagSegmentStore
	}
	raw, err := store.db.Get([]byte("r/"+wire), nil)
	if err != nil || len(raw) != size || hashHex(raw) != wire {
		return nil, errDagSegmentStore
	}
	return raw, nil
}

func (store *dagSegmentStore) view(execution *dagSegmentedExecution) *dagSegmentedExecution {
	next, active := *execution, *execution.active
	active.pending = map[string]dagRecord{}
	active.payloadReader = store.readPayload
	next.active = &active
	return &next
}

func (store *dagSegmentStore) replayManifest(base *dagSegmentedExecution, manifest DagManifest) (*dagSegmentedExecution, error) {
	when, err := strconv.ParseInt(manifest.TimeNs, 10, 64)
	if err != nil || when <= 0 || strconv.FormatInt(when, 10) != manifest.TimeNs {
		return nil, errDagSegmentStore
	}
	encoded := make([]string, 0, len(manifest.Blocks))
	size := 0
	for _, hash := range manifest.Blocks {
		raw, err := store.db.Get([]byte("r/"+hash), nil)
		if err != nil || len(raw) > DagMaxWire-size || hashHex(raw) != hash {
			return nil, errDagSegmentStore
		}
		size += len(raw)
		encoded = append(encoded, base64.StdEncoding.EncodeToString(raw))
	}
	next, err := base.apply(canonical(DagBatch{Blocks: encoded, GenesisHash: store.meta.Anchor, Previous: manifest.Previous,
		Schema: "gg.dag.checkpoint.batch.v1", Sequence: manifest.Checkpoint}), when)
	if err != nil || !bytes.Equal(canonical(next.active.Manifest), canonical(manifest)) {
		return nil, errDagSegmentStore
	}
	return store.view(next), nil
}

func (store *dagSegmentStore) stage(ctx context.Context, execution *dagSegmentedExecution) error {
	store.mu.Lock()
	defer store.mu.Unlock()
	if ctx.Err() != nil {
		return ctx.Err()
	}
	if store.db == nil || store.failed || execution == nil || execution.checkActiveHistory() != nil {
		return errDagSegmentStore
	}
	state, err := execution.state()
	selected, selectedErr := store.selected.state()
	if err != nil || selectedErr != nil || state.SourceHash != store.meta.SourceHash || state.Anchor != store.meta.Anchor || state.Epoch != selected.Epoch ||
		state.LastCut != selected.LastCut || state.ClosedRoot != selected.ClosedRoot ||
		state.Active.Checkpoint != selected.Active.Checkpoint && state.Active.Checkpoint != selected.Active.Checkpoint+1 ||
		state.Active.Checkpoint == selected.Active.Checkpoint && state != selected ||
		state.Active.Checkpoint != selected.Active.Checkpoint && state.Active.Previous != selected.Active.ManifestHash {
		return errDagSegmentStore
	}
	meta := store.meta
	batch := new(leveldb.Batch)
	put := func(key string, raw []byte, manifest bool) error {
		old, err := store.db.Get([]byte(key), nil)
		if err == nil {
			if !bytes.Equal(old, raw) {
				return errDagSegmentStore
			}
			return nil
		}
		if err != leveldb.ErrNotFound {
			return errDagSegmentStore
		}
		meta.Bytes += uint64(len(raw))
		if manifest {
			meta.Manifests++
		} else {
			meta.Records++
		}
		if meta.Bytes > dagStoreMaxBytes || meta.Manifests > dagStoreMaxObjects || meta.Records > dagStoreMaxObjects {
			return errDagCandidateCredit
		}
		batch.Put([]byte(key), raw)
		return nil
	}
	for _, record := range execution.active.pending {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		if len(record.Raw) != record.WireBytes || record.WireBytes < 1 || record.WireBytes > DagMaxWire || hashHex(record.Raw) != record.WireHash {
			return errDagSegmentStore
		}
		if err = put("r/"+record.WireHash, record.Raw, false); err != nil {
			return err
		}
	}
	if err = put("m/"+execution.active.Commitment.ManifestHash, canonical(execution.active.Manifest), true); err != nil {
		return err
	}
	batch.Put([]byte("meta"), canonical(meta))
	if err = store.syncWrite(batch); err != nil {
		return err
	}
	store.meta = meta
	return nil
}

func (store *dagSegmentStore) stageCut(ctx context.Context, current *dagSegmentedExecution) error {
	store.mu.Lock()
	currentHash, err := segmentStateHash(current)
	selectedHash, selectedErr := segmentStateHash(store.selected)
	if store.db == nil || store.failed || err != nil || selectedErr != nil || currentHash != selectedHash {
		store.mu.Unlock()
		return errDagSegmentStore
	}
	if store.ready != nil && store.ready.replay.plan.matches(current) == nil {
		store.mu.Unlock()
		return nil
	}
	store.mu.Unlock()
	receipt, err := persistDagHistorySegment(ctx, store.root, current)
	if err != nil {
		return err
	}
	store.mu.Lock()
	defer store.mu.Unlock()
	selectedHash, err = segmentStateHash(store.selected)
	if store.db == nil || store.failed || err != nil || selectedHash != currentHash {
		return errDagSegmentStore
	}
	store.ready = receipt
	return nil
}

func (store *dagSegmentStore) commitHistory(ctx context.Context, history []State, execution *dagSegmentedExecution) error {
	store.mu.Lock()
	defer store.mu.Unlock()
	if ctx.Err() != nil {
		return ctx.Err()
	}
	if store.db == nil || store.failed || execution == nil || len(history) < 1 || len(history) > HistoryLimit {
		return errDagSegmentStore
	}
	state, err := execution.state()
	selected, selectedErr := store.selected.state()
	if err != nil || selectedErr != nil || history[len(history)-1].DAGSegmented == nil || *history[len(history)-1].DAGSegmented != state ||
		state.Anchor != store.meta.Anchor || state.SourceHash != store.meta.SourceHash {
		return errDagSegmentStore
	}
	cut := state.Epoch == selected.Epoch+1
	if cut {
		if store.ready == nil || store.ready.replay.plan.matches(store.selected) != nil {
			return errDagSegmentStore
		}
		expected, err := store.ready.successor(store.selected)
		if err != nil {
			return err
		}
		expectedState, _ := expected.state()
		if state != expectedState {
			return errDagSegmentStore
		}
	} else if state.Epoch != selected.Epoch ||
		state.Active.Checkpoint == selected.Active.Checkpoint && state != selected ||
		state.Active.Checkpoint != selected.Active.Checkpoint && (state.Active.Checkpoint != selected.Active.Checkpoint+1 || state.Active.Previous != selected.Active.ManifestHash) {
		return errDagSegmentStore
	}
	raw := canonical(persisted{GenesisHash: store.meta.Anchor, History: history, Schema: "gg.native.public-history.v3"})
	if len(raw) > dagHistoryMaxBytes {
		return errDagSegmentStore
	}
	keep := map[string]bool{}
	for _, manifest := range execution.manifests {
		keep["m/"+dagDigest("GG-DAG-CHECKPOINT-MANIFEST-v1\x00", manifest)] = true
	}
	keep["m/"+execution.startManifest] = true
	err = execution.active.visitOrderPrefix(execution.active.orderCount(), func(leaf DagOrderLeaf) error {
		record, found, err := execution.active.historyRecord(leaf.Hash)
		if err != nil || !found {
			return errDagSegmentStore
		}
		keep["r/"+record.WireHash] = true
		return nil
	})
	if err != nil {
		return err
	}
	batch := new(leveldb.Batch)
	if cut {
		reference := dagSegmentArchiveReference{ArchiveHash: store.ready.replay.archiveHash, Cut: state.LastCut, Epoch: selected.Epoch, Schema: "gg.dag.segment-reference.v1"}
		if store.ready.replay.index == nil || store.ready.replay.index.ArchiveHash != reference.ArchiveHash || store.stageClosedIndex(batch, store.ready.replay.index, store.selected.closed) != nil {
			return errDagSegmentStore
		}
		if found, err := store.db.Has([]byte(segmentArchiveReferenceKey(selected.Epoch)), nil); err != nil || found {
			return errDagSegmentStore
		}
		if found, err := store.db.Has([]byte("m/"+execution.startManifest), nil); err != nil || found {
			return errDagSegmentStore
		}
		batch.Put([]byte(segmentArchiveReferenceKey(selected.Epoch)), canonical(reference))
		batch.Put([]byte("m/"+execution.startManifest), canonical(execution.active.Manifest))
	}
	meta := dagSegmentStoreMeta{Anchor: store.meta.Anchor, Schema: store.meta.Schema, SourceHash: store.meta.SourceHash}
	for _, prefix := range []string{"r/", "m/"} {
		iter := store.db.NewIterator(util.BytesPrefix([]byte(prefix)), nil)
		for iter.Next() {
			key := string(iter.Key())
			if !keep[key] {
				batch.Delete(append([]byte(nil), iter.Key()...))
				continue
			}
			delete(keep, key)
			meta.Bytes += uint64(len(iter.Value()))
			if prefix == "r/" {
				meta.Records++
			} else {
				meta.Manifests++
			}
		}
		iterErr := iter.Error()
		iter.Release()
		if iterErr != nil {
			return errDagSegmentStore
		}
	}
	if cut {
		delete(keep, "m/"+execution.startManifest)
		meta.Manifests++
		meta.Bytes += uint64(len(canonical(execution.active.Manifest)))
	}
	if len(keep) != 0 || meta.Bytes > dagStoreMaxBytes {
		return errDagSegmentStore
	}
	batch.Put([]byte("history"), raw)
	batch.Put([]byte("meta"), canonical(meta))
	var snapshot *dagSegmentProofView
	present := false
	for _, view := range store.proofViews {
		present = present || view.state == state
	}
	if !present {
		value, err := segmentProofView(execution)
		if err != nil {
			return err
		}
		snapshot = &value
	}
	if err = store.syncWrite(batch); err != nil {
		return err
	}
	store.meta, store.selected = meta, store.view(execution)
	if snapshot != nil {
		store.retainProofView(*snapshot)
	}
	if cut {
		store.ready = nil
		store.closedEntries++
	}
	return nil
}
