"""Finite transport resource policy and backpressure; no throughput claim."""
from copy import deepcopy
import queue
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from backend import gg_native_resources as resources,gg_protocol_transport as transport
from tests.test_native_resources import server


class NativeResourceTransportTests(unittest.TestCase):
    def client(self,own,peer,error=None):
        client=transport.ProofTransportClient.__new__(transport.ProofTransportClient)
        client._control=threading.RLock();client._counter=0;client._last_request=10;client._backoff=0
        client._transport_budget=own;client._peer_budget=peer;client.anchor={"genesis_hash":"a"*64}
        client.sent=[];client.send=client.sent.append
        def response(**kwargs):
            result={"schema":transport.SCHEMA,"event":"RESPONSE","genesis_hash":"a"*64,"id":client._counter}
            result.update(error=error) if error else result.update(payload={"verified_elsewhere":True})
            return result
        client._read=response
        return client

    def test_low_exact_budgets_and_server_finite_increased_capacity(self):
        low=resources.LOW.transport()
        self.assertEqual([low[name] for name in ("connections","requests_per_second",
            "requests_per_connection_second","handlers","queue_count","client_interval_micros")],[8,32,8,2,8,135000])
        large=server().transport()
        self.assertEqual([large[name] for name in ("connections","requests_per_second",
            "requests_per_connection_second","handlers","queue_count","queue_bytes","client_interval_micros")],
            [64,2048,256,32,64,64*65536,3907])
        self.assertEqual(transport._transport_budget(large),large)
        for name in set(large)-{"schema"}:
            bad=dict(large);bad[name]=True
            with self.subTest(name=name),self.assertRaises(ValueError):transport._transport_budget(bad)
        for change in ({"requests_per_second":8193},{"queue_bytes":1},{"client_interval_micros":1},
                {"request_bytes":65537},{"unknown":1},{"schema":"future"}):
            with self.subTest(change=change),self.assertRaises(ValueError):transport._transport_budget(dict(large,**change))

    def test_client_respects_authenticated_low_peer_and_server_pace_without_retry(self):
        large,low=server().transport(),resources.LOW.transport()
        for own,peer,delay in ((low,large,.135),(large,low,.135),(large,large,.003907)):
            client=self.client(own,peer)
            with patch.object(transport.time,"monotonic",return_value=10),patch.object(transport.time,"sleep") as sleep:
                self.assertEqual(client.call({"method":"state"}),{"verified_elsewhere":True})
            self.assertAlmostEqual(sleep.call_args.args[0],delay)
            self.assertEqual(len(client.sent),1)
        client=self.client(large,large,"GG_PROTOCOL_RELAY_LIMIT")
        for expected in (.135,.27,.54,1.08,2,2):
            with patch.object(transport.time,"monotonic",return_value=10),patch.object(transport.time,"sleep"):
                with self.assertRaisesRegex(ValueError,"RELAY_LIMIT"):client.call({"method":"state"})
            self.assertEqual(client._backoff,expected)
        self.assertEqual(len(client.sent),6,"backpressure must not trigger automatic retries")

    def test_queue_has_independent_byte_backpressure_and_expired_work_never_runs(self):
        subject=transport.ProofTransportServer.__new__(transport.ProofTransportServer)
        subject._stop=threading.Event();subject._queue=queue.Queue(maxsize=8);subject._queue_lock=threading.Lock()
        request={"id":1,"peer_key":"public","payload":{"method":"state"}}
        size=len(transport.pack(request["payload"]))
        subject._queued_bytes=size;subject._queue.put((request,size,9))
        subject._handler=Mock(side_effect=AssertionError("expired request ran"))
        subject._reply=Mock(side_effect=lambda *args,**kwargs:subject._stop.set())
        with patch.object(transport.time,"monotonic",return_value=10):subject._worker()
        subject._handler.assert_not_called()
        self.assertEqual(subject._queued_bytes,0);self.assertEqual(subject._queue.unfinished_tasks,0)
        self.assertIn("TIMEOUT",str(subject._reply.call_args.kwargs["error"]))

    def test_byte_limit_rejects_request_even_when_queue_count_is_not_full(self):
        subject=transport.ProofTransportServer.__new__(transport.ProofTransportServer)
        subject._stop=threading.Event();subject._queue=queue.Queue(maxsize=8)
        subject._queue_lock=threading.Lock();subject._peer_lock=threading.RLock();subject._peers={}
        subject.anchor={"genesis_hash":"a"*64};subject._transport_budget=resources.LOW.transport();subject.last_error=""
        subject._queued_bytes=subject._transport_budget["queue_bytes"]-1
        request={"schema":transport.SCHEMA,"event":"REQUEST","genesis_hash":"a"*64,"id":1,
            "peer_key":"authenticated-public-fixture","payload":{"method":"state"}}
        subject._read=Mock(side_effect=[request,ValueError("GG_PUBLIC_STOP_FIXTURE")])
        subject._reply=Mock();subject.request_stop=lambda:subject._stop.set()
        subject._reader()
        self.assertTrue(subject._queue.empty())
        self.assertEqual(subject._queued_bytes,subject._transport_budget["queue_bytes"]-1)
        self.assertIn("QUEUE_FULL",str(subject._reply.call_args.kwargs["error"]))

    def test_selected_server_cannot_launch_unowned_transport(self):
        from tests.test_protocol_transport_history import public_key
        key=public_key("resource-unowned")
        pin={"genesis_hash":"a"*64,"genesis":{"protocol":{"environment":"TESTNET"}}}
        with patch.object(transport.protocol,"validate_pin",side_effect=deepcopy),patch.object(transport.subprocess,"Popen") as spawn:
            with self.assertRaisesRegex(ValueError,"OWNED_PROFILE_REQUIRED"):
                transport._Pipe(key,pin,{"mode":"CLIENT"},binary="PUBLIC-fixture",resources=server())
        spawn.assert_not_called()


if __name__=="__main__":unittest.main()
