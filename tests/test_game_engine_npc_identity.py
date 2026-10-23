"""Regression tests for durable NPC identity and bounded world use."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))


def main() -> int:
    from backend import game_engine_content as content
    from backend import game_engine_gear as gear
    from backend import game_engine_npc_identity as identity

    people_catalog = identity.catalog_from_content(content.starter_content())
    assert len(people_catalog) == 7
    assert len({row["name"] for row in people_catalog.values()}) == 7
    state = identity.runtime_state(people_catalog)
    assert state["schema"] == identity.SCHEMA

    stations = gear.world_stations(gear.starter_tables())
    world_items = [
        {
            "id": "ground-cache",
            "kind": "CONTAINER",
            "x": 2.75,
            "z": 1.35,
            "tags": ["CONTAINER", "LOOT"],
        }
    ]
    identity.tick(
        state,
        0.5,
        player_x=0.0,
        player_z=0.0,
        world_items=world_items,
        stations=stations,
        active_ids=["npc-wanderer-01", "npc-guardian-01"],
    )
    wanderer = identity.view(state, "npc-wanderer-01")
    assert wanderer["action"] in identity.ACTIVITIES
    assert wanderer["target"]["id"] == "ground-cache"
    assert len(wanderer["memory"]) >= 1
    assert all(0.0 <= value <= 1.0 for value in wanderer["needs"].values())

    for step in range(1, 80):
        identity.tick(
            state,
            0.5 + step * 0.5,
            player_x=30.0,
            player_z=30.0,
            world_items=world_items,
            stations=stations,
        )
    view = identity.view(state, "npc-wanderer-01")
    assert len(view["memory"]) <= identity.MAX_MEMORY
    assert len(view["inventory"]) <= identity.MAX_CARRIED_ITEMS
    assert len(view["goals"]) <= identity.MAX_GOALS
    overview = identity.build_view(state)
    assert overview["population"] == 7
    assert overview["unique_names"] == 7
    assert overview["memory_events"] >= 1

    restored = identity.restore_state(state, people_catalog)
    assert identity.view(restored, "npc-wanderer-01") == view
    created = identity.ensure_individual(
        restored,
        "editor-npc-01",
        archetype="WANDERER",
        role="WANDERER",
        home={"x": 1.0, "z": 2.0},
    )
    assert created["name"].startswith("Newcomer")
    assert identity.target_for(restored, "missing-person") is None

    print("GAME_ENGINE_NPC_IDENTITY_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

