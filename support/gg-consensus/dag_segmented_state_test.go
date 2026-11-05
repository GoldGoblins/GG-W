package main

import (
	"testing"
)

func TestDagSegmentedStatePublicShapeAndExactCutTransaction(t *testing.T) {
	base, keys := segmentedFixture(t)
	first, err := base.apply(segmentedBatch(t, base.active, segmentedWire(t, base.active, keys, 0, 3)), 1700000002000000000)
	if err != nil {
		t.Fatal(err)
	}
	transaction, err := first.cutTransaction()
	if err != nil {
		t.Fatal(err)
	}
	plan, err := first.checkedCutTransaction(canonical(transaction))
	if err != nil {
		t.Fatal(err)
	}
	for _, current := range []*dagSegmentedExecution{base, first, plan.next} {
		state, err := current.state()
		if err != nil || validateSegmentedState(state, current.source, current.anchor) != nil {
			t.Fatal("real derived state rejected", err)
		}
	}
	for _, field := range []string{"before", "cut", "epoch", "schema"} {
		bad := transaction
		switch field {
		case "before":
			bad.Before = DagZero
		case "cut":
			bad.Cut = DagZero
		case "epoch":
			bad.Epoch++
		case "schema":
			bad.Schema += ".unknown"
		}
		if _, err := first.checkedCutTransaction(canonical(bad)); err == nil {
			t.Fatal("modified canonical cut accepted", field)
		}
	}
	if _, err := plan.next.checkedCutTransaction(canonical(transaction)); err == nil {
		t.Fatal("spent cut replay accepted in next epoch")
	}
	if _, err := first.checkedCutTransaction(append(canonical(transaction), '\n')); err == nil {
		t.Fatal("noncanonical cut accepted")
	}
}

func TestDagSegmentedStateRejectsInconsistentPublicCountersAndAuthors(t *testing.T) {
	base, keys := segmentedFixture(t)
	first, err := base.apply(segmentedBatch(t, base.active, segmentedWire(t, base.active, keys, 0, 1)), 1700000002000000000)
	if err != nil {
		t.Fatal(err)
	}
	state, _ := first.state()
	mutations := map[string]func(*dagSegmentedState){
		"source":           func(s *dagSegmentedState) { s.SourceHash = DagZero },
		"anchor":           func(s *dagSegmentedState) { s.Anchor = DagZero },
		"epoch":            func(s *dagSegmentedState) { s.Epoch = 0 },
		"counter_overflow": func(s *dagSegmentedState) { s.Blocks = ^uint64(0) },
		"transactions":     func(s *dagSegmentedState) { s.Transactions++ },
		"sequence":         func(s *dagSegmentedState) { s.Authors[0].Sequence = "0" },
		"nonce":            func(s *dagSegmentedState) { s.Authors[0].Nonce = "01" },
		"owner":            func(s *dagSegmentedState) { s.Authors[0].Key = s.Authors[1].Key },
		"uncreated_head":   func(s *dagSegmentedState) { s.Authors[1].Head = DagZero },
		"rank":             func(s *dagSegmentedState) { s.LastRank = 2 },
		"active_count":     func(s *dagSegmentedState) { s.Active.Blocks = 0 },
		"chain":            func(s *dagSegmentedState) { s.Active.ChainID += "a" },
		"closed_root":      func(s *dagSegmentedState) { s.ClosedRoot = DagZero },
	}
	for name, mutate := range mutations {
		t.Run(name, func(t *testing.T) {
			bad := state
			mutate(&bad)
			if validateSegmentedState(bad, first.source, first.anchor) == nil {
				t.Fatal("inconsistent public state accepted")
			}
		})
	}
}
