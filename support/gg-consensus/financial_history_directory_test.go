//go:build !js

package main

import (
	"context"
	"os"
	"path/filepath"
	"testing"
)

func TestFinancialHistoryReadDirectoryFailureLatchesWithoutReturningOriginal(t *testing.T) {
	history, _, records, values, _ := historyPhysicalV2(t, 1)
	key := records[0].key
	if raw, err := history.get(context.Background(), key); err != nil || string(raw) != string(values[key]) {
		t.Fatal("real archived record did not verify before directory damage", err)
	}
	path := history.directory()
	if err := os.Rename(path, filepath.Join(history.root, "PUBLIC-displaced-history")); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte("PUBLIC regular file is not a directory"), 0600); err != nil {
		t.Fatal(err)
	}
	if raw, err := history.get(context.Background(), key); err == nil || raw != nil || !history.failed.Load() {
		t.Fatal("directory failure returned original bytes or failed to latch", err)
	}
	if raw, err := history.get(context.Background(), key); err == nil || raw != nil {
		t.Fatal("known directory failure did not remain closed")
	}
}
