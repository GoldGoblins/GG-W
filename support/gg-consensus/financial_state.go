package main

// Public financial state shape. A valid shape is not a replay or a certificate;
// the native journal and verifyInput provide those independent checks.
import (
	"context"
	abci "github.com/cometbft/cometbft/abci/types"
	"strconv"
)

type financialApplication interface {
	CheckTx(context.Context, *abci.RequestCheckTx) (*abci.ResponseCheckTx, error)
	PrepareProposal(context.Context, *abci.RequestPrepareProposal) (*abci.ResponsePrepareProposal, error)
	ProcessProposal(context.Context, *abci.RequestProcessProposal) (*abci.ResponseProcessProposal, error)
	FinalizeBlock(context.Context, *abci.RequestFinalizeBlock) (*abci.ResponseFinalizeBlock, error)
	Commit(context.Context, *abci.RequestCommit) (*abci.ResponseCommit, error)
	CutTransaction(context.Context, int64) ([]byte, int64, error)
	Receipt(context.Context, State, financialReceiptSelector) (financialCertifiedReceipt, error)
	ProducerContext(context.Context, State, int) (financialProducerContext, error)
	Account(context.Context, State, string) (financialCertifiedAccount, error)
	Registry(context.Context, State, protocolRegistrySelector) (financialCertifiedRegistry, error)
	Block(context.Context, State, string) (financialCertifiedBlock, error)
	RecentBlocks(context.Context, State, financialRecentSelector) (financialRecentBlocks, error)
	Reward(context.Context, State, protocolRewardSelector) (financialCertifiedReward, error)
	CommitteeState(context.Context, uint64) (State, error)
	OriginalCore(context.Context, financialOriginalCoreSelector) (financialOriginalCoreChunk, error)
	Close() error
}

func validateFinancialCommitment(value financialDagCommitment, genesis Genesis, anchor string) error {
	if genesis.FinancialDAG == nil || genesis.FinancialDAG.validateShape(genesis) != nil || !pubPattern.MatchString(anchor) ||
		validateFinancialVersionFields(value, *genesis.FinancialDAG) != nil || value.Anchor != anchor || value.SourceHash != genesis.FinancialDAG.hash() ||
		value.Epoch < 1 || value.Epoch > dagSegmentCounterMax || value.Blocks > dagSegmentCounterMax || value.Blocks < value.Epoch-1 ||
		value.Attempts > dagSegmentCounterMax || value.Applied > value.Attempts || value.Rejected != value.Attempts-value.Applied ||
		value.Operations > dagSegmentCounterMax || !genesis.FinancialDAG.hasProtocol() && value.Operations != 0 ||
		value.Checkpoint > dagSegmentCounterMax || value.Checkpoint < value.Epoch-1 || value.Checkpoint-(value.Epoch-1) > value.Blocks+value.Operations ||
		value.Blocks > 0 && value.Checkpoint == value.Epoch-1 || value.RawBytes > dagSegmentCounterMax || value.RawBytes < value.Blocks ||
		value.ActiveBlocks < 0 || value.ActiveBlocks > DagMaxRecords || uint64(value.ActiveBlocks) > value.Blocks-(value.Epoch-1) ||
		value.ActiveBytes > DagMaxHistoryWire || value.ActiveBytes > value.RawBytes || value.ActiveBytes < uint64(value.ActiveBlocks) ||
		value.LastRank > value.Blocks || !genesis.FinancialDAG.hasLineage() && value.LastRank < value.Epoch-1 || value.Blocks > 0 && value.LastRank == 0 ||
		value.Blocks <= dagSegmentCounterMax/financialMaxTransactions && value.Attempts > value.Blocks*financialMaxTransactions ||
		value.Epoch == 1 && uint64(value.ActiveBlocks) != value.Blocks {
		return errFinancialDag
	}
	if generalFinancialAccounts(genesis) && validateFinancialAccountRoot(value.AccountTree, genesis, anchor, value.Applied) != nil {
		return errFinancialDag
	}
	when, ok := dagDecimalNs(value.TimeNs)
	start, _ := dagDecimalNs(genesis.FinancialDAG.StartedAtNs)
	if !ok || when < start || when > int64(dagSegmentCounterMax)-5000000000 {
		return errFinancialDag
	}
	for _, root := range []string{value.AccountRoot, value.ActiveOrderRoot, value.ClosedRoot, value.IndexRoot, value.LastCut, value.Previous, value.ReceiptsRoot, value.SummaryIndex} {
		if !pubPattern.MatchString(root) {
			return errFinancialDag
		}
	}
	sequences, attempts := uint64(0), uint64(0)
	for index, author := range value.Authors {
		if author.Key != genesis.FinancialDAG.Producers[index] || !pubPattern.MatchString(author.Head) ||
			author.Sequence > value.Blocks-sequences || author.Attempts > value.Attempts-attempts ||
			author.Sequence <= dagSegmentCounterMax/financialMaxTransactions && author.Attempts > author.Sequence*financialMaxTransactions {
			return errFinancialDag
		}
		sequences += author.Sequence
		attempts += author.Attempts
	}
	if !genesis.FinancialDAG.hasProtocol() && (sequences != value.Blocks || attempts != value.Attempts) {
		return errFinancialDag
	}
	if value.ActiveBlocks == 0 && (value.ActiveBytes != 0 || value.IndexRoot != DagZero || value.SummaryIndex != DagZero || value.ActiveOrderRoot != (dagOrderAccumulator{}).root()) {
		return errFinancialDag
	}
	if value.Epoch == 1 {
		emptyClosed, err := (dagClosedSegments{}).root()
		if err != nil || value.ClosedRoot != emptyClosed || value.LastCut != financialDagOrigin(*genesis.FinancialDAG, anchor) {
			return errFinancialDag
		}
		if !genesis.FinancialDAG.hasProtocol() && value.Blocks == 0 {
			initial, err := newFinancialDagExecution(genesis, anchor, *genesis.FinancialDAG)
			if err != nil {
				return err
			}
			zero, err := initial.commitment()
			if err != nil || !streamCanonicalEqual(canonical(value), zero) {
				return errFinancialDag
			}
		}
	}
	return nil
}

func financialNativeState(base State, execution *financialDagExecution, height int64) (State, error) {
	value, err := execution.commitment()
	if err != nil || execution.provisional {
		return State{}, errFinancialDag
	}
	state := copyState(base)
	state.Accounts = append([]Account(nil), execution.money.Accounts...)
	if generalFinancialAccounts(execution.genesis) {
		root := execution.money.Tree.root.link
		state.AccountTree = &root
	}
	state.FinancialDAG, state.Height = &value, height
	if publicFinancialProtocol(execution.genesis) {
		protocol := execution.money.Protocol.commitment()
		state.Protocol = &protocol
		state.SupplyAtomic = protocol.Economics.Issued
		state.Schema = "gg.native.state.v6"
	}
	sealState(&state)
	if err := validateState(state, execution.genesis, execution.anchor); err != nil {
		return State{}, err
	}
	return state, nil
}

func financialHeightKey(height int64) string {
	text := strconv.FormatInt(height, 10)
	for len(text) < 20 {
		text = "0" + text
	}
	return "j/" + text
}
