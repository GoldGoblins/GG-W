"""Actual equip thresholds, original set tooltip and durable gear identity."""
import copy
import unittest
from unittest.mock import patch
import test_game_engine_adapter_services as services
from backend import game_engine_items as items
from backend import game_engine_adapter_item_sets as sets


class ItemSets(unittest.TestCase):
    publish=services.Services.publish
    call=services.Services.call
    control=services.Services.control
    service=services.Services.service
    view=services.Services.view

    def setUp(self):services.Services.setUp(self)

    def wear(self,ref):
        item=next((i for i in self.runtime._item_instances.values() if i.get('definition_id')==ref and i.get('owner_id')=='player'),None)
        if item is None:
            item=items.make_instance(self.runtime._item_catalog,'set-fixture-'+ref,ref)
            self.runtime._item_instances[item['instance_id']]=item
            self.runtime._inventory[ref]=self.runtime._inventory.get(ref,0)+1
        self.assertIsNone(self.runtime.equip_item(item['instance_id']).get('error'));self.publish()
        return item

    def strip(self):
        for item in list(self.runtime._player_equipped_instances_locked()):
            if item['definition_id'] in sets.DEFAULT_SETS['saltwake_voyager']['members']:
                self.assertIsNone(self.runtime.unequip_item(item['instance_id']).get('error'))

    def test_thresholds_add_to_real_combat_and_unequip_removes_each_bonus_without_duplicate_stacking(self):
        self.strip();first=self.wear('item.tideguard_jacket');a=self.runtime._player_combat_profile_locked()
        second=self.wear('item.drift_cloak');b=self.runtime._player_combat_profile_locked()
        self.assertEqual(b['armor']-a['armor'],second['gear']['stats']['armor']+3)
        third=self.wear('item.saltpath_boots');c=self.runtime._player_combat_profile_locked()
        self.assertEqual(c['max_health']-b['max_health'],12)
        for _ in range(4):self.assertEqual(self.runtime._player_combat_profile_locked(),c)
        self.runtime.unequip_item(third['instance_id']);self.assertEqual(self.runtime._player_combat_profile_locked(),b)
        self.runtime.unequip_item(second['instance_id']);self.assertEqual(self.runtime._player_combat_profile_locked(),a)

    def tooltip(self):
        self.ui.execute("SET_TIP=CreateFrame('GameTooltip','SetTip');SET_TIP:SetInventoryItem('player',5)")
        return self.ui.evaluate("local s='';for i=1,SET_TIP:NumLines() do local r=getglobal('SetTipTextLeft'..i);if r then s=s..(r:GetText() or '')..'\\n' end end;return s")[0]

    def test_original_tooltip_counts_actual_equipped_members_and_restores_same_set_effects(self):
        self.strip();self.wear('item.tideguard_jacket');self.wear('item.drift_cloak')
        text=self.tooltip();self.assertIn('Saltwake Voyager (2/3)',text);self.assertIn('+3 armor',text);self.assertIn('(3)',text)
        profile=self.runtime._player_combat_profile_locked();before=copy.deepcopy(self.runtime._item_instances)
        self.runtime.save_state();self.runtime.load_state();self.publish()
        self.assertEqual(self.runtime._item_instances,before);self.assertEqual(self.runtime._player_combat_profile_locked(),profile)
        self.assertIn('Saltwake Voyager (2/3)',self.tooltip())

    def test_unknown_set_request_never_modifies_or_saves_items_or_teaches_a_profession(self):
        before=copy.deepcopy((self.runtime._inventory,self.runtime._item_instances,self.runtime._profession_state))
        with patch.object(self.runtime,'save_state',wraps=self.runtime.save_state) as save:
            self.assertEqual(self.service('ItemSetInfo',id=7)['error'],'ITEM_SET_NOT_LOCAL');self.assertFalse(save.called)
        self.assertEqual(before,(self.runtime._inventory,self.runtime._item_instances,self.runtime._profession_state))

    def test_same_set_bonus_applies_to_actual_npc_equipment_without_player_profession_or_double_stacking(self):
        owner='npc-guardian-01'
        cloak=items.make_instance(self.runtime._item_catalog,'npc-set-cloak','item.drift_cloak',owner_id=owner,location='EQUIPPED')
        self.runtime._item_instances[cloak['instance_id']]=cloak
        enabled=self.runtime._npc_combat_profile_locked(owner)
        for _ in range(3):self.assertEqual(self.runtime._npc_combat_profile_locked(owner),enabled)
        table=self.runtime._gear_tables;self.runtime._gear_tables=dict(table,item_sets={})
        disabled=self.runtime._npc_combat_profile_locked(owner)
        self.assertEqual(enabled['armor']-disabled['armor'],3.)
        self.assertEqual(enabled['damage'],disabled['damage'])
        self.assertEqual(enabled['max_health'],disabled['max_health'])
        self.runtime._gear_tables=table

    def test_authored_sets_validate_duplicates_nonfinite_modifiers_and_real_skill_gates(self):
        table=copy.deepcopy(self.runtime._gear_tables);table['item_sets']={'test':dict(name='Test',members=['item.tideguard_jacket'],
            bonuses=[dict(count=1,stats={'armor':5},text='+5 armor.')],profession='ENCHANTING',profession_rank=2)}
        rows=sets.set_rows(table,self.runtime._item_catalog);worn=[dict(definition_id='item.tideguard_jacket',condition=1.)]
        self.assertEqual(sets.active_stats(rows,worn,{'ENCHANTING':dict(level=1,trained=True)}),{})
        self.assertEqual(sets.active_stats(rows,worn,{'ENCHANTING':dict(level=2,trained=True)}),{'armor':5})
        table['item_sets']['other']=copy.deepcopy(table['item_sets']['test'])
        with self.assertRaisesRegex(ValueError,'ITEM_SET_DUPLICATE'):sets.set_rows(table,self.runtime._item_catalog)
        table['item_sets'].pop('other');table['item_sets']['test']['bonuses'][0]['stats']['armor']=float('nan')
        with self.assertRaisesRegex(ValueError,'ITEM_SET_BONUS_INVALID'):sets.set_rows(table,self.runtime._item_catalog)

if __name__=='__main__':unittest.main()
