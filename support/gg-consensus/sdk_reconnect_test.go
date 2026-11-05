//go:build gg_sdk_peer_lifecycle_test

package p2p

import (
	"sync"
	"testing"
	"time"

	"github.com/cometbft/cometbft/config"
	"github.com/cometbft/cometbft/libs/log"
	"github.com/cometbft/cometbft/libs/service"
)

type ggReconnectNoopService struct{ service.BaseService }

func (*ggReconnectNoopService) OnStart() error { return nil }
func (*ggReconnectNoopService) OnStop()        {}

func ggReconnectFixture(t *testing.T) *Switch {
	sw := NewSwitch(config.DefaultP2PConfig(), nil)
	// Registration/backoff only. A nil transport must never be dialed here.
	base := service.NewBaseService(log.NewNopLogger(), "GG reconnect unit fixture", &ggReconnectNoopService{})
	sw.BaseService = *base
	if err := sw.BaseService.Start(); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = sw.BaseService.Stop() })
	return sw
}

func TestGGReconnectInitialWaitDeduplicatesAndCancelsBeforeDial(t *testing.T) {
	sw := ggReconnectFixture(t)
	addr := &NetAddress{ID: ID("0000000000000000000000000000000000000001")}
	done := make(chan struct{})
	go func() { defer close(done); sw.reconnectToPeer(addr) }()
	deadline := time.Now().Add(time.Second)
	for !sw.reconnecting.Has(string(addr.ID)) && time.Now().Before(deadline) {
		time.Sleep(time.Millisecond)
	}
	if !sw.reconnecting.Has(string(addr.ID)) {
		t.Fatal("reconnect was not registered")
	}
	duplicate := make(chan struct{})
	go func() { defer close(duplicate); sw.reconnectToPeer(addr) }()
	select {
	case <-duplicate:
	case <-time.After(200 * time.Millisecond):
		t.Fatal("duplicate reconnect job was retained")
	}
	select {
	case <-done:
		t.Fatal("initial wait was bypassed")
	default:
	}
	_ = sw.BaseService.Stop()
	select {
	case <-done:
	case <-time.After(500 * time.Millisecond):
		t.Fatal("reconnect backoff did not cancel")
	}
	if sw.reconnecting.Has(string(addr.ID)) {
		t.Fatal("cancelled registration retained")
	}
}

func TestGGConcurrentReconnectRegistrationReleasesAllWaitersOnStop(t *testing.T) {
	sw := ggReconnectFixture(t)
	addr := &NetAddress{ID: ID("0000000000000000000000000000000000000002")}
	var workers sync.WaitGroup
	start := make(chan struct{})
	for i := 0; i < 32; i++ {
		workers.Add(1)
		go func() { defer workers.Done(); <-start; sw.reconnectToPeer(addr) }()
	}
	close(start)
	deadline := time.Now().Add(time.Second)
	for !sw.reconnecting.Has(string(addr.ID)) && time.Now().Before(deadline) {
		time.Sleep(time.Millisecond)
	}
	if !sw.reconnecting.Has(string(addr.ID)) {
		t.Fatal("no registration")
	}
	_ = sw.BaseService.Stop()
	done := make(chan struct{})
	go func() { workers.Wait(); close(done) }()
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("reconnect workers survived stop")
	}
	if sw.reconnecting.Has(string(addr.ID)) {
		t.Fatal("registration survived stop")
	}
}
