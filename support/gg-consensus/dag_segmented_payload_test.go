//go:build !js

package main

import (
	"bytes"
	"context"
	"encoding/base64"
	"testing"
	"time"

	abci "github.com/cometbft/cometbft/abci/types"
)

func TestDagSegmentedPayloadActual5000TXChunksAndRestart(t *testing.T) {
	app, backend, keys, root := segmentedSDKFixture(t)
	wire := segmentedWire(t, backend.current.active, keys, 0, 5000)
	commitSegmentedSDK(t, app, segmentedBatch(t, backend.current.active, wire))
	state := copyState(app.state)
	order, _ := backend.current.active.orderList()
	leaf := order[0]
	var recovered []byte
	for offset := 0; offset < len(wire); offset += DagPayloadChunkBytes {
		response, chunk := queryPayload(t, app, state, DagPayloadSelector{Hash: leaf.Hash, Index: 1, Offset: offset})
		if response.Code != 0 || chunk.Hash != leaf.Hash || chunk.Index != 1 || chunk.Height != state.Height ||
			chunk.GenesisHash != app.anchor || chunk.StateRoot != state.StateRoot || chunk.Offset != offset ||
			chunk.Total != len(wire) || chunk.WireHash != hashHex(wire) {
			t.Fatal("selected chunk context", response)
		}
		part, err := base64.StdEncoding.DecodeString(chunk.Data)
		if err != nil || len(part) != min(DagPayloadChunkBytes, len(wire)-offset) {
			t.Fatal("chunk bound")
		}
		recovered = append(recovered, part...)
	}
	if !bytes.Equal(recovered, wire) {
		t.Fatal("original signed bytes changed")
	}
	packet := segmentedProofPacket(t, app, state, leaf.Hash, 0)
	if _, err := verifyInput(packet); err != nil || packet.DAGSegmentedBlockProof.Leaf.Hash != leaf.Hash {
		t.Fatal("original lacks SDK membership", err)
	}
	if err := app.Close(); err != nil {
		t.Fatal(err)
	}
	restored, err := newDagEnabledLedger(app.genesis, app.anchor, root, false)
	if err != nil {
		t.Fatal(err)
	}
	defer restored.Close()
	response, chunk := queryPayload(t, restored, state, DagPayloadSelector{Hash: leaf.Hash, Index: 1})
	if response.Code != 0 || chunk.WireHash != hashHex(wire) {
		t.Fatal("replayed original unavailable")
	}
}

func TestDagSegmentedPayloadNeverPublishesStagedOrRetiredOriginal(t *testing.T) {
	app, backend, keys, _ := segmentedSDKFixture(t)
	wire := segmentedWire(t, backend.current.active, keys, 0, 1)
	batch := segmentedBatch(t, backend.current.active, wire)
	record, err := decodeDagBlockContext(wire, backend.current.active.Source, 0, backend.current.active.segmentPrecheck, dagSegmentCounterMax, int64(dagSegmentCounterMax))
	if err != nil {
		t.Fatal(err)
	}
	processed, err := app.ProcessProposal(context.Background(), &abci.RequestProcessProposal{Txs: [][]byte{batch}, Time: time.Unix(1700000002, 0)})
	if err != nil || processed.Status != abci.ResponseProcessProposal_ACCEPT {
		t.Fatal("staging", err)
	}
	selector := DagPayloadSelector{Hash: record.Hash, Index: 1}
	response, _ := queryPayload(t, app, app.state, selector)
	if response.Code == 0 {
		t.Fatal("proposal-ready bytes claimed selected")
	}
	commitSegmentedSDK(t, app, batch)
	before := copyState(app.state)
	cut, err := backend.current.cutTransaction()
	if err != nil {
		t.Fatal(err)
	}
	commitSegmentedSDK(t, app, canonical(cut))
	response, _ = queryPayload(t, app, before, selector)
	if response.Code == 0 || backend.store.health() != nil {
		t.Fatal("retired active payload must be unavailable without poisoning healthy archive")
	}
}

func TestDagSegmentedPayloadRejectsSelectorContextCancellationAndCorruption(t *testing.T) {
	app, backend, keys, _ := segmentedSDKFixture(t)
	wire := segmentedWire(t, backend.current.active, keys, 0, 2)
	commitSegmentedSDK(t, app, segmentedBatch(t, backend.current.active, wire))
	order, _ := backend.current.active.orderList()
	base := DagPayloadSelector{Hash: order[0].Hash, Index: 1}
	for name, selector := range map[string]DagPayloadSelector{
		"unknown_hash": {Hash: DagZero, Index: 1}, "zero_index": {Hash: base.Hash}, "wrong_index": {Hash: base.Hash, Index: 2},
		"unaligned_offset": {Hash: base.Hash, Index: 1, Offset: 1}, "negative_offset": {Hash: base.Hash, Index: 1, Offset: -1},
		"past_end": {Hash: base.Hash, Index: 1, Offset: DagMaxWire},
	} {
		t.Run(name, func(t *testing.T) {
			response, _ := queryPayload(t, app, app.state, selector)
			if response.Code == 0 {
				t.Fatal("bad selector accepted")
			}
		})
	}
	for _, raw := range []string{"{\"hash\":\"" + base.Hash + "\",\"index\":true,\"offset\":0}", string(canonical(base)) + " ", "{\"verified\":true}"} {
		response, _ := app.Query(context.Background(), &abci.RequestQuery{Path: "/gg/dag/payload-chunk", Height: app.state.Height, Data: []byte(raw)})
		if response.Code == 0 {
			t.Fatal("noncanonical selector accepted")
		}
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := backend.store.publicPayload(ctx, app.state, base); err == nil {
		t.Fatal("cancelled read")
	}
	wrong := copyState(app.state)
	wrong.DAGSegmented.Active.OrderRoot = DagZero
	if _, err := backend.store.publicPayload(context.Background(), wrong, base); err == nil {
		t.Fatal("unretained view")
	}
	backend.store.payloadSlots <- struct{}{}
	backend.store.payloadSlots <- struct{}{}
	if _, err := backend.store.publicPayload(context.Background(), app.state, base); err == nil || err.Error() != "GG_DAG_PAYLOAD_BUSY" {
		t.Fatal("unbounded readers", err)
	}
	<-backend.store.payloadSlots
	<-backend.store.payloadSlots
	if err := backend.store.db.Put([]byte("r/"+hashHex(wire)), []byte("corrupt selected original"), nil); err != nil {
		t.Fatal(err)
	}
	if _, err := backend.store.publicPayload(context.Background(), app.state, base); err == nil || backend.store.health() == nil {
		t.Fatal("selected corruption did not fail closed")
	}
}

func TestDagSegmentedPayloadPinnedSnapshotSurvivesCutWithoutConsensusLock(t *testing.T) {
	app, backend, keys, _ := segmentedSDKFixture(t)
	wire := segmentedWire(t, backend.current.active, keys, 0, 1)
	commitSegmentedSDK(t, app, segmentedBatch(t, backend.current.active, wire))
	before := copyState(app.state)
	order, _ := backend.current.active.orderList()
	selector := DagPayloadSelector{Hash: order[0].Hash, Index: 1}
	entered, release := make(chan struct{}), make(chan struct{})
	backend.store.beforePayloadRead = func() { close(entered); <-release }
	done := make(chan error, 1)
	go func() {
		chunk, err := backend.store.publicPayload(context.Background(), before, selector)
		if err == nil && chunk.WireHash != hashHex(wire) {
			t.Error("changed pinned original")
		}
		done <- err
	}()
	select {
	case <-entered:
	case <-time.After(2 * time.Second):
		t.Fatal("reader not isolated")
	}
	committed := make(chan struct{})
	go func() {
		cut, _ := backend.current.cutTransaction()
		commitSegmentedSDK(t, app, canonical(cut))
		close(committed)
	}()
	select {
	case <-committed:
	case <-time.After(2 * time.Second):
		close(release)
		t.Fatal("payload query held consensus/store lock")
	}
	close(release)
	if err := <-done; err != nil {
		t.Fatal("pinned pre-cut bytes lost", err)
	}
}

func TestDagSegmentedPayloadCloseWaitsForOwnedSnapshotAndRejectsNewReaders(t *testing.T) {
	app, backend, keys, _ := segmentedSDKFixture(t)
	wire := segmentedWire(t, backend.current.active, keys, 0, 1)
	commitSegmentedSDK(t, app, segmentedBatch(t, backend.current.active, wire))
	state := copyState(app.state)
	order, _ := backend.current.active.orderList()
	selector := DagPayloadSelector{Hash: order[0].Hash, Index: 1}
	entered, release := make(chan struct{}), make(chan struct{})
	backend.store.beforePayloadRead = func() { close(entered); <-release }
	read := make(chan error, 1)
	go func() { _, err := backend.store.publicPayload(context.Background(), state, selector); read <- err }()
	<-entered
	closed := make(chan error, 1)
	go func() { closed <- backend.store.close() }()
	deadline := time.Now().Add(2 * time.Second)
	for {
		backend.store.mu.Lock()
		stopped := backend.store.db == nil
		backend.store.mu.Unlock()
		if stopped {
			break
		}
		if time.Now().After(deadline) {
			close(release)
			t.Fatal("close did not stop ingress")
		}
		time.Sleep(time.Millisecond)
	}
	select {
	case <-closed:
		close(release)
		t.Fatal("closed DB before reader release")
	default:
	}
	if _, err := backend.store.publicPayload(context.Background(), state, selector); err == nil {
		t.Fatal("new reader entered closing store")
	}
	close(release)
	if err := <-read; err != nil {
		t.Fatal(err)
	}
	if err := <-closed; err != nil {
		t.Fatal(err)
	}
	if backend.store.payloadCache.bytes != 0 {
		t.Fatal("closed payload cache retained")
	}
}
