package main

// Versioned public-protocol state. This composes independent account signing,
// authenticated producer ownership, monetary epochs and explicit committees.
// Legacy source/genesis versions retain their old encodings and execution.
import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/hex"
	"errors"
	"math/big"
	"sort"
	"strconv"
	"unicode/utf8"
)

const financialProtocolSourceSchema = "gg.financial-dag.source.v5"
const protocolUnusedKeyPolicy = "SWEEP_NEVER_SPENT_BALANCE_TO_DECLARED_ACCOUNT"

var errFinancialProtocol = errors.New("GG_FINANCIAL_PROTOCOL_INVALID")

type protocolProducerBody struct {
	ChainID         string `json:"chain_id"`
	LabelUTF8       string `json:"label_utf8"`
	NetworkID       string `json:"network_id"`
	NodeKey         string `json:"node_key"`
	Nonce           string `json:"nonce"`
	OwnerPeerKey    string `json:"owner_peer_key"`
	Platform        string `json:"platform"`
	ProducerKey     string `json:"producer_key"`
	RewardAccount   string `json:"reward_account"`
	Schema          string `json:"schema"`
	UnusedKeyPolicy string `json:"unused_key_policy"`
}

type protocolProducerInvite struct {
	Body              protocolProducerBody `json:"body"`
	NodeSignature     string               `json:"node_signature"`
	OwnerSignature    string               `json:"owner_signature"`
	ProducerSignature string               `json:"producer_signature"`
}

type financialProtocolGenesis struct {
	Committee              publicCommittee          `json:"committee"`
	Economics              economicPolicy           `json:"economics"`
	Environment            string                   `json:"environment"`
	ExpectedBlocksPerEpoch uint64                   `json:"expected_blocks_per_epoch,string"`
	InitialProducers       []protocolProducerInvite `json:"initial_producers"`
	InitialWorkTarget      string                   `json:"initial_work_target"`
	MaxCommitteeChangeBPS  uint32                   `json:"max_committee_change_bps"`
	MaxEpochParticipants   uint64                   `json:"max_epoch_participants,string"`
	MaxProducerEntries     uint64                   `json:"max_producer_entries,string"`
	MaxWorkHeights         uint64                   `json:"max_work_heights,string"`
	MaxWorkTarget          string                   `json:"max_work_target"`
	MinWorkTarget          string                   `json:"min_work_target"`
	RegistrationWorkTarget string                   `json:"registration_work_target"`
	Schema                 string                   `json:"schema"`
}

type protocolProducerRecord struct {
	Attempts uint64                 `json:"attempts,string"`
	Epoch    uint64                 `json:"epoch,string"`
	Head     string                 `json:"head"`
	Invite   protocolProducerInvite `json:"invite"`
	Rank     uint64                 `json:"rank,string"`
	Schema   string                 `json:"schema"`
	Sequence uint64                 `json:"sequence,string"`
}

type protocolReservedRole struct {
	Owner  string `json:"owner_peer_key"`
	Role   string `json:"role"`
	Schema string `json:"schema"`
}

type financialProtocolCommitment struct {
	Committee        publicCommittee      `json:"committee"`
	Economics        economicState        `json:"economics"`
	FeePot           string               `json:"fee_pot_atomic"`
	LastSettlement   string               `json:"last_settlement"`
	OperationRoot    protocolRegistryLink `json:"operation_root"`
	PendingCommittee *committeeChangePlan `json:"pending_committee,omitempty"`
	ProducerRoot     protocolRegistryLink `json:"producer_root"`
	RewardRoot       protocolRegistryLink `json:"reward_root"`
	RoleRoot         protocolRegistryLink `json:"role_root"`
	Schema           string               `json:"schema"`
	Settlements      uint64               `json:"settlements,string"`
	TimeNs           string               `json:"time_ns"`
	WorkAnchorHeight uint64               `json:"work_anchor_height,string"`
	WorkAnchorRoot   string               `json:"work_anchor_root"`
	WorkBlocks       uint64               `json:"work_blocks,string"`
	WorkRoot         protocolRegistryLink `json:"work_root"`
	WorkTarget       string               `json:"work_target"`
}

type protocolRewardReceipt struct {
	BeforeIssued  string               `json:"before_issued_atomic"`
	ClosedThrough uint64               `json:"closed_through_epoch,string"`
	Credits       []economicCredit     `json:"credits,omitempty"`
	CreditsCount  int                  `json:"credits_count"`
	CreditsRoot   string               `json:"credits_root"`
	Epoch         uint64               `json:"epoch,string"`
	Fees          string               `json:"fees_atomic"`
	Genesis       string               `json:"genesis_hash"`
	Index         uint64               `json:"index,string"`
	Minted        string               `json:"minted_atomic"`
	NextIssued    string               `json:"next_issued_atomic"`
	Schema        string               `json:"schema"`
	WorkRoot      protocolRegistryLink `json:"work_root"`
}

type financialProtocolExecution struct {
	genesis                                     Genesis
	height                                      uint64
	state                                       financialProtocolCommitment
	producers, roles, work, rewards, operations protocolRegistryTree
	pendingRewards                              map[string]protocolRewardReceipt
}

func publicFinancialProtocol(genesis Genesis) bool {
	return genesis.Protocol != nil && genesis.FinancialDAG != nil && genesis.FinancialDAG.Schema == financialProtocolSourceSchema
}

func (source financialDagSource) hasProtocol() bool {
	return source.Schema == financialProtocolSourceSchema
}

func protocolRegistryRulesFor(genesis Genesis, anchor, namespace string) (protocolRegistryRules, error) {
	if !publicFinancialProtocol(genesis) || !pubPattern.MatchString(anchor) {
		return protocolRegistryRules{}, errFinancialProtocol
	}
	maximum := genesis.Protocol.MaxProducerEntries
	if namespace == "roles" {
		maximum = 1 << 32
	}
	if namespace == "epoch_work" {
		maximum = genesis.Protocol.MaxEpochParticipants
	}
	if namespace == "rewards" || namespace == "operations" {
		maximum = 1 << 32
	}
	rules := protocolRegistryRules{Genesis: anchor, MaxEntries: maximum, MaxValueBytes: 4096, Namespace: namespace, Schema: "gg.protocol.registry-rules.v1"}
	if !rules.valid() {
		return rules, errFinancialProtocol
	}
	return rules, nil
}

func checkProtocolProducerInvite(invite protocolProducerInvite, genesis Genesis) error {
	body := invite.Body
	if genesis.FinancialDAG == nil || body.Schema != "gg.financial.producer-registration.v1" || body.UnusedKeyPolicy != protocolUnusedKeyPolicy || body.ChainID != genesis.ChainID || body.NetworkID != genesis.FinancialDAG.NetworkID ||
		!pubPattern.MatchString(body.Nonce) || len(canonical(invite)) > 4096 {
		return errFinancialProtocol
	}
	if body.Platform != "windows" && body.Platform != "linux" && body.Platform != "termux" && body.Platform != "other" {
		return errFinancialProtocol
	}
	label, err := base64.StdEncoding.DecodeString(body.LabelUTF8)
	if err != nil || base64.StdEncoding.EncodeToString(label) != body.LabelUTF8 || len(label) == 0 || len(label) > 96 || !utf8.Valid(label) {
		return errFinancialProtocol
	}
	for _, r := range string(label) {
		if r < 32 || r == 127 {
			return errFinancialProtocol
		}
	}
	seen := map[string]bool{}
	for _, key := range []string{body.NodeKey, body.OwnerPeerKey, body.ProducerKey, body.RewardAccount} {
		if !financialAccountAddress(key) || seen[key] {
			return errFinancialProtocol
		}
		seen[key] = true
	}
	message := append([]byte("GG-FINANCIAL-PRODUCER-REGISTRATION-v1\x00"), canonical(body)...)
	for index, key := range []string{body.NodeKey, body.OwnerPeerKey, body.ProducerKey} {
		signatures := []string{invite.NodeSignature, invite.OwnerSignature, invite.ProducerSignature}
		raw, _ := hex.DecodeString(key)
		signature, err := hex.DecodeString(signatures[index])
		if err != nil || len(signatures[index]) != 128 || hex.EncodeToString(signature) != signatures[index] || !verifyTransactionSignature(raw, message, signature) {
			return errFinancialProtocol
		}
	}
	return nil
}

func validateFinancialProtocolGenesis(genesis Genesis) error {
	policy := genesis.Protocol
	if policy == nil || !publicFinancialProtocol(genesis) {
		return errFinancialProtocol
	}
	// Leave room for the actual SDK header, state and a selected path in a
	// bounded light proof. Larger rosters enter through certified registration.
	if len(canonical(genesis)) > 64*1024 {
		return errFinancialProtocol
	}
	if policy != nil && policy.Economics.TreasuryBPS > 0 && policy.MaxEpochParticipants >= economicMaxRecipients {
		return errFinancialProtocol
	}
	fee, feeErr := economicMinimumFee(policy.Economics, 128*1024)
	maximum, _ := economicAmount(policy.Economics.MaxSupply)
	initial, _ := economicAmount(policy.Economics.InitialSupply)
	reward, _ := economicAmount(policy.Economics.EpochReward)
	if feeErr != nil || fee >= maximum || genesis.FinancialAccounts == nil || genesis.FinancialAccounts.MaxAccounts < 2 || initial == 0 && reward == 0 {
		return errFinancialProtocol
	}
	if !publicFinancialProtocol(genesis) || genesis.GenesisTime <= 0 || genesis.GenesisTime > (int64(dagSegmentCounterMax)-5000000000)/1000000000 || policy.Schema != "gg.financial.protocol-genesis.v1" || !policy.Economics.valid() ||
		(policy.Environment != "TESTNET" && policy.Environment != "MAINNET") || !policy.Committee.valid() || policy.Committee.Epoch != 0 || len(policy.Committee.Members) > 64 ||
		policy.MaxCommitteeChangeBPS == 0 || policy.MaxCommitteeChangeBPS > 3333 || policy.MaxProducerEntries < 1 || policy.MaxProducerEntries > 1<<32 ||
		policy.MaxEpochParticipants < 1 || policy.MaxEpochParticipants > economicMaxRecipients || policy.MaxWorkHeights < 8 || policy.MaxWorkHeights > 65536 ||
		policy.ExpectedBlocksPerEpoch < 1 || policy.ExpectedBlocksPerEpoch > 1000000000 || policy.InitialProducers == nil || len(policy.InitialProducers) < 1 ||
		len(policy.InitialProducers) > 128 || uint64(len(policy.InitialProducers)) > policy.MaxProducerEntries || len(genesis.Validators) != len(policy.Committee.Members) ||
		len(genesis.FinancialDAG.Producers) != len(policy.InitialProducers) || genesis.Membership != nil || genesis.SupplyAtomic != policy.Economics.InitialSupply ||
		genesis.FinancialDAG.StartedAtNs != strconv.FormatInt(genesis.GenesisTime*1000000000, 10) {
		return errFinancialProtocol
	}
	for _, target := range []string{policy.InitialWorkTarget, policy.MinWorkTarget, policy.MaxWorkTarget, policy.RegistrationWorkTarget} {
		if !pubPattern.MatchString(target) || target == DagZero {
			return errFinancialProtocol
		}
	}
	if policy.InitialWorkTarget < policy.MinWorkTarget || policy.InitialWorkTarget > policy.MaxWorkTarget || policy.RegistrationWorkTarget > policy.MaxWorkTarget {
		return errFinancialProtocol
	}
	for index, member := range policy.Committee.Members {
		if member.ValidatorKey != genesis.Validators[index] {
			return errFinancialProtocol
		}
	}
	previous := ""
	roles := map[string]protocolReservedRole{}
	wallets := map[string]bool{}
	reserve := func(key, owner, role string) bool {
		value := protocolReservedRole{Owner: owner, Role: role, Schema: "gg.financial.reserved-role.v1"}
		if prior, exists := roles[key]; exists && prior != value {
			return false
		}
		roles[key] = value
		return true
	}
	for _, member := range policy.Committee.Members {
		if !reserve(member.ValidatorKey, member.OwnerPeerKey, "VALIDATOR") || !reserve(member.NodeKey, member.OwnerPeerKey, "NODE") || !reserve(member.OwnerPeerKey, member.OwnerPeerKey, "OWNER") {
			return errFinancialProtocol
		}
		if !reserve(member.AccountKey, member.OwnerPeerKey, "GOVERNANCE") {
			return errFinancialProtocol
		}
		wallets[member.AccountKey] = true
	}
	if genesis.FinancialAccounts != nil {
		for _, allocation := range genesis.FinancialAccounts.Allocations {
			wallets[allocation.Address] = true
		}
	}
	for index, invite := range policy.InitialProducers {
		body := invite.Body
		if checkProtocolProducerInvite(invite, genesis) != nil || body.ProducerKey <= previous || body.ProducerKey != genesis.FinancialDAG.Producers[index] ||
			!reserve(body.ProducerKey, body.OwnerPeerKey, "PRODUCER") || !reserve(body.NodeKey, body.OwnerPeerKey, "NODE") || !reserve(body.OwnerPeerKey, body.OwnerPeerKey, "OWNER") {
			return errFinancialProtocol
		}
		wallets[body.RewardAccount] = true
		previous = body.ProducerKey
	}
	if policy.Economics.TreasuryBPS > 0 {
		wallets[policy.Economics.TreasuryAccount] = true
	}
	for address := range wallets {
		if role, reserved := roles[address]; reserved && role.Role != "GOVERNANCE" {
			return errFinancialProtocol
		}
	}
	if genesis.FinancialAccounts == nil || uint64(len(wallets)) > genesis.FinancialAccounts.MaxAccounts {
		return errFinancialProtocol
	}
	return nil
}

func genesisValidatorPower(genesis Genesis, index int) int64 {
	if publicFinancialProtocol(genesis) {
		if index < 0 || index >= len(genesis.Protocol.Committee.Members) {
			return 0
		}
		power, ok := economicAmount(genesis.Protocol.Committee.Members[index].Power)
		if !ok || power >= 1<<50 {
			return 0
		}
		return int64(power)
	}
	return 1
}

func (protocol *financialProtocolExecution) clone() *financialProtocolExecution {
	if protocol == nil {
		return nil
	}
	copy := *protocol
	copy.state.Committee.Members = append([]publicConsensusMember(nil), protocol.state.Committee.Members...)
	if protocol.state.PendingCommittee != nil {
		pending := *protocol.state.PendingCommittee
		pending.Next.Members = append([]publicConsensusMember(nil), pending.Next.Members...)
		copy.state.PendingCommittee = &pending
	}
	copy.pendingRewards = make(map[string]protocolRewardReceipt, len(protocol.pendingRewards))
	for key, value := range protocol.pendingRewards {
		copy.pendingRewards[key] = value
	}
	return &copy
}

func (protocol *financialProtocolExecution) commitment() financialProtocolCommitment {
	value := protocol.state
	value.Committee.Members = append([]publicConsensusMember(nil), value.Committee.Members...)
	value.ProducerRoot, value.WorkRoot, value.RewardRoot = protocol.producers.root.link, protocol.work.root.link, protocol.rewards.root.link
	value.RoleRoot = protocol.roles.root.link
	value.OperationRoot = protocol.operations.root.link
	return value
}

func initialFinancialProtocol(ctx context.Context, genesis Genesis, anchor string) (*financialProtocolExecution, error) {
	if validateFinancialProtocolGenesis(genesis) != nil {
		return nil, errFinancialProtocol
	}
	producers, err := protocolRegistryRulesFor(genesis, anchor, "producers")
	if err != nil {
		return nil, err
	}
	roles, err := protocolRegistryRulesFor(genesis, anchor, "roles")
	if err != nil {
		return nil, err
	}
	work, err := protocolRegistryRulesFor(genesis, anchor, "epoch_work")
	if err != nil {
		return nil, err
	}
	rewards, err := protocolRegistryRulesFor(genesis, anchor, "rewards")
	if err != nil {
		return nil, err
	}
	p := &financialProtocolExecution{genesis: genesis, pendingRewards: map[string]protocolRewardReceipt{}}
	if p.producers, err = newProtocolRegistry(producers); err != nil {
		return nil, err
	}
	if p.roles, err = newProtocolRegistry(roles); err != nil {
		return nil, err
	}
	if p.work, err = newProtocolRegistry(work); err != nil {
		return nil, err
	}
	if p.rewards, err = newProtocolRegistry(rewards); err != nil {
		return nil, err
	}
	operationRules, err := protocolRegistryRulesFor(genesis, anchor, "operations")
	if err != nil {
		return nil, err
	}
	if p.operations, err = newProtocolRegistry(operationRules); err != nil {
		return nil, err
	}
	economy, err := initialEconomicState(genesis.Protocol.Economics, anchor)
	if err != nil {
		return nil, err
	}
	p.state = financialProtocolCommitment{Committee: genesis.Protocol.Committee, Economics: economy, FeePot: "0", LastSettlement: DagZero,
		Schema: "gg.financial.protocol-state.v1", TimeNs: genesis.FinancialDAG.StartedAtNs, WorkAnchorRoot: anchor, WorkTarget: genesis.Protocol.InitialWorkTarget}
	origin := financialDagOrigin(*genesis.FinancialDAG, anchor)
	for _, invite := range genesis.Protocol.InitialProducers {
		record := protocolProducerRecord{Head: origin, Invite: invite, Schema: "gg.financial.producer-state.v1"}
		p.producers, err = p.producers.set(ctx, invite.Body.ProducerKey, canonical(record))
		if err != nil {
			return nil, err
		}
		if err = p.reserveProducerRoles(ctx, invite); err != nil {
			return nil, err
		}
	}
	for _, member := range genesis.Protocol.Committee.Members {
		if err = p.reserveRole(ctx, member.AccountKey, member.OwnerPeerKey, "GOVERNANCE"); err != nil {
			return nil, err
		}
		if err = p.reserveRole(ctx, member.ValidatorKey, member.OwnerPeerKey, "VALIDATOR"); err != nil {
			return nil, err
		}
		if err = p.reserveRole(ctx, member.NodeKey, member.OwnerPeerKey, "NODE"); err != nil {
			return nil, err
		}
		if err = p.reserveRole(ctx, member.OwnerPeerKey, member.OwnerPeerKey, "OWNER"); err != nil {
			return nil, err
		}
	}
	return p, nil
}

func (protocol *financialProtocolExecution) reserveProducerRoles(ctx context.Context, invite protocolProducerInvite) error {
	body := invite.Body
	if err := protocol.reserveRole(ctx, body.ProducerKey, body.OwnerPeerKey, "PRODUCER"); err != nil {
		return err
	}
	if err := protocol.reserveRole(ctx, body.NodeKey, body.OwnerPeerKey, "NODE"); err != nil {
		return err
	}
	if err := protocol.reserveRole(ctx, body.OwnerPeerKey, body.OwnerPeerKey, "OWNER"); err != nil {
		return err
	}
	return nil
}

func (protocol *financialProtocolExecution) reserveRole(ctx context.Context, key, owner, role string) error {
	if !financialAccountAddress(key) || !financialAccountAddress(owner) {
		return errFinancialProtocol
	}
	value := protocolReservedRole{Owner: owner, Role: role, Schema: "gg.financial.reserved-role.v1"}
	raw, exists, err := protocol.roles.get(ctx, key)
	if err != nil {
		return err
	}
	if exists && !bytes.Equal(raw, canonical(value)) {
		return errFinancialProtocol
	}
	protocol.roles, err = protocol.roles.set(ctx, key, canonical(value))
	return err
}

func (protocol *financialProtocolExecution) producer(ctx context.Context, key string, genesis Genesis) (protocolProducerRecord, error) {
	raw, exists, err := protocol.producers.get(ctx, key)
	var record protocolProducerRecord
	if err != nil || !exists || decodeStrict(raw, &record) != nil || !bytes.Equal(raw, canonical(record)) || record.Schema != "gg.financial.producer-state.v1" ||
		record.Invite.Body.ProducerKey != key || !pubPattern.MatchString(record.Head) || checkProtocolProducerInvite(record.Invite, genesis) != nil ||
		record.Attempts > dagSegmentCounterMax || record.Sequence > dagSegmentCounterMax || record.Epoch > dagSegmentCounterMax || record.Rank > dagSegmentCounterMax ||
		(record.Sequence == 0) != (record.Rank == 0) {
		return record, errFinancialProtocol
	}
	return record, nil
}

type protocolEpochWeight struct {
	Epoch  uint64 `json:"epoch,string"`
	Weight string `json:"weight"`
}

func (protocol *financialProtocolExecution) recordWork(ctx context.Context, share verifiedMiningShare, genesis Genesis) error {
	if !share.verified || !share.networkWork || share.networkWeight == nil || share.networkWeight.Sign() <= 0 || share.epoch != protocol.state.Economics.NextEpoch {
		return errFinancialProtocol
	}
	raw, exists, err := protocol.work.get(ctx, share.rewardAccount)
	if err != nil {
		return err
	}
	weight := new(big.Int)
	if exists {
		var prior protocolEpochWeight
		if decodeStrict(raw, &prior) != nil || !bytes.Equal(raw, canonical(prior)) || prior.Epoch != share.epoch {
			return errFinancialProtocol
		}
		var ok bool
		weight, ok = economicWorkWeight(prior.Weight)
		if !ok {
			return errFinancialProtocol
		}
	} else if protocol.work.root.link.Count >= genesis.Protocol.MaxEpochParticipants {
		return errors.New("GG_REWARD_EPOCH_PARTICIPANT_LIMIT")
	}
	weight.Add(weight, share.networkWeight)
	if weight.BitLen() > 512 || protocol.state.WorkBlocks == dagSegmentCounterMax {
		return errFinancialProtocol
	}
	updated, err := protocol.work.set(ctx, share.rewardAccount, canonical(protocolEpochWeight{Epoch: share.epoch, Weight: weight.String()}))
	if err != nil {
		return err
	}
	protocol.work = updated
	protocol.state.WorkBlocks++
	return nil
}

func (protocol *financialProtocolExecution) weights(ctx context.Context, maximum uint64) ([]economicWeight, error) {
	rows := make([]economicWeight, 0, int(protocol.work.root.link.Count))
	err := protocol.work.walk(ctx, maximum, func(key string, raw []byte) error {
		var value protocolEpochWeight
		if decodeStrict(raw, &value) != nil || !bytes.Equal(raw, canonical(value)) || value.Epoch != protocol.state.Economics.NextEpoch {
			return errFinancialProtocol
		}
		if _, ok := economicWorkWeight(value.Weight); !ok {
			return errFinancialProtocol
		}
		rows = append(rows, economicWeight{Address: key, Weight: value.Weight})
		return nil
	})
	return rows, err
}

func protocolRetarget(previous string, blocks uint64, policy financialProtocolGenesis) (string, error) {
	if !pubPattern.MatchString(previous) || policy.ExpectedBlocksPerEpoch == 0 {
		return "", errFinancialProtocol
	}
	target, ok := new(big.Int).SetString(previous, 16)
	if !ok || target.Sign() == 0 {
		return "", errFinancialProtocol
	}
	if blocks == 0 {
		blocks = 1
	}
	next := new(big.Int).Mul(new(big.Int).Set(target), new(big.Int).SetUint64(policy.ExpectedBlocksPerEpoch))
	next.Quo(next, new(big.Int).SetUint64(blocks))
	lower := new(big.Int).Quo(new(big.Int).Set(target), big.NewInt(4))
	upper := new(big.Int).Mul(new(big.Int).Set(target), big.NewInt(4))
	minimum, _ := new(big.Int).SetString(policy.MinWorkTarget, 16)
	maximum, _ := new(big.Int).SetString(policy.MaxWorkTarget, 16)
	if minimum == nil || maximum == nil {
		return "", errFinancialProtocol
	}
	if next.Cmp(lower) < 0 {
		next.Set(lower)
	}
	if next.Cmp(upper) > 0 {
		next.Set(upper)
	}
	if next.Cmp(minimum) < 0 {
		next.Set(minimum)
	}
	if next.Cmp(maximum) > 0 {
		next.Set(maximum)
	}
	text := next.Text(16)
	for len(text) < 64 {
		text = "0" + text
	}
	if !pubPattern.MatchString(text) {
		return "", errFinancialProtocol
	}
	return text, nil
}

func protocolRewardKey(index uint64) string {
	return hashHex([]byte("GG-FINANCIAL-REWARD-INDEX-v1\x00" + strconv.FormatUint(index, 10)))
}

func protocolRewardReceiptID(receipt protocolRewardReceipt) string {
	receipt.Credits = nil
	return hashHex(append([]byte("GG-FINANCIAL-REWARD-RECEIPT-v1\x00"), canonical(receipt)...))
}

func protocolCreditRoot(credits []economicCredit) string {
	return dagRoot(credits, "GG-FINANCIAL-REWARD-CREDITS-v1\x00")
}

func protocolSortedRewardAddresses(genesis Genesis) []string {
	seen := map[string]bool{}
	for _, invite := range genesis.Protocol.InitialProducers {
		seen[invite.Body.RewardAccount] = true
	}
	if genesis.Protocol.Economics.TreasuryBPS > 0 {
		seen[genesis.Protocol.Economics.TreasuryAccount] = true
	}
	keys := make([]string, 0, len(seen))
	for key := range seen {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	return keys
}

func financialProtocolRoot(value financialProtocolCommitment) string {
	return hashHex(append([]byte("GG-FINANCIAL-PROTOCOL-COMMITMENT-v1\x00"), canonical(value)...))
}

func copyFinancialProtocolCommitment(value financialProtocolCommitment) financialProtocolCommitment {
	value.Committee.Members = append([]publicConsensusMember(nil), value.Committee.Members...)
	if value.PendingCommittee != nil {
		pending := *value.PendingCommittee
		pending.Next.Members = append([]publicConsensusMember(nil), pending.Next.Members...)
		value.PendingCommittee = &pending
	}
	return value
}

func validateFinancialProtocolCommitment(state State, genesis Genesis, anchor string) error {
	if !publicFinancialProtocol(genesis) || state.Protocol == nil || state.AccountTree == nil || state.FinancialDAG == nil || state.FinancialDAG.ProducerRoot == nil || state.Height < 0 {
		return errFinancialProtocol
	}
	p := state.Protocol
	rules, err := economicRulesHash(genesis.Protocol.Economics, anchor)
	issued, ok := economicAmount(p.Economics.Issued)
	fees, fok := economicAmount(p.FeePot)
	total, tok := economicAmount(state.AccountTree.Total)
	when, validTime := dagDecimalNs(p.TimeNs)
	if err != nil || p.Schema != "gg.financial.protocol-state.v1" || p.Economics.Schema != "gg.financial.economic-state.v1" || p.Economics.RulesHash != rules ||
		!ok || !fok || !tok || issued < financialInitialSupply(genesis) || issued > financialMaximumSupply(genesis) || fees > issued || total != issued-fees ||
		!p.Committee.valid() || len(p.Committee.Members) > 64 || !validTime || when < genesis.GenesisTime*1000000000 || !pubPattern.MatchString(p.LastSettlement) ||
		p.WorkAnchorHeight > uint64(state.Height) || !pubPattern.MatchString(p.WorkAnchorRoot) || !pubPattern.MatchString(p.WorkTarget) ||
		p.WorkTarget < genesis.Protocol.MinWorkTarget || p.WorkTarget > genesis.Protocol.MaxWorkTarget || p.Settlements != p.RewardRoot.Count ||
		p.ProducerRoot != *state.FinancialDAG.ProducerRoot || p.ProducerRoot.Count < uint64(len(genesis.Protocol.InitialProducers)) || p.WorkBlocks < p.WorkRoot.Count || p.OperationRoot.Count != state.FinancialDAG.Operations {
		return errFinancialProtocol
	}
	epoch, err := economicEpochAt(genesis.Protocol.Economics, uint64(genesis.GenesisTime), uint64(when/1000000000))
	if err != nil || epoch != p.Economics.NextEpoch {
		return errFinancialProtocol
	}
	for _, item := range []struct {
		link      protocolRegistryLink
		namespace string
	}{{p.ProducerRoot, "producers"}, {p.RoleRoot, "roles"}, {p.WorkRoot, "epoch_work"}, {p.RewardRoot, "rewards"}, {p.OperationRoot, "operations"}} {
		rules, err := protocolRegistryRulesFor(genesis, anchor, item.namespace)
		if err != nil || !validProtocolRegistryLink(item.link, rules, rules.hash()) {
			return errFinancialProtocol
		}
	}
	if p.PendingCommittee != nil {
		plan, err := planCommitteeChange(p.Committee, p.PendingCommittee.Next, anchor, p.PendingCommittee.DecidedHeight, genesis.Protocol.MaxCommitteeChangeBPS)
		if err != nil || !bytes.Equal(canonical(plan), canonical(*p.PendingCommittee)) || uint64(state.Height) < plan.DecidedHeight || uint64(state.Height) >= plan.EffectiveHeight {
			return errFinancialProtocol
		}
	}
	return nil
}
