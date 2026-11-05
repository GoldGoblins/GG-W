//go:build !js

package main

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"encoding/base64"
	"encoding/json"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"time"

	abci "github.com/cometbft/cometbft/abci/types"
	cmtjson "github.com/cometbft/cometbft/libs/json"
	"github.com/cometbft/cometbft/types"
	"github.com/syndtr/goleveldb/leveldb"
)

func segmentedSDKGenesis(t *testing.T) (Genesis, []ed25519.PrivateKey) {
	t.Helper()
	base, keys := segmentedFixture(t)
	genesis, _, _, _ := testGenesis()
	genesis.Schema, genesis.DAGSegmented = "gg.native.genesis.v4", &base.source
	return genesis, keys
}

func segmentedSDKFixture(t *testing.T) (*Ledger, *dagSegmentedNativeApplication, []ed25519.PrivateKey, string) {
	t.Helper()
	genesis, keys := segmentedSDKGenesis(t)
	root := t.TempDir()
	app, err := newDagEnabledLedger(genesis, hashHex(canonical(genesis)), root, true)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = app.Close() })
	return app, app.segmented.(*dagSegmentedNativeApplication), keys, root
}

func commitSegmentedSDK(t *testing.T, app *Ledger, tx []byte) {
	t.Helper()
	txs := [][]byte{}
	if tx != nil {
		txs = append(txs, tx)
	}
	when := time.Unix(1700000002+app.state.Height, 0)
	if _, err := app.FinalizeBlock(context.Background(), &abci.RequestFinalizeBlock{Height: app.state.Height + 1, Txs: txs, Time: when}); err != nil {
		t.Fatal(err)
	}
	if _, err := app.Commit(context.Background(), &abci.RequestCommit{}); err != nil {
		t.Fatal(err)
	}
}

func segmentedSDKPacket(t *testing.T, app *Ledger) VerifyInput {
	t.Helper()
	_, _, _, validators := testGenesis()
	header := signedFixture(app.genesis, validators, app.state.Height+1, app.state.StateRoot, nil, types.BlockID{})
	raw, err := cmtjson.Marshal(header)
	if err != nil {
		t.Fatal(err)
	}
	return VerifyInput{Schema: "gg.consensus.proof.v1", Genesis: app.genesis, GenesisHash: app.anchor, SignedHeader: raw, State: copyState(app.state)}
}

func TestDagSegmentedLedgerTenThousandTXCutSDKCommitAndFullRestart(t *testing.T) {
	app, backend, keys, root := segmentedSDKFixture(t)
	ctx := context.Background()
	first := segmentedBatch(t, backend.current.active, segmentedWire(t, backend.current.active, keys, 0, 5000))
	check, err := app.CheckTx(ctx, &abci.RequestCheckTx{Tx: first})
	if err != nil || check.Code != 0 {
		t.Fatal("mempool", err)
	}
	processed, err := app.ProcessProposal(ctx, &abci.RequestProcessProposal{Txs: [][]byte{first}, Time: time.Unix(1700000002, 0)})
	if err != nil || processed.Status != abci.ResponseProcessProposal_ACCEPT || app.state.Height != 0 || backend.store.meta.Records != 1 {
		t.Fatal("originals not staged before accept", err)
	}
	commitSegmentedSDK(t, app, first)
	transaction, err := backend.current.cutTransaction()
	if err != nil {
		t.Fatal(err)
	}
	cut := canonical(transaction)
	prepared, err := app.PrepareProposal(ctx, &abci.RequestPrepareProposal{Txs: [][]byte{cut}, Time: time.Unix(1700000003, 0), MaxTxBytes: 64 * 1024 * 1024})
	if err != nil || len(prepared.Txs) != 1 || backend.store.ready == nil || app.state.DAGSegmented.Epoch != 1 {
		t.Fatal("cut archive not durable before proposer returns", err)
	}
	commitSegmentedSDK(t, app, cut)
	cutPacket := segmentedSDKPacket(t, app)
	result, err := verifyInput(cutPacket)
	if err != nil || result["dag_history_replay_verified"] != false || result["execution_status_verified"] != false ||
		app.state.DAGSegmented.Epoch != 2 || backend.store.meta.Records != 0 || backend.store.meta.Manifests != 1 || backend.current.active.nonces[0] != 5000 {
		t.Fatal("certified exact cut", err)
	}
	second := segmentedBatch(t, backend.current.active, segmentedWire(t, backend.current.active, keys, 0, 5000))
	commitSegmentedSDK(t, app, second)
	after := copyState(app.state)
	if after.DAGSegmented.Transactions != 10000 || after.DAGSegmented.Authors[0].Nonce != "10000" || after.DAGSegmented.Authors[0].Sequence != "2" {
		t.Fatal("lost ownership/nonce/sequence continuity")
	}
	if path := os.Getenv("GG_PUBLIC_SEGMENTED_CERT_FIXTURE"); path != "" {
		packet := map[string]any{"after_cut": cutPacket, "after_next": segmentedSDKPacket(t, app),
			"first_batch": base64.StdEncoding.EncodeToString(first), "second_batch": base64.StdEncoding.EncodeToString(second)}
		if err := os.WriteFile(path, canonical(packet), 0600); err != nil {
			t.Fatal(err)
		}
	}
	if err := app.Close(); err != nil {
		t.Fatal(err)
	}
	restored, err := newDagEnabledLedger(app.genesis, app.anchor, root, false)
	if err != nil {
		t.Fatal("full signed archive + active replay startup", err)
	}
	defer restored.Close()
	if !bytes.Equal(canonical(restored.state), canonical(after)) {
		t.Fatal("restart changed selected SDK state")
	}
	nextBackend := restored.segmented.(*dagSegmentedNativeApplication)
	third := segmentedBatch(t, nextBackend.current.active, segmentedWire(t, nextBackend.current.active, keys, 0, 1))
	commitSegmentedSDK(t, restored, third)
	if restored.state.DAGSegmented.Transactions != 10001 {
		t.Fatal("real next author nonce failed after archive + active restart")
	}
}

func TestDagSegmentedLedgerSDKCertificateBindsCutAndRejectsChangedAuthorOrQuorum(t *testing.T) {
	app, backend, keys, _ := segmentedSDKFixture(t)
	commitSegmentedSDK(t, app, segmentedBatch(t, backend.current.active, segmentedWire(t, backend.current.active, keys, 0, 1)))
	cut, _ := backend.current.cutTransaction()
	commitSegmentedSDK(t, app, canonical(cut))
	packet := segmentedSDKPacket(t, app)
	for _, kind := range []string{"cut", "closed_root", "nonce", "owner", "two_votes"} {
		t.Run(kind, func(t *testing.T) {
			var bad VerifyInput
			if decodeStrict(canonical(packet), &bad) != nil {
				t.Fatal("fixture")
			}
			switch kind {
			case "cut":
				bad.State.DAGSegmented.LastCut = DagZero
			case "closed_root":
				bad.State.DAGSegmented.ClosedRoot = DagZero
			case "nonce":
				bad.State.DAGSegmented.Authors[0].Nonce = "0"
			case "owner":
				bad.State.DAGSegmented.Authors[0].Key = bad.State.DAGSegmented.Authors[1].Key
			case "two_votes":
				var header types.SignedHeader
				if cmtjson.Unmarshal(bad.SignedHeader, &header) != nil {
					t.Fatal("fixture")
				}
				for index := 2; index < 4; index++ {
					header.Commit.Signatures[index] = types.NewCommitSigAbsent()
				}
				bad.SignedHeader, _ = cmtjson.Marshal(header)
			}
			sealState(&bad.State)
			if result, err := verifyInput(bad); err == nil || result != nil {
				t.Fatal("changed segmented state/quorum accepted")
			}
		})
	}
}

func TestDagSegmentedLedgerAtomicCutCommitAmbiguityRecoversOnlyExactOldOrNewState(t *testing.T) {
	for _, afterSync := range []bool{false, true} {
		t.Run(map[bool]string{false: "before", true: "after"}[afterSync], func(t *testing.T) {
			app, backend, keys, root := segmentedSDKFixture(t)
			commitSegmentedSDK(t, app, segmentedBatch(t, backend.current.active, segmentedWire(t, backend.current.active, keys, 0, 4)))
			old := copyState(app.state)
			cut, _ := backend.current.cutTransaction()
			if _, err := app.FinalizeBlock(context.Background(), &abci.RequestFinalizeBlock{Height: 2, Txs: [][]byte{canonical(cut)}, Time: time.Unix(1700000003, 0)}); err != nil {
				t.Fatal(err)
			}
			newState := copyState(*app.staged)
			write := backend.store.write
			backend.store.write = func(batch *leveldb.Batch) error {
				if afterSync {
					if err := write(batch); err != nil {
						return err
					}
				}
				return errors.New("owned ambiguous cut commit")
			}
			if _, err := app.Commit(context.Background(), &abci.RequestCommit{}); err == nil || !bytes.Equal(canonical(app.state), canonical(old)) {
				t.Fatal("uncertain commit acknowledged or published")
			}
			if _, err := app.Commit(context.Background(), &abci.RequestCommit{}); err == nil {
				t.Fatal("failed handle silently retried uncertain commit")
			}
			_ = app.Close()
			restored, err := newDagEnabledLedger(app.genesis, app.anchor, root, false)
			if err != nil {
				t.Fatal("exact old/new recovery", err)
			}
			defer restored.Close()
			expected := old
			if afterSync {
				expected = newState
			}
			if !bytes.Equal(canonical(restored.state), canonical(expected)) {
				t.Fatal("recovery manufactured a prefix or guessed state")
			}
			live := restored.segmented.(*dagSegmentedNativeApplication)
			commitSegmentedSDK(t, restored, segmentedBatch(t, live.current.active, segmentedWire(t, live.current.active, keys, 0, 1)))
			if restored.state.DAGSegmented.Transactions != 5 {
				t.Fatal("nonce lost across ambiguous cut")
			}
		})
	}
}

func TestDagSegmentedLedgerRejectsDamagedReferencedArchiveAndUnpreparedCut(t *testing.T) {
	app, backend, keys, root := segmentedSDKFixture(t)
	commitSegmentedSDK(t, app, segmentedBatch(t, backend.current.active, segmentedWire(t, backend.current.active, keys, 0, 1)))
	cut, _ := backend.current.cutTransaction()
	plan, _ := backend.current.checkedCutTransaction(canonical(cut))
	state := copyState(app.state)
	value, _ := plan.next.state()
	state.DAGSegmented = &value
	state.Height++
	sealState(&state)
	if backend.store.commitHistory(context.Background(), append(append([]State(nil), app.history...), state), plan.next) == nil {
		t.Fatal("unprepared cut committed without archive barrier")
	}
	commitSegmentedSDK(t, app, canonical(cut))
	path := filepath.Join(root, "gg-dag-segments", app.state.DAGSegmented.LastCut+".ggseg")
	_ = app.Close()
	if err := os.WriteFile(path, []byte("corrupt referenced original history"), 0600); err != nil {
		t.Fatal(err)
	}
	if restored, err := newDagEnabledLedger(app.genesis, app.anchor, root, false); err == nil || restored != nil {
		if restored != nil {
			_ = restored.Close()
		}
		t.Fatal("corrupt signed history replaced by saved account snapshot")
	}
	raw, _ := os.ReadFile(path)
	if string(raw) != "corrupt referenced original history" {
		t.Fatal("corrupt archive silently repaired")
	}
}

func TestDagSegmentedLedgerInvalidFinalizeAndStaleCutCannotPublish(t *testing.T) {
	app, backend, keys, _ := segmentedSDKFixture(t)
	commitSegmentedSDK(t, app, segmentedBatch(t, backend.current.active, segmentedWire(t, backend.current.active, keys, 0, 1)))
	cut, _ := backend.current.cutTransaction()
	when := time.Unix(1700000003, 0)
	if _, err := app.FinalizeBlock(context.Background(), &abci.RequestFinalizeBlock{Height: 2, Txs: [][]byte{canonical(cut)}, Time: when}); err != nil {
		t.Fatal(err)
	}
	if _, err := app.FinalizeBlock(context.Background(), &abci.RequestFinalizeBlock{Height: 2, Txs: [][]byte{canonical(cut), canonical(cut)}, Time: when}); err == nil {
		t.Fatal("multiple cuts finalized")
	}
	if _, err := app.Commit(context.Background(), &abci.RequestCommit{}); err == nil || app.state.Height != 1 {
		t.Fatal("older staged candidate survived failed finalize")
	}
	commitSegmentedSDK(t, app, canonical(cut))
	response, err := app.ProcessProposal(context.Background(), &abci.RequestProcessProposal{Txs: [][]byte{canonical(cut)}, Time: when.Add(time.Second)})
	if err != nil || response.Status != abci.ResponseProcessProposal_REJECT {
		t.Fatal("stale epoch cut replay accepted", err)
	}
	responseQuery, err := app.Query(context.Background(), &abci.RequestQuery{Path: "/gg/dag/history"})
	var state dagSegmentedState
	if err != nil || responseQuery.Code != 0 || json.Unmarshal(responseQuery.Value, &state) != nil || state != *app.state.DAGSegmented {
		t.Fatal("CLI query differs from SDK-selected state", err)
	}
}

func TestDagSegmentedLedgerReplayedArchivesAuthenticateIntermediateQueryStates(t *testing.T) {
	app, backend, keys, root := segmentedSDKFixture(t)
	for index := 0; index < 3; index++ {
		commitSegmentedSDK(t, app, segmentedBatch(t, backend.current.active, segmentedWire(t, backend.current.active, keys, 0, 1)))
	}
	cut, _ := backend.current.cutTransaction()
	commitSegmentedSDK(t, app, canonical(cut))
	// Keep the final genuine root and all originals. Forge only a middle query
	// snapshot and recompute its native state hash. Startup must reject it.
	var saved persisted
	raw, err := backend.store.db.Get([]byte("history"), nil)
	if err != nil || decodeStrict(raw, &saved) != nil {
		t.Fatal("fixture", err)
	}
	saved.History[1].DAGSegmented.Active.AccountRoot = DagZero
	sealState(&saved.History[1])
	batch := new(leveldb.Batch)
	batch.Put([]byte("history"), canonical(saved))
	if err := backend.store.write(batch); err != nil {
		t.Fatal(err)
	}
	_ = app.Close()
	if restored, err := newDagEnabledLedger(app.genesis, app.anchor, root, false); err == nil || restored != nil {
		if restored != nil {
			_ = restored.Close()
		}
		t.Fatal("re-sealed middle snapshot accepted without signed-history provenance")
	}
}

func TestDagSegmentedLedgerExplicitVersionAndImmutableOwnedGenesis(t *testing.T) {
	genesis, _ := segmentedSDKGenesis(t)
	old := genesis
	old.Schema = "gg.native.genesis.v3"
	if validateGenesis(old, hashHex(canonical(old))) == nil {
		t.Fatal("old SDK genesis silently gained segmented semantics")
	}
	base, _ := dagFixture(t)
	both := genesis
	both.DAG = &base.Source
	if validateGenesis(both, hashHex(canonical(both))) == nil {
		t.Fatal("two DAG modes in one genesis accepted")
	}
	app, err := newDagEnabledLedger(genesis, hashHex(canonical(genesis)), t.TempDir(), true)
	if err != nil {
		t.Fatal(err)
	}
	defer app.Close()
	before := canonical(app.genesis)
	genesis.DAGSegmented.Genesis.Producers[0] = DagZero
	if !bytes.Equal(before, canonical(app.genesis)) {
		t.Fatal("caller mutated owned native source/roles")
	}
	if _, err := newLedger(app.genesis, app.anchor, t.TempDir()); err == nil {
		t.Fatal("segmented source entered volatile legacy ledger")
	}
}

func TestDagSegmentedLedgerKeepsNativeTransfersAndCompleteExecutionProof(t *testing.T) {
	app, backend, keys, _ := segmentedSDKFixture(t)
	_, _, nativeKeys, validators := testGenesis()
	dag := segmentedBatch(t, backend.current.active, segmentedWire(t, backend.current.active, keys, 0, 1))
	native := testTx(app.genesis, app.anchor, nativeKeys, 0, 1, "100", 0)
	when := time.Unix(1700000002, 0)
	for _, txs := range [][][]byte{{dag, native}, {native, dag}} {
		response, err := app.ProcessProposal(context.Background(), &abci.RequestProcessProposal{Txs: txs, Time: when})
		if err != nil || response.Status != abci.ResponseProcessProposal_REJECT {
			t.Fatal("mixed execution scopes accepted", err)
		}
	}
	commitSegmentedSDK(t, app, dag)
	before := copyState(app.state)
	proposal, err := app.Query(context.Background(), &abci.RequestQuery{Path: "/gg/dag/cut-proposal"})
	value, _ := backend.current.cutTransaction()
	if err != nil || proposal.Code != 0 || !bytes.Equal(proposal.Value, canonical(value)) || backend.store.ready != nil {
		t.Fatal("local cut query changed archive/consensus state", err)
	}
	commitSegmentedSDK(t, app, native)
	if *before.DAGSegmented != *app.state.DAGSegmented {
		t.Fatal("native transfer changed DAG history")
	}
	txs := types.Txs{native}
	txHeader := signedFixture(app.genesis, validators, 2, before.StateRoot, txs, types.BlockID{})
	header := signedFixture(app.genesis, validators, 3, app.state.StateRoot, nil, txHeader.Commit.BlockID)
	headerJSON, _ := cmtjson.Marshal(header)
	txHeaderJSON, _ := cmtjson.Marshal(txHeader)
	proofJSON, _ := cmtjson.Marshal(txs.Proof(0))
	packet := VerifyInput{Schema: "gg.consensus.proof.v1", Genesis: app.genesis, GenesisHash: app.anchor, State: app.state, SignedHeader: headerJSON,
		TxHeader: txHeaderJSON, TxProof: proofJSON, ExpectedTxHash: hashHex(native), BeforeState: &before, BlockTxs: []string{base64.StdEncoding.EncodeToString(native)}}
	result, err := verifyInput(packet)
	if err != nil || result["execution_status_verified"] != true || result["transaction_inclusion_verified"] != true {
		t.Fatal("native execution proof lost in new mode", err)
	}
}

func TestDagSegmentedLedgerLosingPreparedBranchIsNotSelectedOrRetained(t *testing.T) {
	app, backend, keys, root := segmentedSDKFixture(t)
	a := segmentedBatch(t, backend.current.active, segmentedWire(t, backend.current.active, keys, 0, 1))
	b := segmentedBatch(t, backend.current.active, segmentedWire(t, backend.current.active, keys, 1, 1))
	when := time.Unix(1700000002, 0)
	for _, tx := range [][]byte{a, b} {
		response, err := app.ProcessProposal(context.Background(), &abci.RequestProcessProposal{Txs: [][]byte{tx}, Time: when})
		if err != nil || response.Status != abci.ResponseProcessProposal_ACCEPT {
			t.Fatal("alternative proposal not prepared", err)
		}
	}
	if backend.store.meta.Records != 2 || app.state.DAGSegmented.Blocks != 0 {
		t.Fatal("preparation published a branch")
	}
	commitSegmentedSDK(t, app, b)
	if backend.store.meta.Records != 1 || app.state.DAGSegmented.Authors[0].Nonce != "0" || app.state.DAGSegmented.Authors[1].Nonce != "1" {
		t.Fatal("losing creator selected or losing data retained")
	}
	_ = app.Close()
	restored, err := newDagEnabledLedger(app.genesis, app.anchor, root, false)
	if err != nil {
		t.Fatal("winning branch replay", err)
	}
	defer restored.Close()
	if *restored.state.DAGSegmented != *app.state.DAGSegmented {
		t.Fatal("restart chose a prepared losing branch")
	}
}

func TestDagSegmentedLedgerCrashChild(t *testing.T) {
	mode := os.Getenv("GG_TEST_SEGMENT_SDK_CRASH_MODE")
	if mode == "" {
		return
	}
	genesis, keys := segmentedSDKGenesis(t)
	app, err := newDagEnabledLedger(genesis, hashHex(canonical(genesis)), os.Getenv("GG_TEST_SEGMENT_SDK_CRASH_ROOT"), true)
	if err != nil {
		t.Fatal(err)
	}
	backend := app.segmented.(*dagSegmentedNativeApplication)
	commitSegmentedSDK(t, app, segmentedBatch(t, backend.current.active, segmentedWire(t, backend.current.active, keys, 0, 1)))
	cut, _ := backend.current.cutTransaction()
	if _, err := app.FinalizeBlock(context.Background(), &abci.RequestFinalizeBlock{Height: 2, Txs: [][]byte{canonical(cut)}, Time: time.Unix(1700000003, 0)}); err != nil {
		t.Fatal(err)
	}
	write := backend.store.write
	backend.store.write = func(batch *leveldb.Batch) error {
		if mode == "after" {
			if err := write(batch); err != nil {
				return err
			}
			os.Exit(78)
		}
		os.Exit(77)
		return nil
	}
	_, _ = app.Commit(context.Background(), &abci.RequestCommit{})
	t.Fatal("real cut-commit crash injection did not execute")
}

func TestDagSegmentedLedgerActualProcessCrashAtAtomicCutCommit(t *testing.T) {
	genesis, keys := segmentedSDKGenesis(t)
	for index, mode := range []string{"before", "after"} {
		t.Run(mode, func(t *testing.T) {
			root := t.TempDir()
			ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
			defer cancel()
			command := exec.CommandContext(ctx, os.Args[0], "-test.run=^TestDagSegmentedLedgerCrashChild$")
			command.Env = append(os.Environ(), "GG_TEST_SEGMENT_SDK_CRASH_MODE="+mode, "GG_TEST_SEGMENT_SDK_CRASH_ROOT="+root)
			out, err := command.CombinedOutput()
			var exit *exec.ExitError
			if !errors.As(err, &exit) || exit.ExitCode() != 77+index {
				t.Fatal("child missed real synchronous commit boundary", err, string(out))
			}
			app, err := newDagEnabledLedger(genesis, hashHex(canonical(genesis)), root, false)
			if err != nil {
				t.Fatal("post-crash replay", err)
			}
			defer app.Close()
			if app.state.Height != int64(1+index) || app.state.DAGSegmented.Epoch != uint64(1+index) {
				t.Fatal("crash recovery guessed old/new head")
			}
			backend := app.segmented.(*dagSegmentedNativeApplication)
			commitSegmentedSDK(t, app, segmentedBatch(t, backend.current.active, segmentedWire(t, backend.current.active, keys, 0, 1)))
			if app.state.DAGSegmented.Transactions != 2 {
				t.Fatal("nonce repeated or lost after crash")
			}
		})
	}
}
