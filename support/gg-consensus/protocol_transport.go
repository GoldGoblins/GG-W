//go:build !js

package main

// The proof relay uses the pinned SDK's authenticated encrypted connection.
// This transport grants no wallet, producer or consensus authority. Its parent
// supplies bounded application responses; clients still verify SDK certificates
// and independently selected records. Secret keys enter only through stdin.
import (
	"bufio"
	"bytes"
	"crypto/ed25519"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net"
	"strconv"
	"sync"
	"time"

	cmted "github.com/cometbft/cometbft/crypto/ed25519"
	cmtconn "github.com/cometbft/cometbft/p2p/conn"
)

const protocolTransportMaxFrame = 256*1024 + 4096

var errProtocolTransport = errors.New("GG_PROTOCOL_TRANSPORT_UNAVAILABLE")

type protocolTransportBootstrap struct {
	Resources *nativeResources `json:"resources,omitempty"`
	Allowed   []string         `json:"allowed_keys"`
	Expected  string           `json:"expected_key"`
	Genesis   string           `json:"genesis_hash"`
	Host      string           `json:"host"`
	Mode      string           `json:"mode"`
	Port      int              `json:"port"`
	Private   string           `json:"private_key"`
	Schema    string           `json:"schema"`
}

type protocolTransportFrame struct {
	Limits      *nativeTransportBudget `json:"limits,omitempty"`
	LocalLimits *nativeTransportBudget `json:"local_limits,omitempty"`
	Resources   map[string]any         `json:"resources,omitempty"`
	Error       string                 `json:"error,omitempty"`
	Event       string                 `json:"event"`
	Genesis     string                 `json:"genesis_hash,omitempty"`
	ID          uint64                 `json:"id,omitempty"`
	Payload     json.RawMessage        `json:"payload,omitempty"`
	Peer        string                 `json:"peer_key,omitempty"`
	Schema      string                 `json:"schema"`
}

func readProtocolTransportFrame(reader io.Reader) ([]byte, error) {
	var prefix [4]byte
	if _, err := io.ReadFull(reader, prefix[:]); err != nil {
		return nil, err
	}
	length := binary.BigEndian.Uint32(prefix[:])
	if length == 0 || length > protocolTransportMaxFrame {
		return nil, errProtocolTransport
	}
	raw := make([]byte, int(length))
	if _, err := io.ReadFull(reader, raw); err != nil {
		return nil, err
	}
	return raw, nil
}

func writeProtocolTransportFrame(writer io.Writer, value any) error {
	raw := canonical(value)
	if frame, ok := value.(protocolTransportFrame); ok && frame.Event == "READY" && frame.Resources != nil {
		// Only this public private-pipe attestation needs recursive map order.
		// All legacy READY and non-READY payload/signature bytes stay unchanged.
		raw = ownedRestoreCanonical(frame)
	}
	if len(raw) == 0 || len(raw) > protocolTransportMaxFrame {
		return errProtocolTransport
	}
	var prefix [4]byte
	binary.BigEndian.PutUint32(prefix[:], uint32(len(raw)))
	if err := writeAll(writer, prefix[:]); err != nil {
		return err
	}
	return writeAll(writer, raw)
}

func writeAll(writer io.Writer, raw []byte) error {
	for len(raw) > 0 {
		n, err := writer.Write(raw)
		if err != nil {
			return err
		}
		if n <= 0 {
			return io.ErrShortWrite
		}
		raw = raw[n:]
	}
	return nil
}

func decodeProtocolTransportFrame(raw []byte) (protocolTransportFrame, error) {
	var frame protocolTransportFrame
	if decodeStrictLimited(raw, &frame, 128, 64) != nil || frame.Schema != "gg.protocol.transport-frame.v1" ||
		frame.Limits != nil && (frame.Event != "HELLO" && frame.Event != "READY" || !validNativeTransportBudget(frame.Limits)) ||
		frame.Resources != nil && frame.Event != "READY" ||
		frame.LocalLimits != nil && (frame.Event != "READY" || !validNativeTransportBudget(frame.LocalLimits)) {
		return frame, errProtocolTransport
	}
	return frame, nil
}

type protocolTransportRate struct {
	mu          sync.Mutex
	at          time.Time
	tokens      float64
	rate, burst float64
}

func (limit *protocolTransportRate) take() bool {
	limit.mu.Lock()
	defer limit.mu.Unlock()
	now := time.Now()
	if limit.at.IsZero() {
		limit.at = now
		limit.tokens = limit.burst
	}
	limit.tokens += now.Sub(limit.at).Seconds() * limit.rate
	limit.at = now
	if limit.tokens > limit.burst {
		limit.tokens = limit.burst
	}
	if limit.tokens < 1 {
		return false
	}
	limit.tokens--
	return true
}

// Legacy helper keeps its exact HELLO shape. Updated SERVER clients offer
// bounded receive limits over the authenticated channel; absence means LOW.
func protocolTransportConnection(socket net.Conn, private cmted.PrivKey, expected, genesis string, server bool, allowed map[string]bool) (*cmtconn.SecretConnection, string, error) {
	connection, peer, _, err := protocolTransportConnectionUsing(socket, private, expected, genesis, server, allowed, nil)
	return connection, peer, err
}

func protocolTransportConnectionUsing(socket net.Conn, private cmted.PrivKey, expected, genesis string, server bool, allowed map[string]bool, local *nativeTransportBudget) (*cmtconn.SecretConnection, string, nativeTransportBudget, error) {
	remoteBudget := nativeTransportResources(nil)
	if local != nil && !validNativeTransportBudget(local) {
		return nil, "", remoteBudget, errProtocolTransport
	}
	if err := socket.SetDeadline(time.Now().Add(6 * time.Second)); err != nil {
		return nil, "", remoteBudget, errProtocolTransport
	}
	connection, err := cmtconn.MakeSecretConnection(socket, private)
	if err != nil {
		return nil, "", remoteBudget, errProtocolTransport
	}
	remote := connection.RemotePubKey()
	peer := hex.EncodeToString(remote.Bytes())
	if remote.Type() != "ed25519" || !financialAccountAddress(peer) || server && !allowed[peer] || !server && peer != expected {
		return nil, "", remoteBudget, errProtocolTransport
	}
	greeting := protocolTransportFrame{Event: "HELLO", Genesis: genesis, Schema: "gg.protocol.transport-frame.v1"}
	if !server {
		greeting.Limits = local
		if err = writeProtocolTransportFrame(connection, greeting); err != nil {
			return nil, "", remoteBudget, err
		}
	}
	raw, err := readProtocolTransportFrame(connection)
	if err != nil {
		return nil, "", remoteBudget, err
	}
	frame, err := decodeProtocolTransportFrame(raw)
	if err != nil || frame.Event != "HELLO" || frame.Genesis != genesis || frame.ID != 0 || frame.Payload != nil || frame.Peer != "" || frame.Error != "" || frame.Resources != nil {
		return nil, "", remoteBudget, errProtocolTransport
	}
	if frame.Limits != nil {
		remoteBudget = *frame.Limits
	}
	if server {
		// A legacy/LOW client keeps the former response shape. A capability
		// offer receives the server's own limits, never the client's claim.
		if frame.Limits != nil {
			budget := nativeTransportResources(nil)
			if local != nil {
				budget = *local
			}
			greeting.Limits = &budget
		}
		if err = writeProtocolTransportFrame(connection, greeting); err != nil {
			return nil, "", remoteBudget, err
		}
	}
	_ = socket.SetDeadline(time.Time{})
	return connection, peer, remoteBudget, nil
}

func protocolTransportPeerRates(resources *nativeResources, budget nativeTransportBudget, allowed map[string]bool) map[string]*protocolTransportRate {
	if resources == nil || resources.Mode != "SERVER" {
		return nil
	}
	// Construct once from the validated allowlist (at most64), never on a
	// socket reconnect. All sockets of one authenticated key share its mutex.
	peers := make(map[string]*protocolTransportRate, len(allowed))
	for key := range allowed {
		peers[key] = &protocolTransportRate{rate: float64(budget.RequestsPerConnectionSecond), burst: float64(budget.RequestsPerConnectionSecond)}
	}
	return peers
}

func runProtocolTransport(in io.Reader, out io.Writer) error {
	reader := bufio.NewReaderSize(in, 32768)
	raw, err := readProtocolTransportFrame(reader)
	if err != nil || len(raw) > 16384 {
		return errProtocolTransport
	}
	var boot protocolTransportBootstrap
	if decodeStrictLimited(raw, &boot, 64, 64) != nil || boot.Schema != "gg.protocol.transport-bootstrap.v1" || !pubPattern.MatchString(boot.Genesis) ||
		(boot.Mode != "CLIENT" && boot.Mode != "SERVER") || boot.Port < 1 || boot.Port > 65535 || len(boot.Allowed) > 64 {
		return errProtocolTransport
	}
	if err = bindNativeResources(boot.Resources); err != nil {
		return err
	}
	budget := nativeTransportResources(boot.Resources)
	attestation, err := nativeResourceReady(boot.Resources, nativeResourceCommitWait(boot.Resources))
	if err != nil {
		return err
	}
	ip := net.ParseIP(boot.Host)
	// This integration is explicitly limited to the approved local test network.
	if ip == nil || !(ip.IsPrivate() || ip.IsLoopback()) {
		return errProtocolTransport
	}
	secret, err := hex.DecodeString(boot.Private)
	if err != nil || len(secret) != 64 || !bytes.Equal(ed25519.NewKeyFromSeed(secret[:32]), secret) {
		return errProtocolTransport
	}
	private := cmted.PrivKey(secret)
	boot.Private = ""
	if !financialAccountAddress(hex.EncodeToString(private.PubKey().Bytes())) {
		return errProtocolTransport
	}
	allowed := map[string]bool{}
	for _, key := range boot.Allowed {
		if !financialAccountAddress(key) || allowed[key] {
			return errProtocolTransport
		}
		allowed[key] = true
	}
	peerRates := protocolTransportPeerRates(boot.Resources, budget, allowed)
	endpoint := net.JoinHostPort(boot.Host, strconv.Itoa(boot.Port))
	var output sync.Mutex
	emit := func(frame protocolTransportFrame) error {
		output.Lock()
		defer output.Unlock()
		return writeProtocolTransportFrame(out, frame)
	}
	if boot.Mode == "CLIENT" {
		if !financialAccountAddress(boot.Expected) || len(allowed) != 0 {
			return errProtocolTransport
		}
		socket, err := net.DialTimeout("tcp", endpoint, 6*time.Second)
		if err != nil {
			return errProtocolTransport
		}
		defer socket.Close()
		var offer *nativeTransportBudget
		if boot.Resources != nil && boot.Resources.Mode == "SERVER" {
			offer = &budget
		}
		connection, peer, peerBudget, err := protocolTransportConnectionUsing(socket, private, boot.Expected, boot.Genesis, false, nil, offer)
		if err != nil {
			return errProtocolTransport
		}
		ready := protocolTransportFrame{Event: "READY", Genesis: boot.Genesis, Peer: peer, Schema: "gg.protocol.transport-frame.v1"}
		if boot.Resources != nil {
			ready.Resources = attestation
			ready.Limits = &peerBudget
			ready.LocalLimits = &budget
		}
		if emit(ready) != nil {
			return errProtocolTransport
		}
		counter := uint64(0)
		for {
			raw, err := readProtocolTransportFrame(reader)
			if err == io.EOF {
				return nil
			}
			if err != nil {
				return errProtocolTransport
			}
			request, err := decodeProtocolTransportFrame(raw)
			if err != nil || counter == ^uint64(0) || request.ID != counter+1 || request.Event != "REQUEST" || request.Genesis != boot.Genesis || request.Peer != "" || request.Error != "" || len(request.Payload) == 0 || len(request.Payload) > 65536 {
				return errProtocolTransport
			}
			counter = request.ID
			_ = socket.SetDeadline(time.Now().Add(30 * time.Second))
			if writeProtocolTransportFrame(connection, request) != nil {
				return errProtocolTransport
			}
			raw, err = readProtocolTransportFrame(connection)
			if err != nil {
				return errProtocolTransport
			}
			reply, err := decodeProtocolTransportFrame(raw)
			if err != nil || reply.Event != "RESPONSE" || reply.ID != counter || reply.Genesis != boot.Genesis || reply.Peer != "" {
				return errProtocolTransport
			}
			if emit(reply) != nil {
				return errProtocolTransport
			}
		}
	}
	if len(allowed) == 0 || boot.Expected != "" {
		return errProtocolTransport
	}
	listener, err := net.Listen("tcp", endpoint)
	if err != nil {
		return errProtocolTransport
	}
	defer listener.Close()
	var mu sync.Mutex
	connections := map[net.Conn]bool{}
	pending := map[uint64]chan protocolTransportFrame{}
	var next uint64
	stop := make(chan struct{})
	go func() {
		defer close(stop)
		defer listener.Close()
		defer func() {
			mu.Lock()
			defer mu.Unlock()
			for socket := range connections {
				_ = socket.Close()
			}
		}()
		for {
			raw, err := readProtocolTransportFrame(reader)
			if err != nil {
				return
			}
			frame, err := decodeProtocolTransportFrame(raw)
			if err != nil || frame.Event != "RESPONSE" || frame.Genesis != boot.Genesis || frame.Peer != "" {
				return
			}
			mu.Lock()
			reply := pending[frame.ID]
			mu.Unlock()
			if reply != nil {
				select {
				case reply <- frame:
				default:
				}
			}
		}
	}()
	ready := protocolTransportFrame{Event: "READY", Genesis: boot.Genesis, Peer: hex.EncodeToString(private.PubKey().Bytes()), Schema: "gg.protocol.transport-frame.v1"}
	if boot.Resources != nil {
		ready.Resources = attestation
		ready.Limits = &budget
		ready.LocalLimits = &budget
	}
	if emit(ready) != nil {
		return errProtocolTransport
	}
	global := protocolTransportRate{rate: float64(budget.RequestsPerSecond), burst: float64(budget.RequestsPerSecond)}
	for {
		socket, err := listener.Accept()
		if err != nil {
			select {
			case <-stop:
				return nil
			default:
				return errProtocolTransport
			}
		}
		mu.Lock()
		if len(connections) >= budget.Connections {
			mu.Unlock()
			_ = socket.Close()
			continue
		}
		connections[socket] = true
		mu.Unlock()
		go func(socket net.Conn) {
			defer socket.Close()
			defer func() { mu.Lock(); delete(connections, socket); mu.Unlock() }()
			connection, peer, _, err := protocolTransportConnectionUsing(socket, private, "", boot.Genesis, true, allowed, &budget)
			if err != nil {
				return
			}
			shared := peerRates[peer]
			if boot.Resources != nil && boot.Resources.Mode == "SERVER" && shared == nil {
				return
			}
			counter := uint64(0)
			limit := protocolTransportRate{rate: float64(budget.RequestsPerConnectionSecond), burst: float64(budget.RequestsPerConnectionSecond)}
			for {
				_ = socket.SetDeadline(time.Now().Add(30 * time.Second))
				raw, err := readProtocolTransportFrame(connection)
				if err != nil {
					return
				}
				frame, err := decodeProtocolTransportFrame(raw)
				if err != nil || counter == ^uint64(0) || frame.Event != "REQUEST" || frame.ID != counter+1 || frame.Genesis != boot.Genesis || frame.Peer != "" || frame.Error != "" || len(frame.Payload) == 0 || len(frame.Payload) > 65536 {
					return
				}
				counter = frame.ID
				response := protocolTransportFrame{Event: "RESPONSE", Genesis: boot.Genesis, ID: counter, Error: "GG_PROTOCOL_RELAY_LIMIT", Schema: "gg.protocol.transport-frame.v1"}
				admitted := false
				if shared == nil {
					admitted = global.take() && limit.take()
				} else {
					admitted = shared.take() && limit.take() && global.take()
				}
				if admitted {
					mu.Lock()
					if next == ^uint64(0) {
						mu.Unlock()
						return
					}
					next++
					id := next
					reply := make(chan protocolTransportFrame, 1)
					pending[id] = reply
					mu.Unlock()
					request := protocolTransportFrame{Event: "REQUEST", Genesis: boot.Genesis, ID: id, Payload: frame.Payload, Peer: peer, Schema: "gg.protocol.transport-frame.v1"}
					if emit(request) != nil {
						mu.Lock()
						delete(pending, id)
						mu.Unlock()
						return
					}
					timer := time.NewTimer(20 * time.Second)
					select {
					case response = <-reply:
						response.ID = counter
					case <-timer.C:
						response.Error = "GG_PROTOCOL_RELAY_TIMEOUT"
					case <-stop:
						timer.Stop()
						return
					}
					timer.Stop()
					mu.Lock()
					delete(pending, id)
					mu.Unlock()
				}
				if writeProtocolTransportFrame(connection, response) != nil {
					return
				}
			}
		}(socket)
	}
}
