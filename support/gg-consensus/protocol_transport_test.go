//go:build !js

package main

// The channel identities in this suite are reproducible public test data.
// net.Pipe exercises the real pinned SDK encryption/identity handshake without
// opening a network listener or executing a node.
import (
	"bytes"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net"
	"strings"
	"testing"
	"time"

	cmted "github.com/cometbft/cometbft/crypto/ed25519"
	cmtconn "github.com/cometbft/cometbft/p2p/conn"
)

func publicTransportKey(name string) cmted.PrivKey {
	seed := sha256.Sum256([]byte("PUBLIC protocol transport fixture " + name))
	return cmted.PrivKey(ed25519.NewKeyFromSeed(seed[:]))
}

func transportWire(raw []byte) []byte {
	var prefix [4]byte
	binary.BigEndian.PutUint32(prefix[:], uint32(len(raw)))
	return append(prefix[:], raw...)
}

type protocolShortWriter struct{ bytes.Buffer }

func (writer *protocolShortWriter) Write(raw []byte) (int, error) {
	if len(raw) > 3 {
		raw = raw[:3]
	}
	return writer.Buffer.Write(raw)
}

type protocolZeroWriter struct{}

func (protocolZeroWriter) Write([]byte) (int, error) { return 0, nil }

func TestProtocolTransportFramingBoundsTruncationAndShortWrites(t *testing.T) {
	for name, raw := range map[string][]byte{
		"empty-prefix": {}, "partial-prefix": {0, 0, 0}, "zero": {0, 0, 0, 0},
		"truncated": append([]byte{0, 0, 0, 2}, 'x'),
		"oversize":  {0x7f, 0xff, 0xff, 0xff},
	} {
		t.Run(name, func(t *testing.T) {
			if _, err := readProtocolTransportFrame(bytes.NewReader(raw)); err == nil {
				t.Fatal("malformed framing accepted")
			}
		})
	}
	wanted := protocolTransportFrame{Schema: "gg.protocol.transport-frame.v1", Event: "REQUEST", Genesis: strings.Repeat("a", 64), ID: 1, Payload: json.RawMessage(`{"method":"state"}`)}
	var output protocolShortWriter
	if err := writeProtocolTransportFrame(&output, wanted); err != nil {
		t.Fatal("partial underlying writes lost data", err)
	}
	raw, err := readProtocolTransportFrame(&output)
	if err != nil || !bytes.Equal(raw, canonical(wanted)) {
		t.Fatal("framing changed the request", err)
	}
	if err := writeAll(protocolZeroWriter{}, []byte("x")); !errors.Is(err, io.ErrShortWrite) {
		t.Fatal("zero-byte writer did not fail closed", err)
	}
	for _, raw := range [][]byte{
		[]byte(`{"event":"REQUEST","schema":"gg.protocol.transport-frame.v1","extra":true}`),
		[]byte(`{"event":"REQUEST","event":"RESPONSE","schema":"gg.protocol.transport-frame.v1"}`),
		[]byte(`{"event":"REQUEST","schema":"gg.protocol.transport-frame.v0"}`),
	} {
		if _, err := decodeProtocolTransportFrame(raw); err == nil {
			t.Fatal("ambiguous or unversioned frame accepted")
		}
	}
}

func TestProtocolTransportRealEncryptedPeerAndChainBinding(t *testing.T) {
	serverKey, clientKey := publicTransportKey("server"), publicTransportKey("client")
	serverPublic, clientPublic := hex.EncodeToString(serverKey.PubKey().Bytes()), hex.EncodeToString(clientKey.PubKey().Bytes())
	anchor := strings.Repeat("b", 64)
	type result struct {
		connection *cmtconn.SecretConnection
		peer       string
		err        error
	}
	for _, scenario := range []string{"accepted", "wrong-server", "unapproved-client", "foreign-genesis"} {
		t.Run(scenario, func(t *testing.T) {
			serverSocket, clientSocket := net.Pipe()
			defer serverSocket.Close()
			defer clientSocket.Close()
			allowed := map[string]bool{clientPublic: true}
			expected, clientGenesis := serverPublic, anchor
			if scenario == "wrong-server" {
				expected = hex.EncodeToString(publicTransportKey("stranger").PubKey().Bytes())
			}
			if scenario == "unapproved-client" {
				allowed = map[string]bool{}
			}
			if scenario == "foreign-genesis" {
				clientGenesis = strings.Repeat("c", 64)
			}
			serverResults, clientResults := make(chan result, 1), make(chan result, 1)
			go func() {
				connection, peer, err := protocolTransportConnection(serverSocket, serverKey, "", anchor, true, allowed)
				serverResults <- result{connection, peer, err}
				if err != nil {
					_ = serverSocket.Close()
				}
			}()
			go func() {
				connection, peer, err := protocolTransportConnection(clientSocket, clientKey, expected, clientGenesis, false, nil)
				clientResults <- result{connection, peer, err}
				if err != nil {
					_ = clientSocket.Close()
				}
			}()
			await := func(channel <-chan result) result {
				select {
				case value := <-channel:
					return value
				case <-time.After(8 * time.Second):
					t.Fatal("bounded cryptographic handshake did not return")
					return result{}
				}
			}
			server, client := await(serverResults), await(clientResults)
			if scenario != "accepted" {
				if server.err == nil || client.err == nil {
					t.Fatal("wrong peer or chain authenticated", server.err, client.err)
				}
				return
			}
			if server.err != nil || client.err != nil || server.peer != clientPublic || client.peer != serverPublic {
				t.Fatal("actual SDK authenticated channel failed", server.err, client.err)
			}
			// Same maximum identity chunk as Python's IPC fixture. The SDK
			// carries opaque JSON; it neither decodes nor trusts the codec.
			original := bytes.Repeat([]byte("x"), 32*1024)
			digest := sha256.Sum256(original)
			id := hex.EncodeToString(digest[:])
			chunk := map[string]any{"schema": "gg.lossless-chunk-codec.v1", "codec": "identity", "hash": id,
				"total": len(original), "wire_sha256": id, "index": 0, "offset": 0, "raw_size": len(original),
				"raw_sha256": id, "data": base64.StdEncoding.EncodeToString(original)}
			codecPayload := canonical(map[string]any{"method": "account_chunk_codec", "document_hash": id, "chunk": chunk})
			if len(codecPayload) > 65536 {
				t.Fatal("opaque codec exceeded native request limit")
			}
			for index, payload := range []json.RawMessage{json.RawMessage(`{"method":"state"}`), codecPayload} {
				request := protocolTransportFrame{Schema: "gg.protocol.transport-frame.v1", Event: "REQUEST", Genesis: anchor, ID: uint64(index + 1), Payload: payload}
				written := make(chan error, 1)
				go func() { written <- writeProtocolTransportFrame(client.connection, request) }()
				raw, err := readProtocolTransportFrame(server.connection)
				if err != nil || !bytes.Equal(raw, canonical(request)) {
					t.Fatal("encrypted channel changed framed payload", err)
				}
				if err := <-written; err != nil {
					t.Fatal(err)
				}
			}
		})
	}
}

func TestProtocolTransportRejectsBootstrapBeforeNetworkEffects(t *testing.T) {
	private := publicTransportKey("bootstrap")
	base := protocolTransportBootstrap{Allowed: []string{}, Expected: hex.EncodeToString(publicTransportKey("remote").PubKey().Bytes()), Genesis: strings.Repeat("d", 64), Host: "127.0.0.1", Mode: "CLIENT", Port: 12345, Private: hex.EncodeToString(private), Schema: "gg.protocol.transport-bootstrap.v1"}
	for _, change := range []func(*protocolTransportBootstrap){
		func(b *protocolTransportBootstrap) { b.Host = "8.8.8.8" },
		func(b *protocolTransportBootstrap) { b.Host = "localhost" },
		func(b *protocolTransportBootstrap) { b.Host = "0.0.0.0" },
		func(b *protocolTransportBootstrap) { b.Private = b.Private[:64] + strings.Repeat("0", 64) },
		func(b *protocolTransportBootstrap) { b.Allowed = []string{b.Expected} },
		func(b *protocolTransportBootstrap) { b.Expected = strings.Repeat("0", 64) },
		func(b *protocolTransportBootstrap) { b.Genesis = "unbound" },
		func(b *protocolTransportBootstrap) { b.Mode = "UNKNOWN" },
	} {
		bootstrap := base
		change(&bootstrap)
		var output bytes.Buffer
		if err := runProtocolTransport(bytes.NewReader(transportWire(canonical(bootstrap))), &output); err == nil || output.Len() != 0 {
			t.Fatal("invalid private bootstrap attempted a ready channel", err)
		}
	}
}
