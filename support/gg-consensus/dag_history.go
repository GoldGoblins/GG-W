package main

// Immutable, content-addressed AVL history. A clone shares its root; insertion
// copies only a bounded search path. Native committed roots resolve old nodes
// through an owned disk reader. Every known hash is authenticated on lookup;
// missing/corrupt storage is NOT an authenticated absence of a producer block.
import (
	"errors"
	"fmt"
	"math"
	"strings"
)

var errDagHistoryUnavailable = errors.New("GG_DAG_HISTORY_UNAVAILABLE")

type dagHistoryRecord struct {
	Hash      string `json:"hash"`
	Index     int    `json:"index"`
	Rank      int64  `json:"rank"`
	WireBytes int    `json:"wire_bytes"`
	WireHash  string `json:"wire_hash"`
}
type dagHistoryValue struct {
	Order  *DagOrderLeaf     `json:"order,omitempty"`
	Record *dagHistoryRecord `json:"record,omitempty"`
}
type dagHistoryBody struct {
	Height int             `json:"height"`
	Key    string          `json:"key"`
	Left   string          `json:"left"`
	Right  string          `json:"right"`
	Schema string          `json:"schema"`
	Value  dagHistoryValue `json:"value"`
}
type dagHistoryRef struct {
	hash string
	node *dagHistoryNode
}
type dagHistoryNode struct {
	body        dagHistoryBody
	left, right dagHistoryRef
}
type dagHistory struct {
	root      dagHistoryRef
	read      func(string) (dagHistoryBody, error)
	segmented bool // set by the segmented constructor, never by disk metadata
	protocol  bool // set only by the versioned public financial constructor
}

func (ref dagHistoryRef) id() string {
	if ref.hash == "" {
		return DagZero
	}
	return ref.hash
}
func historyDigest(body dagHistoryBody) string { return dagDigest("GG-DAG-HISTORY-NODE-v1\x00", body) }
func historyOrderKey(index int) string         { return fmt.Sprintf("o/%08d", index) }

func validHistoryBody(body dagHistoryBody) bool {
	return validHistoryBodyLimits(body, DagMaxRank, DagMaxSequence)
}

func validHistoryBodyLimits(body dagHistoryBody, rankLimit int64, sequenceLimit uint64, publicMode ...bool) bool {
	if body.Schema != "gg.dag.history-node.v1" || body.Height < 1 || body.Height > 64 || !pubPattern.MatchString(body.Left) || !pubPattern.MatchString(body.Right) {
		return false
	}
	if record := body.Value.Record; record != nil {
		return body.Value.Order == nil && body.Key == "b/"+record.Hash && pubPattern.MatchString(record.Hash) && pubPattern.MatchString(record.WireHash) &&
			record.Index >= 1 && record.Index <= DagMaxRecords && record.Rank >= 1 && record.Rank <= rankLimit && record.WireBytes > 0 && record.WireBytes <= DagMaxWire
	}
	if leaf := body.Value.Order; leaf != nil {
		producerValid := leaf.Producer >= 0 && leaf.Producer < 6 && leaf.ProducerKey == ""
		if len(publicMode) == 1 && publicMode[0] {
			producerValid = leaf.Producer == -1 && financialAccountAddress(leaf.ProducerKey)
		}
		return body.Key == historyOrderKey(leaf.Index) && leaf.Index >= 1 && leaf.Index <= DagMaxRecords && pubPattern.MatchString(leaf.Hash) &&
			producerValid && leaf.Sequence >= 1 && leaf.Sequence <= sequenceLimit && leaf.Transactions >= 0 && leaf.Transactions <= DagMaxBlockTransactions
	}
	return false
}

func (tree dagHistory) load(ref dagHistoryRef) (*dagHistoryNode, error) {
	if ref.id() == DagZero {
		return nil, nil
	}
	if ref.node != nil {
		return ref.node, nil
	}
	if tree.read == nil {
		return nil, errDagHistoryUnavailable
	}
	body, err := tree.read(ref.hash)
	valid := validHistoryBody(body)
	if tree.segmented {
		valid = validHistoryBodyLimits(body, math.MaxInt64, dagSegmentCounterMax, tree.protocol)
	}
	if err != nil || !valid || historyDigest(body) != ref.hash {
		return nil, errDagHistoryUnavailable
	}
	return &dagHistoryNode{body: body, left: dagHistoryRef{hash: body.Left}, right: dagHistoryRef{hash: body.Right}}, nil
}
func (tree dagHistory) get(key string) (dagHistoryValue, bool, error) {
	ref := tree.root
	for depth := 0; ref.id() != DagZero; depth++ {
		if depth >= 64 {
			return dagHistoryValue{}, false, errDagHistoryUnavailable
		}
		node, err := tree.load(ref)
		if err != nil {
			return dagHistoryValue{}, false, err
		}
		if key == node.body.Key {
			return node.body.Value, true, nil
		}
		if key < node.body.Key {
			ref = node.left
		} else {
			ref = node.right
		}
	}
	return dagHistoryValue{}, false, nil
}
func (tree dagHistory) height(ref dagHistoryRef) (int, error) {
	node, err := tree.load(ref)
	if node == nil {
		return 0, err
	}
	return node.body.Height, err
}
func (tree dagHistory) make(key string, value dagHistoryValue, left, right dagHistoryRef) (dagHistoryRef, error) {
	a, err := tree.height(left)
	if err != nil {
		return dagHistoryRef{}, err
	}
	b, err := tree.height(right)
	if err != nil {
		return dagHistoryRef{}, err
	}
	height := a
	if b > height {
		height = b
	}
	height++
	body := dagHistoryBody{Height: height, Key: key, Left: left.id(), Right: right.id(), Schema: "gg.dag.history-node.v1", Value: value}
	return dagHistoryRef{hash: historyDigest(body), node: &dagHistoryNode{body: body, left: left, right: right}}, nil
}
func (tree dagHistory) rotate(ref dagHistoryRef, left bool) (dagHistoryRef, error) {
	node, err := tree.load(ref)
	if err != nil || node == nil {
		return dagHistoryRef{}, errDagHistoryUnavailable
	}
	pivot := node.left
	if left {
		pivot = node.right
	}
	child, err := tree.load(pivot)
	if err != nil || child == nil {
		return dagHistoryRef{}, errDagHistoryUnavailable
	}
	if left {
		lower, err := tree.make(node.body.Key, node.body.Value, node.left, child.left)
		if err != nil {
			return dagHistoryRef{}, err
		}
		return tree.make(child.body.Key, child.body.Value, lower, child.right)
	}
	lower, err := tree.make(node.body.Key, node.body.Value, child.right, node.right)
	if err != nil {
		return dagHistoryRef{}, err
	}
	return tree.make(child.body.Key, child.body.Value, child.left, lower)
}
func (tree dagHistory) insert(ref dagHistoryRef, key string, value dagHistoryValue, depth int) (dagHistoryRef, error) {
	if depth >= 64 {
		return dagHistoryRef{}, errDagHistoryUnavailable
	}
	node, err := tree.load(ref)
	if err != nil {
		return dagHistoryRef{}, err
	}
	if node == nil {
		return tree.make(key, value, dagHistoryRef{}, dagHistoryRef{})
	}
	if key == node.body.Key {
		return dagHistoryRef{}, errors.New("GG_DAG_HISTORY_DUPLICATE")
	}
	a, b := node.left, node.right
	if key < node.body.Key {
		a, err = tree.insert(a, key, value, depth+1)
	} else {
		b, err = tree.insert(b, key, value, depth+1)
	}
	if err != nil {
		return dagHistoryRef{}, err
	}
	root, err := tree.make(node.body.Key, node.body.Value, a, b)
	if err != nil {
		return dagHistoryRef{}, err
	}
	ah, err := tree.height(a)
	if err != nil {
		return dagHistoryRef{}, err
	}
	bh, err := tree.height(b)
	if err != nil {
		return dagHistoryRef{}, err
	}
	if ah-bh > 1 {
		child, err := tree.load(a)
		if err != nil {
			return dagHistoryRef{}, err
		}
		if key > child.body.Key {
			a, err = tree.rotate(a, true)
			if err != nil {
				return dagHistoryRef{}, err
			}
			root, err = tree.make(node.body.Key, node.body.Value, a, b)
			if err != nil {
				return dagHistoryRef{}, err
			}
		}
		return tree.rotate(root, false)
	}
	if bh-ah > 1 {
		child, err := tree.load(b)
		if err != nil {
			return dagHistoryRef{}, err
		}
		if key < child.body.Key {
			b, err = tree.rotate(b, false)
			if err != nil {
				return dagHistoryRef{}, err
			}
			root, err = tree.make(node.body.Key, node.body.Value, a, b)
			if err != nil {
				return dagHistoryRef{}, err
			}
		}
		return tree.rotate(root, true)
	}
	return root, nil
}
func (tree dagHistory) put(key string, value dagHistoryValue) (dagHistory, error) {
	root, err := tree.insert(tree.root, key, value, 0)
	next := tree
	next.root = root
	return next, err
}

func (tree dagHistory) walk(ref dagHistoryRef, low, high string, visit func(dagHistoryBody) error, depth int) error {
	if depth >= 64 {
		return errDagHistoryUnavailable
	}
	node, err := tree.load(ref)
	if err != nil || node == nil {
		return err
	}
	if node.body.Key > low {
		if err = tree.walk(node.left, low, high, visit, depth+1); err != nil {
			return err
		}
	}
	if node.body.Key >= low && node.body.Key < high {
		if err = visit(node.body); err != nil {
			return err
		}
	}
	if node.body.Key < high {
		return tree.walk(node.right, low, high, visit, depth+1)
	}
	return nil
}
func (tree dagHistory) newNodes(seen map[string]bool, visit func(string, dagHistoryBody) error) error {
	var walk func(dagHistoryRef) error
	walk = func(ref dagHistoryRef) error {
		if ref.node == nil || seen[ref.id()] {
			return nil
		}
		seen[ref.id()] = true
		if err := visit(ref.id(), ref.node.body); err != nil {
			return err
		}
		if err := walk(ref.node.left); err != nil {
			return err
		}
		return walk(ref.node.right)
	}
	return walk(tree.root)
}

func (execution *DagExecution) orderCount() int {
	if execution.proofOrder != nil {
		return len(execution.proofOrder)
	}
	return int(execution.orderRoot.count)
}
func (execution *DagExecution) orderList() ([]DagOrderLeaf, error) {
	order := make([]DagOrderLeaf, 0, execution.orderCount())
	err := execution.visitOrderPrefix(execution.orderCount(), func(leaf DagOrderLeaf) error {
		order = append(order, leaf)
		return nil
	})
	if err != nil {
		return nil, errDagHistoryUnavailable
	}
	return order, nil
}

// All selected leaves are still authenticated and checked in order. Only the
// caller-requested prefix is visited; no full leaf slice or Merkle tree is
// needed by proposal validation. This is O(prefix) work, not constant time.
func (execution *DagExecution) visitOrderPrefix(count int, visit func(DagOrderLeaf) error) error {
	if count < 0 || count > execution.orderCount() || count > DagMaxRecords {
		return errDagHistoryUnavailable
	}
	seen := 0
	accept := func(leaf DagOrderLeaf) error {
		if leaf.Index != seen+1 || seen >= count {
			return errDagHistoryUnavailable
		}
		seen++
		return visit(leaf)
	}
	if execution.proofOrder != nil {
		for _, leaf := range execution.proofOrder[:count] {
			if err := accept(leaf); err != nil {
				return err
			}
		}
	} else {
		high := "p/"
		if count < execution.orderCount() {
			high = historyOrderKey(count + 1)
		}
		if err := execution.history.walk(execution.history.root, "o/", high, func(body dagHistoryBody) error {
			if body.Value.Order == nil || body.Key != historyOrderKey(body.Value.Order.Index) {
				return errDagHistoryUnavailable
			}
			return accept(*body.Value.Order)
		}, 0); err != nil {
			return err
		}
	}
	if seen != count {
		return errDagHistoryUnavailable
	}
	return nil
}

func (execution *DagExecution) orderPrefixRoot(count int) (string, error) {
	var tree dagOrderAccumulator
	if err := execution.visitOrderPrefix(count, func(leaf DagOrderLeaf) error {
		tree.append(leaf)
		return nil
	}); err != nil {
		return "", err
	}
	return tree.root(), nil
}
func (execution *DagExecution) historyRecord(hash string) (dagRecord, bool, error) {
	value, found, err := execution.history.get("b/" + hash)
	if err != nil || !found {
		return dagRecord{}, found, err
	}
	if value.Record == nil || value.Record.Hash != hash {
		return dagRecord{}, false, errDagHistoryUnavailable
	}
	item := value.Record
	record := dagRecord{Hash: hash, WireHash: item.WireHash, WireBytes: item.WireBytes, Index: item.Index, Rank: item.Rank}
	if pending, ok := execution.pending[hash]; ok {
		record.Raw = pending.Raw
	}
	return record, true, nil
}
func (execution *DagExecution) historyRank(hash string) (int64, bool, error) {
	if execution.segmentMode {
		if hash == execution.segmentParent {
			return execution.segmentRankBase, true, nil
		}
		if hash == execution.Source.GenesisHash {
			return 0, false, nil
		}
	}
	if hash == execution.Source.GenesisHash {
		return 0, true, nil
	}
	record, found, err := execution.historyRecord(hash)
	return record.Rank, found, err
}

// Strict lexical shape used before trusting a decoded disk node.
func historyKeyMatches(body dagHistoryBody) bool {
	return validHistoryBody(body) && (strings.HasPrefix(body.Key, "b/") || strings.HasPrefix(body.Key, "o/"))
}
