"""Real local dashboard metrics and bounded signed-ledger replay invariants.

All state and keys are temporary fixtures. These checks neither connect peers
nor send funds on any blockchain.
"""
import copy
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend import omni_assets as assets, omni_lab as lab


class NetworkLabMetricsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=patch.object(assets,'ROOT',Path(self.tmp.name));self.root.start()
        assets.bootstrap()
        lab._keys.clear();lab._receiver=None;lab._retry=[];lab._participating=False
        lab._measurement_target(None,reset=True)

    def tearDown(self):
        lab._keys.clear();lab._receiver=None;lab._retry=[];lab._participating=False
        lab._measurement_target(None,reset=True)
        self.root.stop();self.tmp.cleanup()

    def test_empty_state_has_no_invented_measurements_or_supply(self):
        state=lab.snapshot();dashboard=state['dashboard']
        self.assertEqual(state['state'],'NOT_CREATED')
        self.assertEqual(dashboard['measurements'],[])
        self.assertIsNone(dashboard['last_measurement'])
        self.assertIsNone(dashboard['conservation']['supply_atomic'])
        self.assertEqual(dashboard['recent_blocks'],[])
        self.assertEqual(dashboard['pending_transactions'],[])
        self.assertEqual(dashboard['limits'],{'pending':64,'blocks':256,'recent_blocks':16,'measurements':32})

    def test_new_session_recovers_record_missing_chain_identity(self):
        lab._load()
        lab._save({'damaged':True})
        state=lab.create()
        self.assertEqual(state['state'],'ACTIVE_SESSION')
        self.assertTrue(state['chain_id'].startswith('gglab:'))
        self.assertEqual(lab.verify()['state'],'VERIFIED')

    def test_queue_block_quorum_and_exact_conservation_summaries(self):
        state=lab.create();self.assertIsNone(state['dashboard']['quorum']['last_signatures'])
        lab.configure({'enabled':[True,True,False,False]})
        envelope=lab.prepare(2,3,'1.234567');lab.submit(envelope)
        dashboard=lab.snapshot()['dashboard'];queued=dashboard['pending_transactions'][0]
        self.assertEqual((queued['sender_index'],queued['recipient_index'],queued['amount'],queued['fee']),(2,3,'1.234567','0.001'))
        self.assertEqual(queued['txid'],lab.digest(envelope))
        self.assertEqual(dashboard['quorum']['missing'],1)
        self.assertEqual(lab.commit()['state'],'WAITING_QUORUM')
        self.assertEqual(lab.snapshot()['height'],0)
        lab.configure({'enabled':[True,True,True,False],
                       'economics':{'burn_bps':1000,'holder_bps':2000,'contributor_bps':7000}})
        self.assertEqual(lab.commit()['state'],'FINALIZED')
        dashboard=lab.snapshot()['dashboard'];block=dashboard['recent_blocks'][0]
        self.assertEqual((block['height'],block['signatures'],block['txid']),(1,3,queued['txid']))
        self.assertEqual(dashboard['pending_transactions'],[])
        self.assertEqual(dashboard['quorum'],{'enabled':3,'total':4,'required':3,'missing':0,'last_signatures':3})
        conservation=dashboard['conservation']
        self.assertEqual(conservation['state'],'BALANCED')
        for key in ('supply_atomic','balances_atomic','burned_atomic','contributor_pool_atomic','accounted_atomic'):
            self.assertIsInstance(conservation[key],str)
        self.assertEqual(int(conservation['supply_atomic']),lab.SUPPLY)
        self.assertEqual(int(conservation['balances_atomic'])+int(conservation['burned_atomic'])+int(conservation['contributor_pool_atomic']),lab.SUPPLY)

    def test_history_and_measurement_series_are_bounded(self):
        lab.create()
        for index in range(20):
            lab.submit(lab.prepare(index%4,(index+1)%4,'0.000001'))
            self.assertEqual(lab.commit()['state'],'FINALIZED')
        dashboard=lab.snapshot()['dashboard']
        self.assertEqual([row['height'] for row in dashboard['recent_blocks']],list(range(20,4,-1)))
        self.assertEqual(len(dashboard['measurements']),32)
        self.assertTrue(all(math.isfinite(row['elapsed_ms']) and row['elapsed_ms']>=0 for row in dashboard['measurements']))
        self.assertTrue(all(row['operation'] in {'verify','commit','transport_test','retry_transport'} for row in dashboard['measurements']))
        self.assertFalse(any('signature' in row or 'body' in row for row in dashboard['measurements']))

    def test_duration_uses_measured_counter_and_observation_clock(self):
        lab.create();value=lab._load()
        with patch.object(lab.time,'perf_counter',side_effect=[10.0,10.125]),patch.object(lab.time,'time',return_value=1234567890.5):
            self.assertEqual(lab.verify(value)['state'],'VERIFIED')
        self.assertEqual(lab._measurements[-1],{'operation':'verify','elapsed_ms':125.0,'observed_at':1234567890.5,'state':'VERIFIED'})

    def test_transport_loss_retry_reports_actual_counters_and_work(self):
        lab.create();lab.configure({'participating':True})
        self.assertEqual(lab.transport_test(loss=True)['state'],'RETRY_REQUIRED')
        before=lab.snapshot()
        self.assertEqual(before['retry_packets'],1)
        self.assertGreater(before['transport']['accepted_bytes'],0)
        self.assertGreater(before['transport']['storage_used'],0)
        self.assertEqual(lab.retry_transport()['state'],'QUEUED')
        state=lab.snapshot()
        self.assertEqual(state['retry_packets'],0)
        self.assertEqual(state['transport']['storage_used'],0)
        self.assertEqual(state['transport']['signature_checks'],1)
        self.assertEqual(state['transport']['delivered'],1)
        operations={row['operation']:row for row in state['dashboard']['measurements']}
        self.assertEqual(operations['transport_test']['state'],'RETRY_REQUIRED')
        self.assertEqual(operations['retry_transport']['state'],'QUEUED')

    def test_session_replacement_and_target_switch_clear_measurements(self):
        first=lab.create()['chain_id'];lab.submit(lab.prepare());lab.commit()
        self.assertIn('commit',[row['operation'] for row in lab.snapshot()['dashboard']['measurements']])
        second=lab.create()
        self.assertNotEqual(second['chain_id'],first)
        self.assertEqual([row['operation'] for row in second['dashboard']['measurements']],['verify'])
        with tempfile.TemporaryDirectory() as other,patch.object(assets,'ROOT',Path(other)):
            assets.bootstrap();lab.create();lab.submit(lab.prepare());lab.commit()
        restored=lab.snapshot()
        self.assertEqual(restored['chain_id'],second['chain_id'])
        self.assertEqual([row['operation'] for row in restored['dashboard']['measurements']],['verify'])

    def test_top_level_chain_identity_cannot_disagree_with_genesis(self):
        lab.create();value=lab._load();value['chain_id']='gglab:'+'1'*24
        self.assertEqual(lab.verify(value)['state'],'INVALID')

    def test_fixed_genesis_parameters_and_types_are_verified(self):
        lab.create();original=lab._load()
        for key,replacement in (('decimals',9),('decimals',6.0),('symbol','GGHB'),('quorum',3.0),
                                ('chain_id','gglab:invalid'),('validators',['bad']*4)):
            with self.subTest(key=key,replacement=replacement):
                value=copy.deepcopy(original);value['genesis'][key]=replacement;value['head']=lab.digest(value['genesis'])
                self.assertEqual(lab.verify(value)['state'],'INVALID')

    def test_corrupt_shapes_are_invalid_without_unbounded_replay(self):
        lab.create();original=lab._load()
        cases=[{'height':True},{'height':257,'blocks':[{}]*257},{'pending':[{}]*65},
               {'enabled':[True,True,True,1]},{'config':{'preset':'desktop','role':'invented'}},
               {'economics':{'burn_bps':False,'holder_bps':0,'contributor_bps':10000}},
               {'balances':[]},{'nonces':None},{'blocks':None},{'genesis':[]},{'pending':[{'body':{}}]}]
        for change in cases:
            with self.subTest(fields=list(change)):
                value=copy.deepcopy(original);value.update(change)
                self.assertEqual(lab.verify(value)['state'],'INVALID')
        self.assertEqual(lab.verify([])['state'],'INVALID')
        self.assertEqual(lab.verify({})['state'],'INVALID')

    def test_invalid_persisted_session_never_exposes_corrupt_balances(self):
        lab.create();value=lab._load();address=value['genesis']['validators'][0];value['balances'][address]+=1;lab._save(value)
        state=lab.snapshot()
        self.assertEqual(state['state'],'INVALID_SESSION')
        self.assertFalse(state['participating'])
        self.assertNotIn('balances',state)
        self.assertNotIn('participants',state)
        self.assertEqual(state['dashboard']['conservation']['state'],'INVALID')
        self.assertIsNone(state['dashboard']['conservation']['balances_atomic'])
        with self.assertRaisesRegex(ValueError,'HISTORY_INVALID'):lab.prepare()

    def test_stale_pending_transaction_can_be_rejected_without_sealing_valid_history(self):
        lab.create();lab.submit(lab.prepare(0,1,'1'));lab.submit(lab.prepare(0,1,'2'))
        self.assertEqual(lab.commit()['state'],'FINALIZED')
        self.assertEqual(lab.verify()['state'],'VERIFIED')
        self.assertEqual(len(lab.snapshot()['dashboard']['pending_transactions']),1)
        with self.assertRaisesRegex(ValueError,'REPLAY_OR_NONCE'):lab.commit()
        self.assertEqual(lab.snapshot()['pending'],0)
        self.assertEqual(lab.verify()['state'],'VERIFIED')

    def test_valid_older_block_without_optional_account_root_still_verifies(self):
        lab.create();lab.submit(lab.prepare());lab.commit();value=lab._load()
        receipt=value['blocks'][0];block=receipt['block'];del block['account_root']
        raw=assets.pack(block).encode()
        receipt['signatures']=[{'validator':str(key.pubkey()),'signature':str(key.sign_message(raw))}
                               for key in lab._keys[value['chain_id']]]
        value['head']=lab.digest(block);lab._save(value)
        self.assertEqual(lab.verify()['state'],'VERIFIED')
        self.assertIsNone(lab.snapshot()['dashboard']['recent_blocks'][0]['account_root'])


if __name__=='__main__':unittest.main()
