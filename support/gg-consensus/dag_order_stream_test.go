//go:build !js

package main

import (
	"fmt"
	"runtime"
	"testing"
)

func streamOrderFixture(t *testing.T, count int) (*DagExecution, []DagOrderLeaf) {
	t.Helper()
	execution := &DagExecution{}
	leaves := make([]DagOrderLeaf, count)
	for i := range leaves {
		leaves[i] = DagOrderLeaf{Hash: fmt.Sprintf("%064x", i+1), Index: i + 1, Producer: i % 6, Sequence: uint64(i/6 + 1), Transactions: i % 7}
		leaf := leaves[i]
		var err error
		execution.history, err = execution.history.put(historyOrderKey(leaf.Index), dagHistoryValue{Order: &leaf})
		if err != nil {
			t.Fatal(err)
		}
		execution.orderRoot.append(leaf)
	}
	return execution, leaves
}

// Independent former proposal path: materialize all leaves, then construct all
// levels of the original odd-duplicate Merkle tree. No new traversal is used.
func previousCompleteOrderRoot(execution *DagExecution) (string, error) {
	order := make([]DagOrderLeaf, 0, execution.orderCount())
	err := execution.history.walk(execution.history.root, "o/", "p/", func(body dagHistoryBody) error {
		if body.Value.Order == nil || body.Value.Order.Index != len(order)+1 {
			return errDagHistoryUnavailable
		}
		order = append(order, *body.Value.Order)
		return nil
	}, 0)
	if err != nil || len(order) != execution.orderCount() {
		return "", errDagHistoryUnavailable
	}
	return dagRoot(order, dagOrderDomain), nil
}

func TestDagStreamingOrderMatchesIndependentCompleteTreeAndEverySmallPrefix(t *testing.T) {
	execution, leaves := streamOrderFixture(t, DagMaxRecords)
	before := execution.history.root.id()
	counts := []int{255, 256, 257, 1023, 1024, 1025, 2047, 2048, 2049, 4094, 4095}
	for count := 0; count <= 129; count++ {
		counts = append(counts, count)
	}
	for _, count := range counts {
		root, err := execution.orderPrefixRoot(count)
		if err != nil || root != dagRoot(leaves[:count], dagOrderDomain) {
			t.Fatalf("prefix %d: %v", count, err)
		}
	}
	old, err := previousCompleteOrderRoot(execution)
	if err != nil || old != execution.orderRoot.root() || execution.history.root.id() != before {
		t.Fatal("changed root/history")
	}
	for _, count := range []int{-1, DagMaxRecords + 1} {
		if root, err := execution.orderPrefixRoot(count); err == nil || root != "" {
			t.Fatal("accepted invalid prefix")
		}
	}
	view := &DagExecution{proofOrder: append([]DagOrderLeaf{}, leaves...)}
	if root, err := view.orderPrefixRoot(len(leaves)); err != nil || root != old {
		t.Fatal("changed read-only proof semantics")
	}
}

func TestDagStreamingOrderRejectsMissingExtraReindexedAndUnauthenticatedLeaves(t *testing.T) {
	for _, mode := range []string{"missing", "extra", "wrong-index", "wrong-key", "missing-disk-node", "changed-disk-node"} {
		t.Run(mode, func(t *testing.T) {
			execution, leaves := streamOrderFixture(t, 33)
			if mode == "missing-disk-node" || mode == "changed-disk-node" {
				nodes := map[string]dagHistoryBody{}
				if err := execution.history.newNodes(map[string]bool{}, func(id string, body dagHistoryBody) error { nodes[id] = body; return nil }); err != nil {
					t.Fatal(err)
				}
				root := execution.history.root.id()
				if mode == "missing-disk-node" {
					delete(nodes, root)
				} else {
					body := nodes[root]
					body.Value.Order.Transactions++
					nodes[root] = body
				}
				execution.history = dagHistory{root: dagHistoryRef{hash: root}, read: func(id string) (dagHistoryBody, error) { return nodes[id], nil }}
			} else {
				tree := dagHistory{}
				if mode == "extra" {
					leaves = append(leaves, DagOrderLeaf{Hash: fmt.Sprintf("%064x", 34), Index: 34, Producer: 0, Sequence: 7})
				}
				for i, leaf := range leaves {
					if mode == "missing" && i == 15 {
						continue
					}
					key := historyOrderKey(leaf.Index)
					if mode == "wrong-index" && i == 15 {
						leaf.Index++
					}
					if mode == "wrong-key" && i == 15 {
						key = "o/00000016x"
					}
					copy := leaf
					var err error
					tree, err = tree.put(key, dagHistoryValue{Order: &copy})
					if err != nil {
						t.Fatal(err)
					}
				}
				execution.history = tree
			}
			if root, err := execution.orderPrefixRoot(33); err == nil || root != "" {
				t.Fatal("malformed history returned an authenticated root")
			}
		})
	}
	execution, _ := streamOrderFixture(t, 33)
	marker := fmt.Errorf("owned callback stopped")
	visited := 0
	err := execution.visitOrderPrefix(33, func(DagOrderLeaf) error { visited++; return marker })
	if err != marker || visited != 1 {
		t.Fatal("ignored caller stop")
	}
}

func TestDagStreamingOrderAvoidsCompleteLeafSliceAndMerkleLevels(t *testing.T) {
	execution, _ := streamOrderFixture(t, DagMaxRecords)
	expected := execution.orderRoot.root()
	measure := func(stream bool) uint64 {
		runtime.GC()
		var before, after runtime.MemStats
		runtime.ReadMemStats(&before)
		var root string
		var err error
		if stream {
			root, err = execution.orderPrefixRoot(execution.orderCount())
		} else {
			root, err = previousCompleteOrderRoot(execution)
		}
		runtime.ReadMemStats(&after)
		if err != nil || root != expected {
			t.Fatal("allocation sample changed validation")
		}
		return after.TotalAlloc - before.TotalAlloc
	}
	// Warm both paths before their measured runs.
	measure(false)
	measure(true)
	previous, current := measure(false), measure(true)
	t.Logf("GG_DAG_ORDER_ALLOCATION baseline=%d candidate=%d leaves=%d", previous, current, DagMaxRecords)
	if current >= previous {
		t.Fatal("streaming proposal validation retained the full-list/tree allocation")
	}
}
