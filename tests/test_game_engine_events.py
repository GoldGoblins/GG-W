"""Regression tests for authoritative GAME ENGINE event journaling."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))


def main() -> int:
    from backend import game_engine_events as events
    from backend.game_engine_host import GameEngineRuntime

    journal = events.new_journal()
    payload = {"z": [index for index in range(40)], "nested": {"value": "kept"}}
    first = events.append(
        journal,
        "loot",
        tick=12,
        sim_time=0.2,
        actor_id="player",
        subject_id="loot-0001",
        target_id="loot.coastal_cache",
        text="Loot acquired.",
        payload=payload,
    )
    payload["z"].append(999)
    assert first["sequence"] == 1
    assert first["kind"] == "LOOT"
    assert first["payload"]["z"][-1] == 15
    assert first["payload"]["nested"]["value"] == "kept"

    for index in range(events.MAX_EVENTS + 12):
        events.append(journal, "TICK", tick=index, payload={"index": index})
    view = events.view(journal, limit=events.MAX_EVENTS)
    assert view["schema"] == events.SCHEMA
    assert view["count"] == events.MAX_EVENTS
    sequences = [row["sequence"] for row in view["events"]]
    assert sequences == sorted(sequences)
    assert len(set(sequences)) == len(sequences)
    assert view["next_sequence"] == sequences[-1] + 1
    view["events"].clear()
    assert journal["events"]

    restored = events.restore(
        {
            "schema": events.SCHEMA,
            "next_sequence": 2,
            "events": [
                {"sequence": 9, "kind": "A"},
                {"sequence": 9, "kind": "B"},
                {"sequence": "bad", "kind": "C"},
            ],
        }
    )
    restored_sequences = [row["sequence"] for row in restored["events"]]
    assert restored_sequences == [9, 10, 11]
    assert restored["next_sequence"] == 12

    runtime = GameEngineRuntime()
    try:
        initial = runtime.snapshot()
        assert initial["event_journal"]["schema"] == events.SCHEMA
        assert initial["event_journal"]["events"][0]["kind"] == "WORLD_RESET"
        for _ in range(30):
            runtime.step()
        runtime.claim_loot(321)
        runtime.socket_item("starter-iron-saber", "rune.tir")
        runtime.enchant_gear("starter-iron-saber", "enchant.aquatic_edge")
        runtime.craft_gear("recipe.fiber_rope", "station.workbench")
        current = runtime.snapshot()
        rows = current["event_journal"]["events"]
        kinds = {row["kind"] for row in rows}
        assert {"LOOT", "SOCKET", "GEAR_ENCHANT", "GEAR_CRAFT"}.issubset(kinds)
        assert all(
            row["sequence"] < following["sequence"]
            for row, following in zip(rows, rows[1:])
        )
        assert any("LOOT" in line for line in current["render"]["fallback"]["terminal"]["lines"])
        assert any(
            row["actor_id"] == "player" and row["subject_id"] == "loot-0001"
            for row in rows
            if row["kind"] == "LOOT"
        )

        saved = runtime.save_state()
        saved_sequences = [
            row["sequence"] for row in saved["event_journal"]["events"]
        ]
        assert saved["event_journal"]["events"][-1]["kind"] == "SAVE"
        runtime.reset()
        loaded = runtime.load_state()
        loaded_rows = loaded["event_journal"]["events"]
        assert loaded_rows[-1]["kind"] == "LOAD"
        assert loaded_rows[-2]["kind"] == "SAVE"
        assert [row["sequence"] for row in loaded_rows[:-1]] == saved_sequences
    finally:
        runtime.shutdown()

    print("GAME_ENGINE_EVENTS_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
