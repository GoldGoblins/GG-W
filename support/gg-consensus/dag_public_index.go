//go:build !js

package main

// The derived public index contains no executable payload. Ordered leaves are
// stored once; each committed checkpoint adds just six account leaves. Queries
// pin a LevelDB snapshot, then do all reads/hashing outside consensus locks.
// Recovery always verifies the original signed payload before trusting an index.
import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"math/bits"
	"strconv"
	"strings"

	"github.com/syndtr/goleveldb/leveldb"
	"github.com/syndtr/goleveldb/leveldb/util"
)

const dagPublicMaxBytes uint64 = 16 * 1024 * 1024
const dagPublicValueMax = 4096
const dagPublicMaxReaders = 4

type dagPublicSnapshot struct {
	Accounts   []Account     `json:"accounts"`
	Commitment DagCommitment `json:"commitment"`
	Schema     string        `json:"schema"`
}

type dagPublicHead struct {
	Bytes      uint64        `json:"bytes"`
	Commitment DagCommitment `json:"commitment"`
	Schema     string        `json:"schema"`
}

func publicSnapshot(execution *DagExecution) dagPublicSnapshot {
	return dagPublicSnapshot{Accounts: append([]Account(nil), execution.Accounts...),
		Commitment: execution.Commitment, Schema: "gg.dag.public-snapshot.v1"}
}

func publicOrderKey(index int) string                { return fmt.Sprintf("pub/o/%04d", index) }
func publicSnapshotKey(value DagCommitment) string   { return "pub/s/" + value.ManifestHash }
func publicEntryBytes(key string, raw []byte) uint64 { return uint64(len(key) + len(raw)) }

func (store *dagStore) validPublicSnapshot(value dagPublicSnapshot) error {
	if value.Schema != "gg.dag.public-snapshot.v1" || len(value.Accounts) != len(store.source.Accounts) ||
		validateDagCommitment(value.Commitment, store.source, store.anchor) != nil ||
		dagRoot(value.Accounts, "GG-DAG-ACCOUNT-v1\x00") != value.Commitment.AccountRoot {
		return errors.New("GG_DAG_PUBLIC_ACCOUNTS")
	}
	var supply, nonces uint64
	for i, account := range value.Accounts {
		balance, err := strconv.ParseUint(account.Balance, 10, 64)
		if account.Address != store.source.Accounts[i] || err != nil || strconv.FormatUint(balance, 10) != account.Balance ||
			balance > 6*DagAllocation || account.Nonce > DagAllocation {
			return errors.New("GG_DAG_PUBLIC_ACCOUNTS")
		}
		supply += balance
		nonces += account.Nonce
	}
	if supply != 6*DagAllocation || nonces != value.Commitment.Transactions {
		return errors.New("GG_DAG_PUBLIC_ACCOUNTS")
	}
	return nil
}

func (store *dagStore) validPublicOrder(order []DagOrderLeaf, snapshot dagPublicSnapshot) error {
	if len(order) != snapshot.Commitment.Blocks || dagRoot(order, "GG-DAG-FINALIZED-ORDER-v1\x00") != snapshot.Commitment.OrderRoot {
		return errors.New("GG_DAG_PUBLIC_ORDER")
	}
	allowed := [6]bool{}
	for _, producer := range store.source.AllowedProducers {
		allowed[producer] = true
	}
	var sequences, nonces [6]uint64
	seen := make(map[string]bool, len(order))
	var transactions uint64
	for i, leaf := range order {
		if leaf.Index != i+1 || !pubPattern.MatchString(leaf.Hash) || seen[leaf.Hash] || leaf.Producer < 0 || leaf.Producer >= 6 ||
			!allowed[leaf.Producer] || leaf.Sequence != sequences[leaf.Producer]+1 || leaf.Transactions < 0 || leaf.Transactions > DagMaxBlockTransactions {
			return errors.New("GG_DAG_PUBLIC_ORDER")
		}
		seen[leaf.Hash] = true
		sequences[leaf.Producer]++
		nonces[leaf.Producer] += uint64(leaf.Transactions)
		transactions += uint64(leaf.Transactions)
	}
	if transactions != snapshot.Commitment.Transactions {
		return errors.New("GG_DAG_PUBLIC_ORDER")
	}
	for i, producer := range store.source.Genesis.Producers {
		for _, account := range snapshot.Accounts {
			if account.Address == producer && account.Nonce != nonces[i] {
				return errors.New("GG_DAG_PUBLIC_ORDER")
			}
		}
	}
	return nil
}

func decodePublic(raw []byte, target any) error {
	if len(raw) == 0 || len(raw) > dagPublicValueMax || decodeStrict(raw, target) != nil || !bytes.Equal(raw, canonical(target)) {
		return errors.New("GG_DAG_PUBLIC_ENCODING")
	}
	return nil
}

func (store *dagStore) publicHead() (dagPublicHead, error) {
	var head dagPublicHead
	raw, err := store.db.Get([]byte("pub/head"), nil)
	if err != nil || decodePublic(raw, &head) != nil || head.Schema != fmt.Sprintf("gg.dag.public-head.v%d", store.meta.PublicIndex) ||
		head.Bytes > dagPublicMaxBytes || validateDagCommitment(head.Commitment, store.source, store.anchor) != nil {
		return head, errors.New("GG_DAG_PUBLIC_HEAD")
	}
	return head, nil
}

// Opening a versioned index fails closed for missing, oversized or alien keys.
// Exact equality against the fully replayed payload is checked subsequently.
func (store *dagStore) checkPublicContents() error {
	head, err := store.publicHead()
	if err != nil {
		return err
	}
	iterator := store.db.NewIterator(util.BytesPrefix([]byte("pub/")), nil)
	defer iterator.Release()
	var size uint64
	orders, snapshots, heads, refs, nodes := 0, 0, 0, 0, 0
	for iterator.Next() {
		key, raw := string(iterator.Key()), iterator.Value()
		switch {
		case key == "pub/head":
			heads++
		case strings.HasPrefix(key, "pub/s/") && len(key) == 70:
			var value dagPublicSnapshot
			if decodePublic(raw, &value) != nil || store.validPublicSnapshot(value) != nil ||
				key != publicSnapshotKey(value.Commitment) || value.Commitment.Checkpoint > head.Commitment.Checkpoint {
				return errors.New("GG_DAG_PUBLIC_SNAPSHOT")
			}
			snapshots++
			size += publicEntryBytes(key, raw)
		case strings.HasPrefix(key, "pub/o/"):
			var value DagOrderLeaf
			if decodePublic(raw, &value) != nil || value.Index < 1 || value.Index > head.Commitment.Blocks || key != publicOrderKey(value.Index) {
				return errors.New("GG_DAG_PUBLIC_ORDER")
			}
			orders++
			size += publicEntryBytes(key, raw)
		case store.meta.PublicIndex == 2 && strings.HasPrefix(key, "pub/h/") && len(key) == 70 && pubPattern.MatchString(key[6:]):
			var index int
			if decodePublic(raw, &index) != nil || index < 1 || index > head.Commitment.Blocks {
				return errors.New("GG_DAG_PUBLIC_REF")
			}
			refs++
			size += publicEntryBytes(key, raw)
		case store.meta.PublicIndex == 2 && strings.HasPrefix(key, "pub/n/"):
			var hash string
			if !validPublicNodeKey(key, head.Commitment.Blocks) || decodePublic(raw, &hash) != nil || !pubPattern.MatchString(hash) {
				return errors.New("GG_DAG_PUBLIC_NODE")
			}
			nodes++
			size += publicEntryBytes(key, raw)
		default:
			return errors.New("GG_DAG_PUBLIC_KEY")
		}
		if size > dagPublicMaxBytes || orders > DagMaxRecords || snapshots > DagMaxRecords+1 {
			return errors.New("GG_DAG_PUBLIC_LIMIT")
		}
	}
	if iterator.Error() != nil || heads != 1 || size != head.Bytes || orders != head.Commitment.Blocks ||
		snapshots != int(head.Commitment.Checkpoint)+1 {
		return errors.New("GG_DAG_PUBLIC_CONTENTS")
	}
	if store.meta.PublicIndex == 2 && (refs != orders || nodes != 2*orders-bits.OnesCount(uint(orders))) {
		return errors.New("GG_DAG_PUBLIC_CONTENTS")
	}
	return nil
}

// Commit selection, the immutable proof leaves and the native history occupy
// one synchronous atomic batch. Prepared but unselected forks never enter it.
func (store *dagStore) commitExecution(raw []byte, execution *DagExecution) error {
	store.mu.Lock()
	defer store.mu.Unlock()
	if store.db == nil || store.failed {
		return errors.New("GG_DAG_STORE_FAULT")
	}
	if !store.retentionReady {
		return errors.New("GG_DAG_STORE_REPLAY_REQUIRED")
	}
	if len(raw) == 0 || len(raw) > dagHistoryMaxBytes {
		return errors.New("GG_DAG_STORE_HISTORY_SIZE")
	}
	if execution == nil || execution.proofOrder != nil || execution.Anchor != store.anchor || dagDigest("GG-DAG-CONSENSUS-SOURCE-v1\x00", execution.Source) != store.meta.SourceHash {
		return errors.New("GG_DAG_PUBLIC_SELECTION")
	}
	snapshot := publicSnapshot(execution)
	transition, err := store.validateTransition(execution)
	if err != nil {
		return err
	}
	if !transition.selected {
		return errors.New("GG_DAG_PUBLIC_SELECTION")
	}
	manifest, err := store.db.Get([]byte("m/"+execution.Commitment.ManifestHash), nil)
	if err != nil || !bytes.Equal(manifest, canonical(execution.Manifest)) {
		return errors.New("GG_DAG_PUBLIC_NOT_PREPARED")
	}
	sealed := *execution
	sealed.seal()
	if !bytes.Equal(canonical(sealed.Commitment), canonical(execution.Commitment)) {
		return errors.New("GG_DAG_PUBLIC_SELECTION")
	}
	batch := new(leveldb.Batch)
	batch.Put([]byte("history"), raw)
	head := dagPublicHead{Schema: "gg.dag.public-head.v2"}
	if store.meta.PublicIndex == 2 {
		head, err = store.publicHead()
		if err != nil {
			return err
		}
		if head.Commitment == execution.Commitment {
			return store.finishRetentionSelection(batch, execution)
		}
		if execution.Commitment.Checkpoint != head.Commitment.Checkpoint+1 || execution.Commitment.Previous != head.Commitment.ManifestHash ||
			execution.Commitment.Blocks <= head.Commitment.Blocks || execution.Commitment.Transactions < head.Commitment.Transactions {
			return errors.New("GG_DAG_PUBLIC_APPEND_ONLY")
		}
	} else if store.meta.PublicIndex != 0 || execution.Commitment.Checkpoint != 0 {
		return errors.New("GG_DAG_PUBLIC_GENESIS_REQUIRED")
	}
	pending := map[string][]byte{}
	read := func(key string, target any) error {
		value, ok := pending[key]
		if !ok {
			var err error
			value, err = store.db.Get([]byte(key), nil)
			if err != nil {
				return errors.New("GG_DAG_PUBLIC_NODE_MISSING")
			}
		}
		return decodePublic(value, target)
	}
	put := func(key string, value any) error {
		if _, ok := pending[key]; ok {
			return errors.New("GG_DAG_PUBLIC_APPEND_EXISTING")
		}
		if _, err := store.db.Get([]byte(key), nil); err != leveldb.ErrNotFound {
			return errors.New("GG_DAG_PUBLIC_APPEND_EXISTING")
		}
		raw := canonical(value)
		pending[key] = raw
		batch.Put([]byte(key), raw)
		head.Bytes += publicEntryBytes(key, raw)
		return nil
	}
	if err = appendPublicOrderEntries(transition.leaves, read, put); err != nil {
		return err
	}
	key, value := publicSnapshotKey(execution.Commitment), canonical(snapshot)
	batch.Put([]byte(key), value)
	head.Bytes += publicEntryBytes(key, value)
	if head.Bytes > dagPublicMaxBytes || len(value) > dagPublicValueMax {
		return errors.New("GG_DAG_PUBLIC_LIMIT")
	}
	head.Commitment = execution.Commitment
	batch.Put([]byte("pub/head"), canonical(head))
	return store.finishRetentionSelection(batch, execution)
}

// The caller has just replayed and authenticated every original block. Legacy
// stores gain only derived records; versioned corrupt stores are never repaired.
func (store *dagStore) verifyOrMigratePublic(execution *DagExecution, snapshots []dagPublicSnapshot) error {
	store.mu.Lock()
	defer store.mu.Unlock()
	if store.db == nil || store.failed {
		return errors.New("GG_DAG_STORE_FAULT")
	}
	if len(snapshots) != int(execution.Commitment.Checkpoint)+1 {
		return errors.New("GG_DAG_PUBLIC_REPLAY")
	}
	order, err := execution.orderList()
	if err != nil {
		return err
	}
	expected := make(map[string][]byte, len(snapshots)+len(order)+1)
	head := dagPublicHead{Schema: "gg.dag.public-head.v1", Commitment: execution.Commitment}
	add := func(key string, value any) {
		raw := canonical(value)
		expected[key] = raw
		head.Bytes += publicEntryBytes(key, raw)
	}
	for i, value := range snapshots {
		if value.Commitment.Checkpoint != uint64(i) || store.validPublicSnapshot(value) != nil {
			return errors.New("GG_DAG_PUBLIC_REPLAY")
		}
		add(publicSnapshotKey(value.Commitment), value)
	}
	for _, leaf := range order {
		add(publicOrderKey(leaf.Index), leaf)
	}
	if head.Bytes > dagPublicMaxBytes {
		return errors.New("GG_DAG_PUBLIC_LIMIT")
	}
	expected["pub/head"] = canonical(head)
	if store.meta.PublicIndex == 1 {
		if err := store.verifyPublicEntries(expected); err != nil {
			return err
		}
	}
	delete(expected, "pub/head")
	head.Schema = "gg.dag.public-head.v2"
	read := func(key string, target any) error { return decodePublic(expected[key], target) }
	put := func(key string, value any) error {
		raw := canonical(value)
		if previous, ok := expected[key]; ok {
			if !bytes.Equal(previous, raw) {
				return errors.New("GG_DAG_PUBLIC_REPLAY")
			}
			return nil
		}
		expected[key] = raw
		head.Bytes += publicEntryBytes(key, raw)
		return nil
	}
	if err := appendPublicOrderEntries(order, read, put); err != nil {
		return err
	}
	if head.Bytes > dagPublicMaxBytes {
		return errors.New("GG_DAG_PUBLIC_LIMIT")
	}
	expected["pub/head"] = canonical(head)
	if store.meta.PublicIndex == 2 {
		if err := store.verifyPublicEntries(expected); err != nil {
			return err
		}
	}
	batch := new(leveldb.Batch)
	if store.meta.PublicIndex != 2 {
		for key, value := range expected {
			batch.Put([]byte(key), value)
		}
	}
	meta := store.meta
	meta.PublicIndex = 2
	meta, err = store.verifyOrMigrateHistory(batch, meta)
	if err != nil {
		return err
	}
	meta, err = store.verifyOrMigrateSelection(batch, meta, execution, snapshots)
	if err != nil {
		return err
	}
	batch.Put([]byte("meta"), canonical(meta))
	if meta != store.meta {
		if err := store.syncWrite(batch); err != nil {
			return err
		}
	}
	store.meta = meta
	store.metadataPersisted.Store(true)
	store.replayedMetadata = nil
	return store.restoreRetention(execution, snapshots)
}

func (store *dagStore) publicExecution(ctx context.Context, expected DagCommitment) (*DagExecution, error) {
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	if validateDagCommitment(expected, store.source, store.anchor) != nil {
		return nil, errors.New("GG_DAG_PUBLIC_CONTEXT")
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
	defer func() {
		store.mu.Lock()
		store.activeReaders--
		store.mu.Unlock()
		store.readers.Done()
	}()
	defer snapshot.Release()
	read := func(key string, target any) error {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		if hook != nil {
			hook(key)
		}
		if ctx.Err() != nil {
			return ctx.Err()
		}
		raw, err := snapshot.Get([]byte(key), nil)
		if err != nil {
			return errors.New("GG_DAG_PUBLIC_READ")
		}
		return decodePublic(raw, target)
	}
	var value dagPublicSnapshot
	if err = read(publicSnapshotKey(expected), &value); err != nil {
		return nil, err
	}
	if value.Commitment != expected || store.validPublicSnapshot(value) != nil {
		return nil, errors.New("GG_DAG_PUBLIC_CONTEXT")
	}
	order := make([]DagOrderLeaf, expected.Blocks)
	for i := range order {
		if err = read(publicOrderKey(i+1), &order[i]); err != nil {
			return nil, err
		}
	}
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	if store.validPublicOrder(order, value) != nil {
		return nil, errors.New("GG_DAG_PUBLIC_ORDER")
	}
	return &DagExecution{Source: store.source, Anchor: store.anchor, Accounts: value.Accounts, proofOrder: order, Commitment: expected}, nil
}
