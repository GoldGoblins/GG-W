//go:build !js

package main

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"sync"
	"testing"
	"time"

	abci "github.com/cometbft/cometbft/abci/types"
)

func queryPayload(t *testing.T, app *Ledger, state State, selector DagPayloadSelector) (*abci.ResponseQuery, DagPayloadChunk) {
	t.Helper()
	response, err := app.Query(context.Background(), &abci.RequestQuery{Path: "/gg/dag/payload-chunk", Height: state.Height, Data: canonical(selector)})
	if err != nil {
		t.Fatal(err)
	}
	var chunk DagPayloadChunk
	if response.Code == 0 && (decodeStrict(response.Value, &chunk) != nil || len(response.Value) > 65536) {
		t.Fatal("unbounded or malformed chunk")
	}
	return response, chunk
}

func TestDagPayloadChunksReturnActualCommitted5000TXWireAndRecoverAfterRestart(t *testing.T) {
	app, keys, root := dagLedgerFixture(t)
	state := commitPublicFixture(t, app, keys, 0, 5000)
	hash := orderFixture(t, app.dag)[0].Hash
	record := recordFixture(t, app.dag, hash)
	expected, err := app.store.(*dagStore).readPayload(context.Background(), record.WireHash, record.WireBytes)
	if err != nil {
		t.Fatal(err)
	}
	wireHash := recordFixture(t, app.dag, hash).WireHash
	var received []byte
	for offset := 0; offset < len(expected); offset += DagPayloadChunkBytes {
		response, chunk := queryPayload(t, app, state, DagPayloadSelector{Hash: hash, Index: 1, Offset: offset})
		if response.Code != 0 || chunk.Schema != "gg.dag.payload-chunk.v1" || chunk.Hash != hash || chunk.Index != 1 || chunk.Offset != offset ||
			chunk.Total != len(expected) || chunk.WireHash != wireHash || chunk.GenesisHash != state.GenesisHash || chunk.Height != state.Height || chunk.StateRoot != state.StateRoot {
			t.Fatal("chunk context changed")
		}
		data, err := base64.StdEncoding.Strict().DecodeString(chunk.Data)
		if err != nil || len(data) > DagPayloadChunkBytes {
			t.Fatal("invalid chunk data")
		}
		received = append(received, data...)
	}
	if !bytes.Equal(received, expected) || hashHex(received) != wireHash {
		t.Fatal("actual signed bytes did not roundtrip")
	}
	app.Close()
	restored, err := newDagEnabledLedger(app.genesis, app.anchor, root, false)
	if err != nil {
		t.Fatal(err)
	}
	defer restored.Close()
	response, chunk := queryPayload(t, restored, state, DagPayloadSelector{Hash: hash, Index: 1})
	if response.Code != 0 || chunk.WireHash != wireHash {
		t.Fatal("replayed payload not available")
	}
}

func TestDagPayloadQueryCannotExposePreparedOrFutureSelectedData(t *testing.T) {
	app, keys, _ := dagLedgerFixture(t)
	old := copyState(app.state)
	candidate, batch := retentionCandidate(t, app.dag, keys, 1)
	selector := DagPayloadSelector{Hash: orderFixture(t, candidate)[0].Hash, Index: 1}
	if err := app.store.prepare(candidate); err != nil {
		t.Fatal(err)
	}
	response, _ := queryPayload(t, app, old, selector)
	if response.Code == 0 {
		t.Fatal("prepared payload exposed as committed")
	}
	if _, err := app.FinalizeBlock(context.Background(), &abci.RequestFinalizeBlock{Height: 1, Time: time.Unix(1700000002, 0), Txs: [][]byte{batch}}); err != nil {
		t.Fatal(err)
	}
	response, _ = queryPayload(t, app, old, selector)
	if response.Code == 0 {
		t.Fatal("staged payload exposed before Commit")
	}
	if _, err := app.Commit(context.Background(), &abci.RequestCommit{}); err != nil {
		t.Fatal(err)
	}
	response, _ = queryPayload(t, app, old, selector)
	// Height zero means current in ABCI. Pin the actual first committed height
	// before appending a second block, then try its future index under that pin.
	first := copyState(app.state)
	commitPublicFixture(t, app, keys, 1, 1)
	response, _ = queryPayload(t, app, first, DagPayloadSelector{Hash: orderFixture(t, app.dag)[1].Hash, Index: 2})
	if response.Code == 0 {
		t.Fatal("historical pin exposed a future selected leaf")
	}
	response, _ = queryPayload(t, app, first, selector)
	if response.Code != 0 {
		t.Fatal("older selected payload disappeared")
	}
}

func TestDagPayloadSelectorsCancellationAndReaderSlotsAreBounded(t *testing.T) {
	app, keys, _ := dagLedgerFixture(t)
	state := commitPublicFixture(t, app, keys, 0, 1)
	hash := orderFixture(t, app.dag)[0].Hash
	base := DagPayloadSelector{Hash: hash, Index: 1}
	for _, data := range [][]byte{[]byte(`{}`), []byte(`{"hash":"x","index":1,"offset":0}`),
		canonical(DagPayloadSelector{Hash: hash, Index: 0}), canonical(DagPayloadSelector{Hash: hash, Index: 2}),
		canonical(DagPayloadSelector{Hash: hash, Index: 1, Offset: -1}), canonical(DagPayloadSelector{Hash: hash, Index: 1, Offset: 1}),
		canonical(DagPayloadSelector{Hash: hash, Index: 1, Offset: DagMaxWire}), append(canonical(base), ' ')} {
		response, err := app.Query(context.Background(), &abci.RequestQuery{Path: "/gg/dag/payload-chunk", Height: state.Height, Data: data})
		if err != nil || response.Code == 0 {
			t.Fatal("invalid bounded selector accepted", string(data), err)
		}
	}
	app.payloadSlots <- struct{}{}
	app.payloadSlots <- struct{}{}
	response, _ := queryPayload(t, app, state, base)
	if response.Code == 0 || response.Log != "GG_DAG_PAYLOAD_BUSY" {
		t.Fatal("payload reader slots unbounded")
	}
	<-app.payloadSlots
	<-app.payloadSlots
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	response, err := app.Query(ctx, &abci.RequestQuery{Path: "/gg/dag/payload-chunk", Height: state.Height, Data: canonical(base)})
	if err != nil || response.Code == 0 {
		t.Fatal("cancelled payload read succeeded")
	}
	// Owned memory corruption must not return a first chunk with a stale wire
	// digest. This never changes production data or a filesystem fixture.
	record := recordFixture(t, app.dag, hash)
	raw, err := app.store.(*dagStore).readPayload(context.Background(), record.WireHash, record.WireBytes)
	if err != nil {
		t.Fatal(err)
	}
	record.Raw = append([]byte(nil), raw...)
	record.Raw[0] ^= 1
	app.dag.pending[hash] = record
	response, _ = queryPayload(t, app, state, base)
	if response.Code == 0 {
		t.Fatal("changed committed bytes were served")
	}
}

type pausedPayloadContext struct {
	context.Context
	mu      sync.Mutex
	calls   int
	entered chan struct{}
	release chan struct{}
}

func (ctx *pausedPayloadContext) Err() error {
	ctx.mu.Lock()
	ctx.calls++
	pause := ctx.calls == 2
	ctx.mu.Unlock()
	if pause {
		close(ctx.entered)
		<-ctx.release
	}
	return nil
}

func TestDagPayloadReadDoesNotHoldConsensusLockAndKeepsItsHistoricalPin(t *testing.T) {
	app, keys, _ := dagLedgerFixture(t)
	first := commitPublicFixture(t, app, keys, 0, 1)
	hash := orderFixture(t, app.dag)[0].Hash
	ctx := &pausedPayloadContext{Context: context.Background(), entered: make(chan struct{}), release: make(chan struct{})}
	done := make(chan *abci.ResponseQuery, 1)
	go func() {
		response, _ := app.Query(ctx, &abci.RequestQuery{Path: "/gg/dag/payload-chunk", Height: first.Height, Data: canonical(DagPayloadSelector{Hash: hash, Index: 1})})
		done <- response
	}()
	select {
	case <-ctx.entered:
	case <-time.After(time.Second):
		close(ctx.release)
		t.Fatal("payload query did not reach isolated read")
	}
	committed := make(chan struct{})
	go func() { commitPublicFixture(t, app, keys, 1, 1); close(committed) }()
	select {
	case <-committed:
	case <-time.After(time.Second):
		close(ctx.release)
		t.Fatal("payload query held consensus lock")
	}
	close(ctx.release)
	response := <-done
	var chunk DagPayloadChunk
	if response.Code != 0 || json.Unmarshal(response.Value, &chunk) != nil || chunk.StateRoot != first.StateRoot || chunk.Height != first.Height {
		t.Fatal("payload read lost its pinned state")
	}
}
