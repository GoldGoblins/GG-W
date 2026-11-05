//go:build !js

package main

// These public, deterministic test identities and easy test-only work targets
// exercise the complete native application. They are never a network policy.
import (
	"bytes"
	"context"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"sort"
	"strconv"
	"strings"
	"testing"
	"time"

	abci "github.com/cometbft/cometbft/abci/types"
	cmted "github.com/cometbft/cometbft/crypto/ed25519"
	cmtjson "github.com/cometbft/cometbft/libs/json"
	cmtproto "github.com/cometbft/cometbft/proto/tendermint/types"
	"github.com/cometbft/cometbft/types"
)

func publicFixtureKey(name string) ed25519.PrivateKey {
	seed := sha256.Sum256([]byte("GG PUBLIC INTEGRATION FIXTURE " + name))
	return ed25519.NewKeyFromSeed(seed[:])
}

func publicFixtureAddress(key ed25519.PrivateKey) string { return hex.EncodeToString(key[32:]) }

func assertPublicCanonicalJSON(t *testing.T, value any) {
	t.Helper()
	raw := canonical(value)
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	var decoded any
	if decoder.Decode(&decoded) != nil || !bytes.Equal(raw, canonical(decoded)) {
		t.Fatal("public output is not sorted canonical JSON across language boundaries")
	}
}

func publicFixtureInvite(genesis Genesis, name string, keys map[string]ed25519.PrivateKey) protocolProducerInvite {
	key := func(role string) string {
		value := publicFixtureKey(name + ":" + role)
		address := publicFixtureAddress(value)
		keys[address] = value
		return address
	}
	body := protocolProducerBody{ChainID: genesis.ChainID, NetworkID: genesis.FinancialDAG.NetworkID,
		NodeKey: key("node"), OwnerPeerKey: key("owner"), ProducerKey: key("producer"), RewardAccount: key("reward"),
		LabelUTF8: base64.StdEncoding.EncodeToString([]byte(name)), Nonce: hashHex([]byte(name)), Platform: "linux",
		Schema: "gg.financial.producer-registration.v1", UnusedKeyPolicy: protocolUnusedKeyPolicy}
	message := append([]byte("GG-FINANCIAL-PRODUCER-REGISTRATION-v1\x00"), canonical(body)...)
	sign := func(address string) string { return hex.EncodeToString(ed25519.Sign(keys[address], message)) }
	return protocolProducerInvite{Body: body, NodeSignature: sign(body.NodeKey), OwnerSignature: sign(body.OwnerPeerKey), ProducerSignature: sign(body.ProducerKey)}
}

func publicProtocolFixture(t *testing.T) (*financialDagExecution, map[string]ed25519.PrivateKey, []ed25519.PrivateKey) {
	t.Helper()
	keys := map[string]ed25519.PrivateKey{}
	key := func(name string) string {
		value := publicFixtureKey(name)
		address := publicFixtureAddress(value)
		keys[address] = value
		return address
	}
	genesis := Genesis{ChainID: "ggnet:" + strings.Repeat("d", 24), Decimals: 6, GenesisTime: 1700000000,
		Schema: "gg.native.genesis.v7", SupplyAtomic: "1000000000000", Symbol: "GG-TEST"}
	source := financialDagSource{AllowedProducers: []int{}, NativeChainID: genesis.ChainID, NetworkID: hashHex([]byte("GG PUBLIC TEST NETWORK")),
		Schema: financialProtocolSourceSchema, SignatureProfile: TransactionSignatureProfile, StartedAtNs: strconv.FormatInt(genesis.GenesisTime*1000000000, 10)}
	source.Policy = source.rules()
	genesis.FinancialDAG = &source
	committee := publicCommittee{Members: []publicConsensusMember{}, Schema: "gg.financial.public-committee.v1"}
	for index := 0; index < 4; index++ {
		name := "validator:" + strconv.Itoa(index)
		committee.Members = append(committee.Members, publicConsensusMember{AccountKey: key(name + ":account"), NodeKey: key(name + ":node"),
			OwnerPeerKey: key(name + ":owner"), Power: "1", ValidatorKey: key(name + ":vote")})
	}
	sort.Slice(committee.Members, func(i, j int) bool { return committee.Members[i].ValidatorKey < committee.Members[j].ValidatorKey })
	for _, member := range committee.Members {
		genesis.Validators = append(genesis.Validators, member.ValidatorKey)
	}
	policy := &financialProtocolGenesis{Committee: committee, Economics: economicPolicy{EpochReward: "64000", EpochSeconds: 10,
		FeePerByte: "1", HalvingEpochs: 100, InitialSupply: genesis.SupplyAtomic, MaxSupply: "2000000000000", MinFee: "10",
		Schema: "gg.financial.economic-policy.v1", TailReward: "1"}, Environment: "TESTNET", ExpectedBlocksPerEpoch: 1000,
		InitialWorkTarget: strings.Repeat("f", 64), MaxWorkTarget: strings.Repeat("f", 64), MinWorkTarget: strings.Repeat("0", 63) + "1",
		RegistrationWorkTarget: strings.Repeat("f", 64), MaxCommitteeChangeBPS: 3333, MaxEpochParticipants: 64,
		MaxProducerEntries: 128, MaxWorkHeights: 64, Schema: "gg.financial.protocol-genesis.v1"}
	for _, name := range []string{"Windows", "Linux", "Termux"} {
		policy.InitialProducers = append(policy.InitialProducers, publicFixtureInvite(genesis, name, keys))
	}
	sort.Slice(policy.InitialProducers, func(i, j int) bool {
		return policy.InitialProducers[i].Body.ProducerKey < policy.InitialProducers[j].Body.ProducerKey
	})
	producers := []ed25519.PrivateKey{}
	for _, invite := range policy.InitialProducers {
		source.Producers = append(source.Producers, invite.Body.ProducerKey)
		producers = append(producers, keys[invite.Body.ProducerKey])
	}
	genesis.Protocol = policy
	genesis.FinancialAccounts = &financialAccountGenesis{Allocations: []financialAccountAllocation{{Address: key("payer"), Balance: genesis.SupplyAtomic}},
		MaxAccounts: 20000, Schema: "gg.financial.account-genesis.v1"}
	anchor := hashHex(canonical(genesis))
	if err := validateGenesis(genesis, anchor); err != nil {
		t.Fatal("public fixture genesis", err)
	}
	model, err := newFinancialDagExecution(genesis, anchor, source)
	if err != nil {
		t.Fatal("public fixture execution", err)
	}
	return model, keys, producers
}

func publicProtocolSDKFixture(t *testing.T) (*Ledger, *financialNativeApplication, map[string]ed25519.PrivateKey, []ed25519.PrivateKey, string) {
	t.Helper()
	model, keys, producers := publicProtocolFixture(t)
	root := t.TempDir()
	app, err := newDagEnabledLedger(model.genesis, model.anchor, root, true)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = app.Close() })
	return app, app.financial.(*financialNativeApplication), keys, producers, root
}

func publicFixturePayment(base *financialDagExecution, sender ed25519.PrivateKey, receiver string, nonce uint64, amount string) Envelope {
	cap := "100000"
	body := Body{Amount: amount, ChainID: base.genesis.ChainID, GenesisHash: base.anchor, MaxFee: &cap, Nonce: nonce,
		Recipient: receiver, Sender: publicFixtureAddress(sender), Version: 2}
	return Envelope{Body: body, Signature: hex.EncodeToString(ed25519.Sign(sender, canonical(body)))}
}

func publicFixtureBlock(t *testing.T, base *financialDagExecution, producer, worker ed25519.PrivateKey, payments []Envelope) (financialProtocolBlock, []byte, string) {
	t.Helper()
	record, err := base.money.Protocol.producer(context.Background(), publicFixtureAddress(producer), base.genesis)
	if err != nil {
		t.Fatal(err)
	}
	body := financialProtocolBlockBody{CreatedAtNs: uint64(base.timeNs), Epoch: base.epoch, GenesisHash: base.anchor, Parents: []string{record.Head},
		PaymentRoot: financialDagPaymentRoot(payments), Payments: payments, ProducerKey: publicFixtureAddress(producer), Rank: record.Rank + 1,
		Schema: "gg.financial-dag.block.v2", Sequence: record.Sequence + 1, SourceHash: base.source.hash()}
	block := financialProtocolBlock{Body: body, Signature: hex.EncodeToString(ed25519.Sign(producer, append([]byte(financialDomain+"DAG-BLOCK-SIGN-v2\x00"), canonical(body)...)))}
	block.Work.Job.ShareTarget, block.Work.Job.WorkerKey = base.money.Protocol.state.WorkTarget, publicFixtureAddress(worker)
	job, err := base.money.Protocol.expectedBlockWork(context.Background(), block, base.anchor)
	if err != nil {
		t.Fatal(err)
	}
	solution, _, _, err := mineFinancialWork(context.Background(), job, worker, 0, 1<<20)
	if err != nil || solution == nil {
		t.Fatal("fixture real work", err)
	}
	block.Work = *solution
	return block, canonical(block), financialProtocolBlockID(block)
}

func publicFixtureBatch(t *testing.T, base *financialDagExecution, operations []protocolOperation, blocks ...[]byte) []byte {
	t.Helper()
	previous, err := base.commitmentHash()
	if err != nil {
		t.Fatal(err)
	}
	encoded := []string{}
	for _, raw := range blocks {
		encoded = append(encoded, base64.StdEncoding.EncodeToString(raw))
	}
	return canonical(financialDagBatch{Blocks: encoded, Operations: operations, GenesisHash: base.anchor, Previous: previous,
		Schema: "gg.financial-dag.batch.v2", Sequence: base.checkpoint + 1, SourceHash: base.source.hash()})
}

func publicFixtureAuthorize(t *testing.T, base *financialDagExecution, operation protocolOperation, payer ed25519.PrivateKey, nonce uint64) protocolOperation {
	t.Helper()
	root, err := protocolOperationRoot(operation)
	if err != nil {
		t.Fatal(err)
	}
	body := protocolFeeBody{ChainID: base.genesis.ChainID, Genesis: base.anchor, MaxFee: "100000", Nonce: nonce, Operation: root,
		Schema: "gg.financial.protocol-fee.v1", Sender: publicFixtureAddress(payer)}
	operation.Fee = protocolFeeAuthorization{Body: body, Signature: hex.EncodeToString(ed25519.Sign(payer, protocolFeeMessage(body)))}
	return operation
}

func publicFixturePacket(t *testing.T, app *Ledger, keys map[string]ed25519.PrivateKey) VerifyInput {
	t.Helper()
	validators := []cmted.PrivKey{}
	for _, member := range app.genesis.Protocol.Committee.Members {
		validators = append(validators, cmted.PrivKey(keys[member.ValidatorKey]))
	}
	header := signedFixture(app.genesis, validators, app.state.Height+1, app.state.StateRoot, nil, types.BlockID{})
	raw, err := cmtjson.Marshal(header)
	if err != nil {
		t.Fatal(err)
	}
	return VerifyInput{Schema: "gg.consensus.proof.v1", Genesis: app.genesis, GenesisHash: app.anchor, SignedHeader: raw, State: copyState(app.state)}
}

func publicFixtureTransitionHeader(t *testing.T, app *Ledger, state State, keys map[string]ed25519.PrivateKey) []byte {
	t.Helper()
	validators := []cmted.PrivKey{}
	for _, member := range state.Protocol.Committee.Members {
		validators = append(validators, cmted.PrivKey(keys[member.ValidatorKey]))
	}
	header := signedFixture(app.genesis, validators, state.Height+1, state.StateRoot, nil, types.BlockID{})
	next, err := committeeValidatorSet(state.Protocol.PendingCommittee.Next)
	if err != nil {
		t.Fatal(err)
	}
	header.NextValidatorsHash = next.Hash()
	header.Commit.BlockID.Hash = header.Header.Hash()
	set, _ := committeeValidatorSet(state.Protocol.Committee)
	for index, validator := range set.Validators {
		vote := &cmtproto.Vote{Type: cmtproto.PrecommitType, Height: header.Height, Round: 0, BlockID: header.Commit.BlockID.ToProto(), Timestamp: header.Time, ValidatorAddress: validator.Address, ValidatorIndex: int32(index)}
		for _, key := range validators {
			if bytes.Equal(key.PubKey().Address(), validator.Address) {
				header.Commit.Signatures[index].Signature, _ = key.Sign(types.VoteSignBytes(app.genesis.ChainID, vote))
			}
		}
	}
	raw, err := cmtjson.Marshal(header)
	if err != nil {
		t.Fatal(err)
	}
	return raw
}

func TestPublicProtocol5000DistinctPaymentsCertifiedAttributionAndColdReplay(t *testing.T) {
	app, backend, keys, producers, root := publicProtocolSDKFixture(t)
	payer := keys[app.genesis.FinancialAccounts.Allocations[0].Address]
	payments := make([]Envelope, 5000)
	fees := uint64(0)
	for index := range payments {
		payments[index] = publicFixturePayment(backend.current, payer, publicFixtureAddress(publicFixtureKey("receiver:"+strconv.Itoa(index))), uint64(index), "7")
		fee, err := economicMinimumFee(app.genesis.Protocol.Economics, uint64(len(canonical(payments[index]))))
		if err != nil {
			t.Fatal(err)
		}
		fees += fee
	}
	worker := publicFixtureKey("independent-phone-worker")
	block, raw, id := publicFixtureBlock(t, backend.current, producers[0], worker, payments)
	batch := publicFixtureBatch(t, backend.current, nil, raw)
	before := canonical(app.state)
	checked, err := app.CheckTx(context.Background(), &abci.RequestCheckTx{Tx: batch})
	if err != nil || checked.Code != 0 || !bytes.Equal(before, canonical(app.state)) {
		t.Fatal("mempool validation mutated or failed", err, checked)
	}
	commitFinancialSDK(t, app, batch)
	state := app.state
	if state.FinancialDAG.Applied != 5000 || state.FinancialDAG.Rejected != 0 || state.Protocol.FeePot != strconv.FormatUint(fees, 10) || state.SupplyAtomic != app.genesis.SupplyAtomic {
		t.Fatal("actual payments/fees/issuance")
	}
	proof, err := backend.Account(context.Background(), state, publicFixtureAddress(payer))
	account, exists, accountErr := checkFinancialCertifiedAccount(context.Background(), proof, state, app.genesis)
	if err != nil || accountErr != nil || !exists || account.Nonce != 5000 || account.Balance != strconv.FormatUint(1000000000000-35000-fees, 10) {
		t.Fatal("payer money or nonce", err, accountErr)
	}
	if state.AccountTree.Count != 5000+1+4+3 {
		t.Fatal("unique independent accounts were not created", state.AccountTree.Count)
	}
	blockProof, err := backend.Block(context.Background(), state, id)
	if err != nil || checkFinancialCertifiedBlock(blockProof, state, app.genesis, id) != nil || blockProof.Creator.Key != publicFixtureAddress(producers[0]) ||
		blockProof.Creator.WorkerKey != publicFixtureAddress(worker) || blockProof.Creator.Rank != block.Body.Rank || !bytes.Equal(canonical(blockProof.Creator.Parents), canonical(block.Body.Parents)) {
		t.Fatal("single creator / separate worker / causal proof", err)
	}
	packet := publicFixturePacket(t, app, keys)
	packet.FinancialBlock, packet.ExpectedFinancialBlock = &blockProof, id
	if result, err := verifyInput(packet); err != nil || result["verified"] != true {
		t.Fatal("real SDK signature proof", err)
	}
	receipt, err := backend.Receipt(context.Background(), state, financialReceiptSelector{Block: id, Index: 4999})
	if err != nil || checkFinancialCertifiedReceipt(receipt, state, app.genesis) != nil {
		t.Fatal("real public selected payment receipt", err)
	}
	index := 4999
	packet.FinancialReceipt = &receipt
	packet.ExpectedFinancialReceipt = &financialReceiptExpectation{Block: id, Index: &index, TransactionID: financialIntentID(canonical(payments[index]))}
	if result, err := verifyInput(packet); err != nil || result["financial_receipt_verified"] != true {
		t.Fatal("independent public payment selector", err)
	} else {
		assertPublicCanonicalJSON(t, result)
	}
	assertPublicCanonicalJSON(t, state)
	assertPublicCanonicalJSON(t, financialRecentSelector{Limit: 16, Start: 1})
	for _, mutate := range []func(*financialCertifiedBlock){func(p *financialCertifiedBlock) { p.Creator.WorkerKey = publicFixtureAddress(payer) }, func(p *financialCertifiedBlock) { p.Creator.Parents = []string{strings.Repeat("e", 64)} }, func(p *financialCertifiedBlock) { p.Creator.Rank++ }} {
		bad := blockProof
		mutate(&bad)
		if checkFinancialCertifiedBlock(bad, state, app.genesis, id) == nil {
			t.Fatal("forged attribution accepted")
		}
	}
	discovery, err := backend.RecentBlocks(context.Background(), state, financialRecentSelector{Start: 1, Limit: 16})
	if err != nil || len(discovery.Blocks) != 1 || discovery.Blocks[0].Block != id || discovery.Blocks[0].Index != blockProof.Context.OrderIndex {
		t.Fatal("canonical discovery", err)
	}
	snapshot := canonical(state)
	if err := app.Close(); err != nil {
		t.Fatal(err)
	}
	reopened, err := newDagEnabledLedger(app.genesis, app.anchor, root, false)
	if err != nil {
		t.Fatal("cold independent journal replay", err)
	}
	defer reopened.Close()
	if !bytes.Equal(snapshot, canonical(reopened.state)) {
		t.Fatal("cold money / creator / indexes differ")
	}
	discovery, err = reopened.financial.(*financialNativeApplication).RecentBlocks(context.Background(), reopened.state, financialRecentSelector{Start: 1, Limit: 1})
	if err != nil || discovery.Blocks[0].Block != id {
		t.Fatal("cold canonical order index", err)
	}
}

func TestPublicProtocolCancellationOriginalRaceAndExactReceipt(t *testing.T) {
	for _, cancelFirst := range []bool{true, false} {
		t.Run(strconv.FormatBool(cancelFirst), func(t *testing.T) {
			app, backend, keys, producers, _ := publicProtocolSDKFixture(t)
			payer := keys[app.genesis.FinancialAccounts.Allocations[0].Address]
			payment := publicFixturePayment(backend.current, payer, publicFixtureAddress(publicFixtureKey("cancel-recipient")), 0, "9")
			operation := protocolOperation{Cancel: &protocolCancelBody{Genesis: app.anchor, Nonce: 0, Replaces: hashHex(canonical(payment)), Schema: "gg.financial.nonce-cancel.v1", Sender: publicFixtureAddress(payer)}, Schema: "gg.financial.protocol-operation.v1"}
			operation = publicFixtureAuthorize(t, backend.current, operation, payer, 0)
			if cancelFirst {
				commitFinancialSDK(t, app, publicFixtureBatch(t, backend.current, []protocolOperation{operation}))
			}
			_, raw, _ := publicFixtureBlock(t, backend.current, producers[0], producers[0], []Envelope{payment})
			commitFinancialSDK(t, app, publicFixtureBatch(t, backend.current, nil, raw))
			selector := protocolRegistrySelector{Namespace: "operations", Key: protocolOperationReceiptKey(publicFixtureAddress(payer), 0)}
			proof, err := backend.Registry(context.Background(), app.state, selector)
			value, exists, verifyErr := checkFinancialCertifiedRegistry(context.Background(), proof, app.state, app.genesis, selector)
			if err != nil || verifyErr != nil || exists != cancelFirst {
				t.Fatal("cancel selector", err, verifyErr)
			}
			if cancelFirst {
				var receipt protocolOperationReceipt
				if decodeStrict(value, &receipt) != nil || receipt.Authorization != protocolFeeAuthorizationID(operation.Fee) || receipt.Kind != "NONCE_CANCELLED" || app.state.FinancialDAG.Applied != 0 || app.state.FinancialDAG.Rejected != 1 {
					t.Fatal("cancel did not win exact nonce")
				}
				wrong := selector
				wrong.Key = hashHex([]byte("another nonce"))
				if _, _, err := checkFinancialCertifiedRegistry(context.Background(), proof, app.state, app.genesis, wrong); err == nil {
					t.Fatal("operation proof selector substitution")
				}
			} else {
				before := canonical(app.state)
				check, err := app.CheckTx(context.Background(), &abci.RequestCheckTx{Tx: publicFixtureBatch(t, backend.current, []protocolOperation{operation})})
				if err != nil || check.Code == 0 || !bytes.Equal(before, canonical(app.state)) || app.state.FinancialDAG.Applied != 1 {
					t.Fatal("late cancel changed original payment", err)
				}
			}
		})
	}
}

func TestPublicProtocolRegistrationDustAndOrderedRoleRace(t *testing.T) {
	app, backend, keys, producers, _ := publicProtocolSDKFixture(t)
	payer := keys[app.genesis.FinancialAccounts.Allocations[0].Address]
	invite := publicFixtureInvite(app.genesis, "new-independent-owner", keys)
	payments := []Envelope{publicFixturePayment(backend.current, payer, invite.Body.RewardAccount, 0, "1000000"), publicFixturePayment(backend.current, payer, invite.Body.ProducerKey, 1, "23")}
	_, raw, _ := publicFixtureBlock(t, backend.current, producers[0], producers[0], payments)
	commitFinancialSDK(t, app, publicFixtureBatch(t, backend.current, nil, raw))
	// This immutable core predates the role registration. Its valid payment
	// becomes an ordered rejection; it must not freeze the producer sequence.
	_, racing, _ := publicFixtureBlock(t, backend.current, producers[1], producers[1], []Envelope{publicFixturePayment(backend.current, payer, invite.Body.ProducerKey, 2, "11")})
	operation := protocolOperation{Producer: &protocolProducerOperation{Invite: invite}, Schema: "gg.financial.protocol-operation.v1"}
	operation = publicFixtureAuthorize(t, backend.current, operation, keys[invite.Body.RewardAccount], 0)
	operation.Producer.Work.Job.ShareTarget = app.genesis.Protocol.RegistrationWorkTarget
	operation.Producer.Work.Job.WorkerKey = invite.Body.NodeKey
	job, err := expectedProtocolAdmissionWork(backend.current, operation)
	if err != nil {
		t.Fatal(err)
	}
	solution, _, _, err := mineFinancialWork(context.Background(), job, keys[invite.Body.NodeKey], 0, 1<<20)
	if err != nil || solution == nil {
		t.Fatal(err)
	}
	operation.Producer.Work = *solution
	commitFinancialSDK(t, app, publicFixtureBatch(t, backend.current, []protocolOperation{operation}))
	account, exists, err := backend.current.money.Tree.get(context.Background(), invite.Body.ProducerKey)
	if err != nil || !exists || account.Balance != "0" || account.Nonce != 0 {
		t.Fatal("never-spent dust did not sweep with signed consent", err)
	}
	commitFinancialSDK(t, app, publicFixtureBatch(t, backend.current, nil, racing))
	if app.state.FinancialDAG.Rejected != 1 || app.state.FinancialDAG.Applied != 2 {
		t.Fatal("role race invalidated immutable creator core")
	}
	_, raw, _ = publicFixtureBlock(t, backend.current, keys[invite.Body.ProducerKey], keys[invite.Body.NodeKey], []Envelope{})
	commitFinancialSDK(t, app, publicFixtureBatch(t, backend.current, nil, raw))
	if app.state.Protocol.ProducerRoot.Count != 4 || app.state.FinancialDAG.Blocks != 3 {
		t.Fatal("new owner cannot produce")
	}
}

func TestPublicProtocolEpochRewardsConserveFeesAndIdleEpochsDoNotMint(t *testing.T) {
	app, backend, keys, producers, _ := publicProtocolSDKFixture(t)
	payer := keys[app.genesis.FinancialAccounts.Allocations[0].Address]
	payment := publicFixturePayment(backend.current, payer, publicFixtureAddress(publicFixtureKey("economic-recipient")), 0, "10")
	_, raw, _ := publicFixtureBlock(t, backend.current, producers[0], publicFixtureKey("economic-phone-worker"), []Envelope{payment})
	commitFinancialSDK(t, app, publicFixtureBatch(t, backend.current, nil, raw))
	fees, _ := economicAmount(app.state.Protocol.FeePot)
	finalized, err := app.FinalizeBlock(context.Background(), &abci.RequestFinalizeBlock{Height: app.state.Height + 1, Time: time.Unix(app.genesis.GenesisTime+10, 0)})
	if err != nil || len(finalized.AppHash) != 32 {
		t.Fatal(err)
	}
	if _, err = app.Commit(context.Background(), &abci.RequestCommit{}); err != nil {
		t.Fatal(err)
	}
	if app.state.SupplyAtomic != "1000000064000" || app.state.Protocol.FeePot != "0" || app.state.Protocol.Settlements != 1 {
		t.Fatal("capped issuance/fees settlement")
	}
	reward := app.genesis.Protocol.InitialProducers[0].Body.RewardAccount
	proof, err := backend.Reward(context.Background(), app.state, protocolRewardSelector{Address: reward, Index: 1})
	if err != nil || checkFinancialCertifiedReward(context.Background(), proof, app.state, app.genesis, protocolRewardSelector{Address: reward, Index: 1}) != nil || proof.Credit.Amount != strconv.FormatUint(64000+fees, 10) {
		t.Fatal("actual reward credit", err)
	}
	issued := app.state.SupplyAtomic
	_, err = app.FinalizeBlock(context.Background(), &abci.RequestFinalizeBlock{Height: app.state.Height + 1, Time: time.Unix(app.genesis.GenesisTime+100, 0)})
	if err != nil {
		t.Fatal(err)
	}
	if _, err = app.Commit(context.Background(), &abci.RequestCommit{}); err != nil {
		t.Fatal(err)
	}
	if app.state.SupplyAtomic != issued || app.state.AccountTree.Total != issued {
		t.Fatal("idle epochs minted without admitted work")
	}
}

func TestPublicProtocolGovernanceUsesAccountSignaturesAndSDKHPlusTwo(t *testing.T) {
	app, backend, keys, _, root := publicProtocolSDKFixture(t)
	payer := keys[app.genesis.FinancialAccounts.Allocations[0].Address]
	beforeCommittee := app.state.Protocol.Committee
	next := beforeCommittee
	next.Members = append([]publicConsensusMember(nil), next.Members...)
	next.Epoch++
	next.Members[0].Power = "2"
	from, _ := publicCommitteeRoot(beforeCommittee, app.anchor)
	change := protocolCommitteeOperation{Body: protocolCommitteeBody{ExpiresHeight: 64, FromRoot: from, Genesis: app.anchor, Next: next, Schema: "gg.financial.committee-proposal.v1", UnusedKeyPolicy: protocolUnusedKeyPolicy}, Ballots: []protocolCommitteeBallot{}, Consents: []protocolMemberConsent{}}
	operation := protocolOperation{Committee: &change, Schema: "gg.financial.protocol-operation.v1"}
	proposal, _ := protocolOperationRoot(operation)
	for _, member := range beforeCommittee.Members[:3] {
		message := []byte("GG-FINANCIAL-COMMITTEE-BALLOT-v1\x00" + proposal + "\x00" + member.ValidatorKey)
		change.Ballots = append(change.Ballots, protocolCommitteeBallot{ValidatorKey: member.ValidatorKey, Signature: hex.EncodeToString(ed25519.Sign(keys[member.AccountKey], message))})
	}
	operation = publicFixtureAuthorize(t, backend.current, operation, payer, 0)
	bad := operation
	badChange := change
	badChange.Ballots = append([]protocolCommitteeBallot(nil), change.Ballots...)
	bad.Committee = &badChange
	member := beforeCommittee.Members[0]
	badChange.Ballots[0].Signature = hex.EncodeToString(ed25519.Sign(keys[member.ValidatorKey], []byte("GG-FINANCIAL-COMMITTEE-BALLOT-v1\x00"+proposal+"\x00"+member.ValidatorKey)))
	check, err := app.CheckTx(context.Background(), &abci.RequestCheckTx{Tx: publicFixtureBatch(t, backend.current, []protocolOperation{bad})})
	if err != nil || check.Code == 0 {
		t.Fatal("vote key impersonated monetary governance account", err)
	}
	commitFinancialSDK(t, app, publicFixtureBatch(t, backend.current, []protocolOperation{operation}))
	if app.state.Protocol.Committee.Epoch != 0 || app.state.Protocol.PendingCommittee == nil || app.state.Protocol.PendingCommittee.EffectiveHeight != 3 {
		t.Fatal("H+2 plan")
	}
	decision := copyState(app.state)
	transition := financialCommitteeTransition{Schema: "gg.financial.committee-transition-proof.v1", State: decision, SignedHeader: publicFixtureTransitionHeader(t, app, decision, keys)}
	trust, err := initialCommitteeTrust(app.genesis, app.anchor)
	if err != nil {
		t.Fatal(err)
	}
	if err = trust.accept(app.genesis, transition); err != nil {
		t.Fatal("real predecessor SDK quorum transition", err)
	}
	if committee, err := trust.committeeAt(2); err != nil || committee.Epoch != 0 {
		t.Fatal("light trust activated before H+2", err)
	}
	if committee, err := trust.committeeAt(3); err != nil || committee.Epoch != 1 {
		t.Fatal("light trust failed after H+2", err)
	}
	if err = trust.accept(app.genesis, transition); err == nil {
		t.Fatal("committee certificate replay accepted")
	}
	commitFinancialSDK(t, app, nil)
	if app.state.Protocol.Committee.Epoch != 0 {
		t.Fatal("committee activated before H+2")
	}
	commitFinancialSDK(t, app, nil)
	if app.state.Protocol.Committee.Epoch != 1 || app.state.Protocol.PendingCommittee != nil {
		t.Fatal("committee failed at H+2")
	}
	stored, err := backend.CommitteeState(context.Background(), 1)
	if err != nil || !bytes.Equal(canonical(stored), canonical(decision)) {
		t.Fatal("certifiable predecessor decision missing", err)
	}
	snapshot := canonical(app.state)
	_ = app.Close()
	reopened, err := newDagEnabledLedger(app.genesis, app.anchor, root, false)
	if err != nil {
		t.Fatal(err)
	}
	defer reopened.Close()
	if !bytes.Equal(snapshot, canonical(reopened.state)) {
		t.Fatal("cold H+2 decision recovery changed committee")
	}
}
