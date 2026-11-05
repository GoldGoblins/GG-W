"""Real creator/worker signatures and durable pool events across stale jobs.

SDK selected-record lookup and producer lifecycle are explicit policy seams,
not certificates or live nodes. Job derivation, immutable creator signatures,
hash work, worker signatures and the protected pool journal run normally. The
separate four-SDK integration verifies the real node/proof boundary.
"""
import base64
from contextlib import ExitStack
from copy import deepcopy
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from backend import gg_protocol_runtime as runtime,gg_protocol_producer as producer
from backend import gg_financial_protocol as protocol,gg_financial_economy as economy
from backend import gg_financial_dag as financial,gg_financial_wire as wire
from backend.gg_financial_pool import PoolBook
from backend.gg_node_store import pack,unpack
from backend.gg_consensus_process import BroadcastPreviouslySeen
from tests.test_protocol_integrated_profiles import public_protocol_pin
from tests.test_financial_general_clients import public_key


class PoolLifecycleOwnerFixture:
    """Weak-referenceable policy owner for the real owner-ended guard."""
    _closed=False;_failed=False


class PoolStaleWorkTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.pin=public_protocol_pin();self.creator=public_key(302);self.worker=public_key(400)
        self.key=self.creator.pubkey().hex();source=self.pin['genesis']['financial_dag']
        origin=hashlib.sha256(financial.DOMAIN+b'DAG-GENESIS\0'+pack({'anchor':self.pin['genesis_hash'],'source':financial.source_hash(source)})).hexdigest()
        body={'created_at_ns':source['started_at_ns'],'epoch':'1','genesis_hash':self.pin['genesis_hash'],'parents':[origin],
            'payment_root':wire.payment_root([]),'payments':[],'producer_key':self.key,'rank':'1','schema':'gg.financial-dag.block.v2',
            'sequence':'1','source_hash':financial.source_hash(source)}
        self.core={'body':body,'signature':self.creator.sign_message(financial.DOMAIN+b'DAG-BLOCK-SIGN-v2\0'+pack(body)).hex()}
        self.identifier=producer.core_id(self.core)
        self.record={'sequence':'0','rank':'0','head':origin,'invite':deepcopy(self.pin['genesis']['protocol']['initial_producers'][0])}
        self.packet={'state':{'height':10,'financial_dag':{'epoch':'1'},'protocol':{'economics':{'next_epoch':'0'},
            'work_anchor_height':'8','work_anchor_root':'a'*64,'work_target':'f'*64,'time_ns':source['started_at_ns']}}}
        self.lookup_calls=[]
        def selected_record(packet,trust,**options):
            self.lookup_calls.append(deepcopy(packet))
            return {'financial_registry_exists':True,'financial_registry_value':base64.b64encode(pack(self.record)).decode()}
        self.stack.enter_context(patch.object(protocol,'verify_selected',side_effect=selected_record))
        self.job=protocol.derive_block_job(self.core,self.packet,self.pin,self.key,self.worker.pubkey().hex(),'f'*64)
        self.solution,_,_=economy.mine_work(self.job.document(),self.worker,0,1)
        self.assertIsNotNone(self.solution)
        self.book=PoolBook.create(Path(self.temp.name)/'pool',public_key(300),self.pin,public_key(303).pubkey().hex(),public_key(303).pubkey().hex(),1000)
        self.addCleanup(self.book.close)
        self.assignment=self.book.register_job(self.job,public_key(401).pubkey().hex())['body']['assignment']
        self.share={'assignment':self.assignment,'solution':deepcopy(self.solution)}
        self.db=sqlite3.connect(':memory:');self.addCleanup(self.db.close)
        self.db.execute('CREATE TABLE protocol_work(identifier TEXT PRIMARY KEY,packet BLOB,wire BLOB)')
        self.db.execute('CREATE TABLE protocol_cores(identifier TEXT,producer TEXT,sequence INTEGER,core BLOB)')
        self.db.execute('CREATE INDEX protocol_active ON protocol_cores(producer,sequence) WHERE core IS NOT NULL')
        self.db.execute('INSERT INTO protocol_cores VALUES(?,?,?,?)',(self.identifier,self.key,1,pack(self.core)))
        self.profile=SimpleNamespace(_lock=threading.RLock(),_db=self.db,_meta={'protocol_producer':{'work':{}}})
        from backend.gg_protocol_node import OwnedProtocolNode
        self.node=OwnedProtocolNode.__new__(OwnedProtocolNode)
        # Declared lifecycle seam only; real process_ready and cancellation
        # guards still run before these signature/journal stale-work cases.
        process=SimpleNamespace(poll=lambda:None)
        self.profile._closed=False;self.profile._failed=False
        self.node.owner=PoolLifecycleOwnerFixture();self.node.profile=self.profile
        self.node._closed=False;self.node._recovering=False;self.node._epoch_stopping=False
        self.node._start_gate=threading.Lock();self.node._stop_signal=threading.Event();self.node.settings={}
        self.node._node={'process':process,'_ready':{'process':process}}
        self.node.anchor=self.pin;self.node.binary=Path('PUBLIC-SDK-LOOKUP-POLICY-SEAM');self.node._stamp=None
        self.live=deepcopy(self.packet);self.node.selected_proof=lambda *args,**kwargs:deepcopy(self.live)
        self.engine=producer.ProtocolProducer.__new__(producer.ProtocolProducer)
        self.engine.profile=self.profile;self.engine.node=self.node;self.engine.anchor=self.pin;self.engine._check=lambda:None
        self.engine.original=lambda identifier:pack(self.core)
        self.engine.reconcile=lambda key:(deepcopy(self.live),deepcopy(self.record))
        def save(state,retain):retain();self.profile._meta['protocol_producer']=deepcopy(state)
        self.engine._save=save;self.engine.submit_pending=lambda key:{'state':'TEST_ONLY_ADMISSION_SEAM','SDK_selected':False}
        self.controller=runtime.ProtocolRuntime();self.controller.node=self.node;self.controller.producer=self.engine
        self.controller._check_work=lambda:None

    def change(self,name):
        if name=='epoch':self.live['state']['protocol']['economics']['next_epoch']='1'
        elif name=='anchor':self.live['state']['protocol'].update(work_anchor_height='9',work_anchor_root='b'*64)
        elif name=='target':self.live['state']['protocol']['work_target']='e'*64
        elif name=='expired':self.live['state']['height']=73
        elif name=='selected-head':self.record.update(sequence='1',head=self.identifier,rank='1')
        else:raise AssertionError(name)

    def test_old_valid_job_is_stale_before_any_share_append_for_each_live_change(self):
        for name in ('epoch','anchor','target','expired','selected-head'):
            self.live=deepcopy(self.packet);self.record.update(sequence='0',rank='0');before=self.book._head['events']
            self.change(name)
            with self.subTest(change=name),self.assertRaisesRegex(ValueError,'^GG_POOL_JOB_STALE$'):
                self.controller._pool_accept_share(self.book,self.share)
            self.assertEqual(self.book._head['events'],before)
            self.assertEqual(self.db.execute('SELECT count(*) FROM protocol_work').fetchone()[0],0)

    def test_invalid_worker_signature_stays_terminal_even_when_context_is_stale(self):
        self.change('epoch');bad=deepcopy(self.share);bad['solution']['signature']='0'*128
        self.lookup_calls.clear();before=self.book._head['events']
        with self.assertRaises(ValueError) as failure:self.controller._pool_accept_share(self.book,bad)
        self.assertNotEqual(str(failure.exception),'GG_POOL_JOB_STALE')
        self.assertEqual(self.lookup_calls,[]);self.assertEqual(self.book._head['events'],before)

    def test_different_self_signed_job_is_not_the_exact_issued_assignment(self):
        self.change('epoch');bad=deepcopy(self.share);job=deepcopy(self.job.document());job['epoch']='1'
        bad['solution'],_,_=economy.mine_work(job,self.worker,0,1)
        with self.assertRaisesRegex(ValueError,'^GG_MINING_WORK_INVALID$'):self.controller._pool_accept_share(self.book,bad)
        self.assertFalse(any(self.book._rows('SHARE','0')))

    def test_second_certified_lookup_rotation_after_admission_is_retryable(self):
        def advance_on_attach(key):
            self.change('epoch');return deepcopy(self.live),deepcopy(self.record)
        self.engine.reconcile=advance_on_attach
        with self.assertRaisesRegex(ValueError,'^GG_POOL_JOB_STALE$'):self.controller._pool_accept_share(self.book,self.share)
        self.assertEqual(len(list(self.book._rows('SHARE','0'))),1)
        self.assertEqual(self.db.execute('SELECT count(*) FROM protocol_work').fetchone()[0],0)
        # A retained low-difficulty share is accounting, never certified money.
        self.assertEqual(self.book._get('INCOME','1'),None)

    def test_exact_fresh_context_keeps_old_optional_attach_call_compatible(self):
        for options in ({},{'expected_job':self.job}):
            with self.subTest(optional_context=bool(options)):
                result=self.engine.attach_work(self.identifier,self.solution,**options)
                self.assertEqual(result['state'],'DURABLE_NETWORK_WORK');self.assertFalse(result['SDK_selected'])
                raw=self.db.execute('SELECT wire FROM protocol_work WHERE identifier=?',(self.identifier,)).fetchone()[0]
                self.assertEqual(unpack(raw),{**self.core,'work':self.solution})

    def ready_submission(self):
        self.engine.attach_work(self.identifier,self.solution)
        self.live['state']['financial_dag']['checkpoint']='0'
        self.engine.submit_pending=producer.ProtocolProducer.submit_pending.__get__(self.engine)

    def test_cached_broadcast_preserves_original_and_work_without_selection_claim(self):
        self.ready_submission()
        originals=list(self.db.execute('SELECT * FROM protocol_cores'));work=list(self.db.execute('SELECT * FROM protocol_work'))
        state=deepcopy(self.profile._meta)
        with patch.object(self.node,'_rpc',side_effect=BroadcastPreviouslySeen()):
            result=self.engine.submit_pending(self.key)
        self.assertEqual(result,{'state':'BROADCAST_PREVIOUSLY_SEEN','blocks':1,'SDK_selected':False,'payments_executed_asserted':False})
        self.assertEqual(list(self.db.execute('SELECT * FROM protocol_cores')),originals)
        self.assertEqual(list(self.db.execute('SELECT * FROM protocol_work')),work)
        self.assertEqual(self.profile._meta,state)
        for error in (ValueError('GG_VALIDATOR_RPC_UNAVAILABLE'),ValueError('GG_VALIDATOR_BROADCAST_PREVIOUSLY_SEEN')):
            with patch.object(self.node,'_rpc',side_effect=error),self.assertRaises(ValueError) as failure:
                self.engine.submit_pending(self.key)
            self.assertIs(failure.exception,error)

    def test_cached_broadcast_allows_next_bounded_mining_reconciliation(self):
        self.ready_submission();controller=self.controller;controller.owner=self.profile
        controller._schedule_inbox=lambda:None;controller._fill_drain=lambda key:None
        self.engine.mine=Mock();self.engine.reconcile=Mock(wraps=self.engine.reconcile)
        with patch.object(self.node,'_rpc',side_effect=BroadcastPreviouslySeen()) as broadcast, \
                patch.object(controller._mine_cancel,'wait',side_effect=[False,True]):
            controller._mine(self.key,5)
        self.assertEqual(broadcast.call_count,2);self.assertEqual(self.engine.reconcile.call_count,4)
        self.assertEqual(controller._mine_error,'');self.assertIsNone(controller._mine_until)
        self.assertIsNotNone(self.db.execute('SELECT core FROM protocol_cores').fetchone()[0])
        self.assertEqual(self.db.execute('SELECT count(*) FROM protocol_work').fetchone()[0],1)

    def test_attach_private_job_and_immutable_core_binding_cannot_be_forged(self):
        with self.assertRaisesRegex(ValueError,'CERTIFIED_CONTEXT_REQUIRED'):
            self.engine.attach_work(self.identifier,self.solution,expected_job=self.job.document())
        with self.assertRaisesRegex(ValueError,'^GG_MINING_WORK_INVALID$'):
            self.engine.attach_work('f'*64,self.solution,expected_job=self.job)
        self.change('anchor');bad=deepcopy(self.solution);bad['signature']='0'*128
        with self.assertRaises(ValueError) as failure:self.engine.attach_work(self.identifier,bad,expected_job=self.job)
        self.assertNotEqual(str(failure.exception),'GG_POOL_JOB_STALE')
        self.assertEqual(self.db.execute('SELECT count(*) FROM protocol_work').fetchone()[0],0)

    def test_pool_job_selected_between_reconcile_and_query_returns_stale(self):
        self.controller.owner=SimpleNamespace(_lock=self.profile._lock,_db=self.db,descriptor=lambda:{'public_keys':[public_key(300).pubkey().hex(),self.key]})
        self.controller.pools={'Pool':self.book};self.controller._relay_policy={'pool':'Pool','producer_slot':0,'share_target':'f'*64}
        session=object();self.controller._relay_session=session;self.change('selected-head');before=self.book._head['events']
        with self.assertRaisesRegex(ValueError,'^GG_POOL_JOB_STALE$'):
            self.controller._relay_request(self.node,self.worker.pubkey().hex(),{'method':'pool_job','payout_account':public_key(401).pubkey().hex()},session)
        self.assertEqual(self.book._head['events'],before)

    def test_finite_worker_retries_only_dedicated_stale_and_stops_on_invalid_work(self):
        for code,expected_calls in (('GG_POOL_JOB_STALE',2),('GG_MINING_WORK_INVALID',1),('GG_MINING_WORK_MANIFEST_CONTEXT',1)):
            controller=runtime.ProtocolRuntime();controller.node=SimpleNamespace(profile=SimpleNamespace(native_node_signer=lambda:self.worker))
            calls=[]
            def work(account,worker,attempts):
                calls.append(1)
                if len(calls)==1:raise ValueError(code)
                controller._mine_cancel.set()
            controller._pool_work_once=work
            controller._pool_work(SimpleNamespace(public_address=lambda:public_key(401).pubkey().hex()),1,1)
            with self.subTest(error=code):
                self.assertEqual(len(calls),expected_calls);self.assertEqual(controller._pool_worker['state'],'STOPPED')
                if code=='GG_POOL_JOB_STALE':self.assertEqual(controller._mine_error,'')
                else:self.assertEqual(controller._mine_error,code)


if __name__=='__main__':unittest.main()
