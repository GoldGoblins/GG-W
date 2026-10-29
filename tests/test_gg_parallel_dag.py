"""Actual signed sibling DAG, independent public verifier and bounded attacks.

All keys are disposable fixtures in RAM. No wallet, user node, public endpoint,
filesystem state or screenshot is used; no test identity secret is printed.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import tracemalloc
import unittest
from unittest.mock import patch

from backend import gg_parallel_dag as dag


class ParallelDagTests(unittest.TestCase):
    def setUp(self):
        self.node=dag.ParallelDag();self.node.start();self.addCleanup(self.node.stop)

    def candidate(self,producer=0,sequence=1,source=0):
        root=self.node._preview_root;parents=list(self.node._frontier)
        return self.node._candidate(producer,sequence,parents,root,[source])

    def signed(self,raw,change=None,tx_change=None):
        value=json.loads(raw);body=value['body']
        if change:change(body)
        if tx_change:
            tx=body['transactions'][0];tx_change(tx)
            source=tx['body']['from']
            tx['signature']=self.node._account_keys[source].sign_message(b'GG-DAG-TX-SIGN-v1\0'+dag.pack(tx['body'])).hex()
        body['payload_root']=dag._tree(body['transactions'],b'GG-DAG-PAYLOAD-v1\0')[-1][0]
        value['signature']=self.node._producer_keys[body['producer_index']].sign_message(b'GG-DAG-PROPOSAL-SIGN-v1\0'+dag.pack(body)).hex()
        return dag.pack(value)

    def test_real_twenty_four_siblings_then_seven_parents_and_independent_verification(self):
        verifier=self.node.fork_verifier();self.addCleanup(verifier.stop)
        first=self.node.build_wave(24,8)
        self.assertEqual(first['blocks_admitted'],24);self.assertEqual(first['transactions_validated'],192)
        self.assertEqual(first['last_wave']['workers_used'],4);self.assertTrue(first['last_wave']['parallel'])
        self.assertGreater(first['last_wave']['worker_overlap_ms'],0)
        self.assertEqual({row['rank'] for row in first['block_graph']['blocks']},{0,1})
        self.assertEqual({len(row['parent_hashes']) for row in first['block_graph']['blocks'] if row['rank']},{1})
        for row in reversed(list(self.node._records.values())):
            if row['rank']:verifier.admit(row['wire'],row['producer_index'])
        self.assertEqual(verifier.reconcile()['state_root'],first['preview']['state_root'])
        second=self.node.build_wave(24,8)
        new=[row for row in self.node._records.values() if row['rank']==2]
        self.assertEqual(len(new),24);self.assertTrue(all(len(row['parents'])==7 for row in new))
        # The larger real tail also retains genesis and all first-wave links.
        self.assertEqual(len(second['block_graph']['blocks']),49);self.assertEqual(len(second['block_graph']['edges']),192)
        for row in reversed(new):verifier.admit(row['wire'],row['producer_index'])
        self.assertEqual(verifier.reconcile()['state_root'],second['preview']['state_root'])
        self.assertEqual(second['preview']['accepted'],384);self.assertEqual(second['preview']['conflicts'],0)
        self.assertEqual(sum(int(v['balance_atomic']) for v in self.node._preview_state.values()),dag.ACCOUNT_COUNT*dag.INITIAL_BALANCE)
        self.assertEqual(sum(v['nonce'] for v in self.node._preview_state.values()),384)
        self.assertEqual(verifier._producer_keys,[]);self.assertEqual(verifier._account_keys,{})
        with self.assertRaisesRegex(ValueError,'VERIFIER_ONLY'):verifier.build_wave()
        graph=second['block_graph'];mapping={row['hash']:row for row in graph['blocks']}
        for edge in graph['edges']:
            self.assertIn(edge['from'],mapping[edge['to']]['parent_hashes'])
            self.assertLess(mapping[edge['from']]['rank'],mapping[edge['to']]['rank'])
        self.assertEqual(second['canonical_finalized'],0);self.assertEqual(second['finality'],dag.FINALITY)
        self.assertFalse(second['preview']['canonical']);self.assertIsNone(graph['metrics']['ttf_p95_ms'])
        self.assertTrue(all(row['signature_verified'] and not row['certificate_verified'] for row in graph['blocks'] if row['rank']))
        self.assertFalse(next(row for row in graph['blocks'] if not row['rank'])['signature_verified'])

    def test_same_nonce_double_spend_reconciles_identically_even_with_incremental_opposite_arrival(self):
        verifier=self.node.fork_verifier();self.addCleanup(verifier.stop)
        first=self.candidate()
        second=self.signed(first,change=lambda body:body.update(producer_index=1),tx_change=lambda tx:tx['body'].update(to=self.node._addresses[2],amount_atomic='2'))
        self.node.admit(first,0);self.node.admit(second,1);expected=self.node.reconcile()
        # A different node previews the other sibling first. Late siblings may
        # revise this nonfinal preview; identical complete DAGs must agree.
        verifier.admit(second,1);verifier.reconcile();verifier.admit(first,0)
        actual=verifier.reconcile()
        self.assertEqual(actual,expected);self.assertEqual(actual['accepted'],1);self.assertEqual(actual['conflicts'],1)
        self.assertEqual(self.node._preview_state[self.node._addresses[0]]['nonce'],1)
        self.assertEqual(self.node.snapshot()['blocks_admitted'],2)
        self.assertEqual(self.node.snapshot()['canonical_finalized'],0)

    def test_identical_transaction_in_sibling_blocks_executes_once_and_duplicate_wire_skips_crypto(self):
        raw=self.candidate();other=self.signed(raw,change=lambda body:body.update(producer_index=1))
        self.node.admit(raw,0);before=self.node.snapshot()['admission']['signature_checks']
        duplicate=self.node.admit(raw,0)
        self.assertEqual(duplicate['state'],'DUPLICATE')
        self.assertEqual(self.node.snapshot()['admission']['signature_checks'],before)
        self.node.admit(other,1);preview=self.node.reconcile()
        self.assertEqual(preview['accepted'],1);self.assertEqual(preview['duplicates'],1);self.assertEqual(preview['conflicts'],0)

    def test_unknown_parents_rank_domain_peer_and_schema_fail_before_signatures(self):
        raw=self.candidate()
        mutations=[('UNKNOWN_PARENT',lambda b:b.update(parents=['f'*64])),
            ('PARENTS',lambda b:b.update(parents=b['parents']*8)),
            ('RANK',lambda b:b.update(rank=2)),
            ('DOMAIN',lambda b:b.update(chain_id='ggdag:'+'0'*24)),
            ('PRODUCER_PEER',lambda b:b.update(producer_index=1))]
        for code,change in mutations:
            with self.subTest(code=code):
                altered=self.signed(raw,change=change)
                with self.assertRaisesRegex(ValueError,code):self.node.admit(altered,0)
                self.assertEqual(self.node.snapshot()['admission']['signature_checks'],0)
                self.assertEqual(self.node.snapshot()['blocks_admitted'],0)
        for bad in (b'{"body":{},"body":{}}',b'{',b'[]',b' '*(dag.MAX_BLOCK_BYTES+1)):
            with self.assertRaises(ValueError):self.node.admit(bad,0)
        with self.assertRaisesRegex(ValueError,'UNKNOWN_PEER'):self.node.admit(raw,4)
        self.assertEqual(self.node.snapshot()['admission']['signature_checks'],0)

    def test_modified_block_or_transaction_signature_and_witness_never_enter_graph(self):
        raw=self.candidate();value=json.loads(raw)
        value['signature']='0'*128
        with self.assertRaisesRegex(ValueError,'SIGNATURE'):self.node.admit(dag.pack(value),0)
        for tx_change in (lambda tx:tx['witness']['leaf'].update(balance_atomic='999999999999'),
                          lambda tx:tx['body'].update(nonce=True),
                          lambda tx:tx['body'].update(amount_atomic='1e6'),
                          lambda tx:tx['body'].update(amount_atomic='1000000001')):
            altered=self.signed(raw,tx_change=tx_change)
            with self.assertRaises(ValueError):self.node.admit(altered,0)
        value=json.loads(raw);value['body']['transactions'][0]['signature']='0'*128
        value['body']['payload_root']=dag._tree(value['body']['transactions'],b'GG-DAG-PAYLOAD-v1\0')[-1][0]
        value['signature']=self.node._producer_keys[0].sign_message(b'GG-DAG-PROPOSAL-SIGN-v1\0'+dag.pack(value['body'])).hex()
        with self.assertRaisesRegex(ValueError,'SIGNATURE'):self.node.admit(dag.pack(value),0)
        self.assertEqual(self.node.snapshot()['blocks_admitted'],0);self.assertEqual(len(self.node.snapshot()['block_graph']['blocks']),1)

    def test_sequence_equivocation_and_cross_session_replay_are_rejected(self):
        raw=self.candidate();self.node.admit(raw,0)
        changed=self.signed(raw,change=lambda body:body.update(created_at_ns=body['created_at_ns']+1))
        with self.assertRaisesRegex(ValueError,'EQUIVOCATION'):self.node.admit(changed,0)
        other=dag.ParallelDag();other.start();self.addCleanup(other.stop)
        with self.assertRaisesRegex(ValueError,'DOMAIN'):other.admit(raw,0)
        self.assertEqual(other.snapshot()['admission']['signature_checks'],0)

    def test_wave_limits_precede_work_and_invalid_traffic_spends_bounded_credit(self):
        for blocks,tx in ((True,1),(33,1),(1,129),(32,17),(-1,2)):
            with self.assertRaises(ValueError):self.node.build_wave(blocks,tx)
        self.assertEqual(self.node.snapshot()['admission']['attempts'],0)
        with patch.object(dag,'MAX_ATTEMPTS',5):
            for _ in range(8):
                with self.assertRaises(ValueError):self.node.admit(b'bad',0)
        sample=self.node.snapshot()
        self.assertEqual(sample['admission']['attempts'],8);self.assertEqual(sample['admission']['rejected'],8)
        self.assertEqual(sample['admission']['charged_bytes'],24);self.assertEqual(sample['admission']['signature_checks'],0)
        self.assertEqual(len(self.node._peer_bytes),4);self.assertEqual(len(self.node._records),1)
        with patch.object(dag,'MAX_SESSION_BYTES',100):
            with self.assertRaisesRegex(ValueError,'SESSION_CREDIT'):self.node.admit(b'x'*101,0)
        self.assertEqual(self.node.snapshot()['blocks_admitted'],0)

    def test_retention_roots_and_storage_stay_bounded_and_snapshot_is_detached(self):
        for _ in range(6):sample=self.node.build_wave(24,1)
        self.assertEqual(sample['blocks_admitted'],144);self.assertEqual(len(sample['block_graph']['blocks']),dag.GRAPH_BLOCKS)
        self.assertEqual(sample['block_graph']['history_limit'],128)
        self.assertLessEqual(len(sample['block_graph']['edges']),dag.GRAPH_BLOCKS*7);self.assertLessEqual(len(self.node._roots),dag.MAX_ROOTS)
        self.assertTrue(sample['block_graph']['partial_history'])
        sample['block_graph']['blocks'][0]['parent_hashes'].clear()
        self.assertTrue(self.node.snapshot()['block_graph']['blocks'][0]['parent_hashes'])
        with patch.object(dag,'MAX_RECORDS',len(self.node._records)):
            with self.assertRaisesRegex(ValueError,'RECORD_LIMIT'):self.node.build_wave(1,0)
        self.assertLessEqual(self.node.snapshot()['admission']['stored_bytes'],dag.MAX_SESSION_BYTES)

    def test_parallel_job_memory_is_bounded_and_worker_pool_leaves_no_thread(self):
        tracemalloc.start()
        try:
            before=tracemalloc.get_traced_memory()[0];sample=self.node.build_wave(32,16)
            peak=tracemalloc.get_traced_memory()[1]-before
        finally:tracemalloc.stop()
        self.assertEqual(sample['transactions_validated'],512);self.assertLess(peak,64*1024*1024)
        self.assertLess(sample['admission']['stored_bytes'],dag.MAX_SESSION_BYTES)
        self.assertFalse(any(thread.name.startswith('gg-dag-producer') for thread in threading.enumerate()))

    def test_busy_and_stop_race_cannot_publish_old_session_or_leave_workers(self):
        gate=threading.Event();all_entered=threading.Event();counter=[0];lock=threading.Lock();errors=[]
        candidate=self.node._candidate
        def held(*args):
            value=candidate(*args)
            with lock:
                counter[0]+=1
                if counter[0]>=4:all_entered.set()
            if not gate.wait(3):raise RuntimeError('PUBLIC_FIXTURE_TIMEOUT')
            return value
        def run():
            try:self.node.build_wave(4,1)
            except Exception as error:errors.append(type(error).__name__)
        with patch.object(self.node,'_candidate',side_effect=held):
            worker=threading.Thread(target=run);worker.start()
            self.assertTrue(all_entered.wait(3))
            with self.assertRaisesRegex(ValueError,'WAVE_BUSY'):self.node.build_wave(4,1)
            stopped=self.node.stop();gate.set();worker.join(5)
        self.assertFalse(worker.is_alive());self.assertTrue(errors)
        self.assertEqual(stopped['state'],'STOPPED');self.assertEqual(self.node.snapshot()['block_graph']['blocks'],[])
        self.assertFalse(self.node._account_keys);self.assertFalse(self.node._producer_keys)
        self.assertFalse(any(thread.name.startswith('gg-dag-producer') for thread in threading.enumerate()))

    def test_headless_default_snapshot_and_public_data_never_include_signing_keys(self):
        sample=self.node.build_wave(4,1);raw=json.dumps(sample)
        self.assertNotIn('signature',raw.replace('signature_verified','').replace('signature_checks',''))
        self.assertNotIn('seed',raw);self.assertNotIn('password',raw);self.assertNotIn('private',raw)
        for block in sample['block_graph']['blocks']:
            self.assertFalse({'body','wire','transactions','signature'} & set(block))
        script="""import builtins,sys
original=builtins.__import__
def guarded(name,*args,**kwargs):
 if name.split('.')[0] in {'PySide6','PyQt5','PyQt6','PIL','solders','prompt_toolkit'}:raise RuntimeError('FORBIDDEN_HEADLESS_IMPORT')
 return original(name,*args,**kwargs)
builtins.__import__=guarded
from backend.gg_parallel_dag import ParallelDag
node=ParallelDag();assert node.snapshot()['state']=='STOPPED'
node.start();value=node.build_wave(4,1);assert value['canonical_finalized']==0
node.stop();assert node.snapshot()['state']=='STOPPED'
print('HEADLESS_DAG=PASS')
"""
        result=subprocess.run([sys.executable,'-X','utf8','-B','-c',script],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr);self.assertIn('HEADLESS_DAG=PASS',result.stdout)


if __name__=='__main__':unittest.main()
