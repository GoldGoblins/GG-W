//go:build !js

package main

// Exact selected financial journals, including empty SDK application heights.
// All originals execute again against a separately pinned SDK certificate.
// Application recovery never imports consensus databases or signing keys.
import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	cmtjson "github.com/cometbft/cometbft/libs/json"
	"github.com/cometbft/cometbft/types"
	"github.com/syndtr/goleveldb/leveldb"
	"github.com/syndtr/goleveldb/leveldb/opt"
)

const financialArchiveMagic = "GGFINAR1"
const financialSDKArchiveMagic = "GGFINAR2"
const financialArchiveScope = "FULL_SELECTED_ORIGINAL_SIGNED_PAYMENTS_AND_SDK_APP_HEIGHT_REPLAY_WITH_PINNED_CERTIFICATE_NOT_CONSENSUS_OR_SIGNING_STATE_RECOVERY"

var errFinancialArchive = errors.New("GG_FINANCIAL_ARCHIVE_INVALID")

type financialArchiveCommand struct {
	ArchivePath              string                 `json:"archive_path"`
	Certificate              *dagArchiveCertificate `json:"certificate,omitempty"`
	Genesis                  Genesis                `json:"genesis"`
	GenesisHash              string                 `json:"genesis_hash"`
	MinimumCertificateHeight int64                  `json:"minimum_certificate_height,omitempty"`
	MinimumCertificateBlock  string                 `json:"minimum_certificate_block,omitempty"`
	Root                     string                 `json:"root,omitempty"`
	RestoreRoot              string                 `json:"restore_root,omitempty"`
}

type financialArchiveFooter struct {
	Content   string `json:"content_sha256"`
	Height    int64  `json:"height"`
	Journal   string `json:"journal_sha256"`
	Schema    string `json:"schema"`
	StateRoot string `json:"state_root"`
}

type financialArchiveReplay struct {
	execution       *financialDagExecution
	lineageScratch  *financialLineageScratch
	accountScratch  *financialAccountScratch
	protocolScratch *financialProtocolScratch
	state           State
	journal         string
	when            int64
	sdkNextRaw      []byte
	sdkPrevious     *types.Header
	sdkRecovery     *financialSDKRecovery
	sdkCommit       []byte
}

func newFinancialArchiveReplay(genesis Genesis, anchor string) (*financialArchiveReplay, error) {
	execution, err := newFinancialDagExecution(genesis, anchor, *genesis.FinancialDAG)
	if err != nil {
		return nil, err
	}
	cursor := &financialArchiveReplay{execution: execution, state: initialState(execution.genesis, anchor), journal: DagZero, when: execution.timeNs}
	if execution.source.hasLineage() {
		cursor.lineageScratch, err = newFinancialLineageScratch()
		if err != nil {
			return nil, err
		}
		freezeFinancialLineage(execution, cursor.lineageScratch.read)
	}
	if execution.source.hasGeneralAccounts() {
		rules, err := financialAccountRulesFor(genesis, anchor)
		if err != nil {
			_ = cursor.close()
			return nil, err
		}
		cursor.accountScratch, err = newFinancialAccountScratch(rules)
		if err != nil {
			_ = cursor.close()
			return nil, err
		}
		if err = cursor.accountScratch.stage(context.Background(), execution); err != nil {
			_ = cursor.close()
			return nil, err
		}
		if err = freezeFinancialAccounts(execution, cursor.accountScratch.read); err != nil {
			_ = cursor.close()
			return nil, err
		}
	}
	if execution.source.hasProtocol() {
		cursor.protocolScratch, err = newFinancialProtocolScratch(genesis, anchor)
		if err != nil {
			_ = cursor.close()
			return nil, err
		}
		if err = cursor.protocolScratch.stage(context.Background(), execution); err != nil {
			_ = cursor.close()
			return nil, err
		}
		if err = freezeFinancialProtocol(execution, cursor.protocolScratch.read); err != nil {
			_ = cursor.close()
			return nil, err
		}
	}
	return cursor, nil
}

func (cursor *financialArchiveReplay) close() error {
	var lineageErr, accountErr error
	if cursor.lineageScratch != nil {
		lineageErr = cursor.lineageScratch.close()
	}
	if cursor.accountScratch != nil {
		accountErr = cursor.accountScratch.close()
	}
	var protocolErr error
	if cursor.protocolScratch != nil {
		protocolErr = cursor.protocolScratch.close()
	}
	return errors.Join(lineageErr, accountErr, protocolErr)
}

func (cursor *financialArchiveReplay) apply(ctx context.Context, raw []byte) (financialJournalEntry, error) {
	if ctx.Err() != nil {
		return financialJournalEntry{}, ctx.Err()
	}
	// The previous delta was saved before its sink callback. Release its RAM
	// references only now, after the sink could atomically retain those nodes.
	if cursor.lineageScratch != nil {
		freezeFinancialLineage(cursor.execution, cursor.lineageScratch.read)
	}
	if cursor.accountScratch != nil {
		if err := freezeFinancialAccounts(cursor.execution, cursor.accountScratch.read); err != nil {
			return financialJournalEntry{}, err
		}
	}
	if cursor.protocolScratch != nil {
		if err := freezeFinancialProtocol(cursor.execution, cursor.protocolScratch.read); err != nil {
			return financialJournalEntry{}, err
		}
	}
	var entry financialJournalEntry
	if len(raw) > financialJournalMaxWire || decodeStrictLimited(raw, &entry, DagMaxBatchBlocks, 64) != nil || !bytes.Equal(raw, canonical(entry)) ||
		entry.Schema != "gg.financial-dag.journal-entry.v1" || cursor.state.Height == int64(dagSegmentCounterMax) ||
		entry.Height != cursor.state.Height+1 || entry.Previous != cursor.journal {
		return entry, errFinancialArchive
	}
	when, ok := dagDecimalNs(entry.TimeNs)
	if !ok || when < cursor.when || when > int64(dagSegmentCounterMax)-5000000000 {
		return entry, errFinancialArchive
	}
	execution, err := advanceFinancialExecution(ctx, cursor.execution, cursor.state, when)
	if err != nil {
		return entry, err
	}
	if !bytes.Equal(entry.Transaction, []byte("null")) {
		var err error
		execution, err = financialTransition(ctx, execution, entry.Transaction, when)
		if err != nil {
			return entry, err
		}
	}
	state, err := financialNativeState(cursor.state, execution, entry.Height)
	if err != nil || state.StateRoot != entry.After {
		return entry, errFinancialArchive
	}
	if cursor.lineageScratch != nil {
		if err = cursor.lineageScratch.stage(ctx, execution); err != nil {
			return entry, err
		}
	}
	if cursor.accountScratch != nil {
		if err = cursor.accountScratch.stage(ctx, execution); err != nil {
			return entry, err
		}
	}
	if cursor.protocolScratch != nil {
		if err = cursor.protocolScratch.stage(ctx, execution); err != nil {
			return entry, err
		}
	}
	cursor.execution, cursor.state, cursor.when, cursor.journal = execution, state, when, financialJournalHash(raw)
	return entry, nil
}

func checkedFinancialArchiveCertificate(value dagArchiveCertificate, request financialArchiveCommand) (dagArchiveCertificate, string, error) {
	if request.Genesis.FinancialDAG == nil || value.Genesis.FinancialDAG == nil || value.State.FinancialDAG == nil ||
		value.GenesisHash != request.GenesisHash || !bytes.Equal(canonical(value.Genesis), canonical(request.Genesis)) ||
		len(canonical(value)) > dagArchiveHeaderLimit || request.MinimumCertificateHeight < 0 ||
		request.MinimumCertificateBlock != "" && (!pubPattern.MatchString(request.MinimumCertificateBlock) || request.MinimumCertificateHeight == 0) {
		return value, "", errors.New("GG_FINANCIAL_ARCHIVE_TRUST")
	}
	if _, err := verifyInput(value.packet()); err != nil {
		return value, "", errors.New("GG_FINANCIAL_ARCHIVE_CERTIFICATE")
	}
	header, _, err := verifyFinancialCertificate(value.packet())
	if err != nil || header.Height < request.MinimumCertificateHeight {
		return value, "", errors.New("GG_FINANCIAL_ARCHIVE_CERTIFICATE_FLOOR")
	}
	block := strings.ToLower(header.Commit.BlockID.Hash.String())
	if header.Height == request.MinimumCertificateHeight && request.MinimumCertificateBlock != "" && block != request.MinimumCertificateBlock {
		return value, "", errors.New("GG_FINANCIAL_ARCHIVE_CERTIFICATE_CONFLICT")
	}
	value.SignedHeader, err = cmtjson.Marshal(header)
	if err != nil {
		return value, "", errFinancialArchive
	}
	return value, block, nil
}

func financialArchiveResult(cursor *financialArchiveReplay, certificate dagArchiveCertificate, block, whole, content string) map[string]any {
	value := cursor.state.FinancialDAG
	return map[string]any{"schema": "gg.financial.archive.result.v1", "verified": true, "verification_scope": financialArchiveScope,
		"certificate": certificate, "certificate_block": block,
		"archive_sha256": whole, "content_sha256": content, "genesis_hash": certificate.GenesisHash, "source_hash": value.SourceHash,
		"certificate_height": certificate.State.Height + 1, "application_height": cursor.state.Height, "state_root": cursor.state.StateRoot,
		"journal_sha256": cursor.journal, "account_root": cursor.state.AccountRoot, "financial_commitment": value,
		"blocks_replayed": strconv.FormatUint(value.Blocks, 10), "payments_applied": strconv.FormatUint(value.Applied, 10),
		"payments_rejected": strconv.FormatUint(value.Rejected, 10), "raw_original_bytes": strconv.FormatUint(value.RawBytes, 10),
		"checkpoints_replayed": strconv.FormatUint(value.Checkpoint, 10), "snapshot_trust_used": false, "signing_keys_exported": false,
		"consensus_store_restored": false, "validator_signing_state_restored": false, "network_contact_asserted": false,
		"sdk_recovery_available": cursor.sdkRecovery != nil && cursor.state.Height > 0,
		"archive_version":        financialArchiveVersion(cursor)}
}

func financialFooter(cursor *financialArchiveReplay, content string) financialArchiveFooter {
	return financialArchiveFooter{Content: content, Height: cursor.state.Height, Journal: cursor.journal, Schema: "gg.financial.archive.footer.v1", StateRoot: cursor.state.StateRoot}
}

type financialArchiveSink func(financialJournalEntry, []byte, *financialArchiveReplay) error

func readFinancialArchive(ctx context.Context, input io.Reader, request financialArchiveCommand, sink financialArchiveSink) (map[string]any, error) {
	return readFinancialArchiveUsing(ctx, input, request, sink, nil)
}

func readFinancialArchiveUsing(ctx context.Context, input io.Reader, request financialArchiveCommand, sink financialArchiveSink, finish func(*financialArchiveReplay) error) (published map[string]any, failure error) {
	digest := sha256.New()
	hashed := io.TeeReader(input, digest)
	var magic [8]byte
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	if _, err := io.ReadFull(hashed, magic[:]); err != nil || !financialArchiveMagicValid(string(magic[:])) {
		return nil, errFinancialArchive
	}
	raw, err := readArchiveFrame(hashed, 'H', dagArchiveHeaderLimit)
	var header dagArchiveHeader
	if err != nil || decodeStrictLimited(raw, &header, MaxBlockTxs, 64) != nil || !bytes.Equal(raw, canonical(header)) || !financialArchiveSchemaMatches(string(magic[:]), header.Schema) {
		return nil, errFinancialArchive
	}
	certificate, block, err := checkedFinancialArchiveCertificate(header.Certificate, request)
	if err != nil {
		return nil, err
	}
	if !bytes.Equal(certificate.SignedHeader, header.Certificate.SignedHeader) {
		return nil, errFinancialArchive
	}
	cursor, err := newFinancialArchiveReplay(request.Genesis, request.GenesisHash)
	if err != nil {
		return nil, err
	}
	defer func() {
		if err := cursor.close(); err != nil {
			published, failure = nil, err
		}
	}()
	if string(magic[:]) == financialSDKArchiveMagic {
		cursor.sdkRecovery, err = newFinancialSDKRecovery(request.Genesis)
		if err != nil {
			return nil, err
		}
	}
	if publicFinancialProtocol(request.Genesis) && cursor.sdkRecovery == nil {
		return nil, errFinancialSDKRecovery
	}
	headerRaw, err := readArchiveFrame(hashed, 'B', dagArchiveHeaderLimit)
	if err != nil {
		return nil, err
	}
	currentHeader, err := checkedFinancialSDKHeader(headerRaw, request.Genesis, 1)
	if err != nil || financialSDKStateBinding(currentHeader, cursor.state) != nil {
		return nil, errFinancialSDKBinding
	}
	if cursor.sdkRecovery != nil && cursor.sdkRecovery.checkHeader(currentHeader) != nil {
		return nil, errFinancialSDKBinding
	}
	for height := int64(1); height <= certificate.State.Height; height++ {
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		raw, err := readArchiveFrame(hashed, 'J', financialJournalMaxWire)
		if err != nil {
			return nil, err
		}
		entry, err := cursor.apply(ctx, raw)
		if err != nil {
			return nil, err
		}
		headerRaw, err = readArchiveFrame(hashed, 'B', dagArchiveHeaderLimit)
		if err != nil {
			return nil, err
		}
		nextHeader, headerErr := checkedFinancialSDKHeader(headerRaw, request.Genesis, height+1)
		if headerErr != nil || financialSDKJournalBinding(currentHeader, nextHeader, entry, cursor.state) != nil {
			return nil, errFinancialSDKBinding
		}
		if cursor.sdkRecovery != nil && cursor.sdkRecovery.advance(currentHeader, nextHeader, cursor.state) != nil {
			return nil, errFinancialSDKBinding
		}
		cursor.sdkPrevious = currentHeader
		cursor.sdkNextRaw = headerRaw
		currentHeader = nextHeader
		if sink != nil {
			if err = sink(entry, raw, cursor); err != nil {
				return nil, err
			}
		}
		cursor.execution = cursor.execution.clone() // no retained pending originals/receipts across heights
	}
	if !bytes.Equal(canonical(cursor.state), canonical(certificate.State)) || financialSDKCertificateBinding(currentHeader, certificate) != nil {
		return nil, errors.New("GG_FINANCIAL_ARCHIVE_STATE_MISMATCH")
	}
	if cursor.sdkRecovery != nil {
		cursor.sdkCommit, err = readArchiveFrame(hashed, 'C', financialSDKCommitMaxWire)
		if err != nil || cursor.sdkRecovery.bindCommit(cursor.sdkPrevious, currentHeader, cursor.sdkCommit) != nil {
			return nil, errFinancialSDKBinding
		}
	}
	content := hex.EncodeToString(digest.Sum(nil))
	raw, err = readArchiveFrame(hashed, 'F', dagArchiveFooterLimit)
	if err != nil || !bytes.Equal(raw, canonical(financialFooter(cursor, content))) {
		return nil, errFinancialArchive
	}
	var extra [1]byte
	if n, err := hashed.Read(extra[:]); n != 0 || err != io.EOF {
		return nil, errFinancialArchive
	}
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	if finish != nil {
		if err = finish(cursor); err != nil {
			return nil, err
		}
	}
	return financialArchiveResult(cursor, certificate, block, hex.EncodeToString(digest.Sum(nil)), content), nil
}

// Read only the selected journal prefix. Derived receipt indexes and candidates
// are never copied or trusted; restore derives them again from actual originals.
func exportFinancialArchive(ctx context.Context, output io.Writer, request financialArchiveCommand) (published map[string]any, failure error) {
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	if request.Certificate == nil {
		return nil, errFinancialArchive
	}
	certificate, block, err := checkedFinancialArchiveCertificate(*request.Certificate, request)
	if err != nil {
		return nil, err
	}
	if !realArchiveDirectory(request.Root) || !realArchiveDirectory(filepath.Join(request.Root, "gg-financial-dag.leveldb")) {
		return nil, errors.New("GG_FINANCIAL_ARCHIVE_SOURCE")
	}
	db, err := leveldb.OpenFile(filepath.Join(request.Root, "gg-financial-dag.leveldb"), &opt.Options{ReadOnly: true, ErrorIfMissing: true,
		Strict: opt.StrictAll, BlockCacheCapacity: 4 * 1024 * 1024, OpenFilesCacheCapacity: 32})
	if err != nil {
		return nil, errors.New("GG_FINANCIAL_ARCHIVE_SOURCE_BUSY_OR_INVALID")
	}
	defer func() {
		if closeErr := db.Close(); closeErr != nil && failure == nil {
			published = nil
			failure = errors.New("GG_FINANCIAL_ARCHIVE_SOURCE_CLOSE")
		}
	}()
	logical, err := openFinancialHistory(ctx, db, request.Root, request.GenesisHash, request.Genesis.FinancialDAG.hash(), false)
	if err != nil {
		return nil, err
	}
	raw, err := db.Get([]byte("head"), nil)
	var saved financialStoreHead
	if err != nil || len(raw) > financialStoreHeadMaxWire || decodeStrict(raw, &saved) != nil || !bytes.Equal(raw, canonical(saved)) ||
		!validFinancialStoreRecovery(saved, request.Genesis, request.GenesisHash, false) || saved.Anchor != request.GenesisHash || saved.Source != request.Genesis.FinancialDAG.hash() ||
		saved.State.Height < certificate.State.Height || validateState(saved.State, request.Genesis, request.GenesisHash) != nil {
		return nil, errors.New("GG_FINANCIAL_ARCHIVE_SOURCE")
	}
	cursor, err := newFinancialArchiveReplay(request.Genesis, request.GenesisHash)
	if err != nil {
		return nil, err
	}
	defer func() {
		if err := cursor.close(); err != nil {
			published, failure = nil, err
		}
	}()
	digest := sha256.New()
	hashed := io.MultiWriter(output, digest)
	loadHeader, loadCommit, closeHeaders, version, err := financialSDKHeaderSource(request.Root, func(key string) ([]byte, error) {
		return logical.requiredRead(ctx, func(key string) ([]byte, error) { return logical.get(ctx, key) }, key)
	}, saved, certificate.State.Height+1)
	if err != nil {
		return nil, err
	}
	defer closeHeaders()
	magic, schema := financialArchiveMagic, "gg.financial.public-archive.v1"
	if version == 2 {
		magic, schema = financialSDKArchiveMagic, "gg.financial.public-archive.v2"
		cursor.sdkRecovery, err = newFinancialSDKRecovery(request.Genesis)
		if err != nil {
			return nil, err
		}
	}
	if n, err := io.WriteString(hashed, magic); err != nil || n != 8 {
		return nil, errFinancialArchive
	}
	if err = writeArchiveFrame(hashed, 'H', canonical(dagArchiveHeader{Certificate: certificate, Schema: schema}), dagArchiveHeaderLimit); err != nil {
		return nil, err
	}
	headerRaw, err := loadHeader(1)
	if err != nil {
		return nil, err
	}
	currentHeader, err := checkedFinancialSDKHeader(headerRaw, request.Genesis, 1)
	if err != nil || financialSDKStateBinding(currentHeader, cursor.state) != nil {
		return nil, errFinancialSDKBinding
	}
	if cursor.sdkRecovery != nil && cursor.sdkRecovery.checkHeader(currentHeader) != nil {
		return nil, errFinancialSDKBinding
	}
	if err = writeArchiveFrame(hashed, 'B', headerRaw, dagArchiveHeaderLimit); err != nil {
		return nil, err
	}
	for height := int64(1); height <= certificate.State.Height; height++ {
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		raw, err := logical.requiredRead(ctx, func(key string) ([]byte, error) { return logical.get(ctx, key) }, financialHeightKey(height))
		if err != nil || len(raw) > financialJournalMaxWire {
			return nil, errFinancialArchive
		}
		entry, applyErr := cursor.apply(ctx, raw)
		if applyErr != nil {
			return nil, applyErr
		}
		headerRaw, err = loadHeader(height + 1)
		if err != nil {
			return nil, err
		}
		nextHeader, headerErr := checkedFinancialSDKHeader(headerRaw, request.Genesis, height+1)
		if headerErr != nil || financialSDKJournalBinding(currentHeader, nextHeader, entry, cursor.state) != nil {
			return nil, errFinancialSDKBinding
		}
		if cursor.sdkRecovery != nil && cursor.sdkRecovery.advance(currentHeader, nextHeader, cursor.state) != nil {
			return nil, errFinancialSDKBinding
		}
		cursor.sdkPrevious = currentHeader
		currentHeader = nextHeader
		if err = writeArchiveFrame(hashed, 'J', raw, financialJournalMaxWire); err != nil {
			return nil, err
		}
		if err = writeArchiveFrame(hashed, 'B', headerRaw, dagArchiveHeaderLimit); err != nil {
			return nil, err
		}
		cursor.execution = cursor.execution.clone()
	}
	if !bytes.Equal(canonical(cursor.state), canonical(certificate.State)) || financialSDKCertificateBinding(currentHeader, certificate) != nil {
		return nil, errors.New("GG_FINANCIAL_ARCHIVE_STATE_MISMATCH")
	}
	if cursor.sdkRecovery != nil {
		cursor.sdkCommit, err = loadCommit(certificate.State.Height)
		if err != nil || cursor.sdkRecovery.bindCommit(cursor.sdkPrevious, currentHeader, cursor.sdkCommit) != nil {
			return nil, errFinancialSDKBinding
		}
		if err = writeArchiveFrame(hashed, 'C', cursor.sdkCommit, financialSDKCommitMaxWire); err != nil {
			return nil, err
		}
	}
	content := hex.EncodeToString(digest.Sum(nil))
	if err = writeArchiveFrame(hashed, 'F', canonical(financialFooter(cursor, content)), dagArchiveFooterLimit); err != nil {
		return nil, err
	}
	if err = closeHeaders(); err != nil {
		return nil, errors.New("GG_FINANCIAL_ARCHIVE_SOURCE_CLOSE")
	}
	return financialArchiveResult(cursor, certificate, block, hex.EncodeToString(digest.Sum(nil)), content), nil
}

func openFinancialArchiveInput(path string) (*os.File, os.FileInfo, error) {
	info, err := os.Lstat(path)
	if err != nil || !info.Mode().IsRegular() || info.Mode()&os.ModeSymlink != 0 || info.Size() < 8 {
		return nil, nil, errors.New("GG_FINANCIAL_ARCHIVE_FILE")
	}
	file, err := os.Open(path)
	if err != nil {
		return nil, nil, errors.New("GG_FINANCIAL_ARCHIVE_FILE")
	}
	opened, err := file.Stat()
	if err != nil || !os.SameFile(info, opened) || info.Size() != opened.Size() || !info.ModTime().Equal(opened.ModTime()) {
		_ = file.Close()
		return nil, nil, errors.New("GG_FINANCIAL_ARCHIVE_FILE")
	}
	return file, info, nil
}

func unchangedFinancialArchive(file *os.File, info os.FileInfo) bool {
	after, err := file.Stat()
	return err == nil && os.SameFile(info, after) && info.Size() == after.Size() && info.ModTime().Equal(after.ModTime())
}

func runFinancialArchiveCommand(mode string, raw []byte) (map[string]any, error) {
	var request financialArchiveCommand
	if len(raw) > 512*1024 || decodeStrictLimited(raw, &request, MaxBlockTxs, 64) != nil || !filepath.IsAbs(request.ArchivePath) ||
		validateGenesis(request.Genesis, request.GenesisHash) != nil || request.Genesis.FinancialDAG == nil {
		return nil, errors.New("GG_FINANCIAL_ARCHIVE_COMMAND")
	}
	if mode == "financial-history-verify" || mode == "financial-history-restore" {
		if request.Root != "" || request.Certificate != nil || (mode == "financial-history-verify" && request.RestoreRoot != "") {
			return nil, errors.New("GG_FINANCIAL_ARCHIVE_COMMAND")
		}
		file, info, err := openFinancialArchiveInput(request.ArchivePath)
		if err != nil {
			return nil, err
		}
		defer file.Close()
		var result map[string]any
		if mode == "financial-history-restore" {
			result, err = restoreFinancialArchive(context.Background(), file, info, request)
		} else {
			result, err = readFinancialArchive(context.Background(), file, request, nil)
		}
		if err != nil {
			return nil, err
		}
		if !unchangedFinancialArchive(file, info) {
			return nil, errors.New("GG_FINANCIAL_ARCHIVE_CHANGED")
		}
		if file.Close() != nil {
			return nil, errors.New("GG_FINANCIAL_ARCHIVE_CLOSE")
		}
		return result, nil
	}
	if mode != "financial-history-export" || request.Certificate == nil || request.RestoreRoot != "" || !filepath.IsAbs(request.Root) {
		return nil, errors.New("GG_FINANCIAL_ARCHIVE_COMMAND")
	}
	root, err := filepath.EvalSymlinks(request.Root)
	if err != nil {
		return nil, errors.New("GG_FINANCIAL_ARCHIVE_SOURCE")
	}
	request.Root = root
	parent, err := filepath.EvalSymlinks(filepath.Dir(request.ArchivePath))
	if err != nil || !realArchiveDirectory(parent) {
		return nil, errors.New("GG_FINANCIAL_ARCHIVE_DESTINATION")
	}
	destination := filepath.Join(parent, filepath.Base(request.ArchivePath))
	if pathWithinArchiveRoot(destination, root) {
		return nil, errors.New("GG_FINANCIAL_ARCHIVE_SOURCE_WRITE_FORBIDDEN")
	}
	file, err := os.OpenFile(destination, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil {
		return nil, errors.New("GG_FINANCIAL_ARCHIVE_DESTINATION_EXISTS_OR_UNAVAILABLE")
	}
	created, statErr := file.Stat()
	complete := false
	defer func() {
		_ = file.Close()
		if !complete && statErr == nil {
			if info, err := os.Lstat(destination); err == nil && os.SameFile(info, created) {
				_ = os.Remove(destination)
			}
		}
	}()
	if statErr != nil {
		return nil, errFinancialArchive
	}
	result, err := exportFinancialArchive(context.Background(), file, request)
	if err != nil {
		return nil, err
	}
	if file.Sync() != nil || file.Close() != nil {
		return nil, errors.New("GG_FINANCIAL_ARCHIVE_CLOSE")
	}
	complete = true
	return result, nil
}
