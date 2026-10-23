"""Authored content packs for the GAME ENGINE.

This file is deliberately data-first.  A pack is a bounded, mergeable page of
items, people, quests, dialogue, schedules and world events.  It can be
activated without replacing the authoritative simulation, which gives the
world a real streaming seam while keeping the original starter island stable
for old saves and regression tests.
"""

from __future__ import annotations

import copy
from typing import Any


SCHEMA = "gg.game-engine.content-packs.v1"
VERSION = 1
MAX_PACKS = 8
MAX_ROWS = 64


def _visual(
    asset_id: str,
    model: str,
    color: str,
    scale: tuple[float, float, float],
    *,
    spin: float = 12.0,
    float_m: float = 0.04,
) -> dict[str, Any]:
    """Give every authored item an explicit 3D state in every context."""
    states: dict[str, dict[str, Any]] = {}
    for context in ("GROUND", "CONTAINER", "INVENTORY", "EQUIPPED", "POCKET"):
        factor = 0.72 if context == "CONTAINER" else (0.82 if context == "EQUIPPED" else 1.0)
        states[context] = {
            "asset_id": asset_id,
            "renderer": "NATIVE_ASSET_KIT",
            "model": model,
            "scale": [round(value * factor, 4) for value in scale],
            "rotation": [0.0, 0.0, 0.0],
            "offset_y": 0.16 if context != "EQUIPPED" else 0.05,
            "float_m": float_m if context == "GROUND" else 0.0,
            "spin_deg_s": spin if context == "GROUND" else 0.0,
            "base_color": color,
        }
    return {"asset_id": asset_id, "states": states}


def _item(
    item_id: str,
    name: str,
    kind: str,
    rarity: str,
    level: int,
    *,
    tags: list[str],
    asset_id: str,
    model: str = "#Cube",
    color: str = "#8db89a",
    scale: tuple[float, float, float] = (0.24, 0.24, 0.24),
    stack_limit: int = 1,
    equip_slot: str = "",
    spin: float = 12.0,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": item_id,
        "name": name,
        "kind": kind,
        "rarity": rarity,
        "level": level,
        "stack_limit": stack_limit,
        "tags": list(tags),
        "asset_id": asset_id,
        "visual": _visual(asset_id, model, color, scale, spin=spin),
    }
    if equip_slot:
        row["equip_slot"] = equip_slot
        row["tags"].append("EQUIPMENT")
    return row


def _insertable(
    item_id: str,
    name: str,
    kind: str,
    level: int,
    color: str,
    effects: dict[str, dict[str, int]],
    *,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": item_id,
        "name": name,
        "kind": kind,
        "level": level,
        "tags": tags or [kind, "TIDEFALL"],
        "socket_effects": effects,
        "asset_id": item_id,
        "visual": _visual(item_id, "#Sphere", color, (0.14, 0.14, 0.14), spin=8.0),
    }


def _material(
    item_id: str,
    name: str,
    color: str,
    *,
    level: int = 1,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": item_id,
        "name": name,
        "kind": "MATERIAL",
        "level": level,
        "tags": tags or ["MATERIAL", "CRAFTING", "TIDEFALL"],
        "asset_id": item_id,
        "visual": _visual(item_id, "#Sphere", color, (0.13, 0.13, 0.13), spin=7.0),
    }


def tidefall_frontier() -> dict[str, Any]:
    """Return the first substantial authored world page as fresh data."""
    items = {
        "item.rusted_hatchet": _item(
            "item.rusted_hatchet", "Rusted Hatchet", "WEAPON", "UNCOMMON", 2,
            tags=["WEAPON", "MELEE", "AXE", "TIDEFALL"], asset_id="itemmesh.rusted_hatchet",
            color="#a87351", scale=(0.12, 0.58, 0.12), equip_slot="MAIN_HAND", spin=24.0,
        ),
        "item.driftwood_bow": _item(
            "item.driftwood_bow", "Driftwood Bow", "WEAPON", "RARE", 4,
            tags=["WEAPON", "RANGED", "BOW", "TIDEFALL"], asset_id="itemmesh.driftwood_bow",
            color="#b98558", scale=(0.12, 0.72, 0.12), equip_slot="RANGED", spin=18.0,
        ),
        "item.shellmail_vest": _item(
            "item.shellmail_vest", "Shellmail Vest", "ARMOR", "RARE", 4,
            tags=["ARMOR", "CHEST", "SHOREWARDENS"], asset_id="itemmesh.shellmail_vest",
            color="#6f9fa5", scale=(0.42, 0.42, 0.24), equip_slot="CHEST", spin=5.0,
        ),
        "item.coral_circlet": _item(
            "item.coral_circlet", "Coral Circlet", "ARMOR", "EPIC", 6,
            tags=["ARMOR", "HEAD", "MAGIC"], asset_id="itemmesh.coral_circlet",
            color="#d9878c", scale=(0.28, 0.18, 0.28), equip_slot="HEAD", spin=9.0,
        ),
        "item.mariner_gloves": _item(
            "item.mariner_gloves", "Mariner's Gloves", "ARMOR", "UNCOMMON", 3,
            tags=["ARMOR", "HANDS", "CRAFTING"], asset_id="itemmesh.mariner_gloves",
            color="#8dabc0", scale=(0.22, 0.16, 0.22), equip_slot="HANDS", spin=7.0,
        ),
        "item.stormboots": _item(
            "item.stormboots", "Stormboots", "ARMOR", "RARE", 5,
            tags=["ARMOR", "FEET", "MOBILITY"], asset_id="itemmesh.stormboots",
            color="#536d9b", scale=(0.25, 0.18, 0.32), equip_slot="FEET", spin=7.0,
        ),
        "item.deepwater_cloak": _item(
            "item.deepwater_cloak", "Deepwater Cloak", "ARMOR", "EPIC", 7,
            tags=["ARMOR", "BACK", "WATER"], asset_id="itemmesh.deepwater_cloak",
            color="#455c91", scale=(0.36, 0.46, 0.12), equip_slot="BACK", spin=6.0,
        ),
        "item.tidebreaker_axe": _item(
            "item.tidebreaker_axe", "Tidebreaker Axe", "WEAPON", "LEGENDARY", 8,
            tags=["WEAPON", "MELEE", "AXE", "LEGENDARY"], asset_id="itemmesh.tidebreaker_axe",
            color="#e5a04f", scale=(0.16, 0.8, 0.16), equip_slot="MAIN_HAND", spin=30.0,
        ),
        "item.rune_etched_buckler": _item(
            "item.rune_etched_buckler", "Rune-Etched Buckler", "ARMOR", "RARE", 5,
            tags=["ARMOR", "SHIELD", "SOCKETABLE"], asset_id="itemmesh.rune_buckler",
            color="#7184ad", scale=(0.32, 0.32, 0.12), equip_slot="OFF_HAND", spin=8.0,
        ),
        "item.tideglass_lantern": _item(
            "item.tideglass_lantern", "Tideglass Lantern", "UTILITY", "UNCOMMON", 3,
            tags=["UTILITY", "LIGHT", "EXPLORATION"], asset_id="itemmesh.tideglass_lantern",
            model="#Sphere", color="#e4c46c", scale=(0.2, 0.3, 0.2), equip_slot="OFF_HAND", spin=11.0,
        ),
        "item.stormheart": _item(
            "item.stormheart", "Stormheart", "TRINKET", "EPIC", 7,
            tags=["TRINKET", "LIGHTNING", "MAGIC"], asset_id="itemmesh.stormheart",
            model="#Sphere", color="#b88cff", scale=(0.2, 0.2, 0.2), equip_slot="TRINKET_1", spin=20.0,
        ),
        "item.gilded_compass": _item(
            "item.gilded_compass", "Gilded Compass", "TRINKET", "LEGENDARY", 9,
            tags=["TRINKET", "NAVIGATION", "LOOT"], asset_id="itemmesh.gilded_compass",
            model="#Sphere", color="#f0d26f", scale=(0.18, 0.18, 0.18), equip_slot="TRINKET_2", spin=25.0,
        ),
        "item.thronglet_seed": _item(
            "item.thronglet_seed", "Thronglet Seed", "MATERIAL", "ARTIFACT", 10,
            tags=["MATERIAL", "LIFE", "ARTIFACT"], asset_id="itemmesh.thronglet_seed",
            model="#Sphere", color="#df7eb5", scale=(0.16, 0.2, 0.16), stack_limit=20, spin=17.0,
        ),
        "item.murk_fang": _item(
            "item.murk_fang", "Murkfang", "MATERIAL", "UNCOMMON", 3,
            tags=["MATERIAL", "MONSTER", "CRAFTING"], asset_id="itemmesh.murk_fang",
            model="#Cone", color="#a4b47b", scale=(0.12, 0.3, 0.12), stack_limit=99, spin=10.0,
        ),
        "item.coral_fragment": _item(
            "item.coral_fragment", "Coral Fragment", "MATERIAL", "COMMON", 2,
            tags=["MATERIAL", "CORAL", "CRAFTING"], asset_id="itemmesh.coral_fragment",
            model="#Cylinder", color="#d9878c", scale=(0.15, 0.2, 0.15), stack_limit=99, spin=8.0,
        ),
        "item.void_pearl": _item(
            "item.void_pearl", "Void Pearl", "MATERIAL", "EPIC", 7,
            tags=["MATERIAL", "MAGIC", "JEWELCRAFTING"], asset_id="itemmesh.void_pearl",
            model="#Sphere", color="#654a98", scale=(0.15, 0.15, 0.15), stack_limit=20, spin=16.0,
        ),
        "item.healing_tonic": _item(
            "item.healing_tonic", "Healing Tonic", "CONSUMABLE", "COMMON", 2,
            tags=["CONSUMABLE", "RECOVERY", "ALCHEMY"], asset_id="itemmesh.healing_tonic",
            model="#Cylinder", color="#d26c78", scale=(0.14, 0.28, 0.14), stack_limit=20, spin=6.0,
        ),
        "item.smoked_fish": _item(
            "item.smoked_fish", "Smoked Fish", "CONSUMABLE", "COMMON", 2,
            tags=["CONSUMABLE", "FOOD", "SURVIVAL"], asset_id="itemmesh.smoked_fish",
            model="#Cube", color="#b87d55", scale=(0.3, 0.12, 0.15), stack_limit=20, spin=4.0,
        ),
        "item.tidegate_key": _item(
            "item.tidegate_key", "Tidegate Key", "QUEST", "RARE", 5,
            tags=["QUEST", "KEY", "TIDEGATE"], asset_id="itemmesh.tidegate_key",
            model="#Cylinder", color="#e4c46c", scale=(0.08, 0.3, 0.08), spin=15.0,
        ),
        "item.sunken_relic": _item(
            "item.sunken_relic", "Sunken Relic", "QUEST", "ARTIFACT", 10,
            tags=["QUEST", "RELIC", "ARTIFACT"], asset_id="itemmesh.sunken_relic",
            model="#Sphere", color="#f0d26f", scale=(0.22, 0.22, 0.22), spin=18.0,
        ),
    }

    gear_specs = {
        "item.rusted_hatchet": {"slot": "MAIN_HAND", "base_type": "AXE", "max_sockets": 2, "base_stats": {"damage": 8, "durability": 70}},
        "item.driftwood_bow": {"slot": "RANGED", "base_type": "BOW", "max_sockets": 3, "base_stats": {"damage": 7, "crit": 2, "durability": 65}},
        "item.shellmail_vest": {"slot": "CHEST", "base_type": "CHEST_ARMOR", "max_sockets": 3, "base_stats": {"armor": 12, "grit": 8, "durability": 110}},
        "item.coral_circlet": {"slot": "HEAD", "base_type": "HELM", "max_sockets": 2, "base_stats": {"armor": 6, "spirit": 8, "loot_find": 3}},
        "item.mariner_gloves": {"slot": "HANDS", "base_type": "GAUNTLETS", "max_sockets": 0, "base_stats": {"finesse": 4, "craft_speed": 2}},
        "item.stormboots": {"slot": "FEET", "base_type": "BOOTS", "max_sockets": 0, "base_stats": {"move_speed": 2, "swim_speed": 2}},
        "item.deepwater_cloak": {"slot": "BACK", "base_type": "CLOAK", "max_sockets": 0, "base_stats": {"swim_speed": 4, "damage_reduction": 2}},
        "item.tidebreaker_axe": {"slot": "MAIN_HAND", "base_type": "AXE", "max_sockets": 3, "base_stats": {"damage": 16, "crit": 4, "durability": 130}},
        "item.rune_etched_buckler": {"slot": "OFF_HAND", "base_type": "SHIELD", "max_sockets": 2, "base_stats": {"armor": 9, "damage_reduction": 2, "durability": 90}},
        "item.tideglass_lantern": {"slot": "OFF_HAND", "base_type": "LANTERN", "max_sockets": 0, "base_stats": {"spirit": 3, "sense_radius": 2}},
        "item.stormheart": {"slot": "TRINKET_1", "base_type": "CHARM", "max_sockets": 0, "base_stats": {"lightning_damage": 5, "crit": 3}},
        "item.gilded_compass": {"slot": "TRINKET_2", "base_type": "COMPASS", "max_sockets": 0, "base_stats": {"navigation": 4, "loot_find": 5}},
    }

    runes = {
        "rune.amn": _insertable("rune.amn", "Amn Rune", "RUNE", 7, "#e9d08d", {"WEAPON": {"life_steal": 2}, "ARMOR": {"health": 5}, "DEFAULT": {"grit": 1}}),
        "rune.ko": _insertable("rune.ko", "Ko Rune", "RUNE", 8, "#a6b9d6", {"WEAPON": {"damage": 3}, "ARMOR": {"armor": 3}, "DEFAULT": {"finesse": 2}}),
        "rune.umbra": _insertable("rune.umbra", "Umbra Rune", "RUNE", 9, "#765b9f", {"WEAPON": {"shadow_damage": 5}, "ARMOR": {"damage_reduction": 3}, "DEFAULT": {"spirit": 2}}),
        "rune.vex": _insertable("rune.vex", "Vex Rune", "RUNE", 10, "#df7eb5", {"WEAPON": {"damage_pct": 6}, "ARMOR": {"health": 8}, "DEFAULT": {"crit": 2}}),
    }
    gems = {
        "gem.sapphire": _insertable("gem.sapphire", "Tide Sapphire", "GEM", 5, "#70a9e8", {"WEAPON": {"ice_damage": 3}, "ARMOR": {"water_resist": 4}, "DEFAULT": {"swim_speed": 2}}),
        "gem.emerald": _insertable("gem.emerald", "Wild Emerald", "GEM", 5, "#76c47d", {"WEAPON": {"poison_damage": 3}, "ARMOR": {"nature_resist": 4}, "DEFAULT": {"loot_find": 2}}),
        "gem.amethyst": _insertable("gem.amethyst", "Storm Amethyst", "GEM", 7, "#b88cff", {"WEAPON": {"lightning_damage": 4}, "ARMOR": {"storm_resist": 5}, "DEFAULT": {"spell_power": 3}}),
        "gem.onyx": _insertable("gem.onyx", "Void Onyx", "GEM", 8, "#4c536c", {"WEAPON": {"shadow_damage": 4}, "ARMOR": {"damage_reduction": 2}, "DEFAULT": {"grit": 3}}),
    }
    runewords = {
        "runeword.stormcall": {
            "id": "runeword.stormcall", "name": "Stormcall", "sequence": ["rune.ort", "rune.ral", "rune.ko"],
            "socket_count": 3, "allowed_base_types": ["SWORD", "AXE", "BOW"],
            "bonuses": {"damage": 8, "lightning_damage": 8, "crit": 4},
        },
        "runeword.deepward": {
            "id": "runeword.deepward", "name": "Deepward", "sequence": ["rune.tal", "rune.ith", "rune.umbra"],
            "socket_count": 3, "allowed_base_types": ["CHEST_ARMOR", "SHIELD", "HELM"],
            "bonuses": {"armor": 10, "damage_reduction": 6, "water_resist": 8},
        },
        "runeword.wayfarer": {
            "id": "runeword.wayfarer", "name": "Wayfarer", "sequence": ["rune.tir", "rune.ko"],
            "socket_count": 2, "allowed_base_types": ["BOW", "AXE", "SWORD"],
            "bonuses": {"move_speed": 3, "loot_find": 4, "travel_speed": 3},
        },
    }
    enchantments = {
        "enchant.stormedge": {"id": "enchant.stormedge", "name": "Stormedge", "stat": "lightning_damage", "value": 5, "allowed_categories": ["WEAPON"]},
        "enchant.scavenger": {"id": "enchant.scavenger", "name": "Scavenger's Eye", "stat": "loot_find", "value": 4, "allowed_categories": ["ARMOR", "HELM", "UTILITY"]},
        "enchant.deepward": {"id": "enchant.deepward", "name": "Deepwarding", "stat": "damage_reduction", "value": 4, "allowed_categories": ["ARMOR", "HELM"]},
        "enchant.tide-step": {"id": "enchant.tide-step", "name": "Tide-Step", "stat": "move_speed", "value": 3, "allowed_categories": ["ARMOR", "UTILITY"]},
    }
    materials = {
        "material.coral": _material("material.coral", "Living Coral", "#d9878c", level=2),
        "material.murk_fang": _material("material.murk_fang", "Murkfang", "#a4b47b", level=3),
        "material.storm_iron": _material("material.storm_iron", "Storm Iron", "#7184ad", level=6),
        "material.void_pearl": _material("material.void_pearl", "Void Pearl", "#654a98", level=7),
        "material.tide_silk": _material("material.tide_silk", "Tide Silk", "#70a9e8", level=4),
        "material.bone": _material("material.bone", "Saltbone", "#d6d6d6", level=2),
    }
    gear = {
        "gear_specs": gear_specs,
        "runes": runes,
        "gems": gems,
        "runewords": runewords,
        "enchantments": enchantments,
        "materials": materials,
        "insertables": {**runes, **gems},
        "workstations": {
            "station.tideforge": {"id": "station.tideforge", "name": "Tideforge", "kind": "FORGE", "tags": ["BLACKSMITHING", "WEAPON", "ARMOR"], "position": {"x": -3.5, "y": 0.0, "z": 8.0}},
            "station.alchemy": {"id": "station.alchemy", "name": "Saltglass Still", "kind": "ALCHEMY", "tags": ["ALCHEMY", "RECOVERY"], "position": {"x": 8.0, "y": 0.0, "z": 7.0}},
            "station.jewelbench": {"id": "station.jewelbench", "name": "Coral Jewelbench", "kind": "JEWELCRAFT", "tags": ["JEWELCRAFTING", "GEMS"], "position": {"x": -7.0, "y": 0.0, "z": -7.0}},
        },
        "recipes": {
            "recipe.tideforge_hatchet": {"id": "recipe.tideforge_hatchet", "name": "Forge Rusted Hatchet", "inputs": {"material.storm_iron": 2, "material.bone": 1}, "output": {"item.rusted_hatchet": 1}, "station_id": "station.tideforge", "profession": "BLACKSMITHING", "difficulty": 2},
            "recipe.shellmail_vest": {"id": "recipe.shellmail_vest", "name": "Weave Shellmail", "inputs": {"material.coral": 3, "material.tide_silk": 2, "material.bone": 2}, "output": {"item.shellmail_vest": 1}, "station_id": "station.tideforge", "profession": "LEATHERWORKING", "difficulty": 4},
            "recipe.stormheart": {"id": "recipe.stormheart", "name": "Cut Stormheart", "inputs": {"material.void_pearl": 2, "material.storm_iron": 1}, "output": {"item.stormheart": 1}, "station_id": "station.jewelbench", "profession": "JEWELCRAFTING", "difficulty": 6},
            "recipe.healing_tonic": {"id": "recipe.healing_tonic", "name": "Brew Healing Tonic", "inputs": {"item.sun_herb": 2, "material.coral": 1}, "output": {"item.healing_tonic": 2}, "station_id": "station.alchemy", "profession": "ENCHANTING", "difficulty": 2},
        },
    }

    individuals = {
        "npc-smith-01": {"id": "npc-smith-01", "name": "Kessa Stormanvil", "role": "BLACKSMITH", "archetype": "WANDERER", "occupation": "BLACKSMITH", "faction_id": "SHOREWARDENS", "personality": ["PRECISE", "PROUD"], "needs": {"hunger": 0.24, "thirst": 0.32, "fatigue": 0.44, "curiosity": 0.58}, "goals": [{"id": "goal.rebuild-tideforge", "kind": "CRAFT", "target": "station.tideforge"}], "inventory": ["material.storm_iron", "material.bone", "item.rusted_hatchet"], "equipment": ["item.shellmail_vest", "item.rusted_hatchet"], "home": {"x": -3.5, "y": 0.0, "z": 8.0}, "action": "CRAFT", "activity": "CRAFT"},
        "npc-freebooter-02": {"id": "npc-freebooter-02", "name": "Jax Brasshook", "role": "RAIDER", "archetype": "WANDERER", "occupation": "RAIDER", "faction_id": "FREEBOOTERS", "personality": ["BOLD", "GREEDY"], "needs": {"hunger": 0.3, "thirst": 0.39, "fatigue": 0.25, "curiosity": 0.76}, "goals": [{"id": "goal.find-legendary", "kind": "INSPECT_LOOT", "target": "legendary"}], "inventory": ["item.murk_fang", "item.smoked_fish"], "equipment": ["item.driftwood_bow"], "home": {"x": 10.0, "y": 0.0, "z": -6.0}, "action": "EXPLORE", "activity": "EXPLORE"},
        "npc-wildkin-02": {"id": "npc-wildkin-02", "name": "Mossback", "role": "WILDLIFE", "archetype": "CRITTER", "occupation": "FORAGER", "faction_id": "WILDKIN", "personality": ["ALERT", "PATIENT"], "needs": {"hunger": 0.62, "thirst": 0.46, "fatigue": 0.18, "curiosity": 0.88}, "goals": [{"id": "goal.grow-thronglet", "kind": "GATHER", "target": "thronglet"}], "inventory": ["item.thronglet_seed", "item.sun_herb"], "equipment": [], "home": {"x": -8.0, "y": 0.0, "z": -7.0}, "action": "GATHER", "activity": "GATHER"},
        "npc-herbalist-01": {"id": "npc-herbalist-01", "name": "Vela Reedbloom", "role": "HERBALIST", "archetype": "WANDERER", "occupation": "FORAGER", "faction_id": "WAYFARERS", "personality": ["KIND", "FOCUSED"], "needs": {"hunger": 0.27, "thirst": 0.41, "fatigue": 0.29, "curiosity": 0.7}, "goals": [{"id": "goal.brew-remedy", "kind": "CRAFT", "target": "station.alchemy"}], "inventory": ["item.sun_herb", "material.coral"], "equipment": ["item.coral_circlet"], "home": {"x": 8.0, "y": 0.0, "z": 7.0}, "action": "CRAFT", "activity": "CRAFT"},
        "npc-cartographer-02": {"id": "npc-cartographer-02", "name": "Tollan Bluechart", "role": "SCOUT", "archetype": "WANDERER", "occupation": "SCOUT", "faction_id": "WAYFARERS", "personality": ["CURIOUS", "RESTLESS"], "needs": {"hunger": 0.31, "thirst": 0.36, "fatigue": 0.38, "curiosity": 0.91}, "goals": [{"id": "goal.map-tidegate", "kind": "EXPLORE", "target": "tidegate"}], "inventory": ["item.tideglass_lantern", "item.gilded_compass"], "equipment": ["item.stormboots", "item.gilded_compass"], "home": {"x": -7.0, "y": 0.0, "z": -7.0}, "action": "EXPLORE", "activity": "EXPLORE"},
        "npc-tender-01": {"id": "npc-tender-01", "name": "Nix Seedkeeper", "role": "FORAGER", "archetype": "WANDERER", "occupation": "FORAGER", "faction_id": "WILDKIN", "personality": ["PLAYFUL", "SOCIABLE"], "needs": {"hunger": 0.44, "thirst": 0.52, "fatigue": 0.22, "curiosity": 0.97}, "goals": [{"id": "goal.share-seeds", "kind": "GATHER", "target": "thronglet"}], "inventory": ["item.thronglet_seed", "item.coral_fragment"], "equipment": ["item.mariner_gloves"], "home": {"x": 1.0, "y": 0.0, "z": -11.0}, "action": "GATHER", "activity": "GATHER"},
        "npc-salvager-02": {"id": "npc-salvager-02", "name": "Odo Ninepockets", "role": "SCAVENGER", "archetype": "WANDERER", "occupation": "SCAVENGER", "faction_id": "FREEBOOTERS", "personality": ["SUSPICIOUS", "RESOURCEFUL"], "needs": {"hunger": 0.36, "thirst": 0.42, "fatigue": 0.47, "curiosity": 0.66}, "goals": [{"id": "goal.open-reliquary", "kind": "INSPECT_LOOT", "target": "reliquary"}], "inventory": ["item.void_pearl", "item.old_boot"], "equipment": ["item.rune_etched_buckler"], "home": {"x": 11.0, "y": 0.0, "z": 4.0}, "action": "INSPECT_LOOT", "activity": "INSPECT_LOOT"},
        "npc-keeper-02": {"id": "npc-keeper-02", "name": "Aris Tideledger", "role": "GUARDIAN", "archetype": "GUARDIAN", "occupation": "WARDEN", "faction_id": "SHOREWARDENS", "personality": ["DUTIFUL", "CALM"], "needs": {"hunger": 0.2, "thirst": 0.3, "fatigue": 0.33, "curiosity": 0.4}, "goals": [{"id": "goal.guard-tidegate", "kind": "GUARD", "target": "tidegate"}], "inventory": ["item.tidegate_key", "item.healing_tonic"], "equipment": ["item.deepwater_cloak", "item.rune_etched_buckler"], "home": {"x": -12.0, "y": 0.0, "z": 1.0}, "action": "GUARD", "activity": "WANDER"},
        "npc-relic-warden-01": {"id": "npc-relic-warden-01", "name": "The Reliquary Warden", "role": "GUARDIAN", "archetype": "GUARDIAN", "occupation": "WARDEN", "faction_id": "SHOREWARDENS", "personality": ["ANCIENT", "CAUTIOUS"], "needs": {"hunger": 0.1, "thirst": 0.1, "fatigue": 0.08, "curiosity": 0.61}, "goals": [{"id": "goal.protect-relic", "kind": "GUARD", "target": "sunken-relic"}], "inventory": ["item.sunken_relic"], "equipment": ["item.tidebreaker_axe", "item.coral_circlet"], "home": {"x": 13.0, "y": 0.0, "z": 10.0}, "action": "GUARD", "activity": "WANDER"},
    }

    dialogue = {
        "npc-smith-01": {"id": "npc-smith-01", "speaker": "Kessa Stormanvil", "start": "start", "nodes": {"start": {"id": "start", "text": "The old forge can make more than repairs. It can give a person a future worth defending.", "choices": [{"id": "tideforge", "label": "Rebuild the forge", "text": "I will bring you the materials.", "next": "forge", "effects": [{"kind": "ACCEPT_QUEST", "quest_id": "quest.tideforge"}, {"kind": "RELATIONSHIP", "amount": 0.08}]}, {"id": "runes", "label": "Ask about runewords", "text": "What makes a runeword hold?", "next": "runes"}, {"id": "leave", "label": "Leave", "text": "I will return.", "next": "end"}]}, "forge": {"id": "forge", "text": "Good. The first honest hammer strike is louder than any boast.", "choices": [{"id": "leave", "label": "Go gather", "text": "The island will provide.", "next": "end"}]}, "runes": {"id": "runes", "text": "Order, base and intention. If one is false, the word becomes scrap.", "choices": [{"id": "leave", "label": "Remember", "text": "I will make it count.", "next": "end"}]}, "end": {"id": "end", "text": "Kessa returns to the anvil.", "choices": []}}},
        "npc-freebooter-02": {"id": "npc-freebooter-02", "speaker": "Jax Brasshook", "start": "start", "nodes": {"start": {"id": "start", "text": "There is always a better haul somewhere. The trick is deciding what you are willing to risk for it.", "choices": [{"id": "debt", "label": "Take the risky job", "text": "Show me where the good loot is.", "next": "debt", "effects": [{"kind": "ACCEPT_QUEST", "quest_id": "quest.freebooter-debt"}, {"kind": "FACTION", "faction_id": "FREEBOOTERS", "amount": 0.05}]}, {"id": "auction", "label": "Ask about the market", "text": "Who is buying today?", "next": "market"}, {"id": "leave", "label": "Leave", "text": "Keep your powder dry.", "next": "end"}]}, "debt": {"id": "debt", "text": "Bring me a legendary find and the crew will stop calling you ballast.", "choices": [{"id": "leave", "label": "Hunt", "text": "I will return with proof.", "next": "end"}]}, "market": {"id": "market", "text": "Runes, gems and anything that makes a rival look twice.", "choices": [{"id": "leave", "label": "Close deal", "text": "Noted.", "next": "end"}]}, "end": {"id": "end", "text": "Jax watches the horizon for a profitable mistake.", "choices": []}}},
        "npc-wildkin-02": {"id": "npc-wildkin-02", "speaker": "Mossback", "start": "start", "nodes": {"start": {"id": "start", "text": "The little seeds listen. They remember footsteps, kindness and fire.", "choices": [{"id": "wildkin-truce", "label": "Offer a truce", "text": "We can share the living shore.", "next": "truce", "effects": [{"kind": "ACCEPT_QUEST", "quest_id": "quest.wildkin-truce"}, {"kind": "FACTION", "faction_id": "WILDKIN", "amount": 0.08}]}, {"id": "seeds", "label": "Ask about seeds", "text": "What do they become?", "next": "seeds"}, {"id": "leave", "label": "Leave", "text": "Grow well.", "next": "end"}]}, "truce": {"id": "truce", "text": "Then walk softly, and do not take the last seed from a hungry nest.", "choices": [{"id": "leave", "label": "Agree", "text": "I will remember.", "next": "end"}]}, "seeds": {"id": "seeds", "text": "A seed is a tiny world. Give it time and it gives a world back.", "choices": [{"id": "leave", "label": "Listen", "text": "The island is speaking.", "next": "end"}]}, "end": {"id": "end", "text": "Mossback returns to the reeds.", "choices": []}}},
        "npc-herbalist-01": {"id": "npc-herbalist-01", "speaker": "Vela Reedbloom", "start": "start", "nodes": {"start": {"id": "start", "text": "A living world needs healers as much as heroes. Bring me ingredients and I can keep both moving.", "choices": [{"id": "remedy", "label": "Learn the remedy", "text": "I will help brew it.", "next": "remedy", "effects": [{"kind": "ACCEPT_QUEST", "quest_id": "quest.reedbloom-remedy"}, {"kind": "RELATIONSHIP", "amount": 0.07}]}, {"id": "leave", "label": "Leave", "text": "Stay safe.", "next": "end"}]}, "remedy": {"id": "remedy", "text": "The still is patient. Let the ingredients keep their own voices.", "choices": [{"id": "leave", "label": "Gather", "text": "I will be back.", "next": "end"}]}, "end": {"id": "end", "text": "Vela checks the next vial.", "choices": []}}},
        "npc-cartographer-02": {"id": "npc-cartographer-02", "speaker": "Tollan Bluechart", "start": "start", "nodes": {"start": {"id": "start", "text": "Every road is a story someone decided to remember. The tidegate is writing a dangerous chapter.", "choices": [{"id": "chart", "label": "Map the tidegate", "text": "Point me toward the next landmark.", "next": "chart", "effects": [{"kind": "ACCEPT_QUEST", "quest_id": "quest.bluechart"}, {"kind": "RELATIONSHIP", "amount": 0.05}]}, {"id": "leave", "label": "Leave", "text": "Keep the map dry.", "next": "end"}]}, "chart": {"id": "chart", "text": "Follow the lanterns, then listen for the gate before you see it.", "choices": [{"id": "leave", "label": "Set out", "text": "I know the way.", "next": "end"}]}, "end": {"id": "end", "text": "Tollan adds another mark to the chart.", "choices": []}}},
    }

    return {
        "schema": SCHEMA,
        "version": VERSION,
        "id": "pack.tidefall-frontier",
        "name": "Tidefall Frontier",
        "description": "A living shoreline page with factions, crafted gear, named residents and recurring events.",
        "items": items,
        "containers": {
            "container.fisher_cache": {"id": "container.fisher_cache", "name": "Fisher's Cache", "kind": "CONTAINER", "rarity": "UNCOMMON", "level": 3, "stack_limit": 1, "tags": ["CONTAINER", "LOOT", "FISHER"], "asset_id": "container.fisher_cache", "visual": _visual("container.fisher_cache", "#Cube", "#6f9fa5", (0.9, 0.62, 0.9), spin=0.0, float_m=0.01)},
            "container.sunken_reliquary": {"id": "container.sunken_reliquary", "name": "Sunken Reliquary", "kind": "CONTAINER", "rarity": "EPIC", "level": 8, "stack_limit": 1, "tags": ["CONTAINER", "LOOT", "RELIC"], "asset_id": "container.sunken_reliquary", "visual": _visual("container.sunken_reliquary", "#Cube", "#765b9f", (1.0, 0.7, 1.0), spin=0.0, float_m=0.01)},
        },
        "loot_tables": {
            "loot.tidegate-assault": {"id": "loot.tidegate-assault", "name": "Tidegate Assault", "entries": [{"item_id": "item.tidegate_key", "weight": 16, "min": 1, "max": 1}, {"item_id": "item.shellmail_vest", "weight": 10, "min": 1, "max": 1}, {"item_id": "rune.ko", "weight": 8, "min": 1, "max": 1}, {"item_id": "gem.sapphire", "weight": 7, "min": 1, "max": 1}, {"item_id": "material.storm_iron", "weight": 22, "min": 1, "max": 2}, {"item_id": "item.healing_tonic", "weight": 18, "min": 1, "max": 2}]},
            "loot.freebooter-haul": {"id": "loot.freebooter-haul", "name": "Freebooter Haul", "entries": [{"item_id": "item.driftwood_bow", "weight": 13, "min": 1, "max": 1}, {"item_id": "item.tidebreaker_axe", "weight": 2, "min": 1, "max": 1}, {"item_id": "rune.vex", "weight": 3, "min": 1, "max": 1}, {"item_id": "gem.onyx", "weight": 6, "min": 1, "max": 1}, {"item_id": "material.void_pearl", "weight": 7, "min": 1, "max": 1}, {"item_id": "item.smoked_fish", "weight": 25, "min": 1, "max": 2}]},
            "loot.wildkin-bloom": {"id": "loot.wildkin-bloom", "name": "Wildkin Bloom", "entries": [{"item_id": "item.thronglet_seed", "weight": 14, "min": 1, "max": 2}, {"item_id": "item.coral_circlet", "weight": 4, "min": 1, "max": 1}, {"item_id": "gem.emerald", "weight": 9, "min": 1, "max": 1}, {"item_id": "material.coral", "weight": 28, "min": 1, "max": 3}, {"item_id": "item.sun_herb", "weight": 31, "min": 1, "max": 3}]},
        },
        "gear": gear,
        "recipes": {
            "recipe.smoked_fish": {"id": "recipe.smoked_fish", "name": "Smoke Fish", "inputs": {"item.sea_salt": 1, "material.bone": 1}, "output": {"item.smoked_fish": 2}, "skill": "SURVIVAL"},
            "recipe.tideglass_lantern": {"id": "recipe.tideglass_lantern", "name": "Shape Tideglass Lantern", "inputs": {"material.coral": 2, "material.tide_silk": 1}, "output": {"item.tideglass_lantern": 1}, "skill": "SURVIVAL"},
        },
        "npc_individuals": individuals,
        "npc_spawns": [
            {"id": "npc-smith-01", "archetype": "WANDERER", "x": -3.5, "z": 8.0, "scale": (1.0, 1.18, 1.0), "color": "#c98989", "phase": 1.1},
            {"id": "npc-freebooter-02", "archetype": "WANDERER", "x": 10.0, "z": -6.0, "scale": (0.94, 1.08, 0.94), "color": "#d7a36f", "phase": 2.6},
            {"id": "npc-wildkin-02", "archetype": "CRITTER", "x": -8.0, "z": -7.0, "scale": (0.78, 0.9, 0.78), "color": "#8db89a", "phase": 3.4},
            {"id": "npc-herbalist-01", "archetype": "WANDERER", "x": 8.0, "z": 7.0, "scale": (0.88, 1.05, 0.88), "color": "#76c47d", "phase": 4.8},
            {"id": "npc-cartographer-02", "archetype": "WANDERER", "x": -7.0, "z": -7.0, "scale": (0.86, 1.08, 0.86), "color": "#70a9e8", "phase": 5.5},
            {"id": "npc-keeper-02", "archetype": "GUARDIAN", "x": -12.0, "z": 1.0, "scale": (1.0, 1.25, 1.0), "color": "#7fa9c4", "phase": 6.1},
            {"id": "npc-fisher-01", "archetype": "WANDERER", "x": 1.4, "z": 12.8, "scale": (0.92, 1.08, 0.92), "color": "#c8a97e", "phase": 1.15},
            {"id": "npc-hut-01", "archetype": "WANDERER", "x": 7.2, "z": 9.0, "scale": (0.88, 1.04, 0.88), "color": "#e2c094", "phase": 2.85},
            {"id": "npc-hut-02", "archetype": "WANDERER", "x": -1.2, "z": -7.2, "scale": (0.9, 1.06, 0.9), "color": "#d9b88a", "phase": 3.55},
        ],
        "ambient_life": [
            {"id": "ambient-diver-01", "role": "DIVER", "route": "SHORE_ORBIT", "activity_day": "GATHER", "x": -9.0, "z": 8.0, "radius": 1.7, "speed": 0.55, "phase": 0.8, "sense_radius": 5.5, "color": "#70a9e8", "scale": (0.78, 0.95, 0.78)},
            {"id": "ambient-miner-01", "role": "SCOUT", "route": "RIDGE_SWEEP", "activity_day": "SCOUTING", "x": 11.0, "z": 9.0, "radius": 2.3, "speed": 0.48, "phase": 2.2, "sense_radius": 5.5, "color": "#a6b9d6", "scale": (0.82, 1.0, 0.82)},
            {"id": "ambient-runner-02", "role": "TRAVELER", "route": "ROAD_LOOP", "activity_day": "TRAVELING", "x": -11.0, "z": -8.0, "radius": 2.0, "speed": 0.58, "phase": 3.9, "sense_radius": 5.5, "color": "#d9878c", "scale": (0.76, 0.94, 0.76)},
            {"id": "ambient-gatherer-01", "role": "FORAGER", "route": "CRATE_RUN", "activity_day": "GATHER", "x": 9.0, "z": 11.0, "radius": 1.8, "speed": 0.42, "phase": 5.1, "sense_radius": 5.5, "color": "#8db89a", "scale": (0.84, 1.0, 0.84)},
        ],
        "dialogue": dialogue,
        "quests": {
            "quest.tideforge": {"id": "quest.tideforge", "name": "The Tideforge Rekindled", "description": "Craft a serviceable hatchet and put the tideforge back into the island's hands.", "giver_id": "npc-smith-01", "objective": {"kind": "CRAFT", "definition_id": "item.rusted_hatchet", "required": 1, "label": "Craft a Rusted Hatchet"}, "rewards": {"xp": 180, "gold": 55, "items": ["item.storm_iron"], "faction": {"SHOREWARDENS": 18}}, "unlocks": ["quest.stormcall"]},
            "quest.stormcall": {"id": "quest.stormcall", "name": "Call the Storm", "description": "Turn a socketed weapon into a named runeword and prove that crafting can change a fight.", "giver_id": "npc-smith-01", "prerequisites": ["quest.tideforge"], "objective": {"kind": "ACQUIRE_GEAR", "rarity_at_least": "RARE", "required": 1, "label": "Acquire rare-or-better gear"}, "rewards": {"xp": 240, "gold": 90, "items": ["rune.vex"], "faction": {"SHOREWARDENS": 12}}},
            "quest.freebooter-debt": {"id": "quest.freebooter-debt", "name": "A Debt in Salt", "description": "Find a legendary haul before the freebooters decide you are bad luck.", "giver_id": "npc-freebooter-02", "objective": {"kind": "ACQUIRE_GEAR", "rarity_at_least": "LEGENDARY", "required": 1, "label": "Acquire legendary gear"}, "rewards": {"xp": 260, "gold": 120, "items": ["gem.onyx"], "faction": {"FREEBOOTERS": 20}}},
            "quest.wildkin-truce": {"id": "quest.wildkin-truce", "name": "The Seeded Truce", "description": "Speak with the wildkin and protect one living seed from the next hungry tide.", "giver_id": "npc-wildkin-02", "objective": {"kind": "TALK", "target_id": "npc-wildkin-02", "choice_id": "wildkin-truce", "required": 1, "label": "Offer Mossback a truce"}, "rewards": {"xp": 150, "gold": 35, "items": ["item.thronglet_seed"], "faction": {"WILDKIN": 22}}},
            "quest.reedbloom-remedy": {"id": "quest.reedbloom-remedy", "name": "Reedbloom Remedy", "description": "Craft a tonic so the next expedition can return alive.", "giver_id": "npc-herbalist-01", "objective": {"kind": "CRAFT", "definition_id": "item.healing_tonic", "required": 1, "label": "Craft a Healing Tonic"}, "rewards": {"xp": 135, "gold": 45, "items": ["item.smoked_fish"], "faction": {"WAYFARERS": 15}}},
            "quest.bluechart": {"id": "quest.bluechart", "name": "Bluechart Tidegate", "description": "Follow the living routes and recover the key that opens the next page of the shore.", "giver_id": "npc-cartographer-02", "objective": {"kind": "ACQUIRE_GEAR", "definition_id": "item.tidegate_key", "rarity_at_least": "RARE", "required": 1, "label": "Recover the Tidegate Key"}, "rewards": {"xp": 210, "gold": 70, "items": ["item.gilded_compass"], "faction": {"WAYFARERS": 18}}},
        },
        "world_events": {
            "event.tidegate-siege": {"id": "event.tidegate-siege", "name": "Tidegate Siege", "description": "Shorewardens and wildkin contest the old gate while the tide rises.", "faction_id": "SHOREWARDENS", "trigger_after_s": 8.0, "duration_s": 22.0, "location": {"x": -12.0, "z": 1.0}, "loot_table_id": "loot.tidegate-assault", "reward_item_id": "item.tidegate_key", "reward_quantity": 1, "standing": {"SHOREWARDENS": 5, "WILDKIN": -3}},
            "event.freebooter-auction": {"id": "event.freebooter-auction", "name": "Freebooter Auction", "description": "A moving market appears, and every resident has a different price for risk.", "faction_id": "FREEBOOTERS", "trigger_after_s": 24.0, "duration_s": 20.0, "location": {"x": 10.0, "z": -6.0}, "loot_table_id": "loot.freebooter-haul", "reward_item_id": "item.driftwood_bow", "reward_quantity": 1, "standing": {"FREEBOOTERS": 5, "WAYFARERS": 1}},
            "event.wildkin-bloom": {"id": "event.wildkin-bloom", "name": "Wildkin Bloom", "description": "A seed-memory wakes the reeds and draws every curious creature closer.", "faction_id": "WILDKIN", "trigger_after_s": 42.0, "duration_s": 26.0, "location": {"x": -8.0, "z": -7.0}, "loot_table_id": "loot.wildkin-bloom", "reward_item_id": "item.thronglet_seed", "reward_quantity": 2, "standing": {"WILDKIN": 6, "SHOREWARDENS": -1}},
            "event.stormfront": {"id": "event.stormfront", "name": "Stormfront Crossing", "description": "The weather turns the frontier into a shared problem instead of a backdrop.", "faction_id": "WAYFARERS", "trigger_after_s": 66.0, "duration_s": 28.0, "location": {"x": 0.0, "z": 12.0}, "loot_table_id": "loot.tidegate-assault", "reward_item_id": "item.stormheart", "reward_quantity": 1, "standing": {"WAYFARERS": 6, "FREEBOOTERS": 1}},
        },
        "initial_world_items": [
            {"id": "pack-tideglass-lantern", "definition_id": "item.tideglass_lantern", "x": 3.5, "z": 6.0},
            {"id": "pack-shellmail-cache", "definition_id": "item.shellmail_vest", "x": -4.5, "z": 7.0},
            {"id": "pack-coral-fragment", "definition_id": "item.coral_fragment", "x": -6.0, "z": -5.0, "quantity": 2},
            {"id": "pack-stormheart-cache", "definition_id": "item.stormheart", "x": 10.5, "z": 7.0},
        ],
        "asset_bindings": {
            "itemmesh.rusted_hatchet": {"source": "gg-authored-hatchet.gltf", "unit_scale": [1.0, 0.6, 1.0]},
            "itemmesh.driftwood_bow": {"source": "gg-authored-bow.gltf", "unit_scale": [0.8, 0.8, 0.8]},
            "itemmesh.shellmail_vest": {"source": "gg-authored-shellmail.gltf", "unit_scale": [0.8, 0.8, 0.8]},
            "itemmesh.coral_circlet": {"source": "gg-authored-circlet.gltf", "unit_scale": [0.5, 0.5, 0.5]},
            "itemmesh.tidebreaker_axe": {"source": "gg-authored-axe.gltf", "unit_scale": [1.0, 0.8, 1.0]},
        },
        "affixes": {
            "affix.stormtouched": {"id": "affix.stormtouched", "name": "of the Stormtouched", "stat": "lightning_damage", "min": 2, "max": 8},
            "affix.deepfinder": {"id": "affix.deepfinder", "name": "of the Deepfinder", "stat": "loot_find", "min": 2, "max": 7},
            "affix.seedkeeper": {"id": "affix.seedkeeper", "name": "of the Seedkeeper", "stat": "health", "min": 3, "max": 12},
        },
    }


def available_packs() -> dict[str, dict[str, Any]]:
    return {"pack.tidefall-frontier": tidefall_frontier()}


def merge_pack(content: dict[str, Any], pack: dict[str, Any]) -> dict[str, Any]:
    """Merge one page by identity, preserving starter rows and list order."""
    result = copy.deepcopy(content) if isinstance(content, dict) else {}
    mapping_fields = (
        "abilities", "items", "containers", "loot_tables", "recipes", "affixes",
        "enchantments", "races", "specs", "talents", "classes", "npc_individuals",
        "dialogue", "vendors", "quests", "world_events", "asset_bindings",
    )
    for field in mapping_fields:
        rows = pack.get(field) if isinstance(pack, dict) else None
        if not isinstance(rows, dict):
            continue
        target = result.setdefault(field, {})
        if not isinstance(target, dict):
            target = {}
            result[field] = target
        for key, value in list(rows.items())[:MAX_ROWS]:
            if isinstance(value, dict):
                target[str(key)] = copy.deepcopy(value)

    pack_gear = pack.get("gear") if isinstance(pack, dict) else None
    if isinstance(pack_gear, dict):
        target_gear = result.setdefault("gear", {})
        if not isinstance(target_gear, dict):
            target_gear = {}
            result["gear"] = target_gear
        for field, rows in pack_gear.items():
            if not isinstance(rows, dict):
                continue
            target_rows = target_gear.setdefault(field, {})
            if not isinstance(target_rows, dict):
                target_rows = {}
                target_gear[field] = target_rows
            for key, value in list(rows.items())[:MAX_ROWS]:
                if isinstance(value, dict):
                    target_rows[str(key)] = copy.deepcopy(value)

    for field in ("ambient_life", "npc_spawns", "initial_world_items"):
        rows = pack.get(field) if isinstance(pack, dict) else None
        if not isinstance(rows, list):
            continue
        existing = result.setdefault(field, [])
        if not isinstance(existing, list):
            existing = []
            result[field] = existing
        seen = {str(row.get("id")) for row in existing if isinstance(row, dict) and row.get("id")}
        for value in rows[:MAX_ROWS]:
            if not isinstance(value, dict) or not value.get("id"):
                continue
            identity = str(value["id"])
            if identity in seen:
                existing[:] = [row for row in existing if not (isinstance(row, dict) and str(row.get("id")) == identity)]
            existing.append(copy.deepcopy(value))
            seen.add(identity)

    active = result.setdefault("_active_packs", [])
    if not isinstance(active, list):
        active = []
        result["_active_packs"] = active
    pack_id = str(pack.get("id", ""))[:64] if isinstance(pack, dict) else ""
    if pack_id and pack_id not in active:
        active.append(pack_id)
    result["_active_packs"] = list(dict.fromkeys(str(value) for value in active))[:MAX_PACKS]
    return result


def summary(content: dict[str, Any], available: dict[str, Any] | None = None) -> dict[str, Any]:
    active = content.get("_active_packs", []) if isinstance(content, dict) else []
    if not isinstance(active, list):
        active = []
    available_rows = available if isinstance(available, dict) else available_packs()
    return {
        "schema": SCHEMA,
        "available": len(available_rows),
        "active": list(dict.fromkeys(str(value) for value in active))[:MAX_PACKS],
        "active_count": len(active),
        "policy": "BOUNDED_AUTHORED_PAGE_MERGE_PRESERVES_AUTHORITATIVE_STATE",
    }
