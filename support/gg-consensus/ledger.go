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
	"io"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
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
	Accounts     []string `json:"accounts"`
	ChainID      string   `json:"chain_id"`
	Decimals     int      `json:"decimals"`
	GenesisTime  int64    `json:"genesis_time_unix"`
	Schema       string   `json:"schema"`
	SupplyAtomic string   `json:"supply_atomic"`
	Symbol       string   `json:"symbol"`
	Validators   []string `json:"validators"`
}

type Body struct {
	Amount      string `json:"amount_atomic"`
	ChainID     string `json:"chain_id"`
	GenesisHash string `json:"genesis_hash"`
	Nonce       uint64 `json:"nonce"`
	Recipient   string `json:"recipient"`
	Sender      string `json:"sender"`
	Version     int    `json:"version"`
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
	AccountRoot  string `json:"account_root"`
	ChainID      string `json:"chain_id"`
	GenesisHash  string `json:"genesis_hash"`
	Schema       string `json:"schema"`
	SupplyAtomic string `json:"supply_atomic"`
}

type State struct {
	AccountRoot  string    `json:"account_root"`
	Accounts     []Account `json:"accounts"`
	ChainID      string    `json:"chain_id"`
	Decimals     int       `json:"decimals"`
	GenesisHash  string    `json:"genesis_hash"`
	Height       int64     `json:"height"`
	Schema       string    `json:"schema"`
	StateRoot    string    `json:"state_root"`
	SupplyAtomic string    `json:"supply_atomic"`
	Symbol       string    `json:"symbol"`
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

// Duplicate object keys are rejected before decoding typed public data.
func checkJSONValue(decoder *json.Decoder, depth int) error {
	if depth > 12 {
		return errors.New("GG_JSON_DEPTH")
	}
	token, err := decoder.Token()
	if err != nil {
		return err
	}
	delimiter, container := token.(json.Delim)
	if !container {
		return nil
	}
	switch delimiter {
	case '{':
		seen := map[string]bool{}
		for decoder.More() {
			key, err := decoder.Token()
			if err != nil {
				return err
			}
			name, ok := key.(string)
			if !ok || seen[name] {
				return errors.New("GG_JSON_DUPLICATE_KEY")
			}
			seen[name] = true
			if err := checkJSONValue(decoder, depth+1); err != nil {
				return err
			}
		}
	case '[':
		for decoder.More() {
			if err := checkJSONValue(decoder, depth+1); err != nil {
				return err
			}
		}
	default:
		return errors.New("GG_JSON_DELIMITER")
	}
	_, err = decoder.Token()
	return err
}

func decodeStrict(data []byte, target any) error {
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.UseNumber()
	if err := checkJSONValue(decoder, 0); err != nil {
		return err
	}
	if _, err := decoder.Token(); err != io.EOF {
		return errors.New("GG_JSON_TRAILING_DATA")
	}
	decoder = json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	return decoder.Decode(target)
}

func validateGenesis(genesis Genesis, anchor string) error {
	if genesis.Schema != "gg.native.genesis.v1" || !chainPattern.MatchString(genesis.ChainID) ||
		genesis.Decimals != 6 || genesis.SupplyAtomic != strconv.FormatUint(Supply, 10) ||
		genesis.Symbol != "GG-NET-TEST" || genesis.GenesisTime <= 0 || len(genesis.Accounts) != 4 || len(genesis.Validators) != 4 ||
		anchor != hashHex(canonical(genesis)) {
		return errors.New("GG_GENESIS_INVALID")
	}
	for _, entries := range [][]string{genesis.Accounts, genesis.Validators} {
		seen := map[string]bool{}
		for _, entry := range entries {
			if !pubPattern.MatchString(entry) || seen[entry] {
				return errors.New("GG_GENESIS_IDENTITIES")
			}
			seen[entry] = true
		}
	}
	return nil
}

func initialState(genesis Genesis, anchor string) State {
	addresses := append([]string(nil), genesis.Accounts...)
	sort.Strings(addresses)
	state := State{ChainID: genesis.ChainID, GenesisHash: anchor, Decimals: 6, Height: 0, Schema: "gg.native.state.v1", SupplyAtomic: genesis.SupplyAtomic, Symbol: genesis.Symbol}
	for _, address := range addresses {
		state.Accounts = append(state.Accounts, Account{Address: address, Balance: strconv.FormatUint(Supply/4, 10)})
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
	return Commitment{AccountRoot: state.AccountRoot, ChainID: state.ChainID, GenesisHash: state.GenesisHash, Schema: "gg.native.commitment.v1", SupplyAtomic: state.SupplyAtomic}
}

func sealState(state *State) {
	levels := merkleLevels(state.Accounts)
	root := levels[len(levels)-1][0]
	state.AccountRoot = hex.EncodeToString(root[:])
	state.StateRoot = hashHex(canonical(commitmentFor(*state)))
}

func copyState(state State) State {
	state.Accounts = append([]Account(nil), state.Accounts...)
	return state
}

func validateState(state State, genesis Genesis, anchor string) error {
	if state.Schema != "gg.native.state.v1" || state.ChainID != genesis.ChainID || state.GenesisHash != anchor || state.Height < 0 ||
		state.Decimals != 6 || state.Symbol != genesis.Symbol || state.SupplyAtomic != genesis.SupplyAtomic || len(state.Accounts) != 4 {
		return errors.New("GG_STATE_INVALID")
	}
	expected := append([]string(nil), genesis.Accounts...)
	sort.Strings(expected)
	total := uint64(0)
	for i, account := range state.Accounts {
		balance, err := strconv.ParseUint(account.Balance, 10, 64)
		if err != nil || !uintPattern.MatchString(account.Balance) || account.Address != expected[i] || balance > Supply || total > Supply-balance {
			return errors.New("GG_STATE_ACCOUNTS")
		}
		total += balance
	}
	if total != Supply {
		return errors.New("GG_STATE_SUPPLY")
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
	body := envelope.Body
	if body.Version != 1 || body.ChainID != genesis.ChainID || body.GenesisHash != anchor || body.Sender == body.Recipient ||
		!pubPattern.MatchString(body.Sender) || !pubPattern.MatchString(body.Recipient) || !uintPattern.MatchString(body.Amount) {
		return envelope, errors.New("GG_TX_CONTEXT")
	}
	sender, recipient := false, false
	for _, address := range genesis.Accounts {
		sender = sender || address == body.Sender
		recipient = recipient || address == body.Recipient
	}
	if !sender || !recipient {
		return envelope, errors.New("GG_TX_ACCOUNT")
	}
	amount, err := strconv.ParseUint(body.Amount, 10, 64)
	if err != nil || amount == 0 || amount > Supply {
		return envelope, errors.New("GG_TX_AMOUNT")
	}
	public, _ := hex.DecodeString(body.Sender)
	signature, err := hex.DecodeString(envelope.Signature)
	if err != nil || len(signature) != ed25519.SignatureSize || envelope.Signature != hex.EncodeToString(signature) || !ed25519.Verify(public, canonical(body), signature) {
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
	mu      sync.RWMutex
	genesis Genesis
	anchor  string
	state   State
	staged  *State
	history []State
	file    string
}

func newLedger(genesis Genesis, anchor, root string) (*Ledger, error) {
	if err := validateGenesis(genesis, anchor); err != nil {
		return nil, err
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
	return &abci.ResponseInfo{Data: "GG native four-validator test ledger", Version: "gg-native-test-v1", AppVersion: 1, LastBlockHeight: app.state.Height, LastBlockAppHash: hash}, nil
}

func (app *Ledger) InitChain(context.Context, *abci.RequestInitChain) (*abci.ResponseInitChain, error) {
	app.mu.RLock()
	defer app.mu.RUnlock()
	hash, _ := hex.DecodeString(app.state.StateRoot)
	return &abci.ResponseInitChain{AppHash: hash}, nil
}

func (app *Ledger) CheckTx(_ context.Context, request *abci.RequestCheckTx) (*abci.ResponseCheckTx, error) {
	app.mu.RLock()
	defer app.mu.RUnlock()
	envelope, err := parseEnvelope(request.Tx, app.genesis, app.anchor)
	if err == nil {
		state := copyState(app.state)
		err = applyEnvelope(&state, envelope, true)
	}
	if err != nil {
		return &abci.ResponseCheckTx{Code: 1, Log: err.Error(), Codespace: "gg"}, nil
	}
	return &abci.ResponseCheckTx{Code: 0, GasWanted: 1}, nil
}

func (app *Ledger) PrepareProposal(_ context.Context, request *abci.RequestPrepareProposal) (*abci.ResponsePrepareProposal, error) {
	app.mu.RLock()
	defer app.mu.RUnlock()
	state := copyState(app.state)
	accepted := [][]byte{}
	size := int64(0)
	for _, raw := range request.Txs {
		if len(accepted) >= MaxBlockTxs || size+int64(len(raw))+8 > request.MaxTxBytes {
			break
		}
		envelope, err := parseEnvelope(raw, app.genesis, app.anchor)
		if err != nil || applyEnvelope(&state, envelope, false) != nil {
			continue
		}
		accepted = append(accepted, raw)
		size += int64(len(raw)) + 8
	}
	return &abci.ResponsePrepareProposal{Txs: accepted}, nil
}

func (app *Ledger) ProcessProposal(_ context.Context, request *abci.RequestProcessProposal) (*abci.ResponseProcessProposal, error) {
	app.mu.RLock()
	defer app.mu.RUnlock()
	state := copyState(app.state)
	if len(request.Txs) > MaxBlockTxs {
		return &abci.ResponseProcessProposal{Status: abci.ResponseProcessProposal_REJECT}, nil
	}
	for _, raw := range request.Txs {
		envelope, err := parseEnvelope(raw, app.genesis, app.anchor)
		if err != nil || applyEnvelope(&state, envelope, false) != nil {
			return &abci.ResponseProcessProposal{Status: abci.ResponseProcessProposal_REJECT}, nil
		}
	}
	return &abci.ResponseProcessProposal{Status: abci.ResponseProcessProposal_ACCEPT}, nil
}

func (app *Ledger) FinalizeBlock(_ context.Context, request *abci.RequestFinalizeBlock) (*abci.ResponseFinalizeBlock, error) {
	app.mu.Lock()
	defer app.mu.Unlock()
	if request.Height != app.state.Height+1 || len(request.Txs) > MaxBlockTxs {
		return nil, errors.New("GG_FINALIZE_HEIGHT")
	}
	state := copyState(app.state)
	results := make([]*abci.ExecTxResult, len(request.Txs))
	for i, raw := range request.Txs {
		envelope, err := parseEnvelope(raw, app.genesis, app.anchor)
		if err != nil || applyEnvelope(&state, envelope, false) != nil {
			return nil, errors.New("GG_FINALIZE_INVALID_TX")
		}
		results[i] = &abci.ExecTxResult{Code: 0, GasWanted: 1, GasUsed: 1, Events: []abci.Event{{Type: "gg.transfer", Attributes: []abci.EventAttribute{
			{Key: "sender", Value: envelope.Body.Sender, Index: true}, {Key: "recipient", Value: envelope.Body.Recipient, Index: true},
			{Key: "amount_atomic", Value: envelope.Body.Amount, Index: false}}}}}
	}
	state.Height = request.Height
	sealState(&state)
	app.staged = &state
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

func (app *Ledger) Commit(context.Context, *abci.RequestCommit) (*abci.ResponseCommit, error) {
	app.mu.Lock()
	defer app.mu.Unlock()
	if app.staged == nil {
		return nil, errors.New("GG_COMMIT_WITHOUT_FINALIZE")
	}
	history := append(append([]State(nil), app.history...), copyState(*app.staged))
	if len(history) > HistoryLimit {
		history = history[len(history)-HistoryLimit:]
	}
	if err := atomicPublic(app.file, canonical(persisted{GenesisHash: app.anchor, History: history, Schema: "gg.native.public-history.v1"})); err != nil {
		return nil, errors.New("GG_PUBLIC_STATE_SAVE")
	}
	app.state = copyState(*app.staged)
	app.history = history
	app.staged = nil
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

func (app *Ledger) Query(_ context.Context, request *abci.RequestQuery) (*abci.ResponseQuery, error) {
	app.mu.RLock()
	defer app.mu.RUnlock()
	state, err := app.stateAt(request.Height)
	if err != nil {
		return &abci.ResponseQuery{Code: 2, Log: err.Error(), Height: app.state.Height}, nil
	}
	var payload any
	switch request.Path {
	case "/gg/state":
		payload = state
	case "/gg/genesis":
		payload = initialState(app.genesis, app.anchor)
		state = initialState(app.genesis, app.anchor)
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
	return &abci.ResponseQuery{Code: 0, Value: canonical(payload), Height: state.Height}, nil
}

func (app *Ledger) String() string { return fmt.Sprintf("GG Ledger height %d", app.state.Height) }
