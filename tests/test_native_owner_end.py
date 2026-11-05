"""Source1 owned lifetime signals precede blocked database teardown.

Real protected owners and real contained sleeping children; native RPC/SDK
identity verification is explicitly mocked. No consensus proof is claimed.
"""
from contextlib import ExitStack
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from backend import gg_consensus as native,gg_observer_profile as observers
from backend import gg_consensus_node as validators,gg_observer_node as observer_nodes
from backend import gg_native_process_policy as policy,gg_testnet_process as limits
from tests import test_lan_validator_runtime as fixture


class NativeOwnerEndTests(unittest.TestCase):
    cleanup=fixture.ValidatorRuntimeTests.cleanup
    manager=fixture.ValidatorRuntimeTests.manager
    network=fixture.ValidatorRuntimeTests.network

    def setUp(self):
        fixture.ValidatorRuntimeTests.setUp(self)
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(observers,'ROOT',Path(self.temp.name)/'observers'))
        binary=Path(self.temp.name)/'not-an-SDK-public-policy-seam';binary.write_bytes(b'fixture')
        stamp=(binary.stat().st_size,binary.stat().st_mtime_ns)
        self.stack.enter_context(patch.object(native,'_installed_binary',return_value=binary))
        self.stack.enter_context(patch.object(native,'_validate_binary_at',return_value=stamp))

    def sleeper(self,node):
        if os.name!='nt':
            from backend.gg_posix_native import launch
            # A public sleeping child must satisfy the production session and
            # rlimit readback, without changing any ownership/cancellation gate.
            descriptor,name=tempfile.mkstemp(prefix='public-owner-sleeper-',suffix='.py',dir=self.temp.name)
            wrapper=Path(name)
            with os.fdopen(descriptor,'w',encoding='utf-8',newline='\n') as stream:
                stream.write('#!'+sys.executable+'\nimport time\ntime.sleep(30)\n')
            wrapper.chmod(0o700)
            process=launch(wrapper,cwd=node.profile.root,env=os.environ.copy())
        else:
            process=subprocess.Popen([getattr(sys,'_base_executable',sys.executable),'-I','-c','import time;time.sleep(30)'],
                stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        self.addCleanup(limits._stop_owned,process)
        node._lease=policy.contain_owned_native(process,node._process_owner());node._node={'process':process,'_ready':None}
        node._epoch_stopping=False;return process

    def validator(self,manager,name):
        profile=manager._validator_profiles[name]
        profile.bind_anchor(manager._peer._bundle,manager._peer._trusted)
        node=validators.OwnedValidator(profile,manager._peer);self.addCleanup(node.close);return node

    def ended_while_blocked(self,owner,node,child,other=None):
        errors=[];worker=None
        node._public_packet={'public_historical_policy_fixture':True}
        self.assertIsNotNone(node.cached_certificate())
        def close():
            try:owner.close()
            except Exception as error:errors.append(type(error).__name__)
        with owner._lock:
            worker=threading.Thread(target=close);worker.start();deadline=time.monotonic()+2
            while not policy.owner_ended(owner):
                self.assertLess(time.monotonic(),deadline);time.sleep(.005)
            self.assertFalse(owner._closed);self.assertIsNotNone(owner._db)
            start=time.monotonic();self.assertTrue(node._owner_stopped());self.assertEqual(node.snapshot()['state'],'CLOSED')
            self.assertLess(time.monotonic()-start,.2)
            self.assertIsNone(node.cached_certificate())
            with self.assertRaisesRegex(ValueError,'START_CANCELLED'):node._check_start()
            with self.assertRaisesRegex(ValueError,'PROOF_UNAVAILABLE'):node._check_proof_epoch()
            # The transport gate must reject before listener probing, network I/O
            # or accepting another native economic submission.
            with patch.object(node,'_owned',side_effect=AssertionError('listener probe after owner end')):
                with self.assertRaises(ValueError):node._rpc('status')
                with self.assertRaises(ValueError):node._rpc('broadcast_tx_sync',b'public fixture bytes')
            if os.name=='nt':child.wait(timeout=3)
            if other is not None:
                self.assertFalse(other._owner_stopped());self.assertTrue(other._alive())
        worker.join(3);self.assertFalse(worker.is_alive());self.assertEqual(errors,[])

    def test_validator_owner_end_is_immediate_even_while_owner_database_lock_is_held(self):
        first,second,phone,_=self.network()
        node=self.validator(first,'Win1');other=self.validator(second,'Lin1')
        child=self.sleeper(node);self.sleeper(other)
        self.ended_while_blocked(first._peer._profile,node,child,other)
        self.assertTrue(node.snapshot()['owner_stopped']);self.assertFalse(node.snapshot()['certificate_is_network_liveness'])

    def test_observer_owner_end_invalidates_live_execution_before_database_teardown(self):
        first,second,phone,_=self.network()
        phone.dispatch('lan.observer_create',{'profile':'Full'})
        node=observer_nodes.OwnedObserver(phone._observers.profiles['Full'],phone._peer);self.addCleanup(node.close)
        child=self.sleeper(node)
        self.ended_while_blocked(phone._peer._profile,node,child)
        view=node.snapshot();self.assertTrue(view['owner_stopped'])
        self.assertFalse(view['native_connection']['connected']);self.assertFalse(view['local_state_read_from_owned_sdk'])

    def test_failed_real_owner_store_cannot_continue_to_act_as_validator(self):
        first,_,_,_=self.network();node=self.validator(first,'Win1')
        owner=first._peer._profile
        owner._failed=True
        try:
            self.assertTrue(node._owner_stopped())
            with self.assertRaisesRegex(ValueError,'START_CANCELLED'):node._check_start()
        finally:owner._failed=False

    def test_closed_native_profile_stops_its_child_without_ending_owner_or_sibling(self):
        first,_,_,_=self.network();node=self.validator(first,'Win1');other=self.validator(first,'Win2')
        child=self.sleeper(node);outside=self.sleeper(other);cancel=threading.Event()
        worker=threading.Thread(target=node._watch_owner,args=(cancel,),daemon=True);worker.start()
        try:
            node.profile.close()
            with patch.object(node,'_owned',side_effect=AssertionError('listener probe after profile close')):
                with self.assertRaisesRegex(ValueError,'OWNER_STOPPED'):node._rpc('broadcast_tx_sync',b'public fixture')
            with self.assertRaisesRegex(ValueError,'PROOF_UNAVAILABLE'):node._check_proof_epoch()
            worker.join(3);self.assertFalse(worker.is_alive());self.assertIsNotNone(child.poll())
            self.assertIsNone(outside.poll());self.assertFalse(first._peer._profile._closed)
            self.assertFalse(policy.owner_ended(first._peer._profile));self.assertFalse(other._owner_stopped())
        finally:cancel.set();worker.join(3)


if __name__=='__main__':unittest.main()
