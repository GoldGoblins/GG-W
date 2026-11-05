package main

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"strconv"
	"strings"
	"testing"
	"time"

	abci "github.com/cometbft/cometbft/abci/types"
	cmted "github.com/cometbft/cometbft/crypto/ed25519"
	cmtjson "github.com/cometbft/cometbft/libs/json"
	"github.com/cometbft/cometbft/types"
)

func dagCertifiedFixture(t *testing.T) VerifyInput {
	t.Helper()
	app, keys, _ := dagLedgerFixture(t)
	wires := [][]byte{}
	for producer := 0; producer < 5; producer++ {
		wires = append(wires, dagWire(t, app.dag, keys, producer, producer+1))
	}
	batch := dagBatchWire(t, app.dag, wires...)
	if _, err := app.FinalizeBlock(context.Background(), &abci.RequestFinalizeBlock{Height: 1, Time: time.Unix(1700000002, 0), Txs: [][]byte{batch}}); err != nil {
		t.Fatal(err)
	}
	if _, err := app.Commit(context.Background(), &abci.RequestCommit{}); err != nil {
		t.Fatal(err)
	}
	_, _, _, validators := testGenesis()
	header := signedFixture(app.genesis, validators, 2, app.state.StateRoot, nil, types.BlockID{})
	raw, _ := cmtjson.Marshal(header)
	account, err := dagAccountProofFor(app.dag, app.state, app.genesis.DAG.Accounts[5])
	if err != nil {
		t.Fatal(err)
	}
	block, err := dagBlockProofFor(app.dag, app.state, orderFixture(t, app.dag)[4].Hash)
	if err != nil {
		t.Fatal(err)
	}
	page, err := dagOrderPageFor(app.dag, app.state, 0)
	if err != nil {
		t.Fatal(err)
	}
	return VerifyInput{Schema: "gg.consensus.proof.v1", Genesis: app.genesis, GenesisHash: app.anchor, State: app.state,
		SignedHeader: raw, DAGAccountProof: &account, DAGBlockProof: &block, DAGOrderPage: &page}
}

func TestCertifiedConflictFixtureUsesTwoSDKValidCommitsForOneHeight(t *testing.T) {
	genesis, anchor, _, validators := testGenesis()
	if path := os.Getenv("GG_PUBLIC_LAN_ANCHOR_FIXTURE"); path != "" {
		raw, err := os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
		var bound struct {
			Genesis     Genesis `json:"genesis"`
			GenesisHash string  `json:"genesis_hash"`
		}
		if decodeStrict(raw, &bound) != nil || validateGenesis(bound.Genesis, bound.GenesisHash) != nil {
			t.Fatal("invalid public LAN anchor")
		}
		genesis, anchor = bound.Genesis, bound.GenesisHash
		validators = make([]cmted.PrivKey, 4)
		for i := range validators {
			// Disposable publicly documented test derivation; never an owner key.
			seed := sha256.Sum256([]byte("GG public conflict validator " + strconv.Itoa(i)))
			validators[i] = cmted.PrivKey(ed25519.NewKeyFromSeed(seed[:]))
			public := hex.EncodeToString(validators[i].PubKey().Bytes())
			found := false
			for _, member := range genesis.Validators {
				found = found || member == public
			}
			if !found {
				t.Fatal("conflict fixture validator context")
			}
		}
	}
	state := initialState(genesis, anchor)
	firstHeader := signedFixture(genesis, validators, 1, state.StateRoot, nil, types.BlockID{})
	secondHeader := signedFixture(genesis, validators, 1, state.StateRoot, types.Txs{types.Tx("public conflicting block fixture")}, types.BlockID{})
	firstRaw, _ := cmtjson.Marshal(firstHeader)
	secondRaw, _ := cmtjson.Marshal(secondHeader)
	first := VerifyInput{Schema: "gg.consensus.proof.v1", Genesis: genesis, GenesisHash: anchor, State: state, SignedHeader: firstRaw}
	second := first
	second.SignedHeader = secondRaw
	if bytes.Equal(firstHeader.Commit.BlockID.Hash, secondHeader.Commit.BlockID.Hash) {
		t.Fatal("fixture blocks do not conflict")
	}
	for _, packet := range []VerifyInput{first, second} {
		if _, err := verifyInput(packet); err != nil {
			t.Fatal("real signed conflict certificate failed SDK", err)
		}
	}
	firstHeader.Commit.Signatures[3] = types.NewCommitSigAbsent()
	variantRaw, _ := cmtjson.Marshal(firstHeader)
	variant := first
	variant.SignedHeader = variantRaw
	if _, err := verifyInput(variant); err != nil {
		t.Fatal("same block with three signatures rejected", err)
	}
	if path := os.Getenv("GG_PUBLIC_CERTIFIED_CONFLICT_FIXTURE"); path != "" {
		if err := os.WriteFile(path, canonical(map[string]VerifyInput{"first": first, "second": second, "variant": variant}), 0600); err != nil {
			t.Fatal(err)
		}
	}
}

func TestDagCertifiedMembershipUsesSDKQuorumWithoutClaimingLocalExecution(t *testing.T) {
	input := dagCertifiedFixture(t)
	result, err := verifyInput(input)
	if err != nil || result["dag_account_proof_verified"] != true || result["dag_block_proof_verified"] != true || result["execution_status_verified"] != false ||
		result["dag_asset_mode"] != "PRODUCER_OWNED_NONFINANCIAL" {
		t.Fatal("certified membership mislabeled or rejected", err)
	}
	// Optional test-only export is public material; synthetic private keys
	// remain inside the fixture constructor. The runner owns the destination.
	if path := os.Getenv("GG_PUBLIC_DAG_CERTIFIED_FIXTURE_PATH"); path != "" {
		if err := os.WriteFile(path, canonical(input), 0600); err != nil {
			t.Fatal(err)
		}
	}
	var header types.SignedHeader
	if cmtjson.Unmarshal(input.SignedHeader, &header) != nil {
		t.Fatal("invalid header fixture")
	}
	header.Commit.Signatures[3] = types.NewCommitSigAbsent()
	input.SignedHeader, _ = cmtjson.Marshal(header)
	if _, err := verifyInput(input); err != nil {
		t.Fatal("three-validator certificate rejected", err)
	}
	header.Commit.Signatures[2] = types.NewCommitSigAbsent()
	input.SignedHeader, _ = cmtjson.Marshal(header)
	if _, err := verifyInput(input); err == nil {
		t.Fatal("two-validator certificate accepted")
	}
}

func TestDagCertifiedProofRejectsChangedContextLeafDirectionsAndCommittee(t *testing.T) {
	input := dagCertifiedFixture(t)
	for _, mutation := range []string{"account", "nonce", "index", "direction", "odd_duplicate", "long_path", "block", "block_index", "producer", "commitment", "height", "root", "committee", "source"} {
		t.Run(mutation, func(t *testing.T) {
			var changed VerifyInput
			if json.Unmarshal(canonical(input), &changed) != nil {
				t.Fatal("fixture clone")
			}
			switch mutation {
			case "account":
				changed.DAGAccountProof.Leaf.Balance = "0"
			case "nonce":
				changed.DAGAccountProof.Leaf.Nonce++
			case "index":
				changed.DAGAccountProof.Index--
			case "direction":
				changed.DAGAccountProof.Path[0].Side = "right"
			case "odd_duplicate":
				changed.DAGAccountProof.Path[1].Hash = strings.Repeat("f", 64)
			case "long_path":
				changed.DAGAccountProof.Path = append(changed.DAGAccountProof.Path, changed.DAGAccountProof.Path[0])
			case "block":
				changed.DAGBlockProof.Leaf.Hash = strings.Repeat("d", 64)
			case "block_index":
				changed.DAGBlockProof.Leaf.Index--
			case "producer":
				changed.DAGBlockProof.Leaf.Producer = 6
			case "commitment":
				changed.DAGBlockProof.Commitment.Transactions++
			case "height":
				changed.DAGAccountProof.Height++
			case "root":
				changed.State.DAG.OrderRoot = strings.Repeat("e", 64)
				sealState(&changed.State)
			case "committee":
				changed.Genesis.Validators[0] = changed.Genesis.Accounts[0]
				changed.GenesisHash = hashHex(canonical(changed.Genesis))
			case "source":
				changed.Genesis.DAG.NetworkID = strings.Repeat("e", 64)
				changed.GenesisHash = hashHex(canonical(changed.Genesis))
			}
			if _, err := verifyInput(changed); err == nil {
				t.Fatal("changed certified DAG proof accepted")
			}
		})
	}
}

func TestDagProofQueriesCoverOddTreesAndHistoricalStates(t *testing.T) {
	app, keys, _ := dagLedgerFixture(t)
	ctx := context.Background()
	for height := int64(1); height <= 3; height++ {
		batch := dagBatchWire(t, app.dag, dagWire(t, app.dag, keys, 0, 1))
		if _, err := app.FinalizeBlock(ctx, &abci.RequestFinalizeBlock{Height: height, Time: time.Unix(1700000001+height, 0), Txs: [][]byte{batch}}); err != nil {
			t.Fatal(err)
		}
		if _, err := app.Commit(ctx, &abci.RequestCommit{}); err != nil {
			t.Fatal(err)
		}
	}
	for _, height := range []int64{1, 2, 3} {
		state, _ := app.stateAt(height)
		for _, address := range app.genesis.DAG.Accounts {
			response, _ := app.Query(ctx, &abci.RequestQuery{Path: "/gg/dag/account-proof", Data: []byte(address), Height: height})
			var proof DagAccountProof
			if response.Code != 0 || decodeStrict(response.Value, &proof) != nil || verifyDagAccountProof(proof, state, *app.genesis.DAG) != nil {
				t.Fatal("historical DAG account witness failed", height)
			}
		}
		for _, block := range orderFixture(t, app.dag)[:int(height)] {
			response, _ := app.Query(ctx, &abci.RequestQuery{Path: "/gg/dag/block-proof", Data: []byte(block.Hash), Height: height})
			var proof DagBlockProof
			if response.Code != 0 || decodeStrict(response.Value, &proof) != nil || verifyDagBlockProof(proof, state, *app.genesis.DAG) != nil {
				t.Fatal("historical DAG block witness failed", height)
			}
		}
	}
	unknown, _ := app.Query(ctx, &abci.RequestQuery{Path: "/gg/dag/block-proof", Data: []byte(strings.Repeat("f", 64))})
	if unknown.Code == 0 {
		t.Fatal("unknown block received membership witness")
	}
	// The old native-asset proof also works under v2. Its embedded optional
	// commitment must be compared by value rather than Go pointer identity.
	native, _ := app.Query(ctx, &abci.RequestQuery{Path: "/gg/proof", Data: []byte(app.state.Accounts[0].Address)})
	var proof Proof
	if json.Unmarshal(native.Value, &proof) != nil || verifyAccountProof(proof, app.state) != nil {
		t.Fatal("native asset witness broke under DAG v2")
	}
}

func TestDagCertifiedRootDoesNotInventAccountOrBlockMembership(t *testing.T) {
	input := dagCertifiedFixture(t)
	input.DAGAccountProof = nil
	input.DAGBlockProof = nil
	result, err := verifyInput(input)
	if err != nil || result["dag_account_proof_verified"] != false || result["dag_block_proof_verified"] != false || result["execution_status_verified"] != false {
		t.Fatal("certificate alone invented local evidence", err)
	}
	if !bytes.Equal(canonical(result["dag_commitment"]), canonical(input.State.DAG)) {
		t.Fatal("verifier omitted the exact certified DAG context")
	}
}

func TestDagStateRejectsImpossibleCheckpointHeightAndTransactionCounts(t *testing.T) {
	input := dagCertifiedFixture(t)
	state := copyState(input.State)
	state.Height = 0
	if validateState(state, input.Genesis, input.GenesisHash) == nil {
		t.Fatal("checkpoint newer than native execution height accepted")
	}
	state = copyState(input.State)
	state.DAG.Transactions = uint64(state.DAG.Blocks)*DagMaxBlockTransactions + 1
	sealState(&state)
	if validateState(state, input.Genesis, input.GenesisHash) == nil {
		t.Fatal("transaction count exceeds actual per-block bound")
	}
}
