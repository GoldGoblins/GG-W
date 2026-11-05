package main

// Public payment v2 preserves the full uint64 nonce through JavaScript/JSON.
// Legacy v1 keeps its original numeric nonce and exact canonical wire bytes.
import (
	"bytes"
	"encoding/json"
	"errors"
	"strconv"
)

func (body Body) MarshalJSON() ([]byte, error) {
	if body.Version != 2 {
		type legacyBody Body
		return json.Marshal(legacyBody(body))
	}
	type publicBody struct {
		Amount      string  `json:"amount_atomic"`
		ChainID     string  `json:"chain_id"`
		GenesisHash string  `json:"genesis_hash"`
		MaxFee      *string `json:"max_fee_atomic,omitempty"`
		Nonce       string  `json:"nonce"`
		Recipient   string  `json:"recipient"`
		Sender      string  `json:"sender"`
		Version     int     `json:"version"`
	}
	return json.Marshal(publicBody{Amount: body.Amount, ChainID: body.ChainID, GenesisHash: body.GenesisHash, MaxFee: body.MaxFee,
		Nonce: strconv.FormatUint(body.Nonce, 10), Recipient: body.Recipient, Sender: body.Sender, Version: body.Version})
}

func (body *Body) UnmarshalJSON(raw []byte) error {
	type wireBody struct {
		Amount      string          `json:"amount_atomic"`
		ChainID     string          `json:"chain_id"`
		GenesisHash string          `json:"genesis_hash"`
		MaxFee      *string         `json:"max_fee_atomic,omitempty"`
		Nonce       json.RawMessage `json:"nonce"`
		Recipient   string          `json:"recipient"`
		Sender      string          `json:"sender"`
		Version     int             `json:"version"`
	}
	var value wireBody
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&value); err != nil {
		return err
	}
	nonce := uint64(0)
	if value.Version == 2 {
		var text string
		if json.Unmarshal(value.Nonce, &text) != nil {
			return errors.New("GG_TX_NONCE_ENCODING")
		}
		parsed, ok := economicAmount(text)
		if !ok {
			return errors.New("GG_TX_NONCE_ENCODING")
		}
		nonce = parsed
	} else if len(value.Nonce) > 0 {
		if json.Unmarshal(value.Nonce, &nonce) != nil {
			return errors.New("GG_TX_NONCE_ENCODING")
		}
	}
	*body = Body{Amount: value.Amount, ChainID: value.ChainID, GenesisHash: value.GenesisHash, MaxFee: value.MaxFee, Nonce: nonce,
		Recipient: value.Recipient, Sender: value.Sender, Version: value.Version}
	return nil
}
