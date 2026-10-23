"""Deterministic, low-cost third-person movement primitives.

The controller keeps the useful feel of a WoW/Jak-style avatar separate from
the host's entity pool. Ground movement resolves forward/back against
character-facing; A/D turn the character, E interacts, and Q fires/releases
the grapple. The host applies right-mouse facing before this movement step;
left-mouse orbit leaves character facing alone.
No physics engine or per-frame object graph is needed; the fixed-step host
owns integration and terrain contact.
"""

from __future__ import annotations

import math
from typing import Any

from backend import game_engine_world as world


SCHEMA = "gg.game-engine.controller.v1"
GROUND_SPEED_MPS = 7.0
SPRINT_SPEED_MPS = 10.5
GROUND_ACCEL_MPS2 = 34.0
GROUND_DECEL_MPS2 = 42.0
TURN_SPEED_RADPS = 2.8
# Full-hold single jump. A perfect second hop adds about the same height.
# 12.20 m/s is the speed whose 80%-timed double jump meets the scaled roof.
JUMP_SPEED_MPS = 12.20
GRAVITY_MPS2 = 22.0
COYOTE_TIME_S = 0.11
JUMP_BUFFER_TIME_S = 0.13
JUMP_HOLD_TIME_S = 0.16
JUMP_HOLD_GRAVITY_SCALE = 0.52
# Quality 1 is the apex. The extra scale makes up for the one-frame
# release before the second press, so a perfect hop still adds a full
# first-jump height. The power then brings quality 0.8 down to about
# 80% of that added height (hut roof / palm crown).
DOUBLE_JUMP_PERFECT_SCALE = 1.145
DOUBLE_JUMP_QUALITY_POWER = 1.70


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _clamp(value: Any, low: float, high: float, default: float = 0.0) -> float:
    return max(low, min(high, _finite(value, default)))


def camera_basis(yaw_degrees: Any = 0.0) -> dict[str, tuple[float, float]]:
    """Return forward/right axes for the scene's yaw convention.

    The authored Blender characters face +Z at yaw zero.  Ground movement,
    swimming and flight all use that same forward axis so the rendered mesh
    never walks backwards relative to its facing.
    """
    radians = math.radians(_finite(yaw_degrees))
    sine = math.sin(radians)
    cosine = math.cos(radians)
    return {
        "forward": (sine, cosine),
        "right": (-cosine, sine),
    }


def character_basis(yaw_radians: Any = 0.0) -> dict[str, tuple[float, float]]:
    """Return the character-facing axes used by ground locomotion."""
    radians = _finite(yaw_radians)
    sine = math.sin(radians)
    cosine = math.cos(radians)
    return {
        "forward": (sine, cosine),
        "right": (-cosine, sine),
    }


def movement_direction(
    camera_yaw: Any,
    forward: Any,
    strafe: Any,
) -> tuple[float, float, float]:
    """Resolve normalized facing-relative input to world X/Z direction.

    The historical parameter name is kept for callers that already use this
    small helper.  It now represents character yaw for ground input.
    """
    axes = character_basis(math.radians(_finite(camera_yaw)))
    forward_input = _clamp(forward, -1.0, 1.0)
    strafe_input = _clamp(strafe, -1.0, 1.0)
    x = (
        axes["forward"][0] * forward_input
        + axes["right"][0] * strafe_input
    )
    z = (
        axes["forward"][1] * forward_input
        + axes["right"][1] * strafe_input
    )
    length = math.hypot(x, z)
    if length <= 0.0001:
        return 0.0, 0.0, 0.0
    # Diagonal input must not be faster than cardinal input.
    return x / length, z / length, min(1.0, length)


def _approach(current: float, target: float, maximum_delta: float) -> float:
    delta = target - current
    if abs(delta) <= maximum_delta:
        return target
    return current + math.copysign(maximum_delta, delta)


def ground_step(
    *,
    camera_yaw: Any = 0.0,
    character_yaw: Any | None = None,
    forward: Any = 0.0,
    strafe: Any = 0.0,
    turn_input: Any | None = None,
    legacy_steer: Any = 0.0,
    boost: Any = False,
    current_vx: Any = 0.0,
    current_vz: Any = 0.0,
    current_yaw: Any = 0.0,
    dt: Any = 1.0 / 60.0,
) -> dict[str, Any]:
    """Advance horizontal WoW-style control by one fixed step.

    ``turn_input`` is an in-place yaw axis: negative is left, positive is
    right.  ``legacy_steer`` remains as a compatibility alias for old input
    rows, but it is a turn axis now.  Strafe is never inferred from turn, so
    A/D can rotate without making the player slide sideways.
    """
    safe_dt = _clamp(dt, 0.0, 0.25, 1.0 / 60.0)
    safe_forward = _clamp(forward, -1.0, 1.0)
    safe_strafe = _clamp(strafe, -1.0, 1.0)
    safe_turn = _clamp(
        legacy_steer if turn_input is None else turn_input,
        -1.0,
        1.0,
    )
    safe_character_yaw = (
        math.radians(_finite(camera_yaw))
        if character_yaw is None
        else _finite(character_yaw)
    )
    direction_x, direction_z, input_strength = movement_direction(
        math.degrees(safe_character_yaw),
        safe_forward,
        safe_strafe,
    )
    maximum_speed = SPRINT_SPEED_MPS if bool(boost) else GROUND_SPEED_MPS
    target_vx = direction_x * maximum_speed * input_strength
    target_vz = direction_z * maximum_speed * input_strength
    current_x = _finite(current_vx)
    current_z = _finite(current_vz)
    accelerating = input_strength > 0.0001
    response = GROUND_ACCEL_MPS2 if accelerating else GROUND_DECEL_MPS2
    delta = response * safe_dt
    next_vx = _approach(current_x, target_vx, delta)
    next_vz = _approach(current_z, target_vz, delta)
    next_yaw = _finite(current_yaw)
    next_yaw += safe_turn * TURN_SPEED_RADPS * safe_dt
    next_yaw = (next_yaw + math.pi) % math.tau - math.pi
    next_speed = math.hypot(next_vx, next_vz)
    return {
        "schema": SCHEMA,
        "vx": next_vx,
        "vz": next_vz,
        "yaw": next_yaw,
        "speed": next_speed,
        "direction_x": direction_x,
        "direction_z": direction_z,
        "input_strength": input_strength,
        "turn_input": safe_turn,
        "turning": abs(safe_turn) > 0.0001,
        "ground_speed_mps": maximum_speed,
        "sprinting": bool(boost) and accelerating,
    }


def double_jump_quality(vertical_velocity: Any, jump_speed: Any) -> float:
    """1 at the apex, 0 when vertical speed is still a full hop."""
    speed = max(0.5, abs(_finite(jump_speed, JUMP_SPEED_MPS)))
    return max(0.0, 1.0 - min(1.0, abs(_finite(vertical_velocity)) / speed))


def double_jump_launch_speed(
    vertical_velocity: Any,
    jump_speed: Any,
    *,
    perfect_launch: Any = None,
) -> float:
    """Second hop. A perfect apex launch rises as far as the first hop.

    Earlier or later timing scales the launch down. Quality 0.8 is the
    "80% well timed" hop used to size hut roofs and palm crowns.
    """
    speed = _clamp(jump_speed, 0.5, 30.0, JUMP_SPEED_MPS)
    perfect = speed if perfect_launch is None else _clamp(
        perfect_launch, 0.5, 30.0, speed
    )
    quality = double_jump_quality(vertical_velocity, speed)
    fraction = max(0.34, quality ** DOUBLE_JUMP_QUALITY_POWER)
    return perfect * DOUBLE_JUMP_PERFECT_SCALE * fraction


def vertical_step(
    *,
    y: Any,
    vertical_velocity: Any,
    ground_y: Any,
    jump_pressed: Any,
    jump_was_pressed: Any,
    dt: Any,
    coyote_remaining: Any = 0.0,
    jump_buffer_remaining: Any = 0.0,
    jump_hold_time: Any = 0.0,
    jump_count: Any = 0,
    jump_speed: Any = JUMP_SPEED_MPS,
    double_jump_speed: Any = None,
    max_jumps: Any = 2,
    gravity: Any = GRAVITY_MPS2,
    hold_time: Any = JUMP_HOLD_TIME_S,
    hold_gravity_scale: Any = JUMP_HOLD_GRAVITY_SCALE,
) -> dict[str, Any]:
    """Advance a buffered variable-height jump, coyote jump and air jump."""
    safe_dt = _clamp(dt, 0.0, 0.25, 1.0 / 60.0)
    safe_ground = _finite(ground_y)
    safe_jump_speed = _clamp(jump_speed, 0.5, 30.0, JUMP_SPEED_MPS)
    safe_gravity = _clamp(gravity, 1.0, 80.0, GRAVITY_MPS2)
    safe_hold_time = _clamp(hold_time, 0.0, 1.0, JUMP_HOLD_TIME_S)
    safe_hold_gravity_scale = _clamp(
        hold_gravity_scale, 0.1, 1.0, JUMP_HOLD_GRAVITY_SCALE
    )
    next_y = _finite(y, safe_ground)
    next_velocity = _finite(vertical_velocity)
    grounded = next_y <= safe_ground + 0.025 and next_velocity <= 0.25
    safe_max_jumps = int(_clamp(max_jumps, 1.0, 3.0, 2.0))
    used_jumps = int(_clamp(jump_count, 0.0, float(safe_max_jumps), 0.0))
    if grounded:
        used_jumps = 0

    held = bool(jump_pressed)
    pressed_edge = held and not bool(jump_was_pressed)
    buffer_time = _clamp(
        jump_buffer_remaining,
        0.0,
        JUMP_BUFFER_TIME_S,
    )
    if pressed_edge:
        buffer_time = JUMP_BUFFER_TIME_S
    elif buffer_time > 0.0:
        buffer_time = max(0.0, buffer_time - safe_dt)

    coyote_time = _clamp(coyote_remaining, 0.0, COYOTE_TIME_S)
    if grounded:
        coyote_time = COYOTE_TIME_S
    first_jump = buffer_time > 0.0 and (grounded or coyote_time > 0.0)
    double_jumped = (
        buffer_time > 0.0
        and not first_jump
        and not grounded
        and used_jumps < safe_max_jumps
    )
    jumped = first_jump or double_jumped
    hold_time = _clamp(jump_hold_time, 0.0, JUMP_HOLD_TIME_S)
    if jumped:
        # The second hop uses the same launch speed as the first when it is
        # timed at the apex. Off-apex timing reduces that launch; it does not
        # keep the old shorter fixed impulse.
        reference_vy = next_velocity
        # A release on the previous frame cuts upward speed by 0.55. Judge
        # the second hop on the speed the player released from, otherwise an
        # early tap looks like an apex jump and gets the full extra height.
        if double_jumped and not bool(jump_was_pressed) and reference_vy > 0.0:
            reference_vy = reference_vy / 0.55
        next_velocity = (
            safe_jump_speed
            if first_jump
            else double_jump_launch_speed(
                reference_vy,
                safe_jump_speed,
                perfect_launch=double_jump_speed,
            )
        )
        grounded = False
        buffer_time = 0.0
        if first_jump:
            used_jumps = 1
            coyote_time = 0.0
        else:
            used_jumps += 1
        hold_time = 0.0
    elif not grounded:
        coyote_time = max(0.0, coyote_time - safe_dt)

    if held and next_velocity > 0.0 and hold_time < safe_hold_time:
        applied_gravity = safe_gravity * safe_hold_gravity_scale
        hold_time = min(safe_hold_time, hold_time + safe_dt)
    else:
        applied_gravity = safe_gravity
        if (
            bool(jump_was_pressed)
            and not held
            and next_velocity > 0.0
            and hold_time > 0.0
        ):
            next_velocity *= 0.55
        hold_time = (
            safe_hold_time
            if held and next_velocity > 0.0
            else 0.0
        )

    next_velocity -= applied_gravity * safe_dt
    next_y += next_velocity * safe_dt
    if next_y <= safe_ground:
        next_y = safe_ground
        next_velocity = 0.0
        grounded = True
        used_jumps = 0
        hold_time = 0.0
        coyote_time = COYOTE_TIME_S
    else:
        grounded = False
    return {
        "y": next_y,
        "vertical_velocity": next_velocity,
        "grounded": grounded,
        "jumped": jumped,
        "double_jumped": double_jumped,
        "jump_count": used_jumps,
        "jump_stage": used_jumps,
        "coyote_remaining": coyote_time,
        "jump_buffer_remaining": buffer_time,
        "jump_hold_time": hold_time,
    }


def grapple_constraint(
    *,
    position: tuple[Any, Any, Any],
    velocity: tuple[Any, Any, Any],
    anchor: tuple[Any, Any, Any],
    rope_length: Any,
    yaw: Any,
    forward: Any = 0.0,
    strafe: Any = 0.0,
    dt: Any = 1.0 / 60.0,
    pump_acceleration: Any = 7.0,
    ground_y: Any | None = None,
) -> dict[str, float]:
    """Apply a one-sided rope constraint, swing steering, and floor contact."""
    delta = _clamp(dt, 0.0, 0.1, 1.0 / 60.0)
    px, py, pz = (_finite(value) for value in position)
    vx, vy, vz = (_finite(value) for value in velocity)
    ax, ay, az = (_finite(value) for value in anchor)
    length = _clamp(rope_length, 0.25, 32.0, 9.0)

    # Apply modest player steering. The radial part is removed below while
    # the rope is taut, so movement input pumps the swing instead of stretching
    # the line.
    basis = character_basis(_finite(yaw))
    forward_input = _clamp(forward, -1.0, 1.0)
    strafe_input = _clamp(strafe, -1.0, 1.0)
    fx = basis["forward"][0] * forward_input + basis["right"][0] * strafe_input
    fz = basis["forward"][1] * forward_input + basis["right"][1] * strafe_input
    strength = min(1.0, math.hypot(fx, fz))
    acceleration = _clamp(pump_acceleration, 0.0, 24.0, 7.0) * strength
    vx += fx * acceleration * delta
    vz += fz * acceleration * delta

    rx, ry, rz = px - ax, py - ay, pz - az
    distance = math.sqrt(rx * rx + ry * ry + rz * rz)
    if distance < 1e-5:
        rx, ry, rz = 0.0, -1.0, 0.0
        distance = 1.0
    nx, ny, nz = rx / distance, ry / distance, rz / distance

    taut = distance >= length
    if taut:
        # A rope can pull but cannot push. Project only when it is stretched;
        # if the player moves toward the anchor, the rope is allowed to sag.
        px = ax + nx * length
        py = ay + ny * length
        pz = az + nz * length

    floor = _finite(ground_y, -1.0e9) if ground_y is not None else None
    floor_contact = floor is not None and py < floor
    if floor_contact:
        py = max(floor, ay - length)
        vertical_offset = py - ay
        horizontal_radius = math.sqrt(
            max(0.0, length * length - vertical_offset * vertical_offset)
        )
        horizontal_x = px - ax
        horizontal_z = pz - az
        horizontal_distance = math.hypot(horizontal_x, horizontal_z)
        if horizontal_distance < 1.0e-5:
            horizontal_x, horizontal_z = character_basis(_finite(yaw))["forward"]
            horizontal_distance = math.hypot(horizontal_x, horizontal_z)
        px = ax + horizontal_x / horizontal_distance * horizontal_radius
        pz = az + horizontal_z / horizontal_distance * horizontal_radius

    if taut:
        # Preserve tangential momentum, which produces the pendulum swing.
        rx, ry, rz = px - ax, py - ay, pz - az
        constrained_distance = max(1.0e-5, math.sqrt(rx * rx + ry * ry + rz * rz))
        nx, ny, nz = rx / constrained_distance, ry / constrained_distance, rz / constrained_distance
        radial_speed = vx * nx + vy * ny + vz * nz
        vx -= radial_speed * nx
        vy -= radial_speed * ny
        vz -= radial_speed * nz
    if floor_contact:
        # At floor contact, keep the velocity tangent to the circle where the
        # rope sphere intersects the ground instead of allowing downward drift.
        vy = max(0.0, vy)
        radial_x, radial_z = px - ax, pz - az
        radial_horizontal = math.hypot(radial_x, radial_z)
        if radial_horizontal > 1.0e-5:
            nx, nz = radial_x / radial_horizontal, radial_z / radial_horizontal
            speed_into_rope = vx * nx + vz * nz
            vx -= speed_into_rope * nx
            vz -= speed_into_rope * nz
    return {"x": px, "y": py, "z": pz, "vx": vx, "vy": vy, "vz": vz}


def build_view(
    *,
    camera_yaw: Any,
    camera_pitch: Any,
    camera_distance: Any,
    grounded: Any,
    sprinting: Any,
) -> dict[str, Any]:
    """Expose controller facts without leaking implementation details."""
    return {
        "schema": SCHEMA,
        "model": "WOW_CLASSIC_THIRD_PERSON",
        "input_space": "CHARACTER_FORWARD_RIGHT",
        "movement_grammar": "W_S_MOVE_A_D_TURN_E_INTERACT_Q_GRAPPLE",
        "camera_control": "RIGHT_MOUSE_FACING_LEFT_ORBIT_SMART_FOLLOW",
        "grounded": bool(grounded),
        "sprinting": bool(sprinting),
        "camera": {
            "yaw": round(_finite(camera_yaw), 4),
            "pitch": round(_clamp(camera_pitch, -75.0, 75.0, -8.0), 4),
            "distance_m": round(
                _clamp(
                    camera_distance,
                    2.0,
                    160.0,
                    world.DEFAULT_CAMERA_DISTANCE_M,
                ),
                3,
            ),
        },
        "limits": {
            "walk_speed_mps": GROUND_SPEED_MPS,
            "sprint_speed_mps": SPRINT_SPEED_MPS,
            "jump_speed_mps": JUMP_SPEED_MPS,
            "gravity_mps2": GRAVITY_MPS2,
            "coyote_time_s": COYOTE_TIME_S,
            "jump_buffer_s": JUMP_BUFFER_TIME_S,
            "variable_jump_hold_s": JUMP_HOLD_TIME_S,
        },
    }
