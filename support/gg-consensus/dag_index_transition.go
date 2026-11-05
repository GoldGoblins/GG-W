//go:build !js

package main

// Local-only additive storage transition. Existing selected history, originals,
// signing identities and anti-double-sign state are never replaced or repaired.
import (
	"bytes"
	"context"
	"errors"
	"path/filepath"
	"strconv"
	"time"

	"github.com/syndtr/goleveldb/leveldb"
)

const dagIndexTransitionKey = "index-transition"
const dagIndexTransitionScope = "ORIGINAL_DAG_REPLAY_AND_ADDITIVE_INDEX_TRANSITION_NOT_NATIVE_TRANSFER_HISTORY_OR_NETWORK_FRESHNESS"

var errDagIndexTransition = errors.New("GG_DAG_INDEX_TRANSITION_INVALID_OR_INTERRUPTED")

type dagIndexTransitionProgress struct {
	Anchor      string `json:"anchor"`
	HistoryHash string `json:"history_sha256"`
	Indexed     uint64 `json:"indexed,string"`
	MetaHash    string `json:"meta_sha256"`
	Schema      string `json:"schema"`
	SourceHash  string `json:"source_hash"`
}

type dagIndexTransitionCommand struct {
	Genesis     Genesis `json:"genesis"`
	GenesisHash string  `json:"genesis_hash"`
	Root        string  `json:"root"`
	Schema      string  `json:"schema"`
}

func (store *dagSegmentStore) loadIndexTransition() error {
	if store.meta.Schema != "gg.dag.segmented-store.v1" {
		return errDagIndexTransition
	}
	expected := &dagIndexTransitionProgress{Anchor: store.meta.Anchor, MetaHash: hashHex(canonical(store.meta)),
		Schema: "gg.dag.index-transition-progress.v1", SourceHash: store.meta.SourceHash}
	raw, err := store.db.Get([]byte(dagIndexTransitionKey), nil)
	if err == leveldb.ErrNotFound {
		store.transition = expected
		return nil
	}
	var value dagIndexTransitionProgress
	if err != nil || len(raw) > 1024 || decodeStrict(raw, &value) != nil || !bytes.Equal(raw, canonical(value)) ||
		value.Anchor != expected.Anchor || value.MetaHash != expected.MetaHash || value.Schema != expected.Schema || value.SourceHash != expected.SourceHash ||
		value.Indexed >= dagSegmentCounterMax || !pubPattern.MatchString(value.HistoryHash) {
		return errDagIndexTransition
	}
	store.transition = &value
	store.transitionSaved = true
	return nil
}

func transitionIndexReceipt(store *dagSegmentStore, history []State, current *dagSegmentedExecution, state string, historyHash string) map[string]any {
	commitment, _ := current.state()
	last := history[len(history)-1]
	return map[string]any{"schema": "gg.dag.index-transition-result.v1", "state": state, "verified": true,
		"verification_scope": dagIndexTransitionScope, "genesis_hash": store.meta.Anchor, "source_hash": store.meta.SourceHash,
		"commitment": commitment, "indexed_epochs": strconv.FormatUint(commitment.Epoch-1, 10), "history_sha256": historyHash,
		"native_state_height": last.Height, "native_state_root": last.StateRoot, "original_history_replayed": true,
		"native_transfer_history_replayed": false, "signers_opened": false, "consensus_started": false, "network_started": false}
}

// The optional hook is an owned disk-failure test seam, never a request field.
// It runs after mandatory full initial provenance and before the first write.
func transitionDagIndex(ctx context.Context, request dagIndexTransitionCommand, hook ...func(*dagSegmentStore)) (result map[string]any, finalErr error) {
	if len(hook) > 1 || ctx == nil || ctx.Err() != nil || request.Schema != "gg.dag.index-transition-request.v1" ||
		validateGenesis(request.Genesis, request.GenesisHash) != nil || request.Genesis.DAGSegmented == nil || !filepath.IsAbs(request.Root) {
		return nil, errDagIndexTransition
	}
	store, history, current, err := openDagSegmentStoreContext(ctx, request.Genesis, request.GenesisHash, request.Root, false, dagSegmentOpenIndexTransition)
	if err != nil {
		return nil, err
	}
	defer func() {
		if err := store.close(); err != nil {
			result = nil
			finalErr = err
		}
	}()
	raw, err := store.db.Get([]byte("history"), nil)
	if err != nil {
		return nil, errDagIndexTransition
	}
	historyHash := hashHex(raw)
	if store.transition == nil {
		return transitionIndexReceipt(store, history, current, "ALREADY_CURRENT", historyHash), nil
	}
	if len(hook) == 1 && hook[0] != nil {
		hook[0](store)
	}
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	if !store.transitionSaved {
		batch := new(leveldb.Batch)
		batch.Put([]byte(dagIndexTransitionKey), canonical(store.transition))
		if err := store.syncWrite(batch); err != nil {
			return nil, err
		}
		store.transitionSaved = true
	}
	// A second bounded forward pass derives each next batch. The first pass
	// already checked the complete original history/tail and any saved prefix.
	// No whole-history list or deferred unbounded write batch is accumulated.
	cursor, err := newDagSegmentedExecution(*request.Genesis.DAGSegmented, request.GenesisHash)
	if err != nil {
		return nil, err
	}
	for epoch := uint64(1); epoch <= store.closedEntries; epoch++ {
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		raw, err := store.db.Get([]byte(segmentArchiveReferenceKey(epoch)), nil)
		var reference dagSegmentArchiveReference
		if err != nil || decodeStrict(raw, &reference) != nil || !bytes.Equal(raw, canonical(reference)) || reference.Epoch != epoch {
			return nil, errDagIndexTransition
		}
		file, _, err := checkedSegmentFile(filepath.Join(store.root, "gg-dag-segments", reference.Cut+".ggseg"), false, dagSegmentArchiveMaxBytes)
		if err != nil {
			return nil, err
		}
		replayed, replayErr := readDagHistorySegment(ctx, file, cursor)
		closeErr := file.Close()
		if replayErr != nil || closeErr != nil || replayed.plan.hash != reference.Cut || replayed.archiveHash != reference.ArchiveHash {
			return nil, errDagIndexTransition
		}
		if epoch <= store.transition.Indexed {
			if err := store.verifyClosedIndex(replayed.index, cursor.closed); err != nil {
				return nil, err
			}
		} else {
			if epoch != store.transition.Indexed+1 {
				return nil, errDagIndexTransition
			}
			batch := new(leveldb.Batch)
			if err := store.stageClosedIndex(batch, replayed.index, cursor.closed); err != nil {
				return nil, err
			}
			next := *store.transition
			next.Indexed = epoch
			batch.Put([]byte(dagIndexTransitionKey), canonical(next))
			if ctx.Err() != nil {
				return nil, ctx.Err()
			}
			if err := store.syncWrite(batch); err != nil {
				return nil, err
			}
			store.transition = &next
		}
		cursor = replayed.plan.next
	}
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	if store.transition.Indexed != store.closedEntries || store.transition.HistoryHash != historyHash || store.transition.MetaHash != hashHex(canonical(store.meta)) {
		return nil, errDagIndexTransition
	}
	still, err := store.db.Get([]byte("history"), nil)
	if err != nil || hashHex(still) != historyHash {
		return nil, errDagIndexTransition
	}
	nextMeta := store.meta
	nextMeta.Schema = "gg.dag.segmented-store.v2"
	batch := new(leveldb.Batch)
	batch.Put([]byte("meta"), canonical(nextMeta))
	batch.Delete([]byte(dagIndexTransitionKey))
	if err := store.syncWrite(batch); err != nil {
		return nil, err
	}
	store.meta = nextMeta
	store.transition = nil
	store.transitionSaved = false
	return transitionIndexReceipt(store, history, current, "INDEX_TRANSITION_COMPLETE", historyHash), nil
}

func runDagIndexTransitionCommand(raw []byte) (map[string]any, error) {
	var request dagIndexTransitionCommand
	if len(raw) > 65536 || decodeStrictLimited(raw, &request, 128, 64) != nil || !bytes.Equal(raw, canonical(request)) {
		return nil, errDagIndexTransition
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Minute)
	defer cancel()
	return transitionDagIndex(ctx, request)
}
