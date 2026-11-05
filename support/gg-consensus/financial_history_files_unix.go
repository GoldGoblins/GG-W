//go:build !windows && !js

package main

import (
	"golang.org/x/sys/unix"
	"os"
	"path/filepath"
	"strings"
)

// Preserve the existing POSIX per-read resolution and exact path semantics.
func financialHistoryReadDirectory(path string) (func() error, error) {
	if !realArchiveDirectory(path) {
		return nil, errFinancialHistory
	}
	resolved, err := filepath.EvalSymlinks(path)
	if err != nil || resolved != path {
		return nil, errFinancialHistory
	}
	return func() error { return nil }, nil
}

func financialHistorySyncDirectory(path string) error {
	file, err := os.Open(path)
	if err != nil {
		return errFinancialHistory
	}
	err = file.Sync()
	closeErr := file.Close()
	if err != nil || closeErr != nil {
		return errFinancialHistory
	}
	return nil
}
func financialHistoryPublish(stage, final string) error {
	// Link is exclusive. Publication never replaces an existing file. Recovery
	// recognizes the one possible two-link stage/final pair under its intent.
	if os.Link(stage, final) != nil {
		return errFinancialHistory
	}
	if financialHistorySyncDirectory(filepath.Dir(final)) != nil {
		return errFinancialHistory
	}
	if os.Remove(stage) != nil || financialHistorySyncDirectory(filepath.Dir(final)) != nil {
		return errFinancialHistory
	}
	return nil
}
func financialHistoryReserve(path string, required uint64) error {
	var state unix.Statfs_t
	if unix.Statfs(path, &state) != nil || state.Bsize <= 0 {
		return errFinancialHistory
	}
	block := uint64(state.Bsize)
	available := uint64(state.Bavail)
	if available < required/block || available == required/block && required%block != 0 {
		return errFinancialHistory
	}
	return nil
}

// Each owned-start directory is held while its64-entry stream is consumed.
// Identity+namespace timestamps are rechecked at every batch; no previous
// process or path-resolution result grants the next invocation trust.
func financialRecoveryOpenDirectory(path string) (*os.File, func() error, error) {
	resolved, err := filepath.EvalSymlinks(path)
	if err != nil || resolved != path {
		return nil, nil, errFinancialHistory
	}
	fd, err := financialRecoveryUnixOpen(path, unix.O_RDONLY|unix.O_DIRECTORY)
	if err != nil {
		return nil, nil, errFinancialHistory
	}
	file := os.NewFile(uintptr(fd), path)
	before, err := file.Stat()
	if err != nil || !before.IsDir() {
		_ = file.Close()
		return nil, nil, errFinancialHistory
	}
	check := func() error {
		after, e := file.Stat()
		current, ce := os.Lstat(path)
		if e != nil || ce != nil || !current.IsDir() || current.Mode()&os.ModeSymlink != 0 || !os.SameFile(before, after) || !os.SameFile(before, current) || !before.ModTime().Equal(after.ModTime()) || !before.ModTime().Equal(current.ModTime()) {
			return errFinancialHistory
		}
		return nil
	}
	return file, check, nil
}
func financialRecoveryOpenFile(path string) (*os.File, os.FileInfo, error) {
	before, err := os.Lstat(path)
	if err != nil || !before.Mode().IsRegular() || before.Mode()&os.ModeSymlink != 0 {
		return nil, nil, errFinancialHistory
	}
	fd, err := financialRecoveryUnixOpen(path, unix.O_RDONLY)
	if err != nil {
		return nil, nil, errFinancialHistory
	}
	file := os.NewFile(uintptr(fd), path)
	after, err := file.Stat()
	var state unix.Stat_t
	if err != nil || unix.Fstat(fd, &state) != nil || !recoveryPendingLink(path, after, uint64(state.Nlink)) || !os.SameFile(before, after) {
		_ = file.Close()
		return nil, nil, errFinancialHistory
	}
	return file, after, nil
}

// Resolve every ancestor through an already opened directory descriptor.
// O_NOFOLLOW applies to every component, not only the last pathname element.
func financialRecoveryUnixOpen(path string, flags int) (int, error) {
	if !filepath.IsAbs(path) || filepath.Clean(path) != path {
		return -1, errFinancialHistory
	}
	fd, err := unix.Open(string(filepath.Separator), unix.O_RDONLY|unix.O_DIRECTORY|unix.O_NOFOLLOW|unix.O_CLOEXEC, 0)
	if err != nil {
		return -1, err
	}
	parts := strings.Split(strings.TrimPrefix(path, string(filepath.Separator)), string(filepath.Separator))
	for index, part := range parts {
		if part == "" || part == "." || part == ".." {
			_ = unix.Close(fd)
			return -1, errFinancialHistory
		}
		nextFlags := unix.O_RDONLY | unix.O_DIRECTORY
		if index == len(parts)-1 {
			nextFlags = flags
		}
		next, e := unix.Openat(fd, part, nextFlags|unix.O_NOFOLLOW|unix.O_CLOEXEC, 0)
		closeErr := unix.Close(fd)
		if e != nil || closeErr != nil {
			if e == nil {
				_ = unix.Close(next)
			}
			return -1, errFinancialHistory
		}
		fd = next
	}
	return fd, nil
}

func financialRecoveryInspectFile(path string) error {
	file, _, err := financialRecoveryOpenFile(path)
	if err != nil {
		return err
	}
	if file.Close() != nil {
		return errFinancialHistory
	}
	return nil
}

// Eager dev/inode comes from the retained descriptor, not a later pathname.
func financialRecoveryRootAnchor(path string) (func() error, func() error, error) {
	held, err := financialRecoveryUnixOpen(path, unix.O_RDONLY|unix.O_DIRECTORY)
	if err != nil {
		return nil, nil, err
	}
	var before unix.Stat_t
	if unix.Fstat(held, &before) != nil {
		_ = unix.Close(held)
		return nil, nil, errFinancialHistory
	}
	check := func() (failure error) {
		var live unix.Stat_t
		if unix.Fstat(held, &live) != nil || live.Dev != before.Dev || live.Ino != before.Ino {
			return errFinancialHistory
		}
		current, e := financialRecoveryUnixOpen(path, unix.O_RDONLY|unix.O_DIRECTORY)
		if e != nil {
			return errFinancialHistory
		}
		defer func() {
			if unix.Close(current) != nil {
				failure = errFinancialHistory
			}
		}()
		var actual unix.Stat_t
		if unix.Fstat(current, &actual) != nil || actual.Dev != before.Dev || actual.Ino != before.Ino {
			return errFinancialHistory
		}
		return nil
	}
	return check, func() error { return unix.Close(held) }, nil
}
