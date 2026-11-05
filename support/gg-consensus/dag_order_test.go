package main

import (
	"context"
	"encoding/json"
	abci "github.com/cometbft/cometbft/abci/types"
	cmtjson "github.com/cometbft/cometbft/libs/json"
	"github.com/cometbft/cometbft/types"
	"strings"
	"testing"
	"time"
)

func TestDagOrderPagesAreCompleteContiguousPinnedAndHistorical(t *testing.T) {
	app, keys, _ := dagLedgerFixture(t)
	ctx := context.Background()
	for height := int64(1); height <= 2; height++ {
		base := app.dag.clone()
		wires := [][]byte{}
		count := 33
		if height == 2 {
			count = 32
		}
		for index := 0; index < count; index++ {
			transactions := index % 3 // Includes actual signed empty blocks.
			wire := dagWire(t, base, keys, index%6, transactions)
			record, err := decodeDagBlock(wire, base.Source, 0)
			if err != nil || base.admit(record) != nil {
				t.Fatal("fixture chain", err)
			}
			wires = append(wires, wire)
		}
		batch := dagBatchWire(t, app.dag, wires...)
		if _, err := app.FinalizeBlock(ctx, &abci.RequestFinalizeBlock{Height: height, Time: time.Unix(1700000001+height, 0), Txs: [][]byte{batch}}); err != nil {
			t.Fatal(err)
		}
		if _, err := app.Commit(ctx, &abci.RequestCommit{}); err != nil {
			t.Fatal(err)
		}
	}
	for _, height := range []int64{1, 2} {
		state, _ := app.stateAt(height)
		_, _, _, validators := testGenesis()
		header, _ := cmtjson.Marshal(signedFixture(app.genesis, validators, height+1, state.StateRoot, nil, types.BlockID{}))
		seen := []DagOrderLeaf{}
		for start := 0; start < state.DAG.Blocks; start += DagOrderPageSize {
			response, _ := app.Query(ctx, &abci.RequestQuery{Path: "/gg/dag/order-page", Data: canonical(struct {
				Start int `json:"start"`
			}{start}), Height: height})
			var page DagOrderPage
			if response.Code != 0 || len(response.Value) > 65536 || decodeStrict(response.Value, &page) != nil || verifyDagOrderPage(page, state, *app.genesis.DAG) != nil {
				t.Fatal("historical page", height, start)
			}
			input := VerifyInput{Schema: "gg.consensus.proof.v1", Genesis: app.genesis, GenesisHash: app.anchor, State: state, SignedHeader: header, DAGOrderPage: &page}
			result, err := verifyInput(input)
			if err != nil || result["dag_order_page_verified"] != true || result["execution_status_verified"] != false {
				t.Fatal("SDK page", err)
			}
			for _, witness := range page.Items {
				seen = append(seen, witness.Leaf)
			}
		}
		if len(seen) != state.DAG.Blocks {
			t.Fatal("page omitted leaves")
		}
		for index, leaf := range seen {
			if leaf != orderFixture(t, app.dag)[index] {
				t.Fatal("canonical order changed")
			}
		}
	}
	for _, raw := range []string{`{}`, `{"start":1}`, `{"start":-1}`, `{"start":96}`, `{"start":0,"extra":1}`, `{"start":0.0}`, `{"start":0,"start":32}`} {
		response, _ := app.Query(ctx, &abci.RequestQuery{Path: "/gg/dag/order-page", Data: []byte(raw)})
		if response.Code == 0 {
			t.Fatal("bad cursor accepted", raw)
		}
	}
}

func TestDagOrderPageRejectsOmissionReorderingAndChangedCertifiedContext(t *testing.T) {
	input := dagCertifiedFixture(t)
	for _, mutation := range []string{"omit", "duplicate", "swap", "start", "complete", "nil", "index", "hash", "producer", "sequence", "transactions", "path", "root", "height", "genesis", "commitment"} {
		t.Run(mutation, func(t *testing.T) {
			var changed VerifyInput
			_ = json.Unmarshal(canonical(input), &changed)
			page := changed.DAGOrderPage
			switch mutation {
			case "omit":
				page.Items = page.Items[:len(page.Items)-1]
			case "duplicate":
				page.Items[1] = page.Items[0]
			case "swap":
				page.Items[0], page.Items[1] = page.Items[1], page.Items[0]
			case "start":
				page.Start = 32
			case "complete":
				page.Complete = false
			case "nil":
				page.Items = nil
			case "index":
				page.Items[0].Leaf.Index++
			case "hash":
				page.Items[0].Leaf.Hash = strings.Repeat("f", 64)
			case "producer":
				page.Items[0].Leaf.Producer = 6
			case "sequence":
				page.Items[0].Leaf.Sequence++
			case "transactions":
				page.Items[0].Leaf.Transactions++
			case "path":
				page.Items[0].Path = []PathItem{}
			case "root":
				page.StateRoot = strings.Repeat("f", 64)
			case "height":
				page.Height++
			case "genesis":
				page.GenesisHash = strings.Repeat("f", 64)
			case "commitment":
				page.Commitment.Transactions++
			}
			if _, err := verifyInput(changed); err == nil {
				t.Fatal("mutated page certified")
			}
		})
	}
}

func TestDagEmptyOrderAndZeroTransactionBlocksHaveConsistentCertificates(t *testing.T) {
	app, keys, _ := dagLedgerFixture(t)
	empty, err := dagOrderPageFor(app.dag, app.state, 0)
	if err != nil || !empty.Complete || len(empty.Items) != 0 || verifyDagOrderPage(empty, app.state, *app.genesis.DAG) != nil {
		t.Fatal("empty genesis page")
	}
	batch := dagBatchWire(t, app.dag, dagWire(t, app.dag, keys, 0, 0))
	_, err = app.FinalizeBlock(context.Background(), &abci.RequestFinalizeBlock{Height: 1, Time: time.Unix(1700000002, 0), Txs: [][]byte{batch}})
	if err != nil {
		t.Fatal(err)
	}
	if _, err = app.Commit(context.Background(), &abci.RequestCommit{}); err != nil {
		t.Fatal(err)
	}
	if app.state.DAG.Transactions != 0 || app.state.DAG.Blocks != 1 || validateState(app.state, app.genesis, app.anchor) != nil {
		t.Fatal("empty block changed TX count or invalid state")
	}
	page, err := dagOrderPageFor(app.dag, app.state, 0)
	if err != nil || verifyDagOrderPage(page, app.state, *app.genesis.DAG) != nil {
		t.Fatal("empty block membership")
	}
	_, _, _, validators := testGenesis()
	header, _ := cmtjson.Marshal(signedFixture(app.genesis, validators, 2, app.state.StateRoot, nil, types.BlockID{}))
	if _, err := verifyInput(VerifyInput{Schema: "gg.consensus.proof.v1", Genesis: app.genesis, GenesisHash: app.anchor, State: app.state, SignedHeader: header, DAGOrderPage: &page}); err != nil {
		t.Fatal(err)
	}
	if _, err := dagOrderPageFor(app.dag, app.state, 1); err == nil {
		t.Fatal("empty trailing page allowed")
	}
}

func TestDagOrderPageAtMaximumTreeFitsOwnedQueryBudget(t *testing.T) {
	base, keys := dagFixture(t)
	for index := 0; index < DagMaxRecords; index++ {
		wire := dagWire(t, base, keys, 0, 0)
		record, err := decodeDagBlock(wire, base.Source, 0)
		if err != nil || base.admit(record) != nil {
			t.Fatal("max-tree fixture", index, err)
		}
	}
	base.seal()
	state := State{GenesisHash: base.Anchor, Height: 1, StateRoot: strings.Repeat("a", 64), DAG: &base.Commitment}
	for _, start := range []int{0, 2048, 4064} {
		page, err := dagOrderPageFor(base, state, start)
		if err != nil || verifyDagOrderPage(page, state, base.Source) != nil || len(canonical(page)) > 65536 {
			t.Fatal("max-size page exceeds or fails its contract", start, err)
		}
	}
}
