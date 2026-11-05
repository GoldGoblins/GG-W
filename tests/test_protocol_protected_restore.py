"""Protected journal/pipe policy regression proposals, not live SDK evidence.

Profiles, vault records and signatures below are real disposable filesystem
objects. Recorded pipes/threads and terminal results are explicit unit seams;
the native Go cases independently execute genuine originals and SDK encodings.
"""
from contextlib import ExitStack
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import tempfile
import socket
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from backend import gg_protected_restore as restore
from backend import gg_observer_profile as observers,gg_node_store as nodes
from backend import portable_wallet_vault as vault,gg_native_pipe_lifecycle as pipes
from backend import gg_protocol_runtime as runtime,gg_protocol_transport as transport
from backend import gg_consensus as native
from backend import gg_financial_protocol as protocol
from backend.gg_native_start import START_MAX_SECONDS
from backend.terminal_cli import FOREGROUND_COMMANDS,foreground_summary
from tests.test_durable_node_store import configuration
from tests.test_protocol_integrated_profiles import public_protocol_pin


def structural_packet(pin,*,height=1,block='b'*64):
    """A journal-policy seam only: this is deliberately NOT an SDK certificate."""
    return {'schema':'gg.consensus.proof.v1',**deepcopy(pin),'state':{'height':height,'state_root':'a'*64},
        'signed_header':{'header':{'height':str(height+1)},'commit':{'block_id':{'hash':block}}}}


class ProtectedReplicaRecoveryJournalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='gg-owned-restore-profile-');self.addCleanup(self.temp.cleanup)
        self.stack=ExitStack();self.addCleanup(self.stack.close);root=Path(self.temp.name)
        self.stack.enter_context(patch.object(nodes,'ROOT',root/'nodes'))
        self.stack.enter_context(patch.object(observers,'ROOT',root/'observers'))
        self.stack.enter_context(vault.session('PUBLIC disposable handoff regression password'))
        self.owner=nodes.NodeProfile.create('Owner',configuration());self.addCleanup(self.owner.close)
        self.pin=public_protocol_pin()
        self.profile=observers.ObserverProfile.create_for_protocol('Replica',self.owner,self.pin,label='Existing nonvoting replica')
        self.addCleanup(lambda:self.profile.close());self.packet=structural_packet(self.pin)

    def test_canonical_ready_before_restore_ack_is_rejected_by_actual_restore_loop(self):
        # Explicit pipe/launcher/terminal seams; the actual decoder and phase
        # loop run, without a native process, socket or SDK proof claim.
        from backend import gg_native_resources as resources
        archive=Path(self.temp.name)/'PUBLIC-early-ready.ggfin';archive.write_bytes(b'not a native archive proof')
        child=SimpleNamespace(pid=17,stdin=io.BytesIO(),stdout=io.BytesIO(),poll=lambda:None,
            terminate=Mock(),kill=Mock())
        node=SimpleNamespace(profile=self.profile,owner=self.owner,anchor=self.pin,role='REPLICA',
            settings={'resources':resources.LOW.wire()},member={'host':'127.0.0.1','p2p_port':23451},
            node_key=self.profile.native_node_signer().pubkey().hex(),binary=Path('/PUBLIC-unused-native'),
            _lock=threading.RLock(),_node={'process':None,'_ready':None},rpc_port=None,
            _process_owner=lambda:self.owner,_unchanged=Mock(),_check_start=Mock(),
            _native_forbidden_ports=lambda:set(),_native_bootstrap=Mock())
        node._native_ready=lambda process:{'schema':'gg.consensus.protocol-ready.v1',
            'chain_id':self.pin['genesis']['chain_id'],'genesis_hash':self.pin['genesis_hash'],
            'node_id':'c'*40,'pid':process.pid,'rpc_port':23450,'p2p_host':'127.0.0.1','p2p_port':23451,
            'role':'REPLICA','consensus_signing':False,'state_sync':False}
        child.stdout.write(native._pack(resources.readiness(node,node._native_ready(child)))+b'\n');child.stdout.seek(0)
        reserve=SimpleNamespace(bind=Mock(),getsockname=lambda:('127.0.0.1',23450),close=Mock())
        with patch.object(restore,'_reserve_p2p_endpoint',return_value=reserve), \
                patch.object(restore.socket,'socket',return_value=reserve), \
                patch.object(restore.subprocess,'Popen',return_value=child), \
                patch('backend.gg_posix_native.launch',return_value=child), \
                patch.object(restore,'contain_owned_native',return_value=SimpleNamespace(facts={},close=Mock())), \
                patch.object(restore.threading,'Thread'),patch.object(restore.pipes,'bind_owned_pipe'), \
                patch.object(restore,'_stop_attempt'),patch.object(restore,'_ack') as ack, \
                patch.object(restore,'_validated_ready_frame',wraps=restore._validated_ready_frame) as validated, \
                patch.object(self.profile,'prepare_recovery',wraps=self.profile.prepare_recovery) as prepare:
            with self.assertRaisesRegex(ValueError,'GG_OWNED_RESTORE_READY'):restore.restore_start(node,archive)
        validated.assert_not_called();prepare.assert_not_called();ack.assert_not_called()
        node._native_bootstrap.assert_not_called();self.assertIsNone(node._node['_ready'])
        self.assertEqual(node._restore_progress_record[1]['phase'],'FAILED')
        self.assertFalse(node._restore_progress_record[1]['node_ready'])

    def test_rejected_restore_never_rebinds_live_or_retained_low_resource_attempt(self):
        from backend import gg_native_resources as resources
        from tests.test_native_resources import server
        archive=Path(self.temp.name)/'PUBLIC-rejected-start.ggfin';archive.write_bytes(b'not read on rejected start')
        child=SimpleNamespace(poll=lambda:None,kill=Mock(),terminate=Mock())
        for process,previous in ((child,object()),(None,SimpleNamespace(_resource_retired=False))):
            node=SimpleNamespace(profile=self.profile,owner=self.owner,anchor=self.pin,role='REPLICA',
                settings={'resources':server().wire()},_native_resource_attempt=resources.LOW,
                _lock=threading.RLock(),_node={'process':process},_restore_resource=previous,
                _process_owner=lambda:self.owner,_unchanged=Mock(),_check_start=Mock())
            epoch=node._node
            with patch.object(restore.resources,'capture',wraps=resources.capture) as capture:
                with self.assertRaises((ValueError,pipes.NativePipeStopPending)):restore.restore_start(node,archive)
            capture.assert_not_called()
            self.assertIs(node._native_resource_attempt,resources.LOW)
            self.assertIs(node._node,epoch);self.assertIs(node._restore_resource,previous)
        child.kill.assert_not_called();child.terminate.assert_not_called()

    def test_terminal_epoch_can_validate_new_profile_without_live_capture_or_rejected_check_drift(self):
        from backend import gg_native_resources as resources
        from tests.test_native_resources import server
        archive=Path(self.temp.name)/'PUBLIC-terminal-epoch.ggfin';archive.write_bytes(b'not read before admission')
        selected=server();observed=[]
        node=SimpleNamespace(profile=self.profile,owner=self.owner,anchor=self.pin,role='REPLICA',
            settings={'resources':selected.wire()},_native_resource_attempt=resources.LOW,
            _lock=threading.RLock(),_node={'process':None},_restore_resource=None,_unchanged=Mock(),
            _process_owner=lambda:self.owner)
        def check():observed.append(resources.current(node))
        node._check_start=Mock(side_effect=check)
        with patch.object(restore,'_HandoffResource',side_effect=ValueError('GG_PUBLIC_AFTER_NEW_PROFILE_CHECK')):
            with self.assertRaisesRegex(ValueError,'AFTER_NEW_PROFILE_CHECK'):restore.restore_start(node,archive)
        self.assertEqual(observed,[selected])
        self.assertIs(node._native_resource_attempt,resources.LOW)
        self.assertIsNone(node._node['process']);self.assertIsNone(node._restore_resource)

    def test_schema7_pending_intent_survives_cold_profile_without_new_key_or_owner(self):
        key=self.profile.native_node_signer().pubkey().hex();owner=self.profile._body['owner_key']
        self.profile.prepare_recovery('c'*64,self.packet)
        self.assertEqual(self.profile._body['schema'],observers.PUBLIC_RECOVERY_SCHEMA)
        self.assertEqual(self.profile.anchor(),self.pin)
        with self.assertRaisesRegex(ValueError,'RECOVERY_INCOMPLETE'):self.profile.claim_native_start()
        self.profile.close();self.profile=observers.ObserverProfile.open('Replica')
        self.assertEqual(self.profile.native_node_signer().pubkey().hex(),key)
        self.assertEqual(self.profile._body['owner_key'],owner)
        self.assertEqual(self.profile._recovery_intent()['certificate'],self.packet)
        self.assertTrue(self.profile.snapshot()['recovery_pending'])
        self.assertFalse((self.profile.root/'native').exists())

    def test_completed_recovery_keeps_exact_floor_and_allows_only_existing_native_root(self):
        self.profile.prepare_recovery('c'*64,self.packet)
        self.profile.finish_recovery('c'*64,self.packet)
        with self.assertRaisesRegex(ValueError,'HISTORY_MISSING'):self.profile.claim_native_start()
        # Only the filesystem context is modeled here; this empty directory
        # is not asserted to be a verified native history or usable SDK store.
        (self.profile.root/'native').mkdir(mode=0o700)
        self.assertIs(self.profile.claim_native_start(),False)
        key=self.profile.native_node_signer().pubkey().hex()
        self.profile.close();self.profile=observers.ObserverProfile.open('Replica')
        self.assertEqual(self.profile.public_certificate(),self.packet)
        self.assertEqual(self.profile.native_node_signer().pubkey().hex(),key)
        self.assertFalse(self.profile.snapshot()['recovery_pending'])
        self.assertFalse(hasattr(self.profile,'native_signers'))

    def test_changed_archive_or_certificate_cannot_retarget_pending_original_intent(self):
        self.profile.prepare_recovery('c'*64,self.packet)
        before=deepcopy(self.profile._body)
        for digest,packet in (('d'*64,self.packet),('c'*64,structural_packet(self.pin,block='e'*64))):
            with self.assertRaisesRegex(ValueError,'INTENT_CHANGED'):self.profile.prepare_recovery(digest,packet)
            with self.assertRaisesRegex(ValueError,'INTENT_CHANGED'):self.profile.finish_recovery(digest,packet)
        self.assertEqual(self.profile._body,before)

    def test_pending_public_recovery_cannot_open_a_second_transport_with_same_identity(self):
        self.profile.prepare_recovery('c'*64,self.packet)
        with self.assertRaisesRegex(ValueError,'RECOVERY_INCOMPLETE'):
            transport._protected_context(self.profile.native_node_signer(),self.pin,self.owner,self.profile)
        self.profile.finish_recovery('c'*64,self.packet)
        self.assertEqual(transport._protected_context(self.profile.native_node_signer(),self.pin,self.owner,self.profile),(self.owner,self.profile))

    def test_profile_close_retains_real_protected_journals_until_declared_child_terminal(self):
        child=SimpleNamespace(pid=12345,terminate=Mock())
        node=SimpleNamespace(profile=self.profile,owner=self.owner,anchor=self.pin,_lock=threading.RLock(),_node={'process':child},
            rpc_port=12346,_process_owner=lambda:self.owner,request_stop=Mock(),stop=Mock(side_effect=pipes.NativePipeStopPending))
        resource=restore._HandoffResource(node);resource.process=child
        resource.epoch=node._node;resource.rpc_port=node.rpc_port;node._restore_resource=resource
        pipes.bind_owned_pipe(resource,resource._protected_owners)
        try:
            with patch.object(restore.termination,'process_terminal',return_value=False):
                with self.assertRaises(pipes.NativePipeStopPending):resource.retire_after_terminal(child)
            with patch.object(restore.termination,'process_terminal',return_value=False):
                with self.assertRaises(pipes.NativePipeStopPending):self.profile.close()
            self.assertFalse(self.profile._closed);self.assertIsNotNone(self.profile._db)
            self.assertFalse(resource._resource_retired)
            with patch.object(restore.termination,'process_terminal',return_value=True):resource.retire_after_terminal(child)
            self.assertTrue(resource._resource_retired)
            self.profile.close();self.assertTrue(self.profile._closed)
        finally:
            with patch.object(restore.termination,'process_terminal',return_value=True):resource.retire_after_terminal(child)


class OwnedRestoreFrameAndProgressTests(unittest.TestCase):
    def node(self):
        node=SimpleNamespace(anchor=public_protocol_pin(),_node={'process':None},_epoch_stopping=False,
            _start_cancelled=lambda:False,_alive=lambda:True)
        return node

    def ready(self,selected,*,schema='gg.consensus.protocol-ready.v1'):
        from backend import gg_native_resources as resources
        node=self.node();node._lock=threading.RLock();node.settings={'resources':selected.wire()}
        process=SimpleNamespace(pid=17,stdout=None)
        value={'schema':schema,'chain_id':node.anchor['genesis']['chain_id'],'genesis_hash':node.anchor['genesis_hash'],
            'node_id':'c'*40,'pid':17,'rpc_port':23450,'p2p_host':'127.0.0.1','p2p_port':23451,
            'consensus_signing':False,'state_sync':False}
        if schema=='gg.consensus.protocol-ready.v1':value['role']='REPLICA'
        node._native_ready=lambda owned:deepcopy(value)
        resources.capture(node);node._node={'process':process,'_ready':None}
        return node,process,resources.readiness(node,deepcopy(value))

    def test_canonical_sdk_ready_low_and_server256_decode_through_actual_attempt_reader(self):
        from backend import gg_native_resources as resources
        selected=(resources.LOW,resources.NativeResources('SERVER',256,256,256*1024**2,
            512*1024**2,8*1024**3,1024,1024*1024**2,10000,6))
        for profile in selected:
            for schema in ('gg.consensus.protocol-ready.v1','gg.consensus.observer-ready.v1'):
                with self.subTest(mode=profile.mode,schema=schema):
                    node,process,expected=self.ready(profile,schema=schema)
                    raw=native._pack(expected)+b'\n';self.assertLessEqual(len(raw),1024)
                    process.stdout=io.BytesIO(raw)
                    resource=SimpleNamespace(node=node,process=process,check=Mock())
                    frame=restore._read_attempt_frame(resource)
                    resource.check.assert_called_once_with()
                    actual=restore._validated_ready_frame(node,process,frame)
                    self.assertIs(actual['process'],process);self.assertEqual(actual['resources'],profile.ready())
                    self.assertEqual(actual['sdk_rates'],profile.sdk_rates());self.assertIsNone(node._node['_ready'])

    def test_ready_parser_rejects_declared_struct_order_and_duplicate_or_noncanonical_frames(self):
        from backend import gg_native_resources as resources
        for profile in (resources.LOW,resources.NativeResources('SERVER',256,256,256*1024**2,
                512*1024**2,8*1024**3,1024,1024*1024**2,10000,6)):
            node,process,expected=self.ready(profile)
            raw=native._pack(expected)+b'\n'
            # Match the former Go bug: sorted outer maps but nativeResources
            # struct declaration order at resources.profile. This is not a
            # second accepted dialect after the producer's normalization.
            declared=json.loads(raw);declared['resources']['profile']=profile.wire()
            struct_raw=json.dumps(declared,ensure_ascii=False,separators=(',',':')).encode()+b'\n'
            self.assertNotEqual(struct_raw,raw)
            rawlist=(struct_raw,b' '+raw,raw[:-1],raw[:-2]+b',"pid":17}\n',
                raw.replace(b'"mode":"'+profile.mode.encode()+b'"',
                    b'"mode":"'+profile.mode.encode()+b'","mode":"'+profile.mode.encode()+b'"'))
            for candidate in rawlist:
                with self.subTest(mode=profile.mode,raw=candidate[:80]):
                    process.stdout=io.BytesIO(candidate)
                    resource=SimpleNamespace(node=node,process=process,check=Mock())
                    with self.assertRaisesRegex(ValueError,'GG_OWNED_RESTORE_FRAME'):restore._read_attempt_frame(resource)
                    resource.check.assert_not_called();self.assertIsNone(node._node['_ready'])

    def test_decoded_ready_rejects_unknown_mismatched_and_numerically_equal_wrong_types(self):
        from backend import gg_native_resources as resources
        for profile in (resources.LOW,resources.NativeResources('SERVER',256,256,256*1024**2,
                512*1024**2,8*1024**3,1024,1024*1024**2,10000,6)):
            node,process,expected=self.ready(profile)
            variants=[]
            for name in ('sdk_send_bytes_per_second','sdk_recv_bytes_per_second'):
                for wrong in (float(expected[name]),True,str(expected[name]),None):
                    bad=deepcopy(expected)
                    if wrong is None:bad.pop(name)
                    else:bad[name]=wrong
                    variants.append((name,wrong,bad))
            for name in ('pid','rpc_port','p2p_port'):
                for wrong in (float(expected[name]),True,expected[name]+1):
                    bad=deepcopy(expected);bad[name]=wrong;variants.append((name,wrong,bad))
            for name in ('consensus_signing','state_sync'):
                bad=deepcopy(expected);bad[name]=0;variants.append((name,0,bad))
            for name,wrong in (('extra',True),('schema','gg.consensus.protocol-ready.v9'),('genesis_hash','d'*64)):
                bad=deepcopy(expected);bad[name]=wrong;variants.append((name,wrong,bad))
            for name,wrong,bad in variants:
                with self.subTest(mode=profile.mode,field=name,wrong=wrong):
                    process.stdout=io.BytesIO(native._pack(bad)+b'\n')
                    resource=SimpleNamespace(node=node,process=process,check=Mock())
                    decoded=restore._read_attempt_frame(resource)
                    resource.check.assert_called_once_with()
                    with self.assertRaisesRegex(ValueError,'GG_OWNED_RESTORE_READY'):
                        restore._validated_ready_frame(node,process,decoded)
                    self.assertIsNone(node._node['_ready'])

    def test_progress_heights_are_exact_s63_strings_not_javascript_floats(self):
        node=self.node()
        for value in (0,2**53+1,2**63-1):
            restore._progress(node,'FULL_ORIGINAL_AUDIT',processed=value)
            body=restore.public_progress(node)
            self.assertEqual(body['processed_height'],str(value));self.assertIsNone(body['verified_through'])
            self.assertFalse(body['node_ready']);self.assertFalse(body['full_original_audit_completed'])
            restore._progress(node,'APPLICATION_RESTORED',processed=value,verified=value)
            body=restore.public_progress(node)
            self.assertEqual(body['verified_through'],str(value));self.assertTrue(body['full_original_audit_completed'])
        for bad in (-1,2**63,True,False,1.0,'1',float('inf')):
            for field in ('processed','verified'):
                with self.subTest(bad=bad,field=field):
                    with self.assertRaisesRegex(ValueError,'HEIGHT'):restore._progress(node,'FULL_ORIGINAL_AUDIT',**{field:bad})

    def test_ready_progress_is_scoped_to_exact_live_epoch_and_masks_stop_restart(self):
        node=self.node();restore._progress(node,'READY',processed=7,verified=7)
        self.assertTrue(restore.public_progress(node)['node_ready'])
        node._epoch_stopping=True
        stopped=restore.public_progress(node)
        self.assertEqual(stopped['phase'],'STOPPED');self.assertFalse(stopped['node_ready'])
        node._epoch_stopping=False;node._start_cancelled=lambda:True
        self.assertFalse(restore.public_progress(node)['node_ready'])
        node._start_cancelled=lambda:False;node._alive=lambda:False
        self.assertFalse(restore.public_progress(node)['node_ready'])
        node._alive=lambda:True;node._node={'process':object()}
        changed=restore.public_progress(node)
        self.assertEqual(changed['phase'],'UNAVAILABLE');self.assertFalse(changed['node_ready'])
        self.assertIsNone(changed['verified_through']);self.assertFalse(changed['full_original_audit_completed'])

    def test_progress_copy_cannot_mutate_atomic_epoch_bound_record(self):
        node=self.node();restore._progress(node,'READY',processed=9,verified=9)
        visible=restore.public_progress(node);visible['node_ready']=False;visible['verified_through']='100'
        actual=restore.public_progress(node)
        self.assertTrue(actual['node_ready']);self.assertEqual(actual['verified_through'],'9')
        self.assertFalse(actual['network_contact_asserted']);self.assertFalse(actual['certificate_is_network_liveness'])

    def test_frames_reject_duplicate_unknown_truncated_and_oversized_data(self):
        valid=native._pack({'schema':'PUBLIC-unit-frame','pid':5})+b'\n'
        self.assertEqual(restore._read_frame(SimpleNamespace(stdout=io.BytesIO(valid))),{'schema':'PUBLIC-unit-frame','pid':5})
        for raw in (valid[:-1],b'{"pid":5,"pid":6}\n',b' '+valid,b'x'*(restore.FRAME_MAX+1)+b'\n',b'[]\n'):
            with self.subTest(length=len(raw)):
                with self.assertRaises((ValueError,json.JSONDecodeError)):restore._read_frame(SimpleNamespace(stdout=io.BytesIO(raw)))
        node=self.node();process=SimpleNamespace(pid=17)
        frame={'schema':'PUBLIC-unit-frame','pid':17,'genesis_hash':node.anchor['genesis_hash'],'extra':True}
        with self.assertRaisesRegex(ValueError,'FRAME'):restore._bound(frame,node,process,'PUBLIC-unit-frame',set())

    def test_audited_frame_requires_exact_owned_pid_pin_and_unchanged_recovery_certificate(self):
        node=self.node();process=SimpleNamespace(pid=17);packet=structural_packet(node.anchor)
        frame={'schema':'gg.native.owned-archive-audited.v1','pid':17,'genesis_hash':node.anchor['genesis_hash'],
            'archive_sha256':'a'*64,'certificate':packet,'native_node_ready':False}
        digest,certificate,tip=restore._certificate_frame(frame,node,process,frame['schema'])
        self.assertEqual(digest,'a'*64);self.assertEqual(certificate,packet);self.assertEqual(tip[0],2)
        for field,value in (('pid',True),('pid',18),('genesis_hash','e'*64),('native_node_ready',True),('archive_sha256','bad')):
            bad=deepcopy(frame);bad[field]=value
            with self.assertRaises(ValueError):restore._certificate_frame(bad,node,process,frame['schema'])
        with self.assertRaisesRegex(ValueError,'INTENT_CHANGED'):
            restore._certificate_frame(frame,node,process,frame['schema'],'c'*64,packet)

    def test_ack_is_exact_same_pid_pin_digest_and_phase_without_seed(self):
        node=self.node();process=SimpleNamespace(pid=19,stdin=io.BytesIO())
        restore._ack(process,node,'a'*64,'RESTORE')
        body=json.loads(process.stdin.getvalue())
        self.assertEqual(set(body),{'schema','pid','genesis_hash','archive_sha256','phase'})
        self.assertEqual(body['pid'],19);self.assertEqual(body['phase'],'RESTORE')
        self.assertNotIn('node_seed',body);self.assertNotIn('validator_seed',body)

    def test_new_command_is_foreground_and_keeps_existing_180_second_policy(self):
        self.assertIn('protocol.replica_restore_start',FOREGROUND_COMMANDS)
        self.assertEqual(START_MAX_SECONDS,180)
        self.assertEqual(runtime.COMMANDS['protocol.replica_restore_start'],{'owner_profile','profile','settings_path','path'})
        node=self.node();restore._progress(node,'SDK_START',processed=2**53+1,verified=2**53+1)
        body={'protocol_network':{'archive_startup':restore.public_progress(node)}}
        visible=foreground_summary('protocol.replica_restore_start',body)
        self.assertEqual(visible['archive_startup']['verified_through'],str(2**53+1))
        self.assertFalse(visible['archive_startup']['node_ready']);self.assertFalse(visible['certificate_is_network_liveness'])


class RestoreRuntimeCancellationTests(unittest.TestCase):
    def test_cancel_before_existing_worker_runs_cannot_start_native_or_drop_owned_reference(self):
        # Explicit deterministic controller/thread seam, no SDK or file proof.
        service=runtime.ProtocolRuntime();pin=public_protocol_pin();owner=object();profile=SimpleNamespace(anchor=lambda:pin)
        service.owner=owner;service.replicas={'Replica':profile};started=[];closed=[];threads=[]
        class Node:
            role='REPLICA'
            def __init__(self,*args):self._node={'process':None};self.profile=profile
            def restore_start(self,path):started.append(path)
            def close(self):closed.append(self)
            def request_stop(self):pass
        class Thread:
            def __init__(self,*,target,**options):self.target=target;threads.append(self)
            def start(self):pass
        args={'owner_profile':'Owner','profile':'Replica','settings_path':'public-settings','path':'public-archive'}
        with patch.object(runtime.setup,'_owner'),patch.object(service,'_owned',return_value=owner), \
                patch.object(runtime,'read_public',return_value={}),patch.object(runtime,'validate_settings',side_effect=lambda x:x), \
                patch.object(runtime,'local_acceptance'),patch.object(runtime,'OwnedProtocolNode',Node), \
                patch.object(runtime.threading,'Thread',Thread),patch.object(service,'snapshot',return_value={}):
            service._start_replica_restore(args)
            node=service.node;service.request_stop();threads[0].target()
        self.assertEqual(started,[]);self.assertEqual(closed,[node]);self.assertIs(service.node,node)

    def test_cancel_during_construction_is_not_cleared_before_publication(self):
        service=runtime.ProtocolRuntime();pin=public_protocol_pin();owner=object();profile=SimpleNamespace(anchor=lambda:pin)
        service.owner=owner;service.replicas={'Replica':profile};closed=[]
        class Node:
            def __init__(self,*args):service.request_stop()
            def close(self):closed.append(self)
        args={'owner_profile':'Owner','profile':'Replica','settings_path':'public-settings','path':'public-archive'}
        with patch.object(runtime.setup,'_owner'),patch.object(service,'_owned',return_value=owner), \
                patch.object(runtime,'read_public',return_value={}),patch.object(runtime,'validate_settings',side_effect=lambda x:x), \
                patch.object(runtime,'local_acceptance'),patch.object(runtime,'OwnedProtocolNode',Node):
            with self.assertRaisesRegex(ValueError,'START_CANCELLED'):service._start_replica_restore(args)
        self.assertIsNone(service.node);self.assertEqual(len(closed),1);self.assertTrue(service._cancel.is_set())


class RestoreAttemptEpochTests(unittest.TestCase):
    """Declared IO/callback seams: no fake result is accepted as native proof."""
    def attempt(self):
        temporary=tempfile.TemporaryDirectory(prefix='gg-restore-epoch-policy-');self.addCleanup(temporary.cleanup)
        owner=SimpleNamespace(_lock=threading.RLock(),_closed=False,_failed=False,_db=object(),_lease=7)
        profile=SimpleNamespace(_lock=threading.RLock(),_closed=False,_failed=False,_db=object(),_lease=8,
            root=Path(temporary.name),prepare_recovery=Mock(),finish_recovery=Mock())
        child=SimpleNamespace(pid=91,terminate=Mock(),kill=Mock(),stdin=io.BytesIO(),stdout=io.BytesIO())
        node=SimpleNamespace(owner=owner,profile=profile,anchor=public_protocol_pin(),_lock=threading.RLock(),
            _node={'process':child},rpc_port=25000,role='REPLICA',node_key='9'*64,
            _process_owner=lambda:owner,_check_start=Mock(),stop=Mock(),_native_bootstrap=Mock(return_value={'node_seed':'PUBLIC-unit-seed'}))
        resource=restore._HandoffResource(node);resource.process=child;resource.epoch=node._node
        resource.rpc_port=node.rpc_port;resource.lease=SimpleNamespace(close=Mock());node._restore_resource=resource
        return node,resource

    def replace(self,node):
        other=SimpleNamespace(pid=92,terminate=Mock(),kill=Mock(),stdin=io.BytesIO(),stdout=io.BytesIO())
        node._node={'process':other};node._restore_resource=object();node.rpc_port=25001
        node._restore_progress_record=(node._node,{'phase':'PUBLIC-B-UNCHANGED'})
        return other

    def test_seedless_audit_request_does_not_request_or_serialize_private_bootstrap(self):
        node,resource=self.attempt()
        request=restore._public_request(node,Path('/PUBLIC-archive'),None)
        self.assertEqual(set(request),{'schema','archive_path','expected_node_key','genesis','genesis_hash',
            'minimum_certificate_height','minimum_certificate_block','restore_root','resources'})
        self.assertNotIn(b'node_seed',native._pack(request));self.assertNotIn(b'validator_seed',native._pack(request))
        node._native_bootstrap.assert_not_called();node.profile.prepare_recovery.assert_not_called()

    def test_lost_prepare_commit_sends_no_bootstrap_and_keeps_seed_unrequested(self):
        node,resource=self.attempt();node.profile.prepare_recovery.side_effect=ValueError('GG_PUBLIC_UNIT_COMMIT_LOST')
        with self.assertRaisesRegex(ValueError,'COMMIT_LOST'):
            restore._prepare_private_grant(resource,'a'*64,structural_packet(node.anchor))
        node._native_bootstrap.assert_not_called();self.assertEqual(resource.process.stdin.getvalue(),b'')

    def test_private_bootstrap_is_created_only_after_exact_protected_prepare(self):
        node,resource=self.attempt();events=[]
        node.profile.prepare_recovery.side_effect=lambda *args:events.append('protected-commit')
        node._native_bootstrap.side_effect=lambda fresh:(events.append('private-bootstrap') or {'node_seed':'PUBLIC-unit-seed'})
        raw=restore._prepare_private_grant(resource,'a'*64,structural_packet(node.anchor))
        self.assertEqual(events,['protected-commit','private-bootstrap'])
        grant=json.loads(raw);self.assertEqual(grant['pid'],91);self.assertEqual(grant['phase'],'RESTORE')
        self.assertEqual(grant['genesis_hash'],resource.anchor['genesis_hash'])

    def test_retarget_inside_frame_read_cannot_prepare_or_write_new_epoch(self):
        node,resource=self.attempt()
        def read(process):self.assertIs(process,resource.process);self.replace(node);return {'schema':'PUBLIC-stale-A'}
        with patch.object(restore,'_read_frame',side_effect=read):
            with self.assertRaisesRegex(ValueError,'EPOCH_CHANGED'):restore._read_attempt_frame(resource)
        node.profile.prepare_recovery.assert_not_called();node._native_bootstrap.assert_not_called()
        self.assertEqual(node._restore_progress_record[1],{'phase':'PUBLIC-B-UNCHANGED'})

    def test_retarget_inside_prepare_never_requests_private_seed_or_updates_b(self):
        node,resource=self.attempt()
        node.profile.prepare_recovery.side_effect=lambda *args:self.replace(node)
        with self.assertRaisesRegex(ValueError,'EPOCH_CHANGED'):
            restore._prepare_private_grant(resource,'a'*64,structural_packet(node.anchor))
        node._native_bootstrap.assert_not_called()
        self.assertEqual(node._restore_progress_record[1],{'phase':'PUBLIC-B-UNCHANGED'})

    def test_retarget_inside_finish_status_or_after_start_cannot_advance_ready(self):
        for phase in ('finish','status','after_start'):
            with self.subTest(phase=phase):
                node,resource=self.attempt()
                callback=Mock(side_effect=lambda *args:self.replace(node))
                with self.assertRaisesRegex(ValueError,'EPOCH_CHANGED'):restore._call_attempt(resource,callback)
                self.assertEqual(node._restore_progress_record[1],{'phase':'PUBLIC-B-UNCHANGED'})
                with self.assertRaisesRegex(ValueError,'EPOCH_CHANGED'):restore._update_progress(resource,'READY',verified=1)

    def test_old_failure_and_profile_close_stop_only_a_and_leave_b_alive(self):
        node,resource=self.attempt();other=self.replace(node)
        with patch.object(restore.termination,'process_terminal',return_value=True), \
                patch.object(restore.termination,'wait_process_terminal',return_value=0):
            resource.close()
        self.assertTrue(resource._resource_retired);node.stop.assert_not_called()
        other.terminate.assert_not_called();other.kill.assert_not_called();self.assertFalse(other.stdin.closed)
        self.assertIs(node._node['process'],other)
        self.assertEqual(node._restore_progress_record[1],{'phase':'PUBLIC-B-UNCHANGED'})

    def test_old_attempt_guard_kills_only_a_on_retarget_with_original_deadline(self):
        node,resource=self.attempt();other=self.replace(node)
        cancel=SimpleNamespace(wait=lambda seconds:False);expired=threading.Event()
        with patch.object(restore.termination,'process_terminal',return_value=False):
            restore._guard_attempt(resource,cancel,expired,float('inf'))
        resource.process.kill.assert_called_once_with();other.kill.assert_not_called();self.assertFalse(expired.is_set())


_PENDING_ACTUAL_RESTORE=None  # One explicit test owner, retained only on failed terminal proof.


class ProtectedRestoreActualSDKAcceptanceTests(unittest.TestCase):
    """Actual public command/profile/native pipe/SDK; no cryptographic stubs.

    Root provides the newly compiled candidate and genuine public fixture from
    TestFinancialOwnedRestorePublicFixtureExport. Missing inputs FAIL; this
    acceptance is never silently skipped or replaced by the policy seams above.
    """
    def test_actual_public_command_retains_same_native_pid_and_nonvoting_sdk(self):
        self.actual_owned_resource_start()

    def test_actual_server_restore_attests_runtime_same_pid_and_exact_kernel_profile(self):
        from backend.gg_native_resources import NativeResources
        # Fits the test owner's unchanged 512 MiB leaf; no test budget bypass.
        self.actual_owned_resource_start(NativeResources("SERVER",4,4,256*1024**2,
            512*1024**2,8*1024**3,1024,1024*1024**2,10000,6))

    def actual_owned_resource_start(self,selected=None):
        global _PENDING_ACTUAL_RESTORE
        fixture=os.environ.get('GG_OWNED_RESTORE_PUBLIC_FIXTURE')
        tools=os.environ.get('GG_OWNED_RESTORE_TOOLS')
        self.assertTrue(fixture and tools,'explicit current native candidate/public fixture required')
        fixture=Path(fixture).resolve(strict=True);tools=Path(tools).resolve(strict=True)
        pin=protocol.validate_pin(json.loads((fixture/'pin.json').read_bytes()))
        original=fixture/'originals.ggfin';self.assertTrue(original.is_file())
        temporary=tempfile.TemporaryDirectory(prefix='gg-actual-owned-restore-')
        stack=ExitStack();service=None;process=None;client=None;opened=[]
        try:
            root=Path(temporary.name)
            stack.enter_context(patch.object(nodes,'ROOT',root/'nodes'))
            stack.enter_context(patch.object(observers,'ROOT',root/'observers'))
            # A path redirect to the independently manifested actual candidate,
            # not a verifier/process/SDK/cryptography implementation seam.
            stack.enter_context(patch.object(native,'TOOLS',tools))
            stack.enter_context(vault.session('PUBLIC disposable actual restore acceptance password'))
            owner=nodes.NodeProfile.create('ActualOwner',configuration())
            opened.append(owner)
            member=observers.ObserverProfile.create_for_protocol('ActualReplica',owner,pin,label='Actual isolated restore replica')
            opened.append(member)
            public_key=member.native_node_signer().pubkey().hex()
            member.close();owner.close()
            def free_port():
                with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as listener:
                    listener.bind(('127.0.0.1',0));return listener.getsockname()[1]
            p2p,peer=free_port(),free_port()
            while peer==p2p:peer=free_port()
            settings={'listen_host':'127.0.0.1','max_inbound':0,'max_outbound':1,'p2p_port':p2p,
                'peers':[{'host':'127.0.0.1','id':'1'*40,'port':peer}]}
            if selected is not None:settings['resources']=selected.wire()
            settings_path=root/'public-settings.json';settings_path.write_bytes(native._pack(settings))
            service=runtime.ProtocolRuntime();deadline=time.monotonic()+START_MAX_SECONDS
            service.dispatch('protocol.replica_restore_start',{'owner_profile':'ActualOwner','profile':'ActualReplica',
                'settings_path':str(settings_path),'path':str(original)})
            node=service.node;seen_ready=False
            while time.monotonic()<deadline:
                with node._lock:
                    resource=getattr(node,'_restore_resource',None)
                    if resource is not None and resource.current():
                        if process is None:process=resource.process
                        self.assertIs(resource.process,process);self.assertIs(node._node['process'],process)
                progress=node.restore_progress()
                if progress and progress['phase']=='READY':seen_ready=True;break
                thread=service._thread
                if thread is not None and not thread.is_alive():break
                time.sleep(.02)
            self.assertTrue(seen_ready,'actual protected restore/start failed: '+service._error)
            self.assertIsNotNone(process);self.assertFalse(restore.termination.process_terminal(process))
            self.assertEqual(node.profile.native_node_signer().pubkey().hex(),public_key)
            self.assertEqual(node.profile._body['schema'],observers.PUBLIC_RECOVERY_SCHEMA)
            self.assertTrue(node.profile._recovery_intent()['complete'])
            self.assertEqual(node._status()['validator_info']['voting_power'],'0')
            self.assertEqual(node.role,'REPLICA')
            from backend.gg_native_resources import resolve
            expected=resolve(selected)
            self.assertEqual(node._node['_ready']['resources'],expected.ready())
            self.assertEqual(node._lease.facts['resource_profile'],expected.wire())
            self.assertIsNone(node._lease.facts['cpu_seconds'])
            self.assertEqual(node._lease.facts['group']['resource_profile'],expected.wire())
            self.assertEqual(node._restore_resource.resources,expected)
            observed=node.resource_observation()
            self.assertTrue(observed['native_attested']);self.assertEqual(observed['state'],'APPLIED')
            self.assertEqual(observed['applied'],expected.ready())
            relay_profile=observers.ObserverProfile.create_for_protocol('ActualTransportClient',node.owner,pin,label='Actual bounded transport client')
            opened.append(relay_profile);relay_port=free_port()
            service.dispatch('protocol.relay_start',{'host':'127.0.0.1','port':relay_port,
                'allowed_peer_keys':[relay_profile.native_node_signer().pubkey().hex()]})
            client=transport.ProofTransportClient(relay_profile.native_node_signer(),pin,
                {'host':'127.0.0.1','port':relay_port,'server_key':node.node_key},
                binary=node.binary,stamp=node._stamp,owner=node.owner,profile=relay_profile,resources=expected)
            # The saved certificate attests restored history and does not assert liveness.
            with self.assertRaisesRegex(ValueError,'^GG_PROTOCOL_NO_FRESH_CERTIFICATE$'):
                client.call({'method':'state'})
            certificate=node.profile.public_certificate();height=certificate['state']['height']
            selector={'namespace':'producers','key':pin['genesis']['financial_dag']['producers'][0]}
            proof=client.call({'method':'query','path':'/gg/financial-dag/registry-proof',
                'height':height,'selector':selector})
            packet={**certificate,'financial_registry':proof}
            protocol.verify_selected(packet,pin,registry=selector,binary=node.binary,stamp=node._stamp)
            for pipe in (client,service._relay):
                observation=pipe.resource_observation()
                self.assertEqual(observation['state'],'APPLIED')
                self.assertEqual(observation['applied'],expected.ready())
                self.assertEqual(observation['applied_transport_budget'],expected.transport())
                self.assertFalse(observation['full_sdk_node_running'])
            self.assertEqual(client.ready['limits'],expected.transport())
            self.assertEqual(service.snapshot()['protocol_network']['resources']['applied'],expected.ready())
            self.assertEqual(service.snapshot()['protocol_network']['proof_relay']['resources']['applied_transport_budget'],expected.transport())
            client.close();client=None;service.dispatch('protocol.relay_stop',{})
            history=node._query('/gg/protocol/local-history-status')
            certificate=node.profile.public_certificate();height=certificate['state']['height']
            self.assertEqual(history['state'],'READY');self.assertEqual(history['mode'],'FULL_REPLAY')
            self.assertEqual(history['verified_through'],str(height));self.assertEqual(history['retained_through'],str(height))
            self.assertEqual(progress['verified_through'],str(height));self.assertTrue(progress['node_ready'])
            self.assertFalse(progress['network_contact_asserted']);self.assertFalse(progress['certificate_is_network_liveness'])
            self.assertIs(node._node['process'],process)
            service.stop_node()
            self.assertTrue(restore.termination.process_terminal(process))
            stopped=node.restore_progress();self.assertFalse(stopped['node_ready']);self.assertNotEqual(stopped['phase'],'READY')
        finally:
            try:
                if client is not None:client.close()
                if service is not None:service.close()
                if process is not None and not restore.termination.process_terminal(process):raise pipes.NativePipeStopPending()
                for profile in reversed(opened):profile.close()
            except BaseException:
                temporary._finalizer.detach()
                _PENDING_ACTUAL_RESTORE=(service,process,client,stack,temporary,tuple(opened))
                raise
            stack.close();temporary.cleanup()
