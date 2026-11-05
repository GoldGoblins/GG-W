//go:build !js

package main

import (
	"bytes"
	"context"
	"encoding/base64"
	"errors"
	"io"
	"path/filepath"
	"strconv"

	"github.com/syndtr/goleveldb/leveldb"
)

type dagClosedSelector struct {
	Epoch string `json:"epoch"`
	Start int    `json:"start"`
}
type dagClosedPayloadSelector struct {
	Epoch  string `json:"epoch"`
	Hash   string `json:"hash"`
	Index  int    `json:"index"`
	Offset int    `json:"offset"`
}
type dagClosedPayloadChunk struct {
	DagPayloadChunk
	Epoch string `json:"epoch"`
}

func closedEpoch(value string, current dagSegmentedState) (uint64, error) {
	epoch, err := strconv.ParseUint(value, 10, 64)
	if err != nil || epoch < 1 || epoch >= current.Epoch || strconv.FormatUint(epoch, 10) != value {
		return 0, errDagClosedProof
	}
	return epoch, nil
}

func (store *dagSegmentStore) closedSnapshot(state State) (*leveldb.Snapshot, dagSegmentedSource, func(), error) {
	store.mu.Lock()
	defer store.mu.Unlock()
	if store.db == nil || store.failed || store.selected == nil || state.DAGSegmented == nil || state.GenesisHash != store.meta.Anchor ||
		state.DAGSegmented.Epoch-1 > store.closedEntries || state.DAGSegmented.SourceHash != store.meta.SourceHash {
		return nil, dagSegmentedSource{}, nil, errDagSegmentStore
	}
	snapshot, err := store.db.GetSnapshot()
	if err != nil {
		return nil, dagSegmentedSource{}, nil, errDagSegmentStore
	}
	store.payloadReaders.Add(1)
	done := func() { snapshot.Release(); store.payloadReaders.Done() }
	return snapshot, store.selected.source, done, nil
}

func (store *dagSegmentStore) closedFault() error {
	store.mu.Lock()
	store.failed = true
	store.mu.Unlock()
	return errDagSegmentStore
}

func closedTreePath(ctx context.Context, epoch, count uint64, get func(string) ([]byte, error)) ([]PathItem, error) {
	if epoch < 1 || epoch > count || count > dagSegmentCounterMax {
		return nil, errDagClosedProof
	}
	var node func(int, uint64) (string, error)
	node = func(level int, index uint64) (string, error) {
		if ctx.Err() != nil {
			return "", ctx.Err()
		}
		width := uint64(1) << level
		base := index * width
		if base >= count {
			return "", errDagClosedProof
		}
		if width <= count-base {
			raw, err := get(closedNodeKey(level, index))
			if err != nil || !pubPattern.Match(raw) {
				return "", errDagSegmentStore
			}
			return string(raw), nil
		}
		if level == 0 {
			return "", errDagClosedProof
		}
		left, err := node(level-1, index*2)
		if err != nil {
			return "", err
		}
		right := left
		if base+width/2 < count {
			right, err = node(level-1, index*2+1)
			if err != nil {
				return "", err
			}
		}
		return closedSegmentJoin(left, right), nil
	}
	path := []PathItem{}
	at := epoch - 1
	for width, level := count, 0; width > 1; width, level = (width+1)/2, level+1 {
		sibling := at ^ 1
		side := "right"
		if at&1 == 1 {
			side = "left"
		}
		if sibling >= width {
			sibling = at
		}
		hash, err := node(level, sibling)
		if err != nil {
			return nil, err
		}
		path = append(path, PathItem{Hash: hash, Side: side})
		at /= 2
	}
	return path, nil
}

func (store *dagSegmentStore) readClosedIndex(ctx context.Context, snapshot *leveldb.Snapshot, state State, source dagSegmentedSource, epoch uint64) (*dagClosedIndex, dagHistoryCutBody, []PathItem, error) {
	var empty dagHistoryCutBody
	if ctx.Err() != nil {
		return nil, empty, nil, ctx.Err()
	}
	raw, err := snapshot.Get([]byte(closedIndexKey(epoch)), nil)
	if err != nil {
		return nil, empty, nil, store.closedFault()
	}
	index, cut, hash, err := checkedClosedIndex(raw, source, state.GenesisHash, epoch)
	if err != nil {
		return nil, empty, nil, store.closedFault()
	}
	raw, err = snapshot.Get([]byte(segmentArchiveReferenceKey(epoch)), nil)
	var reference dagSegmentArchiveReference
	if err != nil || decodeStrict(raw, &reference) != nil || !bytes.Equal(raw, canonical(reference)) || reference.Epoch != epoch ||
		reference.Schema != "gg.dag.segment-reference.v1" || reference.Cut != hash || reference.ArchiveHash != index.ArchiveHash {
		return nil, empty, nil, store.closedFault()
	}
	path, err := closedTreePath(ctx, epoch, state.DAGSegmented.Epoch-1, func(key string) ([]byte, error) { return snapshot.Get([]byte(key), nil) })
	if ctx.Err() != nil {
		return nil, empty, nil, ctx.Err()
	}
	if err != nil || verifyClosedCutPath(hash, path, epoch, state.DAGSegmented.Epoch-1, state.DAGSegmented.ClosedRoot) != nil {
		return nil, empty, nil, store.closedFault()
	}
	return index, cut, path, nil
}

func (store *dagSegmentStore) publicClosedPage(ctx context.Context, state State, selector dagClosedSelector) (dagSegmentedClosedPage, error) {
	empty := dagSegmentedClosedPage{}
	if state.DAGSegmented == nil || ctx.Err() != nil {
		return empty, errDagClosedProof
	}
	epoch, err := closedEpoch(selector.Epoch, *state.DAGSegmented)
	if err != nil || selector.Start < 0 || selector.Start >= DagMaxRecords || selector.Start%DagOrderPageSize != 0 {
		return empty, errDagClosedProof
	}
	select {
	case store.proofSlots <- struct{}{}:
		defer func() { <-store.proofSlots }()
	default:
		return empty, errors.New("GG_DAG_PROOF_BUSY")
	}
	snapshot, source, done, err := store.closedSnapshot(state)
	if err != nil {
		return empty, err
	}
	defer done()
	if store.beforeProofRead != nil {
		store.beforeProofRead()
	}
	index, cut, path, err := store.readClosedIndex(ctx, snapshot, state, source, epoch)
	if err != nil {
		return empty, err
	}
	if selector.Start >= len(index.Order) {
		return empty, errDagClosedProof
	}
	end := min(selector.Start+DagOrderPageSize, len(index.Order))
	levels := dagTree(index.Order, dagOrderDomain)
	page := dagSegmentedClosedPage{Commitment: *state.DAGSegmented, Complete: end == len(index.Order), Cut: append([]byte(nil), index.Cut...), ClosedPath: path,
		GenesisHash: state.GenesisHash, Height: state.Height, Items: []dagSegmentedOrderWitness{}, Schema: "gg.dag.segmented-closed-page.v1", Start: selector.Start, StateRoot: state.StateRoot}
	for position := selector.Start; position < end; position++ {
		leaf, err := segmentedPublicLeaf(index.Order[position], cut.Before, source)
		if err != nil {
			return empty, store.closedFault()
		}
		page.Items = append(page.Items, dagSegmentedOrderWitness{Leaf: leaf, Path: dagPathFromLevels(levels, position)})
	}
	if ctx.Err() != nil {
		return empty, ctx.Err()
	}
	if verifySegmentedClosedPage(page, state, source) != nil {
		return empty, store.closedFault()
	}
	return page, nil
}

func (store *dagSegmentStore) publicClosedPayload(ctx context.Context, state State, selector dagClosedPayloadSelector) (dagClosedPayloadChunk, error) {
	empty := dagClosedPayloadChunk{}
	if state.DAGSegmented == nil || ctx.Err() != nil {
		return empty, errDagClosedProof
	}
	epoch, err := closedEpoch(selector.Epoch, *state.DAGSegmented)
	if err != nil || !pubPattern.MatchString(selector.Hash) || selector.Index < 1 || selector.Index > DagMaxRecords || selector.Offset < 0 || selector.Offset >= DagMaxWire || selector.Offset%DagPayloadChunkBytes != 0 {
		return empty, errDagClosedProof
	}
	select {
	case store.payloadSlots <- struct{}{}:
		defer func() { <-store.payloadSlots }()
	default:
		return empty, errors.New("GG_DAG_PAYLOAD_BUSY")
	}
	snapshot, source, done, err := store.closedSnapshot(state)
	if err != nil {
		return empty, err
	}
	defer done()
	if store.beforePayloadRead != nil {
		store.beforePayloadRead()
	}
	index, cut, _, err := store.readClosedIndex(ctx, snapshot, state, source, epoch)
	if err != nil {
		return empty, err
	}
	if selector.Index > len(index.Order) || index.Order[selector.Index-1].Hash != selector.Hash {
		return empty, errDagClosedProof
	}
	payload := index.Payloads[selector.Index-1]
	leaf := index.Order[selector.Index-1]
	if selector.Offset >= payload.Size {
		return empty, errDagClosedProof
	}
	raw := store.payloadCache.get(payload.WireHash, payload.Size)
	if raw == nil {
		directory := filepath.Join(store.root, "gg-dag-segments")
		hash := dagDigest("GG-DAG-HISTORY-CUT-v1\x00", cut)
		if !realArchiveDirectory(directory) {
			return empty, store.closedFault()
		}
		file, info, err := checkedSegmentFile(filepath.Join(directory, hash+".ggseg"), false, dagSegmentArchiveMaxBytes)
		if err != nil {
			return empty, store.closedFault()
		}
		if info.Size() != index.ArchiveBytes {
			_ = file.Close()
			return empty, store.closedFault()
		}
		raw = make([]byte, payload.Size)
		n, readErr := file.ReadAt(raw, payload.Offset)
		after, statErr := file.Stat()
		closeErr := file.Close()
		if n != payload.Size || readErr != nil && readErr != io.EOF || statErr != nil || after.Size() != info.Size() || closeErr != nil || hashHex(raw) != payload.WireHash {
			return empty, store.closedFault()
		}
		if ctx.Err() != nil {
			return empty, ctx.Err()
		}
		when, err := strconv.ParseInt(payload.TimeNs, 10, 64)
		if err != nil {
			return empty, store.closedFault()
		}
		precheck := cut.Before.LastCut
		if epoch == 1 {
			precheck = source.Genesis.PrecheckRoot
		}
		// Restore the true source2 authentication domain, as the executor does.
		// validationView's short legacy chain alias is only for shape checking.
		originalSource := source.validationView()
		originalSource.Schema = source.Schema
		originalSource.Genesis.Schema = source.Genesis.Schema
		originalSource.Genesis.ChainID = source.Genesis.ChainID
		originalSource.GenesisHash = source.GenesisHash
		// Match applyDagBatch's already selected per-manifest +5s allowance.
		// It is not valid to compare against an archive's final manifest time
		// with a stricter clock rule and then poison a healthy validator.
		record, err := decodeDagBlockContext(raw, originalSource, when+5000000000, precheck, dagSegmentCounterMax, int64(dagSegmentCounterMax))
		if err != nil || record.Hash != leaf.Hash || record.Block.Body.Producer != leaf.Producer || record.Block.Body.Sequence != leaf.Sequence || len(record.Block.Body.Transactions) != leaf.Transactions {
			return empty, store.closedFault()
		}
		if ctx.Err() != nil {
			return empty, ctx.Err()
		}
		store.payloadCache.put(payload.WireHash, raw)
	}
	end := min(selector.Offset+DagPayloadChunkBytes, len(raw))
	chunk := dagClosedPayloadChunk{Epoch: selector.Epoch, DagPayloadChunk: DagPayloadChunk{Data: base64.StdEncoding.EncodeToString(raw[selector.Offset:end]),
		GenesisHash: state.GenesisHash, Hash: selector.Hash, Height: state.Height, Index: selector.Index, Offset: selector.Offset,
		Schema: "gg.dag.closed-payload-chunk.v1", StateRoot: state.StateRoot, Total: len(raw), WireHash: payload.WireHash}}
	if ctx.Err() != nil {
		return empty, ctx.Err()
	}
	return chunk, nil
}
