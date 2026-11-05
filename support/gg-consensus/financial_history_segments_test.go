//go:build !js

package main

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/binary"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"syscall"
	"testing"
	"time"

	abci "github.com/cometbft/cometbft/abci/types"
	cmtjson "github.com/cometbft/cometbft/libs/json"
	"github.com/syndtr/goleveldb/leveldb"
	"github.com/syndtr/goleveldb/leveldb/opt"
	"github.com/syndtr/goleveldb/leveldb/util"
)

func historyPublicFixture(t *testing.T) (*Ledger, *financialNativeApplication, string, string) {
	t.Helper()
	app, backend, keys, producers, root := publicProtocolSDKFixture(t)
	payer := keys[publicFixtureAddress(publicFixtureKey("payer"))]
	receiver := publicFixtureAddress(publicFixtureKey("history-recipient"))
	worker := publicFixtureKey("history-worker")
	_, wire, id := publicFixtureBlock(t, backend.current, producers[0], worker, []Envelope{publicFixturePayment(backend.current, payer, receiver, 0, "3")})
	commitFinancialSDK(t, app, publicFixtureBatch(t, backend.current, nil, wire))
	commitFinancialSDK(t, app, nil)
	return app, backend, root, id
}
func historyLogicalBytes(t *testing.T, store *financialStore) map[string][]byte {
	t.Helper()
	result := map[string][]byte{}
	iter := store.history.iterator(context.Background())
	defer iter.Release()
	for iter.Next() {
		key := string(iter.Key())
		if historyImmutableKey(key) {
			result[key] = append([]byte(nil), iter.Value()...)
		}
	}
	if iter.Error() != nil {
		t.Fatal(iter.Error())
	}
	return result
}
func historySealAll(t *testing.T, store *financialStore) {
	t.Helper()
	store.mu.Lock()
	defer store.mu.Unlock()
	if err := store.history.drainTo(context.Background(), store.head, 0); err != nil {
		t.Fatal(err)
	}
}
func historyAssertSame(t *testing.T, store *financialStore, want map[string][]byte) {
	t.Helper()
	got := historyLogicalBytes(t, store)
	if len(got) != len(want) {
		t.Fatal("logical inventory count changed", len(got), len(want))
	}
	for key, value := range want {
		if !bytes.Equal(got[key], value) {
			t.Fatal("original or derived bytes changed", key)
		}
	}
}
func historyRawDB(t *testing.T, root string) *leveldb.DB {
	t.Helper()
	db, err := leveldb.OpenFile(filepath.Join(root, "gg-financial-dag.leveldb"), &opt.Options{ErrorIfMissing: true, Strict: opt.StrictAll})
	if err != nil {
		t.Fatal(err)
	}
	return db
}
func historyCopyPublicTree(t *testing.T, source, target string) {
	t.Helper()
	if err := os.Mkdir(target, 0700); err != nil {
		t.Fatal(err)
	}
	entries, err := os.ReadDir(source)
	if err != nil {
		t.Fatal(err)
	}
	for _, entry := range entries {
		from, to := filepath.Join(source, entry.Name()), filepath.Join(target, entry.Name())
		info, err := os.Lstat(from)
		if err != nil || info.Mode()&os.ModeSymlink != 0 {
			t.Fatal("unexpected fixture path")
		}
		if info.IsDir() {
			historyCopyPublicTree(t, from, to)
			continue
		}
		if !info.Mode().IsRegular() {
			t.Fatal("nonregular fixture file")
		}
		raw, err := os.ReadFile(from)
		if err != nil || os.WriteFile(to, raw, 0600) != nil {
			t.Fatal("fixture copy failed")
		}
	}
}

func TestFinancialHistoryExactOriginalDerivedProofAndColdEquality(t *testing.T) {
	app, backend, root, block := historyPublicFixture(t)
	ctx := context.Background()
	want := historyLogicalBytes(t, backend.store)
	state := canonical(app.state)
	receipt, err := backend.Receipt(ctx, app.state, financialReceiptSelector{Block: block, Index: 0})
	if err != nil {
		t.Fatal(err)
	}
	account := publicFixtureAddress(publicFixtureKey("history-recipient"))
	beforeAccount, err := backend.Account(ctx, app.state, account)
	if err != nil {
		t.Fatal(err)
	}
	beforeRegistry, err := backend.Registry(ctx, app.state, protocolRegistrySelector{Namespace: "producers", Key: app.genesis.Protocol.InitialProducers[0].Body.ProducerKey})
	if err != nil {
		t.Fatal(err)
	}
	old, err := backend.store.db.GetSnapshot()
	if err != nil {
		t.Fatal(err)
	}
	historySealAll(t, backend.store)
	historyAssertSame(t, backend.store, want)
	for key, value := range want {
		raw, err := backend.store.db.Get([]byte(key), nil)
		if err != nil || !historyReference(raw) || len(raw) != financialHistoryCompactReferenceBytes || string(raw[:8]) != financialHistoryReferenceMagicV2 {
			t.Fatal("active copy not atomically retired into compact v2", key)
		}
		previous, err := backend.store.history.read(ctx, func(k string) ([]byte, error) { return old.Get([]byte(k), nil) }, key)
		if err != nil || !bytes.Equal(previous, value) {
			t.Fatal("pre-publication reader lost exact bytes", key, err)
		}
	}
	old.Release()
	afterReceipt, err := backend.Receipt(ctx, app.state, financialReceiptSelector{Block: block, Index: 0})
	if err != nil || !bytes.Equal(canonical(receipt), canonical(afterReceipt)) {
		t.Fatal("historical receipt changed", err)
	}
	afterAccount, err := backend.Account(ctx, app.state, account)
	if err != nil || !bytes.Equal(canonical(beforeAccount), canonical(afterAccount)) {
		t.Fatal("account proof changed", err)
	}
	afterRegistry, err := backend.Registry(ctx, app.state, protocolRegistrySelector{Namespace: "producers", Key: app.genesis.Protocol.InitialProducers[0].Body.ProducerKey})
	if err != nil || !bytes.Equal(canonical(beforeRegistry), canonical(afterRegistry)) {
		t.Fatal("registry proof changed", err)
	}
	if _, err = backend.Block(ctx, app.state, block); err != nil {
		t.Fatal(err)
	}
	if _, err = backend.RecentBlocks(ctx, app.state, financialRecentSelector{Start: 1, Limit: 1}); err != nil {
		t.Fatal(err)
	}
	if _, err = backend.OriginalCore(ctx, financialOriginalCoreSelector{Block: block, Offset: 0, MaxBytes: 32768}); err != nil {
		t.Fatal(err)
	}
	if app.Close() != nil {
		t.Fatal("close")
	}
	cold, err := newFinancialLedger(app.genesis, app.anchor, root, false)
	if err != nil {
		t.Fatal("cold original replay", err)
	}
	defer cold.Close()
	if !bytes.Equal(state, canonical(cold.state)) {
		t.Fatal("cold semantic state changed")
	}
	historyAssertSame(t, cold.financial.(*financialNativeApplication).store, want)
}

func TestFinancialHistoryPublicationFaultsRecoverOnlyOldOrCompleteView(t *testing.T) {
	for _, point := range []string{"INTENT_SYNC", "FILE_CREATED", "RECORD_WRITTEN", "TREE_WRITTEN", "FILE_WRITTEN", "FILE_SYNC", "FILE_CLOSED", "FILE_PUBLISHED", "READBACK_VERIFIED", "METADATA_BEFORE_SYNC", "METADATA_AFTER_SYNC"} {
		t.Run(point, func(t *testing.T) {
			app, backend, root, block := historyPublicFixture(t)
			want := historyLogicalBytes(t, backend.store)
			state := canonical(app.state)
			injected := errors.New("owned publication fault")
			seen := false
			backend.store.history.fault = func(step string) error {
				if step == point {
					seen = true
					return injected
				}
				return nil
			}
			backend.store.mu.Lock()
			err := backend.store.history.seal(context.Background(), backend.store.head)
			backend.store.failed = true
			backend.store.mu.Unlock()
			if !seen || err != injected {
				t.Fatal("real IO boundary not reached", err)
			}
			if !bytes.Equal(state, canonical(app.state)) {
				t.Fatal("archive fault changed selected money")
			}
			if app.Close() != nil {
				t.Fatal("close")
			}
			if point == "FILE_PUBLISHED" {
				rawdb := historyRawDB(t, root)
				intentBefore, _ := rawdb.Get([]byte("zs/intent"), nil)
				headBefore, _ := rawdb.Get([]byte("head"), nil)
				filePath := filepath.Join(root, "gg-financial-history", historySegmentName(1))
				fileBefore, e := os.ReadFile(filePath)
				if e != nil {
					t.Fatal(e)
				}
				var entry financialJournalEntry
				if decodeStrict(want[financialHeightKey(1)], &entry) != nil {
					t.Fatal("entry fixture")
				}
				replacement := "a"
				if strings.HasPrefix(entry.After, replacement) {
					replacement = "b"
				}
				entry.After = replacement + entry.After[1:]
				badOriginal := canonical(entry)
				if len(badOriginal) != len(want[financialHeightKey(1)]) || rawdb.Put([]byte(financialHeightKey(1)), badOriginal, &opt.WriteOptions{Sync: true}) != nil || rawdb.Close() != nil {
					t.Fatal("same-size semantic-corruption fixture")
				}
				rejected, rejectErr := newFinancialLedger(app.genesis, app.anchor, root, false)
				if rejected != nil {
					_ = rejected.Close()
				}
				if rejectErr == nil {
					t.Fatal("storage intent bypassed full semantic replay")
				}
				rawdb = historyRawDB(t, root)
				intentAfter, _ := rawdb.Get([]byte("zs/intent"), nil)
				headAfter, _ := rawdb.Get([]byte("head"), nil)
				originalAfter, _ := rawdb.Get([]byte(financialHeightKey(1)), nil)
				fileAfter, e := os.ReadFile(filePath)
				if e != nil || !bytes.Equal(intentBefore, intentAfter) || !bytes.Equal(headBefore, headAfter) || !bytes.Equal(fileBefore, fileAfter) || !bytes.Equal(originalAfter, badOriginal) {
					t.Fatal("failed semantic audit mutated pending storage or money")
				}
				if rawdb.Put([]byte(financialHeightKey(1)), want[financialHeightKey(1)], &opt.WriteOptions{Sync: true}) != nil || rawdb.Close() != nil {
					t.Fatal("restore exact original fixture")
				}
			}
			cold, err := newFinancialLedger(app.genesis, app.anchor, root, false)
			if err != nil {
				t.Fatal("exact recovery failed", err)
			}
			defer cold.Close()
			store := cold.financial.(*financialNativeApplication).store
			if !bytes.Equal(state, canonical(cold.state)) {
				t.Fatal("recovery changed state")
			}
			historyAssertSame(t, store, want)
			if _, err = cold.financial.Receipt(context.Background(), cold.state, financialReceiptSelector{Block: block, Index: 0}); err != nil {
				t.Fatal("selected original unavailable", err)
			}
			if _, err = store.db.Get([]byte("zs/intent"), nil); err != leveldb.ErrNotFound {
				t.Fatal("ambiguous intent retained after accepted recovery", err)
			}
			historySealAll(t, store)
			historyAssertSame(t, store, want)
		})
	}
}

func TestFinancialHistoryMissingCorruptForeignDuplicateAndUnknownFilesFailClosed(t *testing.T) {
	for _, kind := range []string{"missing_file", "corrupt_file", "foreign_head", "unknown_metadata", "unknown_file", "reference_alias", "missing_reference", "missing_active_queue", "pointer_length", "pointer_offset", "pointer_path", "pointer_index", "pointer_segment"} {
		t.Run(kind, func(t *testing.T) {
			app, backend, root, _ := historyPublicFixture(t)
			if kind != "missing_active_queue" {
				historySealAll(t, backend.store)
			}
			state := canonical(app.state)
			if app.Close() != nil {
				t.Fatal("close")
			}
			db := historyRawDB(t, root)
			batch := new(leveldb.Batch)
			switch kind {
			case "missing_file":
				if os.Remove(filepath.Join(root, "gg-financial-history", historySegmentName(1))) != nil {
					t.Fatal("remove fixture")
				}
			case "corrupt_file":
				path := filepath.Join(root, "gg-financial-history", historySegmentName(1))
				file, err := os.OpenFile(path, os.O_RDWR, 0)
				if err != nil {
					t.Fatal(err)
				}
				if _, err = file.WriteAt([]byte{0}, 0); err != nil || file.Sync() != nil || file.Close() != nil {
					t.Fatal("corrupt fixture")
				}
			case "foreign_head":
				raw, _ := db.Get([]byte("zs/head"), nil)
				var head financialHistoryHead
				if decodeStrict(raw, &head) != nil {
					t.Fatal("head")
				}
				head.Anchor = strings.Repeat("a", 64)
				batch.Put([]byte("zs/head"), canonical(head))
			case "unknown_metadata":
				batch.Put([]byte("zs/unrecognized"), []byte("x"))
			case "unknown_file":
				if os.WriteFile(filepath.Join(root, "gg-financial-history", "foreign"), []byte("must remain"), 0600) != nil {
					t.Fatal("foreign fixture")
				}
			case "reference_alias":
				first, _ := db.Get([]byte(financialHeightKey(1)), nil)
				batch.Put([]byte(financialHeightKey(2)), first)
			case "missing_reference":
				batch.Delete([]byte(financialHeightKey(1)))
			case "missing_active_queue":
				batch.Delete([]byte(financialHistoryActive + financialHeightKey(1)))
			case "pointer_length", "pointer_offset", "pointer_path", "pointer_index", "pointer_segment":
				raw, e := db.Get([]byte(financialHeightKey(1)), nil)
				ref, version, decodeErr := historyDecodeReference(raw, financialHeightKey(1))
				if e != nil || decodeErr != nil || version != 2 {
					t.Fatal("compact reference fixture", decodeErr)
				}
				switch kind {
				case "pointer_length":
					ref.Length = financialJournalMaxWire + 1
				case "pointer_offset":
					ref.Offset = -1
				case "pointer_path":
					ref.Path = make([]PathItem, 13)
				case "pointer_index":
					ref.Index = financialHistorySegmentRecords
				case "pointer_segment":
					ref.Segment = dagSegmentCounterMax
				}
				changed := append([]byte(nil), raw...)
				binary.BigEndian.PutUint64(changed[8:16], ref.Segment)
				binary.BigEndian.PutUint32(changed[16:20], uint32(ref.Index))
				binary.BigEndian.PutUint32(changed[20:24], uint32(ref.Length))
				binary.BigEndian.PutUint64(changed[24:32], uint64(ref.Offset))
				if kind == "pointer_path" {
					ref.Schema = "gg.financial.history.reference.v1"
					changed = append([]byte(financialHistoryReferenceMagic), canonical(ref)...)
				}
				batch.Put([]byte(financialHeightKey(1)), changed)

			}
			if batch.Len() > 0 && db.Write(batch, &opt.WriteOptions{Sync: true}) != nil {
				t.Fatal("mutation")
			}
			if strings.HasPrefix(kind, "pointer_") {
				parser := &financialHistory{db: db, root: root, anchor: app.anchor, source: app.genesis.FinancialDAG.hash()}
				if _, e := parser.get(context.Background(), financialHeightKey(1)); e == nil {
					t.Fatal("unbounded or foreign reference accepted")
				}
			}
			if db.Close() != nil {
				t.Fatal("close raw")
			}
			bad, err := newFinancialLedger(app.genesis, app.anchor, root, false)
			if bad != nil {
				_ = bad.Close()
			}
			if err == nil {
				t.Fatal("unverified history accepted", kind)
			}
			if !bytes.Equal(state, canonical(app.state)) {
				t.Fatal("failed cold open rewrote runtime state")
			}
			if kind == "unknown_file" {
				raw, err := os.ReadFile(filepath.Join(root, "gg-financial-history", "foreign"))
				if err != nil || string(raw) != "must remain" {
					t.Fatal("unknown file removed or repaired")
				}
			}
		})
	}
}

func TestFinancialHistoryPhysicalDigestCannotBlessWrongCutState(t *testing.T) {
	app, backend, root, _ := historyPublicFixture(t)
	badCut := backend.store.head
	badCut.State = copyState(badCut.State)
	badCut.State.StateRoot = strings.Repeat("a", 64)
	if err := backend.store.history.seal(context.Background(), badCut); err == nil || backend.store.history.head.Segments != 0 {
		t.Fatal("unbound owned cut published")
	}
	historySealAll(t, backend.store)
	if app.Close() != nil {
		t.Fatal("close")
	}
	db := historyRawDB(t, root)
	raw, err := db.Get([]byte(historySegmentKey(1)), nil)
	var segment financialHistorySegment
	if err != nil || decodeStrict(raw, &segment) != nil {
		t.Fatal("segment")
	}
	path := filepath.Join(root, "gg-financial-history", historySegmentName(1))
	fileBytes, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	old := canonical(segment.Header)
	segment.Header.CutState = strings.Repeat("a", 64)
	changed := canonical(segment.Header)
	if len(old) != len(changed) {
		t.Fatal("fixture size")
	}
	copy(fileBytes[12:12+len(changed)], changed)
	digest := sha256.Sum256(fileBytes[:len(fileBytes)-32])
	copy(fileBytes[len(fileBytes)-32:], digest[:])
	segment.Digest = hex.EncodeToString(digest[:])
	if os.WriteFile(path, fileBytes, 0600) != nil {
		t.Fatal("write physical fixture")
	}
	headRaw, _ := db.Get([]byte("zs/head"), nil)
	var head financialHistoryHead
	if decodeStrict(headRaw, &head) != nil {
		t.Fatal("head")
	}
	head.Digest = segment.Digest
	batch := new(leveldb.Batch)
	batch.Put([]byte("zs/head"), canonical(head))
	batch.Put([]byte(historySegmentKey(1)), canonical(segment))
	if db.Write(batch, &opt.WriteOptions{Sync: true}) != nil || db.Close() != nil {
		t.Fatal("write metadata")
	}
	bad, err := newFinancialLedger(app.genesis, app.anchor, root, false)
	if bad != nil {
		_ = bad.Close()
	}
	if err == nil {
		t.Fatal("physical checksum substituted for full cut/state replay")
	}
}

func TestFinancialHistoryMigrationFaultsResumeAfterFullOriginalReplay(t *testing.T) {
	app, backend, base, _ := historyPublicFixture(t)
	for i := 0; i < 260; i++ {
		commitFinancialSDK(t, app, nil)
	}
	want := historyLogicalBytes(t, backend.store)
	state := canonical(app.state)
	genesis, anchor := app.genesis, app.anchor
	if app.Close() != nil {
		t.Fatal("close")
	}
	db := historyRawDB(t, base)
	batch := new(leveldb.Batch)
	iter := db.NewIterator(util.BytesPrefix([]byte("z")), nil)
	for iter.Next() {
		batch.Delete(append([]byte(nil), iter.Key()...))
	}
	if iter.Error() != nil {
		t.Fatal(iter.Error())
	}
	iter.Release()
	if db.Write(batch, &opt.WriteOptions{Sync: true}) != nil || db.Close() != nil {
		t.Fatal("legacy physical fixture")
	}
	for _, failAt := range []int{0, 1, 2, 3} {
		t.Run(fmt.Sprint(failAt), func(t *testing.T) {
			root := filepath.Join(t.TempDir(), "owned")
			historyCopyPublicTree(t, base, root)
			seen := 0
			fault := errors.New("owned init crash")
			configure := func(step string) error {
				if step == "INITIALIZE_COMPLETE_SYNC" && failAt == 3 {
					return fault
				}
				if step == "INITIALIZE_HEAD_SYNC" && failAt == 0 {
					return fault
				}
				if step == "INITIALIZE_CHUNK_SYNC" {
					seen++
					if seen == failAt {
						return fault
					}
				}
				return nil
			}
			opened, _, _, err := openFinancialStoreModeFault(context.Background(), genesis, anchor, root, false, false, configure)
			if opened != nil {
				_ = opened.close()
			}
			if err != fault {
				t.Fatal("migration fault not exercised", err, seen)
			}
			if failAt == 0 {
				rawdb := historyRawDB(t, root)
				if rawdb.Put([]byte(financialHeightKey(1)), []byte(`{}`), &opt.WriteOptions{Sync: true}) != nil || rawdb.Close() != nil {
					t.Fatal("corrupt init fixture")
				}
				rejected, rejectErr := newFinancialLedger(genesis, anchor, root, false)
				if rejected != nil {
					_ = rejected.Close()
				}
				if rejectErr == nil {
					t.Fatal("init marker replaced full original replay")
				}
				rawdb = historyRawDB(t, root)
				if rawdb.Put([]byte(financialHeightKey(1)), want[financialHeightKey(1)], &opt.WriteOptions{Sync: true}) != nil || rawdb.Close() != nil {
					t.Fatal("restore exact fixture original")
				}
			}
			cold, err := newFinancialLedger(genesis, anchor, root, false)
			if err != nil {
				t.Fatal("same original prefix could not resume", err)
			}
			defer cold.Close()
			if !bytes.Equal(state, canonical(cold.state)) {
				t.Fatal("resumed init trusted stale metadata")
			}
			historyAssertSame(t, cold.financial.(*financialNativeApplication).store, want)
		})
	}
}

func TestFinancialHistoryCancellationSpaceAndAmbiguousSyncKeepOriginals(t *testing.T) {
	for _, kind := range []string{"cancel_before", "cancel_after_write", "cancel_after_tree", "space_failure", "space_tree", "close_failure", "ambiguous_sync"} {
		t.Run(kind, func(t *testing.T) {
			app, backend, root, _ := historyPublicFixture(t)
			want := historyLogicalBytes(t, backend.store)
			state := canonical(app.state)
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			if kind == "cancel_before" {
				cancel()
			}
			backend.store.history.fault = func(step string) error {
				if kind == "cancel_after_write" && step == "FILE_WRITTEN" {
					cancel()
				}
				if kind == "cancel_after_tree" && step == "TREE_WRITTEN" {
					cancel()
				}
				if kind == "space_tree" && step == "TREE_WRITTEN" {
					return syscall.ENOSPC
				}
				if kind == "space_failure" && step == "FILE_WRITTEN" {
					return syscall.ENOSPC
				}
				if kind == "close_failure" && step == "FILE_CLOSED" {
					return io.ErrClosedPipe
				}
				if kind == "ambiguous_sync" && step == "METADATA_AFTER_SYNC" {
					return syscall.EIO
				}
				return nil
			}
			backend.store.mu.Lock()
			err := backend.store.history.seal(ctx, backend.store.head)
			backend.store.failed = true
			backend.store.mu.Unlock()
			if err == nil {
				t.Fatal("uncertain operation reported success")
			}
			if !bytes.Equal(state, canonical(app.state)) {
				t.Fatal("fault changed money")
			}
			if app.Close() != nil {
				t.Fatal("close")
			}
			cold, err := newFinancialLedger(app.genesis, app.anchor, root, false)
			if err != nil {
				t.Fatal("originals lost", err)
			}
			defer cold.Close()
			historyAssertSame(t, cold.financial.(*financialNativeApplication).store, want)
		})
	}
}

func TestFinancialHistoryStatusAuditBoundaryAndReaderCloseFence(t *testing.T) {
	app, backend, root, _ := historyPublicFixture(t)
	ctx := context.Background()
	query, err := app.Query(ctx, &abci.RequestQuery{Path: "/gg/protocol/local-history-status"})
	if err != nil || query.Code != 0 {
		t.Fatal(err)
	}
	var status map[string]any
	if decodeStrict(query.Value, &status) != nil || status["verified_through"] != "0" || status["retained_through"] != "2" || status["checkpoint_trusted"] != false {
		t.Fatal("live commits claimed cold replay", string(query.Value))
	}
	read, release, err := backend.store.protocolQueryRead(ctx)
	if err != nil {
		t.Fatal(err)
	}
	done := make(chan error, 1)
	go func() { done <- app.Close() }()
	deadline := time.Now().Add(time.Second)
	for time.Now().Before(deadline) {
		backend.store.mu.Lock()
		closing := backend.store.db == nil
		backend.store.mu.Unlock()
		if closing {
			break
		}
		time.Sleep(time.Millisecond)
	}
	if _, err = read(financialHeightKey(1)); err != nil {
		t.Fatal("close invalidated owned reader lease", err)
	}
	select {
	case <-done:
		t.Fatal("closed DB while read lease retained")
	default:
	}
	release()
	select {
	case err = <-done:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(time.Second):
		t.Fatal("close fence did not drain")
	}
	cold, err := newFinancialLedger(app.genesis, app.anchor, root, false)
	if err != nil {
		t.Fatal(err)
	}
	defer cold.Close()
	query, err = cold.Query(ctx, &abci.RequestQuery{Path: "/gg/protocol/local-history-status"})
	if err != nil || query.Code != 0 || decodeStrict(query.Value, &status) != nil || status["verified_through"] != "2" {
		t.Fatal("cold audit boundary absent", err)
	}
	bad, err := cold.Query(ctx, &abci.RequestQuery{Path: "/gg/protocol/local-history-status", Height: 1})
	if err != nil || bad.Code == 0 {
		t.Fatal("local status mislabelled historical proof")
	}
}

func TestFinancialHistoryPublicExportRestoreAndObserverStartupUseResolver(t *testing.T) {
	request, original := financialObserverArchiveFixture(t, financialLineageSourceSchema)
	if _, err := restoreFinancialObserver(context.Background(), request, nil); err != nil {
		t.Fatal(err)
	}
	app, err := newFinancialLedger(request.Genesis, request.GenesisHash, request.RestoreRoot, false)
	if err != nil {
		t.Fatal(err)
	}
	store := app.financial.(*financialNativeApplication).store
	want := historyLogicalBytes(t, store)
	historySealAll(t, store)
	if app.Close() != nil {
		t.Fatal("close")
	}
	archiveRequest := request.financialArchiveCommand
	archiveRequest.Root = request.RestoreRoot
	archiveRequest.RestoreRoot = ""
	var output bytes.Buffer
	if _, err = exportFinancialArchive(context.Background(), &output, archiveRequest); err != nil || !bytes.Equal(original, output.Bytes()) {
		t.Fatal("public full-original archive changed across segment tier", err)
	}
	cold, err := newFinancialLedger(request.Genesis, request.GenesisHash, request.RestoreRoot, false)
	if err != nil {
		t.Fatal(err)
	}
	defer cold.Close()
	historyAssertSame(t, cold.financial.(*financialNativeApplication).store, want)
	boot := Bootstrap{Root: request.RestoreRoot, Genesis: request.Genesis, GenesisHash: request.GenesisHash, observer: &nativeObserverBootstrap{ObserverGrant: request.ObserverGrant}}
	if err = prepareFinancialObserverSDKStartup(context.Background(), boot, cold, request.RestoreRoot); err != nil {
		t.Fatal("owned SDK handoff lost archived headers", err)
	}
}

func TestFinancialHistoryDenseDerivedRolloverNeedsMultipleBoundedSegments(t *testing.T) {
	app, backend, keys, producers, _ := publicProtocolSDKFixture(t)
	payer := keys[publicFixtureAddress(publicFixtureKey("payer"))]
	payments := make([]Envelope, 5000)
	for i := range payments {
		receiver := publicFixtureAddress(publicFixtureKey(fmt.Sprintf("history distinct recipient %d", i)))
		payments[i] = publicFixturePayment(backend.current, payer, receiver, uint64(i), "1")
	}
	_, wire, _ := publicFixtureBlock(t, backend.current, producers[0], publicFixtureKey("history dense worker"), payments)
	commitFinancialSDK(t, app, publicFixtureBatch(t, backend.current, nil, wire))
	if app.state.FinancialDAG.Applied != 5000 || app.state.FinancialDAG.Rejected != 0 {
		t.Fatal("not real distinct-account execution")
	}
	want := historyLogicalBytes(t, backend.store)
	if len(want) <= financialHistorySegmentRecords {
		t.Fatal("fixture does not exceed one segment")
	}
	historySealAll(t, backend.store)
	if backend.store.history.head.Segments < 2 || backend.store.history.activeBytes != 0 || backend.store.history.archivedOriginals != 1 {
		t.Fatal("one small derived segment left unbounded suffix")
	}
	historyAssertSame(t, backend.store, want)
}

func TestFinancialHistoryActualMissingSegmentLatchesFaultButUnknownSelectorDoesNot(t *testing.T) {
	app, backend, _, block := historyPublicFixture(t)
	ctx := context.Background()
	if _, err := backend.Receipt(ctx, app.state, financialReceiptSelector{Block: strings.Repeat("a", 64), Index: 0}); err == nil {
		t.Fatal("unknown block selector accepted")
	}
	status, _, err := backend.LocalHistoryStatus(ctx)
	if err != nil || status["state"] != "READY" || status["archive_fault"] != nil {
		t.Fatal("selector miss tainted storage", err)
	}
	account := publicFixtureAddress(publicFixtureKey("history-recipient"))
	if _, err = backend.Account(ctx, app.state, account); err != nil {
		t.Fatal("cache priming", err)
	}
	historySealAll(t, backend.store)
	if err = os.Remove(filepath.Join(backend.store.history.directory(), historySegmentName(1))); err != nil {
		t.Fatal("owned missing-file fixture", err)
	}
	if _, err = backend.Receipt(ctx, app.state, financialReceiptSelector{Block: block, Index: 0}); err == nil {
		t.Fatal("missing selected original reported available")
	}
	status, _, err = backend.LocalHistoryStatus(ctx)
	if err != nil || status["state"] != "UNAVAILABLE" || status["archive_fault"] != "GG_FINANCIAL_HISTORY_UNAVAILABLE" {
		t.Fatal("actual fault absent from public local report", err)
	}
	if _, err = backend.Account(ctx, app.state, account); err == nil {
		t.Fatal("cached account bypassed known required-history failure")
	}
	if _, err = app.CheckTx(ctx, &abci.RequestCheckTx{Tx: nil}); err != errFinancialStore {
		t.Fatal("new selection bypassed known history fault", err)
	}
	if _, _, err = backend.CutTransaction(ctx, 0); err == nil {
		t.Fatal("cut production continued after known history failure")
	}
}

func TestFinancialHistoryExclusivePublicationSupportsOwnedLongPaths(t *testing.T) {
	root := t.TempDir()
	for len(root) < 300 {
		root = filepath.Join(root, "owned-history-long-path-component")
		if err := os.Mkdir(root, 0700); err != nil {
			t.Fatal(err)
		}
	}
	stage, final := filepath.Join(root, "segment.pending"), filepath.Join(root, "segment.ggfh")
	if err := financialHistoryReserve(root, 4096); err != nil {
		t.Fatal("owned long-path free-space query", err)
	}
	file, err := os.OpenFile(stage, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = file.Write([]byte("exact public history bytes")); err != nil {
		file.Close()
		t.Fatal(err)
	}
	syncErr := file.Sync()
	closeErr := file.Close()
	if syncErr != nil || closeErr != nil {
		t.Fatal("actual file flush/close failed")
	}
	if err = financialHistoryPublish(stage, final); err != nil {
		t.Fatal("owned long-path exclusive publish", err)
	}
	raw, err := os.ReadFile(final)
	if err != nil || string(raw) != "exact public history bytes" {
		t.Fatal("wrong publication target", err)
	}
	if err = os.WriteFile(stage, []byte("must not replace"), 0600); err != nil {
		t.Fatal(err)
	}
	if err = financialHistoryPublish(stage, final); err == nil {
		t.Fatal("immutable publication replaced existing file")
	}
	raw, err = os.ReadFile(final)
	if err != nil || string(raw) != "exact public history bytes" {
		t.Fatal("exclusive target changed", err)
	}
}

func TestFinancialHistoryCommitteeOperationRewardsAcrossSegmentsRemainExact(t *testing.T) {
	app, backend, keys, producers, root := publicProtocolSDKFixture(t)
	ctx := context.Background()
	payer := keys[app.genesis.FinancialAccounts.Allocations[0].Address]
	before := app.state.Protocol.Committee
	next := before
	next.Members = append([]publicConsensusMember(nil), before.Members...)
	next.Epoch++
	next.Members[0].Power = "2"
	from, _ := publicCommitteeRoot(before, app.anchor)
	change := protocolCommitteeOperation{Body: protocolCommitteeBody{ExpiresHeight: 64, FromRoot: from, Genesis: app.anchor, Next: next, Schema: "gg.financial.committee-proposal.v1", UnusedKeyPolicy: protocolUnusedKeyPolicy}, Ballots: []protocolCommitteeBallot{}, Consents: []protocolMemberConsent{}}
	operation := protocolOperation{Committee: &change, Schema: "gg.financial.protocol-operation.v1"}
	proposal, _ := protocolOperationRoot(operation)
	for _, member := range before.Members[:3] {
		message := []byte("GG-FINANCIAL-COMMITTEE-BALLOT-v1\x00" + proposal + "\x00" + member.ValidatorKey)
		change.Ballots = append(change.Ballots, protocolCommitteeBallot{ValidatorKey: member.ValidatorKey, Signature: hex.EncodeToString(ed25519.Sign(keys[member.AccountKey], message))})
	}
	operation = publicFixtureAuthorize(t, backend.current, operation, payer, 0)
	commitFinancialSDK(t, app, publicFixtureBatch(t, backend.current, []protocolOperation{operation}))
	decision := canonical(app.state)
	historySealAll(t, backend.store)
	commitFinancialSDK(t, app, nil)
	commitFinancialSDK(t, app, nil)
	if app.state.Protocol.Committee.Epoch != 1 {
		t.Fatal("real H+2 transition missing")
	}
	payment := publicFixturePayment(backend.current, payer, publicFixtureAddress(publicFixtureKey("history after committee recipient")), 1, "7")
	_, wire, block := publicFixtureBlock(t, backend.current, producers[0], publicFixtureKey("history after committee worker"), []Envelope{payment})
	commitFinancialSDK(t, app, publicFixtureBatch(t, backend.current, nil, wire))
	if _, err := app.FinalizeBlock(ctx, &abci.RequestFinalizeBlock{Height: app.state.Height + 1, Time: time.Unix(app.genesis.GenesisTime+10, 0)}); err != nil {
		t.Fatal(err)
	}
	if _, err := app.Commit(ctx, &abci.RequestCommit{}); err != nil {
		t.Fatal(err)
	}
	rewardSelector := protocolRewardSelector{Address: app.genesis.Protocol.InitialProducers[0].Body.RewardAccount, Index: 1}
	reward, err := backend.Reward(ctx, app.state, rewardSelector)
	if err != nil {
		t.Fatal("real settlement proof", err)
	}
	opSelector := protocolRegistrySelector{Namespace: "operations", Key: protocolOperationReceiptKey(publicFixtureAddress(payer), 0)}
	opProof, err := backend.Registry(ctx, app.state, opSelector)
	if err != nil {
		t.Fatal(err)
	}
	want := historyLogicalBytes(t, backend.store)
	state := canonical(app.state)
	historySealAll(t, backend.store)
	stored, err := backend.CommitteeState(ctx, 1)
	if err != nil || !bytes.Equal(canonical(stored), decision) {
		t.Fatal("archived predecessor decision", err)
	}
	afterReward, err := backend.Reward(ctx, app.state, rewardSelector)
	if err != nil || !bytes.Equal(canonical(reward), canonical(afterReward)) {
		t.Fatal("archived settlement changed", err)
	}
	afterOp, err := backend.Registry(ctx, app.state, opSelector)
	if err != nil || !bytes.Equal(canonical(opProof), canonical(afterOp)) {
		t.Fatal("archived operation payload changed", err)
	}
	if _, err = backend.Receipt(ctx, app.state, financialReceiptSelector{Block: block, Index: 0}); err != nil {
		t.Fatal("archived post-transition original", err)
	}
	if app.Close() != nil {
		t.Fatal("close")
	}
	cold, err := newFinancialLedger(app.genesis, app.anchor, root, false)
	if err != nil {
		t.Fatal("cold committee/settlement history", err)
	}
	defer cold.Close()
	if !bytes.Equal(canonical(cold.state), state) {
		t.Fatal("cold monetary or committee state changed")
	}
	historyAssertSame(t, cold.financial.(*financialNativeApplication).store, want)
}

func historyIntegrityFixture(t *testing.T, settle bool) (*Ledger, *financialNativeApplication, string, []string, State) {
	t.Helper()
	app, backend, keys, producers, root := publicProtocolSDKFixture(t)
	payer := keys[app.genesis.FinancialAccounts.Allocations[0].Address]
	blocks := []string{}
	var first State
	for i := 0; i < 3; i++ {
		payment := publicFixturePayment(backend.current, payer, publicFixtureAddress(publicFixtureKey("history integrity receiver")), uint64(i), "1")
		_, wire, id := publicFixtureBlock(t, backend.current, producers[0], publicFixtureKey("history integrity worker"), []Envelope{payment})
		commitFinancialSDK(t, app, publicFixtureBatch(t, backend.current, nil, wire))
		blocks = append(blocks, id)
		if i == 0 {
			first = copyState(app.state)
		}
	}
	if settle {
		if _, err := app.FinalizeBlock(context.Background(), &abci.RequestFinalizeBlock{Height: app.state.Height + 1, Time: time.Unix(app.genesis.GenesisTime+10, 0)}); err != nil {
			t.Fatal(err)
		}
		if _, err := app.Commit(context.Background(), &abci.RequestCommit{}); err != nil {
			t.Fatal(err)
		}
	}
	return app, backend, root, blocks, first
}

// Real owned LevelDB mutation, including its nonauthoritative active queue so
// cold rejection exercises the required semantic record rather than only a
// scheduler length mismatch. This never uses the native signing/write APIs.
func historyTamperActive(t *testing.T, db *leveldb.DB, key string, value []byte) {
	t.Helper()
	batch := new(leveldb.Batch)
	if value == nil {
		batch.Delete([]byte(key))
		batch.Delete([]byte(financialHistoryActive + key))
	} else {
		batch.Put([]byte(key), value)
		if !historyReference(value) {
			var size [8]byte
			binary.BigEndian.PutUint64(size[:], uint64(6+len(key)+len(value)))
			batch.Put([]byte(financialHistoryActive+key), size[:])
		}
	}
	if err := db.Write(batch, &opt.WriteOptions{Sync: true}); err != nil {
		t.Fatal(err)
	}
}
func historyAssertFaultAndExactColdRepair(t *testing.T, app *Ledger, backend *financialNativeApplication, root, key string, original []byte) {
	t.Helper()
	ctx := context.Background()
	before := canonical(app.state)
	status, _, err := backend.LocalHistoryStatus(ctx)
	if err != nil || status["state"] != "UNAVAILABLE" || status["archive_fault"] != "GG_FINANCIAL_HISTORY_UNAVAILABLE" || !backend.store.history.failed.Load() || backend.store.health() == nil {
		t.Fatal("required semantic fault was not latched", err)
	}
	if _, err = app.CheckTx(ctx, &abci.RequestCheckTx{Tx: nil}); err != errFinancialStore {
		t.Fatal("known storage fault bypassed selection guard", err)
	}
	if _, err = app.FinalizeBlock(ctx, &abci.RequestFinalizeBlock{Height: app.state.Height + 1, Time: time.Unix(0, backend.store.timeNs+1000000)}); err == nil {
		t.Fatal("new valid empty commit context accepted after required fault")
	}
	if generalFinancialAccounts(app.genesis) {
		if _, err = backend.Account(ctx, app.state, app.genesis.FinancialAccounts.Allocations[0].Address); err == nil {
			t.Fatal("cached account path bypassed known history failure")
		}
	} else if app.genesis.FinancialDAG.hasLineage() {
		if _, err = backend.store.readLineageNode(app.state.FinancialDAG.LineageRoot); err == nil {
			t.Fatal("cached lineage path bypassed known history failure")
		}
	}
	if !bytes.Equal(before, canonical(app.state)) {
		t.Fatal("failure changed money")
	}
	if err = app.Close(); err != nil {
		t.Fatal(err)
	}
	bad, err := newFinancialLedger(app.genesis, app.anchor, root, false)
	if bad != nil {
		_ = bad.Close()
	}
	if err == nil {
		t.Fatal("corrupt required row accepted on cold replay", key)
	}
	db := historyRawDB(t, root)
	historyTamperActive(t, db, key, original)
	if db.Close() != nil {
		t.Fatal("close repair fixture")
	}
	cold, err := newFinancialLedger(app.genesis, app.anchor, root, false)
	if err != nil {
		t.Fatal("exact originals could not be reverified", err)
	}
	defer cold.Close()
	if !bytes.Equal(before, canonical(cold.state)) {
		t.Fatal("cold repair changed exact state")
	}
	status, _, err = cold.financial.(*financialNativeApplication).LocalHistoryStatus(ctx)
	if err != nil || status["state"] != "READY" || status["verified_through"] != fmt.Sprint(cold.state.Height) {
		t.Fatal("fresh full replay did not establish a new healthy owner", err)
	}
}

func TestFinancialHistoryRequiredActiveDiscoveryAndMMRFaultsLatch(t *testing.T) {
	for _, kind := range []string{"bo_missing", "bo_malformed", "bo_wrong_reference", "t_missing", "t_malformed", "t_wrong_digest", "p_malformed", "p_semantic"} {
		t.Run(kind, func(t *testing.T) {
			app, backend, root, blocks, _ := historyIntegrityFixture(t, false)
			ctx := context.Background()
			key := financialBlockOrderKey(1)
			if strings.HasPrefix(kind, "t_") {
				key = financialSummaryNodeKey(0, 2)
			}
			if strings.HasPrefix(kind, "p_") {
				key = "p/" + blocks[0]
			}
			original, err := backend.store.db.Get([]byte(key), nil)
			if err != nil {
				t.Fatal("required fixture", err)
			}
			// Populate the ordinary verified cache before discovering an independent
			// record fault; the global fault fence must invalidate its use too.
			if _, err = backend.Account(ctx, app.state, app.genesis.FinancialAccounts.Allocations[0].Address); err != nil {
				t.Fatal(err)
			}
			var mutation []byte
			switch kind {
			case "bo_missing", "t_missing":
			case "bo_malformed", "t_malformed", "p_malformed":
				mutation = []byte(`{}`)
			case "bo_wrong_reference":
				mutation = []byte(blocks[1])
			case "t_wrong_digest":
				mutation = []byte(strings.Repeat("a", 64))
			case "p_semantic":
				var row financialReceiptArchive
				if decodeStrict(original, &row) != nil {
					t.Fatal("archive")
				}
				row.Summary.ContextHash = strings.Repeat("a", 64)
				mutation = canonical(row)
			}
			historyTamperActive(t, backend.store.db, key, mutation)
			if strings.HasPrefix(kind, "bo_") {
				_, err = backend.RecentBlocks(ctx, app.state, financialRecentSelector{Start: 1, Limit: 1})
			} else {
				_, err = backend.Receipt(ctx, app.state, financialReceiptSelector{Block: blocks[0], Index: 0})
			}
			if err == nil {
				t.Fatal("required active corruption reported success", kind)
			}
			historyAssertFaultAndExactColdRepair(t, app, backend, root, key, original)
		})
	}
}

func TestFinancialHistoryRequiredOriginalSemanticCryptoFaultsLatch(t *testing.T) {
	for _, kind := range []string{"missing", "malformed", "wrong_height", "invalid_real_signature", "new_immutable_collision"} {
		t.Run(kind, func(t *testing.T) {
			app, backend, root, blocks, _ := historyIntegrityFixture(t, false)
			if kind == "new_immutable_collision" {
				var producer ed25519.PrivateKey
				for _, name := range []string{"Windows", "Linux", "Termux"} {
					key := publicFixtureKey(name + ":producer")
					if publicFixtureAddress(key) == app.genesis.FinancialDAG.Producers[0] {
						producer = key
						break
					}
				}
				if producer == nil {
					t.Fatal("public producer fixture")
				}
				payment := publicFixturePayment(backend.current, publicFixtureKey("payer"), publicFixtureAddress(publicFixtureKey("history integrity receiver")), 3, "1")
				_, wire, _ := publicFixtureBlock(t, backend.current, producer, publicFixtureKey("history integrity worker"), []Envelope{payment})
				batch := publicFixtureBatch(t, backend.current, nil, wire)
				if _, err := app.FinalizeBlock(context.Background(), &abci.RequestFinalizeBlock{Height: app.state.Height + 1, Time: time.Unix(0, backend.store.timeNs+1000000), Txs: [][]byte{batch}}); err != nil {
					t.Fatal("actual valid new execution before collision", err)
				}
				key := financialSummaryNodeKey(0, app.state.FinancialDAG.Blocks+1)
				if _, err := backend.store.db.Get([]byte(key), nil); err != leveldb.ErrNotFound {
					t.Fatal("new immutable key already existed")
				}
				historyTamperActive(t, backend.store.db, key, []byte(strings.Repeat("a", 64)))
				if _, err := app.Commit(context.Background(), &abci.RequestCommit{}); err == nil {
					t.Fatal("unexpected immutable collision published money")
				}
				historyAssertFaultAndExactColdRepair(t, app, backend, root, key, nil)
				return
			}
			key := financialHeightKey(1)
			original, err := backend.store.db.Get([]byte(key), nil)
			if err != nil {
				t.Fatal(err)
			}
			var mutation []byte
			if kind == "malformed" {
				mutation = []byte(`{}`)
			} else if kind != "missing" {
				var entry financialJournalEntry
				if decodeStrict(original, &entry) != nil {
					t.Fatal("journal")
				}
				if kind == "wrong_height" {
					entry.Height++
				} else {
					var batch financialDagBatch
					if decodeStrict(entry.Transaction, &batch) != nil {
						t.Fatal("batch")
					}
					raw, err := base64.StdEncoding.Strict().DecodeString(batch.Blocks[0])
					if err != nil {
						t.Fatal(err)
					}
					var block financialProtocolBlock
					if decodeStrict(raw, &block) != nil {
						t.Fatal("signed block")
					}
					replacement := "a"
					if strings.HasPrefix(block.Signature, replacement) {
						replacement = "b"
					}
					block.Signature = replacement + block.Signature[1:]
					batch.Blocks[0] = base64.StdEncoding.EncodeToString(canonical(block))
					entry.Transaction = canonical(batch)
				}
				mutation = canonical(entry)
			}
			historyTamperActive(t, backend.store.db, key, mutation)
			if _, err = backend.Receipt(context.Background(), app.state, financialReceiptSelector{Block: blocks[0], Index: 0}); err == nil {
				t.Fatal("required original corruption not rejected")
			}
			historyAssertFaultAndExactColdRepair(t, app, backend, root, key, original)
		})
	}
}

func TestFinancialHistoryAuthenticatedRewardFaultsLatch(t *testing.T) {
	for _, kind := range []string{"missing", "malformed", "semantic"} {
		t.Run(kind, func(t *testing.T) {
			app, backend, root, _, _ := historyIntegrityFixture(t, true)
			ctx := context.Background()
			selector := protocolRewardSelector{Address: app.genesis.Protocol.InitialProducers[0].Body.RewardAccount, Index: 1}
			proof, err := backend.Reward(ctx, app.state, selector)
			if err != nil {
				t.Fatal("real reward fixture", err)
			}
			if checkFinancialCertifiedReward(ctx, proof, app.state, app.genesis, selector) != nil {
				t.Fatal("independent reward verification")
			}
			key := protocolRewardPrefix + protocolRewardReceiptID(proof.Receipt)
			original, err := backend.store.db.Get([]byte(key), nil)
			if err != nil {
				t.Fatal(err)
			}
			var mutation []byte
			if kind == "malformed" {
				mutation = []byte(`{}`)
			} else if kind == "semantic" {
				var row protocolRewardReceipt
				if decodeStrict(original, &row) != nil {
					t.Fatal("reward")
				}
				row.CreditsRoot = strings.Repeat("a", 64)
				mutation = canonical(row)
			}
			historyTamperActive(t, backend.store.db, key, mutation)
			if _, err = backend.Reward(ctx, app.state, selector); err == nil {
				t.Fatal("authenticated reward reference lost without failure")
			}
			historyAssertFaultAndExactColdRepair(t, app, backend, root, key, original)
		})
	}
}

func historyCommitGovernance(t *testing.T, app *Ledger, backend *financialNativeApplication, keys map[string]ed25519.PrivateKey) {
	t.Helper()
	before := app.state.Protocol.Committee
	next := before
	next.Members = append([]publicConsensusMember(nil), before.Members...)
	next.Epoch++
	next.Members[0].Power = "2"
	from, _ := publicCommitteeRoot(before, app.anchor)
	change := protocolCommitteeOperation{Body: protocolCommitteeBody{ExpiresHeight: 64, FromRoot: from, Genesis: app.anchor, Next: next, Schema: "gg.financial.committee-proposal.v1", UnusedKeyPolicy: protocolUnusedKeyPolicy}, Ballots: []protocolCommitteeBallot{}, Consents: []protocolMemberConsent{}}
	operation := protocolOperation{Committee: &change, Schema: "gg.financial.protocol-operation.v1"}
	proposal, _ := protocolOperationRoot(operation)
	for _, member := range before.Members[:3] {
		change.Ballots = append(change.Ballots, protocolCommitteeBallot{ValidatorKey: member.ValidatorKey, Signature: hex.EncodeToString(ed25519.Sign(keys[member.AccountKey], []byte("GG-FINANCIAL-COMMITTEE-BALLOT-v1\x00"+proposal+"\x00"+member.ValidatorKey)))})
	}
	operation = publicFixtureAuthorize(t, backend.current, operation, keys[app.genesis.FinancialAccounts.Allocations[0].Address], 0)
	commitFinancialSDK(t, app, publicFixtureBatch(t, backend.current, []protocolOperation{operation}))
}
func TestFinancialHistoryKnownCommitteeVsOptionalSelectorIntegrity(t *testing.T) {
	for _, kind := range []string{"missing", "malformed", "semantic"} {
		t.Run(kind, func(t *testing.T) {
			app, backend, keys, _, root := publicProtocolSDKFixture(t)
			ctx := context.Background()
			if _, err := backend.CommitteeState(ctx, 1); err == nil || backend.store.history.failed.Load() {
				t.Fatal("unknown future committee poisoned source")
			}
			oldRead, oldRelease, oldThrough, viewErr := backend.store.protocolQueryReadView(ctx)
			if viewErr != nil || oldThrough != 0 {
				t.Fatal("old committee view", viewErr)
			}
			releaseOld := func() {
				if oldRelease != nil {
					oldRelease()
					oldRelease = nil
				}
			}
			defer releaseOld()
			historyCommitGovernance(t, app, backend, keys)
			if _, err := oldRead(financialCommitteeStateKey(1)); err != leveldb.ErrNotFound || backend.store.history.failed.Load() {
				releaseOld()
				t.Fatal("old snapshot saw later decision or poisoned source", err)
			}
			if _, err := oldRead(financialHeightKey(1)); err != leveldb.ErrNotFound || backend.store.history.failed.Load() {
				releaseOld()
				t.Fatal("later global height poisoned old snapshot", err)
			}
			releaseOld()

			if _, err := backend.CommitteeState(ctx, 1); err != nil {
				t.Fatal("actual predecessor decision missing", err)
			}
			key := financialCommitteeStateKey(1)
			original, err := backend.store.db.Get([]byte(key), nil)
			if err != nil {
				t.Fatal(err)
			}
			var mutation []byte
			if kind == "malformed" {
				mutation = []byte(`{}`)
			} else if kind == "semantic" {
				var row State
				if decodeStrict(original, &row) != nil {
					t.Fatal("decision")
				}
				row.Protocol.PendingCommittee.Next.Epoch++
				mutation = canonical(row)
			}
			historyTamperActive(t, backend.store.db, key, mutation)
			if _, err = backend.CommitteeState(ctx, 1); err == nil {
				t.Fatal("known decision corruption not rejected")
			}
			historyAssertFaultAndExactColdRepair(t, app, backend, root, key, original)
		})
	}
}

func TestFinancialHistoryRequiredTreeAndSDKHeaderFaultsLatch(t *testing.T) {
	for _, kind := range []string{"fa", "pr", "fl", "h_missing", "h_semantic"} {
		t.Run(kind, func(t *testing.T) {
			var app *Ledger
			var backend *financialNativeApplication
			var root, key string
			var boot Bootstrap
			if kind == "fa" || kind == "pr" {
				app, backend, root, _, _ = historyIntegrityFixture(t, false)
				if kind == "fa" {
					key = financialAccountPrefix + app.state.AccountTree.Hash
					backend.store.accountCache.clear()
				} else {
					link, err := protocolRegistryRootFor(app.state, "producers")
					if err != nil {
						t.Fatal(err)
					}
					key = protocolRegistryPrefix + link.Hash
					backend.store.protocolCache.clear()
				}
			} else {
				request, _ := financialObserverArchiveFixture(t, financialLineageSourceSchema)
				if _, err := restoreFinancialObserver(context.Background(), request, nil); err != nil {
					t.Fatal(err)
				}
				root = request.RestoreRoot
				var err error
				app, err = newFinancialLedger(request.Genesis, request.GenesisHash, root, false)
				if err != nil {
					t.Fatal(err)
				}
				t.Cleanup(func() { _ = app.Close() })
				backend = app.financial.(*financialNativeApplication)
				boot = Bootstrap{Root: root, Genesis: request.Genesis, GenesisHash: request.GenesisHash, observer: &nativeObserverBootstrap{ObserverGrant: request.ObserverGrant}}
				if kind == "fl" {
					key = financialLineagePrefix + app.state.FinancialDAG.LineageRoot
					backend.store.lineageCache.clear()
				} else {
					key = financialSDKHeaderKey(1)
				}
			}
			original, err := backend.store.db.Get([]byte(key), nil)
			if err != nil {
				t.Fatal(err)
			}
			mutation := []byte(`{}`)
			if kind == "h_missing" {
				mutation = nil
			} else if kind == "h_semantic" {
				header, err := checkedFinancialSDKHeader(original, app.genesis, 1)
				if err != nil {
					t.Fatal(err)
				}
				header.ChainID = "z" + header.ChainID[1:]
				mutation, err = cmtjson.Marshal(header)
				if err != nil {
					t.Fatal(err)
				}
			}
			historyTamperActive(t, backend.store.db, key, mutation)
			switch kind {
			case "fa":
				_, err = backend.Account(context.Background(), app.state, app.genesis.FinancialAccounts.Allocations[0].Address)
			case "pr":
				_, err = backend.Registry(context.Background(), app.state, protocolRegistrySelector{Namespace: "producers", Key: app.genesis.FinancialDAG.Producers[0]})
			case "fl":
				_, err = backend.store.readLineageNode(app.state.FinancialDAG.LineageRoot)
			default:
				err = prepareFinancialObserverSDKStartup(context.Background(), boot, app, root)
			}
			if err == nil {
				t.Fatal("required active tree/header corruption returned success", kind)
			}
			// Legacy observer fixtures lack the general-account query. The health,
			// status, new-finalize and exact cold checks are shared for all modes.
			historyAssertFaultAndExactColdRepair(t, app, backend, root, key, original)
		})
	}
}

func TestFinancialHistoryOptionalSelectorsAndCancellationStayHealthy(t *testing.T) {
	app, backend, _, blocks, first := historyIntegrityFixture(t, true)
	ctx := context.Background()
	unknown := strings.Repeat("a", 64)
	checks := []func() error{
		func() error {
			_, err := backend.Receipt(ctx, app.state, financialReceiptSelector{Block: unknown, Index: 0})
			return err
		},
		func() error { _, err := backend.Block(ctx, app.state, unknown); return err },
		func() error {
			_, err := backend.OriginalCore(ctx, financialOriginalCoreSelector{Block: unknown, Offset: 0, MaxBytes: 1})
			return err
		},
		func() error { _, err := backend.CommitteeState(ctx, 1); return err },
		func() error {
			_, err := backend.Registry(ctx, app.state, protocolRegistrySelector{Namespace: "unknown", Key: unknown})
			return err
		},
		func() error {
			_, err := backend.RecentBlocks(ctx, app.state, financialRecentSelector{Start: app.state.FinancialDAG.Blocks + 1, Limit: 1})
			return err
		},
		func() error {
			_, err := backend.Receipt(ctx, app.state, financialReceiptSelector{Block: blocks[0], Index: 1})
			return err
		},
		func() error {
			_, err := backend.OriginalCore(ctx, financialOriginalCoreSelector{Block: blocks[0], Offset: DagMaxWire - 1, MaxBytes: 1})
			return err
		},
		func() error { _, err := backend.Block(ctx, first, blocks[2]); return err },
		func() error {
			_, err := backend.Receipt(ctx, first, financialReceiptSelector{Block: blocks[2], Index: 0})
			return err
		},
		func() error {
			_, err := backend.Reward(ctx, app.state, protocolRewardSelector{Address: publicFixtureAddress(publicFixtureKey("not a reward recipient")), Index: 1})
			return err
		},
	}
	for i, check := range checks {
		if err := check(); err == nil {
			t.Fatal("negative selector unexpectedly succeeded", i)
		}
		if backend.store.history.failed.Load() || backend.store.health() != nil {
			t.Fatal("optional selector poisoned healthy native source", i)
		}
	}
	key := financialBlockOrderKey(1)
	original, err := backend.store.db.Get([]byte(key), nil)
	if err != nil {
		t.Fatal(err)
	}
	historyTamperActive(t, backend.store.db, key, nil)
	cancelled, cancel := context.WithCancel(ctx)
	cancel()
	if _, err = backend.RecentBlocks(cancelled, app.state, financialRecentSelector{Start: 1, Limit: 1}); err == nil || backend.store.history.failed.Load() {
		t.Fatal("cancelled required read poisoned source", err)
	}
	historyTamperActive(t, backend.store.db, key, original)
	if _, err = backend.RecentBlocks(ctx, app.state, financialRecentSelector{Start: 1, Limit: 1}); err != nil {
		t.Fatal("restored healthy required read", err)
	}
	status, _, err := backend.LocalHistoryStatus(ctx)
	if err != nil || status["state"] != "READY" {
		t.Fatal("healthy selector/cancel source unavailable", err)
	}
}

func TestFinancialHistoryEmptyProofEntriesRequireHealthyOwnedStore(t *testing.T) {
	for _, effect := range []string{"known_required_fault", "healthy_close"} {
		t.Run(effect, func(t *testing.T) {
			model, keys, _ := publicProtocolFixture(t)
			var genesis Genesis
			if decodeStrict(canonical(model.genesis), &genesis) != nil {
				t.Fatal("owned public genesis copy")
			}
			genesis.SupplyAtomic = "0"
			genesis.Protocol.Economics.InitialSupply = "0"
			genesis.FinancialAccounts.Allocations = []financialAccountAllocation{}
			anchor := hashHex(canonical(genesis))
			if err := validateGenesis(genesis, anchor); err != nil {
				t.Fatal("valid zero-allocation configured genesis", err)
			}
			app, err := newFinancialLedger(genesis, anchor, t.TempDir(), true)
			if err != nil {
				t.Fatal(err)
			}
			defer app.Close()
			backend := app.financial.(*financialNativeApplication)
			ctx := context.Background()
			savedState := copyState(app.state)
			stateBytes := canonical(savedState)
			packet := publicFixturePacket(t, app, keys)
			certificateBytes := append([]byte(nil), packet.SignedHeader...)
			if result, err := verifyInput(packet); err != nil || result["verified"] != true {
				t.Fatal("real retained state certificate fixture", err)
			}
			unknown := publicFixtureAddress(publicFixtureKey("empty proof entry absence"))
			selectors := []protocolRegistrySelector{{Namespace: "operations", Key: unknown}, {Namespace: "rewards", Key: unknown}}
			for _, selector := range selectors {
				root, err := protocolRegistryRootFor(savedState, selector.Namespace)
				if err != nil || root.Count != 0 {
					t.Fatal("namespace is not genuinely empty", err)
				}
				proof, err := backend.Registry(ctx, savedState, selector)
				if err != nil {
					t.Fatal("healthy empty absence", err)
				}
				if _, exists, err := checkFinancialCertifiedRegistry(ctx, proof, savedState, app.genesis, selector); err != nil || exists {
					t.Fatal("empty absence failed independent verification", err)
				}
			}
			// Current valid public initialization always ensures at least one
			// producer reward account, even with zero supply/no allocations. Legacy
			// general genesis requires a positive allocation. Do not fabricate an
			// unreachable empty account State merely to claim configured coverage.
			if savedState.AccountTree == nil || savedState.AccountTree.Count == 0 {
				t.Fatal("zero-supply account fixture no longer matches configured initialization")
			}
			account, err := backend.Account(ctx, savedState, unknown)
			if err != nil {
				t.Fatal("healthy configured account absence", err)
			}
			if _, exists, err := checkFinancialCertifiedAccount(ctx, account, savedState, app.genesis); err != nil || exists {
				t.Fatal("account absence failed independent verification", err)
			}
			if backend.store.history.failed.Load() {
				t.Fatal("healthy absence poisoned source")
			}
			if effect == "known_required_fault" {
				key := protocolRegistryPrefix + savedState.Protocol.ProducerRoot.Hash
				backend.store.protocolCache.clear()
				historyTamperActive(t, backend.store.db, key, []byte(`{}`))
				if _, err = backend.Registry(ctx, savedState, protocolRegistrySelector{Namespace: "producers", Key: genesis.FinancialDAG.Producers[0]}); err == nil || !backend.store.history.failed.Load() {
					t.Fatal("independent real required fault not observed", err)
				}
			} else {
				if err = app.Close(); err != nil {
					t.Fatal(err)
				}
				if backend.store.history.failed.Load() {
					t.Fatal("healthy close relabelled as observed corruption")
				}
			}
			for _, selector := range selectors {
				if _, err = backend.Registry(ctx, savedState, selector); err == nil {
					t.Fatal("new empty absence escaped closed/faulted entry", effect, selector.Namespace)
				}
			}
			if _, err = backend.Account(ctx, savedState, unknown); err == nil {
				t.Fatal("new account proof escaped closed/faulted entry", effect)
			}
			if !bytes.Equal(stateBytes, canonical(savedState)) || !bytes.Equal(certificateBytes, packet.SignedHeader) || !bytes.Equal(stateBytes, canonical(packet.State)) {
				t.Fatal("entry guard erased or mutated retained public evidence")
			}
			if result, err := verifyInput(packet); err != nil || result["verified"] != true {
				t.Fatal("retained certificate cannot be independently read after store unavailability", err)
			}
		})
	}
}

// This is an independent construction of the historical hash domains and
// odd-duplication tree. A format change must preserve these exact roots.
func historyTestIndependentLayers(keys []string, values map[string][]byte) [][]string {
	leaves := make([]string, len(keys))
	for i, key := range keys {
		digest := sha256.New()
		digest.Write([]byte("GG-FINANCIAL-HISTORY-RECORD-v1\x00"))
		var lengths [12]byte
		binary.BigEndian.PutUint32(lengths[:4], uint32(len(key)))
		binary.BigEndian.PutUint64(lengths[4:], uint64(len(values[key])))
		digest.Write(lengths[:])
		digest.Write([]byte(key))
		digest.Write(values[key])
		leaves[i] = hex.EncodeToString(digest.Sum(nil))
	}
	layers := [][]string{leaves}
	for len(layers[len(layers)-1]) > 1 {
		old := layers[len(layers)-1]
		next := []string{}
		for i := 0; i < len(old); i += 2 {
			right := old[i]
			if i+1 < len(old) {
				right = old[i+1]
			}
			digest := sha256.Sum256([]byte("GG-FINANCIAL-HISTORY-NODE-v1\x00" + old[i] + right))
			next = append(next, hex.EncodeToString(digest[:]))
		}
		layers = append(layers, next)
	}
	return layers
}
func historyTestCompactWire(record financialHistoryRecord, index int, sequence uint64) []byte {
	raw := make([]byte, 32)
	copy(raw, "GGFHREF2")
	binary.BigEndian.PutUint64(raw[8:16], sequence)
	binary.BigEndian.PutUint32(raw[16:20], uint32(index))
	binary.BigEndian.PutUint32(raw[20:24], uint32(record.length))
	binary.BigEndian.PutUint64(raw[24:], uint64(record.offset))
	return raw
}

// Explicit historical-v1 fixture generation belongs only to owned tests.
// Production seal always emits v2; no published file is ever rewritten.
func historyInstallLegacyV1(t *testing.T, store *financialStore) financialHistorySegment {
	t.Helper()
	store.mu.Lock()
	defer store.mu.Unlock()
	h := store.history
	keys := []string{}
	values := map[string][]byte{}
	iter := h.db.NewIterator(util.BytesPrefix([]byte(financialHistoryActive)), nil)
	for iter.Next() {
		key := strings.TrimPrefix(string(iter.Key()), financialHistoryActive)
		raw, err := h.db.Get([]byte(key), nil)
		if err != nil || historyReference(raw) {
			iter.Release()
			t.Fatal("active legacy fixture", err)
		}
		keys = append(keys, key)
		values[key] = append([]byte(nil), raw...)
	}
	err := iter.Error()
	iter.Release()
	if err != nil || len(keys) < 1 || len(keys) > financialHistorySegmentRecords {
		t.Fatal("legacy fixture size", err, len(keys))
	}
	sort.Strings(keys)
	layers := historyTestIndependentLayers(keys, values)
	firstHeight, lastHeight := int64(0), int64(0)
	for _, key := range keys {
		if strings.HasPrefix(key, "j/") {
			var height int64
			if _, err := fmt.Sscanf(key, "j/%d", &height); err != nil {
				t.Fatal(err)
			}
			if firstHeight == 0 {
				firstHeight = height
			}
			lastHeight = height
		}
	}
	header := financialHistorySegmentHeader{Anchor: h.anchor, Count: len(keys), CutHeight: store.head.State.Height,
		CutJournal: store.head.Journal, CutState: store.head.State.StateRoot, First: keys[0], FirstHeight: firstHeight,
		Last: keys[len(keys)-1], LastHeight: lastHeight, Previous: h.head.Digest, Root: layers[len(layers)-1][0],
		Schema: "gg.financial.history.segment-header.v1", Segment: h.head.Segments + 1, Source: h.source}
	var body bytes.Buffer
	body.WriteString("GGFHSEG1")
	var length [4]byte
	binary.BigEndian.PutUint32(length[:], uint32(len(canonical(header))))
	body.Write(length[:])
	body.Write(canonical(header))
	records := make([]financialHistoryRecord, len(keys))
	for i, key := range keys {
		records[i] = financialHistoryRecord{key: key, digest: layers[0][i], length: len(values[key]), offset: int64(body.Len())}
		body.Write(historyRecordFrame(key, values[key]))
	}
	digest := sha256.Sum256(body.Bytes())
	body.Write(digest[:])
	segment := financialHistorySegment{Bytes: int64(body.Len()), Digest: hex.EncodeToString(digest[:]), Header: header, Schema: "gg.financial.history.segment.v1"}
	if err := os.MkdirAll(h.directory(), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(h.directory(), historySegmentName(header.Segment)), body.Bytes(), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := h.inspectFile(context.Background(), segment, true); err != nil {
		t.Fatal("historical-v1 bytes rejected before indexing", err)
	}
	if err := h.commitSegment(context.Background(), segment, records); err != nil {
		t.Fatal("historical-v1 exact index", err)
	}
	return segment
}

// Independently serialize a self-contained physical v2 segment. Its bo/ values
// are valid digests; semantic full-ledger replay is covered by the real public
// fixture and the existing receipt/account/registry/committee/reward tests.
func historyPhysicalV2(t *testing.T, count int) (*financialHistory, financialHistorySegment, []financialHistoryRecord, map[string][]byte, []byte) {
	t.Helper()
	return historyPhysicalFormat(t, count, 2)
}
func historyPhysicalFormat(t *testing.T, count, version int) (*financialHistory, financialHistorySegment, []financialHistoryRecord, map[string][]byte, []byte) {
	t.Helper()
	root := t.TempDir()
	keys := make([]string, count)
	values := map[string][]byte{}
	for i := range keys {
		keys[i] = fmt.Sprintf("bo/%020d", i+1)
		value := sha256.Sum256([]byte(fmt.Sprintf("independent physical record %d", i)))
		values[keys[i]] = []byte(hex.EncodeToString(value[:]))
	}
	layers := historyTestIndependentLayers(keys, values)
	header := financialHistorySegmentHeader{Anchor: strings.Repeat("a", 64), Count: count, CutHeight: 0, CutJournal: DagZero,
		CutState: strings.Repeat("b", 64), First: keys[0], Last: keys[count-1], Previous: DagZero,
		Root: layers[len(layers)-1][0], Schema: fmt.Sprintf("gg.financial.history.segment-header.v%d", version), Segment: 1, Source: strings.Repeat("c", 64)}
	var body bytes.Buffer
	body.WriteString(fmt.Sprintf("GGFHSEG%d", version))
	var size [4]byte
	binary.BigEndian.PutUint32(size[:], uint32(len(canonical(header))))
	body.Write(size[:])
	body.Write(canonical(header))
	records := make([]financialHistoryRecord, count)
	for i, key := range keys {
		records[i] = financialHistoryRecord{key: key, digest: layers[0][i], length: len(values[key]), offset: int64(body.Len())}
		var lengths [6]byte
		binary.BigEndian.PutUint16(lengths[:2], uint16(len(key)))
		binary.BigEndian.PutUint32(lengths[2:], uint32(len(values[key])))
		body.Write(lengths[:])
		body.WriteString(key)
		body.Write(values[key])
	}
	if version == 2 {
		for _, layer := range layers {
			for _, digest := range layer {
				raw, err := hex.DecodeString(digest)
				if err != nil {
					t.Fatal(err)
				}
				body.Write(raw)
			}
		}
	}
	digest := sha256.Sum256(body.Bytes())
	body.Write(digest[:])
	segment := financialHistorySegment{Bytes: int64(body.Len()), Digest: hex.EncodeToString(digest[:]), Header: header, Schema: fmt.Sprintf("gg.financial.history.segment.v%d", version)}
	db, err := leveldb.OpenFile(filepath.Join(root, "gg-financial-dag.leveldb"), &opt.Options{Strict: opt.StrictAll})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if err := db.Close(); err != nil {
			t.Error(err)
		}
	})
	head := financialHistoryHead{Anchor: header.Anchor, Digest: segment.Digest, Initialized: true, Schema: "gg.financial.history.head.v1", Segments: 1, Source: header.Source}
	h := &financialHistory{db: db, root: root, anchor: header.Anchor, source: header.Source, head: head, hasHead: true}
	if err := os.Mkdir(h.directory(), 0700); err != nil {
		t.Fatal(err)
	}
	raw := append([]byte(nil), body.Bytes()...)
	if err := os.WriteFile(filepath.Join(h.directory(), historySegmentName(1)), raw, 0600); err != nil {
		t.Fatal(err)
	}
	batch := new(leveldb.Batch)
	batch.Put([]byte("zs/head"), canonical(head))
	batch.Put([]byte(historySegmentKey(1)), canonical(segment))
	for i, record := range records {
		wire := historyTestCompactWire(record, i, 1)
		if version == 1 {
			ref := financialHistoryReference{Index: i, Length: record.length, Offset: record.offset, Path: historyPath(layers, i), Schema: "gg.financial.history.reference.v1", Segment: 1}
			wire = append([]byte("GGFHREF1\x00"), canonical(ref)...)
		}
		batch.Put([]byte(record.key), wire)
	}
	if err := db.Write(batch, &opt.WriteOptions{Sync: true}); err != nil {
		t.Fatal(err)
	}
	return h, segment, records, values, raw
}

type historyFooterReadCounter struct {
	reader       io.ReaderAt
	start, end   int64
	reads, bytes int
}

func (reader *historyFooterReadCounter) ReadAt(p []byte, offset int64) (int, error) {
	if len(p) != 32 || offset < reader.start || offset+32 > reader.end {
		return 0, errors.New("proof attempted a non-sibling or out-of-footer read")
	}
	reader.reads++
	reader.bytes += len(p)
	return reader.reader.ReadAt(p, offset)
}

func TestFinancialHistoryV2ExactWireOddRootsAndBoundedProofReads(t *testing.T) {
	for _, count := range []int{1, 3, 5, 4096} {
		t.Run(fmt.Sprint(count), func(t *testing.T) {
			h, segment, records, values, raw := historyPhysicalV2(t, count)
			end, err := historyRecordEnd(segment)
			if err != nil {
				t.Fatal(err)
			}
			layers := historyLayers(records)
			digests := 0
			for _, layer := range layers {
				digests += len(layer)
			}
			if digests != historyTreeDigestCount(count) || digests > 8191 || end+int64(digests)*32+32 != segment.Bytes ||
				layers[len(layers)-1][0] != segment.Header.Root {
				t.Fatal("layout or unchanged odd-tree root", digests, segment.Bytes)
			}
			if count == 4096 && digests != 8191 {
				t.Fatal("maximum tree layout changed")
			}
			for i, record := range records {
				wire := historyReferenceWire(record, i, segment, layers)
				want := historyTestCompactWire(record, i, 1)
				if len(wire) != 32 || !bytes.Equal(wire, want) {
					t.Fatal("reference fields or exact 32-byte representation changed", i)
				}
				ref, version, err := historyDecodeReference(wire, record.key)
				if err != nil || version != 2 || ref.Index != i || ref.Length != record.length || ref.Offset != record.offset || ref.Segment != 1 || len(ref.Path) != 0 {
					t.Fatal("compact decode", i, err)
				}
				reader := &historyFooterReadCounter{reader: bytes.NewReader(raw), start: end, end: segment.Bytes - 32}
				path, err := historyReadFooterPath(context.Background(), reader, segment, i)
				ref.Path = path
				if err != nil || !historyCheckPath(historyRecordHash(record.key, values[record.key]), ref, segment.Header) ||
					!bytes.Equal(canonical(path), canonical(historyPath(layers, i))) || reader.reads != len(layers)-1 || reader.reads > 12 || reader.bytes != reader.reads*32 {
					t.Fatal("proof root, selected siblings, or read bound", i, err, reader.reads)
				}
			}
			for _, index := range []int{0, count / 2, count - 1} {
				got, err := h.get(context.Background(), records[index].key)
				if err != nil || !bytes.Equal(got, values[records[index].key]) {
					t.Fatal("exact logical bytes through real file lookup", index, err)
				}
			}
			if _, err := h.inspectFile(context.Background(), segment, false); err != nil {
				t.Fatal("independent bytes rejected by full footer/index/digest audit", err)
			}
			if _, err := openFinancialHistory(context.Background(), h.db, h.root, h.anchor, h.source, true); err != nil {
				t.Fatal("cold physical inventory failed", err)
			}
		})
	}
}

func TestFinancialHistoryV1AndV2MixedColdReplaySnapshotsAndImmutableFiles(t *testing.T) {
	app, backend, root, block := historyPublicFixture(t)
	ctx := context.Background()
	receiptState := copyState(app.state)
	before, err := backend.Receipt(ctx, receiptState, financialReceiptSelector{Block: block, Index: 0})
	if err != nil {
		t.Fatal(err)
	}
	legacy := historyInstallLegacyV1(t, backend.store)
	legacyPath := filepath.Join(backend.store.history.directory(), historySegmentName(legacy.Header.Segment))
	legacyBytes, err := os.ReadFile(legacyPath)
	if err != nil {
		t.Fatal(err)
	}
	// A pure-v1 cold start must still run the complete original/derived audit.
	genesis, anchor := app.genesis, app.anchor
	if err := app.Close(); err != nil {
		t.Fatal(err)
	}
	app, err = newFinancialLedger(genesis, anchor, root, false)
	if err != nil {
		t.Fatal("published v1 full cold replay", err)
	}
	defer app.Close()
	backend = app.financial.(*financialNativeApplication)
	wantOld := historyLogicalBytes(t, backend.store)
	old, err := backend.store.db.GetSnapshot()
	if err != nil {
		t.Fatal(err)
	}
	defer func() {
		if old != nil {
			old.Release()
		}
	}()
	for key := range wantOld {
		raw, err := old.Get([]byte(key), nil)
		if err != nil || !bytes.HasPrefix(raw, []byte(financialHistoryReferenceMagic)) {
			t.Fatal("fixture did not publish actual legacy references", key, err)
		}
	}
	commitFinancialSDK(t, app, nil)
	want := historyLogicalBytes(t, backend.store)
	historySealAll(t, backend.store)
	if backend.store.history.head.Segments <= legacy.Header.Segment {
		t.Fatal("new v2 suffix was not published")
	}
	for key, value := range wantOld {
		got, err := backend.store.history.read(ctx, func(key string) ([]byte, error) { return old.Get([]byte(key), nil) }, key)
		if err != nil || !bytes.Equal(got, value) {
			t.Fatal("old v1 snapshot lost its exact original", key, err)
		}
	}
	old.Release()
	old = nil
	current, err := backend.store.db.GetSnapshot()
	if err != nil {
		t.Fatal(err)
	}
	commitFinancialSDK(t, app, nil)
	historySealAll(t, backend.store)
	for key, value := range want {
		got, err := backend.store.history.read(ctx, func(key string) ([]byte, error) { return current.Get([]byte(key), nil) }, key)
		if err != nil || !bytes.Equal(got, value) {
			current.Release()
			t.Fatal("old mixed-format snapshot lost exact bytes", key, err)
		}
	}
	current.Release()
	// The additional commit is intentionally part of the final cold replay.
	state := canonical(app.state)
	want = historyLogicalBytes(t, backend.store)
	after, err := backend.Receipt(ctx, receiptState, financialReceiptSelector{Block: block, Index: 0})
	if err != nil || !bytes.Equal(canonical(before), canonical(after)) {
		t.Fatal("mixed-format historical proof changed", err)
	}
	if err := app.Close(); err != nil {
		t.Fatal(err)
	}
	cold, err := newFinancialLedger(app.genesis, app.anchor, root, false)
	if err != nil {
		t.Fatal("full independent legacy/v2 original and derived replay", err)
	}
	defer cold.Close()
	if !bytes.Equal(state, canonical(cold.state)) {
		t.Fatal("mixed-format cold root or money changed")
	}
	historyAssertSame(t, cold.financial.(*financialNativeApplication).store, want)
	afterBytes, err := os.ReadFile(legacyPath)
	if err != nil || !bytes.Equal(legacyBytes, afterBytes) {
		t.Fatal("published legacy file was rewritten", err)
	}
}

func TestFinancialHistoryV2CorruptFooterRequiresColdAllLayerComparison(t *testing.T) {
	for _, kind := range []string{"sibling_leaf", "sibling_parent", "unread_leaf", "footer_root"} {
		t.Run(kind, func(t *testing.T) {
			h, segment, records, values, raw := historyPhysicalV2(t, 5)
			end, err := historyRecordEnd(segment)
			if err != nil {
				t.Fatal(err)
			}
			offset := end + 32
			liveMustReject := true
			switch kind {
			case "sibling_parent":
				offset = end + 5*32 + 32
			case "unread_leaf":
				offset = end + 4*32
				liveMustReject = false
			case "footer_root":
				offset = segment.Bytes - 64
				liveMustReject = false
			}
			raw[offset] ^= 0x80
			// Rebind the full-file digest to the corrupt tree deliberately.
			// A hash-only cold audit would now accept it; all-layer comparison
			// must still reject the mismatch with recomputed key/raw leaves.
			digest := sha256.Sum256(raw[:len(raw)-32])
			copy(raw[len(raw)-32:], digest[:])
			segment.Digest = hex.EncodeToString(digest[:])
			h.head.Digest = segment.Digest
			batch := new(leveldb.Batch)
			batch.Put([]byte(historySegmentKey(1)), canonical(segment))
			batch.Put([]byte("zs/head"), canonical(h.head))
			if h.db.Write(batch, &opt.WriteOptions{Sync: true}) != nil ||
				os.WriteFile(filepath.Join(h.directory(), historySegmentName(1)), raw, 0600) != nil {
				t.Fatal("owned corrupt-footer fixture")
			}
			got, err := h.get(context.Background(), records[0].key)
			if liveMustReject {
				if err == nil || !h.failed.Load() {
					t.Fatal("selected sibling corruption bypassed root authentication", kind)
				}
			} else if err != nil || !bytes.Equal(got, values[records[0].key]) {
				t.Fatal("bounded lookup read an unrelated footer node", err)
			}
			if _, err := openFinancialHistory(context.Background(), h.db, h.root, h.anchor, h.source, true); err == nil {
				t.Fatal("full cold footer comparison accepted recomputed-file-hash corruption", kind)
			}
		})
	}
}

func TestFinancialHistoryV2BadIndexesVersionsAndForeignFilesFailClosed(t *testing.T) {
	for _, kind := range []string{"index", "offset", "offset_footer", "length", "segment", "unknown_reference", "trailing", "truncated", "alias", "missing_reference", "v1_reference_v2_segment", "unknown_segment", "cross_header", "unknown_file_magic", "missing_segment", "foreign_anchor", "foreign_source"} {
		t.Run(kind, func(t *testing.T) {
			h, segment, records, _, rawFile := historyPhysicalV2(t, 3)
			key := records[0].key
			wire := historyTestCompactWire(records[0], 0, 1)
			batch := new(leveldb.Batch)
			switch kind {
			case "index":
				binary.BigEndian.PutUint32(wire[16:20], 2)
			case "offset":
				binary.BigEndian.PutUint64(wire[24:], uint64(records[0].offset+1))
			case "offset_footer":
				end, err := historyRecordEnd(segment)
				if err != nil {
					t.Fatal(err)
				}
				binary.BigEndian.PutUint64(wire[24:], uint64(end))
			case "length":
				binary.BigEndian.PutUint32(wire[20:24], uint32(records[0].length+1))
			case "segment":
				binary.BigEndian.PutUint64(wire[8:16], 2)
			case "unknown_reference":
				wire[7] = '9'
			case "trailing":
				wire = append(wire, 0)
			case "truncated":
				wire = wire[:31]
			case "alias":
				wire = historyTestCompactWire(records[1], 1, 1)
			case "missing_reference":
				wire = nil
			case "v1_reference_v2_segment":
				ref := financialHistoryReference{Index: 0, Length: records[0].length, Offset: records[0].offset, Path: historyPath(historyLayers(records), 0), Schema: "gg.financial.history.reference.v1", Segment: 1}
				wire = append([]byte(financialHistoryReferenceMagic), canonical(ref)...)
			case "unknown_segment":
				segment.Schema = "gg.financial.history.segment.v3"
			case "cross_header":
				segment.Header.Schema = "gg.financial.history.segment-header.v1"
			case "unknown_file_magic":
				rawFile[7] = '9'
				if err := os.WriteFile(filepath.Join(h.directory(), historySegmentName(1)), rawFile, 0600); err != nil {
					t.Fatal(err)
				}
			case "missing_segment":
				if err := os.Remove(filepath.Join(h.directory(), historySegmentName(1))); err != nil {
					t.Fatal(err)
				}
			case "foreign_anchor":
				segment.Header.Anchor = strings.Repeat("d", 64)
			case "foreign_source":
				segment.Header.Source = strings.Repeat("d", 64)
			}
			if wire == nil {
				batch.Delete([]byte(key))
			} else {
				batch.Put([]byte(key), wire)
			}
			batch.Put([]byte(historySegmentKey(1)), canonical(segment))
			if err := h.db.Write(batch, &opt.WriteOptions{Sync: true}); err != nil {
				t.Fatal(err)
			}
			_, err := h.requiredRead(context.Background(), func(key string) ([]byte, error) { return h.get(context.Background(), key) }, key)
			if err == nil || !h.failed.Load() {
				t.Fatal("required corrupt reference/file escaped fault fence", kind, err)
			}
			if _, err := openFinancialHistory(context.Background(), h.db, h.root, h.anchor, h.source, true); err == nil {
				t.Fatal("cold index/version/file inventory accepted corruption", kind)
			}
		})
	}
}

func TestFinancialHistoryV2CancellationIsNotCorruptionAndFooterStaysInsideQuota(t *testing.T) {
	for _, count := range []int{1, 3} {
		t.Run(fmt.Sprint(count), func(t *testing.T) {
			h, segment, records, _, raw := historyPhysicalV2(t, count)
			ctx, cancel := context.WithCancel(context.Background())
			cancel()
			reader := &historyFooterReadCounter{reader: bytes.NewReader(raw), start: 0, end: segment.Bytes}
			if _, err := historyReadFooterPath(ctx, reader, segment, 0); !errors.Is(err, context.Canceled) || reader.reads != 0 {
				t.Fatal("cancelled proof performed IO or lost cancellation", err)
			}
			ctx, cancel = context.WithCancel(context.Background())
			_, err := h.read(ctx, func(key string) ([]byte, error) {
				value, err := h.db.Get([]byte(key), nil)
				if key == records[0].key {
					cancel()
				}
				return value, err
			}, records[0].key)
			if !errors.Is(err, context.Canceled) || h.failed.Load() {
				t.Fatal("mid-lookup cancel poisoned store", err)
			}
			if _, err := h.get(context.Background(), records[0].key); err != nil {
				t.Fatal("cancel damaged healthy lookup", err)
			}
			segment.Bytes = financialHistorySegmentBytes
			end, err := historyRecordEnd(segment)
			if err != nil || end+int64(historyTreeDigestCount(count))*32+32 != financialHistorySegmentBytes {
				t.Fatal("footer was added above the existing quota", err)
			}
			segment.Bytes++
			if _, err := historyRecordEnd(segment); err == nil {
				t.Fatal("segment above existing 64 MiB quota accepted")
			}
			segment.Bytes = int64(12 + len(canonical(segment.Header)) + count*7 + historyTreeDigestCount(count)*32 + 31)
			if _, err := historyRecordEnd(segment); err == nil {
				t.Fatal("tree overlaps minimum record region")
			}
		})
	}
	for _, count := range []int{-1, 0, financialHistorySegmentRecords + 1} {
		if historyTreeDigestCount(count) != 0 {
			t.Fatal("unbounded Count admitted by footer sizing", count)
		}
	}
}

func TestFinancialHistoryLegacyV1ReferenceValidationRemainsStrict(t *testing.T) {
	app, backend, root, _ := historyPublicFixture(t)
	defer app.Close()
	historyInstallLegacyV1(t, backend.store)
	key := financialHeightKey(1)
	original, err := backend.store.db.Get([]byte(key), nil)
	if err != nil {
		t.Fatal(err)
	}
	for _, kind := range []string{"path_long", "path_side", "path_hash", "index", "offset", "schema", "noncanonical", "compact_to_v1"} {
		t.Run(kind, func(t *testing.T) {
			ref, version, err := historyDecodeReference(original, key)
			if err != nil || version != 1 || len(ref.Path) == 0 {
				t.Fatal("legacy reference fixture", err)
			}
			switch kind {
			case "path_long":
				ref.Path = make([]PathItem, 13)
			case "path_side":
				ref.Path[0].Side = "invalid"
			case "path_hash":
				first := "a"
				if strings.HasPrefix(ref.Path[0].Hash, first) {
					first = "b"
				}
				ref.Path[0].Hash = first + ref.Path[0].Hash[1:]
			case "index":
				ref.Index = -1
			case "offset":
				ref.Offset = -1
			case "schema":
				ref.Schema = "gg.financial.history.reference.v9"
			}
			wire := append([]byte(financialHistoryReferenceMagic), canonical(ref)...)
			if kind == "noncanonical" {
				wire = append(wire, '\n')
			}
			if kind == "compact_to_v1" {
				record := financialHistoryRecord{key: key, length: ref.Length, offset: ref.Offset}
				wire = historyTestCompactWire(record, ref.Index, ref.Segment)
			}
			if err := backend.store.db.Put([]byte(key), wire, &opt.WriteOptions{Sync: true}); err != nil {
				t.Fatal(err)
			}
			parser := &financialHistory{db: backend.store.db, root: root, anchor: app.anchor, source: app.genesis.FinancialDAG.hash()}
			if _, err := parser.get(context.Background(), key); err == nil || !parser.failed.Load() {
				t.Fatal("invalid legacy reference escaped strict resolver", kind, err)
			}
			if _, err := openFinancialHistory(context.Background(), backend.store.db, root, parser.anchor, parser.source, true); err == nil {
				t.Fatal("invalid legacy index escaped cold verification", kind)
			}
			if err := backend.store.db.Put([]byte(key), original, &opt.WriteOptions{Sync: true}); err != nil {
				t.Fatal(err)
			}
		})
	}
}

func TestFinancialHistoryV1V2PhysicalEquivalenceAtOneOddAnd4096(t *testing.T) {
	for _, count := range []int{1, 3, 5, 4096} {
		t.Run(fmt.Sprint(count), func(t *testing.T) {
			v1, oldSegment, oldRecords, oldValues, oldRaw := historyPhysicalFormat(t, count, 1)
			v2, newSegment, records, values, raw := historyPhysicalFormat(t, count, 2)
			if oldSegment.Header.Root != newSegment.Header.Root || string(oldRaw[:8]) != "GGFHSEG1" || string(raw[:8]) != "GGFHSEG2" ||
				int64(len(raw)-len(oldRaw)) != int64(historyTreeDigestCount(count))*32 {
				t.Fatal("physical representation changed logical root or tree sizing")
			}
			for i, record := range records {
				if oldRecords[i] != record || !bytes.Equal(oldValues[record.key], values[record.key]) {
					t.Fatal("exact logical record changed between versions", i)
				}
				wire, err := v2.db.Get([]byte(record.key), nil)
				if err != nil || len(wire) != 32 {
					t.Fatal("actual DB value was not fixed-size v2", i, err)
				}
			}
			for _, index := range []int{0, count / 2, count - 1} {
				key := records[index].key
				before, err1 := v1.get(context.Background(), key)
				after, err2 := v2.get(context.Background(), key)
				if err1 != nil || err2 != nil || !bytes.Equal(before, after) || !bytes.Equal(after, values[key]) {
					t.Fatal("resolved bytes differ across explicit format versions", index, err1, err2)
				}
				wire, err := v1.db.Get([]byte(key), nil)
				ref, version, decodeErr := historyDecodeReference(wire, key)
				if err != nil || decodeErr != nil || version != 1 ||
					!historyCheckPath(historyRecordHash(key, before), ref, oldSegment.Header) {
					t.Fatal("historical v1 path failed unchanged root", index, err, decodeErr)
				}
			}
			for _, h := range []*financialHistory{v1, v2} {
				if _, err := openFinancialHistory(context.Background(), h.db, h.root, h.anchor, h.source, true); err != nil {
					t.Fatal("explicit version cold physical audit", err)
				}
			}
		})
	}
}

type historyTreeFaultWriter struct {
	written, stop int
	cause         error
	cancel        context.CancelFunc
	short         bool
}

func (writer *historyTreeFaultWriter) Write(raw []byte) (int, error) {
	if writer.written >= writer.stop {
		if writer.short {
			return len(raw) - 1, nil
		}
		if writer.cancel != nil {
			writer.cancel()
			return len(raw), nil
		}
		return 0, writer.cause
	}
	writer.written += len(raw)
	return len(raw), nil
}
func TestFinancialHistoryV2FooterWriteFailuresAndMidTreeCancellation(t *testing.T) {
	_, _, records, _, _ := historyPhysicalV2(t, 5)
	layers := historyLayers(records)
	for _, stop := range []int{0, 32, 5 * 32, (5 + 3) * 32} {
		for _, kind := range []string{"enospc", "close", "short", "cancel"} {
			t.Run(fmt.Sprintf("%d/%s", stop, kind), func(t *testing.T) {
				ctx, cancel := context.WithCancel(context.Background())
				defer cancel()
				writer := &historyTreeFaultWriter{stop: stop, cause: syscall.ENOSPC}
				switch kind {
				case "close":
					writer.cause = io.ErrClosedPipe
				case "short":
					writer.short = true
				case "cancel":
					writer.cancel = cancel
				}
				err := historyWriteTree(ctx, writer, sha256.New(), layers)
				if err == nil || kind == "cancel" && !errors.Is(err, context.Canceled) {
					t.Fatal("footer write/cancel failure was reported as durable completion", err)
				}
			})
		}
	}
}
