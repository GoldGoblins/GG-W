"""Original Lua/button intents operate on one real combat drop without proxies."""
import copy
import json
import unittest

import test_game_engine_local_groups_native as native
import test_game_engine_local_ground_loot as ground
from backend import game_engine_items as items


class NativeGroundLoot(unittest.TestCase):
    setUp = native.NativeLocalGroups.setUp
    bind = native.NativeLocalGroups.bind
    switch = native.NativeLocalGroups.switch
    view = native.NativeLocalGroups.view
    publish = native.NativeLocalGroups.publish
    join = native.NativeLocalGroups.join
    public = ground.GroundGroupLoot.public
    combat_drop = ground.GroundGroupLoot.combat_drop
    opened_drop = ground.GroundGroupLoot.opened_drop

    def call(self, source):
        requests = native.NativeLocalGroups.call(self, source)
        for slot in requests.get('loot_picks', []):
            frozen = self.gameplay.local.loot(slot)
            result = self.runtime.loot_slot(*frozen['args'])
            self.assertIsNone(result.get('error'), result.get('error'))
        if requests.get('loot_close'):
            result = self.runtime.close_loot(self.gameplay.local.loot_session)
            self.assertIsNone(result.get('error'), result.get('error'))
        self.publish()
        return requests

    def active_group(self, method='group'):
        self.join(); self.switch(self.first); self.publish()
        self.call('SetLootMethod("'+method+'")')

    def button(self):
        self.ui.execute("lootButton=CreateFrame('LootButton','GGGroundLootButton');lootButton:SetWidth(30);lootButton:SetHeight(30);lootButton:SetPoint('CENTER',UIParent,'CENTER',0,0);lootButton:RegisterForClicks('LeftButtonUp');lootButton:SetSlot(1)")

    def test_original_ground_button_bop_roll_confirmation_and_open_event_are_exactly_once(self):
        self.active_group()
        self.ui.execute("GG_GROUND_OPEN=0;local f=CreateFrame('Frame');f:RegisterEvent('LOOT_OPENED');f:SetScript('OnEvent',function()GG_GROUND_OPEN=GG_GROUND_OPEN+1 end)")
        item, session = self.opened_drop(bonding=1); self.publish(); self.button()
        self.assertEqual(self.ui.evaluate('return GetNumLootItems(),LootSlotIsItem(1),GG_GROUND_OPEN'), [1, 1, 1])
        self.runtime.pickup_item(item['instance_id']); self.publish()
        self.assertEqual(self.ui.evaluate('return GG_GROUND_OPEN'), [1])
        self.ui.click('GGGroundLootButton'); self.call('')
        roll = self.runtime._services['loot_rolls'][0]; key = roll['id']
        self.assertEqual(roll['eligible'], ['player']); self.assertEqual(roll['votes'], {})
        self.call('RollOnLoot('+str(key)+',1)')
        self.assertEqual(item['location'], 'GROUND'); self.assertEqual(roll['votes'], {})
        self.call('ConfirmLootRoll('+str(key)+',1)')
        self.assertEqual(item['location'], 'INVENTORY'); self.assertEqual(item['bound_to'], self.first)
        self.assertEqual(item.get('contents', []), []); self.assertFalse(item.get('container_state'))
        self.assertEqual(self.ui.evaluate('return GetNumLootItems()'), [0])
        before = self.runtime._local_custody_store.snapshot()['characters']
        self.call('ConfirmLootRoll('+str(key)+',1)')
        self.assertEqual(self.runtime._local_custody_store.snapshot()['characters'], before)

    def test_original_ground_master_candidates_and_give_use_only_actual_self(self):
        self.active_group('master')
        item, _ = self.opened_drop(); self.publish()
        self.assertEqual(self.ui.evaluate('return GetMasterLootCandidate(1),GetMasterLootCandidate(2)'), [self.runtime._local_character_name, None])
        self.call('GiveMasterLoot(1,1)')
        self.assertEqual(item['location'], 'INVENTORY'); self.assertEqual(item.get('contents', []), [])
        self.call('SetLootMethod("master","Second Hero")')
        item, session = self.opened_drop(); self.publish()
        self.ui.execute('GiveMasterLoot(1,1)')
        pair = self.ui.request('requests')['loot_master_gives'][0]
        frozen = self.gameplay.local.master_loot(*pair)
        before = copy.deepcopy((self.runtime._item_instances, self.runtime._inventory))
        denied = self.runtime.client_control(frozen['args'][0])
        self.assertEqual(denied.get('error'), 'LOOT_MASTER_NOT_PRESENT')
        self.assertEqual((self.runtime._item_instances, self.runtime._inventory), before)

    def test_original_queued_ground_button_rejects_moved_source_and_close_adds_no_container_state(self):
        self.active_group()
        item, session = self.opened_drop(); self.publish(); self.button()
        self.ui.click('GGGroundLootButton')
        slot = self.ui.request('requests')['loot_picks'][0]
        frozen = self.gameplay.local.loot(slot)
        item['position']['x'] += .1
        before = copy.deepcopy((self.runtime._item_instances, self.runtime._inventory))
        denied = self.runtime.loot_slot(*frozen['args'])
        self.assertEqual(denied.get('error'), 'LOOT_SOURCE_CHANGED_OR_CLOSED')
        self.assertEqual((self.runtime._item_instances, self.runtime._inventory), before)
        self.runtime.pickup_item(item['instance_id']); self.publish()
        self.call('CloseLoot()')
        self.assertEqual(item['location'], 'GROUND'); self.assertFalse(item.get('container_state'))
        self.assertEqual(item.get('contents', []), []); self.assertFalse(self.runtime._services['loot_rolls'])


if __name__ == '__main__': unittest.main()
