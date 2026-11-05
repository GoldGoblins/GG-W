"""Local owned production has no peer start/baseline/stop authority dependency."""
import time
import unittest
from unittest.mock import Mock,patch
from backend.gg_parallel_dag import ParallelDag
from backend import lan_dag_runtime as runtime
from backend.terminal_cli import parse_command,foreground_summary
from tests import test_lan_dag_stress_protocol as fixture


class OwnedNodeTests(unittest.TestCase):
    setUp=fixture.DagStressProtocolTests.setUp
    cleanup=fixture.DagStressProtocolTests.cleanup
    plan=fixture.DagStressProtocolTests.plan

    def prepare_nodes(self):
        for peer in self.peers:
            peer._engine.produce_lan_test_block=ParallelDag.produce_lan_test_block.__get__(peer._engine)
            peer._token_rpc=Mock(side_effect=AssertionError('Independent work attempted peer control RPC'))
        self.addCleanup(self.stop_nodes)

    def stop_nodes(self):
        for peer in self.peers:peer.stop_dag_production()
        for peer in self.peers:
            if peer._node_worker:peer._node_worker.join(2)

    def await_blocks(self,peer,minimum=1):
        until=time.monotonic()+2
        while True:
            state=peer._node_snapshot();work=state.get('production') or {}
            if work.get('blocks',0)>=minimum:return state
            self.assertLess(time.monotonic(),until,state);time.sleep(.01)

    def test_participant_starts_with_unequal_history_and_no_peer_rpc(self):
        self.prepare_nodes();coordinator,participant,other=self.peers
        ParallelDag.produce_lan_test_block(coordinator._engine,0,1)
        self.assertNotEqual(coordinator._engine.lan_evidence()['blocks'],participant._engine.lan_evidence()['blocks'])
        participant.start_dag_production(3000,1,50)
        first=self.await_blocks(participant)
        self.assertEqual(other._node_snapshot()['state'],'IDLE')
        # Even its trusted coordinator's old sync STOP cannot stop this worker.
        participant._dag_stress_command(coordinator.public_key,'DAG_STRESS_STOP',{'run_id':'a'*64})
        second=self.await_blocks(participant,first['production']['blocks']+1)
        self.assertTrue(second['worker_active'])
        self.assertFalse(participant._dag_stress_snapshot()['all_peers_synced'])
        participant.stop_dag_production();participant._node_worker.join(1)
        self.assertFalse(participant._node_snapshot()['worker_active'])
        before=participant._engine.lan_evidence()['producer_blocks']
        participant.start_dag_production(1000,1,100);self.await_blocks(participant)
        participant.stop_dag_production();participant._node_worker.join(1)
        after=participant._engine.lan_evidence()['producer_blocks']
        self.assertGreater(sum(after[2:4]),sum(before[2:4]))
        self.assertEqual(sum(after[:2]+after[4:]),0)
        for peer in self.peers:peer._token_rpc.assert_not_called()

    def test_pausing_one_node_leaves_another_producing_and_automatic_end_is_bounded(self):
        self.prepare_nodes();a,b,_=self.peers
        a.start_dag_production(3000,2,100);b.start_dag_production(1000,1,100)
        self.await_blocks(a);first=self.await_blocks(b)
        a.stop_dag_production();a._node_worker.join(1)
        self.assertEqual(a._node_snapshot()['state'],'STOPPED')
        self.await_blocks(b,first['production']['blocks']+1)
        b._node_worker.join(2);last=b._node_snapshot()
        self.assertFalse(last['worker_active']);self.assertEqual(last['state'],'COMPLETE')
        self.assertEqual(last['stop_reason'],'DURATION')
        self.assertEqual(last['production']['transactions'],last['production']['blocks'])
        self.assertEqual(last['production']['basis'],'LOCAL_OWN_PRODUCTION_NOT_NETWORK_CAPACITY')

    def test_sync_prepare_and_local_production_are_mutually_exclusive(self):
        self.prepare_nodes();coordinator,participant,_=self.peers
        signed=self.plan();participant.start_dag_production(3000,1,100)
        with self.assertRaisesRegex(ValueError,'PRODUCTION_BUSY'):
            participant._dag_stress_command(coordinator.public_key,'DAG_STRESS_PREPARE',{'plan':signed})
        participant.stop_dag_production();participant._node_worker.join(1)
        coordinator._dag_stress_command(coordinator.public_key,'DAG_STRESS_PREPARE',{'plan':signed})
        with self.assertRaisesRegex(ValueError,'PRODUCTION_BUSY'):coordinator.start_dag_production(1000,1,100)

    def test_invalid_parameters_and_stopped_or_faulted_session_cannot_start_work(self):
        self.prepare_nodes();peer=self.peers[1]
        for args in [(True,1,100),(999,1,100),(600001,1,100),(1000,0,100),(1000,50001,100),(1000,1,-1)]:
            with self.subTest(args=args),self.assertRaises(ValueError):peer.start_dag_production(*args)
        self.assertIsNone(peer._node_worker)
        peer._engine._lan_fault='GG_DAG_PRODUCER_EQUIVOCATION'
        with self.assertRaisesRegex(ValueError,'EQUIVOCATION'):peer.start_dag_production(1000,1,100)
        peer._engine._lan_fault='';peer._cancel.set()
        with self.assertRaisesRegex(ValueError,'STOPPED'):peer.start_dag_production(1000,1,100)

    def test_lifetime_stop_signals_independent_worker_and_zero_budget_pause_is_cancellable(self):
        self.prepare_nodes();peer=self.peers[1];peer.start_dag_production(3000,1,100)
        self.await_blocks(peer);peer.resources.configure({'cpu':0})
        peer.request_stop();peer._node_worker.join(1)
        self.assertFalse(peer._node_worker.is_alive())
        self.assertFalse(peer._node_snapshot()['can_start'])


class LocalProductionRoutingTests(unittest.TestCase):
    def test_cli_and_desktop_route_only_owned_work_and_reject_peer_target_arguments(self):
        manager=runtime.LanDagRuntime();peer=Mock();manager._peer=peer
        with patch.object(manager,'snapshot',return_value={'public':'fixture'}):
            name,args=parse_command('lan.dag_produce_start duration_ms=3000 transactions_per_block=32 interval_ms=250')
            manager.dispatch(name,args)
            peer.start_dag_production.assert_called_once_with(duration_ms=3000,transactions_per_block=32,interval_ms=250)
            manager.dispatch('lan.dag_produce_stop');peer.stop_dag_production.assert_called_once_with()
            for bad in ({'host':'127.0.0.5'},{'remote':True},{'peer_key':'a'*64}):
                with self.assertRaisesRegex(ValueError,'ACTION_ARGUMENTS'):manager.dispatch(name,bad)
        peer.start_dag_stress.assert_not_called();peer.stop.assert_not_called()

    def test_cli_exposes_owned_production_separately_from_replica_test(self):
        body={'lan':{'state':'READY'},'dag_production':{'scope':'BOUNDED_LOCAL_OWNED_PRODUCTION','state':'RUNNING',
            'worker_active':True,'production':{'basis':'LOCAL_OWN_PRODUCTION_NOT_NETWORK_CAPACITY','state':'RUNNING',
                'blocks':3,'transactions':96,'elapsed_ms':1000,'bps':3,'tps':96}},
            'dag_stress':{'state':'IDLE','all_peers_synced':False}}
        result=foreground_summary('lan.start',body)
        self.assertEqual(result['dag_production']['production']['transactions'],96)
        self.assertFalse(result['dag_stress']['all_peers_synced'])


if __name__=='__main__':unittest.main()
