//go:build !js

package main

// Validate the metadata extension independently of the candidate's mutable
// frontier and history. The base is captured only after atomic Sync, or after
// complete signed recovery. Re-inserting the new entries into that immutable
// authenticated root proves exact prefix preservation without a full scan.
import (
	"errors"
)

type dagCanonicalPrefix struct {
	commitment        DagCommitment
	historyRoot       string
	frontier          dagOrderAccumulator
	heads             [6]string
	sequences, nonces [6]uint64
	bytes             int
}

type dagValidatedTransition struct {
	leaves   []DagOrderLeaf
	selected bool
}

func canonicalPrefixFor(execution *DagExecution) (*dagCanonicalPrefix, error) {
	if execution == nil || execution.proofOrder != nil || len(execution.heads) != 6 || len(execution.sequences) != 6 || len(execution.nonces) != 6 {
		return nil, errDagHistoryUnavailable
	}
	prefix := &dagCanonicalPrefix{commitment: execution.Commitment, historyRoot: execution.history.root.id(), frontier: execution.orderRoot, bytes: execution.bytes}
	copy(prefix.heads[:], execution.heads)
	copy(prefix.sequences[:], execution.sequences)
	copy(prefix.nonces[:], execution.nonces)
	return prefix, nil
}

// Hash-addressed old nodes are authenticated when read. Every attached new
// object must also bind its actual child refs to its canonical body. Checking
// objects rather than just hash strings prevents inconsistent RAM aliases.
func validateNewHistoryObjects(tree dagHistory) error {
	seen := map[*dagHistoryNode]bool{}
	var check func(dagHistoryRef, int) error
	check = func(ref dagHistoryRef, depth int) error {
		if ref.node == nil {
			return nil
		}
		node := ref.node
		if depth >= 64 || !validHistoryBody(node.body) || historyDigest(node.body) != ref.id() ||
			node.body.Left != node.left.id() || node.body.Right != node.right.id() {
			return errDagHistoryUnavailable
		}
		if seen[node] {
			return nil
		}
		seen[node] = true
		if len(seen) > 2*DagMaxRecords {
			return errDagHistoryUnavailable
		}
		if err := check(node.left, depth+1); err != nil {
			return err
		}
		return check(node.right, depth+1)
	}
	return check(tree.root, 0)
}

func transitionCountersMatch(execution *DagExecution, prefix *dagCanonicalPrefix) bool {
	if len(execution.heads) != 6 || len(execution.sequences) != 6 || len(execution.nonces) != 6 || execution.bytes != prefix.bytes || execution.orderRoot != prefix.frontier {
		return false
	}
	for i, producer := range execution.Source.Genesis.Producers {
		if execution.heads[i] != prefix.heads[i] || execution.sequences[i] != prefix.sequences[i] || execution.nonces[i] != prefix.nonces[i] {
			return false
		}
		found := false
		for _, account := range execution.Accounts {
			if account.Address == producer {
				found = true
				if account.Nonce != prefix.nonces[i] {
					return false
				}
			}
		}
		if !found {
			return false
		}
	}
	return true
}

func (store *dagStore) validateTransition(execution *DagExecution) (dagValidatedTransition, error) {
	result := dagValidatedTransition{}
	invalid := errors.New("GG_DAG_STORE_UNVERIFIED")
	if execution == nil || execution.proofOrder != nil || execution.Anchor != store.anchor ||
		dagDigest("GG-DAG-CONSENSUS-SOURCE-v1\x00", execution.Source) != store.meta.SourceHash ||
		store.validPublicSnapshot(publicSnapshot(execution)) != nil {
		return result, invalid
	}
	sealed := *execution
	sealed.seal()
	if sealed.Commitment != execution.Commitment {
		return result, invalid
	}
	if err := validateNewHistoryObjects(execution.history); err != nil {
		return result, err
	}
	if store.meta.PublicIndex == 0 {
		// Standalone, unselected storage containers retain the independent old
		// full-order path. Live operation leaves this branch at genesis Commit.
		order, err := execution.orderList()
		if err != nil {
			return result, err
		}
		if store.validPublicOrder(order, publicSnapshot(execution)) != nil || dagRoot(order, dagOrderDomain) != execution.orderRoot.root() {
			return result, invalid
		}
		result.leaves = order
		result.selected = execution.Commitment.Checkpoint == 0
		return result, nil
	}
	prefix := store.prefix
	if store.meta.PublicIndex != 2 || prefix == nil || prefix.commitment != store.selected || prefix.historyRoot != store.meta.HistoryRoot ||
		prefix.frontier.count != uint64(prefix.commitment.Blocks) || prefix.frontier.root() != prefix.commitment.OrderRoot {
		return result, errDagHistoryUnavailable
	}
	if execution.Commitment == prefix.commitment {
		if execution.history.root.id() != prefix.historyRoot || !transitionCountersMatch(execution, prefix) {
			return result, invalid
		}
		result.selected = true
		return result, nil
	}
	value := execution.Commitment
	count := value.Blocks - prefix.commitment.Blocks
	if value.Checkpoint != prefix.commitment.Checkpoint+1 || value.Previous != prefix.commitment.ManifestHash ||
		count < 1 || count > DagMaxBatchBlocks || count != len(execution.Manifest.Blocks) || value.Transactions < prefix.commitment.Transactions {
		return result, invalid
	}
	expected := *prefix
	history := dagHistory{root: dagHistoryRef{hash: prefix.historyRoot}, read: store.readHistoryNode}
	allowed := [6]bool{}
	for _, producer := range store.source.AllowedProducers {
		allowed[producer] = true
	}
	result.leaves = make([]DagOrderLeaf, 0, count)
	transactions := prefix.commitment.Transactions
	for offset := 0; offset < count; offset++ {
		index := prefix.commitment.Blocks + offset + 1
		entry, found, err := execution.history.get(historyOrderKey(index))
		if err != nil {
			return dagValidatedTransition{}, err
		}
		if !found || entry.Order == nil {
			return dagValidatedTransition{}, invalid
		}
		leaf := *entry.Order
		if leaf.Index != index || !pubPattern.MatchString(leaf.Hash) || leaf.Producer < 0 || leaf.Producer >= 6 || !allowed[leaf.Producer] ||
			leaf.Sequence != expected.sequences[leaf.Producer]+1 || leaf.Transactions < 0 || leaf.Transactions > DagMaxBlockTransactions {
			return dagValidatedTransition{}, invalid
		}
		record, found, err := execution.historyRecord(leaf.Hash)
		if err != nil {
			return dagValidatedTransition{}, err
		}
		pending, owned := execution.pending[leaf.Hash]
		if !found || !owned || record.Index != index || record.Hash != leaf.Hash || record.WireHash != execution.Manifest.Blocks[offset] ||
			pending.Hash != record.Hash || pending.Index != record.Index || pending.Rank != record.Rank || pending.WireHash != record.WireHash || pending.WireBytes != record.WireBytes {
			return dagValidatedTransition{}, invalid
		}
		info := dagHistoryRecord{Hash: record.Hash, Index: index, Rank: record.Rank, WireBytes: record.WireBytes, WireHash: record.WireHash}
		// Duplicate hashes, including any old prefix hash, cannot be inserted
		// into the base again. Every modified search path authenticates its old
		// nodes. The same deterministic b/ then o/ insertion order is retained.
		history, err = history.put("b/"+leaf.Hash, dagHistoryValue{Record: &info})
		if err != nil {
			return dagValidatedTransition{}, err
		}
		copy := leaf
		history, err = history.put(historyOrderKey(index), dagHistoryValue{Order: &copy})
		if err != nil {
			return dagValidatedTransition{}, err
		}
		expected.frontier.append(leaf)
		expected.heads[leaf.Producer] = leaf.Hash
		expected.sequences[leaf.Producer]++
		expected.nonces[leaf.Producer] += uint64(leaf.Transactions)
		expected.bytes += record.WireBytes
		transactions += uint64(leaf.Transactions)
		result.leaves = append(result.leaves, leaf)
	}
	if history.root.id() != execution.history.root.id() || !transitionCountersMatch(execution, &expected) || transactions != value.Transactions {
		return dagValidatedTransition{}, invalid
	}
	result.selected = true
	return result, nil
}
