package main

import (
	"bytes"
	"crypto/ed25519"
	"crypto/sha256"
	"fmt"
	"sync"
	"testing"
)

func TestAuthorKeyCacheOwnsPositivePointsAndHasFixedBound(t *testing.T) {
	cache := authorKeyCache{}
	for i := 0; i < authorKeyCacheLimit+17; i++ {
		// Disposable public deterministic audit fixture, never an owner seed.
		seed := sha256.Sum256([]byte(fmt.Sprintf("GG-PUBLIC-CACHE-FIXTURE-%d", i)))
		public := ed25519.NewKeyFromSeed(seed[:]).Public().(ed25519.PublicKey)
		original := append([]byte{}, public...)
		if !cache.valid(public) {
			t.Fatal("prime key refused")
		}
		copy(public, make([]byte, 32))
		if cache.valid(public) || !cache.valid(original) {
			t.Fatal("mutable caller bytes changed a cache entry")
		}
		if len(cache.values) > authorKeyCacheLimit {
			t.Fatal("public cache grew with unique keys")
		}
	}
	if len(cache.values) != authorKeyCacheLimit {
		t.Fatal("cache was not exercised across eviction")
	}
	identity := make([]byte, 32)
	identity[0] = 1
	for _, invalid := range [][]byte{nil, make([]byte, 31), make([]byte, 33), make([]byte, 32), identity} {
		before := len(cache.values)
		if cache.valid(invalid) || len(cache.values) != before {
			t.Fatal("invalid/negative key was cached")
		}
	}
}

func TestAuthorKeyCacheConcurrentCallsCannotChangeValidation(t *testing.T) {
	cache := authorKeyCache{}
	public := ed25519.NewKeyFromSeed(bytes.Repeat([]byte{43}, 32)).Public().(ed25519.PublicKey)
	var workers sync.WaitGroup
	failures := make(chan bool, 8)
	for i := 0; i < 8; i++ {
		workers.Add(1)
		go func() {
			defer workers.Done()
			for n := 0; n < 128; n++ {
				if !cache.valid(public) || cache.valid(make([]byte, 32)) {
					failures <- true
					return
				}
			}
		}()
	}
	workers.Wait()
	close(failures)
	if len(failures) != 0 || len(cache.values) != 1 {
		t.Fatal("concurrent point admission diverged")
	}
}

func TestCachedAuthorStillRequiresEveryMessageAndSignature(t *testing.T) {
	key := ed25519.NewKeyFromSeed(bytes.Repeat([]byte{44}, 32))
	public := key.Public().(ed25519.PublicKey)
	message := []byte("GG-PUBLIC-CACHE-MESSAGE-A")
	signature := ed25519.Sign(key, message)
	if !validAuthorKey(public) || !verifyTransactionSignature(public, message, signature) {
		t.Fatal("valid fixture refused")
	}
	if verifyTransactionSignature(public, []byte("GG-PUBLIC-CACHE-MESSAGE-B"), signature) {
		t.Fatal("author cache bypassed message verification")
	}
	identityR := append([]byte{}, signature...)
	copy(identityR[:32], make([]byte, 32))
	identityR[0] = 1
	if verifyTransactionSignature(public, message, identityR) {
		t.Fatal("author cache bypassed signature-point validation")
	}
	changed := append([]byte{}, signature...)
	changed[63] |= 0x80
	if verifyTransactionSignature(public, message, changed) {
		t.Fatal("author cache bypassed scalar validation")
	}
}
