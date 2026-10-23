"""Original context-sale consumer over the same real vendor and exact cursor."""
import copy
import unittest
from unittest.mock import patch
import test_game_engine_adapter_transactions as transactions


class WorldCursor(unittest.TestCase):
    setUp=transactions.Transactions.setUp
    setUpClass=classmethod(transactions.Transactions.setUpClass.__func__)
    refresh=transactions.Transactions.refresh
    run_lua=transactions.Transactions.run_lua
    merchant_row=transactions.Transactions.merchant_row
    open_merchant=transactions.Transactions.open_merchant

    def held(self):
        self.open_merchant();self.run_lua(f'BuyMerchantItem({self.merchant_row()})');self.refresh()
        item='native-merchant-first'
        slot=next(n for n,ref in self.presentation.gameplay_views.inventory_refs.items() if ref[1]==item)
        self.run_lua(f'PickupContainerItem(0,{slot})');return item,slot

    def context(self,identity):
        return self.presentation.context_world(identity,self.runtime.world_context,self.runtime.merchant_sell)

    def test_real_vendor_context_sells_same_bundle_once_and_preserves_total_coins(self):
        key,slot=self.held();before=sum([self.runtime._economy_state['wallet']['gold'],self.runtime._economy_state['vendors']['vendor.mira']['gold']])
        self.assertIsNone(self.context('npc-wanderer-01').get('error'))
        self.assertEqual(self.runtime._item_instances[key]['owner_id'],'npc-wanderer-01')
        self.assertEqual(self.runtime._item_instances[key]['quantity'],3)
        self.assertEqual(self.ui.evaluate('return CursorHasItem()'),[False])
        self.assertEqual(sum([self.runtime._economy_state['wallet']['gold'],self.runtime._economy_state['vendors']['vendor.mira']['gold']]),before)
        custody=copy.deepcopy((self.runtime._item_instances,self.runtime._economy_state));self.context('npc-wanderer-01')
        self.assertTrue(custody==(self.runtime._item_instances,self.runtime._economy_state))

    def test_failed_save_wrong_world_pick_and_stale_display_never_drop_dragged_custody(self):
        key,slot=self.held();before=copy.deepcopy((self.runtime._item_instances,self.runtime._economy_state))
        self.assertIn('error',self.context('no-such-person'))
        self.assertEqual(self.ui.evaluate('return CursorHasItem()'),[1])
        with patch.object(self.runtime._state_store,'save',side_effect=OSError('disk full')):
            self.assertIsNotNone(self.context('npc-wanderer-01').get('error'))
        self.assertTrue(before==(self.runtime._item_instances,self.runtime._economy_state));self.assertEqual(self.ui.evaluate('return CursorHasItem()'),[1])
        self.presentation._shown_gameplay.inventory_refs[slot]=('item.wrong','wrong-instance')
        self.assertEqual(self.context('npc-wanderer-01').get('error'),'MERCHANT_CURSOR_SOURCE_CHANGED')
        self.assertTrue(before==(self.runtime._item_instances,self.runtime._economy_state));self.assertEqual(self.ui.evaluate('return CursorHasItem()'),[1])

    def test_split_cursor_sells_only_one_real_unit_and_loaded_splits_never_overwrite_another_owned_instance(self):
        key,slot=self.held();self.run_lua(f'ClearCursor();SplitContainerItem(0,{slot},1)')
        before=copy.deepcopy((self.runtime._item_instances,self.runtime._economy_state))
        with patch.object(self.runtime._state_store,'save',side_effect=OSError('disk full')):
            self.assertEqual(self.context('npc-wanderer-01').get('error'),'VENDOR_SAVE_FAILED')
        self.assertTrue(before==(self.runtime._item_instances,self.runtime._economy_state));self.assertEqual(self.ui.evaluate('return CursorHasItem()'),[1])
        coins=sum([self.runtime._economy_state['wallet']['gold'],self.runtime._economy_state['vendors']['vendor.mira']['gold']])
        self.assertIsNone(self.context('npc-wanderer-01').get('error'))
        self.assertEqual(self.runtime._item_instances[key]['quantity'],2);self.assertEqual(self.runtime._item_instances[key]['owner_id'],'player')
        sold=self.runtime._economy_state['buybacks']['vendor.mira'][-1]['instance_id']
        self.assertEqual(self.runtime._item_instances[sold]['quantity'],1);self.assertNotEqual(sold,key)
        self.assertEqual(self.ui.evaluate('return CursorHasItem()'),[False])
        self.runtime.load_state();self.open_merchant()
        self.assertEqual(self.runtime._item_instances[sold]['quantity'],1)
        slot=next(n for n,ref in self.presentation.gameplay_views.inventory_refs.items() if ref[1]==key)
        self.run_lua(f'SplitContainerItem(0,{slot},1)');self.assertIsNone(self.context('npc-wanderer-01').get('error'))
        second=self.runtime._economy_state['buybacks']['vendor.mira'][-1]['instance_id']
        self.assertNotEqual(second,sold);self.assertEqual(self.runtime._item_instances[sold]['quantity'],1)
        self.assertEqual(self.runtime._item_instances[second]['quantity'],1);self.assertEqual(self.runtime._item_instances[key]['quantity'],1)
        self.assertEqual(sum([self.runtime._economy_state['wallet']['gold'],self.runtime._economy_state['vendors']['vendor.mira']['gold']]),coins)

    def test_sale_buyback_and_both_wallets_survive_restore_with_one_checkpoint_per_affair(self):
        key,slot=self.held();self.run_lua('ClearCursor()')
        with patch.object(self.runtime._state_store,'save',wraps=self.runtime._state_store.save) as save:
            self.assertIsNone(self.runtime.merchant_sell('vendor.mira',key).get('error'))
        self.assertEqual(save.call_count,1)
        expected=copy.deepcopy(self.runtime._economy_state)
        self.runtime.load_state();self.open_merchant()
        for field in ('wallet','vendors','buybacks'):self.assertEqual(self.runtime._economy_state[field],expected[field])
        self.assertEqual(self.runtime._item_instances[key]['owner_id'],'npc-wanderer-01')
        before=copy.deepcopy((self.runtime._item_instances,self.runtime._economy_state,self.runtime._individual_state))
        with patch.object(self.runtime._state_store,'save',side_effect=OSError('disk full')):
            self.assertEqual(self.runtime.merchant_buyback('vendor.mira',key).get('error'),'VENDOR_SAVE_FAILED')
        self.assertTrue(before==(self.runtime._item_instances,self.runtime._economy_state,self.runtime._individual_state))
        with patch.object(self.runtime._state_store,'save',wraps=self.runtime._state_store.save) as save:
            self.assertIsNone(self.runtime.merchant_buyback('vendor.mira',key).get('error'))
        self.assertEqual(save.call_count,1)
        expected=copy.deepcopy(self.runtime._economy_state);self.runtime.load_state()
        for field in ('wallet','vendors','buybacks'):self.assertEqual(self.runtime._economy_state[field],expected[field])
        self.assertEqual(self.runtime._item_instances[key]['owner_id'],'player');self.assertEqual(self.runtime._item_instances[key]['quantity'],3)

    def test_failed_purchase_and_repair_restore_actual_custody_and_successful_repair_saves_gear_and_payment(self):
        self.open_merchant();before=copy.deepcopy((self.runtime._item_instances,self.runtime._economy_state,self.runtime._individual_state))
        with patch.object(self.runtime._state_store,'save',side_effect=OSError('disk full')):
            self.assertEqual(self.runtime.merchant_buy('vendor.mira','native-merchant-first').get('error'),'VENDOR_SAVE_FAILED')
        self.assertTrue(before==(self.runtime._item_instances,self.runtime._economy_state,self.runtime._individual_state))
        worn=next(i for i in self.runtime._item_instances.values() if i.get('owner_id')=='player' and i.get('location')=='EQUIPPED' and i.get('gear'))
        key=worn['instance_id'];worn['condition']=.4
        before=copy.deepcopy((self.runtime._item_instances,self.runtime._economy_state))
        with patch.object(self.runtime._state_store,'save',side_effect=OSError('disk full')):
            self.assertEqual(self.runtime.merchant_repair('vendor.mira',key).get('error'),'VENDOR_SAVE_FAILED')
        self.assertTrue(before==(self.runtime._item_instances,self.runtime._economy_state))
        with patch.object(self.runtime._state_store,'save',wraps=self.runtime._state_store.save) as save:
            self.assertIsNone(self.runtime.merchant_repair('vendor.mira',key).get('error'))
        self.assertEqual(save.call_count,1)
        expected=copy.deepcopy(self.runtime._economy_state);self.runtime.load_state()
        self.assertEqual(self.runtime._item_instances[key]['condition'],1.)
        for field in ('wallet','vendors'):self.assertEqual(self.runtime._economy_state[field],expected[field])


if __name__=='__main__':unittest.main()
