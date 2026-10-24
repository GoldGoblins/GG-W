"""Real WASM growth caps, Windows-safe input and asynchronous cancellation."""
from __future__ import annotations

import base64
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import qip_lab
from backend.platform_files import mode_matches
from test_qip_lab import minimal_qip_module, section, uleb


def growth_module(*, table=False):
    # Store memory.grow/table.grow's result at byte 32, then return those bytes.
    # Requests exceed the runtime cap by one page/entry; a capped grow yields -1.
    grow = (b'\xd0\x70\x41' + uleb(qip_lab.MAX_TABLE_ENTRIES + 1) + b'\xfc\x0f\x00'
            if table else b'\x41' + uleb(qip_lab.MAX_MEMORY_PAGES) + b'\x40\x00')
    instructions = b'\x41\x20' + grow + b'\x36\x02\x00\x42' + uleb((32 << 32) | 4) + b'\x0b'
    body = b'\x00' + instructions
    return (b'\x00asm\x01\x00\x00\x00'
            + section(1, b'\x01\x60\x01\x7f\x01\x7e')
            + section(3, b'\x01\x00')
            + (section(4, b'\x01\x70\x00\x00') if table else b'')
            + section(5, b'\x01\x00\x01')
            + section(7, b'\x02\x06memory\x02\x00\x06render\x00\x00')
            + section(10, b'\x01' + uleb(len(body)) + body))


class QipRuntimeLimitsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='gg-qip-limits-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / 'fixture.wasm'
        self.path.write_bytes(minimal_qip_module())

    def wait(self, job):
        deadline = time.monotonic() + 7
        while job['state'] in {'RUNNING', 'CANCELLING'} and time.monotonic() < deadline:
            time.sleep(.01)
            job = qip_lab.job_status(job['job_id'])
        self.assertNotIn(job['state'], {'RUNNING', 'CANCELLING'})
        return job

    @unittest.skipUnless(shutil.which('node'), 'Node runtime required')
    def test_full_input_limit_uses_private_files_and_leaves_no_scratch(self):
        real_run = qip_lab.run_bounded
        captured = []
        payload = 'x' * qip_lab.MAX_INPUT_BYTES

        def inspect_launch(argv, **kwargs):
            self.assertLess(len(' '.join(argv)), 12000)
            self.assertNotIn(payload, ' '.join(argv))
            module, input_file = map(Path, argv[-2:])
            captured.append(module.parent)
            self.assertTrue(mode_matches(module.parent, 0o700))
            self.assertTrue(mode_matches(input_file, 0o600))
            self.assertEqual(input_file.read_bytes(), payload.encode())
            return real_run(argv, **kwargs)

        with patch.object(qip_lab, 'run_bounded', side_effect=inspect_launch):
            result = qip_lab.run_file(str(self.path), payload)
        self.assertEqual(result['state'], 'DONE', result)
        self.assertEqual(result['input_bytes'], qip_lab.MAX_INPUT_BYTES)
        self.assertTrue(captured)
        self.assertFalse(captured[0].exists())

    @unittest.skipUnless(shutil.which('node'), 'Node runtime required')
    def test_memory_without_declared_maximum_cannot_grow_past_runtime_cap(self):
        self.path.write_bytes(growth_module())
        result = qip_lab.run_file(str(self.path), '')
        self.assertEqual(result['state'], 'DONE', result)
        self.assertEqual(struct.unpack('<i', base64.b64decode(result['output_base64']))[0], -1)

    @unittest.skipUnless(shutil.which('node'), 'Node runtime required')
    def test_table_without_declared_maximum_cannot_grow_past_runtime_cap(self):
        self.path.write_bytes(growth_module(table=True))
        result = qip_lab.run_file(str(self.path), '')
        self.assertEqual(result['state'], 'DONE', result)
        self.assertEqual(struct.unpack('<i', base64.b64decode(result['output_base64']))[0], -1)

    @unittest.skipUnless(shutil.which('node'), 'Node runtime required')
    def test_source_replacement_after_inspection_cannot_change_executed_bytes(self):
        real_inspect = qip_lab.inspect_bytes

        def replace_source(data, **kwargs):
            result = real_inspect(data, **kwargs)
            self.path.write_bytes(b'not the inspected module')
            return result

        with patch.object(qip_lab, 'inspect_bytes', side_effect=replace_source):
            result = qip_lab.run_file(str(self.path), '')
        self.assertEqual(result['state'], 'DONE', result)
        self.assertEqual(result['output_text'], 'OK')

    def test_oversized_file_is_rejected_before_reading_payload(self):
        with self.path.open('r+b') as stream:
            stream.truncate(qip_lab.MAX_MODULE_BYTES + 1)
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('unbounded file read')):
            result = qip_lab.inspect_file(str(self.path))
            execution = qip_lab.run_file(str(self.path), '')
        self.assertEqual(result['reason'], 'QIP_MODULE_TOO_LARGE')
        self.assertEqual(execution['state'], 'BLOCKED')
        self.assertEqual(execution['inspection']['reason'], 'QIP_MODULE_TOO_LARGE')

    def test_cancel_before_result_publication_wins_over_fast_completion(self):
        entered = threading.Event()
        finish = threading.Event()

        def complete(*args, **kwargs):
            entered.set()
            self.assertTrue(finish.wait(timeout=3))
            return {'schema': qip_lab.SCHEMA, 'state': 'DONE', 'output_text': 'completed'}

        with patch.object(qip_lab, 'run_file', side_effect=complete):
            job = qip_lab.start(str(self.path), '')
            self.assertTrue(entered.wait(timeout=3))
            try:
                self.assertEqual(qip_lab.cancel(job['job_id'])['state'], 'CANCELLING')
            finally:
                finish.set()
            self.assertEqual(self.wait(job)['state'], 'CANCELLED')


if __name__ == '__main__':
    unittest.main()
