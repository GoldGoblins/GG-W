"""Original wrap cursor uses crafted paper, one saved item and real custody."""
import copy
import unittest
from unittest.mock import patch
import test_game_engine_adapter_services as services
from backend import game_engine_items as items
from backend.game_engine_adapter_wrapping import PAPER,GIFT


class Wrapping(unittest.TestCase):
    publish=services.Services.publish
    call=services.Services.call
    control=services.Services.control
    service=services.Services.service
    view=services.Services.view
    move_near_npc=services.Services.move_near_npc

    def setUp(self):
        services.Services.setUp(self)
        self.bridge.gameEngineContainerUseItem=lambda ref,item:self.runtime.action_use_item(ref,item)

    def ready(self):
        before=dict(self.runtime._inventory)
        self.assertIsNone((self.runtime.craft_recipe('recipe.wrapping_paper')).get('error'))
        self.assertEqual(self.runtime._inventory['material.fiber'],before['material.fiber']-2)
        self.assertEqual(self.runtime._inventory['material.resin'],before['material.resin']-1)
        paper=next(i for i in self.runtime._item_instances.values() if i['definition_id']==PAPER and i['location']=='INVENTORY')
        target=self.runtime._item_instances['starter-iron-saber'];self.runtime.unequip_item(target['instance_id'])
        self.publish();self.call(f"UseContainerItem(0,{paper['slot_index']+1})")
        self.assertIsNotNone(self.view()['inventory_cursor']['wrap'])
        return paper,target

    def wrap(self,paper,target):
        cursor=self.view()['inventory_cursor']['wrap']
        return self.service('InventoryWrap',item=target['instance_id'],paper=paper['instance_id'],wrap_generation=cursor['generation'])

    def test_original_cursor_wrap_and_unwrap_preserve_the_same_gear_and_consume_one_crafted_paper(self):
        paper,target=self.ready();original=copy.deepcopy(target);quantity=paper['quantity'];identity=target['instance_id']
        self.call(f"PickupContainerItem(0,{target['slot_index']+1})")
        actual=self.runtime._item_instances[identity]
        self.assertEqual(actual['definition_id'],GIFT);self.assertEqual(paper['quantity'],quantity-1)
        self.assertEqual(actual['gift']['original'],original);self.assertIsNone(self.view()['inventory_cursor']['wrap'])
        self.assertNotIn(original['definition_id'],self.runtime._inventory)
        self.assertEqual(self.runtime._inventory[GIFT],1)
        self.runtime.load_state();self.publish();actual=self.runtime._item_instances[identity]
        self.assertEqual(actual['definition_id'],GIFT);self.assertEqual(actual['gift']['original']['gear'],original['gear'])
        self.call(f"UseContainerItem(0,{actual['slot_index']+1})")
        unwrapped=self.runtime._item_instances[identity]
        self.assertEqual(unwrapped['definition_id'],original['definition_id']);self.assertEqual(unwrapped['gear'],original['gear'])
        self.assertNotIn('gift',unwrapped);self.assertNotIn(GIFT,self.runtime._inventory)
        self.assertEqual(self.runtime._inventory[original['definition_id']],1)

    def test_failed_wrap_and_unwrap_save_restore_the_exact_payload_counts_and_cursor(self):
        paper,target=self.ready();before=copy.deepcopy((self.runtime._item_instances,self.runtime._inventory,self.runtime._gift_wrap))
        with patch.object(self.runtime,'save_state',side_effect=OSError('fixture disk')):
            self.assertEqual(self.wrap(paper,target)['error'],'SERVICE_SAVE_FAILED')
        self.assertEqual(before,(self.runtime._item_instances,self.runtime._inventory,self.runtime._gift_wrap))
        paper=self.runtime._item_instances[paper['instance_id']];target=self.runtime._item_instances[target['instance_id']]
        self.assertIsNone((self.wrap(paper,target)).get('error'));before=copy.deepcopy((self.runtime._item_instances,self.runtime._inventory))
        with patch.object(self.runtime,'save_state',side_effect=OSError('fixture disk')):
            self.assertEqual(self.service('InventoryUnwrap',item=target['instance_id'])['error'],'SERVICE_SAVE_FAILED')
        self.assertEqual(before,(self.runtime._item_instances,self.runtime._inventory))
        self.assertIsNone((self.service('InventoryUnwrap',item=target['instance_id'])).get('error'))

    def test_paper_lock_cancel_expiry_and_stale_source_never_consume_another_stack(self):
        paper,target=self.ready();quantity=paper['quantity'];cursor=self.view()['inventory_cursor']['wrap']
        self.assertEqual(self.runtime.move_inventory_slot(paper['instance_id'],63)['error'],'ITEM_PENDING_CONFIRMATION')
        self.call('ClearCursor()');self.assertIsNone(self.view()['inventory_cursor']['wrap'])
        self.assertEqual(paper['quantity'],quantity)
        self.assertEqual(self.service('InventoryWrap',item=target['instance_id'],paper=paper['instance_id'],wrap_generation=cursor['generation'])['error'],'WRAPPING_PAPER_CHANGED')
        self.call(f"UseContainerItem(0,{paper['slot_index']+1})")
        self.runtime._gift_wrap['expires']=0;self.publish();self.assertIsNone(self.view()['inventory_cursor']['wrap'])
        self.assertEqual(paper['quantity'],quantity)

    def test_bound_stackable_already_wrapped_and_paper_itself_are_rejected(self):
        paper,target=self.ready();before=paper['quantity']
        self.assertEqual(self.wrap(paper,paper)['error'],'WRAPPING_PAPER_CANNOT_WRAP_ITSELF')
        target=self.runtime._item_instances[target['instance_id']];target['bound_to']=self.runtime._persistence_key
        self.assertEqual(self.wrap(paper,target)['error'],'WRAPPING_BOUND_ITEM')
        target=self.runtime._item_instances[target['instance_id']];target.pop('bound_to')
        material=next(i for i in self.runtime._item_instances.values() if i.get('location')=='INVENTORY' and i.get('quantity',1)>1 and i['definition_id']!=PAPER)
        self.assertEqual(self.wrap(paper,material)['error'],'WRAPPING_STACKABLE_ITEM')
        self.assertEqual(self.runtime._item_instances[paper['instance_id']]['quantity'],before)
        self.assertIsNone((self.wrap(paper,target)).get('error'));target=self.runtime._item_instances[target['instance_id']]
        paper=self.runtime._item_instances[paper['instance_id']]
        self.runtime.action_use_item(PAPER,paper['instance_id'])
        self.assertEqual(self.wrap(paper,target)['error'],'WRAPPING_ITEM_INELIGIBLE')

    def test_wrapped_mail_escrow_and_restore_keep_the_same_hidden_item_without_craftable_contents(self):
        paper,target=self.ready();identity=target['instance_id'];original=copy.deepcopy(target)
        self.wrap(paper,target);self.service('MailOpen')
        self.assertIsNone((self.service('MailSend',target='player',subject='A gift',item=identity)).get('error'))
        self.runtime.load_state();self.publish();gift=self.runtime._item_instances[identity]
        self.assertEqual(gift['location'],'MAIL');self.assertEqual(gift['gift']['original']['gear'],original['gear'])
        self.assertNotIn(original['definition_id'],self.runtime._inventory)
        self.service('MailOpen');mail=next(m for m in self.view()['mail']['rows'] if m['subject']=='A gift')
        self.assertIsNone((self.service('MailItem',id=mail['id'])).get('error'))
        self.assertIsNone((self.service('InventoryUnwrap',item=identity)).get('error'))
        self.assertEqual(self.runtime._item_instances[identity]['definition_id'],original['definition_id'])
        self.assertEqual(self.runtime._item_instances[identity]['gear'],original['gear'])
        self.assertIsNone(self.view()['inventory_cursor']['wrap'])

    def test_invalid_hidden_payload_cannot_unwrap_into_a_stack_or_quest_item(self):
        paper,target=self.ready();self.assertIsNone(self.wrap(paper,target).get('error'))
        identity=target['instance_id']
        for ref in ('material.fiber','item.guild_charter'):
            current=self.runtime._item_instances[identity]
            current['gift']['original']=items.make_instance(self.runtime._item_catalog,'invalid-original',ref)
            before=copy.deepcopy((self.runtime._item_instances,self.runtime._inventory))
            self.assertEqual(self.service('InventoryUnwrap',item=identity)['error'],'WRAPPED_GIFT_INVALID')
            self.assertEqual(before,(self.runtime._item_instances,self.runtime._inventory))

    def test_missing_content_pack_keeps_hidden_identity_and_gear_until_the_real_definition_returns(self):
        paper,target=self.ready();original=copy.deepcopy(target);key=target['instance_id'];ref=target['definition_id']
        self.assertIsNone(self.wrap(paper,target).get('error'))
        definition=self.runtime._item_catalog['items'].pop(ref)
        self.runtime.load_state();self.publish();gift=self.runtime._item_instances[key]
        self.assertEqual(gift['gift']['original']['definition_id'],ref)
        self.assertEqual(gift['gift']['original']['gear'],original['gear'])
        before=copy.deepcopy((self.runtime._item_instances,self.runtime._inventory))
        self.assertEqual(self.service('InventoryUnwrap',item=key).get('error'),'WRAPPED_GIFT_CONTENT_UNAVAILABLE')
        self.assertTrue(before==(self.runtime._item_instances,self.runtime._inventory))
        self.runtime._item_catalog['items'][ref]=definition
        self.assertIsNone(self.service('InventoryUnwrap',item=key).get('error'))
        self.assertEqual(self.runtime._item_instances[key]['definition_id'],ref)
        self.assertEqual(self.runtime._item_instances[key]['gear'],original['gear'])

    def test_invalid_bounded_hidden_payload_is_retained_through_repeated_saves_and_cannot_be_unwrapped(self):
        paper,target=self.ready();key=target['instance_id'];self.assertIsNone(self.wrap(paper,target).get('error'))
        invalid=copy.deepcopy(self.runtime._item_instances[key]['gift']);invalid['original']['quantity']=2
        self.runtime._item_instances[key]['gift']=invalid;self.runtime.save_state();self.runtime.load_state();self.publish()
        item=self.runtime._item_instances[key]
        self.assertTrue(item['gift_invalid']);self.assertEqual(item['gift_quarantine'],invalid)
        before=copy.deepcopy((self.runtime._item_instances,self.runtime._inventory))
        self.assertEqual(self.service('InventoryUnwrap',item=key).get('error'),'WRAPPED_GIFT_INVALID')
        self.assertTrue(before==(self.runtime._item_instances,self.runtime._inventory))
        self.runtime.save_state();self.runtime.load_state();self.assertEqual(self.runtime._item_instances[key]['gift_quarantine'],invalid)

    def test_oversized_saved_hidden_payload_rejects_restore_before_replacing_actual_items_or_pose(self):
        paper,target=self.ready();key=target['instance_id'];self.assertIsNone(self.wrap(paper,target).get('error'))
        payload=self.runtime._state_store.load(self.runtime._persistence_key)
        gift=next(i for i in payload['item_instances'] if i['instance_id']==key)
        gift['gift']['extra']='x'*17000
        self.runtime._state_store.save(self.runtime._persistence_key,payload)
        before=copy.deepcopy((self.runtime._item_instances,self.runtime._inventory,self.runtime._lifecycle_position_locked()))
        self.assertEqual(self.runtime.load_state().get('error'),'ITEM_SAVE_GIFT_PAYLOAD_INVALID')
        self.assertTrue(before==(self.runtime._item_instances,self.runtime._inventory,self.runtime._lifecycle_position_locked()))
        restored=self.runtime._state_store.load(self.runtime._persistence_key)
        self.assertEqual(next(i for i in restored['item_instances'] if i['instance_id']==key)['gift']['extra'],'x'*17000)

if __name__=='__main__':unittest.main()
