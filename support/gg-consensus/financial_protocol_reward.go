package main

import (
	"context"
	"encoding/hex"
)

type protocolRewardSelector struct {
	Address string `json:"address"`
	Index   uint64 `json:"index,string"`
}

type financialCertifiedReward struct {
	Credit      economicCredit             `json:"credit"`
	CreditIndex int                        `json:"credit_index"`
	CreditPath  []PathItem                 `json:"credit_path"`
	Receipt     protocolRewardReceipt      `json:"receipt"`
	Registry    financialCertifiedRegistry `json:"registry"`
	Schema      string                     `json:"schema"`
}

func checkProtocolRewardHeader(receipt protocolRewardReceipt, genesis Genesis, anchor string) error {
	before, bok := economicAmount(receipt.BeforeIssued)
	next, nok := economicAmount(receipt.NextIssued)
	minted, mok := economicAmount(receipt.Minted)
	fees, fok := economicAmount(receipt.Fees)
	if !publicFinancialProtocol(genesis) || receipt.Credits != nil || receipt.Schema != "gg.financial.reward-receipt.v1" || receipt.Genesis != anchor ||
		!bok || !nok || !mok || !fok || before > financialMaximumSupply(genesis) || minted > financialMaximumSupply(genesis)-before || next != before+minted ||
		fees > before || fees > economicMaxUint-minted || receipt.Epoch > receipt.ClosedThrough || receipt.Index == 0 || receipt.Index > 1<<32 ||
		receipt.CreditsCount < 0 || receipt.CreditsCount > economicMaxRecipients || !pubPattern.MatchString(receipt.CreditsRoot) {
		return errFinancialProtocol
	}
	rules, err := protocolRegistryRulesFor(genesis, anchor, "epoch_work")
	if err != nil || !validProtocolRegistryLink(receipt.WorkRoot, rules, rules.hash()) {
		return errFinancialProtocol
	}
	return nil
}

func checkFinancialCertifiedReward(ctx context.Context, proof financialCertifiedReward, state State, genesis Genesis, expected protocolRewardSelector) error {
	if state.Protocol == nil || proof.Schema != "gg.financial.reward-proof.v1" || !financialAccountAddress(expected.Address) ||
		expected.Index != proof.Receipt.Index || expected.Index > state.Protocol.Settlements || proof.Credit.Address != expected.Address ||
		checkProtocolRewardHeader(proof.Receipt, genesis, state.GenesisHash) != nil || proof.CreditIndex < 0 || proof.CreditIndex >= proof.Receipt.CreditsCount {
		return errFinancialProtocol
	}
	amount, valid := economicAmount(proof.Credit.Amount)
	if !valid || amount == 0 {
		return errFinancialProtocol
	}
	raw, exists, err := checkFinancialCertifiedRegistry(ctx, proof.Registry, state, genesis, protocolRegistrySelector{Namespace: "rewards", Key: protocolRewardKey(expected.Index)})
	if err != nil || !exists || string(raw) != protocolRewardReceiptID(proof.Receipt) {
		return errFinancialProtocol
	}
	value := dagDigest("GG-FINANCIAL-REWARD-CREDITS-v1\x00L\x00", proof.Credit)
	index, count, used := proof.CreditIndex, proof.Receipt.CreditsCount, 0
	for count > 1 {
		if err := ctx.Err(); err != nil {
			return err
		}
		if used >= len(proof.CreditPath) {
			return errFinancialProtocol
		}
		step := proof.CreditPath[used]
		side := "right"
		if index&1 != 0 {
			side = "left"
		}
		if step.Side != side || !pubPattern.MatchString(step.Hash) || index^1 >= count && step.Hash != value {
			return errFinancialProtocol
		}
		left, right := value, step.Hash
		if side == "left" {
			left, right = right, left
		}
		a, _ := hex.DecodeString(left)
		b, _ := hex.DecodeString(right)
		value = hashHex(append(append([]byte("GG-FINANCIAL-REWARD-CREDITS-v1\x00N\x00"), a...), b...))
		index, count, used = index/2, (count+1)/2, used+1
	}
	if used != len(proof.CreditPath) || value != proof.Receipt.CreditsRoot {
		return errFinancialProtocol
	}
	return ctx.Err()
}
