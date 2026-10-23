"""Regression tests for item definitions, context state and world interactions."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))


def main() -> int:
    from backend import game_engine_content as content
    from backend import game_engine_items as items
    from backend.game_engine_host import GameEngineRuntime

    catalog = items.catalog_from_content(content.starter_content())
    assert catalog["schema"] == items.SCHEMA
    assert catalog["limits"]["max_world_instances"] == items.MAX_WORLD_INSTANCES
    assert catalog["items"]["item.iron_saber"]["rarity"] == "UNCOMMON"
    assert catalog["items"]["item.tideguard_jacket"]["equip_slot"] == "CHEST"
    assert catalog["items"]["item.drift_cloak"]["equip_slot"] == "BACK"
    assert catalog["items"]["item.saltpath_boots"]["equip_slot"] == "FEET"
    assert catalog["items"]["item.moon_shard"]["rarity"] == "EPIC"
    assert catalog["items"]["item.sunken_crown"]["rarity"] == "LEGENDARY"
    assert list(items.RARITIES) == [
        "TRASH",
        "COMMON",
        "UNCOMMON",
        "RARE",
        "EPIC",
        "LEGENDARY",
        "ARTIFACT",
    ]

    ground = items.make_instance(
        catalog,
        "test-ground-saber",
        "item.iron_saber",
        location="GROUND",
        position={"x": 1, "z": 2},
    )
    assert ground["owner_id"] == ""
    assert items.instance_view(catalog, ground)["visual"]["state"] == "GROUND"
    ok, transition = items.transition_instance(
        ground,
        "INVENTORY",
        owner_id="player",
    )
    assert ok is True
    assert transition["location"] == "INVENTORY"
    assert items.instance_view(catalog, ground)["visual"]["state"] == "INVENTORY"
    ok, _ = items.transition_instance(
        ground,
        "EQUIPPED",
        owner_id="player",
        equipped_slot="MAIN_HAND",
    )
    assert ok is True
    assert items.instance_view(catalog, ground)["visual"]["state"] == "EQUIPPED"
    assert items.roll_loot(catalog, 123) == items.roll_loot(catalog, 123)
    assert items.roll_loot(catalog, 123)["item_id"] in catalog["items"]

    runtime = GameEngineRuntime()
    try:
        initial = runtime.snapshot()
        from backend.game_engine_nature_catalog import loot_tables
        assert initial["items"]["catalog"]["loot_tables"] == 2 + len(loot_tables())
        assert initial["items"]["counts"]["by_location"]["GROUND"] == 4
        # NPC equipment is now materialized as canonical instances too; the
        # two player equipment rows remain visible in the player equipment
        # view while the global location count includes all seven NPC loadouts.
        assert initial["items"]["counts"]["by_location"]["EQUIPPED"] == 11
        assert {row["equipped_slot"] for row in initial["items"]["equipment"]} == {
            "MAIN_HAND",
            "OFF_HAND",
            "BACK",
            "FEET",
        }
        assert {row["attachment"]["socket"] for row in initial["items"]["equipment"]} == {
            "MAIN_HAND",
            "OFF_HAND",
            "BACK",
            "FEET",
        }
        saber = next(
            row
            for row in initial["items"]["equipment"]
            if row["definition_id"] == "item.iron_saber"
        )
        assert saber["visual"]["tint_variant"].startswith("UNCOMMON_")
        assert saber["visual"]["base_color"] == "#8fa4b8"
        assert saber["attachment"]["node"] == "SOCKET_MAIN_HAND"
        assert initial["items"]["interaction_target"]["action"] == "PICKUP"
        assert {row["item"]["rarity"] for row in initial["render"]["entities"] if row.get("item")} == {
            "COMMON",
            "UNCOMMON",
            "EPIC",
            "TRASH",
        }
        assert initial["render"]["item_instances"]["budget"] == items.MAX_WORLD_INSTANCES

        picked = runtime.pickup_item()
        assert picked["item_result"]["action"] == "PICKUP"
        assert picked["item_result"]["item"]["location"] == "INVENTORY"
        assert picked["items"]["counts"]["by_location"]["GROUND"] == 3

        equipped = runtime.equip_item()
        assert equipped["item_result"]["action"] == "EQUIP"
        assert equipped["item_result"]["slot"] == "MAIN_HAND"
        assert any(
            row["definition_id"] == "item.iron_saber"
            and row["location"] == "EQUIPPED"
            for row in equipped["items"]["equipment"]
        )

        opened = runtime.open_container()
        assert opened["item_result"]["action"] == "OPEN"
        assert opened["item_result"]["container"]["container_state"] == "OPEN"
        assert len(opened["item_result"]["container"]["contents"]) == 2

        looted = runtime.loot_container()
        assert looted["item_result"]["action"] == "LOOT"
        assert looted["item_result"]["count"] == 2
        assert looted["items"]["counts"]["by_location"].get("CONTAINER", 0) == 0
        assert looted["items"]["counts"]["by_location"]["INVENTORY"] >= 3

        saved = runtime.save_state()
        assert saved["persistence_result"]["mode"] == "MEMORY_ONLY"
        runtime.reset()
        restored = runtime.load_state()
        assert restored["items"]["counts"] == looted["items"]["counts"]

        before = restored["items"]["counts"]
        assert runtime.equip_item("missing-item")["item_result"]["error"]
        assert runtime.drop_item("missing-item")["item_result"]["error"]
        assert runtime.snapshot()["items"]["counts"] == before
        runtime.equip_item("crate-tideguard-jacket-01")
        worn = runtime.equip_item("crate-sunken-crown-01")
        assert {row["equipped_slot"] for row in worn["items"]["equipment"]} == {
            "MAIN_HAND", "OFF_HAND", "BACK", "FEET", "CHEST", "HEAD"
        }
        dropped = runtime.drop_item("crate-sunken-crown-01")
        assert dropped["item_result"]["item"]["location"] == "GROUND"
        assert len(dropped["items"]["equipment"]) == 5
    finally:
        runtime.shutdown()

    print("GAME_ENGINE_ITEMS_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
