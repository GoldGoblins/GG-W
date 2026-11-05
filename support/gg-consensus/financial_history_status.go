//go:build !js

package main

import (
	"context"
	"strconv"
)

// O(1), best effort. Never wait behind archive IO or hold an application lock.
// A report is only owned local runtime metadata, never a consensus certificate
// or a continuous audit of all disk bytes. An empty missing list is not proof
// of availability when state is UNAVAILABLE / archive_fault is non-null.
func (backend *financialNativeApplication) LocalHistoryStatus(ctx context.Context) (map[string]any, int64, error) {
	if err := ctx.Err(); err != nil {
		return nil, 0, err
	}
	store := backend.store
	if !store.mu.TryLock() {
		return nil, 0, errDagCandidateCredit
	}
	defer store.mu.Unlock()
	h := store.history
	if h == nil {
		return nil, 0, errFinancialHistory
	}
	through := store.head.State.Height
	if h.archivedOriginals < 0 || h.archivedOriginals > through || store.verifiedThrough < 0 || store.verifiedThrough > through {
		return nil, 0, errFinancialHistory
	}
	first, activeFirst, activeLast := int64(0), int64(0), int64(0)
	if through > 0 {
		first = 1
	}
	if h.archivedOriginals < through {
		activeFirst = h.archivedOriginals + 1
		activeLast = through
	}
	state := "READY"
	var fault any
	if store.db == nil || store.failed || h.failed.Load() {
		state = "UNAVAILABLE"
		fault = "GG_FINANCIAL_HISTORY_UNAVAILABLE"
	}
	d := func(value int64) string { return strconv.FormatInt(value, 10) }
	u := func(value uint64) string { return strconv.FormatUint(value, 10) }
	return map[string]any{
		"schema":       "gg.financial.local-history-status.v1",
		"scope":        "LOCAL_NATIVE_RUNTIME_REPORT_NOT_SDK_CERTIFICATE_OR_CONTACT",
		"genesis_hash": store.head.Anchor, "mode": "FULL_REPLAY", "state": state,
		"verified_through": d(store.verifiedThrough), "retained_through": d(through),
		"originals_first_height": d(first), "active_original_first_height": d(activeFirst),
		"active_original_last_height": d(activeLast), "active_original_count": d(through - h.archivedOriginals),
		"active_bytes": u(h.activeBytes), "archive_segments": u(h.head.Segments),
		"archive_bytes": u(h.archivedBytes), "archived_original_count": d(h.archivedOriginals),
		"missing_archive_ranges": []any{}, "archive_fault": fault,
		"disk_reserve_bytes":                 u(financialHistoryDiskReserve),
		"full_replay_required_on_cold_start": true, "checkpoint_trusted": false,
	}, through, nil
}

type financialHistoryCutCursor struct {
	h        *financialHistory
	sequence uint64
	next     *financialHistorySegmentHeader
}

func newFinancialHistoryCutCursor(h *financialHistory) (*financialHistoryCutCursor, error) {
	cursor := &financialHistoryCutCursor{h: h, sequence: 1}
	return cursor, cursor.load()
}
func (cursor *financialHistoryCutCursor) load() error {
	cursor.next = nil
	if cursor.sequence > cursor.h.head.Segments {
		return nil
	}
	segment, err := cursor.h.segment(func(key string) ([]byte, error) { return cursor.h.db.Get([]byte(key), nil) }, cursor.sequence)
	if err != nil {
		return err
	}
	cursor.next = &segment.Header
	return nil
}
func (cursor *financialHistoryCutCursor) check(height int64, state, journal string) error {
	for cursor.next != nil && cursor.next.CutHeight <= height {
		if cursor.next.CutHeight != height || cursor.next.CutState != state || cursor.next.CutJournal != journal {
			return errFinancialHistory
		}
		cursor.sequence++
		if err := cursor.load(); err != nil {
			return err
		}
	}
	return nil
}
