"""Public profile commands, private unlock context and truthful observations."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

from backend import gg_node_store as store,lan_dag_runtime as runtime,terminal_cli as cli
from backend import terminal_service,portable_wallet_vault as vault


class DurableRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.unlock=vault.session('disposable runtime fixture password');self.unlock.__enter__();self.addCleanup(self.unlock.__exit__,None,None,None)
        self.temp=tempfile.TemporaryDirectory(prefix='gg-profile-runtime-');self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)/'nodes';self.scope=patch.object(store,'ROOT',self.base)
        self.scope.start();self.addCleanup(self.scope.stop)
        self.managers=[];self.addCleanup(self.cleanup)

    def cleanup(self):
        for manager in reversed(self.managers):manager.stop()

    def manager(self):
        manager=runtime.LanDagRuntime();self.managers.append(manager);return manager

    def start(self,manager,name='Fixture',**kwargs):
        return manager.dispatch('lan.start',{'profile':name,'label':name,'bind_host':'127.0.0.1','port':0,
            'allow_dag_transactions':True,**kwargs})

    def test_cold_status_and_invalid_resume_arguments_make_no_profile(self):
        manager=self.manager();manager.snapshot()
        for args in ({},{'profile':'Fixture','bind_host':'127.0.0.1'},{'profile':'Fixture','password':'unused fixture'}):
            with self.assertRaisesRegex(ValueError,'ACTION_ARGUMENTS'):manager.dispatch('lan.resume',args)
        self.assertFalse(self.base.exists())
        with self.assertRaises(ValueError):manager.dispatch('lan.resume',{'profile':'../escape'})
        self.assertFalse(self.base.exists())

    def test_public_start_stop_resume_preserves_invite_and_reports_storage_truth(self):
        manager=self.manager();state=self.start(manager);invite=manager.dispatch('lan.invite')
        self.assertFalse(state['lan_setup']['ephemeral_keys']);self.assertFalse(state['lan_setup']['new_pairing_after_restart'])
        manager.stop();restored=manager.dispatch('lan.resume',{'profile':'Fixture'})
        self.assertEqual(manager.dispatch('lan.invite'),invite)
        summary=cli.foreground_summary('lan.resume',restored)
        self.assertTrue(summary['storage']['restored']);self.assertTrue(summary['storage']['keys_encrypted_at_rest'])
        self.assertEqual(summary['storage']['records'],0);self.assertFalse(summary['ephemeral_keys'])
        self.assertEqual(restored['dag_production']['state'],'IDLE')
        self.assertNotIn('protected_keys',json.dumps(summary))

    def test_second_runtime_cannot_own_same_profile_and_failure_leaves_it_inactive(self):
        self.start(self.manager());other=self.manager()
        with self.assertRaisesRegex(ValueError,'PROFILE_IN_USE'):other.dispatch('lan.resume',{'profile':'Fixture'})
        self.assertFalse(other.active)

    def test_invalid_public_configuration_is_rejected_before_creating_a_profile(self):
        for options in ({'port':True},{'bind_host':'8.8.8.8'},{'auto_produce':'yes'},{'label':''}):
            with self.assertRaises(ValueError):self.start(self.manager(),**options)
            self.assertFalse(self.base.exists())

    def test_unbound_participant_keeps_signed_bootstrap_across_restart(self):
        coordinator=self.manager();self.start(coordinator,'Coordinator')
        bootstrap=coordinator.dispatch('lan.bootstrap');participant=self.manager()
        self.start(participant,'Participant',bootstrap=bootstrap)
        invite=participant.dispatch('lan.invite');participant.stop()
        participant.dispatch('lan.resume',{'profile':'Participant'})
        self.assertEqual(participant.dispatch('lan.bootstrap'),bootstrap)
        self.assertEqual(participant.dispatch('lan.invite'),invite)
        self.assertEqual(participant.snapshot()['lan_setup']['announcement_error'],'')

    def test_portable_unlock_exists_only_during_dispatch_and_never_enters_arguments(self):
        previous=vault._password.get()
        with patch.object(terminal_service.assets,'bootstrap'):
            service=terminal_service.TerminalService(secret=Mock(return_value='public fixture node password'))
        self.addCleanup(service.close);service._portable=True
        fake=Mock()
        def dispatch(command,args):
            self.assertIsNotNone(vault._password.get());self.assertEqual(args,{'profile':'Fixture'})
            return {'state':'PAIRING'}
        fake.dispatch.side_effect=dispatch
        with patch.object(service,'_lan',return_value=fake):
            service.dispatch('lan.start',{'profile':'Fixture'})
            self.assertIs(vault._password.get(),previous);self.assertEqual(service.secret.call_count,2)
            service.dispatch('lan.resume',{'profile':'Fixture'})
            self.assertIs(vault._password.get(),previous);self.assertEqual(service.secret.call_count,3)

    def test_foreground_resume_does_not_inject_new_session_options(self):
        service=Mock();service.dispatch.return_value={'lan':{'state':'READY'}}
        with redirect_stdout(io.StringIO()),patch.object(cli,'foreground_session',side_effect=KeyboardInterrupt) as foreground:
            code=cli.main(['--json','--foreground','--command','lan.resume profile=Fixture','--own-production','{}'],lambda:service)
        self.assertEqual(code,130);self.assertEqual(service.dispatch.call_args.args,('lan.resume',{'profile':'Fixture'}))
        self.assertEqual(foreground.call_args.kwargs['own_production']['duration_ms'],60000)


if __name__=='__main__':unittest.main()
