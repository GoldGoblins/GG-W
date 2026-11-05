//go:build !js

package main

// Restore only an explicitly bound nonvoting observer. Public history cannot
// reconstruct or rewind a validator's private signing state. The root identity
// is published only after full monetary replay and exact SDK store validation.
import (
	"bytes"
	"context"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"syscall"

	dbm "github.com/cometbft/cometbft-db"
	cmtjson "github.com/cometbft/cometbft/libs/json"
	sm "github.com/cometbft/cometbft/state"
	cmtstore "github.com/cometbft/cometbft/store"
	"github.com/cometbft/cometbft/types"
	"github.com/syndtr/goleveldb/leveldb"
	"github.com/syndtr/goleveldb/leveldb/opt"
	"github.com/syndtr/goleveldb/leveldb/storage"
)

const financialObserverScope = "FULL_SELECTED_ORIGINAL_REPLAY_AND_AUTHENTICATED_SDK_OFFLINE_BOOTSTRAP_FOR_OWNED_NONVOTING_OBSERVER_NOT_SIGNER_RECOVERY_OR_LIVE_CONTACT"

var errFinancialObserverStorageUnavailable = errors.New("GG_OBSERVER_RECOVERY_STORAGE_UNAVAILABLE")

// Call only for the error from an actual owned storage operation. A storage
// obstacle grants no recovery authority and never resets or retries a target.
// Numeric 32/33 are Windows sharing/lock violations; on POSIX they have other
// meanings (including EPIPE), so those numbers are deliberately OS guarded.
func financialObserverStorageError(cause, otherwise error) error {
	if errors.Is(cause, context.Canceled) || errors.Is(cause, context.DeadlineExceeded) {
		return otherwise
	}
	if os.IsPermission(cause) || errors.Is(cause, os.ErrPermission) || errors.Is(cause, storage.ErrLocked) {
		return errFinancialObserverStorageUnavailable
	}
	if runtime.GOOS == "windows" {
		var code syscall.Errno
		if errors.As(cause, &code) && (code == 32 || code == 33) {
			return errFinancialObserverStorageUnavailable
		}
	}
	return otherwise
}

// The pinned SDK consumes its offline-sync marker at construction, before any
// block has been downloaded. A stopped, still-unjoined restored observer needs
// that same context again. Restore ONLY this hint after exact public snapshot
// and SDK graph checks; never bootstrap stores or change a voter's state here.
func prepareFinancialObserverSDKStartup(ctx context.Context, boot Bootstrap, app *Ledger, root string) error {
	return prepareFinancialObserverSDKStartupWithFault(ctx, boot, app, root, nil)
}

// The private callback observes a result only after a real successful close.
// Public/native startup never supplies it and no wire field can enable it.
func prepareFinancialObserverSDKStartupWithFault(ctx context.Context, boot Bootstrap, app *Ledger, root string, fault func(string) error) (failure error) {
	defer func() {
		if recover() != nil {
			failure = errFinancialSDKRecovery
		}
	}()
	if (boot.observer == nil && (boot.public == nil || boot.public.Role != "REPLICA")) || app == nil || app.financial == nil {
		return nil
	}
	if ctx == nil {
		return errFinancialSDKRecovery
	}
	if ctx.Err() != nil {
		return ctx.Err()
	}
	backend, ok := app.financial.(*financialNativeApplication)
	if !ok {
		return errFinancialSDKRecovery
	}
	saved := backend.store.head.Recovery
	if saved == nil {
		return nil
	}
	if filepath.Clean(boot.Root) != filepath.Clean(root) || !filepath.IsAbs(root) || !realArchiveDirectory(root) ||
		boot.GenesisHash != app.anchor || !bytes.Equal(canonical(boot.Genesis), canonical(app.genesis)) {
		return errFinancialSDKRecovery
	}
	marker, identity, err := nativeRootIdentity(boot)
	if err != nil {
		return errFinancialSDKRecovery
	}
	file, _, err := checkedSegmentFile(filepath.Join(root, marker), false, 65536)
	if err != nil {
		return errFinancialSDKRecovery
	}
	actualIdentity, readErr := io.ReadAll(io.LimitReader(file, 65537))
	closeErr := file.Close()
	if readErr != nil || closeErr != nil || !bytes.Equal(actualIdentity, identity) {
		return errFinancialSDKRecovery
	}
	data := filepath.Join(root, "data")
	open := func(name string, readOnly bool) (dbm.DB, error) {
		if !realArchiveDirectory(data) || !realArchiveDirectory(filepath.Join(data, name+".db")) {
			return nil, errFinancialSDKRecovery
		}
		return dbm.NewGoLevelDBWithOpts(name, data, &opt.Options{ReadOnly: readOnly, ErrorIfMissing: true, Strict: opt.StrictAll,
			WriteBuffer: 512 * 1024, BlockCacheCapacity: 512 * 1024, OpenFilesCacheCapacity: 16})
	}
	blocks, err := open("blockstore", true)
	if err != nil {
		return errFinancialSDKRecovery
	}
	blockStore := cmtstore.NewBlockStore(blocks)
	if blockStore.Height() > 0 {
		return blocks.Close()
	} // Joined: no snapshot hint may be reinstated.
	if blockStore.Base() != 0 {
		blocks.Close()
		return errFinancialSDKRecovery
	}
	blockGraph, err := financialSDKGraph(blocks)
	closeErr = blocks.Close()
	if err != nil || closeErr != nil {
		return errFinancialSDKRecovery
	}
	if !saved.Complete || saved.Certificate == nil || len(saved.SDKCommit) == 0 || app.state.Height < 1 ||
		app.state.Height != saved.Height-1 || !bytes.Equal(canonical(app.state), canonical(saved.Certificate.State)) {
		return errFinancialSDKRecovery
	}
	recovery, err := newFinancialSDKRecovery(app.genesis)
	if err != nil {
		return err
	}
	if publicFinancialProtocol(app.genesis) {
		owned := backend.store.recoverySDK
		if owned == nil || owned.state.LastBlockHeight != app.state.Height || owned.commit == nil {
			return errFinancialSDKRecovery
		}
		copy := *owned
		copy.state = owned.state.Copy()
		recovery = &copy
	}
	header := func(height int64) (*types.Header, error) {
		raw, err := backend.store.history.requiredRead(ctx, func(key string) ([]byte, error) { return backend.store.history.get(ctx, key) }, financialSDKHeaderKey(height))
		if err != nil {
			return nil, errFinancialSDKRecovery
		}
		header, err := checkedFinancialSDKHeader(raw, app.genesis, height)
		if err != nil {
			return nil, backend.store.history.rejectRecord(ctx, err)
		}
		return header, nil
	}
	current, err := header(1)
	if err != nil {
		return err
	}
	for height := int64(1); !publicFinancialProtocol(app.genesis) && height <= app.state.Height; height++ {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		next, err := header(height + 1)
		if err != nil || !bytes.Equal(current.Hash(), next.LastBlockID.Hash) || recovery.advance(current, next) != nil {
			return errFinancialSDKRecovery
		}
		if height == app.state.Height {
			if hex.EncodeToString(next.Hash()) != saved.Block || recovery.bindCommit(current, next, saved.SDKCommit) != nil {
				return errFinancialSDKRecovery
			}
		}
		current = next
	}
	base, expected, commits, err := financialSDKGeneratedGraphs(recovery)
	if err != nil || !financialSDKGraphEqual(blockGraph, commits) {
		return errFinancialSDKRecovery
	}
	// Derive the marker key/encoding through the pinned SDK rather than treating
	// arbitrary SDK metadata as an accepted repair target.
	markerKey := ""
	for key := range expected {
		if _, exists := base[key]; !exists {
			if markerKey != "" {
				return errFinancialSDKRecovery
			}
			markerKey = key
		}
	}
	zeroDB := dbm.NewMemDB()
	zeroErr := sm.NewStore(zeroDB, sm.StoreOptions{DiscardABCIResponses: false}).SetOfflineStateSyncHeight(0)
	zero, graphErr := financialSDKGraph(zeroDB)
	zeroDB.Close()
	if zeroErr != nil || graphErr != nil || markerKey == "" || len(zero) != 1 || zero[markerKey] == nil {
		return errFinancialSDKRecovery
	}
	stateDB, err := open("state", false)
	if err != nil {
		return errFinancialSDKRecovery
	}
	defer func() {
		// Exactly one actual Close, including all error/cancellation returns.
		// Its result can replace only an otherwise successful return.
		closeErr := stateDB.Close()
		if failure != nil {
			return
		}
		if closeErr != nil {
			failure = financialObserverStorageError(closeErr, errFinancialSDKRecovery)
			return
		}
		if financialObserverFault(fault, "SDK_STARTUP_STATE_CLOSE") != nil {
			failure = errFinancialSDKRecovery
		}
	}()
	actual, err := financialSDKGraph(stateDB)
	if err != nil {
		return errFinancialSDKRecovery
	}
	if stored, exists := actual["genesisDoc"]; exists {
		document := genesisDoc(app.genesis)
		if document.ValidateAndComplete() != nil {
			return errFinancialSDKRecovery
		}
		encoded, err := cmtjson.Marshal(document)
		if err != nil || !bytes.Equal(stored, encoded) {
			return errFinancialSDKRecovery
		}
		expected["genesisDoc"] = encoded
	}
	wasCleared := bytes.Equal(actual[markerKey], zero[markerKey])
	if !wasCleared && !bytes.Equal(actual[markerKey], expected[markerKey]) {
		return errFinancialSDKRecovery
	}
	actual[markerKey] = expected[markerKey]
	if !financialSDKGraphEqual(actual, expected) {
		return errFinancialSDKRecovery
	}
	if ctx.Err() != nil {
		return ctx.Err()
	}
	if !wasCleared {
		return nil
	}
	return sm.NewStore(stateDB, sm.StoreOptions{DiscardABCIResponses: false}).SetOfflineStateSyncHeight(recovery.state.LastBlockHeight)
}

const financialObserverIntentDB = "gg-observer-recovery.leveldb"
const financialObserverMarkerStage = ".gg-observer-recovery-root.tmp"

var errFinancialObserverRecovery = errors.New("GG_OBSERVER_RECOVERY_INVALID_OR_USED_TARGET")

type financialObserverRestoreCommand struct {
	financialArchiveCommand
	ArchiveHash   string              `json:"expected_archive_sha256"`
	ObserverGrant nativeObserverGrant `json:"observer_grant"`
}

type financialObserverRestoreIntent struct {
	Archive     string                `json:"archive_sha256"`
	Certificate dagArchiveCertificate `json:"certificate"`
	Grant       nativeObserverGrant   `json:"observer_grant"`
	Phase       int                   `json:"phase"`
	Schema      string                `json:"schema"`
	Identity    json.RawMessage       `json:"identity,omitempty"`
}

type financialObserverIntentStore struct {
	db    *leveldb.DB
	head  financialObserverRestoreIntent
	fault func(string) error
}

func financialObserverFault(fault func(string) error, point string) error {
	if fault != nil {
		return fault(point)
	}
	return nil
}

func financialObserverLayoutName(name string) bool {
	return name == financialObserverIntentDB || name == "gg-financial-dag.leveldb" || name == "gg-financial-history" || name == "data" || name == "config" || name == nativeObserverRootFile || name == nativePublicRootFile || name == financialObserverMarkerStage
}

func financialObserverRootLayout(root string) (bool, error) {
	entries, err := archiveDirectoryEntries(root, 8)
	if err != nil || len(entries) > 8 {
		return false, errFinancialObserverRecovery
	}
	owned := false
	for _, entry := range entries {
		if !financialObserverLayoutName(entry.Name()) || entry.Type()&os.ModeSymlink != 0 {
			return false, errFinancialObserverRecovery
		}
		info, err := entry.Info()
		if err != nil {
			return false, errFinancialObserverRecovery
		}
		if entry.Name() == nativeObserverRootFile || entry.Name() == nativePublicRootFile || entry.Name() == financialObserverMarkerStage {
			if !info.Mode().IsRegular() {
				return false, errFinancialObserverRecovery
			}
		} else if !info.IsDir() {
			return false, errFinancialObserverRecovery
		}
		if entry.Name() == financialObserverIntentDB {
			owned = true
		}
		if entry.Name() == "config" {
			children, e := archiveDirectoryEntries(filepath.Join(root, "config"), 0)
			if e != nil || len(children) > 0 {
				return false, errFinancialObserverRecovery
			}
		}
		if entry.Name() == "data" {
			children, e := archiveDirectoryEntries(filepath.Join(root, "data"), 2)
			if e != nil || len(children) > 2 {
				return false, errFinancialObserverRecovery
			}
			for _, child := range children {
				if (child.Name() != "state.db" && child.Name() != "blockstore.db") || !child.IsDir() || child.Type()&os.ModeSymlink != 0 {
					return false, errFinancialObserverRecovery
				}
			}
		}
	}
	if len(entries) > 0 && !owned {
		return false, errFinancialObserverRecovery
	}
	return owned, nil
}

func openFinancialObserverIntent(root string, want financialObserverRestoreIntent, fault func(string) error) (*financialObserverIntentStore, error) {
	owned, err := financialObserverRootLayout(root)
	if err != nil {
		return nil, err
	}
	path := filepath.Join(root, financialObserverIntentDB)
	db, err := leveldb.OpenFile(path, &opt.Options{ErrorIfExist: !owned, ErrorIfMissing: owned, Strict: opt.StrictAll, WriteBuffer: 512 * 1024, BlockCacheCapacity: 512 * 1024, OpenFilesCacheCapacity: 16})
	if err != nil {
		return nil, financialObserverStorageError(err, errFinancialObserverRecovery)
	}
	ok := false
	defer func() {
		if !ok {
			_ = db.Close()
		}
	}()
	iterator := db.NewIterator(nil, nil)
	keys := 0
	var raw []byte
	for iterator.Next() {
		keys++
		if keys > 1 || string(iterator.Key()) != "head" {
			iterator.Release()
			return nil, errFinancialObserverRecovery
		}
		raw = append([]byte(nil), iterator.Value()...)
	}
	err = iterator.Error()
	iterator.Release()
	if err != nil {
		return nil, errFinancialObserverRecovery
	}
	store := &financialObserverIntentStore{db: db, head: want, fault: fault}
	if keys == 0 {
		entries, e := archiveDirectoryEntries(root, 1)
		if e != nil || len(entries) != 1 || entries[0].Name() != financialObserverIntentDB {
			return nil, errFinancialObserverRecovery
		}
		if err = store.write("INTENT"); err != nil {
			return nil, err
		}
	} else {
		var head financialObserverRestoreIntent
		if len(raw) > 512*1024 || decodeStrictLimited(raw, &head, 128, 64) != nil || !bytes.Equal(raw, canonical(head)) || head.Phase < 0 || head.Phase > 3 {
			return nil, errFinancialObserverRecovery
		}
		actual := head
		actual.Phase = 0
		if !bytes.Equal(canonical(actual), canonical(want)) {
			return nil, errors.New("GG_OBSERVER_RECOVERY_INTENT_CHANGED")
		}
		store.head = head
	}
	ok = true
	return store, nil
}

func (s *financialObserverIntentStore) write(point string) error {
	if err := financialObserverFault(s.fault, point+"_BEFORE_SYNC"); err != nil {
		return err
	}
	batch := new(leveldb.Batch)
	batch.Put([]byte("head"), canonical(s.head))
	if err := s.db.Write(batch, &opt.WriteOptions{Sync: true, NoWriteMerge: true}); err != nil {
		return financialObserverStorageError(err, errFinancialObserverRecovery)
	}
	return financialObserverFault(s.fault, point+"_AFTER_SYNC")
}
func (s *financialObserverIntentStore) phase(phase int, point string) error {
	if s.head.Phase >= phase {
		return nil
	}
	s.head.Phase = phase
	return s.write(point)
}

func financialSDKGraph(database dbm.DB) (values map[string][]byte, failure error) {
	iterator, err := database.Iterator(nil, nil)
	if err != nil {
		return nil, err
	}
	defer func() {
		if closeErr := iterator.Close(); closeErr != nil {
			values = nil
			failure = errors.Join(failure, closeErr)
		}
	}()
	values = map[string][]byte{}
	for ; iterator.Valid(); iterator.Next() {
		if len(values) >= 16 || len(iterator.Key()) > 256 || len(iterator.Value()) > dagArchiveHeaderLimit {
			return nil, errFinancialObserverRecovery
		}
		values[string(iterator.Key())] = append([]byte(nil), iterator.Value()...)
	}
	return values, iterator.Error()
}
func financialSDKGraphEqual(a, b map[string][]byte) bool {
	if len(a) != len(b) {
		return false
	}
	for key, value := range a {
		if other, ok := b[key]; !ok || !bytes.Equal(value, other) {
			return false
		}
	}
	return true
}
func financialSDKGeneratedGraphs(recovery *financialSDKRecovery) (map[string][]byte, map[string][]byte, map[string][]byte, error) {
	// The actual pinned SDK encodes every record; no private key or old RPC index
	// is copied. The fresh disk stores are checked against this bounded encoding.
	stateDB := dbm.NewMemDB()
	defer stateDB.Close()
	store := sm.NewStore(stateDB, sm.StoreOptions{DiscardABCIResponses: false})
	if err := store.Bootstrap(recovery.state); err != nil {
		return nil, nil, nil, err
	}
	base, err := financialSDKGraph(stateDB)
	if err != nil {
		return nil, nil, nil, err
	}
	if err = store.SetOfflineStateSyncHeight(recovery.state.LastBlockHeight); err != nil {
		return nil, nil, nil, err
	}
	full, err := financialSDKGraph(stateDB)
	if err != nil {
		return nil, nil, nil, err
	}
	blocks := dbm.NewMemDB()
	defer blocks.Close()
	if err = cmtstore.NewBlockStore(blocks).SaveSeenCommit(recovery.state.LastBlockHeight, recovery.commit); err != nil {
		return nil, nil, nil, err
	}
	commits, err := financialSDKGraph(blocks)
	return base, full, commits, err
}

func bootstrapFinancialObserverSDK(root string, recovery *financialSDKRecovery, readOnly bool, fault func(string) error) (err error) {
	defer func() {
		if recover() != nil {
			err = errFinancialObserverRecovery
		}
	}()
	if recovery == nil || recovery.commit == nil || recovery.state.LastBlockHeight < 1 {
		return errFinancialSDKRecovery
	}
	base, full, commits, err := financialSDKGeneratedGraphs(recovery)
	if err != nil {
		return err
	}
	data := filepath.Join(root, "data")
	if !readOnly {
		if e := os.Mkdir(data, 0700); e != nil && !os.IsExist(e) {
			return financialObserverStorageError(e, errFinancialObserverRecovery)
		}
	}
	if !realArchiveDirectory(data) {
		return errFinancialObserverRecovery
	}
	for _, name := range []string{"state", "blockstore"} {
		directory := filepath.Join(data, name+".db")
		_, inspect := os.Lstat(directory)
		exists := inspect == nil
		if exists && !realArchiveDirectory(directory) || !exists && !os.IsNotExist(inspect) || readOnly && !exists {
			return errFinancialObserverRecovery
		}
		database, e := dbm.NewGoLevelDBWithOpts(name, data, &opt.Options{ReadOnly: readOnly, ErrorIfMissing: exists || readOnly, ErrorIfExist: !exists, Strict: opt.StrictAll, WriteBuffer: 512 * 1024, BlockCacheCapacity: 512 * 1024, OpenFilesCacheCapacity: 16})
		if e != nil {
			return financialObserverStorageError(e, errFinancialObserverRecovery)
		}
		err = func() error {
			defer database.Close()
			actual, e := financialSDKGraph(database)
			if e != nil {
				return errFinancialObserverRecovery
			}
			expected := full
			if name == "blockstore" {
				expected = commits
			}
			if readOnly {
				if !financialSDKGraphEqual(actual, expected) {
					return errFinancialObserverRecovery
				}
				closeErr := database.Close()
				if closeErr != nil {
					return financialObserverStorageError(closeErr, errFinancialObserverRecovery)
				}
				if closeErr == nil {
					point := "SDK_STATE_READONLY_CLOSE"
					if name == "blockstore" {
						point = "SDK_BLOCKSTORE_READONLY_CLOSE"
					}
					// Owned fault seam after a real close, never decoded from a command.
					closeErr = financialObserverFault(fault, point)
				}
				if closeErr != nil {
					// Public errors never expose a filesystem path or close detail.
					return errFinancialObserverRecovery
				}
				return nil
			}
			if name == "state" {
				if len(actual) == 0 {
					if e = financialObserverFault(fault, "SDK_STATE_BEFORE_BOOTSTRAP"); e != nil {
						return e
					}
					if e = sm.NewStore(database, sm.StoreOptions{DiscardABCIResponses: false}).Bootstrap(recovery.state); e != nil {
						return e
					}
					if e = financialObserverFault(fault, "SDK_STATE_AFTER_BOOTSTRAP"); e != nil {
						return e
					}
				} else if !financialSDKGraphEqual(actual, base) && !financialSDKGraphEqual(actual, full) {
					return errFinancialObserverRecovery
				}
				if e = financialObserverFault(fault, "SDK_STATE_BEFORE_MARKER"); e != nil {
					return e
				}
				if e = sm.NewStore(database, sm.StoreOptions{DiscardABCIResponses: false}).SetOfflineStateSyncHeight(recovery.state.LastBlockHeight); e != nil {
					return e
				}
				batch := database.NewBatch()
				defer batch.Close()
				for key, value := range full {
					if _, ok := base[key]; !ok {
						if e = batch.Set([]byte(key), value); e != nil {
							return e
						}
					}
				}
				if e = batch.WriteSync(); e != nil {
					return e
				}
				if e = financialObserverFault(fault, "SDK_STATE_AFTER_MARKER"); e != nil {
					return e
				}
			} else {
				if len(actual) > 0 && !financialSDKGraphEqual(actual, commits) {
					return errFinancialObserverRecovery
				}
				if e = financialObserverFault(fault, "SDK_COMMIT_BEFORE_SYNC"); e != nil {
					return e
				}
				batch := database.NewBatch()
				defer batch.Close()
				for key, value := range commits {
					if e = batch.Set([]byte(key), value); e != nil {
						return e
					}
				}
				if e = batch.WriteSync(); e != nil {
					return e
				}
				if e = financialObserverFault(fault, "SDK_COMMIT_AFTER_SYNC"); e != nil {
					return e
				}
			}
			actual, e = financialSDKGraph(database)
			if e != nil || !financialSDKGraphEqual(actual, expected) {
				return errFinancialObserverRecovery
			}
			closeErr := database.Close()
			return financialObserverStorageError(closeErr, closeErr)
		}()
		if err != nil {
			return err
		}
	}
	return nil
}

func publishFinancialObserverRoot(root string, identity []byte, fault func(string) error) error {
	return publishFinancialOwnedRoot(root, nativeObserverRootFile, identity, fault)
}

func publishFinancialOwnedRoot(root, markerName string, identity []byte, fault func(string) error) error {
	if markerName != nativeObserverRootFile && markerName != nativePublicRootFile {
		return errFinancialObserverRecovery
	}
	marker := filepath.Join(root, markerName)
	stage := filepath.Join(root, financialObserverMarkerStage)
	if err := financialObserverFault(fault, "ROOT_MARKER_BEFORE"); err != nil {
		return err
	}
	if info, err := os.Lstat(marker); err == nil {
		raw, e := os.ReadFile(marker)
		if e != nil || !info.Mode().IsRegular() || !bytes.Equal(raw, identity) {
			return financialObserverStorageError(e, errFinancialObserverRecovery)
		}
		if pending, e := os.Lstat(stage); e == nil {
			if !os.SameFile(info, pending) {
				return errFinancialObserverRecovery
			}
			if e = os.Remove(stage); e != nil {
				return financialObserverStorageError(e, e)
			}
		} else if !os.IsNotExist(e) {
			return financialObserverStorageError(e, errFinancialObserverRecovery)
		}
		return nil
	} else if !os.IsNotExist(err) {
		return financialObserverStorageError(err, errFinancialObserverRecovery)
	}
	file, err := os.OpenFile(stage, os.O_RDWR|os.O_CREATE|os.O_EXCL, 0600)
	if os.IsExist(err) {
		file, _, err = checkedSegmentFile(stage, true, int64(len(identity)))
	}
	if err != nil {
		return financialObserverStorageError(err, errFinancialObserverRecovery)
	}
	defer file.Close()
	existing, err := io.ReadAll(io.LimitReader(file, int64(len(identity))+1))
	if err != nil || len(existing) > len(identity) || !bytes.Equal(existing, identity[:len(existing)]) {
		return errFinancialObserverRecovery
	}
	if len(existing) < len(identity) {
		if _, err = file.Write(identity[len(existing):]); err != nil {
			return financialObserverStorageError(err, err)
		}
	}
	if err = file.Sync(); err != nil {
		return financialObserverStorageError(err, err)
	}
	if err = file.Close(); err != nil {
		return financialObserverStorageError(err, err)
	}
	if err = os.Link(stage, marker); err != nil {
		return financialObserverStorageError(err, errFinancialObserverRecovery)
	}
	if err = financialObserverFault(fault, "ROOT_MARKER_AFTER_LINK"); err != nil {
		return err
	}
	if err = os.Remove(stage); err != nil {
		return financialObserverStorageError(err, err)
	}
	return financialObserverFault(fault, "ROOT_MARKER_AFTER_SYNC")
}

func restoreFinancialObserver(ctx context.Context, request financialObserverRestoreCommand, fault func(string) error) (map[string]any, error) {
	if request.Certificate == nil || request.Root != "" || !pubPattern.MatchString(request.ArchiveHash) || !filepath.IsAbs(request.ArchivePath) || !filepath.IsAbs(request.RestoreRoot) ||
		validateGenesis(request.Genesis, request.GenesisHash) != nil || request.Genesis.FinancialDAG == nil || validateNativeObserverGrant(request.ObserverGrant, request.Genesis, request.GenesisHash) != nil {
		return nil, errFinancialObserverRecovery
	}
	// The protected Python profile serializes object keys in a different order
	// from cmtjson. Normalize the independently verified expected certificate
	// before exact intent comparison; signatures and committed bytes are unchanged.
	expected, _, verifyErr := checkedFinancialArchiveCertificate(*request.Certificate, request.financialArchiveCommand)
	if verifyErr != nil {
		return nil, verifyErr
	}
	request.Certificate = &expected
	file, info, err := openFinancialArchiveInput(request.ArchivePath)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	var sdk *financialSDKRecovery
	result, err := readFinancialArchiveUsing(ctx, file, request.financialArchiveCommand, nil, func(cursor *financialArchiveReplay) error { sdk = cursor.sdkRecovery; return nil })
	if err != nil {
		return nil, err
	}
	if result["archive_sha256"] != request.ArchiveHash || sdk == nil || sdk.commit == nil || !bytes.Equal(canonical(result["certificate"]), canonical(*request.Certificate)) || !unchangedFinancialArchive(file, info) {
		return nil, errFinancialSDKRecovery
	}
	root := filepath.Clean(request.RestoreRoot)
	archivePath, err := filepath.EvalSymlinks(request.ArchivePath)
	if err != nil || pathWithinArchiveRoot(archivePath, root) {
		return nil, errFinancialObserverRecovery
	}
	_, identity, err := nativeRootIdentity(Bootstrap{Root: root, Genesis: request.Genesis, GenesisHash: request.GenesisHash, observer: &nativeObserverBootstrap{ObserverGrant: request.ObserverGrant}})
	if err != nil {
		return nil, err
	}
	if err = os.Mkdir(root, 0700); err != nil && !os.IsExist(err) {
		return nil, financialObserverStorageError(err, errFinancialObserverRecovery)
	}
	if !realArchiveDirectory(root) {
		return nil, errFinancialObserverRecovery
	}
	want := financialObserverRestoreIntent{Archive: request.ArchiveHash, Certificate: *request.Certificate, Grant: request.ObserverGrant, Schema: "gg.financial.observer-recovery.v1"}
	intent, err := openFinancialObserverIntent(root, want, fault)
	if err != nil {
		return nil, err
	}
	defer intent.db.Close()
	reused := intent.head.Phase == 3
	if intent.head.Phase >= 2 {
		if err = bootstrapFinancialObserverSDK(root, sdk, true, fault); err != nil {
			return nil, err
		}
	}
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	if err = financialObserverFault(fault, "APPLICATION_BEFORE"); err != nil {
		return nil, err
	}
	if _, err = file.Seek(0, io.SeekStart); err != nil {
		return nil, err
	}
	result, err = restoreFinancialArchiveInLayout(ctx, file, info, request.financialArchiveCommand, nil, true)
	if err != nil {
		return nil, err
	}
	if err = financialObserverFault(fault, "APPLICATION_AFTER"); err != nil {
		return nil, err
	}
	if result["archive_sha256"] != request.ArchiveHash || !unchangedFinancialArchive(file, info) {
		return nil, errFinancialObserverRecovery
	}
	if err = intent.phase(1, "APP_PHASE"); err != nil {
		return nil, err
	}
	if intent.head.Phase < 2 {
		if err = bootstrapFinancialObserverSDK(root, sdk, false, fault); err != nil {
			return nil, err
		}
		if err = intent.phase(2, "SDK_PHASE"); err != nil {
			return nil, err
		}
	}
	if err = bootstrapFinancialObserverSDK(root, sdk, true, fault); err != nil {
		return nil, err
	}
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	if err = publishFinancialObserverRoot(root, identity, fault); err != nil {
		return nil, err
	}
	if err = intent.phase(3, "COMPLETE"); err != nil {
		return nil, err
	}
	if err = intent.db.Close(); err != nil {
		return nil, financialObserverStorageError(err, err)
	}
	result["verification_scope"] = financialObserverScope
	result["consensus_store_restored"] = true
	result["observer_store_restored"] = true
	result["sdk_offline_bootstrap_complete"] = true
	result["consensus_signing"] = false
	result["native_node_ready"] = false
	result["restore_reused"] = reused
	result["SDK_historical_block_bodies_restored"] = false
	return result, nil
}

func runFinancialObserverRestoreCommand(raw []byte) (map[string]any, error) {
	var request financialObserverRestoreCommand
	if len(raw) > 512*1024 || decodeStrictLimited(raw, &request, 128, 64) != nil {
		return nil, errFinancialObserverRecovery
	}
	return restoreFinancialObserver(context.Background(), request, nil)
}
