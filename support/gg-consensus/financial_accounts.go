package main

// Immutable account dictionary selected only by explicit general-account
// genesis/source versions. This kernel authenticates state and pure transfers;
// the composed application owns signatures, SDK selection and atomic durable
// publication. Existing four-account roots and execution are untouched.
import (
	"bytes"
	"context"
	"encoding/hex"
	"errors"
	"strconv"
)

const financialAccountPathMax = 64
const financialAccountNodeMaxBytes = 2048
const financialAccountStageMaxNodes = 262144

var errFinancialAccount = errors.New("GG_FINANCIAL_ACCOUNT_STATE_UNAVAILABLE")

type financialAccountRules struct {
	Genesis     string `json:"genesis_hash"`
	MaxAccounts uint64 `json:"max_accounts,string"`
	MaxTotal    uint64 `json:"max_total_atomic,string"`
	Schema      string `json:"schema"`
}

func (rules financialAccountRules) valid() bool {
	return rules.Schema == "gg.financial.account-rules.v1" && canonicalFinancialHex(rules.Genesis) &&
		rules.MaxAccounts > 0 && rules.MaxAccounts <= 1<<32 && rules.MaxTotal > 0
}
func (rules financialAccountRules) hash() string {
	return hashHex(append([]byte("GG-FINANCIAL-ACCOUNT-RULES-v1\x00"), canonical(rules)...))
}

// All child metadata is authenticated by its parent's hash. The reader must
// check that the referenced child's actual body has exactly this metadata.
type financialAccountLink struct {
	Count  uint64 `json:"count,string"`
	Hash   string `json:"hash"`
	Height int    `json:"height"`
	Total  string `json:"total_atomic"`
}

// Decimal-string nonce avoids lossy JSON-number round trips in future web/UI
// adapters. Legacy Account and transaction-envelope encodings are unchanged.
type financialAccountLeaf struct {
	Address string `json:"address"`
	Balance string `json:"balance_atomic"`
	Nonce   uint64 `json:"nonce,string"`
}

func (leaf financialAccountLeaf) account() Account {
	return Account{Address: leaf.Address, Balance: leaf.Balance, Nonce: leaf.Nonce}
}

type financialAccountNode struct {
	Account financialAccountLeaf `json:"account"`
	Count   uint64               `json:"count,string"`
	Height  int                  `json:"height"`
	Left    financialAccountLink `json:"left"`
	Right   financialAccountLink `json:"right"`
	Rules   string               `json:"rules_hash"`
	Schema  string               `json:"schema"`
	Total   string               `json:"total_atomic"`
	// Local-only proof that this exact VALUE was checked. JSON cannot supply
	// this handle; its immutable snapshot never aliases the public node copy.
	checked *checkedFinancialAccountNode
}
type checkedFinancialAccountRules struct {
	value financialAccountRules
	hash  string
}
type checkedFinancialAccountNode struct {
	value financialAccountNode
	link  financialAccountLink
	rules *checkedFinancialAccountRules
}
type financialAccountRef struct {
	link        financialAccountLink
	node        *financialAccountNode
	left, right *financialAccountRef
}
type financialAccountTree struct {
	rules     financialAccountRules
	rulesHash string
	checked   *checkedFinancialAccountRules
	root      financialAccountRef
	read      func(string) (financialAccountNode, error)
}
type financialAccountProof struct {
	Address string                 `json:"address"`
	Exists  bool                   `json:"exists"`
	Path    []financialAccountNode `json:"path"`
	Rules   string                 `json:"rules_hash"`
	Schema  string                 `json:"schema"`
}

func financialAccountAmount(value string, maximum uint64) (uint64, bool) {
	if len(value) == 0 || len(value) > 20 || !uintPattern.MatchString(value) {
		return 0, false
	}
	amount, err := strconv.ParseUint(value, 10, 64)
	return amount, err == nil && amount <= maximum
}
func financialAccountAddress(address string) bool {
	if len(address) != 64 || !canonicalFinancialHex(address) {
		return false
	}
	key, err := hex.DecodeString(address)
	return err == nil && validAuthorKey(key)
}
func financialAccountEmpty(rulesHash string) financialAccountLink {
	return financialAccountLink{Hash: hashHex([]byte("GG-FINANCIAL-ACCOUNT-EMPTY-v1\x00" + rulesHash)), Total: "0"}
}
func financialAccountDigest(node financialAccountNode) string {
	return hashHex(append([]byte("GG-FINANCIAL-ACCOUNT-NODE-v1\x00"), canonical(node)...))
}
func financialAccountNodeLink(node financialAccountNode) financialAccountLink {
	return financialAccountLink{Count: node.Count, Hash: financialAccountDigest(node), Height: node.Height, Total: node.Total}
}
func validFinancialAccountLink(link financialAccountLink, rules financialAccountRules, rulesHash string) bool {
	if link.Count == 0 {
		return link == financialAccountEmpty(rulesHash)
	}
	if link.Count > rules.MaxAccounts || link.Height < 1 || link.Height > financialAccountPathMax || !canonicalFinancialHex(link.Hash) || link.Hash == financialAccountEmpty(rulesHash).Hash {
		return false
	}
	if _, ok := financialAccountAmount(link.Total, rules.MaxTotal); !ok {
		return false
	}
	// AVL height has both a minimum node count (Fibonacci recurrence) and
	// a complete-tree maximum. Rules cap counts at2^32, so no arithmetic wraps.
	a, b := uint64(0), uint64(1)
	for height := 1; height < link.Height; height++ {
		a, b = b, a+b+1
		if b > rules.MaxAccounts {
			return false
		}
	}
	return link.Count >= b && (link.Height >= 33 || link.Count <= (uint64(1)<<uint(link.Height))-1)
}
func validFinancialAccountNodeShape(node financialAccountNode, rules financialAccountRules, rulesHash string) bool {
	if node.Schema != "gg.financial.account-node.v1" || node.Rules != rulesHash || !financialAccountAddress(node.Account.Address) ||
		!validFinancialAccountLink(node.Left, rules, rulesHash) || !validFinancialAccountLink(node.Right, rules, rulesHash) {
		return false
	}
	balance, ok := financialAccountAmount(node.Account.Balance, rules.MaxTotal)
	left, lok := financialAccountAmount(node.Left.Total, rules.MaxTotal)
	right, rok := financialAccountAmount(node.Right.Total, rules.MaxTotal)
	if !ok || !lok || !rok || left > rules.MaxTotal-balance || right > rules.MaxTotal-balance-left ||
		node.Left.Count >= rules.MaxAccounts || node.Right.Count > rules.MaxAccounts-1-node.Left.Count {
		return false
	}
	height := node.Left.Height
	if node.Right.Height > height {
		height = node.Right.Height
	}
	difference := node.Left.Height - node.Right.Height
	return difference >= -1 && difference <= 1 && node.Height == height+1 &&
		node.Count == node.Left.Count+node.Right.Count+1 && node.Total == strconv.FormatUint(left+balance+right, 10)
}
func validFinancialAccountNode(node financialAccountNode, rules financialAccountRules, rulesHash string) bool {
	return validFinancialAccountNodeShape(node, rules, rulesHash) && validFinancialAccountLink(financialAccountNodeLink(node), rules, rulesHash)
}
func checkFinancialAccountRules(rules financialAccountRules) (*checkedFinancialAccountRules, error) {
	if !rules.valid() {
		return nil, errFinancialAccount
	}
	return &checkedFinancialAccountRules{value: rules, hash: rules.hash()}, nil
}
func (tree financialAccountTree) rulesBound() bool {
	return tree.checked != nil && tree.rules == tree.checked.value && tree.rulesHash == tree.checked.hash
}

// Own a value only after checking its entire public body. The canonical bytes
// and their domain-separated hash are computed once, with unchanged encoding.
// Callers cannot turn a raw/public "verified" flag into this private record.
func checkFinancialAccountNodeValue(node financialAccountNode, rules *checkedFinancialAccountRules) (*checkedFinancialAccountNode, []byte, error) {
	node.checked = nil
	if rules == nil || !validFinancialAccountNodeShape(node, rules.value, rules.hash) {
		return nil, nil, errFinancialAccount
	}
	raw := canonical(node)
	if len(raw) == 0 || len(raw) > financialAccountNodeMaxBytes {
		return nil, nil, errFinancialAccount
	}
	link := financialAccountLink{Count: node.Count, Hash: hashHex(append([]byte("GG-FINANCIAL-ACCOUNT-NODE-v1\x00"), raw...)), Height: node.Height, Total: node.Total}
	if !validFinancialAccountLink(link, rules.value, rules.hash) {
		return nil, nil, errFinancialAccount
	}
	return &checkedFinancialAccountNode{value: node, link: link, rules: rules}, raw, nil
}
func (checked *checkedFinancialAccountNode) public() financialAccountNode {
	node := checked.value
	node.checked = checked
	return node
}
func (checked *checkedFinancialAccountNode) matches(node financialAccountNode, expected financialAccountLink, rules *checkedFinancialAccountRules) bool {
	if checked == nil || checked.rules == nil || rules == nil || checked.rules.value != rules.value || checked.rules.hash != rules.hash || checked.link != expected {
		return false
	}
	node.checked = nil
	return node == checked.value
}
func decodeOwnedFinancialAccountNode(raw []byte, rules financialAccountRules) (financialAccountNode, financialAccountLink, error) {
	var node financialAccountNode
	checkedRules, err := checkFinancialAccountRules(rules)
	if err != nil || len(raw) == 0 || len(raw) > financialAccountNodeMaxBytes || decodeStrict(raw, &node) != nil {
		return node, financialAccountLink{}, errFinancialAccount
	}
	checked, encoded, err := checkFinancialAccountNodeValue(node, checkedRules)
	if err != nil || !bytes.Equal(raw, encoded) {
		return node, financialAccountLink{}, errFinancialAccount
	}
	return checked.public(), checked.link, nil
}
func decodeFinancialAccountNode(raw []byte, expected financialAccountLink, rules financialAccountRules) (financialAccountNode, error) {
	node, link, err := decodeOwnedFinancialAccountNode(raw, rules)
	if err != nil || link != expected {
		return node, errFinancialAccount
	}
	return node, nil
}
func newFinancialAccountTree(rules financialAccountRules) (financialAccountTree, error) {
	checked, err := checkFinancialAccountRules(rules)
	if err != nil {
		return financialAccountTree{}, errFinancialAccount
	}
	return financialAccountTree{rules: rules, rulesHash: checked.hash, checked: checked, root: financialAccountRef{link: financialAccountEmpty(checked.hash)}}, nil
}
func (tree financialAccountTree) load(ctx context.Context, ref financialAccountRef, lower, upper string) (*financialAccountNode, financialAccountRef, financialAccountRef, error) {
	if err := ctx.Err(); err != nil {
		return nil, financialAccountRef{}, financialAccountRef{}, err
	}
	if !tree.rulesBound() {
		return nil, financialAccountRef{}, financialAccountRef{}, errFinancialAccount
	}
	if ref.link.Count == 0 {
		if ref.link != financialAccountEmpty(tree.rulesHash) {
			return nil, financialAccountRef{}, financialAccountRef{}, errFinancialAccount
		}
		return nil, financialAccountRef{}, financialAccountRef{}, nil
	}
	var node financialAccountNode
	if ref.node != nil {
		node = *ref.node
	} else {
		if tree.read == nil || !validFinancialAccountLink(ref.link, tree.rules, tree.rulesHash) {
			return nil, financialAccountRef{}, financialAccountRef{}, errFinancialAccount
		}
		var err error
		node, err = tree.read(ref.link.Hash)
		if err != nil {
			return nil, financialAccountRef{}, financialAccountRef{}, errFinancialAccount
		}
	}
	if err := ctx.Err(); err != nil {
		return nil, financialAccountRef{}, financialAccountRef{}, err
	}
	if node.checked != nil {
		if !node.checked.matches(node, ref.link, tree.checked) {
			return nil, financialAccountRef{}, financialAccountRef{}, errFinancialAccount
		}
	} else {
		checked, _, err := checkFinancialAccountNodeValue(node, tree.checked)
		if err != nil || checked.link != ref.link {
			return nil, financialAccountRef{}, financialAccountRef{}, errFinancialAccount
		}
		node = checked.public()
	}
	if lower != "" && node.Account.Address <= lower || upper != "" && node.Account.Address >= upper {
		return nil, financialAccountRef{}, financialAccountRef{}, errFinancialAccount
	}
	left, right := financialAccountRef{link: node.Left}, financialAccountRef{link: node.Right}
	if ref.left != nil {
		left = *ref.left
		if left.link != node.Left {
			return nil, left, right, errFinancialAccount
		}
	}
	if ref.right != nil {
		right = *ref.right
		if right.link != node.Right {
			return nil, left, right, errFinancialAccount
		}
	}
	return &node, left, right, nil
}
func (tree financialAccountTree) get(ctx context.Context, address string) (Account, bool, error) {
	// Identical validated search to proof(), without allocating a public path.
	if !financialAccountAddress(address) {
		return Account{}, false, errFinancialAccount
	}
	ref, lower, upper := tree.root, "", ""
	for depth := 0; ; depth++ {
		if depth > financialAccountPathMax {
			return Account{}, false, errFinancialAccount
		}
		node, left, right, err := tree.load(ctx, ref, lower, upper)
		if err != nil {
			return Account{}, false, err
		}
		if node == nil {
			return Account{}, false, nil
		}
		if depth == financialAccountPathMax {
			return Account{}, false, errFinancialAccount
		}
		if address == node.Account.Address {
			return node.Account.account(), true, nil
		}
		if address < node.Account.Address {
			ref, upper = left, node.Account.Address
		} else {
			ref, lower = right, node.Account.Address
		}
	}
}
func (tree financialAccountTree) make(account Account, left, right financialAccountRef) (financialAccountRef, error) {
	if !tree.rulesBound() || !validFinancialAccountLink(left.link, tree.rules, tree.rulesHash) || !validFinancialAccountLink(right.link, tree.rules, tree.rulesHash) {
		return financialAccountRef{}, errFinancialAccount
	}
	balance, ok := financialAccountAmount(account.Balance, tree.rules.MaxTotal)
	a, aok := financialAccountAmount(left.link.Total, tree.rules.MaxTotal)
	b, bok := financialAccountAmount(right.link.Total, tree.rules.MaxTotal)
	if !ok || !aok || !bok || a > tree.rules.MaxTotal-balance || b > tree.rules.MaxTotal-balance-a ||
		left.link.Count >= tree.rules.MaxAccounts || right.link.Count > tree.rules.MaxAccounts-1-left.link.Count {
		return financialAccountRef{}, errFinancialAccount
	}
	height := left.link.Height
	if right.link.Height > height {
		height = right.link.Height
	}
	node := financialAccountNode{Account: financialAccountLeaf{Address: account.Address, Balance: account.Balance, Nonce: account.Nonce}, Count: left.link.Count + right.link.Count + 1, Height: height + 1,
		Left: left.link, Right: right.link, Rules: tree.rulesHash, Schema: "gg.financial.account-node.v1", Total: strconv.FormatUint(a+balance+b, 10)}
	checked, _, err := checkFinancialAccountNodeValue(node, tree.checked)
	if err != nil {
		return financialAccountRef{}, errFinancialAccount
	}
	node = checked.public()
	return financialAccountRef{link: checked.link, node: &node, left: &left, right: &right}, nil
}
func (tree financialAccountTree) balance(ctx context.Context, account Account, left, right financialAccountRef) (financialAccountRef, error) {
	switch difference := left.link.Height - right.link.Height; {
	case difference > 1:
		child, a, b, err := tree.load(ctx, left, "", account.Address)
		if err != nil {
			return financialAccountRef{}, err
		}
		if child == nil {
			return financialAccountRef{}, errFinancialAccount
		}
		if a.link.Height >= b.link.Height {
			lower, err := tree.make(account, b, right)
			if err != nil {
				return financialAccountRef{}, err
			}
			return tree.make(child.Account.account(), a, lower)
		}
		middle, c, d, err := tree.load(ctx, b, child.Account.Address, account.Address)
		if err != nil {
			return financialAccountRef{}, err
		}
		if middle == nil {
			return financialAccountRef{}, errFinancialAccount
		}
		afterLeft, err := tree.make(child.Account.account(), a, c)
		if err != nil {
			return financialAccountRef{}, err
		}
		afterRight, err := tree.make(account, d, right)
		if err != nil {
			return financialAccountRef{}, err
		}
		return tree.make(middle.Account.account(), afterLeft, afterRight)
	case difference < -1:
		child, a, b, err := tree.load(ctx, right, account.Address, "")
		if err != nil {
			return financialAccountRef{}, err
		}
		if child == nil {
			return financialAccountRef{}, errFinancialAccount
		}
		if b.link.Height >= a.link.Height {
			lower, err := tree.make(account, left, a)
			if err != nil {
				return financialAccountRef{}, err
			}
			return tree.make(child.Account.account(), lower, b)
		}
		middle, c, d, err := tree.load(ctx, a, account.Address, child.Account.Address)
		if err != nil {
			return financialAccountRef{}, err
		}
		if middle == nil {
			return financialAccountRef{}, errFinancialAccount
		}
		afterLeft, err := tree.make(account, left, c)
		if err != nil {
			return financialAccountRef{}, err
		}
		afterRight, err := tree.make(child.Account.account(), d, b)
		if err != nil {
			return financialAccountRef{}, err
		}
		return tree.make(middle.Account.account(), afterLeft, afterRight)
	default:
		return tree.make(account, left, right)
	}
}
func (tree financialAccountTree) put(ctx context.Context, ref financialAccountRef, account Account, depth int, lower, upper string) (financialAccountRef, error) {
	if depth >= financialAccountPathMax {
		return financialAccountRef{}, errFinancialAccount
	}
	node, left, right, err := tree.load(ctx, ref, lower, upper)
	if err != nil {
		return financialAccountRef{}, err
	}
	if node == nil {
		empty := financialAccountRef{link: financialAccountEmpty(tree.rulesHash)}
		return tree.make(account, empty, empty)
	}
	if account.Address == node.Account.Address {
		return tree.make(account, left, right)
	}
	if account.Address < node.Account.Address {
		left, err = tree.put(ctx, left, account, depth+1, lower, node.Account.Address)
	} else {
		right, err = tree.put(ctx, right, account, depth+1, node.Account.Address, upper)
	}
	if err != nil {
		return financialAccountRef{}, err
	}
	return tree.balance(ctx, node.Account.account(), left, right)
}
func (tree financialAccountTree) set(ctx context.Context, account Account) (financialAccountTree, error) {
	if !financialAccountAddress(account.Address) {
		return tree, errFinancialAccount
	}
	if _, ok := financialAccountAmount(account.Balance, tree.rules.MaxTotal); !ok {
		return tree, errFinancialAccount
	}
	root, err := tree.put(ctx, tree.root, account, 0, "", "")
	if err != nil {
		return tree, err
	}
	if err := ctx.Err(); err != nil {
		return tree, err
	}
	result := tree
	result.root = root
	return result, nil
}
func (tree financialAccountTree) proof(ctx context.Context, address string) (financialAccountProof, error) {
	value := financialAccountProof{Address: address, Path: []financialAccountNode{}, Rules: tree.rulesHash, Schema: "gg.financial.account-proof.v1"}
	if !financialAccountAddress(address) {
		return value, errFinancialAccount
	}
	ref, lower, upper := tree.root, "", ""
	for depth := 0; ; depth++ {
		if depth > financialAccountPathMax {
			return value, errFinancialAccount
		}
		node, left, right, err := tree.load(ctx, ref, lower, upper)
		if err != nil {
			return value, err
		}
		if node == nil {
			return value, nil
		}
		if depth == financialAccountPathMax {
			return value, errFinancialAccount
		}
		value.Path = append(value.Path, *node)
		if address == node.Account.Address {
			value.Exists = true
			return value, nil
		}
		if address < node.Account.Address {
			ref, upper = left, node.Account.Address
		} else {
			ref, lower = right, node.Account.Address
		}
	}
}

// expected and rules must come from independently authenticated application
// state. A proof carries neither a self-selected trusted root nor a verified flag.
func verifyFinancialAccountProof(ctx context.Context, proof financialAccountProof, expected financialAccountLink, rules financialAccountRules) (Account, bool, error) {
	if !rules.valid() || proof.Schema != "gg.financial.account-proof.v1" || proof.Rules != rules.hash() || !financialAccountAddress(proof.Address) ||
		len(proof.Path) > financialAccountPathMax || !validFinancialAccountLink(expected, rules, rules.hash()) {
		return Account{}, false, errFinancialAccount
	}
	ref, lower, upper := expected, "", ""
	for index, node := range proof.Path {
		if err := ctx.Err(); err != nil {
			return Account{}, false, err
		}
		if !validFinancialAccountNode(node, rules, proof.Rules) || financialAccountNodeLink(node) != ref ||
			lower != "" && node.Account.Address <= lower || upper != "" && node.Account.Address >= upper {
			return Account{}, false, errFinancialAccount
		}
		if proof.Address == node.Account.Address {
			if index != len(proof.Path)-1 || !proof.Exists {
				return Account{}, false, errFinancialAccount
			}
			return node.Account.account(), true, nil
		}
		if proof.Address < node.Account.Address {
			ref, upper = node.Left, node.Account.Address
		} else {
			ref, lower = node.Right, node.Account.Address
		}
	}
	if err := ctx.Err(); err != nil {
		return Account{}, false, err
	}
	if proof.Exists || ref != financialAccountEmpty(proof.Rules) {
		return Account{}, false, errFinancialAccount
	}
	return Account{}, false, nil
}

// Pure atomic transition after upstream account-signature authentication. It
// publishes no SDK receipt/finality. Error/cancellation returns the original root.
func (tree financialAccountTree) transfer(ctx context.Context, sender, recipient string, amount, nonce uint64) (financialAccountTree, string, error) {
	if !financialAccountAddress(sender) || !financialAccountAddress(recipient) || sender == recipient || amount == 0 || amount > tree.rules.MaxTotal {
		return tree, "", errFinancialAccount
	}
	from, exists, err := tree.get(ctx, sender)
	if err != nil {
		return tree, "", err
	}
	if !exists {
		return tree, "REJECTED_FUNDS", nil
	}
	if from.Nonce != nonce {
		return tree, "REJECTED_NONCE", nil
	}
	if from.Nonce == ^uint64(0) {
		return tree, "REJECTED_NONCE_EXHAUSTED", nil
	}
	to, targetExists, err := tree.get(ctx, recipient)
	if err != nil {
		return tree, "", err
	}
	if !targetExists {
		// This is an ordered state conflict, not an IO/corruption failure.
		// Keep existing-account transfers available at the admission ceiling.
		if tree.root.link.Count >= tree.rules.MaxAccounts {
			return tree, "REJECTED_ACCOUNT_LIMIT", nil
		}
		to = Account{Address: recipient, Balance: "0"}
	}
	available, _ := financialAccountAmount(from.Balance, tree.rules.MaxTotal)
	destination, _ := financialAccountAmount(to.Balance, tree.rules.MaxTotal)
	if available < amount || destination > tree.rules.MaxTotal-amount {
		return tree, "REJECTED_FUNDS", nil
	}
	from.Balance, from.Nonce = strconv.FormatUint(available-amount, 10), from.Nonce+1
	to.Balance = strconv.FormatUint(destination+amount, 10)
	next, err := tree.set(ctx, from)
	if err == nil {
		next, err = next.set(ctx, to)
	}
	if err != nil {
		return tree, "", err
	}
	if err := ctx.Err(); err != nil {
		return tree, "", err
	}
	if next.root.link.Total != tree.root.link.Total {
		return tree, "", errFinancialAccount
	}
	return next, "APPLIED", nil
}

// Stage only newly reachable immutable nodes into a caller-owned transaction.
// The adapter must commit them with its authoritative head atomically, before
// freezing. This callback interface alone is not durable crash-recovery evidence.
func (tree financialAccountTree) stage(ctx context.Context, maxNodes int, save func(string, []byte) error) error {
	if maxNodes < 1 || maxNodes > financialAccountStageMaxNodes || save == nil {
		return errFinancialAccount
	}
	seen := map[string]bool{}
	var visit func(financialAccountRef, string, string, int) error
	visit = func(ref financialAccountRef, lower, upper string, depth int) error {
		if err := ctx.Err(); err != nil {
			return err
		}
		if depth > financialAccountPathMax || !validFinancialAccountLink(ref.link, tree.rules, tree.rulesHash) {
			return errFinancialAccount
		}
		if ref.link.Count == 0 || ref.node == nil || seen[ref.link.Hash] {
			return nil
		}
		if len(seen) >= maxNodes {
			return errFinancialAccount
		}
		seen[ref.link.Hash] = true
		node, left, right, err := tree.load(ctx, ref, lower, upper)
		if err != nil {
			return err
		}
		if node == nil {
			return errFinancialAccount
		}
		if err := visit(left, lower, node.Account.Address, depth+1); err != nil {
			return err
		}
		if err := visit(right, node.Account.Address, upper, depth+1); err != nil {
			return err
		}
		raw := canonical(*node)
		if len(raw) > financialAccountNodeMaxBytes {
			return errFinancialAccount
		}
		if err := save(ref.link.Hash, raw); err != nil {
			return err
		}
		return ctx.Err()
	}
	return visit(tree.root, "", "", 0)
}
func (tree financialAccountTree) freeze(read func(string) (financialAccountNode, error)) (financialAccountTree, error) {
	if tree.root.link.Count > 0 && read == nil {
		return tree, errFinancialAccount
	}
	next := tree
	next.root = financialAccountRef{link: tree.root.link}
	next.read = read
	return next, nil
}
