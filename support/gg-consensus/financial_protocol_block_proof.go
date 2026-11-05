package main

type financialRecentSelector struct {
	Limit int    `json:"limit"`
	Start uint64 `json:"start,string"`
}
type financialRecentBlock struct {
	Block string `json:"block"`
	Index uint64 `json:"index,string"`
}
type financialRecentBlocks struct {
	Blocks    []financialRecentBlock `json:"blocks"`
	Height    int64                  `json:"height"`
	Schema    string                 `json:"schema"`
	StateRoot string                 `json:"state_root"`
}

type financialOriginalCoreSelector struct {
	Block    string `json:"block"`
	MaxBytes int    `json:"max_bytes"`
	Offset   int    `json:"offset"`
}

type financialOriginalCoreChunk struct {
	Block      string `json:"block"`
	Data       []byte `json:"data"`
	Offset     int    `json:"offset"`
	Schema     string `json:"schema"`
	TotalBytes int    `json:"total_bytes"`
	WireHash   string `json:"wire_hash"`
}

// Summary membership also covers blocks with zero payments. The certificate
// proves the application's admitted creator/order/outcomes; it does not claim
// that a client replayed the complete block or measured live network traffic.
type financialCertifiedBlock struct {
	Context     financialExecutionContext `json:"context"`
	Creator     financialDagCreator       `json:"creator"`
	Height      int64                     `json:"height"`
	Schema      string                    `json:"schema"`
	StateRoot   string                    `json:"state_root"`
	Summary     financialSummary          `json:"summary"`
	SummaryPath []PathItem                `json:"summary_path"`
}

func checkFinancialCertifiedBlock(proof financialCertifiedBlock, state State, genesis Genesis, expectedBlock string) error {
	value := state.FinancialDAG
	s := proof.Summary
	if !publicFinancialProtocol(genesis) || value == nil || !pubPattern.MatchString(expectedBlock) || proof.Context.BlockHash != expectedBlock ||
		proof.Schema != "gg.financial.block-proof.v1" || proof.Height != state.Height || proof.StateRoot != state.StateRoot || !proof.Context.valid(state.GenesisHash) ||
		proof.Context.SourceHash != value.SourceHash || proof.Context.Checkpoint > value.Checkpoint || proof.Context.Epoch > value.Epoch ||
		!validFinancialPublicCreator(proof.Creator, value) ||
		s.Schema != "gg.financial.summary.v3" || s.ContextHash != financialContextHash(proof.Context) || s.Transactions < 0 || s.Transactions > financialMaxTransactions ||
		s.Applied < 0 || s.Rejected < 0 || s.Applied > s.Transactions || s.Rejected != s.Transactions-s.Applied ||
		!pubPattern.MatchString(s.AccountRootBefore) || !pubPattern.MatchString(s.AccountRootAfter) || !pubPattern.MatchString(s.ReceiptsRoot) || !pubPattern.MatchString(s.InputHash) {
		return errFinancialReceipt
	}
	if _, valid := economicAmount(s.Fees); !valid {
		return errFinancialReceipt
	}
	id := financialDagSummaryID(proof.Context, proof.Creator, s)
	if verifyClosedCutPath(id, proof.SummaryPath, proof.Context.OrderIndex, value.Blocks, value.ReceiptsRoot) != nil {
		return errFinancialReceipt
	}
	return nil
}
