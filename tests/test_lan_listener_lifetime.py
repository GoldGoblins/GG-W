"""Actual owned TCP listener lifetime, including server-active close and rebind."""
import socket
import unittest
from backend import gg_lan_dag as lan


class LanListenerLifetimeTests(unittest.TestCase):
    def peer(self,port=0):
        value=lan.LanDagPeer('owned-listener-fixture',port=port)
        self.addCleanup(value.stop);return value

    def test_server_closed_connection_does_not_prevent_immediate_endpoint_restart(self):
        first=self.peer();first.start_pairing();port=first.port
        with socket.create_connection(('127.0.0.1',port),timeout=2) as client:
            lan._send(client,{'kind':'invite'},lan.MAX_INVITE)
            invite,_=lan._receive(client,lan.MAX_INVITE)
            self.assertEqual(invite,first.public_invite())
            self.assertEqual(client.recv(1),b'')  # server actively closes first
        first.stop();self.assertIsNone(first._listener)
        second=self.peer(port);second.start_pairing()
        with socket.create_connection(('127.0.0.1',port),timeout=2) as client:
            lan._send(client,{'kind':'invite'},lan.MAX_INVITE)
            invite,_=lan._receive(client,lan.MAX_INVITE)
            self.assertEqual(invite,second.public_invite())
            self.assertNotEqual(invite['body']['peer_key'],first.public_key)

    def test_second_active_listener_cannot_share_owned_endpoint(self):
        first=self.peer();first.start_pairing();second=self.peer(first.port)
        with self.assertRaises(OSError):second.start_pairing()
        self.assertIsNone(second._listener)
        with socket.create_connection(('127.0.0.1',first.port),timeout=2) as client:
            lan._send(client,{'kind':'invite'},lan.MAX_INVITE)
            invite,_=lan._receive(client,lan.MAX_INVITE)
            self.assertEqual(invite,first.public_invite())


if __name__=='__main__':unittest.main()
