"""Last-ingredient crafting remains usable by the actual saved item services."""
import json
import unittest

import test_game_engine_local_custody_services as fixture
from backend import game_engine_items as items
from backend import game_engine_enchants as enchants


class CraftingCustody(unittest.TestCase):
    setUp = fixture.SharedServices.setUp
    bind = fixture.SharedServices.bind
    switch = fixture.SharedServices.switch

    def command(self, op, **fields):
        return self.runtime.client_control(json.dumps(dict(kind='service', op=op,
            session=self.runtime._service_generation, **fields)))

    def test_last_paper_ingredients_allow_wrap_and_exact_saved_restore(self):
        blade = self.runtime._item_instances['starter-iron-saber']
        self.assertNotIn('error', self.runtime.unequip_item(blade['instance_id']))
        with self.runtime._lock:
            self.runtime._inventory.update({'material.fiber': 2, 'material.resin': 1})
            self.runtime._reconcile_item_instances_locked()
        crafted = self.runtime.craft_recipe('recipe.wrapping_paper')
        self.assertNotIn('error', crafted)
        self.assertEqual(self.runtime._inventory, items.inventory_counts(self.runtime._item_instances.values()))
        self.assertNotIn('material.resin', self.runtime._inventory)
        self.assertNotIn('material.fiber', self.runtime._inventory)
        paper = next(row for row in self.runtime._item_instances.values()
                     if row['definition_id'] == 'item.gg_wrapping_paper' and row['location'] == 'INVENTORY')
        self.assertNotIn('error', self.command('InventoryWrapOpen', item=paper['instance_id']))
        wrapped = self.command('InventoryWrap', item=blade['instance_id'], paper=paper['instance_id'],
                               wrap_generation=self.runtime._gift_wrap_generation)
        self.assertNotIn('error', wrapped)
        self.assertEqual(self.runtime._item_instances[blade['instance_id']]['gift']['original']['definition_id'], 'item.iron_saber')
        self.switch(self.first)
        self.assertEqual(self.runtime._inventory, items.inventory_counts(self.runtime._item_instances.values()))
        self.assertEqual(self.runtime._item_instances[blade['instance_id']]['gift']['original']['definition_id'], 'item.iron_saber')

    def test_last_scroll_reagents_allow_real_cursor_application_and_saved_restore(self):
        definition = enchants.definition('enchant.chromatic.red')
        cost = enchants.scroll_cost(definition)
        with self.runtime._lock:
            self.runtime._inventory.update(cost)
            self.runtime._reconcile_item_instances_locked()
            self.runtime._x[0], self.runtime._z[0] = -3, -1.5
            self.runtime._y[0] = self.runtime._terrain_height_locked(-3, -1.5) + .65
        crafted = self.runtime.craft_gear('recipe.enchant_scroll.enchant.chromatic.red', 'station.enchanting_altar')
        self.assertNotIn('error', crafted)
        self.assertEqual(self.runtime._inventory, items.inventory_counts(self.runtime._item_instances.values()))
        for key in cost:
            self.assertNotIn(key, self.runtime._inventory)
        scroll = crafted['gear_craft_result']['created'][0]['instance_id']
        self.assertNotIn('error', self.command('EnchantOpen', item=scroll))
        self.assertNotIn('error', self.command('EnchantPick', item='starter-iron-saber',
                                             target_generation=self.runtime._item_target_generation))
        self.assertNotIn(scroll, self.runtime._item_instances)
        self.switch(self.first)
        self.assertNotIn(scroll, self.runtime._item_instances)
        self.assertEqual(self.runtime._inventory, items.inventory_counts(self.runtime._item_instances.values()))
        self.assertEqual(self.runtime._item_instances['starter-iron-saber']['gear']['enchantments'][0]['id'], definition['id'])


if __name__ == '__main__':
    unittest.main()
