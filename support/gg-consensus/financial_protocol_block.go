package main

// The producer signs an immutable payment core. A bounded mining wrapper may
// change when the epoch/target changes without changing the block identity,
// account signatures, causal sequence or user payment intent.
import (
	"context"
	"encoding/hex"
)

type financialProtocolBlockBody struct {
	CreatedAtNs uint64     `json:"created_at_ns,string"`
	Epoch       uint64     `json:"epoch,string"`
	GenesisHash string     `json:"genesis_hash"`
	Parents     []string   `json:"parents"`
	PaymentRoot string     `json:"payment_root"`
	Payments    []Envelope `json:"payments"`
	ProducerKey string     `json:"producer_key"`
	Rank        uint64     `json:"rank,string"`
	Schema      string     `json:"schema"`
	Sequence    uint64     `json:"sequence,string"`
	SourceHash  string     `json:"source_hash"`
}

type financialProtocolBlock struct {
	Body      financialProtocolBlockBody `json:"body"`
	Signature string                     `json:"signature"`
	Work      miningWorkSolution         `json:"work"`
}

type financialProtocolCore struct {
	Body      financialProtocolBlockBody `json:"body"`
	Signature string                     `json:"signature"`
}

func financialProtocolBlockID(block financialProtocolBlock) string {
	return hashHex(append([]byte(financialDomain+"DAG-BLOCK-CORE-v2\x00"), canonical(financialProtocolCore{Body: block.Body, Signature: block.Signature})...))
}

func (protocol *financialProtocolExecution) expectedBlockWork(ctx context.Context, block financialProtocolBlock, anchor string) (miningWorkJob, error) {
	producer, err := protocol.producer(ctx, block.Body.ProducerKey, protocol.genesis)
	if err != nil {
		return miningWorkJob{}, err
	}
	if protocol.state.WorkAnchorHeight > dagSegmentCounterMax-protocol.genesis.Protocol.MaxWorkHeights {
		return miningWorkJob{}, errFinancialProtocol
	}
	id := financialProtocolBlockID(block)
	job := miningWorkJob{Epoch: protocol.state.Economics.NextEpoch, ExpiresHeight: protocol.state.WorkAnchorHeight + protocol.genesis.Protocol.MaxWorkHeights,
		Genesis: anchor, JobNonce: hashHex([]byte("GG-FINANCIAL-WORK-NONCE-v1\x00" + id + producer.Invite.Body.Nonce)), NetworkTarget: protocol.state.WorkTarget,
		PayloadRoot: id, RewardAccount: producer.Invite.Body.RewardAccount, Schema: "gg.financial.mining-job.v1", ShareTarget: block.Work.Job.ShareTarget,
		StateHeight: protocol.state.WorkAnchorHeight, StateRoot: protocol.state.WorkAnchorRoot, WorkerKey: block.Work.Job.WorkerKey}
	if !job.valid() {
		return job, errMiningWork
	}
	return job, nil
}

func decodeFinancialProtocolBlock(ctx context.Context, raw []byte, source financialDagSource, anchor string, epoch uint64, when int64, protocols ...*financialProtocolExecution) (financialDagRecord, error) {
	if err := ctx.Err(); err != nil {
		return financialDagRecord{}, err
	}
	var block financialProtocolBlock
	if !source.hasProtocol() || len(raw) == 0 || len(raw) > DagMaxWire || decodeStrictLimited(raw, &block, financialMaxTransactions, 64) != nil || !streamCanonicalEqual(raw, block) {
		return financialDagRecord{}, errFinancialProtocol
	}
	body := block.Body
	start, _ := dagDecimalNs(source.StartedAtNs)
	if body.Schema != "gg.financial-dag.block.v2" || body.GenesisHash != anchor || body.SourceHash != source.hash() || !financialAccountAddress(body.ProducerKey) ||
		body.Epoch == 0 || body.Epoch > epoch || body.Sequence == 0 || body.Sequence > dagSegmentCounterMax || body.Rank == 0 || body.Rank > dagSegmentCounterMax ||
		body.CreatedAtNs < uint64(start) || body.CreatedAtNs > dagSegmentCounterMax-5000000000 || when < 0 || when > int64(dagSegmentCounterMax)-5000000000 ||
		when > 0 && body.CreatedAtNs > uint64(when)+5000000000 || body.Payments == nil || len(body.Payments) > financialMaxTransactions ||
		len(body.Parents) == 0 || len(body.Parents) > DagMaxParents || body.PaymentRoot != financialDagPaymentRoot(body.Payments) {
		return financialDagRecord{}, errFinancialProtocol
	}
	for index, parent := range body.Parents {
		if !pubPattern.MatchString(parent) || index > 0 && parent <= body.Parents[index-1] {
			return financialDagRecord{}, errFinancialProtocol
		}
	}
	key, _ := hex.DecodeString(body.ProducerKey)
	signature, err := hex.DecodeString(block.Signature)
	if err != nil || len(block.Signature) != 128 || hex.EncodeToString(signature) != block.Signature ||
		!verifyTransactionSignature(key, append([]byte(financialDomain+"DAG-BLOCK-SIGN-v2\x00"), canonical(body)...), signature) {
		return financialDagRecord{}, errFinancialProtocol
	}
	record := financialDagRecord{Hash: financialProtocolBlockID(block), Raw: raw, Protocol: &block,
		Block: financialDagBlock{Body: financialDagBlockBody{CreatedAtNs: body.CreatedAtNs, Epoch: body.Epoch, GenesisHash: body.GenesisHash, Parents: body.Parents,
			PaymentRoot: body.PaymentRoot, Payments: body.Payments, Producer: -1, Rank: body.Rank, Schema: body.Schema, Sequence: body.Sequence, SourceHash: body.SourceHash}, Signature: block.Signature}}
	if len(protocols) > 1 {
		return financialDagRecord{}, errFinancialProtocol
	}
	if len(protocols) == 1 && protocols[0] != nil {
		protocol := protocols[0]
		expected, err := protocol.expectedBlockWork(ctx, block, anchor)
		if err != nil {
			return financialDagRecord{}, err
		}
		share, err := verifyMiningWork(expected, block.Work, protocol.height)
		if err != nil || !share.networkWork {
			return financialDagRecord{}, errMiningWork
		}
		record.workShare = &share
	}
	// Core-only decoding is used for already authenticated historical receipts.
	// Admission always requires the separately verified owned protocol context.
	return record, ctx.Err()
}
