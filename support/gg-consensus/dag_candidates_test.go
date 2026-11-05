//go:build !js

package main

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"encoding/hex"
	"errors"
	"testing"
	"time"

	abci "github.com/cometbft/cometbft/abci/types"
	"github.com/syndtr/goleveldb/leveldb"
)

// Each variant is an actual differently signed body, not a fabricated size,
// commitment, certificate or measured throughput. Disposable public fixtures.
func retentionCandidate(t *testing.T, base *DagExecution, keys []ed25519.PrivateKey, variant int) (*DagExecution, []byte) {
	t.Helper()
	var block DagBlock
	if decodeStrict(dagWire(t, base, keys, 0, 1), &block) != nil {
		t.Fatal("fixture decode")
	}
	block.Body.CreatedAtNs += int64(variant)
	block.Signature = hex.EncodeToString(ed25519.Sign(keys[0], append([]byte("GG-DAG-PROPOSAL-SIGN-v1\x00"), canonical(block.Body)...)))
	batch := dagBatchWire(t, base, canonical(block))
	next, err := applyDagBatch(base, batch, 1700000002000000000)
	if err != nil {
		t.Fatal(err)
	}
	return next, batch
}

func prepareRetentionCandidates(t *testing.T, app *Ledger, keys []ed25519.PrivateKey, count int) []*DagExecution {
	t.Helper()
	out := []*DagExecution{}
	for i := 0; i < count; i++ {
		next, batch := retentionCandidate(t, app.dag, keys, i)
		response, err := app.ProcessProposal(context.Background(), &abci.RequestProcessProposal{Time: time.Unix(1700000002, 0), Txs: [][]byte{batch}})
		if err != nil || response.Status != abci.ResponseProcessProposal_ACCEPT {
			t.Fatal("valid preparation refused", i, err)
		}
		out = append(out, next)
	}
	return out
}

func TestDagCandidateProposerQuotaCanCommitEmptyHeightWithoutFaultingStore(t *testing.T) {
	app, keys, root := dagLedgerFixture(t)
	store := app.store.(*dagStore)
	accepted := prepareRetentionCandidates(t, app, keys, dagCandidateMaxManifests)
	before := store.meta
	next, batch := retentionCandidate(t, app.dag, keys, dagCandidateMaxManifests)
	err := store.prepare(next)
	if !errors.Is(err, errDagCandidateCredit) || store.failed || store.meta != before {
		t.Fatal("proposer quota mutated cached prefix or faulted whole store", err)
	}
	for _, index := range []int{0, len(accepted) - 1} {
		if _, err = store.load(accepted[index].Commitment); err != nil {
			t.Fatal("proposer quota unexpectedly evicted cached data", err)
		}
	}
	prepared, err := app.PrepareProposal(context.Background(), &abci.RequestPrepareProposal{Time: time.Unix(1700000002, 0), MaxTxBytes: 64 * 1024 * 1024, Txs: [][]byte{batch}})
	if err != nil || len(prepared.Txs) != 0 {
		t.Fatal("candidate pressure prevented safe empty proposal", err)
	}
	if _, err = app.FinalizeBlock(context.Background(), &abci.RequestFinalizeBlock{Height: 1, Time: time.Unix(1700000002, 0)}); err != nil {
		t.Fatal(err)
	}
	if _, err = app.Commit(context.Background(), &abci.RequestCommit{}); err != nil {
		t.Fatal(err)
	}
	if len(store.candidates) != 0 || store.meta.Records != 0 || store.meta.Manifests != 1 || app.state.DAG.Blocks != 0 {
		t.Fatal("empty decided height did not release losing candidates")
	}
	if _, err = store.load(accepted[0].Commitment); err == nil {
		t.Fatal("losing candidate remained loadable after decision")
	}
	first := commitPublicFixture(t, app, keys, 0, 3)
	block := orderFixture(t, app.dag)[0].Hash
	app.Close()
	restored, err := newDagEnabledLedger(app.genesis, app.anchor, root, false)
	if err != nil {
		t.Fatal(err)
	}
	defer restored.Close()
	if restored.state.Height != 2 || len(restored.store.(*dagStore).candidates) != 0 {
		t.Fatal("quota recovery did not survive reopen")
	}
	assertPublicQueries(t, restored, first, block)
}

func TestDagFinalizedPayloadUsesReservedSpaceAndDoesNotSelectBeforeCommit(t *testing.T) {
	app, keys, root := dagLedgerFixture(t)
	store := app.store.(*dagStore)
	accepted := prepareRetentionCandidates(t, app, keys, dagCandidateMaxManifests)
	chosen, batch := retentionCandidate(t, app.dag, keys, dagCandidateMaxManifests+1)
	oldHistory, _ := store.history()
	oldHead, _ := store.publicHead()
	pinned, err := store.db.GetSnapshot()
	if err != nil {
		t.Fatal(err)
	}
	defer pinned.Release()
	loserKey := []byte("r/" + accepted[0].Manifest.Blocks[0])
	if _, err = app.FinalizeBlock(context.Background(), &abci.RequestFinalizeBlock{Height: 1, Time: time.Unix(1700000002, 0), Txs: [][]byte{batch}}); err != nil {
		t.Fatal("decided payload refused behind candidate quota", err)
	}
	if len(store.candidates) != 2 || store.meta.Records != 1 || store.meta.Manifests != 2 {
		t.Fatal("decided preparation did not retire precisely the losing objects")
	}
	if _, err = store.db.Get(loserKey, nil); err != leveldb.ErrNotFound {
		t.Fatal("losing data retained")
	}
	if _, err = pinned.Get(loserKey, nil); err != nil {
		t.Fatal("atomic cleanup invalidated an existing reader", err)
	}
	actualHistory, _ := store.history()
	actualHead, _ := store.publicHead()
	if !bytes.Equal(actualHistory, oldHistory) || actualHead != oldHead || app.state.DAG.Blocks != 0 {
		t.Fatal("prepared payload manufactured selection/finality")
	}
	if _, err = store.load(chosen.Commitment); err != nil {
		t.Fatal("decided payload not durably available", err)
	}
	pinned.Release()
	app.Close()
	// Crash after finalized payload Sync, before application Commit: replay the
	// OLD history, then re-execute the SDK-decided block with unchanged nonces.
	restored, err := newDagEnabledLedger(app.genesis, app.anchor, root, false)
	if err != nil {
		t.Fatal(err)
	}
	defer restored.Close()
	if restored.state.Height != 0 || len(restored.store.(*dagStore).candidates) != 2 {
		t.Fatal("pre-commit crash selected speculative state")
	}
	if _, err = restored.FinalizeBlock(context.Background(), &abci.RequestFinalizeBlock{Height: 1, Time: time.Unix(1700000002, 0), Txs: [][]byte{batch}}); err != nil {
		t.Fatal(err)
	}
	if _, err = restored.Commit(context.Background(), &abci.RequestCommit{}); err != nil {
		t.Fatal(err)
	}
	if restored.state.DAG.Transactions != 1 || len(restored.store.(*dagStore).candidates) != 0 {
		t.Fatal("decided recovery repeated or lost execution")
	}
	assertPublicQueries(t, restored, restored.state, orderFixture(t, chosen)[0].Hash)
}

func TestDagRetentionUnknownSyncOutcomeRecoversExactPayloadAndSelectedPrefix(t *testing.T) {
	for _, phase := range []string{"finalize", "commit"} {
		for _, after := range []bool{false, true} {
			t.Run(phase+map[bool]string{false: "_before_sync", true: "_after_sync_lost_return"}[after], func(t *testing.T) {
				app, keys, root := dagLedgerFixture(t)
				store := app.store.(*dagStore)
				loser, _ := retentionCandidate(t, app.dag, keys, 1)
				chosen, batch := retentionCandidate(t, app.dag, keys, 2)
				if err := store.prepare(chosen); err != nil {
					t.Fatal(err)
				}
				if phase == "commit" {
					if _, err := app.FinalizeBlock(context.Background(), &abci.RequestFinalizeBlock{Height: 1, Time: time.Unix(1700000002, 0), Txs: [][]byte{batch}}); err != nil {
						t.Fatal(err)
					}
				}
				if err := store.prepare(loser); err != nil {
					t.Fatal(err)
				}
				before := store.meta
				write := store.write
				store.write = func(b *leveldb.Batch) error {
					if after {
						if err := write(b); err != nil {
							return err
						}
					}
					return errors.New("disposable retention write outcome")
				}
				var err error
				if phase == "finalize" {
					_, err = app.FinalizeBlock(context.Background(), &abci.RequestFinalizeBlock{Height: 1, Time: time.Unix(1700000002, 0), Txs: [][]byte{batch}})
				} else {
					_, err = app.Commit(context.Background(), &abci.RequestCommit{})
				}
				if err == nil || !store.failed || store.meta != before || app.state.Height != 0 || store.prepare(chosen) == nil {
					t.Fatal("ambiguous write was acknowledged or reused")
				}
				app.Close()
				restored, err := newDagEnabledLedger(app.genesis, app.anchor, root, false)
				if err != nil {
					t.Fatal(err)
				}
				defer restored.Close()
				height := int64(0)
				if phase == "commit" && after {
					height = 1
				}
				if restored.state.Height != height {
					t.Fatal("incorrect durable selection after lost return")
				}
				_, err = restored.store.load(loser.Commitment)
				if (err == nil) == after {
					t.Fatal("cleanup did not recover exact atomic outcome")
				}
				if height == 0 {
					if _, err = restored.FinalizeBlock(context.Background(), &abci.RequestFinalizeBlock{Height: 1, Time: time.Unix(1700000002, 0), Txs: [][]byte{batch}}); err != nil {
						t.Fatal(err)
					}
					if _, err = restored.Commit(context.Background(), &abci.RequestCommit{}); err != nil {
						t.Fatal(err)
					}
				}
				if restored.state.DAG.Transactions != 1 {
					t.Fatal("wrong replayed nonce or transaction count")
				}
				assertPublicQueries(t, restored, restored.state, orderFixture(t, chosen)[0].Hash)
			})
		}
	}
}

func TestDagRetentionKeepsSharedWireAllSelectedAncestorsAndHistoricalProofs(t *testing.T) {
	app, keys, root := dagLedgerFixture(t)
	store := app.store.(*dagStore)
	first := commitPublicFixture(t, app, keys, 0, 3)
	block := orderFixture(t, app.dag)[0].Hash
	second := commitPublicFixture(t, app, keys, 1, 7)
	wire := dagWire(t, app.dag, keys, 0, 1)
	batch := dagBatchWire(t, app.dag, wire)
	a, err := applyDagBatch(app.dag, batch, 1700000004000000000)
	if err != nil {
		t.Fatal(err)
	}
	b, err := applyDagBatch(app.dag, batch, 1700000005000000000)
	if err != nil {
		t.Fatal(err)
	}
	for _, candidate := range []*DagExecution{a, b} {
		if err = store.prepare(candidate); err != nil {
			t.Fatal(err)
		}
	}
	if len(store.candidates) != 3 || a.Manifest.Blocks[0] != b.Manifest.Blocks[0] {
		t.Fatal("shared data fixture incorrect")
	}
	if _, err = app.FinalizeBlock(context.Background(), &abci.RequestFinalizeBlock{Height: 3, Time: time.Unix(1700000005, 0), Txs: [][]byte{batch}}); err != nil {
		t.Fatal(err)
	}
	if _, err = app.Commit(context.Background(), &abci.RequestCommit{}); err != nil {
		t.Fatal(err)
	}
	if store.meta.Records != 3 || store.meta.Manifests != 4 || len(store.candidates) != 0 {
		t.Fatal("shared selected data or old selected manifest was removed")
	}
	if err = store.prepareFinalized(a); err == nil {
		t.Fatal("older preparation authorized new cleanup")
	}
	assertPublicQueries(t, app, first, block)
	assertPublicQueries(t, app, second, block)
	app.Close()
	restored, err := newDagEnabledLedger(app.genesis, app.anchor, root, false)
	if err != nil {
		t.Fatal(err)
	}
	defer restored.Close()
	assertPublicQueries(t, restored, first, block)
	assertPublicQueries(t, restored, second, block)
}

func TestDagCandidateByteObjectAndFinalizationReserveBoundaries(t *testing.T) {
	// Credit arithmetic only. These synthetic SIZE counters are not payload
	// validation, physical storage, a full-history test or measured capacity.
	for _, kind := range []string{"bytes", "manifests", "total_bytes", "records", "total_manifests"} {
		t.Run(kind, func(t *testing.T) {
			store := &dagStore{candidates: map[string]uint64{}}
			meta := dagStoreMeta{}
			switch kind {
			case "bytes":
				store.candidates["r/fixture"] = dagCandidateMaxBytes
			case "manifests":
				for i := 0; i < dagCandidateMaxManifests; i++ {
					store.candidates["m/"+string(rune(100+i))] = 1
				}
			case "total_bytes":
				meta.Bytes = dagStoreMaxBytes - dagFinalizeReserveBytes
			case "records":
				meta.Records = dagStoreMaxObjects - DagMaxBatchBlocks
			case "total_manifests":
				meta.Manifests = dagStoreMaxObjects - 1
			}
			if err := store.candidateCredit(meta, nil); err != nil {
				t.Fatal("exact credit boundary rejected", err)
			}
			switch kind {
			case "bytes":
				store.candidates["r/fixture"]++
			case "manifests":
				store.candidates["m/one_more"] = 1
			case "total_bytes":
				meta.Bytes++
			case "records":
				meta.Records++
			case "total_manifests":
				meta.Manifests++
			}
			if !errors.Is(store.candidateCredit(meta, nil), errDagCandidateCredit) {
				t.Fatal("credit overflow accepted")
			}
		})
	}
}

func TestDagInvalidFinalizationCannotAuthorizeCandidateRetirement(t *testing.T) {
	for _, kind := range []string{"bad_transaction", "wrong_height", "stale_selection"} {
		t.Run(kind, func(t *testing.T) {
			app, keys, _ := dagLedgerFixture(t)
			old := app.dag
			commitPublicFixture(t, app, keys, 0, 1)
			store := app.store.(*dagStore)
			candidate, batch := retentionCandidate(t, app.dag, keys, 7)
			if err := store.prepare(candidate); err != nil {
				t.Fatal(err)
			}
			before := store.meta
			writes := 0
			write := store.write
			store.write = func(batch *leveldb.Batch) error { writes++; return write(batch) }
			var err error
			switch kind {
			case "bad_transaction":
				var block DagBlock
				if decodeStrict(dagWire(t, app.dag, keys, 0, 1), &block) != nil {
					t.Fatal("decode")
				}
				block.Body.Transactions[0].Signature = string(bytes.Repeat([]byte("0"), 128))
				block.Body.PayloadRoot = dagRoot(block.Body.Transactions, "GG-DAG-PAYLOAD-v1\x00")
				block.Signature = hex.EncodeToString(ed25519.Sign(keys[0], append([]byte("GG-DAG-PROPOSAL-SIGN-v1\x00"), canonical(block.Body)...)))
				batch = dagBatchWire(t, app.dag, canonical(block))
				_, err = app.FinalizeBlock(context.Background(), &abci.RequestFinalizeBlock{Height: 2, Time: time.Unix(1700000003, 0), Txs: [][]byte{batch}})
			case "wrong_height":
				_, err = app.FinalizeBlock(context.Background(), &abci.RequestFinalizeBlock{Height: 1, Time: time.Unix(1700000003, 0), Txs: [][]byte{batch}})
			case "stale_selection":
				err = store.prepareFinalized(old)
			}
			if err == nil || writes != 0 || before != store.meta || store.failed {
				t.Fatal("invalid request changed availability obligations")
			}
			if _, err = store.load(candidate.Commitment); err != nil {
				t.Fatal("valid pending payload lost", err)
			}
		})
	}
}

func TestDagCandidateRealPayloadByteQuotaAndDecidedRecovery(t *testing.T) {
	app, keys, _ := dagLedgerFixture(t)
	store := app.store.(*dagStore)
	var block DagBlock
	if decodeStrict(dagWire(t, app.dag, keys, 0, 5000), &block) != nil {
		t.Fatal("decode signed payload")
	}
	accepted := 0
	var batch []byte
	var rejected *DagExecution
	var firstBatch []byte
	var firstCommitment DagCommitment
	for variant := 0; variant < dagCandidateMaxManifests; variant++ {
		block.Body.CreatedAtNs++
		block.Signature = hex.EncodeToString(ed25519.Sign(keys[0], append([]byte("GG-DAG-PROPOSAL-SIGN-v1\x00"), canonical(block.Body)...)))
		batch = dagBatchWire(t, app.dag, canonical(block))
		next, err := applyDagBatch(app.dag, batch, 1700000002000000000)
		if err != nil {
			t.Fatal(err)
		}
		before := store.meta
		err = store.prepare(next)
		if errors.Is(err, errDagCandidateCredit) {
			if before != store.meta || store.failed {
				t.Fatal("byte rejection changed durable state")
			}
			rejected = next
			break
		}
		if err != nil {
			t.Fatal(err)
		}
		if accepted == 0 {
			firstBatch = append([]byte(nil), batch...)
			firstCommitment = next.Commitment
		}
		accepted++
	}
	if rejected == nil || accepted < 2 || accepted >= dagCandidateMaxManifests {
		t.Fatal("actual byte quota was not reached independently of manifest count", accepted)
	}
	var retained uint64
	for _, size := range store.candidates {
		retained += size
	}
	if retained > dagCandidateMaxBytes {
		t.Fatal("candidate byte cap exceeded")
	}
	response, err := app.ProcessProposal(context.Background(), &abci.RequestProcessProposal{Time: time.Unix(1700000002, 0), Txs: [][]byte{batch}})
	if err != nil || response.Status != abci.ResponseProcessProposal_ACCEPT || store.meta.Records != 1 || app.state.DAG.Blocks != 0 {
		t.Fatal("byte cache pressure changed deterministic validity or selected state", err)
	}
	if _, err = store.load(firstCommitment); err == nil {
		t.Fatal("earlier 5000TX payload was not actually evicted")
	}
	if _, err := app.FinalizeBlock(context.Background(), &abci.RequestFinalizeBlock{Height: 1, Time: time.Unix(1700000002, 0), Txs: [][]byte{firstBatch}}); err != nil {
		t.Fatal("decided 5000TX payload could not recover from actual byte pressure", err)
	}
	if _, err := app.Commit(context.Background(), &abci.RequestCommit{}); err != nil {
		t.Fatal(err)
	}
	if app.state.DAG.Transactions != 5000 || app.state.DAG.ManifestHash != firstCommitment.ManifestHash || store.meta.Records != 1 || len(store.candidates) != 0 {
		t.Fatal("incorrect decided payload or retained losing data")
	}
	t.Logf("actual signed preparations=%d; candidate logical bytes=%d; selected transactions=%d; selected logical bytes=%d; not a throughput/full-history/physical-host test", accepted, retained, app.state.DAG.Transactions, store.meta.Bytes)
}

func TestDagProcessProposalCoherenceAcrossDifferentCachesAndEvictedDecidedPayload(t *testing.T) {
	a, keys, _ := dagLedgerFixture(t)
	b, _, _ := dagLedgerFixture(t)
	if a.anchor != b.anchor {
		t.Fatal("different test genesis")
	}
	old := prepareRetentionCandidates(t, a, keys, dagCandidateMaxManifests)[0]
	_, batch := retentionCandidate(t, a.dag, keys, dagCandidateMaxManifests+1)
	for _, app := range []*Ledger{a, b} {
		response, err := app.ProcessProposal(context.Background(), &abci.RequestProcessProposal{Time: time.Unix(1700000002, 0), Txs: [][]byte{batch}})
		if err != nil || response.Status != abci.ResponseProcessProposal_ACCEPT {
			t.Fatal("validity depended on local cache history", err)
		}
	}
	store := a.store.(*dagStore)
	if len(store.candidates) != 2 {
		t.Fatal("full cache failed to roll within its bound")
	}
	if _, err := store.load(old.Commitment); err == nil {
		t.Fatal("old candidate was not actually evicted")
	}
	// The SDK supplies a complete DECIDED block, including when its earlier
	// app cache entry was evicted. Both nodes must execute the same state.
	_, oldBatch := retentionCandidate(t, a.dag, keys, 0)
	for _, app := range []*Ledger{a, b} {
		if _, err := app.FinalizeBlock(context.Background(), &abci.RequestFinalizeBlock{Height: 1, Time: time.Unix(1700000002, 0), Txs: [][]byte{oldBatch}}); err != nil {
			t.Fatal(err)
		}
		if _, err := app.Commit(context.Background(), &abci.RequestCommit{}); err != nil {
			t.Fatal(err)
		}
		assertPublicQueries(t, app, app.state, orderFixture(t, old)[0].Hash)
	}
	if !bytes.Equal(canonical(a.state), canonical(b.state)) || a.state.DAG.ManifestHash != old.Commitment.ManifestHash {
		t.Fatal("cache rollover changed deterministic execution")
	}
}

func TestDagProposalCacheRolloverUnknownWriteOutcomeIsAtomic(t *testing.T) {
	for _, after := range []bool{false, true} {
		t.Run(map[bool]string{false: "before_sync", true: "after_sync_lost_return"}[after], func(t *testing.T) {
			app, keys, root := dagLedgerFixture(t)
			store := app.store.(*dagStore)
			old := prepareRetentionCandidates(t, app, keys, dagCandidateMaxManifests)[0]
			chosen, batch := retentionCandidate(t, app.dag, keys, dagCandidateMaxManifests+1)
			before := store.meta
			write := store.write
			store.write = func(b *leveldb.Batch) error {
				if after {
					if err := write(b); err != nil {
						return err
					}
				}
				return errors.New("disposable rollover outcome")
			}
			response, err := app.ProcessProposal(context.Background(), &abci.RequestProcessProposal{Time: time.Unix(1700000002, 0), Txs: [][]byte{batch}})
			if err == nil || response != nil || !store.failed || store.meta != before || app.state.Height != 0 {
				t.Fatal("unknown cache write published an acceptance or changed application state")
			}
			app.Close()
			restored, err := newDagEnabledLedger(app.genesis, app.anchor, root, false)
			if err != nil {
				t.Fatal(err)
			}
			defer restored.Close()
			if restored.state.Height != 0 {
				t.Fatal("cache rollover selected a state")
			}
			_, oldErr := restored.store.load(old.Commitment)
			_, newErr := restored.store.load(chosen.Commitment)
			if after && (oldErr == nil || newErr != nil) || !after && (oldErr != nil || newErr == nil) {
				t.Fatal("cache rollover did not recover exact before/after atomic outcome")
			}
		})
	}
}
