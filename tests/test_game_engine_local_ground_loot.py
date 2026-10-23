"""Actual combat drops are one real canonical source, never fake containers."""
import copy
import json
import unittest
from unittest.mock import patch

import test_game_engine_local_groups_loot as fixture
from backend import game_engine_items as items


class GroundGroupLoot(unittest.TestCase):
    setUp = fixture.SavedGroupLoot.setUp
    bind = fixture.SavedGroupLoot.bind
    switch = fixture.SavedGroupLoot.switch
    view = fixture.SavedGroupLoot.view
    public = fixture.SavedGroupLoot.public
    join = fixture.SavedGroupLoot.join
    roll = fixture.SavedGroupLoot.roll
    pick = fixture.SavedGroupLoot.pick

    def combat_drop(self, *, bonding=0, rarity='RARE'):
        index = self.runtime._npc_index_for_id_locked('npc-wanderer-01')
        self.assertIsNotNone(index)
        spawned = self.runtime._spawn_combat_loot_locked('npc-wanderer-01', index)
        self.assertTrue(spawned['created'], spawned)
        item = self.runtime._item_instances[spawned['instance_id']]
        definition = items.definition(self.runtime._item_catalog, item['definition_id'])
        definition.update(rarity=rarity, bonding=bonding)
        item.update(rarity=rarity, rarity_color=items.rarity_style(rarity)['color'])
        p = item['position']
        self.runtime._x[0] = p['x']; self.runtime._y[0] = p['y'] + .65; self.runtime._z[0] = p['z']
        return item

    def opened_drop(self, **fields):
        item = self.combat_drop(**fields)
        before = copy.deepcopy((self.runtime._item_instances, self.runtime._inventory))
        result = self.runtime.pickup_item(item['instance_id'])
        self.assertIsNone(result.get('error'), result.get('error'))
        self.assertEqual((self.runtime._item_instances, self.runtime._inventory), before)
        self.assertTrue(result['loot']['open'])
        self.assertEqual(result['loot']['rows'][0]['instance_id'], item['instance_id'])
        self.assertEqual(self.runtime._engine_loot['source_kind'], 'GROUND')
        self.assertEqual(self.runtime._engine_loot['ids'], (item['instance_id'],))
        return item, self.runtime._engine_loot['session']

    def test_actual_combat_drop_opens_without_transfer_then_need_awards_exact_instance_once(self):
        self.join(); item, session = self.opened_drop()
        inactive = self.runtime._local_custody_store.snapshot()['characters'][self.second]
        self.pick(item, item, session)
        roll = self.roll()
        self.assertEqual(roll['source'], item['instance_id']); self.assertEqual(roll['source_kind'], 'GROUND')
        self.assertEqual(roll['eligible'], ['player']); self.assertEqual(roll['votes'], {})
        self.public('LootRollVote', id=roll['id'], vote=1)
        actual = copy.deepcopy(self.runtime._item_instances[item['instance_id']])
        self.assertEqual(actual['location'], 'INVENTORY'); self.assertTrue(actual['loot_claimed'])
        self.assertEqual(actual.get('contents', []), []); self.assertFalse(actual.get('container_state'))
        repeat = self.runtime.client_control(json.dumps(dict(kind='service', op='LootRollVote', id=roll['id'], vote=1)))
        self.assertEqual(repeat.get('error'), 'LOOT_ROLL_CHANGED_OR_CLOSED')
        self.assertEqual(self.runtime._local_custody_store.snapshot()['characters'][self.second], inactive)
        self.switch(self.first)
        self.assertEqual(self.runtime._item_instances[item['instance_id']], actual)

    def test_ground_bop_confirmation_relogin_disk_failure_and_retry_keep_exact_physical_terms(self):
        self.join(); item, session = self.opened_drop(bonding=1)
        self.pick(item, item, session); key = self.roll()['id']
        self.public('LootRollConfirm', id=key, vote=2)
        self.assertEqual(self.roll()['votes'], {})
        self.switch(self.first)
        actual = self.runtime._item_instances[item['instance_id']]
        self.assertEqual(actual['location'], 'GROUND')
        before = copy.deepcopy((self.runtime._item_instances, self.runtime._inventory, self.runtime._services['loot_rolls']))
        with patch.object(self.runtime._state_store, 'save', side_effect=OSError('test disk failure')):
            failed = self.runtime.client_control(json.dumps(dict(kind='service', op='LootRollVote', id=key, vote=2)))
        self.assertEqual(failed.get('error'), 'SERVICE_SAVE_FAILED')
        self.assertEqual((self.runtime._item_instances, self.runtime._inventory, self.runtime._services['loot_rolls']), before)
        self.public('LootRollVote', id=key, vote=2)
        actual = self.runtime._item_instances[item['instance_id']]
        self.assertEqual(actual['bound_to'], self.first); self.assertEqual(actual['owner_id'], 'player')
        self.assertEqual(actual.get('contents', []), []); self.assertFalse(actual.get('container_state'))

    def test_ground_movement_quantity_owner_location_or_source_changes_close_and_cannot_award(self):
        self.join()
        for changed in ('movement', 'quantity', 'owner', 'location', 'source_position'):
            with self.subTest(changed=changed):
                item, session = self.opened_drop(); self.pick(item, item, session); key = self.roll()['id']
                if changed == 'movement': self.runtime._x[0] += items.INTERACTION_RADIUS_M + 5
                elif changed == 'quantity': item['quantity'] += 1
                elif changed == 'owner': item['owner_id'] = 'npc-wanderer-01'
                elif changed == 'location': item['location'] = 'POCKET'; item['owner_id'] = 'npc-wanderer-01'
                else: item['position']['x'] += .25
                before = copy.deepcopy((self.runtime._item_instances, self.runtime._inventory))
                self.assertFalse(self.runtime._loot_view_locked()['open'])
                denied = self.runtime.client_control(json.dumps(dict(kind='service', op='LootRollVote', id=key, vote=1)))
                self.assertEqual(denied.get('error'), 'LOOT_ITEM_CHANGED')
                self.assertEqual((self.runtime._item_instances, self.runtime._inventory), before)
                self.runtime._services['loot_rolls'].clear()

    def test_close_pass_and_timeout_keep_ground_drop_without_container_fields_or_binding(self):
        self.join(); item, session = self.opened_drop(bonding=1)
        before = copy.deepcopy(item)
        self.assertIsNone(self.runtime.close_loot(session).get('error'))
        self.assertEqual(item, before)
        item_result = self.runtime.pickup_item(item['instance_id'])
        self.assertIsNone(item_result.get('error'))
        self.pick(item, item, self.runtime._engine_loot['session']); key = self.roll()['id']
        self.public('LootRollVote', id=key, vote=0)
        self.assertEqual(item, before); self.assertIn(item['instance_id'], self.runtime._services['free_loot'])
        self.runtime._services['free_loot'].remove(item['instance_id'])
        self.pick(item, item, self.runtime._engine_loot['session']); roll = self.roll()
        with patch('time.time', return_value=roll['expires'] + 1):
            self.runtime._settle_services_locked()
        self.assertEqual(item, before); self.assertFalse(self.runtime._services['loot_rolls'])

    def test_ground_master_uses_only_actual_self_and_offline_master_never_proxies(self):
        self.join('master'); item, session = self.opened_drop()
        self.public('LootMasterSlot', loot_session=session, item=item['instance_id'], target=self.runtime._local_character_name)
        self.assertEqual(item['location'], 'INVENTORY'); self.assertEqual(item.get('contents', []), [])
        self.public('GroupLoot', method='master', master='Second Hero')
        item, session = self.opened_drop(); before = copy.deepcopy(item)
        denied = self.runtime.loot_slot(session, item['instance_id'], item['instance_id'])
        self.assertEqual(denied.get('error'), 'LOOT_MASTER_NOT_PRESENT')
        self.assertEqual(item, before); self.assertFalse(self.runtime._services['loot_rolls'])

    def test_roundrobin_ground_award_and_stale_frozen_window_after_reopen(self):
        self.join('roundrobin'); item, session = self.opened_drop()
        self.pick(item, item, session)
        self.assertEqual(item['location'], 'INVENTORY'); self.assertFalse(self.runtime._services['loot_rolls'])
        self.assertEqual(item.get('contents', []), []); self.assertFalse(item.get('container_state'))
        second, next_session = self.opened_drop()
        denied = self.runtime.loot_slot(session, item['instance_id'], item['instance_id'])
        self.assertEqual(denied.get('error'), 'LOOT_SOURCE_CHANGED_OR_CLOSED')
        self.assertEqual(second['location'], 'GROUND'); self.assertNotEqual(next_session, session)

    def test_absent_optional_container_fields_are_never_inserted_by_ground_close_or_award(self):
        self.join('roundrobin'); item = self.combat_drop()
        # The generic factory has legacy empty fields even on a weapon. Their
        # absence is also valid; a loot flow must never create container state.
        self.assertEqual(item.pop('contents'), []); self.assertEqual(item.pop('container_state'), '')
        opened = self.runtime.pickup_item(item['instance_id'])
        session = self.runtime._engine_loot['session']
        self.assertIsNone(opened.get('error')); self.runtime.close_loot(session)
        self.assertNotIn('contents', item); self.assertNotIn('container_state', item)
        self.runtime.pickup_item(item['instance_id'])
        self.pick(item, item, self.runtime._engine_loot['session'])
        self.assertEqual(item['location'], 'INVENTORY')
        self.assertNotIn('contents', item); self.assertNotIn('container_state', item)

    def test_out_of_range_pending_ground_roll_expires_without_pass_votes_or_free_loot(self):
        self.join(); item, session = self.opened_drop()
        self.pick(item, item, session); roll = self.roll()
        before = copy.deepcopy(item); self.runtime._x[0] += items.INTERACTION_RADIUS_M + 5
        with patch('time.time', return_value=roll['expires'] + 1):
            self.runtime._settle_services_locked()
        self.assertEqual(item, before); self.assertFalse(self.runtime._services['loot_rolls'])
        self.assertNotIn(item['instance_id'], self.runtime._services['free_loot'])
        self.switch(self.first); self.assertFalse(self.runtime._services['loot_rolls'])


if __name__ == '__main__': unittest.main()
