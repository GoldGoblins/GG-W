"""Real protected profile/intent persistence; native crypto is an explicit seam.

The structural certificates below do not claim SDK finality. Genuine archive,
SDK bootstrap and live rejoin evidence is separate from these policy cases.
"""
from copy import deepcopy
from pathlib import Path
import socket
import unittest
from unittest.mock import patch

from tests import test_financial_producer as fixtures
from backend import gg_node_store as nodes,gg_observer_profile as profiles,gg_observer_recovery as recovery
from backend import gg_financial_archive as archive,lan_dag_runtime as runtime,terminal_service


class ObserverRecoveryPolicyTests(unittest.TestCase):
    def setUp(self):
        fixtures.FinancialProducerJournalTests.setUp(self)
        self.stack.enter_context(patch.object(profiles,'ROOT',Path(self.temp.name)/'observers'))
        self.observers=[];self.addCleanup(lambda:[profile.close() for profile in self.observers])
    cleanup=fixtures.FinancialProducerJournalTests.cleanup

    def observer(self,name='RecoverObserver',index=0):
        with socket.socket() as reserve:reserve.bind(('127.0.0.1',0));port=reserve.getsockname()[1]
        member=profiles.ObserverProfile.create_for_owned_profile(name,self.owners[index],label='Recovery observer',p2p_port=port)
        self.observers.append(member);return member

    def core(self):return {key:deepcopy(self.packet[key]) for key in archive.BASE}
    def idle(self,index=0):owner=self.owners[index];name=owner.name;owner.close();return name
    def public_file(self):path=Path(self.temp.name)/'history.ggfin';path.write_bytes(b'public native policy seam');return path
    def child_result(self):return {'certificate':self.core(),'archive_sha256':'a'*64,'sdk_recovery_available':True,'archive_version':2,'native_node_ready':False}

    def test_owned_restore_verifies_before_intent_never_passes_signers_and_commits_completion_before_owner_floor(self):
        member=self.observer();grant=member.public_grant();name=member.name;root=member.root/'native';member.close()
        owner=self.idle();path=self.public_file();events=[];opened=[];prepare_original=profiles.ObserverProfile.prepare_recovery
        def prepare(profile,*args):
            value=prepare_original(profile,*args);opened.append(profile);return value
        def child(mode,request,profile,**options):
            options['check']();events.append(mode)
            if mode=='verify':
                self.assertNotIn('restore_root',request);self.assertNotIn('observer_grant',request)
            else:
                self.assertEqual(mode,'observer-restore');self.assertEqual(request['restore_root'],str(root))
                self.assertEqual(request['observer_grant'],grant);self.assertEqual(request['expected_archive_sha256'],'a'*64)
                self.assertFalse(any('seed' in key or 'private' in key or key=='validator_index' for key in request))
            return self.child_result()
        def save(profile,certificate):
            self.assertEqual(opened[0].public_certificate(),certificate)
            self.assertFalse(opened[0].snapshot()['recovery_pending'])
            events.append('owner_floor')
        with patch.object(archive,'_run',side_effect=child),patch.object(nodes.NodeProfile,'save_consensus_certificate',autospec=True,side_effect=save),patch.object(profiles.ObserverProfile,'prepare_recovery',autospec=True,side_effect=prepare):
            result=recovery.restore_observer(owner,path,name)
        self.assertEqual(events,['verify','observer-restore','owner_floor']);self.assertFalse(result['observer']['recovery_pending'])
        self.assertNotIn('certificate',result);self.assertFalse(result['native_node_ready'])
        reopened=profiles.ObserverProfile.open(name);self.observers.append(reopened)
        self.assertEqual(reopened.public_grant(),grant);self.assertEqual(reopened.public_certificate(),self.core())

    def test_foreign_owner_live_lease_and_legacy_context_cannot_prepare_recovery(self):
        member=self.observer();name=member.name;member.close();owner=self.idle(1);path=self.public_file()
        with patch.object(archive,'_run') as child:
            with self.assertRaisesRegex(ValueError,'GG_SDK_VALIDATOR_OWNER'):recovery.restore_observer(owner,path,name)
            child.assert_not_called()
        owner=self.idle();member=profiles.ObserverProfile.open(name);self.observers.append(member)
        with patch.object(archive,'_run') as child:
            with self.assertRaises(ValueError):recovery.restore_observer(owner,path,name)
            child.assert_not_called()
        member.close();legacy=self.child_result();legacy.update(sdk_recovery_available=False,archive_version=1)
        with patch.object(archive,'_run',return_value=legacy),patch.object(profiles.ObserverProfile,'prepare_recovery') as prepare:
            with self.assertRaisesRegex(ValueError,'GG_OBSERVER_RECOVERY_PUBLIC_SDK_CONTEXT_REQUIRED'):recovery.restore_observer(owner,path,name)
            prepare.assert_not_called()

    def test_native_failure_keeps_same_pending_identity_and_explicit_retry_completes(self):
        member=self.observer();name=member.name;grant=member.public_grant();member.close();owner=self.idle();path=self.public_file()
        def fail(mode,*args,**options):
            if mode=='observer-restore':raise ValueError('GG_OWNED_NATIVE_FAILURE')
            return self.child_result()
        with patch.object(archive,'_run',side_effect=fail),patch.object(nodes.NodeProfile,'save_consensus_certificate') as floor:
            with self.assertRaisesRegex(ValueError,'GG_OWNED_NATIVE_FAILURE'):recovery.restore_observer(owner,path,name)
            floor.assert_not_called()
        reopened=profiles.ObserverProfile.open(name);self.observers.append(reopened)
        self.assertEqual(reopened.public_grant(),grant);self.assertTrue(reopened.snapshot()['recovery_pending'])
        with self.assertRaisesRegex(ValueError,'GG_OBSERVER_RECOVERY_INCOMPLETE'):reopened.claim_native_start()
        with self.assertRaisesRegex(ValueError,'GG_OBSERVER_RECOVERY_INTENT_CHANGED'):reopened.prepare_recovery('b'*64,self.core())
        reopened.close()
        with patch.object(archive,'_run',side_effect=lambda *args,**kwargs:self.child_result()),patch.object(nodes.NodeProfile,'save_consensus_certificate'):
            result=recovery.restore_observer(owner,path,name)
        self.assertFalse(result['observer']['recovery_pending'])

    def test_profile_unknown_prepare_commit_reopens_actual_state_without_new_keys(self):
        for after in (False,True):
            with self.subTest(after=after):
                member=self.observer('Prepare'+str(after));grant=member.public_grant();original=member._commit
                def uncertain():
                    if after:original()
                    raise OSError('owned commit uncertainty')
                with patch.object(member,'_commit',side_effect=uncertain):
                    with self.assertRaisesRegex(ValueError,'GG_OBSERVER_STORE_WRITE_FAILED'):member.prepare_recovery('a'*64,self.core())
                member.close();reopened=profiles.ObserverProfile.open(member.name);self.observers.append(reopened)
                self.assertEqual(reopened.public_grant(),grant)
                self.assertEqual(reopened._body['schema'],profiles.RECOVERY_SCHEMA if after else profiles.SCHEMA)
                reopened.prepare_recovery('a'*64,self.core())
                self.assertTrue(reopened.snapshot()['recovery_pending'])

    def test_unknown_completion_commit_reopens_pending_or_complete_and_retry_is_idempotent(self):
        for after in (False,True):
            with self.subTest(after=after):
                member=self.observer('Finish'+str(after));grant=member.public_grant();member.prepare_recovery('a'*64,self.core());original=member._commit
                def uncertain():
                    if after:original()
                    raise OSError('owned completion uncertainty')
                with patch.object(member,'_commit',side_effect=uncertain):
                    with self.assertRaisesRegex(ValueError,'GG_OBSERVER_STORE_WRITE_FAILED'):member.finish_recovery('a'*64,self.core())
                member.close();reopened=profiles.ObserverProfile.open(member.name);self.observers.append(reopened)
                self.assertEqual(reopened.public_grant(),grant);self.assertEqual(reopened.snapshot()['recovery_pending'],not after)
                reopened.finish_recovery('a'*64,self.core());reopened.finish_recovery('a'*64,self.core())
                self.assertFalse(reopened.snapshot()['recovery_pending'])

    def test_existing_started_observer_cannot_be_reset_and_pending_certificate_cannot_be_advanced(self):
        member=self.observer();self.assertTrue(member.claim_native_start())
        (member.root/'native').mkdir()
        with self.assertRaisesRegex(ValueError,'GG_OBSERVER_RECOVERY_FRESH_PROFILE_REQUIRED'):member.prepare_recovery('a'*64,self.core())
        pending=self.observer('Pending');pending.prepare_recovery('a'*64,self.core())
        with self.assertRaisesRegex(ValueError,'GG_OBSERVER_RECOVERY_INCOMPLETE'):pending.remember_certificate(self.core())
        with self.assertRaisesRegex(ValueError,'GG_OBSERVER_RECOVERY_INTENT_CHANGED'):pending.finish_recovery('b'*64,self.core())

    def test_missing_public_store_recovers_same_started_identity_without_lowering_saved_certificate(self):
        member=self.observer();grant=member.public_grant();member.claim_native_start();member.remember_certificate(self.core())
        later=self.core();later['state']['height']=1;later['signed_header']['header']['height']='2';later['signed_header']['commit']['block_id']['hash']='3'*64
        member.prepare_recovery('a'*64,later)
        self.assertEqual(member.public_certificate(),self.core());member.close()
        reopened=profiles.ObserverProfile.open(member.name);self.observers.append(reopened)
        self.assertEqual(reopened.public_grant(),grant);self.assertTrue(reopened.snapshot()['recovery_pending'])
        reopened.finish_recovery('a'*64,later)
        with self.assertRaisesRegex(ValueError,'GG_OBSERVER_RECOVERY_CERTIFICATE_REWIND'):reopened.prepare_recovery('b'*64,self.core())
        newer=deepcopy(later);newer['state']['height']=2;newer['signed_header']['header']['height']='3';newer['signed_header']['commit']['block_id']['hash']='4'*64
        reopened.prepare_recovery('b'*64,newer)
        self.assertEqual(reopened.public_grant(),grant);self.assertTrue(reopened.snapshot()['recovery_pending'])

    def test_native_verification_receives_observer_floor_even_when_owner_has_no_observation(self):
        member=self.observer();name=member.name;member.claim_native_start()
        certificate=self.core();certificate['state']['height']=1;certificate['signed_header']['header']['height']='2';certificate['signed_header']['commit']['block_id']['hash']='3'*64
        member.remember_certificate(certificate);member.close();owner=self.idle();path=self.public_file()
        def child(mode,request,profile,**options):
            self.assertEqual(request['minimum_certificate_height'],2);self.assertEqual(request['minimum_certificate_block'],'3'*64)
            return {**self.child_result(),'certificate':certificate}
        with patch.object(archive,'_run',side_effect=child),patch.object(nodes.NodeProfile,'save_consensus_certificate'):
            result=recovery.restore_observer(owner,path,name)
        self.assertFalse(result['observer']['recovery_pending'])

    def test_malformed_timeout_and_relative_path_fail_without_native_handoff(self):
        with patch.object(archive,'_run') as child:
            for value in (True,float('nan'),0,14401):
                with self.subTest(timeout=value),self.assertRaisesRegex(ValueError,'GG_OBSERVER_RECOVERY_ARGUMENTS'):
                    recovery.restore_observer('OwnNode','/public/history.ggfin','Observer',timeout=value)
            child.assert_not_called()
        member=self.observer();name=member.name;member.close();owner=self.idle()
        with patch.object(archive,'_run') as child:
            with self.assertRaisesRegex(ValueError,'GG_FINANCIAL_HISTORY_PATH'):recovery.restore_observer(owner,'relative.ggfin',name)
            child.assert_not_called()


class ObserverRecoveryRuntimeTests(unittest.TestCase):
    def test_runtime_routes_one_owned_operation_and_preserves_unlock_stop_and_argument_fences(self):
        manager=runtime.LanDagRuntime();self.addCleanup(manager.stop)
        with patch.object(recovery,'restore_observer',return_value={'policy_seam':True}) as work:
            result=manager.dispatch('lan.observer_history_restore',{'profile':'OwnNode','observer':'OwnObserver','path':'/public/history.ggfin'})
            self.assertTrue(result['policy_seam']);self.assertEqual(work.call_args.kwargs['observer'],'OwnObserver')
            self.assertFalse(manager._archive_importing)
            with self.assertRaises(ValueError):manager.dispatch('lan.observer_history_restore',{'profile':'OwnNode','observer':'OwnObserver','path':'/public/history.ggfin','force':True})
            manager._peer=object()
            try:
                with self.assertRaisesRegex(ValueError,'GG_LAN_STOP_BEFORE_FINANCIAL_HISTORY'):manager.financial_history('observer-restore',profile='OwnNode',observer='OwnObserver',path='/public/history.ggfin')
            finally:manager._peer=None
        def cancel(**options):manager._stop_requested.set();options['check']()
        with patch.object(recovery,'restore_observer',side_effect=cancel):
            with self.assertRaisesRegex(ValueError,'GG_FINANCIAL_HISTORY_CANCELLED'):manager.financial_history('observer-restore',profile='OwnNode',observer='OwnObserver',path='/public/history.ggfin')
        service=terminal_service.TerminalService();self.addCleanup(service.close);service._portable=True
        with patch.object(service,'_password',side_effect=ValueError('UNIT_VISIBLE_UNLOCK_REQUIRED')) as password:
            with self.assertRaisesRegex(ValueError,'UNIT_VISIBLE_UNLOCK_REQUIRED'):service.dispatch('lan.observer_history_restore',{'profile':'OwnNode','observer':'OwnObserver','path':'/public/history.ggfin'})
            password.assert_called_once()


if __name__=='__main__':unittest.main()
