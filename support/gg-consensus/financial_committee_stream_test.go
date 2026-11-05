//go:build !js

package main

import (
	"bytes"
	"context"
	"encoding/binary"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	cmted "github.com/cometbft/cometbft/crypto/ed25519"
	cmtjson "github.com/cometbft/cometbft/libs/json"
	"github.com/cometbft/cometbft/types"
)

func committeeStreamInput(frames ...committeeVerifierFrame) []byte {
	var input bytes.Buffer
	for _, frame := range frames {
		input.Write(transportWire(canonical(frame)))
	}
	return input.Bytes()
}

func TestCommitteeResidentStreamPinsGenesisAndRejectsImportedAuthority(t *testing.T) {
	app, _, keys, _, _ := publicProtocolSDKFixture(t)
	commitFinancialSDK(t, app, nil)
	validators := make([]cmted.PrivKey, len(app.genesis.Validators))
	for index, public := range app.genesis.Validators {
		validators[index] = cmted.PrivKey(keys[public])
	}
	header := signedFixture(app.genesis, validators, app.state.Height+1, app.state.StateRoot, nil, types.BlockID{})
	rawHeader, err := cmtjson.Marshal(header)
	if err != nil {
		t.Fatal(err)
	}
	proof := VerifyInput{Schema: "gg.consensus.proof.v1", Genesis: app.genesis, GenesisHash: app.anchor, SignedHeader: rawHeader, State: copyState(app.state)}
	if _, err := verifyInput(proof); err != nil {
		t.Fatal("real pinned SDK fixture does not verify", err)
	}
	foreignPin, foreignPath, forgedHeader := proof, proof, proof
	foreignPin.GenesisHash = strings.Repeat("e", 64)
	foreignPath.CommitteeTrustPath = "/peer/cannot-select-trust-context"
	var mutated types.SignedHeader
	if cmtjson.Unmarshal(rawHeader, &mutated) != nil {
		t.Fatal("fixture header")
	}
	mutated.Commit.Signatures[0].Signature[0] ^= 1
	mutated.Commit.Signatures[1].Signature[0] ^= 1
	forgedHeader.SignedHeader, _ = cmtjson.Marshal(&mutated)
	frame := func(action string, proof *VerifyInput) committeeVerifierFrame {
		return committeeVerifierFrame{Action: action, Schema: "gg.native.committee-verifier-request.v1", Proof: proof}
	}
	init := committeeVerifierFrame{Action: "init", Schema: "gg.native.committee-verifier-request.v1", Genesis: &app.genesis, GenesisHash: app.anchor}
	badTransition := financialCommitteeTransition{Schema: "gg.financial.committee-transition-proof.v1", State: copyState(app.state), SignedHeader: rawHeader}
	transition := committeeVerifierFrame{Action: "transition", Schema: "gg.native.committee-verifier-request.v1", Transition: &badTransition}
	frames := []committeeVerifierFrame{frame("verify", &proof), init, init, frame("verify", &proof), frame("verify", &foreignPin), frame("verify", &foreignPath), frame("verify", &forgedHeader), transition, frame("verify", &proof)}
	var output bytes.Buffer
	if err := runCommitteeVerifyStream(bytes.NewReader(committeeStreamInput(frames...)), &output); err != nil {
		t.Fatal(err)
	}
	wanted := []bool{false, true, false, true, false, false, false, false, true}
	for index, ok := range wanted {
		raw, err := readProtocolTransportFrame(&output)
		var reply map[string]any
		if err != nil || decodeStrict(raw, &reply) != nil || reply["ok"] != ok {
			t.Fatalf("frame %d: expected ok=%v, got %s (%v)", index, ok, raw, err)
		}
		if index >= 1 && reply["epoch"] != "0" {
			t.Fatal("failed request advanced or reset committee trust")
		}
		if index == 3 || index == 8 {
			result, exists := reply["result"].(map[string]any)
			if !exists || result["verified"] != true {
				t.Fatal("resident verifier omitted independently checked SDK result")
			}
		} else if reply["result"] != nil {
			t.Fatal("rejected request exposed a verified result")
		}
	}
	if output.Len() != 0 {
		t.Fatal("unbound extra replies")
	}
}

func TestCommitteeStreamAndPublicJournalRejectTruncatedOrOversizedFrames(t *testing.T) {
	for _, raw := range [][]byte{{0, 0, 0, 0}, {0, 0, 0}, {0, 0, 0, 2, 'x'}, {0x7f, 0xff, 0xff, 0xff}} {
		if err := runCommitteeVerifyStream(bytes.NewReader(raw), &bytes.Buffer{}); err == nil {
			t.Fatal("malformed resident verifier framing accepted")
		}
	}
	model, _, _ := publicProtocolFixture(t)
	root := t.TempDir()
	path := filepath.Join(root, "committee-public-originals.bin")
	if err := os.WriteFile(path, []byte(financialCommitteeTrustMagic), 0600); err != nil {
		t.Fatal(err)
	}
	trust, err := readFinancialCommitteeTrust(context.Background(), path, model.genesis, model.anchor)
	if err != nil || trust.current.Epoch != 0 {
		t.Fatal("empty history did not reconstruct genesis trust", err)
	}
	var oversize [4]byte
	binary.BigEndian.PutUint32(oversize[:], 256*1024+1)
	for _, suffix := range [][]byte{{0}, {0, 0, 0, 0}, oversize[:], transportWire([]byte(`{"verified":true}`)), transportWire(canonical(financialCommitteeTransition{Schema: "gg.financial.committee-transition-proof.v1"}))} {
		if err := os.WriteFile(path, append([]byte(financialCommitteeTrustMagic), suffix...), 0600); err != nil {
			t.Fatal(err)
		}
		if _, err := readFinancialCommitteeTrust(context.Background(), path, model.genesis, model.anchor); err == nil {
			t.Fatal("corrupt or claimed-verified public history became trust")
		}
	}
	if err := os.WriteFile(path, append([]byte("FOREIGN!"), json.RawMessage(`{}`)...), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := readFinancialCommitteeTrust(context.Background(), path, model.genesis, model.anchor); err == nil {
		t.Fatal("foreign journal header accepted")
	}
}
