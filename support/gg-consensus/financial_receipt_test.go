//go:build !js

package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	abci "github.com/cometbft/cometbft/abci/types"
	"github.com/syndtr/goleveldb/leveldb"
	"github.com/syndtr/goleveldb/leveldb/opt"
	"os"
	"path/filepath"
	"testing"
)

func TestFinancialCertifiedReceipt5000PaymentAndCreatorSurviveCutAndColdReplay(t *testing.T) {
	app, backend, accounts, producers, root := financialSDKFixture(t)
	inputs := make([][]byte, 5000)
	for index := range inputs {
		inputs[index] = testTx(app.genesis, app.anchor, accounts, 0, 1, "1", uint64(index))
	}
	wire, block := financialDagSignedBlock(t, backend.current, producers, 0, inputs, nil)
	commitFinancialSDK(t, app, financialDagBatchWire(t, backend.current, wire))
	selector := financialReceiptSelector{Block: block, Index: 4999}
	before := copyState(app.state)
	query, err := app.Query(context.Background(), &abci.RequestQuery{Path: "/gg/financial-dag/receipt", Data: canonical(selector)})
	if err != nil || query.Code != 0 {
		t.Fatal("bounded receipt query failed", err, query)
	}
	var proof financialCertifiedReceipt
	if decodeStrict(query.Value, &proof) != nil || checkFinancialCertifiedReceipt(proof, app.state, app.genesis) != nil || proof.Receipt.Leaf.TransactionID != financialIntentID(inputs[4999]) ||
		proof.Creator.Key != app.genesis.FinancialDAG.Producers[0] || proof.Creator.Sequence != 1 {
		t.Fatal("receipt did not prove exact monetary intent and creator")
	}
	if len(query.Value) > 32*1024 {
		t.Fatal("single receipt unexpectedly contains whole block or history")
	}
	cut, err := backend.current.prepareCut()
	if err != nil {
		t.Fatal(err)
	}
	commitFinancialSDK(t, app, cut)
	wire, newBlock := financialDagSignedBlock(t, backend.current, producers, 1, [][]byte{inputs[4999], testTx(app.genesis, app.anchor, accounts, 0, 1, "2", 5000)}, nil)
	commitFinancialSDK(t, app, financialDagBatchWire(t, backend.current, wire))
	rejected, err := backend.Receipt(context.Background(), app.state, financialReceiptSelector{Block: newBlock, Index: 0})
	if err != nil || rejected.Receipt.Leaf.Outcome != "REJECTED_NONCE" || checkFinancialCertifiedReceipt(rejected, app.state, app.genesis) != nil {
		t.Fatal("authentic state-conflict receipt was not certified", err)
	}
	// A receipt from a closed segment is authenticated by the NEW certificate,
	// not a claim that an old root means a still-live connection.
	current, err := backend.Receipt(context.Background(), app.state, selector)
	if err != nil || current.Context.Epoch != 1 || current.Summary.Transactions != 5000 || checkFinancialCertifiedReceipt(current, app.state, app.genesis) != nil {
		t.Fatal("closed receipt lost global certified membership", err)
	}
	packet := segmentedSDKPacket(t, app)
	packet.FinancialReceipt = &current
	verified, err := verifyInput(packet)
	if err != nil || verified["financial_receipt_verified"] != true || verified["financial_history_replay_verified"] != false {
		t.Fatal("SDK did not authenticate exact closed payment outcome", err)
	}
	if target := os.Getenv("GG_PUBLIC_FINANCIAL_SDK_OUTPUT"); target != "" {
		output, err := os.OpenFile(target, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
		if err != nil {
			t.Fatal(err)
		}
		encoded := canonical(packet)
		_, writeErr := output.Write(encoded)
		closeErr := output.Close()
		if writeErr != nil || closeErr != nil {
			t.Fatal("public synthetic receipt export failed")
		}
	}
	// Older retained height uses exactly its own MMR length/root.
	historical, err := backend.Receipt(context.Background(), before, selector)
	if err != nil || !bytes.Equal(canonical(historical), canonical(proof)) {
		t.Fatal("historical receipt substituted new root", err)
	}
	snapshot := copyState(app.state)
	_ = app.Close()
	reopened, err := newDagEnabledLedger(app.genesis, app.anchor, root, false)
	if err != nil {
		t.Fatal(err)
	}
	defer reopened.Close()
	replayed, err := reopened.financial.Receipt(context.Background(), reopened.state, selector)
	if err != nil || !bytes.Equal(canonical(replayed), canonical(current)) || reopened.state.StateRoot != snapshot.StateRoot {
		t.Fatal("replayed receipt differs from original committed evidence", err)
	}
	for _, mutate := range []func(*financialCertifiedReceipt){
		func(p *financialCertifiedReceipt) { p.Creator.Producer = 1 },
		func(p *financialCertifiedReceipt) { p.Creator.Key = DagZero },
		func(p *financialCertifiedReceipt) { p.Creator.Sequence++ },
		func(p *financialCertifiedReceipt) { p.Context.OrderIndex++ },
		func(p *financialCertifiedReceipt) { p.Context.Checkpoint++ },
		func(p *financialCertifiedReceipt) { p.Context.SourceHash = DagZero },
		func(p *financialCertifiedReceipt) { p.Receipt.Leaf.Outcome = "REJECTED_NONCE" },
		func(p *financialCertifiedReceipt) { p.Receipt.Leaf.TransactionID = DagZero },
		func(p *financialCertifiedReceipt) { p.Summary.Applied-- },
		func(p *financialCertifiedReceipt) { p.Summary.Transactions++ },
		func(p *financialCertifiedReceipt) { p.Payment.Body.Nonce++ },
		func(p *financialCertifiedReceipt) { p.SummaryPath[0].Hash = DagZero },
		func(p *financialCertifiedReceipt) { p.Height-- },
	} {
		var changed financialCertifiedReceipt
		_ = json.Unmarshal(canonical(current), &changed)
		mutate(&changed)
		packet.FinancialReceipt = &changed
		if checkFinancialCertifiedReceipt(changed, snapshot, app.genesis) == nil {
			t.Fatal("changed receipt accepted")
		}
		if _, err := verifyInput(packet); err == nil {
			t.Fatal("SDK verifier accepted substituted financial proof")
		}
	}
}

func TestFinancialSummaryMMRPathsBindEveryOddLengthIndexAndExactCount(t *testing.T) {
	tree := dagClosedSegments{}
	nodes := map[string][]byte{}
	ids := []string{}
	for count := 1; count <= 257; count++ {
		id := hashHex([]byte(fmt.Sprintf("public financial summary %d", count)))
		ids = append(ids, id)
		err := appendFinancialSummary(&tree, id, func(key, value string) error {
			if _, exists := nodes[key]; exists {
				return errors.New("immutable node replaced")
			}
			nodes[key] = []byte(value)
			return nil
		})
		if err != nil {
			t.Fatal(err)
		}
		root, err := tree.root()
		if err != nil {
			t.Fatal(err)
		}
		for _, index := range []int{1, count, (count + 1) / 2} {
			path, err := financialMMRPath(context.Background(), func(key string) ([]byte, error) {
				raw, ok := nodes[key]
				if !ok {
					return nil, leveldb.ErrNotFound
				}
				return raw, nil
			}, ids[index-1], uint64(index), uint64(count))
			if err != nil || verifyClosedCutPath(ids[index-1], path, uint64(index), uint64(count), root) != nil {
				t.Fatal("MMR path disagrees with independently updated accumulator", count, index, err)
			}
			// The count comes from the complete SDK-certified commitment. The generic
			// odd-node Merkle root alone does not authenticate its padding/count.
			if verifyClosedCutPath(DagZero, path, uint64(index), uint64(count), root) == nil {
				t.Fatal("changed financial summary accepted")
			}
		}
	}
}

func TestFinancialStoredReceiptAndSummaryNodesAreRecomputedFromSignedOriginals(t *testing.T) {
	for _, kind := range []string{"receipt", "summary_node", "missing_node"} {
		t.Run(kind, func(t *testing.T) {
			app, backend, accounts, producers, root := financialSDKFixture(t)
			wire, block := financialDagSignedBlock(t, backend.current, producers, 0, [][]byte{testTx(app.genesis, app.anchor, accounts, 0, 1, "3", 0)}, nil)
			commitFinancialSDK(t, app, financialDagBatchWire(t, backend.current, wire))
			_ = app.Close()
			db, err := leveldb.OpenFile(filepath.Join(root, "gg-financial-dag.leveldb"), &opt.Options{ErrorIfMissing: true})
			if err != nil {
				t.Fatal(err)
			}
			switch kind {
			case "receipt":
				raw, _ := db.Get([]byte("p/"+block), nil)
				var record financialReceiptArchive
				if json.Unmarshal(raw, &record) != nil {
					t.Fatal("fixture")
				}
				record.Receipts[0].Outcome = "REJECTED_FUNDS"
				err = db.Put([]byte("p/"+block), canonical(record), &opt.WriteOptions{Sync: true})
			case "summary_node":
				err = db.Put([]byte(financialSummaryNodeKey(0, 1)), []byte(DagZero), &opt.WriteOptions{Sync: true})
			case "missing_node":
				err = db.Delete([]byte(financialSummaryNodeKey(0, 1)), &opt.WriteOptions{Sync: true})
			}
			if err != nil {
				t.Fatal(err)
			}
			_ = db.Close()
			if reopened, err := newDagEnabledLedger(app.genesis, app.anchor, root, false); err == nil {
				reopened.Close()
				t.Fatal("derived receipt data trusted without original replay")
			}
		})
	}
}
