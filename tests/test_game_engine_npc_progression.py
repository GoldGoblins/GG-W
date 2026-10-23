"""Regression tests for NPC levels, power evaluation and autonomous builds."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))


def main() -> int:
    from backend import game_engine_content as content
    from backend import game_engine_fallback as fallback
    from backend import game_engine_gear as gear
    from backend import game_engine_items as items
    from backend import game_engine_npc_identity as npc_identity
    from backend import game_engine_npc_progression as npc_progression
    from backend.game_engine_host import GameEngineRuntime

    state = npc_progression.starter_state(
        "npc-test",
        role="GUARDIAN",
        occupation="WARDEN",
    )
    assert state["spec"] == "WARDEN"
    assert state["level"] == 1
    before_stats = dict(state["base_stats"])
    first_level = npc_progression.grant_xp(
        state,
        100,
        source="TEST_ACTION",
        sim_time=2.0,
    )
    assert first_level["level"] == 2
    assert first_level["level_ups"] == 1
    assert sum(state["base_stats"].values()) > sum(before_stats.values())
    assert state["talents"]["tidewalker"] == 2
    assert state["last_gain"]["source"] == "TEST_ACTION"

    catalog = items.catalog_from_content(content.starter_content())
    tables = catalog["gear"]
    saber = items.make_instance(
        catalog,
        "npc-test-saber",
        "item.iron_saber",
        location="EQUIPPED",
        owner_id="npc-test",
        equipped_slot="MAIN_HAND",
    )
    for insertable_id in ("rune.tir", "rune.ort", "rune.tal"):
        ok, _ = gear.insert_socket(
            saber["gear"],
            insertable_id,
            tables,
        )
        assert ok is True
    before_score = npc_progression.item_score(saber)
    refreshed = npc_progression.recalculate(state, [saber], source="TEST_GEAR", sim_time=3.0)
    assert refreshed["changed"] is True
    assert state["gear_score"] == before_score
    assert state["derived_stats"]["damage"] > 0
    assert state["power_score"] > 0

    action = {
        "last_action": "INSPECT_LOOT",
        "target_id": "npc-test-saber",
        "status": "EQUIPPED",
        "count": 1,
    }
    gained = npc_progression.apply_world_action(
        state,
        action,
        payload={"definition_id": "item.iron_saber", "gear_upgrade": True},
        sim_time=4.0,
    )
    assert gained["xp_gained"] == 12
    duplicate = npc_progression.apply_world_action(state, action, sim_time=5.0)
    assert duplicate["processed"] is False

    state["level"] = npc_progression.MAX_LEVEL
    state["xp"] = 0
    state["paragon"] = npc_progression.ASCENSION_PARAGON_COST
    ascended, ascension = npc_progression.ascend(state, sim_time=6.0)
    assert ascended is True
    assert ascension["ascension"] == 1
    assert state["level"] == 1
    assert state["base_stats"]["grit"] >= before_stats["grit"] + npc_progression.ASCENSION_STAT_BONUS

    dos_view = fallback.build_view(
        [
            {
                "id": "e-npc-test",
                "kind": "NPC",
                "x": 1,
                "z": 2,
                "individual": {
                    "name": "Mira Saltwake",
                    "progression": {
                        "level": 7,
                        "spec": "EXPLORER",
                        "ascension": 1,
                        "gear_score": 123.5,
                        "power_score": 456.7,
                    },
                },
            }
        ]
    )
    assert dos_view["entities"][0]["label"] == "Mira Saltwake L7 P457"
    assert dos_view["entities"][0]["progression"]["gear_score"] == 123.5

    runtime = GameEngineRuntime()
    try:
        people = runtime._individual_state["individuals"]
        mira = people["npc-wanderer-01"]
        starting_power = mira["progression"]["power_score"]
        mira["home"] = {"x": 2.75, "y": 0.0, "z": 1.35}
        mira["last_update_s"] = 0.0
        npc_identity.tick(
            runtime._individual_state,
            1.0,
            player_x=100.0,
            player_z=100.0,
            world_items=runtime._world_use_rows_locked(),
            stations=[],
            active_ids=["npc-wanderer-01"],
        )
        assert mira["activity"] == "INSPECT_LOOT"
        assert mira["target"]["id"] == "crate-sunken-crown-01"
        mira["activity"] = "INSPECT_LOOT"
        mira["action"] = "INSPECT_LOOT"
        mira["target"] = {
            "id": "crate-sunken-crown-01",
            "kind": "ARMOR",
            "x": 2.75,
            "z": 1.35,
        }
        assert runtime._execute_npc_world_action_locked(
            "npc-wanderer-01",
            mira,
            (2.75, 1.35),
        ) is True
        crown = runtime._item_instances["crate-sunken-crown-01"]
        assert crown["location"] == "EQUIPPED"
        assert crown["owner_id"] == "npc-wanderer-01"
        assert "item.sunken_crown" in mira["equipment"]
        assert mira["progression"]["gear_score"] > 0
        assert mira["progression"]["power_score"] > starting_power
        assert mira["progression"]["last_gain"]["amount"] == 12
        assert any(
            row["kind"] == "NPC_POWER_CHANGED"
            for row in runtime.snapshot()["event_journal"]["events"]
        )

        vendor_gear = items.make_instance(
            runtime._item_catalog,
            "npc-progression-vendor-crown",
            "item.tideguard_jacket",
            location="INVENTORY",
            owner_id="player",
        )
        runtime._item_instances[vendor_gear["instance_id"]] = vendor_gear
        runtime._inventory["item.tideguard_jacket"] = (
            runtime._inventory.get("item.tideguard_jacket", 0) + 1
        )
        mira_index = next(
            index
            for index in runtime._npc_indices
            if runtime._npc_ids[index] == "npc-wanderer-01"
        )
        runtime._x[0] = runtime._x[mira_index]
        runtime._z[0] = runtime._z[mira_index]
        vendor_trade = runtime.vendor_sell(
            "vendor.mira",
            vendor_gear["instance_id"],
        )
        assert vendor_trade["economy_result"]["npc_gear_upgrade"]["gear_upgrade"] is True
        assert vendor_gear["location"] == "EQUIPPED"
        assert vendor_gear["owner_id"] == "npc-wanderer-01"
        assert vendor_gear["instance_id"] not in {
            row["instance_id"] for row in runtime._item_instances.values()
            if row.get("location") == "POCKET"
            and row.get("owner_id") == "npc-wanderer-01"
        }

        crafter = people["npc-guardian-01"]
        crafter["progression"]["professions"]["SURVIVAL"]["level"] = 8
        crafter["inventory"] = [
            "material.fresh_water",
            "item.sea_salt",
            "item.sun_herb",
        ]
        crafted, craft_result = runtime._npc_craft_at_station_locked(
            "npc-guardian-01",
            crafter,
            "station.campfire",
        )
        assert crafted is True
        assert craft_result["profession"] == "SURVIVAL"
        assert craft_result["profession_level"] == 8
        assert craft_result["quality"] == "ARTIFACT"

        runtime.save_state()
        runtime.reset()
        loaded = runtime.load_state()
        loaded_mira = loaded["people"]["people"]
        loaded_mira = next(row for row in loaded_mira if row["id"] == "npc-wanderer-01")
        assert loaded_mira["progression"]["gear_score"] == mira["progression"]["gear_score"]
        assert loaded_mira["progression"]["power_score"] == mira["progression"]["power_score"]
        assert any(
            row["instance_id"] == "crate-sunken-crown-01"
            for row in loaded["items"]["equipment"]
        ) is False
        assert any(
            row["instance_id"] == "crate-sunken-crown-01"
            and row["location"] == "EQUIPPED"
            for row in runtime._item_instances.values()
        )
    finally:
        runtime.shutdown()

    print("GAME_ENGINE_NPC_PROGRESSION_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
