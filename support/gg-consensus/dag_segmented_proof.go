package main

// Selected membership only. Every proof binds the entire certified segmented
// commitment; it does not prove full history replay or archive availability.
import (
	"errors"
	"strconv"
)

type dagSegmentedAccountProof struct {
	Commitment  dagSegmentedState `json:"commitment"`
	GenesisHash string            `json:"genesis_hash"`
	Height      int64             `json:"height"`
	Index       int               `json:"index"`
	Leaf        Account           `json:"leaf"`
	Path        []PathItem        `json:"path"`
	Schema      string            `json:"schema"`
	StateRoot   string            `json:"state_root"`
}

// The internal order hash retains its exact existing uint64 decimal encoding.
// Public counters use strings so a JS/JSON roundtrip cannot round a sequence or
// global index. CreatorKey and GlobalIndex are derived and checked, never trust.
type dagSegmentedOrderLeaf struct {
	CreatorKey   string `json:"creator_key"`
	GlobalIndex  string `json:"global_index"`
	Hash         string `json:"hash"`
	Index        int    `json:"index"`
	Producer     int    `json:"producer_index"`
	Sequence     string `json:"sequence"`
	Transactions int    `json:"transactions"`
}

type dagSegmentedBlockProof struct {
	Commitment  dagSegmentedState     `json:"commitment"`
	GenesisHash string                `json:"genesis_hash"`
	Height      int64                 `json:"height"`
	Leaf        dagSegmentedOrderLeaf `json:"leaf"`
	Path        []PathItem            `json:"path"`
	Schema      string                `json:"schema"`
	StateRoot   string                `json:"state_root"`
}

type dagSegmentedOrderWitness struct {
	Leaf dagSegmentedOrderLeaf `json:"leaf"`
	Path []PathItem            `json:"path"`
}

type dagSegmentedOrderPage struct {
	Commitment  dagSegmentedState          `json:"commitment"`
	Complete    bool                       `json:"complete"`
	GenesisHash string                     `json:"genesis_hash"`
	Height      int64                      `json:"height"`
	Items       []dagSegmentedOrderWitness `json:"items"`
	Schema      string                     `json:"schema"`
	Start       int                        `json:"start"`
	StateRoot   string                     `json:"state_root"`
}

var errDagSegmentProof = errors.New("GG_DAG_SEGMENTED_MEMBERSHIP_PROOF")

func segmentedProofContext(value dagSegmentedState, anchor string, height int64, root string, state State, source dagSegmentedSource) error {
	if state.DAGSegmented == nil || state.DAG != nil || value != *state.DAGSegmented || anchor != state.GenesisHash ||
		height != state.Height || root != state.StateRoot || validateSegmentedState(value, source, anchor) != nil {
		return errDagSegmentProof
	}
	return nil
}

func segmentedPublicLeaf(leaf DagOrderLeaf, value dagSegmentedState, source dagSegmentedSource) (dagSegmentedOrderLeaf, error) {
	if leaf.Producer < 0 || leaf.Producer >= 6 || leaf.Index < 1 || leaf.Index > value.Active.Blocks {
		return dagSegmentedOrderLeaf{}, errDagSegmentProof
	}
	return dagSegmentedOrderLeaf{CreatorKey: source.Genesis.Producers[leaf.Producer],
		GlobalIndex: strconv.FormatUint(value.Blocks-uint64(value.Active.Blocks)+uint64(leaf.Index), 10), Hash: leaf.Hash,
		Index: leaf.Index, Producer: leaf.Producer, Sequence: strconv.FormatUint(leaf.Sequence, 10), Transactions: leaf.Transactions}, nil
}

func checkedSegmentedLeaf(leaf dagSegmentedOrderLeaf, value dagSegmentedState, source dagSegmentedSource) (DagOrderLeaf, error) {
	if !pubPattern.MatchString(leaf.Hash) || leaf.Index < 1 || leaf.Index > value.Active.Blocks || leaf.Producer < 0 || leaf.Producer >= 6 ||
		leaf.CreatorKey != source.Genesis.Producers[leaf.Producer] || leaf.Transactions < 0 || leaf.Transactions > DagMaxBlockTransactions ||
		leaf.GlobalIndex != strconv.FormatUint(value.Blocks-uint64(value.Active.Blocks)+uint64(leaf.Index), 10) {
		return DagOrderLeaf{}, errDagSegmentProof
	}
	allowed := false
	for _, producer := range source.AllowedProducers {
		allowed = allowed || producer == leaf.Producer
	}
	sequence, err := strconv.ParseUint(leaf.Sequence, 10, 64)
	last, lastErr := strconv.ParseUint(value.Authors[leaf.Producer].Sequence, 10, 64)
	if !allowed || err != nil || lastErr != nil || sequence < 1 || sequence > last || sequence > value.Blocks ||
		strconv.FormatUint(sequence, 10) != leaf.Sequence {
		return DagOrderLeaf{}, errDagSegmentProof
	}
	return DagOrderLeaf{Hash: leaf.Hash, Index: leaf.Index, Producer: leaf.Producer, Sequence: sequence, Transactions: leaf.Transactions}, nil
}

func verifySegmentedAccountProof(proof dagSegmentedAccountProof, state State, source dagSegmentedSource) error {
	if proof.Schema != "gg.dag.segmented-account-proof.v1" || proof.Path == nil || segmentedProofContext(proof.Commitment, proof.GenesisHash, proof.Height, proof.StateRoot, state, source) != nil ||
		proof.Index < 0 || proof.Index >= len(source.Accounts) || proof.Leaf.Address != source.Accounts[proof.Index] || proof.Leaf.Nonce > DagAllocation {
		return errDagSegmentProof
	}
	balance, err := strconv.ParseUint(proof.Leaf.Balance, 10, 64)
	if err != nil || strconv.FormatUint(balance, 10) != proof.Leaf.Balance || balance > 6*DagAllocation {
		return errDagSegmentProof
	}
	for _, author := range proof.Commitment.Authors {
		if author.Key == proof.Leaf.Address && author.Nonce != strconv.FormatUint(proof.Leaf.Nonce, 10) {
			return errDagSegmentProof
		}
	}
	return verifyDagPath(proof.Leaf, proof.Path, proof.Index, 6, proof.Commitment.Active.AccountRoot, "GG-DAG-ACCOUNT-v1\x00")
}

func verifySegmentedBlockProof(proof dagSegmentedBlockProof, state State, source dagSegmentedSource) error {
	if proof.Schema != "gg.dag.segmented-block-proof.v1" || proof.Path == nil || segmentedProofContext(proof.Commitment, proof.GenesisHash, proof.Height, proof.StateRoot, state, source) != nil {
		return errDagSegmentProof
	}
	leaf, err := checkedSegmentedLeaf(proof.Leaf, proof.Commitment, source)
	if err != nil {
		return err
	}
	return verifyDagPath(leaf, proof.Path, leaf.Index-1, proof.Commitment.Active.Blocks, proof.Commitment.Active.OrderRoot, dagOrderDomain)
}

func verifySegmentedOrderPage(page dagSegmentedOrderPage, state State, source dagSegmentedSource) error {
	if page.Schema != "gg.dag.segmented-order-page.v1" || page.Items == nil ||
		segmentedProofContext(page.Commitment, page.GenesisHash, page.Height, page.StateRoot, state, source) != nil || page.Start < 0 ||
		page.Start > page.Commitment.Active.Blocks || page.Start%DagOrderPageSize != 0 || page.Start == page.Commitment.Active.Blocks && page.Start != 0 {
		return errDagSegmentProof
	}
	count := min(DagOrderPageSize, page.Commitment.Active.Blocks-page.Start)
	if len(page.Items) != count || page.Complete != (page.Start+count == page.Commitment.Active.Blocks) {
		return errDagSegmentProof
	}
	for index, witness := range page.Items {
		leaf, err := checkedSegmentedLeaf(witness.Leaf, page.Commitment, source)
		if err != nil || witness.Path == nil || leaf.Index != page.Start+index+1 || verifyDagPath(leaf, witness.Path, leaf.Index-1, page.Commitment.Active.Blocks, page.Commitment.Active.OrderRoot, dagOrderDomain) != nil {
			return errDagSegmentProof
		}
	}
	return nil
}
