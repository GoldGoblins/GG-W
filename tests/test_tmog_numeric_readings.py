"""Exercise the real QML JavaScript used for TMOG numeric labels, without a window."""
import json
from pathlib import Path
import unittest

from PySide6.QtCore import QCoreApplication, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine, QQmlExpression


ROOT = Path(__file__).resolve().parents[1]


class TmogNumericReadingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])
        cls.engine = QQmlEngine()
        cls.component = QQmlComponent(cls.engine)
        cls.component.setData(
            b'import QtQml\nimport "TmogReadings.js" as Readings\nQtObject {}',
            QUrl.fromLocalFile(str(ROOT / "qml/components/TmogReadingsTest.qml")),
        )
        if not cls.component.isReady():
            raise AssertionError([error.toString() for error in cls.component.errors()])
        cls.fixture = cls.component.create()
        if cls.fixture is None:
            raise AssertionError([error.toString() for error in cls.component.errors()])
        cls.context = QQmlEngine.contextForObject(cls.fixture)

    @classmethod
    def tearDownClass(cls):
        cls.fixture.deleteLater()
        cls.engine.deleteLater()
        cls.app.processEvents()

    def evaluate(self, expression):
        result = QQmlExpression(self.context, self.fixture, "JSON.stringify(" + expression + ")")
        evaluated = result.evaluate()
        self.assertFalse(result.hasError(), result.error().toString())
        # Qt versions expose the isUndefined out-argument as a tuple.
        if isinstance(evaluated, tuple):
            evaluated, undefined = evaluated
            self.assertFalse(undefined)
        return json.loads(evaluated)

    def test_finite_values_do_not_coerce_missing_or_non_numeric_data(self):
        for expression, expected in (
            ("0", 0), ("12.5", 12.5), ("-2", -2),
            ("null", None), ("undefined", None), ("true", None),
            ("false", None), ('"0"', None), ("NaN", None),
            ("Infinity", None), ("-Infinity", None),
        ):
            with self.subTest(expression=expression):
                self.assertEqual(self.evaluate("Readings.finiteValue(" + expression + ")"), expected)

    def test_probe_keys(self):
        groups = {
            "cpu": ("cpu_busy", "cores"),
            "memory": ("mem_used_kb", "mem_total_kb", "mem_pct"),
            "frequency": ("mhz", "mhz_max"),
            "io": ("disk_read_bps", "disk_write_bps", "net_rx_bps", "net_tx_bps"),
            "": ("temp_c", "gpu_busy", "energy_w"),
        }
        for probe, keys in groups.items():
            for key in keys:
                with self.subTest(key=key):
                    self.assertEqual(self.evaluate(f"Readings.probeKey({json.dumps(key)})"), probe)

    def test_real_zero_is_available_but_null_missing_and_bad_numbers_are_not(self):
        for key in ("cpu_busy", "gpu_busy", "mem_used_kb", "mhz", "net_rx_bps", "energy_w"):
            with self.subTest(key=key):
                self.assertEqual(self.evaluate(f'Readings.value({{{json.dumps(key)}:0}}, {json.dumps(key)})'), 0)
                for raw in ("null", "undefined", '"0"', "true", "NaN", "Infinity"):
                    self.assertIsNone(self.evaluate(f'Readings.value({{{json.dumps(key)}:{raw}}}, {json.dumps(key)})'))
                self.assertIsNone(self.evaluate(f'Readings.value({{}}, {json.dumps(key)})'))

    def test_unavailable_and_probe_failure_metadata_hide_stale_values(self):
        cases = (
            ('{cpu_busy:25,pending:true}', "cpu_busy"),
            ('{cpu_busy:25,error:"OSError"}', "cpu_busy"),
            ('{cpu_busy:25,unavailable:["cpu_busy"]}', "cpu_busy"),
            ('{cpu_busy:25,sample_errors:{cpu:"OSError"}}', "cpu_busy"),
            ('{cpu_busy:25,sampled_at:{cpu:null}}', "cpu_busy"),
            ('{cpu_busy:25,cpu_pending:true}', "cpu_busy"),
            ('{cpu_busy:25,cpu_sample_age_ms:1001}', "cpu_busy"),
            ('{mem_used_kb:25,sample_errors:{memory:"OSError"}}', "mem_used_kb"),
            ('{mhz:2500,sampled_at:{frequency:null}}', "mhz"),
            ('{disk_read_bps:25,sample_errors:{io:"OSError"}}', "disk_read_bps"),
            ('{net_rx_bps:25,sampled_at:{io:null}}', "net_rx_bps"),
        )
        for payload, key in cases:
            with self.subTest(payload=payload, key=key):
                self.assertFalse(self.evaluate(f'Readings.available({payload}, {json.dumps(key)})'))
                self.assertEqual(self.evaluate(f'Readings.text({payload}, {json.dumps(key)}, 1, "%")'), "--")
        self.assertTrue(self.evaluate('Readings.available({cpu_busy:0,cpu_sample_age_ms:1000}, "cpu_busy")'))
        self.assertTrue(self.evaluate('Readings.available({cpu_busy:25,sample_errors:{io:"OSError"}}, "cpu_busy")'))

    def test_invalid_physical_ranges_are_unavailable(self):
        for key, raw in (("cpu_busy", -1), ("cpu_busy", 100.1), ("gpu_busy", 101),
                         ("mem_used_kb", -1), ("mhz", -1), ("mhz_max", -1),
                         ("disk_write_bps", -1), ("net_tx_bps", -1), ("energy_w", -1)):
            with self.subTest(key=key, raw=raw):
                self.assertFalse(self.evaluate(f'Readings.available({{{json.dumps(key)}:{raw}}}, {json.dumps(key)})'))
        self.assertTrue(self.evaluate('Readings.available({cpu_busy:100}, "cpu_busy")'))

    def test_labels_round_mhz_and_preserve_zero_watts_in_both_schemas(self):
        self.assertEqual(self.evaluate('Readings.text({mhz:2456.789123}, "mhz", 0, " MHz")'), "2457 MHz")
        self.assertEqual(self.evaluate('Readings.text({energy_w:12.345678}, "energy_w", 1, " W")'), "12.3 W")
        self.assertEqual(self.evaluate('Readings.text({energy_w:0}, "energy_w", 1, " W")'), "0.0 W")
        self.assertEqual(self.evaluate('Readings.text({energy:{watts:0}}, "energy_w", 1, " W")'), "0.0 W")
        self.assertEqual(self.evaluate('Readings.text({energy_w:null,energy:{watts:50}}, "energy_w", 1, " W")'), "--")
        self.assertEqual(self.evaluate('Readings.text({energy:{watts:50},unavailable:["energy_w"]}, "energy_w", 1, " W")'), "--")

    def test_per_core_labels_accept_live_numbers_and_snapshot_rows(self):
        self.assertEqual(self.evaluate('Readings.coreText({cores:[0,25.678]}, 0)'), "0.0%")
        self.assertEqual(self.evaluate('Readings.coreText({cores:[0,25.678]}, 1)'), "25.7%")
        self.assertEqual(self.evaluate('Readings.coreText({cores:[{id:0,pct:0},{id:1,pct:25.678}]}, 1, 0)'), "26%")
        for payload, index in (
            ('{cores:[0]}', "1"), ('{cores:[0]}', "-1"), ('{cores:[0]}', "0.5"),
            ('{cores:[0]}', '"0"'), ('{cores:[null]}', "0"), ('{cores:[true]}', "0"),
            ('{cores:[{id:0}]}', "0"), ('{cores:[101]}', "0"), ('{cores:[-1]}', "0"),
            ('{cores:[0],pending:true}', "0"), ('{cores:[0],cpu_pending:true}', "0"),
            ('{cores:[0],cpu_sample_age_ms:1001}', "0"),
            ('{cores:[0],sample_errors:{cpu:"OSError"}}', "0"),
            ('{cores:[0],sampled_at:{cpu:null}}', "0"),
            ('{cores:[0],unavailable:["cores"]}', "0"),
            ('{cores:[0],unavailable:["cpu_busy"]}', "0"),
        ):
            with self.subTest(payload=payload, index=index):
                self.assertEqual(self.evaluate(f'Readings.coreText({payload}, {index})'), "--")


if __name__ == "__main__":
    unittest.main()
