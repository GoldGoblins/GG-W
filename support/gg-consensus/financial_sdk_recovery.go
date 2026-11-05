//go:build !js

package main

import (
	"bytes"
	"errors"

	cmtjson "github.com/cometbft/cometbft/libs/json"
	cmtstate "github.com/cometbft/cometbft/proto/tendermint/state"
	sm "github.com/cometbft/cometbft/state"
	"github.com/cometbft/cometbft/types"
	"github.com/cometbft/cometbft/version"
)

const financialSDKCommitMaxWire = 16 * 1024

var errFinancialSDKRecovery = errors.New("GG_FINANCIAL_SDK_RECOVERY_CONTEXT")

func financialArchiveMagicValid(magic string) bool {
	return magic == financialArchiveMagic || magic == financialSDKArchiveMagic
}
func financialArchiveSchemaMatches(magic, schema string) bool {
	return magic == financialArchiveMagic && schema == "gg.financial.public-archive.v1" || magic == financialSDKArchiveMagic && schema == "gg.financial.public-archive.v2"
}
func financialArchiveVersion(cursor *financialArchiveReplay) int {
	if cursor.sdkRecovery != nil {
		return 2
	}
	return 1
}

// Derive every validator change and proposer priority from genesis and owned
// application replay, using the pinned SDK updateState order. A peer's state
// snapshot or advertised priority never supplies the recovery validator set.
type financialSDKRecovery struct {
	state   sm.State
	genesis Genesis
	commit  *types.Commit
}

func newFinancialSDKRecovery(genesis Genesis) (*financialSDKRecovery, error) {
	state, err := sm.MakeGenesisState(genesisDoc(genesis))
	if err != nil {
		return nil, errFinancialSDKRecovery
	}
	return &financialSDKRecovery{state: state, genesis: genesis}, nil
}

func (r *financialSDKRecovery) checkHeader(header *types.Header) error {
	if header == nil || !bytes.Equal(header.ConsensusHash, r.state.ConsensusParams.Hash()) ||
		header.Version.Block != version.BlockProtocol || header.Version.App != r.state.ConsensusParams.Version.App ||
		header.Height != r.state.LastBlockHeight+1 || !bytes.Equal(header.ValidatorsHash, r.state.Validators.Hash()) || !bytes.Equal(header.NextValidatorsHash, r.state.NextValidators.Hash()) {
		return errFinancialSDKRecovery
	}
	return nil
}

func (r *financialSDKRecovery) advance(current, next *types.Header, replayed ...State) error {
	if r.checkHeader(current) != nil || next == nil || next.Height != current.Height+1 || len(replayed) > 1 {
		return errFinancialSDKRecovery
	}
	nextValidators := r.state.NextValidators.Copy()
	if publicFinancialProtocol(r.genesis) {
		if len(replayed) != 1 || replayed[0].Height != current.Height || validateState(replayed[0], r.genesis, replayed[0].GenesisHash) != nil ||
			financialSDKStateBinding(next, replayed[0]) != nil {
			return errFinancialSDKRecovery
		}
		updates, err := financialProtocolStateValidatorUpdates(*replayed[0].Protocol, current.Height)
		if err != nil {
			return err
		}
		changes, err := types.PB2TM.ValidatorUpdates(updates)
		if err != nil || len(changes) > 0 && nextValidators.UpdateWithChangeSet(changes) != nil {
			return errFinancialSDKRecovery
		}
	}
	nextValidators.IncrementProposerPriority(1)
	if !bytes.Equal(next.ValidatorsHash, r.state.NextValidators.Hash()) || !bytes.Equal(next.NextValidatorsHash, nextValidators.Hash()) ||
		!bytes.Equal(next.ConsensusHash, r.state.ConsensusParams.Hash()) || next.Version != current.Version {
		return errFinancialSDKRecovery
	}
	r.state.LastValidators = r.state.Validators.Copy()
	r.state.Validators = r.state.NextValidators.Copy()
	r.state.NextValidators = nextValidators
	r.state.LastBlockHeight = current.Height
	r.state.LastBlockTime = current.Time
	r.state.LastBlockID = next.LastBlockID
	r.state.AppHash = append([]byte(nil), next.AppHash...)
	r.state.LastResultsHash = append([]byte(nil), next.LastResultsHash...)
	r.state.Version = cmtstate.Version{Consensus: next.Version, Software: version.TMCoreSemVer}
	// Bootstrap writes full current/next sets and current params at these heights.
	r.state.LastHeightValidatorsChanged = next.Height + 1
	r.state.LastHeightConsensusParamsChanged = next.Height
	return nil
}

func (r *financialSDKRecovery) bindCommit(previous, final *types.Header, raw []byte) error {
	if len(raw) == 0 || len(raw) > financialSDKCommitMaxWire || r.checkHeader(final) != nil {
		return errFinancialSDKRecovery
	}
	if r.state.LastBlockHeight == 0 {
		if previous != nil || !bytes.Equal(raw, []byte("null")) || final.Height != 1 {
			return errFinancialSDKRecovery
		}
		return nil
	}
	var commit types.Commit
	if previous == nil || cmtjson.Unmarshal(raw, &commit) != nil || commit.ValidateBasic() != nil {
		return errFinancialSDKRecovery
	}
	normalized, err := cmtjson.Marshal(&commit)
	if err != nil || !bytes.Equal(raw, normalized) || previous.Height != r.state.LastBlockHeight || final.Height != previous.Height+1 ||
		commit.Height != previous.Height || !commit.BlockID.Equals(final.LastBlockID) || !bytes.Equal(commit.BlockID.Hash, previous.Hash()) {
		return errFinancialSDKRecovery
	}
	signed, err := cmtjson.Marshal(&types.SignedHeader{Header: previous, Commit: &commit})
	if err != nil {
		return errFinancialSDKRecovery
	}
	if _, err = verifyHeaderWithSets(signed, r.genesis, r.state.LastValidators, r.state.Validators); err != nil {
		return errFinancialSDKRecovery
	}
	r.commit = &commit
	return nil
}
