"""Regression for the first authoritative living-world gameplay loop."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))


def _place_player_near(runtime, identity_id: str, distance: float = 1.0) -> None:
    with runtime._lock:
        index = runtime._npc_index_for_id_locked(identity_id)
        assert index is not None
        runtime._x[0] = runtime._x[index] + distance
        runtime._z[0] = runtime._z[index]
        runtime._y[0] = runtime._terrain_height_locked(
            runtime._x[0], runtime._z[0]
        ) + 0.65
        runtime._vx[0] = runtime._vy[0] = runtime._vz[0] = 0.0


def _actor(snapshot: dict, actor_id: str) -> dict:
    return next(
        row
        for row in snapshot["combat"]["actors"]
        if row.get("id") == actor_id
    )


def _agent(snapshot: dict, identity_id: str) -> dict:
    return next(
        row
        for row in snapshot["npc"]["agents"]
        if row.get("id") == identity_id
    )


def main() -> int:
    from backend import game_engine_combat as combat
    from backend import game_engine_content as content
    from backend import game_engine_factions as factions
    from backend import game_engine_quests as quests
    from backend import game_engine_schedules as schedules
    from backend.game_engine_host import GameEngineRuntime

    # The isolated contracts remain deterministic and bounded before the host
    # binds them to the physical entity/item pools.
    schedule = schedules.schedule_for("SCAVENGER")
    assert schedules.active_slot(schedule, 15.0)["activity"] == "INSPECT_LOOT"
    faction_state = factions.new_state(
        [{"id": "npc-test", "archetype": "GUARDIAN"}]
    )
    person_change = factions.adjust_person(
        faction_state,
        "npc-test",
        -60,
        source="TEST",
        sim_time=1.0,
    )
    assert person_change["disposition"] == "HOSTILE"
    quest_catalog = quests.normalized_catalog()
    quest_state = quests.new_state()
    accepted, _ = quests.accept(
        quest_state,
        quest_catalog,
        "quest.shoreline-first",
        0.0,
    )
    assert accepted is True
    progress = quests.record_event(
        quest_state,
        quest_catalog,
        {"kind": "DEFEAT", "target_id": "npc-critter-01"},
        2.0,
    )
    assert progress["changed"] is True
    claimed, claim_result = quests.claim(
        quest_state,
        quest_catalog,
        "quest.shoreline-first",
        3.0,
    )
    assert claimed is True
    assert claim_result["rewards"]["gold"] == 25

    combat_state = combat.new_state()
    player_profile = combat.profile(
        {
            "level": 1,
            "base_stats": {"might": 8, "finesse": 5, "grit": 5},
            "gear_stats": {"damage": 4},
        },
        kind="PLAYER",
        actor_id="player",
    )
    target_profile = combat.profile(
        {
            "level": 1,
            "base_stats": {"might": 5, "finesse": 5, "grit": 5},
        },
        actor_id="target",
    )
    hit = combat.resolve_attack(
        combat_state,
        attacker_id="player",
        defender_id="target",
        attacker_profile=player_profile,
        defender_profile=target_profile,
        sim_time=0.0,
        seed=7,
    )
    assert hit["ok"] is True
    cooldown = combat.resolve_attack(
        combat_state,
        attacker_id="player",
        defender_id="target",
        attacker_profile=player_profile,
        defender_profile=target_profile,
        sim_time=0.1,
        seed=8,
    )
    assert cooldown["status"] == "COOLDOWN"

    runtime = GameEngineRuntime()
    try:
        initial = runtime.snapshot()
        assert initial["combat"]["schema"] == combat.SCHEMA
        assert initial["quests"]["schema"] == quests.SCHEMA
        assert initial["factions"]["schema"] == factions.SCHEMA
        assert initial["render"]["fallback"]["quests"]["schema"] == quests.SCHEMA
        assert _actor(initial, "player")["alive"] is True
        assert _agent(initial, "npc-critter-01")["individual"]["schedule"]["schema"] == schedules.SCHEMA

        _place_player_near(runtime, "npc-guardian-01")
        accepted_view = runtime.accept_quest("quest.shoreline-first")
        assert accepted_view["quest_result"]["progress"]["status"] == "ACTIVE"

        _place_player_near(runtime, "npc-critter-01")
        last_attack = {}
        for _ in range(16):
            with runtime._lock:
                runtime._sim_time += 1.0
            last_attack = runtime.attack("npc-critter-01")
            if last_attack.get("combat_result", {}).get("defeated"):
                break
        assert last_attack["combat_result"]["status"] == "DEFEATED"
        assert last_attack["combat_result"]["defeat"]["loot"]["created"] is True

        defeated = runtime.snapshot()
        assert _actor(defeated, "npc-critter-01")["alive"] is False
        assert _agent(defeated, "npc-critter-01")["state"] == "DEAD"
        assert defeated["quests"]["ready"] == 1
        assert any(
            row.get("origin") == "COMBAT_DROP"
            and row.get("location") == "GROUND"
            for row in runtime._item_instances.values()
        )
        critter_relation = next(
            row
            for row in defeated["factions"]["people"]
            if row.get("identity_id") == "npc-critter-01"
        )
        assert critter_relation["disposition"] == "HOSTILE"
        assert defeated["progression"]["xp"] > 0

        claimed_view = runtime.claim_quest("quest.shoreline-first")
        assert claimed_view["quest_result"]["rewards"]["gold"] == 25
        assert "quest.shoreline-first" in claimed_view["quests"]["completed"]
        assert any(
            row.get("origin") == "QUEST_REWARD"
            and row.get("definition_id") == "item.moon_shard"
            for row in runtime._item_instances.values()
        )
        shorewarden = next(
            row
            for row in claimed_view["factions"]["factions"]
            if row.get("id") == "SHOREWARDENS"
        )
        assert shorewarden["player_standing"] == 12

        saved = runtime.save_state()
        saved_time = saved["simulation"]["time_s"]
        runtime.reset()
        loaded = runtime.load_state()
        assert loaded["simulation"]["time_s"] == saved_time
        assert "quest.shoreline-first" in loaded["quests"]["completed"]
        assert _actor(loaded, "npc-critter-01")["alive"] is False
        assert _agent(loaded, "npc-critter-01")["state"] == "DEAD"

        dos = runtime.set_presentation_mode("DOS_2D")
        assert dos["render"]["presentation"]["mode"] == "DOS_2D"
        assert dos["render"]["fallback"]["quests"]["completed"] == dos["quests"]["completed"]
        assert dos["render"]["fallback"]["factions"]["schema"] == factions.SCHEMA
        assert _actor(dos, "npc-critter-01")["alive"] is False
        assert json.dumps(dos["items"], sort_keys=True) == json.dumps(
            loaded["items"], sort_keys=True
        )
    finally:
        runtime.shutdown()

    print("GAME_ENGINE_LIVING_WORLD_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
