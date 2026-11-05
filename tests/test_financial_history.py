"""Protected-profile and CLI routing policy; the native child is an explicit seam.

No stub below is presented as a valid SDK certificate or replay. Real native
signature/replay and owned SDK process evidence run separately.
"""
from copy import deepcopy
from pathlib import Path
from contextlib import ExitStack
import tempfile
import unittest
import socket
from unittest.mock import patch

from tests import test_financial_producer as fixtures
from backend import gg_financial_archive as history,gg_node_store as nodes,gg_consensus_profile as validators
from backend import gg_observer_profile as observers
from backend import gg_financial_account as accounts
from backend import lan_dag_runtime as runtime,terminal_service


class FinancialHistoryDestinationTests(unittest.TestCase):
    def test_all_owned_key_profile_roots_are_protected_before_any_public_file_is_created(self):
        with tempfile.TemporaryDirectory(prefix='gg-financial-destination-') as directory,ExitStack() as stack:
            base=Path(directory)
            for index,module in enumerate((nodes,validators,observers,accounts)):
                root=base/('keys'+str(index));root.mkdir()
                stack.enter_context(patch.object(module,'ROOT',root))
            for module in (nodes,validators,observers,accounts):
                for target in (module.ROOT/'untrusted.ggfin',module.ROOT/'..'/module.ROOT.name/'untrusted.ggfin'):
                    with self.subTest(root=str(module.ROOT)),self.assertRaisesRegex(ValueError,'PROTECTED_DESTINATION'):
                        history._public_destination(target)
                    self.assertFalse(target.exists())
            destination=base/'public.ggfin'
            self.assertEqual(history._public_destination(destination),destination)
            self.assertFalse(destination.exists())


class FinancialHistoryPolicyTests(unittest.TestCase):
    def setUp(self):
        fixtures.FinancialProducerJournalTests.setUp(self)
        self.stack.enter_context(patch.object(observers,'ROOT',Path(self.temp.name)/'observers'))
    cleanup=fixtures.FinancialProducerJournalTests.cleanup

    def idle_owner(self,index=0):
        owner=self.owners[index];name=owner.name;metadata=deepcopy(owner._meta);owner.close()
        return name,metadata

    def core(self):return {key:deepcopy(self.packet[key]) for key in history.BASE}

    def test_export_uses_owned_validator_anchor_and_never_sends_keys_or_changes_owner_floor(self):
        source=self.validators[0];source_name=source.name;source_root=source.root/'native';source.close()
        anchor=self.context.anchor();owner,metadata=self.idle_owner();path=Path(self.temp.name)/'history.ggfin';captured=[]
        def child(mode,request,profile,**options):
            captured.append((mode,request));self.assertEqual(profile.name,owner)
            self.assertEqual(request['root'],str(source_root));self.assertEqual(request['genesis_hash'],anchor['genesis_hash'])
            self.assertEqual(request['minimum_certificate_height'],1)
            return {'policy_seam':True,'network_contact_asserted':False,'certificate':self.core()}
        with patch.object(validators.ValidatorProfile,'public_certificate',return_value=self.core()),patch.object(history,'_run',side_effect=child):
            result=history.history('export',owner,path,validator=source_name)
        self.assertTrue(result['policy_seam']);self.assertNotIn('certificate',result)
        self.assertEqual(len(captured),1)
        self.assertEqual(set(captured[0][1]),{'genesis','genesis_hash','archive_path','root','certificate','minimum_certificate_height','minimum_certificate_block'})
        reopened=nodes.NodeProfile.open(owner);self.owners.append(reopened)
        self.assertEqual(reopened._meta,metadata)

    def test_another_owner_cannot_export_a_validator_profile(self):
        source=self.validators[1];source_name=source.name;source.close();owner,_=self.idle_owner()
        with patch.object(history,'_run') as child:
            with self.assertRaisesRegex(ValueError,'GG_SDK_VALIDATOR_OWNER'):
                history.history('export',owner,Path(self.temp.name)/'foreign.ggfin',validator=source_name)
            child.assert_not_called()

    def test_nonvoting_observer_is_an_owned_offline_source_without_validator_key_access(self):
        with socket.socket() as reserve:
            reserve.bind(('127.0.0.1',0));port=reserve.getsockname()[1]
        observer=observers.ObserverProfile.create_for_owned_profile('HistoryObserver',self.profile,label='History observer',p2p_port=port)
        source_root=observer.root/'native';observer.close();owner,_=self.idle_owner()
        def child(mode,request,profile,**options):
            self.assertEqual(request['root'],str(source_root));self.assertEqual(mode,'export')
            return {'policy_seam':True,'certificate':self.core(),'validator_signing_state_restored':False}
        with patch.object(observers.ObserverProfile,'public_certificate',return_value=self.core()),patch.object(history,'_run',side_effect=child):
            result=history.history('export',owner,Path(self.temp.name)/'observer.ggfin',observer='HistoryObserver')
        self.assertFalse(result['validator_signing_state_restored'])

    def test_live_profile_lease_prevents_offline_archive_work(self):
        with patch.object(history,'_run') as child:
            with self.assertRaises(ValueError):history.history('verify',self.profile.name,Path(self.temp.name)/'absent.ggfin')
            child.assert_not_called()

    def test_restore_advances_floor_only_after_native_success_and_keeps_signing_separate(self):
        owner,_=self.idle_owner();path=Path(self.temp.name)/'archive.ggfin';path.write_bytes(b'public policy seam')
        target=Path(self.temp.name)/'recovered';certificate=self.core()
        def child(mode,request,profile,**options):
            self.assertEqual(mode,'restore');self.assertEqual(request['restore_root'],str(target))
            options['check']();return {'policy_seam':True,'certificate':certificate,'native_node_ready':False}
        with patch.object(history,'_run',side_effect=child),patch.object(nodes.NodeProfile,'save_consensus_certificate') as save:
            result=history.history('restore',owner,path,destination=target)
            save.assert_called_once_with(certificate)
        self.assertFalse(result['native_node_ready'])
        with patch.object(history,'_run',side_effect=ValueError('GG_FINANCIAL_ARCHIVE_INVALID')),patch.object(nodes.NodeProfile,'save_consensus_certificate') as save:
            with self.assertRaisesRegex(ValueError,'GG_FINANCIAL_ARCHIVE_INVALID'):history.history('restore',owner,path,destination=target)
            save.assert_not_called()

    def test_ambiguous_sources_unknown_modes_and_protected_destinations_fail_before_child(self):
        public=Path(self.temp.name)/'public.ggfin'
        with patch.object(history,'_run') as child:
            for mode,options in [('export',{}),('export',{'validator':'A','observer':'B'}),('verify',{'validator':'A'}),('restore',{}),('signing-restore',{})]:
                with self.subTest(mode=mode,options=options),self.assertRaisesRegex(ValueError,'GG_FINANCIAL_HISTORY_ARGUMENTS'):
                    history.history(mode,self.profile.name,public,**options)
            for root in (nodes.ROOT,validators.ROOT):
                with self.assertRaisesRegex(ValueError,'GG_FINANCIAL_HISTORY_PROTECTED_DESTINATION'):
                    history._public_destination(root/'forbidden.ggfin')
            child.assert_not_called()


class FinancialHistoryRuntimeTests(unittest.TestCase):
    def test_runtime_routes_the_owned_operation_and_keeps_stop_and_unknown_argument_fences(self):
        manager=runtime.LanDagRuntime();self.addCleanup(manager.stop)
        with patch.object(history,'history',return_value={'policy_seam':True}) as work:
            result=manager.dispatch('lan.financial_history_export',{'profile':'OwnNode','validator':'OwnValidator','path':'/public/archive.ggfin'})
            self.assertTrue(result['policy_seam']);self.assertEqual(work.call_args.args,('export',))
            self.assertEqual(work.call_args.kwargs['profile'],'OwnNode');self.assertFalse(manager._archive_importing)
            with self.assertRaises(ValueError):manager.dispatch('lan.financial_history_restore',{'profile':'OwnNode','path':'/public/archive.ggfin','destination':'/public/restore','force':True})
            manager._peer=object()
            try:
                with self.assertRaisesRegex(ValueError,'GG_LAN_STOP_BEFORE_FINANCIAL_HISTORY'):
                    manager.financial_history('verify',profile='OwnNode',path='/public/archive.ggfin')
            finally:manager._peer=None
        def cancel(mode,**options):manager._stop_requested.set();options['check']()
        with patch.object(history,'history',side_effect=cancel):
            with self.assertRaisesRegex(ValueError,'GG_FINANCIAL_HISTORY_CANCELLED'):
                manager.financial_history('verify',profile='OwnNode',path='/public/archive.ggfin')
        self.assertFalse(manager._archive_importing)

    def test_portable_history_commands_require_the_existing_visible_password_step(self):
        service=terminal_service.TerminalService();self.addCleanup(service.close);service._portable=True
        for command in ('lan.financial_history_export','lan.financial_history_verify','lan.financial_history_restore'):
            with self.subTest(command=command),patch.object(service,'_password',side_effect=ValueError('UNIT_VISIBLE_UNLOCK_REQUIRED')) as secret:
                with self.assertRaisesRegex(ValueError,'UNIT_VISIBLE_UNLOCK_REQUIRED'):
                    service.dispatch(command,{'profile':'OwnNode','path':'/public/archive.ggfin'})
                secret.assert_called_once()


if __name__=='__main__':unittest.main()
