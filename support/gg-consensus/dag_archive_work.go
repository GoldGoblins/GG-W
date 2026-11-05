//go:build !js

package main

// One reusable, leased public workspace per caller-selected work root. Neither
// archives nor their record names choose paths. Working data is never authority.
import (
	"bytes"
	"errors"
	"io"
	"os"
	"path/filepath"

	"github.com/syndtr/goleveldb/leveldb"
	"github.com/syndtr/goleveldb/leveldb/storage"
)

var errDagArchiveWork = errors.New("GG_DAG_ARCHIVE_WORK_UNAVAILABLE")

const dagArchiveOwner = "gg.dag.archive-work.v1\n"

type dagArchiveWork struct {
	replay        *dagReplayWork
	lease         storage.Storage
	metadataBytes uint64
	metadataNodes int
	closed        bool
	closeError    error
}

func realArchiveDirectory(path string) bool {
	info, err := os.Lstat(path)
	return err == nil && info.IsDir() && info.Mode()&os.ModeSymlink == 0
}

func archiveDirectoryEntries(path string, limit int) ([]os.DirEntry, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, errDagArchiveWork
	}
	entries, readErr := file.ReadDir(limit + 1)
	closeErr := file.Close()
	if readErr != nil && readErr != io.EOF || closeErr != nil || len(entries) > limit {
		return nil, errDagArchiveWork
	}
	return entries, nil
}

func openDagArchiveWork(root string) (*dagArchiveWork, error) {
	if !filepath.IsAbs(root) || !realArchiveDirectory(root) {
		return nil, errDagArchiveWork
	}
	parent := filepath.Join(root, "gg-dag-archive-work")
	if err := os.Mkdir(parent, 0700); err != nil && !os.IsExist(err) {
		return nil, errDagArchiveWork
	}
	if !realArchiveDirectory(parent) {
		return nil, errDagArchiveWork
	}
	entries, err := archiveDirectoryEntries(parent, 2)
	if err != nil {
		return nil, errDagArchiveWork
	}
	for _, entry := range entries {
		if entry.Name() != "lease" && entry.Name() != "gg-dag-replay-work" {
			return nil, errDagArchiveWork
		}
	}
	guard := filepath.Join(parent, "lease")
	if err = os.Mkdir(guard, 0700); err != nil && !os.IsExist(err) {
		return nil, errDagArchiveWork
	}
	if !realArchiveDirectory(guard) {
		return nil, errDagArchiveWork
	}
	entries, err = archiveDirectoryEntries(guard, 3)
	if err != nil {
		return nil, errDagArchiveWork
	}
	for _, entry := range entries {
		if entry.Name() != "LOCK" && entry.Name() != "LOG" && entry.Name() != "OWNER" {
			return nil, errDagArchiveWork
		}
		info, statErr := entry.Info()
		if statErr != nil || !info.Mode().IsRegular() || info.Mode()&os.ModeSymlink != 0 {
			return nil, errDagArchiveWork
		}
		if entry.Name() == "OWNER" && info.Size() > int64(len(dagArchiveOwner)) {
			return nil, errDagArchiveWork
		}
	}
	// Hold the parent lease BEFORE checking/reclaiming scratch work. Two archive
	// commands cannot race while one is creating its OWNER/database files.
	lease, err := storage.OpenFile(guard, false)
	if err != nil {
		return nil, errDagArchiveWork
	}
	valid := false
	defer func() {
		if !valid {
			_ = lease.Close()
		}
	}()
	owner := filepath.Join(guard, "OWNER")
	ownerFile, err := os.Open(owner)
	var raw []byte
	if err == nil {
		raw, err = io.ReadAll(io.LimitReader(ownerFile, int64(len(dagArchiveOwner)+1)))
		if ownerFile.Close() != nil {
			return nil, errDagArchiveWork
		}
	}
	if err != nil && !os.IsNotExist(err) || len(raw) > len(dagArchiveOwner) || !bytes.HasPrefix([]byte(dagArchiveOwner), raw) {
		return nil, errDagArchiveWork
	}
	if string(raw) != dagArchiveOwner {
		for _, name := range []string{"LOCK", "LOG"} {
			if info, statErr := os.Lstat(filepath.Join(guard, name)); statErr == nil && info.Size() != 0 || statErr != nil && !os.IsNotExist(statErr) {
				return nil, errDagArchiveWork
			}
		}
		// Only the exact incomplete public owner marker is completed, under the
		// exclusive lease. Unknown files/marker contents are never deleted.
		flags := os.O_WRONLY | os.O_CREATE | os.O_TRUNC
		if os.IsNotExist(err) {
			flags = os.O_WRONLY | os.O_CREATE | os.O_EXCL
		}
		file, openErr := os.OpenFile(owner, flags, 0600)
		if openErr != nil {
			return nil, errDagArchiveWork
		}
		n, writeErr := file.Write([]byte(dagArchiveOwner))
		syncErr := file.Sync()
		closeErr := file.Close()
		if writeErr != nil || n != len(dagArchiveOwner) || syncErr != nil || closeErr != nil {
			return nil, errDagArchiveWork
		}
	}
	work, err := newDagReplayWorkAt(filepath.Join(parent, "gg-dag-replay-work"))
	if err != nil {
		return nil, errDagArchiveWork
	}
	value, ok := work.(*dagReplayWork)
	if !ok {
		_ = work.close()
		return nil, errDagArchiveWork
	}
	valid = true
	return &dagArchiveWork{replay: value, lease: lease}, nil
}

// Keep authenticated history nodes on disposable disk, with fixed per-node,
// byte, entry and LevelDB cache budgets. No old payload or full tree is retained.
func (work *dagArchiveWork) archive(execution *DagExecution) (*DagExecution, error) {
	if work.closed || work.replay == nil || work.replay.db == nil {
		return nil, errDagArchiveWork
	}
	batch := new(leveldb.Batch)
	seen := map[string]bool{}
	bytesAfter, nodesAfter := work.metadataBytes, work.metadataNodes
	err := execution.history.newNodes(seen, func(hash string, body dagHistoryBody) error {
		if len(seen) > 2*DagMaxRecords {
			return errDagArchiveWork
		}
		raw := canonical(body)
		if _, err := decodeHistoryNode(hash, raw); err != nil {
			return err
		}
		key := "hx/" + hash
		previous, err := work.replay.db.Get([]byte(key), nil)
		if err == nil {
			if !bytes.Equal(previous, raw) {
				return errDagArchiveWork
			}
			return nil
		}
		if err != leveldb.ErrNotFound {
			return errDagArchiveWork
		}
		bytesAfter += uint64(len(key) + len(raw))
		nodesAfter++
		if bytesAfter > dagMetadataMaxBytes || nodesAfter > dagMetadataMaxNodes {
			return errDagArchiveWork
		}
		batch.Put([]byte(key), raw)
		return nil
	})
	if err != nil || work.replay.db.Write(batch, nil) != nil {
		return nil, errDagArchiveWork
	}
	work.metadataBytes, work.metadataNodes = bytesAfter, nodesAfter
	next := *execution
	next.pending = map[string]dagRecord{}
	next.history = dagHistory{root: dagHistoryRef{hash: execution.history.root.id()}, read: func(hash string) (dagHistoryBody, error) {
		if work.closed || work.replay.db == nil {
			return dagHistoryBody{}, errDagArchiveWork
		}
		raw, err := work.replay.db.Get([]byte("hx/"+hash), nil)
		if err != nil {
			return dagHistoryBody{}, errDagArchiveWork
		}
		return decodeHistoryNode(hash, raw)
	}}
	return &next, nil
}

func (work *dagArchiveWork) close() error {
	if work.closed {
		return work.closeError
	}
	if work.replay != nil && work.replay.close() != nil {
		work.closeError = errDagArchiveWork
		// An unconfirmed cleanup keeps the parent lease until process exit.
		// No later command in this process may claim this workspace is free.
		return work.closeError
	}
	if work.lease != nil && work.lease.Close() != nil {
		work.closeError = errDagArchiveWork
	}
	work.lease = nil
	work.closed = true
	return work.closeError
}
