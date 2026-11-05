//go:build !js

package main

import (
	"crypto/ed25519"
	"encoding/hex"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
)

const nativeObserverBootstrapSchema = "gg.native.observer-bootstrap.v1"
const nativeObserverRootFile = "gg-observer-identity.json"

type nativeObserverBootstrap struct {
	Resources     *nativeResources    `json:"resources,omitempty"`
	ExpectedFresh *bool               `json:"expected_fresh"`
	Genesis       Genesis             `json:"genesis"`
	GenesisHash   string              `json:"genesis_hash"`
	NodeSeed      string              `json:"node_seed"`
	ObserverGrant nativeObserverGrant `json:"observer_grant"`
	Root          string              `json:"root"`
	RPCPort       int                 `json:"rpc_port"`
	Schema        string              `json:"schema"`
}

type nativeObserverRootIdentity struct {
	Genesis       Genesis             `json:"genesis"`
	GenesisHash   string              `json:"genesis_hash"`
	NodeKey       string              `json:"node_key"`
	ObserverGrant nativeObserverGrant `json:"observer_grant"`
	Schema        string              `json:"schema"`
}

func validateNativeObserverBootstrap(boot nativeObserverBootstrap) error {
	if !validNativeResources(boot.Resources) || boot.Schema != nativeObserverBootstrapSchema || boot.ExpectedFresh == nil || validateGenesis(boot.Genesis, boot.GenesisHash) != nil ||
		validateNativeObserverGrant(boot.ObserverGrant, boot.Genesis, boot.GenesisHash) != nil || !pubPattern.MatchString(boot.NodeSeed) ||
		!filepath.IsAbs(boot.Root) || boot.RPCPort < 1024 || boot.RPCPort > 65535 || boot.RPCPort == boot.ObserverGrant.Body.P2PPort {
		return errNativeObserver
	}
	seed, _ := hex.DecodeString(boot.NodeSeed)
	public := ed25519.NewKeyFromSeed(seed).Public().(ed25519.PublicKey)
	if hex.EncodeToString(public) != boot.ObserverGrant.Body.NodeKey {
		return errNativeObserver
	}
	return nil
}

func decodeNativeBootstrap(raw []byte) (Bootstrap, error) {
	if len(raw) > 512*1024 {
		return Bootstrap{}, errors.New("GG_BOOTSTRAP_INVALID")
	}
	var schema struct {
		Schema string `json:"schema"`
	}
	if json.Unmarshal(raw, &schema) != nil {
		return Bootstrap{}, errors.New("GG_BOOTSTRAP_INVALID")
	}
	if schema.Schema == nativePublicBootstrapSchema {
		var public nativePublicBootstrap
		if decodeStrictLimited(raw, &public, 128, 64) != nil || validateNativePublicBootstrap(public) != nil {
			return Bootstrap{}, errors.New("GG_PUBLIC_BOOTSTRAP_INVALID")
		}
		return Bootstrap{Resources: public.Resources, Schema: public.Schema, Genesis: public.Genesis, GenesisHash: public.GenesisHash, NodeSeed: public.NodeSeed,
			ValidatorSeed: public.ValidatorSeed, ValidatorIndex: -1, Root: public.Root, RPCPort: public.RPCPort, P2PPort: public.P2PPort,
			Peers: public.Peers, ExpectedFresh: public.ExpectedFresh, public: &public}, nil
	}
	if len(raw) > 65536 {
		return Bootstrap{}, errors.New("GG_BOOTSTRAP_INVALID")
	}
	if schema.Schema == nativeObserverBootstrapSchema {
		var observer nativeObserverBootstrap
		// Unknown fields/duplicate names, including validator_seed/index, fail
		// before any root write. A role flag cannot disable validator checks.
		if decodeStrictLimited(raw, &observer, 128, 64) != nil || validateNativeObserverBootstrap(observer) != nil {
			return Bootstrap{}, errNativeObserver
		}
		return Bootstrap{Resources: observer.Resources, Schema: observer.Schema, Genesis: observer.Genesis, GenesisHash: observer.GenesisHash,
			NodeSeed: observer.NodeSeed, Root: observer.Root, RPCPort: observer.RPCPort, P2PPort: observer.ObserverGrant.Body.P2PPort,
			ExpectedFresh: observer.ExpectedFresh, ValidatorIndex: -1, observer: &observer}, nil
	}
	var boot Bootstrap
	if decodeStrict(raw, &boot) != nil || validateBootstrap(boot) != nil {
		return Bootstrap{}, errors.New("GG_BOOTSTRAP_INVALID")
	}
	return boot, nil
}

func nativeRootIdentity(boot Bootstrap) (string, []byte, error) {
	if boot.public != nil {
		return nativePublicIdentity(boot)
	}
	if _, err := os.Lstat(filepath.Join(boot.Root, nativePublicRootFile)); !os.IsNotExist(err) {
		return "", nil, errors.New("GG_NATIVE_ROOT_ROLE_CHANGED")
	}
	if boot.observer == nil {
		if _, err := os.Lstat(filepath.Join(boot.Root, nativeObserverRootFile)); !os.IsNotExist(err) {
			return "", nil, errors.New("GG_NATIVE_ROOT_ROLE_CHANGED")
		}
		return "gg-public-genesis.json", canonical(boot.Genesis), nil
	}
	// One atomic marker binds both immutable genesis and observer P2P identity.
	// This root can never be adopted as a validator root or open signer state.
	for _, forbidden := range []string{"gg-public-genesis.json", filepath.Join("data", "priv_validator_state.json"), filepath.Join("config", "priv_validator_key.json")} {
		if _, err := os.Lstat(filepath.Join(boot.Root, forbidden)); !os.IsNotExist(err) {
			return "", nil, errors.New("GG_NATIVE_OBSERVER_VALIDATOR_STATE_FORBIDDEN")
		}
	}
	for current := boot.Root; ; current = filepath.Dir(current) {
		if info, err := os.Lstat(current); err == nil {
			if !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
				return "", nil, errors.New("GG_NATIVE_OBSERVER_ROOT_PATH")
			}
		} else if !os.IsNotExist(err) {
			return "", nil, errors.New("GG_NATIVE_OBSERVER_ROOT_PATH")
		}
		if filepath.Dir(current) == current {
			break
		}
	}
	return nativeObserverRootFile, canonical(nativeObserverRootIdentity{Genesis: boot.Genesis, GenesisHash: boot.GenesisHash,
		NodeKey: boot.observer.ObserverGrant.Body.NodeKey, ObserverGrant: boot.observer.ObserverGrant, Schema: "gg.native.observer-root.v1"}), nil
}
