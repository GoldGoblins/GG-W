//go:build windows && !js

package main

import (
	"golang.org/x/sys/windows"
	"os"
	"path/filepath"
	"strings"
	"unsafe"
)

// Only add the extended filesystem namespace to an already verified absolute
// target. Reject device namespaces, ADS and legacy name-normalization edges;
// prefixing such a name could otherwise change what the ordinary os call meant.
func financialHistoryWindowsPath(path string) (string, error) {
	if strings.IndexByte(path, 0) >= 0 || !filepath.IsAbs(path) || filepath.Clean(path) != path || strings.Contains(path, "/") {
		return "", errFinancialHistory
	}
	plain := path
	if strings.HasPrefix(plain, `\\?\UNC\`) {
		plain = `\\` + plain[8:]
	} else if strings.HasPrefix(plain, `\\?\`) {
		plain = plain[4:]
	}
	unc := strings.HasPrefix(plain, `\\`)
	var parts []string
	if unc {
		parts = strings.Split(plain[2:], `\`)
		if len(parts) < 3 || parts[0] == "?" || parts[0] == "." {
			return "", errFinancialHistory
		}
	} else {
		if len(plain) < 3 || plain[1] != ':' || plain[2] != '\\' || !(plain[0] >= 'A' && plain[0] <= 'Z' || plain[0] >= 'a' && plain[0] <= 'z') {
			return "", errFinancialHistory
		}
		parts = strings.Split(plain[3:], `\`)
	}
	for _, part := range parts {
		if part == "" || part == "." || part == ".." || strings.ContainsAny(part, ":?*") || strings.TrimRight(part, " .") != part {
			return "", errFinancialHistory
		}
		stem := strings.ToUpper(strings.SplitN(part, ".", 2)[0])
		switch stem {
		case "COM\u00b9", "COM\u00b2", "COM\u00b3", "LPT\u00b9", "LPT\u00b2", "LPT\u00b3":
			return "", errFinancialHistory
		}
		if stem == "CON" || stem == "PRN" || stem == "AUX" || stem == "NUL" || len(stem) == 4 && (strings.HasPrefix(stem, "COM") || strings.HasPrefix(stem, "LPT")) && stem[3] >= '1' && stem[3] <= '9' {
			return "", errFinancialHistory
		}
	}
	if unc {
		return `\\?\UNC\` + plain[2:], nil
	}
	return `\\?\` + plain, nil
}

// FILE_ID_INFO keeps the complete volume64/file-id128 identity. Unsupported
// kernel/filesystem queries fail closed; there is no truncated/zero fallback.
type financialHistoryDirectoryIdentity struct {
	Volume uint64
	ID     [16]byte
}

// Private native IO seam only. No persisted record or caller document can
// supply these functions or turn a previous directory check into authority.
type financialHistoryDirectoryIO struct {
	open    func(string) (windows.Handle, error)
	inspect func(windows.Handle) (financialHistoryDirectoryIdentity, error)
	path    func(windows.Handle) (string, error)
	close   func(windows.Handle) error
}

func financialHistoryOpenDirectory(path string) (windows.Handle, error) {
	name, err := windows.UTF16PtrFromString(path)
	if err != nil {
		return windows.InvalidHandle, errFinancialHistory
	}
	return windows.CreateFile(name, windows.FILE_READ_ATTRIBUTES,
		windows.FILE_SHARE_READ|windows.FILE_SHARE_WRITE|windows.FILE_SHARE_DELETE,
		nil, windows.OPEN_EXISTING, windows.FILE_FLAG_BACKUP_SEMANTICS|windows.FILE_FLAG_OPEN_REPARSE_POINT, 0)
}

func financialHistoryInspectDirectory(handle windows.Handle) (financialHistoryDirectoryIdentity, error) {
	var identity financialHistoryDirectoryIdentity
	var info windows.ByHandleFileInformation
	if windows.GetFileInformationByHandle(handle, &info) != nil ||
		info.FileAttributes&windows.FILE_ATTRIBUTE_DIRECTORY == 0 || info.FileAttributes&windows.FILE_ATTRIBUTE_REPARSE_POINT != 0 {
		return identity, errFinancialHistory
	}
	if windows.GetFileInformationByHandleEx(handle, windows.FileIdInfo,
		(*byte)(unsafe.Pointer(&identity)), uint32(unsafe.Sizeof(identity))) != nil {
		return identity, errFinancialHistory
	}
	return identity, nil
}

func financialHistoryFinalDirectoryPath(handle windows.Handle) (string, error) {
	// FILE_NAME_NORMALIZED | VOLUME_NAME_DOS == 0. One kernel lookup replaces
	// EvalSymlinks' per-component Lstat plus FindFirstFile case-normalization.
	// Keep a finite UTF-16 buffer even for UNC/extended long paths.
	size := uint32(512)
	for attempt := 0; attempt < 2; attempt++ {
		buffer := make([]uint16, size)
		n, err := windows.GetFinalPathNameByHandle(handle, &buffer[0], size, 0)
		if err != nil || n == 0 || n >= 32768 {
			return "", errFinancialHistory
		}
		if n >= size {
			size = n + 1
			continue
		}
		return windows.UTF16ToString(buffer[:n]), nil
	}
	return "", errFinancialHistory
}

func financialHistoryDirectoryDefaultIO() financialHistoryDirectoryIO {
	return financialHistoryDirectoryIO{financialHistoryOpenDirectory, financialHistoryInspectDirectory,
		financialHistoryFinalDirectoryPath, windows.CloseHandle}
}

// Hold the exact opened directory across ONE record read. Every invocation
// reopens/revalidates; neither a boolean nor a prior canonical path is cached.
func financialHistoryReadDirectory(path string) (func() error, error) {
	return financialHistoryWindowsReadDirectory(path, financialHistoryDirectoryDefaultIO())
}

func financialHistoryWindowsReadDirectory(path string, ops financialHistoryDirectoryIO) (func() error, error) {
	expected, err := financialHistoryWindowsPath(path)
	if err != nil || ops.open == nil || ops.inspect == nil || ops.path == nil || ops.close == nil {
		return nil, errFinancialHistory
	}
	validate := func(handle windows.Handle) (financialHistoryDirectoryIdentity, error) {
		identity, err := ops.inspect(handle)
		if err != nil {
			return identity, errFinancialHistory
		}
		resolved, err := ops.path(handle)
		// Exact comparison retains canonical spelling/case and rejects aliases,
		// short names, redirected ancestors, device namespaces and moved dirs.
		if err != nil || resolved != expected {
			return identity, errFinancialHistory
		}
		return identity, nil
	}
	handle, err := ops.open(expected)
	if err != nil {
		return nil, errFinancialHistory
	}
	before, err := validate(handle)
	if err != nil {
		// The operation already fails, including any failed handle cleanup.
		if closeErr := ops.close(handle); closeErr != nil {
			return nil, errFinancialHistory
		}
		return nil, errFinancialHistory
	}
	return func() (failure error) {
		defer func() {
			if ops.close(handle) != nil {
				failure = errFinancialHistory
			}
		}()
		after, err := validate(handle)
		if err != nil || before != after {
			return errFinancialHistory
		}
		// Bind the current pathname back to the same full kernel identity. A
		// renamed/replaced directory cannot pass only because its old fd lives.
		current, err := ops.open(expected)
		if err != nil {
			return errFinancialHistory
		}
		defer func() {
			if ops.close(current) != nil {
				failure = errFinancialHistory
			}
		}()
		actual, err := validate(current)
		if err != nil || actual != before {
			return errFinancialHistory
		}
		return nil
	}, nil
}

func financialHistoryPublish(stage, final string) error {
	stage, err := financialHistoryWindowsPath(stage)
	if err != nil {
		return err
	}
	final, err = financialHistoryWindowsPath(final)
	if err != nil {
		return err
	}
	from, err := windows.UTF16PtrFromString(stage)
	if err != nil {
		return errFinancialHistory
	}
	to, err := windows.UTF16PtrFromString(final)
	if err != nil {
		return errFinancialHistory
	}
	// WRITE_THROUGH, without REPLACE_EXISTING. No foreign destination is replaced.
	if windows.MoveFileEx(from, to, windows.MOVEFILE_WRITE_THROUGH) != nil {
		return errFinancialHistory
	}
	return nil
}
func financialHistorySyncDirectory(path string) error {
	// The Windows publication primitive above provides the synchronous rename.
	// Pending-file removal does not retire an authoritative selected copy; the
	// durable intent is cleared only afterwards. Missing committed files fail.
	return nil
}
func financialHistoryReserve(path string, required uint64) error {
	path, err := financialHistoryWindowsPath(path)
	if err != nil {
		return err
	}
	name, err := windows.UTF16PtrFromString(path)
	if err != nil {
		return errFinancialHistory
	}
	var available, total, free uint64
	if windows.GetDiskFreeSpaceEx(name, &available, &total, &free) != nil || available < required {
		return errFinancialHistory
	}
	return nil
}

func financialRecoveryOpenDirectory(path string) (*os.File, func() error, error) {
	expected, err := financialHistoryWindowsPath(path)
	if err != nil {
		return nil, nil, err
	}
	name, err := windows.UTF16PtrFromString(expected)
	if err != nil {
		return nil, nil, errFinancialHistory
	}
	handle, err := windows.CreateFile(name, windows.FILE_LIST_DIRECTORY|windows.FILE_READ_ATTRIBUTES,
		windows.FILE_SHARE_READ|windows.FILE_SHARE_WRITE|windows.FILE_SHARE_DELETE, nil, windows.OPEN_EXISTING,
		windows.FILE_FLAG_BACKUP_SEMANTICS|windows.FILE_FLAG_OPEN_REPARSE_POINT, 0)
	if err != nil {
		return nil, nil, errFinancialHistory
	}
	file := os.NewFile(uintptr(handle), path)
	before, err := financialHistoryInspectDirectory(handle)
	info, ie := file.Stat()
	if err != nil || ie != nil {
		_ = file.Close()
		return nil, nil, errFinancialHistory
	}
	check := func() (failure error) {
		actual, e := financialHistoryInspectDirectory(handle)
		final, fe := financialHistoryFinalDirectoryPath(handle)
		after, ae := file.Stat()
		if e != nil || fe != nil || ae != nil || actual != before || final != expected || !info.ModTime().Equal(after.ModTime()) {
			return errFinancialHistory
		}
		current, e := financialHistoryOpenDirectory(expected)
		if e != nil {
			return errFinancialHistory
		}
		defer func() {
			if windows.CloseHandle(current) != nil {
				failure = errFinancialHistory
			}
		}()
		identity, e := financialHistoryInspectDirectory(current)
		if e != nil || identity != before {
			return errFinancialHistory
		}
		return nil
	}
	if err = check(); err != nil {
		_ = file.Close()
		return nil, nil, err
	}
	return file, check, nil
}
func financialRecoveryOpenFile(path string) (*os.File, os.FileInfo, error) {
	expected, err := financialHistoryWindowsPath(path)
	if err != nil {
		return nil, nil, err
	}
	name, err := windows.UTF16PtrFromString(expected)
	if err != nil {
		return nil, nil, errFinancialHistory
	}
	handle, err := windows.CreateFile(name, windows.GENERIC_READ, windows.FILE_SHARE_READ, nil, windows.OPEN_EXISTING, windows.FILE_FLAG_OPEN_REPARSE_POINT, 0)
	if err != nil {
		return nil, nil, errFinancialHistory
	}
	file := os.NewFile(uintptr(handle), path)
	var state windows.ByHandleFileInformation
	final, e := financialHistoryFinalDirectoryPath(handle)
	info, ie := file.Stat()
	if windows.GetFileInformationByHandle(handle, &state) != nil || state.FileAttributes&(windows.FILE_ATTRIBUTE_REPARSE_POINT|windows.FILE_ATTRIBUTE_DIRECTORY) != 0 || e != nil || ie != nil || !recoveryPendingLink(path, info, uint64(state.NumberOfLinks)) || final != expected || !info.Mode().IsRegular() {
		_ = file.Close()
		return nil, nil, errFinancialHistory
	}
	return file, info, nil
}

// Metadata-only final namespace check can inspect a live LevelDB LOCK file
// without reading/reinterpreting mutable DB bytes or taking its writer lock.
func financialRecoveryInspectFile(path string) (failure error) {
	expected, err := financialHistoryWindowsPath(path)
	if err != nil {
		return err
	}
	name, err := windows.UTF16PtrFromString(expected)
	if err != nil {
		return errFinancialHistory
	}
	handle, err := windows.CreateFile(name, windows.FILE_READ_ATTRIBUTES, windows.FILE_SHARE_READ|windows.FILE_SHARE_WRITE|windows.FILE_SHARE_DELETE, nil, windows.OPEN_EXISTING, windows.FILE_FLAG_OPEN_REPARSE_POINT, 0)
	if err != nil {
		return errFinancialHistory
	}
	defer func() {
		if windows.CloseHandle(handle) != nil {
			failure = errFinancialHistory
		}
	}()
	var state windows.ByHandleFileInformation
	final, e := financialHistoryFinalDirectoryPath(handle)
	if windows.GetFileInformationByHandle(handle, &state) != nil || state.FileAttributes&(windows.FILE_ATTRIBUTE_REPARSE_POINT|windows.FILE_ATTRIBUTE_DIRECTORY) != 0 || state.NumberOfLinks != 1 || e != nil || final != expected {
		return errFinancialHistory
	}
	return nil
}

// Keep one full-volume64/file-ID128 anchor until the owned attempt returns.
// Validation uses one transient current-path handle and never lazy FileInfo.
func financialRecoveryRootAnchor(path string) (func() error, func() error, error) {
	expected, err := financialHistoryWindowsPath(path)
	if err != nil {
		return nil, nil, err
	}
	ops := financialHistoryDirectoryDefaultIO()
	held, err := ops.open(expected)
	if err != nil {
		return nil, nil, errFinancialHistory
	}
	validate := func(handle windows.Handle) (financialHistoryDirectoryIdentity, error) {
		identity, e := ops.inspect(handle)
		final, pe := ops.path(handle)
		if e != nil || pe != nil || final != expected {
			return identity, errFinancialHistory
		}
		return identity, nil
	}
	before, err := validate(held)
	if err != nil {
		_ = ops.close(held)
		return nil, nil, err
	}
	check := func() (failure error) {
		same, e := validate(held)
		if e != nil || same != before {
			return errFinancialHistory
		}
		current, e := ops.open(expected)
		if e != nil {
			return errFinancialHistory
		}
		defer func() {
			if ops.close(current) != nil {
				failure = errFinancialHistory
			}
		}()
		actual, e := validate(current)
		if e != nil || actual != before {
			return errFinancialHistory
		}
		return nil
	}
	return check, func() error { return ops.close(held) }, nil
}
