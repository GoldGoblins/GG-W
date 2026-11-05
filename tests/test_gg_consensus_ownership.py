"""Android listener visibility never authorizes a foreign or changed child."""
from types import SimpleNamespace
import http.client
import threading
import time
import unittest
from unittest.mock import Mock,patch
import psutil
from backend import gg_consensus as node
from backend.gg_consensus_process import OwnedNativeRPC


class OwnedListenerTests(unittest.TestCase):
    def check(self,failure,*,platform='posix',same=True,alive=True,stamp=True,ready=True):
        process=Mock(pid=12345);process.poll.return_value=None if alive else 1
        owned={'process':process,'rpc_port':51001,'p2p_port':51002,'_ready':
               {'process':process if same else object()} if ready else None}
        probe=Mock();probe.net_connections.side_effect=failure
        binary=Mock();binary.stat.return_value=SimpleNamespace(st_size=100,st_mtime_ns=200)
        with patch.object(node,'_nodes',[owned]),patch.object(node.psutil,'Process',return_value=probe),\
             patch.object(node,'BINARY',binary),patch.object(node,'_binary_stamp',(100,200) if stamp else (100,201)),\
             patch.object(node,'os',SimpleNamespace(name=platform)):
            return node._owned(0),owned

    def test_denied_visibility_accepts_only_same_live_attested_unchanged_owned_child(self):
        for failure in (psutil.AccessDenied(12345),PermissionError()):
            result,row=self.check(failure)
            self.assertTrue(result);self.assertEqual(row['ownership_provider'],'OWNED_CHILD_READY_PIPE')
            for changes in ({'platform':'nt'},{'same':False},{'alive':False},{'stamp':False},{'ready':False}):
                with self.subTest(changes=changes):self.assertFalse(self.check(failure,**changes)[0])

    def test_process_disappearance_or_unrelated_io_never_uses_attestation(self):
        for failure in (psutil.NoSuchProcess(12345),OSError('unrelated failure'),psutil.ZombieProcess(12345)):
            self.assertFalse(self.check(failure)[0])

    def test_normal_kernel_listener_mismatch_never_uses_attestation(self):
        process=Mock(pid=12345);process.poll.return_value=None
        row={'process':process,'rpc_port':51001,'p2p_port':51002,'_ready':{'process':process}}
        for listeners in ([],[SimpleNamespace(status=psutil.CONN_LISTEN,laddr=SimpleNamespace(ip='0.0.0.0',port=51001))]):
            with patch.object(node,'_nodes',[row]),patch.object(node.psutil,'Process') as probe:
                probe.return_value.net_connections.return_value=listeners
                self.assertFalse(node._owned(0))


class OwnedRPCStopRaceTests(unittest.TestCase):
    """Controlled thread interleavings; no listener, node or process is started."""
    def controller(self):
        class Controller(OwnedNativeRPC):
            def __init__(self):
                self._closed=False;self.profile=SimpleNamespace(_closed=False,_failed=False)
                self._stop=threading.Event();self._connection=None;self.rpc_port=45123
                self._unchanged=Mock();self._owned=Mock(return_value=True)
            def _owner_stopped(self):return self._stop.is_set()
            def request_stop(self):self._stop.set();self._drop_connection()
        return Controller()

    def interleave(self,phase,*,replacement=False):
        entered=threading.Event();release=threading.Event();controller=self.controller();outcomes=[]
        class Connection:
            sock=None
            def __init__(self):self.closed=False;self.requests=0;self.responses=0
            @property
            def timeout(self):return 3
            @timeout.setter
            def timeout(self,value):
                if phase=='prepare':
                    entered.set()
                    if not release.wait(2):raise TimeoutError('PUBLIC test preparation barrier')
            def request(self,*args,**kwargs):
                self.requests+=1
                if phase=='request':
                    entered.set()
                    if not release.wait(2):raise TimeoutError('PUBLIC test request barrier')
                    if self.closed:raise AttributeError('PUBLIC simulated HTTP socket closed during request')
            def getresponse(self):self.responses+=1;raise AssertionError('cancelled request obtained response')
            def close(self):self.closed=True
        connection=Connection();controller._connection=connection
        def observer():
            try:controller._rpc('status');outcomes.append('unexpected success')
            except (ValueError,OSError,http.client.HTTPException) as error:outcomes.append((type(error),str(error)))
            except BaseException as error:outcomes.append(('unexpected exception',type(error).__name__))
        thread=threading.Thread(target=observer,name='PUBLIC controlled RPC observer');thread.start()
        newer=None
        try:
            self.assertTrue(entered.wait(1))
            before=time.monotonic();controller.request_stop();self.assertLess(time.monotonic()-before,.5)
            self.assertTrue(connection.closed)
            if replacement:
                newer=Connection();controller._connection=newer;controller._stop.clear()
        finally:release.set();thread.join(2)
        self.assertFalse(thread.is_alive());self.assertEqual(outcomes,[(ValueError,'GG_NATIVE_OWNER_STOPPED')])
        self.assertEqual(connection.requests,0 if phase=='prepare' else 1);self.assertEqual(connection.responses,0)
        controller._unchanged.assert_called_once();controller._owned.assert_called_once()
        if replacement:
            self.assertIs(controller._connection,newer);self.assertFalse(newer.closed);controller._drop_connection()
        else:self.assertIsNone(controller._connection)

    def test_stop_drops_work_connection_during_request_preparation_without_dead_observer(self):self.interleave('prepare')

    def test_stop_interrupts_http_internal_close_race_with_sanitized_owner_boundary(self):self.interleave('request')

    def test_interrupted_old_request_never_closes_a_replacement_connection(self):self.interleave('request',replacement=True)

    def test_listener_ownership_is_still_required_before_work_connection(self):
        controller=self.controller();controller._owned.return_value=False
        with patch('backend.gg_consensus_process.http.client.HTTPConnection',side_effect=AssertionError('foreign listener used')):
            with self.assertRaisesRegex(ValueError,'GG_VALIDATOR_LISTENER_NOT_OWNED'):controller._rpc('status')


if __name__=='__main__':unittest.main()
