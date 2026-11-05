//go:build !js

package main

// Explicit protocol-v7 startup. Legacy laboratory bootstraps keep their fixed
// roster. Public peers authenticate transport keys; a connection grants no
// producer identity, monetary authority or validator voting power.
import (
	"crypto/ed25519"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
)

const nativePublicBootstrapSchema = "gg.native.protocol-bootstrap.v1"
const nativePublicRootFile = "gg-protocol-node.json"

type nativePublicMembershipContext struct {
	CommitteeTransitions []financialCommitteeTransition `json:"committee_transitions,omitempty"`
	SignedHeader         json.RawMessage                `json:"signed_header"`
	State                State                          `json:"state"`
}

type nativePublicBootstrap struct {
	Resources     *nativeResources               `json:"resources,omitempty"`
	ExpectedFresh *bool                          `json:"expected_fresh"`
	Genesis       Genesis                        `json:"genesis"`
	GenesisHash   string                         `json:"genesis_hash"`
	ListenHost    string                         `json:"listen_host"`
	MaxInbound    int                            `json:"max_inbound"`
	MaxOutbound   int                            `json:"max_outbound"`
	Membership    *nativePublicMembershipContext `json:"membership_context,omitempty"`
	NodeSeed      string                         `json:"node_seed"`
	P2PPort       int                            `json:"p2p_port"`
	Peers         []Peer                         `json:"peers"`
	Role          string                         `json:"role"`
	Root          string                         `json:"root"`
	RPCPort       int                            `json:"rpc_port"`
	Schema        string                         `json:"schema"`
	ValidatorSeed string                         `json:"validator_seed,omitempty"`
}

func publicLiteralIP(value string, listen bool) bool {
	ip := net.ParseIP(value)
	return ip != nil && ip.String() == value && (ip.IsGlobalUnicast() || ip.IsLoopback() || listen && ip.IsUnspecified())
}

func validateNativePublicBootstrap(value nativePublicBootstrap) error {
	if !validNativeResources(value.Resources) || value.Schema != nativePublicBootstrapSchema || value.ExpectedFresh == nil || !publicFinancialProtocol(value.Genesis) || validateGenesis(value.Genesis, value.GenesisHash) != nil ||
		!filepath.IsAbs(value.Root) || !pubPattern.MatchString(value.NodeSeed) || !publicLiteralIP(value.ListenHost, true) ||
		value.MaxInbound < 0 || value.MaxInbound > 64 || value.MaxOutbound < 1 || value.MaxOutbound > 16 || value.Peers == nil || len(value.Peers) < 1 || len(value.Peers) > value.MaxOutbound ||
		value.P2PPort < 1024 || value.P2PPort > 65535 || value.RPCPort < 1024 || value.RPCPort > 65535 || value.P2PPort == value.RPCPort ||
		(value.Role != "VALIDATOR" && value.Role != "REPLICA") {
		return errors.New("GG_PUBLIC_BOOTSTRAP_INVALID")
	}
	seed, _ := hex.DecodeString(value.NodeSeed)
	nodeKey := hex.EncodeToString(ed25519.NewKeyFromSeed(seed)[32:])
	ids, endpoints := map[string]bool{}, map[string]bool{}
	idPattern := regexp.MustCompile(`^[0-9a-f]{40}$`)
	for _, peer := range value.Peers {
		endpoint := net.JoinHostPort(peer.Host, strconv.Itoa(peer.Port))
		if !publicLiteralIP(peer.Host, false) || peer.Port < 1024 || peer.Port > 65535 || !idPattern.MatchString(peer.ID) ||
			peer.ID == membershipNodeID(nodeKey) || ids[peer.ID] || endpoints[endpoint] {
			return errors.New("GG_PUBLIC_BOOTSTRAP_PEERS")
		}
		ids[peer.ID], endpoints[endpoint] = true, true
	}
	committee := value.Genesis.Protocol.Committee
	if value.Membership != nil {
		packet := VerifyInput{Schema: "gg.consensus.proof.v1", Genesis: value.Genesis, GenesisHash: value.GenesisHash, State: value.Membership.State,
			SignedHeader: value.Membership.SignedHeader, CommitteeTransitions: value.Membership.CommitteeTransitions}
		if _, err := verifyInput(packet); err != nil {
			return errors.New("GG_PUBLIC_MEMBERSHIP_CERTIFICATE")
		}
		committee = value.Membership.State.Protocol.Committee
		if pending := value.Membership.State.Protocol.PendingCommittee; pending != nil {
			committee = pending.Next
		}
	}
	if value.Role == "VALIDATOR" {
		if !pubPattern.MatchString(value.ValidatorSeed) {
			return errors.New("GG_PUBLIC_VALIDATOR_BINDING")
		}
		seed, _ := hex.DecodeString(value.ValidatorSeed)
		validator := hex.EncodeToString(ed25519.NewKeyFromSeed(seed)[32:])
		found := false
		for _, member := range committee.Members {
			if member.ValidatorKey == validator && member.NodeKey == nodeKey {
				found = true
			}
		}
		if !found {
			return errors.New("GG_PUBLIC_VALIDATOR_BINDING")
		}
	} else if value.ValidatorSeed != "" {
		return errors.New("GG_PUBLIC_REPLICA_SIGNER_FORBIDDEN")
	}
	for _, member := range committee.Members {
		if nodeKey == member.AccountKey || nodeKey == member.OwnerPeerKey || nodeKey == member.ValidatorKey || value.Role == "REPLICA" && nodeKey == member.NodeKey {
			return errors.New("GG_PUBLIC_NODE_ROLE_COLLISION")
		}
	}
	for _, invite := range value.Genesis.Protocol.InitialProducers {
		body := invite.Body
		if nodeKey == body.ProducerKey || nodeKey == body.OwnerPeerKey || nodeKey == body.RewardAccount {
			return errors.New("GG_PUBLIC_NODE_ROLE_COLLISION")
		}
	}
	for _, allocation := range value.Genesis.FinancialAccounts.Allocations {
		if nodeKey == allocation.Address {
			return errors.New("GG_PUBLIC_NODE_ROLE_COLLISION")
		}
	}
	return nil
}

func nativePublicIdentity(boot Bootstrap) (string, []byte, error) {
	if boot.public == nil {
		return "", nil, errors.New("GG_PUBLIC_ROOT_IDENTITY")
	}
	for current := boot.Root; ; current = filepath.Dir(current) {
		if info, err := os.Lstat(current); err == nil {
			if !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
				return "", nil, errors.New("GG_PUBLIC_ROOT_PATH")
			}
		} else if !os.IsNotExist(err) {
			return "", nil, errors.New("GG_PUBLIC_ROOT_PATH")
		}
		if filepath.Dir(current) == current {
			break
		}
	}
	for _, forbidden := range []string{"gg-public-genesis.json", nativeObserverRootFile} {
		if _, err := os.Lstat(filepath.Join(boot.Root, forbidden)); !os.IsNotExist(err) {
			return "", nil, errors.New("GG_NATIVE_ROOT_ROLE_CHANGED")
		}
	}
	if boot.public.Role == "REPLICA" {
		for _, forbidden := range []string{filepath.Join("data", "priv_validator_state.json"), filepath.Join("config", "priv_validator_key.json")} {
			if _, err := os.Lstat(filepath.Join(boot.Root, forbidden)); !os.IsNotExist(err) {
				return "", nil, errors.New("GG_PUBLIC_REPLICA_SIGNER_FORBIDDEN")
			}
		}
	}
	seed, _ := hex.DecodeString(boot.NodeSeed)
	nodeKey := hex.EncodeToString(ed25519.NewKeyFromSeed(seed)[32:])
	validator := ""
	if boot.public.Role == "VALIDATOR" {
		seed, _ = hex.DecodeString(boot.ValidatorSeed)
		validator = hex.EncodeToString(ed25519.NewKeyFromSeed(seed)[32:])
	}
	identity := struct {
		Genesis      Genesis `json:"genesis"`
		GenesisHash  string  `json:"genesis_hash"`
		NodeKey      string  `json:"node_key"`
		Role         string  `json:"role"`
		Schema       string  `json:"schema"`
		ValidatorKey string  `json:"validator_key,omitempty"`
	}{boot.Genesis, boot.GenesisHash, nodeKey, boot.public.Role, "gg.native.protocol-root.v1", validator}
	return nativePublicRootFile, canonical(identity), nil
}
