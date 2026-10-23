"""Bounded recurring world events for the authoritative GAME ENGINE.

An event is a real simulation transition: it starts at a deterministic world
time, exposes an authored location and loot table, changes faction pressure,
and later completes into durable history.  The renderer only displays the
state returned here; it never manufactures an event banner on its own.
"""

from __future__ import annotations

import copy
import math
from typing import Any


SCHEMA = "gg.game-engine.world-events.v1"
VERSION = 1
MAX_EVENTS = 32
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
    """The base island has no scheduled crisis; packs add authored events."""
    return {}


def _definition(raw: Any, event_id: str) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    location = raw.get("location", {}) if isinstance(raw.get("location"), dict) else {}
    standing = raw.get("standing", {}) if isinstance(raw.get("standing"), dict) else {}
    return {
        "id": _text(raw.get("id"), event_id, 64),
        "name": _text(raw.get("name"), event_id, 96),
        "description": _text(raw.get("description"), "A world event is underway.", 180),
        "faction_id": _text(raw.get("faction_id"), "WAYFARERS", 32).upper(),
        "trigger_after_s": round(max(0.0, min(1_000_000.0, _safe_float(raw.get("trigger_after_s")))), 3),
        "duration_s": round(max(1.0, min(86_400.0, _safe_float(raw.get("duration_s"), 20.0))), 3),
        "location": {
            "x": max(-1_000_000.0, min(1_000_000.0, _safe_float(location.get("x")))),
            "z": max(-1_000_000.0, min(1_000_000.0, _safe_float(location.get("z")))),
        },
        "loot_table_id": _text(raw.get("loot_table_id"), limit=96),
        "reward_item_id": _text(raw.get("reward_item_id"), limit=96),
        "reward_quantity": max(1, min(16, _safe_int(raw.get("reward_quantity"), 1))),
        "standing": {
            _text(key, limit=32).upper(): max(-1000, min(1000, _safe_int(value)))
            for key, value in list(standing.items())[:8]
            if _text(key)
        },
    }


def normalized_catalog(raw: Any = None) -> dict[str, dict[str, Any]]:
    source = raw if isinstance(raw, dict) else catalog()
    result: dict[str, dict[str, Any]] = {}
    for event_id, value in list(source.items())[:MAX_EVENTS]:
        wanted = _text(event_id, limit=64)
        if not wanted:
            continue
        row = _definition(value, wanted)
        if row is not None:
            result[row["id"]] = row
    return result


def new_state() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "active": [],
        "history": [],
        "last_event": {},
        "revision": 0,
    }


def normalize_state(raw: Any, event_catalog: Any = None) -> dict[str, Any]:
    definitions = normalized_catalog(event_catalog)
    base = new_state()
    source = raw if isinstance(raw, dict) else {}
    active = source.get("active", [])
    if isinstance(active, list):
        for value in active[:MAX_ACTIVE]:
            if not isinstance(value, dict):
                continue
            event_id = _text(value.get("event_id"), limit=64)
            if event_id not in definitions:
                continue
            started = max(0.0, _safe_float(value.get("started_at")))
            expires = max(started, _safe_float(value.get("expires_at")))
            base["active"].append({
                "event_id": event_id,
                "started_at": round(started, 3),
                "expires_at": round(expires, 3),
                "progress": round(max(0.0, min(1.0, _safe_float(value.get("progress")))), 4),
            })
    history = source.get("history", [])
    if isinstance(history, list):
        base["history"] = [
            {
                "event_id": _text(value.get("event_id"), limit=64),
                "phase": _text(value.get("phase"), "COMPLETE", 16).upper(),
                "time_s": round(max(0.0, _safe_float(value.get("time_s"))), 3),
            }
            for value in history[-MAX_HISTORY:]
            if isinstance(value, dict) and _text(value.get("event_id"), limit=64)
        ]
    if isinstance(source.get("last_event"), dict):
        base["last_event"] = copy.deepcopy(source["last_event"])
    base["revision"] = max(0, _safe_int(source.get("revision")))
    return base


def tick(
    state: dict[str, Any],
    event_catalog: Any,
    sim_time: Any,
) -> dict[str, Any]:
    """Advance event phases and return only newly started/completed facts."""
    definitions = normalized_catalog(event_catalog)
    safe_time = max(0.0, _safe_float(sim_time))
    active = state.setdefault("active", [])
    history = state.setdefault("history", [])
    if not isinstance(active, list):
        active = []
        state["active"] = active
    if not isinstance(history, list):
        history = []
        state["history"] = history
    changes: list[dict[str, Any]] = []
    active_ids = {str(row.get("event_id")) for row in active if isinstance(row, dict)}
    history_ids = {
        str(row.get("event_id"))
        for row in history
        if isinstance(row, dict) and str(row.get("phase", "COMPLETE")) == "COMPLETE"
    }

    for event_id in sorted(definitions):
        definition = definitions[event_id]
        if event_id in active_ids or event_id in history_ids:
            continue
        if safe_time < _safe_float(definition.get("trigger_after_s")):
            continue
        if len(active) >= MAX_ACTIVE:
            break
        started = _safe_float(definition.get("trigger_after_s"))
        duration = max(1.0, _safe_float(definition.get("duration_s"), 20.0))
        row = {
            "event_id": event_id,
            "started_at": round(started, 3),
            "expires_at": round(started + duration, 3),
            "progress": round(max(0.0, min(1.0, (safe_time - started) / duration)), 4),
        }
        active.append(row)
        active_ids.add(event_id)
        changes.append({"phase": "START", "event": copy.deepcopy(definition), "state": copy.deepcopy(row)})

    remaining: list[dict[str, Any]] = []
    for row in active[:MAX_ACTIVE]:
        if not isinstance(row, dict):
            continue
        event_id = str(row.get("event_id", ""))
        definition = definitions.get(event_id)
        if definition is None:
            continue
        started = _safe_float(row.get("started_at"))
        expires = max(started, _safe_float(row.get("expires_at")))
        if safe_time >= expires:
            completed = {
                "event_id": event_id,
                "phase": "COMPLETE",
                "time_s": round(safe_time, 3),
            }
            history.append(completed)
            changes.append({"phase": "COMPLETE", "event": copy.deepcopy(definition), "state": copy.deepcopy(completed)})
            continue
        row["progress"] = round(max(0.0, min(1.0, (safe_time - started) / max(1.0, expires - started))), 4)
        remaining.append(row)
    state["active"] = remaining[:MAX_ACTIVE]
    state["history"] = history[-MAX_HISTORY:]
    if changes:
        state["last_event"] = copy.deepcopy(changes[-1])
        state["revision"] = max(0, _safe_int(state.get("revision"))) + len(changes)
    return {"changed": bool(changes), "changes": changes}


def view(state: Any, event_catalog: Any = None) -> dict[str, Any]:
    definitions = normalized_catalog(event_catalog)
    source = normalize_state(state, definitions)
    active_rows = []
    for raw in source.get("active", [])[:MAX_ACTIVE]:
        if not isinstance(raw, dict):
            continue
        definition = definitions.get(str(raw.get("event_id")))
        if definition is not None:
            active_rows.append({**copy.deepcopy(definition), "state": copy.deepcopy(raw)})
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "catalog": [copy.deepcopy(definitions[key]) for key in sorted(definitions)[:MAX_EVENTS]],
        "active": active_rows,
        "active_count": len(active_rows),
        "history": copy.deepcopy(source.get("history", [])[-MAX_HISTORY:]),
        "last_event": copy.deepcopy(source.get("last_event", {})),
        "revision": max(0, _safe_int(source.get("revision"))),
        "policy": "DETERMINISTIC_SCHEDULED_EVENTS_WITH_DURABLE_HISTORY",
    }
