"""Actual four-process GG consensus and adversarial controller boundaries.

All identities belong to new disposable fixtures. No running desktop node,
remembered wallet key, public chain or arbitrary endpoint is used.
"""
from collections import OrderedDict, deque
from contextlib import ExitStack
from copy import deepcopy
import base64
import hashlib
import http.client
import json
from pathlib import Path
import socket
import subprocess
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from backend.gg_ed25519 import Keypair
from backend import gg_consensus as node


@unittest.skipUnless(node.available(), 'Optional pinned GG consensus engine is not installed')
class FourProcessConsensusTests(unittest.TestCase):
    def setUp(self):
        self.processes=[]
        try:
            self.initial=node.start()
            self.processes=[n['process'] for n in node._nodes]
        except Exception:
            node.stop()
            raise

    def tearDown(self):
        node.stop()
        for process in self.processes:
            self.assertIsNotNone(process.poll(), 'OWNED_CONSENSUS_PROCESS_SURVIVED')

    def wait(self,predicate,timeout=15):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            try:
                value=predicate()
                if value:return value
            except (ValueError,KeyError,TypeError,OSError,http.client.HTTPException):
                pass
            time.sleep(.05)
        self.fail('CONSENSUS_FIXTURE_TIMEOUT')

    def transfer(self,source,target,quantity):
        review=node.prepare(source,node._genesis['accounts'][target],quantity)['review']
        self.assertIsNotNone(review)
        result=node.send(review['id'],review['review_digest'])
        record=node._transactions[0]
        self.assertEqual(record['state'],'FINALIZED')
        self.assertTrue(record['execution_verified'])
        self.assertEqual(record['certificate_height'],record['height']+1)
        return result,record

    def state(self):
        return node._verified_state()[1]

    def test_real_processes_exact_roundtrip_certificates_proofs_and_no_secret_files(self):
        self.assertEqual(self.initial['state'],'RUNNING')
        self.assertEqual(self.initial['online'],4)
        self.assertEqual(self.initial['physical_hosts'],1)
        self.assertEqual(self.initial['operator_count'],1)
        self.assertFalse(self.initial['production'])
        self.assertEqual(len({p.pid for p in self.processes}),4)
        self.assertEqual(len(set(node._genesis['validators'])),4)
        self.assertTrue(all(node._owned(i) for i in range(4)))
        self.assertTrue(all(v['identity_verified'] and v['peers']>=1 for v in self.initial['validators']))
        self.assertTrue(all(a['quantity']=='250000' for a in self.initial['accounts']))
        before=self.state()
        sent,record=self.transfer(0,1,'1.000001')
        self.assertEqual(sent['accounts'][0]['quantity'],'249998.999999')
        self.assertEqual(sent['accounts'][1]['quantity'],'250001.000001')
        index,_,_=node._verified_state()
        height=record['height']
        header=node._rpc(index,'commit',{'height':str(height+1)})['signed_header']
        state=node._read_state_at(index,height)
        payload=node._proof_payload(state,header)
        payload['account_proof']=node._query(index,'/gg/proof',height,bytes.fromhex(node._genesis['accounts'][0]))
        verified=node._verify(payload)
        self.assertTrue(verified['account_proof_verified'])
        self.assertEqual(verified['certificate_height'],height+1)
        # Public state, its witness, the genesis trust anchor and the quorum
        # are all needed; none can be replaced by a plausible display value.
        corruptions=[]
        wrong=deepcopy(payload);wrong['state']['accounts'][0]['balance_atomic']='1';corruptions.append(wrong)
        wrong=deepcopy(payload);wrong['state']['height']+=1;corruptions.append(wrong)
        wrong=deepcopy(payload);wrong['genesis_hash']='0'*64;corruptions.append(wrong)
        wrong=deepcopy(payload);wrong['account_proof']['leaf']['balance_atomic']='1';corruptions.append(wrong)
        wrong=deepcopy(payload);wrong['signed_header']['commit']['signatures']=wrong['signed_header']['commit']['signatures'][:2];corruptions.append(wrong)
        wrong=deepcopy(payload)
        signatures=wrong['signed_header']['commit']['signatures']
        signed=next(s for s in signatures if s.get('signature'))
        wrong['signed_header']['commit']['signatures']=[deepcopy(signed)]*3;corruptions.append(wrong)
        wrong=deepcopy(payload);wrong['signed_header']=node._rpc(index,'commit',{'height':str(height)})['signed_header'];corruptions.append(wrong)
        for number,wrong in enumerate(corruptions):
            with self.subTest(corruption=number),self.assertRaisesRegex(ValueError,'CERTIFICATE_INVALID'):
                node._verify(wrong)
        # Committed transaction replay does not debit a sender twice.
        old=bytes(record['_raw'])
        try:
            response=node._rpc(index,'broadcast_tx_sync',{'tx':'0x'+old.hex()})
            self.assertNotEqual(int(response.get('code',0)),0)
        except node.RpcUnavailable:
            # Comet may reject an already-cached transaction as a top-level
            # RPC error before the application's CheckTx result is returned.
            pass
        self.transfer(1,0,'1.000001')
        after=self.state()
        self.assertEqual({a['address']:a['balance_atomic'] for a in before['accounts']},
                         {a['address']:a['balance_atomic'] for a in after['accounts']})
        # Invalid requests are rejected at CheckTx before changing state.
        source=node._genesis['accounts'][0];target=node._genesis['accounts'][1]
        nonce=node._account_map(after)[source]['nonce']
        valid=json.loads(node._signed_transaction(0,target,'1',nonce))
        malformed=[]
        for key,value in [('chain_id','ggnet:'+'0'*24),('genesis_hash','0'*64),('nonce',nonce-1),('nonce',nonce+256)]:
            envelope=deepcopy(valid);envelope['body'][key]=value
            envelope['signature']=bytes(node._accounts[0].sign_message(node._pack(envelope['body']))).hex()
            malformed.append(node._pack(envelope))
        envelope=deepcopy(valid);envelope['signature']='0'*128;malformed.append(node._pack(envelope))
        envelope=deepcopy(valid);envelope['body']['amount_atomic']='2';malformed.append(node._pack(envelope))
        for number,raw in enumerate(malformed):
            with self.subTest(invalid_transaction=number):
                rejected=node._rpc(index,'broadcast_tx_sync',{'tx':'0x'+raw.hex()})
                self.assertNotEqual(int(rejected.get('code',0)),0)
        current=self.state()
        self.assertEqual(current['state_root'],after['state_root'])
        self.wait(lambda:all(node._read_state_at(i,current['height'])['state_root']==current['state_root'] for i in range(4)))
        # Stop only this fixture's children before inspecting their public WAL
        # and databases. Keys stay in this test's RAM and never enter failures.
        secrets=[]
        for key in [*node._accounts,*node._validator_keys,*node._node_keys]:
            raw=bytes(key);seed=raw[:32]
            secrets.extend((seed,seed.hex().encode(),base64.b64encode(seed),raw,raw.hex().encode(),base64.b64encode(raw)))
        directories=[Path(n['root']) for n in node._nodes]
        for i in range(4):node._stop_process(i)
        inspected=0
        for directory in directories:
            self.assertTrue((directory/'data/priv_validator_state.json').is_file())
            self.assertFalse((directory/'config/priv_validator_key.json').exists())
            self.assertFalse((directory/'config/node_key.json').exists())
            for path in directory.rglob('*'):
                if not path.is_file():continue
                with path.open('rb') as file:
                    carry=b''
                    while True:
                        chunk=file.read(65536)
                        if not chunk:break
                        body=carry+chunk
                        self.assertFalse(any(secret in body for secret in secrets),'PRIVATE_KEY_BYTES_PERSISTED')
                        carry=body[-256:]
                inspected+=1
        self.assertGreater(inspected,12)

    def test_real_quorum_loss_restart_and_original_hash_recovery(self):
        _,before,_=node._verified_state()
        node.stop_node(3)
        self.assertIsNone(node._nodes[3]['process'])
        self.transfer(0,1,'0.000001')
        node.stop_node(2)
        self.assertEqual(sum(node._alive(i) for i in range(4)),2)
        time.sleep(.2)
        index,state,_=node._verified_state()
        head=int(node._status(index)['sync_info']['latest_block_height'])
        nonce=node._account_map(state)[node._genesis['accounts'][0]]['nonce']
        raw=node._signed_transaction(0,node._genesis['accounts'][1],'1',nonce)
        record=node._submit(raw,{'sender':node._genesis['accounts'][0],
            'recipient':node._genesis['accounts'][1],'amount':'0.000001'},wait=0)
        original_hash=record['hash']
        self.assertIn(record['state'],{'SUBMITTED','BROADCAST_UNKNOWN'})
        time.sleep(.7)
        self.assertFalse(node._reconcile(record))
        self.assertEqual(int(node._status(index)['sync_info']['latest_block_height']),head)
        self.assertEqual(self.state()['state_root'],state['state_root'])
        with self.assertRaisesRegex(ValueError,'NO_QUORUM'):
            node.prepare(0,node._genesis['accounts'][1],'1')
        # Restart retains the SAME public validator keys and anti-double-sign
        # histories. No fresh transaction is signed to recover this request.
        validators=list(node._genesis['validators'])
        node.restart_node(2);node.restart_node(3)
        self.processes.extend(n['process'] for n in node._nodes if n['process'] not in self.processes)
        self.assertEqual(node._genesis['validators'],validators)
        self.assertTrue(node._reconcile(record,timeout=20))
        self.assertEqual(record['hash'],original_hash)
        self.assertEqual(record['_raw'],raw)
        self.assertTrue(record['execution_verified'])
        self.assertEqual(record['certificate_height'],record['height']+1)
        # Two one-atomic-unit sends out are returned as one exact send back.
        self.transfer(1,0,'0.000002')
        current=self.state()
        self.assertEqual({a['address']:a['balance_atomic'] for a in current['accounts']},
                         {a['address']:a['balance_atomic'] for a in before['accounts']})
        self.wait(lambda:all(node._read_state_at(i,current['height'])['state_root']==current['state_root'] for i in range(4)))
        self.assertEqual(node.snapshot()['state'],'RUNNING')


class ConsensusControllerGuards(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack()
        keys=[Keypair() for _ in range(4)]
        genesis={'schema':'gg.native.genesis.v1','chain_id':'ggnet:'+'a'*24,'genesis_time_unix':1700000000,
                 'accounts':[node._public(k) for k in keys],'validators':[node._public(Keypair()) for _ in range(4)],
                 'supply_atomic':str(node.SUPPLY),'decimals':6,'symbol':node.SYMBOL}
        values={'_closed':False,'_temporary':None,'_genesis':genesis,'_genesis_hash':node._digest(genesis),
                '_accounts':keys,'_validator_keys':[],'_node_keys':[],'_nodes':[], '_review':None,
                '_transactions':deque(maxlen=64),'_measurements':deque(maxlen=32),'_events':deque(maxlen=48),
                '_certificate_cache':{},'_execution_cache':OrderedDict(),'_last_state':None,'_last_proof':None,
                '_last_test':None,'_benchmark':None,'_submitted':0,'_connections':{},'_binary_stamp':None}
        for name,value in values.items():self.stack.enter_context(patch.object(node,name,value))
        self.state={'height':3,'chain_id':genesis['chain_id'],'genesis_hash':node._genesis_hash,'state_root':'b'*64,
                    'accounts':[{'address':a,'balance_atomic':str(node.SUPPLY//4),'nonce':0} for a in genesis['accounts']]}

    def tearDown(self):self.stack.close()

    def review(self,**changes):
        review={'id':'fixture-review','chain_id':node._genesis['chain_id'],'genesis_hash':node._genesis_hash,
                'sender_index':0,'sender':node._genesis['accounts'][0],'recipient':node._genesis['accounts'][1],
                'amount':'1','atomic':'1000000','symbol':node.SYMBOL,'nonce':0,'expires_at':time.time()+120}
        review.update(changes);review['review_digest']=node._digest(review);node._review=review
        return deepcopy(review)

    def send_mocks(self):
        self.stack.enter_context(patch.object(node,'_alive',return_value=True))
        self.stack.enter_context(patch.object(node,'_verified_state',return_value=(0,self.state,{})))
        self.stack.enter_context(patch.object(node,'snapshot',return_value={}))
        return self.stack.enter_context(patch.object(node,'_submit',return_value={}))

    def test_exact_review_id_digest_single_use_and_cancellation(self):
        submit=self.send_mocks();review=self.review()
        for identifier,digest in [('wrong',review['review_digest']),(review['id'],'wrong')]:
            with self.assertRaisesRegex(ValueError,'REVIEW_REQUIRED'):node.send(identifier,digest)
        node.send(review['id'],review['review_digest']);submit.assert_called_once()
        self.assertIsNone(node._review)
        with self.assertRaisesRegex(ValueError,'REVIEW_REQUIRED'):node.send(review['id'],review['review_digest'])
        self.review();node.cancel_review();self.assertIsNone(node._review)

    def test_review_content_is_bound_and_invalidated_before_execution(self):
        submit=self.send_mocks()
        for key,value in [('amount','2'),('atomic','2'),('recipient',node._genesis['accounts'][2]),('nonce',1),('sender_index',1)]:
            review=self.review();node._review[key]=value
            with self.subTest(field=key),self.assertRaisesRegex(ValueError,'REVIEW_CHANGED'):
                node.send(review['id'],review['review_digest'])
            self.assertIsNone(node._review);submit.assert_not_called()

    def test_expired_wrong_chain_or_genesis_review_never_submits(self):
        submit=self.send_mocks()
        for change in ({'expires_at':time.time()-1},{'chain_id':'ggnet:'+'f'*24},{'genesis_hash':'f'*64}):
            review=self.review(**change)
            with self.subTest(change=list(change)),self.assertRaisesRegex(ValueError,'EXPIRED'):
                node.send(review['id'],review['review_digest'])
            self.assertIsNone(node._review);submit.assert_not_called()

    def test_nonce_balance_quorum_or_unresolved_drift_blocks_send(self):
        submit=self.send_mocks()
        for field,value,code in [('nonce',1,'NONCE_CHANGED'),('balance_atomic','0','INSUFFICIENT_FUNDS')]:
            review=self.review();self.state['accounts'][0][field]=value
            with self.assertRaisesRegex(ValueError,code):node.send(review['id'],review['review_digest'])
            self.assertIsNone(node._review);submit.assert_not_called()
            self.state['accounts'][0].update(nonce=0,balance_atomic=str(node.SUPPLY//4))
        review=self.review()
        with patch.object(node,'_alive',side_effect=lambda i:i<2),self.assertRaisesRegex(ValueError,'NO_QUORUM'):
            node.send(review['id'],review['review_digest'])
        review=self.review();node._transactions.append({'state':'BROADCAST_UNKNOWN'})
        with self.assertRaisesRegex(ValueError,'UNRESOLVED_TRANSACTION'):node.send(review['id'],review['review_digest'])
        submit.assert_not_called()

    def test_prepare_rejects_bad_sender_recipient_amount_and_unresolved_state(self):
        with patch.object(node,'_alive',return_value=True),patch.object(node,'_verified_state',return_value=(0,self.state,{})),patch.object(node,'snapshot',return_value={}):
            recipient=node._genesis['accounts'][1]
            for sender,target,amount in [(True,recipient,'1'),(-1,recipient,'1'),(4,recipient,'1'),
                (0,node._genesis['accounts'][0],'1'),(0,'0'*64,'1'),(0,recipient,'0'),(0,recipient,'1e2'),
                (0,recipient,'0.0000001'),(0,recipient,1.1),(0,recipient,'250001')]:
                with self.subTest(sender=sender,amount=amount),self.assertRaises(ValueError):node.prepare(sender,target,amount)
                self.assertIsNone(node._review)
            for state in ('SUBMITTED','BROADCAST_UNKNOWN'):
                node._transactions.clear();node._transactions.append({'state':state})
                with self.assertRaisesRegex(ValueError,'UNRESOLVED_TRANSACTION'):node.prepare(0,recipient,'1')

    def test_uncertain_broadcast_has_known_hash_and_no_write_retry(self):
        raw=b'public-synthetic-transaction'
        with patch.object(node,'_verified_state',return_value=(0,self.state,{})),\
             patch.object(node,'_rpc',side_effect=OSError('synthetic disconnect')) as rpc,\
             patch.object(node,'_reconcile',return_value=False) as reconcile:
            record=node._submit(raw,{'amount':'1'},wait=0)
        self.assertEqual(record['state'],'BROADCAST_UNKNOWN')
        self.assertEqual(record['hash'],hashlib.sha256(raw).hexdigest())
        self.assertEqual(record['_raw'],raw)
        self.assertEqual(node._submitted,1);rpc.assert_called_once()
        reconcile.assert_called_once_with(record,0)

    def test_session_quota_and_unknown_rpc_are_rejected_before_io(self):
        node._submitted=node.MAX_TRANSFERS
        with patch.object(node,'_rpc') as rpc:
            with self.assertRaisesRegex(ValueError,'SESSION_LIMIT'):node._submit(b'fixture',{'amount':'1'})
            rpc.assert_not_called()
        for index in (True,-1,4,'0'):
            with self.assertRaisesRegex(ValueError,'NODE_INDEX'):node._index(index)
        for method in ('unsafe_flush_mempool','dial_peers','https://example.invalid','genesis'):
            with self.assertRaisesRegex(ValueError,'RPC_METHOD'):node._rpc(0,method)
        for count in (True,0,3,129,'32'):
            with self.assertRaisesRegex(ValueError,'BENCHMARK_LIMIT'):node.benchmark(count)

    def test_cached_execution_cannot_cross_genesis_or_raw_transaction(self):
        raw=b'signed-public-fixture';txid=hashlib.sha256(raw).hexdigest()
        record={'hash':txid,'_raw':raw,'_started':time.perf_counter(),'state':'SUBMITTED'}
        cached={'genesis_hash':node._genesis_hash,'raw':raw,'height':4,'certificate_height':5}
        node._execution_cache[txid]=cached
        with patch.object(node,'_rpc') as rpc:
            self.assertTrue(node._receipt(0,record));rpc.assert_not_called()
            self.assertTrue(record['execution_verified'])
            cached['genesis_hash']='f'*64
            with self.assertRaisesRegex(ValueError,'CACHED_EXECUTION_CONTEXT'):node._receipt(0,record)
            cached['genesis_hash']=node._genesis_hash;cached['raw']=b'changed'
            with self.assertRaisesRegex(ValueError,'CACHED_EXECUTION_CONTEXT'):node._receipt(0,record)

    def test_failed_cleanup_retains_owned_process_references(self):
        process=MagicMock();process.poll.return_value=None
        node._nodes=[{'process':process}]
        with patch.object(node,'_stop_process',side_effect=ValueError('synthetic stop failure')):
            with self.assertRaisesRegex(ValueError,'STOP_FAILED'):node.stop()
        self.assertIs(node._nodes[0]['process'],process)
        self.assertIsNotNone(node._genesis)

    def test_terminal_shutdown_fences_already_dequeued_start_and_rpc(self):
        dequeued=threading.Event();resume=threading.Event();outcomes=[]
        def worker():
            dequeued.set();resume.wait(2)
            try:node.start();outcomes.append('UNEXPECTED_START')
            except ValueError as error:outcomes.append(str(error))
        with patch.object(node.subprocess,'Popen') as launch,patch.object(node.http.client,'HTTPConnection') as http:
            thread=threading.Thread(target=worker,daemon=True);thread.start()
            try:
                self.assertTrue(dequeued.wait(1));node.shutdown();resume.set();thread.join(2)
                self.assertFalse(thread.is_alive());self.assertEqual(outcomes,['GG_CONSENSUS_SHUTTING_DOWN'])
                with self.assertRaisesRegex(ValueError,'SHUTTING_DOWN'):node._rpc(0,'status')
                launch.assert_not_called();http.assert_not_called()
            finally:resume.set();thread.join(2)

    def test_sdk_timeout_or_launch_failure_is_sanitized_and_fail_closed(self):
        payload={'genesis':{'chain_id':node._genesis['chain_id']},
                 'state':{'height':1,'state_root':'b'*64}}
        for failure in (subprocess.TimeoutExpired('public-verifier',6),OSError('private-fixture-not-for-output')):
            with self.subTest(kind=type(failure).__name__),patch.object(node.subprocess,'run',side_effect=failure):
                with self.assertRaisesRegex(ValueError,'VERIFY_UNAVAILABLE') as caught:node._verify(payload)
                self.assertNotIn('private-fixture',str(caught.exception))


if __name__=='__main__':unittest.main()
