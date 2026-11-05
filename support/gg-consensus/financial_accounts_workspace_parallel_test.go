//go:build !js

package main

import (
	"bytes"
	"context"
	"errors"
	"runtime"
	"strconv"
	"testing"
)

func TestAccountWorkspaceParallelPublicationIsExactAndFailureAtomic(t *testing.T) {
	ctx := context.Background()
	base, err := newFinancialAccountTree(financialAccountTestRules())
	if err != nil {
		t.Fatal(err)
	}
	work, err := newFinancialAccountWorkspace(base, financialAccountWorkspaceBytes)
	if err != nil {
		t.Fatal(err)
	}
	reference := base
	for index := 0; index < 1025; index++ {
		account := Account{Address: financialAccountTestAddress(1600000 + index), Balance: strconv.Itoa(1000 + index), Nonce: uint64(index)}
		if err = work.set(ctx, account); err != nil {
			t.Fatal(err)
		}
		reference, err = reference.set(ctx, account)
		if err != nil {
			t.Fatal(err)
		}
	}
	old := runtime.GOMAXPROCS(1)
	defer runtime.GOMAXPROCS(old)
	serial, err := work.freeze(ctx)
	if err != nil {
		t.Fatal(err)
	}
	runtime.GOMAXPROCS(2)
	parallel, err := work.freeze(ctx)
	if err != nil {
		t.Fatal(err)
	}
	compareWorkspaceTrees(t, serial, reference)
	compareWorkspaceTrees(t, parallel, reference)
	retained := workspaceNodeBytes(t, parallel)
	late := &workspaceCancelContext{Context: ctx, remaining: 40}
	rejected, err := work.freeze(late)
	if !errors.Is(err, context.Canceled) || rejected.root.link != base.root.link {
		t.Fatal("parallel cancellation published a partial tree", err)
	}
	actual := workspaceNodeBytes(t, parallel)
	for hash, raw := range retained {
		if !bytes.Equal(actual[hash], raw) {
			t.Fatal("parallel cancellation changed a retained immutable node")
		}
	}
	if work.root.owned == nil || work.root.owned.left.owned == nil || work.root.owned.right.owned == nil {
		t.Fatal("fixture did not build two independently publishable branches")
	}
	owner := work.root.owned.left.owned.owner
	work.root.owned.left.owned.owner = nil
	rejected, err = work.freeze(ctx)
	work.root.owned.left.owned.owner = owner
	if err == nil || rejected.root.link != base.root.link {
		t.Fatal("parallel corruption published a partial tree")
	}
	final, err := work.freeze(ctx)
	if err != nil {
		t.Fatal(err)
	}
	compareWorkspaceTrees(t, final, reference)
}
