//go:build !js

package main

// Keep the SDK's normal shared ordering for mutable ABCI calls. Only Query
// uses Ledger's own immutable-state capture and bounded snapshot readers;
// it must not hold the SDK local client's global mutex while reading data.
import (
	"context"
	"strings"

	abcicli "github.com/cometbft/cometbft/abci/client"
	abci "github.com/cometbft/cometbft/abci/types"
	"github.com/cometbft/cometbft/proxy"
)

type ledgerQueryClient struct {
	abcicli.Client
	app   *Ledger
	peers *nativeObserverPeerPolicy
	owned context.Context
}

func (client *ledgerQueryClient) Query(ctx context.Context, request *abci.RequestQuery) (*abci.ResponseQuery, error) {
	if client.peers != nil && strings.HasPrefix(request.Path, "/p2p/filter/") {
		if client.peers.allowed(ctx, request.Path) {
			return &abci.ResponseQuery{Code: 0}, nil
		}
		return &abci.ResponseQuery{Code: 1, Log: "GG_CONSENSUS_PEER_NOT_AUTHORIZED"}, nil
	}
	return client.app.Query(ctx, request)
}

type ledgerClientCreator struct {
	base  proxy.ClientCreator
	app   *Ledger
	peers *nativeObserverPeerPolicy
	owned context.Context
}

func (creator *ledgerClientCreator) NewABCIClient() (abcicli.Client, error) {
	client, err := creator.base.NewABCIClient()
	if err != nil {
		return nil, err
	}
	return &ledgerQueryClient{Client: client, app: creator.app, peers: creator.peers, owned: creator.owned}, nil
}

func newLedgerClientCreator(app *Ledger) proxy.ClientCreator {
	return newOwnedLedgerClientCreator(app, nil)
}

func newLedgerClientCreatorWithPeers(app *Ledger, peers *nativeObserverPeerPolicy) proxy.ClientCreator {
	return newOwnedLedgerClientCreatorWithPeers(app, peers, nil)
}

func newOwnedLedgerClientCreator(app *Ledger, owned context.Context) proxy.ClientCreator {
	return &ledgerClientCreator{base: proxy.NewLocalClientCreator(app), app: app, owned: owned}
}
func newOwnedLedgerClientCreatorWithPeers(app *Ledger, peers *nativeObserverPeerPolicy, owned context.Context) proxy.ClientCreator {
	return &ledgerClientCreator{base: proxy.NewLocalClientCreator(app), app: app, peers: peers, owned: owned}
}

// SDK crash-gap replay currently passes context.TODO. Join cancellation and
// the one non-authoritative owned-work value without bypassing the embedded
// SDK local client's shared mutable-call mutex.
func ownedLedgerCallContext(call, owned context.Context) (context.Context, func()) {
	if owned == nil {
		return call, func() {}
	}
	joined, cancel := context.WithCancel(call)
	stop := context.AfterFunc(owned, cancel)
	if owned.Err() != nil {
		cancel()
	}
	if recovery := recoveryFrom(owned); recovery != nil {
		joined = context.WithValue(joined, ownedRecoveryKey{}, recovery)
		joined = context.WithValue(joined, ownedSDKInvocationKey{}, true)
	}
	return joined, func() { stop(); cancel() }
}
func (client *ledgerQueryClient) FinalizeBlock(ctx context.Context, request *abci.RequestFinalizeBlock) (*abci.ResponseFinalizeBlock, error) {
	joined, done := ownedLedgerCallContext(ctx, client.owned)
	defer done()
	response, err := client.Client.FinalizeBlock(joined, request)
	if err == nil {
		err = recoveryWork(joined, 1, nil)
	}
	return response, err
}
func (client *ledgerQueryClient) Commit(ctx context.Context, request *abci.RequestCommit) (*abci.ResponseCommit, error) {
	joined, done := ownedLedgerCallContext(ctx, client.owned)
	defer done()
	response, err := client.Client.Commit(joined, request)
	if err == nil {
		err = recoveryWork(joined, 1, nil)
	}
	return response, err
}
