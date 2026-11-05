package main

import "context"

type financialCertifiedAccount struct {
	GenesisHash string                `json:"genesis_hash"`
	Height      int64                 `json:"height"`
	Proof       financialAccountProof `json:"proof"`
	Schema      string                `json:"schema"`
	StateRoot   string                `json:"state_root"`
}

// verifyInput authenticates the SDK certificate first. A provider cannot
// choose its own trusted root or replace verification with a local flag.
func checkFinancialCertifiedAccount(ctx context.Context, proof financialCertifiedAccount, state State, genesis Genesis) (Account, bool, error) {
	if !generalFinancialAccounts(genesis) || state.FinancialDAG == nil || state.AccountTree == nil ||
		proof.Schema != "gg.financial-dag.account-proof.v1" || proof.GenesisHash != state.GenesisHash || proof.Height != state.Height || proof.StateRoot != state.StateRoot ||
		validateFinancialAccountRoot(state.AccountTree, genesis, state.GenesisHash, state.FinancialDAG.Applied) != nil {
		return Account{}, false, errFinancialAccount
	}
	rules, err := financialAccountRulesFor(genesis, state.GenesisHash)
	if err != nil {
		return Account{}, false, err
	}
	return verifyFinancialAccountProof(ctx, proof.Proof, *state.AccountTree, rules)
}
