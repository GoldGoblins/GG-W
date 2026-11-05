package main

import (
	"bytes"
	"crypto/ed25519"
	"crypto/sha256"
	"crypto/sha512"
	"encoding/binary"
	"testing"

	"github.com/oasisprotocol/curve25519-voi/curve"
	"github.com/oasisprotocol/curve25519-voi/curve/scalar"
)

// Independent previous predicate: explicitly check BOTH points and S before
// standard verification. No call to the candidate's equation shortcut.
func previousFullPointSignatureOracle(public, message, signature []byte) bool {
	return canonicalPrimePoint(public, true) && validTransactionSignatureEncoding(signature) && ed25519.Verify(public, message, signature)
}

func compareEquationProfile(t *testing.T, public, message, signature []byte) bool {
	t.Helper()
	expected := previousFullPointSignatureOracle(public, message, signature)
	for _, exact := range []bool{false, true} {
		if verifyTransactionSignatureForProvider(public, message, signature, exact) != expected {
			t.Fatalf("full subgroup oracle disagreement; reviewed equation=%v", exact)
		}
	}
	return expected
}

func TestExactRValidAndMutatedInputsMatchFullPointOracle(t *testing.T) {
	keys := make([]ed25519.PrivateKey, 6)
	for i := range keys {
		keys[i] = ed25519.NewKeyFromSeed(bytes.Repeat([]byte{byte(71 + i)}, 32))
	}
	for i := 0; i < 1000; i++ {
		var counter [8]byte
		binary.LittleEndian.PutUint64(counter[:], uint64(i))
		digest := sha256.Sum256(append([]byte("GG-PUBLIC-EQUATION-PROFILE-FIXTURE"), counter[:]...))
		message := digest[:]
		key := keys[i%len(keys)]
		public := key.Public().(ed25519.PublicKey)
		signature := ed25519.Sign(key, message)
		if !compareEquationProfile(t, public, message, signature) {
			t.Fatal("valid deterministic fixture rejected")
		}
		changed := append([]byte{}, signature...)
		changed[i%len(changed)] ^= byte(i%7 + 1)
		compareEquationProfile(t, public, message, changed)
		other := append([]byte{}, public...)
		other[i%len(other)] ^= byte(i%7 + 1)
		compareEquationProfile(t, other, message, signature)
		compareEquationProfile(t, public, append(append([]byte{}, message...), 1), signature)
	}
	key := keys[0]
	public := key.Public().(ed25519.PublicKey)
	message := []byte("public length fixture")
	signature := ed25519.Sign(key, message)
	for _, bad := range [][]byte{nil, public[:31], append(append([]byte{}, public...), 0)} {
		compareEquationProfile(t, bad, message, signature)
	}
	for _, bad := range [][]byte{nil, signature[:63], append(append([]byte{}, signature...), 0)} {
		compareEquationProfile(t, public, message, bad)
	}
}

func TestExactRAllTorsionCosetsAndIdentityKeepOriginalProfile(t *testing.T) {
	if !curve.EIGHT_TORSION[0].IsIdentity() {
		t.Fatal("public torsion fixture ordering changed")
	}
	identityCases := 0
	primeCases := 0
	nonPrimeCases := 0
	for _, secret := range []uint64{7, 19} {
		a := scalar.NewFromUint64(secret)
		var author curve.EdwardsPoint
		author.Mul(curve.ED25519_BASEPOINT_POINT, a)
		public, err := author.MarshalBinary()
		if err != nil || !canonicalPrimePoint(public, true) {
			t.Fatal("invalid public author fixture")
		}
		for _, nonce := range []uint64{0, 1, 11} {
			r := scalar.NewFromUint64(nonce)
			var base curve.EdwardsPoint
			base.Mul(curve.ED25519_BASEPOINT_POINT, r)
			for index, torsion := range curve.EIGHT_TORSION {
				var point curve.EdwardsPoint
				point.Add(&base, torsion)
				encoded, err := point.MarshalBinary()
				if err != nil {
					t.Fatal(err)
				}
				for counter := byte(0); counter < 4; counter++ {
					message := append([]byte("GG-PUBLIC-COFACTORED-POINT-FIXTURE"), counter)
					hasher := sha512.New()
					hasher.Write(encoded)
					hasher.Write(public)
					hasher.Write(message)
					h, err := scalar.NewFromBytesModOrderWide(hasher.Sum(nil))
					if err != nil {
						t.Fatal(err)
					}
					var product, s scalar.Scalar
					product.Mul(h, a)
					s.Add(&product, r)
					scalarBytes, err := s.MarshalBinary()
					if err != nil {
						t.Fatal(err)
					}
					signature := append(append([]byte{}, encoded...), scalarBytes...)
					accepted := compareEquationProfile(t, public, message, signature)
					standard := ed25519.Verify(public, message, signature)
					switch {
					case index != 0:
						nonPrimeCases++
						if standard || accepted {
							t.Fatal("nonzero torsion coset accepted by exact-R verifier")
						}
					case nonce == 0:
						identityCases++
						if !standard || accepted {
							t.Fatal("identity must satisfy standard equation but fail application profile")
						}
					default:
						primeCases++
						if !standard || !accepted {
							t.Fatal("valid prime-order R rejected")
						}
					}
				}
			}
		}
	}
	if identityCases != 8 || primeCases != 16 || nonPrimeCases != 168 {
		t.Fatal("public coset coverage incomplete")
	}
}
