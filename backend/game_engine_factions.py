"""Bounded faction reputation and NPC disposition rules.

Faction standing is durable simulation data.  It is intentionally separate
from rendering and from the prose memory on an NPC, so a hostile act or a
quest reward changes the same relation in rich 3D, DOS and SAVE/LOAD.
"""

from __future__ import annotations

import copy
import math
from typing import Any, Iterable


SCHEMA = "gg.game-engine.factions.v1"
VERSION = 1
MAX_FACTIONS = 8
MAX_PEOPLE = 96
MAX_REPUTATION = 100000

FACTIONS: dict[str, dict[str, Any]] = {
    "SHOREWARDENS": {
        "id": "SHOREWARDENS",
        "name": "Shorewardens",
        "description": "Keepers of the island roads, caches and tidal gates.",
        "hostile_at": -50,
        "friendly_at": 50,
    },
    "FREEBOOTERS": {
        "id": "FREEBOOTERS",
        "name": "Freebooters",
        "description": "Scavengers and traders who follow opportunity across the shore.",
        "hostile_at": -50,
        "friendly_at": 50,
    },
    "WILDKIN": {
        "id": "WILDKIN",
        "name": "Wildkin",
        "description": "Foragers and creatures that claim the living parts of the island.",
        "hostile_at": -50,
        "friendly_at": 50,
    },
    "WAYFARERS": {
        "id": "WAYFARERS",
        "name": "Wayfarers",
        "description": "Couriers, fishers and unaffiliated people moving between settlements.",
        "hostile_at": -50,
        "friendly_at": 50,
    },
}


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


def _text(value: Any, default: str = "", limit: int = 64) -> str:
    return str(value or default).strip()[:limit]


def faction_for_identity(
    *,
    role: Any = "",
    archetype: Any = "",
    occupation: Any = "",
) -> str:
    values = {
        _text(role, limit=32).upper(),
        _text(archetype, limit=32).upper(),
        _text(occupation, limit=32).upper(),
    }
    if values.intersection({"GUARDIAN", "WARDEN", "BLACKSMITH", "LEATHERWORKER"}):
        return "SHOREWARDENS"
    if values.intersection({"SCAVENGER", "RAIDER", "DUELIST"}):
        return "FREEBOOTERS"
    if values.intersection({"CRITTER", "FORAGER", "WILDLIFE"}):
        return "WILDKIN"
    return "WAYFARERS"


def _faction_id(value: Any, default: str = "WAYFARERS") -> str:
    wanted = _text(value, default, 32).upper()
    return wanted if wanted in FACTIONS else default


def _standing(value: Any) -> int:
    return max(-MAX_REPUTATION, min(MAX_REPUTATION, _safe_int(value)))


def disposition(value: Any, faction_id: Any = "") -> str:
    faction = FACTIONS.get(_faction_id(faction_id)) or {}
    standing = _standing(value)
    if standing <= _safe_int(faction.get("hostile_at"), -50):
        return "HOSTILE"
    if standing >= _safe_int(faction.get("friendly_at"), 50):
        return "FRIENDLY"
    return "NEUTRAL"


def _person_row(raw: Any, identity_id: str) -> dict[str, Any]:
    row = raw if isinstance(raw, dict) else {}
    faction_id = _faction_id(row.get("faction_id"))
    standing = _standing(row.get("standing"))
    return {
        "identity_id": _text(row.get("identity_id"), identity_id, 64),
        "faction_id": faction_id,
        "standing": standing,
        "disposition": disposition(standing, faction_id),
        "last_change": _safe_int(row.get("last_change")),
        "last_source": _text(row.get("last_source"), limit=48),
    }


def new_state(people: Iterable[dict[str, Any]] | None = None) -> dict[str, Any]:
    person_rows: dict[str, dict[str, Any]] = {}
    for raw in list(people or [])[:MAX_PEOPLE]:
        if not isinstance(raw, dict):
            continue
        identity_id = _text(raw.get("id"), limit=64)
        if not identity_id:
            continue
        person_rows[identity_id] = _person_row(
            {
                "identity_id": identity_id,
                "faction_id": raw.get("faction_id")
                or faction_for_identity(
                    role=raw.get("role"),
                    archetype=raw.get("archetype"),
                    occupation=raw.get("occupation"),
                ),
            },
            identity_id,
        )
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "player": {faction_id: 0 for faction_id in list(FACTIONS)[:MAX_FACTIONS]},
        "people": person_rows,
        "last_change": {},
        "revision": 0,
    }


def normalize_state(
    raw: Any,
    people: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    base = new_state(people)
    source = raw if isinstance(raw, dict) else {}
    player = source.get("player", {})
    if isinstance(player, dict):
        for faction_id in list(base["player"]):
            base["player"][faction_id] = _standing(player.get(faction_id))
    saved_people = source.get("people", {})
    if isinstance(saved_people, dict):
        for identity_id, value in list(saved_people.items())[:MAX_PEOPLE]:
            wanted = _text(identity_id, limit=64)
            if not wanted:
                continue
            base["people"][wanted] = _person_row(value, wanted)
    last_change = source.get("last_change")
    if isinstance(last_change, dict):
        base["last_change"] = {
            key: copy.deepcopy(last_change[key])
            for key in ("faction_id", "identity_id", "amount", "source", "time_s")
            if key in last_change
        }
    base["revision"] = max(0, _safe_int(source.get("revision")))
    return base


def adjust_player(
    state: dict[str, Any],
    faction_id: Any,
    amount: Any,
    *,
    source: Any = "WORLD",
    sim_time: Any = 0.0,
) -> dict[str, Any]:
    wanted = _faction_id(faction_id)
    delta = max(-MAX_REPUTATION, min(MAX_REPUTATION, _safe_int(amount)))
    player = state.setdefault("player", {})
    before = _standing(player.get(wanted))
    after = _standing(before + delta)
    player[wanted] = after
    result = {
        "faction_id": wanted,
        "before": before,
        "after": after,
        "delta": after - before,
        "disposition": disposition(after, wanted),
        "source": _text(source, "WORLD", 48),
        "time_s": round(max(0.0, _safe_float(sim_time)), 3),
    }
    state["last_change"] = copy.deepcopy(result)
    state["revision"] = max(0, _safe_int(state.get("revision"))) + 1
    return result


def adjust_person(
    state: dict[str, Any],
    identity_id: Any,
    amount: Any,
    *,
    source: Any = "WORLD",
    sim_time: Any = 0.0,
) -> dict[str, Any]:
    people = state.setdefault("people", {})
    wanted = _text(identity_id, limit=64)
    row = people.get(wanted)
    if not isinstance(row, dict):
        row = _person_row({}, wanted)
        people[wanted] = row
    delta = max(-MAX_REPUTATION, min(MAX_REPUTATION, _safe_int(amount)))
    before = _standing(row.get("standing"))
    after = _standing(before + delta)
    row["standing"] = after
    row["disposition"] = disposition(after, row.get("faction_id"))
    row["last_change"] = delta
    row["last_source"] = _text(source, "WORLD", 48)
    result = {
        "identity_id": wanted,
        "faction_id": _faction_id(row.get("faction_id")),
        "before": before,
        "after": after,
        "delta": after - before,
        "disposition": row["disposition"],
        "source": _text(source, "WORLD", 48),
        "time_s": round(max(0.0, _safe_float(sim_time)), 3),
    }
    state["last_change"] = copy.deepcopy(result)
    state["revision"] = max(0, _safe_int(state.get("revision"))) + 1
    return result


def person_faction(state: dict[str, Any], identity_id: Any) -> str:
    people = state.get("people", {}) if isinstance(state, dict) else {}
    row = people.get(str(identity_id)) if isinstance(people, dict) else None
    return _faction_id(row.get("faction_id")) if isinstance(row, dict) else "WAYFARERS"


def view(state: Any) -> dict[str, Any]:
    source = normalize_state(state)
    people = source.get("people", {})
    faction_rows = []
    for faction_id in list(FACTIONS)[:MAX_FACTIONS]:
        definition = FACTIONS[faction_id]
        faction_rows.append(
            {
                **copy.deepcopy(definition),
                "player_standing": _standing(source.get("player", {}).get(faction_id)),
                "player_disposition": disposition(
                    source.get("player", {}).get(faction_id), faction_id
                ),
            }
        )
    person_rows = []
    if isinstance(people, dict):
        for identity_id in sorted(people)[:MAX_PEOPLE]:
            row = people.get(identity_id)
            if isinstance(row, dict):
                person_rows.append(copy.deepcopy(row))
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "factions": faction_rows,
        "people": person_rows,
        "last_change": copy.deepcopy(source.get("last_change", {})),
        "revision": max(0, _safe_int(source.get("revision"))),
        "policy": "AUTHORITATIVE_REPUTATION_DISPOSITION_WITH_PERSON_BINDINGS",
    }
