//go:build !js

package main

// The final quorum-signed SDK header authenticates every preceding header
// through LastBlockID. Each actual block's DataHash, AppHash and Time bind the
// selected package and its application height; final balances alone do not.
import (
	"bytes"
	"encoding/hex"
	"errors"
	"path/filepath"
	"strconv"
	"time"

	dbm "github.com/cometbft/cometbft-db"
	cmtjson "github.com/cometbft/cometbft/libs/json"
	cmtstore "github.com/cometbft/cometbft/store"
	"github.com/cometbft/cometbft/types"
	"github.com/syndtr/goleveldb/leveldb/opt"
)

var errFinancialSDKBinding = errors.New("GG_FINANCIAL_ARCHIVE_SDK_BINDING")

func financialSDKHeaderKey(height int64) string { return "h/" + financialHeightKey(height)[2:] }

func checkedFinancialSDKHeader(raw []byte, genesis Genesis, height int64) (*types.Header, error) {
	var header types.Header
	if len(raw) == 0 || len(raw) > dagArchiveHeaderLimit || cmtjson.Unmarshal(raw, &header) != nil {
		return nil, errFinancialSDKBinding
	}
	normalized, err := cmtjson.Marshal(&header)
	validators := validatorSet(genesis)
	if err != nil || !bytes.Equal(raw, normalized) || header.ValidateBasic() != nil || header.Height != height ||
		header.ChainID != genesis.ChainID || !publicFinancialProtocol(genesis) && (!bytes.Equal(header.ValidatorsHash, validators.Hash()) || !bytes.Equal(header.NextValidatorsHash, validators.Hash())) ||
		header.Time.UnixNano() < 0 || !time.Unix(0, header.Time.UnixNano()).UTC().Equal(header.Time.UTC()) {
		return nil, errFinancialSDKBinding
	}
	if height == 1 && !header.LastBlockID.IsZero() {
		return nil, errFinancialSDKBinding
	}
	return &header, nil
}

func financialSDKStateBinding(header *types.Header, state State) error {
	expected, err := hex.DecodeString(state.StateRoot)
	if err != nil || header.Height != state.Height+1 || !bytes.Equal(header.AppHash, expected) {
		return errFinancialSDKBinding
	}
	return nil
}

func financialSDKJournalBinding(current, next *types.Header, entry financialJournalEntry, state State) error {
	when, ok := dagDecimalNs(entry.TimeNs)
	txs := types.Txs{}
	if len(entry.Transaction) > 0 && !bytes.Equal(entry.Transaction, []byte("null")) {
		txs = append(txs, types.Tx(entry.Transaction))
	}
	if !ok || current.Height != entry.Height || current.Time.UnixNano() != when || !bytes.Equal(current.DataHash, txs.Hash()) ||
		next.Height != current.Height+1 || !next.Time.After(current.Time) || !bytes.Equal(next.LastBlockID.Hash, current.Hash()) {
		return errFinancialSDKBinding
	}
	return financialSDKStateBinding(next, state)
}

func financialSDKCertificateBinding(header *types.Header, certificate dagArchiveCertificate) error {
	trusted, _, err := verifyFinancialCertificate(certificate.packet())
	if err != nil || !bytes.Equal(header.Hash(), trusted.Header.Hash()) {
		return errFinancialSDKBinding
	}
	return nil
}

// Restored stores retain public authenticated headers, not SDK consensus DBs.
// A real live-source export reads only SDK BlockMeta records from its blockstore.
func financialSDKHeaderSource(root string, financialRead func(string) ([]byte, error), head financialStoreHead, last int64) (func(int64) ([]byte, error), func(int64) ([]byte, error), func() error, int, error) {
	origin := int64(0)
	if head.Recovery != nil && head.Recovery.Complete {
		origin = head.Recovery.Height
	}
	if origin > 0 && last <= origin {
		version := 1
		if last == origin && len(head.Recovery.SDKCommit) > 0 {
			version = 2
		}
		return func(height int64) ([]byte, error) { return financialRead(financialSDKHeaderKey(height)) },
			func(height int64) ([]byte, error) {
				if height == origin-1 && version == 2 {
					return append([]byte(nil), head.Recovery.SDKCommit...), nil
				}
				return nil, errFinancialSDKBinding
			},
			func() error { return nil }, version, nil
	}
	directory := filepath.Join(root, "data")
	if !realArchiveDirectory(directory) || !realArchiveDirectory(filepath.Join(directory, "blockstore.db")) {
		return nil, nil, nil, 0, errFinancialSDKBinding
	}
	db, err := dbm.NewGoLevelDBWithOpts("blockstore", directory, &opt.Options{ReadOnly: true, ErrorIfMissing: true, Strict: opt.StrictAll,
		BlockCacheCapacity: 4 * 1024 * 1024, OpenFilesCacheCapacity: 32})
	if err != nil {
		return nil, nil, nil, 0, errFinancialSDKBinding
	}
	var store *cmtstore.BlockStore
	func() {
		defer func() {
			if recover() != nil {
				store = nil
			}
		}()
		store = cmtstore.NewBlockStore(db)
	}()
	maximumBase := int64(1)
	if origin > 0 {
		maximumBase = origin + 1
	}
	if store == nil || store.Base() > maximumBase || store.Height() < last {
		_ = db.Close()
		return nil, nil, nil, 0, errFinancialSDKBinding
	}
	load := func(height int64) (raw []byte, err error) {
		defer func() {
			if recover() != nil {
				raw = nil
				err = errFinancialSDKBinding
			}
		}()
		if origin > 0 && height <= origin {
			return financialRead(financialSDKHeaderKey(height))
		}
		metadata := store.LoadBlockMeta(height)
		if metadata == nil {
			return nil, errFinancialSDKBinding
		}
		return cmtjson.Marshal(&metadata.Header)
	}
	commit := func(height int64) (raw []byte, err error) {
		defer func() {
			if recover() != nil {
				raw = nil
				err = errFinancialSDKBinding
			}
		}()
		if height == 0 {
			return []byte("null"), nil
		}
		if origin > 0 && height == origin-1 && len(head.Recovery.SDKCommit) > 0 {
			return append([]byte(nil), head.Recovery.SDKCommit...), nil
		}
		value := store.LoadBlockCommit(height)
		if value == nil {
			return nil, errFinancialSDKBinding
		}
		return cmtjson.Marshal(value)
	}
	return load, commit, db.Close, 2, nil
}

func financialSDKHeaderHeight(key string) (int64, bool) {
	if len(key) < 3 || key[:2] != "h/" {
		return 0, false
	}
	height, err := strconv.ParseInt(key[2:], 10, 64)
	return height, err == nil && height > 0 && key == financialSDKHeaderKey(height)
}

type financialStoredSDKReplay struct {
	read     func(string) ([]byte, error)
	genesis  Genesis
	recovery *financialStoreRecovery
	header   *types.Header
	sdk      *financialSDKRecovery
}

func newFinancialStoredSDKReplay(read func(string) ([]byte, error), genesis Genesis, recovery *financialStoreRecovery, state State) (*financialStoredSDKReplay, error) {
	if recovery == nil {
		return nil, nil
	}
	if publicFinancialProtocol(genesis) && recovery.Complete && len(recovery.SDKCommit) == 0 {
		return nil, errFinancialSDKRecovery
	}
	raw, err := read(financialSDKHeaderKey(1))
	if err != nil {
		return nil, errFinancialSDKBinding
	}
	header, err := checkedFinancialSDKHeader(raw, genesis, 1)
	if err != nil || financialSDKStateBinding(header, state) != nil {
		return nil, errFinancialSDKBinding
	}
	replay := &financialStoredSDKReplay{read: read, genesis: genesis, recovery: recovery, header: header}
	if len(recovery.SDKCommit) > 0 || publicFinancialProtocol(genesis) {
		replay.sdk, err = newFinancialSDKRecovery(genesis)
		if err != nil || replay.sdk.checkHeader(header) != nil {
			return nil, errFinancialSDKRecovery
		}
		if recovery.Height == 1 && recovery.Complete && replay.sdk.bindCommit(nil, header, recovery.SDKCommit) != nil {
			return nil, errFinancialSDKRecovery
		}
	}
	if recovery.Height == 1 && (financialSDKCertificateBinding(header, *recovery.Certificate) != nil || !bytes.Equal(canonical(state), canonical(recovery.Certificate.State))) {
		return nil, errFinancialSDKBinding
	}
	return replay, nil
}

func (replay *financialStoredSDKReplay) apply(entry financialJournalEntry, state State) error {
	if replay == nil || entry.Height >= replay.recovery.Height {
		return nil
	}
	raw, err := replay.read(financialSDKHeaderKey(entry.Height + 1))
	if err != nil {
		return errFinancialSDKBinding
	}
	next, err := checkedFinancialSDKHeader(raw, replay.genesis, entry.Height+1)
	if err != nil || financialSDKJournalBinding(replay.header, next, entry, state) != nil {
		return errFinancialSDKBinding
	}
	if replay.sdk != nil {
		if replay.sdk.advance(replay.header, next, state) != nil {
			return errFinancialSDKRecovery
		}
		if next.Height == replay.recovery.Height && replay.recovery.Complete && replay.sdk.bindCommit(replay.header, next, replay.recovery.SDKCommit) != nil {
			return errFinancialSDKRecovery
		}
	}
	replay.header = next
	if next.Height == replay.recovery.Height && (financialSDKCertificateBinding(next, *replay.recovery.Certificate) != nil ||
		!bytes.Equal(canonical(state), canonical(replay.recovery.Certificate.State))) {
		return errFinancialSDKBinding
	}
	return nil
}
