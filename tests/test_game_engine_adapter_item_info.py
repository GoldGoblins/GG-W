"""Catalog tooltips carry real base stats and exact-instance enchantments."""
import copy
import unittest
import test_game_engine_adapter_services as service_tests
from backend import game_engine_gear as gear,game_engine_items as items,game_engine_enchants as enchants
from backend.game_engine_adapter_gameplay import identity

class ItemInfo(unittest.TestCase):
    setUp=service_tests.Services.setUp
    publish=service_tests.Services.publish
    call=service_tests.Services.call
    control=service_tests.Services.control
    view=service_tests.Services.view
    service=service_tests.Services.service

    def test_original_catalog_lookup_without_owned_instance_and_real_armor_tooltip(self):
        ref='item.tideguard_jacket';data=next(r for r in self.view()['item_templates'] if r['definition_id']==ref)
        expected=gear.gear_spec_for_definition(ref,self.runtime._item_catalog['gear'])['base_stats']
        self.assertEqual(data['armor'],expected['armor']);self.assertIn([7,expected['stamina']],data['stats'])
        self.assertEqual(data['required_level'],0)
        self.assertEqual(self.ui.evaluate(f'return (GetItemInfo({identity(ref)}))'),[items.definition(self.runtime._item_catalog,ref)['name']])
        self.ui.execute(f'GGItemTip=CreateFrame("GameTooltip","GGItemTip");GGItemTip:SetHyperlink("item:{identity(ref)}:0:0:0")')
        self.assertGreaterEqual(self.ui.evaluate('return GGItemTip:NumLines()')[0],4)
        self.assertFalse(any(r['feature']=='item_stats' for r in self.ui.request('requests')['unimplemented']))

    def test_original_owned_item_tooltip_includes_actual_enchant_and_durability(self):
        sword=items.make_instance(self.runtime._item_catalog,'item-tooltip-fixture','item.weapon_sword',location='GROUND')
        with self.runtime._lock:
            self.runtime._item_instances[sword['instance_id']]=sword
            ok,result=self.runtime._move_item_locked(sword,'INVENTORY',owner_id='player');self.assertTrue(ok,result)
            ok,result=gear.apply_enchant(sword['gear'],'enchant.chromatic.red',self.runtime._gear_tables);self.assertTrue(ok,result)
            self.runtime._ensure_inventory_slots_locked()
        self.publish();slot=sword['slot_index']+1
        self.ui.execute(f'GGItemTip=CreateFrame("GameTooltip","GGItemTip");GGItemTip:SetBagItem(0,{slot})')
        rows=self.ui.evaluate('local t={} for i=1,GGItemTip:NumLines() do local r=getglobal("GGItemTipTextLeft"..i);t[i]=r and r:GetText() or "" end return table.concat(t,string.char(10))')[0]
        self.assertIn(enchants.definition('enchant.chromatic.red')['name'],rows)
        self.assertIn('100 / 100',rows)
        before=copy.deepcopy(sword);self.ui.execute(f'GGItemTip:SetBagItem(0,{slot})');self.assertEqual(before,self.runtime._item_instance_locked(sword['instance_id']))

    def test_unknown_template_query_is_explicit_and_does_not_change_custody(self):
        before=copy.deepcopy((self.runtime._item_instances,self.runtime._inventory,self.runtime._economy_state))
        self.assertEqual(self.service('ItemInfo',id=77)['error'],'ITEM_TEMPLATE_NOT_LOCAL')
        self.assertEqual(before,(self.runtime._item_instances,self.runtime._inventory,self.runtime._economy_state))
        self.assertIsNone(self.service('ItemInfo',id=identity('item.weapon_sword')).get('error'))

if __name__=='__main__':unittest.main()
