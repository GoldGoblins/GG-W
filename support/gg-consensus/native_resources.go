//go:build !js

package main

// Local launch policy only. No field enters genesis, consensus, signatures,
// archive identity or stored financial bytes. Nil preserves legacy LOW wires.
import (
	"errors"
	"runtime"
	"runtime/debug"
	"sync"
	"time"

	cfg "github.com/cometbft/cometbft/config"
)

var errNativeResources = errors.New("GG_NATIVE_RESOURCE_PROFILE")

type nativeResources struct {
	Schema                string `json:"schema"`
	Mode                  string `json:"mode"`
	GoMaxProcs            int    `json:"go_max_procs"`
	VerifyWorkers         int    `json:"verify_workers"`
	GoHeapBytes           int64  `json:"go_heap_bytes"`
	ProcessMemoryBytes    int64  `json:"process_memory_bytes"`
	VirtualBytes          int64  `json:"virtual_bytes"`
	OpenFiles             int    `json:"open_files"`
	OwnerMemoryBytes      int64  `json:"owner_memory_bytes"`
	OwnerCPUBasisPoints   int    `json:"owner_cpu_basis_points"`
	MaximumNativeChildren int    `json:"maximum_native_children"`
}

func validNativeResources(value *nativeResources) bool {
	if value == nil {
		return true
	}
	const MiB int64 = 1 << 20
	if value.Schema == "gg.native.resources.v1" && value.Mode == "LOW" {
		return value.GoMaxProcs == 2 && value.VerifyWorkers == 8 && value.GoHeapBytes == 256*MiB &&
			value.ProcessMemoryBytes == 512*MiB && value.VirtualBytes == 8<<30 && value.OpenFiles == 1024 &&
			value.OwnerMemoryBytes == 0 && value.OwnerCPUBasisPoints == 10000 && value.MaximumNativeChildren == 6
	}
	return value.Schema == "gg.native.resources.v1" && value.Mode == "SERVER" &&
		value.GoMaxProcs >= 1 && value.GoMaxProcs <= 256 &&
		value.VerifyWorkers >= 1 && value.VerifyWorkers <= value.GoMaxProcs &&
		value.GoHeapBytes >= 96*MiB && value.GoHeapBytes <= 1<<40 &&
		value.ProcessMemoryBytes >= 512*MiB && value.ProcessMemoryBytes <= 1<<40 &&
		value.GoHeapBytes <= value.ProcessMemoryBytes-64*MiB &&
		value.VirtualBytes >= 8<<30 && value.VirtualBytes <= 1<<44 &&
		value.VirtualBytes >= 2*value.ProcessMemoryBytes &&
		value.OpenFiles >= 1024 && value.OpenFiles <= 65536 &&
		value.OwnerMemoryBytes >= value.ProcessMemoryBytes && value.OwnerMemoryBytes <= 1<<42 &&
		value.OwnerCPUBasisPoints >= 1 && value.OwnerCPUBasisPoints <= 10000 &&
		value.MaximumNativeChildren >= 1 && value.MaximumNativeChildren <= 6 &&
		value.GoHeapBytes%MiB == 0 && value.ProcessMemoryBytes%MiB == 0 &&
		value.VirtualBytes%MiB == 0 && value.OwnerMemoryBytes%MiB == 0
}

type nativeResourceBinding struct {
	mu      sync.Mutex
	bound   bool
	profile *nativeResources
}

var nativeResourceProcess nativeResourceBinding

// The first seedless restore request and its later bootstrap must bind the
// same immutable profile. Environment settings are read back, never widened.
func bindNativeResources(value *nativeResources) error {
	if !validNativeResources(value) {
		return errNativeResources
	}
	nativeResourceProcess.mu.Lock()
	defer nativeResourceProcess.mu.Unlock()
	if nativeResourceProcess.bound {
		previous := nativeResourceProcess.profile
		if (previous == nil) != (value == nil) || previous != nil && *previous != *value {
			return errNativeResources
		}
	}
	if value != nil {
		if runtime.GOMAXPROCS(0) != value.GoMaxProcs || debug.SetMemoryLimit(-1) != value.GoHeapBytes {
			return errNativeResources
		}
		copy := *value
		nativeResourceProcess.profile = &copy
		dagTxSignatureSelectedBudget.Store(int64(value.VerifyWorkers))
	}
	nativeResourceProcess.bound = true
	return nil
}

const nativeSDKLowRate int64 = 5120000
const nativeSDKServerRatePerCPU int64 = 64 << 20

// Validate before int64 multiplication; no native rate is host-derived or
// supplied by peers. This removes only the pinned SDK's default rate ceiling.
func nativeSDKResourceRate(value *nativeResources) (int64, error) {
	if !validNativeResources(value) {
		return 0, errNativeResources
	}
	if value != nil && value.Mode == "SERVER" {
		return int64(value.GoMaxProcs) * nativeSDKServerRatePerCPU, nil
	}
	return nativeSDKLowRate, nil
}

func applyNativeSDKResourceRates(configuration *cfg.Config, value *nativeResources) error {
	rate, err := nativeSDKResourceRate(value)
	if err != nil || configuration == nil || configuration.P2P == nil {
		return errNativeResources
	}
	configuration.P2P.SendRate = rate
	configuration.P2P.RecvRate = rate
	return nil
}

// Called only for actual full SDK readiness, using its applied config.
// Transport-only Go children keep their existing generic resource ACK.
func nativeSDKResourceFacts(value *nativeResources, send, receive int64) (map[string]any, error) {
	rate, err := nativeSDKResourceRate(value)
	if err != nil || send != rate || receive != rate {
		return nil, errNativeResources
	}
	return map[string]any{"sdk_send_bytes_per_second": send, "sdk_recv_bytes_per_second": receive}, nil
}

func nativeResourceCommitWait(value *nativeResources) time.Duration {
	if value != nil && value.Mode == "SERVER" {
		return 10 * time.Millisecond
	}
	return 100 * time.Millisecond
}

func nativeResourceReady(value *nativeResources, commitWait time.Duration) (map[string]any, error) {
	if commitWait != nativeResourceCommitWait(value) {
		return nil, errNativeResources
	}
	if err := bindNativeResources(value); err != nil {
		return nil, err
	}
	if value == nil {
		return nil, nil
	}
	copy := *value
	return map[string]any{"schema": "gg.native.resources-ready.v1", "profile": copy,
		"go_max_procs": runtime.GOMAXPROCS(0), "go_heap_bytes": debug.SetMemoryLimit(-1),
		"verify_workers":           dagTxSignatureWorkerMaximum(),
		"effective_verify_workers": min(runtime.GOMAXPROCS(0), dagTxSignatureWorkerMaximum()),
		"commit_wait_ms":           commitWait.Milliseconds()}, nil
}

type nativeTransportBudget struct {
	Schema                      string `json:"schema"`
	Connections                 int    `json:"connections"`
	RequestsPerSecond           int    `json:"requests_per_second"`
	RequestsPerConnectionSecond int    `json:"requests_per_connection_second"`
	Handlers                    int    `json:"handlers"`
	QueueCount                  int    `json:"queue_count"`
	QueueBytes                  int    `json:"queue_bytes"`
	ClientIntervalMicros        int    `json:"client_interval_micros"`
	RequestSeconds              int    `json:"request_seconds"`
	RequestBytes                int    `json:"request_bytes"`
	ResponseBytes               int    `json:"response_bytes"`
}

func nativeTransportResources(value *nativeResources) nativeTransportBudget {
	budget := nativeTransportBudget{Schema: "gg.native.transport-budget.v1", Connections: 8,
		RequestsPerSecond: 32, RequestsPerConnectionSecond: 8, Handlers: 2, QueueCount: 8, QueueBytes: 8 * 65536,
		ClientIntervalMicros: 135000, RequestSeconds: 20, RequestBytes: 65536, ResponseBytes: protocolTransportMaxFrame}
	if value != nil && value.Mode == "SERVER" {
		budget.Connections = min(64, max(8, value.GoMaxProcs*2))
		budget.RequestsPerSecond = min(8192, max(32, value.GoMaxProcs*64))
		budget.RequestsPerConnectionSecond = min(1024, max(8, value.GoMaxProcs*8))
		budget.Handlers = min(64, max(2, value.VerifyWorkers))
		budget.QueueCount = min(256, max(8, budget.Handlers*2))
		budget.QueueBytes = budget.QueueCount * 65536
		budget.ClientIntervalMicros = (1000000 + budget.RequestsPerConnectionSecond - 1) / budget.RequestsPerConnectionSecond
	}
	return budget
}

func validNativeTransportBudget(budget *nativeTransportBudget) bool {
	return budget != nil && budget.Schema == "gg.native.transport-budget.v1" &&
		budget.Connections >= 8 && budget.Connections <= 64 &&
		budget.RequestsPerSecond >= 32 && budget.RequestsPerSecond <= 8192 &&
		budget.RequestsPerConnectionSecond >= 8 && budget.RequestsPerConnectionSecond <= 1024 &&
		budget.Handlers >= 2 && budget.Handlers <= 64 && budget.QueueCount >= 8 && budget.QueueCount <= 256 &&
		budget.QueueBytes == budget.QueueCount*65536 && budget.ClientIntervalMicros >= 1 &&
		budget.ClientIntervalMicros <= 135000 && budget.ClientIntervalMicros*budget.RequestsPerConnectionSecond >= 1000000 &&
		budget.RequestSeconds == 20 && budget.RequestBytes == 65536 && budget.ResponseBytes == protocolTransportMaxFrame
}
