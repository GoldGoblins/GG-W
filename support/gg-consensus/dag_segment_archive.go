//go:build !js

package main

// Local immutable original-signed segment archives. A replay uses a separately
// verified epoch base, never an account snapshot supplied by the archive. The
// durable receipt below is a storage barrier, NOT an SDK/quorum certificate.
import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strconv"
)

const dagSegmentArchiveMagic = "GGDAGSG1"
const dagSegmentArchiveMaxBytes int64 = DagMaxHistoryWire + DagMaxRecords*(dagManifestMaxBytes+10) + 2*dagArchiveHeaderLimit + dagArchiveFooterLimit + 32

var errDagSegmentArchive = errors.New("GG_DAG_SEGMENT_ARCHIVE")

type dagSegmentArchiveHeader struct {
	Anchor     string `json:"anchor"`
	BaseRoot   string `json:"base_root"`
	Blocks     int    `json:"blocks"`
	Cut        string `json:"cut"`
	Epoch      uint64 `json:"epoch,string"`
	Manifests  int    `json:"manifests"`
	RawBytes   int    `json:"raw_bytes"`
	Schema     string `json:"schema"`
	SourceHash string `json:"source_hash"`
}

type dagSegmentArchiveFooter struct {
	Blocks      int    `json:"blocks"`
	ContentHash string `json:"content_sha256"`
	Cut         string `json:"cut"`
	Manifests   int    `json:"manifests"`
	RawBytes    int    `json:"raw_bytes"`
	Schema      string `json:"schema"`
	SourceHash  string `json:"source_hash"`
}

type dagSegmentArchiveReplay struct {
	plan        dagHistoryCutPlan
	archiveHash string
	contentHash string
	index       *dagClosedIndex
}

func checkedSegmentBase(base *dagSegmentedExecution) (dagSegmentedState, error) {
	if base == nil || base.active == nil || validateSegmentedSource(base.source) != nil ||
		base.active.orderCount() != 0 || base.active.bytes != 0 || len(base.manifests) != 0 ||
		len(base.active.pending) != 0 || base.active.proofOrder != nil || base.active.payloadReader != nil ||
		base.active.Manifest.Checkpoint != 0 || len(base.active.Manifest.Blocks) != 0 ||
		base.active.Commitment.ManifestHash != base.startManifest || base.checkActiveHistory() != nil {
		return dagSegmentedState{}, errDagSegmentArchive
	}
	sealed := base.active.clone()
	sealed.seal()
	if sealed.Commitment != base.active.Commitment {
		return dagSegmentedState{}, errDagSegmentArchive
	}
	return base.state()
}

func segmentArchiveHeader(execution *dagSegmentedExecution, plan dagHistoryCutPlan) (dagSegmentArchiveHeader, error) {
	state, err := checkedSegmentBase(execution.startBase)
	if err != nil || plan.matches(execution) != nil {
		return dagSegmentArchiveHeader{}, errDagSegmentArchive
	}
	return dagSegmentArchiveHeader{Anchor: execution.anchor, BaseRoot: dagDigest("GG-DAG-SEGMENTED-STATE-v1\x00", state),
		Blocks: execution.active.orderCount(), Cut: plan.hash, Epoch: state.Epoch, Manifests: len(execution.manifests),
		RawBytes: execution.active.bytes, Schema: "gg.dag.history-segment.v1", SourceHash: state.SourceHash}, nil
}

// Stream one bounded segment. A complete footer/EOF and all block + TX
// signatures are required before the successor is returned even to this caller.
func readDagHistorySegment(ctx context.Context, input io.Reader, base *dagSegmentedExecution) (*dagSegmentArchiveReplay, error) {
	return readDagHistorySegmentObserved(ctx, input, base, nil)
}

// Observations are provisional until the whole archive/footer/EOF succeeds.
// The owned startup verifier uses them only to check its bounded history set;
// no caller may publish an observed prefix as a verified archive result.
func readDagHistorySegmentObserved(ctx context.Context, input io.Reader, base *dagSegmentedExecution, observe func(dagSegmentedState), retain ...func(*dagSegmentedExecution) error) (*dagSegmentArchiveReplay, error) {
	if len(retain) > 1 {
		return nil, errDagSegmentArchive
	}
	recordView := func(execution *dagSegmentedExecution) error {
		if len(retain) == 1 && retain[0] != nil {
			return retain[0](execution)
		}
		return nil
	}
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	baseState, err := checkedSegmentBase(base)
	if err != nil {
		return nil, err
	}
	whole, content := sha256.New(), sha256.New()
	limited := &io.LimitedReader{R: input, N: dagSegmentArchiveMaxBytes + 1}
	hashed := io.TeeReader(limited, whole)
	prefix := io.TeeReader(hashed, content)
	var magic [8]byte
	if _, err = io.ReadFull(prefix, magic[:]); err != nil || string(magic[:]) != dagSegmentArchiveMagic {
		return nil, errDagSegmentArchive
	}
	raw, err := readArchiveFrame(prefix, 'H', dagArchiveHeaderLimit)
	var header dagSegmentArchiveHeader
	if err != nil || decodeStrict(raw, &header) != nil || !bytes.Equal(raw, canonical(header)) ||
		header.Schema != "gg.dag.history-segment.v1" || header.Anchor != baseState.Anchor || header.SourceHash != baseState.SourceHash ||
		header.BaseRoot != dagDigest("GG-DAG-SEGMENTED-STATE-v1\x00", baseState) || header.Epoch != baseState.Epoch ||
		!pubPattern.MatchString(header.Cut) || header.Blocks < 1 || header.Blocks > DagMaxRecords ||
		header.Manifests < 1 || header.Manifests > header.Blocks || header.RawBytes < 1 || header.RawBytes > DagMaxHistoryWire {
		return nil, errDagSegmentArchive
	}
	cursor := base
	if observe != nil {
		observe(baseState)
	}
	if err := recordView(base); err != nil {
		return nil, err
	}
	blocks, rawBytes := 0, 0
	for index := 0; index < header.Manifests; index++ {
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		raw, err = readArchiveFrame(prefix, 'M', dagManifestMaxBytes)
		var manifest DagManifest
		if err != nil || decodeStrict(raw, &manifest) != nil || !bytes.Equal(raw, canonical(manifest)) ||
			len(manifest.Blocks) < 1 || len(manifest.Blocks) > DagMaxBatchBlocks || len(manifest.Blocks) > header.Blocks-blocks ||
			manifest.Checkpoint != cursor.active.Manifest.Checkpoint+1 || manifest.Previous != cursor.active.Commitment.ManifestHash ||
			manifest.GenesisHash != baseState.Anchor || manifest.SourceHash != baseState.SourceHash || manifest.Schema != "gg.dag.execution.manifest.v1" {
			return nil, errDagSegmentArchive
		}
		when, parseErr := strconv.ParseInt(manifest.TimeNs, 10, 64)
		if parseErr != nil || when <= 0 || strconv.FormatInt(when, 10) != manifest.TimeNs {
			return nil, errDagSegmentArchive
		}
		encoded := make([]string, 0, len(manifest.Blocks))
		batchBytes := 0
		for _, wireHash := range manifest.Blocks {
			if ctx.Err() != nil {
				return nil, ctx.Err()
			}
			// The remaining aggregate budget is checked BEFORE frame allocation.
			limit := min(DagMaxWire, header.RawBytes-rawBytes, DagMaxWire-batchBytes)
			raw, err = readArchiveFrame(prefix, 'R', limit)
			if err != nil || !pubPattern.MatchString(wireHash) || hashHex(raw) != wireHash {
				return nil, errDagSegmentArchive
			}
			batchBytes += len(raw)
			rawBytes += len(raw)
			blocks++
			encoded = append(encoded, base64.StdEncoding.EncodeToString(raw))
		}
		batch := DagBatch{Blocks: encoded, GenesisHash: manifest.GenesisHash, Previous: manifest.Previous,
			Schema: "gg.dag.checkpoint.batch.v1", Sequence: manifest.Checkpoint}
		cursor, err = cursor.apply(canonical(batch), when)
		if err != nil {
			return nil, err
		}
		if !bytes.Equal(canonical(cursor.active.Manifest), canonical(manifest)) {
			return nil, errDagSegmentArchive
		}
		// Original bytes are in the input archive, not retained once authenticated.
		// Authenticated metadata remains bounded by the active segment policy.
		cursor.active.pending = map[string]dagRecord{}
		if observe != nil {
			state, _ := cursor.state()
			observe(state)
		}
		if err := recordView(cursor); err != nil {
			return nil, err
		}
	}
	plan, err := cursor.prepareCut()
	if err != nil || blocks != header.Blocks || rawBytes != header.RawBytes || plan.hash != header.Cut {
		return nil, errDagSegmentArchive
	}
	raw, err = readArchiveFrame(prefix, 'C', dagArchiveHeaderLimit)
	if err != nil || !bytes.Equal(raw, canonical(plan.body)) {
		return nil, errDagSegmentArchive
	}
	contentHash := hex.EncodeToString(content.Sum(nil))
	raw, err = readArchiveFrame(hashed, 'F', dagArchiveFooterLimit)
	expectedFooter := dagSegmentArchiveFooter{Blocks: blocks, ContentHash: contentHash, Cut: plan.hash,
		Manifests: header.Manifests, RawBytes: rawBytes, Schema: "gg.dag.history-segment-footer.v1", SourceHash: header.SourceHash}
	if err != nil || !bytes.Equal(raw, canonical(expectedFooter)) {
		return nil, errDagSegmentArchive
	}
	var extra [1]byte
	if n, endErr := hashed.Read(extra[:]); n != 0 || endErr != io.EOF || limited.N <= 0 || ctx.Err() != nil {
		return nil, errDagSegmentArchive
	}
	if observe != nil {
		state, _ := plan.next.state()
		observe(state)
	}
	if err := recordView(plan.next); err != nil {
		return nil, err
	}
	result := &dagSegmentArchiveReplay{plan: plan, archiveHash: hex.EncodeToString(whole.Sum(nil)), contentHash: contentHash}
	result.index, err = originalDerivedClosedIndex(cursor, result, header, expectedFooter)
	if err != nil {
		return nil, err
	}
	return result, nil
}

func writeDagHistorySegment(ctx context.Context, output io.Writer, execution *dagSegmentedExecution) error {
	if ctx.Err() != nil {
		return ctx.Err()
	}
	plan, err := execution.prepareCut()
	if err != nil {
		return err
	}
	header, err := segmentArchiveHeader(execution, plan)
	if err != nil {
		return err
	}
	content := sha256.New()
	prefix := io.MultiWriter(output, content)
	if n, err := io.WriteString(prefix, dagSegmentArchiveMagic); err != nil || n != len(dagSegmentArchiveMagic) {
		return errDagSegmentArchive
	}
	if err = writeArchiveFrame(prefix, 'H', canonical(header), dagArchiveHeaderLimit); err != nil {
		return err
	}
	records := make(map[string]dagRecord, header.Blocks)
	err = execution.active.visitOrderPrefix(header.Blocks, func(leaf DagOrderLeaf) error {
		record, found, err := execution.active.historyRecord(leaf.Hash)
		if err != nil || !found {
			return errDagSegmentArchive
		}
		records[record.WireHash] = record
		return nil
	})
	if err != nil || len(records) != header.Blocks {
		return errDagSegmentArchive
	}
	for _, manifest := range execution.manifests {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		if err = writeArchiveFrame(prefix, 'M', canonical(manifest), dagManifestMaxBytes); err != nil {
			return err
		}
		batchBytes := 0
		for _, wire := range manifest.Blocks {
			if ctx.Err() != nil {
				return ctx.Err()
			}
			record, found := records[wire]
			if !found || record.WireBytes < 1 || record.WireBytes > DagMaxWire-batchBytes {
				return errDagSegmentArchive
			}
			raw := record.Raw
			if raw == nil && execution.active.payloadReader != nil {
				raw, err = execution.active.payloadReader(ctx, wire, record.WireBytes)
				if err != nil {
					return err
				}
			}
			if len(raw) != record.WireBytes || hashHex(raw) != wire {
				return errDagSegmentArchive
			}
			batchBytes += len(raw)
			if err = writeArchiveFrame(prefix, 'R', raw, DagMaxWire); err != nil {
				return err
			}
		}
	}
	if err = writeArchiveFrame(prefix, 'C', canonical(plan.body), dagArchiveHeaderLimit); err != nil {
		return err
	}
	footer := dagSegmentArchiveFooter{Blocks: header.Blocks, ContentHash: hex.EncodeToString(content.Sum(nil)), Cut: plan.hash,
		Manifests: header.Manifests, RawBytes: header.RawBytes, Schema: "gg.dag.history-segment-footer.v1", SourceHash: header.SourceHash}
	return writeArchiveFrame(output, 'F', canonical(footer), dagArchiveFooterLimit)
}

type dagSegmentArchiveOwner struct {
	Anchor     string `json:"anchor"`
	Schema     string `json:"schema"`
	SourceHash string `json:"source_hash"`
}

// Only persistDagHistorySegment can produce a ready receipt. It carries no
// consensus approval; the later SDK integration must certify this exact cut.
type dagSegmentArchiveReceipt struct {
	replay *dagSegmentArchiveReplay
	ready  bool
}

func (receipt *dagSegmentArchiveReceipt) successor(current *dagSegmentedExecution) (*dagSegmentedExecution, error) {
	if receipt == nil || !receipt.ready || receipt.replay == nil || receipt.replay.plan.matches(current) != nil {
		return nil, errDagSegmentArchive
	}
	// Return a fresh prepared value, not the receipt's mutable private pointer.
	plan, err := current.prepareCut()
	if err != nil {
		return nil, err
	}
	return plan.next, nil
}

type dagSegmentArchiveIO struct {
	sync    func(*os.File) error
	close   func(*os.File) error
	publish func(string, string) error
}

func segmentArchiveDefaultIO() dagSegmentArchiveIO {
	return dagSegmentArchiveIO{sync: (*os.File).Sync, close: (*os.File).Close, publish: os.Link}
}

func checkedSegmentFile(path string, writable bool, limit int64) (*os.File, os.FileInfo, error) {
	before, err := os.Lstat(path)
	if err != nil || !before.Mode().IsRegular() || before.Mode()&os.ModeSymlink != 0 || before.Size() < 0 || before.Size() > limit {
		return nil, nil, errDagSegmentArchive
	}
	flags := os.O_RDONLY
	if writable {
		flags = os.O_RDWR
	}
	file, err := os.OpenFile(path, flags, 0)
	if err != nil {
		return nil, nil, errDagSegmentArchive
	}
	after, err := file.Stat()
	if err != nil || !os.SameFile(before, after) {
		_ = file.Close()
		return nil, nil, errDagSegmentArchive
	}
	return file, after, nil
}

func removeOwnedSegmentPending(path string, owned os.FileInfo) error {
	current, err := os.Lstat(path)
	if err != nil || !current.Mode().IsRegular() || current.Mode()&os.ModeSymlink != 0 || !os.SameFile(current, owned) {
		return errDagSegmentArchive
	}
	return os.Remove(path)
}

// Called under the real OS lease. A partial initial OWNER may be finished only
// before any archive/staging/foreign file exists. Unknown contents are preserved.
func ensureSegmentOwner(parent string, owner dagSegmentArchiveOwner) error {
	path := filepath.Join(parent, "OWNER")
	expected := canonical(owner)
	file, _, err := checkedSegmentFile(path, false, 1024)
	var raw []byte
	absent := false
	if err == nil {
		raw, err = io.ReadAll(io.LimitReader(file, 1025))
		closeErr := file.Close()
		if err != nil || closeErr != nil {
			return errDagSegmentArchive
		}
		if bytes.Equal(raw, expected) {
			return nil
		}
	} else if _, statErr := os.Lstat(path); os.IsNotExist(statErr) {
		absent = true
	} else {
		return errDagSegmentArchive
	}
	if !bytes.HasPrefix(expected, raw) {
		return errDagSegmentArchive
	}
	entries, err := archiveDirectoryEntries(parent, 2)
	if err != nil {
		return errDagSegmentArchive
	}
	for _, entry := range entries {
		if entry.Name() != "OWNER" && entry.Name() != "gg-dag-archive-work" {
			return errDagSegmentArchive
		}
	}
	flags := os.O_WRONLY | os.O_CREATE | os.O_EXCL
	if absent {
		file, err = os.OpenFile(path, flags, 0600)
	} else {
		// Open and compare identity BEFORE truncation, so a substituted symlink
		// cannot turn initial-marker recovery into an unrelated file write.
		file, _, err = checkedSegmentFile(path, true, 1024)
		if err == nil {
			err = file.Truncate(0)
			if err != nil {
				_ = file.Close()
			}
		}
	}
	if err != nil {
		return errDagSegmentArchive
	}
	n, writeErr := file.Write(expected)
	syncErr, closeErr := file.Sync(), file.Close()
	if writeErr != nil || n != len(expected) || syncErr != nil || closeErr != nil {
		return errDagSegmentArchive
	}
	return nil
}

func persistDagHistorySegment(ctx context.Context, root string, current *dagSegmentedExecution) (*dagSegmentArchiveReceipt, error) {
	return persistDagHistorySegmentWithIO(ctx, root, current, segmentArchiveDefaultIO())
}

func persistDagHistorySegmentWithIO(ctx context.Context, root string, current *dagSegmentedExecution, ops dagSegmentArchiveIO) (receipt *dagSegmentArchiveReceipt, finalErr error) {
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	if current == nil || !filepath.IsAbs(root) || !realArchiveDirectory(root) || ops.sync == nil || ops.close == nil || ops.publish == nil {
		return nil, errDagSegmentArchive
	}
	plan, err := current.prepareCut()
	if err != nil {
		return nil, err
	}
	header, err := segmentArchiveHeader(current, plan)
	if err != nil {
		return nil, err
	}
	resolved, err := filepath.EvalSymlinks(root)
	if err != nil || !filepath.IsAbs(resolved) || !realArchiveDirectory(resolved) {
		return nil, errDagSegmentArchive
	}
	parent := filepath.Join(resolved, "gg-dag-segments")
	if err = os.Mkdir(parent, 0700); err != nil && !os.IsExist(err) {
		return nil, errDagSegmentArchive
	}
	if !realArchiveDirectory(parent) {
		return nil, errDagSegmentArchive
	}
	work, err := openDagArchiveWork(parent)
	if err != nil {
		return nil, err
	}
	defer func() {
		if err := work.close(); err != nil {
			receipt, finalErr = nil, err
		}
		if ctx.Err() != nil {
			receipt, finalErr = nil, ctx.Err()
		}
	}()
	if err = ensureSegmentOwner(parent, dagSegmentArchiveOwner{Anchor: header.Anchor, Schema: "gg.dag.segment-store.v1", SourceHash: header.SourceHash}); err != nil {
		return nil, err
	}
	finalPath := filepath.Join(parent, plan.hash+".ggseg")
	pendingPath := filepath.Join(parent, "segment.pending")
	verifyAndSync := func(path string) (*dagSegmentArchiveReplay, error) {
		file, _, err := checkedSegmentFile(path, true, dagSegmentArchiveMaxBytes)
		if err != nil {
			return nil, err
		}
		replay, replayErr := readDagHistorySegment(ctx, file, current.startBase)
		if replayErr == nil && replay.plan.matches(current) != nil {
			replayErr = errDagSegmentArchive
		}
		var syncErr error
		if replayErr == nil && ctx.Err() == nil {
			syncErr = ops.sync(file)
		} else if replayErr == nil {
			replayErr = ctx.Err()
		}
		closeErr := ops.close(file)
		if closeErr != nil {
			_ = file.Close()
		}
		if replayErr != nil || syncErr != nil || closeErr != nil {
			return nil, errDagSegmentArchive
		}
		return replay, nil
	}
	// An existing immutable file is always fully replayed; filename presence is
	// never a storage receipt. No final archive is overwritten or removed.
	if _, statErr := os.Lstat(finalPath); statErr == nil {
		replay, err := verifyAndSync(finalPath)
		if err != nil {
			return nil, err
		}
		return &dagSegmentArchiveReceipt{replay: replay, ready: true}, nil
	} else if !os.IsNotExist(statErr) {
		return nil, errDagSegmentArchive
	}
	if info, statErr := os.Lstat(pendingPath); statErr == nil {
		if !info.Mode().IsRegular() || info.Mode()&os.ModeSymlink != 0 || info.Size() > dagSegmentArchiveMaxBytes || removeOwnedSegmentPending(pendingPath, info) != nil {
			return nil, errDagSegmentArchive
		}
	} else if !os.IsNotExist(statErr) {
		return nil, errDagSegmentArchive
	}
	file, err := os.OpenFile(pendingPath, os.O_RDWR|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil {
		return nil, errDagSegmentArchive
	}
	owned, err := file.Stat()
	if err != nil {
		_ = file.Close()
		return nil, errDagSegmentArchive
	}
	writeErr := writeDagHistorySegment(ctx, file, current)
	var syncErr error
	if writeErr == nil && ctx.Err() == nil {
		syncErr = ops.sync(file)
	} else if writeErr == nil {
		writeErr = ctx.Err()
	}
	closeErr := ops.close(file)
	if closeErr != nil {
		_ = file.Close()
	}
	if writeErr != nil || syncErr != nil || closeErr != nil {
		return nil, errDagSegmentArchive
	}
	replay, err := verifyAndSync(pendingPath)
	if err != nil || ctx.Err() != nil {
		return nil, errDagSegmentArchive
	}
	currentInfo, err := os.Lstat(pendingPath)
	if err != nil || !os.SameFile(owned, currentInfo) || !currentInfo.Mode().IsRegular() || currentInfo.Mode()&os.ModeSymlink != 0 {
		return nil, errDagSegmentArchive
	}
	// Hard-link publication is atomic and refuses an existing destination.
	// Unsupported filesystems fail closed. Sync+Close is a process-crash barrier;
	// power-loss/directory durability is not asserted by this implementation.
	if err = ops.publish(pendingPath, finalPath); err != nil {
		return nil, errDagSegmentArchive
	}
	if err = removeOwnedSegmentPending(pendingPath, owned); err != nil {
		return nil, err
	}
	return &dagSegmentArchiveReceipt{replay: replay, ready: true}, nil
}
