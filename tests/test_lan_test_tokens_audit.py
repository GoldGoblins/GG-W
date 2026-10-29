"""Independent CPU-only checks of the ephemeral coordinator test ledger.

All identities below are synthetic deterministic fixtures. These tests bind no
socket, access no user state and make no physical-device or DAG-finality claim.
"""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.gg_ed25519 import Keypair
from backend.gg_parallel_dag import digest,pack
from backend import gg_lan_test_tokens as token
from backend import gg_lan_dag as lan


class TestTokenLedgerAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.identities=[Keypair.from_seed(bytes([i])*32) for i in (1,2,3)]
        cls.signers=[Keypair.from_seed(bytes([i])*32) for i in (4,5,6)]
        cls.roster=[{'peer_key':peer.pubkey().hex(),'producer_keys':[signer.pubkey().hex()],
                     'label':f'synthetic-{i}'} for i,(peer,signer) in enumerate(zip(cls.identities,cls.signers))]
        cls.peers=[row['peer_key'] for row in cls.roster]
        cls.coordinator=cls.peers[0]
        cls.descriptor=token.genesis(cls.roster,cls.coordinator)

    def setUp(self):
        self.ledgers=[self.ledger(i) for i in range(3)]
        self.authority=self.ledgers[0]

    def ledger(self,index,network='f'*64):
        return token.TestTokenLedger(network,self.descriptor,self.roster,self.coordinator,
            self.peers[index],self.signers[index],self.identities[0] if index==0 else None)

    def signed_transaction(self,body,signer=0,domain=token._TX):
        return {'body':body,'signature':self.signers[signer].sign_message(domain+pack(body)).hex()}

    def signed_receipt(self,body):
        return {'body':body,'signature':self.identities[0].sign_message(token._RECEIPT+pack(body)).hex()}

    def assert_unchanged(self,ledger,before):
        self.assertEqual(ledger.snapshot(),before)

    def test_exact_balances_nonces_supply_and_replicated_roots(self):
        receipts=self.authority.commit_batch(self.authority.sign_batch(self.peers[1],'7',3))
        for follower in self.ledgers[1:]:
            follower.apply_receipts(receipts)
            self.assertEqual(follower.status(),self.authority.status())
        rows={row['peer_key']:row for row in self.authority.snapshot()['accounts']}
        self.assertEqual(rows[self.peers[0]]['balance_atomic'],'999999979')
        self.assertEqual(rows[self.peers[1]]['balance_atomic'],'1000000021')
        self.assertEqual([rows[peer]['nonce'] for peer in self.peers],[3,0,0])
        self.assertEqual(sum(int(row['balance_atomic']) for row in rows.values()),3_000_000_000)

    def test_each_peer_signs_its_own_account(self):
        tx=self.ledgers[1].sign_batch(self.peers[2],'17')
        receipt=self.authority.commit_batch(tx)
        for follower in self.ledgers[1:]:follower.apply_receipts(receipt)
        forged=deepcopy(tx[0]);forged['body']['nonce']=1
        forged=self.signed_transaction(forged['body'],signer=0)
        before=self.authority.snapshot()
        with self.assertRaises(ValueError):self.authority.commit_batch([forged])
        self.assert_unchanged(self.authority,before)
        with self.assertRaisesRegex(ValueError,'GG_LAN_TOKEN_OWN_SIGNER'):
            token.TestTokenLedger('f'*64,self.descriptor,self.roster,self.coordinator,
                                  self.peers[1],self.signers[0])

    def test_bad_amounts_and_boolean_counts_cannot_sign(self):
        invalid=(0,1,True,None,'0','-1','01','1.0','1e3',' 1','1 ',str(2**63),'9'*100)
        before=self.authority.snapshot()
        for amount in invalid:
            with self.subTest(amount=amount):
                with self.assertRaises(ValueError):self.authority.sign_batch(self.peers[1],amount)
        for count in (True,False,0,17,1.0):
            with self.subTest(count=count):
                with self.assertRaises(ValueError):self.authority.sign_batch(self.peers[1],'1',count)
        self.assert_unchanged(self.authority,before)

    def test_overspend_and_nonlocal_balance_are_not_authority(self):
        with self.assertRaises(ValueError):self.authority.sign_batch(self.peers[1],'1000000001')
        tx=self.authority.sign_batch(self.peers[1],'1')[0]
        tx['body']['amount_atomic']='1000000001'
        before=self.authority.snapshot()
        with self.assertRaises(ValueError):self.authority.commit_batch([self.signed_transaction(tx['body'])])
        self.assert_unchanged(self.authority,before)
        with self.assertRaisesRegex(ValueError,'GG_LAN_TOKEN_COORDINATOR_REQUIRED'):
            self.ledgers[1].commit_batch(self.ledgers[1].sign_batch(self.peers[2],'1'))

    def test_signed_domain_changes_and_wrong_signature_are_atomic(self):
        template=self.authority.sign_batch(self.peers[1],'1')[0]
        changes=({'network_id':'e'*64},{'asset':'GG'},{'schema':'gg.lan-test-token.transfer.v2'},
                 {'nonce':True},{'nonce':1},{'recipient_peer_key':self.peers[0]},
                 {'extra':1})
        for change in changes:
            with self.subTest(change=change):
                body={**template['body'],**change};before=self.authority.snapshot()
                with self.assertRaises(ValueError):self.authority.commit_batch([self.signed_transaction(body)])
                self.assert_unchanged(self.authority,before)
        wrong_domain=self.signed_transaction(template['body'],domain=b'GG-DAG-TRANSFER-v1\0')
        with self.assertRaises(ValueError):self.authority.commit_batch([wrong_domain])
        damaged=deepcopy(template);damaged['signature']='0'*128
        with self.assertRaises(ValueError):self.authority.commit_batch([damaged])
        with self.assertRaises(ValueError):self.ledger(0,network='e'*64).commit_batch([template])

    def test_invalid_second_transaction_rolls_back_entire_batch(self):
        transactions=self.authority.sign_batch(self.peers[1],'9',2)
        transactions[1]['signature']='0'*128
        before=self.authority.snapshot()
        with self.assertRaises(ValueError):self.authority.commit_batch(transactions)
        self.assert_unchanged(self.authority,before)
        transactions=self.authority.sign_batch(self.peers[1],'9',2)
        transactions[1]['body']['nonce']=0
        transactions[1]['body']['amount_atomic']='10'
        transactions[1]=self.signed_transaction(transactions[1]['body'])
        with self.assertRaises(ValueError):self.authority.commit_batch(transactions)
        self.assert_unchanged(self.authority,before)

    def test_retries_are_idempotent_and_old_nonce_cannot_change_transfer(self):
        transactions=self.authority.sign_batch(self.peers[1],'3',2)
        receipts=self.authority.commit_batch(transactions)
        before=self.authority.snapshot()
        self.assertEqual(self.authority.commit_batch(transactions),receipts)
        self.assert_unchanged(self.authority,before)
        for follower in self.ledgers[1:]:
            follower.apply_receipts(receipts);before_follower=follower.snapshot()
            follower.apply_receipts(receipts);self.assert_unchanged(follower,before_follower)
        changed=deepcopy(transactions[0]);changed['body']['amount_atomic']='4'
        with self.assertRaises(ValueError):self.authority.commit_batch([self.signed_transaction(changed['body'])])
        self.assert_unchanged(self.authority,before)

    def test_duplicate_transaction_batch_replicates_successfully(self):
        transaction=self.authority.sign_batch(self.peers[1],'3')[0]
        receipts=self.authority.commit_batch([transaction,transaction])
        for follower in self.ledgers[1:]:
            follower.apply_receipts(receipts)
            self.assertEqual(follower.status(),self.authority.status())
        self.assertEqual(self.authority.revision(),1)

    def test_receipt_signature_domain_hash_and_root_rejections_are_atomic(self):
        receipts=self.authority.commit_batch(self.authority.sign_batch(self.peers[1],'2',2))
        for change in ({'state_root':'0'*64},{'previous':'0'*64},
                       {'transaction_id':'0'*64},{'network_id':'e'*64},
                       {'sequence':3},{'sequence':True}):
            with self.subTest(change=change):
                broken=deepcopy(receipts);broken[1]=self.signed_receipt({**broken[1]['body'],**change})
                before=self.ledgers[1].snapshot()
                with self.assertRaises(ValueError):self.ledgers[1].apply_receipts(broken)
                self.assert_unchanged(self.ledgers[1],before)
        broken=deepcopy(receipts);broken[1]['signature']='0'*128
        with self.assertRaises(ValueError):self.ledgers[1].apply_receipts(broken)
        self.assertEqual(self.ledgers[1].revision(),0)

    def test_changed_committed_receipt_detects_coordinator_equivocation(self):
        receipts=self.authority.commit_batch(self.authority.sign_batch(self.peers[1],'2'))
        self.ledgers[1].apply_receipts(receipts)
        body={**receipts[0]['body'],'state_root':'0'*64}
        before=self.ledgers[1].snapshot()
        with self.assertRaisesRegex(ValueError,'GG_LAN_TOKEN_COORDINATOR_EQUIVOCATION'):
            self.ledgers[1].apply_receipts([self.signed_receipt(body)])
        self.assert_unchanged(self.ledgers[1],before)

    def test_hash_chain_and_receipts_are_deterministic(self):
        transactions=self.authority.sign_batch(self.peers[1],'11',3)
        receipts=self.authority.commit_batch(transactions)
        other=self.ledger(0)
        self.assertEqual(other.commit_batch(transactions),receipts)
        self.assertEqual(other.status(),self.authority.status())
        self.assertEqual(receipts[1]['body']['previous'],
                         digest(receipts[0]['body'],b'GG-LAN-TEST-TOKEN-RECEIPT-ID-v1\0'))

    def test_caps_cursors_and_snapshot_truth(self):
        self.assertEqual(token.MAX_TRANSFERS,4096);self.assertEqual(token.MAX_BATCH,16)
        for malformed in ([],[{}]*17,None):
            with self.assertRaises(ValueError):self.authority.commit_batch(malformed)
        for after,limit in ((True,1),(1,1),(0,True),(0,17),(-1,1)):
            with self.assertRaises(ValueError):self.authority.records(after,limit)
        body=self.authority.snapshot()
        self.assertFalse(body['financial_assets']);self.assertFalse(body['dag_finality'])
        self.assertEqual(body['authority'],'SINGLE_PAIRED_COORDINATOR')
        self.assertEqual(body['scope'],'PRIVATE_COORDINATOR_ORDERED_TEST_LEDGER')

    def test_expiration_during_receipt_signing_publishes_no_partial_batch(self):
        transactions=self.authority.sign_batch(self.peers[1],'1')
        before=self.authority.snapshot();now=[100.0]
        original=self.authority._authority.sign_message
        def delayed_signature(*args,**kwargs):
            signature=original(*args,**kwargs);now[0]+=.002
            return signature
        def permitted():
            if now[0]>=100.001:raise ValueError('GG_LAN_CIRCLE_DEADLINE')
        with patch.object(self.authority._authority,'sign_message',side_effect=delayed_signature):
            with self.assertRaisesRegex(ValueError,'GG_LAN_CIRCLE_DEADLINE'):
                self.authority.commit_batch(transactions,check=permitted)
        self.assert_unchanged(self.authority,before)


class TestCircleSigningAudit(unittest.TestCase):
    """Call the real signing policy without a listener or transport workload."""
    def setUp(self):
        self.nodes=[lan.LanDagPeer(f'synthetic-{i}',allow_test_tokens=True) for i in range(3)]
        roster=[{'peer_key':peer.public_key,'producer_keys':[key.pubkey().hex() for key in peer._local_keys],
                 'label':peer.label} for peer in self.nodes]
        self.coordinator=self.nodes[0].public_key
        self.ring=[peer.public_key for peer in self.nodes]
        descriptor=token.genesis(roster,self.coordinator)
        for peer in self.nodes:
            peer._network='f'*64;peer._trusted=self.coordinator
            peer._roster={row['peer_key']:row for row in roster}
            peer._tokens=token.TestTokenLedger('f'*64,descriptor,roster,self.coordinator,
                peer.public_key,peer._local_keys[0],peer._identity if peer==self.nodes[0] else None)
        self.participant=self.nodes[1]

    def tearDown(self):
        for peer in self.nodes:peer.stop()

    def plan(self,number=1,**changes):
        body={'schema':'gg.lan-test-token.circle.v1','network_id':'f'*64,'run_id':f'{number:064x}',
              'ring':self.ring,'amount_atomic':'1','batch':1,'duration_ms':60000,
              'max_transfers':4096,'initial_sequence':0,'initial_head':self.participant._tokens.head_at(0)}
        body.update(changes)
        return lan._signed(self.nodes[0]._identity,lan._CIRCLE,body)

    def sign(self,plan,peer=None):
        return self.participant._token_command(peer or self.coordinator,'CIRCLE_SIGN',
                                               {'plan':plan,'records':[],'count':1})

    def test_remote_signing_is_coordinator_only_and_follows_fixed_ring(self):
        plan=self.plan()
        with self.assertRaises(ValueError):self.sign(plan,peer=self.nodes[2].public_key)
        transactions=self.sign(plan)['transactions']
        self.assertEqual(len(transactions),1)
        self.assertEqual(transactions[0]['body']['sender_peer_key'],self.nodes[1].public_key)
        self.assertEqual(transactions[0]['body']['recipient_peer_key'],self.nodes[2].public_key)
        self.nodes[0]._tokens.commit_batch(transactions)

    def test_plan_domain_and_limits_cannot_authorize_signing(self):
        for changes in ({'network_id':'e'*64},{'duration_ms':60001},{'duration_ms':True},
                        {'batch':17},{'max_transfers':4097},{'ring':list(reversed(self.ring))}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):self.sign(self.plan(**changes))
        self.assertEqual(self.participant._tokens.revision(),0)

    def test_retired_plan_cannot_replay_after_more_than_32_runs(self):
        first=self.plan()
        for number in range(1,34):
            current=self.plan(number)
            self.sign(current)
            self.participant._token_command(self.coordinator,'CIRCLE_END',{'run_id':current['body']['run_id']})
        with self.assertRaisesRegex(ValueError,'GG_LAN_CIRCLE_REPLAY'):self.sign(first)

    def test_participant_stop_revokes_its_current_signing_plan(self):
        plan=self.plan();self.sign(plan)
        self.participant.stop_token_circle()
        with self.assertRaises(ValueError):self.sign(plan)

    def test_stop_during_first_sign_does_not_return_transactions(self):
        plan=self.plan();original=self.participant._tokens.sign_batch
        def stopped_sign(*args,**kwargs):
            transactions=original(*args,**kwargs)
            self.participant.stop_token_circle()
            return transactions
        with patch.object(self.participant._tokens,'sign_batch',side_effect=stopped_sign):
            with self.assertRaisesRegex(ValueError,'GG_LAN_CIRCLE_CANCELLED'):self.sign(plan)
        with self.assertRaises(ValueError):self.sign(plan)
        self.assertEqual(self.participant._tokens.revision(),0)

    def test_expiration_during_account_signing_returns_no_transactions(self):
        plan=self.plan(duration_ms=10000);now=[100.0]
        original=self.participant._tokens._signer.sign_message
        def delayed_signature(*args,**kwargs):
            signature=original(*args,**kwargs);now[0]+=.002
            return signature
        with patch.object(lan.time,'monotonic',side_effect=lambda:now[0]), \
             patch.object(self.participant._tokens._signer,'sign_message',side_effect=delayed_signature):
            with self.assertRaisesRegex(ValueError,'GG_LAN_CIRCLE_DEADLINE'):
                self.participant._token_command(self.coordinator,'CIRCLE_SIGN',
                    {'plan':plan,'records':[],'count':1,'budget_ms':1})
        self.assertEqual(self.participant._tokens.revision(),0)

    def test_stale_peer_sync_exhausts_one_shared_budget_before_signing(self):
        coordinator=self.nodes[0];ledger=coordinator._tokens
        ledger.commit_batch(ledger.sign_batch(self.nodes[1].public_key,'1',2))
        plan=self.plan(duration_ms=1,initial_sequence=2,initial_head=ledger.head_at(2))
        now=[100.0];requests=[];peers={peer.public_key:peer for peer in self.nodes}
        def bounded_rpc(peer,kind,payload,*,cancel=None,deadline=None):
            self.assertIsNotNone(deadline)
            requests.append((kind,deadline));now[0]+=.0006
            if now[0]>=deadline:raise ValueError('GG_LAN_CIRCLE_DEADLINE')
            remote=peers[peer]
            if kind in ('TOKEN_STATUS','CIRCLE_END'):return remote._tokens.status()
            if kind=='TOKEN_APPLY':return remote._tokens.apply_receipts(payload['records'])
            self.fail(f'unexpected request after stale sync: {kind}')
        with patch.object(lan.time,'monotonic',side_effect=lambda:now[0]), \
             patch.object(coordinator,'_token_rpc',side_effect=bounded_rpc):
            coordinator._circle_loop(plan,coordinator._circle_cancel)
        work=[deadline for kind,deadline in requests if kind!='CIRCLE_END']
        cleanup=[deadline for kind,deadline in requests if kind=='CIRCLE_END']
        self.assertEqual(len(work),2)
        self.assertTrue(all(abs(deadline-100.001)<1e-9 for deadline in work))
        self.assertEqual(len(set(cleanup)),1)
        self.assertLessEqual(cleanup[0]-100.0012,1.000001)
        self.assertEqual(coordinator._circle['state'],'TIME_BUDGET')
        self.assertFalse(coordinator._circle['all_peers_synced'])
        self.assertEqual(coordinator._circle['transactions'],0)
        self.assertEqual(ledger.revision(),2)

    def test_rpc_pacing_stops_at_deadline_before_opening_a_socket(self):
        coordinator=self.nodes[0];target=self.nodes[1].public_key;now=[100.0];waits=[]
        coordinator._token_rpc_times[target]=100.0
        class Cancel:
            def is_set(self):return False
            def wait(self,delay):waits.append(delay);now[0]+=delay;return False
        with patch.object(lan.time,'monotonic',side_effect=lambda:now[0]), \
             patch.object(lan.socket,'create_connection') as connect:
            with self.assertRaisesRegex(ValueError,'GG_LAN_CIRCLE_DEADLINE'):
                coordinator._token_rpc(target,'TOKEN_STATUS',{},cancel=Cancel(),deadline=100.001)
        connect.assert_not_called()
        self.assertEqual(len(waits),1);self.assertLessEqual(waits[0],.001001)

    def test_legacy_constructor_keeps_test_tokens_off_and_stop_clears_signers(self):
        peer=lan.LanDagPeer('synthetic-legacy','127.0.0.1',0,None,False)
        self.assertFalse(peer.allow_test_tokens);self.assertIsNone(peer._tokens)
        self.assertEqual(peer._closed_circle_ids,set())
        self.assertFalse(peer.token_snapshot()['enabled'])
        peer.stop()
        self.assertIsNone(peer._identity);self.assertEqual(peer._local_keys,[])


if __name__=='__main__':unittest.main()
