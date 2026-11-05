//go:build !js

package main

import (
	"crypto/ed25519"
	"encoding/hex"
	"testing"
)

func TestDagSegmentedNetworkDomainRejectsCrossNetworkFirstSignedBlock(t *testing.T) {
	first, keys := segmentedFixture(t)
	wire := segmentedWire(t, first.active, keys, 0, 3)
	source := first.source
	source.NetworkID = hashHex([]byte("different explicitly pinned DAG network"))
	source.Genesis.ChainID = source.chainID()
	source.GenesisHash = dagDigest("GG-DAG-DATA-v1\x00", source.Genesis)
	second, err := newDagSegmentedExecution(source, hashHex([]byte("different native anchor")))
	if err != nil {
		t.Fatal(err)
	}
	if _, err = second.apply(segmentedBatch(t, second.active, wire), 1700000002000000000); err == nil {
		t.Fatal("same signed initial block replayed in another source network")
	}
}

func TestDagSegmentedNetworkDomainBindsNativeIdentityAndInitialTransactionNamespace(t *testing.T) {
	first, _ := segmentedFixture(t)
	second := first.source
	second.NetworkID = hashHex([]byte("second DAG network context"))
	second.Genesis.ChainID = second.chainID()
	second.GenesisHash = dagDigest("GG-DAG-DATA-v1\x00", second.Genesis)
	if validateSegmentedSource(second) != nil || second.Genesis.ChainID == first.source.Genesis.ChainID || second.GenesisHash == first.source.GenesisHash {
		t.Fatal("different network did not derive a distinct block/TX/genesis domain")
	}
	bad := first.source
	bad.NetworkID = second.NetworkID
	if validateSegmentedSource(bad) == nil {
		t.Fatal("source network changed without deriving its corresponding identity")
	}
}

func TestDagSegmentedNetworkDomainUsesEntireSHA256Identity(t *testing.T) {
	first, _ := segmentedFixture(t)
	normalized := first.source
	normalized.Genesis.ChainID, normalized.GenesisHash = "", ""
	if len(first.source.Genesis.ChainID) != 70 || first.source.Genesis.ChainID != "ggdag:"+dagDigest("GG-DAG-SEGMENTED-CHAIN-ID-v1\x00", normalized) {
		t.Fatal("network signing domain truncated its digest")
	}
	if first.active.Source.Genesis.ChainID != first.source.Genesis.ChainID || first.active.Commitment.ChainID != first.source.Genesis.ChainID {
		t.Fatal("private legacy shape alias leaked into real execution")
	}
}

func TestDagSegmentedNetworkDomainRejectsForeignTXInsideCorrectlyResignedOuterBlock(t *testing.T) {
	first, keys := segmentedFixture(t)
	source := first.source
	source.NetworkID = hashHex([]byte("foreign TX test network"))
	source.Genesis.ChainID = source.chainID()
	source.GenesisHash = dagDigest("GG-DAG-DATA-v1\x00", source.Genesis)
	second, err := newDagSegmentedExecution(source, hashHex([]byte("foreign TX test anchor")))
	if err != nil {
		t.Fatal(err)
	}
	var old, wrapped DagBlock
	if decodeStrict(segmentedWire(t, first.active, keys, 0, 3), &old) != nil || decodeStrict(segmentedWire(t, second.active, keys, 0, 3), &wrapped) != nil {
		t.Fatal("fixture")
	}
	wrapped.Body.Transactions = old.Body.Transactions
	wrapped.Body.PayloadRoot = dagRoot(wrapped.Body.Transactions, "GG-DAG-PAYLOAD-v1\x00")
	wrapped.Signature = hex.EncodeToString(ed25519.Sign(keys[0], append([]byte("GG-DAG-PROPOSAL-SIGN-v1\x00"), canonical(wrapped.Body)...)))
	if _, err := second.apply(segmentedBatch(t, second.active, canonical(wrapped)), 1700000002000000000); err == nil {
		t.Fatal("correct outer network signature laundered foreign signed TX")
	}
}

func TestDagSegmentedNetworkDomainNeverSilentlyRehashesOldUnpublishedSource(t *testing.T) {
	first, _ := segmentedFixture(t)
	old := first.source
	view := old
	view.Genesis.ChainID, view.GenesisHash, view.NetworkID = "", "", ""
	old.Genesis.ChainID = "ggdag:" + dagDigest("GG-DAG-SEGMENTED-CHAIN-ID-v1\x00", view)[:24]
	old.GenesisHash = dagDigest("GG-DAG-DATA-v1\x00", old.Genesis)
	if validateSegmentedSource(old) == nil {
		t.Fatal("old unbound namespace was silently accepted or upgraded")
	}
}
