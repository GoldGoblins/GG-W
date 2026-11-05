//go:build !js

package main

// Fully indexed startup still executes every original signed payload. Only
// disposable replay bookkeeping moves to disk; no execution snapshot is trusted.
import (
	"bytes"
	"encoding/base64"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/syndtr/goleveldb/leveldb"
	"github.com/syndtr/goleveldb/leveldb/opt"
	"github.com/syndtr/goleveldb/leveldb/storage"
)

const dagReplayWorkMaxBytes uint64 = 128 * 1024 * 1024
const dagReplayWorkBufferBytes = 1024 * 1024
const dagReplayWorkCacheBytes = 1024 * 1024
const dagReplayWorkMaxEntries = dagMetadataMaxNodes + DagMaxRecords + 1

var errDagReplayWork = errors.New("GG_DAG_REPLAY_WORK_UNAVAILABLE")

type dagReplayScratch interface {
	putManifest(uint64, string, []byte) error
	manifest(uint64) (string, []byte, error)
	firstMetadata(string) (bool, error)
	close() error
}

type dagReplayWork struct {
	directory, parent string
	db                *leveldb.DB
	bytes             uint64
	entries           int
	closed            bool
	closeError        error
	managed           bool
}

const dagReplayWorkOwner = "gg.dag.replay-work.v1\n"

// The native caller already owns the canonical DB's exclusive lock. One
// reserved workspace per profile prevents unbounded orphan directories after
// crashes. An unknown directory, link or live scratch lease is never removed.
func newDagReplayWorkAt(directory string) (dagReplayScratch, error) {
	if !filepath.IsAbs(directory) || filepath.Base(directory) != "gg-dag-replay-work" {
		return nil, errDagReplayWork
	}
	owner := filepath.Join(directory, "OWNER")
	if info, err := os.Lstat(directory); err == nil {
		if !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
			return nil, errDagReplayWork
		}
		entries, err := os.ReadDir(directory)
		if err != nil {
			return nil, errDagReplayWork
		}
		if len(entries) == 0 {
			if os.Remove(directory) != nil {
				return nil, errDagReplayWork
			}
		} else {
			info, err := os.Lstat(owner)
			if err != nil || !info.Mode().IsRegular() || info.Size() > int64(len(dagReplayWorkOwner)) {
				return nil, errDagReplayWork
			}
			raw, err := os.ReadFile(owner)
			if err != nil {
				return nil, errDagReplayWork
			}
			if string(raw) != dagReplayWorkOwner {
				// A crash while creating OWNER can leave only that incomplete
				// public marker. Remove these exact files nonrecursively.
				if len(entries) != 1 || entries[0].Name() != "OWNER" || !bytes.HasPrefix([]byte(dagReplayWorkOwner), raw) ||
					os.Remove(owner) != nil || os.Remove(directory) != nil {
					return nil, errDagReplayWork
				}
			} else {
				path := filepath.Join(directory, "work.leveldb")
				if info, err := os.Lstat(path); err == nil {
					if !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
						return nil, errDagReplayWork
					}
					// Acquire the storage lease without trusting/parsing a
					// possibly interrupted scratch database's manifest.
					lease, err := storage.OpenFile(path, false)
					if err != nil {
						return nil, errDagReplayWork
					}
					if lease.Close() != nil {
						return nil, errDagReplayWork
					}
				} else if !os.IsNotExist(err) {
					return nil, errDagReplayWork
				}
				if os.RemoveAll(directory) != nil {
					return nil, errDagReplayWork
				}
			}
		}
	} else if !os.IsNotExist(err) {
		return nil, errDagReplayWork
	}
	if os.Mkdir(directory, 0700) != nil {
		return nil, errDagReplayWork
	}
	file, err := os.OpenFile(owner, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if err != nil {
		_ = os.Remove(directory)
		return nil, errDagReplayWork
	}
	n, writeErr := file.Write([]byte(dagReplayWorkOwner))
	syncErr := file.Sync()
	closeErr := file.Close()
	if writeErr != nil || n != len(dagReplayWorkOwner) || syncErr != nil || closeErr != nil {
		_ = os.Remove(owner)
		_ = os.Remove(directory)
		return nil, errDagReplayWork
	}
	work := &dagReplayWork{directory: directory, parent: filepath.Dir(directory), managed: true}
	return work.open()
}

func newDagReplayWork() (dagReplayScratch, error) {
	directory, err := os.MkdirTemp("", "gg-dag-replay-")
	if err != nil {
		return nil, errDagReplayWork
	}
	if !filepath.IsAbs(directory) {
		_ = os.Remove(directory) // exact newly created empty directory only
		return nil, errDagReplayWork
	}
	work := &dagReplayWork{directory: directory, parent: filepath.Dir(directory)}
	return work.open()
}

func (work *dagReplayWork) open() (dagReplayScratch, error) {
	var err error
	work.db, err = leveldb.OpenFile(filepath.Join(work.directory, "work.leveldb"), &opt.Options{
		ErrorIfExist: true, Strict: opt.StrictAll, Compression: opt.NoCompression,
		WriteBuffer: dagReplayWorkBufferBytes, BlockCacheCapacity: dagReplayWorkCacheBytes, OpenFilesCacheCapacity: 8})
	if err != nil {
		_ = work.close()
		return nil, errDagReplayWork
	}
	return work, nil
}

func replayManifestKey(checkpoint uint64) string { return fmt.Sprintf("m/%08d", checkpoint) }

func (work *dagReplayWork) insert(key string, raw []byte) error {
	if work.closed || work.db == nil || len(raw) == 0 || len(raw) > dagManifestMaxBytes+64 ||
		work.entries >= dagReplayWorkMaxEntries || work.bytes+uint64(len(key)+len(raw)) > dagReplayWorkMaxBytes {
		return errDagReplayWork
	}
	if found, err := work.db.Has([]byte(key), nil); err != nil || found {
		return errDagReplayWork
	}
	// Scratch is never recovered or used as durable authority. An uncertain
	// temporary write outcome aborts startup instead of publishing any state.
	if work.db.Put([]byte(key), raw, &opt.WriteOptions{NoWriteMerge: true}) != nil {
		return errDagReplayWork
	}
	work.bytes += uint64(len(key) + len(raw))
	work.entries++
	return nil
}

func (work *dagReplayWork) putManifest(checkpoint uint64, hash string, raw []byte) error {
	if checkpoint > DagMaxRecords || !pubPattern.MatchString(hash) || len(raw) == 0 || len(raw) > dagManifestMaxBytes {
		return errDagReplayWork
	}
	value := make([]byte, 64+len(raw))
	copy(value, hash)
	copy(value[64:], raw)
	return work.insert(replayManifestKey(checkpoint), value)
}

func (work *dagReplayWork) manifest(checkpoint uint64) (string, []byte, error) {
	if work.closed || work.db == nil || checkpoint > DagMaxRecords {
		return "", nil, errDagReplayWork
	}
	raw, err := work.db.Get([]byte(replayManifestKey(checkpoint)), nil)
	if err != nil || len(raw) <= 64 || len(raw) > dagManifestMaxBytes+64 || !pubPattern.Match(raw[:64]) {
		return "", nil, errDagReplayWork
	}
	return string(raw[:64]), raw[64:], nil
}

func (work *dagReplayWork) firstMetadata(hash string) (bool, error) {
	if work.closed || work.db == nil || !pubPattern.MatchString(hash) {
		return false, errDagReplayWork
	}
	key := "h/" + hash
	raw, err := work.db.Get([]byte(key), nil)
	if err == nil {
		if !bytes.Equal(raw, []byte{1}) {
			return false, errDagReplayWork
		}
		return false, nil
	}
	if err != leveldb.ErrNotFound {
		return false, errDagReplayWork
	}
	if err := work.insert(key, []byte{1}); err != nil {
		return false, err
	}
	return true, nil
}

func (work *dagReplayWork) close() error {
	if work.closed {
		return work.closeError
	}
	work.closed = true
	if work.db != nil {
		if work.db.Close() != nil {
			work.closeError = errDagReplayWork
		}
		work.db = nil
	}
	// Delete only the exact owned temporary child, never a replacement link or
	// a computed ancestor. This contains public work data, never private keys.
	info, err := os.Lstat(work.directory)
	validName := work.managed && filepath.Base(work.directory) == "gg-dag-replay-work" ||
		!work.managed && strings.HasPrefix(filepath.Base(work.directory), "gg-dag-replay-")
	if err != nil || !filepath.IsAbs(work.directory) || filepath.Dir(work.directory) != work.parent ||
		!validName || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		work.closeError = errDagReplayWork
		return work.closeError
	}
	if os.RemoveAll(work.directory) != nil {
		work.closeError = errDagReplayWork
	}
	return work.closeError
}

// Bound total raw bytes BEFORE retaining base64 copies. A malformed manifest
// cannot force 128 individually maximum-sized payloads into one replay batch.
func (store *dagStore) replayManifest(base *DagExecution, manifest DagManifest) (*DagExecution, error) {
	return replayDagManifest(base, manifest, func(hash string) ([]byte, error) { return store.db.Get([]byte("r/"+hash), nil) })
}

// The portable archive and indexed database use the SAME signed replay path.
// Only the bounded byte provider differs; no state snapshot bypass is added.
func replayDagManifest(base *DagExecution, manifest DagManifest, read func(string) ([]byte, error)) (*DagExecution, error) {
	if len(manifest.Blocks) < 1 || len(manifest.Blocks) > DagMaxBatchBlocks {
		return nil, errors.New("GG_DAG_STORE_PROTOCOL_REPLAY")
	}
	encoded := make([]string, len(manifest.Blocks))
	size := 0
	for i, hash := range manifest.Blocks {
		wire, err := read(hash)
		if err != nil || len(wire) == 0 || len(wire) > DagMaxWire || hashHex(wire) != hash {
			return nil, errors.New("GG_DAG_STORE_PAYLOAD_MISSING_OR_CHANGED")
		}
		size += len(wire)
		if size > DagMaxWire {
			return nil, errors.New("GG_DAG_BATCH_SIZE")
		}
		encoded[i] = base64.StdEncoding.EncodeToString(wire)
	}
	ns, _ := dagDecimalNs(manifest.TimeNs)
	batch := DagBatch{Blocks: encoded, GenesisHash: base.Anchor, Previous: base.Commitment.ManifestHash,
		Schema: "gg.dag.checkpoint.batch.v1", Sequence: manifest.Checkpoint}
	next, err := applyDagBatch(base, canonical(batch), ns)
	if err != nil || !bytes.Equal(canonical(next.Manifest), canonical(manifest)) {
		return nil, errors.New("GG_DAG_STORE_PROTOCOL_REPLAY")
	}
	return next, nil
}

type dagIndexedReplayCheck struct {
	store         *dagStore
	work          dagReplayScratch
	publicBytes   uint64
	metadataBytes uint64
	metadataNodes int
	selected      dagStoreMeta
}

func (check *dagIndexedReplayCheck) publicEntry(key string, value any) error {
	raw := canonical(value)
	actual, err := check.store.db.Get([]byte(key), nil)
	if err != nil || len(raw) > dagPublicValueMax || !bytes.Equal(actual, raw) {
		return errors.New("GG_DAG_PUBLIC_REPLAY_MISMATCH")
	}
	check.publicBytes += publicEntryBytes(key, raw)
	if check.publicBytes > dagPublicMaxBytes {
		return errors.New("GG_DAG_PUBLIC_LIMIT")
	}
	return nil
}

func (check *dagIndexedReplayCheck) selection(key string, size uint64) error {
	actual, found, err := readSelection(check.store.db, key)
	if err != nil || !found || actual != size {
		return errDagHistoryUnavailable
	}
	check.selected, err = addSelected(check.selected, key, size)
	return err
}

func (check *dagIndexedReplayCheck) step(execution *DagExecution, previousBlocks int) error {
	snapshot := publicSnapshot(execution)
	if check.store.validPublicSnapshot(snapshot) != nil ||
		check.publicEntry(publicSnapshotKey(execution.Commitment), snapshot) != nil ||
		check.selection("m/"+execution.Commitment.ManifestHash, uint64(len(canonical(execution.Manifest)))) != nil {
		return errDagHistoryUnavailable
	}
	if previousBlocks < 0 || execution.orderCount()-previousBlocks > DagMaxBatchBlocks {
		return errDagHistoryUnavailable
	}
	read := func(key string, target any) error {
		raw, err := check.store.db.Get([]byte(key), nil)
		if err != nil {
			return errDagHistoryUnavailable
		}
		return decodePublic(raw, target)
	}
	// Each aligned subtree is generated once, after its children were already
	// independently checked from signed replay. Exact prefix key counts were
	// checked on opening; no unvisited extra public/selection row can hide.
	for index := previousBlocks + 1; index <= execution.orderCount(); index++ {
		value, found, err := execution.history.get(historyOrderKey(index))
		if err != nil || !found || value.Order == nil || value.Order.Index != index {
			return errDagHistoryUnavailable
		}
		leaf := *value.Order
		if err := appendPublicOrderEntries([]DagOrderLeaf{leaf}, read, check.publicEntry); err != nil {
			return err
		}
		record, found, err := execution.historyRecord(leaf.Hash)
		if err != nil || !found || record.Index != index ||
			check.selection("r/"+record.WireHash, uint64(record.WireBytes)) != nil {
			return errDagHistoryUnavailable
		}
	}
	// The RAM set covers only this bounded batch's newly constructed nodes.
	// Historical deduplication uses the exact disposable disk set, not Bloom
	// membership, a growing RAM map, or a skipped metadata integrity check.
	seen := map[string]bool{}
	return execution.history.newNodes(seen, func(hash string, body dagHistoryBody) error {
		if len(seen) > 2*DagMaxRecords {
			return errDagHistoryUnavailable
		}
		raw := canonical(body)
		if _, err := decodeHistoryNode(hash, raw); err != nil {
			return err
		}
		actual, err := check.store.db.Get([]byte("hx/"+hash), nil)
		if err != nil || !bytes.Equal(actual, raw) {
			return errDagHistoryUnavailable
		}
		first, err := check.work.firstMetadata(hash)
		if err != nil {
			return err
		}
		if first {
			check.metadataBytes += uint64(67 + len(raw))
			check.metadataNodes++
			if check.metadataBytes > dagMetadataMaxBytes || check.metadataNodes > dagMetadataMaxNodes {
				return errDagHistoryUnavailable
			}
		}
		return nil
	})
}

// Only the already versioned store uses this path. newDagStore has verified
// exact on-disk key shapes, totals and counts before this fresh, unpublished
// store is passed here. Legacy migration keeps its original atomic path.
func (store *dagStore) replayIndexed(expected DagCommitment) (*DagExecution, error) {
	return store.replayIndexedObserved(expected, nil)
}

// An archive sink sees each verified checkpoint before transient payload RAM
// is released. A failed sink cannot publish replay readiness or an archive.
func (store *dagStore) replayIndexedObserved(expected DagCommitment, observe func(DagManifest) error) (*DagExecution, error) {
	store.mu.Lock()
	defer store.mu.Unlock()
	if store.db == nil || store.failed || store.retentionReady || store.metadataFault.Load() ||
		store.meta.PublicIndex != 2 || store.meta.HistoryIndex != 1 || store.meta.SelectionIndex != 1 ||
		validateDagCommitment(expected, store.source, store.anchor) != nil {
		return nil, errDagHistoryUnavailable
	}
	execution, err := newDagExecution(store.source, store.anchor)
	if err != nil {
		return nil, err
	}
	factory := store.openReplayScratch
	if factory == nil {
		factory = func() (dagReplayScratch, error) { return newDagReplayWorkAt(store.replayWorkPath) }
	}
	work, err := factory()
	if err != nil || work == nil {
		return nil, errDagReplayWork
	}
	defer work.close()
	current := expected.ManifestHash
	for checkpoint := expected.Checkpoint; ; checkpoint-- {
		raw, err := store.db.Get([]byte("m/"+current), nil)
		if err != nil {
			return nil, errors.New("GG_DAG_STORE_MANIFEST_MISSING")
		}
		manifest, err := store.validManifest(raw, current)
		if err != nil || manifest.Checkpoint != checkpoint {
			return nil, errors.New("GG_DAG_STORE_CHAIN")
		}
		if err := work.putManifest(checkpoint, current, raw); err != nil {
			return nil, err
		}
		if checkpoint == 0 {
			if current != execution.Commitment.ManifestHash {
				return nil, errors.New("GG_DAG_STORE_GENESIS")
			}
			break
		}
		current = manifest.Previous
	}
	check := dagIndexedReplayCheck{store: store, work: work, selected: store.meta}
	check.selected.SelectedBytes, check.selected.SelectedRecords, check.selected.SelectedManifests = 0, 0, 0
	if err := check.step(execution, 0); err != nil {
		return nil, err
	}
	for checkpoint := uint64(1); checkpoint <= expected.Checkpoint; checkpoint++ {
		hash, raw, err := work.manifest(checkpoint)
		if err != nil {
			return nil, err
		}
		manifest, err := store.validManifest(raw, hash)
		if err != nil || manifest.Checkpoint != checkpoint || manifest.Previous != execution.Commitment.ManifestHash {
			return nil, errors.New("GG_DAG_STORE_CHAIN")
		}
		previousBlocks := execution.orderCount()
		execution, err = store.replayManifest(execution, manifest)
		if err != nil {
			return nil, err
		}
		if err := check.step(execution, previousBlocks); err != nil {
			return nil, err
		}
		if observe != nil {
			if err := observe(execution.Manifest); err != nil {
				return nil, err
			}
		}
		execution = store.archiveExecution(execution)
	}
	if execution.Commitment != expected || check.metadataBytes != store.meta.HistoryBytes || check.metadataNodes != store.meta.HistoryNodes ||
		execution.history.root.id() != store.meta.HistoryRoot || check.selected.SelectedBytes != store.meta.SelectedBytes ||
		check.selected.SelectedRecords != store.meta.SelectedRecords || check.selected.SelectedManifests != store.meta.SelectedManifests {
		return nil, errDagHistoryUnavailable
	}
	head := dagPublicHead{Bytes: check.publicBytes, Commitment: expected, Schema: "gg.dag.public-head.v2"}
	raw, err := store.db.Get([]byte("pub/head"), nil)
	if err != nil || !bytes.Equal(raw, canonical(head)) {
		return nil, errors.New("GG_DAG_PUBLIC_REPLAY_MISMATCH")
	}
	// Cleanup is part of successful recovery. No writable prefix/readiness is
	// published if temporary IO or removal failed, even after valid signatures.
	if err := work.close(); err != nil {
		return nil, err
	}
	if err := store.restoreRetentionCount(execution, int(expected.Checkpoint)+1); err != nil {
		return nil, err
	}
	store.replayedMetadata = nil
	return execution, nil
}
