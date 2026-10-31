"""Real signed socket authentication across the observed 1.8s TCP delay."""
import socket
import threading
import time
import unittest
from unittest.mock import patch

from backend import gg_lan_dag as lan


class RetransmissionAuthenticationTests(unittest.TestCase):
    def test_measured_1800ms_gap_no_longer_closes_a_valid_signed_handshake(self):
        client=lan.LanDagPeer('owned-client');server=lan.LanDagPeer('owned-server')
        self.addCleanup(client.stop);self.addCleanup(server.stop)
        client._network=server._network='a'*64
        client._roster={server.public_key:{'host':'127.0.0.1','port':16120}}
        server._roster={client.public_key:{'host':'127.0.0.1','port':16121}}
        left,right=socket.socketpair();self.addCleanup(left.close);self.addCleanup(right.close)
        result=[];errors=[];deadline=time.monotonic()+4
        def respond():
            try:
                hello,_size=server._read(right,lan.MAX_INVITE,deadline=deadline)
                time.sleep(1.8)
                result.append(server._server_auth(right,hello,'127.0.0.1',deadline))
            except Exception as error:errors.append(error)
        thread=threading.Thread(target=respond,daemon=True);thread.start();self.addCleanup(thread.join,1)
        began=time.monotonic()
        channel=client._client_auth(left,server.public_key,deadline)
        thread.join(1)
        self.assertFalse(thread.is_alive());self.assertEqual(errors,[])
        self.assertGreaterEqual(time.monotonic()-began,1.8)
        self.assertLess(time.monotonic()-began,3.5)
        self.assertEqual(result,[(client.public_key,channel)])

    def test_slow_peer_still_obeys_the_earlier_whole_work_deadline(self):
        left,right=socket.socketpair();self.addCleanup(left.close);self.addCleanup(right.close)
        began=time.monotonic()
        with patch.object(lan,'IO_TIMEOUT',.02):
            with self.assertRaisesRegex(ValueError,'GG_LAN_READ_DEADLINE'):
                lan._receive(left,lan.MAX_FRAME,deadline=began+.08)
        self.assertLess(time.monotonic()-began,.3)


if __name__=='__main__':unittest.main()
