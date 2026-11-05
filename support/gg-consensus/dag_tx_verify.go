package main

// Schedule independent signatures only. The admission rules and ordered state
// transition remain in dag_execution.go; no verification result is cached.
import (
	"encoding/hex"
	"runtime"
	"sync"
	"sync/atomic"
)

const dagTxSignatureWorkerLimit = 8
const dagTxSignatureParallelMinimum = 256

// Zero is the legacy/LOW limit. Only validated local native startup may set
// a finite SERVER budget; it is never supplied by transactions or peers.
var dagTxSignatureSelectedBudget atomic.Int64

func dagTxSignatureWorkerMaximum() int {
	selected := dagTxSignatureSelectedBudget.Load()
	if selected == 0 {
		return dagTxSignatureWorkerLimit
	}
	return int(selected)
}

func dagTxSignatureWorkers(count, cpuBudget int) int {
	if count < dagTxSignatureParallelMinimum || cpuBudget < 2 {
		return 1
	}
	if cpuBudget > dagTxSignatureWorkerMaximum() {
		return dagTxSignatureWorkerMaximum()
	}
	return cpuBudget
}

func verifyDagTransactionSignatures(public []byte, transactions []DagTx) bool {
	return verifyDagTransactionSignaturesUsing(public, transactions,
		dagTxSignatureWorkers(len(transactions), runtime.GOMAXPROCS(0)), verifyTransactionSignature)
}

// Inputs are owned by the decoded candidate and immutable until all workers
// join. Each worker constructs one message/signature at a time. The injected
// verifier lets tests count actual strict cryptographic calls and in-flight
// work; production always supplies verifyTransactionSignature above.
func verifyDagTransactionSignaturesUsing(public []byte, transactions []DagTx, workers int, verify func([]byte, []byte, []byte) bool) bool {
	if len(transactions) > DagMaxBlockTransactions {
		return false
	}
	if len(transactions) == 0 {
		return true
	}
	if workers < 1 {
		workers = 1
	}
	if workers > dagTxSignatureWorkerMaximum() {
		workers = dagTxSignatureWorkerMaximum()
	}
	if workers > len(transactions) {
		workers = len(transactions)
	}
	check := func(index int) bool {
		transaction := &transactions[index]
		if len(transaction.Signature) != 128 {
			return false
		}
		signature, err := hex.DecodeString(transaction.Signature)
		return err == nil && hex.EncodeToString(signature) == transaction.Signature &&
			verify(public, append([]byte("GG-DAG-LAN-TEST-TX-SIGN-v2\x00"), canonical(transaction.Body)...), signature)
	}
	if workers == 1 {
		for i := range transactions {
			if !check(i) {
				return false
			}
		}
		return true
	}
	var next atomic.Int64
	var failed atomic.Bool
	var group sync.WaitGroup
	group.Add(workers)
	for i := 0; i < workers; i++ {
		go func() {
			defer group.Done()
			for !failed.Load() {
				index := int(next.Add(1) - 1)
				if index >= len(transactions) {
					return
				}
				if !check(index) {
					failed.Store(true)
					return
				}
			}
		}()
	}
	group.Wait()
	return !failed.Load()
}
