"""Bounded view reuse without making actual casts trust stale observation."""
import copy
import struct
import unittest
from unittest.mock import patch

import test_game_engine_adapter_spells as fixture
from backend.game_engine_adapter_streaming import Surface


class CountingSight:
    """Count real imported triangle rays; an actual prop enables the wall."""
    def __init__(self, runtime, identity):
        index = runtime._npc_index_for_id_locked(identity)
        x = (runtime._x[index] + runtime._x[0]) / 2
        y, z = runtime._y[index] + .5, runtime._z[index]
        points = ((x, y - 5, z - 5), (x, y + 5, z - 5),
                  (x, y + 5, z + 5), (x, y - 5, z + 5))
        blob = b''.join(struct.pack('<3f', *point) for point in points)
        row = dict(offset=0, vertices=4, stride=12, indices=[0, 1, 2, 0, 2, 3],
                   group=0, prop_key='actual-wall', kind='wmo')
        self.surface = Surface(dict(groups=[{}], collision=[row]), blob)
        self.calls = []
        self.blocked(False)

    def blocked(self, value):
        self.surface.active_props = {'actual-wall'} if value else set()

    def line_of_sight(self, start, end):
        self.calls.append((start, end))
        return self.surface.line_of_sight(start, end)


class SpellObservation(unittest.TestCase):
    setUp = fixture.Spells.setUp
    target = fixture.Spells.target

    def sight(self):
        identity = self.target()
        provider = CountingSight(self.runtime, identity)
        scoped = patch.object(self.runtime, '_engine_world', provider, create=True)
        scoped.start(); self.addCleanup(scoped.stop)
        return identity, provider

    def duplicate_view(self, ref):
        r = self.runtime
        ability = copy.deepcopy(r._content['abilities'][ref])
        r._content['abilities'] = {ref: ability}
        r._actions.slots = [dict(kind='EMPTY', ref='') for _ in r._actions.slots]
        r._actions.slots[0] = dict(kind='ABILITY', ref=ref)
        r._actions.slots[1] = dict(kind='ABILITY', ref=ref)
        r._actions.slots[2] = dict(kind='MACRO', ref='7')
        r._client_macros = {'7': dict(name='Actual ability alias', ability=ref)}

    def start(self, ref, target=None):
        with self.runtime._lock:
            return self.runtime._start_spell_locked(ref, target)

    def test_self_target_and_form_getters_never_scan_units_or_cast_any_world_sight_ray(self):
        _, sight = self.sight(); r = self.runtime; r._combat_target_id = ''
        with patch.object(r, '_legacy_units_locked', wraps=r._legacy_units_locked) as units:
            for ref in ('ability.reef_guard', 'ability.watch_ward', 'ability.tide_mend'):
                ability = r._content['abilities'][ref]
                self.assertEqual(r._spell_target_locked(ability), 'player')
                self.assertTrue(r._spell_availability_locked(ref, ability)['usable'])
            r._spells_view_locked(); r._action_view_locked()
            self.assertEqual(units.call_count, 0)
        self.assertEqual(sight.calls, [])
        r._combat_state['actors']['player']['alive'] = False
        with self.assertRaisesRegex(ValueError, 'SPELL_TARGET_INVALID'):
            r._spell_target_locked(r._content['abilities']['ability.watch_ward'])
        ok, result = self.start('ability.watch_ward')
        self.assertFalse(ok); self.assertEqual(result['error'], 'COMBAT_PLAYER_DEFEATED')
        self.assertEqual(sight.calls, [])

    def test_duplicate_slot_macro_and_catalog_ref_share_one_evaluation_and_fresh_next_view(self):
        _, sight = self.sight(); r = self.runtime; ref = 'ability.island_spark'
        self.duplicate_view(ref); ability = r._content['abilities'][ref]
        expected = r._spell_availability_locked(ref, ability)
        ray_count = len(sight.calls); self.assertGreater(ray_count, 0)
        sight.calls.clear(); tick = r._tick
        with patch.object(r, '_spell_availability_locked', wraps=r._spell_availability_locked) as availability:
            view = r._action_view_locked()
            self.assertEqual(availability.call_count, 1)
        self.assertEqual(len(sight.calls), ray_count)
        for row in view['slots'][:3] + view['abilities']:
            self.assertEqual(row['usable'], expected['usable']); self.assertEqual(row['reason'], expected['reason'])
        sight.blocked(True); sight.calls.clear()
        with patch.object(r, '_spell_availability_locked', wraps=r._spell_availability_locked) as availability:
            next_view = r._action_view_locked()
            self.assertEqual(availability.call_count, 1)
        self.assertFalse(next_view['slots'][0]['usable']); self.assertGreater(len(sight.calls), 0)
        self.assertEqual(r._tick, tick)

    def test_hostile_cast_revalidates_same_tick_wall_party_and_target_death_after_observation(self):
        identity, sight = self.sight(); r = self.runtime; ref = 'ability.island_spark'
        self.duplicate_view(ref); tick = r._tick
        for changed in ('wall', 'party', 'death'):
            with self.subTest(changed=changed):
                sight.blocked(False); r._services['group']['members'] = []
                r._combat_state['actors'][identity]['alive'] = True
                self.assertTrue(r._action_view_locked()['slots'][0]['usable'])
                sight.calls.clear(); before = r._resource
                if changed == 'wall': sight.blocked(True)
                elif changed == 'party': r._services['group']['members'] = [identity]
                else: r._combat_state['actors'][identity]['alive'] = False
                ok, result = self.start(ref)
                self.assertFalse(ok)
                self.assertIn(result['error'], ('SPELL_HOSTILE_TARGET_REQUIRED', 'SPELL_TARGET_NOT_IN_SIGHT', 'SPELL_TARGET_INVALID'))
                self.assertEqual(r._resource, before); self.assertIsNone(r._spell_state['pending'])
                if changed != 'death': self.assertGreater(len(sight.calls), 0)
                self.assertEqual(r._tick, tick)

    def test_friendly_cast_revalidates_same_tick_wall_membership_and_death_after_observation(self):
        identity, sight = self.sight(); r = self.runtime
        definition = copy.deepcopy(r._content['abilities']['ability.island_spark'])
        definition.update(id='ability.actual_friend', name='Authored friendly cast', target='friendly')
        definition['effect'] = dict(heal=5.)
        r._content['abilities'][definition['id']] = definition
        self.duplicate_view(definition['id']); tick = r._tick
        for changed in ('wall', 'membership', 'death'):
            with self.subTest(changed=changed):
                sight.blocked(False); r._services['group']['members'] = [identity]
                r._combat_state['actors'][identity]['alive'] = True
                self.assertTrue(r._action_view_locked()['slots'][0]['usable'])
                sight.calls.clear(); before = r._resource
                if changed == 'wall': sight.blocked(True)
                elif changed == 'membership': r._services['group']['members'] = []
                else: r._combat_state['actors'][identity]['alive'] = False
                ok, result = self.start(definition['id'], identity)
                self.assertFalse(ok)
                self.assertIn(result['error'], ('SPELL_FRIENDLY_TARGET_REQUIRED', 'SPELL_TARGET_NOT_IN_SIGHT', 'SPELL_TARGET_INVALID'))
                self.assertEqual(r._resource, before); self.assertIsNone(r._spell_state['pending'])
                if changed != 'death': self.assertGreater(len(sight.calls), 0)
                self.assertEqual(r._tick, tick)

    def test_pending_cast_still_rechecks_changed_wall_before_damage_or_resource_commit(self):
        identity, sight = self.sight(); r = self.runtime; ref = 'ability.island_spark'
        self.duplicate_view(ref); self.assertTrue(r._action_view_locked()['slots'][0]['usable'])
        health = r._combat_state['actors'][identity]['health']; resource = r._resource; tick = r._tick
        ok, result = self.start(ref); self.assertTrue(ok, result)
        sight.blocked(True); sight.calls.clear()
        with r._lock:
            r._sim_time += .1; r._tick_spells_locked(.1)
        self.assertIsNone(r._spell_state['pending']); self.assertGreater(len(sight.calls), 0)
        self.assertEqual(r._combat_state['actors'][identity]['health'], health)
        self.assertEqual(r._resource, resource); self.assertEqual(r._tick, tick)


if __name__ == '__main__': unittest.main()
