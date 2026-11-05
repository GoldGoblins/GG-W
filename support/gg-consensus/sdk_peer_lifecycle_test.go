//go:build gg_sdk_peer_lifecycle_test

package mempool

// Injected only into the exact derived SDK test package by a Go overlay.
// These are lifecycle unit tests; actual native peers run separately.
import (
	"sync/atomic"
	"testing"
	"time"

	cfg "github.com/cometbft/cometbft/config"
	"github.com/cometbft/cometbft/p2p/mocks"
	"github.com/cometbft/cometbft/types"
)

type ggLifecyclePeerState struct{}

func (ggLifecyclePeerState) GetHeight() int64 { return 1 }

func TestGGSyncWaitReleasesDisconnectedPeer(t *testing.T) {
	for _, stopReactor := range []bool{false, true} {
		t.Run(map[bool]string{false: "peer", true: "reactor"}[stopReactor], func(t *testing.T) {
			reactor := NewReactor(cfg.DefaultMempoolConfig(), nil, true)
			if err := reactor.Start(); err != nil {
				t.Fatal(err)
			}
			quit := make(chan struct{})
			peer := mocks.NewPeer(t)
			peer.On("Quit").Return((<-chan struct{})(quit))
			done := make(chan struct{})
			go func() { defer close(done); reactor.broadcastTxRoutine(peer) }()
			t.Cleanup(func() {
				_ = reactor.Stop()
				select {
				case <-done:
				case <-time.After(time.Second):
					t.Error("worker leaked after cleanup")
				}
			})
			if stopReactor {
				_ = reactor.Stop()
			} else {
				close(quit)
			}
			select {
			case <-done:
			case <-time.After(500 * time.Millisecond):
				t.Fatal("disconnected peer retained while waiting for block sync")
			}
		})
	}
}

func TestGGPeerReadinessWaitCancelsBeforeStateExists(t *testing.T) {
	reactor := NewReactor(cfg.DefaultMempoolConfig(), nil, false)
	if err := reactor.Start(); err != nil {
		t.Fatal(err)
	}
	peer := mocks.NewPeer(t)
	quit := make(chan struct{})
	entered := make(chan struct{}, 1)
	var release atomic.Bool
	peer.On("IsRunning").Return(true)
	peer.On("Quit").Return((<-chan struct{})(quit))
	peer.On("Get", types.PeerStateKey).Return(func(string) any {
		select {
		case entered <- struct{}{}:
		default:
		}
		if release.Load() {
			return ggLifecyclePeerState{}
		}
		return nil
	})
	done := make(chan struct{})
	go func() { defer close(done); reactor.broadcastTxRoutine(peer) }()
	t.Cleanup(func() {
		_ = reactor.Stop()
		release.Store(true)
		select {
		case <-done:
		case <-time.After(time.Second):
			t.Error("readiness worker leaked after cleanup")
		}
	})
	select {
	case <-entered:
	case <-time.After(time.Second):
		t.Fatal("worker never entered readiness wait")
	}
	close(quit)
	select {
	case <-done:
	case <-time.After(500 * time.Millisecond):
		t.Fatal("readiness wait retained disconnected peer")
	}
}
