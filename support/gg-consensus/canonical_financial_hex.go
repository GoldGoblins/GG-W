package main

// Exactly the existing ^[0-9a-f]{64}$ wire grammar. This does not check
// elliptic-curve membership, signatures, roots, account roles or authority.
// Length is checked before the bounded ASCII scan; no Unicode normalization.
func canonicalFinancialHex(value string) bool {
	if len(value) != 64 {
		return false
	}
	for index := 0; index < len(value); index++ {
		b := value[index]
		if b < '0' || b > 'f' || b > '9' && b < 'a' {
			return false
		}
	}
	return true
}
