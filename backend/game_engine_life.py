"""Bounded, deterministic ambient-life data for the GAME ENGINE.

The first living-world layer is intentionally smaller than a full AI
simulation. It gives render-only population proxies authored roles, day-cycle
schedules and a tiny stimulus contract. A later scheduler can promote
selected proxies into the existing physics/NPC pools without changing the row
shape consumed by QML.
"""

from __future__ import annotations

import copy
import math
from typing import Any, Callable, Iterable

from backend import game_engine_animation as animation_contract


SCHEMA = "gg.game-engine.life.v1"
VERSION = 1
DAY_LENGTH_S = 120.0
# Visual villagers are cheap deterministic proxies. Keep the nearby physical
# NPC/AI pool separate; selected proxies can still be promoted by the host.
MAX_PROXIES = 24
RENDER_RADIUS_M = 192.0
PLAYER_SENSE_RADIUS_M = 5.5
PHASES = ("DAWN", "DAY", "DUSK", "NIGHT")
ACTIVITIES = (
    "FISHING",
    "TRAVELING",
    "SCOUTING",
    "HAULING",
    "RESTING",
    "NOTICE_PLAYER",
    "TRADING",
    "GUARDING",
    "SOCIALIZING",
)


_CORE_SPAWNS: tuple[dict[str, Any], ...] = (
    {
        "id": "ambient-fisher-01",
        "role": "FISHER",
        "route": "SHORE_ORBIT",
        "activity_day": "FISHING",
        "x": -4.4,
        "z": -4.6,
        "radius": 1.8,
        "speed": 0.52,
        "phase": 0.4,
        "sense_radius": PLAYER_SENSE_RADIUS_M,
        "color": "#d7a36f",
        "scale": (0.82, 0.98, 0.82),
    },
    {
        "id": "ambient-traveler-01",
        "role": "TRAVELER",
        "route": "ROAD_LOOP",
        "activity_day": "TRAVELING",
        "x": 5.1,
        "z": -3.7,
        "radius": 2.2,
        "speed": 0.43,
        "phase": 1.8,
        "sense_radius": PLAYER_SENSE_RADIUS_M,
        "color": "#b6a6c8",
        "scale": (0.76, 0.92, 0.76),
    },
    {
        "id": "ambient-scout-01",
        "role": "SCOUT",
        "route": "RIDGE_SWEEP",
        "activity_day": "SCOUTING",
        "x": -6.1,
        "z": 5.0,
        "radius": 2.0,
        "speed": 0.61,
        "phase": 3.0,
        "sense_radius": PLAYER_SENSE_RADIUS_M,
        "color": "#7fa9c4",
        "scale": (0.88, 1.08, 0.88),
    },
    {
        "id": "ambient-carrier-01",
        "role": "CARRIER",
        "route": "CRATE_RUN",
        "activity_day": "HAULING",
        "x": 6.8,
        "z": 5.5,
        "radius": 1.5,
        "speed": 0.36,
        "phase": 4.6,
        "sense_radius": PLAYER_SENSE_RADIUS_M,
        "color": "#8db89a",
        "scale": (0.92, 1.02, 0.92),
    },
)

# One small island page should still feel inhabited. These homes sit on the
# authored walkable plateau and use short route radii so villagers animate in
# place instead of wandering through cliffs, huts, or the sea. Content packs
# can add four more rows while the shared budget stays at 24.
_VILLAGE_POSITIONS = (
    (-8.5, -8.0), (-1.0, -8.4), (7.8, -7.8), (-10.0, -3.0),
    (-3.0, -3.0), (4.6, -2.5), (9.2, 1.0), (-8.7, 2.3),
    (-3.5, 4.5), (3.1, 4.8), (8.3, 5.4), (-5.8, 8.1),
    (1.4, 9.0), (6.4, 9.2), (-1.5, 12.0), (10.0, 8.2),
)
_VILLAGE_ROLES = (
    ("VILLAGER", "TRAVELING", "#d7a36f"),
    ("FORAGER", "SCOUTING", "#8db89a"),
    ("FISHER", "FISHING", "#70a9c4"),
    ("CARRIER", "HAULING", "#c98989"),
    ("SCOUT", "SCOUTING", "#7fa9c4"),
    ("TRAVELER", "TRAVELING", "#b6a6c8"),
    ("VILLAGER", "TRAVELING", "#e0bc78"),
    ("FORAGER", "SCOUTING", "#91b27d"),
)
_VILLAGE_ROUTES = ("ROAD_LOOP", "RIDGE_SWEEP", "SHORE_ORBIT", "CRATE_RUN")
_VILLAGE_SCALES = (
    (0.82, 0.98, 0.82), (0.90, 1.08, 0.90),
    (0.76, 0.94, 0.76), (0.96, 1.12, 0.96),
)
_AMBIENT_VILLAGERS = tuple(
    {
        "id": f"ambient-islander-{index + 1:02d}",
        "role": _VILLAGE_ROLES[index % len(_VILLAGE_ROLES)][0],
        "route": _VILLAGE_ROUTES[index % len(_VILLAGE_ROUTES)],
        "activity_day": _VILLAGE_ROLES[index % len(_VILLAGE_ROLES)][1],
        "x": position[0],
        "z": position[1],
        "radius": 0.85 + (index % 4) * 0.22,
        "speed": 0.28 + (index % 5) * 0.045,
        "phase": 0.71 * index + 0.3,
        "sense_radius": PLAYER_SENSE_RADIUS_M,
        "color": _VILLAGE_ROLES[index % len(_VILLAGE_ROLES)][2],
        "scale": _VILLAGE_SCALES[index % len(_VILLAGE_SCALES)],
    }
    for index, position in enumerate(_VILLAGE_POSITIONS)
)
DEFAULT_SPAWNS: tuple[dict[str, Any], ...] = _CORE_SPAWNS + _AMBIENT_VILLAGERS


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _clamp(value: Any, low: float, high: float, default: float = 0.0) -> float:
    return max(low, min(high, _finite(value, default)))


def starter_spawns() -> list[dict[str, Any]]:
    """Return isolated authored spawn data for the starter island."""
    from backend.game_engine_settlement import resident_spawns
    return resident_spawns(list(DEFAULT_SPAWNS))


def spawns_from_content(content: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Accept bounded ambient authoring while preserving safe defaults."""
    source = content.get("ambient_life") if isinstance(content, dict) else None
    raw_rows = source if isinstance(source, list) else starter_spawns()
    defaults = {str(row["id"]): row for row in DEFAULT_SPAWNS}
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_rows[:MAX_PROXIES]:
        if not isinstance(raw, dict):
            continue
        identity = str(raw.get("id", "")).strip()[:64]
        if not identity or identity in seen:
            continue
        base = copy.deepcopy(defaults.get(identity, {}))
        base.update(copy.deepcopy(raw))
        base["id"] = identity
        base["role"] = str(base.get("role", "WANDERER")).upper()[:32]
        base["route"] = str(base.get("route", "ROAD_LOOP")).upper()[:32]
        base["activity_day"] = str(
            base.get("activity_day", "TRAVELING")
        ).upper()[:32]
        base["x"] = _clamp(base.get("x"), -128.0, 128.0)
        base["z"] = _clamp(base.get("z"), -128.0, 128.0)
        base["radius"] = _clamp(base.get("radius"), 0.5, 32.0, 1.5)
        base["speed"] = _clamp(base.get("speed"), 0.05, 4.0, 0.4)
        base["phase"] = _finite(base.get("phase"))
        base["sense_radius"] = _clamp(
            base.get("sense_radius"), 1.0, 16.0, PLAYER_SENSE_RADIUS_M
        )
        base["color"] = str(base.get("color", "#8db89a"))[:16]
        scale = base.get("scale", (0.8, 1.0, 0.8))
        if not isinstance(scale, (list, tuple)) or len(scale) < 3:
            scale = (0.8, 1.0, 0.8)
        base["scale"] = tuple(
            _clamp(component, 0.35, 1.8, 0.8) for component in scale[:3]
        )
        if isinstance(base.get("waypoints"), list):
            base["waypoints"] = [
                dict(x=_clamp(p.get("x"), -128, 128),z=_clamp(p.get("z"), -128, 128),
                     wait_s=_clamp(p.get("wait_s"),0,3600),
                     activity=str(p.get("activity","TRAVELING")).upper()[:32])
                for p in base["waypoints"][:32] if isinstance(p,dict)
            ]
            base["route_offset_s"] = _finite(base.get("route_offset_s"))
            prepare_routine(base)
        result.append(base)
        seen.add(identity)
    return result


def _local_route_points(spawn):
    """Migrate old home/radius content to a fixed out-and-back path.

    The same saved home and radius always yield the same endpoints. This is
    independent of the camera, day phase and whether the actor is rendered.
    """
    x, z = _finite(spawn.get('x')), _finite(spawn.get('z'))
    radius = _clamp(spawn.get('radius'), .5, 32, 1.5)
    return [dict(x=x,z=z,wait_s=20,activity='RESTING'),
            dict(x=x+radius,z=z,wait_s=12,activity=spawn.get('activity_day','TRAVELING'))]


def prepare_routine(spawn):
    """Compile every outward and return leg, including the last-to-first leg."""
    points=spawn.get("waypoints") or _local_route_points(spawn)
    mode=str(spawn.get('route_mode','LOOP')).upper()
    if mode not in ('LOOP','PING_PONG'):
        raise ValueError('resident route_mode must be LOOP or PING_PONG')
    order=list(range(len(points)))
    if mode=='PING_PONG':
        order+=list(range(len(points)-2,0,-1))
    segments=[];elapsed=0.;speed=_clamp(spawn.get('speed'),.05,4,.4)
    for step,i in enumerate(order):
        p=points[i]
        wait=max(0,_finite(p.get('wait_s')))
        if wait:
            segments.append(dict(start=elapsed,end=elapsed+wait,x=p['x'],z=p['z'],vx=0.,vz=0.,
                                 activity=p.get('activity','RESTING'),stop=i))
            elapsed+=wait
        q=points[order[(step+1)%len(order)]]
        dx,dz=q['x']-p['x'],q['z']-p['z'];length=math.hypot(dx,dz)
        if length>0:
            duration=length/speed
            segments.append(dict(start=elapsed,end=elapsed+duration,x=p['x'],z=p['z'],
                                 vx=dx/duration,vz=dz/duration,activity='TRAVELING',stop=i))
            elapsed+=duration
    spawn['_routine_segments']=segments;spawn['_routine_period_s']=elapsed


def routine_state(spawn,sim_time):
    """Analytic location: unloading never resets a clock or changes a route."""
    if '_routine_segments' not in spawn:prepare_routine(spawn)
    period=spawn['_routine_period_s']
    if not period:return dict(x=spawn['x'],z=spawn['z'],vx=0.,vz=0.,activity='RESTING',stop=0)
    clock=(max(0,sim_time)+_finite(spawn.get('route_offset_s')))%period
    for segment in spawn['_routine_segments']:
        if clock<segment['end']:
            elapsed=clock-segment['start']
            return dict(x=segment['x']+segment['vx']*elapsed,z=segment['z']+segment['vz']*elapsed,
                        vx=segment['vx'],vz=segment['vz'],activity=segment['activity'],stop=segment['stop'])
    raise AssertionError('routine clock outside compiled circuit')


def world_clock(sim_time: Any) -> dict[str, Any]:
    """Map fixed-step seconds to a compact deterministic world clock."""
    safe_time = max(0.0, _finite(sim_time))
    day_index = int(safe_time // DAY_LENGTH_S) + 1
    cycle_s = safe_time % DAY_LENGTH_S
    cycle = cycle_s / DAY_LENGTH_S
    if cycle < 0.15:
        phase = "DAWN"
    elif cycle < 0.68:
        phase = "DAY"
    elif cycle < 0.83:
        phase = "DUSK"
    else:
        phase = "NIGHT"
    hour = cycle * 24.0
    minute = int((hour - int(hour)) * 60.0)
    return {
        "day": day_index,
        "time_s": round(safe_time, 3),
        "cycle_s": round(cycle_s, 3),
        "hour": round(hour, 3),
        "label": f"{int(hour):02d}:{minute:02d}",
        "phase": phase,
        "day_length_s": DAY_LENGTH_S,
    }


def _height_at(
    terrain_height: Callable[[float, float], Any] | None,
    x: float,
    z: float,
) -> float:
    if terrain_height is None:
        return 0.0
    try:
        return _finite(terrain_height(x, z))
    except (TypeError, ValueError):
        return 0.0


def proxy_rows(
    spawns: Iterable[dict[str, Any]],
    sim_time: Any,
    *,
    player_x: Any = 0.0,
    player_z: Any = 0.0,
    terrain_height: Callable[[float, float], Any] | None = None,
    render_radius_m: float | None = None,
) -> list[dict[str, Any]]:
    """Build stable render rows and apply one bounded player stimulus pass."""
    safe_time = max(0.0, _finite(sim_time))
    clock = world_clock(safe_time)
    px = _finite(player_x)
    pz = _finite(player_z)
    rows: list[dict[str, Any]] = []
    for raw_spawn in list(spawns)[:MAX_PROXIES]:
        if not isinstance(raw_spawn, dict):
            continue
        spawn = raw_spawn
        role = str(spawn.get("role", "WANDERER"))[:32]
        routine=routine_state(spawn,safe_time)
        x,z,velocity_x,velocity_z=(routine[k] for k in ('x','z','vx','vz'))
        distance = math.hypot(x - px, z - pz)
        hidden=render_radius_m is not None and distance>render_radius_m
        sense_radius = _clamp(
            spawn.get("sense_radius"), 1.0, 16.0, PLAYER_SENSE_RADIUS_M
        )
        notices_player = distance <= sense_radius
        if notices_player and math.hypot(velocity_x,velocity_z)<.001:
            activity = "NOTICE_PLAYER"
            yaw = math.atan2(px - x, pz - z) if distance > 0.0001 else 0.0
            velocity_x = 0.0
            velocity_z = 0.0
        else:
            # A passing pedestrian keeps walking on their own route. Making
            # the pose idle while an analytic route still moves the root
            # causes skating whenever the player stands beside the road.
            activity=routine['activity']
            yaw=math.atan2(velocity_x,velocity_z) if math.hypot(velocity_x,velocity_z)>.001 else 0.
        horizontal_speed = math.hypot(velocity_x, velocity_z)
        pose = None if hidden else animation_contract.build_pose(
            sim_time=safe_time + _finite(spawn.get("phase")),
            horizontal_speed=horizontal_speed,
            grounded=True,
            sprinting=False,
            vertical_velocity=0.0,
        )
        scale = spawn.get("scale", (0.8, 1.0, 0.8))
        if not isinstance(scale, (list, tuple)) or len(scale) < 3:
            scale = (0.8, 1.0, 0.8)
        rows.append(
            {
                "id": str(spawn.get("id", "ambient-life")),
                "kind": "ACTOR",
                "x": round(x, 3),
                "y": 0.0 if hidden else round(_height_at(terrain_height, x, z) + 0.65, 3),
                "z": round(z, 3),
                "yaw": round(yaw, 4),
                "sx": round(_clamp(scale[0], 0.35, 1.8, 0.8), 3),
                "sy": round(_clamp(scale[1], 0.35, 1.8, 1.0), 3),
                "sz": round(_clamp(scale[2], 0.35, 1.8, 0.8), 3),
                "color": str(spawn.get("color", "#8db89a")),
                "speed": round(horizontal_speed, 3),
                "motion_state": str(pose.get("state", "IDLE")) if pose else "IDLE",
                "hidden": hidden,
                "animation": pose,
                "asset": None,
                "equipment": [],
                "item": None,
                "life": {
                    "role": role,
                    "activity": activity,
                    "stimulus": "PLAYER_NEAR" if notices_player else "NONE",
                    "attention": notices_player,
                    "schedule_phase": clock["phase"],
                    "home_x": round(_finite(spawn.get("x")), 3),
                    "home_z": round(_finite(spawn.get("z")), 3),
                    "distance_to_player_m": round(distance, 3),
                    "route": spawn.get('route','ROAD_LOOP'),
                    "route_stop": routine['stop'] if routine else None,
                },
            }
        )
    return rows


def build_view(rows: Iterable[dict[str, Any]], sim_time: Any) -> dict[str, Any]:
    """Return compact inspector/network data for the ambient population."""
    safe_rows = [row for row in rows if isinstance(row, dict)][:MAX_PROXIES]
    activities: dict[str, int] = {}
    stimuli: dict[str, int] = {}
    proxies: list[dict[str, Any]] = []
    for row in safe_rows:
        life = row.get("life", {}) if isinstance(row.get("life"), dict) else {}
        activity = str(life.get("activity", "TRAVELING"))
        stimulus = str(life.get("stimulus", "NONE"))
        activities[activity] = activities.get(activity, 0) + 1
        stimuli[stimulus] = stimuli.get(stimulus, 0) + 1
        proxies.append(
            {
                "id": str(row.get("id", "ambient-life")),
                "role": str(life.get("role", "WANDERER")),
                "activity": activity,
                "stimulus": stimulus,
                "attention": bool(life.get("attention", False)),
                "motion_state": str(row.get("motion_state", "IDLE")),
                "x": row.get("x", 0.0),
                "z": row.get("z", 0.0),
                "individual": copy.deepcopy(row.get("individual", {})),
            }
        )
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "clock": world_clock(sim_time),
        "population": len(safe_rows),
        "budget": MAX_PROXIES,
        "visible": len(safe_rows),
        "simulation": "RENDER_ONLY_DETERMINISTIC_SCHEDULES",
        "activities": dict(sorted(activities.items())),
        "stimuli": dict(sorted(stimuli.items())),
        "proxies": proxies,
    }
