package main

// Ordered monetary execution kernel. This does not activate a network rule,
// authenticate a DAG producer, certify an order, create mining rewards, or
// persist a receipt. A future versioned SDK application must bind this exact
// context/result into committed state before clients may claim finality.
import (
	"context"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"errors"
	"runtime"
	"sync"
	"sync/atomic"
)

const financialDomain = "GG-ORDERED-MONETARY-v1\x00"
const financialMaxTransactions = 50000
const financialMaxInputBytes = 32 * 1024 * 1024

type financialExecutionContext struct {
	BlockHash  string `json:"block_hash"`
	Checkpoint uint64 `json:"checkpoint,string"`
	Epoch      uint64 `json:"epoch,string"`
	Genesis    string `json:"genesis_hash"`
	OrderIndex uint64 `json:"order_index,string"`
	Schema     string `json:"schema"`
	SourceHash string `json:"source_hash"`
}

func (binding financialExecutionContext) valid(anchor string) bool {
	return binding.Schema == "gg.financial.execution-context.v1" && binding.Genesis == anchor &&
		pubPattern.MatchString(anchor) && pubPattern.MatchString(binding.BlockHash) && pubPattern.MatchString(binding.SourceHash) &&
		binding.Epoch > 0 && binding.Epoch <= dagSegmentCounterMax && binding.Checkpoint > 0 && binding.Checkpoint <= dagSegmentCounterMax &&
		binding.OrderIndex > 0 && binding.OrderIndex <= dagSegmentCounterMax
}

type financialReceipt struct {
	AccountRootAfter  string `json:"account_root_after,omitempty"`
	AccountRootBefore string `json:"account_root_before,omitempty"`
	ContextHash       string `json:"context_hash"`
	Fee               string `json:"fee_atomic,omitempty"`
	Index             int    `json:"index"`
	Outcome           string `json:"outcome"`
	Schema            string `json:"schema"`
	TransactionID     string `json:"transaction_id"`
}

type financialSummary struct {
	AccountRootAfter  string `json:"account_root_after"`
	AccountRootBefore string `json:"account_root_before"`
	Applied           int    `json:"applied"`
	ContextHash       string `json:"context_hash"`
	Fees              string `json:"fees_atomic,omitempty"`
	InputHash         string `json:"input_hash"`
	ReceiptsRoot      string `json:"receipts_root"`
	Rejected          int    `json:"rejected"`
	Schema            string `json:"schema"`
	Transactions      int    `json:"transactions"`
}

type financialExecutionResult struct {
	Receipts []financialReceipt
	State    State
	Summary  financialSummary
}

// A composed DAG application owns its surrounding metadata separately. Its
// account transition must not temporarily claim that old DAG metadata commits
// the new account root. This monetary view is attached atomically by the caller.
type financialMoneyState struct {
	AccountRoot string
	Accounts    []Account
	GenesisHash string
	Protocol    *financialProtocolExecution
	Tree        *financialAccountTree
}

type financialMoneyResult struct {
	Money    financialMoneyState
	Receipts []financialReceipt
	Summary  financialSummary
}

type financialReceiptProof struct {
	Leaf financialReceipt `json:"leaf"`
	Path []PathItem       `json:"path"`
}

func financialContextHash(binding financialExecutionContext) string {
	return hashHex(append([]byte(financialDomain+"CONTEXT\x00"), canonical(binding)...))
}

func financialIntentID(raw []byte) string {
	return hashHex(append([]byte(financialDomain+"INTENT\x00"), raw...))
}

// Inputs must remain immutable until the joined workers return. Every valid
// envelope is parsed and strictly signature-verified once; no result cache.
func financialEnvelopes(ctx context.Context, inputs [][]byte, genesis Genesis, anchor string) ([]Envelope, error) {
	return financialEnvelopesWithDecoded(ctx, inputs, genesis, anchor, nil)
}

func financialEnvelopesWithDecoded(ctx context.Context, inputs [][]byte, genesis Genesis, anchor string, decoded *financialDecodedPayments) ([]Envelope, error) {
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	if len(inputs) > financialMaxTransactions {
		return nil, errors.New("GG_FINANCIAL_BATCH_LIMIT")
	}
	remaining := financialMaxInputBytes
	for _, raw := range inputs {
		if len(raw) == 0 || len(raw) > MaxTxBytes || len(raw) > remaining {
			return nil, errors.New("GG_FINANCIAL_BATCH_LIMIT")
		}
		remaining -= len(raw)
	}
	if decoded != nil && len(decoded.values) != len(inputs) {
		return nil, errors.New("GG_FINANCIAL_BATCH_INVALID_TRANSACTION")
	}
	envelopes := make([]Envelope, len(inputs))
	var next atomic.Int64
	var failed atomic.Bool
	worker := func() {
		for !failed.Load() && ctx.Err() == nil {
			index := int(next.Add(1) - 1)
			if index >= len(inputs) {
				return
			}
			var value Envelope
			var err error
			if decoded == nil {
				value, err = parseEnvelope(inputs[index], genesis, anchor)
			} else {
				value, err = decoded.envelope(index, inputs[index])
				if err == nil {
					value, err = validateEnvelopeValue(value, genesis, anchor)
				}
			}
			if err != nil {
				failed.Store(true)
				return
			}
			envelopes[index] = value
		}
	}
	workers := dagTxSignatureWorkers(len(inputs), runtime.GOMAXPROCS(0))
	if workers == 1 {
		worker()
	} else {
		var group sync.WaitGroup
		group.Add(workers)
		for i := 0; i < workers; i++ {
			go func() { defer group.Done(); worker() }()
		}
		group.Wait()
	}
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	if failed.Load() {
		return nil, errors.New("GG_FINANCIAL_BATCH_INVALID_TRANSACTION")
	}
	return envelopes, nil
}

func financialInputHash(contextHash string, inputs [][]byte) string {
	hash := sha256.New()
	hash.Write([]byte(financialDomain + "INPUT\x00" + contextHash))
	var size [8]byte
	binary.BigEndian.PutUint64(size[:], uint64(len(inputs)))
	hash.Write(size[:])
	for _, raw := range inputs {
		binary.BigEndian.PutUint64(size[:], uint64(len(raw)))
		hash.Write(size[:])
		hash.Write(raw)
	}
	return hex.EncodeToString(hash.Sum(nil))
}

// Invalid encoding/signatures reject the entire input without applying a
// payment. State-dependent conflicts instead receive deterministic receipts in
// the supplied order, so an authentic competing payment cannot freeze a DAG
// producer's history. The caller still has to authenticate and certify order.
func executeFinancialTransactions(ctx context.Context, genesis Genesis, anchor string, state State, binding financialExecutionContext, inputs [][]byte) (financialExecutionResult, error) {
	if ctx.Err() != nil {
		return financialExecutionResult{}, ctx.Err()
	}
	if !binding.valid(anchor) || validateGenesis(genesis, anchor) != nil || validateState(state, genesis, anchor) != nil {
		return financialExecutionResult{}, errors.New("GG_FINANCIAL_EXECUTION_CONTEXT")
	}
	if generalFinancialAccounts(genesis) {
		return financialExecutionResult{}, errors.New("GG_FINANCIAL_ACCOUNT_TREE_REQUIRED")
	}
	result, err := executeFinancialMoney(ctx, genesis, anchor, financialMoneyState{AccountRoot: state.AccountRoot, Accounts: state.Accounts, GenesisHash: anchor}, binding, inputs)
	if err != nil {
		return financialExecutionResult{}, err
	}
	next := copyState(state)
	next.Accounts = result.Money.Accounts
	sealState(&next)
	if validateState(next, genesis, anchor) != nil {
		return financialExecutionResult{}, errors.New("GG_FINANCIAL_EXECUTION_STATE")
	}
	if ctx.Err() != nil {
		return financialExecutionResult{}, ctx.Err()
	}
	return financialExecutionResult{State: next, Receipts: result.Receipts, Summary: result.Summary}, nil
}

func executeFinancialMoney(ctx context.Context, genesis Genesis, anchor string, money financialMoneyState, binding financialExecutionContext, inputs [][]byte) (financialMoneyResult, error) {
	return executeFinancialMoneyWithDecoded(ctx, genesis, anchor, money, binding, inputs, nil)
}

func executeFinancialMoneyWithDecoded(ctx context.Context, genesis Genesis, anchor string, money financialMoneyState, binding financialExecutionContext, inputs [][]byte, decoded *financialDecodedPayments) (financialMoneyResult, error) {
	if ctx.Err() != nil {
		return financialMoneyResult{}, ctx.Err()
	}
	if !binding.valid(anchor) || validateGenesis(genesis, anchor) != nil || validateFinancialMoney(money, genesis, anchor) != nil {
		return financialMoneyResult{}, errors.New("GG_FINANCIAL_EXECUTION_CONTEXT")
	}
	if generalFinancialAccounts(genesis) {
		return executeFinancialAccountMoneyWithDecoded(ctx, genesis, anchor, money, binding, inputs, decoded)
	}
	envelopes, err := financialEnvelopesWithDecoded(ctx, inputs, genesis, anchor, decoded)
	if err != nil {
		return financialMoneyResult{}, err
	}
	next := State{Accounts: append([]Account(nil), money.Accounts...), AccountRoot: money.AccountRoot}
	contextHash := financialContextHash(binding)
	result := financialMoneyResult{Receipts: make([]financialReceipt, 0, len(inputs))}
	result.Summary = financialSummary{AccountRootBefore: money.AccountRoot, ContextHash: contextHash,
		InputHash: financialInputHash(contextHash, inputs), Schema: "gg.financial.summary.v1", Transactions: len(inputs)}
	accounts := make(map[string]int, len(next.Accounts))
	for index, account := range next.Accounts {
		accounts[account.Address] = index
	}
	for index, envelope := range envelopes {
		if ctx.Err() != nil {
			return financialMoneyResult{}, ctx.Err()
		}
		before := next.AccountRoot
		source, sourceExists := accounts[envelope.Body.Sender]
		if !sourceExists {
			return financialMoneyResult{}, errors.New("GG_FINANCIAL_EXECUTION_ACCOUNT")
		}
		outcome := "APPLIED"
		switch {
		case envelope.Body.Nonce != next.Accounts[source].Nonce:
			outcome = "REJECTED_NONCE"
		case next.Accounts[source].Nonce == ^uint64(0):
			outcome = "REJECTED_NONCE_EXHAUSTED"
		default:
			if err := applyEnvelope(&next, envelope, false); err != nil {
				if err.Error() != "GG_TX_FUNDS" {
					return financialMoneyResult{}, errors.New("GG_FINANCIAL_EXECUTION_TRANSITION")
				}
				outcome = "REJECTED_FUNDS"
			} else {
				next.AccountRoot = nativeAccountRoot(next.Accounts)
			}
		}
		if outcome == "APPLIED" {
			result.Summary.Applied++
		} else {
			result.Summary.Rejected++
		}
		result.Receipts = append(result.Receipts, financialReceipt{AccountRootAfter: next.AccountRoot, AccountRootBefore: before,
			ContextHash: contextHash, Index: index, Outcome: outcome, Schema: "gg.financial.receipt.v1", TransactionID: financialIntentID(inputs[index])})
	}
	if ctx.Err() != nil {
		return financialMoneyResult{}, ctx.Err()
	}
	if validateNativeAccountState(next.Accounts, genesis, next.AccountRoot) != nil {
		return financialMoneyResult{}, errors.New("GG_FINANCIAL_EXECUTION_STATE")
	}
	result.Money = financialMoneyState{AccountRoot: next.AccountRoot, Accounts: next.Accounts, GenesisHash: anchor}
	result.Summary.AccountRootAfter = next.AccountRoot
	result.Summary.ReceiptsRoot = sealFinancialReceiptRoot(result.Summary, financialReceiptTreeRoot(result.Receipts))
	if ctx.Err() != nil {
		return financialMoneyResult{}, ctx.Err()
	}
	return result, nil
}

func financialReceiptLevels(receipts []financialReceipt) [][][32]byte {
	leaves := make([][32]byte, len(receipts))
	for index, receipt := range receipts {
		leaves[index] = sha256.Sum256(append([]byte(financialDomain+"RECEIPT\x00"), canonical(receipt)...))
	}
	levels := [][][32]byte{leaves}
	for len(levels[len(levels)-1]) > 1 {
		previous := levels[len(levels)-1]
		next := make([][32]byte, (len(previous)+1)/2)
		for index := range next {
			left, right := previous[index*2], previous[index*2]
			if index*2+1 < len(previous) {
				right = previous[index*2+1]
			}
			next[index] = financialReceiptJoin(left, right)
		}
		levels = append(levels, next)
	}
	return levels
}

func financialReceiptJoin(left, right [32]byte) [32]byte {
	raw := append([]byte(financialDomain+"RECEIPT-NODE\x00"), left[:]...)
	return sha256.Sum256(append(raw, right[:]...))
}

func financialReceiptTreeRoot(receipts []financialReceipt) [32]byte {
	if len(receipts) == 0 {
		return sha256.Sum256([]byte(financialDomain + "RECEIPT-EMPTY\x00"))
	}
	levels := financialReceiptLevels(receipts)
	return levels[len(levels)-1][0]
}

// Seal count, outcome totals, input/context and both account roots as well as
// the receipt tree. Duplicate-last padding alone cannot authenticate the count.
func sealFinancialReceiptRoot(summary financialSummary, tree [32]byte) string {
	summary.ReceiptsRoot = ""
	raw := append([]byte(financialDomain+"RECEIPT-COMMITMENT\x00"), canonical(summary)...)
	raw = append(raw, 0)
	return hashHex(append(raw, tree[:]...))
}

func makeFinancialReceiptProof(receipts []financialReceipt, index int) (financialReceiptProof, error) {
	if len(receipts) > financialMaxTransactions || index < 0 || index >= len(receipts) {
		return financialReceiptProof{}, errors.New("GG_FINANCIAL_RECEIPT_SELECTOR")
	}
	proof := financialReceiptProof{Leaf: receipts[index], Path: []PathItem{}}
	levels := financialReceiptLevels(receipts)
	position := index
	for _, row := range levels[:len(levels)-1] {
		sibling, side := position^1, "right"
		if position%2 == 1 {
			side = "left"
		}
		if sibling >= len(row) {
			sibling = position
		}
		proof.Path = append(proof.Path, PathItem{Hash: hex.EncodeToString(row[sibling][:]), Side: side})
		position /= 2
	}
	return proof, nil
}

// Inclusion against the supplied summary only: the caller must independently
// authenticate that summary in SDK state. This function asserts no finality.
func checkFinancialReceiptInclusion(binding financialExecutionContext, summary financialSummary, proof financialReceiptProof) bool {
	return checkFinancialReceiptInclusionVersion(binding, summary, proof, false)
}
func checkFinancialReceiptInclusionVersion(binding financialExecutionContext, summary financialSummary, proof financialReceiptProof, general bool, protocolMode ...bool) bool {
	leaf := proof.Leaf
	summarySchema, receiptSchema := financialReceiptSchemas(general)
	public := len(protocolMode) == 1 && protocolMode[0]
	if len(protocolMode) > 1 {
		return false
	}
	if public {
		summarySchema, receiptSchema = "gg.financial.summary.v3", "gg.financial.receipt.v3"
	}
	if public {
		fees, fok := economicAmount(summary.Fees)
		charged, cok := economicAmount(leaf.Fee)
		if !fok || !cok || charged > fees || leaf.Outcome != "APPLIED" && charged != 0 {
			return false
		}
	} else if summary.Fees != "" || leaf.Fee != "" {
		return false
	}
	if !binding.valid(binding.Genesis) || summary.Schema != summarySchema || summary.ContextHash != financialContextHash(binding) ||
		summary.Transactions < 1 || summary.Transactions > financialMaxTransactions || summary.Applied < 0 || summary.Rejected < 0 ||
		summary.Applied > summary.Transactions || summary.Rejected != summary.Transactions-summary.Applied ||
		!pubPattern.MatchString(summary.AccountRootBefore) || !pubPattern.MatchString(summary.AccountRootAfter) ||
		!pubPattern.MatchString(summary.InputHash) || !pubPattern.MatchString(summary.ReceiptsRoot) ||
		leaf.Schema != receiptSchema || leaf.ContextHash != summary.ContextHash ||
		leaf.Index < 0 || leaf.Index >= summary.Transactions || !pubPattern.MatchString(leaf.TransactionID) ||
		(!public && (!pubPattern.MatchString(leaf.AccountRootBefore) || !pubPattern.MatchString(leaf.AccountRootAfter))) || public && (leaf.AccountRootBefore != "" || leaf.AccountRootAfter != "") {
		return false
	}
	if !public && (leaf.Index == 0 && leaf.AccountRootBefore != summary.AccountRootBefore ||
		leaf.Index == summary.Transactions-1 && leaf.AccountRootAfter != summary.AccountRootAfter) {
		return false
	}
	switch leaf.Outcome {
	case "APPLIED":
		if !public && leaf.AccountRootBefore == leaf.AccountRootAfter || summary.Applied == 0 {
			return false
		}
	case "REJECTED_NONCE", "REJECTED_NONCE_EXHAUSTED", "REJECTED_FUNDS":
		if leaf.AccountRootBefore != leaf.AccountRootAfter || summary.Rejected == 0 {
			return false
		}
	case "REJECTED_ACCOUNT_LIMIT":
		if !general || leaf.AccountRootBefore != leaf.AccountRootAfter || summary.Rejected == 0 {
			return false
		}
	case "REJECTED_FEE_LIMIT", "REJECTED_OPERATIONAL_KEY":
		if !public || leaf.AccountRootBefore != leaf.AccountRootAfter || summary.Rejected == 0 {
			return false
		}
	default:
		return false
	}
	value := sha256.Sum256(append([]byte(financialDomain+"RECEIPT\x00"), canonical(leaf)...))
	position, width, depth := leaf.Index, summary.Transactions, 0
	for width > 1 {
		if depth >= len(proof.Path) {
			return false
		}
		item := proof.Path[depth]
		if !pubPattern.MatchString(item.Hash) {
			return false
		}
		raw, _ := hex.DecodeString(item.Hash)
		var sibling [32]byte
		copy(sibling[:], raw)
		if position%2 == 1 {
			if item.Side != "left" {
				return false
			}
			value = financialReceiptJoin(sibling, value)
		} else {
			if item.Side != "right" || position+1 >= width && sibling != value {
				return false
			}
			value = financialReceiptJoin(value, sibling)
		}
		position, width, depth = position/2, (width+1)/2, depth+1
	}
	return depth == len(proof.Path) && sealFinancialReceiptRoot(summary, value) == summary.ReceiptsRoot
}
