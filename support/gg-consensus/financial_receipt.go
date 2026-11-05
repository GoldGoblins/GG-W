package main

// A compact receipt is authenticated in two steps: the payment outcome belongs
// to a sealed block summary, and that summary/creator belongs to the certified
// global summary MMR. Closed segment cuts never erase this commitment.
import "errors"

type financialDagCreator struct {
	Key       string   `json:"key"`
	Parents   []string `json:"parents,omitempty"`
	Producer  int      `json:"producer_index"`
	Rank      uint64   `json:"rank,string,omitempty"`
	Sequence  uint64   `json:"sequence,string"`
	WorkHash  string   `json:"work_hash,omitempty"`
	WorkerKey string   `json:"worker_key,omitempty"`
}

func validFinancialPublicCreator(creator financialDagCreator, commitment *financialDagCommitment) bool {
	if commitment == nil || creator.Producer != -1 || !financialAccountAddress(creator.Key) || !financialAccountAddress(creator.WorkerKey) ||
		!pubPattern.MatchString(creator.WorkHash) || creator.Sequence == 0 || creator.Sequence > commitment.Blocks || creator.Rank == 0 || creator.Rank > commitment.LastRank ||
		len(creator.Parents) == 0 || len(creator.Parents) > DagMaxParents {
		return false
	}
	for index, parent := range creator.Parents {
		if !pubPattern.MatchString(parent) || index > 0 && parent <= creator.Parents[index-1] {
			return false
		}
	}
	return true
}

type financialReceiptSelector struct {
	Block string `json:"block"`
	Index int    `json:"index"`
}

type financialReceiptExpectation struct {
	Block         string `json:"block,omitempty"`
	Index         *int   `json:"index,omitempty"`
	TransactionID string `json:"transaction_id"`
}

func financialDagSummaryID(binding financialExecutionContext, creator financialDagCreator, summary financialSummary) string {
	return dagDigest(financialDomain+"DAG-SUMMARY\x00", struct {
		Block   string              `json:"block"`
		Creator financialDagCreator `json:"creator"`
		Summary financialSummary    `json:"summary"`
	}{binding.BlockHash, creator, summary})
}

type financialCertifiedReceipt struct {
	Context     financialExecutionContext `json:"context"`
	Creator     financialDagCreator       `json:"creator"`
	Height      int64                     `json:"height"`
	Payment     Envelope                  `json:"payment"`
	Receipt     financialReceiptProof     `json:"receipt"`
	Schema      string                    `json:"schema"`
	StateRoot   string                    `json:"state_root"`
	Summary     financialSummary          `json:"summary"`
	SummaryPath []PathItem                `json:"summary_path"`
}

var errFinancialReceipt = errors.New("GG_FINANCIAL_CERTIFIED_RECEIPT")

func checkFinancialCertifiedReceipt(proof financialCertifiedReceipt, state State, genesis Genesis) error {
	value := state.FinancialDAG
	if publicFinancialProtocol(genesis) {
		if value == nil || proof.Schema != "gg.financial-dag.receipt-proof.v2" || proof.Height != state.Height || proof.StateRoot != state.StateRoot ||
			proof.Context.Genesis != state.GenesisHash || proof.Context.SourceHash != value.SourceHash || proof.Context.Checkpoint > value.Checkpoint || proof.Context.Epoch > value.Epoch ||
			!validFinancialPublicCreator(proof.Creator, value) ||
			len(proof.Receipt.Path) > 16 || !checkFinancialReceiptInclusionVersion(proof.Context, proof.Summary, proof.Receipt, true, true) {
			return errFinancialReceipt
		}
		id := financialDagSummaryID(proof.Context, proof.Creator, proof.Summary)
		if verifyClosedCutPath(id, proof.SummaryPath, proof.Context.OrderIndex, value.Blocks, value.ReceiptsRoot) != nil {
			return errFinancialReceipt
		}
		raw := canonical(proof.Payment)
		if _, err := parseEnvelope(raw, genesis, state.GenesisHash); err != nil || financialIntentID(raw) != proof.Receipt.Leaf.TransactionID {
			return errFinancialReceipt
		}
		return nil
	}
	if value == nil || genesis.FinancialDAG == nil || len(genesis.FinancialDAG.Producers) != 6 || proof.Schema != "gg.financial-dag.receipt-proof.v1" || proof.Height != state.Height || proof.StateRoot != state.StateRoot ||
		proof.Context.Genesis != state.GenesisHash || proof.Context.SourceHash != value.SourceHash || proof.Context.Checkpoint > value.Checkpoint || proof.Context.Epoch > value.Epoch ||
		proof.Creator.Producer < 0 || proof.Creator.Producer >= 6 || proof.Creator.Key != genesis.FinancialDAG.Producers[proof.Creator.Producer] ||
		proof.Creator.Sequence < 1 || proof.Creator.Sequence > value.Authors[proof.Creator.Producer].Sequence ||
		len(proof.Receipt.Path) > 16 || !checkFinancialReceiptInclusionVersion(proof.Context, proof.Summary, proof.Receipt, generalFinancialAccounts(genesis)) {
		return errFinancialReceipt
	}
	id := financialDagSummaryID(proof.Context, proof.Creator, proof.Summary)
	if verifyClosedCutPath(id, proof.SummaryPath, proof.Context.OrderIndex, value.Blocks, value.ReceiptsRoot) != nil {
		return errFinancialReceipt
	}
	raw := canonical(proof.Payment)
	if _, err := parseEnvelope(raw, genesis, state.GenesisHash); err != nil || financialIntentID(raw) != proof.Receipt.Leaf.TransactionID {
		return errFinancialReceipt
	}
	return nil
}
