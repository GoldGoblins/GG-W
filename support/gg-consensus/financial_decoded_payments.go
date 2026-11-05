package main

// A private binding between owned decoded values and their canonical wire.
// It establishes neither signature validity nor any state-dependent outcome.
// Each use rechecks exact wire binding AND the ordinary context/signature.
import (
	"crypto/sha256"
	"errors"
)

type financialDecodedPayment struct {
	value     Envelope
	wireHash  [32]byte
	wireBytes int
}

type financialDecodedPayments struct {
	values []financialDecodedPayment
}

func ownedFinancialEnvelope(value Envelope) Envelope {
	if value.Body.MaxFee != nil {
		fee := *value.Body.MaxFee
		value.Body.MaxFee = &fee
	}
	return value
}

func prepareFinancialDecodedPayments(values []Envelope) ([][]byte, *financialDecodedPayments, error) {
	if len(values) > financialMaxTransactions {
		return nil, nil, errors.New("GG_FINANCIAL_BATCH_LIMIT")
	}
	inputs := make([][]byte, len(values))
	decoded := &financialDecodedPayments{values: make([]financialDecodedPayment, len(values))}
	remaining := financialMaxInputBytes
	for index, value := range values {
		value = ownedFinancialEnvelope(value)
		raw := canonical(value)
		if len(raw) == 0 || len(raw) > MaxTxBytes || len(raw) > remaining {
			return nil, nil, errors.New("GG_FINANCIAL_BATCH_LIMIT")
		}
		remaining -= len(raw)
		inputs[index] = raw
		decoded.values[index] = financialDecodedPayment{value: value, wireHash: sha256.Sum256(raw), wireBytes: len(raw)}
	}
	return inputs, decoded, nil
}

func (decoded *financialDecodedPayments) envelope(index int, raw []byte) (Envelope, error) {
	if decoded == nil || index < 0 || index >= len(decoded.values) {
		return Envelope{}, errors.New("GG_FINANCIAL_BATCH_INVALID_TRANSACTION")
	}
	value := decoded.values[index]
	if len(raw) != value.wireBytes || sha256.Sum256(raw) != value.wireHash {
		return Envelope{}, errors.New("GG_FINANCIAL_BATCH_INVALID_TRANSACTION")
	}
	// A consumer cannot mutate the binding's private MaxFee through a returned
	// pointer. Strings and all other Body fields are immutable values.
	return ownedFinancialEnvelope(value.value), nil
}
