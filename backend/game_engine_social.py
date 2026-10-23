"""Bounded social encounters and NPC-to-NPC relationship state.

The social layer samples the same physical/ambient positions that movement and
world-use already expose.  It only selects a small number of nearby pairs; the
host then commits memories, relationship changes or combat consequences to
the real individual/item/actor stores.  No social row is a substitute for a
simulation transition.
"""

from __future__ import annotations

import copy
import math
from typing import Any, Iterable


SCHEMA = "gg.game-engine.social.v1"
VERSION = 1
MAX_RELATIONSHIPS = 128
MAX_HISTORY = 64
MAX_PAIRS_PER_PASS = 4
DEFAULT_RADIUS_M = 3.75
SOCIAL_COOLDOWN_S = 8.0
HOSTILE_PERSONALITIES = frozenset({"AGGRESSIVE", "RAIDER", "PREDATORY"})


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


def _clamp(value: Any, low: float, high: float, default: float = 0.0) -> float:
    return max(low, min(high, _safe_float(value, default)))


def _text(value: Any, default: str = "", limit: int = 96) -> str:
    return str(value or default).strip()[:limit]


def pair_id(first: Any, second: Any) -> str:
    values = sorted({_text(first, limit=64), _text(second, limit=64)})
    values = [value for value in values if value]
    return "|".join(values[:2]) if len(values) == 2 else ""


def new_state() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "relationships": {},
        "history": [],
        "last_event": {},
        "revision": 0,
    }


def _relationship(raw: Any, key: str) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    return {
        "pair_id": _text(raw.get("pair_id"), key, 128),
        "a_id": _text(raw.get("a_id"), limit=64),
        "b_id": _text(raw.get("b_id"), limit=64),
        "affinity": round(_clamp(raw.get("affinity"), -1.0, 1.0), 4),
        "trust": round(_clamp(raw.get("trust"), -1.0, 1.0), 4),
        "meetings": max(0, min(1_000_000, _safe_int(raw.get("meetings")))),
        "last_kind": _text(raw.get("last_kind"), "CONVERSE", 32).upper(),
        "last_outcome": _text(raw.get("last_outcome"), "", 96),
        "last_time_s": round(max(0.0, _safe_float(raw.get("last_time_s"))), 3),
        "cooldown_until": round(max(0.0, _safe_float(raw.get("cooldown_until"))), 3),
    }


def normalize_state(raw: Any) -> dict[str, Any]:
    base = new_state()
    source = raw if isinstance(raw, dict) else {}
    relationships = source.get("relationships", {})
    if isinstance(relationships, dict):
        for key, value in list(relationships.items())[:MAX_RELATIONSHIPS]:
            wanted = _text(key, limit=128)
            if not wanted:
                continue
            row = _relationship(value, wanted)
            if row is not None and row["a_id"] and row["b_id"]:
                base["relationships"][wanted] = row
    history = source.get("history", [])
    if isinstance(history, list):
        base["history"] = [
            {
                "pair_id": _text(item.get("pair_id"), limit=128),
                "a_id": _text(item.get("a_id"), limit=64),
                "b_id": _text(item.get("b_id"), limit=64),
                "kind": _text(item.get("kind"), "CONVERSE", 32).upper(),
                "distance_m": round(max(0.0, _safe_float(item.get("distance_m"))), 3),
                "outcome": _text(item.get("outcome"), limit=96),
                "time_s": round(max(0.0, _safe_float(item.get("time_s"))), 3),
            }
            for item in history[-MAX_HISTORY:]
            if isinstance(item, dict) and _text(item.get("pair_id"), limit=128)
        ]
    if isinstance(source.get("last_event"), dict):
        base["last_event"] = copy.deepcopy(source["last_event"])
    base["revision"] = max(0, _safe_int(source.get("revision")))
    return base


def _faction_id(person: dict[str, Any]) -> str:
    return _text(person.get("faction_id"), "WAYFARERS", 32).upper()


def _is_conflict(first: dict[str, Any], second: dict[str, Any]) -> bool:
    first_traits = {
        _text(value, limit=24).upper()
        for value in first.get("personality", [])
        if value
    }
    second_traits = {
        _text(value, limit=24).upper()
        for value in second.get("personality", [])
        if value
    }
    if first_traits.intersection(HOSTILE_PERSONALITIES) or second_traits.intersection(HOSTILE_PERSONALITIES):
        return True
    factions = {_faction_id(first), _faction_id(second)}
    # Wildkin and the two opportunist/warden groups are potential conflicts,
    # but only when an authored individual actually reaches the encounter.
    return "WILDKIN" in factions and bool(factions.intersection({"SHOREWARDENS", "FREEBOOTERS"}))


def nearby_pairs(
    people: dict[str, dict[str, Any]],
    positions: dict[str, tuple[float, float]],
    state: Any,
    sim_time: Any,
    *,
    radius_m: Any = DEFAULT_RADIUS_M,
) -> list[dict[str, Any]]:
    """Select deterministic nearby pairs whose social cooldown has elapsed."""
    source_state = normalize_state(state)
    radius = _clamp(radius_m, 1.0, 16.0, DEFAULT_RADIUS_M)
    now = max(0.0, _safe_float(sim_time))
    ids = sorted(
        identity_id
        for identity_id in positions
        if identity_id in people and isinstance(people.get(identity_id), dict)
    )
    result: list[dict[str, Any]] = []
    for offset, first_id in enumerate(ids):
        first_position = positions.get(first_id)
        first = people.get(first_id)
        if first_position is None or not isinstance(first, dict):
            continue
        for second_id in ids[offset + 1:]:
            second_position = positions.get(second_id)
            second = people.get(second_id)
            if second_position is None or not isinstance(second, dict):
                continue
            key = pair_id(first_id, second_id)
            relationship = source_state["relationships"].get(key, {})
            if now + 0.0001 < _safe_float(relationship.get("cooldown_until")):
                continue
            distance = math.hypot(
                _safe_float(first_position[0]) - _safe_float(second_position[0]),
                _safe_float(first_position[1]) - _safe_float(second_position[1]),
            )
            if distance > radius:
                continue
            hostile_history = _safe_float(relationship.get("affinity")) <= -0.35
            result.append(
                {
                    "pair_id": key,
                    "a_id": first_id,
                    "b_id": second_id,
                    "kind": "CONFLICT"
                    if _is_conflict(first, second) or hostile_history
                    else "CONVERSE",
                    "distance_m": round(distance, 3),
                    "time_s": round(now, 3),
                }
            )
    result.sort(key=lambda row: (str(row.get("kind")), float(row.get("distance_m", 0.0)), str(row.get("pair_id", ""))))
    return result[:MAX_PAIRS_PER_PASS]


def record(
    state: dict[str, Any],
    encounter: dict[str, Any],
    sim_time: Any,
    *,
    outcome: str = "ACKNOWLEDGED",
) -> dict[str, Any]:
    """Commit one meeting and advance its durable relation/cooldown."""
    if not isinstance(state, dict):
        return {}
    pair = pair_id(encounter.get("a_id"), encounter.get("b_id"))
    if not pair:
        return {"error": "SOCIAL_PAIR_REQUIRED"}
    now = max(0.0, _safe_float(sim_time))
    relationships = state.setdefault("relationships", {})
    previous = relationships.get(pair)
    row = _relationship(previous, pair) or {
        "pair_id": pair,
        "a_id": min(_text(encounter.get("a_id"), limit=64), _text(encounter.get("b_id"), limit=64)),
        "b_id": max(_text(encounter.get("a_id"), limit=64), _text(encounter.get("b_id"), limit=64)),
        "affinity": 0.0,
        "trust": 0.0,
        "meetings": 0,
        "last_kind": "CONVERSE",
        "last_outcome": "",
        "last_time_s": 0.0,
        "cooldown_until": 0.0,
    }
    kind = _text(encounter.get("kind"), "CONVERSE", 32).upper()
    delta = -0.08 if kind == "CONFLICT" else 0.035
    trust_delta = -0.1 if kind == "CONFLICT" else 0.025
    row["affinity"] = round(_clamp(_safe_float(row.get("affinity")) + delta, -1.0, 1.0), 4)
    row["trust"] = round(_clamp(_safe_float(row.get("trust")) + trust_delta, -1.0, 1.0), 4)
    row["meetings"] = max(0, min(1_000_000, _safe_int(row.get("meetings"))) + 1)
    row["last_kind"] = kind
    row["last_outcome"] = _text(outcome, "ACKNOWLEDGED", 96)
    row["last_time_s"] = round(now, 3)
    row["cooldown_until"] = round(now + SOCIAL_COOLDOWN_S, 3)
    relationships[pair] = row
    state["relationships"] = dict(list(relationships.items())[:MAX_RELATIONSHIPS])
    history_row = {
        "pair_id": pair,
        "a_id": row["a_id"],
        "b_id": row["b_id"],
        "kind": kind,
        "distance_m": round(max(0.0, _safe_float(encounter.get("distance_m"))), 3),
        "outcome": row["last_outcome"],
        "time_s": round(now, 3),
    }
    state.setdefault("history", []).append(history_row)
    state["history"] = state["history"][-MAX_HISTORY:]
    state["last_event"] = copy.deepcopy(history_row)
    state["revision"] = max(0, _safe_int(state.get("revision"))) + 1
    return copy.deepcopy({**row, "event": history_row})


def view(state: Any, active_ids: Iterable[str] | None = None) -> dict[str, Any]:
    source = normalize_state(state)
    allowed = {str(value) for value in active_ids} if active_ids is not None else None
    relationships: list[dict[str, Any]] = []
    for key in sorted(source.get("relationships", {}))[:MAX_RELATIONSHIPS]:
        row = source["relationships"].get(key)
        if not isinstance(row, dict):
            continue
        if allowed is not None and not ({str(row.get("a_id")), str(row.get("b_id"))} & allowed):
            continue
        relationships.append(copy.deepcopy(row))
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "relationships": relationships,
        "relationship_count": len(relationships),
        "history": copy.deepcopy(source.get("history", [])[-MAX_HISTORY:]),
        "last_event": copy.deepcopy(source.get("last_event", {})),
        "revision": max(0, _safe_int(source.get("revision"))),
        "policy": "POSITION_GATED_NPC_MEETINGS_WITH_DURABLE_MEMORY_AND_RELATIONS",
    }
