//go:build !js

package main

// This is a derived index, never an execution snapshot. Startup independently
// replays every original signature, TX, nonce and state root before trusting it.
// Nodes are immutable and append-only, so old candidate/query roots stay valid.
import (
	"bytes"
	"sync"

	"github.com/syndtr/goleveldb/leveldb"
)

const dagMetadataMaxBytes uint64 = 128 * 1024 * 1024
const dagMetadataMaxNodes = 262144
const dagMetadataNodeMax = 2048
const dagMetadataCacheNodes = 512

type dagMetadataCache struct {
	mu      sync.Mutex
	entries map[string]dagHistoryBody
	order   []string
}

func (cache *dagMetadataCache) get(hash string) (dagHistoryBody, bool) {
	cache.mu.Lock()
	defer cache.mu.Unlock()
	body, ok := cache.entries[hash]
	return body, ok
}
func (cache *dagMetadataCache) put(hash string, body dagHistoryBody) {
	cache.mu.Lock()
	defer cache.mu.Unlock()
	if cache.entries == nil {
		cache.entries = map[string]dagHistoryBody{}
	}
	if _, ok := cache.entries[hash]; ok {
		return
	}
	cache.entries[hash] = body
	cache.order = append(cache.order, hash)
	if len(cache.order) > dagMetadataCacheNodes {
		delete(cache.entries, cache.order[0])
		cache.order = cache.order[1:]
	}
}
func (cache *dagMetadataCache) clear() {
	cache.mu.Lock()
	defer cache.mu.Unlock()
	cache.entries = nil
	cache.order = nil
}

func decodeHistoryNode(hash string, raw []byte) (dagHistoryBody, error) {
	var body dagHistoryBody
	if !pubPattern.MatchString(hash) || len(raw) == 0 || len(raw) > dagMetadataNodeMax || decodeStrict(raw, &body) != nil ||
		!bytes.Equal(raw, canonical(body)) || !validHistoryBody(body) || historyDigest(body) != hash {
		return body, errDagHistoryUnavailable
	}
	return body, nil
}

// historyDB is immutable for the store lifetime. The independent lifecycle
// lock drains Get calls before Close; no store/app/cache mutex is held over IO.
// We never delete nodes, so a long-lived DB snapshot is unnecessary here.
func (store *dagStore) readHistoryNode(hash string) (dagHistoryBody, error) {
	if store.metadataClosed.Load() {
		return dagHistoryBody{}, errDagHistoryUnavailable
	}
	store.metadataLife.RLock()
	defer store.metadataLife.RUnlock()
	if store.metadataClosed.Load() {
		return dagHistoryBody{}, errDagHistoryUnavailable
	}
	if store.metadataFault.Load() {
		return dagHistoryBody{}, errDagHistoryUnavailable
	}
	if body, ok := store.metadataCache.get(hash); ok {
		return body, nil
	}
	if store.beforeHistoryRead != nil {
		store.beforeHistoryRead(hash)
	}
	raw, err := store.historyDB.Get([]byte("hx/"+hash), nil)
	if err != nil {
		store.metadataFault.Store(true)
		return dagHistoryBody{}, errDagHistoryUnavailable
	}
	body, err := decodeHistoryNode(hash, raw)
	if err != nil {
		store.metadataFault.Store(true)
		return body, err
	}
	store.metadataCache.put(hash, body)
	return body, nil
}

func validMetadataMeta(meta dagStoreMeta) bool {
	if meta.HistoryIndex == 0 {
		return meta.HistoryRoot == "" && meta.HistoryBytes == 0 && meta.HistoryNodes == 0
	}
	return meta.HistoryIndex == 1 && pubPattern.MatchString(meta.HistoryRoot) && meta.HistoryBytes <= dagMetadataMaxBytes &&
		meta.HistoryNodes >= 0 && meta.HistoryNodes <= dagMetadataMaxNodes
}

// Caller owns store.mu. Only nodes reachable from this selected execution join
// the same Sync batch as native history/public proofs and the selected root.
func (store *dagStore) stageHistoryNodes(batch *leveldb.Batch, meta dagStoreMeta, execution *DagExecution) (dagStoreMeta, error) {
	if meta.HistoryIndex != 1 {
		return meta, errDagHistoryUnavailable
	}
	err := execution.history.newNodes(map[string]bool{}, func(hash string, body dagHistoryBody) error {
		raw := canonical(body)
		if _, err := decodeHistoryNode(hash, raw); err != nil {
			return err
		}
		previous, err := store.db.Get([]byte("hx/"+hash), nil)
		if err == nil {
			if !bytes.Equal(previous, raw) {
				return errDagHistoryUnavailable
			}
			return nil
		}
		if err != leveldb.ErrNotFound {
			return errDagHistoryUnavailable
		}
		meta.HistoryBytes += uint64(len("hx/") + len(hash) + len(raw))
		meta.HistoryNodes++
		if meta.HistoryBytes > dagMetadataMaxBytes || meta.HistoryNodes > dagMetadataMaxNodes {
			return errDagHistoryUnavailable
		}
		batch.Put([]byte("hx/"+hash), raw)
		return nil
	})
	meta.HistoryRoot = execution.history.root.id()
	return meta, err
}

type dagMetadataReplay struct {
	root  string
	bytes uint64
	nodes int
	seen  map[string]bool
	// Only legacy index-zero migration retains derived bodies, and only until
	// the atomic migration completes. Canonical operation keeps a bounded cache.
	legacy map[string][]byte
}

func (store *dagStore) observeHistory(execution *DagExecution, replay *dagMetadataReplay) error {
	replay.root = execution.history.root.id()
	return execution.history.newNodes(replay.seen, func(hash string, body dagHistoryBody) error {
		raw := canonical(body)
		if _, err := decodeHistoryNode(hash, raw); err != nil {
			return err
		}
		replay.bytes += uint64(67 + len(raw))
		replay.nodes++
		if replay.bytes > dagMetadataMaxBytes || replay.nodes > dagMetadataMaxNodes {
			return errDagHistoryUnavailable
		}
		if store.meta.HistoryIndex == 1 {
			actual, err := store.db.Get([]byte("hx/"+hash), nil)
			if err != nil || !bytes.Equal(actual, raw) {
				return errDagHistoryUnavailable
			}
		} else {
			replay.legacy[hash] = raw
		}
		return nil
	})
}

// Caller has replayed every signed payload and owns store.mu. Versioned
// missing, extra, altered or root-inconsistent derived data is never repaired.
func (store *dagStore) verifyOrMigrateHistory(batch *leveldb.Batch, meta dagStoreMeta) (dagStoreMeta, error) {
	replay := store.replayedMetadata
	if replay == nil {
		return meta, errDagHistoryUnavailable
	}
	if meta.HistoryIndex == 1 {
		if meta.HistoryRoot != replay.root || meta.HistoryBytes != replay.bytes || meta.HistoryNodes != replay.nodes {
			return meta, errDagHistoryUnavailable
		}
		return meta, nil
	}
	for hash, raw := range replay.legacy {
		batch.Put([]byte("hx/"+hash), raw)
	}
	meta.HistoryIndex = 1
	meta.HistoryRoot = replay.root
	meta.HistoryBytes = replay.bytes
	meta.HistoryNodes = replay.nodes
	return meta, nil
}
