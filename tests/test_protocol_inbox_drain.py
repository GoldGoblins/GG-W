"""Drain races/recovery with real signed originals and protected inbox files.

The core index/producer callbacks and SDK account/creator/receipt lookups are
explicit lifecycle policy doubles. They are NOT certificates, native execution
or a live network. Payment, producer and inbox-admission signatures are real.
The independent four-SDK runtime test remains the monetary acceptance proof.
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
from unittest.mock import Mock, patch

from backend import gg_protocol_runtime as runtime, gg_protocol_inbox as inbox
from backend import gg_protocol_producer as producer, gg_financial_protocol as protocol
from backend import gg_financial_dag as financial, gg_financial_wire as wire
from backend import gg_node_store as nodes, portable_wallet_vault as vault
from backend.gg_node_store import pack, unpack
from tests.test_durable_node_store import configuration
from tests.test_protocol_integrated_profiles import public_protocol_pin, originals
from tests.test_financial_general_clients import public_key
from tests.test_financial_account import policy_packet, account_policy


class RetiringCoreIndex:
    """Real SQLite rows; callback runs after a selected read, like reconcile."""
    def __init__(self, db): self.db=db;self.after_read=None
    def execute(self, sql, values=()):
        cursor=self.db.execute(sql,values)
        if self.after_read is not None and sql.startswith('SELECT core IS NULL'):
            rows=cursor.fetchall();callback=self.after_read;self.after_read=None;callback()
            return SimpleNamespace(fetchone=lambda:rows[0] if rows else None)
        return cursor


class InboxDrainTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(prefix='gg-inbox-drain-');self.addCleanup(self.temporary.cleanup)
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(nodes,'ROOT',Path(self.temporary.name)/'nodes'))
        self.stack.enter_context(vault.session('PUBLIC disposable queue regression password'))
        self.owner=nodes.NodeProfile.create('DrainOwner',configuration());self.addCleanup(self.owner.close)
        self.identity,self.creators=self.owner.signers();self.creator=self.creators[0];self.key=self.creator.pubkey().hex()
        self.pin=public_protocol_pin();genesis=deepcopy(self.pin['genesis'])
        invite=deepcopy(genesis['protocol']['initial_producers'][0]);body=invite['body']
        body.update(owner_peer_key=self.identity.pubkey().hex(),producer_key=self.key)
        # Exact existing producer-invite domain; validate_pin checks all PoPs.
        message=b'GG-FINANCIAL-PRODUCER-REGISTRATION-v1\0'+pack(body)
        invite.update(owner_signature=self.identity.sign_message(message).hex(),
                      producer_signature=self.creator.sign_message(message).hex(),
                      node_signature=public_key(301).sign_message(message).hex())
        genesis['protocol']['initial_producers']=[invite];genesis['financial_dag']['producers']=[self.key]
        self.pin=protocol.validate_pin({'genesis':genesis,'genesis_hash':hashlib.sha256(pack(genesis)).hexdigest()})
        self.raw=originals(self.pin,count=96);self.payments=unpack(self.raw)['payments']
        self.source=self.pin['genesis']['financial_dag']
        self.db=sqlite3.connect(':memory:');self.addCleanup(self.db.close)
        self.db.execute('CREATE TABLE protocol_cores(identifier TEXT PRIMARY KEY,producer TEXT,sequence INTEGER,core BLOB)')
        self.db.execute('CREATE INDEX protocol_active ON protocol_cores(producer,sequence) WHERE core IS NOT NULL')
        self.index=RetiringCoreIndex(self.db);self.cores={};self.signed=[]
        self.controller=runtime.ProtocolRuntime()
        self.controller.owner=SimpleNamespace(_lock=self.owner._lock,_db=self.index,descriptor=self.owner.descriptor)
        self.packet=policy_packet(self.pin,public_key(0).pubkey().hex(),nonce=0,height=1)
        self.selected_sequence=1;self.outcome='REJECTED_FUNDS';self.lookups=[]
        self.node=SimpleNamespace(anchor=self.pin,binary=Path('PUBLIC-SDK-LOOKUP-POLICY-SEAM'),_stamp=None,
                                  selected_proof=self.selected_proof)
        self.controller.node=self.node;self.controller._check_work=lambda:None
        self.engine=SimpleNamespace(original=self.original,
            produce_batch=Mock(side_effect=self.produce_batch))
        self.controller.producer=self.engine
        self.stack.enter_context(patch.object(financial,'verify_account',side_effect=account_policy))
        self.stack.enter_context(patch.object(protocol,'verify_selected',side_effect=self.registry_policy))
        self.issue([],1,retired=True)
        self.book=inbox.ProtocolInbox(self.owner,self.pin)
        self.entry=self.book.accept(self.raw,self.key);self.controller._inbox=self.book

    def registry_policy(self,packet,trust,**options):
        # Only this explicitly declared SDK lookup seam is replaced. No caller
        # treats these dictionaries as cryptographically verified certificates.
        value=packet['financial_registry']['PUBLIC_policy_record']
        return {'financial_registry_exists':True,'financial_registry_value':base64.b64encode(pack(value)).decode()}

    def selected_proof(self,kind,selector,*,packet=None):
        self.lookups.append((kind,deepcopy(selector),deepcopy(packet)))
        if kind=='account':
            self.assertIsNone(packet);return deepcopy(self.packet)
        self.assertIsNotNone(packet)
        expected={name:self.packet[name] for name in protocol.BASE|({'committee_transitions'} if 'committee_transitions' in self.packet else set())}
        self.assertEqual(packet,expected)
        self.assertEqual(packet['state']['height'],self.packet['state']['height'])
        self.assertEqual(packet['state']['state_root'],self.packet['state']['state_root'])
        self.assertNotIn('financial_account',packet);self.assertNotIn('expected_financial_account',packet)
        if kind=='registry':
            return {**deepcopy(packet),'financial_registry':{'PUBLIC_policy_record':{'sequence':str(self.selected_sequence)}}}
        if kind=='receipt':return {**deepcopy(packet),'financial_receipt':{'receipt':{'leaf':{'outcome':self.outcome}}}}
        raise AssertionError(kind)

    def issue(self,payments,sequence,*,retired=False):
        parent=next((identifier for identifier,raw in self.cores.items() if int(unpack(raw)['body']['sequence'])==sequence-1),
                    hashlib.sha256(b'PUBLIC-unit-origin').hexdigest())
        body={'created_at_ns':self.source['started_at_ns'],'epoch':'1','genesis_hash':self.pin['genesis_hash'],
              'parents':[parent],'payment_root':wire.payment_root(payments),'payments':deepcopy(payments),
              'producer_key':self.key,'rank':str(sequence),'schema':'gg.financial-dag.block.v2','sequence':str(sequence),
              'source_hash':financial.source_hash(self.source)}
        core={'body':body,'signature':self.creator.sign_message(financial.DOMAIN+b'DAG-BLOCK-SIGN-v2\0'+pack(body)).hex()}
        raw=pack(core);producer.decode_core(raw,self.pin,authenticate_accounts=True)
        identifier=producer.core_id(core);self.cores[identifier]=raw;self.signed.append(identifier)
        self.db.execute('INSERT INTO protocol_cores VALUES(?,?,?,?)',(identifier,self.key,sequence,None if retired else raw))
        return identifier

    def original(self,identifier):
        raw=self.cores[identifier];producer.decode_core(raw,self.pin,authenticate_accounts=True);return raw

    def produce_batch(self,key,payments,size,*,check):
        check();self.assertEqual(key,self.key)
        next_sequence=self.db.execute('SELECT COALESCE(max(sequence),0)+1 FROM protocol_cores WHERE producer=?',(key,)).fetchone()[0]
        return [{'block':self.issue(payments[start:start+size],next_sequence+offset)}
                for offset,start in enumerate(range(0,len(payments),size))]

    def schedule(self):
        self.controller._schedule_inbox();return self.controller._drains[self.key]

    def window(self,*,count=1,size=5000):
        self.entry.remember_window({'floor_sequence':'1','first_nonce':'0','count':count,'size':size})

    def local_account(self):
        # Separate local AccountProfile interface seam; exact signed document
        # bytes and all queue logic remain the same, with no InboxEntry branch.
        value=SimpleNamespace(name='PUBLIC-local-account',_lock=threading.RLock(),_account=None,
                              _nonce=inbox.InboxEntry._nonce,public_address=self.entry.public_address)
        def pending(packet):value._account=account_policy(packet,self.pin,value.public_address());return self.raw if int(value._account['financial_account']['nonce'])<96 else None
        value.pending=pending;value.snapshot=lambda:{'next_signing_nonce':'96'}
        self.controller.accounts[value.name]=value
        self.controller._drains[self.key]={'profile':value.name,'size':5000,'state':'DURABLE_ORIGINALS','issued':{},'remaining_originals':None}
        return value

    def test_exact_96_known_core_waits_when_reconcile_retires_between_sql_reads(self):
        identifier=self.issue(self.payments,2);drain=self.schedule();drain['issued'][identifier]={'first':0,'last':95}
        self.index.after_read=lambda:self.db.execute('UPDATE protocol_cores SET core=NULL WHERE identifier=?',(identifier,))
        with patch.object(self.creator,'sign_message',side_effect=AssertionError('duplicate core signature')):
            result=self.controller._fill_drain(self.key)
        self.assertEqual(result['state'],'WAITING_FOR_CREATOR_SELECTION')
        self.engine.produce_batch.assert_not_called();self.assertEqual(len(self.signed),2)
        self.assertIsNone(self.db.execute('SELECT core FROM protocol_cores WHERE identifier=?',(identifier,)).fetchone()[0])
        self.assertEqual(drain['issued'][identifier],{'first':0,'last':95})

    def test_same_retirement_race_is_blocked_for_local_account_drain(self):
        identifier=self.issue(self.payments,2);self.local_account()
        self.controller._drains[self.key]['issued'][identifier]={'first':0,'last':95}
        self.index.after_read=lambda:self.db.execute('UPDATE protocol_cores SET core=NULL WHERE identifier=?',(identifier,))
        result=self.controller._fill_drain(self.key)
        self.assertEqual(result['state'],'WAITING_FOR_CREATOR_SELECTION');self.engine.produce_batch.assert_not_called()

    def test_newer_retirement_does_not_mix_old_account_with_new_receipt(self):
        identifier=self.issue(self.payments,2,retired=True);drain=self.schedule();drain['issued'][identifier]={'first':0,'last':95}
        self.selected_sequence=1
        result=self.controller._fill_drain(self.key)
        self.assertEqual(result['state'],'WAITING_FOR_ACCOUNT_PROOF')
        self.assertEqual([kind for kind,_,_ in self.lookups],['account','registry'])
        self.engine.produce_batch.assert_not_called();self.assertIsNone(self.entry._body['paused_nonce'])

    def test_selected_rejection_uses_same_base_certificate_and_pauses_without_resigning(self):
        identifier=self.issue(self.payments,2,retired=True);drain=self.schedule();drain['issued'][identifier]={'first':0,'last':95}
        self.selected_sequence=2
        result=self.controller._fill_drain(self.key)
        self.assertEqual(result['state'],'PAUSED_SELECTED_REJECTION');self.assertEqual(result['outcome'],'REJECTED_FUNDS')
        self.assertEqual(self.entry._body['paused_nonce'],'0');self.assertNotIn(self.key,self.controller._drains)
        self.assertEqual([kind for kind,_,_ in self.lookups],['account','registry','receipt'])
        self.engine.produce_batch.assert_not_called();self.assertEqual(len(self.signed),2)

    def test_pinned_registry_retains_committee_chain_without_account_payload_extras(self):
        identifier=self.issue(self.payments,2,retired=True);drain=self.schedule();drain['issued'][identifier]={'first':0,'last':95}
        self.packet['committee_transitions']=[]
        self.assertEqual(self.controller._fill_drain(self.key)['state'],'WAITING_FOR_ACCOUNT_PROOF')
        pinned=self.lookups[-1][2]
        self.assertEqual(pinned['committee_transitions'],[])
        self.assertNotIn('financial_account',pinned);self.engine.produce_batch.assert_not_called()

    def test_existing_pending_prefix_is_adopted_even_without_window_or_issued_map(self):
        identifier=self.issue(self.payments,2);drain=self.schedule()
        result=self.controller._fill_drain(self.key)
        self.assertEqual(result['state'],'WAITING_FOR_CREATOR_SELECTION')
        self.assertEqual(drain['issued'],{identifier:{'first':0,'last':95}})
        self.assertEqual(self.entry._body['window']['floor_sequence'],'1')
        self.engine.produce_batch.assert_not_called()

    def test_matching_96_prefix_before_empty_core_stays_issued_after_retirement_and_cold_reload(self):
        prefix=self.issue(self.payments,2);trailing=self.issue([],3);drain=self.schedule()
        with patch.object(self.creator,'sign_message',side_effect=AssertionError('duplicate queue core signature')):
            result=self.controller._fill_drain(self.key)
        self.assertEqual(result['state'],'WAITING_FOR_EXISTING_CREATOR_CORES')
        self.assertEqual(drain['issued'],{prefix:{'first':0,'last':95}})
        self.assertEqual(self.entry._body['window'],{'floor_sequence':'1','first_nonce':'0','count':1,'size':5000})
        self.assertNotIn(trailing,drain['issued'])
        self.db.execute('UPDATE protocol_cores SET core=NULL WHERE sequence>=2')
        self.assertEqual(self.controller._fill_drain(self.key)['state'],'WAITING_FOR_ACCOUNT_PROOF')
        self.engine.produce_batch.assert_not_called();self.assertEqual(len(self.signed),3)
        self.book=inbox.ProtocolInbox(self.owner,self.pin);self.entry=self.book.entries[hashlib.sha256(self.raw).hexdigest()]
        self.controller._inbox=self.book;self.controller._drains.clear();self.controller._relayed_sources.clear()
        recovered=self.schedule()
        self.assertEqual(self.controller._fill_drain(self.key)['state'],'WAITING_FOR_ACCOUNT_PROOF')
        self.assertEqual(recovered['issued'],{prefix:{'first':0,'last':95}})
        self.assertEqual(self.entry._body['window']['count'],1)
        self.engine.produce_batch.assert_not_called();self.assertEqual(len(self.signed),3)

    def test_empty_persisted_window_does_not_cache_missing_core_before_first_issue(self):
        self.window();drain=self.schedule()
        self.controller._recover_inbox_window(self.entry,drain,0)
        self.assertNotIn('window_loaded',drain)
        first=self.controller._fill_drain(self.key)
        self.assertEqual(first['state'],'DURABLE_SIGNED_CORE_WINDOW');self.assertEqual(len(first['cores']),1)
        self.assertEqual(self.engine.produce_batch.call_count,1)
        again=self.controller._fill_drain(self.key)
        self.assertEqual(again['state'],'WAITING_FOR_CREATOR_SELECTION')
        self.assertEqual(self.engine.produce_batch.call_count,1);self.assertEqual(len(self.signed),2)

    def test_cold_partial_window_and_three_nonce_waves_never_reissue_96_originals(self):
        self.window(count=3,size=32);first=self.issue(self.payments[:32],2)
        self.book=inbox.ProtocolInbox(self.owner,self.pin);self.entry=self.book.entries[hashlib.sha256(self.raw).hexdigest()]
        self.controller._inbox=self.book;drain=self.schedule()
        self.assertEqual(self.controller._fill_drain(self.key)['state'],'WAITING_FOR_CREATOR_SELECTION')
        self.assertEqual(drain['issued'][first],{'first':0,'last':31});self.assertNotIn('window_loaded',drain)
        for nonce,sequence in ((32,3),(64,4)):
            self.db.execute('UPDATE protocol_cores SET core=NULL WHERE sequence<?',(sequence,))
            identifier=self.issue(self.payments[nonce:nonce+32],sequence)
            self.packet=policy_packet(self.pin,self.entry.public_address(),nonce=nonce,height=sequence)
            self.assertEqual(self.controller._fill_drain(self.key)['state'],'WAITING_FOR_CREATOR_SELECTION')
            self.assertEqual(drain['issued'][identifier],{'first':nonce,'last':nonce+31})
        self.assertIn('window_loaded',drain)
        self.packet=policy_packet(self.pin,self.entry.public_address(),nonce=96,height=5)
        done=self.controller._fill_drain(self.key)
        self.assertEqual(done['state'],'NONCES_CONSUMED_RECEIPTS_STILL_REQUIRED')
        self.assertNotIn(self.key,self.controller._drains);self.assertEqual(self.book.entries,{})
        self.controller._schedule_inbox();self.assertEqual(self.controller._drains,{})
        self.engine.produce_batch.assert_not_called();self.assertEqual(len(self.signed),4)
        status=self.book.status(hashlib.sha256(self.raw).hexdigest())
        self.assertFalse(status['payments_executed_asserted'])
        self.assertEqual(status['state'],'NONCES_CONSUMED_OUTCOME_UNRESOLVED')

    def test_missing_issued_core_or_changed_original_window_fails_without_new_signature(self):
        identifier=self.issue(self.payments,2);drain=self.schedule();drain['issued'][identifier]={'first':0,'last':95}
        self.db.execute('DELETE FROM protocol_cores WHERE identifier=?',(identifier,))
        with self.assertRaisesRegex(ValueError,'DRAIN_ISSUED_CORE_MISSING'):self.controller._fill_drain(self.key)
        self.window();self.issue(self.payments[1:],2)
        with self.assertRaisesRegex(ValueError,'SIGNING_WINDOW_CONFLICT'):
            self.controller._recover_inbox_window(self.entry,drain,0)
        self.engine.produce_batch.assert_not_called()

    def test_cold_partial_creation_uses_persisted_size_only_for_unissued_suffix(self):
        self.window(count=3,size=32);first=self.issue(self.payments[:32],2,retired=True)
        self.book=inbox.ProtocolInbox(self.owner,self.pin);self.entry=self.book.entries[hashlib.sha256(self.raw).hexdigest()]
        self.controller._inbox=self.book;drain=self.schedule()
        self.assertEqual(drain['size'],32)
        self.packet=policy_packet(self.pin,self.entry.public_address(),nonce=32,height=3)
        result=self.controller._fill_drain(self.key)
        self.assertEqual(result['state'],'DURABLE_SIGNED_CORE_WINDOW');self.assertEqual(len(result['cores']),2)
        self.assertEqual(len(self.signed),4)
        self.assertEqual(unpack(self.cores[first])['body']['payments'],self.payments[:32])
        for offset,row in enumerate(result['cores']):
            core=unpack(self.cores[row['block']])
            self.assertEqual(core['body']['sequence'],str(offset+3))
            self.assertEqual(core['body']['payments'],self.payments[32+offset*32:64+offset*32])
        self.assertEqual(self.entry._body['window']['floor_sequence'],'1')
        self.controller._recover_inbox_window(self.entry,drain,32)
        self.assertIn('window_loaded',drain)
        self.assertEqual(self.controller._fill_drain(self.key)['state'],'WAITING_FOR_CREATOR_SELECTION')
        self.assertEqual(self.engine.produce_batch.call_count,1)

    def test_pool_queue_wait_retries_only_inside_existing_cancelled_bounded_loop(self):
        worker=public_key(400);self.node.profile=SimpleNamespace(native_node_signer=lambda:worker)
        account=SimpleNamespace(public_address=self.entry.public_address);calls=[]
        def wait_for_creator(*arguments):
            calls.append(arguments)
            if len(calls)==3:self.controller._mine_cancel.set()
            raise ValueError('GG_POOL_WAITING_FOR_CREATOR_QUEUE')
        with patch.object(self.controller,'_pool_work_once',side_effect=wait_for_creator), \
             patch.object(self.controller._mine_cancel,'wait',side_effect=lambda seconds:self.controller._mine_cancel.is_set()) as wait:
            self.controller._pool_work(account,1,1)
        self.assertEqual(len(calls),3);self.assertTrue(all(value.args==(.2,) for value in wait.call_args_list))
        self.assertEqual(self.controller._mine_error,'');self.assertEqual(self.controller._operation_cursors,{})
        self.assertEqual(self.controller._pool_worker['shares_found'],0)
        self.assertEqual(self.controller._pool_worker['shares_retained'],0)
        self.assertFalse(self.controller._pool_worker['money_created_asserted'])
        self.engine.produce_batch.assert_not_called();self.assertEqual(len(self.signed),1)

    def test_pool_other_errors_stay_terminal_and_duration_is_not_extended(self):
        self.node.profile=SimpleNamespace(native_node_signer=lambda:public_key(400))
        account=SimpleNamespace(public_address=self.entry.public_address)
        with patch.object(self.controller,'_pool_work_once',side_effect=ValueError('GG_MINING_WORK_INVALID')) as once:
            self.controller._pool_work(account,1,1)
        self.assertEqual(once.call_count,1);self.assertEqual(self.controller._mine_error,'GG_MINING_WORK_INVALID')
        self.controller._mine_error=''
        with patch.object(self.controller,'_pool_work_once',side_effect=ValueError('GG_POOL_WAITING_FOR_CREATOR_QUEUE')) as once, \
             patch.object(runtime.time,'monotonic',side_effect=[100.,100.,101.]), \
             patch.object(self.controller._mine_cancel,'wait',return_value=False) as wait:
            self.controller._pool_work(account,1,1)
        self.assertEqual(once.call_count,1);wait.assert_called_once_with(.2)

    def test_scheduler_does_not_resurrect_completed_or_replaced_book_snapshot(self):
        for action in ('mark_done','replace_book'):
            with self.subTest(action=action):
                if not self.book.entries:self.entry=self.book.accept(self.raw,self.key)
                book=self.book;entry=self.entry;controller=self.controller
                controller._inbox=book;controller._drains.clear();controller._relayed_sources.clear()
                packet=policy_packet(self.pin,entry.public_address(),nonce=96,height=3)
                class CompleteBeforeDrainLock:
                    def __enter__(self):
                        if action=='mark_done':book.mark_done(entry,packet)
                        else:controller._inbox=inbox.ProtocolInbox(self_owner,self_pin)
                    def __exit__(self,*arguments):return False
                self_owner=self.owner;self_pin=self.pin
                previous=controller._drain_lock
                try:
                    controller._drain_lock=CompleteBeforeDrainLock()
                    controller._schedule_inbox()
                finally:controller._drain_lock=previous
                self.assertEqual(controller._drains,{})
                self.assertEqual(controller._relayed_sources,{})
                self.engine.produce_batch.assert_not_called();self.assertEqual(len(self.signed),1)


if __name__=='__main__':unittest.main()
