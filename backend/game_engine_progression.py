"""Deterministic RPG progression primitives for the GAME ENGINE preview."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


SCHEMA = "gg.game-engine.progression.v1"
VERSION = 1
MAX_LEVEL = 60
RACES = ("ISLANDER", "TIDEBORN", "SKYKIN")
SPECS = ("EXPLORER", "WARDEN", "DUELIST")


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def xp_for_next(level: int) -> int:
    safe_level = max(1, min(MAX_LEVEL, _safe_int(level, 1)))
    return 100 + (safe_level - 1) * 35


def select_race(state: dict[str, Any], race: str) -> tuple[bool, dict[str, Any]]:
    value = str(race or "").upper()
    if value not in RACES:
        return False, {"error": "PROGRESSION_RACE_UNKNOWN", "allowed": list(RACES)}
    state["race"] = value
    return True, {"race": value}


def select_spec(state: dict[str, Any], spec: str) -> tuple[bool, dict[str, Any]]:
    value = str(spec or "").upper()
    if value not in SPECS:
        return False, {"error": "PROGRESSION_SPEC_UNKNOWN", "allowed": list(SPECS)}
    state["spec"] = value
    return True, {"spec": value}


def starter_state() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "race": "ISLANDER",
        "class_id": "class.pathfinder",
        "spec": "EXPLORER",
        "level": 1,
        "xp": 0,
        "xp_to_next": xp_for_next(1),
        "ascension": 0,
        "paragon": 0,
        "talent_points": 2,
        "talents": {"trailblazer": 1, "tidewalker": 0, "skybound": 0},
        "base_stats": {"might": 5, "finesse": 5, "spirit": 5, "grit": 5},
        "additive_stats": {
            "move_speed": 0.0,
            "swim_speed": 0.0,
            "air_control": 0.0,
            "loot_find": 0.0,
        },
    }


def grant_xp(state: dict[str, Any], amount: Any) -> dict[str, Any]:
    """Apply XP with deterministic level-ups and an explicit level cap."""
    gained = max(0, min(1_000_000, _safe_int(amount)))
    state["xp"] = max(0, _safe_int(state.get("xp"))) + gained
    level = max(1, min(MAX_LEVEL, _safe_int(state.get("level"), 1)))
    level_ups = 0
    while level < MAX_LEVEL and state["xp"] >= xp_for_next(level):
        state["xp"] -= xp_for_next(level)
        level += 1
        level_ups += 1
        state["talent_points"] = _safe_int(state.get("talent_points")) + 1
    state["level"] = level
    state["xp_to_next"] = xp_for_next(level)
    if level == MAX_LEVEL:
        state["paragon"] = max(0, _safe_int(state.get("paragon"))) + state["xp"] // 250
        state["xp"] %= 250
    return {"xp_gained": gained, "level_ups": level_ups, "level": level}


def add_talent(state: dict[str, Any], talent_id: str) -> tuple[bool, dict[str, Any]]:
    points = _safe_int(state.get("talent_points"))
    talent_key = str(talent_id or "").strip().lower()
    talents = state.setdefault("talents", {})
    if points <= 0:
        return False, {"error": "PROGRESSION_TALENT_POINTS_MISSING"}
    if talent_key not in talents:
        return False, {"error": "PROGRESSION_TALENT_UNKNOWN", "talent_id": talent_key}
    talents[talent_key] = _safe_int(talents.get(talent_key)) + 1
    state["talent_points"] = points - 1
    return True, {"talent_id": talent_key, "rank": talents[talent_key]}


def add_stat(state: dict[str, Any], stat: str, amount: Any) -> tuple[bool, dict[str, Any]]:
    key = str(stat or "").strip().lower()
    additive = state.setdefault("additive_stats", {})
    if key not in additive:
        return False, {"error": "PROGRESSION_STAT_UNKNOWN", "stat": key}
    value = float(amount) if isinstance(amount, (int, float)) else 0.0
    if value != value or abs(value) == float("inf"):
        value = 0.0
    additive[key] = round(float(additive.get(key, 0.0)) + value, 4)
    return True, {"stat": key, "value": additive[key]}


def ascend(state: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    """Allow a deliberately explicit ascension gate for future endgame rules."""
    level = _safe_int(state.get("level"), 1)
    if level < MAX_LEVEL:
        return False, {"error": "PROGRESSION_ASCENSION_LEVEL_REQUIRED", "required_level": MAX_LEVEL}
    state["ascension"] = _safe_int(state.get("ascension")) + 1
    state["level"] = 1
    state["xp"] = 0
    state["xp_to_next"] = xp_for_next(1)
    return True, {"ascension": state["ascension"]}


def summary(state: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(state)
