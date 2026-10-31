"""Deterministic transport budgets, shared pacing and bounded diagnostics.

All fixtures use RAM signers and fake sockets/clocks. No external endpoints,
real wallets, live application, persistent logs or physical peers are used.
"""
import socket
import threading
import unittest
from unittest.mock import Mock,patch

from backend import gg_lan_dag as lan


class Clock:
    def __init__(self):self.now=100.0;self.stopped=False;self.on_wait=None
    def monotonic(self):return self.now
    def is_set(self):return self.stopped
    def set(self):self.stopped=True
    def wait(self,delay):
        if self.on_wait:self.on_wait(delay)
        self.now+=delay
        return self.stopped


class FakeSocket:
    def __init__(self,clock=None,latency=0):
        self.clock=clock;self.latency=latency;self.calls=0;self.timeout=None;self.closed=False
    def settimeout(self,value):self.timeout=value
    def sendall(self,raw):
        self.calls+=1
        if self.clock:self.clock.now+=min(self.latency,self.timeout)
        if self.latency>self.timeout:raise socket.timeout()
    def close(self):self.closed=True
    def __enter__(self):return self
    def __exit__(self,*args):self.close()


class TransportHealthTests(unittest.TestCase):
    def peer(self):
        peer=lan.LanDagPeer('local-fixture');remote='a'*64
        peer._roster={remote:{'label':'Linux','host':'127.0.0.1','port':16555,'producer_indices':[0,1]}}
        self.addCleanup(peer.stop)
        return peer,remote

    def test_send_uses_frame_budget_in_one_sendall_not_poll_interval(self):
        clock=Clock();sock=FakeSocket(clock,latency=.5)
        with patch.object(lan.time,'monotonic',side_effect=clock.monotonic):
            size=lan._send(sock,{'state':'READY'},lan.MAX_FRAME,deadline=clock.now+3)
        self.assertEqual(sock.calls,1);self.assertGreater(size,4)
        self.assertEqual(sock.timeout,lan.FRAME_SECONDS)
        self.assertGreater(sock.timeout,lan.IO_TIMEOUT)

    def test_send_earlier_deadline_expiry_and_unknown_partial_send_are_not_retried(self):
        clock=Clock();sock=FakeSocket(clock,latency=.5)
        with patch.object(lan.time,'monotonic',side_effect=clock.monotonic):
            with self.assertRaises(socket.timeout):lan._send(sock,{'state':'READY'},lan.MAX_FRAME,deadline=clock.now+.2)
            with self.assertRaisesRegex(ValueError,'GG_LAN_CIRCLE_DEADLINE'):
                lan._send(sock,{'state':'READY'},lan.MAX_FRAME,deadline=clock.now)
        self.assertEqual(sock.calls,1);self.assertAlmostEqual(sock.timeout,.2)

    def test_send_default_is_finite_and_late_return_fails_closed(self):
        sock=FakeSocket()
        with patch.object(lan.time,'monotonic',side_effect=(100,100,102)):
            with self.assertRaisesRegex(ValueError,'GG_LAN_SEND_DEADLINE'):
                lan._send(sock,{'state':'READY'},lan.MAX_FRAME)
        self.assertEqual(sock.timeout,lan.FRAME_SECONDS);self.assertEqual(sock.calls,1)

    def test_shared_get_page_control_pacing_releases_lock_and_preserves_rates(self):
        peer,remote=self.peer();clock=Clock();peer._cancel=clock
        def check_wait(_delay):self.assertFalse(peer._lock._is_owned())
        clock.on_wait=check_wait;grants=[]
        with patch.object(lan.time,'monotonic',side_effect=clock.monotonic):
            for operation in ('GET','TOKEN_STATUS','PAGE','DAG_STRESS_STOP','GET','TOKEN_STATUS'):
                peer._pace_connection(remote,operation,deadline=clock.now+3)
                grants.append((operation,clock.now))
        self.assertTrue(all(b[1]-a[1]>=.1-1e-9 for a,b in zip(grants,grants[1:])))
        for operations,gap in (({'GET','PAGE'},.2),({'TOKEN_STATUS','DAG_STRESS_STOP'},.125)):
            times=[stamp for operation,stamp in grants if operation in operations]
            self.assertTrue(all(b-a>=gap-1e-9 for a,b in zip(times,times[1:])))
        self.assertEqual(peer._control_waiters,{})
        self.assertEqual(set(peer._outbound_next),{remote})

    def test_active_gossip_capacity_and_control_priority_are_bounded(self):
        peer,remote=self.peer();clock=Clock();peer._cancel=clock
        with patch.object(lan.time,'monotonic',side_effect=clock.monotonic),patch.object(peer,'_gossip_active',return_value=True):
            grants=[]
            for _ in range(8):
                peer._pace_connection(remote,'PAGE',deadline=clock.now+3);grants.append(clock.now)
            self.assertAlmostEqual(grants[-1]-grants[0],.875)
            peer._control_waiters[remote]=1
            def release_control(_delay):peer._control_waiters.clear()
            clock.on_wait=release_control
            peer._pace_connection(remote,'GET',deadline=clock.now+3)
        self.assertGreater(clock.now,grants[-1])

    def test_pacing_cancel_deadline_and_contended_elapsed_time_never_connect(self):
        peer,remote=self.peer();clock=Clock();peer._cancel=clock;cancel=threading.Event()
        peer._outbound_next[remote]=clock.now+2
        def cancel_wait(_delay):cancel.set()
        clock.on_wait=cancel_wait
        with patch.object(lan.time,'monotonic',side_effect=clock.monotonic),patch.object(cancel,'wait',side_effect=clock.wait):
            with self.assertRaisesRegex(ValueError,'GG_LAN_CIRCLE_CANCELLED'):
                peer._pace_connection(remote,'DAG_STRESS_STOP',cancel=cancel,deadline=clock.now+1)
            self.assertEqual(peer._control_waiters,{})
            cancel.clear();clock.on_wait=None
            with self.assertRaisesRegex(ValueError,'GG_LAN_CIRCLE_DEADLINE'):
                peer._pace_connection(remote,'PAGE',deadline=clock.now+.15)
            def blocked_activity():clock.now+=2;return True
            with patch.object(peer,'_gossip_active',side_effect=blocked_activity):
                with self.assertRaisesRegex(ValueError,'GG_LAN_CIRCLE_DEADLINE'):
                    peer._pace_connection(remote,'PAGE',deadline=clock.now+1)
        self.assertEqual(peer._outbound_next[remote],102)

    def test_concurrent_pacing_reservations_do_not_burst(self):
        peer,remote=self.peer();barrier=threading.Barrier(3);grants=[]
        def paced():
            barrier.wait();peer._pace_connection(remote,'TOKEN_STATUS');grants.append(lan.time.monotonic())
        threads=[threading.Thread(target=paced) for _ in range(2)]
        for worker in threads:worker.start()
        barrier.wait()
        for worker in threads:worker.join(1);self.assertFalse(worker.is_alive())
        self.assertEqual(len(grants),2);self.assertGreaterEqual(abs(grants[1]-grants[0]),.115)
        self.assertEqual(peer._control_waiters,{})

    def test_backoff_is_bounded_and_progress_and_active_convergence_resume(self):
        peer,remote=self.peer();clock=Clock()
        with patch.object(lan.time,'monotonic',side_effect=clock.monotonic):
            idle=[peer._gossip_result(remote) for _ in range(10)]
            errors=[peer._gossip_result(remote,error=True) for _ in range(10)]
            self.assertEqual(idle[-1],2);self.assertEqual(errors[-1],4)
            self.assertEqual(peer._gossip_result(remote,error=True,active=True),1)
            self.assertEqual(peer._gossip_result(remote,active=True),.1)
            self.assertEqual(peer._gossip_result(remote,progress=True),.1)
            peer._dag_plan={'begun':True,'deadline':clock.now+1};peer._dag_stress['state']='STOPPING'
            self.assertTrue(peer._gossip_active())
        self.assertEqual(set(peer._gossip_health),{remote})

    def test_active_convergence_bypasses_idle_backoff_but_idle_waits(self):
        for active in (False,True):
            with self.subTest(active=active):
                peer,remote=self.peer();clock=Clock();peer._cancel=clock;peer._cursors={remote:0}
                peer._gossip_health[remote]={'idle':5,'errors':0,'next':clock.now+2}
                if active:peer._dag_plan={'begun':True,'deadline':clock.now+3}
                stamps=[]
                def pull(*args):stamps.append(clock.now);clock.set();return 0
                with patch.object(lan.time,'monotonic',side_effect=clock.monotonic),patch.object(peer,'_pull',side_effect=pull):
                    peer._gossip_loop()
                self.assertEqual(len(stamps),1)
                if active:self.assertLess(stamps[0],100.2)
                else:self.assertGreaterEqual(stamps[0],102)

    def test_accept_drop_reasons_are_observable_without_refunding_limits(self):
        for reason in ('SESSION','RATE','HANDLERS','BYTES'):
            with self.subTest(reason=reason):
                peer,_=self.peer();clock=Clock()
                if reason=='SESSION':peer._connections_admitted=lan.MAX_REQUESTS
                if reason=='RATE':peer._connection_times.extend([clock.now]*32)
                if reason=='BYTES':peer._raw_received=lan.MAX_TOTAL_BYTES+1
                if reason=='HANDLERS':
                    for _ in range(4):peer._slots.acquire()
                sock=FakeSocket()
                def close():sock.closed=True;peer._cancel.set()
                sock.close=close;listener=Mock();listener.accept.return_value=(sock,('127.0.0.1',16555));peer._listener=listener
                with patch.object(lan.time,'monotonic',side_effect=clock.monotonic):peer._accept()
                peer._cancel.clear();body=peer.snapshot()['lan'];diagnostics=body['transport']
                self.assertTrue(sock.closed);self.assertEqual(len(peer._handlers),0)
                self.assertEqual(diagnostics['counters']['admission_drops'][reason],1)
                self.assertEqual(diagnostics['history'][-1]['reason'],reason)
                self.assertEqual(diagnostics['history'][-1]['stage'],'ACCEPT')
                if reason in {'SESSION','BYTES'}:self.assertEqual(body['state'],'EXHAUSTED')
                if reason=='HANDLERS':self.assertEqual(peer._connections_admitted,1)

    def test_credit_exhaustion_stops_futile_gossip_and_blocks_new_connections(self):
        peer,remote=self.peer();peer._traffic[remote]={'frames':lan.MAX_REQUESTS,'bytes':0}
        with self.assertRaisesRegex(ValueError,'GG_LAN_CREDIT'):peer._credit(remote,10)
        self.assertEqual(peer._traffic[remote]['frames'],lan.MAX_REQUESTS+1)
        self.assertEqual(peer._total_bytes,10)
        with patch.object(lan.socket,'create_connection',side_effect=AssertionError('exhausted session connected')):
            with self.assertRaisesRegex(ValueError,'GG_LAN_SESSION_EXHAUSTED'):peer._pull(remote,'PAGE',{'after':0})
        with patch.object(peer,'_pull',side_effect=AssertionError('exhausted gossip continued')):peer._gossip_loop()
        body=peer.snapshot()['lan'];self.assertEqual(body['state'],'EXHAUSTED')
        self.assertEqual(body['transport']['exhausted_reason'],'FRAMES')
        with self.assertRaisesRegex(ValueError,'GG_LAN_SESSION_EXHAUSTED'):peer.start_dag_stress()
        with self.assertRaisesRegex(ValueError,'GG_LAN_SESSION_EXHAUSTED'):peer.start_token_circle()
        before=peer._raw_received
        with self.assertRaisesRegex(ValueError,'GG_LAN_CREDIT'):peer._account_received(lan.MAX_TOTAL_BYTES+1)
        self.assertEqual(peer._raw_received,before+lan.MAX_TOTAL_BYTES+1)

    def test_bounded_sanitized_history_and_expected_local_stop_preserve_real_errors(self):
        peer,remote=self.peer();peer._dag_stress['last_error']='GG_LAN_PROPOSAL_HASH'
        for _ in range(40):peer._error(ValueError('GG_LAN_EOF'),'PAGE','RECEIVE',remote)
        self.assertEqual(len(peer._transport_history),32)
        self.assertEqual(peer._transport_counts['failures'],40)
        self.assertEqual(peer._transport_history[-1]['peer_label'],'Linux')
        previous=(peer._last_error,peer._last_error_at,peer._rejected)
        peer._cancel.set();peer._error(ConnectionResetError('secret raw message'),'GET','RECEIVE',remote)
        self.assertEqual((peer._last_error,peer._last_error_at,peer._rejected),previous)
        self.assertEqual(peer._transport_counts['expected_closures'],1)
        peer._error(ValueError('GG_DAG_SIGNATURE'),'PAGE','VALIDATE',remote)
        self.assertEqual(peer._last_error,'GG_DAG_SIGNATURE')
        self.assertFalse(peer._transport_history[-1]['expected'])
        self.assertEqual(peer._dag_stress['last_error'],'GG_LAN_PROPOSAL_HASH')
        self.assertEqual(peer.snapshot()['lan']['transport']['state'],'STOPPED')

    def test_remote_cancel_code_is_not_local_cancellation_and_labels_are_redacted(self):
        peer,remote=self.peer();peer._roster[remote]['label']='a'*64
        error=ValueError('GG_LAN_CIRCLE_CANCELLED')
        peer._error(error,'private operation','private stage',remote)
        peer._error(error)  # Outer gossip must not count a recorded RPC twice.
        record=peer._transport_history[-1]
        self.assertEqual((record['operation'],record['stage'],record['peer_label']),('','',''))
        self.assertFalse(record['expected']);self.assertEqual(peer._transport_counts['failures'],1)
        cancel=threading.Event();cancel.set()
        peer._error(ValueError('GG_LAN_CIRCLE_CANCELLED'),'DAG_STRESS_STOP','WAIT',remote,cancel=cancel)
        self.assertEqual(peer._transport_counts['expected_closures'],1)
        self.assertEqual(set(peer._transport_counts),{'failures','expected_closures','successes','admission_drops'})
        for label in ('Device 123e4567-e89b-12d3-a456-426614174000','api_key_abcd1234','bearer something'):
            peer._roster[remote]['label']=label
            peer._error(ValueError('GG_LAN_EOF'),'PAGE','RECEIVE',remote)
            self.assertEqual(peer._transport_history[-1]['peer_label'],'')

    def test_stop_after_pacing_opens_no_new_socket(self):
        peer,remote=self.peer()
        with (patch.object(peer,'_pace_connection',side_effect=lambda *args,**kwargs:peer._cancel.set()),
              patch.object(lan.socket,'create_connection') as connect):
            with self.assertRaisesRegex(ValueError,'GG_LAN_STOPPED'):peer._pull(remote,'PAGE',{'after':0})
        connect.assert_not_called()
        self.assertTrue(peer._transport_history[-1]['expected'])

    def test_pull_request_and_server_data_end_share_connection_deadline(self):
        peer,remote=self.peer();sock=FakeSocket()
        with (patch.object(lan.socket,'create_connection',return_value=sock),
              patch.object(peer,'_client_auth',return_value='session'),
              patch.object(peer,'_read',return_value=({},10)),
              patch.object(peer,'_check_frame',return_value={'kind':'END','payload':{'records':0}}),
              patch.object(lan,'_send',return_value=10) as send):
            self.assertEqual(peer._pull(remote,'PAGE',{'after':0}),0)
            self.assertIsInstance(send.call_args.kwargs['deadline'],float)
        peer._slots.acquire();peer._engine=Mock()
        peer._engine.public_proposals.return_value={'records':[{'hash':'b'*64,'admission_index':1,'wire':b'wire'}]}
        try:
            with (patch.object(peer,'_read',side_effect=(({},10),({},10))),
                  patch.object(peer,'_server_auth',return_value=(remote,'session')),
                  patch.object(peer,'_check_frame',return_value={'kind':'PAGE','payload':{'after':0}}),
                  patch.object(lan,'_send',return_value=10) as send):
                peer._serve(FakeSocket(),'127.0.0.1')
                self.assertEqual(send.call_count,2)
                self.assertEqual(send.call_args_list[0].kwargs['deadline'],send.call_args_list[1].kwargs['deadline'])
        finally:peer._engine=None

    def test_incoming_auth_failure_has_stage_but_no_unverified_peer_label(self):
        peer,_=self.peer();peer._slots.acquire()
        with (patch.object(peer,'_read',return_value=({},10)),
              patch.object(peer,'_server_auth',side_effect=ValueError('GG_DAG_SIGNATURE'))):
            peer._serve(FakeSocket(),'127.0.0.1')
        record=peer._transport_history[-1]
        self.assertEqual((record['operation'],record['stage'],record['code'],record['peer_label']),
            ('INCOMING','AUTH','GG_DAG_SIGNATURE',''))

    def test_rpc_lost_ack_is_not_replayed_and_has_exact_operation_stage(self):
        peer,remote=self.peer();sock=FakeSocket()
        with (patch.object(lan.socket,'create_connection',return_value=sock) as connect,
              patch.object(peer,'_client_auth',return_value='session'),
              patch.object(peer,'_read',side_effect=ValueError('GG_LAN_EOF')),
              patch.object(lan,'_send',return_value=10) as send):
            with self.assertRaisesRegex(ValueError,'GG_LAN_EOF'):peer._token_rpc(remote,'DAG_STRESS_STOP',{})
        self.assertEqual((connect.call_count,send.call_count),(1,1))
        self.assertFalse(peer._sockets);self.assertFalse(peer._circle_sockets)
        record=peer._transport_history[-1]
        self.assertEqual((record['operation'],record['stage'],record['code']),('DAG_STRESS_STOP','RECEIVE','GG_LAN_EOF'))


if __name__=='__main__':unittest.main()
