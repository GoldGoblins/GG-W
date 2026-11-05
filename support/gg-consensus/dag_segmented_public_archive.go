//go:build !js

package main

// A portable original-signed history, in forward order from pinned genesis.
// Closed segments are streamed as bounded nested frames, never allocated as a
// whole or used as an account snapshot. The active tail uses the same executor.
// Nothing is published until the SDK pin, full replay, footer and EOF agree.
import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/binary"
	"encoding/hex"
	"errors"
	"io"
	"path/filepath"
)

const dagSegmentedPublicMagic = "GGDAGAR2"
const dagSegmentedPublicScope = "FULL_ORIGINAL_SIGNED_SEGMENT_CHAIN_AND_ACTIVE_REPLAY_WITH_PINNED_SDK_CERTIFICATE_NOT_NATIVE_TRANSFER_HISTORY"

var errDagSegmentedPublicArchive = errors.New("GG_DAG_SEGMENTED_PUBLIC_ARCHIVE")

type dagSegmentedPublicFooter struct {
	ActiveCheckpoints uint64 `json:"active_checkpoints"`
	Blocks            uint64 `json:"blocks,string"`
	ContentHash       string `json:"content_sha256"`
	RawBytes          uint64 `json:"raw_bytes,string"`
	Schema            string `json:"schema"`
	Segments          uint64 `json:"segments,string"`
}

func segmentedPublicFooter(execution *dagSegmentedExecution, content string) dagSegmentedPublicFooter {
	state, _ := execution.state()
	return dagSegmentedPublicFooter{ActiveCheckpoints: state.Active.Checkpoint, Blocks: state.Blocks, ContentHash: content,
		RawBytes: state.RawBytes, Schema: "gg.dag.archive.footer.v2", Segments: state.Epoch - 1}
}

func segmentedArchiveResult(execution *dagSegmentedExecution, certificate dagArchiveCertificate, whole, content string) map[string]any {
	state, _ := execution.state()
	base, _ := execution.startBase.state()
	return map[string]any{"schema": "gg.dag.archive.result.v2", "verified": true, "history_replayed": true,
		"verification_scope": dagSegmentedPublicScope, "archive_sha256": whole, "content_sha256": content,
		"commitment": state, "accounts": execution.active.Accounts,
		"segment_base":       map[string]any{"commitment": base, "accounts": execution.startBase.active.Accounts},
		"certificate_height": certificate.State.Height + 1, "genesis_hash": certificate.GenesisHash,
		"network_id": execution.source.NetworkID, "signing_keys_exported": false, "snapshot_trust_used": false}
}

// No history-sized lists or buffers. Each next base is derived from the entire
// preceding signed segment; no epoch supplied by a peer can skip that work.
func verifyDagSegmentedPublicArchive(ctx context.Context, input io.Reader, request dagArchiveCommand) (map[string]any, error) {
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	if validateGenesis(request.Genesis, request.GenesisHash) != nil || request.Genesis.DAGSegmented == nil {
		return nil, errDagSegmentedPublicArchive
	}
	digest := sha256.New()
	hashed := io.TeeReader(input, digest)
	var magic [8]byte
	if _, err := io.ReadFull(hashed, magic[:]); err != nil || string(magic[:]) != dagSegmentedPublicMagic {
		return nil, errDagSegmentedPublicArchive
	}
	raw, err := readArchiveFrame(hashed, 'H', dagArchiveHeaderLimit)
	var header dagArchiveHeader
	if err != nil || decodeStrictLimited(raw, &header, MaxBlockTxs, 64) != nil || !bytes.Equal(raw, canonical(header)) || header.Schema != "gg.dag.public-archive.v2" {
		return nil, errDagSegmentedPublicArchive
	}
	if err := checkedArchiveCertificate(header.Certificate, request); err != nil {
		return nil, err
	}
	normalized, err := normalizedArchiveHeader(header.Certificate)
	if err != nil || !bytes.Equal(normalized, header.Certificate.SignedHeader) {
		return nil, errDagSegmentedPublicArchive
	}
	expected := *header.Certificate.State.DAGSegmented
	cursor, err := newDagSegmentedExecution(*request.Genesis.DAGSegmented, request.GenesisHash)
	if err != nil {
		return nil, err
	}
	for epoch := uint64(1); epoch < expected.Epoch; epoch++ {
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		var frame [5]byte
		if _, err := io.ReadFull(hashed, frame[:]); err != nil || frame[0] != 'S' {
			return nil, errDagSegmentedPublicArchive
		}
		size := int64(binary.BigEndian.Uint32(frame[1:]))
		if size < 1 || size > dagSegmentArchiveMaxBytes {
			return nil, errDagSegmentedPublicArchive
		}
		segment := &io.LimitedReader{R: hashed, N: size}
		replayed, err := readDagHistorySegment(ctx, segment, cursor)
		if err != nil || segment.N != 0 {
			return nil, errDagSegmentedPublicArchive
		}
		cursor = replayed.plan.next
		state, err := cursor.state()
		if err != nil || state.Blocks > expected.Blocks-uint64(expected.Active.Blocks) || state.RawBytes > expected.RawBytes || state.Transactions > expected.Transactions {
			return nil, errDagSegmentedPublicArchive
		}
	}
	for checkpoint := uint64(1); checkpoint <= expected.Active.Checkpoint; checkpoint++ {
		raw, err := readArchiveFrame(hashed, 'M', dagManifestMaxBytes)
		if err != nil {
			return nil, err
		}
		cursor, err = replaySegmentedPublicManifest(ctx, cursor, raw, expected, func(wanted string, limit int) ([]byte, error) {
			return readArchiveFrame(hashed, 'R', limit)
		})
		if err != nil {
			return nil, err
		}
	}
	actual, err := cursor.state()
	if err != nil || actual != expected {
		return nil, errDagSegmentedPublicArchive
	}
	content := hex.EncodeToString(digest.Sum(nil))
	raw, err = readArchiveFrame(hashed, 'F', dagArchiveFooterLimit)
	if err != nil || !bytes.Equal(raw, canonical(segmentedPublicFooter(cursor, content))) {
		return nil, errDagSegmentedPublicArchive
	}
	var extra [1]byte
	if n, err := hashed.Read(extra[:]); n != 0 || err != io.EOF || ctx.Err() != nil {
		return nil, errDagSegmentedPublicArchive
	}
	return segmentedArchiveResult(cursor, header.Certificate, hex.EncodeToString(digest.Sum(nil)), content), nil
}

// Both import and export perform actual signature/parent/sequence/nonce/balance
// execution. Aggregate credit is checked BEFORE allocating each raw frame.
func replaySegmentedPublicManifest(ctx context.Context, base *dagSegmentedExecution, raw []byte, expected dagSegmentedState, read func(string, int) ([]byte, error)) (*dagSegmentedExecution, error) {
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	var manifest DagManifest
	state, err := base.state()
	if err != nil || decodeStrictLimited(raw, &manifest, DagMaxBatchBlocks, 16) != nil || !bytes.Equal(raw, canonical(manifest)) ||
		manifest.Schema != "gg.dag.execution.manifest.v1" || manifest.GenesisHash != base.anchor || manifest.SourceHash != state.SourceHash ||
		manifest.Checkpoint != state.Active.Checkpoint+1 || manifest.Previous != state.Active.ManifestHash || len(manifest.Blocks) < 1 ||
		state.Epoch != expected.Epoch || state.Active.Blocks > expected.Active.Blocks || len(manifest.Blocks) > expected.Active.Blocks-state.Active.Blocks ||
		state.RawBytes > expected.RawBytes {
		return nil, errDagSegmentedPublicArchive
	}
	when, ok := dagDecimalNs(manifest.TimeNs)
	if !ok {
		return nil, errDagSegmentedPublicArchive
	}
	encoded := make([]string, 0, len(manifest.Blocks))
	size := 0
	remaining := expected.RawBytes - state.RawBytes
	for _, wire := range manifest.Blocks {
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		limit := min(DagMaxWire-size, int(min(remaining, uint64(DagMaxWire))))
		if !pubPattern.MatchString(wire) || limit < 1 {
			return nil, errDagSegmentedPublicArchive
		}
		raw, err := read(wire, limit)
		if err != nil || len(raw) < 1 || len(raw) > limit || hashHex(raw) != wire {
			return nil, errDagSegmentedPublicArchive
		}
		size += len(raw)
		remaining -= uint64(len(raw))
		encoded = append(encoded, base64.StdEncoding.EncodeToString(raw))
	}
	next, err := base.apply(canonical(DagBatch{Blocks: encoded, GenesisHash: base.anchor, Previous: manifest.Previous,
		Schema: "gg.dag.checkpoint.batch.v1", Sequence: manifest.Checkpoint}), when)
	if err != nil || !bytes.Equal(canonical(next.active.Manifest), canonical(manifest)) {
		return nil, errDagSegmentedPublicArchive
	}
	next.active.pending = map[string]dagRecord{}
	return next, nil
}

// The command opens an offline database read-only with its exclusive OS lease.
// Holding this lock also makes direct internal use safe from concurrent commit.
func exportDagSegmentedPublicArchive(ctx context.Context, output io.Writer, store *dagSegmentStore, request dagArchiveCommand) (map[string]any, error) {
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	if request.Certificate == nil || request.Genesis.DAGSegmented == nil || checkedArchiveCertificate(*request.Certificate, request) != nil {
		return nil, errDagSegmentedPublicArchive
	}
	store.mu.Lock()
	defer store.mu.Unlock()
	if store.db == nil || store.failed || store.meta.Anchor != request.GenesisHash || store.selected == nil ||
		!bytes.Equal(canonical(store.selected.source), canonical(*request.Genesis.DAGSegmented)) {
		return nil, errDagSegmentedPublicArchive
	}
	certificate := *request.Certificate
	expected := *certificate.State.DAGSegmented
	state, err := store.selected.state()
	if err != nil || state != expected {
		return nil, errors.New("GG_DAG_ARCHIVE_HEAD_CHANGED")
	}
	certificate.SignedHeader, err = normalizedArchiveHeader(certificate)
	if err != nil {
		return nil, err
	}
	digest := sha256.New()
	hashed := io.MultiWriter(output, digest)
	if n, err := io.WriteString(hashed, dagSegmentedPublicMagic); err != nil || n != len(dagSegmentedPublicMagic) {
		return nil, errDagSegmentedPublicArchive
	}
	if err := writeArchiveFrame(hashed, 'H', canonical(dagArchiveHeader{Certificate: certificate, Schema: "gg.dag.public-archive.v2"}), dagArchiveHeaderLimit); err != nil {
		return nil, err
	}
	cursor, err := newDagSegmentedExecution(*request.Genesis.DAGSegmented, request.GenesisHash)
	if err != nil {
		return nil, err
	}
	for epoch := uint64(1); epoch < expected.Epoch; epoch++ {
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		raw, err := store.db.Get([]byte(segmentArchiveReferenceKey(epoch)), nil)
		var reference dagSegmentArchiveReference
		if err != nil || len(raw) > 512 || decodeStrict(raw, &reference) != nil || !bytes.Equal(raw, canonical(reference)) ||
			reference.Epoch != epoch || reference.Schema != "gg.dag.segment-reference.v1" || !pubPattern.MatchString(reference.Cut) || !pubPattern.MatchString(reference.ArchiveHash) {
			return nil, errDagSegmentedPublicArchive
		}
		file, info, err := checkedSegmentFile(filepath.Join(store.root, "gg-dag-segments", reference.Cut+".ggseg"), false, dagSegmentArchiveMaxBytes)
		if err != nil {
			return nil, err
		}
		frame := [5]byte{'S'}
		binary.BigEndian.PutUint32(frame[1:], uint32(info.Size()))
		if n, err := hashed.Write(frame[:]); err != nil || n != len(frame) {
			_ = file.Close()
			return nil, errDagSegmentedPublicArchive
		}
		limited := &io.LimitedReader{R: file, N: info.Size()}
		replayed, replayErr := readDagHistorySegment(ctx, io.TeeReader(limited, hashed), cursor)
		var extra [1]byte
		n, endErr := file.Read(extra[:])
		closeErr := file.Close()
		if replayErr != nil || limited.N != 0 || n != 0 || endErr != io.EOF || closeErr != nil || replayed.plan.hash != reference.Cut || replayed.archiveHash != reference.ArchiveHash {
			return nil, errDagSegmentedPublicArchive
		}
		cursor = replayed.plan.next
	}
	// Only one active segment's metadata is retained. Earlier segments are gone
	// from the execution graph, and their bytes were streamed through the hash.
	for _, manifest := range store.selected.manifests {
		raw := canonical(manifest)
		if err := writeArchiveFrame(hashed, 'M', raw, dagManifestMaxBytes); err != nil {
			return nil, err
		}
		cursor, err = replaySegmentedPublicManifest(ctx, cursor, raw, expected, func(wanted string, limit int) ([]byte, error) {
			raw, err := store.db.Get([]byte("r/"+wanted), nil)
			if err != nil || len(raw) < 1 || len(raw) > limit || hashHex(raw) != wanted {
				return nil, errDagSegmentedPublicArchive
			}
			if err := writeArchiveFrame(hashed, 'R', raw, limit); err != nil {
				return nil, err
			}
			return raw, nil
		})
		if err != nil {
			return nil, err
		}
	}
	actual, err := cursor.state()
	if err != nil || actual != expected || len(store.selected.manifests) != int(expected.Active.Checkpoint) || ctx.Err() != nil {
		return nil, errDagSegmentedPublicArchive
	}
	content := hex.EncodeToString(digest.Sum(nil))
	if err := writeArchiveFrame(hashed, 'F', canonical(segmentedPublicFooter(cursor, content)), dagArchiveFooterLimit); err != nil {
		return nil, err
	}
	return segmentedArchiveResult(cursor, certificate, hex.EncodeToString(digest.Sum(nil)), content), nil
}
