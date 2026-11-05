package main

// Deterministic application execution for the existing signed LAN DAG format.
// This file performs no I/O, starts no consensus and asserts no certificate.
// A CometBFT application must bind its resulting commitment into AppHash and
// durably retain the validated payload BEFORE returning a proposal acceptance.
import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/hex"
	"errors"
	"math"
	"sort"
	"strconv"
	"strings"
)

const DagAllocation uint64 = 1000000000
const DagZero = "0000000000000000000000000000000000000000000000000000000000000000"
const DagPayloadChunkBytes = 32 * 1024

var errDagCandidateCredit = errors.New("GG_DAG_STORE_CANDIDATE_CREDIT")

// Field ordering follows Python's sorted-key ASCII JSON. All accepted string
// fields below are constrained ASCII protocol names, decimal strings or hex.
type DagGenesis struct {
	AccountCount    int                 `json:"account_count"`
	Allocation      string              `json:"allocation_atomic"`
	ChainID         string              `json:"chain_id"`
	ExecutionPolicy *DagExecutionPolicy `json:"execution_policy,omitempty"`
	PrecheckRoot    string              `json:"precheck_root"`
	Producers       []string            `json:"producers"`
	Schema          string              `json:"schema"`
	TestMode        string              `json:"test_mode"`
}

type DagSource struct {
	Accounts         []string   `json:"accounts"`
	AllowedProducers []int      `json:"allowed_producers"`
	Genesis          DagGenesis `json:"genesis"`
	GenesisHash      string     `json:"genesis_hash"`
	NetworkID        string     `json:"network_id"`
	Schema           string     `json:"schema"`
	SignatureProfile string     `json:"signature_profile"`
	StartedAtNs      string     `json:"started_at_ns"`
}

type DagTxBody struct {
	Amount       string `json:"amount_atomic"`
	ChainID      string `json:"chain_id"`
	From         string `json:"from"`
	Nonce        uint64 `json:"nonce"`
	PrecheckRoot string `json:"precheck_root"`
	Schema       string `json:"schema"`
	To           string `json:"to"`
}

type DagTx struct {
	Body      DagTxBody `json:"body"`
	Signature string    `json:"signature"`
}

type DagBlockBody struct {
	ChainID      string   `json:"chain_id"`
	CreatedAtNs  int64    `json:"created_at_ns"`
	Parents      []string `json:"parents"`
	PayloadRoot  string   `json:"payload_root"`
	PrecheckRoot string   `json:"precheck_root"`
	Producer     int      `json:"producer_index"`
	Rank         int64    `json:"rank"`
	Schema       string   `json:"schema"`
	Sequence     uint64   `json:"sequence"`
	Transactions []DagTx  `json:"transactions"`
}

type DagBlock struct {
	Body      DagBlockBody `json:"body"`
	Signature string       `json:"signature"`
}

type DagBatch struct {
	Blocks      []string `json:"blocks"`
	GenesisHash string   `json:"genesis_hash"`
	Previous    string   `json:"previous"`
	Schema      string   `json:"schema"`
	Sequence    uint64   `json:"sequence"`
}

type DagManifest struct {
	Blocks      []string `json:"blocks"`
	Checkpoint  uint64   `json:"checkpoint"`
	GenesisHash string   `json:"genesis_hash"`
	Previous    string   `json:"previous"`
	Schema      string   `json:"schema"`
	SourceHash  string   `json:"source_hash"`
	TimeNs      string   `json:"time_ns"`
}

type DagOrderLeaf struct {
	Hash         string `json:"hash"`
	Index        int    `json:"index"`
	Producer     int    `json:"producer_index"`
	ProducerKey  string `json:"producer_key,omitempty"`
	Sequence     uint64 `json:"sequence"`
	Transactions int    `json:"transactions"`
}

type DagCommitment struct {
	AccountRoot  string `json:"account_root"`
	Blocks       int    `json:"blocks"`
	ChainID      string `json:"chain_id"`
	Checkpoint   uint64 `json:"checkpoint"`
	GenesisHash  string `json:"genesis_hash"`
	ManifestHash string `json:"manifest_hash"`
	NetworkID    string `json:"network_id"`
	OrderRoot    string `json:"order_root"`
	Previous     string `json:"previous"`
	Schema       string `json:"schema"`
	TimeNs       string `json:"time_ns"`
	Transactions uint64 `json:"transactions"`
}

type dagRecord struct {
	Block     DagBlock
	Raw       []byte
	Hash      string
	WireHash  string
	WireBytes int
	Index     int
	Rank      int64
}

type DagPayloadSelector struct {
	Hash   string `json:"hash"`
	Index  int    `json:"index"`
	Offset int    `json:"offset"`
}

type DagPayloadChunk struct {
	Data        string `json:"data"`
	GenesisHash string `json:"genesis_hash"`
	Hash        string `json:"hash"`
	Height      int64  `json:"height"`
	Index       int    `json:"index"`
	Offset      int    `json:"offset"`
	Schema      string `json:"schema"`
	StateRoot   string `json:"state_root"`
	Total       int    `json:"total"`
	WireHash    string `json:"wire_hash"`
}

// Committed executions/records are immutable after publication. The caller
// captures the matching state and current execution under app.mu, then releases
// it before copying ONE bounded chunk. Historical prefixes remain append-only.
func dagPayloadChunkFor(ctx context.Context, execution *DagExecution, state State, selector DagPayloadSelector) (DagPayloadChunk, error) {
	result := DagPayloadChunk{}
	if ctx.Err() != nil {
		return result, ctx.Err()
	}
	if execution == nil || state.DAG == nil || execution.Anchor != state.GenesisHash || !pubPattern.MatchString(selector.Hash) ||
		selector.Index < 1 || selector.Index > state.DAG.Blocks || selector.Index > execution.orderCount() ||
		selector.Offset < 0 || selector.Offset >= DagMaxWire || selector.Offset%DagPayloadChunkBytes != 0 {
		return result, errors.New("GG_DAG_PAYLOAD_SELECTOR")
	}
	record, ok, err := execution.historyRecord(selector.Hash)
	if err != nil {
		return result, err
	}
	if !ok || record.Index != selector.Index || record.Hash != selector.Hash ||
		!pubPattern.MatchString(record.WireHash) || record.WireBytes < 1 || record.WireBytes > DagMaxWire || selector.Offset >= record.WireBytes {
		return result, errors.New("GG_DAG_PAYLOAD_NOT_COMMITTED")
	}
	raw := record.Raw
	if raw == nil && execution.payloadReader != nil {
		var err error
		raw, err = execution.payloadReader(ctx, record.WireHash, record.WireBytes)
		if err != nil {
			return result, err
		}
	}
	if len(raw) != record.WireBytes || selector.Offset == 0 && hashHex(raw) != record.WireHash {
		return result, errors.New("GG_DAG_PAYLOAD_CHANGED")
	}
	end := selector.Offset + DagPayloadChunkBytes
	if end > len(raw) {
		end = len(raw)
	}
	result = DagPayloadChunk{Data: base64.StdEncoding.EncodeToString(raw[selector.Offset:end]), GenesisHash: state.GenesisHash,
		Hash: selector.Hash, Height: state.Height, Index: selector.Index, Offset: selector.Offset, Schema: "gg.dag.payload-chunk.v1",
		StateRoot: state.StateRoot, Total: len(raw), WireHash: record.WireHash}
	if ctx.Err() != nil {
		return DagPayloadChunk{}, ctx.Err()
	}
	return result, nil
}

type DagExecution struct {
	Source        DagSource
	Anchor        string
	Accounts      []Account
	proofOrder    []DagOrderLeaf // explicit materialized read-only proof view only
	Manifest      DagManifest
	Commitment    DagCommitment
	history       dagHistory
	pending       map[string]dagRecord
	heads         []string
	sequences     []uint64
	nonces        []uint64
	bytes         int
	orderRoot     dagOrderAccumulator
	payloadReader func(context.Context, string, int) ([]byte, error)
	// Only the explicitly constructed segmented-history kernel sets these.
	// Current live v1 sources never decode or enable this context.
	segmentMode         bool
	segmentParent       string
	segmentRankBase     int64
	segmentSequenceBase []uint64
	segmentPrecheck     string
}

// The storage implementation is native-only. Public WASM verification shares
// these execution/commitment rules without acquiring a filesystem or writer.
type dagPersistence interface {
	health() error
	prepare(*DagExecution) error
	prepareProposal(*DagExecution) error
	prepareFinalized(*DagExecution) error
	load(DagCommitment) (*DagExecution, error)
	history() ([]byte, error)
	commit([]byte) error
	commitExecution([]byte, *DagExecution) error
	archiveExecution(*DagExecution) *DagExecution
	publicExecution(context.Context, DagCommitment) (*DagExecution, error)
	publicProof(context.Context, State, string, string, int) (any, error)
	close() error
}

func dagDigest(domain string, value any) string {
	return hashHex(append([]byte(domain), canonical(value)...))
}

func dagTree[T any](values []T, domain string) [][]string {
	level := make([]string, len(values))
	for i, value := range values {
		level[i] = dagDigest(domain+"L\x00", value)
	}
	if len(level) == 0 {
		level = []string{hashHex([]byte(domain + "EMPTY\x00"))}
	}
	levels := [][]string{level}
	for len(level) > 1 {
		next := make([]string, (len(level)+1)/2)
		for i := 0; i < len(level); i += 2 {
			j := i + 1
			if j == len(level) {
				j = i
			}
			a, _ := hex.DecodeString(level[i])
			b, _ := hex.DecodeString(level[j])
			next[i/2] = hashHex(append(append([]byte(domain+"N\x00"), a...), b...))
		}
		level = next
		levels = append(levels, level)
	}
	return levels
}

func dagRoot[T any](values []T, domain string) string {
	levels := dagTree(values, domain)
	return levels[len(levels)-1][0]
}

func dagDecimalNs(value string) (int64, bool) {
	n, err := strconv.ParseInt(value, 10, 64)
	return n, err == nil && n >= 1000000000 && strconv.FormatInt(n, 10) == value
}

func validateDagSource(source DagSource) error {
	g := source.Genesis
	if source.Schema != "gg.dag.consensus.source.v1" || source.SignatureProfile != TransactionSignatureProfile ||
		!validDagGenesisPolicy(g) || g.TestMode != "PRODUCER_OWNED_NONFINANCIAL" ||
		len(g.ChainID) != 30 || g.ChainID[:6] != "ggdag:" || strings.ToLower(g.ChainID) != g.ChainID || !pubPattern.MatchString(source.NetworkID) ||
		g.Allocation != "1000000000" || g.AccountCount != 6 || len(g.Producers) != 6 || len(source.Accounts) != 6 ||
		source.GenesisHash != dagDigest("GG-DAG-DATA-v1\x00", g) {
		return errors.New("GG_DAG_SOURCE_CONTEXT")
	}
	if _, ok := dagDecimalNs(source.StartedAtNs); !ok {
		return errors.New("GG_DAG_SOURCE_TIME")
	}
	if _, err := hex.DecodeString(g.ChainID[6:]); err != nil {
		return errors.New("GG_DAG_SOURCE_CONTEXT")
	}
	seen := map[string]bool{}
	for _, public := range g.Producers {
		raw, err := hex.DecodeString(public)
		if !pubPattern.MatchString(public) || err != nil || !validAuthorKey(raw) || seen[public] {
			return errors.New("GG_DAG_SOURCE_PRODUCERS")
		}
		seen[public] = true
	}
	expected := append([]string(nil), g.Producers...)
	sort.Strings(expected)
	for i, address := range source.Accounts {
		if address != expected[i] {
			return errors.New("GG_DAG_SOURCE_ACCOUNTS")
		}
	}
	allowed := -1
	for _, index := range source.AllowedProducers {
		if index <= allowed || index < 0 || index >= 6 {
			return errors.New("GG_DAG_SOURCE_ROLES")
		}
		allowed = index
	}
	if source.AllowedProducers == nil {
		return errors.New("GG_DAG_SOURCE_ROLES")
	}
	if g.PrecheckRoot != dagRoot(dagInitialAccounts(source), "GG-DAG-ACCOUNT-v1\x00") {
		return errors.New("GG_DAG_SOURCE_ROOT")
	}
	return nil
}

func dagInitialAccounts(source DagSource) []Account {
	accounts := make([]Account, len(source.Accounts))
	for i, address := range source.Accounts {
		accounts[i] = Account{Address: address, Balance: "1000000000"}
	}
	return accounts
}

func newDagExecution(source DagSource, anchor string) (*DagExecution, error) {
	if validateDagSource(source) != nil || !pubPattern.MatchString(anchor) {
		return nil, errors.New("GG_DAG_EXECUTION_CONTEXT")
	}
	// Copy caller-owned slices: a later caller mutation cannot change policy.
	var owned DagSource
	if decodeStrict(canonical(source), &owned) != nil {
		return nil, errors.New("GG_DAG_EXECUTION_CONTEXT")
	}
	execution := &DagExecution{Source: owned, Anchor: anchor, Accounts: dagInitialAccounts(owned),
		pending: map[string]dagRecord{}, heads: make([]string, 6), sequences: make([]uint64, 6), nonces: make([]uint64, 6)}
	execution.Manifest = DagManifest{Blocks: []string{}, Checkpoint: 0, GenesisHash: anchor, Previous: DagZero,
		Schema: "gg.dag.execution.manifest.v1", SourceHash: dagDigest("GG-DAG-CONSENSUS-SOURCE-v1\x00", owned), TimeNs: "0"}
	execution.seal()
	return execution, nil
}

func validateDagCommitment(value DagCommitment, source DagSource, anchor string) error {
	if value.Schema != "gg.dag.commitment.v1" || value.ChainID != source.Genesis.ChainID || value.GenesisHash != source.GenesisHash ||
		value.NetworkID != source.NetworkID || value.Blocks < 0 || value.Blocks > DagMaxRecords || value.Checkpoint > uint64(value.Blocks) ||
		value.Transactions > uint64(value.Blocks)*DagMaxBlockTransactions {
		return errors.New("GG_DAG_COMMITMENT_CONTEXT")
	}
	for _, root := range []string{value.AccountRoot, value.ManifestHash, value.OrderRoot, value.Previous} {
		if !pubPattern.MatchString(root) {
			return errors.New("GG_DAG_COMMITMENT_ROOT")
		}
	}
	if value.Checkpoint == 0 {
		initial, err := newDagExecution(source, anchor)
		if err != nil || !bytes.Equal(canonical(initial.Commitment), canonical(value)) {
			return errors.New("GG_DAG_COMMITMENT_GENESIS")
		}
	} else {
		if _, ok := dagDecimalNs(value.TimeNs); !ok || value.Previous == value.ManifestHash {
			return errors.New("GG_DAG_COMMITMENT_TIME")
		}
	}
	return nil
}

func (execution *DagExecution) seal() {
	transactions := uint64(0)
	for _, account := range execution.Accounts {
		transactions += account.Nonce
	}
	execution.Commitment = DagCommitment{AccountRoot: dagRoot(execution.Accounts, "GG-DAG-ACCOUNT-v1\x00"), Blocks: execution.orderCount(),
		ChainID: execution.Source.Genesis.ChainID, Checkpoint: execution.Manifest.Checkpoint, GenesisHash: execution.Source.GenesisHash,
		ManifestHash: dagDigest("GG-DAG-CHECKPOINT-MANIFEST-v1\x00", execution.Manifest), NetworkID: execution.Source.NetworkID,
		OrderRoot: execution.orderRoot.root(), Previous: execution.Manifest.Previous,
		Schema: "gg.dag.commitment.v1", TimeNs: execution.Manifest.TimeNs, Transactions: transactions}
}

func (execution *DagExecution) clone() *DagExecution {
	clone := *execution
	clone.Accounts = append([]Account(nil), execution.Accounts...)
	if execution.proofOrder != nil {
		clone.proofOrder = append([]DagOrderLeaf{}, execution.proofOrder...)
	}
	clone.Manifest.Blocks = append([]string{}, execution.Manifest.Blocks...)
	clone.pending = make(map[string]dagRecord, len(execution.pending))
	for key, value := range execution.pending {
		clone.pending[key] = value
	}
	clone.heads = append([]string(nil), execution.heads...)
	clone.sequences = append([]uint64(nil), execution.sequences...)
	clone.nonces = append([]uint64(nil), execution.nonces...)
	clone.segmentSequenceBase = append([]uint64(nil), execution.segmentSequenceBase...)
	return &clone
}

func decodeDagBlock(raw []byte, source DagSource, upperTime int64) (dagRecord, error) {
	return decodeDagBlockContext(raw, source, upperTime, source.Genesis.PrecheckRoot, DagMaxSequence, DagMaxRank)
}

func decodeDagBlockContext(raw []byte, source DagSource, upperTime int64, precheck string, sequenceLimit uint64, rankLimit int64) (dagRecord, error) {
	var block DagBlock
	if len(raw) == 0 || len(raw) > DagMaxWire || decodeStrictLimited(raw, &block, DagMaxBlockTransactions, 64) != nil || !streamCanonicalEqual(raw, block) {
		return dagRecord{}, errors.New("GG_DAG_BLOCK_ENCODING")
	}
	body := block.Body
	started, _ := dagDecimalNs(source.StartedAtNs)
	if body.Schema != "gg.parallel-dag.block.v1" || body.ChainID != source.Genesis.ChainID || body.PrecheckRoot != precheck ||
		body.Producer < 0 || body.Producer >= 6 || body.Sequence < 1 || body.Sequence > sequenceLimit || body.Rank < 1 || body.Rank > rankLimit ||
		body.CreatedAtNs < started-1000000000 || upperTime > 0 && body.CreatedAtNs > upperTime ||
		len(body.Parents) < 1 || len(body.Parents) > DagMaxParents || body.Transactions == nil || len(body.Transactions) > DagMaxBlockTransactions {
		return dagRecord{}, errors.New("GG_DAG_BLOCK_CONTEXT")
	}
	allowed := false
	for _, index := range source.AllowedProducers {
		if index == body.Producer {
			allowed = true
		}
	}
	if !allowed {
		return dagRecord{}, errors.New("GG_DAG_PRODUCER_ROLE_FORBIDDEN")
	}
	seen := map[string]bool{}
	for _, parent := range body.Parents {
		if !pubPattern.MatchString(parent) || seen[parent] {
			return dagRecord{}, errors.New("GG_DAG_PARENTS")
		}
		seen[parent] = true
	}
	if body.PayloadRoot != dagRoot(body.Transactions, "GG-DAG-PAYLOAD-v1\x00") {
		return dagRecord{}, errors.New("GG_DAG_PAYLOAD_ROOT")
	}
	public, _ := hex.DecodeString(source.Genesis.Producers[body.Producer])
	signature, err := hex.DecodeString(block.Signature)
	if err != nil || len(block.Signature) != 128 || hex.EncodeToString(signature) != block.Signature || !verifyTransactionSignature(public, streamCanonicalDomainBytes("GG-DAG-PROPOSAL-SIGN-v1\x00", body), signature) {
		return dagRecord{}, errors.New("GG_DAG_BLOCK_SIGNATURE")
	}
	return dagRecord{Block: block, Raw: raw, Hash: streamCanonicalDigest("GG-DAG-BLOCK-v1\x00", body), WireHash: hashHex(raw), WireBytes: len(raw)}, nil
}

func (execution *DagExecution) admit(record dagRecord) error {
	body := record.Block.Body
	producer := body.Producer
	precheck := execution.Source.Genesis.PrecheckRoot
	if execution.segmentMode {
		precheck = execution.segmentPrecheck
		if body.PrecheckRoot != precheck || body.Rank < execution.segmentRankBase || body.Rank-execution.segmentRankBase > DagMaxRank ||
			body.Sequence < execution.segmentSequenceBase[producer] || body.Sequence-execution.segmentSequenceBase[producer] > DagMaxSequence {
			return errors.New("GG_DAG_SEGMENT_BLOCK_CONTEXT")
		}
	}
	_, exists, err := execution.historyRecord(record.Hash)
	if err != nil {
		return err
	}
	if exists {
		return errors.New("GG_DAG_ALREADY_COMMITTED")
	}
	if execution.orderCount() >= DagMaxRecords || execution.bytes > DagMaxHistoryWire-len(record.Raw) {
		return errors.New("GG_DAG_EXECUTION_LIMIT")
	}
	maximum := int64(0)
	ownsParent := execution.heads[producer] == ""
	for _, parent := range body.Parents {
		rank, exists, err := execution.historyRank(parent)
		if err != nil {
			return err
		}
		if !exists {
			return errors.New("GG_DAG_UNKNOWN_PARENT")
		}
		if rank > maximum {
			maximum = rank
		}
		if parent == execution.heads[producer] {
			ownsParent = true
		}
	}
	if body.Rank != maximum+1 {
		return errors.New("GG_DAG_RANK")
	}
	if body.Sequence != execution.sequences[producer]+1 || !ownsParent {
		return errors.New("GG_DAG_CAUSAL_SEQUENCE")
	}
	sender := execution.Source.Genesis.Producers[producer]
	index := sort.SearchStrings(execution.Source.Accounts, sender)
	// Reject cheap rule violations before starting cryptographic work. Nonces
	// describe the same ordered sequence as the former per-TX state fold.
	for offset, transaction := range body.Transactions {
		tx := transaction.Body
		target := sort.SearchStrings(execution.Source.Accounts, tx.To)
		if tx.Schema != "gg.parallel-dag.tx.v2" || tx.ChainID != execution.Source.Genesis.ChainID || tx.PrecheckRoot != precheck ||
			tx.From != sender || target >= len(execution.Accounts) || execution.Accounts[target].Address != tx.To || tx.To == sender ||
			tx.Amount != "1" || execution.nonces[producer] >= DagAllocation ||
			tx.Nonce != execution.nonces[producer]+uint64(offset) || tx.Nonce >= DagAllocation {
			return errors.New("GG_DAG_TX_RULES")
		}
	}
	public, _ := hex.DecodeString(sender)
	if !verifyDagTransactionSignatures(public, body.Transactions) {
		return errors.New("GG_DAG_TX_SIGNATURE")
	}
	// Workers have joined successfully. State is still changed sequentially;
	// scheduling never chooses the account root, nonce order or publication.
	for _, transaction := range body.Transactions {
		target := sort.SearchStrings(execution.Source.Accounts, transaction.Body.To)
		balance, _ := strconv.ParseUint(execution.Accounts[index].Balance, 10, 64)
		recipient, _ := strconv.ParseUint(execution.Accounts[target].Balance, 10, 64)
		if balance == 0 || recipient >= 6*DagAllocation {
			return errors.New("GG_DAG_TX_BALANCE")
		}
		execution.Accounts[index].Balance = strconv.FormatUint(balance-1, 10)
		execution.Accounts[index].Nonce++
		execution.Accounts[target].Balance = strconv.FormatUint(recipient+1, 10)
		execution.nonces[producer]++
	}
	// Full decoded TX objects are transient validation work, not history state.
	stored := record
	stored.Block = DagBlock{}
	stored.Index = execution.orderCount() + 1
	stored.Rank = body.Rank
	info := dagHistoryRecord{Hash: stored.Hash, Index: stored.Index, Rank: stored.Rank, WireBytes: stored.WireBytes, WireHash: stored.WireHash}
	leaf := DagOrderLeaf{Hash: record.Hash, Index: stored.Index, Producer: producer, Sequence: body.Sequence, Transactions: len(body.Transactions)}
	history, err := execution.history.put("b/"+record.Hash, dagHistoryValue{Record: &info})
	if err != nil {
		return err
	}
	history, err = history.put(historyOrderKey(leaf.Index), dagHistoryValue{Order: &leaf})
	if err != nil {
		return err
	}
	execution.history = history
	execution.pending[record.Hash] = stored
	execution.bytes += len(record.Raw)
	execution.heads[producer] = record.Hash
	execution.sequences[producer] = body.Sequence
	execution.orderRoot.append(leaf)
	execution.Manifest.Blocks = append(execution.Manifest.Blocks, record.WireHash)
	return nil
}

// blockTimeNs is the authenticated proposal time, identical at every validator.
// Zero performs mempool admissibility only. Its result must never be persisted
// or certified; actual proposal processing supplies a positive consensus time.
func applyDagBatch(base *DagExecution, raw []byte, blockTimeNs int64) (*DagExecution, error) {
	var batch DagBatch
	if len(raw) == 0 || len(raw) > DagMaxBatchWire || decodeStrictLimited(raw, &batch, DagMaxBatchBlocks, 64) != nil || !streamCanonicalEqual(raw, batch) ||
		batch.Schema != "gg.dag.checkpoint.batch.v1" || batch.GenesisHash != base.Anchor || batch.Previous != base.Commitment.ManifestHash ||
		batch.Sequence != base.Manifest.Checkpoint+1 || len(batch.Blocks) < 1 || len(batch.Blocks) > DagMaxBatchBlocks {
		return nil, errors.New("GG_DAG_BATCH_CONTEXT")
	}
	upper := int64(0)
	if blockTimeNs != 0 {
		previous, _ := dagDecimalNs(base.Manifest.TimeNs)
		if blockTimeNs < previous || blockTimeNs > math.MaxInt64-5000000000 {
			return nil, errors.New("GG_DAG_CHECKPOINT_TIME")
		}
		upper = blockTimeNs + 5000000000
	}
	next := base.clone()
	next.Manifest.Blocks = []string{}
	size := 0
	previousRank := int64(0)
	previousHash := ""
	for _, encoded := range batch.Blocks {
		wire, err := base64.StdEncoding.Strict().DecodeString(encoded)
		if err != nil || base64.StdEncoding.EncodeToString(wire) != encoded {
			return nil, errors.New("GG_DAG_BATCH_ENCODING")
		}
		size += len(wire)
		if size > DagMaxWire {
			return nil, errors.New("GG_DAG_BATCH_SIZE")
		}
		var record dagRecord
		if base.segmentMode {
			record, err = decodeDagBlockContext(wire, base.Source, upper, base.segmentPrecheck, dagSegmentCounterMax, math.MaxInt64)
		} else {
			record, err = decodeDagBlock(wire, base.Source, upper)
		}
		if err != nil {
			return nil, err
		}
		if record.Block.Body.Rank < previousRank || record.Block.Body.Rank == previousRank && record.Hash <= previousHash {
			return nil, errors.New("GG_DAG_BATCH_ORDER")
		}
		if err = next.admit(record); err != nil {
			return nil, err
		}
		previousRank = record.Block.Body.Rank
		previousHash = record.Hash
	}
	next.Manifest.Checkpoint = batch.Sequence
	next.Manifest.Previous = base.Commitment.ManifestHash
	if blockTimeNs == 0 {
		next.Manifest.TimeNs = "0"
	} else {
		next.Manifest.TimeNs = strconv.FormatInt(blockTimeNs, 10)
	}
	next.seal()
	return next, nil
}
