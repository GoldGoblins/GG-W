//go:build !js

package main

// Uncommitted payload is a bounded, disposable cache, not an availability
// certificate. Every accepted new payload is synced, but later valid proposals
// may replace older cache entries. CometBFT stores the decided block BEFORE
// FinalizeBlock supplies its full data for re-execution. Selected history is
// never pruned here. Recovery rebuilds PUBLIC sizes after full verified replay.
import (
	"errors"
	"strings"

	"github.com/syndtr/goleveldb/leveldb"
)

const dagCandidateMaxBytes uint64 = 96 * 1024 * 1024
const dagCandidateMaxManifests = 128
const dagFinalizeReserveBytes uint64 = DagMaxWire + dagManifestMaxBytes

func (store *dagStore) restoreRetention(execution *DagExecution, snapshots []dagPublicSnapshot) error {
	return store.restoreRetentionCount(execution, len(snapshots))
}

func (store *dagStore) restoreRetentionCount(execution *DagExecution, snapshots int) error {
	if store.meta.SelectionIndex != 1 || store.meta.SelectedRecords != execution.orderCount() || store.meta.SelectedManifests != snapshots {
		return errDagHistoryUnavailable
	}
	// Only legacy-zero migration temporarily classified all old keys as
	// candidates. Discard verified selected entries after its successful Sync.
	for key, size := range store.candidates {
		selectedSize, selected, err := readSelection(store.db, key)
		if err != nil || selected && selectedSize != size {
			return errDagHistoryUnavailable
		}
		if selected {
			delete(store.candidates, key)
		}
	}
	if store.candidateCacheBound() != nil {
		return errDagHistoryUnavailable
	}
	prefix, err := canonicalPrefixFor(execution)
	if err != nil {
		return err
	}
	store.selected = execution.Commitment
	store.retentionReady = true
	store.prefix = prefix
	return nil
}

func (store *dagStore) candidateCredit(meta dagStoreMeta, added map[string]uint64) error {
	var size uint64
	manifests := 0
	for key, value := range store.candidates {
		size += value
		if strings.HasPrefix(key, "m/") {
			manifests++
		}
	}
	for key, value := range added {
		size += value
		if strings.HasPrefix(key, "m/") {
			manifests++
		}
	}
	if size > dagCandidateMaxBytes || manifests > dagCandidateMaxManifests ||
		meta.Bytes > dagStoreMaxBytes-dagFinalizeReserveBytes ||
		meta.Records > dagStoreMaxObjects-DagMaxBatchBlocks || meta.Manifests > dagStoreMaxObjects-1 {
		return errDagCandidateCredit
	}
	return nil
}

func retentionKeys(execution *DagExecution) map[string]bool {
	keep := map[string]bool{"m/" + execution.Commitment.ManifestHash: true}
	for _, hash := range execution.Manifest.Blocks {
		keep["r/"+hash] = true
	}
	return keep
}

// Caller owns store.mu. All deletions and exact size/count changes join the
// SAME synchronous atomic write as prepared payload or committed selection.
func (store *dagStore) retireCandidates(batch *leveldb.Batch, meta dagStoreMeta, keep map[string]bool) (dagStoreMeta, []string, error) {
	retired := []string{}
	for key, size := range store.candidates {
		if keep[key] {
			continue
		}
		_, selected, err := store.selectedObject(key)
		if err != nil {
			return meta, nil, err
		}
		if selected || size > meta.Bytes {
			return meta, nil, errors.New("GG_DAG_STORE_RETENTION_STATE")
		}
		meta.Bytes -= size
		if strings.HasPrefix(key, "m/") {
			meta.Manifests--
		} else {
			meta.Records--
		}
		if meta.Manifests < 0 || meta.Records < 0 {
			return meta, nil, errors.New("GG_DAG_STORE_RETENTION_STATE")
		}
		batch.Delete([]byte(key))
		retired = append(retired, key)
	}
	return meta, retired, nil
}

func (store *dagStore) finishRetentionSelection(batch *leveldb.Batch, execution *DagExecution) error {
	prefix, err := canonicalPrefixFor(execution)
	if err != nil {
		return err
	}
	keep := retentionKeys(execution)
	for key := range keep {
		_, pending := store.candidates[key]
		_, selected, err := store.selectedObject(key)
		if err != nil {
			return err
		}
		if !pending && !selected {
			return errors.New("GG_DAG_PUBLIC_NOT_PREPARED")
		}
	}
	meta, retired, err := store.retireCandidates(batch, store.meta, keep)
	if err != nil {
		return err
	}
	meta.PublicIndex = 2
	meta, err = store.stageSelection(batch, meta, execution, keep)
	if err != nil {
		return err
	}
	meta, err = store.stageHistoryNodes(batch, meta, execution)
	if err != nil {
		return err
	}
	batch.Put([]byte("meta"), canonical(meta))
	if err := store.syncWrite(batch); err != nil {
		return err
	}
	for _, key := range retired {
		delete(store.candidates, key)
	}
	for key := range keep {
		if _, ok := store.candidates[key]; ok {
			delete(store.candidates, key)
		}
	}
	store.meta = meta
	store.selected = execution.Commitment
	store.prefix = prefix
	return nil
}
