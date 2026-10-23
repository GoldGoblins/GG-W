"""Small, deterministic NPC primitives for the GAME ENGINE preview.

The first NPC layer is intentionally a cheap simulation contract, not a
general-purpose agent framework.  Perception is radial, line-of-sight aware
and bounded, decisions
run at a lower cadence than movement, and each archetype is a small state
machine.  The host can replace each decision target with a short bounded A*
waypoint route without changing the snapshot or editor contracts; direct
steering remains the explicit fallback when no route is available.
"""

from __future__ import annotations

import math
from typing import Any, NamedTuple


SCHEMA = "gg.game-engine.npc.v1"
VERSION = 1
MAX_NPCS = 96
DECISION_HZ = 20
MOVEMENT_HZ = 60
DECISION_TICKS = max(1, MOVEMENT_HZ // DECISION_HZ)
STATES = ("WANDER", "FOLLOW", "ALERT", "FLEE", "DEAD")
ARCHETYPES = ("WANDERER", "GUARDIAN", "CRITTER")
PERCEPTION_MODEL = "RADIAL_LOS_BOUNDED"
NAVIGATION_STATUS = "TILED_HEIGHTFIELD_ASTAR_QUERY; DIRECT_FALLBACK_BOUNDED"
INTERACTION_RADIUS_M = 3.5

# These are gameplay-space values.  They are deliberately small enough to
# make the behavior visible in the first-island preview and are not tied to a
# final character scale or combat balance pass.
PROFILES: dict[str, dict[str, float]] = {
    "WANDERER": {
        "speed": 1.55,
        "run_speed": 2.1,
        "sense_radius": 10.0,
        "alert_radius": 0.0,
        "danger_radius": 0.0,
        "stop_distance": 2.7,
        "wander_radius": 5.5,
        "memory_s": 1.25,
    },
    "GUARDIAN": {
        "speed": 1.25,
        "run_speed": 1.65,
        "sense_radius": 14.0,
        "alert_radius": 7.0,
        "danger_radius": 0.0,
        "stop_distance": 5.5,
        "wander_radius": 4.0,
        "memory_s": 2.0,
    },
    "CRITTER": {
        "speed": 1.8,
        "run_speed": 2.8,
        "sense_radius": 8.5,
        "alert_radius": 0.0,
        "danger_radius": 5.5,
        "stop_distance": 3.5,
        "wander_radius": 6.5,
        "memory_s": 0.65,
    },
}

# Stable authoring seeds make a reset/replay visually useful.  The host turns
# these into pooled runtime entities and keeps their metadata separate from
# the generic render arrays.
DEFAULT_SPAWNS: tuple[dict[str, Any], ...] = (
    {
        "id": "npc-wanderer-01",
        "archetype": "WANDERER",
        "x": 6.8,
        "z": 5.6,
        "scale": (0.9, 1.1, 0.9),
        "color": "#d7a36f",
        "phase": 0.35,
    },
    {
        "id": "npc-guardian-01",
        "archetype": "GUARDIAN",
        "x": 3.6,
        "z": 3.4,
        "scale": (1.0, 1.25, 1.0),
        "color": "#7fa9c4",
        "phase": 2.15,
    },
    {
        "id": "npc-critter-01",
        "archetype": "CRITTER",
        "x": 9.8,
        "z": 2.2,
        "scale": (0.72, 0.82, 0.72),
        "color": "#b6a6c8",
        "phase": 4.45,
    },
    {
        "id": "npc-fisher-01",
        "archetype": "WANDERER",
        "x": 1.4,
        "z": 12.8,
        "scale": (0.92, 1.08, 0.92),
        "color": "#c8a97e",
        "phase": 1.15,
    },
    {
        "id": "npc-hut-01",
        "archetype": "WANDERER",
        "x": 7.2,
        "z": 9.0,
        "scale": (0.88, 1.04, 0.88),
        "color": "#e2c094",
        "phase": 2.85,
    },
    {
        "id": "npc-hut-02",
        "archetype": "WANDERER",
        "x": -1.2,
        "z": -7.2,
        "scale": (0.9, 1.06, 0.9),
        "color": "#d9b88a",
        "phase": 3.55,
    },
)


def spawns_from_content(content: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Merge optional authored physical NPC spawns over the starter pool."""
    result = [dict(row) for row in DEFAULT_SPAWNS]
    source = content.get("npc_spawns") if isinstance(content, dict) else None
    if isinstance(source, list):
        by_id = {
            str(row.get("id")): row
            for row in result
            if isinstance(row, dict) and row.get("id")
        }
        for raw in source[:MAX_NPCS]:
            if not isinstance(raw, dict):
                continue
            identity = str(raw.get("id", "")).strip()[:48]
            if not identity:
                continue
            base = dict(by_id.get(identity, {}))
            base.update(dict(raw))
            base["id"] = identity
            base["archetype"] = normalize_archetype(base.get("archetype"))
            base["x"] = _clamp(base.get("x"), -1000000.0, 1000000.0)
            base["z"] = _clamp(base.get("z"), -1000000.0, 1000000.0)
            raw_scale = base.get("scale", (1.0, 1.0, 1.0))
            if not isinstance(raw_scale, (list, tuple)) or len(raw_scale) < 3:
                raw_scale = (1.0, 1.0, 1.0)
            base["scale"] = tuple(
                _clamp(value, 0.35, 3.0, 1.0) for value in raw_scale[:3]
            )
            base["color"] = str(base.get("color", "#d7a36f"))[:16]
            base["phase"] = _safe_float(base.get("phase"))
            by_id[identity] = base
        result = [by_id[key] for key in by_id]
    return result[:MAX_NPCS]


class NpcDecision(NamedTuple):
    """Allocation-light result of one bounded NPC decision pass."""

    state: str
    target_x: float
    target_z: float
    desired_speed: float
    perception_radius: float
    target_distance: float
    reason: str
    stimulus: str
    line_of_sight: bool
    memory_age: float


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _safe_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"false", "0", "no", "off", ""}:
            return False
        if lowered in {"true", "1", "yes", "on"}:
            return True
    return bool(value) if value is not None else default


def _clamp(value: Any, low: float, high: float, default: float = 0.0) -> float:
    return max(low, min(high, _safe_float(value, default)))


def normalize_archetype(value: Any, default: str = "WANDERER") -> str:
    candidate = str(value or default).upper()
    if candidate in ARCHETYPES:
        return candidate
    fallback = str(default or "WANDERER").upper()
    return fallback if fallback in ARCHETYPES else "WANDERER"


def profile_for(archetype: Any) -> dict[str, float]:
    """Return a copy so callers cannot mutate the shared balance table."""
    return dict(PROFILES[normalize_archetype(archetype)])


def _bounded_target(
    home_x: float,
    home_z: float,
    target_x: float,
    target_z: float,
    radius: float,
) -> tuple[float, float]:
    safe_radius = _clamp(radius, 0.0, 64.0)
    dx = target_x - home_x
    dz = target_z - home_z
    distance = math.hypot(dx, dz)
    if distance <= safe_radius or distance <= 0.0001:
        return target_x, target_z
    scale = safe_radius / distance
    return home_x + dx * scale, home_z + dz * scale


def _wander_target(
    home_x: float,
    home_z: float,
    phase: float,
    sim_time: float,
    radius: float,
) -> tuple[float, float]:
    """Produce a smooth, replay-stable target without a mutable RNG."""
    safe_time = _safe_float(sim_time)
    safe_phase = _safe_float(phase)
    safe_radius = _clamp(radius, 0.0, 64.0)
    angle = safe_time * 0.42 + safe_phase
    return (
        home_x + math.sin(angle) * safe_radius * 0.58,
        home_z + math.cos(angle * 0.83) * safe_radius * 0.58,
    )


def decide(
    archetype: Any,
    state: Any,
    sim_time: Any,
    x: Any,
    z: Any,
    home_x: Any,
    home_z: Any,
    player_x: Any,
    player_z: Any,
    phase: Any = 0.0,
    line_of_sight: Any = True,
    memory_age: Any = 999.0,
    last_seen_x: Any | None = None,
    last_seen_z: Any | None = None,
) -> NpcDecision:
    """Choose one cheap behavior target from bounded local information.

    ``state`` is accepted as part of the stable contract so a later content
    system can add hysteresis or scripted transitions without changing the
    host call shape.  The first pass derives the state from the current
    perception sample, keeping resets and replays deterministic.
    """
    kind = normalize_archetype(archetype)
    profile = PROFILES[kind]
    current_x = _safe_float(x)
    current_z = _safe_float(z)
    origin_x = _safe_float(home_x, current_x)
    origin_z = _safe_float(home_z, current_z)
    target_player_x = _safe_float(player_x)
    target_player_z = _safe_float(player_z)
    distance_x = target_player_x - current_x
    distance_z = target_player_z - current_z
    player_distance = math.hypot(distance_x, distance_z)
    sense_radius = profile["sense_radius"]
    stop_distance = profile["stop_distance"]
    safe_memory_age = _clamp(memory_age, 0.0, 60.0, 999.0)
    visible = _safe_bool(line_of_sight, True) and player_distance <= sense_radius
    remembered_x = _safe_float(last_seen_x, current_x)
    remembered_z = _safe_float(last_seen_z, current_z)
    memory_distance = math.hypot(
        remembered_x - current_x,
        remembered_z - current_z,
    )
    remembered = (
        not visible
        and safe_memory_age <= profile["memory_s"]
        and (last_seen_x is not None or last_seen_z is not None)
    )
    stimulus = "VISIBLE_PLAYER" if visible else (
        "LAST_SEEN_MEMORY" if remembered else "NONE"
    )
    effective_x = target_player_x if visible else remembered_x
    effective_z = target_player_z if visible else remembered_z
    effective_distance = player_distance if visible else memory_distance
    detected = visible or remembered
    next_state = "WANDER"
    target_x, target_z = _wander_target(
        origin_x,
        origin_z,
        _safe_float(phase),
        _safe_float(sim_time),
        profile["wander_radius"],
    )
    desired_speed = profile["speed"]
    reason = "PATROL_ORBIT"

    if (
        kind == "CRITTER"
        and visible
        and player_distance <= profile["danger_radius"]
    ):
        next_state = "FLEE"
        if player_distance > 0.0001:
            direction_x = -distance_x / player_distance
            direction_z = -distance_z / player_distance
        else:
            angle = _safe_float(phase)
            direction_x = math.cos(angle)
            direction_z = math.sin(angle)
        target_x, target_z = _bounded_target(
            origin_x,
            origin_z,
            current_x + direction_x * profile["wander_radius"],
            current_z + direction_z * profile["wander_radius"],
            profile["wander_radius"],
        )
        desired_speed = profile["run_speed"]
        reason = "DANGER_RADIUS"
    elif (
        kind == "GUARDIAN"
        and detected
    ):
        next_state = "ALERT"
        target_x, target_z = effective_x, effective_z
        desired_speed = (
            profile["speed"]
            if effective_distance > profile["alert_radius"]
            else 0.0
        )
        reason = "PLAYER_SENSE" if visible else "LAST_SEEN_MEMORY"
    elif (
        kind == "WANDERER"
        and detected
    ):
        next_state = "FOLLOW"
        target_x, target_z = effective_x, effective_z
        desired_speed = profile["speed"] if effective_distance > stop_distance else 0.0
        reason = "PLAYER_SENSE" if visible else "LAST_SEEN_MEMORY"
    elif math.hypot(target_x - current_x, target_z - current_z) < 0.35:
        desired_speed = 0.0
        reason = "WANDER_TARGET_REACHED"

    # Keep wandering/fleeing agents inside their local authored neighborhood;
    # the host's bounded tile route must still respect this content boundary.
    if next_state in {"WANDER", "FLEE"}:
        target_x, target_z = _bounded_target(
            origin_x,
            origin_z,
            target_x,
            target_z,
            profile["wander_radius"],
        )

    # Keep the accepted state in the public vocabulary even if a caller sends
    # an unknown previous state while a content document is being migrated.
    _ = str(state or "WANDER").upper() if state is not None else "WANDER"
    return NpcDecision(
        next_state,
        round(target_x, 5),
        round(target_z, 5),
        round(max(0.0, desired_speed), 5),
        round(sense_radius, 4),
        round(effective_distance, 5),
        reason,
        stimulus,
        visible,
        round(safe_memory_age, 4),
    )


def nearest_interaction_target(
    rows: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    player_x: Any,
    player_z: Any,
    radius: Any = INTERACTION_RADIUS_M,
) -> dict[str, Any] | None:
    """Select the nearest NPC inside a small, deterministic talk radius."""
    safe_radius = _clamp(radius, 0.5, 12.0, INTERACTION_RADIUS_M)
    px = _safe_float(player_x)
    pz = _safe_float(player_z)
    best: dict[str, Any] | None = None
    best_distance = float("inf")
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        if str(raw.get("state", "WANDER")).upper() == "DEAD":
            continue
        distance = math.hypot(
            _safe_float(raw.get("x")) - px,
            _safe_float(raw.get("z")) - pz,
        )
        if distance > safe_radius:
            continue
        identity = str(raw.get("id", ""))
        if distance > best_distance or (
            abs(distance - best_distance) <= 0.0001
            and best is not None
            and identity >= str(best.get("id", ""))
        ):
            continue
        best_distance = distance
        best = {
            "id": identity,
            "entity_id": str(raw.get("entity_id", "")),
            "archetype": normalize_archetype(raw.get("archetype")),
            "state": str(raw.get("state", "WANDER")).upper(),
            "distance_m": round(distance, 3),
        }
    return best


def interaction_response(archetype: Any, state: Any) -> str:
    """Return a small content hook until dialogue data is connected."""
    kind = normalize_archetype(archetype)
    behavior = str(state or "WANDER").upper()
    if kind == "GUARDIAN":
        return "The guardian marks your approach."
    if kind == "CRITTER":
        return "The critter watches you, then relaxes."
    if behavior == "FOLLOW":
        return "The wanderer recognizes your path."
    return "The wanderer offers a quiet greeting."


def build_interaction_view(
    target: dict[str, Any] | None,
    last_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a compact interaction affordance for the overlay."""
    selected = dict(target) if isinstance(target, dict) else None
    return {
        "available": selected is not None,
        "radius_m": INTERACTION_RADIUS_M,
        "target_id": str(selected.get("id", "")) if selected else "",
        "target_name": str(selected.get("name",selected.get("id",""))) if selected else "",
        "target_distance_m": (
            round(_safe_float(selected.get("distance_m")), 3)
            if selected
            else 0.0
        ),
        "target": selected or {},
        "last_result": dict(last_result) if isinstance(last_result, dict) else {},
    }


def build_view(
    rows: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    decision_hz: int = DECISION_HZ,
    interaction: dict[str, Any] | None = None,
    last_interaction: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a bounded, UI/network-safe NPC inspector view."""
    bounded_rows: list[dict[str, Any]] = []
    counts = {state_name: 0 for state_name in STATES}
    for row_index, raw in enumerate(rows):
        if row_index >= MAX_NPCS:
            break
        if not isinstance(raw, dict):
            continue
        row = dict(raw)
        state_name = str(row.get("state", "WANDER")).upper()
        if state_name not in STATES:
            state_name = "WANDER"
        row["state"] = state_name
        row["archetype"] = normalize_archetype(row.get("archetype"))
        counts[state_name] += 1
        bounded_rows.append(row)
    safe_hz = max(1, min(MOVEMENT_HZ, int(decision_hz)))
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "active": len(bounded_rows),
        "capacity": MAX_NPCS,
        "decision_hz": safe_hz,
        "movement_hz": MOVEMENT_HZ,
        "perception": PERCEPTION_MODEL,
        "navigation": NAVIGATION_STATUS,
        "states": counts,
        "interaction": build_interaction_view(interaction, last_interaction),
        "agents": bounded_rows,
    }
