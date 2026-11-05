//go:build !js

package main

import (
	"context"
	"encoding/base64"
	"fmt"
	"github.com/syndtr/goleveldb/leveldb"
	"sort"
	"strconv"
	"strings"
)

const financialReceiptArchiveMaxWire = financialMaxTransactions*512 + 8192

type financialReceiptArchive struct {
	Context  financialExecutionContext `json:"context"`
	Creator  financialDagCreator       `json:"creator"`
	Height   int64                     `json:"height"`
	Receipts []financialReceipt        `json:"receipts"`
	Schema   string                    `json:"schema"`
	Summary  financialSummary          `json:"summary"`
}

// Validate a PRESENT immutable row before interpreting selector-relative
// bounds. A missing p/<hash> is optional; a malformed stored row is not.
func (store *financialStore) decodeReceiptArchive(ctx context.Context, raw []byte, block string, genesis Genesis) (financialReceiptArchive, error) {
	var archive financialReceiptArchive
	if len(raw) == 0 || len(raw) > financialReceiptArchiveMaxWire || decodeStrictLimited(raw, &archive, financialMaxTransactions, 64) != nil || !streamCanonicalEqual(raw, archive) ||
		archive.Schema != "gg.financial-dag.receipt-archive.v1" || archive.Context.BlockHash != block || !archive.Context.valid(store.history.anchor) ||
		archive.Context.SourceHash != store.history.source || archive.Height < 1 || archive.Height > store.history.retainedThrough.Load() ||
		archive.Summary.Transactions < 0 || archive.Summary.Transactions > financialMaxTransactions || len(archive.Receipts) != archive.Summary.Transactions {
		return archive, store.history.rejectRecord(ctx, errFinancialReceipt)
	}
	s := archive.Summary
	schema, _ := financialReceiptSchemas(generalFinancialAccounts(genesis))
	if publicFinancialProtocol(genesis) {
		schema = "gg.financial.summary.v3"
	}
	if s.Schema != schema || s.ContextHash != financialContextHash(archive.Context) || s.Applied < 0 || s.Rejected < 0 || s.Applied > s.Transactions || s.Rejected != s.Transactions-s.Applied ||
		!pubPattern.MatchString(s.AccountRootBefore) || !pubPattern.MatchString(s.AccountRootAfter) || !pubPattern.MatchString(s.InputHash) || !pubPattern.MatchString(s.ReceiptsRoot) {
		return archive, store.history.rejectRecord(ctx, errFinancialReceipt)
	}
	if publicFinancialProtocol(genesis) {
		if _, ok := economicAmount(s.Fees); !ok || !validFinancialPublicCreator(archive.Creator, &financialDagCommitment{Blocks: dagSegmentCounterMax, LastRank: dagSegmentCounterMax}) {
			return archive, store.history.rejectRecord(ctx, errFinancialReceipt)
		}
	} else if s.Fees != "" || genesis.FinancialDAG == nil || archive.Creator.Producer < 0 || archive.Creator.Producer >= len(genesis.FinancialDAG.Producers) || archive.Creator.Key != genesis.FinancialDAG.Producers[archive.Creator.Producer] || archive.Creator.Sequence < 1 || archive.Creator.Sequence > dagSegmentCounterMax {
		return archive, store.history.rejectRecord(ctx, errFinancialReceipt)
	}
	return archive, nil
}

func checkedFinancialJournalBatch(raw []byte, archive financialReceiptArchive, genesis Genesis) (financialDagBatch, error) {
	var entry financialJournalEntry
	var batch financialDagBatch
	if len(raw) == 0 || len(raw) > financialJournalMaxWire || decodeStrictLimited(raw, &entry, DagMaxBatchBlocks, 64) != nil || !streamCanonicalEqual(raw, entry) ||
		entry.Schema != "gg.financial-dag.journal-entry.v1" || entry.Height != archive.Height || !pubPattern.MatchString(entry.After) || !pubPattern.MatchString(entry.Previous) {
		return batch, errFinancialStore
	}
	if _, ok := dagDecimalNs(entry.TimeNs); !ok {
		return batch, errFinancialStore
	}
	schema := "gg.financial-dag.batch.v1"
	if publicFinancialProtocol(genesis) {
		schema = "gg.financial-dag.batch.v2"
	}
	if decodeStrictLimited(entry.Transaction, &batch, DagMaxBatchBlocks, 64) != nil || !streamCanonicalEqual(entry.Transaction, batch) || batch.Schema != schema ||
		batch.GenesisHash != archive.Context.Genesis || batch.SourceHash != archive.Context.SourceHash || batch.Sequence != archive.Context.Checkpoint || !pubPattern.MatchString(batch.Previous) || len(batch.Blocks) < 1 || len(batch.Blocks) > DagMaxBatchBlocks {
		return batch, errFinancialStore
	}
	return batch, nil
}

func financialSummaryNodeKey(level int, start uint64) string {
	return fmt.Sprintf("t/%02d/%020d", level, start)
}

func financialBlockOrderKey(index uint64) string { return fmt.Sprintf("bo/%020d", index) }
func validFinancialBlockOrderKey(key string, count uint64) bool {
	if !strings.HasPrefix(key, "bo/") {
		return false
	}
	index, err := strconv.ParseUint(strings.TrimPrefix(key, "bo/"), 10, 64)
	return err == nil && index > 0 && index <= count && key == financialBlockOrderKey(index)
}

func validFinancialSummaryNodeKey(key string, count uint64) bool {
	fields := strings.Split(key, "/")
	if len(fields) != 3 {
		return false
	}
	level, e1 := strconv.Atoi(fields[1])
	start, e2 := strconv.ParseUint(fields[2], 10, 64)
	return e1 == nil && e2 == nil && level >= 0 && level < 63 && start >= 1 && start <= count &&
		(start-1)%(uint64(1)<<level) == 0 && (uint64(1)<<level) <= count-start+1 && key == financialSummaryNodeKey(level, start)
}

func appendFinancialSummary(tree *dagClosedSegments, id string, save func(string, string) error) error {
	value := dagDigest(dagClosedSegmentDomain+"L\x00", id)
	start := tree.count + 1
	if err := save(financialSummaryNodeKey(0, start), value); err != nil {
		return err
	}
	for level := 0; tree.count&(uint64(1)<<level) != 0; level++ {
		if level >= 63 {
			return errFinancialStore
		}
		value = closedSegmentJoin(tree.peaks[level], value)
		start -= uint64(1) << level
		if err := save(financialSummaryNodeKey(level+1, start), value); err != nil {
			return err
		}
	}
	return tree.append(id)
}

// The same deterministic derivation writes atomically at commit and verifies
// every stored receipt row and MMR node again during original signed replay.
func financialReceiptEntries(ctx context.Context, base dagClosedSegments, execution *financialDagExecution, height int64, save func(string, []byte) error) (dagClosedSegments, error) {
	records := make([]financialDagRecord, 0, len(execution.pending))
	for _, record := range execution.pending {
		records = append(records, record)
	}
	sort.Slice(records, func(a, b int) bool { return records[a].Context.OrderIndex < records[b].Context.OrderIndex })
	tree := base
	for _, record := range records {
		if ctx.Err() != nil {
			return tree, ctx.Err()
		}
		if record.Context.OrderIndex != tree.count+1 || len(record.Receipts) != record.Summary.Transactions {
			return tree, errFinancialStore
		}
		archive := financialReceiptArchive{Context: record.Context, Creator: record.Creator, Height: height, Receipts: record.Receipts, Schema: "gg.financial-dag.receipt-archive.v1", Summary: record.Summary}
		raw := canonical(archive)
		if len(raw) > financialReceiptArchiveMaxWire {
			return tree, errFinancialStore
		}
		if err := save("p/"+record.Hash, raw); err != nil {
			return tree, err
		}
		if execution.source.hasProtocol() {
			if err := save(financialBlockOrderKey(record.Context.OrderIndex), []byte(record.Hash)); err != nil {
				return tree, err
			}
		}
		id := financialDagSummaryID(record.Context, record.Creator, record.Summary)
		if err := appendFinancialSummary(&tree, id, func(key, value string) error { return save(key, []byte(value)) }); err != nil {
			return tree, err
		}
	}
	if tree != execution.receipts {
		return tree, errFinancialStore
	}
	return tree, nil
}

func financialMMRPath(ctx context.Context, read func(string) ([]byte, error), id string, index, count uint64) ([]PathItem, error) {
	if index < 1 || index > count || count > dagSegmentCounterMax {
		return nil, errFinancialReceipt
	}
	var subtree func(int, uint64) (string, error)
	subtree = func(level int, start uint64) (string, error) {
		if ctx.Err() != nil {
			return "", ctx.Err()
		}
		if level < 0 || level >= 63 || start < 1 || start > count {
			return "", errFinancialStore
		}
		if uint64(1)<<level <= count-start+1 {
			raw, err := read(financialSummaryNodeKey(level, start))
			if err != nil || !pubPattern.Match(raw) {
				return "", errFinancialStore
			}
			return string(raw), nil
		}
		left, err := subtree(level-1, start)
		if err != nil {
			return "", err
		}
		right := left
		if next := start + (uint64(1) << (level - 1)); next <= count {
			right, err = subtree(level-1, next)
			if err != nil {
				return "", err
			}
		}
		return closedSegmentJoin(left, right), nil
	}
	value := dagDigest(dagClosedSegmentDomain+"L\x00", id)
	path := []PathItem{}
	position := index - 1
	for width, level := count, 0; width > 1; width, level = (width+1)/2, level+1 {
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		sibling := value
		start := (((index - 1) >> level) ^ 1) << level
		start++
		if start <= count {
			var err error
			sibling, err = subtree(level, start)
			if err != nil {
				return nil, err
			}
		}
		side := "right"
		if position&1 != 0 {
			side = "left"
			value = closedSegmentJoin(sibling, value)
		} else {
			value = closedSegmentJoin(value, sibling)
		}
		path = append(path, PathItem{Hash: sibling, Side: side})
		position /= 2
	}
	return path, nil
}

func financialPaymentFromJournal(ctx context.Context, read func(string) ([]byte, error), archive financialReceiptArchive, index int, genesis Genesis) (Envelope, error) {
	raw, err := read(financialHeightKey(archive.Height))
	if err != nil {
		return Envelope{}, err
	}
	batch, err := checkedFinancialJournalBatch(raw, archive, genesis)
	if err != nil {
		return Envelope{}, errFinancialStore
	}
	remaining := DagMaxWire
	for _, encoded := range batch.Blocks {
		if ctx.Err() != nil {
			return Envelope{}, ctx.Err()
		}
		if len(encoded) > (remaining+2)/3*4 {
			return Envelope{}, errFinancialStore
		}
		wire, err := base64.StdEncoding.Strict().DecodeString(encoded)
		if err != nil || len(wire) > remaining {
			return Envelope{}, errFinancialStore
		}
		remaining -= len(wire)
		if !publicFinancialProtocol(genesis) && hashHex(append([]byte(financialDomain+"DAG-BLOCK\x00"), wire...)) != archive.Context.BlockHash {
			continue
		}
		record, err := decodeFinancialDagBlock(ctx, wire, *genesis.FinancialDAG, archive.Context.Genesis, archive.Context.Epoch, 0)
		if publicFinancialProtocol(genesis) && err == nil && record.Hash != archive.Context.BlockHash {
			continue
		}
		if err != nil || index < 0 || index >= len(record.Block.Body.Payments) {
			return Envelope{}, errFinancialStore
		}
		return record.Block.Body.Payments[index], nil
	}
	return Envelope{}, errFinancialStore
}

func (store *financialStore) receipt(ctx context.Context, state State, genesis Genesis, selector financialReceiptSelector) (financialCertifiedReceipt, error) {
	if !pubPattern.MatchString(selector.Block) || selector.Index < 0 || selector.Index >= financialMaxTransactions || state.FinancialDAG == nil || genesis.FinancialDAG == nil {
		return financialCertifiedReceipt{}, errFinancialReceipt
	}
	select {
	case store.receiptSlots <- struct{}{}:
		defer func() { <-store.receiptSlots }()
	default:
		return financialCertifiedReceipt{}, errDagCandidateCredit
	}
	store.mu.Lock()
	if store.db == nil || store.failed || store.history.failed.Load() {
		store.mu.Unlock()
		return financialCertifiedReceipt{}, errFinancialStore
	}
	snapshot, err := store.db.GetSnapshot()
	if err != nil {
		store.mu.Unlock()
		return financialCertifiedReceipt{}, store.history.rejectRecord(ctx, errFinancialStore)
	}
	store.readers.Add(1)
	store.mu.Unlock()
	defer store.readers.Done()
	defer snapshot.Release()
	read := func(key string) ([]byte, error) {
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		return store.history.read(ctx, func(key string) ([]byte, error) { return snapshot.Get([]byte(key), nil) }, key)
	}
	raw, err := read("p/" + selector.Block)
	if err == leveldb.ErrNotFound {
		return financialCertifiedReceipt{}, errFinancialReceipt
	}
	if err != nil {
		return financialCertifiedReceipt{}, err
	}
	archive, err := store.decodeReceiptArchive(ctx, raw, selector.Block, genesis)
	if err != nil {
		return financialCertifiedReceipt{}, err
	}
	// A valid later record queried against an older retained state is a normal
	// selector miss, not corruption of that record or the current store.
	if archive.Height > state.Height {
		return financialCertifiedReceipt{}, errFinancialReceipt
	}
	if archive.Context.OrderIndex > state.FinancialDAG.Blocks || archive.Context.Checkpoint > state.FinancialDAG.Checkpoint || archive.Context.Epoch > state.FinancialDAG.Epoch {
		return financialCertifiedReceipt{}, store.history.rejectRecord(ctx, errFinancialReceipt)
	}
	if selector.Index >= len(archive.Receipts) {
		return financialCertifiedReceipt{}, errFinancialReceipt
	}
	receipt, err := makeFinancialReceiptProof(archive.Receipts, selector.Index)
	if err != nil {
		return financialCertifiedReceipt{}, store.history.rejectRecord(ctx, err)
	}
	id := financialDagSummaryID(archive.Context, archive.Creator, archive.Summary)
	path, err := financialMMRPath(ctx, store.history.requiredDigestRead(ctx, read), id, archive.Context.OrderIndex, state.FinancialDAG.Blocks)
	if err != nil {
		return financialCertifiedReceipt{}, store.history.rejectRecord(ctx, err)
	}
	journalRead := func(key string) ([]byte, error) { return store.history.requiredRead(ctx, read, key) }
	payment, err := financialPaymentFromJournal(ctx, journalRead, archive, selector.Index, genesis)
	if err != nil {
		return financialCertifiedReceipt{}, store.history.rejectRecord(ctx, err)
	}
	proof := financialCertifiedReceipt{Context: archive.Context, Creator: archive.Creator, Height: state.Height, Payment: payment, Receipt: receipt,
		Schema: "gg.financial-dag.receipt-proof.v1", StateRoot: state.StateRoot, Summary: archive.Summary, SummaryPath: path}
	if publicFinancialProtocol(genesis) {
		proof.Schema = "gg.financial-dag.receipt-proof.v2"
	}
	if ctx.Err() != nil {
		return financialCertifiedReceipt{}, ctx.Err()
	}
	if checkFinancialCertifiedReceipt(proof, state, genesis) != nil {
		return financialCertifiedReceipt{}, store.history.rejectRecord(ctx, errFinancialReceipt)
	}
	return proof, nil
}
