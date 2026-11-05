//go:build !js

package main

import (
	"context"
	"errors"
	"math/bits"

	"github.com/syndtr/goleveldb/leveldb"
)

const dagPublicQueryReadLimit = 256

func (store *dagStore) publicProof(ctx context.Context, state State, path, identifier string, start int) (payload any, err error) {
	defer func() {
		if ctx.Err() != nil {
			payload = nil
			err = ctx.Err()
		}
	}()
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	if state.DAG == nil || state.GenesisHash != store.anchor || validateDagCommitment(*state.DAG, store.source, store.anchor) != nil {
		return nil, errors.New("GG_DAG_PUBLIC_CONTEXT")
	}
	count := state.DAG.Blocks
	switch path {
	case "/gg/dag/order-page":
		if start < 0 || start > count || start%DagOrderPageSize != 0 || start == count && start != 0 {
			return nil, errors.New("GG_DAG_ORDER_PAGE_CURSOR")
		}
	case "/gg/dag/account-proof", "/gg/dag/block-proof":
		if !pubPattern.MatchString(identifier) {
			return nil, errors.New("GG_DAG_PROOF_IDENTIFIER")
		}
	default:
		return nil, errors.New("GG_DAG_PROOF_PATH")
	}
	store.mu.Lock()
	if store.db == nil || store.failed || store.meta.PublicIndex != 2 {
		store.mu.Unlock()
		return nil, errors.New("GG_DAG_STORE_FAULT")
	}
	if store.activeReaders >= dagPublicMaxReaders {
		store.mu.Unlock()
		return nil, errors.New("GG_DAG_PUBLIC_BUSY")
	}
	snapshot, err := store.db.GetSnapshot()
	if err != nil {
		store.mu.Unlock()
		return nil, errors.New("GG_DAG_PUBLIC_SNAPSHOT")
	}
	store.readers.Add(1)
	store.activeReaders++
	hook := store.beforePublicRead
	store.mu.Unlock()
	defer func() { store.mu.Lock(); store.activeReaders--; store.mu.Unlock(); store.readers.Done() }()
	defer snapshot.Release()
	reads := 0
	read := func(key string, target any) error {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		reads++
		if reads > dagPublicQueryReadLimit {
			return errors.New("GG_DAG_PUBLIC_READ_LIMIT")
		}
		if hook != nil {
			hook(key)
		}
		if ctx.Err() != nil {
			return ctx.Err()
		}
		raw, err := snapshot.Get([]byte(key), nil)
		if err != nil {
			if err == leveldb.ErrNotFound {
				return err
			}
			return errors.New("GG_DAG_PUBLIC_READ")
		}
		return decodePublic(raw, target)
	}
	var value dagPublicSnapshot
	if err = read(publicSnapshotKey(*state.DAG), &value); err != nil {
		return nil, err
	}
	if value.Commitment != *state.DAG || store.validPublicSnapshot(value) != nil {
		return nil, errors.New("GG_DAG_PUBLIC_CONTEXT")
	}
	if path == "/gg/dag/account-proof" {
		proof, err := dagAccountProofFor(&DagExecution{Accounts: value.Accounts, Commitment: value.Commitment}, state, identifier)
		if err == nil {
			err = verifyDagAccountProof(proof, state, store.source)
		}
		return proof, err
	}
	nodes := map[string]string{}
	var subtree func(int, int) (string, error)
	subtree = func(level, start int) (string, error) {
		if ctx.Err() != nil {
			return "", ctx.Err()
		}
		if level < 0 || level >= bits.Len(uint(DagMaxRecords)) || start < 0 || start >= count || start%(1<<level) != 0 {
			return "", errors.New("GG_DAG_PUBLIC_NODE")
		}
		key := publicNodeKey(level, start)
		if hash, ok := nodes[key]; ok {
			return hash, nil
		}
		var hash string
		if start+(1<<level) <= count {
			if err := read(key, &hash); err != nil {
				return "", err
			}
			if !pubPattern.MatchString(hash) {
				return "", errors.New("GG_DAG_PUBLIC_NODE")
			}
		} else {
			left, err := subtree(level-1, start)
			if err != nil {
				return "", err
			}
			right := left
			if start+(1<<(level-1)) < count {
				right, err = subtree(level-1, start+(1<<(level-1)))
				if err != nil {
					return "", err
				}
			}
			hash = dagOrderJoin(left, right)
		}
		nodes[key] = hash
		return hash, nil
	}
	witness := func(leaf DagOrderLeaf) (DagOrderWitness, error) {
		index := leaf.Index - 1
		if index < 0 || index >= count || !pubPattern.MatchString(leaf.Hash) {
			return DagOrderWitness{}, errors.New("GG_DAG_PUBLIC_ORDER")
		}
		items := []PathItem{}
		width := count
		hash := dagDigest(dagOrderDomain+"L\x00", leaf)
		for level := 0; width > 1; level++ {
			sibling := index ^ 1
			other := hash
			side := "right"
			if index%2 != 0 {
				side = "left"
			}
			if sibling < width {
				var err error
				other, err = subtree(level, sibling*(1<<level))
				if err != nil {
					return DagOrderWitness{}, err
				}
			}
			items = append(items, PathItem{Hash: other, Side: side})
			if side == "left" {
				hash = dagOrderJoin(other, hash)
			} else {
				hash = dagOrderJoin(hash, other)
			}
			index /= 2
			width = (width + 1) / 2
		}
		if hash != state.DAG.OrderRoot {
			return DagOrderWitness{}, errors.New("GG_DAG_PROOF_ROOT")
		}
		return DagOrderWitness{Leaf: leaf, Path: items}, nil
	}
	readLeaf := func(index int) (DagOrderLeaf, error) {
		var leaf DagOrderLeaf
		if index < 1 || index > count {
			return leaf, errors.New("GG_DAG_UNKNOWN_BLOCK")
		}
		if err := read(publicOrderKey(index), &leaf); err != nil {
			return leaf, err
		}
		if leaf.Index != index {
			return leaf, errors.New("GG_DAG_PUBLIC_ORDER")
		}
		return leaf, nil
	}
	if path == "/gg/dag/block-proof" {
		var index int
		if err := read(publicRefKey(identifier), &index); err != nil {
			if err == leveldb.ErrNotFound {
				return nil, errors.New("GG_DAG_UNKNOWN_BLOCK")
			}
			return nil, err
		}
		leaf, err := readLeaf(index)
		if err != nil {
			return nil, err
		}
		if leaf.Hash != identifier {
			return nil, errors.New("GG_DAG_PUBLIC_REF")
		}
		item, err := witness(leaf)
		if err != nil {
			return nil, err
		}
		proof := DagBlockProof{Commitment: value.Commitment, GenesisHash: state.GenesisHash, Height: state.Height, Leaf: item.Leaf, Path: item.Path,
			Schema: "gg.dag.block-proof.v1", StateRoot: state.StateRoot}
		return proof, verifyDagBlockProof(proof, state, store.source)
	}
	page := DagOrderPage{Commitment: value.Commitment, GenesisHash: state.GenesisHash, Height: state.Height, Items: []DagOrderWitness{},
		Schema: "gg.dag.order-page.v1", Start: start, StateRoot: state.StateRoot}
	end := start + DagOrderPageSize
	if end > count {
		end = count
	}
	page.Complete = end == count
	leaves := []DagOrderLeaf{}
	for index := start + 1; index <= end; index++ {
		leaf, err := readLeaf(index)
		if err != nil {
			return nil, err
		}
		leaves = append(leaves, leaf)
		nodes[publicNodeKey(0, index-1)] = dagDigest(dagOrderDomain+"L\x00", leaf)
	}
	for _, leaf := range leaves {
		item, err := witness(leaf)
		if err != nil {
			return nil, err
		}
		page.Items = append(page.Items, item)
	}
	return page, verifyDagOrderPage(page, state, store.source)
}
