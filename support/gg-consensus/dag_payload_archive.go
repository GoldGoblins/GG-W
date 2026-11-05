//go:build !js

package main

// The original signed r/<wire hash> objects remain durably immutable. Only
// committed execution RAM is compacted. Replay verifies every original block
// and TX before archiving each batch; no decoded state snapshot bypass exists.
import (
	"context"
	"errors"
	"sync"
)

const dagPayloadCacheBytes = 32 * 1024 * 1024
const dagPayloadCacheRecords = 2
const dagPayloadMaxReaders = 2

type dagPayloadCache struct {
	mu      sync.Mutex
	entries map[string][]byte
	order   []string
	bytes   int
}

func (cache *dagPayloadCache) get(hash string, size int) []byte {
	cache.mu.Lock()
	defer cache.mu.Unlock()
	raw := cache.entries[hash]
	if len(raw) != size {
		return nil
	}
	for index, key := range cache.order {
		if key == hash {
			cache.order = append(append(cache.order[:index:index], cache.order[index+1:]...), hash)
			break
		}
	}
	return raw
}

func (cache *dagPayloadCache) put(hash string, raw []byte) {
	cache.mu.Lock()
	defer cache.mu.Unlock()
	if len(raw) == 0 || len(raw) > dagPayloadCacheBytes {
		return
	}
	if cache.entries == nil {
		cache.entries = map[string][]byte{}
	}
	if previous, ok := cache.entries[hash]; ok {
		cache.bytes -= len(previous)
		for index, key := range cache.order {
			if key == hash {
				cache.order = append(cache.order[:index], cache.order[index+1:]...)
				break
			}
		}
	}
	cache.entries[hash] = raw
	cache.bytes += len(raw)
	cache.order = append(cache.order, hash)
	for cache.bytes > dagPayloadCacheBytes || len(cache.order) > dagPayloadCacheRecords {
		key := cache.order[0]
		cache.order = cache.order[1:]
		cache.bytes -= len(cache.entries[key])
		delete(cache.entries, key)
	}
}

func (cache *dagPayloadCache) clear() {
	cache.mu.Lock()
	defer cache.mu.Unlock()
	cache.entries = nil
	cache.order = nil
	cache.bytes = 0
}

func (store *dagStore) archiveExecution(execution *DagExecution) *DagExecution {
	next := *execution
	next.pending = map[string]dagRecord{}
	if store.metadataPersisted.Load() {
		next.history = dagHistory{root: dagHistoryRef{hash: execution.history.root.id()}, read: store.readHistoryNode}
	}
	next.payloadReader = store.readPayload
	return &next
}

func (store *dagStore) readPayload(ctx context.Context, hash string, size int) ([]byte, error) {
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	if !pubPattern.MatchString(hash) || size < 1 || size > DagMaxWire {
		return nil, errors.New("GG_DAG_PAYLOAD_SELECTOR")
	}
	store.mu.Lock()
	if store.db == nil || store.failed || !store.retentionReady {
		store.mu.Unlock()
		return nil, errors.New("GG_DAG_STORE_FAULT")
	}
	if _, pending := store.candidates["r/"+hash]; pending || store.meta.SelectionIndex != 1 {
		store.mu.Unlock()
		return nil, errors.New("GG_DAG_PAYLOAD_NOT_COMMITTED")
	}
	if store.payloadReaders >= dagPayloadMaxReaders {
		store.mu.Unlock()
		return nil, errors.New("GG_DAG_PAYLOAD_BUSY")
	}
	snapshot, err := store.db.GetSnapshot()
	if err != nil {
		store.mu.Unlock()
		return nil, errors.New("GG_DAG_PAYLOAD_SNAPSHOT")
	}
	store.payloadReaders++
	store.readers.Add(1)
	hook := store.beforePayloadRead
	selectionHook := store.beforeSelectionRead
	store.mu.Unlock()
	defer func() { store.mu.Lock(); store.payloadReaders--; store.mu.Unlock(); store.readers.Done() }()
	defer snapshot.Release()
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	if selectionHook != nil {
		selectionHook(hash)
	}
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	selectedSize, selected, selectionErr := readSelection(snapshot, "r/"+hash)
	if selectionErr != nil {
		store.metadataFault.Store(true)
		return nil, selectionErr
	}
	if !selected {
		exists, err := snapshot.Has([]byte("r/"+hash), nil)
		if err != nil || exists {
			store.metadataFault.Store(true)
			return nil, errDagHistoryUnavailable
		}
		return nil, errors.New("GG_DAG_PAYLOAD_NOT_COMMITTED")
	}
	if selectedSize != uint64(size) {
		store.metadataFault.Store(true)
		return nil, errDagHistoryUnavailable
	}
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	if raw := store.payloadCache.get(hash, size); raw != nil {
		return raw, nil
	}
	if hook != nil {
		hook(hash)
	}
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	value, err := snapshot.Get([]byte("r/"+hash), nil)
	if err != nil || len(value) != size {
		return nil, errors.New("GG_DAG_PAYLOAD_CHANGED")
	}
	// Snapshot buffers are read-only library data. Give the cache its own
	// immutable allocation before releasing the pinned database view.
	raw := append([]byte(nil), value...)
	if hashHex(raw) != hash {
		return nil, errors.New("GG_DAG_PAYLOAD_CHANGED")
	}
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	store.payloadCache.put(hash, raw)
	return raw, nil
}
