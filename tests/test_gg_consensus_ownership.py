"""Android listener visibility never authorizes a foreign or changed child."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
import psutil
from backend import gg_consensus as node


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


if __name__=='__main__':unittest.main()
