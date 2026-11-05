//go:build !js

package main

import (
	"context"
	"testing"
	"time"

	abci "github.com/cometbft/cometbft/abci/types"
)

func TestDagSDKLocalQueryClientCannotHoldConsensusBehindPayloadRead(t *testing.T) {
	app, keys, _ := dagLedgerFixture(t)
	first := commitPublicFixture(t, app, keys, 0, 1)
	hash := orderFixture(t, app.dag)[0].Hash
	creator := newLedgerClientCreator(app)
	query, err := creator.NewABCIClient()
	if err != nil {
		t.Fatal(err)
	}
	consensus, err := creator.NewABCIClient()
	if err != nil {
		t.Fatal(err)
	}
	ctx := &pausedPayloadContext{Context: context.Background(), entered: make(chan struct{}), release: make(chan struct{})}
	done := make(chan *abci.ResponseQuery, 1)
	go func() {
		response, _ := query.Query(ctx, &abci.RequestQuery{Path: "/gg/dag/payload-chunk", Height: first.Height, Data: canonical(DagPayloadSelector{Hash: hash, Index: 1})})
		done <- response
	}()
	select {
	case <-ctx.entered:
	case <-time.After(time.Second):
		close(ctx.release)
		t.Fatal("SDK query did not reach isolated read")
	}
	committed := make(chan error, 1)
	go func() {
		_, err := consensus.FinalizeBlock(context.Background(), &abci.RequestFinalizeBlock{Height: 2, Time: time.Unix(1700000003, 0)})
		if err == nil {
			_, err = consensus.Commit(context.Background(), &abci.RequestCommit{})
		}
		committed <- err
	}()
	select {
	case err := <-committed:
		if err != nil {
			close(ctx.release)
			t.Fatal(err)
		}
	case <-time.After(time.Second):
		close(ctx.release)
		t.Fatal("SDK shared client lock blocked consensus behind public Query")
	}
	close(ctx.release)
	response := <-done
	if response == nil || response.Code != 0 || response.Height != first.Height || app.state.Height != 2 {
		t.Fatal("client isolation changed pinned query or execution")
	}
}
