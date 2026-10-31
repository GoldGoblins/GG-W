"""Independent owned work and strict replica evidence are separate observations."""
import json
import math
import time
import unittest
from backend import gg_lan_dag as lan
from backend.gg_parallel_dag import ParallelDag
from tests import test_lan_dag_stress_protocol as fixture
from tests.test_lan_dag_stress_process import OwnedProcess


class ProductionMetricsTests(unittest.TestCase):
    setUp=fixture.DagStressProtocolTests.setUp
    cleanup=fixture.DagStressProtocolTests.cleanup
    finish=fixture.DagStressProtocolTests.finish

    def test_actual_owned_work_survives_missing_replica_ack_and_has_own_time_window(self):
        # No cross-peer delivery in this control fixture. Each node still signs
        # and admits its own blocks; strict three-replica proof cannot match.
        for peer in self.peers:
            peer._engine.produce_lan_test_block=ParallelDag.produce_lan_test_block.__get__(peer._engine)
        coordinator=self.peers[0];coordinator.start_dag_stress(1000,2,100)
        result=self.finish();production=result['production']
        self.assertEqual(result['state'],'TIME_BUDGET')
        self.assertFalse(result['all_peers_synced']);self.assertIsNone(result['acknowledged_tps'])
        self.assertIn(production['state'],('COMPLETE','STOPPED'))
        self.assertGreater(production['blocks'],0)
        self.assertEqual(production['transactions'],production['blocks']*2)
        self.assertLess(production['elapsed_ms'],result['elapsed_ms'])
        self.assertAlmostEqual(production['tps'],production['transactions']*1000/production['elapsed_ms'],delta=.01)
        frozen=coordinator._dag_status()['production'];time.sleep(.015)
        self.assertEqual(frozen,coordinator._dag_status()['production'])
        self.assertTrue(all(row['production']['blocks']>0 for row in result['participants']))

    def test_received_blocks_do_not_become_owned_production(self):
        coordinator,remote,_=self.peers;injected=[]
        def produce(*args,**kwargs):
            block=ParallelDag.produce_lan_test_block(coordinator._engine,*args,**kwargs)
            if not injected:
                received=ParallelDag.produce_lan_test_block(remote._engine,2,2)
                coordinator._ingest(received['wire'],remote.public_key);injected.append(True)
            return block
        coordinator._engine.produce_lan_test_block=produce
        coordinator.start_dag_stress(1000,2,100,remote=False)
        result=self.finish();production=result['production']
        evidence=coordinator._engine.lan_evidence()
        self.assertEqual(production['blocks'],sum(evidence['producer_blocks'][:2]))
        self.assertEqual(production['transactions'],sum(evidence['producer_transactions'][:2]))
        self.assertGreater(result['blocks'],production['blocks'])
        self.assertEqual(result['blocks'],production['blocks']+1)
        self.assertFalse(result['all_peers_synced'])

    def test_public_production_recomputes_rates_and_drops_extra_fields(self):
        value={'state':'COMPLETE','blocks':4,'transactions':32,'elapsed_ms':500,
               'tps':999999,'basis':'NETWORK_CAPACITY','private_marker':'MUST_NOT_EXPORT'}
        result=lan.LanDagPeer._dag_public_production(value)
        self.assertEqual(result['tps'],64);self.assertEqual(result['bps'],8)
        self.assertEqual(result['basis'],'LOCAL_OWN_PRODUCTION_NOT_NETWORK_CAPACITY')
        self.assertNotIn('MUST_NOT_EXPORT',json.dumps(result))
        for key,bad in [('blocks',True),('transactions',-1),('elapsed_ms',math.nan),('elapsed_ms',math.inf),('state','ACKNOWLEDGED')]:
            with self.subTest(key=key,bad=bad):
                self.assertIsNone(lan.LanDagPeer._dag_public_production({**value,key:bad}))
        self.assertIsNone(lan.LanDagPeer._dag_public_production(None))


class IndependentProcessModelTest(unittest.TestCase):
    def test_two_fast_processes_keep_producing_while_third_cannot_work_then_catches_up(self):
        peers=[]
        try:
            for label in ('Fast producer A','Fast producer B','Held slow replica'):
                peers.append(OwnedProcess(label))
            coordinator=peers[0]
            for peer in peers[1:]:peer.call('pin',coordinator=coordinator.invite['body']['peer_key'])
            bundle=coordinator.call('create',invites=[peer.invite for peer in peers])
            self.assertTrue(all(row['state']=='READY' for row in coordinator.call('distribute',bundle=bundle)))
            self.assertEqual(peers[2].call('hold_work')['state'],'HELD')
            coordinator.call('start',duration_ms=4000,transactions_per_block=1,interval_ms=100)
            until=time.monotonic()+2
            while True:
                first=[peer.call('status') for peer in peers]
                if all((row['stress'].get('production') or {}).get('blocks',0)>0 for row in first[:2]):break
                self.assertLess(time.monotonic(),until,'Fast producers did not start independently')
                time.sleep(.03)
            time.sleep(.2)
            later=[peer.call('status') for peer in peers]
            for index in (0,1):
                self.assertGreater(later[index]['stress']['production']['blocks'],first[index]['stress']['production']['blocks'])
            self.assertEqual(later[2]['blocks'],0)
            until=time.monotonic()+6
            while True:
                result=coordinator.call('status')
                if result['stress']['state'] not in ('STARTING','RUNNING','STOPPING'):break
                self.assertLess(time.monotonic(),until);time.sleep(.1)
            self.assertFalse(result['stress']['all_peers_synced'])
            self.assertIsNone(result['stress']['acknowledged_tps'])
            self.assertGreater(result['stress']['production']['transactions'],0)
            peers[2].call('release_work')
            until=time.monotonic()+8
            while True:
                states=[peer.call('status') for peer in peers]
                if all(lan.LanDagPeer._dag_same_evidence(states[0]['evidence'],row['evidence']) for row in states):break
                self.assertLess(time.monotonic(),until,'Released slow replica failed to catch up')
                time.sleep(.1)
            self.assertTrue(all(row['canonical_finalized']==0 for row in states))
            self.assertFalse(coordinator.call('status')['stress']['all_peers_synced'],'Late catch-up must not manufacture a timed ACK')
            print(json.dumps({'scope':'THREE_OWNED_LOOPBACK_PROCESSES_NOT_PHYSICAL_HOSTS',
                'fast_producers_progressed_while_slow_held':True,'slow_later_caught_up':True,
                'shared_verified_blocks':states[0]['blocks'],'shared_verified_transactions':states[0]['transactions'],
                'late_ACK_created':False}),flush=True)
        finally:
            for peer in reversed(peers):peer.close()


if __name__=='__main__':unittest.main()
