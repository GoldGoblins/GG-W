"""Original crafting/loot Lua calls must transact real, bounded GG item state."""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QGuiApplication
from backend import game_engine_items as items, game_engine_mmo as mmo
from backend import game_engine_character_creation as appearance
from backend.game_engine_presentation import Presentation

APP = QGuiApplication.instance() or QGuiApplication([])


class Bridge(QObject):
    snapshotPublished = Signal(object)

    def __init__(self, runtime):
        super().__init__()
        self.runtime = runtime

    def gameEngineCraftBookRecipe(self, session, recipe, count):
        return json.dumps(self.runtime.craft_book_recipe(session, recipe, count))

    def gameEngineCraftingClose(self, session):
        return json.dumps(self.runtime.close_crafting(session))

    def gameEngineCraftingStop(self):
        return json.dumps(self.runtime.stop_crafting())

    def gameEngineLootSlot(self, session, source, instance):
        return json.dumps(self.runtime.loot_slot(session, source, instance))

    def gameEngineLootClose(self, session):
        return json.dumps(self.runtime.close_loot(session))


class LocalActions(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        for context in (patch.dict(os.environ, {'XDG_STATE_HOME': directory.name}),
                        patch.object(mmo, 'DEFAULT_STASH_PATH', Path(directory.name) / 'stash.json'),
                        patch.object(appearance, 'STATE_PATH', Path(directory.name) / 'appearance.json')):
            context.start()
            self.addCleanup(context.stop)
        from backend.game_engine_host import GameEngineRuntime
        self.runtime = GameEngineRuntime()
        self.addCleanup(self.runtime.shutdown)
        self.bridge = Bridge(self.runtime)
        self.presentation = Presentation(self.bridge, device=False)
        self.addCleanup(self.presentation.close)
        self.assertTrue(self.presentation.full_ui)
        self.ui = self.presentation.lua
        self.ui.execute("localEvents={};localErrors={};e=CreateFrame('Frame'); for _,n in ipairs({'TRADE_SKILL_SHOW','TRADE_SKILL_UPDATE','TRADE_SKILL_CLOSE','CRAFT_SHOW','CRAFT_UPDATE','CRAFT_CLOSE','LOOT_OPENED','LOOT_SLOT_CLEARED','LOOT_CLOSED','UI_ERROR_MESSAGE'}) do e:RegisterEvent(n) end; e:SetScript('OnEvent',function() table.insert(localEvents,event);if event=='UI_ERROR_MESSAGE' then table.insert(localErrors,arg1) end end)")

    def publish(self):
        self.presentation.last_update = 0
        self.presentation.update(self.runtime.ui_snapshot())
        self.assertFalse(self.presentation.errors, self.presentation.errors)

    def action(self, script):
        self.ui.execute(script)
        self.presentation._ui_requests(self.ui.request('requests'))
        self.publish()

    def near_station(self, key):
        p = self.runtime._gear_tables['workstations'][key]['position']
        self.runtime._x[0], self.runtime._z[0] = p['x'], p['z']
        self.runtime._y[0] = self.runtime._terrain_height_locked(p['x'], p['z']) + .65

    def open_loot(self):
        row = next(r for r in self.runtime._item_instances.values()
                   if r.get('kind') == 'CONTAINER' and r.get('location') == 'GROUND'
                   and any(c.get('container_id') == r['instance_id'] and c.get('location') == 'CONTAINER'
                           for c in self.runtime._item_instances.values()))
        p = row['position']
        self.runtime._x[0], self.runtime._z[0] = p['x'], p['z']
        self.runtime._y[0] = p['y'] + .65
        self.assertNotIn('error', self.runtime.open_container(row['instance_id']))
        self.publish()
        self.ui.execute("lootButton=CreateFrame('LootButton','GGTestLootButton');lootButton:SetWidth(30);lootButton:SetHeight(30);lootButton:SetPoint('CENTER',UIParent,'CENTER',0,0);lootButton:RegisterForClicks('LeftButtonUp');lootButton:SetSlot(1)")
        return row

    def test_trade_skill_consumes_real_reagents_and_cannot_mint_on_repeat(self):
        self.runtime._inventory['item.sea_salt'] = 2
        self.runtime._inventory['item.sun_herb'] = 4
        self.runtime._reconcile_item_instances_locked()
        before = self.runtime._inventory.get('item.field_ration', 0)
        self.runtime.open_crafting()
        self.publish()
        book=self.ui.evaluate('return GetNumTradeSkills(),GetTradeSkillInfo(2)')
        self.assertGreaterEqual(book[0],3)
        self.assertEqual(book[1:3],['Field Ration','trivial'])
        self.action('DoTradeSkill(2,999);DoTradeSkill(2,999)')
        self.assertEqual(self.ui.evaluate('return GetTradeskillRepeatCount()'), [1])
        self.runtime._tick_crafting_locked(.1)
        self.publish()
        self.assertEqual(self.runtime._inventory.get('item.field_ration', 0), before + 2)
        self.assertNotIn('item.sea_salt', self.runtime._inventory)
        self.assertGreater(self.ui.evaluate('return table.getn(localErrors)')[0], 0)
        self.action('CloseTradeSkill()')
        self.assertFalse(self.runtime._engine_craft_book)
        self.assertEqual(self.ui.evaluate('return GetNumTradeSkills()'), [0])
        self.assertIn('TRADE_SKILL_CLOSE', self.ui.evaluate('return table.concat(localEvents,",")')[0])

    def test_craft_book_uses_actual_station_and_rejects_stale_session(self):
        station = 'station.workbench'
        self.near_station(station)
        self.runtime.open_crafting('CRAFT', station)
        self.publish()
        self.assertGreater(self.ui.evaluate('return GetNumCrafts()')[0], 0)
        self.ui.execute("for i=1,GetNumCrafts() do local n=GetCraftInfo(i);if n=='Woven Rope' then DoCraft(i) end end")
        self.runtime.open_crafting('CRAFT', station)
        before = copy.deepcopy(self.runtime._inventory)
        self.presentation._ui_requests(self.ui.request('requests'))
        self.assertEqual(self.runtime._inventory, before)
        self.assertIn('CRAFT_BOOK_CHANGED_OR_CLOSED', self.ui.evaluate('return table.concat(localErrors,",")')[0])
        self.publish()
        self.runtime._x[0] += 100
        self.action('DoCraft(1)')
        self.assertEqual(self.runtime._inventory, before)
        self.assertFalse(self.runtime._engine_craft_book)
        self.assertIn('error', self.runtime.open_crafting('CRAFT', station))

    def test_full_inventory_rejects_before_consuming_and_preserves_physical_state(self):
        # Spare ingredients remain in their stacks, so this recipe needs an
        # additional product cell. All filler cells name actual valid items.
        self.runtime._item_instances = {}
        for index in range(items.MAX_INVENTORY_SLOTS):
            ref = 'item.sea_salt' if index == 0 else 'item.sun_herb' if index == 1 else 'item.island_compass'
            row = items.make_instance(self.runtime._item_catalog, f'full-{index}', ref,
                                      location='INVENTORY', quantity=10 if index < 2 else 1, owner_id='player')
            self.runtime._item_instances[row['instance_id']] = row
        self.runtime._inventory = items.inventory_counts(self.runtime._item_instances.values())
        self.runtime.snapshot_locked()
        before = copy.deepcopy((self.runtime._inventory, self.runtime._item_instances))
        result = self.runtime.craft_recipe('recipe.field_ration')
        self.assertEqual(result['error'], 'ITEM_INVENTORY_FULL')
        self.assertEqual((self.runtime._inventory, self.runtime._item_instances), before)

    def test_loot_button_moves_one_exact_item_clears_slot_and_cannot_duplicate(self):
        source = self.open_loot()
        rows = self.runtime._loot_view_locked()['rows']
        self.assertGreater(len(rows), 1)
        first, second = rows[0]['instance_id'], rows[1]['instance_id']
        count = self.ui.evaluate('return GetNumLootItems()')[0]
        # The original LootButton intentionally refuses a scripted Click.
        self.action("lootButton:Click('LeftButton');lootButton:Click('LeftButton')")
        self.assertEqual(self.runtime._item_instances[first]['location'], 'CONTAINER')
        self.ui.click('GGTestLootButton')
        self.ui.click('GGTestLootButton')
        self.presentation._ui_requests(self.ui.request('requests'))
        self.publish()
        self.assertEqual(self.runtime._item_instances[first]['location'], 'INVENTORY')
        self.assertEqual(self.runtime._item_instances[second]['location'], 'CONTAINER')
        self.assertEqual(self.ui.evaluate('return GetNumLootItems()'), [count])
        self.assertEqual(self.ui.evaluate('return GetLootSlotInfo(1)')[1:4], ['', 0, -1])
        self.assertIn('LOOT_SLOT_CLEARED', self.ui.evaluate('return table.concat(localEvents,",")')[0])
        before = copy.deepcopy(self.runtime._inventory)
        self.action('LootSlot(2);GiveMasterLoot(2,1)')
        self.assertEqual(self.runtime._inventory, before)
        self.action('CloseLoot()')
        self.assertEqual(self.ui.evaluate('return GetNumLootItems()'), [0])
        self.assertIn('LOOT_CLOSED', self.ui.evaluate('return table.concat(localEvents,",")')[0])

    def test_queued_loot_rejects_reopened_chest_and_out_of_reach(self):
        source = self.open_loot()
        first = self.runtime._loot_view_locked()['rows'][0]['instance_id']
        self.ui.click('GGTestLootButton')
        self.runtime.open_container(source['instance_id'])
        before = copy.deepcopy(self.runtime._inventory)
        self.presentation._ui_requests(self.ui.request('requests'))
        self.assertEqual(self.runtime._inventory, before)
        self.assertEqual(self.runtime._item_instances[first]['location'], 'CONTAINER')
        self.publish()
        self.runtime._x[0] += 100
        self.ui.click('GGTestLootButton')
        self.presentation._ui_requests(self.ui.request('requests'))
        self.publish()
        self.assertEqual(self.runtime._inventory, before)
        self.assertEqual(self.ui.evaluate('return GetNumLootItems()'), [0])

    def test_original_stop_casting_cancels_remaining_real_crafts(self):
        self.runtime._inventory['item.sea_salt'] = 4
        self.runtime._inventory['item.sun_herb'] = 8
        self.runtime._reconcile_item_instances_locked()
        before = self.runtime._inventory.get('item.field_ration', 0)
        self.runtime.open_crafting()
        self.publish()
        self.action('DoTradeSkill(2,4)')
        self.assertEqual(self.ui.evaluate('return GetTradeskillRepeatCount()'), [3])
        self.action('SpellStopCasting()')
        self.runtime._tick_crafting_locked(1)
        self.publish()
        self.assertFalse(self.runtime._engine_craft_repeat)
        self.assertEqual(self.runtime._inventory.get('item.field_ration', 0), before+1)
        self.assertEqual(self.ui.evaluate('return GetTradeskillRepeatCount()'), [0])

    def test_repeat_rechecks_station_after_movement_without_spending(self):
        self.near_station('station.workbench')
        self.runtime._inventory['material.fiber'] = 12
        self.runtime._reconcile_item_instances_locked()
        self.runtime.open_crafting('TRADE_SKILL', 'station.workbench')
        self.publish()
        self.action("for i=1,GetNumTradeSkills() do local n=GetTradeSkillInfo(i);if n=='Woven Rope' then DoTradeSkill(i,4) end end")
        self.assertEqual(self.runtime._engine_craft_repeat['remaining'], 3)
        before = copy.deepcopy(self.runtime._inventory)
        self.runtime._x[0] += 100
        self.runtime._tick_crafting_locked(.1)
        self.publish()
        self.assertEqual(self.runtime._inventory, before)
        self.assertFalse(self.runtime._engine_craft_repeat)
        self.assertEqual(self.ui.evaluate('return GetNumTradeSkills()'), [0])

    def test_world_instance_capacity_refuses_output_without_losing_materials(self):
        # No reagent bundle is fully consumed, so this craft needs one more
        # live registry entry. Several small bundles could otherwise free one.
        for definition in ('item.sea_salt', 'item.sun_herb'):
            rows = [r for r in self.runtime._item_instances.values()
                    if r.get('definition_id') == definition and r.get('location') == 'INVENTORY']
            for row in rows:
                row['quantity'] = 10
            self.runtime._inventory[definition] = sum(r['quantity'] for r in rows)
        while len(self.runtime._item_instances) < items.MAX_WORLD_INSTANCES:
            key = f'used-{len(self.runtime._item_instances)}'
            self.runtime._item_instances[key] = items.make_instance(self.runtime._item_catalog, key,
                'item.island_compass', location='GROUND', owner_id='')
        self.runtime.ui_snapshot()  # assign stable visible bag cells before the failure
        before = copy.deepcopy(self.runtime._inventory)
        instances = copy.deepcopy(self.runtime._item_instances)
        result = self.runtime.craft_recipe('recipe.field_ration')
        self.assertEqual(result['error'], 'ITEM_INSTANCE_CAPACITY')
        self.assertEqual(self.runtime._inventory, before)
        self.assertEqual(self.runtime._item_instances, instances)

    def test_crafting_reclaims_ingredients_before_allocating_output_at_capacity(self):
        # Product comes first in the dictionary, after the previous product
        # was used. Allocation must still follow both ingredient deductions.
        self.runtime._inventory = {'item.field_ration': 0, **self.runtime._inventory}
        self.runtime._inventory['item.sea_salt'] = 1
        self.runtime._inventory['item.sun_herb'] = 2
        self.runtime._reconcile_item_instances_locked()
        while len(self.runtime._item_instances) < items.MAX_WORLD_INSTANCES:
            key = f'ground-{len(self.runtime._item_instances)}'
            self.runtime._item_instances[key] = items.make_instance(self.runtime._item_catalog, key,
                'item.island_compass', location='GROUND', owner_id='')
        result = self.runtime.craft_recipe('recipe.field_ration')
        self.assertNotIn('error', result)
        products = [r for r in self.runtime._item_instances.values()
                    if r.get('definition_id') == 'item.field_ration' and r.get('location') == 'INVENTORY']
        self.assertEqual(sum(r['quantity'] for r in products), 1)
        self.assertEqual(len(self.runtime._item_instances), items.MAX_WORLD_INSTANCES - 1)
        self.assertFalse(any(r.get('location') == 'DESTROYED' for r in self.runtime._item_instances.values()))

    def test_repeated_crafting_and_consumption_does_not_leak_registry_slots(self):
        initial = len(self.runtime._item_instances)
        ids = set(self.runtime._item_instances)
        # Earlier saves may already contain consumed tombstones.
        self.runtime._item_instances['old-consumed'] = items.make_instance(
            self.runtime._item_catalog, 'old-consumed', 'item.island_compass',
            location='DESTROYED', owner_id='')
        for _ in range(items.MAX_WORLD_INSTANCES + 5):
            self.runtime._inventory['item.sea_salt'] = 1
            self.runtime._inventory['item.sun_herb'] = 2
            self.runtime._reconcile_item_instances_locked()
            self.assertNotIn('error', self.runtime.craft_recipe('recipe.field_ration'))
            products = [r for r in self.runtime._item_instances.values()
                        if r.get('definition_id') == 'item.field_ration' and r.get('location') == 'INVENTORY']
            self.assertEqual(sum(r['quantity'] for r in products), 1)
            self.assertTrue(all(r['instance_id'] not in ids for r in products))
            ids.update(r['instance_id'] for r in products)
            self.runtime._inventory['item.field_ration'] = 0
            self.runtime._reconcile_item_instances_locked()
            self.assertLessEqual(len(self.runtime._item_instances), initial)
            self.assertFalse(any(r.get('location') == 'DESTROYED' for r in self.runtime._item_instances.values()))


if __name__ == '__main__':
    unittest.main()
