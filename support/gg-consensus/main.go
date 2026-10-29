// GG's disposable native ledger on the maintained CometBFT consensus engine.
// Bootstrap secrets enter only through stdin; no validator/node key is saved.
package main

import (
	"context"
	"crypto/ed25519"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"os"
	"os/signal"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
	"sync"
	"syscall"
	"time"

	cfg "github.com/cometbft/cometbft/config"
	cmtcrypto "github.com/cometbft/cometbft/crypto"
	cmted "github.com/cometbft/cometbft/crypto/ed25519"
	cmtjson "github.com/cometbft/cometbft/libs/json"
	"github.com/cometbft/cometbft/libs/log"
	cmtnode "github.com/cometbft/cometbft/node"
	"github.com/cometbft/cometbft/p2p"
	"github.com/cometbft/cometbft/privval"
	cmtproto "github.com/cometbft/cometbft/proto/tendermint/types"
	"github.com/cometbft/cometbft/proxy"
	"github.com/cometbft/cometbft/types"
)

type Peer struct {
	ID   string `json:"id"`
	Port int    `json:"port"`
}
type Bootstrap struct {
	Schema         string  `json:"schema"`
	Genesis        Genesis `json:"genesis"`
	GenesisHash    string  `json:"genesis_hash"`
	ValidatorIndex int     `json:"validator_index"`
	ValidatorSeed  string  `json:"validator_seed"`
	NodeSeed       string  `json:"node_seed"`
	Root           string  `json:"root"`
	RPCPort        int     `json:"rpc_port"`
	P2PPort        int     `json:"p2p_port"`
	Peers          []Peer  `json:"peers"`
}

type SafePV struct {
	mu    sync.Mutex
	inner *privval.FilePV
	chain string
}

func newSafePV(key cmtcrypto.PrivKey, path, chain string) (*SafePV, error) {
	pv := privval.NewFilePV(key, "", path)
	if raw, err := os.ReadFile(path); err == nil {
		if len(raw) > 8192 {
			return nil, errors.New("GG_SIGN_STATE_SIZE")
		}
		// Decode into the existing struct to retain its unexported public-state path.
		if cmtjson.Unmarshal(raw, &pv.LastSignState) != nil {
			return nil, errors.New("GG_SIGN_STATE_INVALID")
		}
	} else if !os.IsNotExist(err) {
		return nil, errors.New("GG_SIGN_STATE_READ")
	}
	return &SafePV{inner: pv, chain: chain}, nil
}

func (pv *SafePV) GetPubKey() (cmtcrypto.PubKey, error) {
	pv.mu.Lock()
	defer pv.mu.Unlock()
	return pv.inner.GetPubKey()
}
func (pv *SafePV) SignVote(chain string, vote *cmtproto.Vote) error {
	pv.mu.Lock()
	defer pv.mu.Unlock()
	if chain != pv.chain {
		return errors.New("GG_SIGN_CHAIN")
	}
	return pv.inner.SignVote(chain, vote)
}
func (pv *SafePV) SignProposal(chain string, proposal *cmtproto.Proposal) error {
	pv.mu.Lock()
	defer pv.mu.Unlock()
	if chain != pv.chain {
		return errors.New("GG_SIGN_CHAIN")
	}
	return pv.inner.SignProposal(chain, proposal)
}

func validatorSet(genesis Genesis) *types.ValidatorSet {
	validators := make([]*types.Validator, 4)
	for i, encoded := range genesis.Validators {
		public, _ := hex.DecodeString(encoded)
		validators[i] = types.NewValidator(cmted.PubKey(public), 1)
	}
	return types.NewValidatorSet(validators)
}

func genesisDoc(genesis Genesis) *types.GenesisDoc {
	parameters := types.DefaultConsensusParams()
	parameters.Block.MaxBytes = 64 * 1024
	parameters.Block.MaxGas = -1
	parameters.Evidence.MaxBytes = 8 * 1024
	parameters.Validator.PubKeyTypes = []string{cmted.KeyType}
	parameters.ABCI.VoteExtensionsEnableHeight = 0
	validators := make([]types.GenesisValidator, 4)
	for i, encoded := range genesis.Validators {
		public, _ := hex.DecodeString(encoded)
		key := cmted.PubKey(public)
		validators[i] = types.GenesisValidator{Address: key.Address(), PubKey: key, Power: 1, Name: fmt.Sprintf("GG validator %d", i+1)}
	}
	return &types.GenesisDoc{GenesisTime: time.Unix(genesis.GenesisTime, 0).UTC(), ChainID: genesis.ChainID, InitialHeight: 1,
		ConsensusParams: parameters, Validators: validators, AppState: canonical(genesis)}
}

func validateBootstrap(boot Bootstrap) error {
	if boot.Schema != "gg.consensus.bootstrap.v1" || validateGenesis(boot.Genesis, boot.GenesisHash) != nil ||
		boot.ValidatorIndex < 0 || boot.ValidatorIndex > 3 || !pubPattern.MatchString(boot.ValidatorSeed) || !pubPattern.MatchString(boot.NodeSeed) ||
		!filepath.IsAbs(boot.Root) || boot.RPCPort < 1024 || boot.RPCPort > 65535 || boot.P2PPort < 1024 || boot.P2PPort > 65535 ||
		boot.RPCPort == boot.P2PPort || len(boot.Peers) != 3 {
		return errors.New("GG_BOOTSTRAP_INVALID")
	}
	seen := map[string]bool{}
	ports := map[int]bool{boot.RPCPort: true, boot.P2PPort: true}
	idPattern := regexp.MustCompile(`^[0-9a-f]{40}$`)
	for _, peer := range boot.Peers {
		if !idPattern.MatchString(peer.ID) || peer.Port < 1024 || peer.Port > 65535 || seen[peer.ID] || ports[peer.Port] {
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
	return nil
}

func runNode(raw []byte, parentPID int) error {
	var boot Bootstrap
	if len(raw) > 65536 || decodeStrict(raw, &boot) != nil || validateBootstrap(boot) != nil {
		return errors.New("GG_BOOTSTRAP_INVALID")
	}
	root, err := filepath.Abs(boot.Root)
	if err != nil {
		return errors.New("GG_ROOT")
	}
	for _, folder := range []string{root, filepath.Join(root, "data"), filepath.Join(root, "config")} {
		if os.MkdirAll(folder, 0700) != nil {
			return errors.New("GG_ROOT_CREATE")
		}
	}
	// Bind the root directory to one immutable public genesis, including restarts.
	marker := filepath.Join(root, "gg-public-genesis.json")
	if previous, err := os.ReadFile(marker); err == nil {
		if string(previous) != string(canonical(boot.Genesis)) {
			return errors.New("GG_ROOT_GENESIS_CHANGED")
		}
	} else if os.IsNotExist(err) {
		if atomicPublic(marker, canonical(boot.Genesis)) != nil {
			return errors.New("GG_GENESIS_SAVE")
		}
	} else {
		return errors.New("GG_GENESIS_READ")
	}
	validatorSeed, _ := hex.DecodeString(boot.ValidatorSeed)
	nodeSeed, _ := hex.DecodeString(boot.NodeSeed)
	validatorKey := cmted.PrivKey(ed25519.NewKeyFromSeed(validatorSeed))
	nodeKey := &p2p.NodeKey{PrivKey: cmted.PrivKey(ed25519.NewKeyFromSeed(nodeSeed))}
	pv, err := newSafePV(validatorKey, filepath.Join(root, "data", "priv_validator_state.json"), boot.Genesis.ChainID)
	if err != nil {
		return err
	}
	app, err := newLedger(boot.Genesis, boot.GenesisHash, root)
	if err != nil {
		return err
	}
	configuration := cfg.DefaultConfig().SetRoot(root)
	configuration.Moniker = fmt.Sprintf("GG test validator %d", boot.ValidatorIndex+1)
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
	configuration.P2P.ExternalAddress = ""
	configuration.P2P.Seeds = ""
	configuration.P2P.PexReactor = false
	configuration.P2P.AddrBookStrict = false
	configuration.P2P.AllowDuplicateIP = true
	configuration.P2P.LibP2PConfig.Enabled = false
	configuration.P2P.MaxNumInboundPeers = 3
	configuration.P2P.MaxNumOutboundPeers = 3
	configuration.P2P.HandshakeTimeout = 2 * time.Second
	configuration.P2P.DialTimeout = time.Second
	configuration.P2P.PersistentPeersMaxDialPeriod = time.Second
	peers := []string{}
	ids := []string{}
	for _, peer := range boot.Peers {
		peers = append(peers, fmt.Sprintf("%s@127.0.0.1:%d", peer.ID, peer.Port))
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
	configuration.Consensus.TimeoutCommit = 100 * time.Millisecond
	configuration.Instrumentation.Prometheus = false
	configuration.StateSync.Enable = false
	configuration.Storage.DiscardABCIResponses = false
	if configuration.ValidateBasic() != nil {
		return errors.New("GG_NODE_CONFIG")
	}
	document := genesisDoc(boot.Genesis)
	provider := func() (*types.GenesisDoc, error) { return document, nil }
	node, err := cmtnode.NewNode(configuration, pv, nodeKey, proxy.NewLocalClientCreator(app), provider, cfg.DefaultDBProvider,
		cmtnode.DefaultMetricsProvider(configuration.Instrumentation), log.NewNopLogger())
	if err != nil {
		return errors.New("GG_NODE_CREATE")
	}
	if node.Start() != nil {
		return errors.New("GG_NODE_START")
	}
	// One bounded public attestation on the pipe owned by the controller. This
	// supports platforms where /proc/net socket ownership queries are denied;
	// it never substitutes for certificate/signature verification.
	ready := canonical(map[string]any{"schema": "gg.consensus.ready.v1", "chain_id": boot.Genesis.ChainID,
		"node_id": string(nodeKey.ID()), "pid": os.Getpid(), "rpc_port": boot.RPCPort, "p2p_port": boot.P2PPort})
	if len(ready) > 1024 {
		return errors.New("GG_READY_SIZE")
	}
	if _, err := fmt.Fprintln(os.Stdout, string(ready)); err != nil {
		return errors.New("GG_READY_PIPE")
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
	limit := int64(65537)
	verify := len(os.Args) == 2 && os.Args[1] == "verify"
	if verify {
		limit = 262145
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
	if len(os.Args) != 1 || len(raw) > 65536 || runNode(raw, parentPID) != nil {
		fmt.Fprintln(os.Stderr, "GG_CONSENSUS_START_FAILED")
		os.Exit(1)
	}
}

// Keep context import explicit for SDK API compatibility diagnostics.
var _ = context.Background
