//go:build !js

package main

// Persist only complete aligned subtrees. Partial rightmost subtrees are
// reconstructed for the requested historical count, with the SAME odd-node
// duplication rule. No per-height copy of all Merkle nodes is necessary.
import (
	"bytes"
	"errors"
	"fmt"
	"math/bits"
	"strconv"
	"strings"

	"github.com/syndtr/goleveldb/leveldb/util"
)

func publicRefKey(hash string) string       { return "pub/h/" + hash }
func publicNodeKey(level, start int) string { return fmt.Sprintf("pub/n/%02d/%08d", level, start) }
func validPublicNodeKey(key string, count int) bool {
	parts := strings.Split(key, "/")
	if len(parts) != 4 || parts[0] != "pub" || parts[1] != "n" {
		return false
	}
	level, err := strconv.Atoi(parts[2])
	if err != nil || level < 0 || level >= bits.Len(uint(DagMaxRecords)) {
		return false
	}
	start, err := strconv.Atoi(parts[3])
	width := 1 << level
	return err == nil && start >= 0 && start%width == 0 && start <= count-width && key == publicNodeKey(level, start)
}

func appendPublicOrderEntries(leaves []DagOrderLeaf, read func(string, any) error, put func(string, any) error) error {
	for _, leaf := range leaves {
		if leaf.Index < 1 || leaf.Index > DagMaxRecords || !pubPattern.MatchString(leaf.Hash) {
			return errors.New("GG_DAG_PUBLIC_ORDER")
		}
		value := dagDigest(dagOrderDomain+"L\x00", leaf)
		for key, entry := range map[string]any{publicOrderKey(leaf.Index): leaf, publicRefKey(leaf.Hash): leaf.Index, publicNodeKey(0, leaf.Index-1): value} {
			if err := put(key, entry); err != nil {
				return err
			}
		}
		for level := 1; leaf.Index%(1<<level) == 0; level++ {
			start := leaf.Index - (1 << level)
			var left string
			if err := read(publicNodeKey(level-1, start), &left); err != nil || !pubPattern.MatchString(left) {
				return errors.New("GG_DAG_PUBLIC_NODE_MISSING")
			}
			value = dagOrderJoin(left, value)
			if err := put(publicNodeKey(level, start), value); err != nil {
				return err
			}
		}
	}
	return nil
}

// Used only AFTER authenticating every original signed block during startup.
// Even a syntactically valid rehashed index must match that independent replay.
func (store *dagStore) verifyPublicEntries(expected map[string][]byte) error {
	iterator := store.db.NewIterator(util.BytesPrefix([]byte("pub/")), nil)
	defer iterator.Release()
	count := 0
	for iterator.Next() {
		value, ok := expected[string(iterator.Key())]
		if !ok || !bytes.Equal(value, iterator.Value()) {
			return errors.New("GG_DAG_PUBLIC_REPLAY_MISMATCH")
		}
		count++
	}
	if iterator.Error() != nil || count != len(expected) {
		return errors.New("GG_DAG_PUBLIC_REPLAY_MISMATCH")
	}
	return nil
}
