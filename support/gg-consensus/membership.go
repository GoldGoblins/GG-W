package main

// Public fixed membership. Possession proofs bind the four roles; SDK vote
// verification and voting power remain unchanged. Labels attest no hardware.
import (
	"encoding/base64"
	"encoding/hex"
	"errors"
	"math"
	"net"
	"sort"
	"strconv"
	"strings"
	"unicode/utf8"
)

type ConsensusMemberBody struct {
	AccountKey       string `json:"account_key"`
	Host             string `json:"host"`
	LabelUTF8        string `json:"label_utf8"`
	NodeKey          string `json:"node_key"`
	Nonce            string `json:"nonce"`
	OwnerPeerKey     string `json:"owner_peer_key"`
	P2PPort          int    `json:"p2p_port"`
	Schema           string `json:"schema"`
	SignatureProfile string `json:"signature_profile"`
	ValidatorKey     string `json:"validator_key"`
}

type ConsensusMemberInvite struct {
	AccountSignature   string              `json:"account_signature"`
	Body               ConsensusMemberBody `json:"body"`
	NodeSignature      string              `json:"node_signature"`
	OwnerSignature     string              `json:"owner_signature"`
	ValidatorSignature string              `json:"validator_signature"`
}

type ConsensusMembership struct {
	ChainID     string                  `json:"chain_id"`
	GenesisTime int64                   `json:"genesis_time_unix"`
	Schema      string                  `json:"schema"`
	Scope       string                  `json:"scope"`
	Validators  []ConsensusMemberInvite `json:"validators"`
}

func privateMemberHost(host string) bool {
	ip := net.ParseIP(host)
	if ip == nil || ip.To4() == nil || ip.String() != host {
		return false
	}
	address := ip.To4()
	return address[0] == 127 || address[0] == 10 || address[0] == 172 && address[1] >= 16 && address[1] <= 31 || address[0] == 192 && address[1] == 168
}

func membershipNodeID(public string) string {
	raw, _ := hex.DecodeString(public)
	return hashHex(raw)[:40]
}

func membershipPeerAllowed(membership *ConsensusMembership, path string) bool {
	if membership == nil {
		return false
	}
	if strings.HasPrefix(path, "/p2p/filter/id/") {
		identifier := strings.TrimPrefix(path, "/p2p/filter/id/")
		for _, invite := range membership.Validators {
			if identifier == membershipNodeID(invite.Body.NodeKey) {
				return true
			}
		}
	} else if strings.HasPrefix(path, "/p2p/filter/addr/") {
		host, port, err := net.SplitHostPort(strings.TrimPrefix(path, "/p2p/filter/addr/"))
		number, portError := strconv.Atoi(port)
		if err != nil || portError != nil || number < 1 || number > 65535 || !privateMemberHost(host) {
			return false
		}
		for _, invite := range membership.Validators {
			if host == invite.Body.Host {
				return true
			}
		}
	}
	return false
}

func validateMemberInvite(invite ConsensusMemberInvite) error {
	body := invite.Body
	if body.Schema != "gg.consensus.validator.invite.v1" || body.SignatureProfile != TransactionSignatureProfile ||
		!pubPattern.MatchString(body.Nonce) || !privateMemberHost(body.Host) || body.P2PPort < 1024 || body.P2PPort > 65535 || len(body.LabelUTF8) > 344 {
		return errors.New("GG_CONSENSUS_MEMBER_CONTEXT")
	}
	label, err := base64.StdEncoding.Strict().DecodeString(body.LabelUTF8)
	if err != nil || base64.StdEncoding.EncodeToString(label) != body.LabelUTF8 || !utf8.Valid(label) || utf8.RuneCount(label) < 1 || utf8.RuneCount(label) > 64 {
		return errors.New("GG_CONSENSUS_MEMBER_LABEL")
	}
	for _, r := range string(label) {
		if r < 32 || r == 127 {
			return errors.New("GG_CONSENSUS_MEMBER_LABEL")
		}
	}
	roles := []string{"validator", "node", "account", "owner"}
	keys := []string{body.ValidatorKey, body.NodeKey, body.AccountKey, body.OwnerPeerKey}
	signatures := []string{invite.ValidatorSignature, invite.NodeSignature, invite.AccountSignature, invite.OwnerSignature}
	seen := map[string]bool{}
	for i, public := range keys {
		raw, keyError := hex.DecodeString(public)
		signature, signatureError := hex.DecodeString(signatures[i])
		message := append([]byte("GG-CONSENSUS-"+strings.ToUpper(roles[i])+"-INVITE-v1\x00"), canonical(body)...)
		if keyError != nil || !pubPattern.MatchString(public) || seen[public] || !validAuthorKey(raw) || signatureError != nil ||
			len(signature) != 64 || signatures[i] != hex.EncodeToString(signature) || !verifyTransactionSignature(raw, message, signature) {
			return errors.New("GG_CONSENSUS_MEMBER_POSSESSION")
		}
		seen[public] = true
	}
	return nil
}

func validateMembership(membership ConsensusMembership, genesis Genesis) error {
	if !hasDagExecution(genesis) || membership.Schema != "gg.lan.consensus.membership.v1" || membership.Scope != "PRIVATE_LAN_EXPERIMENT" ||
		membership.ChainID != genesis.ChainID || membership.GenesisTime != genesis.GenesisTime || membership.GenesisTime <= 0 ||
		membership.GenesisTime > (math.MaxInt64-5000000000)/1000000000 || len(membership.Validators) != 4 || len(canonical(membership)) > 20*1024 ||
		len(genesis.Validators) != 4 || (!generalFinancialAccounts(genesis) && len(genesis.Accounts) != 4) || (generalFinancialAccounts(genesis) && genesis.Accounts != nil) {
		return errors.New("GG_CONSENSUS_MEMBERSHIP_CONTEXT")
	}
	forbidden := map[string]bool{}
	var producers []string
	if genesis.DAG != nil {
		producers = genesis.DAG.Genesis.Producers
	} else if genesis.DAGSegmented != nil {
		producers = genesis.DAGSegmented.Genesis.Producers
	} else if genesis.FinancialDAG != nil {
		producers = genesis.FinancialDAG.Producers
	}
	for _, public := range producers {
		forbidden[public] = true
	}
	owners := map[string]bool{}
	for _, invite := range membership.Validators {
		owners[invite.Body.OwnerPeerKey] = true
	}
	keys := map[string]bool{}
	endpoints := map[string]bool{}
	order := []string{}
	for i, invite := range membership.Validators {
		if validateMemberInvite(invite) != nil {
			return errors.New("GG_CONSENSUS_MEMBERSHIP_INVITE")
		}
		body := invite.Body
		if forbidden[body.OwnerPeerKey] || genesis.Validators[i] != body.ValidatorKey || !generalFinancialAccounts(genesis) && genesis.Accounts[i] != body.AccountKey {
			return errors.New("GG_CONSENSUS_MEMBERSHIP_BINDING")
		}
		for _, public := range []string{body.ValidatorKey, body.NodeKey, body.AccountKey} {
			if forbidden[public] || owners[public] || keys[public] {
				return errors.New("GG_CONSENSUS_MEMBERSHIP_ROLE")
			}
			keys[public] = true
		}
		endpoint := net.JoinHostPort(body.Host, strconv.Itoa(body.P2PPort))
		if endpoints[endpoint] {
			return errors.New("GG_CONSENSUS_MEMBERSHIP_ENDPOINT")
		}
		endpoints[endpoint] = true
		order = append(order, body.ValidatorKey)
	}
	if !sort.StringsAreSorted(order) {
		return errors.New("GG_CONSENSUS_MEMBERSHIP_ORDER")
	}
	return nil
}
