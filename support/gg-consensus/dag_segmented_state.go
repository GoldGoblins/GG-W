package main

// Public shape/commitment rules for explicit segmented SDK genesis. A shape
// check is never a history replay or quorum proof; verifyInput supplies the
// separately pinned SDK certificate, native startup supplies full replay.
import (
	"bytes"
	"context"
	"errors"
	abci "github.com/cometbft/cometbft/abci/types"
	"strconv"
)

// Native SDK wiring is behind an interface so public WASM verification never
// imports the LevelDB/archive writer implementation.
type dagSegmentedApplication interface {
	CheckTx(context.Context, *abci.RequestCheckTx) (*abci.ResponseCheckTx, error)
	PrepareProposal(context.Context, *abci.RequestPrepareProposal) (*abci.ResponsePrepareProposal, error)
	ProcessProposal(context.Context, *abci.RequestProcessProposal) (*abci.ResponseProcessProposal, error)
	FinalizeBlock(context.Context, *abci.RequestFinalizeBlock) (*abci.ResponseFinalizeBlock, error)
	Commit(context.Context, *abci.RequestCommit) (*abci.ResponseCommit, error)
	CutTransaction(context.Context, int64) (dagSegmentCutTransaction, error)
	PublicProof(context.Context, State, string, string, int) (any, error)
	Close() error
}

func hasDagExecution(genesis Genesis) bool {
	return genesis.DAG != nil || genesis.DAGSegmented != nil || genesis.FinancialDAG != nil
}

func validateSegmentedGenesis(genesis Genesis) error {
	if genesis.DAG != nil || genesis.DAGSegmented == nil || validateSegmentedSource(*genesis.DAGSegmented) != nil {
		return errors.New("GG_GENESIS_SEGMENTED_SOURCE")
	}
	started, _ := dagDecimalNs(genesis.DAGSegmented.StartedAtNs)
	if genesis.GenesisTime <= 0 || genesis.GenesisTime > (int64(dagSegmentCounterMax)-5000000000)/1000000000 ||
		started > genesis.GenesisTime*1000000000+5000000000 {
		return errors.New("GG_GENESIS_SEGMENTED_TIME")
	}
	for _, validator := range genesis.Validators {
		for _, producer := range genesis.DAGSegmented.Genesis.Producers {
			if validator == producer {
				return errors.New("GG_GENESIS_DAG_VALIDATOR_ROLE")
			}
		}
	}
	return nil
}

func validateSegmentedState(value dagSegmentedState, source dagSegmentedSource, anchor string) error {
	if validateSegmentedSource(source) != nil || !pubPattern.MatchString(anchor) || value.Schema != "gg.dag.segmented-commitment.v1" ||
		value.Anchor != anchor || value.SourceHash != dagDigest("GG-DAG-CONSENSUS-SOURCE-v2\x00", source) ||
		value.Epoch < 1 || value.Epoch > dagSegmentCounterMax || value.Blocks > dagSegmentCounterMax || value.LastRank < 0 ||
		uint64(value.LastRank) > value.Blocks || uint64(value.LastRank) < value.Epoch-1 || value.Blocks > 0 && value.LastRank == 0 || value.Blocks < value.Epoch-1 || value.RawBytes < value.Blocks ||
		value.Active.Blocks < 0 || value.Active.Blocks > DagMaxRecords || uint64(value.Active.Blocks) > value.Blocks-(value.Epoch-1) ||
		value.Active.Checkpoint > uint64(value.Active.Blocks) || value.Active.Transactions != value.Transactions ||
		value.Transactions > 6*DagAllocation || value.Blocks <= dagSegmentCounterMax/DagMaxBlockTransactions && value.Transactions > value.Blocks*DagMaxBlockTransactions ||
		value.Active.Schema != "gg.dag.commitment.v1" || value.Active.ChainID != source.Genesis.ChainID ||
		value.Active.GenesisHash != source.GenesisHash || value.Active.NetworkID != source.NetworkID {
		return errDagSegment
	}
	for _, root := range []string{value.ClosedRoot, value.LastCut, value.Active.AccountRoot, value.Active.OrderRoot, value.Active.Previous, value.Active.ManifestHash} {
		if !pubPattern.MatchString(root) {
			return errDagSegment
		}
	}
	sequences, nonces := uint64(0), uint64(0)
	for i, author := range value.Authors {
		sequence, seqErr := strconv.ParseUint(author.Sequence, 10, 64)
		nonce, nonceErr := strconv.ParseUint(author.Nonce, 10, 64)
		if seqErr != nil || nonceErr != nil || sequence > uint64(value.LastRank) || sequence > value.Blocks || sequences > value.Blocks-sequence || nonce > DagAllocation ||
			sequence <= DagAllocation/DagMaxBlockTransactions && nonce > sequence*DagMaxBlockTransactions ||
			strconv.FormatUint(sequence, 10) != author.Sequence || strconv.FormatUint(nonce, 10) != author.Nonce ||
			author.Key != source.Genesis.Producers[i] || !pubPattern.MatchString(author.Head) || sequence == 0 && author.Head != source.GenesisHash {
			return errDagSegment
		}
		sequences += sequence
		nonces += nonce
	}
	if sequences != value.Blocks || nonces != value.Transactions {
		return errDagSegment
	}
	if value.Epoch == 1 {
		empty, _ := (dagClosedSegments{}).root()
		if value.LastCut != source.GenesisHash || value.ClosedRoot != empty || value.Blocks != uint64(value.Active.Blocks) || value.RawBytes > DagMaxHistoryWire {
			return errDagSegment
		}
	}
	if value.Active.Blocks == 0 {
		previous := value.LastCut
		if value.Epoch == 1 {
			previous = DagZero
			initial, err := newDagSegmentedExecution(source, anchor)
			if err != nil {
				return err
			}
			expected, _ := initial.state()
			if value != expected {
				return errDagSegment
			}
		} else if _, ok := dagDecimalNs(value.Active.TimeNs); !ok {
			return errDagSegment
		}
		manifest := DagManifest{Blocks: []string{}, Checkpoint: 0, GenesisHash: anchor, Previous: previous,
			Schema: "gg.dag.execution.manifest.v1", SourceHash: value.SourceHash, TimeNs: value.Active.TimeNs}
		if value.Active.Previous != previous || value.Active.ManifestHash != dagDigest("GG-DAG-CHECKPOINT-MANIFEST-v1\x00", manifest) ||
			value.Active.OrderRoot != (dagOrderAccumulator{}).root() {
			return errDagSegment
		}
	} else if value.Active.Checkpoint == 0 {
		return errDagSegment
	} else if _, ok := dagDecimalNs(value.Active.TimeNs); !ok {
		return errDagSegment
	}
	return nil
}

type dagSegmentCutTransaction struct {
	Before string `json:"before"`
	Cut    string `json:"cut"`
	Epoch  uint64 `json:"epoch,string"`
	Schema string `json:"schema"`
}

func (execution *dagSegmentedExecution) cutTransaction() (dagSegmentCutTransaction, error) {
	plan, err := execution.prepareCut()
	if err != nil {
		return dagSegmentCutTransaction{}, err
	}
	return dagSegmentCutTransaction{Before: plan.beforeHash, Cut: plan.hash, Epoch: execution.closed.count + 1, Schema: "gg.dag.segment-cut.tx.v1"}, nil
}

func (execution *dagSegmentedExecution) checkedCutTransaction(raw []byte) (dagHistoryCutPlan, error) {
	var value dagSegmentCutTransaction
	if len(raw) == 0 || len(raw) > 1024 || decodeStrict(raw, &value) != nil || !bytes.Equal(raw, canonical(value)) {
		return dagHistoryCutPlan{}, errDagSegment
	}
	expected, err := execution.cutTransaction()
	if err != nil || value != expected {
		return dagHistoryCutPlan{}, errDagSegment
	}
	return execution.prepareCut()
}
