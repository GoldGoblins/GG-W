"""A stalled GUI retains one VT snapshot and receives the final replay state."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QT_QUICK_BACKEND", "software")
_TEST_HOME = tempfile.TemporaryDirectory(prefix="gg-vt-backpressure-test-")
os.environ["GG_DESKTOP_STATE_ROOT"] = str(Path(_TEST_HOME.name) / "state")
os.environ["GG_DESKTOP_DATA_ROOT"] = str(Path(_TEST_HOME.name) / "data")
os.environ["GG_USER_CODEX_HOME"] = str(Path(_TEST_HOME.name) / "codex")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import Qt
from PySide6.QtQuick import QQuickItem
from PySide6.QtWidgets import QApplication

from backend.mini_vt import MiniVt
from backend.terminal_grid import TerminalGrid, _VtHost


class SnapshotBackpressureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_host(self):
        host = _VtHost()
        host.start()
        host.resize(3, 24)
        deliveries = []
        host.snapshotReady.connect(deliveries.append)
        self.addCleanup(self.stop_host, host)
        return host, deliveries

    @staticmethod
    def stop_host(host):
        if host._pulse is not None:
            host._pulse.stop()

    @staticmethod
    def acknowledge(host, snapshot):
        host.acknowledge(snapshot["generation"], snapshot["serial"])

    def test_stalled_consumer_holds_one_snapshot_and_stops_timer(self):
        host, deliveries = self.make_host()
        expected = MiniVt(3, 24)
        total_bytes = 0
        for number in range(100):
            raw = ("row-%03d\r\n" % number).encode() * 4
            expected.feed(raw.decode())
            total_bytes += len(raw)
            host.feed(raw)
            host._emit_snapshot()
            self.assertEqual(len(deliveries), 1)
            self.assertFalse(host._pulse.isActive())
        self.assertTrue(host._dirty)
        self.acknowledge(host, deliveries[0])
        self.assertTrue(host._pulse.isActive())
        host._emit_snapshot()
        self.assertEqual(len(deliveries), 2)
        self.assertEqual(deliveries[-1]["bytes_processed"], total_bytes)
        self.assertEqual(deliveries[-1]["buf"], expected.buf)
        self.assertEqual(deliveries[-1]["history"], expected.history)
        self.assertFalse(host._pulse.isActive())
        self.acknowledge(host, deliveries[-1])
        self.assertFalse(host._pulse.isActive())

    def test_only_matching_delivery_can_release_next_snapshot(self):
        host, deliveries = self.make_host()
        host.feed(b"first")
        host._emit_snapshot()
        first = deliveries[-1]
        host.feed(b" second")
        host.acknowledge(first["generation"] + 1, first["serial"])
        host.acknowledge(first["generation"], first["serial"] + 1)
        host._emit_snapshot()
        self.assertEqual(len(deliveries), 1)
        self.acknowledge(host, first)
        host._emit_snapshot()
        second = deliveries[-1]
        host.feed(b" third")
        self.acknowledge(host, first)
        host._emit_snapshot()
        self.assertEqual(len(deliveries), 2)
        self.assertEqual(host._snapshot_in_flight, (second["generation"], second["serial"]))
        self.acknowledge(host, second)
        host._emit_snapshot()
        self.assertEqual(len(deliveries), 3)

    def test_reset_waits_for_old_delivery_then_sends_complete_new_generation(self):
        host, deliveries = self.make_host()
        host.feed(b"old session\r\n" * 6)
        host._emit_snapshot()
        first = deliveries[-1]
        host.reset(1)
        host.feed(b"new session\r\n")
        host._emit_snapshot()
        self.assertEqual(len(deliveries), 1)
        self.assertFalse(host._pulse.isActive())
        host.acknowledge(1, first["serial"])
        host._emit_snapshot()
        self.assertEqual(len(deliveries), 1)
        self.acknowledge(host, first)
        host._emit_snapshot()
        latest = deliveries[-1]
        self.assertEqual(len(deliveries), 2)
        self.assertEqual(latest["generation"], 1)
        self.assertEqual(latest["history"], [])
        self.assertIn("new session", "".join(cell[0] for cell in latest["buf"][0]))
        self.assertNotIn("old session", repr(latest["buf"]))
        self.assertEqual(latest["bytes_processed"], len(b"old session\r\n" * 6 + b"new session\r\n"))
        host.feed(b"more")
        self.acknowledge(host, first)
        host._emit_snapshot()
        self.assertEqual(len(deliveries), 2)

    def test_shutdown_cannot_be_rearmed_by_late_acknowledgement(self):
        host, deliveries = self.make_host()
        host.feed(b"before shutdown")
        host._emit_snapshot()
        first = deliveries[-1]
        host.feed(b"pending")
        pulse = host._pulse
        # This host is deliberately on the test thread, not a worker thread.
        with patch.object(host, "thread", return_value=None):
            host.shutdown()
        self.acknowledge(host, first)
        host.feed(b"after shutdown")
        host.resize(5, 40)
        host.reset(1)
        host._emit_snapshot()
        self.assertEqual(len(deliveries), 1)
        self.assertFalse(pulse.isActive())
        self.assertIsNone(host._snapshot_in_flight)

    def make_grid(self):
        pane = QQuickItem()
        pane.setWidth(640)
        pane.setHeight(384)
        grid = TerminalGrid(pane)
        grid._ready_emitted = True
        self.addCleanup(self.stop_grid, pane, grid)
        deliveries = []
        # Observe actual worker emissions without draining the GUI's queue.
        grid._host.snapshotReady.connect(deliveries.append, Qt.ConnectionType.DirectConnection)
        return grid, deliveries

    def stop_grid(self, pane, grid):
        grid._stop_worker()
        grid.setParentItem(None)
        self.app.processEvents()

    def wait_without_gui(self, condition):
        deadline = time.monotonic() + 3
        while not condition() and time.monotonic() < deadline:
            time.sleep(0.002)
        self.assertTrue(condition(), "VT worker did not reach the expected state")

    def drain_gui(self, grid):
        deadline = time.monotonic() + 3
        while grid.output_pending() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.002)
        self.assertFalse(grid.output_pending(), "Final VT snapshot did not reach the GUI")

    def test_real_queued_consumer_resumes_with_all_bytes_and_scrollback(self):
        grid, deliveries = self.make_grid()
        chunks = [b"first\r\n" * 30]
        grid.feed_bytes(chunks[0])
        self.wait_without_gui(lambda: len(deliveries) == 1)
        for number in range(80):
            raw = ("history-%03d\r\n" % number).encode() * 3
            chunks.append(raw)
            grid.feed_bytes(raw)
        total_bytes = sum(map(len, chunks))
        self.wait_without_gui(lambda: grid._host._bytes_processed == total_bytes)
        time.sleep(0.08)  # More than two former snapshot periods, GUI still blocked.
        self.assertEqual(len(deliveries), 1)
        self.assertIsNone(grid._snap)
        self.assertTrue(grid.output_pending())
        self.drain_gui(grid)
        self.assertEqual(len(deliveries), 2)
        self.assertEqual(grid._bytes_applied, total_bytes)
        expected = MiniVt(deliveries[-1]["rows"], deliveries[-1]["cols"])
        expected.feed(b"".join(chunks).decode())
        self.assertEqual(grid._snap["buf"], expected.buf)
        self.assertEqual(grid._snap["history"], expected.history)

    def test_real_reset_rejects_queued_old_contents_without_deadlock(self):
        grid, deliveries = self.make_grid()
        grid.feed_bytes(b"OLD SESSION\r\n" * 30)
        self.wait_without_gui(lambda: len(deliveries) == 1)
        grid.reset_terminal()
        grid.feed_bytes(b"NEW SESSION\r\n")
        with patch.object(grid, "_apply_current_snapshot", wraps=grid._apply_current_snapshot) as apply:
            self.drain_gui(grid)
        self.assertTrue(apply.call_args_list)
        self.assertTrue(all(call.args[0]["generation"] == 1 for call in apply.call_args_list))
        self.assertEqual(grid._snap["generation"], 1)
        text = "\n".join("".join(cell[0] for cell in row) for row in grid._snap["buf"])
        self.assertIn("NEW SESSION", text)
        self.assertNotIn("OLD SESSION", text)
        self.assertEqual(grid._snap["history"], [])
        self.assertEqual(len(deliveries), 2)

    def test_stopping_grid_safely_discards_queued_snapshot(self):
        grid, deliveries = self.make_grid()
        grid.feed_bytes(b"queued at shutdown")
        self.wait_without_gui(lambda: len(deliveries) == 1)
        worker = grid._thread
        grid._stop_worker()
        self.assertFalse(worker.isRunning())
        self.app.processEvents()
        self.assertIsNone(grid._snap)


if __name__ == "__main__":
    unittest.main()
