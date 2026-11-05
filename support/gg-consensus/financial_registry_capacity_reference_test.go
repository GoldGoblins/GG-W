//go:build !js

package main

// Immutable authenticated dictionaries for producer ownership/heads and other
// protocol records. Only changed paths are staged; historical roots retain
// bounded authenticated disk readers instead of a global in-memory roster.
import (
	"bytes"
	"context"
	"errors"
)

const capacityReferenceRegistryPathMax = 64
const capacityReferenceRegistryStageMax = 262144

var errCapacityReferenceRegistry = errors.New("GG_PROTOCOL_REGISTRY_INVALID")

type capacityReferenceRegistryRules struct {
	Genesis       string `json:"genesis_hash"`
	MaxEntries    uint64 `json:"max_entries,string"`
	MaxValueBytes int    `json:"max_value_bytes"`
	Namespace     string `json:"namespace"`
	Schema        string `json:"schema"`
}

func (rules capacityReferenceRegistryRules) valid() bool {
	return rules.Schema == "gg.protocol.registry-rules.v1" && pubPattern.MatchString(rules.Genesis) &&
		rules.MaxEntries > 0 && rules.MaxEntries <= 1<<32 && rules.MaxValueBytes > 0 && rules.MaxValueBytes <= 16384 &&
		(rules.Namespace == "producers" || rules.Namespace == "roles" || rules.Namespace == "epoch_work" || rules.Namespace == "membership" || rules.Namespace == "rewards" || rules.Namespace == "operations")
}

func (rules capacityReferenceRegistryRules) hash() string {
	return hashHex(append([]byte("GG-PROTOCOL-REGISTRY-RULES-v1\x00"), canonical(rules)...))
}

type capacityReferenceRegistryLink struct {
	Count  uint64 `json:"count,string"`
	Hash   string `json:"hash"`
	Height int    `json:"height"`
}

type capacityReferenceRegistryNode struct {
	Height int                           `json:"height"`
	Key    string                        `json:"key"`
	Left   capacityReferenceRegistryLink `json:"left"`
	Right  capacityReferenceRegistryLink `json:"right"`
	Rules  string                        `json:"rules_hash"`
	Schema string                        `json:"schema"`
	Value  []byte                        `json:"value"`
}

type capacityReferenceRegistryRef struct {
	link capacityReferenceRegistryLink
	node *capacityReferenceRegistryPrivateNode
}

type capacityReferenceRegistryPrivateNode struct {
	public      capacityReferenceRegistryNode
	left, right capacityReferenceRegistryRef
}

type capacityReferenceRegistryTree struct {
	rules     capacityReferenceRegistryRules
	rulesHash string
	root      capacityReferenceRegistryRef
	read      func(string) (capacityReferenceRegistryNode, error)
}

type capacityReferenceRegistryProof struct {
	Exists bool                            `json:"exists"`
	Key    string                          `json:"key"`
	Path   []capacityReferenceRegistryNode `json:"path"`
	Rules  string                          `json:"rules_hash"`
	Schema string                          `json:"schema"`
}

func capacityReferenceRegistryEmpty(rulesHash string) capacityReferenceRegistryLink {
	return capacityReferenceRegistryLink{Hash: hashHex([]byte("GG-PROTOCOL-REGISTRY-EMPTY-v1\x00" + rulesHash))}
}

func validCapacityReferenceRegistryLink(link capacityReferenceRegistryLink, rules capacityReferenceRegistryRules, rulesHash string) bool {
	if !rules.valid() || rulesHash != rules.hash() || !pubPattern.MatchString(link.Hash) || link.Count > rules.MaxEntries {
		return false
	}
	if link.Count == 0 {
		return link == capacityReferenceRegistryEmpty(rulesHash)
	}
	if link.Height < 1 || link.Height > capacityReferenceRegistryPathMax || uint64(link.Height) > link.Count || link.Hash == capacityReferenceRegistryEmpty(rulesHash).Hash {
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

func capacityReferenceRegistryNodeLink(node capacityReferenceRegistryNode) capacityReferenceRegistryLink {
	return capacityReferenceRegistryLink{Count: node.Left.Count + node.Right.Count + 1,
		Hash: hashHex(append([]byte("GG-PROTOCOL-REGISTRY-NODE-v1\x00"), canonical(node)...)), Height: node.Height}
}

func validCapacityReferenceRegistryNode(node capacityReferenceRegistryNode, rules capacityReferenceRegistryRules, rulesHash string) bool {
	if node.Schema != "gg.protocol.registry-node.v1" || node.Rules != rulesHash || !pubPattern.MatchString(node.Key) ||
		len(node.Value) == 0 || len(node.Value) > rules.MaxValueBytes || !validCapacityReferenceRegistryLink(node.Left, rules, rulesHash) ||
		!validCapacityReferenceRegistryLink(node.Right, rules, rulesHash) || node.Left.Count >= rules.MaxEntries || node.Right.Count > rules.MaxEntries-1-node.Left.Count {
		return false
	}
	height := node.Left.Height
	if node.Right.Height > height {
		height = node.Right.Height
	}
	difference := node.Left.Height - node.Right.Height
	return difference >= -1 && difference <= 1 && node.Height == height+1 && validCapacityReferenceRegistryLink(capacityReferenceRegistryNodeLink(node), rules, rulesHash)
}

func newCapacityReferenceRegistry(rules capacityReferenceRegistryRules) (capacityReferenceRegistryTree, error) {
	if !rules.valid() {
		return capacityReferenceRegistryTree{}, errCapacityReferenceRegistry
	}
	rulesHash := rules.hash()
	return capacityReferenceRegistryTree{rules: rules, rulesHash: rulesHash, root: capacityReferenceRegistryRef{link: capacityReferenceRegistryEmpty(rulesHash)}}, nil
}

func (tree capacityReferenceRegistryTree) load(ctx context.Context, ref capacityReferenceRegistryRef, lower, upper string) (*capacityReferenceRegistryNode, capacityReferenceRegistryRef, capacityReferenceRegistryRef, error) {
	if err := ctx.Err(); err != nil {
		return nil, capacityReferenceRegistryRef{}, capacityReferenceRegistryRef{}, err
	}
	if !validCapacityReferenceRegistryLink(ref.link, tree.rules, tree.rulesHash) {
		return nil, capacityReferenceRegistryRef{}, capacityReferenceRegistryRef{}, errCapacityReferenceRegistry
	}
	if ref.link.Count == 0 {
		if ref.node != nil {
			return nil, capacityReferenceRegistryRef{}, capacityReferenceRegistryRef{}, errCapacityReferenceRegistry
		}
		return nil, capacityReferenceRegistryRef{}, capacityReferenceRegistryRef{}, nil
	}
	var node capacityReferenceRegistryNode
	var left, right capacityReferenceRegistryRef
	if ref.node != nil {
		node, left, right = ref.node.public, ref.node.left, ref.node.right
		if left.link != node.Left || right.link != node.Right {
			return nil, left, right, errCapacityReferenceRegistry
		}
	} else {
		if tree.read == nil {
			return nil, left, right, errCapacityReferenceRegistry
		}
		var err error
		node, err = tree.read(ref.link.Hash)
		if err != nil {
			return nil, left, right, err
		}
		left, right = capacityReferenceRegistryRef{link: node.Left}, capacityReferenceRegistryRef{link: node.Right}
	}
	if !validCapacityReferenceRegistryNode(node, tree.rules, tree.rulesHash) || capacityReferenceRegistryNodeLink(node) != ref.link ||
		lower != "" && node.Key <= lower || upper != "" && node.Key >= upper {
		return nil, left, right, errCapacityReferenceRegistry
	}
	return &node, left, right, nil
}

func (tree capacityReferenceRegistryTree) make(key string, value []byte, left, right capacityReferenceRegistryRef) (capacityReferenceRegistryRef, error) {
	height := left.link.Height
	if right.link.Height > height {
		height = right.link.Height
	}
	node := capacityReferenceRegistryNode{Height: height + 1, Key: key, Left: left.link, Right: right.link, Rules: tree.rulesHash,
		Schema: "gg.protocol.registry-node.v1", Value: append([]byte(nil), value...)}
	if !validCapacityReferenceRegistryNode(node, tree.rules, tree.rulesHash) {
		return capacityReferenceRegistryRef{}, errCapacityReferenceRegistry
	}
	return capacityReferenceRegistryRef{link: capacityReferenceRegistryNodeLink(node), node: &capacityReferenceRegistryPrivateNode{public: node, left: left, right: right}}, nil
}

func (tree capacityReferenceRegistryTree) balance(ctx context.Context, key string, value []byte, left, right capacityReferenceRegistryRef) (capacityReferenceRegistryRef, error) {
	difference := left.link.Height - right.link.Height
	if difference >= -1 && difference <= 1 {
		return tree.make(key, value, left, right)
	}
	if difference == 2 {
		node, ll, lr, err := tree.load(ctx, left, "", key)
		if err != nil || node == nil {
			return capacityReferenceRegistryRef{}, errCapacityReferenceRegistry
		}
		if ll.link.Height >= lr.link.Height {
			updated, err := tree.make(key, value, lr, right)
			if err != nil {
				return capacityReferenceRegistryRef{}, err
			}
			return tree.make(node.Key, node.Value, ll, updated)
		}
		middle, ml, mr, err := tree.load(ctx, lr, node.Key, key)
		if err != nil || middle == nil {
			return capacityReferenceRegistryRef{}, errCapacityReferenceRegistry
		}
		a, err := tree.make(node.Key, node.Value, ll, ml)
		if err != nil {
			return capacityReferenceRegistryRef{}, err
		}
		b, err := tree.make(key, value, mr, right)
		if err != nil {
			return capacityReferenceRegistryRef{}, err
		}
		return tree.make(middle.Key, middle.Value, a, b)
	}
	if difference == -2 {
		node, rl, rr, err := tree.load(ctx, right, key, "")
		if err != nil || node == nil {
			return capacityReferenceRegistryRef{}, errCapacityReferenceRegistry
		}
		if rr.link.Height >= rl.link.Height {
			updated, err := tree.make(key, value, left, rl)
			if err != nil {
				return capacityReferenceRegistryRef{}, err
			}
			return tree.make(node.Key, node.Value, updated, rr)
		}
		middle, ml, mr, err := tree.load(ctx, rl, key, node.Key)
		if err != nil || middle == nil {
			return capacityReferenceRegistryRef{}, errCapacityReferenceRegistry
		}
		a, err := tree.make(key, value, left, ml)
		if err != nil {
			return capacityReferenceRegistryRef{}, err
		}
		b, err := tree.make(node.Key, node.Value, mr, rr)
		if err != nil {
			return capacityReferenceRegistryRef{}, err
		}
		return tree.make(middle.Key, middle.Value, a, b)
	}
	return capacityReferenceRegistryRef{}, errCapacityReferenceRegistry
}

func (tree capacityReferenceRegistryTree) put(ctx context.Context, ref capacityReferenceRegistryRef, key string, value []byte, depth int, lower, upper string) (capacityReferenceRegistryRef, error) {
	if depth > capacityReferenceRegistryPathMax {
		return capacityReferenceRegistryRef{}, errCapacityReferenceRegistry
	}
	node, left, right, err := tree.load(ctx, ref, lower, upper)
	if err != nil {
		return capacityReferenceRegistryRef{}, err
	}
	if node == nil {
		empty := capacityReferenceRegistryRef{link: capacityReferenceRegistryEmpty(tree.rulesHash)}
		return tree.make(key, value, empty, empty)
	}
	if depth == capacityReferenceRegistryPathMax {
		return capacityReferenceRegistryRef{}, errCapacityReferenceRegistry
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
		return capacityReferenceRegistryRef{}, err
	}
	return tree.balance(ctx, node.Key, node.Value, left, right)
}

func (tree capacityReferenceRegistryTree) set(ctx context.Context, key string, value []byte) (capacityReferenceRegistryTree, error) {
	if !pubPattern.MatchString(key) || len(value) == 0 || len(value) > tree.rules.MaxValueBytes {
		return tree, errCapacityReferenceRegistry
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

func (tree capacityReferenceRegistryTree) get(ctx context.Context, key string) ([]byte, bool, error) {
	if !pubPattern.MatchString(key) {
		return nil, false, errCapacityReferenceRegistry
	}
	ref, lower, upper := tree.root, "", ""
	for depth := 0; depth <= capacityReferenceRegistryPathMax; depth++ {
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
	return nil, false, errCapacityReferenceRegistry
}

func (tree capacityReferenceRegistryTree) proof(ctx context.Context, key string) (capacityReferenceRegistryProof, error) {
	proof := capacityReferenceRegistryProof{Key: key, Path: []capacityReferenceRegistryNode{}, Rules: tree.rulesHash, Schema: "gg.protocol.registry-proof.v1"}
	if !pubPattern.MatchString(key) {
		return proof, errCapacityReferenceRegistry
	}
	ref, lower, upper := tree.root, "", ""
	for depth := 0; depth <= capacityReferenceRegistryPathMax; depth++ {
		node, left, right, err := tree.load(ctx, ref, lower, upper)
		if err != nil {
			return proof, err
		}
		if node == nil {
			return proof, nil
		}
		if depth == capacityReferenceRegistryPathMax {
			return proof, errCapacityReferenceRegistry
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
	return proof, errCapacityReferenceRegistry
}

func verifyCapacityReferenceRegistryProof(ctx context.Context, proof capacityReferenceRegistryProof, expected capacityReferenceRegistryLink, rules capacityReferenceRegistryRules, expectedKey string) ([]byte, bool, error) {
	if !pubPattern.MatchString(expectedKey) || proof.Key != expectedKey || proof.Schema != "gg.protocol.registry-proof.v1" || proof.Rules != rules.hash() ||
		len(proof.Path) > capacityReferenceRegistryPathMax || !validCapacityReferenceRegistryLink(expected, rules, rules.hash()) {
		return nil, false, errCapacityReferenceRegistry
	}
	ref, lower, upper := expected, "", ""
	for index, node := range proof.Path {
		if err := ctx.Err(); err != nil {
			return nil, false, err
		}
		if !validCapacityReferenceRegistryNode(node, rules, proof.Rules) || capacityReferenceRegistryNodeLink(node) != ref ||
			lower != "" && node.Key <= lower || upper != "" && node.Key >= upper {
			return nil, false, errCapacityReferenceRegistry
		}
		if expectedKey == node.Key {
			if !proof.Exists || index != len(proof.Path)-1 {
				return nil, false, errCapacityReferenceRegistry
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
	if proof.Exists || ref != capacityReferenceRegistryEmpty(proof.Rules) {
		return nil, false, errCapacityReferenceRegistry
	}
	return nil, false, nil
}

func (tree capacityReferenceRegistryTree) stage(ctx context.Context, save func(string, []byte) error) error {
	stack := []capacityReferenceRegistryRef{tree.root}
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
		if len(seen) >= capacityReferenceRegistryStageMax {
			return errCapacityReferenceRegistry
		}
		node := ref.node.public
		if !validCapacityReferenceRegistryNode(node, tree.rules, tree.rulesHash) || capacityReferenceRegistryNodeLink(node) != ref.link ||
			ref.node.left.link != node.Left || ref.node.right.link != node.Right {
			return errCapacityReferenceRegistry
		}
		raw := canonical(node)
		if len(raw) > tree.rules.MaxValueBytes*2+2048 {
			return errCapacityReferenceRegistry
		}
		if err := save(ref.link.Hash, raw); err != nil {
			return err
		}
		seen[ref.link.Hash] = true
		stack = append(stack, ref.node.left, ref.node.right)
	}
	return nil
}

func (tree capacityReferenceRegistryTree) freeze(read func(string) (capacityReferenceRegistryNode, error)) (capacityReferenceRegistryTree, error) {
	if read == nil || !validCapacityReferenceRegistryLink(tree.root.link, tree.rules, tree.rulesHash) {
		return tree, errCapacityReferenceRegistry
	}
	result := tree
	result.root = capacityReferenceRegistryRef{link: tree.root.link}
	result.read = read
	return result, nil
}

func (tree capacityReferenceRegistryTree) walk(ctx context.Context, maximum uint64, visit func(string, []byte) error) error {
	if tree.root.link.Count > maximum {
		return errCapacityReferenceRegistry
	}
	type item struct {
		ref          capacityReferenceRegistryRef
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
				return errCapacityReferenceRegistry
			}
			if err = visit(node.Key, append([]byte(nil), node.Value...)); err != nil {
				return err
			}
			previous = node.Key
			count++
			continue
		}
		if len(stack) > 2*capacityReferenceRegistryPathMax {
			return errCapacityReferenceRegistry
		}
		stack = append(stack, item{ref: right, lower: node.Key, upper: row.upper}, item{ref: row.ref, lower: row.lower, upper: row.upper, emit: true}, item{ref: left, lower: row.lower, upper: node.Key})
	}
	if count != tree.root.link.Count {
		return errCapacityReferenceRegistry
	}
	return nil
}

func decodeCapacityReferenceRegistryNode(raw []byte, expected capacityReferenceRegistryLink, rules capacityReferenceRegistryRules) (capacityReferenceRegistryNode, error) {
	var node capacityReferenceRegistryNode
	if len(raw) == 0 || len(raw) > rules.MaxValueBytes*2+2048 || decodeStrict(raw, &node) != nil || !bytes.Equal(raw, canonical(node)) ||
		!validCapacityReferenceRegistryNode(node, rules, rules.hash()) || capacityReferenceRegistryNodeLink(node) != expected {
		return node, errCapacityReferenceRegistry
	}
	return node, nil
}
