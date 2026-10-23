"""Physical vendor bundles and atomic GG money/item transitions via Lua routes."""

import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from backend import game_engine_items as items
from backend import game_engine_mmo as mmo
from backend.game_engine_adapter_gameplay import GameplayViews
from backend.game_engine_adapter_merchant import MerchantViews


class Merchant(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(mmo, "DEFAULT_STASH_PATH", Path(directory) / "unused.json"):
                from backend.game_engine_host import GameEngineRuntime
                cls.Runtime = GameEngineRuntime

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        with patch.object(mmo, "DEFAULT_STASH_PATH", Path(directory.name) / "account-stash.json"):
            self.runtime = self.Runtime()
        self.addCleanup(self.runtime.shutdown)
        self.views = GameplayViews()
        self.merchant = MerchantViews(self.views.identity)
        self.vendor_id = "vendor.mira"
        self.npc_id = "npc-wanderer-01"
        with self.runtime._lock:
            self.npc_index = next(index for index in self.runtime._npc_indices
                                  if self.runtime._npc_ids[index] == self.npc_id)
            self.runtime._x[0] = self.runtime._x[self.npc_index]
            self.runtime._z[0] = self.runtime._z[self.npc_index]
            person = self.runtime._individual_state["individuals"][self.npc_id]
            for name, quantity in (("merchant-bundle-first", 3), ("merchant-bundle-second", 7)):
                self.runtime._item_instances[name] = items.make_instance(
                    self.runtime._item_catalog, name, "item.sea_salt", quantity=quantity,
                    owner_id=self.npc_id, location="POCKET")
                person["inventory"].append("item.sea_salt")
        opened = self.runtime.open_merchant(self.vendor_id)
        self.assertNotIn("error", opened)
        self.refresh()

    def refresh(self):
        snapshot = self.runtime.snapshot()
        self.views.update(snapshot)
        self.projected = self.merchant.update(snapshot)
        return snapshot

    def vendor(self, snapshot):
        return next(row for row in snapshot["economy"]["vendors"] if row["id"] == self.vendor_id)

    def bundle_row(self):
        return next(row for row, (_, instance) in self.merchant.buy_refs.items()
                    if instance == "merchant-bundle-first")

    def purchase_bundle(self):
        plan = self.merchant.route_buy(self.bundle_row(), 1)
        result = self.runtime.merchant_buy(*plan["args"])
        self.assertNotIn("error", result)
        self.refresh()
        return result

    def test_exact_bundle_purchase_and_sale_conserve_total_money(self):
        before = self.runtime.snapshot()
        row = self.bundle_row()
        offer = self.projected["items"][row - 1]
        total_before = before["economy"]["wallet"]["gold"] + self.vendor(before)["gold"]
        self.assertTrue(self.projected["open"])
        self.assertEqual(offer["quantity"], 3)
        self.assertEqual(offer["num_available"], 1)
        self.assertEqual(offer["item_id"], self.views.identity("item.sea_salt"))
        bought = self.purchase_bundle()
        self.assertEqual(bought["economy_result"]["quantity"], 3)
        self.assertEqual(bought["economy_result"]["total_price"] * 10000, offer["price"])
        self.assertEqual(bought["economy"]["wallet"]["gold"] + self.vendor(bought)["gold"], total_before)
        self.assertEqual(self.runtime._item_instances["merchant-bundle-first"]["owner_id"], "player")
        self.assertEqual(self.runtime._item_instances["merchant-bundle-first"]["quantity"], 3)
        self.assertEqual(self.runtime._item_instances["merchant-bundle-second"]["owner_id"], self.npc_id)
        self.assertEqual(self.runtime._item_instances["merchant-bundle-second"]["quantity"], 7)
        slot = next(slot for slot, (_, instance) in self.views.inventory_refs.items()
                    if instance == "merchant-bundle-first")
        plan = self.merchant.route_sell(0, slot, self.views.inventory_refs)
        self.assertEqual(plan["method"], "gameEngineMerchantSell")
        sold = self.runtime.merchant_sell(*plan["args"])
        self.assertNotIn("error", sold)
        self.assertEqual(sold["economy_result"]["quantity"], 3)
        self.assertEqual(sold["economy"]["wallet"]["gold"] + self.vendor(sold)["gold"], total_before)
        self.assertEqual(self.runtime._item_instances["merchant-bundle-first"]["location"], "POCKET")
        self.assertEqual(self.runtime._item_instances["merchant-bundle-first"]["owner_id"], self.npc_id)

    def test_proximity_alone_does_not_open_or_retain_the_merchant(self):
        self.runtime.close_merchant()
        snapshot = self.refresh()
        self.assertTrue(self.vendor(snapshot)["presence"]["available"])
        self.assertFalse(self.projected["open"])
        self.assertEqual(self.merchant.buy_refs, {})
        self.assertEqual(self.merchant.sell_refs, {})
        with self.assertRaisesRegex(ValueError, "closed"):
            self.merchant.route_buy(1)
        snapshot.pop("merchant")
        self.assertFalse(self.merchant.update(snapshot)["open"])

    def test_unavailable_vendor_closes_projection_even_with_stale_open_flag(self):
        with self.runtime._lock:
            self.runtime._x[0] += 100
        snapshot = self.runtime.snapshot()
        self.assertFalse(self.vendor(snapshot)["presence"]["available"])
        snapshot["merchant"].update(open=True, vendor_id=self.vendor_id)
        self.assertFalse(self.merchant.update(snapshot)["open"])
        self.assertEqual(self.merchant.buy_refs, {})

    def test_stale_plan_runtime_rechecks_reach_and_keeps_item_and_money(self):
        plan = self.merchant.route_buy(self.bundle_row())
        item_before = copy.deepcopy(self.runtime._item_instances["merchant-bundle-first"])
        money_before = copy.deepcopy(self.runtime._economy_state)
        with self.runtime._lock:
            self.runtime._x[0] += 100
        rejected = self.runtime.merchant_buy(*plan["args"])
        self.assertEqual(rejected["error"], "MERCHANT_SESSION_REQUIRED")
        self.assertEqual(self.runtime._item_instances["merchant-bundle-first"], item_before)
        self.assertEqual(self.runtime._economy_state, money_before)

    def test_stale_close_plan_cannot_buy_while_vendor_remains_nearby(self):
        plan = self.merchant.route_buy(self.bundle_row())
        item_before = copy.deepcopy(self.runtime._item_instances["merchant-bundle-first"])
        money_before = copy.deepcopy(self.runtime._economy_state)
        self.runtime.close_merchant()
        self.assertTrue(self.vendor(self.runtime.snapshot())["presence"]["available"])
        rejected = self.runtime.merchant_buy(*plan["args"])
        self.assertEqual(rejected["error"], "MERCHANT_SESSION_REQUIRED")
        self.assertEqual(self.runtime._item_instances["merchant-bundle-first"], item_before)
        self.assertEqual(self.runtime._economy_state, money_before)

    def test_guarded_host_rejects_session_vendor_drift(self):
        money_before = copy.deepcopy(self.runtime._economy_state)
        rejected = self.runtime.merchant_buy("vendor.missing", "merchant-bundle-first")
        self.assertEqual(rejected["error"], "MERCHANT_SESSION_REQUIRED")
        self.assertEqual(self.runtime._economy_state, money_before)
        self.assertEqual(self.runtime._item_instances["merchant-bundle-first"]["owner_id"], self.npc_id)

    def test_stale_buy_cannot_purchase_another_same_template_stack(self):
        plan = self.merchant.route_buy(self.bundle_row())
        first = self.runtime.merchant_buy(*plan["args"])
        self.assertNotIn("error", first)
        money_before = copy.deepcopy(self.runtime._economy_state)
        rejected = self.runtime.merchant_buy(*plan["args"])
        self.assertEqual(rejected["error"], "VENDOR_STOCK_INSTANCE_INVALID")
        self.assertEqual(self.runtime._economy_state, money_before)
        self.assertEqual(self.runtime._item_instances["merchant-bundle-second"]["owner_id"], self.npc_id)
        self.assertEqual(self.runtime._item_instances["merchant-bundle-second"]["quantity"], 7)

    def test_foreign_source_has_no_sell_route_and_host_rejects_it(self):
        with self.assertRaisesRegex(ValueError, "exact inventory item"):
            self.merchant.route_sell(0, 1, {1: ("item.sea_salt", "merchant-bundle-second")})
        money_before = copy.deepcopy(self.runtime._economy_state)
        rejected = self.runtime.merchant_sell(self.vendor_id, "merchant-bundle-second")
        self.assertEqual(rejected["error"], "VENDOR_SELL_LOCATION_INVALID")
        self.assertEqual(self.runtime._economy_state, money_before)

    def test_finite_bundle_counts_and_other_sell_containers_are_explicitly_rejected(self):
        before = copy.deepcopy(self.runtime._economy_state)
        for quantity in (0, 2, 3, -1):
            with self.subTest(quantity=quantity), self.assertRaisesRegex(ValueError, "purchase count|insufficient identical physical"):
                self.merchant.route_buy(self.bundle_row(), quantity)
        for bag in (-100, -1, 1, 5):
            with self.subTest(bag=bag), self.assertRaisesRegex(ValueError, "sell container"):
                self.merchant.route_sell(bag, 1, self.views.inventory_refs)
        self.assertEqual(self.runtime._economy_state, before)

    def test_oversized_quote_fails_closed_without_price_clamping(self):
        snapshot = self.runtime.snapshot()
        offer = self.vendor(snapshot)["offers"]["buy"][0]
        offer["total_price"] = ((1 << 32) - 1) // 10000 + 1
        with self.assertRaisesRegex(ValueError, "represented in copper"):
            self.merchant.update(snapshot)
        self.assertFalse(self.merchant.opened)
        self.assertEqual(self.merchant.buy_refs, {})
        self.assertEqual(self.merchant.sell_refs, {})

    def test_ambiguous_instance_or_unknown_session_fails_closed(self):
        snapshot = self.runtime.snapshot()
        offers = self.vendor(snapshot)["offers"]["buy"]
        offers.append(copy.deepcopy(offers[0]))
        with self.assertRaisesRegex(ValueError, "Ambiguous"):
            self.merchant.update(snapshot)
        self.assertFalse(self.merchant.opened)
        snapshot = self.runtime.snapshot()
        snapshot["merchant"]["vendor_id"] = "vendor.missing"
        with self.assertRaisesRegex(ValueError, "session vendor"):
            self.merchant.update(snapshot)
        self.assertEqual(self.merchant.buy_refs, {})

    def test_insufficient_money_keeps_the_physical_bundle_unchanged(self):
        plan = self.merchant.route_buy(self.bundle_row())
        with self.runtime._lock:
            self.runtime._economy_state["wallet"]["gold"] = 0
        before = copy.deepcopy(self.runtime._item_instances["merchant-bundle-first"])
        rejected = self.runtime.merchant_buy(*plan["args"])
        self.assertEqual(rejected["error"], "VENDOR_PLAYER_GOLD_INSUFFICIENT")
        self.assertEqual(self.runtime._item_instances["merchant-bundle-first"], before)
        self.assertEqual(rejected["economy"]["wallet"]["gold"], 0)


if __name__ == "__main__":
    unittest.main()
