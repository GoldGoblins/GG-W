package main

import (
	"bytes"
	"os"
	"path/filepath"
	"testing"
	"time"

	cmtjson "github.com/cometbft/cometbft/libs/json"
	"github.com/cometbft/cometbft/privval"
	cmtproto "github.com/cometbft/cometbft/proto/tendermint/types"
)

func TestMissingSignerStateFailsClosedAndInitializationIsExclusive(t *testing.T) {
	genesis, _, _, keys := testGenesis()
	path := filepath.Join(t.TempDir(), "state.json")
	if _, err := newSafePV(keys[0], path, genesis.ChainID); err == nil {
		t.Fatal("missing restart state recreated")
	}
	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Fatal("restart wrote a new file")
	}
	if _, err := initializeSafePV(keys[0], path, genesis.ChainID); err != nil {
		t.Fatal(err)
	}
	original, _ := os.ReadFile(path)
	if _, err := initializeSafePV(keys[0], path, genesis.ChainID); err == nil {
		t.Fatal("initialization replaced existing state")
	}
	current, _ := os.ReadFile(path)
	if !bytes.Equal(original, current) {
		t.Fatal("existing state changed")
	}
	if _, err := newSafePV(keys[0], path, genesis.ChainID); err != nil {
		t.Fatal(err)
	}
}

func TestLoadedSignerStateBindsAuthorChainAndExactHeightRoundStep(t *testing.T) {
	genesis, _, _, keys := testGenesis()
	path := filepath.Join(t.TempDir(), "state.json")
	pv, err := initializeSafePV(keys[0], path, genesis.ChainID)
	if err != nil {
		t.Fatal(err)
	}
	vote := &cmtproto.Vote{Type: cmtproto.PrevoteType, Height: 2, Round: 1, Timestamp: time.Unix(1700000000, 0)}
	if err := pv.SignVote(genesis.ChainID, vote); err != nil {
		t.Fatal(err)
	}
	good, _ := os.ReadFile(path)
	if _, err := newSafePV(keys[1], path, genesis.ChainID); err == nil {
		t.Fatal("foreign author state accepted")
	}
	if _, err := newSafePV(keys[0], path, "foreign-chain"); err == nil {
		t.Fatal("foreign chain state accepted")
	}
	changes := []func(*privval.FilePVLastSignState){
		func(s *privval.FilePVLastSignState) { s.Height++ },
		func(s *privval.FilePVLastSignState) { s.Round++ },
		func(s *privval.FilePVLastSignState) { s.Step = 3 },
		func(s *privval.FilePVLastSignState) { s.Height = -1 },
		func(s *privval.FilePVLastSignState) { s.Signature = nil },
		func(s *privval.FilePVLastSignState) { s.SignBytes = nil },
		func(s *privval.FilePVLastSignState) { s.Signature[0] ^= 1 },
		func(s *privval.FilePVLastSignState) { s.SignBytes = append(s.SignBytes, 0) },
	}
	for i, change := range changes {
		var state privval.FilePVLastSignState
		if cmtjson.Unmarshal(good, &state) != nil {
			t.Fatal("fixture invalid")
		}
		change(&state)
		raw, _ := cmtjson.Marshal(state)
		if os.WriteFile(path, raw, 0600) != nil {
			t.Fatal("fixture write")
		}
		if _, err := newSafePV(keys[0], path, genesis.ChainID); err == nil {
			t.Fatalf("corrupt state %d accepted", i)
		}
	}
	for _, raw := range [][]byte{[]byte(`{"height":"0","round":0,"step":0,"step":0}`), []byte(`{"height":"0","round":0,"step":0,"unexpected":true}`), []byte(`{"height":"0","round":0,"step":0,"signbytes":"00"}`), good[:len(good)/2]} {
		os.WriteFile(path, raw, 0600)
		if _, err := newSafePV(keys[0], path, genesis.ChainID); err == nil {
			t.Fatal("ambiguous or partial state accepted")
		}
	}
	os.WriteFile(path, good, 0600)
	reloaded, err := newSafePV(keys[0], path, genesis.ChainID)
	if err != nil || reloaded.SignVote(genesis.ChainID, vote) != nil {
		t.Fatal("valid signed state failed reload", err)
	}
}
