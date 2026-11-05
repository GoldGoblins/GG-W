package main

import (
	"bytes"
	"crypto/ed25519"
	"encoding/hex"
	"errors"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

// Independent former sequential admission/fold. Keep this oracle separate
// from the new scheduler/preflight so acceptance and state can be compared.
func formerDagTransactionFold(execution *DagExecution, producer int, transactions []DagTx) error {
	sender := execution.Source.Genesis.Producers[producer]
	index := sort.SearchStrings(execution.Source.Accounts, sender)
	for _, transaction := range transactions {
		tx := transaction.Body
		target := sort.SearchStrings(execution.Source.Accounts, tx.To)
		if tx.Schema != "gg.parallel-dag.tx.v2" || tx.ChainID != execution.Source.Genesis.ChainID || tx.PrecheckRoot != execution.Source.Genesis.PrecheckRoot ||
			tx.From != sender || target >= len(execution.Accounts) || execution.Accounts[target].Address != tx.To || tx.To == sender ||
			tx.Amount != "1" || tx.Nonce != execution.nonces[producer] || tx.Nonce >= DagAllocation {
			return errors.New("rules")
		}
		signature, err := hex.DecodeString(transaction.Signature)
		public, _ := hex.DecodeString(sender)
		if err != nil || len(transaction.Signature) != 128 || hex.EncodeToString(signature) != transaction.Signature ||
			!verifyTransactionSignature(public, append([]byte("GG-DAG-LAN-TEST-TX-SIGN-v2\x00"), canonical(tx)...), signature) {
			return errors.New("signature")
		}
		balance, _ := strconv.ParseUint(execution.Accounts[index].Balance, 10, 64)
		recipient, _ := strconv.ParseUint(execution.Accounts[target].Balance, 10, 64)
		if balance == 0 || recipient >= 6*DagAllocation {
			return errors.New("balance")
		}
		execution.Accounts[index].Balance = strconv.FormatUint(balance-1, 10)
		execution.Accounts[index].Nonce++
		execution.Accounts[target].Balance = strconv.FormatUint(recipient+1, 10)
		execution.nonces[producer]++
	}
	return nil
}

func txSignatureFixture(t *testing.T, count int) (*DagExecution, []ed25519.PrivateKey, dagRecord) {
	t.Helper()
	base, keys := dagFixture(t)
	record, err := decodeDagBlock(dagWire(t, base, keys, 0, count), base.Source, 0)
	if err != nil {
		t.Fatal(err)
	}
	return base, keys, record
}

func TestDagTxSignatureWorkerSelectionBoundsCPUAndSmallBlocks(t *testing.T) {
	for _, count := range []int{0, 1, 255, 256, 5000, DagMaxBlockTransactions} {
		for _, budget := range []int{-1, 0, 1, 2, 3, 8, 128} {
			expected := budget
			if count < 256 || budget < 2 {
				expected = 1
			} else if expected > 8 {
				expected = 8
			}
			if got := dagTxSignatureWorkers(count, budget); got != expected {
				t.Fatal("worker bound", count, budget, got, expected)
			}
		}
	}
}

func TestDagTxSignatureWorkersActuallyVerifyEachSignatureOnEveryCall(t *testing.T) {
	base, _, record := txSignatureFixture(t, 513)
	public, _ := hex.DecodeString(base.Source.Genesis.Producers[0])
	for _, workers := range []int{-1, 1, 2, 8, 128} {
		t.Run(strconv.Itoa(workers), func(t *testing.T) {
			var calls atomic.Int64
			verify := func(public, message, signature []byte) bool {
				calls.Add(1)
				return verifyTransactionSignature(public, message, signature)
			}
			for repeat := 1; repeat <= 2; repeat++ {
				if !verifyDagTransactionSignaturesUsing(public, record.Block.Body.Transactions, workers, verify) || calls.Load() != int64(repeat*513) {
					t.Fatal("skipped, repeated or cached cryptographic work", calls.Load())
				}
			}
		})
	}
}

func TestDagTxSignatureWorkersRejectEveryMutationAtFirstMiddleAndLast(t *testing.T) {
	base, keys, record := txSignatureFixture(t, 257)
	public, _ := hex.DecodeString(base.Source.Genesis.Producers[0])
	for _, position := range []int{0, 128, 256} {
		for _, kind := range []string{"zero", "short", "long", "uppercase", "hex", "message", "other-author", "other-domain", "identity-R", "noncanonical-S"} {
			t.Run(strconv.Itoa(position)+"/"+kind, func(t *testing.T) {
				txs := append([]DagTx(nil), record.Block.Body.Transactions...)
				tx := &txs[position]
				switch kind {
				case "zero":
					tx.Signature = strings.Repeat("0", 128)
				case "short":
					tx.Signature = tx.Signature[:126]
				case "long":
					tx.Signature += "00"
				case "uppercase":
					tx.Signature = strings.ToUpper(tx.Signature)
				case "hex":
					tx.Signature = "zz" + tx.Signature[2:]
				case "message":
					tx.Body.Amount = "2"
				case "other-author":
					tx.Signature = hex.EncodeToString(ed25519.Sign(keys[1], append([]byte("GG-DAG-LAN-TEST-TX-SIGN-v2\x00"), canonical(tx.Body)...)))
				case "other-domain":
					tx.Signature = hex.EncodeToString(ed25519.Sign(keys[0], append([]byte("GG-DAG-PROPOSAL-SIGN-v1\x00"), canonical(tx.Body)...)))
				case "identity-R":
					tx.Signature = "01" + strings.Repeat("00", 31) + tx.Signature[64:]
				case "noncanonical-S":
					tx.Signature = tx.Signature[:64] + strings.Repeat("ff", 32)
				}
				for _, workers := range []int{1, 2, 8} {
					if verifyDagTransactionSignaturesUsing(public, txs, workers, verifyTransactionSignature) {
						t.Fatal("invalid transaction admitted", workers)
					}
				}
			})
		}
	}
}

func TestDagTxSignatureWorkersStopAndJoinAllInFlightWork(t *testing.T) {
	base, _, record := txSignatureFixture(t, 513)
	public, _ := hex.DecodeString(base.Source.Genesis.Producers[0])
	txs := record.Block.Body.Transactions
	txs[0].Signature = strings.Repeat("0", 128)
	entered := make(chan struct{}, 8)
	releaseBad := make(chan struct{})
	releaseOthers := make(chan struct{})
	badChecked := make(chan struct{})
	var active, calls, atReturn atomic.Int64
	finished := make(chan bool, 1)
	go func() {
		accepted := verifyDagTransactionSignaturesUsing(public, txs, 1000, func(public, message, signature []byte) bool {
			active.Add(1)
			defer active.Add(-1)
			calls.Add(1)
			select {
			case entered <- struct{}{}:
			default:
			}
			if bytes.Equal(signature, make([]byte, 64)) {
				<-releaseBad
				valid := verifyTransactionSignature(public, message, signature)
				close(badChecked)
				return valid
			}
			<-releaseOthers
			return verifyTransactionSignature(public, message, signature)
		})
		atReturn.Store(active.Load())
		finished <- accepted
	}()
	// Release all test barriers even if an assertion fails.
	defer func() {
		select {
		case <-releaseBad:
		default:
			close(releaseBad)
		}
		select {
		case <-releaseOthers:
		default:
			close(releaseOthers)
		}
	}()
	deadline := time.After(5 * time.Second)
	for i := 0; i < 8; i++ {
		select {
		case <-entered:
		case <-deadline:
			t.Fatal("bounded workers did not reach barrier")
		}
	}
	if active.Load() != 8 || calls.Load() != 8 {
		t.Fatal("worker cap exceeded", active.Load(), calls.Load())
	}
	close(releaseBad)
	select {
	case <-badChecked:
	case <-deadline:
		t.Fatal("actual invalid signature not checked")
	}
	select {
	case <-finished:
		t.Fatal("returned before outstanding signature work joined")
	default:
	}
	close(releaseOthers)
	select {
	case accepted := <-finished:
		if accepted || active.Load() != 0 || atReturn.Load() != 0 || calls.Load() > int64(len(txs)) {
			t.Fatal("failed batch leaked or duplicated work", accepted, active.Load(), calls.Load())
		}
	case <-deadline:
		t.Fatal("workers did not join")
	}
}

func TestDagTxSignatureEarlyFailureStopsWithoutDependingOnSchedulerTiming(t *testing.T) {
	base, _, record := txSignatureFixture(t, 513)
	public, _ := hex.DecodeString(base.Source.Genesis.Producers[0])
	txs := append([]DagTx(nil), record.Block.Body.Transactions...)
	for _, position := range []int{0, 128, 512} {
		original := txs[position]
		txs[position].Signature = strings.Repeat("0", 128)
		calls := 0
		if verifyDagTransactionSignaturesUsing(public, txs, 1, func(public, message, signature []byte) bool {
			calls++
			return verifyTransactionSignature(public, message, signature)
		}) || calls != position+1 {
			t.Fatal("sequential failure did not stop at the actual invalid signature", position, calls)
		}
		txs[position] = original
	}
	// Every possible initially claimed job is malformed. No worker can claim a
	// later job before publishing failure, regardless of callback scheduling.
	for i := 0; i < dagTxSignatureWorkerLimit; i++ {
		txs[i].Signature = "00"
	}
	var calls atomic.Int64
	if verifyDagTransactionSignaturesUsing(public, txs, 1000, func(public, message, signature []byte) bool {
		calls.Add(1)
		return verifyTransactionSignature(public, message, signature)
	}) || calls.Load() != 0 {
		t.Fatal("malformed initial jobs did not stop the bounded pool", calls.Load())
	}
}

func TestDagTxSignatureSchedulerEmptyAndOversizedInputsDoNoCrypto(t *testing.T) {
	verify := func(_, _, _ []byte) bool { t.Fatal("unexpected cryptographic call"); return false }
	if !verifyDagTransactionSignaturesUsing(nil, nil, 100, verify) ||
		verifyDagTransactionSignaturesUsing(nil, make([]DagTx, DagMaxBlockTransactions+1), 100, verify) {
		t.Fatal("empty/maximum transaction boundary changed")
	}
}

func TestDagTxParallelAdmissionMatchesFormerFoldAcrossCPUBudgets(t *testing.T) {
	previousBudget := runtime.GOMAXPROCS(0)
	defer runtime.GOMAXPROCS(previousBudget)
	for _, count := range []int{0, 1, 255, 256, 257, 5000} {
		t.Run(strconv.Itoa(count), func(t *testing.T) {
			base, _, record := txSignatureFixture(t, count)
			oracle := base.clone()
			if err := formerDagTransactionFold(oracle, 0, record.Block.Body.Transactions); err != nil {
				t.Fatal(err)
			}
			var commitment []byte
			for _, budget := range []int{1, 2, 8} {
				runtime.GOMAXPROCS(budget)
				next := base.clone()
				if err := next.admit(record); err != nil {
					t.Fatal(err)
				}
				next.seal()
				if !bytes.Equal(canonical(next.Accounts), canonical(oracle.Accounts)) || !bytes.Equal(canonical(next.nonces), canonical(oracle.nonces)) {
					t.Fatal("parallel schedule changed ordered state", budget)
				}
				if commitment != nil && !bytes.Equal(commitment, canonical(next.Commitment)) {
					t.Fatal("CPU budget changed commitment", budget)
				}
				commitment = canonical(next.Commitment)
			}
		})
	}
}

func TestDagTxPreflightAndFoldMatchFormerNegativeRulesAndRetainBase(t *testing.T) {
	for _, kind := range []string{"schema", "chain", "root", "sender", "recipient", "self", "amount", "nonce-first", "nonce-last", "allocation", "wrapped-nonce", "balance", "recipient-cap", "signature", "later-rule-and-earlier-signature"} {
		t.Run(kind, func(t *testing.T) {
			base, keys, record := txSignatureFixture(t, 257)
			body := &record.Block.Body
			last := &body.Transactions[256]
			sender := sort.SearchStrings(base.Source.Accounts, body.Transactions[0].Body.From)
			recipient := sort.SearchStrings(base.Source.Accounts, last.Body.To)
			switch kind {
			case "schema":
				last.Body.Schema += "x"
			case "chain":
				last.Body.ChainID += "x"
			case "root":
				last.Body.PrecheckRoot = DagZero
			case "sender":
				last.Body.From = last.Body.To
			case "recipient":
				last.Body.To = strings.Repeat("f", 64)
			case "self":
				last.Body.To = last.Body.From
			case "amount":
				last.Body.Amount = "0"
			case "nonce-first":
				body.Transactions[0].Body.Nonce++
			case "nonce-last":
				last.Body.Nonce--
			case "allocation":
				base.nonces[0] = DagAllocation - 256
				for i := range body.Transactions {
					body.Transactions[i].Body.Nonce = base.nonces[0] + uint64(i)
				}
			case "wrapped-nonce":
				base.nonces[0] = ^uint64(0)
			case "balance":
				base.Accounts[sender].Balance = "256"
			case "recipient-cap":
				base.Accounts[recipient].Balance = strconv.FormatUint(6*DagAllocation-256, 10)
			case "signature":
				last.Signature = strings.Repeat("0", 128)
			case "later-rule-and-earlier-signature":
				body.Transactions[0].Signature = strings.Repeat("0", 128)
				last.Body.Amount = "2"
			}
			if kind != "signature" && kind != "later-rule-and-earlier-signature" {
				for i := range body.Transactions {
					tx := &body.Transactions[i]
					tx.Signature = hex.EncodeToString(ed25519.Sign(keys[0], append([]byte("GG-DAG-LAN-TEST-TX-SIGN-v2\x00"), canonical(tx.Body)...)))
				}
			}
			oracle := base.clone()
			if formerDagTransactionFold(oracle, 0, body.Transactions) == nil {
				t.Fatal("former independent oracle unexpectedly accepted")
			}
			body.PayloadRoot = dagRoot(body.Transactions, "GG-DAG-PAYLOAD-v1\x00")
			record.Block.Signature = hex.EncodeToString(ed25519.Sign(keys[0], append([]byte("GG-DAG-PROPOSAL-SIGN-v1\x00"), canonical(*body)...)))
			beforeAccounts, beforeNonces := canonical(base.Accounts), canonical(base.nonces)
			batch := dagBatchWire(t, base, canonical(record.Block))
			if next, err := applyDagBatch(base, batch, 1700000002000000000); err == nil || next != nil ||
				!bytes.Equal(beforeAccounts, canonical(base.Accounts)) || !bytes.Equal(beforeNonces, canonical(base.nonces)) || base.orderCount() != 0 {
				t.Fatal("invalid batch accepted or changed retained base")
			}
		})
	}
}
