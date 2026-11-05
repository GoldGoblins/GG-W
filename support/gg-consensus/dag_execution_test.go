package main

import (
	"bytes"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"os"
	"sort"
	"strconv"
	"strings"
	"testing"
)

func dagFixture(t *testing.T) (*DagExecution, []ed25519.PrivateKey) {
	t.Helper()
	keys := make([]ed25519.PrivateKey, 6)
	public := make([]string, 6)
	for i := range keys {
		seed := sha256.Sum256([]byte("public-dag-execution-fixture-" + strconv.Itoa(i)))
		keys[i] = ed25519.NewKeyFromSeed(seed[:])
		public[i] = hex.EncodeToString(keys[i].Public().(ed25519.PublicKey))
	}
	accounts := append([]string(nil), public...)
	sort.Strings(accounts)
	source := DagSource{Accounts: accounts, AllowedProducers: []int{0, 1, 2, 3, 4, 5}, NetworkID: strings.Repeat("b", 64), Schema: "gg.dag.consensus.source.v1", SignatureProfile: TransactionSignatureProfile, StartedAtNs: "1700000000000000000"}
	source.Genesis = DagGenesis{AccountCount: 6, Allocation: "1000000000", ChainID: "ggdag:" + strings.Repeat("a", 24), Producers: public, Schema: "gg.parallel-dag.genesis.v2", TestMode: "PRODUCER_OWNED_NONFINANCIAL"}
	source.Genesis.PrecheckRoot = dagRoot(dagInitialAccounts(source), "GG-DAG-ACCOUNT-v1\x00")
	source.GenesisHash = dagDigest("GG-DAG-DATA-v1\x00", source.Genesis)
	execution, err := newDagExecution(source, strings.Repeat("c", 64))
	if err != nil {
		t.Fatal(err)
	}
	return execution, keys
}

func dagWire(t *testing.T, base *DagExecution, keys []ed25519.PrivateKey, producer, count int) []byte {
	t.Helper()
	parents := []string{base.Source.GenesisHash}
	rank := int64(1)
	if base.heads[producer] != "" {
		parents = []string{base.heads[producer]}
		rank = rankFixture(t, base, parents[0]) + 1
	}
	txs := []DagTx{}
	for i := 0; i < count; i++ {
		body := DagTxBody{Amount: "1", ChainID: base.Source.Genesis.ChainID, From: base.Source.Genesis.Producers[producer], Nonce: base.nonces[producer] + uint64(i), PrecheckRoot: base.Source.Genesis.PrecheckRoot, Schema: "gg.parallel-dag.tx.v2", To: base.Source.Genesis.Producers[(producer+1)%6]}
		txs = append(txs, DagTx{Body: body, Signature: hex.EncodeToString(ed25519.Sign(keys[producer], append([]byte("GG-DAG-LAN-TEST-TX-SIGN-v2\x00"), canonical(body)...)))})
	}
	body := DagBlockBody{ChainID: base.Source.Genesis.ChainID, CreatedAtNs: 1700000001000000000, Parents: parents, PayloadRoot: dagRoot(txs, "GG-DAG-PAYLOAD-v1\x00"), PrecheckRoot: base.Source.Genesis.PrecheckRoot, Producer: producer, Rank: rank, Schema: "gg.parallel-dag.block.v1", Sequence: base.sequences[producer] + 1, Transactions: txs}
	return canonical(DagBlock{Body: body, Signature: hex.EncodeToString(ed25519.Sign(keys[producer], append([]byte("GG-DAG-PROPOSAL-SIGN-v1\x00"), canonical(body)...)))})
}

func dagBatchWire(t *testing.T, base *DagExecution, wires ...[]byte) []byte {
	t.Helper()
	sort.Slice(wires, func(i, j int) bool {
		a, err := decodeDagBlock(wires[i], base.Source, 0)
		if err != nil {
			t.Fatal(err)
		}
		b, err := decodeDagBlock(wires[j], base.Source, 0)
		if err != nil {
			t.Fatal(err)
		}
		if a.Block.Body.Rank != b.Block.Body.Rank {
			return a.Block.Body.Rank < b.Block.Body.Rank
		}
		return a.Hash < b.Hash
	})
	encoded := []string{}
	for _, wire := range wires {
		encoded = append(encoded, base64.StdEncoding.EncodeToString(wire))
	}
	return canonical(DagBatch{Blocks: encoded, GenesisHash: base.Anchor, Previous: base.Commitment.ManifestHash, Schema: "gg.dag.checkpoint.batch.v1", Sequence: base.Manifest.Checkpoint + 1})
}

func TestDagBatchValidatesEverySignatureAndPreservesSupplyAndAtomicPrefix(t *testing.T) {
	base, keys := dagFixture(t)
	first := dagWire(t, base, keys, 0, 3)
	second := dagWire(t, base, keys, 2, 2)
	batch := dagBatchWire(t, base, first, second)
	next, err := applyDagBatch(base, batch, 1700000002000000000)
	if err != nil {
		t.Fatal(err)
	}
	if next.Commitment.Blocks != 2 || next.Commitment.Transactions != 5 || base.Commitment.Blocks != 0 || base.orderCount() != 0 {
		t.Fatal("incorrect committed prefix")
	}
	total := uint64(0)
	for _, account := range next.Accounts {
		n, _ := strconv.ParseUint(account.Balance, 10, 64)
		total += n
	}
	if total != 6*DagAllocation {
		t.Fatal("supply changed")
	}
	before := canonical(next.Commitment)
	if _, err = applyDagBatch(next, batch, 1700000003000000000); err == nil {
		t.Fatal("replayed batch accepted")
	}
	if !bytes.Equal(before, canonical(next.Commitment)) {
		t.Fatal("failed batch mutated execution")
	}
}

func TestDagBatchRejectsTamperedTransactionsRolesUnknownParentsAndSequenceReuse(t *testing.T) {
	for _, kind := range []string{"signature", "nonce", "parent", "role", "rank"} {
		t.Run(kind, func(t *testing.T) {
			base, keys := dagFixture(t)
			var block DagBlock
			_ = decodeStrict(dagWire(t, base, keys, 0, 2), &block)
			switch kind {
			case "signature":
				block.Body.Transactions[1].Signature = strings.Repeat("0", 128)
			case "nonce":
				block.Body.Transactions[1].Body.Nonce = 0
				block.Body.Transactions[1].Signature = hex.EncodeToString(ed25519.Sign(keys[0], append([]byte("GG-DAG-LAN-TEST-TX-SIGN-v2\x00"), canonical(block.Body.Transactions[1].Body)...)))
			case "parent":
				block.Body.Parents = []string{strings.Repeat("d", 64)}
			case "role":
				base.Source.AllowedProducers = []int{1, 2, 3}
			case "rank":
				block.Body.Rank = 2
			}
			block.Body.PayloadRoot = dagRoot(block.Body.Transactions, "GG-DAG-PAYLOAD-v1\x00")
			block.Signature = hex.EncodeToString(ed25519.Sign(keys[0], append([]byte("GG-DAG-PROPOSAL-SIGN-v1\x00"), canonical(block.Body)...)))
			wire := canonical(block)
			encoded := base64.StdEncoding.EncodeToString(wire)
			batch := canonical(DagBatch{Blocks: []string{encoded}, GenesisHash: base.Anchor, Previous: base.Commitment.ManifestHash, Schema: "gg.dag.checkpoint.batch.v1", Sequence: 1})
			if _, err := applyDagBatch(base, batch, 1700000002000000000); err == nil {
				t.Fatal("invalid batch accepted")
			}
			if base.Commitment.Blocks != 0 || base.Accounts[0].Nonce != 0 {
				t.Fatal("invalid batch changed committed state")
			}
		})
	}
}

func TestDagManifestStoresOnlyCurrentDeltaAndLinksAnImmutablePriorCheckpoint(t *testing.T) {
	base, keys := dagFixture(t)
	a, err := applyDagBatch(base, dagBatchWire(t, base, dagWire(t, base, keys, 0, 1)), 1700000002000000000)
	if err != nil {
		t.Fatal(err)
	}
	b, err := applyDagBatch(a, dagBatchWire(t, a, dagWire(t, a, keys, 0, 2)), 1700000003000000000)
	if err != nil {
		t.Fatal(err)
	}
	if len(b.Manifest.Blocks) != 1 || b.orderCount() != 2 || b.Manifest.Previous != a.Commitment.ManifestHash || b.Manifest.Checkpoint != 2 || b.Commitment.Transactions != 3 {
		t.Fatal("manifest delta or checkpoint link invalid")
	}
	if a.orderCount() != 1 || a.Commitment.Transactions != 1 {
		t.Fatal("later checkpoint changed old state")
	}
}

func TestDagBftProposalTimeIsDeterministicAndMempoolValidationIsNotCertifiable(t *testing.T) {
	base, keys := dagFixture(t)
	batch := dagBatchWire(t, base, dagWire(t, base, keys, 0, 1))
	preview, err := applyDagBatch(base, batch, 0)
	if err != nil || preview.Manifest.TimeNs != "0" {
		t.Fatal("mempool admissibility failed")
	}
	if _, err = applyDagBatch(base, batch, 1700000000000000000-5000000000); err == nil {
		t.Fatal("future DAG timestamp accepted")
	}
	a, err := applyDagBatch(base, batch, 1700000002000000000)
	if err != nil {
		t.Fatal(err)
	}
	b, err := applyDagBatch(base, batch, 1700000002000000000)
	if err != nil || !bytes.Equal(canonical(a.Commitment), canonical(b.Commitment)) {
		t.Fatal("execution depended on local clock")
	}
}

func TestDagPythonProtocolFixture(t *testing.T) {
	path := os.Getenv("GG_PUBLIC_DAG_CORE_FIXTURE")
	if path == "" {
		t.Skip("Run the public Python/Go DAG fixture harness for cross-runtime coverage")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var fixture struct {
		Source       DagSource       `json:"source"`
		Anchor       string          `json:"anchor"`
		Batch        json.RawMessage `json:"batch"`
		TimeNs       string          `json:"time_ns"`
		Accounts     []Account       `json:"accounts"`
		Transactions uint64          `json:"transactions"`
	}
	if decodeStrict(raw, &fixture) != nil {
		t.Fatal("invalid public Python fixture")
	}
	base, err := newDagExecution(fixture.Source, fixture.Anchor)
	if err != nil {
		t.Fatal(err)
	}
	now, ok := dagDecimalNs(fixture.TimeNs)
	if !ok {
		t.Fatal("invalid public fixture time")
	}
	next, err := applyDagBatch(base, fixture.Batch, now)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(canonical(next.Accounts), canonical(fixture.Accounts)) || next.Commitment.Transactions != fixture.Transactions {
		t.Fatal("Python/Go DAG execution differs")
	}
}
