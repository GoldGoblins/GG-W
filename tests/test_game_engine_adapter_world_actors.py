"""Actual original M2 world geometry/event anchors and the shared native mixer."""
import array
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import struct
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

APP = None


class WorldActorPipeline(unittest.TestCase):
    def setUp(self):
        from backend.game_engine_adapter_formats import PROJECT
        temporary = tempfile.TemporaryDirectory(prefix='gg-world-actor-', dir=PROJECT / 'qml')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        context = patch.dict(os.environ, {'QT_QPA_PLATFORM': 'offscreen', **{
            'XDG_' + name + '_HOME': str(self.root / name.lower()) for name in ('STATE', 'CONFIG', 'CACHE', 'DATA')}})
        context.start()
        self.addCleanup(context.stop)
        from PySide6.QtGui import QGuiApplication
        from backend.game_engine_adapter_formats import AssetCache
        from backend.game_engine_adapter_world_actors import WorldActors
        from backend.game_engine_adapter_entity_audio import EntityAudio
        from backend.game_engine_native_presentation import Audio
        from backend.game_engine_audio_stream import MusicStreams
        from backend.game_engine_audio_short import ShortSounds
        from backend.game_engine_adapter_audio import ZoneAudio
        from tests.test_game_engine_adapter_entity_audio import entity_entries
        from tools.world.engine_format_fixtures import table_dbc, mpq, event_m2, blp, m2
        global APP
        APP = QGuiApplication.instance() or QGuiApplication([])
        files = entity_entries()
        model = [0] * 16
        model[0], model[2], model[4], model[13], model[14], model[15] = 10, 'GG/actor.mdx', 1., 1, 1., 2.
        display = [0] * 12
        display[0], display[1], display[4], display[5] = 100, 10, 1., 255
        self.model_bytes = event_m2([('$FSD', 0, 0, (0, 0, 0), (0, 250, 750)),
                                    ('$DSL', 175, 0, (0, 0, 0), (0,)),
                                    ('$DSE', 0, 0, (0, 0, 0), (750,))])
        from tools.world.engine_world_actor_fixtures import with_socket
        self.model_bytes = with_socket(self.model_bytes)
        files.update({'DBFilesClient/CreatureModelData.dbc': table_dbc([model], 16),
                      'DBFilesClient/CreatureDisplayInfo.dbc': table_dbc([display], 12),
                      'GG/actor.m2': self.model_bytes, 'GG/attachment.m2': m2(), 'gold.blp': blp(), 'GG/gold.blp': blp()})
        data = self.root / 'Data'
        data.mkdir()
        (data / 'model.MPQ').write_bytes(mpq(entries=files))
        self.cache = AssetCache()
        self.addCleanup(self.cache.close)
        self.cache.mount_chain(data)
        self.pool = ThreadPoolExecutor(max_workers=1)
        # The scene facade supplies the authored surface's real catalog ID;
        # all display/model/pose/event decoding below uses the actual native reader.
        self.stream = SimpleNamespace(active=True, cache=self.cache, pool=self.pool,
                                      config={},
                                      query=lambda *at: {'terrain_id': 4}, water_sample=lambda *at: {})
        self.audio = Audio()
        self.audio.gain(1, 1, 1, 1, True)
        self.audio.listener(2, 1, -3, 0)
        self.streams = MusicStreams(self.audio)
        self.short = ShortSounds(self.audio)
        self.now = 0.
        self.zone = ZoneAudio(self.streams, data, clock=lambda: self.now, short_sounds=self.short)
        self.entity = EntityAudio(clock=lambda: self.now)
        self.world = WorldActors(clock=lambda: self.now)
        self.addCleanup(self.close_pipeline)
        self.snapshot = {'player': {'time_s': 0., 'grounded': True, 'vehicle': 'NONE'},
                         'combat_live': {'player': {'alive': True}}, 'event_journal': {'events': []},
                         'render': {'entities': [dict(id='original-player', kind='PLAYER', x=2., y=1., z=-3.,
                                                    yaw=math.pi / 2, sx=1., sy=1., sz=1., motion_state='RUN',
                                                    asset={'appearance': {'display_id': 100, 'animation_id': 7}},
                                                    equipment=[{'slot': 'CHEST', 'material': 2}])]}}

    def close_pipeline(self):
        self.world.close()
        self.entity.close()
        self.pool.shutdown(wait=True, cancel_futures=True)
        self.cache.close()
        self.zone.close()
        self.short.close()
        self.streams.close()
        self.audio.close()

    def update(self, *, running=True, scope='original-character'):
        self.entity.update(self.zone, self.snapshot, self.stream, scope=scope, running=running)
        self.world.update(self.snapshot, self.stream, self.entity, scope=scope, running=running)

    def finish(self):
        if self.world.future is not None:
            self.world.future.result(timeout=5)
            self.assertTrue(self.world.finish())

    def step(self):
        self.now += .01
        self.zone.listener = (2, 1, -3)
        self.zone.update(area_id=99)
        self.streams.pump()
        self.short.pump()
        samples = array.array('f')
        samples.frombytes(self.audio.render(480))
        time.sleep(.001)
        return sum(value * value for value in samples)

    def loaded(self, kit):
        return any(Path(key[0]).name == str(kit) + '.wav' for key in self.short.loaded)

    def test_actual_world_vertices_and_animation_audio_use_the_same_anchor_without_cadence_duplication(self):
        from PySide6.QtGui import QQuaternion, QVector3D
        from backend.game_engine_adapter_formats import NativeFormats
        self.update()
        self.finish()
        self.assertEqual(self.world.actorIds, ['original-player'])
        self.assertTrue(self.entity.actors['player']['model_driven'])
        model = self.world.records['original-player']['model']
        geometry = model.batches[0].geometry
        # Move far enough to trigger GG distance cadence if the actual M2
        # consumer has failed to claim this actor. Only original $FSD survives.
        self.snapshot['player']['time_s'] = .3
        self.snapshot['render']['entities'][0]['x'] = 3.5
        with patch.object(self.entity, 'model_events', wraps=self.entity.model_events) as dispatch, \
             patch.object(self.zone, 'entity_event', wraps=self.zone.entity_event) as triggers:
            self.update()
            self.finish()
            events = [key for call in dispatch.call_args_list if isinstance(call.args[1], dict)
                      for key in call.args[1].get('keys', [])]
            feet = [key for key in events if key['tag'] == '$FSD']
            self.assertEqual([key['time_ms'] for key in feet], [0, 250])
            self.assertEqual([call.args[1] for call in triggers.call_args_list], ['$FSD', '$FSD'])
        self.assertIs(model.batches[0].geometry, geometry)
        self.assertEqual(model.options['cursor_ms'], 300)
        for key in feet:
            for actual, expected in zip(key['position'], (3.5, 1., -3.3)):
                self.assertAlmostEqual(actual, expected, places=5)
        # An independent native identity pose gives the raw Qt vertices.
        # Apply the canonical Qt rotation/translation mathematically and
        # compare every actual retained world vertex from the real batch.
        reference = self.root / 'reference.m2'
        reference.write_bytes(self.model_bytes)
        reader = NativeFormats(self.root)
        self.addCleanup(reader.close)
        meta, blob = reader.decode(reference, runtime=True, anim_id=7, cursor_ms=300, clock_ms=300)
        base = meta['rows'][0]
        result = bytes(geometry.vertexData())
        rotation = QQuaternion.fromEulerAngles(0., 90., 0.)
        for vertex in range(base['vertices']):
            source = struct.unpack_from('<3f', blob, base['offset'] + vertex * base.get('stride', 32))
            want = rotation.rotatedVector(QVector3D(*source)) + QVector3D(3.5, 1., -3.)
            actual = struct.unpack_from('<3f', result, vertex * model.batches[0].stride)
            for a, b in zip(actual, (want.x(), want.y(), want.z())):
                self.assertAlmostEqual(a, b, places=5)
        energy = 0.
        for _ in range(750):
            energy += self.step()
            if self.loaded(171) and self.loaded(174) and 'entity:player' in self.zone.emitters.handles:
                break
        self.assertTrue(self.loaded(171), self.zone.diagnostics())
        self.assertTrue(self.loaded(174), self.zone.diagnostics())
        self.assertIn('entity:player', self.zone.emitters.handles)
        self.assertGreater(energy, .001)
        self.assertFalse(self.short.errors)
        self.snapshot['player']['time_s'] = .8
        self.update()
        self.finish()
        self.assertNotIn('entity:player', self.zone.emitters.handles, 'Actual $DSE must release the original model loop')

    def test_actual_original_socket_outfit_shares_world_anchor_and_retains_child_geometry(self):
        self.snapshot['render']['entities'][0]['asset']['appearance']['attachments'] = [
            {'id': 1, 'model': 'GG/attachment.m2'}]
        self.update()
        self.finish()
        parent = self.world.records['original-player']['model']
        child = parent.children[1]
        geometry = child.batches[0].geometry
        self.assertEqual(len(self.world.batches), 2)
        self.assertFalse(child.attachment_limitations)
        self.assertTrue(child.instance.startswith('attachment:'))
        self.snapshot['player']['time_s'] = .3
        self.snapshot['render']['entities'][0]['x'] = 3.5
        self.update()
        self.finish()
        self.assertIs(parent.children[1], child)
        self.assertIs(child.batches[0].geometry, geometry)
        # Independently decode the actual child through the parent's original
        # socket matrix, with the same authoritative original pose clock.
        # This verifies world anchoring, rather than just an options flag.
        from backend.game_engine_adapter_formats import NativeFormats
        reference = NativeFormats(self.root)
        self.addCleanup(reference.close)
        independent_child = self.root / 'independent-attachment.m2'
        independent_child.write_bytes(child.path.read_bytes())
        metadata, blob = reference.decode(independent_child, runtime=True, anim_id=0,
            cursor_ms=300, clock_ms=300, anchor=parent.attachments['1'])
        row = metadata['rows'][0]
        actual = bytes(geometry.vertexData())
        for index in range(row['vertices']):
            expected = struct.unpack_from('<3f', blob, row['offset'] + index * row.get('stride', 32))
            vertex = struct.unpack_from('<3f', actual, index * child.batches[0].stride)
            for a, b in zip(vertex, expected):
                self.assertAlmostEqual(a, b, places=5)
        self.assertFalse(json.loads(self.world.diagnostics)['errors'])
        self.world.close()
        self.assertTrue(child.closed)
        self.assertFalse(self.cache.attachment_models)
        self.assertEqual(self.cache._reader().request('stats')['effect_instances'], 0)

    def test_completed_late_pose_cannot_emit_after_retirement_pause_or_scope_replacement(self):
        self.update()
        self.finish()
        old = self.world.records['original-player']['model']
        self.snapshot['player']['time_s'] = .3
        self.update()
        self.world.future.result(timeout=5)
        self.snapshot['render']['entities'] = []
        with patch.object(self.entity, 'model_events', wraps=self.entity.model_events) as dispatch:
            self.update()
            self.assertFalse(any(call.args[1] and call.args[1].get('keys') for call in dispatch.call_args_list))
        self.assertTrue(old.closed)
        self.assertFalse(self.cache.live_models)
        self.assertFalse(self.world.actorIds)
        self.assertEqual(self.cache._reader().request('stats')['effect_instances'], 0)
        row = dict(id='original-player', kind='PLAYER', x=2., y=1., z=-3.,
                   asset={'appearance': {'display_id': 100, 'animation_id': 7}}, motion_state='RUN')
        self.snapshot['render']['entities'] = [row]
        self.update()
        self.finish()
        owner = self.world.records['original-player']['owner']
        self.snapshot['player']['time_s'] = .6
        self.update()
        self.world.future.result(timeout=5)
        with patch.object(self.entity, 'model_events', wraps=self.entity.model_events) as dispatch:
            self.update(running=False)
            self.assertFalse(any(call.args[1] and call.args[1].get('keys') for call in dispatch.call_args_list))
        self.assertFalse(self.entity.actors['player']['model_driven'])
        self.snapshot['player']['time_s'] = 5.
        with patch.object(self.entity, 'model_events', wraps=self.entity.model_events) as dispatch:
            self.update()
            self.finish()
            self.assertFalse(any(call.args[1] and call.args[1].get('keys') for call in dispatch.call_args_list))
        self.assertTrue(self.entity.actors['player']['model_driven'])
        retained = self.world.records['original-player']['model']
        self.update(scope='another-character')
        self.finish()
        self.assertTrue(retained.closed)
        self.assertNotEqual(self.world.records['original-player']['owner'], owner)
        self.assertEqual(len(self.cache.live_models), 1)
        self.assertTrue(any(row.get('entity_event') == 'body_loop' for row in self.zone.sound_queue),
                        'Retiring an old canonical player must preserve the new epoch body-loop request')

    def test_missing_original_display_and_capacity_stay_explicit_without_fabricating_a_model(self):
        self.snapshot['render']['entities'][0]['asset']['appearance']['display_id'] = 999
        self.update()
        self.assertEqual(self.world.requestedIds, ['original-player'])
        self.assertFalse(self.world.actorIds)
        self.assertFalse(self.cache.live_models)
        self.assertTrue(any('unknown creature display' in error for error in json.loads(self.world.diagnostics)['errors']))
        row = self.snapshot['render']['entities'][0]
        row['kind'] = 'NPC'
        row['asset']['appearance']['display_id'] = 100
        self.snapshot['render']['entities'] = [dict(deepcopy(row), id='npc-' + str(i), individual={'id': 'person-' + str(i)}) for i in range(150)]
        self.update()
        self.finish()
        self.assertEqual(len(self.world.actorIds), 4)
        self.assertEqual(len(self.world.requestedIds), 128)
        self.assertEqual(len(self.cache.live_models), 4)
        self.assertLessEqual(len(json.loads(self.world.diagnostics)['errors']), 16)
        self.assertTrue(any('capacity exceeded' in error for error in json.loads(self.world.diagnostics)['errors']))
        self.assertIsNone(self.world.future)
        self.world.close()
        self.assertFalse(self.cache.live_models)
        self.assertEqual(self.cache.live_bytes, 0)
        self.assertEqual(self.cache._reader().request('stats')['effect_instances'], 0)

    def test_inactive_presentation_ticks_do_not_churn_qml_collections_and_real_retirement_notifies(self):
        from PySide6.QtTest import QSignalSpy
        self.update()
        self.finish()
        spy = QSignalSpy(self.world.changed)
        old = self.world.records['original-player']['model']
        self.stream.active = False
        self.world.update(self.snapshot, self.stream, self.entity, scope='original-character', running=False)
        self.assertTrue(old.closed)
        self.assertEqual(spy.count(), 1)
        for _ in range(30):
            self.world.update(self.snapshot, self.stream, self.entity, scope='original-character', running=False)
            self.world.close()
        self.assertEqual(spy.count(), 1, 'An inactive world has no visible actor collection change to republish')
        self.assertFalse(self.world.batches)
        self.assertFalse(self.world.requestedIds)

    def test_manifest_binding_is_atomic_and_keeps_real_identity_and_canonical_snapshot_unchanged(self):
        original = deepcopy(self.snapshot)
        self.snapshot['render']['entities'][0]['asset'] = {'source': 'real-gg-crew.glb'}
        untouched = deepcopy(self.snapshot)
        self.stream.config = {'actor_bindings': [{'actor_id': 'player', 'display_id': 100,
                                                'animation_ids': {'RUN': 7, 'IDLE': 7}}]}
        bound = self.world.bound_snapshot(self.snapshot, self.stream)
        self.assertEqual(self.snapshot, untouched)
        self.assertEqual(bound['render']['entities'][0]['id'], untouched['render']['entities'][0]['id'])
        self.assertEqual(bound['render']['entities'][0]['asset']['appearance'], {'display_id': 100, 'animation_id': 7})
        self.entity.update(self.zone, bound, self.stream, scope='bound', running=True)
        self.world.update(bound, self.stream, self.entity, scope='bound', running=True)
        self.finish()
        self.assertTrue(self.entity.actors['player']['model_driven'])
        self.assertEqual(self.world.actorIds, ['original-player'])
        self.assertEqual(self.world.records['original-player']['model'].batches[0].state['world_actor_id'], 'original-player')
        for malformed in ([{'actor_id': 'player', 'display_id': True}],
                          [{'actor_id': 'player', 'display_id': 100, 'animation_ids': {'RUN': -1}}],
                          [{'actor_id': 'player', 'display_id': 100}, {'actor_id': 'player', 'display_id': 101}],
                          [{'actor_id': 'player', 'display_id': 100, 'appearance': {'unknown': 'bad'}}]):
            self.stream.config['actor_bindings'] = malformed
            self.assertIs(self.world.bound_snapshot(self.snapshot, self.stream), self.snapshot)
            self.assertEqual(self.snapshot, untouched)
        self.snapshot = original

    def test_actual_presentation_consumes_mounted_manifest_binding_and_retires_on_unload(self):
        from PySide6.QtCore import QObject
        from backend import game_engine_mmo as mmo, game_engine_character_creation as appearance
        from backend.game_engine_host import GameEngineRuntime
        from backend.game_engine_adapter_streaming import WorldStream
        from backend.game_engine_presentation import Presentation
        from tools.world.engine_world_fixtures import make
        manifest = make(self.root, wmos=False)
        config = json.loads(manifest.read_text())
        config.update(archive_directory=str(self.root / 'Data'), actor_bindings=[{
            'actor_id': 'player', 'display_id': 100, 'animation_ids': {'IDLE': 7, 'STAND': 7, 'RUN': 7, 'WALK': 7}}])
        manifest.write_text(json.dumps(config))
        stream = WorldStream()
        self.addCleanup(stream.close)
        stream.configure(str(manifest))
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            stream.update(-2, 2.65, 20)
            if stream.pages and stream.pending is None:
                break
            time.sleep(.003)
        self.assertTrue(stream.pages, stream.last_error)
        with patch.object(mmo, 'DEFAULT_STASH_PATH', self.root / 'stash.json'), \
             patch.object(appearance, 'STATE_PATH', self.root / 'appearance.json'):
            runtime = GameEngineRuntime()
        self.addCleanup(runtime.shutdown)
        with runtime._lock:
            runtime._engine_world = stream
            runtime._x[0], runtime._y[0], runtime._z[0] = -2., 2.65, 20.
            runtime._running = True
        bridge = QObject()
        bridge._engine_world_stream = stream
        presentation = Presentation(bridge, device=False)
        self.addCleanup(lambda p=presentation, b=bridge: p.close())
        snapshot = runtime.snapshot()
        original = deepcopy(snapshot)
        player_id = next(row['id'] for row in snapshot['render']['entities'] if row['kind'] == 'PLAYER')
        presentation.last_update = 0.
        presentation.update(snapshot)
        if presentation.worldActors.future is not None:
            presentation.worldActors.future.result(timeout=5)
            presentation.worldActors.finish()
        self.assertEqual(snapshot, original)
        self.assertEqual(presentation.worldActors.actorIds, [player_id], presentation.worldActors.diagnostics)
        self.assertTrue(presentation.entity_audio.actors['player']['model_driven'])
        self.assertFalse(presentation.errors)
        retained = presentation.worldActors.records[player_id]['model']
        geometry = retained.batches[0].geometry
        compact = runtime.ui_snapshot()
        self.assertNotIn('entities', compact.get('render', {}))
        presentation.last_update = 0.
        presentation.update(compact)
        self.assertIs(presentation.worldActors.records.get(player_id, {}).get('model'), retained,
            'An inspector-only UI delta is not an authoritative empty world scene')
        self.assertTrue(presentation.entity_audio.actors['player']['model_driven'])
        # A throttled render callback must still replace its rows: the next
        # inspector delta consumes the latest actual position, never the old
        # full snapshot's position or an invented UI-only actor.
        with runtime._lock:
            runtime._x[0] = -3.
            runtime._sim_time = .1
        with runtime._lock:
            latest = runtime.render_snapshot_locked()
        presentation.last_update = time.monotonic()
        presentation.update(latest)
        presentation.last_update = 0.
        presentation.update(runtime.ui_snapshot())
        if presentation.worldActors.future is not None:
            presentation.worldActors.future.result(timeout=5)
            presentation.worldActors.finish()
        self.assertIs(presentation.worldActors.records[player_id]['model'], retained)
        self.assertAlmostEqual(retained.options['anchor'][12], -3., places=5)
        source = retained.path
        attachment_source = stream.cache.resolve('GG/attachment.m2')
        attachment = stream.cache.create_attachment(attachment_source, 'attachment:test:world-actor', retained.options,
            [1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1.])
        # The actual stream's next eviction used to unlink the actor's
        # archive extraction while its retained native pose still used it.
        for time_s in (.3, .8):
            with runtime._lock:
                runtime._sim_time = time_s
            presentation.last_update = 0.
            presentation.update(runtime.snapshot())
            stream.update(-2, 2.65, 20)
            self.assertTrue(source.is_file(), 'World eviction must pin retained original actor sources')
            self.assertTrue(attachment_source.is_file(), 'An original attachment keeps its own source resident')
            stream.cache.pose_attachment(attachment, retained.options,
                [1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1.])
            if presentation.worldActors.future is not None:
                presentation.worldActors.future.result(timeout=5)
                presentation.worldActors.finish()
            self.assertIs(presentation.worldActors.records[player_id]['model'], retained)
            self.assertIs(retained.batches[0].geometry, geometry)
            self.assertFalse(json.loads(presentation.worldActors.diagnostics)['errors'])
            presentation.last_update = 0.
            presentation.update(runtime.ui_snapshot())
            self.assertIs(presentation.worldActors.records[player_id]['model'], retained)
        empty_scene = runtime.snapshot()
        empty_scene['render'] = {**empty_scene['render'], 'entities': []}
        presentation.last_update = 0.
        presentation.update(empty_scene)
        self.assertTrue(retained.closed, 'An explicit canonical empty scene retires its original actors')
        presentation.last_update = 0.
        presentation.update(runtime.ui_snapshot())
        self.assertFalse(presentation.worldActors.actorIds, 'An inspector delta cannot resurrect retired canonical rows')
        with runtime._lock:
            runtime._engine_world = None
            runtime._running = False
        bridge._engine_world_stream = None
        presentation.last_update = 0.
        presentation.update(runtime.snapshot())
        self.assertTrue(retained.closed)
        stream.cache.release_attachment(attachment)
        stream.update(-2, 2.65, 20)
        self.assertFalse(source.exists(), 'Retired actors must release the extraction pin')
        self.assertFalse(attachment_source.exists(), 'Retired attachments must release the extraction pin')
        self.assertFalse(presentation.worldActors.requestedIds)
        self.assertFalse(presentation.worldActors.batches)
        self.assertFalse(presentation.errors)


if __name__ == '__main__':
    unittest.main()
