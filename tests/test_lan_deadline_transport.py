"""Bounded receive polling and real signed loopback token regression tests."""
import socket
import struct
import threading
import time
import unittest
from unittest.mock import patch

from backend import gg_lan_dag as lan


class ReceiveDeadlineTests(unittest.TestCase):
    def pair(self):
        left,right=socket.socketpair()
        self.addCleanup(left.close);self.addCleanup(right.close)
        return left,right

    def worker(self,action):
        thread=threading.Thread(target=action,daemon=True);thread.start()
        self.addCleanup(thread.join,1)
        return thread

    def test_silent_poll_timeouts_do_not_abort_a_valid_frame(self):
        left,right=self.pair();value={'state':'READY'};raw=lan.pack(value)
        def send():
            time.sleep(.07);left.sendall(struct.pack('!I',len(raw))+raw)
        self.worker(send)
        with patch.object(lan,'IO_TIMEOUT',.02),patch.object(lan,'FRAME_SECONDS',.3):
            result,size=lan._receive(right,lan.MAX_FRAME)
        self.assertEqual(result,value);self.assertEqual(size,len(raw)+4)

    def test_header_does_not_reset_body_deadline_and_received_bytes_are_charged(self):
        left,right=self.pair();raw=lan.pack({'state':'READY'});charged=[];finished=threading.Event()
        def send():
            if finished.wait(.06):return
            left.sendall(struct.pack('!I',len(raw)))
            if not finished.wait(.12):left.sendall(raw)
        self.worker(send);began=time.monotonic()
        try:
            with patch.object(lan,'IO_TIMEOUT',.02),patch.object(lan,'FRAME_SECONDS',.13):
                with self.assertRaisesRegex(ValueError,'GG_LAN_READ_DEADLINE'):
                    lan._receive(right,lan.MAX_FRAME,account=charged.append)
        finally:finished.set()
        self.assertLess(time.monotonic()-began,.3);self.assertEqual(sum(charged),4)

    def test_earlier_work_or_connection_budget_still_bounds_silent_peer(self):
        _left,right=self.pair();began=time.monotonic()
        with patch.object(lan,'IO_TIMEOUT',.02):
            with self.assertRaisesRegex(ValueError,'GG_LAN_READ_DEADLINE'):
                lan._receive(right,lan.MAX_FRAME,deadline=began+.07)
        self.assertLess(time.monotonic()-began,.25)

    def test_cancellation_during_authentication_cleans_tracked_socket(self):
        left,_right=self.pair();peer=lan.LanDagPeer('owned-cancel');self.addCleanup(peer.stop)
        remote='a'*64;peer._roster={remote:{'host':'127.0.0.1','port':16120}}
        cancel=threading.Event();timer=threading.Timer(.05,cancel.set);timer.start();self.addCleanup(timer.cancel)
        began=time.monotonic()
        with patch.object(lan.socket,'create_connection',return_value=left),patch.object(lan,'IO_TIMEOUT',.02):
            with self.assertRaisesRegex(ValueError,'GG_LAN_CIRCLE_CANCELLED') as raised:
                peer._token_rpc(remote,'TOKEN_STATUS',{},cancel=cancel,deadline=began+1)
        self.assertLess(time.monotonic()-began,.25)
        self.assertEqual(lan._failure_details(raised.exception),{'operation':'TOKEN_STATUS','stage':'AUTH','error_class':'ValueError'})
        self.assertFalse(peer._sockets);self.assertFalse(peer._circle_sockets)

    def test_eof_accounting_and_late_bytes_fail_closed(self):
        left,right=self.pair();left.close()
        with self.assertRaisesRegex(ValueError,'GG_LAN_EOF'):lan._receive(right,lan.MAX_FRAME)
        class Late:
            def settimeout(self,_value):pass
            def recv(self,_count):return b'\0'
        charged=[]
        with patch.object(lan.time,'monotonic',side_effect=(0,0,2)):
            with self.assertRaisesRegex(ValueError,'GG_LAN_READ_DEADLINE'):
                lan._receive(Late(),lan.MAX_FRAME,account=charged.append)
        self.assertEqual(charged,[1])
        def reject(_size):raise ValueError('GG_LAN_CREDIT')
        with self.assertRaisesRegex(ValueError,'GG_LAN_CREDIT'):
            lan._receive(Late(),lan.MAX_FRAME,account=reject)

    def test_transport_error_metadata_is_sanitized_timestamped_and_sticky(self):
        peer=lan.LanDagPeer('owned-error');self.addCleanup(peer.stop)
        error=TimeoutError('private endpoint or other exception prose')
        error._gg_lan_details={'operation':'CIRCLE_SIGN','stage':'RECEIVE','payload':'private'}
        with patch.object(lan.time,'time',return_value=1234.5):peer._error(error)
        body=peer.snapshot()['lan']
        self.assertEqual(body['last_error'],'GG_LAN_IO_TIMEOUT');self.assertEqual(body['last_error_at'],1234.5)
        self.assertEqual(body['last_error_details'],{'operation':'CIRCLE_SIGN','stage':'RECEIVE','error_class':'TimeoutError'})
        left,right=self.pair();raw=lan.pack({'state':'READY'});left.sendall(struct.pack('!I',len(raw))+raw)
        peer._read(right,lan.MAX_FRAME)  # Successful I/O must not erase failure history.
        self.assertEqual(peer.snapshot()['lan']['last_error'],'GG_LAN_IO_TIMEOUT')
        error._gg_lan_details={'operation':'private text','stage':{'private':'text'}}
        self.assertEqual(lan._failure_details(error),{'operation':'','stage':'','error_class':'TimeoutError'})


class SignedTokenDeadlineTests(unittest.TestCase):
    def paired(self):
        peers=[lan.LanDagPeer('owned-deadline-'+str(index),allow_test_tokens=True) for index in range(3)]
        for peer in peers:self.addCleanup(peer.stop);peer.start_pairing()
        coordinator=peers[0]
        for peer in peers[1:]:peer.pin_coordinator(coordinator.public_key)
        bundle=coordinator.create_session([peer.public_invite() for peer in peers],enable_test_tokens=True)
        for peer in peers:peer.install_session(bundle)
        return peers

    def test_batch16_sign_response_after_350ms_completes_real_closed_circle(self):
        peers=self.paired();coordinator=peers[0];target=min(peers[1:],key=lambda peer:peer.public_key)
        command=target._token_command;observed=[]
        def delayed(peer,kind,payload):
            if kind=='CIRCLE_SIGN' and not observed:
                observed.append((len(payload['records']),payload['count']));time.sleep(.5)
            return command(peer,kind,payload)
        target._token_command=delayed
        initial={row['peer_key']:row['balance_atomic'] for row in coordinator.token_snapshot()['accounts']}
        coordinator.start_token_circle(2200,16,'1');coordinator._circle_thread.join(4)
        self.assertFalse(coordinator._circle_thread.is_alive())
        result=coordinator.snapshot()['token_circle']
        self.assertEqual(observed,[(16,16)])
        self.assertEqual(result['state'],'COMPLETE',result);self.assertTrue(result['all_peers_synced'],result)
        self.assertGreaterEqual(result['completed_rounds'],16);self.assertEqual(result['transactions'],result['completed_rounds']*3)
        self.assertEqual(result['last_error_details'],{})
        states=[peer.token_snapshot() for peer in peers]
        self.assertEqual(len({state['head'] for state in states}),1)
        self.assertEqual(len({state['state_root'] for state in states}),1)
        for state in states:self.assertEqual({row['peer_key']:row['balance_atomic'] for row in state['accounts']},initial)

    def test_lost_submit_ack_is_not_replayed_or_rolled_back(self):
        peers=self.paired();coordinator,sender,recipient=peers;command=coordinator._token_command;submissions=[]
        def delayed_ack(peer,kind,payload):
            result=command(peer,kind,payload)
            if kind=='TOKEN_SUBMIT':submissions.append(1);time.sleep(lan.FRAME_SECONDS+.12)
            return result
        coordinator._token_command=delayed_ack
        transactions=sender._tokens.sign_batch(recipient.public_key,'1')
        with self.assertRaisesRegex(ValueError,'GG_LAN_READ_DEADLINE') as raised:
            sender._token_rpc(coordinator.public_key,'TOKEN_SUBMIT',{'transactions':transactions},cancel=threading.Event(),deadline=time.monotonic()+2)
        self.assertEqual(submissions,[1]);self.assertEqual(coordinator.token_snapshot()['sequence'],1)
        self.assertEqual(lan._failure_details(raised.exception),{'operation':'TOKEN_SUBMIT','stage':'RECEIVE','error_class':'ValueError'})
        self.assertFalse(sender._circle_sockets)


if __name__=='__main__':unittest.main()
