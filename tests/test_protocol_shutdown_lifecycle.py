"""Deterministic shutdown ownership boundaries; no native execution evidence.

The fake processes and threads below model only kill/wait/poll/join outcomes.
No subprocess, listener, cryptographic verification or network is exercised.
Proof-shaped dictionaries are deliberately not accepted certificates: CLOSED
must reject them before disk access or any native verifier construction.
"""
from collections import OrderedDict
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
import subprocess
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from backend import gg_committee_history as histories
from backend import gg_protocol_transport as transport
from backend import gg_protocol_runtime as runtime
from backend import gg_process_termination as termination


class RecordedPipe:
    def __init__(self,events,label):
        self.events=events;self.label=label;self.closed=False

    def close(self):
        self.events.append(self.label);self.closed=True


class OwnedProcessOutcome:
    """An explicit unit double; never an OS process or native crypto seam."""
    def __init__(self,*,kill_exit=-9,kill_error=False,wait_error=None,returncode=None):
        self.returncode=returncode;self.kill_exit=kill_exit;self.kill_error=kill_error
        self.wait_error=wait_error;self.events=[];self.wait_timeouts=[]
        self.stdin=RecordedPipe(self.events,'stdin-close')
        self.stdout=RecordedPipe(self.events,'stdout-close')

    def poll(self):
        self.events.append('poll');return self.returncode

    def kill(self):
        self.events.append('kill')
        if self.kill_error:raise OSError('PUBLIC FAKE OWNED STOP FAILURE')
        self.returncode=self.kill_exit

    def wait(self,timeout=None):
        self.events.append('wait');self.wait_timeouts.append(timeout)
        if self.wait_error is not None:raise self.wait_error
        # A None result deliberately models an untrustworthy/incomplete wait
        # seam: close must independently consult the exact process's poll.
        return self.returncode


class ThreadOutcome:
    def __init__(self,*,alive_after_join):
        self.alive_after_join=alive_after_join;self.join_timeouts=[]

    def join(self,timeout=None):self.join_timeouts.append(timeout)
    def is_alive(self):return self.alive_after_join


def bare_stream(process):
    stream=histories._NativeStream.__new__(histories._NativeStream)
    stream.process=process;stream.closed=False;stream._lock=threading.RLock()
    return stream


def bare_pipe(process):
    pipe=transport._Pipe.__new__(transport._Pipe)
    pipe.process=process;pipe._closed=False;pipe._write_lock=threading.RLock()
    return pipe


def bare_server(process,threads):
    server=transport.ProofTransportServer.__new__(transport.ProofTransportServer)
    server.process=process;server._closed=False;server._stop=threading.Event()
    server._write_lock=threading.RLock();server._threads=list(threads)
    return server


def bare_closed_history():
    subject=histories.CommitteeHistory.__new__(histories.CommitteeHistory)
    subject._lock=threading.RLock();subject.closed=True;subject.epoch=1
    subject._historical=None;subject._historical_epoch=0
    subject.pin={'genesis_hash':'a'*64};subject.binary=Path('PUBLIC-unit-binary');subject.stamp=None
    subject._stream=SimpleNamespace(call=Mock(side_effect=AssertionError('CLOSED main stream called')))
    subject._disk_lock=Mock(side_effect=AssertionError('CLOSED touched disk lock'))
    subject._sync=Mock(side_effect=AssertionError('CLOSED synchronized history'))
    subject._append=Mock(side_effect=AssertionError('CLOSED appended record'))
    subject._read=Mock(side_effect=AssertionError('CLOSED read record'))
    return subject


class FakeProcessKernelAdapter:
    """Explicitly adapt only this file's fake OS outcomes, never real Popen."""
    def setUp(self):
        real_wait=termination.wait_process_terminal;real_terminal=termination.process_terminal
        def wait(child,timeout):
            return child.wait(timeout=timeout) if type(child) is OwnedProcessOutcome else real_wait(child,timeout)
        def terminal(child):
            return child.poll() is not None if type(child) is OwnedProcessOutcome else real_terminal(child)
        for name,adapter in (('wait_process_terminal',wait),('process_terminal',terminal)):
            selected=patch.object(termination,name,side_effect=adapter);selected.start();self.addCleanup(selected.stop)


class ClosedCommitteeHistoryTests(FakeProcessKernelAdapter,unittest.TestCase):
    def test_closed_methods_reject_before_disk_sync_or_native_creation(self):
        for name,args in (('refresh',()),('append',({},)),('transition',(1,)),('verify',({},))):
            with self.subTest(method=name):
                subject=bare_closed_history()
                with patch.object(histories,'_NativeStream',side_effect=AssertionError('CLOSED spawned child')) as spawn:
                    with self.assertRaisesRegex(ValueError,'^GG_COMMITTEE_HISTORY_CLOSED$'):
                        getattr(subject,name)(*args)
                subject._disk_lock.assert_not_called();subject._sync.assert_not_called()
                subject._append.assert_not_called();subject._read.assert_not_called()
                subject._stream.call.assert_not_called();spawn.assert_not_called()

    def test_closed_historical_certificate_cannot_resurrect_detached_verifier(self):
        subject=bare_closed_history()
        # Allow the legacy path to proceed far enough that the old code would
        # try _NativeStream at needed=0 < history.epoch=1. No proof is verified.
        subject._disk_lock=Mock(return_value=nullcontext());subject._sync=Mock()
        old_packet={'state':{'protocol':{'committee':{'epoch':'0'},'pending_committee':None}}}
        with patch.object(histories,'_NativeStream',side_effect=AssertionError('HISTORICAL CHILD RESURRECTED')) as spawn:
            with self.assertRaisesRegex(ValueError,'^GG_COMMITTEE_HISTORY_CLOSED$'):
                subject.verify(old_packet)
        spawn.assert_not_called();subject._disk_lock.assert_not_called();subject._sync.assert_not_called()
        self.assertIsNone(subject._historical)

    def test_closed_guard_runs_after_waiting_for_history_lock(self):
        for name,args in (('refresh',()),('append',({},)),('transition',(1,)),('verify',({},))):
            with self.subTest(method=name):
                subject=bare_closed_history();subject.closed=False
                lock=threading.RLock();attempted=threading.Event();errors=[]

                class Gate:
                    def __enter__(self):attempted.set();lock.acquire();return self
                    def __exit__(self,*unused):lock.release()

                subject._lock=Gate()
                def operate_after_gate():
                    try:getattr(subject,name)(*args)
                    except BaseException as error:errors.append(error)

                worker=threading.Thread(target=operate_after_gate,name='PUBLIC-unit-history-lock',daemon=True)
                with lock:
                    worker.start()
                    try:self.assertTrue(attempted.wait(1),'worker did not attempt history lock')
                    finally:subject.closed=True
                worker.join(2)
                self.assertFalse(worker.is_alive(),'bounded unit worker did not terminate')
                self.assertEqual(len(errors),1);self.assertIsInstance(errors[0],ValueError)
                self.assertEqual(str(errors[0]),'GG_COMMITTEE_HISTORY_CLOSED')
                subject._disk_lock.assert_not_called();subject._sync.assert_not_called()

    def test_pending_cached_history_is_not_removed_or_replaced(self):
        binary=Path('PUBLIC-unit-binary');pin={'genesis_hash':'a'*64};stamp=None
        key=(str(binary.resolve()),stamp,pin['genesis_hash'])
        subject=SimpleNamespace(closed=True,close=Mock(side_effect=ValueError('GG_COMMITTEE_VERIFIER_STOP_PENDING')))
        cache=OrderedDict([(key,subject)])
        with patch.object(histories,'_CACHE',cache),patch.object(histories,'CommitteeHistory',side_effect=AssertionError('REPLACEMENT SPAWN')) as create:
            with self.assertRaisesRegex(ValueError,'^GG_COMMITTEE_VERIFIER_STOP_PENDING$'):
                histories.history(pin,binary,stamp)
        self.assertIs(cache[key],subject);self.assertEqual(len(cache),1);create.assert_not_called()

    def test_close_all_failure_preserves_exact_cached_owner(self):
        subject=SimpleNamespace(close=Mock(side_effect=ValueError('GG_COMMITTEE_VERIFIER_STOP_PENDING')))
        cache=OrderedDict([('PUBLIC-owner',subject)])
        with patch.object(histories,'_CACHE',cache):
            with self.assertRaisesRegex(ValueError,'^GG_COMMITTEE_VERIFIER_STOP_PENDING$'):
                histories.close_all()
        self.assertIs(cache['PUBLIC-owner'],subject);subject.close.assert_called_once_with()

    def test_pending_oldest_blocks_all_new_helpers_until_same_owner_is_terminal(self):
        binary=Path('PUBLIC-unit-binary');stamp=None
        def key(tag):return (str(binary.resolve()),stamp,tag*64)
        def context(process):
            value=histories.CommitteeHistory.__new__(histories.CommitteeHistory)
            value._lock=threading.RLock();value.closed=False
            value._stream=bare_stream(process);value._historical=None
            return value
        # These are explicitly fake OS outcomes. Use the real history/stream
        # close paths to prove exact ownership retention, not a close() stub.
        oldest_process=OwnedProcessOutcome(kill_exit=None)
        oldest=context(oldest_process);newer=context(OwnedProcessOutcome())
        replacement=context(OwnedProcessOutcome())
        cache=OrderedDict([(key('a'),oldest),(key('b'),newer)])
        def construct(pin,selected_binary,selected_stamp):
            self.assertEqual((selected_binary,selected_stamp),(binary,stamp))
            self.assertEqual(pin,{'genesis_hash':'e'*64})
            self.assertEqual(list(cache),[key('b')])
            self.assertIs(cache[key('b')],newer)
            self.assertIsNotNone(oldest_process.returncode)
            self.assertTrue(oldest_process.stdin.closed);self.assertTrue(oldest_process.stdout.closed)
            return replacement
        with patch.object(histories,'_CACHE',cache),patch.object(histories,'CommitteeHistory',side_effect=construct) as create:
            for tag in ('c','d','e'):
                with self.subTest(pending_new_key=tag):
                    with self.assertRaisesRegex(ValueError,'^GG_COMMITTEE_VERIFIER_STOP_PENDING$'):
                        histories.history({'genesis_hash':tag*64},binary,stamp)
                    create.assert_not_called();self.assertEqual(len(cache),2)
                    self.assertEqual(list(cache),[key('a'),key('b')])
                    self.assertIs(cache[key('a')],oldest);self.assertIs(cache[key('b')],newer)
                    self.assertIs(oldest._stream.process,oldest_process)
                    self.assertIsNone(oldest_process.returncode)
                    self.assertFalse(oldest_process.stdin.closed);self.assertFalse(oldest_process.stdout.closed)
                    self.assertEqual(newer._stream.process.wait_timeouts,[])
            self.assertEqual(oldest_process.wait_timeouts,[1,1,1])
            # Simulate this SAME owned child becoming terminal. An explicit
            # retry can now close its pipes, remove it and allocate ONE helper.
            oldest_process.returncode=-9
            result=histories.history({'genesis_hash':'e'*64},binary,stamp)
            self.assertIs(result,replacement);self.assertEqual(list(cache),[key('b'),key('e')])
            self.assertIs(cache[key('b')],newer);self.assertIs(cache[key('e')],replacement)
            self.assertNotIn(key('a'),cache);self.assertEqual(oldest_process.wait_timeouts,[1,1,1,1])
            create.assert_called_once_with({'genesis_hash':'e'*64},binary,stamp)
            self.assertIs(histories.history({'genesis_hash':'e'*64},binary,stamp),replacement)
            self.assertEqual(create.call_count,1);self.assertEqual(len(cache),2)


class ExactOwnedHelperStopTests(FakeProcessKernelAdapter,unittest.TestCase):
    def helpers(self,process_factory):
        for kind,maker,error in (
                ('verifier',bare_stream,'GG_COMMITTEE_VERIFIER_STOP_PENDING'),
                ('transport',bare_pipe,'GG_PROTOCOL_RELAY_STOP_PENDING')):
            process=process_factory();yield kind,maker(process),process,error

    def assert_pending_retained(self,helper,process,error):
        with self.assertRaisesRegex(ValueError,'^'+error+'$'):helper.close()
        self.assertIs(helper.process,process)
        self.assertIsNone(process.returncode)
        self.assertFalse(process.stdin.closed);self.assertFalse(process.stdout.closed)
        self.assertEqual(process.wait_timeouts,[1])
        self.assertEqual(process.events[-1],'poll')
        if type(helper) is histories._NativeStream:
            self.assertTrue(helper.closed)
            with self.assertRaisesRegex(ValueError,'^GG_COMMITTEE_VERIFIER_UNAVAILABLE$'):
                helper.call('verify',proof={})
        else:self.assertTrue(helper._closed);self.assertFalse(helper.alive())

    def test_close_requires_fresh_poll_even_when_wait_returns_without_exception(self):
        for kind,helper,process,error in self.helpers(lambda:OwnedProcessOutcome(kill_exit=None)):
            with self.subTest(kind=kind):self.assert_pending_retained(helper,process,error)

    def test_failed_kill_with_live_child_is_pending_and_retains_ownership(self):
        for kind,helper,process,error in self.helpers(lambda:OwnedProcessOutcome(kill_error=True)):
            with self.subTest(kind=kind):
                # _NativeStream's existing bounded try skips wait after kill
                # raises. _Pipe.request_stop catches that error before wait1.
                if kind=='verifier':
                    with self.assertRaisesRegex(ValueError,'^'+error+'$'):helper.close()
                    self.assertIs(helper.process,process);self.assertTrue(helper.closed)
                    self.assertEqual(process.wait_timeouts,[])
                    self.assertFalse(process.stdin.closed);self.assertFalse(process.stdout.closed)
                    self.assertEqual(process.events[-1],'poll')
                else:self.assert_pending_retained(helper,process,error)

    def test_wait_timeout_with_live_child_is_pending(self):
        def process():return OwnedProcessOutcome(kill_exit=None,wait_error=subprocess.TimeoutExpired('PUBLIC-unit-child',1))
        for kind,helper,child,error in self.helpers(process):
            with self.subTest(kind=kind):self.assert_pending_retained(helper,child,error)

    def test_terminal_exact_child_closes_pipes_after_fresh_poll(self):
        for kind,helper,process,error in self.helpers(OwnedProcessOutcome):
            with self.subTest(kind=kind):
                helper.close()
                self.assertIs(helper.process,process);self.assertEqual(process.returncode,-9)
                self.assertEqual(process.wait_timeouts,[1])
                self.assertEqual(process.events[-4:],['wait','poll','stdin-close','stdout-close'])
                self.assertTrue(process.stdin.closed);self.assertTrue(process.stdout.closed)

    def test_already_terminal_child_is_not_killed(self):
        for kind,helper,process,error in self.helpers(lambda:OwnedProcessOutcome(returncode=0,kill_error=True)):
            with self.subTest(kind=kind):
                helper.close();self.assertNotIn('kill',process.events)
                self.assertEqual(process.returncode,0);self.assertEqual(process.wait_timeouts,[1])
                self.assertTrue(process.stdin.closed);self.assertTrue(process.stdout.closed)

    def test_wait_error_does_not_hide_confirmed_terminal_exit(self):
        for kind,helper,process,error in self.helpers(lambda:OwnedProcessOutcome(wait_error=OSError('PUBLIC wait raced exit'))):
            with self.subTest(kind=kind):
                helper.close();self.assertEqual(process.returncode,-9)
                self.assertEqual(process.wait_timeouts,[1])
                self.assertEqual(process.events[-3:],['poll','stdin-close','stdout-close'])


class RelayHandlerStopTests(FakeProcessKernelAdapter,unittest.TestCase):
    def test_live_handler_is_pending_even_when_transport_process_is_terminal(self):
        pending=ThreadOutcome(alive_after_join=True);retired=ThreadOutcome(alive_after_join=False)
        process=OwnedProcessOutcome();server=bare_server(process,[pending,retired])
        with self.assertRaisesRegex(ValueError,'^GG_PROTOCOL_RELAY_STOP_PENDING$'):server.close()
        self.assertTrue(server._stop.is_set());self.assertTrue(server._closed)
        self.assertEqual(pending.join_timeouts,[2]);self.assertEqual(retired.join_timeouts,[2])
        self.assertEqual(process.returncode,-9);self.assertIs(server.process,process)
        self.assertIs(server._threads[0],pending);self.assertIs(server._threads[1],retired)
        self.assertEqual(process.wait_timeouts,[1])

    def test_all_retired_handlers_and_terminal_process_close_successfully(self):
        handlers=[ThreadOutcome(alive_after_join=False) for unused in range(3)]
        process=OwnedProcessOutcome();server=bare_server(process,handlers)
        server.close()
        self.assertTrue(server._stop.is_set());self.assertEqual(process.returncode,-9)
        self.assertTrue(all(item.join_timeouts==[2] for item in handlers))
        self.assertTrue(process.stdin.closed);self.assertTrue(process.stdout.closed)

    def test_current_callback_thread_is_not_joined_or_reported_as_external_pending(self):
        retired=ThreadOutcome(alive_after_join=False)
        server=bare_server(OwnedProcessOutcome(),[threading.current_thread(),retired])
        server.close();self.assertEqual(retired.join_timeouts,[2])
        self.assertEqual(server.process.returncode,-9)

    def test_terminal_handlers_cannot_hide_live_native_transport(self):
        retired=ThreadOutcome(alive_after_join=False)
        process=OwnedProcessOutcome(kill_exit=None);server=bare_server(process,[retired])
        with self.assertRaisesRegex(ValueError,'^GG_PROTOCOL_RELAY_STOP_PENDING$'):server.close()
        self.assertEqual(retired.join_timeouts,[2]);self.assertIs(server.process,process)
        self.assertEqual(process.wait_timeouts,[1]);self.assertIsNone(process.returncode)
        self.assertFalse(process.stdin.closed);self.assertFalse(process.stdout.closed)


class ObservedCommandLock:
    """Observe a real acquisition attempt without a timing-based sleep."""
    def __init__(self):self.lock=threading.RLock();self.attempted=threading.Event()
    def acquire(self,*args,**kwargs):self.attempted.set();return self.lock.acquire(*args,**kwargs)
    def release(self):self.lock.release()


def relay_controller():
    controller=runtime.ProtocolRuntime()
    node=SimpleNamespace(request_stop=Mock(),close=Mock());session=object()
    controller.node=node;controller._relay_session=session
    return controller,node,session


class RuntimeRelayLifecycleTests(unittest.TestCase):
    """Real controller methods; fake effects only, no process or certificate."""
    def test_cancel_releases_contended_callback_without_command_or_view_lock(self):
        controller,node,session=relay_controller();gate=ObservedCommandLock();controller._control=gate
        errors=[];effects=[];done=threading.Event()
        def callback():
            try:
                with controller._relay_command_lock(node,session):effects.append('UNEXPECTED EFFECT')
            except BaseException as error:errors.append(error)
            finally:done.set()
        worker=threading.Thread(target=callback,name='PUBLIC-unit-relay-cancel',daemon=True)
        try:
            with gate.lock,controller._view_lock:
                worker.start();self.assertTrue(gate.attempted.wait(1))
                controller.request_stop()
                self.assertTrue(done.wait(2),'cancelled callback required a command/view lock held by stop')
        finally:
            controller._cancel.set()
            if worker.ident is not None:worker.join(2)
        self.assertFalse(worker.is_alive());self.assertEqual(effects,[])
        self.assertEqual(len(errors),1);self.assertIsInstance(errors[0],ValueError)
        self.assertEqual(str(errors[0]),'GG_PROTOCOL_RELAY_TARGET_STOPPED')

    def test_target_is_rechecked_after_acquire_and_lock_is_released_on_rejection(self):
        for change in ('cancel','session','node'):
            with self.subTest(change=change):
                controller,node,session=relay_controller();effects=[]
                def acquired(**kwargs):
                    if change=='cancel':controller._cancel.set()
                    elif change=='session':controller._relay_session=object()
                    else:controller.node=object()
                    return True
                acquire=Mock(side_effect=acquired);release=Mock()
                controller._control=SimpleNamespace(acquire=acquire,release=release)
                with self.assertRaisesRegex(ValueError,'^GG_PROTOCOL_RELAY_TARGET_STOPPED$'):
                    with controller._relay_command_lock(node,session):effects.append('UNEXPECTED EFFECT')
                self.assertEqual(effects,[]);acquire.assert_called_once_with(timeout=.05)
                release.assert_called_once_with()

    def test_exception_in_live_callback_releases_command_lock_once(self):
        controller,node,session=relay_controller();acquire=Mock(return_value=True);release=Mock()
        controller._control=SimpleNamespace(acquire=acquire,release=release)
        with self.assertRaisesRegex(ValueError,'^GG_PUBLIC_UNIT_EFFECT_FAILED$'):
            with controller._relay_command_lock(node,session):raise ValueError('GG_PUBLIC_UNIT_EFFECT_FAILED')
        acquire.assert_called_once_with(timeout=.05);release.assert_called_once_with()

    def test_stop_pending_retains_exact_relay_and_journals_until_explicit_retry(self):
        controller,node,session=relay_controller();owner=SimpleNamespace(close=Mock())
        producer=SimpleNamespace(close=Mock());book=SimpleNamespace(close=Mock());inbox=object()
        relay=SimpleNamespace(request_stop=Mock(),close=Mock(side_effect=[ValueError('GG_PROTOCOL_RELAY_STOP_PENDING'),None]))
        controller.owner=owner;controller.producer=producer;controller.pools['PUBLIC-pool']=book
        controller._relay=relay;controller._relay_policy={'accept_accounts':True};controller._inbox=inbox
        with self.assertRaisesRegex(ValueError,'^GG_PROTOCOL_RELAY_STOP_PENDING$'):controller.stop_node()
        self.assertIs(controller._relay,relay);self.assertIs(controller.node,node);self.assertTrue(controller.active)
        self.assertIs(controller.owner,owner);self.assertIs(controller.producer,producer)
        self.assertIs(controller.pools['PUBLIC-pool'],book);self.assertIs(controller._inbox,inbox)
        self.assertIsNone(controller._relay_session);self.assertIsNone(controller._relay_policy)
        self.assertTrue(controller._cancel.is_set());node.close.assert_not_called()
        producer.close.assert_not_called();book.close.assert_not_called();owner.close.assert_not_called()
        relay.close.assert_called_once_with()
        # An explicit second owner action retries the SAME retained relay. This
        # is not an automatic close_all repetition or an ignored first failure.
        controller.stop_node()
        self.assertIsNone(controller._relay);self.assertIsNone(controller.node);self.assertFalse(controller.active)
        self.assertIsNone(controller.producer);self.assertEqual(controller.pools,{})
        self.assertEqual(relay.close.call_count,2);node.close.assert_called_once_with()
        producer.close.assert_called_once_with();book.close.assert_called_once_with()
        owner.close.assert_not_called()

    def test_stop_can_join_callback_while_caller_retains_command_and_view_locks(self):
        controller,node,session=relay_controller();gate=ObservedCommandLock();controller._control=gate
        errors=[];effects=[]
        def callback():
            try:
                with controller._relay_command_lock(node,session):effects.append('UNEXPECTED EFFECT')
            except BaseException as error:errors.append(error)
        worker=threading.Thread(target=callback,name='PUBLIC-unit-stop-join',daemon=True)
        def close_relay():
            worker.join(1)
            if worker.is_alive():raise ValueError('GG_PROTOCOL_RELAY_STOP_PENDING')
        relay=SimpleNamespace(request_stop=Mock(),close=Mock(side_effect=close_relay));controller._relay=relay
        try:
            with gate.lock,controller._view_lock:
                worker.start();self.assertTrue(gate.attempted.wait(1));controller.stop_node()
        finally:
            controller._cancel.set()
            if worker.ident is not None:worker.join(2)
        self.assertFalse(worker.is_alive());self.assertEqual(effects,[])
        self.assertEqual(len(errors),1);self.assertIsInstance(errors[0],ValueError)
        self.assertEqual(str(errors[0]),'GG_PROTOCOL_RELAY_TARGET_STOPPED')
        self.assertIsNone(controller._relay);self.assertIsNone(controller.node)
        relay.close.assert_called_once_with();node.close.assert_called_once_with()


def public_snapshot_source(tag,*,role='VALIDATOR'):
    """Public config-only seam: no proof or native execution is represented."""
    pin={'genesis_hash':tag*64,'genesis':{'chain_id':'PUBLIC-chain-'+tag,
         'protocol':{'environment':'TESTNET'},'financial_dag':{'network_id':'PUBLIC-network-'+tag}}}
    owner=SimpleNamespace(name='PUBLIC-owner-'+tag,snapshot=lambda:{'state':'READY','canonical_finality':False},
        descriptor=lambda:{'label':'PUBLIC-owner-label-'+tag,'public_keys':[tag*64]})
    node=SimpleNamespace(anchor=pin,node_key=tag*64,profile=SimpleNamespace(name='PUBLIC-native-'+tag),
        role=role,settings={'peers':[{'id':'PUBLIC-peer-'+tag}]},_alive=lambda:True)
    return node,owner


def public_account_source(pin,address):
    # Public source-selection seam only; this creates no signature or receipt.
    return SimpleNamespace(anchor=lambda:deepcopy(pin),public_address=lambda:address,
        journal_observation=lambda:{'profile':'PUBLIC-unit-journal','address':address,
            'signed_batches_exact':'0','journal':None})


class RuntimeSnapshotIdentityTests(unittest.TestCase):
    def controller(self):
        controller=runtime.ProtocolRuntime();node,owner=public_snapshot_source('a')
        controller.node=node;controller.owner=owner
        return controller,node,owner

    def test_waiting_snapshot_has_public_identity_and_only_matching_sorted_account_sources(self):
        controller,node,owner=self.controller();foreign,_=public_snapshot_source('b')
        controller.accounts={'PUBLIC-z':public_account_source(node.anchor,'z'*64),
            'PUBLIC-unbound':public_account_source(None,'u'*64),
            'PUBLIC-foreign':public_account_source(foreign.anchor,'f'*64),
            'PUBLIC-a':public_account_source(deepcopy(node.anchor),'c'*64)}
        view=controller.snapshot();network=view['protocol_network']
        self.assertEqual((view['chain_id'],view['genesis_hash'],view['network_id'],view['node_key']),
            ('PUBLIC-chain-a','a'*64,'PUBLIC-network-a','a'*64))
        self.assertEqual(view['environment'],'TESTNET');self.assertEqual(view['state'],'WAITING_FOR_CERTIFICATE')
        self.assertEqual(network['source_profile'],owner.name);self.assertEqual(network['native_profile'],node.profile.name)
        self.assertEqual(network['account_sources'],[{'profile':'PUBLIC-a','address':'c'*64},{'profile':'PUBLIC-z','address':'z'*64}])
        self.assertEqual(view['connection_state'],'UNOBSERVED');self.assertEqual(view['peers'],[])
        self.assertFalse(view['dag_proofs']['canonical_finality']);self.assertIsNone(view['dag_proofs']['certificate_height'])
        self.assertEqual(view['own_financial_accounts'],[]);self.assertIsNone(view.get('state_root'))
        self.assertFalse(network['operator_start']['startup_state_is_execution_receipt'])
        view['protocol_network']['account_sources'][0]['address']='PUBLIC-mutated-return-value'
        self.assertEqual(controller.snapshot()['protocol_network']['account_sources'][0]['address'],'c'*64)

    def test_snapshot_keeps_one_node_owner_and_graph_identity_if_live_pointer_retargets(self):
        controller,node,owner=self.controller();replacement,replacement_owner=public_snapshot_source('b',role='REPLICA')
        controller.accounts={'PUBLIC-a':public_account_source(node.anchor,'c'*64),
                             'PUBLIC-b':public_account_source(replacement.anchor,'d'*64)}
        controller._view={'state':'READY','state_root':'e'*64,'certificate_height':5,'producers':[],
            'connection_state':'UNOBSERVED','network_contact_at':None}
        def leaf(anchor,identifier):
            return {'genesis_hash':anchor,'hash':identifier,'certificate_height':5,'global_index':'1',
                'producer_key':'f'*64,'rank':'1','sequence':'1','worker_key':'c'*64,'work_hash':'d'*64,
                'transactions':'0','applied':'0','rejected':'0','parents':[]}
        controller._proven_blocks={'a'*64:leaf(node.anchor['genesis_hash'],'a'*64),
                                  'b'*64:leaf(replacement.anchor['genesis_hash'],'b'*64)}
        def retarget():controller.node=replacement;controller.owner=replacement_owner;return True
        node._alive=retarget
        # The synthetic selected rows only test source selection. They are not
        # passed to or counted as successful cryptographic proof verification.
        view=controller.snapshot();network=view['protocol_network']
        self.assertIs(controller.node,replacement);self.assertIs(controller.owner,replacement_owner)
        self.assertEqual(view['node_key'],node.node_key);self.assertEqual(view['network_id'],'PUBLIC-network-a')
        self.assertEqual(network['node_role'],'VALIDATOR');self.assertEqual(network['native_profile'],'PUBLIC-native-a')
        self.assertEqual(network['source_profile'],owner.name)
        self.assertEqual(network['account_sources'],[{'profile':'PUBLIC-a','address':'c'*64}])
        self.assertEqual([row['hash'] for row in view['dag_proofs']['proven_blocks']],['a'*64])
        self.assertEqual([row['hash'] for row in view['block_graph']['blocks']],['a'*64])
        self.assertEqual([row['address'] for row in network['own_journals']['accounts']],['c'*64])

    def test_account_sources_and_journals_use_one_selection_when_mapping_changes(self):
        controller,node,owner=self.controller();foreign,_=public_snapshot_source('b')
        selected=public_account_source(node.anchor,'c'*64)
        controller.accounts={'PUBLIC-original':selected}
        def retarget_accounts():
            controller.accounts={'PUBLIC-replacement':public_account_source(foreign.anchor,'d'*64)}
            return 'c'*64
        selected.public_address=retarget_accounts
        view=controller.snapshot()['protocol_network']
        self.assertEqual(set(controller.accounts),{'PUBLIC-replacement'})
        self.assertEqual(view['account_sources'],[{'profile':'PUBLIC-original','address':'c'*64}])
        self.assertEqual([row['address'] for row in view['own_journals']['accounts']],['c'*64])

    def test_snapshot_never_waits_for_command_lock_held_by_another_thread(self):
        controller,node,owner=self.controller();done=threading.Event();errors=[];views=[]
        def observe():
            try:views.append(controller.snapshot())
            except BaseException as error:errors.append(error)
            finally:done.set()
        worker=threading.Thread(target=observe,name='PUBLIC-unit-independent-snapshot',daemon=True)
        try:
            with controller._control:
                worker.start()
                self.assertTrue(done.wait(2),'snapshot waited for command lock and could invert view-lock ordering')
        finally:
            if worker.ident is not None:worker.join(2)
        self.assertFalse(worker.is_alive());self.assertEqual(errors,[]);self.assertEqual(len(views),1)
        self.assertEqual(views[0]['protocol_network']['native_profile'],node.profile.name)


class RuntimeSnapshotServiceReferenceTests(unittest.TestCase):
    def test_each_service_reference_is_captured_once_before_a_concurrent_clear(self):
        # This models a precise scheduling point, without sleeps or a fake
        # certificate. The first attribute read returns its actual old object
        # and clears the shared runtime field before the next statement.
        fields=('_relay','_relay_policy','_inbox','_mine_thread')

        class ClearOnFirstRead(runtime.ProtocolRuntime):
            def __getattribute__(self,name):
                value=super().__getattribute__(name)
                if name in fields:
                    data=object.__getattribute__(self,'__dict__')
                    if data.get('_clear_on_first_read')==name:
                        object.__setattr__(self,name,None)
                        object.__setattr__(self,'_clear_on_first_read',None)
                        data['_cleared_reads'].append(name)
                return value

        for field in fields:
            with self.subTest(field=field):
                controller=ClearOnFirstRead();node,owner=public_snapshot_source('a')
                controller.node=node;controller.owner=owner
                peers=[{'peer_key':'PUBLIC-unit-peer','last_request_at':0}]
                controller._relay=SimpleNamespace(alive=lambda:True,peers=lambda:deepcopy(peers))
                controller._relay_policy={'accept_accounts':True}
                controller._inbox=SimpleNamespace(snapshot=lambda:{'state':'PUBLIC-unit-inbox','documents':0})
                controller._mine_thread=SimpleNamespace(is_alive=lambda:True)
                controller._cleared_reads=[];controller._clear_on_first_read=field

                view=controller.snapshot();network=view['protocol_network']
                self.assertEqual(controller._cleared_reads,[field])
                self.assertIsNone(getattr(controller,field))
                self.assertTrue(network['worker_active'])
                self.assertEqual(network['receiver_inbox'],{'state':'PUBLIC-unit-inbox','documents':0})
                self.assertEqual(network['proof_relay'],{'active':True,'accounts_enabled':True,'peers':peers,'resources':None})
                self.assertEqual(view['state'],'WAITING_FOR_CERTIFICATE')
                self.assertFalse(view['dag_proofs']['canonical_finality'])
                self.assertIsNone(view.get('state_root'));self.assertEqual(view['own_financial_accounts'],[])

                # The next observation sees the cleared pointer. References
                # are local to one read, never a service lifetime extension.
                next_network=controller.snapshot()['protocol_network']
                if field=='_relay':
                    self.assertEqual(next_network['proof_relay'],{'active':False,'accounts_enabled':False,'peers':[],'resources':None})
                elif field=='_relay_policy':self.assertFalse(next_network['proof_relay']['accounts_enabled'])
                elif field=='_inbox':self.assertIsNone(next_network['receiver_inbox'])
                else:self.assertFalse(next_network['worker_active'])


if __name__=='__main__':unittest.main()
