package main

// The application's transaction/key admission profile is shared with Python.
// This does not replace CometBFT's consensus-vote verification rules.
import (
	"bytes"
	"crypto/ed25519"
	"runtime"
	"sync"

	"github.com/oasisprotocol/curve25519-voi/curve"
	"github.com/oasisprotocol/curve25519-voi/curve/scalar"
)

const TransactionSignatureProfile = "GG-Ed25519-PrimeOrder-v1"

func canonicalPrimePoint(raw []byte, author bool) bool {
	if len(raw) != ed25519.PublicKeySize {
		return false
	}
	var point curve.EdwardsPoint
	if point.UnmarshalBinary(raw) != nil {
		return false
	}
	canonical, err := point.MarshalBinary()
	return err == nil && bytes.Equal(raw, canonical) && point.IsTorsionFree() && (!author || !point.IsIdentity())
}

// The finite account working set is 5008 public points in the 5000-recipient
// native acceptance fixture. Retain it without repeated subgroup validation.
// The FIFO uses exactly 8192*32 bytes (256KiB), plus a map with at most 8192
// immutable public keys/bools and Go allocator overhead. Entry count, rather
// than an implementation-dependent map byte estimate, is the hard bound.
const authorKeyCacheLimit = 8192

// Only immutable PUBLIC points with successful canonical/nonidentity/subgroup
// validation are cached. No message, signature, private input or failed point
// is stored. Eviction changes cost only, never the admission decision.
type authorKeyCache struct {
	mu     sync.Mutex
	values map[[ed25519.PublicKeySize]byte]bool
	order  [authorKeyCacheLimit][ed25519.PublicKeySize]byte
	next   int
}

func (cache *authorKeyCache) valid(public []byte) bool {
	if len(public) != ed25519.PublicKeySize {
		return false
	}
	var key [ed25519.PublicKeySize]byte
	copy(key[:], public)
	cache.mu.Lock()
	known := cache.values[key]
	cache.mu.Unlock()
	if known {
		return true
	}
	// Validate the owned copy, not caller-owned mutable backing storage.
	if !canonicalPrimePoint(key[:], true) {
		return false
	}
	cache.mu.Lock()
	defer cache.mu.Unlock()
	if cache.values == nil {
		cache.values = make(map[[ed25519.PublicKeySize]byte]bool)
	}
	if !cache.values[key] {
		if len(cache.values) == authorKeyCacheLimit {
			delete(cache.values, cache.order[cache.next])
		}
		cache.values[key] = true
		cache.order[cache.next] = key
		cache.next = (cache.next + 1) % authorKeyCacheLimit
	}
	return true
}

var transactionAuthorKeys authorKeyCache

func validAuthorKey(public []byte) bool { return transactionAuthorKeys.valid(public) }

func validTransactionSignatureEncoding(signature []byte) bool {
	if len(signature) != ed25519.SignatureSize {
		return false
	}
	var s scalar.Scalar
	if _, err := s.SetCanonicalBytes(signature[32:]); err != nil {
		return false
	}
	return canonicalPrimePoint(signature[:32], true)
}

// Go1.27.3 was reviewed down to its standard verifier: canonical S and
// exact encoded R=[S]B-[H(R,A,M)]A, with no cofactor multiplication. Once A
// is prime-order this proves canonical prime-order R. Identity is explicitly
// forbidden by our profile. Other compiler releases retain BOTH point checks.
// Every accepted message/signature still goes through standard verification;
// no cryptographic verification decision or private material is cached.
func verifyTransactionSignatureForProvider(public, message, signature []byte, exactR bool) bool {
	if len(public) != ed25519.PublicKeySize || len(signature) != ed25519.SignatureSize {
		return false
	}
	var author [ed25519.PublicKeySize]byte
	var proof [ed25519.SignatureSize]byte
	copy(author[:], public)
	copy(proof[:], signature)
	if !validAuthorKey(author[:]) {
		return false
	}
	if exactR {
		identity := [ed25519.PublicKeySize]byte{1}
		if bytes.Equal(proof[:ed25519.PublicKeySize], identity[:]) {
			return false
		}
	} else if !validTransactionSignatureEncoding(proof[:]) {
		return false
	}
	return ed25519.Verify(author[:], message, proof[:])
}

func verifyTransactionSignature(public, message, signature []byte) bool {
	return verifyTransactionSignatureForProvider(public, message, signature, runtime.Version() == "go1.27.3")
}
