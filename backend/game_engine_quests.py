"""Data-driven quest objectives for the authoritative GAME ENGINE state."""

from __future__ import annotations

import copy
import math
from typing import Any
from backend import game_engine_world as world_scale


SCHEMA = "gg.game-engine.quests.v1"
VERSION = 1
MAX_QUESTS = 32
MAX_ACTIVE = 8
MAX_HISTORY = 32


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return number if math.isfinite(number) else default


def _text(value: Any, default: str = "", limit: int = 96) -> str:
    return str(value or default).strip()[:limit]


def catalog() -> dict[str, dict[str, Any]]:
    """Return the first authored quest table as isolated content data."""
    return {
        "quest.shoreline-first": {
            "id": "quest.shoreline-first",
            "name": "The First Ripple",
            "description": "Prove that the shoreline can be defended by stopping a dangerous wildkin.",
            "giver_id": "npc-guardian-01",
            "objective": {
                "kind": "DEFEAT",
                "target_id": "npc-critter-01",
                "required": 1,
                "label": "Defeat Pip Pebbletail",
            },
            "rewards": {
                "xp": 90,
                "gold": 25,
                "items": ["item.moon_shard"],
                "faction": {"SHOREWARDENS": 12},
            },
            "unlocks": ["quest.shoreline-report"],
        },
        "quest.better-kit": {
            "id": "quest.better-kit",
            "name": "A Better Kit",
            "description": "Find or craft a genuinely useful piece of gear and show it can change a life.",
            "giver_id": "npc-wanderer-01",
            "objective": {
                "kind": "ACQUIRE_GEAR",
                "rarity_at_least": "RARE",
                "required": 1,
                "label": "Acquire Rare-or-better gear",
            },
            "rewards": {
                "xp": 125,
                "gold": 40,
                "items": ["item.field_ration"],
                "faction": {"FREEBOOTERS": 10},
            },
        },
        "quest.shoreline-report": {
            "id": "quest.shoreline-report",
            "name": "The Watch Remembers",
            "description": "Return to the tidewatch and make a truthful report after the first shoreline hunt.",
            "giver_id": "npc-guardian-01",
            "prerequisites": ["quest.shoreline-first"],
            "objective": {
                "kind": "TALK",
                "target_id": "npc-guardian-01",
                "choice_id": "shoreline-report",
                "required": 1,
                "label": "Report back to Brann Tidewatch",
            },
            "rewards": {
                "xp": 110,
                "gold": 30,
                "items": ["item.field_ration"],
                "faction": {"SHOREWARDENS": 15, "WAYFARERS": 3},
            },
        },
        "quest.windmill-watch": {
            "id": "quest.windmill-watch",
            "name": "The West Wind",
            "description": "Follow the ridge path to the old windmill and read the coast from above.",
            "giver_id": "npc-guardian-01",
            "objective": {
                "kind": "VISIT",
                "target_id": "landmark.west-windmill",
                "location": {"x": -11.0 * world_scale.ISLAND_LAYOUT_SCALE, "z": -10.0 * world_scale.ISLAND_LAYOUT_SCALE},
                "radius_m": 3.0,
                "required_mode": "GROUND",
                "required": 1,
                "label": "Reach the west windmill overlook",
            },
            "rewards": {
                "xp": 80,
                "gold": 18,
                "items": ["item.field_ration"],
                "faction": {"WAYFARERS": 8},
            },
        },
        "quest.waterwheel-current": {
            "id": "quest.waterwheel-current",
            "name": "Where the Current Turns",
            "description": "Trace the south trail to the cove waterwheel and see where fresh water reaches the sea.",
            "giver_id": "npc-wanderer-01",
            "objective": {
                "kind": "VISIT",
                "target_id": "landmark.cove-waterwheel",
                "location": {"x": 9.0 * world_scale.ISLAND_LAYOUT_SCALE, "z": -13.0 * world_scale.ISLAND_LAYOUT_SCALE},
                "radius_m": 3.0,
                "required_mode": "GROUND",
                "required": 1,
                "label": "Reach the cove waterwheel",
            },
            "rewards": {
                "xp": 95,
                "gold": 22,
                "items": ["item.moon_shard"],
                "faction": {"WAYFARERS": 10, "SHOREWARDENS": 4},
            },
            "unlocks": ["quest.tide-beacon"],
        },
        "quest.tide-beacon": {
            "id": "quest.tide-beacon",
            "name": "The Tide Beacon",
            "description": "Continue along the south coast to the beacon above the tide pools.",
            "giver_id": "npc-wanderer-01",
            "prerequisites": ["quest.waterwheel-current"],
            "objective": {
                "kind": "VISIT",
                "target_id": "landmark.south-tide-beacon",
                "location": {"x": 4.0 * world_scale.ISLAND_LAYOUT_SCALE, "z": -22.0 * world_scale.ISLAND_LAYOUT_SCALE},
                "radius_m": 3.0,
                "required_mode": "GROUND",
                "required": 1,
                "label": "Reach the tide beacon on the south point",
            },
            "rewards": {
                "xp": 140,
                "gold": 35,
                "items": ["item.field_ration", "item.moon_shard"],
                "faction": {"WAYFARERS": 12, "FREEBOOTERS": 5},
            },
        },
    }


def _quest_definition(raw: Any, quest_id: str) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    objective = raw.get("objective", {}) if isinstance(raw.get("objective"), dict) else {}
    location = objective.get("location", {}) if isinstance(objective.get("location"), dict) else {}
    has_location = "x" in location and "z" in location
    required_mode = _text(objective.get("required_mode"), limit=16).upper()
    if required_mode not in {"GROUND", "SWIM", "FLY"}:
        required_mode = ""
    rewards = raw.get("rewards", {}) if isinstance(raw.get("rewards"), dict) else {}
    return {
        "id": _text(raw.get("id"), quest_id, 64),
        "name": _text(raw.get("name"), quest_id, 96),
        "description": _text(raw.get("description"), limit=160),
        "giver_id": _text(raw.get("giver_id"), limit=64),
        "shareable": raw.get("shareable", True) is True,
        "objective": {
            "kind": _text(objective.get("kind"), "DEFEAT", 32).upper(),
            "target_id": _text(objective.get("target_id"), limit=96),
            "definition_id": _text(objective.get("definition_id"), limit=96),
            "choice_id": _text(objective.get("choice_id"), limit=48),
            "rarity_at_least": _text(objective.get("rarity_at_least"), "COMMON", 16).upper(),
            "location": {
                "x": max(-100000.0, min(100000.0, _safe_float(location.get("x")))),
                "z": max(-100000.0, min(100000.0, _safe_float(location.get("z")))),
            } if has_location else {},
            "radius_m": max(1.0, min(64.0, _safe_float(objective.get("radius_m"), 3.0))),
            "required_mode": required_mode,
            "required": max(1, min(1_000_000, _safe_int(objective.get("required"), 1))),
            "label": _text(objective.get("label"), "Complete objective", 128),
        },
        "rewards": {
            "xp": max(0, min(1_000_000, _safe_int(rewards.get("xp")))),
            "gold": max(0, min(2_000_000_000, _safe_int(rewards.get("gold")))),
            "items": [
                _text(value, limit=96)
                for value in rewards.get("items", [])[:8]
                if _text(value)
            ] if isinstance(rewards.get("items"), list) else [],
            "faction": {
                _text(key, limit=32).upper(): max(-100000, min(100000, _safe_int(value)))
                for key, value in list(rewards.get("faction", {}).items())[:8]
                if _text(key)
            } if isinstance(rewards.get("faction"), dict) else {},
        },
        "prerequisites": [
            _text(value, limit=64)
            for value in raw.get("prerequisites", [])[:8]
            if _text(value)
        ] if isinstance(raw.get("prerequisites"), list) else [],
        "unlocks": [
            _text(value, limit=64)
            for value in raw.get("unlocks", [])[:8]
            if _text(value)
        ] if isinstance(raw.get("unlocks"), list) else [],
    }


def normalized_catalog(raw: Any = None) -> dict[str, dict[str, Any]]:
    source = raw if isinstance(raw, dict) else catalog()
    result: dict[str, dict[str, Any]] = {}
    for quest_id, value in list(source.items())[:MAX_QUESTS]:
        wanted = _text(quest_id, limit=64)
        if not wanted:
            continue
        definition = _quest_definition(value, wanted)
        if definition is not None:
            result[definition["id"]] = definition
    return result


def new_state() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "active": {},
        "completed": [],
        "history": [],
        "last_event": {},
        "revision": 0,
    }


def _progress_row(raw: Any, definition: dict[str, Any]) -> dict[str, Any]:
    row = raw if isinstance(raw, dict) else {}
    objective = definition.get("objective", {})
    required = max(1, _safe_int(objective.get("required"), 1))
    current = max(0, min(required, _safe_int(row.get("current"), 0)))
    status = _text(row.get("status"), "ACTIVE", 16).upper()
    if status not in {"ACTIVE", "READY"}:
        status = "ACTIVE"
    if current >= required:
        status = "READY"
    return {
        "quest_id": definition["id"],
        "status": status,
        "current": current,
        "required": required,
        "accepted_at": round(max(0.0, _safe_float(row.get("accepted_at"))), 3),
        "ready_at": round(max(0.0, _safe_float(row.get("ready_at"))), 3),
        "last_event": copy.deepcopy(row.get("last_event", {}))
        if isinstance(row.get("last_event"), dict)
        else {},
    }


def normalize_state(raw: Any, quest_catalog: Any = None) -> dict[str, Any]:
    definitions = normalized_catalog(quest_catalog)
    base = new_state()
    source = raw if isinstance(raw, dict) else {}
    active = source.get("active", {})
    if isinstance(active, dict):
        for quest_id, value in list(active.items())[:MAX_ACTIVE]:
            definition = definitions.get(str(quest_id))
            if definition is not None:
                base["active"][definition["id"]] = _progress_row(value, definition)
    completed = source.get("completed", [])
    if isinstance(completed, list):
        base["completed"] = list(dict.fromkeys(
            _text(value, limit=64) for value in completed[:MAX_HISTORY] if _text(value)
        ))[:MAX_HISTORY]
    history = source.get("history", [])
    if isinstance(history, list):
        base["history"] = [copy.deepcopy(row) for row in history[-MAX_HISTORY:] if isinstance(row, dict)]
    if isinstance(source.get("last_event"), dict):
        base["last_event"] = copy.deepcopy(source["last_event"])
    base["revision"] = max(0, _safe_int(source.get("revision")))
    return base


def accept(state: dict[str, Any], quest_catalog: Any, quest_id: Any, sim_time: Any) -> tuple[bool, dict[str, Any]]:
    definitions = normalized_catalog(quest_catalog)
    wanted = _text(quest_id, limit=64)
    definition = definitions.get(wanted)
    if definition is None:
        return False, {"error": "QUEST_UNKNOWN", "quest_id": wanted}
    active = state.setdefault("active", {})
    completed = state.setdefault("completed", [])
    if wanted in active:
        return False, {"error": "QUEST_ALREADY_ACTIVE", "quest_id": wanted}
    if wanted in completed:
        return False, {"error": "QUEST_ALREADY_COMPLETED", "quest_id": wanted}
    completed_ids = {str(value) for value in completed}
    missing = [
        str(prerequisite)
        for prerequisite in definition.get("prerequisites", [])[:8]
        if str(prerequisite) not in completed_ids
    ]
    if missing:
        return False, {
            "error": "QUEST_PREREQUISITES_MISSING",
            "quest_id": wanted,
            "missing": missing,
        }
    if len(active) >= MAX_ACTIVE:
        return False, {"error": "QUEST_ACTIVE_LIMIT", "limit": MAX_ACTIVE}
    row = _progress_row({"accepted_at": max(0.0, _safe_float(sim_time))}, definition)
    active[wanted] = row
    state["revision"] = max(0, _safe_int(state.get("revision"))) + 1
    return True, {"quest": copy.deepcopy(definition), "progress": copy.deepcopy(row)}


def _event_matches(objective: dict[str, Any], event: dict[str, Any]) -> bool:
    kind = _text(objective.get("kind"), limit=32).upper()
    event_kind = _text(event.get("kind"), limit=32).upper()
    if kind == "DEFEAT":
        return event_kind == "DEFEAT" and (
            not objective.get("target_id")
            or str(objective.get("target_id")) == str(event.get("target_id"))
        )
    if kind == "ACQUIRE_GEAR":
        if event_kind not in {"PICKUP", "EQUIP", "CRAFT", "DEFEAT"}:
            return False
        if objective.get("definition_id") and str(objective.get("definition_id")) != str(event.get("definition_id")):
            return False
        rarity_order = {"TRASH": 0, "COMMON": 1, "UNCOMMON": 2, "RARE": 3, "EPIC": 4, "LEGENDARY": 5, "ARTIFACT": 6}
        return rarity_order.get(str(event.get("rarity", "COMMON")).upper(), 1) >= rarity_order.get(
            str(objective.get("rarity_at_least", "COMMON")).upper(), 1
        )
    if kind == "TALK":
        return event_kind == "TALK" and (
            not objective.get("target_id")
            or str(objective.get("target_id")) == str(event.get("target_id"))
        ) and (
            not objective.get("choice_id")
            or str(objective.get("choice_id")) == str(event.get("choice_id"))
        )
    if kind == "CRAFT":
        return event_kind == "CRAFT" and (
            not objective.get("definition_id")
            or str(objective.get("definition_id")) == str(event.get("definition_id"))
        )
    if kind == "VISIT":
        if event_kind != "VISIT" or (
            objective.get("target_id")
            and str(objective.get("target_id")) != str(event.get("target_id"))
        ):
            return False
        required_mode = str(objective.get("required_mode") or "").upper()
        return not required_mode or required_mode == str(event.get("movement_mode") or "").upper()
    return False


def record_event(
    state: dict[str, Any],
    quest_catalog: Any,
    event: Any,
    sim_time: Any,
) -> dict[str, Any]:
    definitions = normalized_catalog(quest_catalog)
    event_row = event if isinstance(event, dict) else {}
    changed: list[dict[str, Any]] = []
    active = state.setdefault("active", {})
    for quest_id in list(active)[:MAX_ACTIVE]:
        progress = active.get(quest_id)
        definition = definitions.get(str(quest_id))
        if not isinstance(progress, dict) or definition is None or progress.get("status") == "READY":
            continue
        if not _event_matches(definition.get("objective", {}), event_row):
            continue
        progress["current"] = min(
            max(1, _safe_int(progress.get("required"), 1)),
            max(0, _safe_int(progress.get("current"))) + max(1, _safe_int(event_row.get("amount"), 1)),
        )
        progress["last_event"] = {
            "kind": _text(event_row.get("kind"), limit=32).upper(),
            "target_id": _text(event_row.get("target_id"), limit=96),
            "definition_id": _text(event_row.get("definition_id"), limit=96),
            "time_s": round(max(0.0, _safe_float(sim_time)), 3),
        }
        if progress["current"] >= progress["required"]:
            progress["status"] = "READY"
            progress["ready_at"] = round(max(0.0, _safe_float(sim_time)), 3)
        changed.append(copy.deepcopy(progress))
    if changed:
        state["last_event"] = copy.deepcopy(changed[-1])
        state["revision"] = max(0, _safe_int(state.get("revision"))) + 1
    return {"changed": bool(changed), "quests": changed}


def claim(state: dict[str, Any], quest_catalog: Any, quest_id: Any, sim_time: Any) -> tuple[bool, dict[str, Any]]:
    definitions = normalized_catalog(quest_catalog)
    wanted = _text(quest_id, limit=64)
    definition = definitions.get(wanted)
    progress = state.get("active", {}).get(wanted) if isinstance(state.get("active"), dict) else None
    if definition is None:
        return False, {"error": "QUEST_UNKNOWN", "quest_id": wanted}
    if not isinstance(progress, dict) or progress.get("status") != "READY":
        return False, {"error": "QUEST_NOT_READY", "quest_id": wanted}
    state.setdefault("active", {}).pop(wanted, None)
    completed = state.setdefault("completed", [])
    if wanted not in completed:
        completed.append(wanted)
    reward = copy.deepcopy(definition.get("rewards", {}))
    history_row = {
        "quest_id": wanted,
        "completed_at": round(max(0.0, _safe_float(sim_time)), 3),
        "reward": copy.deepcopy(reward),
    }
    state.setdefault("history", []).append(history_row)
    state["history"] = state["history"][-MAX_HISTORY:]
    state["last_event"] = copy.deepcopy(history_row)
    state["revision"] = max(0, _safe_int(state.get("revision"))) + 1
    return True, {
        "quest": copy.deepcopy(definition),
        "progress": copy.deepcopy(progress),
        "rewards": reward,
        "unlocks": copy.deepcopy(definition.get("unlocks", [])),
    }


def view(state: Any, quest_catalog: Any = None) -> dict[str, Any]:
    definitions = normalized_catalog(quest_catalog)
    source = normalize_state(state, definitions)
    active_rows = []
    for quest_id in sorted(source.get("active", {}))[:MAX_ACTIVE]:
        progress = source["active"].get(quest_id)
        definition = definitions.get(quest_id)
        if isinstance(progress, dict) and definition is not None:
            active_rows.append({**copy.deepcopy(definition), "progress": copy.deepcopy(progress)})
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "catalog": [copy.deepcopy(definitions[key]) for key in sorted(definitions)[:MAX_QUESTS]],
        "available": [
            key
            for key in sorted(definitions)[:MAX_QUESTS]
            if key not in source.get("completed", [])
            and all(
                prerequisite in source.get("completed", [])
                for prerequisite in definitions[key].get("prerequisites", [])
            )
        ],
        "active": active_rows,
        "active_count": len(active_rows),
        "ready": sum(
            1
            for row in active_rows
            if isinstance(row.get("progress"), dict)
            and row["progress"].get("status") == "READY"
        ),
        "completed": list(source.get("completed", [])[:MAX_HISTORY]),
        "history": copy.deepcopy(source.get("history", [])[-MAX_HISTORY:]),
        "last_event": copy.deepcopy(source.get("last_event", {})),
        "revision": max(0, _safe_int(source.get("revision"))),
        "policy": "DATA_DRIVEN_OBJECTIVES_WITH_EXPLICIT_REWARD_CLAIM",
    }
