"""Actual account-chest transfers through the bounded GgEngine routing plan."""

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
from backend.game_engine_adapter_bank import BankViews
from backend.game_engine_adapter_gameplay import GameplayViews


class Bank(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Importing the host creates its module-level runtime. Even that
        # unused fixture must not read or create the user's account stash.
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(mmo, "DEFAULT_STASH_PATH", Path(directory) / "unused.json"):
                from backend.game_engine_host import GameEngineRuntime
                cls.Runtime = GameEngineRuntime

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.stash_path = Path(directory.name) / "account-stash.json"
        with patch.object(mmo, "DEFAULT_STASH_PATH", self.stash_path):
            self.runtime = self.Runtime()
        self.addCleanup(self.runtime.shutdown)
        self.views = GameplayViews()
        self.bank = BankViews(self.views.identity)
        self.food = next(ref for ref, definition in self.runtime._item_catalog["items"].items()
                         if definition.get("kind") == "CONSUMABLE"
                         and definition.get("stack_limit", 1) >= 7)
        with self.runtime._lock:
            for instance, slot, quantity in (("bank-first-stack", 60, 3),
                                              ("bank-second-stack", 61, 7)):
                row = items.make_instance(self.runtime._item_catalog, instance, self.food,
                                          quantity=quantity)
                row["slot_index"] = slot
                self.runtime._item_instances[instance] = row
            self.runtime._inventory = items.inventory_counts(self.runtime._item_instances.values())
            crate = next(row for row in self.runtime._item_instances.values()
                         if row.get("definition_id") == "container.supply_crate")
            self.crate = crate["instance_id"]
            self.runtime._x[0] = crate["position"]["x"]
            self.runtime._z[0] = crate["position"]["z"]
        self.runtime.open_container(self.crate)
        self.refresh()

    def refresh(self):
        snapshot = self.runtime.snapshot()
        self.views.update(snapshot)
        self.projected = self.bank.update(snapshot)
        return snapshot

    def transfer(self, source_bag, source_slot, destination_bag, destination_slot):
        plan = self.bank.route({"src_bag": source_bag, "src_slot": source_slot,
                               "dst_bag": destination_bag, "dst_slot": destination_slot,
                               "count": None}, self.views.inventory_refs)
        methods = {"gameEngineBankDepositAt": self.runtime.deposit_to_stash,
                   "gameEngineBankWithdrawAt": self.runtime.withdraw_from_stash,
                   "gameEngineBankMove": self.runtime.move_stash_slot}
        result = methods[plan["method"]](*plan["args"])
        self.assertNotIn("error", result)
        self.refresh()
        return result

    def test_real_capacity_and_exact_stack_roundtrip(self):
        self.assertTrue(self.projected["open"])
        self.assertEqual(self.projected["capacity"], mmo.MAX_STASH_SLOTS)
        self.assertEqual(self.projected["items"], [])
        self.transfer(0, 61, -1, 48)
        snapshot = self.runtime.snapshot()
        stored = next(row for row in snapshot["bank"]["items"] if row["slot_index"] == 47)
        self.assertEqual(stored["quantity"], 3)
        self.assertEqual(stored["definition_id"], self.food)
        self.assertNotEqual(stored["instance_id"], "bank-first-stack")
        self.assertNotIn("bank-first-stack", self.runtime._item_instances)
        self.assertEqual(self.runtime._item_instances["bank-second-stack"]["quantity"], 7)
        projected = self.projected["items"][0]
        self.assertEqual(projected["item_id"], self.views.identity(self.food))
        self.assertEqual(projected["count"], 3)
        self.assertEqual(projected["slot"], 48)
        self.assertEqual(projected["icon"], stored["icon"])
        self.transfer(-1, 48, 0, 64)
        self.assertEqual(self.runtime._item_instances[stored["instance_id"]]["slot_index"], 63)
        self.assertEqual(self.runtime._item_instances[stored["instance_id"]]["quantity"], 3)
        self.assertEqual(self.runtime._item_instances["bank-second-stack"]["quantity"], 7)
        self.assertEqual(self.projected["items"], [])
        self.assertEqual(self.bank.bank_refs, {})

    def test_real_within_bank_move_swaps_two_independent_instances(self):
        self.transfer(0, 61, -1, 47)
        self.transfer(0, 62, -1, 48)
        first = self.bank.bank_refs[47][1]
        second = self.bank.bank_refs[48][1]
        self.transfer(-1, 47, -1, 48)
        self.assertEqual(self.bank.bank_refs[48][1], first)
        self.assertEqual(self.bank.bank_refs[47][1], second)
        self.assertEqual({row["count"] for row in self.projected["items"]}, {3, 7})
        self.assertTrue(self.stash_path.is_file())
        reloaded = mmo.LocalAccountStashStore(self.stash_path).load(self.runtime._account_id)
        self.assertEqual({row["instance_id"]: row["slot_index"] for row in reloaded["items"]},
                         {first: 47, second: 46})

    def test_original_bank_right_click_auto_stores_without_consuming_the_stack(self):
        plan = self.bank.route_use(0, 61, self.views.inventory_refs)
        self.assertEqual(plan["method"], "gameEngineBankDepositAt")
        deposited = self.runtime.deposit_to_stash(*plan["args"])
        self.assertNotIn("error", deposited)
        self.refresh()
        slot = next(iter(self.bank.bank_refs))
        instance = self.bank.bank_refs[slot][1]
        self.assertEqual(self.projected["items"][0]["count"], 3)
        plan = self.bank.route_use(-1, slot, self.views.inventory_refs)
        self.assertEqual(plan["method"], "gameEngineBankWithdrawAt")
        withdrawn = self.runtime.withdraw_from_stash(*plan["args"])
        self.assertNotIn("error", withdrawn)
        self.assertEqual(self.runtime._item_instances[instance]["quantity"], 3)
        self.assertEqual(self.runtime._item_instances[instance]["location"], "INVENTORY")
        self.assertEqual(self.runtime._item_instances["bank-second-stack"]["quantity"], 7)

    def test_closed_or_failed_bank_clears_visible_and_routable_sources(self):
        self.transfer(0, 61, -1, 48)
        with self.runtime._lock:
            self.runtime._x[0] += 100
        self.refresh()
        self.assertFalse(self.projected["open"])
        self.assertEqual(self.projected["items"], [])
        self.assertEqual(self.bank.bank_refs, {})
        with self.assertRaisesRegex(ValueError, "closed or out of reach"):
            self.bank.route({"src_bag": -1, "src_slot": 48, "dst_bag": 0,
                             "dst_slot": 64, "count": None}, self.views.inventory_refs)
        # Accessible alone cannot override the runtime's account-store error.
        broken = self.runtime.snapshot()
        broken["bank"].update(accessible=True, error="ACCOUNT_STASH_FORMAT_INVALID")
        self.assertFalse(self.bank.update(broken)["open"])

    def test_stale_plan_runtime_rechecks_reach_without_deleting_the_source(self):
        self.transfer(0, 61, -1, 48)
        instance = self.bank.bank_refs[48][1]
        plan = self.bank.route({"src_bag": -1, "src_slot": 48, "dst_bag": 0,
                               "dst_slot": 64, "count": None}, self.views.inventory_refs)
        before = self.stash_path.read_bytes()
        with self.runtime._lock:
            self.runtime._x[0] += 100
        rejected = self.runtime.withdraw_from_stash(*plan["args"])
        self.assertEqual(rejected["error"], "ACCOUNT_STASH_OUT_OF_REACH")
        self.assertEqual(self.stash_path.read_bytes(), before)
        self.assertNotIn(instance, self.runtime._item_instances)
        self.assertTrue(any(row["instance_id"] == instance for row in rejected["bank"]["items"]))

    def test_runtime_rejects_forged_foreign_instance_ownership(self):
        with self.runtime._lock:
            row = items.make_instance(self.runtime._item_catalog, "bank-foreign-stack", self.food,
                                      owner_id="npc-foreign")
            self.runtime._item_instances[row["instance_id"]] = row
        # The adapter has no authority over an external host. Even forged
        # source references cannot turn an NPC-owned instance into player loot.
        plan = self.bank.route({"src_bag": 0, "src_slot": 61, "dst_bag": -1,
                               "dst_slot": 48, "count": None},
                              {61: (self.food, "bank-foreign-stack")})
        rejected = self.runtime.deposit_to_stash(*plan["args"])
        self.assertEqual(rejected["error"], "ACCOUNT_STASH_INVENTORY_ITEM_REQUIRED")
        self.assertEqual(self.runtime._item_instances["bank-foreign-stack"]["location"], "INVENTORY")
        self.assertEqual(rejected["bank"]["items"], [])

    def test_unimplemented_splits_swaps_and_other_bags_leave_runtime_unchanged(self):
        self.transfer(0, 61, -1, 48)
        before = self.stash_path.read_bytes()
        moves = [
            {"src_bag": -1, "src_slot": 48, "dst_bag": 0, "dst_slot": 64, "count": 1},
            {"src_bag": -1, "src_slot": 48, "dst_bag": 0, "dst_slot": 62, "count": None},
            {"src_bag": 0, "src_slot": 62, "dst_bag": -1, "dst_slot": 48, "count": None},
            {"src_bag": -1, "src_slot": 48, "dst_bag": 1, "dst_slot": 1, "count": None},
            {"src_bag": -100, "src_slot": 16, "dst_bag": -1, "dst_slot": 47, "count": None},
            {"src_bag": -1, "src_slot": 48, "dst_bag": 0, "dst_slot": 65, "count": None},
        ]
        for move in moves:
            with self.subTest(move=move), self.assertRaises(ValueError):
                self.bank.route(move, self.views.inventory_refs)
        self.assertEqual(self.stash_path.read_bytes(), before)
        self.assertEqual(self.runtime._item_instances["bank-second-stack"]["quantity"], 7)

    def test_ambiguous_snapshot_fails_closed_and_cannot_route_old_sources(self):
        self.transfer(0, 61, -1, 48)
        malformed = self.runtime.snapshot()
        malformed["bank"]["items"].append(copy.deepcopy(malformed["bank"]["items"][0]))
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            self.bank.update(malformed)
        self.assertFalse(self.bank.opened)
        self.assertEqual(self.bank.bank_refs, {})


if __name__ == "__main__":
    unittest.main()
