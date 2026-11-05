//go:build !js

package main

import (
	"context"
	"encoding/base64"
	"sort"
)

// Selection changes no signature, payment or consensus verification rule.
// PrepareProposal may combine independently admissible packages into one
// canonical batch. Other validators still verify the complete resulting batch.
type financialSelectionBlock struct {
	raw  []byte
	hash string
	rank uint64
}

func financialCutDue(execution *financialDagExecution) bool {
	return execution.activeBlocks > 0 &&
		(execution.activeBlocks > DagMaxRecords-DagMaxBatchBlocks ||
			execution.activeBytes > DagMaxHistoryWire-DagMaxWire)
}

func selectFinancialProposal(ctx context.Context, execution *financialDagExecution, txs [][]byte, when, maxBytes int64) ([]byte, error) {
	raw, _, err := selectFinancialProposalCandidate(ctx, execution, txs, when, maxBytes)
	return raw, err
}

func selectFinancialProposalCandidate(ctx context.Context, execution *financialDagExecution, txs [][]byte, when, maxBytes int64) ([]byte, *financialDagExecution, error) {
	if err := ctx.Err(); err != nil {
		return nil, nil, err
	}
	if maxBytes <= 8 {
		return nil, nil, nil
	}
	maximum := maxBytes - 8
	if maximum > financialDagMaxBatchWire {
		maximum = financialDagMaxBatchWire
	}
	if financialCutDue(execution) {
		cut, err := execution.prepareCut()
		if err != nil {
			return nil, nil, err
		}
		if int64(len(cut)) > maximum {
			return nil, nil, nil
		}
		checked, err := financialTransition(ctx, execution, cut, when)
		if err != nil {
			return nil, nil, err
		}
		return cut, checked, nil
	}
	before, err := execution.commitmentHash()
	if err != nil {
		return nil, nil, err
	}
	batch := financialDagBatch{Blocks: []string{}, GenesisHash: execution.anchor, Previous: before,
		Schema: "gg.financial-dag.batch.v1", Sequence: execution.checkpoint + 1, SourceHash: execution.source.hash()}
	if execution.source.hasProtocol() {
		batch.Schema = "gg.financial-dag.batch.v2"
	}
	encodedBytes := int64(len(canonical(batch)))
	if encodedBytes > maximum {
		return nil, nil, nil
	}
	// Bound the scanned input independently of what eventually fits. No more
	// than one maximum package's encoded bytes and 128 packages are inspected.
	inspected, retained := 0, 0
	rows := make([]financialSelectionBlock, 0, DagMaxBatchBlocks)
	packages := map[string]bool{}
	blocks := map[string]bool{}
	operations := map[string]protocolOperation{}
	var cutFallback []byte
	var cutFallbackCandidate *financialDagExecution
	for index, raw := range txs {
		if err := ctx.Err(); err != nil {
			return nil, nil, err
		}
		if index >= DagMaxBatchBlocks || len(rows) >= DagMaxBatchBlocks {
			break
		}
		if len(raw) == 0 || len(raw) > financialDagMaxBatchWire-inspected {
			continue
		}
		inspected += len(raw)
		id := hashHex(raw)
		if packages[id] {
			continue
		}
		packages[id] = true
		// A malformed account signature rejects its whole submitted package.
		// No remote 'verified' flag or mempool assertion is used here.
		candidateRaw := raw
		if execution.source.hasProtocol() && isDagBatch(raw) {
			candidateRaw, err = rebaseFinancialProtocolPackage(execution, raw)
			if err != nil {
				continue
			}
		}
		checked, err := financialTransition(ctx, execution, candidateRaw, when)
		if err != nil {
			if ctx.Err() != nil {
				return nil, nil, ctx.Err()
			}
			continue
		}
		// The exact canonical single package has already executed completely.
		// Re-admitting its same records would repeat every account-tree update.
		// Oversize packages retain the existing selection/trimming path.
		if len(txs) == 1 && int64(len(candidateRaw)) <= maximum {
			return append([]byte(nil), candidateRaw...), checked, nil
		}
		if !isDagBatch(raw) {
			if int64(len(raw)) <= maximum {
				if len(rows) == 0 {
					return append([]byte(nil), raw...), checked, nil
				}
				if cutFallback == nil {
					cutFallback = append([]byte(nil), raw...)
					cutFallbackCandidate = checked
				}
			}
			continue
		}
		if execution.source.hasProtocol() {
			var submitted financialDagBatch
			if decodeStrictLimited(candidateRaw, &submitted, DagMaxBatchBlocks, 64) != nil {
				return nil, nil, errFinancialProtocol
			}
			for _, operation := range submitted.Operations {
				if len(operations) >= protocolMaxOperations {
					break
				}
				operations[hashHex(canonical(operation))] = operation
			}
		}
		candidate := make([]financialSelectionBlock, 0, len(checked.pending))
		for _, record := range checked.pending {
			leaf, exists, err := checked.history.get("b/" + record.Hash)
			if err != nil || !exists || leaf.Record == nil {
				return nil, nil, errFinancialDag
			}
			candidate = append(candidate, financialSelectionBlock{raw: record.Raw, hash: record.Hash, rank: uint64(leaf.Record.Rank)})
		}
		sort.Slice(candidate, func(i, j int) bool {
			return candidate[i].rank < candidate[j].rank || candidate[i].rank == candidate[j].rank && candidate[i].hash < candidate[j].hash
		})
		for _, row := range candidate {
			if blocks[row.hash] || len(row.raw) > DagMaxWire-retained {
				continue
			}
			if len(rows) >= DagMaxBatchBlocks {
				break
			}
			rows = append(rows, row)
			retained += len(row.raw)
			blocks[row.hash] = true
		}
	}
	sort.Slice(rows, func(i, j int) bool {
		return rows[i].rank < rows[j].rank || rows[i].rank == rows[j].rank && rows[i].hash < rows[j].hash
	})
	next := execution.clone()
	next.previous, next.checkpoint, next.provisional, next.timeNs = before, batch.Sequence, false, when
	operationIDs := make([]string, 0, len(operations))
	for id := range operations {
		operationIDs = append(operationIDs, id)
	}
	sort.Strings(operationIDs)
	for _, id := range operationIDs {
		trial := next.clone()
		if err := trial.applyProtocolOperation(ctx, operations[id]); err != nil {
			if ctx.Err() != nil {
				return nil, nil, ctx.Err()
			}
			continue
		}
		probe := batch
		probe.Operations = append(append([]protocolOperation(nil), batch.Operations...), operations[id])
		cost := int64(len(canonical(probe)))
		if cost > maximum {
			continue
		}
		next, batch, encodedBytes = trial, probe, cost
	}
	decodedBytes := 0
	for _, row := range rows {
		if err := ctx.Err(); err != nil {
			return nil, nil, err
		}
		cost := int64(base64.StdEncoding.EncodedLen(len(row.raw)) + 2)
		if len(batch.Blocks) > 0 {
			cost++
		}
		if cost > maximum-encodedBytes || len(row.raw) > DagMaxWire-decodedBytes {
			continue
		}
		record, err := decodeFinancialDagBlock(ctx, row.raw, next.source, next.anchor, next.epoch, when, next.money.Protocol)
		if err != nil {
			if ctx.Err() != nil {
				return nil, nil, ctx.Err()
			}
			return nil, nil, err // bytes just authenticated above must remain immutable
		}
		trial := next.clone()
		for key, value := range next.pending {
			trial.pending[key] = value
		}
		if err = trial.admit(ctx, record); err != nil {
			if ctx.Err() != nil {
				return nil, nil, ctx.Err()
			}
			// Competing creator sequences, unavailable descendants and active
			// window limits may exclude a block after another block wins.
			continue
		}
		next = trial
		batch.Blocks = append(batch.Blocks, base64.StdEncoding.EncodeToString(row.raw))
		encodedBytes += cost
		decodedBytes += len(row.raw)
	}
	if len(batch.Blocks)+len(batch.Operations) == 0 {
		return cutFallback, cutFallbackCandidate, nil
	}
	if _, err := next.commitment(); err != nil {
		return nil, nil, err
	}
	raw := canonical(batch)
	if int64(len(raw)) != encodedBytes || int64(len(raw)) > maximum {
		return nil, nil, errFinancialDag
	}
	return raw, next, nil
}

// The outer package is unsigned scheduling metadata. Only public-v2 packages
// may be rebased; producer/account/fee/ballot originals stay byte-identical.
// Finalize/Process still demand the proposer's exact resulting commitment.
func rebaseFinancialProtocolPackage(execution *financialDagExecution, raw []byte) ([]byte, error) {
	var batch financialDagBatch
	if !execution.source.hasProtocol() || len(raw) == 0 || len(raw) > financialDagMaxBatchWire || decodeStrictLimited(raw, &batch, DagMaxBatchBlocks, 64) != nil ||
		!streamCanonicalEqual(raw, batch) || batch.Schema != "gg.financial-dag.batch.v2" || batch.GenesisHash != execution.anchor || batch.SourceHash != execution.source.hash() {
		return nil, errFinancialProtocol
	}
	before, err := execution.commitmentHash()
	if err != nil {
		return nil, err
	}
	batch.Previous, batch.Sequence = before, execution.checkpoint+1
	return canonical(batch), nil
}
