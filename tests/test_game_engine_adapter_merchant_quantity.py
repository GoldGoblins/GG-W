"""Finite shown bundles commit together; requests never mint or retarget stock."""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QObject, Signal

from backend import game_engine_items as items, game_engine_mmo as mmo
from backend import game_engine_character_creation as appearance
from backend.game_engine_adapter_gameplay import GameplayViews
from backend.game_engine_adapter_merchant import MAX_VENDOR_ROWS, MerchantViews
from backend.game_engine_local_characters import CharacterStore


class GGBridge(QObject):
    """Use the same JSON method boundary as the real Qt game hosts."""
    snapshotPublished = Signal(object)

    def __init__(self, runtime):
        super().__init__(); self.runtime = runtime; self.calls = []

    def gameEngineMerchantBuyBundles(self, vendor, requests):
        self.calls.append((vendor, requests))
        return json.dumps(self.runtime.merchant_buy_bundles(vendor, requests))


_APP = None


class MerchantQuantity(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        environment = {"XDG_" + key + "_HOME": str(self.root / key.lower())
                       for key in ("STATE", "CONFIG", "CACHE", "DATA")}
        for context in (patch.dict(os.environ, environment),
                        patch.object(mmo, "DEFAULT_STASH_PATH", self.root / "stash.json"),
                        patch.object(appearance, "STATE_PATH", self.root / "appearance.json")):
            context.start(); self.addCleanup(context.stop)
        from backend.game_engine_host import GameEngineRuntime
        self.runtime = GameEngineRuntime(); self.addCleanup(self.runtime.shutdown)
        self.runtime._state_store = CharacterStore(self.root / "characters")
        self.runtime._persistence_key = "0" * 32
        self.vendor_id = "vendor.mira"; self.owner = "npc-wanderer-01"
        index = next(index for index in self.runtime._npc_indices
                     if self.runtime._npc_ids[index] == self.owner)
        self.runtime._x[0] = self.runtime._x[index]
        self.runtime._z[0] = self.runtime._z[index]
        self.add_bundle("merchant-quantity-a")
        self.add_bundle("merchant-quantity-b")
        self.add_bundle("merchant-quantity-c", quantity=7)
        self.views = GameplayViews(); self.merchant = MerchantViews(self.views.identity)
        self.assertNotIn("error", self.runtime.open_merchant(self.vendor_id))
        self.refresh()

    def add_bundle(self, instance_id, quantity=3, **fields):
        self.runtime._item_instances[instance_id] = items.make_instance(
            self.runtime._item_catalog, instance_id, "item.sea_salt", quantity=quantity,
            owner_id=self.owner, location="POCKET")
        self.runtime._item_instances[instance_id].update(fields)
        self.runtime._individual_state["individuals"][self.owner]["inventory"].append("item.sea_salt")

    def refresh(self):
        self.shown = self.runtime.snapshot()
        self.projected = self.merchant.update(self.shown)
        self.row = next(row for row, (_, instance) in self.merchant.buy_refs.items()
                        if instance == "merchant-quantity-a")

    def plan(self, quantity=2):
        route = self.merchant.route_buy(self.row, quantity)
        self.assertEqual(route["method"], "gameEngineMerchantBuyBundles")
        return route["args"]

    def state(self):
        fields = ("_item_instances", "_inventory", "_economy_state", "_individual_state",
                  "_combat_state", "_quest_state", "_event_journal", "_events",
                  "_npc_interaction_count", "_npc_last_interaction", "_last_item_interaction",
                  "_persistence_revision", "_item_counter")
        return {key: copy.deepcopy(getattr(self.runtime, key)) for key in fields}

    def rejected(self, args, error):
        before = self.state()
        with patch.object(self.runtime, "save_state", wraps=self.runtime.save_state) as save:
            result = self.runtime.merchant_buy_bundles(*args)
        self.assertEqual(result.get("error"), error)
        self.assertEqual(self.state(), before)
        self.assertEqual(save.call_count, 0)
        return result

    def test_two_visible_physical_bundles_buy_once_at_the_shown_quote_and_survive_reload(self):
        registry = set(self.runtime._item_instances)
        args = self.plan(); records = json.loads(args[1])
        self.assertEqual([row["instance_id"] for row in records], ["merchant-quantity-a", "merchant-quantity-b"])
        self.assertEqual(self.projected["items"][self.row - 1]["num_available"], 2)
        self.assertEqual(self.projected["items"][self.row - 1]["quantity"], 3)
        price = sum(row["total_price"] for row in records)
        wallet = self.runtime._economy_state["wallet"]["gold"]
        vendor = self.runtime._economy_state["vendors"][self.vendor_id]["gold"]
        total = wallet + vendor
        with patch.object(self.runtime, "save_state", wraps=self.runtime.save_state) as save:
            result = self.runtime.merchant_buy_bundles(*args)
        self.assertNotIn("error", result)
        self.assertEqual(save.call_count, 1)
        self.assertEqual(set(self.runtime._item_instances), registry)
        self.assertEqual(result["economy_result"]["bundle_count"], 2)
        self.assertEqual(result["economy_result"]["quantity"], 6)
        self.assertEqual(result["economy_result"]["total_price"], price)
        self.assertEqual(self.runtime._economy_state["wallet"]["gold"], wallet - price)
        self.assertEqual(self.runtime._economy_state["vendors"][self.vendor_id]["gold"], vendor + price)
        self.assertEqual(self.runtime._economy_state["wallet"]["gold"] +
                         self.runtime._economy_state["vendors"][self.vendor_id]["gold"], total)
        transactions = self.runtime._economy_state["history"][-2:]
        self.assertEqual([row["total_price"] for row in transactions], [price // 2] * 2)
        for identity in ("merchant-quantity-a", "merchant-quantity-b"):
            self.assertEqual(self.runtime._item_instances[identity]["owner_id"], "player")
            self.assertEqual(self.runtime._item_instances[identity]["quantity"], 3)
        self.assertEqual(self.runtime._item_instances["merchant-quantity-c"]["owner_id"], self.owner)
        self.runtime.load_state()
        for identity in ("merchant-quantity-a", "merchant-quantity-b"):
            self.assertEqual(self.runtime._item_instances[identity]["owner_id"], "player")
            self.assertEqual(self.runtime._item_instances[identity]["quantity"], 3)
        self.assertEqual(set(self.runtime._item_instances), registry)

    def test_queued_replay_never_selects_new_replacement_stock(self):
        args = self.plan()
        self.assertNotIn("error", self.runtime.merchant_buy_bundles(*args))
        self.add_bundle("merchant-quantity-replacement")
        self.rejected(args, "VENDOR_BUNDLE_REVISION_CHANGED")
        self.assertEqual(self.runtime._item_instances["merchant-quantity-replacement"]["owner_id"], self.owner)

    def test_replay_cannot_consume_replacement_even_if_revision_is_unchanged(self):
        args = self.plan(); revision = json.loads(args[1])[0]["revision"]
        self.assertNotIn("error", self.runtime.merchant_buy_bundles(*args))
        self.add_bundle("merchant-quantity-replacement")
        self.runtime._economy_state["vendors"][self.vendor_id]["revision"] = revision
        self.rejected(args, "VENDOR_STOCK_INSTANCE_INVALID")

    def test_route_rejects_bool_zero_overflow_and_insufficient_identical_stock(self):
        for count in (True, False, 0, -1, MAX_VENDOR_ROWS + 1, 2.0, "2"):
            with self.subTest(count=count), self.assertRaisesRegex(ValueError, "purchase count"):
                self.merchant.route_buy(self.row, count)
        with self.assertRaisesRegex(ValueError, "insufficient identical physical"):
            self.merchant.route_buy(self.row, 3)
        self.assertEqual(self.merchant.route_buy(self.row, 1)["method"], "gameEngineMerchantBuy")

    def test_plans_are_immutable_and_selected_row_is_first(self):
        args = self.plan()
        self.shown["economy"]["vendors"][0]["offers"]["buy"].clear()
        self.assertEqual(self.plan(), args)
        row = next(row for row, (_, instance) in self.merchant.buy_refs.items()
                   if instance == "merchant-quantity-b")
        records = json.loads(self.merchant.route_buy(row, 2)["args"][1])
        self.assertEqual(records[0]["instance_id"], "merchant-quantity-b")
        self.assertEqual(records[1]["instance_id"], "merchant-quantity-a")

    def test_each_real_row_has_finite_identical_stock_and_recounts_after_purchase(self):
        first = self.row
        second = next(row for row, (_, instance) in self.merchant.buy_refs.items()
                      if instance == "merchant-quantity-b")
        self.assertNotEqual(first, second)
        for row in (first, second):
            self.assertEqual(self.projected["items"][row - 1]["num_available"], 2)
            records = json.loads(self.merchant.route_buy(row, 2)["args"][1])
            self.assertEqual({record["instance_id"] for record in records},
                             {"merchant-quantity-a", "merchant-quantity-b"})
        self.assertNotIn("error", self.runtime.merchant_buy(self.vendor_id, "merchant-quantity-a"))
        projected = self.merchant.update(self.runtime.snapshot())
        self.assertNotIn("merchant-quantity-a", [source[1] for source in self.merchant.buy_refs.values()])
        second = next(row for row, (_, instance) in self.merchant.buy_refs.items()
                      if instance == "merchant-quantity-b")
        self.assertEqual(projected["items"][second - 1]["num_available"], 1)
        with self.assertRaisesRegex(ValueError, "insufficient identical physical"):
            self.merchant.route_buy(second, 2)
        self.add_bundle("merchant-quantity-new-physical-stock")
        projected = self.merchant.update(self.runtime.snapshot())
        for row, (_, identity) in self.merchant.buy_refs.items():
            if identity in {"merchant-quantity-b", "merchant-quantity-new-physical-stock"}:
                self.assertEqual(projected["items"][row - 1]["num_available"], 2)

    def test_original_lua_buys_two_real_bundles_through_ggbridge_with_one_save_and_reload(self):
        global _APP
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtGui import QGuiApplication
        from backend.game_engine_presentation import Presentation
        _APP = QGuiApplication.instance() or QGuiApplication([])
        bridge = self.gg_bridge = GGBridge(self.runtime)
        presentation = self.gg_presentation = Presentation(bridge, device=False)
        self.addCleanup(presentation.close)
        self.assertTrue(presentation.full_ui)
        ui = presentation.lua; self.assertIsNotNone(ui)
        presentation.last_update = 0; presentation.update(self.runtime.snapshot())
        shown = presentation.gameplay_views.merchant
        row = next(index for index, (_, identity) in shown.buy_refs.items()
                   if identity == "merchant-quantity-a")
        second = next(index for index, (_, identity) in shown.buy_refs.items()
                      if identity == "merchant-quantity-b")
        self.assertEqual(ui.evaluate(
            f"local _,_,_,q,n=GetMerchantItemInfo({row}); "
            f"local _,_,_,q2,n2=GetMerchantItemInfo({second}); return q,n,q2,n2"), [3,2,3,2])
        price = self.projected["items"][self.row - 1]["price"] // 10000 * 2
        gold = self.runtime._economy_state["wallet"]["gold"]
        registry = set(self.runtime._item_instances)
        ui.execute(f"BuyMerchantItem({row},2)")
        requests = ui.request("requests")
        self.assertEqual(requests["merchant_buys"], [[row, 2]])
        with patch.object(self.runtime, "save_state", wraps=self.runtime.save_state) as save:
            presentation._game_requests(requests)
        self.assertEqual(save.call_count, 1)
        self.assertEqual(len(bridge.calls), 1)
        self.assertEqual(bridge.calls[0][0], self.vendor_id)
        self.assertEqual([record["instance_id"] for record in json.loads(bridge.calls[0][1])],
                         ["merchant-quantity-a", "merchant-quantity-b"])
        self.assertEqual(self.runtime._economy_state["wallet"]["gold"], gold - price)
        self.assertEqual(set(self.runtime._item_instances), registry)
        for identity in ("merchant-quantity-a", "merchant-quantity-b"):
            self.assertEqual(self.runtime._item_instances[identity]["owner_id"], "player")
            self.assertEqual(self.runtime._item_instances[identity]["quantity"], 3)
        result = self.runtime.load_state(); self.assertNotIn("error", result)
        self.assertEqual(self.runtime._economy_state["wallet"]["gold"], gold - price)
        for identity in ("merchant-quantity-a", "merchant-quantity-b"):
            self.assertEqual(self.runtime._item_instances[identity]["owner_id"], "player")
        presentation.last_update = 0; presentation.update(self.runtime.snapshot())
        self.assertNotIn("merchant-quantity-a", [source[1] for source in presentation.gameplay_views.merchant.buy_refs.values()])
        self.assertNotIn("merchant-quantity-b", [source[1] for source in presentation.gameplay_views.merchant.buy_refs.values()])
        self.assertFalse(presentation.errors, presentation.errors)
        self.assertFalse(presentation.unsupported_requests, presentation.unsupported_requests)
        self.assertFalse(ui.errors, ui.errors)

    def test_different_condition_and_enchantments_are_separate_bundles(self):
        self.runtime._item_instances["merchant-quantity-b"]["condition"] = .5
        self.refresh()
        with self.assertRaisesRegex(ValueError, "insufficient identical physical"):
            self.merchant.route_buy(self.row, 2)
        self.runtime._item_instances["merchant-quantity-b"]["condition"] = 1.
        self.runtime._item_instances["merchant-quantity-b"]["enchantments"] = [{"id": "different"}]
        self.refresh()
        with self.assertRaisesRegex(ValueError, "insufficient identical physical"):
            self.merchant.route_buy(self.row, 2)

    def test_closed_and_distant_sessions_fail_without_moving_any_bundle(self):
        args = self.plan(); self.runtime.close_merchant()
        self.rejected(args, "MERCHANT_SESSION_REQUIRED")
        self.runtime.open_merchant(self.vendor_id); self.runtime._x[0] += 100.
        self.rejected(args, "MERCHANT_SESSION_REQUIRED")

    def test_changed_vendor_revision_and_unversioned_quote_both_reject(self):
        args = self.plan()
        account = self.runtime._economy_state["vendors"][self.vendor_id]
        account["revision"] += 1
        self.rejected(args, "VENDOR_BUNDLE_REVISION_CHANGED")
        self.runtime._economy_state["vendors"][self.vendor_id]["revision"] -= 1
        # Even when no revision accompanies a price edit, the frozen quote
        # must agree with the authoritative vendor definition at execution.
        self.runtime._vendor_catalog[self.vendor_id]["pricing"]["item.sea_salt"]["buy"] += 10
        self.rejected(args, "VENDOR_BUNDLE_OFFER_CHANGED")

    def test_changed_stack_quantity_or_item_condition_rejects_the_whole_plan(self):
        args = self.plan()
        self.runtime._item_instances["merchant-quantity-b"]["quantity"] += 1
        self.rejected(args, "VENDOR_BUNDLE_OFFER_CHANGED")
        self.runtime._item_instances["merchant-quantity-b"]["quantity"] -= 1
        self.runtime._item_instances["merchant-quantity-b"]["condition"] = .25
        self.rejected(args, "VENDOR_BUNDLE_OFFER_CHANGED")

    def test_fake_ids_duplicates_and_forged_prices_fail_without_stock_or_coin_changes(self):
        args = self.plan(); rows = json.loads(args[1])
        changed = copy.deepcopy(rows); changed[1]["instance_id"] = "stock-does-not-exist"
        self.rejected((self.vendor_id, changed), "VENDOR_STOCK_INSTANCE_INVALID")
        self.rejected((self.vendor_id, [rows[0], rows[0]]), "VENDOR_BUNDLE_INSTANCE_DUPLICATE")
        changed = copy.deepcopy(rows)
        for row in changed: row["total_price"] = 1
        self.rejected((self.vendor_id, changed), "VENDOR_BUNDLE_OFFER_CHANGED")

    def test_malformed_count_bool_quotes_and_oversized_requests_fail_closed(self):
        rows = json.loads(self.plan()[1])
        for value in ([], rows[:1], rows * 9, {}, "{", " " * 8193):
            with self.subTest(value=str(value)[:20]):
                before = self.state()
                result = self.runtime.merchant_buy_bundles(self.vendor_id, value)
                self.assertIn("error", result); self.assertEqual(self.state(), before)
        for field in ("quantity", "total_price", "revision"):
            changed = copy.deepcopy(rows); changed[0][field] = True
            before = self.state()
            result = self.runtime.merchant_buy_bundles(self.vendor_id, changed)
            self.assertIn("error", result); self.assertEqual(self.state(), before)

    def test_aggregate_wallet_and_vendor_coin_capacity_are_checked_before_first_move(self):
        args = self.plan(); price = json.loads(args[1])[0]["total_price"]
        self.runtime._economy_state["wallet"]["gold"] = price
        self.rejected(args, "VENDOR_PLAYER_GOLD_INSUFFICIENT")
        self.runtime._economy_state["wallet"]["gold"] = price * 2
        self.runtime._economy_state["vendors"][self.vendor_id]["gold"] = 2_000_000_000 - price
        self.rejected(args, "VENDOR_GOLD_CAPACITY")

    def test_all_physical_backpack_slots_are_reserved_before_first_move(self):
        args = self.plan()
        used = sum(row.get("owner_id") == "player" and row.get("location") == "INVENTORY"
                   for row in self.runtime._item_instances.values())
        for number in range(items.MAX_INVENTORY_SLOTS - used - 1):
            identity = "full-backpack-" + str(number)
            self.runtime._item_instances[identity] = items.make_instance(
                self.runtime._item_catalog, identity, "item.sea_salt", owner_id="player", location="INVENTORY")
            self.runtime._inventory["item.sea_salt"] = self.runtime._inventory.get("item.sea_salt", 0) + 1
        self.runtime._ensure_inventory_slots_locked()
        self.rejected(args, "VENDOR_PLAYER_INVENTORY_FULL")

    def test_second_move_failure_rolls_back_first_bundle_with_no_checkpoint(self):
        args = self.plan(); move = self.runtime._move_item_locked
        def guarded(instance, *positional, **keywords):
            if instance["instance_id"] == "merchant-quantity-b":
                return False, {"error": "INJECTED_MOVE_FAILURE"}
            return move(instance, *positional, **keywords)
        with patch.object(self.runtime, "_move_item_locked", side_effect=guarded):
            self.rejected(args, "VENDOR_ATOMIC_ROLLBACK")

    def test_disk_failure_restores_every_item_coin_and_event_and_preserves_previous_save(self):
        args = self.plan(); self.runtime.save_state(snapshot=False)
        saved = self.runtime._state_store.load(self.runtime._persistence_key)
        before = self.state()
        with patch.object(self.runtime._state_store, "save", side_effect=OSError("disk full")):
            result = self.runtime.merchant_buy_bundles(*args)
        self.assertEqual(result.get("error"), "VENDOR_SAVE_FAILED")
        self.assertEqual(self.state(), before)
        self.assertEqual(self.runtime._state_store.load(self.runtime._persistence_key), saved)


if __name__ == "__main__":
    unittest.main()
