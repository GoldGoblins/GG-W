"""Actual owned companions across real native world load/update/unload seams."""
import copy
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QObject
from PySide6.QtGui import QGuiApplication
APP = QGuiApplication.instance() or QGuiApplication([])

from tests import test_game_engine_local_custody_services as fixture
from backend import game_engine_adapter_pet_world as continuity
from backend.game_engine_adapter_formats import PROJECT
from backend.game_engine_adapter_streaming import WorldStream, load_world, update_world
from tools.world import engine_world_fixtures as world


class PetTransitions(unittest.TestCase):
    def setUp(self):
        fixture.SharedServices.setUp(self)
        from backend import game_engine_host
        mocked = patch.object(game_engine_host, '_RUNTIME', self.runtime)
        mocked.start(); self.addCleanup(mocked.stop)
        self.bridge = QObject()
        self.addCleanup(self.unload)
        self.art = tempfile.TemporaryDirectory(dir=PROJECT / 'qml')
        self.addCleanup(self.art.cleanup)
        self.assets = Path(self.art.name)
        self.manifest = world.make(self.assets)
        self.pet = self.tame()
        with self.runtime._lock:
            self.pet.update(x=self.pet['x'] + 2, yaw=31., vx=.25, vz=-.5,
                            target='npc-wanderer-01', command=2, xp=42,
                            learned={'8388865': True, '8388866': True}, training_spent=1)
            self.actor = self.runtime._combat_state['actors']['pet:' + str(self.pet['number'])]
            self.actor['health'] = self.actor['max_health'] * .6
            self.actor['engaged_target'] = self.pet['target']
            self.original = copy.deepcopy(self.pet)
            self.original_actor = copy.deepcopy(self.actor)
            self.player_pose = tuple(getattr(self.runtime, '_' + key)[0] for key in ('x', 'y', 'z', 'vx', 'vy', 'vz'))

    bind = fixture.SharedServices.bind

    def service(self, op, **fields):
        result = self.runtime.client_control(json.dumps(dict(kind='service', op=op,
            session=self.runtime._service_generation, **fields)))
        self.assertNotIn('error', result)
        return result

    def tame(self):
        from backend.game_engine_nature_catalog import ANIMALS, SPECIES
        with self.runtime._lock:
            self.runtime._refresh_nature_locked()
            animal = next(a for a in self.runtime._nature.rows if a['species'] in ANIMALS
                          and SPECIES[a['species']]['domain'] == 'LAND' and not a.get('dead'))
            self.runtime._x[0], self.runtime._y[0], self.runtime._z[0] = animal['x'], animal['y'] + .65, animal['z']
        self.service('PetTame', id=animal['id'])
        return self.runtime._active_pet_locked()

    def configure(self, **fields):
        value = json.loads(self.manifest.read_text())
        value.update(fields)
        self.manifest.write_text(json.dumps(value))

    def load(self):
        result = load_world(self.bridge, str(self.manifest))
        self.assertTrue(result['ok'], result)
        return self.bridge._engine_world_stream

    def distinct_floor(self):
        self.configure(wmos=[],spawn=[-2,100.65,20])
        (self.assets/'Test_32_32.adt').write_bytes(world.terrain(position=(0,0,100)))
        self.assertGreater(abs(self.original['y']-100),.75)

    def assert_return_beside_player(self, pet):
        self.assertEqual(pet['x'],self.runtime._x[0]+1.)
        self.assertEqual(pet['z'],self.runtime._z[0]+1.)
        self.assertEqual(pet['y'],self.runtime._terrain_height_locked(pet['x'],pet['z']))

    def unload(self):
        if hasattr(self.bridge, '_engine_world_stream'):
            return load_world(self.bridge, '')

    def settle(self):
        deadline = time.monotonic() + 10
        stream = self.bridge._engine_world_stream
        while time.monotonic() < deadline:
            update_world(self.bridge)
            if stream.last_error:
                self.fail(stream.last_error)
            if stream.pages and stream.pending is None:
                return stream
            time.sleep(.005)
        self.fail('Actual native pages did not settle')

    def unchanged_progress(self, pet):
        mutable = {'x', 'y', 'z', 'yaw', 'vx', 'vy', 'vz', 'target', 'command'}
        self.assertEqual({k:v for k,v in self.original.items() if k not in mutable},
                         {k:v for k,v in pet.items() if k not in mutable})
        self.assertEqual(self.runtime._combat_state['actors']['pet:' + str(pet['number'])]['health'],
                         self.original_actor['health'])

    def test_actual_world_handoff_preserves_progress_publishes_one_pet_and_restores_own_return_pose(self):
        stream = self.load()
        self.assertEqual(self.runtime._services['active_pet'], self.original['number'])
        self.assertTrue(continuity.pending(self.runtime, self.pet))
        self.assertEqual(self.pet['target'], '')
        self.assertEqual(self.pet['command'], 1)
        self.assertFalse(any(row['id'] == self.pet['id'] for row in self.runtime._nature.rows))
        self.settle()
        pet = self.runtime._active_pet_locked()
        self.assertFalse(continuity.pending(self.runtime, pet))
        self.unchanged_progress(pet)
        floor = stream.query(pet['x'], pet['y'] + .65, pet['z'])
        self.assertTrue(floor['loaded']); self.assertFalse(floor['impassable'])
        self.assertEqual(pet['y'], floor['height'])
        self.assertLessEqual(((pet['x']-self.runtime._x[0])**2+(pet['z']-self.runtime._z[0])**2)**.5, 2.)
        self.assertEqual(sum(row['id'] == pet['id'] for row in self.runtime._nature.rows), 1)
        # Later legitimate progress/combat state is not rolled back by unload.
        pet['xp'] += 7; self.actor['health'] -= 1
        self.unload()
        for key in continuity._POSE:
            if key in self.original: self.assertEqual(pet[key], self.original[key])
        self.assertEqual(pet['xp'], self.original['xp'] + 7)
        self.assertEqual(self.actor['health'], self.original_actor['health'] - 1)
        self.assertEqual(tuple(getattr(self.runtime, '_' + key)[0] for key in ('x','y','z','vx','vy','vz')), self.player_pose)

    def test_pending_tick_cannot_attack_or_publish_old_gg_coordinates_and_saves_no_transition_keys(self):
        self.load()
        actor = copy.deepcopy(self.actor)
        with self.runtime._lock:
            self.runtime._tick_services_locked(1/60)
        self.assertEqual(self.actor, actor)
        self.assertEqual(self.runtime._services['active_pet'], self.original['number'])
        self.assertEqual((self.pet['x'],self.pet['y'],self.pet['z']), tuple(self.original[k] for k in ('x','y','z')))
        self.assertFalse(any(row['id'] == self.pet['id'] for row in self.runtime._nature.rows))
        self.runtime.save_state(snapshot=False)
        saved = self.runtime._state_store.load(self.runtime._persistence_key)
        stored = saved['player']['client_controls']['services']['pets'][0]
        self.assertEqual(set(stored), set(self.original))
        self.assertFalse(any('world_transfer' in key or 'pending_world' in key for key in stored))

    def test_failed_manifest_and_initial_update_have_no_pet_or_player_side_effects(self):
        before = copy.deepcopy((self.pet, self.actor))
        self.configure(schema='wrong')
        self.assertFalse(load_world(self.bridge, str(self.manifest))['ok'])
        self.assertEqual((self.pet,self.actor), before)
        self.configure(schema='gg.engine-world.v1')
        with patch.object(WorldStream, 'update', side_effect=ValueError('Rejected initial world frame')):
            self.assertFalse(load_world(self.bridge, str(self.manifest))['ok'])
        self.assertEqual((self.pet,self.actor), before)
        self.assertIsNone(getattr(self.runtime, '_engine_world', None))
        self.assertEqual(tuple(getattr(self.runtime, '_' + key)[0] for key in ('x','y','z','vx','vy','vz')), self.player_pose)

    def test_repeated_load_refusal_preserves_the_original_return_capture(self):
        stream = self.load(); self.settle()
        before = copy.deepcopy((self.pet,self.actor))
        self.assertFalse(load_world(self.bridge, str(self.manifest))['ok'])
        self.assertEqual((self.pet,self.actor), before)
        self.assertIs(self.runtime._engine_world, stream)
        self.unload()
        for key in continuity._POSE:
            if key in self.original: self.assertEqual(self.pet[key], self.original[key])

    def test_real_floor_hole_and_impassable_page_never_receive_a_pet(self):
        for options in ({'holes':65535}, {'impassable':True}):
            with self.subTest(options=options):
                self.configure(wmos=[])
                (self.assets/'Test_32_32.adt').write_bytes(world.terrain(**options))
                stream = self.load(); self.settle()
                self.assertTrue(continuity.pending(self.runtime, self.pet))
                self.assertEqual((self.pet['x'],self.pet['y'],self.pet['z']), tuple(self.original[k] for k in ('x','y','z')))
                self.assertFalse(any(row['id'] == self.pet['id'] for row in self.runtime._nature.rows))
                self.unload()
                self.assertEqual(self.runtime._services['active_pet'], self.original['number'])
                self.unchanged_progress(self.pet)

    def test_first_terrain_page_cannot_place_before_resident_wmo_raises_floor(self):
        self.configure(spawn=[-8,3.65,12])
        stream = self.load(); deadline = time.monotonic()+10
        while not stream.pages and time.monotonic()<deadline:
            update_world(self.bridge); time.sleep(.005)
        self.assertEqual(len(stream.pages), 1)
        self.assertTrue(continuity.pending(self.runtime,self.pet))
        self.settle()
        self.assertEqual(self.pet['y'],3.)
        self.unchanged_progress(self.pet)

    def test_successful_stable_then_take_before_a_frame_cancels_old_transfer_without_replay(self):
        self.distinct_floor(); stream = self.load()
        self.service('StableOpen'); self.service('StableBuy'); self.service('StableStore')
        self.assertEqual(self.runtime._services['active_pet'],0)
        self.service('StableTake',number=self.pet['number'])
        pet = self.runtime._active_pet_locked()
        self.assertTrue(continuity.pending(self.runtime,pet))
        self.assertFalse(continuity.settle(self.runtime,stream))
        self.settle(); self.assertEqual(pet['y'],100.)
        self.assertEqual(sum(row['id']==pet['id'] for row in self.runtime._nature.rows),1)
        self.unload()
        self.assert_return_beside_player(pet)
        self.assertEqual(self.runtime._services['active_pet'],self.original['number'])
        self.unchanged_progress(pet)

    def test_actual_stable_swap_uses_new_active_pet_and_true_distinct_world_floor(self):
        self.service('StableOpen'); self.service('StableBuy'); self.service('StableStore')
        second = self.tame(); second_state=copy.deepcopy(second)
        self.distinct_floor(); self.load(); self.settle()
        self.service('StableSwap',number=self.original['number'])
        pet=self.runtime._active_pet_locked()
        self.assertEqual(pet['number'],self.original['number'])
        self.assertTrue(continuity.pending(self.runtime,pet))
        self.assertFalse(any(row['id']==pet['id'] for row in self.runtime._nature.rows))
        self.settle(); self.assertEqual(pet['y'],100.)
        self.unchanged_progress(pet)
        self.unload(); self.assert_return_beside_player(pet)
        self.assertEqual(second['number'],second_state['number'])
        self.assertEqual(second['xp'],second_state['xp'])
        self.assertEqual(len(self.runtime._services['pets']),2)

    def test_dead_pending_body_stays_hidden_until_explicit_revive_gets_real_floor(self):
        self.distinct_floor(); self.load()
        self.actor.update(alive=False,health=0.)
        with self.runtime._lock:self.runtime._publish_companions_locked()
        self.assertTrue(continuity.pending(self.runtime,self.pet))
        self.assertFalse(any(row['id']==self.pet['id'] for row in self.runtime._nature.rows))
        self.settle()
        self.assertTrue(continuity.pending(self.runtime,self.pet))
        with self.runtime._lock:self.runtime._publish_companions_locked()
        self.assertFalse(any(row['id']==self.pet['id'] for row in self.runtime._nature.rows))
        self.assertEqual(self.actor['health'],0.)
        self.service('StableOpen'); self.service('PetRevive')
        self.assertTrue(continuity.pending(self.runtime,self.pet))
        self.settle(); self.assertEqual(self.pet['y'],100.)
        self.assertTrue(self.actor['alive']); self.assertEqual(self.actor['health'],self.actor['max_health'])
        self.assertEqual(self.pet['number'],self.original['number'])
        self.assertEqual(self.pet['xp'],self.original['xp'])
        self.unload(); self.assert_return_beside_player(self.pet)
        self.assertTrue(self.actor['alive']); self.assertEqual(self.actor['health'],self.actor['max_health'])

    def test_placed_pet_death_returns_own_corpse_pose_without_resurrection(self):
        self.distinct_floor(); self.load(); self.settle()
        self.actor.update(alive=False,health=0.)
        with self.runtime._lock:self.runtime._publish_companions_locked()
        body=next(row for row in self.runtime._nature.rows if row['id']==self.pet['id'])
        self.assertTrue(body['dead']); self.assertEqual(body['y'],100.)
        self.unload()
        self.assertEqual((self.pet['x'],self.pet['y'],self.pet['z']),tuple(self.original[k] for k in ('x','y','z')))
        body=next(row for row in self.runtime._nature.rows if row['id']==self.pet['id'])
        self.assertTrue(body['dead']); self.assertEqual(body['y'],self.original['y'])
        self.assertFalse(self.actor['alive']); self.assertEqual(self.actor['health'],0.)
        self.assertEqual(self.pet['xp'],self.original['xp'])

    def test_pet_already_dead_before_loading_stays_hidden_in_other_map_and_dead_on_return(self):
        self.actor.update(alive=False,health=0.)
        self.load(); self.settle()
        self.assertTrue(continuity.pending(self.runtime,self.pet))
        with self.runtime._lock:self.runtime._publish_companions_locked()
        self.assertFalse(any(row['id']==self.pet['id'] for row in self.runtime._nature.rows))
        self.unload()
        body=next(row for row in self.runtime._nature.rows if row['id']==self.pet['id'])
        self.assertTrue(body['dead']); self.assertEqual(body['y'],self.original['y'])
        self.assertFalse(self.actor['alive']); self.assertEqual(self.actor['health'],0.)

    def test_dismiss_abandon_and_death_during_pending_never_resurrect(self):
        self.load(); self.service('PetDismiss')
        self.settle(); self.unload()
        self.assertIsNone(self.runtime._active_pet_locked())
        self.assertEqual(self.runtime._services['active_pet'],0)
        # Explicit stable retrieval reactivates the actual existing record.
        self.service('StableOpen'); self.service('StableTake',number=self.original['number'])
        self.pet = self.runtime._active_pet_locked()
        self.load(); self.actor.update(alive=False,health=0.)
        self.settle(); self.unload()
        self.assertFalse(self.actor['alive']); self.assertEqual(self.actor['health'],0.)
        self.service('PetAbandon')
        self.assertFalse(self.runtime._services['pets'])
        self.load(); self.settle(); self.unload()
        self.assertIsNone(self.runtime._active_pet_locked())

    def test_failed_dismiss_rollback_copy_retains_pending_actual_pet(self):
        self.load()
        with patch.object(self.runtime._state_store,'save',side_effect=OSError('Rejected character save')):
            result = self.runtime.client_control(json.dumps(dict(kind='service',op='PetDismiss',session=self.runtime._service_generation)))
        self.assertEqual(result['error'],'SERVICE_SAVE_FAILED')
        pet = self.runtime._active_pet_locked()
        self.assertIsNot(pet,self.pet)
        self.assertTrue(continuity.pending(self.runtime,pet))
        self.settle(); self.unchanged_progress(pet)
        self.unload()
        self.assertEqual((pet['x'],pet['y'],pet['z']),tuple(self.original[k] for k in ('x','y','z')))

    def test_actual_character_switch_and_same_character_reload_never_restore_previous_capture(self):
        self.load()
        self.assertTrue(self.session.logout(),self.session.error)
        self.assertTrue(self.session.enter(self.second),self.session.error)
        pose = tuple(getattr(self.runtime,'_'+key)[0] for key in ('x','y','z'))
        update_world(self.bridge)
        self.assertIsNone(self.runtime._active_pet_locked())
        self.assertIsNone(getattr(self.runtime,'_engine_world',None))
        self.assertEqual(tuple(getattr(self.runtime,'_'+key)[0] for key in ('x','y','z')),pose)
        self.assertTrue(self.session.logout(),self.session.error)
        self.assertTrue(self.session.enter(self.first),self.session.error)
        self.pet = self.runtime._active_pet_locked()
        previous_stream=self.load(); self.runtime.save_state(snapshot=False); self.runtime.load_state()
        replacement = self.runtime._active_pet_locked()
        self.assertTrue(continuity.pending(self.runtime,replacement))
        before = copy.deepcopy(replacement)
        update_world(self.bridge)
        # Durable mounted-map resumption rebinds a fresh provider and current
        # load epoch. It must never reuse the previous live transfer object.
        self.assertIsNotNone(getattr(self.runtime,'_engine_world',None))
        self.assertIsNot(self.runtime._engine_world,previous_stream)
        self.assertTrue(previous_stream.closed)
        self.assertEqual(self.runtime._engine_world.return_scope,continuity.scope(self.runtime))
        self.assertEqual({k:v for k,v in replacement.items() if k not in ('vx','vz')},
                         {k:v for k,v in before.items() if k not in ('vx','vz')})
        self.assertEqual((replacement['vx'],replacement['vz']),(0.,0.))


if __name__ == '__main__':
    unittest.main()
