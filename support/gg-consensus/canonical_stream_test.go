package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"runtime"
	"strings"
	"testing"
)

type failWriter struct{}

func (failWriter) Write(raw []byte) (int, error) { return 0, errors.New("owned writer fault") }

type shortWriter struct{}

func (shortWriter) Write(raw []byte) (int, error) { return 0, nil }
func TestCanonicalStreamIdenticalBytesHashAndDomain(t *testing.T) {
	cases := []any{nil, true, 0, "<>&\u2028\n\"\\", []any{nil, 1, "s"}, map[string]any{"z": false, "a": []string{"x", "y"}}, struct {
		A string `json:"a"`
		B []byte `json:"b"`
	}{"test", []byte{1, 2, 3}}, strings.Repeat("x", 16*1024*1024)}
	for _, value := range cases {
		raw, err := json.Marshal(value)
		if err != nil {
			t.Fatal(err)
		}
		for _, domain := range []string{"", "GG-DAG-BLOCK-v1\x00", "GG-DAG-PROPOSAL-SIGN-v1\x00"} {
			expected := append([]byte(domain), raw...)
			digest := sha256.Sum256(expected)
			if !bytes.Equal(streamCanonicalDomainBytes(domain, value), expected) || streamCanonicalDigest(domain, value) != hex.EncodeToString(digest[:]) || !streamCanonicalEqual(raw, value) {
				t.Fatal("canonical protocol bytes changed")
			}
		}
		for _, changed := range [][]byte{append(bytes.Clone(raw), ' '), append([]byte{' '}, raw...), append(bytes.Clone(raw), 'x')} {
			if streamCanonicalEqual(changed, value) {
				t.Fatal("noncanonical accepted")
			}
		}
	}
	for _, writer := range []io.Writer{failWriter{}, shortWriter{}} {
		if streamCanonical(writer, "x") == nil {
			t.Fatal("write failure hidden")
		}
	}
	var output bytes.Buffer
	tail := canonicalTail{target: &output}
	for _, chunk := range []string{"", "a", "bc", "", "d", "\n"} {
		if _, err := tail.Write([]byte(chunk)); err != nil {
			t.Fatal(err)
		}
	}
	if !tail.have || tail.last[0] != '\n' || output.String() != "abcd" {
		t.Fatal("chunk boundary altered bytes")
	}
}
func TestCanonicalStreamAllocation(t *testing.T) {
	value := strings.Repeat("x", 16*1024*1024)
	used := make([]uint64, 2)
	functions := []func() string{func() string {
		raw, _ := json.Marshal(value)
		sum := sha256.Sum256(append([]byte("domain\x00"), raw...))
		return hex.EncodeToString(sum[:])
	}, func() string { return streamCanonicalDigest("domain\x00", value) }}
	var expected string
	for index, operation := range functions {
		runtime.GC()
		runtime.GC()
		var before, after runtime.MemStats
		runtime.ReadMemStats(&before)
		result := operation()
		runtime.ReadMemStats(&after)
		if index == 0 {
			expected = result
		} else if expected != result {
			t.Fatal("digest changed")
		}
		used[index] = after.TotalAlloc - before.TotalAlloc
	}
	fmt.Printf("GG_CANONICAL_HASH_ALLOC previous=%d streamed=%d\n", used[0], used[1])
	if used[1]*100 >= used[0]*75 {
		t.Fatal("no material allocation reduction")
	}
}
