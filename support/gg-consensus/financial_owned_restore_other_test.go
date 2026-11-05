//go:build !windows && !js

package main

import "os/exec"

func ownedRestoreTestChildFlags(command *exec.Cmd) {}
