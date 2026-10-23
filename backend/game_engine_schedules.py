"""Deterministic daily schedules for individual NPC world use."""

from __future__ import annotations

import copy
import math
from typing import Any


SCHEMA = "gg.game-engine.schedules.v1"
VERSION = 1
DAY_LENGTH_S = 60.0
MAX_SLOTS = 8
ACTIVITIES = frozenset(
    {
        "WANDER",
        "INSPECT_LOOT",
        "GATHER",
        "CRAFT",
        "HAUL",
        "EXPLORE",
        "REST",
        "OBSERVE_PLAYER",
    }
)

DEFAULT_BY_OCCUPATION: dict[str, tuple[dict[str, Any], ...]] = {
    "SCAVENGER": (
        {"id": "NIGHT_REST", "start_s": 0.0, "end_s": 12.0, "activity": "REST", "target_kind": "HOME"},
        {"id": "SHORE_SCAVENGE", "start_s": 12.0, "end_s": 42.0, "activity": "INSPECT_LOOT", "target_kind": "GEAR"},
        {"id": "CAMP_RETURN", "start_s": 42.0, "end_s": 60.0, "activity": "EXPLORE", "target_kind": "STATION"},
    ),
    "WARDEN": (
        {"id": "WATCH_REST", "start_s": 0.0, "end_s": 9.0, "activity": "REST", "target_kind": "HOME"},
        {"id": "GATE_WATCH", "start_s": 9.0, "end_s": 39.0, "activity": "GATHER", "target_kind": "STATION"},
        {"id": "CACHE_ROUND", "start_s": 39.0, "end_s": 60.0, "activity": "HAUL", "target_kind": "CONTAINER"},
    ),
    "FORAGER": (
        {"id": "BURROW_REST", "start_s": 0.0, "end_s": 10.0, "activity": "REST", "target_kind": "HOME"},
        {"id": "HERB_RUN", "start_s": 10.0, "end_s": 46.0, "activity": "GATHER", "target_kind": "NATURE"},
        {"id": "PLAY_EXPLORE", "start_s": 46.0, "end_s": 60.0, "activity": "EXPLORE", "target_kind": "STATION"},
    ),
}
DEFAULT_GENERIC: tuple[dict[str, Any], ...] = (
    {"id": "REST", "start_s": 0.0, "end_s": 10.0, "activity": "REST", "target_kind": "HOME"},
    {"id": "WORK", "start_s": 10.0, "end_s": 45.0, "activity": "EXPLORE", "target_kind": "STATION"},
    {"id": "ROAM", "start_s": 45.0, "end_s": 60.0, "activity": "WANDER", "target_kind": "NONE"},
)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return number if math.isfinite(number) else default


def _text(value: Any, default: str = "", limit: int = 32) -> str:
    return str(value or default).strip()[:limit]


def _activity(value: Any, default: str = "WANDER") -> str:
    wanted = _text(value, default, 32).upper()
    return wanted if wanted in ACTIVITIES else default


def schedule_for(occupation: Any, raw: Any = None) -> list[dict[str, Any]]:
    """Normalize authored slots, or choose a bounded occupation default."""
    source = raw if isinstance(raw, (list, tuple)) else None
    if source is None:
        source = DEFAULT_BY_OCCUPATION.get(
            _text(occupation, "TRAVELER", 32).upper(),
            DEFAULT_GENERIC,
        )
    result: list[dict[str, Any]] = []
    for ordinal, value in enumerate(list(source)[:MAX_SLOTS]):
        if not isinstance(value, dict):
            continue
        start = max(0.0, min(DAY_LENGTH_S, _safe_float(value.get("start_s"))))
        end = max(0.0, min(DAY_LENGTH_S, _safe_float(value.get("end_s"), DAY_LENGTH_S)))
        if end <= start:
            continue
        result.append(
            {
                "id": _text(value.get("id"), f"SLOT_{ordinal:02d}", 48).upper(),
                "start_s": round(start, 3),
                "end_s": round(end, 3),
                "activity": _activity(value.get("activity")),
                "target_kind": _text(value.get("target_kind"), "NONE", 24).upper(),
            }
        )
    result.sort(key=lambda row: (row["start_s"], row["end_s"], row["id"]))
    return result[:MAX_SLOTS]


def active_slot(schedule: Any, sim_time: Any) -> dict[str, Any] | None:
    rows = schedule_for("TRAVELER", schedule)
    phase = max(0.0, _safe_float(sim_time)) % DAY_LENGTH_S
    for row in rows:
        if row["start_s"] <= phase < row["end_s"]:
            result = copy.deepcopy(row)
            result["phase_s"] = round(phase, 3)
            result["remaining_s"] = round(max(0.0, row["end_s"] - phase), 3)
            return result
    return None


def view(schedule: Any, sim_time: Any = 0.0) -> dict[str, Any]:
    rows = schedule_for("TRAVELER", schedule)
    current = active_slot(rows, sim_time)
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "day_length_s": DAY_LENGTH_S,
        "phase_s": round(max(0.0, _safe_float(sim_time)) % DAY_LENGTH_S, 3),
        "slots": rows,
        "active_slot": current or {},
        "policy": "DETERMINISTIC_OCCUPATION_SCHEDULE_WITH_NEED_OVERRIDE",
    }
