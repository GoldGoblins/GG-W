"""Owned RAM-only live session: real signatures, no wallet or network access."""
import json
import threading
import time
import unittest
from unittest.mock import patch

from backend import gg_parallel_dag as dag


class LiveDagTests(unittest.TestCase):
    def setUp(self):
        self.node=dag.ParallelDag()
        self.addCleanup(self.node.stop)

    def wait(self,predicate,timeout=5):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            value=self.node.snapshot()
            if predicate(value):return value
            time.sleep(.01)
        self.fail('Owned live fixture did not reach expected state')

    def test_live_automatically_creates_real_signed_empty_siblings_then_pause_retains(self):
        self.node.start_live(4,0,30)
        value=self.wait(lambda sample:sample['wave_count']>=3)
        self.assertEqual(value['transactions_validated'],0)
        self.assertEqual(value['preview']['accepted'],0)
        self.assertEqual(value['canonical_finalized'],0)
        self.assertGreaterEqual(value['admission']['signature_checks'],12)
        self.assertTrue(any(len(row['parent_hashes'])>1 for row in value['block_graph']['blocks']))
        paused=self.node.stop_live()
        self.assertEqual(paused['state'],'RUNNING')
        self.assertEqual(paused['live']['state'],'PAUSED')
        self.assertFalse(paused['live']['enabled']);self.assertFalse(paused['live']['in_flight'])
        count=paused['blocks_admitted'];time.sleep(.08)
        self.assertEqual(self.node.snapshot()['blocks_admitted'],count)
        self.assertEqual(count,paused['admission']['signature_checks'])
        self.assertFalse(any(t.name.startswith(('gg-dag-live','gg-dag-producer')) for t in threading.enumerate()))
        verifier=self.node.fork_verifier();self.addCleanup(verifier.stop)
        self.assertEqual(verifier.reconcile()['state_root'],paused['preview']['state_root'])

    def test_session_cap_stops_visibly_without_discarding_history(self):
        with patch.object(dag,'MAX_RECORDS',13):
            self.node.start_live(4,0,10)
            value=self.wait(lambda sample:sample['live']['state']=='LIMIT_REACHED')
            self.node.stop_live()
            self.assertEqual(value['blocks_admitted'],12)
            self.assertEqual(value['live']['stop_reason'],'GG_DAG_RECORD_LIMIT')
            self.assertEqual(len(value['block_graph']['blocks']),13)
            self.assertEqual(value['state'],'RUNNING')
            self.assertGreater(value['admission']['stored_bytes'],0)
        self.assertEqual(self.node.snapshot()['blocks_admitted'],12)

    def test_wave_byte_budget_stop_keeps_existing_records_and_reports_reason(self):
        self.node.start();self.node.build_wave(4,0)
        before=self.node.snapshot()
        with patch.object(dag,'MAX_SESSION_BYTES',before['admission']['charged_bytes']):
            self.node.start_live(4,0,10)
            value=self.wait(lambda sample:sample['live']['state']=='LIMIT_REACHED')
            self.node.stop_live()
        self.assertEqual(value['blocks_admitted'],before['blocks_admitted'])
        self.assertEqual(value['live']['stop_reason'],'GG_DAG_SESSION_CREDIT')
        self.assertEqual(value['admission']['stored_bytes'],before['admission']['stored_bytes'])

    def test_attempt_budget_preflights_whole_wave_without_partial_admission(self):
        self.node.start()
        with self.assertRaises(ValueError):self.node.admit(b'bad',0)
        with patch.object(dag,'MAX_ATTEMPTS',3):
            self.node.start_live(4,0,10)
            value=self.wait(lambda sample:sample['live']['state']=='LIMIT_REACHED')
            self.node.stop_live()
        self.assertEqual(value['blocks_admitted'],0)
        self.assertEqual(value['admission']['attempts'],1)
        self.assertEqual(value['live']['stop_reason'],'GG_DAG_SESSION_CREDIT')

    def test_live_options_strict_and_start_is_idempotent_no_second_runner(self):
        for args in ((True,0,125),(8,True,125),(8,0,True),(8,0,0),(8,0,60001),(32,17,125)):
            with self.assertRaises(ValueError):self.node.start_live(*args)
        self.assertEqual(self.node.snapshot()['state'],'STOPPED')
        self.node.start_live(4,0,1000)
        chain=self.node.snapshot()['chain_id']
        self.node.start_live(4,0,1000)
        self.assertEqual(self.node.snapshot()['chain_id'],chain)
        self.assertEqual(len([t for t in threading.enumerate() if t.name=='gg-dag-live']),1)
        with self.assertRaisesRegex(ValueError,'LIVE_ALREADY_RUNNING'):self.node.start_live(8,0,125)
        with self.assertRaisesRegex(ValueError,'LIVE_RUNNING'):self.node.build_wave(4,0)

    def test_stop_during_real_producer_work_cancels_admission_and_joins(self):
        entered=threading.Event();release=threading.Event()
        candidate=self.node._candidate
        def held(*args):
            value=candidate(*args);entered.set()
            if not release.wait(3):raise RuntimeError('OWNED_FIXTURE_TIMEOUT')
            return value
        result=[]
        with patch.object(self.node,'_candidate',side_effect=held):
            self.node.start_live(4,0,100)
            self.assertTrue(entered.wait(3))
            stopper=threading.Thread(target=lambda:result.append(self.node.stop()))
            stopper.start();time.sleep(.03)
            self.assertTrue(stopper.is_alive())
            release.set();stopper.join(5)
        self.assertFalse(stopper.is_alive())
        self.assertEqual(result[0]['state'],'STOPPED')
        self.assertEqual(self.node.snapshot()['block_graph']['blocks'],[])
        self.assertFalse(self.node._producer_keys);self.assertFalse(self.node._account_keys)
        self.assertFalse(any(t.name.startswith(('gg-dag-live','gg-dag-producer')) for t in threading.enumerate()))

    def test_empty_reconcile_preserves_mixed_transaction_preview_and_verifier(self):
        self.node.start();verifier=self.node.fork_verifier();self.addCleanup(verifier.stop)
        self.node.build_wave(4,2)
        original=self.node.snapshot()['preview']
        with patch.object(self.node,'_set_root',side_effect=AssertionError('EMPTY_ROOT_REBUILD')):
            self.node.build_wave(8,0)
        self.assertEqual(self.node.snapshot()['preview'],original)
        self.node.build_wave(4,2)
        rank=0
        for row in self.node._records.values():
            if row['rank']:
                if row['rank']!=rank:verifier.reconcile();rank=row['rank']
                verifier.admit(row['wire'],row['producer_index'])
        self.assertEqual(verifier.reconcile()['state_root'],self.node.snapshot()['preview']['state_root'])
        self.assertEqual(self.node.snapshot()['preview']['accepted'],16)

    def test_rolling_actual_rates_decay_to_zero_and_measurements_bounded_detached(self):
        self.node.start()
        for _ in range(35):self.node.build_wave(1,0)
        value=self.node.snapshot()
        self.assertEqual(len(value['measurements']),dag.MEASUREMENT_COUNT)
        self.assertEqual(value['measurements'][-1]['sequence'],35)
        self.assertEqual(value['block_graph']['metrics']['bps'],7)
        self.assertEqual(value['block_graph']['metrics']['tps'],0)
        value['measurements'][-1]['blocks']=999
        self.assertEqual(self.node.snapshot()['measurements'][-1]['blocks'],1)
        with patch.object(dag.time,'monotonic',return_value=time.monotonic()+dag.RATE_WINDOW_SECONDS+1):
            metrics=self.node.snapshot()['block_graph']['metrics']
        self.assertEqual(metrics['bps'],0);self.assertEqual(metrics['tps'],0)
        self.assertTrue(all(sample['producer_ms']>0 and sample['validation_ms']>0 for sample in value['measurements']))

    def test_slow_work_skips_missed_periods_without_backlog(self):
        starts=[];original=self.node.build_wave
        def slow(*args,**kwargs):
            starts.append(time.monotonic());time.sleep(.045)
            return original(*args,**kwargs)
        with patch.object(self.node,'build_wave',side_effect=slow):
            self.node.start_live(1,0,10)
            self.wait(lambda sample:sample['wave_count']>=4)
            self.node.stop_live()
        self.assertTrue(all(b-a>.05 for a,b in zip(starts,starts[1:])),starts)
        self.assertLessEqual(len(starts),5)

    def test_live_failure_sanitizes_message_and_preserves_session(self):
        with patch.object(self.node,'build_wave',side_effect=RuntimeError('DO NOT PUBLISH arbitrary exception detail')):
            self.node.start_live(4,0,100)
            value=self.wait(lambda sample:sample['live']['state']=='ERROR')
            self.node.stop_live()
        self.assertEqual(value['live']['stop_reason'],'GG_DAG_LIVE_FAILED')
        self.assertNotIn('arbitrary',json.dumps(value))
        self.assertEqual(value['state'],'RUNNING')


if __name__=='__main__':unittest.main()
