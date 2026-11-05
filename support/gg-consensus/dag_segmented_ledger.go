//go:build !js

package main

import (
	"bytes"
	"context"
	"encoding/hex"
	"errors"
	"strconv"

	abci "github.com/cometbft/cometbft/abci/types"
)

type dagSegmentedNativeApplication struct {
	app     *Ledger
	current *dagSegmentedExecution
	staged  *dagSegmentedExecution
	store   *dagSegmentStore
}

func newDagSegmentedLedger(genesis Genesis, anchor, root string, create bool) (*Ledger, error) {
	if validateGenesis(genesis, anchor) != nil || genesis.DAGSegmented == nil {
		return nil, errDagSegmentStore
	}
	var owned Genesis
	if decodeStrict(canonical(genesis), &owned) != nil {
		return nil, errDagSegmentStore
	}
	store, history, current, err := openDagSegmentStore(owned, anchor, root, create)
	if err != nil {
		return nil, err
	}
	app := &Ledger{genesis: owned, anchor: anchor, history: history, state: copyState(history[len(history)-1])}
	app.segmented = &dagSegmentedNativeApplication{app: app, current: current, store: store}
	return app, nil
}

func (backend *dagSegmentedNativeApplication) Close() error { return backend.store.close() }

func (backend *dagSegmentedNativeApplication) PublicProof(ctx context.Context, state State, path, identifier string, start int) (any, error) {
	return backend.store.publicProof(ctx, state, path, identifier, start)
}

func (backend *dagSegmentedNativeApplication) CutTransaction(ctx context.Context, height int64) (dagSegmentCutTransaction, error) {
	backend.app.mu.RLock()
	defer backend.app.mu.RUnlock()
	if ctx.Err() != nil {
		return dagSegmentCutTransaction{}, ctx.Err()
	}
	if height != backend.app.state.Height || backend.store.health() != nil {
		return dagSegmentCutTransaction{}, errDagSegmentStore
	}
	return backend.current.cutTransaction()
}

func (backend *dagSegmentedNativeApplication) apply(state *State, execution *dagSegmentedExecution, raw []byte, when int64, pending bool) (*dagSegmentedExecution, bool, error) {
	var next *dagSegmentedExecution
	var err error
	if isDagBatch(raw) {
		next, err = execution.apply(raw, when)
	} else if bytes.HasPrefix(raw, []byte("{\"before\":")) {
		var plan dagHistoryCutPlan
		plan, err = execution.checkedCutTransaction(raw)
		if err == nil {
			next = plan.next
		}
	} else {
		envelope, err := parseEnvelope(raw, backend.app.genesis, backend.app.anchor)
		if err == nil {
			err = applyEnvelope(state, envelope, pending)
		}
		return execution, false, err
	}
	if err != nil {
		return execution, true, err
	}
	value, err := next.state()
	if err != nil {
		return execution, true, err
	}
	state.DAGSegmented = &value
	return next, true, nil
}

func (backend *dagSegmentedNativeApplication) prepare(ctx context.Context, execution *dagSegmentedExecution) error {
	if execution.closed.count == backend.current.closed.count+1 {
		return backend.store.stageCut(ctx, backend.current)
	}
	return backend.store.stage(ctx, execution)
}

func (backend *dagSegmentedNativeApplication) CheckTx(ctx context.Context, request *abci.RequestCheckTx) (*abci.ResponseCheckTx, error) {
	backend.app.mu.RLock()
	defer backend.app.mu.RUnlock()
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	if backend.store.health() != nil {
		return nil, errDagSegmentStore
	}
	state := copyState(backend.app.state)
	_, _, err := backend.apply(&state, backend.current, request.Tx, 0, true)
	if err != nil {
		return &abci.ResponseCheckTx{Code: 1, Log: err.Error(), Codespace: "gg"}, nil
	}
	return &abci.ResponseCheckTx{Code: 0, GasWanted: 1}, nil
}

func (backend *dagSegmentedNativeApplication) PrepareProposal(ctx context.Context, request *abci.RequestPrepareProposal) (*abci.ResponsePrepareProposal, error) {
	backend.app.mu.RLock()
	defer backend.app.mu.RUnlock()
	state := copyState(backend.app.state)
	execution := backend.current
	dagSeen, nativeSeen := false, false
	accepted := [][]byte{}
	size, limit := int64(0), min(request.MaxTxBytes, int64(64*1024*1024))
	for _, raw := range request.Txs {
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		if len(accepted) >= MaxBlockTxs || size+int64(len(raw))+8 > limit {
			break
		}
		isDAG := isDagBatch(raw) || bytes.HasPrefix(raw, []byte("{\"before\":"))
		if isDAG && (dagSeen || nativeSeen) || !isDAG && dagSeen {
			continue
		}
		next, dag, err := backend.apply(&state, execution, raw, request.Time.UnixNano(), false)
		if err != nil {
			continue
		}
		execution = next
		dagSeen = dagSeen || dag
		nativeSeen = nativeSeen || !dag
		accepted = append(accepted, raw)
		size += int64(len(raw)) + 8
	}
	if err := backend.prepare(ctx, execution); err != nil {
		if errors.Is(err, errDagCandidateCredit) && backend.prepare(ctx, backend.current) == nil {
			return &abci.ResponsePrepareProposal{Txs: [][]byte{}}, nil
		}
		return nil, err
	}
	return &abci.ResponsePrepareProposal{Txs: accepted}, nil
}

func (backend *dagSegmentedNativeApplication) ProcessProposal(ctx context.Context, request *abci.RequestProcessProposal) (*abci.ResponseProcessProposal, error) {
	backend.app.mu.RLock()
	defer backend.app.mu.RUnlock()
	state := copyState(backend.app.state)
	execution := backend.current
	dagSeen, nativeSeen, size := false, false, 0
	if len(request.Txs) > MaxBlockTxs {
		return &abci.ResponseProcessProposal{Status: abci.ResponseProcessProposal_REJECT}, nil
	}
	for _, raw := range request.Txs {
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		size += len(raw) + 8
		isDAG := isDagBatch(raw) || bytes.HasPrefix(raw, []byte("{\"before\":"))
		if size > 64*1024*1024 || isDAG && (dagSeen || nativeSeen) || !isDAG && dagSeen {
			return &abci.ResponseProcessProposal{Status: abci.ResponseProcessProposal_REJECT}, nil
		}
		next, dag, err := backend.apply(&state, execution, raw, request.Time.UnixNano(), false)
		if err != nil {
			return &abci.ResponseProcessProposal{Status: abci.ResponseProcessProposal_REJECT}, nil
		}
		execution = next
		dagSeen = dagSeen || dag
		nativeSeen = nativeSeen || !dag
	}
	if err := backend.prepare(ctx, execution); err != nil {
		return nil, err
	}
	return &abci.ResponseProcessProposal{Status: abci.ResponseProcessProposal_ACCEPT}, nil
}

func (backend *dagSegmentedNativeApplication) FinalizeBlock(ctx context.Context, request *abci.RequestFinalizeBlock) (*abci.ResponseFinalizeBlock, error) {
	backend.app.mu.Lock()
	defer backend.app.mu.Unlock()
	backend.staged, backend.app.staged = nil, nil
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	if request.Height != backend.app.state.Height+1 || len(request.Txs) > MaxBlockTxs {
		return nil, errors.New("GG_FINALIZE_HEIGHT")
	}
	state := copyState(backend.app.state)
	execution := backend.current
	dagSeen, nativeSeen, size := false, false, 0
	results := make([]*abci.ExecTxResult, len(request.Txs))
	for index, raw := range request.Txs {
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		size += len(raw) + 8
		isDAG := isDagBatch(raw) || bytes.HasPrefix(raw, []byte("{\"before\":"))
		if size > 64*1024*1024 || isDAG && (dagSeen || nativeSeen) || !isDAG && dagSeen {
			return nil, errors.New("GG_FINALIZE_DAG_LIMIT")
		}
		next, dag, err := backend.apply(&state, execution, raw, request.Time.UnixNano(), false)
		if err != nil {
			return nil, errors.New("GG_FINALIZE_INVALID_TX")
		}
		execution = next
		dagSeen = dagSeen || dag
		nativeSeen = nativeSeen || !dag
		kind := "gg.transfer"
		if dag {
			kind = "gg.dag_checkpoint"
			if execution.closed.count != backend.current.closed.count {
				kind = "gg.dag_segment_cut"
			}
		}
		results[index] = &abci.ExecTxResult{Code: 0, GasWanted: 1, GasUsed: 1, Events: []abci.Event{{Type: kind, Attributes: []abci.EventAttribute{
			{Key: "epoch", Value: strconv.FormatUint(execution.closed.count+1, 10), Index: false}}}}}
	}
	if err := backend.prepare(ctx, execution); err != nil {
		return nil, err
	}
	state.Height = request.Height
	sealState(&state)
	if validateState(state, backend.app.genesis, backend.app.anchor) != nil {
		return nil, errDagSegmentStore
	}
	backend.staged, backend.app.staged = execution, &state
	hash, _ := hex.DecodeString(state.StateRoot)
	return &abci.ResponseFinalizeBlock{TxResults: results, AppHash: hash}, nil
}

func (backend *dagSegmentedNativeApplication) Commit(ctx context.Context, _ *abci.RequestCommit) (*abci.ResponseCommit, error) {
	backend.app.mu.Lock()
	defer backend.app.mu.Unlock()
	if backend.staged == nil || backend.app.staged == nil {
		return nil, errors.New("GG_COMMIT_WITHOUT_FINALIZE")
	}
	history := append(append([]State(nil), backend.app.history...), copyState(*backend.app.staged))
	if len(history) > HistoryLimit {
		history = history[len(history)-HistoryLimit:]
	}
	if err := backend.store.commitHistory(ctx, history, backend.staged); err != nil {
		return nil, err
	}
	backend.current = backend.store.view(backend.staged)
	backend.app.history, backend.app.state = history, copyState(*backend.app.staged)
	backend.staged, backend.app.staged = nil, nil
	return &abci.ResponseCommit{}, nil
}

var _ dagSegmentedApplication = (*dagSegmentedNativeApplication)(nil)
