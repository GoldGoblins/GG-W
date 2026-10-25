"""Exercise the real QML damping without touching the running desktop."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QML_DISABLE_DISK_CACHE", "1")
PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from PySide6.QtCore import QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtWidgets import QApplication


class TmogVisualDampingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.engine = QQmlEngine()
        self.component = QQmlComponent(self.engine, QUrl.fromLocalFile(
            str(PROJECT / "qml/components/TmogSurface.qml")))
        self.root = self.component.create()
        self.assertIsNotNone(self.root, [e.toString() for e in self.component.errors()])
        self.engine.globalObject().setProperty("meter", self.engine.newQObject(self.root))

    def tearDown(self):
        self.root.deleteLater()
        self.app.processEvents()

    def js(self, expression):
        result = self.engine.evaluate(expression)
        self.assertFalse(result.isError(), result.toString())
        return result.toVariant()

    def test_step_moves_every_frame_and_settles_without_overshoot(self):
        values = self.js("""(function() {
            meter.liveTicks = 1;
            var readings = [];
            for (var i = 0; i < 60; ++i) {
                meter.applyPulse({cpu_busy: 100, mhz: 3200}, 1/60);
                readings.push(meter.liveCpu);
            }
            return readings;
        })()""")
        self.assertGreater(values[0], 0)
        self.assertLess(values[0], 15)
        self.assertTrue(all(a < b <= 100 for a, b in zip(values, values[1:])))
        self.assertGreater(values[19], 90)
        self.assertGreater(values[-1], 99.8)

    def test_alternating_sample_noise_is_damped_but_history_stays_bounded(self):
        values = self.js("""(function() {
            meter.liveTicks = 1;
            var readings = [];
            for (var i = 0; i < 240; ++i) {
                meter.applyPulse({cpu_busy: i % 2 ? 100 : 0}, 1/60);
                if (i > 180) readings.push(meter.liveCpu);
            }
            return readings;
        })()""")
        self.assertLess(max(values) - min(values), 7)
        self.assertEqual(len(self.root.property("liveCpuHist").toVariant()), 120)

    def test_response_depends_on_elapsed_time_not_number_of_frames(self):
        difference = self.js("""(function() {
            meter.liveTicks = 1;
            var slow = 0, fast = 0;
            for (var i = 0; i < 30; ++i) slow = meter.dampValue(slow, 100, 1/60);
            for (var j = 0; j < 60; ++j) fast = meter.dampValue(fast, 100, 1/120);
            return Math.abs(slow - fast);
        })()""")
        self.assertLess(difference, 0.000001)

    def test_original_damped_histories_advance_each_display_frame(self):
        result = self.js("""(function() {
            meter.page = "PERFORMANCE";
            meter.liveTicks = 1;
            var cpu = [], disk = [], net = [];
            for (var i = 0; i < 12; ++i) {
                meter.applyPulse({cpu_busy:80, mem_used_kb:50, mem_total_kb:100,
                    disk_read_bps:65536, disk_write_bps:0,
                    net_rx_bps:131072, net_tx_bps:0, cores:[i === 0 ? 100 : 0]}, 1/60);
                cpu.push(meter.liveCpu);
                disk.push(meter.liveDiskRead / 1024);
                net.push(meter.liveNetRx / 1024);
            }
            return {cpu:cpu,disk:disk,net:net,cpuHist:meter.liveCpuHist,
                diskHist:meter.liveDiskHist,netHist:meter.liveNetHist,
                coreHist:meter.liveCoreHists[0]};
        })()""")
        for key in ("cpu", "disk", "net"):
            self.assertEqual(len(result[key + "Hist"]), 12)
            for actual, displayed in zip(result[key + "Hist"], result[key]):
                self.assertAlmostEqual(actual, displayed, places=5)
            self.assertTrue(all(a < b for a, b in zip(result[key], result[key][1:])))
        self.assertEqual(len(result["coreHist"]), 12)
        self.assertTrue(all(a > b > 0 for a, b in zip(result["coreHist"], result["coreHist"][1:])))

    def test_io_spring_is_stable_with_uneven_frame_spacing(self):
        values = self.js("""(function() {
            var state = [0, 0], readings = [];
            for (var i = 0; i < 60; ++i) {
                state = meter.springFollow(state[0], state[1], 100, i % 2 ? 0.025 : 0.008);
                readings.push(state[0]);
            }
            return readings;
        })()""")
        self.assertTrue(all(a < b <= 100 for a, b in zip(values, values[1:])))
        self.assertGreater(values[-1], 99.8)


if __name__ == "__main__":
    unittest.main()
