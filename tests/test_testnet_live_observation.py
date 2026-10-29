"""Fast observations cannot start nodes, transfer, or bypass identity checks."""
from collections import deque
from contextlib import ExitStack
import threading
import unittest
from unittest.mock import patch

from backend import gg_testnet as node


class LiveObservationTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        for name,value in {'_identity_valid':True,'_session':'owned-test-session',
                           '_measurements':deque(maxlen=32),
                           '_rpc_stats':{'requests':0,'members':0,'batches':0}}.items():
            self.stack.enter_context(patch.object(node,name,value))
        self.alive=self.stack.enter_context(patch.object(node,'_alive',return_value=True))
        self.rpc=self.stack.enter_context(patch.object(node,'_rpc',return_value={
            'number':'0x2','hash':'0x'+'2'*64,'parentHash':'0x'+'1'*64,
            'timestamp':'0x1','transactions':[]}))
        self.graph=self.stack.enter_context(patch.object(node,'_block_graph',return_value={
            'blocks':[],'edges':[],'stale':False,'metrics':{},'observed_at':1}))
        self.start=self.stack.enter_context(patch.object(node,'start'))
        self.send=self.stack.enter_context(patch.object(node,'_broadcast'))

    def tearDown(self):
        self.start.assert_not_called();self.send.assert_not_called()

    def test_owned_read_has_actual_rpc_timing_and_no_account_or_transfer_work(self):
        with patch.object(node,'_account_snapshots') as accounts:
            packet=node.telemetry_snapshot()
        self.rpc.assert_called_once_with('eth_getBlockByNumber',['latest',False])
        accounts.assert_not_called()
        body=packet['testnet']
        self.assertEqual(body['session'],'owned-test-session')
        self.assertEqual(body['height'],2)
        self.assertEqual(body['state'],'RUNNING');self.assertEqual(body['error'],'')
        self.assertEqual(body['measurements'][-1]['operation'],'rpc')
        self.assertEqual(body['measurements'][-1]['block_height'],2)
        self.assertGreaterEqual(body['measurements'][-1]['elapsed_ms'],0)
        self.assertGreater(body['observation_at'],1)

    def test_stopped_or_unverified_identity_never_probes_or_revives_node(self):
        self.alive.return_value=False
        self.assertEqual(node.telemetry_snapshot()['testnet']['state'],'STOPPED')
        self.alive.return_value=True
        with patch.object(node,'_identity_valid',False):
            body=node.telemetry_snapshot()['testnet']
        self.assertEqual(body['state'],'READ_FAILED');self.assertIsNone(body['review'])
        self.assertTrue(body['block_graph']['stale'])
        self.rpc.assert_not_called();self.graph.assert_not_called()

    def test_invalid_header_or_parent_stays_failed_without_new_points(self):
        self.rpc.return_value={'number':'0x2','hash':'invented-non-hash'}
        before=len(node._block_history.rows)
        packet=node.telemetry_snapshot()
        self.assertEqual(packet['testnet']['state'],'READ_FAILED')
        self.assertEqual(packet['testnet']['measurements'][-1]['state'],'FAIL')
        self.assertTrue(packet['testnet']['block_graph']['stale'])
        self.assertEqual(len(node._block_history.rows),before)
        self.graph.assert_not_called()

    def test_busy_transaction_lane_skips_read_instead_of_queuing(self):
        held=threading.Event();release=threading.Event()
        def owner():
            with node.LOCK:
                held.set();release.wait(2)
        thread=threading.Thread(target=owner);thread.start()
        try:
            self.assertTrue(held.wait(1));self.assertIsNone(node.telemetry_snapshot())
            self.rpc.assert_not_called()
        finally:
            release.set();thread.join(2)
        self.assertFalse(thread.is_alive())


if __name__=='__main__':unittest.main()
