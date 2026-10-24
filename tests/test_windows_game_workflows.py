"""Real Windows GAMES flows using original synthetic assets and owned state."""
from __future__ import annotations

import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from backend import game_engine_assets as assets, game_engine_asset_editor as editor
from backend import game_workflow_common as common, game_workflows as workflows
from backend import game_workflow_jobs as jobs, game_workflow_profile as profile
from backend import game_workflow_rig as rig, game_workflow_scout as scout
from backend import game_workflow_collections as collections, game_asset_resources as resources
from backend.platform_process import run_bounded


def triangle():
    value = rig.GLB()
    position = value.accessor([[-1, -1, 0], [1, -1, 0], [0, 1, 0]], 'VEC3', bounds=True)
    normal = value.accessor([[0, 0, 1]] * 3, 'VEC3')
    indices = value.accessor([[0], [1], [2]], 'SCALAR', component=5123)
    value.doc.update(nodes=[{'mesh': 0}], scene=0, scenes=[{'nodes': [0]}],
                     meshes=[{'primitives': [{'attributes': {'POSITION': position, 'NORMAL': normal},
                                              'indices': indices, 'material': 0}]}],
                     materials=[{'doubleSided': True, 'pbrMetallicRoughness': {
                         'baseColorFactor': [.3, .7, .9, 1], 'metallicFactor': 0, 'roughnessFactor': 1}}])
    return bytes(value.finish())


@unittest.skipUnless(os.name == 'nt', 'Windows integration')
class WindowsGameWorkflowsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='gg-games-åäö ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.library = self.root / 'assets room'
        self.library.mkdir()
        self.enterContext(patch.object(common, 'ROOT', self.root / 'state'))

    def write(self, name, data):
        path = self.library / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data if isinstance(data, bytes) else json.dumps(data).encode('utf-8'))
        return path

    def run_job(self, operation, arguments):
        state = jobs.start(operation, arguments)
        self.assertEqual(state['status'], 'QUEUED', state)
        deadline = time.monotonic() + jobs.TIMEOUT + 5
        while state['status'] in jobs.BUSY and time.monotonic() < deadline:
            time.sleep(.03)
            state = jobs.status(state['job_id'])
        self.assertNotIn(state['status'], jobs.BUSY, state)
        return state

    def test_drive_and_file_urls_reach_editor_and_runtime(self):
        source = self.write('model å.glb', triangle())
        with patch.object(assets, 'ASSET_ROOT', self.library):
            for value in (str(source), source.as_uri()):
                self.assertEqual(editor.local_path(value), source)
                self.assertEqual(assets.inspect_asset(value)['status'], 'READY')
            for invalid in ('https://example.invalid/model.glb', 'file://remote-host/model.glb', source.as_uri() + '?query'):
                with self.assertRaises(ValueError):
                    editor.local_path(invalid)
                self.assertNotEqual(assets.inspect_asset(invalid)['status'], 'READY')

    def test_scout_context_candidate_routes_and_rig_use_actual_workers(self):
        source = self.write('original triangle.glb', triangle())
        indexed = self.run_job('scout_index', {'path': self.library.as_uri(), 'game': 'Synthetic Windows game'})
        self.assertEqual(indexed['status'], 'COMPLETE', indexed)
        self.assertEqual(indexed['result']['indexed'], 1)
        self.assertEqual(scout.search('triangle')['hits'][0]['path'], str(source))
        image = workflows.execute('scout_visual', {'keys': [scout.search()['hits'][0]['key']]})
        self.assertEqual(image['status'], 'READY', image)

        binary_data = bytearray(52)
        binary_data[:7] = b'\x7fELF\x01\x01\x01'
        struct.pack_into('<H', binary_data, 18, 8)
        artifact = self.write('observed.elf', bytes(binary_data))
        exported = self.write('function.json', {'name': 'f', 'address': 'ram:00100000',
            'pseudocode': 'int f(void) { return 7; }', 'callees': []})
        packet = self.run_job('context_export', {'path': exported.as_uri(), 'target': artifact.as_uri(), 'query': 'f'})
        self.assertEqual(packet['status'], 'COMPLETE', packet)
        self.assertEqual(packet['result']['context']['provenance'], 'EXTERNAL_EXPORT_UNVERIFIED')
        candidate = self.write('candidate.c', b'int f(void) { return 8; }')
        checked = self.run_job('verify_candidate', {'context': packet['result']['packet_path'], 'candidate': candidate.as_uri()})
        self.assertEqual(checked['status'], 'COMPLETE', checked)
        self.assertEqual(checked['result']['acceptance'], 'REJECTED')

        from test_game_workflows import graph
        route = self.write('route.json', graph('Windows fixture'))
        routed = self.run_job('flow_check', {'path': route.as_uri()})
        self.assertEqual(routed['status'], 'COMPLETE', routed)
        self.assertTrue(routed['result']['oracle']['valid'])

        from test_game_asset_workflow_improvements import fixture_dae, fixture_smd
        dae = self.write('rig.dae', fixture_dae())
        smd = self.write('motion.smd', fixture_smd())
        trial = self.run_job('rig_trial', {'path': dae.as_uri(), 'animation': smd.as_uri(), 'fps': 30, 'basis': 'SMD_LOCAL'})
        self.assertEqual(trial['status'], 'COMPLETE', trial)
        self.assertEqual(trial['result']['matched_joints'], 1)
        self.assertTrue(Path(trial['result']['model_path']).is_file())
        self.assertEqual(artifact.read_bytes(), bytes(binary_data))
        self.assertEqual(candidate.read_bytes(), b'int f(void) { return 8; }')
        self.assertEqual(dae.read_bytes(), fixture_dae())

    def test_operation_error_is_not_reported_as_completed_success(self):
        source = self.write('invalid route.json', {})
        state = self.run_job('flow_check', {'path': source.as_uri()})
        self.assertEqual(state['status'], 'ERROR', state)
        self.assertEqual(state['result']['status'], 'ERROR')
        self.assertEqual(source.read_bytes(), b'{}')

    def test_worker_exit_cannot_overwrite_the_completed_state(self):
        folder = common.ROOT / 'jobs' / ('a' * 32)
        common.write_json(folder / 'state.json', {'job_id': folder.name, 'created': time.time() - 5,
                                                   'status': 'RUNNING', 'pid': 1})
        common.write_json(folder / 'result.json', {'status': 'READY', 'observed': True})
        def completed_during_process_check(_state):
            common.write_json(folder / 'state.json', {'job_id': folder.name, 'created': time.time() - 5,
                                                       'status': 'COMPLETE', 'pid': 1})
            return False
        with patch.object(jobs, '_alive', side_effect=completed_during_process_check):
            state = jobs.status(folder.name)
        self.assertEqual(state['status'], 'COMPLETE')
        self.assertTrue(state['result']['observed'])

    def test_committed_result_survives_exit_before_final_status(self):
        folder = common.ROOT / 'jobs' / ('a' * 32)
        common.write_json(folder / 'state.json', {'job_id': folder.name, 'created': time.time() - 5,
                                                   'status': 'RUNNING', 'pid': 1})
        common.write_json(folder / 'result.json', {'schema': common.SCHEMA, 'status': 'READY', 'observed': True})
        with patch.object(jobs, '_alive', return_value=False):
            state = jobs.status(folder.name)
        self.assertEqual(state['status'], 'COMPLETE')
        self.assertTrue(state['result']['observed'])

    def test_junctions_are_not_followed_by_asset_collections(self):
        from backend.application_paths import expose_directory
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'private.glb').write_bytes(triangle())
        expose_directory(self.library / 'alias', outside)
        self.assertEqual(scout.index(str(self.library))['indexed'], 0)
        self.assertEqual(collections.plan(str(self.library))['collections'], [])
        with self.assertRaisesRegex(ValueError, 'OUTSIDE|SYMLINK'):
            resources.reference(self.library / 'model.gltf', 'alias/private.glb', self.library, common.MAX_FILE)

    def test_candidate_compiler_parses_without_executing(self):
        from backend.game_workflow_verify import syntax_gate
        accepted = syntax_gate('int gg_add(int value) { return value + 7; }')
        self.assertEqual(accepted['state'], 'PASS', accepted)
        rejected = syntax_gate('int gg_add(int value) { return value + 7 }')
        self.assertEqual(rejected['state'], 'FAIL', rejected)

    def test_scene_profile_uses_distributable_qt_capture(self):
        # A generated fixture in the real library keeps the child's normal
        # allowlist. No private or user-authored production asset is changed.
        with tempfile.TemporaryDirectory(prefix='.gg-scene-test-', dir=assets.ASSET_ROOT) as raw:
            source = Path(raw) / 'triangle.glb'
            source.write_bytes(triangle())
            plan = profile.plan([{'path': str(source)}])
            env = {'QT_QPA_PLATFORM': 'offscreen', 'QSG_RHI_BACKEND': 'd3d11',
                   'QSG_RHI_PREFER_SOFTWARE_RENDERER': '1'}
            with patch.dict(os.environ, env):
                os.environ.pop('QT_QUICK_BACKEND', None)
                measured = profile.measure(plan['packet_path'], 3)
            self.assertEqual(measured['status'], 'MEASURED')
            self.assertEqual(set(measured['stages']), set(profile.STAGES))
            self.assertTrue(all(row['samples'] == 3 for row in measured['stages'].values()))
            self.assertEqual(set(measured['screenshots']), set(profile.STAGES))
            for row in measured['screenshots'].values():
                self.assertTrue(Path(row['path']).read_bytes().startswith(b'\x89PNG'))
            self.assertEqual(source.read_bytes(), triangle())

    def test_blender_routes_roundtrip_in_owned_factory_scene(self):
        choices = sorted(Path('C:/Program Files/Blender Foundation').glob('Blender */blender.exe'))
        self.assertTrue(choices, 'Blender required for the existing Blender route bridge')
        code, output, errors, trigger = run_bounded([str(choices[-1]), '--background', '--factory-startup',
            '--python', str(PROJECT / 'tests/test_game_workflows_blender.py')], cwd=PROJECT,
            timeout=40, max_output_bytes=32768)
        self.assertEqual(trigger, 'NONE')
        self.assertEqual(code, 0, (output + errors).decode('utf-8', 'replace'))
        self.assertIn(b'GAME_WORKFLOWS_BLENDER=PASS', output, errors.decode('utf-8', 'replace'))


if __name__ == '__main__':
    unittest.main()
