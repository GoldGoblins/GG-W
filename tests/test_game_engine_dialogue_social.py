"""Regression for authored dialogue, durable NPC relations and population promotion."""

from __future__ import annotations

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


def main() -> int:
    from backend import game_engine_dialogue as dialogue
    from backend import game_engine_quests as quests
    from backend import game_engine_social as social
    from backend.game_engine_host import GameEngineRuntime

    catalog = dialogue.normalized_catalog()
    state = dialogue.new_state()
    started, start_result = dialogue.start(state, catalog, "npc-guardian-01", 0.0)
    assert started is True
    assert start_result["node"]["speaker"] == "Brann Tidewatch"
    chosen, choice_result = dialogue.choose(
        state,
        catalog,
        "npc-guardian-01",
        "shoreline-duty",
        1.0,
    )
    assert chosen is True
    assert choice_result["effects"][0]["kind"] == "ACCEPT_QUEST"

    quest_state = quests.new_state()
    quest_catalog = quests.normalized_catalog()
    accepted, _ = quests.accept(
        quest_state,
        quest_catalog,
        "quest.shoreline-report",
        0.0,
    )
    assert accepted is False
    assert _ == {"error": "QUEST_PREREQUISITES_MISSING", "quest_id": "quest.shoreline-report", "missing": ["quest.shoreline-first"]}

    people = {
        "npc-a": {"id": "npc-a", "personality": ["SOCIABLE"], "faction_id": "WAYFARERS"},
        "npc-b": {"id": "npc-b", "personality": ["SOCIABLE"], "faction_id": "WAYFARERS"},
    }
    social_state = social.new_state()
    pairs = social.nearby_pairs(
        people,
        {"npc-a": (0.0, 0.0), "npc-b": (1.0, 0.0)},
        social_state,
        2.0,
    )
    assert pairs and pairs[0]["kind"] == "CONVERSE"
    relation = social.record(social_state, pairs[0], 2.0, outcome="CONVERSATION")
    assert relation["meetings"] == 1
    assert social.view(social_state)["relationship_count"] == 1

    runtime = GameEngineRuntime()
    try:
        # Force two authored actors into a valid hostile encounter to verify
        # that the host commits combat through the real actor resolver.
        with runtime._lock:
            guardian_index = runtime._npc_index_for_id_locked("npc-guardian-01")
            critter_index = runtime._npc_index_for_id_locked("npc-critter-01")
            assert guardian_index is not None and critter_index is not None
            runtime._x[guardian_index] = 0.0
            runtime._z[guardian_index] = 0.0
            runtime._x[critter_index] = 1.0
            runtime._z[critter_index] = 0.0
            runtime._individual_state["individuals"]["npc-guardian-01"]["personality"] = [
                "AGGRESSIVE"
            ]
            runtime._tick = 30
            runtime._sim_time = 1.0
            runtime._tick_social_locked()
        conflict_snapshot = runtime.snapshot()
        assert any(
            row.get("kind") == "CONFLICT"
            for row in conflict_snapshot["social"]["history"]
        )
        assert any(
            row.get("kind") == "NPC_COMBAT_ATTACK"
            for row in conflict_snapshot["event_journal"]["events"]
        )
        runtime.reset()

        _place_player_near(runtime, "npc-guardian-01")
        interaction = runtime.npc_interact()
        assert interaction["npc_interaction_result"]["dialogue"]["node"]["choices"]
        choice = runtime.talk_npc("npc-guardian-01", "shoreline-duty")
        assert choice["dialogue_result"]["choice_id"] == "shoreline-duty"
        assert choice["quests"]["active_count"] == 1
        assert any(
            row.get("kind") == "DIALOGUE_CHOICE"
            for row in choice["event_journal"]["events"]
        )
        with runtime._lock:
            runtime._record_quest_event_locked(
                {"kind": "DEFEAT", "target_id": "npc-critter-01"}
            )
        first_claim = runtime.claim_quest("quest.shoreline-first")
        assert "quest.shoreline-first" in first_claim["quests"]["completed"]
        runtime.npc_interact()
        report = runtime.talk_npc("npc-guardian-01", "shoreline-report")
        report_progress = next(
            row
            for row in report["quests"]["active"]
            if row.get("id") == "quest.shoreline-report"
        )
        assert report_progress["progress"]["status"] == "READY"

        with runtime._lock:
            runtime._running = True
            for _ in range(720):
                runtime._tick_locked(1.0 / 60.0)
            runtime._running = False
        promoted = runtime.snapshot()
        assert promoted["living_world"]["promoted_count"] == 1
        assert promoted["simulation"]["active_npcs"] == 7
        # Promotion replaces one ambient presentation with one physical
        # presentation. Saved scenery can grow without changing that rule.
        rows=promoted['render']['entities']
        assert promoted['simulation']['render_entity_count']==len(rows)<=96
        assert len({row['id'] for row in rows})==len(rows)
        for identity in promoted['living_world']['promoted_ids']:
            assert sum(row['id']==identity or (row.get('individual') or {}).get('id')==identity for row in rows)==1
        assert promoted["social"]["relationship_count"] >= 1

        saved = runtime.save_state()
        saved_ids = saved["living_world"]["promoted_ids"]
        assert saved_ids
        runtime.reset()
        loaded = runtime.load_state()
        assert loaded["living_world"]["promoted_ids"] == saved_ids
        assert loaded["dialogue"]["active"]["npc_id"] == "npc-guardian-01"
        assert loaded["social"]["relationship_count"] >= 1
    finally:
        runtime.shutdown()

    print("GAME_ENGINE_DIALOGUE_SOCIAL_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
