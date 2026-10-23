"""Bounded individual state for NPCs and ambient people.

The physics NPC contract remains a cheap state machine.  This companion
contract gives each person a durable identity, needs, carried/equipped item
references, goals and a short memory.  It is deliberately data-only and
updated at a low cadence, so richer world use can grow without moving
perception, camera or rendering work into the fixed-step hot path.
"""

from __future__ import annotations

import copy
import math
from typing import Any, Iterable

from backend import game_engine_factions as factions
from backend import game_engine_npc_progression as npc_progression
from backend import game_engine_schedules as schedules


SCHEMA = "gg.game-engine.npc.identity.v1"
VERSION = 1
MAX_INDIVIDUALS = 96
MAX_MEMORY = 8
MAX_CARRIED_ITEMS = 12
MAX_EQUIPPED_ITEMS = 19
MAX_GOALS = 4
MAX_TRAITS = 4
MAX_WORLD_ACTION_STATUS = 24
NEED_KEYS = ("hunger", "thirst", "fatigue", "curiosity")
ACTIVITIES = (
    "WANDER",
    "OBSERVE_PLAYER",
    "SEEK_FOOD",
    "SEEK_WATER",
    "INSPECT_LOOT",
    "GATHER",
    "CRAFT",
    "HAUL",
    "EXPLORE",
    "REST",
)


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


def _text(value: Any, default: str = "", limit: int = 64) -> str:
    return str(value or default).strip()[:limit]


def _seed(identity_id: Any) -> int:
    return sum((index + 1) * ord(char) for index, char in enumerate(str(identity_id))) & 0xFFFF


def _position(value: Any) -> dict[str, float]:
    row = value if isinstance(value, dict) else {}
    return {
        "x": _clamp(row.get("x"), -1000000.0, 1000000.0),
        "y": _clamp(row.get("y"), -1000000.0, 1000000.0),
        "z": _clamp(row.get("z"), -1000000.0, 1000000.0),
    }


def _default_individuals() -> tuple[dict[str, Any], ...]:
    return (
        {
            "id": "npc-wanderer-01",
            "name": "Mira Saltwake",
            "role": "WANDERER",
            "archetype": "WANDERER",
            "occupation": "SCAVENGER",
            "personality": ["CURIOUS", "SOCIABLE"],
            "needs": {"hunger": 0.28, "thirst": 0.34, "fatigue": 0.18, "curiosity": 0.72},
            "goals": [
                {"id": "goal.map-shore", "kind": "EXPLORE", "target": "shoreline"},
                {"id": "goal.find-gems", "kind": "INSPECT_LOOT", "target": "gem"},
            ],
            "inventory": ["item.old_boot", "item.sea_salt", "item.goblin_totem"],
            "equipment": ["item.iron_saber"],
            "home": {"x": 7.5, "y": 0.0, "z": 4.5},
            "action": "EXPLORE",
            "activity": "EXPLORE",
        },
        {
            "id": "npc-guardian-01",
            "name": "Brann Tidewatch",
            "role": "GUARDIAN",
            "archetype": "GUARDIAN",
            "occupation": "WARDEN",
            "personality": ["DUTIFUL", "CAUTIOUS"],
            "needs": {"hunger": 0.22, "thirst": 0.25, "fatigue": 0.32, "curiosity": 0.38},
            "goals": [
                {"id": "goal.guard-cache", "kind": "GUARD", "target": "supply-crate"},
                {"id": "goal.check-traveler", "kind": "OBSERVE", "target": "people"},
            ],
            "inventory": ["item.field_ration", "item.moon_shard"],
            "equipment": ["item.tideguard_jacket", "item.sunken_crown"],
            "home": {"x": -10.0, "y": 0.0, "z": 4.0},
            "action": "GATHER",
            "activity": "GATHER",
        },
        {
            "id": "npc-critter-01",
            "name": "Pip Pebbletail",
            "role": "CRITTER",
            "archetype": "CRITTER",
            "occupation": "FORAGER",
            "personality": ["PLAYFUL", "ALERT"],
            "needs": {"hunger": 0.56, "thirst": 0.48, "fatigue": 0.12, "curiosity": 0.82},
            "goals": [
                {"id": "goal.find-snacks", "kind": "GATHER", "target": "food"},
                {"id": "goal.avoid-danger", "kind": "FLEE", "target": "danger"},
            ],
            "inventory": ["item.sun_herb"],
            "equipment": [],
            "home": {"x": 4.0, "y": 0.0, "z": -9.0},
            "action": "GATHER",
            "activity": "GATHER",
        },
        {
            "id": "ambient-fisher-01",
            "name": "Olla Netmaker",
            "role": "FISHER",
            "archetype": "AMBIENT",
            "occupation": "FISHER",
            "personality": ["PATIENT", "OBSERVANT"],
            "needs": {"hunger": 0.42, "thirst": 0.37, "fatigue": 0.26, "curiosity": 0.46},
            "goals": [{"id": "goal.fish-tide", "kind": "GATHER", "target": "shoreline"}],
            "inventory": ["item.sea_salt"],
            "equipment": ["item.old_boot"],
            "home": {"x": -4.4, "y": 0.0, "z": -4.6},
            "action": "GATHER",
            "activity": "GATHER",
        },
        {
            "id": "ambient-traveler-01",
            "name": "Rook Farstep",
            "role": "TRAVELER",
            "archetype": "AMBIENT",
            "occupation": "COURIER",
            "personality": ["RESTLESS", "GENEROUS"],
            "needs": {"hunger": 0.31, "thirst": 0.4, "fatigue": 0.44, "curiosity": 0.63},
            "goals": [{"id": "goal.road-loop", "kind": "TRAVEL", "target": "road"}],
            "inventory": ["item.field_ration", "item.island_compass"],
            "equipment": ["item.island_compass"],
            "home": {"x": 5.1, "y": 0.0, "z": -3.7},
            "action": "EXPLORE",
            "activity": "EXPLORE",
        },
        {
            "id": "ambient-scout-01",
            "name": "Senn Highwatch",
            "role": "SCOUT",
            "archetype": "AMBIENT",
            "occupation": "SCOUT",
            "personality": ["FOCUSED", "CURIOUS"],
            "needs": {"hunger": 0.24, "thirst": 0.3, "fatigue": 0.2, "curiosity": 0.78},
            "goals": [{"id": "goal.ridge-sweep", "kind": "EXPLORE", "target": "ridge"}],
            "inventory": ["item.moon_shard"],
            "equipment": ["item.iron_saber"],
            "home": {"x": -6.1, "y": 0.0, "z": 5.0},
            "action": "EXPLORE",
            "activity": "EXPLORE",
        },
        {
            "id": "ambient-carrier-01",
            "name": "Brik Cratehand",
            "role": "CARRIER",
            "archetype": "AMBIENT",
            "occupation": "HAULER",
            "personality": ["PRACTICAL", "KIND"],
            "needs": {"hunger": 0.36, "thirst": 0.3, "fatigue": 0.51, "curiosity": 0.34},
            "goals": [{"id": "goal.crate-run", "kind": "HAUL", "target": "supply-crate"}],
            "inventory": ["item.sea_salt", "item.field_ration"],
            "equipment": ["item.tideguard_jacket"],
            "home": {"x": 6.8, "y": 0.0, "z": 5.5},
            "action": "HAUL",
            "activity": "HAUL",
        },
    )


def starter_individuals() -> dict[str, dict[str, Any]]:
    return {str(row["id"]): copy.deepcopy(row) for row in _default_individuals()}


def normalize_individual(raw: Any, fallback: dict[str, Any] | None = None) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    base = copy.deepcopy(fallback) if isinstance(fallback, dict) else {}
    base.update(copy.deepcopy(raw))
    identity_id = _text(base.get("id"), limit=64)
    if not identity_id:
        return None
    personality_values = base.get("personality", [])
    if not isinstance(personality_values, (list, tuple)):
        personality_values = []
    inventory_values = base.get("inventory", [])
    if not isinstance(inventory_values, (list, tuple)):
        inventory_values = []
    equipment_values = base.get("equipment", [])
    if not isinstance(equipment_values, (list, tuple)):
        equipment_values = []
    progression_seed = npc_progression.starter_state(
        identity_id,
        role=base.get("role"),
        archetype=base.get("archetype"),
        occupation=base.get("occupation"),
    )
    normalized_progression = npc_progression.normalize_state(
        base.get("progression"),
        progression_seed,
        identity_id=identity_id,
        role=base.get("role"),
        archetype=base.get("archetype"),
        occupation=base.get("occupation"),
    )
    result: dict[str, Any] = {
        "id": identity_id,
        "name": _text(base.get("name"), identity_id, 64),
        "role": _text(base.get("role"), "WANDERER", 32).upper(),
        "archetype": _text(base.get("archetype"), "AMBIENT", 32).upper(),
        "occupation": _text(base.get("occupation"), "TRAVELER", 32).upper(),
        "faction_id": _text(
            base.get("faction_id"),
            factions.faction_for_identity(
                role=base.get("role"),
                archetype=base.get("archetype"),
                occupation=base.get("occupation"),
            ),
            32,
        ).upper(),
        "personality": list(dict.fromkeys(
            _text(value, limit=24).upper()
            for value in personality_values[:MAX_TRAITS]
            if _text(value)
        ))[:MAX_TRAITS],
        "needs": {
            key: round(_clamp(
                (base.get("needs", {}) if isinstance(base.get("needs"), dict) else {}).get(key),
                0.0,
                1.0,
                0.25,
            ), 4)
            for key in NEED_KEYS
        },
        "goals": [],
        "inventory": [
            _text(value, limit=96)
            for value in inventory_values[:MAX_CARRIED_ITEMS]
            if _text(value)
        ],
        "equipment": [
            _text(value, limit=96)
            for value in equipment_values[:MAX_EQUIPPED_ITEMS]
            if _text(value)
        ],
        "progression": normalized_progression,
        "schedule": schedules.schedule_for(
            base.get("occupation"),
            base.get("schedule"),
        ),
        "home": _position(base.get("home")),
        "action": _text(base.get("action"), "WANDER", 32).upper(),
        "activity": _text(base.get("activity"), "WANDER", 32).upper(),
        "target": {},
        "memory": [],
        "relationship_to_player": round(_clamp(base.get("relationship_to_player"), -1.0, 1.0), 4),
        "last_update_s": max(0.0, _safe_float(base.get("last_update_s"))),
        "revision": max(0, _safe_int(base.get("revision"), 0)),
        "world_action": {
            "last_action": "",
            "target_id": "",
            "time_s": 0.0,
            "status": "NONE",
            "count": 0,
        },
    }
    if result["action"] not in ACTIVITIES:
        result["action"] = "WANDER"
    if result["activity"] not in ACTIVITIES:
        result["activity"] = result["action"]
    raw_world_action = base.get("world_action")
    if isinstance(raw_world_action, dict):
        result["world_action"] = {
            "last_action": _text(raw_world_action.get("last_action"), "WANDER", 32).upper()
            if raw_world_action.get("last_action")
            else "",
            "target_id": _text(raw_world_action.get("target_id"), limit=96),
            "time_s": round(max(0.0, _safe_float(raw_world_action.get("time_s"))), 3),
            "status": _text(raw_world_action.get("status"), "NONE", MAX_WORLD_ACTION_STATUS).upper(),
            "count": max(0, _safe_int(raw_world_action.get("count"), 0)),
        }
    raw_goals = base.get("goals", [])
    if isinstance(raw_goals, list):
        for raw_goal in raw_goals[:MAX_GOALS]:
            if not isinstance(raw_goal, dict):
                continue
            goal_id = _text(raw_goal.get("id"), limit=64)
            if not goal_id:
                continue
            result["goals"].append(
                {
                    "id": goal_id,
                    "kind": _text(raw_goal.get("kind"), "WANDER", 24).upper(),
                    "target": _text(raw_goal.get("target"), limit=64),
                }
            )
    raw_target = base.get("target")
    if isinstance(raw_target, dict):
        target_id = _text(raw_target.get("id"), limit=96)
        if target_id:
            result["target"] = {
                "id": target_id,
                "kind": _text(raw_target.get("kind"), "WORLD", 24).upper(),
                "x": _clamp(raw_target.get("x"), -1000000.0, 1000000.0),
                "z": _clamp(raw_target.get("z"), -1000000.0, 1000000.0),
            }
    raw_memory = base.get("memory", [])
    if isinstance(raw_memory, list):
        for raw_event in raw_memory[-MAX_MEMORY:]:
            if not isinstance(raw_event, dict):
                continue
            event_id = _text(raw_event.get("id"), limit=64)
            kind = _text(raw_event.get("kind"), "OBSERVE", 24).upper()
            if not event_id:
                event_id = f"{kind.lower()}-{len(result['memory']):02d}"
            result["memory"].append(
                {
                    "id": event_id,
                    "kind": kind,
                    "target_id": _text(raw_event.get("target_id"), limit=96),
                    "time_s": round(max(0.0, _safe_float(raw_event.get("time_s"))), 3),
                    "weight": round(_clamp(raw_event.get("weight"), 0.0, 1.0, 0.5), 3),
                    "text": _text(raw_event.get("text"), limit=96),
                }
            )
    return result


def catalog_from_content(content: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    defaults = starter_individuals()
    source = content.get("npc_individuals") if isinstance(content, dict) else None
    if isinstance(source, dict):
        rows = list(source.values())
    elif isinstance(source, list):
        rows = source
    else:
        rows = []
    for raw in rows[:MAX_INDIVIDUALS]:
        if not isinstance(raw, dict):
            continue
        identity_id = _text(raw.get("id"), limit=64)
        if not identity_id:
            continue
        normalized = normalize_individual(raw, defaults.get(identity_id))
        if normalized is not None:
            defaults[identity_id] = normalized
    return dict(list(defaults.items())[:MAX_INDIVIDUALS])


def runtime_state(catalog: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    source = catalog if isinstance(catalog, dict) else catalog_from_content()
    individuals: dict[str, dict[str, Any]] = {}
    for identity_id, raw in list(source.items())[:MAX_INDIVIDUALS]:
        normalized = normalize_individual(raw)
        if normalized is not None:
            individuals[normalized["id"]] = normalized
    return {"schema": SCHEMA, "version": VERSION, "individuals": individuals}


def restore_state(raw: Any, catalog: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    base = runtime_state(catalog)
    source = raw.get("individuals") if isinstance(raw, dict) else raw
    if not isinstance(source, dict):
        return base
    for identity_id, value in list(source.items())[:MAX_INDIVIDUALS]:
        fallback = base["individuals"].get(str(identity_id))
        if isinstance(value, dict):
            candidate = copy.deepcopy(value)
            candidate["id"] = identity_id
        else:
            candidate = None
        normalized = normalize_individual(candidate, fallback)
        if normalized is not None:
            base["individuals"][normalized["id"]] = normalized
    base["individuals"] = dict(list(base["individuals"].items())[:MAX_INDIVIDUALS])
    return base


def ensure_individual(
    state: dict[str, Any],
    identity_id: Any,
    *,
    archetype: str = "WANDERER",
    role: str = "WANDERER",
    home: dict[str, Any] | None = None,
) -> dict[str, Any]:
    people = state.setdefault("individuals", {})
    wanted = _text(identity_id, "person-unknown", 64)
    existing = people.get(wanted)
    if isinstance(existing, dict):
        return existing
    if len(people) >= MAX_INDIVIDUALS:
        return next(iter(people.values()))
    ordinal = len(people) + 1
    created = normalize_individual(
        {
            "id": wanted,
            "name": f"Newcomer {ordinal:02d}",
            "role": role,
            "archetype": archetype,
            "occupation": "TRAVELER",
            "personality": ["CURIOUS"],
            "home": home or {},
            "action": "WANDER",
            "activity": "WANDER",
        }
    )
    if created is None:
        created = normalize_individual({"id": wanted}) or {"id": wanted}
    people[wanted] = created
    return created


def _distance(x: Any, z: Any, target_x: Any, target_z: Any) -> float:
    return math.hypot(_safe_float(x) - _safe_float(target_x), _safe_float(z) - _safe_float(target_z))


def _target_row(raw: Any, *, fallback_kind: str = "WORLD") -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    target_id = _text(raw.get("id"), limit=96)
    if not target_id:
        return None
    return {
        "id": target_id,
        "kind": _text(raw.get("kind"), fallback_kind, 24).upper(),
        "x": _clamp(raw.get("x"), -1000000.0, 1000000.0),
        "z": _clamp(raw.get("z"), -1000000.0, 1000000.0),
    }


def _nearest_target(
    person: dict[str, Any],
    rows: Iterable[dict[str, Any]],
    *,
    preferred_kinds: set[str] | None = None,
    preferred_tags: set[str] | None = None,
    preferred_gear: bool = False,
) -> dict[str, Any] | None:
    home = person.get("home", {}) if isinstance(person.get("home"), dict) else {}
    source_rows = [row for row in rows if isinstance(row, dict)]
    if preferred_gear:
        gear_rows = [
            row for row in source_rows
            if _safe_float(row.get("gear_score")) > 0.0
        ]
        if gear_rows:
            source_rows = gear_rows
    best: dict[str, Any] | None = None
    best_score = float("inf")
    for raw in source_rows:
        if not isinstance(raw, dict):
            continue
        candidate = _target_row(raw)
        if candidate is None:
            continue
        kind = str(raw.get("kind", "WORLD")).upper()
        tags = {str(tag).upper() for tag in raw.get("tags", []) if tag}
        if preferred_kinds and kind not in preferred_kinds:
            continue
        if preferred_tags and not tags.intersection(preferred_tags):
            continue
        distance = _distance(home.get("x"), home.get("z"), candidate["x"], candidate["z"])
        # Prefer authored semantic matches, then deterministic distance/id.
        score = distance - (2.0 if preferred_tags and tags.intersection(preferred_tags) else 0.0)
        if score < best_score or (
            abs(score - best_score) <= 0.0001
            and best is not None
            and candidate["id"] < best["id"]
        ):
            best = candidate
            best_score = score
    return best


def _choose_activity(
    person: dict[str, Any],
    sim_time: float,
    player_x: float,
    player_z: float,
    world_items: list[dict[str, Any]],
    stations: list[dict[str, Any]],
) -> tuple[str, dict[str, Any] | None]:
    home = person.get("home", {}) if isinstance(person.get("home"), dict) else {}
    needs = person.get("needs", {}) if isinstance(person.get("needs"), dict) else {}
    player_distance = _distance(home.get("x"), home.get("z"), player_x, player_z)
    if player_distance <= 7.5:
        return "OBSERVE_PLAYER", {"id": "player", "kind": "PLAYER", "x": player_x, "z": player_z}
    if _safe_float(needs.get("fatigue")) >= 0.78:
        return "REST", {"id": f"home:{person.get('id', '')}", "kind": "HOME", "x": _safe_float(home.get("x")), "z": _safe_float(home.get("z"))}
    if _safe_float(needs.get("thirst")) >= 0.75:
        target = _nearest_target(person, stations, preferred_tags={"WATER", "COOKING"})
        return "SEEK_WATER", target
    if _safe_float(needs.get("hunger")) >= 0.75:
        target = _nearest_target(person, world_items, preferred_tags={"FOOD", "COOKING"})
        return "SEEK_FOOD", target

    # A schedule is an authored preference, not a blind override.  Critical
    # needs and nearby player perception above still win; an unavailable
    # scheduled target falls through to the occupation policy below.
    scheduled = schedules.active_slot(person.get("schedule"), sim_time)
    if isinstance(scheduled, dict):
        scheduled_activity = str(scheduled.get("activity", "WANDER")).upper()
        target_kind = str(scheduled.get("target_kind", "NONE")).upper()
        if scheduled_activity == "REST":
            # A calendar is a preference, not a sleep animation forced onto
            # every person at the start of a new world.  Only a genuinely
            # tired individual follows the rest slot; otherwise occupation
            # goals (for example a scavenger seeing a real cache) remain
            # actionable.  This keeps schedules meaningful without masking
            # the existing need/goal contract.
            if _safe_float(needs.get("fatigue")) >= 0.5:
                return "REST", {
                    "id": f"home:{person.get('id', '')}",
                    "kind": "HOME",
                    "x": _safe_float(home.get("x")),
                    "z": _safe_float(home.get("z")),
                }
        if scheduled_activity == "WANDER":
            return "WANDER", None
        target = None
        if target_kind == "GEAR":
            target = _nearest_target(person, world_items, preferred_gear=True)
        elif target_kind == "CONTAINER":
            target = _nearest_target(person, world_items, preferred_kinds={"CONTAINER", "CHEST"})
        elif target_kind in {"NATURE", "FOOD"}:
            target = _nearest_target(person, world_items, preferred_tags={target_kind})
        elif target_kind == "STATION":
            target = _nearest_target(person, stations)
        if target is not None:
            return scheduled_activity, target

    occupation = str(person.get("occupation", "TRAVELER")).upper()
    if occupation in {"HAULER", "COURIER"}:
        target = _nearest_target(person, world_items, preferred_kinds={"CONTAINER", "CHEST"})
        return "HAUL", target
    if occupation in {"FISHER", "FORAGER"}:
        target = _nearest_target(person, world_items, preferred_tags={"FOOD", "NATURE", "WATER"})
        return "GATHER", target
    if occupation in {"WARDEN", "BLACKSMITH", "LEATHERWORKER"}:
        target = _nearest_target(person, stations, preferred_tags={"REPAIR", "METAL", "SURVIVAL"})
        return "CRAFT", target
    if occupation in {"SCOUT", "SCAVENGER"} or _safe_float(needs.get("curiosity")) >= 0.62:
        target = _nearest_target(person, world_items, preferred_gear=True)
        if target is not None:
            return "INSPECT_LOOT", target
        target = _nearest_target(person, stations, preferred_tags={"SURVIVAL", "SOCKETING"})
        return "EXPLORE", target

    cycle = (int(max(0.0, sim_time) // 6.0) + _seed(person.get("id"))) % 4
    if cycle == 0:
        target = _nearest_target(person, stations, preferred_tags={"SURVIVAL"})
        return "CRAFT", target
    if cycle == 1:
        target = _nearest_target(person, world_items)
        return "INSPECT_LOOT", target
    if cycle == 2:
        target = _nearest_target(person, stations)
        return "EXPLORE", target
    return "WANDER", None


def record_memory(
    state: dict[str, Any],
    identity_id: Any,
    kind: Any,
    target_id: Any,
    sim_time: Any,
    *,
    text: str = "",
    weight: float = 0.5,
) -> dict[str, Any] | None:
    people = state.get("individuals", {}) if isinstance(state, dict) else {}
    person = people.get(str(identity_id)) if isinstance(people, dict) else None
    if not isinstance(person, dict):
        return None
    memory = person.setdefault("memory", [])
    if not isinstance(memory, list):
        memory = []
        person["memory"] = memory
    memory_kind = _text(kind, "OBSERVE", 24).upper()
    memory_target = _text(target_id, limit=96)
    event = {
        "id": f"{memory_kind.lower()}:{memory_target or 'world'}:{max(0, _safe_int(_safe_float(sim_time) * 10)):06d}",
        "kind": memory_kind,
        "target_id": memory_target,
        "time_s": round(max(0.0, _safe_float(sim_time)), 3),
        "weight": round(_clamp(weight, 0.0, 1.0, 0.5), 3),
        "text": _text(text, limit=96),
    }
    for previous in reversed(memory):
        if (
            isinstance(previous, dict)
            and previous.get("kind") == event["kind"]
            and previous.get("target_id") == event["target_id"]
            and abs(_safe_float(previous.get("time_s")) - event["time_s"]) < 3.0
        ):
            previous.update(event)
            return previous
    memory.append(event)
    person["memory"] = memory[-MAX_MEMORY:]
    person["revision"] = max(0, _safe_int(person.get("revision"))) + 1
    return event


def record_world_action(
    state: dict[str, Any],
    identity_id: Any,
    action: Any,
    target_id: Any,
    sim_time: Any,
    *,
    status: str = "COMMITTED",
    text: str = "",
) -> dict[str, Any] | None:
    """Commit one bounded world-use outcome to a person's durable state."""
    people = state.get("individuals", {}) if isinstance(state, dict) else {}
    person = people.get(str(identity_id)) if isinstance(people, dict) else None
    if not isinstance(person, dict):
        return None
    previous = person.get("world_action")
    previous_count = (
        _safe_int(previous.get("count"), 0)
        if isinstance(previous, dict)
        else 0
    )
    row = {
        "last_action": _text(action, "WANDER", 32).upper(),
        "target_id": _text(target_id, limit=96),
        "time_s": round(max(0.0, _safe_float(sim_time)), 3),
        "status": _text(status, "COMMITTED", MAX_WORLD_ACTION_STATUS).upper(),
        "count": max(0, previous_count) + 1,
    }
    person["world_action"] = row
    person["revision"] = max(0, _safe_int(person.get("revision"))) + 1
    record_memory(
        state,
        identity_id,
        "WORLD_ACTION",
        row["target_id"],
        row["time_s"],
        text=text or f"{row['last_action'].lower()} {row['status'].lower()}",
        weight=0.55 if row["status"] == "COMMITTED" else 0.35,
    )
    return copy.deepcopy(row)


def tick(
    state: dict[str, Any],
    sim_time: Any,
    *,
    player_x: Any = 0.0,
    player_z: Any = 0.0,
    world_items: Iterable[dict[str, Any]] = (),
    stations: Iterable[dict[str, Any]] = (),
    active_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Advance individual needs and choose one bounded world action per person."""
    if not isinstance(state, dict):
        return {}
    safe_time = max(0.0, _safe_float(sim_time))
    item_rows = [row for row in list(world_items)[:32] if isinstance(row, dict)]
    station_rows = [row for row in list(stations)[:8] if isinstance(row, dict)]
    allowed = {str(value) for value in active_ids} if active_ids is not None else None
    people = state.get("individuals", {})
    if not isinstance(people, dict):
        return state
    for identity_id, person in list(people.items())[:MAX_INDIVIDUALS]:
        if allowed is not None and str(identity_id) not in allowed:
            continue
        if not isinstance(person, dict):
            continue
        previous_time = max(0.0, _safe_float(person.get("last_update_s")))
        delta = max(0.0, min(1.0, safe_time - previous_time))
        if delta <= 0.0 and safe_time > 0.0:
            continue
        needs = person.get("needs", {})
        if not isinstance(needs, dict):
            needs = {}
            person["needs"] = needs
        needs["hunger"] = round(_clamp(_safe_float(needs.get("hunger")) + delta * 0.004, 0.0, 1.0), 4)
        needs["thirst"] = round(_clamp(_safe_float(needs.get("thirst")) + delta * 0.006, 0.0, 1.0), 4)
        needs["fatigue"] = round(_clamp(_safe_float(needs.get("fatigue")) + delta * 0.003, 0.0, 1.0), 4)
        needs["curiosity"] = round(_clamp(_safe_float(needs.get("curiosity")) + delta * 0.001, 0.0, 1.0), 4)
        old_activity = _text(person.get("activity"), "WANDER", 32).upper()
        activity, target = _choose_activity(
            person,
            safe_time,
            _safe_float(player_x),
            _safe_float(player_z),
            item_rows,
            station_rows,
        )
        person["action"] = activity
        person["activity"] = activity
        person["target"] = target or {}
        person["last_update_s"] = round(safe_time, 3)
        if activity != old_activity:
            record_memory(
                state,
                identity_id,
                "ACTIVITY_CHANGE",
                target.get("id", "") if isinstance(target, dict) else "",
                safe_time,
                text=f"{old_activity} -> {activity}",
                weight=0.45,
            )
        if activity == "OBSERVE_PLAYER":
            person["relationship_to_player"] = round(
                _clamp(_safe_float(person.get("relationship_to_player")) + 0.002, -1.0, 1.0),
                4,
            )
            record_memory(state, identity_id, "PLAYER_SEEN", "player", safe_time, text="Player nearby", weight=0.6)
        elif isinstance(target, dict) and target.get("id"):
            record_memory(
                state,
                identity_id,
                "WORLD_TARGET",
                target.get("id"),
                safe_time,
                text=f"Using world: {activity.lower()}",
                weight=0.35,
            )
    return state


def target_for(state: dict[str, Any], identity_id: Any) -> dict[str, Any] | None:
    people = state.get("individuals", {}) if isinstance(state, dict) else {}
    person = people.get(str(identity_id)) if isinstance(people, dict) else None
    target = person.get("target") if isinstance(person, dict) else None
    return copy.deepcopy(target) if isinstance(target, dict) and target.get("id") else None


def view(state: dict[str, Any], identity_id: Any) -> dict[str, Any]:
    people = state.get("individuals", {}) if isinstance(state, dict) else {}
    person = people.get(str(identity_id)) if isinstance(people, dict) else None
    if not isinstance(person, dict):
        person = {"id": str(identity_id or "person-unknown")}
    return {
        "id": _text(person.get("id"), "person-unknown", 64),
        "name": _text(person.get("name"), "Unknown Person", 64),
        "role": _text(person.get("role"), "WANDERER", 32).upper(),
        "archetype": _text(person.get("archetype"), "AMBIENT", 32).upper(),
        "occupation": _text(person.get("occupation"), "TRAVELER", 32).upper(),
        "faction_id": _text(person.get("faction_id"), "WAYFARERS", 32).upper(),
        "personality": [_text(value, limit=24).upper() for value in person.get("personality", [])[:MAX_TRAITS]],
        "needs": {
            key: round(_clamp((person.get("needs", {}) if isinstance(person.get("needs"), dict) else {}).get(key), 0.0, 1.0), 3)
            for key in NEED_KEYS
        },
        "goals": copy.deepcopy(person.get("goals", [])[:MAX_GOALS]) if isinstance(person.get("goals"), list) else [],
        "inventory": [_text(value, limit=96) for value in person.get("inventory", [])[:MAX_CARRIED_ITEMS]],
        "equipment": [_text(value, limit=96) for value in person.get("equipment", [])[:MAX_EQUIPPED_ITEMS]],
        "action": _text(person.get("action"), "WANDER", 32).upper(),
        "activity": _text(person.get("activity"), "WANDER", 32).upper(),
        "target": copy.deepcopy(person.get("target", {})) if isinstance(person.get("target"), dict) else {},
        "memory": copy.deepcopy(person.get("memory", [])[-MAX_MEMORY:]) if isinstance(person.get("memory"), list) else [],
        "world_action": copy.deepcopy(person.get("world_action", {}))
        if isinstance(person.get("world_action"), dict)
        else {},
        "progression": npc_progression.summary(person.get("progression")),
        "schedule": schedules.view(person.get("schedule", []), person.get("last_update_s", 0.0)),
        "relationship_to_player": round(_clamp(person.get("relationship_to_player"), -1.0, 1.0), 3),
        "last_update_s": round(max(0.0, _safe_float(person.get("last_update_s"))), 3),
        "revision": max(0, _safe_int(person.get("revision"))),
    }


def build_view(state: dict[str, Any], active_ids: Iterable[str] | None = None) -> dict[str, Any]:
    people = state.get("individuals", {}) if isinstance(state, dict) else {}
    allowed = {str(value) for value in active_ids} if active_ids is not None else None
    rows: list[dict[str, Any]] = []
    activities: dict[str, int] = {}
    memory_events = 0
    needs_total = {key: 0.0 for key in NEED_KEYS}
    progression_levels = 0
    progression_power = 0.0
    progression_ascensions = 0
    progression_max_power = 0.0
    if isinstance(people, dict):
        for identity_id in sorted(people)[:MAX_INDIVIDUALS]:
            if allowed is not None and identity_id not in allowed:
                continue
            row = view(state, identity_id)
            rows.append(row)
            activity = row["activity"]
            activities[activity] = activities.get(activity, 0) + 1
            memory_events += len(row["memory"])
            for key in NEED_KEYS:
                needs_total[key] += float(row["needs"][key])
            progression = row.get("progression", {})
            if isinstance(progression, dict):
                progression_levels += max(1, _safe_int(progression.get("level"), 1))
                power = max(0.0, _safe_float(progression.get("power_score")))
                progression_power += power
                progression_max_power = max(progression_max_power, power)
                progression_ascensions += max(0, _safe_int(progression.get("ascension"), 0))
    population = len(rows)
    average_needs = {
        key: round(value / population, 3) if population else 0.0
        for key, value in needs_total.items()
    }
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "population": population,
        "budget": MAX_INDIVIDUALS,
        "active": population,
        "unique_names": len({row["name"] for row in rows}),
        "activities": dict(sorted(activities.items())),
        "average_needs": average_needs,
        "memory_events": memory_events,
        "progression": {
            "average_level": round(progression_levels / population, 3) if population else 0.0,
            "average_power_score": round(progression_power / population, 3) if population else 0.0,
            "max_power_score": round(progression_max_power, 3),
            "ascensions": progression_ascensions,
        },
        "people": rows,
        "simulation": "BOUNDED_LOW_RATE_INDIVIDUAL_WORLD_USE",
        "policy": "IDENTITY_NEEDS_MEMORY_GOALS_INVENTORY_EQUIPMENT_PROGRESSION",
    }
