"""Windows observations have real rate windows independent of UI pulse frequency."""
from __future__ import annotations

from contextlib import ExitStack
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import windows_telemetry as metrics


class WindowsTelemetrySamplingTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.clock = 0.0
        self.stack.enter_context(patch.multiple(metrics, _probe_cache={}, _previous_io=None,
            _last_pulse_at=None, _io_rates=(0., 0., 0., 0.), _interface=(None, ""),
            _cached_snapshot=None, _samples={}, _history_stamps={}, _history_clock=None))
        self.stack.enter_context(patch.object(metrics.time, "monotonic", side_effect=lambda: self.clock))
        self.memory = self.stack.enter_context(patch.object(metrics.psutil, "virtual_memory",
            return_value=SimpleNamespace(used=1024**3, available=3*1024**3,
                                         total=4*1024**3, percent=25.0)))
        self.cpu = self.stack.enter_context(patch.object(metrics.psutil, "cpu_percent",
            return_value=[20.0, 40.0]))
        self.frequency = self.stack.enter_context(patch.object(metrics.psutil, "cpu_freq",
            return_value=SimpleNamespace(current=3000.0, max=4200.0)))
        self.battery = self.stack.enter_context(patch.object(metrics.psutil, "sensors_battery", return_value=None))
        self.network = self.stack.enter_context(patch.object(metrics.psutil, "net_io_counters",
            return_value=SimpleNamespace(bytes_recv=1000, bytes_sent=2000)))
        self.disk = self.stack.enter_context(patch.object(metrics.psutil, "disk_io_counters",
            return_value=SimpleNamespace(read_bytes=4000, write_bytes=5000)))
        self.interfaces = self.stack.enter_context(patch.object(metrics.psutil, "net_if_stats",
            return_value={"Ethernet": SimpleNamespace(isup=True)}))

    def at(self, time):
        self.clock = time
        return metrics.pulse()

    def test_first_cpu_read_is_only_a_baseline_and_exact_boundary_matures(self):
        baseline = self.at(0.0)
        self.assertIsNone(baseline["cpu_busy"])
        self.assertTrue(baseline["cpu_pending"])
        self.assertEqual(baseline["cores"], [])
        self.assertIsNone(baseline["sampled_at"]["cpu"])
        self.cpu.assert_called_once_with(interval=None, percpu=True)
        self.at(0.016)
        self.at(0.099)
        self.assertEqual(self.cpu.call_count, 1)
        mature = self.at(0.1)
        self.assertEqual(mature["cpu_busy"], 30)
        self.assertEqual(mature["cores"], [20, 40])
        self.assertFalse(mature["cpu_pending"])
        self.assertEqual(mature["sampled_at"]["cpu"], 0.1)
        self.assertEqual(mature["cpu_sample_interval_ms"], 100)
        self.assertEqual(mature["cpu_sample_age_ms"], 0)
        held = self.at(0.116)
        self.assertEqual(held["sampled_at"]["cpu"], 0.1)
        self.assertEqual(held["cpu_sample_age_ms"], 16)
        self.assertEqual(held["dt"], 0.016)
        self.assertEqual(held["sample_clock"], "monotonic_seconds")

    def test_fast_pulses_do_not_repeat_hardware_reads_or_advance_sample_times(self):
        self.at(0)
        for i in range(1, 60):
            payload = self.at(i / 60)
        # Timer jitter may make a window slightly longer, never shorter.
        self.assertEqual(self.cpu.call_count, 10)
        self.assertEqual(self.network.call_count, 10)
        self.assertEqual(self.disk.call_count, 10)
        self.assertEqual(self.memory.call_count, 4)
        self.assertEqual(self.frequency.call_count, 1)
        self.assertEqual(self.battery.call_count, 1)
        self.assertEqual(self.interfaces.call_count, 1)
        self.assertAlmostEqual(payload["dt"], 1/60, places=4)
        self.assertEqual(payload["sampled_at"]["memory"], .75)
        self.assertEqual(payload["sampled_at"]["frequency"], 0)
        self.assertEqual(payload["sampled_at"]["battery"], 0)
        self.at(1.0)
        self.assertEqual(self.frequency.call_count, 2)
        self.assertEqual(self.battery.call_count, 1)
        self.at(5.0)
        self.assertEqual(self.frequency.call_count, 3)
        self.assertEqual(self.battery.call_count, 2)
        self.assertEqual(self.interfaces.call_count, 2)

    def test_cpu_failure_holds_last_real_value_and_timestamp_then_rebaselines(self):
        self.at(0)
        self.at(.1)
        self.cpu.side_effect = OSError("opaque driver failure")
        failed = self.at(.2)
        self.assertEqual(failed["cpu_busy"], 30)
        self.assertEqual(failed["sampled_at"]["cpu"], .1)
        self.assertEqual(failed["cpu_sample_age_ms"], 100)
        self.assertEqual(failed["sample_errors"]["cpu"], "OSError")
        self.assertNotIn("opaque", json.dumps(failed))
        self.at(.216)
        self.assertEqual(self.cpu.call_count, 3)
        self.cpu.side_effect = None
        self.cpu.return_value = [60.0, 80.0]
        primed = self.at(.3)
        self.assertEqual(primed["cpu_busy"], 30)
        self.assertEqual(primed["sampled_at"]["cpu"], .1)
        recovered = self.at(.4)
        self.assertEqual(recovered["cpu_busy"], 70)
        self.assertEqual(recovered["sampled_at"]["cpu"], .4)
        self.assertEqual(recovered["cpu_sample_interval_ms"], 100)
        self.assertNotIn("cpu", recovered["sample_errors"])

    def test_missing_failed_or_invalid_first_samples_remain_unknown(self):
        self.cpu.side_effect = OSError("driver")
        self.memory.side_effect = OSError("memory query")
        self.frequency.return_value = None
        self.battery.side_effect = OSError("power query")
        payload = self.at(0)
        self.assertTrue(payload["cpu_pending"])
        self.assertIsNone(payload["cpu_busy"])
        self.assertIsNone(payload["mem_pct"])
        self.assertIsNone(payload["mhz"])
        self.assertEqual(payload["energy_source"], "UNKNOWN")
        self.assertIsNone(payload["sampled_at"]["cpu"])
        self.assertIsNone(payload["sampled_at"]["memory"])
        self.assertIn("cpu_busy", payload["unavailable"])
        self.assertIn("mhz", payload["unavailable"])
        self.cpu.side_effect = None
        self.cpu.return_value = [float("nan"), 40]
        self.assertIsNone(self.at(.1)["cpu_busy"])
        self.cpu.return_value = [True, 40]
        self.assertIsNone(self.at(.2)["cpu_busy"])
        self.cpu.return_value = [20, 101]
        self.assertIsNone(self.at(.3)["cpu_busy"])
        self.cpu.return_value = [0, 0]
        self.assertIsNone(self.at(.4)["cpu_busy"])
        self.assertEqual(self.at(.5)["cpu_busy"], 0)
        self.assertFalse(self.at(.516)["cpu_pending"])

    def test_clock_rollback_reprimes_cpu_and_never_reuses_future_sample(self):
        self.at(10)
        before = self.at(10.1)
        self.assertEqual(before["cpu_busy"], 30)
        reset = self.at(2)
        self.assertIsNone(reset["cpu_busy"])
        self.assertEqual(reset["cores"], [])
        self.assertIsNone(reset["sampled_at"]["cpu"])
        self.assertEqual(reset["sampled_at"]["memory"], 2)
        self.assertEqual(reset["dt"], 0)
        recovered = self.at(2.1)
        self.assertEqual(recovered["cpu_busy"], 30)
        self.assertEqual(recovered["sampled_at"]["cpu"], 2.1)
        self.assertEqual(recovered["cpu_sample_interval_ms"], 100)

    def test_io_failure_does_not_publish_false_zero_or_rewrite_observation_time(self):
        self.at(0)
        self.network.return_value = SimpleNamespace(bytes_recv=2000, bytes_sent=4000)
        measured = self.at(.1)
        self.assertEqual(measured["net_rx_bps"], 10000)
        self.network.side_effect = OSError("unavailable adapter")
        failed = self.at(.2)
        self.assertEqual(failed["net_rx_bps"], measured["net_rx_bps"])
        self.assertEqual(failed["sampled_at"]["io"], .1)
        self.assertEqual(failed["sample_errors"]["io"], "OSError")
        self.at(.216)
        self.assertEqual(self.network.call_count, 3)
        self.network.side_effect = None
        self.network.return_value = SimpleNamespace(bytes_recv=3000, bytes_sent=6000)
        recovered = self.at(.3)
        self.assertAlmostEqual(recovered["net_rx_bps"], 5000)
        self.assertEqual(recovered["sampled_at"]["io"], .3)

    def test_slow_probe_errors_keep_successful_value_and_real_timestamp(self):
        self.at(0)
        self.frequency.side_effect = OSError("probe")
        failed = self.at(1)
        self.assertEqual(failed["mhz"], 3000)
        self.assertEqual(failed["sampled_at"]["frequency"], 0)
        self.assertEqual(failed["sample_errors"]["frequency"], "OSError")
        self.at(1.016)
        self.assertEqual(self.frequency.call_count, 2)
        self.frequency.side_effect = None
        self.frequency.return_value = SimpleNamespace(current=3500, max=4200)
        recovered = self.at(2)
        self.assertEqual(recovered["mhz"], 3500)
        self.assertEqual(recovered["sampled_at"]["frequency"], 2)

    def test_snapshot_does_not_invent_zero_history_during_cpu_baseline(self):
        pending = self.at(0)
        with patch.object(metrics, "_identity", return_value={}), \
             patch.object(metrics.psutil, "swap_memory", return_value=SimpleNamespace(used=0, total=0)), \
             patch.object(metrics.psutil, "pids", return_value=[1]), \
             patch.object(metrics.psutil, "boot_time", return_value=0), \
             patch.object(metrics.psutil, "cpu_count", return_value=2):
            data = metrics.snapshot("PERFORMANCE", live=pending)
            self.assertIsNone(data["cpu_busy"])
            self.assertEqual(data["cores"], [])
            self.assertEqual(data["cpu_hist"], [])
            self.assertTrue(data["cpu_pending"])
            for key in ("mem_cached_kb", "mem_buffers_kb", "mem_shared_kb", "mem_slab_kb"):
                self.assertIsNone(data[key])
                self.assertIn(key, data["unavailable"])
            self.assertNotIn("mem_cached_kb", pending["unavailable"])

    def snapshot_at(self, time, live):
        self.clock = time
        with patch.object(metrics, "_identity", return_value={}), \
             patch.object(metrics.psutil, "swap_memory", return_value=SimpleNamespace(used=0, total=0)), \
             patch.object(metrics.psutil, "pids", return_value=[1]), \
             patch.object(metrics.psutil, "boot_time", return_value=0), \
             patch.object(metrics.psutil, "cpu_count", return_value=2):
            return metrics.snapshot("PERFORMANCE", live=live)

    def test_snapshot_histories_do_not_replay_held_values_during_probe_failure(self):
        self.at(0)
        first = self.snapshot_at(.1, self.at(.1))
        initial_histories = {name: first[name + "_hist"] for name in ("cpu", "mem", "net", "disk", "mhz")}
        self.assertEqual(initial_histories["cpu"], [30])
        for probe in (self.cpu, self.memory, self.frequency, self.network):
            probe.side_effect = OSError("probe unavailable")
        failed = self.at(1.1)
        # The page still has to read available memory for its expanded fields;
        # let that separate probe succeed without changing the held live data.
        self.memory.side_effect = None
        failed_page = self.snapshot_at(1.1, failed)
        for name, expected in initial_histories.items():
            self.assertEqual(failed_page[name + "_hist"], expected)
        for moment in (2.1, 3.1):
            self.memory.side_effect = OSError("probe unavailable")
            still_failed = self.at(moment)
            self.memory.side_effect = None
            stale_page = self.snapshot_at(moment, still_failed)
            for name, expected in initial_histories.items():
                self.assertEqual(stale_page[name + "_hist"], expected)
        for probe in (self.cpu, self.frequency, self.network):
            probe.side_effect = None
        self.cpu.return_value = [60, 80]
        self.memory.return_value = SimpleNamespace(used=2*1024**3, available=2*1024**3,
                                                   total=4*1024**3, percent=50)
        self.frequency.return_value = SimpleNamespace(current=3200, max=4200)
        self.network.return_value = SimpleNamespace(bytes_recv=11264, bytes_sent=12288)
        primed = self.snapshot_at(4.1, self.at(4.1))
        self.assertEqual(primed["cpu_hist"], [30])
        recovered = self.snapshot_at(4.4, self.at(4.4))
        self.assertEqual(recovered["cpu_hist"], [30, 70])
        held = self.snapshot_at(4.8, self.at(4.416))
        for name in initial_histories:
            self.assertEqual(held[name + "_hist"], recovered[name + "_hist"])
        self.assertEqual(set(metrics._history_stamps), {"cpu", "mem", "net", "disk", "mhz"})

    def test_snapshot_history_clock_reset_and_legacy_input_are_supported(self):
        self.at(10)
        mature = self.at(10.1)
        first = self.snapshot_at(10.1, mature)
        self.assertEqual(first["cpu_hist"], [30])
        reset = self.at(2)
        reset_page = self.snapshot_at(2, reset)
        self.assertEqual(reset_page["cpu_hist"], [30])
        self.assertEqual(reset_page["mem_hist"], [25, 25])
        reobserved = self.snapshot_at(2.3, self.at(2.3))
        self.assertEqual(reobserved["cpu_hist"], [30, 30])
        self.assertEqual(self.snapshot_at(2.6, reobserved)["cpu_hist"], [30, 30])
        unobserved = dict(reobserved, sampled_at={key: None for key in reobserved["sampled_at"]})
        self.assertEqual(self.snapshot_at(2.9, unobserved)["cpu_hist"], [30, 30])
        legacy = dict(reobserved)
        legacy.pop("sampled_at")
        self.assertEqual(self.snapshot_at(3.2, legacy)["cpu_hist"], [30, 30, 30])
        self.assertEqual(self.snapshot_at(3.5, legacy)["cpu_hist"], [30, 30, 30, 30])


if __name__ == "__main__":
    unittest.main()
