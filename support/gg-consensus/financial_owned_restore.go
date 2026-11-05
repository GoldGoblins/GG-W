//go:build !js

package main

// An explicit private-pipe extension for an existing protected nonvoting P2P
// identity. It never imports validator state or trusts an application snapshot.
import (
	"bufio"
	"bytes"
	"context"
	"crypto/ed25519"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"sync"
	"time"
)

const ownedRestoreFrameMax = 512 * 1024
const ownedRestoreStartSeconds = 180

var errOwnedRestore = errors.New("GG_OWNED_RESTORE_START_FAILED")

type financialOwnedRestoreRequest struct {
	Attempt     string           `json:"attempt,omitempty"`
	Resources   *nativeResources `json:"resources,omitempty"`
	ArchivePath string           `json:"archive_path"`
	NodeKey     string           `json:"expected_node_key"`
	Genesis     Genesis          `json:"genesis"`
	GenesisHash string           `json:"genesis_hash"`
	FloorBlock  string           `json:"minimum_certificate_block"`
	FloorHeight int64            `json:"minimum_certificate_height"`
	Root        string           `json:"restore_root"`
	Schema      string           `json:"schema"`
}

type financialOwnedRestoreGrant struct {
	Archive     string          `json:"archive_sha256"`
	Bootstrap   json.RawMessage `json:"bootstrap"`
	GenesisHash string          `json:"genesis_hash"`
	Phase       string          `json:"phase"`
	PID         int             `json:"pid"`
	Schema      string          `json:"schema"`
}

type financialOwnedRestoreAck struct {
	Archive     string `json:"archive_sha256"`
	GenesisHash string `json:"genesis_hash"`
	Phase       string `json:"phase"`
	PID         int    `json:"pid"`
	Schema      string `json:"schema"`
}

// A single ownership cell binds a real ledger to exact bootstrap identity.
// No exported/decoded flag can manufacture or reuse it.
type financialOwnedLedger struct {
	mu         sync.Mutex
	app        *Ledger
	identity   []byte
	used       bool
	rootAnchor *ownedRecoveryRoot
}

func (owned *financialOwnedLedger) take(boot Bootstrap) (*Ledger, error) {
	owned.mu.Lock()
	defer owned.mu.Unlock()
	_, identity, err := nativeRootIdentity(boot)
	if err != nil || owned.used || owned.app == nil || !bytes.Equal(owned.identity, identity) {
		return nil, errOwnedRestore
	}
	if owned.rootAnchor == nil || owned.rootAnchor.checkRoot(boot.Root) != nil {
		return nil, errOwnedRestore
	}

	backend, ok := owned.app.financial.(*financialNativeApplication)
	if !ok || backend.store.health() != nil || backend.store.head.Recovery == nil || !backend.store.head.Recovery.Complete ||
		!bytes.Equal(canonical(backend.store.head.State), canonical(owned.app.state)) {
		return nil, errOwnedRestore
	}
	owned.used = true
	app := owned.app
	owned.app = nil
	return app, nil
}

func (owned *financialOwnedLedger) close() error {
	owned.mu.Lock()
	defer owned.mu.Unlock()
	var failure error
	if owned.app != nil {
		failure = owned.app.Close()
		owned.app = nil
	}
	if owned.rootAnchor != nil {
		if err := owned.rootAnchor.close(); err != nil {
			failure = errors.Join(failure, err)
		} else {
			owned.rootAnchor = nil
		}
	}
	return failure
}

// The private envelope has one language-neutral canonical encoding. This
// normalization never changes a consensus, archive, signature or stored byte.
func ownedRestoreCanonical(value any) []byte {
	encoded := canonical(value)
	var shape any
	decoder := json.NewDecoder(bytes.NewReader(encoded))
	decoder.UseNumber()
	if decoder.Decode(&shape) != nil {
		return nil
	}
	return canonical(shape)
}

func readOwnedRestoreFrame(input *bufio.Reader, target any) error {
	raw, err := input.ReadSlice('\n')
	if err != nil || len(raw) < 3 || len(raw) > ownedRestoreFrameMax || raw[len(raw)-1] != '\n' {
		return errOwnedRestore
	}
	raw = raw[:len(raw)-1]
	if decodeStrictLimited(raw, target, 128, 64) != nil || !bytes.Equal(raw, ownedRestoreCanonical(target)) {
		return errOwnedRestore
	}
	return nil
}

func writeOwnedRestoreFrame(output io.Writer, body any) error {
	raw := ownedRestoreCanonical(body)
	if len(raw) == 0 || len(raw)+1 > ownedRestoreFrameMax {
		return errOwnedRestore
	}
	raw = append(raw, '\n')
	n, err := output.Write(raw)
	if err != nil || n != len(raw) {
		return errOwnedRestore
	}
	return nil
}

func ownedRestoreAck(input *bufio.Reader, archive, genesis, phase string) error {
	var ack financialOwnedRestoreAck
	if readOwnedRestoreFrame(input, &ack) != nil || ack != (financialOwnedRestoreAck{Archive: archive, GenesisHash: genesis, PID: os.Getpid(), Phase: phase, Schema: "gg.native.owned-archive-ack.v1"}) {
		return errOwnedRestore
	}
	return nil
}

func ownedRestoreBootstrap(raw []byte) (Bootstrap, error) {
	boot, err := decodeNativeBootstrap(raw)
	if err != nil || boot.ExpectedFresh == nil || *boot.ExpectedFresh ||
		(boot.observer == nil && (boot.public == nil || boot.public.Role != "REPLICA")) || boot.ValidatorSeed != "" ||
		boot.Genesis.FinancialDAG == nil {
		return Bootstrap{}, errOwnedRestore
	}
	return boot, nil
}

func readOwnedRestoreGrant(input *bufio.Reader, request financialOwnedRestoreRequest, archive string) (Bootstrap, []byte, error) {
	var grant financialOwnedRestoreGrant
	if readOwnedRestoreFrame(input, &grant) != nil || grant.Schema != "gg.native.owned-archive-restore.v1" || grant.Phase != "RESTORE" ||
		grant.PID != os.Getpid() || grant.Archive != archive || grant.GenesisHash != request.GenesisHash {
		return Bootstrap{}, nil, errOwnedRestore
	}
	boot, err := ownedRestoreBootstrap(grant.Bootstrap)
	if err != nil || !bytes.Equal(canonical(boot.Resources), canonical(request.Resources)) || boot.Root != request.Root || boot.GenesisHash != request.GenesisHash || !bytes.Equal(canonical(boot.Genesis), canonical(request.Genesis)) {
		return Bootstrap{}, nil, errOwnedRestore
	}
	seed, _ := hex.DecodeString(boot.NodeSeed)
	if hex.EncodeToString(ed25519.NewKeyFromSeed(seed)[32:]) != request.NodeKey {
		return Bootstrap{}, nil, errOwnedRestore
	}
	// Path/role/signing-state guards are evaluated before any target write.
	if _, _, err = nativeRootIdentity(boot); err != nil {
		return Bootstrap{}, nil, errOwnedRestore
	}
	return boot, grant.Bootstrap, nil
}

// Full original replay remains mandatory on every attempt, including an
// interrupted durable prefix. No phase or saved certificate skips execution.
func restoreFinancialOwned(ctx context.Context, file *os.File, info os.FileInfo, request financialArchiveCommand, boot Bootstrap,
	sdk *financialSDKRecovery, archive string, fault func(string) error, progress func(string, int64) error) (owned *financialOwnedLedger, result map[string]any, failure error) {
	if ctx.Err() != nil {
		return nil, nil, ctx.Err()
	}
	if request.Certificate == nil || sdk == nil || sdk.commit == nil || !pubPattern.MatchString(archive) ||
		request.RestoreRoot != boot.Root || request.GenesisHash != boot.GenesisHash ||
		!bytes.Equal(canonical(request.Genesis), canonical(boot.Genesis)) || !unchangedFinancialArchive(file, info) {
		return nil, nil, errOwnedRestore
	}
	marker, identity, err := nativeRootIdentity(boot)
	if err != nil {
		return nil, nil, err
	}
	archivePath, err := filepath.EvalSymlinks(request.ArchivePath)
	if err != nil || pathWithinArchiveRoot(archivePath, boot.Root) {
		return nil, nil, errOwnedRestore
	}
	if err = os.Mkdir(boot.Root, 0700); err != nil && !os.IsExist(err) {
		return nil, nil, financialObserverStorageError(err, errOwnedRestore)
	}
	if !realArchiveDirectory(boot.Root) {
		return nil, nil, errOwnedRestore
	}
	want := financialObserverRestoreIntent{Archive: archive, Certificate: *request.Certificate,
		Schema: "gg.financial.owned-recovery.v1", Identity: append(json.RawMessage(nil), identity...)}
	if boot.observer != nil {
		want.Grant = boot.observer.ObserverGrant
	}
	intent, err := openFinancialObserverIntent(boot.Root, want, fault)
	if err != nil {
		return nil, nil, err
	}
	closed := false
	defer func() {
		if !closed {
			if err := intent.db.Close(); err != nil && failure == nil {
				failure = financialObserverStorageError(err, errOwnedRestore)
			}
		}
		if failure != nil && owned != nil {
			_ = owned.close()
			owned = nil
		}
	}()
	if intent.head.Phase >= 2 {
		if err = bootstrapFinancialObserverSDK(boot.Root, sdk, true, fault); err != nil {
			return nil, nil, err
		}
	}
	if _, err = file.Seek(0, io.SeekStart); err != nil {
		return nil, nil, errOwnedRestore
	}
	anchor, rootErr := openOwnedRecoveryRoot(boot.Root)
	if rootErr != nil {
		return nil, nil, errOwnedRestore
	}
	owned = &financialOwnedLedger{identity: identity, rootAnchor: anchor}

	result, err = restoreFinancialArchiveOwned(ctx, file, info, request, nil, true, func(app *Ledger) error {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		owned.app = app
		return nil
	})
	if err != nil {
		return owned, nil, err
	}
	if result["archive_sha256"] != archive || !unchangedFinancialArchive(file, info) {
		return owned, nil, errOwnedRestore
	}
	if err = intent.phase(1, "APP_PHASE"); err != nil {
		return owned, nil, err
	}
	if progress != nil {
		if err = progress("APPLICATION_RESTORED", request.Certificate.State.Height); err != nil {
			return owned, nil, err
		}
	}
	if ctx.Err() != nil {
		return owned, nil, ctx.Err()
	}
	if intent.head.Phase < 2 {
		if err = bootstrapFinancialObserverSDK(boot.Root, sdk, false, fault); err != nil {
			return owned, nil, err
		}
		if err = intent.phase(2, "SDK_PHASE"); err != nil {
			return owned, nil, err
		}
	}
	if err = bootstrapFinancialObserverSDK(boot.Root, sdk, true, fault); err != nil {
		return owned, nil, err
	}
	if ctx.Err() != nil {
		return owned, nil, ctx.Err()
	}
	if err = publishFinancialOwnedRoot(boot.Root, marker, identity, fault); err != nil {
		return owned, nil, err
	}
	if err = intent.phase(3, "COMPLETE"); err != nil {
		return owned, nil, err
	}
	err = intent.db.Close()
	closed = true
	if err != nil {
		return owned, nil, financialObserverStorageError(err, errOwnedRestore)
	}
	return owned, result, nil
}

func runFinancialOwnedRestoreStart(input *os.File, output io.Writer, parentPID int) error {
	return runFinancialOwnedRestoreStartUsing(input, output, parentPID, nil, nil)
}

// Non-wire observers are only for deterministic tests of actual retained
// ledger identity. Production supplies nil; they grant no recovery authority.
func runFinancialOwnedRestoreStartUsing(input *os.File, output io.Writer, parentPID int, retained, ready func(*Ledger)) error {
	// Cancellation and a short read lease begin before any private frame.
	ctx, cancel, done := ownedRecoveryLifetime(input, parentPID)
	defer cancel()
	defer close(done)
	timer := time.AfterFunc(ownedRecoveryBootstrap, cancel)
	defer timer.Stop()
	var recovery *ownedRecovery
	reader := bufio.NewReaderSize(input, ownedRestoreFrameMax)
	var request financialOwnedRestoreRequest
	if readOwnedRestoreFrame(reader, &request) != nil || request.Schema != "gg.native.owned-archive-start.v1" || !filepath.IsAbs(request.ArchivePath) ||
		!filepath.IsAbs(request.Root) || !pubPattern.MatchString(request.NodeKey) || validateGenesis(request.Genesis, request.GenesisHash) != nil || request.Genesis.FinancialDAG == nil ||
		(request.FloorHeight == 0 && request.FloorBlock != "") || request.FloorHeight < 0 || request.FloorHeight > 0 && !pubPattern.MatchString(request.FloorBlock) {
		return errOwnedRestore
	}
	if err := bindNativeResources(request.Resources); err != nil {
		return err
	}
	if request.Attempt != "" {
		var err error
		ctx, recovery, err = newOwnedRecovery(ctx, cancel, output, request.Root, request.GenesisHash, request.Attempt, request.Resources)
		if err != nil {
			return err
		}
		timer.Stop()
		go recovery.guard(ctx, done)
		if err = recoveryPhase(ctx, "INVENTORY"); err != nil {
			return err
		}
		if err = recoveryWork(ctx, uint64(len(ownedRestoreCanonical(request))+1), nil); err != nil {
			return err
		}
		if _, err = os.Lstat(request.Root); err == nil {
			if err = inventoryOwnedNativeRoot(ctx, request.Root); err != nil {
				return err
			}
		} else if !os.IsNotExist(err) {
			return errOwnedRestore
		}
	} else {
		timer.Stop()
		timer = time.AfterFunc(ownedRestoreStartSeconds*time.Second, cancel)
		defer timer.Stop()
	}
	if err := recoveryPhase(ctx, "ARCHIVE_AUDIT"); err != nil {
		return err
	}
	file, info, err := openFinancialArchiveInput(request.ArchivePath)
	if err != nil {
		return err
	}
	defer file.Close()
	command := financialArchiveCommand{ArchivePath: request.ArchivePath, Genesis: request.Genesis, GenesisHash: request.GenesisHash,
		MinimumCertificateHeight: request.FloorHeight, MinimumCertificateBlock: request.FloorBlock, RestoreRoot: request.Root}
	progress := func(phase string, height int64) error {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		return writeOwnedRestoreFrame(output, map[string]any{"schema": "gg.native.owned-archive-progress.v1", "phase": phase,
			"genesis_hash": request.GenesisHash, "pid": os.Getpid(), "processed_height": height, "native_node_ready": false,
			"certificate_is_network_liveness": false})
	}
	if err = progress("FULL_ORIGINAL_AUDIT", 0); err != nil {
		return err
	}
	var sdk *financialSDKRecovery
	lastProgress := time.Now()
	verified, err := readFinancialArchiveUsing(ctx, file, command, func(entry financialJournalEntry, raw []byte, cursor *financialArchiveReplay) error {
		if err := recoveryWork(ctx, uint64(len(raw)+1), &entry.Height); err != nil {
			return err
		}
		if time.Since(lastProgress) >= 250*time.Millisecond {
			lastProgress = time.Now()
			return progress("FULL_ORIGINAL_AUDIT", entry.Height)
		}
		return ctx.Err()
	}, func(cursor *financialArchiveReplay) error { sdk = cursor.sdkRecovery; return nil })
	if err != nil || sdk == nil || sdk.commit == nil || !unchangedFinancialArchive(file, info) {
		return errOwnedRestore
	}
	encoded := canonical(verified["certificate"])
	var certificate dagArchiveCertificate
	if decodeStrictLimited(encoded, &certificate, 128, 64) != nil {
		return errOwnedRestore
	}
	archive, ok := verified["archive_sha256"].(string)
	if !ok || !pubPattern.MatchString(archive) {
		return errOwnedRestore
	}
	command.Certificate = &certificate
	if err = writeOwnedRestoreFrame(output, map[string]any{"schema": "gg.native.owned-archive-audited.v1", "genesis_hash": request.GenesisHash,
		"pid": os.Getpid(), "archive_sha256": archive, "certificate": certificate, "native_node_ready": false}); err != nil {
		return err
	}
	boot, bootstrapRaw, err := readOwnedRestoreGrant(reader, request, archive)
	if err != nil || ctx.Err() != nil {
		return errOwnedRestore
	}
	if err = recoveryPhase(ctx, "ARCHIVE_RESTORE"); err != nil {
		return err
	}
	owned, _, err := restoreFinancialOwned(ctx, file, info, command, boot, sdk, archive, nil, progress)
	if err != nil {
		return err
	}
	defer owned.close()
	if retained != nil {
		retained(owned.app)
	}
	if err = writeOwnedRestoreFrame(output, map[string]any{"schema": "gg.native.owned-archive-restored.v1", "genesis_hash": boot.GenesisHash,
		"pid": os.Getpid(), "archive_sha256": archive, "certificate": certificate, "native_node_ready": false}); err != nil {
		return err
	}
	if ownedRestoreAck(reader, archive, boot.GenesisHash, "START") != nil || ctx.Err() != nil {
		return errOwnedRestore
	}
	if err = input.Close(); err != nil {
		return errOwnedRestore
	}
	if err = file.Close(); err != nil {
		return errOwnedRestore
	}
	if recovery != nil {
		ctx = context.WithValue(ctx, ownedRecoveryRootKey{}, owned.rootAnchor)
	}
	app, err := owned.take(boot)
	if err != nil {
		return err
	}
	// runNodeWithOwnedLedger owns Close from this point, even on startup error.
	return runNodeWithOwnedLedger(bootstrapRaw, parentPID, app, ctx, func(actual *Ledger) {
		if ready != nil {
			ready(actual)
		}
		timer.Stop()
		if recovery != nil {
			recovery.finish()
		}
	})
}
