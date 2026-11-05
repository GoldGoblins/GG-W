//go:build !js

package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"testing"
)

func publicProtocolGenesisPinFixture(t *testing.T) nativeProtocolGenesisPin {
	t.Helper()
	execution, _, _ := publicProtocolFixture(t)
	var pin nativeProtocolGenesisPin
	if decodeStrict(canonical(nativeProtocolGenesisPin{Genesis: execution.genesis, GenesisHash: execution.anchor}), &pin) != nil {
		t.Fatal("public pin fixture encoding")
	}
	return pin
}

func TestPublicProtocolGenesisValidationMatchesExactNativeInitialState(t *testing.T) {
	pin := publicProtocolGenesisPinFixture(t)
	result, err := validateProtocolGenesis(canonical(pin))
	if err != nil || !result.Verified || result.CertificateAsserted || result.Schema != "gg.protocol.genesis-validation.v1" || result.Environment != "TESTNET" ||
		result.GenesisHash != pin.GenesisHash || result.ChainID != pin.Genesis.ChainID || result.VoterCount != len(pin.Genesis.Validators) ||
		result.ProducerCount != len(pin.Genesis.FinancialDAG.Producers) {
		t.Fatal("public-only genesis result disagrees with actual input", err)
	}
	state := initialState(pin.Genesis, pin.GenesisHash)
	if state.Height != 0 || state.FinancialDAG == nil || state.FinancialDAG.Blocks != 0 || state.FinancialDAG.Applied != 0 || state.Protocol == nil ||
		result.InitialStateRoot != state.StateRoot || result.InitialStateRoot == DagZero || result.InitialStateRoot == pin.GenesisHash {
		t.Fatal("validation supplied a placeholder root or execution/certificate claim")
	}
	if validateState(state, pin.Genesis, pin.GenesisHash) != nil {
		t.Fatal("native initialization root is invalid")
	}
	assertPublicCanonicalJSON(t, result)
	var fields map[string]json.RawMessage
	if decodeStrict(canonical(result), &fields) != nil || len(fields) != 9 {
		t.Fatal("public result is not the exact nine-field contract")
	}
	for _, name := range []string{"certificate_asserted", "chain_id", "environment", "genesis_hash", "initial_state_root", "producer_count", "schema", "verified", "voter_count"} {
		if fields[name] == nil {
			t.Fatal("missing required public result field", name)
		}
	}
}

func TestPublicProtocolGenesisValidationCanonicalInputAndBoundedPublicOutput(t *testing.T) {
	pin := publicProtocolGenesisPinFixture(t)
	raw := canonical(pin)
	var output bytes.Buffer
	if err := runProtocolGenesisValidation(bytes.NewReader(raw), &output); err != nil {
		t.Fatal(err)
	}
	var response nativeProtocolGenesisValidation
	if output.Len() > 1024 || decodeStrict(output.Bytes(), &response) != nil || !response.Verified || !bytes.Equal(output.Bytes(), canonical(response)) {
		t.Fatal("public command output is oversized, noncanonical or invalid")
	}
	for _, changed := range [][]byte{append([]byte(" "), raw...), append(append([]byte(nil), raw...), '\n'),
		[]byte(`{"genesis_hash":"` + pin.GenesisHash + `","genesis":` + string(canonical(pin.Genesis)) + `}`),
		[]byte(`{"genesis":` + string(canonical(pin.Genesis)) + `,"genesis_hash":"` + pin.GenesisHash + `","genesis_hash":"` + pin.GenesisHash + `"}`)} {
		output.Reset()
		if runProtocolGenesisValidation(bytes.NewReader(changed), &output) == nil || output.String() != `{"error":"GG_PROTOCOL_GENESIS_INVALID","verified":false}` {
			t.Fatal("noncanonical/ambiguous pin escaped strict two-field input")
		}
	}
}

func TestPublicProtocolGenesisValidationRejectsLegacyMissingAndSecretBootstrapFields(t *testing.T) {
	pin := publicProtocolGenesisPinFixture(t)
	legacy, anchor, _, _ := testGenesis()
	root := filepath.Join(t.TempDir(), "native-must-not-be-created")
	inputs := [][]byte{nil, []byte("{"), []byte("null"), []byte("[]"), []byte(`{"verified":true}`),
		canonical(nativeProtocolGenesisPin{Genesis: legacy, GenesisHash: anchor}),
		canonical(map[string]any{"genesis": pin.Genesis}), canonical(map[string]any{"genesis_hash": pin.GenesisHash}),
		canonical(map[string]any{"genesis": pin.Genesis, "genesis_hash": pin.GenesisHash, "root": root,
			"node_seed": "PUBLIC-INPUT-SENTINEL-NEVER-ECHO", "validator_seed": "PUBLIC-INPUT-SENTINEL-NEVER-ECHO"})}
	for _, raw := range inputs {
		var output bytes.Buffer
		err := runProtocolGenesisValidation(bytes.NewReader(raw), &output)
		if err != errProtocolGenesisInvalid || output.String() != `{"error":"GG_PROTOCOL_GENESIS_INVALID","verified":false}` ||
			bytes.Contains(output.Bytes(), []byte("SENTINEL")) || output.Len() > 256 {
			t.Fatal("invalid/private bootstrap data escaped bounded public failure")
		}
	}
	if _, err := os.Stat(root); !os.IsNotExist(err) {
		t.Fatal("public validation touched a native node root", err)
	}
}

func TestPublicProtocolGenesisValidationRejectsIntrinsicallyValidMainnet(t *testing.T) {
	pin := publicProtocolGenesisPinFixture(t)
	pin.Genesis.Protocol.Environment, pin.Genesis.Symbol = "MAINNET", "GG"
	pin.GenesisHash = hashHex(canonical(pin.Genesis))
	if validateGenesis(pin.Genesis, pin.GenesisHash) != nil {
		t.Fatal("mainnet negative fixture must satisfy existing native schema rules")
	}
	if _, err := validateProtocolGenesis(canonical(pin)); err != errProtocolGenesisInvalid {
		t.Fatal("read-only TESTNET operator command accepted mainnet policy")
	}
}

func TestPublicProtocolGenesisValidationChecksPossessionPolicyAndExactAnchor(t *testing.T) {
	for _, change := range []string{"hash", "mutated-policy", "owner-signature", "validator-power", "supply", "source-producer"} {
		t.Run(change, func(t *testing.T) {
			pin := publicProtocolGenesisPinFixture(t)
			switch change {
			case "hash":
				pin.GenesisHash = strings.Repeat("0", 64)
			case "mutated-policy":
				pin.Genesis.Protocol.MaxWorkHeights++
			case "owner-signature":
				pin.Genesis.Protocol.InitialProducers[0].OwnerSignature = strings.Repeat("0", 128)
			case "validator-power":
				pin.Genesis.Protocol.Committee.Members[0].Power = "0"
			case "supply":
				pin.Genesis.SupplyAtomic = "7"
			case "source-producer":
				pin.Genesis.FinancialDAG.Producers[0] = publicFixtureAddress(publicFixtureKey("unregistered-oracle-producer"))
			}
			if change != "hash" && change != "mutated-policy" {
				// A new hash cannot launder invalid PoP, money or committee policy.
				pin.GenesisHash = hashHex(canonical(pin.Genesis))
			}
			if _, err := validateProtocolGenesis(canonical(pin)); err != errProtocolGenesisInvalid {
				t.Fatal("forged public genesis accepted")
			}
		})
	}
}

type protocolGenesisUnendingReader struct{ read int }

func (reader *protocolGenesisUnendingReader) Read(raw []byte) (int, error) {
	for index := range raw {
		raw[index] = ' '
	}
	reader.read += len(raw)
	return len(raw), nil
}

type protocolGenesisFailedReader struct{}

func (protocolGenesisFailedReader) Read([]byte) (int, error) {
	return 0, errors.New("PUBLIC-READER-SENTINEL-NEVER-ECHO")
}

type protocolGenesisFailedWriter struct{}

func (protocolGenesisFailedWriter) Write([]byte) (int, error) {
	return 0, errors.New("PUBLIC-WRITER-SENTINEL-NEVER-ECHO")
}

func TestPublicProtocolGenesisValidationBoundsReadAndHidesIOErrors(t *testing.T) {
	endless := &protocolGenesisUnendingReader{}
	var output bytes.Buffer
	if runProtocolGenesisValidation(endless, &output) != errProtocolGenesisInvalid || endless.read != protocolGenesisPinMaxBytes+1 {
		t.Fatal("public pin reader exceeded the fixed256KiB plus one-byte bound")
	}
	if output.String() != `{"error":"GG_PROTOCOL_GENESIS_INVALID","verified":false}` {
		t.Fatal("oversize input exposed a non-generic error")
	}
	output.Reset()
	if runProtocolGenesisValidation(protocolGenesisFailedReader{}, &output) != errProtocolGenesisInvalid || bytes.Contains(output.Bytes(), []byte("SENTINEL")) {
		t.Fatal("reader failure leaked its cause")
	}
	if err := runProtocolGenesisValidation(bytes.NewReader(canonical(publicProtocolGenesisPinFixture(t))), protocolGenesisFailedWriter{}); err != errProtocolGenesisInvalid {
		t.Fatal("writer failure leaked its cause or succeeded", err)
	}
	if err := writeAll(protocolZeroWriter{}, []byte("x")); !errors.Is(err, io.ErrShortWrite) {
		t.Fatal("short-write failure lost its ordinary IO guard")
	}
}

func TestPublicProtocolGenesisValidationUsesActualCountsAndAccountInitialization(t *testing.T) {
	pin := publicProtocolGenesisPinFixture(t)
	first, err := validateProtocolGenesis(canonical(pin))
	if err != nil {
		t.Fatal(err)
	}
	member := publicConsensusMember{AccountKey: publicFixtureAddress(publicFixtureKey("oracle-extra-account")),
		NodeKey: publicFixtureAddress(publicFixtureKey("oracle-extra-node")), OwnerPeerKey: publicFixtureAddress(publicFixtureKey("oracle-extra-owner")),
		Power: "2", ValidatorKey: publicFixtureAddress(publicFixtureKey("oracle-extra-validator"))}
	pin.Genesis.Protocol.Committee.Members = append(pin.Genesis.Protocol.Committee.Members, member)
	sort.Slice(pin.Genesis.Protocol.Committee.Members, func(i, j int) bool {
		return pin.Genesis.Protocol.Committee.Members[i].ValidatorKey < pin.Genesis.Protocol.Committee.Members[j].ValidatorKey
	})
	pin.Genesis.Validators = []string{}
	for _, value := range pin.Genesis.Protocol.Committee.Members {
		pin.Genesis.Validators = append(pin.Genesis.Validators, value.ValidatorKey)
	}
	pin.Genesis.FinancialAccounts.Allocations[0].Address = member.AccountKey
	pin.GenesisHash = hashHex(canonical(pin.Genesis))
	second, err := validateProtocolGenesis(canonical(pin))
	if err != nil || second.VoterCount != 5 || second.ProducerCount != first.ProducerCount || second.InitialStateRoot == first.InitialStateRoot ||
		second.InitialStateRoot != initialState(pin.Genesis, pin.GenesisHash).StateRoot || second.CertificateAsserted {
		t.Fatal("public response hardcoded a roster or ignored real account initialization", err)
	}
}
