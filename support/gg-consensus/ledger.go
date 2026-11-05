package main

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"

	abci "github.com/cometbft/cometbft/abci/types"
)

const Supply uint64 = 1000000000000
const MaxTxBytes = 2048
const MaxBlockTxs = 128
const HistoryLimit = 256

var pubPattern = regexp.MustCompile(`^[0-9a-f]{64}$`)
var chainPattern = regexp.MustCompile(`^ggnet:[0-9a-f]{24}$`)
var uintPattern = regexp.MustCompile(`^(0|[1-9][0-9]{0,19})$`)

// Field ordering below is lexicographic, matching compact sorted-key JSON.
type Genesis struct {
	checked           *checkedGenesisContext
	Accounts          []string                  `json:"accounts"`
	ChainID           string                    `json:"chain_id"`
	DAG               *DagSource                `json:"dag,omitempty"`
	DAGSegmented      *dagSegmentedSource       `json:"dag_segmented,omitempty"`
	Decimals          int                       `json:"decimals"`
	FinancialAccounts *financialAccountGenesis  `json:"financial_accounts,omitempty"`
	FinancialDAG      *financialDagSource       `json:"financial_dag,omitempty"`
	GenesisTime       int64                     `json:"genesis_time_unix"`
	Membership        *ConsensusMembership      `json:"membership,omitempty"`
	Protocol          *financialProtocolGenesis `json:"protocol,omitempty"`
	Schema            string                    `json:"schema"`
	SupplyAtomic      string                    `json:"supply_atomic"`
	Symbol            string                    `json:"symbol"`
	Validators        []string                  `json:"validators"`
}

// This handle is created only after local full genesis validation. It is not
// decoded from JSON; the canonical anchor is rechecked before reuse.
type checkedGenesisContext struct {
	anchor   string
	reserved map[string]bool
}

type Body struct {
	Amount      string  `json:"amount_atomic"`
	ChainID     string  `json:"chain_id"`
	GenesisHash string  `json:"genesis_hash"`
	MaxFee      *string `json:"max_fee_atomic,omitempty"`
	Nonce       uint64  `json:"nonce"`
	Recipient   string  `json:"recipient"`
	Sender      string  `json:"sender"`
	Version     int     `json:"version"`
}

type Envelope struct {
	Body      Body   `json:"body"`
	Signature string `json:"signature"`
}

type Account struct {
	Address string `json:"address"`
	Balance string `json:"balance_atomic"`
	Nonce   uint64 `json:"nonce"`
}

type Commitment struct {
	AccountRoot  string                  `json:"account_root"`
	AccountTree  *financialAccountLink   `json:"account_tree,omitempty"`
	ChainID      string                  `json:"chain_id"`
	DAG          *DagCommitment          `json:"dag,omitempty"`
	DAGSegmented *dagSegmentedState      `json:"dag_segmented,omitempty"`
	FinancialDAG *financialDagCommitment `json:"financial_dag,omitempty"`
	GenesisHash  string                  `json:"genesis_hash"`
	ProtocolRoot string                  `json:"protocol_root,omitempty"`
	Schema       string                  `json:"schema"`
	SupplyAtomic string                  `json:"supply_atomic"`
}

type State struct {
	AccountRoot  string                       `json:"account_root"`
	AccountTree  *financialAccountLink        `json:"account_tree,omitempty"`
	Accounts     []Account                    `json:"accounts"`
	ChainID      string                       `json:"chain_id"`
	DAG          *DagCommitment               `json:"dag,omitempty"`
	DAGSegmented *dagSegmentedState           `json:"dag_segmented,omitempty"`
	Decimals     int                          `json:"decimals"`
	FinancialDAG *financialDagCommitment      `json:"financial_dag,omitempty"`
	GenesisHash  string                       `json:"genesis_hash"`
	Height       int64                        `json:"height"`
	Protocol     *financialProtocolCommitment `json:"protocol,omitempty"`
	Schema       string                       `json:"schema"`
	StateRoot    string                       `json:"state_root"`
	SupplyAtomic string                       `json:"supply_atomic"`
	Symbol       string                       `json:"symbol"`
}

type PathItem struct {
	Hash string `json:"hash"`
	Side string `json:"side"`
}

type Proof struct {
	AccountRoot string     `json:"account_root"`
	ChainID     string     `json:"chain_id"`
	Commitment  Commitment `json:"commitment"`
	GenesisHash string     `json:"genesis_hash"`
	Height      int64      `json:"height"`
	Leaf        Account    `json:"leaf"`
	Path        []PathItem `json:"path"`
	Schema      string     `json:"schema"`
	StateRoot   string     `json:"state_root"`
}

func canonical(value any) []byte {
	data, err := json.Marshal(value)
	if err != nil {
		panic("GG_CANONICAL_ENCODING")
	}
	return data
}

func hashHex(data []byte) string {
	value := sha256.Sum256(data)
	return hex.EncodeToString(value[:])
}

// json.Valid is the syntax authority. The second walk checks only decoded
// object names and the existing depth bound, skipping value strings in place.
// It never constructs a second copy of a batch's large base64 value.
type jsonNameWalk struct {
	raw              []byte
	pos              int
	maxArrayElements int
	maxObjectFields  int
}

func (walk *jsonNameWalk) space() {
	for walk.pos < len(walk.raw) {
		switch walk.raw[walk.pos] {
		case ' ', '\t', '\r', '\n':
			walk.pos++
		default:
			return
		}
	}
}
func (walk *jsonNameWalk) quoted() (int, int) {
	start := walk.pos
	walk.pos++
	for walk.pos < len(walk.raw) {
		value := walk.raw[walk.pos]
		walk.pos++
		if value == '\\' {
			walk.pos++
		} else if value == '"' {
			return start, walk.pos
		}
	}
	return start, walk.pos
}
func (walk *jsonNameWalk) value(depth int) error {
	if depth > 12 {
		return errors.New("GG_JSON_DEPTH")
	}
	walk.space()
	switch walk.raw[walk.pos] {
	case '{':
		walk.pos++
		walk.space()
		seen := map[string]bool{}
		fields := 0
		if walk.raw[walk.pos] == '}' {
			walk.pos++
			return nil
		}
		for {
			fields++
			if walk.maxObjectFields > 0 && fields > walk.maxObjectFields {
				return errors.New("GG_JSON_OBJECT_LIMIT")
			}
			first, last := walk.quoted()
			var name string
			if json.Unmarshal(walk.raw[first:last], &name) != nil {
				return errors.New("GG_JSON_KEY")
			}
			if seen[name] {
				return errors.New("GG_JSON_DUPLICATE_KEY")
			}
			seen[name] = true
			walk.space()
			walk.pos++ // validated colon
			if err := walk.value(depth + 1); err != nil {
				return err
			}
			walk.space()
			separator := walk.raw[walk.pos]
			walk.pos++
			if separator == '}' {
				return nil
			}
			walk.space()
		}
	case '[':
		walk.pos++
		walk.space()
		if walk.raw[walk.pos] == ']' {
			walk.pos++
			return nil
		}
		elements := 0
		for {
			elements++
			if walk.maxArrayElements > 0 && elements > walk.maxArrayElements {
				return errors.New("GG_JSON_ARRAY_LIMIT")
			}
			if err := walk.value(depth + 1); err != nil {
				return err
			}
			walk.space()
			separator := walk.raw[walk.pos]
			walk.pos++
			if separator == ']' {
				return nil
			}
		}
	case '"':
		walk.quoted()
	default:
		for walk.pos < len(walk.raw) {
			switch walk.raw[walk.pos] {
			case ' ', '\t', '\r', '\n', ',', ']', '}':
				return nil
			default:
				walk.pos++
			}
		}
	}
	return nil
}
func decodeStrict(data []byte, target any) error {
	return decodeStrictLimited(data, target, 0, 0)
}

// Reject impossible DAG collection shapes BEFORE encoding/json can allocate
// millions of typed TX rows from a small array of empty/malformed objects.
// The ordinary reader retains its previous acceptance rules and defaults.
func decodeStrictLimited(data []byte, target any, maxArrayElements, maxObjectFields int) error {
	if !json.Valid(data) {
		return errors.New("GG_JSON_ENCODING")
	}
	walk := jsonNameWalk{raw: data, maxArrayElements: maxArrayElements, maxObjectFields: maxObjectFields}
	if err := walk.value(0); err != nil {
		return err
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	return decoder.Decode(target)
}

func validateGenesis(genesis Genesis, anchor string) error {
	if genesis.checked != nil && genesis.checked.anchor == anchor && anchor == hashHex(canonical(genesis)) {
		return nil
	}
	expectedSchema := "gg.native.genesis.v1"
	if genesis.DAGSegmented != nil {
		if err := validateSegmentedGenesis(genesis); err != nil {
			return err
		}
		expectedSchema = "gg.native.genesis.v4"
	}
	if genesis.DAG != nil {
		expectedSchema = "gg.native.genesis.v2"
		if validateDagSource(*genesis.DAG) != nil {
			return errors.New("GG_GENESIS_DAG_SOURCE")
		}
		started, _ := dagDecimalNs(genesis.DAG.StartedAtNs)
		if genesis.GenesisTime <= 0 || genesis.GenesisTime > (int64(^uint64(0)>>1)-5000000000)/1000000000 || started > genesis.GenesisTime*1000000000+5000000000 {
			return errors.New("GG_GENESIS_DAG_TIME")
		}
		for _, validator := range genesis.Validators {
			for _, producer := range genesis.DAG.Genesis.Producers {
				if validator == producer {
					return errors.New("GG_GENESIS_DAG_VALIDATOR_ROLE")
				}
			}
		}
	}
	if genesis.Membership != nil {
		if genesis.DAGSegmented == nil {
			expectedSchema = "gg.native.genesis.v3"
		}
		if validateMembership(*genesis.Membership, genesis) != nil {
			return errors.New("GG_GENESIS_MEMBERSHIP")
		}
	}
	if genesis.FinancialDAG != nil {
		if genesis.DAG != nil || genesis.DAGSegmented != nil || genesis.FinancialDAG.validateShape(genesis) != nil {
			return errors.New("GG_GENESIS_FINANCIAL_DAG")
		}
		expectedSchema = "gg.native.genesis.v5"
		if genesis.FinancialDAG.hasGeneralAccounts() {
			if validateFinancialAccountGenesis(genesis) != nil {
				return errors.New("GG_GENESIS_FINANCIAL_ACCOUNTS")
			}
			expectedSchema = "gg.native.genesis.v6"
		}
		if publicFinancialProtocol(genesis) {
			if validateFinancialProtocolGenesis(genesis) != nil {
				return errors.New("GG_GENESIS_FINANCIAL_PROTOCOL")
			}
			expectedSchema = "gg.native.genesis.v7"
		}
	}
	if genesis.Protocol != nil && !publicFinancialProtocol(genesis) {
		return errors.New("GG_GENESIS_FINANCIAL_PROTOCOL")
	}
	if genesis.FinancialAccounts != nil && !generalFinancialAccounts(genesis) {
		return errors.New("GG_GENESIS_FINANCIAL_ACCOUNTS")
	}
	accountShape := len(genesis.Accounts) == 4 && genesis.FinancialAccounts == nil
	if generalFinancialAccounts(genesis) {
		accountShape = genesis.Accounts == nil
	}
	monetaryShape := genesis.SupplyAtomic == strconv.FormatUint(Supply, 10) && genesis.Symbol == "GG-NET-TEST"
	validatorShape := len(genesis.Validators) == 4
	if publicFinancialProtocol(genesis) {
		monetaryShape = genesis.SupplyAtomic == genesis.Protocol.Economics.InitialSupply && (genesis.Protocol.Environment == "TESTNET" && genesis.Symbol == "GG-TEST" || genesis.Protocol.Environment == "MAINNET" && genesis.Symbol == "GG")
		validatorShape = len(genesis.Validators) == len(genesis.Protocol.Committee.Members)
	}
	if genesis.Schema != expectedSchema || !chainPattern.MatchString(genesis.ChainID) ||
		genesis.Decimals != 6 || !monetaryShape ||
		genesis.GenesisTime <= 0 || !accountShape || !validatorShape ||
		anchor != hashHex(canonical(genesis)) {
		return errors.New("GG_GENESIS_INVALID")
	}
	for _, entries := range [][]string{genesis.Accounts, genesis.Validators} {
		seen := map[string]bool{}
		for _, entry := range entries {
			raw, err := hex.DecodeString(entry)
			if !canonicalFinancialHex(entry) || seen[entry] || err != nil || !validAuthorKey(raw) {
				return errors.New("GG_GENESIS_IDENTITIES")
			}
			seen[entry] = true
		}
	}
	return nil
}

func initialNativeAccounts(genesis Genesis) []Account {
	if generalFinancialAccounts(genesis) {
		return nil
	}
	addresses := append([]string(nil), genesis.Accounts...)
	sort.Strings(addresses)
	accounts := make([]Account, 0, len(addresses))
	for _, address := range addresses {
		accounts = append(accounts, Account{Address: address, Balance: strconv.FormatUint(Supply/4, 10)})
	}
	return accounts
}

func initialState(genesis Genesis, anchor string) State {
	state := State{ChainID: genesis.ChainID, GenesisHash: anchor, Accounts: initialNativeAccounts(genesis), Decimals: 6, Height: 0, Schema: "gg.native.state.v1", SupplyAtomic: genesis.SupplyAtomic, Symbol: genesis.Symbol}
	if genesis.DAG != nil {
		execution, err := newDagExecution(*genesis.DAG, anchor)
		if err != nil {
			panic("GG_DAG_GENESIS_INVALID")
		}
		state.DAG = &execution.Commitment
		state.Schema = "gg.native.state.v2"
	}
	if genesis.DAGSegmented != nil {
		execution, err := newDagSegmentedExecution(*genesis.DAGSegmented, anchor)
		if err != nil {
			panic("GG_DAG_SEGMENTED_GENESIS_INVALID")
		}
		value, err := execution.state()
		if err != nil {
			panic("GG_DAG_SEGMENTED_GENESIS_INVALID")
		}
		state.DAGSegmented, state.Schema = &value, "gg.native.state.v3"
	}
	if genesis.FinancialDAG != nil {
		execution, err := newFinancialDagExecution(genesis, anchor, *genesis.FinancialDAG)
		if err != nil {
			panic("GG_FINANCIAL_DAG_GENESIS_INVALID")
		}
		value, err := execution.commitment()
		if err != nil {
			panic("GG_FINANCIAL_DAG_GENESIS_INVALID")
		}
		state.FinancialDAG, state.Schema = &value, "gg.native.state.v4"
		if generalFinancialAccounts(genesis) {
			root := execution.money.Tree.root.link
			state.AccountTree = &root
			state.Schema = "gg.native.state.v5"
		}
		if publicFinancialProtocol(genesis) {
			protocol := execution.money.Protocol.commitment()
			state.Protocol = &protocol
			state.Schema = "gg.native.state.v6"
			state.SupplyAtomic = protocol.Economics.Issued
		}
	}
	sealState(&state)
	return state
}

func merkleLevels(accounts []Account) [][][32]byte {
	leaves := make([][32]byte, 4)
	for i, account := range accounts {
		leaves[i] = sha256.Sum256(append([]byte{0}, canonical(account)...))
	}
	levels := [][][32]byte{leaves}
	for len(levels[len(levels)-1]) > 1 {
		previous := levels[len(levels)-1]
		next := make([][32]byte, len(previous)/2)
		for i := range next {
			raw := append([]byte{1}, previous[i*2][:]...)
			raw = append(raw, previous[i*2+1][:]...)
			next[i] = sha256.Sum256(raw)
		}
		levels = append(levels, next)
	}
	return levels
}

func commitmentFor(state State) Commitment {
	schema := "gg.native.commitment.v1"
	if state.DAG != nil {
		schema = "gg.native.commitment.v2"
	}
	if state.DAGSegmented != nil {
		schema = "gg.native.commitment.v3"
	}
	if state.FinancialDAG != nil {
		schema = "gg.native.commitment.v4"
		if state.AccountTree != nil {
			schema = "gg.native.commitment.v5"
		}
	}
	protocolRoot := ""
	if state.Protocol != nil {
		schema = "gg.native.commitment.v6"
		protocolRoot = financialProtocolRoot(*state.Protocol)
	}
	return Commitment{AccountRoot: state.AccountRoot, AccountTree: state.AccountTree, ChainID: state.ChainID, DAG: state.DAG, DAGSegmented: state.DAGSegmented, FinancialDAG: state.FinancialDAG, GenesisHash: state.GenesisHash, ProtocolRoot: protocolRoot, Schema: schema, SupplyAtomic: state.SupplyAtomic}
}

func sealState(state *State) {
	if state.AccountTree != nil {
		state.AccountRoot = state.AccountTree.Hash
	} else {
		state.AccountRoot = nativeAccountRoot(state.Accounts)
	}
	state.StateRoot = hashHex(canonical(commitmentFor(*state)))
}

func nativeAccountRoot(accounts []Account) string {
	levels := merkleLevels(accounts)
	root := levels[len(levels)-1][0]
	return hex.EncodeToString(root[:])
}

// Monetary account rules are separate from the surrounding DAG commitment.
// This remains the existing four-account test model, with unchanged leaf bytes.
func validateNativeAccountState(accounts []Account, genesis Genesis, root string) error {
	if len(accounts) != 4 || len(genesis.Accounts) != 4 {
		return errors.New("GG_STATE_ACCOUNTS")
	}
	expected := append([]string(nil), genesis.Accounts...)
	sort.Strings(expected)
	total := uint64(0)
	for i, account := range accounts {
		balance, err := strconv.ParseUint(account.Balance, 10, 64)
		if err != nil || !uintPattern.MatchString(account.Balance) || account.Address != expected[i] || balance > Supply || total > Supply-balance {
			return errors.New("GG_STATE_ACCOUNTS")
		}
		total += balance
	}
	if total != Supply {
		return errors.New("GG_STATE_SUPPLY")
	}
	if nativeAccountRoot(accounts) != root {
		return errors.New("GG_STATE_ROOT")
	}
	return nil
}

func copyState(state State) State {
	state.Accounts = append([]Account(nil), state.Accounts...)
	if state.AccountTree != nil {
		root := *state.AccountTree
		state.AccountTree = &root
	}
	if state.DAG != nil {
		value := *state.DAG
		state.DAG = &value
	}
	if state.DAGSegmented != nil {
		value := *state.DAGSegmented
		state.DAGSegmented = &value
	}
	if state.FinancialDAG != nil {
		value := *state.FinancialDAG
		value.Authors = append([]financialDagAuthor(nil), state.FinancialDAG.Authors...)
		if value.ProducerRoot != nil {
			root := *value.ProducerRoot
			value.ProducerRoot = &root
		}
		if value.AccountTree != nil {
			root := *value.AccountTree
			value.AccountTree = &root
		}
		state.FinancialDAG = &value
	}
	if state.Protocol != nil {
		value := copyFinancialProtocolCommitment(*state.Protocol)
		state.Protocol = &value
	}
	return state
}

func validateState(state State, genesis Genesis, anchor string) error {
	schema := "gg.native.state.v1"
	if genesis.DAG != nil {
		schema = "gg.native.state.v2"
		if state.DAG == nil || state.Height < 0 || state.DAG.Checkpoint > uint64(state.Height) || validateDagCommitment(*state.DAG, *genesis.DAG, anchor) != nil {
			return errors.New("GG_STATE_DAG")
		}
	} else if state.DAG != nil {
		return errors.New("GG_STATE_DAG_UNEXPECTED")
	}
	if genesis.DAGSegmented != nil {
		schema = "gg.native.state.v3"
		if state.DAGSegmented == nil || state.Height < 0 || validateSegmentedState(*state.DAGSegmented, *genesis.DAGSegmented, anchor) != nil ||
			state.DAGSegmented.Active.Checkpoint > uint64(state.Height) || state.DAGSegmented.Epoch-1 > uint64(state.Height) {
			return errors.New("GG_STATE_SEGMENTED_DAG")
		}
	} else if state.DAGSegmented != nil {
		return errors.New("GG_STATE_SEGMENTED_UNEXPECTED")
	}
	if genesis.FinancialDAG != nil {
		schema = "gg.native.state.v4"
		if generalFinancialAccounts(genesis) {
			schema = "gg.native.state.v5"
		}
		if publicFinancialProtocol(genesis) {
			schema = "gg.native.state.v6"
		}
		if state.FinancialDAG == nil || state.Height < 0 || validateFinancialCommitment(*state.FinancialDAG, genesis, anchor) != nil ||
			state.FinancialDAG.Checkpoint > uint64(state.Height) || state.FinancialDAG.AccountRoot != state.AccountRoot {
			return errors.New("GG_STATE_FINANCIAL_DAG")
		}
	} else if state.FinancialDAG != nil {
		return errors.New("GG_STATE_FINANCIAL_UNEXPECTED")
	}
	accountShape := len(state.Accounts) == 4 && state.AccountTree == nil
	if generalFinancialAccounts(genesis) {
		accountShape = state.Accounts == nil && state.FinancialDAG != nil && state.FinancialDAG.AccountTree != nil &&
			validateFinancialAccountRoot(state.AccountTree, genesis, anchor, state.FinancialDAG.Applied) == nil &&
			*state.AccountTree == *state.FinancialDAG.AccountTree && state.AccountRoot == state.AccountTree.Hash
	}
	supplyShape := state.SupplyAtomic == genesis.SupplyAtomic
	if publicFinancialProtocol(genesis) {
		supplyShape = state.Protocol != nil && state.SupplyAtomic == state.Protocol.Economics.Issued && validateFinancialProtocolCommitment(state, genesis, anchor) == nil
	} else if state.Protocol != nil {
		supplyShape = false
	}
	if state.Schema != schema || state.ChainID != genesis.ChainID || state.GenesisHash != anchor || state.Height < 0 ||
		state.Decimals != 6 || state.Symbol != genesis.Symbol || !supplyShape || !accountShape {
		return errors.New("GG_STATE_INVALID")
	}
	if !generalFinancialAccounts(genesis) {
		if err := validateNativeAccountState(state.Accounts, genesis, state.AccountRoot); err != nil {
			return err
		}
	}
	copy := copyState(state)
	sealState(&copy)
	if copy.AccountRoot != state.AccountRoot || copy.StateRoot != state.StateRoot {
		return errors.New("GG_STATE_ROOT")
	}
	return nil
}

func parseEnvelope(raw []byte, genesis Genesis, anchor string) (Envelope, error) {
	var envelope Envelope
	if len(raw) == 0 || len(raw) > MaxTxBytes {
		return envelope, errors.New("GG_TX_SIZE")
	}
	if err := decodeStrict(raw, &envelope); err != nil {
		return envelope, errors.New("GG_TX_ENCODING")
	}
	if !bytes.Equal(raw, canonical(envelope)) {
		return envelope, errors.New("GG_TX_NONCANONICAL")
	}
	return validateEnvelopeValue(envelope, genesis, anchor)
}

// Encoding is established by the strict parser or a private owned
// decoded-payment binding. Context and signatures are ALWAYS checked.
func validateEnvelopeValue(envelope Envelope, genesis Genesis, anchor string) (Envelope, error) {
	body := envelope.Body
	versionValid := body.Version == 1 && body.MaxFee == nil
	if publicFinancialProtocol(genesis) {
		versionValid = body.Version == 2 && body.MaxFee != nil
		if versionValid {
			_, versionValid = economicAmount(*body.MaxFee)
		}
	}
	if !versionValid || body.ChainID != genesis.ChainID || body.GenesisHash != anchor || body.Sender == body.Recipient ||
		!canonicalFinancialHex(body.Sender) || !canonicalFinancialHex(body.Recipient) || !uintPattern.MatchString(body.Amount) {
		return envelope, errors.New("GG_TX_CONTEXT")
	}
	sender, recipient := false, false
	if generalFinancialAccounts(genesis) {
		sender = financialAccountAddress(body.Sender) && !financialReservedAccountKey(genesis, body.Sender)
		recipient = financialAccountAddress(body.Recipient) && !financialReservedAccountKey(genesis, body.Recipient)
	}
	for _, address := range genesis.Accounts {
		sender = sender || address == body.Sender
		recipient = recipient || address == body.Recipient
	}
	if !sender || !recipient {
		return envelope, errors.New("GG_TX_ACCOUNT")
	}
	amount, err := strconv.ParseUint(body.Amount, 10, 64)
	if err != nil || amount == 0 || amount > financialMaximumSupply(genesis) {
		return envelope, errors.New("GG_TX_AMOUNT")
	}
	public, _ := hex.DecodeString(body.Sender)
	signature, err := hex.DecodeString(envelope.Signature)
	if err != nil || len(signature) != ed25519.SignatureSize || envelope.Signature != hex.EncodeToString(signature) || !verifyTransactionSignature(public, canonical(body), signature) {
		return envelope, errors.New("GG_TX_SIGNATURE")
	}
	return envelope, nil
}

func applyEnvelope(state *State, envelope Envelope, pending bool) error {
	source, target := -1, -1
	for i, account := range state.Accounts {
		if account.Address == envelope.Body.Sender {
			source = i
		}
		if account.Address == envelope.Body.Recipient {
			target = i
		}
	}
	if source < 0 || target < 0 {
		return errors.New("GG_TX_ACCOUNT")
	}
	from := &state.Accounts[source]
	to := &state.Accounts[target]
	if pending {
		if envelope.Body.Nonce < from.Nonce || envelope.Body.Nonce-from.Nonce >= 256 {
			return errors.New("GG_TX_NONCE")
		}
	} else if envelope.Body.Nonce != from.Nonce {
		return errors.New("GG_TX_NONCE")
	}
	amount, _ := strconv.ParseUint(envelope.Body.Amount, 10, 64)
	balance, _ := strconv.ParseUint(from.Balance, 10, 64)
	dest, _ := strconv.ParseUint(to.Balance, 10, 64)
	if balance < amount || dest > Supply-amount || from.Nonce == ^uint64(0) {
		return errors.New("GG_TX_FUNDS")
	}
	if !pending {
		from.Balance = strconv.FormatUint(balance-amount, 10)
		to.Balance = strconv.FormatUint(dest+amount, 10)
		from.Nonce++
	}
	return nil
}

type persisted struct {
	GenesisHash string  `json:"genesis_hash"`
	History     []State `json:"history"`
	Schema      string  `json:"schema"`
}

type Ledger struct {
	abci.BaseApplication
	mu           sync.RWMutex
	genesis      Genesis
	anchor       string
	state        State
	staged       *State
	history      []State
	file         string
	dag          *DagExecution
	stagedDag    *DagExecution
	store        dagPersistence
	segmented    dagSegmentedApplication
	financial    financialApplication
	payloadSlots chan struct{}
}

func newLedger(genesis Genesis, anchor, root string) (*Ledger, error) {
	if err := validateGenesis(genesis, anchor); err != nil {
		return nil, err
	}
	if hasDagExecution(genesis) {
		return nil, errors.New("GG_DAG_EXPLICIT_STORE_MODE_REQUIRED")
	}
	app := &Ledger{genesis: genesis, anchor: anchor, state: initialState(genesis, anchor), file: filepath.Join(root, "gg-public-state.json")}
	app.history = []State{copyState(app.state)}
	if raw, err := os.ReadFile(app.file); err == nil {
		if len(raw) > 2*1024*1024 {
			return nil, errors.New("GG_HISTORY_SIZE")
		}
		var saved persisted
		if decodeStrict(raw, &saved) != nil || saved.Schema != "gg.native.public-history.v1" || saved.GenesisHash != anchor || len(saved.History) < 1 || len(saved.History) > HistoryLimit {
			return nil, errors.New("GG_HISTORY_INVALID")
		}
		for i, state := range saved.History {
			if validateState(state, genesis, anchor) != nil || (i > 0 && state.Height != saved.History[i-1].Height+1) {
				return nil, errors.New("GG_HISTORY_INVALID")
			}
		}
		app.history = saved.History
		app.state = copyState(saved.History[len(saved.History)-1])
	} else if !os.IsNotExist(err) {
		return nil, errors.New("GG_HISTORY_READ")
	}
	return app, nil
}

func (app *Ledger) Info(context.Context, *abci.RequestInfo) (*abci.ResponseInfo, error) {
	app.mu.RLock()
	defer app.mu.RUnlock()
	hash, _ := hex.DecodeString(app.state.StateRoot)
	version := uint64(1)
	label := "gg-native-test-v1"
	if app.store != nil {
		version = 2
		label = "gg-native-dag-test-v2"
	}
	if app.segmented != nil {
		version, label = 3, "gg-native-segmented-dag-test-v3"
	}
	if app.financial != nil {
		version, label = 4, "gg-native-financial-dag-test-v4"
	}
	return &abci.ResponseInfo{Data: "GG native four-validator test ledger", Version: label, AppVersion: version, LastBlockHeight: app.state.Height, LastBlockAppHash: hash}, nil
}

func isDagBatch(raw []byte) bool { return bytes.HasPrefix(raw, []byte("{\"blocks\":")) }

func (app *Ledger) applyTransaction(state *State, execution *DagExecution, raw []byte, blockTimeNs int64, pending bool) (*DagExecution, bool, error) {
	if isDagBatch(raw) {
		if app.store == nil || execution == nil {
			return execution, true, errors.New("GG_DAG_NOT_CONFIGURED")
		}
		next, err := applyDagBatch(execution, raw, blockTimeNs)
		if err != nil {
			return execution, true, err
		}
		value := next.Commitment
		state.DAG = &value
		return next, true, nil
	}
	envelope, err := parseEnvelope(raw, app.genesis, app.anchor)
	if err == nil {
		err = applyEnvelope(state, envelope, pending)
	}
	return execution, false, err
}

func (app *Ledger) preparePayload(execution *DagExecution) error {
	if app.store == nil {
		return nil
	}
	return app.store.prepare(execution)
}

func (app *Ledger) Close() error {
	app.mu.Lock()
	defer app.mu.Unlock()
	if app.financial != nil {
		return app.financial.Close()
	}
	if app.segmented != nil {
		return app.segmented.Close()
	}
	if app.store != nil {
		return app.store.close()
	}
	return nil
}

func (app *Ledger) InitChain(context.Context, *abci.RequestInitChain) (*abci.ResponseInitChain, error) {
	app.mu.RLock()
	defer app.mu.RUnlock()
	hash, _ := hex.DecodeString(app.state.StateRoot)
	return &abci.ResponseInitChain{AppHash: hash}, nil
}

func (app *Ledger) CheckTx(ctx context.Context, request *abci.RequestCheckTx) (*abci.ResponseCheckTx, error) {
	if app.financial != nil {
		return app.financial.CheckTx(ctx, request)
	}
	if app.segmented != nil {
		return app.segmented.CheckTx(ctx, request)
	}
	app.mu.RLock()
	defer app.mu.RUnlock()
	if app.store != nil {
		if err := app.store.health(); err != nil {
			if errors.Is(err, errDagHistoryUnavailable) {
				return nil, err
			}
			return &abci.ResponseCheckTx{Code: 1, Log: "GG_DAG_STORE_FAULT", Codespace: "gg"}, nil
		}
	}
	state := copyState(app.state)
	_, _, err := app.applyTransaction(&state, app.dag, request.Tx, 0, true)
	if errors.Is(err, errDagHistoryUnavailable) {
		return nil, err
	}
	if err != nil {
		return &abci.ResponseCheckTx{Code: 1, Log: err.Error(), Codespace: "gg"}, nil
	}
	return &abci.ResponseCheckTx{Code: 0, GasWanted: 1}, nil
}

func (app *Ledger) PrepareProposal(ctx context.Context, request *abci.RequestPrepareProposal) (*abci.ResponsePrepareProposal, error) {
	if app.financial != nil {
		return app.financial.PrepareProposal(ctx, request)
	}
	if app.segmented != nil {
		return app.segmented.PrepareProposal(ctx, request)
	}
	app.mu.RLock()
	defer app.mu.RUnlock()
	state := copyState(app.state)
	execution := app.dag
	dagSeen := false
	nativeSeen := false
	accepted := [][]byte{}
	size := int64(0)
	maxBytes := request.MaxTxBytes
	if app.store != nil && maxBytes > 64*1024*1024 {
		maxBytes = 64 * 1024 * 1024
	}
	for _, raw := range request.Txs {
		if len(accepted) >= MaxBlockTxs || size+int64(len(raw))+8 > maxBytes {
			break
		}
		// The two test assets have separate bounded execution-proof formats.
		// Preserve both transaction types, but never create a mixed block that
		// the lightweight native-transfer replay cannot completely verify.
		if isDagBatch(raw) && (dagSeen || nativeSeen) || !isDagBatch(raw) && dagSeen {
			continue
		}
		next, dagTx, err := app.applyTransaction(&state, execution, raw, request.Time.UnixNano(), false)
		if errors.Is(err, errDagHistoryUnavailable) {
			return nil, err
		}
		if err != nil {
			continue
		}
		execution = next
		dagSeen = dagSeen || dagTx
		nativeSeen = nativeSeen || !dagTx
		accepted = append(accepted, raw)
		size += int64(len(raw)) + 8
	}
	// A proposer may skip ProcessProposal for its own proposal. Its payload
	// must therefore already be durable before PrepareProposal returns it.
	if err := app.preparePayload(execution); err != nil {
		// Candidate pressure cannot prohibit a safe empty height. Such a
		// commit decides the height and releases its losing preparations.
		if errors.Is(err, errDagCandidateCredit) && app.preparePayload(app.dag) == nil {
			return &abci.ResponsePrepareProposal{Txs: [][]byte{}}, nil
		}
		return nil, err
	}
	return &abci.ResponsePrepareProposal{Txs: accepted}, nil
}

func (app *Ledger) ProcessProposal(ctx context.Context, request *abci.RequestProcessProposal) (*abci.ResponseProcessProposal, error) {
	if app.financial != nil {
		return app.financial.ProcessProposal(ctx, request)
	}
	if app.segmented != nil {
		return app.segmented.ProcessProposal(ctx, request)
	}
	app.mu.RLock()
	defer app.mu.RUnlock()
	state := copyState(app.state)
	execution := app.dag
	dagSeen := false
	nativeSeen := false
	size := 0
	if len(request.Txs) > MaxBlockTxs {
		return &abci.ResponseProcessProposal{Status: abci.ResponseProcessProposal_REJECT}, nil
	}
	for _, raw := range request.Txs {
		size += len(raw) + 8
		if app.store != nil && size > 64*1024*1024 || isDagBatch(raw) && (dagSeen || nativeSeen) || !isDagBatch(raw) && dagSeen {
			return &abci.ResponseProcessProposal{Status: abci.ResponseProcessProposal_REJECT}, nil
		}
		next, dagTx, err := app.applyTransaction(&state, execution, raw, request.Time.UnixNano(), false)
		if errors.Is(err, errDagHistoryUnavailable) {
			return nil, err
		}
		if err != nil {
			return &abci.ResponseProcessProposal{Status: abci.ResponseProcessProposal_REJECT}, nil
		}
		execution = next
		dagSeen = dagSeen || dagTx
		nativeSeen = nativeSeen || !dagTx
	}
	if app.store != nil {
		if err := app.store.prepareProposal(execution); err != nil {
			// Storage failure is a local unavailable node, not a verdict that
			// a deterministic-valid block is invalid at other validators.
			return nil, err
		}
	}
	return &abci.ResponseProcessProposal{Status: abci.ResponseProcessProposal_ACCEPT}, nil
}

func (app *Ledger) FinalizeBlock(ctx context.Context, request *abci.RequestFinalizeBlock) (*abci.ResponseFinalizeBlock, error) {
	if app.financial != nil {
		return app.financial.FinalizeBlock(ctx, request)
	}
	if app.segmented != nil {
		return app.segmented.FinalizeBlock(ctx, request)
	}
	app.mu.Lock()
	defer app.mu.Unlock()
	// An unsuccessful re-execution must never leave a previous candidate
	// available for Commit. Only this invocation can stage its exact result.
	app.staged = nil
	app.stagedDag = nil
	if request.Height != app.state.Height+1 || len(request.Txs) > MaxBlockTxs {
		return nil, errors.New("GG_FINALIZE_HEIGHT")
	}
	state := copyState(app.state)
	execution := app.dag
	dagSeen := false
	nativeSeen := false
	size := 0
	results := make([]*abci.ExecTxResult, len(request.Txs))
	for i, raw := range request.Txs {
		size += len(raw) + 8
		if app.store != nil && size > 64*1024*1024 || isDagBatch(raw) && (dagSeen || nativeSeen) || !isDagBatch(raw) && dagSeen {
			return nil, errors.New("GG_FINALIZE_DAG_LIMIT")
		}
		next, dagTx, err := app.applyTransaction(&state, execution, raw, request.Time.UnixNano(), false)
		if err != nil {
			return nil, errors.New("GG_FINALIZE_INVALID_TX")
		}
		execution = next
		dagSeen = dagSeen || dagTx
		nativeSeen = nativeSeen || !dagTx
		if dagTx {
			results[i] = &abci.ExecTxResult{Code: 0, GasWanted: 1, GasUsed: 1, Events: []abci.Event{{Type: "gg.dag_checkpoint", Attributes: []abci.EventAttribute{
				{Key: "blocks", Value: strconv.Itoa(execution.Commitment.Blocks), Index: false},
				{Key: "transactions", Value: strconv.FormatUint(execution.Commitment.Transactions, 10), Index: false}}}}}
			continue
		}
		envelope, _ := parseEnvelope(raw, app.genesis, app.anchor)
		results[i] = &abci.ExecTxResult{Code: 0, GasWanted: 1, GasUsed: 1, Events: []abci.Event{{Type: "gg.transfer", Attributes: []abci.EventAttribute{
			{Key: "sender", Value: envelope.Body.Sender, Index: true}, {Key: "recipient", Value: envelope.Body.Recipient, Index: true},
			{Key: "amount_atomic", Value: envelope.Body.Amount, Index: false}}}}}
	}
	var prepareErr error
	if app.store != nil {
		prepareErr = app.store.prepareFinalized(execution)
	}
	if prepareErr != nil {
		return nil, prepareErr
	}
	state.Height = request.Height
	sealState(&state)
	app.staged = &state
	app.stagedDag = execution
	hash, _ := hex.DecodeString(state.StateRoot)
	return &abci.ResponseFinalizeBlock{TxResults: results, AppHash: hash}, nil
}

func atomicPublic(path string, raw []byte) error {
	file, err := os.CreateTemp(filepath.Dir(path), ".gg-public-*")
	if err != nil {
		return err
	}
	name := file.Name()
	defer os.Remove(name)
	if err = file.Chmod(0600); err == nil {
		_, err = file.Write(raw)
	}
	if err == nil {
		err = file.Sync()
	}
	closeErr := file.Close()
	if err == nil {
		err = closeErr
	}
	if err != nil {
		return err
	}
	return os.Rename(name, path)
}

func (app *Ledger) Commit(ctx context.Context, request *abci.RequestCommit) (*abci.ResponseCommit, error) {
	if app.financial != nil {
		return app.financial.Commit(ctx, request)
	}
	if app.segmented != nil {
		return app.segmented.Commit(ctx, request)
	}
	app.mu.Lock()
	defer app.mu.Unlock()
	if app.staged == nil {
		return nil, errors.New("GG_COMMIT_WITHOUT_FINALIZE")
	}
	history := append(append([]State(nil), app.history...), copyState(*app.staged))
	if len(history) > HistoryLimit {
		history = history[len(history)-HistoryLimit:]
	}
	schema := "gg.native.public-history.v1"
	if app.store != nil {
		schema = "gg.native.public-history.v2"
	}
	raw := canonical(persisted{GenesisHash: app.anchor, History: history, Schema: schema})
	var err error
	if app.store != nil {
		if app.stagedDag == nil || app.staged.DAG == nil || !bytes.Equal(canonical(app.stagedDag.Commitment), canonical(app.staged.DAG)) {
			return nil, errors.New("GG_DAG_COMMIT_SELECTION")
		}
		err = app.store.commitExecution(raw, app.stagedDag)
	} else {
		err = atomicPublic(app.file, raw)
	}
	if err != nil {
		return nil, errors.New("GG_PUBLIC_STATE_SAVE")
	}
	app.state = copyState(*app.staged)
	app.history = history
	app.staged = nil
	app.dag = app.stagedDag
	if app.store != nil {
		app.dag = app.store.archiveExecution(app.dag)
	}
	app.stagedDag = nil
	return &abci.ResponseCommit{}, nil
}

func (app *Ledger) stateAt(height int64) (State, error) {
	if height == 0 {
		return copyState(app.state), nil
	}
	for _, state := range app.history {
		if state.Height == height {
			return copyState(state), nil
		}
	}
	return State{}, errors.New("GG_HEIGHT_NOT_RETAINED")
}

func (app *Ledger) Query(ctx context.Context, request *abci.RequestQuery) (*abci.ResponseQuery, error) {
	if request.Path == "/gg/protocol/local-history-status" {
		if ctx.Err() != nil || request.Height != 0 || len(request.Data) != 0 || !app.mu.TryRLock() {
			return &abci.ResponseQuery{Code: 3, Log: "GG_LOCAL_HISTORY_STATUS_UNAVAILABLE"}, nil
		}
		local, ok := app.financial.(interface {
			LocalHistoryStatus(context.Context) (map[string]any, int64, error)
		})
		app.mu.RUnlock()
		if !ok {
			return &abci.ResponseQuery{Code: 3, Log: "GG_LOCAL_HISTORY_STATUS_UNAVAILABLE"}, nil
		}
		payload, height, err := local.LocalHistoryStatus(ctx)
		if err != nil {
			return &abci.ResponseQuery{Code: 3, Log: "GG_LOCAL_HISTORY_STATUS_UNAVAILABLE"}, nil
		}
		return &abci.ResponseQuery{Code: 0, Value: canonical(payload), Height: height}, nil
	}

	app.mu.RLock()
	if strings.HasPrefix(request.Path, "/p2p/filter/") {
		allowed := membershipPeerAllowed(app.genesis.Membership, request.Path)
		app.mu.RUnlock()
		if allowed {
			return &abci.ResponseQuery{Code: 0}, nil
		}
		return &abci.ResponseQuery{Code: 1, Log: "GG_CONSENSUS_PEER_NOT_A_MEMBER"}, nil
	}
	state, err := app.stateAt(request.Height)
	genesis, anchor, store, currentHeight := app.genesis, app.anchor, app.store, app.state.Height
	execution, payloadSlots := app.dag, app.payloadSlots
	app.mu.RUnlock()
	if err != nil {
		return &abci.ResponseQuery{Code: 2, Log: err.Error(), Height: currentHeight}, nil
	}
	if ctx.Err() != nil {
		return &abci.ResponseQuery{Code: 2, Log: "GG_QUERY_CANCELLED", Height: state.Height}, nil
	}
	var payload any
	responseHeight := state.Height
	switch request.Path {
	case "/gg/state":
		payload = state
	case "/gg/genesis":
		payload = initialState(genesis, anchor)
		state = initialState(genesis, anchor)
	case "/gg/dag/commitment":
		if state.FinancialDAG != nil {
			payload = state.FinancialDAG
			break
		}
		if state.DAGSegmented != nil {
			payload = state.DAGSegmented
			break
		}
		if state.DAG == nil {
			return &abci.ResponseQuery{Code: 4, Log: "GG_DAG_NOT_CONFIGURED", Height: state.Height}, nil
		}
		payload = state.DAG
	case "/gg/financial-dag/commitment":
		if state.FinancialDAG == nil {
			return &abci.ResponseQuery{Code: 2, Log: "GG_FINANCIAL_DAG_NOT_CONFIGURED", Height: state.Height}, nil
		}
		payload = state.FinancialDAG
	case "/gg/financial-dag/receipt":
		var selector financialReceiptSelector
		if app.financial == nil || len(request.Data) > 192 || decodeStrict(request.Data, &selector) != nil || !bytes.Equal(request.Data, canonical(selector)) {
			return &abci.ResponseQuery{Code: 3, Log: "GG_FINANCIAL_RECEIPT_SELECTOR", Height: state.Height}, nil
		}
		payload, err = app.financial.Receipt(ctx, state, selector)
		if err != nil {
			return &abci.ResponseQuery{Code: 3, Log: "GG_FINANCIAL_RECEIPT_UNAVAILABLE", Height: state.Height}, nil
		}
	case "/gg/financial-dag/account-proof":
		var address string
		if app.financial == nil || !generalFinancialAccounts(genesis) || len(request.Data) > 66 || decodeStrict(request.Data, &address) != nil || !bytes.Equal(request.Data, canonical(address)) || !financialAccountAddress(address) {
			return &abci.ResponseQuery{Code: 3, Log: "GG_FINANCIAL_ACCOUNT_SELECTOR", Height: state.Height}, nil
		}
		payload, err = app.financial.Account(ctx, state, address)
		if err != nil {
			return &abci.ResponseQuery{Code: 3, Log: "GG_FINANCIAL_ACCOUNT_UNAVAILABLE", Height: state.Height}, nil
		}
	case "/gg/protocol/original-core-chunk":
		var selector financialOriginalCoreSelector
		if app.financial == nil || !publicFinancialProtocol(genesis) || len(request.Data) > 160 || decodeStrict(request.Data, &selector) != nil || !bytes.Equal(request.Data, canonical(selector)) {
			return &abci.ResponseQuery{Code: 3, Log: "GG_ORIGINAL_CORE_SELECTOR", Height: state.Height}, nil
		}
		payload, err = app.financial.OriginalCore(ctx, selector)
		if err != nil {
			return &abci.ResponseQuery{Code: 3, Log: "GG_ORIGINAL_CORE_UNAVAILABLE", Height: state.Height}, nil
		}
	case "/gg/protocol/committee-transition-state":
		var epoch string
		if app.financial == nil || !publicFinancialProtocol(genesis) || len(request.Data) > 22 || decodeStrict(request.Data, &epoch) != nil || !bytes.Equal(request.Data, canonical(epoch)) {
			return &abci.ResponseQuery{Code: 3, Log: "GG_COMMITTEE_STATE_SELECTOR", Height: state.Height}, nil
		}
		selected, ok := financialCounter(epoch)
		if !ok || selected == 0 {
			return &abci.ResponseQuery{Code: 3, Log: "GG_COMMITTEE_STATE_SELECTOR", Height: state.Height}, nil
		}
		decision, decisionErr := app.financial.CommitteeState(ctx, selected)
		if decisionErr != nil {
			return &abci.ResponseQuery{Code: 3, Log: "GG_COMMITTEE_STATE_UNAVAILABLE", Height: state.Height}, nil
		}
		payload, responseHeight = decision, decision.Height
	case "/gg/financial-dag/block-proof":
		var block string
		if app.financial == nil || !publicFinancialProtocol(genesis) || len(request.Data) > 66 || decodeStrict(request.Data, &block) != nil || !bytes.Equal(request.Data, canonical(block)) {
			return &abci.ResponseQuery{Code: 3, Log: "GG_FINANCIAL_BLOCK_SELECTOR", Height: state.Height}, nil
		}
		payload, err = app.financial.Block(ctx, state, block)
		if err != nil {
			return &abci.ResponseQuery{Code: 3, Log: "GG_FINANCIAL_BLOCK_UNAVAILABLE", Height: state.Height}, nil
		}
	case "/gg/financial-dag/recent-blocks":
		var selector financialRecentSelector
		if app.financial == nil || !publicFinancialProtocol(genesis) || len(request.Data) > 128 || decodeStrict(request.Data, &selector) != nil || !bytes.Equal(request.Data, canonical(selector)) {
			return &abci.ResponseQuery{Code: 3, Log: "GG_FINANCIAL_RECENT_SELECTOR", Height: state.Height}, nil
		}
		payload, err = app.financial.RecentBlocks(ctx, state, selector)
		if err != nil {
			return &abci.ResponseQuery{Code: 3, Log: "GG_FINANCIAL_RECENT_UNAVAILABLE", Height: state.Height}, nil
		}
	case "/gg/financial-dag/reward-proof":
		var selector protocolRewardSelector
		if app.financial == nil || !publicFinancialProtocol(genesis) || len(request.Data) > 128 || decodeStrict(request.Data, &selector) != nil || !bytes.Equal(request.Data, canonical(selector)) {
			return &abci.ResponseQuery{Code: 3, Log: "GG_FINANCIAL_REWARD_SELECTOR", Height: state.Height}, nil
		}
		payload, err = app.financial.Reward(ctx, state, selector)
		if err != nil {
			return &abci.ResponseQuery{Code: 3, Log: "GG_FINANCIAL_REWARD_UNAVAILABLE", Height: state.Height}, nil
		}
	case "/gg/financial-dag/registry-proof":
		var selector protocolRegistrySelector
		if app.financial == nil || !publicFinancialProtocol(genesis) || len(request.Data) > 160 || decodeStrict(request.Data, &selector) != nil || !bytes.Equal(request.Data, canonical(selector)) {
			return &abci.ResponseQuery{Code: 3, Log: "GG_FINANCIAL_REGISTRY_SELECTOR", Height: state.Height}, nil
		}
		payload, err = app.financial.Registry(ctx, state, selector)
		if err != nil {
			return &abci.ResponseQuery{Code: 3, Log: "GG_FINANCIAL_REGISTRY_UNAVAILABLE", Height: state.Height}, nil
		}
	case "/gg/financial-dag/source":
		if genesis.FinancialDAG == nil {
			return &abci.ResponseQuery{Code: 2, Log: "GG_FINANCIAL_DAG_NOT_CONFIGURED", Height: state.Height}, nil
		}
		payload = genesis.FinancialDAG
	case "/gg/financial-dag/producer-context":
		var selector struct {
			Producer int `json:"producer_index"`
		}
		if app.financial == nil || len(request.Data) > 64 || decodeStrict(request.Data, &selector) != nil || !bytes.Equal(request.Data, canonical(selector)) {
			return &abci.ResponseQuery{Code: 3, Log: "GG_FINANCIAL_PRODUCER_SELECTOR", Height: state.Height}, nil
		}
		payload, err = app.financial.ProducerContext(ctx, state, selector.Producer)
		if err != nil {
			return &abci.ResponseQuery{Code: 3, Log: "GG_FINANCIAL_PRODUCER_UNAVAILABLE", Height: state.Height}, nil
		}
	case "/gg/financial-dag/cut-transaction":
		if app.financial == nil || len(request.Data) != 0 {
			return &abci.ResponseQuery{Code: 2, Log: "GG_FINANCIAL_DAG_NOT_CONFIGURED", Height: state.Height}, nil
		}
		raw, cutHeight, cutErr := app.financial.CutTransaction(ctx, request.Height)
		if cutErr != nil {
			return &abci.ResponseQuery{Code: 2, Log: "GG_FINANCIAL_DAG_CUT_UNAVAILABLE", Height: cutHeight}, nil
		}
		payload = json.RawMessage(raw)
		responseHeight = cutHeight
	case "/gg/dag/history":
		if state.DAGSegmented == nil {
			return &abci.ResponseQuery{Code: 4, Log: "GG_DAG_SEGMENTED_NOT_CONFIGURED", Height: state.Height}, nil
		}
		payload = state.DAGSegmented
	case "/gg/dag/closed-page", "/gg/dag/closed-payload-chunk":
		if state.DAGSegmented == nil || app.segmented == nil || len(request.Data) > 256 {
			return &abci.ResponseQuery{Code: 3, Log: "GG_DAG_CLOSED_SELECTOR", Height: state.Height}, nil
		}
		payload, err = app.segmented.PublicProof(ctx, state, request.Path, string(request.Data), 0)
		if err != nil {
			return &abci.ResponseQuery{Code: 3, Log: err.Error(), Height: state.Height}, nil
		}
	case "/gg/dag/cut-proposal":
		if app.segmented == nil {
			return &abci.ResponseQuery{Code: 4, Log: "GG_DAG_SEGMENTED_NOT_CONFIGURED", Height: state.Height}, nil
		}
		value, err := app.segmented.CutTransaction(ctx, state.Height)
		if err != nil {
			return &abci.ResponseQuery{Code: 2, Log: "GG_DAG_CUT_PROPOSAL_UNAVAILABLE", Height: state.Height}, nil
		}
		payload = value
	case "/gg/dag/payload-chunk":
		var selector DagPayloadSelector
		if len(request.Data) > 192 || decodeStrict(request.Data, &selector) != nil || !bytes.Equal(request.Data, canonical(selector)) {
			return &abci.ResponseQuery{Code: 3, Log: "GG_DAG_PAYLOAD_SELECTOR", Height: state.Height}, nil
		}
		if state.DAGSegmented != nil && app.segmented != nil {
			payload, err = app.segmented.PublicProof(ctx, state, request.Path, string(request.Data), 0)
			if err != nil {
				return &abci.ResponseQuery{Code: 3, Log: err.Error(), Height: state.Height}, nil
			}
			break
		}
		if payloadSlots == nil {
			return &abci.ResponseQuery{Code: 4, Log: "GG_DAG_NOT_CONFIGURED", Height: state.Height}, nil
		}
		select {
		case payloadSlots <- struct{}{}:
			defer func() { <-payloadSlots }()
		default:
			return &abci.ResponseQuery{Code: 2, Log: "GG_DAG_PAYLOAD_BUSY", Height: state.Height}, nil
		}
		payload, err = dagPayloadChunkFor(ctx, execution, state, selector)
		if err != nil {
			return &abci.ResponseQuery{Code: 3, Log: err.Error(), Height: state.Height}, nil
		}
	case "/gg/dag/account-proof", "/gg/dag/block-proof", "/gg/dag/order-page", "/gg/dag/base-proof":
		if state.DAGSegmented != nil && app.segmented != nil {
			identifier, start := "", 0
			if request.Path == "/gg/dag/base-proof" {
				if len(request.Data) != 0 {
					return &abci.ResponseQuery{Code: 3, Log: "GG_DAG_BASE_PROOF_SELECTOR", Height: state.Height}, nil
				}
			} else if request.Path == "/gg/dag/order-page" {
				var cursor struct {
					Start int `json:"start"`
				}
				if len(request.Data) > 32 || decodeStrict(request.Data, &cursor) != nil || !bytes.Equal(request.Data, canonical(cursor)) || cursor.Start < 0 ||
					cursor.Start%DagOrderPageSize != 0 || cursor.Start > state.DAGSegmented.Active.Blocks || cursor.Start == state.DAGSegmented.Active.Blocks && cursor.Start != 0 {
					return &abci.ResponseQuery{Code: 3, Log: "GG_DAG_ORDER_PAGE_CURSOR", Height: state.Height}, nil
				}
				start = cursor.Start
			} else {
				identifier = string(request.Data)
				if len(request.Data) == 32 {
					identifier = hex.EncodeToString(request.Data)
				}
				if !canonicalFinancialHex(identifier) {
					return &abci.ResponseQuery{Code: 3, Log: "GG_DAG_PROOF_IDENTIFIER", Height: state.Height}, nil
				}
			}
			payload, err = app.segmented.PublicProof(ctx, state, request.Path, identifier, start)
			if err != nil {
				return &abci.ResponseQuery{Code: 2, Log: err.Error(), Height: state.Height}, nil
			}
			break
		}
		if state.DAG == nil || store == nil {
			return &abci.ResponseQuery{Code: 4, Log: "GG_DAG_NOT_CONFIGURED", Height: state.Height}, nil
		}
		if request.Path == "/gg/dag/base-proof" {
			return &abci.ResponseQuery{Code: 4, Log: "GG_DAG_SEGMENTED_NOT_CONFIGURED", Height: state.Height}, nil
		}
		identifier, start := "", 0
		if request.Path == "/gg/dag/order-page" {
			var cursor struct {
				Start int `json:"start"`
			}
			if len(request.Data) > 32 || decodeStrict(request.Data, &cursor) != nil || !bytes.Equal(request.Data, canonical(cursor)) ||
				cursor.Start < 0 || cursor.Start%DagOrderPageSize != 0 || cursor.Start > state.DAG.Blocks || cursor.Start == state.DAG.Blocks && cursor.Start != 0 {
				return &abci.ResponseQuery{Code: 3, Log: "GG_DAG_ORDER_PAGE_CURSOR", Height: state.Height}, nil
			}
			start = cursor.Start
		} else {
			if len(request.Data) != 32 && len(request.Data) != 64 {
				return &abci.ResponseQuery{Code: 3, Log: "GG_DAG_PROOF_IDENTIFIER", Height: state.Height}, nil
			}
			identifier = string(request.Data)
			if len(request.Data) == 32 {
				identifier = hex.EncodeToString(request.Data)
			}
			if !canonicalFinancialHex(identifier) {
				return &abci.ResponseQuery{Code: 3, Log: "GG_DAG_PROOF_IDENTIFIER", Height: state.Height}, nil
			}
		}
		payload, err = store.publicProof(ctx, state, request.Path, identifier, start)
		if err != nil {
			if err.Error() == "GG_DAG_UNKNOWN_ACCOUNT" || err.Error() == "GG_DAG_UNKNOWN_BLOCK" {
				return &abci.ResponseQuery{Code: 3, Log: err.Error(), Height: state.Height}, nil
			}
			return &abci.ResponseQuery{Code: 2, Log: "GG_DAG_PROOF_UNAVAILABLE", Height: state.Height}, nil
		}
	case "/gg/proof":
		address := string(request.Data)
		if len(request.Data) == 32 {
			address = hex.EncodeToString(request.Data)
		}
		index := -1
		for i, account := range state.Accounts {
			if account.Address == address {
				index = i
			}
		}
		if index < 0 {
			return &abci.ResponseQuery{Code: 3, Log: "GG_UNKNOWN_ACCOUNT", Height: state.Height}, nil
		}
		levels := merkleLevels(state.Accounts)
		cursor := index
		path := []PathItem{}
		for _, level := range levels[:len(levels)-1] {
			side := "right"
			if cursor%2 == 1 {
				side = "left"
			}
			sibling := level[cursor^1]
			path = append(path, PathItem{Hash: hex.EncodeToString(sibling[:]), Side: side})
			cursor /= 2
		}
		payload = Proof{AccountRoot: state.AccountRoot, ChainID: state.ChainID, Commitment: commitmentFor(state), GenesisHash: state.GenesisHash, Height: state.Height, Leaf: state.Accounts[index], Path: path, Schema: "gg.native.proof.v1", StateRoot: state.StateRoot}
	default:
		return &abci.ResponseQuery{Code: 4, Log: "GG_QUERY_PATH", Height: state.Height}, nil
	}
	return &abci.ResponseQuery{Code: 0, Value: canonical(payload), Height: responseHeight}, nil
}

func (app *Ledger) String() string { return fmt.Sprintf("GG Ledger height %d", app.state.Height) }
