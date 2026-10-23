"""Bounded authoritative event journal for the local GAME ENGINE.

The journal is an audit trail of state transitions, not a second simulation
and not a source of synthetic UI progress.  Callers mutate the canonical
inventory, gear, NPC and world state first; this contract then records the
bounded fact that the transition happened.  The payload sanitizer keeps a
malformed or oversized client event from turning the snapshot or memory save
into an unbounded data sink.
"""

from __future__ import annotations

from copy import deepcopy
import math
from typing import Any, Iterable


SCHEMA = "gg.game-engine.events.v1"
VERSION = 1
MAX_EVENTS = 256
MAX_EVENT_TEXT = 192
MAX_EVENT_ID = 96
MAX_PAYLOAD_KEYS = 16
MAX_PAYLOAD_ITEMS = 16
MAX_PAYLOAD_DEPTH = 3
MAX_SEQUENCE = 2_000_000_000


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


def _text(value: Any, default: str = "", limit: int = MAX_EVENT_ID) -> str:
    return str(value or default).strip()[:limit]


def _safe_sequence(value: Any, default: int = 1) -> int:
    return max(1, min(MAX_SEQUENCE, _safe_int(value, default)))


def _safe_payload(value: Any, depth: int = 0) -> Any:
    """Return a deterministic, JSON-safe and bounded payload copy."""
    if depth > MAX_PAYLOAD_DEPTH:
        return "[DEPTH_LIMIT]"
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return max(-MAX_SEQUENCE, min(MAX_SEQUENCE, value))
    if isinstance(value, float):
        return round(value, 6) if math.isfinite(value) else 0.0
    if isinstance(value, str):
        return value[:MAX_EVENT_TEXT]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key in sorted(value, key=lambda item: str(item))[:MAX_PAYLOAD_KEYS]:
            result[_text(key, "field", 48)] = _safe_payload(value[key], depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [_safe_payload(item, depth + 1) for item in list(value)[:MAX_PAYLOAD_ITEMS]]
    return _text(value, "[UNSUPPORTED]", MAX_EVENT_TEXT)


def new_journal() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "next_sequence": 1,
        "events": [],
    }


def _normalize_event(raw: Any, sequence: int) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    kind = _text(raw.get("kind"), "UNSPECIFIED", 48).upper()
    text = _text(raw.get("text"), kind, MAX_EVENT_TEXT)
    return {
        "sequence": _safe_sequence(sequence),
        "tick": max(0, _safe_int(raw.get("tick"), 0)),
        "time_s": round(max(0.0, _safe_float(raw.get("time_s"), 0.0)), 3),
        "kind": kind,
        "actor_id": _text(raw.get("actor_id"), "system"),
        "subject_id": _text(raw.get("subject_id")),
        "target_id": _text(raw.get("target_id")),
        "text": text,
        "payload": _safe_payload(raw.get("payload", {})),
    }


def normalize(raw: Any) -> dict[str, Any]:
    """Restore a journal while enforcing ordering, shape and retention."""
    source_events: Iterable[Any]
    raw_next = 1
    if isinstance(raw, dict):
        source_events = raw.get("events", [])
        raw_next = _safe_sequence(raw.get("next_sequence"), 1)
    elif isinstance(raw, list):
        source_events = raw
    else:
        source_events = []
    if not isinstance(source_events, (list, tuple)):
        source_events = []

    result = new_journal()
    sequence = 1
    for raw_event in list(source_events)[-MAX_EVENTS:]:
        if not isinstance(raw_event, dict):
            continue
        requested = _safe_sequence(raw_event.get("sequence"), sequence)
        sequence = max(sequence, requested)
        normalized = _normalize_event(raw_event, sequence)
        if normalized is None:
            continue
        result["events"].append(normalized)
        sequence = min(MAX_SEQUENCE, sequence + 1)
    result["next_sequence"] = max(raw_next, sequence)
    if result["next_sequence"] > MAX_SEQUENCE:
        result["next_sequence"] = MAX_SEQUENCE
    return result


def append(
    journal: dict[str, Any],
    kind: Any,
    *,
    tick: Any = 0,
    sim_time: Any = 0.0,
    actor_id: Any = "system",
    subject_id: Any = "",
    target_id: Any = "",
    text: Any = "",
    payload: Any = None,
) -> dict[str, Any]:
    """Append one bounded event and return an isolated event copy."""
    if not isinstance(journal, dict):
        return {}
    if journal.get("schema") != SCHEMA:
        journal.clear()
        journal.update(new_journal())
    sequence = _safe_sequence(journal.get("next_sequence"), 1)
    raw_event = {
        "sequence": sequence,
        "tick": max(0, _safe_int(tick, 0)),
        "time_s": max(0.0, _safe_float(sim_time, 0.0)),
        "kind": _text(kind, "UNSPECIFIED", 48),
        "actor_id": _text(actor_id, "system"),
        "subject_id": _text(subject_id),
        "target_id": _text(target_id),
        "text": _text(text, _text(kind, "UNSPECIFIED", 48), MAX_EVENT_TEXT),
        "payload": {} if payload is None else payload,
    }
    event = _normalize_event(raw_event, sequence)
    if event is None:
        return {}
    events = journal.setdefault("events", [])
    if not isinstance(events, list):
        events = []
        journal["events"] = events
    events.append(event)
    journal["events"] = events[-MAX_EVENTS:]
    journal["version"] = VERSION
    journal["next_sequence"] = (
        1 if sequence >= MAX_SEQUENCE else sequence + 1
    )
    return deepcopy(event)


def view(raw: Any, limit: int = 24) -> dict[str, Any]:
    """Expose a stable chronological window without leaking mutable storage."""
    normalized = normalize(raw)
    safe_limit = max(0, min(MAX_EVENTS, _safe_int(limit, 24)))
    retained = normalized["events"][-safe_limit:] if safe_limit else []
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "count": len(normalized["events"]),
        "retention": MAX_EVENTS,
        "next_sequence": normalized["next_sequence"],
        "events": deepcopy(retained),
        "ordering": "CHRONOLOGICAL_ASCENDING_SEQUENCE",
        "policy": "BOUNDED_AUDIT_TRAIL_NO_SIMULATION_AUTHORITY",
    }


def restore(raw: Any) -> dict[str, Any]:
    """Named restore entry point for persistence call sites."""
    return normalize(raw)
