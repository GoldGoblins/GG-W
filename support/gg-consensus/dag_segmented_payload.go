//go:build !js

package main

// Selected source2 originals, pinned to a retained certified active view.
// Index is epoch-local, exactly as in that view's membership proof. The caller
// must verify the original body hash/signature before displaying causal edges.
import (
	"context"
	"encoding/base64"
	"errors"
)

type dagSegmentPayload struct {
	Hash, WireHash string
	Size           int
}

func (store *dagSegmentStore) publicPayload(ctx context.Context, state State, selector DagPayloadSelector) (DagPayloadChunk, error) {
	result := DagPayloadChunk{}
	if ctx.Err() != nil {
		return result, ctx.Err()
	}
	if state.DAGSegmented == nil || !pubPattern.MatchString(selector.Hash) || selector.Index < 1 ||
		selector.Index > state.DAGSegmented.Active.Blocks || selector.Offset < 0 || selector.Offset >= DagMaxWire || selector.Offset%DagPayloadChunkBytes != 0 {
		return result, errors.New("GG_DAG_PAYLOAD_SELECTOR")
	}
	select {
	case store.payloadSlots <- struct{}{}:
		defer func() { <-store.payloadSlots }()
	default:
		return result, errors.New("GG_DAG_PAYLOAD_BUSY")
	}
	store.mu.Lock()
	if store.db == nil || store.failed || state.GenesisHash != store.meta.Anchor {
		store.mu.Unlock()
		return result, errDagSegmentStore
	}
	if store.selected == nil || store.selected.closed.count+1 != state.DAGSegmented.Epoch {
		// Closed epoch originals have moved to their signed archive. This
		// endpoint promises a retained active view, not cold archive traversal.
		store.mu.Unlock()
		return result, errDagSegmentProofUnavailable
	}
	var record dagSegmentPayload
	for _, view := range store.proofViews {
		if view.state == *state.DAGSegmented && len(view.payloads) >= selector.Index {
			record = view.payloads[selector.Index-1]
			break
		}
	}
	if record.Hash != selector.Hash || selector.Offset >= record.Size {
		store.mu.Unlock()
		return result, errDagSegmentProofUnavailable
	}
	snapshot, err := store.db.GetSnapshot()
	if err != nil {
		store.mu.Unlock()
		return result, errDagSegmentStore
	}
	store.payloadReaders.Add(1)
	hook := store.beforePayloadRead
	store.mu.Unlock()
	defer store.payloadReaders.Done()
	defer snapshot.Release()
	if hook != nil {
		hook()
	}
	if ctx.Err() != nil {
		return result, ctx.Err()
	}
	raw := store.payloadCache.get(record.WireHash, record.Size)
	if raw == nil {
		value, readErr := snapshot.Get([]byte("r/"+record.WireHash), nil)
		if readErr != nil || len(value) != record.Size || hashHex(value) != record.WireHash {
			store.mu.Lock()
			store.failed = true
			store.mu.Unlock()
			return result, errors.New("GG_DAG_PAYLOAD_CHANGED")
		}
		// Never cache a borrowed LevelDB snapshot buffer.
		raw = append([]byte(nil), value...)
		if ctx.Err() != nil {
			return result, ctx.Err()
		}
		store.payloadCache.put(record.WireHash, raw)
	}
	end := min(selector.Offset+DagPayloadChunkBytes, len(raw))
	result = DagPayloadChunk{Data: base64.StdEncoding.EncodeToString(raw[selector.Offset:end]), GenesisHash: state.GenesisHash,
		Hash: record.Hash, Height: state.Height, Index: selector.Index, Offset: selector.Offset, Schema: "gg.dag.payload-chunk.v1",
		StateRoot: state.StateRoot, Total: record.Size, WireHash: record.WireHash}
	if ctx.Err() != nil {
		return DagPayloadChunk{}, ctx.Err()
	}
	return result, nil
}
