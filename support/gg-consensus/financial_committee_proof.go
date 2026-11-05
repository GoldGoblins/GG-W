package main

// A committee named by an untrusted current state cannot verify that state.
// Start at the pinned genesis and accept each change only through a quorum
// certificate signed by the independently known preceding committee.
import (
	"bytes"
	"encoding/hex"
	"encoding/json"
	"errors"

	cmted "github.com/cometbft/cometbft/crypto/ed25519"
	cmtjson "github.com/cometbft/cometbft/libs/json"
	"github.com/cometbft/cometbft/types"
)

type financialCommitteeTransition struct {
	Schema       string          `json:"schema"`
	SignedHeader json.RawMessage `json:"signed_header"`
	State        State           `json:"state"`
}

type verifiedCommitteeTrust struct {
	anchor             string
	current, previous  publicCommittee
	decided, effective uint64
	certificateTime    int64
}

func committeeValidatorSet(committee publicCommittee) (*types.ValidatorSet, error) {
	if !committee.valid() || len(committee.Members) > 64 {
		return nil, errCommittee
	}
	validators := make([]*types.Validator, len(committee.Members))
	for index, member := range committee.Members {
		public, _ := hex.DecodeString(member.ValidatorKey)
		power, _ := economicAmount(member.Power)
		validators[index] = types.NewValidator(cmted.PubKey(public), int64(power))
	}
	return types.NewValidatorSet(validators), nil
}

func verifyHeaderWithSets(raw []byte, genesis Genesis, current, next *types.ValidatorSet) (*types.SignedHeader, error) {
	if len(raw) == 0 || len(raw) > 64*1024 || current == nil || next == nil {
		return nil, errors.New("GG_HEADER_SIZE")
	}
	var header types.SignedHeader
	if cmtjson.Unmarshal(raw, &header) != nil || header.ValidateBasic(genesis.ChainID) != nil {
		return nil, errors.New("GG_HEADER_INVALID")
	}
	if !bytes.Equal(header.ValidatorsHash, current.Hash()) || !bytes.Equal(header.NextValidatorsHash, next.Hash()) {
		return nil, errors.New("GG_HEADER_VALIDATORS")
	}
	if current.VerifyCommitLight(genesis.ChainID, header.Commit.BlockID, header.Height, header.Commit) != nil {
		return nil, errors.New("GG_HEADER_QUORUM")
	}
	return &header, nil
}

func initialCommitteeTrust(genesis Genesis, anchor string) (*verifiedCommitteeTrust, error) {
	if !publicFinancialProtocol(genesis) || validateGenesis(genesis, anchor) != nil {
		return nil, errCommittee
	}
	return &verifiedCommitteeTrust{anchor: anchor, current: genesis.Protocol.Committee}, nil
}

func (trust *verifiedCommitteeTrust) accept(genesis Genesis, transition financialCommitteeTransition) error {
	state := transition.State
	if trust == nil || transition.Schema != "gg.financial.committee-transition-proof.v1" || validateState(state, genesis, trust.anchor) != nil || state.Protocol == nil ||
		state.Protocol.PendingCommittee == nil || state.Height < 1 || uint64(state.Height) < trust.effective || !bytes.Equal(canonical(state.Protocol.Committee), canonical(trust.current)) {
		return errCommittee
	}
	pending := state.Protocol.PendingCommittee
	plan, err := planCommitteeChange(trust.current, pending.Next, trust.anchor, uint64(state.Height), genesis.Protocol.MaxCommitteeChangeBPS)
	if err != nil || pending.DecidedHeight != uint64(state.Height) || !bytes.Equal(canonical(plan), canonical(*pending)) {
		return errCommittee
	}
	oldSet, err := committeeValidatorSet(trust.current)
	if err != nil {
		return err
	}
	nextSet, err := committeeValidatorSet(plan.Next)
	if err != nil {
		return err
	}
	header, err := verifyHeaderWithSets(transition.SignedHeader, genesis, oldSet, nextSet)
	if err != nil || header.Height != state.Height+1 || hex.EncodeToString(header.AppHash) != state.StateRoot || header.Time.UnixNano() <= trust.certificateTime {
		return errCommittee
	}
	// Store no remote 'verified' flag, public root override or mutable pointer.
	trust.previous = copyPublicCommittee(trust.current)
	trust.current = copyPublicCommittee(plan.Next)
	trust.decided, trust.effective, trust.certificateTime = plan.DecidedHeight, plan.EffectiveHeight, header.Time.UnixNano()
	return nil
}

func copyPublicCommittee(value publicCommittee) publicCommittee {
	value.Members = append([]publicConsensusMember(nil), value.Members...)
	return value
}

func (trust *verifiedCommitteeTrust) committeeAt(height uint64) (publicCommittee, error) {
	if trust == nil || height < trust.decided {
		return publicCommittee{}, errCommittee
	}
	if trust.effective > 0 && height < trust.effective {
		return trust.previous, nil
	}
	return trust.current, nil
}

func verifyFinancialCertificate(input VerifyInput) (*types.SignedHeader, *verifiedCommitteeTrust, error) {
	if !publicFinancialProtocol(input.Genesis) {
		if len(input.CommitteeTransitions) > 0 || input.CommitteeTrustPath != "" || input.committeeTrust != nil {
			return nil, nil, errCommittee
		}
		header, err := verifyHeader(input.SignedHeader, input.Genesis)
		return header, nil, err
	}
	if input.CommitteeTrustPath != "" || len(input.CommitteeTransitions) > 128 {
		return nil, nil, errCommittee
	}
	trust := input.committeeTrust
	if trust == nil {
		var err error
		trust, err = initialCommitteeTrust(input.Genesis, input.GenesisHash)
		if err != nil {
			return nil, nil, err
		}
	} else {
		if trust.anchor != input.GenesisHash {
			return nil, nil, errCommittee
		}
		owned := *trust
		trust = &owned
	}
	for _, transition := range input.CommitteeTransitions {
		if err := trust.accept(input.Genesis, transition); err != nil {
			return nil, nil, err
		}
	}
	state := input.State
	if state.Protocol == nil || state.Height < 0 {
		return nil, nil, errCommittee
	}
	stateCommittee, err := trust.committeeAt(uint64(state.Height))
	if err != nil {
		return nil, nil, err
	}
	if !bytes.Equal(canonical(state.Protocol.Committee), canonical(stateCommittee)) {
		return nil, nil, errCommittee
	}
	current, err := trust.committeeAt(uint64(state.Height) + 1)
	if err != nil {
		return nil, nil, err
	}
	next := current
	if pending := state.Protocol.PendingCommittee; pending != nil && pending.DecidedHeight == uint64(state.Height) {
		next = pending.Next
	}
	currentSet, err := committeeValidatorSet(current)
	if err != nil {
		return nil, nil, err
	}
	nextSet, err := committeeValidatorSet(next)
	if err != nil {
		return nil, nil, err
	}
	header, err := verifyHeaderWithSets(input.SignedHeader, input.Genesis, currentSet, nextSet)
	return header, trust, err
}
