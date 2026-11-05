//go:build !js

package main

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
	"testing"

	cmtjson "github.com/cometbft/cometbft/libs/json"
	"github.com/cometbft/cometbft/types"
)

func publicArchiveFixture(t *testing.T, counts ...int) (dagArchiveCommand, *dagStore) {
	t.Helper()
	app, keys, root := dagLedgerFixture(t)
	for index, count := range counts {
		commitPublicFixture(t, app, keys, index%6, count)
	}
	_, _, _, validators := testGenesis()
	signed := signedFixture(app.genesis, validators, app.state.Height+1, app.state.StateRoot, nil, types.BlockID{})
	header, err := cmtjson.Marshal(signed)
	if err != nil {
		t.Fatal(err)
	}
	certificate := dagArchiveCertificate{Genesis: app.genesis, GenesisHash: app.anchor, Schema: "gg.consensus.proof.v1", SignedHeader: header, State: copyState(app.state)}
	if err = app.Close(); err != nil {
		t.Fatal(err)
	}
	store, err := openDagStore(*app.genesis.DAG, app.anchor, root, false, true)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = store.close() })
	return dagArchiveCommand{ArchivePath: filepath.Join(t.TempDir(), "history.ggdag"), Certificate: &certificate,
		Genesis: app.genesis, GenesisHash: app.anchor, Root: root, WorkRoot: t.TempDir()}, store
}

func archiveBytes(t *testing.T, counts ...int) ([]byte, dagArchiveCommand, map[string]any) {
	t.Helper()
	request, store := publicArchiveFixture(t, counts...)
	before := indexedReplayImage(t, store.db)
	var output bytes.Buffer
	result, err := exportDagPublicArchive(context.Background(), &output, store, request)
	if err != nil || result["verified"] != true {
		t.Fatal("archive export", err)
	}
	if indexedReplayImage(t, store.db) != before {
		t.Fatal("archive export changed original database")
	}
	request.WorkRoot = t.TempDir()
	return output.Bytes(), request, result
}

func TestDagPublicArchiveActualSignedPayloadReplayMatchesOriginalAccountsOrderAndFileHash(t *testing.T) {
	raw, request, exported := archiveBytes(t, 5000, 257, 3)
	result, err := verifyDagPublicArchive(context.Background(), bytes.NewReader(raw), request)
	if err != nil || !bytes.Equal(canonical(result), canonical(exported)) {
		t.Fatal("portable signed replay differs from original", err)
	}
	expected := sha256.Sum256(raw)
	if result["archive_sha256"] != hex.EncodeToString(expected[:]) || result["blocks_replayed"] != 3 || result["transactions_replayed"] != uint64(5260) {
		t.Fatal("archive byte identity or actual unique signed work count changed")
	}
	if result["signing_keys_exported"] != false || result["snapshot_trust_used"] != false {
		t.Fatal("false archive scope")
	}
}

func TestDagPublicArchiveEmptyCertifiedGenesisStillRequiresValidHeaderAndFooter(t *testing.T) {
	raw, request, exported := archiveBytes(t)
	result, err := verifyDagPublicArchive(context.Background(), bytes.NewReader(raw), request)
	if err != nil || result["blocks_replayed"] != 0 || !bytes.Equal(canonical(result), canonical(exported)) {
		t.Fatal(err)
	}
	for _, invalid := range [][]byte{nil, raw[:8], raw[:len(raw)-1], append(append([]byte(nil), raw...), 0)} {
		if result, err = verifyDagPublicArchive(context.Background(), bytes.NewReader(invalid), request); result != nil || err == nil {
			t.Fatal("partial/extended genesis archive passed")
		}
	}
}

type archiveTestFrame struct {
	kind byte
	raw  []byte
}

func archiveTestFrames(t *testing.T, raw []byte) []archiveTestFrame {
	t.Helper()
	frames := []archiveTestFrame{}
	position := len(dagArchiveMagic)
	for position < len(raw) {
		if position+5 > len(raw) {
			t.Fatal("fixture frame")
		}
		size := int(binary.BigEndian.Uint32(raw[position+1 : position+5]))
		end := position + 5 + size
		if end > len(raw) {
			t.Fatal("fixture frame bounds")
		}
		frames = append(frames, archiveTestFrame{raw[position], append([]byte(nil), raw[position+5:end]...)})
		position = end
	}
	return frames
}
func changedArchiveBytes(t *testing.T, frames []archiveTestFrame) []byte {
	t.Helper()
	var output bytes.Buffer
	output.WriteString(dagArchiveMagic)
	for _, frame := range frames {
		if frame.kind == 'F' {
			var footer dagArchiveFooter
			if decodeStrict(frame.raw, &footer) != nil {
				t.Fatal("fixture footer")
			}
			footer.ContentHash = hashHex(output.Bytes())
			frame.raw = canonical(footer)
		}
		if err := writeArchiveFrame(&output, frame.kind, frame.raw, DagMaxWire); err != nil {
			t.Fatal(err)
		}
	}
	return output.Bytes()
}

func TestDagPublicArchiveSelfRehashedPayloadManifestAndOrderMutationsNeverPass(t *testing.T) {
	raw, request, _ := archiveBytes(t, 3, 2)
	for _, mode := range []string{"payload", "manifest_time_zero", "manifest_previous", "manifest_source", "omit_record", "swap_records", "footer_count"} {
		t.Run(mode, func(t *testing.T) {
			frames := archiveTestFrames(t, raw)
			switch mode {
			case "payload":
				frames[2].raw[len(frames[2].raw)-3] ^= 1
			case "manifest_time_zero", "manifest_previous", "manifest_source":
				var value DagManifest
				if decodeStrict(frames[1].raw, &value) != nil {
					t.Fatal("fixture manifest")
				}
				if mode == "manifest_time_zero" {
					value.TimeNs = "0"
				} else if mode == "manifest_previous" {
					value.Previous = DagZero
				} else {
					value.SourceHash = strings.Repeat("e", 64)
				}
				frames[1].raw = canonical(value)
			case "omit_record":
				frames = append(frames[:2], frames[3:]...)
			case "swap_records":
				frames[2], frames[4] = frames[4], frames[2]
			case "footer_count":
				var value dagArchiveFooter
				if decodeStrict(frames[len(frames)-1].raw, &value) != nil {
					t.Fatal("fixture footer")
				}
				value.Blocks++
				frames[len(frames)-1].raw = canonical(value)
			}
			changed := changedArchiveBytes(t, frames)
			result, err := verifyDagPublicArchive(context.Background(), bytes.NewReader(changed), request)
			if result != nil || err == nil {
				t.Fatal("mutated archive self-checksum became authority")
			}
		})
	}
}

func TestDagPublicArchivePinnedTrustCertificateAndMonotonicFloorAreRequired(t *testing.T) {
	raw, request, _ := archiveBytes(t, 1)
	for _, mode := range []string{"foreign_anchor", "old_height", "same_height_conflict", "bad_quorum"} {
		t.Run(mode, func(t *testing.T) {
			changed := request
			data := raw
			switch mode {
			case "foreign_anchor":
				changed.GenesisHash = strings.Repeat("e", 64)
			case "old_height":
				changed.MinimumCertificateHeight = request.Certificate.State.Height + 2
			case "same_height_conflict":
				changed.MinimumCertificateHeight = request.Certificate.State.Height + 1
				changed.MinimumCertificateBlock = strings.Repeat("f", 64)
			case "bad_quorum":
				frames := archiveTestFrames(t, raw)
				var header dagArchiveHeader
				if decodeStrict(frames[0].raw, &header) != nil {
					t.Fatal("fixture header")
				}
				header.Certificate.SignedHeader = json.RawMessage(`{}`)
				frames[0].raw = canonical(header)
				data = changedArchiveBytes(t, frames)
			}
			if result, err := verifyDagPublicArchive(context.Background(), bytes.NewReader(data), changed); result != nil || err == nil {
				t.Fatal("untrusted/stale certificate passed")
			}
		})
	}
}

func TestDagPublicArchiveFrameLimitsRejectBeforeReadingDeclaredHugePayload(t *testing.T) {
	for _, kind := range []byte{'H', 'M', 'R', 'F'} {
		raw := []byte{kind, 255, 255, 255, 255, 1, 2, 3}
		reader := bytes.NewReader(raw)
		if _, err := readArchiveFrame(reader, kind, 1024); err == nil || reader.Len() != 3 {
			t.Fatal("oversized frame read or allocated untrusted payload")
		}
	}
}

type failingArchiveWriter struct{ remaining int }

func (writer *failingArchiveWriter) Write(raw []byte) (int, error) {
	if writer.remaining <= 0 {
		return 0, errors.New("owned writer failure")
	}
	if len(raw) > writer.remaining {
		n := writer.remaining
		writer.remaining = 0
		return n, nil
	}
	writer.remaining -= len(raw)
	return len(raw), nil
}

func TestDagPublicArchiveOutputFailureNeverPublishesReadyPrefixAndCanRetryExactSource(t *testing.T) {
	request, store := publicArchiveFixture(t, 2, 3)
	before := indexedReplayImage(t, store.db)
	writer := &failingArchiveWriter{remaining: len(dagArchiveMagic) + dagArchiveHeaderLimit}
	// Force a short write in the first raw payload, after the header/manifest.
	writer.remaining = len(dagArchiveMagic) + 5 + len(canonical(dagArchiveHeader{Certificate: *request.Certificate, Schema: "gg.dag.public-archive.v1"})) + 600
	if result, err := exportDagPublicArchive(context.Background(), writer, store, request); result != nil || err == nil || store.retentionReady {
		t.Fatal("failed archive sink published a complete replay/receipt")
	}
	if indexedReplayImage(t, store.db) != before {
		t.Fatal("archive sink failure changed source database")
	}
	var retry bytes.Buffer
	if _, err := exportDagPublicArchive(context.Background(), &retry, store, request); err != nil {
		t.Fatal("archive failure could not retry exact source", err)
	}
}

func TestDagPublicArchiveWorkspaceLeaseRejectsOverlapAndReclaimsOnlyOwnedAbandonment(t *testing.T) {
	root := t.TempDir()
	first, err := openDagArchiveWork(root)
	if err != nil {
		t.Fatal(err)
	}
	if second, err := openDagArchiveWork(root); err == nil || second != nil {
		t.Fatal("concurrent archive workspace accepted")
	}
	if err = first.replay.db.Close(); err != nil {
		t.Fatal(err)
	}
	first.replay.db = nil
	if err = first.lease.Close(); err != nil {
		t.Fatal(err)
	}
	first.lease = nil
	first.closed = true // simulated process exit; owned files remain
	recovered, err := openDagArchiveWork(root)
	if err != nil {
		t.Fatal("owned abandoned work did not recover", err)
	}
	if err = recovered.close(); err != nil {
		t.Fatal(err)
	}
	unknown := filepath.Join(root, "gg-dag-archive-work", "lease", "OWNER")
	if err = os.WriteFile(unknown, []byte("foreign marker"), 0600); err != nil {
		t.Fatal(err)
	}
	if value, err := openDagArchiveWork(root); err == nil || value != nil {
		t.Fatal("unknown workspace marker accepted")
	}
	actual, _ := os.ReadFile(unknown)
	if string(actual) != "foreign marker" {
		t.Fatal("unknown marker was repaired or deleted")
	}
}

func TestDagPublicArchiveCommandNoOverwriteNoSourceWritesAndActualFileRoundtrip(t *testing.T) {
	request, store := publicArchiveFixture(t, 3)
	if err := store.close(); err != nil {
		t.Fatal(err)
	}
	result, err := runDagArchiveCommand("archive-export", canonical(request))
	if err != nil || result["verified"] != true {
		t.Fatal("native archive command export", err)
	}
	raw, err := os.ReadFile(request.ArchivePath)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = runDagArchiveCommand("archive-export", canonical(request)); err == nil {
		t.Fatal("archive command overwrote an existing output")
	}
	after, _ := os.ReadFile(request.ArchivePath)
	if !bytes.Equal(raw, after) {
		t.Fatal("existing archive changed")
	}
	verification := request
	verification.Root = ""
	verification.Certificate = nil
	verified, err := runDagArchiveCommand("archive-verify", canonical(verification))
	if err != nil || !bytes.Equal(canonical(verified), canonical(result)) {
		t.Fatal("native archive command verify", err)
	}
	inside := request
	inside.ArchivePath = filepath.Join(request.Root, "forbidden.ggdag")
	if _, err = runDagArchiveCommand("archive-export", canonical(inside)); err == nil {
		t.Fatal("export created output in source profile")
	}
	if _, err = os.Lstat(inside.ArchivePath); !os.IsNotExist(err) {
		t.Fatal("forbidden source output exists")
	}
}

func TestDagPublicArchiveCancellationAndMissingFooterNeverYieldVerifiedReceipt(t *testing.T) {
	raw, request, _ := archiveBytes(t, 3)
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if result, err := verifyDagPublicArchive(ctx, bytes.NewReader(raw), request); result != nil || err == nil {
		t.Fatal("cancelled archive replay passed")
	}
	empty, emptyRequest, _ := archiveBytes(t)
	if result, err := verifyDagPublicArchive(ctx, bytes.NewReader(empty), emptyRequest); result != nil || err == nil {
		t.Fatal("cancelled empty archive passed")
	}
	frames := archiveTestFrames(t, raw)
	frames = frames[:len(frames)-1]
	missing := changedArchiveBytes(t, frames)
	if result, err := verifyDagPublicArchive(context.Background(), io.LimitReader(bytes.NewReader(missing), int64(len(missing))), request); result != nil || err == nil {
		t.Fatal("missing footer passed")
	}
}

func TestDagPublicArchiveExactPinnedCertificateFloorAndBlockRemainValid(t *testing.T) {
	raw, request, _ := archiveBytes(t, 1)
	header, err := verifyHeader(request.Certificate.SignedHeader, request.Genesis)
	if err != nil {
		t.Fatal(err)
	}
	request.MinimumCertificateHeight = header.Height
	request.MinimumCertificateBlock = strings.ToLower(header.Commit.BlockID.Hash.String())
	if result, err := verifyDagPublicArchive(context.Background(), bytes.NewReader(raw), request); err != nil || result["verified"] != true {
		t.Fatal("exact certificate floor failed", err)
	}
	request.MinimumCertificateHeight = 0
	if result, err := verifyDagPublicArchive(context.Background(), bytes.NewReader(raw), request); result != nil || err == nil {
		t.Fatal("block-only floor was silently ignored")
	}
}

func TestDagPublicArchiveExportCannotOpenAnActiveSourceWriter(t *testing.T) {
	request, store := publicArchiveFixture(t, 1)
	if err := store.close(); err != nil {
		t.Fatal(err)
	}
	active, err := newDagEnabledLedger(request.Genesis, request.GenesisHash, request.Root, false)
	if err != nil {
		t.Fatal(err)
	}
	defer active.Close()
	if result, err := runDagArchiveCommand("archive-export", canonical(request)); result != nil || err == nil {
		t.Fatal("read-only export overlapped the actual exclusive source writer")
	}
	if _, err = os.Lstat(request.ArchivePath); !os.IsNotExist(err) {
		t.Fatal("busy source created an archive output")
	}
}

func TestDagPublicArchiveExportNeverCopiesOpaqueHeaderExtensions(t *testing.T) {
	request, store := publicArchiveFixture(t, 1)
	certificate := *request.Certificate
	var header map[string]json.RawMessage
	if json.Unmarshal(certificate.SignedHeader, &header) != nil {
		t.Fatal("fixture header")
	}
	marker := "UNRECOGNIZED_OPAQUE_EXTENSION_MUST_NOT_BE_EXPORTED"
	header["unexpected_extension"] = canonical(marker)
	raw, err := json.Marshal(header)
	if err != nil {
		t.Fatal(err)
	}
	certificate.SignedHeader = raw
	request.Certificate = &certificate
	var output bytes.Buffer
	result, err := exportDagPublicArchive(context.Background(), &output, store, request)
	if err != nil {
		if result != nil || output.Len() != 0 {
			t.Fatal("rejected header extension left exported content")
		}
		return
	}
	if bytes.Contains(output.Bytes(), []byte(marker)) {
		t.Fatal("unrecognized opaque header content was copied")
	}
	request.WorkRoot = t.TempDir()
	verified, err := verifyDagPublicArchive(context.Background(), bytes.NewReader(output.Bytes()), request)
	if err != nil || !bytes.Equal(canonical(verified), canonical(result)) {
		t.Fatal("normalized SDK header no longer verifies", err)
	}
}

func TestDagPublicArchiveWorkspaceUnknownOrOversizedMetadataNeverBecomesOwned(t *testing.T) {
	for _, mode := range []string{"oversized_owner", "unknown_guard_file", "unknown_parent_file", "foreign_log_without_owner"} {
		t.Run(mode, func(t *testing.T) {
			root := t.TempDir()
			work, err := openDagArchiveWork(root)
			if err != nil {
				t.Fatal(err)
			}
			if err = work.close(); err != nil {
				t.Fatal(err)
			}
			parent := filepath.Join(root, "gg-dag-archive-work")
			guard := filepath.Join(parent, "lease")
			var target string
			payload := []byte("foreign data")
			switch mode {
			case "oversized_owner":
				target = filepath.Join(guard, "OWNER")
				payload = bytes.Repeat([]byte("x"), 4096)
			case "unknown_guard_file":
				target = filepath.Join(guard, "FOREIGN")
			case "unknown_parent_file":
				target = filepath.Join(parent, "FOREIGN")
			case "foreign_log_without_owner":
				if err = os.Remove(filepath.Join(guard, "OWNER")); err != nil {
					t.Fatal(err)
				}
				target = filepath.Join(guard, "LOG")
			}
			if err = os.WriteFile(target, payload, 0600); err != nil {
				t.Fatal(err)
			}
			if value, err := openDagArchiveWork(root); value != nil || err == nil {
				t.Fatal("unknown metadata was claimed as owned")
			}
			actual, err := os.ReadFile(target)
			if err != nil || !bytes.Equal(actual, payload) {
				t.Fatal("foreign metadata changed")
			}
		})
	}
}
