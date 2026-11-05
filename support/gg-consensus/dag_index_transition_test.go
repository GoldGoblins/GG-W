//go:build !js

package main

import (
	"bytes"
	"context"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/syndtr/goleveldb/leveldb"
	"github.com/syndtr/goleveldb/leveldb/opt"
)

// Construct the genuine indexless logical format in a separate LevelDB. No
// x/t/progress entries are copied or merely hidden by changing a v2 label.
func indexlessFixture(t *testing.T) (dagIndexTransitionCommand, State, map[string][]byte, map[string][]byte) {
	t.Helper()
	app, backend, source, _ := closedSDKFixture(t)
	root := t.TempDir()
	db, err := leveldb.OpenFile(filepath.Join(root, "gg-dag-segmented.leveldb"), &opt.Options{ErrorIfExist: true})
	if err != nil {
		t.Fatal(err)
	}
	original := map[string][]byte{}
	batch := new(leveldb.Batch)
	iter := backend.store.db.NewIterator(nil, nil)
	for iter.Next() {
		key, raw := string(iter.Key()), append([]byte(nil), iter.Value()...)
		if key == "meta" {
			meta := backend.store.meta
			meta.Schema = "gg.dag.segmented-store.v1"
			raw = canonical(meta)
		}
		if key == "meta" || key == "history" || strings.HasPrefix(key, "r/") || strings.HasPrefix(key, "m/") || strings.HasPrefix(key, "c/") {
			original[key] = raw
			batch.Put([]byte(key), raw)
		}
	}
	if iter.Error() != nil {
		t.Fatal(iter.Error())
	}
	iter.Release()
	if err := db.Write(batch, &opt.WriteOptions{Sync: true}); err != nil {
		t.Fatal(err)
	}
	if err := db.Close(); err != nil {
		t.Fatal(err)
	}
	archives := map[string][]byte{}
	if err := os.Mkdir(filepath.Join(root, "gg-dag-segments"), 0700); err != nil {
		t.Fatal(err)
	}
	entries, err := os.ReadDir(filepath.Join(source, "gg-dag-segments"))
	if err != nil {
		t.Fatal(err)
	}
	for _, entry := range entries {
		if entry.Name() != "OWNER" && !strings.HasSuffix(entry.Name(), ".ggseg") {
			continue
		}
		path := filepath.Join(source, "gg-dag-segments", entry.Name())
		info, err := os.Lstat(path)
		if err != nil || !info.Mode().IsRegular() || info.Size() > dagSegmentArchiveMaxBytes {
			t.Fatal("fixture archive")
		}
		file, err := os.Open(path)
		if err != nil {
			t.Fatal(err)
		}
		raw, err := io.ReadAll(io.LimitReader(file, dagSegmentArchiveMaxBytes+1))
		_ = file.Close()
		if err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(root, "gg-dag-segments", entry.Name()), raw, 0600); err != nil {
			t.Fatal(err)
		}
		archives[entry.Name()] = raw
	}
	// Public fixture bytes stand in for a sibling anti-double-sign file. The
	// maintenance command must never open/rewrite it or any signer/config path.
	if err := os.Mkdir(filepath.Join(root, "data"), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "data", "priv_validator_state.json"), []byte("public immutable signer-state fixture"), 0600); err != nil {
		t.Fatal(err)
	}
	return dagIndexTransitionCommand{Schema: "gg.dag.index-transition-request.v1", Genesis: app.genesis, GenesisHash: app.anchor, Root: root}, copyState(app.state), original, archives
}

func assertTransitionPreserved(t *testing.T, request dagIndexTransitionCommand, original map[string][]byte, archives map[string][]byte, current bool) {
	t.Helper()
	db, err := leveldb.OpenFile(filepath.Join(request.Root, "gg-dag-segmented.leveldb"), &opt.Options{ReadOnly: true})
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	for key, expected := range original {
		if current && key == "meta" {
			var meta dagSegmentStoreMeta
			if decodeStrict(expected, &meta) != nil {
				t.Fatal("fixture meta")
			}
			meta.Schema = "gg.dag.segmented-store.v2"
			expected = canonical(meta)
		}
		raw, err := db.Get([]byte(key), nil)
		if err != nil || !bytes.Equal(raw, expected) {
			t.Fatal("old logical value changed", key, err)
		}
	}
	for name, expected := range archives {
		raw, err := os.ReadFile(filepath.Join(request.Root, "gg-dag-segments", name))
		if err != nil || !bytes.Equal(raw, expected) {
			t.Fatal("original archive changed", name, err)
		}
	}
	raw, err := os.ReadFile(filepath.Join(request.Root, "data", "priv_validator_state.json"))
	if err != nil || string(raw) != "public immutable signer-state fixture" {
		t.Fatal("signer state changed")
	}
}

func TestIndexTransitionPreservesGenuineThreeEpoch5000TXHistoryAndColdProofs(t *testing.T) {
	request, before, original, archives := indexlessFixture(t)
	app, err := newDagEnabledLedger(request.Genesis, request.GenesisHash, request.Root, false)
	if err == nil {
		_ = app.Close()
		t.Fatal("normal startup accepted indexless state")
	}
	result, err := transitionDagIndex(context.Background(), request)
	if err != nil {
		t.Fatal(err)
	}
	if result["state"] != "INDEX_TRANSITION_COMPLETE" || result["indexed_epochs"] != "3" || result["verification_scope"] != dagIndexTransitionScope ||
		result["signers_opened"] != false || result["consensus_started"] != false || result["network_started"] != false || result["native_transfer_history_replayed"] != false {
		t.Fatal("incorrect transition receipt")
	}
	assertTransitionPreserved(t, request, original, archives, true)
	app, err = newDagEnabledLedger(request.Genesis, request.GenesisHash, request.Root, false)
	if err != nil {
		t.Fatal("new store did not reopen", err)
	}
	if !bytes.Equal(canonical(before), canonical(app.state)) {
		t.Fatal("height, root, nonce or accounts changed")
	}
	closedPagePacket(t, app, "1")
	closedPagePacket(t, app, "2")
	closedPagePacket(t, app, "3")
	_ = app.Close()
	again, err := transitionDagIndex(context.Background(), request)
	if err != nil || again["state"] != "ALREADY_CURRENT" {
		t.Fatal("idempotent verified rerun", err)
	}
	assertTransitionPreserved(t, request, original, archives, true)
}

func TestIndexTransitionResolvesEveryBeforeWriteAndUnknownSyncOutcome(t *testing.T) {
	for _, afterSync := range []bool{false, true} {
		for barrier := 1; barrier <= 5; barrier++ {
			name := string(rune('0' + barrier))
			if afterSync {
				name += "_after_actual_sync"
			}
			t.Run(name, func(t *testing.T) {
				request, _, original, archives := indexlessFixture(t)
				writes := 0
				_, err := transitionDagIndex(context.Background(), request, func(store *dagSegmentStore) {
					real := store.write
					store.write = func(batch *leveldb.Batch) error {
						writes++
						if writes == barrier && !afterSync {
							return errors.New("public injected prewrite failure")
						}
						if err := real(batch); err != nil {
							return err
						}
						if writes == barrier {
							return errors.New("public injected unknown sync acknowledgement")
						}
						return nil
					}
				})
				if err == nil || writes != barrier {
					t.Fatal("barrier not exercised", barrier, writes, err)
				}
				complete := afterSync && barrier == 5
				assertTransitionPreserved(t, request, original, archives, complete)
				if !complete {
					app, err := newDagEnabledLedger(request.Genesis, request.GenesisHash, request.Root, false)
					if err == nil {
						_ = app.Close()
						t.Fatal("partial migration became a consensus authority")
					}
				}
				result, err := transitionDagIndex(context.Background(), request)
				if err != nil {
					t.Fatal("verified resume failed", err)
				}
				if result["indexed_epochs"] != "3" {
					t.Fatal("resume lost selected epoch")
				}
				assertTransitionPreserved(t, request, original, archives, true)
			})
		}
	}
}

func TestIndexTransitionCancellationRetainsExactAtomicProgressAndResumes(t *testing.T) {
	request, _, original, archives := indexlessFixture(t)
	ctx, cancel := context.WithCancel(context.Background())
	writes := 0
	_, err := transitionDagIndex(ctx, request, func(store *dagSegmentStore) {
		real := store.write
		store.write = func(batch *leveldb.Batch) error {
			writes++
			err := real(batch)
			if writes == 2 {
				cancel()
			}
			return err
		}
	})
	if err == nil || writes != 2 {
		t.Fatal("cancel did not stop after committed first prefix", err, writes)
	}
	assertTransitionPreserved(t, request, original, archives, false)
	result, err := transitionDagIndex(context.Background(), request)
	if err != nil || result["state"] != "INDEX_TRANSITION_COMPLETE" {
		t.Fatal("cancelled prefix did not resume", err)
	}
}

func TestIndexTransitionDoesNotRepairCorruptArchiveOrSavedIndexPrefix(t *testing.T) {
	for _, kind := range []string{"archive_before_initial_verification", "saved_index", "saved_progress", "extra_node"} {
		t.Run(kind, func(t *testing.T) {
			request, _, original, archives := indexlessFixture(t)
			if kind == "archive_before_initial_verification" {
				for name, raw := range archives {
					if strings.HasSuffix(name, ".ggseg") {
						copyRaw := append([]byte(nil), raw...)
						copyRaw[len(copyRaw)/2] ^= 1
						_ = os.WriteFile(filepath.Join(request.Root, "gg-dag-segments", name), copyRaw, 0600)
						archives[name] = copyRaw
						break
					}
				}
			} else {
				writes := 0
				_, err := transitionDagIndex(context.Background(), request, func(store *dagSegmentStore) {
					real := store.write
					store.write = func(batch *leveldb.Batch) error {
						writes++
						if writes == 3 {
							return errors.New("public prefix stop")
						}
						return real(batch)
					}
				})
				if err == nil {
					t.Fatal("prefix fixture did not stop")
				}
				db, err := leveldb.OpenFile(filepath.Join(request.Root, "gg-dag-segmented.leveldb"), nil)
				if err != nil {
					t.Fatal(err)
				}
				switch kind {
				case "saved_index":
					_ = db.Put([]byte(closedIndexKey(1)), []byte("changed index"), nil)
				case "saved_progress":
					raw, _ := db.Get([]byte(dagIndexTransitionKey), nil)
					var marker dagIndexTransitionProgress
					_ = decodeStrict(raw, &marker)
					marker.HistoryHash = DagZero
					_ = db.Put([]byte(dagIndexTransitionKey), canonical(marker), nil)
				case "extra_node":
					_ = db.Put([]byte(closedNodeKey(0, 30)), []byte(DagZero), nil)
				}
				_ = db.Close()
			}
			called := false
			_, err := transitionDagIndex(context.Background(), request, func(*dagSegmentStore) { called = true })
			if err == nil || called {
				t.Fatal("bad initial provenance reached transition writes", kind, err)
			}
			assertTransitionPreserved(t, request, original, archives, false)
		})
	}
}

func TestIndexTransitionLeaseWrongPinAndCallerClaimsNeverEnableWrites(t *testing.T) {
	request, _, original, archives := indexlessFixture(t)
	db, err := leveldb.OpenFile(filepath.Join(request.Root, "gg-dag-segmented.leveldb"), nil)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := transitionDagIndex(context.Background(), request); err == nil {
		t.Fatal("transition bypassed real DB lease")
	}
	_ = db.Close()
	wrong := request
	wrong.GenesisHash = DagZero
	if _, err := transitionDagIndex(context.Background(), wrong); err == nil {
		t.Fatal("wrong genesis pin accepted")
	}
	var claim map[string]any
	_ = decodeStrict(canonical(request), &claim)
	claim["verified"] = true
	if _, err := runDagIndexTransitionCommand(canonical(claim)); err == nil {
		t.Fatal("caller verified flag accepted")
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := transitionDagIndex(ctx, request); err == nil {
		t.Fatal("cancelled command opened store")
	}
	assertTransitionPreserved(t, request, original, archives, false)
}

func TestIndexTransitionCLISortedPublicRequestMatchesTypedCanonicalForm(t *testing.T) {
	request, _, original, archives := indexlessFixture(t)
	// Python pack() and the shared CLI sort all keys; a typed Go request must
	// encode exactly that public wire form, not just agree with its own tests.
	wire := canonical(map[string]any{"schema": request.Schema, "genesis": request.Genesis,
		"genesis_hash": request.GenesisHash, "root": request.Root})
	if !bytes.Equal(wire, canonical(request)) {
		t.Fatal("typed maintenance request differs from sorted CLI JSON")
	}
	result, err := runDagIndexTransitionCommand(wire)
	if err != nil || result["state"] != "INDEX_TRANSITION_COMPLETE" || result["indexed_epochs"] != "3" {
		t.Fatal("real CLI wire request rejected", err)
	}
	assertTransitionPreserved(t, request, original, archives, true)
}

func TestIndexTransitionEmptyLegacyStoreStillVerifiesAndCommitsAtomically(t *testing.T) {
	app, backend, _, root := segmentedSDKFixture(t)
	meta := backend.store.meta
	meta.Schema = "gg.dag.segmented-store.v1"
	if err := backend.store.db.Put([]byte("meta"), canonical(meta), nil); err != nil {
		t.Fatal(err)
	}
	before := copyState(app.state)
	_ = app.Close()
	request := dagIndexTransitionCommand{Schema: "gg.dag.index-transition-request.v1", Genesis: app.genesis, GenesisHash: app.anchor, Root: root}
	result, err := runDagIndexTransitionCommand(canonical(request))
	if err != nil || result["indexed_epochs"] != "0" {
		t.Fatal("empty legacy transition", err)
	}
	restored, err := newDagEnabledLedger(app.genesis, app.anchor, root, false)
	if err != nil {
		t.Fatal(err)
	}
	defer restored.Close()
	if !bytes.Equal(canonical(before), canonical(restored.state)) {
		t.Fatal("empty genesis changed")
	}
}

// Test-only conversion of a STOPPED SDK's public application records into
// their actual old logical format. No production command can call this helper.
// The original v2 DB is preserved outside the native root as evidence.
func recreateIndexlessSDKFixture(t *testing.T, request dagIndexTransitionCommand, prepared, backup string) map[string]any {
	t.Helper()
	store, history, _, err := openDagSegmentStoreMode(request.Genesis, request.GenesisHash, request.Root, false, true)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := os.Lstat(prepared); !os.IsNotExist(err) {
		_ = store.close()
		t.Fatal("prepared fixture target already exists")
	}
	if _, err := os.Lstat(backup); !os.IsNotExist(err) {
		_ = store.close()
		t.Fatal("backup fixture target already exists")
	}
	db, err := leveldb.OpenFile(prepared, &opt.Options{ErrorIfExist: true})
	if err != nil {
		_ = store.close()
		t.Fatal(err)
	}
	batch := new(leveldb.Batch)
	copied := 0
	iter := store.db.NewIterator(nil, nil)
	for iter.Next() {
		key := string(iter.Key())
		if key != "meta" && key != "history" && !strings.HasPrefix(key, "r/") && !strings.HasPrefix(key, "m/") && !strings.HasPrefix(key, "c/") {
			continue
		}
		raw := append([]byte(nil), iter.Value()...)
		if key == "meta" {
			meta := store.meta
			meta.Schema = "gg.dag.segmented-store.v1"
			raw = canonical(meta)
		}
		batch.Put([]byte(key), raw)
		copied++
	}
	iterErr := iter.Error()
	iter.Release()
	writeErr := db.Write(batch, &opt.WriteOptions{Sync: true})
	closeErr := db.Close()
	sourceClose := store.close()
	if iterErr != nil || writeErr != nil || closeErr != nil || sourceClose != nil {
		t.Fatal("legacy logical fixture copy failed")
	}
	active := filepath.Join(request.Root, "gg-dag-segmented.leveldb")
	if err := os.Rename(active, backup); err != nil {
		t.Fatal(err)
	}
	if err := os.Rename(prepared, active); err != nil {
		_ = os.Rename(backup, active)
		t.Fatal(err)
	}
	last := history[len(history)-1]
	return map[string]any{"schema": "gg.public.indexless-sdk-fixture.v1", "logical_records_copied": copied, "native_height": last.Height,
		"native_state_root": last.StateRoot, "commitment": last.DAGSegmented, "original_v2_DB_retained": true, "signer_or_network_data_copied": false}
}

func TestIndexTransitionActualSDKIndexlessFixture(t *testing.T) {
	if path := os.Getenv("GG_PUBLIC_INDEXLESS_SDK_FIXTURE"); path != "" {
		var config struct {
			Request  dagIndexTransitionCommand `json:"request"`
			Prepared string                    `json:"prepared"`
			Backup   string                    `json:"backup"`
			Receipt  string                    `json:"receipt"`
		}
		raw, err := os.ReadFile(path)
		if err != nil || len(raw) > 65536 || decodeStrict(raw, &config) != nil {
			t.Fatal("actual fixture configuration")
		}
		workspace, err := filepath.Abs(filepath.Join("..", ".."))
		if err != nil {
			t.Fatal(err)
		}
		allowed := filepath.Join(workspace, ".runtime", "dagoblin-stress-v1", "index-transition-v1")
		for _, target := range []string{path, config.Request.Root, config.Prepared, config.Backup, config.Receipt} {
			absolute, err := filepath.Abs(target)
			if err != nil || absolute != target || !pathWithinArchiveRoot(target, allowed) {
				t.Fatal("fixture target outside owned task evidence")
			}
		}
		result := recreateIndexlessSDKFixture(t, config.Request, config.Prepared, config.Backup)
		if err := os.WriteFile(config.Receipt, canonical(result), 0600); err != nil {
			t.Fatal(err)
		}
		return
	}
	// Default suite path remains a genuine assertion, not a skipped/no-op test.
	app, _, root, _ := closedSDKFixture(t)
	state := copyState(app.state)
	_ = app.Close()
	parent := t.TempDir()
	request := dagIndexTransitionCommand{Schema: "gg.dag.index-transition-request.v1", Genesis: app.genesis, GenesisHash: app.anchor, Root: root}
	result := recreateIndexlessSDKFixture(t, request, filepath.Join(parent, "prepared.leveldb"), filepath.Join(parent, "backup.leveldb"))
	if result["original_v2_DB_retained"] != true {
		t.Fatal("fixture backup missing")
	}
	if _, err := transitionDagIndex(context.Background(), request); err != nil {
		t.Fatal(err)
	}
	restored, err := newDagEnabledLedger(app.genesis, app.anchor, root, false)
	if err != nil {
		t.Fatal(err)
	}
	defer restored.Close()
	if !bytes.Equal(canonical(state), canonical(restored.state)) {
		t.Fatal("actual old logical fixture changed SDK state")
	}
}
