//go:build windows && !js

package main

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"golang.org/x/sys/windows"
)

func historyDirectoryFixture(t *testing.T) string {
	t.Helper()
	root, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(root, "ExactDirectoryCase")
	if err := os.Mkdir(path, 0700); err != nil {
		t.Fatal(err)
	}
	return path
}

func historyTrackedDirectoryIO(t *testing.T) (financialHistoryDirectoryIO, map[windows.Handle]bool, *int) {
	t.Helper()
	ops := financialHistoryDirectoryDefaultIO()
	open, close := ops.open, ops.close
	live := map[windows.Handle]bool{}
	opens := new(int)
	ops.open = func(path string) (windows.Handle, error) {
		handle, err := open(path)
		if err == nil {
			live[handle] = true
			(*opens)++
		}
		return handle, err
	}
	ops.close = func(handle windows.Handle) error {
		err := close(handle)
		if err == nil {
			delete(live, handle)
		}
		return err
	}
	t.Cleanup(func() {
		for handle := range live {
			_ = windows.CloseHandle(handle)
			t.Error("directory handle survived its read/failed query")
		}
	})
	return ops, live, opens
}

// Mandatory policy negative even on hosts that cannot create directory links
// or DOS aliases: a real opened target must never authorize another spelling.
func historyDirectoryRejectsResolvedAlias(t *testing.T, target, alias string) {
	t.Helper()
	ops, live, _ := historyTrackedDirectoryIO(t)
	open := ops.open
	canonical, err := financialHistoryWindowsPath(target)
	if err != nil {
		t.Fatal(err)
	}
	ops.open = func(string) (windows.Handle, error) { return open(canonical) }
	finish, err := financialHistoryWindowsReadDirectory(alias, ops)
	if err == nil {
		_ = finish()
		t.Fatal("real canonical directory handle authorized a different alias path")
	}
	if len(live) != 0 {
		t.Fatal("mandatory alias-policy rejection retained a handle")
	}
}

func TestFinancialHistoryWindowsDirectoryUsesActualFreshHandlesAndExactPath(t *testing.T) {
	path := historyDirectoryFixture(t)
	ops, live, opens := historyTrackedDirectoryIO(t)
	for read := 0; read < 2; read++ {
		finish, err := financialHistoryWindowsReadDirectory(path, ops)
		if err != nil || finish == nil || len(live) != 1 {
			t.Fatal("actual directory was not opened and checked", err, len(live))
		}
		if err := finish(); err != nil || len(live) != 0 {
			t.Fatal("actual after-read identity/path binding or cleanup", err, len(live))
		}
	}
	if *opens != 4 {
		t.Fatal("directory validity cached across reads instead of reopening", *opens)
	}
	// Rename after successful closure must work, proving no live read handle
	// was retained outside the per-read guard.
	if err := os.Rename(path, path+"-after-close"); err != nil {
		t.Fatal("successful read retained a directory handle", err)
	}
}

func TestFinancialHistoryWindowsMovedOrRetargetedDirectoryRejectsAndCloses(t *testing.T) {
	for _, replace := range []bool{false, true} {
		t.Run(map[bool]string{false: "renamed", true: "replaced"}[replace], func(t *testing.T) {
			path := historyDirectoryFixture(t)
			ops, live, _ := historyTrackedDirectoryIO(t)
			finish, err := financialHistoryWindowsReadDirectory(path, ops)
			if err != nil {
				t.Fatal(err)
			}
			if err := os.Rename(path, path+"-moved"); err != nil {
				_ = finish()
				t.Fatal("actual directory retarget fixture", err)
			}
			if replace {
				if err := os.Mkdir(path, 0700); err != nil {
					_ = finish()
					t.Fatal(err)
				}
			}
			if finish() == nil || len(live) != 0 {
				t.Fatal("moved/replaced directory accepted or handle leaked", len(live))
			}
		})
	}
}

func TestFinancialHistoryWindowsDirectoryRechecksFullIdentityAndFailsAPIsClosed(t *testing.T) {
	for _, fault := range []string{"inspect-before", "closed-handle-before", "path-before", "inspect-after", "path-after", "reopen", "id128-after", "id128-current", "volume64-after", "close"} {
		t.Run(fault, func(t *testing.T) {
			path := historyDirectoryFixture(t)
			ops, live, _ := historyTrackedDirectoryIO(t)
			open, inspect, resolve, close := ops.open, ops.inspect, ops.path, ops.close
			opens, inspections, paths := 0, 0, 0
			ops.open = func(path string) (windows.Handle, error) {
				opens++
				if fault == "reopen" && opens == 2 {
					return windows.InvalidHandle, windows.ERROR_ACCESS_DENIED
				}
				return open(path)
			}
			ops.inspect = func(handle windows.Handle) (financialHistoryDirectoryIdentity, error) {
				inspections++
				if fault == "closed-handle-before" && inspections == 1 {
					if err := close(handle); err != nil {
						t.Fatal(err)
					}
				}
				identity, err := inspect(handle)
				if fault == "inspect-before" && inspections == 1 || fault == "inspect-after" && inspections == 2 {
					return identity, windows.ERROR_CALL_NOT_IMPLEMENTED
				}
				if fault == "id128-after" && inspections == 2 || fault == "id128-current" && inspections == 3 {
					identity.ID[15] ^= 1 // A high128-bit change must not be truncated.
				}
				if fault == "volume64-after" && inspections == 2 {
					identity.Volume ^= uint64(1) << 63
				}
				return identity, err
			}
			ops.path = func(handle windows.Handle) (string, error) {
				path, err := resolve(handle)
				paths++
				if fault == "path-before" && paths == 1 || fault == "path-after" && paths == 2 {
					return "", windows.ERROR_ACCESS_DENIED
				}
				return path, err
			}
			ops.close = func(handle windows.Handle) error {
				if err := close(handle); err != nil {
					return err
				}
				if fault == "close" {
					return windows.ERROR_ACCESS_DENIED // Real handle already closed.
				}
				return nil
			}
			finish, err := financialHistoryWindowsReadDirectory(path, ops)
			if err == nil {
				err = finish()
			}
			if err == nil || len(live) != 0 {
				t.Fatal("query/identity/close error accepted or leaked handle", err, len(live))
			}
		})
	}
}

func TestFinancialHistoryWindowsDirectoryRejectsWrongCaseNamesFilesAndNamespaces(t *testing.T) {
	path := historyDirectoryFixture(t)
	file := filepath.Join(filepath.Dir(path), "PUBLIC-ordinary-file")
	if err := os.WriteFile(file, []byte("PUBLIC directory type regression"), 0600); err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{file, filepath.Join(filepath.Dir(path), strings.ToLower(filepath.Base(path))), path + `\.`, path + ".", path + ":stream", `\\.\` + path[4:]} {
		ops, live, _ := historyTrackedDirectoryIO(t)
		finish, err := financialHistoryWindowsReadDirectory(name, ops)
		if err == nil {
			_ = finish()
			t.Fatal("noncanonical/type/device/ADS path accepted", name)
		}
		if len(live) != 0 {
			t.Fatal("rejected path retained its handle")
		}
	}
}

func TestFinancialHistoryWindowsDirectoryRejectsFinalAndAncestorLinks(t *testing.T) {
	for _, ancestor := range []bool{false, true} {
		t.Run(map[bool]string{false: "final-link", true: "ancestor-link"}[ancestor], func(t *testing.T) {
			target := historyDirectoryFixture(t)
			link := target + "-alias"
			historyDirectoryRejectsResolvedAlias(t, target, link)
			if err := os.Symlink(target, link); err != nil {
				if errors.Is(err, windows.ERROR_PRIVILEGE_NOT_HELD) || os.IsPermission(err) {
					t.Log("HOST_CAPABILITY_UNEXERCISED: actual directory-symlink creation unavailable; mandatory exact-path alias rejection ran")
					return
				}
				t.Fatal(err)
			}
			if ancestor {
				if err := os.Mkdir(filepath.Join(target, "ExactChild"), 0700); err != nil {
					t.Fatal(err)
				}
				link = filepath.Join(link, "ExactChild")
			}
			ops, live, _ := historyTrackedDirectoryIO(t)
			finish, err := financialHistoryWindowsReadDirectory(link, ops)
			if err == nil {
				_ = finish()
				t.Fatal("actual reparse/ancestor alias accepted")
			}
			if len(live) != 0 {
				t.Fatal("alias rejection retained a handle")
			}
		})
	}
}

func TestFinancialHistoryWindowsDirectorySupportsCanonicalExtendedLongPaths(t *testing.T) {
	path := historyDirectoryFixture(t)
	for len(path) < 620 {
		path = filepath.Join(path, "canonical-history-long-path-component")
		if err := os.Mkdir(path, 0700); err != nil {
			t.Fatal(err)
		}
	}
	for _, name := range []string{path, `\\?\` + path} {
		finish, err := financialHistoryReadDirectory(name)
		if err != nil {
			t.Fatal("canonical long path rejected", err)
		}
		if err := finish(); err != nil {
			t.Fatal("long path after-read check or closure", err)
		}
	}
	// Syntax-only UNC preservation; ordinary tests never contact a network share.
	if path, err := financialHistoryWindowsPath(`\\server\share\CanonicalHistory`); err != nil || path != `\\?\UNC\server\share\CanonicalHistory` {
		t.Fatal("canonical UNC namespace mapping changed", path, err)
	}
}

func TestFinancialHistoryWindowsDirectoryRejectsActualShortNameAlias(t *testing.T) {
	path := historyDirectoryFixture(t)
	historyDirectoryRejectsResolvedAlias(t, path, filepath.Join(filepath.Dir(path), "EXACTD~1"))
	name, err := windows.UTF16PtrFromString(path)
	if err != nil {
		t.Fatal(err)
	}
	buffer := make([]uint16, 32768)
	n, err := windows.GetShortPathName(name, &buffer[0], uint32(len(buffer)))
	if errors.Is(err, windows.ERROR_NOT_SUPPORTED) || errors.Is(err, windows.ERROR_INVALID_FUNCTION) {
		t.Log("HOST_CAPABILITY_UNEXERCISED: actual DOS short-name queries unsupported; mandatory exact-path alias rejection ran")
		return
	}
	if err != nil || n == 0 || n >= uint32(len(buffer)) {
		t.Fatal("actual short-name query failed", err)
	}
	alias := windows.UTF16ToString(buffer[:n])
	if alias == path {
		t.Log("HOST_CAPABILITY_UNEXERCISED: actual DOS short-name alias disabled; mandatory exact-path alias rejection ran")
		return
	}
	ops, live, _ := historyTrackedDirectoryIO(t)
	finish, err := financialHistoryWindowsReadDirectory(alias, ops)
	if err == nil {
		_ = finish()
		t.Fatal("actual DOS short-name alias was accepted as canonical")
	}
	if len(live) != 0 {
		t.Fatal("short-name rejection retained a handle")
	}
}
