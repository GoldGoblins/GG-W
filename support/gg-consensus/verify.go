package main

import (
	"bytes"
	"context"
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
	committeeTrust            *verifiedCommitteeTrust
	CommitteeTransitions      []financialCommitteeTransition `json:"committee_transitions,omitempty"`
	CommitteeTrustPath        string                         `json:"committee_trust_path,omitempty"`
	Schema                    string                         `json:"schema"`
	Genesis                   Genesis                        `json:"genesis"`
	GenesisHash               string                         `json:"genesis_hash"`
	SignedHeader              json.RawMessage                `json:"signed_header"`
	State                     State                          `json:"state"`
	AccountProof              *Proof                         `json:"account_proof,omitempty"`
	DAGAccountProof           *DagAccountProof               `json:"dag_account_proof,omitempty"`
	DAGBlockProof             *DagBlockProof                 `json:"dag_block_proof,omitempty"`
	DAGOrderPage              *DagOrderPage                  `json:"dag_order_page,omitempty"`
	DAGSegmentedAccountProof  *dagSegmentedAccountProof      `json:"dag_segmented_account_proof,omitempty"`
	DAGSegmentedBlockProof    *dagSegmentedBlockProof        `json:"dag_segmented_block_proof,omitempty"`
	DAGSegmentedOrderPage     *dagSegmentedOrderPage         `json:"dag_segmented_order_page,omitempty"`
	DAGSegmentedBaseProof     *dagSegmentedBaseProof         `json:"dag_segmented_base_proof,omitempty"`
	DAGSegmentedClosedPage    *dagSegmentedClosedPage        `json:"dag_segmented_closed_page,omitempty"`
	FinancialReceipt          *financialCertifiedReceipt     `json:"financial_receipt,omitempty"`
	ExpectedFinancialReceipt  *financialReceiptExpectation   `json:"expected_financial_receipt,omitempty"`
	FinancialProducer         *financialProducerContext      `json:"financial_producer,omitempty"`
	FinancialAccount          *financialCertifiedAccount     `json:"financial_account,omitempty"`
	ExpectedFinancialAccount  string                         `json:"expected_financial_account,omitempty"`
	FinancialRegistry         *financialCertifiedRegistry    `json:"financial_registry,omitempty"`
	ExpectedFinancialRegistry *protocolRegistrySelector      `json:"expected_financial_registry,omitempty"`
	FinancialBlock            *financialCertifiedBlock       `json:"financial_block,omitempty"`
	ExpectedFinancialBlock    string                         `json:"expected_financial_block,omitempty"`
	FinancialReward           *financialCertifiedReward      `json:"financial_reward,omitempty"`
	ExpectedFinancialReward   *protocolRewardSelector        `json:"expected_financial_reward,omitempty"`
	TxHeader                  json.RawMessage                `json:"tx_header,omitempty"`
	TxProof                   json.RawMessage                `json:"tx_proof,omitempty"`
	ExpectedTxHash            string                         `json:"expected_tx_hash,omitempty"`
	BeforeState               *State                         `json:"before_state,omitempty"`
	BlockTxs                  []string                       `json:"block_txs,omitempty"`
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
		!bytes.Equal(canonical(proof.Commitment), canonical(commitmentFor(state))) || len(proof.Path) != 2 {
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
	header, _, err := verifyFinancialCertificate(input)
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
	if input.FinancialReceipt != nil && checkFinancialCertifiedReceipt(*input.FinancialReceipt, input.State, input.Genesis) != nil {
		return nil, errFinancialReceipt
	}
	if input.FinancialReceipt == nil && input.ExpectedFinancialReceipt != nil || input.FinancialReceipt != nil && publicFinancialProtocol(input.Genesis) && input.ExpectedFinancialReceipt == nil {
		return nil, errFinancialReceipt
	}
	if expected := input.ExpectedFinancialReceipt; expected != nil {
		proof := input.FinancialReceipt
		if !pubPattern.MatchString(expected.TransactionID) || proof.Receipt.Leaf.TransactionID != expected.TransactionID ||
			expected.Block != "" && (!pubPattern.MatchString(expected.Block) || proof.Context.BlockHash != expected.Block) ||
			expected.Index != nil && (*expected.Index < 0 || *expected.Index >= financialMaxTransactions || proof.Receipt.Leaf.Index != *expected.Index) {
			return nil, errFinancialReceipt
		}
	}
	if input.FinancialProducer != nil && checkFinancialProducerContext(*input.FinancialProducer, input.State, input.Genesis) != nil {
		return nil, errFinancialProducer
	}
	var financialAccount Account
	financialAccountExists := false
	if input.FinancialAccount == nil && input.ExpectedFinancialAccount != "" {
		return nil, errFinancialAccount
	}
	if input.FinancialAccount != nil {
		if !financialAccountAddress(input.ExpectedFinancialAccount) || input.ExpectedFinancialAccount != input.FinancialAccount.Proof.Address {
			return nil, errFinancialAccount
		}
		financialAccount, financialAccountExists, err = checkFinancialCertifiedAccount(context.Background(), *input.FinancialAccount, input.State, input.Genesis)
		if err != nil {
			return nil, err
		}
	}
	var registryValue []byte
	registryExists := false
	if (input.FinancialRegistry == nil) != (input.ExpectedFinancialRegistry == nil) {
		return nil, errFinancialProtocol
	}
	if input.FinancialRegistry != nil {
		registryValue, registryExists, err = checkFinancialCertifiedRegistry(context.Background(), *input.FinancialRegistry, input.State, input.Genesis, *input.ExpectedFinancialRegistry)
		if err != nil {
			return nil, err
		}
	}
	if (input.FinancialBlock == nil) != (input.ExpectedFinancialBlock == "") {
		return nil, errFinancialReceipt
	}
	if input.FinancialBlock != nil && checkFinancialCertifiedBlock(*input.FinancialBlock, input.State, input.Genesis, input.ExpectedFinancialBlock) != nil {
		return nil, errFinancialReceipt
	}
	if (input.FinancialReward == nil) != (input.ExpectedFinancialReward == nil) {
		return nil, errFinancialProtocol
	}
	if input.FinancialReward != nil && checkFinancialCertifiedReward(context.Background(), *input.FinancialReward, input.State, input.Genesis, *input.ExpectedFinancialReward) != nil {
		return nil, errFinancialProtocol
	}
	if input.DAGAccountProof != nil {
		if input.Genesis.DAG == nil || verifyDagAccountProof(*input.DAGAccountProof, input.State, *input.Genesis.DAG) != nil {
			return nil, errors.New("GG_CERTIFIED_DAG_ACCOUNT_PROOF")
		}
	}
	if input.DAGBlockProof != nil {
		if input.Genesis.DAG == nil || verifyDagBlockProof(*input.DAGBlockProof, input.State, *input.Genesis.DAG) != nil {
			return nil, errors.New("GG_CERTIFIED_DAG_BLOCK_PROOF")
		}
	}
	if input.DAGOrderPage != nil {
		if input.Genesis.DAG == nil || verifyDagOrderPage(*input.DAGOrderPage, input.State, *input.Genesis.DAG) != nil {
			return nil, errors.New("GG_CERTIFIED_DAG_ORDER_PAGE")
		}
	}
	if input.DAGSegmentedAccountProof != nil {
		if input.Genesis.DAGSegmented == nil || verifySegmentedAccountProof(*input.DAGSegmentedAccountProof, input.State, *input.Genesis.DAGSegmented) != nil {
			return nil, errDagSegmentProof
		}
	}
	if input.DAGSegmentedBlockProof != nil {
		if input.Genesis.DAGSegmented == nil || verifySegmentedBlockProof(*input.DAGSegmentedBlockProof, input.State, *input.Genesis.DAGSegmented) != nil {
			return nil, errDagSegmentProof
		}
	}
	if input.DAGSegmentedOrderPage != nil {
		if input.Genesis.DAGSegmented == nil || verifySegmentedOrderPage(*input.DAGSegmentedOrderPage, input.State, *input.Genesis.DAGSegmented) != nil {
			return nil, errDagSegmentProof
		}
	}
	transactionVerified := false
	if input.DAGSegmentedClosedPage != nil {
		if input.Genesis.DAGSegmented == nil || verifySegmentedClosedPage(*input.DAGSegmentedClosedPage, input.State, *input.Genesis.DAGSegmented) != nil {
			return nil, errDagClosedProof
		}
	}
	var epochBase *dagVerifiedEpochBase
	if input.DAGSegmentedBaseProof != nil {
		if input.Genesis.DAGSegmented == nil {
			return nil, errDagSegmentedBaseProof
		}
		epochBase, err = verifySegmentedBaseProof(*input.DAGSegmentedBaseProof, input.State, *input.Genesis.DAGSegmented)
		if err != nil {
			return nil, err
		}
	}
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
	result := map[string]any{"verified": true, "schema": "gg.consensus.proof-result.v1", "chain_id": input.Genesis.ChainID,
		"state_height": input.State.Height, "certificate_height": header.Height, "state_root": input.State.StateRoot,
		"account_root": input.State.AccountRoot, "validator_count": 4, "quorum_required": 3,
		"transaction_inclusion_verified": transactionVerified, "transaction_height": txHeight,
		"account_proof_verified": input.AccountProof != nil, "execution_status_verified": executionVerified}
	if publicFinancialProtocol(input.Genesis) {
		committee := input.State.Protocol.Committee
		if pending := input.State.Protocol.PendingCommittee; pending != nil && uint64(header.Height) >= pending.EffectiveHeight {
			committee = pending.Next
		}
		set, err := committeeValidatorSet(committee)
		if err != nil {
			return nil, err
		}
		result["validator_count"] = len(committee.Members)
		result["quorum_required"] = nil
		result["voting_power_total"] = fmt.Sprint(set.TotalVotingPower())
		result["quorum_voting_power_required"] = fmt.Sprint(set.TotalVotingPower()*2/3 + 1)
		result["committee_trust_scope"] = "PINNED_GENESIS_AND_PRECEDING_COMMITTEE_QUORUM_CERTIFICATES"
	}
	if input.State.DAG != nil {
		result["dag_commitment"] = input.State.DAG
		result["dag_asset_mode"] = "PRODUCER_OWNED_NONFINANCIAL"
		result["dag_account_proof_verified"] = input.DAGAccountProof != nil
		result["dag_block_proof_verified"] = input.DAGBlockProof != nil
		result["dag_order_page_verified"] = input.DAGOrderPage != nil
	}
	if input.State.DAGSegmented != nil {
		result["dag_segmented_commitment"] = input.State.DAGSegmented
		result["dag_asset_mode"] = "PRODUCER_OWNED_NONFINANCIAL"
		result["dag_history_policy"] = input.Genesis.DAGSegmented.Genesis.HistoryPolicy
		result["dag_history_replay_verified"] = false
		result["dag_segmented_account_proof_verified"] = input.DAGSegmentedAccountProof != nil
		result["dag_segmented_block_proof_verified"] = input.DAGSegmentedBlockProof != nil
		result["dag_segmented_order_page_verified"] = input.DAGSegmentedOrderPage != nil
		result["dag_segmented_base_proof_verified"] = epochBase != nil
		result["dag_segmented_closed_page_verified"] = input.DAGSegmentedClosedPage != nil
		if input.DAGSegmentedClosedPage != nil {
			result["dag_segmented_closed_membership_scope"] = dagClosedMembershipScope
		}
		if epochBase != nil {
			result["dag_segmented_epoch_base"] = epochBase
			result["dag_segmented_base_scope"] = dagSegmentedBaseScope
		}
		result["dag_segmented_membership_scope"] = "CERTIFIED_ACTIVE_SEGMENT_MEMBERSHIP_NOT_FULL_HISTORY_REPLAY"
		if input.DAGSegmentedAccountProof != nil {
			result["dag_segmented_account"] = input.DAGSegmentedAccountProof.Leaf
		}
		result["dag_account_proof_verified"] = false
		result["dag_block_proof_verified"] = false
		result["dag_order_page_verified"] = false
	}
	if input.State.FinancialDAG != nil {
		result["financial_dag_commitment"] = input.State.FinancialDAG
		result["dag_asset_mode"] = "NATIVE_ACCOUNT_SIGNED_PAYMENTS_FIXED_TEST_ALLOCATION"
		if generalFinancialAccounts(input.Genesis) {
			result["dag_asset_mode"] = "NATIVE_ACCOUNT_SIGNED_PAYMENTS_GENERAL_TEST_ALLOCATION"
			result["financial_account_verified"] = input.FinancialAccount != nil
			if input.FinancialAccount != nil {
				result["financial_account_address"] = input.FinancialAccount.Proof.Address
				result["financial_account_exists"] = financialAccountExists
				result["financial_account"] = nil
				if financialAccountExists {
					result["financial_account"] = financialAccountLeaf{Address: financialAccount.Address, Balance: financialAccount.Balance, Nonce: financialAccount.Nonce}
				}
				result["financial_account_scope"] = "SDK_CERTIFIED_ACCOUNT_MEMBERSHIP_OR_ABSENCE_NOT_FULL_HISTORY_REPLAY"
			}
		}
		result["financial_history_replay_verified"] = false
		if publicFinancialProtocol(input.Genesis) {
			result["dag_asset_mode"] = "NATIVE_SIGNED_PAYMENTS_CAPPED_ISSUANCE_FEES_AND_WORK"
			result["financial_block_verified"] = input.FinancialBlock != nil
			if input.FinancialBlock != nil {
				result["financial_block"] = input.FinancialBlock
				result["financial_block_scope"] = "SDK_CERTIFIED_ADMITTED_BLOCK_SUMMARY_AND_CREATOR_NOT_FULL_BLOCK_REPLAY"
			}
			result["financial_reward_verified"] = input.FinancialReward != nil
			if input.FinancialReward != nil {
				result["financial_reward_credit"] = input.FinancialReward.Credit
				result["financial_reward_index"] = fmt.Sprint(input.ExpectedFinancialReward.Index)
				result["financial_reward_epoch"] = fmt.Sprint(input.FinancialReward.Receipt.Epoch)
				result["financial_reward_scope"] = "SDK_CERTIFIED_HISTORICAL_EPOCH_CREDIT_NOT_CURRENT_SPENDABLE_BALANCE"
			}
			result["financial_registry_verified"] = input.FinancialRegistry != nil
			if input.FinancialRegistry != nil {
				result["financial_registry_namespace"] = input.ExpectedFinancialRegistry.Namespace
				result["financial_registry_key"] = input.ExpectedFinancialRegistry.Key
				result["financial_registry_exists"] = registryExists
				result["financial_registry_value"] = registryValue
				result["financial_registry_scope"] = "SDK_CERTIFIED_SELECTED_RECORD_NOT_FULL_REGISTRY_OR_HISTORY_REPLAY"
			}
		}
		result["financial_receipt_verified"] = input.FinancialReceipt != nil
		result["financial_producer_verified"] = input.FinancialProducer != nil
		if input.FinancialProducer != nil {
			proof := input.FinancialProducer
			result["financial_producer_key"] = input.Genesis.FinancialDAG.Producers[proof.Producer]
			result["financial_parent"] = proof.Parent
			result["financial_parent_rank"] = fmt.Sprint(proof.ParentRank)
			result["financial_sequence"] = fmt.Sprint(proof.Sequence)
		}
		if input.FinancialReceipt != nil {
			result["financial_receipt"] = input.FinancialReceipt.Receipt.Leaf
			result["financial_creator"] = input.FinancialReceipt.Creator
			result["financial_receipt_scope"] = "SDK_CERTIFIED_ORDERED_PAYMENT_OUTCOME_AND_CREATOR_NOT_FULL_HISTORY_REPLAY"
		}
	}
	return result, nil
}

func runVerify(raw []byte) error {
	var input VerifyInput
	// All supported public schemas have at most128 native block TXs,32
	// order witnesses,12 path siblings and64 fields per object. Reject shape
	// amplification before allocating typed proof collections.
	if decodeStrictLimited(raw, &input, MaxBlockTxs, 64) != nil {
		return errors.New("GG_PROOF_ENCODING")
	}
	if err := loadInputCommitteeTrust(&input); err != nil {
		return err
	}
	result, err := verifyInput(input)
	if err != nil {
		return err
	}
	fmt.Println(string(canonical(result)))
	return nil
}
