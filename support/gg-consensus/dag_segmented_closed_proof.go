package main

// Closed membership binds an arbitrary archived cut to the current SDK root.
// It authenticates selected order leaves, not original availability or replay.
import (
	"bytes"
	"encoding/json"
	"errors"
	"strconv"
)

const dagClosedMembershipScope = "SDK_CERTIFIED_CLOSED_CUT_AND_SELECTED_MEMBERSHIP_NOT_FULL_HISTORY_REPLAY"

var errDagClosedProof = errors.New("GG_DAG_CLOSED_MEMBERSHIP_PROOF")

type dagSegmentedClosedPage struct {
	Commitment  dagSegmentedState          `json:"commitment"`
	Complete    bool                       `json:"complete"`
	Cut         json.RawMessage            `json:"cut"`
	ClosedPath  []PathItem                 `json:"closed_path"`
	GenesisHash string                     `json:"genesis_hash"`
	Height      int64                      `json:"height"`
	Items       []dagSegmentedOrderWitness `json:"items"`
	Schema      string                     `json:"schema"`
	Start       int                        `json:"start"`
	StateRoot   string                     `json:"state_root"`
}

// Same odd-node duplication/root bagging as dagClosedSegments. Global counts
// remain uint64 here: WASM must not narrow them through architecture-sized int.
func verifyClosedCutPath(cut string, path []PathItem, epoch, count uint64, root string) error {
	if !pubPattern.MatchString(cut) || !pubPattern.MatchString(root) || epoch < 1 || epoch > count || count > dagSegmentCounterMax || path == nil || len(path) > 63 {
		return errDagClosedProof
	}
	value := dagDigest(dagClosedSegmentDomain+"L\x00", cut)
	at := epoch - 1
	used := 0
	for width := count; width > 1; width = (width + 1) / 2 {
		if used >= len(path) {
			return errDagClosedProof
		}
		step := path[used]
		used++
		if !pubPattern.MatchString(step.Hash) {
			return errDagClosedProof
		}
		if at&1 == 1 {
			if step.Side != "left" {
				return errDagClosedProof
			}
			value = closedSegmentJoin(step.Hash, value)
		} else {
			if step.Side != "right" || at+1 == width && step.Hash != value {
				return errDagClosedProof
			}
			value = closedSegmentJoin(value, step.Hash)
		}
		at /= 2
	}
	if used != len(path) || value != root {
		return errDagClosedProof
	}
	return nil
}

func checkedClosedCut(raw json.RawMessage, source dagSegmentedSource, anchor string) (dagHistoryCutBody, string, error) {
	var body dagHistoryCutBody
	if len(raw) == 0 || len(raw) > 256*1024 || decodeStrictLimited(raw, &body, 128, 64) != nil || !bytes.Equal(raw, canonical(body)) ||
		body.Schema != "gg.dag.history-cut.v1" || !pubPattern.MatchString(body.HistoryRoot) || validateSegmentedState(body.Before, source, anchor) != nil || body.Before.Active.Blocks < 1 {
		return body, "", errDagClosedProof
	}
	total := uint64(0)
	for index, account := range body.Accounts {
		balance, err := strconv.ParseUint(account.Balance, 10, 64)
		if err != nil || strconv.FormatUint(balance, 10) != account.Balance || balance > 6*DagAllocation || account.Address != source.Accounts[index] || account.Nonce > DagAllocation {
			return body, "", errDagClosedProof
		}
		total += balance
		for _, author := range body.Before.Authors {
			if author.Key == account.Address && author.Nonce != strconv.FormatUint(account.Nonce, 10) {
				return body, "", errDagClosedProof
			}
		}
	}
	if total != 6*DagAllocation || dagRoot(body.Accounts[:], "GG-DAG-ACCOUNT-v1\x00") != body.Before.Active.AccountRoot {
		return body, "", errDagClosedProof
	}
	return body, dagDigest("GG-DAG-HISTORY-CUT-v1\x00", body), nil
}

func verifySegmentedClosedPage(page dagSegmentedClosedPage, state State, source dagSegmentedSource) error {
	if page.Schema != "gg.dag.segmented-closed-page.v1" || segmentedProofContext(page.Commitment, page.GenesisHash, page.Height, page.StateRoot, state, source) != nil ||
		page.Items == nil || page.Start < 0 || page.Start%DagOrderPageSize != 0 {
		return errDagClosedProof
	}
	cut, hash, err := checkedClosedCut(page.Cut, source, state.GenesisHash)
	if err != nil || cut.Before.Epoch >= page.Commitment.Epoch || cut.Before.Blocks > page.Commitment.Blocks ||
		cut.Before.Transactions > page.Commitment.Transactions || cut.Before.RawBytes > page.Commitment.RawBytes ||
		cut.Before.LastRank > page.Commitment.LastRank || verifyClosedCutPath(hash, page.ClosedPath, cut.Before.Epoch, page.Commitment.Epoch-1, page.Commitment.ClosedRoot) != nil ||
		cut.Before.Epoch+1 == page.Commitment.Epoch && hash != page.Commitment.LastCut {
		return errDagClosedProof
	}
	count := cut.Before.Active.Blocks
	if page.Start >= count || len(page.Items) != min(DagOrderPageSize, count-page.Start) || page.Complete != (page.Start+len(page.Items) == count) {
		return errDagClosedProof
	}
	for index, witness := range page.Items {
		leaf, err := checkedSegmentedLeaf(witness.Leaf, cut.Before, source)
		if err != nil || leaf.Index != page.Start+index+1 || witness.Path == nil ||
			verifyDagPath(leaf, witness.Path, leaf.Index-1, count, cut.Before.Active.OrderRoot, dagOrderDomain) != nil {
			return errDagClosedProof
		}
	}
	return nil
}
