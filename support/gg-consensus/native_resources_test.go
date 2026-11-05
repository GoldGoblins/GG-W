//go:build !js

package main

import (
	"bufio"
	"bytes"
	"context"
	"crypto/ed25519"
	"encoding/hex"
	"os"
	"runtime"
	"runtime/debug"
	"strconv"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	cfg "github.com/cometbft/cometbft/config"
)

func serverResourceFixture() *nativeResources {
	return &nativeResources{Schema: "gg.native.resources.v1", Mode: "SERVER",
		GoMaxProcs: 32, VerifyWorkers: 32, GoHeapBytes: 256 << 20,
		ProcessMemoryBytes: 512 << 20, VirtualBytes: 8 << 30, OpenFiles: 1024,
		OwnerMemoryBytes: 1 << 30, OwnerCPUBasisPoints: 10000, MaximumNativeChildren: 6}
}

func TestNativeResourcesMaximum256SelectionIsExplicitAndBounded(t *testing.T) {
	isolateNativeResources(t)
	profile := serverResourceFixture()
	profile.GoMaxProcs, profile.VerifyWorkers = 256, 256
	runtime.GOMAXPROCS(256)
	debug.SetMemoryLimit(profile.GoHeapBytes)
	if bindNativeResources(profile) != nil || dagTxSignatureWorkerMaximum() != 256 ||
		dagTxSignatureWorkers(5000, runtime.GOMAXPROCS(0)) != 256 ||
		dagTxSignatureWorkers(1, 256) != 1 {
		t.Fatal("explicit finite server selection truncated or unbounded")
	}
}

func TestNativeResourcesServerFailureJoinsEveryInFlightWorker(t *testing.T) {
	isolateNativeResources(t)
	profile := serverResourceFixture()
	runtime.GOMAXPROCS(32)
	debug.SetMemoryLimit(profile.GoHeapBytes)
	if bindNativeResources(profile) != nil {
		t.Fatal("profile failed")
	}
	base, _, record := txSignatureFixture(t, 513)
	public, _ := hex.DecodeString(base.Source.Genesis.Producers[0])
	txs := record.Block.Body.Transactions
	txs[0].Signature = string(bytes.Repeat([]byte("0"), 128))
	entered := make(chan struct{}, 32)
	badRelease, othersRelease, badChecked := make(chan struct{}), make(chan struct{}), make(chan struct{})
	finished := make(chan bool, 1)
	var active, calls, atReturn atomic.Int64
	go func() {
		accepted := verifyDagTransactionSignaturesUsing(public, txs, 256, func(public, message, signature []byte) bool {
			active.Add(1)
			defer active.Add(-1)
			calls.Add(1)
			select {
			case entered <- struct{}{}:
			default:
			}
			if bytes.Equal(signature, make([]byte, 64)) {
				<-badRelease
				valid := verifyTransactionSignature(public, message, signature)
				close(badChecked)
				return valid
			}
			<-othersRelease
			return verifyTransactionSignature(public, message, signature)
		})
		atReturn.Store(active.Load())
		finished <- accepted
	}()
	defer func() {
		select {
		case <-badRelease:
		default:
			close(badRelease)
		}
		select {
		case <-othersRelease:
		default:
			close(othersRelease)
		}
	}()
	deadline := time.After(5 * time.Second)
	for i := 0; i < 32; i++ {
		select {
		case <-entered:
		case <-deadline:
			t.Fatal("selected 32 workers did not all start")
		}
	}
	if active.Load() != 32 || calls.Load() != 32 {
		t.Fatal("server workers exceeded or lost the selected bound")
	}
	close(badRelease)
	select {
	case <-badChecked:
	case <-deadline:
		t.Fatal("invalid signature not checked")
	}
	select {
	case <-finished:
		t.Fatal("returned without joining server workers")
	default:
	}
	close(othersRelease)
	select {
	case accepted := <-finished:
		if accepted || active.Load() != 0 || atReturn.Load() != 0 || calls.Load() > int64(len(txs)) {
			t.Fatal("server failure leaked or duplicated in-flight work")
		}
	case <-deadline:
		t.Fatal("server workers did not join")
	}
}

func TestNativeResourcesBootstrapAndRestoreGrantPreserveRoleAndExactProfile(t *testing.T) {
	genesis, anchor, grant, keys := observerGrantFixture(t)
	fresh := true
	profile := serverResourceFixture()
	observer := nativeObserverBootstrap{Resources: profile, ExpectedFresh: &fresh, Genesis: genesis, GenesisHash: anchor,
		NodeSeed: hex.EncodeToString(keys[0].Seed()), ObserverGrant: grant, Root: t.TempDir(), RPCPort: 24001,
		Schema: nativeObserverBootstrapSchema}
	boot, err := decodeNativeBootstrap(canonical(observer))
	if err != nil || boot.Resources == nil || *boot.Resources != *profile || boot.ValidatorSeed != "" || boot.ValidatorIndex != -1 {
		t.Fatal("observer resource profile changed role or was discarded", err)
	}
	bad := *profile
	bad.VerifyWorkers = 257
	observer.Resources = &bad
	if _, err = decodeNativeBootstrap(canonical(observer)); err == nil {
		t.Fatal("invalid observer profile accepted")
	}
	membership, membershipAnchor, committee := membershipFixture(t)
	var validatorKeys []ed25519.PrivateKey
	for _, candidate := range committee {
		if publicFixtureAddress(candidate[0]) == membership.Validators[0] {
			validatorKeys = candidate
		}
	}
	validator := Bootstrap{Resources: profile, Schema: "gg.consensus.bootstrap.v2", Genesis: membership, GenesisHash: membershipAnchor,
		ValidatorIndex: 0, ValidatorSeed: hex.EncodeToString(validatorKeys[0].Seed()), NodeSeed: hex.EncodeToString(validatorKeys[1].Seed()),
		Root: t.TempDir(), RPCPort: 25000, P2PPort: membership.Membership.Validators[0].Body.P2PPort, ExpectedFresh: &fresh}
	decodedValidator, err := decodeNativeBootstrap(canonical(validator))
	if err != nil || decodedValidator.Resources == nil || *decodedValidator.Resources != *profile ||
		decodedValidator.ValidatorSeed != validator.ValidatorSeed {
		t.Fatal("validator lost bound profile or signer checks", err)
	}
	validator.Resources = &bad
	if _, err = decodeNativeBootstrap(canonical(validator)); err == nil {
		t.Fatal("invalid validator profile accepted")
	}
	command, replica, _, _ := ownedRestoreFixture(t)
	replica.public.Resources = profile
	request := financialOwnedRestoreRequest{Resources: profile, Genesis: command.Genesis, GenesisHash: command.GenesisHash,
		Root: command.RestoreRoot, NodeKey: publicFixtureAddress(publicFixtureKey("owned-restore-replica"))}
	digest := hashHex([]byte("public resource grant identity"))
	original := *replica.public
	other := *profile
	other.VerifyWorkers = 16
	for _, changed := range []*nativeResources{nil, &other, &bad} {
		value := original
		value.Resources = changed
		frame := financialOwnedRestoreGrant{Archive: digest, Bootstrap: canonical(value), GenesisHash: request.GenesisHash,
			Phase: "RESTORE", PID: os.Getpid(), Schema: "gg.native.owned-archive-restore.v1"}
		raw := append(ownedRestoreCanonical(frame), '\n')
		if _, _, err = readOwnedRestoreGrant(bufio.NewReaderSize(bytes.NewReader(raw), ownedRestoreFrameMax), request, digest); err == nil {
			t.Fatal("seedless request/bootstrap resource mismatch accepted")
		}
	}
	frame := financialOwnedRestoreGrant{Archive: digest, Bootstrap: canonical(original), GenesisHash: request.GenesisHash,
		Phase: "RESTORE", PID: os.Getpid(), Schema: "gg.native.owned-archive-restore.v1"}
	raw := append(ownedRestoreCanonical(frame), '\n')
	decoded, _, err := readOwnedRestoreGrant(bufio.NewReaderSize(bytes.NewReader(raw), ownedRestoreFrameMax), request, digest)
	if err != nil || decoded.ValidatorSeed != "" || decoded.public.Role != "REPLICA" || *decoded.Resources != *profile {
		t.Fatal("same-PID replica profile did not survive grant", err)
	}
}

func TestNativeResourcesSDKRatesKeepLowAndApplyFiniteServerBeforeValidation(t *testing.T) {
	if rate, err := nativeSDKResourceRate(nil); err != nil || rate != 5120000 {
		t.Fatal("legacy SDK rate changed", rate, err)
	}
	low := *serverResourceFixture()
	low.Mode, low.GoMaxProcs, low.VerifyWorkers, low.OwnerMemoryBytes = "LOW", 2, 8, 0
	if rate, err := nativeSDKResourceRate(&low); err != nil || rate != 5120000 {
		t.Fatal("explicit LOW SDK rate changed", rate, err)
	}
	configuration := cfg.DefaultConfig()
	if err := applyNativeSDKResourceRates(configuration, nil); err != nil ||
		configuration.P2P.SendRate != 5120000 || configuration.P2P.RecvRate != 5120000 {
		t.Fatal("LOW SDK config changed", err)
	}
	profile := serverResourceFixture()
	for _, cpu := range []int{1, 32, 256} {
		profile.GoMaxProcs, profile.VerifyWorkers = cpu, cpu
		expected := int64(cpu) * (64 << 20)
		if rate, err := nativeSDKResourceRate(profile); err != nil || rate != expected {
			t.Fatal("finite SERVER derivation", cpu, rate, err)
		}
		if err := applyNativeSDKResourceRates(configuration, profile); err != nil ||
			configuration.P2P.SendRate != expected || configuration.P2P.RecvRate != expected ||
			configuration.ValidateBasic() != nil {
			t.Fatal("real SDK config did not accept selected rate", cpu, err)
		}
		facts, err := nativeSDKResourceFacts(profile, configuration.P2P.SendRate, configuration.P2P.RecvRate)
		if err != nil || facts["sdk_send_bytes_per_second"] != expected || facts["sdk_recv_bytes_per_second"] != expected {
			t.Fatal("actual SDK rates not attested", facts, err)
		}
		if _, err = nativeSDKResourceFacts(profile, expected-1, expected); err == nil {
			t.Fatal("unapplied send rate claimed")
		}
		if _, err = nativeSDKResourceFacts(profile, expected, expected-1); err == nil {
			t.Fatal("unapplied receive rate claimed")
		}
	}
	if configuration.P2P.SendRate != 17179869184 {
		t.Fatal("SERVER256 was truncated through a32-bit rate")
	}
	for _, invalid := range []int{-1, 0, 257, int(^uint(0) >> 1)} {
		profile.GoMaxProcs = invalid
		beforeSend, beforeRecv := configuration.P2P.SendRate, configuration.P2P.RecvRate
		if err := applyNativeSDKResourceRates(configuration, profile); err == nil ||
			configuration.P2P.SendRate != beforeSend || configuration.P2P.RecvRate != beforeRecv {
			t.Fatal("invalid/overflow profile partially changed SDK rates", invalid, err)
		}
	}
	if err := applyNativeSDKResourceRates(nil, nil); err == nil {
		t.Fatal("missing SDK config accepted")
	}
}

func TestNativeResourcesSDKReadyMaximumWireFitsOriginal1024ByteFrame(t *testing.T) {
	profile := serverResourceFixture()
	profile.GoMaxProcs, profile.VerifyWorkers = 256, 256
	profile.GoHeapBytes, profile.ProcessMemoryBytes = (1<<40)-(64<<20), 1<<40
	profile.VirtualBytes, profile.OpenFiles, profile.OwnerMemoryBytes = 1<<44, 65536, 1<<42
	if !validNativeResources(profile) {
		t.Fatal("maximum valid profile fixture")
	}
	// Size oracle only: no large runtime heap/OS budget is applied or allocated.
	attestation := map[string]any{"schema": "gg.native.resources-ready.v1", "profile": *profile, "go_max_procs": 256,
		"go_heap_bytes": profile.GoHeapBytes, "verify_workers": 256, "effective_verify_workers": 256, "commit_wait_ms": 10}
	facts, err := nativeSDKResourceFacts(profile, 17179869184, 17179869184)
	if err != nil {
		t.Fatal(err)
	}
	ready := map[string]any{"schema": "gg.consensus.protocol-ready.v1", "chain_id": "ggnet:" + strings.Repeat("a", 24),
		"genesis_hash": strings.Repeat("b", 64), "node_id": strings.Repeat("c", 40), "pid": int64(9223372036854775807),
		"rpc_port": 65535, "p2p_host": "ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff", "p2p_port": 65534,
		"role": "VALIDATOR", "consensus_signing": false, "state_sync": false, "resources": attestation}
	for name, value := range facts {
		ready[name] = value
	}
	raw := canonical(ready)
	if len(raw) != 967 || len(raw)+1 > 1024 {
		t.Fatal("maximum native readiness frame exceeded original bound", len(raw))
	}
}

func isolateNativeResources(t *testing.T) {
	t.Helper()
	nativeResourceProcess.mu.Lock()
	bound, previous := nativeResourceProcess.bound, nativeResourceProcess.profile
	nativeResourceProcess.bound, nativeResourceProcess.profile = false, nil
	nativeResourceProcess.mu.Unlock()
	budget := dagTxSignatureSelectedBudget.Swap(0)
	cpu, heap := runtime.GOMAXPROCS(0), debug.SetMemoryLimit(-1)
	t.Cleanup(func() {
		runtime.GOMAXPROCS(cpu)
		debug.SetMemoryLimit(heap)
		dagTxSignatureSelectedBudget.Store(budget)
		nativeResourceProcess.mu.Lock()
		nativeResourceProcess.bound, nativeResourceProcess.profile = bound, previous
		nativeResourceProcess.mu.Unlock()
	})
}

func TestNativeResourcesStrictFiniteProfileAndLegacyLow(t *testing.T) {
	if !validNativeResources(nil) || dagTxSignatureWorkerMaximum() != 8 ||
		nativeResourceCommitWait(nil) != 100*time.Millisecond {
		t.Fatal("legacy LOW defaults changed")
	}
	low := nativeResources{Schema: "gg.native.resources.v1", Mode: "LOW",
		GoMaxProcs: 2, VerifyWorkers: 8, GoHeapBytes: 256 << 20,
		ProcessMemoryBytes: 512 << 20, VirtualBytes: 8 << 30, OpenFiles: 1024,
		OwnerCPUBasisPoints: 10000, MaximumNativeChildren: 6}
	if !validNativeResources(&low) || nativeResourceCommitWait(&low) != 100*time.Millisecond {
		t.Fatal("explicit LOW does not preserve the old policy")
	}
	maximum := serverResourceFixture()
	maximum.GoMaxProcs, maximum.VerifyWorkers = 256, 256
	if !validNativeResources(maximum) || nativeResourceCommitWait(maximum) != 10*time.Millisecond {
		t.Fatal("finite server profile incorrectly capped at laptop/core count")
	}
	for _, mutate := range []func(*nativeResources){
		func(p *nativeResources) { p.Schema = "future" },
		func(p *nativeResources) { p.Mode = "AUTO" },
		func(p *nativeResources) { p.GoMaxProcs = 257 },
		func(p *nativeResources) { p.VerifyWorkers = 33 },
		func(p *nativeResources) { p.GoHeapBytes = 512 << 20 },
		func(p *nativeResources) { p.ProcessMemoryBytes = 511 << 20 },
		func(p *nativeResources) { p.VirtualBytes = 4 << 30 },
		func(p *nativeResources) { p.OwnerMemoryBytes = 0 },
		func(p *nativeResources) { p.OpenFiles = 65537 },
		func(p *nativeResources) { p.MaximumNativeChildren = 7 },
		func(p *nativeResources) { p.OwnerCPUBasisPoints = 10001 },
		func(p *nativeResources) { p.GoHeapBytes++ },
	} {
		value := *serverResourceFixture()
		mutate(&value)
		if validNativeResources(&value) {
			t.Fatal("invalid resource profile accepted", value)
		}
	}
	for _, raw := range []string{
		`{"schema":"gg.native.resources.v1","mode":"SERVER","go_max_procs":true}`,
		`{"schema":"gg.native.resources.v1","mode":"SERVER","go_max_procs":32,"unknown":1}`,
		`{"schema":"gg.native.resources.v1","mode":"SERVER","go_max_procs":32,"go_max_procs":32}`,
	} {
		var value nativeResources
		if decodeStrict([]byte(raw), &value) == nil {
			t.Fatal("non-strict resource wire accepted")
		}
	}
}

func TestNativeResourcesAttestActualRuntimeAndRejectChangedAttempt(t *testing.T) {
	isolateNativeResources(t)
	profile := serverResourceFixture()
	runtime.GOMAXPROCS(profile.GoMaxProcs)
	debug.SetMemoryLimit(profile.GoHeapBytes)
	bad := *profile
	bad.GoMaxProcs, bad.VerifyWorkers = 16, 16
	if bindNativeResources(&bad) == nil || dagTxSignatureWorkerMaximum() != 8 {
		t.Fatal("unapplied CPU envelope accepted or changed scheduler")
	}
	bad = *profile
	bad.GoHeapBytes = 192 << 20
	if bindNativeResources(&bad) == nil || dagTxSignatureWorkerMaximum() != 8 {
		t.Fatal("unapplied heap envelope accepted")
	}
	ready, err := nativeResourceReady(profile, 10*time.Millisecond)
	if err != nil || ready["go_max_procs"] != 32 || ready["go_heap_bytes"] != int64(256<<20) ||
		ready["verify_workers"] != 32 || ready["effective_verify_workers"] != 32 || ready["commit_wait_ms"] != int64(10) {
		t.Fatal("actual selected runtime not attested", ready, err)
	}
	if _, err = nativeResourceReady(profile, 100*time.Millisecond); err == nil {
		t.Fatal("wrong SDK scheduling delay attested")
	}
	copy := *profile
	profile.VerifyWorkers = 16 // A caller cannot mutate the already copied process binding.
	if bindNativeResources(profile) == nil || bindNativeResources(nil) == nil || dagTxSignatureWorkerMaximum() != 32 {
		t.Fatal("bound profile was silently replaced")
	}
	if bindNativeResources(&copy) != nil {
		t.Fatal("same-PID request/bootstrap profile could not rebind")
	}
	runtime.GOMAXPROCS(16)
	if _, err = nativeResourceReady(&copy, 10*time.Millisecond); err == nil {
		t.Fatal("runtime drift was hidden")
	}
}

func TestNativeResourcesServerWorkersAboveEightStayFiniteAndJoin(t *testing.T) {
	isolateNativeResources(t)
	profile := serverResourceFixture()
	runtime.GOMAXPROCS(profile.GoMaxProcs)
	debug.SetMemoryLimit(profile.GoHeapBytes)
	if bindNativeResources(profile) != nil {
		t.Fatal("server profile failed")
	}
	if dagTxSignatureWorkers(255, 32) != 1 || dagTxSignatureWorkers(256, 32) != 32 ||
		dagTxSignatureWorkers(5000, 256) != 32 {
		t.Fatal("selected scheduler bounds changed")
	}
	base, _, record := txSignatureFixture(t, 513)
	public, _ := hex.DecodeString(base.Source.Genesis.Producers[0])
	var active, peak, calls atomic.Int64
	if !verifyDagTransactionSignaturesUsing(public, record.Block.Body.Transactions, 256,
		func(public, message, signature []byte) bool {
			now := active.Add(1)
			for previous := peak.Load(); now > previous && !peak.CompareAndSwap(previous, now); previous = peak.Load() {
			}
			defer active.Add(-1)
			calls.Add(1)
			return verifyTransactionSignature(public, message, signature)
		}) || calls.Load() != 513 || active.Load() != 0 || peak.Load() > 32 {
		t.Fatal("server scheduler skipped signatures, exceeded budget or leaked work")
	}
	profile.GoMaxProcs, profile.VerifyWorkers = 256, 256
	// Immutable binding rejects widening even though 256 is a valid future start.
	if bindNativeResources(profile) == nil {
		t.Fatal("live server widened")
	}
}

func TestNativeResourcesFinancialServerKeepsExactOrderedStateReceiptsAndNonce(t *testing.T) {
	isolateNativeResources(t)
	genesis, anchor, keys, _ := testGenesis()
	state := initialState(genesis, anchor)
	inputs := make([][]byte, 513)
	for index := range inputs {
		source := index % 4
		inputs[index] = testTx(genesis, anchor, keys, source, (source+1)%4, "1", uint64(index/4))
	}
	before := canonical(state)
	runtime.GOMAXPROCS(1)
	serial, err := executeFinancialTransactions(context.Background(), genesis, anchor, state, financialTestContext(anchor), inputs)
	if err != nil {
		t.Fatal(err)
	}
	profile := serverResourceFixture()
	runtime.GOMAXPROCS(profile.GoMaxProcs)
	debug.SetMemoryLimit(profile.GoHeapBytes)
	if bindNativeResources(profile) != nil {
		t.Fatal("server binding failed")
	}
	parallel, err := executeFinancialTransactions(context.Background(), genesis, anchor, state, financialTestContext(anchor), inputs)
	if err != nil || !bytes.Equal(canonical(serial), canonical(parallel)) || !bytes.Equal(before, canonical(state)) ||
		parallel.Summary.Applied != len(inputs) || parallel.Summary.Rejected != 0 {
		t.Fatal("server changed monetary execution", err)
	}
	repeated, err := executeFinancialTransactions(context.Background(), genesis, anchor, parallel.State, financialTestContext(anchor), inputs)
	if err != nil || repeated.Summary.Applied != 0 || repeated.Summary.Rejected != len(inputs) ||
		!bytes.Equal(canonical(repeated.State), canonical(parallel.State)) {
		t.Fatal("server admitted repeated nonces", err)
	}
	cancelled, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err = executeFinancialTransactions(cancelled, genesis, anchor, state, financialTestContext(anchor), inputs); err == nil {
		t.Fatal("server bypassed cancellation")
	}
	for index, receipt := range parallel.Receipts {
		if receipt.Index != index || receipt.Outcome != "APPLIED" {
			t.Fatal("receipt order changed", strconv.Itoa(index))
		}
	}
}
