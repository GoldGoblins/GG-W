//go:build !js

package main

// An original-derived, atomically selected index, never a trusted state image.
import (
	"bytes"
	"encoding/json"
	"fmt"
	"math/bits"
	"strconv"

	"github.com/syndtr/goleveldb/leveldb"
)

const dagClosedIndexMaxBytes = 2 * 1024 * 1024

type dagClosedPayload struct {
	WireHash string `json:"wire_hash"`
	Size     int    `json:"size"`
	Offset   int64  `json:"offset"`
	TimeNs   string `json:"time_ns"`
}
type dagClosedIndex struct {
	ArchiveHash  string             `json:"archive_sha256"`
	ArchiveBytes int64              `json:"archive_bytes"`
	Cut          json.RawMessage    `json:"cut"`
	Order        []DagOrderLeaf     `json:"order"`
	Payloads     []dagClosedPayload `json:"payloads"`
	Schema       string             `json:"schema"`
}

func closedIndexKey(epoch uint64) string           { return fmt.Sprintf("x/%020d", epoch) }
func closedNodeKey(level int, index uint64) string { return fmt.Sprintf("t/%02d/%020d", level, index) }

func originalDerivedClosedIndex(execution *dagSegmentedExecution, replayed *dagSegmentArchiveReplay, header dagSegmentArchiveHeader, footer dagSegmentArchiveFooter) (*dagClosedIndex, error) {
	if execution == nil || replayed == nil || replayed.plan.matches(execution) != nil {
		return nil, errDagSegmentStore
	}
	// The streaming reader already verified this exact header against its
	// separately verified base. Its cursor deliberately retains no startBase
	// graph, so reconstructing a writer header from that pointer is invalid.
	if header.Cut != replayed.plan.hash || header.Epoch != replayed.plan.body.Before.Epoch || header.Blocks != execution.active.orderCount() || header.RawBytes != execution.active.bytes || header.Manifests != len(execution.manifests) {
		return nil, errDagSegmentStore
	}
	order, err := execution.active.orderList()
	if err != nil {
		return nil, err
	}
	value := &dagClosedIndex{ArchiveHash: replayed.archiveHash, Cut: canonical(replayed.plan.body), Order: order,
		Payloads: make([]dagClosedPayload, len(order)), Schema: "gg.dag.closed-index.v1"}
	positions := make(map[string]int, len(order))
	for index, leaf := range order {
		record, found, err := execution.active.historyRecord(leaf.Hash)
		if err != nil || !found || record.Index != index+1 || !pubPattern.MatchString(record.WireHash) || record.WireBytes < 1 || record.WireBytes > DagMaxWire {
			return nil, errDagSegmentStore
		}
		if _, duplicate := positions[record.WireHash]; duplicate {
			return nil, errDagSegmentStore
		}
		positions[record.WireHash] = index
		value.Payloads[index] = dagClosedPayload{WireHash: record.WireHash, Size: record.WireBytes}
	}
	offset := int64(8 + 5 + len(canonical(header)))
	for _, manifest := range execution.manifests {
		offset += int64(5 + len(canonical(manifest)))
		for _, wire := range manifest.Blocks {
			index, found := positions[wire]
			if !found || value.Payloads[index].Offset != 0 {
				return nil, errDagSegmentStore
			}
			value.Payloads[index].Offset = offset + 5
			value.Payloads[index].TimeNs = manifest.TimeNs
			offset += int64(5 + value.Payloads[index].Size)
		}
	}
	for _, payload := range value.Payloads {
		if payload.Offset == 0 {
			return nil, errDagSegmentStore
		}
	}
	value.ArchiveBytes = offset + int64(5+len(value.Cut)+5+len(canonical(footer)))
	if len(canonical(value)) > dagClosedIndexMaxBytes || value.ArchiveBytes > dagSegmentArchiveMaxBytes {
		return nil, errDagSegmentStore
	}
	return value, nil
}

// Return only the O(log epochs) newly completed nodes for this append. Old
// peaks were already derived by selected execution/full original replay.
func closedIndexEntries(index *dagClosedIndex, prefix dagClosedSegments) (map[string][]byte, error) {
	var cut dagHistoryCutBody
	if index == nil || decodeStrict(index.Cut, &cut) != nil || !bytes.Equal(index.Cut, canonical(cut)) || cut.Before.Epoch != prefix.count+1 || !prefix.valid() {
		return nil, errDagSegmentStore
	}
	hash := dagDigest("GG-DAG-HISTORY-CUT-v1\x00", cut)
	value := dagDigest(dagClosedSegmentDomain+"L\x00", hash)
	entries := map[string][]byte{closedIndexKey(cut.Before.Epoch): canonical(index)}
	for level := 0; level < 63; level++ {
		entries[closedNodeKey(level, prefix.count>>level)] = []byte(value)
		if prefix.count&(uint64(1)<<level) == 0 {
			return entries, nil
		}
		value = closedSegmentJoin(prefix.peaks[level], value)
	}
	return nil, errDagSegmentStore
}

func (store *dagSegmentStore) stageClosedIndex(batch *leveldb.Batch, index *dagClosedIndex, prefix dagClosedSegments) error {
	entries, err := closedIndexEntries(index, prefix)
	if err != nil {
		return err
	}
	for key, raw := range entries {
		found, err := store.db.Has([]byte(key), nil)
		if err != nil || found {
			return errDagSegmentStore
		}
		batch.Put([]byte(key), raw)
	}
	return nil
}

func (store *dagSegmentStore) verifyClosedIndex(index *dagClosedIndex, prefix dagClosedSegments) error {
	entries, err := closedIndexEntries(index, prefix)
	if err != nil {
		return err
	}
	for key, expected := range entries {
		raw, err := store.db.Get([]byte(key), nil)
		if err != nil || !bytes.Equal(raw, expected) {
			return errDagSegmentStore
		}
	}
	return nil
}

func closedIndexNodeCount(count uint64) uint64 { return count*2 - uint64(bits.OnesCount64(count)) }

func checkedClosedIndex(raw []byte, source dagSegmentedSource, anchor string, epoch uint64) (*dagClosedIndex, dagHistoryCutBody, string, error) {
	var index dagClosedIndex
	var empty dagHistoryCutBody
	if len(raw) == 0 || len(raw) > dagClosedIndexMaxBytes || decodeStrictLimited(raw, &index, DagMaxRecords, 64) != nil || !bytes.Equal(raw, canonical(index)) || index.Schema != "gg.dag.closed-index.v1" ||
		!pubPattern.MatchString(index.ArchiveHash) || index.ArchiveBytes < 1 || index.ArchiveBytes > dagSegmentArchiveMaxBytes {
		return nil, empty, "", errDagSegmentStore
	}
	cut, hash, err := checkedClosedCut(index.Cut, source, anchor)
	if err != nil || cut.Before.Epoch != epoch || len(index.Order) != cut.Before.Active.Blocks || len(index.Payloads) != len(index.Order) ||
		dagRoot(index.Order, dagOrderDomain) != cut.Before.Active.OrderRoot {
		return nil, empty, "", errDagSegmentStore
	}
	for position, leaf := range index.Order {
		public, err := segmentedPublicLeaf(leaf, cut.Before, source)
		if err != nil {
			return nil, empty, "", errDagSegmentStore
		}
		if _, err = checkedSegmentedLeaf(public, cut.Before, source); err != nil || leaf.Index != position+1 {
			return nil, empty, "", errDagSegmentStore
		}
		payload := index.Payloads[position]
		when, timeErr := strconv.ParseInt(payload.TimeNs, 10, 64)
		last, lastErr := strconv.ParseInt(cut.Before.Active.TimeNs, 10, 64)
		if !pubPattern.MatchString(payload.WireHash) || payload.Size < 1 || payload.Size > DagMaxWire || payload.Offset < 13 || payload.Offset > index.ArchiveBytes-int64(payload.Size) {
			return nil, empty, "", errDagSegmentStore
		}
		if timeErr != nil || lastErr != nil || when <= 0 || when > int64(dagSegmentCounterMax)-5000000000 || when > last || strconv.FormatInt(when, 10) != payload.TimeNs {
			return nil, empty, "", errDagSegmentStore
		}
	}
	return &index, cut, hash, nil
}

func validClosedNodeKey(key string, count uint64) bool {
	if len(key) != 25 || key[:2] != "t/" || key[4] != '/' {
		return false
	}
	level, err := strconv.Atoi(key[2:4])
	if err != nil || level < 0 || level > 62 {
		return false
	}
	index, err := strconv.ParseUint(key[5:], 10, 64)
	return err == nil && key == closedNodeKey(level, index) && index < (count>>level)
}
