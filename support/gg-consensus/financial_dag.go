package main

// Financial DAG transition model. It authenticates real producer blocks and
// account-signed native payments. Authenticated immutable readers may resolve
// old topology/accounts on disk; the transition performs no durable writes and
// supplies no SDK certificate.
// Native activation/persistence must bind this source and complete transition;
// legacy genesis, block formats and nonfinancial sources are unchanged.
import (
	"context"
	"encoding/base64"
	"encoding/binary"
	"encoding/hex"
	"errors"
	"sort"
	"strconv"
)

const financialDagMaxBatchWire = 48 * 1024 * 1024

var errFinancialDag = errors.New("GG_FINANCIAL_DAG_CONTEXT")

type financialDagPolicy struct {
	AccountModel       string `json:"account_model"`
	ActiveMaxBlocks    int    `json:"active_max_blocks"`
	ActiveMaxWireBytes int    `json:"active_max_wire_bytes"`
	BlockMaxParents    int    `json:"block_max_parents"`
	BlockMaxPayments   int    `json:"block_max_payments"`
	BlockMaxWireBytes  int    `json:"block_max_wire_bytes"`
	Execution          string `json:"execution"`
	History            string `json:"history"`
	Schema             string `json:"schema"`
}

func financialDagRules() financialDagPolicy {
	return financialDagPolicy{AccountModel: "FIXED_NATIVE_FOUR_ACCOUNT_TEST_ALLOCATION", ActiveMaxBlocks: DagMaxRecords,
		ActiveMaxWireBytes: DagMaxHistoryWire, BlockMaxParents: DagMaxParents, BlockMaxPayments: financialMaxTransactions,
		BlockMaxWireBytes: DagMaxWire, Execution: "NATIVE_SIGNED_PAYMENTS_ORDERED_REJECTIONS_NO_FEES_OR_ISSUANCE",
		History: "ORIGINAL_SIGNED_SEGMENTS_AND_SDK_CERTIFIED_CUTS", Schema: "gg.financial-dag.policy.v1"}
}

// Deliberately excludes the completed native genesis hash: a future genesis
// can contain this definition without a circular hash. Blocks bind BOTH this
// source hash and the completed native anchor, supplied separately at runtime.
type financialDagSource struct {
	AllowedProducers []int              `json:"allowed_producers"`
	NativeChainID    string             `json:"native_chain_id"`
	NetworkID        string             `json:"network_id,omitempty"`
	Policy           financialDagPolicy `json:"policy"`
	Producers        []string           `json:"producers"`
	Schema           string             `json:"schema"`
	SignatureProfile string             `json:"signature_profile"`
	StartedAtNs      string             `json:"started_at_ns"`
}

func (source financialDagSource) hash() string {
	return dagDigest(financialDomain+"DAG-SOURCE\x00", source)
}

const financialLineageSourceSchema = "gg.financial-dag.source.v3"

func (source financialDagSource) hasLineage() bool {
	return source.Schema == financialLineageSourceSchema || source.hasGeneralAccounts()
}
func (source financialDagSource) hasGeneralAccounts() bool {
	return source.Schema == financialGeneralSourceSchema || source.hasProtocol()
}

func (source financialDagSource) rules() financialDagPolicy {
	policy := financialDagRules()
	if source.hasLineage() {
		policy.Schema = "gg.financial-dag.policy.v2"
		policy.History = "PERMANENT_AUTHENTICATED_TOPOLOGY_AND_SDK_CERTIFIED_CUTS"
	}
	if source.hasGeneralAccounts() {
		policy.Schema = "gg.financial-dag.policy.v3"
		policy.AccountModel = "GENERAL_NATIVE_ACCOUNT_TREE_TEST_ALLOCATION"
	}
	if source.hasProtocol() {
		policy.Schema = "gg.financial-dag.policy.v4"
		policy.AccountModel = "GENERAL_NATIVE_ACCOUNT_TREE_CAPPED_ECONOMY"
		policy.Execution = "NATIVE_ACCOUNT_PAYMENTS_FEES_WORK_AND_CAPPED_EPOCH_REWARDS"
	}
	return policy
}

func financialDagOrigin(source financialDagSource, anchor string) string {
	return dagDigest(financialDomain+"DAG-GENESIS\x00", struct {
		Anchor string `json:"anchor"`
		Source string `json:"source"`
	}{anchor, source.hash()})
}

func (source financialDagSource) validate(genesis Genesis, anchor string) error {
	if validateGenesis(genesis, anchor) != nil {
		return errFinancialDag
	}
	return source.validateShape(genesis)
}

func (source financialDagSource) validateShape(genesis Genesis) error {
	if genesis.checked != nil && genesis.checked.anchor == hashHex(canonical(genesis)) && genesis.FinancialDAG != nil && streamCanonicalEqual(canonical(source), *genesis.FinancialDAG) {
		return nil
	}
	networked := source.Schema == "gg.financial-dag.source.v2" || source.hasLineage()
	producerCountValid := len(source.Producers) == 6
	if source.hasProtocol() {
		producerCountValid = len(source.Producers) >= 1 && len(source.Producers) <= 128
		if len(source.AllowedProducers) != 0 {
			return errFinancialDag
		}
	}
	if !(source.Schema == "gg.financial-dag.source.v1" && source.NetworkID == "" || networked && pubPattern.MatchString(source.NetworkID)) || source.NativeChainID != genesis.ChainID ||
		source.Policy != source.rules() || source.SignatureProfile != TransactionSignatureProfile || !producerCountValid || source.AllowedProducers == nil ||
		genesis.GenesisTime > (int64(dagSegmentCounterMax)-5000000000)/1000000000 {
		return errFinancialDag
	}
	start, valid := dagDecimalNs(source.StartedAtNs)
	if !valid || start < genesis.GenesisTime*1000000000 || start > genesis.GenesisTime*1000000000+5000000000 {
		return errFinancialDag
	}
	seen := map[string]bool{}
	for _, key := range append(append([]string{}, genesis.Accounts...), genesis.Validators...) {
		seen[key] = true // producer authority is separate from native account/vote authority
	}
	if source.hasGeneralAccounts() {
		if validateFinancialAccountGenesis(genesis) != nil {
			return errFinancialDag
		}
		for _, allocation := range genesis.FinancialAccounts.Allocations {
			seen[allocation.Address] = true
		}
	} else if genesis.FinancialAccounts != nil {
		return errFinancialDag
	}
	for _, key := range source.Producers {
		raw, err := hex.DecodeString(key)
		if !pubPattern.MatchString(key) || err != nil || !validAuthorKey(raw) || seen[key] {
			return errFinancialDag
		}
		seen[key] = true
	}
	previous := -1
	for _, index := range source.AllowedProducers {
		if index <= previous || index < 0 || index >= len(source.Producers) {
			return errFinancialDag
		}
		previous = index
	}
	if source.hasProtocol() && validateFinancialProtocolGenesis(genesis) != nil {
		return errFinancialDag
	}
	return nil
}

type financialDagBlockBody struct {
	CreatedAtNs uint64     `json:"created_at_ns,string"`
	Epoch       uint64     `json:"epoch,string"`
	GenesisHash string     `json:"genesis_hash"`
	Parents     []string   `json:"parents"`
	PaymentRoot string     `json:"payment_root"`
	Payments    []Envelope `json:"payments"`
	Producer    int        `json:"producer_index"`
	Rank        uint64     `json:"rank,string"`
	Schema      string     `json:"schema"`
	Sequence    uint64     `json:"sequence,string"`
	SourceHash  string     `json:"source_hash"`
}

type financialDagBlock struct {
	Body      financialDagBlockBody `json:"body"`
	Signature string                `json:"signature"`
}

func financialDagPaymentRoot(payments []Envelope) string {
	root, _ := hex.DecodeString(dagRoot(payments, financialDomain+"DAG-PAYMENT-TREE\x00"))
	var count [8]byte
	binary.BigEndian.PutUint64(count[:], uint64(len(payments)))
	raw := append([]byte(financialDomain+"DAG-PAYMENT-ROOT\x00"), count[:]...)
	return hashHex(append(raw, root...))
}

type financialDagRecord struct {
	Block     financialDagBlock
	Hash      string
	Raw       []byte
	Receipts  []financialReceipt
	Summary   financialSummary
	Context   financialExecutionContext
	Creator   financialDagCreator
	Protocol  *financialProtocolBlock
	workShare *verifiedMiningShare
}

func decodeFinancialDagBlock(ctx context.Context, raw []byte, source financialDagSource, anchor string, epoch uint64, consensusTimeNs int64, protocol ...*financialProtocolExecution) (financialDagRecord, error) {
	if ctx.Err() != nil {
		return financialDagRecord{}, ctx.Err()
	}
	if source.hasProtocol() {
		return decodeFinancialProtocolBlock(ctx, raw, source, anchor, epoch, consensusTimeNs, protocol...)
	}
	var block financialDagBlock
	if len(raw) == 0 || len(raw) > DagMaxWire || decodeStrictLimited(raw, &block, financialMaxTransactions, 64) != nil || !streamCanonicalEqual(raw, block) {
		return financialDagRecord{}, errors.New("GG_FINANCIAL_DAG_BLOCK_ENCODING")
	}
	body := block.Body
	start, _ := dagDecimalNs(source.StartedAtNs)
	validEpoch := body.Epoch == epoch || source.hasLineage() && body.Epoch > 0 && body.Epoch < epoch
	if len(source.Producers) != 6 || body.Schema != "gg.financial-dag.block.v1" || body.GenesisHash != anchor || body.SourceHash != source.hash() || !validEpoch ||
		body.Producer < 0 || body.Producer >= 6 || body.Sequence < 1 || body.Sequence > dagSegmentCounterMax || body.Rank < 1 || body.Rank > dagSegmentCounterMax ||
		body.CreatedAtNs < uint64(start) || body.CreatedAtNs > dagSegmentCounterMax-5000000000 ||
		body.Payments == nil || len(body.Payments) > financialMaxTransactions || len(body.Parents) < 1 || len(body.Parents) > DagMaxParents {
		return financialDagRecord{}, errFinancialDag
	}
	allowed := sort.SearchInts(source.AllowedProducers, body.Producer)
	if allowed >= len(source.AllowedProducers) || source.AllowedProducers[allowed] != body.Producer {
		return financialDagRecord{}, errors.New("GG_FINANCIAL_DAG_PRODUCER_ROLE")
	}
	if consensusTimeNs < 0 || consensusTimeNs > int64(dagSegmentCounterMax)-5000000000 || consensusTimeNs > 0 && body.CreatedAtNs > uint64(consensusTimeNs)+5000000000 {
		return financialDagRecord{}, errors.New("GG_FINANCIAL_DAG_TIME")
	}
	for index, parent := range body.Parents {
		if !pubPattern.MatchString(parent) || index > 0 && parent <= body.Parents[index-1] {
			return financialDagRecord{}, errors.New("GG_FINANCIAL_DAG_PARENTS")
		}
	}
	if body.PaymentRoot != financialDagPaymentRoot(body.Payments) || len(block.Signature) != 128 {
		return financialDagRecord{}, errors.New("GG_FINANCIAL_DAG_PAYLOAD")
	}
	public, _ := hex.DecodeString(source.Producers[body.Producer])
	signature, err := hex.DecodeString(block.Signature)
	if err != nil || hex.EncodeToString(signature) != block.Signature ||
		!verifyTransactionSignature(public, append([]byte(financialDomain+"DAG-BLOCK-SIGN\x00"), canonical(body)...), signature) {
		return financialDagRecord{}, errors.New("GG_FINANCIAL_DAG_BLOCK_SIGNATURE")
	}
	if ctx.Err() != nil {
		return financialDagRecord{}, ctx.Err()
	}
	return financialDagRecord{Block: block, Hash: hashHex(append([]byte(financialDomain+"DAG-BLOCK\x00"), raw...)), Raw: raw}, nil
}

type financialDagAuthor struct {
	Attempts uint64 `json:"attempts,string"`
	Epoch    string `json:"epoch,omitempty"`
	Head     string `json:"head"`
	Key      string `json:"key"`
	Sequence uint64 `json:"sequence,string"`
}

type financialDagCommitment struct {
	AccountRoot     string                `json:"account_root"`
	AccountTree     *financialAccountLink `json:"account_tree,omitempty"`
	ActiveBlocks    int                   `json:"active_blocks"`
	ActiveBytes     uint64                `json:"active_bytes,string"`
	ActiveOrderRoot string                `json:"active_order_root"`
	Anchor          string                `json:"anchor"`
	Applied         uint64                `json:"applied,string"`
	Attempts        uint64                `json:"attempts,string"`
	Authors         []financialDagAuthor  `json:"authors,omitempty"`
	Blocks          uint64                `json:"blocks,string"`
	Checkpoint      uint64                `json:"checkpoint,string"`
	ClosedRoot      string                `json:"closed_root"`
	Epoch           uint64                `json:"epoch,string"`
	EpochBaseRank   string                `json:"epoch_base_rank,omitempty"`
	IndexRoot       string                `json:"index_root"`
	LastCut         string                `json:"last_cut"`
	LastRank        uint64                `json:"last_rank,string"`
	LineageRoot     string                `json:"lineage_root,omitempty"`
	Operations      uint64                `json:"operations,string,omitempty"`
	Previous        string                `json:"previous"`
	ProducerRoot    *protocolRegistryLink `json:"producer_root,omitempty"`
	RawBytes        uint64                `json:"raw_bytes,string"`
	ReceiptsRoot    string                `json:"receipts_root"`
	Rejected        uint64                `json:"rejected,string"`
	Schema          string                `json:"schema"`
	SourceHash      string                `json:"source_hash"`
	SummaryIndex    string                `json:"summary_index"`
	TimeNs          string                `json:"time_ns"`
}

type financialDagExecution struct {
	genesis      Genesis
	source       financialDagSource
	anchor       string
	money        financialMoneyState
	history      dagHistory
	lineage      dagHistory // source-v3: all selected headers; native store bounds RAM through its disk reader
	summaries    dagHistory
	order        dagOrderAccumulator
	receipts     dagClosedSegments // authenticated financial summary IDs, not legacy cuts
	closed       dagClosedSegments
	pending      map[string]financialDagRecord
	heads        []string
	authors      []financialDagAuthor
	epoch        uint64
	epochAnchor  string
	rankBase     uint64
	lastRank     uint64
	blocks       uint64
	operations   uint64
	activeBlocks int
	activeBytes  uint64
	rawBytes     uint64
	attempts     uint64
	applied      uint64
	rejected     uint64
	checkpoint   uint64
	previous     string
	timeNs       int64
	provisional  bool
}

func newFinancialDagExecution(genesis Genesis, anchor string, source financialDagSource) (*financialDagExecution, error) {
	if genesis.FinancialDAG != nil && !streamCanonicalEqual(canonical(source), *genesis.FinancialDAG) {
		return nil, errFinancialDag
	}
	if source.validate(genesis, anchor) != nil {
		return nil, errFinancialDag
	}
	var owned Genesis
	if decodeStrict(canonical(genesis), &owned) != nil {
		return nil, errFinancialDag
	}
	owned.checked = &checkedGenesisContext{anchor: anchor, reserved: checkedGenesisReservedKeys(owned)}
	source.Producers = append([]string{}, source.Producers...)
	source.AllowedProducers = append([]int{}, source.AllowedProducers...)
	money, err := initialFinancialMoney(owned, anchor)
	if err != nil {
		return nil, err
	}
	start, _ := dagDecimalNs(source.StartedAtNs)
	genesisID := financialDagOrigin(source, anchor)
	execution := &financialDagExecution{genesis: owned, source: source, anchor: anchor,
		money:   money,
		history: dagHistory{segmented: true, protocol: source.hasProtocol()}, lineage: dagHistory{segmented: true, protocol: source.hasProtocol()}, summaries: dagHistory{segmented: true, protocol: source.hasProtocol()}, pending: map[string]financialDagRecord{},
		epoch: 1, epochAnchor: genesisID, previous: DagZero, timeNs: start}
	if !source.hasProtocol() {
		execution.heads = make([]string, len(source.Producers))
		execution.authors = make([]financialDagAuthor, len(source.Producers))
	}
	for index, key := range source.Producers {
		if source.hasProtocol() {
			break
		}
		execution.heads[index] = genesisID
		execution.authors[index] = financialDagAuthor{Key: key, Head: genesisID}
		if source.Schema != "gg.financial-dag.source.v1" {
			execution.authors[index].Epoch = "0"
		}
	}
	return execution, nil
}

func (execution *financialDagExecution) commitment() (financialDagCommitment, error) {
	if execution == nil || (!execution.source.hasProtocol() && (len(execution.source.Producers) != 6 || len(execution.authors) != 6 || len(execution.heads) != 6)) || execution.source.Policy != execution.source.rules() || execution.source.NativeChainID != execution.genesis.ChainID ||
		execution.epoch < 1 || execution.epoch > dagSegmentCounterMax || execution.closed.count != execution.epoch-1 ||
		execution.blocks > dagSegmentCounterMax || execution.attempts > dagSegmentCounterMax || execution.applied > execution.attempts ||
		execution.rejected != execution.attempts-execution.applied || execution.receipts.count != execution.blocks ||
		execution.activeBlocks < 0 || execution.activeBlocks > DagMaxRecords || execution.activeBytes > DagMaxHistoryWire ||
		uint64(execution.activeBlocks) > execution.blocks || execution.rawBytes > dagSegmentCounterMax || execution.rawBytes < execution.blocks ||
		execution.activeBytes > execution.rawBytes || execution.activeBytes < uint64(execution.activeBlocks) || execution.order.count != uint64(execution.activeBlocks) ||
		execution.lastRank > execution.blocks || !execution.source.hasLineage() && execution.epoch-1 > execution.lastRank || execution.checkpoint > dagSegmentCounterMax ||
		execution.operations > dagSegmentCounterMax || !execution.source.hasProtocol() && execution.operations != 0 ||
		execution.checkpoint < execution.epoch-1 || execution.checkpoint-(execution.epoch-1) > execution.blocks+execution.operations ||
		execution.blocks <= dagSegmentCounterMax/financialMaxTransactions && execution.attempts > execution.blocks*financialMaxTransactions ||
		execution.timeNs < 1000000000 || execution.timeNs > int64(dagSegmentCounterMax)-5000000000 ||
		validateFinancialMoney(execution.money, execution.genesis, execution.anchor) != nil {
		return financialDagCommitment{}, errFinancialDag
	}
	sequences, attempts := uint64(0), uint64(0)
	for index, author := range execution.authors {
		if author.Key != execution.source.Producers[index] || !pubPattern.MatchString(author.Head) || author.Sequence > execution.blocks-sequences || author.Attempts > execution.attempts-attempts ||
			author.Sequence <= dagSegmentCounterMax/financialMaxTransactions && author.Attempts > author.Sequence*financialMaxTransactions {
			return financialDagCommitment{}, errFinancialDag
		}
		sequences += author.Sequence
		attempts += author.Attempts
	}
	if !execution.source.hasProtocol() && (sequences != execution.blocks || attempts != execution.attempts) {
		return financialDagCommitment{}, errFinancialDag
	}
	closed, err := execution.closed.root()
	if err != nil {
		return financialDagCommitment{}, err
	}
	receipts, err := execution.receipts.root()
	if err != nil {
		return financialDagCommitment{}, err
	}
	value := financialDagCommitment{AccountRoot: execution.money.AccountRoot, ActiveBlocks: execution.activeBlocks, ActiveBytes: execution.activeBytes,
		ActiveOrderRoot: execution.order.root(), Anchor: execution.anchor, Applied: execution.applied, Attempts: execution.attempts,
		Authors: append([]financialDagAuthor(nil), execution.authors...), Blocks: execution.blocks, Checkpoint: execution.checkpoint, ClosedRoot: closed, Epoch: execution.epoch,
		IndexRoot: execution.history.root.id(), LastCut: execution.epochAnchor, LastRank: execution.lastRank, Previous: execution.previous,
		RawBytes: execution.rawBytes, ReceiptsRoot: receipts, Rejected: execution.rejected, Schema: "gg.financial-dag.commitment.v1",
		SourceHash: execution.source.hash(), SummaryIndex: execution.summaries.root.id(), TimeNs: strconv.FormatInt(execution.timeNs, 10)}
	if execution.source.Schema != "gg.financial-dag.source.v1" {
		value.Schema = "gg.financial-dag.commitment.v2"
		value.EpochBaseRank = strconv.FormatUint(execution.rankBase, 10)
	}
	if execution.source.hasLineage() {
		value.Schema = "gg.financial-dag.commitment.v3"
		value.LineageRoot = execution.lineage.root.id()
	}
	if execution.source.hasGeneralAccounts() {
		root := execution.money.Tree.root.link
		value.AccountTree = &root
		value.Schema = "gg.financial-dag.commitment.v4"
	}
	if execution.source.hasProtocol() {
		root := execution.money.Protocol.producers.root.link
		value.ProducerRoot = &root
		value.Operations = execution.operations
		value.Schema = "gg.financial-dag.commitment.v5"
	}
	if err := validateFinancialVersionFields(value, execution.source); err != nil {
		return financialDagCommitment{}, err
	}
	return value, nil
}

func (execution *financialDagExecution) commitmentHash() (string, error) {
	value, err := execution.commitment()
	if err != nil {
		return "", err
	}
	return dagDigest(financialDomain+"DAG-COMMITMENT\x00", value), nil
}

func (execution *financialDagExecution) clone() *financialDagExecution {
	next := *execution
	next.heads = append([]string(nil), execution.heads...)
	next.authors = append([]financialDagAuthor(nil), execution.authors...)
	next.money.Protocol = execution.money.Protocol.clone()
	next.pending = map[string]financialDagRecord{}
	return &next
}

type financialDagBatch struct {
	Blocks      []string            `json:"blocks"`
	GenesisHash string              `json:"genesis_hash"`
	Operations  []protocolOperation `json:"operations,omitempty"`
	Previous    string              `json:"previous"`
	Schema      string              `json:"schema"`
	Sequence    uint64              `json:"sequence,string"`
	SourceHash  string              `json:"source_hash"`
}

// consensusTimeNs==0 computes mempool admissibility only. Its provisional
// result cannot be chained or cut and must never be persisted as certified.
func (execution *financialDagExecution) applyBatch(ctx context.Context, raw []byte, consensusTimeNs int64) (*financialDagExecution, error) {
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	before, err := execution.commitmentHash()
	if err != nil || execution.provisional || execution.checkpoint == dagSegmentCounterMax {
		return nil, errFinancialDag
	}
	var batch financialDagBatch
	expectedSchema := "gg.financial-dag.batch.v1"
	if execution.source.hasProtocol() {
		expectedSchema = "gg.financial-dag.batch.v2"
	}
	if len(raw) == 0 || len(raw) > financialDagMaxBatchWire || decodeStrictLimited(raw, &batch, DagMaxBatchBlocks, 64) != nil || !streamCanonicalEqual(raw, batch) ||
		batch.Schema != expectedSchema || batch.GenesisHash != execution.anchor || batch.SourceHash != execution.source.hash() || batch.Previous != before ||
		batch.Sequence != execution.checkpoint+1 || batch.Blocks == nil || len(batch.Blocks)+len(batch.Operations) < 1 || len(batch.Blocks) > DagMaxBatchBlocks ||
		len(batch.Operations) > protocolMaxOperations || !execution.source.hasProtocol() && batch.Operations != nil ||
		consensusTimeNs < 0 || consensusTimeNs > int64(dagSegmentCounterMax)-5000000000 || consensusTimeNs > 0 && consensusTimeNs < execution.timeNs {
		return nil, errors.New("GG_FINANCIAL_DAG_BATCH")
	}
	next := execution.clone()
	next.previous, next.checkpoint = before, batch.Sequence
	next.provisional = consensusTimeNs == 0
	if consensusTimeNs > 0 {
		next.timeNs = consensusTimeNs
	}
	if next.source.hasProtocol() && consensusTimeNs == 0 {
		if next.money.Protocol.height == dagSegmentCounterMax {
			return nil, errFinancialProtocol
		}
		next.money.Protocol.height++
	}
	previousOperation := ""
	for _, operation := range batch.Operations {
		id := hashHex(canonical(operation))
		if id <= previousOperation {
			return nil, errors.New("GG_PROTOCOL_OPERATION_ORDER")
		}
		if err := next.applyProtocolOperation(ctx, operation); err != nil {
			return nil, err
		}
		previousOperation = id
	}
	remaining, previousRank, previousHash := DagMaxWire, uint64(0), ""
	for _, encoded := range batch.Blocks {
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		if len(encoded) > (remaining+2)/3*4 {
			return nil, errors.New("GG_FINANCIAL_DAG_BATCH_LIMIT")
		}
		wire, err := base64.StdEncoding.Strict().DecodeString(encoded)
		if err != nil || len(wire) > remaining || base64.StdEncoding.EncodeToString(wire) != encoded {
			return nil, errors.New("GG_FINANCIAL_DAG_BATCH_ENCODING")
		}
		remaining -= len(wire)
		record, err := decodeFinancialDagBlock(ctx, wire, next.source, next.anchor, next.epoch, consensusTimeNs, next.money.Protocol)
		if err != nil {
			return nil, err
		}
		if record.Block.Body.Rank < previousRank || record.Block.Body.Rank == previousRank && record.Hash <= previousHash {
			return nil, errors.New("GG_FINANCIAL_DAG_BATCH_ORDER")
		}
		if err := next.admit(ctx, record); err != nil {
			return nil, err
		}
		previousRank, previousHash = record.Block.Body.Rank, record.Hash
	}
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	if _, err := next.commitment(); err != nil {
		return nil, err
	}
	return next, nil
}

func (execution *financialDagExecution) admit(ctx context.Context, record financialDagRecord) error {
	body := record.Block.Body
	var producer protocolProducerRecord
	var author financialDagAuthor
	if execution.source.hasProtocol() {
		if record.Protocol == nil || record.workShare == nil || !record.workShare.verified || !record.workShare.networkWork {
			return errFinancialProtocol
		}
		var err error
		producer, err = execution.money.Protocol.producer(ctx, record.Protocol.Body.ProducerKey, execution.genesis)
		if err != nil {
			return err
		}
		author = financialDagAuthor{Key: producer.Invite.Body.ProducerKey, Head: producer.Head, Sequence: producer.Sequence, Attempts: producer.Attempts}
	} else {
		if body.Producer < 0 || body.Producer >= len(execution.authors) {
			return errFinancialDag
		}
		author = execution.authors[body.Producer]
	}
	// Legacy cuts preserve the last actual author's block in the commitment,
	// while the next causal parent moves to this epoch's cut anchor. The
	// separate heads table carries that existing schema-specific parent rule.
	// Dynamic protocol producers retain their authenticated registry lineage.
	ownHead := author.Head
	if !execution.source.hasProtocol() {
		ownHead = execution.heads[body.Producer]
	}
	if execution.activeBlocks >= DagMaxRecords || uint64(len(record.Raw)) > DagMaxHistoryWire-execution.activeBytes ||
		execution.blocks == dagSegmentCounterMax || execution.rawBytes > dagSegmentCounterMax-uint64(len(record.Raw)) ||
		execution.attempts > dagSegmentCounterMax-uint64(len(body.Payments)) || author.Sequence == dagSegmentCounterMax {
		return errors.New("GG_FINANCIAL_DAG_HISTORY_LIMIT")
	}
	parents := execution.history
	if execution.source.hasLineage() {
		parents = execution.lineage
	}
	if _, exists, err := parents.get("b/" + record.Hash); err != nil {
		return err
	} else if exists {
		return errors.New("GG_FINANCIAL_DAG_DUPLICATE")
	}
	maximum, ownsParent := uint64(0), false
	for _, parent := range body.Parents {
		var rank uint64
		if execution.source.hasLineage() && parent == financialDagOrigin(execution.source, execution.anchor) {
			rank = 0
		} else if !execution.source.hasLineage() && parent == execution.epochAnchor {
			rank = execution.rankBase
		} else {
			value, exists, err := parents.get("b/" + parent)
			if err != nil {
				return err
			}
			if !exists || value.Record == nil {
				return errors.New("GG_FINANCIAL_DAG_UNKNOWN_PARENT")
			}
			rank = uint64(value.Record.Rank)
		}
		if rank > maximum {
			maximum = rank
		}
		ownsParent = ownsParent || parent == ownHead
	}
	if maximum == dagSegmentCounterMax || body.Rank != maximum+1 || !ownsParent || body.Sequence != author.Sequence+1 {
		return errors.New("GG_FINANCIAL_DAG_CAUSAL_SEQUENCE")
	}
	inputs, decoded, err := prepareFinancialDecodedPayments(body.Payments)
	if err != nil {
		return err
	}
	binding := financialExecutionContext{BlockHash: record.Hash, Checkpoint: execution.checkpoint, Epoch: execution.epoch,
		Genesis: execution.anchor, OrderIndex: execution.blocks + 1, Schema: "gg.financial.execution-context.v1", SourceHash: execution.source.hash()}
	result, err := executeFinancialMoneyWithDecoded(ctx, execution.genesis, execution.anchor, execution.money, binding, inputs, decoded)
	if err != nil {
		return err
	}
	index := execution.activeBlocks + 1
	info := dagHistoryRecord{Hash: record.Hash, Index: index, Rank: int64(body.Rank), WireBytes: len(record.Raw), WireHash: hashHex(record.Raw)}
	leaf := DagOrderLeaf{Hash: record.Hash, Index: index, Producer: body.Producer, Sequence: body.Sequence, Transactions: len(body.Payments)}
	if execution.source.hasProtocol() {
		leaf.Producer = -1
		leaf.ProducerKey = author.Key
	}
	history, err := execution.history.put("b/"+record.Hash, dagHistoryValue{Record: &info})
	if err != nil {
		return err
	}
	lineage := execution.lineage
	if execution.source.hasLineage() {
		// Index remains the actual position within the execution epoch. Global
		// monetary order is authenticated separately in record.Context.OrderIndex.
		lineage, err = lineage.put("b/"+record.Hash, dagHistoryValue{Record: &info})
		if err != nil {
			return err
		}
	}
	history, err = history.put(historyOrderKey(index), dagHistoryValue{Order: &leaf})
	if err != nil {
		return err
	}
	creator := financialDagCreator{Key: author.Key, Producer: body.Producer, Sequence: body.Sequence}
	if execution.source.hasProtocol() {
		creator.Producer = -1
		creator.WorkerKey = record.Protocol.Work.Job.WorkerKey
		creator.WorkHash = record.workShare.identifier
		creator.Rank = body.Rank
		creator.Parents = append([]string(nil), body.Parents...)
		producer.Head = record.Hash
		producer.Rank = body.Rank
		producer.Sequence = body.Sequence
		producer.Attempts += uint64(len(body.Payments))
		producer.Epoch = body.Epoch
		protocol := result.Money.Protocol
		protocol.producers, err = protocol.producers.set(ctx, author.Key, canonical(producer))
		if err != nil {
			return err
		}
		if err = protocol.recordWork(ctx, *record.workShare, execution.genesis); err != nil {
			return err
		}
	}
	summaryID := financialDagSummaryID(binding, creator, result.Summary)
	summaryLeaf := leaf
	summaryLeaf.Hash = summaryID
	summaries, err := execution.summaries.put(historyOrderKey(index), dagHistoryValue{Order: &summaryLeaf})
	if err != nil {
		return err
	}
	if err := execution.receipts.append(summaryID); err != nil {
		return err
	}
	execution.history, execution.lineage, execution.summaries, execution.money = history, lineage, summaries, result.Money
	execution.order.append(leaf)
	execution.blocks++
	execution.activeBlocks++
	execution.activeBytes += uint64(len(record.Raw))
	execution.rawBytes += uint64(len(record.Raw))
	execution.attempts += uint64(len(body.Payments))
	execution.applied += uint64(result.Summary.Applied)
	execution.rejected += uint64(result.Summary.Rejected)
	if !execution.source.hasProtocol() {
		execution.heads[body.Producer] = record.Hash
		execution.authors[body.Producer].Head = record.Hash
		execution.authors[body.Producer].Sequence = body.Sequence
		execution.authors[body.Producer].Attempts += uint64(len(body.Payments))
		if execution.source.Schema != "gg.financial-dag.source.v1" {
			execution.authors[body.Producer].Epoch = strconv.FormatUint(body.Epoch, 10)
		}
	}
	if body.Rank > execution.lastRank {
		execution.lastRank = body.Rank
	}
	record.Block = financialDagBlock{} // full decoded envelopes are transient
	record.Protocol = nil
	record.workShare = nil
	record.Receipts, record.Summary = result.Receipts, result.Summary
	record.Context, record.Creator = binding, creator
	execution.pending[record.Hash] = record
	return nil
}

type financialDagCut struct {
	Before     string `json:"before"`
	Epoch      uint64 `json:"epoch,string"`
	Genesis    string `json:"genesis_hash"`
	Schema     string `json:"schema"`
	SourceHash string `json:"source_hash"`
}

func (execution *financialDagExecution) prepareCut() ([]byte, error) {
	before, err := execution.commitmentHash()
	if err != nil || execution.provisional || execution.activeBlocks == 0 || execution.epoch == dagSegmentCounterMax || execution.checkpoint == dagSegmentCounterMax {
		return nil, errors.New("GG_FINANCIAL_DAG_CUT_CONTEXT")
	}
	return canonical(financialDagCut{Before: before, Epoch: execution.epoch, Genesis: execution.anchor,
		Schema: "gg.financial-dag.cut.v1", SourceHash: execution.source.hash()}), nil
}

// This is a pure candidate transition, not cut authorization or activation.
// A native application may publish it only after real SDK ordering/commit and
// durable retention of the original signed segment and its receipt metadata.
func (execution *financialDagExecution) applyCut(ctx context.Context, raw []byte, consensusTimeNs int64) (*financialDagExecution, error) {
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	expected, err := execution.prepareCut()
	if err != nil || len(raw) > 1024 || string(raw) != string(expected) || consensusTimeNs < execution.timeNs || consensusTimeNs > int64(dagSegmentCounterMax)-5000000000 {
		return nil, errors.New("GG_FINANCIAL_DAG_CUT_CONTEXT")
	}
	cutID := hashHex(append([]byte(financialDomain+"DAG-CUT\x00"), raw...))
	next := execution.clone()
	if err := next.closed.append(cutID); err != nil {
		return nil, err
	}
	next.previous, _ = execution.commitmentHash()
	next.checkpoint++
	next.epoch++
	next.epochAnchor, next.rankBase, next.timeNs = cutID, next.lastRank, consensusTimeNs
	next.history, next.summaries = dagHistory{segmented: true, protocol: next.source.hasProtocol()}, dagHistory{segmented: true, protocol: next.source.hasProtocol()}
	next.activeBlocks, next.activeBytes, next.order = 0, 0, dagOrderAccumulator{}
	if !next.source.hasLineage() {
		for index := range next.heads {
			next.heads[index] = cutID
		}
	}
	if _, err := next.commitment(); err != nil {
		return nil, err
	}
	return next, nil
}
