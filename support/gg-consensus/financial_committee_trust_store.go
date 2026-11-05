//go:build !js

package main

// Public certificate journal: no imported trust flag, consensus database,
// wallet, credentials or validator signing state. Every load starts at the
// pinned genesis and streams bounded frames, checking every preceding quorum.
import (
	"bufio"
	"bytes"
	"context"
	"encoding/binary"
	"io"
	"os"
	"strconv"
)

type committeeVerifierFrame struct {
	Action      string                        `json:"action"`
	Genesis     *Genesis                      `json:"genesis,omitempty"`
	GenesisHash string                        `json:"genesis_hash,omitempty"`
	Proof       *VerifyInput                  `json:"proof,omitempty"`
	Schema      string                        `json:"schema"`
	Transition  *financialCommitteeTransition `json:"transition,omitempty"`
}

// This process owns no listener, key or consensus state. Its in-memory trust
// comes only from a pinned genesis and individually verified predecessor
// certificates received on its parent's bounded pipe. No serialized trust flag
// or caller-chosen committee can initialize or replace that context.
func runCommitteeVerifyStream(in io.Reader, out io.Writer) error {
	reader := bufio.NewReaderSize(in, 32768)
	writer := bufio.NewWriterSize(out, 8192)
	var genesis Genesis
	var anchor string
	var trust *verifiedCommitteeTrust
	for {
		var prefix [4]byte
		if n, err := io.ReadFull(reader, prefix[:]); err != nil {
			if err == io.EOF && n == 0 {
				return nil
			}
			return errCommittee
		}
		length := binary.BigEndian.Uint32(prefix[:])
		if length == 0 || length > 256*1024+1024 {
			return errCommittee
		}
		raw := make([]byte, int(length))
		if _, err := io.ReadFull(reader, raw); err != nil {
			return errCommittee
		}
		var frame committeeVerifierFrame
		if decodeStrictLimited(raw, &frame, 128, 64) != nil || frame.Schema != "gg.native.committee-verifier-request.v1" {
			return errCommittee
		}
		ok := false
		reply := map[string]any{"ok": false}
		switch frame.Action {
		case "init":
			if trust == nil && frame.Genesis != nil && frame.Proof == nil && frame.Transition == nil {
				var err error
				genesis, anchor = *frame.Genesis, frame.GenesisHash
				trust, err = initialCommitteeTrust(genesis, anchor)
				ok = err == nil
			}
		case "transition":
			if trust != nil && frame.Transition != nil && frame.Genesis == nil && frame.GenesisHash == "" && frame.Proof == nil && trust.current.Epoch < financialCommitteeTrustMaxRecords {
				ok = trust.accept(genesis, *frame.Transition) == nil
			}
		case "verify":
			if trust != nil && frame.Proof != nil && frame.Genesis == nil && frame.GenesisHash == "" && frame.Transition == nil {
				input := *frame.Proof
				if input.CommitteeTrustPath == "" && input.CommitteeTransitions == nil && input.GenesisHash == anchor && bytes.Equal(canonical(input.Genesis), canonical(genesis)) {
					input.committeeTrust = trust
					result, err := verifyInput(input)
					if err == nil {
						ok = true
						reply["result"] = result
					}
				}
			}
		}
		reply["ok"] = ok
		if trust != nil {
			reply["epoch"] = strconv.FormatUint(trust.current.Epoch, 10)
		}
		encoded := canonical(reply)
		if len(encoded) > 8192 {
			return errCommittee
		}
		binary.BigEndian.PutUint32(prefix[:], uint32(len(encoded)))
		if _, err := writer.Write(prefix[:]); err != nil {
			return err
		}
		if _, err := writer.Write(encoded); err != nil {
			return err
		}
		if err := writer.Flush(); err != nil {
			return err
		}
	}
}

const financialCommitteeTrustMagic = "GGCOMTR1"
const financialCommitteeTrustMaxBytes int64 = 8 << 30
const financialCommitteeTrustMaxRecords = 1000000

func readFinancialCommitteeTrust(ctx context.Context, path string, genesis Genesis, anchor string) (*verifiedCommitteeTrust, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, errCommittee
	}
	defer file.Close()
	info, err := file.Stat()
	if err != nil || !info.Mode().IsRegular() || info.Size() < 8 || info.Size() > financialCommitteeTrustMaxBytes {
		return nil, errCommittee
	}
	var magic [8]byte
	if _, err = io.ReadFull(file, magic[:]); err != nil || string(magic[:]) != financialCommitteeTrustMagic {
		return nil, errCommittee
	}
	trust, err := initialCommitteeTrust(genesis, anchor)
	if err != nil {
		return nil, err
	}
	for count := 0; ; count++ {
		if err = ctx.Err(); err != nil {
			return nil, err
		}
		var size [4]byte
		n, readErr := io.ReadFull(file, size[:])
		if readErr == io.EOF && n == 0 {
			return trust, nil
		}
		length := binary.BigEndian.Uint32(size[:])
		if readErr != nil || count >= financialCommitteeTrustMaxRecords || length == 0 || length > 256*1024 {
			return nil, errCommittee
		}
		raw := make([]byte, int(length))
		if _, err = io.ReadFull(file, raw); err != nil {
			return nil, errCommittee
		}
		var transition financialCommitteeTransition
		if decodeStrictLimited(raw, &transition, 128, 64) != nil || !bytes.Equal(raw, canonical(transition)) {
			return nil, errCommittee
		}
		if err = trust.accept(genesis, transition); err != nil {
			return nil, err
		}
	}
}

func loadInputCommitteeTrust(input *VerifyInput) error {
	if input.CommitteeTrustPath == "" {
		return nil
	}
	if validateGenesis(input.Genesis, input.GenesisHash) != nil {
		return errCommittee
	}
	trust, err := readFinancialCommitteeTrust(context.Background(), input.CommitteeTrustPath, input.Genesis, input.GenesisHash)
	if err != nil {
		return err
	}
	input.committeeTrust = trust
	input.CommitteeTrustPath = ""
	return nil
}
