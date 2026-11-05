//go:build !js

package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io"
	"os"
	"path/filepath"

	"github.com/syndtr/goleveldb/leveldb"
)

// No recovery path erases or truncates a failed prefix. A matching incomplete
// store is fully replayed and compared byte-for-byte before extending it.
func restoreFinancialArchive(ctx context.Context, file *os.File, info os.FileInfo, request financialArchiveCommand) (map[string]any, error) {
	return restoreFinancialArchiveUsing(ctx, file, info, request, nil)
}

func restoreFinancialArchiveUsing(ctx context.Context, file *os.File, info os.FileInfo, request financialArchiveCommand, configure func(*financialStore)) (map[string]any, error) {
	return restoreFinancialArchiveInLayout(ctx, file, info, request, configure, false)
}

func restoreFinancialArchiveInLayout(ctx context.Context, file *os.File, info os.FileInfo, request financialArchiveCommand, configure func(*financialStore), observerLayout bool) (map[string]any, error) {
	return restoreFinancialArchiveOwned(ctx, file, info, request, configure, observerLayout, nil)
}

// The callback is an in-process ownership transfer, never a decoded command.
// It runs only after full original replay, prefix equality and durable finish.
// A callback failure closes the same store; no partially verified ledger escapes.
func restoreFinancialArchiveOwned(ctx context.Context, file *os.File, info os.FileInfo, request financialArchiveCommand, configure func(*financialStore), observerLayout bool, take func(*Ledger) error) (map[string]any, error) {
	if !filepath.IsAbs(request.RestoreRoot) || !realArchiveDirectory(request.RestoreRoot) {
		return nil, errors.New("GG_FINANCIAL_RESTORE_TARGET")
	}
	root, err := filepath.EvalSymlinks(request.RestoreRoot)
	if err != nil {
		return nil, errors.New("GG_FINANCIAL_RESTORE_TARGET")
	}
	archivePath, err := filepath.EvalSymlinks(request.ArchivePath)
	if err != nil || pathWithinArchiveRoot(archivePath, root) {
		return nil, errors.New("GG_FINANCIAL_RESTORE_TARGET")
	}
	limit := 2
	if observerLayout {
		limit = 7
	}
	entries, err := archiveDirectoryEntries(root, limit)
	if err != nil || len(entries) > limit {
		return nil, errors.New("GG_FINANCIAL_RESTORE_TARGET_NOT_EMPTY_OR_OWNED_PREFIX")
	}
	create := true
	for _, entry := range entries {
		if entry.Name() == "gg-financial-history" {
			continue
		}
		if entry.Name() == "gg-financial-dag.leveldb" {
			create = false
			continue
		}
		if !observerLayout || !financialObserverLayoutName(entry.Name()) {
			return nil, errors.New("GG_FINANCIAL_RESTORE_TARGET_NOT_EMPTY_OR_OWNED_PREFIX")
		}
	}
	// Bind resumability to this exact complete file before any target mutation.
	if _, err = file.Seek(0, io.SeekStart); err != nil {
		return nil, errFinancialArchive
	}
	digest := sha256.New()
	buffer := make([]byte, 64*1024)
	for {
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		n, readErr := file.Read(buffer)
		if n > 0 {
			_, _ = digest.Write(buffer[:n])
			if err := recoveryWork(ctx, uint64(n), nil); err != nil {
				return nil, err
			}
		}
		if readErr == io.EOF {
			break
		}
		if readErr != nil {
			return nil, errFinancialArchive
		}
	}
	archiveHash := hex.EncodeToString(digest.Sum(nil))
	if !unchangedFinancialArchive(file, info) {
		return nil, errors.New("GG_FINANCIAL_ARCHIVE_CHANGED")
	}
	if _, err = file.Seek(0, io.SeekStart); err != nil {
		return nil, errFinancialArchive
	}
	var magic [8]byte
	if _, err = io.ReadFull(file, magic[:]); err != nil || !financialArchiveMagicValid(string(magic[:])) {
		return nil, errFinancialArchive
	}
	raw, err := readArchiveFrame(file, 'H', dagArchiveHeaderLimit)
	var header dagArchiveHeader
	if err != nil || decodeStrictLimited(raw, &header, MaxBlockTxs, 64) != nil || !bytes.Equal(raw, canonical(header)) || !financialArchiveSchemaMatches(string(magic[:]), header.Schema) {
		return nil, errFinancialArchive
	}
	certificate, block, err := checkedFinancialArchiveCertificate(header.Certificate, request)
	if err != nil {
		return nil, err
	}
	if !bytes.Equal(certificate.SignedHeader, header.Certificate.SignedHeader) {
		return nil, errFinancialArchive
	}
	firstHeaderRaw, err := readArchiveFrame(file, 'B', dagArchiveHeaderLimit)
	if err != nil {
		return nil, err
	}
	firstHeader, err := checkedFinancialSDKHeader(firstHeaderRaw, request.Genesis, 1)
	initial := initialState(request.Genesis, request.GenesisHash)
	if err != nil || financialSDKStateBinding(firstHeader, initial) != nil {
		return nil, errFinancialSDKBinding
	}
	recovery := financialStoreRecovery{Archive: archiveHash, Block: block, Height: certificate.State.Height + 1, Certificate: &certificate}
	store, snapshots, execution, err := openFinancialStoreMode(ctx, request.Genesis, request.GenesisHash, root, create, true)
	if err != nil {
		return nil, errors.New("GG_FINANCIAL_RESTORE_PREFIX_INVALID_OR_BUSY")
	}
	transferred := false
	defer func() {
		if !transferred {
			_ = store.close()
		}
	}()
	reused := false
	if store.head.Recovery == nil {
		if store.head.State.Height != 0 || store.head.Journal != DagZero || len(store.candidates) != 0 {
			return nil, errors.New("GG_FINANCIAL_RESTORE_TARGET_NOT_EMPTY_OR_OWNED_PREFIX")
		}
		next := store.head
		next.Schema = "gg.financial-dag.store.v2"
		next.Recovery = &recovery
		batch := new(leveldb.Batch)
		batch.Put([]byte("head"), canonical(next))
		batch.Put([]byte(financialSDKHeaderKey(1)), firstHeaderRaw)
		if err = store.syncWrite(batch); err != nil {
			return nil, err
		}
		store.head = next
	} else {
		actual := *store.head.Recovery
		reused = actual.Complete
		actual.Complete = false
		actual.SDKCommit = nil
		if !bytes.Equal(canonical(actual), canonical(recovery)) || store.head.State.Height > certificate.State.Height {
			return nil, errors.New("GG_FINANCIAL_RESTORE_INTENT_CHANGED")
		}
	}
	storedFirst, err := store.history.requiredRead(ctx, func(key string) ([]byte, error) { return store.history.get(ctx, key) }, financialSDKHeaderKey(1))
	if err != nil || !bytes.Equal(storedFirst, firstHeaderRaw) {
		return nil, store.history.rejectRecord(ctx, errors.New("GG_FINANCIAL_RESTORE_PREFIX_CHANGED"))
	}
	if configure != nil {
		configure(store)
	} // explicit owned fault seam, never decoded from a command
	prefix := store.head
	prefixVerified := prefix.State.Height == 0
	if _, err = file.Seek(0, io.SeekStart); err != nil {
		return nil, errFinancialArchive
	}
	sink := func(entry financialJournalEntry, raw []byte, cursor *financialArchiveReplay) error {
		if entry.Height <= prefix.State.Height {
			original, err := store.history.requiredRead(ctx, func(key string) ([]byte, error) { return store.history.get(ctx, key) }, financialHeightKey(entry.Height))
			if err != nil || !bytes.Equal(raw, original) {
				return store.history.rejectRecord(ctx, errors.New("GG_FINANCIAL_RESTORE_PREFIX_CHANGED"))
			}
			storedHeader, headerErr := store.history.requiredRead(ctx, func(key string) ([]byte, error) { return store.history.get(ctx, key) }, financialSDKHeaderKey(entry.Height+1))
			if headerErr != nil || !bytes.Equal(storedHeader, cursor.sdkNextRaw) {
				return store.history.rejectRecord(ctx, errors.New("GG_FINANCIAL_RESTORE_PREFIX_CHANGED"))
			}
			if entry.Height == prefix.State.Height {
				if prefix.Journal != cursor.journal || !bytes.Equal(canonical(prefix.State), canonical(cursor.state)) || prefix.TimeNs != entry.TimeNs {
					return store.history.rejectRecord(ctx, errors.New("GG_FINANCIAL_RESTORE_PREFIX_CHANGED"))
				}
				prefixVerified = true
			}
			return recoveryWork(ctx, uint64(len(raw)+1), &entry.Height)
		}
		if !prefixVerified {
			return store.history.rejectRecord(ctx, errors.New("GG_FINANCIAL_RESTORE_PREFIX_CHANGED"))
		}
		transaction := []byte(nil)
		if !bytes.Equal(entry.Transaction, []byte("null")) {
			transaction = entry.Transaction
			if err := store.stage(ctx, transaction); err != nil {
				return err
			}
		}
		if err := store.commitWithSDKHeader(ctx, cursor.state, cursor.execution, transaction, cursor.when, cursor.sdkNextRaw); err != nil {
			return err
		}
		if take != nil {
			snapshots = append(snapshots, copyState(cursor.state))
			if len(snapshots) > HistoryLimit {
				snapshots = append([]State(nil), snapshots[len(snapshots)-HistoryLimit:]...)
			}
		}
		return recoveryWork(ctx, uint64(len(raw)+1), &entry.Height)
	}
	var sdkCommit []byte
	var sdk *financialSDKRecovery
	result, err := readFinancialArchiveUsing(ctx, file, request, sink, func(cursor *financialArchiveReplay) error {
		sdkCommit = append([]byte(nil), cursor.sdkCommit...)
		if take == nil {
			return nil
		}
		sdk = cursor.sdkRecovery
		// A replay cursor's scratch readers are about to close. The immutable
		// final execution must use this exact still-owned verified store.
		execution = cursor.execution.clone()
		freezeFinancialLineage(execution, store.readLineageNode)
		if err := freezeFinancialAccounts(execution, store.readAccountNode); err != nil {
			return err
		}
		return freezeFinancialProtocol(execution, store.readProtocolNode)
	})
	if err != nil {
		return nil, err
	}
	if !prefixVerified || result["archive_sha256"] != archiveHash || !unchangedFinancialArchive(file, info) {
		return nil, errors.New("GG_FINANCIAL_ARCHIVE_CHANGED")
	}
	if store.head.State.StateRoot != certificate.State.StateRoot || store.head.State.Height != certificate.State.Height {
		return nil, errors.New("GG_FINANCIAL_RESTORE_STATE_MISMATCH")
	}
	if store.head.Recovery.Complete && !bytes.Equal(store.head.Recovery.SDKCommit, sdkCommit) {
		return nil, store.history.rejectRecord(ctx, errors.New("GG_FINANCIAL_RESTORE_PREFIX_CHANGED"))
	}
	if !store.head.Recovery.Complete {
		done := *store.head.Recovery
		done.Complete = true
		done.SDKCommit = sdkCommit
		next := store.head
		next.Recovery = &done
		batch := new(leveldb.Batch)
		batch.Put([]byte("head"), canonical(next))
		if err = store.syncWrite(batch); err != nil {
			return nil, err
		}
		store.head = next
	}
	if take != nil {
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		if execution == nil || sdk == nil || sdk.commit == nil || store.health() != nil || len(snapshots) == 0 ||
			!bytes.Equal(canonical(snapshots[len(snapshots)-1]), canonical(store.head.State)) {
			return nil, errFinancialSDKRecovery
		}
		if store.history.activeBytes >= financialHistoryActiveTarget {
			if err = store.history.drainTo(ctx, store.head, financialHistoryLowWatermark); err != nil {
				return nil, err
			}
		}
		store.verifiedThrough = store.head.State.Height
		store.recoverySDK = sdk
		if execution.source.hasProtocol() {
			store.execution = execution.clone()
		}
		app := &Ledger{genesis: execution.genesis, anchor: request.GenesisHash, history: snapshots, state: copyState(store.head.State)}
		app.financial = &financialNativeApplication{app: app, current: execution, store: store}
		if err = take(app); err != nil {
			return nil, err
		}
		transferred = true
	} else {
		if err = store.close(); err != nil {
			return nil, errors.New("GG_FINANCIAL_RESTORE_CLOSE")
		}
	}
	result["application_store_restored"] = true
	result["restore_reused"] = reused
	result["native_node_ready"] = false
	return result, nil
}
