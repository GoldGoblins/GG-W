package main

// Registry/governance operations execute inside the same native journaled
// transition as money and block admission. They are never financial blocks,
// and transport pairing or a UI flag grants none of these permissions.
import (
	"bytes"
	"context"
	"encoding/hex"
	"errors"
	"strconv"
)

const protocolMaxOperations = 32

type protocolCancelBody struct {
	Genesis  string `json:"genesis_hash"`
	Nonce    uint64 `json:"nonce,string"`
	Replaces string `json:"replaces"`
	Schema   string `json:"schema"`
	Sender   string `json:"sender"`
}

// A receipt binds the exact account-signed authorization, independently of
// replaceable registration work or SDK envelope metadata. An absent receipt
// does not prove that an alternative payment did not consume this nonce.
type protocolOperationReceipt struct {
	Authorization string `json:"authorization_id"`
	Fee           string `json:"fee_atomic"`
	Height        uint64 `json:"height,string"`
	Kind          string `json:"kind"`
	Nonce         uint64 `json:"nonce,string"`
	Operation     string `json:"operation_root"`
	Schema        string `json:"schema"`
	Sender        string `json:"sender"`
}

func protocolOperationReceiptKey(sender string, nonce uint64) string {
	return hashHex([]byte("GG-FINANCIAL-OPERATION-RECEIPT-KEY-v1\x00" + sender + "\x00" + strconv.FormatUint(nonce, 10)))
}

func protocolFeeAuthorizationID(fee protocolFeeAuthorization) string {
	return hashHex(append([]byte("GG-FINANCIAL-PROTOCOL-AUTHORIZATION-v1\x00"), canonical(fee)...))
}

func validProtocolOperationReceipt(receipt protocolOperationReceipt, state State, key string) bool {
	_, feeOK := economicAmount(receipt.Fee)
	return receipt.Schema == "gg.financial.operation-receipt.v1" && financialAccountAddress(receipt.Sender) &&
		pubPattern.MatchString(receipt.Authorization) && pubPattern.MatchString(receipt.Operation) && feeOK &&
		receipt.Height > 0 && receipt.Height <= uint64(state.Height) && receipt.Nonce < economicMaxUint &&
		(receipt.Kind == "PRODUCER_REGISTERED" || receipt.Kind == "COMMITTEE_DECIDED" || receipt.Kind == "NONCE_CANCELLED") &&
		protocolOperationReceiptKey(receipt.Sender, receipt.Nonce) == key
}

func (execution *financialDagExecution) recordProtocolOperation(ctx context.Context, operation protocolOperation) error {
	root, err := protocolOperationRoot(operation)
	if err != nil {
		return err
	}
	fee, err := economicMinimumFee(execution.genesis.Protocol.Economics, uint64(len(canonical(operation))))
	if err != nil {
		return err
	}
	body := operation.Fee.Body
	kind := "NONCE_CANCELLED"
	if operation.Producer != nil {
		kind = "PRODUCER_REGISTERED"
	}
	if operation.Committee != nil {
		kind = "COMMITTEE_DECIDED"
	}
	receipt := protocolOperationReceipt{Authorization: protocolFeeAuthorizationID(operation.Fee), Fee: strconv.FormatUint(fee, 10), Height: execution.money.Protocol.height,
		Kind: kind, Nonce: body.Nonce, Operation: root, Schema: "gg.financial.operation-receipt.v1", Sender: body.Sender}
	key := protocolOperationReceiptKey(body.Sender, body.Nonce)
	tree := execution.money.Protocol.operations
	if _, exists, err := tree.get(ctx, key); err != nil {
		return err
	} else if exists {
		return errFinancialProtocol
	}
	tree, err = tree.set(ctx, key, canonical(receipt))
	if err == nil {
		execution.money.Protocol.operations = tree
	}
	return err
}

type protocolFeeBody struct {
	ChainID   string `json:"chain_id"`
	Genesis   string `json:"genesis_hash"`
	MaxFee    string `json:"max_fee_atomic"`
	Nonce     uint64 `json:"nonce,string"`
	Operation string `json:"operation_root"`
	Schema    string `json:"schema"`
	Sender    string `json:"sender"`
}

type protocolFeeAuthorization struct {
	Body      protocolFeeBody `json:"body"`
	Signature string          `json:"signature"`
}

type protocolCommitteeBody struct {
	ExpiresHeight   uint64          `json:"expires_height,string"`
	FromRoot        string          `json:"from_root"`
	Genesis         string          `json:"genesis_hash"`
	Next            publicCommittee `json:"next"`
	Schema          string          `json:"schema"`
	UnusedKeyPolicy string          `json:"unused_key_policy"`
}

type protocolCommitteeBallot struct {
	Signature    string `json:"signature"`
	ValidatorKey string `json:"validator_key"`
}

type protocolMemberConsent struct {
	AccountSignature   string `json:"account_signature"`
	NodeSignature      string `json:"node_signature"`
	OwnerSignature     string `json:"owner_signature"`
	ValidatorKey       string `json:"validator_key"`
	ValidatorSignature string `json:"validator_signature"`
}

type protocolCommitteeOperation struct {
	Ballots  []protocolCommitteeBallot `json:"ballots"`
	Body     protocolCommitteeBody     `json:"body"`
	Consents []protocolMemberConsent   `json:"consents"`
}

type protocolProducerOperation struct {
	Invite protocolProducerInvite `json:"invite"`
	Work   miningWorkSolution     `json:"work"`
}

type protocolOperation struct {
	Cancel    *protocolCancelBody         `json:"cancel,omitempty"`
	Committee *protocolCommitteeOperation `json:"committee,omitempty"`
	Fee       protocolFeeAuthorization    `json:"fee"`
	Producer  *protocolProducerOperation  `json:"producer,omitempty"`
	Schema    string                      `json:"schema"`
}

func protocolOperationRoot(operation protocolOperation) (string, error) {
	count := 0
	if operation.Producer != nil {
		count++
	}
	if operation.Committee != nil {
		count++
	}
	if operation.Cancel != nil {
		count++
	}
	if operation.Schema != "gg.financial.protocol-operation.v1" || count != 1 {
		return "", errFinancialProtocol
	}
	if operation.Cancel != nil {
		return hashHex(append([]byte("GG-FINANCIAL-NONCE-CANCEL-v1\x00"), canonical(operation.Cancel)...)), nil
	}
	if operation.Producer != nil {
		return hashHex(append([]byte("GG-FINANCIAL-PRODUCER-ADMISSION-v1\x00"), canonical(operation.Producer.Invite)...)), nil
	}
	return hashHex(append([]byte("GG-FINANCIAL-COMMITTEE-PROPOSAL-v1\x00"), canonical(operation.Committee.Body)...)), nil
}

func protocolSignature(key, signature string, message []byte) bool {
	public, err := hex.DecodeString(key)
	if err != nil || !financialAccountAddress(key) {
		return false
	}
	sig, err := hex.DecodeString(signature)
	return err == nil && len(signature) == 128 && hex.EncodeToString(sig) == signature && verifyTransactionSignature(public, message, sig)
}

func protocolFeeMessage(body protocolFeeBody) []byte {
	return append([]byte("GG-FINANCIAL-PROTOCOL-FEE-v1\x00"), canonical(body)...)
}

func protocolReserveFundedRole(ctx context.Context, money *financialMoneyState, key, owner, role, recoveryAccount string) error {
	// The signed producer invite/member proposal explicitly authorizes this
	// conversion. Unsolicited deposits cannot squat on fresh operational keys.
	// A key with any consumed monetary nonce remains permanently ineligible.
	if err := money.Protocol.reserveRole(ctx, key, owner, role); err != nil {
		return err
	}
	account, exists, err := money.Tree.get(ctx, key)
	if err != nil || !exists {
		return err
	}
	if account.Nonce != 0 || key == recoveryAccount {
		return errors.New("GG_PROTOCOL_ROLE_WALLET_COLLISION")
	}
	balance, ok := economicAmount(account.Balance)
	if !ok {
		return errFinancialProtocol
	}
	if balance == 0 {
		return nil
	}
	reserved, err := protocolAccountIsReserved(ctx, money.Protocol, recoveryAccount)
	if err != nil || reserved || !financialAccountAddress(recoveryAccount) {
		return errFinancialProtocol
	}
	receiver, present, err := money.Tree.get(ctx, recoveryAccount)
	if err != nil {
		return err
	}
	if !present {
		receiver = Account{Address: recoveryAccount, Balance: "0"}
	}
	before, ok := economicAmount(receiver.Balance)
	if !ok || before > money.Tree.rules.MaxTotal-balance {
		return errFinancialProtocol
	}
	account.Balance = "0"
	tree, err := money.Tree.set(ctx, account)
	if err != nil {
		return err
	}
	receiver.Balance = strconv.FormatUint(before+balance, 10)
	tree, err = tree.set(ctx, receiver)
	if err != nil {
		return err
	}
	money.Tree = &tree
	money.AccountRoot = tree.root.link.Hash
	return nil
}

func chargeProtocolOperation(ctx context.Context, execution *financialDagExecution, operation protocolOperation) error {
	root, err := protocolOperationRoot(operation)
	body := operation.Fee.Body
	cap, capOK := economicAmount(body.MaxFee)
	if err != nil || !capOK || body.Schema != "gg.financial.protocol-fee.v1" || body.ChainID != execution.genesis.ChainID || body.Genesis != execution.anchor ||
		body.Operation != root || !protocolSignature(body.Sender, operation.Fee.Signature, protocolFeeMessage(body)) {
		return errFinancialProtocol
	}
	reserved, err := protocolAccountIsReserved(ctx, execution.money.Protocol, body.Sender)
	if err != nil || reserved {
		return errFinancialProtocol
	}
	fee, err := economicMinimumFee(execution.genesis.Protocol.Economics, uint64(len(canonical(operation))))
	if err != nil || fee > cap {
		return errors.New("GG_PROTOCOL_OPERATION_FEE_LIMIT")
	}
	account, exists, err := execution.money.Tree.get(ctx, body.Sender)
	if err != nil || !exists || account.Nonce != body.Nonce || account.Nonce == economicMaxUint {
		return errors.New("GG_PROTOCOL_OPERATION_NONCE")
	}
	balance, ok := economicAmount(account.Balance)
	pot, potOK := economicAmount(execution.money.Protocol.state.FeePot)
	if !ok || !potOK || balance < fee || pot > economicMaxUint-fee {
		return errors.New("GG_PROTOCOL_OPERATION_FUNDS")
	}
	account.Balance, account.Nonce = strconv.FormatUint(balance-fee, 10), account.Nonce+1
	tree, err := execution.money.Tree.set(ctx, account)
	if err != nil {
		return err
	}
	execution.money.Tree = &tree
	execution.money.AccountRoot = tree.root.link.Hash
	execution.money.Protocol.state.FeePot = strconv.FormatUint(pot+fee, 10)
	return nil
}

func expectedProtocolAdmissionWork(execution *financialDagExecution, operation protocolOperation) (miningWorkJob, error) {
	if operation.Producer == nil {
		return miningWorkJob{}, errFinancialProtocol
	}
	protocol := execution.money.Protocol
	if protocol.state.WorkAnchorHeight > dagSegmentCounterMax-execution.genesis.Protocol.MaxWorkHeights {
		return miningWorkJob{}, errFinancialProtocol
	}
	payload := struct {
		Fee    protocolFeeAuthorization `json:"fee"`
		Invite protocolProducerInvite   `json:"invite"`
	}{operation.Fee, operation.Producer.Invite}
	id := hashHex(append([]byte("GG-FINANCIAL-REGISTRATION-WORK-v1\x00"), canonical(payload)...))
	return miningWorkJob{Epoch: protocol.state.Economics.NextEpoch, ExpiresHeight: protocol.state.WorkAnchorHeight + execution.genesis.Protocol.MaxWorkHeights,
		Genesis: execution.anchor, JobNonce: operation.Producer.Invite.Body.Nonce, NetworkTarget: execution.genesis.Protocol.RegistrationWorkTarget,
		PayloadRoot: id, RewardAccount: operation.Producer.Invite.Body.RewardAccount, Schema: "gg.financial.mining-job.v1",
		ShareTarget: operation.Producer.Work.Job.ShareTarget, StateHeight: protocol.state.WorkAnchorHeight, StateRoot: protocol.state.WorkAnchorRoot,
		WorkerKey: operation.Producer.Work.Job.WorkerKey}, nil
}

func applyProtocolProducer(ctx context.Context, execution *financialDagExecution, operation protocolOperation) error {
	invite := operation.Producer.Invite
	body := invite.Body
	if checkProtocolProducerInvite(invite, execution.genesis) != nil || operation.Fee.Body.Sender != body.RewardAccount {
		return errFinancialProtocol
	}
	protocol := execution.money.Protocol
	if _, exists, err := protocol.producers.get(ctx, body.ProducerKey); err != nil {
		return err
	} else if exists {
		return errors.New("GG_PRODUCER_ALREADY_REGISTERED")
	}
	if protocol.producers.root.link.Count >= execution.genesis.Protocol.MaxProducerEntries {
		return errors.New("GG_PRODUCER_REGISTRY_FULL")
	}
	expected, err := expectedProtocolAdmissionWork(execution, operation)
	if err != nil {
		return err
	}
	share, err := verifyMiningWork(expected, operation.Producer.Work, protocol.height)
	if err != nil || !share.networkWork {
		return errMiningWork
	}
	if err = chargeProtocolOperation(ctx, execution, operation); err != nil {
		return err
	}
	for _, row := range []struct{ key, role string }{{body.ProducerKey, "PRODUCER"}, {body.NodeKey, "NODE"}, {body.OwnerPeerKey, "OWNER"}} {
		if err = protocolReserveFundedRole(ctx, &execution.money, row.key, body.OwnerPeerKey, row.role, body.RewardAccount); err != nil {
			return err
		}
	}
	record := protocolProducerRecord{Head: financialDagOrigin(execution.source, execution.anchor), Invite: invite, Schema: "gg.financial.producer-state.v1"}
	protocol.producers, err = protocol.producers.set(ctx, body.ProducerKey, canonical(record))
	return err
}

func applyProtocolCommittee(ctx context.Context, execution *financialDagExecution, operation protocolOperation) error {
	protocol := execution.money.Protocol
	change := operation.Committee
	body := change.Body
	root, err := publicCommitteeRoot(protocol.state.Committee, execution.anchor)
	if err != nil || protocol.state.PendingCommittee != nil || body.Schema != "gg.financial.committee-proposal.v1" || body.UnusedKeyPolicy != protocolUnusedKeyPolicy || body.Genesis != execution.anchor || body.FromRoot != root ||
		body.ExpiresHeight < protocol.height || body.ExpiresHeight-protocol.height > 65536 || len(body.Next.Members) > 64 || len(change.Ballots) > 64 || len(change.Consents) > 64 ||
		change.Ballots == nil || change.Consents == nil {
		return errCommittee
	}
	plan, err := planCommitteeChange(protocol.state.Committee, body.Next, execution.anchor, protocol.height, execution.genesis.Protocol.MaxCommitteeChangeBPS)
	if err != nil {
		return err
	}
	proposal, err := protocolOperationRoot(operation)
	if err != nil {
		return err
	}
	old := map[string]publicConsensusMember{}
	total, approved := uint64(0), uint64(0)
	for _, member := range protocol.state.Committee.Members {
		old[member.ValidatorKey] = member
		power, _ := economicAmount(member.Power)
		total += power
	}
	previous := ""
	for _, ballot := range change.Ballots {
		member, exists := old[ballot.ValidatorKey]
		message := []byte("GG-FINANCIAL-COMMITTEE-BALLOT-v1\x00" + proposal + "\x00" + ballot.ValidatorKey)
		if !exists || ballot.ValidatorKey <= previous || !protocolSignature(member.AccountKey, ballot.Signature, message) {
			return errCommittee
		}
		power, _ := economicAmount(member.Power)
		approved += power
		previous = ballot.ValidatorKey
	}
	if approved <= total/3*2+(total%3*2)/3 {
		return errors.New("GG_COMMITTEE_GOVERNANCE_QUORUM")
	}
	consents := map[string]protocolMemberConsent{}
	previous = ""
	for _, consent := range change.Consents {
		if consent.ValidatorKey <= previous {
			return errCommittee
		}
		consents[consent.ValidatorKey] = consent
		previous = consent.ValidatorKey
	}
	for _, member := range body.Next.Members {
		if _, exists := old[member.ValidatorKey]; exists {
			continue
		}
		consent, exists := consents[member.ValidatorKey]
		message := []byte("GG-FINANCIAL-COMMITTEE-MEMBER-CONSENT-v1\x00" + proposal + "\x00" + member.ValidatorKey)
		if !exists || !protocolSignature(member.AccountKey, consent.AccountSignature, message) || !protocolSignature(member.NodeKey, consent.NodeSignature, message) ||
			!protocolSignature(member.OwnerPeerKey, consent.OwnerSignature, message) || !protocolSignature(member.ValidatorKey, consent.ValidatorSignature, message) {
			return errCommittee
		}
		delete(consents, member.ValidatorKey)
		reserved, err := protocolAccountIsReserved(ctx, protocol, member.AccountKey)
		if err != nil || reserved {
			return errCommittee
		}
		for _, row := range []struct{ key, role string }{{member.ValidatorKey, "VALIDATOR"}, {member.NodeKey, "NODE"}, {member.OwnerPeerKey, "OWNER"}} {
			if err = protocolReserveFundedRole(ctx, &execution.money, row.key, member.OwnerPeerKey, row.role, member.AccountKey); err != nil {
				return err
			}
		}
		if err = protocol.reserveRole(ctx, member.AccountKey, member.OwnerPeerKey, "GOVERNANCE"); err != nil {
			return err
		}
		// Pin the governance account as a wallet before any later role key
		// can reuse its address, even when its balance starts at zero.
		account, exists, err := execution.money.Tree.get(ctx, member.AccountKey)
		if err != nil {
			return err
		}
		if !exists {
			account = Account{Address: member.AccountKey, Balance: "0"}
			tree, err := execution.money.Tree.set(ctx, account)
			if err != nil {
				return err
			}
			execution.money.Tree = &tree
		}
	}
	if len(consents) != 0 {
		return errCommittee
	}
	if err = chargeProtocolOperation(ctx, execution, operation); err != nil {
		return err
	}
	protocol.state.PendingCommittee = &plan
	return nil
}

func (execution *financialDagExecution) applyProtocolOperation(ctx context.Context, operation protocolOperation) error {
	if !execution.source.hasProtocol() || execution.money.Protocol == nil || execution.operations == dagSegmentCounterMax || len(canonical(operation)) > 128*1024 {
		return errFinancialProtocol
	}
	if _, err := protocolOperationRoot(operation); err != nil {
		return err
	}
	var err error
	if operation.Producer != nil {
		err = applyProtocolProducer(ctx, execution, operation)
	} else if operation.Committee != nil {
		err = applyProtocolCommittee(ctx, execution, operation)
	} else {
		body := operation.Cancel
		if body == nil || body.Schema != "gg.financial.nonce-cancel.v1" || body.Genesis != execution.anchor || body.Sender != operation.Fee.Body.Sender || body.Nonce != operation.Fee.Body.Nonce || !pubPattern.MatchString(body.Replaces) {
			return errFinancialProtocol
		}
		err = chargeProtocolOperation(ctx, execution, operation)
	}
	if err != nil {
		return err
	}
	if err = execution.recordProtocolOperation(ctx, operation); err != nil {
		return err
	}
	size := uint64(len(canonical(operation)))
	if size > dagSegmentCounterMax-execution.rawBytes {
		return errFinancialProtocol
	}
	execution.operations++
	execution.rawBytes += size
	execution.money.AccountRoot = execution.money.Tree.root.link.Hash
	if err = validateProtocolMoney(execution.money, execution.genesis, execution.anchor); err != nil {
		return err
	}
	return ctx.Err()
}

// A candidate is cloned by callers before this mutates its private path nodes.
// A rejected operation cannot publish a partial fee, reservation or committee.
func canonicalProtocolOperation(operation protocolOperation) bool {
	if _, err := protocolOperationRoot(operation); err != nil {
		return false
	}
	raw := canonical(operation)
	var decoded protocolOperation
	return decodeStrictLimited(raw, &decoded, 128, 64) == nil && bytes.Equal(raw, canonical(decoded))
}
