//go:build !js

package main

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"encoding/base64"
	"encoding/hex"
	"errors"
	"testing"
	"time"

	abci "github.com/cometbft/cometbft/abci/types"
	cmtjson "github.com/cometbft/cometbft/libs/json"
	"github.com/cometbft/cometbft/types"
	voi "github.com/oasisprotocol/curve25519-voi/primitives/ed25519"
	"github.com/syndtr/goleveldb/leveldb"
)

func dagLedgerFixture(t *testing.T) (*Ledger, []ed25519.PrivateKey, string) {
	t.Helper()
	base, keys := dagFixture(t)
	genesis, _, _, _ := testGenesis()
	genesis.Schema = "gg.native.genesis.v2"
	genesis.DAG = &base.Source
	root := t.TempDir()
	app, err := newDagEnabledLedger(genesis, hashHex(canonical(genesis)), root, true)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = app.Close() })
	return app, keys, root
}

func TestDagLedgerPersistsBeforeProposalAcceptButPublishesOnlyAfterCommit(t *testing.T) {
	app, keys, root := dagLedgerFixture(t)
	ctx := context.Background()
	wire := dagWire(t, app.dag, keys, 0, 3)
	batch := dagBatchWire(t, app.dag, wire)
	when := time.Unix(1700000002, 0).UTC()
	check, err := app.CheckTx(ctx, &abci.RequestCheckTx{Tx: batch})
	if err != nil || check.Code != 0 {
		t.Fatal("valid batch refused mempool", err)
	}
	next, err := applyDagBatch(app.dag, batch, when.UnixNano())
	if err != nil {
		t.Fatal(err)
	}
	if _, err = app.store.load(next.Commitment); err == nil {
		t.Fatal("mempool check persisted a certifiable checkpoint")
	}
	prepared, err := app.PrepareProposal(ctx, &abci.RequestPrepareProposal{Txs: [][]byte{batch}, Time: when, MaxTxBytes: 64 * 1024 * 1024})
	if err != nil || len(prepared.Txs) != 1 {
		t.Fatal("proposer did not retain batch", err)
	}
	if _, err = app.store.load(next.Commitment); err != nil {
		t.Fatal("proposer returned before payload became durable", err)
	}
	accepted, err := app.ProcessProposal(ctx, &abci.RequestProcessProposal{Txs: prepared.Txs, Time: when})
	if err != nil || accepted.Status != abci.ResponseProcessProposal_ACCEPT || app.state.DAG.Blocks != 0 {
		t.Fatal("proposal acceptance changed canonical state", err)
	}
	nativeBefore := canonical(app.state.Accounts)
	response, err := app.FinalizeBlock(ctx, &abci.RequestFinalizeBlock{Height: 1, Time: when, Txs: prepared.Txs})
	if err != nil || response.TxResults[0].Code != 0 || app.state.Height != 0 || app.state.DAG.Blocks != 0 {
		t.Fatal("finalize published uncommitted state", err)
	}
	if _, err = app.Commit(ctx, &abci.RequestCommit{}); err != nil {
		t.Fatal(err)
	}
	if app.state.Height != 1 || app.state.DAG.Transactions != 3 || app.state.DAG.Blocks != 1 || !bytes.Equal(nativeBefore, canonical(app.state.Accounts)) ||
		!bytes.Equal(response.AppHash, mustHex(t, app.state.StateRoot)) {
		t.Fatal("commit did not bind separate DAG execution into exact AppHash")
	}
	expected := canonical(app.state)
	_ = app.Close()
	reloaded, err := newDagEnabledLedger(app.genesis, app.anchor, root, false)
	if err != nil {
		t.Fatal(err)
	}
	defer reloaded.Close()
	if !bytes.Equal(expected, canonical(reloaded.state)) || !bytes.Equal(canonical(next.Accounts), canonical(reloaded.dag.Accounts)) {
		t.Fatal("restart did not restore exact committed DAG state")
	}
}

func mustHex(t *testing.T, value string) []byte {
	t.Helper()
	raw, err := hex.DecodeString(value)
	if err != nil {
		t.Fatal(err)
	}
	return raw
}

func TestDagLedgerStorageFailureRejectsVotingAndMempool(t *testing.T) {
	for _, proposer := range []bool{false, true} {
		t.Run(map[bool]string{false: "process", true: "prepare"}[proposer], func(t *testing.T) {
			app, keys, _ := dagLedgerFixture(t)
			batch := dagBatchWire(t, app.dag, dagWire(t, app.dag, keys, 0, 1))
			store := app.store.(*dagStore)
			store.write = func(*leveldb.Batch) error { return errors.New("owned injected failure") }
			ctx := context.Background()
			when := time.Unix(1700000002, 0)
			if proposer {
				if _, err := app.PrepareProposal(ctx, &abci.RequestPrepareProposal{Txs: [][]byte{batch}, Time: when, MaxTxBytes: 64 * 1024 * 1024}); err == nil {
					t.Fatal("failed durable write returned a proposal")
				}
			} else {
				proposal, err := app.ProcessProposal(ctx, &abci.RequestProcessProposal{Txs: [][]byte{batch}, Time: when})
				if err == nil || proposal != nil {
					t.Fatal("failed local storage produced a protocol vote instead of an unavailable-node error")
				}
			}
			check, _ := app.CheckTx(ctx, &abci.RequestCheckTx{Tx: batch})
			if check.Code == 0 || app.state.Height != 0 || app.state.DAG.Blocks != 0 {
				t.Fatal("faulted storage accepted new work or changed state")
			}
		})
	}
}

func TestDagLedgerCommitUnknownOutcomeRecoversExactDurableSelection(t *testing.T) {
	for _, after := range []bool{false, true} {
		t.Run(map[bool]string{false: "before_sync", true: "after_sync_lost_return"}[after], func(t *testing.T) {
			app, keys, root := dagLedgerFixture(t)
			batch := dagBatchWire(t, app.dag, dagWire(t, app.dag, keys, 0, 2))
			ctx := context.Background()
			if _, err := app.FinalizeBlock(ctx, &abci.RequestFinalizeBlock{Height: 1, Time: time.Unix(1700000002, 0), Txs: [][]byte{batch}}); err != nil {
				t.Fatal(err)
			}
			store := app.store.(*dagStore)
			write := store.write
			store.write = func(batch *leveldb.Batch) error {
				if after {
					if err := write(batch); err != nil {
						return err
					}
				}
				return errors.New("owned injected commit failure")
			}
			if _, err := app.Commit(ctx, &abci.RequestCommit{}); err == nil || app.state.Height != 0 || app.state.DAG.Blocks != 0 {
				t.Fatal("uncertain commit was acknowledged or published")
			}
			if _, err := app.Commit(ctx, &abci.RequestCommit{}); err == nil {
				t.Fatal("faulted store silently retried an uncertain commit")
			}
			_ = app.Close()
			restored, err := newDagEnabledLedger(app.genesis, app.anchor, root, false)
			if err != nil {
				t.Fatal(err)
			}
			defer restored.Close()
			expected := int64(0)
			if after {
				expected = 1
			}
			if restored.state.Height != expected || restored.state.DAG.Blocks != int(expected) {
				t.Fatal("recovery guessed the durable commit outcome")
			}
		})
	}
}

func TestDagLedgerInvalidFinalizeClearsPreviouslyStagedCandidate(t *testing.T) {
	app, keys, _ := dagLedgerFixture(t)
	ctx := context.Background()
	batch := dagBatchWire(t, app.dag, dagWire(t, app.dag, keys, 0, 1))
	when := time.Unix(1700000002, 0)
	if _, err := app.FinalizeBlock(ctx, &abci.RequestFinalizeBlock{Height: 1, Time: when, Txs: [][]byte{batch}}); err != nil {
		t.Fatal(err)
	}
	if _, err := app.FinalizeBlock(ctx, &abci.RequestFinalizeBlock{Height: 1, Time: when, Txs: [][]byte{batch, batch}}); err == nil {
		t.Fatal("multiple DAG batches accepted in one consensus block")
	}
	if _, err := app.Commit(ctx, &abci.RequestCommit{}); err == nil || app.state.Height != 0 {
		t.Fatal("failed finalization committed an older candidate")
	}
}

func TestDagAlternativeValidOuterSignatureCannotPoisonPayloadCache(t *testing.T) {
	app, keys, _ := dagLedgerFixture(t)
	raw := dagWire(t, app.dag, keys, 0, 1)
	var alternative DagBlock
	if decodeStrict(raw, &alternative) != nil {
		t.Fatal("invalid fixture")
	}
	message := append([]byte("GG-DAG-PROPOSAL-SIGN-v1\x00"), canonical(alternative.Body)...)
	signature, err := voi.PrivateKey(keys[0]).Sign(rand.Reader, message, &voi.Options{AddedRandomness: true})
	if err != nil {
		t.Fatal(err)
	}
	alternative.Signature = hex.EncodeToString(signature)
	other := canonical(alternative)
	if bytes.Equal(raw, other) || !ed25519.Verify(keys[0].Public().(ed25519.PublicKey), message, signature) {
		t.Fatal("alternative signature fixture is not valid and distinct")
	}
	a, err := applyDagBatch(app.dag, dagBatchWire(t, app.dag, raw), 1700000002000000000)
	if err != nil {
		t.Fatal(err)
	}
	b, err := applyDagBatch(app.dag, dagBatchWire(t, app.dag, other), 1700000002000000000)
	if err != nil {
		t.Fatal(err)
	}
	if orderFixture(t, a)[0].Hash != orderFixture(t, b)[0].Hash || a.Manifest.Blocks[0] == b.Manifest.Blocks[0] || a.Commitment.AccountRoot != b.Commitment.AccountRoot {
		t.Fatal("body identity and wire identity were conflated")
	}
	for _, candidate := range []*DagExecution{a, b} {
		if err := app.store.prepare(candidate); err != nil {
			t.Fatal("earlier valid signature poisoned alternative candidate", err)
		}
	}
	for _, candidate := range []*DagExecution{a, b} {
		if _, err := app.store.load(candidate.Commitment); err != nil {
			t.Fatal("prepared alternative could not be recovered", err)
		}
	}
}

func TestDagAndNativeTransfersUseSeparateBlocksAndKeepCompleteNativeExecutionProof(t *testing.T) {
	app, dagKeys, _ := dagLedgerFixture(t)
	_, _, nativeKeys, validators := testGenesis()
	ctx := context.Background()
	when := time.Unix(1700000002, 0)
	dagBatch := dagBatchWire(t, app.dag, dagWire(t, app.dag, dagKeys, 0, 1))
	nativeTx := testTx(app.genesis, app.anchor, nativeKeys, 0, 1, "100", 0)
	for _, transactions := range [][][]byte{{dagBatch, nativeTx}, {nativeTx, dagBatch}} {
		prepared, err := app.PrepareProposal(ctx, &abci.RequestPrepareProposal{Txs: transactions, Time: when, MaxTxBytes: 64 * 1024 * 1024})
		if err != nil || len(prepared.Txs) != 1 || !bytes.Equal(prepared.Txs[0], transactions[0]) {
			t.Fatal("proposal did not retain a single execution-proof kind", err)
		}
		processed, _ := app.ProcessProposal(ctx, &abci.RequestProcessProposal{Txs: transactions, Time: when})
		if processed.Status != abci.ResponseProcessProposal_REJECT {
			t.Fatal("mixed execution-proof kinds accepted")
		}
		if _, err := app.FinalizeBlock(ctx, &abci.RequestFinalizeBlock{Height: 1, Txs: transactions, Time: when}); err == nil {
			t.Fatal("mixed block finalized")
		}
	}
	if _, err := app.FinalizeBlock(ctx, &abci.RequestFinalizeBlock{Height: 1, Txs: [][]byte{dagBatch}, Time: when}); err != nil {
		t.Fatal(err)
	}
	if _, err := app.Commit(ctx, &abci.RequestCommit{}); err != nil {
		t.Fatal(err)
	}
	before := copyState(app.state)
	if _, err := app.FinalizeBlock(ctx, &abci.RequestFinalizeBlock{Height: 2, Txs: [][]byte{nativeTx}, Time: when.Add(time.Second)}); err != nil {
		t.Fatal("native transfer disabled in DAG mode", err)
	}
	if _, err := app.Commit(ctx, &abci.RequestCommit{}); err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(canonical(before.DAG), canonical(app.state.DAG)) {
		t.Fatal("separate native transfer changed DAG state")
	}
	txs := types.Txs{nativeTx}
	txHeader := signedFixture(app.genesis, validators, 2, before.StateRoot, txs, types.BlockID{})
	stateHeader := signedFixture(app.genesis, validators, 3, app.state.StateRoot, nil, txHeader.Commit.BlockID)
	txHeaderJSON, _ := cmtjson.Marshal(txHeader)
	stateHeaderJSON, _ := cmtjson.Marshal(stateHeader)
	txProofJSON, _ := cmtjson.Marshal(txs.Proof(0))
	input := VerifyInput{Schema: "gg.consensus.proof.v1", Genesis: app.genesis, GenesisHash: app.anchor, State: app.state, SignedHeader: stateHeaderJSON,
		TxHeader: txHeaderJSON, TxProof: txProofJSON, ExpectedTxHash: hashHex(nativeTx), BeforeState: &before, BlockTxs: []string{base64.StdEncoding.EncodeToString(nativeTx)}}
	result, err := verifyInput(input)
	if err != nil || result["execution_status_verified"] != true || result["transaction_inclusion_verified"] != true {
		t.Fatal("native transfer lost complete light execution verification", err)
	}
}
