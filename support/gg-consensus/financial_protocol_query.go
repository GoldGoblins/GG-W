//go:build !js

package main

import (
	"context"
	"encoding/base64"
	"fmt"
	"github.com/syndtr/goleveldb/leveldb"
	"sort"
)

func financialCommitteeStateKey(epoch uint64) string { return fmt.Sprintf("vc/%020d", epoch) }

// Discovery is deliberately separate from authentication. The client verifies
// an independent summary proof for every returned hash and requested index.
func (store *financialStore) recentBlocks(ctx context.Context, state State, genesis Genesis, selector financialRecentSelector) (financialRecentBlocks, error) {
	if !publicFinancialProtocol(genesis) || state.FinancialDAG == nil || selector.Start == 0 || selector.Limit < 1 || selector.Limit > 16 || selector.Start > state.FinancialDAG.Blocks {
		return financialRecentBlocks{}, errFinancialProtocol
	}
	read, release, err := store.protocolQueryRead(ctx)
	if err != nil {
		return financialRecentBlocks{}, err
	}
	defer release()
	result := financialRecentBlocks{Blocks: []financialRecentBlock{}, Height: state.Height, Schema: "gg.financial.recent-blocks.v1", StateRoot: state.StateRoot}
	for index := selector.Start; index <= state.FinancialDAG.Blocks && len(result.Blocks) < selector.Limit; index++ {
		raw, err := store.history.requiredRead(ctx, read, financialBlockOrderKey(index))
		if err != nil || !pubPattern.Match(raw) {
			return financialRecentBlocks{}, store.history.rejectRecord(ctx, errFinancialProtocol)
		}
		// This range is committed. Its block reference must resolve to a row
		// with that same order, even though clients still authenticate their
		// independently requested summary proof rather than trusting discovery.
		stored, readErr := store.history.requiredRead(ctx, read, "p/"+string(raw))
		if readErr != nil {
			return financialRecentBlocks{}, readErr
		}
		archive, decodeErr := store.decodeReceiptArchive(ctx, stored, string(raw), genesis)
		if decodeErr != nil {
			return financialRecentBlocks{}, decodeErr
		}
		if archive.Context.OrderIndex != index || archive.Height > state.Height || archive.Context.Checkpoint > state.FinancialDAG.Checkpoint || archive.Context.Epoch > state.FinancialDAG.Epoch {
			return financialRecentBlocks{}, store.history.rejectRecord(ctx, errFinancialProtocol)
		}
		result.Blocks = append(result.Blocks, financialRecentBlock{Block: string(raw), Index: index})
	}
	return result, nil
}

func (store *financialStore) originalCoreChunk(ctx context.Context, genesis Genesis, selector financialOriginalCoreSelector) (financialOriginalCoreChunk, error) {
	if !publicFinancialProtocol(genesis) || !pubPattern.MatchString(selector.Block) || selector.Offset < 0 || selector.Offset >= DagMaxWire || selector.MaxBytes < 1 || selector.MaxBytes > 32768 {
		return financialOriginalCoreChunk{}, errFinancialProtocol
	}
	read, release, err := store.protocolQueryRead(ctx)
	if err != nil {
		return financialOriginalCoreChunk{}, err
	}
	defer release()
	raw, err := read("p/" + selector.Block)
	if err == leveldb.ErrNotFound {
		return financialOriginalCoreChunk{}, errFinancialProtocol
	}
	if err != nil {
		return financialOriginalCoreChunk{}, err
	}
	archive, err := store.decodeReceiptArchive(ctx, raw, selector.Block, genesis)
	if err != nil {
		return financialOriginalCoreChunk{}, err
	}
	raw, err = store.history.requiredRead(ctx, read, financialHeightKey(archive.Height))
	if err != nil {
		return financialOriginalCoreChunk{}, err
	}
	batch, err := checkedFinancialJournalBatch(raw, archive, genesis)
	if err != nil {
		return financialOriginalCoreChunk{}, store.history.rejectRecord(ctx, err)
	}
	remaining := DagMaxWire
	for _, encoded := range batch.Blocks {
		if err = ctx.Err(); err != nil {
			return financialOriginalCoreChunk{}, err
		}
		if len(encoded) > base64.StdEncoding.EncodedLen(remaining) {
			return financialOriginalCoreChunk{}, store.history.rejectRecord(ctx, errFinancialProtocol)
		}
		wire, decodeErr := base64.StdEncoding.Strict().DecodeString(encoded)
		if decodeErr != nil || len(wire) > remaining {
			return financialOriginalCoreChunk{}, store.history.rejectRecord(ctx, errFinancialProtocol)
		}
		remaining -= len(wire)
		record, decodeErr := decodeFinancialProtocolBlock(ctx, wire, *genesis.FinancialDAG, archive.Context.Genesis, archive.Context.Epoch, 0)
		if decodeErr != nil {
			return financialOriginalCoreChunk{}, store.history.rejectRecord(ctx, decodeErr)
		}
		if record.Hash != selector.Block {
			continue
		}
		core := canonical(financialProtocolCore{Body: record.Protocol.Body, Signature: record.Protocol.Signature})
		if selector.Offset >= len(core) {
			return financialOriginalCoreChunk{}, errFinancialProtocol
		}
		end := selector.Offset + selector.MaxBytes
		if end > len(core) {
			end = len(core)
		}
		return financialOriginalCoreChunk{Block: selector.Block, Data: append([]byte(nil), core[selector.Offset:end]...), Offset: selector.Offset,
			Schema: "gg.financial.original-core-chunk.v1", TotalBytes: len(core), WireHash: hashHex(core)}, nil
	}
	return financialOriginalCoreChunk{}, store.history.rejectRecord(ctx, errFinancialProtocol)
}

func (store *financialStore) committeeState(ctx context.Context, genesis Genesis, epoch uint64) (State, error) {
	if !publicFinancialProtocol(genesis) || epoch == 0 || epoch > dagSegmentCounterMax {
		return State{}, errCommittee
	}
	if err := ctx.Err(); err != nil {
		return State{}, err
	}
	read, release, through, err := store.protocolQueryReadView(ctx)
	if err != nil {
		return State{}, err
	}
	defer release()
	var raw []byte
	if epoch <= through {
		raw, err = store.history.requiredRead(ctx, read, financialCommitteeStateKey(epoch))
	} else {
		raw, err = read(financialCommitteeStateKey(epoch))
	}
	if err == leveldb.ErrNotFound {
		return State{}, errCommittee
	}
	if err != nil {
		return State{}, err
	}
	var state State
	if len(raw) > 256*1024 || decodeStrictLimited(raw, &state, 128, 64) != nil || !streamCanonicalEqual(raw, state) ||
		validateState(state, genesis, hashHex(canonical(genesis))) != nil || state.Protocol == nil || state.Protocol.PendingCommittee == nil ||
		state.Protocol.PendingCommittee.Next.Epoch != epoch || state.Protocol.PendingCommittee.DecidedHeight != uint64(state.Height) || epoch > through || state.Height < 1 || state.Height > store.history.retainedThrough.Load() {
		return State{}, store.history.rejectRecord(ctx, errCommittee)
	}
	return state, nil
}

// A reader lease prevents closing the store during a query. Immutable record
// and node keys allow historical-root proofs while commits append new records.
func (store *financialStore) protocolQueryRead(ctx context.Context) (func(string) ([]byte, error), func(), error) {
	read, release, _, err := store.protocolQueryReadView(ctx)
	return read, release, err
}

// The owned head/range and DB snapshot are captured under the SAME commit
// mutex. Readers cannot see a newly synced row before its cached head facts,
// nor mix old rows with a later archive-reference metadata transaction.
func (store *financialStore) protocolQueryReadView(ctx context.Context) (func(string) ([]byte, error), func(), uint64, error) {
	if err := ctx.Err(); err != nil {
		return nil, nil, 0, err
	}
	select {
	case store.receiptSlots <- struct{}{}:
	default:
		return nil, nil, 0, errDagCandidateCredit
	}
	store.mu.Lock()
	if store.db == nil || store.failed || store.history.failed.Load() {
		store.mu.Unlock()
		<-store.receiptSlots
		return nil, nil, 0, errFinancialStore
	}
	snapshot, err := store.db.GetSnapshot()
	if err != nil {
		store.mu.Unlock()
		<-store.receiptSlots
		return nil, nil, 0, store.history.rejectRecord(ctx, errFinancialStore)
	}
	history := store.history
	through := uint64(0)
	if store.head.State.Protocol != nil {
		through = store.head.State.Protocol.Committee.Epoch
		if pending := store.head.State.Protocol.PendingCommittee; pending != nil {
			through = pending.Next.Epoch
		}
	}
	store.readers.Add(1)
	store.mu.Unlock()
	release := func() { snapshot.Release(); store.readers.Done(); <-store.receiptSlots }
	read := func(key string) ([]byte, error) {
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		return history.read(ctx, func(key string) ([]byte, error) { return snapshot.Get([]byte(key), nil) }, key)
	}
	return read, release, through, nil
}

func (store *financialStore) blockProof(ctx context.Context, state State, genesis Genesis, block string) (financialCertifiedBlock, error) {
	if !publicFinancialProtocol(genesis) || state.FinancialDAG == nil || !pubPattern.MatchString(block) {
		return financialCertifiedBlock{}, errFinancialReceipt
	}
	read, release, err := store.protocolQueryRead(ctx)
	if err != nil {
		return financialCertifiedBlock{}, err
	}
	defer release()
	raw, err := read("p/" + block)
	if err == leveldb.ErrNotFound {
		return financialCertifiedBlock{}, errFinancialReceipt
	}
	if err != nil {
		return financialCertifiedBlock{}, err
	}
	archive, err := store.decodeReceiptArchive(ctx, raw, block, genesis)
	if err != nil {
		return financialCertifiedBlock{}, err
	}
	if archive.Height > state.Height {
		return financialCertifiedBlock{}, errFinancialReceipt
	}
	if archive.Context.OrderIndex > state.FinancialDAG.Blocks || archive.Context.Checkpoint > state.FinancialDAG.Checkpoint || archive.Context.Epoch > state.FinancialDAG.Epoch {
		return financialCertifiedBlock{}, store.history.rejectRecord(ctx, errFinancialReceipt)
	}
	id := financialDagSummaryID(archive.Context, archive.Creator, archive.Summary)
	path, err := financialMMRPath(ctx, store.history.requiredDigestRead(ctx, read), id, archive.Context.OrderIndex, state.FinancialDAG.Blocks)
	if err != nil {
		return financialCertifiedBlock{}, store.history.rejectRecord(ctx, err)
	}
	proof := financialCertifiedBlock{Context: archive.Context, Creator: archive.Creator, Height: state.Height, Schema: "gg.financial.block-proof.v1", StateRoot: state.StateRoot, Summary: archive.Summary, SummaryPath: path}
	if err = checkFinancialCertifiedBlock(proof, state, genesis, block); err != nil {
		return financialCertifiedBlock{}, store.history.rejectRecord(ctx, err)
	}
	return proof, nil
}

func (store *financialStore) rewardProof(ctx context.Context, state State, genesis Genesis, selector protocolRewardSelector) (financialCertifiedReward, error) {
	if !publicFinancialProtocol(genesis) || state.Protocol == nil || selector.Index == 0 || selector.Index > state.Protocol.Settlements || !financialAccountAddress(selector.Address) {
		return financialCertifiedReward{}, errFinancialProtocol
	}
	// Release each bounded lease before acquiring the next; no nested slot wait.
	registry, err := store.registryProof(ctx, state, genesis, protocolRegistrySelector{Namespace: "rewards", Key: protocolRewardKey(selector.Index)})
	if err != nil {
		return financialCertifiedReward{}, err
	}
	id, exists, err := checkFinancialCertifiedRegistry(ctx, registry, state, genesis, protocolRegistrySelector{Namespace: "rewards", Key: protocolRewardKey(selector.Index)})
	if err != nil || !exists {
		return financialCertifiedReward{}, store.history.rejectRecord(ctx, errFinancialProtocol)
	}
	read, release, err := store.protocolQueryRead(ctx)
	if err != nil {
		return financialCertifiedReward{}, err
	}
	defer release()
	raw, err := store.history.requiredRead(ctx, read, protocolRewardPrefix+string(id))
	var receipt protocolRewardReceipt
	if err != nil || len(raw) > protocolRewardMaxWire || decodeStrictLimited(raw, &receipt, economicMaxRecipients, 64) != nil || !streamCanonicalEqual(raw, receipt) ||
		!validProtocolRewardReceipt(receipt, genesis, state.GenesisHash) || protocolRewardReceiptID(receipt) != string(id) {
		return financialCertifiedReward{}, store.history.rejectRecord(ctx, errFinancialProtocol)
	}
	index := sort.Search(len(receipt.Credits), func(i int) bool { return receipt.Credits[i].Address >= selector.Address })
	if index == len(receipt.Credits) || receipt.Credits[index].Address != selector.Address {
		return financialCertifiedReward{}, errFinancialProtocol
	}
	path, err := dagPath(receipt.Credits, index, "GG-FINANCIAL-REWARD-CREDITS-v1\x00")
	if err != nil {
		return financialCertifiedReward{}, store.history.rejectRecord(ctx, err)
	}
	proof := financialCertifiedReward{Credit: receipt.Credits[index], CreditIndex: index, CreditPath: path, Receipt: receipt, Registry: registry, Schema: "gg.financial.reward-proof.v1"}
	proof.Receipt.Credits = nil
	if err = checkFinancialCertifiedReward(ctx, proof, state, genesis, selector); err != nil {
		return financialCertifiedReward{}, store.history.rejectRecord(ctx, err)
	}
	return proof, nil
}
