//go:build !js

package main

import (
	"bytes"
	"context"
	"encoding/hex"
	"errors"
	abci "github.com/cometbft/cometbft/abci/types"
	"sort"
	"strconv"
)

// This explicit genesis mode orders ALL money through financial DAG blocks.
// Legacy transfer and nonfinancial DAG modes are selected by their old genesis.
type financialNativeApplication struct {
	app             *Ledger
	current, staged *financialDagExecution
	store           *financialStore
	stagedRaw       []byte
	stagedTime      int64
	candidate       financialTransitionCache
}

func newFinancialLedger(genesis Genesis, anchor, root string, create bool) (*Ledger, error) {
	return newFinancialLedgerContext(context.Background(), genesis, anchor, root, create)
}
func newFinancialLedgerContext(ctx context.Context, genesis Genesis, anchor, root string, create bool) (*Ledger, error) {
	store, history, execution, err := openFinancialStore(ctx, genesis, anchor, root, create)
	if err != nil {
		return nil, err
	}
	app := &Ledger{genesis: execution.genesis, anchor: anchor, history: history, state: copyState(history[len(history)-1])}
	app.financial = &financialNativeApplication{app: app, current: execution, store: store}
	return app, nil
}

func (backend *financialNativeApplication) Close() error {
	backend.candidate.clear()
	return backend.store.close()
}

func (backend *financialNativeApplication) Receipt(ctx context.Context, state State, selector financialReceiptSelector) (financialCertifiedReceipt, error) {
	return backend.store.receipt(ctx, state, backend.app.genesis, selector)
}
func (backend *financialNativeApplication) Account(ctx context.Context, state State, address string) (financialCertifiedAccount, error) {
	return backend.store.accountProof(ctx, state, backend.app.genesis, address)
}

func (backend *financialNativeApplication) Registry(ctx context.Context, state State, selector protocolRegistrySelector) (financialCertifiedRegistry, error) {
	return backend.store.registryProof(ctx, state, backend.app.genesis, selector)
}

func (backend *financialNativeApplication) Block(ctx context.Context, state State, block string) (financialCertifiedBlock, error) {
	return backend.store.blockProof(ctx, state, backend.app.genesis, block)
}

func (backend *financialNativeApplication) RecentBlocks(ctx context.Context, state State, selector financialRecentSelector) (financialRecentBlocks, error) {
	return backend.store.recentBlocks(ctx, state, backend.app.genesis, selector)
}

func (backend *financialNativeApplication) Reward(ctx context.Context, state State, selector protocolRewardSelector) (financialCertifiedReward, error) {
	return backend.store.rewardProof(ctx, state, backend.app.genesis, selector)
}

func (backend *financialNativeApplication) CommitteeState(ctx context.Context, epoch uint64) (State, error) {
	return backend.store.committeeState(ctx, backend.app.genesis, epoch)
}

func (backend *financialNativeApplication) OriginalCore(ctx context.Context, selector financialOriginalCoreSelector) (financialOriginalCoreChunk, error) {
	return backend.store.originalCoreChunk(ctx, backend.app.genesis, selector)
}

func (backend *financialNativeApplication) ProducerContext(ctx context.Context, state State, producer int) (financialProducerContext, error) {
	backend.app.mu.RLock()
	defer backend.app.mu.RUnlock()
	if backend.store.health() != nil {
		return financialProducerContext{}, errFinancialStore
	}
	return makeFinancialProducerContext(ctx, state, backend.app.genesis, producer, backend.store.producerViews)
}

// A zero height requests the current cut. Bind its bytes and response height
// under one lock; a prior Query snapshot may already have been superseded.
// Explicit historical heights remain pinned and cannot authorize a new cut.
func (backend *financialNativeApplication) CutTransaction(ctx context.Context, height int64) ([]byte, int64, error) {
	backend.app.mu.RLock()
	defer backend.app.mu.RUnlock()
	currentHeight := backend.app.state.Height
	if ctx.Err() != nil {
		return nil, currentHeight, ctx.Err()
	}
	if height != 0 && height != currentHeight || backend.store.health() != nil {
		return nil, currentHeight, errFinancialStore
	}
	raw, err := backend.current.prepareCut()
	return raw, currentHeight, err
}

func financialTransition(ctx context.Context, execution *financialDagExecution, raw []byte, when int64) (*financialDagExecution, error) {
	if isDagBatch(raw) {
		return execution.applyBatch(ctx, raw, when)
	}
	if bytes.HasPrefix(raw, []byte("{\"before\":")) {
		cutTime := when
		if when == 0 {
			cutTime = execution.timeNs
		}
		next, err := execution.applyCut(ctx, raw, cutTime)
		if err == nil && when == 0 {
			next.provisional = true
		}
		return next, err
	}
	return nil, errors.New("GG_FINANCIAL_DAG_ONLY")
}

func (backend *financialNativeApplication) CheckTx(ctx context.Context, request *abci.RequestCheckTx) (*abci.ResponseCheckTx, error) {
	backend.app.mu.RLock()
	defer backend.app.mu.RUnlock()
	if err := backend.store.health(); err != nil {
		backend.candidate.clear()
		return nil, err
	}
	raw := request.Tx
	if backend.current.source.hasProtocol() && isDagBatch(raw) {
		var err error
		raw, err = rebaseFinancialProtocolPackage(backend.current, raw)
		if err != nil {
			backend.candidate.clear()
			return &abci.ResponseCheckTx{Code: 1, Log: err.Error(), Codespace: "gg"}, nil
		}
	}
	_, err := financialTransition(ctx, backend.current, raw, 0)
	if ctx.Err() != nil {
		backend.candidate.clear()
		return nil, ctx.Err()
	}
	if err != nil {
		backend.candidate.clear()
		return &abci.ResponseCheckTx{Code: 1, Log: err.Error(), Codespace: "gg"}, nil
	}
	return &abci.ResponseCheckTx{GasWanted: 1}, nil
}

func (backend *financialNativeApplication) PrepareProposal(ctx context.Context, request *abci.RequestPrepareProposal) (*abci.ResponsePrepareProposal, error) {
	backend.app.mu.RLock()
	defer backend.app.mu.RUnlock()
	succeeded := false
	defer func() {
		if !succeeded {
			backend.candidate.clear()
		}
	}()
	if err := backend.store.health(); err != nil {
		return nil, err
	}
	accepted := [][]byte{}
	if request.Time.UnixNano() < backend.store.timeNs || request.Time.UnixNano() > int64(dagSegmentCounterMax)-5000000000 {
		return &abci.ResponsePrepareProposal{Txs: accepted}, nil
	}
	base, err := advanceFinancialExecution(ctx, backend.current, backend.app.state, request.Time.UnixNano())
	if err != nil {
		return nil, err
	}
	raw, next, err := selectFinancialProposalCandidate(ctx, base, request.Txs, request.Time.UnixNano(), request.MaxTxBytes)
	if err != nil {
		return nil, err
	}
	if len(raw) > 0 {
		if err := backend.store.stage(ctx, raw); err != nil {
			if errors.Is(err, errDagCandidateCredit) {
				return &abci.ResponsePrepareProposal{Txs: accepted}, nil
			}
			return nil, err
		}
		if key, ok := financialCandidateIdentity(backend.current, backend.app.state, raw, request.Time.UnixNano()); ok {
			backend.candidate.retain(ctx, key, raw, next)
		} else {
			backend.candidate.clear()
		}
		accepted = append(accepted, raw)
	} else {
		backend.candidate.clear()
	}
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	succeeded = true
	return &abci.ResponsePrepareProposal{Txs: accepted}, nil
}

func (backend *financialNativeApplication) ProcessProposal(ctx context.Context, request *abci.RequestProcessProposal) (*abci.ResponseProcessProposal, error) {
	backend.app.mu.RLock()
	defer backend.app.mu.RUnlock()
	succeeded := false
	defer func() {
		if !succeeded {
			backend.candidate.clear()
		}
	}()
	if err := backend.store.health(); err != nil {
		return nil, err
	}
	reject := &abci.ResponseProcessProposal{Status: abci.ResponseProcessProposal_REJECT}
	if len(request.Txs) > 1 || request.Time.UnixNano() < backend.store.timeNs || request.Time.UnixNano() > int64(dagSegmentCounterMax)-5000000000 {
		return reject, nil
	}
	base, err := advanceFinancialExecution(ctx, backend.current, backend.app.state, request.Time.UnixNano())
	if err != nil {
		return reject, nil
	}
	if len(request.Txs) == 1 {
		// No caller-owned byte slice may remain behind an accepted cache key.
		raw := append([]byte(nil), request.Txs[0]...)
		key, eligible := financialCandidateIdentity(backend.current, backend.app.state, raw, request.Time.UnixNano())
		hit := eligible && backend.candidate.matches(key, raw)
		var next *financialDagExecution
		if !hit {
			var err error
			next, err = financialTransition(ctx, base, raw, request.Time.UnixNano())
			if err != nil {
				if ctx.Err() != nil {
					return nil, ctx.Err()
				}
				return reject, nil
			}
		}
		if err := backend.store.stage(ctx, raw); err != nil {
			return nil, err
		}
		if !hit {
			if eligible {
				backend.candidate.retain(ctx, key, raw, next)
			} else {
				backend.candidate.clear()
			}
		}
	} else {
		backend.candidate.clear()
	}
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	succeeded = true
	return &abci.ResponseProcessProposal{Status: abci.ResponseProcessProposal_ACCEPT}, nil
}

func (backend *financialNativeApplication) FinalizeBlock(ctx context.Context, request *abci.RequestFinalizeBlock) (*abci.ResponseFinalizeBlock, error) {
	backend.app.mu.Lock()
	defer backend.app.mu.Unlock()
	defer backend.candidate.clear()
	backend.staged, backend.app.staged, backend.stagedRaw = nil, nil, nil
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	if backend.store.health() != nil || backend.app.state.Height == int64(dagSegmentCounterMax) || request.Height != backend.app.state.Height+1 || len(request.Txs) > 1 {
		return nil, errors.New("GG_FINANCIAL_FINALIZE_CONTEXT")
	}
	when := request.Time.UnixNano()
	if when < backend.store.timeNs || when > int64(dagSegmentCounterMax)-5000000000 {
		return nil, errors.New("GG_FINANCIAL_FINALIZE_TIME")
	}
	execution, err := advanceFinancialExecution(ctx, backend.current, backend.app.state, when)
	if err != nil {
		return nil, err
	}
	var raw []byte
	results := make([]*abci.ExecTxResult, 0, len(request.Txs))
	if len(request.Txs) == 1 {
		raw = append([]byte(nil), request.Txs[0]...)
		var next *financialDagExecution
		if key, ok := financialCandidateIdentity(backend.current, backend.app.state, raw, when); ok {
			next = backend.candidate.take(key, raw)
		}
		if next == nil {
			var err error
			next, err = financialTransition(ctx, execution, raw, when)
			if err != nil {
				return nil, err
			}
		}
		if err := backend.store.stage(ctx, raw); err != nil {
			return nil, err
		}
		execution = next
		kind := "gg.financial_dag_checkpoint"
		if next.epoch != backend.current.epoch {
			kind = "gg.financial_dag_cut"
		}
		results = append(results, &abci.ExecTxResult{GasWanted: 1, GasUsed: 1, Events: []abci.Event{{Type: kind, Attributes: []abci.EventAttribute{
			{Key: "applied", Value: strconv.FormatUint(next.applied-backend.current.applied, 10)},
			{Key: "rejected", Value: strconv.FormatUint(next.rejected-backend.current.rejected, 10)},
		}}}})
	}
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	state, err := financialNativeState(backend.app.state, execution, request.Height)
	if err != nil {
		return nil, err
	}
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	backend.staged, backend.app.staged, backend.stagedRaw, backend.stagedTime = execution, &state, append([]byte(nil), raw...), when
	hash, _ := hex.DecodeString(state.StateRoot)
	updates, err := financialProtocolValidatorUpdates(execution, request.Height)
	if err != nil {
		backend.staged, backend.app.staged, backend.stagedRaw = nil, nil, nil
		return nil, err
	}
	if err := recoveryWork(ctx, uint64(len(raw)+1), &request.Height); err != nil {
		return nil, err
	}
	return &abci.ResponseFinalizeBlock{AppHash: hash, TxResults: results, ValidatorUpdates: updates}, nil
}

func financialProtocolValidatorUpdates(execution *financialDagExecution, height int64) ([]abci.ValidatorUpdate, error) {
	if !execution.source.hasProtocol() {
		return nil, nil
	}
	return financialProtocolStateValidatorUpdates(execution.money.Protocol.state, height)
}

func financialProtocolStateValidatorUpdates(state financialProtocolCommitment, height int64) ([]abci.ValidatorUpdate, error) {
	pending := state.PendingCommittee
	if pending == nil || pending.DecidedHeight != uint64(height) {
		return nil, nil
	}
	old := map[string]uint64{}
	for _, member := range state.Committee.Members {
		power, _ := economicAmount(member.Power)
		old[member.ValidatorKey] = power
	}
	updates := []abci.ValidatorUpdate{}
	for _, member := range pending.Next.Members {
		power, _ := economicAmount(member.Power)
		if prior, exists := old[member.ValidatorKey]; !exists || prior != power {
			key, _ := hex.DecodeString(member.ValidatorKey)
			updates = append(updates, abci.Ed25519ValidatorUpdate(key, int64(power)))
		}
		delete(old, member.ValidatorKey)
	}
	keys := make([]string, 0, len(old))
	for key := range old {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	for _, encoded := range keys {
		key, _ := hex.DecodeString(encoded)
		updates = append(updates, abci.Ed25519ValidatorUpdate(key, 0))
	}
	return updates, nil
}

func (backend *financialNativeApplication) Commit(ctx context.Context, _ *abci.RequestCommit) (*abci.ResponseCommit, error) {
	backend.app.mu.Lock()
	defer backend.app.mu.Unlock()
	defer backend.candidate.clear()
	if backend.staged == nil || backend.app.staged == nil {
		return nil, errors.New("GG_COMMIT_WITHOUT_FINALIZE")
	}
	if err := backend.store.commit(ctx, *backend.app.staged, backend.staged, backend.stagedRaw, backend.stagedTime); err != nil {
		return nil, err
	}
	backend.current = backend.staged.clone() // drop transient decoded payment/receipt batches
	backend.app.state = copyState(*backend.app.staged)
	backend.app.history = append(backend.app.history, copyState(backend.app.state))
	if len(backend.app.history) > HistoryLimit {
		backend.app.history = append([]State(nil), backend.app.history[len(backend.app.history)-HistoryLimit:]...)
	}
	backend.staged, backend.app.staged, backend.stagedRaw = nil, nil, nil
	return &abci.ResponseCommit{}, nil
}

var _ financialApplication = (*financialNativeApplication)(nil)
