"""Real original bind decisions, owned instances, locks and failed-save rollback."""
import copy
import unittest
from unittest.mock import patch
import test_game_engine_adapter_services as services
from backend import game_engine_items as items


class ItemBinding(unittest.TestCase):
    publish=services.Services.publish
    call=services.Services.call
    control=services.Services.control
    service=services.Services.service
    view=services.Services.view
    move_near_npc=services.Services.move_near_npc

    def setUp(self):
        services.Services.setUp(self)
        self.bridge.gameEngineItemEquip=lambda item,slot:self.runtime.equip_item(item,slot)
        self.bridge.gameEngineContainerUseItem=lambda definition,item:self.runtime.action_use_item(definition,item)
        self.bridge.gameEngineEquipmentMove=lambda item,slot:self.runtime.move_equipment_to_inventory(item,slot)
        self.ui.execute("BIND_EVENTS={};BIND_FRAME=CreateFrame('Frame');for _,e in ipairs({'EQUIP_BIND_CONFIRM','AUTOEQUIP_BIND_CONFIRM','USE_BIND_CONFIRM'}) do BIND_FRAME:RegisterEvent(e) end;BIND_FRAME:SetScript('OnEvent',function() table.insert(BIND_EVENTS,{event,arg1}) end)")

    def source(self,ref='item.iron_saber',mode=2,quantity=1):
        self.runtime._item_catalog['items'][ref]['bonding']=mode
        self.runtime._engine_item_templates=None
        item=items.make_instance(self.runtime._item_catalog,'binding-fixture-'+str(mode),ref,quantity=quantity)
        self.runtime._item_instances[item['instance_id']]=item
        self.runtime._inventory[ref]=self.runtime._inventory.get(ref,0)+quantity
        self.publish()
        return item

    def answer(self,op='ItemBindingEquipAnswer',**fields):
        return self.service(op,binding_generation=self.view()['item_binding']['generation'],**fields)

    def test_original_equip_answer_saves_exact_item_and_replay_cannot_bind_twice(self):
        item=self.source();slot=item['slot_index'];old=next(i for i in self.runtime._item_instances.values() if i.get('equipped_slot')=='MAIN_HAND')
        self.call(f'PickupContainerItem(0,{slot+1});PickupInventoryItem(16)')
        self.assertEqual(item['location'],'INVENTORY');self.assertEqual(old['location'],'EQUIPPED')
        self.assertEqual(self.ui.evaluate('return BIND_EVENTS[1][1],BIND_EVENTS[1][2]'),['EQUIP_BIND_CONFIRM',0])
        self.assertEqual(self.ui.evaluate(f'local _,_,locked=GetContainerItemInfo(0,{slot+1});return locked,IsInventoryItemLocked(16)'),[1,1])
        self.call('EquipPendingItem(0)')
        actual=self.runtime._item_instances[item['instance_id']]
        self.assertEqual(actual['location'],'EQUIPPED');self.assertEqual(actual['bound_to'],self.runtime._persistence_key)
        self.assertEqual(self.runtime._item_instances[old['instance_id']]['slot_index'],slot)
        before=copy.deepcopy((self.runtime._item_instances,self.runtime._inventory));self.call('EquipPendingItem(0)')
        self.assertEqual(before,(self.runtime._item_instances,self.runtime._inventory))
        self.runtime.load_state();self.publish()
        self.assertEqual(self.runtime._item_instances[item['instance_id']]['bound_to'],self.runtime._persistence_key)
        self.assertFalse(self.view()['item_binding']['equips'])
        self.ui.execute("BIND_TIP=CreateFrame('GameTooltip','BindingTip');BIND_TIP:SetInventoryItem('player',16)")
        lines=self.ui.evaluate('return BindingTipTextLeft2:GetText()')
        self.assertIn('Soulbound',lines[0])

    def test_auto_equip_cancel_replacement_expiry_and_required_level(self):
        item=self.source();self.call(f"PickupContainerItem(0,{item['slot_index']+1});AutoEquipCursorItem()")
        self.assertEqual(self.ui.evaluate('return BIND_EVENTS[1][1]'),['AUTOEQUIP_BIND_CONFIRM'])
        self.assertEqual(self.runtime.move_inventory_slot(item['instance_id'],63)['error'],'ITEM_PENDING_CONFIRMATION')
        self.assertEqual(self.runtime.drop_item(item['instance_id'])['error'],'ITEM_PENDING_CONFIRMATION')
        self.call('CancelPendingEquip(0)');self.assertNotIn('bound_to',item)
        self.assertFalse(self.view()['item_binding']['equips'])
        definition=self.runtime._item_catalog['items'][item['definition_id']];definition['required_level']=60
        self.assertEqual(self.runtime.equip_item(item['instance_id'])['error'],'ITEM_LEVEL_REQUIRED')
        self.assertFalse(self.view()['item_binding']['equips']);definition['required_level']=0
        self.runtime.equip_item(item['instance_id']);record=next(iter(self.runtime._item_pending_equips.values()))
        record['expires']=0;self.publish();self.assertFalse(self.view()['item_binding']['equips'])
        self.assertIsNone((self.runtime.move_inventory_slot(item['instance_id'],63)).get('error'))

    def test_failed_save_stale_epoch_source_destination_and_dead_confirm_preserve_assets(self):
        item=self.source();self.runtime.equip_item(item['instance_id']);self.publish()
        before=copy.deepcopy((self.runtime._item_instances,self.runtime._inventory,self.runtime._item_pending_equips))
        with patch.object(self.runtime,'save_state',side_effect=OSError('fixture disk')):
            self.assertEqual(self.answer(index=0,accept=True)['error'],'SERVICE_SAVE_FAILED')
        self.assertEqual(before,(self.runtime._item_instances,self.runtime._inventory,self.runtime._item_pending_equips))
        gen=self.view()['item_binding']['generation']
        self.assertEqual(self.service('ItemBindingEquipAnswer',binding_generation=gen-1,index=0,accept=True)['error'],'ITEM_BIND_WINDOW_CHANGED')
        current=self.runtime._item_instances[item['instance_id']];current['slot_index']=63
        self.assertEqual(self.answer(index=0,accept=True)['error'],'ITEM_BIND_SOURCE_CHANGED')
        current=self.runtime._item_instances[item['instance_id']];current['slot_index']=item['slot_index']
        actor=self.runtime._combat_state['actors']['player'];actor['alive']=False;actor['health']=0
        self.assertEqual(self.answer(index=0,accept=True)['error'],'PLAYER_DEFEATED')
        self.assertIsNone((self.answer(index=0,accept=False)).get('error'))

    def test_original_bind_on_use_consumes_one_and_binds_only_the_remaining_exact_stack(self):
        item=self.source('item.field_ration',3,2);actor=self.runtime._combat_state['actors']['player'];actor['health']=25
        self.call(f"UseContainerItem(0,{item['slot_index']+1})")
        self.assertEqual(self.ui.evaluate('return BIND_EVENTS[1][1]'),['USE_BIND_CONFIRM'])
        self.assertEqual(item['quantity'],2);self.assertEqual(actor['health'],25)
        self.call('ConfirmBindOnUse()');actual=self.runtime._item_instances[item['instance_id']]
        self.assertEqual(actual['quantity'],1);self.assertEqual(actual['bound_to'],self.runtime._persistence_key)
        self.assertEqual(self.runtime._combat_state['actors']['player']['health'],50)
        self.call('ConfirmBindOnUse()');self.assertEqual(actual['quantity'],1)
        self.runtime.load_state();self.assertEqual(self.runtime._item_instances[item['instance_id']]['bound_to'],self.runtime._persistence_key)

    def test_bound_mail_auction_trade_drop_and_cross_character_stash_are_rejected(self):
        item=self.source();self.runtime.equip_item(item['instance_id']);self.answer(index=0,accept=True)
        self.runtime.unequip_item(item['instance_id']);self.move_near_npc();self.publish()
        self.service('MailOpen');self.assertEqual(self.service('MailSend',target='player',subject='Bound',item=item['instance_id'])['error'],'TRADE_ITEM_BOUND')
        self.service('AuctionOpen');self.assertEqual(self.service('AuctionStart',item=item['instance_id'],min_bid=10,buyout=20,duration=120)['error'],'TRADE_ITEM_BOUND')
        self.service('TradeOpen',target='npc-wanderer-01');self.assertEqual(self.service('TradeSet',slot=1,item=item['instance_id'])['error'],'TRADE_ITEM_BOUND')
        self.assertEqual(self.runtime.drop_item(item['instance_id'])['error'],'ITEM_BOUND_CANNOT_DROP')
        with patch.object(self.runtime,'_stash_access_locked',return_value=True):
            self.assertIsNone((self.runtime.deposit_to_stash(item['instance_id'])).get('error'))
            stored=self.runtime._stash_state['item']['instance_id']
            key=self.runtime._persistence_key;self.runtime._persistence_key='another-fixture-character'
            self.assertEqual(self.runtime.withdraw_from_stash(stored)['error'],'ITEM_BOUND_TO_ANOTHER_CHARACTER')
            self.runtime._persistence_key=key
            self.assertIsNone((self.runtime.withdraw_from_stash(stored)).get('error'))
        self.assertEqual(self.runtime._item_instances[stored]['bound_to'],key)

    def test_reverse_doll_swap_defers_then_returns_the_old_weapon_to_the_clicked_cell(self):
        item=self.source();old=next(i for i in self.runtime._item_instances.values() if i.get('equipped_slot')=='MAIN_HAND')
        source_slot=item['slot_index']
        self.call(f"PickupInventoryItem(16);PickupContainerItem(0,{item['slot_index']+1})")
        self.assertEqual(old['location'],'EQUIPPED');self.assertEqual(item['location'],'INVENTORY')
        self.call('EquipPendingItem(0)')
        self.assertEqual(self.runtime._item_instances[item['instance_id']]['location'],'EQUIPPED')
        self.assertEqual(self.runtime._item_instances[old['instance_id']]['slot_index'],source_slot)

    def test_original_loot_binds_pickup_item_before_any_transfer_and_preserves_binding_on_reload(self):
        self.bridge.gameEngineLootSlot=lambda session,source,item:self.runtime.loot_slot(session,source,item)
        source=next(i for i in self.runtime._item_instances.values() if i.get('kind')=='CONTAINER' and i.get('location')=='GROUND'
                    and any(r.get('location')=='CONTAINER' and r.get('container_id')==i['instance_id'] for r in self.runtime._item_instances.values()))
        target=next(i for i in self.runtime._item_instances.values() if i.get('location')=='CONTAINER' and i.get('container_id')==source['instance_id'])
        self.runtime._item_catalog['items'][target['definition_id']]['bonding']=1;self.runtime._engine_item_templates=None
        position=source['position'];self.runtime._x[0]=position['x'];self.runtime._z[0]=position['z'];self.runtime._y[0]=position['y']+.65
        self.assertIsNone(self.runtime.open_container(source['instance_id']).get('error'));self.publish()
        self.ui.execute("pick=CreateFrame('LootButton','BindingLootPick');pick:SetWidth(30);pick:SetHeight(30);pick:SetPoint('CENTER',UIParent,'CENTER',0,0);pick:SetSlot(1);pick:RegisterForClicks('LeftButtonUp')")
        self.ui.click('BindingLootPick');self.presentation._ui_requests(self.ui.request('requests'));self.publish()
        self.assertEqual(self.runtime._item_instances[target['instance_id']]['location'],'CONTAINER')
        self.assertEqual(self.runtime._loot_view_locked()['pending_bind']['item'],target['instance_id'])
        before=copy.deepcopy((self.runtime._item_instances,self.runtime._inventory,self.runtime._engine_loot))
        with patch.object(self.runtime,'save_state',side_effect=OSError('fixture disk')):
            failed=self.service('LootBindConfirm',loot_session=self.runtime._engine_loot['session'],source=source['instance_id'],item=target['instance_id'])
            self.assertEqual(failed['error'],'SERVICE_SAVE_FAILED')
        self.assertEqual(before,(self.runtime._item_instances,self.runtime._inventory,self.runtime._engine_loot))
        self.call('LootSlot(1)')
        actual=self.runtime._item_instances[target['instance_id']]
        self.assertEqual(actual['location'],'INVENTORY');self.assertEqual(actual['bound_to'],self.runtime._persistence_key)
        after=copy.deepcopy((self.runtime._item_instances,self.runtime._inventory));self.call('LootSlot(1)')
        self.assertEqual(after,(self.runtime._item_instances,self.runtime._inventory))
        self.assertEqual(self.runtime.drop_item(actual['instance_id'])['error'],'ITEM_BOUND_CANNOT_DROP')
        self.runtime.save_state();self.runtime.load_state();self.publish()
        self.assertEqual(self.runtime._item_instances[target['instance_id']]['bound_to'],self.runtime._persistence_key)
        self.service('MailOpen');self.assertEqual(self.service('MailSend',target='player',subject='Bound pickup',item=target['instance_id'])['error'],'TRADE_ITEM_BOUND')

    def test_quest_reward_count_reconciliation_binds_new_stack_to_this_character(self):
        ref='item.iron_saber';self.runtime._item_catalog['items'][ref]['bonding']=4
        self.runtime._inventory[ref]=self.runtime._inventory.get(ref,0)+1
        old=set(self.runtime._item_instances);self.runtime._reconcile_item_instances_locked()
        new=[i for key,i in self.runtime._item_instances.items() if key not in old and i['definition_id']==ref]
        self.assertEqual(len(new),1);self.assertEqual(new[0]['bound_to'],self.runtime._persistence_key)
        self.runtime.save_state();self.runtime.load_state()
        self.assertEqual(self.runtime._item_instances[new[0]['instance_id']]['bound_to'],self.runtime._persistence_key)

if __name__=='__main__':unittest.main()
