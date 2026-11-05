package main

// Work/share primitives for the integrated mining and pool path. The expected
// job is derived by the native application, not supplied as authority by a
// miner. Work admission, monetary settlement and BFT votes remain separate.
import (
	"bytes"
	"context"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"errors"
	"math/big"
	"sort"
	"sync"
)

var errMiningWork = errors.New("GG_MINING_WORK_INVALID")

type miningWorkJob struct {
	Epoch         uint64 `json:"epoch,string"`
	ExpiresHeight uint64 `json:"expires_height,string"`
	Genesis       string `json:"genesis_hash"`
	JobNonce      string `json:"job_nonce"`
	NetworkTarget string `json:"network_target"`
	PayloadRoot   string `json:"payload_root"`
	RewardAccount string `json:"reward_account"`
	Schema        string `json:"schema"`
	ShareTarget   string `json:"share_target"`
	StateHeight   uint64 `json:"state_height,string"`
	StateRoot     string `json:"state_root"`
	WorkerKey     string `json:"worker_key"`
}

type miningWorkSolution struct {
	Job       miningWorkJob `json:"job"`
	Nonce     uint64        `json:"nonce,string"`
	Schema    string        `json:"schema"`
	Signature string        `json:"signature"`
}

type verifiedMiningShare struct {
	epoch, stateHeight, expiresHeight  uint64
	genesis, identifier, rewardAccount string
	weight                             *big.Int
	networkWeight                      *big.Int
	networkWork, verified              bool
}

func (job miningWorkJob) valid() bool {
	if job.Schema != "gg.financial.mining-job.v1" || job.ExpiresHeight <= job.StateHeight ||
		job.ExpiresHeight-job.StateHeight > 65536 || !financialAccountAddress(job.WorkerKey) || !financialAccountAddress(job.RewardAccount) {
		return false
	}
	for _, value := range []string{job.Genesis, job.JobNonce, job.NetworkTarget, job.ShareTarget, job.PayloadRoot, job.StateRoot} {
		if !pubPattern.MatchString(value) {
			return false
		}
	}
	network, _ := hex.DecodeString(job.NetworkTarget)
	share, _ := hex.DecodeString(job.ShareTarget)
	return new(big.Int).SetBytes(network).Sign() > 0 && bytes.Compare(network, share) <= 0 && len(canonical(job)) <= 4096
}

func miningWorkHeader(job miningWorkJob) []byte {
	return append([]byte("GG-FINANCIAL-MINING-WORK-v1\x00"), canonical(job)...)
}

func miningWorkDigest(header []byte, nonce uint64) [32]byte {
	buffer := make([]byte, len(header)+8)
	copy(buffer, header)
	binary.BigEndian.PutUint64(buffer[len(header):], nonce)
	return sha256.Sum256(buffer)
}

func miningSignatureMessage(digest [32]byte) []byte {
	return append([]byte("GG-FINANCIAL-MINING-OWNER-v1\x00"), digest[:]...)
}

func verifyMiningWork(expected miningWorkJob, solution miningWorkSolution, currentHeight uint64) (verifiedMiningShare, error) {
	if !expected.valid() || solution.Schema != "gg.financial.mining-solution.v1" || solution.Job != expected ||
		currentHeight < expected.StateHeight || currentHeight > expected.ExpiresHeight {
		return verifiedMiningShare{}, errMiningWork
	}
	digest := miningWorkDigest(miningWorkHeader(expected), solution.Nonce)
	shareTarget, _ := hex.DecodeString(expected.ShareTarget)
	networkTarget, _ := hex.DecodeString(expected.NetworkTarget)
	key, _ := hex.DecodeString(expected.WorkerKey)
	signature, err := hex.DecodeString(solution.Signature)
	if err != nil || len(solution.Signature) != 128 || hex.EncodeToString(signature) != solution.Signature || bytes.Compare(digest[:], shareTarget) > 0 ||
		!verifyTransactionSignature(key, miningSignatureMessage(digest), signature) {
		return verifiedMiningShare{}, errMiningWork
	}
	denominator := new(big.Int).Add(new(big.Int).SetBytes(shareTarget), big.NewInt(1))
	weight := new(big.Int).Quo(new(big.Int).Lsh(big.NewInt(1), 256), denominator)
	networkDenominator := new(big.Int).Add(new(big.Int).SetBytes(networkTarget), big.NewInt(1))
	networkWeight := new(big.Int).Quo(new(big.Int).Lsh(big.NewInt(1), 256), networkDenominator)
	return verifiedMiningShare{epoch: expected.Epoch, stateHeight: expected.StateHeight, expiresHeight: expected.ExpiresHeight, genesis: expected.Genesis,
		identifier: hex.EncodeToString(digest[:]), rewardAccount: expected.RewardAccount, weight: weight,
		networkWeight: networkWeight, networkWork: bytes.Compare(digest[:], networkTarget) <= 0, verified: true}, nil
}

// Mining is bounded by both nonce count and cancellation. Returning exhausted
// never wraps the nonce to zero. No goroutine, key creation or network starts.
func mineFinancialWork(ctx context.Context, job miningWorkJob, key ed25519.PrivateKey, start uint64, attempts uint32) (*miningWorkSolution, uint64, bool, error) {
	if !job.valid() || len(key) != ed25519.PrivateKeySize || attempts == 0 || attempts > 1<<20 || start > economicMaxUint-uint64(attempts-1) ||
		hex.EncodeToString(key[32:]) != job.WorkerKey || !bytes.Equal(ed25519.NewKeyFromSeed(key[:32]), key) {
		return nil, start, false, errMiningWork
	}
	header := miningWorkHeader(job)
	target, _ := hex.DecodeString(job.ShareTarget)
	buffer := make([]byte, len(header)+8)
	copy(buffer, header)
	for offset := uint64(0); offset < uint64(attempts); offset++ {
		nonce := start + offset
		if offset%256 == 0 && ctx.Err() != nil {
			return nil, nonce, false, ctx.Err()
		}
		binary.BigEndian.PutUint64(buffer[len(header):], nonce)
		digest := sha256.Sum256(buffer)
		if bytes.Compare(digest[:], target) <= 0 {
			signature := ed25519.Sign(key, miningSignatureMessage(digest))
			solution := &miningWorkSolution{Job: job, Nonce: nonce, Schema: "gg.financial.mining-solution.v1", Signature: hex.EncodeToString(signature)}
			if nonce == economicMaxUint {
				return solution, nonce, true, nil
			}
			return solution, nonce + 1, false, nil
		}
	}
	last := start + uint64(attempts-1)
	if last == economicMaxUint {
		return nil, last, true, nil
	}
	return nil, last + 1, false, nil
}

type miningPoolShares struct {
	mu      sync.Mutex
	epoch   uint64
	genesis string
	shares  map[string]string
	weights map[string]*big.Int
}

func newMiningPoolShares(genesis string, epoch uint64) (*miningPoolShares, error) {
	if !pubPattern.MatchString(genesis) {
		return nil, errMiningWork
	}
	return &miningPoolShares{epoch: epoch, genesis: genesis, shares: make(map[string]string), weights: make(map[string]*big.Int)}, nil
}

func (pool *miningPoolShares) accept(share verifiedMiningShare, currentHeight uint64) error {
	if pool == nil {
		return errMiningWork
	}
	pool.mu.Lock()
	defer pool.mu.Unlock()
	if !share.verified || share.genesis != pool.genesis || share.epoch != pool.epoch || currentHeight < share.stateHeight || currentHeight > share.expiresHeight ||
		share.weight == nil || share.weight.Sign() <= 0 || share.weight.BitLen() > 256 || !financialAccountAddress(share.rewardAccount) ||
		!pubPattern.MatchString(share.identifier) || len(pool.shares) >= economicMaxRecipients {
		return errMiningWork
	}
	if _, exists := pool.shares[share.identifier]; exists {
		return errors.New("GG_MINING_SHARE_ALREADY_ACCEPTED")
	}
	weight := new(big.Int)
	if existing := pool.weights[share.rewardAccount]; existing != nil {
		weight.Set(existing)
	}
	weight.Add(weight, share.weight)
	if weight.BitLen() > 512 {
		return errMiningWork
	}
	pool.shares[share.identifier] = share.rewardAccount
	pool.weights[share.rewardAccount] = weight
	return nil
}

func (pool *miningPoolShares) allocation(reward uint64, operator string, commissionBPS uint32) ([]economicCredit, error) {
	if pool == nil {
		return nil, errMiningWork
	}
	pool.mu.Lock()
	defer pool.mu.Unlock()
	addresses := make([]string, 0, len(pool.weights))
	for address := range pool.weights {
		addresses = append(addresses, address)
	}
	sort.Strings(addresses)
	weights := make([]economicWeight, 0, len(addresses))
	for _, address := range addresses {
		weights = append(weights, economicWeight{Address: address, Weight: pool.weights[address].String()})
	}
	return economicPoolAllocation(reward, operator, commissionBPS, weights)
}
