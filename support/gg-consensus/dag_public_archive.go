//go:build !js

package main

// Public original DAG payload + exact selected checkpoint manifests. This is
// full signed DAG replay against a separately pinned SDK certificate, never a
// private-key backup, native-transfer-history replay or a state-sync snapshot.
import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"

	cmtjson "github.com/cometbft/cometbft/libs/json"
)

const dagArchiveMagic = "GGDAGAR1"
const dagArchiveHeaderLimit = 256 * 1024
const dagArchiveFooterLimit = 1024
const dagArchiveMaxBytes int64 = DagMaxHistoryWire + (DagMaxRecords+1)*(dagManifestMaxBytes+5) + dagArchiveHeaderLimit + dagArchiveFooterLimit + 5*DagMaxRecords + 32

type dagArchiveCertificate struct {
	CommitteeTransitions []financialCommitteeTransition `json:"committee_transitions,omitempty"`
	Genesis              Genesis                        `json:"genesis"`
	GenesisHash          string                         `json:"genesis_hash"`
	Schema               string                         `json:"schema"`
	SignedHeader         json.RawMessage                `json:"signed_header"`
	State                State                          `json:"state"`
}

func (value dagArchiveCertificate) packet() VerifyInput {
	return VerifyInput{Schema: value.Schema, Genesis: value.Genesis, GenesisHash: value.GenesisHash, SignedHeader: value.SignedHeader, State: value.State, CommitteeTransitions: value.CommitteeTransitions}
}

func normalizedArchiveHeader(certificate dagArchiveCertificate) (json.RawMessage, error) {
	value, err := verifyHeader(certificate.SignedHeader, certificate.Genesis)
	if err != nil {
		return nil, errors.New("GG_DAG_ARCHIVE_CERTIFICATE")
	}
	raw, err := cmtjson.Marshal(value)
	if err != nil {
		return nil, errors.New("GG_DAG_ARCHIVE_CERTIFICATE")
	}
	return raw, nil
}

type dagArchiveHeader struct {
	Certificate dagArchiveCertificate `json:"certificate"`
	Schema      string                `json:"schema"`
}

type dagArchiveFooter struct {
	Blocks      int    `json:"blocks"`
	Checkpoints uint64 `json:"checkpoints"`
	ContentHash string `json:"content_sha256"`
	RawBytes    int    `json:"raw_bytes"`
	Schema      string `json:"schema"`
}

type dagArchiveCommand struct {
	ArchivePath              string                 `json:"archive_path"`
	Certificate              *dagArchiveCertificate `json:"certificate,omitempty"`
	Genesis                  Genesis                `json:"genesis"`
	GenesisHash              string                 `json:"genesis_hash"`
	MinimumCertificateHeight int64                  `json:"minimum_certificate_height,omitempty"`
	MinimumCertificateBlock  string                 `json:"minimum_certificate_block,omitempty"`
	Root                     string                 `json:"root,omitempty"`
	WorkRoot                 string                 `json:"work_root"`
}

func checkedArchiveCertificate(value dagArchiveCertificate, request dagArchiveCommand) error {
	segmented := request.Genesis.DAGSegmented != nil
	if segmented && (value.Genesis.DAGSegmented == nil || value.State.DAGSegmented == nil) ||
		!segmented && (value.Genesis.DAG == nil || value.State.DAG == nil) || value.GenesisHash != request.GenesisHash ||
		!bytes.Equal(canonical(value.Genesis), canonical(request.Genesis)) || len(canonical(value)) > dagArchiveHeaderLimit ||
		request.MinimumCertificateHeight < 0 || request.MinimumCertificateBlock != "" && !pubPattern.MatchString(request.MinimumCertificateBlock) {
		return errors.New("GG_DAG_ARCHIVE_TRUST")
	}
	if request.MinimumCertificateBlock != "" && request.MinimumCertificateHeight == 0 {
		return errors.New("GG_DAG_ARCHIVE_TRUST")
	}
	if _, err := verifyInput(value.packet()); err != nil {
		return errors.New("GG_DAG_ARCHIVE_CERTIFICATE")
	}
	header, err := verifyHeader(value.SignedHeader, value.Genesis)
	if err != nil || header.Height < request.MinimumCertificateHeight {
		return errors.New("GG_DAG_ARCHIVE_CERTIFICATE_FLOOR")
	}
	if header.Height == request.MinimumCertificateHeight && request.MinimumCertificateBlock != "" &&
		strings.ToLower(header.Commit.BlockID.Hash.String()) != request.MinimumCertificateBlock {
		return errors.New("GG_DAG_ARCHIVE_CERTIFICATE_CONFLICT")
	}
	return nil
}

func writeArchiveFrame(output io.Writer, kind byte, raw []byte, limit int) error {
	if len(raw) == 0 || len(raw) > limit {
		return errors.New("GG_DAG_ARCHIVE_FRAME_LIMIT")
	}
	header := [5]byte{kind}
	binary.BigEndian.PutUint32(header[1:], uint32(len(raw)))
	if n, err := output.Write(header[:]); err != nil || n != len(header) {
		return errors.New("GG_DAG_ARCHIVE_WRITE")
	}
	if n, err := output.Write(raw); err != nil || n != len(raw) {
		return errors.New("GG_DAG_ARCHIVE_WRITE")
	}
	return nil
}

func readArchiveFrame(input io.Reader, kind byte, limit int) ([]byte, error) {
	var header [5]byte
	if _, err := io.ReadFull(input, header[:]); err != nil || header[0] != kind {
		return nil, errors.New("GG_DAG_ARCHIVE_FRAME")
	}
	size := binary.BigEndian.Uint32(header[1:])
	if size == 0 || uint64(size) > uint64(limit) {
		return nil, errors.New("GG_DAG_ARCHIVE_FRAME_LIMIT")
	}
	raw := make([]byte, int(size))
	if _, err := io.ReadFull(input, raw); err != nil {
		return nil, errors.New("GG_DAG_ARCHIVE_TRUNCATED")
	}
	return raw, nil
}

func archiveResult(execution *DagExecution, certificate dagArchiveCertificate, archiveHash, contentHash string) map[string]any {
	return map[string]any{"schema": "gg.dag.archive.result.v1", "verified": true,
		"verification_scope": "FULL_ORIGINAL_SIGNED_DAG_REPLAY_AND_PINNED_SDK_CERTIFICATE_NOT_NATIVE_TRANSFER_HISTORY_REPLAY",
		"archive_sha256":     archiveHash, "content_sha256": contentHash, "blocks_replayed": execution.Commitment.Blocks,
		"transactions_replayed": execution.Commitment.Transactions, "raw_payload_bytes": execution.bytes,
		"checkpoints_replayed": execution.Commitment.Checkpoint, "account_root": execution.Commitment.AccountRoot,
		"order_root": execution.Commitment.OrderRoot, "manifest_hash": execution.Commitment.ManifestHash,
		"certificate_height": certificate.State.Height + 1, "genesis_hash": certificate.GenesisHash,
		"network_id": execution.Source.NetworkID, "signing_keys_exported": false, "snapshot_trust_used": false}
}

// The archive's header never supplies its own trust. request.Genesis and the
// optional monotonic certificate floor come from the caller's owned pin.
func verifyDagPublicArchive(ctx context.Context, input io.Reader, request dagArchiveCommand) (result map[string]any, finalErr error) {
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	if validateGenesis(request.Genesis, request.GenesisHash) != nil || request.Genesis.DAG == nil {
		return nil, errors.New("GG_DAG_ARCHIVE_TRUST")
	}
	digest := sha256.New()
	hashed := io.TeeReader(io.LimitReader(input, dagArchiveMaxBytes+1), digest)
	var magic [8]byte
	if _, err := io.ReadFull(hashed, magic[:]); err != nil || string(magic[:]) != dagArchiveMagic {
		return nil, errors.New("GG_DAG_ARCHIVE_MAGIC")
	}
	raw, err := readArchiveFrame(hashed, 'H', dagArchiveHeaderLimit)
	var header dagArchiveHeader
	if err != nil || decodeStrict(raw, &header) != nil || !bytes.Equal(raw, canonical(header)) || header.Schema != "gg.dag.public-archive.v1" {
		return nil, errors.New("GG_DAG_ARCHIVE_HEADER")
	}
	if err = checkedArchiveCertificate(header.Certificate, request); err != nil {
		return nil, err
	}
	normalized, err := normalizedArchiveHeader(header.Certificate)
	if err != nil || !bytes.Equal(header.Certificate.SignedHeader, normalized) {
		return nil, errors.New("GG_DAG_ARCHIVE_HEADER_ENCODING")
	}
	expected := *header.Certificate.State.DAG
	execution, err := newDagExecution(*request.Genesis.DAG, request.GenesisHash)
	if err != nil {
		return nil, err
	}
	work, err := openDagArchiveWork(request.WorkRoot)
	if err != nil {
		return nil, err
	}
	defer func() {
		if work.close() != nil {
			result = nil
			finalErr = errDagArchiveWork
		}
	}()
	for checkpoint := uint64(1); checkpoint <= expected.Checkpoint; checkpoint++ {
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		raw, err = readArchiveFrame(hashed, 'M', dagManifestMaxBytes)
		if err != nil {
			return nil, err
		}
		manifest, manifestErr := checkedDagManifest(raw, dagDigest("GG-DAG-CHECKPOINT-MANIFEST-v1\x00", json.RawMessage(raw)),
			request.GenesisHash, dagDigest("GG-DAG-CONSENSUS-SOURCE-v1\x00", execution.Source))
		if manifestErr != nil || manifest.Checkpoint != checkpoint || manifest.Previous != execution.Commitment.ManifestHash {
			return nil, errors.New("GG_DAG_ARCHIVE_MANIFEST")
		}
		previous := execution.orderCount()
		next, err := replayDagManifest(execution, manifest, func(wanted string) ([]byte, error) {
			if ctx.Err() != nil {
				return nil, ctx.Err()
			}
			raw, err := readArchiveFrame(hashed, 'R', DagMaxWire)
			if err != nil || hashHex(raw) != wanted {
				return nil, errors.New("GG_DAG_ARCHIVE_PAYLOAD")
			}
			return raw, nil
		})
		if err != nil {
			return nil, err
		}
		if next.orderCount() <= previous || next.orderCount() > expected.Blocks {
			return nil, errors.New("GG_DAG_ARCHIVE_ORDER")
		}
		execution, err = work.archive(next)
		if err != nil {
			return nil, err
		}
	}
	if execution.Commitment != expected {
		return nil, errors.New("GG_DAG_ARCHIVE_EXECUTION_MISMATCH")
	}
	// The footer digest covers every preceding actual byte; the footer itself
	// is outside that digest. No extra concatenated stream/trailing bytes pass.
	contentHash := hex.EncodeToString(digest.Sum(nil))
	raw, err = readArchiveFrame(hashed, 'F', dagArchiveFooterLimit)
	var footer dagArchiveFooter
	if err != nil || decodeStrict(raw, &footer) != nil || !bytes.Equal(raw, canonical(footer)) ||
		footer != (dagArchiveFooter{ContentHash: contentHash, Blocks: expected.Blocks, Checkpoints: expected.Checkpoint,
			RawBytes: execution.bytes, Schema: "gg.dag.archive.footer.v1"}) {
		return nil, errors.New("GG_DAG_ARCHIVE_FOOTER")
	}
	var extra [1]byte
	if n, err := input.Read(extra[:]); n != 0 || err != io.EOF {
		return nil, errors.New("GG_DAG_ARCHIVE_TRAILING_DATA")
	}
	if err = work.close(); err != nil {
		return nil, err
	}
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	return archiveResult(execution, header.Certificate, hex.EncodeToString(digest.Sum(nil)), contentHash), nil
}

func exportDagPublicArchive(ctx context.Context, output io.Writer, store *dagStore, request dagArchiveCommand) (result map[string]any, finalErr error) {
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	if request.Certificate == nil || checkedArchiveCertificate(*request.Certificate, request) != nil {
		return nil, errors.New("GG_DAG_ARCHIVE_CERTIFICATE")
	}
	certificate := *request.Certificate
	normalized, err := normalizedArchiveHeader(certificate)
	if err != nil {
		return nil, err
	}
	certificate.SignedHeader = normalized
	if store.meta.PublicIndex != 2 || store.meta.HistoryIndex != 1 || store.meta.SelectionIndex != 1 ||
		store.anchor != request.GenesisHash || !bytes.Equal(canonical(store.source), canonical(*request.Genesis.DAG)) {
		return nil, errors.New("GG_DAG_ARCHIVE_INDEX_REQUIRED")
	}
	head, err := store.publicHead()
	if err != nil || head.Commitment != *certificate.State.DAG {
		return nil, errors.New("GG_DAG_ARCHIVE_HEAD_CHANGED")
	}
	work, err := openDagArchiveWork(request.WorkRoot)
	if err != nil {
		return nil, err
	}
	defer func() {
		if work.close() != nil {
			result = nil
			finalErr = errDagArchiveWork
		}
	}()
	store.openReplayScratch = func() (dagReplayScratch, error) { return work.replay, nil }
	digest := sha256.New()
	hashed := io.MultiWriter(output, digest)
	if n, err := hashed.Write([]byte(dagArchiveMagic)); err != nil || n != len(dagArchiveMagic) {
		return nil, errors.New("GG_DAG_ARCHIVE_WRITE")
	}
	if err = writeArchiveFrame(hashed, 'H', canonical(dagArchiveHeader{Certificate: certificate, Schema: "gg.dag.public-archive.v1"}), dagArchiveHeaderLimit); err != nil {
		return nil, err
	}
	execution, err := store.replayIndexedObserved(head.Commitment, func(manifest DagManifest) error {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		if err := writeArchiveFrame(hashed, 'M', canonical(manifest), dagManifestMaxBytes); err != nil {
			return err
		}
		for _, key := range manifest.Blocks {
			if ctx.Err() != nil {
				return ctx.Err()
			}
			raw, err := store.db.Get([]byte("r/"+key), nil)
			if err != nil || len(raw) == 0 || len(raw) > DagMaxWire || hashHex(raw) != key {
				return errors.New("GG_DAG_ARCHIVE_PAYLOAD")
			}
			if err = writeArchiveFrame(hashed, 'R', raw, DagMaxWire); err != nil {
				return err
			}
		}
		return nil
	})
	if err != nil {
		return nil, err
	}
	if err = work.close(); err != nil {
		return nil, err
	}
	contentHash := hex.EncodeToString(digest.Sum(nil))
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	footer := dagArchiveFooter{ContentHash: contentHash, Blocks: execution.Commitment.Blocks, Checkpoints: execution.Commitment.Checkpoint, RawBytes: execution.bytes, Schema: "gg.dag.archive.footer.v1"}
	if err = writeArchiveFrame(hashed, 'F', canonical(footer), dagArchiveFooterLimit); err != nil {
		return nil, err
	}
	return archiveResult(execution, certificate, hex.EncodeToString(digest.Sum(nil)), contentHash), nil
}

func pathWithinArchiveRoot(path, root string) bool {
	rel, err := filepath.Rel(root, path)
	return err == nil && (rel == "." || rel != ".." && !strings.HasPrefix(rel, ".."+string(filepath.Separator)))
}

func runDagArchiveCommand(mode string, raw []byte) (map[string]any, error) {
	var request dagArchiveCommand
	if len(raw) > 512*1024 || decodeStrictLimited(raw, &request, MaxBlockTxs, 64) != nil || !filepath.IsAbs(request.ArchivePath) ||
		!filepath.IsAbs(request.WorkRoot) || validateGenesis(request.Genesis, request.GenesisHash) != nil || !hasDagExecution(request.Genesis) {
		return nil, errors.New("GG_DAG_ARCHIVE_COMMAND")
	}
	segmented := request.Genesis.DAGSegmented != nil
	workRoot, err := filepath.EvalSymlinks(request.WorkRoot)
	if err != nil || !realArchiveDirectory(workRoot) {
		return nil, errDagArchiveWork
	}
	request.WorkRoot = workRoot
	if mode == "archive-verify" {
		if request.Root != "" || request.Certificate != nil {
			return nil, errors.New("GG_DAG_ARCHIVE_COMMAND")
		}
		info, err := os.Lstat(request.ArchivePath)
		if err != nil || !info.Mode().IsRegular() || info.Mode()&os.ModeSymlink != 0 || info.Size() <= 0 || !segmented && info.Size() > dagArchiveMaxBytes {
			return nil, errors.New("GG_DAG_ARCHIVE_FILE")
		}
		file, err := os.Open(request.ArchivePath)
		if err != nil {
			return nil, errors.New("GG_DAG_ARCHIVE_FILE")
		}
		defer file.Close()
		opened, err := file.Stat()
		if err != nil || !os.SameFile(info, opened) {
			return nil, errors.New("GG_DAG_ARCHIVE_FILE")
		}
		var result map[string]any
		var verifyErr error
		if segmented {
			result, verifyErr = verifyDagSegmentedPublicArchive(context.Background(), file, request)
		} else {
			result, verifyErr = verifyDagPublicArchive(context.Background(), file, request)
		}
		if closeErr := file.Close(); closeErr != nil {
			return nil, errors.New("GG_DAG_ARCHIVE_CLOSE")
		}
		return result, verifyErr
	}
	if mode != "archive-export" || request.Certificate == nil || !filepath.IsAbs(request.Root) {
		return nil, errors.New("GG_DAG_ARCHIVE_COMMAND")
	}
	root, err := filepath.EvalSymlinks(request.Root)
	if err != nil {
		return nil, errors.New("GG_DAG_ARCHIVE_SOURCE")
	}
	parent, err := filepath.EvalSymlinks(filepath.Dir(request.ArchivePath))
	if err != nil {
		return nil, errors.New("GG_DAG_ARCHIVE_DESTINATION")
	}
	destination := filepath.Join(parent, filepath.Base(request.ArchivePath))
	if pathWithinArchiveRoot(destination, root) || pathWithinArchiveRoot(workRoot, root) {
		return nil, errors.New("GG_DAG_ARCHIVE_SOURCE_WRITE_FORBIDDEN")
	}
	if err = checkedArchiveCertificate(*request.Certificate, request); err != nil {
		return nil, err
	}
	var closeSource func() error
	var export func(io.Writer) (map[string]any, error)
	if segmented {
		store, _, _, openErr := openDagSegmentStoreMode(request.Genesis, request.GenesisHash, root, false, true)
		if openErr != nil {
			return nil, errors.New("GG_DAG_ARCHIVE_SOURCE_BUSY_OR_INVALID")
		}
		closeSource = store.close
		export = func(output io.Writer) (map[string]any, error) {
			return exportDagSegmentedPublicArchive(context.Background(), output, store, request)
		}
	} else {
		store, openErr := openDagStore(*request.Genesis.DAG, request.GenesisHash, root, false, true)
		if openErr != nil {
			return nil, errors.New("GG_DAG_ARCHIVE_SOURCE_BUSY_OR_INVALID")
		}
		closeSource = store.close
		export = func(output io.Writer) (map[string]any, error) {
			return exportDagPublicArchive(context.Background(), output, store, request)
		}
	}
	defer closeSource()
	file, err := os.OpenFile(destination, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil {
		return nil, errors.New("GG_DAG_ARCHIVE_DESTINATION_EXISTS_OR_UNAVAILABLE")
	}
	created, statErr := file.Stat()
	complete := false
	defer func() {
		_ = file.Close()
		if !complete && statErr == nil {
			if current, err := os.Lstat(destination); err == nil && os.SameFile(created, current) {
				_ = os.Remove(destination)
			}
		}
	}()
	if statErr != nil {
		return nil, errors.New("GG_DAG_ARCHIVE_DESTINATION")
	}
	result, exportErr := export(file)
	if exportErr != nil {
		return nil, exportErr
	}
	if file.Sync() != nil || file.Close() != nil {
		return nil, errors.New("GG_DAG_ARCHIVE_CLOSE")
	}
	if closeSource() != nil {
		return nil, errors.New("GG_DAG_ARCHIVE_SOURCE_CLOSE")
	}
	complete = true
	return result, nil
}
