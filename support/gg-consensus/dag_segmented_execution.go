package main

// Genesis-bound continuing history kernel. Explicit SDK genesis v4 carries this
// separate source in dag_segmented. Legacy dag/source decoders still reject it;
// no existing source is upgraded. Only the native archive + SDK commit path may
// activate a prepared cut; a preparation plan alone has no finality authority.
import (
	"encoding/hex"
	"errors"
	"math"
	"sort"
	"strconv"
)

const dagSegmentCounterMax uint64 = math.MaxInt64
const dagClosedSegmentDomain = "GG-DAG-CLOSED-SEGMENTS-v1\x00"

var errDagSegment = errors.New("GG_DAG_SEGMENT_CONTEXT")

type dagHistoryPolicy struct {
	ArchiveMode  string `json:"archive_mode"`
	Boundary     string `json:"boundary"`
	CounterLimit string `json:"counter_limit"`
	CounterScope string `json:"counter_scope"`
	Profile      string `json:"profile"`
	Schema       string `json:"schema"`
	Verification string `json:"verification"`
}

func segmentedHistoryPolicy() dagHistoryPolicy {
	return dagHistoryPolicy{ArchiveMode: "ORIGINAL_SIGNED_SEGMENTS_REQUIRED", Boundary: "SDK_CERTIFIED_CUT",
		CounterLimit: "9223372036854775807", CounterScope: "GLOBAL_WITH_ACTIVE_SEGMENT_OFFSETS",
		Profile: "GG-DAG-SEGMENTED-v1", Schema: "gg.dag.history-policy.v1", Verification: "FULL_SIGNED_ARCHIVE_CHAIN_REPLAY"}
}

type dagSegmentedGenesis struct {
	AccountCount    int                 `json:"account_count"`
	Allocation      string              `json:"allocation_atomic"`
	ChainID         string              `json:"chain_id"`
	ExecutionPolicy *DagExecutionPolicy `json:"execution_policy"` // per-active-segment bounds
	HistoryPolicy   dagHistoryPolicy    `json:"history_policy"`
	PrecheckRoot    string              `json:"precheck_root"`
	Producers       []string            `json:"producers"`
	Schema          string              `json:"schema"`
	TestMode        string              `json:"test_mode"`
}

type dagSegmentedSource struct {
	Accounts         []string            `json:"accounts"`
	AllowedProducers []int               `json:"allowed_producers"`
	Genesis          dagSegmentedGenesis `json:"genesis"`
	GenesisHash      string              `json:"genesis_hash"`
	NetworkID        string              `json:"network_id"`
	Schema           string              `json:"schema"`
	SignatureProfile string              `json:"signature_profile"`
	StartedAtNs      string              `json:"started_at_ns"`
}

// NetworkID is a pre-genesis network namespace. New LAN negotiation must derive
// it from its signed roster/committee context BEFORE constructing this source;
// using the later whole-session digest would create a circular dependency.
// Blocks and TX bind the resulting chain ID, including in the initial epoch.
func (source dagSegmentedSource) chainID() string {
	source.Genesis.ChainID = ""
	source.GenesisHash = ""
	return "ggdag:" + dagDigest("GG-DAG-SEGMENTED-CHAIN-ID-v1\x00", source)
}

func (source dagSegmentedSource) validationView() DagSource {
	g := source.Genesis
	// Legacy's shorter chain string is a private shape-validation alias. It is
	// never exported or used to authenticate a segmented block/transaction.
	if len(g.ChainID) > 30 {
		g.ChainID = g.ChainID[:30]
	}
	view := DagSource{Accounts: source.Accounts, AllowedProducers: source.AllowedProducers,
		NetworkID: source.NetworkID, Schema: "gg.dag.consensus.source.v1", SignatureProfile: source.SignatureProfile, StartedAtNs: source.StartedAtNs}
	view.Genesis = DagGenesis{AccountCount: g.AccountCount, Allocation: g.Allocation, ChainID: g.ChainID,
		ExecutionPolicy: g.ExecutionPolicy, PrecheckRoot: g.PrecheckRoot, Producers: g.Producers,
		Schema: "gg.parallel-dag.genesis.v3", TestMode: g.TestMode}
	view.GenesisHash = dagDigest("GG-DAG-DATA-v1\x00", view.Genesis)
	return view
}

func validateSegmentedSource(source dagSegmentedSource) error {
	if source.Schema != "gg.dag.consensus.source.v2" || source.Genesis.Schema != "gg.parallel-dag.genesis.v4" ||
		source.Genesis.HistoryPolicy != segmentedHistoryPolicy() || source.Genesis.ExecutionPolicy == nil ||
		*source.Genesis.ExecutionPolicy != currentDagExecutionPolicy() || source.Genesis.ChainID != source.chainID() ||
		source.GenesisHash != dagDigest("GG-DAG-DATA-v1\x00", source.Genesis) || validateDagSource(source.validationView()) != nil {
		return errDagSegment
	}
	return nil
}

type dagClosedSegments struct {
	count uint64
	peaks [64]string
}

func closedSegmentJoin(left, right string) string {
	a, _ := hex.DecodeString(left)
	b, _ := hex.DecodeString(right)
	return hashHex(append(append([]byte(dagClosedSegmentDomain+"N\x00"), a...), b...))
}

func (tree dagClosedSegments) valid() bool {
	if tree.count > dagSegmentCounterMax {
		return false
	}
	for level, peak := range tree.peaks {
		present := tree.count&(uint64(1)<<level) != 0
		if present && !pubPattern.MatchString(peak) || !present && peak != "" {
			return false
		}
	}
	return true
}

func (tree *dagClosedSegments) append(cut string) error {
	if !tree.valid() || !pubPattern.MatchString(cut) || tree.count == dagSegmentCounterMax {
		return errDagSegment
	}
	value := dagDigest(dagClosedSegmentDomain+"L\x00", cut)
	count := tree.count
	for level := range tree.peaks {
		if count&1 == 0 {
			tree.peaks[level] = value
			tree.count++
			return nil
		}
		value = closedSegmentJoin(tree.peaks[level], value)
		tree.peaks[level] = ""
		count >>= 1
	}
	return errDagSegment
}

func (tree dagClosedSegments) root() (string, error) {
	if !tree.valid() {
		return "", errDagSegment
	}
	if tree.count == 0 {
		return hashHex([]byte(dagClosedSegmentDomain + "EMPTY\x00")), nil
	}
	value, height := "", 0
	for level, peak := range tree.peaks {
		if peak == "" {
			continue
		}
		if value == "" {
			value, height = peak, level
			continue
		}
		for height < level {
			value = closedSegmentJoin(value, value)
			height++
		}
		value = closedSegmentJoin(peak, value)
		height = level + 1
	}
	return value, nil
}

type dagSegmentAuthor struct {
	Head     string `json:"head"`
	Key      string `json:"key"`
	Nonce    string `json:"nonce"`
	Sequence string `json:"sequence"`
}

type dagSegmentAuthors [6]dagSegmentAuthor

func (authors *dagSegmentAuthors) UnmarshalJSON(raw []byte) error {
	var values []dagSegmentAuthor
	if len(raw) > 8192 || decodeStrictLimited(raw, &values, 6, 4) != nil || len(values) != 6 {
		return errDagSegment
	}
	copy(authors[:], values)
	return nil
}

type dagSegmentedState struct {
	Active       DagCommitment     `json:"active"`
	Anchor       string            `json:"anchor"`
	Authors      dagSegmentAuthors `json:"authors"`
	Blocks       uint64            `json:"blocks,string"`
	ClosedRoot   string            `json:"closed_root"`
	Epoch        uint64            `json:"epoch,string"`
	LastCut      string            `json:"last_cut"`
	LastRank     int64             `json:"last_rank,string"`
	RawBytes     uint64            `json:"raw_bytes,string"`
	Schema       string            `json:"schema"`
	SourceHash   string            `json:"source_hash"`
	Transactions uint64            `json:"transactions,string"`
}

type dagSegmentedExecution struct {
	source           dagSegmentedSource
	anchor           string
	active           *DagExecution
	closed           dagClosedSegments
	closedBlocks     uint64
	closedBytes      uint64
	lastCut          string
	lastRank         int64
	authorHeads      [6]string
	baseAuthorHeads  [6]string
	baseCut          *dagHistoryCutBody // immutable cut preimage, no old graph or raw payload
	baseBeforeClosed [64]string
	startManifest    string
	manifests        []DagManifest          // bounded by active blocks, needed for exact archive replay
	startBase        *dagSegmentedExecution // empty verified epoch base; never retains older raw history
}

func newDagSegmentedExecution(source dagSegmentedSource, anchor string) (*dagSegmentedExecution, error) {
	if validateSegmentedSource(source) != nil || !pubPattern.MatchString(anchor) {
		return nil, errDagSegment
	}
	var owned dagSegmentedSource
	if decodeStrict(canonical(source), &owned) != nil {
		return nil, errDagSegment
	}
	active, err := newDagExecution(owned.validationView(), anchor)
	if err != nil {
		return nil, err
	}
	// This view is internal block-validation context, not an SDK/public source.
	active.Source.Schema = owned.Schema
	active.Source.Genesis.Schema = owned.Genesis.Schema
	active.Source.Genesis.ChainID = owned.Genesis.ChainID
	active.Source.GenesisHash = owned.GenesisHash
	active.segmentMode, active.history.segmented = true, true
	active.segmentParent, active.segmentPrecheck = owned.GenesisHash, owned.Genesis.PrecheckRoot
	active.segmentSequenceBase = make([]uint64, 6)
	active.Manifest.SourceHash = dagDigest("GG-DAG-CONSENSUS-SOURCE-v2\x00", owned)
	active.seal()
	result := &dagSegmentedExecution{source: owned, anchor: anchor, active: active, lastCut: owned.GenesisHash}
	for i := range result.authorHeads {
		result.authorHeads[i] = owned.GenesisHash
	}
	result.baseAuthorHeads = result.authorHeads
	result.startManifest = active.Commitment.ManifestHash
	result.captureSegmentBase()
	return result, nil
}

func (execution *dagSegmentedExecution) captureSegmentBase() {
	base := *execution
	base.active = execution.active.clone()
	base.active.payloadReader = nil
	base.startBase = nil
	execution.startBase = &base
}

func (execution *dagSegmentedExecution) state() (dagSegmentedState, error) {
	result := dagSegmentedState{}
	if execution == nil || execution.active == nil || execution.closed.count == dagSegmentCounterMax ||
		execution.active.orderCount() < 0 || execution.active.orderCount() > DagMaxRecords || execution.active.bytes < 0 || execution.active.bytes > DagMaxHistoryWire ||
		execution.closedBlocks > dagSegmentCounterMax-uint64(execution.active.orderCount()) ||
		execution.closedBytes > math.MaxUint64-uint64(execution.active.bytes) {
		return result, errDagSegment
	}
	if len(execution.active.Accounts) != 6 || len(execution.active.nonces) != 6 || len(execution.active.sequences) != 6 {
		return result, errDagSegment
	}
	for i, key := range execution.source.Genesis.Producers {
		index := sort.SearchStrings(execution.source.Accounts, key)
		if index >= len(execution.active.Accounts) || execution.active.Accounts[index].Address != key ||
			execution.active.Accounts[index].Nonce != execution.active.nonces[i] {
			return result, errDagSegment
		}
	}
	root, err := execution.closed.root()
	if err != nil {
		return result, err
	}
	result = dagSegmentedState{Active: execution.active.Commitment, Anchor: execution.anchor,
		Blocks: execution.closedBlocks + uint64(execution.active.orderCount()), ClosedRoot: root, Epoch: execution.closed.count + 1,
		LastCut: execution.lastCut, LastRank: execution.lastRank, RawBytes: execution.closedBytes + uint64(execution.active.bytes),
		Schema: "gg.dag.segmented-commitment.v1", SourceHash: dagDigest("GG-DAG-CONSENSUS-SOURCE-v2\x00", execution.source),
		Transactions: execution.active.Commitment.Transactions}
	for i := range result.Authors {
		result.Authors[i] = dagSegmentAuthor{Head: execution.authorHeads[i], Key: execution.source.Genesis.Producers[i],
			Nonce: strconv.FormatUint(execution.active.nonces[i], 10), Sequence: strconv.FormatUint(execution.active.sequences[i], 10)}
	}
	return result, nil
}

func (execution *dagSegmentedExecution) apply(raw []byte, proposalTime int64) (*dagSegmentedExecution, error) {
	if _, err := execution.state(); err != nil {
		return nil, err
	}
	active, err := applyDagBatch(execution.active, raw, proposalTime)
	if err != nil {
		return nil, err
	}
	next := *execution
	next.active = active
	next.manifests = append(append([]DagManifest(nil), execution.manifests...), active.Manifest)
	err = active.visitOrderPrefix(active.orderCount(), func(leaf DagOrderLeaf) error {
		if leaf.Index <= execution.active.orderCount() {
			return nil
		}
		record, found, err := active.historyRecord(leaf.Hash)
		if err != nil || !found {
			return errDagHistoryUnavailable
		}
		next.authorHeads[leaf.Producer] = leaf.Hash
		if record.Rank > next.lastRank {
			next.lastRank = record.Rank
		}
		return nil
	})
	if err != nil {
		return nil, err
	}
	if _, err = next.state(); err != nil {
		return nil, err
	}
	return &next, nil
}

type dagHistoryCutBody struct {
	Accounts    [6]Account        `json:"accounts"`
	Before      dagSegmentedState `json:"before"`
	HistoryRoot string            `json:"history_root"`
	Schema      string            `json:"schema"`
}

// A plan is NOT an activated checkpoint, a durable archive receipt or finality.
// Its successor is private until the archive + SDK commit integration exists.
type dagHistoryCutPlan struct {
	body       dagHistoryCutBody
	hash       string
	beforeHash string
	next       *dagSegmentedExecution
}

func (execution *dagSegmentedExecution) checkActiveHistory() error {
	if len(execution.active.segmentSequenceBase) != 6 {
		return errDagSegment
	}
	count, size := 0, 0
	rank := execution.active.segmentRankBase
	heads := execution.baseAuthorHeads
	sequences := append([]uint64(nil), execution.active.segmentSequenceBase...)
	order := dagOrderAccumulator{}
	wires := make([]string, 0, execution.active.orderCount())
	err := execution.active.visitOrderPrefix(execution.active.orderCount(), func(leaf DagOrderLeaf) error {
		if leaf.Producer < 0 || leaf.Producer >= 6 || leaf.Sequence != sequences[leaf.Producer]+1 {
			return errDagSegment
		}
		record, found, err := execution.active.historyRecord(leaf.Hash)
		if err != nil || !found || record.Index != leaf.Index || record.WireBytes < 1 || record.WireBytes > DagMaxWire {
			return errDagHistoryUnavailable
		}
		if size > DagMaxHistoryWire-record.WireBytes {
			return errDagSegment
		}
		count++
		size += record.WireBytes
		heads[leaf.Producer], sequences[leaf.Producer] = leaf.Hash, leaf.Sequence
		if record.Rank > rank {
			rank = record.Rank
		}
		order.append(leaf)
		wires = append(wires, record.WireHash)
		return nil
	})
	if err != nil || count != execution.active.orderCount() || size != execution.active.bytes ||
		rank != execution.lastRank || heads != execution.authorHeads || order.root() != execution.active.Commitment.OrderRoot {
		return errDagSegment
	}
	for i := range sequences {
		if sequences[i] != execution.active.sequences[i] {
			return errDagSegment
		}
	}
	previous, offset := execution.startManifest, 0
	for index, manifest := range execution.manifests {
		if manifest.Checkpoint != uint64(index+1) || manifest.Previous != previous || manifest.GenesisHash != execution.anchor ||
			manifest.SourceHash != execution.active.Manifest.SourceHash || manifest.Schema != "gg.dag.execution.manifest.v1" ||
			len(manifest.Blocks) < 1 || len(manifest.Blocks) > DagMaxBatchBlocks {
			return errDagSegment
		}
		for _, hash := range manifest.Blocks {
			if offset >= len(wires) || wires[offset] != hash {
				return errDagSegment
			}
			offset++
		}
		previous = dagDigest("GG-DAG-CHECKPOINT-MANIFEST-v1\x00", manifest)
	}
	if offset != len(wires) || previous != execution.active.Commitment.ManifestHash {
		return errDagSegment
	}
	return nil
}

func (execution *dagSegmentedExecution) prepareCut() (dagHistoryCutPlan, error) {
	plan := dagHistoryCutPlan{}
	before, err := execution.state()
	if err != nil || execution.active.orderCount() == 0 || execution.active.proofOrder != nil ||
		execution.active.Manifest.TimeNs == "0" || len(execution.active.Accounts) != 6 || len(execution.manifests) < 1 {
		return plan, errDagSegment
	}
	if execution.checkActiveHistory() != nil {
		return plan, errDagSegment
	}
	sealed := execution.active.clone()
	sealed.seal()
	if sealed.Commitment != execution.active.Commitment {
		return plan, errDagSegment
	}
	plan.body = dagHistoryCutBody{Before: before, HistoryRoot: execution.active.history.root.id(), Schema: "gg.dag.history-cut.v1"}
	copy(plan.body.Accounts[:], execution.active.Accounts)
	plan.hash = dagDigest("GG-DAG-HISTORY-CUT-v1\x00", plan.body)
	plan.beforeHash = dagDigest("GG-DAG-SEGMENTED-STATE-v1\x00", before)
	next := *execution
	if err = next.closed.append(plan.hash); err != nil {
		return dagHistoryCutPlan{}, err
	}
	next.closedBlocks, next.closedBytes, next.lastCut = before.Blocks, before.RawBytes, plan.hash
	next.baseCut = &plan.body
	next.baseBeforeClosed = execution.closed.peaks
	next.baseAuthorHeads = execution.authorHeads
	next.manifests = nil
	next.active = execution.active.clone()
	next.active.history = dagHistory{segmented: true}
	next.active.pending = map[string]dagRecord{}
	next.active.payloadReader = nil
	next.active.proofOrder = nil
	next.active.bytes = 0
	next.active.orderRoot = dagOrderAccumulator{}
	next.active.segmentParent, next.active.segmentPrecheck = plan.hash, plan.hash
	next.active.segmentRankBase = execution.lastRank
	next.active.segmentSequenceBase = append([]uint64(nil), execution.active.sequences...)
	for i := range next.active.heads {
		next.active.heads[i] = plan.hash
	}
	next.active.Manifest = DagManifest{Blocks: []string{}, Checkpoint: 0, GenesisHash: execution.anchor,
		Previous: plan.hash, Schema: "gg.dag.execution.manifest.v1", SourceHash: before.SourceHash, TimeNs: execution.active.Manifest.TimeNs}
	next.active.seal()
	next.startManifest = next.active.Commitment.ManifestHash
	next.captureSegmentBase()
	if _, err = next.state(); err != nil {
		return dagHistoryCutPlan{}, err
	}
	plan.next = &next
	return plan, nil
}

func (plan dagHistoryCutPlan) matches(execution *dagSegmentedExecution) error {
	expected, err := execution.prepareCut()
	if err != nil || plan.hash != expected.hash || plan.beforeHash != expected.beforeHash || plan.body != expected.body || plan.next == nil {
		return errDagSegment
	}
	actualState, err := plan.next.state()
	if err != nil {
		return err
	}
	expectedState, err := expected.next.state()
	if err != nil || actualState != expectedState {
		return errDagSegment
	}
	return nil
}
