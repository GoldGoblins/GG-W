package main

// Membership witnesses bind public DAG records to the native AppHash. They
// verify certified membership; they do not claim local replay or monetary use.
import (
	"bytes"
	"encoding/hex"
	"errors"
	"strconv"
)

type DagAccountProof struct {
	Commitment  DagCommitment `json:"commitment"`
	GenesisHash string        `json:"genesis_hash"`
	Height      int64         `json:"height"`
	Index       int           `json:"index"`
	Leaf        Account       `json:"leaf"`
	Path        []PathItem    `json:"path"`
	Schema      string        `json:"schema"`
	StateRoot   string        `json:"state_root"`
}

type DagBlockProof struct {
	Commitment  DagCommitment `json:"commitment"`
	GenesisHash string        `json:"genesis_hash"`
	Height      int64         `json:"height"`
	Leaf        DagOrderLeaf  `json:"leaf"`
	Path        []PathItem    `json:"path"`
	Schema      string        `json:"schema"`
	StateRoot   string        `json:"state_root"`
}

const DagOrderPageSize = 32

type DagOrderWitness struct {
	Leaf DagOrderLeaf `json:"leaf"`
	Path []PathItem   `json:"path"`
}

// Start is a zero-based cursor. Every nonterminal page has exactly32 items;
// the final page contains all remaining leaves. No caller-selected count can
// silently skip data, and context is shared rather than repeated per witness.
type DagOrderPage struct {
	Commitment  DagCommitment     `json:"commitment"`
	Complete    bool              `json:"complete"`
	GenesisHash string            `json:"genesis_hash"`
	Height      int64             `json:"height"`
	Items       []DagOrderWitness `json:"items"`
	Schema      string            `json:"schema"`
	Start       int               `json:"start"`
	StateRoot   string            `json:"state_root"`
}

func dagPath[T any](values []T, index int, domain string) ([]PathItem, error) {
	if index < 0 || index >= len(values) {
		return nil, errors.New("GG_DAG_PROOF_INDEX")
	}
	return dagPathFromLevels(dagTree(values, domain), index), nil
}

func dagPathFromLevels(levels [][]string, index int) []PathItem {
	path := []PathItem{}
	for _, level := range levels[:len(levels)-1] {
		sibling, side := index^1, "right"
		if index%2 == 1 {
			side = "left"
		}
		if sibling >= len(level) {
			sibling = index
		}
		path = append(path, PathItem{Hash: level[sibling], Side: side})
		index /= 2
	}
	return path
}

func verifyDagPath[T any](leaf T, path []PathItem, index, count int, root, domain string) error {
	if index < 0 || index >= count || count > DagMaxRecords || !pubPattern.MatchString(root) {
		return errors.New("GG_DAG_PROOF_INDEX")
	}
	value := dagDigest(domain+"L\x00", leaf)
	stepIndex := 0
	for count > 1 {
		if stepIndex >= len(path) {
			return errors.New("GG_DAG_PROOF_PATH_LENGTH")
		}
		step := path[stepIndex]
		side := "right"
		if index%2 == 1 {
			side = "left"
		}
		if step.Side != side || !pubPattern.MatchString(step.Hash) || index^1 >= count && step.Hash != value {
			return errors.New("GG_DAG_PROOF_PATH")
		}
		left, right := value, step.Hash
		if side == "left" {
			left, right = step.Hash, value
		}
		a, _ := hex.DecodeString(left)
		b, _ := hex.DecodeString(right)
		value = hashHex(append(append([]byte(domain+"N\x00"), a...), b...))
		index /= 2
		count = (count + 1) / 2
		stepIndex++
	}
	if stepIndex != len(path) || value != root {
		return errors.New("GG_DAG_PROOF_ROOT")
	}
	return nil
}

func dagProofContext(commitment DagCommitment, anchor string, height int64, root string, state State) error {
	if state.DAG == nil || anchor != state.GenesisHash || height != state.Height || root != state.StateRoot ||
		!bytes.Equal(canonical(commitment), canonical(state.DAG)) {
		return errors.New("GG_DAG_PROOF_CONTEXT")
	}
	return nil
}

func verifyDagAccountProof(proof DagAccountProof, state State, source DagSource) error {
	if proof.Schema != "gg.dag.account-proof.v1" || dagProofContext(proof.Commitment, proof.GenesisHash, proof.Height, proof.StateRoot, state) != nil ||
		proof.Index < 0 || proof.Index >= len(source.Accounts) || proof.Leaf.Address != source.Accounts[proof.Index] || proof.Leaf.Nonce > DagAllocation {
		return errors.New("GG_DAG_ACCOUNT_PROOF_CONTEXT")
	}
	balance, err := strconv.ParseUint(proof.Leaf.Balance, 10, 64)
	if err != nil || !uintPattern.MatchString(proof.Leaf.Balance) || balance > 6*DagAllocation {
		return errors.New("GG_DAG_ACCOUNT_PROOF_BALANCE")
	}
	return verifyDagPath(proof.Leaf, proof.Path, proof.Index, len(source.Accounts), state.DAG.AccountRoot, "GG-DAG-ACCOUNT-v1\x00")
}

func verifyDagBlockProof(proof DagBlockProof, state State, source DagSource) error {
	if proof.Schema != "gg.dag.block-proof.v1" || dagProofContext(proof.Commitment, proof.GenesisHash, proof.Height, proof.StateRoot, state) != nil ||
		!pubPattern.MatchString(proof.Leaf.Hash) || proof.Leaf.Transactions < 0 || proof.Leaf.Transactions > DagMaxBlockTransactions ||
		proof.Leaf.Sequence < 1 || proof.Leaf.Sequence > uint64(state.DAG.Blocks) {
		return errors.New("GG_DAG_BLOCK_PROOF_CONTEXT")
	}
	allowed := false
	for _, producer := range source.AllowedProducers {
		allowed = allowed || proof.Leaf.Producer == producer
	}
	if !allowed {
		return errors.New("GG_DAG_BLOCK_PROOF_PRODUCER")
	}
	return verifyDagPath(proof.Leaf, proof.Path, proof.Leaf.Index-1, state.DAG.Blocks, state.DAG.OrderRoot, "GG-DAG-FINALIZED-ORDER-v1\x00")
}

func dagAccountProofFor(execution *DagExecution, state State, address string) (DagAccountProof, error) {
	for i, account := range execution.Accounts {
		if account.Address == address {
			path, err := dagPath(execution.Accounts, i, "GG-DAG-ACCOUNT-v1\x00")
			return DagAccountProof{Commitment: execution.Commitment, GenesisHash: state.GenesisHash, Height: state.Height,
				Index: i, Leaf: account, Path: path, Schema: "gg.dag.account-proof.v1", StateRoot: state.StateRoot}, err
		}
	}
	return DagAccountProof{}, errors.New("GG_DAG_UNKNOWN_ACCOUNT")
}

func dagBlockProofFor(execution *DagExecution, state State, identifier string) (DagBlockProof, error) {
	order, err := execution.orderList()
	if err != nil {
		return DagBlockProof{}, err
	}
	for i, block := range order {
		if block.Hash == identifier {
			path, err := dagPath(order, i, "GG-DAG-FINALIZED-ORDER-v1\x00")
			return DagBlockProof{Commitment: execution.Commitment, GenesisHash: state.GenesisHash, Height: state.Height,
				Leaf: block, Path: path, Schema: "gg.dag.block-proof.v1", StateRoot: state.StateRoot}, err
		}
	}
	return DagBlockProof{}, errors.New("GG_DAG_UNKNOWN_BLOCK")
}

func dagOrderPageFor(execution *DagExecution, state State, start int) (DagOrderPage, error) {
	order, err := execution.orderList()
	if err != nil {
		return DagOrderPage{}, err
	}
	page := DagOrderPage{Commitment: execution.Commitment, GenesisHash: state.GenesisHash, Height: state.Height,
		Schema: "gg.dag.order-page.v1", Start: start, StateRoot: state.StateRoot, Items: []DagOrderWitness{}}
	if start < 0 || start > len(order) || start%DagOrderPageSize != 0 || start == len(order) && start != 0 {
		return DagOrderPage{}, errors.New("GG_DAG_ORDER_PAGE_CURSOR")
	}
	end := start + DagOrderPageSize
	if end > len(order) {
		end = len(order)
	}
	page.Complete = end == len(order)
	if start < end {
		levels := dagTree(order, "GG-DAG-FINALIZED-ORDER-v1\x00")
		for index := start; index < end; index++ {
			page.Items = append(page.Items, DagOrderWitness{Leaf: order[index], Path: dagPathFromLevels(levels, index)})
		}
	}
	return page, nil
}

func verifyDagOrderPage(page DagOrderPage, state State, source DagSource) error {
	if page.Schema != "gg.dag.order-page.v1" || page.Items == nil ||
		dagProofContext(page.Commitment, page.GenesisHash, page.Height, page.StateRoot, state) != nil ||
		page.Start < 0 || page.Start > state.DAG.Blocks || page.Start%DagOrderPageSize != 0 ||
		page.Start == state.DAG.Blocks && page.Start != 0 {
		return errors.New("GG_DAG_ORDER_PAGE_CONTEXT")
	}
	count := state.DAG.Blocks - page.Start
	if count > DagOrderPageSize {
		count = DagOrderPageSize
	}
	if len(page.Items) != count || page.Complete != (page.Start+count == state.DAG.Blocks) {
		return errors.New("GG_DAG_ORDER_PAGE_LENGTH")
	}
	for index, witness := range page.Items {
		if witness.Leaf.Index != page.Start+index+1 {
			return errors.New("GG_DAG_ORDER_PAGE_INDEX")
		}
		proof := DagBlockProof{Commitment: page.Commitment, GenesisHash: page.GenesisHash, Height: page.Height,
			Leaf: witness.Leaf, Path: witness.Path, Schema: "gg.dag.block-proof.v1", StateRoot: page.StateRoot}
		if err := verifyDagBlockProof(proof, state, source); err != nil {
			return err
		}
	}
	return nil
}
