//go:build !js

package main

// Public, pure TESTNET genesis validation for the operator provisioning flow.
// This command accepts no node bootstrap, private seed, root path or listener.
// A computed initial root is never an SDK certificate or network activation.
import (
	"bytes"
	"errors"
	"io"
)

const protocolGenesisPinMaxBytes = 256 * 1024

var errProtocolGenesisInvalid = errors.New("GG_PROTOCOL_GENESIS_INVALID")

type nativeProtocolGenesisPin struct {
	Genesis     Genesis `json:"genesis"`
	GenesisHash string  `json:"genesis_hash"`
}

// Keep public JSON fields lexicographic, exactly matching Python canonical
// encoding. No scope field or imported assertion can expand this response.
type nativeProtocolGenesisValidation struct {
	CertificateAsserted bool   `json:"certificate_asserted"`
	ChainID             string `json:"chain_id"`
	Environment         string `json:"environment"`
	GenesisHash         string `json:"genesis_hash"`
	InitialStateRoot    string `json:"initial_state_root"`
	ProducerCount       int    `json:"producer_count"`
	Schema              string `json:"schema"`
	Verified            bool   `json:"verified"`
	VoterCount          int    `json:"voter_count"`
}

func validateProtocolGenesis(raw []byte) (result nativeProtocolGenesisValidation, failure error) {
	defer func() {
		if recover() != nil {
			result, failure = nativeProtocolGenesisValidation{}, errProtocolGenesisInvalid
		}
	}()
	var pin nativeProtocolGenesisPin
	if len(raw) == 0 || len(raw) > protocolGenesisPinMaxBytes || decodeStrictLimited(raw, &pin, 128, 64) != nil ||
		!bytes.Equal(raw, canonical(pin)) || pin.Genesis.Schema != "gg.native.genesis.v7" || !publicFinancialProtocol(pin.Genesis) ||
		pin.Genesis.Protocol.Environment != "TESTNET" || validateGenesis(pin.Genesis, pin.GenesisHash) != nil {
		return result, errProtocolGenesisInvalid
	}
	execution, err := newFinancialDagExecution(pin.Genesis, pin.GenesisHash, *pin.Genesis.FinancialDAG)
	if err != nil {
		return result, errProtocolGenesisInvalid
	}
	// This is the exact state initializer used by openFinancialStoreMode before
	// its first durable head is written, with no database or SDK process here.
	state := initialState(execution.genesis, pin.GenesisHash)
	if state.Height != 0 || validateState(state, execution.genesis, pin.GenesisHash) != nil {
		return result, errProtocolGenesisInvalid
	}
	return nativeProtocolGenesisValidation{CertificateAsserted: false, ChainID: execution.genesis.ChainID,
		Environment: "TESTNET", GenesisHash: pin.GenesisHash, InitialStateRoot: state.StateRoot,
		ProducerCount: len(execution.source.Producers), Schema: "gg.protocol.genesis-validation.v1", Verified: true,
		VoterCount: len(execution.genesis.Protocol.Committee.Members)}, nil
}

func writeProtocolGenesisInvalid(out io.Writer) error {
	// Every failure has this fixed bounded public response, including malformed
	// input and reader errors. Never serialize an underlying error or its data.
	_ = writeAll(out, []byte(`{"error":"GG_PROTOCOL_GENESIS_INVALID","verified":false}`))
	return errProtocolGenesisInvalid
}

func runProtocolGenesisValidation(in io.Reader, out io.Writer) error {
	raw, err := io.ReadAll(io.LimitReader(in, protocolGenesisPinMaxBytes+1))
	if err != nil || len(raw) > protocolGenesisPinMaxBytes {
		return writeProtocolGenesisInvalid(out)
	}
	result, err := validateProtocolGenesis(raw)
	if err != nil {
		return writeProtocolGenesisInvalid(out)
	}
	if writeAll(out, canonical(result)) != nil {
		return errProtocolGenesisInvalid
	}
	return nil
}
