//go:build !js

package main

import (
	"bytes"
	"context"
	"errors"
	"strings"
	"testing"
)

func TestFinancialDecodedPaymentsRetainSignaturesWireContextAndOwnedValues(t *testing.T) {
	model, keys, _ := publicProtocolFixture(t)
	payer := keys[model.genesis.FinancialAccounts.Allocations[0].Address]
	recipient := publicFixtureAddress(publicFixtureKey("decoded owned recipient"))
	values := []Envelope{publicFixturePayment(model, payer, recipient, 0, "7")}
	inputs, decoded, err := prepareFinancialDecodedPayments(values)
	if err != nil {
		t.Fatal(err)
	}
	original := append([]byte(nil), inputs[0]...)
	*values[0].Body.MaxFee = "0"
	values[0].Signature = strings.Repeat("0", 128)
	values[0].Body.Nonce = 999
	first, err := financialEnvelopesWithDecoded(context.Background(), inputs, model.genesis, model.anchor, decoded)
	if err != nil || len(first) != 1 || *first[0].Body.MaxFee != "100000" || !bytes.Equal(original, inputs[0]) {
		t.Fatal("decoded binding aliases source values or lost exact signature/context", err)
	}
	*first[0].Body.MaxFee = "1"
	if _, err = financialEnvelopesWithDecoded(context.Background(), inputs, model.genesis, model.anchor, decoded); err != nil {
		t.Fatal("returned MaxFee aliases private binding", err)
	}
	for _, raw := range [][]byte{append([]byte(" "), original...), append(append([]byte(nil), original...), '\n'), []byte(`{"body":null}`)} {
		if _, err = financialEnvelopesWithDecoded(context.Background(), [][]byte{raw}, model.genesis, model.anchor, decoded); err == nil {
			t.Fatal("changed/noncanonical raw bytes reused a decoded binding")
		}
	}
	if _, err = financialEnvelopesWithDecoded(context.Background(), nil, model.genesis, model.anchor, decoded); err == nil {
		t.Fatal("decoded count mismatch accepted")
	}
	if _, err = financialEnvelopesWithDecoded(context.Background(), inputs, model.genesis, strings.Repeat("e", 64), decoded); err == nil {
		t.Fatal("decoded binding bypassed current genesis anchor")
	}
	wrong := publicFixturePayment(model, payer, recipient, 0, "7")
	wrong.Signature = strings.Repeat("0", 128)
	bad, badDecoded, err := prepareFinancialDecodedPayments([]Envelope{wrong})
	if err != nil {
		t.Fatal(err)
	}
	if _, err = financialEnvelopesWithDecoded(context.Background(), bad, model.genesis, model.anchor, badDecoded); err == nil {
		t.Fatal("decoded representation was mistaken for a signature result")
	}
	cancelled, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err = financialEnvelopesWithDecoded(cancelled, inputs, model.genesis, model.anchor, decoded); !errors.Is(err, context.Canceled) {
		t.Fatal("decoded verification bypassed cancellation", err)
	}
}

func TestFinancialDecodedAndRawPaymentExecutionHaveExactOutcomesAndNodes(t *testing.T) {
	model, keys, _ := publicProtocolFixture(t)
	payer := keys[model.genesis.FinancialAccounts.Allocations[0].Address]
	values := make([]Envelope, 513)
	for index := range values {
		recipient := publicFixtureAddress(publicFixtureKey("decoded differential recipient " + string(rune(index+1024))))
		values[index] = publicFixturePayment(model, payer, recipient, uint64(index), "7")
	}
	// Authentic nonce conflicts remain receipts, not failed cryptographic input.
	values[257] = publicFixturePayment(model, payer, values[257].Body.Recipient, 0, "7")
	inputs, decoded, err := prepareFinancialDecodedPayments(values)
	if err != nil {
		t.Fatal(err)
	}
	binding := financialTestContext(model.anchor)
	rawResult, err := executeFinancialMoney(context.Background(), model.genesis, model.anchor, model.money, binding, inputs)
	if err != nil {
		t.Fatal(err)
	}
	decodedResult, err := executeFinancialMoneyWithDecoded(context.Background(), model.genesis, model.anchor, model.money, binding, inputs, decoded)
	if err != nil || !bytes.Equal(canonical(rawResult.Summary), canonical(decodedResult.Summary)) ||
		!bytes.Equal(canonical(rawResult.Receipts), canonical(decodedResult.Receipts)) ||
		!bytes.Equal(canonical(rawResult.Money.Protocol.state), canonical(decodedResult.Money.Protocol.state)) {
		t.Fatal("decoded path changed fees/order/nonce/conflicts/receipts/protocol state", err)
	}
	compareWorkspaceTrees(t, *rawResult.Money.Tree, *decodedResult.Money.Tree)
	if decodedResult.Summary.Rejected == 0 || decodedResult.Summary.Applied == 0 {
		t.Fatal("differential fixture missed applied and authentic conflicting transactions")
	}
	values[256].Signature = strings.Repeat("0", 128)
	bad, badDecoded, err := prepareFinancialDecodedPayments(values)
	if err != nil {
		t.Fatal(err)
	}
	before := model.money.AccountRoot
	if _, err = executeFinancialMoneyWithDecoded(context.Background(), model.genesis, model.anchor, model.money, binding, bad, badDecoded); err == nil || model.money.AccountRoot != before {
		t.Fatal("one bad signature did not reject whole input without changing base")
	}
}
