// GG's disposable native ledger on the maintained CometBFT consensus engine.
// Bootstrap secrets enter only through stdin; no validator/node key is saved.
package main

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"os/signal"
	"path/filepath"
	"regexp"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	cfg "github.com/cometbft/cometbft/config"
	cmtcrypto "github.com/cometbft/cometbft/crypto"
	cmted "github.com/cometbft/cometbft/crypto/ed25519"
	cmtjson "github.com/cometbft/cometbft/libs/json"
	"github.com/cometbft/cometbft/libs/log"
	"github.com/cometbft/cometbft/libs/protoio"
	cmtnode "github.com/cometbft/cometbft/node"
	"github.com/cometbft/cometbft/p2p"
	"github.com/cometbft/cometbft/privval"
	cmtproto "github.com/cometbft/cometbft/proto/tendermint/types"
	"github.com/cometbft/cometbft/types"
)

type Peer struct {
	ID   string `json:"id"`
	Port int    `json:"port"`
	Host string `json:"host,omitempty"`
}
type Bootstrap struct {
	Resources      *nativeResources `json:"resources,omitempty"`
	Schema         string           `json:"schema"`
	Genesis        Genesis          `json:"genesis"`
	GenesisHash    string           `json:"genesis_hash"`
	ValidatorIndex int              `json:"validator_index"`
	ValidatorSeed  string           `json:"validator_seed"`
	NodeSeed       string           `json:"node_seed"`
	Root           string           `json:"root"`
	RPCPort        int              `json:"rpc_port"`
	P2PPort        int              `json:"p2p_port"`
	Peers          []Peer           `json:"peers"`
	ExpectedFresh  *bool            `json:"expected_fresh,omitempty"`
	observer       *nativeObserverBootstrap
	public         *nativePublicBootstrap
}

type SafePV struct {
	mu                sync.Mutex
	inner             *privval.FilePV
	chain             string
	recovery          context.Context
	recoveryReady     bool
	recoveryState     []byte
	recoveryStateInfo os.FileInfo
}

func newSafePV(key cmtcrypto.PrivKey, path, chain string) (*SafePV, error) {
	pv := privval.NewFilePV(key, "", path)
	if raw, err := os.ReadFile(path); err == nil {
		if len(raw) > 8192 {
			return nil, errors.New("GG_SIGN_STATE_SIZE")
		}
		// Decode into the existing struct to retain its unexported public-state path.
		var fields map[string]json.RawMessage
		if decodeStrict(raw, &fields) != nil || len(fields) < 3 || len(fields) > 5 {
			return nil, errors.New("GG_SIGN_STATE_INVALID")
		}
		for name := range fields {
			if name != "height" && name != "round" && name != "step" && name != "signature" && name != "signbytes" {
				return nil, errors.New("GG_SIGN_STATE_INVALID")
			}
		}
		if fields["height"] == nil || fields["round"] == nil || fields["step"] == nil || cmtjson.Unmarshal(raw, &pv.LastSignState) != nil || !validLastSignState(pv.LastSignState, key.PubKey(), chain) {
			return nil, errors.New("GG_SIGN_STATE_INVALID")
		}
	} else if os.IsNotExist(err) {
		// Recreating this file during restart could sign a conflicting H/R/S.
		return nil, errors.New("GG_SIGN_STATE_MISSING")
	} else {
		return nil, errors.New("GG_SIGN_STATE_READ")
	}
	return &SafePV{inner: pv, chain: chain}, nil
}

func initializeSafePV(key cmtcrypto.PrivKey, path, chain string) (*SafePV, error) {
	// Only the fresh-root path may initialize. Never overwrite or repair state.
	state := privval.NewFilePV(key, "", path).LastSignState
	raw, err := cmtjson.Marshal(state)
	if err != nil {
		return nil, errors.New("GG_SIGN_STATE_INVALID")
	}
	file, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil {
		return nil, errors.New("GG_SIGN_STATE_CREATE")
	}
	_, err = file.Write(raw)
	if err == nil {
		err = file.Sync()
	}
	closeErr := file.Close()
	if err != nil || closeErr != nil {
		return nil, errors.New("GG_SIGN_STATE_CREATE")
	}
	return newSafePV(key, path, chain)
}

func validLastSignState(state privval.FilePVLastSignState, public cmtcrypto.PubKey, chain string) bool {
	if state.Height == 0 && state.Round == 0 && state.Step == 0 {
		return len(state.SignBytes) == 0 && len(state.Signature) == 0
	}
	if state.Height < 1 || state.Round < 0 || state.Step < 1 || state.Step > 3 || len(state.SignBytes) == 0 || len(state.SignBytes) > 1024 || len(state.Signature) != 64 || !public.VerifySignature(state.SignBytes, state.Signature) {
		return false
	}
	if state.Step == 1 {
		var proposal cmtproto.CanonicalProposal
		if protoio.UnmarshalDelimited(state.SignBytes, &proposal) != nil {
			return false
		}
		raw, err := protoio.MarshalDelimited(&proposal)
		return err == nil && bytes.Equal(raw, state.SignBytes) && proposal.Type == cmtproto.ProposalType && proposal.ChainID == chain && proposal.Height == state.Height && proposal.Round == int64(state.Round)
	}
	var vote cmtproto.CanonicalVote
	if protoio.UnmarshalDelimited(state.SignBytes, &vote) != nil {
		return false
	}
	raw, err := protoio.MarshalDelimited(&vote)
	expected := cmtproto.PrevoteType
	if state.Step == 3 {
		expected = cmtproto.PrecommitType
	}
	return err == nil && bytes.Equal(raw, state.SignBytes) && vote.Type == expected && vote.ChainID == chain && vote.Height == state.Height && vote.Round == int64(state.Round)
}

func (pv *SafePV) GetPubKey() (cmtcrypto.PubKey, error) {
	pv.mu.Lock()
	defer pv.mu.Unlock()
	return pv.inner.GetPubKey()
}
func (pv *SafePV) SignVote(chain string, vote *cmtproto.Vote) error {
	pv.mu.Lock()
	defer pv.mu.Unlock()
	if pv.recovery != nil && (!pv.recoveryReady || pv.recovery.Err() != nil) {
		return errors.New("GG_SIGN_RECOVERY_NOT_READY")
	}
	if chain != pv.chain {
		return errors.New("GG_SIGN_CHAIN")
	}
	return pv.inner.SignVote(chain, vote)
}
func (pv *SafePV) SignProposal(chain string, proposal *cmtproto.Proposal) error {
	pv.mu.Lock()
	defer pv.mu.Unlock()
	if pv.recovery != nil && (!pv.recoveryReady || pv.recovery.Err() != nil) {
		return errors.New("GG_SIGN_RECOVERY_NOT_READY")
	}
	if chain != pv.chain {
		return errors.New("GG_SIGN_CHAIN")
	}
	return pv.inner.SignProposal(chain, proposal)
}

func validatorSet(genesis Genesis) *types.ValidatorSet {
	validators := make([]*types.Validator, len(genesis.Validators))
	for i, encoded := range genesis.Validators {
		public, _ := hex.DecodeString(encoded)
		validators[i] = types.NewValidator(cmted.PubKey(public), genesisValidatorPower(genesis, i))
	}
	return types.NewValidatorSet(validators)
}

func genesisDoc(genesis Genesis) *types.GenesisDoc {
	parameters := types.DefaultConsensusParams()
	parameters.Block.MaxBytes = 64 * 1024
	if hasDagExecution(genesis) {
		parameters.Block.MaxBytes = 64 * 1024 * 1024
		parameters.Version.App = 2
		if genesis.DAGSegmented != nil {
			parameters.Version.App = 3
		}
		if genesis.FinancialDAG != nil {
			parameters.Version.App = 4
		}
	}
	parameters.Block.MaxGas = -1
	parameters.Evidence.MaxBytes = 8 * 1024
	parameters.Validator.PubKeyTypes = []string{cmted.KeyType}
	parameters.ABCI.VoteExtensionsEnableHeight = 0
	validators := make([]types.GenesisValidator, len(genesis.Validators))
	for i, encoded := range genesis.Validators {
		public, _ := hex.DecodeString(encoded)
		key := cmted.PubKey(public)
		validators[i] = types.GenesisValidator{Address: key.Address(), PubKey: key, Power: genesisValidatorPower(genesis, i), Name: fmt.Sprintf("GG validator %d", i+1)}
	}
	return &types.GenesisDoc{GenesisTime: time.Unix(genesis.GenesisTime, 0).UTC(), ChainID: genesis.ChainID, InitialHeight: 1,
		ConsensusParams: parameters, Validators: validators, AppState: canonical(genesis)}
}

func validateBootstrap(boot Bootstrap) error {
	if !validNativeResources(boot.Resources) {
		return errNativeResources
	}
	anchored := boot.Genesis.Membership != nil
	if (!anchored && (boot.Schema != "gg.consensus.bootstrap.v1" || boot.ExpectedFresh != nil)) ||
		(anchored && (boot.Schema != "gg.consensus.bootstrap.v2" || boot.ExpectedFresh == nil || len(boot.Peers) != 0)) || validateGenesis(boot.Genesis, boot.GenesisHash) != nil ||
		boot.ValidatorIndex < 0 || boot.ValidatorIndex > 3 || !pubPattern.MatchString(boot.ValidatorSeed) || !pubPattern.MatchString(boot.NodeSeed) ||
		!filepath.IsAbs(boot.Root) || boot.RPCPort < 1024 || boot.RPCPort > 65535 || boot.P2PPort < 1024 || boot.P2PPort > 65535 ||
		boot.RPCPort == boot.P2PPort || !anchored && len(boot.Peers) != 3 {
		return errors.New("GG_BOOTSTRAP_INVALID")
	}
	seen := map[string]bool{}
	ports := map[int]bool{boot.RPCPort: true, boot.P2PPort: true}
	idPattern := regexp.MustCompile(`^[0-9a-f]{40}$`)
	for _, peer := range boot.Peers {
		if peer.Host != "" || !idPattern.MatchString(peer.ID) || peer.Port < 1024 || peer.Port > 65535 || seen[peer.ID] || ports[peer.Port] {
			return errors.New("GG_BOOTSTRAP_PEERS")
		}
		seen[peer.ID] = true
		ports[peer.Port] = true
	}
	seed, _ := hex.DecodeString(boot.ValidatorSeed)
	public := ed25519.NewKeyFromSeed(seed).Public().(ed25519.PublicKey)
	if hex.EncodeToString(public) != boot.Genesis.Validators[boot.ValidatorIndex] {
		return errors.New("GG_BOOTSTRAP_VALIDATOR")
	}
	if anchored {
		member := boot.Genesis.Membership.Validators[boot.ValidatorIndex].Body
		nodeSeed, _ := hex.DecodeString(boot.NodeSeed)
		nodePublic := ed25519.NewKeyFromSeed(nodeSeed).Public().(ed25519.PublicKey)
		if member.NodeKey != hex.EncodeToString(nodePublic) || member.P2PPort != boot.P2PPort {
			return errors.New("GG_BOOTSTRAP_MEMBER_BINDING")
		}
	}
	return nil
}

func runNode(raw []byte, parentPID int) error {
	return runNodeWithOwnedLedger(raw, parentPID, nil, context.Background(), nil)
}

// prepared is an actual fully replayed, exclusively owned ledger, not a
// checkpoint, decoded state or authority flag. Normal startup passes nil.
func runNodeWithOwnedLedger(raw []byte, parentPID int, prepared *Ledger, startContext context.Context, readyHook func(*Ledger)) (failure error) {
	if startContext == nil || startContext.Err() != nil {
		return errOwnedRecovery
	}
	if prepared != nil {
		defer func() {
			if closeErr := prepared.Close(); closeErr != nil && failure == nil {
				failure = errFinancialStore
			}
		}()
	}
	boot, err := decodeNativeBootstrap(raw)
	if err != nil {
		return err
	}
	if err = bindNativeResources(boot.Resources); err != nil {
		return err
	}
	markerName, identity, err := nativeRootIdentity(boot)
	if err != nil {
		return err
	}
	root, err := filepath.Abs(boot.Root)
	if err != nil {
		return errors.New("GG_ROOT")
	}
	if boot.ExpectedFresh != nil {
		_, markerError := os.Lstat(filepath.Join(root, markerName))
		if !*boot.ExpectedFresh && markerError != nil {
			return errors.New("GG_NATIVE_HISTORY_REQUIRED")
		}
		if *boot.ExpectedFresh && !os.IsNotExist(markerError) {
			return errors.New("GG_NATIVE_FRESH_ROOT_REQUIRED")
		}
	}
	for _, folder := range []string{root, filepath.Join(root, "data"), filepath.Join(root, "config")} {
		if info, inspectErr := os.Lstat(folder); inspectErr == nil {
			if !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
				return errors.New("GG_ROOT_CREATE")
			}
		} else if !os.IsNotExist(inspectErr) {
			return errors.New("GG_ROOT_CREATE")
		}
		if os.MkdirAll(folder, 0700) != nil {
			return errors.New("GG_ROOT_CREATE")
		}
	}
	if recoveryFrom(startContext) != nil && startContext.Value(ownedRecoveryRootKey{}) == nil {
		anchor, e := openOwnedRecoveryRoot(root)
		if e != nil {
			return e
		}
		defer func() {
			if e := anchor.close(); e != nil && failure == nil {
				failure = e
			}
		}()
		startContext = context.WithValue(startContext, ownedRecoveryRootKey{}, anchor)
	}

	// Bind the root directory to one immutable public genesis, including restarts.
	marker := filepath.Join(root, markerName)
	freshRoot := false
	if _, inspectErr := os.Lstat(marker); inspectErr == nil {
		file, _, readErr := checkedSegmentFile(marker, false, 65536)
		if readErr != nil {
			return errors.New("GG_GENESIS_READ")
		}
		previous, readErr := io.ReadAll(io.LimitReader(file, 65537))
		closeErr := file.Close()
		if readErr != nil || closeErr != nil || len(previous) > 65536 {
			return errors.New("GG_GENESIS_READ")
		}
		if string(previous) != string(identity) {
			return errors.New("GG_ROOT_GENESIS_CHANGED")
		}
	} else if os.IsNotExist(inspectErr) {
		entries, readErr := os.ReadDir(filepath.Join(root, "data"))
		if readErr != nil || len(entries) != 0 {
			return errors.New("GG_ROOT_GENESIS_MISSING")
		}
		if atomicPublic(marker, identity) != nil {
			return errors.New("GG_GENESIS_SAVE")
		}
		freshRoot = true
	} else {
		return errors.New("GG_GENESIS_READ")
	}
	nodeSeed, _ := hex.DecodeString(boot.NodeSeed)
	nodeKey := &p2p.NodeKey{PrivKey: cmted.PrivKey(ed25519.NewKeyFromSeed(nodeSeed))}
	var pv types.PrivValidator
	if boot.observer != nil || boot.public != nil && boot.public.Role == "REPLICA" {
		pv, err = newNativeObserverPV(nodeKey.PrivKey.PubKey().Bytes())
	} else {
		validatorSeed, _ := hex.DecodeString(boot.ValidatorSeed)
		validatorKey := cmted.PrivKey(ed25519.NewKeyFromSeed(validatorSeed))
		statePath := filepath.Join(root, "data", "priv_validator_state.json")
		if freshRoot {
			pv, err = initializeSafePV(validatorKey, statePath, boot.Genesis.ChainID)
		} else {
			pv, err = newSafePV(validatorKey, statePath, boot.Genesis.ChainID)
		}
	}
	if err != nil {
		return err
	}
	if owned := recoveryFrom(startContext); owned != nil {
		if signer, ok := pv.(*SafePV); ok {
			signer.recovery = startContext
			signer.recoveryReady = false
		}
		if err = recoveryPhase(startContext, "VERIFY_HISTORY"); err != nil {
			return err
		}
	}
	var app *Ledger
	if prepared != nil {
		if (boot.observer == nil && (boot.public == nil || boot.public.Role != "REPLICA")) || prepared.financial == nil ||
			prepared.anchor != boot.GenesisHash || !bytes.Equal(canonical(prepared.genesis), canonical(boot.Genesis)) {
			return errFinancialSDKRecovery
		}
		app = prepared
	} else if hasDagExecution(boot.Genesis) {
		app, err = newDagEnabledLedgerContext(startContext, boot.Genesis, boot.GenesisHash, root, freshRoot)
	} else {
		app, err = newLedger(boot.Genesis, boot.GenesisHash, root)
	}
	if err != nil {
		return err
	}
	if prepared == nil {
		defer app.Close()
	}
	if recoveryFrom(startContext) != nil {
		if err = recoveryPhase(startContext, "VERIFY_SDK_BINDINGS"); err != nil {
			return err
		}
	}
	if boot.observer != nil && app.financial != nil {
		if err = prepareFinancialObserverSDKStartup(startContext, boot, app, root); err != nil {
			return err
		}
	}
	if boot.public != nil && boot.public.Role == "REPLICA" && app.financial != nil {
		if err = prepareFinancialObserverSDKStartup(startContext, boot, app, root); err != nil {
			return err
		}
	}
	if startContext.Err() != nil {
		return startContext.Err()
	}
	configuration := cfg.DefaultConfig().SetRoot(root)
	configuration.Moniker = fmt.Sprintf("GG test validator %d", boot.ValidatorIndex+1)
	if boot.observer != nil {
		configuration.Moniker = "GG native full observer"
	}
	configuration.DBBackend = "goleveldb"
	configuration.LogLevel = "error"
	configuration.PrivValidatorListenAddr = ""
	configuration.RPC.ListenAddress = fmt.Sprintf("tcp://127.0.0.1:%d", boot.RPCPort)
	configuration.RPC.Unsafe = false
	configuration.RPC.GRPCListenAddress = ""
	configuration.RPC.PprofListenAddress = ""
	configuration.RPC.MaxOpenConnections = 16
	configuration.RPC.MaxSubscriptionClients = 8
	configuration.RPC.MaxSubscriptionsPerClient = 4
	configuration.RPC.MaxRequestBatchSize = 16
	configuration.RPC.MaxBodyBytes = 256 * 1024
	configuration.RPC.MaxHeaderBytes = 8192
	configuration.RPC.TimeoutBroadcastTxCommit = 4 * time.Second
	configuration.P2P.ListenAddress = fmt.Sprintf("tcp://127.0.0.1:%d", boot.P2PPort)
	if boot.public != nil {
		configuration.P2P.ListenAddress = "tcp://" + net.JoinHostPort(boot.public.ListenHost, strconv.Itoa(boot.P2PPort))
	}
	if boot.Genesis.Membership != nil {
		if boot.observer != nil {
			configuration.P2P.ListenAddress = fmt.Sprintf("tcp://%s:%d", boot.observer.ObserverGrant.Body.Host, boot.P2PPort)
		} else {
			member := boot.Genesis.Membership.Validators[boot.ValidatorIndex].Body
			configuration.P2P.ListenAddress = fmt.Sprintf("tcp://%s:%d", member.Host, member.P2PPort)
		}
		configuration.FilterPeers = true
		for index, invite := range boot.Genesis.Membership.Validators {
			if boot.observer == nil && index == boot.ValidatorIndex {
				continue
			}
			body := invite.Body
			boot.Peers = append(boot.Peers, Peer{ID: membershipNodeID(body.NodeKey), Port: body.P2PPort, Host: body.Host})
		}
	}
	configuration.P2P.ExternalAddress = ""
	configuration.P2P.Seeds = ""
	configuration.P2P.PexReactor = false
	configuration.P2P.AddrBookStrict = false
	configuration.P2P.AllowDuplicateIP = true
	configuration.P2P.LibP2PConfig.Enabled = false
	configuration.P2P.MaxNumInboundPeers = 3
	configuration.P2P.MaxNumOutboundPeers = 3
	if boot.Genesis.Membership != nil {
		configuration.P2P.MaxNumInboundPeers = 3 + nativeObserverMax
	}
	if boot.observer != nil {
		configuration.P2P.MaxNumInboundPeers = 0
		configuration.P2P.MaxNumOutboundPeers = 4
	}
	if boot.public != nil {
		configuration.P2P.MaxNumInboundPeers = boot.public.MaxInbound
		configuration.P2P.MaxNumOutboundPeers = boot.public.MaxOutbound
	}
	configuration.P2P.HandshakeTimeout = 2 * time.Second
	configuration.P2P.DialTimeout = time.Second
	configuration.P2P.PersistentPeersMaxDialPeriod = time.Second
	peers := []string{}
	ids := []string{}
	for _, peer := range boot.Peers {
		host := peer.Host
		if host == "" {
			host = "127.0.0.1"
		}
		peers = append(peers, peer.ID+"@"+net.JoinHostPort(host, strconv.Itoa(peer.Port)))
		ids = append(ids, peer.ID)
	}
	configuration.P2P.PersistentPeers = strings.Join(peers, ",")
	configuration.P2P.PrivatePeerIDs = strings.Join(ids, ",")
	configuration.Mempool.Size = 256
	configuration.Mempool.MaxTxsBytes = 512 * 1024
	configuration.Mempool.MaxTxBytes = MaxTxBytes
	configuration.Mempool.CacheSize = 1024
	configuration.Mempool.WalPath = ""
	configuration.Mempool.Recheck = true
	if hasDagExecution(boot.Genesis) {
		configuration.RPC.MaxBodyBytes = 72 * 1024 * 1024
		configuration.Mempool.MaxTxBytes = DagMaxBatchWire
		configuration.Mempool.MaxTxsBytes = 2 * DagMaxBatchWire
	}
	// Real signed empty blocks keep the public topology observable at idle.
	// Transactions still wake consensus immediately; voting/quorum are unchanged.
	configuration.Consensus.CreateEmptyBlocks = true
	configuration.Consensus.CreateEmptyBlocksInterval = 2 * time.Second
	configuration.Consensus.TimeoutPropose = 400 * time.Millisecond
	configuration.Consensus.TimeoutProposeDelta = 100 * time.Millisecond
	configuration.Consensus.TimeoutPrevote = 200 * time.Millisecond
	configuration.Consensus.TimeoutPrevoteDelta = 100 * time.Millisecond
	configuration.Consensus.TimeoutPrecommit = 200 * time.Millisecond
	configuration.Consensus.TimeoutPrecommitDelta = 100 * time.Millisecond
	configuration.Consensus.TimeoutCommit = nativeResourceCommitWait(boot.Resources)
	configuration.Consensus.SkipTimeoutCommit = false
	if hasDagExecution(boot.Genesis) {
		// The legacy small-transfer demo's 400ms proposal window repeatedly
		// expires while peers receive and verify a multi-megabyte signed batch.
		// Budget actual data/verification work; quorum and signature checks stay
		// unchanged. These are latency budgets, not throughput claims.
		// A maximum 50000-TX batch takes several seconds of real signature
		// work at each phase. Short vote waits caused repeated nil rounds even
		// after the SDK's eager full-TX log allocation was removed. These are
		// upper waiting budgets: a healthy quorum still advances immediately.
		configuration.Consensus.TimeoutPropose = 30 * time.Second
		configuration.Consensus.TimeoutProposeDelta = 5 * time.Second
		configuration.Consensus.TimeoutPrevote = 15 * time.Second
		configuration.Consensus.TimeoutPrevoteDelta = 2 * time.Second
		configuration.Consensus.TimeoutPrecommit = 10 * time.Second
		configuration.Consensus.TimeoutPrecommitDelta = 2 * time.Second
	}
	configuration.Instrumentation.Prometheus = false
	configuration.StateSync.Enable = false
	configuration.Storage.DiscardABCIResponses = false
	if err = applyNativeSDKResourceRates(configuration, boot.Resources); err != nil {
		return err
	}
	if configuration.ValidateBasic() != nil {
		return errors.New("GG_NODE_CONFIG")
	}
	document := genesisDoc(boot.Genesis)
	provider := func() (*types.GenesisDoc, error) { return document, nil }
	creator := newOwnedLedgerClientCreator(app, startContext)
	if boot.Genesis.Membership != nil {
		peers, peerErr := newNativeObserverPeerPolicy(boot.Genesis, boot.GenesisHash, root)
		if peerErr != nil {
			return peerErr
		}
		creator = newOwnedLedgerClientCreatorWithPeers(app, peers, startContext)
	}
	if recoveryFrom(startContext) != nil {
		if err = recoveryPhase(startContext, "SDK_START"); err != nil {
			return err
		}
	}
	node, err := cmtnode.NewNodeWithContext(startContext, configuration, pv, nodeKey, creator, provider, cfg.DefaultDBProvider,
		cmtnode.DefaultMetricsProvider(configuration.Instrumentation), log.NewNopLogger())
	if err != nil {
		return errors.New("GG_NODE_CREATE")
	}
	if owned := recoveryFrom(startContext); owned != nil {
		backend, ok := app.financial.(*financialNativeApplication)
		if !ok {
			return errOwnedRecovery
		}
		if err = owned.sealSDKRecovery(backend.store.verifiedThrough); err != nil {
			return err
		}
	}
	if err = recoveryRootCurrent(startContext, root); err != nil {
		return err
	}
	if recoveryFrom(startContext) != nil {
		if err = inventoryOwnedNativeNamespace(startContext, root); err != nil {
			return err
		}
		if err = recoveryRootCurrent(startContext, root); err != nil {
			return err
		}
		if floor, ok := startContext.Value(ownedRecoveryFloorKey{}).(ownedRecoveryFloor); ok && floor.height > 0 {
			if err = checkOwnedRecoveryNodeFloor(startContext, boot, app, floor, node); err != nil {
				return err
			}
		}
		if signer, ok := pv.(*SafePV); ok {
			if err = checkOwnedRecoverySigner(signer, root, boot.Genesis.ChainID, node.BlockStore().Height()+1, false); err != nil {
				return err
			}
		}

	}
	if node.Start() != nil {
		return errors.New("GG_NODE_START")
	}
	defer func() {
		if node.IsRunning() {
			_ = node.Stop()
		}
		node.Wait()
	}()
	if startContext.Err() != nil {
		return startContext.Err()
	}
	// One bounded public attestation on the pipe owned by the controller. This
	// supports platforms where /proc/net socket ownership queries are denied;
	// it never substitutes for certificate/signature verification.
	readyBody := map[string]any{"schema": "gg.consensus.ready.v1", "chain_id": boot.Genesis.ChainID,
		"node_id": string(nodeKey.ID()), "pid": os.Getpid(), "rpc_port": boot.RPCPort, "p2p_port": boot.P2PPort}
	if boot.public != nil {
		readyBody["schema"] = "gg.consensus.protocol-ready.v1"
		readyBody["genesis_hash"] = boot.GenesisHash
		readyBody["p2p_host"] = boot.public.ListenHost
		readyBody["role"] = boot.public.Role
		readyBody["consensus_signing"] = boot.public.Role == "VALIDATOR"
		readyBody["state_sync"] = false
	}
	if boot.Genesis.Membership != nil {
		readyBody["schema"] = "gg.consensus.ready.v2"
		if boot.observer != nil {
			readyBody["schema"] = "gg.consensus.observer-ready.v1"
			readyBody["p2p_host"] = boot.observer.ObserverGrant.Body.Host
			readyBody["genesis_hash"] = boot.GenesisHash
			readyBody["consensus_signing"] = false
			readyBody["state_sync"] = false
		} else {
			readyBody["p2p_host"] = boot.Genesis.Membership.Validators[boot.ValidatorIndex].Body.Host
		}
	}
	if boot.Resources != nil {
		attestation, resourceErr := nativeResourceReady(boot.Resources, configuration.Consensus.TimeoutCommit)
		if resourceErr != nil {
			return resourceErr
		}
		readyBody["resources"] = attestation
		sdkFacts, sdkErr := nativeSDKResourceFacts(boot.Resources, configuration.P2P.SendRate, configuration.P2P.RecvRate)
		if sdkErr != nil {
			return sdkErr
		}
		for name, value := range sdkFacts {
			readyBody[name] = value
		}
	}
	if owned := recoveryFrom(startContext); owned != nil {
		completedHeight, cutErr := owned.auditedColdCut()
		if cutErr != nil {
			return cutErr
		}
		if err = recoveryWork(startContext, 1, &completedHeight); err != nil {
			return err
		}
		if err = owned.flushCompleted(startContext); err != nil {
			return err
		}
	}
	if owned := recoveryFrom(startContext); owned != nil && owned.reader != nil {
		// SDK, signer, app and root are verified, but SafePV remains CLOSED while
		// the exact foreground owner checks actual listener/RPC ownership.
		preparedBody := make(map[string]any, len(readyBody))
		for key, value := range readyBody {
			preparedBody[key] = value
		}
		preparedBody["schema"] = "gg.consensus.protocol-prepared.v1"
		preparedBody["consensus_signing"] = false
		if err = inventoryOwnedNativeNamespace(startContext, root); err != nil {
			return err
		}
		if err = recoveryRootCurrent(startContext, root); err != nil {
			return err
		}
		if err = owned.flushCompleted(startContext); err != nil {
			return err
		}
		if err = owned.freezeProgress(startContext); err != nil {
			return err
		}
		if err = writeOwnedRestoreFrame(owned.output, preparedBody); err != nil {
			return err
		}
		if err = owned.acknowledgePrepared(startContext); err != nil {
			return err
		}
		if err = recoveryRootCurrent(startContext, root); err != nil {
			return err
		}
		if signer, ok := pv.(*SafePV); ok {
			if err = checkOwnedRecoverySigner(signer, root, boot.Genesis.ChainID, node.BlockStore().Height()+1, true); err != nil {
				return err
			}
		}

	}
	if owned := recoveryFrom(startContext); owned != nil {
		if err = owned.freezeProgress(startContext); err != nil {
			return err
		}
	}
	ready := canonical(readyBody)
	if prepared != nil || recoveryFrom(startContext) != nil {
		// The retained-ledger handoff uses the same language-neutral private
		// frame encoding as its audit/restored records, including nested structs.
		ready = ownedRestoreCanonical(readyBody)
	}
	if len(ready) == 0 || len(ready) > 1024 {
		return errors.New("GG_READY_SIZE")
	}
	if _, err := fmt.Fprintln(os.Stdout, string(ready)); err != nil {
		return errors.New("GG_READY_PIPE")
	}
	if readyHook != nil {
		readyHook(app)
	}
	stop := make(chan os.Signal, 1)
	signal.Notify(stop, os.Interrupt, syscall.SIGTERM)
	parentLost := make(chan struct{}, 1)
	leaseStopped := make(chan struct{})
	if runtime.GOOS == "linux" || runtime.GOOS == "android" {
		go func() {
			ticker := time.NewTicker(500 * time.Millisecond)
			defer ticker.Stop()
			for {
				select {
				case <-leaseStopped:
					return
				case <-ticker.C:
					if parentPID <= 1 || os.Getppid() != parentPID {
						parentLost <- struct{}{}
						return
					}
				}
			}
		}()
	}
	var exitDeadline *time.Timer
	select {
	case <-startContext.Done():
	case <-stop:
	case <-parentLost:
		// The owning controller and its RAM seeds are gone. Give only this node
		// a short graceful-stop window, then guarantee its own process exits.
		exitDeadline = time.AfterFunc(3*time.Second, func() { os.Exit(0) })
	}
	close(leaseStopped)
	signal.Stop(stop)
	if node.IsRunning() {
		_ = node.Stop()
	}
	node.Wait()
	if exitDeadline != nil {
		exitDeadline.Stop()
	}
	return nil
}

func main() {
	parentPID := os.Getppid()
	if len(os.Args) == 2 && os.Args[1] == "protocol-owned-start" {
		if err := runOwnedProtocolStart(os.Stdin, os.Stdout, parentPID); err != nil {
			code := err.Error()
			if !regexp.MustCompile(`^GG_[A-Z0-9_]{1,100}$`).MatchString(code) {
				code = "GG_OWNED_RECOVERY_FAILED"
			}
			_, _ = fmt.Fprintln(os.Stdout, string(canonical(map[string]any{"error": code})))
			os.Exit(1)
		}
		return
	}
	if len(os.Args) == 2 && os.Args[1] == "financial-owned-restore-start" {
		if err := runFinancialOwnedRestoreStart(os.Stdin, os.Stdout, parentPID); err != nil {
			code := err.Error()
			if !regexp.MustCompile(`^GG_[A-Z0-9_]{1,100}$`).MatchString(code) {
				code = "GG_OWNED_RESTORE_START_FAILED"
			}
			_, _ = fmt.Fprintln(os.Stdout, string(canonical(map[string]any{"error": code})))
			os.Exit(1)
		}
		return
	}
	if len(os.Args) > 1 && os.Args[1] == "validate-protocol-genesis" {
		if len(os.Args) != 2 {
			_ = writeProtocolGenesisInvalid(os.Stdout)
			os.Exit(1)
		}
		if runProtocolGenesisValidation(os.Stdin, os.Stdout) != nil {
			os.Exit(1)
		}
		return
	}
	if len(os.Args) == 2 && os.Args[1] == "protocol-transport" {
		if runProtocolTransport(os.Stdin, os.Stdout) != nil {
			os.Exit(1)
		}
		return
	}
	if len(os.Args) == 2 && os.Args[1] == "verify-stream" {
		if runCommitteeVerifyStream(os.Stdin, os.Stdout) != nil {
			os.Exit(1)
		}
		return
	}
	limit := int64(512*1024 + 1)
	verify := len(os.Args) == 2 && os.Args[1] == "verify"
	archive := len(os.Args) == 2 && (os.Args[1] == "archive-export" || os.Args[1] == "archive-verify")
	financialArchive := len(os.Args) == 2 && (os.Args[1] == "financial-history-export" || os.Args[1] == "financial-history-verify" || os.Args[1] == "financial-history-restore")
	observerRestore := len(os.Args) == 2 && os.Args[1] == "financial-observer-restore"
	indexTransition := len(os.Args) == 2 && os.Args[1] == "index-transition"
	if verify {
		limit = 262145
	}
	if archive || financialArchive || indexTransition || observerRestore {
		limit = 512*1024 + 1
	}
	raw, err := io.ReadAll(io.LimitReader(os.Stdin, limit))
	if err != nil {
		os.Exit(1)
	}
	if verify {
		if len(raw) > 262144 || runVerify(raw) != nil {
			fmt.Fprintln(os.Stdout, `{"verified":false,"error":"GG_PROOF_INVALID"}`)
			os.Exit(1)
		}
		return
	}
	if archive || financialArchive || indexTransition || observerRestore {
		var result map[string]any
		var archiveErr error
		if observerRestore {
			result, archiveErr = runFinancialObserverRestoreCommand(raw)
		} else if financialArchive {
			result, archiveErr = runFinancialArchiveCommand(os.Args[1], raw)
		} else if indexTransition {
			result, archiveErr = runDagIndexTransitionCommand(raw)
		} else {
			result, archiveErr = runDagArchiveCommand(os.Args[1], raw)
		}
		if archiveErr != nil {
			code := archiveErr.Error()
			valid := len(code) > 0 && len(code) <= 128 && strings.HasPrefix(code, "GG_")
			for _, character := range code {
				if !(character >= 'A' && character <= 'Z' || character >= '0' && character <= '9' || character == '_') {
					valid = false
				}
			}
			if !valid {
				code = "GG_DAG_ARCHIVE_FAILED"
			}
			fmt.Fprintln(os.Stdout, string(canonical(map[string]any{"verified": false, "error": code})))
			os.Exit(1)
		}
		fmt.Fprintln(os.Stdout, string(canonical(result)))
		return
	}
	if len(os.Args) != 1 || len(raw) > 65536 || runNode(raw, parentPID) != nil {
		fmt.Fprintln(os.Stderr, "GG_CONSENSUS_START_FAILED")
		os.Exit(1)
	}
}

// Keep context import explicit for SDK API compatibility diagnostics.
var _ = context.Background

// The original SafePV journal is never imported, reconstructed or reset. Pin
// its actual no-follow file bytes+inode before node.Start, then require exact
// identity after the foreground owner's one ACK before enabling inner.Sign*.
func checkOwnedRecoverySigner(pv *SafePV, root, chain string, maxHeight int64, enable bool) (failure error) {
	pv.mu.Lock()
	defer pv.mu.Unlock()
	if pv.recovery == nil || pv.recovery.Err() != nil {
		return errors.New("GG_SIGN_RECOVERY_NOT_READY")
	}
	finish, err := recoveryHistoryDirectory(pv.recovery, filepath.Join(root, "data"))
	if err != nil {
		return errors.New("GG_SIGN_STATE_CHANGED")
	}
	defer func() {
		if finish() != nil {
			pv.recoveryReady = false
			failure = errors.New("GG_SIGN_STATE_CHANGED")
		}
	}()
	path := filepath.Join(root, "data", "priv_validator_state.json")
	file, info, err := financialRecoveryOpenFile(path)
	if err != nil {
		return errors.New("GG_SIGN_STATE_CHANGED")
	}
	raw, err := io.ReadAll(io.LimitReader(file, 8193))
	closeErr := file.Close()
	if err != nil || closeErr != nil || len(raw) > 8192 {
		return errors.New("GG_SIGN_STATE_CHANGED")
	}
	var fields map[string]json.RawMessage
	if decodeStrict(raw, &fields) != nil || len(fields) < 3 || len(fields) > 5 {
		return errors.New("GG_SIGN_STATE_CHANGED")
	}
	for name := range fields {
		if name != "height" && name != "round" && name != "step" && name != "signature" && name != "signbytes" {
			return errors.New("GG_SIGN_STATE_CHANGED")
		}
	}
	candidate := privval.NewFilePV(pv.inner.Key.PrivKey, "", path)
	if fields["height"] == nil || fields["round"] == nil || fields["step"] == nil || cmtjson.Unmarshal(raw, &candidate.LastSignState) != nil || !validLastSignState(candidate.LastSignState, pv.inner.Key.PubKey, chain) || candidate.LastSignState.Height > maxHeight || !bytes.Equal(canonical(candidate.LastSignState), canonical(pv.inner.LastSignState)) {
		return errors.New("GG_SIGN_STATE_CHANGED")
	}
	if pv.recoveryState == nil {
		if enable {
			return errors.New("GG_SIGN_STATE_CHANGED")
		}
		pv.recoveryState = append([]byte(nil), raw...)
		pv.recoveryStateInfo = info
	} else if !bytes.Equal(raw, pv.recoveryState) || !os.SameFile(info, pv.recoveryStateInfo) {
		return errors.New("GG_SIGN_STATE_CHANGED")
	}
	if enable {
		if pv.recovery.Err() != nil {
			return errors.New("GG_SIGN_RECOVERY_NOT_READY")
		}
		pv.recoveryReady = true
	}
	return nil
}
