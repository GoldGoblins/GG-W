//go:build !js

package main

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"os"
	"path/filepath"
	"strings"
	"testing"

	abci "github.com/cometbft/cometbft/abci/types"
	cmtproto "github.com/cometbft/cometbft/proto/tendermint/types"
)

func observerGrantFixture(t *testing.T) (Genesis, string, nativeObserverGrant, []ed25519.PrivateKey) {
	t.Helper()
	genesis, anchor, committee := membershipFixture(t)
	_, producers := dagFixture(t)
	seed := sha256.Sum256([]byte("public-native-observer-node-fixture"))
	node := ed25519.NewKeyFromSeed(seed[:])
	keys := []ed25519.PrivateKey{node, committee[0][3], producers[0]}
	body := nativeObserverGrantBody{GenesisHash: anchor, Host: "127.0.0.2", LabelUTF8: base64.StdEncoding.EncodeToString([]byte("Full nod Göteborg")),
		NodeKey: hex.EncodeToString(node.Public().(ed25519.PublicKey)), OwnerPeerKey: hex.EncodeToString(keys[1].Public().(ed25519.PublicKey)),
		P2PPort: 24000, ProducerKey: genesis.DAG.Genesis.Producers[0], Schema: nativeObserverGrantSchema, SignatureProfile: TransactionSignatureProfile}
	grant := signObserverGrantFixture(body, keys)
	if validateNativeObserverGrant(grant, genesis, anchor) != nil {
		t.Fatal("valid public observer fixture rejected")
	}
	return genesis, anchor, grant, keys
}

func signObserverGrantFixture(body nativeObserverGrantBody, keys []ed25519.PrivateKey) nativeObserverGrant {
	sign := func(index int, role string) string {
		return hex.EncodeToString(ed25519.Sign(keys[index], append([]byte("GG-NATIVE-OBSERVER-"+strings.ToUpper(role)+"-GRANT-v1\x00"), canonical(body)...)))
	}
	return nativeObserverGrant{Body: body, NodeSignature: sign(0, "node"), OwnerSignature: sign(1, "owner"), ProducerSignature: sign(2, "producer")}
}

func TestNativeObserverPublicIdentityCannotSignVotesOrProposals(t *testing.T) {
	_, _, grant, _ := observerGrantFixture(t)
	public, _ := hex.DecodeString(grant.Body.NodeKey)
	original := append([]byte(nil), public...)
	pv, err := newNativeObserverPV(public)
	if err != nil {
		t.Fatal(err)
	}
	public[0] ^= 1
	key, err := pv.GetPubKey()
	if err != nil || !bytes.Equal(key.Bytes(), original) {
		t.Fatal("mutable constructor public key")
	}
	returned := key.Bytes()
	returned[0] ^= 1
	key, err = pv.GetPubKey()
	if err != nil || !bytes.Equal(key.Bytes(), original) {
		t.Fatal("mutable returned public key")
	}
	vote := &cmtproto.Vote{Height: 1, Round: 0}
	proposal := &cmtproto.Proposal{Height: 1, Round: 0}
	if pv.SignVote("any-chain", vote) == nil || pv.SignProposal("any-chain", proposal) == nil || len(vote.Signature) != 0 || len(proposal.Signature) != 0 {
		t.Fatal("public-only observer produced a consensus signature")
	}
	if pv.SignVote("any-chain", nil) == nil || pv.SignProposal("any-chain", nil) == nil {
		t.Fatal("nil request enabled signing")
	}
	if _, err := newNativeObserverPV(make([]byte, 32)); err == nil {
		t.Fatal("invalid public identity accepted")
	}
}

func TestNativeObserverGrantContextAndEveryPossessionProof(t *testing.T) {
	genesis, anchor, original, keys := observerGrantFixture(t)
	for _, kind := range []string{"node_signature", "owner_signature", "producer_signature", "foreign_genesis", "unregistered_producer", "public_host", "noncanonical_host", "invalid_port", "endpoint_collision", "bad_label", "label_control", "wrong_profile", "node_role_alias", "owner_role_alias", "owner_producer_alias", "wrong_schema"} {
		t.Run(kind, func(t *testing.T) {
			grant := original
			changedKeys := append([]ed25519.PrivateKey(nil), keys...)
			switch kind {
			case "node_signature":
				grant.NodeSignature = strings.Repeat("0", 128)
			case "owner_signature":
				grant.OwnerSignature = strings.Repeat("0", 128)
			case "producer_signature":
				grant.ProducerSignature = strings.Repeat("0", 128)
			case "foreign_genesis":
				grant.Body.GenesisHash = DagZero
			case "unregistered_producer":
				grant.Body.ProducerKey = grant.Body.OwnerPeerKey
			case "public_host":
				grant.Body.Host = "8.8.8.8"
			case "noncanonical_host":
				grant.Body.Host = "127.000.0.2"
			case "invalid_port":
				grant.Body.P2PPort = 0
			case "endpoint_collision":
				grant.Body.Host, grant.Body.P2PPort = genesis.Membership.Validators[0].Body.Host, genesis.Membership.Validators[0].Body.P2PPort
			case "bad_label":
				grant.Body.LabelUTF8 = "!"
			case "label_control":
				grant.Body.LabelUTF8 = base64.StdEncoding.EncodeToString([]byte("bad\nlabel"))
			case "wrong_profile":
				grant.Body.SignatureProfile = "OTHER"
			case "node_role_alias":
				grant.Body.NodeKey = grant.Body.ProducerKey
				changedKeys[0] = keys[2]
			case "owner_role_alias":
				_, _, committee := membershipFixture(t)
				changedKeys[1] = committee[0][0]
				grant.Body.OwnerPeerKey = hex.EncodeToString(changedKeys[1].Public().(ed25519.PublicKey))
			case "owner_producer_alias":
				grant.Body.OwnerPeerKey = grant.Body.ProducerKey
				changedKeys[1] = keys[2]
			case "wrong_schema":
				grant.Body.Schema = "OTHER"
			}
			if !strings.HasSuffix(kind, "_signature") {
				grant = signObserverGrantFixture(grant.Body, changedKeys)
			}
			if validateNativeObserverGrant(grant, genesis, anchor) == nil {
				t.Fatal("invalid observer capability accepted", kind)
			}
		})
	}
}

func TestNativeObserverPeerFileRequiresCanonicalBoundedIndependentCapability(t *testing.T) {
	genesis, anchor, grant, keys := observerGrantFixture(t)
	root := t.TempDir()
	policy, err := newNativeObserverPeerPolicy(genesis, anchor, root)
	if err != nil {
		t.Fatal(err)
	}
	before := canonical(genesis)
	path := filepath.Join(root, nativeObserverAdmissionFile)
	ctx := context.Background()
	observerID := "/p2p/filter/id/" + membershipNodeID(grant.Body.NodeKey)
	committeeID := "/p2p/filter/id/" + membershipNodeID(genesis.Membership.Validators[0].Body.NodeKey)
	if policy.allowed(ctx, observerID) || !policy.allowed(ctx, committeeID) {
		t.Fatal("missing optional file changed fixed membership")
	}
	write := func(raw []byte) {
		t.Helper()
		if os.WriteFile(path, raw, 0600) != nil {
			t.Fatal("owned public file write")
		}
	}
	document := nativeObserverAdmissionDocument{GenesisHash: anchor, Grants: []nativeObserverGrant{grant}, Schema: nativeObserverAdmissionSchema}
	write(canonical(document))
	if !policy.allowed(ctx, observerID) || !policy.allowed(ctx, "/p2p/filter/addr/127.0.0.2:49000") || policy.allowed(ctx, "/p2p/filter/addr/8.8.8.8:49000") {
		t.Fatal("registered read-only identity/address mismatch")
	}
	// Same length and restored mtime must not preserve an obsolete cached set.
	info, _ := os.Stat(path)
	seed := sha256.Sum256([]byte("second public observer identity"))
	other := ed25519.NewKeyFromSeed(seed[:])
	changed := grant.Body
	changed.NodeKey = hex.EncodeToString(other.Public().(ed25519.PublicKey))
	document.Grants = []nativeObserverGrant{signObserverGrantFixture(changed, []ed25519.PrivateKey{other, keys[1], keys[2]})}
	write(canonical(document))
	_ = os.Chtimes(path, info.ModTime(), info.ModTime())
	if policy.allowed(ctx, observerID) || !policy.allowed(ctx, "/p2p/filter/id/"+membershipNodeID(changed.NodeKey)) {
		t.Fatal("mtime/size substituted for complete capability bytes")
	}
	for _, raw := range [][]byte{[]byte("broken"), append(canonical(document), '\n'), bytes.Repeat([]byte("x"), nativeObserverAdmissionMax+1),
		canonical(nativeObserverAdmissionDocument{GenesisHash: anchor, Grants: []nativeObserverGrant{grant, grant}, Schema: nativeObserverAdmissionSchema})} {
		write(raw)
		if policy.allowed(ctx, observerID) || !policy.allowed(ctx, committeeID) {
			t.Fatal("corrupt optional file grants access or disables committee")
		}
	}
	if !bytes.Equal(before, canonical(genesis)) || len(genesis.Validators) != 4 {
		t.Fatal("observer admission changed consensus genesis")
	}
}

type observerCancelContext struct {
	context.Context
	cancel    context.CancelFunc
	remaining int
}

func (ctx *observerCancelContext) Err() error {
	ctx.remaining--
	if ctx.remaining <= 0 {
		ctx.cancel()
	}
	return ctx.Context.Err()
}

func TestNativeObserverCancelledCapabilityReadCannotPoisonNextPeer(t *testing.T) {
	genesis, anchor, grant, _ := observerGrantFixture(t)
	root := t.TempDir()
	policy, err := newNativeObserverPeerPolicy(genesis, anchor, root)
	if err != nil {
		t.Fatal(err)
	}
	raw := canonical(nativeObserverAdmissionDocument{GenesisHash: anchor, Grants: []nativeObserverGrant{grant}, Schema: nativeObserverAdmissionSchema})
	if os.WriteFile(filepath.Join(root, nativeObserverAdmissionFile), raw, 0600) != nil {
		t.Fatal("file")
	}
	base, cancel := context.WithCancel(context.Background())
	defer cancel()
	ctx := &observerCancelContext{Context: base, cancel: cancel, remaining: 3}
	if _, valid := policy.grants(ctx); valid {
		t.Fatal("cancelled work granted peer access")
	}
	if policy.allowed(nil, "/p2p/filter/id/"+membershipNodeID(grant.Body.NodeKey)) || !policy.allowed(context.Background(), "/p2p/filter/id/"+membershipNodeID(grant.Body.NodeKey)) {
		t.Fatal("cancelled verification poisoned a later genuine peer")
	}
}

func TestNativeObserverQueryClientAppliesPeerPolicyWithoutChangingLedger(t *testing.T) {
	genesis, anchor, grant, _ := observerGrantFixture(t)
	root := t.TempDir()
	app, err := newDagEnabledLedger(genesis, anchor, root, true)
	if err != nil {
		t.Fatal(err)
	}
	defer app.Close()
	policy, err := newNativeObserverPeerPolicy(genesis, anchor, root)
	if err != nil {
		t.Fatal(err)
	}
	creator := newLedgerClientCreatorWithPeers(app, policy)
	client, err := creator.NewABCIClient()
	if err != nil {
		t.Fatal(err)
	}
	ctx := context.Background()
	path := "/p2p/filter/id/" + membershipNodeID(grant.Body.NodeKey)
	before := canonical(app.state)
	result, err := client.Query(ctx, &abci.RequestQuery{Path: path})
	if err != nil || result.Code == 0 {
		t.Fatal("unknown peer accepted")
	}
	document := nativeObserverAdmissionDocument{GenesisHash: anchor, Grants: []nativeObserverGrant{grant}, Schema: nativeObserverAdmissionSchema}
	if os.WriteFile(filepath.Join(root, nativeObserverAdmissionFile), canonical(document), 0600) != nil {
		t.Fatal("owned capability file")
	}
	result, err = client.Query(ctx, &abci.RequestQuery{Path: path})
	if err != nil || result.Code != 0 {
		t.Fatal("actual ABCI client did not authorize valid read-only peer", err)
	}
	result, err = client.Query(ctx, &abci.RequestQuery{Path: "/gg/genesis"})
	if err != nil || result.Code != 0 || !bytes.Equal(before, canonical(app.state)) {
		t.Fatal("peer policy changed ledger or broke ordinary query", err)
	}
}

func TestNativeObserverBootstrapHasNoValidatorSeedAndImmutableRole(t *testing.T) {
	genesis, anchor, grant, keys := observerGrantFixture(t)
	fresh := true
	request := nativeObserverBootstrap{ExpectedFresh: &fresh, Genesis: genesis, GenesisHash: anchor, NodeSeed: hex.EncodeToString(keys[0].Seed()),
		ObserverGrant: grant, Root: filepath.Join(t.TempDir(), "native"), RPCPort: 24001, Schema: nativeObserverBootstrapSchema}
	boot, err := decodeNativeBootstrap(canonical(request))
	if err != nil || boot.observer == nil || boot.ValidatorIndex != -1 || boot.ValidatorSeed != "" {
		t.Fatal("observer was decoded as a signer", err)
	}
	name, identity, err := nativeRootIdentity(boot)
	if err != nil || name != nativeObserverRootFile || bytes.Contains(identity, []byte(request.NodeSeed)) {
		t.Fatal("root marker leaked or confused identity", err)
	}
	for _, field := range []string{"validator_seed", "validator_index", "verified", "observer"} {
		var value map[string]any
		_ = decodeStrict(canonical(request), &value)
		value[field] = true
		if _, err := decodeNativeBootstrap(canonical(value)); err == nil {
			t.Fatal("observer accepted a caller signing/verification field", field)
		}
	}
	wrong := request
	wrong.ExpectedFresh = nil
	if _, err := decodeNativeBootstrap(canonical(wrong)); err == nil {
		t.Fatal("implicit fresh/resume accepted")
	}
	wrong = request
	wrong.NodeSeed = strings.Repeat("0", 64)
	if _, err := decodeNativeBootstrap(canonical(wrong)); err == nil {
		t.Fatal("foreign P2P key accepted")
	}
	if os.MkdirAll(boot.Root, 0700) != nil || os.WriteFile(filepath.Join(boot.Root, nativeObserverRootFile), identity, 0600) != nil {
		t.Fatal("owned root fixture")
	}
	ordinary := Bootstrap{Root: boot.Root, Genesis: genesis}
	if _, _, err := nativeRootIdentity(ordinary); err == nil {
		t.Fatal("validator adopted observer root")
	}
	if os.WriteFile(filepath.Join(boot.Root, "gg-public-genesis.json"), canonical(genesis), 0600) != nil {
		t.Fatal("owned collision fixture")
	}
	if _, _, err := nativeRootIdentity(boot); err == nil {
		t.Fatal("observer adopted a validator root")
	}
}
