//go:build !js

package main

import (
	"bytes"
	"crypto/sha256"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"testing"

	"github.com/syndtr/goleveldb/leveldb"
	"github.com/syndtr/goleveldb/leveldb/util"
)

func indexedReplayImage(t *testing.T, db *leveldb.DB) string {
	t.Helper()
	digest := sha256.New()
	iterator := db.NewIterator(nil, nil)
	defer iterator.Release()
	for iterator.Next() {
		key, value := iterator.Key(), iterator.Value()
		fmt.Fprintf(digest, "%d:%d:", len(key), len(value))
		digest.Write(key)
		digest.Write(value)
	}
	if iterator.Error() != nil {
		t.Fatal(iterator.Error())
	}
	return fmt.Sprintf("%x", digest.Sum(nil))
}

func TestDagIndexedReplayMatchesOriginalFullOracleAndDoesNotWriteCanonicalDB(t *testing.T) {
	for _, count := range []int{0, 1, 17, 129} {
		t.Run(strconv.Itoa(count), func(t *testing.T) {
			app, keys, root := dagLedgerFixture(t)
			for i := 0; i < count; i++ {
				transactions := 1
				if i == count-1 {
					transactions = 257
				}
				commitPublicFixture(t, app, keys, i%6, transactions)
			}
			state := copyState(app.state)
			expected := *state.DAG
			_ = app.Close()
			oracleStore, err := newDagStore(*app.genesis.DAG, app.anchor, root, false)
			if err != nil {
				t.Fatal(err)
			}
			before := indexedReplayImage(t, oracleStore.db)
			var snapshots []dagPublicSnapshot
			oracle, err := oracleStore.replay(expected, func(value *DagExecution) { snapshots = append(snapshots, publicSnapshot(value)) })
			if err != nil || oracleStore.verifyOrMigratePublic(oracle, snapshots) != nil || indexedReplayImage(t, oracleStore.db) != before {
				t.Fatal("independent former full replay/index oracle failed", err)
			}
			oracleOrder := orderFixture(t, oracle)
			oracleRoot := oracle.history.root.id()
			_ = oracleStore.close()
			store, err := newDagStore(*app.genesis.DAG, app.anchor, root, false)
			if err != nil {
				t.Fatal(err)
			}
			defer store.close()
			var work *dagReplayWork
			store.openReplayScratch = func() (dagReplayScratch, error) {
				value, err := newDagReplayWork()
				if err == nil {
					work = value.(*dagReplayWork)
				}
				return value, err
			}
			store.write = func(*leveldb.Batch) error { t.Fatal("indexed startup wrote canonical DB"); return errors.New("write") }
			next, err := store.replayIndexed(expected)
			if err != nil {
				t.Fatal(err)
			}
			if !bytes.Equal(canonical(next.Accounts), canonical(oracle.Accounts)) || next.Commitment != oracle.Commitment ||
				!bytes.Equal(canonical(next.Manifest), canonical(oracle.Manifest)) || next.history.root.id() != oracleRoot ||
				!bytes.Equal(canonical(next.heads), canonical(oracle.heads)) || !bytes.Equal(canonical(next.nonces), canonical(oracle.nonces)) ||
				!bytes.Equal(canonical(next.sequences), canonical(oracle.sequences)) || next.bytes != oracle.bytes ||
				!bytes.Equal(canonical(orderFixture(t, next)), canonical(oracleOrder)) || indexedReplayImage(t, store.db) != before {
				t.Fatal("streaming replay differed from independent former state/order/index result")
			}
			if !store.retentionReady || store.prefix == nil || store.prefix.historyRoot != oracleRoot || store.replayedMetadata != nil ||
				len(next.pending) != 0 || next.history.root.node != nil || len(store.metadataCache.entries) > dagMetadataCacheNodes ||
				work == nil || !work.closed || work.db != nil || work.entries != count+1+store.meta.HistoryNodes {
				t.Fatal("replay kept historical work in RAM or published an incomplete prefix")
			}
			if _, err := os.Stat(work.directory); !os.IsNotExist(err) {
				t.Fatal("scratch data remained after successful recovery")
			}
			_ = store.close()
			restored, err := newDagEnabledLedger(app.genesis, app.anchor, root, false)
			if err != nil {
				t.Fatal(err)
			}
			defer restored.Close()
			if !bytes.Equal(canonical(restored.state), canonical(state)) || restored.store.(*dagStore).replayedMetadata != nil {
				t.Fatal("ordinary native constructor did not preserve state through indexed replay")
			}
			commitPublicFixture(t, restored, keys, count%6, 1)
		})
	}
}

type faultReplayScratch struct {
	dagReplayScratch
	mode string
}

func (work faultReplayScratch) putManifest(checkpoint uint64, hash string, raw []byte) error {
	if work.mode == "put" {
		return errDagReplayWork
	}
	return work.dagReplayScratch.putManifest(checkpoint, hash, raw)
}
func (work faultReplayScratch) manifest(checkpoint uint64) (string, []byte, error) {
	if work.mode == "get" {
		return "", nil, errDagReplayWork
	}
	if work.mode == "reorder" {
		return work.dagReplayScratch.manifest(0)
	}
	hash, raw, err := work.dagReplayScratch.manifest(checkpoint)
	if work.mode == "changed" {
		hash = DagZero
	}
	return hash, raw, err
}
func (work faultReplayScratch) firstMetadata(hash string) (bool, error) {
	if work.mode == "dedup" {
		return false, errDagReplayWork
	}
	return work.dagReplayScratch.firstMetadata(hash)
}
func (work faultReplayScratch) close() error {
	err := work.dagReplayScratch.close()
	if work.mode == "close" {
		return errDagReplayWork
	}
	return err
}

func TestDagIndexedReplayScratchFailuresNeverPublishOrChangeCanonicalData(t *testing.T) {
	for _, mode := range []string{"open", "put", "get", "reorder", "changed", "dedup", "close"} {
		t.Run(mode, func(t *testing.T) {
			app, keys, root := dagLedgerFixture(t)
			for i := 0; i < 3; i++ {
				commitPublicFixture(t, app, keys, i, 1)
			}
			expected := *app.state.DAG
			_ = app.Close()
			store, err := newDagStore(*app.genesis.DAG, app.anchor, root, false)
			if err != nil {
				t.Fatal(err)
			}
			defer store.close()
			before := indexedReplayImage(t, store.db)
			var scratch *dagReplayWork
			store.openReplayScratch = func() (dagReplayScratch, error) {
				if mode == "open" {
					return nil, errDagReplayWork
				}
				work, err := newDagReplayWork()
				if err != nil {
					return nil, err
				}
				scratch = work.(*dagReplayWork)
				return faultReplayScratch{work, mode}, nil
			}
			if value, err := store.replayIndexed(expected); err == nil || value != nil || store.retentionReady || store.prefix != nil ||
				store.selected != (DagCommitment{}) || indexedReplayImage(t, store.db) != before {
				t.Fatal("failed temporary replay work published or modified canonical state")
			}
			if scratch != nil {
				if _, err := os.Stat(scratch.directory); !os.IsNotExist(err) {
					t.Fatal("temporary data leaked on rejected startup")
				}
			}
		})
	}
}

func TestDagReplayScratchExactMembershipShapeBudgetAndCleanup(t *testing.T) {
	value, err := newDagReplayWork()
	if err != nil {
		t.Fatal(err)
	}
	work := value.(*dagReplayWork)
	defer work.close()
	if !filepath.IsAbs(work.directory) || !strings.HasPrefix(filepath.Base(work.directory), "gg-dag-replay-") {
		t.Fatal("unowned work directory")
	}
	key := strings.Repeat("a", 64)
	if first, err := work.firstMetadata(key); err != nil || !first {
		t.Fatal(err)
	}
	if first, err := work.firstMetadata(key); err != nil || first || work.entries != 1 {
		t.Fatal("deduplication was not exact")
	}
	if err := work.db.Put([]byte("h/"+key), []byte{2}, nil); err != nil {
		t.Fatal(err)
	}
	if _, err := work.firstMetadata(key); err == nil {
		t.Fatal("malformed visited marker was accepted")
	}
	if work.putManifest(DagMaxRecords+1, key, []byte("{}")) == nil || work.putManifest(0, "wrong", []byte("{}")) == nil ||
		work.putManifest(0, key, make([]byte, dagManifestMaxBytes+1)) == nil {
		t.Fatal("work shape/manifest size bound was ignored")
	}
	work.bytes = dagReplayWorkMaxBytes
	if _, err := work.firstMetadata(strings.Repeat("b", 64)); err == nil {
		t.Fatal("logical work-byte quota exceeded")
	}
	work.bytes = 0
	work.entries = dagReplayWorkMaxEntries
	if _, err := work.firstMetadata(strings.Repeat("b", 64)); err == nil {
		t.Fatal("work entry quota exceeded")
	}
	if work.close() != nil || work.close() != nil {
		t.Fatal("work close was not idempotent")
	}
	if _, _, err := work.manifest(0); err == nil {
		t.Fatal("closed work returned data")
	}
	if _, err := os.Stat(work.directory); !os.IsNotExist(err) {
		t.Fatal("scratch not removed")
	}
}

func TestDagReplayScratchLargeExactSetUsesDiskAndKeepsBoundedHeap(t *testing.T) {
	value, err := newDagReplayWork()
	if err != nil {
		t.Fatal(err)
	}
	work := value.(*dagReplayWork)
	defer work.close()
	runtime.GC()
	var before, after runtime.MemStats
	runtime.ReadMemStats(&before)
	const count = dagMetadataMaxNodes
	for i := 0; i < count; i++ {
		hash := hashHex([]byte(strconv.Itoa(i)))
		if first, err := work.firstMetadata(hash); err != nil || !first {
			t.Fatal("missing unique public marker", i, err)
		}
	}
	for i := 0; i < count; i += 17 {
		if first, err := work.firstMetadata(hashHex([]byte(strconv.Itoa(i)))); err != nil || first {
			t.Fatal("disk-backed deduplication lost exact earlier membership", i, err)
		}
	}
	runtime.GC()
	runtime.ReadMemStats(&after)
	files, err := os.ReadDir(filepath.Join(work.directory, "work.leveldb"))
	if err != nil {
		t.Fatal(err)
	}
	tables := 0
	for _, file := range files {
		if strings.HasSuffix(file.Name(), ".ldb") || strings.HasSuffix(file.Name(), ".sst") {
			tables++
		}
	}
	heapGrowth := int64(after.HeapAlloc) - int64(before.HeapAlloc)
	if work.entries != count || work.bytes != count*67 || tables < 1 || heapGrowth > 16*1024*1024 {
		t.Fatal("work set stayed in an unbounded RAM structure or lost its logical quota", work.entries, work.bytes, tables, heapGrowth)
	}
	t.Logf("GG_DAG_REPLAY_WORK markers=%d logical_bytes=%d heap_growth=%d tables=%d write_buffer=%d block_cache=%d", count, work.bytes, heapGrowth, tables, dagReplayWorkBufferBytes, dagReplayWorkCacheBytes)
}

func TestDagManagedReplayWorkReclaimsOnlyOwnedAbandonedWorkAndPreservesLiveLease(t *testing.T) {
	path := filepath.Join(t.TempDir(), "gg-dag-replay-work")
	first, err := newDagReplayWorkAt(path)
	if err != nil {
		t.Fatal(err)
	}
	work := first.(*dagReplayWork)
	defer work.close()
	if _, err := newDagReplayWorkAt(path); err == nil {
		t.Fatal("active workspace lease was removed")
	}
	if _, err := work.firstMetadata(strings.Repeat("c", 64)); err != nil {
		t.Fatal("active work was damaged", err)
	}
	// Simulate process death by releasing OS handles without normal cleanup.
	if work.db.Close() != nil {
		t.Fatal("failed to abandon fixture work")
	}
	work.db = nil
	work.closed = true // the old process can never clean the replacement path
	if os.WriteFile(filepath.Join(path, "work.leveldb", "CURRENT"), []byte("interrupted temporary manifest"), 0600) != nil {
		t.Fatal("failed to create interrupted temporary DB")
	}
	replacement, err := newDagReplayWorkAt(path)
	if err != nil {
		t.Fatal("abandoned scratch could not be discarded independently of canonical DB", err)
	}
	defer replacement.close()
	if value := replacement.(*dagReplayWork); value.entries != 0 || value.bytes != 0 {
		t.Fatal("abandoned scratch became recovered authority")
	}
	if replacement.close() != nil {
		t.Fatal("replacement workspace cleanup failed")
	}
	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Fatal("managed workspace remained after recovery")
	}
}

func TestDagManagedReplayWorkRejectsUnknownContentsAndRecoversIncompleteCreation(t *testing.T) {
	for _, mode := range []string{"empty", "partial-owner", "unknown", "foreign-owner"} {
		t.Run(mode, func(t *testing.T) {
			path := filepath.Join(t.TempDir(), "gg-dag-replay-work")
			if os.Mkdir(path, 0700) != nil {
				t.Fatal("fixture directory")
			}
			if mode == "partial-owner" {
				_ = os.WriteFile(filepath.Join(path, "OWNER"), []byte("gg.dag."), 0600)
			} else if mode == "foreign-owner" {
				_ = os.WriteFile(filepath.Join(path, "OWNER"), []byte("foreign-owned-data"), 0600)
			} else if mode == "unknown" {
				_ = os.WriteFile(filepath.Join(path, "unrelated.txt"), []byte("preserve"), 0600)
			}
			work, err := newDagReplayWorkAt(path)
			if mode == "unknown" || mode == "foreign-owner" {
				if err == nil || work != nil {
					t.Fatal("unknown work data was removed")
				}
				entries, err := os.ReadDir(path)
				if err != nil || len(entries) != 1 {
					t.Fatal("rejected work directory was changed")
				}
			} else {
				if err != nil || work == nil {
					t.Fatal("safe incomplete creation could not recover", err)
				}
				if work.close() != nil {
					t.Fatal("cleanup")
				}
			}
		})
	}
}

func TestDagIndexedReplayRejectsValidlyEncodedFalsePublicIndexesWithoutRepair(t *testing.T) {
	for _, mode := range []string{"aligned-subtree", "order", "older-snapshot"} {
		t.Run(mode, func(t *testing.T) {
			app, keys, root := dagLedgerFixture(t)
			for i := 0; i < 3; i++ {
				commitPublicFixture(t, app, keys, i, 1)
			}
			store := app.store.(*dagStore)
			switch mode {
			case "aligned-subtree":
				if err := store.db.Put([]byte(publicNodeKey(1, 0)), canonical(DagZero), nil); err != nil {
					t.Fatal(err)
				}
			case "order":
				raw, _ := store.db.Get([]byte(publicOrderKey(1)), nil)
				var leaf DagOrderLeaf
				_ = decodePublic(raw, &leaf)
				leaf.Transactions = 2
				if err := store.db.Put([]byte(publicOrderKey(1)), canonical(leaf), nil); err != nil {
					t.Fatal(err)
				}
			case "older-snapshot":
				iterator := store.db.NewIterator(util.BytesPrefix([]byte("pub/s/")), nil)
				var key string
				var old, changed []byte
				for iterator.Next() {
					var snapshot dagPublicSnapshot
					_ = decodePublic(iterator.Value(), &snapshot)
					if snapshot.Commitment.Checkpoint != 1 {
						continue
					}
					key = string(iterator.Key())
					old = append([]byte{}, iterator.Value()...)
					first, _ := strconv.ParseUint(snapshot.Accounts[0].Balance, 10, 64)
					second, _ := strconv.ParseUint(snapshot.Accounts[1].Balance, 10, 64)
					snapshot.Accounts[0].Balance = strconv.FormatUint(first-1, 10)
					snapshot.Accounts[1].Balance = strconv.FormatUint(second+1, 10)
					snapshot.Commitment.AccountRoot = dagRoot(snapshot.Accounts, "GG-DAG-ACCOUNT-v1\x00")
					if store.validPublicSnapshot(snapshot) != nil {
						t.Fatal("negative fixture is not a validly encoded independent false snapshot")
					}
					changed = canonical(snapshot)
					break
				}
				iterator.Release()
				if key == "" {
					t.Fatal("missing older snapshot fixture")
				}
				head, err := store.publicHead()
				if err != nil {
					t.Fatal(err)
				}
				head.Bytes = uint64(int64(head.Bytes) + int64(len(changed)-len(old)))
				batch := new(leveldb.Batch)
				batch.Put([]byte(key), changed)
				batch.Put([]byte("pub/head"), canonical(head))
				if store.db.Write(batch, nil) != nil {
					t.Fatal("failed to create false snapshot")
				}
			}
			if store.checkPublicContents() != nil {
				t.Fatal("negative fixture did not survive syntactic/count preflight")
			}
			before := indexedReplayImage(t, store.db)
			_ = app.Close()
			if value, err := newDagEnabledLedger(app.genesis, app.anchor, root, false); err == nil || value != nil {
				if value != nil {
					value.Close()
				}
				t.Fatal("false public index accepted")
			}
			db, err := leveldb.OpenFile(filepath.Join(root, "gg-dag-public.leveldb"), nil)
			if err != nil {
				t.Fatal(err)
			}
			defer db.Close()
			if indexedReplayImage(t, db) != before {
				t.Fatal("rejected startup repaired/rebuilt versioned data")
			}
		})
	}
}

func TestDagReplayManifestLimitsTotalBeforeEncodingOrExecutingUntrustedBatch(t *testing.T) {
	app, _, _ := dagLedgerFixture(t)
	store := app.store.(*dagStore)
	raw := bytes.Repeat([]byte{'x'}, DagMaxWire/2+1)
	first := hashHex(raw)
	if store.db.Put([]byte("r/"+first), raw, nil) != nil {
		t.Fatal("fixture write")
	}
	raw[0] = 'y'
	second := hashHex(raw)
	if store.db.Put([]byte("r/"+second), raw, nil) != nil {
		t.Fatal("fixture write")
	}
	manifest := app.dag.Manifest
	manifest.Blocks = []string{first, second}
	manifest.Checkpoint = 1
	if next, err := store.replayManifest(app.dag, manifest); err == nil || next != nil || err.Error() != "GG_DAG_BATCH_SIZE" {
		t.Fatal("untrusted total was not bounded before decoding/executing", err)
	}
}
