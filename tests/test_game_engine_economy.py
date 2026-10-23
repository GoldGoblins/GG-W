"""Regression for physical vendor stock and atomic gold transactions."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))


def _move_player_to(runtime, npc_id: str) -> None:
    index = next(
        index
        for index in runtime._npc_indices
        if runtime._npc_ids[index] == npc_id
    )
    runtime._x[0] = runtime._x[index]
    runtime._z[0] = runtime._z[index]


def _offer(snapshot: dict, definition_id: str) -> dict:
    for vendor in snapshot["economy"]["vendors"]:
        for row in vendor["offers"]["buy"]:
            if row["definition_id"] == definition_id:
                return row
    raise AssertionError(f"missing vendor offer: {definition_id}")


def main() -> int:
    from backend import game_engine_dos as dos
    from backend import game_engine_economy as economy
    from backend.game_engine_host import GameEngineRuntime

    assert dos.parse("BUY vendor.mira npc-npc-wanderer-01-pocket-00")["args"] == [
        "vendor.mira",
        "npc-npc-wanderer-01-pocket-00",
    ]
    assert dos.parse("SELL instance-01")["args"] == ["", "instance-01"]
    assert dos.parse("BUY")["ok"] is False

    runtime = GameEngineRuntime()
    try:
        _move_player_to(runtime, "npc-wanderer-01")
        before = runtime.snapshot()
        assert before["economy"]["wallet"]["gold"] == 250
        assert before["economy"]["last"] == {}
        assert before["economy"]["vendors"][0]["presence"]["available"] is True
        assert before["economy"]["vendors"][0]["needs"]["hunger"] == 0.28
        assert before["economy"]["vendors"][0]["need_thresholds"]["hunger"] == 0.92
        assert any(
            row["definition_id"] == "item.sea_salt"
            and row["target_stock"] == 2
            for row in before["economy"]["vendors"][0]["preferences"]
        )
        assert any(
            line.startswith("GOLD 250")
            for line in before["render"]["fallback"]["terminal"]["lines"]
        )
        offer = _offer(before, "item.old_boot")
        instance_id = offer["instance_id"]
        vendor_account_before = before["economy"]["vendors"][0]["gold"]

        bought = runtime.vendor_buy("vendor.mira", instance_id)
        buy_result = bought["economy_result"]
        assert buy_result["ok"] is True
        assert buy_result["action"] == "BUY"
        assert buy_result["total_price"] == 3
        assert buy_result["base_unit_price"] == 3
        assert buy_result["demand"] == 0
        assert bought["economy"]["wallet"]["gold"] == 247
        old_boot_quote = next(
            row
            for row in bought["economy"]["vendors"][0]["pricing"]
            if row["definition_id"] == "item.old_boot"
        )
        assert old_boot_quote["demand"] == 1
        assert old_boot_quote["stock"] == 0
        assert old_boot_quote["buy_price"] == 4
        assert runtime._item_instances[instance_id]["owner_id"] == "player"
        assert runtime._item_instances[instance_id]["location"] == "INVENTORY"
        assert runtime._inventory["item.old_boot"] == 1
        assert "item.old_boot" not in runtime._individual_state["individuals"]["npc-wanderer-01"]["inventory"]

        sold = runtime.vendor_sell("vendor.mira", instance_id)
        sell_result = sold["economy_result"]
        assert sell_result["ok"] is True
        assert sell_result["action"] == "SELL"
        assert sell_result["total_price"] == 1
        assert sell_result["demand"] == 1
        assert sold["economy"]["wallet"] == {
            "gold": 248,
            "earned": 1,
            "spent": 3,
            "revision": 2,
        }
        assert sold["economy"]["vendors"][0]["gold"] == vendor_account_before + 2
        assert runtime._item_instances[instance_id]["owner_id"] == "npc-wanderer-01"
        assert runtime._item_instances[instance_id]["location"] == "POCKET"
        assert runtime._inventory.get("item.old_boot", 0) == 0
        assert runtime._individual_state["individuals"]["npc-wanderer-01"]["inventory"].count("item.old_boot") == 1
        assert any(row["kind"] == "VENDOR_SELL" for row in sold["event_journal"]["events"])

        runtime._economy_state["wallet"]["gold"] = 0
        before_failed_item = copy.deepcopy(runtime._item_instances[instance_id])
        blocked = runtime.vendor_buy("vendor.mira", instance_id)
        assert blocked["error"] == "VENDOR_PLAYER_GOLD_INSUFFICIENT"
        assert runtime._item_instances[instance_id] == before_failed_item
        assert runtime._economy_state["vendors"]["vendor.mira"]["transactions"] == 2

        quest_item = runtime._item_instances["starter-island-compass"]
        quest_before = copy.deepcopy(quest_item)
        quest_blocked = runtime.vendor_sell("vendor.mira", "starter-island-compass")
        assert quest_blocked["error"] == "VENDOR_ITEM_NOT_TRADEABLE"
        assert quest_item == quest_before

        saved = runtime.save_state()
        assert saved["persistence_result"]["mode"] == "MEMORY_ONLY"
        loaded = runtime.load_state()
        assert loaded["economy"]["wallet"]["gold"] == 0
        assert loaded["economy"]["last"]["action"] == "SELL"
    finally:
        runtime.shutdown()

    dos_runtime = GameEngineRuntime()
    try:
        _move_player_to(dos_runtime, "npc-wanderer-01")
        dos_offer = _offer(dos_runtime.snapshot(), "item.old_boot")
        dispatched = dos_runtime.dos_command(
            f"BUY vendor.mira {dos_offer['instance_id']}"
        )
        assert dispatched["economy_result"]["action"] == "BUY"
        assert dispatched["economy_result"]["ok"] is True
    finally:
        dos_runtime.shutdown()

    distant_runtime = GameEngineRuntime()
    try:
        distant_runtime._x[0] = 1000.0
        distant_runtime._z[0] = 1000.0
        distant_offer = _offer(distant_runtime.snapshot(), "item.old_boot")
        distant = distant_runtime.vendor_buy(
            "vendor.mira",
            distant_offer["instance_id"],
        )
        assert distant["error"] == "VENDOR_NPC_UNAVAILABLE"
    finally:
        distant_runtime.shutdown()

    restock_runtime = GameEngineRuntime()
    try:
        initial = restock_runtime.snapshot()
        initial_vendor = initial["economy"]["vendors"][0]
        assert initial_vendor["restock"]["successful"] == 0
        assert initial_vendor["restock"]["attempts"] == 0
        with restock_runtime._lock:
            # Place the fixed-step clock just before the authored 12-second
            # interval so the next 2 Hz economy pass is the due boundary.
            restock_runtime._tick = 719
            restock_runtime._sim_time = 11.99
        restocked = restock_runtime.step()
        restock_vendor = restocked["economy"]["vendors"][0]
        assert restock_vendor["restock"]["successful"] == 1
        assert restock_vendor["restock"]["attempts"] == 1
        assert restock_vendor["decision"]["action"] == "RESTOCK"
        assert restock_vendor["decision"]["selected_definition_id"] == "item.sea_salt"
        assert restock_vendor["restock"]["last"]["ok"] is True
        assert restock_vendor["restock"]["last"]["table_id"] == "loot.goblin_pocket"
        created = [
            row
            for row in restock_runtime._item_instances.values()
            if row.get("origin") == "VENDOR_RESTOCK"
        ]
        assert len(created) == 1
        assert created[0]["location"] == "POCKET"
        assert created[0]["owner_id"] == "npc-wanderer-01"
        assert created[0]["roll_table_id"] == "loot.goblin_pocket"
        assert isinstance(created[0]["seed"], int)
        assert any(
            row["kind"] == "VENDOR_RESTOCK"
            for row in restocked["event_journal"]["events"]
        )
        assert any(
            row["kind"] == "VENDOR_DECISION"
            and row["payload"]["decision"]["selected_definition_id"] == "item.sea_salt"
            for row in restocked["event_journal"]["events"]
        )
        saved_restock = restock_runtime.save_state()
        assert saved_restock["persistence_result"]["mode"] == "MEMORY_ONLY"
        loaded_restock = restock_runtime.load_state()
        loaded_vendor = loaded_restock["economy"]["vendors"][0]
        assert loaded_vendor["restock"]["successful"] == 1
        assert loaded_vendor["restock"]["last"]["status"] == "RESTOCKED"
        assert loaded_vendor["decision"]["selected_definition_id"] == "item.sea_salt"
        assert any(
            row.get("origin") == "VENDOR_RESTOCK"
            for row in restock_runtime._item_instances.values()
        )
    finally:
        restock_runtime.shutdown()

    needs_runtime = GameEngineRuntime()
    try:
        with needs_runtime._lock:
            needs_runtime._individual_state["individuals"]["npc-wanderer-01"]["needs"][
                "hunger"
            ] = 0.99
            needs_runtime._tick = 719
            needs_runtime._sim_time = 11.99
        held = needs_runtime.step()
        held_vendor = held["economy"]["vendors"][0]
        assert held_vendor["decision"]["action"] == "HOLD"
        assert held_vendor["decision"]["reason"] == "NEEDS_HUNGER"
        assert held_vendor["restock"]["successful"] == 0
        assert held_vendor["restock"]["attempts"] == 0
        assert held_vendor["decision_count"] == 1
        assert held_vendor["hold_count"] == 1
        assert any(
            row["kind"] == "VENDOR_DECISION"
            and row["payload"]["decision"]["reason"] == "NEEDS_HUNGER"
            for row in held["event_journal"]["events"]
        )
        saved_hold = needs_runtime.save_state()
        assert saved_hold["persistence_result"]["mode"] == "MEMORY_ONLY"
        loaded_hold = needs_runtime.load_state()
        assert loaded_hold["economy"]["vendors"][0]["decision"]["reason"] == "NEEDS_HUNGER"
    finally:
        needs_runtime.shutdown()

    catalog = economy.starter_vendors()
    account = economy.new_state(catalog)["vendors"]["vendor.mira"]
    salt_preference = economy.preference_for(catalog["vendor.mira"], "item.sea_salt")
    assert salt_preference == {
        "priority": 0.9,
        "target_stock": 2,
        "buy_bias": -0.04,
        "sell_premium": 0.18,
    }
    preferred_candidate = economy.choose_restock_candidate(
        catalog["vendor.mira"],
        [
            {"definition_id": "item.old_boot", "seed": 1},
            {"definition_id": "item.sea_salt", "seed": 2},
        ],
        {"item.old_boot": 1, "item.sea_salt": 0},
    )
    assert preferred_candidate["definition_id"] == "item.sea_salt"
    baseline = economy.dynamic_prices(
        catalog["vendor.mira"], account, "item.old_boot", 1
    )
    economy.record_market_transaction(account, "item.old_boot", "BUY", 1.0)
    pressured = economy.dynamic_prices(
        catalog["vendor.mira"], account, "item.old_boot", 0
    )
    assert baseline["buy"] == 3
    assert pressured["buy"] == 4
    plan = economy.restock_plan(catalog["vendor.mira"], account, 2, 12.0)
    assert plan["due"] is True
    assert plan["seed"] == economy.restock_plan(
        catalog["vendor.mira"], account, 2, 12.0
    )["seed"]

    print("GAME_ENGINE_ECONOMY_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
