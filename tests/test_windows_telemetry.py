"""Windows telemetry keeps useful rate windows and avoids redundant scans."""
from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import windows_telemetry as metrics


class WindowsTelemetryTests(unittest.TestCase):
    def test_io_rate_is_held_between_counter_reads_and_handles_reset(self):
        clock = [10.0]
        with patch.multiple(metrics, _previous_io=None, _last_pulse_at=0.0,
                            _io_rates=(0.0, 0.0, 0.0, 0.0), _interface=(0.0, "")), \
             patch.object(metrics.time, "monotonic", side_effect=lambda: clock[0]), \
             patch.object(metrics.psutil, "virtual_memory", return_value=SimpleNamespace(
                 used=1024**3, total=2*1024**3, percent=50)), \
             patch.object(metrics.psutil, "cpu_percent", return_value=[20, 40]), \
             patch.object(metrics.psutil, "cpu_freq", return_value=None), \
             patch.object(metrics.psutil, "sensors_battery", return_value=None), \
             patch.object(metrics.psutil, "net_io_counters", side_effect=[
                 SimpleNamespace(bytes_recv=1000, bytes_sent=0),
                 SimpleNamespace(bytes_recv=13000, bytes_sent=0),
                 SimpleNamespace(bytes_recv=0, bytes_sent=0)]) as network, \
             patch.object(metrics.psutil, "disk_io_counters", return_value=None), \
             patch.object(metrics.psutil, "net_if_stats", return_value={
                 "Ethernet": SimpleNamespace(isup=True)}) as interfaces:
            first = metrics.pulse()
            self.assertEqual(first["cpu_busy"], 30)
            self.assertEqual(first["net_rx_bps"], 0)
            clock[0] += 0.016
            self.assertEqual(metrics.pulse()["net_rx_bps"], 0)
            self.assertEqual(network.call_count, 1)
            clock[0] = 10.12
            measured = metrics.pulse()["net_rx_bps"]
            self.assertAlmostEqual(measured, 100000)
            clock[0] = 10.136
            self.assertEqual(metrics.pulse()["net_rx_bps"], measured)
            self.assertEqual(network.call_count, 2)
            self.assertEqual(interfaces.call_count, 1)
            clock[0] = 15.2
            self.assertEqual(metrics.pulse()["net_rx_bps"], 0)
            self.assertEqual(interfaces.call_count, 2)

    def test_inventory_reuses_live_sample_without_stepping_cpu_io_baselines(self):
        live = {"schema": metrics.SCHEMA, "cpu_busy": 33, "cores": [20, 46],
                "mhz": 3000, "mem_pct": 50, "energy_source": "AC",
                "net_rx_bps": 1234, "net_tx_bps": 4321,
                "disk_read_bps": 3456, "disk_write_bps": 6543}
        with patch.object(metrics, "_cached_snapshot", None), \
             patch.object(metrics, "pulse", side_effect=AssertionError("duplicate hardware read")), \
             patch.object(metrics, "_processes", return_value=([{"pid": 1}], {}, 100)) as processes, \
             patch.object(metrics, "_identity", return_value={}):
            data = metrics.snapshot("SUMMARY", live=live)
            self.assertEqual(data["cpu_busy"], 33)
            self.assertEqual(data["net_rx_bps"], 1234)
            self.assertEqual(data["cores"][1]["pct"], 46)
            self.assertEqual(live["cores"], [20, 46])
            processes.assert_called_once_with(fill_limit=17, need_users=False, details=False)


if __name__ == "__main__":
    unittest.main()
