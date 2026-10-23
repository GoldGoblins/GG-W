"""Bound items use vendor custody without becoming transferable to other characters."""
import copy
import unittest
from unittest.mock import patch
import test_game_engine_adapter_merchant as merchant
from backend import game_engine_trade as trade


class VendorBinding(unittest.TestCase):
    setUpClass=classmethod(merchant.Merchant.setUpClass.__func__)
    setUp=merchant.Merchant.setUp
    refresh=merchant.Merchant.refresh

    def owned_bound(self,owner=None):
        result=self.runtime.merchant_buy(self.vendor_id,'merchant-bundle-first')
        self.assertIsNone(result.get('error'))
        row=self.runtime._item_instances['merchant-bundle-first']
        row['bound_to']=owner or self.runtime._persistence_key
        return row

    def test_own_bound_sale_and_buyback_keep_binding_and_save_atomically(self):
        row=self.owned_bound();key=row['instance_id'];binding=row['bound_to']
        valid,reason=trade.validate_offer(row,self.runtime._item_catalog['items'][row['definition_id']],owner_id='player',location='INVENTORY')
        self.assertFalse(valid);self.assertEqual(reason.get('error'),'TRADE_ITEM_BOUND')
        before=copy.deepcopy((self.runtime._item_instances,self.runtime._economy_state))
        with patch.object(self.runtime._state_store,'save',side_effect=OSError('disk full')):
            self.assertEqual(self.runtime.merchant_sell(self.vendor_id,key).get('error'),'VENDOR_SAVE_FAILED')
        self.assertTrue(before==(self.runtime._item_instances,self.runtime._economy_state),'failed bound sale changed custody')
        self.assertIsNone(self.runtime.merchant_sell(self.vendor_id,key).get('error'))
        self.assertEqual(self.runtime._item_instances[key]['bound_to'],binding)
        self.runtime.load_state();self.assertIsNone(self.runtime.open_merchant(self.vendor_id).get('error'))
        self.assertEqual(self.runtime._item_instances[key]['owner_id'],self.npc_id)
        self.assertIsNone(self.runtime.merchant_buyback(self.vendor_id,key).get('error'))
        self.assertEqual(self.runtime._item_instances[key]['bound_to'],binding)
        self.assertEqual(self.runtime._item_instances[key]['owner_id'],'player')
        self.assertEqual(self.runtime._item_instances[key]['quantity'],3)
        self.runtime.load_state();self.assertEqual(self.runtime._item_instances[key]['bound_to'],binding)

    def test_foreign_binding_blocks_both_buy_and_sell_without_moving_items_or_coins(self):
        row=self.owned_bound('foreign-local-character')
        stock=self.runtime._item_instances['merchant-bundle-second'];stock['bound_to']='foreign-local-character'
        before=copy.deepcopy((self.runtime._item_instances,self.runtime._economy_state))
        self.assertEqual(self.runtime.merchant_sell(self.vendor_id,row['instance_id']).get('error'),'ITEM_BOUND_TO_ANOTHER_CHARACTER')
        self.assertEqual(self.runtime.merchant_buy(self.vendor_id,stock['instance_id']).get('error'),'ITEM_BOUND_TO_ANOTHER_CHARACTER')
        self.assertTrue(before==(self.runtime._item_instances,self.runtime._economy_state),'foreign binding changed vendor custody')
