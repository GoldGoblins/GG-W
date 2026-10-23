"""Original item-targeting clicks consume exact scrolls after real confirmations."""
import copy
import unittest
from unittest.mock import patch
import test_game_engine_adapter_services as services
from backend import game_engine_enchants as enchants


class ItemTargeting(unittest.TestCase):
    publish=services.Services.publish
    call=services.Services.call
    control=services.Services.control
    service=services.Services.service
    view=services.Services.view

    def setUp(self):
        services.Services.setUp(self)
        self.bridge.gameEngineContainerUseItem=lambda ref,item:self.runtime.action_use_item(ref,item)
        with self.runtime._lock:
            self.runtime._x[0]=-3;self.runtime._z[0]=-1.5
            self.runtime._y[0]=self.runtime._terrain_height_locked(-3,-1.5)+.65
            self.runtime._inventory.update({'material.fiber':30,'material.runic_oil':30,'item.moon_shard':30})
            self.runtime._reconcile_item_instances_locked()
        self.ui.execute("ENCHANT_EVENTS={};EF=CreateFrame('Frame');EF:RegisterEvent('BIND_ENCHANT');EF:RegisterEvent('REPLACE_ENCHANT');EF:SetScript('OnEvent',function() table.insert(ENCHANT_EVENTS,{event,arg1,arg2}) end)")

    def scroll(self,color='red'):
        before=copy.deepcopy(self.runtime._inventory)
        value=self.runtime.craft_gear('recipe.enchant_scroll.enchant.chromatic.'+color,'station.enchanting_altar')
        self.assertIsNone(value.get('error'))
        self.assertLess(self.runtime._inventory['material.fiber'],before['material.fiber'])
        item=self.runtime._item_instances[value['gear_craft_result']['created'][0]['instance_id']]
        self.publish();self.call(f"UseContainerItem(0,{item['slot_index']+1})")
        self.assertTrue(self.view()['item_targeting']['active'])
        return item

    def answer(self,op,**fields):
        return self.service(op,target_generation=self.view()['item_targeting']['generation'],**fields)

    def test_original_doll_pick_applies_the_exact_crafted_scroll_once_and_restores_real_combat_effects(self):
        scroll=self.scroll();identity=scroll['instance_id'];blade=self.runtime._item_instances['starter-iron-saber']
        self.assertEqual(self.ui.evaluate('return SpellIsTargeting(),CursorHasItem()'),[1,False])
        self.assertEqual(self.runtime.move_inventory_slot(identity,63)['error'],'ITEM_PENDING_CONFIRMATION')
        self.call('PickupInventoryItem(16)')
        self.assertNotIn(identity,self.runtime._item_instances)
        self.assertEqual(blade['gear']['enchantments'][0]['id'],'enchant.chromatic.red')
        self.assertFalse(self.view()['item_targeting']['active'])
        self.assertIn('burn',{e['kind'] for e in self.runtime._player_combat_profile_locked()['enchant_effects']})
        before=copy.deepcopy((self.runtime._inventory,blade['gear']));self.call('BindEnchant();ReplaceEnchant()')
        self.assertEqual(before,(self.runtime._inventory,blade['gear']))
        self.runtime.load_state();self.publish()
        self.assertNotIn(identity,self.runtime._item_instances)
        self.assertEqual(self.runtime._item_instances[blade['instance_id']]['gear']['enchantments'][0]['id'],'enchant.chromatic.red')
        self.assertFalse(self.view()['item_targeting']['active'])

    def test_bind_then_replace_question_preserves_the_old_enchant_until_both_original_answers(self):
        first=self.scroll();self.call('PickupInventoryItem(16)')
        second=self.scroll('blue');blade=self.runtime._item_instances['starter-iron-saber'];old=copy.deepcopy(blade['gear'])
        with patch.dict(enchants.CATALOG['enchant.chromatic.blue'],{'binds':True}):
            self.call('PickupInventoryItem(16)')
            self.assertEqual(self.view()['item_targeting']['stage'],'BIND')
            self.assertEqual(blade['gear'],old);self.assertNotIn('bound_to',blade)
            self.assertEqual(self.ui.evaluate('return ENCHANT_EVENTS[1][1]'),['BIND_ENCHANT'])
            self.call('BindEnchant()')
            self.assertEqual(self.view()['item_targeting']['stage'],'REPLACE')
            self.assertEqual(blade['gear'],old);self.assertIn(second['instance_id'],self.runtime._item_instances)
            self.assertEqual(self.ui.evaluate('return ENCHANT_EVENTS[2][1],ENCHANT_EVENTS[2][2],ENCHANT_EVENTS[2][3]'),['REPLACE_ENCHANT','Crimson Ember','Glacier Edge'])
            self.call('ReplaceEnchant()')
        self.assertNotIn(second['instance_id'],self.runtime._item_instances)
        self.assertEqual(blade['gear']['enchantments'][0]['id'],'enchant.chromatic.blue')
        self.assertEqual(blade['bound_to'],str(self.runtime._persistence_key))
        self.assertNotIn('burn',{e['kind'] for e in self.runtime._player_combat_profile_locked()['enchant_effects']})
        self.assertIn('slow',{e['kind'] for e in self.runtime._player_combat_profile_locked()['enchant_effects']})

    def test_invalid_target_cancel_expiry_and_stale_confirmation_preserve_the_real_scroll(self):
        scroll=self.scroll();quantity=copy.deepcopy(self.runtime._inventory)
        self.call('PickupInventoryItem(8)')
        self.assertTrue(self.view()['item_targeting']['active']);self.assertEqual(quantity,self.runtime._inventory)
        self.call('SpellStopTargeting()')
        self.assertFalse(self.view()['item_targeting']['active']);self.assertIn(scroll['instance_id'],self.runtime._item_instances)
        scroll=self.scroll('blue');old=self.view()['item_targeting']['generation']
        result=self.service('EnchantPick',item='starter-iron-saber',target_generation=old-1)
        self.assertEqual(result['error'],'ENCHANT_CURSOR_CHANGED')
        self.assertIn(scroll['instance_id'],self.runtime._item_instances)
        self.runtime._item_target['expires']=0;self.publish()
        self.assertFalse(self.view()['item_targeting']['active'])
        self.assertIsNone(self.runtime.move_inventory_slot(scroll['instance_id'],63).get('error'))

    def test_failed_save_restores_pending_cursor_exact_scroll_gear_and_binding_for_retry(self):
        scroll=self.scroll();blade=self.runtime._item_instances['starter-iron-saber']
        with patch.dict(enchants.CATALOG['enchant.chromatic.red'],{'binds':True}):
            self.call('PickupInventoryItem(16)')
            before=copy.deepcopy((self.runtime._inventory,self.runtime._item_instances,self.runtime._item_target))
            with patch.object(self.runtime,'save_state',side_effect=OSError('fixture disk')):
                self.assertEqual(self.answer('EnchantBindConfirm')['error'],'SERVICE_SAVE_FAILED')
            self.assertEqual(before,(self.runtime._inventory,self.runtime._item_instances,self.runtime._item_target))
            self.assertIsNone(self.answer('EnchantBindConfirm').get('error'))
        self.assertNotIn(scroll['instance_id'],self.runtime._item_instances)
        self.assertEqual(self.runtime._item_instances[blade['instance_id']]['bound_to'],str(self.runtime._persistence_key))

    def test_changed_target_dead_player_and_locked_crafting_do_not_consume(self):
        scroll=self.scroll()
        with patch.dict(enchants.CATALOG['enchant.chromatic.red'],{'binds':True}):
            self.call('PickupInventoryItem(16)')
            blade=self.runtime._item_instances['starter-iron-saber'];blade['gear']['condition']=.5
            candidate=dict(self.runtime._inventory);candidate[scroll['definition_id']]=0
            self.assertEqual(self.runtime._craft_inventory_error_locked(candidate),'ITEM_PENDING_CONFIRMATION')
            self.assertEqual(self.answer('EnchantBindConfirm')['error'],'ENCHANT_TARGET_CHANGED')
            self.runtime._combat_state['actors']['player']['alive']=False
            self.assertEqual(self.answer('EnchantBindConfirm')['error'],'PLAYER_DEFEATED')
            self.assertIsNone(self.answer('EnchantCancel').get('error'))
        self.assertIn(scroll['instance_id'],self.runtime._item_instances)

    def test_original_actionbar_accepts_real_scroll_and_arms_the_same_cursor_without_consumption(self):
        self.bridge.gameEngineActionBarEdit=self.runtime.action_bar_edit
        self.bridge.gameEngineActionUse=self.runtime.action_use
        scroll=self.scroll();self.call('SpellStopTargeting()');before=copy.deepcopy(self.runtime._inventory)
        self.call(f"PickupContainerItem(0,{scroll['slot_index']+1});PlaceAction(12)")
        self.assertEqual(self.runtime._actions.slots[11],{'kind':'ITEM','ref':scroll['definition_id']})
        self.assertEqual(self.ui.evaluate('return IsUsableAction(12)'),[1,None])
        self.call('UseAction(12)')
        self.assertTrue(self.view()['item_targeting']['active']);self.assertEqual(self.runtime._item_target['scroll'],scroll['instance_id'])
        self.assertEqual(self.runtime._inventory,before)
        self.assertEqual(self.ui.evaluate('return IsUsableAction(12)'),[None,None])

    def test_trade_enchant_cannot_modify_gear_or_scroll_waiting_for_an_original_confirmation(self):
        from backend import game_engine_adapter_trade_enchant as trade
        scroll=self.scroll();blade=self.runtime._item_instances['starter-iron-saber']
        with patch.dict(enchants.CATALOG['enchant.chromatic.red'],{'binds':True}):self.call('PickupInventoryItem(16)')
        offer={'slots':{},'enchant_item':blade['instance_id'],'enchant_id':'enchant.chromatic.red','enchant_scroll':scroll['instance_id']}
        before=copy.deepcopy((self.runtime._item_instances,self.runtime._inventory))
        with self.assertRaisesRegex(ValueError,'ITEM_PENDING_CONFIRMATION'):trade.select_item(self.runtime,offer,blade['instance_id'])
        with self.assertRaisesRegex(ValueError,'ITEM_PENDING_CONFIRMATION'):trade.apply(self.runtime,offer)
        self.assertEqual(before,(self.runtime._item_instances,self.runtime._inventory))

if __name__=='__main__':unittest.main()
