//go:build !js

package main

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/binary"
	"encoding/hex"
	"errors"
	"io"
	"os"
	"path/filepath"
	"testing"
	"time"

	dbm "github.com/cometbft/cometbft-db"
	cmted "github.com/cometbft/cometbft/crypto/ed25519"
	cmtjson "github.com/cometbft/cometbft/libs/json"
	cmtproto "github.com/cometbft/cometbft/proto/tendermint/types"
	cmtversion "github.com/cometbft/cometbft/proto/tendermint/version"
	cmtstore "github.com/cometbft/cometbft/store"
	"github.com/cometbft/cometbft/types"
	"github.com/cometbft/cometbft/version"
	"github.com/syndtr/goleveldb/leveldb"
	"github.com/syndtr/goleveldb/leveldb/opt"
)

// Cryptographically signed SDK block fixtures with real blockstore encoding.
// This is not claimed to be a live consensus run; that evidence is separate.
func financialFixtureSDKChain(t *testing.T, genesis Genesis, anchor, root string, state State, signerGroups ...[]cmted.PrivKey) *types.SignedHeader {
	t.Helper()
	journal, err := leveldb.OpenFile(filepath.Join(root, "gg-financial-dag.leveldb"), &opt.Options{ReadOnly: true, ErrorIfMissing: true})
	if err != nil {
		t.Fatal(err)
	}
	defer journal.Close()
	directory := filepath.Join(root, "data")
	if os.Mkdir(directory, 0700) != nil {
		t.Fatal("SDK directory")
	}
	db, err := dbm.NewGoLevelDB("blockstore", directory)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	store := cmtstore.NewBlockStore(db)
	set := validatorSet(genesis)
	_, _, _, keys := testGenesis()
	if len(signerGroups) > 0 {
		keys = signerGroups[0]
	}
	previous := types.BlockID{}
	commit := &types.Commit{}
	before := initialState(genesis, anchor).StateRoot
	when, _ := dagDecimalNs(genesis.FinancialDAG.StartedAtNs)
	var result *types.SignedHeader
	for height := int64(1); height <= state.Height+1; height++ {
		txs := types.Txs{}
		after := before
		if height <= state.Height {
			raw, err := journal.Get([]byte(financialHeightKey(height)), nil)
			var entry financialJournalEntry
			if err != nil || decodeStrict(raw, &entry) != nil {
				t.Fatal("journal", err)
			}
			when, _ = dagDecimalNs(entry.TimeNs)
			after = entry.After
			if !bytes.Equal(entry.Transaction, []byte("null")) {
				txs = append(txs, types.Tx(entry.Transaction))
			}
		} else {
			when += 1000000
		}
		block := types.MakeBlock(height, txs, commit, nil)
		application, _ := hex.DecodeString(before)
		block.Header.Version = cmtversion.Consensus{Block: version.BlockProtocol, App: genesisDoc(genesis).ConsensusParams.Version.App}
		block.Header.ChainID = genesis.ChainID
		block.Header.Time = time.Unix(0, when).UTC()
		block.Header.LastBlockID = previous
		block.Header.ValidatorsHash = set.Hash()
		block.Header.NextValidatorsHash = set.Hash()
		block.Header.AppHash = application
		block.Header.ConsensusHash = genesisDoc(genesis).ConsensusParams.Hash()
		block.Header.ProposerAddress = set.Validators[0].Address
		parts, err := block.MakePartSet(types.BlockPartSizeBytes)
		if err != nil {
			t.Fatal(err)
		}
		id := types.BlockID{Hash: block.Hash(), PartSetHeader: parts.Header()}
		signatures := make([]types.CommitSig, len(set.Validators))
		for index, validator := range set.Validators {
			for _, key := range keys {
				if !bytes.Equal(key.PubKey().Address(), validator.Address) {
					continue
				}
				vote := &cmtproto.Vote{Type: cmtproto.PrecommitType, Height: height, Round: 0, BlockID: id.ToProto(), Timestamp: block.Header.Time,
					ValidatorAddress: validator.Address, ValidatorIndex: int32(index)}
				signature, err := key.Sign(types.VoteSignBytes(genesis.ChainID, vote))
				if err != nil {
					t.Fatal(err)
				}
				signatures[index] = types.CommitSig{BlockIDFlag: types.BlockIDFlagCommit, ValidatorAddress: validator.Address, Timestamp: block.Header.Time, Signature: signature}
			}
		}
		commit = &types.Commit{Height: height, Round: 0, BlockID: id, Signatures: signatures}
		store.SaveBlock(block, parts, commit)
		previous = id
		before = after
		result = &types.SignedHeader{Header: &block.Header, Commit: commit}
	}
	return result
}

func financialPublicFixture(t *testing.T, counts ...int) (financialArchiveCommand, []byte, []string) {
	t.Helper()
	app, backend, accounts, producers, root := financialSessionSDKFixture(t)
	nonce := uint64(0)
	ids := []string{}
	for round, count := range counts {
		inputs := make([][]byte, count)
		for index := range inputs {
			inputs[index] = testTx(app.genesis, app.anchor, accounts, 0, 1, "1", nonce)
			nonce++
		}
		batch, _ := financialContextBlock(t, app, producers, 0, inputs)
		var decoded financialDagBatch
		if decodeStrict(batch, &decoded) != nil || len(decoded.Blocks) != 1 {
			t.Fatal("fixture batch")
		}
		wire, err := base64.StdEncoding.Strict().DecodeString(decoded.Blocks[0])
		if err != nil {
			t.Fatal(err)
		}
		ids = append(ids, hashHex(append([]byte(financialDomain+"DAG-BLOCK\x00"), wire...)))
		commitFinancialSDK(t, app, batch)
		commitFinancialSDK(t, app, nil)
		if round < len(counts)-1 {
			cut, err := backend.current.prepareCut()
			if err != nil {
				t.Fatal(err)
			}
			commitFinancialSDK(t, app, cut)
		}
	}
	if err := app.Close(); err != nil {
		t.Fatal(err)
	}
	signed := financialFixtureSDKChain(t, app.genesis, app.anchor, root, app.state)
	header, err := cmtjson.Marshal(signed)
	if err != nil {
		t.Fatal(err)
	}
	certificate := dagArchiveCertificate{Schema: "gg.consensus.proof.v1", Genesis: app.genesis, GenesisHash: app.anchor, SignedHeader: header, State: copyState(app.state)}
	request := financialArchiveCommand{ArchivePath: filepath.Join(t.TempDir(), "history.ggfin"), Root: root, Certificate: &certificate, Genesis: app.genesis, GenesisHash: app.anchor}
	if err = app.Close(); err != nil {
		t.Fatal(err)
	}
	var output bytes.Buffer
	if _, err = exportFinancialArchive(context.Background(), &output, request); err != nil {
		t.Fatal("export", err)
	}
	return request, output.Bytes(), ids
}

func financialRestoreFixture(t *testing.T, request financialArchiveCommand, raw []byte) (financialArchiveCommand, *os.File, os.FileInfo) {
	t.Helper()
	if err := os.WriteFile(request.ArchivePath, raw, 0600); err != nil {
		t.Fatal(err)
	}
	request.Root = ""
	request.Certificate = nil
	request.RestoreRoot = t.TempDir()
	file, info, err := openFinancialArchiveInput(request.ArchivePath)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = file.Close() })
	return request, file, info
}

func TestFinancialPublicArchiveReplays5000PaymentsCutsAndEmptySDKHeights(t *testing.T) {
	request, raw, _ := financialPublicFixture(t, 5000, 3, 2)
	result, err := readFinancialArchive(context.Background(), bytes.NewReader(raw), request, nil)
	if err != nil || result["blocks_replayed"] != "3" || result["payments_applied"] != "5005" || result["snapshot_trust_used"] != false || result["consensus_store_restored"] != false {
		t.Fatal("full financial replay", err, result)
	}
	if result["application_height"] != int64(8) || result["checkpoints_replayed"] != "5" {
		t.Fatal("SDK gaps/cuts omitted", result)
	}
	var again bytes.Buffer
	exported, err := exportFinancialArchive(context.Background(), &again, request)
	if err != nil || !bytes.Equal(raw, again.Bytes()) || !bytes.Equal(canonical(result), canonical(exported)) {
		t.Fatal("non-deterministic original export", err)
	}
}

func TestFinancialPublicArchiveRestoresExactAccountsOldReceiptsAndOriginalJournal(t *testing.T) {
	source, raw, ids := financialPublicFixture(t, 5000, 2)
	expected := source.Certificate.State
	request, file, info := financialRestoreFixture(t, source, raw)
	result, err := restoreFinancialArchive(context.Background(), file, info, request)
	if err != nil || result["application_store_restored"] != true || result["native_node_ready"] != false || result["signing_keys_exported"] != false {
		t.Fatal("restore", err, result)
	}
	app, err := newDagEnabledLedger(source.Genesis, source.GenesisHash, request.RestoreRoot, false)
	if err != nil {
		t.Fatal(err)
	}
	defer app.Close()
	if !bytes.Equal(canonical(expected), canonical(app.state)) {
		t.Fatal("restored money differs")
	}
	backend := app.financial.(*financialNativeApplication)
	receipt, err := backend.Receipt(context.Background(), app.state, financialReceiptSelector{Block: ids[0], Index: 4999})
	if err != nil || receipt.Context.BlockHash != ids[0] || receipt.Receipt.Leaf.Outcome != "APPLIED" {
		t.Fatal("old receipt was not rebuilt", err)
	}
	if err = app.Close(); err != nil {
		t.Fatal(err)
	}
	source.Root = request.RestoreRoot
	var output bytes.Buffer
	if _, err = exportFinancialArchive(context.Background(), &output, source); err != nil || !bytes.Equal(raw, output.Bytes()) {
		t.Fatal("restored journal lost originals", err)
	}
	reused, err := restoreFinancialArchive(context.Background(), file, info, request)
	if err != nil || reused["restore_reused"] != true {
		t.Fatal("completed recovery not idempotent", err)
	}
}

func TestFinancialPublicArchiveRejectsTamperingTruncationTrailingDataForeignPinAndFloor(t *testing.T) {
	request, raw, _ := financialPublicFixture(t, 3, 2)
	changed := append([]byte(nil), raw...)
	changed[len(changed)/2] ^= 1
	for index, value := range [][]byte{changed, raw[:len(raw)-1], append(append([]byte(nil), raw...), 0), append([]byte("BADFIN00"), raw[8:]...)} {
		if result, err := readFinancialArchive(context.Background(), bytes.NewReader(value), request, nil); err == nil || result != nil {
			t.Fatal("corrupt archive accepted", index)
		}
	}
	pin := request
	pin.GenesisHash = DagZero
	if _, err := readFinancialArchive(context.Background(), bytes.NewReader(raw), pin, nil); err == nil {
		t.Fatal("foreign anchor accepted")
	}
	pin = request
	pin.MinimumCertificateHeight = request.Certificate.State.Height + 2
	if _, err := readFinancialArchive(context.Background(), bytes.NewReader(raw), pin, nil); err == nil {
		t.Fatal("stale certificate accepted")
	}
	pin = request
	pin.MinimumCertificateHeight = request.Certificate.State.Height + 1
	pin.MinimumCertificateBlock = DagZero
	if _, err := readFinancialArchive(context.Background(), bytes.NewReader(raw), pin, nil); err == nil {
		t.Fatal("conflicting certificate accepted")
	}
}

func TestFinancialPublicArchiveIncompleteRestoreCannotStartNormallyAndResumesExactPrefix(t *testing.T) {
	source, raw, _ := financialPublicFixture(t, 3, 2)
	for _, durable := range []bool{false, true} {
		t.Run(map[bool]string{false: "rollback", true: "durable_then_error"}[durable], func(t *testing.T) {
			request, file, info := financialRestoreFixture(t, source, raw)
			injected := errors.New("owned recovery IO uncertainty")
			_, err := restoreFinancialArchiveUsing(context.Background(), file, info, request, func(store *financialStore) {
				write := store.write
				calls := 0
				store.write = func(batch *leveldb.Batch) error {
					calls++
					if calls == 3 {
						if durable {
							if err := write(batch); err != nil {
								return err
							}
						}
						return injected
					}
					return write(batch)
				}
			})
			if err == nil {
				t.Fatal("injected write did not fail")
			}
			if app, err := newDagEnabledLedger(source.Genesis, source.GenesisHash, request.RestoreRoot, false); err == nil {
				_ = app.Close()
				t.Fatal("incomplete financial store started normally")
			}
			result, err := restoreFinancialArchive(context.Background(), file, info, request)
			if err != nil || result["application_store_restored"] != true {
				t.Fatal("exact prefix did not resume", err)
			}
		})
	}
}

func TestFinancialPublicArchiveRefusesChangedRestoreIntentAndUnownedTarget(t *testing.T) {
	source, raw, _ := financialPublicFixture(t, 3, 2)
	request, file, info := financialRestoreFixture(t, source, raw)
	ctx, cancel := context.WithCancel(context.Background())
	_, err := restoreFinancialArchiveUsing(ctx, file, info, request, func(store *financialStore) { cancel() })
	if !errors.Is(err, context.Canceled) {
		t.Fatal("cancellation reason lost", err)
	}
	// Change the complete file while retaining a real header. Even if its own
	// footer were rehashed, it cannot reuse the earlier sealed recovery intent.
	changed := append([]byte(nil), raw...)
	changed[len(changed)-10] ^= 1
	path := filepath.Join(t.TempDir(), "changed.ggfin")
	if os.WriteFile(path, changed, 0600) != nil {
		t.Fatal("write")
	}
	other, otherInfo, err := openFinancialArchiveInput(path)
	if err != nil {
		t.Fatal(err)
	}
	defer other.Close()
	request.ArchivePath = path
	if _, err = restoreFinancialArchive(context.Background(), other, otherInfo, request); err == nil {
		t.Fatal("changed archive reused pending intent")
	}
	request.RestoreRoot = t.TempDir()
	if os.WriteFile(filepath.Join(request.RestoreRoot, "not-owned.txt"), []byte("retain"), 0600) != nil {
		t.Fatal("write")
	}
	if _, err = restoreFinancialArchive(context.Background(), other, otherInfo, request); err == nil {
		t.Fatal("unowned target overwritten")
	}
}

func TestFinancialPublicArchiveExportIsReadOnlyAndRefusesLiveSourceAndOverwrite(t *testing.T) {
	request, raw, _ := financialPublicFixture(t, 3)
	store, _, _, err := openFinancialStore(context.Background(), request.Genesis, request.GenesisHash, request.Root, false)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = exportFinancialArchive(context.Background(), io.Discard, request); err == nil {
		t.Fatal("opened busy source")
	}
	if store.close() != nil {
		t.Fatal("close")
	}
	before := segmentedArchiveDirectoryImage(t, request.Root)
	result, err := runFinancialArchiveCommand("financial-history-export", canonical(request))
	if err != nil || result["verified"] != true {
		t.Fatal("native export command", err)
	}
	if segmentedArchiveDirectoryImage(t, request.Root) != before {
		t.Fatal("export modified source")
	}
	if _, err = runFinancialArchiveCommand("financial-history-export", canonical(request)); err == nil {
		t.Fatal("overwrote existing archive")
	}
	saved, err := os.ReadFile(request.ArchivePath)
	if err != nil || !bytes.Equal(saved, raw) {
		t.Fatal("different command bytes", err)
	}
	request.ArchivePath = filepath.Join(request.Root, "forbidden.ggfin")
	if _, err = runFinancialArchiveCommand("financial-history-export", canonical(request)); err == nil {
		t.Fatal("wrote into source")
	}
}

func TestFinancialPublicArchiveRejectsMovedSDKHeightEvenWhenFinalMoneyIsIdentical(t *testing.T) {
	request, raw, _ := financialPublicFixture(t, 3)
	type frame struct {
		kind byte
		raw  []byte
	}
	input := bytes.NewReader(raw[8:])
	frames := []frame{}
	journal := []int{}
	for input.Len() > 0 {
		var prefix [5]byte
		if _, err := io.ReadFull(input, prefix[:]); err != nil {
			t.Fatal(err)
		}
		body := make([]byte, int(binary.BigEndian.Uint32(prefix[1:])))
		if _, err := io.ReadFull(input, body); err != nil {
			t.Fatal(err)
		}
		if prefix[0] == 'J' {
			journal = append(journal, len(frames))
		}
		frames = append(frames, frame{prefix[0], body})
	}
	if len(journal) != 2 {
		t.Fatal("fixture SDK height count")
	}
	var first, second financialJournalEntry
	if decodeStrict(frames[journal[0]].raw, &first) != nil || decodeStrict(frames[journal[1]].raw, &second) != nil {
		t.Fatal("fixture entries")
	}
	transaction := append([]byte(nil), first.Transaction...)
	initial := initialState(request.Genesis, request.GenesisHash)
	initial.Height = 1
	sealState(&initial)
	first.Transaction = []byte("null")
	first.After = initial.StateRoot
	frames[journal[0]].raw = canonical(first)
	second.Transaction = transaction
	second.TimeNs = first.TimeNs
	second.Previous = financialJournalHash(frames[journal[0]].raw)
	// Preserve the original certified final account/financial state exactly.
	second.After = request.Certificate.State.StateRoot
	frames[journal[1]].raw = canonical(second)
	var changed bytes.Buffer
	changed.Write(raw[:8])
	for _, item := range frames {
		if item.kind == 'F' {
			break
		}
		if err := writeArchiveFrame(&changed, item.kind, item.raw, financialJournalMaxWire); err != nil {
			t.Fatal(err)
		}
	}
	footer := financialArchiveFooter{Content: hashHex(changed.Bytes()), Height: 2, Journal: financialJournalHash(frames[journal[1]].raw),
		Schema: "gg.financial.archive.footer.v1", StateRoot: request.Certificate.State.StateRoot}
	if writeArchiveFrame(&changed, 'F', canonical(footer), dagArchiveFooterLimit) != nil {
		t.Fatal("footer")
	}
	if result, err := readFinancialArchive(context.Background(), bytes.NewReader(changed.Bytes()), request, nil); err == nil {
		t.Fatal("selected SDK height was rewritten under the same final certificate", result["state_root"])
	}
}

type financialRecoveryBatchProbe struct{ head []byte }

func (probe *financialRecoveryBatchProbe) Put(key, value []byte) {
	if bytes.Equal(key, []byte("head")) {
		probe.head = append([]byte(nil), value...)
	}
}
func (probe *financialRecoveryBatchProbe) Delete(key []byte) {}

func TestFinancialPublicArchiveCompletionSyncUncertaintyReopensActualDurableOutcome(t *testing.T) {
	source, raw, _ := financialPublicFixture(t, 3, 2)
	for _, durable := range []bool{false, true} {
		t.Run(map[bool]string{false: "before_completion_sync", true: "after_completion_sync"}[durable], func(t *testing.T) {
			request, file, info := financialRestoreFixture(t, source, raw)
			injected := false
			_, err := restoreFinancialArchiveUsing(context.Background(), file, info, request, func(store *financialStore) {
				write := store.write
				store.write = func(batch *leveldb.Batch) error {
					probe := &financialRecoveryBatchProbe{}
					if batch.Replay(probe) != nil {
						t.Fatal("batch")
					}
					var head financialStoreHead
					if len(probe.head) > 0 && decodeStrict(probe.head, &head) == nil && head.Recovery != nil && head.Recovery.Complete && !injected {
						injected = true
						if durable {
							if err := write(batch); err != nil {
								return err
							}
						}
						return errors.New("owned completion sync uncertainty")
					}
					return write(batch)
				}
			})
			if err == nil || !injected {
				t.Fatal("completion fault not observed", err)
			}
			app, openErr := newDagEnabledLedger(source.Genesis, source.GenesisHash, request.RestoreRoot, false)
			if durable {
				if openErr != nil {
					t.Fatal("durable completion lost", openErr)
				}
				_ = app.Close()
			} else if openErr == nil {
				_ = app.Close()
				t.Fatal("uncommitted completion started normally")
			}
			result, err := restoreFinancialArchive(context.Background(), file, info, request)
			if err != nil || result["restore_reused"] != durable {
				t.Fatal("wrong durable completion outcome", err, result)
			}
		})
	}
}

func TestFinancialPublicArchiveColdStoreRejectsMissingOrRewrittenSDKHeaderEvidence(t *testing.T) {
	source, raw, _ := financialPublicFixture(t, 3, 2)
	for _, damage := range []string{"missing", "timestamp"} {
		t.Run(damage, func(t *testing.T) {
			request, file, info := financialRestoreFixture(t, source, raw)
			if _, err := restoreFinancialArchive(context.Background(), file, info, request); err != nil {
				t.Fatal(err)
			}
			db, err := leveldb.OpenFile(filepath.Join(request.RestoreRoot, "gg-financial-dag.leveldb"), nil)
			if err != nil {
				t.Fatal(err)
			}
			key := []byte(financialSDKHeaderKey(2))
			if damage == "missing" {
				err = db.Delete(key, &opt.WriteOptions{Sync: true})
			} else {
				value, readErr := db.Get(key, nil)
				var header types.Header
				if readErr != nil || cmtjson.Unmarshal(value, &header) != nil {
					t.Fatal("header")
				}
				header.Time = header.Time.Add(time.Nanosecond)
				value, readErr = cmtjson.Marshal(&header)
				if readErr != nil {
					t.Fatal(readErr)
				}
				err = db.Put(key, value, &opt.WriteOptions{Sync: true})
			}
			if err != nil || db.Close() != nil {
				t.Fatal("damage", err)
			}
			if app, err := newDagEnabledLedger(source.Genesis, source.GenesisHash, request.RestoreRoot, false); err == nil {
				_ = app.Close()
				t.Fatal("corrupt SDK evidence silently repaired")
			}
		})
	}
}
