"""Small owned RAM-only independent-producer tests, never a network benchmark.

The configured local clocks vary; no visual jitter, synthetic block or remote
peer is involved. Every accepted proposal has real signed bytes and parents.
"""
import json
import random
import threading
import time
import unittest
from unittest.mock import patch

from backend import gg_parallel_dag as dag


class IndependentProducerTests(unittest.TestCase):
    def setUp(self):
        self.node=dag.ParallelDag(random_source=random.Random(20261029))
        self.addCleanup(self.node.stop)

    def wait(self,predicate,seconds=3):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            value=self.node.snapshot()
            if predicate(value):return value
            time.sleep(.01)
        self.fail('Bounded owned async fixture did not reach its expected state')

    def test_eight_actual_workers_have_uneven_counts_times_and_varied_real_parents(self):
        self.node.start_async_live()
        value=self.wait(lambda body:body['blocks_admitted']>=32 and all(row['proposals'] for row in body['producers']))
        self.assertEqual(value['producer_count'],8)
        self.assertEqual(value['worker_count'],8)
        workers=list(self.node._async_threads)
        self.assertEqual(len(workers),8)
        self.assertTrue(all(worker.is_alive() for worker in workers))
        value=self.node.stop_live()
        self.assertTrue(all(not worker.is_alive() for worker in workers))
        counts=[row['proposals'] for row in value['producers']]
        self.assertGreater(max(counts),min(counts),'Independent configured rates must produce different actual counts')
        self.assertEqual(sum(counts),value['blocks_admitted'])
        self.assertEqual(len({row['configured_interval_ms'] for row in value['producers']}),8)
        records=list(self.node._records.values())
        self.assertEqual([row['admission_index'] for row in records],list(range(len(records))))
        self.assertEqual(len(records[0]['body']['producers']),8)
        proposals=records[1:]
        self.assertEqual({row['producer_index'] for row in proposals},set(range(8)))
        self.assertGreaterEqual(len({len(row['parents']) for row in proposals}),3)
        self.assertIn(1,{len(row['parents']) for row in proposals})
        self.assertTrue(all(1<=len(row['parents'])<=7 for row in proposals))
        by_hash={row['hash']:row for row in records}
        for row in proposals:
            envelope=json.loads(row['wire']);body=envelope['body']
            dag._verify(self.node._producer_public[row['producer_index']],b'GG-DAG-PROPOSAL-SIGN-v1\0'+dag.pack(body),envelope['signature'])
            for parent in row['parents']:
                self.assertIn(parent,by_hash)
                self.assertLess(by_hash[parent]['admission_index'],row['admission_index'])
                self.assertLess(by_hash[parent]['rank'],row['rank'])
        for producer in range(8):
            times=[row['body']['created_at_ns'] for row in proposals if row['producer_index']==producer]
            self.assertTrue(all(first<second for first,second in zip(times,times[1:])))
            self.assertEqual(int(value['producers'][producer]['last_created_at_ns']),times[-1])
        self.assertEqual(value['admission']['signature_checks'],len(proposals))
        self.assertEqual(value['canonical_finalized'],0)
        self.assertEqual(value['live']['mode'],'ASYNC_INDEPENDENT_PRODUCERS')
        self.assertLessEqual(value['live']['max_in_flight_proposals'],8)
        self.assertEqual(self.node._async_reserved,0)
        self.assertTrue(all(row['kind']=='async_proposal' and row['blocks']==1 for row in value['measurements']))
        self.assertEqual(value['block_graph']['producer_count'],8)
        self.assertTrue(all('admission_index' in row for row in value['block_graph']['blocks']))

    def test_pause_resume_is_idempotent_and_manual_default_stays_four(self):
        manual=self.node.start()
        self.assertEqual(manual['producer_count'],4)
        with self.assertRaisesRegex(ValueError,'PRODUCER_COUNT_SESSION'):self.node.start_async_live()
        self.assertEqual(self.node.snapshot()['chain_id'],manual['chain_id'])
        self.node.stop()
        self.node.start_async_live()
        first=self.wait(lambda body:body['blocks_admitted']>=3)
        coordinator=self.node._live_thread
        self.node.start_async_live()
        self.assertIs(self.node._live_thread,coordinator)
        with self.assertRaisesRegex(ValueError,'LIVE_ALREADY_RUNNING'):self.node.start_async_live(producer_count=16)
        with self.assertRaisesRegex(ValueError,'LIVE_RUNNING'):self.node.build_wave(1,0)
        paused=self.node.stop_live();before=paused['blocks_admitted']
        time.sleep(.04)
        self.assertEqual(self.node.snapshot()['blocks_admitted'],before)
        self.node.start_async_live()
        resumed=self.wait(lambda body:body['blocks_admitted']>before)
        self.assertEqual(resumed['chain_id'],first['chain_id'])

    def test_dynamic_membership_bounds_and_independent_verifier(self):
        for count in (True,0,-1,17,'8'):
            with self.assertRaisesRegex(ValueError,'PRODUCER_COUNT'):self.node.start_async_live(producer_count=count)
        with self.assertRaisesRegex(ValueError,'PRODUCER_COUNT'):dag.ParallelDag(False)
        node=dag.ParallelDag(16);self.addCleanup(node.stop)
        self.assertEqual(node.start()['producer_count'],16)
        verifier=node.fork_verifier();self.addCleanup(verifier.stop)
        genesis=next(iter(node._records))
        raw=node._candidate(15,1,[genesis],node._preview_root,[])
        node.admit(raw,15)
        verifier.admit(raw,15)
        self.assertEqual(verifier.snapshot()['producer_count'],16)
        self.assertEqual(verifier.snapshot()['block_graph']['producer_count'],16)
        self.assertEqual(verifier.reconcile()['state_root'],node.reconcile()['state_root'])
        self.assertEqual(verifier._producer_keys,[])
        with self.assertRaisesRegex(ValueError,'UNKNOWN_PEER'):node.admit(raw,16)

    def test_priority_cancel_does_not_wait_for_state_lock_and_cleanup_joins_signers(self):
        entered=threading.Event();release=threading.Event();original=self.node._candidate
        def held(*args,**kwargs):
            result=original(*args,**kwargs)
            if args[0]==0:
                entered.set()
                if not release.wait(3):raise ValueError('GG_DAG_FIXTURE_TIMEOUT')
            return result
        with patch.object(self.node,'_candidate',side_effect=held):
            self.node.start_async_live()
            self.assertTrue(entered.wait(2))
            workers=list(self.node._async_threads)
            lock_held=threading.Event();unlock=threading.Event()
            def hold_lock():
                with self.node._lock:
                    lock_held.set();unlock.wait(2)
            holder=threading.Thread(target=hold_lock);holder.start()
            self.assertTrue(lock_held.wait(1))
            began=time.monotonic();self.node.request_stop()
            self.assertLess(time.monotonic()-began,.05)
            unlock.set();holder.join(2)
            result=[]
            cleaner=threading.Thread(target=lambda:result.append(self.node.stop()))
            cleaner.start();time.sleep(.03)
            self.assertTrue(cleaner.is_alive(),'Key cleanup must wait for its own in-flight signer')
            release.set();cleaner.join(3)
        self.assertFalse(cleaner.is_alive())
        self.assertTrue(all(not worker.is_alive() for worker in workers))
        self.assertEqual(result[0]['state'],'STOPPED')
        self.assertEqual(result[0]['producer_count'],8)
        self.assertEqual(result[0]['worker_count'],0)
        self.assertEqual(self.node._producer_keys,[])
        self.assertEqual(self.node._account_keys,{})

    def test_record_and_attempt_limits_stop_without_erasing_real_history(self):
        with patch.object(dag,'MAX_RECORDS',17):
            self.node.start_async_live()
            self.wait(lambda body:body['live']['state']=='LIMIT_REACHED')
            value=self.node.stop_live()
        self.assertEqual(value['live']['stop_reason'],'GG_DAG_RECORD_LIMIT')
        self.assertEqual(value['blocks_admitted'],16)
        self.assertEqual(len(value['block_graph']['blocks']),17)
        self.assertEqual(self.node._async_reserved,0)
        self.assertLessEqual(value['admission']['charged_bytes'],dag.MAX_SESSION_BYTES)
        self.node.stop()
        with patch.object(dag,'MAX_ATTEMPTS',5):
            self.node.start_async_live()
            self.wait(lambda body:body['live']['state']=='LIMIT_REACHED')
            value=self.node.stop_live()
        self.assertEqual(value['admission']['attempts'],5)
        self.assertEqual(value['blocks_admitted'],5)
        self.assertEqual(value['live']['stop_reason'],'GG_DAG_SESSION_CREDIT')

    def test_async_signed_transactions_keep_preview_noncanonical(self):
        self.node.start_async_live(8,1,250)
        self.wait(lambda body:body['transactions_validated']>=8)
        value=self.node.stop_live()
        self.assertEqual(value['transactions_validated'],value['blocks_admitted'])
        self.assertEqual(value['preview']['accepted'],value['transactions_validated'])
        self.assertEqual(value['admission']['signature_checks'],value['blocks_admitted']*2)
        self.assertEqual(value['canonical_finalized'],0)
        self.assertFalse(value['preview']['canonical'])
        verifier=self.node.fork_verifier();self.addCleanup(verifier.stop)
        self.assertEqual(verifier.start()['producer_count'],8)
        self.assertEqual(verifier.reconcile()['state_root'],value['preview']['state_root'])
        self.assertEqual(sum(int(row['balance_atomic']) for row in self.node._preview_state.values()),dag.ACCOUNT_COUNT*dag.INITIAL_BALANCE)

    def test_failure_and_byte_credit_stop_are_bounded_and_do_not_publish_exception_detail(self):
        with patch.object(self.node,'_candidate',side_effect=RuntimeError('private fixture detail must not escape')):
            self.node.start_async_live()
            self.wait(lambda body:body['live']['state']=='ERROR')
            value=self.node.stop_live()
        self.assertEqual(value['live']['stop_reason'],'GG_DAG_LIVE_FAILED')
        self.assertNotIn('private fixture',json.dumps(value))
        self.assertEqual(value['blocks_admitted'],0)
        self.assertEqual(value['worker_count'],0)
        self.node.stop()
        with patch.object(dag,'MAX_SESSION_BYTES',128):
            self.node.start_async_live()
            self.wait(lambda body:body['live']['state']=='LIMIT_REACHED')
            value=self.node.stop_live()
        self.assertEqual(value['live']['stop_reason'],'GG_DAG_SESSION_CREDIT')
        self.assertEqual(value['blocks_admitted'],0)
        self.assertEqual(len(value['block_graph']['blocks']),1)
        self.assertEqual(self.node._async_reserved,0)


if __name__=='__main__':unittest.main()
