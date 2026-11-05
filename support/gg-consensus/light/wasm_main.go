//go:build js && wasm

// Public-data verification only. This entry point shares the native ledger and
// SDK proof verifier; it has no wallet, signing, HTTP, or filesystem API.
package main

import (
	"encoding/hex"
	"encoding/json"
	"syscall/js"

	cmted "github.com/cometbft/cometbft/crypto/ed25519"
	"github.com/cometbft/cometbft/types"
)

func validatorSet(genesis Genesis) *types.ValidatorSet {
	validators := make([]*types.Validator, len(genesis.Validators))
	for i, encoded := range genesis.Validators {
		public, _ := hex.DecodeString(encoded)
		validators[i] = types.NewValidator(cmted.PubKey(public), genesisValidatorPower(genesis, i))
	}
	return types.NewValidatorSet(validators)
}

func invalidResult() string { return `{"verified":false,"error":"GG_PROOF_INVALID"}` }

func loadInputCommitteeTrust(input *VerifyInput) error {
	if input.CommitteeTrustPath != "" {
		return errCommittee
	}
	return nil
}

func verifyPublic(_ js.Value, arguments []js.Value) (result any) {
	result = invalidResult()
	defer func() {
		if recover() != nil {
			result = invalidResult()
		}
	}()
	if len(arguments) != 1 || arguments[0].Type() != js.TypeString {
		return result
	}
	raw := arguments[0].String()
	if len(raw) == 0 || len(raw) > 256*1024 {
		return result
	}
	var input VerifyInput
	if decodeStrictLimited([]byte(raw), &input, MaxBlockTxs, 64) != nil {
		return result
	}
	verified, err := verifyInput(input)
	if err != nil {
		return result
	}
	encoded, err := json.Marshal(verified)
	if err != nil || len(encoded) > 8192 {
		return result
	}
	return string(encoded)
}

func main() {
	callback := js.FuncOf(verifyPublic)
	js.Global().Set("ggVerifyConsensusProof", callback)
	select {}
}
