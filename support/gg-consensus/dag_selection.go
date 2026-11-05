//go:build !js

package main

// Exact, derived selected-object membership lives on disk. Its markers and
// counters join the SAME atomic Sync as native history and selected roots.
// Startup authenticates the original signed history before trusting this index.
import (
	"bytes"
	"errors"
	"strings"

	"github.com/syndtr/goleveldb/leveldb"
	"github.com/syndtr/goleveldb/leveldb/opt"
)

type dagSelectionReader interface {
	Get([]byte, *opt.ReadOptions) ([]byte, error)
}

const dagCandidateCatalogRecords = 8192
const dagCandidateCatalogManifests = dagCandidateMaxManifests + 1

func selectionKey(key string) string { return "sel/" + key }

func validSelectionObject(key string, size uint64) bool {
	if len(key) != 66 || !pubPattern.MatchString(key[2:]) || size == 0 {
		return false
	}
	return strings.HasPrefix(key, "r/") && size <= DagMaxWire || strings.HasPrefix(key, "m/") && size <= dagManifestMaxBytes
}

func readSelection(reader dagSelectionReader, key string) (uint64, bool, error) {
	raw, err := reader.Get([]byte(selectionKey(key)), nil)
	if err == leveldb.ErrNotFound {
		return 0, false, nil
	}
	var size uint64
	if err != nil || len(raw) == 0 || len(raw) > 16 || decodeStrict(raw, &size) != nil || !bytes.Equal(raw, canonical(size)) || !validSelectionObject(key, size) {
		return 0, false, errDagHistoryUnavailable
	}
	return size, true, nil
}

func validSelectionMeta(meta dagStoreMeta) bool {
	if meta.SelectionIndex == 0 {
		return meta.SelectedBytes == 0 && meta.SelectedRecords == 0 && meta.SelectedManifests == 0
	}
	return meta.SelectionIndex == 1 && meta.SelectedBytes <= meta.Bytes && meta.SelectedRecords >= 0 && meta.SelectedRecords <= meta.Records &&
		meta.SelectedManifests >= 0 && meta.SelectedManifests <= meta.Manifests
}

// Caller owns store.mu. A stored object omitted from both verified membership
// and the bounded candidate catalog is unavailable metadata, not an absence.
func (store *dagStore) selectedObject(key string) (uint64, bool, error) {
	if store.meta.SelectionIndex != 1 {
		return 0, false, errDagHistoryUnavailable
	}
	size, found, err := readSelection(store.db, key)
	_, pending := store.candidates[key]
	if err == nil && !(found && pending) {
		if found || pending {
			return size, found, nil
		}
		exists, readErr := store.db.Has([]byte(key), nil)
		if readErr == nil && !exists {
			return 0, false, nil
		}
	}
	store.metadataFault.Store(true)
	return 0, false, errDagHistoryUnavailable
}

func (store *dagStore) candidateCacheBound() error {
	var size uint64
	records, manifests := 0, 0
	for key, value := range store.candidates {
		size += value
		if strings.HasPrefix(key, "m/") {
			manifests++
		} else {
			records++
		}
		if records > dagCandidateCatalogRecords || manifests > dagCandidateCatalogManifests || size > dagCandidateMaxBytes+dagFinalizeReserveBytes {
			return errDagHistoryUnavailable
		}
	}
	return nil
}

func addSelected(meta dagStoreMeta, key string, size uint64) (dagStoreMeta, error) {
	if !validSelectionObject(key, size) {
		return meta, errDagHistoryUnavailable
	}
	meta.SelectedBytes += size
	if strings.HasPrefix(key, "m/") {
		meta.SelectedManifests++
	} else {
		meta.SelectedRecords++
	}
	if !validSelectionMeta(meta) {
		return meta, errDagHistoryUnavailable
	}
	return meta, nil
}

func (store *dagStore) stageSelection(batch *leveldb.Batch, meta dagStoreMeta, execution *DagExecution, keep map[string]bool) (dagStoreMeta, error) {
	if meta.SelectionIndex != 1 {
		return meta, errDagHistoryUnavailable
	}
	for key := range keep {
		if size, pending := store.candidates[key]; pending {
			if _, found, err := readSelection(store.db, key); err != nil || found {
				return meta, errDagHistoryUnavailable
			}
			var err error
			meta, err = addSelected(meta, key, size)
			if err != nil {
				return meta, err
			}
			batch.Put([]byte(selectionKey(key)), canonical(size))
		} else {
			if _, found, err := store.selectedObject(key); err != nil || !found {
				return meta, errDagHistoryUnavailable
			}
		}
	}
	if meta.SelectedRecords != execution.Commitment.Blocks || meta.SelectedManifests != int(execution.Commitment.Checkpoint)+1 {
		return meta, errDagHistoryUnavailable
	}
	return meta, nil
}

// This runs only AFTER full signed replay and public/history-index checking.
// It streams expected membership. A versioned missing/extra/changed marker is
// never rebuilt; a legacy-zero index is added only in the shared migration Sync.
func (store *dagStore) verifyOrMigrateSelection(batch *leveldb.Batch, meta dagStoreMeta, execution *DagExecution, snapshots []dagPublicSnapshot) (dagStoreMeta, error) {
	legacy := meta.SelectionIndex == 0
	if !legacy && meta.SelectionIndex != 1 {
		return meta, errDagHistoryUnavailable
	}
	expected := meta
	expected.SelectionIndex = 1
	expected.SelectedBytes = 0
	expected.SelectedRecords = 0
	expected.SelectedManifests = 0
	mark := func(key string, size uint64) error {
		previous, found, err := readSelection(store.db, key)
		if err != nil || legacy && found || !legacy && (!found || previous != size) {
			return errDagHistoryUnavailable
		}
		expected, err = addSelected(expected, key, size)
		if err != nil {
			return err
		}
		if legacy {
			batch.Put([]byte(selectionKey(key)), canonical(size))
		}
		return nil
	}
	if len(snapshots) != int(execution.Commitment.Checkpoint)+1 {
		return meta, errDagHistoryUnavailable
	}
	for _, snapshot := range snapshots {
		key := "m/" + snapshot.Commitment.ManifestHash
		raw, err := store.db.Get([]byte(key), nil)
		if err != nil || mark(key, uint64(len(raw))) != nil {
			return meta, errDagHistoryUnavailable
		}
	}
	if err := execution.visitOrderPrefix(execution.orderCount(), func(leaf DagOrderLeaf) error {
		record, found, err := execution.historyRecord(leaf.Hash)
		if err != nil || !found {
			return errDagHistoryUnavailable
		}
		return mark("r/"+record.WireHash, uint64(record.WireBytes))
	}); err != nil {
		return meta, err
	}
	if !legacy && (expected.SelectedBytes != meta.SelectedBytes || expected.SelectedRecords != meta.SelectedRecords || expected.SelectedManifests != meta.SelectedManifests) {
		return meta, errors.New("GG_DAG_SELECTION_REPLAY_MISMATCH")
	}
	return expected, nil
}
