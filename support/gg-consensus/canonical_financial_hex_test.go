package main

import (
	"strings"
	"testing"
)

func TestFinancialCanonicalHexExactlyMatchesExistingWireGrammar(t *testing.T) {
	base := []byte(strings.Repeat("a0", 32))
	for index := range base {
		original := base[index]
		for candidate := 0; candidate < 256; candidate++ {
			base[index] = byte(candidate)
			value := string(base)
			if canonicalFinancialHex(value) != pubPattern.MatchString(value) {
				t.Fatal("fixed ASCII grammar differs from existing canonical parser", index, candidate)
			}
		}
		base[index] = original
	}
	for _, value := range []string{"", strings.Repeat("0", 63), strings.Repeat("f", 65),
		strings.Repeat("f", 64) + "\n", strings.Repeat("a", 4096), strings.Repeat("０", 64),
		strings.Repeat("A", 64), strings.Repeat("0", 64), strings.Repeat("f", 64)} {
		if canonicalFinancialHex(value) != pubPattern.MatchString(value) {
			t.Fatal("length/Unicode/boundary grammar changed")
		}
	}
}
