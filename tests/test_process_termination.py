"""Owned OS-terminal proof and release ordering, never SDK/crypto acceptance.

Windows cases use benign Python children and the exact borrowed Popen handle.
Other cases declare fake kernel outcomes solely for finite ownership/policy
regressions. They do not stand in for an actual process signal or certificate.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,call,patch

from backend import gg_process_termination as termination
from backend import gg_consensus_process as process_transport
from backend import gg_native_start as native_start
from backend import gg_native_process_policy as policy
from backend import gg_protocol_runtime as runtime
from backend import gg_committee_history as histories
from backend.gg_native_resources import LOW


class BorrowedProcessTerminalTests(unittest.TestCase):
    def child(self,source):
        child=subprocess.Popen([getattr(sys,'_base_executable',sys.executable),'-I','-c',source],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        self.addCleanup(self.finish,child)
        return child

    def finish(self,child):
        # Independent cleanup never trusts the deliberately injected cache.
        child.returncode=None;terminal=False
        try:
            try:child.kill()
            except OSError:pass
            if os.name=='nt':
                import _winapi
                if _winapi.WaitForSingleObject(child._handle,3000)!=_winapi.WAIT_OBJECT_0:
                    raise AssertionError('PUBLIC owned child cleanup did not signal')
                child.returncode=_winapi.GetExitCodeProcess(child._handle)
            else:child.wait(timeout=3)
            terminal=True
        finally:
            if terminal:
                for stream in (child.stdin,child.stdout):
                    if stream is not None:stream.close()

    def test_posix_delegates_to_normal_wait_and_preserves_timeout_error(self):
        child=SimpleNamespace(wait=Mock(return_value=9))
        with patch.object(termination,'_WINDOWS',False):
            self.assertEqual(termination.wait_process_terminal(child,2.5),9)
            child.wait.assert_called_once_with(timeout=2.5)
            failure=subprocess.TimeoutExpired('PUBLIC child',.1);child.wait.side_effect=failure
            with self.assertRaises(subprocess.TimeoutExpired) as rejected:termination.wait_process_terminal(child,.1)
            self.assertIs(rejected.exception,failure)

    def test_windows_path_requires_borrowed_handle_without_pid_fallback(self):
        class NoHandle:
            @property
            def pid(self):raise AssertionError('PID lookup forbidden')
        with patch.object(termination,'_WINDOWS',True):
            with self.assertRaisesRegex(OSError,'^GG_PROCESS_OWNED_HANDLE_UNAVAILABLE$'):
                termination.wait_process_terminal(NoHandle(),0)

    @unittest.skipUnless(os.name=='nt','Windows process-handle signal regression')
    def test_cached_returncode_cannot_make_a_live_owned_child_terminal(self):
        import _winapi
        child=self.child('import time;time.sleep(30)');handle=child._handle
        self.assertEqual(_winapi.WaitForSingleObject(handle,0),_winapi.WAIT_TIMEOUT)
        child.returncode=73
        self.assertEqual(child.poll(),73)
        self.assertEqual(child.wait(timeout=0),73,'fault must exercise the Popen cached-result path')
        with self.assertRaises(subprocess.TimeoutExpired):termination.wait_process_terminal(child,.025)
        self.assertFalse(termination.process_terminal(child))
        self.assertIs(child._handle,handle);self.assertFalse(child.stdin.closed);self.assertFalse(child.stdout.closed)
        self.assertEqual(_winapi.WaitForSingleObject(handle,0),_winapi.WAIT_TIMEOUT)

    @unittest.skipUnless(os.name=='nt','Windows process-handle signal regression')
    def test_actual_exit_is_terminal_with_the_same_retained_borrowed_handle(self):
        import _winapi
        child=self.child('pass');handle=child._handle
        self.assertEqual(termination.wait_process_terminal(child,3),0)
        self.assertEqual(_winapi.WaitForSingleObject(handle,0),_winapi.WAIT_OBJECT_0)
        child.returncode=73
        self.assertEqual(termination.wait_process_terminal(child,0),0)
        self.assertEqual(child.returncode,0);self.assertTrue(termination.process_terminal(child))
        self.assertIs(child._handle,handle)
        self.assertEqual(_winapi.WaitForSingleObject(handle,0),_winapi.WAIT_OBJECT_0)


    @unittest.skipUnless(os.name=='nt','Windows detached native-pipe Job accounting regression')
    def test_detached_native_pipes_preserve_one_process_job_and_exact_public_io(self):
        import ctypes
        from ctypes import wintypes
        import time
        import _winapi
        from backend import gg_testnet_process as limits

        class Accounting(ctypes.Structure):
            _fields_=[('user',ctypes.c_int64),('kernel',ctypes.c_int64),
                ('period_user',ctypes.c_int64),('period_kernel',ctypes.c_int64),
                ('faults',wintypes.DWORD),('total',wintypes.DWORD),
                ('active',wintypes.DWORD),('limited',wintypes.DWORD)]

        public_input=b'PUBLIC_NATIVE_PIPE_PROBE\n'
        source="""import sys
payload=sys.stdin.buffer.readline(128)
if payload!=b'PUBLIC_NATIVE_PIPE_PROBE\\n':raise SystemExit(92)
sys.stdout.buffer.write(b'PUBLIC_NATIVE_PIPE_OK:'+payload)
sys.stdout.buffer.flush()
"""
        flags=native_start.native_pipe_creation_flags()
        self.assertEqual(flags,subprocess.DETACHED_PROCESS)
        deadline=time.monotonic()+3
        child=subprocess.Popen([str(Path(sys._base_executable).resolve()),'-I','-c',source],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
            creationflags=flags)
        self.addCleanup(self.finish,child)
        handle=child._handle
        lease=limits.contain(child);self.addCleanup(lease.close)
        self.assertEqual(lease.facts,{'provider':'WINDOWS_JOB_OBJECT','verified':True,
            'memory_bytes':512*1024**2,'cpu_seconds':300,'active_process_limit':1,'kill_on_close':True,
            'resource_profile':LOW.wire()})
        self.assertEqual(_winapi.WaitForSingleObject(handle,0),_winapi.WAIT_TIMEOUT)
        output,error=child.communicate(public_input,timeout=max(0,deadline-time.monotonic()))
        self.assertEqual((output,error),(b'PUBLIC_NATIVE_PIPE_OK:'+public_input,None))
        self.assertEqual(termination.wait_process_terminal(child,max(0,deadline-time.monotonic())),0)
        self.assertIs(child._handle,handle)
        self.assertEqual(_winapi.WaitForSingleObject(handle,0),_winapi.WAIT_OBJECT_0)
        accounting=Accounting()
        self.assertTrue(lease._kernel.QueryInformationJobObject(lease._job,1,
            ctypes.byref(accounting),ctypes.sizeof(accounting),None))
        self.assertEqual((accounting.total,accounting.active,accounting.limited),(1,0,0))
        lease.close();self.assertTrue(lease.closed)


class ReleaseOwnershipTests(unittest.TestCase):
    def process_double(self):
        return SimpleNamespace(returncode=73,poll=Mock(return_value=73),terminate=Mock(),kill=Mock(),
            stdin=SimpleNamespace(close=Mock()),stdout=SimpleNamespace(close=Mock()))

    def controller(self,child):
        class Controller(process_transport.OwnedNativeRPC):
            def _owner_stopped(self):return False
        controller=Controller();controller._lock=threading.RLock();controller._epoch_stopping=False
        controller._monitor_cancel=None;controller._connection=None
        controller._node={'process':child,'_ready':None};controller._lease=SimpleNamespace(close=Mock())
        return controller

    def test_native_stop_keeps_exact_child_lease_and_pipes_when_kernel_never_signals(self):
        child=self.process_double();controller=self.controller(child)
        node=controller._node;lease=controller._lease
        def pending(selected,timeout):raise subprocess.TimeoutExpired('PUBLIC child',timeout)
        with patch.object(termination,'process_terminal',return_value=False), \
                patch.object(termination,'wait_process_terminal',side_effect=pending) as wait:
            with self.assertRaisesRegex(ValueError,'^GG_VALIDATOR_STOP_FAILED$'):controller.stop()
        self.assertIs(controller._node,node);self.assertIs(controller._node['process'],child)
        self.assertIs(controller._lease,lease);self.assertTrue(controller._epoch_stopping)
        self.assertEqual(wait.call_args_list,[call(child,4),call(child,3),call(child,3)])
        child.poll.assert_not_called();child.terminate.assert_called_once_with()
        self.assertEqual(child.kill.call_count,2)
        child.stdin.close.assert_not_called();child.stdout.close.assert_not_called()

    def test_native_stop_releases_only_after_kernel_terminal_proof(self):
        child=self.process_double();controller=self.controller(child);lease=controller._lease
        with patch.object(termination,'process_terminal',return_value=True), \
                patch.object(termination,'wait_process_terminal',return_value=0) as wait:
            controller.stop()
        self.assertIsNone(controller._node['process']);self.assertIsNone(controller._lease)
        wait.assert_called_once_with(child,4);lease.close.assert_called_once_with()
        child.stdin.close.assert_called_once_with();child.stdout.close.assert_called_once_with()
        child.kill.assert_not_called();child.terminate.assert_not_called()

    def test_fresh_no_input_intent_is_not_released_for_cached_exit_without_signal(self):
        with tempfile.TemporaryDirectory(prefix='gg-terminal-intent-') as temporary:
            profile=SimpleNamespace(_lock=threading.Lock(),root=Path(temporary)/'PUBLIC-profile',
                _closed=False,_failed=False,_db=object(),_lease=object(),
                _body={'native_started':True,'certificate':None,'fault':''},_write=Mock())
            child=self.process_double()
            # This is solely the release-policy seam for an already active
            # reservation. Constructor validation still requires real protected
            # profile/Popen types and is exercised by the actual start suite.
            reservation=native_start.NativeStartReservation.__new__(native_start.NativeStartReservation)
            reservation._profile=profile;reservation._process=child
            reservation._active=True;reservation._thread=threading.get_ident()
            reservation._fresh=True;reservation._input_started=False
            reservation._db=profile._db;reservation._lease=profile._lease
            reservation._body=dict(profile._body);profile._lock.acquire()
            with patch.object(termination,'process_terminal',return_value=False):
                with self.assertRaisesRegex(ValueError,'^GG_NATIVE_START_ABORT_NOT_PROVEN$'):
                    reservation.__exit__(ValueError,ValueError('GG_PUBLIC_UNIT_CANCELLED'),None)
            self.assertTrue(profile._body['native_started']);profile._write.assert_not_called()
            self.assertTrue(profile._lock.acquire(blocking=False));profile._lock.release()

    def test_group_pending_retains_registry_children_and_one_total_deadline(self):
        children=[Mock() for unused in range(3)];group=policy._Group.__new__(policy._Group)
        group._lock=threading.RLock();group._closed=False;group._kernel=None;group._job=None
        group._children=set(children);owner=object();groups={owner:group};ended=set()
        try:
            with patch.object(policy,'_groups',groups),patch.object(policy,'_ended',ended), \
                    patch.object(termination,'process_terminal',return_value=False), \
                    patch.object(policy.time,'monotonic',side_effect=[100,101,102,104]), \
                    patch.object(termination,'wait_process_terminal',side_effect=subprocess.TimeoutExpired('PUBLIC child',3)) as wait:
                with self.assertRaisesRegex(RuntimeError,'^GG_NATIVE_GROUP_STOP_FAILED$'):policy.close_owner(owner)
            self.assertIs(groups[owner],group);self.assertEqual(group._children,set(children))
            self.assertIn(owner,ended);self.assertTrue(group._closed)
            self.assertEqual([entry.args[1] for entry in wait.call_args_list],[2,1,0])
            self.assertEqual({entry.args[0] for entry in wait.call_args_list},set(children))
            for child in children:child.kill.assert_called_once_with()
        finally:group._children.clear()

    def test_group_pruning_keeps_unsignaled_child_despite_cached_exit(self):
        old=Mock();old.poll.return_value=73;new=Mock();new.poll.return_value=None
        group=policy._Group.__new__(policy._Group);group._lock=threading.RLock()
        group._closed=False;group._kernel=None;group._job=None;group._children={old};group._resources=LOW
        try:
            with patch.object(termination,'process_terminal',return_value=False):group.attach(new)
            self.assertEqual(group._children,{old,new});old.poll.assert_not_called()
        finally:group._children.clear()

    def test_runtime_owner_preflight_pending_keeps_every_profile_until_exact_retry(self):
        controller=runtime.ProtocolRuntime();events=[]
        controller.stop_node=Mock(side_effect=lambda:events.append('stop_node'))
        def profile(name):return SimpleNamespace(close=Mock(side_effect=lambda:events.append(name)))
        account=profile('account');validator=profile('validator');replica=profile('replica');owner=profile('owner')
        controller.accounts={'PUBLIC-account':account};controller.validators={'PUBLIC-validator':validator}
        controller.replicas={'PUBLIC-replica':replica};controller.owner=owner
        collections=(controller.accounts,controller.validators,controller.replicas)
        calls=0
        def preflight(selected):
            nonlocal calls
            self.assertIs(selected,owner);calls+=1;events.append('owner_preflight')
            if calls==1:raise RuntimeError('GG_NATIVE_GROUP_STOP_FAILED')
        with patch.object(policy,'close_owner',side_effect=preflight), \
                patch.object(histories,'close_all',side_effect=lambda:events.append('histories')):
            with self.assertRaisesRegex(RuntimeError,'^GG_NATIVE_GROUP_STOP_FAILED$'):controller.close()
            self.assertEqual(events,['stop_node','owner_preflight']);self.assertIs(controller.owner,owner)
            self.assertIs(controller.accounts,collections[0]);self.assertEqual(controller.accounts,{'PUBLIC-account':account})
            self.assertIs(controller.validators,collections[1]);self.assertEqual(controller.validators,{'PUBLIC-validator':validator})
            self.assertIs(controller.replicas,collections[2]);self.assertEqual(controller.replicas,{'PUBLIC-replica':replica})
            for value in (account,validator,replica,owner):value.close.assert_not_called()
            controller.close()
        self.assertEqual(events,['stop_node','owner_preflight','stop_node','owner_preflight','account','validator','replica','owner','histories'])
        self.assertIsNone(controller.owner);self.assertEqual(controller.accounts,{})
        self.assertEqual(controller.validators,{});self.assertEqual(controller.replicas,{})


if __name__=='__main__':unittest.main()
