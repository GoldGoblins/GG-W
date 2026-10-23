"""Real LocalCharacters loot: original settings, custody, consent and bypasses."""
import copy
import json
import unittest
from unittest.mock import patch

import test_game_engine_local_custody_services as fixture
from backend import game_engine_items as items


class SavedGroupLoot(unittest.TestCase):
    setUp = fixture.SharedServices.setUp
    bind = fixture.SharedServices.bind
    switch = fixture.SharedServices.switch
    view = fixture.SharedServices.view

    def public(self, op, **fields):
        result = self.runtime.client_control(json.dumps(dict(kind='service', op=op,
            session=self.runtime._service_generation, **fields)))
        self.assertIsNone(result.get('error'), result.get('error'))
        return result

    def join(self, method='group', master=None, threshold=2):
        self.public('GroupInvite', target='Second Hero')
        self.switch(self.second); self.public('GroupAccept'); self.switch(self.first)
        self.public('GroupLoot', method=method, master=master or 'player', threshold=threshold)

    def actual_source(self, *, rarity='RARE', bonding=0):
        source = next(s for s in self.runtime._item_instances.values() if s.get('kind') == 'CONTAINER'
                      and s.get('location') == 'GROUND' and any(i.get('location') == 'CONTAINER'
                      and i.get('container_id') == s['instance_id'] for i in self.runtime._item_instances.values()))
        item = next(i for i in self.runtime._item_instances.values() if i.get('location') == 'CONTAINER'
                    and i.get('container_id') == source['instance_id'])
        definition = items.definition(self.runtime._item_catalog, item['definition_id'])
        definition.update(rarity=rarity, bonding=bonding); item['rarity'] = rarity
        p = source['position']; self.runtime._x[0] = p['x']; self.runtime._y[0] = p['y'] + .65; self.runtime._z[0] = p['z']
        return source, item

    def opened(self, **fields):
        source, item = self.actual_source(**fields)
        result = self.runtime.open_container(source['instance_id'])
        self.assertIsNone(result.get('error'), result.get('error'))
        return source, item, self.runtime._engine_loot['session']

    def pick(self, source, item, session):
        result = self.runtime.loot_slot(session, source['instance_id'], item['instance_id'])
        self.assertIsNone(result.get('error'), result.get('error'))
        return result

    def roll(self):
        return self.runtime._services['loot_rolls'][0]

    def test_shared_nonfreeforall_bulk_opens_actual_window_preserving_custody_then_canonical_window_succeeds(self):
        self.join(); source, item = self.actual_source()
        self.assertIsNone(self.runtime.open_container(source['instance_id']).get('error'))
        before = copy.deepcopy((self.runtime._item_instances, self.runtime._inventory))
        result = self.runtime.loot_container(source['instance_id'])
        self.assertIsNone(result.get('error'), result.get('error'))
        self.assertTrue(result['loot']['open'])
        self.assertEqual((self.runtime._item_instances, self.runtime._inventory), before)
        inactive = self.runtime._local_custody_store.snapshot()['characters'][self.second]
        self.pick(source, item, self.runtime._engine_loot['session'])
        roll = self.roll(); self.assertEqual(roll['eligible'], ['player']); self.assertEqual(roll['votes'], {})
        self.public('LootRollVote', id=roll['id'], vote=1)
        self.assertEqual(self.runtime._item_instances[item['instance_id']]['location'], 'INVENTORY')
        self.assertEqual(self.runtime._local_custody_store.snapshot()['characters'][self.second], inactive)
        self.assertNotIn(self.second, self.runtime._combat_state.get('actors', {}))
        self.assertNotIn(self.second, self.runtime._individual_state['individuals'])

    def test_freeforall_keeps_actual_ground_and_bulk_pickups_enabled(self):
        self.join('freeforall'); source, _ = self.actual_source()
        ground = next(i for i in self.runtime._item_instances.values() if i.get('location') == 'GROUND'
                      and i.get('kind') != 'CONTAINER')
        p = ground['position']; self.runtime._x[0] = p['x']; self.runtime._y[0] = p['y'] + .65; self.runtime._z[0] = p['z']
        picked = self.runtime.pickup_item(ground['instance_id'])
        self.assertIsNone(picked.get('error'), picked.get('error'))
        self.assertEqual(self.runtime._item_instances[ground['instance_id']]['owner_id'], 'player')
        p = source['position']; self.runtime._x[0] = p['x']; self.runtime._y[0] = p['y'] + .65; self.runtime._z[0] = p['z']
        looted = self.runtime.loot_container(source['instance_id'])
        self.assertIsNone(looted.get('error'), looted.get('error')); self.assertGreater(looted['item_result']['count'], 0)
        self.assertFalse(self.runtime._services['loot_rolls'])

    def test_roundrobin_and_below_threshold_award_only_actual_player_without_offline_votes(self):
        self.join('roundrobin'); source, item, session = self.opened()
        self.pick(source, item, session)
        self.assertEqual(self.runtime._item_instances[item['instance_id']]['location'], 'INVENTORY')
        self.assertFalse(self.runtime._services['loot_rolls'])
        self.public('GroupLoot', method='group', threshold=4)
        source, item, session = self.opened(); self.pick(source, item, session)
        self.assertEqual(self.runtime._item_instances[item['instance_id']]['owner_id'], 'player')
        self.assertFalse(self.runtime._services['loot_rolls'])

    def test_pass_and_timeout_leave_exact_physical_item_unbound_in_source(self):
        self.join(); source, item, session = self.opened(bonding=1)
        self.pick(source, item, session); roll = self.roll()
        before = copy.deepcopy(item); self.public('LootRollVote', id=roll['id'], vote=0)
        self.assertEqual(self.runtime._item_instances[item['instance_id']], before)
        self.assertFalse(self.runtime._services['loot_rolls'])
        self.assertIn(item['instance_id'], self.runtime._services['free_loot'])
        self.runtime._services['free_loot'].remove(item['instance_id'])
        self.pick(source, item, session); roll = self.roll()
        self.assertEqual(roll['votes'], {})
        with patch('time.time', return_value=roll['expires'] + 1):
            self.runtime._settle_services_locked()
        self.assertEqual(self.runtime._item_instances[item['instance_id']], before)
        self.assertFalse(self.runtime._services['loot_rolls'])

    def test_binding_confirmation_save_failure_reload_and_once_only_vote_preserve_physical_instance(self):
        self.join(); source, item, session = self.opened(bonding=1)
        self.pick(source, item, session); roll = self.roll(); key = roll['id']
        self.public('LootRollConfirm', id=key, vote=1)
        self.assertEqual(roll['votes'], {})
        self.switch(self.first)
        self.assertEqual(self.roll()['eligible'], ['player']); self.assertEqual(self.roll()['votes'], {})
        before = copy.deepcopy((self.runtime._item_instances, self.runtime._inventory, self.runtime._services['loot_rolls']))
        with patch.object(self.runtime._state_store, 'save', side_effect=OSError('test disk failure')):
            failed = self.runtime.client_control(json.dumps(dict(kind='service', op='LootRollVote', id=key, vote=1)))
        self.assertEqual(failed.get('error'), 'SERVICE_SAVE_FAILED')
        self.assertEqual((self.runtime._item_instances, self.runtime._inventory, self.runtime._services['loot_rolls']), before)
        self.public('LootRollVote', id=key, vote=1)
        actual = copy.deepcopy(self.runtime._item_instances[item['instance_id']])
        self.assertEqual(actual['bound_to'], self.first); self.assertEqual(actual['owner_id'], 'player')
        repeat = self.runtime.client_control(json.dumps(dict(kind='service', op='LootRollVote', id=key, vote=1)))
        self.assertEqual(repeat.get('error'), 'LOOT_ROLL_CHANGED_OR_CLOSED')
        self.switch(self.first); self.assertEqual(self.runtime._item_instances[item['instance_id']], actual)

    def test_needbeforegreed_rejects_unusable_need_and_accepts_actual_greed(self):
        self.join('needbeforegreed'); source, item, session = self.opened()
        items.definition(self.runtime._item_catalog, item['definition_id'])['required_level'] = self.runtime._progression['level'] + 1
        self.pick(source, item, session); roll = self.roll()
        result = self.runtime.client_control(json.dumps(dict(kind='service', op='LootRollVote', id=roll['id'], vote=1)))
        self.assertEqual(result.get('error'), 'LOOT_CANNOT_NEED_UNUSABLE_ITEM')
        self.assertEqual(self.roll()['votes'], {})
        self.public('LootRollVote', id=roll['id'], vote=2)
        self.assertEqual(self.runtime._item_instances[item['instance_id']]['owner_id'], 'player')

    def test_offline_master_never_gets_proxy_candidates_or_award_and_pending_master_rechecks_authority(self):
        self.join('master'); source, item, session = self.opened()
        candidates = self.runtime._loot_view_locked()['master_candidates']
        self.assertEqual(candidates, [self.runtime._local_character_name, None, None, None, None])
        self.pick(source, item, session); key = self.roll()['id']
        self.public('GroupLoot', method='master', master='Second Hero')
        before = copy.deepcopy((self.runtime._item_instances, self.runtime._inventory))
        denied = self.runtime.client_control(json.dumps(dict(kind='service', op='LootMasterGive', id=key, target='player')))
        self.assertEqual(denied.get('error'), 'LOOT_MASTER_REQUIRED')
        self.assertEqual((self.runtime._item_instances, self.runtime._inventory), before)
        self.public('GroupLoot', method='master', master='player')
        with patch.object(self.runtime._state_store, 'save', side_effect=OSError('test disk failure')):
            failed = self.runtime.client_control(json.dumps(dict(kind='service', op='LootMasterGive', id=key, target='player')))
        self.assertEqual(failed.get('error'), 'SERVICE_SAVE_FAILED')
        self.assertEqual((self.runtime._item_instances, self.runtime._inventory), before)
        self.public('LootMasterGive', id=key, target='player')
        self.assertEqual(self.runtime._item_instances[item['instance_id']]['owner_id'], 'player')
        self.public('GroupLoot', method='master', master='Second Hero')
        source, item, session = self.opened(); before = copy.deepcopy(self.runtime._item_instances)
        denied = self.runtime.loot_slot(session, source['instance_id'], item['instance_id'])
        self.assertEqual(denied.get('error'), 'LOOT_MASTER_NOT_PRESENT')
        self.assertEqual(self.runtime._item_instances, before); self.assertFalse(self.runtime._services['loot_rolls'])


if __name__ == '__main__': unittest.main()
