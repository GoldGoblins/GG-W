package main

import (
	"bytes"
	"crypto/ed25519"
	"crypto/sha256"
	"fmt"
	"runtime"
	"testing"
	"unsafe"
)

func TestAuthorPublicPointCacheRetainsWorkingSetAndEvictsExactOldest(t *testing.T) {
	if authorKeyCacheLimit != 8192 {
		t.Fatal("bounded 5008-account fixture working-set contract changed")
	}
	keys := make([][ed25519.PublicKeySize]byte, authorKeyCacheLimit+1)
	for index := range keys {
		seed := sha256.Sum256([]byte(fmt.Sprintf("GG PUBLIC WORKING SET KEY %d", index)))
		copy(keys[index][:], ed25519.NewKeyFromSeed(seed[:])[ed25519.SeedSize:])
	}
	runtime.GC()
	var before, after runtime.MemStats
	runtime.ReadMemStats(&before)
	cache := new(authorKeyCache)
	for index := 0; index < authorKeyCacheLimit; index++ {
		input := append([]byte{}, keys[index][:]...)
		if !cache.valid(input) {
			t.Fatal("actual prime-order public fixture rejected", index)
		}
		// The cache owns an array copy before point admission. A caller's
		// mutable backing bytes must never change an accepted public point.
		clear(input)
		if cache.valid(input) || !cache.valid(keys[index][:]) {
			t.Fatal("caller alias changed accepted key or admitted torsion")
		}
		if len(cache.values) != index+1 {
			t.Fatal("cache entry count differs from distinct positive keys")
		}
	}
	if len(cache.values) != authorKeyCacheLimit || cache.next != 0 {
		t.Fatal("full public cache did not retain its exact bound")
	}
	// Every account in the actual 5008-account financial fixture fits inside
	// this one cache. Hits cannot advance the eviction ring or evict a key.
	for index := 0; index < 5008; index++ {
		if !cache.values[keys[index]] || !cache.valid(keys[index][:]) {
			t.Fatal("working-set positive public point was evicted", index)
		}
	}
	if cache.next != 0 || len(cache.values) != authorKeyCacheLimit {
		t.Fatal("positive hit changed bounded eviction state")
	}
	runtime.GC()
	runtime.ReadMemStats(&after)
	// A process heap delta is diagnostic, not a portable map-layout contract.
	// The exact fixed FIFO size and entry/eviction limits are asserted below.
	if after.HeapAlloc >= before.HeapAlloc {
		t.Logf("public point cache: entries=%d, fixed_object_bytes=%d, observed_held_heap_delta_bytes=%d", len(cache.values), unsafe.Sizeof(*cache), after.HeapAlloc-before.HeapAlloc)
	} else {
		t.Logf("public point cache: entries=%d, fixed_object_bytes=%d; process heap delta affected by unrelated reclamation", len(cache.values), unsafe.Sizeof(*cache))
	}
	if unsafe.Sizeof(cache.order) != uintptr(authorKeyCacheLimit*ed25519.PublicKeySize) {
		t.Fatal("public FIFO storage differs from finite key bound")
	}
	if !cache.valid(keys[authorKeyCacheLimit][:]) || len(cache.values) != authorKeyCacheLimit || cache.next != 1 || cache.values[keys[0]] {
		t.Fatal("new positive key did not evict exactly the oldest entry")
	}
	for index := 1; index <= authorKeyCacheLimit; index++ {
		if !cache.values[keys[index]] {
			t.Fatal("positive insertion evicted an unrelated cached public key", index)
		}
	}
	identity := make([]byte, ed25519.PublicKeySize)
	identity[0] = 1
	for _, invalid := range [][]byte{nil, make([]byte, 31), make([]byte, 33), make([]byte, 32), identity} {
		if cache.valid(invalid) || len(cache.values) != authorKeyCacheLimit || cache.next != 1 || cache.values[keys[0]] || !cache.values[keys[1]] {
			t.Fatal("invalid point was cached or changed positive eviction state")
		}
	}
	// Once evicted, the original point must validate anew and replace only
	// the next FIFO entry. Eviction never changes the cryptographic decision.
	if !cache.valid(keys[0][:]) || cache.next != 2 || !cache.values[keys[0]] || cache.values[keys[1]] || len(cache.values) != authorKeyCacheLimit {
		t.Fatal("evicted public point changed acceptance or FIFO bound")
	}
	runtime.KeepAlive(cache)
	runtime.KeepAlive(keys)
}

func TestCachedPublicPointStillChecksEverySignatureForBothProviders(t *testing.T) {
	key := ed25519.NewKeyFromSeed(bytes.Repeat([]byte{91}, ed25519.SeedSize))
	public := append([]byte{}, key[ed25519.SeedSize:]...)
	message := []byte("GG PUBLIC WORKING SET SIGNATURE ORIGINAL")
	signature := ed25519.Sign(key, message)
	if !validAuthorKey(public) || !validAuthorKey(public) {
		t.Fatal("positive public-key hit fixture unavailable")
	}
	identityR := append([]byte{}, signature...)
	clear(identityR[:32])
	identityR[0] = 1
	torsionR := append([]byte{}, signature...)
	clear(torsionR[:32])
	noncanonicalS := append([]byte{}, signature...)
	copy(noncanonicalS[32:], bytes.Repeat([]byte{255}, 32))
	for _, exactR := range []bool{false, true} {
		if !verifyTransactionSignatureForProvider(public, message, signature, exactR) {
			t.Fatal("cached public point changed valid standard signature acceptance")
		}
		if verifyTransactionSignatureForProvider(public, append(append([]byte{}, message...), 1), signature, exactR) {
			t.Fatal("positive public-key hit bypassed actual message verification")
		}
		for _, invalid := range [][]byte{identityR, torsionR, noncanonicalS, signature[:63], append(append([]byte{}, signature...), 0)} {
			if verifyTransactionSignatureForProvider(public, message, invalid, exactR) {
				t.Fatal("positive public-key hit bypassed signature/point/scalar/length checks")
			}
		}
	}
	alias := append([]byte{}, public...)
	clear(alias)
	alias[0] = 1
	if validAuthorKey(alias) || !verifyTransactionSignature(public, message, signature) {
		t.Fatal("caller alias mutation changed cached canonical key/signature decision")
	}
}
