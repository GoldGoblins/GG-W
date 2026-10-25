"""Hardware telemetry keeps one current sample without a visible QML consumer."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import tmog_contract
from backend.tmog_sampler import TmogSampler


class BackgroundTelemetryTests(unittest.TestCase):
    def test_desktop_samples_without_ui_polls_and_stops_on_close(self):
        samples = []
        def pulse():
            samples.append(time.monotonic())
            return {"cpu_busy": len(samples)}

        with patch.object(tmog_contract, "pulse", side_effect=pulse), \
             patch.object(tmog_contract, "snapshot") as inventory, \
             patch("backend.tmog_sampler.IDLE_SECONDS", .04):
            sampler = TmogSampler(isolate=False)
            try:
                sampler.start()
                worker = sampler._meter_thread
                sampler.start()
                self.assertIs(sampler._meter_thread, worker)
                # No pulse()/snapshot() getters and no Qt event loop here.
                time.sleep(.2)
                first = len(samples)
                self.assertGreaterEqual(first, 5)
                time.sleep(.12)
                self.assertGreater(len(samples), first)
                with sampler._lock:
                    latest = json.loads(sampler._pulse_raw)
                self.assertEqual(latest["cpu_busy"], len(samples))
                self.assertEqual(sampler._pages, {})
                self.assertIsNone(sampler._page_thread)
                inventory.assert_not_called()
            finally:
                sampler.close()
                worker = sampler._meter_thread
                if worker is not None:
                    worker.join(timeout=1)
                    self.assertFalse(worker.is_alive())
            count = len(samples)
            sampler.start()
            time.sleep(.05)
            self.assertEqual(len(samples), count)

    def test_blocked_probe_never_queues_more_sampling_requests(self):
        entered = threading.Event()
        released = threading.Event()
        def blocked():
            entered.set()
            released.wait(1)
            return {"cpu_busy": 7}
        with patch.object(tmog_contract, "pulse", side_effect=blocked) as collect:
            sampler = TmogSampler(isolate=False)
            try:
                sampler.start()
                self.assertTrue(entered.wait(1))
                for _ in range(100):
                    sampler.start()
                    sampler.pulse()
                self.assertEqual(collect.call_count, 1)
                started = time.monotonic()
                sampler.close()
                self.assertLess(time.monotonic() - started, .05)
            finally:
                released.set()
                sampler.close()
                if sampler._meter_thread is not None:
                    sampler._meter_thread.join(timeout=1)
                    self.assertFalse(sampler._meter_thread.is_alive())
            self.assertTrue(json.loads(sampler._pulse_raw)["pending"])


if __name__ == "__main__":
    unittest.main()
