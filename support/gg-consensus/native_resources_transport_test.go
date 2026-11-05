//go:build !js

package main

// Actual pinned encryption over net.Pipe, not a network/capacity assertion.
import (
	"bytes"
	"encoding/hex"
	"encoding/json"
	"net"
	"runtime"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func TestNativeResourcesTransportFiniteBudgetsKeepLowAndScaleExplicitServer(t *testing.T) {
	low := nativeTransportResources(nil)
	if low.Connections != 8 || low.RequestsPerSecond != 32 || low.RequestsPerConnectionSecond != 8 ||
		low.Handlers != 2 || low.QueueCount != 8 || low.QueueBytes != 8*65536 || low.ClientIntervalMicros != 135000 {
		t.Fatal("LOW transport budgets changed", low)
	}
	profile := serverResourceFixture()
	server := nativeTransportResources(profile)
	if !validNativeTransportBudget(&server) || server.Connections != 64 || server.RequestsPerSecond != 2048 ||
		server.RequestsPerConnectionSecond != 256 || server.Handlers != 32 || server.QueueCount != 64 ||
		server.QueueBytes != 64*65536 || server.ClientIntervalMicros != 3907 {
		t.Fatal("finite SERVER transport budget", server)
	}
	profile.GoMaxProcs, profile.VerifyWorkers = 256, 256
	maximum := nativeTransportResources(profile)
	if !validNativeTransportBudget(&maximum) || maximum.RequestsPerSecond != 8192 ||
		maximum.RequestsPerConnectionSecond != 1024 || maximum.Handlers != 64 || maximum.QueueCount != 128 {
		t.Fatal("maximum finite transport profile", maximum)
	}
	for _, change := range []func(*nativeTransportBudget){
		func(b *nativeTransportBudget) { b.Connections = 65 },
		func(b *nativeTransportBudget) { b.RequestsPerSecond = 8193 },
		func(b *nativeTransportBudget) { b.RequestsPerConnectionSecond = 1025 },
		func(b *nativeTransportBudget) { b.QueueBytes++ },
		func(b *nativeTransportBudget) { b.ClientIntervalMicros = 1 },
		func(b *nativeTransportBudget) { b.RequestBytes = 65537 },
		func(b *nativeTransportBudget) { b.Schema = "future" },
	} {
		bad := server
		change(&bad)
		if validNativeTransportBudget(&bad) {
			t.Fatal("unbounded peer budget accepted", bad)
		}
	}
	request := protocolTransportFrame{Event: "REQUEST", Schema: "gg.protocol.transport-frame.v1", Limits: &server}
	if _, err := decodeProtocolTransportFrame(canonical(request)); err == nil {
		t.Fatal("request smuggled HELLO policy")
	}
}

func TestNativeResourcesTransportAuthenticatedLimitsAndLegacyLowHello(t *testing.T) {
	serverKey, clientKey := publicTransportKey("resource-server"), publicTransportKey("resource-client")
	serverPublic, clientPublic := hex.EncodeToString(serverKey.PubKey().Bytes()), hex.EncodeToString(clientKey.PubKey().Bytes())
	anchor := strings.Repeat("e", 64)
	type result struct {
		peer   string
		limits nativeTransportBudget
		err    error
	}
	for _, offerServer := range []bool{false, true} {
		serverSocket, clientSocket := net.Pipe()
		serverResults, clientResults := make(chan result, 1), make(chan result, 1)
		low, large := nativeTransportResources(nil), nativeTransportResources(serverResourceFixture())
		var offer *nativeTransportBudget
		if offerServer {
			offer = &large
		}
		go func() {
			_, peer, limits, err := protocolTransportConnectionUsing(serverSocket, serverKey, "", anchor, true, map[string]bool{clientPublic: true}, &low)
			serverResults <- result{peer, limits, err}
			if err != nil {
				serverSocket.Close()
			}
		}()
		go func() {
			_, peer, limits, err := protocolTransportConnectionUsing(clientSocket, clientKey, serverPublic, anchor, false, nil, offer)
			clientResults <- result{peer, limits, err}
			if err != nil {
				clientSocket.Close()
			}
		}()
		await := func(channel <-chan result) result {
			select {
			case value := <-channel:
				return value
			case <-time.After(8 * time.Second):
				serverSocket.Close()
				clientSocket.Close()
				t.Fatal("bounded authenticated resource HELLO did not return")
				return result{}
			}
		}
		server, client := await(serverResults), await(clientResults)
		serverSocket.Close()
		clientSocket.Close()
		if server.err != nil || client.err != nil || server.peer != clientPublic || client.peer != serverPublic ||
			client.limits != low {
			t.Fatal("SERVER client did not learn authenticated LOW receive limits", server, client)
		}
		wanted := low
		if offerServer {
			wanted = large
		}
		if server.limits != wanted {
			t.Fatal("peer's limits changed across encrypted handshake")
		}
	}
	legacy := protocolTransportFrame{Event: "HELLO", Genesis: anchor, Schema: "gg.protocol.transport-frame.v1"}
	if bytes.Contains(canonical(legacy), []byte("limits")) || bytes.Contains(canonical(legacy), []byte("resources")) {
		t.Fatal("legacy LOW HELLO bytes changed")
	}
}

func TestNativeResourcesTransportServerPeerQuotaSharedAcrossSocketsAndReconnects(t *testing.T) {
	key := hex.EncodeToString(publicTransportKey("shared-resource-peer").PubKey().Bytes())
	other := hex.EncodeToString(publicTransportKey("isolated-resource-peer").PubKey().Bytes())
	allowed := map[string]bool{key: true, other: true}
	budget := nativeTransportResources(serverResourceFixture())
	if protocolTransportPeerRates(nil, budget, allowed) != nil {
		t.Fatal("LOW gained a shared-key restriction")
	}
	peers := protocolTransportPeerRates(serverResourceFixture(), budget, allowed)
	if len(peers) != 2 || peers[key] == peers[other] {
		t.Fatal("unbounded or aliased peer states")
	}
	shared := peers[key]
	// Freeze replenishment only in this test to count a deterministic burst
	// while64 concurrent socket goroutines debit the actual shared mutex.
	shared.rate, shared.burst = 0, 2
	peers[other].rate, peers[other].burst = 0, 2
	var accepted atomic.Int64
	var group sync.WaitGroup
	for i := 0; i < 64; i++ {
		group.Add(1)
		go func() {
			defer group.Done()
			if peers[key].take() {
				accepted.Add(1)
			}
		}()
	}
	group.Wait()
	if accepted.Load() != 2 || peers[key] != shared || peers[key].take() {
		t.Fatal("concurrent sockets/reconnect lookup refilled or multiplied one peer's quota")
	}
	if !peers[other].take() || !peers[other].take() || peers[other].take() {
		t.Fatal("one authenticated peer consumed another peer's credit")
	}
}

func TestNativeResourcesTransportReadyCanonicalEnvelopeLeavesOtherFramesExact(t *testing.T) {
	// Encoder/framing coverage only: these are finite public attestation
	// fixtures, not a claim that this test applied their Go/kernel budgets.
	low := nativeResources{Schema: "gg.native.resources.v1", Mode: "LOW", GoMaxProcs: 2, VerifyWorkers: 8,
		GoHeapBytes: 256 << 20, ProcessMemoryBytes: 512 << 20, VirtualBytes: 8 << 30, OpenFiles: 1024,
		OwnerCPUBasisPoints: 10000, MaximumNativeChildren: 6}
	server4 := low
	server4.Mode, server4.GoMaxProcs, server4.VerifyWorkers, server4.OwnerMemoryBytes = "SERVER", 4, 4, 1<<30
	server256 := server4
	server256.GoMaxProcs, server256.VerifyWorkers = 256, 256
	anchor, peer := strings.Repeat("a", 64), strings.Repeat("b", 64)
	check := func(t *testing.T, value protocolTransportFrame, expected []byte) {
		t.Helper()
		var output bytes.Buffer
		if err := writeProtocolTransportFrame(&output, value); err != nil {
			t.Fatal("actual frame encoder", err)
		}
		if !bytes.Equal(output.Bytes(), transportWire(expected)) {
			t.Fatal("length prefix or exact canonical frame bytes changed")
		}
		decoded, err := readProtocolTransportFrame(&output)
		if err != nil || !bytes.Equal(decoded, expected) || output.Len() != 0 {
			t.Fatal("framed body/trailing bytes", err)
		}
	}
	legacy := protocolTransportFrame{Event: "READY", Genesis: anchor, Peer: peer, Schema: "gg.protocol.transport-frame.v1"}
	t.Run("legacy-ready", func(t *testing.T) { check(t, legacy, canonical(legacy)) })
	for _, test := range []struct {
		name    string
		profile nativeResources
	}{{"LOW", low}, {"SERVER4", server4}, {"SERVER256", server256}} {
		t.Run(test.name, func(t *testing.T) {
			profile := test.profile
			if !validNativeResources(&profile) {
				t.Fatal("invalid public encoder fixture")
			}
			budget := nativeTransportResources(&profile)
			resources := map[string]any{"schema": "gg.native.resources-ready.v1", "profile": profile,
				"go_max_procs": profile.GoMaxProcs, "go_heap_bytes": profile.GoHeapBytes,
				"verify_workers": profile.VerifyWorkers, "effective_verify_workers": min(profile.GoMaxProcs, profile.VerifyWorkers),
				"commit_wait_ms": nativeResourceCommitWait(&profile).Milliseconds()}
			ready := protocolTransportFrame{Event: "READY", Genesis: anchor, Peer: peer,
				Schema: "gg.protocol.transport-frame.v1", Resources: resources, Limits: &budget, LocalLimits: &budget}
			// Independent expected JSON shape: maps all the way down, never
			// the production private-envelope normalization helper or structs.
			profileMap := map[string]any{"schema": profile.Schema, "mode": profile.Mode,
				"go_max_procs": profile.GoMaxProcs, "verify_workers": profile.VerifyWorkers,
				"go_heap_bytes": profile.GoHeapBytes, "process_memory_bytes": profile.ProcessMemoryBytes,
				"virtual_bytes": profile.VirtualBytes, "open_files": profile.OpenFiles,
				"owner_memory_bytes": profile.OwnerMemoryBytes, "owner_cpu_basis_points": profile.OwnerCPUBasisPoints,
				"maximum_native_children": profile.MaximumNativeChildren}
			budgetMap := map[string]any{"schema": budget.Schema, "connections": budget.Connections,
				"requests_per_second": budget.RequestsPerSecond, "requests_per_connection_second": budget.RequestsPerConnectionSecond,
				"handlers": budget.Handlers, "queue_count": budget.QueueCount, "queue_bytes": budget.QueueBytes,
				"client_interval_micros": budget.ClientIntervalMicros, "request_seconds": budget.RequestSeconds,
				"request_bytes": budget.RequestBytes, "response_bytes": budget.ResponseBytes}
			resourcesMap := map[string]any{"schema": "gg.native.resources-ready.v1", "profile": profileMap,
				"go_max_procs": profile.GoMaxProcs, "go_heap_bytes": profile.GoHeapBytes,
				"verify_workers": profile.VerifyWorkers, "effective_verify_workers": min(profile.GoMaxProcs, profile.VerifyWorkers),
				"commit_wait_ms": nativeResourceCommitWait(&profile).Milliseconds()}
			expected := canonical(map[string]any{"event": "READY", "genesis_hash": anchor, "peer_key": peer,
				"schema": "gg.protocol.transport-frame.v1", "resources": resourcesMap,
				"limits": budgetMap, "local_limits": budgetMap})
			if bytes.Equal(expected, canonical(ready)) {
				t.Fatal("fixture no longer detects declaration-order producer bug")
			}
			check(t, ready, expected)
			// The gate is resource-bearing READY only, even if a later
			// decoder rejects other fields on a nil-resource control frame.
			nilResources := ready
			nilResources.Resources = nil
			check(t, nilResources, canonical(nilResources))
			capability := protocolTransportFrame{Event: "HELLO", Genesis: anchor,
				Schema: "gg.protocol.transport-frame.v1", Limits: &budget}
			check(t, capability, canonical(capability))
			for _, event := range []string{"HELLO", "REQUEST", "RESPONSE", "ERROR"} {
				t.Run(event, func(t *testing.T) {
					other := ready
					other.Event, other.ID = event, 7
					other.Payload = json.RawMessage(`{"z_original":9007199254740993,"a_signature":"PUBLIC_UNCHANGED_BYTES"}`)
					check(t, other, canonical(other))
				})
			}
		})
	}
}

func TestNativeResourcesTransportUnappliedEnvelopeFailsBeforeNetworkOrReady(t *testing.T) {
	isolateNativeResources(t)
	profile := serverResourceFixture()
	profile.GoMaxProcs = 256
	profile.VerifyWorkers = 256
	if runtime.GOMAXPROCS(0) == 256 {
		runtime.GOMAXPROCS(2)
	}
	bootstrap := protocolTransportBootstrap{Resources: profile, Allowed: []string{},
		Expected: hex.EncodeToString(publicTransportKey("resource-remote").PubKey().Bytes()),
		Genesis:  strings.Repeat("a", 64), Host: "127.0.0.1", Mode: "CLIENT", Port: 1,
		Private: hex.EncodeToString(publicTransportKey("resource-bootstrap")), Schema: "gg.protocol.transport-bootstrap.v1"}
	var output bytes.Buffer
	if err := runProtocolTransport(bytes.NewReader(transportWire(canonical(bootstrap))), &output); err == nil || output.Len() != 0 {
		t.Fatal("missing actual Go envelope reached transport readiness", err)
	}
}
