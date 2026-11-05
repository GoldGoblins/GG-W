//go:build !js

package main

// A retained archive certificate can predate the first actual SDK block. This
// is an exact nonvoting owned-ledger proof, never a checkpoint/signing grant.
import (
	"bytes"
	"context"
	"encoding/hex"
	"errors"
	cmtjson "github.com/cometbft/cometbft/libs/json"
	cmtnode "github.com/cometbft/cometbft/node"
	sm "github.com/cometbft/cometbft/state"
	cmtstore "github.com/cometbft/cometbft/store"
	"github.com/cometbft/cometbft/types"
	"io"
	"path/filepath"
)

var errOwnedRecoveryFloor = errors.New("GG_OWNED_RECOVERY_CERTIFICATE_FLOOR")

func checkOwnedRecoveryNodeFloor(ctx context.Context, boot Bootstrap, app *Ledger, floor ownedRecoveryFloor, node *cmtnode.Node) (failure error) {
	defer func() {
		if recover() != nil {
			failure = errOwnedRecoveryFloor
		}
	}()
	if ctx.Err() != nil {
		return ctx.Err()
	}
	if node == nil || app == nil || floor.height < 1 {
		return errOwnedRecoveryFloor
	}
	blocks := node.BlockStore()
	if blocks == nil {
		return errOwnedRecoveryFloor
	}
	// Original validator/full-blockstore predicate is unchanged. A validator can
	// never enter the restored nonvoting fallback, even with valid archive bytes.
	meta := blocks.LoadBlockMeta(floor.height)
	if blocks.Height() >= floor.height && meta != nil && hex.EncodeToString(meta.BlockID.Hash) == floor.block && app.state.Height >= floor.height-1 {
		return nil
	}
	if _, ok := node.PrivValidator().(*nativeObserverPV); !ok {
		return errOwnedRecoveryFloor
	}
	environment, err := node.ConfigureRPC()
	if err != nil || environment == nil || environment.StateStore == nil {
		return errOwnedRecoveryFloor
	}
	actual, err := environment.StateStore.Load()
	if err != nil {
		return errOwnedRecoveryFloor
	}
	return checkOwnedRecoveryRestoredFloor(ctx, boot, app, floor, blocks, actual)
}

func ownedRecoveryFloorOrigin(ctx context.Context, boot Bootstrap, app *Ledger, floor ownedRecoveryFloor) (*financialNativeApplication, *types.SignedHeader, error) {
	if ctx.Err() != nil {
		return nil, nil, ctx.Err()
	}
	if app == nil || boot.ValidatorSeed != "" || boot.ExpectedFresh == nil || *boot.ExpectedFresh ||
		(boot.observer == nil && (boot.public == nil || boot.public.Role != "REPLICA")) ||
		boot.public != nil && boot.public.Role != "REPLICA" || !publicFinancialProtocol(boot.Genesis) ||
		app.anchor != boot.GenesisHash || !bytes.Equal(canonical(app.genesis), canonical(boot.Genesis)) {
		return nil, nil, errOwnedRecoveryFloor
	}
	backend, ok := app.financial.(*financialNativeApplication)
	if !ok || backend.store == nil || backend.store.health() != nil || backend.store.history == nil {
		return nil, nil, errOwnedRecoveryFloor
	}
	store := backend.store
	saved := store.head.Recovery
	owned := store.recoverySDK
	if saved == nil || !saved.Complete || saved.Certificate == nil || owned == nil || owned.commit == nil ||
		floor.height != saved.Height || floor.block != saved.Block || saved.Height < 2 ||
		store.verifiedThrough < saved.Height-1 || store.verifiedThrough > app.state.Height ||
		!bytes.Equal(canonical(store.head.State), canonical(app.state)) ||
		owned.state.LastBlockHeight != saved.Height-1 || owned.commit.Height != saved.Height-1 {
		return nil, nil, errOwnedRecoveryFloor
	}
	// Reverify original quorum signatures/committee transitions; a saved profile
	// certificate and a stored Complete bit alone cannot satisfy this predicate.
	certificate, block, err := checkedFinancialArchiveCertificate(*saved.Certificate, financialArchiveCommand{Genesis: boot.Genesis, GenesisHash: boot.GenesisHash, MinimumCertificateHeight: floor.height, MinimumCertificateBlock: floor.block})
	if err != nil || block != floor.block || certificate.State.Height != floor.height-1 {
		return nil, nil, errOwnedRecoveryFloor
	}
	signed, _, err := verifyFinancialCertificate(certificate.packet())
	if err != nil || signed.Height != floor.height || hex.EncodeToString(signed.Header.Hash()) != floor.block {
		return nil, nil, errOwnedRecoveryFloor
	}
	raw, err := store.history.requiredRead(ctx, func(key string) ([]byte, error) { return store.history.get(ctx, key) }, financialSDKHeaderKey(floor.height))
	retained, err2 := checkedFinancialSDKHeader(raw, boot.Genesis, floor.height)
	commitRaw, err3 := cmtjson.Marshal(owned.commit)
	if err != nil || err2 != nil || err3 != nil || !bytes.Equal(retained.Hash(), signed.Header.Hash()) ||
		!bytes.Equal(commitRaw, saved.SDKCommit) || !bytes.Equal(owned.state.AppHash, signed.AppHash) ||
		financialSDKStateBinding(signed.Header, certificate.State) != nil {
		return nil, nil, errOwnedRecoveryFloor
	}
	marker, identity, err := nativeRootIdentity(boot)
	if err != nil {
		return nil, nil, errOwnedRecoveryFloor
	}
	finish, err := recoveryHistoryDirectory(ctx, boot.Root)
	if err != nil {
		return nil, nil, errOwnedRecoveryFloor
	}
	file, _, err := recoveryHistoryFile(ctx, filepath.Join(boot.Root, marker), 65536)
	if err != nil {
		_ = finish()
		return nil, nil, errOwnedRecoveryFloor
	}
	actual, readErr := io.ReadAll(io.LimitReader(file, 65537))
	closeErr := file.Close()
	directoryErr := finish()
	if readErr != nil || closeErr != nil || directoryErr != nil || !bytes.Equal(actual, identity) || recoveryRootCurrent(ctx, boot.Root) != nil {
		return nil, nil, errOwnedRecoveryFloor
	}
	return backend, signed, nil
}

func checkOwnedRecoveryRestoredFloor(ctx context.Context, boot Bootstrap, app *Ledger, floor ownedRecoveryFloor, blocks *cmtstore.BlockStore, actual sm.State) (failure error) {
	defer func() {
		if recover() != nil {
			failure = errOwnedRecoveryFloor
		}
	}()
	backend, origin, err := ownedRecoveryFloorOrigin(ctx, boot, app, floor)
	if err != nil {
		return err
	}
	if blocks == nil {
		return errOwnedRecoveryFloor
	}
	store := backend.store
	owned := store.recoverySDK
	seen := blocks.LoadSeenCommit(owned.state.LastBlockHeight)
	if seen == nil || !bytes.Equal(canonical(seen), canonical(owned.commit)) {
		return errOwnedRecoveryFloor
	}
	if blocks.Height() == 0 {
		if blocks.Base() != 0 || app.state.Height != floor.height-1 || !bytes.Equal(canonical(app.state), canonical(store.head.Recovery.Certificate.State)) || !actual.Equals(owned.state) {
			return errOwnedRecoveryFloor
		}
		return ctx.Err()
	}
	// A joined store may start at origin+1: the quorum-certified origin header
	// remains in the fully reexecuted app's retained originals/header records.
	// Larger missing ranges cannot be proven here and remain rejected.
	base, last := blocks.Base(), blocks.Height()
	if base != floor.height+1 || last < base || actual.LastBlockHeight != last || app.state.Height != last ||
		actual.ChainID != boot.Genesis.ChainID || !bytes.Equal(actual.AppHash, mustOwnedFloorRoot(app.state.StateRoot)) {
		return errOwnedRecoveryFloor
	}
	current := origin.Header
	for height := base; height <= last; height++ {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		meta := blocks.LoadBlockMeta(height)
		if meta == nil {
			return errOwnedRecoveryFloor
		}
		encoded, e := cmtjson.Marshal(&meta.Header)
		if e != nil {
			return errOwnedRecoveryFloor
		}
		next, e := checkedFinancialSDKHeader(encoded, boot.Genesis, height)
		if e != nil || !bytes.Equal(meta.BlockID.Hash, next.Hash()) || !bytes.Equal(next.LastBlockID.Hash, current.Hash()) {
			return errOwnedRecoveryFloor
		}
		entry, e := ownedRecoveryFloorJournal(ctx, store, current.Height)
		if e != nil {
			return e
		}
		// These After roots came from this attempt's mandatory complete execution,
		// not from an imported state; the binding helper only reads Height/StateRoot.
		if financialSDKJournalBinding(current, next, entry, State{Height: entry.Height, StateRoot: entry.After}) != nil {
			return errOwnedRecoveryFloor
		}
		current = next
		if e = recoveryWork(ctx, uint64(len(encoded)+1), nil); e != nil {
			return e
		}
	}
	finalEntry, err := ownedRecoveryFloorJournal(ctx, store, last)
	if err != nil || !ownedRecoveryFloorJournalHeader(current, finalEntry) || !bytes.Equal(actual.AppHash, mustOwnedFloorRoot(finalEntry.After)) {
		return errOwnedRecoveryFloor
	}
	meta := blocks.LoadBlockMeta(last)
	commit := blocks.LoadSeenCommit(last)
	if meta == nil || commit == nil || !commit.BlockID.Equals(meta.BlockID) || !actual.LastBlockID.Equals(meta.BlockID) || !actual.LastBlockTime.Equal(current.Time) {
		return errOwnedRecoveryFloor
	}
	// Only the last preceding State is needed. It is always inside the existing
	// bounded history window; no origin/intermediate history array is retained.
	var previous State
	found := false
	for _, state := range app.history {
		if state.Height == last-1 {
			previous = state
			found = true
			break
		}
	}
	if !found {
		return errOwnedRecoveryFloor
	}
	currentSet, err := ownedRecoveryColdCommittee(previous, last, boot)
	if err != nil {
		return err
	}
	nextSet, err := ownedRecoveryColdCommittee(previous, last+1, boot)
	if err != nil {
		return err
	}
	afterSet, err := ownedRecoveryColdCommittee(app.state, last+2, boot)
	if err != nil {
		return err
	}
	signed, err := cmtjson.Marshal(&types.SignedHeader{Header: current, Commit: commit})
	if err != nil {
		return errOwnedRecoveryFloor
	}
	if _, err = verifyHeaderWithSets(signed, boot.Genesis, currentSet, nextSet); err != nil {
		return errOwnedRecoveryFloor
	}
	if actual.LastValidators == nil || actual.Validators == nil || actual.NextValidators == nil ||
		!bytes.Equal(actual.LastValidators.Hash(), currentSet.Hash()) || !bytes.Equal(actual.Validators.Hash(), nextSet.Hash()) || !bytes.Equal(actual.NextValidators.Hash(), afterSet.Hash()) ||
		blocks.Base() != base || blocks.Height() != last || recoveryRootCurrent(ctx, boot.Root) != nil {
		return errOwnedRecoveryFloor
	}
	return ctx.Err()
}
func mustOwnedFloorRoot(root string) []byte {
	decoded, err := hex.DecodeString(root)
	if err != nil {
		return nil
	}
	return decoded
}
func ownedRecoveryFloorJournal(ctx context.Context, store *financialStore, height int64) (financialJournalEntry, error) {
	raw, err := store.history.requiredRead(ctx, func(key string) ([]byte, error) { return store.history.get(ctx, key) }, financialHeightKey(height))
	var entry financialJournalEntry
	if err != nil || len(raw) > financialJournalMaxWire || decodeStrictLimited(raw, &entry, DagMaxBatchBlocks, 64) != nil || !streamCanonicalEqual(raw, entry) || entry.Schema != "gg.financial-dag.journal-entry.v1" || entry.Height != height || !pubPattern.MatchString(entry.After) {
		return entry, errOwnedRecoveryFloor
	}
	return entry, nil
}
func ownedRecoveryFloorJournalHeader(header *types.Header, entry financialJournalEntry) bool {
	when, ok := dagDecimalNs(entry.TimeNs)
	txs := types.Txs{}
	if len(entry.Transaction) > 0 && !bytes.Equal(entry.Transaction, []byte("null")) {
		txs = append(txs, types.Tx(entry.Transaction))
	}
	return ok && header.Height == entry.Height && header.Time.UnixNano() == when && bytes.Equal(header.DataHash, txs.Hash())
}
func ownedRecoveryColdCommittee(state State, height int64, boot Bootstrap) (*types.ValidatorSet, error) {
	if state.Protocol == nil || height < state.Height || height > state.Height+2 || validateState(state, boot.Genesis, boot.GenesisHash) != nil {
		return nil, errOwnedRecoveryFloor
	}
	committee := state.Protocol.Committee
	if pending := state.Protocol.PendingCommittee; pending != nil && uint64(height) >= pending.EffectiveHeight {
		committee = pending.Next
	}
	set, err := committeeValidatorSet(committee)
	if err != nil {
		return nil, errOwnedRecoveryFloor
	}
	return set, nil
}
