"""Small data-driven gameplay catalogue for the GAME ENGINE vertical slice.

The real MMO catalogue will eventually be authored by the in-game editor and
compiled into packed content pages.  Keeping this first catalogue as plain
data lets abilities, loot, crafting and editor previews share one contract
without hard-coding game rules into the renderer.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from backend import game_engine_gear as gear_catalog
from backend import game_engine_economy as economy_catalog
from backend import game_engine_dialogue as dialogue_catalog
from backend import game_engine_items as item_catalog
from backend import game_engine_life as life_catalog
from backend import game_engine_npc_identity as identity_catalog
from backend import game_engine_content_packs as content_packs
from backend import game_engine_quests as quests_catalog
from backend import game_engine_world_events as world_events_catalog
from backend.game_engine_adapter_spells import authored_abilities


SCHEMA = "gg.game-engine.content.v1"
CONTENT_VERSION = 1


def starter_content() -> dict[str, Any]:
    """Return a fresh, editable starter catalogue."""
    return {
        "schema": SCHEMA,
        "version": CONTENT_VERSION,
        "abilities": {
            "ability.surge": {
                "id": "ability.surge",
                "name": "Island Surge",
                "kind": "MOVEMENT",
                "cooldown_s": 2.5,
                "resource_cost": 12,
                "tags": ["MOBILITY", "GROUND_SWIM_FLY"],
                "effect": {"impulse": 9.0, "particle_burst": 24},
            },
            "ability.undertow": {
                "id": "ability.undertow",
                "name": "Undertow",
                "kind": "MOVEMENT",
                "cooldown_s": 3.5,
                "resource_cost": 16,
                "tags": ["MOBILITY", "SWIM"],
                "effect": {"impulse": 12.0, "particle_burst": 28},
            },
            "ability.sky_leap": {
                "id": "ability.sky_leap",
                "name": "Sky Leap",
                "kind": "MOVEMENT",
                "cooldown_s": 4.0,
                "resource_cost": 20,
                "tags": ["MOBILITY", "FLY"],
                "effect": {"impulse": 14.0, "particle_burst": 32},
            },
            **authored_abilities(),
        },
        "items": item_catalog.starter_definitions(),
        "loot_tables": item_catalog.starter_loot_tables(),
        # Gear is intentionally a separate table family.  That keeps the
        # legacy item count stable while making sockets, runes, gems,
        # runewords, stations and authored crafting data inspectable.
        "gear": gear_catalog.starter_tables(),
        "ambient_life": life_catalog.starter_spawns(),
        "npc_individuals": identity_catalog.starter_individuals(),
        "dialogue": dialogue_catalog.catalog(),
        "quests": quests_catalog.catalog(),
        "world_events": world_events_catalog.catalog(),
        "vendors": economy_catalog.starter_vendors(),
        "recipes": {
            "recipe.wrapping_paper": {
                "id":"recipe.wrapping_paper","name":"Wrapping Paper","profession":"SURVIVAL",
                "inputs":{"material.fiber":2,"material.resin":1},
                "output":{"item.gg_wrapping_paper":2},"skill":"SURVIVAL",
            },
            "recipe.field_ration": {
                "id": "recipe.field_ration",
                "name": "Field Ration",
                "inputs": {
                    "item.sea_salt": 1,
                    "item.sun_herb": 2,
                },
                "output": {"item.field_ration": 1},
                "skill": "CAMP_COOKING",
            },
        },
        "affixes": {
            "affix.tide": {
                "id": "affix.tide",
                "name": "of the Tide",
                "stat": "swim_speed",
                "min": 1,
                "max": 4,
            },
            "affix.wanderer": {
                "id": "affix.wanderer",
                "name": "of the Wanderer",
                "stat": "travel_speed",
                "min": 1,
                "max": 3,
            },
        },
        "enchantments": {
            "enchant.tide": {
                "id": "enchant.tide",
                "name": "Tidebinding",
                "stat": "swim_speed",
                "value": 2,
                "tags": ["WATER", "MOBILITY"],
            },
            "enchant.wayfinder": {
                "id": "enchant.wayfinder",
                "name": "Wayfinder's Mark",
                "stat": "loot_find",
                "value": 1,
                "tags": ["EXPLORATION", "LOOT"],
            },
        },
        "races": {
            "race.islander": {"id": "race.islander", "name": "Islander"},
            "race.tideborn": {"id": "race.tideborn", "name": "Tideborn"},
            "race.skykin": {"id": "race.skykin", "name": "Skykin"},
        },
        "specs": {
            "spec.explorer": {"id": "spec.explorer", "name": "Explorer", "role": "TRAVEL"},
            "spec.warden": {"id": "spec.warden", "name": "Warden", "role": "CONTROL"},
            "spec.duelist": {"id": "spec.duelist", "name": "Duelist", "role": "ACTION"},
        },
        "talents": {
            "trailblazer": {"id": "trailblazer", "name": "Trailblazer", "stat": "move_speed"},
            "tidewalker": {"id": "tidewalker", "name": "Tidewalker", "stat": "swim_speed"},
            "skybound": {"id": "skybound", "name": "Skybound", "stat": "air_control"},
        },
        "classes": {
            "class.pathfinder": {
                "id": "class.pathfinder",
                "name": "Pathfinder",
                "starter_ability": "ability.surge",
                "tags": ["EXPLORATION", "MOBILITY"],
            },
        },
    }


def content_summary(content: dict[str, Any]) -> dict[str, Any]:
    """Return a compact summary suitable for a render/editor snapshot."""
    gear_source = content.get("gear") if isinstance(content.get("gear"), dict) else {}
    gear_summary = gear_catalog.table_summary(gear_source)
    individuals = content.get("npc_individuals", {})
    vendors = content.get("vendors", {})
    dialogue = content.get("dialogue", {})
    quests = content.get("quests", {})
    world_events = content.get("world_events", {})
    asset_bindings = content.get("asset_bindings", {})
    return {
        "schema": str(content.get("schema", SCHEMA)),
        "version": int(content.get("version", CONTENT_VERSION)),
        "abilities": len(content.get("abilities", {})),
        "items": len(content.get("items", {})),
        "recipes": len(content.get("recipes", {})),
        "affixes": len(content.get("affixes", {})),
        "classes": len(content.get("classes", {})),
        "enchantments": len(content.get("enchantments", {})),
        "races": len(content.get("races", {})),
        "specs": len(content.get("specs", {})),
        "talents": len(content.get("talents", {})),
        "ambient_life": len(content.get("ambient_life", [])),
        "npc_individuals": len(individuals) if isinstance(individuals, (dict, list)) else 0,
        "vendors": len(vendors) if isinstance(vendors, (dict, list)) else 0,
        "dialogue_trees": len(dialogue) if isinstance(dialogue, (dict, list)) else 0,
        "quests": len(quests) if isinstance(quests, (dict, list)) else 0,
        "world_events": len(world_events) if isinstance(world_events, (dict, list)) else 0,
        "asset_bindings": len(asset_bindings) if isinstance(asset_bindings, (dict, list)) else 0,
        "active_content_packs": list(content.get("_active_packs", []))[:content_packs.MAX_PACKS]
        if isinstance(content.get("_active_packs"), list)
        else [],
        "gear_tables": gear_summary,
        "gear_slots": gear_summary["slots"],
        "runes": gear_summary["runes"],
        "gems": gear_summary["gems"],
        "runewords": gear_summary["runewords"],
        "gear_enchantments": gear_summary["enchantments"],
        "gear_materials": gear_summary["materials"],
        "workstations": gear_summary["workstations"],
        "gear_recipes": gear_summary["recipes"],
    }


def available_content_packs() -> dict[str, dict[str, Any]]:
    """Return the local authored pages that can be activated by the host."""
    return content_packs.available_packs()


def merge_content_pack(
    content: dict[str, Any],
    pack: dict[str, Any],
) -> dict[str, Any]:
    """Apply one bounded authored page without mutating the source object."""
    return content_packs.merge_pack(content, pack)


def content_pack_summary(
    content: dict[str, Any],
    available: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return content_packs.summary(content, available)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def craft(
    content: dict[str, Any],
    recipe_id: str,
    inventory: dict[str, int],
) -> tuple[bool, dict[str, Any]]:
    """Craft one recipe using a copy-safe, deterministic inventory operation."""
    recipe = content.get("recipes", {}).get(str(recipe_id))
    if not isinstance(recipe, dict):
        return False, {"error": "CONTENT_RECIPE_NOT_FOUND", "recipe_id": recipe_id}
    inputs = recipe.get("inputs", {})
    outputs = recipe.get("output", {})
    if not isinstance(inputs, dict) or not isinstance(outputs, dict):
        return False, {"error": "CONTENT_RECIPE_INVALID", "recipe_id": recipe_id}
    normalized_inputs = {
        str(item_id): max(0, _safe_int(amount)) for item_id, amount in inputs.items()
    }
    normalized_outputs = {
        str(item_id): max(0, _safe_int(amount)) for item_id, amount in outputs.items()
    }
    for item_id, amount in normalized_inputs.items():
        if _safe_int(inventory.get(item_id)) < amount:
            return False, {
                "error": "CONTENT_MATERIALS_MISSING",
                "recipe_id": recipe_id,
                "item_id": item_id,
            }
    for item_id, amount in normalized_inputs.items():
        inventory[item_id] = _safe_int(inventory.get(item_id)) - amount
    for item_id, amount in normalized_outputs.items():
        inventory[item_id] = _safe_int(inventory.get(item_id)) + amount
    return True, {
        "recipe_id": str(recipe_id),
        "name": str(recipe.get("name", recipe_id)),
        "outputs": normalized_outputs,
    }


def deterministic_loot(
    content: dict[str, Any],
    seed: int,
    *,
    base_item_id: str = "item.island_compass",
) -> dict[str, Any]:
    """Roll a reproducible affix payload without using global random state."""
    affixes = list(content.get("affixes", {}).values())
    state = _safe_int(seed, 1) & 0xFFFFFFFF
    if state == 0:
        state = 1

    def next_u32() -> int:
        nonlocal state
        state ^= (state << 13) & 0xFFFFFFFF
        state ^= (state >> 17) & 0xFFFFFFFF
        state ^= (state << 5) & 0xFFFFFFFF
        state &= 0xFFFFFFFF
        return state

    selected: list[dict[str, Any]] = []
    if affixes:
        first = affixes[next_u32() % len(affixes)]
        if isinstance(first, dict):
            low = _safe_int(first.get("min"), 1)
            high = max(low, _safe_int(first.get("max"), low))
            selected.append(
                {
                    "id": str(first.get("id", "")),
                    "name": str(first.get("name", "")),
                    "stat": str(first.get("stat", "")),
                    "value": low + (next_u32() % (high - low + 1)),
                }
            )
    base = content.get("items", {}).get(str(base_item_id), {})
    return {
        "seed": int(seed),
        "base_item_id": str(base_item_id),
        "name": str(base.get("name", base_item_id)) if isinstance(base, dict) else str(base_item_id),
        "affixes": selected,
    }


def enchant_item(
    content: dict[str, Any],
    item: dict[str, Any],
    enchant_id: str,
) -> tuple[bool, dict[str, Any]]:
    """Add one deterministic enchantment to a rolled item instance."""
    enchantments = content.get("enchantments", {})
    enchantment = enchantments.get(str(enchant_id)) if isinstance(enchantments, dict) else None
    if not isinstance(enchantment, dict):
        return False, {"error": "CONTENT_ENCHANTMENT_NOT_FOUND", "enchant_id": enchant_id}
    if not isinstance(item, dict) or not item.get("instance_id"):
        return False, {"error": "CONTENT_ITEM_INSTANCE_REQUIRED"}
    applied = item.setdefault("enchantments", [])
    if not isinstance(applied, list):
        applied = []
        item["enchantments"] = applied
    if len(applied) >= 2:
        return False, {"error": "CONTENT_ENCHANTMENT_SLOTS_FULL"}
    if any(str(row.get("id")) == str(enchant_id) for row in applied if isinstance(row, dict)):
        return False, {"error": "CONTENT_ENCHANTMENT_DUPLICATE", "enchant_id": enchant_id}
    row = {
        "id": str(enchantment.get("id", enchant_id)),
        "name": str(enchantment.get("name", enchant_id)),
        "stat": str(enchantment.get("stat", "")),
        "value": _safe_int(enchantment.get("value"), 1),
    }
    applied.append(row)
    return True, {"instance_id": str(item["instance_id"]), "enchantment": row}


def clone_content(content: dict[str, Any]) -> dict[str, Any]:
    """Give an editor session an isolated mutable catalogue."""
    return deepcopy(content)
