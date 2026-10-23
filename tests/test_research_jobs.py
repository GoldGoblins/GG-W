"""Exercise job boundaries, cleanup, cancellation and durable report handoff."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import research_jobs as jobs, research_lab as lab, research_desk, research_learning


class ResearchJobsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='gg-research-jobs-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.enterContext(patch.object(jobs, 'ROOT', self.root / 'jobs'))
        self.enterContext(patch.object(lab, 'TOOLS_ROOT', self.root / 'tools'))
        self.enterContext(patch.object(research_desk, 'ROOT', self.root / 'desk'))

    def folder(self, job_id='a' * 32):
        folder = jobs.ROOT / job_id
        (folder / 'scratch').mkdir(parents=True)
        jobs._write(folder / 'state.json', {'job_id': job_id, 'status': 'RUNNING', 'worker_pid': os.getpid()})
        return folder

    def test_project_snapshot_excludes_private_paths_and_symlinks(self):
        project = self.root / 'project'
        project.mkdir()
        (project / 'main.js').write_text("export const known = 'observable';")
        (project / '.env').write_text('private')
        (project / 'credentials.json').write_text('private')
        (project / 'node_modules').mkdir()
        (project / 'node_modules/private.js').write_text('private')
        (project / 'link.js').symlink_to(project / '.env')
        target, _, kind, size = jobs._snapshot(project, self.folder() / 'scratch')
        self.assertEqual(kind, 'JAVASCRIPT PROJECT')
        self.assertEqual([p.name for p in target.iterdir()], ['main.js'])
        self.assertEqual(size, (project / 'main.js').stat().st_size)

    def test_snapshot_isolated_from_later_target_changes(self):
        source = self.root / 'main.js'
        source.write_text('export const observed = 7;')
        target, _, _, _ = jobs._snapshot(source, self.folder() / 'scratch')
        source.write_text('export const observed = 99;')
        self.assertIn('7', (target / 'main.js').read_text())

    def test_project_size_bound_and_private_keys_fail_closed(self):
        source = self.root / 'main.js'
        source.write_text('export const test = 7;')
        project = self.root / 'project'
        project.mkdir()
        (project / 'main.js').write_bytes(b'x' * 100)
        with patch.object(jobs, 'MAX_INPUT', 50):
            with self.assertRaisesRegex(ValueError, 'PROJECT_SIZE_LIMIT'):
                jobs._snapshot(project, self.folder() / 'scratch')
        source.write_text('-----BEGIN PRIVATE KEY-----')
        with self.assertRaisesRegex(ValueError, 'PRIVATE_KEY_MATERIAL'):
            jobs._snapshot(source, self.folder('b' * 32) / 'scratch')

    def test_unsupported_target_is_not_executed(self):
        marker = self.root / 'executed'
        source = self.root / 'program.py'
        source.write_text(f'open({str(marker)!r}, "w").close()')
        with self.assertRaisesRegex(ValueError, 'SELECT_NATIVE_BINARY'):
            jobs._snapshot(source, self.folder() / 'scratch')
        self.assertFalse(marker.exists())

    def test_invalid_operation_and_option_injection_rejected_before_launch(self):
        for operation, query in [('shell', 'touch'), ('function', '--help'), ('decompile', ''), ('xrefs', 'x' * 161)]:
            result = jobs.start('/missing', operation, query)
            self.assertEqual(result['status'], 'ERROR')
        self.assertFalse(jobs.ROOT.exists())

    def test_cancel_stops_process_and_output_is_bounded(self):
        folder = self.folder()
        (folder / 'cancel').touch()
        with self.assertRaisesRegex(ValueError, 'CANCELLED'):
            jobs._run([sys.executable, '-c', 'import time; time.sleep(30)'], folder)
        (folder / 'cancel').unlink()
        with patch.object(jobs, 'MAX_OUTPUT', 100):
            with self.assertRaisesRegex(ValueError, 'OUTPUT_LIMIT'):
                jobs._run([sys.executable, '-c', 'print("x" * 10000)'], folder)

    def test_timeout_and_scratch_budget_stop_jobs(self):
        folder = self.folder()
        with patch.object(jobs, 'TIMEOUT', 0.1):
            with self.assertRaisesRegex(ValueError, 'TIME_LIMIT'):
                jobs._run([sys.executable, '-c', 'import time; time.sleep(30)'], folder)
        (folder / 'scratch/oversized').write_bytes(b'x' * 100)
        with patch.object(jobs, 'MAX_SCRATCH', 50):
            with self.assertRaisesRegex(ValueError, 'SCRATCH_LIMIT'):
                jobs._run([sys.executable, '-c', 'import time; time.sleep(30)'], folder)

    def test_stopped_worker_becomes_error_and_scratch_is_removed(self):
        folder = self.folder()
        result = jobs.status(folder.name)
        self.assertEqual(result['reason'], 'WORKER_STOPPED')
        self.assertFalse((folder / 'scratch').exists())

    def test_running_job_prevents_admission(self):
        source = self.root / 'main.js'
        source.write_text('export const marker = 7;')
        self.folder()
        with patch.object(jobs, '_alive', return_value=True), patch.object(lab, 'tool_inventory', return_value={
                'engines': [{'name': 'REA', 'state': 'READY'}]}):
            self.assertEqual(jobs.start(str(source))['reason'], 'ANALYSIS_ALREADY_RUNNING')

    def test_report_survives_process_cache_and_saves_proposed_lesson(self):
        folder = self.folder()
        report = {'schema': lab.SCHEMA, 'report_id': folder.name, 'status': 'ANALYZED', 'path': '/selected/program',
                  'format': 'ELF', 'engine': 'REA / Ghidra', 'observed_at': '2026-10-08T00:00:00Z',
                  'provenance': 'LOCAL_ENGINE_STATIC_OBSERVATION', 'artifact_sha256': 'f' * 64,
                  'facts': ['Observed function'], 'strings': [], 'limits': ['Static observation'], 'content': {'function': 'main'}}
        jobs._write(folder / 'state.json', {'job_id': folder.name, 'status': 'COMPLETE'})
        jobs._write(folder / 'report.json', report)
        with lab._LOCK:
            lab._REPORTS.clear()
        saved = lab.save_finding(folder.name, 'Native observation', 'main is present.', 'Inspect the function')
        self.assertEqual(saved['status'], 'FINDING_SAVED')
        self.assertEqual(saved['method_status'], 'PROPOSED')
        self.assertEqual(research_learning.verify_method(saved['method_id'])['status'], 'INDEPENDENT_TEST_REQUIRED')

    def test_cleanup_retains_recent_reports_and_never_removes_active_job(self):
        for n in range(5):
            folder = self.folder(f'{n:032x}')
            jobs._write(folder / 'state.json', {'job_id': folder.name, 'status': 'COMPLETE'})
            jobs._write(folder / 'report.json', {'report': 'small'})
        with patch.object(jobs, 'MAX_JOBS', 2):
            jobs._cleanup()
        self.assertEqual(len([p for p in jobs.ROOT.iterdir() if p.is_dir()]), 2)

    def test_invalid_ids_and_symlink_records_cannot_escape_job_root(self):
        for value in ['../../outside', 'a' * 31, 'F' * 32]:
            self.assertEqual(jobs.status(value)['status'], 'ERROR')
        folder = self.folder()
        (folder / 'state.json').unlink()
        (folder / 'state.json').symlink_to(self.root / 'private')
        self.assertEqual(jobs.status(folder.name)['status'], 'ERROR')
        outside = self.root / 'outside'
        (outside / 'scratch').mkdir(parents=True)
        marker = outside / 'scratch/retained'
        marker.write_text('retain')
        (jobs.ROOT / ('b' * 32)).symlink_to(outside, target_is_directory=True)
        jobs._cleanup()
        self.assertTrue(marker.exists())

    def test_method_steps_reach_actual_full_and_compact_turn_context(self):
        from backend.omni_gpt_profiles import build_context
        research_desk.add_method({'name': 'Distinctive native workflow', 'trigger': 'distinctive research',
            'steps': ['Inspect the selected function', 'Compare arithmetic with the fixture'],
            'status': 'PROPOSED', 'proof': 'Independent verification is pending'})
        for compact, budget in [(False, 14000), (True, 2200)]:
            context = build_context('distinctive research', include_registry=not compact, max_chars=budget)
            self.assertIn('[GG RESEARCH MEMORY]', context)
            self.assertIn('Inspect the selected function', context)
            self.assertIn('PROPOSED', context)
            self.assertIn('[/GG RESEARCH MEMORY]', context)
            self.assertLessEqual(len(context), budget)

    def test_pseudocode_layout_is_preserved_while_secrets_are_scrubbed(self):
        text = 'int add(int value) {\n  return value + 7;\n}\npassword=private-value'
        clean = lab._redact_text(text)
        self.assertIn('\n  return value + 7;', clean)
        self.assertNotIn('private-value', clean)

    def test_actual_sandbox_hides_host_files_environment_and_blocks_tool_writes(self):
        entry = lab.TOOLS_ROOT / 'rea/node_modules/rea-agents/scripts/rea.mjs'
        entry.parent.mkdir(parents=True)
        (entry.parents[1] / 'package.json').write_text('{"version":"6.0.0"}')
        private = self.root / 'host-private'
        private.write_text('synthetic fixture only')
        entry.write_text("import fs from 'node:fs';\nlet immutable=false;\n" +
            "try { fs.writeFileSync('/tools/unwanted-write', 'test'); } catch(e) { immutable=true; }\n" +
            "console.log(JSON.stringify({host_file:fs.existsSync(" + json.dumps(str(private)) + ")," +
            "inherited_env:Boolean(process.env.GG_SYNTHETIC_TEST_VALUE),tools_immutable:immutable}));")
        folder = self.folder()
        target = folder / 'scratch/target'
        target.mkdir()
        command = jobs._sandbox(folder / 'scratch', target, 'JAVASCRIPT PROJECT', 'analyze', '')
        with patch.dict(os.environ, {'GG_SYNTHETIC_TEST_VALUE': 'synthetic-fixture'}):
            code, output, _ = jobs._run(command, folder)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output), {'host_file': False, 'inherited_env': False, 'tools_immutable': True})
        self.assertFalse((lab.TOOLS_ROOT / 'unwanted-write').exists())


if __name__ == '__main__':
    unittest.main()
