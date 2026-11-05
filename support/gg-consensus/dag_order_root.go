package main

// An append frontier for the EXISTING odd-duplicate binary Merkle root. This
// changes no wire schema, leaf/domain hash or proof. Value-copy on an execution
// clone keeps sibling proposals independent. Persistent full order validation
// and historical proof generation remain separate checks.
import "encoding/hex"

const dagOrderDomain = "GG-DAG-FINALIZED-ORDER-v1\x00"

type dagOrderAccumulator struct {
	count uint64
	peaks [64]string
}

func dagOrderJoin(left, right string) string {
	a, _ := hex.DecodeString(left)
	b, _ := hex.DecodeString(right)
	return hashHex(append(append([]byte(dagOrderDomain+"N\x00"), a...), b...))
}

func (tree *dagOrderAccumulator) append(leaf DagOrderLeaf) {
	value := dagDigest(dagOrderDomain+"L\x00", leaf)
	count := tree.count
	for level := 0; level < len(tree.peaks); level++ {
		if count&1 == 0 {
			tree.peaks[level] = value
			tree.count++
			return
		}
		value = dagOrderJoin(tree.peaks[level], value)
		tree.peaks[level] = ""
		count >>= 1
	}
	panic("GG_DAG_ORDER_ACCUMULATOR_OVERFLOW") // unreachable under protocol cap
}

func (tree dagOrderAccumulator) root() string {
	if tree.count == 0 {
		return hashHex([]byte(dagOrderDomain + "EMPTY\x00"))
	}
	value := ""
	height := 0
	for level, peak := range tree.peaks {
		if peak == "" {
			continue
		}
		if value == "" {
			value = peak
			height = level
			continue
		}
		for height < level {
			value = dagOrderJoin(value, value)
			height++
		}
		value = dagOrderJoin(peak, value)
		height = level + 1
	}
	return value
}
