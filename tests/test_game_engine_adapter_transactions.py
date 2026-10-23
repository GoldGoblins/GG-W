"""Original Lua bank/vendor verbs through Presentation and real isolated GG state."""

import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QGuiApplication
from backend import game_engine_items as items
from backend import game_engine_mmo as mmo
from backend.game_engine_presentation import Presentation

APP = QGuiApplication.instance() or QGuiApplication([])


class Bridge(QObject):
    snapshotPublished = Signal(object)

    def __init__(self, runtime):
        super().__init__()
        self.runtime = runtime
        self.calls = []

    def perform(self, name, method, *args):
        self.calls.append((name, args))
        # Match the actual Qt host's JSON return path, including its snapshots.
        return json.dumps(method(*args))

    def gameEngineBankDepositAt(self, instance, slot):
        return self.perform("bank_deposit", self.runtime.deposit_to_stash, instance, slot)

    def gameEngineBankWithdrawAt(self, instance, slot):
        return self.perform("bank_withdraw", self.runtime.withdraw_from_stash, instance, slot)

    def gameEngineBankMove(self, instance, slot):
        return self.perform("bank_move", self.runtime.move_stash_slot, instance, slot)

    def gameEngineBankClose(self):
        return self.perform("bank_close", self.runtime.close_bank)

    def gameEngineMerchantBuy(self, vendor, instance):
        return self.perform("merchant_buy", self.runtime.merchant_buy, vendor, instance)

    def gameEngineMerchantSell(self, vendor, instance):
        return self.perform("merchant_sell", self.runtime.merchant_sell, vendor, instance)

    def gameEngineMerchantSellCount(self, vendor, instance, quantity):
        return self.perform('merchant_sell_count', self.runtime.merchant_sell, vendor, instance, quantity)

    def gameEngineMerchantBuyAt(self,vendor,instance,slot):
        return self.perform('merchant_buy_at',self.runtime.merchant_buy_at,vendor,instance,slot)

    def gameEngineMerchantBuyback(self,vendor,instance):
        return self.perform('merchant_buyback',self.runtime.merchant_buyback,vendor,instance)

    def gameEngineMerchantRepair(self,vendor,instance):
        return self.perform('merchant_repair',self.runtime.merchant_repair,vendor,instance)

    def gameEngineMerchantClose(self):
        return self.perform("merchant_close", self.runtime.close_merchant)

    def gameEngineContainerUseItem(self, definition, instance):
        return self.perform("normal_item_use", self.runtime.action_use_item, definition, instance)

    def gameEngineInventoryMove(self, instance, slot):
        return self.perform("inventory_move", self.runtime.move_inventory_slot, instance, slot)

    def gameEngineItemEquip(self, instance, slot):
        return self.perform("item_equip", self.runtime.equip_item, instance, slot)

    def gameEngineEquipmentMove(self, instance, slot):
        return self.perform("equipment_move", self.runtime.move_equipment_to_inventory, instance, slot)


class Transactions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The host's module-level runtime must also avoid the user's chest.
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(mmo, "DEFAULT_STASH_PATH", Path(directory) / "unused.json"):
                from backend.game_engine_host import GameEngineRuntime
                cls.Runtime = GameEngineRuntime

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        env = patch.dict(os.environ, {"XDG_STATE_HOME": directory.name})
        env.start()
        self.addCleanup(env.stop)
        with patch.object(mmo, "DEFAULT_STASH_PATH", Path(directory.name) / "account-stash.json"):
            self.runtime = self.Runtime()
        self.addCleanup(self.runtime.shutdown)
        with self.runtime._lock:
            self.food = next(ref for ref, definition in self.runtime._item_catalog["items"].items()
                             if definition.get("kind") == "CONSUMABLE"
                             and definition.get("stack_limit", 1) >= 7)
            for name, slot, quantity in (("native-bank-food-first", 60, 3),
                                         ("native-bank-food-second", 61, 7)):
                item = items.make_instance(self.runtime._item_catalog, name, self.food, quantity=quantity)
                item["slot_index"] = slot
                self.runtime._item_instances[name] = item
            self.runtime._inventory = items.inventory_counts(self.runtime._item_instances.values())
            self.crate = next(row["instance_id"] for row in self.runtime._item_instances.values()
                              if row.get("definition_id") == "container.supply_crate")
            self.npc = next(index for index in self.runtime._npc_indices
                            if self.runtime._npc_ids[index] == "npc-wanderer-01")
            person = self.runtime._individual_state["individuals"]["npc-wanderer-01"]
            for name, quantity in (("native-merchant-first", 3), ("native-merchant-second", 7)):
                self.runtime._item_instances[name] = items.make_instance(
                    self.runtime._item_catalog, name, "item.sea_salt", quantity=quantity,
                    owner_id="npc-wanderer-01", location="POCKET")
                person["inventory"].append("item.sea_salt")
        self.bridge = Bridge(self.runtime)
        self.presentation = Presentation(self.bridge, device=False)
        self.addCleanup(self.presentation.close)
        self.assertTrue(self.presentation.full_ui)
        self.assertIsNotNone(self.presentation.lua)
        self.ui = self.presentation.lua
        self.ui.execute("""
            txBankShown=0 txBankClosed=0 txBankUpdated=0 txBankSlots=0
            txMerchantShown=0 txMerchantClosed=0 txMerchantUpdated=0 txRefusals=0
            txBankExpectedSlot=nil txBankExpectedCount=nil txLastError=nil txBankSources=''
            txEvents=CreateFrame('Frame')
            for _,e in ipairs({'BANKFRAME_OPENED','BANKFRAME_CLOSED','BAG_UPDATE',
                'PLAYERBANKSLOTS_CHANGED','MERCHANT_SHOW','MERCHANT_CLOSED',
                'MERCHANT_UPDATE','UI_ERROR_MESSAGE'}) do txEvents:RegisterEvent(e) end
            txEvents:SetScript('OnEvent',function()
                if event=='BANKFRAME_OPENED' then
                    assert(GetContainerNumSlots(-1)==48)
                    assert(GetBagName(-1)=='GG shared chest')
                    if txBankExpectedSlot then
                        local icon,count=GetContainerItemInfo(-1,txBankExpectedSlot)
                        assert(icon and count==txBankExpectedCount)
                    end
                    txBankShown=txBankShown+1
                elseif event=='BANKFRAME_CLOSED' then
                    assert(GetContainerNumSlots(-1)==0)
                    txBankClosed=txBankClosed+1
                elseif event=='BAG_UPDATE' and arg1==-1 then
                    txBankUpdated=txBankUpdated+1
                elseif event=='PLAYERBANKSLOTS_CHANGED' then
                    txBankSlots=txBankSlots+1
                    txBankSources=txBankSources..'['..tostring(arg1)..']'
                elseif event=='MERCHANT_SHOW' then
                    assert(GetMerchantNumItems()>0)
                    local name,icon,price,quantity,stock=GetMerchantItemInfo(1)
                    assert(name and icon and price>0 and quantity>0 and stock==1)
                    txMerchantShown=txMerchantShown+1
                elseif event=='MERCHANT_CLOSED' then
                    assert(GetMerchantNumItems()==0)
                    txMerchantClosed=txMerchantClosed+1
                elseif event=='MERCHANT_UPDATE' then
                    txMerchantUpdated=txMerchantUpdated+1
                elseif event=='UI_ERROR_MESSAGE' then
                    txRefusals=txRefusals+1 txLastError=arg1
                end
            end)
        """)
        self.refresh()

    def refresh(self):
        self.presentation.last_update = 0
        self.presentation.update(self.runtime.snapshot())

    def run_lua(self, source):
        self.ui.execute(source)
        requests = self.ui.request("requests")
        self.presentation._game_requests(requests)
        return requests

    def open_bank(self):
        with self.runtime._lock:
            crate = self.runtime._item_instances[self.crate]
            self.runtime._x[0] = crate["position"]["x"]
            self.runtime._z[0] = crate["position"]["z"]
        result = self.runtime.open_container(self.crate)
        self.assertNotIn("error", result)
        self.refresh()

    def open_merchant(self):
        with self.runtime._lock:
            self.runtime._x[0] = self.runtime._x[self.npc]
            self.runtime._z[0] = self.runtime._z[self.npc]
        result = self.runtime.open_merchant("vendor.mira")
        self.assertNotIn("error", result)
        self.refresh()

    def merchant_row(self, instance="native-merchant-first"):
        return next(row for row, (_, ref) in self.presentation.gameplay_views.merchant.buy_refs.items()
                    if ref == instance)

    def check_clean(self, *, unsupported=False):
        self.assertFalse(self.presentation.errors, self.presentation.errors)
        self.assertFalse(self.ui.errors, self.ui.errors)
        if not unsupported:
            self.assertFalse(self.presentation.unsupported_requests,
                             self.presentation.unsupported_requests)

    def test_bank_lua_cursor_roundtrip_slot48_and_stable_events(self):
        self.open_bank()
        self.assertEqual(self.ui.evaluate("local n,full=GetNumBankSlots() return txBankShown,GetContainerNumSlots(-1),n,full,GetBankSlotCost(0)"),
                         [1, 48, 0, None, 0])
        counts = self.ui.evaluate("return txBankShown,txBankUpdated,txBankSlots")
        self.refresh()
        self.assertEqual(self.ui.evaluate("return txBankShown,txBankUpdated,txBankSlots"), counts)
        requests = self.run_lua("PickupContainerItem(0,61) PickupContainerItem(-1,48)")
        self.assertEqual(len(requests["item_moves"]), 1)
        self.assertNotIn("native-bank-food-first", self.runtime._item_instances)
        self.assertEqual(self.runtime._item_instances["native-bank-food-second"]["quantity"], 7)
        self.refresh()
        bank_instance = self.presentation.gameplay_views.bank.bank_refs[48][1]
        self.assertEqual(self.ui.evaluate("local icon,n=GetContainerItemInfo(-1,48) return icon~=nil,n"),
                         [True, 3])
        self.run_lua("PickupContainerItem(-1,48) PickupContainerItem(0,64)")
        self.assertEqual(self.runtime._item_instances[bank_instance]["slot_index"], 63)
        self.assertEqual(self.runtime._item_instances[bank_instance]["quantity"], 3)
        self.refresh()
        self.assertEqual(self.ui.evaluate("return GetContainerItemInfo(-1,48)==nil,txBankShown"), [True, 1])
        self.check_clean()

    def test_stock_bank_inventory_band_and_show_handler_see_real_data(self):
        self.open_bank()
        self.runtime.deposit_to_stash("native-bank-food-first", 2)
        self.runtime.close_bank()
        self.refresh()
        self.ui.execute("txBankExpectedSlot=3 txBankExpectedCount=3")
        self.open_bank()
        actual = self.runtime.snapshot()["bank"]["items"][0]
        self.assertEqual(self.ui.evaluate("return BankButtonIDToInvSlotID(3),GetInventoryItemCount('player',42),GetInventoryItemTexture('player',42)"),
                         [42, 3, actual["icon"]])
        self.assertEqual(self.ui.evaluate("return GetInventoryItemQuality('player',42),GetInventoryItemLink('player',42)~=nil"),
                         [self.presentation.gameplay_views.bank.update(self.runtime.snapshot())["items"][0]["quality"], True])
        self.assertEqual(self.ui.evaluate("return GetInventoryItemTexture('player',43)==nil,txBankShown,txBankClosed"),
                         [True, 2, 1])
        # Feeding a bank copy must preserve the actual template's stack size,
        # including the independently owned backpack copy of that template.
        item_id = self.presentation.gameplay_views.identity(self.food)
        self.assertEqual(self.ui.evaluate(f"local _,_,_,_,_,_,limit,_,icon=GetItemInfo({item_id}) return limit,icon"),
                         [actual["stack_limit"], actual["icon"]])
        self.check_clean()

    def test_bank_right_click_does_not_consume_and_close_does_not_reopen_nearby(self):
        self.open_bank()
        self.run_lua("UseContainerItem(0,61)")
        bank = self.runtime.snapshot()["bank"]
        self.assertEqual(len(bank["items"]), 1)
        self.assertEqual(bank["items"][0]["quantity"], 3)
        self.assertFalse(any(name == "normal_item_use" for name, _ in self.bridge.calls))
        self.refresh()
        slot = next(iter(self.presentation.gameplay_views.bank.bank_refs))
        self.run_lua(f"UseContainerItem(-1,{slot})")
        self.assertEqual(self.runtime._item_instances[bank["items"][0]["instance_id"]]["quantity"], 3)
        self.refresh()
        self.run_lua("CloseBankFrame()")
        self.assertFalse(self.runtime.snapshot()["bank"]["accessible"])
        self.assertTrue(self.runtime.snapshot()["bank"]["nearby"])
        self.refresh()
        counts = self.ui.evaluate("return txBankShown,txBankClosed,txBankUpdated,txBankSlots")
        self.refresh()
        self.assertEqual(self.ui.evaluate("return txBankShown,txBankClosed,txBankUpdated,txBankSlots"), counts)
        self.assertEqual(self.ui.evaluate("return GetContainerNumSlots(-1),txBankClosed"), [0, 1])
        self.check_clean()

    def test_two_native_drops_in_one_drain_do_not_relocate_the_first_stack(self):
        self.open_bank()
        requests = self.run_lua("""
            PickupContainerItem(0,61) PickupContainerItem(-1,48) ClearCursor()
            PickupContainerItem(0,62) PickupContainerItem(-1,48)
        """)
        self.assertEqual(len(requests["item_moves"]), 2)
        snapshot = self.runtime.snapshot()
        self.assertEqual([(row["slot_index"], row["quantity"]) for row in snapshot["bank"]["items"]], [(47, 3)])
        self.assertEqual(self.runtime._item_instances["native-bank-food-second"]["location"], "INVENTORY")
        self.assertEqual(self.runtime._item_instances["native-bank-food-second"]["slot_index"], 61)
        self.assertEqual(sum(name == "bank_deposit" for name, _ in self.bridge.calls), 1)
        self.assertIn("cross-container swaps", self.ui.evaluate("return txLastError")[0])
        self.check_clean(unsupported=True)

    def test_original_bank_slot_events_distinguish_identity_fields_and_identical_swaps(self):
        self.open_bank()
        # Original ui_items/feed.rs: a vault never emits BAG_UPDATE. An
        # exact source changing fires no arg; same-source field changes use
        # arg1='player'. Unchanged cells produce no events.
        self.assertEqual(self.ui.evaluate("return txBankUpdated,txBankSlots,txBankSources"), [0, 0, ""])
        self.runtime.deposit_to_stash("native-bank-food-first", 2)
        self.refresh()
        self.assertEqual(self.ui.evaluate("return txBankUpdated,txBankSlots,txBankSources"), [0, 1, "[nil]"])
        first = self.presentation.gameplay_views.bank.bank_refs[3][1]
        with self.runtime._lock:
            self.runtime._stash_state["items"][0]["condition"] = .5
        self.refresh()
        self.assertEqual(self.ui.evaluate("return txBankSources"), ["[nil][player]"])
        # Restore the same appearance, then give the independent second
        # source the same stack size to exercise a visually identical swap.
        with self.runtime._lock:
            self.runtime._stash_state["items"][0]["condition"] = 1
            self.runtime._item_instances["native-bank-food-second"]["quantity"] = 3
            self.runtime._inventory = items.inventory_counts(self.runtime._item_instances.values())
        self.refresh()
        self.runtime.deposit_to_stash("native-bank-food-second", 3)
        self.refresh()
        before = self.ui.evaluate("return txBankSources")[0]
        self.runtime.move_stash_slot(first, 3)
        self.refresh()
        self.assertEqual(self.ui.evaluate("return txBankUpdated,txBankSources"), [0, before + "[nil][nil]"])
        stable = self.ui.evaluate("return txBankSlots,txBankSources")
        with self.runtime._lock:
            self.runtime._stash_state["revision"] += 1
        self.refresh()
        self.assertEqual(self.ui.evaluate("return txBankSlots,txBankSources"), stable)
        self.check_clean()

    def test_merchant_real_getters_buy_and_use_sale_preserve_money(self):
        self.open_merchant()
        row = self.merchant_row()
        projected = self.presentation.gameplay_views.merchant.update(self.runtime.snapshot())["items"][row - 1]
        result = self.ui.evaluate(f"local name,icon,p,q,s,u=GetMerchantItemInfo({row}) return name,icon,p,q,s,u")
        self.assertEqual(result[:5], [projected["name"], projected["texture"], projected["price"], 3, 1])
        self.assertEqual(result[5],1,'An unrestricted GG item was incorrectly marked unusable')
        self.assertEqual(self.ui.evaluate(f"return GetMerchantItemLink({row})~=nil,GetMerchantItemMaxStack({row}),GetNumBuybackItems(),CanMerchantRepair()"),
                         [True, 1, 0, 1])
        stable = self.ui.evaluate("return txMerchantShown,txMerchantUpdated")
        self.refresh()
        self.assertEqual(self.ui.evaluate("return txMerchantShown,txMerchantUpdated"), stable)
        total = self.runtime._economy_state["wallet"]["gold"] + self.runtime._economy_state["vendors"]["vendor.mira"]["gold"]
        self.run_lua(f"BuyMerchantItem({row},1)")
        self.assertEqual(self.runtime._item_instances["native-merchant-first"]["owner_id"], "player")
        self.assertEqual(self.runtime._item_instances["native-merchant-first"]["quantity"], 3)
        self.assertEqual(self.runtime._item_instances["native-merchant-second"]["quantity"], 7)
        self.refresh()
        slot = next(slot for slot, (_, instance) in self.presentation.gameplay_views.inventory_refs.items()
                    if instance == "native-merchant-first")
        self.run_lua(f"UseContainerItem(0,{slot})")
        self.assertEqual(self.runtime._item_instances["native-merchant-first"]["owner_id"], "npc-wanderer-01")
        self.assertEqual(self.runtime._item_instances["native-merchant-first"]["quantity"], 3)
        self.assertFalse(any(name == "normal_item_use" for name, _ in self.bridge.calls))
        self.assertEqual(self.runtime._economy_state["wallet"]["gold"] + self.runtime._economy_state["vendors"]["vendor.mira"]["gold"], total)
        self.refresh()
        self.assertEqual(self.ui.evaluate("return txMerchantShown,txMerchantUpdated>0"), [1, True])
        self.check_clean()

    def test_original_split_merchant_sale_rolls_back_then_sells_exact_count_and_restores_custody(self):
        self.open_merchant();self.run_lua(f'BuyMerchantItem({self.merchant_row()})');self.refresh()
        key='native-merchant-first'
        slot=next(n for n,ref in self.presentation.gameplay_views.inventory_refs.items() if ref[1]==key)
        before=copy.deepcopy((self.runtime._item_instances,self.runtime._economy_state))
        with patch.object(self.runtime._state_store,'save',side_effect=OSError('disk full')):
            requests=self.run_lua(f'SplitContainerItem(0,{slot},2);PickupMerchantItem(0)')
        self.assertEqual(requests['merchant_sale_counts'],[[0,slot,2]])
        self.assertTrue(before==(self.runtime._item_instances,self.runtime._economy_state),'failed save changed merchant custody')
        self.assertEqual(self.ui.request('cursor_source'),dict(kind='item',bag=0,slot=slot,count=2))
        with patch.object(self.runtime._state_store,'save',wraps=self.runtime._state_store.save) as save:
            self.run_lua('PickupMerchantItem(0)')
        self.assertEqual(save.call_count,1)
        sold=self.runtime._economy_state['buybacks']['vendor.mira'][-1]['instance_id']
        self.assertNotEqual(sold,key);self.assertEqual(self.runtime._item_instances[key]['quantity'],1)
        self.assertEqual(self.runtime._item_instances[sold]['quantity'],2)
        self.assertEqual(self.runtime._item_instances[sold]['owner_id'],'npc-wanderer-01')
        self.assertEqual(self.ui.evaluate('return CursorHasItem()'),[False])
        self.assertEqual(self.ui.request('requests')['merchant_sale_counts'],[])
        self.runtime.load_state()
        self.assertEqual(self.runtime._item_instances[key]['quantity'],1);self.assertEqual(self.runtime._item_instances[sold]['quantity'],2)
        self.assertEqual(self.runtime._economy_state['buybacks']['vendor.mira'][-1]['instance_id'],sold)

    def test_repeated_split_sales_cannot_restore_more_than_the_actual_remaining_stack(self):
        self.open_merchant();self.run_lua(f'BuyMerchantItem({self.merchant_row()})');self.refresh()
        key='native-merchant-first'
        slot=next(n for n,ref in self.presentation.gameplay_views.inventory_refs.items() if ref[1]==key)
        self.run_lua(f'SplitContainerItem(0,{slot},2);PickupMerchantItem(0);SplitContainerItem(0,{slot},2);PickupMerchantItem(0)')
        self.assertEqual(self.runtime._item_instances[key]['quantity'],1)
        rows=self.runtime._economy_state['buybacks']['vendor.mira'];self.assertEqual(len(rows),1)
        self.assertEqual(self.runtime._item_instances[rows[0]['instance_id']]['quantity'],2)
        self.assertEqual(self.ui.evaluate('return CursorHasItem()'),[False])

    def test_failed_original_merchant_sale_does_not_overwrite_a_newer_item_cursor(self):
        self.open_merchant();self.run_lua(f'BuyMerchantItem({self.merchant_row()})');self.refresh()
        key='native-merchant-first'
        slot=next(n for n,ref in self.presentation.gameplay_views.inventory_refs.items() if ref[1]==key)
        before=copy.deepcopy((self.runtime._item_instances,self.runtime._economy_state))
        with patch.object(self.runtime._state_store,'save',side_effect=OSError('disk full')):
            self.run_lua(f'SplitContainerItem(0,{slot},2);PickupMerchantItem(0);PickupContainerItem(0,62)')
        self.assertTrue(before==(self.runtime._item_instances,self.runtime._economy_state),'failed sale changed owned items')
        self.assertEqual(self.ui.request('cursor_source'),dict(kind='item',bag=0,slot=62,count=None))
        self.assertEqual(self.ui.request('requests')['merchant_sale_counts'],[])

    def test_original_merchant_cursor_sale_and_close_are_authoritative(self):
        self.open_merchant()
        row = self.merchant_row()
        self.run_lua(f"BuyMerchantItem({row})")
        self.refresh()
        slot = next(slot for slot, (_, instance) in self.presentation.gameplay_views.inventory_refs.items()
                    if instance == "native-merchant-first")
        requests = self.run_lua(f"PickupContainerItem(0,{slot}) PickupMerchantItem(0)")
        self.assertEqual(requests["merchant_sells"], [[0, slot]])
        self.assertEqual(self.runtime._item_instances["native-merchant-first"]["owner_id"], "npc-wanderer-01")
        self.refresh()
        row = self.merchant_row()
        self.ui.execute(f"BuyMerchantItem({row})")
        stale = self.ui.request("requests")
        self.run_lua("CloseMerchant()")
        before = copy.deepcopy(self.runtime._economy_state)
        self.presentation._game_requests(stale)
        self.assertEqual(self.runtime._economy_state, before)
        self.assertEqual(self.runtime._item_instances["native-merchant-first"]["owner_id"], "npc-wanderer-01")
        self.refresh()
        self.assertEqual(self.ui.evaluate("return GetMerchantNumItems(),txMerchantClosed"), [0, 1])
        stable = self.ui.evaluate("return txMerchantShown,txMerchantClosed,txMerchantUpdated")
        self.refresh()
        self.assertEqual(self.ui.evaluate("return txMerchantShown,txMerchantClosed,txMerchantUpdated"), stable)
        self.assertTrue(next(v for v in self.runtime.snapshot()["economy"]["vendors"] if v["id"] == "vendor.mira")["presence"]["available"])
        self.check_clean(unsupported=True)

    def test_insufficient_identical_bundles_refused_but_cursor_purchase_uses_chosen_slot(self):
        self.open_merchant()
        row = self.merchant_row()
        before_money = copy.deepcopy(self.runtime._economy_state)
        before_item = copy.deepcopy(self.runtime._item_instances["native-merchant-first"])
        self.run_lua(f"BuyMerchantItem({row},2)")
        self.assertEqual(self.runtime._economy_state,before_money)
        self.assertEqual(self.runtime._item_instances['native-merchant-first'],before_item)
        requests = self.run_lua(f"PickupMerchantItem({row}) PickupContainerItem(0,64)")
        self.assertEqual(len(requests["merchant_slot_buys"]), 1)
        item=self.runtime._item_instances['native-merchant-first']
        self.assertEqual((item['owner_id'],item['location'],item['slot_index']),('player','INVENTORY',63))
        self.assertLess(self.runtime._economy_state['wallet']['gold'],before_money['wallet']['gold'])
        self.assertFalse(any(name == "merchant_buy" for name, _ in self.bridge.calls))
        self.assertTrue(any("insufficient identical physical bundles" in error for error in self.presentation.unsupported_requests))
        self.check_clean(unsupported=True)

    def test_cursor_purchases_distinguish_two_same_template_physical_bundles(self):
        self.open_merchant();first=self.merchant_row();second=self.merchant_row('native-merchant-second')
        entries=self.presentation.gameplay_views.merchant.entry_refs
        self.assertEqual(len(entries),len(self.presentation.gameplay_views.merchant.buy_refs))
        self.run_lua(f'PickupMerchantItem({second}) PickupContainerItem(0,64)')
        self.assertEqual(self.runtime._item_instances['native-merchant-second']['quantity'],7)
        self.assertEqual(self.runtime._item_instances['native-merchant-second']['slot_index'],63)
        self.assertEqual(self.runtime._item_instances['native-merchant-first']['owner_id'],'npc-wanderer-01')
        self.check_clean()

    def test_cursor_purchase_cannot_overwrite_occupied_slot_or_reuse_stock(self):
        self.open_merchant();row=self.merchant_row();before=copy.deepcopy(self.runtime._economy_state)
        request=self.run_lua(f'PickupMerchantItem({row}) PickupContainerItem(0,61)')
        self.assertEqual(len(request['merchant_slot_buys']),1)
        self.assertEqual(self.runtime._economy_state,before)
        self.assertEqual(self.runtime._item_instances['native-bank-food-first']['quantity'],3)
        self.assertIn('OCCUPIED',self.ui.evaluate('return txLastError')[0])
        self.assertEqual(self.runtime._item_instances['native-merchant-first']['location'],'POCKET')
        self.check_clean()

    def test_lua_buyback_preserves_the_exact_stack_and_original_sale_price(self):
        self.open_merchant();row=self.merchant_row();self.run_lua(f'BuyMerchantItem({row})');self.refresh()
        instance='native-merchant-first';slot=next(slot for slot,pair in self.presentation.gameplay_views.inventory_refs.items() if pair[1]==instance)
        before=self.runtime._economy_state['wallet']['gold'];self.run_lua(f'UseContainerItem(0,{slot})');self.refresh()
        self.assertEqual(self.ui.evaluate('return GetNumBuybackItems()'),[1])
        sale=self.runtime._economy_state['buybacks']['vendor.mira'][0]
        self.assertEqual(self.runtime._economy_state['wallet']['gold'],before+sale['price'])
        self.run_lua('BuybackItem(1)');self.refresh()
        self.assertEqual(self.runtime._economy_state['wallet']['gold'],before)
        self.assertEqual(self.runtime._item_instances[instance]['quantity'],3)
        self.assertEqual(self.runtime._item_instances[instance]['location'],'INVENTORY')
        self.assertEqual(self.ui.evaluate('return GetNumBuybackItems()'),[0])
        self.check_clean()

    def test_repair_all_and_cursor_repair_charge_gold_and_do_not_sell_items(self):
        self.open_merchant()
        gear=next(row for row in self.runtime._item_instances.values() if row.get('owner_id')=='player' and row.get('location') in ('INVENTORY','EQUIPPED') and isinstance(row.get('gear'),dict))
        gear['condition']=.25;self.refresh()
        gold=self.runtime._economy_state['wallet']['gold'];cost=self.runtime._merchant_view_locked()['repair_gold']
        self.assertGreater(cost,0);self.assertEqual(self.ui.evaluate('return GetRepairAllCost()'),[cost*10000,True])
        self.run_lua('RepairAllItems()');self.refresh()
        self.assertEqual(gear['condition'],1.);self.assertEqual(self.runtime._economy_state['wallet']['gold'],gold-cost)
        gear['condition']=.6;self.refresh();equipment_slot=next(slot for slot,instance in self.presentation.gameplay_views.equipment_refs.items() if instance==gear['instance_id'])
        self.run_lua(f'ShowRepairCursor() UseInventoryItem({equipment_slot}) HideRepairCursor()');self.refresh()
        self.assertEqual(gear['condition'],1.);self.assertEqual(gear['location'],'EQUIPPED')
        self.assertNotIn('error',self.runtime.unequip_item(gear['instance_id']));self.refresh();owned=gear
        owned['condition']=.5;self.refresh();slot=next(slot for slot,pair in self.presentation.gameplay_views.inventory_refs.items() if pair[1]==owned['instance_id'])
        self.run_lua(f'ShowRepairCursor() UseContainerItem(0,{slot}) HideRepairCursor()');self.refresh()
        self.assertEqual(owned['condition'],1.);self.assertEqual(owned['location'],'INVENTORY')
        self.assertEqual(owned['owner_id'],'player');self.assertFalse(any(name=='merchant_sell' for name,_ in self.bridge.calls))
        self.check_clean()

    def test_insufficient_repair_money_and_stale_buyback_reach_leave_state_unchanged(self):
        self.open_merchant();gear=next(row for row in self.runtime._item_instances.values() if row.get('owner_id')=='player' and isinstance(row.get('gear'),dict))
        gear['condition']=.1;self.runtime._economy_state['wallet']['gold']=0;self.refresh();before=copy.deepcopy(self.runtime._economy_state)
        self.run_lua('RepairAllItems()');self.assertEqual(gear['condition'],.1);self.assertEqual(self.runtime._economy_state,before)
        self.runtime._x[0]+=1000
        self.assertIn('error',self.runtime.merchant_repair('vendor.mira',''))
        self.assertIn('error',self.runtime.merchant_buyback('vendor.mira','native-merchant-first'))
        self.check_clean()

    def test_repeated_shown_merchant_row_does_not_buy_a_different_physical_bundle(self):
        self.open_merchant()
        row = self.merchant_row()
        price = self.presentation.gameplay_views.merchant.update(self.runtime.snapshot())["items"][row - 1]["price"] // 10000
        before = self.runtime._economy_state["wallet"]["gold"]
        requests = self.run_lua(f"BuyMerchantItem({row}) BuyMerchantItem({row})")
        self.assertEqual(len(requests["merchant_buys"]), 2)
        self.assertEqual(self.runtime._item_instances["native-merchant-first"]["owner_id"], "player")
        self.assertEqual(self.runtime._item_instances["native-merchant-second"]["owner_id"], "npc-wanderer-01")
        self.assertEqual(self.runtime._item_instances["native-merchant-second"]["quantity"], 7)
        self.assertEqual(self.runtime._economy_state["wallet"]["gold"], before - price)
        self.check_clean(unsupported=True)

    def test_queued_click_keeps_its_exact_product_across_new_snapshot_publication(self):
        self.open_merchant()
        row = self.merchant_row()
        self.ui.execute(f"BuyMerchantItem({row})")
        # An independent authoritative action changes physical stock while
        # the original Lua click is pending, before Presentation publishes
        # its next frame. The pending row still means the old exact product.
        bought = self.runtime.merchant_buy("vendor.mira", "native-merchant-first")
        self.assertNotIn("error", bought)
        before = copy.deepcopy(self.runtime._economy_state)
        self.refresh()
        self.assertEqual(self.runtime._item_instances["native-merchant-second"]["owner_id"], "npc-wanderer-01")
        self.assertEqual(self.runtime._item_instances["native-merchant-second"]["quantity"], 7)
        self.assertEqual(self.runtime._economy_state, before)
        self.check_clean(unsupported=True)

    def test_later_drain_before_repaint_still_buys_the_original_visible_row(self):
        self.open_merchant()
        row = self.merchant_row()
        self.run_lua(f"BuyMerchantItem({row})")
        self.assertEqual(self.runtime._item_instances["native-merchant-first"]["owner_id"], "player")
        # A successful transaction refreshed eligibility, but the original
        # native widget still displays the old row until the next publish.
        before = copy.deepcopy(self.runtime._economy_state)
        self.run_lua(f"BuyMerchantItem({row})")
        self.assertEqual(self.runtime._item_instances["native-merchant-second"]["owner_id"], "npc-wanderer-01")
        self.assertEqual(self.runtime._economy_state, before)
        self.check_clean(unsupported=True)

    def test_native_queued_purchase_rechecks_current_reach(self):
        self.open_merchant()
        row = self.merchant_row()
        self.ui.execute(f"BuyMerchantItem({row})")
        pending = self.ui.request("requests")
        money = copy.deepcopy(self.runtime._economy_state)
        before = copy.deepcopy(self.runtime._item_instances["native-merchant-first"])
        with self.runtime._lock:
            self.runtime._x[0] += 100
        self.presentation._game_requests(pending)
        self.assertEqual(self.runtime._economy_state, money)
        self.assertEqual(self.runtime._item_instances["native-merchant-first"], before)
        self.assertEqual(self.ui.evaluate("return txLastError"), ["MERCHANT_SESSION_REQUIRED"])
        self.refresh()
        self.assertEqual(self.ui.evaluate("return GetMerchantNumItems(),txMerchantClosed"), [0, 1])
        self.check_clean()

    def test_queued_inventory_drag_and_autoequip_reject_replaced_slot_sources(self):
        first, replacement = "native-queued-sword-first", "native-queued-sword-replacement"
        with self.runtime._lock:
            for name, slot in ((first, 58), (replacement, 59)):
                row = items.make_instance(self.runtime._item_catalog, name, "item.weapon_sword")
                row["slot_index"] = slot
                self.runtime._item_instances[name] = row
            self.runtime._inventory = items.inventory_counts(self.runtime._item_instances.values())
        for mode in ("move", "autoequip"):
            with self.subTest(mode=mode):
                with self.runtime._lock:
                    self.runtime._item_instances[first]["slot_index"] = 58
                    self.runtime._item_instances[replacement]["slot_index"] = 59
                self.refresh()
                if mode == "move":
                    self.ui.execute("PickupContainerItem(0,59) PickupContainerItem(0,64)")
                else:
                    self.ui.execute("PickupContainerItem(0,59) assert(AutoEquipCursorItem())")
                swapped = self.runtime.move_inventory_slot(first, 59)
                self.assertNotIn("error", swapped)
                source_before = copy.deepcopy(self.runtime._item_instances[first])
                replacement_before = copy.deepcopy(self.runtime._item_instances[replacement])
                calls_before = len(self.bridge.calls)
                self.refresh()
                self.assertEqual(self.runtime._item_instances[first], source_before)
                self.assertEqual(self.runtime._item_instances[replacement], replacement_before)
                self.assertFalse(any(name in ("inventory_move", "item_equip")
                                     for name, _ in self.bridge.calls[calls_before:]))
                self.assertIn("source changed", self.ui.evaluate("return txLastError")[0])
        self.check_clean(unsupported=True)

    def test_qobject_snapshot_signals_during_multiple_buys_cannot_reenter_or_rebind(self):
        self.open_merchant()
        row = self.merchant_row()
        visible_id = self.presentation._shown_gameplay.merchant.buy_refs[row][1]
        baseline_updates = self.presentation.updates
        baseline_shows = self.ui.evaluate("return txMerchantShown,txMerchantUpdated")
        observations = []
        depth = 0
        maximum_depth = 0
        original = self.bridge.gameEngineMerchantBuy

        def nested_publish(snapshot):
            # Bypass the cadence gate so the drain guard itself must protect
            # the original displayed bindings from this direct Qt callback.
            self.presentation.last_update = 0
            self.presentation.update(snapshot)
            observations.append((self.presentation.updates,
                                 self.presentation._shown_gameplay.merchant.buy_refs[row][1]))

        def reentrant_buy(vendor, instance):
            nonlocal depth, maximum_depth
            depth += 1
            maximum_depth = max(maximum_depth, depth)
            try:
                result = original(vendor, instance)
                self.bridge.snapshotPublished.emit(self.runtime.snapshot())
                return result
            finally:
                depth -= 1

        self.bridge.snapshotPublished.connect(nested_publish)
        with patch.object(self.bridge, "gameEngineMerchantBuy", reentrant_buy):
            requests = self.run_lua(" ".join(f"BuyMerchantItem({row})" for _ in range(8)))
        self.assertEqual(len(requests["merchant_buys"]), 8)
        self.assertEqual(maximum_depth, 1)
        self.assertEqual(observations, [(baseline_updates, visible_id)] * 8)
        self.assertEqual(self.ui.evaluate("return txMerchantShown,txMerchantUpdated"), baseline_shows)
        self.assertEqual(self.runtime._item_instances["native-merchant-first"]["owner_id"], "player")
        self.assertEqual(self.runtime._item_instances["native-merchant-second"]["owner_id"], "npc-wanderer-01")
        self.assertTrue(all(args == ("vendor.mira", visible_id) for name, args in self.bridge.calls
                            if name == "merchant_buy"))
        self.check_clean(unsupported=True)

    def test_external_occupied_bank_cell_blocks_an_older_empty_cell_drop(self):
        self.open_bank()
        self.ui.execute("PickupContainerItem(0,61) PickupContainerItem(-1,48)")
        deposited = self.runtime.deposit_to_stash("native-bank-food-second", 47)
        self.assertNotIn("error", deposited)
        actual_bank_before = copy.deepcopy(deposited["bank"]["items"])
        source_before = copy.deepcopy(self.runtime._item_instances["native-bank-food-first"])
        calls_before = len(self.bridge.calls)
        self.refresh()
        self.assertEqual(self.runtime._item_instances["native-bank-food-first"], source_before)
        self.assertEqual(self.runtime.snapshot()["bank"]["items"], actual_bank_before)
        self.assertFalse(any(name == "bank_deposit" for name, _ in self.bridge.calls[calls_before:]))
        self.assertIn("cross-container swaps", self.ui.evaluate("return txLastError")[0])
        self.check_clean(unsupported=True)

    def test_held_bag_cursor_is_cleared_when_its_exact_source_is_replaced(self):
        first, replacement = "native-held-sword-first", "native-held-sword-replacement"
        with self.runtime._lock:
            for name, slot in ((first, 58), (replacement, 59)):
                row = items.make_instance(self.runtime._item_catalog, name, "item.weapon_sword")
                row["slot_index"] = slot
                self.runtime._item_instances[name] = row
            self.runtime._inventory = items.inventory_counts(self.runtime._item_instances.values())
        self.refresh()
        self.ui.execute("PickupContainerItem(0,59)")
        self.assertEqual(self.ui.evaluate("return CursorHasItem()"), [True])
        swapped = self.runtime.move_inventory_slot(first, 59)
        self.assertNotIn("error", swapped)
        before = {name: copy.deepcopy(self.runtime._item_instances[name]) for name in (first, replacement)}
        self.refresh()
        self.assertEqual(self.ui.evaluate("return CursorHasItem()"), [False])
        requests = self.run_lua("PickupContainerItem(0,64)")
        self.assertEqual(requests["item_moves"], [])
        self.assertEqual({name: self.runtime._item_instances[name] for name in (first, replacement)}, before)
        self.check_clean()

    def test_held_bank_cursor_is_cleared_after_same_template_source_swap(self):
        self.open_bank()
        self.runtime.deposit_to_stash("native-bank-food-first", 2)
        self.runtime.deposit_to_stash("native-bank-food-second", 3)
        self.refresh()
        first = self.presentation.gameplay_views.bank.bank_refs[3][1]
        self.ui.execute("PickupContainerItem(-1,3)")
        self.assertEqual(self.ui.evaluate("return CursorHasItem()"), [True])
        moved = self.runtime.move_stash_slot(first, 3)
        self.assertNotIn("error", moved)
        before = copy.deepcopy(moved["bank"]["items"])
        self.refresh()
        self.assertEqual(self.ui.evaluate("return CursorHasItem()"), [False])
        requests = self.run_lua("PickupContainerItem(0,64)")
        self.assertEqual(requests["item_moves"], [])
        self.assertEqual(self.runtime.snapshot()["bank"]["items"], before)
        self.check_clean()

    def test_held_equipment_cursor_is_cleared_when_another_item_is_equipped(self):
        first, replacement = "native-held-equipped-first", "native-held-equipped-replacement"
        with self.runtime._lock:
            for name in (first, replacement):
                self.runtime._item_instances[name] = items.make_instance(
                    self.runtime._item_catalog, name, "item.weapon_sword")
            self.runtime._inventory = items.inventory_counts(self.runtime._item_instances.values())
        self.assertNotIn("error", self.runtime.equip_item(first, "MAIN_HAND"))
        self.refresh()
        self.ui.execute("assert(PickupInventoryItem(16))")
        self.assertEqual(self.ui.evaluate("return CursorHasItem()"), [True])
        self.assertNotIn("error", self.runtime.equip_item(replacement, "MAIN_HAND"))
        before = {name: copy.deepcopy(self.runtime._item_instances[name]) for name in (first, replacement)}
        self.refresh()
        self.assertEqual(self.ui.evaluate("return CursorHasItem()"), [False])
        requests = self.run_lua("PickupContainerItem(0,64)")
        self.assertEqual(requests["item_moves"], [])
        self.assertEqual({name: self.runtime._item_instances[name] for name in (first, replacement)}, before)
        self.check_clean()

    def test_held_merchant_cursor_does_not_rebind_to_the_next_physical_offer(self):
        self.open_merchant()
        row = self.merchant_row()
        self.ui.execute(f"PickupMerchantItem({row})")
        bought = self.runtime.merchant_buy("vendor.mira", "native-merchant-first")
        self.assertNotIn("error", bought)
        before = copy.deepcopy(self.runtime._economy_state)
        self.refresh()
        requests = self.run_lua("PickupContainerItem(0,64)")
        self.assertEqual(requests["merchant_slot_buys"], [])
        self.assertEqual(self.runtime._economy_state, before)
        self.assertEqual(self.runtime._item_instances["native-merchant-second"]["owner_id"], "npc-wanderer-01")
        self.check_clean()

    def test_held_same_instance_survives_count_and_condition_updates(self):
        self.ui.execute("PickupContainerItem(0,61)")
        self.assertEqual(self.ui.evaluate("return CursorHasItem()"), [True])
        with self.runtime._lock:
            source = self.runtime._item_instances["native-bank-food-first"]
            source.update(quantity=2, condition=.5)
            self.runtime._inventory = items.inventory_counts(self.runtime._item_instances.values())
        self.refresh()
        self.assertEqual(self.ui.evaluate("return CursorHasItem()"), [True])
        requests = self.run_lua("PickupContainerItem(0,64)")
        self.assertEqual(len(requests["item_moves"]), 1)
        self.assertEqual((source["slot_index"], source["quantity"], source["condition"]), (63, 2, .5))
        self.assertEqual(self.runtime._item_instances["native-bank-food-second"]["quantity"], 7)
        self.check_clean()


if __name__ == "__main__":
    unittest.main()
