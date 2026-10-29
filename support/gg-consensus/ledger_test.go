package main

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	abci "github.com/cometbft/cometbft/abci/types"
	cmted "github.com/cometbft/cometbft/crypto/ed25519"
	cmtjson "github.com/cometbft/cometbft/libs/json"
	cmtproto "github.com/cometbft/cometbft/proto/tendermint/types"
	cmtversion "github.com/cometbft/cometbft/proto/tendermint/version"
	"github.com/cometbft/cometbft/types"
	"github.com/cometbft/cometbft/version"
)

func testGenesis() (Genesis, string, []ed25519.PrivateKey, []cmted.PrivKey) {
	genesis := Genesis{ChainID: "ggnet:" + strings.Repeat("a", 24), Decimals: 6, GenesisTime: 1700000000, Schema: "gg.native.genesis.v1", SupplyAtomic: "1000000000000", Symbol: "GG-NET-TEST"}
	accounts := []ed25519.PrivateKey{}
	validators := []cmted.PrivKey{}
	for i := 0; i < 4; i++ {
		seed := sha256.Sum256([]byte("synthetic-account-fixture-" + string(rune('a'+i))))
		key := ed25519.NewKeyFromSeed(seed[:])
		accounts = append(accounts, key)
		genesis.Accounts = append(genesis.Accounts, hex.EncodeToString(key.Public().(ed25519.PublicKey)))
		seed = sha256.Sum256([]byte("synthetic-validator-fixture-" + string(rune('a'+i))))
		val := cmted.PrivKey(ed25519.NewKeyFromSeed(seed[:]))
		validators = append(validators, val)
		genesis.Validators = append(genesis.Validators, hex.EncodeToString(val.PubKey().Bytes()))
	}
	return genesis, hashHex(canonical(genesis)), accounts, validators
}

func testTx(genesis Genesis, anchor string, keys []ed25519.PrivateKey, source, target int, amount string, nonce uint64) []byte {
	body := Body{Amount: amount, ChainID: genesis.ChainID, GenesisHash: anchor, Nonce: nonce, Recipient: genesis.Accounts[target], Sender: genesis.Accounts[source], Version: 1}
	return canonical(Envelope{Body: body, Signature: hex.EncodeToString(ed25519.Sign(keys[source], canonical(body)))})
}

func TestCanonicalTransactionRejectsReplayTamperAndAmbiguousJSON(t *testing.T) {
	genesis, anchor, keys, _ := testGenesis()
	raw := testTx(genesis, anchor, keys, 0, 1, "1234567", 0)
	envelope, err := parseEnvelope(raw, genesis, anchor)
	if err != nil {
		t.Fatal(err)
	}
	state := initialState(genesis, anchor)
	if applyEnvelope(&state, envelope, false) != nil {
		t.Fatal("valid transfer rejected")
	}
	if applyEnvelope(&state, envelope, false) == nil {
		t.Fatal("nonce replay accepted")
	}
	var changed Envelope
	json.Unmarshal(raw, &changed)
	changed.Body.Amount = "1234568"
	for _, bad := range [][]byte{canonical(changed), append([]byte(" "), raw...), bytes.Replace(raw, []byte(`"nonce":0`), []byte(`"nonce":0,"nonce":0`), 1), bytes.Replace(raw, []byte(`"version":1`), []byte(`"version":1.0`), 1)} {
		if _, err := parseEnvelope(bad, genesis, anchor); err == nil {
			t.Fatalf("ambiguous/tampered input accepted")
		}
	}
	changed.Body.GenesisHash = strings.Repeat("b", 64)
	changed.Signature = hex.EncodeToString(ed25519.Sign(keys[0], canonical(changed.Body)))
	if _, err := parseEnvelope(canonical(changed), genesis, anchor); err == nil {
		t.Fatal("wrong genesis accepted")
	}
}

func TestProposalFiltersNonceConflictsAndOverspendingWithoutMutatingCommit(t *testing.T) {
	genesis, anchor, keys, _ := testGenesis()
	app, err := newLedger(genesis, anchor, t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	first := testTx(genesis, anchor, keys, 0, 1, "200000000000", 0)
	overspend := testTx(genesis, anchor, keys, 0, 2, "100000000000", 1)
	response, err := app.PrepareProposal(context.Background(), &abci.RequestPrepareProposal{MaxTxBytes: 64000, Txs: [][]byte{first, overspend, first}})
	if err != nil || len(response.Txs) != 1 {
		t.Fatal("proposal did not filter invalid remainder", err)
	}
	proposal, _ := app.ProcessProposal(context.Background(), &abci.RequestProcessProposal{Txs: [][]byte{first, overspend}})
	if proposal.Status != abci.ResponseProcessProposal_REJECT {
		t.Fatal("overspending block accepted")
	}
	if app.state.Height != 0 || app.state.StateRoot != initialState(genesis, anchor).StateRoot {
		t.Fatal("check changed committed state")
	}
	check, _ := app.CheckTx(context.Background(), &abci.RequestCheckTx{Tx: testTx(genesis, anchor, keys, 0, 1, "1", 255)})
	if check.Code != 0 {
		t.Fatal("bounded future nonce should enter mempool")
	}
	check, _ = app.CheckTx(context.Background(), &abci.RequestCheckTx{Tx: testTx(genesis, anchor, keys, 0, 1, "1", 256)})
	if check.Code == 0 {
		t.Fatal("unbounded future nonce accepted")
	}
}

func TestCommitPersistsExactPublicStateAndEmptyHeightKeepsRoot(t *testing.T) {
	genesis, anchor, keys, _ := testGenesis()
	root := t.TempDir()
	app, err := newLedger(genesis, anchor, root)
	if err != nil {
		t.Fatal(err)
	}
	first := testTx(genesis, anchor, keys, 0, 1, "1234567", 0)
	response, err := app.FinalizeBlock(context.Background(), &abci.RequestFinalizeBlock{Height: 1, Txs: [][]byte{first}})
	if err != nil || response.TxResults[0].Code != 0 {
		t.Fatal(err)
	}
	if app.state.Height != 0 {
		t.Fatal("finalize published uncommitted state")
	}
	if _, err = app.Commit(context.Background(), &abci.RequestCommit{}); err != nil {
		t.Fatal(err)
	}
	if validateState(app.state, genesis, anchor) != nil {
		t.Fatal("invalid committed state")
	}
	rootHash := app.state.StateRoot
	if _, err = app.FinalizeBlock(context.Background(), &abci.RequestFinalizeBlock{Height: 2}); err != nil {
		t.Fatal(err)
	}
	if _, err = app.Commit(context.Background(), &abci.RequestCommit{}); err != nil {
		t.Fatal(err)
	}
	if app.state.StateRoot != rootHash {
		t.Fatal("empty block height changed state commitment")
	}
	reloaded, err := newLedger(genesis, anchor, root)
	if err != nil || reloaded.state.Height != 2 || reloaded.state.StateRoot != rootHash {
		t.Fatal("public state restart failed", err)
	}
	proof, _ := app.Query(context.Background(), &abci.RequestQuery{Path: "/gg/proof", Data: []byte(genesis.Accounts[0]), Height: 1})
	var accountProof Proof
	if json.Unmarshal(proof.Value, &accountProof) != nil || verifyAccountProof(accountProof, app.history[1]) != nil {
		t.Fatal("historical membership proof failed")
	}
	for _, entry := range mustReadDir(t, root) {
		if strings.Contains(entry.Name(), "key") {
			t.Fatal("private-key file created")
		}
	}
}

func mustReadDir(t *testing.T, path string) []os.DirEntry {
	t.Helper()
	rows, err := os.ReadDir(path)
	if err != nil {
		t.Fatal(err)
	}
	return rows
}

func TestInvalidSavedStateFailsClosed(t *testing.T) {
	genesis, anchor, _, _ := testGenesis()
	root := t.TempDir()
	state := initialState(genesis, anchor)
	state.Accounts[0].Balance = "0"
	os.WriteFile(filepath.Join(root, "gg-public-state.json"), canonical(persisted{GenesisHash: anchor, History: []State{state}, Schema: "gg.native.public-history.v1"}), 0600)
	if _, err := newLedger(genesis, anchor, root); err == nil {
		t.Fatal("corrupt public state accepted")
	}
}

func TestUpstreamSignerSurvivesRestartWithoutKeyFileAndRejectsDoubleSign(t *testing.T) {
	genesis, _, _, keys := testGenesis()
	root := t.TempDir()
	path := filepath.Join(root, "priv_validator_state.json")
	pv, err := newSafePV(keys[0], path, genesis.ChainID)
	if err != nil {
		t.Fatal(err)
	}
	block := types.BlockID{Hash: bytes.Repeat([]byte{1}, 32), PartSetHeader: types.PartSetHeader{Total: 1, Hash: bytes.Repeat([]byte{2}, 32)}}
	vote := &cmtproto.Vote{Type: cmtproto.PrevoteType, Height: 1, Round: 0, BlockID: block.ToProto(), Timestamp: time.Unix(1700000000, 0)}
	if err := pv.SignVote(genesis.ChainID, vote); err != nil {
		t.Fatal(err)
	}
	signature := append([]byte(nil), vote.Signature...)
	reloaded, err := newSafePV(keys[0], path, genesis.ChainID)
	if err != nil {
		t.Fatal(err)
	}
	if err := reloaded.SignVote(genesis.ChainID, vote); err != nil || !bytes.Equal(signature, vote.Signature) {
		t.Fatal("same HRS signature not reused", err)
	}
	vote.BlockID.Hash[0] = 3
	if err := reloaded.SignVote(genesis.ChainID, vote); err == nil {
		t.Fatal("conflicting same HRS vote signed")
	}
	if err := reloaded.SignVote("foreign-chain", vote); err == nil {
		t.Fatal("foreign chain signed")
	}
	files := mustReadDir(t, root)
	if len(files) != 1 || files[0].Name() != "priv_validator_state.json" {
		t.Fatal("unexpected signer file")
	}
	raw, _ := os.ReadFile(path)
	if bytes.Contains(raw, []byte(hex.EncodeToString(keys[0]))) || bytes.Contains(raw, []byte(base64.StdEncoding.EncodeToString(keys[0]))) {
		t.Fatal("private key written to sign state")
	}
}

func signedFixture(genesis Genesis, keys []cmted.PrivKey, height int64, appHash string, txs types.Txs, parent types.BlockID) *types.SignedHeader {
	validators := validatorSet(genesis)
	application, _ := hex.DecodeString(appHash)
	header := &types.Header{Version: cmtversion.Consensus{Block: version.BlockProtocol, App: 1}, ChainID: genesis.ChainID, Height: height,
		Time: time.Unix(1700000000+height, 0).UTC(), LastBlockID: parent, DataHash: txs.Hash(), ValidatorsHash: validators.Hash(), NextValidatorsHash: validators.Hash(),
		ConsensusHash: bytes.Repeat([]byte{5}, 32), AppHash: application, ProposerAddress: validators.Validators[0].Address}
	block := types.BlockID{Hash: header.Hash(), PartSetHeader: types.PartSetHeader{Total: 1, Hash: bytes.Repeat([]byte{7}, 32)}}
	signatures := make([]types.CommitSig, 4)
	for i, validator := range validators.Validators {
		var key cmted.PrivKey
		for _, candidate := range keys {
			if bytes.Equal(candidate.PubKey().Address(), validator.Address) {
				key = candidate
			}
		}
		vote := &cmtproto.Vote{Type: cmtproto.PrecommitType, Height: height, Round: 0, BlockID: block.ToProto(), Timestamp: header.Time, ValidatorAddress: validator.Address, ValidatorIndex: int32(i)}
		signature, _ := key.Sign(types.VoteSignBytes(genesis.ChainID, vote))
		signatures[i] = types.CommitSig{BlockIDFlag: types.BlockIDFlagCommit, ValidatorAddress: validator.Address, Timestamp: header.Time, Signature: signature}
	}
	return &types.SignedHeader{Header: header, Commit: &types.Commit{Height: height, Round: 0, BlockID: block, Signatures: signatures}}
}

func publicFixture(t *testing.T) VerifyInput {
	t.Helper()
	genesis, anchor, keys, validators := testGenesis()
	before := initialState(genesis, anchor)
	raw := testTx(genesis, anchor, keys, 0, 1, "1234567", 0)
	envelope, _ := parseEnvelope(raw, genesis, anchor)
	after := copyState(before)
	applyEnvelope(&after, envelope, false)
	after.Height = 1
	sealState(&after)
	txs := types.Txs{raw}
	txHeader := signedFixture(genesis, validators, 1, before.StateRoot, txs, types.BlockID{})
	header := signedFixture(genesis, validators, 2, after.StateRoot, nil, txHeader.Commit.BlockID)
	headerJSON, _ := cmtjson.Marshal(header)
	txHeaderJSON, _ := cmtjson.Marshal(txHeader)
	proofJSON, _ := cmtjson.Marshal(txs.Proof(0))
	return VerifyInput{Schema: "gg.consensus.proof.v1", Genesis: genesis, GenesisHash: anchor, SignedHeader: headerJSON, State: after,
		TxHeader: txHeaderJSON, TxProof: proofJSON, ExpectedTxHash: hashHex(raw), BeforeState: &before, BlockTxs: []string{base64.StdEncoding.EncodeToString(raw)}}
}

func TestSDKCertifiedProofVerifiesExecutionFromTwoAdjacentCommits(t *testing.T) {
	input := publicFixture(t)
	result, err := verifyInput(input)
	if err != nil || result["verified"] != true || result["execution_status_verified"] != true {
		t.Fatal("valid SDK proof rejected", err)
	}
	var header types.SignedHeader
	cmtjson.Unmarshal(input.SignedHeader, &header)
	header.Commit.Signatures[3] = types.NewCommitSigAbsent()
	input.SignedHeader, _ = cmtjson.Marshal(header)
	if _, err := verifyInput(input); err != nil {
		t.Fatal("3/4 quorum rejected", err)
	}
	header.Commit.Signatures[2] = types.NewCommitSigAbsent()
	input.SignedHeader, _ = cmtjson.Marshal(header)
	if _, err := verifyInput(input); err == nil {
		t.Fatal("2/4 quorum accepted")
	}
}

func TestSDKProofRejectsForgedHeadersRootsTransactionsAndState(t *testing.T) {
	for _, mutation := range []string{"header", "state", "genesis", "signature", "tx", "before", "parent", "validator"} {
		t.Run(mutation, func(t *testing.T) {
			input := publicFixture(t)
			switch mutation {
			case "header":
				var h types.SignedHeader
				cmtjson.Unmarshal(input.SignedHeader, &h)
				h.Height++
				input.SignedHeader, _ = cmtjson.Marshal(h)
			case "state":
				input.State.Accounts[0].Balance = "0"
			case "genesis":
				input.Genesis.Decimals = 9
			case "signature":
				var h types.SignedHeader
				cmtjson.Unmarshal(input.SignedHeader, &h)
				h.Commit.Signatures[0].Signature[0] ^= 1
				h.Commit.Signatures[1].Signature[0] ^= 1
				input.SignedHeader, _ = cmtjson.Marshal(h)
			case "tx":
				input.BlockTxs[0] = base64.StdEncoding.EncodeToString([]byte("invalid"))
			case "before":
				input.BeforeState.Height++
			case "parent":
				var h types.SignedHeader
				cmtjson.Unmarshal(input.TxHeader, &h)
				h.Commit.BlockID.PartSetHeader.Hash[0] ^= 1
				input.TxHeader, _ = cmtjson.Marshal(h)
			case "validator":
				input.Genesis.Validators[0] = input.Genesis.Accounts[0]
				input.GenesisHash = hashHex(canonical(input.Genesis))
			}
			if _, err := verifyInput(input); err == nil {
				t.Fatal("forged proof accepted")
			}
		})
	}
}

func TestMerkleWitnessRejectsChangedLeafSideAndRoot(t *testing.T) {
	genesis, anchor, _, _ := testGenesis()
	app, _ := newLedger(genesis, anchor, t.TempDir())
	response, _ := app.Query(context.Background(), &abci.RequestQuery{Path: "/gg/proof", Data: []byte(genesis.Accounts[0])})
	var proof Proof
	json.Unmarshal(response.Value, &proof)
	if verifyAccountProof(proof, app.state) != nil {
		t.Fatal("valid account proof rejected")
	}
	proof.Leaf.Balance = "0"
	if verifyAccountProof(proof, app.state) == nil {
		t.Fatal("changed leaf accepted")
	}
	json.Unmarshal(response.Value, &proof)
	proof.Path[0].Side = "diagonal"
	if verifyAccountProof(proof, app.state) == nil {
		t.Fatal("changed side accepted")
	}
	json.Unmarshal(response.Value, &proof)
	proof.Path[1].Hash = strings.Repeat("0", 64)
	if verifyAccountProof(proof, app.state) == nil {
		t.Fatal("changed sibling accepted")
	}
}
