package main

import (
	"bytes"
	"math"
	"math/rand"
	"strconv"
	"testing"
)

func TestDeterministicTransfersConserveSupplyAndReplayNeverMutatesState(t *testing.T) {
	genesis, anchor, keys, _ := testGenesis()
	state := initialState(genesis, anchor)
	random := rand.New(rand.NewSource(20261031)) // public reproducible input schedule
	for iteration := 0; iteration < 2000; iteration++ {
		source := random.Intn(4)
		target := (source + 1 + random.Intn(3)) % 4
		var nonce uint64
		for _, account := range state.Accounts {
			if account.Address == genesis.Accounts[source] {
				nonce = account.Nonce
			}
		}
		amount := strconv.FormatUint(uint64(random.Int63n(int64(Supply)))+1, 10)
		raw := testTx(genesis, anchor, keys, source, target, amount, nonce)
		envelope, err := parseEnvelope(raw, genesis, anchor)
		if err != nil {
			t.Fatal(err)
		}
		before := canonical(state)
		if err := applyEnvelope(&state, envelope, false); err != nil {
			if !bytes.Equal(before, canonical(state)) {
				t.Fatal("rejected transfer changed committed state")
			}
		} else {
			accepted := canonical(state)
			if applyEnvelope(&state, envelope, false) == nil || !bytes.Equal(accepted, canonical(state)) {
				t.Fatal("nonce replay changed state")
			}
		}
		sealState(&state)
		if validateState(state, genesis, anchor) != nil {
			t.Fatal("supply,nonce or state commitment invariant failed")
		}
	}
}

func TestAmountBoundariesAndExhaustedNonceFailWithoutPartialMutation(t *testing.T) {
	genesis, anchor, keys, _ := testGenesis()
	for _, amount := range []string{"0", "-1", "01", "1.0", "1e3", "+1", "18446744073709551616", strconv.FormatUint(Supply+1, 10)} {
		if _, err := parseEnvelope(testTx(genesis, anchor, keys, 0, 1, amount, 0), genesis, anchor); err == nil {
			t.Fatal("invalid atomic amount accepted")
		}
	}
	state := initialState(genesis, anchor)
	for i := range state.Accounts {
		if state.Accounts[i].Address == genesis.Accounts[0] {
			state.Accounts[i].Nonce = math.MaxUint64
		}
	}
	envelope, err := parseEnvelope(testTx(genesis, anchor, keys, 0, 1, "1", math.MaxUint64), genesis, anchor)
	if err != nil {
		t.Fatal(err)
	}
	before := canonical(state)
	if applyEnvelope(&state, envelope, false) == nil || !bytes.Equal(before, canonical(state)) {
		t.Fatal("nonce overflow wrapped or changed balances")
	}
}
