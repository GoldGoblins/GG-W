"""Finite verifier instrumentation preserves evidence after actual worker death."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from PySide6.QtCore import QObject, QUrl
from tools.world.cold_runtime_timings import ColdRuntimeTimings, read_timings

PROJECT = Path(__file__).resolve().parents[1]


class WorldVerifierTimings(unittest.TestCase):
    def test_wrapped_call_preserves_result_exception_and_bounded_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            timings = ColdRuntimeTimings(directory, enabled=True, limit=2)
            loader = QObject()
            loader.setProperty('source', QUrl.fromLocalFile('/authored/some-model.glb'))
            values = []
            def actual(owner, value):
                values.append(value)
                if value == -1: raise ValueError('Fixture failure')
                return owner, value * 2
            measured = timings.wrap('fixture', actual)
            self.assertEqual(measured(loader, 3), (loader, 6))
            with self.assertRaisesRegex(ValueError, 'Fixture failure'): measured(loader, -1)
            for number in range(30): self.assertEqual(measured(loader, number), (loader, number * 2))
            self.assertEqual(len(values), 32)
            evidence = timings.snapshot()['cold_runtime_calls']
            self.assertEqual(len(evidence), 2)
            self.assertTrue(all(row['source'] == 'some-model.glb' and row['completed'] for row in evidence))
            self.assertEqual(evidence[1]['error'], 'ValueError')
            self.assertTrue(all(row['duration_ms'] >= 0 for row in evidence))

    def test_actual_abrupt_child_exit_retains_incomplete_call_source_and_timestamps(self):
        with tempfile.TemporaryDirectory() as directory:
            source = '''import os,sys
from PySide6.QtCore import QObject,QUrl
from tools.world.cold_runtime_timings import ColdRuntimeTimings
timings=ColdRuntimeTimings(sys.argv[1],enabled=True)
timings.stage('app_entered')
loader=QObject();loader.setProperty('source',QUrl.fromLocalFile('/fixture/large-library.glb'))
timings.wrap('named_nodes',lambda loader:os._exit(17))(loader)
'''
            child = subprocess.run([sys.executable, '-B', '-c', source, directory], cwd=PROJECT,
                                   capture_output=True, timeout=5)
            self.assertEqual(child.returncode, 17, child.stderr.decode(errors='replace'))
            evidence = read_timings(directory)
            self.assertEqual([row['name'] for row in evidence['setup_stages']], ['child_started', 'app_entered'])
            self.assertEqual(len(evidence['cold_runtime_calls']), 1)
            row = evidence['cold_runtime_calls'][0]
            self.assertEqual(row['source'], 'large-library.glb')
            self.assertEqual(row['name'], 'named_nodes')
            self.assertFalse(row['completed'])
            self.assertGreater(row['observed_incomplete_ms'], 0)
            self.assertGreaterEqual(row['elapsed_s'], 0)
            self.assertNotIn('/fixture/', str(evidence))


if __name__ == '__main__':
    unittest.main()
