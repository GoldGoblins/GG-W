//go:build !js

package main

import (
	"bytes"
	"context"
	"encoding/binary"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"

	cmtjson "github.com/cometbft/cometbft/libs/json"
	"github.com/cometbft/cometbft/types"
)

func segmentedArchiveDirectoryImage(t *testing.T, root string) string {
	t.Helper()
	var image bytes.Buffer
	err := filepath.Walk(root, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if info.Mode().IsRegular() {
			raw, err := os.ReadFile(path)
			if err != nil {
				return err
			}
			rel, _ := filepath.Rel(root, path)
			image.WriteString(rel + ":" + hashHex(raw) + "\n")
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	return hashHex(image.Bytes())
}

func segmentedPublicArchiveFixture(t *testing.T, counts ...int) (dagArchiveCommand, *dagSegmentStore) {
	t.Helper()
	app, backend, keys, root := segmentedSDKFixture(t)
	for index, count := range counts {
		commitSegmentedSDK(t, app, segmentedBatch(t, backend.current.active, segmentedWire(t, backend.current.active, keys, index%6, count)))
		if index < len(counts)-1 {
			cut, err := backend.current.cutTransaction()
			if err != nil {
				t.Fatal(err)
			}
			commitSegmentedSDK(t, app, canonical(cut))
		}
	}
	packet := segmentedSDKPacket(t, app)
	certificate := dagArchiveCertificate{Genesis: app.genesis, GenesisHash: app.anchor, Schema: packet.Schema, State: packet.State, SignedHeader: packet.SignedHeader}
	return dagArchiveCommand{ArchivePath: filepath.Join(t.TempDir(), "history.ggdag"), Certificate: &certificate,
		Genesis: app.genesis, GenesisHash: app.anchor, Root: root, WorkRoot: t.TempDir()}, backend.store
}

func segmentedPublicArchiveBytes(t *testing.T, counts ...int) ([]byte, dagArchiveCommand, map[string]any) {
	t.Helper()
	request, store := segmentedPublicArchiveFixture(t, counts...)
	before := indexedReplayImage(t, store.db)
	var output bytes.Buffer
	result, err := exportDagSegmentedPublicArchive(context.Background(), &output, store, request)
	if err != nil || result == nil || result["verified"] != true || indexedReplayImage(t, store.db) != before {
		t.Fatal("original source changed or archive failed", err)
	}
	return output.Bytes(), request, result
}

func segmentedPublicTestEncode(t *testing.T, frames []archiveTestFrame) []byte {
	t.Helper()
	var output bytes.Buffer
	output.WriteString(dagSegmentedPublicMagic)
	for _, frame := range frames {
		if frame.kind == 'F' {
			var footer dagSegmentedPublicFooter
			if decodeStrict(frame.raw, &footer) != nil {
				t.Fatal("fixture")
			}
			footer.ContentHash = hashHex(output.Bytes())
			frame.raw = canonical(footer)
		}
		if err := writeArchiveFrame(&output, frame.kind, frame.raw, int(dagSegmentArchiveMaxBytes)); err != nil {
			t.Fatal(err)
		}
	}
	return output.Bytes()
}

func TestDagSegmentedPublicArchiveFullOriginalChainActiveTailAndDerivedAccounts(t *testing.T) {
	raw, request, exported := segmentedPublicArchiveBytes(t, 5000, 257, 3)
	result, err := verifyDagSegmentedPublicArchive(context.Background(), bytes.NewReader(raw), request)
	if err != nil || !bytes.Equal(canonical(result), canonical(exported)) {
		t.Fatal("portable independent replay differs from SDK state", err)
	}
	state := result["commitment"].(dagSegmentedState)
	base := result["segment_base"].(map[string]any)["commitment"].(dagSegmentedState)
	if state.Transactions != 5260 || state.Blocks != 3 || state.Epoch != 3 || state.Active.Blocks != 1 ||
		base.Epoch != 3 || base.Active.Blocks != 0 || base.Transactions != 5257 || base.Authors[0].Nonce != "5000" || base.Authors[1].Nonce != "257" ||
		result["archive_sha256"] != hashHex(raw) || result["history_replayed"] != true || result["snapshot_trust_used"] != false ||
		result["signing_keys_exported"] != false || result["verification_scope"] != dagSegmentedPublicScope {
		t.Fatal("false history, counter, nonce or verification scope")
	}
	if path := os.Getenv("GG_PUBLIC_SEGMENTED_ARCHIVE_FIXTURE"); path != "" {
		if err := os.WriteFile(path, raw, 0600); err != nil {
			t.Fatal(err)
		}
		pin := map[string]any{"genesis": request.Genesis, "genesis_hash": request.GenesisHash}
		if err := os.WriteFile(path+".pin.json", canonical(pin), 0600); err != nil {
			t.Fatal(err)
		}
	}
}

func TestDagSegmentedPublicArchiveRejectsRehashedOmissionsReorderingCorruptionAndSnapshot(t *testing.T) {
	raw, request, _ := segmentedPublicArchiveBytes(t, 3, 7, 2)
	for _, kind := range []string{"missing_segment", "reordered_segments", "duplicate_segment", "closed_signature", "closed_footer", "active_payload", "active_manifest", "snapshot_frame", "outer_footer", "wrong_magic", "truncated", "trailing"} {
		t.Run(kind, func(t *testing.T) {
			frames := archiveTestFrames(t, raw)
			switch kind {
			case "missing_segment":
				frames = append(frames[:1], frames[2:]...)
			case "reordered_segments":
				frames[1], frames[2] = frames[2], frames[1]
			case "duplicate_segment":
				frames[2] = frames[1]
			case "closed_signature":
				segments := segmentTestFrames(t, frames[1].raw)
				for i := range segments {
					if segments[i].kind == 'R' {
						segments[i].raw[len(segments[i].raw)-3] ^= 1
						break
					}
				}
				frames[1].raw = segmentTestEncode(t, segments)
			case "closed_footer":
				frames[1].raw[len(frames[1].raw)-3] ^= 1
			case "active_payload":
				for i := range frames {
					if frames[i].kind == 'R' {
						frames[i].raw[len(frames[i].raw)-3] ^= 1
						break
					}
				}
			case "active_manifest":
				for i := range frames {
					if frames[i].kind == 'M' {
						var manifest DagManifest
						if decodeStrict(frames[i].raw, &manifest) != nil {
							t.Fatal("fixture")
						}
						manifest.Previous = DagZero
						frames[i].raw = canonical(manifest)
						break
					}
				}
			case "snapshot_frame":
				frames[1] = archiveTestFrame{'A', canonical(map[string]any{"accounts": request.Certificate.State.DAGSegmented.Authors})}
			case "outer_footer":
				var footer dagSegmentedPublicFooter
				if decodeStrict(frames[len(frames)-1].raw, &footer) != nil {
					t.Fatal("fixture")
				}
				footer.Blocks++
				frames[len(frames)-1].raw = canonical(footer)
			}
			changed := segmentedPublicTestEncode(t, frames)
			if kind == "wrong_magic" {
				changed[7] = '1'
			} else if kind == "truncated" {
				changed = changed[:len(changed)-1]
			} else if kind == "trailing" {
				changed = append(changed, 0)
			}
			if result, err := verifyDagSegmentedPublicArchive(context.Background(), bytes.NewReader(changed), request); result != nil || err == nil {
				t.Fatal("rehashed invalid archive published a receipt")
			}
		})
	}
}

func TestDagSegmentedPublicArchivePinnedTrustSDKQuorumAndMonotonicFloor(t *testing.T) {
	raw, original, _ := segmentedPublicArchiveBytes(t, 2, 3)
	for _, kind := range []string{"pin", "future_floor", "same_height_conflict", "zero_height_floor", "self_signed_header", "two_votes", "account_snapshot"} {
		t.Run(kind, func(t *testing.T) {
			request := original
			frames := archiveTestFrames(t, raw)
			switch kind {
			case "pin":
				request.GenesisHash = strings.Repeat("f", 64)
			case "future_floor":
				request.MinimumCertificateHeight = original.Certificate.State.Height + 2
			case "same_height_conflict":
				request.MinimumCertificateHeight = original.Certificate.State.Height + 1
				request.MinimumCertificateBlock = strings.Repeat("f", 64)
			case "zero_height_floor":
				request.MinimumCertificateBlock = strings.Repeat("f", 64)
			default:
				var header dagArchiveHeader
				if decodeStrict(frames[0].raw, &header) != nil {
					t.Fatal("fixture")
				}
				if kind == "self_signed_header" {
					header.Certificate.SignedHeader = json.RawMessage(`{}`)
				} else if kind == "two_votes" {
					var signed types.SignedHeader
					if cmtjson.Unmarshal(header.Certificate.SignedHeader, &signed) != nil {
						t.Fatal("fixture")
					}
					for index := 2; index < 4; index++ {
						signed.Commit.Signatures[index] = types.NewCommitSigAbsent()
					}
					header.Certificate.SignedHeader, _ = cmtjson.Marshal(signed)
				} else {
					header.Certificate.State.DAGSegmented.Authors[0].Nonce = "0"
				}
				frames[0].raw = canonical(header)
			}
			if result, err := verifyDagSegmentedPublicArchive(context.Background(), bytes.NewReader(segmentedPublicTestEncode(t, frames)), request); result != nil || err == nil {
				t.Fatal("unpinned, conflicting or fake certificate passed")
			}
		})
	}
	header, err := verifyHeader(original.Certificate.SignedHeader, original.Genesis)
	if err != nil {
		t.Fatal(err)
	}
	original.MinimumCertificateHeight = header.Height
	original.MinimumCertificateBlock = strings.ToLower(header.Commit.BlockID.Hash.String())
	if _, err := verifyDagSegmentedPublicArchive(context.Background(), bytes.NewReader(raw), original); err != nil {
		t.Fatal("exact floor rejected", err)
	}
}

func TestDagSegmentedPublicArchiveEmptyGenesisAndSelectedEmptyCutRequireCompleteEOF(t *testing.T) {
	for _, counts := range [][]int{nil, {0}} {
		raw, request, exported := segmentedPublicArchiveBytes(t, counts...)
		if result, err := verifyDagSegmentedPublicArchive(context.Background(), bytes.NewReader(raw), request); err != nil || !bytes.Equal(canonical(result), canonical(exported)) {
			t.Fatal("empty certified state", err)
		}
		for _, bad := range [][]byte{nil, raw[:8], raw[:len(raw)-1], append(append([]byte(nil), raw...), 0)} {
			if result, err := verifyDagSegmentedPublicArchive(context.Background(), bytes.NewReader(bad), request); err == nil || result != nil {
				t.Fatal("partial empty history accepted")
			}
		}
	}
	app, backend, keys, root := segmentedSDKFixture(t)
	commitSegmentedSDK(t, app, segmentedBatch(t, backend.current.active, segmentedWire(t, backend.current.active, keys, 0, 2)))
	cut, _ := backend.current.cutTransaction()
	commitSegmentedSDK(t, app, canonical(cut))
	packet := segmentedSDKPacket(t, app)
	certificate := dagArchiveCertificate{Genesis: app.genesis, GenesisHash: app.anchor, State: packet.State, SignedHeader: packet.SignedHeader, Schema: packet.Schema}
	emptyRequest := dagArchiveCommand{Genesis: app.genesis, GenesisHash: app.anchor, Root: root, WorkRoot: t.TempDir(), Certificate: &certificate}
	var empty bytes.Buffer
	exported, err := exportDagSegmentedPublicArchive(context.Background(), &empty, backend.store, emptyRequest)
	if err != nil {
		t.Fatal("selected empty cut export", err)
	}
	verified, err := verifyDagSegmentedPublicArchive(context.Background(), bytes.NewReader(empty.Bytes()), emptyRequest)
	if err != nil || !bytes.Equal(canonical(verified), canonical(exported)) || verified["commitment"].(dagSegmentedState).Active.Blocks != 0 {
		t.Fatal("selected empty cut replay", err)
	}
	request, store := segmentedPublicArchiveFixture(t, 2)
	current := store.selected
	// Complete the SDK-selected cut, leaving no new active proposals.
	plan, err := current.prepareCut()
	if err != nil {
		t.Fatal(err)
	}
	if plan.next.active.orderCount() != 0 {
		t.Fatal("fixture")
	}
	// A merely prepared empty successor cannot be exported under the old SDK pin.
	store.selected = plan.next
	defer func() { store.selected = current }()
	var output bytes.Buffer
	if result, err := exportDagSegmentedPublicArchive(context.Background(), &output, store, request); err == nil || result != nil || output.Len() != 0 {
		t.Fatal("uncertified prepared successor exposed as selected")
	}
}

func TestDagSegmentedPublicArchiveNestedFrameBudgetAndCancellation(t *testing.T) {
	raw, request, _ := segmentedPublicArchiveBytes(t, 3, 2)
	frames := archiveTestFrames(t, raw)
	var prefix bytes.Buffer
	prefix.WriteString(dagSegmentedPublicMagic)
	if err := writeArchiveFrame(&prefix, 'H', frames[0].raw, dagArchiveHeaderLimit); err != nil {
		t.Fatal(err)
	}
	oversized := [5]byte{'S'}
	binary.BigEndian.PutUint32(oversized[1:], uint32(dagSegmentArchiveMaxBytes+1))
	prefix.Write(oversized[:])
	if result, err := verifyDagSegmentedPublicArchive(context.Background(), bytes.NewReader(prefix.Bytes()), request); err == nil || result != nil {
		t.Fatal("oversized nested frame accepted")
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if result, err := verifyDagSegmentedPublicArchive(ctx, bytes.NewReader(raw), request); err == nil || result != nil {
		t.Fatal("cancelled replay returned receipt")
	}
	writer := &failingArchiveWriter{remaining: 500}
	request, store := segmentedPublicArchiveFixture(t, 2, 1)
	if result, err := exportDagSegmentedPublicArchive(context.Background(), writer, store, request); err == nil || result != nil {
		t.Fatal("partial output returned receipt")
	}
}

func TestDagSegmentedPublicArchiveCommandReadOnlyExclusiveAndNoOverwrite(t *testing.T) {
	request, store := segmentedPublicArchiveFixture(t, 2, 3)
	if result, err := runDagArchiveCommand("archive-export", canonical(request)); err == nil || result != nil {
		t.Fatal("running writer lease was bypassed")
	}
	if err := store.close(); err != nil {
		t.Fatal(err)
	}
	before := segmentedArchiveDirectoryImage(t, request.Root)
	exported, err := runDagArchiveCommand("archive-export", canonical(request))
	if err != nil || exported["verified"] != true || segmentedArchiveDirectoryImage(t, request.Root) != before {
		t.Fatal("export changed original files", err)
	}
	if result, err := runDagArchiveCommand("archive-export", canonical(request)); err == nil || result != nil {
		t.Fatal("existing destination overwritten")
	}
	verify := request
	verify.Certificate, verify.Root = nil, ""
	result, err := runDagArchiveCommand("archive-verify", canonical(verify))
	if err != nil || !bytes.Equal(canonical(result), canonical(exported)) {
		t.Fatal("command roundtrip", err)
	}
	for _, target := range []string{filepath.Join(request.Root, "forbidden.ggdag"), filepath.Join(request.Root, "gg-dag-segmented.leveldb", "forbidden.ggdag")} {
		bad := request
		bad.ArchivePath = target
		if result, err := runDagArchiveCommand("archive-export", canonical(bad)); err == nil || result != nil {
			t.Fatal("export wrote inside source")
		}
	}
	file, err := os.Open(request.ArchivePath)
	if err != nil {
		t.Fatal(err)
	}
	defer file.Close()
	if _, err = file.Seek(0, io.SeekStart); err != nil {
		t.Fatal(err)
	}
}
