package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math/rand"
	"reflect"
	"runtime"
	"strings"
	"testing"
)

type strictJSONAllocationProbe struct{ called bool }

func (probe *strictJSONAllocationProbe) UnmarshalJSON([]byte) error { probe.called = true; return nil }

func TestStrictDAGShapeLimitsRunBeforeAnyTypedUnmarshal(t *testing.T) {
	for _, limit := range []int{DagMaxBatchBlocks, DagMaxBlockTransactions} {
		t.Run(fmt.Sprint(limit), func(t *testing.T) {
			exact := []byte("[" + strings.Repeat("0,", limit-1) + "0]")
			probe := strictJSONAllocationProbe{}
			if err := decodeStrictLimited(exact, &probe, limit, 64); err != nil || !probe.called {
				t.Fatal("exact collection limit rejected", err)
			}
			over := []byte("[" + strings.Repeat("0,", limit) + "0]")
			probe.called = false
			if err := decodeStrictLimited(over, &probe, limit, 64); err == nil || err.Error() != "GG_JSON_ARRAY_LIMIT" || probe.called {
				t.Fatal("over-limit collection reached typed decoder")
			}
			if err := decodeStrict(over, &probe); err != nil || !probe.called {
				t.Fatal("ordinary strict reader's original rules changed", err)
			}
		})
	}
	var object strings.Builder
	object.WriteByte('{')
	for i := 0; i < 65; i++ {
		if i > 0 {
			object.WriteByte(',')
		}
		fmt.Fprintf(&object, "\"k%d\":0", i)
	}
	object.WriteByte('}')
	probe := strictJSONAllocationProbe{}
	if err := decodeStrictLimited([]byte(object.String()), &probe, 50000, 64); err == nil || err.Error() != "GG_JSON_OBJECT_LIMIT" || probe.called {
		t.Fatal("object limit reached typed decoder")
	}
}

func TestActualDAGBlockAndBatchRejectCollectionAmplificationWithinSmallAllocationBudget(t *testing.T) {
	base, _ := dagFixture(t)
	attacks := map[string][]byte{
		"two_million_empty_TX_objects":    []byte(`{"body":{"transactions":[` + strings.Repeat(`{},`, 1999999) + `{}]},"signature":""}`),
		"two_million_empty_batch_strings": []byte(`{"blocks":[` + strings.Repeat(`"",`, 1999999) + `""]}`),
	}
	var object strings.Builder
	object.WriteByte('{')
	for i := 0; i < 500000; i++ {
		if i > 0 {
			object.WriteByte(',')
		}
		fmt.Fprintf(&object, "\"unknown%06d\":0", i)
	}
	object.WriteByte('}')
	attacks["half_million_unknown_object_fields"] = []byte(object.String())
	for name, raw := range attacks {
		t.Run(name, func(t *testing.T) {
			if !json.Valid(raw) || len(raw) > DagMaxWire {
				t.Fatal("attack fixture not actually within raw byte limit")
			}
			runtime.GC()
			var before, after runtime.MemStats
			runtime.ReadMemStats(&before)
			var err error
			if name == "two_million_empty_batch_strings" {
				_, err = applyDagBatch(base, raw, 1700000002000000000)
			} else {
				_, err = decodeDagBlock(raw, base.Source, 1700000002000000000)
			}
			runtime.ReadMemStats(&after)
			if err == nil || after.TotalAlloc-before.TotalAlloc > 16*1024*1024 {
				t.Fatal("invalid collection caused typed allocation amplification", after.TotalAlloc-before.TotalAlloc)
			}
			t.Logf("GG_DAG_JSON_PREFLIGHT case=%s raw_bytes=%d allocated_bytes=%d", name, len(raw), after.TotalAlloc-before.TotalAlloc)
		})
	}
}

func TestStrictJSONMatchesIndependentPreviousReader(t *testing.T) {
	cases := [][]byte{nil, []byte(`{}`), []byte(`[]`), []byte(`null`), []byte(`false`), []byte(`0`), []byte(`1e1000`), []byte(`"quoted\\\""`), []byte(`{} {}`), []byte(`{"a":1,"a":2}`), []byte(`{"a":1,"\u0061":2}`), []byte(`{"\ud800":1,"\ufffd":2}`), []byte{'{', '"', 0xff, '"', ':', '1', ',', '"', 0xfe, '"', ':', '2', '}'}, []byte(`{"a":[{},[],null,true,2,"x"],"b":{"a":3}}`)}
	for depth := 0; depth < 16; depth++ {
		cases = append(cases, []byte(strings.Repeat("[", depth)+"0"+strings.Repeat("]", depth)), []byte(strings.Repeat(`{"a":`, depth)+"{}"+strings.Repeat("}", depth)))
	}
	random := rand.New(rand.NewSource(271828))
	for i := 0; i < 20000; i++ {
		count := random.Intn(80)
		raw := make([]byte, count)
		alphabet := []byte("{\"aAb\\u0123456789,}:[]nultfre -+.e\r\n\t")
		for j := range raw {
			raw[j] = alphabet[random.Intn(len(alphabet))]
		}
		cases = append(cases, raw)
	}
	for index, raw := range cases {
		var old, new any
		before := legacyStrict(raw, &old)
		after := decodeStrict(raw, &new)
		if (before == nil) != (after == nil) || before == nil && !reflect.DeepEqual(old, new) {
			t.Fatalf("oracle mismatch at %d", index)
		}
	}
	type typed struct {
		A string `json:"a"`
	}
	for _, raw := range []string{`{"a":"ok"}`, `{"A":"ok"}`, `{"a":"ok","b":1}`, `{"a":"x","\u0061":"y"}`, `{"a":null}`} {
		var a, b typed
		first := legacyStrict([]byte(raw), &a)
		last := decodeStrict([]byte(raw), &b)
		if (first == nil) != (last == nil) || first == nil && a != b {
			t.Fatal("typed compatibility")
		}
	}
	// Every one-byte mutation of a structured document compares two separate
	// implementations, including malformed syntax, escapes and delimiters.
	seed := []byte(`{"a":{"nested":["a\\b",1,false,null]},"b":"x"}`)
	for index := range seed {
		for value := 0; value < 256; value++ {
			raw := bytes.Clone(seed)
			raw[index] = byte(value)
			var a, b any
			first := legacyStrict(raw, &a)
			last := decodeStrict(raw, &b)
			if (first == nil) != (last == nil) || first == nil && !reflect.DeepEqual(a, b) {
				t.Fatal("single-byte mutation oracle mismatch", index, value)
			}
		}
	}
}
func TestStrictJSONLargeValueAvoidsDuplicateValueAllocation(t *testing.T) {
	raw := []byte(`{"a":"` + strings.Repeat("x", 16*1024*1024) + `"}`)
	type payload struct {
		A string `json:"a"`
	}
	used := make([]uint64, 2)
	for index, decoder := range []func([]byte, any) error{legacyStrict, decodeStrict} {
		runtime.GC()
		var before, after runtime.MemStats
		runtime.ReadMemStats(&before)
		var result payload
		if decoder(raw, &result) != nil || len(result.A) != 16*1024*1024 {
			t.Fatal("large value changed")
		}
		runtime.ReadMemStats(&after)
		used[index] = after.TotalAlloc - before.TotalAlloc
		runtime.KeepAlive(result)
	}
	fmt.Printf("GG_JSON_ALLOCATION baseline=%d candidate=%d bytes=%d\n", used[0], used[1], len(raw))
	if used[1]*100 >= used[0]*70 {
		t.Fatal("candidate failed bounded allocation reduction")
	}
	var changed map[string]json.RawMessage
	if decodeStrict(append(bytes.TrimSuffix(raw, []byte("}")), []byte(`,"\u0061":"duplicate"}`)...), &changed) == nil {
		t.Fatal("large duplicate alias accepted")
	}
}

// The previous independent decoder is retained only as a test oracle.
func legacyCheck(decoder *json.Decoder, depth int) error {
	if depth > 12 {
		return errors.New("GG_JSON_DEPTH")
	}
	token, err := decoder.Token()
	if err != nil {
		return err
	}
	delimiter, container := token.(json.Delim)
	if !container {
		return nil
	}
	switch delimiter {
	case '{':
		seen := map[string]bool{}
		for decoder.More() {
			key, err := decoder.Token()
			if err != nil {
				return err
			}
			name, ok := key.(string)
			if !ok || seen[name] {
				return errors.New("GG_JSON_DUPLICATE_KEY")
			}
			seen[name] = true
			if err := legacyCheck(decoder, depth+1); err != nil {
				return err
			}
		}
	case '[':
		for decoder.More() {
			if err := legacyCheck(decoder, depth+1); err != nil {
				return err
			}
		}
	default:
		return errors.New("GG_JSON_DELIMITER")
	}
	_, err = decoder.Token()
	return err
}

func legacyStrict(data []byte, target any) error {
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.UseNumber()
	if err := legacyCheck(decoder, 0); err != nil {
		return err
	}
	if _, err := decoder.Token(); err != io.EOF {
		return errors.New("GG_JSON_TRAILING_DATA")
	}
	decoder = json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	return decoder.Decode(target)
}
