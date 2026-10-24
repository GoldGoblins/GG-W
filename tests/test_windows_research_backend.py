"""Windows paths, native fixtures and real asynchronous WASM execution."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
import threading
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import qip_lab, research_jobs, research_desk, research_lab
from test_qip_lab import minimal_qip_module


class ResearchBackendTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='gg-research-backend-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_file_urls_with_unicode_spaces_reach_every_inspector(self):
        from backend.game_workflow_common import local_path
        path = self.root / '\u00e5\u00e4\u00f6 module.wasm'
        path.write_bytes(minimal_qip_module())
        self.assertEqual(local_path(path.as_uri()), path)
        self.assertEqual(research_lab.inspect_file(path.as_uri())['format'], 'WASM')
        self.assertEqual(qip_lab.inspect_file(path.as_uri())['state'], 'READY')
        self.assertEqual(qip_lab.inspect_file('file://other-host/C:/program.wasm')['state'], 'BLOCKED')

    def test_job_records_round_trip_unicode(self):
        path = self.root / 'record.json'
        research_jobs._write(path, {'name': '\u00e5\u00e4\u00f6\u2192'})
        self.assertEqual(research_jobs._read(path)['name'], '\u00e5\u00e4\u00f6\u2192')

    @unittest.skipUnless(os.name == 'nt', 'Windows UNC semantics')
    def test_remote_shares_are_rejected_before_filesystem_access(self):
        from backend.game_workflow_common import local_path
        with patch.object(Path, 'resolve', side_effect=AssertionError('Unexpected network path access')):
            for resolve in (research_lab._path, qip_lab._path_from_url, local_path):
                with self.assertRaises(ValueError):
                    resolve(r'\\other-host\share\program.bin')

    @unittest.skipUnless(os.name == 'nt', 'Windows file-sharing semantics')
    def test_job_state_write_survives_an_active_windows_reader(self):
        path = self.root / 'state.json'
        research_jobs._write(path, {'status': 'RUNNING'})
        opened = threading.Event()

        def read_briefly():
            with path.open('rb') as stream:
                opened.set()
                time.sleep(.08)
                stream.read()

        reader = threading.Thread(target=read_briefly)
        reader.start()
        self.assertTrue(opened.wait(1))
        research_jobs._write(path, {'status': 'COMPLETE'})
        reader.join(1)
        self.assertEqual(research_jobs._read(path)['status'], 'COMPLETE')

    def wait(self, job):
        deadline = time.monotonic() + 7
        while job['state'] in {'RUNNING', 'CANCELLING'} and time.monotonic() < deadline:
            time.sleep(.02)
            job = qip_lab.job_status(job['job_id'])
        self.assertNotIn(job['state'], {'RUNNING', 'CANCELLING'})
        return job

    def test_wasm_returns_immediately_then_produces_actual_output(self):
        path = self.root / 'module.wasm'
        path.write_bytes(minimal_qip_module())
        began = time.monotonic()
        job = qip_lab.start(path.as_uri(), '{}')
        self.assertLess(time.monotonic() - began, .2)
        self.assertEqual(job['state'], 'RUNNING')
        result = self.wait(job)
        self.assertEqual(result['state'], 'DONE', result)
        self.assertEqual(result['output_text'], 'OK')

    def test_wasm_cancel_stops_actual_runtime(self):
        path = self.root / 'module.wasm'
        path.write_bytes(minimal_qip_module())
        job = qip_lab.start(str(path), '{}')
        qip_lab.cancel(job['job_id'])
        self.assertEqual(self.wait(job)['state'], 'CANCELLED')

    def test_eval_runs_started_in_the_same_second_are_distinct(self):
        with patch.object(research_desk, 'ROOT', self.root / 'desk'), patch.object(research_desk, '_now', return_value='2026-10-23T00:00:00Z'):
            one = research_desk.start_run(eval_name='same')
            two = research_desk.start_run(eval_name='same')
            self.assertNotEqual(one['run_id'], two['run_id'])
            self.assertEqual(research_desk.finish_run(one['run_id'])['status'], 'RUN_FINISHED')
            self.assertEqual(research_desk.finish_run(two['run_id'])['status'], 'RUN_FINISHED')

    def test_nonfinite_or_invalid_eval_scores_do_not_finish_run(self):
        with patch.object(research_desk, 'ROOT', self.root / 'desk'):
            run = research_desk.start_run()
            for score in (float('nan'), float('inf'), -1, 2, True, 'bad'):
                result = research_desk.finish_run(run['run_id'], score=score)
                self.assertEqual(result['status'], 'ERROR')
                self.assertEqual(research_desk.snapshot()['runs'][0]['status'], 'RUNNING')
            self.assertEqual(research_desk.finish_run(run['run_id'], score=.5)['status'], 'RUN_FINISHED')


if __name__ == '__main__':
    unittest.main()
