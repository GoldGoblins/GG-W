"""Codec resource/lifecycle unit seams, not native/kernel acceptance evidence.

Readiness, processes and kernel leases below are explicitly simulated. The
separate real protected SERVER restore/SDK/relay case supplies actual acceptance.
No production gate is patched out to authorize an unbound codec operation.
"""
from copy import deepcopy
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from backend import gg_native_resources as resources,gg_protocol_runtime as runtime
from backend import gg_lossless_wire as wire
from tests.test_native_resources import server


class CodecProcessFixture:
    def __init__(self):self.returncode=None;self.stdin=None;self.stdout=None
    def poll(self):return self.returncode
    def kill(self):self.returncode=0
    def terminate(self):self.returncode=0


class CodecPipeFixture:
    def __init__(self,node,profile,peer):
        self._resources=profile;self._protected_owners=(node.owner,node.profile)
        self.process=CodecProcessFixture();self._lease=SimpleNamespace(facts={'verified':True})
        self.ready={'resources':profile.ready(),'local_limits':profile.transport(),'limits':peer.transport()}
        self._closed=False;self._resource_retired=False;self._threads=[];self.pending_close=False
    def alive(self):return not self._closed and self.process.poll() is None
    def resource_observation(self):return resources.pipe_observation(self)
    def request_stop(self):self._closed=True;self.process.kill()
    def close(self):
        self.request_stop()
        if self.pending_close:raise ValueError('GG_PROTOCOL_RELAY_STOP_PENDING')
        self._lease=None;self._protected_owners=();self._resource_retired=True


def attest_codec_fixture(controller,node,*,client=False,profile=resources.LOW,peer=resources.LOW,owner=None,session=None,bind=True):
    """Attach an explicit unit-only ACK/kernel seam, then use real binding code."""
    # __new__ nodes must carry the ordinary constructor's lifecycle state so
    # the real process_ready/_start_cancelled guards precede codec callbacks.
    node._closed=False;node._recovering=False;node._epoch_stopping=False
    node._start_gate=threading.Lock();node._stop_signal=threading.Event()
    node.owner=owner if owner is not None else SimpleNamespace(_closed=False,_failed=False,_lease=object())
    controller.owner=node.owner
    if not hasattr(node,'profile'):node.profile=SimpleNamespace()
    for name,value in (('_closed',False),('_failed',False),('_lease',object())):
        if not hasattr(node.profile,name):setattr(node.profile,name,value)
    node.settings={} if profile.mode=='LOW' else {'resources':profile.wire()}
    node._native_resource_attempt=profile
    node._check_start=getattr(node,'_check_start',lambda:None)
    node._owner_stopped=lambda:node.owner._closed or node.owner._failed
    pipe=CodecPipeFixture(node,profile,peer)
    process=pipe.process if client else CodecProcessFixture()
    node._lease=None if client else SimpleNamespace(facts={'verified':True})
    node._node={'process':process,'_ready':{'process':process,'resources':profile.ready(),'sdk_rates':profile.sdk_rates()}}
    node.request_stop=lambda:process.kill()
    def close():
        if client:pipe.close()
        process.kill()
    node.close=close
    if client:
        node._transport=pipe
        node.resource_observation=lambda:resources.pipe_observation(node._transport,node=node)
        attempt=object();controller._codec_start_attempt=attempt
        controller.node=node
        if not bind:return pipe
        return controller._bind_codec(node,pipe,attempt=attempt,client=True)
    node.resource_observation=lambda:resources.observation(node)
    controller.node=node;controller._relay=pipe;controller._relay_session=session if session is not None else object()
    if not bind:return pipe
    return controller._bind_codec(node,pipe,session=controller._relay_session)


class ProtocolCodecResourceTests(unittest.TestCase):
    def binding(self,*,client=False,profile=resources.LOW,peer=resources.LOW):
        controller=runtime.ProtocolRuntime();node=SimpleNamespace(role='LIGHT' if client else 'REPLICA')
        cell=attest_codec_fixture(controller,node,client=client,profile=profile,peer=peer)
        return controller,node,cell

    def test_unbound_initial_low_budget_cannot_authorize_new_codec_work(self):
        controller=runtime.ProtocolRuntime()
        self.assertEqual(controller._codec_upload_budget.work_burst,8)
        self.assertTrue(controller._codec_workspaces.acquire(blocking=False));self.assertTrue(controller._codec_workspaces.acquire(blocking=False))
        self.assertFalse(controller._codec_workspaces.acquire(blocking=False))
        controller._codec_workspaces.release();controller._codec_workspaces.release()
        with self.assertRaisesRegex(ValueError,'ACK_REQUIRED'):controller._codec_cell(SimpleNamespace())
        with self.assertRaisesRegex(ValueError,'ACK_REQUIRED'):
            with controller._codec_workspace(lambda:None,time.monotonic()+1):self.fail('unbound workspace ran')

    def test_low_server_and_server_to_low_peer_derive_one_attested_cell(self):
        for client,profile,peer,rate,count in ((False,resources.LOW,resources.LOW,8,2),
                (False,server(),server(),256,32),(True,server(),resources.LOW,8,32)):
            with self.subTest(client=client,mode=profile.mode,peer=peer.mode):
                controller,node,cell=self.binding(client=client,profile=profile,peer=peer)
                self.assertEqual(cell.budget.work_burst,rate);self.assertEqual(cell.limits['workspaces'],count)
                held=[]
                for _ in range(count):held.append(cell.workspaces.acquire(blocking=False))
                self.assertTrue(all(held));self.assertFalse(cell.workspaces.acquire(blocking=False))
                for _ in held:cell.workspaces.release()
                self.assertIs(controller._codec_cell(node,client=client,session=None if client else controller._relay_session),cell)

    def test_getters_chunks_polls_and_ack_refresh_never_reconstruct_or_refill_bucket(self):
        clock=[0.0];original=runtime.RefillBudget
        with patch.object(runtime,'RefillBudget',side_effect=lambda byte,work,**kwargs:original(byte,work,clock=lambda:clock[0],**kwargs)):
            controller,node,cell=self.binding(client=True)
        budget,workspaces=cell.budget,cell.workspaces
        self.assertTrue(budget.take('public-actor',budget.byte_burst,budget.work_burst))
        with patch.object(runtime,'RefillBudget',side_effect=AssertionError('fresh codec bucket')):
            for _ in range(4):
                cell.transport.ready=deepcopy(cell.transport.ready)
                node.resource_observation()
                self.assertIs(controller._codec_cell(node,client=True),cell)
                self.assertIs(controller._bind_codec(node,cell.transport,attempt=cell.attempt,client=True),cell)
                self.assertFalse(budget.take('public-actor',1,1))
        self.assertIs(cell.budget,budget);self.assertIs(cell.workspaces,workspaces)

    def test_stale_native_epoch_capture_profile_owner_and_transport_are_rejected(self):
        for change in ('epoch','capture','profile','owner','runtime_owner','transport','settings','lease'):
            with self.subTest(change=change):
                controller,node,cell=self.binding(client=True);budget=cell.budget
                if change=='epoch':node._node=dict(node._node)
                elif change=='capture':node._native_resource_attempt=resources.NativeResources(**{name:getattr(resources.LOW,name) for name in resources.NativeResources.__dataclass_fields__})
                elif change=='profile':node.profile=SimpleNamespace(_closed=False,_failed=False,_lease=object())
                elif change=='owner':node.owner=SimpleNamespace(_closed=False,_failed=False,_lease=object())
                elif change=='runtime_owner':controller.owner=SimpleNamespace(_closed=False,_failed=False,_lease=object())
                elif change=='transport':node._transport=CodecPipeFixture(node,resources.LOW,resources.LOW)
                elif change=='settings':node.settings={'resources':server().wire()}
                else:cell.transport._lease=SimpleNamespace(facts={'verified':True})
                with self.assertRaisesRegex(ValueError,'EPOCH_CHANGED|PROFILE_CHANGED'):controller._codec_cell(node,client=True)
                self.assertIs(controller._codec_client,cell);self.assertIs(cell.budget,budget)

    def test_missing_ack_and_changed_epoch_during_observation_cannot_borrow_budget(self):
        controller,node,cell=self.binding(client=True)
        cell.transport.ready.pop('resources')
        with self.assertRaisesRegex(ValueError,'ACK_REQUIRED'):controller._codec_cell(node,client=True)
        cell.transport.ready['resources']=resources.LOW.ready()
        # Client hook observes through node.resource_observation, so mutate
        # after its real attestation derivation but before the final fence.
        original=node.resource_observation
        def node_retarget():
            result=original();node._node=dict(node._node);return result
        node.resource_observation=node_retarget
        with self.assertRaisesRegex(ValueError,'EPOCH_CHANGED'):controller._codec_cell(node,client=True)

    def test_full_sdk_rates_are_required_and_refresh_keeps_the_same_cell(self):
        controller,node,cell=self.binding();budget=cell.budget
        self.assertEqual(node._node['_ready']['sdk_rates'],resources.LOW.sdk_rates())
        node._node['_ready'].pop('sdk_rates')
        with self.assertRaisesRegex(ValueError,'ACK_REQUIRED'):controller._codec_cell(node,session=controller._relay_session)
        node._node['_ready']['sdk_rates']={name:True for name in resources.LOW.sdk_rates()}
        with self.assertRaisesRegex(ValueError,'ACK_REQUIRED'):controller._codec_cell(node,session=controller._relay_session)
        node._node['_ready']['sdk_rates']=resources.LOW.sdk_rates()
        self.assertIs(controller._codec_cell(node,session=controller._relay_session),cell)
        self.assertIs(cell.budget,budget)

    def test_reconnect_cannot_reset_cell_before_explicit_terminal_retirement(self):
        controller,node,cell=self.binding(client=True)
        replacement=CodecPipeFixture(node,resources.LOW,resources.LOW)
        with self.assertRaisesRegex(ValueError,'STOP_PENDING'):
            controller._bind_codec(node,replacement,attempt=cell.attempt,client=True)
        self.assertIs(controller._codec_client,cell)

    def test_workspace_release_and_stop_invalidation_preserve_exact_bucket(self):
        controller,node,cell=self.binding(client=True)
        with self.assertRaisesRegex(ValueError,'PUBLIC_CODEC_FAILURE'):
            with controller._codec_workspace(lambda:None,time.monotonic()+1,binding=cell):raise ValueError('PUBLIC_CODEC_FAILURE')
        self.assertTrue(cell.workspaces.acquire(blocking=False));self.assertTrue(cell.workspaces.acquire(blocking=False))
        cell.workspaces.release();cell.workspaces.release()
        controller.request_stop()
        with self.assertRaisesRegex(ValueError,'EPOCH_CHANGED'):controller._codec_cell(node,client=True)
        self.assertIs(controller._codec_client,cell)

    def test_pending_full_stop_retains_cell_and_retires_only_after_explicit_retry(self):
        controller,node,cell=self.binding();cell.transport.pending_close=True
        controller.producer=SimpleNamespace(close=Mock());producer=controller.producer
        with patch.object(runtime.termination,'process_terminal',side_effect=lambda process:process.poll() is not None):
            with self.assertRaisesRegex(ValueError,'RELAY_STOP_PENDING'):controller.stop_node()
            self.assertIs(controller._codec_server,cell);self.assertIs(controller._relay,cell.transport)
            self.assertFalse(cell.active);producer.close.assert_not_called()
            cell.transport.pending_close=False;controller.stop_node()
        self.assertIsNone(controller._codec_server);self.assertIsNone(controller._relay);self.assertIsNone(controller.node)
        producer.close.assert_called_once()

    def test_explicit_relay_stop_never_clears_unrelated_light_sender_cell(self):
        controller,node,server_cell=self.binding()
        sender=SimpleNamespace(role='LIGHT')
        sender_cell=attest_codec_fixture(controller,sender,client=True)
        controller.snapshot=Mock(return_value={})
        with patch.object(runtime.termination,'process_terminal',side_effect=lambda process:process.poll() is not None):
            controller.dispatch('protocol.relay_stop',{})
        self.assertIsNone(controller._codec_server);self.assertIs(controller._codec_client,sender_cell)
        self.assertTrue(sender_cell.active);self.assertIs(controller._codec_cell(sender,client=True),sender_cell)
        self.assertIsNot(server_cell.budget,sender_cell.budget)

    def test_constructor_or_ack_bind_failure_closes_ingress_and_retains_pending_instance(self):
        from tests.test_protocol_transport_history import public_key
        for phase in ('constructor','binding'):
            for pending in (False,True):
                with self.subTest(phase=phase,pending=pending):
                    controller=runtime.ProtocolRuntime()
                    node=runtime.OwnedProtocolNode.__new__(runtime.OwnedProtocolNode)
                    node.role='REPLICA';node.anchor={'PUBLIC':'unit anchor'};node.binary=None;node._stamp=None
                    attest_codec_fixture(controller,node,bind=False)
                    node._check_start=lambda:None
                    controller.owner=node.owner;controller._relay=None;controller._relay_session=None
                    key=public_key('codec-resource-constructor');node.profile.native_node_signer=lambda:key
                    controller.snapshot=Mock(return_value={});created=[];close_pending=[pending]
                    def construct(pipe,*args,**kwargs):
                        created.append(pipe)
                        with self.assertRaisesRegex(ValueError,'ACK_REQUIRED'):
                            controller._codec_cell(node,session=controller._relay_session)
                        pipe.process=CodecProcessFixture();pipe._lease=SimpleNamespace(facts={'verified':True})
                        pipe._resources=kwargs['resources'];pipe._protected_owners=(node.owner,node.profile);pipe._closed=False
                        pipe.ready={'local_limits':pipe._resources.transport(),'limits':pipe._resources.transport()}
                        if phase=='constructor':raise ValueError('PUBLIC_CONSTRUCTOR_FAILED')
                    def close(pipe):
                        pipe._closed=True;pipe.process.kill()
                        if close_pending[0]:raise ValueError('GG_PROTOCOL_RELAY_STOP_PENDING')
                        pipe._lease=None;pipe._protected_owners=();pipe._resource_retired=True
                    expected='RELAY_STOP_PENDING' if pending else 'PUBLIC_CONSTRUCTOR_FAILED|ACK_REQUIRED'
                    with patch.object(runtime.ProofTransportServer,'__init__',construct),\
                         patch.object(runtime.ProofTransportServer,'close',close),\
                         patch.object(runtime.termination,'process_terminal',side_effect=lambda process:process.poll() is not None):
                        with self.assertRaisesRegex(ValueError,expected):
                            controller.dispatch('protocol.relay_start',{'host':'127.0.0.1','port':12345,'allowed_peer_keys':[key.pubkey().hex()]})
                        self.assertIsNone(controller._relay_session);self.assertIsNone(controller._relay_policy)
                        self.assertIsNone(controller._codec_server)
                        if pending:
                            self.assertIs(controller._relay,created[0]);self.assertIs(controller._codec_pending_relay,created[0])
                            close_pending[0]=False;controller.dispatch('protocol.relay_stop',{})
                        self.assertIsNone(controller._relay);self.assertIsNone(controller._codec_pending_relay)
                    self.assertEqual(len(created),1,'failure must never silently reconstruct a listener')

    def test_stop_during_light_constructor_cannot_publish_a_late_ready_epoch(self):
        controller=runtime.ProtocolRuntime();node=SimpleNamespace(role='LIGHT')
        attest_codec_fixture(controller,node,client=True,bind=False)
        controller.owner=node.owner;controller.node=None;controller._codec_start_attempt=None
        node.profile.anchor=lambda:{'PUBLIC':'unit anchor'};controller.replicas['Light']=node.profile
        node.start=Mock()
        def construct(*args,**kwargs):controller.request_stop();return node
        with patch.object(runtime,'local_acceptance'),patch.object(runtime,'read_public',return_value={}),\
             patch.object(runtime,'LightProtocolNode',side_effect=construct),\
             patch.object(runtime.threading,'Thread',side_effect=AssertionError('cancelled LIGHT published watcher')):
            with self.assertRaisesRegex(ValueError,'EPOCH_CHANGED'):
                controller.dispatch('protocol.light_start',{'profile':'Light','settings_path':'PUBLIC-unused-unit-path'})
        node.start.assert_not_called();self.assertIsNone(controller.node);self.assertIsNone(controller._codec_client)
        self.assertIsNone(controller._codec_pending_light);self.assertTrue(controller._cancel.is_set())

    def relay_start_fixture(self):
        from tests.test_protocol_transport_history import public_key
        controller=runtime.ProtocolRuntime();node=runtime.OwnedProtocolNode.__new__(runtime.OwnedProtocolNode)
        node.role='REPLICA';node.anchor={'PUBLIC':'unit anchor'};node.binary=None;node._stamp=None
        attest_codec_fixture(controller,node,bind=False);node._check_start=lambda:None
        # Unit stop intent need not imply synchronous main-process exit. This
        # makes the constructor's own cancellation fence essential to the case.
        node.request_stop=Mock();controller.owner=node.owner;controller._relay=None;controller._relay_session=None
        key=public_key('codec-constructor-race');node.profile.native_node_signer=lambda:key
        controller.snapshot=Mock(return_value={})
        args={'host':'127.0.0.1','port':12345,'allowed_peer_keys':[key.pubkey().hex()]}
        return controller,node,args

    @staticmethod
    def constructor_close_fixture(pipe):
        pipe._closed=True;pipe._stop.set()
        if pipe.process is not None:pipe.process.kill()
        pipe._lease=None;pipe._protected_owners=();pipe._native_retired=True;pipe._resource_retired=True

    def test_full_stop_before_init_resumes_keeps_attempt_and_cannot_spawn_after_seed_reset(self):
        controller,node,args=self.relay_start_fixture();entered=threading.Event();release=threading.Event()
        outcomes=[];errors=[];spawned=[]
        def init(pipe,*values,**kwargs):
            entered.set()
            if not release.wait(2):raise AssertionError('unit constructor gate timed out')
            # Reproduce the ordinary constructor resets that defeated G.
            pipe._closed=False;pipe._resource_retired=False;pipe._native_retired=False
            pipe._stop=threading.Event();pipe.process=None
            pipe.process=pipe._spawn_pipe(node.profile)
        def spawn(pipe,profile):spawned.append(CodecProcessFixture());return spawned[-1]
        def start():
            try:outcomes.append(controller.dispatch('protocol.relay_start',args))
            except BaseException as error:errors.append(error)
        with patch.object(runtime.ProofTransportServer,'__init__',init),\
             patch.object(runtime.ProofTransportServer,'_spawn_pipe',spawn),\
             patch.object(runtime.ProofTransportServer,'close',self.constructor_close_fixture),\
             patch.object(runtime.termination,'process_terminal',side_effect=lambda process:process.poll() is not None):
            worker=threading.Thread(target=start);worker.start()
            try:
                self.assertTrue(entered.wait(1));relay=controller._relay;attempt=controller._codec_relay_attempt
                with self.assertRaisesRegex(ValueError,'RELAY_STOP_PENDING'):controller.stop_node()
                self.assertIs(controller._relay,relay);self.assertIs(controller._codec_pending_relay,relay)
                self.assertIs(controller._codec_relay_attempt,attempt);self.assertTrue(attempt.constructing)
                self.assertTrue(attempt.cancelled);self.assertFalse(relay._resource_retired)
            finally:release.set();worker.join(3)
            self.assertFalse(worker.is_alive())
        self.assertEqual(outcomes,[]);self.assertTrue(errors);self.assertEqual(spawned,[])
        self.assertIsNone(controller._relay);self.assertIsNone(controller._codec_relay_attempt)

    def test_child_returning_after_stop_is_retained_before_postspawn_cancel_and_closed(self):
        controller,node,args=self.relay_start_fixture();entered=threading.Event();release=threading.Event()
        child=CodecProcessFixture();closed=[];outcomes=[];errors=[]
        def spawn(pipe,profile):
            entered.set()
            if not release.wait(2):raise AssertionError('unit spawn gate timed out')
            return child
        def init(pipe,*values,**kwargs):
            pipe._closed=False;pipe._resource_retired=False;pipe._native_retired=False
            pipe._stop=threading.Event();pipe.process=None
            pipe.process=pipe._spawn_pipe(node.profile)
            self.fail('cancelled spawn reached bootstrap/publication')
        def close(pipe):
            closed.append(pipe.process);self.constructor_close_fixture(pipe)
        def start():
            try:outcomes.append(controller.dispatch('protocol.relay_start',args))
            except BaseException as error:errors.append(error)
        with patch.object(runtime.ProofTransportServer,'__init__',init),\
             patch.object(runtime.ProofTransportServer,'_spawn_pipe',spawn),\
             patch.object(runtime.ProofTransportServer,'close',close),\
             patch.object(runtime.termination,'process_terminal',side_effect=lambda process:process.poll() is not None):
            worker=threading.Thread(target=start);worker.start()
            try:
                self.assertTrue(entered.wait(1));attempt=controller._codec_relay_attempt
                with self.assertRaisesRegex(ValueError,'RELAY_STOP_PENDING'):controller.stop_node()
                self.assertTrue(attempt.constructing);self.assertTrue(attempt.cancelled)
            finally:release.set();worker.join(3)
            self.assertFalse(worker.is_alive())
        self.assertEqual(outcomes,[]);self.assertTrue(errors);self.assertIn(child,closed)
        self.assertEqual(child.poll(),0);self.assertIsNone(controller._relay);self.assertIsNone(controller._codec_relay_attempt)

    def test_stop_after_binding_cannot_publish_late_relay_started_success(self):
        controller,node,args=self.relay_start_fixture();bind=controller._bind_codec;created=[]
        def spawn(pipe,profile):return CodecProcessFixture()
        def init(pipe,*values,**kwargs):
            created.append(pipe);pipe._closed=False;pipe._resources=kwargs['resources']
            pipe._protected_owners=(node.owner,node.profile);pipe._resource_retired=False;pipe._native_retired=False
            pipe._lease=SimpleNamespace(facts={'verified':True});pipe.process=pipe._spawn_pipe(node.profile)
            pipe.ready={'resources':pipe._resources.ready(),'local_limits':pipe._resources.transport(),'limits':pipe._resources.transport()}
        def bind_then_stop(*values,**kwargs):
            cell=bind(*values,**kwargs);controller.request_stop();return cell
        with patch.object(runtime.ProofTransportServer,'__init__',init),\
             patch.object(runtime.ProofTransportServer,'_spawn_pipe',spawn),\
             patch.object(runtime.ProofTransportServer,'close',self.constructor_close_fixture),\
             patch.object(controller,'_bind_codec',side_effect=bind_then_stop),\
             patch.object(runtime.termination,'process_terminal',side_effect=lambda process:process.poll() is not None):
            with self.assertRaisesRegex(ValueError,'EPOCH_CHANGED'):controller.dispatch('protocol.relay_start',args)
        self.assertEqual(len(created),1);self.assertIsNone(controller._relay_session)
        self.assertIsNone(controller._relay);self.assertIsNone(controller._codec_server);self.assertIsNone(controller._codec_relay_attempt)
