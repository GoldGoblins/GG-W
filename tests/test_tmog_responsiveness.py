"""Slow system probes must not consume the desktop's frame budget."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
_STATE = tempfile.TemporaryDirectory(prefix="gg-tmog-test-")
os.environ["GG_DESKTOP_STATE_ROOT"] = str(Path(_STATE.name) / "state")
os.environ["GG_DESKTOP_DATA_ROOT"] = str(Path(_STATE.name) / "data")
os.environ["GG_USER_CODEX_HOME"] = str(Path(_STATE.name) / "codex")
PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from PySide6.QtWidgets import QApplication
from backend.chat_surface_host import ChatSurfaceHost
from backend import tmog_contract
from backend.tmog_sampler import TmogSampler


class TmogResponsivenessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait_until(self, condition, timeout=2):
        deadline = time.monotonic() + timeout
        while not condition() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.001)
        self.assertTrue(condition())

    def stop_sampler(self, sampler):
        sampler.close()
        for thread in (sampler._meter_thread, sampler._page_thread):
            if thread is not None:
                thread.join(timeout=1)
                self.assertFalse(thread.is_alive())

    def test_ui_getter_does_not_wait_for_a_slow_windows_probe(self):
        def slow_pulse():
            time.sleep(0.08)
            return {"schema": tmog_contract.SCHEMA, "cpu_busy": 23.0}

        with patch.object(tmog_contract, "pulse", side_effect=slow_pulse), \
             patch("backend.chat_surface_host.TmogSampler", side_effect=lambda: TmogSampler(isolate=False)):
            host = ChatSurfaceHost()
            try:
                began = time.perf_counter()
                json.loads(host.tmogPulse())
                elapsed = time.perf_counter() - began
                self.assertLess(elapsed, 0.01, "TMOG blocks the UI while reading system metrics")
            finally:
                host.shutdown()

    def test_slow_process_inventory_does_not_stall_meters_or_queue_requests(self):
        entered = threading.Event()
        release = threading.Event()
        samples = []
        pages = []

        def pulse():
            samples.append(time.monotonic())
            return {"schema": tmog_contract.SCHEMA, "cpu_busy": len(samples), "cores": []}

        def snapshot(page, *, live):
            pages.append(page)
            if page == "PROCESSES":
                entered.set()
                release.wait(2)
            return {"schema": tmog_contract.SCHEMA, "page": page, "cpu_busy": live["cpu_busy"]}

        with patch.object(tmog_contract, "pulse", side_effect=pulse), \
             patch.object(tmog_contract, "snapshot", side_effect=snapshot):
            sampler = TmogSampler(isolate=False)
            try:
                sampler.snapshot("PROCESSES")
                self.assertTrue(entered.wait(1))
                first = json.loads(sampler.pulse())["cpu_busy"]
                for _ in range(250):
                    sampler.snapshot("PROCESSES")
                    sampler.snapshot("DISK")
                # Only the latest page is pending; old requests are replaced.
                sampler.snapshot("SERVICES")
                time.sleep(0.12)
                self.assertGreaterEqual(json.loads(sampler.pulse())["cpu_busy"] - first, 5)
                self.assertEqual(pages, ["PROCESSES"])
                self.assertTrue(json.loads(sampler.snapshot("SERVICES"))["pending"])
                release.set()
                self.wait_until(lambda: not json.loads(sampler.snapshot("SERVICES")).get("pending"))
                self.assertEqual(pages, ["PROCESSES", "SERVICES"])
                self.assertEqual(json.loads(sampler.snapshot("SERVICES"))["page"], "SERVICES")
            finally:
                release.set()
                self.stop_sampler(sampler)

    def test_fault_preserves_latest_sample_and_recovers(self):
        fail = threading.Event()

        def pulse():
            if fail.is_set():
                raise OSError("unavailable driver")
            return {"schema": tmog_contract.SCHEMA, "cpu_busy": 42}

        with patch.object(tmog_contract, "pulse", side_effect=pulse):
            sampler = TmogSampler(isolate=False)
            try:
                self.wait_until(lambda: json.loads(sampler.pulse()).get("cpu_busy") == 42)
                fail.set()
                self.wait_until(lambda: "error" in json.loads(sampler.pulse()))
                self.assertEqual(json.loads(sampler.pulse())["cpu_busy"], 42)
                fail.clear()
                self.wait_until(lambda: "error" not in json.loads(sampler.pulse()))
            finally:
                self.stop_sampler(sampler)

    def test_idle_and_shutdown_do_not_keep_polling(self):
        with patch.object(tmog_contract, "pulse", return_value={"cpu_busy": 1}) as collect, \
             patch("backend.tmog_sampler.IDLE_SECONDS", 0.06):
            sampler = TmogSampler(isolate=False)
            try:
                sampler.pulse()
                self.wait_until(lambda: collect.call_count > 1)
                time.sleep(0.12)
                count = collect.call_count
                time.sleep(0.08)
                self.assertEqual(collect.call_count, count)
                sampler.pulse()
                self.wait_until(lambda: collect.call_count > count)
            finally:
                self.stop_sampler(sampler)
            count = collect.call_count
            sampler.pulse()
            sampler.snapshot("SUMMARY")
            time.sleep(0.04)
            self.assertEqual(collect.call_count, count)

    def test_close_does_not_wait_for_a_blocked_inventory(self):
        entered = threading.Event()
        release = threading.Event()

        def blocked(page, *, live):
            entered.set()
            release.wait(2)
            return {"page": page}

        with patch.object(tmog_contract, "pulse", return_value={"cpu_busy": 1}), \
             patch.object(tmog_contract, "snapshot", side_effect=blocked):
            sampler = TmogSampler(isolate=False)
            try:
                sampler.snapshot("PROCESSES")
                self.assertTrue(entered.wait(1))
                began = time.perf_counter()
                sampler.close()
                self.assertLess(time.perf_counter() - began, 0.01)
                release.set()
                self.stop_sampler(sampler)
                self.assertTrue(json.loads(sampler.snapshot("PROCESSES"))["pending"])
            finally:
                release.set()
                self.stop_sampler(sampler)

    @unittest.skipUnless(os.name == "nt", "Real Windows telemetry workers")
    def test_isolated_workers_return_real_data_and_exit_on_shutdown(self):
        sampler = TmogSampler(isolate=True)
        try:
            self.wait_until(lambda: bool(json.loads(sampler.pulse()).get("cores"))
                            and not json.loads(sampler.pulse()).get("cpu_pending", True), timeout=5)
            live = json.loads(sampler.pulse())
            self.assertEqual(live["platform"], "Windows")
            self.assertIn("cpu_busy", live)
            self.assertTrue(live["cores"])
            self.wait_until(lambda: bool(json.loads(sampler.snapshot("SUMMARY")).get("processes")), timeout=15)
            snapshot = json.loads(sampler.snapshot("SUMMARY"))
            self.assertGreater(snapshot["process_count"], 0)
            self.assertLessEqual(len(snapshot["processes"]), 17)
            self.assertTrue(any(row["comm"] for row in snapshot["processes"]))
            self.assertFalse(any(row["pid"] == 0 for row in snapshot["processes"]))
            processes = [worker.process for worker in sampler._workers.values()]
            self.assertEqual(len(processes), 2)
            self.assertTrue(all(process.poll() is None for process in processes))
            sampler.close()
            for process in processes:
                process.wait(timeout=3)
        finally:
            self.stop_sampler(sampler)

    @unittest.skipUnless(os.name == "nt", "Real Windows telemetry worker")
    def test_worker_accepts_only_telemetry_operations(self):
        from backend.tmog_worker import TmogWorker
        worker = TmogWorker()
        try:
            with self.assertRaises(ValueError):
                worker.request("unsupported", timeout=3)
            with self.assertRaises(ValueError):
                worker.request("snapshot", page="PROCESSES", live={"cores": [0]*33}, timeout=3)
            self.assertGreater(worker.request("pulse", timeout=3)["mem_total_kb"], 0)
        finally:
            worker.close()


if __name__ == "__main__":
    unittest.main()
