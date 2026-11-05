//go:build windows

package main

import (
	"os/exec"
	"syscall"
)

func ownedRestoreTestChildFlags(command *exec.Cmd) {
	// Direct gated test binary; no console host or breakaway child.
	command.SysProcAttr = &syscall.SysProcAttr{CreationFlags: 0x8}
}
