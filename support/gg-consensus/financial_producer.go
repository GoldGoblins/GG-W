package main

// Source v2 exposes the operational creator epoch and cut rank in its signed
// state commitment. Source v1 encodings and roots remain unchanged. A producer
// must verify this context against an independently pinned SDK certificate.
import (
	"context"
	"errors"
	"sort"
	"strconv"
)

var errFinancialProducer = errors.New("GG_FINANCIAL_PRODUCER_CONTEXT")

func financialCounter(text string) (uint64, bool) {
	value, err := strconv.ParseUint(text, 10, 64)
	return value, err == nil && value <= dagSegmentCounterMax && strconv.FormatUint(value, 10) == text
}

func validateFinancialVersionFields(value financialDagCommitment, source financialDagSource) error {
	if source.hasProtocol() {
		if value.Schema != "gg.financial-dag.commitment.v5" || value.Authors != nil || value.ProducerRoot == nil || value.AccountTree == nil || value.AccountTree.Hash != value.AccountRoot ||
			!pubPattern.MatchString(value.LineageRoot) || (value.Blocks == 0) != (value.LineageRoot == DagZero) {
			return errFinancialDag
		}
		base, valid := financialCounter(value.EpochBaseRank)
		if !valid || base > value.LastRank {
			return errFinancialDag
		}
		return nil
	}
	if value.ProducerRoot != nil || len(value.Authors) != 6 {
		return errFinancialDag
	}
	if source.hasGeneralAccounts() {
		if value.AccountTree == nil || value.AccountTree.Hash != value.AccountRoot {
			return errFinancialDag
		}
	} else if value.AccountTree != nil {
		return errFinancialDag
	}
	if source.Schema == "gg.financial-dag.source.v1" {
		if value.Schema != "gg.financial-dag.commitment.v1" || value.EpochBaseRank != "" || value.LineageRoot != "" {
			return errFinancialDag
		}
		for _, author := range value.Authors {
			if author.Epoch != "" {
				return errFinancialDag
			}
		}
		return nil
	}
	if source.hasLineage() {
		schema := "gg.financial-dag.commitment.v3"
		if source.hasGeneralAccounts() {
			schema = "gg.financial-dag.commitment.v4"
		}
		if value.Schema != schema || !pubPattern.MatchString(value.LineageRoot) || (value.Blocks == 0) != (value.LineageRoot == DagZero) {
			return errFinancialDag
		}
	} else if source.Schema != "gg.financial-dag.source.v2" || value.Schema != "gg.financial-dag.commitment.v2" || value.LineageRoot != "" {
		return errFinancialDag
	}
	base, ok := financialCounter(value.EpochBaseRank)
	if !ok || base > value.LastRank || value.Epoch == 1 && base != 0 || !source.hasLineage() && value.Epoch > 1 && base < value.Epoch-1 {
		return errFinancialDag
	}
	active := 0
	for _, author := range value.Authors {
		epoch, ok := financialCounter(author.Epoch)
		if !ok || epoch > value.Epoch || author.Sequence == 0 && epoch != 0 || author.Sequence > 0 && epoch == 0 {
			return errFinancialDag
		}
		if source.hasLineage() && author.Sequence == 0 && author.Head != financialDagOrigin(source, value.Anchor) {
			return errFinancialDag
		}
		if author.Sequence > 0 && epoch == value.Epoch {
			active++
		}
	}
	if active > value.ActiveBlocks {
		return errFinancialDag
	}
	return nil
}

type financialProducerContext struct {
	Epoch       uint64           `json:"epoch,string"`
	GenesisHash string           `json:"genesis_hash"`
	Height      int64            `json:"height"`
	Parent      string           `json:"parent"`
	ParentPath  []dagHistoryBody `json:"parent_path"`
	ParentRank  uint64           `json:"parent_rank,string"`
	Producer    int              `json:"producer_index"`
	Schema      string           `json:"schema"`
	Sequence    uint64           `json:"sequence,string"`
	SourceHash  string           `json:"source_hash"`
	StateRoot   string           `json:"state_root"`
}

func financialHistoryWitness(ctx context.Context, tree dagHistory, key string) ([]dagHistoryBody, error) {
	path := []dagHistoryBody{}
	ref := tree.root
	for depth := 0; ref.id() != DagZero; depth++ {
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		if depth >= 64 {
			return nil, errFinancialProducer
		}
		node, err := tree.load(ref)
		if err != nil || node == nil {
			return nil, errDagHistoryUnavailable
		}
		path = append(path, node.body)
		if key == node.body.Key {
			return path, nil
		}
		if key < node.body.Key {
			ref = node.left
		} else {
			ref = node.right
		}
	}
	return nil, errFinancialProducer
}

func checkFinancialHistoryWitness(root, key string, path []dagHistoryBody) (dagHistoryValue, error) {
	if len(path) < 1 || len(path) > 64 || !pubPattern.MatchString(root) {
		return dagHistoryValue{}, errFinancialProducer
	}
	expected := root
	for at, body := range path {
		if !validHistoryBodyLimits(body, int64(dagSegmentCounterMax), dagSegmentCounterMax) || historyDigest(body) != expected {
			return dagHistoryValue{}, errFinancialProducer
		}
		if key == body.Key {
			if at != len(path)-1 {
				return dagHistoryValue{}, errFinancialProducer
			}
			return body.Value, nil
		}
		if key < body.Key {
			expected = body.Left
		} else {
			expected = body.Right
		}
	}
	return dagHistoryValue{}, errFinancialProducer
}

func checkFinancialProducerContext(proof financialProducerContext, state State, genesis Genesis) error {
	value := state.FinancialDAG
	if value == nil || genesis.FinancialDAG == nil || genesis.FinancialDAG.hasProtocol() || (genesis.FinancialDAG.Schema != "gg.financial-dag.source.v2" && !genesis.FinancialDAG.hasLineage()) || len(genesis.FinancialDAG.Producers) != 6 ||
		proof.Schema != "gg.financial-dag.producer-context.v1" || proof.Height != state.Height || proof.StateRoot != state.StateRoot || proof.GenesisHash != state.GenesisHash ||
		proof.SourceHash != value.SourceHash || proof.Epoch != value.Epoch || proof.Producer < 0 || proof.Producer >= 6 || proof.ParentPath == nil ||
		validateFinancialVersionFields(*value, *genesis.FinancialDAG) != nil {
		return errFinancialProducer
	}
	source := genesis.FinancialDAG
	allowed := sort.SearchInts(source.AllowedProducers, proof.Producer)
	if allowed >= len(source.AllowedProducers) || source.AllowedProducers[allowed] != proof.Producer {
		return errFinancialProducer
	}
	author := value.Authors[proof.Producer]
	if author.Sequence == dagSegmentCounterMax || proof.Sequence != author.Sequence+1 {
		return errFinancialProducer
	}
	epoch, _ := financialCounter(author.Epoch)
	if author.Sequence > 0 && (epoch == value.Epoch || source.hasLineage()) {
		if proof.Parent != author.Head {
			return errFinancialProducer
		}
		root := value.IndexRoot
		if source.hasLineage() {
			root = value.LineageRoot
		}
		leaf, err := checkFinancialHistoryWitness(root, "b/"+author.Head, proof.ParentPath)
		if err != nil || leaf.Record == nil || leaf.Record.Hash != author.Head || leaf.Record.Rank < 1 || uint64(leaf.Record.Rank) != proof.ParentRank {
			return errFinancialProducer
		}
	} else {
		base, ok := financialCounter(value.EpochBaseRank)
		parent := value.LastCut
		if source.hasLineage() {
			parent, base = financialDagOrigin(*source, value.Anchor), 0
		}
		if !ok || proof.Parent != parent || proof.ParentRank != base || len(proof.ParentPath) != 0 {
			return errFinancialProducer
		}
	}
	if proof.ParentRank >= dagSegmentCounterMax {
		return errFinancialProducer
	}
	return nil
}

type financialProducerView struct {
	commitment financialDagCommitment
	history    dagHistory
	lineage    dagHistory
}

const financialProducerViewLimit = 8

// Optional compact account metadata is a value. State copies deliberately own
// separate pointers, so pointer identity must never select a producer witness.
func equalFinancialCommitments(left, right financialDagCommitment) bool {
	return streamCanonicalEqual(canonical(left), right)
}

func financialProducerViews(previous []financialProducerView, execution *financialDagExecution) ([]financialProducerView, error) {
	if execution.source.hasProtocol() {
		return nil, nil
	}
	if execution.source.Schema != "gg.financial-dag.source.v2" && !execution.source.hasLineage() {
		return previous, nil
	}
	value, err := execution.commitment()
	if err != nil {
		return nil, err
	}
	if len(previous) > 0 && equalFinancialCommitments(previous[len(previous)-1].commitment, value) {
		return previous, nil
	}
	start := 0
	if len(previous) >= financialProducerViewLimit {
		start = len(previous) - financialProducerViewLimit + 1
	}
	next := append([]financialProducerView{}, previous[start:]...)
	return append(next, financialProducerView{commitment: value, history: execution.history, lineage: execution.lineage}), nil
}

func makeFinancialProducerContext(ctx context.Context, state State, genesis Genesis, producer int, views []financialProducerView) (financialProducerContext, error) {
	if state.FinancialDAG == nil || genesis.FinancialDAG == nil || genesis.FinancialDAG.hasProtocol() || len(state.FinancialDAG.Authors) != 6 || producer < 0 || producer >= 6 {
		return financialProducerContext{}, errFinancialProducer
	}
	value := state.FinancialDAG
	author := value.Authors[producer]
	epoch, _ := financialCounter(author.Epoch)
	base, _ := financialCounter(value.EpochBaseRank)
	proof := financialProducerContext{Epoch: value.Epoch, GenesisHash: state.GenesisHash, Height: state.Height, Parent: value.LastCut, ParentPath: []dagHistoryBody{}, ParentRank: base,
		Producer: producer, Schema: "gg.financial-dag.producer-context.v1", Sequence: author.Sequence + 1, SourceHash: value.SourceHash, StateRoot: state.StateRoot}
	if genesis.FinancialDAG.hasLineage() {
		proof.Parent, proof.ParentRank = financialDagOrigin(*genesis.FinancialDAG, value.Anchor), 0
	}
	if author.Sequence > 0 && (epoch == value.Epoch || genesis.FinancialDAG.hasLineage()) {
		found := false
		for _, view := range views {
			if equalFinancialCommitments(view.commitment, *value) {
				tree := view.history
				if genesis.FinancialDAG.hasLineage() {
					tree = view.lineage
				}
				path, err := financialHistoryWitness(ctx, tree, "b/"+author.Head)
				if err != nil {
					return financialProducerContext{}, err
				}
				leaf := path[len(path)-1].Value
				if leaf.Record == nil {
					return financialProducerContext{}, errFinancialProducer
				}
				proof.Parent, proof.ParentPath, proof.ParentRank = author.Head, path, uint64(leaf.Record.Rank)
				found = true
				break
			}
		}
		if !found {
			return financialProducerContext{}, errFinancialProducer
		}
	}
	if ctx.Err() != nil {
		return financialProducerContext{}, ctx.Err()
	}
	if err := checkFinancialProducerContext(proof, state, genesis); err != nil {
		return financialProducerContext{}, err
	}
	return proof, nil
}
