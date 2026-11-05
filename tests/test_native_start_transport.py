"""Real pipe/process/store fault paths with a public fake-SDK policy boundary.

The child receives only public fixture bytes, never signer material. It checks
the protected profile's public startup flag before emitting a fixture readiness
line. This is transport/lifecycle evidence, not real SDK or consensus evidence.
"""
from copy import deepcopy
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from backend import gg_consensus_process as transport,gg_consensus as native
from backend.gg_consensus_process import OwnedNativeRPC
from tests import test_native_observer_profile as fixture

CHILD=r'''
import json,os,sqlite3,sys,time
from pathlib import Path
if sys.argv[1]=='blocked':time.sleep(30);raise SystemExit(1)
body=json.loads(sys.stdin.buffer.read(65537));root=Path(body['root']);profile=root.parent
dbfile=next(profile.glob('*.sqlite3'))
with sqlite3.connect(dbfile.resolve().as_uri()+'?mode=ro&immutable=1',uri=True) as db:
 record=json.loads(db.execute('SELECT record FROM state').fetchone()[0]);assert record['body']['native_started'] is True
root.mkdir(exist_ok=True);(root/'public-transport-fixture').write_text('claimed before input',encoding='utf-8')
selected=body['resources']
# Public policy seam, not an SDK claim. Actual Go attestation is tested by native acceptance.
resources={'schema':'gg.native.resources-ready.v1','profile':selected,'go_max_procs':selected['go_max_procs'],
 'go_heap_bytes':selected['go_heap_bytes'],'verify_workers':selected['verify_workers'],
 'effective_verify_workers':min(selected['go_max_procs'],selected['verify_workers']),
 'commit_wait_ms':10 if selected['mode']=='SERVER' else 100}
ready={'pid':os.getpid(),'rpc_port':body['rpc_port'],'p2p_port':body['p2p_port'],'claimed_before_input':True,'resources':resources}
rate=selected['go_max_procs']*(64*1024**2) if selected['mode']=='SERVER' else 5120000
ready.update(sdk_send_bytes_per_second=rate,sdk_recv_bytes_per_second=rate)
if sys.argv[1]=='missing-profile':ready.pop('resources')
if sys.argv[1]=='wrong-profile':ready['resources']['go_max_procs']+=1
print(json.dumps(ready),flush=True)
time.sleep(30)
'''


class PublicTransportHarness(OwnedNativeRPC):
    def __init__(self,profile,peer,temp,mode='normal',size=1):
        self.profile=profile;self.peer=peer;self.mode=mode;self.size=size;self.cancelled=threading.Event()
        self._lock=threading.RLock();self._closed=False;self._fault='';self._node={'process':None,'_ready':None}
        self._lease=None;self._connection=None;self._monitor_cancel=None;self._epoch_stopping=True;self.rpc_port=None
        self.binary=Path(temp)/'public-boundary-not-SDK';self.binary.write_bytes(b'policy seam only')
        stat=self.binary.stat();self._stamp=(stat.st_size,stat.st_mtime_ns)
        self.member={'host':'127.0.0.1','p2p_port':profile.public_grant()['body']['p2p_port'] if hasattr(profile,'public_grant') else profile.public_invite()['body']['p2p_port']}
        self.anchor=profile.anchor();self.children=[]
    def _owner_stopped(self):return self.cancelled.is_set() or self.peer._cancel.is_set()
    def _process_owner(self):return self.peer
    def _native_bootstrap(self,fresh):
        return {'expected_fresh':fresh,'public_fixture':'x'*self.size,'root':str(self.profile.root/'native'),
            'rpc_port':self.rpc_port,'p2p_port':self.member['p2p_port']}
    def _native_ready(self,process):
        return {'pid':process.pid,'rpc_port':self.rpc_port,'p2p_port':self.member['p2p_port'],'claimed_before_input':True}
    def _spawn_native(self):
        if os.name!='nt':
            from backend.gg_posix_native import launch
            # The public Python fixture must satisfy the SAME session/rlimit
            # readback as the SDK. Embed its public argv mode in an owned
            # executable, without widening the production launch-argument guard.
            descriptor,name=tempfile.mkstemp(prefix='public-native-transport-',suffix='.py',dir=self.binary.parent)
            wrapper=Path(name)
            with os.fdopen(descriptor,'w',encoding='utf-8',newline='\n') as stream:
                stream.write('#!'+sys.executable+'\nimport sys\nsys.argv=[sys.argv[0],'+repr(self.mode)+']\n'+CHILD)
            wrapper.chmod(0o700)
            process=launch(wrapper,cwd=self.profile.root,env=os.environ.copy())
        else:
            process=subprocess.Popen([getattr(sys,'_base_executable',sys.executable),'-I','-c',CHILD,self.mode],
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,cwd=self.profile.root,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        self.children.append(process);return process
    def _owned(self):return self._alive() and self._node.get('_ready') is not None
    def _status(self):return {'public_fixture_readiness_only':True}
    def snapshot(self):return {'public_transport_fixture':True,'owned_process':self._alive()}
    def start(self):
        with self._lock:return self._launch_native()
    def close(self):self.stop();self._closed=True


class NativeStartTransportTests(unittest.TestCase):
    cleanup=fixture.NativeObserverProfileTests.cleanup
    profile=fixture.NativeObserverProfileTests.profile
    network=fixture.NativeObserverProfileTests.network
    observer=fixture.NativeObserverProfileTests.observer
    def setUp(self):fixture.NativeObserverProfileTests.setUp(self)
    def cases(self):
        profile=self.validators[0];profile.bind_anchor(self.bundle,self.peers[0].public_key)
        return ((profile,self.peers[0]),(self.observer(),self.peers[2]))
    def node(self,case,**options):
        node=PublicTransportHarness(*case,self.temp.name,**options);self.addCleanup(node.close);return node

    def test_durable_claim_precedes_real_pipe_input_and_successful_stop_closes_handles(self):
        for case in self.cases():
            node=self.node(case);view=node.start();self.assertTrue(view['owned_process'])
            process=node.children[-1];self.assertTrue(node.profile.snapshot()['native_started'])
            self.assertEqual((node.profile.root/'native/public-transport-fixture').read_text(encoding='utf-8'),'claimed before input')
            node.stop();self.assertIsNotNone(process.poll());self.assertTrue(process.stdin.closed);self.assertTrue(process.stdout.closed)

    def test_owned_listener_status_cannot_bypass_missing_or_mismatched_new_low_attestation(self):
        for case in self.cases():
            node=self.node(case,mode='missing-profile')
            # A real TCP ownership/status result is insufficient without the
            # exact frame, including on Windows where socket inspection works.
            with patch.object(node,'_owned',return_value=True),patch.object(transport,'START_SECONDS',.4):
                with self.assertRaisesRegex(ValueError,'READY_TIMEOUT'):node.start()
            self.assertTrue(node.profile.snapshot()['native_started'])
            self.assertIsNotNone(node.children[-1].poll())
            node.mode='wrong-profile'
            with patch.object(node,'_owned',return_value=True),patch.object(transport,'START_SECONDS',.4):
                with self.assertRaisesRegex(ValueError,'READY_TIMEOUT'):node.start()
            self.assertIsNotNone(node.children[-1].poll())

    def test_serialization_limit_or_error_and_Popen_failure_take_no_durable_intent(self):
        for case in self.cases():
            node=self.node(case,size=65536)
            with self.assertRaisesRegex(ValueError,'BOOTSTRAP_LIMIT'):node.start()
            self.assertFalse(node.profile.snapshot()['native_started']);self.assertFalse(node.children)
            node.size=1
            with patch.object(native,'_pack',side_effect=ValueError('GG_FIXTURE_ENCODING_FAILURE')):
                with self.assertRaisesRegex(ValueError,'ENCODING_FAILURE'):node.start()
            with patch.object(node,'_spawn_native',side_effect=OSError('public fixture spawn failure')):
                with self.assertRaises(OSError):node.start()
            self.assertFalse(node.profile.snapshot()['native_started']);self.assertFalse((node.profile.root/'native').exists())

    def test_containment_failure_never_claims_and_same_profile_can_retry(self):
        for case in self.cases():
            node=self.node(case);before=deepcopy(node.profile._body)
            with patch.object(transport,'contain_owned_native',side_effect=RuntimeError('GG_FIXTURE_CONTAINMENT_FAILURE')):
                with self.assertRaisesRegex(RuntimeError,'CONTAINMENT_FAILURE'):node.start()
            self.assertIsNotNone(node.children[-1].poll());self.assertEqual(node.profile._body,before)
            self.assertTrue(node.start()['owned_process'])

    def test_cancellation_after_claim_before_write_releases_only_known_unlaunched_attempt(self):
        for case in self.cases():
            node=self.node(case);before=deepcopy(node.profile._body);commit=node.profile._commit
            def cancel_after_commit():commit();node.cancelled.set()
            with patch.object(node.profile,'_commit',side_effect=cancel_after_commit):
                with self.assertRaisesRegex(ValueError,'START_CANCELLED'):node.start()
            self.assertEqual(node.profile._body,before);self.assertIsNotNone(node.children[-1].poll())
            self.assertFalse((node.profile.root/'native').exists());node.cancelled.clear()
            self.assertTrue(node.start()['owned_process'])

    def test_partial_pipe_write_keeps_start_intent_and_missing_history_fails_closed(self):
        for case in self.cases():
            node=self.node(case,mode='blocked');spawn=node._spawn_native
            class Partial:
                def __init__(self,stream):self.stream=stream
                def write(self,raw):self.stream.write(raw[:8]);self.stream.flush();raise OSError('public fixture unknown partial input')
                def close(self):self.stream.close()
                @property
                def closed(self):return self.stream.closed
            def partial():
                process=spawn();process.stdin=Partial(process.stdin);return process
            with patch.object(node,'_spawn_native',side_effect=partial):
                with self.assertRaises(OSError):node.start()
            self.assertTrue(node.profile.snapshot()['native_started']);self.assertIsNotNone(node.children[-1].poll())
            with self.assertRaisesRegex(ValueError,'HISTORY_MISSING'):node.start()

    def test_start_deadline_bounds_real_blocked_pipe_and_retains_ambiguous_intent(self):
        for case in self.cases():
            node=self.node(case,mode='blocked',size=60000);started=time.monotonic()
            with patch.object(transport,'START_SECONDS',.3):
                with self.assertRaisesRegex(ValueError,'READY_TIMEOUT'):node.start()
            self.assertLess(time.monotonic()-started,2)
            self.assertTrue(node.profile.snapshot()['native_started']);self.assertIsNotNone(node.children[-1].poll())
            self.assertTrue(node.children[-1].stdin.closed);self.assertTrue(node.children[-1].stdout.closed)

    def test_start_deadline_during_known_commit_return_stops_child_and_releases_no_input_intent(self):
        for case in self.cases():
            node=self.node(case);before=deepcopy(node.profile._body);commit=node.profile._commit;calls=[0]
            def slow_return():
                calls[0]+=1;commit()
                if calls[0]==1:time.sleep(.4)
            with patch.object(transport,'START_SECONDS',.15),patch.object(node.profile,'_commit',side_effect=slow_return):
                with self.assertRaisesRegex(ValueError,'READY_TIMEOUT'):node.start()
            self.assertEqual(node.profile._body,before);self.assertIsNotNone(node.children[-1].poll())
            self.assertFalse((node.profile.root/'native').exists())

    def test_late_start_completion_cannot_publish_success_after_child_deadline(self):
        for case in self.cases():
            node=self.node(case)
            with patch.object(transport,'START_SECONDS',.3),patch.object(node,'_after_native_start',side_effect=lambda:time.sleep(.45)):
                with self.assertRaisesRegex(ValueError,'READY_TIMEOUT'):node.start()
            self.assertIsNotNone(node.children[-1].poll());self.assertTrue(node.profile.snapshot()['native_started'])
            self.assertTrue((node.profile.root/'native/public-transport-fixture').is_file())

    def test_post_readiness_publication_failure_is_not_retried_or_relabelled_as_timeout(self):
        for case in self.cases():
            node=self.node(case)
            with patch.object(node,'_after_native_start',side_effect=OSError('public fixture publication failure')) as publish:
                with self.assertRaisesRegex(OSError,'publication failure'):node.start()
            self.assertEqual(publish.call_count,1);self.assertIsNotNone(node.children[-1].poll())
            self.assertTrue(node.profile.snapshot()['native_started']);self.assertTrue((node.profile.root/'native').is_dir())

    def test_priority_cancellation_unblocks_pipe_without_waiting_for_work_lock(self):
        for case in self.cases():
            node=self.node(case,mode='blocked',size=60000);entered=threading.Event();errors=[];spawn=node._spawn_native
            class Observed:
                def __init__(self,stream):self.stream=stream
                def write(self,raw):entered.set();return self.stream.write(raw)
                def close(self):self.stream.close()
            def observe():
                process=spawn();process.stdin=Observed(process.stdin);return process
            def start():
                try:node.start()
                except ValueError as error:errors.append(str(error))
            with patch.object(node,'_spawn_native',side_effect=observe):
                worker=threading.Thread(target=start);worker.start();self.assertTrue(entered.wait(3))
                now=time.monotonic();node.cancelled.set();worker.join(2)
                self.assertFalse(worker.is_alive());self.assertLess(time.monotonic()-now,1)
            self.assertEqual(errors,['GG_VALIDATOR_START_CANCELLED'])
            self.assertTrue(node.profile.snapshot()['native_started']);self.assertIsNotNone(node.children[-1].poll())

    def test_cleanup_stop_flag_does_not_relabel_an_unrelated_pipe_failure_as_cancel(self):
        case=self.cases()[0]
        class StopFlagHarness(PublicTransportHarness):
            internal_stop=False
            def _start_cancelled(self):return self.internal_stop or super()._start_cancelled()
            def stop(self):self.internal_stop=True;return super().stop()
        node=StopFlagHarness(*case,self.temp.name,mode='blocked');self.addCleanup(node.close);spawn=node._spawn_native
        class Broken:
            def __init__(self,stream):self.stream=stream
            def write(self,raw):raise OSError('public fixture pipe failure before cleanup')
            def close(self):self.stream.close()
        def broken():
            process=spawn();process.stdin=Broken(process.stdin);return process
        with patch.object(node,'_spawn_native',side_effect=broken):
            with self.assertRaisesRegex(OSError,'pipe failure before cleanup'):node.start()
        self.assertTrue(node.internal_stop);self.assertTrue(node.profile.snapshot()['native_started'])


if __name__=='__main__':unittest.main()
