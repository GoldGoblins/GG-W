package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
)

// Delay exactly one byte across writes. Encoder.Encode's final newline is
// excluded while all JSON bytes go unchanged to the existing hash/message.
type canonicalTail struct {
	target io.Writer
	last   [1]byte
	have   bool
}

func (stream *canonicalTail) writeExact(raw []byte) error {
	count, err := stream.target.Write(raw)
	if err != nil {
		return err
	}
	if count != len(raw) {
		return io.ErrShortWrite
	}
	return nil
}
func (stream *canonicalTail) Write(raw []byte) (int, error) {
	if len(raw) == 0 {
		return 0, nil
	}
	if stream.have {
		if err := stream.writeExact(stream.last[:]); err != nil {
			return 0, err
		}
	}
	if len(raw) > 1 {
		if err := stream.writeExact(raw[:len(raw)-1]); err != nil {
			return 0, err
		}
	}
	stream.last[0] = raw[len(raw)-1]
	stream.have = true
	return len(raw), nil
}
func streamCanonical(target io.Writer, value any) error {
	stream := canonicalTail{target: target}
	if err := json.NewEncoder(&stream).Encode(value); err != nil {
		return err
	}
	if !stream.have || stream.last[0] != '\n' {
		return errors.New("GG_CANONICAL_ENCODING")
	}
	return nil
}

type canonicalComparator struct {
	expected []byte
	offset   int
	equal    bool
}

func (writer *canonicalComparator) Write(raw []byte) (int, error) {
	if writer.offset > len(writer.expected) || len(raw) > len(writer.expected)-writer.offset {
		writer.equal = false
		return len(raw), nil
	}
	if !bytes.Equal(raw, writer.expected[writer.offset:writer.offset+len(raw)]) {
		writer.equal = false
	}
	writer.offset += len(raw)
	return len(raw), nil
}
func streamCanonicalEqual(raw []byte, value any) bool {
	writer := canonicalComparator{expected: raw, equal: true}
	return streamCanonical(&writer, value) == nil && writer.equal && writer.offset == len(raw)
}
func streamCanonicalDomainBytes(domain string, value any) []byte {
	var target bytes.Buffer
	target.WriteString(domain)
	if streamCanonical(&target, value) != nil {
		panic("GG_CANONICAL_ENCODING")
	}
	return target.Bytes()
}
func streamCanonicalDigest(domain string, value any) string {
	target := sha256.New()
	target.Write([]byte(domain))
	if streamCanonical(target, value) != nil {
		panic("GG_CANONICAL_ENCODING")
	}
	return hex.EncodeToString(target.Sum(nil))
}
