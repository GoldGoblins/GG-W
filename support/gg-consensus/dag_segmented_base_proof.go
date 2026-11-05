package main

// SDK-selected epoch base. The last-cut preimage and authenticated closed-tree
// append derive the base; no caller-supplied account snapshot is trusted. This
// verifies a certified base, NOT original-signed full-history replay.
import (
	"bytes"
	"encoding/json"
	"errors"
	"strconv"
)

const dagSegmentedBaseScope = "SDK_CERTIFIED_CUT_PREIMAGE_AND_EPOCH_BASE_NOT_FULL_HISTORY_REPLAY"

var errDagSegmentedBaseProof = errors.New("GG_DAG_SEGMENTED_BASE_PROOF")

type dagSegmentedBaseProof struct {
	Commitment     dagSegmentedState `json:"commitment"`
	Cut            json.RawMessage   `json:"cut"`
	GenesisHash    string            `json:"genesis_hash"`
	Height         int64             `json:"height"`
	PreviousClosed []string          `json:"previous_closed"`
	Schema         string            `json:"schema"`
	StateRoot      string            `json:"state_root"`
}

type dagVerifiedEpochBase struct {
	Accounts   [6]Account        `json:"accounts"`
	Commitment dagSegmentedState `json:"commitment"`
}

func derivedSegmentedBase(current dagSegmentedState, source dagSegmentedSource, cut json.RawMessage, previous []string) (*dagVerifiedEpochBase, error) {
	if validateSegmentedState(current, source, current.Anchor) != nil || previous == nil {
		return nil, errDagSegmentedBaseProof
	}
	result := &dagVerifiedEpochBase{}
	if current.Epoch == 1 {
		if !bytes.Equal(cut, []byte("null")) || len(previous) != 0 {
			return nil, errDagSegmentedBaseProof
		}
		initial, err := newDagSegmentedExecution(source, current.Anchor)
		if err != nil {
			return nil, err
		}
		result.Commitment, err = initial.state()
		if err != nil {
			return nil, err
		}
		copy(result.Accounts[:], initial.active.Accounts)
	} else {
		var body dagHistoryCutBody
		// Canonical raw bytes also reject fixed-array truncation, duplicate or
		// omitted fields. The public decoder alone must not discard a seventh
		// account and then hash only the first six as if the input were exact.
		if len(cut) == 0 || len(cut) > 256*1024 || decodeStrictLimited(cut, &body, 128, 64) != nil ||
			!bytes.Equal(cut, canonical(body)) || body.Schema != "gg.dag.history-cut.v1" || !pubPattern.MatchString(body.HistoryRoot) ||
			dagDigest("GG-DAG-HISTORY-CUT-v1\x00", body) != current.LastCut || len(previous) != 64 ||
			validateSegmentedState(body.Before, source, current.Anchor) != nil || body.Before.Epoch >= dagSegmentCounterMax ||
			body.Before.Epoch+1 != current.Epoch || body.Before.Active.Blocks < 1 {
			return nil, errDagSegmentedBaseProof
		}
		tree := dagClosedSegments{count: body.Before.Epoch - 1}
		copy(tree.peaks[:], previous)
		root, err := tree.root()
		if err != nil || root != body.Before.ClosedRoot || tree.append(current.LastCut) != nil {
			return nil, errDagSegmentedBaseProof
		}
		root, err = tree.root()
		if err != nil || root != current.ClosedRoot {
			return nil, errDagSegmentedBaseProof
		}
		before := body.Before
		result.Commitment = before
		result.Commitment.Epoch++
		result.Commitment.LastCut, result.Commitment.ClosedRoot = current.LastCut, root
		manifest := DagManifest{Blocks: []string{}, Checkpoint: 0, GenesisHash: current.Anchor, Previous: current.LastCut,
			Schema: "gg.dag.execution.manifest.v1", SourceHash: current.SourceHash, TimeNs: before.Active.TimeNs}
		result.Commitment.Active.Blocks, result.Commitment.Active.Checkpoint = 0, 0
		result.Commitment.Active.Previous = current.LastCut
		result.Commitment.Active.OrderRoot = (dagOrderAccumulator{}).root()
		result.Commitment.Active.ManifestHash = dagDigest("GG-DAG-CHECKPOINT-MANIFEST-v1\x00", manifest)
		result.Accounts = body.Accounts
	}
	base := result.Commitment
	if validateSegmentedState(base, source, current.Anchor) != nil || current.Blocks < uint64(current.Active.Blocks) ||
		current.Blocks-uint64(current.Active.Blocks) != base.Blocks || current.RawBytes < base.RawBytes ||
		current.RawBytes-base.RawBytes > DagMaxHistoryWire || current.Transactions < base.Transactions ||
		current.Transactions-base.Transactions > uint64(current.Active.Blocks)*DagMaxBlockTransactions ||
		current.LastRank < base.LastRank || current.LastRank-base.LastRank > int64(current.Active.Blocks) {
		return nil, errDagSegmentedBaseProof
	}
	if current.Active.Blocks == 0 && current != base || current.Active.Blocks > 0 && (current.RawBytes == base.RawBytes || current.LastRank == base.LastRank) {
		return nil, errDagSegmentedBaseProof
	}
	baseTime, timeErr := strconv.ParseInt(base.Active.TimeNs, 10, 64)
	currentTime, currentTimeErr := strconv.ParseInt(current.Active.TimeNs, 10, 64)
	if timeErr != nil || currentTimeErr != nil || currentTime < baseTime {
		return nil, errDagSegmentedBaseProof
	}
	total := uint64(0)
	for index, account := range result.Accounts {
		balance, err := strconv.ParseUint(account.Balance, 10, 64)
		if account.Address != source.Accounts[index] || account.Nonce > DagAllocation || err != nil ||
			strconv.FormatUint(balance, 10) != account.Balance || balance > 6*DagAllocation {
			return nil, errDagSegmentedBaseProof
		}
		total += balance
		for _, author := range base.Authors {
			if author.Key == account.Address && author.Nonce != strconv.FormatUint(account.Nonce, 10) {
				return nil, errDagSegmentedBaseProof
			}
		}
	}
	if total != 6*DagAllocation || dagRoot(result.Accounts[:], "GG-DAG-ACCOUNT-v1\x00") != base.Active.AccountRoot {
		return nil, errDagSegmentedBaseProof
	}
	for index, author := range base.Authors {
		baseSequence, _ := strconv.ParseUint(author.Sequence, 10, 64)
		sequence, _ := strconv.ParseUint(current.Authors[index].Sequence, 10, 64)
		baseNonce, _ := strconv.ParseUint(author.Nonce, 10, 64)
		nonce, _ := strconv.ParseUint(current.Authors[index].Nonce, 10, 64)
		if sequence < baseSequence || nonce < baseNonce || sequence-baseSequence > uint64(current.Active.Blocks) ||
			nonce-baseNonce > (sequence-baseSequence)*DagMaxBlockTransactions ||
			sequence == baseSequence && current.Authors[index].Head != author.Head {
			return nil, errDagSegmentedBaseProof
		}
	}
	return result, nil
}

func verifySegmentedBaseProof(proof dagSegmentedBaseProof, state State, source dagSegmentedSource) (*dagVerifiedEpochBase, error) {
	if proof.Schema != "gg.dag.segmented-base-proof.v1" ||
		segmentedProofContext(proof.Commitment, proof.GenesisHash, proof.Height, proof.StateRoot, state, source) != nil {
		return nil, errDagSegmentedBaseProof
	}
	return derivedSegmentedBase(proof.Commitment, source, proof.Cut, proof.PreviousClosed)
}
