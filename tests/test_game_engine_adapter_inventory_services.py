"""Original destroy/auto-store intents preserve custody, counts and saves."""
import copy
import unittest
from unittest.mock import patch
import test_game_engine_adapter_services as service_tests
from backend import game_engine_items as items


class Inventory(unittest.TestCase):
    setUp=service_tests.Services.setUp
    publish=service_tests.Services.publish
    call=service_tests.Services.call
    control=service_tests.Services.control
    view=service_tests.Services.view
    service=service_tests.Services.service

    def stack(self,identity,quantity):
        with self.runtime._lock:
            row=items.make_instance(self.runtime._item_catalog,identity,'item.field_ration',quantity=quantity,location='GROUND')
            self.runtime._item_instances[identity]=row;ok,result=self.runtime._move_item_locked(row,'INVENTORY',owner_id='player');self.assertTrue(ok,result)
            self.runtime._ensure_inventory_slots_locked()
            return row

    def test_original_delete_cursor_removes_only_the_exact_item_and_survives_reload(self):
        row=self.stack('destroy-probe',4);other=self.stack('destroy-keep',3);self.publish()
        self.call(f'PickupContainerItem(0,{row["slot_index"]+1}) DeleteCursorItem()')
        self.assertNotIn(row['instance_id'],self.runtime._item_instances)
        self.assertIn(other['instance_id'],self.runtime._item_instances);self.assertEqual(self.runtime._inventory['item.field_ration'],3)
        self.runtime.load_state();self.assertNotIn(row['instance_id'],self.runtime._item_instances)
        self.assertEqual(self.runtime._inventory['item.field_ration'],3)

    def test_original_whole_and_split_auto_store_use_compatible_stacks_and_one_commit(self):
        row=self.stack('auto-source',4);other=self.stack('auto-target',3);self.publish()
        with patch.object(self.runtime._state_store,'save',wraps=self.runtime._state_store.save) as save:
            self.call(f'PickupContainerItem(0,{row["slot_index"]+1}) PutItemInBackpack()')
        self.assertEqual(save.call_count,1);self.assertEqual(self.runtime._item_instances[other['instance_id']]['quantity'],7)
        self.assertNotIn(row['instance_id'],self.runtime._item_instances)
        self.call(f'SplitContainerItem(0,{other["slot_index"]+1},2) PutItemInBackpack()')
        owned=[i for i in self.runtime._item_instances.values() if i.get('definition_id')=='item.field_ration' and i.get('location')=='INVENTORY']
        self.assertEqual(sorted(i['quantity'] for i in owned),[2,5]);self.assertEqual(self.runtime._inventory['item.field_ration'],7)
        self.runtime.load_state();self.assertEqual(self.runtime._inventory['item.field_ration'],7)

    def test_failed_destroy_or_split_save_restores_item_and_aggregate(self):
        row=self.stack('rollback-probe',4)
        for op in ('InventoryDestroy','InventoryAutoStore'):
            before=copy.deepcopy((self.runtime._item_instances,self.runtime._inventory,self.runtime._item_counter))
            with patch.object(self.runtime._state_store,'save',side_effect=OSError('disk full')):
                self.assertEqual(self.service(op,item=row['instance_id'],count=2)['error'],'SERVICE_SAVE_FAILED')
            self.assertEqual(before,(self.runtime._item_instances,self.runtime._inventory,self.runtime._item_counter))

if __name__=='__main__':unittest.main()
