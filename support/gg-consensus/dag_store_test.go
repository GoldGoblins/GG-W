package main

import (
	"bytes"
	"errors"
	"path/filepath"
	"testing"

	"github.com/syndtr/goleveldb/leveldb"
)

func dagStoreFixture(t *testing.T) (*DagExecution, *dagStore, string) {
	t.Helper()
	base, _ := dagFixture(t)
	root := t.TempDir()
	store, err := newDagStore(base.Source, base.Anchor, root, true)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = store.close() })
	if err = store.prepare(base); err != nil {
		t.Fatal(err)
	}
	return base, store, root
}

func TestDagStoreSyncPayloadPrecedesSelectionAndRecoveryRevalidatesExecution(t *testing.T) {
	base, store, root := dagStoreFixture(t)
	_, keys := dagFixture(t)
	next, err := applyDagBatch(base, dagBatchWire(t, base, dagWire(t, base, keys, 0, 3)), 1700000002000000000)
	if err != nil {
		t.Fatal(err)
	}
	if err = store.prepare(next); err != nil {
		t.Fatal(err)
	}
	// This is a public storage-container fixture, not a consensus certificate.
	history := canonical(map[string]any{"public_container_fixture": true, "selected": base.Commitment})
	if err = store.commit(history); err != nil {
		t.Fatal(err)
	}
	_ = store.close()
	opened, err := newDagStore(base.Source, base.Anchor, root, false)
	if err != nil {
		t.Fatal(err)
	}
	defer opened.close()
	actual, err := opened.history()
	if err != nil || !bytes.Equal(actual, history) {
		t.Fatal("prepared data silently selected a canonical state")
	}
	restored, err := opened.load(next.Commitment)
	if err != nil || !bytes.Equal(canonical(restored.Accounts), canonical(next.Accounts)) {
		t.Fatal("durable execution did not replay", err)
	}
}

func TestDagStoreRejectsMempoolOnlyStateBeforeAnyPayloadAcknowledgement(t *testing.T) {
	base, store, _ := dagStoreFixture(t)
	_, keys := dagFixture(t)
	preview, err := applyDagBatch(base, dagBatchWire(t, base, dagWire(t, base, keys, 0, 1)), 0)
	if err != nil {
		t.Fatal(err)
	}
	before := store.meta
	if store.prepare(preview) == nil || store.meta != before {
		t.Fatal("uncertifiable mempool state was acknowledged")
	}
}

func TestDagStoreExclusiveOwnerMissingDatabaseAndAccidentalRecreationFailClosed(t *testing.T) {
	base, store, root := dagStoreFixture(t)
	if second, err := newDagStore(base.Source, base.Anchor, root, false); err == nil {
		second.close()
		t.Fatal("second owner opened the same database")
	}
	if second, err := newDagStore(base.Source, base.Anchor, root, true); err == nil {
		second.close()
		t.Fatal("existing database was recreated")
	}
	if second, err := newDagStore(base.Source, base.Anchor, filepath.Join(root, "missing"), false); err == nil {
		second.close()
		t.Fatal("missing recovery database was initialized")
	}
	_ = store.close()
	opened, err := newDagStore(base.Source, base.Anchor, root, false)
	if err != nil {
		t.Fatal(err)
	}
	opened.close()
}

func TestDagStoreWriteFailureStopsAcknowledgementsAndDoesNotInventCommittedHistory(t *testing.T) {
	for _, after := range []bool{false, true} {
		t.Run(map[bool]string{false: "before_sync", true: "after_sync_lost_return"}[after], func(t *testing.T) {
			base, store, root := dagStoreFixture(t)
			_, keys := dagFixture(t)
			next, err := applyDagBatch(base, dagBatchWire(t, base, dagWire(t, base, keys, 0, 2)), 1700000002000000000)
			if err != nil {
				t.Fatal(err)
			}
			selected := canonical(map[string]any{"selected": base.Commitment})
			if err = store.commit(selected); err != nil {
				t.Fatal(err)
			}
			write := store.write
			store.write = func(batch *leveldb.Batch) error {
				if after {
					if err := write(batch); err != nil {
						return err
					}
				}
				return errors.New("owned injected failure")
			}
			if store.prepare(next) == nil || !store.failed || store.prepare(base) == nil {
				t.Fatal("failed storage continued acknowledging payloads")
			}
			store.close()
			opened, err := newDagStore(base.Source, base.Anchor, root, false)
			if err != nil {
				t.Fatal(err)
			}
			defer opened.close()
			history, err := opened.history()
			if err != nil || !bytes.Equal(history, selected) {
				t.Fatal("uncommitted candidate changed selected history")
			}
			_, err = opened.load(next.Commitment)
			if after && err != nil || !after && err == nil {
				t.Fatal("unknown write outcome did not recover exact durable prefix")
			}
		})
	}
}

func TestDagStoreMissingOrChangedPayloadIsNeverSilentlyRepaired(t *testing.T) {
	for _, changed := range []bool{false, true} {
		t.Run(map[bool]string{false: "missing", true: "changed"}[changed], func(t *testing.T) {
			base, store, root := dagStoreFixture(t)
			_, keys := dagFixture(t)
			next, err := applyDagBatch(base, dagBatchWire(t, base, dagWire(t, base, keys, 0, 1)), 1700000002000000000)
			if err != nil {
				t.Fatal(err)
			}
			if err = store.prepare(next); err != nil {
				t.Fatal(err)
			}
			key := []byte("r/" + next.Manifest.Blocks[0])
			if changed {
				_ = store.db.Put(key, []byte("changed public payload"), nil)
			} else {
				_ = store.db.Delete(key, nil)
			}
			if _, err = store.load(next.Commitment); err == nil {
				t.Fatal("missing/changed payload accepted")
			}
			store.close()
			if reopened, err := newDagStore(base.Source, base.Anchor, root, false); err == nil {
				reopened.close()
				t.Fatal("altered journal was repaired or accepted")
			}
		})
	}
}
