//go:build !js

package main

// A native full observer has only a protected P2P key. Its PrivValidator
// adapter contains PUBLIC bytes and cannot sign. Signed read-only peer grants
// do not add validators, voting power, account allocations or DAG ownership.
import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/hex"
	"errors"
	"io"
	"net"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"unicode/utf8"

	cmtcrypto "github.com/cometbft/cometbft/crypto"
	cmted "github.com/cometbft/cometbft/crypto/ed25519"
	cmtproto "github.com/cometbft/cometbft/proto/tendermint/types"
)

const nativeObserverGrantSchema = "gg.native.observer-grant.v1"
const nativeObserverAdmissionSchema = "gg.native.observer-admissions.v1"
const nativeObserverAdmissionFile = "gg-observer-admissions.json"
const nativeObserverAdmissionMax = 64 * 1024
const nativeObserverMax = 6

var errNativeObserver = errors.New("GG_NATIVE_OBSERVER_INVALID")
var errNativeObserverSigning = errors.New("GG_NATIVE_OBSERVER_SIGNING_FORBIDDEN")

type nativeObserverPV struct{ public cmted.PubKey }

func newNativeObserverPV(public []byte) (*nativeObserverPV, error) {
	if !validAuthorKey(public) {
		return nil, errNativeObserver
	}
	return &nativeObserverPV{public: append(cmted.PubKey(nil), public...)}, nil
}

func (pv *nativeObserverPV) GetPubKey() (cmtcrypto.PubKey, error) {
	if pv == nil || !validAuthorKey(pv.public) {
		return nil, errNativeObserver
	}
	return append(cmted.PubKey(nil), pv.public...), nil
}

func (*nativeObserverPV) SignVote(string, *cmtproto.Vote) error {
	return errNativeObserverSigning
}

func (*nativeObserverPV) SignProposal(string, *cmtproto.Proposal) error {
	return errNativeObserverSigning
}

// Lexical field order matches the existing compact sorted-key public encoding.
// Human labels are base64 UTF-8, as in native validator possession proofs.
type nativeObserverGrantBody struct {
	GenesisHash      string `json:"genesis_hash"`
	Host             string `json:"host"`
	LabelUTF8        string `json:"label_utf8"`
	NodeKey          string `json:"node_key"`
	OwnerPeerKey     string `json:"owner_peer_key"`
	P2PPort          int    `json:"p2p_port"`
	ProducerKey      string `json:"producer_key"`
	Schema           string `json:"schema"`
	SignatureProfile string `json:"signature_profile"`
}

type nativeObserverGrant struct {
	Body              nativeObserverGrantBody `json:"body"`
	NodeSignature     string                  `json:"node_signature"`
	OwnerSignature    string                  `json:"owner_signature"`
	ProducerSignature string                  `json:"producer_signature"`
}

type nativeObserverAdmissionDocument struct {
	GenesisHash string                `json:"genesis_hash"`
	Grants      []nativeObserverGrant `json:"grants"`
	Schema      string                `json:"schema"`
}

func nativeObserverProducers(genesis Genesis) []string {
	if genesis.FinancialDAG != nil {
		return genesis.FinancialDAG.Producers
	}
	if genesis.DAGSegmented != nil {
		return genesis.DAGSegmented.Genesis.Producers
	}
	if genesis.DAG != nil {
		return genesis.DAG.Genesis.Producers
	}
	return nil
}

// The caller must supply the already validated immutable native genesis/pin.
// A registered producer delegates a READ-ONLY node, not its producer key or
// voting rights. The signed LAN layer additionally binds that producer to the
// authenticated transport owner; this native capability proves possession.
func validateNativeObserverGrant(grant nativeObserverGrant, genesis Genesis, anchor string) error {
	body := grant.Body
	if genesis.Membership == nil || body.Schema != nativeObserverGrantSchema || body.SignatureProfile != TransactionSignatureProfile ||
		body.GenesisHash != anchor || !pubPattern.MatchString(anchor) || !privateMemberHost(body.Host) ||
		body.P2PPort < 1024 || body.P2PPort > 65535 || len(body.LabelUTF8) > 344 {
		return errNativeObserver
	}
	label, err := base64.StdEncoding.Strict().DecodeString(body.LabelUTF8)
	if err != nil || base64.StdEncoding.EncodeToString(label) != body.LabelUTF8 || !utf8.Valid(label) || utf8.RuneCount(label) < 1 || utf8.RuneCount(label) > 64 {
		return errNativeObserver
	}
	for _, value := range string(label) {
		if value < 32 || value == 127 {
			return errNativeObserver
		}
	}
	registered := false
	for _, producer := range nativeObserverProducers(genesis) {
		registered = registered || producer == body.ProducerKey
		if producer == body.NodeKey || producer == body.OwnerPeerKey {
			return errNativeObserver
		}
	}
	if !registered || body.NodeKey == body.OwnerPeerKey || body.NodeKey == body.ProducerKey {
		return errNativeObserver
	}
	for _, invite := range genesis.Membership.Validators {
		member := invite.Body
		for _, forbidden := range []string{member.ValidatorKey, member.NodeKey, member.AccountKey, member.OwnerPeerKey} {
			if body.NodeKey == forbidden {
				return errNativeObserver
			}
		}
		if body.OwnerPeerKey == member.ValidatorKey || body.OwnerPeerKey == member.NodeKey || body.OwnerPeerKey == member.AccountKey {
			return errNativeObserver
		}
		if body.Host == member.Host && body.P2PPort == member.P2PPort {
			return errNativeObserver
		}
	}
	roles := []string{"node", "owner", "producer"}
	keys := []string{body.NodeKey, body.OwnerPeerKey, body.ProducerKey}
	signatures := []string{grant.NodeSignature, grant.OwnerSignature, grant.ProducerSignature}
	for index, role := range roles {
		public, keyErr := hex.DecodeString(keys[index])
		signature, signatureErr := hex.DecodeString(signatures[index])
		message := append([]byte("GG-NATIVE-OBSERVER-"+strings.ToUpper(role)+"-GRANT-v1\x00"), canonical(body)...)
		if keyErr != nil || !pubPattern.MatchString(keys[index]) || !validAuthorKey(public) || signatureErr != nil ||
			len(signature) != 64 || signatures[index] != hex.EncodeToString(signature) || !verifyTransactionSignature(public, message, signature) {
			return errNativeObserver
		}
	}
	return nil
}

type nativeObserverPeerPolicy struct {
	mu         sync.Mutex
	genesis    Genesis
	anchor     string
	root       string
	cachedHash string
	cached     []nativeObserverGrant
	valid      bool
}

func newNativeObserverPeerPolicy(genesis Genesis, anchor, root string) (*nativeObserverPeerPolicy, error) {
	if validateGenesis(genesis, anchor) != nil || genesis.Membership == nil || len(nativeObserverProducers(genesis)) != 6 ||
		!filepath.IsAbs(root) || !realArchiveDirectory(root) {
		return nil, errNativeObserver
	}
	var owned Genesis
	if decodeStrict(canonical(genesis), &owned) != nil {
		return nil, errNativeObserver
	}
	return &nativeObserverPeerPolicy{genesis: owned, anchor: anchor, root: root}, nil
}

func (policy *nativeObserverPeerPolicy) grants(ctx context.Context) ([]nativeObserverGrant, bool) {
	if ctx == nil || ctx.Err() != nil {
		return nil, false
	}
	file, _, err := checkedSegmentFile(filepath.Join(policy.root, nativeObserverAdmissionFile), false, nativeObserverAdmissionMax)
	if err != nil {
		return nil, false
	}
	raw, readErr := io.ReadAll(io.LimitReader(file, nativeObserverAdmissionMax+1))
	closeErr := file.Close()
	if readErr != nil || closeErr != nil || len(raw) > nativeObserverAdmissionMax || ctx.Err() != nil {
		return nil, false
	}
	// Cache this PUBLIC capability set by its complete content digest, never
	// mtime/size alone. Modified bytes require a fresh canonical/signature check.
	digest := hashHex(raw)
	policy.mu.Lock()
	defer policy.mu.Unlock()
	if digest == policy.cachedHash {
		return policy.cached, policy.valid
	}
	policy.cachedHash, policy.cached, policy.valid = digest, nil, false
	var document nativeObserverAdmissionDocument
	if decodeStrictLimited(raw, &document, nativeObserverMax, 12) != nil || !bytes.Equal(raw, canonical(document)) ||
		document.Schema != nativeObserverAdmissionSchema || document.GenesisHash != policy.anchor ||
		document.Grants == nil || len(document.Grants) > nativeObserverMax {
		return nil, false
	}
	producers, nodes, endpoints := map[string]bool{}, map[string]bool{}, map[string]bool{}
	for _, grant := range document.Grants {
		if ctx.Err() != nil {
			policy.cachedHash = ""
			return nil, false
		}
		body := grant.Body
		endpoint := net.JoinHostPort(body.Host, strconv.Itoa(body.P2PPort))
		if validateNativeObserverGrant(grant, policy.genesis, policy.anchor) != nil ||
			producers[body.ProducerKey] || nodes[body.NodeKey] || endpoints[endpoint] {
			return nil, false
		}
		producers[body.ProducerKey], nodes[body.NodeKey], endpoints[endpoint] = true, true, true
	}
	if ctx.Err() != nil {
		policy.cachedHash = ""
		return nil, false
	}
	policy.cached, policy.valid = document.Grants, true
	return policy.cached, true
}

func (policy *nativeObserverPeerPolicy) allowed(ctx context.Context, path string) bool {
	if ctx == nil || ctx.Err() != nil {
		return false
	}
	// Corrupt, missing or slow optional-node metadata never removes the fixed
	// committee's existing peer authorization or changes its voting power.
	if membershipPeerAllowed(policy.genesis.Membership, path) {
		return true
	}
	identifier, host := "", ""
	if strings.HasPrefix(path, "/p2p/filter/id/") {
		identifier = strings.TrimPrefix(path, "/p2p/filter/id/")
		raw, err := hex.DecodeString(identifier)
		if err != nil || len(raw) != 20 || hex.EncodeToString(raw) != identifier {
			return false
		}
	} else if strings.HasPrefix(path, "/p2p/filter/addr/") {
		address, port, err := net.SplitHostPort(strings.TrimPrefix(path, "/p2p/filter/addr/"))
		number, portErr := strconv.Atoi(port)
		if err != nil || portErr != nil || number < 1 || number > 65535 || !privateMemberHost(address) {
			return false
		}
		host = address
	} else {
		return false
	}
	grants, valid := policy.grants(ctx)
	if !valid {
		return false
	}
	for _, grant := range grants {
		if identifier != "" && membershipNodeID(grant.Body.NodeKey) == identifier || host != "" && grant.Body.Host == host {
			return true
		}
	}
	return false
}
