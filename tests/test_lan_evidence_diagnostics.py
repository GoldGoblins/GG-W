"""Diagnostic observations never substitute for the original signed ACK."""
from copy import deepcopy
import json
import math
import time
import unittest
from unittest.mock import patch
from backend import gg_lan_dag as lan
from backend.gg_parallel_dag import ParallelDag
from tests import test_lan_dag_stress_protocol as fixture


class EvidenceDiagnosticsTests(unittest.TestCase):
    setUp=fixture.DagStressProtocolTests.setUp
    cleanup=fixture.DagStressProtocolTests.cleanup
    plan=fixture.DagStressProtocolTests.plan

    def status(self):
        evidence=self.peers[0]._engine.lan_evidence()
        return {'state':'COMPLETE','worker_active':False,'run_id':'a'*64,'last_error':'','evidence':evidence}

    def test_reports_each_exact_evidence_difference_without_exporting_identifiers(self):
        status=self.status();evidence=status['evidence']
        for field in ('chain_id','blocks','transactions','blockset_digest','state_root','producer_blocks','producer_transactions'):
            changed=deepcopy(status)
            value=changed['evidence'][field]
            changed['evidence'][field]=value+1 if type(value) is int else [x+1 for x in value] if isinstance(value,list) else 'changed'
            result=lan.LanDagPeer._dag_evidence_check(changed,evidence,'a'*64)
            self.assertFalse(result['matched']);self.assertIn(field,result['pending'])
            self.assertNotIn('a'*64,json.dumps(result))
            self.assertNotIn(evidence['state_root'],json.dumps(result))
        result=lan.LanDagPeer._dag_evidence_check(status,evidence,'a'*64)
        self.assertTrue(result['matched']);self.assertEqual(result['pending'],[])

    def test_matching_counts_do_not_hide_wrong_run_running_worker_or_error(self):
        status=self.status()
        for field,value,pending in (('run_id','b'*64,'run'),('worker_active',True,'worker'),
                                    ('state','RUNNING','state'),('last_error','GG_TEST','peer_error')):
            changed=deepcopy(status);changed[field]=value
            result=lan.LanDagPeer._dag_evidence_check(changed,status['evidence'],'a'*64)
            self.assertFalse(result['matched']);self.assertIn(pending,result['pending'])
            self.assertEqual(result['blocks'],0);self.assertEqual(result['transactions'],0)

    def test_late_cleanup_match_is_visible_but_cannot_create_ack(self):
        result,_=fixture.DagStressProtocolTests.coordinate_near_deadline(self,mismatch=True)
        self.assertEqual(result['state'],'TIME_BUDGET');self.assertFalse(result['all_peers_synced'])
        diagnostics=result['convergence'];self.assertGreater(diagnostics['before_deadline']['remaining_ms'],0)
        self.assertTrue(any('blockset_digest' in r['pending'] for r in diagnostics['before_deadline']['peers']))
        self.assertTrue(all(r['matched'] for r in diagnostics['cleanup']['peers']))
        self.assertFalse(diagnostics['cleanup']['within_deadline'])
        self.assertIsNone(result['acknowledged_transactions'])

    def test_relay_measurement_distinguishes_actual_cpu_and_elapsed_admission(self):
        source,receiver,_=self.peers
        self.assertIsNone(receiver._engine.workload_observation()['relay'])
        block=ParallelDag.produce_lan_test_block(source._engine,0,2)
        original=receiver._engine.admit
        # Windows thread CPU accounting can advance in coarse scheduler ticks.
        def delayed(*args,**kwargs):time.sleep(.060);return original(*args,**kwargs)
        with (patch.object(receiver._engine,'admit',side_effect=delayed),
              patch('backend.gg_parallel_dag.time.thread_time_ns',side_effect=[10000000,12000000])):
            receiver._ingest(block['wire'],source.public_key,block['hash'])
        measured=receiver._engine.workload_observation()
        self.assertEqual(measured['relay']['transactions'],2)
        self.assertGreater(measured['relay']['wall_ms']-measured['relay']['cpu_ms'],20)
        self.assertEqual(measured['basis'],'RECENT_JOBS_NOT_CAPACITY')
        before={k:measured['relay'][k] for k in ('transactions','wall_ms','cpu_ms')}
        receiver._ingest(block['wire'],source.public_key,block['hash'])
        after=receiver._engine.workload_observation()['relay']
        self.assertEqual({k:after[k] for k in before},before)
        self.assertTrue(all(math.isfinite(after[k]) and after[k]>=0 for k in ('wall_ms','cpu_ms','age_seconds')))

    def test_unresolved_thread_cpu_clock_does_not_claim_zero_or_more_than_elapsed(self):
        source,receiver,_=self.peers
        block=ParallelDag.produce_lan_test_block(source._engine,0,2)
        with patch('backend.gg_parallel_dag.time.thread_time_ns',side_effect=[0,10**9]):
            receiver._ingest(block['wire'],source.public_key,block['hash'])
        sample=receiver._engine.workload_observation()['relay']
        self.assertFalse(sample['cpu_sample_resolved']);self.assertIsNone(sample['cpu_ms'])
        block=ParallelDag.produce_lan_test_block(source._engine,0,2)
        with patch('backend.gg_parallel_dag.time.thread_time_ns',return_value=0):
            receiver._ingest(block['wire'],source.public_key,block['hash'])
        sample=receiver._engine.workload_observation()['relay']
        self.assertFalse(sample['cpu_sample_resolved']);self.assertIsNone(sample['cpu_ms'])

    def test_untrusted_workload_is_bounded_public_numbers_only(self):
        result=lan.LanDagPeer._dag_public_workload({'seed':'MUST_NOT_EXPORT',
            'local':{'transactions':32,'wall_ms':float('inf'),'sign_ms':True,'verify_ms':-1,'private_key':'MUST_NOT_EXPORT'},
            'relay':{'transactions':50001,'wall_ms':1}})
        self.assertNotIn('MUST_NOT_EXPORT',json.dumps(result));self.assertIsNone(result['relay'])
        self.assertTrue(all(result['local'][k] is None for k in ('wall_ms','sign_ms','verify_ms','age_seconds')))


if __name__=='__main__':unittest.main()
