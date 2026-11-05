package main

import (
	"bytes"
	"context"
)

type protocolRegistrySelector struct {
	Key       string `json:"key"`
	Namespace string `json:"namespace"`
}

type financialCertifiedRegistry struct {
	GenesisHash string                `json:"genesis_hash"`
	Height      int64                 `json:"height"`
	Namespace   string                `json:"namespace"`
	Proof       protocolRegistryProof `json:"proof"`
	Schema      string                `json:"schema"`
	StateRoot   string                `json:"state_root"`
}

func protocolRegistryRootFor(state State, namespace string) (protocolRegistryLink, error) {
	if state.Protocol == nil {
		return protocolRegistryLink{}, errFinancialProtocol
	}
	switch namespace {
	case "producers":
		return state.Protocol.ProducerRoot, nil
	case "roles":
		return state.Protocol.RoleRoot, nil
	case "epoch_work":
		return state.Protocol.WorkRoot, nil
	case "rewards":
		return state.Protocol.RewardRoot, nil
	case "operations":
		return state.Protocol.OperationRoot, nil
	}
	return protocolRegistryLink{}, errFinancialProtocol
}

// The caller's selector is independent of the response. A valid proof of a
// different record (including an absence interval) never answers this request.
func checkFinancialCertifiedRegistry(ctx context.Context, proof financialCertifiedRegistry, state State, genesis Genesis, expected protocolRegistrySelector) ([]byte, bool, error) {
	if !publicFinancialProtocol(genesis) || state.FinancialDAG == nil || proof.Schema != "gg.financial.registry-proof.v1" ||
		proof.GenesisHash != state.GenesisHash || proof.Height != state.Height || proof.StateRoot != state.StateRoot ||
		proof.Namespace != expected.Namespace || !pubPattern.MatchString(expected.Key) {
		return nil, false, errFinancialProtocol
	}
	root, err := protocolRegistryRootFor(state, expected.Namespace)
	if err != nil {
		return nil, false, err
	}
	rules, err := protocolRegistryRulesFor(genesis, state.GenesisHash, expected.Namespace)
	if err != nil {
		return nil, false, err
	}
	raw, exists, err := verifyProtocolRegistryProof(ctx, proof.Proof, root, rules, expected.Key)
	if err != nil || !exists {
		return raw, exists, err
	}
	switch expected.Namespace {
	case "producers":
		var record protocolProducerRecord
		if decodeStrict(raw, &record) != nil || !bytes.Equal(raw, canonical(record)) ||
			record.Schema != "gg.financial.producer-state.v1" || record.Invite.Body.ProducerKey != expected.Key ||
			checkProtocolProducerInvite(record.Invite, genesis) != nil || !pubPattern.MatchString(record.Head) ||
			record.Sequence > state.FinancialDAG.Blocks || record.Attempts > state.FinancialDAG.Attempts || record.Epoch > state.FinancialDAG.Epoch ||
			record.Rank > state.FinancialDAG.LastRank || (record.Sequence == 0) != (record.Rank == 0) {
			return nil, false, errFinancialProtocol
		}
		if record.Sequence == 0 && record.Head != financialDagOrigin(*genesis.FinancialDAG, state.GenesisHash) {
			return nil, false, errFinancialProtocol
		}
	case "roles":
		var role protocolReservedRole
		if decodeStrict(raw, &role) != nil || !bytes.Equal(raw, canonical(role)) || role.Schema != "gg.financial.reserved-role.v1" ||
			!financialAccountAddress(role.Owner) || (role.Role != "OWNER" && role.Role != "NODE" && role.Role != "PRODUCER" && role.Role != "VALIDATOR" && role.Role != "GOVERNANCE") {
			return nil, false, errFinancialProtocol
		}
	case "epoch_work":
		var weight protocolEpochWeight
		if decodeStrict(raw, &weight) != nil || !bytes.Equal(raw, canonical(weight)) || weight.Epoch != state.Protocol.Economics.NextEpoch {
			return nil, false, errFinancialProtocol
		}
		if _, ok := economicWorkWeight(weight.Weight); !ok {
			return nil, false, errFinancialProtocol
		}
	case "operations":
		var receipt protocolOperationReceipt
		if decodeStrict(raw, &receipt) != nil || !bytes.Equal(raw, canonical(receipt)) || !validProtocolOperationReceipt(receipt, state, expected.Key) {
			return nil, false, errFinancialProtocol
		}
	case "rewards":
		if !pubPattern.MatchString(string(raw)) {
			return nil, false, errFinancialProtocol
		}
	default:
		return nil, false, errFinancialProtocol
	}
	return raw, true, nil
}
