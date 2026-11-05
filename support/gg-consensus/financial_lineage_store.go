//go:build !js

package main

// Only newly reachable source-v3 topology nodes join the journal's Sync batch.
// Committed roots use an owned disk reader and the bounded 512-node cache.
// Original bodies, monetary receipts and SDK history retain their own stores.
import (
	"bytes"
	"context"
	"github.com/syndtr/goleveldb/leveldb"
	"github.com/syndtr/goleveldb/leveldb/opt"
	"math"
	"os"
	"path/filepath"
	"strings"
)

const financialLineagePrefix = "fl/"

func decodeFinancialLineageNode(hash string, raw []byte) (dagHistoryBody, error) {
	var body dagHistoryBody
	if !pubPattern.MatchString(hash) || len(raw) == 0 || len(raw) > dagMetadataNodeMax || decodeStrict(raw, &body) != nil || !bytes.Equal(raw, canonical(body)) ||
		body.Value.Record == nil || body.Value.Order != nil || !validHistoryBodyLimits(body, math.MaxInt64, dagSegmentCounterMax) || historyDigest(body) != hash {
		return body, errDagHistoryUnavailable
	}
	return body, nil
}

func stageFinancialLineage(ctx context.Context, execution *financialDagExecution, save func(string, []byte) error) error {
	if !execution.source.hasLineage() {
		return nil
	}
	return execution.lineage.newNodes(map[string]bool{}, func(hash string, body dagHistoryBody) error {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		raw := canonical(body)
		if _, err := decodeFinancialLineageNode(hash, raw); err != nil {
			return err
		}
		return save(financialLineagePrefix+hash, raw)
	})
}

func freezeFinancialLineage(execution *financialDagExecution, read func(string) (dagHistoryBody, error)) {
	if execution.source.hasLineage() {
		execution.lineage = dagHistory{root: dagHistoryRef{hash: execution.lineage.root.id()}, read: read, segmented: true}
	}
}

func freezeFinancialLineageViews(views []financialProducerView, read func(string) (dagHistoryBody, error)) {
	for index := range views {
		if views[index].commitment.Schema == "gg.financial-dag.commitment.v3" || views[index].commitment.Schema == "gg.financial-dag.commitment.v4" {
			views[index].lineage = dagHistory{root: dagHistoryRef{hash: views[index].lineage.root.id()}, read: read, segmented: true}
		}
	}
}

func (store *financialStore) readLineageNode(hash string) (dagHistoryBody, error) {
	// No store/cache mutex is held over disk IO. Close drains the explicit
	// readers before closing this DB; cached data never bypasses that lifetime.
	store.mu.Lock()
	if store.db == nil || store.failed || store.history.failed.Load() {
		store.mu.Unlock()
		return dagHistoryBody{}, errDagHistoryUnavailable
	}
	history := store.history
	store.readers.Add(1)
	store.mu.Unlock()
	defer store.readers.Done()
	if body, ok := store.lineageCache.get(hash); ok {
		return body, nil
	}
	raw, err := history.get(context.Background(), financialLineagePrefix+hash)
	var body dagHistoryBody
	if err == nil {
		body, err = decodeFinancialLineageNode(hash, raw)
	}
	if err != nil {
		_ = history.rejectRecord(context.Background(), err)
		store.mu.Lock()
		store.failed = true
		store.mu.Unlock()
		return dagHistoryBody{}, errDagHistoryUnavailable
	}
	store.lineageCache.put(hash, body)
	return body, nil
}

// Caller owns store.mu or does exclusive cold replay before publication.
func (store *financialStore) stageLineage(ctx context.Context, execution *financialDagExecution, batch *leveldb.Batch) error {
	return stageFinancialLineage(ctx, execution, func(key string, expected []byte) error {
		actual, err := store.history.get(ctx, key)
		if err == nil {
			if !bytes.Equal(actual, expected) {
				return store.history.rejectRecord(ctx, errDagHistoryUnavailable)
			}
			return nil
		}
		if err != leveldb.ErrNotFound || batch == nil {
			return store.history.rejectRecord(ctx, errDagHistoryUnavailable)
		}
		batch.Put([]byte(key), expected)
		return nil
	})
}

// Streaming archive replay also needs old indexed parents. This is temporary
// public-data storage, never an execution snapshot or a user-provided root.
type financialLineageScratch struct {
	db     *leveldb.DB
	root   string
	parent string
	cache  dagMetadataCache
}

func newFinancialLineageScratch() (*financialLineageScratch, error) {
	parent, err := filepath.Abs(os.TempDir())
	if err != nil {
		return nil, err
	}
	parent, err = filepath.EvalSymlinks(parent)
	if err != nil {
		return nil, err
	}
	root, err := os.MkdirTemp(parent, "gg-financial-lineage-")
	if err != nil {
		return nil, err
	}
	scratch := &financialLineageScratch{root: root, parent: parent}
	db, err := leveldb.OpenFile(filepath.Join(root, "index"), &opt.Options{ErrorIfExist: true, Strict: opt.StrictAll, Compression: opt.NoCompression,
		BlockCacheCapacity: 4 << 20, WriteBuffer: 4 << 20, OpenFilesCacheCapacity: 16})
	if err != nil {
		_ = scratch.close()
		return nil, err
	}
	scratch.db = db
	return scratch, nil
}

func (scratch *financialLineageScratch) read(hash string) (dagHistoryBody, error) {
	if scratch.db == nil {
		return dagHistoryBody{}, errDagHistoryUnavailable
	}
	if body, ok := scratch.cache.get(hash); ok {
		return body, nil
	}
	raw, err := scratch.db.Get([]byte(financialLineagePrefix+hash), nil)
	if err != nil {
		return dagHistoryBody{}, errDagHistoryUnavailable
	}
	body, err := decodeFinancialLineageNode(hash, raw)
	if err != nil {
		return body, err
	}
	scratch.cache.put(hash, body)
	return body, nil
}

func (scratch *financialLineageScratch) stage(ctx context.Context, execution *financialDagExecution) error {
	if scratch.db == nil {
		return errDagHistoryUnavailable
	}
	batch := new(leveldb.Batch)
	err := stageFinancialLineage(ctx, execution, func(key string, raw []byte) error {
		saved, err := scratch.db.Get([]byte(key), nil)
		if err == nil {
			if !bytes.Equal(saved, raw) {
				return errDagHistoryUnavailable
			}
			return nil
		}
		if err != leveldb.ErrNotFound {
			return errDagHistoryUnavailable
		}
		batch.Put([]byte(key), raw)
		return nil
	})
	if err != nil {
		return err
	}
	if ctx.Err() != nil {
		return ctx.Err()
	}
	if batch.Len() == 0 {
		return nil
	}
	// Loss aborts replay. A scratch index makes no durability/recovery claim.
	return scratch.db.Write(batch, &opt.WriteOptions{Sync: false, NoWriteMerge: true})
}

func (scratch *financialLineageScratch) count(ctx context.Context) (uint64, error) {
	if scratch.db == nil {
		return 0, errDagHistoryUnavailable
	}
	iter := scratch.db.NewIterator(nil, nil)
	defer iter.Release()
	count := uint64(0)
	for iter.Next() {
		if ctx.Err() != nil {
			return 0, ctx.Err()
		}
		key := string(iter.Key())
		if !strings.HasPrefix(key, financialLineagePrefix) || !pubPattern.MatchString(strings.TrimPrefix(key, financialLineagePrefix)) || count == dagSegmentCounterMax {
			return 0, errDagHistoryUnavailable
		}
		count++
	}
	if iter.Error() != nil {
		return 0, errDagHistoryUnavailable
	}
	return count, nil
}

func (scratch *financialLineageScratch) close() error {
	var closeErr error
	if scratch.db != nil {
		closeErr = scratch.db.Close()
		scratch.db = nil
	}
	scratch.cache.clear()
	if scratch.root == "" {
		return closeErr
	}
	// Verify the exact absolute owned target before recursive cleanup.
	info, err := os.Lstat(scratch.root)
	if err != nil {
		if os.IsNotExist(err) {
			scratch.root = ""
			return closeErr
		}
		return err
	}
	absolute, err := filepath.Abs(scratch.root)
	if err != nil {
		return err
	}
	resolved, err := filepath.EvalSymlinks(absolute)
	if err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 || resolved != absolute || filepath.Dir(absolute) != scratch.parent || !strings.HasPrefix(filepath.Base(absolute), "gg-financial-lineage-") {
		return errDagHistoryUnavailable
	}
	if err = os.RemoveAll(absolute); err != nil {
		return err
	}
	scratch.root = ""
	return closeErr
}
