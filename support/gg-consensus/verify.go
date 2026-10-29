package main

import (
	"bytes"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"strings"

	cmtjson "github.com/cometbft/cometbft/libs/json"
	"github.com/cometbft/cometbft/types"
)

type VerifyInput struct {
	Schema         string          `json:"schema"`
	Genesis        Genesis         `json:"genesis"`
	GenesisHash    string          `json:"genesis_hash"`
	SignedHeader   json.RawMessage `json:"signed_header"`
	State          State           `json:"state"`
	AccountProof   *Proof          `json:"account_proof,omitempty"`
	TxHeader       json.RawMessage `json:"tx_header,omitempty"`
	TxProof        json.RawMessage `json:"tx_proof,omitempty"`
	ExpectedTxHash string          `json:"expected_tx_hash,omitempty"`
	BeforeState    *State          `json:"before_state,omitempty"`
	BlockTxs       []string        `json:"block_txs,omitempty"`
}

func verifyHeader(raw []byte, genesis Genesis) (*types.SignedHeader, error) {
	if len(raw) == 0 || len(raw) > 64*1024 {
		return nil, errors.New("GG_HEADER_SIZE")
	}
	var header types.SignedHeader
	if cmtjson.Unmarshal(raw, &header) != nil || header.ValidateBasic(genesis.ChainID) != nil {
		return nil, errors.New("GG_HEADER_INVALID")
	}
	validators := validatorSet(genesis)
	if !bytes.Equal(header.ValidatorsHash, validators.Hash()) || !bytes.Equal(header.NextValidatorsHash, validators.Hash()) {
		return nil, errors.New("GG_HEADER_VALIDATORS")
	}
	if validators.VerifyCommitLight(genesis.ChainID, header.Commit.BlockID, header.Height, header.Commit) != nil {
		return nil, errors.New("GG_HEADER_QUORUM")
	}
	return &header, nil
}

func verifyAccountProof(proof Proof, state State) error {
	if proof.Schema != "gg.native.proof.v1" || proof.Height != state.Height || proof.ChainID != state.ChainID ||
		proof.GenesisHash != state.GenesisHash || proof.AccountRoot != state.AccountRoot || proof.StateRoot != state.StateRoot ||
		proof.Commitment != commitmentFor(state) || len(proof.Path) != 2 {
		return errors.New("GG_ACCOUNT_PROOF_CONTEXT")
	}
	member := false
	for _, account := range state.Accounts {
		if account == proof.Leaf {
			member = true
		}
	}
	if !member {
		return errors.New("GG_ACCOUNT_PROOF_LEAF")
	}
	value := hashHex(append([]byte{0}, canonical(proof.Leaf)...))
	for _, step := range proof.Path {
		if !pubPattern.MatchString(step.Hash) {
			return errors.New("GG_ACCOUNT_PROOF_HASH")
		}
		left, right := value, step.Hash
		if step.Side == "left" {
			left, right = step.Hash, value
		} else if step.Side != "right" {
			return errors.New("GG_ACCOUNT_PROOF_SIDE")
		}
		a, _ := hex.DecodeString(left)
		b, _ := hex.DecodeString(right)
		raw := append([]byte{1}, a...)
		raw = append(raw, b...)
		value = hashHex(raw)
	}
	if value != state.AccountRoot {
		return errors.New("GG_ACCOUNT_PROOF_ROOT")
	}
	return nil
}

func verifyInput(input VerifyInput) (map[string]any, error) {
	if input.Schema != "gg.consensus.proof.v1" || validateGenesis(input.Genesis, input.GenesisHash) != nil ||
		validateState(input.State, input.Genesis, input.GenesisHash) != nil {
		return nil, errors.New("GG_PROOF_CONTEXT")
	}
	header, err := verifyHeader(input.SignedHeader, input.Genesis)
	if err != nil {
		return nil, err
	}
	if input.State.Height+1 != header.Height || hex.EncodeToString(header.AppHash) != input.State.StateRoot {
		return nil, errors.New("GG_CERTIFIED_STATE_ROOT")
	}
	if input.AccountProof != nil {
		if err := verifyAccountProof(*input.AccountProof, input.State); err != nil {
			return nil, err
		}
	}
	transactionVerified := false
	executionVerified := false
	txHeight := int64(0)
	if len(input.TxHeader) > 0 || len(input.TxProof) > 0 || input.ExpectedTxHash != "" {
		expected := strings.ToLower(input.ExpectedTxHash)
		if !pubPattern.MatchString(expected) {
			return nil, errors.New("GG_TX_PROOF_HASH")
		}
		txHeader, err := verifyHeader(input.TxHeader, input.Genesis)
		if err != nil {
			return nil, err
		}
		if txHeader.Height+1 != header.Height {
			return nil, errors.New("GG_TX_PROOF_HEIGHT")
		}
		if !bytes.Equal(header.LastBlockID.Hash, txHeader.Commit.BlockID.Hash) ||
			header.LastBlockID.PartSetHeader.Total != txHeader.Commit.BlockID.PartSetHeader.Total ||
			!bytes.Equal(header.LastBlockID.PartSetHeader.Hash, txHeader.Commit.BlockID.PartSetHeader.Hash) {
			return nil, errors.New("GG_TX_PROOF_PARENT")
		}
		var proof types.TxProof
		if cmtjson.Unmarshal(input.TxProof, &proof) != nil || proof.Validate(txHeader.DataHash) != nil || hashHex(proof.Data) != expected {
			return nil, errors.New("GG_TX_INCLUSION_PROOF")
		}
		if _, err := parseEnvelope(proof.Data, input.Genesis, input.GenesisHash); err != nil {
			return nil, errors.New("GG_TX_PROOF_SIGNATURE")
		}
		transactionVerified = true
		txHeight = txHeader.Height
		if input.BeforeState != nil || input.BlockTxs != nil {
			if input.BeforeState == nil || validateState(*input.BeforeState, input.Genesis, input.GenesisHash) != nil ||
				input.BeforeState.Height+1 != txHeader.Height || hex.EncodeToString(txHeader.AppHash) != input.BeforeState.StateRoot ||
				len(input.BlockTxs) == 0 || len(input.BlockTxs) > MaxBlockTxs {
				return nil, errors.New("GG_EXECUTION_CONTEXT")
			}
			state := copyState(*input.BeforeState)
			transactions := make(types.Txs, len(input.BlockTxs))
			total := 0
			found := 0
			for i, encoded := range input.BlockTxs {
				raw, err := base64.StdEncoding.DecodeString(encoded)
				total += len(raw)
				if err != nil || len(raw) > MaxTxBytes || total > 64*1024 {
					return nil, errors.New("GG_EXECUTION_TX_LIMIT")
				}
				transactions[i] = raw
				envelope, err := parseEnvelope(raw, input.Genesis, input.GenesisHash)
				if err != nil || applyEnvelope(&state, envelope, false) != nil {
					return nil, errors.New("GG_EXECUTION_TX")
				}
				if hashHex(raw) == expected {
					found++
				}
			}
			if found != 1 || !bytes.Equal(transactions.Hash(), txHeader.DataHash) {
				return nil, errors.New("GG_EXECUTION_DATA_ROOT")
			}
			state.Height = txHeader.Height
			sealState(&state)
			if state.StateRoot != input.State.StateRoot || !bytes.Equal(canonical(state.Accounts), canonical(input.State.Accounts)) {
				return nil, errors.New("GG_EXECUTION_STATE_ROOT")
			}
			executionVerified = true
		}
	}
	if !transactionVerified && (input.BeforeState != nil || input.BlockTxs != nil) {
		return nil, errors.New("GG_EXECUTION_WITHOUT_TX_PROOF")
	}
	return map[string]any{"verified": true, "schema": "gg.consensus.proof-result.v1", "chain_id": input.Genesis.ChainID,
		"state_height": input.State.Height, "certificate_height": header.Height, "state_root": input.State.StateRoot,
		"account_root": input.State.AccountRoot, "validator_count": 4, "quorum_required": 3,
		"transaction_inclusion_verified": transactionVerified, "transaction_height": txHeight,
		"account_proof_verified": input.AccountProof != nil, "execution_status_verified": executionVerified}, nil
}

func runVerify(raw []byte) error {
	var input VerifyInput
	if decodeStrict(raw, &input) != nil {
		return errors.New("GG_PROOF_ENCODING")
	}
	result, err := verifyInput(input)
	if err != nil {
		return err
	}
	fmt.Println(string(canonical(result)))
	return nil
}
