package main

import (
	"fmt"
	"testing"
)

func TestDagIncrementalOrderRootMatchesExistingOddDuplicateTreeEveryPrefix(t *testing.T) {
	var tree dagOrderAccumulator
	leaves := []DagOrderLeaf{}
	if tree.root() != dagRoot(leaves, dagOrderDomain) {
		t.Fatal("empty root changed")
	}
	for i := 1; i <= DagMaxRecords; i++ {
		leaf := DagOrderLeaf{Hash: hashHex([]byte(fmt.Sprint(i))), Index: i, Producer: i % 6, Sequence: uint64(i), Transactions: i % 50001}
		tree.append(leaf)
		leaves = append(leaves, leaf)
		if tree.root() != dagRoot(leaves, dagOrderDomain) {
			t.Fatal("existing proof root changed at count", i)
		}
	}
	if tree.count != uint64(DagMaxRecords) {
		t.Fatal("leaf count changed")
	}
}

func TestDagOrderRootCloneKeepsSiblingBranchesAndHistoricalRootIndependent(t *testing.T) {
	base, keys := dagFixture(t)
	a, err := applyDagBatch(base, dagBatchWire(t, base, dagWire(t, base, keys, 0, 2)), 0)
	if err != nil {
		t.Fatal(err)
	}
	old := a.Commitment.OrderRoot
	left, err := applyDagBatch(a, dagBatchWire(t, a, dagWire(t, a, keys, 0, 3)), 0)
	if err != nil {
		t.Fatal(err)
	}
	right, err := applyDagBatch(a, dagBatchWire(t, a, dagWire(t, a, keys, 1, 4)), 0)
	if err != nil {
		t.Fatal(err)
	}
	if a.Commitment.OrderRoot != old || a.orderRoot.root() != old || a.orderRoot.count != 1 {
		t.Fatal("ancestor mutated")
	}
	if left.Commitment.OrderRoot == right.Commitment.OrderRoot {
		t.Fatal("two different selected branches share a root")
	}
	for _, execution := range []*DagExecution{base, a, left, right} {
		if execution.Commitment.OrderRoot != dagRoot(orderFixture(t, execution), dagOrderDomain) {
			t.Fatal("root differs from existing full tree")
		}
	}
}
