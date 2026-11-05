//go:build !js

package main

// Real signatures and ABCI application/disk transitions. Signed SDK headers in
// these unit fixtures are not evidence of live multi-process consensus.
import (
	"bytes"
	"context"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"errors"
	"fmt"
	cmted "github.com/cometbft/cometbft/crypto/ed25519"
	cmtjson "github.com/cometbft/cometbft/libs/json"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"testing"
	"time"

	abci "github.com/cometbft/cometbft/abci/types"
	"github.com/syndtr/goleveldb/leveldb"
	"github.com/syndtr/goleveldb/leveldb/opt"
)

func financialGeneralTestKey(index int) ed25519.PrivateKey {
	seed := sha256.Sum256([]byte(fmt.Sprintf("PUBLIC-GENERAL-ACCOUNT-APPLICATION-%d", index)))
	return ed25519.NewKeyFromSeed(seed[:])
}
func financialGeneralTestAddress(index int) string {
	return hex.EncodeToString(financialGeneralTestKey(index).Public().(ed25519.PublicKey))
}
func financialGeneralModel(t *testing.T, initial int, maximum uint64) (*financialDagExecution, []ed25519.PrivateKey, []ed25519.PrivateKey) {
	t.Helper()
	old, _, producers := financialLineageFixture(t)
	genesis := old.genesis
	source := old.source
	source.Schema = financialGeneralSourceSchema
	source.Policy = source.rules()
	genesis.Schema = "gg.native.genesis.v6"
	genesis.Accounts = nil
	genesis.FinancialDAG = &source
	genesis.FinancialAccounts = &financialAccountGenesis{MaxAccounts: maximum, Schema: "gg.financial.account-genesis.v1", Allocations: []financialAccountAllocation{}}
	keys := make([]ed25519.PrivateKey, initial)
	for index := range keys {
		keys[index] = financialGeneralTestKey(index)
		balance := Supply / uint64(initial)
		if index == 0 {
			balance += Supply % uint64(initial)
		}
		genesis.FinancialAccounts.Allocations = append(genesis.FinancialAccounts.Allocations, financialAccountAllocation{Address: financialGeneralTestAddress(index), Balance: strconv.FormatUint(balance, 10)})
	}
	sort.Slice(genesis.FinancialAccounts.Allocations, func(a, b int) bool {
		return genesis.FinancialAccounts.Allocations[a].Address < genesis.FinancialAccounts.Allocations[b].Address
	})
	model, err := newFinancialDagExecution(genesis, hashHex(canonical(genesis)), source)
	if err != nil {
		t.Fatal(err)
	}
	return model, keys, producers
}
func financialGeneralSDKFixture(t *testing.T, initial int, maximum uint64) (*Ledger, *financialNativeApplication, []ed25519.PrivateKey, []ed25519.PrivateKey, string) {
	t.Helper()
	model, keys, producers := financialGeneralModel(t, initial, maximum)
	root := t.TempDir()
	app, err := newFinancialLedger(model.genesis, model.anchor, root, true)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = app.Close() })
	return app, app.financial.(*financialNativeApplication), keys, producers, root
}
func financialGeneralPayment(genesis Genesis, anchor string, key ed25519.PrivateKey, recipient, amount string, nonce uint64) []byte {
	body := Body{Amount: amount, ChainID: genesis.ChainID, GenesisHash: anchor, Nonce: nonce, Recipient: recipient, Sender: hex.EncodeToString(key.Public().(ed25519.PublicKey)), Version: 1}
	return canonical(Envelope{Body: body, Signature: hex.EncodeToString(ed25519.Sign(key, canonical(body)))})
}
func financialGeneralQuery(t *testing.T, app *Ledger, address string, height int64) financialCertifiedAccount {
	t.Helper()
	result, err := app.Query(context.Background(), &abci.RequestQuery{Path: "/gg/financial-dag/account-proof", Data: canonical(address), Height: height})
	var proof financialCertifiedAccount
	if err != nil || result.Code != 0 || decodeStrict(result.Value, &proof) != nil {
		t.Fatal("account query", result, err)
	}
	return proof
}

func TestFinancialGeneralGenesisAndCompactStateAreVersioned(t *testing.T) {
	model, _, _ := financialGeneralModel(t, 3, 8192)
	state := initialState(model.genesis, model.anchor)
	if state.Accounts != nil || model.genesis.Accounts != nil || state.AccountTree == nil || state.AccountTree.Count != 3 ||
		state.Schema != "gg.native.state.v5" || state.FinancialDAG.Schema != "gg.financial-dag.commitment.v4" || commitmentFor(state).Schema != "gg.native.commitment.v5" || validateState(state, model.genesis, model.anchor) != nil {
		t.Fatal("general state did not replace global account list with bound root")
	}
	for name, change := range map[string]func(*Genesis){
		"old_schema": func(v *Genesis) { v.Schema = "gg.native.genesis.v5" }, "old_source": func(v *Genesis) { v.FinancialDAG.Schema = financialLineageSourceSchema },
		"legacy_accounts": func(v *Genesis) { v.Accounts = []string{financialGeneralTestAddress(0)} }, "empty_allocation": func(v *Genesis) { v.FinancialAccounts.Allocations = []financialAccountAllocation{} },
		"unsorted": func(v *Genesis) { a := v.FinancialAccounts.Allocations; a[0], a[1] = a[1], a[0] }, "duplicate": func(v *Genesis) {
			v.FinancialAccounts.Allocations[1].Address = v.FinancialAccounts.Allocations[0].Address
		},
		"supply": func(v *Genesis) { v.FinancialAccounts.Allocations[0].Balance = "1" }, "zero": func(v *Genesis) { v.FinancialAccounts.Allocations[0].Balance = "0" },
		"limit": func(v *Genesis) { v.FinancialAccounts.MaxAccounts = 2 }, "role_key": func(v *Genesis) { v.FinancialAccounts.Allocations[0].Address = v.Validators[0] },
	} {
		t.Run(name, func(t *testing.T) {
			var changed Genesis
			if decodeStrict(canonical(model.genesis), &changed) != nil {
				t.Fatal("copy")
			}
			change(&changed)
			if validateGenesis(changed, hashHex(canonical(changed))) == nil {
				t.Fatal("invalid version/allocation accepted")
			}
		})
	}
	changed := copyState(state)
	changed.AccountTree.Count++
	sealState(&changed)
	if validateState(changed, model.genesis, model.anchor) == nil {
		t.Fatal("unmatched root metadata accepted")
	}
	changed = copyState(state)
	changed.Accounts = []Account{{Address: financialGeneralTestAddress(0), Balance: "1"}}
	sealState(&changed)
	if validateState(changed, model.genesis, model.anchor) == nil {
		t.Fatal("provider account table accepted instead of authenticated dictionary")
	}
}

func TestFinancialGeneralSDK5000DistinctFundedAccountsCutsAndColdReplay(t *testing.T) {
	ctx := context.Background()
	app, backend, keys, producers, root := financialGeneralSDKFixture(t, 3, 8192)
	inputs := make([][]byte, 5000)
	for index := range inputs {
		inputs[index] = financialGeneralPayment(app.genesis, app.anchor, keys[0], financialGeneralTestAddress(index+100), "1", uint64(index))
	}
	wire, id := financialLineageBlock(t, backend.current, producers, 0, inputs, nil)
	batch := financialDagBatchWire(t, backend.current, wire)
	before := canonical(app.state)
	checked, err := app.CheckTx(ctx, &abci.RequestCheckTx{Tx: batch})
	if err != nil || checked.Code != 0 {
		t.Fatal("signed general mempool", checked, err)
	}
	when := time.Unix(0, backend.store.timeNs+1000000)
	proposal, err := app.PrepareProposal(ctx, &abci.RequestPrepareProposal{Time: when, MaxTxBytes: 64 << 20, Txs: [][]byte{batch}})
	if err != nil || len(proposal.Txs) != 1 {
		t.Fatal("proposal", err)
	}
	processed, err := app.ProcessProposal(ctx, &abci.RequestProcessProposal{Time: when, Txs: proposal.Txs})
	if err != nil || processed.Status != abci.ResponseProcessProposal_ACCEPT || !bytes.Equal(before, canonical(app.state)) {
		t.Fatal("proposal published accounts before commit", err)
	}
	commitFinancialSDK(t, app, batch)
	if app.state.Accounts != nil || app.state.AccountTree.Count != 5003 || app.state.AccountTree.Total != "1000000000000" || app.state.FinancialDAG.Applied != 5000 {
		t.Fatal("did not execute actual signed funding")
	}
	if backend.current.money.Tree.root.node != nil || backend.current.money.Tree.read == nil {
		t.Fatal("committed account graph retained in RAM")
	}
	for _, index := range []int{100, 2599, 5099, 9000} {
		proof := financialGeneralQuery(t, app, financialGeneralTestAddress(index), 0)
		packet := segmentedSDKPacket(t, app)
		packet.FinancialAccount = &proof
		packet.ExpectedFinancialAccount = proof.Proof.Address
		result, err := verifyInput(packet)
		if err != nil || result["financial_account_verified"] != true || result["financial_account_exists"] != (index != 9000) {
			t.Fatal(index, result, err)
		}
	}
	late, _ := financialLineageBlock(t, backend.current, producers, 1, [][]byte{financialGeneralPayment(app.genesis, app.anchor, keys[0], financialGeneralTestAddress(6000), "2", 5000)}, nil)
	commitFinancialSDK(t, app, nil)
	cut, err := backend.current.prepareCut()
	if err != nil {
		t.Fatal(err)
	}
	commitFinancialSDK(t, app, cut)
	commitFinancialSDK(t, app, financialDagBatchWire(t, backend.current, late))
	if app.state.AccountTree.Count != 5004 || app.state.FinancialDAG.Applied != 5001 || app.state.FinancialDAG.Epoch != 2 {
		t.Fatal("delayed original could not fund new account after cut")
	}
	oldProof := financialGeneralQuery(t, app, financialGeneralTestAddress(6000), 1)
	oldState, err := app.stateAt(1)
	if err != nil {
		t.Fatal(err)
	}
	if _, exists, err := checkFinancialCertifiedAccount(ctx, oldProof, oldState, app.genesis); err != nil || exists {
		t.Fatal("historical absence changed", exists, err)
	}
	receipt, err := backend.Receipt(ctx, app.state, financialReceiptSelector{Block: id, Index: 4999})
	if err != nil {
		t.Fatal(err)
	}
	packet := segmentedSDKPacket(t, app)
	packet.FinancialReceipt = &receipt
	if receipt.Receipt.Leaf.Schema != "gg.financial.receipt.v2" || receipt.Summary.Schema != "gg.financial.summary.v2" {
		t.Fatal("receipt version not explicit")
	}
	if result, err := verifyInput(packet); err != nil || result["financial_receipt_verified"] != true {
		t.Fatal(result, err)
	}
	snapshot := canonical(app.state)
	if app.Close() != nil {
		t.Fatal("close")
	}
	reopened, err := newFinancialLedger(app.genesis, app.anchor, root, false)
	if err != nil {
		t.Fatal(err)
	}
	defer reopened.Close()
	if !bytes.Equal(snapshot, canonical(reopened.state)) {
		t.Fatal("full original account replay changed state")
	}
	proof := financialGeneralQuery(t, reopened, financialGeneralTestAddress(6000), 0)
	if value, exists, err := checkFinancialCertifiedAccount(ctx, proof, reopened.state, reopened.genesis); err != nil || !exists || value.Balance != "2" {
		t.Fatal(value, exists, err)
	}
	cold := reopened.financial.(*financialNativeApplication)
	if cold.current.money.Tree.root.node != nil || len(cold.store.accountCache.entries) > financialAccountCacheNodes {
		t.Fatal("unbounded account cache")
	}
	t.Log("actual account/producer signatures and ABCI storage, historical proofs, cut, late original and cold full replay; not live network capacity")
}

type financialGeneralBatchKeys struct{ keys []string }

func (record *financialGeneralBatchKeys) Put(key, value []byte) {
	record.keys = append(record.keys, string(key))
}
func (record *financialGeneralBatchKeys) Delete(key []byte) {}

func TestFinancialGeneralAtomicCommitFailureBeforeAndAfterWrite(t *testing.T) {
	for _, afterWrite := range []bool{false, true} {
		t.Run(strconv.FormatBool(afterWrite), func(t *testing.T) {
			app, backend, keys, producers, root := financialGeneralSDKFixture(t, 3, 8192)
			wire, _ := financialLineageBlock(t, backend.current, producers, 0, [][]byte{financialGeneralPayment(app.genesis, app.anchor, keys[0], financialGeneralTestAddress(100), "1", 0)}, nil)
			batch := financialDagBatchWire(t, backend.current, wire)
			if err := backend.store.stage(context.Background(), batch); err != nil {
				t.Fatal(err)
			}
			original := backend.store.write
			observed := false
			backend.store.write = func(transaction *leveldb.Batch) error {
				record := &financialGeneralBatchKeys{}
				if err := transaction.Replay(record); err != nil {
					return err
				}
				head, journal, accounts := false, false, false
				for _, key := range record.keys {
					head = head || key == "head"
					journal = journal || strings.HasPrefix(key, "j/")
					accounts = accounts || strings.HasPrefix(key, financialAccountPrefix)
				}
				if !head || !journal || !accounts {
					t.Fatal("account nodes, original journal and head were split across writes")
				}
				observed = true
				if afterWrite {
					if err := original(transaction); err != nil {
						return err
					}
				}
				return errors.New("simulated bounded storage failure")
			}
			before := canonical(app.state)
			when := time.Unix(0, backend.store.timeNs+1000000)
			if _, err := app.FinalizeBlock(context.Background(), &abci.RequestFinalizeBlock{Height: 1, Time: when, Txs: [][]byte{batch}}); err != nil {
				t.Fatal(err)
			}
			if _, err := app.Commit(context.Background(), &abci.RequestCommit{}); err == nil || !observed || !bytes.Equal(before, canonical(app.state)) {
				t.Fatal("failed commit published partial money", err)
			}
			if app.Close() != nil {
				t.Fatal("close")
			}
			reopened, err := newFinancialLedger(app.genesis, app.anchor, root, false)
			if err != nil {
				t.Fatal(err)
			}
			defer reopened.Close()
			expected := uint64(0)
			if afterWrite {
				expected = 1
			}
			if reopened.state.FinancialDAG.Applied != expected || reopened.state.AccountTree.Count != 3+expected {
				t.Fatal("atomic disk boundary did not determine replay")
			}
			proof := financialGeneralQuery(t, reopened, financialGeneralTestAddress(100), 0)
			if _, exists, err := checkFinancialCertifiedAccount(context.Background(), proof, reopened.state, reopened.genesis); err != nil || exists != afterWrite {
				t.Fatal(exists, err)
			}
		})
	}
}

func TestFinancialGeneralColdReplayRejectsMissingCorruptAndExtraAccountNodes(t *testing.T) {
	for _, mode := range []string{"missing", "corrupt", "extra", "different_rules"} {
		t.Run(mode, func(t *testing.T) {
			app, backend, keys, producers, root := financialGeneralSDKFixture(t, 3, 8192)
			wire, _ := financialLineageBlock(t, backend.current, producers, 0, [][]byte{financialGeneralPayment(app.genesis, app.anchor, keys[0], financialGeneralTestAddress(100), "1", 0)}, nil)
			commitFinancialSDK(t, app, financialDagBatchWire(t, backend.current, wire))
			nodeHash := app.state.AccountTree.Hash
			if app.Close() != nil {
				t.Fatal("close")
			}
			db, err := leveldb.OpenFile(filepath.Join(root, "gg-financial-dag.leveldb"), &opt.Options{ErrorIfMissing: true, Strict: opt.StrictAll})
			if err != nil {
				t.Fatal(err)
			}
			key := []byte(financialAccountPrefix + nodeHash)
			switch mode {
			case "missing":
				err = db.Delete(key, &opt.WriteOptions{Sync: true})
			case "corrupt":
				err = db.Put(key, []byte(`{}`), &opt.WriteOptions{Sync: true})
			case "extra":
				rules, _ := financialAccountRulesFor(app.genesis, app.anchor)
				tree, _ := newFinancialAccountTree(rules)
				tree, err = tree.set(context.Background(), Account{Address: financialGeneralTestAddress(9999), Balance: "1"})
				if err == nil {
					err = db.Put([]byte(financialAccountPrefix+tree.root.link.Hash), canonical(*tree.root.node), &opt.WriteOptions{Sync: true})
				}
			case "different_rules":
				raw, readErr := db.Get(key, nil)
				if readErr != nil {
					t.Fatal(readErr)
				}
				var node financialAccountNode
				if decodeStrict(raw, &node) != nil {
					t.Fatal("node")
				}
				node.Rules = strings.Repeat("f", 64)
				err = db.Put(key, canonical(node), &opt.WriteOptions{Sync: true})
			}
			if err != nil {
				t.Fatal(err)
			}
			if db.Close() != nil {
				t.Fatal("close corrupt fixture")
			}
			if reopened, err := newFinancialLedger(app.genesis, app.anchor, root, false); err == nil {
				_ = reopened.Close()
				t.Fatal("invalid account index accepted", mode)
			}
		})
	}
}

func TestFinancialGeneralAccountLimitIsAnOrderedReceiptNotBatchFailure(t *testing.T) {
	app, backend, keys, producers, _ := financialGeneralSDKFixture(t, 3, 3)
	inputs := [][]byte{financialGeneralPayment(app.genesis, app.anchor, keys[0], financialGeneralTestAddress(100), "1", 0), financialGeneralPayment(app.genesis, app.anchor, keys[0], financialGeneralTestAddress(1), "1", 0)}
	wire, id := financialLineageBlock(t, backend.current, producers, 0, inputs, nil)
	commitFinancialSDK(t, app, financialDagBatchWire(t, backend.current, wire))
	if app.state.FinancialDAG.Applied != 1 || app.state.FinancialDAG.Rejected != 1 || app.state.AccountTree.Count != 3 {
		t.Fatal("account cap blocked unrelated valid payment")
	}
	for index, expected := range []string{"REJECTED_ACCOUNT_LIMIT", "APPLIED"} {
		receipt, err := backend.Receipt(context.Background(), app.state, financialReceiptSelector{Block: id, Index: index})
		if err != nil || receipt.Receipt.Leaf.Outcome != expected {
			t.Fatal(receipt, err)
		}
		packet := segmentedSDKPacket(t, app)
		packet.FinancialReceipt = &receipt
		if _, err := verifyInput(packet); err != nil {
			t.Fatal("certified v2 outcome rejected", err)
		}
	}
}

func TestFinancialGeneralCertifiedAccountProofRejectsForgeries(t *testing.T) {
	app, backend, keys, producers, _ := financialGeneralSDKFixture(t, 3, 8192)
	wire, _ := financialLineageBlock(t, backend.current, producers, 0, [][]byte{financialGeneralPayment(app.genesis, app.anchor, keys[0], financialGeneralTestAddress(100), "2", 0)}, nil)
	commitFinancialSDK(t, app, financialDagBatchWire(t, backend.current, wire))
	for _, exists := range []bool{true, false} {
		t.Run(strconv.FormatBool(exists), func(t *testing.T) {
			index := 100
			if !exists {
				index = 9999
			}
			proof := financialGeneralQuery(t, app, financialGeneralTestAddress(index), 0)
			packet := segmentedSDKPacket(t, app)
			packet.FinancialAccount = &proof
			packet.ExpectedFinancialAccount = proof.Proof.Address
			if result, err := verifyInput(packet); err != nil || result["financial_account_exists"] != exists {
				t.Fatal(result, err)
			}
			for name, change := range map[string]func(*VerifyInput){
				"height": func(v *VerifyInput) { v.FinancialAccount.Height++ }, "state_root": func(v *VerifyInput) { v.FinancialAccount.StateRoot = strings.Repeat("f", 64) },
				"genesis": func(v *VerifyInput) { v.FinancialAccount.GenesisHash = strings.Repeat("f", 64) }, "rules": func(v *VerifyInput) { v.FinancialAccount.Proof.Rules = strings.Repeat("f", 64) },
				"exists": func(v *VerifyInput) { v.FinancialAccount.Proof.Exists = !v.FinancialAccount.Proof.Exists }, "key": func(v *VerifyInput) { v.FinancialAccount.Proof.Address = financialGeneralTestAddress(9998) },
				"nonce": func(v *VerifyInput) { v.FinancialAccount.Proof.Path[0].Account.Nonce++ }, "balance": func(v *VerifyInput) { v.FinancialAccount.Proof.Path[0].Account.Balance = "0" },
				"missing": func(v *VerifyInput) {
					v.FinancialAccount.Proof.Path = v.FinancialAccount.Proof.Path[:len(v.FinancialAccount.Proof.Path)-1]
				},
				"extra": func(v *VerifyInput) {
					v.FinancialAccount.Proof.Path = append(v.FinancialAccount.Proof.Path, v.FinancialAccount.Proof.Path[0])
				},
				"metadata": func(v *VerifyInput) { v.State.AccountTree.Count++ }, "old_proof_type": func(v *VerifyInput) {
					v.AccountProof = &Proof{Schema: "gg.native.proof.v1", Height: v.State.Height, ChainID: v.State.ChainID, GenesisHash: v.State.GenesisHash, AccountRoot: v.State.AccountRoot, StateRoot: v.State.StateRoot, Commitment: commitmentFor(v.State)}
				},
				"requested_account": func(v *VerifyInput) { v.ExpectedFinancialAccount = financialGeneralTestAddress(9998) }, "missing_requested_account": func(v *VerifyInput) { v.ExpectedFinancialAccount = "" },
			} {
				t.Run(name, func(t *testing.T) {
					var changed VerifyInput
					if decodeStrict(canonical(packet), &changed) != nil {
						t.Fatal("copy")
					}
					change(&changed)
					if _, err := verifyInput(changed); err == nil {
						t.Fatal("forged certificate-bound account accepted")
					}
				})
			}
		})
	}
}

func financialGeneralObserverArchiveFixture(t *testing.T) (financialObserverRestoreCommand, []byte, []string) {
	t.Helper()
	ctx := context.Background()
	genesis, _, committee := membershipFixture(t)
	model, keys, producers := financialGeneralModel(t, 3, 8192)
	source := model.source
	source.NativeChainID = genesis.ChainID
	source.StartedAtNs = strconv.FormatInt(genesis.GenesisTime*1000000000, 10)
	genesis.DAG = nil
	genesis.Accounts = nil
	genesis.Schema = "gg.native.genesis.v6"
	genesis.FinancialDAG = &source
	genesis.FinancialAccounts = model.genesis.FinancialAccounts
	anchor := hashHex(canonical(genesis))
	if validateGenesis(genesis, anchor) != nil {
		t.Fatal("general account allocations were coupled to voter accounts")
	}
	root := t.TempDir()
	app, err := newFinancialLedger(genesis, anchor, root, true)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = app.Close() })
	backend := app.financial.(*financialNativeApplication)
	nonce := uint64(0)
	ids := []string{}
	for turn, count := range []int{129, 7, 5} {
		inputs := make([][]byte, count)
		for index := range inputs {
			inputs[index] = financialGeneralPayment(genesis, anchor, keys[0], financialGeneralTestAddress(100+int(nonce)), "1", nonce)
			nonce++
		}
		wire, id := financialLineageBlock(t, backend.current, producers, 0, inputs, nil)
		ids = append(ids, id)
		commitFinancialSDK(t, app, financialDagBatchWire(t, backend.current, wire))
		commitFinancialSDK(t, app, nil)
		if turn < 2 {
			cut, err := backend.current.prepareCut()
			if err != nil {
				t.Fatal(err)
			}
			commitFinancialSDK(t, app, cut)
		}
	}
	// This private key was absent from genesis, received real funds, and now
	// signs its own spend. A producer or validator cannot sign on its behalf.
	spend := financialGeneralPayment(genesis, anchor, financialGeneralTestKey(100), financialGeneralTestAddress(999), "1", 0)
	wire, _ := financialLineageBlock(t, backend.current, producers, 1, [][]byte{spend}, nil)
	commitFinancialSDK(t, app, financialDagBatchWire(t, backend.current, wire))
	proof := financialGeneralQuery(t, app, financialGeneralTestAddress(100), 0)
	if account, exists, err := checkFinancialCertifiedAccount(ctx, proof, app.state, genesis); err != nil || !exists || account.Balance != "0" || account.Nonce != 1 {
		t.Fatal("funded outside account could not spend", account, exists, err)
	}
	state := copyState(app.state)
	if state.AccountTree.Count != 145 || state.FinancialDAG.Applied != 142 {
		t.Fatal("general account archive fixture counters", state.AccountTree, state.FinancialDAG.Applied)
	}
	if app.Close() != nil {
		t.Fatal("close")
	}
	signers := []cmted.PrivKey{}
	for _, member := range committee {
		signers = append(signers, cmted.PrivKey(member[0]))
	}
	header := financialFixtureSDKChain(t, genesis, anchor, root, state, signers)
	signed, err := cmtjson.Marshal(header)
	if err != nil {
		t.Fatal(err)
	}
	certificate := dagArchiveCertificate{Schema: "gg.consensus.proof.v1", Genesis: genesis, GenesisHash: anchor, State: state, SignedHeader: signed}
	request := financialArchiveCommand{Genesis: genesis, GenesisHash: anchor, Root: root, Certificate: &certificate, ArchivePath: filepath.Join(t.TempDir(), "general-history.ggfin")}
	var output bytes.Buffer
	if _, err := exportFinancialArchive(ctx, &output, request); err != nil {
		t.Fatal("general account export", err)
	}
	raw := output.Bytes()
	if err := os.WriteFile(request.ArchivePath, raw, 0600); err != nil {
		t.Fatal(err)
	}
	node := financialGeneralTestKey(20000)
	grantKeys := []ed25519.PrivateKey{node, committee[0][3], producers[0]}
	grant := signObserverGrantFixture(nativeObserverGrantBody{GenesisHash: anchor, Host: "127.0.0.1", P2PPort: 24009, LabelUTF8: base64.StdEncoding.EncodeToString([]byte("General account recovered observer")),
		NodeKey: hex.EncodeToString(node.Public().(ed25519.PublicKey)), OwnerPeerKey: hex.EncodeToString(grantKeys[1].Public().(ed25519.PublicKey)), ProducerKey: source.Producers[0], Schema: nativeObserverGrantSchema, SignatureProfile: TransactionSignatureProfile}, grantKeys)
	if validateNativeObserverGrant(grant, genesis, anchor) != nil {
		t.Fatal("general observer grant")
	}
	request.Root = ""
	request.RestoreRoot = filepath.Join(t.TempDir(), "general-observer-native")
	return financialObserverRestoreCommand{financialArchiveCommand: request, ArchiveHash: hashHex(raw), ObserverGrant: grant}, raw, ids
}

func TestFinancialGeneralArchiveFullOriginalReplayAndApplicationRestore(t *testing.T) {
	ctx := context.Background()
	observer, raw, ids := financialGeneralObserverArchiveFixture(t)
	request := observer.financialArchiveCommand
	result, err := readFinancialArchive(ctx, bytes.NewReader(raw), request, nil)
	if err != nil || result["payments_applied"] != "142" || result["snapshot_trust_used"] != false {
		t.Fatal(result, err)
	}
	request.RestoreRoot = t.TempDir()
	file, info, err := openFinancialArchiveInput(request.ArchivePath)
	if err != nil {
		t.Fatal(err)
	}
	defer file.Close()
	restored, err := restoreFinancialArchive(ctx, file, info, request)
	if err != nil || restored["application_store_restored"] != true {
		t.Fatal("general application restore", restored, err)
	}
	app, err := newFinancialLedger(request.Genesis, request.GenesisHash, request.RestoreRoot, false)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(canonical(app.state), canonical(request.Certificate.State)) {
		t.Fatal("restored general state differs")
	}
	for _, index := range []int{100, 999, 9999} {
		proof := financialGeneralQuery(t, app, financialGeneralTestAddress(index), 0)
		if _, exists, err := checkFinancialCertifiedAccount(ctx, proof, app.state, app.genesis); err != nil || exists != (index != 9999) {
			t.Fatal(index, exists, err)
		}
	}
	receipt, err := app.financial.Receipt(ctx, app.state, financialReceiptSelector{Block: ids[0], Index: 128})
	if err != nil || checkFinancialCertifiedReceipt(receipt, app.state, app.genesis) != nil {
		t.Fatal("old restored general receipt", err)
	}
	if app.Close() != nil {
		t.Fatal("close")
	}
	again, err := restoreFinancialArchive(ctx, file, info, request)
	if err != nil || again["restore_reused"] != true {
		t.Fatal("exact restore retry", again, err)
	}
}

func TestFinancialGeneralOfflineObserverSDKRestoreRemainsNonVoting(t *testing.T) {
	ctx := context.Background()
	request, _, _ := financialGeneralObserverArchiveFixture(t)
	result, err := restoreFinancialObserver(ctx, request, nil)
	if err != nil || result["sdk_offline_bootstrap_complete"] != true || result["consensus_signing"] != false || result["native_node_ready"] != false || result["network_contact_asserted"] != false {
		t.Fatal("offline general observer scope", result, err)
	}
	app, err := newFinancialLedger(request.Genesis, request.GenesisHash, request.RestoreRoot, false)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(canonical(app.state), canonical(request.Certificate.State)) {
		t.Fatal("offline SDK recovery lost account state")
	}
	proof := financialGeneralQuery(t, app, financialGeneralTestAddress(999), 0)
	if value, exists, err := checkFinancialCertifiedAccount(ctx, proof, app.state, app.genesis); err != nil || !exists || value.Balance != "1" {
		t.Fatal(value, exists, err)
	}
	if app.Close() != nil {
		t.Fatal("close")
	}
	if _, err := os.Lstat(filepath.Join(request.RestoreRoot, "data/priv_validator_state.json")); !os.IsNotExist(err) {
		t.Fatal("observer recovery created signing state")
	}
	again, err := restoreFinancialObserver(ctx, request, nil)
	if err != nil || again["restore_reused"] != true {
		t.Fatal("observer retry", again, err)
	}
}

func TestFinancialGeneralUnknownSenderAndBadSignaturesCannotCreateFunds(t *testing.T) {
	app, backend, keys, producers, _ := financialGeneralSDKFixture(t, 3, 8192)
	ctx := context.Background()
	unfunded := financialGeneralPayment(app.genesis, app.anchor, financialGeneralTestKey(100), financialGeneralTestAddress(1), "1", 0)
	wire, id := financialLineageBlock(t, backend.current, producers, 0, [][]byte{unfunded}, nil)
	commitFinancialSDK(t, app, financialDagBatchWire(t, backend.current, wire))
	receipt, err := backend.Receipt(ctx, app.state, financialReceiptSelector{Block: id, Index: 0})
	if err != nil || receipt.Receipt.Leaf.Outcome != "REJECTED_FUNDS" || app.state.AccountTree.Count != 3 {
		t.Fatal("unfunded signature minted an account or balance", err)
	}
	valid := financialGeneralPayment(app.genesis, app.anchor, keys[0], financialGeneralTestAddress(100), "1", 0)
	var forged Envelope
	if decodeStrict(valid, &forged) != nil {
		t.Fatal("input")
	}
	forged.Body.Amount = "2"
	bad, _ := financialLineageBlock(t, backend.current, producers, 1, [][]byte{canonical(forged)}, nil)
	before := canonical(app.state)
	check, err := app.CheckTx(ctx, &abci.RequestCheckTx{Tx: financialDagBatchWire(t, backend.current, bad)})
	if err != nil || check.Code == 0 || !bytes.Equal(before, canonical(app.state)) {
		t.Fatal("producer signature replaced account authority", check, err)
	}
}

func TestFinancialGeneralPublicProofVectorsUseActualSharedVerifierInput(t *testing.T) {
	app, backend, keys, producers, _ := financialGeneralSDKFixture(t, 3, 8192)
	wire, id := financialLineageBlock(t, backend.current, producers, 0, [][]byte{financialGeneralPayment(app.genesis, app.anchor, keys[0], financialGeneralTestAddress(100), "2", 0)}, nil)
	commitFinancialSDK(t, app, financialDagBatchWire(t, backend.current, wire))
	packets := map[string]VerifyInput{}
	for name, index := range map[string]int{"membership": 100, "absence": 9999} {
		proof := financialGeneralQuery(t, app, financialGeneralTestAddress(index), 0)
		packet := segmentedSDKPacket(t, app)
		packet.FinancialAccount = &proof
		packet.ExpectedFinancialAccount = proof.Proof.Address
		if _, err := verifyInput(packet); err != nil {
			t.Fatal(name, err)
		}
		packets[name] = packet
	}
	receipt, err := backend.Receipt(context.Background(), app.state, financialReceiptSelector{Block: id, Index: 0})
	if err != nil {
		t.Fatal(err)
	}
	packet := segmentedSDKPacket(t, app)
	packet.FinancialReceipt = &receipt
	if _, err := verifyInput(packet); err != nil {
		t.Fatal(err)
	}
	packets["receipt"] = packet
	producer, err := backend.ProducerContext(context.Background(), app.state, 0)
	if err != nil {
		t.Fatal(err)
	}
	packet = segmentedSDKPacket(t, app)
	packet.FinancialProducer = &producer
	if _, err := verifyInput(packet); err != nil {
		t.Fatal(err)
	}
	packets["producer"] = packet
	if target := os.Getenv("GG_PUBLIC_GENERAL_ACCOUNT_FIXTURES"); target != "" {
		file, err := os.OpenFile(target, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
		if err != nil {
			t.Fatal(err)
		}
		_, writeErr := file.Write(canonical(packets))
		closeErr := file.Close()
		if writeErr != nil || closeErr != nil {
			t.Fatal(writeErr, closeErr)
		}
	}
}

func TestFinancialGeneralProducerViewsUseMetadataValuesAcrossEmptyHeights(t *testing.T) {
	app, backend, keys, producers, _ := financialGeneralSDKFixture(t, 3, 8192)
	wire, _ := financialLineageBlock(t, backend.current, producers, 0, [][]byte{financialGeneralPayment(app.genesis, app.anchor, keys[0], financialGeneralTestAddress(100), "1", 0)}, nil)
	commitFinancialSDK(t, app, financialDagBatchWire(t, backend.current, wire))
	count := len(backend.store.producerViews)
	for turn := 0; turn < 3; turn++ {
		commitFinancialSDK(t, app, nil)
		if len(backend.store.producerViews) != count {
			t.Fatal("identical account metadata consumed a producer view slot")
		}
		state := copyState(app.state)
		proof, err := backend.ProducerContext(context.Background(), state, 0)
		if err != nil || checkFinancialProducerContext(proof, state, app.genesis) != nil {
			t.Fatal("copied metadata could not select exact producer witness", err)
		}
	}
}
