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
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"syscall"
	"testing"

	dbm "github.com/cometbft/cometbft-db"
	cmted "github.com/cometbft/cometbft/crypto/ed25519"
	cmtjson "github.com/cometbft/cometbft/libs/json"
	sm "github.com/cometbft/cometbft/state"
	"github.com/cometbft/cometbft/types"
	"github.com/syndtr/goleveldb/leveldb"
	"github.com/syndtr/goleveldb/leveldb/opt"
	"github.com/syndtr/goleveldb/leveldb/storage"
)

// Actual public-key signatures and native execution. SDK blocks here are signed
// fixtures, not live consensus; genuine multi-process rejoin runs separately.
func financialObserverArchiveFixture(t *testing.T, schemas ...string) (financialObserverRestoreCommand, []byte) {
	t.Helper()
	genesis, _, committee := membershipFixture(t)
	model, _, producers := financialDagFixture(t)
	source := model.source
	source.Schema = "gg.financial-dag.source.v2"
	if len(schemas) > 0 {
		if len(schemas) != 1 || schemas[0] != financialLineageSourceSchema {
			t.Fatal("unsupported public observer fixture source")
		}
		source.Schema = schemas[0]
		source.Policy = source.rules()
	}
	source.NetworkID = strings.Repeat("b", 64)
	genesis.DAG = nil
	genesis.Schema = "gg.native.genesis.v5"
	genesis.FinancialDAG = &source
	anchor := hashHex(canonical(genesis))
	if validateGenesis(genesis, anchor) != nil {
		t.Fatal("financial membership fixture")
	}
	accounts := []ed25519.PrivateKey{}
	signers := []cmted.PrivKey{}
	for _, public := range genesis.Accounts {
		for _, keys := range committee {
			if hex.EncodeToString(keys[2].Public().(ed25519.PublicKey)) == public {
				accounts = append(accounts, keys[2])
			}
		}
	}
	for _, keys := range committee {
		signers = append(signers, cmted.PrivKey(keys[0]))
	}
	root := t.TempDir()
	app, err := newFinancialLedger(genesis, anchor, root, true)
	if err != nil {
		t.Fatal(err)
	}
	batch, _ := financialContextBlock(t, app, producers, 0, [][]byte{testTx(genesis, anchor, accounts, 0, 1, "3", 0), testTx(genesis, anchor, accounts, 0, 1, "2", 1)})
	commitFinancialSDK(t, app, batch)
	commitFinancialSDK(t, app, nil)
	state := copyState(app.state)
	if err = app.Close(); err != nil {
		t.Fatal(err)
	}
	signed := financialFixtureSDKChain(t, genesis, anchor, root, state, signers)
	header, err := cmtjson.Marshal(signed)
	if err != nil {
		t.Fatal(err)
	}
	certificate := dagArchiveCertificate{Schema: "gg.consensus.proof.v1", Genesis: genesis, GenesisHash: anchor, State: state, SignedHeader: header}
	request := financialArchiveCommand{Genesis: genesis, GenesisHash: anchor, Root: root, Certificate: &certificate}
	var output bytes.Buffer
	if _, err = exportFinancialArchive(context.Background(), &output, request); err != nil {
		t.Fatal(err)
	}
	raw := output.Bytes()
	request.ArchivePath = filepath.Join(t.TempDir(), "history.ggfin")
	if err = os.WriteFile(request.ArchivePath, raw, 0600); err != nil {
		t.Fatal(err)
	}
	seed := sha256.Sum256([]byte("public-financial-observer-recovery-fixture"))
	node := ed25519.NewKeyFromSeed(seed[:])
	keys := []ed25519.PrivateKey{node, committee[0][3], producers[0]}
	grant := signObserverGrantFixture(nativeObserverGrantBody{GenesisHash: anchor, Host: "127.0.0.1", P2PPort: 24009,
		LabelUTF8: base64.StdEncoding.EncodeToString([]byte("Recovered observer")), NodeKey: hex.EncodeToString(node.Public().(ed25519.PublicKey)),
		OwnerPeerKey: hex.EncodeToString(keys[1].Public().(ed25519.PublicKey)), ProducerKey: source.Producers[0],
		Schema: nativeObserverGrantSchema, SignatureProfile: TransactionSignatureProfile}, keys)
	if validateNativeObserverGrant(grant, genesis, anchor) != nil {
		t.Fatal("financial observer grant")
	}
	request.Root = ""
	request.RestoreRoot = filepath.Join(t.TempDir(), "restored-native")
	return financialObserverRestoreCommand{financialArchiveCommand: request, ArchiveHash: hashHex(raw), ObserverGrant: grant}, raw
}

// This changes the mode of a real owned LevelDB LOG and exercises the actual
// failed open, not a filesystem mock or a claim about historical IO failures.
func TestFinancialObserverRecoveryStoragePermissionPreservesExactIntent(t *testing.T) {
	t.Run("error_boundaries", func(t *testing.T) {
		fallback := errFinancialObserverRecovery
		for _, row := range []struct {
			name  string
			cause error
			want  error
		}{
			{"permission", os.ErrPermission, errFinancialObserverStorageUnavailable},
			{"wrapped_permission", &os.PathError{Op: "open", Path: "public-test-path-must-not-escape", Err: os.ErrPermission}, errFinancialObserverStorageUnavailable},
			{"joined_permission", errors.Join(errors.New("public-wrapper"), os.ErrPermission), errFinancialObserverStorageUnavailable},
			{"storage_lock", storage.ErrLocked, errFinancialObserverStorageUnavailable},
			{"foreign_exists", os.ErrExist, fallback},
			{"missing", os.ErrNotExist, fallback},
			{"corrupt", errors.New("public-test-corruption"), fallback},
			{"cancelled", context.Canceled, fallback},
			{"deadline", context.DeadlineExceeded, fallback},
			{"cancel_precedes_permission", errors.Join(context.Canceled, os.ErrPermission), fallback},
		} {
			if got := financialObserverStorageError(row.cause, fallback); got != row.want {
				t.Fatalf("classification %s: %v", row.name, got)
			}
		}
		for _, code := range []syscall.Errno{32, 33} {
			want := fallback
			if runtime.GOOS == "windows" {
				want = errFinancialObserverStorageUnavailable
			}
			if got := financialObserverStorageError(code, fallback); got != want {
				t.Fatal("Windows sharing codes were interpreted outside Windows", runtime.GOOS, code, got)
			}
		}
		if financialObserverStorageError(nil, nil) != nil || financialObserverStorageError(context.Canceled, context.Canceled) != context.Canceled {
			t.Fatal("nil/cancellation identity changed")
		}
	})
	t.Run("actual_owned_readonly_LOG", func(t *testing.T) {
		if runtime.GOOS != "windows" && os.Geteuid() == 0 {
			t.Skip("Real permission-denial scope requires an unprivileged filesystem owner; Linux acceptance runs as uid1000")
		}
		request, archive := financialObserverArchiveFixture(t)
		originalRequest := canonical(request)
		stop := errors.New("GG_PUBLIC_PHASE_ZERO_STOP")
		result, err := restoreFinancialObserver(context.Background(), request, func(point string) error {
			if point == "APPLICATION_BEFORE" {
				return stop
			}
			return nil
		})
		if result != nil || err != stop {
			t.Fatal("owned phase0 fixture did not stop at the original boundary", err)
		}
		intentPath := filepath.Join(request.RestoreRoot, financialObserverIntentDB)
		readHead := func() []byte {
			t.Helper()
			db, openErr := leveldb.OpenFile(intentPath, &opt.Options{ReadOnly: true, ErrorIfMissing: true, Strict: opt.StrictAll})
			if openErr != nil {
				t.Fatal("actual readonly intent check", openErr)
			}
			head, readErr := db.Get([]byte("head"), nil)
			closeErr := db.Close()
			if readErr != nil || closeErr != nil {
				t.Fatal("actual readonly intent read/close", readErr, closeErr)
			}
			return append([]byte(nil), head...)
		}
		beforeHead := readHead()
		var phase0 financialObserverRestoreIntent
		if decodeStrict(beforeHead, &phase0) != nil || phase0.Phase != 0 {
			t.Fatal("phase0 intent was not actually durable")
		}
		logPath := filepath.Join(intentPath, "LOG")
		info, err := os.Lstat(logPath)
		if err != nil || !info.Mode().IsRegular() || info.Mode()&os.ModeSymlink != 0 {
			t.Fatal("actual owned LOG fixture", err)
		}
		originalMode := info.Mode().Perm()
		defer func() {
			if err := os.Chmod(logPath, originalMode); err != nil {
				t.Error("restore exact owned LOG mode", err)
			}
		}()
		// On Windows, Chmod without an owner write bit sets FILE_ATTRIBUTE_READONLY.
		// On uid1000 POSIX the same operation removes real write permission.
		if err = os.Chmod(logPath, originalMode&^0222); err != nil {
			t.Fatal("set actual owned LOG readonly", err)
		}
		probe, denied := os.OpenFile(logPath, os.O_WRONLY, 0)
		if denied == nil {
			_ = probe.Close()
			t.Fatal("the actual filesystem did not enforce readonly; no mocked permission credit is allowed")
		}
		if !os.IsPermission(denied) {
			t.Fatal("the actual write probe failed for a different reason", denied)
		}
		result, err = restoreFinancialObserver(context.Background(), request, nil)
		if result != nil || err != errFinancialObserverStorageUnavailable || err.Error() != "GG_OBSERVER_RECOVERY_STORAGE_UNAVAILABLE" {
			t.Fatal("actual storage denial was reported as success, invalid identity, or a path", err)
		}
		if !bytes.Equal(beforeHead, readHead()) || !bytes.Equal(originalRequest, canonical(request)) {
			t.Fatal("storage denial rewrote the durable intent or original request")
		}
		for _, name := range []string{nativeObserverRootFile, financialObserverMarkerStage, "gg-financial-dag.leveldb", "data"} {
			if _, err = os.Lstat(filepath.Join(request.RestoreRoot, name)); !os.IsNotExist(err) {
				t.Fatal("phase0 permission failure created money, SDK, or success state", name)
			}
		}
		if err = os.Chmod(logPath, originalMode); err != nil {
			t.Fatal("restore actual owned LOG permission", err)
		}
		result, err = restoreFinancialObserver(context.Background(), request, nil)
		if err != nil || result["sdk_offline_bootstrap_complete"] != true || result["native_node_ready"] != false {
			t.Fatal("the identical original request could not resume after the obstacle was removed", err)
		}
		app, err := newFinancialLedger(request.Genesis, request.GenesisHash, request.RestoreRoot, false)
		if err != nil {
			t.Fatal("actual cold money replay", err)
		}
		actualState := canonical(app.state)
		if err = app.Close(); err != nil || !bytes.Equal(actualState, canonical(request.Certificate.State)) {
			t.Fatal("exact resumed money state changed", err)
		}
		actualArchive, err := os.ReadFile(request.ArchivePath)
		if err != nil || !bytes.Equal(actualArchive, archive) {
			t.Fatal("storage denial changed the original public archive", err)
		}
	})
}

func TestFinancialObserverRecoveryReplaysMoneyBootstrapsSDKAndRetriesSamePublicIdentity(t *testing.T) {
	request, _ := financialObserverArchiveFixture(t)
	result, err := restoreFinancialObserver(context.Background(), request, nil)
	if err != nil {
		t.Fatal(err)
	}
	if result["observer_store_restored"] != true || result["consensus_store_restored"] != true || result["native_node_ready"] != false || result["validator_signing_state_restored"] != false || result["network_contact_asserted"] != false || result["restore_reused"] != false {
		t.Fatal("scope", result)
	}
	app, err := newFinancialLedger(request.Genesis, request.GenesisHash, request.RestoreRoot, false)
	if err != nil {
		t.Fatal("cold application", err)
	}
	if !bytes.Equal(canonical(app.state), canonical(request.Certificate.State)) {
		t.Fatal("different accounts after recovery")
	}
	app.Close()
	marker, err := os.ReadFile(filepath.Join(request.RestoreRoot, nativeObserverRootFile))
	if err != nil {
		t.Fatal(err)
	}
	var identity nativeObserverRootIdentity
	if decodeStrict(marker, &identity) != nil || identity.ObserverGrant != request.ObserverGrant {
		t.Fatal("public identity changed")
	}
	if _, _, err = nativeRootIdentity(Bootstrap{Root: request.RestoreRoot, Genesis: request.Genesis}); err == nil {
		t.Fatal("observer became a validator root")
	}
	again, err := restoreFinancialObserver(context.Background(), request, nil)
	if err != nil || again["restore_reused"] != true {
		t.Fatal("completed retry", err)
	}
	for _, name := range []string{"gg-public-genesis.json", filepath.Join("data", "priv_validator_state.json"), filepath.Join("config", "priv_validator_key.json")} {
		if _, err = os.Lstat(filepath.Join(request.RestoreRoot, name)); !os.IsNotExist(err) {
			t.Fatal("private signer or validator root was created")
		}
	}
}

// Diagnostics are only for this test's fresh synthetic SDK databases. A LOG
// snapshot is never replay or recovery authority and never replaces err.
func financialObserverFixtureDBError(operation, name, data string, err error) error {
	if err == nil {
		return nil
	}
	errno := "unavailable"
	var code syscall.Errno
	if errors.As(err, &code) {
		errno = fmt.Sprintf("%d", uint64(code))
	}
	var tail []byte
	detail := "not requested for close"
	if operation == "open" {
		tail, detail = financialObserverFixtureLogTail(data, name)
	}
	return fmt.Errorf("fixture SDK %s database=%s error_type=%T errno=%s LOG=%s tail=%q: %w",
		operation, name, err, errno, detail, tail, err)
}

func financialObserverFixtureLogTail(data, name string) (tail []byte, detail string) {
	const maximum int64 = 8 * 1024
	if !filepath.IsAbs(data) || name != "state" && name != "blockstore" {
		return nil, "invalid synthetic database path"
	}
	directory := filepath.Join(data, name+".db")
	for _, path := range []string{data, directory} {
		info, err := os.Lstat(path)
		if err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
			return nil, fmt.Sprintf("ordinary directory unavailable: %v", err)
		}
		resolved, err := filepath.EvalSymlinks(path)
		if err != nil || resolved != path {
			return nil, fmt.Sprintf("canonical directory unavailable: %v", err)
		}
	}
	path := filepath.Join(directory, "LOG")
	before, err := os.Lstat(path)
	if err != nil || !before.Mode().IsRegular() {
		return nil, fmt.Sprintf("ordinary LOG unavailable: %v", err)
	}
	file, err := os.Open(path)
	if err != nil {
		return nil, fmt.Sprintf("LOG open unavailable: %v", err)
	}
	defer func() {
		if closeErr := file.Close(); closeErr != nil {
			tail = nil
			detail = fmt.Sprintf("%s; LOG close error_type=%T error=%v", detail, closeErr, closeErr)
		}
	}()
	opened, err := file.Stat()
	if err != nil || !opened.Mode().IsRegular() || !os.SameFile(before, opened) {
		return nil, fmt.Sprintf("LOG handle identity unavailable: %v", err)
	}
	start := max(int64(0), opened.Size()-maximum)
	tail, err = io.ReadAll(io.NewSectionReader(file, start, min(opened.Size(), maximum)))
	if err != nil {
		return nil, fmt.Sprintf("bounded LOG read unavailable: %v", err)
	}
	after, err := os.Lstat(path)
	if err != nil || !after.Mode().IsRegular() || !os.SameFile(opened, after) {
		return nil, fmt.Sprintf("LOG path identity changed: %v", err)
	}
	return tail, fmt.Sprintf("bounded ordinary snapshot bytes=%d offset=%d", len(tail), start)
}

type financialSDKGraphFaultDB struct {
	dbm.DB
	iterationError, closeError error
	underlyingIteratorCloses   int
}

func (database *financialSDKGraphFaultDB) Iterator(start, end []byte) (dbm.Iterator, error) {
	iterator, err := database.DB.Iterator(start, end)
	if err != nil {
		return nil, err
	}
	return &financialSDKGraphFaultIterator{Iterator: iterator, database: database}, nil
}

type financialSDKGraphFaultIterator struct {
	dbm.Iterator
	database *financialSDKGraphFaultDB
}

func (iterator *financialSDKGraphFaultIterator) Error() error {
	return errors.Join(iterator.Iterator.Error(), iterator.database.iterationError)
}

func (iterator *financialSDKGraphFaultIterator) Close() error {
	iterator.database.underlyingIteratorCloses++
	return errors.Join(iterator.Iterator.Close(), iterator.database.closeError)
}

func TestFinancialSDKGraphIteratorClosePreservesPrimaryErrorAndBounds(t *testing.T) {
	closeFailure := errors.New("public synthetic iterator close failure")
	iterationFailure := errors.New("public synthetic iterator failure")
	for _, scenario := range []struct {
		name             string
		entries          int
		iteration, close error
		primary          error
	}{
		{name: "ordinary", entries: 1},
		{name: "close_only", entries: 1, close: closeFailure},
		{name: "iteration_and_close", entries: 1, iteration: iterationFailure, close: closeFailure, primary: iterationFailure},
		{name: "limit_and_close", entries: 17, close: closeFailure, primary: errFinancialObserverRecovery},
	} {
		t.Run(scenario.name, func(t *testing.T) {
			memory := dbm.NewMemDB()
			defer func() {
				if err := memory.Close(); err != nil {
					t.Error("close real MemDB", err)
				}
			}()
			for index := 0; index < scenario.entries; index++ {
				if err := memory.Set([]byte(fmt.Sprintf("key%02d", index)), []byte("public")); err != nil {
					t.Fatal(err)
				}
			}
			database := &financialSDKGraphFaultDB{DB: memory, iterationError: scenario.iteration, closeError: scenario.close}
			values, err := financialSDKGraph(database)
			if database.underlyingIteratorCloses != 1 {
				t.Fatal("real iterator Close/release was not called exactly once", database.underlyingIteratorCloses)
			}
			if scenario.close != nil {
				if values != nil || !errors.Is(err, scenario.close) || scenario.primary != nil && !errors.Is(err, scenario.primary) {
					t.Fatal("close failure returned data or hid the primary graph error", values, err)
				}
				return
			}
			if err != nil || len(values) != 1 || !bytes.Equal(values["key00"], []byte("public")) {
				t.Fatal("ordinary graph changed", values, err)
			}
			values["key00"][0] = 'x'
			original, err := memory.Get([]byte("key00"))
			if err != nil || !bytes.Equal(original, []byte("public")) {
				t.Fatal("graph value aliases the database", original, err)
			}
		})
	}
}

func TestFinancialObserverRecoveryColdStartupSnapshotContext(t *testing.T) {
	for _, schema := range []string{"gg.financial-dag.source.v2", financialLineageSourceSchema} {
		t.Run(schema, func(t *testing.T) {
			for _, mode := range []string{"cleared_marker", "current_marker", "different_state", "different_blockstore", "voter_mode", "cancelled"} {
				t.Run(mode, func(t *testing.T) {
					var schemas []string
					if schema == financialLineageSourceSchema {
						schemas = []string{schema}
					}
					request, _ := financialObserverArchiveFixture(t, schemas...)
					if _, err := restoreFinancialObserver(context.Background(), request, nil); err != nil {
						t.Fatal(err)
					}
					data := filepath.Join(request.RestoreRoot, "data")
					stateDB, err := dbm.NewGoLevelDBWithOpts("state", data, &opt.Options{ErrorIfMissing: true, Strict: opt.StrictAll})
					if err != nil {
						t.Fatal(financialObserverFixtureDBError("open", "state", data, err))
					}
					stateStore := sm.NewStore(stateDB, sm.StoreOptions{DiscardABCIResponses: false})
					if mode != "current_marker" {
						if err = stateStore.SetOfflineStateSyncHeight(0); err != nil {
							t.Fatal(err)
						}
					}
					document := genesisDoc(request.Genesis)
					if document.ValidateAndComplete() != nil {
						t.Fatal("public SDK genesis")
					}
					encoded, _ := cmtjson.Marshal(document)
					if stateDB.SetSync([]byte("genesisDoc"), encoded) != nil {
						t.Fatal("public SDK startup metadata")
					}
					if mode == "different_state" {
						if stateDB.SetSync([]byte("unknown-state"), []byte("public")) != nil {
							t.Fatal("fixture metadata")
						}
					}
					beforeState, err := financialSDKGraph(stateDB)
					err = errors.Join(err, financialObserverFixtureDBError("close", "state", data, stateDB.Close()))
					if err != nil {
						t.Fatal(err)
					}
					blockDB, err := dbm.NewGoLevelDBWithOpts("blockstore", data, &opt.Options{ErrorIfMissing: true, Strict: opt.StrictAll})
					if err != nil {
						t.Fatal(financialObserverFixtureDBError("open", "blockstore", data, err))
					}
					if mode == "different_blockstore" {
						if blockDB.SetSync([]byte("unknown-block"), []byte("public")) != nil {
							t.Fatal("fixture block metadata")
						}
					}
					beforeBlocks, err := financialSDKGraph(blockDB)
					err = errors.Join(err, financialObserverFixtureDBError("close", "blockstore", data, blockDB.Close()))
					if err != nil {
						t.Fatal(err)
					}
					app, err := newFinancialLedger(request.Genesis, request.GenesisHash, request.RestoreRoot, false)
					if err != nil {
						t.Fatal(err)
					}
					defer app.Close()
					beforeMoney := canonical(app.state)
					boot := Bootstrap{Root: request.RestoreRoot, Genesis: request.Genesis, GenesisHash: request.GenesisHash, observer: &nativeObserverBootstrap{ObserverGrant: request.ObserverGrant}}
					if mode == "voter_mode" {
						boot.observer = nil
					}
					ctx, cancel := context.WithCancel(context.Background())
					defer cancel()
					if mode == "cancelled" {
						cancel()
					}
					err = prepareFinancialObserverSDKStartup(ctx, boot, app, request.RestoreRoot)
					denied := mode == "different_state" || mode == "different_blockstore" || mode == "cancelled"
					if (err != nil) != denied {
						t.Fatal("wrong cold startup decision", mode, err)
					}
					if !denied && mode != "voter_mode" {
						if err = prepareFinancialObserverSDKStartup(ctx, boot, app, request.RestoreRoot); err != nil {
							t.Fatal("repeat", err)
						}
					}
					stateDB, err = dbm.NewGoLevelDBWithOpts("state", data, &opt.Options{ReadOnly: true, ErrorIfMissing: true, Strict: opt.StrictAll})
					if err != nil {
						t.Fatal(financialObserverFixtureDBError("open", "state", data, err))
					}
					marker, err := sm.NewStore(stateDB, sm.StoreOptions{DiscardABCIResponses: false}).GetOfflineStateSyncHeight()
					afterState, graphErr := financialSDKGraph(stateDB)
					graphErr = errors.Join(graphErr, financialObserverFixtureDBError("close", "state", data, stateDB.Close()))
					if err != nil || graphErr != nil {
						t.Fatal("state read", err, graphErr)
					}
					if !denied && mode != "voter_mode" {
						if marker != request.Certificate.State.Height {
							t.Fatal("offline snapshot context was consumed before a real SDK block", marker)
						}
						beforeState["offlineStateSyncHeightKey"] = afterState["offlineStateSyncHeightKey"]
					}
					if !financialSDKGraphEqual(beforeState, afterState) || !bytes.Equal(beforeMoney, canonical(app.state)) {
						t.Fatal("startup rewrote public state")
					}
					blockDB, err = dbm.NewGoLevelDBWithOpts("blockstore", data, &opt.Options{ReadOnly: true, ErrorIfMissing: true, Strict: opt.StrictAll})
					if err != nil {
						t.Fatal(financialObserverFixtureDBError("open", "blockstore", data, err))
					}
					afterBlocks, err := financialSDKGraph(blockDB)
					err = errors.Join(err, financialObserverFixtureDBError("close", "blockstore", data, blockDB.Close()))
					if err != nil || !financialSDKGraphEqual(beforeBlocks, afterBlocks) {
						t.Fatal("startup rewrote SDK block data", err)
					}
					if _, err = os.Lstat(filepath.Join(request.RestoreRoot, "data", "priv_validator_state.json")); !os.IsNotExist(err) {
						t.Fatal("observer created voter signing state")
					}
				})
			}
		})
	}
}

func TestFinancialObserverRecoveryCommandAcceptsPythonObjectOrderAndRejectsUnknownRequestFields(t *testing.T) {
	request, _ := financialObserverArchiveFixture(t)
	var wire map[string]any
	if json.Unmarshal(canonical(request), &wire) != nil {
		t.Fatal("wire fixture")
	}
	// json.Marshal sorts every map, as the shared Python packer does, including
	// nested SDK signed-header fields that were cmtjson struct-ordered on disk.
	raw, err := json.Marshal(wire)
	if err != nil {
		t.Fatal(err)
	}
	result, err := runFinancialObserverRestoreCommand(raw)
	if err != nil || result["observer_store_restored"] != true {
		t.Fatal("actual CLI object order", err)
	}
	for _, field := range []string{"validator_seed", "force"} {
		wire[field] = "not-a-key"
		raw, err = json.Marshal(wire)
		if err != nil {
			t.Fatal(err)
		}
		if _, err = runFinancialObserverRestoreCommand(raw); err == nil {
			t.Fatal("unknown field accepted", field)
		}
		delete(wire, field)
	}
}

func TestFinancialObserverRecoveryResumesExactIntentAcrossDurableBoundaryFailures(t *testing.T) {
	original, _ := financialObserverArchiveFixture(t)
	for _, point := range []string{"INTENT_BEFORE_SYNC", "INTENT_AFTER_SYNC", "APPLICATION_BEFORE", "APPLICATION_AFTER",
		"APP_PHASE_BEFORE_SYNC", "APP_PHASE_AFTER_SYNC", "SDK_STATE_BEFORE_BOOTSTRAP", "SDK_STATE_AFTER_BOOTSTRAP",
		"SDK_STATE_BEFORE_MARKER", "SDK_STATE_AFTER_MARKER", "SDK_COMMIT_BEFORE_SYNC", "SDK_COMMIT_AFTER_SYNC",
		"SDK_PHASE_BEFORE_SYNC", "SDK_PHASE_AFTER_SYNC", "ROOT_MARKER_BEFORE", "ROOT_MARKER_AFTER_LINK",
		"ROOT_MARKER_AFTER_SYNC", "COMPLETE_BEFORE_SYNC", "COMPLETE_AFTER_SYNC"} {
		t.Run(point, func(t *testing.T) {
			request := original
			request.RestoreRoot = filepath.Join(t.TempDir(), "native")
			injected := false
			_, err := restoreFinancialObserver(context.Background(), request, func(actual string) error {
				if actual == point && !injected {
					injected = true
					return errors.New("GG_OWNED_RECOVERY_FAULT")
				}
				return nil
			})
			if err == nil || !injected {
				t.Fatal("missing fault", point, err)
			}
			result, err := restoreFinancialObserver(context.Background(), request, nil)
			if err != nil || result["sdk_offline_bootstrap_complete"] != true {
				t.Fatal("exact resume", point, err)
			}
		})
	}
}

func TestFinancialObserverRecoveryRejectsChangedIntentForeignTargetAndSDKCorruption(t *testing.T) {
	request, _ := financialObserverArchiveFixture(t)
	if _, err := restoreFinancialObserver(context.Background(), request, func(point string) error {
		if point == "APPLICATION_BEFORE" {
			return errors.New("GG_TEST_STOP")
		}
		return nil
	}); err == nil {
		t.Fatal("stop")
	}
	changed := request
	changed.ObserverGrant.Body.LabelUTF8 = base64.StdEncoding.EncodeToString([]byte("Changed"))
	if _, err := restoreFinancialObserver(context.Background(), changed, nil); err == nil {
		t.Fatal("changed signed grant")
	}
	changed = request
	changed.ArchiveHash = strings.Repeat("0", 64)
	if _, err := restoreFinancialObserver(context.Background(), changed, nil); err == nil {
		t.Fatal("changed archive")
	}
	changed = request
	changed.MinimumCertificateHeight = request.Certificate.State.Height + 2
	if _, err := restoreFinancialObserver(context.Background(), changed, nil); err == nil {
		t.Fatal("certificate floor")
	}
	foreign := filepath.Join(t.TempDir(), "native")
	if os.Mkdir(foreign, 0700) != nil || os.WriteFile(filepath.Join(foreign, "untouched"), []byte("keep"), 0600) != nil {
		t.Fatal("fixture")
	}
	changed = request
	changed.RestoreRoot = foreign
	if _, err := restoreFinancialObserver(context.Background(), changed, nil); err == nil {
		t.Fatal("unowned target")
	}
	if _, err := restoreFinancialObserver(context.Background(), request, nil); err != nil {
		t.Fatal(err)
	}
	database, err := dbm.NewGoLevelDB("state", filepath.Join(request.RestoreRoot, "data"))
	if err != nil {
		t.Fatal(err)
	}
	if database.SetSync([]byte("unrelated"), []byte("preserved")) != nil || database.Close() != nil {
		t.Fatal("fixture corruption")
	}
	if _, err = restoreFinancialObserver(context.Background(), request, nil); err == nil {
		t.Fatal("SDK corruption silently repaired")
	}
	database, err = dbm.NewGoLevelDBWithOpts("state", filepath.Join(request.RestoreRoot, "data"), &opt.Options{ReadOnly: true, ErrorIfMissing: true})
	if err != nil {
		t.Fatal(err)
	}
	value, err := database.Get([]byte("unrelated"))
	database.Close()
	if err != nil || string(value) != "preserved" {
		t.Fatal("failed target was altered")
	}
}

func financialRewriteArchive(t *testing.T, raw []byte, legacy bool, mutateCommit bool) []byte {
	t.Helper()
	input := bytes.NewReader(raw[8:])
	var output bytes.Buffer
	if legacy {
		output.WriteString(financialArchiveMagic)
	} else {
		output.Write(raw[:8])
	}
	for input.Len() > 0 {
		var prefix [5]byte
		if _, err := io.ReadFull(input, prefix[:]); err != nil {
			t.Fatal(err)
		}
		body := make([]byte, binary.BigEndian.Uint32(prefix[1:]))
		if _, err := io.ReadFull(input, body); err != nil {
			t.Fatal(err)
		}
		if legacy && prefix[0] == 'C' {
			continue
		}
		if legacy && prefix[0] == 'H' {
			var h dagArchiveHeader
			if decodeStrict(body, &h) != nil {
				t.Fatal("header")
			}
			h.Schema = "gg.financial.public-archive.v1"
			body = canonical(h)
		}
		if mutateCommit && prefix[0] == 'C' {
			var c types.Commit
			if cmtjson.Unmarshal(body, &c) != nil {
				t.Fatal("commit")
			}
			c.Round++
			var err error
			body, err = cmtjson.Marshal(c)
			if err != nil {
				t.Fatal(err)
			}
		}
		if prefix[0] == 'F' {
			var footer financialArchiveFooter
			if decodeStrict(body, &footer) != nil {
				t.Fatal("footer")
			}
			footer.Content = hashHex(output.Bytes())
			body = canonical(footer)
		}
		if writeArchiveFrame(&output, prefix[0], body, financialJournalMaxWire) != nil {
			t.Fatal("frame")
		}
	}
	return output.Bytes()
}

func TestFinancialObserverRecoveryAuthenticatesPriorCommitAndKeepsLegacyApplicationRead(t *testing.T) {
	request, raw := financialObserverArchiveFixture(t)
	changed := financialRewriteArchive(t, raw, false, true)
	if _, err := readFinancialArchive(context.Background(), bytes.NewReader(changed), request.financialArchiveCommand, nil); err == nil {
		t.Fatal("forged prior quorum round")
	}
	legacy := financialRewriteArchive(t, raw, true, false)
	result, err := readFinancialArchive(context.Background(), bytes.NewReader(legacy), request.financialArchiveCommand, nil)
	if err != nil || result["archive_version"] != 1 || result["sdk_recovery_available"] != false {
		t.Fatal("legacy application scope", err)
	}
	if os.WriteFile(request.ArchivePath, legacy, 0600) != nil {
		t.Fatal("legacy fixture")
	}
	request.ArchiveHash = hashHex(legacy)
	if _, err = restoreFinancialObserver(context.Background(), request, nil); err == nil {
		t.Fatal("legacy file claimed SDK context")
	}
	if _, err = os.Lstat(request.RestoreRoot); !os.IsNotExist(err) {
		t.Fatal("legacy failure wrote target")
	}
	appRequest := request.financialArchiveCommand
	appRequest.RestoreRoot = t.TempDir()
	file, info, err := openFinancialArchiveInput(request.ArchivePath)
	if err != nil {
		t.Fatal(err)
	}
	defer file.Close()
	if _, err = restoreFinancialArchive(context.Background(), file, info, appRequest); err != nil {
		t.Fatal("legacy application restore", err)
	}
	appRequest.Root = appRequest.RestoreRoot
	appRequest.RestoreRoot = ""
	var again bytes.Buffer
	if _, err = exportFinancialArchive(context.Background(), &again, appRequest); err != nil || !bytes.Equal(again.Bytes(), legacy) {
		t.Fatal("legacy byte roundtrip", err)
	}
}

func TestFinancialObserverRecoveryOnlyCompletesItsExactMarkerPrefix(t *testing.T) {
	original, _ := financialObserverArchiveFixture(t)
	for _, valid := range []bool{true, false} {
		t.Run(map[bool]string{true: "exact_prefix", false: "changed_prefix"}[valid], func(t *testing.T) {
			request := original
			request.RestoreRoot = filepath.Join(t.TempDir(), "native")
			if _, err := restoreFinancialObserver(context.Background(), request, func(point string) error {
				if point == "ROOT_MARKER_BEFORE" {
					return errors.New("GG_TEST_STOP")
				}
				return nil
			}); err == nil {
				t.Fatal("stop")
			}
			_, identity, err := nativeRootIdentity(Bootstrap{Root: request.RestoreRoot, Genesis: request.Genesis, GenesisHash: request.GenesisHash, observer: &nativeObserverBootstrap{ObserverGrant: request.ObserverGrant}})
			if err != nil {
				t.Fatal(err)
			}
			prefix := append([]byte(nil), identity[:17]...)
			if !valid {
				prefix[0] ^= 1
			}
			stage := filepath.Join(request.RestoreRoot, financialObserverMarkerStage)
			if os.WriteFile(stage, prefix, 0600) != nil {
				t.Fatal("prefix")
			}
			_, err = restoreFinancialObserver(context.Background(), request, nil)
			if valid && err != nil || !valid && err == nil {
				t.Fatal("prefix result", err)
			}
			if !valid {
				after, e := os.ReadFile(stage)
				if e != nil || !bytes.Equal(after, prefix) {
					t.Fatal("bad prefix was repaired")
				}
			}
		})
	}
}

// Actual LevelDB reads and public SDK graphs; only the owned post-close error
// result is injected. This does not reproduce historical AccessDenied, a live
// consensus node, network contact, or a physical filesystem failure.
func TestFinancialObserverRecoveryReadonlyCloseFailuresNeverReportSuccess(t *testing.T) {
	for _, schema := range []string{"gg.financial-dag.source.v2", financialLineageSourceSchema} {
		t.Run(schema, func(t *testing.T) {
			for _, store := range []string{"state", "blockstore"} {
				t.Run(store, func(t *testing.T) {
					var schemas []string
					if schema == financialLineageSourceSchema {
						schemas = []string{schema}
					}
					request, archive := financialObserverArchiveFixture(t, schemas...)
					point := "SDK_STATE_READONLY_CLOSE"
					if store == "blockstore" {
						point = "SDK_BLOCKSTORE_READONLY_CLOSE"
					}
					injected := 0
					closeFailure := errors.New("private-close-detail-not-for-public-output")
					fault := func(actual string) error {
						if actual == point {
							injected++
							return closeFailure
						}
						return nil
					}
					readGraphs := func() map[string]map[string][]byte {
						t.Helper()
						graphs := make(map[string]map[string][]byte)
						for _, name := range []string{"state", "blockstore"} {
							db, err := dbm.NewGoLevelDBWithOpts(name, filepath.Join(request.RestoreRoot, "data"),
								&opt.Options{ReadOnly: true, ErrorIfMissing: true, Strict: opt.StrictAll})
							if err != nil {
								t.Fatal("actual readonly SDK reopen", name, err)
							}
							graph, graphErr := financialSDKGraph(db)
							closeErr := db.Close()
							if graphErr != nil || closeErr != nil {
								t.Fatal("actual readonly SDK graph/close", name, graphErr, closeErr)
							}
							graphs[name] = graph
						}
						return graphs
					}
					assertGraphs := func(want map[string]map[string][]byte) {
						t.Helper()
						for name, actual := range readGraphs() {
							if !financialSDKGraphEqual(actual, want[name]) {
								t.Fatal("readonly close failure changed SDK graph", name)
							}
						}
					}
					result, err := restoreFinancialObserver(context.Background(), request, fault)
					if err != errFinancialObserverRecovery || result != nil || injected != 1 {
						t.Fatal("fresh readonly close fault reported success or leaked its private detail", err, injected)
					}
					for _, marker := range []string{nativeObserverRootFile, financialObserverMarkerStage} {
						if _, err = os.Lstat(filepath.Join(request.RestoreRoot, marker)); !os.IsNotExist(err) {
							t.Fatal("readonly close fault published an observer root", marker)
						}
					}
					graphs := readGraphs()
					result, err = restoreFinancialObserver(context.Background(), request, nil)
					if err != nil || result["sdk_offline_bootstrap_complete"] != true || result["native_node_ready"] != false {
						t.Fatal("same exact public restore after close fault", err)
					}
					assertGraphs(graphs)
					identity, err := os.ReadFile(filepath.Join(request.RestoreRoot, nativeObserverRootFile))
					if err != nil {
						t.Fatal("real completed observer identity", err)
					}
					// A completed retry first rechecks the actual SDK stores. Its
					// close error must also prevent a restore_reused success result.
					injected = 0
					result, err = restoreFinancialObserver(context.Background(), request, fault)
					if err != errFinancialObserverRecovery || result != nil || injected != 1 {
						t.Fatal("completed readonly close fault reported success", err, injected)
					}
					actualIdentity, err := os.ReadFile(filepath.Join(request.RestoreRoot, nativeObserverRootFile))
					if err != nil || !bytes.Equal(identity, actualIdentity) {
						t.Fatal("failed completed retry rewrote the public identity", err)
					}
					assertGraphs(graphs)
					app, err := newFinancialLedger(request.Genesis, request.GenesisHash, request.RestoreRoot, false)
					if err != nil {
						t.Fatal("actual monetary cold replay", err)
					}
					actualState := canonical(app.state)
					if err = app.Close(); err != nil || !bytes.Equal(actualState, canonical(request.Certificate.State)) {
						t.Fatal("readonly close fault changed the original monetary state", err)
					}
					result, err = restoreFinancialObserver(context.Background(), request, nil)
					if err != nil || result["restore_reused"] != true {
						t.Fatal("completed exact retry", err)
					}
					assertGraphs(graphs)
					actualArchive, err := os.ReadFile(request.ArchivePath)
					if err != nil || !bytes.Equal(actualArchive, archive) {
						t.Fatal("readonly close fault rewrote the input archive", err)
					}
				})
			}
		})
	}
	// Startup separately owns a writable SDK state handle. Its successful
	// current/cleared-marker branches must not hide the actual close result.
	for _, schema := range []string{"gg.financial-dag.source.v2", financialLineageSourceSchema} {
		for _, mode := range []string{"current_marker", "cleared_marker", "foreign_state", "cancelled"} {
			t.Run("startup_state_close/"+schema+"/"+mode, func(t *testing.T) {
				var schemas []string
				if schema == financialLineageSourceSchema {
					schemas = []string{schema}
				}
				request, _ := financialObserverArchiveFixture(t, schemas...)
				if _, err := restoreFinancialObserver(context.Background(), request, nil); err != nil {
					t.Fatal("actual completed observer", err)
				}
				data := filepath.Join(request.RestoreRoot, "data")
				stateDB, err := dbm.NewGoLevelDBWithOpts("state", data, &opt.Options{ErrorIfMissing: true, Strict: opt.StrictAll})
				if err != nil {
					t.Fatal("actual startup state", err)
				}
				if mode == "cleared_marker" {
					if err = sm.NewStore(stateDB, sm.StoreOptions{DiscardABCIResponses: false}).SetOfflineStateSyncHeight(0); err != nil {
						_ = stateDB.Close()
						t.Fatal(err)
					}
				}
				if mode == "foreign_state" {
					if err = stateDB.SetSync([]byte("public-startup-extra"), []byte("keep")); err != nil {
						_ = stateDB.Close()
						t.Fatal(err)
					}
				}
				if err = stateDB.Close(); err != nil {
					t.Fatal("actual preparation close", err)
				}
				readGraph := func(name string) map[string][]byte {
					t.Helper()
					db, e := dbm.NewGoLevelDBWithOpts(name, data, &opt.Options{ReadOnly: true, ErrorIfMissing: true, Strict: opt.StrictAll})
					if e != nil {
						t.Fatal("actual readonly reopen", name, e)
					}
					graph, readErr := financialSDKGraph(db)
					closeErr := db.Close()
					if readErr != nil || closeErr != nil {
						t.Fatal("actual graph/close", name, readErr, closeErr)
					}
					return graph
				}
				beforeState, beforeBlocks := readGraph("state"), readGraph("blockstore")
				wantState := map[string][]byte{}
				for key, value := range beforeState {
					wantState[key] = append([]byte(nil), value...)
				}
				if mode == "cleared_marker" {
					markerDB := dbm.NewMemDB()
					if err = sm.NewStore(markerDB, sm.StoreOptions{DiscardABCIResponses: false}).SetOfflineStateSyncHeight(request.Certificate.State.Height); err != nil {
						_ = markerDB.Close()
						t.Fatal(err)
					}
					markerGraph, graphErr := financialSDKGraph(markerDB)
					closeErr := markerDB.Close()
					if graphErr != nil || closeErr != nil || len(markerGraph) != 1 {
						t.Fatal("independent SDK marker", graphErr, closeErr)
					}
					for key, value := range markerGraph {
						if _, exists := wantState[key]; !exists {
							t.Fatal("unknown marker key")
						}
						wantState[key] = value
					}
				}
				app, err := newFinancialLedger(request.Genesis, request.GenesisHash, request.RestoreRoot, false)
				if err != nil {
					t.Fatal("actual money context", err)
				}
				defer app.Close()
				beforeMoney := canonical(app.state)
				boot := Bootstrap{Root: request.RestoreRoot, Genesis: request.Genesis, GenesisHash: request.GenesisHash, observer: &nativeObserverBootstrap{ObserverGrant: request.ObserverGrant}}
				ctx, cancel := context.WithCancel(context.Background())
				defer cancel()
				if mode == "cancelled" {
					cancel()
				}
				calls := 0
				err = prepareFinancialObserverSDKStartupWithFault(ctx, boot, app, request.RestoreRoot, func(point string) error {
					if point != "SDK_STARTUP_STATE_CLOSE" {
						t.Fatal("unexpected owned startup fault point", point)
					}
					calls++
					return errors.New("private-startup-close-detail")
				})
				if mode == "cancelled" {
					if err != context.Canceled || calls != 0 {
						t.Fatal("close fallback replaced cancellation", err, calls)
					}
				} else if mode == "foreign_state" {
					if err != errFinancialSDKRecovery || calls != 0 {
						t.Fatal("close fallback replaced invalid SDK graph", err, calls)
					}
				} else if err != errFinancialSDKRecovery || calls != 1 {
					t.Fatal("startup falsely succeeded or exposed a private close detail", err, calls)
				}
				if !financialSDKGraphEqual(readGraph("state"), wantState) || !financialSDKGraphEqual(readGraph("blockstore"), beforeBlocks) || !bytes.Equal(beforeMoney, canonical(app.state)) {
					t.Fatal("startup close outcome changed unrelated state")
				}
				if mode == "current_marker" || mode == "cleared_marker" {
					panicErr := prepareFinancialObserverSDKStartupWithFault(context.Background(), boot, app, request.RestoreRoot, func(string) error {
						panic("private-startup-close-panic-must-not-escape")
					})
					if panicErr != errFinancialSDKRecovery {
						t.Fatal("existing startup panic fallback changed", panicErr)
					}
					if err = prepareFinancialObserverSDKStartup(context.Background(), boot, app, request.RestoreRoot); err != nil {
						t.Fatal("explicit same startup after actual close", err)
					}
					if !financialSDKGraphEqual(readGraph("state"), wantState) || !financialSDKGraphEqual(readGraph("blockstore"), beforeBlocks) {
						t.Fatal("same startup rewrote SDK state")
					}
				}
				if err = app.Close(); err != nil {
					t.Fatal("actual money close", err)
				}
				cold, err := newFinancialLedger(request.Genesis, request.GenesisHash, request.RestoreRoot, false)
				if err != nil {
					t.Fatal("actual monetary cold replay", err)
				}
				coldState := canonical(cold.state)
				if err = cold.Close(); err != nil || !bytes.Equal(coldState, canonical(request.Certificate.State)) {
					t.Fatal("startup close result changed the certified money root", err)
				}
				if _, err = os.Lstat(filepath.Join(data, "priv_validator_state.json")); !os.IsNotExist(err) {
					t.Fatal("startup created validator signing state")
				}
			})
		}
	}

}
