//go:build !js

package main

import (
	"bytes"
	"context"
	"crypto/ed25519"
	abci "github.com/cometbft/cometbft/abci/types"
	"testing"
	"time"
)

// Advance a real committed SDK application after Query has selected its
// snapshot and before its current-only cut reader acquires the next lock.
type advancingFinancialCutQuery struct {
	financialApplication
	advance func()
}

func (backend *advancingFinancialCutQuery) CutTransaction(ctx context.Context, height int64) ([]byte, int64, error) {
	if backend.advance != nil {
		next := backend.advance
		backend.advance = nil
		next()
	}
	return backend.financialApplication.CutTransaction(ctx, height)
}

func TestFinancialSDKCutQueryHeightRace(t *testing.T) {
	fixtures := []struct {
		name string
		open func(*testing.T) (*Ledger, *financialNativeApplication, []ed25519.PrivateKey, []ed25519.PrivateKey, string)
	}{
		{"source1", financialSDKFixture}, {"source2", financialSessionSDKFixture}, {"source3", financialLineageSDKFixture},
	}
	for _, fixture := range fixtures {
		t.Run(fixture.name, func(t *testing.T) {
			for _, mode := range []string{"latest_advancing", "pinned_advancing", "pinned_current", "cancelled"} {
				t.Run(mode, func(t *testing.T) {
					app, backend, accounts, keys, _ := fixture.open(t)
					raw, _ := financialDagSignedBlock(t, backend.current, keys, 0, [][]byte{testTx(app.genesis, app.anchor, accounts, 0, 1, "1", 0)}, nil)
					commitFinancialSDK(t, app, financialDagBatchWire(t, backend.current, raw))
					before := copyState(app.state)
					advance := func() {
						when := time.Unix(0, backend.store.timeNs+1000000)
						if _, err := app.FinalizeBlock(context.Background(), &abci.RequestFinalizeBlock{Height: app.state.Height + 1, Time: when, Txs: [][]byte{}}); err != nil {
							t.Fatal(err)
						}
						if _, err := app.Commit(context.Background(), &abci.RequestCommit{}); err != nil {
							t.Fatal(err)
						}
					}
					if mode == "latest_advancing" || mode == "pinned_advancing" {
						app.financial = &advancingFinancialCutQuery{financialApplication: app.financial, advance: advance}
					}
					request := &abci.RequestQuery{Path: "/gg/financial-dag/cut-transaction"}
					if mode == "pinned_advancing" || mode == "pinned_current" {
						request.Height = before.Height
					}
					ctx, cancel := context.WithCancel(context.Background())
					defer cancel()
					if mode == "cancelled" {
						cancel()
					}
					result, err := app.Query(ctx, request)
					if err != nil {
						t.Fatal(err)
					}
					if mode == "pinned_advancing" || mode == "cancelled" {
						if result.Code == 0 || len(result.Value) > 0 {
							t.Fatal("stale pinned or cancelled cut was authorized")
						}
					} else {
						expected, err := backend.current.prepareCut()
						if err != nil || result.Code != 0 || result.Height != app.state.Height || !bytes.Equal(result.Value, expected) {
							t.Fatal("latest cut did not bind one current height", result.Code, result.Height, app.state.Height, err)
						}
					}
					if !bytes.Equal(canonical(before.FinancialDAG), canonical(app.state.FinancialDAG)) || !bytes.Equal(canonical(before.Accounts), canonical(app.state.Accounts)) {
						t.Fatal("query changed monetary state")
					}
				})
			}
		})
	}
}
