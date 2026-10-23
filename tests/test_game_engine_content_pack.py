"""Regression for the Tidefall authored content page and world events."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))


def main() -> int:
    from backend import game_engine_assets as assets
    from backend import game_engine_content as content
    from backend import game_engine_host as host

    base = content.starter_content()
    assert len(base["items"]) == 12
    pack = content.available_content_packs()["pack.tidefall-frontier"]
    assert len(pack["items"]) >= 20
    assert len(pack["npc_individuals"]) >= 9
    assert len(pack["world_events"]) == 4
    for asset_id, spec in pack["asset_bindings"].items():
        inspected = assets.inspect_asset(spec["source"], asset_id)
        assert inspected["status"] == "READY"
        assert inspected["mode"] == "AUTHORED_STATIC"

    runtime = host._RUNTIME
    host.reset()
    snapshot = host.activate_content_pack("pack.tidefall-frontier")
    assert snapshot["content_pack_result"]["ok"] is True
    assert snapshot["content_packs"]["active"] == ["pack.tidefall-frontier"]
    assert snapshot["content"]["items"] == 32
    assert snapshot["content"]["npc_individuals"] == 16
    assert snapshot["content"]["ambient_life"] == 8
    assert snapshot["content"]["quests"] == 9
    assert snapshot["content"]["world_events"] == 4
    assert snapshot["content"]["asset_bindings"] == 5
    assert any(
        row.get("origin") == "CONTENT_PACK"
        for row in snapshot["items"]["ground"]
    )

    with runtime._lock:
        runtime._sim_time = 8.0
    snapshot = host.step()
    assert snapshot["world_events"]["active_count"] == 1
    assert snapshot["world_events"]["active"][0]["id"] == "event.tidegate-siege"
    assert any(
        row.get("origin") == "WORLD_EVENT"
        and row.get("definition_id") == "item.tidegate_key"
        for row in snapshot["items"]["ground"]
    )

    saved = host.save_state()
    assert saved["persistence_result"]["bytes"] > 0
    loaded = host.load_state()
    assert loaded["content_packs"]["active"] == ["pack.tidefall-frontier"]
    assert loaded["world_events"]["active_count"] == 1
    assert loaded["content"]["items"] == 32
    assert "PACK" in loaded["dos"]["allowed"]
    assert "EVENTS" in loaded["dos"]["allowed"]
    host.shutdown()
    print("GAME_ENGINE_CONTENT_PACK_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
