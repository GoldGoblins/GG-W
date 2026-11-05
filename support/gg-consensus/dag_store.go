//go:build !js

package main

// Public DAG payload and the native application's history share one LevelDB.
// Proposal-ready payloads/manifests commit synchronously before acceptance;
// application commit atomically selects its exact already-persisted manifest.
// Existing databases are never recreated, repaired or recovered permissively.
import (
	"bytes"
	"context"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"

	"github.com/syndtr/goleveldb/leveldb"
	"github.com/syndtr/goleveldb/leveldb/opt"
)

const dagStoreMaxBytes uint64 = 640 * 1024 * 1024
const dagStoreMaxObjects = 8192
const dagManifestMaxBytes = 16 * 1024
const dagHistoryMaxBytes = 2 * 1024 * 1024

type dagStoreMeta struct {
	Bytes             uint64 `json:"bytes"`
	GenesisHash       string `json:"genesis_hash"`
	Manifests         int    `json:"manifests"`
	Records           int    `json:"records"`
	Schema            string `json:"schema"`
	SourceHash        string `json:"source_hash"`
	PublicIndex       int    `json:"public_index,omitempty"`
	HistoryIndex      int    `json:"history_index,omitempty"`
	HistoryRoot       string `json:"history_root,omitempty"`
	HistoryBytes      uint64 `json:"history_bytes,omitempty"`
	HistoryNodes      int    `json:"history_nodes,omitempty"`
	SelectionIndex    int    `json:"selection_index,omitempty"`
	SelectedBytes     uint64 `json:"selected_bytes,omitempty"`
	SelectedRecords   int    `json:"selected_records,omitempty"`
	SelectedManifests int    `json:"selected_manifests,omitempty"`
}

type dagStore struct {
	mu                  sync.Mutex
	db                  *leveldb.DB
	source              DagSource
	anchor              string
	meta                dagStoreMeta
	failed              bool
	historyDB           *leveldb.DB  // immutable reference, lifetime guarded below
	metadataLife        sync.RWMutex // drains metadata Get calls before DB.Close
	metadataClosed      atomic.Bool
	metadataCache       dagMetadataCache
	metadataFault       atomic.Bool
	metadataPersisted   atomic.Bool
	replayedMetadata    *dagMetadataReplay
	beforeHistoryRead   func(string) // owned hook, set before concurrent readers
	candidates          map[string]uint64
	selected            DagCommitment
	prefix              *dagCanonicalPrefix // bounded, published only after Sync / complete replay
	retentionReady      bool
	readers             sync.WaitGroup
	activeReaders       int
	beforePublicRead    func(string) // owned test hook, called outside consensus/store locks
	payloadReaders      int
	payloadCache        dagPayloadCache
	beforePayloadRead   func(string)                     // owned test hook, called outside all locks
	beforeSelectionRead func(string)                     // owned snapshot-reader hook, outside all locks
	openReplayScratch   func() (dagReplayScratch, error) // owned IO-failure hook, set before startup
	replayWorkPath      string
	// Test injection wraps the real atomic synchronous operation, including
	// the ambiguous case where durable completion precedes an error return.
	write func(*leveldb.Batch) error
}

func newDagStore(source DagSource, anchor, root string, create bool) (*dagStore, error) {
	return openDagStore(source, anchor, root, create, false)
}

// Portable archive export opens an already indexed public database read-only.
// LevelDB's real storage lease excludes a running writer; no migration occurs.
func openDagStore(source DagSource, anchor, root string, create, readOnly bool) (*dagStore, error) {
	if create && readOnly {
		return nil, errors.New("GG_DAG_STORE_CONTEXT")
	}
	if validateDagSource(source) != nil || !pubPattern.MatchString(anchor) || !filepath.IsAbs(root) {
		return nil, errors.New("GG_DAG_STORE_CONTEXT")
	}
	path := filepath.Join(root, "gg-dag-public.leveldb")
	// Bootstrap roots are controlled by the owner; do not follow a replaced
	// store directory or create a missing existing database on recovery.
	if info, err := os.Lstat(path); err == nil {
		if create || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
			return nil, errors.New("GG_DAG_STORE_PATH")
		}
	} else if !os.IsNotExist(err) || !create {
		return nil, errors.New("GG_DAG_STORE_MISSING")
	}
	db, err := leveldb.OpenFile(path, &opt.Options{ErrorIfExist: create, ErrorIfMissing: !create, Strict: opt.StrictAll,
		ReadOnly: readOnly, Compression: opt.NoCompression, WriteBuffer: 4 * 1024 * 1024, BlockCacheCapacity: 4 * 1024 * 1024, OpenFilesCacheCapacity: 32})
	if err != nil {
		return nil, errors.New("GG_DAG_STORE_OPEN")
	}
	store := &dagStore{db: db, source: source, anchor: anchor, candidates: map[string]uint64{}, retentionReady: create,
		replayWorkPath: filepath.Join(root, "gg-dag-replay-work")}
	store.historyDB = db
	store.write = func(batch *leveldb.Batch) error {
		return db.Write(batch, &opt.WriteOptions{Sync: true, NoWriteMerge: true})
	}
	valid := false
	defer func() {
		if !valid {
			_ = db.Close()
		}
	}()
	if create {
		store.meta = dagStoreMeta{GenesisHash: anchor, Schema: "gg.dag.store.v1", SourceHash: dagDigest("GG-DAG-CONSENSUS-SOURCE-v1\x00", source)}
		store.meta.HistoryIndex = 1
		store.meta.HistoryRoot = DagZero
		store.meta.SelectionIndex = 1
		batch := new(leveldb.Batch)
		batch.Put([]byte("meta"), canonical(store.meta))
		if store.write(batch) != nil {
			return nil, errors.New("GG_DAG_STORE_WRITE_FAILED")
		}
	} else {
		raw, err := db.Get([]byte("meta"), nil)
		if err != nil || len(raw) > 1024 || decodeStrict(raw, &store.meta) != nil || !bytes.Equal(raw, canonical(store.meta)) ||
			store.meta.Schema != "gg.dag.store.v1" || store.meta.GenesisHash != anchor ||
			store.meta.SourceHash != dagDigest("GG-DAG-CONSENSUS-SOURCE-v1\x00", source) ||
			store.meta.Bytes > dagStoreMaxBytes || store.meta.Records < 0 || store.meta.Records > dagStoreMaxObjects ||
			store.meta.Manifests < 0 || store.meta.Manifests > dagStoreMaxObjects || store.meta.PublicIndex < 0 || store.meta.PublicIndex > 2 || !validMetadataMeta(store.meta) || !validSelectionMeta(store.meta) {
			return nil, errors.New("GG_DAG_STORE_METADATA")
		}
		if store.checkContents() != nil {
			return nil, errors.New("GG_DAG_STORE_CONTENTS")
		}
	}
	store.metadataPersisted.Store(store.meta.HistoryIndex == 1)
	valid = true
	return store, nil
}

func (store *dagStore) validManifest(raw []byte, identifier string) (DagManifest, error) {
	return checkedDagManifest(raw, identifier, store.anchor, store.meta.SourceHash)
}

func checkedDagManifest(raw []byte, identifier, anchor, sourceHash string) (DagManifest, error) {
	var manifest DagManifest
	if len(raw) == 0 || len(raw) > dagManifestMaxBytes || decodeStrict(raw, &manifest) != nil || !bytes.Equal(raw, canonical(manifest)) ||
		dagDigest("GG-DAG-CHECKPOINT-MANIFEST-v1\x00", manifest) != identifier || manifest.Schema != "gg.dag.execution.manifest.v1" ||
		manifest.GenesisHash != anchor || manifest.SourceHash != sourceHash || !pubPattern.MatchString(manifest.Previous) ||
		manifest.Checkpoint > DagMaxRecords || manifest.Blocks == nil || len(manifest.Blocks) > DagMaxBatchBlocks {
		return manifest, errors.New("GG_DAG_STORE_MANIFEST")
	}
	if manifest.Checkpoint == 0 {
		if len(manifest.Blocks) != 0 || manifest.Previous != DagZero || manifest.TimeNs != "0" {
			return manifest, errors.New("GG_DAG_STORE_MANIFEST")
		}
	} else {
		if _, ok := dagDecimalNs(manifest.TimeNs); !ok || len(manifest.Blocks) == 0 {
			return manifest, errors.New("GG_DAG_STORE_MANIFEST")
		}
	}
	seen := map[string]bool{}
	for _, hash := range manifest.Blocks {
		if !pubPattern.MatchString(hash) || seen[hash] {
			return manifest, errors.New("GG_DAG_STORE_MANIFEST")
		}
		seen[hash] = true
	}
	return manifest, nil
}

func (store *dagStore) checkContents() error {
	meta := store.meta
	meta.Bytes = 0
	meta.Records = 0
	meta.Manifests = 0
	meta.HistoryBytes = 0
	meta.HistoryNodes = 0
	meta.SelectedBytes = 0
	meta.SelectedRecords = 0
	meta.SelectedManifests = 0
	iterator := store.db.NewIterator(nil, nil)
	defer iterator.Release()
	var candidateBytes uint64
	candidateRecords, candidateManifests := 0, 0
	rememberCandidate := func(key string, size uint64) error {
		candidateBytes += size
		if strings.HasPrefix(key, "m/") {
			candidateManifests++
		} else {
			candidateRecords++
		}
		if store.meta.SelectionIndex == 1 && (candidateRecords > dagCandidateCatalogRecords || candidateManifests > dagCandidateCatalogManifests || candidateBytes > dagCandidateMaxBytes+dagFinalizeReserveBytes) {
			return errDagHistoryUnavailable
		}
		store.candidates[key] = size
		return nil
	}
	for iterator.Next() {
		key := string(iterator.Key())
		raw := iterator.Value()
		switch {
		case key == "meta":
		case key == "history":
			if len(raw) == 0 || len(raw) > dagHistoryMaxBytes {
				return errors.New("GG_DAG_STORE_HISTORY")
			}
		case strings.HasPrefix(key, "pub/"):
			if store.meta.PublicIndex == 0 {
				return errors.New("GG_DAG_PUBLIC_INDEX_UNEXPECTED")
			}
		case strings.HasPrefix(key, "sel/"):
			var size uint64
			if store.meta.SelectionIndex != 1 || len(raw) == 0 || len(raw) > 16 || decodeStrict(raw, &size) != nil || !bytes.Equal(raw, canonical(size)) || !validSelectionObject(key[4:], size) {
				return errDagHistoryUnavailable
			}
			exists, err := store.db.Has([]byte(key[4:]), nil)
			if err != nil || !exists {
				return errDagHistoryUnavailable
			}
			meta.SelectedBytes += size
			if strings.HasPrefix(key, "sel/m/") {
				meta.SelectedManifests++
			} else {
				meta.SelectedRecords++
			}
		case strings.HasPrefix(key, "hx/") && len(key) == 67:
			if store.meta.HistoryIndex != 1 {
				return errDagHistoryUnavailable
			}
			if _, err := decodeHistoryNode(key[3:], raw); err != nil {
				return err
			}
			meta.HistoryBytes += uint64(len(key) + len(raw))
			meta.HistoryNodes++
			if meta.HistoryBytes > dagMetadataMaxBytes || meta.HistoryNodes > dagMetadataMaxNodes {
				return errDagHistoryUnavailable
			}
		case strings.HasPrefix(key, "r/") && len(key) == 66:
			if len(raw) == 0 || len(raw) > DagMaxWire || !pubPattern.MatchString(key[2:]) || hashHex(raw) != key[2:] {
				return errors.New("GG_DAG_STORE_RECORD")
			}
			meta.Records++
			meta.Bytes += uint64(len(raw))
			if store.meta.SelectionIndex == 0 {
				if err := rememberCandidate(key, uint64(len(raw))); err != nil {
					return err
				}
			} else {
				size, selected, err := readSelection(store.db, key)
				if err != nil || selected && size != uint64(len(raw)) {
					return errDagHistoryUnavailable
				}
				if !selected {
					if err := rememberCandidate(key, uint64(len(raw))); err != nil {
						return err
					}
				}
			}
		case strings.HasPrefix(key, "m/") && len(key) == 66:
			if _, err := store.validManifest(raw, key[2:]); err != nil {
				return err
			}
			meta.Manifests++
			meta.Bytes += uint64(len(raw))
			if store.meta.SelectionIndex == 0 {
				if err := rememberCandidate(key, uint64(len(raw))); err != nil {
					return err
				}
			} else {
				size, selected, err := readSelection(store.db, key)
				if err != nil || selected && size != uint64(len(raw)) {
					return errDagHistoryUnavailable
				}
				if !selected {
					if err := rememberCandidate(key, uint64(len(raw))); err != nil {
						return err
					}
				}
			}
		default:
			return errors.New("GG_DAG_STORE_KEY")
		}
		if meta.Bytes > dagStoreMaxBytes || meta.Records > dagStoreMaxObjects || meta.Manifests > dagStoreMaxObjects {
			return errors.New("GG_DAG_STORE_LIMIT")
		}
	}
	if iterator.Error() != nil || meta != store.meta {
		return errors.New("GG_DAG_STORE_METADATA")
	}
	if store.meta.SelectionIndex == 1 && store.candidateCacheBound() != nil {
		return errDagHistoryUnavailable
	}
	if store.meta.PublicIndex != 0 {
		return store.checkPublicContents()
	}
	return nil
}

func (store *dagStore) syncWrite(batch *leveldb.Batch) error {
	if store.metadataFault.Load() {
		return errDagHistoryUnavailable
	}
	if store.db == nil || store.failed {
		return errors.New("GG_DAG_STORE_FAULT")
	}
	if err := store.write(batch); err != nil {
		store.failed = true
		return errors.New("GG_DAG_STORE_WRITE_FAILED")
	}
	return nil
}

func (store *dagStore) health() error {
	if store.metadataFault.Load() {
		return errDagHistoryUnavailable
	}
	store.mu.Lock()
	defer store.mu.Unlock()
	if store.db == nil || store.failed {
		return errors.New("GG_DAG_STORE_FAULT")
	}
	return nil
}

func (store *dagStore) prepare(execution *DagExecution) error {
	return store.prepareCandidate(execution, false, false)
}

func (store *dagStore) prepareProposal(execution *DagExecution) error {
	store.mu.Lock()
	defer store.mu.Unlock()
	err := store.prepareCandidateLocked(execution, false, false)
	if errors.Is(err, errDagCandidateCredit) {
		// ProcessProposal validity MUST depend on committed state and block,
		// never a validator's different cache arrival history. Roll the cache
		// atomically, then Sync this fully validated payload before accepting.
		return store.prepareCandidateLocked(execution, false, true)
	}
	return err
}

func (store *dagStore) prepareFinalized(execution *DagExecution) error {
	return store.prepareCandidate(execution, true, true)
}

func (store *dagStore) prepareCandidate(execution *DagExecution, finalized, retire bool) error {
	store.mu.Lock()
	defer store.mu.Unlock()
	return store.prepareCandidateLocked(execution, finalized, retire)
}

func (store *dagStore) prepareCandidateLocked(execution *DagExecution, finalized, retire bool) error {
	if store.metadataFault.Load() {
		return errDagHistoryUnavailable
	}
	if store.db == nil || store.failed {
		return errors.New("GG_DAG_STORE_FAULT")
	}
	if !store.retentionReady {
		return errors.New("GG_DAG_STORE_REPLAY_REQUIRED")
	}
	if execution == nil || execution.Anchor != store.anchor || dagDigest("GG-DAG-CONSENSUS-SOURCE-v1\x00", execution.Source) != store.meta.SourceHash ||
		validateDagCommitment(execution.Commitment, store.source, store.anchor) != nil {
		return errors.New("GG_DAG_STORE_UNVERIFIED")
	}
	transition, err := store.validateTransition(execution)
	if err != nil {
		return err
	}
	if retire && !transition.selected {
		if store.metadataFault.Load() {
			return errDagHistoryUnavailable
		}
		return errors.New("GG_DAG_STORE_SELECTION")
	}
	rawManifest := canonical(execution.Manifest)
	identifier := execution.Commitment.ManifestHash
	if _, err := store.validManifest(rawManifest, identifier); err != nil {
		return err
	}
	if execution.Manifest.Checkpoint > 0 {
		raw, err := store.db.Get([]byte("m/"+execution.Manifest.Previous), nil)
		if err != nil {
			return errors.New("GG_DAG_STORE_PARENT_REQUIRED")
		}
		parent, err := store.validManifest(raw, execution.Manifest.Previous)
		if err != nil || parent.Checkpoint+1 != execution.Manifest.Checkpoint {
			return errors.New("GG_DAG_STORE_PARENT_REQUIRED")
		}
	}
	batch := new(leveldb.Batch)
	meta := store.meta
	retired := []string{}
	if retire {
		var err error
		meta, retired, err = store.retireCandidates(batch, meta, retentionKeys(execution))
		if err != nil {
			return err
		}
	}
	added := map[string]uint64{}
	add := func(key string, raw []byte, manifest bool) error {
		previous, err := store.db.Get([]byte(key), nil)
		if err == nil {
			if !bytes.Equal(previous, raw) {
				return errors.New("GG_DAG_STORE_CONTENT_CHANGED")
			}
			if size, known := store.candidates[key]; known {
				if size != uint64(len(raw)) {
					return errDagHistoryUnavailable
				}
			} else {
				size, selected, err := store.selectedObject(key)
				if err != nil || !selected || size != uint64(len(raw)) {
					return errDagHistoryUnavailable
				}
			}
			return nil
		}
		if err != leveldb.ErrNotFound {
			return errors.New("GG_DAG_STORE_READ")
		}
		if uint64(len(raw)) > dagStoreMaxBytes-meta.Bytes {
			if !finalized {
				return errDagCandidateCredit
			}
			return errors.New("GG_DAG_STORE_LIMIT")
		}
		meta.Bytes += uint64(len(raw))
		if manifest {
			meta.Manifests++
		} else {
			meta.Records++
		}
		if meta.Manifests > dagStoreMaxObjects || meta.Records > dagStoreMaxObjects {
			if !finalized {
				return errDagCandidateCredit
			}
			return errors.New("GG_DAG_STORE_LIMIT")
		}
		batch.Put([]byte(key), raw)
		added[key] = uint64(len(raw))
		return nil
	}
	// Different valid envelope signatures over one body have different wire
	// identities. Uncommitted cache arrival order must not affect consensus.
	wanted := map[string]bool{}
	for _, wireHash := range execution.Manifest.Blocks {
		wanted[wireHash] = true
	}
	for _, record := range execution.pending {
		if wanted[record.WireHash] {
			if record.Raw == nil {
				size, selected, err := store.selectedObject("r/" + record.WireHash)
				if err != nil {
					return err
				}
				if !selected || size != uint64(record.WireBytes) {
					return errors.New("GG_DAG_STORE_PAYLOAD_REQUIRED")
				}
				delete(wanted, record.WireHash)
				continue
			}
			if hashHex(record.Raw) != record.WireHash {
				return errors.New("GG_DAG_STORE_RECORD")
			}
			if err := add("r/"+record.WireHash, record.Raw, false); err != nil {
				return err
			}
			delete(wanted, record.WireHash)
		}
	}
	for hash := range wanted {
		_, selected, err := store.selectedObject("r/" + hash)
		if err != nil {
			return err
		}
		if selected {
			delete(wanted, hash)
		}
	}
	if len(wanted) != 0 {
		return errors.New("GG_DAG_STORE_PAYLOAD_REQUIRED")
	}
	if err := add("m/"+identifier, rawManifest, true); err != nil {
		return err
	}
	if meta == store.meta && len(retired) == 0 {
		return nil
	}
	if !finalized {
		// Retired entries are absent from this prospective batch. Count the
		// kept current payload, rather than the pre-rollover cache contents.
		credit := store
		if retire {
			credit = &dagStore{candidates: map[string]uint64{}}
			keep := retentionKeys(execution)
			for key, size := range store.candidates {
				if keep[key] {
					credit.candidates[key] = size
				}
			}
		}
		if err := credit.candidateCredit(meta, added); err != nil {
			return err
		}
	}
	batch.Put([]byte("meta"), canonical(meta))
	if err := store.syncWrite(batch); err != nil {
		return err
	}
	store.meta = meta
	for _, key := range retired {
		delete(store.candidates, key)
	}
	for key, size := range added {
		store.candidates[key] = size
	}
	return nil
}

func (store *dagStore) load(expected DagCommitment) (*DagExecution, error) {
	// Unselected proposals have authenticated payloads but no committed index.
	return store.replayExecution(expected, nil, false)
}

func (store *dagStore) replay(expected DagCommitment, observe func(*DagExecution)) (*DagExecution, error) {
	return store.replayExecution(expected, observe, true)
}
func (store *dagStore) replayExecution(expected DagCommitment, observe func(*DagExecution), verifyMetadata bool) (*DagExecution, error) {
	store.mu.Lock()
	defer store.mu.Unlock()
	if store.db == nil || store.failed {
		return nil, errors.New("GG_DAG_STORE_FAULT")
	}
	if validateDagCommitment(expected, store.source, store.anchor) != nil {
		return nil, errors.New("GG_DAG_STORE_CHECKPOINT")
	}
	execution, err := newDagExecution(store.source, store.anchor)
	if err != nil {
		return nil, err
	}
	metadata := &dagMetadataReplay{root: DagZero, seen: map[string]bool{}, legacy: map[string][]byte{}}
	store.replayedMetadata = nil
	chain := []DagManifest{}
	current := expected.ManifestHash
	seen := map[string]bool{}
	for {
		if seen[current] || len(chain) > DagMaxRecords {
			return nil, errors.New("GG_DAG_STORE_CHAIN")
		}
		seen[current] = true
		raw, err := store.db.Get([]byte("m/"+current), nil)
		if err != nil {
			return nil, errors.New("GG_DAG_STORE_MANIFEST_MISSING")
		}
		manifest, err := store.validManifest(raw, current)
		if err != nil {
			return nil, err
		}
		if manifest.Checkpoint == 0 {
			if current != execution.Commitment.ManifestHash {
				return nil, errors.New("GG_DAG_STORE_GENESIS")
			}
			break
		}
		chain = append(chain, manifest)
		current = manifest.Previous
	}
	if observe != nil {
		observe(execution)
	}
	for i := len(chain) - 1; i >= 0; i-- {
		manifest := chain[i]
		execution, err = store.replayManifest(execution, manifest)
		if err != nil {
			return nil, err
		}
		if observe != nil {
			observe(execution)
		}
		if verifyMetadata {
			if err := store.observeHistory(execution, metadata); err != nil {
				return nil, err
			}
			execution = store.archiveExecution(execution)
		} else {
			copy := *execution
			copy.pending = map[string]dagRecord{}
			copy.payloadReader = store.readPayload
			execution = &copy
		}
	}
	if !bytes.Equal(canonical(execution.Commitment), canonical(expected)) {
		return nil, errors.New("GG_DAG_STORE_EXECUTION_MISMATCH")
	}
	if verifyMetadata {
		store.replayedMetadata = metadata
	}
	return execution, nil
}

func (store *dagStore) history() ([]byte, error) {
	store.mu.Lock()
	defer store.mu.Unlock()
	if store.db == nil || store.failed {
		return nil, errors.New("GG_DAG_STORE_FAULT")
	}
	raw, err := store.db.Get([]byte("history"), nil)
	if err != nil || len(raw) == 0 || len(raw) > dagHistoryMaxBytes {
		return nil, errors.New("GG_DAG_STORE_HISTORY_MISSING_OR_INVALID")
	}
	return raw, nil
}

func (store *dagStore) commit(raw []byte) error {
	store.mu.Lock()
	defer store.mu.Unlock()
	if len(raw) == 0 || len(raw) > dagHistoryMaxBytes {
		return errors.New("GG_DAG_STORE_HISTORY_SIZE")
	}
	batch := new(leveldb.Batch)
	batch.Put([]byte("history"), raw)
	return store.syncWrite(batch)
}

func (store *dagStore) close() error {
	store.mu.Lock()
	if store.db == nil {
		store.mu.Unlock()
		return nil
	}
	db := store.db
	store.metadataClosed.Store(true)
	store.db = nil
	store.mu.Unlock()
	store.readers.Wait()
	store.metadataLife.Lock()
	defer store.metadataLife.Unlock()
	store.payloadCache.clear()
	store.metadataCache.clear()
	return db.Close()
}

func newDagEnabledLedger(genesis Genesis, anchor, root string, create bool) (*Ledger, error) {
	return newDagEnabledLedgerContext(context.Background(), genesis, anchor, root, create)
}
func newDagEnabledLedgerContext(ctx context.Context, genesis Genesis, anchor, root string, create bool) (*Ledger, error) {
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	if genesis.FinancialDAG != nil {
		return newFinancialLedgerContext(ctx, genesis, anchor, root, create)
	}
	if genesis.DAGSegmented != nil {
		return newDagSegmentedLedger(genesis, anchor, root, create)
	}
	if genesis.DAG == nil || validateGenesis(genesis, anchor) != nil {
		return nil, errors.New("GG_DAG_LEDGER_GENESIS")
	}
	store, err := newDagStore(*genesis.DAG, anchor, root, create)
	if err != nil {
		return nil, err
	}
	valid := false
	defer func() {
		if !valid {
			_ = store.close()
		}
	}()
	execution, err := newDagExecution(*genesis.DAG, anchor)
	if err != nil {
		return nil, err
	}
	app := &Ledger{genesis: genesis, anchor: anchor, state: initialState(genesis, anchor), dag: execution, store: store, payloadSlots: make(chan struct{}, 2)}
	if create {
		app.history = []State{copyState(app.state)}
		if err = store.prepare(execution); err != nil {
			return nil, err
		}
		err = store.commitExecution(canonical(persisted{GenesisHash: anchor, History: app.history, Schema: "gg.native.public-history.v2"}), execution)
		if err != nil {
			return nil, err
		}
	} else {
		raw, err := store.history()
		if err != nil {
			return nil, err
		}
		var saved persisted
		if decodeStrict(raw, &saved) != nil || !bytes.Equal(raw, canonical(saved)) || saved.Schema != "gg.native.public-history.v2" ||
			saved.GenesisHash != anchor || len(saved.History) < 1 || len(saved.History) > HistoryLimit {
			return nil, errors.New("GG_DAG_LEDGER_HISTORY")
		}
		for i, state := range saved.History {
			if validateState(state, genesis, anchor) != nil {
				return nil, errors.New("GG_DAG_LEDGER_HISTORY_STATE")
			}
			if i > 0 {
				previous := saved.History[i-1]
				if state.Height != previous.Height+1 || state.DAG.Checkpoint < previous.DAG.Checkpoint || state.DAG.Checkpoint > previous.DAG.Checkpoint+1 {
					return nil, errors.New("GG_DAG_LEDGER_HISTORY_SEQUENCE")
				}
				if state.DAG.Checkpoint == previous.DAG.Checkpoint {
					if !bytes.Equal(canonical(state.DAG), canonical(previous.DAG)) {
						return nil, errors.New("GG_DAG_LEDGER_HISTORY_CHANGED")
					}
				} else if state.DAG.Previous != previous.DAG.ManifestHash || state.DAG.Blocks <= previous.DAG.Blocks || state.DAG.Transactions < previous.DAG.Transactions {
					return nil, errors.New("GG_DAG_LEDGER_HISTORY_LINK")
				}
			}
		}
		app.history = saved.History
		app.state = copyState(saved.History[len(saved.History)-1])
		if store.meta.PublicIndex == 2 && store.meta.HistoryIndex == 1 && store.meta.SelectionIndex == 1 {
			app.dag, err = store.replayIndexed(*app.state.DAG)
		} else {
			var snapshots []dagPublicSnapshot
			app.dag, err = store.replay(*app.state.DAG, func(value *DagExecution) { snapshots = append(snapshots, publicSnapshot(value)) })
			if err == nil {
				err = store.verifyOrMigratePublic(app.dag, snapshots)
			}
		}
		if err != nil {
			return nil, err
		}
	}
	app.dag = store.archiveExecution(app.dag)
	valid = true
	return app, nil
}

// Compile-time check: the native storage never leaks into the public verifier.
var _ dagPersistence = (*dagStore)(nil)
