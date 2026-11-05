//go:build !js

package main

// Internal owned cold start. Progress is provisional work, never a replay
// cursor, certificate, signing grant or persisted verification cache.
import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"os"
	"os/signal"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"time"
)

const ownedRecoveryCounterMax uint64 = 1<<63 - 1
const ownedRecoveryStall = 180 * time.Second
const ownedRecoveryBootstrap = 12 * time.Second

var errOwnedRecovery = errors.New("GG_OWNED_RECOVERY_FAILED")
var ownedAttemptPattern = regexp.MustCompile(`^[0-9a-f]{32}$`)

type ownedRecoveryKey struct{}
type ownedSDKInvocationKey struct{}
type ownedRecovery struct {
	mu                           sync.Mutex
	output                       io.Writer
	input                        *os.File
	reader                       *bufio.Reader
	root, anchor, attempt, phase string
	profile                      map[string]any
	work                         uint64
	sentWork                     uint64
	processed, verified          *int64
	sent                         time.Time
	lastCompleted                atomic.Int64
	beganWork                    atomic.Bool
	terminal                     atomic.Bool
	sdkRecoveryActive            atomic.Bool
	progressFrozen               bool
	coldCut                      *int64
	finished                     bool
	err                          error
	cancel                       context.CancelFunc
}

func newOwnedRecovery(ctx context.Context, cancel context.CancelFunc, output io.Writer, root, anchor, attempt string, resources *nativeResources) (context.Context, *ownedRecovery, error) {
	if ctx.Err() != nil || !ownedAttemptPattern.MatchString(attempt) || !filepath.IsAbs(root) || !pubPattern.MatchString(anchor) {
		return ctx, nil, errOwnedRecovery
	}
	profile, err := nativeResourceReady(resources, nativeResourceCommitWait(resources))
	if err != nil {
		return ctx, nil, err
	}
	r := &ownedRecovery{output: output, root: root, anchor: anchor, attempt: attempt, profile: profile, cancel: cancel}
	r.lastCompleted.Store(time.Now().UnixNano())
	r.sdkRecoveryActive.Store(true)
	return context.WithValue(ctx, ownedRecoveryKey{}, r), r, nil
}
func recoveryFrom(ctx context.Context) *ownedRecovery {
	if ctx == nil {
		return nil
	}
	r, _ := ctx.Value(ownedRecoveryKey{}).(*ownedRecovery)
	return r
}
func recoveryWork(ctx context.Context, units uint64, processed *int64) error {
	if ctx.Err() != nil {
		return ctx.Err()
	}
	r := recoveryFrom(ctx)
	if r == nil {
		return nil
	}
	if sdk, _ := ctx.Value(ownedSDKInvocationKey{}).(bool); sdk {
		// Check the constructor boundary under the same mutex as completed work.
		return r.completeSDK(units)
	}
	return r.complete(units, processed)
}
func recoveryPhase(ctx context.Context, phase string) error {
	if ctx.Err() != nil {
		return ctx.Err()
	}
	r := recoveryFrom(ctx)
	if r == nil {
		return nil
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	// Phase transitions never renew the lease. A new phase may reset its
	// provisional height; cumulative completed work cannot regress.
	r.phase = phase
	r.processed = nil
	r.verified = nil
	if !r.sent.IsZero() {
		wait := 250*time.Millisecond - time.Since(r.sent)
		if wait > 0 {
			timer := time.NewTimer(wait)
			defer timer.Stop()
			select {
			case <-ctx.Done():
				return ctx.Err()
			case <-timer.C:
			}
		}
	}
	return r.publishLocked()
}
func (r *ownedRecovery) complete(units uint64, processed *int64) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	return r.completeLocked(units, processed)
}
func (r *ownedRecovery) completeSDK(units uint64) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	if !r.sdkRecoveryActive.Load() {
		return nil
	}
	return r.completeLocked(units, nil)
}
func (r *ownedRecovery) completeLocked(units uint64, processed *int64) error {
	if r.err != nil {
		return r.err
	}
	if r.finished || r.progressFrozen {
		return nil
	}
	if units == 0 || units > ownedRecoveryCounterMax-r.work || processed != nil && (*processed < 0 || uint64(*processed) > ownedRecoveryCounterMax) {
		return errOwnedRecovery
	}
	r.work += units
	r.lastCompleted.Store(time.Now().UnixNano())
	r.beganWork.Store(true)
	if processed != nil && (r.processed == nil || *processed >= *r.processed) {
		height := *processed
		r.processed = &height
	}
	// Only completed bytes, entries or authenticated records reach this path.
	// Coalescing cannot fabricate a heartbeat during a blocked operation.
	if r.sent.IsZero() || time.Since(r.sent) >= 250*time.Millisecond {
		return r.publishLocked()
	}
	return nil
}
func (r *ownedRecovery) publishLocked() error {
	if r.progressFrozen {
		return nil
	}
	body := map[string]any{"schema": "gg.native.owned-recovery-progress.v1", "pid": os.Getpid(), "genesis_hash": r.anchor,
		"root": r.root, "attempt": r.attempt, "resource_profile": r.profile, "phase": r.phase, "work_done": r.work,
		"processed_height": r.processed, "verified_through": r.verified, "native_node_ready": false}
	if err := writeOwnedRestoreFrame(r.output, body); err != nil {
		r.err = err
		r.cancel()
		return err
	}
	r.sent = time.Now()
	r.sentWork = r.work
	return nil
}
func (r *ownedRecovery) finish() {
	r.terminal.Store(true)
	r.mu.Lock()
	r.finished = true
	r.mu.Unlock()
}
func (r *ownedRecovery) stalled(now time.Time) bool {
	if r.terminal.Load() {
		return false
	}
	return now.Sub(time.Unix(0, r.lastCompleted.Load())) >= ownedRecoveryStall
}

// Close the input on loss before bootstrap/ACK reads. The exact native child
// additionally remains contained by its foreground controller's OS resource leaf.
func ownedRecoveryLifetime(input *os.File, parentPID int) (context.Context, context.CancelFunc, chan struct{}) {
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	stop := make(chan os.Signal, 1)
	signal.Notify(stop, os.Interrupt, syscall.SIGTERM)
	go func() {
		defer signal.Stop(stop)
		ticker := time.NewTicker(100 * time.Millisecond)
		defer ticker.Stop()
		for {
			select {
			case <-done:
				return
			case <-ctx.Done():
				_ = input.Close()
				return
			case <-stop:
				cancel()
			case <-ticker.C:
				if (runtime.GOOS == "linux" || runtime.GOOS == "android") && (parentPID <= 1 || os.Getppid() != parentPID) {
					cancel()
				}
			}
		}
	}()
	return ctx, cancel, done
}
func (r *ownedRecovery) guard(ctx context.Context, done <-chan struct{}) {
	ticker := time.NewTicker(50 * time.Millisecond)
	defer ticker.Stop()
	for {
		select {
		case <-done:
			return
		case <-ctx.Done():
			return
		case now := <-ticker.C:
			if r.stalled(now) {
				r.cancel()
				return
			}
		}
	}
}

type ownedProtocolStartRequest struct {
	Schema      string          `json:"schema"`
	Attempt     string          `json:"attempt"`
	Bootstrap   json.RawMessage `json:"bootstrap"`
	FloorHeight int64           `json:"minimum_certificate_height"`
	FloorBlock  string          `json:"minimum_certificate_block"`
}

func runOwnedProtocolStart(input *os.File, output io.Writer, parentPID int) (failure error) {
	ctx, cancel, done := ownedRecoveryLifetime(input, parentPID)
	defer cancel()
	defer close(done)
	// A finite pre-bootstrap read cannot be prolonged by peer/progress claims.
	timer := time.AfterFunc(ownedRecoveryBootstrap, cancel)
	defer timer.Stop()
	var request ownedProtocolStartRequest
	reader := bufio.NewReaderSize(input, ownedRestoreFrameMax)
	if readOwnedRestoreFrame(reader, &request) != nil || request.Schema != "gg.native.owned-protocol-start.v1" || !ownedAttemptPattern.MatchString(request.Attempt) {
		return errOwnedRecovery
	}
	if request.FloorHeight < 0 || request.FloorHeight == 0 && request.FloorBlock != "" || request.FloorHeight > 0 && !pubPattern.MatchString(request.FloorBlock) {
		return errOwnedRecovery
	}
	boot, err := decodeNativeBootstrap(request.Bootstrap)
	if err != nil || boot.public == nil || boot.Genesis.FinancialDAG == nil || boot.ExpectedFresh == nil || (boot.public.Role != "VALIDATOR" && boot.public.Role != "REPLICA") {
		return errOwnedRecovery
	}
	ctx, r, err := newOwnedRecovery(ctx, cancel, output, boot.Root, boot.GenesisHash, request.Attempt, boot.Resources)
	if err != nil {
		return err
	}
	r.input = input
	r.reader = reader
	timer.Stop()
	go r.guard(ctx, done)
	if err = recoveryPhase(ctx, "INVENTORY"); err != nil {
		return err
	}
	if err = recoveryWork(ctx, uint64(len(request.Bootstrap)+1), nil); err != nil {
		return err
	}
	if _, e := os.Lstat(boot.Root); e == nil {
		anchor, e := openOwnedRecoveryRoot(boot.Root)
		if e != nil {
			return e
		}
		defer func() {
			if e := anchor.close(); e != nil && failure == nil {
				failure = e
			}
		}()
		ctx = context.WithValue(ctx, ownedRecoveryRootKey{}, anchor)
		if err = inventoryOwnedNativeRoot(ctx, boot.Root); err != nil {
			return err
		}
	} else if !os.IsNotExist(e) || !*boot.ExpectedFresh {
		return errOwnedRecovery
	}
	ctx = context.WithValue(ctx, ownedRecoveryFloorKey{}, ownedRecoveryFloor{height: request.FloorHeight, block: request.FloorBlock})
	return runNodeWithOwnedLedger(request.Bootstrap, parentPID, nil, ctx, func(*Ledger) { r.finish() })
}

type ownedRecoveryRootKey struct{}

// One exact eager kernel anchor per attempt. Directory content/mtime may
// change through legitimate SDK IO; the original kernel identity may not.
type ownedRecoveryRoot struct {
	path        string
	mu          sync.Mutex
	checkKernel func() error
	closeKernel func() error
	closed      bool
}

func openOwnedRecoveryRoot(path string) (*ownedRecoveryRoot, error) {
	if !filepath.IsAbs(path) || filepath.Clean(path) != path {
		return nil, errOwnedRecovery
	}
	check, close, err := financialRecoveryRootAnchor(path)
	if err != nil {
		return nil, err
	}
	return &ownedRecoveryRoot{path: path, checkKernel: check, closeKernel: close}, nil
}
func (root *ownedRecoveryRoot) checkRoot(path string) error {
	root.mu.Lock()
	defer root.mu.Unlock()
	if root.closed || path != root.path {
		return errOwnedRecovery
	}
	return root.checkKernel()
}
func (root *ownedRecoveryRoot) close() error {
	root.mu.Lock()
	defer root.mu.Unlock()
	if root.closed {
		return nil
	}
	if err := root.closeKernel(); err != nil {
		return err
	}
	root.closed = true
	return nil
}
func recoveryRootCurrent(ctx context.Context, root string) error {
	if ctx.Err() != nil {
		return ctx.Err()
	}
	value := ctx.Value(ownedRecoveryRootKey{})
	if value == nil {
		return nil
	}
	anchor, ok := value.(*ownedRecoveryRoot)
	if !ok || anchor == nil {
		return errOwnedRecovery
	}
	return anchor.checkRoot(root)
}

var ownedLevelDBName = regexp.MustCompile(`^(CURRENT|CURRENT\.bak|CURRENT\.[0-9]+|LOCK|LOG|LOG\.old|MANIFEST-[0-9]+|[0-9]+\.(log|ldb|sst|tmp))$`)
var ownedHistoryName = regexp.MustCompile(`^[0-9]{20}\.ggfh(\.pending)?$`)

func ownedNativeLayout(relative string, dir bool) bool {
	parts := strings.Split(filepath.ToSlash(relative), "/")
	switch parts[0] {
	case "config":
		return dir && len(parts) == 1 || len(parts) == 2 && !dir && parts[1] == "addrbook.json"
	case "gg-financial-history":
		if len(parts) == 1 {
			return dir
		}
		return len(parts) == 2 && !dir && ownedHistoryName.MatchString(parts[1])
	case "gg-financial-dag.leveldb", financialObserverIntentDB:
		if len(parts) == 1 {
			return dir
		}
		return len(parts) == 2 && !dir && ownedLevelDBName.MatchString(parts[1])
	case "data":
		if len(parts) == 1 {
			return dir
		}
		if len(parts) == 2 {
			if dir {
				return parts[1] == "blockstore.db" || parts[1] == "state.db" || parts[1] == "tx_index.db" || parts[1] == "block_index.db" || parts[1] == "evidence.db" || parts[1] == "cs.wal"
			}
			return parts[1] == "priv_validator_state.json"
		}
		if len(parts) == 3 && !dir {
			if parts[1] == "cs.wal" {
				return parts[2] == "wal" || regexp.MustCompile(`^wal\.[0-9]+$`).MatchString(parts[2])
			}
			return ownedLevelDBName.MatchString(parts[2])
		}
	default:
		return len(parts) == 1 && !dir && (parts[0] == nativePublicRootFile || parts[0] == nativeObserverRootFile || parts[0] == financialObserverMarkerStage)
	}
	return false
}

// One depth-first stream, <=17 directory handles plus one64KiB leaf buffer.
// No filename list, whole-tree count, heap allocation or trust cache scales with
// retained file count. Existing DB/archive parsers still verify semantics.
func inventoryOwnedNativeRoot(ctx context.Context, root string) error {
	return inventoryOwnedNative(ctx, root, true)
}
func inventoryOwnedNativeNamespace(ctx context.Context, root string) error {
	return inventoryOwnedNative(ctx, root, false)
}
func inventoryOwnedNative(ctx context.Context, root string, readBytes bool) error {
	var walk func(string, int) error
	walk = func(path string, depth int) (failure error) {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		if depth > 16 {
			return errOwnedRecovery
		}
		directory, check, err := financialRecoveryOpenDirectory(path)
		if err != nil {
			return err
		}
		defer func() {
			if e := check(); e != nil && failure == nil {
				failure = e
			}
			if e := directory.Close(); e != nil && failure == nil {
				failure = errOwnedRecovery
			}
		}()
		for {
			entries, readErr := directory.ReadDir(64)
			for _, entry := range entries {
				if ctx.Err() != nil {
					return ctx.Err()
				}
				name := entry.Name()
				if name == "" || name == "." || name == ".." || len(name) > 255 || strings.ContainsAny(name, "/\\\x00") {
					return errOwnedRecovery
				}
				child := filepath.Join(path, name)
				info, err := os.Lstat(child)
				if err != nil || info.Mode()&os.ModeSymlink != 0 {
					return errOwnedRecovery
				}
				rel, err := filepath.Rel(root, child)
				if err != nil || !ownedNativeLayout(rel, info.IsDir()) {
					return errOwnedRecovery
				}
				if info.IsDir() {
					if err = walk(child, depth+1); err != nil {
						return err
					}
				} else if info.Mode().IsRegular() {
					if !readBytes {
						if err = financialRecoveryInspectFile(child); err != nil {
							return err
						}
						if err = recoveryWork(ctx, 1, nil); err != nil {
							return err
						}
						continue
					}
					file, before, err := financialRecoveryOpenFile(child)
					if err != nil {
						return err
					}
					buffer := make([]byte, 64*1024)
					for {
						n, e := file.Read(buffer)
						if n > 0 {
							if err = recoveryWork(ctx, uint64(n), nil); err != nil {
								_ = file.Close()
								return err
							}
						}
						if e == io.EOF {
							break
						}
						if e != nil {
							_ = file.Close()
							return errOwnedRecovery
						}
						if ctx.Err() != nil {
							_ = file.Close()
							return ctx.Err()
						}
					}
					after, e := file.Stat()
					current, ce := os.Lstat(child)
					closeErr := file.Close()
					if e != nil || ce != nil || closeErr != nil || !os.SameFile(before, after) || !os.SameFile(before, current) || before.Size() != after.Size() || !before.ModTime().Equal(after.ModTime()) {
						return errOwnedRecovery
					}
				} else {
					return errOwnedRecovery
				}
				if err = recoveryWork(ctx, 1, nil); err != nil {
					return err
				}
			}
			if err = check(); err != nil {
				return err
			}
			if readErr == io.EOF {
				return nil
			}
			if readErr != nil {
				return errOwnedRecovery
			}
		}
	}
	return walk(root, 0)
}

type ownedRecoveryFloorKey struct{}
type ownedRecoveryFloor struct {
	height int64
	block  string
}

func recoveryPendingLink(path string, info os.FileInfo, links uint64) bool {
	if links == 1 {
		return true
	}
	if links != 2 || filepath.Base(filepath.Dir(path)) != "gg-financial-history" {
		return false
	}
	name := filepath.Base(path)
	if !ownedHistoryName.MatchString(name) {
		return false
	}
	other := path + ".pending"
	if strings.HasSuffix(path, ".pending") {
		other = strings.TrimSuffix(path, ".pending")
	}
	sibling, err := os.Lstat(other)
	return err == nil && sibling.Mode().IsRegular() && sibling.Mode()&os.ModeSymlink == 0 && os.SameFile(info, sibling)
}
func recoveryHistoryDirectory(ctx context.Context, path string) (func() error, error) {
	if recoveryFrom(ctx) == nil {
		return financialHistoryReadDirectory(path)
	}
	file, check, err := financialRecoveryOpenDirectory(path)
	if err != nil {
		return nil, err
	}
	return func() error {
		err := check()
		closeErr := file.Close()
		if err != nil || closeErr != nil {
			return errFinancialHistory
		}
		return nil
	}, nil
}
func recoveryHistoryFile(ctx context.Context, path string, limit int64) (*os.File, os.FileInfo, error) {
	if recoveryFrom(ctx) == nil {
		return checkedSegmentFile(path, false, limit)
	}
	file, info, err := financialRecoveryOpenFile(path)
	if err != nil {
		return nil, nil, err
	}
	if info.Size() < 0 || info.Size() > limit {
		_ = file.Close()
		return nil, nil, errFinancialHistory
	}
	return file, info, nil
}

type ownedRecoveryStartAck struct {
	Schema  string          `json:"schema"`
	Attempt string          `json:"attempt"`
	PID     int             `json:"pid"`
	Anchor  string          `json:"genesis_hash"`
	Root    string          `json:"root"`
	Profile json.RawMessage `json:"resource_profile"`
}

func (r *ownedRecovery) acknowledgePrepared(ctx context.Context) error {
	if r.reader == nil || r.input == nil || ctx.Err() != nil {
		return errOwnedRecovery
	}
	timer := time.AfterFunc(ownedRecoveryBootstrap, r.cancel)
	defer timer.Stop()
	var ack ownedRecoveryStartAck
	if readOwnedRestoreFrame(r.reader, &ack) != nil || ack.Schema != "gg.native.owned-recovery-start-ack.v1" || ack.Attempt != r.attempt || ack.PID != os.Getpid() || ack.Anchor != r.anchor || ack.Root != r.root || !bytes.Equal(ack.Profile, ownedRestoreCanonical(r.profile)) {
		return errOwnedRecovery
	}
	// Exactly one ACK then EOF. An extra frame cannot start another role/epoch.
	if _, err := r.reader.ReadByte(); err != io.EOF {
		return errOwnedRecovery
	}
	if ctx.Err() != nil {
		return ctx.Err()
	}
	return nil
}

// Flush only already completed work, respecting the same4fps ceiling.
// This cannot renew a stall lease and never invents a heartbeat.
func (r *ownedRecovery) flushCompleted(ctx context.Context) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.err != nil {
		return r.err
	}
	if r.work == r.sentWork {
		return nil
	}
	wait := 250*time.Millisecond - time.Since(r.sent)
	if wait > 0 {
		timer := time.NewTimer(wait)
		defer timer.Stop()
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-timer.C:
		}
	}
	return r.publishLocked()
}

// Called once immediately after SDK construction/handshake and before Start.
// The immutable cut is the store's fullcold audit, not a newer live SDK head.
func (r *ownedRecovery) sealSDKRecovery(cut int64) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.sdkRecoveryActive.Store(false)
	if cut < 0 || r.coldCut != nil || r.progressFrozen {
		return errOwnedRecovery
	}
	saved := cut
	r.coldCut = &saved
	return nil
}
func (r *ownedRecovery) auditedColdCut() (int64, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.coldCut == nil {
		return 0, errOwnedRecovery
	}
	return *r.coldCut, nil
}

// Flush and freeze under one mutex so a late completed SDK callback cannot
// write progress after PREPARED/READY or cancel a live SDK on a closed pipe.
func (r *ownedRecovery) freezeProgress(ctx context.Context) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.progressFrozen {
		return nil
	}
	if r.err != nil {
		return r.err
	}
	if r.work != r.sentWork {
		wait := 250*time.Millisecond - time.Since(r.sent)
		if wait > 0 {
			timer := time.NewTimer(wait)
			defer timer.Stop()
			select {
			case <-ctx.Done():
				return ctx.Err()
			case <-timer.C:
			}
		}
		if err := r.publishLocked(); err != nil {
			return err
		}
	}
	r.progressFrozen = true
	return ctx.Err()
}
