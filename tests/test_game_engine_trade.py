"""Regression for atomic player/NPC item-instance trade."""

from __future__ import annotations

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


def _npc_instance(runtime, npc_id: str, definition_id: str) -> dict:
    rows = [
        row
        for row in runtime._item_instances.values()
        if isinstance(row, dict)
        and row.get("owner_id") == npc_id
        and row.get("location") == "POCKET"
        and row.get("definition_id") == definition_id
    ]
    assert rows
    return sorted(rows, key=lambda row: str(row.get("instance_id")))[0]


def main() -> int:
    from backend import game_engine_dos as dos
    from backend.game_engine_host import GameEngineRuntime

    assert dos.parse("TRADE starter-sea-salt npc-npc-wanderer-01-pocket-00")["args"] == [
        "",
        "starter-sea-salt",
        "npc-npc-wanderer-01-pocket-00",
    ]
    assert dos.parse("TRADE give")["ok"] is False

    runtime = GameEngineRuntime()
    try:
        people = runtime._individual_state["individuals"]
        for identity_id, person in people.items():
            for field, location in (("inventory", "POCKET"), ("equipment", "EQUIPPED")):
                references = person.get(field, [])
                matching = [
                    row
                    for row in runtime._item_instances.values()
                    if isinstance(row, dict)
                    and row.get("owner_id") == identity_id
                    and row.get("location") == location
                ]
                for definition_id in set(str(value) for value in references):
                    assert sum(
                        1 for row in matching if row.get("definition_id") == definition_id
                    ) >= sum(1 for value in references if str(value) == definition_id)

        _move_player_to(runtime, "npc-wanderer-01")
        npc_item = _npc_instance(runtime, "npc-wanderer-01", "item.old_boot")
        player_item = runtime._item_instances["starter-sea-salt"]
        before_player_counts = dict(runtime._inventory)
        before_npc_refs = list(people["npc-wanderer-01"]["inventory"])
        traded = runtime.trade_items(
            "npc-wanderer-01",
            "starter-sea-salt",
            str(npc_item["instance_id"]),
        )
        assert "error" not in traded
        result = traded["trade_result"]
        assert result["action"] == "TRADE"
        assert result["policy"] == "ITEM_FOR_ITEM_WHOLE_INSTANCE"
        assert player_item["location"] == "POCKET"
        assert player_item["owner_id"] == "npc-wanderer-01"
        assert npc_item["location"] == "INVENTORY"
        assert npc_item["owner_id"] == "player"
        assert runtime._inventory.get("item.sea_salt", 0) == before_player_counts["item.sea_salt"] - 1
        assert runtime._inventory.get("item.old_boot", 0) == 1
        assert people["npc-wanderer-01"]["inventory"].count("item.old_boot") == before_npc_refs.count("item.old_boot") - 1
        assert people["npc-wanderer-01"]["inventory"].count("item.sea_salt") == before_npc_refs.count("item.sea_salt") + 1
        assert traded["trade"]["last"]["npc_id"] == "npc-wanderer-01"
        assert any(row["kind"] == "NPC_TRADE" for row in traded["event_journal"]["events"])

        saved = runtime.save_state()
        assert saved["persistence_result"]["mode"] == "MEMORY_ONLY"
        loaded = runtime.load_state()
        assert loaded["trade"]["last"]["npc_id"] == "npc-wanderer-01"
        assert loaded["trade"]["last"]["receive"]["owner_id"] == "player"
        assert runtime._item_instances["starter-sea-salt"]["owner_id"] == "npc-wanderer-01"
        assert runtime._item_instances[str(npc_item["instance_id"])]["owner_id"] == "player"
    finally:
        runtime.shutdown()

    blocked_runtime = GameEngineRuntime()
    try:
        _move_player_to(blocked_runtime, "npc-wanderer-01")
        before = {
            key: (row.get("location"), row.get("owner_id"))
            for key, row in blocked_runtime._item_instances.items()
        }
        blocked = blocked_runtime.trade_items(
            "npc-wanderer-01",
            "starter-sea-salt",
            "npc-pocket-totem-01",
        )
        assert blocked["error"] == "TRADE_QUEST_FORBIDDEN"
        assert {
            key: (row.get("location"), row.get("owner_id"))
            for key, row in blocked_runtime._item_instances.items()
        } == before
    finally:
        blocked_runtime.shutdown()

    distant_runtime = GameEngineRuntime()
    try:
        before = dict(distant_runtime._inventory)
        distant = distant_runtime.trade_items(
            "npc-wanderer-01",
            "starter-sea-salt",
            "npc-npc-wanderer-01-pocket-00",
        )
        assert distant["error"] == "NPC_TRADE_NPC_UNAVAILABLE"
        assert distant_runtime._inventory == before

        _move_player_to(distant_runtime, "npc-wanderer-01")
        dos_result = distant_runtime.dos_command(
            "TRADE starter-sea-salt npc-npc-wanderer-01-pocket-00"
        )
        assert dos_result["dos_command"]["ok"] is True
        assert dos_result["trade_result"]["action"] == "TRADE"
    finally:
        distant_runtime.shutdown()

    print("GAME_ENGINE_TRADE_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
