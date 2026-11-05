//go:build !js

package main

// Source-only amendment tests: NOT_EXECUTED. Actual signed originals, existing
// full restore/cold replay and the SDK's real state/blockstore serializers.
import (
	"bufio"
	"bytes"
	"context"
	"encoding/hex"
	"encoding/json"
	"fmt"
	dbm "github.com/cometbft/cometbft-db"
	cmted "github.com/cometbft/cometbft/crypto/ed25519"
	cmtjson "github.com/cometbft/cometbft/libs/json"
	cmtproto "github.com/cometbft/cometbft/proto/tendermint/types"
	sm "github.com/cometbft/cometbft/state"
	cmtstore "github.com/cometbft/cometbft/store"
	"github.com/cometbft/cometbft/types"
	"github.com/syndtr/goleveldb/leveldb/opt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func recoveryFloorRestoredFixture(t *testing.T) (*Ledger, Bootstrap, ownedRecoveryFloor) {
	t.Helper()
	command, boot, _, _ := ownedRestoreFixture(t)
	file, info, sdk, digest := auditOwnedRestore(t, command)
	owned, _, err := restoreFinancialOwned(context.Background(), file, info, command, boot, sdk, digest, nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if err := owned.close(); err != nil {
			t.Error("owned restored fixture close", err)
		}
	})
	app, err := owned.take(boot)
	if err != nil {
		t.Fatal(err)
	}
	if err = app.Close(); err != nil {
		t.Fatal(err)
	}
	cold, err := newFinancialLedger(boot.Genesis, boot.GenesisHash, boot.Root, false)
	if err != nil {
		t.Fatal("real cold restart", err)
	}
	t.Cleanup(func() { _ = cold.Close() })
	return cold, boot, ownedRecoveryFloor{height: command.Certificate.State.Height + 1, block: floorCertificateBlock(t, *command.Certificate)}
}

// Keep certificate parsing on existing verifier APIs, not a hand-authored hash.
func floorCertificateBlock(t *testing.T, certificate dagArchiveCertificate) string {
	t.Helper()
	signed, _, err := verifyFinancialCertificate(certificate.packet())
	if err != nil {
		t.Fatal(err)
	}
	return hex.EncodeToString(signed.Commit.BlockID.Hash)
}

func TestOwnedRecoveryFloorUnjoinedActualColdRestartAndNegativeBindings(t *testing.T) {
	app, boot, floor := recoveryFloorRestoredFixture(t)
	stateDB, err := dbm.NewGoLevelDBWithOpts("state", filepath.Join(boot.Root, "data"), &opt.Options{ReadOnly: true, ErrorIfMissing: true, Strict: opt.StrictAll})
	if err != nil {
		t.Fatal(err)
	}
	defer stateDB.Close()
	blockDB, err := dbm.NewGoLevelDBWithOpts("blockstore", filepath.Join(boot.Root, "data"), &opt.Options{ErrorIfMissing: true, Strict: opt.StrictAll})
	if err != nil {
		t.Fatal(err)
	}
	defer blockDB.Close()
	actual, err := sm.NewStore(stateDB, sm.StoreOptions{DiscardABCIResponses: false}).Load()
	if err != nil {
		t.Fatal(err)
	}
	blocks := cmtstore.NewBlockStore(blockDB)
	if blocks.Height() != 0 || blocks.Base() != 0 || blocks.LoadBlockMeta(floor.height) != nil {
		t.Fatal("fixture must expose the old universal-height blocker")
	}
	if err = checkOwnedRecoveryRestoredFloor(context.Background(), boot, app, floor, blocks, actual); err != nil {
		t.Fatal("exact original cold replay/state/seen-commit origin proof", err)
	}
	for _, mode := range []string{"wrong_floor", "newer_floor", "sdk_state", "seen_commit", "invalid_certificate", "validator_role", "missing_replay_ownership"} {
		t.Run(mode, func(t *testing.T) {
			changedBoot, changedFloor, changedState := boot, floor, actual.Copy()
			backend := app.financial.(*financialNativeApplication)
			saved := backend.store.head.Recovery
			originalOwned := backend.store.recoverySDK
			originalCertificate := saved.Certificate
			originalSeen := blocks.LoadSeenCommit(actual.LastBlockHeight)
			defer func() {
				saved.Certificate = originalCertificate
				backend.store.recoverySDK = originalOwned
				_ = blocks.SaveSeenCommit(actual.LastBlockHeight, originalSeen)
				blocks = cmtstore.NewBlockStore(blockDB)
			}()
			switch mode {
			case "wrong_floor":
				changedFloor.block = strings.Repeat("f", 64)
			case "newer_floor":
				changedFloor.height++
			case "sdk_state":
				changedState.AppHash = bytes.Repeat([]byte{0x77}, 32)
			case "seen_commit":
				bad := cloneFloorCommit(t, originalSeen)
				bad.Signatures[0].Signature[0] ^= 1
				if err := blocks.SaveSeenCommit(actual.LastBlockHeight, bad); err != nil {
					t.Fatal(err)
				}
				blocks = cmtstore.NewBlockStore(blockDB)
			case "invalid_certificate":
				bad := *saved.Certificate
				var signed types.SignedHeader
				if cmtjson.Unmarshal(bad.SignedHeader, &signed) != nil {
					t.Fatal("signed fixture")
				}
				signed.Commit.Signatures[0].Signature[0] ^= 1
				bad.SignedHeader, _ = cmtjson.Marshal(&signed)
				saved.Certificate = &bad
			case "validator_role":
				public := *boot.public
				public.Role = "VALIDATOR"
				changedBoot.public = &public
				changedBoot.ValidatorSeed = strings.Repeat("1", 64)
			case "missing_replay_ownership":
				backend.store.recoverySDK = nil
			}
			if err := checkOwnedRecoveryRestoredFloor(context.Background(), changedBoot, app, changedFloor, blocks, changedState); err == nil {
				t.Fatal("invalid floor binding accepted", mode)
			}
		})
	}
}

func floorFixtureSignBlock(t *testing.T, block *types.Block, keys []cmted.PrivKey, set *types.ValidatorSet) (*types.PartSet, *types.Commit) {
	t.Helper()
	parts, err := block.MakePartSet(types.BlockPartSizeBytes)
	if err != nil {
		t.Fatal(err)
	}
	id := types.BlockID{Hash: block.Hash(), PartSetHeader: parts.Header()}
	signatures := make([]types.CommitSig, len(set.Validators))
	for index, validator := range set.Validators {
		for _, key := range keys {
			if !bytes.Equal(key.PubKey().Address(), validator.Address) {
				continue
			}
			vote := &cmtproto.Vote{Type: cmtproto.PrecommitType, Height: block.Height, Round: 0, BlockID: id.ToProto(), Timestamp: block.Time, ValidatorAddress: validator.Address, ValidatorIndex: int32(index)}
			signature, err := key.Sign(types.VoteSignBytes(block.ChainID, vote))
			if err != nil {
				t.Fatal(err)
			}
			signatures[index] = types.CommitSig{BlockIDFlag: types.BlockIDFlagCommit, ValidatorAddress: validator.Address, Timestamp: block.Time, Signature: signature}
		}
	}
	return parts, &types.Commit{Height: block.Height, Round: 0, BlockID: id, Signatures: signatures}
}
func TestOwnedRecoveryFloorCaughtUpBeyondHistoryWindowWithOldProtectedFloor(t *testing.T) {
	app, boot, floor := recoveryFloorRestoredFixture(t)
	backend := app.financial.(*financialNativeApplication)
	origin, _, err := verifyFinancialCertificate(backend.store.head.Recovery.Certificate.packet())
	if err != nil {
		t.Fatal(err)
	}
	_, keyMap, _ := publicProtocolFixture(t)
	keys := []cmted.PrivKey{}
	for _, public := range boot.Genesis.Validators {
		keys = append(keys, cmted.PrivKey(keyMap[public]))
	}
	database := dbm.NewMemDB()
	defer database.Close()
	blocks := cmtstore.NewBlockStore(database)
	if err = blocks.SaveSeenCommit(floor.height-1, backend.store.recoverySDK.commit); err != nil {
		t.Fatal(err)
	}
	derived := *backend.store.recoverySDK
	derived.state = derived.state.Copy()
	current := origin.Header
	commit := origin.Commit
	set := validatorSet(boot.Genesis)
	last := floor.height + int64(HistoryLimit) + 3
	for height := floor.height; height <= last; height++ {
		commitFinancialSDK(t, app, nil)
		block := types.MakeBlock(height+1, nil, commit, nil)
		block.Header = *current
		block.Header.Height = height + 1
		block.Header.Time = time.Unix(0, backend.store.timeNs+1000000).UTC()
		block.Header.LastBlockID = commit.BlockID
		block.Header.AppHash = mustOwnedFloorRoot(app.state.StateRoot)
		block.Header.DataHash = types.Txs{}.Hash()
		block.Header.LastCommitHash = commit.Hash()
		parts, nextCommit := floorFixtureSignBlock(t, block, keys, set)
		if err = derived.advance(current, &block.Header, copyState(app.state)); err != nil {
			t.Fatal("actual original/header SDK derivation", err)
		}
		if block.Height <= last {
			blocks.SaveBlock(block, parts, nextCommit)
		}
		current = &block.Header
		commit = nextCommit
	}
	expectedState := derived.state.Copy()
	if err = app.Close(); err != nil {
		t.Fatal(err)
	}
	app, err = newFinancialLedger(boot.Genesis, boot.GenesisHash, boot.Root, false)
	if err != nil {
		t.Fatal("full cold replay of all genuine appended originals", err)
	}
	defer app.Close()
	if blocks.Base() != floor.height+1 || blocks.Height() != last || blocks.LoadBlockMeta(floor.height) != nil || len(app.history) > HistoryLimit {
		t.Fatal("caught-up/history-window boundary fixture")
	}
	for _, state := range app.history {
		if state.Height == floor.height-1 {
			t.Fatal("origin unexpectedly still in bounded app.history")
		}
	}
	if err = checkOwnedRecoveryRestoredFloor(context.Background(), boot, app, floor, blocks, expectedState); err != nil {
		t.Fatal("old protected floor with verified real forward extension", err)
	}
	gapDB := dbm.NewMemDB()
	defer gapDB.Close()
	gap := cmtstore.NewBlockStore(gapDB)
	if err = gap.SaveSeenCommit(floor.height-1, app.financial.(*financialNativeApplication).store.recoverySDK.commit); err != nil {
		t.Fatal(err)
	}
	for height := blocks.Base() + 1; height <= blocks.Height(); height++ {
		block := blocks.LoadBlock(height)
		parts, e := block.MakePartSet(types.BlockPartSizeBytes)
		if e != nil {
			t.Fatal(e)
		}
		gap.SaveBlock(block, parts, blocks.LoadSeenCommit(height))
	}
	if err = checkOwnedRecoveryRestoredFloor(context.Background(), boot, app, floor, gap, expectedState); err == nil {
		t.Fatal("missing first actual SDK bridge block accepted")
	}
	badState := expectedState.Copy()
	badState.LastBlockID.Hash = bytes.Repeat([]byte{0x33}, 32)
	if err = checkOwnedRecoveryRestoredFloor(context.Background(), boot, app, floor, blocks, badState); err == nil {
		t.Fatal("forked SDK head accepted")
	}
	originalSeen := blocks.LoadSeenCommit(last)
	bad := cloneFloorCommit(t, originalSeen)
	bad.Signatures[0].Signature[0] ^= 1
	if err = blocks.SaveSeenCommit(last, bad); err != nil {
		t.Fatal(err)
	}
	blocks = cmtstore.NewBlockStore(database)
	if err = checkOwnedRecoveryRestoredFloor(context.Background(), boot, app, floor, blocks, expectedState); err == nil {
		t.Fatal("invalid actual latest quorum commit accepted")
	}
	if err = blocks.SaveSeenCommit(last, originalSeen); err != nil {
		t.Fatal(err)
	}
	blocks = cmtstore.NewBlockStore(database)
	if err = checkOwnedRecoveryRestoredFloor(context.Background(), boot, app, ownedRecoveryFloor{height: floor.height, block: strings.Repeat("0", 64)}, blocks, expectedState); err == nil {
		t.Fatal("old floor fork accepted after catch-up")
	}
}

func TestOwnedRecoveryFloorSDKChild(t *testing.T) {
	if os.Getenv("GG_PRIVATE_RECOVERY_FLOOR_CHILD") != "1" {
		return
	}
	if err := runOwnedProtocolStart(os.Stdin, os.Stdout, os.Getppid()); err != nil {
		_ = writeOwnedRestoreFrame(os.Stdout, map[string]any{"error": err.Error()})
		os.Exit(1)
	}
	os.Exit(0)
}
func TestOwnedRecoveryFloorActualOwnedNormalReplicaRestartsTwice(t *testing.T) {
	app, boot, floor := recoveryFloorRestoredFixture(t)
	if err := app.Close(); err != nil {
		t.Fatal(err)
	}
	// Same existing170s test budget; no compiler/runtime helper/policy expansion.
	ctx, cancel := context.WithTimeout(context.Background(), 170*time.Second)
	defer cancel()
	for attemptIndex := 0; attemptIndex < 2; attemptIndex++ {
		public := *boot.public
		public.P2PPort = ownedRestoreFreePort(t)
		public.RPCPort = ownedRestoreFreePort(t)
		for public.RPCPort == public.P2PPort {
			public.RPCPort = ownedRestoreFreePort(t)
		}
		serializedBootstrap := ownedRestoreCanonical(public)
		if _, decodeErr := decodeNativeBootstrap(serializedBootstrap); decodeErr != nil {
			t.Fatalf("parent exact serialized bootstrap decode: %v", decodeErr)
		}
		rejected := floorRejectedOwnedLayout(t, boot.Root)
		t.Logf("parent samebytes bootstrap decode PASS; actual rejected layout entries=%q", rejected)
		child := exec.CommandContext(ctx, os.Args[0], "-test.run=^TestOwnedRecoveryFloorSDKChild$", "-test.v=false")
		ownedRestoreTestChildFlags(child)
		child.Env = append(os.Environ(), "GG_PRIVATE_RECOVERY_FLOOR_CHILD=1")
		stdin, err := child.StdinPipe()
		if err != nil {
			t.Fatal(err)
		}
		stdout, err := child.StdoutPipe()
		if err != nil {
			t.Fatal(err)
		}
		if err = child.Start(); err != nil {
			t.Fatal(err)
		}
		done := make(chan error, 1)
		go func() { done <- child.Wait() }()
		stop := func() {
			_ = child.Process.Kill()
			select {
			case <-done:
			case <-time.After(3 * time.Second):
				t.Error("owned restart child not terminal")
			}
		}
		defer func() {
			if child.ProcessState == nil {
				stop()
			}
		}()
		attempt := fmt.Sprintf("%032x", attemptIndex+1)
		request := ownedProtocolStartRequest{Schema: "gg.native.owned-protocol-start.v1", Attempt: attempt, Bootstrap: serializedBootstrap, FloorHeight: floor.height, FloorBlock: floor.block}
		if err = writeOwnedRestoreFrame(stdin, request); err != nil {
			t.Fatal(err)
		}
		reader := bufio.NewReaderSize(stdout, ownedRestoreFrameMax)
		prepared := false
		ready := false
		lastPhase, lastWork := "UNOBSERVED", "UNOBSERVED"
		for !ready {
			var frame map[string]json.RawMessage
			if err = readOwnedRestoreFrame(reader, &frame); err != nil {
				t.Fatal("actual normal restart pipe", err)
			}
			var schema string
			if json.Unmarshal(frame["schema"], &schema) != nil {
				t.Fatalf("schema: actual_owned_child_pid=%d last_recovery_phase=%s last_completed_work=%s consumed_native_frame=%s", child.Process.Pid, lastPhase, lastWork, ownedRestoreCanonical(frame))
			}
			switch schema {
			case "gg.native.owned-recovery-progress.v1":
				lastPhase = string(frame["phase"])
				lastWork = string(frame["work_done"])
				if prepared {
					t.Fatal("progress after prepared")
				}
			case "gg.consensus.protocol-prepared.v1":
				if prepared {
					t.Fatal("duplicate prepared")
				}
				prepared = true
				client := &http.Client{Timeout: 3 * time.Second}
				response, e := client.Get(fmt.Sprintf("http://127.0.0.1:%d/status", public.RPCPort))
				if e != nil {
					t.Fatal(e)
				}
				body, e := io.ReadAll(io.LimitReader(response.Body, 65537))
				_ = response.Body.Close()
				client.CloseIdleConnections()
				if e != nil || !bytes.Contains(body, []byte(`"voting_power":"0"`)) {
					t.Fatal("actual SDK prepared replica voting power", e)
				}
				ack := ownedRecoveryStartAck{Schema: "gg.native.owned-recovery-start-ack.v1", Attempt: attempt, PID: child.Process.Pid, Anchor: boot.GenesisHash, Root: boot.Root, Profile: json.RawMessage("null")}
				if err = writeOwnedRestoreFrame(stdin, ack); err != nil {
					t.Fatal(err)
				}
				_ = stdin.Close()
			case "gg.consensus.protocol-ready.v1":
				if !prepared {
					t.Fatal("ready before prepared")
				}
				if string(frame["consensus_signing"]) != "false" || string(frame["role"]) != `"REPLICA"` {
					t.Fatal("replica acquired signing")
				}
				ready = true
			default:
				t.Fatal("actual restart failed", schema, string(ownedRestoreCanonical(frame)))
			}
		}
		stop()
	}
}

func cloneFloorCommit(t *testing.T, commit *types.Commit) *types.Commit {
	t.Helper()
	raw, err := cmtjson.Marshal(commit)
	if err != nil {
		t.Fatal(err)
	}
	var cloned types.Commit
	if cmtjson.Unmarshal(raw, &cloned) != nil {
		t.Fatal("commit clone")
	}
	return &cloned
}

// Bounded fixture-only metadata diagnostic:64-entry directory batches,
// <=512 total entries/depth16, <=16 rejected names/types; no file contents.
func floorRejectedOwnedLayout(t *testing.T, root string) []string {
	t.Helper()
	type directory struct {
		path  string
		depth int
	}
	pending := []directory{{root, 0}}
	rejected := []string{}
	count := 0
	for len(pending) > 0 {
		current := pending[len(pending)-1]
		pending = pending[:len(pending)-1]
		file, err := os.Open(current.path)
		if err != nil {
			t.Fatal("fixture layout directory open", err)
		}
		for {
			entries, readErr := file.ReadDir(64)
			for _, entry := range entries {
				count++
				if count > 512 {
					_ = file.Close()
					t.Fatal("fixture layout diagnostic entry bound")
				}
				path := filepath.Join(current.path, entry.Name())
				info, err := os.Lstat(path)
				if err != nil {
					_ = file.Close()
					t.Fatal("fixture layout entry stat", err)
				}
				relative, err := filepath.Rel(root, path)
				if err != nil {
					_ = file.Close()
					t.Fatal(err)
				}
				accepted := ownedNativeLayout(relative, info.IsDir())
				if !accepted {
					rejected = append(rejected, fmt.Sprintf("%s:%s", filepath.ToSlash(relative), info.Mode().String()))
					if len(rejected) == 16 {
						_ = file.Close()
						return rejected
					}
				}
				if info.IsDir() && info.Mode()&os.ModeSymlink == 0 && accepted {
					if current.depth >= 16 {
						_ = file.Close()
						t.Fatal("fixture layout diagnostic depth bound")
					}
					pending = append(pending, directory{path, current.depth + 1})
				}
			}
			if readErr == io.EOF {
				break
			}
			if readErr != nil {
				_ = file.Close()
				t.Fatal("fixture layout directory read", readErr)
			}
		}
		if err = file.Close(); err != nil {
			t.Fatal("fixture layout directory close", err)
		}
	}
	return rejected
}
