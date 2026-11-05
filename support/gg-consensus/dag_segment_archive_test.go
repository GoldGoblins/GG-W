//go:build !js

package main

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"errors"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"testing"
)

func segmentArchiveFixture(t *testing.T, count int) (*dagSegmentedExecution, *dagSegmentedExecution) {
	t.Helper()
	base, keys := segmentedFixture(t)
	first, err := base.apply(segmentedBatch(t, base.active, segmentedWire(t, base.active, keys, 0, count)), 1700000002000000000)
	if err != nil {
		t.Fatal(err)
	}
	return base, first
}

func segmentArchiveBytes(t *testing.T, current *dagSegmentedExecution) []byte {
	t.Helper()
	var output bytes.Buffer
	if err := writeDagHistorySegment(context.Background(), &output, current); err != nil {
		t.Fatal(err)
	}
	return output.Bytes()
}

func TestDagSegmentArchiveOriginalTenThousandTXReplayAcrossDurableFiles(t *testing.T) {
	base, first := segmentArchiveFixture(t, 5000)
	root := t.TempDir()
	receipt, err := persistDagHistorySegment(context.Background(), root, first)
	if err != nil {
		t.Fatal(err)
	}
	next, err := receipt.successor(first)
	if err != nil || next.active.orderCount() != 0 || next.active.nonces[0] != 5000 || next.startBase == nil ||
		next.startBase.startBase != nil || next.active.payloadReader != nil || len(next.active.pending) != 0 {
		t.Fatal("invalid carried base", err)
	}
	_, keys := segmentedFixture(t)
	second, err := next.apply(segmentedBatch(t, next.active, segmentedWire(t, next.active, keys, 0, 5000)), 1700000003000000000)
	if err != nil {
		t.Fatal(err)
	}
	secondReceipt, err := persistDagHistorySegment(context.Background(), root, second)
	if err != nil {
		t.Fatal(err)
	}
	// Independently reopen and replay the complete chain from the pinned genesis
	// base; do not use a stored intermediate account snapshot as authority.
	cursor := base
	for _, item := range []*dagSegmentArchiveReceipt{receipt, secondReceipt} {
		path := filepath.Join(root, "gg-dag-segments", item.replay.plan.hash+".ggseg")
		file, err := os.Open(path)
		if err != nil {
			t.Fatal(err)
		}
		replayed, replayErr := readDagHistorySegment(context.Background(), file, cursor)
		closeErr := file.Close()
		if replayErr != nil || closeErr != nil || replayed.archiveHash != item.replay.archiveHash {
			t.Fatal("full original archive chain replay", replayErr, closeErr)
		}
		cursor = replayed.plan.next
	}
	state, err := cursor.state()
	if err != nil || state.Transactions != 10000 || state.Blocks != 2 || state.Epoch != 3 || state.Authors[0].Nonce != "10000" || state.Authors[0].Sequence != "2" {
		t.Fatal("lost actual cumulative signed work", state, err)
	}
	if receipt.replay.plan.matches(second) == nil {
		t.Fatal("old receipt accepted for a different epoch")
	}
	if _, err = (&dagSegmentArchiveReceipt{}).successor(first); err == nil {
		t.Fatal("empty receipt exposed successor")
	}
	if _, err = readDagHistorySegment(context.Background(), bytes.NewReader(segmentArchiveBytes(t, second)), base); err == nil {
		t.Fatal("archive chose its own intermediate trust base")
	}
	before, _ := first.state()
	if before.Transactions != 5000 || first.active.orderCount() != 1 {
		t.Fatal("archive mutated old prefix")
	}
}

type segmentTestFrame struct {
	kind byte
	raw  []byte
}

func segmentTestFrames(t *testing.T, raw []byte) []segmentTestFrame {
	t.Helper()
	reader := bytes.NewReader(raw[8:])
	var result []segmentTestFrame
	for reader.Len() != 0 {
		var head [5]byte
		if _, err := io.ReadFull(reader, head[:]); err != nil {
			t.Fatal(err)
		}
		value := make([]byte, binary.BigEndian.Uint32(head[1:]))
		if _, err := io.ReadFull(reader, value); err != nil {
			t.Fatal(err)
		}
		result = append(result, segmentTestFrame{head[0], value})
	}
	return result
}

func segmentTestEncode(t *testing.T, frames []segmentTestFrame) []byte {
	t.Helper()
	var out bytes.Buffer
	out.WriteString(dagSegmentArchiveMagic)
	for _, frame := range frames {
		if err := writeArchiveFrame(&out, frame.kind, frame.raw, dagArchiveHeaderLimit); err != nil {
			t.Fatal(err)
		}
	}
	return out.Bytes()
}

func TestDagSegmentArchiveRejectsCorruptionTruncationAndChangedTrust(t *testing.T) {
	base, first := segmentArchiveFixture(t, 2)
	raw := segmentArchiveBytes(t, first)
	if _, err := readDagHistorySegment(context.Background(), bytes.NewReader(raw), base); err != nil {
		t.Fatal(err)
	}
	for _, size := range []int{0, 1, 8, 12, len(raw) / 2, len(raw) - 1} {
		t.Run("truncated-"+strconv.Itoa(size), func(t *testing.T) {
			if value, err := readDagHistorySegment(context.Background(), bytes.NewReader(raw[:size]), base); err == nil || value != nil {
				t.Fatal("partial archive returned a successor")
			}
		})
	}
	for _, kind := range []byte{'H', 'M', 'R', 'C', 'F'} {
		t.Run("corrupt-"+string(kind), func(t *testing.T) {
			frames := segmentTestFrames(t, raw)
			for i := range frames {
				if frames[i].kind == kind {
					frames[i].raw[len(frames[i].raw)/2] ^= 1
					break
				}
			}
			if value, err := readDagHistorySegment(context.Background(), bytes.NewReader(segmentTestEncode(t, frames)), base); err == nil || value != nil {
				t.Fatal("corrupt original accepted")
			}
		})
	}
	frames := segmentTestFrames(t, raw)
	frames[1], frames[2] = frames[2], frames[1]
	if _, err := readDagHistorySegment(context.Background(), bytes.NewReader(segmentTestEncode(t, frames)), base); err == nil {
		t.Fatal("reordered manifest/raw accepted")
	}
	if _, err := readDagHistorySegment(context.Background(), bytes.NewReader(append(append([]byte{}, raw...), 0)), base); err == nil {
		t.Fatal("trailing data accepted")
	}
	changed := *base
	changed.anchor = hashHex([]byte("different pinned anchor"))
	if _, err := readDagHistorySegment(context.Background(), bytes.NewReader(raw), &changed); err == nil {
		t.Fatal("different caller pin accepted")
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := readDagHistorySegment(ctx, bytes.NewReader(raw), base); err == nil {
		t.Fatal("cancelled replay accepted")
	}
}

func TestDagSegmentArchiveBoundsFrameBeforeReadingItsPayload(t *testing.T) {
	base, _ := segmentArchiveFixture(t, 0)
	raw := append([]byte(dagSegmentArchiveMagic), 'H', 0xff, 0xff, 0xff, 0xff)
	reader := bytes.NewReader(raw)
	if _, err := readDagHistorySegment(context.Background(), reader, base); err == nil || reader.Len() != 0 {
		t.Fatal("oversized frame did not fail at header")
	}
}

func TestDagSegmentArchiveAggregateRawBudgetCheckedBeforeAllocation(t *testing.T) {
	base, first := segmentArchiveFixture(t, 0)
	frames := segmentTestFrames(t, segmentArchiveBytes(t, first))
	var header dagSegmentArchiveHeader
	if decodeStrict(frames[0].raw, &header) != nil {
		t.Fatal("fixture")
	}
	header.RawBytes = 1
	frames[0].raw = canonical(header)
	var raw bytes.Buffer
	raw.WriteString(dagSegmentArchiveMagic)
	for _, frame := range frames[:2] {
		if err := writeArchiveFrame(&raw, frame.kind, frame.raw, dagArchiveHeaderLimit); err != nil {
			t.Fatal(err)
		}
	}
	// A valid-looking R frame claiming 32 MiB must be rejected against the
	// remaining one-byte aggregate budget, before allocating its absent body.
	raw.Write([]byte{'R', 2, 0, 0, 0})
	var before, after runtime.MemStats
	runtime.ReadMemStats(&before)
	value, err := readDagHistorySegment(context.Background(), bytes.NewReader(raw.Bytes()), base)
	runtime.ReadMemStats(&after)
	if err == nil || value != nil || after.TotalAlloc-before.TotalAlloc > 1024*1024 {
		t.Fatal("aggregate budget checked after allocation", after.TotalAlloc-before.TotalAlloc, err)
	}
}

func TestDagSegmentArchiveMultipleManifestsAndDiskPayloadReader(t *testing.T) {
	base, keys := segmentedFixture(t)
	current := base
	payloads := make(map[string]string)
	for index := 0; index < 3; index++ {
		raw := segmentedWire(t, current.active, keys, index, 200)
		path := filepath.Join(t.TempDir(), "original-wire")
		if err := os.WriteFile(path, raw, 0600); err != nil {
			t.Fatal(err)
		}
		payloads[hashHex(raw)] = path
		next, err := current.apply(segmentedBatch(t, current.active, raw), 1700000002000000000+int64(index))
		if err != nil {
			t.Fatal(err)
		}
		current = next
		current.active.pending = map[string]dagRecord{}
	}
	reads := 0
	current.active.payloadReader = func(ctx context.Context, wire string, size int) ([]byte, error) {
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		reads++
		raw, err := os.ReadFile(payloads[wire])
		if err != nil || len(raw) != size {
			return nil, errDagSegmentArchive
		}
		return raw, nil
	}
	raw := segmentArchiveBytes(t, current)
	if reads != 3 {
		t.Fatal("original disk payloads were not fetched", reads)
	}
	replayed, err := readDagHistorySegment(context.Background(), bytes.NewReader(raw), base)
	if err != nil || replayed.plan.body.Before.Transactions != 600 || replayed.plan.body.Before.Active.Checkpoint != 3 {
		t.Fatal("multi-checkpoint signed replay", err)
	}
	if replayed.plan.next.startBase.startBase != nil || len(replayed.plan.next.active.pending) != 0 || replayed.plan.next.active.payloadReader != nil {
		t.Fatal("closed segment retained payloads or old reader")
	}
	current.active.payloadReader = func(context.Context, string, int) ([]byte, error) { return nil, errors.New("disk failure") }
	if receipt, err := persistDagHistorySegment(context.Background(), t.TempDir(), current); err == nil || receipt != nil {
		t.Fatal("missing original disk data returned a storage receipt")
	}
}

func TestDagSegmentArchiveInvalidTXRejectedWithRecomputedWireAndFooterHashes(t *testing.T) {
	base, first := segmentArchiveFixture(t, 1)
	_, keys := segmentedFixture(t)
	frames := segmentTestFrames(t, segmentArchiveBytes(t, first))
	var block DagBlock
	if decodeStrict(frames[2].raw, &block) != nil {
		t.Fatal("fixture")
	}
	// Keep a valid producer block signature while corrupting the TX signature.
	block.Body.Transactions[0].Signature = DagZero + DagZero
	block.Body.PayloadRoot = dagRoot(block.Body.Transactions, "GG-DAG-PAYLOAD-v1\x00")
	block.Signature = hex.EncodeToString(ed25519.Sign(keys[0], append([]byte("GG-DAG-PROPOSAL-SIGN-v1\x00"), canonical(block.Body)...)))
	frames[2].raw = canonical(block)
	var manifest DagManifest
	if decodeStrict(frames[1].raw, &manifest) != nil {
		t.Fatal("fixture")
	}
	manifest.Blocks[0] = hashHex(frames[2].raw)
	frames[1].raw = canonical(manifest)
	var prefix bytes.Buffer
	prefix.WriteString(dagSegmentArchiveMagic)
	for _, frame := range frames[:len(frames)-1] {
		if err := writeArchiveFrame(&prefix, frame.kind, frame.raw, dagArchiveHeaderLimit); err != nil {
			t.Fatal(err)
		}
	}
	var footer dagSegmentArchiveFooter
	if decodeStrict(frames[len(frames)-1].raw, &footer) != nil {
		t.Fatal("fixture")
	}
	digest := sha256.Sum256(prefix.Bytes())
	footer.ContentHash = hex.EncodeToString(digest[:])
	frames[len(frames)-1].raw = canonical(footer)
	if result, err := readDagHistorySegment(context.Background(), bytes.NewReader(segmentTestEncode(t, frames)), base); err == nil || result != nil || err.Error() != "GG_DAG_TX_SIGNATURE" {
		t.Fatal("recomputed checksums replaced original TX signature verification")
	}
}

func TestDagSegmentArchiveSymlinkStoreAndFinalAreRejectedWhenSupported(t *testing.T) {
	_, first := segmentArchiveFixture(t, 0)
	root, outside := t.TempDir(), t.TempDir()
	if err := os.Symlink(outside, filepath.Join(root, "gg-dag-segments")); err != nil {
		// Windows may disallow creating symlinks for this account. This is a
		// capability report, not a claimed symlink execution or a skipped test.
		t.Log("symlink creation unavailable; no symlink-execution claim", err)
		return
	}
	if value, err := persistDagHistorySegment(context.Background(), root, first); err == nil || value != nil {
		t.Fatal("symlink store followed")
	}
	entries, err := os.ReadDir(outside)
	if err != nil || len(entries) != 0 {
		t.Fatal("outside directory changed", err)
	}
	secondRoot := t.TempDir()
	receipt, err := persistDagHistorySegment(context.Background(), secondRoot, first)
	if err != nil {
		t.Fatal(err)
	}
	final := filepath.Join(secondRoot, "gg-dag-segments", receipt.replay.plan.hash+".ggseg")
	if err := os.Remove(final); err != nil {
		t.Fatal(err)
	}
	target := filepath.Join(outside, "foreign-file")
	if err := os.WriteFile(target, []byte("preserve outside"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(target, final); err != nil {
		t.Fatal(err)
	}
	if value, err := persistDagHistorySegment(context.Background(), secondRoot, first); err == nil || value != nil {
		t.Fatal("symlink final followed")
	}
	got, err := os.ReadFile(target)
	if err != nil || string(got) != "preserve outside" {
		t.Fatal("outside target changed", err)
	}
}

func TestDagSegmentArchiveIOFailuresNeverExposeSuccessorAndRetryExactly(t *testing.T) {
	_, first := segmentArchiveFixture(t, 3)
	before, _ := first.state()
	for _, failure := range []string{"sync-before", "sync-after", "close-after", "publish-before", "publish-after"} {
		t.Run(failure, func(t *testing.T) {
			root := t.TempDir()
			ops := segmentArchiveDefaultIO()
			injected := errors.New("injected IO failure")
			switch failure {
			case "sync-before":
				ops.sync = func(*os.File) error { return injected }
			case "sync-after":
				ops.sync = func(file *os.File) error { _ = file.Sync(); return injected }
			case "close-after":
				ops.close = func(file *os.File) error { _ = file.Close(); return injected }
			case "publish-before":
				ops.publish = func(string, string) error { return injected }
			case "publish-after":
				ops.publish = func(from, to string) error {
					if err := os.Link(from, to); err != nil {
						return err
					}
					return injected
				}
			}
			if receipt, err := persistDagHistorySegmentWithIO(context.Background(), root, first, ops); err == nil || receipt != nil {
				t.Fatal("failed storage operation returned a ready receipt")
			}
			after, _ := first.state()
			if after != before {
				t.Fatal("failed storage changed current committed prefix")
			}
			receipt, err := persistDagHistorySegment(context.Background(), root, first)
			if err != nil {
				t.Fatal("exact retry failed", err)
			}
			if _, err = receipt.successor(first); err != nil {
				t.Fatal(err)
			}
			again, err := persistDagHistorySegment(context.Background(), root, first)
			if err != nil || again.replay.archiveHash != receipt.replay.archiveHash {
				t.Fatal("idempotent replay changed immutable archive", err)
			}
		})
	}
}

func TestDagSegmentArchiveForeignFilesLeaseAndPublicationRaceFailClosed(t *testing.T) {
	_, first := segmentArchiveFixture(t, 1)
	for _, name := range []string{"OWNER", "unknown.data"} {
		t.Run(name, func(t *testing.T) {
			root := t.TempDir()
			parent := filepath.Join(root, "gg-dag-segments")
			if err := os.Mkdir(parent, 0700); err != nil {
				t.Fatal(err)
			}
			path := filepath.Join(parent, name)
			original := []byte("foreign data must survive")
			if err := os.WriteFile(path, original, 0600); err != nil {
				t.Fatal(err)
			}
			if receipt, err := persistDagHistorySegment(context.Background(), root, first); err == nil || receipt != nil {
				t.Fatal("foreign store adopted")
			}
			got, err := os.ReadFile(path)
			if err != nil || !bytes.Equal(original, got) {
				t.Fatal("foreign file changed", err)
			}
		})
	}
	root := t.TempDir()
	receipt, err := persistDagHistorySegment(context.Background(), root, first)
	if err != nil {
		t.Fatal(err)
	}
	parent := filepath.Join(root, "gg-dag-segments")
	lease, err := openDagArchiveWork(parent)
	if err != nil {
		t.Fatal(err)
	}
	if got, err := persistDagHistorySegment(context.Background(), root, first); err == nil || got != nil {
		t.Fatal("concurrent writer bypassed OS lease")
	}
	if err := lease.close(); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(parent, receipt.replay.plan.hash+".ggseg")
	original, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte("damaged existing immutable archive"), 0600); err != nil {
		t.Fatal(err)
	}
	if got, err := persistDagHistorySegment(context.Background(), root, first); err == nil || got != nil {
		t.Fatal("damaged final archive accepted")
	}
	unchanged, _ := os.ReadFile(path)
	if !bytes.Equal(unchanged, []byte("damaged existing immutable archive")) || len(original) == 0 {
		t.Fatal("final archive overwritten")
	}
	// A destination appearing between verification and publication must survive.
	raceRoot := t.TempDir()
	ops := segmentArchiveDefaultIO()
	ops.publish = func(from, to string) error {
		if err := os.WriteFile(to, []byte("foreign race winner"), 0600); err != nil {
			return err
		}
		return os.Link(from, to)
	}
	if got, err := persistDagHistorySegmentWithIO(context.Background(), raceRoot, first, ops); err == nil || got != nil {
		t.Fatal("publication race overwrote final")
	}
	plan, _ := first.prepareCut()
	got, _ := os.ReadFile(filepath.Join(raceRoot, "gg-dag-segments", plan.hash+".ggseg"))
	if string(got) != "foreign race winner" {
		t.Fatal("foreign race file changed")
	}
}

func TestDagSegmentArchiveRecoversPartialInitialOwnerButPreservesForeignData(t *testing.T) {
	_, first := segmentArchiveFixture(t, 0)
	plan, _ := first.prepareCut()
	header, err := segmentArchiveHeader(first, plan)
	if err != nil {
		t.Fatal(err)
	}
	owner := canonical(dagSegmentArchiveOwner{Anchor: header.Anchor, Schema: "gg.dag.segment-store.v1", SourceHash: header.SourceHash})
	for _, foreign := range []bool{false, true} {
		root := t.TempDir()
		parent := filepath.Join(root, "gg-dag-segments")
		if err := os.Mkdir(parent, 0700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(parent, "OWNER"), owner[:len(owner)/2], 0600); err != nil {
			t.Fatal(err)
		}
		if foreign {
			if err := os.WriteFile(filepath.Join(parent, "unknown"), []byte("preserve"), 0600); err != nil {
				t.Fatal(err)
			}
		}
		receipt, err := persistDagHistorySegment(context.Background(), root, first)
		if foreign && (err == nil || receipt != nil) || !foreign && (err != nil || receipt == nil) {
			t.Fatal("partial owner recovery boundary", foreign, err)
		}
	}
}

func TestDagSegmentArchiveCrashChild(t *testing.T) {
	mode := os.Getenv("GG_TEST_SEGMENT_CRASH_MODE")
	if mode == "" {
		return
	}
	_, first := segmentArchiveFixture(t, 1)
	ops := segmentArchiveDefaultIO()
	if mode == "before-sync" {
		ops.sync = func(*os.File) error { os.Exit(77); return nil }
	} else if mode == "after-publish" {
		ops.publish = func(from, to string) error {
			if err := os.Link(from, to); err != nil {
				return err
			}
			os.Exit(78)
			return nil
		}
	} else {
		t.Fatal("unknown child mode")
	}
	_, _ = persistDagHistorySegmentWithIO(context.Background(), os.Getenv("GG_TEST_SEGMENT_CRASH_ROOT"), first, ops)
	t.Fatal("crash injection did not execute")
}

func TestDagSegmentArchiveActualProcessCrashRecovery(t *testing.T) {
	_, first := segmentArchiveFixture(t, 1)
	plan, _ := first.prepareCut()
	for index, mode := range []string{"before-sync", "after-publish"} {
		t.Run(mode, func(t *testing.T) {
			root := t.TempDir()
			ctx, cancel := context.WithTimeout(context.Background(), 20_000_000_000)
			defer cancel()
			command := exec.CommandContext(ctx, os.Args[0], "-test.run=^TestDagSegmentArchiveCrashChild$")
			command.Env = append(os.Environ(), "GG_TEST_SEGMENT_CRASH_MODE="+mode, "GG_TEST_SEGMENT_CRASH_ROOT="+root)
			output, err := command.CombinedOutput()
			var exit *exec.ExitError
			if !errors.As(err, &exit) || exit.ExitCode() != 77+index {
				t.Fatal("child did not reach actual crash boundary", err, string(output))
			}
			_, statErr := os.Lstat(filepath.Join(root, "gg-dag-segments", plan.hash+".ggseg"))
			if index == 0 && !os.IsNotExist(statErr) || index == 1 && statErr != nil {
				t.Fatal("wrong old/new file state after crash", statErr)
			}
			receipt, err := persistDagHistorySegment(context.Background(), root, first)
			if err != nil {
				t.Fatal("fresh process lease/replay recovery", err)
			}
			if _, err = receipt.successor(first); err != nil {
				t.Fatal(err)
			}
		})
	}
}
