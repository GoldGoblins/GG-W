"""Owned loopback TCP restart reservations, without starting a native node.

Real sockets exercise kernel TIME_WAIT and active-listener collisions. Explicit
socket-failure seams exercise descriptor ownership only, never cryptography.
All endpoints are disposable 127.0.0.1 ports selected by the OS.
"""
import errno
import os
from pathlib import Path
import socket
import sys
import time
import unittest
from unittest.mock import Mock,patch

from backend import gg_consensus_process as process


class NativeP2PReservationTests(unittest.TestCase):
    def tcp(self):
        value=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
        self.addCleanup(value.close);value.settimeout(2)
        return value

    def listener(self):
        value=self.tcp()
        if os.name!='nt':value.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        value.bind(('127.0.0.1',0));value.listen(1)
        return value

    def test_fresh_reservation_keeps_platform_flags_and_never_enables_reuseport(self):
        reserve=process._reserve_p2p_endpoint('127.0.0.1',0);self.addCleanup(reserve.close)
        self.assertEqual(reserve.family,socket.AF_INET)
        self.assertEqual(reserve.getsockname()[0],'127.0.0.1')
        self.assertGreater(reserve.getsockname()[1],0)
        self.assertEqual(reserve.getsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR),0 if os.name=='nt' else 1)
        if hasattr(socket,'SO_REUSEPORT'):
            self.assertEqual(reserve.getsockopt(socket.SOL_SOCKET,socket.SO_REUSEPORT),0)

    @unittest.skipUnless(sys.platform.startswith('linux'),'Linux exact owned TCP state is read from /proc/net/tcp')
    def test_owned_server_time_wait_rejects_plain_bind_but_allows_native_style_restart(self):
        listener=self.listener();port=listener.getsockname()[1]
        client=self.tcp();client.connect(('127.0.0.1',port));peer_port=client.getsockname()[1]
        accepted,_=listener.accept();self.addCleanup(accepted.close);accepted.settimeout(2)
        # The server sends FIN first. Observe EOF in both directions before
        # releasing every socket, so its exact connection enters TIME_WAIT.
        accepted.shutdown(socket.SHUT_WR);self.assertEqual(client.recv(1),b'')
        client.close();self.assertEqual(accepted.recv(1),b'');accepted.close();listener.close()
        local='0100007F:'+format(port,'04X');remote='0100007F:'+format(peer_port,'04X')
        def exact_states():
            return [row.split()[3] for row in Path('/proc/net/tcp').read_text().splitlines()[1:]
                    if row.split()[1:3]==[local,remote]]
        deadline=time.monotonic()+2
        while '06' not in exact_states() and time.monotonic()<deadline:time.sleep(.01)
        self.assertIn('06',exact_states(),'the owned server-side TIME_WAIT state was not established')
        plain=self.tcp()
        with self.assertRaises(OSError) as rejected:plain.bind(('127.0.0.1',port))
        self.assertEqual(rejected.exception.errno,errno.EADDRINUSE);plain.close()
        reserve=process._reserve_p2p_endpoint('127.0.0.1',port);self.addCleanup(reserve.close)
        self.assertEqual(reserve.getsockname(),('127.0.0.1',port))
        self.assertEqual(reserve.getsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR),1)
        self.assertEqual(reserve.getsockopt(socket.SOL_SOCKET,socket.SO_REUSEPORT),0)

    def test_live_listener_collision_is_rejected_and_failed_reservation_fd_is_closed(self):
        listener=self.listener();endpoint=listener.getsockname();created=[];real_socket=socket.socket
        def owned_socket(*args,**kwargs):
            value=real_socket(*args,**kwargs);created.append(value);self.addCleanup(value.close);return value
        with patch.object(process.socket,'socket',side_effect=owned_socket):
            with self.assertRaises(OSError) as rejected:process._reserve_p2p_endpoint(*endpoint)
        self.assertEqual(rejected.exception.errno,10048 if os.name=='nt' else errno.EADDRINUSE)
        self.assertEqual(len(created),1);self.assertEqual(created[0].fileno(),-1)
        # The reservation cannot replace or disable the original listener.
        client=self.tcp();client.connect(endpoint)
        accepted,_=listener.accept();self.addCleanup(accepted.close)
        self.assertEqual(accepted.getsockname(),endpoint)

    def test_invalid_bind_endpoint_closes_the_created_descriptor(self):
        created=[];real_socket=socket.socket
        def owned_socket(*args,**kwargs):
            value=real_socket(*args,**kwargs);created.append(value);self.addCleanup(value.close);return value
        with patch.object(process.socket,'socket',side_effect=owned_socket):
            with self.assertRaises(OverflowError):process._reserve_p2p_endpoint('127.0.0.1',-1)
        self.assertEqual(len(created),1);self.assertEqual(created[0].fileno(),-1)

    @unittest.skipIf(os.name=='nt','Windows must not set the POSIX reuse flag')
    def test_socket_option_failure_closes_owned_fd_and_preserves_error(self):
        value=self.tcp();failure=OSError('PUBLIC injected socket option failure')
        seam=Mock(wraps=value);seam.setsockopt.side_effect=failure
        with patch.object(process.socket,'socket',return_value=seam):
            with self.assertRaises(OSError) as rejected:process._reserve_p2p_endpoint('127.0.0.1',0)
        self.assertIs(rejected.exception,failure);self.assertEqual(value.fileno(),-1)
        seam.bind.assert_not_called();seam.close.assert_called_once_with()


if __name__=='__main__':unittest.main()
