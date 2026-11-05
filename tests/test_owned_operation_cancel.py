"""Real owned TCP sockets: cancellation does not close another operation."""
import socket
import threading
import time
import unittest

from tests.test_lan_consensus_anchor import paired_peers,member_invites


class OwnedOperationCancelTests(unittest.TestCase):
    def setUp(self):
        self.peers=paired_peers(self);invites=member_invites(self.peers)
        bundle=self.peers[0].create_session([peer.public_invite() for peer in self.peers],
            enable_dag_transactions=True,consensus_invites=invites)
        for peer in self.peers:peer.install_session(bundle,_start_gossip=False)

    def test_cancelled_owned_read_exits_promptly_without_closing_other_socket(self):
        sender=self.peers[2];receiver=self.peers[0];first=threading.Event();second=threading.Event()
        entered=threading.Event();done=threading.Event();errors=[]
        def pending():
            try:
                with sender._connection(receiver.public_key,deadline=time.monotonic()+5,cancel=first) as sock:
                    entered.set();sender._read(sock,4096,deadline=time.monotonic()+5)
            except (OSError,ValueError,EOFError) as error:errors.append(type(error).__name__)
            finally:done.set()
        worker=threading.Thread(target=pending);worker.start()
        self.addCleanup(worker.join,2)
        self.assertTrue(entered.wait(1))
        with sender._connection(receiver.public_key,deadline=time.monotonic()+5,cancel=second) as other:
            start=time.monotonic();sender.cancel_operation(first)
            self.assertTrue(done.wait(.5));self.assertLess(time.monotonic()-start,.6)
            self.assertFalse(second.is_set());self.assertGreaterEqual(other.fileno(),0)
            other.setsockopt(socket.SOL_SOCKET,socket.SO_KEEPALIVE,1)
        worker.join(1);self.assertTrue(errors);self.assertFalse(worker.is_alive())
        self.assertFalse(sender._socket_cancels)

    def test_circle_stop_set_contains_only_actual_circle_owned_connections(self):
        sender=self.peers[2];receiver=self.peers[0];observer=threading.Event()
        with sender._connection(receiver.public_key,deadline=time.monotonic()+4,cancel=observer) as unrelated:
            with self.assertRaisesRegex(ValueError,'CANCELLED'):
                with sender._connection(self.peers[1].public_key,deadline=time.monotonic()+4,cancel=sender._circle_cancel) as circle:
                    self.assertNotIn(unrelated,sender._circle_sockets);self.assertIn(circle,sender._circle_sockets)
                    sender.cancel_operation(sender._circle_cancel)
            self.assertGreaterEqual(unrelated.fileno(),0);self.assertFalse(observer.is_set())
        self.assertFalse(sender._socket_cancels)


if __name__=='__main__':unittest.main()
