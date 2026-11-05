package main

import (
	"context"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"testing"

	abci "github.com/cometbft/cometbft/abci/types"
)

func membershipFixture(t *testing.T) (Genesis, string, [][]ed25519.PrivateKey) {
	t.Helper()
	base, _ := dagFixture(t)
	genesis, _, _, _ := testGenesis()
	genesis.Schema = "gg.native.genesis.v3"
	genesis.DAG = &base.Source
	keys := make([][]ed25519.PrivateKey, 4)
	invites := []ConsensusMemberInvite{}
	for i := 0; i < 4; i++ {
		keys[i] = []ed25519.PrivateKey{}
		for j := 0; j < 4; j++ {
			seed := sha256.Sum256([]byte("public-membership-fixture-" + strconv.Itoa(i) + "-" + strconv.Itoa(j)))
			keys[i] = append(keys[i], ed25519.NewKeyFromSeed(seed[:]))
		}
		public := func(j int) string { return hex.EncodeToString(keys[i][j].Public().(ed25519.PublicKey)) }
		body := ConsensusMemberBody{AccountKey: public(2), Host: "127.0.0.1", LabelUTF8: base64.StdEncoding.EncodeToString([]byte("Göteborg")),
			NodeKey: public(1), Nonce: strings.Repeat("a", 64), OwnerPeerKey: public(3), P2PPort: 23001 + i, Schema: "gg.consensus.validator.invite.v1",
			SignatureProfile: TransactionSignatureProfile, ValidatorKey: public(0)}
		sign := func(role string, index int) string {
			return hex.EncodeToString(ed25519.Sign(keys[i][index], append([]byte("GG-CONSENSUS-"+strings.ToUpper(role)+"-INVITE-v1\x00"), canonical(body)...)))
		}
		invites = append(invites, ConsensusMemberInvite{Body: body, ValidatorSignature: sign("validator", 0), NodeSignature: sign("node", 1), AccountSignature: sign("account", 2), OwnerSignature: sign("owner", 3)})
	}
	sort.Slice(invites, func(i, j int) bool { return invites[i].Body.ValidatorKey < invites[j].Body.ValidatorKey })
	genesis.Validators = []string{}
	genesis.Accounts = []string{}
	for _, invite := range invites {
		genesis.Validators = append(genesis.Validators, invite.Body.ValidatorKey)
		genesis.Accounts = append(genesis.Accounts, invite.Body.AccountKey)
	}
	genesis.Membership = &ConsensusMembership{ChainID: genesis.ChainID, GenesisTime: genesis.GenesisTime, Schema: "gg.lan.consensus.membership.v1", Scope: "PRIVATE_LAN_EXPERIMENT", Validators: invites}
	anchor := hashHex(canonical(genesis))
	if err := validateGenesis(genesis, anchor); err != nil {
		t.Fatal(err)
	}
	return genesis, anchor, keys
}

func TestMembershipGenesisBindsFourPossessionProofsRolesAndEndpoints(t *testing.T) {
	genesis, _, _ := membershipFixture(t)
	for _, kind := range []string{"owner_signature", "node_signature", "account_signature", "validator_signature", "account", "validator", "endpoint", "scope", "order", "role"} {
		t.Run(kind, func(t *testing.T) {
			var changed Genesis
			if decodeStrict(canonical(genesis), &changed) != nil {
				t.Fatal("fixture clone")
			}
			invite := &changed.Membership.Validators[0]
			switch kind {
			case "owner_signature":
				invite.OwnerSignature = strings.Repeat("0", 128)
			case "node_signature":
				invite.NodeSignature = strings.Repeat("0", 128)
			case "account_signature":
				invite.AccountSignature = strings.Repeat("0", 128)
			case "validator_signature":
				invite.ValidatorSignature = strings.Repeat("0", 128)
			case "account":
				changed.Accounts[0] = changed.Accounts[1]
			case "validator":
				changed.Validators[0] = changed.Validators[1]
			case "endpoint":
				invite.Body.Host = "8.8.8.8"
			case "scope":
				changed.Membership.Scope = "MAINNET"
			case "order":
				changed.Membership.Validators[0], changed.Membership.Validators[1] = changed.Membership.Validators[1], changed.Membership.Validators[0]
			case "role":
				invite.Body.NodeKey = invite.Body.ValidatorKey
			}
			if validateGenesis(changed, hashHex(canonical(changed))) == nil {
				t.Fatal("changed membership accepted")
			}
		})
	}
}

func TestMembershipPeerFilterRejectsUnregisteredAuthenticatedIdentity(t *testing.T) {
	genesis, anchor, _ := membershipFixture(t)
	app, err := newDagEnabledLedger(genesis, anchor, t.TempDir(), true)
	if err != nil {
		t.Fatal(err)
	}
	defer app.Close()
	for _, invite := range genesis.Membership.Validators {
		for _, path := range []string{"/p2p/filter/id/" + membershipNodeID(invite.Body.NodeKey), "/p2p/filter/addr/127.0.0.1:40000"} {
			result, _ := app.Query(context.Background(), &abci.RequestQuery{Path: path})
			if result.Code != 0 {
				t.Fatal("registered private peer rejected")
			}
		}
	}
	for _, path := range []string{"/p2p/filter/id/" + strings.Repeat("a", 40), "/p2p/filter/addr/8.8.8.8:40000", "/p2p/filter/addr/127.0.0.2:40000", "/p2p/filter/addr/127.0.0.1:0"} {
		result, _ := app.Query(context.Background(), &abci.RequestQuery{Path: path})
		if result.Code == 0 {
			t.Fatal("unregistered peer accepted")
		}
	}
}

func TestMembershipBootstrapRequiresBoundNodeKeyAndExplicitFreshOrResume(t *testing.T) {
	genesis, anchor, keys := membershipFixture(t)
	var owner []ed25519.PrivateKey
	for _, candidate := range keys {
		if hex.EncodeToString(candidate[0].Public().(ed25519.PublicKey)) == genesis.Validators[0] {
			owner = candidate
		}
	}
	fresh := true
	boot := Bootstrap{Schema: "gg.consensus.bootstrap.v2", Genesis: genesis, GenesisHash: anchor, ValidatorIndex: 0,
		ValidatorSeed: hex.EncodeToString(owner[0].Seed()), NodeSeed: hex.EncodeToString(owner[1].Seed()), Root: filepath.Join(t.TempDir(), "native"),
		RPCPort: 25000, P2PPort: genesis.Membership.Validators[0].Body.P2PPort, ExpectedFresh: &fresh}
	if validateBootstrap(boot) != nil {
		t.Fatal("valid anchored bootstrap rejected")
	}
	for _, kind := range []string{"wrong_node", "implicit_mode", "legacy", "peer_override"} {
		changed := boot
		switch kind {
		case "wrong_node":
			changed.NodeSeed = strings.Repeat("b", 64)
		case "implicit_mode":
			changed.ExpectedFresh = nil
		case "legacy":
			changed.Schema = "gg.consensus.bootstrap.v1"
		case "peer_override":
			changed.Peers = []Peer{{ID: strings.Repeat("a", 40), Port: 25001, Host: "127.0.0.1"}}
		}
		if validateBootstrap(changed) == nil {
			t.Fatal("unbound bootstrap accepted", kind)
		}
	}
	fresh = false
	if runNode(canonical(boot), 0) == nil {
		t.Fatal("missing history recreated during resume")
	}
	if _, err := os.Stat(boot.Root); !os.IsNotExist(err) {
		t.Fatal("failed resume mutated its target")
	}
}

func TestMembershipPythonAnchorCanonicalFixture(t *testing.T) {
	path := os.Getenv("GG_PUBLIC_LAN_ANCHOR_FIXTURE")
	if path == "" {
		t.Skip("runner must supply an actual signed Python LAN v4 anchor")
	}
	raw, err := os.ReadFile(path)
	var fixture struct {
		Genesis     Genesis `json:"genesis"`
		GenesisHash string  `json:"genesis_hash"`
	}
	if err != nil || decodeStrict(raw, &fixture) != nil || validateGenesis(fixture.Genesis, fixture.GenesisHash) != nil {
		t.Fatal("Python LAN anchor failed native validation")
	}
}
