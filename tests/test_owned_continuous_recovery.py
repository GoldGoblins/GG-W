"""Source-only proposal. NOT_EXECUTED; these policy seams are not load proof.

Activate with the coherent candidate only after Root GO. Clocked lease tests
exercise deadlines; they do not replace the required actual >180s cold replay.
The native tests separately construct genuine originals and retained segments.
"""
from copy import deepcopy
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from backend.gg_native_start import OwnedRecoveryProgress
from backend import gg_native_resources as resources
from backend import gg_protected_restore as restore
from backend import gg_protocol_runtime as runtime
from backend.terminal_cli import foreground_summary
from tests.test_protocol_observation_sources import body as observation_body
from backend import local_node_observation as observation


class ContinuousRecoveryBoundaries(unittest.TestCase):
    def setUp(self):
        self.now=0.0
        temporary=tempfile.TemporaryDirectory(prefix='gg-recovery-boundary-');self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.binding={'pid':77,'genesis_hash':'a'*64,'root':str(self.root/'owned-native'),
            'attempt':'b'*32,'resource_profile':resources.LOW.ready()}

    def lease(self,archive=False):
        return OwnedRecoveryProgress(**self.binding,archive=archive,clock=lambda:self.now)

    def frame(self,phase='INVENTORY',work=1,height=None,**changes):
        return {'schema':'gg.native.owned-recovery-progress.v1',**deepcopy(self.binding),'phase':phase,
            'work_done':work,'processed_height':height,'verified_through':None,'native_node_ready':False,**changes}

    def test_completed_work_can_cross_old_total_budget_but_identical_frames_cannot_renew(self):
        lease=self.lease();lease.accept(self.frame())
        for step in range(1,8):
            self.now+=60
            lease.accept(self.frame(work=step+1))
            self.assertFalse(lease.expired())
        self.assertGreater(self.now,180)
        # Three unchanged reports do not grant an additional second.
        for _ in range(3):self.now+=59;lease.accept(self.frame(work=8))
        self.now+=3
        self.assertTrue(lease.expired())
        with self.assertRaisesRegex(ValueError,'STALLED'):lease.accept(self.frame(work=9))

    def test_s63_heights_are_exact_above_javascript_range_and_at_existing_maximum(self):
        lease=self.lease();above=2**53+1;maximum=2**63-1
        lease.accept(self.frame(work=above,height=above))
        value=lease.accept(self.frame('VERIFY_HISTORY',work=maximum,height=maximum))
        self.assertEqual(value['processed_height'],str(maximum))
        self.assertIsNone(value['verified_through'])
        lease.accept(self.frame('VERIFY_SDK_BINDINGS',work=maximum,height=maximum))
        lease.accept(self.frame('SDK_START',work=maximum,height=maximum));lease.ready()
        for field in ('work_done','processed_height'):
            with self.assertRaises(ValueError):lease.accept(self.frame('SDK_START',work=maximum,height=maximum,**{field:2**63}))

    def test_binding_phase_typing_corruption_and_provisional_verification_fail_closed(self):
        for changes in ({'pid':78},{'pid':77.0},{'attempt':'c'*32},{'root':self.binding['root']+'-other'},
                        {'genesis_hash':'c'*64},{'native_node_ready':True},{'work_done':True},
                        {'verified_through':0},{'phase':'VERIFY_HISTORY'},{'unknown':0}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.lease().accept(self.frame(**changes))
        changed=resources.LOW.ready();changed['profile']['go_max_procs']=2.0
        with self.assertRaises(ValueError):self.lease().accept(self.frame(resource_profile=changed))
        lease=self.lease();lease.accept(self.frame())
        with self.assertRaises(ValueError):lease.accept(self.frame('SDK_START',work=2))
        lease.accept(self.frame('VERIFY_HISTORY',work=2,height=20))
        lease.accept(self.frame('VERIFY_HISTORY',work=2,height=None))
        with self.assertRaises(ValueError):lease.accept(self.frame('VERIFY_HISTORY',work=3,height=19))
        with self.assertRaises(ValueError):lease.accept(self.frame('INVENTORY',work=3))
        lease.accept(self.frame('VERIFY_SDK_BINDINGS',work=3,height=20))
        lease.accept(self.frame('SDK_START',work=4,height=20));lease.handshake()
        self.now=12
        with self.assertRaisesRegex(ValueError,'INCOMPLETE'):lease.ready()

    def test_archive_and_normal_phase_sequences_cannot_be_crossed_or_skipped(self):
        normal=self.lease();normal.accept(self.frame())
        with self.assertRaises(ValueError):normal.accept(self.frame('ARCHIVE_AUDIT',work=2))
        archive=self.lease(archive=True)
        for step,phase in enumerate(('INVENTORY','ARCHIVE_AUDIT','ARCHIVE_RESTORE','VERIFY_HISTORY','VERIFY_SDK_BINDINGS','SDK_START')):
            archive.accept(self.frame(phase,work=step+1,height=step))
        archive.ready()
        # A new process gets no successful cursor or inherited lease.
        restarted=self.lease(archive=True)
        with self.assertRaisesRegex(ValueError,'INCOMPLETE'):restarted.ready()

    def test_cancel_and_late_epoch_stop_keep_the_exact_child_and_profile_fence(self):
        owner=SimpleNamespace(_closed=False,_failed=False,_db=object(),_lease=object())
        profile=SimpleNamespace(_closed=False,_failed=False,_db=object(),_lease=object(),root=self.root)
        old_child=SimpleNamespace(terminate=Mock());new_child=SimpleNamespace(terminate=Mock())
        node=SimpleNamespace(settings={},profile=profile,owner=owner,anchor={},rpc_port=88,
            _process_owner=lambda:owner,_check_start=Mock(),_node={'process':old_child})
        resource=restore._HandoffResource(node);node._restore_resource=resource
        resource.process=old_child;resource.epoch=node._node;resource.rpc_port=88
        resource.check();node._node={'process':new_child}
        with self.assertRaisesRegex(ValueError,'EPOCH_CHANGED'):resource.check()
        with patch.object(restore.termination,'process_terminal',return_value=False):
            resource.request_stop()
            with self.assertRaises(restore.pipes.NativePipeStopPending):resource.retire_after_terminal(old_child)
        old_child.terminate.assert_called_once();new_child.terminate.assert_not_called()
        self.assertFalse(resource._resource_retired)
        self.assertIs(resource._protected_lifetimes[0][1],owner._db)
        # An immutable READY report cannot survive an unexpected child death.
        node._node=resource.epoch;node.process_ready=lambda:False;node._alive=lambda:False
        node._recovery_progress_record=(node._node,{'phase':'READY','node_ready':True,'consensus_signing':True,
            'verified_through':'17','full_original_audit_completed':True,'last_error':''})
        public=restore.recovery_progress(node)
        self.assertEqual(public['phase'],'STOPPED');self.assertFalse(public['consensus_signing'])

    def test_actual_owned_observer_returns_during_blocked_start_and_old_worker_cannot_poison_new_epoch(self):
        controller=runtime.ProtocolRuntime();entered=threading.Event();release=threading.Event()
        node=SimpleNamespace(role='VALIDATOR',_node={'process':None},close=Mock())
        def start():entered.set();release.wait(2);raise ValueError('GG_PUBLIC_OLD_WORKER')
        node.start=start;controller.node=node
        try:
            controller._start_owned_observer(node)
            self.assertTrue(entered.wait(1));self.assertTrue(node._recovering)
            self.assertIs(controller.node,node);self.assertIs(node._foreground_cancel,controller._cancel)
            newer=object();controller.node=newer;release.set();controller._thread.join(2)
            self.assertFalse(controller._thread.is_alive());self.assertIs(controller.node,newer)
            self.assertEqual(controller._error,'')
        finally:release.set();controller._thread.join(2)

    def test_real_selected_source_and_cli_preserve_recovery_without_votes_or_contact(self):
        # The actual snapshot projector clears a dead/inactive epoch's cached
        # activity flags while retaining historical certificate/account rows.
        controller=runtime.ProtocolRuntime()
        historical=[{'profile':'History','balance_atomic':'7','nonce':'2'}]
        controller._account_views=historical
        controller._view={'state':'RUNNING','node_ready':True,'consensus_signing':True,
            'certificate_height':4,'state_root':None,'producers':[],'committee':[],'voting_power':'0'}
        controller.owner=SimpleNamespace(name='Owner',snapshot=lambda:{},
            descriptor=lambda:{'label':'Owner','public_keys':['d'*64]})
        controller.node=SimpleNamespace(role='VALIDATOR',profile=SimpleNamespace(name='Vote'),
            node_key='c'*64,_alive=lambda:False,settings={'peers':[]},
            anchor={'genesis_hash':'a'*64,'genesis':{'chain_id':'ggnet:'+'a'*24,
                'financial_dag':{'network_id':'a'*64},'protocol':{'environment':'TESTNET'}}})
        for active in (True,False):
            if not active:controller.node=None
            stopped=controller.snapshot()
            self.assertEqual(stopped['state'],'STOPPED');self.assertFalse(stopped['node_ready'])
            self.assertFalse(stopped['consensus_signing']);self.assertEqual(stopped['certificate_height'],4)
            self.assertEqual(stopped['own_financial_accounts'],historical)
        value=observation_body('Recovering',0)
        progress={'schema':'gg.owned.recovery-observation.v1','phase':'VERIFY_HISTORY','requested_role':'VALIDATOR',
            'work_done':str(2**53+1),'processed_height':'17','verified_through':None,'last_error':'',
            'basis':'LOCAL_OWNED_NATIVE_PIPE_REPORT','node_ready':False,'full_original_audit_completed':False,
            'snapshot_trust_used':False,'certificate_is_network_liveness':False,
            'network_contact_asserted':False,'consensus_signing':False}
        value.update(state='RECOVERING',node_ready=False,consensus_signing=False,own_financial_accounts=[])
        value['protocol_network']['recovery_startup']=progress
        with tempfile.TemporaryDirectory(prefix='gg-recovery-observation-') as directory:
            publisher=observation.Publisher(Path(directory));reader=observation.Reader(Path(directory))
            try:
                publisher.publish(value);selected=reader.snapshot()
                self.assertEqual(selected['state'],'RECOVERING')
                self.assertEqual(selected['protocol_network']['recovery_startup']['work_done'],str(2**53+1))
                summary=foreground_summary('protocol.node_start',selected)
                self.assertFalse(summary['node_ready']);self.assertFalse(summary['consensus_signing'])
                self.assertFalse(summary['certificate_is_network_liveness'])
                self.assertIsNone(summary['recovery_startup']['verified_through'])
                self.assertEqual(summary['own_accounts'],[])
            finally:publisher.close()


class RecoveryAmendmentBoundaries(unittest.TestCase):
    """Actual class/control flow with bounded transport/native-start seams.

    No seam below is an SDK certificate, encrypted handshake or real native
    process. Disposable profiles and the real LIGHT/runtime methods are used.
    """
    def test_final_sdk_start_requires_typed_cold_cut_and_accepts_genesis_zero(self):
        binding={'pid':77,'genesis_hash':'a'*64,'root':str(Path(tempfile.gettempdir()).absolute()/'PUBLIC-cut'),
            'attempt':'b'*32,'resource_profile':resources.LOW.ready()}
        def completed(cut):
            lease=OwnedRecoveryProgress(**binding,clock=lambda:0)
            for index,phase in enumerate(('INVENTORY','VERIFY_HISTORY','VERIFY_SDK_BINDINGS','SDK_START')):
                lease.accept({'schema':'gg.native.owned-recovery-progress.v1',**binding,'phase':phase,
                    'work_done':index+1,'processed_height':cut if phase=='SDK_START' else None,
                    'verified_through':None,'native_node_ready':False})
            return lease
        with self.assertRaisesRegex(ValueError,'INCOMPLETE'):completed(None).ready()
        completed(0).ready()
        for invalid in (False,0.0,'0',-1,2**63):
            with self.subTest(cut=invalid),self.assertRaises(ValueError):completed(invalid)

    def test_actual_light_class_readiness_snapshot_and_inherited_query_entries(self):
        from contextlib import ExitStack
        from backend import gg_protocol_light as light,gg_node_store as nodes,gg_observer_profile as observers
        from backend import portable_wallet_vault as vault,gg_financial_protocol as protocol
        from tests.test_durable_node_store import configuration
        from tests.test_protocol_integrated_profiles import public_protocol_pin
        from tests.test_native_resources import server

        class TransportSeam:
            def __init__(self,key,pin,settings,**values):
                self._protected_owners=(values['owner'],values['profile']);self._resources=values['resources']
                self.closed=False;self.calls=[];self.process=SimpleNamespace(pid=77,returncode=None)
                self.process.poll=lambda:self.process.returncode
                self.ready={'schema':light.TRANSPORT_SCHEMA,'event':'READY','genesis_hash':pin['genesis_hash'],
                    'peer_key':settings['server_key'],'resources':self._resources.ready(),
                    'limits':self._resources.transport(),'local_limits':self._resources.transport()}
            def alive(self):return not self.closed and self.process.poll() is None
            def call(self,value):
                self.calls.append(deepcopy(value));raise ValueError('GG_PUBLIC_LIGHT_QUERY_ENTRY_REACHED')
            def close(self):self.closed=True
            def request_stop(self):self.closed=True

        with tempfile.TemporaryDirectory(prefix='gg-actual-light-class-') as directory,ExitStack() as stack:
            root=Path(directory)
            stack.enter_context(patch.object(nodes,'ROOT',root/'nodes'))
            stack.enter_context(patch.object(observers,'ROOT',root/'observers'))
            stack.enter_context(vault.session('PUBLIC disposable actual LIGHT class boundary'))
            owner=nodes.NodeProfile.create('Owner',configuration());stack.callback(owner.close)
            pin=public_protocol_pin();profile=observers.ObserverProfile.create_for_protocol('Light',owner,pin,label='Actual LIGHT class')
            stack.callback(profile.close)
            settings={'host':'127.0.0.1','port':23455,'server_key':pin['genesis']['protocol']['committee']['members'][0]['node_key']}
            node=light.LightProtocolNode(profile,owner,settings,binary=Path('PUBLIC-unused-native'),stamp=None)
            stack.callback(node.close)
            with patch.object(light,'ProofTransportClient',TransportSeam):view=node.start()
            self.assertTrue(node.process_ready());self.assertEqual(view['role'],'LIGHT')
            self.assertFalse(view['native_sdk_process']);self.assertFalse(view['consensus_signing'])
            self.assertEqual(view['voting_power'],'0');self.assertFalse(view['local_full_history_replayed'])
            self.assertEqual(view['local_history']['state'],'NOT_APPLICABLE');self.assertIsNone(view['network_contact_at'])
            self.assertFalse(hasattr(node,'_epoch_stopping'));self.assertNotIn('_ready',node._node)
            transport=node._transport
            selector={'namespace':'producers','key':pin['genesis']['financial_dag']['producers'][0]}
            with patch.object(protocol,'verify_selected',return_value={}):
                with self.assertRaisesRegex(ValueError,'QUERY_ENTRY_REACHED'):node.selected_proof('registry',selector,packet={'PUBLIC':'query routing seam','state':{'height':0}})
            with self.assertRaisesRegex(ValueError,'QUERY_ENTRY_REACHED'):node.original_core('f'*64)
            self.assertEqual(len(transport.calls),2);self.assertTrue(all(row['method']=='query' for row in transport.calls))
            for target,attribute,value in ((node,'_transport',SimpleNamespace(alive=lambda:True)),
                    (node,'_node',{'process':SimpleNamespace(poll=lambda:None)}),
                    (owner,'_closed',True),(profile,'_failed',True),(owner,'_db',object()),
                    (profile,'_lease',object()),(transport,'_resources',server())):
                with self.subTest(attribute=attribute),patch.object(target,attribute,value):
                    self.assertFalse(node.process_ready())
                    with self.assertRaisesRegex(ValueError,'NODE_RECOVERING'):node.original_core('f'*64)
            with patch.dict(node.settings,{'resources':server().wire()}):self.assertFalse(node.process_ready())
            with patch.dict(transport.ready,{'peer_key':'0'*64}):self.assertFalse(node.process_ready())
            transport.process.returncode=1;self.assertFalse(node.process_ready())
            self.assertFalse(node.snapshot()['consensus_signing']);self.assertEqual(node.snapshot()['state'],'STOPPED')

    def _operator(self,*,role='VALIDATOR',extras=False,fail=False,cancel=False):
        config={'schema':'gg.protocol.local-start.v2','owner_profile':'Owner','native_profile':'Native','role':role,
            'settings_path':'settings.json','account_profiles':[],'producer':extras,'mining':None,
            'pools':[],'relay':None,'account_submissions':[],'pool_work':None}
        class StartSeam(runtime.ProtocolRuntime):
            def __init__(self):
                super().__init__();self.effects=[];self._watch=Mock();self.entered=threading.Event()
            def dispatch(self,command,args):
                if command=='protocol.run':return super().dispatch(command,args)
                if command=='protocol.owner_open':self.owner=SimpleNamespace(name=args['profile'])
                elif command=='protocol.validator_open':
                    self.validators[args['profile']]=SimpleNamespace(anchor=lambda:{'PUBLIC':'pin'},account_reference=lambda:None)
                elif command=='protocol.replica_open':self.replicas[args['profile']]=SimpleNamespace(anchor=lambda:{'PUBLIC':'pin'})
                elif command=='protocol.node_start':
                    self._reset_observation();self._cancel.clear()
                    node=SimpleNamespace(role=role,_node={'process':None},ready=False,close=Mock(),request_stop=Mock())
                    node.process_ready=lambda:node.ready and not self._cancel.is_set()
                    def start():
                        self.entered.set()
                        if cancel:
                            self._cancel.wait(1);raise ValueError('GG_PUBLIC_START_CANCELLED')
                        if fail:raise ValueError('GG_PUBLIC_START_FAILED')
                        node.ready=True
                    node.start=start;self.node=node;self._bind_operator_start(node);self._start_owned_observer(node)
                    self.entered.wait(1)
                    if cancel:self.request_stop()
                    # Deliberately complete before the enclosing run dispatch
                    # returns, while it still holds _control. No worker may
                    # acquire that lock for its completion/failure record.
                    self._thread.join(2)
                    if self._thread.is_alive():raise AssertionError('worker blocked on command lock')
                elif command=='protocol.producer_open':self.effects.append(command)
                return {}
            def snapshot(self):
                return {'state':self._operator_start_state,'pending':self._operator_pending is not None,'error':self._operator_start_error}
        controller=StartSeam()
        with patch.object(runtime,'read_public',side_effect=lambda path,*args:deepcopy(config) if str(path)=='start.json' else {}),\
                patch.object(runtime,'local_acceptance',side_effect=lambda value,*args:value):
            result=controller.dispatch('protocol.run',{'path':'start.json'})
        return controller,result

    def test_actual_runtime_node_only_early_success_failure_and_stop_are_terminal_without_certificate(self):
        for role in ('VALIDATOR','REPLICA'):
            controller,result=self._operator(role=role)
            self.assertEqual(result,{'state':'NODE_STARTED','pending':False,'error':''})
            controller._watch.assert_called_once();self.assertEqual(controller.effects,[])
            controller._advance_operator_start(False);self.assertEqual(controller._operator_start_state,'NODE_STARTED')
        for extras in (False,True):
            controller,result=self._operator(extras=extras,fail=True)
            self.assertEqual(result,{'state':'FAILED','pending':False,'error':'GG_PUBLIC_START_FAILED'})
            controller._watch.assert_not_called();controller.node.close.assert_called_once();self.assertEqual(controller.effects,[])
        controller,result=self._operator(cancel=True,extras=True)
        self.assertEqual(result,{'state':'STOPPED','pending':False,'error':''})
        controller.node.request_stop.assert_called_once();self.assertEqual(controller.effects,[])

    def test_actual_runtime_extras_require_certificate_once_and_stop_invalidates_pending(self):
        controller,result=self._operator(extras=True)
        self.assertEqual(result,{'state':'WAITING_FOR_CERTIFICATE','pending':True,'error':''})
        self.assertIsNotNone(controller._operator_pending['deadline']);self.assertEqual(controller.effects,[])
        controller._advance_operator_start(False);self.assertEqual(controller.effects,[])
        controller._advance_operator_start(True)
        self.assertEqual(controller.effects,['protocol.producer_open']);self.assertIsNone(controller._operator_pending)
        self.assertEqual(controller._operator_start_state,'READY')
        controller._advance_operator_start(True);self.assertEqual(controller.effects,['protocol.producer_open'])
        waiting,_=self._operator(extras=True);waiting.request_stop();waiting._advance_operator_start(True)
        self.assertEqual(waiting._operator_start_state,'STOPPED');self.assertIsNone(waiting._operator_pending)
        self.assertEqual(waiting.effects,[])


if __name__=='__main__':unittest.main()
