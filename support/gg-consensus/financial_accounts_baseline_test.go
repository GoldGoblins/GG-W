// Frozen pre-optimization account kernel, renamed only for differential tests.
// Original SHA-256: 5e33d6258d6fe2f0b422b779a704e1ee8848bcfe7004f3d62f6f4ccb3d68feaa
// No production caller imports or executes this reference.
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

const baselineFinancialAccountPathMax = 64
const baselineFinancialAccountNodeMaxBytes = 2048
const baselineFinancialAccountStageMaxNodes = 262144

var baselineErrFinancialAccount = errors.New("GG_FINANCIAL_ACCOUNT_STATE_UNAVAILABLE")

type baselineFinancialAccountRules struct {
	Genesis     string `json:"genesis_hash"`
	MaxAccounts uint64 `json:"max_accounts,string"`
	MaxTotal    uint64 `json:"max_total_atomic,string"`
	Schema      string `json:"schema"`
}

func (rules baselineFinancialAccountRules) valid() bool {
	return rules.Schema == "gg.financial.account-rules.v1" && pubPattern.MatchString(rules.Genesis) &&
		rules.MaxAccounts > 0 && rules.MaxAccounts <= 1<<32 && rules.MaxTotal > 0
}
func (rules baselineFinancialAccountRules) hash() string {
	return hashHex(append([]byte("GG-FINANCIAL-ACCOUNT-RULES-v1\x00"), canonical(rules)...))
}

// All child metadata is authenticated by its parent's hash. The reader must
// check that the referenced child's actual body has exactly this metadata.
type baselineFinancialAccountLink struct {
	Count  uint64 `json:"count,string"`
	Hash   string `json:"hash"`
	Height int    `json:"height"`
	Total  string `json:"total_atomic"`
}

// Decimal-string nonce avoids lossy JSON-number round trips in future web/UI
// adapters. Legacy Account and transaction-envelope encodings are unchanged.
type baselineFinancialAccountLeaf struct {
	Address string `json:"address"`
	Balance string `json:"balance_atomic"`
	Nonce   uint64 `json:"nonce,string"`
}

func (leaf baselineFinancialAccountLeaf) account() Account {
	return Account{Address: leaf.Address, Balance: leaf.Balance, Nonce: leaf.Nonce}
}

type baselineFinancialAccountNode struct {
	Account baselineFinancialAccountLeaf `json:"account"`
	Count   uint64                       `json:"count,string"`
	Height  int                          `json:"height"`
	Left    baselineFinancialAccountLink `json:"left"`
	Right   baselineFinancialAccountLink `json:"right"`
	Rules   string                       `json:"rules_hash"`
	Schema  string                       `json:"schema"`
	Total   string                       `json:"total_atomic"`
}
type baselineFinancialAccountRef struct {
	link        baselineFinancialAccountLink
	node        *baselineFinancialAccountNode
	left, right *baselineFinancialAccountRef
}
type baselineFinancialAccountTree struct {
	rules     baselineFinancialAccountRules
	rulesHash string
	root      baselineFinancialAccountRef
	read      func(string) (baselineFinancialAccountNode, error)
}
type baselineFinancialAccountProof struct {
	Address string                         `json:"address"`
	Exists  bool                           `json:"exists"`
	Path    []baselineFinancialAccountNode `json:"path"`
	Rules   string                         `json:"rules_hash"`
	Schema  string                         `json:"schema"`
}

func baselineFinancialAccountAmount(value string, maximum uint64) (uint64, bool) {
	if len(value) == 0 || len(value) > 20 || !uintPattern.MatchString(value) {
		return 0, false
	}
	amount, err := strconv.ParseUint(value, 10, 64)
	return amount, err == nil && amount <= maximum
}
func baselineFinancialAccountAddress(address string) bool {
	if len(address) != 64 || !pubPattern.MatchString(address) {
		return false
	}
	key, err := hex.DecodeString(address)
	return err == nil && validAuthorKey(key)
}
func baselineFinancialAccountEmpty(rulesHash string) baselineFinancialAccountLink {
	return baselineFinancialAccountLink{Hash: hashHex([]byte("GG-FINANCIAL-ACCOUNT-EMPTY-v1\x00" + rulesHash)), Total: "0"}
}
func baselineFinancialAccountDigest(node baselineFinancialAccountNode) string {
	return hashHex(append([]byte("GG-FINANCIAL-ACCOUNT-NODE-v1\x00"), canonical(node)...))
}
func baselineFinancialAccountNodeLink(node baselineFinancialAccountNode) baselineFinancialAccountLink {
	return baselineFinancialAccountLink{Count: node.Count, Hash: baselineFinancialAccountDigest(node), Height: node.Height, Total: node.Total}
}
func baselineValidFinancialAccountLink(link baselineFinancialAccountLink, rules baselineFinancialAccountRules, rulesHash string) bool {
	if link.Count == 0 {
		return link == baselineFinancialAccountEmpty(rulesHash)
	}
	if link.Count > rules.MaxAccounts || link.Height < 1 || link.Height > baselineFinancialAccountPathMax || !pubPattern.MatchString(link.Hash) || link.Hash == baselineFinancialAccountEmpty(rulesHash).Hash {
		return false
	}
	if _, ok := baselineFinancialAccountAmount(link.Total, rules.MaxTotal); !ok {
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
func baselineValidFinancialAccountNode(node baselineFinancialAccountNode, rules baselineFinancialAccountRules, rulesHash string) bool {
	if node.Schema != "gg.financial.account-node.v1" || node.Rules != rulesHash || !baselineFinancialAccountAddress(node.Account.Address) ||
		!baselineValidFinancialAccountLink(node.Left, rules, rulesHash) || !baselineValidFinancialAccountLink(node.Right, rules, rulesHash) {
		return false
	}
	balance, ok := baselineFinancialAccountAmount(node.Account.Balance, rules.MaxTotal)
	left, lok := baselineFinancialAccountAmount(node.Left.Total, rules.MaxTotal)
	right, rok := baselineFinancialAccountAmount(node.Right.Total, rules.MaxTotal)
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
		node.Count == node.Left.Count+node.Right.Count+1 && node.Total == strconv.FormatUint(left+balance+right, 10) &&
		baselineValidFinancialAccountLink(baselineFinancialAccountNodeLink(node), rules, rulesHash)
}
func baselineDecodeFinancialAccountNode(raw []byte, expected baselineFinancialAccountLink, rules baselineFinancialAccountRules) (baselineFinancialAccountNode, error) {
	var node baselineFinancialAccountNode
	if !rules.valid() || len(raw) == 0 || len(raw) > baselineFinancialAccountNodeMaxBytes || decodeStrict(raw, &node) != nil ||
		!bytes.Equal(raw, canonical(node)) || !baselineValidFinancialAccountNode(node, rules, rules.hash()) || baselineFinancialAccountNodeLink(node) != expected {
		return node, baselineErrFinancialAccount
	}
	return node, nil
}
func baselineNewFinancialAccountTree(rules baselineFinancialAccountRules) (baselineFinancialAccountTree, error) {
	if !rules.valid() {
		return baselineFinancialAccountTree{}, baselineErrFinancialAccount
	}
	return baselineFinancialAccountTree{rules: rules, rulesHash: rules.hash(), root: baselineFinancialAccountRef{link: baselineFinancialAccountEmpty(rules.hash())}}, nil
}
func (tree baselineFinancialAccountTree) load(ctx context.Context, ref baselineFinancialAccountRef, lower, upper string) (*baselineFinancialAccountNode, baselineFinancialAccountRef, baselineFinancialAccountRef, error) {
	if err := ctx.Err(); err != nil {
		return nil, baselineFinancialAccountRef{}, baselineFinancialAccountRef{}, err
	}
	if !baselineValidFinancialAccountLink(ref.link, tree.rules, tree.rulesHash) {
		return nil, baselineFinancialAccountRef{}, baselineFinancialAccountRef{}, baselineErrFinancialAccount
	}
	if ref.link.Count == 0 {
		return nil, baselineFinancialAccountRef{}, baselineFinancialAccountRef{}, nil
	}
	var node baselineFinancialAccountNode
	if ref.node != nil {
		node = *ref.node
	} else {
		if tree.read == nil {
			return nil, baselineFinancialAccountRef{}, baselineFinancialAccountRef{}, baselineErrFinancialAccount
		}
		var err error
		node, err = tree.read(ref.link.Hash)
		if err != nil {
			return nil, baselineFinancialAccountRef{}, baselineFinancialAccountRef{}, baselineErrFinancialAccount
		}
	}
	if err := ctx.Err(); err != nil {
		return nil, baselineFinancialAccountRef{}, baselineFinancialAccountRef{}, err
	}
	if !baselineValidFinancialAccountNode(node, tree.rules, tree.rulesHash) || baselineFinancialAccountNodeLink(node) != ref.link ||
		lower != "" && node.Account.Address <= lower || upper != "" && node.Account.Address >= upper {
		return nil, baselineFinancialAccountRef{}, baselineFinancialAccountRef{}, baselineErrFinancialAccount
	}
	left, right := baselineFinancialAccountRef{link: node.Left}, baselineFinancialAccountRef{link: node.Right}
	if ref.left != nil {
		left = *ref.left
		if left.link != node.Left {
			return nil, left, right, baselineErrFinancialAccount
		}
	}
	if ref.right != nil {
		right = *ref.right
		if right.link != node.Right {
			return nil, left, right, baselineErrFinancialAccount
		}
	}
	return &node, left, right, nil
}
func (tree baselineFinancialAccountTree) get(ctx context.Context, address string) (Account, bool, error) {
	proof, err := tree.proof(ctx, address)
	if err != nil || !proof.Exists {
		return Account{}, false, err
	}
	return proof.Path[len(proof.Path)-1].Account.account(), true, nil
}
func (tree baselineFinancialAccountTree) make(account Account, left, right baselineFinancialAccountRef) (baselineFinancialAccountRef, error) {
	if !baselineValidFinancialAccountLink(left.link, tree.rules, tree.rulesHash) || !baselineValidFinancialAccountLink(right.link, tree.rules, tree.rulesHash) {
		return baselineFinancialAccountRef{}, baselineErrFinancialAccount
	}
	balance, ok := baselineFinancialAccountAmount(account.Balance, tree.rules.MaxTotal)
	a, aok := baselineFinancialAccountAmount(left.link.Total, tree.rules.MaxTotal)
	b, bok := baselineFinancialAccountAmount(right.link.Total, tree.rules.MaxTotal)
	if !ok || !aok || !bok || a > tree.rules.MaxTotal-balance || b > tree.rules.MaxTotal-balance-a ||
		left.link.Count >= tree.rules.MaxAccounts || right.link.Count > tree.rules.MaxAccounts-1-left.link.Count {
		return baselineFinancialAccountRef{}, baselineErrFinancialAccount
	}
	height := left.link.Height
	if right.link.Height > height {
		height = right.link.Height
	}
	node := baselineFinancialAccountNode{Account: baselineFinancialAccountLeaf{Address: account.Address, Balance: account.Balance, Nonce: account.Nonce}, Count: left.link.Count + right.link.Count + 1, Height: height + 1,
		Left: left.link, Right: right.link, Rules: tree.rulesHash, Schema: "gg.financial.account-node.v1", Total: strconv.FormatUint(a+balance+b, 10)}
	if !baselineValidFinancialAccountNode(node, tree.rules, tree.rulesHash) || len(canonical(node)) > baselineFinancialAccountNodeMaxBytes {
		return baselineFinancialAccountRef{}, baselineErrFinancialAccount
	}
	return baselineFinancialAccountRef{link: baselineFinancialAccountNodeLink(node), node: &node, left: &left, right: &right}, nil
}
func (tree baselineFinancialAccountTree) balance(ctx context.Context, account Account, left, right baselineFinancialAccountRef) (baselineFinancialAccountRef, error) {
	switch difference := left.link.Height - right.link.Height; {
	case difference > 1:
		child, a, b, err := tree.load(ctx, left, "", account.Address)
		if err != nil {
			return baselineFinancialAccountRef{}, err
		}
		if child == nil {
			return baselineFinancialAccountRef{}, baselineErrFinancialAccount
		}
		if a.link.Height >= b.link.Height {
			lower, err := tree.make(account, b, right)
			if err != nil {
				return baselineFinancialAccountRef{}, err
			}
			return tree.make(child.Account.account(), a, lower)
		}
		middle, c, d, err := tree.load(ctx, b, child.Account.Address, account.Address)
		if err != nil {
			return baselineFinancialAccountRef{}, err
		}
		if middle == nil {
			return baselineFinancialAccountRef{}, baselineErrFinancialAccount
		}
		afterLeft, err := tree.make(child.Account.account(), a, c)
		if err != nil {
			return baselineFinancialAccountRef{}, err
		}
		afterRight, err := tree.make(account, d, right)
		if err != nil {
			return baselineFinancialAccountRef{}, err
		}
		return tree.make(middle.Account.account(), afterLeft, afterRight)
	case difference < -1:
		child, a, b, err := tree.load(ctx, right, account.Address, "")
		if err != nil {
			return baselineFinancialAccountRef{}, err
		}
		if child == nil {
			return baselineFinancialAccountRef{}, baselineErrFinancialAccount
		}
		if b.link.Height >= a.link.Height {
			lower, err := tree.make(account, left, a)
			if err != nil {
				return baselineFinancialAccountRef{}, err
			}
			return tree.make(child.Account.account(), lower, b)
		}
		middle, c, d, err := tree.load(ctx, a, account.Address, child.Account.Address)
		if err != nil {
			return baselineFinancialAccountRef{}, err
		}
		if middle == nil {
			return baselineFinancialAccountRef{}, baselineErrFinancialAccount
		}
		afterLeft, err := tree.make(account, left, c)
		if err != nil {
			return baselineFinancialAccountRef{}, err
		}
		afterRight, err := tree.make(child.Account.account(), d, b)
		if err != nil {
			return baselineFinancialAccountRef{}, err
		}
		return tree.make(middle.Account.account(), afterLeft, afterRight)
	default:
		return tree.make(account, left, right)
	}
}
func (tree baselineFinancialAccountTree) put(ctx context.Context, ref baselineFinancialAccountRef, account Account, depth int, lower, upper string) (baselineFinancialAccountRef, error) {
	if depth >= baselineFinancialAccountPathMax {
		return baselineFinancialAccountRef{}, baselineErrFinancialAccount
	}
	node, left, right, err := tree.load(ctx, ref, lower, upper)
	if err != nil {
		return baselineFinancialAccountRef{}, err
	}
	if node == nil {
		empty := baselineFinancialAccountRef{link: baselineFinancialAccountEmpty(tree.rulesHash)}
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
		return baselineFinancialAccountRef{}, err
	}
	return tree.balance(ctx, node.Account.account(), left, right)
}
func (tree baselineFinancialAccountTree) set(ctx context.Context, account Account) (baselineFinancialAccountTree, error) {
	if !baselineFinancialAccountAddress(account.Address) {
		return tree, baselineErrFinancialAccount
	}
	if _, ok := baselineFinancialAccountAmount(account.Balance, tree.rules.MaxTotal); !ok {
		return tree, baselineErrFinancialAccount
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
func (tree baselineFinancialAccountTree) proof(ctx context.Context, address string) (baselineFinancialAccountProof, error) {
	value := baselineFinancialAccountProof{Address: address, Path: []baselineFinancialAccountNode{}, Rules: tree.rulesHash, Schema: "gg.financial.account-proof.v1"}
	if !baselineFinancialAccountAddress(address) {
		return value, baselineErrFinancialAccount
	}
	ref, lower, upper := tree.root, "", ""
	for depth := 0; ; depth++ {
		if depth > baselineFinancialAccountPathMax {
			return value, baselineErrFinancialAccount
		}
		node, left, right, err := tree.load(ctx, ref, lower, upper)
		if err != nil {
			return value, err
		}
		if node == nil {
			return value, nil
		}
		if depth == baselineFinancialAccountPathMax {
			return value, baselineErrFinancialAccount
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
func baselineVerifyFinancialAccountProof(ctx context.Context, proof baselineFinancialAccountProof, expected baselineFinancialAccountLink, rules baselineFinancialAccountRules) (Account, bool, error) {
	if !rules.valid() || proof.Schema != "gg.financial.account-proof.v1" || proof.Rules != rules.hash() || !baselineFinancialAccountAddress(proof.Address) ||
		len(proof.Path) > baselineFinancialAccountPathMax || !baselineValidFinancialAccountLink(expected, rules, rules.hash()) {
		return Account{}, false, baselineErrFinancialAccount
	}
	ref, lower, upper := expected, "", ""
	for index, node := range proof.Path {
		if err := ctx.Err(); err != nil {
			return Account{}, false, err
		}
		if !baselineValidFinancialAccountNode(node, rules, proof.Rules) || baselineFinancialAccountNodeLink(node) != ref ||
			lower != "" && node.Account.Address <= lower || upper != "" && node.Account.Address >= upper {
			return Account{}, false, baselineErrFinancialAccount
		}
		if proof.Address == node.Account.Address {
			if index != len(proof.Path)-1 || !proof.Exists {
				return Account{}, false, baselineErrFinancialAccount
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
	if proof.Exists || ref != baselineFinancialAccountEmpty(proof.Rules) {
		return Account{}, false, baselineErrFinancialAccount
	}
	return Account{}, false, nil
}

// Pure atomic transition after upstream account-signature authentication. It
// publishes no SDK receipt/finality. Error/cancellation returns the original root.
func (tree baselineFinancialAccountTree) transfer(ctx context.Context, sender, recipient string, amount, nonce uint64) (baselineFinancialAccountTree, string, error) {
	if !baselineFinancialAccountAddress(sender) || !baselineFinancialAccountAddress(recipient) || sender == recipient || amount == 0 || amount > tree.rules.MaxTotal {
		return tree, "", baselineErrFinancialAccount
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
	available, _ := baselineFinancialAccountAmount(from.Balance, tree.rules.MaxTotal)
	destination, _ := baselineFinancialAccountAmount(to.Balance, tree.rules.MaxTotal)
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
		return tree, "", baselineErrFinancialAccount
	}
	return next, "APPLIED", nil
}

// Stage only newly reachable immutable nodes into a caller-owned transaction.
// The adapter must commit them with its authoritative head atomically, before
// freezing. This callback interface alone is not durable crash-recovery evidence.
func (tree baselineFinancialAccountTree) stage(ctx context.Context, maxNodes int, save func(string, []byte) error) error {
	if maxNodes < 1 || maxNodes > baselineFinancialAccountStageMaxNodes || save == nil {
		return baselineErrFinancialAccount
	}
	seen := map[string]bool{}
	var visit func(baselineFinancialAccountRef, string, string, int) error
	visit = func(ref baselineFinancialAccountRef, lower, upper string, depth int) error {
		if err := ctx.Err(); err != nil {
			return err
		}
		if depth > baselineFinancialAccountPathMax || !baselineValidFinancialAccountLink(ref.link, tree.rules, tree.rulesHash) {
			return baselineErrFinancialAccount
		}
		if ref.link.Count == 0 || ref.node == nil || seen[ref.link.Hash] {
			return nil
		}
		if len(seen) >= maxNodes {
			return baselineErrFinancialAccount
		}
		seen[ref.link.Hash] = true
		node, left, right, err := tree.load(ctx, ref, lower, upper)
		if err != nil {
			return err
		}
		if node == nil {
			return baselineErrFinancialAccount
		}
		if err := visit(left, lower, node.Account.Address, depth+1); err != nil {
			return err
		}
		if err := visit(right, node.Account.Address, upper, depth+1); err != nil {
			return err
		}
		raw := canonical(*node)
		if len(raw) > baselineFinancialAccountNodeMaxBytes {
			return baselineErrFinancialAccount
		}
		if err := save(ref.link.Hash, raw); err != nil {
			return err
		}
		return ctx.Err()
	}
	return visit(tree.root, "", "", 0)
}
func (tree baselineFinancialAccountTree) freeze(read func(string) (baselineFinancialAccountNode, error)) (baselineFinancialAccountTree, error) {
	if tree.root.link.Count > 0 && read == nil {
		return tree, baselineErrFinancialAccount
	}
	next := tree
	next.root = baselineFinancialAccountRef{link: tree.root.link}
	next.read = read
	return next, nil
}
