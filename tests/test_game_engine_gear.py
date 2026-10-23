"""Regression tests for gear tables, socket rules and station crafting."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))


def main() -> int:
    from backend import game_engine_content as content
    from backend import game_engine_gear as gear

    tables = gear.tables_from_content(content.starter_content())
    summary = gear.table_summary(tables)
    assert summary["slots"] == 19
    assert summary["runes"] == 6
    assert summary["gems"] == 6
    assert summary["runewords"] == 3
    assert summary["enchantments"] == len(gear.starter_enchantments())
    assert "enchant.chromatic.triad_flame" in tables["enchantments"]
    assert "enchant.gear.vitality" in tables["enchantments"]
    assert summary["materials"] == 10
    assert summary["workstations"] == 5
    original_recipes = {'recipe.fiber_rope','recipe.iron_ingot','recipe.field_ration_survival',
        'recipe.iron_saber','recipe.tideguard_jacket','recipe.gem_polish','recipe.runic_oil'}
    assert original_recipes <= tables['recipes'].keys()
    from backend.game_engine_nature_catalog import PRODUCE
    from backend.game_engine_asset_variations import WEAPON_FAMILIES
    for fruit in PRODUCE:
        recipe=tables['recipes']['recipe.cook_'+fruit]
        assert recipe['inputs']['item.nature.'+fruit] == 3
        assert recipe['output'] == {'item.field_ration':1}
        assert recipe['station_id'] == 'station.campfire'
    for family in WEAPON_FAMILIES:
        recipe=tables['recipes']['recipe.weapon_'+family]
        assert recipe['output'] == {'item.weapon_'+family:1}
        assert recipe['station_id'] == 'station.workbench'
    from backend.game_engine_firearms import AMMO
    for ammo in AMMO:
        assert tables['recipes']['recipe.ammo_'+ammo]['output']
    assert summary['recipes'] == len(original_recipes)+len(PRODUCE)+len(WEAPON_FAMILIES)+len(AMMO)
    assert len(tables["insertables"]) == 12
    asset_rows = gear.asset_table_for_definitions(
        tables["gear_specs"],
        tables["materials"],
        tables["insertables"],
        tables=tables,
    )
    assert asset_rows
    assert all(row["renderer"] == "NATIVE_ASSET_KIT" for row in asset_rows.values())
    assert all(row["geometry_mode"] == "PROCEDURAL_GEOMETRY" for row in asset_rows.values())
    assert all(row["style_id"] == "GG_CLAY_ASSET_KIT" for row in asset_rows.values())

    saber = gear.new_gear_state("item.iron_saber", tables=tables)
    assert saber is not None
    assert saber["slot"] == "MAIN_HAND"
    assert saber["base_type"] == "SWORD"
    assert saber["max_sockets"] == 3
    cloak = gear.new_gear_state("item.drift_cloak", tables=tables)
    assert cloak is not None and cloak["slot"] == "BACK" and cloak["socketable"] is False
    boots = gear.new_gear_state("item.saltpath_boots", tables=tables)
    assert boots is not None and boots["slot"] == "FEET"
    assert tables["gear_specs"]["item.iron_saber"]["palette_variants"]["STANDARD"] == "#8fa4b8"
    for insertable_id in ("rune.tir", "rune.ort", "rune.tal"):
        ok, result = gear.insert_socket(saber, insertable_id, tables)
        assert ok is True
        assert result["socket_count"] <= 3
    assert [row["id"] for row in saber["sockets"]] == [
        "rune.tir",
        "rune.ort",
        "rune.tal",
    ]
    assert saber["runeword"]["id"] == "runeword.tideguard"
    assert saber["stats"]["damage_pct"] == 12
    assert saber["stats"]["swim_speed"] == 2
    ok, full_result = gear.insert_socket(saber, "gem.ruby", tables)
    assert ok is False
    assert full_result["error"] == "GEAR_SOCKETS_FULL"

    compass = gear.new_gear_state("item.island_compass", tables=tables)
    assert compass is not None and compass["socketable"] is False
    ok, result = gear.insert_socket(compass, "gem.ruby", tables)
    assert ok is False and result["error"] == "GEAR_NOT_SOCKETABLE"

    ok, enchant_result = gear.apply_enchant(saber, "enchant.aquatic_edge", tables)
    assert ok is True
    assert enchant_result["enchantment"]["stat"] == "swim_speed"
    ok, duplicate_result = gear.apply_enchant(saber, "enchant.aquatic_edge", tables)
    assert ok is False and duplicate_result["error"] == "GEAR_ENCHANTMENT_DUPLICATE"
    ok, _ = gear.apply_enchant(saber, "enchant.steady_hand", tables)
    assert ok is True
    ok, full_enchant_result = gear.apply_enchant(saber, "enchant.fieldcraft", tables)
    assert ok is False and full_enchant_result["error"] == "GEAR_ENCHANTMENT_SLOTS_FULL"

    inventory = {
        "material.fiber": 3,
        "material.flint": 1,
        "material.iron_ore": 3,
    }
    before = dict(inventory)
    ok, wrong_station = gear.craft(
        tables,
        "recipe.iron_ingot",
        inventory,
        station_id="station.workbench",
    )
    assert ok is False and wrong_station["error"] == "GEAR_STATION_REQUIRED"
    assert inventory == before
    ok, craft_result = gear.craft(
        tables,
        "recipe.iron_ingot",
        inventory,
        station_id="station.forge",
        profession_level=5,
    )
    assert ok is True
    assert craft_result["outputs"] == {"material.iron_ingot": 1}
    assert craft_result["quality"] == "MASTERWORK"
    assert inventory["material.iron_ore"] == 0

    normalized = gear.normalize_gear(
        {"sockets": [{"id": "not-a-rune"}] * 30, "quality": "invalid"},
        "item.iron_saber",
        tables,
    )
    assert normalized is not None
    assert len(normalized["sockets"]) == 0
    assert normalized["quality"] == "STANDARD"
    assert normalized["base_stats"]["damage"] == 6
    view = gear.gear_view(saber)
    assert view is not None
    assert view["socket_count"] == 3
    assert len(view["modifiers"]) <= gear.MAX_GEAR_MODIFIERS

    print("GAME_ENGINE_GEAR_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
