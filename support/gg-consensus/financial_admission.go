package main

// Bounded dynamic committee rules for the new integrated application. These
// functions validate plans; only a committed native membership transition may
// produce ABCI validator updates or become a light-client trust context.
import (
	"errors"
	"math/big"
)

var errCommittee = errors.New("GG_DYNAMIC_COMMITTEE_INVALID")

type publicConsensusMember struct {
	AccountKey   string `json:"account_key"`
	NodeKey      string `json:"node_key"`
	OwnerPeerKey string `json:"owner_peer_key"`
	Power        string `json:"power"`
	ValidatorKey string `json:"validator_key"`
}

type publicCommittee struct {
	Epoch   uint64                  `json:"epoch,string"`
	Members []publicConsensusMember `json:"members"`
	Schema  string                  `json:"schema"`
}

type committeeChangePlan struct {
	DecidedHeight   uint64          `json:"decided_height,string"`
	EffectiveHeight uint64          `json:"effective_height,string"`
	FromRoot        string          `json:"from_root"`
	Next            publicCommittee `json:"next"`
	NextRoot        string          `json:"next_root"`
	Schema          string          `json:"schema"`
}

func (committee publicCommittee) valid() bool {
	if committee.Schema != "gg.financial.public-committee.v1" || len(committee.Members) < 4 || len(committee.Members) > 1024 {
		return false
	}
	owners, operational, accounts := map[string]bool{}, map[string]bool{}, map[string]bool{}
	total, previous := uint64(0), ""
	for _, member := range committee.Members {
		power, ok := economicAmount(member.Power)
		if !ok || power == 0 || power >= 1<<50 || total > (1<<60-1)-power || member.ValidatorKey <= previous {
			return false
		}
		for _, key := range []string{member.AccountKey, member.OwnerPeerKey, member.NodeKey, member.ValidatorKey} {
			if !financialAccountAddress(key) {
				return false
			}
		}
		if operational[member.NodeKey] || operational[member.ValidatorKey] || member.NodeKey == member.ValidatorKey {
			return false
		}
		owners[member.OwnerPeerKey] = true
		accounts[member.AccountKey] = true
		operational[member.NodeKey], operational[member.ValidatorKey] = true, true
		total += power
		previous = member.ValidatorKey
	}
	for key := range operational {
		if owners[key] || accounts[key] {
			return false
		}
	}
	for key := range owners {
		if accounts[key] {
			return false
		}
	}
	return true
}

func publicCommitteeRoot(committee publicCommittee, genesis string) (string, error) {
	if !committee.valid() || !pubPattern.MatchString(genesis) {
		return "", errCommittee
	}
	return hashHex(append([]byte("GG-FINANCIAL-PUBLIC-COMMITTEE-v1\x00"+genesis+"\x00"), canonical(committee)...)), nil
}

func planCommitteeChange(before, after publicCommittee, genesis string, decidedHeight uint64, maxChangeBPS uint32) (committeeChangePlan, error) {
	from, first := publicCommitteeRoot(before, genesis)
	next, second := publicCommitteeRoot(after, genesis)
	if first != nil || second != nil || before.Epoch == economicMaxUint || after.Epoch != before.Epoch+1 ||
		decidedHeight == 0 || decidedHeight > economicMaxUint-2 || maxChangeBPS == 0 || maxChangeBPS > 3333 {
		return committeeChangePlan{}, errCommittee
	}
	old, updated := map[string]publicConsensusMember{}, map[string]publicConsensusMember{}
	oldTotal, additions, removals := uint64(0), uint64(0), uint64(0)
	for _, member := range before.Members {
		old[member.ValidatorKey] = member
		power, _ := economicAmount(member.Power)
		oldTotal += power
	}
	for _, member := range after.Members {
		updated[member.ValidatorKey] = member
		power, _ := economicAmount(member.Power)
		prior, exists := old[member.ValidatorKey]
		if !exists {
			additions += power
			continue
		}
		// An existing signer never acquires a second owner through a renamed
		// row. Key/owner rotation needs a separately authenticated operation.
		if prior.OwnerPeerKey != member.OwnerPeerKey || prior.NodeKey != member.NodeKey || prior.AccountKey != member.AccountKey {
			return committeeChangePlan{}, errCommittee
		}
		previous, _ := economicAmount(prior.Power)
		if power > previous {
			additions += power - previous
		} else {
			removals += previous - power
		}
	}
	for key, member := range old {
		if _, exists := updated[key]; !exists {
			power, _ := economicAmount(member.Power)
			removals += power
		}
	}
	changed := additions
	if removals > changed {
		changed = removals
	}
	left := new(big.Int).Mul(new(big.Int).SetUint64(changed), big.NewInt(10000))
	right := new(big.Int).Mul(new(big.Int).SetUint64(oldTotal), new(big.Int).SetUint64(uint64(maxChangeBPS)))
	if left.Cmp(right) > 0 {
		return committeeChangePlan{}, errors.New("GG_COMMITTEE_CHANGE_BUDGET")
	}
	// CometBFT applies a change emitted at FinalizeBlock(H) at height H+2.
	// A certificate over state H is normally carried by signed header H+1.
	after.Members = append([]publicConsensusMember(nil), after.Members...)
	return committeeChangePlan{DecidedHeight: decidedHeight, EffectiveHeight: decidedHeight + 2, FromRoot: from,
		Next: after, NextRoot: next, Schema: "gg.financial.committee-change-plan.v1"}, nil
}
