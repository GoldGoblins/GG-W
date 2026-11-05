package main

import (
	"bytes"
	"crypto/ed25519"
	"testing"

	"github.com/oasisprotocol/curve25519-voi/curve"
)

func TestTransactionSignatureAdmissionProfile(t *testing.T) {
	// Explicitly public deterministic fixture, never an operator/wallet key.
	key := ed25519.NewKeyFromSeed(bytes.Repeat([]byte{42}, ed25519.SeedSize))
	public := key.Public().(ed25519.PublicKey)
	message := []byte("GG-PUBLIC-AUDIT-DOMAIN-A")
	signature := ed25519.Sign(key, message)
	if !validAuthorKey(public) || !verifyTransactionSignature(public, message, signature) {
		t.Fatal("generated fixture rejected")
	}
	if verifyTransactionSignature(public, append(message, 1), signature) {
		t.Fatal("wrong message accepted")
	}
	identity := make([]byte, 32)
	identity[0] = 1
	weak := append(append([]byte{}, identity...), make([]byte, 32)...)
	if validAuthorKey(identity) || verifyTransactionSignature(identity, message, weak) {
		t.Fatal("identity author accepted")
	}
	// L in canonical little-endian representation; S must be strictly below it.
	order := []byte{0xed, 0xd3, 0xf5, 0x5c, 0x1a, 0x63, 0x12, 0x58, 0xd6, 0x9c, 0xf7, 0xa2, 0xde, 0xf9, 0xde, 0x14, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0x10}
	if validTransactionSignatureEncoding(append(append([]byte{}, identity...), order...)) {
		t.Fatal("noncanonical S=L accepted")
	}
	if validAuthorKey(make([]byte, 32)) {
		t.Fatal("torsion author accepted")
	}
	if validTransactionSignatureEncoding(append(make([]byte, 32), signature[32:]...)) {
		t.Fatal("torsion R accepted")
	}
	if validTransactionSignatureEncoding(append(append([]byte{}, identity...), signature[32:]...)) {
		t.Fatal("identity R accepted")
	}
	var normal, torsion, mixed curve.EdwardsPoint
	if normal.UnmarshalBinary(public) != nil || torsion.UnmarshalBinary(make([]byte, 32)) != nil {
		t.Fatal("invalid test fixture")
	}
	mixed.Add(&normal, &torsion)
	encoded, err := mixed.MarshalBinary()
	if err != nil || validAuthorKey(encoded) {
		t.Fatal("mixed-order author accepted")
	}
}
