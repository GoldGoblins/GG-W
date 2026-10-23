"""Bounded data tables and rules for gear, sockets and living crafting.

The game engine keeps authored definitions separate from runtime item
instances.  This module is the same seam for equipment: slots, socketable
insertables, runewords, enchantments, materials, stations and recipes are
plain data, while the small rule functions validate and recalculate one
instance without touching rendering or the fixed-step movement contract.

The names and examples are original starter content.  The design borrows the
useful *patterns* of socket order, item-slot specialization, optional
enhancements and profession stations without importing proprietary assets or
data from another game.
"""

from __future__ import annotations

import copy
import math
from typing import Any, Iterable
from backend import game_engine_enchants as enchant_contract


SCHEMA = "gg.game-engine.gear.v1"
VERSION = 1

MAX_SOCKETS = 6
MAX_ENCHANTMENTS = 2
MAX_GEAR_MODIFIERS = 24
MAX_INSERTABLES = 24
MAX_RECIPE_INPUTS = 8
MAX_RECIPE_OUTPUTS = 4
MAX_PROFESSIONS = 8
MAX_ASSET_ROWS = 96

GEAR_SLOTS = (
    "HEAD",
    "NECK",
    "SHOULDERS",
    "SHIRT",
    "BACK",
    "CHEST",
    "WRISTS",
    "HANDS",
    "WAIST",
    "LEGS",
    "FEET",
    "RING_1",
    "RING_2",
    "MAIN_HAND",
    "OFF_HAND",
    "RANGED",
    "TABARD",
    "TRINKET_1",
    "TRINKET_2",
)

SOCKETABLE_BASE_TYPES = frozenset(
    {
        "HELM",
        "CHEST_ARMOR",
        "SHIELD",
        "SWORD",
        "AXE",
        "MACE",
        "BOW",
        "STAFF",
        "DAGGER",
        "PISTOL",
        "WAND",
        "OFFHAND",
    }
)
INSERTABLE_KINDS = ("RUNE", "GEM", "JEWEL")
QUALITY_LADDER = ("STANDARD", "FINE", "MASTERWORK", "ARTIFACT")


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _clamp(value: Any, low: float, high: float, default: float = 0.0) -> float:
    return max(low, min(high, _safe_float(value, default)))


def _bounded_text(value: Any, default: str = "", limit: int = 64) -> str:
    return str(value or default).strip()[:limit]


def _number(value: Any) -> int | float:
    number = _safe_float(value)
    return int(number) if number.is_integer() else round(number, 4)


def _add_stat(stats: dict[str, int | float], stat: Any, value: Any) -> None:
    key = _bounded_text(stat).lower()
    if not key:
        return
    amount = _safe_float(value)
    if not math.isfinite(amount) or abs(amount) > 100000.0:
        return
    stats[key] = _number(_safe_float(stats.get(key)) + amount)


def _visual(
    asset_id: str,
    model: str,
    color: str,
    scale: tuple[float, float, float],
) -> dict[str, Any]:
    """Give every gear/material family a stable native 3D state."""
    states = {}
    for context in ("GROUND", "CONTAINER", "INVENTORY", "EQUIPPED", "POCKET"):
        factor = 0.72 if context == "CONTAINER" else (0.82 if context == "EQUIPPED" else 1.0)
        states[context] = {
            "asset_id": asset_id,
            "renderer": "NATIVE_ASSET_KIT",
            "model": model,
            "scale": [round(component * factor, 4) for component in scale],
            "rotation": [0.0, 0.0, 0.0],
            "offset_y": 0.16 if context != "EQUIPPED" else 0.05,
            "float_m": 0.06 if context == "GROUND" else 0.0,
            "spin_deg_s": 18.0 if context == "GROUND" else 0.0,
            "base_color": color,
        }
    return {"asset_id": asset_id, "states": states}


def starter_slot_table() -> dict[str, dict[str, Any]]:
    categories = {
        "HEAD": "ARMOR",
        "NECK": "JEWELRY",
        "SHOULDERS": "ARMOR",
        "SHIRT": "COSMETIC",
        "BACK": "ARMOR",
        "CHEST": "ARMOR",
        "WRISTS": "ARMOR",
        "HANDS": "ARMOR",
        "WAIST": "ARMOR",
        "LEGS": "ARMOR",
        "FEET": "ARMOR",
        "RING_1": "JEWELRY",
        "RING_2": "JEWELRY",
        "MAIN_HAND": "WEAPON",
        "OFF_HAND": "UTILITY",
        "RANGED": "WEAPON",
        "TRINKET_1": "TRINKET",
        "TRINKET_2": "TRINKET",
        "TABARD": "COSMETIC",
    }
    return {
        slot: {
            "id": slot,
            "name": slot.replace("_", " ").title(),
            "category": categories[slot],
            "socketable": slot in {"HEAD", "CHEST", "MAIN_HAND", "OFF_HAND", "RANGED"},
            "max_sockets": 3 if slot in {"CHEST", "MAIN_HAND", "RANGED"} else (2 if slot == "HEAD" else 0),
        }
        for slot in GEAR_SLOTS
    }


def starter_gear_specs() -> dict[str, dict[str, Any]]:
    """Map authored item definitions to their equipment contract."""
    out = {
        "item.island_compass": {
            "slot": "OFF_HAND",
            "base_type": "COMPASS",
            "max_sockets": 0,
            "base_stats": {"navigation": 1},
            "palette": "#d6c28f",
            "palette_variants": {
                "STANDARD": "#d6c28f",
                "FINE": "#e4d4a4",
                "MASTERWORK": "#f0e2b4",
                "ARTIFACT": "#f0d26f",
            },
        },
        "item.iron_saber": {
            "slot": "MAIN_HAND",
            "base_type": "SWORD",
            "max_sockets": 3,
            "base_stats": {"damage": 6, "durability": 80},
            "palette": "#8fa4b8",
            "palette_variants": {
                "STANDARD": "#8fa4b8",
                "FINE": "#a8c0d4",
                "MASTERWORK": "#c5d7e6",
                "ARTIFACT": "#f0d26f",
            },
        },
        "item.tideguard_jacket": {
            "slot": "CHEST",
            "base_type": "CHEST_ARMOR",
            "max_sockets": 3,
            "base_stats": {"armor": 8, "stamina": 6, "durability": 100},
            "palette": "#2f6b6a",
            "palette_variants": {
                "STANDARD": "#2f6b6a",
                "FINE": "#3d8a7c",
                "MASTERWORK": "#4ea090",
                "ARTIFACT": "#70a9e8",
            },
        },
        "item.sunken_crown": {
            "slot": "HEAD",
            "base_type": "HELM",
            "max_sockets": 2,
            "base_stats": {"armor": 4, "loot_find": 2, "durability": 65},
            "palette": "#c9893a",
            "palette_variants": {
                "STANDARD": "#c9893a",
                "FINE": "#e0a24a",
                "MASTERWORK": "#eeb45a",
                "ARTIFACT": "#f0d26f",
            },
        },
        "item.drift_cloak": {
            "slot": "BACK",
            "base_type": "CLOAK",
            "max_sockets": 0,
            "base_stats": {"armor": 3, "stamina": 2, "swim_speed": 1},
            "palette": "#3a5a48",
            "palette_variants": {
                "STANDARD": "#3a5a48",
                "FINE": "#4a735c",
                "MASTERWORK": "#5c8a70",
                "ARTIFACT": "#76c47d",
            },
        },
        "item.saltpath_boots": {
            "slot": "FEET",
            "base_type": "BOOTS",
            "max_sockets": 0,
            "base_stats": {"armor": 2, "travel_speed": 1, "durability": 70},
            "palette": "#5a3a28",
            "palette_variants": {
                "STANDARD": "#5a3a28",
                "FINE": "#6e4a34",
                "MASTERWORK": "#84583e",
                "ARTIFACT": "#c98989",
            },
        },
    }

    from backend.game_engine_asset_variations import WEAPON_FAMILIES
    for family in WEAPON_FAMILIES:
        stats={'armor':6,'durability':80} if family=='shield' else {'spell_power':3,'energy':8,'durability':80} if family=='offhand' else {'damage':8,'attack_range':1.2,'spell_power':2,'durability':80} if family=='staff' else {'damage':6,'durability':80}
        out['item.weapon_'+family]=dict(slot='OFF_HAND' if family in ('shield','offhand') else 'MAIN_HAND',
            base_type=family.upper(),max_sockets=3,base_stats=stats,
            palette='#91b7be')
    return out


def starter_runes() -> dict[str, dict[str, Any]]:
    return {
        "rune.el": {
            "id": "rune.el",
            "name": "El Rune",
            "kind": "RUNE",
            "level": 1,
            "tags": ["RUNE", "STARTER"],
            "socket_effects": {
                "WEAPON": {"damage": 1},
                "ARMOR": {"armor": 1},
                "HELM": {"health": 2},
                "DEFAULT": {"stamina": 1},
            },
            "asset_id": "rune.el",
            "visual": _visual("rune.el", "#Sphere", "#d8c68a", (0.12, 0.12, 0.12)),
        },
        "rune.tir": {
            "id": "rune.tir",
            "name": "Tir Rune",
            "kind": "RUNE",
            "level": 2,
            "tags": ["RUNE", "ENERGY"],
            "socket_effects": {
                "WEAPON": {"energy_regen": 1},
                "ARMOR": {"loot_find": 1},
                "DEFAULT": {"curiosity": 1},
            },
            "asset_id": "rune.tir",
            "visual": _visual("rune.tir", "#Sphere", "#d7a36f", (0.13, 0.13, 0.13)),
        },
        "rune.ith": {
            "id": "rune.ith",
            "name": "Ith Rune",
            "kind": "RUNE",
            "level": 3,
            "tags": ["RUNE", "WARD"],
            "socket_effects": {
                "WEAPON": {"damage_pct": 3},
                "ARMOR": {"damage_reduction": 1},
                "DEFAULT": {"armor": 1},
            },
            "asset_id": "rune.ith",
            "visual": _visual("rune.ith", "#Sphere", "#8fb1c8", (0.13, 0.13, 0.13)),
        },
        "rune.tal": {
            "id": "rune.tal",
            "name": "Tal Rune",
            "kind": "RUNE",
            "level": 4,
            "tags": ["RUNE", "TIDE"],
            "socket_effects": {
                "WEAPON": {"poison_damage": 1},
                "ARMOR": {"swim_speed": 1},
                "DEFAULT": {"nature_resist": 1},
            },
            "asset_id": "rune.tal",
            "visual": _visual("rune.tal", "#Sphere", "#76c47d", (0.14, 0.14, 0.14)),
        },
        "rune.ral": {
            "id": "rune.ral",
            "name": "Ral Rune",
            "kind": "RUNE",
            "level": 5,
            "tags": ["RUNE", "FIRE"],
            "socket_effects": {
                "WEAPON": {"fire_damage": 2},
                "ARMOR": {"fire_resist": 2},
                "DEFAULT": {"heat": 1},
            },
            "asset_id": "rune.ral",
            "visual": _visual("rune.ral", "#Sphere", "#ee9949", (0.14, 0.14, 0.14)),
        },
        "rune.ort": {
            "id": "rune.ort",
            "name": "Ort Rune",
            "kind": "RUNE",
            "level": 6,
            "tags": ["RUNE", "STORM"],
            "socket_effects": {
                "WEAPON": {"lightning_damage": 2},
                "ARMOR": {"lightning_resist": 2},
                "DEFAULT": {"storm_resist": 1},
            },
            "asset_id": "rune.ort",
            "visual": _visual("rune.ort", "#Sphere", "#b88cff", (0.15, 0.15, 0.15)),
        },
    }


def starter_gems() -> dict[str, dict[str, Any]]:
    rows = (
        ("ruby", "Ruby", "#d96b67", {"WEAPON": {"damage": 2}, "ARMOR": {"health": 5}}),
        ("sapphire", "Sapphire", "#70a9e8", {"WEAPON": {"mana": 3}, "ARMOR": {"frost_resist": 2}}),
        ("topaz", "Topaz", "#f0d26f", {"WEAPON": {"lightning_damage": 1}, "ARMOR": {"loot_find": 2}}),
        ("emerald", "Emerald", "#76c47d", {"WEAPON": {"crit": 1}, "ARMOR": {"poison_resist": 2}}),
        ("diamond", "Diamond", "#dce9f1", {"WEAPON": {"holy_damage": 2}, "ARMOR": {"damage_reduction": 1}}),
        ("amethyst", "Amethyst", "#b88cff", {"WEAPON": {"spell_power": 2}, "ARMOR": {"stamina": 3}}),
    )
    return {
        f"gem.{gem_id}": {
            "id": f"gem.{gem_id}",
            "name": name,
            "kind": "GEM",
            "level": 1,
            "tags": ["GEM", "JEWELCRAFT"],
            "socket_effects": effects,
            "asset_id": f"gem.{gem_id}",
            "visual": _visual(f"gem.{gem_id}", "#Sphere", color, (0.14, 0.18, 0.14)),
        }
        for gem_id, name, color, effects in rows
    }


def starter_runewords() -> dict[str, dict[str, Any]]:
    return {
        "runeword.tideguard": {
            "id": "runeword.tideguard",
            "name": "Tideguard",
            "sequence": ["rune.tir", "rune.ort", "rune.tal"],
            "socket_count": 3,
            "allowed_base_types": ["SWORD", "CHEST_ARMOR"],
            "bonuses": {"damage_pct": 12, "armor": 6, "swim_speed": 2, "loot_find": 1},
            "tags": ["RUNEWORD", "TIDE", "STARTER"],
        },
        "runeword.wayfinder": {
            "id": "runeword.wayfinder",
            "name": "Wayfinder",
            "sequence": ["rune.el", "rune.ith", "rune.ral"],
            "socket_count": 3,
            "allowed_base_types": ["SWORD", "BOW", "DAGGER"],
            "bonuses": {"travel_speed": 3, "damage": 2, "curiosity": 2},
            "tags": ["RUNEWORD", "EXPLORATION"],
        },
        "runeword.shellkeeper": {
            "id": "runeword.shellkeeper",
            "name": "Shellkeeper",
            "sequence": ["rune.tal", "rune.ort", "rune.ith"],
            "socket_count": 3,
            "allowed_base_types": ["CHEST_ARMOR", "SHIELD"],
            "bonuses": {"armor": 12, "stamina": 4, "damage_reduction": 2, "water_resist": 3},
            "tags": ["RUNEWORD", "GUARDIAN"],
        },
    }


def starter_enchantments() -> dict[str, dict[str, Any]]:
    return {
        **copy.deepcopy(enchant_contract.CATALOG),
        **copy.deepcopy(enchant_contract.GEAR_CATALOG),
        "enchant.aquatic_edge": {
            "id": "enchant.aquatic_edge",
            "name": "Aquatic Edge",
            "stat": "swim_speed",
            "value": 2,
            "allowed_categories": ["WEAPON", "ARMOR"],
            "tags": ["ENCHANT", "WATER"],
            "visual_fx": "WATER",
        },
        "enchant.treasure_sense": {
            "id": "enchant.treasure_sense",
            "name": "Treasure Sense",
            "stat": "loot_find",
            "value": 3,
            "allowed_categories": ["ARMOR", "TRINKET", "UTILITY"],
            "tags": ["ENCHANT", "LOOT"],
            "visual_fx": "ARCANE",
        },
        "enchant.hardened_hide": {
            "id": "enchant.hardened_hide",
            "name": "Hardened Hide",
            "stat": "armor",
            "value": 4,
            "allowed_categories": ["ARMOR"],
            "tags": ["ENCHANT", "SURVIVAL"],
            "visual_fx": "SMOKE",
        },
        "enchant.fieldcraft": {
            "id": "enchant.fieldcraft",
            "name": "Fieldcraft",
            "stat": "gather_speed",
            "value": 3,
            "allowed_categories": ["ARMOR", "UTILITY"],
            "tags": ["ENCHANT", "CRAFTING"],
            "visual_fx": "GAS",
        },
        "enchant.steady_hand": {
            "id": "enchant.steady_hand",
            "name": "Steady Hand",
            "stat": "crit",
            "value": 2,
            "allowed_categories": ["WEAPON"],
            "tags": ["ENCHANT", "COMBAT"],
            "visual_fx": "LIGHTNING",
        },
        "enchant.night_glimmer": {
            "id": "enchant.night_glimmer",
            "name": "Night Glimmer",
            "stat": "night_vision",
            "value": 2,
            "allowed_categories": ["ARMOR", "UTILITY"],
            "tags": ["ENCHANT", "NIGHT"],
            "visual_fx": "SHADOW",
        },
        "enchant.ember_edge": {
            "id": "enchant.ember_edge", "name": "Ember Edge",
            "stat": "damage", "value": 2,
            "allowed_categories": ["WEAPON"],
            "tags": ["ENCHANT", "FIRE"], "visual_fx": "FIRE",
        },
        "enchant.smoke_edge": {
            "id": "enchant.smoke_edge", "name": "Smoke Edge",
            "stat": "damage", "value": 1,
            "allowed_categories": ["WEAPON"],
            "tags": ["ENCHANT", "SMOKE"], "visual_fx": "SMOKE",
        },
        "enchant.venom_edge": {
            "id": "enchant.venom_edge", "name": "Venom Edge",
            "stat": "damage", "value": 2,
            "allowed_categories": ["WEAPON"],
            "tags": ["ENCHANT", "GAS"], "visual_fx": "GAS",
        },
        "enchant.storm_edge": {
            "id": "enchant.storm_edge", "name": "Storm Edge",
            "stat": "crit", "value": 2,
            "allowed_categories": ["WEAPON"],
            "tags": ["ENCHANT", "LIGHTNING"], "visual_fx": "LIGHTNING",
        },
        "enchant.arcane_edge": {
            "id": "enchant.arcane_edge", "name": "Arcane Edge",
            "stat": "crit", "value": 2,
            "allowed_categories": ["WEAPON"],
            "tags": ["ENCHANT", "ARCANE"], "visual_fx": "ARCANE",
        },
        "enchant.shadow_edge": {
            "id": "enchant.shadow_edge", "name": "Shadow Edge",
            "stat": "crit", "value": 2,
            "allowed_categories": ["WEAPON"],
            "tags": ["ENCHANT", "SHADOW"], "visual_fx": "SHADOW",
        },
        "enchant.sun_lance": {
            "id": "enchant.sun_lance", "name": "Sun Lance",
            "stat": "damage", "value": 2,
            "allowed_categories": ["WEAPON"],
            "tags": ["ENCHANT", "LASER"], "visual_fx": "LASER",
        },
    }


def starter_materials() -> dict[str, dict[str, Any]]:
    rows = (
        ("material.fiber", "Island Fiber", "COMMON", "#76c47d", (0.12, 0.25, 0.12)),
        ("material.wood", "Driftwood", "COMMON", "#a8784d", (0.14, 0.28, 0.14)),
        ("material.flint", "Storm Flint", "COMMON", "#8fa8a0", (0.18, 0.1, 0.18)),
        ("material.iron_ore", "Iron Ore", "COMMON", "#9a8d83", (0.18, 0.15, 0.18)),
        ("material.hide", "Saltbeast Hide", "UNCOMMON", "#c98989", (0.22, 0.08, 0.2)),
        ("material.fresh_water", "Fresh Water", "COMMON", "#70a9e8", (0.12, 0.22, 0.12)),
        ("material.resin", "Amber Resin", "UNCOMMON", "#ee9949", (0.13, 0.2, 0.13)),
        ("material.rope", "Woven Rope", "COMMON", "#d6c28f", (0.1, 0.26, 0.1)),
        ("material.iron_ingot", "Iron Ingot", "UNCOMMON", "#b5bdc8", (0.22, 0.12, 0.22)),
        ("material.runic_oil", "Runic Oil", "RARE", "#b88cff", (0.12, 0.2, 0.12)),
    )
    return {
        item_id: {
            "id": item_id,
            "name": name,
            "kind": "MATERIAL",
            "rarity": rarity,
            "level": 1,
            "stack_limit": 99,
            "tags": ["CRAFTING", "RESOURCE"],
            "asset_id": item_id,
            "visual": _visual(item_id, "#Cube", color, scale),
        }
        for item_id, name, rarity, color, scale in rows
    }


def starter_workstations() -> dict[str, dict[str, Any]]:
    return {
        "station.campfire": {
            "id": "station.campfire",
            "name": "Campfire",
            "tags": ["SURVIVAL", "COOKING", "HEAT"],
            "actions": ["COOK", "BOIL", "DRY", "REST"],
            "position": {"x": -1.8, "y": 0.0, "z": 1.1},
        },
        "station.workbench": {
            "id": "station.workbench",
            "name": "Field Workbench",
            "tags": ["SURVIVAL", "WOODWORK", "REPAIR"],
            "actions": ["ASSEMBLE", "REPAIR", "CARVE"],
            "position": {"x": 1.5, "y": 0.0, "z": 2.1},
        },
        "station.forge": {
            "id": "station.forge",
            "name": "Tide Forge",
            "tags": ["BLACKSMITHING", "HEAT", "METAL"],
            "actions": ["SMELT", "FORGE", "REPAIR"],
            "position": {"x": 3.2, "y": 0.0, "z": -1.8},
        },
        "station.enchanting_altar": {
            "id": "station.enchanting_altar",
            "name": "Whispering Altar",
            "tags": ["ENCHANTING", "ARCANE"],
            "actions": ["ENCHANT", "DISENCHANT", "IDENTIFY"],
            "position": {"x": -3.0, "y": 0.0, "z": -1.5},
        },
        "station.jewelers_bench": {
            "id": "station.jewelers_bench",
            "name": "Jewelers Bench",
            "tags": ["JEWELCRAFT", "SOCKETING"],
            "actions": ["CUT_GEM", "SOCKET", "POLISH"],
            "position": {"x": 0.5, "y": 0.0, "z": -3.2},
        },
    }


def starter_recipes() -> dict[str, dict[str, Any]]:
    out = {
        "recipe.fiber_rope": {
            "id": "recipe.fiber_rope",
            "name": "Woven Rope",
            "inputs": {"material.fiber": 3},
            "output": {"material.rope": 1},
            "station_id": "station.workbench",
            "profession": "SURVIVAL",
            "difficulty": 1,
            "tags": ["SURVIVAL", "UTILITY"],
        },
        "recipe.iron_ingot": {
            "id": "recipe.iron_ingot",
            "name": "Smelt Iron Ingot",
            "inputs": {"material.iron_ore": 3, "material.flint": 1},
            "output": {"material.iron_ingot": 1},
            "station_id": "station.forge",
            "profession": "BLACKSMITHING",
            "difficulty": 2,
            "tags": ["METAL", "SURVIVAL"],
        },
        "recipe.field_ration_survival": {
            "id": "recipe.field_ration_survival",
            "name": "Boiled Field Ration",
            "inputs": {
                "material.fresh_water": 1,
                "item.sea_salt": 1,
                "item.sun_herb": 1,
            },
            "output": {"item.field_ration": 1},
            "station_id": "station.campfire",
            "profession": "SURVIVAL",
            "difficulty": 1,
            "tags": ["COOKING", "RECOVERY"],
        },
        "recipe.iron_saber": {
            "id": "recipe.iron_saber",
            "name": "Forge Iron Saber",
            "inputs": {"material.iron_ingot": 2, "material.wood": 1, "material.resin": 1},
            "output": {"item.iron_saber": 1},
            "station_id": "station.forge",
            "profession": "BLACKSMITHING",
            "difficulty": 3,
            "tags": ["WEAPON", "FORGE"],
        },
        "recipe.tideguard_jacket": {
            "id": "recipe.tideguard_jacket",
            "name": "Stitch Tideguard Jacket",
            "inputs": {"material.hide": 3, "material.fiber": 2, "material.iron_ingot": 1},
            "output": {"item.tideguard_jacket": 1},
            "station_id": "station.workbench",
            "profession": "LEATHERWORKING",
            "difficulty": 3,
            "tags": ["ARMOR", "SURVIVAL"],
        },
        "recipe.gem_polish": {
            "id": "recipe.gem_polish",
            "name": "Polish a Gem",
            "inputs": {"material.resin": 1, "material.flint": 1},
            "output": {"gem.ruby": 1},
            "station_id": "station.jewelers_bench",
            "profession": "JEWELCRAFTING",
            "difficulty": 2,
            "tags": ["GEM", "SOCKETING"],
        },
        "recipe.runic_oil": {
            "id": "recipe.runic_oil",
            "name": "Distill Runic Oil",
            "inputs": {"item.sea_salt": 1, "item.moon_shard": 1, "material.resin": 1},
            "output": {"material.runic_oil": 1},
            "station_id": "station.enchanting_altar",
            "profession": "ENCHANTING",
            "difficulty": 4,
            "tags": ["ENCHANTING", "ARCANE"],
        },
    }

    from backend.game_engine_nature_catalog import PRODUCE
    from backend.game_engine_asset_variations import WEAPON_FAMILIES
    for key,spec in PRODUCE.items():
        identity='recipe.cook_'+key
        out[identity]=dict(id=identity,name='Cook '+spec[0]+' Ration',
            inputs={'item.nature.'+key:3,'material.fresh_water':1},output={'item.field_ration':1},
            station_id='station.campfire',profession='SURVIVAL',difficulty=1,tags=['COOKING','FOOD',key.upper()])
    for family in WEAPON_FAMILIES:
        identity='recipe.weapon_'+family
        out[identity]=dict(id=identity,name='Craft '+family.title(),
            inputs={'material.wood':2,'material.iron_ingot':1,'material.fiber':1},
            output={'item.weapon_'+family:1},station_id='station.workbench',profession='SURVIVAL',difficulty=2,tags=['WEAPON','CRAFT'])
    from backend.game_engine_firearms import crafting_recipes
    out.update(crafting_recipes())
    return out


def starter_professions() -> dict[str, dict[str, Any]]:
    names = {
        "SURVIVAL": "Survival",
        "BLACKSMITHING": "Blacksmithing",
        "LEATHERWORKING": "Leatherworking",
        "JEWELCRAFTING": "Jewelcrafting",
        "ENCHANTING": "Enchanting",
    }
    return {
        profession_id: {
            "id": profession_id,
            "name": name,
            "level": 1,
            "xp": 0,
            "max_level": 100,
            "specializations": [],
        }
        for profession_id, name in names.items()
    }


def starter_insertables() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    result.update(starter_runes())
    result.update(starter_gems())
    return result


def starter_tables() -> dict[str, Any]:
    """Return the complete starter gear/crafting table as isolated data."""
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "slots": starter_slot_table(),
        "gear_specs": starter_gear_specs(),
        "runes": starter_runes(),
        "gems": starter_gems(),
        "runewords": starter_runewords(),
        "enchantments": starter_enchantments(),
        "materials": starter_materials(),
        "workstations": starter_workstations(),
        "recipes": starter_recipes(),
        "professions": starter_professions(),
        "insertables": starter_insertables(),
        "limits": {
            "max_sockets": MAX_SOCKETS,
            "max_enchantments": MAX_ENCHANTMENTS,
            "max_gear_modifiers": MAX_GEAR_MODIFIERS,
            "max_insertables": MAX_INSERTABLES,
            "max_recipe_inputs": MAX_RECIPE_INPUTS,
            "max_recipe_outputs": MAX_RECIPE_OUTPUTS,
            "max_professions": MAX_PROFESSIONS,
            "max_asset_rows": MAX_ASSET_ROWS,
        },
        "policy": "DATA_TABLES_VALIDATED_INSTANCE_MODIFIERS_BOUNDED",
    }


def tables_from_content(content: dict[str, Any] | None = None) -> dict[str, Any]:
    source = content.get("gear") if isinstance(content, dict) else None
    defaults = starter_tables()
    if not isinstance(source, dict):
        return defaults
    result = copy.deepcopy(defaults)
    row_limits = {
        "slots": len(GEAR_SLOTS),
        "gear_specs": MAX_ASSET_ROWS,
        "runes": MAX_INSERTABLES,
        "gems": MAX_INSERTABLES,
        "runewords": MAX_INSERTABLES,
        "enchantments": MAX_ASSET_ROWS,
        "materials": MAX_ASSET_ROWS,
        "workstations": MAX_PROFESSIONS * 2,
        "recipes": MAX_ASSET_ROWS,
        "professions": MAX_PROFESSIONS,
        "insertables": MAX_INSERTABLES,
        "item_sets": 64,
    }
    for key, row_limit in row_limits.items():
        value = source.get(key)
        if isinstance(value, dict):
            result[key] = copy.deepcopy(dict(list(value.items())[:row_limit]))
    return result


def table_summary(tables: dict[str, Any]) -> dict[str, Any]:
    def count(key: str) -> int:
        value = tables.get(key, {})
        return len(value) if isinstance(value, dict) else 0

    return {
        "schema": str(tables.get("schema", SCHEMA)),
        "version": _safe_int(tables.get("version"), VERSION),
        "slots": count("slots"),
        "gear_specs": count("gear_specs"),
        "runes": count("runes"),
        "gems": count("gems"),
        "runewords": count("runewords"),
        "enchantments": count("enchantments"),
        "materials": count("materials"),
        "workstations": count("workstations"),
        "recipes": count("recipes"),
        "professions": count("professions"),
        "insertables": count("insertables"),
        "policy": str(tables.get("policy", "")),
    }


def gear_spec_for_definition(
    definition_id: Any,
    tables: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    source = tables if isinstance(tables, dict) else starter_tables()
    specs = source.get("gear_specs", {})
    row = specs.get(str(definition_id)) if isinstance(specs, dict) else None
    return copy.deepcopy(row) if isinstance(row, dict) else None


def _normalize_stats(value: Any, *, limit: int = MAX_GEAR_MODIFIERS) -> dict[str, int | float]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, int | float] = {}
    for key, raw in list(value.items())[:limit]:
        name = _bounded_text(key, limit=48).lower()
        number = _safe_float(raw)
        if name and math.isfinite(number) and abs(number) <= 100000.0:
            result[name] = _number(number)
    return result


def _base_category(base_type: Any) -> str:
    normalized = _bounded_text(base_type).upper()
    if normalized in {"SWORD", "AXE", "MACE", "BOW", "STAFF", "WAND", "DAGGER", "PISTOL"}:
        return "WEAPON"
    if normalized in {"HELM"}:
        return "HELM"
    if normalized in {"CHEST_ARMOR", "SHIELD", "OFFHAND"}:
        return "ARMOR"
    return "UTILITY"


def _socket_effects(insertable: dict[str, Any], category: str) -> dict[str, Any]:
    effects = insertable.get("socket_effects", {})
    if not isinstance(effects, dict):
        return {}
    selected = effects.get(category) or effects.get("ARMOR" if category == "HELM" else "DEFAULT")
    return selected if isinstance(selected, dict) else {}


def _modifier_row(source: str, source_id: str, stat: str, value: Any) -> dict[str, Any]:
    return {
        "source": _bounded_text(source, limit=24).upper(),
        "id": _bounded_text(source_id, limit=64),
        "stat": _bounded_text(stat, limit=48).lower(),
        "value": _number(value),
    }


def _runeword_match(gear: dict[str, Any], tables: dict[str, Any]) -> dict[str, Any] | None:
    sockets = gear.get("sockets", [])
    if not isinstance(sockets, list):
        return None
    sequence = [_bounded_text(row.get("id")) for row in sockets if isinstance(row, dict)]
    base_type = _bounded_text(gear.get("base_type")).upper()
    runewords = tables.get("runewords", {})
    if not isinstance(runewords, dict):
        return None
    for runeword in runewords.values():
        if not isinstance(runeword, dict):
            continue
        expected = [
            _bounded_text(value)
            for value in runeword.get("sequence", [])[:MAX_SOCKETS]
        ]
        allowed = {
            _bounded_text(value).upper()
            for value in runeword.get("allowed_base_types", [])
        }
        count = max(0, min(MAX_SOCKETS, _safe_int(runeword.get("socket_count"), len(expected))))
        if count == len(sequence) == len(expected) and sequence == expected and base_type in allowed:
            return copy.deepcopy(runeword)
    return None


def _enchant_metadata(enchant_id: str) -> dict:
    definition = enchant_contract.definition(enchant_id)
    return {key: copy.deepcopy(definition[key]) for key in
            ('colors', 'description', 'tier', 'families', 'required_level')
            if key in definition}


def recalculate_gear(gear: dict[str, Any], tables: dict[str, Any] | None = None) -> dict[str, Any]:
    """Recompute derived modifiers from base stats, sockets and enchants."""
    source = tables if isinstance(tables, dict) else starter_tables()
    if not isinstance(gear, dict):
        return {}
    stats = _normalize_stats(gear.get("base_stats"))
    modifiers: list[dict[str, Any]] = []
    category = _base_category(gear.get("base_type"))
    insertables = source.get("insertables", {})
    sockets = gear.get("sockets", [])
    if not isinstance(sockets, list):
        sockets = []
    safe_sockets = []
    for index, socket in enumerate(sockets[:MAX_SOCKETS]):
        if not isinstance(socket, dict) or not socket.get("id"):
            continue
        insertable_id = _bounded_text(socket.get("id"), limit=96)
        definition = insertables.get(insertable_id) if isinstance(insertables, dict) else None
        if not isinstance(definition, dict):
            continue
        safe_socket = {
            "index": index,
            "id": insertable_id,
            "name": _bounded_text(definition.get("name"), insertable_id, 64),
            "kind": _bounded_text(definition.get("kind"), "GEM", 16).upper(),
            "level": max(1, _safe_int(definition.get("level"), 1)),
        }
        safe_sockets.append(safe_socket)
        for stat, value in _socket_effects(definition, category).items():
            _add_stat(stats, stat, value)
            modifiers.append(_modifier_row("SOCKET", insertable_id, stat, value))
    gear["sockets"] = safe_sockets
    runeword = _runeword_match(gear, source)
    gear["runeword"] = runeword
    if isinstance(runeword, dict):
        for stat, value in runeword.get("bonuses", {}).items():
            _add_stat(stats, stat, value)
            modifiers.append(_modifier_row("RUNEWORD", runeword.get("id", ""), stat, value))
    enchants = gear.get("enchantments", [])
    safe_enchants = []
    if isinstance(enchants, list):
        for enchant in enchants[:MAX_ENCHANTMENTS]:
            if not isinstance(enchant, dict) or not enchant.get("id"):
                continue
            row = {
                "id": _bounded_text(enchant.get("id"), limit=96),
                "name": _bounded_text(enchant.get("name"), enchant.get("id"), 64),
                "stat": _bounded_text(enchant.get("stat"), limit=48).lower(),
                "value": _number(enchant.get("value", 1)),
                "visual_fx": _bounded_text(enchant.get("visual_fx"), limit=16).upper(),
            }
            row.update(_enchant_metadata(row["id"]))
            safe_enchants.append(row)
            _add_stat(stats, row["stat"], row["value"])
            modifiers.append(_modifier_row("ENCHANT", row["id"], row["stat"], row["value"]))
    gear["enchantments"] = safe_enchants
    gear["stats"] = stats
    gear["modifiers"] = modifiers[:MAX_GEAR_MODIFIERS]
    return gear


def new_gear_state(
    definition_id: Any,
    raw_spec: dict[str, Any] | None = None,
    tables: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    source = tables if isinstance(tables, dict) else starter_tables()
    spec = copy.deepcopy(raw_spec) if isinstance(raw_spec, dict) else gear_spec_for_definition(definition_id, source)
    if not isinstance(spec, dict):
        return None
    slot = _bounded_text(spec.get("slot"), limit=32).upper()
    base_type = _bounded_text(spec.get("base_type"), limit=32).upper()
    if slot not in GEAR_SLOTS or not base_type:
        return None
    max_sockets = max(0, min(MAX_SOCKETS, _safe_int(spec.get("max_sockets"), 0)))
    socketable = max_sockets > 0 and base_type in SOCKETABLE_BASE_TYPES
    gear = {
        "schema": SCHEMA,
        "version": VERSION,
        "slot": slot,
        "base_type": base_type,
        "socketable": socketable,
        "max_sockets": max_sockets if socketable else 0,
        "sockets": [],
        "runeword": None,
        "enchantments": [],
        "base_stats": _normalize_stats(spec.get("base_stats")),
        "stats": _normalize_stats(spec.get("base_stats")),
        "modifiers": [],
        "quality": "STANDARD",
    }
    return recalculate_gear(gear, source)


def normalize_gear(
    raw: Any,
    definition_id: Any,
    tables: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    source = tables if isinstance(tables, dict) else starter_tables()
    # Known item definitions always retain their authored slot/base contract;
    # the saved payload contributes only instance state.  Unknown authored
    # gear may still carry its own complete spec for editor-forward content.
    authored_spec = gear_spec_for_definition(definition_id, source)
    result = new_gear_state(definition_id, None, source)
    if result is None and isinstance(raw, dict):
        result = new_gear_state(definition_id, raw, source)
    if result is None:
        return None
    if isinstance(raw, dict):
        sockets = raw.get("sockets")
        if isinstance(sockets, list):
            result["sockets"] = copy.deepcopy(sockets[:MAX_SOCKETS])
        enchants = raw.get("enchantments")
        if isinstance(enchants, list):
            result["enchantments"] = copy.deepcopy(enchants[:MAX_ENCHANTMENTS])
        result["quality"] = _bounded_text(raw.get("quality"), "STANDARD", 16).upper()
        if result["quality"] not in QUALITY_LADDER:
            result["quality"] = "STANDARD"
        if authored_spec is None and isinstance(raw.get("base_stats"), dict):
            result["base_stats"] = _normalize_stats(raw.get("base_stats"))
    return recalculate_gear(result, source)


def gear_view(gear: Any) -> dict[str, Any] | None:
    if not isinstance(gear, dict):
        return None
    runeword = gear.get("runeword")
    return {
        "schema": str(gear.get("schema", SCHEMA)),
        "version": _safe_int(gear.get("version"), VERSION),
        "slot": _bounded_text(gear.get("slot"), limit=32),
        "base_type": _bounded_text(gear.get("base_type"), limit=32),
        "socketable": bool(gear.get("socketable")),
        "socket_capacity": max(0, min(MAX_SOCKETS, _safe_int(gear.get("max_sockets"), 0))),
        "socket_count": len(gear.get("sockets", [])) if isinstance(gear.get("sockets"), list) else 0,
        "sockets": copy.deepcopy(gear.get("sockets", [])[:MAX_SOCKETS]) if isinstance(gear.get("sockets"), list) else [],
        "runeword": copy.deepcopy(runeword) if isinstance(runeword, dict) else None,
        "enchantments": copy.deepcopy(gear.get("enchantments", [])[:MAX_ENCHANTMENTS]) if isinstance(gear.get("enchantments"), list) else [],
        "quality": _bounded_text(gear.get("quality"), "STANDARD", 16).upper(),
        "base_stats": _normalize_stats(gear.get("base_stats")),
        "stats": _normalize_stats(gear.get("stats")),
        "modifiers": copy.deepcopy(gear.get("modifiers", [])[:MAX_GEAR_MODIFIERS]) if isinstance(gear.get("modifiers"), list) else [],
    }


def insert_socket(
    gear: dict[str, Any],
    insertable_id: Any,
    tables: dict[str, Any] | None = None,
) -> tuple[bool, dict[str, Any]]:
    source = tables if isinstance(tables, dict) else starter_tables()
    if not isinstance(gear, dict):
        return False, {"error": "GEAR_INSTANCE_REQUIRED"}
    if not bool(gear.get("socketable")) or _safe_int(gear.get("max_sockets"), 0) <= 0:
        return False, {"error": "GEAR_NOT_SOCKETABLE"}
    sockets = gear.get("sockets")
    if not isinstance(sockets, list):
        sockets = []
        gear["sockets"] = sockets
    max_sockets = max(0, min(MAX_SOCKETS, _safe_int(gear.get("max_sockets"), 0)))
    if len(sockets) >= max_sockets:
        return False, {"error": "GEAR_SOCKETS_FULL", "socket_capacity": max_sockets}
    wanted = _bounded_text(insertable_id, limit=96)
    insertables = source.get("insertables", {})
    definition = insertables.get(wanted) if isinstance(insertables, dict) else None
    if not isinstance(definition, dict):
        return False, {"error": "GEAR_INSERTABLE_NOT_FOUND", "insertable_id": wanted}
    kind = _bounded_text(definition.get("kind"), limit=16).upper()
    if kind not in INSERTABLE_KINDS:
        return False, {"error": "GEAR_INSERTABLE_KIND_INVALID", "kind": kind}
    socket = {
        "index": len(sockets),
        "id": wanted,
        "name": _bounded_text(definition.get("name"), wanted, 64),
        "kind": kind,
        "level": max(1, _safe_int(definition.get("level"), 1)),
    }
    sockets.append(socket)
    recalculate_gear(gear, source)
    return True, {
        "action": "SOCKET",
        "socket": copy.deepcopy(socket),
        "socket_count": len(gear["sockets"]),
        "socket_capacity": max_sockets,
        "runeword": copy.deepcopy(gear.get("runeword")),
        "stats": copy.deepcopy(gear.get("stats", {})),
    }


def apply_enchant(
    gear: dict[str, Any],
    enchant_id: Any,
    tables: dict[str, Any] | None = None,
) -> tuple[bool, dict[str, Any]]:
    source = tables if isinstance(tables, dict) else starter_tables()
    if not isinstance(gear, dict):
        return False, {"error": "GEAR_INSTANCE_REQUIRED"}
    enchantments = gear.get("enchantments")
    if not isinstance(enchantments, list):
        enchantments = []
        gear["enchantments"] = enchantments
    if len(enchantments) >= MAX_ENCHANTMENTS:
        return False, {"error": "GEAR_ENCHANTMENT_SLOTS_FULL", "capacity": MAX_ENCHANTMENTS}
    wanted = _bounded_text(enchant_id, limit=96)
    definitions = source.get("enchantments", {})
    definition = definitions.get(wanted) if isinstance(definitions, dict) else None
    if not isinstance(definition, dict):
        return False, {"error": "GEAR_ENCHANTMENT_NOT_FOUND", "enchant_id": wanted}
    if any(isinstance(row, dict) and str(row.get("id")) == wanted for row in enchantments):
        return False, {"error": "GEAR_ENCHANTMENT_DUPLICATE", "enchant_id": wanted}
    allowed = {
        _bounded_text(value, limit=24).upper()
        for value in definition.get("allowed_categories", [])
    }
    category = "ARMOR" if _base_category(gear.get("base_type")) == "HELM" else _base_category(gear.get("base_type"))
    if allowed and category not in allowed:
        return False, {"error": "GEAR_ENCHANTMENT_SLOT_INVALID", "category": category}
    row = {
        "id": wanted,
        "name": _bounded_text(definition.get("name"), wanted, 64),
        "stat": _bounded_text(definition.get("stat"), limit=48).lower(),
        "value": _number(definition.get("value", 1)),
        "visual_fx": _bounded_text(definition.get("visual_fx"), limit=16).upper(),
    }
    row.update(_enchant_metadata(wanted))
    enchantments.append(row)
    recalculate_gear(gear, source)
    return True, {"action": "ENCHANT", "enchantment": copy.deepcopy(row), "stats": copy.deepcopy(gear.get("stats", {}))}


def craft(
    tables: dict[str, Any],
    recipe_id: Any,
    inventory: dict[str, int],
    *,
    station_id: Any = "",
    profession_level: int = 1,
) -> tuple[bool, dict[str, Any]]:
    """Consume bounded resources and return a deterministic quality result."""
    recipes = tables.get("recipes", {}) if isinstance(tables, dict) else {}
    wanted = _bounded_text(recipe_id, limit=96)
    recipe = recipes.get(wanted) if isinstance(recipes, dict) else None
    if not isinstance(recipe, dict):
        return False, {"error": "GEAR_RECIPE_NOT_FOUND", "recipe_id": wanted}
    required_station = _bounded_text(recipe.get("station_id"), limit=96)
    chosen_station = _bounded_text(station_id or required_station, limit=96)
    if required_station and chosen_station != required_station:
        return False, {
            "error": "GEAR_STATION_REQUIRED",
            "recipe_id": wanted,
            "station_id": required_station,
        }
    inputs = recipe.get("inputs", {})
    outputs = recipe.get("output", {})
    if not isinstance(inputs, dict) or not isinstance(outputs, dict):
        return False, {"error": "GEAR_RECIPE_INVALID", "recipe_id": wanted}
    normalized_inputs = {
        _bounded_text(item_id, limit=96): max(0, _safe_int(amount))
        for item_id, amount in list(inputs.items())[:MAX_RECIPE_INPUTS]
    }
    normalized_outputs = {
        _bounded_text(item_id, limit=96): max(0, _safe_int(amount))
        for item_id, amount in list(outputs.items())[:MAX_RECIPE_OUTPUTS]
    }
    for item_id, amount in normalized_inputs.items():
        if _safe_int(inventory.get(item_id)) < amount:
            return False, {
                "error": "GEAR_MATERIALS_MISSING",
                "recipe_id": wanted,
                "item_id": item_id,
                "required": amount,
                "available": max(0, _safe_int(inventory.get(item_id))),
            }
    for item_id, amount in normalized_inputs.items():
        inventory[item_id] = max(0, _safe_int(inventory.get(item_id)) - amount)
    for item_id, amount in normalized_outputs.items():
        inventory[item_id] = max(0, _safe_int(inventory.get(item_id)) + amount)
    difficulty = max(1, _safe_int(recipe.get("difficulty"), 1))
    level = max(1, min(100, _safe_int(profession_level, 1)))
    quality = (
        "ARTIFACT" if level >= difficulty + 6 else
        "MASTERWORK" if level >= difficulty + 3 else
        "FINE" if level >= difficulty + 1 else
        "STANDARD"
    )
    return True, {
        "action": "CRAFT",
        "recipe_id": wanted,
        "name": _bounded_text(recipe.get("name"), wanted, 96),
        "station_id": chosen_station,
        "profession": _bounded_text(recipe.get("profession"), limit=32).upper(),
        "profession_level": level,
        "difficulty": difficulty,
        "quality": quality,
        "inputs": normalized_inputs,
        "outputs": normalized_outputs,
    }


def asset_table_for_definitions(
    *groups: dict[str, Any],
    tables: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Build one inspectable asset table for items, gear and resources."""
    source = tables if isinstance(tables, dict) else starter_tables()
    result: dict[str, dict[str, Any]] = {}
    for group in groups:
        if not isinstance(group, dict):
            continue
        for definition_id, row in list(group.items())[:MAX_ASSET_ROWS]:
            if not isinstance(row, dict):
                continue
            asset_id = _bounded_text(row.get("asset_id"), str(definition_id), 96)
            if not asset_id:
                continue
            gear = gear_spec_for_definition(definition_id, source)
            result[asset_id] = {
                "asset_id": asset_id,
                "definition_id": _bounded_text(definition_id, limit=96),
                "name": _bounded_text(row.get("name"), definition_id, 96),
                "kind": _bounded_text(row.get("kind"), "ITEM", 32).upper(),
                "asset_state": "3D_CONTEXT_STATES",
                "visual_states": ["GROUND", "CONTAINER", "INVENTORY", "EQUIPPED", "POCKET"],
                "renderer": "NATIVE_ASSET_KIT",
                "geometry_mode": "PROCEDURAL_GEOMETRY",
                "geometry_key": asset_id,
                "style_id": "GG_CLAY_ASSET_KIT",
                "gear_slot": _bounded_text(gear.get("slot")) if isinstance(gear, dict) else "",
                "socketable": bool(gear and _safe_int(gear.get("max_sockets"), 0) > 0),
            }
    return dict(list(result.items())[:MAX_ASSET_ROWS])


def world_stations(tables: dict[str, Any]) -> list[dict[str, Any]]:
    stations = tables.get("workstations", {}) if isinstance(tables, dict) else {}
    result: list[dict[str, Any]] = []
    if not isinstance(stations, dict):
        return result
    for station_id, row in list(stations.items())[:MAX_PROFESSIONS]:
        if not isinstance(row, dict):
            continue
        position = row.get("position", {}) if isinstance(row.get("position"), dict) else {}
        result.append(
            {
                "id": _bounded_text(row.get("id"), station_id, 96),
                "name": _bounded_text(row.get("name"), station_id, 64),
                "kind": "STATION",
                "tags": [_bounded_text(tag, limit=24).upper() for tag in row.get("tags", [])[:8]],
                "x": _safe_float(position.get("x")),
                "y": _safe_float(position.get("y")),
                "z": _safe_float(position.get("z")),
            }
        )
    return result
