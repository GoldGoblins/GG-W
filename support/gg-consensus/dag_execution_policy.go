package main

import (
	"encoding/json"
	"errors"
)

// Current finite nonfinancial consensus rules. Local RAM/disk quotas are not
// consensus policy. Genesis v3 binds these exact rules before a future network
// can adopt a different history/availability model; legacy v2 is never upgraded.
const DagMaxRecords = 4095
const DagMaxWire = 32 * 1024 * 1024
const DagMaxBatchWire = 48 * 1024 * 1024
const DagMaxBatchBlocks = 128
const DagMaxBlockTransactions = 50000
const DagMaxHistoryWire = 512 * 1024 * 1024
const DagMaxParents = 7
const DagMaxRank = 4096
const DagMaxSequence = 4096

type DagExecutionPolicy struct {
	BlockParents        int    `json:"block_max_parents"`
	BlockRank           int    `json:"block_max_rank"`
	BlockSequence       uint64 `json:"block_max_sequence"`
	BlockTransactions   int    `json:"block_max_transactions"`
	BlockWire           int    `json:"block_max_wire_bytes"`
	CheckpointBlocks    int    `json:"checkpoint_max_blocks"`
	CheckpointEncoded   int    `json:"checkpoint_max_encoded_bytes"`
	CheckpointRaw       int    `json:"checkpoint_max_raw_bytes"`
	HistoryBlocks       int    `json:"history_max_blocks"`
	HistoryRaw          int    `json:"history_max_raw_bytes"`
	HistoryVerification string `json:"history_verification"`
	Profile             string `json:"profile"`
	Schema              string `json:"schema"`
	TransactionModel    string `json:"transaction_model"`
}

func currentDagExecutionPolicy() DagExecutionPolicy {
	return DagExecutionPolicy{BlockParents: DagMaxParents, BlockRank: DagMaxRank, BlockSequence: DagMaxSequence,
		BlockTransactions: DagMaxBlockTransactions, BlockWire: DagMaxWire, CheckpointBlocks: DagMaxBatchBlocks,
		CheckpointEncoded: DagMaxBatchWire, CheckpointRaw: DagMaxWire, HistoryBlocks: DagMaxRecords,
		HistoryRaw: DagMaxHistoryWire, HistoryVerification: "FULL_SIGNED_GENESIS_REPLAY", Profile: "GG-DAG-FINITE-v1",
		Schema: "gg.dag.execution-policy.v1", TransactionModel: "PRODUCER_OWNED_NONFINANCIAL"}
}

func validDagGenesisPolicy(genesis DagGenesis) bool {
	switch genesis.Schema {
	case "gg.parallel-dag.genesis.v2":
		return genesis.ExecutionPolicy == nil
	case "gg.parallel-dag.genesis.v3":
		return genesis.ExecutionPolicy != nil && *genesis.ExecutionPolicy == currentDagExecutionPolicy()
	default:
		return false
	}
}

// An explicit JSON null must not collapse to an omitted legacy field. Python
// rejects that legacy extension; native and WASM must reject the same bytes.
func (genesis *DagGenesis) UnmarshalJSON(raw []byte) error {
	type plainGenesis DagGenesis
	var value plainGenesis
	if err := decodeStrict(raw, &value); err != nil {
		return err
	}
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(raw, &fields); err != nil {
		return err
	}
	_, present := fields["execution_policy"]
	if value.Schema == "gg.parallel-dag.genesis.v2" && present ||
		value.Schema == "gg.parallel-dag.genesis.v3" && (!present || value.ExecutionPolicy == nil) {
		return errors.New("GG_DAG_GENESIS_POLICY_ENCODING")
	}
	*genesis = DagGenesis(value)
	return nil
}
