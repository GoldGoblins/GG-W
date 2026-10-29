"""Explicit finite DAG actions never enter a financial/signing path."""
import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from backend import omni_assets as store,omni_service as service

class DagServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='gg-public-dag-service-');self.addCleanup(self.temp.cleanup)
        change=patch.object(store,'ROOT',Path(self.temp.name));change.start();self.addCleanup(change.stop);store.bootstrap()
    def test_only_fixed_finite_actions_and_public_parameters_are_forwarded(self):
        from backend import gg_parallel_dag as dag
        with patch.object(dag,'start') as start,patch.object(dag,'build_wave') as wave,patch.object(dag,'stop') as stop:
            service.action('dag_start');start.assert_called_once_with()
            service.action('dag_wave');wave.assert_called_once_with(24,8)
            service.action('dag_wave',json.dumps({'blocks':20,'transactions_per_block':16}));self.assertEqual(wave.call_args.args,(20,16))
            service.action('dag_stop');stop.assert_called_once_with()
            prior=(start.call_count,wave.call_count,stop.call_count)
            for name,args in (('dag_start',{'endpoint':'https://example.invalid'}),('dag_wave',{'private_key':'unused-test-value'}),('dag_send',{}),('dag_stop',{'all_processes':True})):
                with self.assertRaisesRegex(ValueError,'GG_DAG_ACTION_ARGUMENTS'):service.action(name,json.dumps(args))
            self.assertEqual((start.call_count,wave.call_count,stop.call_count),prior)
    def test_idle_public_snapshot_does_not_start_producers(self):
        from backend import gg_parallel_dag as dag
        with patch.object(dag,'start') as start,patch.object(dag,'build_wave') as wave,patch.object(dag,'snapshot',return_value={'state':'STOPPED','canonical_finalized':0}) as snapshot:
            first=service.snapshot();second=service.snapshot()
        self.assertEqual(first['parallel_dag'],second['parallel_dag'])
        self.assertEqual(snapshot.call_count,2);start.assert_not_called();wave.assert_not_called()
    def test_live_actions_forward_only_bounded_public_parameters(self):
        from backend import gg_parallel_dag as dag
        with patch.object(dag,'start_live') as start,patch.object(dag,'stop_live') as stop:
            service.action('dag_live_start');start.assert_called_once_with(8,0,125)
            service.action('dag_live_start',json.dumps({'blocks':16,'transactions_per_block':2,'interval_ms':250}))
            self.assertEqual(start.call_args.args,(16,2,250))
            service.action('dag_live_stop');stop.assert_called_once_with()
            prior=(start.call_count,stop.call_count)
            for name,args in (('dag_live_start',{'endpoint':'https://example.invalid'}),('dag_live_stop',{'clear':True})):
                with self.assertRaisesRegex(ValueError,'GG_DAG_ACTION_ARGUMENTS'):service.action(name,json.dumps(args))
            self.assertEqual((start.call_count,stop.call_count),prior)

class TerminalDagTests(unittest.TestCase):
    def setUp(self):
        from backend import gg_parallel_dag as dag
        dag.stop();self.addCleanup(dag.stop)
        self.temp=tempfile.TemporaryDirectory(prefix='gg-headless-dag-');self.addCleanup(self.temp.cleanup)
        change=patch.object(store,'ROOT',Path(self.temp.name));change.start();self.addCleanup(change.stop)
    def test_cli_finite_actual_two_wave_dag_uses_real_parents_and_stops_own_keys(self):
        from backend.terminal_service import TerminalService
        from backend import gg_parallel_dag as dag
        service=TerminalService();self.addCleanup(service.close)
        result=service.dispatch('dag.test')
        report=result['report'];graph=report['block_graph']
        self.assertTrue(result['stopped_after_test']);self.assertEqual(report['wave_count'],2)
        self.assertEqual(report['transactions_validated'],384);self.assertEqual(report['preview']['accepted'],384)
        self.assertEqual(report['canonical_finalized'],0);self.assertEqual(report['finality'],'EXPLICIT_CHECKPOINT_REQUIRED')
        self.assertEqual(report['producer_count'],4);self.assertEqual(graph['topology'],'MULTIPARENT_DAG')
        self.assertTrue(any(len(row['parent_hashes'])==7 for row in graph['blocks']))
        self.assertGreater(len(graph['edges']),len(graph['blocks']))
        self.assertEqual(dag.snapshot()['state'],'STOPPED')
    def test_terminals_own_separate_sessions_and_cannot_stop_each_other(self):
        from backend.terminal_service import TerminalService
        from backend import gg_parallel_dag as dag
        owner=TerminalService();other=TerminalService();self.addCleanup(owner.close);self.addCleanup(other.close)
        first=owner.dispatch('dag.start')
        for command in ('dag.wave','dag.stop'):
            with self.assertRaisesRegex(ValueError,'TERMINAL_OWNED_DAG_REQUIRED'):other.dispatch(command)
        second=other.dispatch('dag.start');self.assertNotEqual(first['chain_id'],second['chain_id'])
        other.close();self.assertEqual(owner.dispatch('dag.status')['state'],'RUNNING')
        self.assertEqual(dag.snapshot()['state'],'STOPPED')
        owner.dispatch('dag.wave',{'blocks':4,'transactions_per_block':2})
        self.assertEqual(owner.dispatch('dag.status')['transactions_validated'],8)
        owner.close();self.assertEqual(owner._dag().snapshot()['state'],'STOPPED')

    def test_concurrent_terminal_start_has_distinct_owners_and_close_is_isolated(self):
        import threading
        from backend.terminal_service import TerminalService
        terminals=[TerminalService(),TerminalService()]
        for service in terminals:self.addCleanup(service.close)
        barrier=threading.Barrier(2);results=[];errors=[]
        def start(service):
            try:barrier.wait(timeout=5);results.append(service.dispatch('dag.start')['chain_id'])
            except BaseException as error:errors.append(type(error).__name__)
        workers=[threading.Thread(target=start,args=(service,)) for service in terminals]
        for worker in workers:worker.start()
        for worker in workers:worker.join(10);self.assertFalse(worker.is_alive())
        self.assertFalse(errors);self.assertEqual(len(set(results)),2)
        terminals[0].close();self.assertEqual(terminals[1].dispatch('dag.status')['state'],'RUNNING')

if __name__=='__main__':unittest.main()
