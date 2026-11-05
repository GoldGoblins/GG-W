package main

// Immutable authenticated dictionaries for producer ownership/heads and other
// protocol records. Only changed paths are staged; historical roots retain
// bounded authenticated disk readers instead of a global in-memory roster.
import (
	"bytes"
	"context"
	"errors"
)

const protocolRegistryPathMax = 64
const protocolRegistryStageMax = 262144

var errProtocolRegistry = errors.New("GG_PROTOCOL_REGISTRY_INVALID")

type protocolRegistryRules struct {
	Genesis       string `json:"genesis_hash"`
	MaxEntries    uint64 `json:"max_entries,string"`
	MaxValueBytes int    `json:"max_value_bytes"`
	Namespace     string `json:"namespace"`
	Schema        string `json:"schema"`
}

func (rules protocolRegistryRules) valid() bool {
	return rules.Schema == "gg.protocol.registry-rules.v1" && pubPattern.MatchString(rules.Genesis) &&
		rules.MaxEntries > 0 && rules.MaxEntries <= 1<<32 && rules.MaxValueBytes > 0 && rules.MaxValueBytes <= 16384 &&
		(rules.Namespace == "producers" || rules.Namespace == "roles" || rules.Namespace == "epoch_work" || rules.Namespace == "membership" || rules.Namespace == "rewards" || rules.Namespace == "operations")
}

func (rules protocolRegistryRules) hash() string {
	return hashHex(append([]byte("GG-PROTOCOL-REGISTRY-RULES-v1\x00"), canonical(rules)...))
}

type protocolRegistryLink struct {
	Count  uint64 `json:"count,string"`
	Hash   string `json:"hash"`
	Height int    `json:"height"`
}

type protocolRegistryNode struct {
	Height  int                  `json:"height"`
	Key     string               `json:"key"`
	Left    protocolRegistryLink `json:"left"`
	Right   protocolRegistryLink `json:"right"`
	Rules   string               `json:"rules_hash"`
	Schema  string               `json:"schema"`
	Value   []byte               `json:"value"`
	checked *checkedProtocolRegistryNode
}

// These records are local-only witnesses; public JSON cannot mint one.
// payload is an owned immutable string, NEVER an aliased mutable Value slice.
type protocolRegistryNodeBody struct {
	Height        int
	Key           string
	Left, Right   protocolRegistryLink
	Rules, Schema string
}
type checkedProtocolRegistryRules struct {
	value protocolRegistryRules
	hash  string
}
type checkedProtocolRegistryNode struct {
	body    protocolRegistryNodeBody
	payload string
	link    protocolRegistryLink
	rules   *checkedProtocolRegistryRules
}

func protocolRegistryBody(node protocolRegistryNode) protocolRegistryNodeBody {
	return protocolRegistryNodeBody{Height: node.Height, Key: node.Key, Left: node.Left, Right: node.Right, Rules: node.Rules, Schema: node.Schema}
}
func (checked *checkedProtocolRegistryNode) public() protocolRegistryNode {
	b := checked.body
	return protocolRegistryNode{Height: b.Height, Key: b.Key, Left: b.Left, Right: b.Right,
		Rules: b.Rules, Schema: b.Schema, Value: []byte(checked.payload), checked: checked}
}
func (checked *checkedProtocolRegistryNode) matches(node protocolRegistryNode, expected protocolRegistryLink, rules *checkedProtocolRegistryRules) bool {
	return checked != nil && checked.rules != nil && rules != nil &&
		checked.rules.value == rules.value && checked.rules.hash == rules.hash &&
		checked.link == expected && checked.body == protocolRegistryBody(node) && string(node.Value) == checked.payload
}
func checkProtocolRegistryRules(rules protocolRegistryRules) (*checkedProtocolRegistryRules, error) {
	if !rules.valid() {
		return nil, errProtocolRegistry
	}
	return &checkedProtocolRegistryRules{value: rules, hash: rules.hash()}, nil
}
func (tree protocolRegistryTree) rulesBound() bool {
	return tree.checked != nil && tree.rules == tree.checked.value && tree.rulesHash == tree.checked.hash
}
func checkProtocolRegistryNodeValue(node protocolRegistryNode, rules *checkedProtocolRegistryRules) (*checkedProtocolRegistryNode, []byte, error) {
	if rules == nil || !validProtocolRegistryNodeShape(node, rules.value, rules.hash) {
		return nil, nil, errProtocolRegistry
	}
	// Own before hashing: future caller mutation cannot change this witness.
	payload := string(node.Value)
	node.Value = []byte(payload)
	node.checked = nil
	raw := canonical(node)
	if len(raw) == 0 || len(raw) > rules.value.MaxValueBytes*2+2048 {
		return nil, nil, errProtocolRegistry
	}
	link := protocolRegistryLink{Count: node.Left.Count + node.Right.Count + 1,
		Hash: hashHex(append([]byte("GG-PROTOCOL-REGISTRY-NODE-v1\x00"), raw...)), Height: node.Height}
	if !validProtocolRegistryLinkBound(link, rules.value, rules.hash) {
		return nil, nil, errProtocolRegistry
	}
	return &checkedProtocolRegistryNode{body: protocolRegistryBody(node), payload: payload, link: link, rules: rules}, raw, nil
}

type protocolRegistryRef struct {
	link protocolRegistryLink
	node *protocolRegistryPrivateNode
}

type protocolRegistryPrivateNode struct {
	public      protocolRegistryNode
	left, right protocolRegistryRef
}

type protocolRegistryTree struct {
	rules     protocolRegistryRules
	rulesHash string
	checked   *checkedProtocolRegistryRules
	root      protocolRegistryRef
	read      func(string) (protocolRegistryNode, error)
}

type protocolRegistryProof struct {
	Exists bool                   `json:"exists"`
	Key    string                 `json:"key"`
	Path   []protocolRegistryNode `json:"path"`
	Rules  string                 `json:"rules_hash"`
	Schema string                 `json:"schema"`
}

func protocolRegistryEmpty(rulesHash string) protocolRegistryLink {
	return protocolRegistryLink{Hash: hashHex([]byte("GG-PROTOCOL-REGISTRY-EMPTY-v1\x00" + rulesHash))}
}

func validProtocolRegistryLink(link protocolRegistryLink, rules protocolRegistryRules, rulesHash string) bool {
	if !rules.valid() || rulesHash != rules.hash() {
		return false
	}
	return validProtocolRegistryLinkBound(link, rules, rulesHash)
}

// Only a rulesBound tree/checked constructor may use this hash-free helper.
func validProtocolRegistryLinkBound(link protocolRegistryLink, rules protocolRegistryRules, rulesHash string) bool {
	if !pubPattern.MatchString(link.Hash) || link.Count > rules.MaxEntries {
		return false
	}
	if link.Count == 0 {
		return link == protocolRegistryEmpty(rulesHash)
	}
	if link.Height < 1 || link.Height > protocolRegistryPathMax || uint64(link.Height) > link.Count || link.Hash == protocolRegistryEmpty(rulesHash).Hash {
		return false
	}
	// An AVL root cannot advertise a shallow height for too many records, or
	// a tall height without the Fibonacci minimum number of descendants.
	if link.Height < 64 && link.Count > (uint64(1)<<uint(link.Height))-1 {
		return false
	}
	a, b := uint64(0), uint64(1)
	for height := 1; height < link.Height; height++ {
		if a > rules.MaxEntries || b >= rules.MaxEntries || a > rules.MaxEntries-b-1 {
			return false
		}
		a, b = b, a+b+1
	}
	return link.Count >= b
}

func protocolRegistryNodeLink(node protocolRegistryNode) protocolRegistryLink {
	return protocolRegistryLink{Count: node.Left.Count + node.Right.Count + 1,
		Hash: hashHex(append([]byte("GG-PROTOCOL-REGISTRY-NODE-v1\x00"), canonical(node)...)), Height: node.Height}
}

func validProtocolRegistryNodeShape(node protocolRegistryNode, rules protocolRegistryRules, rulesHash string) bool {
	if node.Schema != "gg.protocol.registry-node.v1" || node.Rules != rulesHash || !pubPattern.MatchString(node.Key) ||
		len(node.Value) == 0 || len(node.Value) > rules.MaxValueBytes || !validProtocolRegistryLinkBound(node.Left, rules, rulesHash) ||
		!validProtocolRegistryLinkBound(node.Right, rules, rulesHash) || node.Left.Count >= rules.MaxEntries || node.Right.Count > rules.MaxEntries-1-node.Left.Count {
		return false
	}
	height := node.Left.Height
	if node.Right.Height > height {
		height = node.Right.Height
	}
	difference := node.Left.Height - node.Right.Height
	return difference >= -1 && difference <= 1 && node.Height == height+1
}
func validProtocolRegistryNode(node protocolRegistryNode, rules protocolRegistryRules, rulesHash string) bool {
	return rules.valid() && rulesHash == rules.hash() && validProtocolRegistryNodeShape(node, rules, rulesHash) &&
		validProtocolRegistryLinkBound(protocolRegistryNodeLink(node), rules, rulesHash)
}

func newProtocolRegistry(rules protocolRegistryRules) (protocolRegistryTree, error) {
	checked, err := checkProtocolRegistryRules(rules)
	if err != nil {
		return protocolRegistryTree{}, err
	}
	return protocolRegistryTree{rules: rules, rulesHash: checked.hash, checked: checked,
		root: protocolRegistryRef{link: protocolRegistryEmpty(checked.hash)}}, nil
}
func (tree protocolRegistryTree) load(ctx context.Context, ref protocolRegistryRef, lower, upper string) (*protocolRegistryNode, protocolRegistryRef, protocolRegistryRef, error) {
	if err := ctx.Err(); err != nil {
		return nil, protocolRegistryRef{}, protocolRegistryRef{}, err
	}
	if !tree.rulesBound() {
		return nil, protocolRegistryRef{}, protocolRegistryRef{}, errProtocolRegistry
	}
	if ref.link.Count == 0 {
		if ref.link != protocolRegistryEmpty(tree.rulesHash) || ref.node != nil {
			return nil, protocolRegistryRef{}, protocolRegistryRef{}, errProtocolRegistry
		}
		return nil, protocolRegistryRef{}, protocolRegistryRef{}, nil
	}
	var node protocolRegistryNode
	var left, right protocolRegistryRef
	if ref.node != nil {
		node, left, right = ref.node.public, ref.node.left, ref.node.right
		if left.link != node.Left || right.link != node.Right {
			return nil, left, right, errProtocolRegistry
		}
	} else {
		if tree.read == nil || !validProtocolRegistryLinkBound(ref.link, tree.rules, tree.rulesHash) {
			return nil, left, right, errProtocolRegistry
		}
		var err error
		node, err = tree.read(ref.link.Hash)
		if err != nil {
			return nil, left, right, err
		}
		left, right = protocolRegistryRef{link: node.Left}, protocolRegistryRef{link: node.Right}
	}
	if err := ctx.Err(); err != nil {
		return nil, left, right, err
	}
	if node.checked != nil {
		if !node.checked.matches(node, ref.link, tree.checked) {
			return nil, left, right, errProtocolRegistry
		}
	} else {
		checked, _, err := checkProtocolRegistryNodeValue(node, tree.checked)
		if err != nil || checked.link != ref.link {
			return nil, left, right, errProtocolRegistry
		}
		node = checked.public()
	}
	if lower != "" && node.Key <= lower || upper != "" && node.Key >= upper {
		return nil, left, right, errProtocolRegistry
	}
	// A load result never exposes the internal/cached mutable Value slice.
	node.Value = append([]byte(nil), node.Value...)
	return &node, left, right, nil
}
func (tree protocolRegistryTree) make(key string, value []byte, left, right protocolRegistryRef) (protocolRegistryRef, error) {
	if !tree.rulesBound() {
		return protocolRegistryRef{}, errProtocolRegistry
	}
	height := left.link.Height
	if right.link.Height > height {
		height = right.link.Height
	}
	node := protocolRegistryNode{Height: height + 1, Key: key, Left: left.link, Right: right.link, Rules: tree.rulesHash,
		Schema: "gg.protocol.registry-node.v1", Value: value}
	checked, _, err := checkProtocolRegistryNodeValue(node, tree.checked)
	if err != nil {
		return protocolRegistryRef{}, err
	}
	return protocolRegistryRef{link: checked.link, node: &protocolRegistryPrivateNode{public: checked.public(), left: left, right: right}}, nil
}

func (tree protocolRegistryTree) balance(ctx context.Context, key string, value []byte, left, right protocolRegistryRef) (protocolRegistryRef, error) {
	difference := left.link.Height - right.link.Height
	if difference >= -1 && difference <= 1 {
		return tree.make(key, value, left, right)
	}
	if difference == 2 {
		node, ll, lr, err := tree.load(ctx, left, "", key)
		if err != nil || node == nil {
			return protocolRegistryRef{}, errProtocolRegistry
		}
		if ll.link.Height >= lr.link.Height {
			updated, err := tree.make(key, value, lr, right)
			if err != nil {
				return protocolRegistryRef{}, err
			}
			return tree.make(node.Key, node.Value, ll, updated)
		}
		middle, ml, mr, err := tree.load(ctx, lr, node.Key, key)
		if err != nil || middle == nil {
			return protocolRegistryRef{}, errProtocolRegistry
		}
		a, err := tree.make(node.Key, node.Value, ll, ml)
		if err != nil {
			return protocolRegistryRef{}, err
		}
		b, err := tree.make(key, value, mr, right)
		if err != nil {
			return protocolRegistryRef{}, err
		}
		return tree.make(middle.Key, middle.Value, a, b)
	}
	if difference == -2 {
		node, rl, rr, err := tree.load(ctx, right, key, "")
		if err != nil || node == nil {
			return protocolRegistryRef{}, errProtocolRegistry
		}
		if rr.link.Height >= rl.link.Height {
			updated, err := tree.make(key, value, left, rl)
			if err != nil {
				return protocolRegistryRef{}, err
			}
			return tree.make(node.Key, node.Value, updated, rr)
		}
		middle, ml, mr, err := tree.load(ctx, rl, key, node.Key)
		if err != nil || middle == nil {
			return protocolRegistryRef{}, errProtocolRegistry
		}
		a, err := tree.make(key, value, left, ml)
		if err != nil {
			return protocolRegistryRef{}, err
		}
		b, err := tree.make(node.Key, node.Value, mr, rr)
		if err != nil {
			return protocolRegistryRef{}, err
		}
		return tree.make(middle.Key, middle.Value, a, b)
	}
	return protocolRegistryRef{}, errProtocolRegistry
}

func (tree protocolRegistryTree) put(ctx context.Context, ref protocolRegistryRef, key string, value []byte, depth int, lower, upper string) (protocolRegistryRef, error) {
	if depth > protocolRegistryPathMax {
		return protocolRegistryRef{}, errProtocolRegistry
	}
	node, left, right, err := tree.load(ctx, ref, lower, upper)
	if err != nil {
		return protocolRegistryRef{}, err
	}
	if node == nil {
		empty := protocolRegistryRef{link: protocolRegistryEmpty(tree.rulesHash)}
		return tree.make(key, value, empty, empty)
	}
	if depth == protocolRegistryPathMax {
		return protocolRegistryRef{}, errProtocolRegistry
	}
	if key == node.Key {
		return tree.make(key, value, left, right)
	}
	if key < node.Key {
		left, err = tree.put(ctx, left, key, value, depth+1, lower, node.Key)
	} else {
		right, err = tree.put(ctx, right, key, value, depth+1, node.Key, upper)
	}
	if err != nil {
		return protocolRegistryRef{}, err
	}
	return tree.balance(ctx, node.Key, node.Value, left, right)
}

func (tree protocolRegistryTree) set(ctx context.Context, key string, value []byte) (protocolRegistryTree, error) {
	if !pubPattern.MatchString(key) || len(value) == 0 || len(value) > tree.rules.MaxValueBytes {
		return tree, errProtocolRegistry
	}
	root, err := tree.put(ctx, tree.root, key, value, 0, "", "")
	if err != nil {
		return tree, err
	}
	if err = ctx.Err(); err != nil {
		return tree, err
	}
	updated := tree
	updated.root = root
	return updated, nil
}

func (tree protocolRegistryTree) get(ctx context.Context, key string) ([]byte, bool, error) {
	if !pubPattern.MatchString(key) {
		return nil, false, errProtocolRegistry
	}
	ref, lower, upper := tree.root, "", ""
	for depth := 0; depth <= protocolRegistryPathMax; depth++ {
		node, left, right, err := tree.load(ctx, ref, lower, upper)
		if err != nil {
			return nil, false, err
		}
		if node == nil {
			return nil, false, nil
		}
		if key == node.Key {
			return append([]byte(nil), node.Value...), true, nil
		}
		if key < node.Key {
			ref, upper = left, node.Key
		} else {
			ref, lower = right, node.Key
		}
	}
	return nil, false, errProtocolRegistry
}

func (tree protocolRegistryTree) proof(ctx context.Context, key string) (protocolRegistryProof, error) {
	proof := protocolRegistryProof{Key: key, Path: []protocolRegistryNode{}, Rules: tree.rulesHash, Schema: "gg.protocol.registry-proof.v1"}
	if !pubPattern.MatchString(key) {
		return proof, errProtocolRegistry
	}
	ref, lower, upper := tree.root, "", ""
	for depth := 0; depth <= protocolRegistryPathMax; depth++ {
		node, left, right, err := tree.load(ctx, ref, lower, upper)
		if err != nil {
			return proof, err
		}
		if node == nil {
			return proof, nil
		}
		if depth == protocolRegistryPathMax {
			return proof, errProtocolRegistry
		}
		owned := *node
		owned.Value = append([]byte(nil), node.Value...)
		proof.Path = append(proof.Path, owned)
		if key == node.Key {
			proof.Exists = true
			return proof, nil
		}
		if key < node.Key {
			ref, upper = left, node.Key
		} else {
			ref, lower = right, node.Key
		}
	}
	return proof, errProtocolRegistry
}

func verifyProtocolRegistryProof(ctx context.Context, proof protocolRegistryProof, expected protocolRegistryLink, rules protocolRegistryRules, expectedKey string) ([]byte, bool, error) {
	if !pubPattern.MatchString(expectedKey) || proof.Key != expectedKey || proof.Schema != "gg.protocol.registry-proof.v1" || proof.Rules != rules.hash() ||
		len(proof.Path) > protocolRegistryPathMax || !validProtocolRegistryLink(expected, rules, rules.hash()) {
		return nil, false, errProtocolRegistry
	}
	ref, lower, upper := expected, "", ""
	for index, node := range proof.Path {
		if err := ctx.Err(); err != nil {
			return nil, false, err
		}
		if !validProtocolRegistryNode(node, rules, proof.Rules) || protocolRegistryNodeLink(node) != ref ||
			lower != "" && node.Key <= lower || upper != "" && node.Key >= upper {
			return nil, false, errProtocolRegistry
		}
		if expectedKey == node.Key {
			if !proof.Exists || index != len(proof.Path)-1 {
				return nil, false, errProtocolRegistry
			}
			return append([]byte(nil), node.Value...), true, nil
		}
		if expectedKey < node.Key {
			ref, upper = node.Left, node.Key
		} else {
			ref, lower = node.Right, node.Key
		}
	}
	if err := ctx.Err(); err != nil {
		return nil, false, err
	}
	if proof.Exists || ref != protocolRegistryEmpty(proof.Rules) {
		return nil, false, errProtocolRegistry
	}
	return nil, false, nil
}

func (tree protocolRegistryTree) stage(ctx context.Context, save func(string, []byte) error) error {
	stack := []protocolRegistryRef{tree.root}
	seen := map[string]bool{}
	for len(stack) > 0 {
		if err := ctx.Err(); err != nil {
			return err
		}
		last := len(stack) - 1
		ref := stack[last]
		stack = stack[:last]
		if ref.node == nil || seen[ref.link.Hash] {
			continue
		}
		if len(seen) >= protocolRegistryStageMax {
			return errProtocolRegistry
		}
		node, _, _, err := tree.load(ctx, ref, "", "")
		if err != nil {
			return err
		}
		if node == nil {
			return errProtocolRegistry
		}
		raw := canonical(*node)
		if len(raw) > tree.rules.MaxValueBytes*2+2048 {
			return errProtocolRegistry
		}
		if err := save(ref.link.Hash, raw); err != nil {
			return err
		}
		seen[ref.link.Hash] = true
		stack = append(stack, ref.node.left, ref.node.right)
	}
	return nil
}

func (tree protocolRegistryTree) freeze(read func(string) (protocolRegistryNode, error)) (protocolRegistryTree, error) {
	if read == nil || !tree.rulesBound() || !validProtocolRegistryLinkBound(tree.root.link, tree.rules, tree.rulesHash) {
		return tree, errProtocolRegistry
	}
	result := tree
	result.root = protocolRegistryRef{link: tree.root.link}
	result.read = read
	return result, nil
}

func (tree protocolRegistryTree) walk(ctx context.Context, maximum uint64, visit func(string, []byte) error) error {
	if tree.root.link.Count > maximum {
		return errProtocolRegistry
	}
	type item struct {
		ref          protocolRegistryRef
		lower, upper string
		emit         bool
	}
	stack := []item{{ref: tree.root}}
	count := uint64(0)
	previous := ""
	for len(stack) > 0 {
		if err := ctx.Err(); err != nil {
			return err
		}
		last := len(stack) - 1
		row := stack[last]
		stack = stack[:last]
		node, left, right, err := tree.load(ctx, row.ref, row.lower, row.upper)
		if err != nil {
			return err
		}
		if node == nil {
			continue
		}
		if row.emit {
			if count >= maximum || node.Key <= previous {
				return errProtocolRegistry
			}
			if err = visit(node.Key, append([]byte(nil), node.Value...)); err != nil {
				return err
			}
			previous = node.Key
			count++
			continue
		}
		if len(stack) > 2*protocolRegistryPathMax {
			return errProtocolRegistry
		}
		stack = append(stack, item{ref: right, lower: node.Key, upper: row.upper}, item{ref: row.ref, lower: row.lower, upper: row.upper, emit: true}, item{ref: left, lower: row.lower, upper: node.Key})
	}
	if count != tree.root.link.Count {
		return errProtocolRegistry
	}
	return nil
}

func decodeOwnedProtocolRegistryNode(raw []byte, rules protocolRegistryRules) (protocolRegistryNode, protocolRegistryLink, error) {
	var node protocolRegistryNode
	checkedRules, err := checkProtocolRegistryRules(rules)
	if err != nil || len(raw) == 0 || len(raw) > rules.MaxValueBytes*2+2048 || decodeStrict(raw, &node) != nil {
		return node, protocolRegistryLink{}, errProtocolRegistry
	}
	checked, encoded, err := checkProtocolRegistryNodeValue(node, checkedRules)
	if err != nil || !bytes.Equal(raw, encoded) {
		return node, protocolRegistryLink{}, errProtocolRegistry
	}
	return checked.public(), checked.link, nil
}
func decodeProtocolRegistryNode(raw []byte, expected protocolRegistryLink, rules protocolRegistryRules) (protocolRegistryNode, error) {
	node, link, err := decodeOwnedProtocolRegistryNode(raw, rules)
	if err != nil || link != expected {
		return node, errProtocolRegistry
	}
	return node, nil
}
