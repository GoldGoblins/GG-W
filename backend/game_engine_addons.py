"""Small native addon registry for the GAME ENGINE UI.

The registry borrows the useful part of WoW/PitBull/oUF: common state
producers publish stable elements and layouts decide how to display them.
This first seam is intentionally data-only and budgeted.  It does not claim
to execute third-party Lua or Python inside the simulation; a sandboxed
extension ABI can be added later without coupling the renderer to it.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


SCHEMA = "gg.game-engine.addons.v1"
VERSION = 1
EXECUTION_MODEL = "NATIVE_DATA_ONLY_EVENT_DRIVEN"


ADDON_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "id": "UNIT_FRAMES",
        "name": "PitBull-style Unit Frames",
        "category": "UI",
        "version": 1,
        "default_enabled": True,
        "memory_budget_kb": 8,
        "elements": ["player", "target", "resource", "state"],
        "events": ["SNAPSHOT", "TARGET_CHANGED", "COMBAT_STATE"],
    },
    {
        "id": "ACTION_BAR",
        "name": "Action Bar & Cooldowns",
        "category": "UI",
        "version": 1,
        "default_enabled": True,
        "memory_budget_kb": 6,
        "elements": ["abilities", "cooldowns", "resource"],
        "events": ["SNAPSHOT", "ABILITY", "RESOURCE_CHANGED"],
    },
    {
        "id": "NPC_TRACKER",
        "name": "NPC / AI Tracker",
        "category": "WORLD",
        "version": 1,
        "default_enabled": True,
        "memory_budget_kb": 10,
        "elements": ["agents", "perception", "path", "interaction"],
        "events": ["SNAPSHOT", "NPC_STATE", "TARGET_CHANGED"],
    },
    {
        "id": "LOOT_LEDGER",
        "name": "Loot / Craft Ledger",
        "category": "GAMEPLAY",
        "version": 1,
        "default_enabled": True,
        "memory_budget_kb": 5,
        "elements": ["inventory", "affixes", "recipes", "enchantments"],
        "events": ["SNAPSHOT", "LOOT", "CRAFT", "ENCHANT"],
    },
    {
        "id": "WORLD_NAV",
        "name": "World / Cell Navigator",
        "category": "WORLD",
        "version": 1,
        "default_enabled": True,
        "memory_budget_kb": 7,
        "elements": ["cell", "streaming", "navmesh", "medium"],
        "events": ["SNAPSHOT", "CELL_CHANGED", "STREAMING"],
    },
    {
        "id": "TERRAIN_AUTHORING",
        "name": "In-game Terrain Authoring",
        "category": "EDITOR",
        "version": 1,
        "default_enabled": True,
        "memory_budget_kb": 9,
        "elements": ["target", "brush", "undo", "heightfield"],
        "events": ["SNAPSHOT", "TERRAIN_EDIT", "UNDO"],
    },
)

ADDON_IDS = tuple(row["id"] for row in ADDON_DEFINITIONS)


def new_state() -> dict[str, Any]:
    """Return the default built-in addon state."""
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "execution": EXECUTION_MODEL,
        "policy": "BOUNDED_MEMORY_EXPLICIT_EVENTS_NO_ARBITRARY_CODE",
        "addons": [
            {
                **deepcopy(row),
                "enabled": bool(row["default_enabled"]),
                "status": "ACTIVE" if row["default_enabled"] else "DISABLED",
            }
            for row in ADDON_DEFINITIONS
        ],
        "third_party": {
            "status": "NOT_ENABLED",
            "next_seam": "SANDBOXED_NATIVE_OR_WASM_ABI",
        },
    }


def _definition(addon_id: Any) -> dict[str, Any] | None:
    wanted = str(addon_id or "").strip().upper()
    for row in ADDON_DEFINITIONS:
        if row["id"] == wanted:
            return row
    return None


def _normalized_state(state: Any) -> dict[str, Any]:
    normalized = new_state()
    if not isinstance(state, dict):
        return normalized
    raw_addons = state.get("addons")
    if not isinstance(raw_addons, list):
        return normalized
    enabled_by_id = {
        str(row.get("id", "")).upper(): bool(row.get("enabled"))
        for row in raw_addons
        if isinstance(row, dict)
    }
    for row in normalized["addons"]:
        row["enabled"] = enabled_by_id.get(row["id"], row["enabled"])
        row["status"] = "ACTIVE" if row["enabled"] else "DISABLED"
    return normalized


def set_enabled(
    state: Any,
    addon_id: Any,
    enabled: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Enable or disable one known addon and return a small result record."""
    normalized = _normalized_state(state)
    definition = _definition(addon_id)
    if definition is None:
        return normalized, {
            "ok": False,
            "error": "GAME_ENGINE_ADDON_INVALID",
            "addon_id": str(addon_id or ""),
        }
    wanted = definition["id"]
    value = bool(enabled)
    for row in normalized["addons"]:
        if row["id"] == wanted:
            row["enabled"] = value
            row["status"] = "ACTIVE" if value else "DISABLED"
            break
    return normalized, {
        "ok": True,
        "addon_id": wanted,
        "enabled": value,
    }


def normalize_state(state: Any) -> dict[str, Any]:
    """Return a valid public state for persistence and external tooling."""
    return _normalized_state(state)


def enabled(state: Any, addon_id: Any) -> bool:
    wanted = str(addon_id or "").strip().upper()
    normalized = _normalized_state(state)
    return any(
        row["id"] == wanted and bool(row["enabled"])
        for row in normalized["addons"]
    )


def summary(state: Any) -> dict[str, Any]:
    """Return addon definitions plus aggregate budget for the inspector."""
    normalized = _normalized_state(state)
    result = deepcopy(normalized)
    active = [row for row in result["addons"] if row["enabled"]]
    result["active_count"] = len(active)
    result["count"] = len(result["addons"])
    result["active_memory_budget_kb"] = sum(
        int(row.get("memory_budget_kb", 0)) for row in active
    )
    result["memory_budget_policy"] = "EXPLICIT_PER_ADDON_KB"
    return result
