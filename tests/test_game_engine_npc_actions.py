"""Regression for bounded NPC world-use state transitions."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))


def main() -> int:
    from backend.game_engine_host import GameEngineRuntime

    runtime = GameEngineRuntime()
    try:
        people = runtime._individual_state["individuals"]
        wanderer = people["npc-wanderer-01"]
        wanderer["activity"] = "GATHER"
        wanderer["action"] = "GATHER"
        wanderer["target"] = {
            "id": "ground-old-boot-01",
            "kind": "TRASH",
            "x": -1.7,
            "z": 1.9,
        }
        wanderer_index = next(
            index
            for index in runtime._npc_indices
            if runtime._npc_ids[index] == "npc-wanderer-01"
        )
        runtime._x[wanderer_index] = -1.7
        runtime._z[wanderer_index] = 1.9
        assert runtime._execute_npc_world_action_locked(
            "npc-wanderer-01",
            wanderer,
            (-1.7, 1.9),
        ) is True
        boot = runtime._item_instances["ground-old-boot-01"]
        assert boot["location"] == "POCKET"
        assert boot["owner_id"] == "npc-wanderer-01"
        assert "item.old_boot" in wanderer["inventory"]

        carrier = people["ambient-carrier-01"]
        carrier["activity"] = "HAUL"
        carrier["action"] = "HAUL"
        carrier["target"] = {
            "id": "container-supply-crate-01",
            "kind": "CONTAINER",
            "x": 2.75,
            "z": 1.35,
        }
        assert runtime._execute_npc_world_action_locked(
            "ambient-carrier-01",
            carrier,
            (2.75, 1.35),
        ) is True
        hauled = [
            row
            for row in runtime._item_instances.values()
            if row.get("location") == "POCKET"
            and row.get("owner_id") == "ambient-carrier-01"
        ]
        assert len(hauled) == 3
        assert any(row["instance_id"] in {
            "crate-tideguard-jacket-01",
            "crate-sunken-crown-01",
        } for row in hauled)

        crafter = people["npc-guardian-01"]
        crafter["activity"] = "CRAFT"
        crafter["action"] = "CRAFT"
        crafter["target"] = {
            "id": "station.campfire",
            "kind": "STATION",
            "x": -1.8,
            "z": 1.1,
        }
        crafter["inventory"] = [
            "material.fresh_water",
            "item.sea_salt",
            "item.sun_herb",
        ]
        assert runtime._execute_npc_world_action_locked(
            "npc-guardian-01",
            crafter,
            (-1.8, 1.1),
        ) is True
        assert "item.field_ration" in crafter["inventory"]
        assert "material.fresh_water" not in crafter["inventory"]
        assert "item.sea_salt" not in crafter["inventory"]
        assert "item.sun_herb" not in crafter["inventory"]

        rows = runtime.snapshot()["event_journal"]["events"]
        action_rows = [row for row in rows if row["kind"] == "NPC_WORLD_ACTION"]
        assert {row["subject_id"] for row in action_rows} >= {"GATHER", "HAUL", "CRAFT"}
        assert all(row["actor_id"] for row in action_rows)
    finally:
        runtime.shutdown()

    print("GAME_ENGINE_NPC_ACTIONS_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
