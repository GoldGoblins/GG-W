package main

// Execution-kernel evidence only. Prepared successors below are consumed by
// tests, not activated by a live SDK node or an unverified archive snapshot.
import (
	"crypto/ed25519"
	"encoding/base64"
	"encoding/hex"
	"reflect"
	"sort"
	"strconv"
	"testing"
)

func segmentedFixture(t *testing.T) (*dagSegmentedExecution, []ed25519.PrivateKey) {
	t.Helper()
	base, keys := dagFixture(t)
	g := base.Source.Genesis
	policy := currentDagExecutionPolicy()
	source := dagSegmentedSource{Accounts: base.Source.Accounts, AllowedProducers: base.Source.AllowedProducers,
		NetworkID: base.Source.NetworkID, Schema: "gg.dag.consensus.source.v2", SignatureProfile: TransactionSignatureProfile,
		StartedAtNs: base.Source.StartedAtNs,
		Genesis: dagSegmentedGenesis{AccountCount: g.AccountCount, Allocation: g.Allocation, ExecutionPolicy: &policy,
			HistoryPolicy: segmentedHistoryPolicy(), PrecheckRoot: g.PrecheckRoot, Producers: g.Producers,
			Schema: "gg.parallel-dag.genesis.v4", TestMode: g.TestMode}}
	source.Genesis.ChainID = source.chainID()
	source.GenesisHash = dagDigest("GG-DAG-DATA-v1\x00", source.Genesis)
	result, err := newDagSegmentedExecution(source, base.Anchor)
	if err != nil {
		t.Fatal(err)
	}
	return result, keys
}

func segmentedWire(t *testing.T, base *DagExecution, keys []ed25519.PrivateKey, producer, count int) []byte {
	t.Helper()
	parent := base.heads[producer]
	if parent == "" {
		parent = base.segmentParent
	}
	rank, known, err := base.historyRank(parent)
	if err != nil || !known {
		t.Fatal("fixture parent", err)
	}
	transactions := []DagTx{}
	for i := 0; i < count; i++ {
		body := DagTxBody{Amount: "1", ChainID: base.Source.Genesis.ChainID, From: base.Source.Genesis.Producers[producer],
			Nonce: base.nonces[producer] + uint64(i), PrecheckRoot: base.segmentPrecheck, Schema: "gg.parallel-dag.tx.v2",
			To: base.Source.Genesis.Producers[(producer+1)%6]}
		transactions = append(transactions, DagTx{Body: body, Signature: hex.EncodeToString(ed25519.Sign(keys[producer], append([]byte("GG-DAG-LAN-TEST-TX-SIGN-v2\x00"), canonical(body)...)))})
	}
	body := DagBlockBody{ChainID: base.Source.Genesis.ChainID, CreatedAtNs: 1700000001000000000, Parents: []string{parent},
		PayloadRoot: dagRoot(transactions, "GG-DAG-PAYLOAD-v1\x00"), PrecheckRoot: base.segmentPrecheck, Producer: producer,
		Rank: rank + 1, Schema: "gg.parallel-dag.block.v1", Sequence: base.sequences[producer] + 1, Transactions: transactions}
	return canonical(DagBlock{Body: body, Signature: hex.EncodeToString(ed25519.Sign(keys[producer], append([]byte("GG-DAG-PROPOSAL-SIGN-v1\x00"), canonical(body)...)))})
}

func segmentedBatch(t *testing.T, base *DagExecution, wires ...[]byte) []byte {
	t.Helper()
	sort.Slice(wires, func(i, j int) bool {
		a, e := decodeDagBlockContext(wires[i], base.Source, 0, base.segmentPrecheck, dagSegmentCounterMax, int64(dagSegmentCounterMax))
		if e != nil {
			t.Fatal(e)
		}
		b, e := decodeDagBlockContext(wires[j], base.Source, 0, base.segmentPrecheck, dagSegmentCounterMax, int64(dagSegmentCounterMax))
		if e != nil {
			t.Fatal(e)
		}
		if a.Block.Body.Rank != b.Block.Body.Rank {
			return a.Block.Body.Rank < b.Block.Body.Rank
		}
		return a.Hash < b.Hash
	})
	encoded := []string{}
	for _, raw := range wires {
		encoded = append(encoded, base64.StdEncoding.EncodeToString(raw))
	}
	return canonical(DagBatch{Blocks: encoded, GenesisHash: base.Anchor, Previous: base.Commitment.ManifestHash,
		Schema: "gg.dag.checkpoint.batch.v1", Sequence: base.Manifest.Checkpoint + 1})
}

func TestSegmentedHistoryRealSignedTXPreserveIdentityBalancesNonceAndSequenceAcrossCut(t *testing.T) {
	base, keys := segmentedFixture(t)
	firstWire := segmentedWire(t, base.active, keys, 0, 5000)
	first, err := base.apply(segmentedBatch(t, base.active, firstWire), 1700000002000000000)
	if err != nil {
		t.Fatal(err)
	}
	before, _ := first.state()
	plan, err := first.prepareCut()
	if err != nil || plan.matches(first) != nil {
		t.Fatal("cut", err)
	}
	if first.active.orderCount() != 1 || first.active.nonces[0] != 5000 {
		t.Fatal("preparation mutated old prefix")
	}
	next := plan.next
	if next.active.orderCount() != 0 || next.active.bytes != 0 || next.active.nonces[0] != 5000 || next.active.sequences[0] != 1 || !reflect.DeepEqual(first.active.Accounts, next.active.Accounts) {
		t.Fatal("carry changed owned state")
	}
	if _, known, _ := next.active.historyRank(first.source.GenesisHash); known {
		t.Fatal("old genesis remains a weak parent")
	}
	newWire := segmentedWire(t, next.active, keys, 0, 5000)
	finished, err := next.apply(segmentedBatch(t, next.active, newWire), 1700000003000000000)
	if err != nil {
		t.Fatal(err)
	}
	state, err := finished.state()
	if err != nil || state.Blocks != 2 || state.Transactions != 10000 || state.Authors[0].Nonce != "10000" || state.Authors[0].Sequence != "2" || state.Epoch != 2 || state.LastRank != 2 {
		t.Fatal("lost actual cumulative work", state, err)
	}
	if state.Authors[0].Key != before.Authors[0].Key || state.RawBytes != uint64(len(firstWire)+len(newWire)) {
		t.Fatal("ownership or byte total changed")
	}
	if state.Active.Blocks != 1 || state.LastCut != plan.hash || state.ClosedRoot == before.ClosedRoot {
		t.Fatal("unbound closed prefix")
	}
	if _, err = next.apply(segmentedBatchWithoutValidation(next.active, firstWire), 1700000003000000000); err == nil {
		t.Fatal("old segment wire replay accepted")
	}
	var bad DagBlock
	if decodeStrict(newWire, &bad) != nil {
		t.Fatal("fixture")
	}
	bad.Body.Transactions[0].Body.Nonce = 0
	bad.Body.Transactions[0].Signature = hex.EncodeToString(ed25519.Sign(keys[0], append([]byte("GG-DAG-LAN-TEST-TX-SIGN-v2\x00"), canonical(bad.Body.Transactions[0].Body)...)))
	bad.Body.PayloadRoot = dagRoot(bad.Body.Transactions, "GG-DAG-PAYLOAD-v1\x00")
	bad.Signature = hex.EncodeToString(ed25519.Sign(keys[0], append([]byte("GG-DAG-PROPOSAL-SIGN-v1\x00"), canonical(bad.Body)...)))
	if _, err = next.apply(segmentedBatchWithoutValidation(next.active, canonical(bad)), 1700000003000000000); err == nil {
		t.Fatal("spent nonce reused after cut")
	}
	after, _ := first.state()
	if after != before {
		t.Fatal("failed work changed old immutable prefix")
	}
	plan.body.Accounts[0].Balance = "0"
	if plan.matches(first) == nil {
		t.Fatal("caller-mutated cut remains valid")
	}
	if next.active.Accounts[0].Balance == "0" {
		t.Fatal("cut body aliased successor")
	}
}

func segmentedBatchWithoutValidation(base *DagExecution, raw []byte) []byte {
	return canonical(DagBatch{Blocks: []string{base64.StdEncoding.EncodeToString(raw)}, GenesisHash: base.Anchor,
		Previous: base.Commitment.ManifestHash, Schema: "gg.dag.checkpoint.batch.v1", Sequence: base.Manifest.Checkpoint + 1})
}

func TestSegmentedHistoryGoesBeyondLegacyGlobalBlockRankAndSequenceLimitWithBoundedSegments(t *testing.T) {
	state, keys := segmentedFixture(t)
	total := 0
	for total < 4097 {
		if state.active.orderCount() == 1024 {
			plan, err := state.prepareCut()
			if err != nil || plan.matches(state) != nil {
				t.Fatal(err)
			}
			state = plan.next
		}
		n := 128
		if 4097-total < n {
			n = 4097 - total
		}
		draft := state.active.clone()
		wires := make([][]byte, 0, n)
		for i := 0; i < n; i++ {
			raw := segmentedWire(t, draft, keys, 0, 0)
			record, err := decodeDagBlockContext(raw, draft.Source, 0, draft.segmentPrecheck, dagSegmentCounterMax, int64(dagSegmentCounterMax))
			if err != nil || draft.admit(record) != nil {
				t.Fatal("draft", err)
			}
			wires = append(wires, raw)
		}
		var err error
		state, err = state.apply(segmentedBatch(t, state.active, wires...), 1700000002000000000)
		if err != nil {
			t.Fatal(err)
		}
		total += n
		if state.active.orderCount() > 1024 {
			t.Fatal("unbounded active segment")
		}
	}
	value, err := state.state()
	if err != nil || value.Blocks != 4097 || value.Authors[0].Sequence != "4097" || value.LastRank != 4097 || value.Epoch != 5 || value.Transactions != 0 {
		t.Fatal(value, err)
	}
	// Actual cold lookup must use the new context; legacy readers keep old caps.
	bodies := map[string]dagHistoryBody{}
	if err = state.active.history.newNodes(map[string]bool{}, func(id string, body dagHistoryBody) error { bodies[id] = body; return nil }); err != nil {
		t.Fatal(err)
	}
	state.active.history.root = dagHistoryRef{hash: state.active.history.root.id()}
	state.active.history.read = func(id string) (dagHistoryBody, error) {
		body, ok := bodies[id]
		if !ok {
			return body, errDagHistoryUnavailable
		}
		return body, nil
	}
	if rank, known, err := state.active.historyRank(state.authorHeads[0]); err != nil || !known || rank != 4097 {
		t.Fatal("new cold metadata", rank, known, err)
	}
	legacy := state.active.history
	legacy.segmented = false
	if _, _, err = legacy.get("b/" + state.authorHeads[0]); err == nil {
		t.Fatal("legacy metadata range silently widened")
	}
}

func TestSegmentedHistorySourcePolicyBoundIntoGenesisAndLegacySDKStillRejects(t *testing.T) {
	base, _ := segmentedFixture(t)
	source := base.source
	if validateSegmentedSource(source) != nil {
		t.Fatal("valid source")
	}
	var legacy DagSource
	if decodeStrict(canonical(source), &legacy) == nil {
		t.Fatal("current live source decoder accepted unfinished policy")
	}
	if _, err := newDagExecution(base.active.Source, base.anchor); err == nil {
		t.Fatal("current SDK entry accepted source v2")
	}
	fields := reflect.ValueOf(&source.Genesis.HistoryPolicy).Elem()
	for i := 0; i < fields.NumField(); i++ {
		candidate := base.source
		values := reflect.ValueOf(&candidate.Genesis.HistoryPolicy).Elem()
		values.Field(i).SetString(values.Field(i).String() + "-other")
		candidate.Genesis.ChainID = candidate.chainID()
		candidate.GenesisHash = dagDigest("GG-DAG-DATA-v1\x00", candidate.Genesis)
		if validateSegmentedSource(candidate) == nil {
			t.Fatal("unsupported rehashed policy", fields.Type().Field(i).Name)
		}
	}
	detached, err := newDagSegmentedExecution(source, base.anchor)
	if err != nil {
		t.Fatal(err)
	}
	before, _ := detached.state()
	source.Genesis.ExecutionPolicy.BlockTransactions++
	source.Genesis.Producers[0] = source.Genesis.Producers[1]
	after, _ := detached.state()
	if after != before {
		t.Fatal("caller source alias changed owned state")
	}
}

func TestSegmentedHistoryClosedAccumulatorMatchesIndependentOddDuplicateRoot(t *testing.T) {
	tree := dagClosedSegments{}
	values := []string{}
	for i := 0; i < 1025; i++ {
		root, err := tree.root()
		if err != nil || root != dagRoot(values, dagClosedSegmentDomain) {
			t.Fatal("root", i, err)
		}
		value := hashHex([]byte("actual-cut-accumulator-case-" + strconv.Itoa(i)))
		old := tree
		if tree.append(value) != nil {
			t.Fatal("append")
		}
		values = append(values, value)
		if old.count+1 != tree.count {
			t.Fatal("clone count")
		}
	}
	tree.peaks[63] = "bad"
	if tree.append(hashHex([]byte("next"))) == nil {
		t.Fatal("corrupt frontier")
	}
}

func TestSegmentedHistoryCutRejectsEmptyMempoolAndInconsistentStoredCounters(t *testing.T) {
	base, keys := segmentedFixture(t)
	if _, err := base.prepareCut(); err == nil {
		t.Fatal("empty cut")
	}
	raw := segmentedWire(t, base.active, keys, 0, 1)
	mempool, err := base.apply(segmentedBatch(t, base.active, raw), 0)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = mempool.prepareCut(); err == nil {
		t.Fatal("mempool execution made a cut")
	}
	verified, err := base.apply(segmentedBatch(t, base.active, raw), 1700000002000000000)
	if err != nil {
		t.Fatal(err)
	}
	verified.active.bytes++
	if _, err = verified.prepareCut(); err == nil {
		t.Fatal("invented historical bytes")
	}
	verified.active.bytes--
	verified.active.nonces[0] = 0
	if _, err = verified.prepareCut(); err == nil {
		t.Fatal("nonce reset")
	}
}
