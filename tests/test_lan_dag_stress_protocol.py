"""Finite in-memory control/fault tests, not physical-network benchmarks."""
import json
import time
import unittest
from unittest.mock import patch
from backend import gg_lan_dag as lan
from backend.gg_parallel_dag import ParallelDag,make_public_genesis,pack,_tree


class DagStressProtocolTests(unittest.TestCase):
    def setUp(self):
        self.peers=[lan.LanDagPeer(label,allow_dag_transactions=True) for label in ('Windows','Linux','Termux')]
        coordinator=self.peers[0]
        public=[key.pubkey().hex() for peer in self.peers for key in peer._local_keys]
        bundle=make_public_genesis(public,enable_dag_transactions=True)
        roster={peer.public_key:{'label':peer.label,'allow_dag_transactions':True,'credit_index':index,
            'producer_indices':[2*index,2*index+1]} for index,peer in enumerate(self.peers)}
        for index,peer in enumerate(self.peers):
            peer._trusted=coordinator.public_key;peer._network='f'*64;peer._roster=roster;peer._dag_enabled=True
            peer._engine=ParallelDag.from_public_genesis(bundle);peer._local_indices=[2*index,2*index+1]
            peer._engine.attach_local_producers(dict(zip(peer._local_indices,peer._local_keys)))
        lookup={peer.public_key:peer for peer in self.peers}
        for source in self.peers:
            def rpc(target,kind,payload,*,cancel=None,deadline=None,source=source):
                if deadline is not None and time.monotonic()>=deadline:raise ValueError('GG_LAN_CIRCLE_DEADLINE')
                if cancel is not None and cancel.is_set():raise ValueError('GG_LAN_CIRCLE_CANCELLED')
                return lookup[target]._dag_stress_command(source.public_key,kind,payload)
            source._token_rpc=rpc
            original=source._engine.produce_lan_test_block
            def produce(*args,source=source,original=original,**kwargs):
                result=original(*args,**kwargs)
                for target in self.peers:
                    if target is not source:target._ingest(result['wire'],source.public_key)
                return result
            source._engine.produce_lan_test_block=produce
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for peer in self.peers:peer._dag_cancel.set()
        for peer in self.peers:
            for worker in (peer._dag_worker,peer._dag_controller):
                if worker:worker.join(2)

    def plan(self):
        peer=self.peers[0]
        body={'schema':'gg.lan-dag.stress.v1','network_id':peer._network,'run_id':'a'*64,'duration_ms':1000,
            'transactions_per_block':2,'interval_ms':100,'remote':True,'expires_at_ns':time.time_ns()+10**9,
            'baseline':peer._engine.lan_evidence()}
        return lan._signed(peer._identity,lan._DAG_STRESS,body)

    def finish(self):
        coordinator=self.peers[0];coordinator._dag_controller.join(3)
        self.assertFalse(coordinator._dag_controller.is_alive())
        return coordinator._dag_stress_snapshot()

    def test_signed_three_peer_run_contains_actual_dag_tx_and_ack_proofs(self):
        self.peers[0].start_dag_stress(1000,2,100)
        result=self.finish()
        self.assertEqual(result['state'],'COMPLETE',result)
        self.assertTrue(result['all_peers_synced'],result)
        self.assertEqual(result['acknowledged_transactions'],result['transactions'])
        self.assertGreater(result['transactions'],0)
        self.assertEqual(len({row['blockset_digest'] for row in result['participants']}),1)
        self.assertEqual(len({row['state_root'] for row in result['participants']}),1)
        self.assertTrue(all(not peer._dag_worker.is_alive() for peer in self.peers))

    def test_prepare_begin_idempotence_closed_replay_and_wrong_authority(self):
        coordinator,peer,_=self.peers;plan=self.plan();run_id=plan['body']['run_id']
        with self.assertRaisesRegex(ValueError,'COORDINATOR_REQUIRED'):
            peer._dag_stress_command(peer.public_key,'DAG_STRESS_PREPARE',{'plan':plan})
        for _ in range(2):peer._dag_stress_command(coordinator.public_key,'DAG_STRESS_PREPARE',{'plan':plan})
        peer._dag_stress_command(coordinator.public_key,'DAG_STRESS_BEGIN',{'run_id':run_id});worker=peer._dag_worker
        peer._dag_stress_command(coordinator.public_key,'DAG_STRESS_BEGIN',{'run_id':run_id})
        self.assertIs(peer._dag_worker,worker)
        peer._dag_stress_command(coordinator.public_key,'DAG_STRESS_STOP',{'run_id':run_id})
        with self.assertRaisesRegex(ValueError,'REPLAY'):peer._dag_stress_command(coordinator.public_key,'DAG_STRESS_PREPARE',{'plan':plan})
        with self.assertRaisesRegex(ValueError,'REPLAY'):peer._dag_stress_command(coordinator.public_key,'DAG_STRESS_BEGIN',{'run_id':run_id})

    def test_lost_begin_ack_rolls_back_every_attempted_run(self):
        coordinator=self.peers[0];original=coordinator._token_rpc;failed=[False]
        def lost(target,kind,payload,**kwargs):
            result=original(target,kind,payload,**kwargs)
            if kind=='DAG_STRESS_BEGIN' and not failed[0]:failed[0]=True;raise TimeoutError()
            return result
        coordinator._token_rpc=lost
        coordinator.start_dag_stress(1000,1,100)
        result=self.finish()
        self.assertEqual(result['state'],'ERROR',result)
        self.assertFalse(result['all_peers_synced']);self.assertIsNone(result['acknowledged_tps'])
        for peer in self.peers:
            self.assertTrue(peer._dag_worker is None or not peer._dag_worker.is_alive())
            self.assertIn(coordinator._dag_plan['body']['run_id'],peer._dag_closed)

    def test_fault_on_remote_peer_prevents_ack_even_when_blocks_match(self):
        coordinator=self.peers[0];original=coordinator._token_rpc
        def fault(target,kind,payload,**kwargs):
            result=original(target,kind,payload,**kwargs)
            if kind=='DAG_STRESS_STATUS':result['evidence']['protocol_fault']='GG_DAG_PRODUCER_EQUIVOCATION'
            return result
        coordinator._token_rpc=fault;coordinator.start_dag_stress(1000,1,100)
        result=self.finish()
        self.assertEqual(result['state'],'ERROR',result);self.assertFalse(result['all_peers_synced'])
        self.assertIsNone(result['acknowledged_transactions']);self.assertIn('EQUIVOCATION',result['last_error'])
        self.assertFalse(lan.LanDagPeer._dag_same_evidence({},{}))

    def test_limits_optin_unrelated_production_and_capability_query(self):
        coordinator=self.peers[0]
        with self.assertRaises(ValueError):coordinator.start_dag_stress(999,1,100)
        with self.assertRaises(ValueError):coordinator.start_dag_stress(1000,65,100)
        with self.assertRaises(ValueError):coordinator.start_dag_stress(1000,1,99)
        coordinator._engine._live['enabled']=True
        with self.assertRaisesRegex(ValueError,'UNRELATED'):coordinator.start_dag_stress(1000,1,100)
        self.assertTrue(coordinator._engine._live['enabled'])
        coordinator._engine._live['enabled']=False
        with self.assertRaisesRegex(ValueError,'USE_FINITE_STRESS'):coordinator.start_producing()
        coordinator.stop_producing()
        with patch.object(lan,'Keypair',side_effect=AssertionError('key created')),patch.object(lan.socket,'socket',side_effect=AssertionError('socket created')):
            self.assertEqual(lan.dag_stress_capabilities()['limits']['max_tx_per_block'],64)

    def test_stop_during_run_and_repeated_stop_clear_signers_without_new_proof(self):
        coordinator=self.peers[0];coordinator.start_dag_stress(1000,1,100)
        result=coordinator.stop()
        self.assertEqual(result['lan']['state'],'STOPPED')
        self.assertFalse(result['dag_stress']['enabled'])
        self.assertFalse(result['dag_stress']['worker_active'])
        self.assertFalse(result['dag_stress']['can_start'])
        self.assertIsNone(coordinator._identity);self.assertEqual(coordinator._local_keys,[])
        self.assertEqual(coordinator._engine._producer_keys,[])
        self.assertEqual(coordinator.stop()['lan']['state'],'STOPPED')

    def test_software_credit_failure_is_reported_as_limit(self):
        coordinator=self.peers[0]
        def limit(*args,**kwargs):raise ValueError('GG_DAG_PEER_CREDIT')
        coordinator._engine.produce_lan_test_block=limit
        coordinator.start_dag_stress(1000,1,100)
        result=self.finish()
        self.assertEqual(result['state'],'LIMIT_REACHED',result)
        self.assertEqual(result['stop_reason'],'SOFTWARE_PROFILE_LIMIT')
        self.assertFalse(result['all_peers_synced']);self.assertIsNone(result['acknowledged_tps'])

    def test_malformed_signed_orphan_does_not_poison_valid_parent(self):
        source,receiver,_=self.peers
        first=ParallelDag.produce_lan_test_block(source._engine,0,1)
        child=ParallelDag.produce_lan_test_block(source._engine,0,1)
        value=json.loads(child['wire']);tx=value['body']['transactions'][0]
        tx['body']['to']=[]
        tx['signature']=source._local_keys[0].sign_message(b'GG-DAG-LAN-TEST-TX-SIGN-v2\0'+pack(tx['body'])).hex()
        value['body']['payload_root']=_tree(value['body']['transactions'],b'GG-DAG-PAYLOAD-v1\0')[-1][0]
        value['signature']=source._local_keys[0].sign_message(b'GG-DAG-PROPOSAL-SIGN-v1\0'+pack(value['body'])).hex()
        self.assertEqual(receiver._ingest(pack(value),source.public_key),'PENDING_PARENTS')
        self.assertEqual(receiver._ingest(first['wire'],source.public_key),'ADMITTED_UNFINALIZED')
        evidence=receiver._engine.lan_evidence()
        self.assertEqual(evidence['blocks'],1);self.assertEqual(evidence['transactions'],1)
        self.assertEqual(receiver._engine._lan_counts[0],1);self.assertEqual(evidence['protocol_fault'],'')
        self.assertEqual(len(receiver._orphans),0);self.assertEqual(receiver._last_error,'GG_DAG_TX_ACCOUNT')


if __name__=='__main__':unittest.main()
