//go:build !js

package main

// Local storage only. These records do not alter consensus bytes, certify a
// snapshot, delete originals, or recover a validator's private signing state.
// Every cold open still independently executes every selected original.
import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"errors"
	"fmt"
	"hash"
	"io"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync/atomic"

	"github.com/syndtr/goleveldb/leveldb"
	"github.com/syndtr/goleveldb/leveldb/iterator"
	"github.com/syndtr/goleveldb/leveldb/opt"
	"github.com/syndtr/goleveldb/leveldb/util"
)

const financialHistoryMagic = "GGFHSEG1" // Published v1 files remain immutable and readable.
const financialHistoryMagicV2 = "GGFHSEG2"
const financialHistoryReferenceMagic = "GGFHREF1\x00"
const financialHistoryReferenceMagicV2 = "GGFHREF2" // Exactly eight bytes.
const financialHistoryCompactReferenceBytes = 32
const financialHistoryMeta = "zs/"
const financialHistoryActive = "za/"
const financialHistorySegmentBytes int64 = 64 << 20
const financialHistorySegmentRecords = 4096
const financialHistoryHeaderBytes = 8192
const financialHistoryReferenceBytes = 4096
const financialHistoryActiveTarget uint64 = 128 << 20
const financialHistoryLowWatermark uint64 = 64 << 20
const financialHistoryDiskReserve uint64 = 8 << 20

var errFinancialHistory = errors.New("GG_FINANCIAL_HISTORY_UNAVAILABLE")

type financialHistoryHead struct {
	Anchor      string `json:"anchor"`
	Digest      string `json:"digest"`
	Initialized bool   `json:"initialized"`
	Schema      string `json:"schema"`
	Segments    uint64 `json:"segments"`
	Source      string `json:"source"`
}
type financialHistorySegmentHeader struct {
	Anchor      string `json:"anchor"`
	Count       int    `json:"count"`
	CutHeight   int64  `json:"cut_height"`
	CutJournal  string `json:"cut_journal"`
	CutState    string `json:"cut_state"`
	First       string `json:"first"`
	FirstHeight int64  `json:"first_height"`
	Last        string `json:"last"`
	LastHeight  int64  `json:"last_height"`
	Previous    string `json:"previous"`
	Root        string `json:"root"`
	Schema      string `json:"schema"`
	Segment     uint64 `json:"segment"`
	Source      string `json:"source"`
}
type financialHistorySegment struct {
	Bytes  int64                         `json:"bytes"`
	Digest string                        `json:"digest"`
	Header financialHistorySegmentHeader `json:"header"`
	Schema string                        `json:"schema"`
}
type financialHistoryReference struct {
	Index   int        `json:"index"`
	Length  int        `json:"length"`
	Offset  int64      `json:"offset"`
	Path    []PathItem `json:"path"`
	Schema  string     `json:"schema"`
	Segment uint64     `json:"segment"`
}
type financialHistoryRecord struct {
	key, digest string
	length      int
	offset      int64
}
type financialHistory struct {
	pending              *financialHistorySegment
	failed               atomic.Bool
	retainedThrough      atomic.Int64
	db                   *leveldb.DB
	root, anchor, source string
	head                 financialHistoryHead
	hasHead              bool
	syncWrite            func(*leveldb.Batch) error
	activeBytes          uint64
	archivedBytes        uint64
	archivedOriginals    int64
	// Only native owned tests may supply fault. Never decoded or exposed in JSON.
	fault func(string) error
}

func historySegmentKey(sequence uint64) string  { return fmt.Sprintf("zs/segment/%020d", sequence) }
func historySegmentName(sequence uint64) string { return fmt.Sprintf("%020d.ggfh", sequence) }
func historyMetadataKey(key string) bool {
	return strings.HasPrefix(key, financialHistoryMeta) || strings.HasPrefix(key, financialHistoryActive)
}
func historyImmutableKey(key string) bool {
	for _, prefix := range []string{"fa/", "fl/", "pr/", "er/", "p/"} {
		if strings.HasPrefix(key, prefix) {
			return pubPattern.MatchString(strings.TrimPrefix(key, prefix))
		}
	}
	if strings.HasPrefix(key, "j/") || strings.HasPrefix(key, "h/") || strings.HasPrefix(key, "vc/") || strings.HasPrefix(key, "bo/") {
		prefix, number, ok := strings.Cut(key, "/")
		n, err := strconv.ParseUint(number, 10, 64)
		return ok && err == nil && n > 0 && n <= dagSegmentCounterMax && key == fmt.Sprintf("%s/%020d", prefix, n)
	}
	if strings.HasPrefix(key, "t/") {
		return validFinancialSummaryNodeKey(key, dagSegmentCounterMax)
	}
	return false
}
func historyValueLimit(key string) int {
	switch {
	case strings.HasPrefix(key, "j/"):
		return financialJournalMaxWire
	case strings.HasPrefix(key, "h/"):
		return dagArchiveHeaderLimit
	case strings.HasPrefix(key, "p/"):
		return financialReceiptArchiveMaxWire
	case strings.HasPrefix(key, "er/"):
		return protocolRewardMaxWire
	case strings.HasPrefix(key, "vc/"):
		return 256 * 1024
	case strings.HasPrefix(key, "fa/"):
		return financialAccountNodeMaxBytes
	case strings.HasPrefix(key, "fl/"):
		return dagMetadataNodeMax
	case strings.HasPrefix(key, "pr/"):
		return 2*16384 + 2048
	default:
		return 64
	}
}

// Reserve the complete reference family. Unknown/truncated versions must never
// become application bytes or reenter the active-original queue.
func historyReference(raw []byte) bool {
	return bytes.HasPrefix(raw, []byte("GGFHREF"))
}
func historySegmentVersion(segment financialHistorySegment) int {
	switch {
	case segment.Schema == "gg.financial.history.segment.v1" && segment.Header.Schema == "gg.financial.history.segment-header.v1":
		return 1
	case segment.Schema == "gg.financial.history.segment.v2" && segment.Header.Schema == "gg.financial.history.segment-header.v2":
		return 2
	default:
		return 0
	}
}

// Layer widths use the existing odd-node duplication at EACH level. Padding
// the leaf level to a power of two changes roots for some odd record counts.
func historyTreeDigestCount(count int) int {
	if count < 1 || count > financialHistorySegmentRecords {
		return 0
	}
	total := count
	for count > 1 {
		count = (count + 1) / 2
		total += count
	}
	return total
}
func historyRecordEnd(segment financialHistorySegment) (int64, error) {
	version := historySegmentVersion(segment)
	if version == 0 || segment.Bytes < 44 || segment.Bytes > financialHistorySegmentBytes ||
		historyTreeDigestCount(segment.Header.Count) == 0 {
		return 0, errFinancialHistory
	}
	end := segment.Bytes - 32
	if version == 2 {
		end -= int64(historyTreeDigestCount(segment.Header.Count)) * 32
	}
	if end < 12+int64(len(canonical(segment.Header)))+int64(segment.Header.Count)*7 {
		return 0, errFinancialHistory
	}
	return end, nil
}
func historyDecodeReference(raw []byte, key string) (financialHistoryReference, int, error) {
	var reference financialHistoryReference
	if !historyImmutableKey(key) || len(raw) > financialHistoryReferenceBytes {
		return reference, 0, errFinancialHistory
	}
	version := 0
	switch {
	case bytes.HasPrefix(raw, []byte(financialHistoryReferenceMagic)):
		encoded := raw[len(financialHistoryReferenceMagic):]
		if decodeStrict(encoded, &reference) != nil || !bytes.Equal(encoded, canonical(reference)) ||
			reference.Schema != "gg.financial.history.reference.v1" {
			return reference, 0, errFinancialHistory
		}
		version = 1
	case bytes.HasPrefix(raw, []byte(financialHistoryReferenceMagicV2)):
		if len(raw) != financialHistoryCompactReferenceBytes {
			return reference, 0, errFinancialHistory
		}
		index, length, offset := binary.BigEndian.Uint32(raw[16:20]), binary.BigEndian.Uint32(raw[20:24]), binary.BigEndian.Uint64(raw[24:32])
		if index >= financialHistorySegmentRecords || uint64(length) > uint64(historyValueLimit(key)) || offset > uint64(financialHistorySegmentBytes) {
			return reference, 0, errFinancialHistory
		}
		reference = financialHistoryReference{Index: int(index), Length: int(length), Offset: int64(offset), Schema: "gg.financial.history.reference.v2", Segment: binary.BigEndian.Uint64(raw[8:16])}
		version = 2
	default:
		return reference, 0, errFinancialHistory
	}
	if reference.Segment == 0 || reference.Segment > dagSegmentCounterMax || reference.Index < 0 || reference.Index >= financialHistorySegmentRecords ||
		reference.Length < 1 || reference.Length > historyValueLimit(key) || reference.Offset < 0 {
		return reference, 0, errFinancialHistory
	}
	return reference, version, nil
}

// Read only the siblings selected by a bounded, verified Count. The header
// root remains the authentication target; neither the footer nor the reference
// is a trust flag. Even an odd duplicated sibling must equal the running hash.
func historyReadFooterPath(ctx context.Context, reader io.ReaderAt, segment financialHistorySegment, index int) ([]PathItem, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	end, err := historyRecordEnd(segment)
	if err != nil || historySegmentVersion(segment) != 2 || index < 0 || index >= segment.Header.Count {
		return nil, errFinancialHistory
	}
	path := make([]PathItem, 0, 12)
	base := end
	for width := segment.Header.Count; width > 1; width = (width + 1) / 2 {
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		sibling := index ^ 1
		if sibling >= width {
			sibling = index
		}
		var digest [32]byte
		if _, err := reader.ReadAt(digest[:], base+int64(sibling)*32); err != nil {
			return nil, errFinancialHistory
		}
		side := "right"
		if index&1 != 0 {
			side = "left"
		}
		path = append(path, PathItem{Hash: hex.EncodeToString(digest[:]), Side: side})
		base += int64(width) * 32
		index /= 2
	}
	return path, nil
}
func historyWriteTree(ctx context.Context, writer io.Writer, digest hash.Hash, layers [][]string) error {
	for _, layer := range layers {
		for _, value := range layer {
			if err := ctx.Err(); err != nil {
				return err
			}
			raw, err := hex.DecodeString(value)
			if err != nil || len(raw) != 32 {
				return errFinancialHistory
			}
			if err = historyWrite(writer, digest, raw); err != nil {
				return err
			}
		}
	}
	return nil
}
func historyCheckTree(ctx context.Context, reader io.ReaderAt, segment financialHistorySegment, layers [][]string) error {
	offset, err := historyRecordEnd(segment)
	if err != nil {
		return err
	}
	if historySegmentVersion(segment) == 1 {
		return nil
	}
	for _, layer := range layers {
		for _, value := range layer {
			if err := ctx.Err(); err != nil {
				return err
			}
			var raw [32]byte
			if _, err := reader.ReadAt(raw[:], offset); err != nil || hex.EncodeToString(raw[:]) != value {
				return errFinancialHistory
			}
			offset += 32
		}
	}
	if offset != segment.Bytes-32 {
		return errFinancialHistory
	}
	return nil
}
func historyRecordHash(key string, raw []byte) string {
	h := sha256.New()
	_, _ = h.Write([]byte("GG-FINANCIAL-HISTORY-RECORD-v1\x00"))
	var lengths [12]byte
	binary.BigEndian.PutUint32(lengths[:4], uint32(len(key)))
	binary.BigEndian.PutUint64(lengths[4:], uint64(len(raw)))
	_, _ = h.Write(lengths[:])
	_, _ = h.Write([]byte(key))
	_, _ = h.Write(raw)
	return hex.EncodeToString(h.Sum(nil))
}
func historyJoin(left, right string) string {
	return hashHex([]byte("GG-FINANCIAL-HISTORY-NODE-v1\x00" + left + right))
}
func historyLayers(records []financialHistoryRecord) [][]string {
	values := make([]string, len(records))
	for i, r := range records {
		values[i] = r.digest
	}
	layers := [][]string{values}
	for len(values) > 1 {
		next := make([]string, (len(values)+1)/2)
		for i := range next {
			j := 2 * i
			right := values[j]
			if j+1 < len(values) {
				right = values[j+1]
			}
			next[i] = historyJoin(values[j], right)
		}
		values = next
		layers = append(layers, values)
	}
	return layers
}
func historyPath(layers [][]string, index int) []PathItem {
	result := []PathItem{}
	for _, values := range layers[:len(layers)-1] {
		sibling := index ^ 1
		if sibling >= len(values) {
			sibling = index
		}
		side := "right"
		if index&1 != 0 {
			side = "left"
		}
		result = append(result, PathItem{Hash: values[sibling], Side: side})
		index /= 2
	}
	return result
}
func historyCheckPath(value string, reference financialHistoryReference, header financialHistorySegmentHeader) bool {
	if reference.Index < 0 || reference.Index >= header.Count || len(reference.Path) > 12 {
		return false
	}
	index, width := reference.Index, header.Count
	p := 0
	for width > 1 {
		if p >= len(reference.Path) {
			return false
		}
		item := reference.Path[p]
		side := "right"
		if index&1 != 0 {
			side = "left"
		}
		if item.Side != side || !pubPattern.MatchString(item.Hash) || index^1 >= width && item.Hash != value {
			return false
		}
		if side == "right" {
			value = historyJoin(value, item.Hash)
		} else {
			value = historyJoin(item.Hash, value)
		}
		index /= 2
		width = (width + 1) / 2
		p++
	}
	return p == len(reference.Path) && value == header.Root
}
func (h *financialHistory) faultAt(step string) error {
	if h.fault != nil {
		return h.fault(step)
	}
	return nil
}
func (h *financialHistory) directory() string { return filepath.Join(h.root, "gg-financial-history") }
func (h *financialHistory) write(batch *leveldb.Batch) error {
	if h.failed.Load() {
		return errFinancialHistory
	}
	var err error
	if h.syncWrite != nil {
		err = h.syncWrite(batch)
	} else {
		err = h.db.Write(batch, &opt.WriteOptions{Sync: true, NoWriteMerge: true})
	}
	if err != nil || h.failed.Load() {
		return errFinancialHistory
	}
	return nil
}
func (h *financialHistory) segment(read func(string) ([]byte, error), sequence uint64) (financialHistorySegment, error) {
	if sequence == 0 || sequence > dagSegmentCounterMax {
		return financialHistorySegment{}, errFinancialHistory
	}
	var segment financialHistorySegment
	raw, err := read(historySegmentKey(sequence))
	if err != nil || len(raw) > financialHistoryHeaderBytes || decodeStrict(raw, &segment) != nil || !bytes.Equal(raw, canonical(segment)) ||
		historySegmentVersion(segment) == 0 || segment.Header.Segment != sequence ||
		segment.Header.Anchor != h.anchor || segment.Header.Source != h.source || !pubPattern.MatchString(segment.Digest) || !pubPattern.MatchString(segment.Header.Root) ||
		segment.Header.Count < 1 || segment.Header.Count > financialHistorySegmentRecords || !historyImmutableKey(segment.Header.First) || !historyImmutableKey(segment.Header.Last) || segment.Header.First > segment.Header.Last ||
		segment.Bytes < 44 || segment.Bytes > financialHistorySegmentBytes || segment.Header.CutHeight < 0 || segment.Header.CutHeight > int64(dagSegmentCounterMax) || !pubPattern.MatchString(segment.Header.Previous) || !pubPattern.MatchString(segment.Header.CutState) || !pubPattern.MatchString(segment.Header.CutJournal) ||
		segment.Header.FirstHeight < 0 || segment.Header.LastHeight < segment.Header.FirstHeight || segment.Header.LastHeight > segment.Header.CutHeight {
		return segment, errFinancialHistory
	}
	if _, err := historyRecordEnd(segment); err != nil {
		return segment, err
	}
	return segment, nil
}
func historyReadFileHeader(file *os.File, segment financialHistorySegment) error {
	magic := financialHistoryMagic
	switch historySegmentVersion(segment) {
	case 1:
	case 2:
		magic = financialHistoryMagicV2
	default:
		return errFinancialHistory
	}
	var prefix [12]byte
	if _, err := file.ReadAt(prefix[:], 0); err != nil || string(prefix[:8]) != magic {
		return errFinancialHistory
	}
	length := binary.BigEndian.Uint32(prefix[8:])
	if length < 1 || length > financialHistoryHeaderBytes {
		return errFinancialHistory
	}
	raw := make([]byte, int(length))
	if _, err := file.ReadAt(raw, 12); err != nil || !bytes.Equal(raw, canonical(segment.Header)) {
		return errFinancialHistory
	}
	return nil
}
func (h *financialHistory) read(ctx context.Context, get func(string) ([]byte, error), key string) (value []byte, failure error) {
	if h.failed.Load() {
		return nil, errFinancialHistory
	}
	defer func() {
		if failure != nil && failure != leveldb.ErrNotFound && !errors.Is(failure, context.Canceled) && !errors.Is(failure, context.DeadlineExceeded) {
			h.failed.Store(true)
		}
	}()

	if err := ctx.Err(); err != nil {
		return nil, err
	}
	raw, err := get(key)
	if err == leveldb.ErrNotFound {
		return nil, err
	}

	if err != nil {
		return nil, errFinancialHistory
	}
	if !historyReference(raw) {
		return raw, nil
	}
	reference, version, err := historyDecodeReference(raw, key)
	if err != nil {
		return nil, err
	}
	segment, err := h.segment(get, reference.Segment)
	if err != nil {
		return nil, err
	}
	end, endErr := historyRecordEnd(segment)
	if endErr != nil || version != historySegmentVersion(segment) || reference.Index >= segment.Header.Count ||
		reference.Offset < 12+int64(len(canonical(segment.Header))) || reference.Offset > end-6-int64(len(key))-int64(reference.Length) {
		return nil, errFinancialHistory
	}
	finishDirectory, err := recoveryHistoryDirectory(ctx, h.directory())
	if err != nil {
		return nil, errFinancialHistory
	}
	defer func() {
		if finishDirectory() != nil {
			value, failure = nil, errFinancialHistory
		}
	}()
	file, info, err := recoveryHistoryFile(ctx, filepath.Join(h.directory(), historySegmentName(reference.Segment)), financialHistorySegmentBytes)
	if err != nil {
		return nil, errFinancialHistory
	}
	valid := false
	defer func() {
		if !valid {
			_ = file.Close()
		}
	}()
	if info.Size() != segment.Bytes || historyReadFileHeader(file, segment) != nil {
		return nil, errFinancialHistory
	}
	var lengths [6]byte
	if _, err = file.ReadAt(lengths[:], reference.Offset); err != nil || int(binary.BigEndian.Uint16(lengths[:2])) != len(key) || int(binary.BigEndian.Uint32(lengths[2:])) != reference.Length {
		return nil, errFinancialHistory
	}
	record := make([]byte, len(key)+reference.Length)
	if _, err = file.ReadAt(record, reference.Offset+6); err != nil || string(record[:len(key)]) != key {
		return nil, errFinancialHistory
	}
	value = record[len(key):]
	if version == 2 {
		reference.Path, err = historyReadFooterPath(ctx, file, segment, reference.Index)
		if err != nil {
			return nil, err
		}
	}
	if !historyCheckPath(historyRecordHash(key, value), reference, segment.Header) {
		return nil, errFinancialHistory
	}
	if err = ctx.Err(); err != nil {
		return nil, err
	}
	valid = true
	if file.Close() != nil {
		return nil, errFinancialHistory
	}
	return value, nil
}
func (h *financialHistory) get(ctx context.Context, key string) ([]byte, error) {
	return h.read(ctx, func(key string) ([]byte, error) { return h.db.Get([]byte(key), nil) }, key)
}

// Existence is established by the native caller's committed root/range or by
// an already authenticated reference, never by an external lookup selector.
// Semantic checks remain at those same callers. This helper is not wire data.
func (h *financialHistory) rejectRecord(ctx context.Context, cause error) error {
	if cause == nil {
		return nil
	}
	if err := ctx.Err(); err != nil {
		return err
	}
	if !errors.Is(cause, context.Canceled) && !errors.Is(cause, context.DeadlineExceeded) {
		h.failed.Store(true)
	}
	return cause
}
func (h *financialHistory) requiredRead(ctx context.Context, read func(string) ([]byte, error), key string) ([]byte, error) {
	raw, err := read(key)
	if err != nil {
		return nil, h.rejectRecord(ctx, err)
	}
	return raw, nil
}
func (h *financialHistory) requiredDigestRead(ctx context.Context, read func(string) ([]byte, error)) func(string) ([]byte, error) {
	return func(key string) ([]byte, error) {
		raw, err := h.requiredRead(ctx, read, key)
		if err != nil {
			return nil, err
		}
		if !pubPattern.Match(raw) {
			return nil, h.rejectRecord(ctx, errFinancialStore)
		}
		return raw, nil
	}
}

// Iterate the existing ordered logical keyspace. The physical DB remains the
// disk index. Metadata/active scheduling keys are never application records.
type financialHistoryIterator struct {
	iterator.Iterator
	h       *financialHistory
	ctx     context.Context
	value   []byte
	failure error
}

func (it *financialHistoryIterator) Next() bool {
	if it.failure != nil {
		return false
	}
	for it.Iterator.Next() {
		if err := it.ctx.Err(); err != nil {
			it.failure = err
			return false
		}
		key := string(it.Iterator.Key())
		if historyMetadataKey(key) {
			continue
		}
		physical := it.Iterator.Value()
		if it.h.head.Initialized && historyImmutableKey(key) && !historyReference(physical) {
			queue, e := it.h.db.Get([]byte(financialHistoryActive+key), nil)
			if e != nil || len(queue) != 8 || binary.BigEndian.Uint64(queue) != uint64(len(key)+len(physical)+6) {
				it.failure = errFinancialHistory
				return false
			}
		}
		it.value, it.failure = it.h.get(it.ctx, key)
		return it.failure == nil
	}
	return false
}
func (it *financialHistoryIterator) Value() []byte { return it.value }
func (it *financialHistoryIterator) Error() error {
	if it.failure != nil {
		return it.failure
	}
	return it.Iterator.Error()
}
func (h *financialHistory) iterator(ctx context.Context) *financialHistoryIterator {
	return &financialHistoryIterator{Iterator: h.db.NewIterator(nil, nil), h: h, ctx: ctx}
}

type historyBatchTracker struct{ actions map[string]uint64 }

func (v *historyBatchTracker) Put(key, value []byte) {
	k := string(key)
	if !historyImmutableKey(k) {
		return
	}
	size := uint64(0)
	if !historyReference(value) {
		size = uint64(len(key) + len(value) + 6)
	}
	v.actions[k] = size
}
func (v *historyBatchTracker) Delete(key []byte) {
	if historyImmutableKey(string(key)) {
		v.actions[string(key)] = 0
	}
}

// Called before a synchronous application batch. Queue and active-byte facts
// commit atomically with its originals. The queue contains only active keys.
func (h *financialHistory) trackBatch(batch *leveldb.Batch) (uint64, error) {
	if !h.hasHead {
		batch.Put([]byte("zs/head"), canonical(h.head))
	}
	visitor := &historyBatchTracker{actions: map[string]uint64{}}
	if batch.Replay(visitor) != nil {
		return 0, errFinancialHistory
	}
	next := h.activeBytes
	for key, size := range visitor.actions {
		old, err := h.db.Get([]byte(financialHistoryActive+key), nil)
		if err != nil && err != leveldb.ErrNotFound {
			return 0, errFinancialHistory
		}
		if err == nil {
			if len(old) != 8 || binary.BigEndian.Uint64(old) > next {
				return 0, errFinancialHistory
			}
			next -= binary.BigEndian.Uint64(old)
		}
		if size == 0 {
			batch.Delete([]byte(financialHistoryActive + key))
		} else {
			if size > ^uint64(0)-next {
				return 0, errFinancialHistory
			}
			next += size
			var raw [8]byte
			binary.BigEndian.PutUint64(raw[:], size)
			batch.Put([]byte(financialHistoryActive+key), raw[:])
		}
	}
	return next, nil
}
func (h *financialHistory) initialize(ctx context.Context) error {
	if h.head.Initialized {
		return nil
	}
	if !h.hasHead {
		intent := new(leveldb.Batch)
		intent.Put([]byte("zs/head"), canonical(h.head))
		if h.write(intent) != nil {
			return errFinancialHistory
		}
		h.hasHead = true
		if err := h.faultAt("INITIALIZE_HEAD_SYNC"); err != nil {
			return err
		}
	}
	iter := h.db.NewIterator(nil, nil)
	defer iter.Release()
	batch := new(leveldb.Batch)
	for iter.Next() {
		if err := ctx.Err(); err != nil {
			return err
		}
		key := string(iter.Key())
		if !historyImmutableKey(key) {
			continue
		}
		if historyReference(iter.Value()) {
			return errFinancialHistory
		}
		var raw [8]byte
		binary.BigEndian.PutUint64(raw[:], uint64(len(key)+len(iter.Value())+6))
		batch.Put([]byte(financialHistoryActive+key), raw[:])
		if batch.Len() >= 128 {
			if h.write(batch) != nil {
				return errFinancialHistory
			}
			if err := h.faultAt("INITIALIZE_CHUNK_SYNC"); err != nil {
				return err
			}
			batch.Reset()
		}
	}
	if iter.Error() != nil {
		return errFinancialHistory
	}
	h.head.Initialized = true
	batch.Put([]byte("zs/head"), canonical(h.head))
	if h.write(batch) != nil {
		h.head.Initialized = false
		return errFinancialHistory
	}
	if err := h.faultAt("INITIALIZE_COMPLETE_SYNC"); err != nil {
		return err
	}
	return h.checkActive(ctx)
}
func (h *financialHistory) checkActive(ctx context.Context) error {
	iter := h.db.NewIterator(util.BytesPrefix([]byte(financialHistoryActive)), nil)
	defer iter.Release()
	total := uint64(0)
	for iter.Next() {
		if err := ctx.Err(); err != nil {
			return err
		}
		key := strings.TrimPrefix(string(iter.Key()), financialHistoryActive)
		raw, err := h.db.Get([]byte(key), nil)
		size := uint64(len(key) + len(raw) + 6)
		if !historyImmutableKey(key) || err != nil || historyReference(raw) || len(iter.Value()) != 8 || binary.BigEndian.Uint64(iter.Value()) != size || size > ^uint64(0)-total {
			return errFinancialHistory
		}
		total += size
		if err := recoveryWork(ctx, size, nil); err != nil {
			return err
		}
	}
	if iter.Error() != nil {
		return errFinancialHistory
	}
	if h.head.Initialized {
		physical := h.db.NewIterator(nil, nil)
		for physical.Next() {
			if err := ctx.Err(); err != nil {
				physical.Release()
				return err
			}
			key := string(physical.Key())
			raw := physical.Value()
			if !historyImmutableKey(key) || historyReference(raw) {
				continue
			}
			queue, e := h.db.Get([]byte(financialHistoryActive+key), nil)
			if e != nil || len(queue) != 8 || binary.BigEndian.Uint64(queue) != uint64(6+len(key)+len(raw)) {
				physical.Release()
				return errFinancialHistory
			}
		}
		err := physical.Error()
		physical.Release()
		if err != nil {
			return errFinancialHistory
		}
	}
	h.activeBytes = total
	return nil
}
func openFinancialHistory(ctx context.Context, db *leveldb.DB, root, anchor, source string, writable bool) (*financialHistory, error) {
	h := &financialHistory{db: db, root: root, anchor: anchor, source: source, head: financialHistoryHead{Anchor: anchor, Digest: DagZero, Schema: "gg.financial.history.head.v1", Source: source}}
	raw, err := db.Get([]byte("zs/head"), nil)
	if err == leveldb.ErrNotFound {
		iter := db.NewIterator(util.BytesPrefix([]byte("z")), nil)
		exists := iter.Next()
		iterErr := iter.Error()
		iter.Release()
		if exists || iterErr != nil {
			return nil, errFinancialHistory
		}
		if _, err := os.Lstat(h.directory()); !os.IsNotExist(err) {
			return nil, errFinancialHistory
		}
		return h, nil
	}
	h.hasHead = true
	if err != nil || len(raw) > 4096 || decodeStrict(raw, &h.head) != nil || !bytes.Equal(raw, canonical(h.head)) || h.head.Schema != "gg.financial.history.head.v1" || h.head.Anchor != anchor || h.head.Source != source || !pubPattern.MatchString(h.head.Digest) || h.head.Segments > dagSegmentCounterMax || !h.head.Initialized && h.head.Segments != 0 {
		return nil, errFinancialHistory
	}
	if pendingRaw, pendingErr := db.Get([]byte("zs/intent"), nil); pendingErr == nil {
		if !writable || !h.head.Initialized {
			return nil, errFinancialHistory
		}
		segment, e := h.segment(func(string) ([]byte, error) { return pendingRaw, nil }, h.head.Segments+1)
		if e != nil || segment.Header.Previous != h.head.Digest {
			return nil, errFinancialHistory
		}
		h.pending = &segment
	} else if pendingErr != leveldb.ErrNotFound {
		return nil, errFinancialHistory
	}

	if err = h.validate(ctx); err != nil {
		return nil, err
	}
	return h, nil
}
func (h *financialHistory) validate(ctx context.Context) error {
	get := func(key string) ([]byte, error) { return h.db.Get([]byte(key), nil) }
	iter := h.db.NewIterator(util.BytesPrefix([]byte(financialHistoryMeta)), nil)
	defer iter.Release()
	count := uint64(0)
	previous := DagZero
	h.archivedBytes = 0
	h.archivedOriginals = 0
	lastCut := int64(0)
	for iter.Next() {
		if err := ctx.Err(); err != nil {
			return err
		}
		key := string(iter.Key())
		if key == "zs/head" || key == "zs/intent" && h.pending != nil {
			continue
		}
		if count == dagSegmentCounterMax || key != historySegmentKey(count+1) {
			return errFinancialHistory
		}
		count++
		segment, err := h.segment(get, count)
		if err != nil || segment.Header.Previous != previous || segment.Header.CutHeight < lastCut {
			return errFinancialHistory
		}
		lastCut = segment.Header.CutHeight
		if segment.Header.FirstHeight > 0 {
			if segment.Header.FirstHeight != h.archivedOriginals+1 {
				return errFinancialHistory
			}
			h.archivedOriginals = segment.Header.LastHeight
		}
		if uint64(segment.Bytes) > ^uint64(0)-h.archivedBytes {
			return errFinancialHistory
		}
		h.archivedBytes += uint64(segment.Bytes)
		if _, err = h.inspectFile(ctx, segment, false); err != nil {
			return err
		}
		previous = segment.Digest
		if err := recoveryWork(ctx, 1, nil); err != nil {
			return err
		}
	}
	if iter.Error() != nil || count != h.head.Segments || previous != h.head.Digest {
		return errFinancialHistory
	}
	if err := h.inventoryFiles(ctx); err != nil {
		return err
	}
	return h.checkActive(ctx)
}
func (h *financialHistory) inventoryFiles(ctx context.Context) error {
	info, err := os.Lstat(h.directory())
	if os.IsNotExist(err) && h.head.Segments == 0 {
		return nil
	}
	if err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		return errFinancialHistory
	}
	resolved, err := filepath.EvalSymlinks(h.directory())
	if err != nil || resolved != h.directory() {
		return errFinancialHistory
	}
	dir, err := os.Open(h.directory())
	if err != nil {
		return errFinancialHistory
	}
	failure := error(nil)
	for {
		entries, readErr := dir.ReadDir(64)
		for _, entry := range entries {
			if err := ctx.Err(); err != nil {
				failure = err
				break
			}
			name := entry.Name()
			pendingName := false
			if h.pending != nil {
				base := historySegmentName(h.pending.Header.Segment)
				pendingName = name == base || name == base+".pending"
			}
			if pendingName {
				entryInfo, e := entry.Info()
				if e != nil || !entryInfo.Mode().IsRegular() || entryInfo.Mode()&os.ModeSymlink != 0 || entryInfo.Size() < 0 || entryInfo.Size() > financialHistorySegmentBytes {
					failure = errFinancialHistory
					break
				}
				continue
			}
			if len(name) != 25 || !strings.HasSuffix(name, ".ggfh") {
				failure = errFinancialHistory
				break
			}
			sequence, e := strconv.ParseUint(name[:20], 10, 64)
			if e != nil || sequence < 1 || sequence > h.head.Segments || name != historySegmentName(sequence) {
				failure = errFinancialHistory
				break
			}
			entryInfo, e := entry.Info()
			if e != nil || !entryInfo.Mode().IsRegular() || entryInfo.Mode()&os.ModeSymlink != 0 {
				failure = errFinancialHistory
				break
			}
		}
		if failure != nil || readErr == io.EOF {
			break
		}
		if readErr != nil {
			failure = errFinancialHistory
			break
		}
	}
	if dir.Close() != nil {
		return errFinancialHistory
	}
	return failure
}
func historyRecordFrame(key string, raw []byte) []byte {
	frame := make([]byte, 6+len(key)+len(raw))
	binary.BigEndian.PutUint16(frame[:2], uint16(len(key)))
	binary.BigEndian.PutUint32(frame[2:6], uint32(len(raw)))
	copy(frame[6:], key)
	copy(frame[6+len(key):], raw)
	return frame
}
func historyReferenceWire(record financialHistoryRecord, index int, segment financialHistorySegment, layers [][]string) []byte {
	switch historySegmentVersion(segment) {
	case 1:
		reference := financialHistoryReference{Index: index, Length: record.length, Offset: record.offset, Path: historyPath(layers, index), Schema: "gg.financial.history.reference.v1", Segment: segment.Header.Segment}
		return append([]byte(financialHistoryReferenceMagic), canonical(reference)...)
	case 2:
		if index < 0 || index >= segment.Header.Count || record.length < 1 || record.length > historyValueLimit(record.key) ||
			record.offset < 0 || record.offset > financialHistorySegmentBytes || segment.Header.Segment == 0 || segment.Header.Segment > dagSegmentCounterMax {
			return nil
		}
		raw := make([]byte, financialHistoryCompactReferenceBytes)
		copy(raw[:8], financialHistoryReferenceMagicV2)
		binary.BigEndian.PutUint64(raw[8:16], segment.Header.Segment)
		binary.BigEndian.PutUint32(raw[16:20], uint32(index))
		binary.BigEndian.PutUint32(raw[20:24], uint32(record.length))
		binary.BigEndian.PutUint64(raw[24:32], uint64(record.offset))
		return raw
	default:
		return nil
	}
}

// Inspect every frame, digest and exact per-key index. Cold replay subsequently
// rederives the semantic contents; this physical check is never state authority.
func (h *financialHistory) inspectFile(ctx context.Context, segment financialHistorySegment, active bool) (records []financialHistoryRecord, failure error) {
	finishDirectory, e := recoveryHistoryDirectory(ctx, h.directory())
	if e != nil {
		return nil, e
	}
	defer func() {
		if finishDirectory() != nil {
			records = nil
			failure = errFinancialHistory
		}
	}()
	file, info, err := recoveryHistoryFile(ctx, filepath.Join(h.directory(), historySegmentName(segment.Header.Segment)), financialHistorySegmentBytes)
	if err != nil {
		return nil, errFinancialHistory
	}
	defer func() {
		if closeErr := file.Close(); closeErr != nil && failure == nil {
			records = nil
			failure = errFinancialHistory
		}
	}()
	if info.Size() != segment.Bytes || historyReadFileHeader(file, segment) != nil {
		return nil, errFinancialHistory
	}
	if _, err = file.Seek(0, io.SeekStart); err != nil {
		return nil, errFinancialHistory
	}
	digest := sha256.New()
	remaining := segment.Bytes - 32
	buffer := make([]byte, 64*1024)
	for remaining > 0 {
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		size := int64(len(buffer))
		if remaining < size {
			size = remaining
		}
		if _, err = io.ReadFull(file, buffer[:size]); err != nil {
			return nil, errFinancialHistory
		}
		_, _ = digest.Write(buffer[:size])
		if err := recoveryWork(ctx, uint64(size), nil); err != nil {
			return nil, err
		}
		remaining -= size
	}
	footer := make([]byte, 32)
	if _, err = io.ReadFull(file, footer); err != nil || !bytes.Equal(footer, digest.Sum(nil)) || hex.EncodeToString(footer) != segment.Digest {
		return nil, errFinancialHistory
	}
	end, err := historyRecordEnd(segment)
	if err != nil {
		return nil, err
	}
	offset := int64(12 + len(canonical(segment.Header)))
	previous := ""
	firstHeight, lastHeight := int64(0), int64(0)
	journalCount := int64(0)
	for i := 0; i < segment.Header.Count; i++ {
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		var lengths [6]byte
		if offset > end-6 {
			return nil, errFinancialHistory
		}
		if _, err = file.ReadAt(lengths[:], offset); err != nil {
			return nil, errFinancialHistory
		}
		keyLength, valueLength := int(binary.BigEndian.Uint16(lengths[:2])), int(binary.BigEndian.Uint32(lengths[2:]))
		if keyLength < 1 || keyLength > 128 || valueLength < 1 || valueLength > financialJournalMaxWire || int64(6+keyLength+valueLength) > end-offset {
			return nil, errFinancialHistory
		}
		frame := make([]byte, keyLength+valueLength)
		if _, err = file.ReadAt(frame, offset+6); err != nil {
			return nil, errFinancialHistory
		}
		key := string(frame[:keyLength])
		value := frame[keyLength:]
		if !historyImmutableKey(key) || key <= previous || valueLength > historyValueLimit(key) || historyReference(value) {
			return nil, errFinancialHistory
		}
		if strings.HasPrefix(key, "j/") {
			height, _ := strconv.ParseInt(key[2:], 10, 64)
			if firstHeight == 0 {
				firstHeight = height
			}
			lastHeight = height
		}
		previous = key
		if strings.HasPrefix(key, "j/") {
			journalCount++
			if lastHeight-firstHeight+1 != journalCount {
				return nil, errFinancialHistory
			}
		}
		records = append(records, financialHistoryRecord{key: key, digest: historyRecordHash(key, value), length: valueLength, offset: offset})
		offset += int64(6 + keyLength + valueLength)
		if active {
			actual, e := h.db.Get([]byte(key), nil)
			if e != nil || !bytes.Equal(actual, value) {
				return nil, errFinancialHistory
			}
		}
	}
	if offset != end || records[0].key != segment.Header.First || previous != segment.Header.Last || firstHeight != segment.Header.FirstHeight || lastHeight != segment.Header.LastHeight {
		return nil, errFinancialHistory
	}
	layers := historyLayers(records)
	if layers[len(layers)-1][0] != segment.Header.Root {
		return nil, errFinancialHistory
	}
	if err := historyCheckTree(ctx, file, segment, layers); err != nil {
		return nil, err
	}
	if !active {
		for i, record := range records {
			actual, e := h.db.Get([]byte(record.key), nil)
			if e != nil || !bytes.Equal(actual, historyReferenceWire(record, i, segment, layers)) {
				return nil, errFinancialHistory
			}
		}
	}
	return records, nil
}
func historyWriteRecord(writer io.Writer, digest hash.Hash, key string, raw []byte) error {
	var lengths [6]byte
	binary.BigEndian.PutUint16(lengths[:2], uint16(len(key)))
	binary.BigEndian.PutUint32(lengths[2:], uint32(len(raw)))
	for _, part := range [][]byte{lengths[:], []byte(key), raw} {
		if err := historyWrite(writer, digest, part); err != nil {
			return err
		}
	}
	return nil
}
func historyWrite(writer io.Writer, digest hash.Hash, raw []byte) error {
	if n, err := writer.Write(raw); err != nil || n != len(raw) {
		return errFinancialHistory
	}
	if digest != nil {
		_, _ = digest.Write(raw)
	}
	return nil
}
func (h *financialHistory) seal(ctx context.Context, cut financialStoreHead) error {
	if !h.head.Initialized || h.head.Segments == dagSegmentCounterMax || cut.Anchor != h.anchor || cut.Source != h.source {
		return errFinancialHistory
	}
	if _, err := h.db.Get([]byte("zs/intent"), nil); err != leveldb.ErrNotFound {
		return errFinancialHistory
	}
	snapshot, err := h.db.GetSnapshot()
	if err != nil {
		return errFinancialHistory
	}
	defer snapshot.Release()
	rawHead, headErr := snapshot.Get([]byte("head"), nil)
	if headErr != nil || !bytes.Equal(rawHead, canonical(cut)) {
		return errFinancialHistory
	}
	iter := snapshot.NewIterator(util.BytesPrefix([]byte(financialHistoryActive)), nil)
	defer iter.Release()
	records := []financialHistoryRecord{}
	payload := int64(0)
	firstHeight, lastHeight := int64(0), int64(0)
	for iter.Next() {
		if err := ctx.Err(); err != nil {
			return err
		}
		key := strings.TrimPrefix(string(iter.Key()), financialHistoryActive)
		raw, e := snapshot.Get([]byte(key), nil)
		if e != nil || !historyImmutableKey(key) || historyReference(raw) || len(raw) < 1 || len(raw) > historyValueLimit(key) {
			return errFinancialHistory
		}
		size := int64(6 + len(key) + len(raw))
		if len(records) == financialHistorySegmentRecords {
			break
		}
		treeBytes := int64(historyTreeDigestCount(len(records)+1)) * 32
		if payload+size+treeBytes > financialHistorySegmentBytes-financialHistoryHeaderBytes-44 {
			if len(records) > 0 {
				break
			}
			return errFinancialHistory
		}
		records = append(records, financialHistoryRecord{key: key, digest: historyRecordHash(key, raw), length: len(raw)})
		payload += size
		if strings.HasPrefix(key, "j/") {
			height, _ := strconv.ParseInt(key[2:], 10, 64)
			if firstHeight == 0 {
				firstHeight = height
			}
			lastHeight = height
		}
	}
	if iter.Error() != nil {
		return errFinancialHistory
	}
	if len(records) == 0 {
		return nil
	}
	if firstHeight > 0 && firstHeight != h.archivedOriginals+1 {
		return errFinancialHistory
	}
	layers := historyLayers(records)
	header := financialHistorySegmentHeader{Anchor: h.anchor, Count: len(records), CutHeight: cut.State.Height, CutJournal: cut.Journal, CutState: cut.State.StateRoot, First: records[0].key, FirstHeight: firstHeight, Last: records[len(records)-1].key, LastHeight: lastHeight, Previous: h.head.Digest, Root: layers[len(layers)-1][0], Schema: "gg.financial.history.segment-header.v2", Segment: h.head.Segments + 1, Source: h.source}
	rawHeader := canonical(header)
	if len(rawHeader) > financialHistoryHeaderBytes {
		return errFinancialHistory
	}
	var prefix [12]byte
	copy(prefix[:8], financialHistoryMagicV2)
	binary.BigEndian.PutUint32(prefix[8:], uint32(len(rawHeader)))
	digest := sha256.New()
	_, _ = digest.Write(prefix[:])
	_, _ = digest.Write(rawHeader)
	offset := int64(12 + len(rawHeader))
	for i := range records {
		records[i].offset = offset
		raw, e := snapshot.Get([]byte(records[i].key), nil)
		if e != nil || historyRecordHash(records[i].key, raw) != records[i].digest {
			return errFinancialHistory
		}
		if err := historyWriteRecord(io.Discard, digest, records[i].key, raw); err != nil {
			return err
		}
		offset += int64(6 + len(records[i].key) + len(raw))
	}
	if err := historyWriteTree(ctx, io.Discard, digest, layers); err != nil {
		return err
	}
	segment := financialHistorySegment{Bytes: offset + int64(historyTreeDigestCount(len(records)))*32 + 32, Digest: hex.EncodeToString(digest.Sum(nil)), Header: header, Schema: "gg.financial.history.segment.v2"}
	if _, err := historyRecordEnd(segment); err != nil {
		return err
	}
	if err := ctx.Err(); err != nil {
		return err
	}
	if err = os.Mkdir(h.directory(), 0700); err != nil && !os.IsExist(err) {
		return errFinancialHistory
	}
	if !realArchiveDirectory(h.directory()) {
		return errFinancialHistory
	}
	resolved, e := filepath.EvalSymlinks(h.directory())
	if e != nil || resolved != h.directory() {
		return errFinancialHistory
	}
	if err = financialHistoryReserve(h.directory(), uint64(segment.Bytes)+financialHistoryDiskReserve); err != nil {
		return err
	}
	intent := new(leveldb.Batch)
	intent.Put([]byte("zs/intent"), canonical(segment))
	if h.write(intent) != nil {
		return errFinancialHistory
	}
	if err = h.faultAt("INTENT_SYNC"); err != nil {
		return err
	}
	stage := filepath.Join(h.directory(), historySegmentName(header.Segment)+".pending")
	file, err := os.OpenFile(stage, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil {
		return errFinancialHistory
	}
	writeErr := h.faultAt("FILE_CREATED")
	if writeErr == nil {
		writeErr = historyWrite(file, nil, prefix[:])
	}
	if writeErr == nil {
		writeErr = historyWrite(file, nil, rawHeader)
	}
	for _, record := range records {
		if writeErr != nil {
			break
		}
		if writeErr = ctx.Err(); writeErr != nil {
			break
		}
		raw, e := snapshot.Get([]byte(record.key), nil)
		if e != nil || historyRecordHash(record.key, raw) != record.digest {
			writeErr = errFinancialHistory
			break
		}
		writeErr = historyWriteRecord(file, nil, record.key, raw)
		if writeErr == nil {
			writeErr = h.faultAt("RECORD_WRITTEN")
		}
	}
	if writeErr == nil {
		writeErr = historyWriteTree(ctx, file, nil, layers)
	}
	if writeErr == nil {
		writeErr = h.faultAt("TREE_WRITTEN")
	}
	if writeErr == nil {
		footer, _ := hex.DecodeString(segment.Digest)
		writeErr = historyWrite(file, nil, footer)
	}
	if writeErr == nil {
		writeErr = h.faultAt("FILE_WRITTEN")
	}
	if writeErr == nil && file.Sync() != nil {
		writeErr = errFinancialHistory
	}
	if writeErr == nil {
		writeErr = h.faultAt("FILE_SYNC")
	}
	closeErr := file.Close()
	if writeErr != nil {
		return writeErr
	}
	if closeErr != nil {
		return errFinancialHistory
	}
	if err = h.faultAt("FILE_CLOSED"); err != nil {
		return err
	}
	if err := ctx.Err(); err != nil {
		return err
	}
	if err = financialHistoryPublish(stage, strings.TrimSuffix(stage, ".pending")); err != nil {
		return err
	}
	if err = h.faultAt("FILE_PUBLISHED"); err != nil {
		return err
	}
	if _, err = h.inspectFile(ctx, segment, true); err != nil {
		return err
	}
	if err = h.faultAt("READBACK_VERIFIED"); err != nil {
		return err
	}
	return h.commitSegment(ctx, segment, records)
}
func (h *financialHistory) commitSegment(ctx context.Context, segment financialHistorySegment, records []financialHistoryRecord) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	layers := historyLayers(records)
	batch := new(leveldb.Batch)
	retired := uint64(0)
	for i, record := range records {
		raw, err := h.db.Get([]byte(record.key), nil)
		if err != nil || historyReference(raw) || historyRecordHash(record.key, raw) != record.digest {
			return errFinancialHistory
		}
		ref := historyReferenceWire(record, i, segment, layers)
		if len(ref) == 0 || len(ref) > financialHistoryReferenceBytes {
			return errFinancialHistory
		}
		batch.Put([]byte(record.key), ref)
		batch.Delete([]byte(financialHistoryActive + record.key))
		retired += uint64(6 + len(record.key) + record.length)
	}
	if retired > h.activeBytes {
		return errFinancialHistory
	}
	next := h.head
	next.Segments = segment.Header.Segment
	next.Digest = segment.Digest
	batch.Put([]byte(historySegmentKey(next.Segments)), canonical(segment))
	batch.Put([]byte("zs/head"), canonical(next))
	batch.Delete([]byte("zs/intent"))
	if err := h.faultAt("METADATA_BEFORE_SYNC"); err != nil {
		return err
	}
	if h.write(batch) != nil {
		return errFinancialHistory
	}
	h.head = next
	h.activeBytes -= retired
	h.archivedBytes += uint64(segment.Bytes)
	if segment.Header.FirstHeight > 0 {
		h.archivedOriginals = segment.Header.LastHeight
	}
	return h.faultAt("METADATA_AFTER_SYNC")
}
func (h *financialHistory) recoverIntent(ctx context.Context, writable bool) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	raw, err := h.db.Get([]byte("zs/intent"), nil)
	if err == leveldb.ErrNotFound {
		return nil
	}
	if err != nil || !writable || !h.head.Initialized || len(raw) > financialHistoryHeaderBytes {
		return errFinancialHistory
	}
	segment, parsedErr := h.segment(func(string) ([]byte, error) { return raw, nil }, h.head.Segments+1)
	if parsedErr != nil || segment.Header.Previous != h.head.Digest {
		return errFinancialHistory
	}
	final := filepath.Join(h.directory(), historySegmentName(segment.Header.Segment))
	stage := final + ".pending"
	if info, e := os.Lstat(final); e == nil {
		if !info.Mode().IsRegular() || info.Mode()&os.ModeSymlink != 0 {
			return errFinancialHistory
		}
		records, e := h.inspectFile(ctx, segment, true)
		if e != nil {
			return e
		}
		if pending, e := os.Lstat(stage); e == nil {
			if !os.SameFile(info, pending) || os.Remove(stage) != nil || financialHistorySyncDirectory(h.directory()) != nil {
				return errFinancialHistory
			}
		} else if !os.IsNotExist(e) {
			return errFinancialHistory
		}
		if e = h.checkActive(ctx); e != nil {
			return e
		}
		return h.commitSegment(ctx, segment, records)
	} else if !os.IsNotExist(e) {
		return errFinancialHistory
	}
	// Only an exact pending name registered by this durable intent can be
	// discarded. It was never the selected copy. Committed/unknown files are
	// never repaired or removed. A subsequent attempt uses the same originals.
	if info, e := os.Lstat(stage); e == nil {
		file, checked, e := checkedSegmentFile(stage, false, financialHistorySegmentBytes)
		if e != nil || !os.SameFile(info, checked) {
			if file != nil {
				_ = file.Close()
			}
			return errFinancialHistory
		}
		if file.Close() != nil {
			return errFinancialHistory
		}
		latest, e := os.Lstat(stage)
		if e != nil || !os.SameFile(checked, latest) {
			return errFinancialHistory
		}
		if os.Remove(stage) != nil || financialHistorySyncDirectory(h.directory()) != nil {
			return errFinancialHistory
		}
	} else if !os.IsNotExist(e) {
		return errFinancialHistory
	}
	if err := ctx.Err(); err != nil {
		return err
	}
	batch := new(leveldb.Batch)
	batch.Delete([]byte("zs/intent"))
	if h.write(batch) != nil {
		return errFinancialHistory
	}
	return nil
}

// The caller owns store.mu; no application/owner lock is acquired here. This
// loops over fixed-size segments until the active suffix actually reaches the
// low watermark. A single derived-heavy segment is not enough in general.
func (h *financialHistory) drainTo(ctx context.Context, cut financialStoreHead, low uint64) error {
	for h.activeBytes > low {
		if err := ctx.Err(); err != nil {
			return err
		}
		before := h.activeBytes
		if err := h.seal(ctx, cut); err != nil {
			return err
		}
		if h.activeBytes >= before {
			return errFinancialHistory
		}
	}
	return nil
}

// Publication recovery runs only after the OLD logical view passed the full
// independent original/derived replay. A foreign/corrupt store is not changed
// merely because it contains an apparently valid local storage intent.
func (h *financialHistory) resolvePending(ctx context.Context, cut financialStoreHead) error {
	if h.pending == nil {
		return nil
	}
	header := h.pending.Header
	if cut.Anchor != h.anchor || cut.Source != h.source || header.CutHeight != cut.State.Height || header.CutState != cut.State.StateRoot || header.CutJournal != cut.Journal {
		return errFinancialHistory
	}
	if err := h.recoverIntent(ctx, true); err != nil {
		return err
	}
	h.pending = nil
	return h.validate(ctx)
}
