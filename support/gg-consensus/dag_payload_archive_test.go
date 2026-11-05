//go:build !js

package main

import (
	"bytes"
	"context"
	"encoding/base64"
	"strings"
	"testing"
	"time"

	abci "github.com/cometbft/cometbft/abci/types"
	"github.com/syndtr/goleveldb/leveldb"
)

func assertArchived(t *testing.T, execution *DagExecution) {
	t.Helper()
	if len(execution.pending) != 0 || execution.history.root.node != nil {
		t.Fatal("committed execution retained payload or historical metadata tree")
	}
	if execution.payloadReader == nil {
		t.Fatal("archived execution has no owned reader")
	}
}

func TestDagArchived35000SignedTransactionsReopenAndContinueWithoutNonceOrRootChange(t *testing.T) {
	app, keys, root := dagLedgerFixture(t)
	for i := 0; i < 7; i++ {
		commitPublicFixture(t, app, keys, 0, 5000)
		assertArchived(t, app.dag)
	}
	before := copyState(app.state)
	first := orderFixture(t, app.dag)[0].Hash
	record := recordFixture(t, app.dag, first)
	expected, err := app.store.(*dagStore).db.Get([]byte("r/"+record.WireHash), nil)
	if err != nil || len(expected) != record.WireBytes {
		t.Fatal("missing original raw")
	}
	if app.dag.Commitment.Transactions != 35000 || app.dag.nonces[0] != 35000 {
		t.Fatal("actual TX/nonce total changed")
	}
	app.Close()
	restored, err := newDagEnabledLedger(app.genesis, app.anchor, root, false)
	if err != nil {
		t.Fatal(err)
	}
	defer restored.Close()
	assertArchived(t, restored.dag)
	if !bytes.Equal(canonical(before), canonical(restored.state)) {
		t.Fatal("replay changed certified state or roots")
	}
	var received []byte
	for offset := 0; offset < len(expected); offset += DagPayloadChunkBytes {
		response, chunk := queryPayload(t, restored, before, DagPayloadSelector{Hash: first, Index: 1, Offset: offset})
		raw, err := base64.StdEncoding.Strict().DecodeString(chunk.Data)
		if response.Code != 0 || err != nil || chunk.WireHash != record.WireHash || chunk.Total != len(expected) {
			t.Fatal("archived wire/chunk context changed")
		}
		received = append(received, raw...)
	}
	if !bytes.Equal(received, expected) {
		t.Fatal("historical original signed bytes changed")
	}
	commitPublicFixture(t, restored, keys, 0, 1)
	assertArchived(t, restored.dag)
	if restored.dag.nonces[0] != 35001 {
		t.Fatal("reopened producer reused nonce")
	}
}

func TestDagTwoActual50000TXBlocksCrossNativeCacheByteBoundary(t *testing.T) {
	app, keys, _ := dagLedgerFixture(t)
	store := app.store.(*dagStore)
	for i := 0; i < 2; i++ {
		commitPublicFixture(t, app, keys, 0, 50000)
		assertArchived(t, app.dag)
	}
	for i, leaf := range orderFixture(t, app.dag) {
		record := recordFixture(t, app.dag, leaf.Hash)
		if record.WireBytes <= dagPayloadCacheBytes/2 {
			t.Fatal("actual large fixture did not cross byte boundary")
		}
		response, chunk := queryPayload(t, app, app.state, DagPayloadSelector{Hash: leaf.Hash, Index: i + 1})
		if response.Code != 0 || chunk.Total != record.WireBytes {
			t.Fatal("actual max TX block unavailable")
		}
		if store.payloadCache.bytes > dagPayloadCacheBytes || len(store.payloadCache.entries) != 1 {
			t.Fatal("native cache exceeded byte budget")
		}
	}
	if app.dag.Commitment.Transactions != 100000 {
		t.Fatal("synthetic or missing transactions")
	}
}

func TestDagColdDiskReadThroughActualSDKClientCannotBlockNewCertifiedCommit(t *testing.T) {
	app, keys, _ := dagLedgerFixture(t)
	first := commitPublicFixture(t, app, keys, 0, 2)
	store := app.store.(*dagStore)
	hash := orderFixture(t, app.dag)[0].Hash
	entered, release := make(chan struct{}), make(chan struct{})
	released := false
	defer func() {
		if !released {
			close(release)
		}
	}()
	store.beforePayloadRead = func(string) { close(entered); <-release }
	creator := newLedgerClientCreator(app)
	query, err := creator.NewABCIClient()
	if err != nil {
		t.Fatal(err)
	}
	consensus, err := creator.NewABCIClient()
	if err != nil {
		t.Fatal(err)
	}
	result := make(chan *abci.ResponseQuery, 1)
	go func() {
		response, _ := query.Query(context.Background(), &abci.RequestQuery{Path: "/gg/dag/payload-chunk", Height: first.Height, Data: canonical(DagPayloadSelector{Hash: hash, Index: 1})})
		result <- response
	}()
	select {
	case <-entered:
	case <-time.After(2 * time.Second):
		t.Fatal("cold query did not reach disk reader")
	}
	batch := dagBatchWire(t, app.dag, dagWire(t, app.dag, keys, 1, 3))
	committed := make(chan error, 1)
	go func() {
		_, err := consensus.FinalizeBlock(context.Background(), &abci.RequestFinalizeBlock{Height: 2, Time: time.Unix(1700000003, 0), Txs: [][]byte{batch}})
		if err == nil {
			_, err = consensus.Commit(context.Background(), &abci.RequestCommit{})
		}
		committed <- err
	}()
	select {
	case err := <-committed:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("archive disk reader blocked SDK consensus/store lock")
	}
	close(release)
	released = true
	response := <-result
	var chunk DagPayloadChunk
	if response == nil || response.Code != 0 || decodeStrict(response.Value, &chunk) != nil || chunk.StateRoot != first.StateRoot || chunk.Height != first.Height || app.state.DAG.Transactions != 5 {
		t.Fatal("cold historical pin or concurrent actual committed TX changed")
	}
}

func TestDagColdArchiveRejectsUnselectedMissingChangedAndClosedSources(t *testing.T) {
	for _, kind := range []string{"missing", "changed", "size"} {
		t.Run(kind, func(t *testing.T) {
			app, keys, root := dagLedgerFixture(t)
			state := commitPublicFixture(t, app, keys, 0, 1)
			store := app.store.(*dagStore)
			leaf := orderFixture(t, app.dag)[0]
			record := recordFixture(t, app.dag, leaf.Hash)
			candidate, _ := retentionCandidate(t, app.dag, keys, 7)
			if err := store.prepare(candidate); err != nil {
				t.Fatal(err)
			}
			newest := recordFixture(t, candidate, orderFixture(t, candidate)[candidate.orderCount()-1].Hash)
			if _, err := store.readPayload(context.Background(), newest.WireHash, newest.WireBytes); err == nil {
				t.Fatal("unselected candidate leaked through archive reader")
			}
			batch := new(leveldb.Batch)
			switch kind {
			case "missing":
				batch.Delete([]byte("r/" + record.WireHash))
			case "changed":
				batch.Put([]byte("r/"+record.WireHash), bytes.Repeat([]byte{'X'}, record.WireBytes))
			case "size":
				batch.Put([]byte("r/"+record.WireHash), []byte("wrong-size"))
			}
			if err := store.db.Write(batch, nil); err != nil {
				t.Fatal(err)
			}
			response, _ := queryPayload(t, app, state, DagPayloadSelector{Hash: leaf.Hash, Index: 1})
			if response.Code == 0 {
				t.Fatal("missing or changed durable raw served")
			}
			app.Close()
			if _, err := store.readPayload(context.Background(), record.WireHash, record.WireBytes); err == nil {
				t.Fatal("closed reader succeeded")
			}
			restored, err := newDagEnabledLedger(app.genesis, app.anchor, root, false)
			if err == nil {
				restored.Close()
				t.Fatal("corrupt historical wire bypassed full crypto startup replay")
			}
		})
	}
}

func TestDagArchiveReadersBoundCancellationAndCloseDrainWithoutConsensusLock(t *testing.T) {
	app, keys, _ := dagLedgerFixture(t)
	commitPublicFixture(t, app, keys, 0, 1)
	store := app.store.(*dagStore)
	record := recordFixture(t, app.dag, orderFixture(t, app.dag)[0].Hash)
	entered, release := make(chan struct{}, 2), make(chan struct{})
	released := false
	defer func() {
		if !released {
			close(release)
		}
	}()
	store.beforePayloadRead = func(string) { entered <- struct{}{}; <-release }
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	done := make(chan error, 2)
	for i := 0; i < 2; i++ {
		go func() { _, err := store.readPayload(ctx, record.WireHash, record.WireBytes); done <- err }()
		select {
		case <-entered:
		case <-time.After(2 * time.Second):
			t.Fatal("bounded reader did not enter")
		}
	}
	if _, err := store.readPayload(context.Background(), record.WireHash, record.WireBytes); err == nil || !strings.Contains(err.Error(), "BUSY") {
		t.Fatal("unbounded archive readers")
	}
	closed := make(chan error, 1)
	go func() { closed <- app.Close() }()
	select {
	case <-closed:
		t.Fatal("close did not wait for pinned disk readers")
	case <-time.After(20 * time.Millisecond):
	}
	cancel()
	close(release)
	released = true
	for i := 0; i < 2; i++ {
		select {
		case err := <-done:
			if err == nil {
				t.Fatal("cancelled read published bytes")
			}
		case <-time.After(2 * time.Second):
			t.Fatal("read did not release snapshot")
		}
	}
	select {
	case err := <-closed:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("close deadlocked behind reader")
	}
	if store.payloadCache.bytes != 0 || store.payloadReaders != 0 {
		t.Fatal("close retained cache or reader credits")
	}
}

func TestDagArchiveCannotWeakenIndependentOrderValidationOrDropPreparedData(t *testing.T) {
	app, keys, _ := dagLedgerFixture(t)
	commitPublicFixture(t, app, keys, 0, 1)
	store := app.store.(*dagStore)
	candidate, batch := retentionCandidate(t, app.dag, keys, 9)
	tampered := candidate.clone()
	corruptOrderFixture(t, tampered, 0)
	if err := store.prepare(tampered); err == nil {
		t.Fatal("cached order root bypassed independent full order validation")
	}
	tampered = candidate.clone()
	for index, peak := range tampered.orderRoot.peaks {
		if peak != "" {
			tampered.orderRoot.peaks[index] = strings.Repeat("f", 64)
			break
		}
	}
	if err := store.prepare(tampered); err == nil {
		t.Fatal("changed cached frontier bypassed independent full order validation")
	}
	if _, err := app.FinalizeBlock(context.Background(), &abci.RequestFinalizeBlock{Height: 2, Time: time.Unix(1700000003, 0), Txs: [][]byte{batch}}); err != nil {
		t.Fatal(err)
	}
	newest := recordFixture(t, app.stagedDag, orderFixture(t, candidate)[candidate.orderCount()-1].Hash)
	if newest.Raw == nil || newest.Block.Body.Transactions != nil {
		t.Fatal("prepared raw lost before Sync or decoded TX retained")
	}
	assertArchived(t, app.dag)
	if _, err := app.Commit(context.Background(), &abci.RequestCommit{}); err != nil {
		t.Fatal(err)
	}
	assertArchived(t, app.dag)
}
