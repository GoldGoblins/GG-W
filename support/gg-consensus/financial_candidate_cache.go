//go:build !js

package main

// One private deterministic transition, never a consensus or persisted trust
// flag. Callers first revalidate/advance the current owned execution and still
// stage exact originals, derive native state and commit synchronously. A hit
// applies only to the identical committed state, height, clock and wire bytes.
import (
	"bytes"
	"context"
	"reflect"
	"sync"
)

const financialTransitionWireLimit = 4 << 20
const financialTransitionReceiptLimit = 5000
const financialTransitionRetainedLimit uint64 = 64 << 20

type financialCandidateKey struct {
	genesis, source, before, wire string
	height, when                  int64
}

type financialCandidateTransition struct {
	key       financialCandidateKey
	raw       []byte
	execution *financialDagExecution
	estimated uint64
}

type financialTransitionCache struct {
	mu    sync.Mutex
	entry *financialCandidateTransition
}

func financialCandidateIdentity(current *financialDagExecution, before State, raw []byte, when int64) (financialCandidateKey, bool) {
	if current == nil || !current.source.hasProtocol() || current.provisional || when <= 0 || when < current.timeNs ||
		before.Height < 0 || before.Height >= int64(dagSegmentCounterMax) || len(raw) == 0 || len(raw) > financialTransitionWireLimit || !isDagBatch(raw) {
		return financialCandidateKey{}, false
	}
	// A commitment can remain unchanged when a genesis-only admission bound
	// is mutated. Recheck the actual pinned genesis bytes before a memo hit;
	// the private checked handle itself never authorizes a changed genesis.
	if validateGenesis(current.genesis, current.anchor) != nil {
		return financialCandidateKey{}, false
	}
	return financialCandidateKey{genesis: current.anchor, source: current.source.hash(), before: before.StateRoot,
		height: before.Height + 1, when: when, wire: hashHex(raw)}, true
}

func (cache *financialTransitionCache) clear() {
	cache.mu.Lock()
	cache.entry = nil
	cache.mu.Unlock()
}

// ProcessProposal gets no mutable cached execution. Its ordinary durable
// staging and cancellation checks remain mandatory even on this boolean hit.
func (cache *financialTransitionCache) matches(key financialCandidateKey, raw []byte) bool {
	cache.mu.Lock()
	defer cache.mu.Unlock()
	if cache.entry == nil {
		return false
	}
	if cache.entry.key != key || !bytes.Equal(cache.entry.raw, raw) {
		cache.entry = nil
		return false
	}
	return true
}

// Finalize takes sole ownership. execution.clone intentionally drops pending
// receipts/originals, so it must not be used to retrieve a full transition.
func (cache *financialTransitionCache) take(key financialCandidateKey, raw []byte) *financialDagExecution {
	cache.mu.Lock()
	defer cache.mu.Unlock()
	entry := cache.entry
	cache.entry = nil
	if entry == nil || entry.key != key || !bytes.Equal(entry.raw, raw) {
		return nil
	}
	return entry.execution
}

func (cache *financialTransitionCache) retain(ctx context.Context, key financialCandidateKey, raw []byte, next *financialDagExecution) bool {
	cache.clear()
	if ctx.Err() != nil || key.when <= 0 || len(raw) == 0 || len(raw) > financialTransitionWireLimit || hashHex(raw) != key.wire ||
		next == nil || next.provisional || !next.source.hasProtocol() || next.timeNs != key.when || next.money.Protocol == nil ||
		next.money.Protocol.height != uint64(key.height) || next.anchor != key.genesis || next.source.hash() != key.source || len(next.pending) != 1 {
		return false
	}
	// Operations and cuts always use the existing full execution path. This
	// first cache is limited to one ordinary public block of at most5000 TX.
	var batch financialDagBatch
	if decodeStrictLimited(raw, &batch, DagMaxBatchBlocks, 64) != nil || len(batch.Operations) != 0 || len(batch.Blocks) != 1 {
		return false
	}
	receipts := 0
	for _, record := range next.pending {
		// admit intentionally discards decoded block/envelope structs after
		// execution. The native-computed summary and exact raw original remain
		// with every receipt; requiring record.Protocol here would bypass ALL
		// successfully admitted candidates rather than bound their memory.
		if record.Summary.Schema != "gg.financial.summary.v3" || record.Summary.Transactions < 0 ||
			len(record.Receipts) != record.Summary.Transactions {
			return false
		}
		receipts += len(record.Receipts)
	}
	if receipts > financialTransitionReceiptLimit {
		return false
	}
	// A coarse admission reserve plus a separate actual reachable-allocation
	// walk. Neither changes transaction validity: oversized candidates simply
	// execute again. The native process kernel memory cap remains independent.
	coarse := uint64(28<<20) + uint64(len(raw))*4 + uint64(receipts)*4096
	if coarse > financialTransitionRetainedLimit {
		return false
	}
	owned := append([]byte(nil), raw...)
	entry := &financialCandidateTransition{key: key, raw: owned, execution: next}
	estimated, ok := estimateFinancialTransition(ctx, entry)
	if !ok || ctx.Err() != nil {
		return false
	}
	entry.estimated = estimated
	cache.mu.Lock()
	cache.entry = entry
	cache.mu.Unlock()
	return true
}

// This is a conservative retained-size estimate, not a replacement for the
// process resource contract. It counts full backing capacities, actual owned
// tree/ref/node objects and dynamic strings/maps/raw records. Shared string
// data is deliberately overcounted. Functions are borrowed authenticated disk
// readers whose owner remains the backend; the genesis checked handle is also
// owned by that backend independently and may contain a concurrent auth cache.
type financialRetainedWalk struct {
	ctx     context.Context
	bytes   uint64
	steps   uint64
	seen    map[uintptr]bool
	checked reflect.Type
}

func (walk *financialRetainedWalk) add(n uint64) bool {
	if n > financialTransitionRetainedLimit-walk.bytes {
		return false
	}
	walk.bytes += n
	return true
}

func (walk *financialRetainedWalk) dynamic(value reflect.Value) bool {
	walk.steps++
	if walk.steps%256 == 0 && walk.ctx.Err() != nil {
		return false
	}
	if !value.IsValid() {
		return true
	}
	switch value.Kind() {
	case reflect.Pointer:
		if value.IsNil() || value.Type() == walk.checked {
			return true
		}
		address := value.Pointer()
		if walk.seen[address] {
			return true
		}
		walk.seen[address] = true
		return walk.add(uint64(value.Type().Elem().Size())+64) && walk.dynamic(value.Elem())
	case reflect.Struct:
		for index := 0; index < value.NumField(); index++ {
			if !walk.dynamic(value.Field(index)) {
				return false
			}
		}
	case reflect.String:
		return value.Len() == 0 || walk.add(uint64(value.Len())*2+64)
	case reflect.Slice:
		capacity := uint64(value.Cap())
		size := uint64(value.Type().Elem().Size())
		if size != 0 && capacity > financialTransitionRetainedLimit/size || !walk.add(capacity*size+64) {
			return false
		}
		kind := value.Type().Elem().Kind()
		if kind >= reflect.Int && kind <= reflect.Complex128 || kind == reflect.Uintptr || kind == reflect.Bool {
			return true
		}
		all := value.Slice(0, value.Cap())
		for index := 0; index < all.Len(); index++ {
			if !walk.dynamic(all.Index(index)) {
				return false
			}
		}
	case reflect.Array:
		for index := 0; index < value.Len(); index++ {
			if !walk.dynamic(value.Index(index)) {
				return false
			}
		}
	case reflect.Map:
		unit := uint64(value.Type().Key().Size()+value.Type().Elem().Size()) + 64
		count := uint64(value.Len())
		if count > financialTransitionRetainedLimit/(unit*8) || !walk.add(count*unit*8+1024) {
			return false
		}
		iterator := value.MapRange()
		for iterator.Next() {
			if !walk.dynamic(iterator.Key()) || !walk.dynamic(iterator.Value()) {
				return false
			}
		}
	case reflect.Interface:
		if !value.IsNil() {
			return walk.dynamic(value.Elem())
		}
	case reflect.Func:
		// Borrowed store readers, never an imported cache decision.
	case reflect.Chan, reflect.UnsafePointer:
		return value.IsNil()
	}
	return true
}

func estimateFinancialTransition(ctx context.Context, entry *financialCandidateTransition) (uint64, bool) {
	walk := financialRetainedWalk{ctx: ctx, seen: map[uintptr]bool{}, checked: reflect.TypeOf((*checkedGenesisContext)(nil))}
	if ctx.Err() != nil || !walk.dynamic(reflect.ValueOf(entry)) || ctx.Err() != nil {
		return walk.bytes, false
	}
	return walk.bytes, true
}
