//go:build gg_public_fixture

package main

import (
	"context"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"strings"
	"testing"

	abci "github.com/cometbft/cometbft/abci/types"
	cmted "github.com/cometbft/cometbft/crypto/ed25519"
	cmtjson "github.com/cometbft/cometbft/libs/json"
	"github.com/cometbft/cometbft/types"
)

// Compiled only in a scratch native test module. Outputs public certified data;
// the synthetic account/validator private keys never leave the fixture builder.
func TestExportWasmFixture(t *testing.T) {
	input := publicFixture(t)
	app := &Ledger{state: input.State, history: []State{input.State}}
	response, err := app.Query(context.Background(), &abci.RequestQuery{Path: "/gg/proof", Data: []byte(input.State.Accounts[0].Address)})
	if err != nil || response.Code != 0 {
		t.Fatal("fixture query")
	}
	input.AccountProof = &Proof{}
	if json.Unmarshal(response.Value, input.AccountProof) != nil {
		t.Fatal("fixture witness")
	}
	fmt.Println("GG_PUBLIC_FIXTURE " + base64.StdEncoding.EncodeToString(canonical(input)))
	// A second internally valid chain controlled by four different validators.
	// Its proof must be rejected under the original session pin, regardless of
	// how correctly its own chosen validators sign it.
	genesis, _, accounts, _ := testGenesis()
	genesis.ChainID = "ggnet:" + strings.Repeat("f", 24)
	validators := make([]cmted.PrivKey, 4)
	for i := range validators {
		seed := sha256.Sum256([]byte("foreign-synthetic-validator-" + string(rune('a'+i))))
		validators[i] = cmted.PrivKey(ed25519.NewKeyFromSeed(seed[:]))
		genesis.Validators[i] = hex.EncodeToString(validators[i].PubKey().Bytes())
	}
	anchor := hashHex(canonical(genesis))
	before := initialState(genesis, anchor)
	raw := testTx(genesis, anchor, accounts, 0, 1, "1000000", 0)
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
	foreign := VerifyInput{Schema: "gg.consensus.proof.v1", Genesis: genesis, GenesisHash: anchor, SignedHeader: headerJSON,
		State: after, TxHeader: txHeaderJSON, TxProof: proofJSON, ExpectedTxHash: hashHex(raw),
		BeforeState: &before, BlockTxs: []string{base64.StdEncoding.EncodeToString(raw)}}
	if _, err := verifyInput(foreign); err != nil {
		t.Fatal("foreign synthetic fixture must be cryptographically valid")
	}
	fmt.Println("GG_FOREIGN_FIXTURE " + base64.StdEncoding.EncodeToString(canonical(foreign)))
}
