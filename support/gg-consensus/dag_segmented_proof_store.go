//go:build !js

package main

// Four immutable, distinct selected DAG views, at most4095 metadata leaves per
// view. No raw payload, DB lease, old execution graph or unverified snapshot is
// retained. Queries only hash this captured data, outside consensus/store locks.
import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
)

const dagSegmentProofViews = 4

var errDagSegmentProofUnavailable = errors.New("GG_DAG_SEGMENTED_PROOF_NOT_RETAINED")

type dagSegmentProofView struct {
	accounts [6]Account
	order    []DagOrderLeaf
	payloads []dagSegmentPayload
	source   dagSegmentedSource
	state    dagSegmentedState
	cut      json.RawMessage
	previous []string
}

func segmentProofView(execution *dagSegmentedExecution) (dagSegmentProofView, error) {
	state, err := execution.state()
	if err != nil || len(execution.active.Accounts) != 6 {
		return dagSegmentProofView{}, errDagSegmentProof
	}
	order, err := execution.active.orderList()
	if err != nil || len(order) != state.Active.Blocks || dagRoot(order, dagOrderDomain) != state.Active.OrderRoot ||
		dagRoot(execution.active.Accounts, "GG-DAG-ACCOUNT-v1\x00") != state.Active.AccountRoot {
		return dagSegmentProofView{}, errDagSegmentProof
	}
	view := dagSegmentProofView{order: order, source: execution.source, state: state}
	// Compact immutable descriptors only; originals remain in the durable
	// store. A query cannot promote proposal-ready bytes to selected history.
	for _, leaf := range order {
		record, ok, err := execution.active.historyRecord(leaf.Hash)
		if err != nil || !ok || record.Hash != leaf.Hash || record.Index != leaf.Index ||
			!pubPattern.MatchString(record.WireHash) || record.WireBytes < 1 || record.WireBytes > DagMaxWire {
			return dagSegmentProofView{}, errDagSegmentProof
		}
		view.payloads = append(view.payloads, dagSegmentPayload{Hash: record.Hash, WireHash: record.WireHash, Size: record.WireBytes})
	}
	copy(view.accounts[:], execution.active.Accounts)
	view.cut, view.previous = json.RawMessage("null"), []string{}
	if execution.baseCut != nil {
		view.cut = canonical(*execution.baseCut)
		view.previous = append(view.previous, execution.baseBeforeClosed[:]...)
	}
	base, err := derivedSegmentedBase(state, execution.source, view.cut, view.previous)
	if err != nil || execution.startBase == nil {
		return dagSegmentProofView{}, errDagSegmentedBaseProof
	}
	expected, err := execution.startBase.state()
	if err != nil || base.Commitment != expected || !bytes.Equal(canonical(base.Accounts), canonical(execution.startBase.active.Accounts)) {
		return dagSegmentProofView{}, errDagSegmentedBaseProof
	}
	return view, nil
}

func (store *dagSegmentStore) retainProofView(view dagSegmentProofView) {
	for _, previous := range store.proofViews {
		if previous.state == view.state {
			return
		}
	}
	store.proofViews = append(store.proofViews, view)
	if len(store.proofViews) > dagSegmentProofViews {
		copy(store.proofViews, store.proofViews[1:])
		store.proofViews[len(store.proofViews)-1] = dagSegmentProofView{}
		store.proofViews = store.proofViews[:dagSegmentProofViews]
	}
}

func (store *dagSegmentStore) retainReplayProof(execution *dagSegmentedExecution) error {
	view, err := segmentProofView(execution)
	if err != nil {
		return err
	}
	store.retainProofView(view)
	return nil
}

func (store *dagSegmentStore) publicProof(ctx context.Context, state State, path, identifier string, start int) (any, error) {
	if path == "/gg/dag/closed-page" {
		var selector dagClosedSelector
		if len(identifier) > 128 || decodeStrict([]byte(identifier), &selector) != nil || !bytes.Equal([]byte(identifier), canonical(selector)) {
			return nil, errDagClosedProof
		}
		return store.publicClosedPage(ctx, state, selector)
	}
	if path == "/gg/dag/closed-payload-chunk" {
		var selector dagClosedPayloadSelector
		if len(identifier) > 256 || decodeStrict([]byte(identifier), &selector) != nil || !bytes.Equal([]byte(identifier), canonical(selector)) {
			return nil, errDagClosedProof
		}
		return store.publicClosedPayload(ctx, state, selector)
	}
	if path == "/gg/dag/payload-chunk" {
		var selector DagPayloadSelector
		if len(identifier) > 192 || decodeStrict([]byte(identifier), &selector) != nil || !bytes.Equal([]byte(identifier), canonical(selector)) {
			return nil, errors.New("GG_DAG_PAYLOAD_SELECTOR")
		}
		return store.publicPayload(ctx, state, selector)
	}
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	select {
	case store.proofSlots <- struct{}{}:
		defer func() { <-store.proofSlots }()
	default:
		return nil, errors.New("GG_DAG_PROOF_BUSY")
	}
	store.mu.Lock()
	if store.db == nil || store.failed || state.DAGSegmented == nil {
		store.mu.Unlock()
		return nil, errDagSegmentProofUnavailable
	}
	var captured *dagSegmentProofView
	for index := range store.proofViews {
		if store.proofViews[index].state == *state.DAGSegmented {
			value := store.proofViews[index]
			captured = &value
			break
		}
	}
	store.mu.Unlock()
	if captured == nil {
		return nil, errDagSegmentProofUnavailable
	}
	if store.beforeProofRead != nil {
		store.beforeProofRead()
	}
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	view := *captured
	switch path {
	case "/gg/dag/base-proof":
		return dagSegmentedBaseProof{Commitment: view.state, Cut: append(json.RawMessage(nil), view.cut...),
			GenesisHash: state.GenesisHash, Height: state.Height, PreviousClosed: append([]string{}, view.previous...),
			Schema: "gg.dag.segmented-base-proof.v1", StateRoot: state.StateRoot}, nil
	case "/gg/dag/account-proof":
		for index, account := range view.accounts {
			if account.Address != identifier {
				continue
			}
			witness, err := dagPath(view.accounts[:], index, "GG-DAG-ACCOUNT-v1\x00")
			if err != nil {
				return nil, err
			}
			return dagSegmentedAccountProof{Commitment: view.state, GenesisHash: state.GenesisHash, Height: state.Height, Index: index,
				Leaf: account, Path: witness, Schema: "gg.dag.segmented-account-proof.v1", StateRoot: state.StateRoot}, nil
		}
		return nil, errors.New("GG_DAG_UNKNOWN_ACCOUNT")
	case "/gg/dag/block-proof":
		for index, leaf := range view.order {
			if leaf.Hash != identifier {
				continue
			}
			witness, err := dagPath(view.order, index, dagOrderDomain)
			if err != nil {
				return nil, err
			}
			public, err := segmentedPublicLeaf(leaf, view.state, view.source)
			if err != nil {
				return nil, err
			}
			return dagSegmentedBlockProof{Commitment: view.state, GenesisHash: state.GenesisHash, Height: state.Height,
				Leaf: public, Path: witness, Schema: "gg.dag.segmented-block-proof.v1", StateRoot: state.StateRoot}, nil
		}
		return nil, errors.New("GG_DAG_UNKNOWN_BLOCK")
	case "/gg/dag/order-page":
		if start < 0 || start > len(view.order) || start%DagOrderPageSize != 0 || start == len(view.order) && start != 0 {
			return nil, errDagSegmentProof
		}
		end := min(start+DagOrderPageSize, len(view.order))
		page := dagSegmentedOrderPage{Commitment: view.state, Complete: end == len(view.order), GenesisHash: state.GenesisHash, Height: state.Height,
			Items: []dagSegmentedOrderWitness{}, Schema: "gg.dag.segmented-order-page.v1", Start: start, StateRoot: state.StateRoot}
		if start < end {
			levels := dagTree(view.order, dagOrderDomain)
			for index := start; index < end; index++ {
				leaf, err := segmentedPublicLeaf(view.order[index], view.state, view.source)
				if err != nil {
					return nil, err
				}
				page.Items = append(page.Items, dagSegmentedOrderWitness{Leaf: leaf, Path: dagPathFromLevels(levels, index)})
			}
		}
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		return page, nil
	default:
		return nil, errDagSegmentProof
	}
}
