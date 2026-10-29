"""Desktop routes real LAN observations and cancellation to its owned peer.

No sockets, native views, user settings or identities are created here.
"""
import threading
import unittest
from unittest.mock import Mock, patch

from backend import gg_parallel_dag, lan_dag_runtime
from backend.network_telemetry import observe
from backend.network_stop import NetworkStopRuntime, interrupt


class LanDesktopRoutingTests(unittest.TestCase):
    def test_observer_selects_owned_lan_revision_before_snapshot(self):
        order = []
        peer = Mock()
        peer.telemetry_revision.side_effect = lambda: order.append('revision') or ('LAN', 3)
        peer.snapshot.side_effect = lambda: order.append('snapshot') or {'state': 'RUNNING', 'lan': {'state': 'READY'}}
        with patch.object(lan_dag_runtime, 'active_manager', return_value=peer), \
             patch.object(gg_parallel_dag, 'snapshot') as local:
            result = observe('DAG')
        self.assertEqual(order, ['revision', 'snapshot'])
        self.assertEqual(result['revision'], ('LAN', 3))
        self.assertEqual(result['parallel_dag']['lan']['state'], 'READY')
        local.assert_not_called()

    def test_no_lan_preserves_local_engine_observation(self):
        with patch.object(lan_dag_runtime, 'active_manager', return_value=None), \
             patch.object(gg_parallel_dag, 'telemetry_revision', return_value=('LOCAL', 2)), \
             patch.object(gg_parallel_dag, 'snapshot', return_value={'state': 'STOPPED'}) as local:
            result = observe('DAG')
        self.assertEqual(result['revision'], ('LOCAL', 2))
        local.assert_called_once_with()

    def test_lan_interrupt_captures_same_owned_peer_cleanup(self):
        peer = Mock()
        with patch.object(lan_dag_runtime, 'active_manager', return_value=peer), \
             patch.object(gg_parallel_dag, 'request_stop') as local:
            finish = interrupt('DAG')
        peer.request_stop.assert_called_once_with()
        peer.stop.assert_not_called()
        local.assert_not_called()
        finish()
        peer.stop.assert_called_once_with()

    def test_stop_worker_cannot_adopt_later_selected_peer(self):
        entered, release = threading.Event(), threading.Event()
        first, later = Mock(), Mock()
        def held_cleanup():
            entered.set()
            if not release.wait(2):
                raise AssertionError('Owned cleanup fixture timed out')
        first.stop.side_effect = held_cleanup
        runtime = NetworkStopRuntime()
        try:
            with patch.object(lan_dag_runtime, 'active_manager', return_value=first):
                self.assertTrue(runtime.request('DAG'))
                self.assertTrue(entered.wait(1))
            with patch.object(lan_dag_runtime, 'active_manager', return_value=later):
                self.assertTrue(runtime.request('DAG'))
                release.set()
                runtime.close()
            first.request_stop.assert_called_once_with()
            first.stop.assert_called_once_with()
            later.request_stop.assert_not_called()
            later.stop.assert_not_called()
            self.assertFalse(runtime._workers)
        finally:
            release.set()
            runtime.close()


if __name__ == '__main__':
    unittest.main()
