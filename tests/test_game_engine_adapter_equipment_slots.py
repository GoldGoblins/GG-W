"""All nineteen doll slots retain canonical custody and survive real saves."""
import copy
import unittest
from unittest.mock import patch
import test_game_engine_adapter_item_binding as binding
from backend import game_engine_items as items
from backend.game_engine_adapter_gameplay import EQUIPMENT_SLOTS


class EquipmentSlots(unittest.TestCase):
    setUp=binding.ItemBinding.setUp
    publish=binding.ItemBinding.publish
    call=binding.ItemBinding.call
    control=binding.ItemBinding.control
    service=binding.ItemBinding.service
    view=binding.ItemBinding.view

    def source(self,slot,index=0):
        ref='item.doll_fixture_'+slot.lower()
        self.runtime._item_catalog['items'][ref]=dict(id=ref,name='Owned '+slot,kind='ACCESSORY',rarity='COMMON',
            stack_limit=1,equip_slot=slot,equip_slots=['RING_1','RING_2'] if slot.startswith('RING_') else [slot],tags=[])
        item=items.make_instance(self.runtime._item_catalog,'doll-'+slot+'-'+str(index),ref)
        self.runtime._item_instances[item['instance_id']]=item
        self.runtime._inventory[ref]=self.runtime._inventory.get(ref,0)+1
        self.runtime._engine_item_templates=None;self.publish()
        return item

    def wear_original(self,item,slot):
        self.publish();item=self.runtime._item_instances[item['instance_id']]
        self.call(f'PickupContainerItem(0,{item["slot_index"]+1});PickupInventoryItem({EQUIPMENT_SLOTS[slot]})')
        self.assertEqual(self.runtime._item_instances[item['instance_id']]['equipped_slot'],slot)

    def test_real_shirt_two_ring_cells_original_swap_rollback_and_restore(self):
        shirt=self.source('SHIRT');first=self.source('RING_1');second=self.source('RING_1',1)
        for item,slot in ((shirt,'SHIRT'),(first,'RING_1'),(second,'RING_2')):self.wear_original(item,slot)
        replacement=self.source('RING_1',2)
        before=copy.deepcopy((self.runtime._item_instances,self.runtime._inventory))
        with patch.object(self.runtime._state_store,'save',side_effect=OSError('disk full')):
            outcome=self.runtime.equip_item(replacement['instance_id'],'RING_2')
        self.assertEqual(outcome.get('error'),'ITEM_EQUIPMENT_SAVE_FAILED');self.assertTrue(before==(self.runtime._item_instances,self.runtime._inventory))
        self.wear_original(replacement,'RING_2')
        self.assertEqual(self.runtime._item_instances[second['instance_id']]['location'],'INVENTORY')
        expected=copy.deepcopy(self.runtime._item_instances);self.runtime.save_state();self.runtime.load_state();self.publish()
        self.assertTrue(expected==self.runtime._item_instances,'Equipment custody changed on restore')
        for slot,item in ((4,shirt),(11,first),(12,replacement)):
            link=self.ui.evaluate(f'return GetInventoryItemLink("player",{slot})')[0]
            self.assertIn('Owned RING_1' if slot in (11,12) else 'Owned SHIRT',link)

    def test_all_nineteen_actual_instances_fit_the_authoritative_snapshot_and_original_readers(self):
        for item in list(self.runtime._player_equipped_instances_locked()):
            self.assertIsNone(self.runtime.unequip_item(item['instance_id']).get('error'))
        owned=[]
        for slot in EQUIPMENT_SLOTS:
            item=self.source(slot);outcome=self.runtime.equip_item(item['instance_id'],slot)
            self.assertIsNone(outcome.get('error'),slot+': '+str(outcome.get('error')));owned.append(item['instance_id'])
        self.publish();snapshot=self.runtime.snapshot()
        self.assertEqual(snapshot['gear']['slots'],19)
        self.assertEqual({r['instance_id'] for r in snapshot['items']['equipment']},set(owned))
        for slot in range(1,20):self.assertIsNotNone(self.ui.evaluate(f'return GetInventoryItemLink("player",{slot})')[0])
        expected=copy.deepcopy(self.runtime._item_instances);self.runtime.save_state();self.runtime.load_state();self.publish()
        self.assertTrue(expected==self.runtime._item_instances,'Nineteen equipped instances failed to restore')

    def test_original_worn_to_bag_swap_saves_once_at_the_requested_cell_and_failure_keeps_the_worn_item(self):
        first=self.source('RING_1');second=self.source('RING_1',1);self.wear_original(first,'RING_1')
        cell=self.runtime._item_instances[second['instance_id']]['slot_index']
        with patch.object(self.runtime._state_store,'save',wraps=self.runtime._state_store.save) as save:
            self.assertIsNone(self.runtime.move_equipment_to_inventory(first['instance_id'],cell).get('error'))
        self.assertEqual(save.call_count,1)
        self.assertEqual(self.runtime._item_instances[first['instance_id']]['slot_index'],cell)
        self.assertEqual(self.runtime._item_instances[second['instance_id']]['equipped_slot'],'RING_1')
        expected=copy.deepcopy(self.runtime._item_instances);self.runtime.load_state();self.publish()
        self.assertTrue(expected==self.runtime._item_instances,'Requested bag destination was not saved')
        with patch.object(self.runtime._state_store,'save',side_effect=OSError('disk full')):
            self.assertEqual(self.runtime.unequip_item(second['instance_id']).get('error'),'ITEM_EQUIPMENT_SAVE_FAILED')
        self.assertTrue(expected==self.runtime._item_instances,'Failed unequip changed item custody')


if __name__=='__main__':unittest.main()
