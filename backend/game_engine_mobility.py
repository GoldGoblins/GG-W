"""Deterministic movement and shared water-surface contracts for the island.

Every function advances one fixed simulation step in metres. The game host
owns collision, state transitions and the 60 Hz clock; rendering samples the
same analytic waves as swimming and floating vehicles.
"""

from __future__ import annotations

import math
from typing import Any

from backend import game_engine_controller as controller


SCHEMA = "gg.game-engine.mobility.v1"
# Layered directional swells, the cheap stand-in for a Sea of Thieves FFT sea.
# Each row is direction x/z, amplitude m, wave number 1/m, angular rate rad/s,
# phase, and a sideways shift that stays 0. A non-zero shift draws the
# crest somewhere other than the point the body samples, so the picture
# and the rider stop being the same wave. Height at x,z is the only sea.
# Heights are large on purpose. A 0.6 m swell is invisible from the
# gameplay camera and leaves the hull bobbing on a flat sheet.
# The two long swells are the readable sea. The shorter pair stays long
# enough for the near disk (about 8 m between rings offshore) so the
# surface does not turn into faceted stripes. Ripples smaller than that
# live in the scrolling texture, not in the hull.
# World metres per repeat of the painted sea texture.
# qml/shaders/gg-sea.vert copies this table. A second formula there
# would put the picture on a different wave from the rider.
WATER_TEXTURE_TILE_M = 40.0
# How far down the bottom stays readable through the surface.
WATER_SIGHT_M = 5.5
WAVE_COMPONENTS = (
    (0.78, 0.63, 2.80, 0.045, 0.46, 0.20, 0.0),
    (-0.35, 0.94, 1.45, 0.085, 0.78, 1.40, 0.0),
    (0.96, -0.28, 0.36, 0.105, 1.05, 2.50, 0.0),
    (0.42, 0.91, 0.14, 0.145, 1.45, 0.80, 0.0),
)
TIDE_AMPLITUDE_M = 0.55
TIDE_PERIOD_S = 110.0
MAX_WAVE_HEIGHT_M = TIDE_AMPLITUDE_M + sum(row[2] for row in WAVE_COMPONENTS)
PLAYER_ROOT_HEIGHT_M = 0.65

SWIM_SPEED_MPS = 5.2
SWIM_SPRINT_MPS = 7.0
SWIM_ACCEL_MPS2 = 7.0
SWIM_BRAKE_MPS2 = 5.0
SWIM_VERTICAL_SPEED_MPS = 2.5
FLY_SPEED_MPS = 80.0
FLY_BOOST_SPEED_MPS = 180.0
FLY_ACCEL_MPS2 = 100.0
FLY_BRAKE_MPS2 = 240.0
FLY_VERTICAL_SPEED_MPS = 35.0
HOVER_SPEED_MPS = 16.0
HOVER_BOOST_SPEED_MPS = 22.0
HOVER_ACCEL_MPS2 = 19.0
HOVER_BRAKE_MPS2 = 12.0
HOVER_JUMP_SPEED_MPS = 8.4
HOVER_GRAVITY_MPS2 = 15.5
HOVER_HOLD_TIME_S = 0.28
HOVER_HOLD_GRAVITY_SCALE = 0.46
HOVER_RIDE_HEIGHT_M = 0.38
# Root height above the same water sample the mesh draws. The board sits
# on that surface; it is not a second, later wave.
HOVER_WATER_CLEARANCE_M = 0.78
BOAT_MAX_SPEED_MPS = 11.5
BOAT_REVERSE_SPEED_MPS = 3.2
BOAT_ACCEL_MPS2 = 3.4
BOAT_DRAG_MPS2 = 0.48
BOAT_BRAKE_MPS2 = 7.5
BOAT_TURN_RADPS = 1.55
# The procedural hull's origin sits above the waterline so the gunwale
# clears the swell. This is not the keel depth.
BOAT_HULL_DRAFT_M = 1.08
# Local mesh: length about 1.76, beam about 1.12, deck near y=-0.28.
# These scales make a skiff a person can stand in, about 7.4 m by 2.4 m.
SKIFF_SCALE = (2.14, 2.20, 4.20)
SKIFF_FLOOR_LOCAL_Y = -0.28
SKIFF_BOARD_RADIUS_M = 5.2
SKIFF_BOARD_HEIGHT_M = 2.8
MIN_SWIMMABLE_DEPTH_M = 0.22
SWIM_EXIT_DEPTH_M = 0.16
# Keel hangs roughly 0.6 m under the waterline at SKIFF_SCALE.
MIN_BOAT_DEPTH_M = 0.70
SKIFF_BOARD_DEPTH_M = 0.35
MAX_GROUND_GRADE = 0.78
MAX_STEP_UP_M = 0.48


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return number if math.isfinite(number) else default


def _clamp(value: Any, low: float, high: float, default: float = 0.0) -> float:
    return max(low, min(high, _finite(value, default)))


def _approach(current: float, target: float, amount: float) -> float:
    delta = target - current
    if abs(delta) <= amount:
        return target
    return current + math.copysign(amount, delta)


def _approach_vector(
    current_x: float,
    current_z: float,
    target_x: float,
    target_z: float,
    amount: float,
) -> tuple[float, float]:
    dx = target_x - current_x
    dz = target_z - current_z
    distance = math.hypot(dx, dz)
    if distance <= amount or distance <= 1e-8:
        return target_x, target_z
    scale = amount / distance
    return current_x + dx * scale, current_z + dz * scale


def _dt(value: Any) -> float:
    return _clamp(value, 0.0, 0.1, 1.0 / 60.0)


def _offshore_scale(x: float, z: float) -> float:
    """Full swells offshore, a small lap against the island."""
    distance = math.hypot(x, z)
    blend = max(0.0, min(1.0, (distance - 48.0) / 100.0))
    blend = blend * blend * (3.0 - 2.0 * blend)
    return 0.15 + 0.85 * blend


def _surface_components(
    x: Any,
    z: Any,
    time_s: Any,
    *,
    sea_level_m: Any = 0.0,
) -> tuple[float, float, float, float]:
    px = _finite(x)
    pz = _finite(z)
    time_value = _finite(time_s)
    sea_level = _finite(sea_level_m)
    scale = _offshore_scale(px, pz)
    tide_rate = math.tau / TIDE_PERIOD_S
    tide_phase = time_value * tide_rate
    tide = TIDE_AMPLITUDE_M * scale
    height = sea_level + tide * math.sin(tide_phase)
    dhdt = tide * tide_rate * math.cos(tide_phase)
    dhdx = 0.0
    dhdz = 0.0
    crest_sum = 0.0
    crest_weight = 0.0
    offset_x = 0.0
    offset_z = 0.0
    for component in WAVE_COMPONENTS:
        direction_x, direction_z, amplitude, wave_number, angular_rate, phase = component[:6]
        steepness = float(component[6]) if len(component) > 6 else 0.0
        amplitude *= scale
        phase_value = (
            wave_number * (direction_x * px + direction_z * pz)
            - angular_rate * time_value
            + phase
        )
        sine = math.sin(phase_value)
        cosine = math.cos(phase_value)
        height += amplitude * sine
        derivative = amplitude * wave_number * cosine
        dhdx += derivative * direction_x
        dhdz += derivative * direction_z
        dhdt -= amplitude * angular_rate * cosine
        crest_sum += amplitude * max(0.0, sine)
        crest_weight += amplitude
        offset_x += steepness * amplitude * direction_x * cosine
        offset_z += steepness * amplitude * direction_z * cosine
    crest = crest_sum / crest_weight if crest_weight > 1e-6 else 0.0
    return height, dhdx, dhdz, dhdt, max(0.0, min(1.0, crest)), offset_x, offset_z


def water_shade(
    crest: Any,
    steep: Any,
    shore: Any,
    horizon_fade: Any,
) -> tuple[float, float, float, float]:
    """Shade mask over the painted sea texture.

    The texture owns the color and the foam flecks. These channels only
    deepen a trough and ease the far water toward the sky before the fog.
    They stay in 0..1 and are not posterized, so the surface does not break
    into stripes.
    """
    crest_value = _clamp(crest, 0.0, 1.0)
    steep_value = _clamp(steep, 0.0, 1.0)
    shore_value = _clamp(shore, 0.0, 1.0)
    fade = _clamp(horizon_fade, 0.0, 1.0)
    face = crest_value * crest_value * (3.0 - 2.0 * crest_value)
    # Keep this close to 1. A strong per-vertex mask draws the mesh grid.
    mask = 0.90 + 0.10 * face
    lift = max(shore_value, steep_value * 0.35)
    mask = min(1.0, mask + lift * (1.0 - mask))
    mask = mask + (1.0 - mask) * fade
    return (
        mask * (1.0 - 0.06 * fade),
        mask,
        min(1.0, mask * (1.0 + 0.08 * fade)),
        1.0,
    )


def water_clarity(depth_m: Any) -> float:
    """Opacity of the surface. Shallows stay see-through for a few metres.

    0 is clear, 1 is solid. Open sea retains enough transparency to reveal
    the world beneath the moving surface.
    """
    depth = _finite(depth_m)
    if depth <= 0.12:
        return 0.0
    span = max(0.0, min(1.0, (depth - 0.12) / WATER_SIGHT_M))
    span = span * span * (3.0 - 2.0 * span)
    return 0.28 + 0.44 * span


def surface_crest(x: Any, z: Any, time_s: Any) -> float:
    """0 in a trough, 1 when the layered swells are all near a crest."""
    _height, _dx, _dz, _dt, crest, _ox, _oz = _surface_components(
        x, z, time_s
    )
    return crest


def ride_tilt_degrees(yaw: Any, slope_x: Any, slope_z: Any) -> tuple[float, float]:
    """Pitch and roll, in degrees, that lay a +Z-facing board on this slope.

    The slope is world dh/dx, dh/dz. Qt's positive pitch lowers local +Z,
    and positive roll lowers local -X, which is the rider's right at yaw 0.
    Facing is applied first so the nose follows the wave ahead of the board,
    not the world Z axis.
    """
    yaw_value = _finite(yaw)
    forward_x = math.sin(yaw_value)
    forward_z = math.cos(yaw_value)
    right_x = -math.cos(yaw_value)
    right_z = math.sin(yaw_value)
    sx = _finite(slope_x)
    sz = _finite(slope_z)
    along = sx * forward_x + sz * forward_z
    across = sx * right_x + sz * right_z
    pitch = max(-16.0, min(16.0, -math.degrees(math.atan(along))))
    roll = max(-16.0, min(16.0, -math.degrees(math.atan(across))))
    return pitch, roll


def surface_horizontal_offset(
    x: Any,
    z: Any,
    time_s: Any,
) -> tuple[float, float]:
    """Gerstner sideways shift. Gameplay still samples height at rest x/z."""
    _height, _dx, _dz, _dt, _crest, offset_x, offset_z = _surface_components(
        x, z, time_s
    )
    return offset_x, offset_z


def surface_draw(
    x: Any,
    z: Any,
    time_s: Any,
    *,
    sea_level_m: Any = 0.0,
) -> tuple[float, float, float, float, float, float]:
    """Height, slopes, crest and sideways shift from one wave pass."""
    height, dhdx, dhdz, _dhdt, crest, offset_x, offset_z = _surface_components(
        x,
        z,
        time_s,
        sea_level_m=sea_level_m,
    )
    return height, dhdx, dhdz, crest, offset_x, offset_z


def sample_waves(
    points: list[tuple[float, float]],
    time_s: Any,
    *,
    sea_level_m: Any = 0.0,
) -> list[tuple[float, float, float, float]]:
    """Height, dhdx, dhdz and crest for many points.

    One loop so the visible mesh can follow the body without a Python call
    per vertex. The numbers are the same ones ``surface_sample`` uses.
    """
    time_value = _finite(time_s)
    sea_level = _finite(sea_level_m)
    tide_phase = time_value * (math.tau / TIDE_PERIOD_S)
    tide_sin = math.sin(tide_phase)
    sine = math.sin
    cosine = math.cos
    hypot = math.hypot
    waves = WAVE_COMPONENTS
    result: list[tuple[float, float, float, float]] = []
    for point in points:
        px = _finite(point[0])
        pz = _finite(point[1])
        distance = hypot(px, pz)
        blend = (distance - 48.0) / 100.0
        if blend < 0.0:
            blend = 0.0
        elif blend > 1.0:
            blend = 1.0
        blend = blend * blend * (3.0 - 2.0 * blend)
        scale = 0.15 + 0.85 * blend
        height = sea_level + TIDE_AMPLITUDE_M * scale * tide_sin
        dhdx = 0.0
        dhdz = 0.0
        crest_sum = 0.0
        crest_weight = 0.0
        for component in waves:
            direction_x, direction_z, amplitude, wave_number, angular_rate, phase = component[:6]
            amplitude *= scale
            phase_value = (
                wave_number * (direction_x * px + direction_z * pz)
                - angular_rate * time_value
                + phase
            )
            sine_value = sine(phase_value)
            cosine_value = cosine(phase_value)
            height += amplitude * sine_value
            derivative = amplitude * wave_number * cosine_value
            dhdx += derivative * direction_x
            dhdz += derivative * direction_z
            if sine_value > 0.0:
                crest_sum += amplitude * sine_value
            crest_weight += amplitude
        crest = crest_sum / crest_weight if crest_weight > 1.0e-6 else 0.0
        if crest < 0.0:
            crest = 0.0
        elif crest > 1.0:
            crest = 1.0
        result.append((height, dhdx, dhdz, crest))
    return result


def skiff_seat_offset(scale_y: Any) -> float:
    """Player-root height above the skiff origin, standing on the inner deck."""
    return _finite(scale_y, 1.0) * SKIFF_FLOOR_LOCAL_Y + PLAYER_ROOT_HEIGHT_M


def surface_height_slope(
    x: Any,
    z: Any,
    time_s: Any,
    *,
    sea_level_m: Any = 0.0,
) -> tuple[float, float, float]:
    """Return wave height and slopes without allocating the gameplay sample."""
    height, dhdx, dhdz, _dhdt, _crest, _ox, _oz = _surface_components(
        x,
        z,
        time_s,
        sea_level_m=sea_level_m,
    )
    return height, dhdx, dhdz


def surface_sample(
    x: Any,
    z: Any,
    time_s: Any,
    *,
    sea_level_m: Any = 0.0,
) -> dict[str, Any]:
    """Sample deterministic swell, tide, normal and surface current."""
    px = _finite(x)
    pz = _finite(z)
    time_value = _finite(time_s)
    sea_level = _finite(sea_level_m)
    height, dhdx, dhdz, dhdt, _crest, _ox, _oz = _surface_components(
        px,
        pz,
        time_value,
        sea_level_m=sea_level,
    )
    normal_length = math.sqrt(dhdx * dhdx + 1.0 + dhdz * dhdz)
    current_x = -0.12 * dhdx + 0.025 * math.cos(time_value * 0.31 + pz * 0.04)
    current_z = -0.12 * dhdz + 0.020 * math.sin(time_value * 0.27 + px * 0.05)
    return {
        "height_m": round(height, 6),
        "normal": {
            "x": round(-dhdx / normal_length, 6),
            "y": round(1.0 / normal_length, 6),
            "z": round(-dhdz / normal_length, 6),
        },
        "slope": {"x": round(dhdx, 6), "z": round(dhdz, 6)},
        "current_mps": {"x": round(current_x, 6), "z": round(current_z, 6)},
        "vertical_velocity_mps": round(dhdt, 6),
        "wave_height_m": round(height - sea_level, 6),
        "surface_model": "LAYERED_GERSTNER_SWELLS_PLUS_TIDE",
    }


def ground_surface_contact(
    *,
    current_x: Any,
    current_z: Any,
    next_x: Any,
    next_z: Any,
    current_ground_y: Any,
    next_ground_y: Any,
    player_y: Any = None,
    airborne: Any = False,
) -> dict[str, Any]:
    """Reject upward movement through terrain unless the jump clears its top."""
    cx = _finite(current_x)
    cz = _finite(current_z)
    nx = _finite(next_x)
    nz = _finite(next_z)
    current_y = _finite(current_ground_y)
    next_y = _finite(next_ground_y)
    distance = math.hypot(nx - cx, nz - cz)
    rise = next_y - current_y
    grade = rise / max(0.05, distance)
    upward_face = rise > MAX_STEP_UP_M or (rise > 0.06 and grade > MAX_GROUND_GRADE)
    clears_face = (
        bool(airborne)
        and player_y is not None
        and _finite(player_y) >= next_y + 0.02
    )
    blocked = rise > 0.0 and upward_face and not clears_face
    return {
        "allowed": not blocked,
        "rise_m": round(rise, 6),
        "grade": round(grade, 6),
        "reason": "UPWARD_FACE" if blocked else "CLEAR",
    }


def swim_step(
    *,
    x: Any,
    z: Any,
    yaw: Any,
    vx: Any,
    vy: Any,
    vz: Any,
    forward: Any,
    strafe: Any,
    turn: Any,
    vertical: Any,
    boost: Any,
    brake: Any,
    y: Any,
    terrain_y: Any,
    water_y: Any,
    water_depth: Any,
    current_x: Any = 0.0,
    current_z: Any = 0.0,
    submerged_volume: Any = False,
    dt: Any,
) -> dict[str, Any]:
    """Accelerate through the water, float naturally, and respect the seabed."""
    delta = _dt(dt)
    next_yaw = (_finite(yaw) + _clamp(turn, -1.0, 1.0) * 2.35 * delta + math.pi) % math.tau - math.pi
    direction_x, direction_z, strength = controller.movement_direction(
        math.degrees(next_yaw),
        _clamp(forward, -1.0, 1.0),
        _clamp(strafe, -1.0, 1.0),
    )
    target_speed = SWIM_SPRINT_MPS if bool(boost) else SWIM_SPEED_MPS
    target_vx = direction_x * target_speed * strength + _finite(current_x) * 0.45
    target_vz = direction_z * target_speed * strength + _finite(current_z) * 0.45
    response = SWIM_ACCEL_MPS2 if strength > 0.001 else SWIM_BRAKE_MPS2
    brake_value = _clamp(brake, 0.0, 1.0)
    if brake_value > 0.0:
        response = 10.0 + 8.0 * brake_value
        target_vx = _finite(current_x) * 0.20
        target_vz = _finite(current_z) * 0.20
    next_vx, next_vz = _approach_vector(
        _finite(vx), _finite(vz), target_vx, target_vz, response * delta
    )

    depth = max(0.0, _finite(water_depth))
    vertical_input = _clamp(vertical, -1.0, 1.0)
    surface_root_y = _finite(water_y) + 0.18
    bottom_root_y = _finite(terrain_y) + 0.42
    dive_range = max(0.0, min(1.5, depth - 0.35))
    target_y = surface_root_y + max(0.0, vertical_input) * 0.75
    if vertical_input < 0.0:
        target_y += vertical_input * dive_range
    target_y = max(bottom_root_y, min(_finite(water_y) + 0.95, target_y))
    buoyancy_acceleration = ((vertical_input*SWIM_VERTICAL_SPEED_MPS-_finite(vy))*4.6 if submerged_volume
                             else (target_y - _finite(y)) * 9.0 - _finite(vy) * 4.6)
    next_vy = _clamp(
        _finite(vy) + buoyancy_acceleration * delta,
        -SWIM_VERTICAL_SPEED_MPS,
        SWIM_VERTICAL_SPEED_MPS,
    )
    next_y = _finite(y) + next_vy * delta
    if next_y <= bottom_root_y:
        next_y = bottom_root_y
        next_vy = max(0.0, next_vy)
    if not submerged_volume and next_y >= _finite(water_y) + 0.95:
        next_y = _finite(water_y) + 0.95
        next_vy = min(0.0, next_vy)
    next_x = _finite(x) + next_vx * delta
    next_z = _finite(z) + next_vz * delta
    return {
        "x": next_x,
        "y": next_y,
        "z": next_z,
        "vx": next_vx,
        "vy": next_vy,
        "vz": next_vz,
        "yaw": next_yaw,
        "speed": math.sqrt(next_vx * next_vx + next_vy * next_vy + next_vz * next_vz),
        "grounded": False,
        "motion_state": "SWIM" if depth > MIN_SWIMMABLE_DEPTH_M else "WALK",
    }


def flight_step(
    *,
    x: Any,
    z: Any,
    yaw: Any,
    vx: Any,
    vy: Any,
    vz: Any,
    forward: Any,
    strafe: Any,
    turn: Any,
    vertical: Any,
    boost: Any,
    y: Any,
    terrain_y: Any,
    dt: Any,
) -> dict[str, Any]:
    """Responsive free flight with bounded inertia and a terrain floor."""
    delta = _dt(dt)
    next_yaw = (_finite(yaw) + _clamp(turn, -1.0, 1.0) * 2.45 * delta + math.pi) % math.tau - math.pi
    direction_x, direction_z, strength = controller.movement_direction(
        math.degrees(next_yaw),
        _clamp(forward, -1.0, 1.0),
        _clamp(strafe, -1.0, 1.0),
    )
    max_speed = FLY_BOOST_SPEED_MPS if bool(boost) else FLY_SPEED_MPS
    target_vx = direction_x * max_speed * strength
    target_vz = direction_z * max_speed * strength
    response = FLY_ACCEL_MPS2 if strength > 0.001 else FLY_BRAKE_MPS2
    next_vx, next_vz = _approach_vector(
        _finite(vx), _finite(vz), target_vx, target_vz, response * delta
    )
    target_vy = _clamp(vertical, -1.0, 1.0) * FLY_VERTICAL_SPEED_MPS
    next_vy = _approach(_finite(vy), target_vy, 18.0 * delta)
    floor_y = _finite(terrain_y) + PLAYER_ROOT_HEIGHT_M
    next_y = max(floor_y, _finite(y) + next_vy * delta)
    if next_y <= floor_y + 1e-5 and next_vy < 0.0:
        next_vy = 0.0
    next_x = _finite(x) + next_vx * delta
    next_z = _finite(z) + next_vz * delta
    speed = math.sqrt(next_vx * next_vx + next_vy * next_vy + next_vz * next_vz)
    return {
        "x": next_x,
        "y": next_y,
        "z": next_z,
        "vx": next_vx,
        "vy": next_vy,
        "vz": next_vz,
        "yaw": next_yaw,
        "speed": speed,
        "grounded": next_y <= floor_y + 1e-5,
        "motion_state": "FLY",
    }


def hoverboard_step(
    *,
    x: Any,
    z: Any,
    yaw: Any,
    vx: Any,
    vy: Any,
    vz: Any,
    forward: Any,
    strafe: Any,
    turn: Any,
    boost: Any,
    jump_pressed: Any,
    jump_was_pressed: Any,
    jump_buffer_remaining: Any,
    coyote_remaining: Any,
    jump_hold_time: Any,
    jump_count: Any = 0,
    grounded: Any,
    y: Any,
    ground_y: Any,
    dt: Any,
) -> dict[str, Any]:
    """Arcade board handling: precise ground turn, air steer and variable jump."""
    delta = _dt(dt)
    current_speed = math.hypot(_finite(vx), _finite(vz))
    turn_rate = 1.75 + min(0.95, current_speed / HOVER_SPEED_MPS * 0.95)
    next_yaw = (_finite(yaw) + _clamp(turn, -1.0, 1.0) * turn_rate * delta + math.pi) % math.tau - math.pi
    direction_x, direction_z, strength = controller.movement_direction(
        math.degrees(next_yaw),
        _clamp(forward, -1.0, 1.0),
        _clamp(strafe, -1.0, 1.0),
    )
    top_speed = HOVER_BOOST_SPEED_MPS if bool(boost) else HOVER_SPEED_MPS
    target_vx = direction_x * top_speed * strength
    target_vz = direction_z * top_speed * strength
    response = HOVER_ACCEL_MPS2 if strength > 0.001 else HOVER_BRAKE_MPS2
    next_vx, next_vz = _approach_vector(
        _finite(vx), _finite(vz), target_vx, target_vz, response * delta
    )
    jump = controller.vertical_step(
        y=y,
        vertical_velocity=vy,
        ground_y=ground_y,
        jump_pressed=jump_pressed,
        jump_was_pressed=jump_was_pressed,
        coyote_remaining=coyote_remaining,
        jump_buffer_remaining=jump_buffer_remaining,
        jump_hold_time=jump_hold_time,
        jump_count=jump_count,
        dt=delta,
        jump_speed=HOVER_JUMP_SPEED_MPS,
        gravity=HOVER_GRAVITY_MPS2,
        hold_time=HOVER_HOLD_TIME_S,
        hold_gravity_scale=HOVER_HOLD_GRAVITY_SCALE,
    )
    next_x = _finite(x) + next_vx * delta
    next_z = _finite(z) + next_vz * delta
    speed = math.sqrt(next_vx * next_vx + jump["vertical_velocity"] ** 2 + next_vz * next_vz)
    return {
        "x": next_x,
        "y": jump["y"],
        "z": next_z,
        "vx": next_vx,
        "vy": jump["vertical_velocity"],
        "vz": next_vz,
        "yaw": next_yaw,
        "speed": speed,
        "grounded": bool(jump["grounded"]),
        "jumped": bool(jump["jumped"]),
        "double_jumped": bool(jump["double_jumped"]),
        "jump_count": int(jump["jump_count"]),
        "jump_stage": int(jump["jump_stage"]),
        "jump_buffer_remaining": jump["jump_buffer_remaining"],
        "coyote_remaining": jump["coyote_remaining"],
        "jump_hold_time": jump["jump_hold_time"],
        "motion_state": "HOVERBOARD" if jump["grounded"] else "HOVERBOARD_AIR",
    }


def boat_step(
    *,
    x: Any,
    z: Any,
    yaw: Any,
    vx: Any,
    vz: Any,
    throttle: Any,
    turn: Any,
    brake: Any,
    current_x: Any,
    current_z: Any,
    dt: Any,
) -> dict[str, Any]:
    """Skiff acceleration and water steering with bounded lateral slip."""
    delta = _dt(dt)
    input_throttle = _clamp(throttle, -1.0, 1.0)
    old_yaw = _finite(yaw)
    forward_x = math.sin(old_yaw)
    forward_z = math.cos(old_yaw)
    side_x = math.cos(old_yaw)
    side_z = -math.sin(old_yaw)
    current_speed = _finite(vx) * forward_x + _finite(vz) * forward_z
    lateral_speed = _finite(vx) * side_x + _finite(vz) * side_z
    if input_throttle > 0.0:
        current_speed = min(BOAT_MAX_SPEED_MPS, current_speed + input_throttle * BOAT_ACCEL_MPS2 * delta)
    elif input_throttle < 0.0:
        current_speed = max(-BOAT_REVERSE_SPEED_MPS, current_speed + input_throttle * BOAT_ACCEL_MPS2 * delta)
    else:
        current_speed = _approach(current_speed, 0.0, BOAT_DRAG_MPS2 * delta)
    brake_value = _clamp(brake, 0.0, 1.0)
    if brake_value > 0.0:
        current_speed = _approach(current_speed, 0.0, BOAT_BRAKE_MPS2 * brake_value * delta)
    speed_factor = min(1.0, abs(current_speed) / 2.8)
    yaw_delta = _clamp(turn, -1.0, 1.0) * BOAT_TURN_RADPS * (0.20 + speed_factor * 0.80)
    yaw_delta *= -1.0 if current_speed < -0.1 else 1.0
    next_yaw = (_finite(yaw) + yaw_delta * delta + math.pi) % math.tau - math.pi
    # Throttle already integrated longitudinal acceleration above. Applying a
    # second low-pass to that same speed compounds two response filters and
    # makes a skiff barely move. Preserve a little lateral slip through turns,
    # while applying current directly so the boat retains readable momentum.
    lateral_speed *= math.exp(-1.65 * delta)
    next_vx = (
        math.sin(next_yaw) * current_speed
        + math.cos(next_yaw) * lateral_speed
        + _finite(current_x)
    )
    next_vz = (
        math.cos(next_yaw) * current_speed
        - math.sin(next_yaw) * lateral_speed
        + _finite(current_z)
    )
    next_x = _finite(x) + next_vx * delta
    next_z = _finite(z) + next_vz * delta
    speed = math.hypot(next_vx, next_vz)
    return {
        "x": next_x,
        "z": next_z,
        "yaw": next_yaw,
        "vx": next_vx,
        "vz": next_vz,
        "speed": speed,
        "pitch": round(min(9.0, max(-6.0, current_speed * 0.48)), 3),
        "roll": round(-_clamp(turn, -1.0, 1.0) * min(12.0, speed * 0.8), 3),
        "motion_state": "BOAT",
    }


def build_view(
    *,
    x: Any = 0.0,
    z: Any = 0.0,
    time_s: Any,
    movement_mode: Any,
    vehicle_kind: Any,
    water_depth: Any,
    speed: Any,
) -> dict[str, Any]:
    """Publish the compact mobility state used by the player HUD."""
    mode = str(movement_mode or "GROUND").upper()
    vehicle = str(vehicle_kind or "NONE").upper()
    if vehicle not in {"NONE", "HOVERBOARD", "BOAT"}:
        vehicle = "NONE"
    medium = "AIR" if mode == "FLY" else (
        "WATER" if mode == "SWIM" or vehicle == "BOAT" else "LAND"
    )
    water = surface_sample(x, z, time_s)
    return {
        "schema": SCHEMA,
        "medium": medium,
        "movement_mode": mode,
        "vehicle": vehicle,
        "speed_mps": round(max(0.0, _finite(speed)), 3),
        "water_depth_m": round(max(0.0, _finite(water_depth)), 3),
        "wave_height_m": water["wave_height_m"],
        "water_surface": water,
        "transitions": "CONTINUOUS_LAND_WATER_AIR_VEHICLE_CONTACT",
        "fixed_step_hz": 60,
    }
