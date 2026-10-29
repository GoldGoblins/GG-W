"""Owned headless LAN sessions and strict public bootstrap CLI files."""
from contextlib import ExitStack,redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock,patch

from backend import lan_dag_runtime,omni_assets
from backend.terminal_cli import main,parse_command
from backend.terminal_service import TerminalService


class LanTerminalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='gg-lan-terminal-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(omni_assets,'ROOT',self.root/'registry'))
        self.service=TerminalService();self.addCleanup(self.service.close)

    def test_separate_terminal_owns_only_its_pairing_peer_and_no_global_node(self):
        other=TerminalService();self.addCleanup(other.close)
        with patch.object(lan_dag_runtime,'auto_bind_host',side_effect=AssertionError('No automatic address during status')):
            self.assertEqual(self.service.dispatch('lan.status')['lan']['state'],'STOPPED')
        started=self.service.dispatch('lan.start',{'label':'Owned terminal','bind_host':'127.0.0.1','port':0})
        self.assertEqual(started['lan']['state'],'PAIRING');self.assertFalse(started['lan_setup']['starting'])
        self.assertTrue(self.service._lan().active);self.assertFalse(other._lan().active)
        self.assertIsNone(self.service._dag_engine);self.assertIsNone(other._dag_engine)
        self.assertIsNone(lan_dag_runtime.active_manager(),'Terminal must not adopt the Desktop peer')
        with self.assertRaisesRegex(ValueError,'STOP_LAN_FIRST'):self.service.dispatch('dag.live_start')
        self.service.close()
        self.assertFalse(self.service._lan().active)
        self.assertFalse(any(thread.name.startswith('gg-lan-') for thread in threading.enumerate()))

    def test_legacy_one_shot_start_cleans_up_without_exporting_or_persisting_keys(self):
        output=io.StringIO()
        with redirect_stdout(output):
            code=main(['--json','--command','lan.start','--args','{"label":"One shot","bind_host":"127.0.0.1","port":0}'],lambda:self.service)
        self.assertEqual(code,0);self.assertTrue(self.service._closed)
        body=json.loads(output.getvalue())
        self.assertEqual(body['lan']['state'],'PAIRING')
        self.assertTrue(body['lan_setup']['ephemeral_keys']);self.assertFalse(self.service._lan().active)
        self.assertNotIn('private_key',json.dumps(body));self.assertNotIn('seed',json.dumps(body))

    def test_interactive_coordinator_exact_parse_dispatch_creates_real_three_peer_session(self):
        remotes=[lan_dag_runtime.LanDagRuntime(),lan_dag_runtime.LanDagRuntime()]
        for peer in remotes:self.addCleanup(peer.stop)
        self.service.dispatch(*parse_command('lan.start label=Windows bind_host=127.0.0.1 port=0'))
        public=self.service.dispatch('lan.bootstrap')
        for label,peer in zip(('Linux','Termux'),remotes):
            peer.start(label=label,bind_host='127.0.0.1',port=0,bootstrap=public,auto_produce=False)
        pending=self.service.dispatch('lan.status')
        self.assertEqual(pending['lan_setup']['invite_count'],3)
        self.assertEqual(pending['lan']['state'],'PAIRING');self.assertEqual(pending['producer_count'],0)
        command,args=parse_command('lan.session_create distribute=true')
        self.assertIs(args['distribute'],True)
        ready=self.service.dispatch(command,args)
        self.assertEqual(ready['lan']['state'],'READY');self.assertEqual(ready['producer_count'],6)
        self.assertEqual(len(ready['lan']['local_producer_indices']),2)
        for peer in remotes:
            remote=peer.snapshot()
            self.assertEqual(remote['lan']['state'],'READY');self.assertEqual(remote['chain_id'],ready['chain_id'])
            self.assertEqual(remote['worker_count'],0);self.assertEqual(remote['canonical_finalized'],0)
            self.assertEqual(remote['blocks_admitted'],0)

    def test_foreground_coordinator_exports_only_explicit_new_public_files_and_joins(self):
        bootstrap=self.root/'gg-lan-bootstrap.json';invite=self.root/'gg-lan-windows.json'
        output=io.StringIO()
        with redirect_stdout(output),patch('backend.terminal_cli.time.sleep',side_effect=KeyboardInterrupt):
            code=main(['--json','--foreground','--command','lan.start label=Windows bind_host=127.0.0.1 port=0',
                       '--bootstrap-out',str(bootstrap),'--invite-out',str(invite)],lambda:self.service)
        self.assertEqual(code,130);self.assertTrue(self.service._closed);self.assertFalse(self.service._lan().active)
        public=lan_dag_runtime.read_public_document(str(bootstrap),'bootstrap')
        signed=lan_dag_runtime.read_public_document(str(invite),'invite')
        self.assertEqual(public['coordinator_invite'],signed)
        self.assertEqual(set(public),{'schema','coordinator_invite','allowed_cidr'})
        self.assertEqual(set(signed),{'body','signature'})
        self.assertEqual(len(signed['body']['producer_keys']),2)
        self.assertIn('PRIVATE_LAN_SESSION_EXPERIMENT',output.getvalue())
        self.assertFalse(any(thread.name.startswith('gg-lan-') for thread in threading.enumerate()))

    def test_join_bootstrap_file_is_injected_before_dispatch_and_foreground_polls_lan(self):
        coordinator=lan_dag_runtime.LanDagRuntime();self.addCleanup(coordinator.stop)
        coordinator.start(label='Coordinator',bind_host='127.0.0.1',port=0)
        path=self.root/'bootstrap.json'
        public=coordinator.dispatch('lan.bootstrap')
        lan_dag_runtime.write_public_document(str(path),public,'bootstrap')
        class Service:
            def __init__(self):self.calls=[];self.closed=0
            def dispatch(self,name,args):
                self.calls.append((name,args))
                return {'lan':{'state':'PAIRING','authenticated_peers':[]},'lan_setup':{'invite_count':1}}
            def close(self):self.closed+=1
        service=Service();output=io.StringIO()
        with redirect_stdout(output),patch('backend.terminal_cli.time.sleep',side_effect=[None,KeyboardInterrupt]):
            code=main(['--json','--foreground','--command','lan.start label=Linux','--bootstrap-file',str(path)],lambda:service)
        self.assertEqual(code,130);self.assertEqual(service.closed,1)
        self.assertEqual([name for name,_ in service.calls],['lan.start','lan.status'])
        self.assertEqual(service.calls[0][1],{'label':'Linux','bootstrap':public})
        self.assertEqual(parse_command('lan.start port=16120 auto_produce=true')[1],{'port':16120,'auto_produce':True})

    def test_invalid_public_file_flags_fail_before_any_service_or_listener(self):
        for options,error in ((['--command','wallet.status','--bootstrap-file','unused.json'],'GG_LAN_BOOTSTRAP_START_REQUIRED'),
                              (['--command','lan.start','--invite-out','unused.json'],'GG_LAN_EXPORT_FOREGROUND_REQUIRED'),
                              (['--foreground','--command','network.start','--bootstrap-out','unused.json'],'GG_LAN_BOOTSTRAP_START_REQUIRED')):
            factory=Mock(side_effect=AssertionError('No service may be made'))
            with self.subTest(options=options),redirect_stdout(io.StringIO()) as output:
                code=main(['--json',*options],factory)
            self.assertEqual(code,1);self.assertEqual(json.loads(output.getvalue())['error'],error);factory.assert_not_called()

    def test_close_signals_owned_peer_without_waiting_for_service_lock(self):
        owned=self.service._lan()
        signal=threading.Event();owned.request_stop=signal.set
        entered=threading.Event();release=threading.Event()
        def hold():
            with self.service._lock:entered.set();release.wait(2)
        holder=threading.Thread(target=hold);holder.start();self.assertTrue(entered.wait(1))
        closer=threading.Thread(target=self.service.close);closer.start()
        try:self.assertTrue(signal.wait(.2),'Cancellation waited on ordinary command lock')
        finally:release.set();holder.join(2);closer.join(2)
        self.assertFalse(holder.is_alive());self.assertFalse(closer.is_alive())


if __name__=='__main__':unittest.main()
