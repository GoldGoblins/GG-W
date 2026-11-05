"""Native ownership/OS termination contracts, not crypto or network evidence.

Fake process outcomes below are explicitly lifecycle policy seams. Windows
cases use actual benign base-Python children and borrowed kernel handles.
"""
import os
from collections import OrderedDict
from contextlib import ExitStack
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from backend import gg_consensus as legacy
from backend import gg_native_pipe_lifecycle as pipes
from backend import gg_process_termination as terminal
from backend import gg_native_start as native_start
from backend import gg_node_store as nodes
from backend import gg_testnet_process as limits
from backend import gg_committee_history as histories
from backend import gg_protocol_transport as relay
from backend.gg_ed25519 import Keypair
from backend import gg_consensus_process as rpc_transport
from backend import gg_native_process_policy as native_policy


def process_double():
    return SimpleNamespace(returncode=73,poll=Mock(return_value=73),kill=Mock(),terminate=Mock(),
        stdin=SimpleNamespace(close=Mock()),stdout=SimpleNamespace(close=Mock()))


class FixedNativePipeOwnershipTests(unittest.TestCase):
    def test_protected_transport_requires_real_owned_objects_and_exact_key_pin_linkage(self):
        from backend import gg_observer_profile as observers,portable_wallet_vault as vault
        from tests.test_durable_node_store import configuration
        from tests.test_protocol_integrated_profiles import public_protocol_pin
        with tempfile.TemporaryDirectory(prefix='gg-pipe-binding-') as temporary,ExitStack() as stack:
            root=Path(temporary);stack.enter_context(patch.object(nodes,'ROOT',root/'nodes'))
            stack.enter_context(patch.object(observers,'ROOT',root/'observers'))
            stack.enter_context(vault.session('PUBLIC disposable profile binding fixture password'))
            owner=nodes.NodeProfile.create('Owner',configuration());other=nodes.NodeProfile.create('Other',configuration());profile=None
            try:
                pin=public_protocol_pin();profile=observers.ObserverProfile.create_for_protocol('Light',owner,pin,label='Public binding test')
                key=profile.native_node_signer()
                self.assertEqual(relay._protected_context(key,pin,owner,profile),(owner,profile))
                with self.assertRaisesRegex(ValueError,'OWNER_MISMATCH'):relay._protected_context(key,pin,other,profile)
                with self.assertRaisesRegex(ValueError,'OWNER_MISMATCH'):relay._protected_context(Keypair(),pin,owner,profile)
                forged=SimpleNamespace(_closed=False,_failed=False,_lease=owner._lease,_db=owner._db,_lock=owner._lock,descriptor=owner.descriptor)
                with self.assertRaisesRegex(ValueError,'OWNED_PROFILE_REQUIRED'):relay._protected_context(key,pin,forged,profile)
            finally:
                if profile is not None:profile.close()
                other.close();owner.close()

    def test_pending_retains_child_leaf_pipes_and_exact_journals_until_explicit_retry(self):
        slot=pipes._FiniteSlot(3);child=process_double();leaf=SimpleNamespace(close=Mock())
        owner=SimpleNamespace(_lock=threading.RLock(),_closed=False,_failed=False)
        close=Mock();owner.close=close
        try:
            with patch.object(pipes,'_FINITE_SLOTS',(slot,)),patch.object(terminal,'process_terminal',return_value=False), \
                    patch.object(terminal,'wait_process_terminal',side_effect=subprocess.TimeoutExpired('PUBLIC owned child',3)):
                with self.assertRaises(pipes.NativePipeStopPending) as rejected:
                    with slot.operation((owner,),close_on_pending=(owner,)):
                        slot.attach(child);slot.lease=leaf
                self.assertTrue(rejected.exception.transferred(owner))
                with self.assertRaises(pipes.NativePipeStopPending):pipes.fence_owner_close(owner)
                self.assertIs(slot.process,child);self.assertIs(slot.lease,leaf)
                self.assertEqual(slot.owners,(owner,));self.assertEqual(slot._closers,(owner,))
                leaf.close.assert_not_called();child.stdin.close.assert_not_called();child.stdout.close.assert_not_called()
                close.assert_not_called();child.poll.assert_not_called()
            with patch.object(terminal,'process_terminal',return_value=True),patch.object(terminal,'wait_process_terminal',return_value=0):slot.retire()
            self.assertIsNone(slot.process);self.assertIsNone(slot.lease);self.assertEqual(slot.owners,())
            self.assertEqual(slot._closers,());leaf.close.assert_called_once_with();close.assert_called_once_with()
        finally:
            slot.process=None;slot.lease=None;slot.owners=();slot._closers=();slot._blocked=False

    def test_active_or_pending_slot_never_overwrites_an_exact_owner(self):
        slot=pipes._FiniteSlot(5);child=process_double()
        with patch.object(terminal,'process_terminal',return_value=True),patch.object(terminal,'wait_process_terminal',return_value=0):
            with slot.operation():
                slot.attach(child)
                with self.assertRaisesRegex(ValueError,'^GG_NATIVE_PIPE_BUSY$'):
                    with slot.operation():self.fail('reentrant launch must be rejected')
                self.assertTrue(slot._active);self.assertIs(slot.process,child)
        self.assertIsNone(slot.process)

    def test_owner_close_and_publication_share_lock_without_lock_inversion(self):
        slot=pipes._FiniteSlot(3);owner=SimpleNamespace(_lock=threading.RLock(),_closed=False,_failed=False)
        acquired=threading.Event();release=threading.Event();outcomes=[]
        def closing():
            with owner._lock:
                acquired.set();release.wait(2)
                with patch.object(pipes,'_FINITE_SLOTS',(slot,)):pipes.fence_owner_close(owner)
                outcomes.append('closed-fence')
        thread=threading.Thread(target=closing);thread.start()
        try:
            self.assertTrue(acquired.wait(1))
            with self.assertRaisesRegex(ValueError,'^GG_NATIVE_PIPE_OWNER_BUSY$'):
                with slot.operation((owner,)):self.fail('busy profile must not publish')
            self.assertIsNone(slot.process);self.assertEqual(slot.owners,())
        finally:release.set();thread.join(2)
        self.assertFalse(thread.is_alive());self.assertEqual(outcomes,['closed-fence'])
        with self.assertRaisesRegex(ValueError,'^GG_NATIVE_PIPE_OWNER_CLOSED$'):
            with slot.operation((owner,)):self.fail('closed intent must remain closed')

    def test_real_node_close_method_keeps_journal_keys_and_lease_under_pending_fence(self):
        # Explicit lease-policy double; no protected-key/crypto claim is made.
        owner=nodes.NodeProfile.__new__(nodes.NodeProfile)
        owner._lock=threading.RLock();owner._closed=False;owner._failed=False
        owner._db=SimpleNamespace(close=Mock());owner._keys=[b'PUBLIC test key placeholder']
        owner._lease=object();owner._segmented_writer=None
        slot=pipes._FiniteSlot(5);slot.owners=(owner,);slot._blocked=True;slot.process=process_double()
        db,keys,lease=owner._db,owner._keys,owner._lease
        try:
            with patch.object(pipes,'_FINITE_SLOTS',(slot,)),patch.object(terminal,'process_terminal',return_value=False), \
                    patch.object(terminal,'wait_process_terminal',side_effect=subprocess.TimeoutExpired('PUBLIC child',5)):
                with self.assertRaises(pipes.NativePipeStopPending):owner.close()
            self.assertIs(owner._db,db);self.assertIs(owner._keys,keys);self.assertIs(owner._lease,lease)
            self.assertFalse(owner._closed);db.close.assert_not_called()
        finally:slot.process=None;slot.owners=();slot._blocked=False

    def test_failed_constructor_keeps_unpublished_object_and_retries_before_next_allocation(self):
        slot=pipes._ConstructionSlot();events=[]
        owner=SimpleNamespace(close=Mock(side_effect=pipes.NativePipeStopPending()))
        with self.assertRaises(pipes.NativePipeStopPending):
            with slot.construction() as reservation:
                reservation.attach(owner);raise ValueError('PUBLIC handshake failure')
        self.assertIs(slot.owner,owner)
        with self.assertRaises(pipes.NativePipeStopPending):
            with slot.construction():events.append('forbidden-new-constructor')
        self.assertEqual(events,[]);self.assertIs(slot.owner,owner)
        owner.close.side_effect=None
        with slot.construction():events.append('next-constructor-after-terminal')
        self.assertIsNone(slot.owner);self.assertEqual(events,['next-constructor-after-terminal'])

    def test_cancellation_before_spawn_clears_only_empty_reservation(self):
        slot=pipes._FiniteSlot(3);owner=SimpleNamespace(_lock=threading.RLock(),_closed=False,_failed=False)
        with self.assertRaisesRegex(ValueError,'^GG_PUBLIC_CANCELLED$'):
            with slot.operation((owner,)):raise ValueError('GG_PUBLIC_CANCELLED')
        self.assertIsNone(slot.process);self.assertEqual(slot.owners,());self.assertFalse(slot._blocked)

    def test_after_terminal_callback_fault_keeps_exact_duty_without_reclosing_completed_resources(self):
        slot=pipes._FiniteSlot(3);child=process_double();leaf=SimpleNamespace(close=Mock())
        first=SimpleNamespace(close=Mock());second=SimpleNamespace(close=Mock(side_effect=[RuntimeError('PUBLIC close fault'),None]))
        with patch.object(terminal,'process_terminal',return_value=True),patch.object(terminal,'wait_process_terminal',return_value=0) as wait:
            with self.assertRaisesRegex(RuntimeError,'^PUBLIC close fault$'):
                with slot.operation((first,second)):
                    slot.attach(child);slot.lease=leaf;slot.defer_close(first,second)
            self.assertIs(slot.process,child);self.assertIs(slot.lease,leaf)
            self.assertEqual(slot._closers,(second,));self.assertEqual(slot.owners,(first,second))
            self.assertTrue(slot._terminal);self.assertTrue(slot._lease_done);self.assertFalse(slot._blocked)
            slot.retire()
            self.assertEqual(wait.call_count,1)
        leaf.close.assert_called_once_with();child.stdin.close.assert_called_once_with();child.stdout.close.assert_called_once_with()
        first.close.assert_called_once_with();self.assertEqual(second.close.call_count,2)
        self.assertIsNone(slot.process);self.assertEqual(slot._closers,())

    def test_leaf_close_failure_keeps_exact_terminal_owner_until_same_leaf_retry(self):
        slot=pipes._FiniteSlot(5);child=process_double()
        leaf=SimpleNamespace(close=Mock(side_effect=[RuntimeError('PUBLIC leaf close fault'),None]))
        with patch.object(terminal,'process_terminal',return_value=True),patch.object(terminal,'wait_process_terminal',return_value=0) as wait:
            with self.assertRaises(pipes.NativePipeStopPending):
                with slot.operation():slot.attach(child);slot.lease=leaf
            self.assertIs(slot.process,child);self.assertIs(slot.lease,leaf);self.assertTrue(slot._terminal)
            self.assertFalse(slot._lease_done);self.assertTrue(slot._blocked)
            child.stdin.close.assert_not_called();child.stdout.close.assert_not_called()
            slot.retire();self.assertEqual(wait.call_count,1)
        self.assertEqual(leaf.close.call_count,2);child.stdin.close.assert_called_once_with();child.stdout.close.assert_called_once_with()
        self.assertIsNone(slot.process);self.assertIsNone(slot.lease)

    def test_unrelated_slot_does_not_wait_for_another_owners_close_callback(self):
        first=pipes._FiniteSlot(3);second=pipes._FiniteSlot(5)
        entered=threading.Event();release=threading.Event();outcome=[]
        owner=SimpleNamespace(close=lambda:(entered.set(),release.wait(2)))
        def work():
            with first.operation((owner,)):first.defer_close(owner)
            outcome.append('done')
        thread=threading.Thread(target=work);thread.start()
        try:
            self.assertTrue(entered.wait(1))
            with second.operation():outcome.append('independent-slot')
            self.assertEqual(outcome,['independent-slot'])
        finally:release.set();thread.join(2)
        self.assertFalse(thread.is_alive());self.assertEqual(outcome,['independent-slot','done'])

    def test_atomic_transfer_receipt_survives_retirement_and_new_generation_before_caller_finally(self):
        slot=pipes._FiniteSlot(3);child=process_double()
        owner=SimpleNamespace(_lock=threading.RLock(),_closed=False,_failed=False,close=Mock())
        replacement=SimpleNamespace(_lock=threading.RLock(),_closed=False,_failed=False)
        with patch.object(terminal,'process_terminal',return_value=False), \
                patch.object(terminal,'wait_process_terminal',side_effect=subprocess.TimeoutExpired('PUBLIC child',3)):
            with self.assertRaises(pipes.NativePipeStopPending) as rejected:
                with slot.operation((owner,),close_on_pending=(owner,)):slot.attach(child)
        self.assertTrue(slot.retains(owner))
        # Exact old TOCTOU point: caller has observed retention, but another
        # explicit retry completes retirement before its finally can transfer.
        with patch.object(terminal,'process_terminal',return_value=True),patch.object(terminal,'wait_process_terminal',return_value=0):slot.retire()
        with slot.operation((replacement,)):
            self.assertTrue(rejected.exception.transferred(owner))
            self.assertFalse(rejected.exception.transferred(replacement))
            self.assertFalse(pipes.NativePipeStopPending((owner,)).transferred(owner))
            self.assertEqual(slot.owners,(replacement,));self.assertEqual(slot._closers,())
        owner.close.assert_called_once_with()

    def test_owner_retirement_rechecks_exact_owner_after_observed_slot_generation_changes(self):
        slot=pipes._FiniteSlot(3)
        old=SimpleNamespace(_lock=threading.RLock(),_closed=False,_failed=False)
        new=SimpleNamespace(_lock=threading.RLock(),_closed=False,_failed=False)
        with slot.operation((new,)):
            slot.retire_owner(old)
            self.assertEqual(slot.owners,(new,));self.assertTrue(slot._active)

    def test_legacy_stop_keeps_entire_signer_and_temp_context_on_kernel_pending(self):
        child=process_double();leaf=SimpleNamespace(close=Mock());temporary=SimpleNamespace(cleanup=Mock())
        node={'process':child,'lease':leaf,'_ready':object()};accounts=[object()];signers=[object()]
        with patch.object(legacy,'_nodes',[node]),patch.object(legacy,'_temporary',temporary), \
                patch.object(legacy,'_accounts',accounts),patch.object(legacy,'_validator_keys',signers), \
                patch.object(legacy,'_drop_connection'),patch.object(terminal,'process_terminal',return_value=False), \
                patch.object(terminal,'wait_process_terminal',side_effect=subprocess.TimeoutExpired('PUBLIC child',4)):
            with self.assertRaisesRegex(ValueError,'^GG_CONSENSUS_STOP_FAILED$'):legacy.stop()
            self.assertIs(legacy._nodes[0],node);self.assertIs(node['process'],child);self.assertIs(node['lease'],leaf)
            self.assertIs(legacy._temporary,temporary);self.assertIs(legacy._accounts,accounts);self.assertIs(legacy._validator_keys,signers)
        temporary.cleanup.assert_not_called();leaf.close.assert_not_called();child.poll.assert_not_called()
        child.stdin.close.assert_not_called();child.stdout.close.assert_not_called()

    def test_legacy_restart_cannot_replace_cached_exit_before_retirement(self):
        child=process_double();node={'process':child,'lease':object()}
        with patch.object(legacy,'_nodes',[node]),patch.object(legacy,'_stop_process',side_effect=ValueError('GG_CONSENSUS_STOP_FAILED')) as stop, \
                patch.object(legacy.subprocess,'Popen') as spawn:
            with self.assertRaisesRegex(ValueError,'^GG_CONSENSUS_STOP_FAILED$'):legacy._launch(0)
        stop.assert_called_once_with(0);spawn.assert_not_called();self.assertIs(node['process'],child)


@unittest.skipUnless(os.name=='nt','Actual borrowed Windows process-handle lifecycle')
class WindowsNativePipeKernelTests(unittest.TestCase):
    def child(self,source):
        child=subprocess.Popen([str(Path(sys._base_executable).resolve()),'-I','-c',source],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
            creationflags=native_start.native_pipe_creation_flags())
        self.addCleanup(self.finish,child)
        return child

    def finish(self,child):
        import _winapi
        child.returncode=None
        try:child.kill()
        except OSError:pass
        self.assertEqual(_winapi.WaitForSingleObject(child._handle,3000),_winapi.WAIT_OBJECT_0)
        child.returncode=_winapi.GetExitCodeProcess(child._handle)
        for stream in (child.stdin,child.stdout):
            if stream is not None:stream.close()

    def test_live_cached_exit_retains_real_child_leaf_and_pipes_then_explicit_exit_retires(self):
        import _winapi
        child=self.child('import sys;sys.stdin.buffer.readline(32)');handle=child._handle
        leaf=limits.contain(child);self.addCleanup(leaf.close)
        slot=pipes._FiniteSlot(3)
        try:
            child.returncode=73
            with patch.object(child,'kill'):
                with self.assertRaises(pipes.NativePipeStopPending):
                    with slot.operation():slot.attach(child);slot.lease=leaf
            self.assertIs(slot.process,child);self.assertIs(slot.lease,leaf);self.assertFalse(leaf.closed)
            self.assertIs(child._handle,handle);self.assertFalse(child.stdin.closed);self.assertFalse(child.stdout.closed)
            self.assertEqual(_winapi.WaitForSingleObject(handle,0),_winapi.WAIT_TIMEOUT)
            child.stdin.write(b'PUBLIC exit\n');child.stdin.flush()
            self.assertEqual(terminal.wait_process_terminal(child,3),0)
            slot.retire();self.assertIsNone(slot.process);self.assertTrue(leaf.closed)
            self.assertEqual(_winapi.WaitForSingleObject(handle,0),_winapi.WAIT_OBJECT_0)
        finally:
            self.finish(child);slot.process=None;slot.lease=None

    def test_real_crash_is_terminal_and_does_not_poison_the_next_owned_operation(self):
        slot=pipes._FiniteSlot(5);child=self.child('import os;os._exit(17)');handle=child._handle
        terminal.wait_process_terminal(child,3);child.returncode=73
        with slot.operation():slot.attach(child)
        self.assertIsNone(slot.process);self.assertEqual(child.returncode,17)
        with slot.operation():pass
        import _winapi
        self.assertEqual(_winapi.WaitForSingleObject(handle,0),_winapi.WAIT_OBJECT_0)

    def test_failed_constructor_retains_real_unsignaled_pipe_until_its_same_close_succeeds(self):
        import _winapi
        child=self.child('import sys;sys.stdin.buffer.readline(32)');handle=child._handle
        class Incomplete:
            def close(self):
                try:terminal.wait_process_terminal(child,.025)
                except subprocess.TimeoutExpired:raise pipes.NativePipeStopPending() from None
                child.stdin.close();child.stdout.close()
        owner=Incomplete();slot=pipes._ConstructionSlot()
        with self.assertRaises(pipes.NativePipeStopPending):
            with slot.construction() as reservation:
                reservation.attach(owner);raise ValueError('PUBLIC constructor handshake failed')
        self.assertIs(slot.owner,owner);self.assertEqual(_winapi.WaitForSingleObject(handle,0),_winapi.WAIT_TIMEOUT)
        self.assertFalse(child.stdin.closed);self.assertFalse(child.stdout.closed)
        child.stdin.write(b'PUBLIC exit\n');child.stdin.flush();terminal.wait_process_terminal(child,3)
        with slot.construction():pass
        self.assertIsNone(slot.owner);self.assertEqual(_winapi.WaitForSingleObject(handle,0),_winapi.WAIT_OBJECT_0)

    def test_actual_history_constructor_publishes_failed_child_before_handshake_unwind(self):
        # Only the SDK message exchange is a policy seam. Child, Job and
        # _NativeStream.close's Windows kernel waits are genuine.
        import _winapi
        child=self.child('import sys;sys.stdin.buffer.readline(32)');handle=child._handle
        leaf=limits.contain(child);self.addCleanup(leaf.close)
        slot=pipes.COMMITTEE_STREAM_INIT
        self.assertIsNone(slot.owner)
        try:
            with patch.object(histories.subprocess,'Popen',return_value=child) as launch, \
                    patch.object(histories._NativeStream,'call',side_effect=ValueError('PUBLIC handshake rejection')), \
                    patch.object(child,'kill'):
                with self.assertRaises(pipes.NativePipeStopPending):histories._NativeStream({},Path(sys._base_executable),None)
                self.assertIs(slot.owner.process,child)
                with self.assertRaises(pipes.NativePipeStopPending):histories._NativeStream({},Path(sys._base_executable),None)
                self.assertEqual(launch.call_count,1)
            self.assertEqual(_winapi.WaitForSingleObject(handle,0),_winapi.WAIT_TIMEOUT)
            child.stdin.write(b'PUBLIC exit\n');child.stdin.flush();terminal.wait_process_terminal(child,3)
            slot.retire();self.assertIsNone(slot.owner)
        finally:
            self.finish(child)
            if slot.owner is not None:slot.retire()

    def test_actual_relay_constructor_retains_exact_failed_pipe_without_crypto_claim(self):
        from tests.test_protocol_integrated_profiles import public_protocol_pin
        import _winapi
        key=Keypair();pin=public_protocol_pin()
        child=self.child('import sys;sys.stdin.buffer.readline(32)');handle=child._handle
        leaf=limits.contain(child);self.addCleanup(leaf.close)
        slot=pipes.TRANSPORT_PIPE_INIT;self.assertIsNone(slot.owner)
        try:
            # Actual key/pin shape validation remains. No native handshake or
            # signature verification is claimed by this lifetime-only test.
            with patch.object(relay.subprocess,'Popen',return_value=child) as launch, \
                    patch.object(relay._Pipe,'_send_raw',side_effect=ValueError('PUBLIC transport rejection')), \
                    patch.object(child,'kill'):
                with self.assertRaises(pipes.NativePipeStopPending):relay._Pipe(key,pin,{'mode':'CLIENT'},binary=Path(sys._base_executable))
                self.assertIs(slot.owner.process,child)
                with self.assertRaises(pipes.NativePipeStopPending):relay._Pipe(key,pin,{'mode':'CLIENT'},binary=Path(sys._base_executable))
                self.assertEqual(launch.call_count,1)
            self.assertEqual(_winapi.WaitForSingleObject(handle,0),_winapi.WAIT_TIMEOUT)
            child.stdin.write(b'PUBLIC exit\n');child.stdin.flush();terminal.wait_process_terminal(child,3)
            slot.retire();self.assertIsNone(slot.owner)
        finally:
            self.finish(child)
            if slot.owner is not None:slot.retire()

    def test_partial_server_handler_start_failure_keeps_started_threads_and_child_for_retry(self):
        from tests.test_protocol_integrated_profiles import public_protocol_pin
        key=Keypair();pin=public_protocol_pin();child=self.child('import sys;sys.stdin.buffer.readline(32)')
        leaf=limits.contain(child);self.addCleanup(leaf.close)
        slot=pipes.TRANSPORT_SERVER_INIT;self.assertIsNone(slot.owner)
        original_start=threading.Thread.start;attempts=0;handler=Mock()
        def start(thread):
            nonlocal attempts
            attempts+=1
            if attempts==2:raise RuntimeError('PUBLIC thread creation failure before OS start')
            return original_start(thread)
        ready={'event':'READY','genesis_hash':pin['genesis_hash'],'peer_key':key.pubkey().hex(),'schema':relay.SCHEMA}
        try:
            with patch.object(relay.subprocess,'Popen',return_value=child),patch.object(relay._Pipe,'_send_raw'), \
                    patch.object(relay._Pipe,'_read',return_value=ready),patch.object(threading.Thread,'start',start), \
                    patch.object(child,'kill'):
                with self.assertRaises(pipes.NativePipeStopPending):
                    relay.ProofTransportServer(key,pin,'127.0.0.1',32123,[key.pubkey().hex()],handler,binary=Path(sys._base_executable))
            retained=slot.owner;self.assertIs(retained.process,child);self.assertEqual(len(retained._threads),1)
            self.assertFalse(retained._threads[0].is_alive());handler.assert_not_called()
            self.assertFalse(child.stdin.closed);self.assertFalse(child.stdout.closed)
            child.stdin.write(b'PUBLIC exit\n');child.stdin.flush();terminal.wait_process_terminal(child,3)
            slot.retire();self.assertIsNone(slot.owner);handler.assert_not_called()
        finally:
            self.finish(child)
            if slot.owner is not None:slot.retire()

    def test_failed_protected_relay_after_real_key_handoff_fences_profile_until_kernel_exit(self):
        import _winapi
        from backend import gg_observer_profile as observers,portable_wallet_vault as vault
        from backend import gg_native_process_policy as policy
        from tests.test_durable_node_store import configuration
        from tests.test_protocol_integrated_profiles import public_protocol_pin
        with tempfile.TemporaryDirectory(prefix='gg-protected-pipe-life-') as temporary,ExitStack() as stack:
            root=Path(temporary);stack.enter_context(patch.object(nodes,'ROOT',root/'nodes'))
            stack.enter_context(patch.object(observers,'ROOT',root/'observers'))
            stack.enter_context(vault.session('PUBLIC disposable protected pipe fixture password'))
            owner=nodes.NodeProfile.create('Owner',configuration());profile=None;child=None
            slot=pipes.TRANSPORT_PIPE_INIT
            try:
                pin=public_protocol_pin();profile=observers.ObserverProfile.create_for_protocol('Light',owner,pin,label='Public lifetime test')
                key=profile.native_node_signer()
                source='''import json,struct,sys
size=struct.unpack('>I',sys.stdin.buffer.read(4))[0]
payload=json.loads(sys.stdin.buffer.read(size))
if not isinstance(payload.get('private_key'),str) or not payload['private_key']:raise SystemExit(92)
sys.stdout.buffer.write(b'PUBLIC_KEY_HANDOFF_ACK\\n');sys.stdout.buffer.flush()
sys.stdin.buffer.readline(64)
'''
                child=self.child(source);database=profile._db;lease=profile._lease;key_state=profile._key
                def expired():
                    try:_winapi.TerminateProcess(child._handle,93)
                    except OSError:pass
                timer=threading.Timer(6,expired);timer.daemon=True;timer.start()
                def rejected_read(**options):
                    self.assertEqual(child.stdout.readline(64),b'PUBLIC_KEY_HANDOFF_ACK\n')
                    raise ValueError('PUBLIC handshake rejection after actual private stdin handoff')
                try:
                    with patch.object(relay._Pipe,'_spawn_pipe',return_value=child),patch.object(relay._Pipe,'_read',side_effect=rejected_read),patch.object(child,'kill'):
                        with self.assertRaises(pipes.NativePipeStopPending):
                            relay._Pipe(key,pin,{'mode':'CLIENT'},binary=Path(sys._base_executable),owner=owner,profile=profile)
                        self.assertIs(slot.owner.process,child)
                        self.assertIn(child,policy._groups[owner]._children)
                        self.assertTrue(slot.owner._lease.facts['verified'])
                        with self.assertRaises((pipes.NativePipeStopPending,ValueError)):profile.close()
                        self.assertIs(profile._db,database);self.assertIs(profile._lease,lease)
                        self.assertTrue(profile._key is key_state);self.assertFalse(profile._closed)
                        self.assertEqual(_winapi.WaitForSingleObject(child._handle,0),_winapi.WAIT_TIMEOUT)
                finally:timer.cancel()
                child.stdin.write(b'PUBLIC exit\n');child.stdin.flush();terminal.wait_process_terminal(child,3)
                profile.close()  # Exact failed relay retires before its lease/key journal.
                self.assertIsNone(slot.owner);self.assertIsNone(profile._db);self.assertIsNone(profile._lease)
                self.assertIsNotNone(owner._db);self.assertFalse(owner._closed)
            finally:
                if child is not None:self.finish(child)
                slot.retire()
                if profile is not None:profile.close()
                owner.close()


class ProtectedClosingFixture:
    """Real protected profiles; public floor fixture is NOT an SDK certificate."""
    def setUp(self):
        from backend import gg_observer_profile as observers,gg_consensus_profile as validators
        from backend import gg_financial_account as accounts,portable_wallet_vault as vault
        from tests.test_durable_node_store import configuration
        from tests.test_protocol_integrated_profiles import public_protocol_pin
        self.temp=tempfile.TemporaryDirectory(prefix='gg-close-intent-')
        self.temp._finalizer.detach()  # Cleanup must follow exact child retirement.
        self.stack=ExitStack();self.profiles=[];self.child_process=None;self.child_lease=None
        self.addCleanup(self.cleanup_fixture);root=Path(self.temp.name)
        for module,folder in ((nodes,'nodes'),(observers,'observers'),(validators,'validators'),(accounts,'accounts')):
            self.stack.enter_context(patch.object(module,'ROOT',root/folder))
        self.stack.enter_context(vault.session('PUBLIC disposable close-intent fixture password'))
        self.owner=nodes.NodeProfile.create('Owner',configuration());self.profiles.append(self.owner)
        self.account=accounts.AccountProfile.create('Gov',label='Public governance test wallet');self.profiles.append(self.account)
        self.validator=validators.ValidatorProfile.create_for_protocol('Voter',self.owner,label='Public voter',p2p_port=22101,account=self.account)
        self.profiles.append(self.validator)
        self.validator_pin=public_protocol_pin({**self.validator.public_invite()['body'],'power':'1'})
        self.validator.bind_protocol(self.validator_pin,account=self.account)
        self.pin=public_protocol_pin()
        self.observer=observers.ObserverProfile.create_for_protocol('Replica',self.owner,self.pin,label='Public replica')
        self.profiles.append(self.observer)

    def stop_child(self):
        child=self.child_process
        if child is None:return
        try:
            if not terminal.process_terminal(child):child.kill()
        except OSError:pass
        terminal.wait_process_terminal(child,3)
        if not terminal.process_terminal(child):raise pipes.NativePipeStopPending()
        if self.child_lease is not None:self.child_lease.close();self.child_lease=None
        for stream in (child.stdin,child.stdout):
            if stream is not None:stream.close()
        self.child_process=None

    def cleanup_fixture(self):
        # Failure retains roots/profile objects; it never deletes a live root.
        self.stop_child()
        for profile in reversed(self.profiles):profile.close()
        self.stack.close();self.temp.cleanup()

    def child(self):
        self.stop_child();source='import sys;sys.stdin.buffer.read(1)\n'
        if os.name=='nt':
            process=subprocess.Popen([str(Path(sys._base_executable).resolve()),'-I','-c',source],
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                creationflags=native_start.native_pipe_creation_flags())
        else:
            from backend.gg_posix_native import launch
            wrapper=Path(self.temp.name)/'public-closing-child.py'
            wrapper.write_text('#!'+sys.executable+'\n'+source,encoding='utf-8');wrapper.chmod(0o700)
            process=launch(wrapper,cwd=self.observer.root,env=os.environ.copy())
        self.child_process=process
        self.child_lease=native_policy.contain_owned_native(process,self.owner)
        return process


class ConcreteRPCPolicyController(rpc_transport.OwnedNativeRPC):
    """Declared owned-session policy seam; shared guards/RPC stay inherited."""
    def _owner_stopped(self):return False


class ClosingIntentPolicyTests(ProtectedClosingFixture,unittest.TestCase):
    def test_real_pending_profiles_deny_signer_issuance_and_native_claim_without_losing_leases(self):
        for profile,getter in ((self.owner,self.owner.signers),(self.validator,self.validator.native_signers),(self.observer,self.observer.native_node_signer)):
            with self.subTest(kind=type(profile).__name__):
                slot=pipes._FiniteSlot(3);slot.owners=(profile,);slot._blocked=True;slot.process=process_double()
                database,lease=profile._db,profile._lease
                try:
                    with patch.object(pipes,'_FINITE_SLOTS',(slot,)),patch.object(terminal,'process_terminal',return_value=False), \
                            patch.object(terminal,'wait_process_terminal',side_effect=subprocess.TimeoutExpired('PUBLIC policy child',3)):
                        with self.assertRaises(pipes.NativePipeStopPending):profile.close()
                    self.assertFalse(profile._closed);self.assertIs(profile._db,database);self.assertIs(profile._lease,lease)
                    with self.assertRaises(ValueError):getter()
                    if hasattr(profile,'claim_native_start'):
                        before=dict(profile._body)
                        with self.assertRaises(ValueError):profile.claim_native_start()
                        self.assertTrue(profile._body==before)
                finally:slot.process=None;slot.owners=();slot._blocked=False

    def test_owner_ended_alone_denies_node_signers_while_public_identity_remains_readable(self):
        descriptor=self.owner.descriptor();session=self.owner.session();self.owner.signers()
        with native_policy._registry_lock:native_policy._ended.add(self.owner)
        self.assertFalse(self.owner._closed);self.assertIsNotNone(self.owner._db)
        with self.assertRaisesRegex(ValueError,'GG_NODE_VAULT_CLOSED'):self.owner.signers()
        self.assertEqual(self.owner.descriptor(),descriptor);self.assertEqual(self.owner.session(),session)

    def test_stored_public_certificate_and_anchor_reads_survive_close_intent(self):
        # These public bytes satisfy only the journal's structural floor. No
        # SDK signature/certificate validity is fabricated or asserted here.
        from copy import deepcopy
        from backend.gg_node_store import pack
        for profile,pin in ((self.validator,self.validator_pin),(self.observer,self.pin)):
            with self.subTest(kind=type(profile).__name__):
                if profile is self.validator:profile.claim_native_start()
                packet={'schema':'gg.consensus.proof.v1',**deepcopy(pin),'state':{'height':1,'state_root':'a'*64},
                    'signed_header':{'header':{'height':'2'},'commit':{'block_id':{'hash':'b'*64}}}}
                profile.remember_certificate(packet);before=pack(profile.public_certificate());anchor=profile.anchor()
                profile._native_pipe_closing=True
                self.assertEqual(pack(profile.public_certificate()),before);self.assertEqual(profile.anchor(),anchor)
                self.assertFalse(profile._closed)

    def test_shared_fresh_rpc_proof_and_work_guards_reject_live_pending_profile_before_io(self):
        node=object.__new__(ConcreteRPCPolicyController);node.profile=self.observer
        node._closed=False;node._fault='';node._epoch_stopping=False;node._node={'process':process_double()};node.rpc_port=1
        node._owner_stopped=lambda:False;node._connection=None
        node._unchanged=Mock(side_effect=AssertionError('binary IO after close intent'))
        node._owned=Mock(side_effect=AssertionError('listener IO after close intent'))
        self.observer._native_pipe_closing=True
        self.assertTrue(node._start_cancelled())
        with self.assertRaisesRegex(ValueError,'PROOF_UNAVAILABLE'):node._check_proof_epoch()
        with self.assertRaisesRegex(ValueError,'START_CANCELLED'):node._check_start()
        with self.assertRaisesRegex(ValueError,'OWNER_STOPPED'):node._rpc('broadcast_tx_sync',b'PUBLIC no operation')
        node._unchanged.assert_not_called();node._owned.assert_not_called()

    def test_all_alive_start_fast_paths_deny_pending_profile_before_snapshot_or_spawn(self):
        from backend.gg_consensus_node import OwnedValidator
        from backend.gg_observer_node import OwnedObserver
        from backend.gg_segmented_authority import OwnedSegmentedAuthority
        from backend.gg_financial_authority import OwnedFinancialAuthority
        from backend.gg_protocol_node import OwnedProtocolNode
        from backend.gg_protocol_light import LightProtocolNode
        for cls,profile in ((OwnedValidator,self.validator),(OwnedObserver,self.observer),
                (OwnedSegmentedAuthority,self.validator),(OwnedFinancialAuthority,self.validator),
                (OwnedProtocolNode,self.observer),(LightProtocolNode,self.observer)):
            for boundary in ('pending_profile','owner_ended'):
                with self.subTest(controller=cls.__name__,boundary=boundary):
                    node=object.__new__(cls);node.profile=profile;node.owner=self.owner
                    node._lock=threading.RLock();node._closed=False;node._fault='';node._managed_cancel=None
                    if cls is OwnedProtocolNode:
                        node._start_gate=threading.Lock();node._recovering=False
                    # Session binding alone is the declared policy seam. The
                    # profile/owner flags and all production start guards run.
                    node._owner_stopped=lambda:native_policy.owner_ended(self.owner)
                    if cls is OwnedSegmentedAuthority:node.session=SimpleNamespace(check=Mock())
                    node._alive=Mock(return_value=True)
                    node.snapshot=Mock(side_effect=AssertionError('premature successful start'))
                    profile._native_pipe_closing=boundary=='pending_profile'
                    if boundary=='owner_ended':
                        with native_policy._registry_lock:native_policy._ended.add(self.owner)
                    try:
                        with self.assertRaises(ValueError):node.start()
                        node._alive.assert_not_called();node.snapshot.assert_not_called()
                    finally:
                        profile._native_pipe_closing=False
                        with native_policy._registry_lock:native_policy._ended.discard(self.owner)

    def test_explicit_restart_retires_exact_child_before_resetting_resumable_stop_or_failed_start(self):
        from backend.gg_observer_node import OwnedObserver
        from backend.gg_protocol_node import OwnedProtocolNode
        # Real protected profiles and contained public children. Only the old
        # legacy session graph and authorized next SDK startup are explicit
        # lifecycle seams: this does not fabricate a native READY/certificate.
        for cls,mode in ((OwnedObserver,'normal_stop'),(OwnedObserver,'failed_start'),
                         (OwnedProtocolNode,'request_stop')):
            with self.subTest(controller=cls.__name__,mode=mode):
                process=self.child();node=object.__new__(cls);node.profile=self.observer;node.owner=self.owner
                node._lock=threading.RLock();node._closed=False;node._fault='';node._stop_signal=threading.Event()
                node._node={'process':process,'_ready':None};node._lease=self.child_lease;node._connection=None
                node._monitor_cancel=None;node._epoch_stopping=False;node._managed_cancel=None
                if cls is OwnedProtocolNode:
                    node._start_gate=threading.Lock();node._recovering=False;node._records=OrderedDict()
                node._owner_stopped=lambda:native_policy.owner_ended(self.owner)
                node._check_context=Mock()  # Legacy session graph only.
                node.snapshot=Mock(side_effect=AssertionError('stopped controller returned alive snapshot'))
                attempts=[];retired=[process]
                def next_start():
                    self.assertTrue(terminal.process_terminal(retired[-1]))
                    self.assertIsNone(node._node['process']);self.assertIsNone(node._lease)
                    self.assertFalse(node._stop_signal.is_set());self.assertFalse(self.observer._closed)
                    attempts.append('authorized-start-boundary')
                    if mode=='failed_start' and len(attempts)==1:
                        child=self.child();retired.append(child)
                        node._node={'process':child,'_ready':None};node._lease=self.child_lease
                        node.stop()  # Exact real cleanup used by failed startup.
                        raise ValueError('GG_PUBLIC_STARTUP_RESULT_FAULT')
                    return {'state':'PUBLIC_AUTHORIZED_START_PATH_ONLY'}
                node._launch_native=next_start
                try:
                    if mode=='normal_stop':node.stop()
                    elif mode=='request_stop':node.request_stop()
                    else:
                        node._alive=Mock(return_value=False)
                        with self.assertRaisesRegex(ValueError,'PUBLIC_STARTUP_RESULT_FAULT'):node.start()
                    self.assertTrue(node._stop_signal.is_set())
                    # Controlled alive outcome probes ordering even if the OS
                    # already completed the requested child's termination.
                    node._alive=Mock(return_value=True)
                    result=node.start()
                    self.assertEqual(result,{'state':'PUBLIC_AUTHORIZED_START_PATH_ONLY'})
                    node._alive.assert_not_called();node.snapshot.assert_not_called()
                    self.assertEqual(len(attempts),2 if mode=='failed_start' else 1)
                    self.assertTrue(all(terminal.process_terminal(child) for child in retired))
                finally:
                    node.stop();self.stop_child()

    def test_reservation_rejects_flag_before_claim_then_cleans_proven_no_input_race(self):
        for profile in (self.validator,self.observer):
            with self.subTest(kind=type(profile).__name__):
                process=self.child();before=dict(profile._body);profile._native_pipe_closing=True
                with self.assertRaisesRegex(ValueError,'PROFILE_UNAVAILABLE'):
                    with native_start.NativeStartReservation(profile,process):self.fail('closed-intent claim')
                self.assertTrue(profile._body==before);profile._native_pipe_closing=False
                try:
                    claim=profile.claim_native_start
                    def close_during_durable_claim():
                        fresh=claim()  # Real protected journal commit, no native/proof stub.
                        profile._native_pipe_closing=True
                        return fresh
                    with self.assertRaisesRegex(ValueError,'PROFILE_UNAVAILABLE'):
                        with patch.object(profile,'claim_native_start',side_effect=close_during_durable_claim):
                            with native_start.NativeStartReservation(profile,process) as intent:
                                try:intent.mark_input_started()
                                except ValueError:
                                    self.assertFalse(intent._input_started)
                                    self.stop_child()  # Genuine terminal proof; no pipe byte was written.
                                    raise
                    self.assertFalse(profile._body['native_started']);self.assertTrue(profile._body==before)
                    self.assertFalse((profile.root/'native').exists())
                finally:self.stop_child()

    def test_handoff_linearized_before_close_intent_never_claims_no_input_abort(self):
        process=self.child();profile=self.observer
        with native_start.NativeStartReservation(profile,process) as intent:
            intent.mark_input_started();profile._native_pipe_closing=True
            self.stop_child()
        self.assertTrue(profile._body['native_started'])
        self.assertFalse((profile.root/'native').exists())

    def test_pending_profile_watch_uses_actual_owned_sdk_stop_path(self):
        from backend.gg_protocol_node import OwnedProtocolNode
        process=self.child();node=object.__new__(OwnedProtocolNode)
        node.profile=self.observer;node.owner=self.owner;node._lock=threading.RLock()
        node._closed=False;node._fault='';node._stop_signal=threading.Event()
        node._node={'process':process,'_ready':None};node._lease=self.child_lease;node._connection=None
        node._epoch_stopping=False;node._monitor_cancel=threading.Event()
        self.observer._native_pipe_closing=True
        node._watch_owner(node._monitor_cancel)
        self.assertTrue(terminal.process_terminal(process));self.assertIsNone(node._node['process'])
        self.assertTrue(node._closed);self.assertIsNone(node._lease)
        self.assertIsNotNone(self.observer._db);self.assertFalse(self.observer._closed)
        self.assertFalse(native_policy.owner_ended(self.owner));self.assertFalse(self.owner._closed)


if __name__=='__main__':unittest.main()
