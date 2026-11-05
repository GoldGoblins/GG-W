"""Real protected LAN/profile control; native launch is an explicit policy seam."""
from copy import deepcopy
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import patch

from backend import gg_observer_control as control,gg_observer_profile as profiles
from tests import test_lan_validator_runtime as fixture


class PolicySDK:
    """No SDK, sockets or certificate verification is claimed by these tests."""
    def __init__(self,profile,owner):
        self.profile=profile;self.owner=owner;self.anchor=profile.anchor();self._node={}
        self._tip=None;self._view_epoch=None;self.running=False;self.event=None;self.starts=0;self.stops=0;self._closed=False
    def _alive(self):return self.running
    def start(self,*,cancel):
        self.event=cancel;self.starts+=1
        if cancel.is_set():raise ValueError('GG_OBSERVER_STOPPED')
        self.running=True
    def request_stop(self):self.running=False
    def stop(self):self.running=False;self.stops+=1
    def close(self):self.stop();self._closed=True
    def refresh_status(self):return self.snapshot()
    def snapshot(self):
        return {'profile':self.profile.name,'state':'RUNNING' if self.running else 'STOPPED',
            'owned_native_process':self.running,'voting_power':0,'consensus_signing':False,
            'local_state_read_from_owned_sdk':False,
            'native_connection':{'state':'UNOBSERVED','connected':False,'latest_height':'0'}}


class ObserverRuntimeTests(unittest.TestCase):
    cleanup=fixture.ValidatorRuntimeTests.cleanup
    manager=fixture.ValidatorRuntimeTests.manager
    network=fixture.ValidatorRuntimeTests.network

    def setUp(self):
        fixture.ValidatorRuntimeTests.setUp(self)
        scope=patch.object(profiles,'ROOT',Path(self.temp.name)/'observers');scope.start();self.addCleanup(scope.stop)

    def test_idle_status_and_constructor_do_not_create_observer_keys_or_workers(self):
        manager=self.manager('Owned')
        snapshot=manager.snapshot()['native_observers']
        self.assertEqual(snapshot,control.empty_snapshot())
        self.assertFalse(Path(profiles.ROOT).exists());self.assertIsNone(manager._observers)

    def test_real_create_open_has_two_distinct_delegates_no_new_validator_and_no_sdk(self):
        first,second,phone,_=self.network();before=phone.snapshot()['dag_consensus']
        for name in ('ObserverA','ObserverB'):phone.dispatch('lan.observer_create',{'profile':name})
        manager=phone._observers
        grants=[value.public_grant()['body'] for value in manager.profiles.values()]
        self.assertEqual(len({value['producer_key'] for value in grants}),2)
        self.assertEqual(len({value['node_key'] for value in grants}),2)
        self.assertTrue(all(value['owner_peer_key']==phone._peer.public_key for value in grants))
        self.assertEqual(phone.snapshot()['dag_consensus'],before)
        self.assertFalse(manager.nodes);self.assertIsNone(manager._status_thread)
        self.assertFalse(phone.snapshot()['lan']['participation']['native_full_observer'])
        self.assertTrue(phone.observer_unlocked('ObserverA'))
        with self.assertRaisesRegex(ValueError,'LOCAL_PROFILE_LIMIT'):phone.dispatch('lan.observer_create',{'profile':'Third'})
        with self.assertRaisesRegex(ValueError,'EXISTS_USE_RESUME'):phone.dispatch('lan.observer_create',{'profile':'ObserverA'})
        public=phone.snapshot()['native_observers'];self.assertEqual(public['validator_votes'],0)
        self.assertNotIn('protected_key',str(public));self.assertNotIn('ciphertext',str(public))

    def test_wrong_role_ephemeral_owner_unbound_and_duplicate_slot_refuse(self):
        empty=fixture.runtime.LanDagRuntime();self.managers.append(empty)
        empty.dispatch('lan.start',{'label':'RAM','bind_host':'127.0.0.1','port':0})
        with self.assertRaisesRegex(ValueError,'PERSISTENT_OWNER'):empty.dispatch('lan.observer_create',{'profile':'Bad'})
        first,second,phone,_=self.network()
        phone.dispatch('lan.observer_create',{'profile':'A','producer_slot':0})
        with self.assertRaisesRegex(ValueError,'SLOT_IN_USE'):phone.dispatch('lan.observer_create',{'profile':'B','producer_slot':0})
        phone._peer.node_role='light'
        with self.assertRaisesRegex(ValueError,'LIGHT_READ_ONLY'):phone.dispatch('lan.observer_start',{'profile':'A'})
        self.assertFalse((Path(profiles.ROOT)/'B').exists())

    def test_restart_events_are_distinct_but_idempotent_start_keeps_same_operation(self):
        _,_,phone,_=self.network();phone.dispatch('lan.observer_create',{'profile':'A'});manager=phone._observers
        with patch.object(control,'OwnedObserver',PolicySDK),patch.object(manager,'_ensure_workers'):
            phone.dispatch('lan.observer_start',{'profile':'A'});event=manager.events['A'];node=manager.nodes['A']
            phone.dispatch('lan.observer_start',{'profile':'A'})
            self.assertIs(manager.events['A'],event);self.assertFalse(event.is_set())
            phone.dispatch('lan.observer_stop',{'profile':'A'});self.assertTrue(event.is_set())
            self.assertFalse(phone.snapshot()['native_observers']['profiles'][0]['native_connection']['connected'])
            node.stop();manager.stopping.clear()
            phone.dispatch('lan.observer_start',{'profile':'A'})
            self.assertIsNot(manager.events['A'],event);self.assertFalse(manager.events['A'].is_set())
            self.assertEqual(phone.snapshot()['native_observers']['own_running'],1)
            self.assertEqual(phone.snapshot()['dag_consensus']['validator_count'],4)

    def test_stop_interrupts_blocked_start_without_runtime_control_lock_or_sibling_stop(self):
        _,_,phone,_=self.network()
        for name in ('A','B'):phone.dispatch('lan.observer_create',{'profile':name})
        manager=phone._observers;entered=threading.Event();result=[]
        class DelayedSDK(PolicySDK):
            def start(self,*,cancel):
                if self.profile.name=='A':
                    entered.set();cancel.wait(3)
                return super().start(cancel=cancel)
        def launch():
            try:phone.dispatch('lan.observer_start',{'profile':'A'})
            except ValueError as error:result.append(str(error))
        with patch.object(control,'OwnedObserver',DelayedSDK),patch.object(manager,'_ensure_workers'):
            phone.dispatch('lan.observer_start',{'profile':'B'})
            worker=threading.Thread(target=launch);worker.start();self.assertTrue(entered.wait(2))
            start=time.monotonic();phone.dispatch('lan.observer_stop',{'profile':'A'});phone.snapshot()
            self.assertLess(time.monotonic()-start,.5);worker.join(3);self.assertFalse(worker.is_alive())
            self.assertEqual(result,['GG_OBSERVER_STOPPED']);self.assertTrue(manager.nodes['B']._alive())
            self.assertFalse(manager.events['B'].is_set())

    def test_failed_native_start_cancels_its_enrollment_run_and_reports_fault(self):
        _,_,phone,_=self.network();phone.dispatch('lan.observer_create',{'profile':'A'});manager=phone._observers
        class FailedSDK(PolicySDK):
            def start(self,*,cancel):raise ValueError('GG_OBSERVER_LAUNCH_TEST_FAILURE')
        with patch.object(control,'OwnedObserver',FailedSDK),patch.object(manager,'_ensure_workers'):
            with self.assertRaisesRegex(ValueError,'LAUNCH_TEST_FAILURE'):phone.dispatch('lan.observer_start',{'profile':'A'})
        self.assertTrue(manager.events['A'].is_set());row=phone.snapshot()['native_observers']['profiles'][0]
        self.assertEqual(row['last_error'],'GG_OBSERVER_LAUNCH_TEST_FAILURE')
        self.assertFalse(row['native_connection']['connected']);self.assertFalse(row['owned_native_process'])

    def test_parallel_creates_reserve_distinct_real_producer_slots(self):
        _,_,phone,_=self.network();manager=phone._observer_controls();entered=threading.Event();resume=threading.Event();errors=[]
        original=profiles.ObserverProfile.create_for_owned_profile
        def delayed(name,*args,**kwargs):
            if name=='A':entered.set();self.assertTrue(resume.wait(5))
            return original(name,*args,**kwargs)
        def create():
            try:phone.dispatch('lan.observer_create',{'profile':'A'})
            except Exception as error:errors.append(str(error))
        with patch.object(profiles.ObserverProfile,'create_for_owned_profile',side_effect=delayed):
            worker=threading.Thread(target=create)
            # Portable passphrases use an explicit per-thread session, never a global cache.
            def unlocked_create():
                with fixture.vault.session('disposable validator runtime password'):create()
            worker=threading.Thread(target=unlocked_create);worker.start();self.assertTrue(entered.wait(2))
            try:phone.dispatch('lan.observer_create',{'profile':'B'})
            finally:resume.set();worker.join(5)
        self.assertFalse(worker.is_alive());self.assertEqual(errors,[])
        keys={value.public_grant()['body']['producer_key'] for value in manager.profiles.values()}
        self.assertEqual(len(keys),2);self.assertFalse(manager._reserved_slots)

    def test_failed_open_names_do_not_accumulate_operation_events(self):
        _,_,phone,_=self.network();manager=phone._observer_controls()
        for index in range(40):
            with self.assertRaises((ValueError,OSError)):
                phone.dispatch('lan.observer_open',{'profile':'Missing'+str(index)})
        self.assertFalse(manager.events);self.assertFalse(manager.busy);self.assertFalse(manager.profiles)
        self.assertFalse(manager._reserved_slots)

    def test_failed_constructor_is_visible_and_creates_no_worker_or_native_intent(self):
        _,_,phone,_=self.network();phone.dispatch('lan.observer_create',{'profile':'A'});manager=phone._observers
        with patch.object(control,'OwnedObserver',side_effect=ValueError('GG_CONSENSUS_TOOL_UNAVAILABLE')):
            with self.assertRaisesRegex(ValueError,'TOOL_UNAVAILABLE'):phone.dispatch('lan.observer_start',{'profile':'A'})
        row=manager.snapshot()['profiles'][0]
        self.assertEqual(row['last_error'],'GG_CONSENSUS_TOOL_UNAVAILABLE')
        self.assertFalse(row['native_started']);self.assertIsNone(manager._status_thread);self.assertIsNone(manager._enroll_thread)

    def test_native_exit_cause_is_not_hidden_by_a_racing_RPC_failure(self):
        _,_,phone,_=self.network();phone.dispatch('lan.observer_create',{'profile':'A'});manager=phone._observers
        class FailedSDK(PolicySDK):
            def snapshot(self):return {**super().snapshot(),'state':'FAULT','last_error':'GG_OBSERVER_NATIVE_PROCESS_EXITED','native_exit_code':1}
        with patch.object(control,'OwnedObserver',FailedSDK),patch.object(manager,'_ensure_workers'):
            phone.dispatch('lan.observer_start',{'profile':'A'})
        manager.errors['A']='GG_OBSERVER_OPERATION_UNAVAILABLE'
        row=manager.snapshot()['profiles'][0]
        self.assertEqual(row['state'],'FAULT');self.assertEqual(row['last_error'],'GG_OBSERVER_NATIVE_PROCESS_EXITED')
        self.assertEqual(row['native_exit_code'],1)

    def test_explicit_reopen_revalidates_unknown_commit_without_resetting_native_history_intent(self):
        _,_,phone,_=self.network();phone.dispatch('lan.observer_create',{'profile':'A'});manager=phone._observers
        profile=manager.profiles['A'];grant=profile.public_grant();commit=profile._commit
        def lost_return():commit();raise OSError('public fixture lost start acknowledgement')
        with patch.object(profile,'_commit',side_effect=lost_return):
            with self.assertRaisesRegex(ValueError,'WRITE_FAILED'):profile.claim_native_start()
        self.assertFalse(manager.unlocked('A'))
        with patch.object(control,'OwnedObserver',side_effect=AssertionError('native start before cold validation')):
            with self.assertRaisesRegex(ValueError,'REOPEN_REQUIRED'):phone.dispatch('lan.observer_start',{'profile':'A'})
        phone.dispatch('lan.observer_open',{'profile':'A'});loaded=manager.profiles['A']
        self.assertIsNot(loaded,profile);self.assertEqual(loaded.public_grant(),grant)
        self.assertTrue(loaded.snapshot()['native_started']);self.assertTrue(manager.unlocked('A'))
        with self.assertRaisesRegex(ValueError,'HISTORY_MISSING'):loaded.claim_native_start()
        self.assertFalse(manager.nodes);self.assertIsNone(manager._status_thread)

    def test_reopen_password_failure_keeps_old_identity_until_successful_revalidation(self):
        from backend import gg_node_vault
        with patch.object(gg_node_vault,'provider',return_value='SCRYPT_AES256_GCM'):
            _,_,phone,_=self.network();phone.dispatch('lan.observer_create',{'profile':'A'});manager=phone._observers
            profile=manager.profiles['A'];grant=profile.public_grant();profile.close()
            with fixture.vault.session('different public fixture password'):
                with self.assertRaises(ValueError):phone.dispatch('lan.observer_open',{'profile':'A'})
            self.assertIs(manager.profiles['A'],profile);self.assertEqual(profile.public_grant(),grant)
            self.assertFalse(manager.unlocked('A'));self.assertFalse(manager.nodes)
            phone.dispatch('lan.observer_open',{'profile':'A'})
            self.assertTrue(manager.unlocked('A'));self.assertEqual(manager.profiles['A'].public_grant(),grant)

    def test_changed_reopened_grant_cannot_replace_cached_identity(self):
        _,_,phone,_=self.network();phone.dispatch('lan.observer_create',{'profile':'A'});manager=phone._observers
        phone.dispatch('lan.observer_create',{'profile':'B'})
        old=manager.profiles['A'];grant=old.public_grant();old.close();loaded=profiles.ObserverProfile.open('A')
        changed=manager.profiles['B'].public_grant()
        # Policy seam after real decryption; this is not a forged-disk crypto test.
        with patch.object(profiles.ObserverProfile,'open',return_value=loaded),patch.object(loaded,'public_grant',return_value=changed):
            with self.assertRaisesRegex(ValueError,'REOPEN_IDENTITY_OR_ANCHOR_CHANGED'):phone.dispatch('lan.observer_open',{'profile':'A'})
        self.assertIs(manager.profiles['A'],old);self.assertEqual(old.public_grant(),grant);self.assertTrue(loaded._closed)


if __name__=='__main__':unittest.main()
