package main

// Deterministic economic transitions for the integrated protocol under construction.
// Legacy genesis/source versions never call these rules. A settlement is an
// allocation plan until its fee debits, account credits and state are committed
// together by the versioned application; it is not an RPC mint operation.
import (
	"errors"
	"math/big"
	"sort"
)

const economicMaxRecipients = 65536
const economicMaxUint = ^uint64(0)

var errEconomicPolicy = errors.New("GG_ECONOMIC_POLICY_INVALID")
var errEconomicState = errors.New("GG_ECONOMIC_STATE_INVALID")

type economicPolicy struct {
	EpochReward     string `json:"epoch_reward_atomic"`
	EpochSeconds    uint64 `json:"epoch_seconds,string"`
	FeePerByte      string `json:"fee_per_byte_atomic"`
	HalvingEpochs   uint64 `json:"halving_epochs,string"`
	InitialSupply   string `json:"initial_supply_atomic"`
	MaxSupply       string `json:"max_supply_atomic"`
	MinFee          string `json:"min_fee_atomic"`
	Schema          string `json:"schema"`
	TailReward      string `json:"tail_reward_atomic"`
	TreasuryAccount string `json:"treasury_account"`
	TreasuryBPS     uint32 `json:"treasury_bps"`
}

type economicState struct {
	Issued    string `json:"issued_atomic"`
	NextEpoch uint64 `json:"next_epoch,string"`
	RulesHash string `json:"rules_hash"`
	Schema    string `json:"schema"`
}

type economicWeight struct {
	Address string `json:"address"`
	Weight  string `json:"weight"`
}

type economicCredit struct {
	Address string `json:"address"`
	Amount  string `json:"amount_atomic"`
}

type economicSettlement struct {
	Credits []economicCredit `json:"credits"`
	Epoch   uint64           `json:"epoch,string"`
	Fees    string           `json:"fees_atomic"`
	Minted  string           `json:"minted_atomic"`
	Next    economicState    `json:"next"`
	Schema  string           `json:"schema"`
}

func economicAmount(value string) (uint64, bool) {
	return financialAccountAmount(value, economicMaxUint)
}

func economicWorkWeight(value string) (*big.Int, bool) {
	if len(value) == 0 || len(value) > 155 || !uintPattern.MatchString(value) {
		return nil, false
	}
	weight, ok := new(big.Int).SetString(value, 10)
	return weight, ok && weight.Sign() > 0 && weight.BitLen() <= 512
}

func (policy economicPolicy) valid() bool {
	initial, a := economicAmount(policy.InitialSupply)
	maximum, b := economicAmount(policy.MaxSupply)
	reward, c := economicAmount(policy.EpochReward)
	tail, d := economicAmount(policy.TailReward)
	_, e := economicAmount(policy.MinFee)
	_, f := economicAmount(policy.FeePerByte)
	return policy.Schema == "gg.financial.economic-policy.v1" && a && b && c && d && e && f &&
		maximum > 0 && initial <= maximum && reward <= maximum && tail <= reward &&
		policy.EpochSeconds > 0 && policy.HalvingEpochs > 0 && policy.TreasuryBPS <= 10000 &&
		(policy.TreasuryBPS == 0 && policy.TreasuryAccount == "" || policy.TreasuryBPS > 0 && financialAccountAddress(policy.TreasuryAccount))
}

func economicRulesHash(policy economicPolicy, genesis string) (string, error) {
	if !policy.valid() || !pubPattern.MatchString(genesis) {
		return "", errEconomicPolicy
	}
	return hashHex(append([]byte("GG-FINANCIAL-ECONOMY-v1\x00"+genesis+"\x00"), canonical(policy)...)), nil
}

func initialEconomicState(policy economicPolicy, genesis string) (economicState, error) {
	rules, err := economicRulesHash(policy, genesis)
	if err != nil {
		return economicState{}, err
	}
	return economicState{Issued: policy.InitialSupply, RulesHash: rules, Schema: "gg.financial.economic-state.v1"}, nil
}

func economicEpochAt(policy economicPolicy, genesisTime, certifiedTime uint64) (uint64, error) {
	if !policy.valid() || certifiedTime < genesisTime {
		return 0, errEconomicPolicy
	}
	return (certifiedTime - genesisTime) / policy.EpochSeconds, nil
}

func economicMinimumFee(policy economicPolicy, wireBytes uint64) (uint64, error) {
	if !policy.valid() || wireBytes == 0 || wireBytes > financialMaxInputBytes {
		return 0, errEconomicPolicy
	}
	perByte, _ := economicAmount(policy.FeePerByte)
	base, _ := economicAmount(policy.MinFee)
	if perByte > 0 && wireBytes > (economicMaxUint-base)/perByte {
		return 0, errEconomicPolicy
	}
	return base + wireBytes*perByte, nil
}

// All quotients use exact integers. The unassigned units are fewer than the
// recipient count; largest remainder with address tie-breaking assigns them
// deterministically. Splitting an identity cannot create additional money.
func economicSplit(total uint64, weights []economicWeight) ([]economicCredit, error) {
	if len(weights) == 0 || len(weights) > economicMaxRecipients {
		return nil, errEconomicState
	}
	denominator := new(big.Int)
	previous := ""
	for _, row := range weights {
		weight, valid := economicWorkWeight(row.Weight)
		if !valid || !financialAccountAddress(row.Address) || row.Address <= previous {
			return nil, errEconomicState
		}
		denominator.Add(denominator, weight)
		previous = row.Address
	}
	type allocation struct {
		address   string
		amount    uint64
		remainder *big.Int
	}
	rows := make([]allocation, len(weights))
	allocated := uint64(0)
	for i, row := range weights {
		weight, _ := economicWorkWeight(row.Weight)
		product := new(big.Int).Mul(new(big.Int).SetUint64(total), weight)
		quotient, remainder := new(big.Int), new(big.Int)
		quotient.QuoRem(product, denominator, remainder)
		amount := quotient.Uint64()
		if amount > total-allocated {
			return nil, errEconomicState
		}
		allocated += amount
		rows[i] = allocation{address: row.Address, amount: amount, remainder: remainder}
	}
	remaining := total - allocated
	if remaining >= uint64(len(rows)) {
		return nil, errEconomicState
	}
	sort.Slice(rows, func(i, j int) bool {
		comparison := rows[i].remainder.Cmp(rows[j].remainder)
		return comparison > 0 || comparison == 0 && rows[i].address < rows[j].address
	})
	for i := uint64(0); i < remaining; i++ {
		rows[i].amount++
	}
	sort.Slice(rows, func(i, j int) bool { return rows[i].address < rows[j].address })
	credits := make([]economicCredit, 0, len(rows))
	for _, row := range rows {
		if row.amount > 0 {
			credits = append(credits, economicCredit{Address: row.address, Amount: new(big.Int).SetUint64(row.amount).String()})
		}
	}
	return credits, nil
}

func economicCommission(total uint64, bps uint32) uint64 {
	product := new(big.Int).Mul(new(big.Int).SetUint64(total), new(big.Int).SetUint64(uint64(bps)))
	return product.Quo(product, big.NewInt(10000)).Uint64()
}

func economicAddCredit(credits []economicCredit, address string, amount uint64) []economicCredit {
	if amount == 0 {
		return credits
	}
	for i := range credits {
		if credits[i].Address == address {
			prior, _ := economicAmount(credits[i].Amount)
			credits[i].Amount = new(big.Int).SetUint64(prior + amount).String()
			return credits
		}
	}
	credits = append(credits, economicCredit{Address: address, Amount: new(big.Int).SetUint64(amount).String()})
	sort.Slice(credits, func(i, j int) bool { return credits[i].Address < credits[j].Address })
	return credits
}

// certifiedEpoch must come from the authenticated consensus clock, and the
// weights/fee pot from the native committed work/fee ledger. Peer JSON cannot
// choose either. Closing the same epoch twice fails the NextEpoch boundary.
func settleEconomicEpoch(policy economicPolicy, genesis string, before economicState, epoch, certifiedEpoch, fees uint64, weights []economicWeight) (economicSettlement, error) {
	rules, err := economicRulesHash(policy, genesis)
	issued, ok := economicAmount(before.Issued)
	maximum, _ := economicAmount(policy.MaxSupply)
	initial, _ := economicAmount(policy.InitialSupply)
	if err != nil || !ok || before.Schema != "gg.financial.economic-state.v1" || before.RulesHash != rules || issued < initial || issued > maximum ||
		epoch != before.NextEpoch || epoch >= certifiedEpoch || epoch == economicMaxUint || fees > issued {
		return economicSettlement{}, errEconomicState
	}
	reward, _ := economicAmount(policy.EpochReward)
	tail, _ := economicAmount(policy.TailReward)
	period := epoch / policy.HalvingEpochs
	if period >= 64 {
		reward = 0
	} else {
		reward >>= period
	}
	if reward < tail {
		reward = tail
	}
	if reward > maximum-issued {
		reward = maximum - issued
	}
	if len(weights) == 0 {
		if fees != 0 {
			return economicSettlement{}, errEconomicState
		}
		reward = 0
	}
	total := reward + fees // fees <= issued, reward <= maximum-issued.
	treasury := economicCommission(total, policy.TreasuryBPS)
	credits := []economicCredit{}
	if len(weights) > 0 {
		credits, err = economicSplit(total-treasury, weights)
		if err != nil {
			return economicSettlement{}, err
		}
	}
	credits = economicAddCredit(credits, policy.TreasuryAccount, treasury)
	after := before
	after.NextEpoch++
	after.Issued = new(big.Int).SetUint64(issued + reward).String()
	return economicSettlement{Credits: credits, Epoch: epoch, Fees: new(big.Int).SetUint64(fees).String(), Minted: new(big.Int).SetUint64(reward).String(), Next: after, Schema: "gg.financial.epoch-settlement.v1"}, nil
}

// The caller must supply a previously certified incoming reward. This pure
// allocation function does not establish its receipt. Accepted shares determine
// proportions, never additional consensus issuance or vote power.
func economicPoolAllocation(reward uint64, operator string, commissionBPS uint32, shares []economicWeight) ([]economicCredit, error) {
	if commissionBPS > 10000 || !financialAccountAddress(operator) {
		return nil, errEconomicPolicy
	}
	commission := economicCommission(reward, commissionBPS)
	credits, err := economicSplit(reward-commission, shares)
	if err != nil {
		return nil, err
	}
	return economicAddCredit(credits, operator, commission), nil
}
