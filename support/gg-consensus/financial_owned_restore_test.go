//go:build !js

package main

// These cases execute real signed originals, filesystem stores and pinned SDK
// encodings in-process. They do not claim live peer connectivity or node rejoin.
import (
	"bufio"
	"bytes"
	"context"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	abci "github.com/cometbft/cometbft/abci/types"
	cmted "github.com/cometbft/cometbft/crypto/ed25519"
	cmtjson "github.com/cometbft/cometbft/libs/json"
)

func ownedRestoreFixture(t *testing.T) (financialArchiveCommand, Bootstrap, []byte, string) {
	t.Helper()
	app, backend, keys, producers, source := publicProtocolSDKFixture(t)
	payer := keys[publicFixtureAddress(publicFixtureKey("payer"))]
	receiver := publicFixtureAddress(publicFixtureKey("owned-restore-recipient"))
	_, original, block := publicFixtureBlock(t, backend.current, producers[0], publicFixtureKey("owned-restore-worker"),
		[]Envelope{publicFixturePayment(backend.current, payer, receiver, 0, "3")})
	commitFinancialSDK(t, app, publicFixtureBatch(t, backend.current, nil, original))
	commitFinancialSDK(t, app, nil)
	state, genesis, anchor := copyState(app.state), app.genesis, app.anchor
	if err := app.Close(); err != nil {
		t.Fatal(err)
	}
	signers := []cmted.PrivKey{}
	for _, public := range genesis.Validators {
		signers = append(signers, cmted.PrivKey(keys[public]))
	}
	signed := financialFixtureSDKChain(t, genesis, anchor, source, state, signers)
	header, err := cmtjson.Marshal(signed)
	if err != nil {
		t.Fatal(err)
	}
	certificate := dagArchiveCertificate{Schema: "gg.consensus.proof.v1", Genesis: genesis, GenesisHash: anchor, State: state, SignedHeader: header}
	command := financialArchiveCommand{Genesis: genesis, GenesisHash: anchor, Root: source, Certificate: &certificate}
	var archive bytes.Buffer
	if _, err = exportFinancialArchive(context.Background(), &archive, command); err != nil {
		t.Fatal(err)
	}
	command.Root = ""
	command.ArchivePath = filepath.Join(t.TempDir(), "actual-signed-originals.ggfin")
	command.RestoreRoot = filepath.Join(t.TempDir(), "owned-native")
	if err = os.WriteFile(command.ArchivePath, archive.Bytes(), 0600); err != nil {
		t.Fatal(err)
	}
	fresh := false
	node := publicFixtureKey("owned-restore-replica")
	public := nativePublicBootstrap{ExpectedFresh: &fresh, Genesis: genesis, GenesisHash: anchor, ListenHost: "127.0.0.1", MaxInbound: 0,
		MaxOutbound: 1, NodeSeed: hex.EncodeToString(node.Seed()), P2PPort: 25031, RPCPort: 25032,
		Peers: []Peer{{ID: membershipNodeID(genesis.Protocol.Committee.Members[0].NodeKey), Host: "127.0.0.1", Port: 25033}},
		Role:  "REPLICA", Root: command.RestoreRoot, Schema: nativePublicBootstrapSchema}
	boot, err := ownedRestoreBootstrap(canonical(public))
	if err != nil {
		t.Fatal(err)
	}
	return command, boot, archive.Bytes(), block
}

func auditOwnedRestore(t *testing.T, command financialArchiveCommand) (*os.File, os.FileInfo, *financialSDKRecovery, string) {
	t.Helper()
	file, info, err := openFinancialArchiveInput(command.ArchivePath)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = file.Close() })
	var sdk *financialSDKRecovery
	result, err := readFinancialArchiveUsing(context.Background(), file, command, nil, func(cursor *financialArchiveReplay) error {
		sdk = cursor.sdkRecovery
		return nil
	})
	if err != nil || sdk == nil {
		t.Fatal("independent actual archive audit", err)
	}
	return file, info, sdk, result["archive_sha256"].(string)
}

func TestFinancialOwnedRestoreHandoffKeepsExactLedgerAndColdRoots(t *testing.T) {
	command, boot, raw, block := ownedRestoreFixture(t)
	file, info, sdk, digest := auditOwnedRestore(t, command)
	owned, result, err := restoreFinancialOwned(context.Background(), file, info, command, boot, sdk, digest, nil, nil)
	if err != nil || owned == nil || owned.app == nil || result["native_node_ready"] != false || digest != hashHex(raw) {
		t.Fatal("actual owned replay", err)
	}
	defer owned.close()
	before := owned.app
	store := before.financial.(*financialNativeApplication).store
	app, err := owned.take(boot)
	if err != nil || app != before || app.financial.(*financialNativeApplication).store != store {
		t.Fatal("ledger/store ownership changed", err)
	}
	defer app.Close()
	if _, err = owned.take(boot); err == nil {
		t.Fatal("ownership cell reused")
	}
	if !bytes.Equal(canonical(app.state), canonical(command.Certificate.State)) || store.health() != nil || store.verifiedThrough != app.state.Height {
		t.Fatal("retained replay boundary changed")
	}
	status, through, err := app.financial.(*financialNativeApplication).LocalHistoryStatus(context.Background())
	if err != nil || status["state"] != "READY" || status["verified_through"] != fmt.Sprint(app.state.Height) || through != app.state.Height ||
		status["retained_through"] != fmt.Sprint(app.state.Height) || status["checkpoint_trusted"] != false {
		t.Fatal("retained ledger local full-replay report", err)
	}
	verifiedThrough := status["verified_through"]
	// The replay scratch databases have already closed. These actual selected
	// account/registry/receipt reads must use the retained store's readers.
	backend := app.financial.(*financialNativeApplication)
	account := publicFixtureAddress(publicFixtureKey("owned-restore-recipient"))
	if _, err = backend.Account(context.Background(), app.state, account); err != nil {
		t.Fatal("account still bound to closed scratch", err)
	}
	if _, err = backend.Registry(context.Background(), app.state, protocolRegistrySelector{Namespace: "producers", Key: app.genesis.FinancialDAG.Producers[0]}); err != nil {
		t.Fatal("registry still bound to closed scratch", err)
	}
	if _, err = backend.Receipt(context.Background(), app.state, financialReceiptSelector{Block: block, Index: 0}); err != nil {
		t.Fatal("derived receipt not retained", err)
	}
	response, err := app.Info(context.Background(), &abci.RequestInfo{})
	if err != nil || response.LastBlockHeight != app.state.Height {
		t.Fatal("ABCI handoff not at real replay height", err)
	}
	// Subsequent actual execution uses the very same ledger, then cold replay
	// independently reconstructs the same state and receipt after its close.
	commitFinancialSDK(t, app, nil)
	status, through, err = backend.LocalHistoryStatus(context.Background())
	if err != nil || status["verified_through"] != verifiedThrough || status["retained_through"] != fmt.Sprint(app.state.Height) || through != app.state.Height ||
		status["active_original_count"] != fmt.Sprint(app.state.Height) || status["archived_original_count"] != "0" {
		t.Fatal("new commit relabeled cold audit or journal range", err)
	}
	saved := canonical(app.state)
	if err = app.Close(); err != nil {
		t.Fatal(err)
	}
	cold, err := newFinancialLedger(command.Genesis, command.GenesisHash, command.RestoreRoot, false)
	if err != nil {
		t.Fatal("cold full replay after continued execution", err)
	}
	defer cold.Close()
	if !bytes.Equal(saved, canonical(cold.state)) {
		t.Fatal("cold root/state changed")
	}
	if _, err = cold.financial.(*financialNativeApplication).Receipt(context.Background(), cold.state, financialReceiptSelector{Block: block, Index: 0}); err != nil {
		t.Fatal("cold actual original receipt", err)
	}
	coldBackend := cold.financial.(*financialNativeApplication)
	if _, err = coldBackend.Account(context.Background(), cold.state, account); err != nil {
		t.Fatal(err)
	}
	// Corrupt a genuinely required active original in the real disposable DB;
	// the same retained C16 fault latch must reject warm-cache reads/new work.
	key := financialHeightKey(cold.state.Height)
	if err = coldBackend.store.db.Delete([]byte(key), nil); err != nil {
		t.Fatal(err)
	}
	if _, err = coldBackend.store.history.requiredRead(context.Background(), func(key string) ([]byte, error) {
		return coldBackend.store.history.get(context.Background(), key)
	}, key); err == nil {
		t.Fatal("missing required actual original accepted")
	}
	status, _, err = coldBackend.LocalHistoryStatus(context.Background())
	if err != nil || status["state"] != "UNAVAILABLE" || status["archive_fault"] != "GG_FINANCIAL_HISTORY_UNAVAILABLE" ||
		status["verified_through"] != fmt.Sprint(cold.state.Height) {
		t.Fatal("retained fault latch/report", err)
	}
	if _, err = coldBackend.Account(context.Background(), cold.state, account); err == nil {
		t.Fatal("warm proof escaped known history fault")
	}
	if _, err = coldBackend.CheckTx(context.Background(), &abci.RequestCheckTx{}); err == nil {
		t.Fatal("new work escaped known history fault")
	}
	if result, err := verifyInput(command.Certificate.packet()); err != nil || result["verified"] != true {
		t.Fatal("retained historical certificate changed", err)
	}
	for _, forbidden := range []string{"data/priv_validator_state.json", "config/priv_validator_key.json"} {
		if _, err = os.Lstat(filepath.Join(command.RestoreRoot, filepath.FromSlash(forbidden))); !os.IsNotExist(err) {
			t.Fatal("nonvoting restore created/imported voter signing state")
		}
	}
}

func TestFinancialOwnedRestoreIdentityAndSignerBoundaries(t *testing.T) {
	command, boot, _, _ := ownedRestoreFixture(t)
	for _, mutation := range []func(*nativePublicBootstrap){
		func(value *nativePublicBootstrap) { value.Role = "VALIDATOR" },
		func(value *nativePublicBootstrap) { value.ValidatorSeed = value.NodeSeed },
		func(value *nativePublicBootstrap) { fresh := true; value.ExpectedFresh = &fresh },
	} {
		bad := *boot.public
		mutation(&bad)
		if _, err := ownedRestoreBootstrap(canonical(bad)); err == nil {
			t.Fatal("voter/fresh authority admitted to restore")
		}
	}
	file, info, sdk, digest := auditOwnedRestore(t, command)
	owned, _, err := restoreFinancialOwned(context.Background(), file, info, command, boot, sdk, digest, nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer owned.close()
	changed := boot
	public := *boot.public
	changed.public = &public
	changed.NodeSeed = hex.EncodeToString(publicFixtureKey("different-owned-replica").Seed())
	changed.public.NodeSeed = changed.NodeSeed
	if _, err = owned.take(changed); err == nil {
		t.Fatal("different protected node identity took retained ledger")
	}
	if owned.used || owned.app == nil {
		t.Fatal("bad identity consumed correct handoff")
	}
}

func TestFinancialOwnedRestoreDurableFaultsResumeExactOriginals(t *testing.T) {
	for _, point := range []string{"INTENT_AFTER_SYNC", "APP_PHASE_AFTER_SYNC", "SDK_PHASE_AFTER_SYNC", "ROOT_MARKER_AFTER_LINK", "COMPLETE_AFTER_SYNC"} {
		t.Run(point, func(t *testing.T) {
			command, boot, _, _ := ownedRestoreFixture(t)
			file, info, sdk, digest := auditOwnedRestore(t, command)
			sentinel := errors.New("public-owned-storage-fault")
			owned, _, err := restoreFinancialOwned(context.Background(), file, info, command, boot, sdk, digest,
				func(actual string) error {
					if actual == point {
						return sentinel
					}
					return nil
				}, nil)
			if err != sentinel || owned != nil {
				t.Fatal("failed attempt escaped ledger or lost fault identity", err)
			}
			_, _ = file.Seek(0, io.SeekStart)
			file2, info2, sdk2, digest2 := auditOwnedRestore(t, command)
			owned, _, err = restoreFinancialOwned(context.Background(), file2, info2, command, boot, sdk2, digest2, nil, nil)
			if err != nil || owned == nil || !bytes.Equal(canonical(owned.app.state), canonical(command.Certificate.State)) {
				t.Fatal("exact explicit resume failed", err)
			}
			if err = owned.close(); err != nil {
				t.Fatal(err)
			}
		})
	}
}

func TestFinancialOwnedRestoreCancelAndArchiveChangeNeverEscapeLedger(t *testing.T) {
	command, boot, _, _ := ownedRestoreFixture(t)
	file, info, sdk, digest := auditOwnedRestore(t, command)
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if owned, _, err := restoreFinancialOwned(ctx, file, info, command, boot, sdk, digest, nil, nil); owned != nil || !errors.Is(err, context.Canceled) {
		t.Fatal("cancelled restore changed authority", err)
	}
	if _, err := os.Lstat(boot.Root); !os.IsNotExist(err) {
		t.Fatal("cancelled entry created root")
	}
	appendFile, err := os.OpenFile(command.ArchivePath, os.O_APPEND|os.O_WRONLY, 0600)
	if err != nil {
		t.Fatal(err)
	}
	_, writeErr := appendFile.Write([]byte("changed"))
	closeErr := appendFile.Close()
	if writeErr != nil || closeErr != nil {
		t.Fatal(writeErr, closeErr)
	}
	if owned, _, err := restoreFinancialOwned(context.Background(), file, info, command, boot, sdk, digest, nil, nil); owned != nil || err == nil {
		t.Fatal("changed audited archive produced ledger")
	}
}

func TestFinancialOwnedRestoreFramesAreCanonicalExactAndBounded(t *testing.T) {
	ack := financialOwnedRestoreAck{Archive: strings.Repeat("a", 64), GenesisHash: strings.Repeat("b", 64), PID: os.Getpid(), Phase: "RESTORE", Schema: "gg.native.owned-archive-ack.v1"}
	var valid bytes.Buffer
	if err := writeOwnedRestoreFrame(&valid, ack); err != nil {
		t.Fatal(err)
	}
	if err := ownedRestoreAck(bufio.NewReaderSize(bytes.NewReader(valid.Bytes()), ownedRestoreFrameMax), ack.Archive, ack.GenesisHash, "RESTORE"); err != nil {
		t.Fatal("actual canonical ack", err)
	}
	for _, raw := range [][]byte{
		[]byte("{\"schema\":\"x\",\"schema\":\"y\"}\n"),
		bytes.TrimSuffix(valid.Bytes(), []byte("\n")),
		[]byte(strings.Repeat("x", ownedRestoreFrameMax+1) + "\n"),
		bytes.Replace(valid.Bytes(), []byte("RESTORE"), []byte("START"), 1),
		append([]byte(" "), valid.Bytes()...),
	} {
		if err := ownedRestoreAck(bufio.NewReaderSize(bytes.NewReader(raw), ownedRestoreFrameMax), ack.Archive, ack.GenesisHash, "RESTORE"); err == nil {
			t.Fatal("invalid/foreign/oversized ack accepted")
		}
	}
	// Cross-language envelope order is normalized recursively without changing
	// consensus signature bytes or the original archived certificate.
	var shape map[string]any
	if json.Unmarshal(valid.Bytes(), &shape) != nil || !bytes.Equal(bytes.TrimSpace(valid.Bytes()), canonical(shape)) {
		t.Fatal("private envelope is not sorted-map canonical JSON")
	}
}

func TestFinancialOwnedRestoreSeedlessAuditAndForeignGrantBeforeWrites(t *testing.T) {
	command, boot, _, _ := ownedRestoreFixture(t)
	request := financialOwnedRestoreRequest{ArchivePath: command.ArchivePath, Genesis: command.Genesis, GenesisHash: command.GenesisHash,
		NodeKey: publicFixtureAddress(publicFixtureKey("owned-restore-replica")), Root: command.RestoreRoot, Schema: "gg.native.owned-archive-start.v1"}
	raw := ownedRestoreCanonical(request)
	if bytes.Contains(raw, []byte("node_seed")) || bytes.Contains(raw, []byte("validator_seed")) || bytes.Contains(raw, []byte("bootstrap")) {
		t.Fatal("initial audit request contains private bootstrap material")
	}
	for _, foreign := range []bool{false, true} {
		public := *boot.public
		if foreign {
			public.NodeSeed = hex.EncodeToString(publicFixtureKey("foreign-valid-replica-key").Seed())
		}
		grant := financialOwnedRestoreGrant{Archive: strings.Repeat("a", 64), Bootstrap: ownedRestoreCanonical(public), GenesisHash: command.GenesisHash,
			Phase: "RESTORE", PID: os.Getpid(), Schema: "gg.native.owned-archive-restore.v1"}
		var input bytes.Buffer
		if err := writeOwnedRestoreFrame(&input, grant); err != nil {
			t.Fatal(err)
		}
		_, _, err := readOwnedRestoreGrant(bufio.NewReaderSize(&input, ownedRestoreFrameMax), request, grant.Archive)
		if (err != nil) != foreign {
			t.Fatal("foreign/exact protected bootstrap binding", foreign, err)
		}
		if _, err = os.Lstat(command.RestoreRoot); !os.IsNotExist(err) {
			t.Fatal("grant validation wrote target before authority checks")
		}
	}
}

func ownedRestoreFreePort(t *testing.T) int {
	t.Helper()
	listener, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	port := listener.Addr().(*net.TCPAddr).Port
	if err = listener.Close(); err != nil {
		t.Fatal(err)
	}
	return port
}

// Helper entry point in the SAME compiled test executable. No compiler, new
// fixture authority or relaxed resource policy exists inside a test process.
func TestFinancialOwnedRestorePublicFixtureExport(t *testing.T) {
	if os.Getenv("GG_OWNED_RESTORE_SDK_CHILD") != "1" {
		if directory := os.Getenv("GG_OWNED_RESTORE_ACCEPTANCE_DIR"); directory != "" {
			command, _, raw, _ := ownedRestoreFixture(t)
			writeOwnedRestorePublicFixture(t, directory, command, raw)
		}
		return
	}
	var retained *Ledger
	err := runFinancialOwnedRestoreStartUsing(os.Stdin, os.Stdout, os.Getppid(), func(app *Ledger) { retained = app }, func(app *Ledger) {
		if retained == nil || app != retained || app.financial.(*financialNativeApplication).store.health() != nil {
			os.Exit(2)
		}
		if writeOwnedRestoreFrame(os.Stdout, map[string]any{"schema": "gg.private.actual-ledger-identity.v1", "pid": os.Getpid(),
			"same_ledger": app == retained, "state_root": app.state.StateRoot}) != nil {
			os.Exit(3)
		}
	})
	if err != nil {
		os.Exit(1)
	}
	os.Exit(0)
}

func TestFinancialOwnedRestoreStartsActualNonvotingSDKInSameOwnedPID(t *testing.T) {
	low := &nativeResources{Schema: "gg.native.resources.v1", Mode: "LOW", GoMaxProcs: 2, VerifyWorkers: 8,
		GoHeapBytes: 256 << 20, ProcessMemoryBytes: 512 << 20, VirtualBytes: 8 << 30, OpenFiles: 1024,
		OwnerCPUBasisPoints: 10000, MaximumNativeChildren: 6}
	server := *low
	server.Mode, server.GoMaxProcs, server.VerifyWorkers, server.OwnerMemoryBytes = "SERVER", 4, 4, 1<<30
	for _, test := range []struct {
		name    string
		profile *nativeResources
	}{{"legacy", nil}, {"LOW", low}, {"SERVER4", &server}} {
		t.Run(test.name, func(t *testing.T) { testFinancialOwnedRestoreActualSDKProfile(t, test.profile) })
	}
}

func testFinancialOwnedRestoreActualSDKProfile(t *testing.T, profile *nativeResources) {
	t.Helper()
	command, boot, raw, _ := ownedRestoreFixture(t)
	// This test uses loopback only and does not claim peer quorum or contact.
	public := *boot.public
	public.Resources = profile
	public.P2PPort, public.RPCPort = ownedRestoreFreePort(t), ownedRestoreFreePort(t)
	for public.RPCPort == public.P2PPort {
		public.RPCPort = ownedRestoreFreePort(t)
	}
	public.Peers[0].Port = ownedRestoreFreePort(t)
	bootstrap := ownedRestoreCanonical(public)
	ctx, cancel := context.WithTimeout(context.Background(), 170*time.Second)
	defer cancel()
	child := exec.CommandContext(ctx, os.Args[0], "-test.run=^TestFinancialOwnedRestorePublicFixtureExport$", "-test.v=false")
	ownedRestoreTestChildFlags(child)
	child.Env = append(os.Environ(), "GG_OWNED_RESTORE_SDK_CHILD=1")
	if profile != nil {
		child.Env = nil
		for _, entry := range os.Environ() {
			if !strings.HasPrefix(entry, "GOMAXPROCS=") && !strings.HasPrefix(entry, "GOMEMLIMIT=") {
				child.Env = append(child.Env, entry)
			}
		}
		child.Env = append(child.Env, "GG_OWNED_RESTORE_SDK_CHILD=1", fmt.Sprintf("GOMAXPROCS=%d", profile.GoMaxProcs),
			fmt.Sprintf("GOMEMLIMIT=%dB", profile.GoHeapBytes))
	}
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
	defer func() {
		_ = child.Process.Kill()
		select {
		case <-done:
		case <-time.After(3 * time.Second):
			t.Error("exact owned SDK helper did not become terminal")
		}
	}()
	request := financialOwnedRestoreRequest{Resources: profile, ArchivePath: command.ArchivePath, Genesis: command.Genesis, GenesisHash: command.GenesisHash,
		NodeKey: publicFixtureAddress(publicFixtureKey("owned-restore-replica")), Root: command.RestoreRoot, Schema: "gg.native.owned-archive-start.v1"}
	if err = writeOwnedRestoreFrame(stdin, request); err != nil {
		t.Fatal(err)
	}
	reader := bufio.NewReaderSize(stdout, ownedRestoreFrameMax)
	phase := 0
	for {
		var frame map[string]json.RawMessage
		if err = readOwnedRestoreFrame(reader, &frame); err != nil {
			t.Fatal("actual native pipe", err)
		}
		var schema string
		if json.Unmarshal(frame["schema"], &schema) != nil {
			t.Fatal("actual native schema")
		}
		switch schema {
		case "gg.native.owned-archive-progress.v1":
			continue
		case "gg.native.owned-archive-audited.v1":
			if phase != 0 {
				t.Fatal("duplicate audit")
			}
			phase = 1
			// This is the exact protected-controller boundary; the Python test
			// below additionally exercises its real durable profile commit.
			grant := financialOwnedRestoreGrant{Archive: hashHex(raw), Bootstrap: bootstrap, GenesisHash: command.GenesisHash,
				Phase: "RESTORE", PID: child.Process.Pid, Schema: "gg.native.owned-archive-restore.v1"}
			if err = writeOwnedRestoreFrame(stdin, grant); err != nil {
				t.Fatal(err)
			}
		case "gg.native.owned-archive-restored.v1":
			if phase != 1 {
				t.Fatal("restore before audit")
			}
			phase = 2
			ack := financialOwnedRestoreAck{Archive: hashHex(raw), GenesisHash: command.GenesisHash, Phase: "START", PID: child.Process.Pid, Schema: "gg.native.owned-archive-ack.v1"}
			if err = writeOwnedRestoreFrame(stdin, ack); err != nil {
				t.Fatal(err)
			}
			_ = stdin.Close()
		case "gg.consensus.protocol-ready.v1":
			if phase != 2 {
				t.Fatal("SDK ready before durable acknowledgements")
			}
			var pid int
			if json.Unmarshal(frame["pid"], &pid) != nil || pid != child.Process.Pid {
				t.Fatal("native PID changed")
			}
			if profile != nil {
				var actual struct {
					Resources struct {
						Profile nativeResources `json:"profile"`
					} `json:"resources"`
					Send int64 `json:"sdk_send_bytes_per_second"`
					Recv int64 `json:"sdk_recv_bytes_per_second"`
				}
				rate, rateErr := nativeSDKResourceRate(profile)
				if json.Unmarshal(ownedRestoreCanonical(frame), &actual) != nil || rateErr != nil ||
					actual.Resources.Profile != *profile || actual.Send != rate || actual.Recv != rate {
					t.Fatal("actual canonical READY lost exact resource profile or SDK rates")
				}
			}
			phase = 3
		case "gg.private.actual-ledger-identity.v1":
			var same bool
			if phase != 3 || json.Unmarshal(frame["same_ledger"], &same) != nil || !same {
				t.Fatal("real SDK creator did not use retained ledger")
			}
			phase = 4
		default:
			t.Fatal("unexpected actual native frame")
		}
		if phase == 4 {
			break
		}
	}
	client := &http.Client{Timeout: 3 * time.Second}
	defer client.CloseIdleConnections()
	requestHTTP, err := http.NewRequestWithContext(ctx, "GET", fmt.Sprintf("http://127.0.0.1:%d/status", public.RPCPort), nil)
	if err != nil {
		t.Fatal(err)
	}
	response, err := client.Do(requestHTTP)
	if err != nil {
		t.Fatal("actual owned SDK RPC", err)
	}
	body, readErr := io.ReadAll(io.LimitReader(response.Body, 65537))
	closeErr := response.Body.Close()
	var status struct {
		Result struct {
			NodeInfo struct {
				Network string `json:"network"`
			} `json:"node_info"`
			ValidatorInfo struct {
				Power string `json:"voting_power"`
			} `json:"validator_info"`
		} `json:"result"`
	}
	if readErr != nil || closeErr != nil || len(body) > 65536 || json.Unmarshal(body, &status) != nil ||
		status.Result.NodeInfo.Network != command.Genesis.ChainID || status.Result.ValidatorInfo.Power != "0" {
		t.Fatal("actual nonvoting SDK identity/RPC")
	}

}

func writeOwnedRestorePublicFixture(t *testing.T, directory string, command financialArchiveCommand, raw []byte) {
	t.Helper()
	if !filepath.IsAbs(directory) || !realArchiveDirectory(directory) {
		t.Fatal("explicit owned fixture directory")
	}
	entries, err := os.ReadDir(directory)
	if err != nil || len(entries) != 0 {
		t.Fatal("fixture target must be new and empty")
	}
	for name, content := range map[string][]byte{"pin.json": ownedRestoreCanonical(map[string]any{"genesis": command.Genesis, "genesis_hash": command.GenesisHash}), "originals.ggfin": raw} {
		file, err := os.OpenFile(filepath.Join(directory, name), os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
		if err != nil {
			t.Fatal(err)
		}
		_, writeErr := file.Write(content)
		syncErr := file.Sync()
		closeErr := file.Close()
		if writeErr != nil || syncErr != nil || closeErr != nil {
			t.Fatal("public fixture write")
		}
	}
}
