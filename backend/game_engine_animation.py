"""Fixed-step locomotion state shared by simulation and Blender-authored rigs."""

from __future__ import annotations

import math
from typing import Any


SCHEMA = "gg.game-engine.animation.v1"
MOTION_STATES = (
    "IDLE", "WALK", "SPRINT", "AIR", "DOUBLE_JUMP", "GRAPPLE",
    "SWIM", "FLY", "HOVERBOARD", "HOVERBOARD_AIR", "BOAT", "SIT", "SLEEP", "KNEEL",
)
WALK_SPEED_MPS = 7.0
SPRINT_SPEED_MPS = 10.5
MAX_SPEED_MPS = 64.0
DOUBLE_JUMP_ANIMATION_SECONDS = 0.64

# The authored GLB action bank is shared by every Codex character and crowd
# LOD.  Keep it within the engine's bounded GLTF animation budget.
ANIMATION_FPS = 24
CLIP_FRAMES = {
    # Locomotion and traversal.
    "Idle": 36, "Walk": 24, "Sprint": 18, "Air": 18,
    "DoubleJump": 16, "Grapple": 24, "Swim": 24, "Fly": 24,
    "Board": 24, "BoardAir": 18, "Skiff": 24,
    "TwoHandIdle": 36, "TwoHandWalk": 24, "TwoHandSprint": 18,
    # Combat reactions and footwork.
    "Land": 18, "DodgeLeft": 20, "DodgeRight": 20, "Parry": 18,
    "HitReact": 20, "Death": 32,
    # Unarmed and broad weapon families.
    "UnarmedAttack": 22, "OneHandSlash": 24, "OneHandThrust": 22,
    "OneHandOverhead": 24, "TwoHandSlash": 26,
    "TwoHandOverhead": 26, "TwoHandThrust": 22,
    "ScytheSweep": 28, "FlailSwing": 30, "WhipCrack": 24,
    "BoomerangThrow": 20, "ShieldBash": 20, "SpearThrust": 22,
    # Ranged and spell casting.
    "PistolFire": 12, "DualPistolFire": 12, "RifleFire": 14,
    "ShotgunFire": 20, "BowShot": 20, "Reload": 32,
    "WandCast": 24, "StaffCast": 30,
    # Physical world interactions, shared by player and independent NPCs.
    "Pickup": 28, "OpenChest": 32, "Gather": 36, "HarvestFruit": 36,
    "Mine": 36, "ChopWood": 34, "Craft": 40, "Cook": 40,
    "Enchant": 40, "Talk": 42, "Eat": 36, "Drink": 32,
    "FishCast": 40, "NetCatch": 32, "Pet": 32, "Milk": 40, "Shear": 36,
}
WORLD_INTERACTION_CLIPS = frozenset({
    "Pickup", "OpenChest", "Gather", "HarvestFruit", "Mine", "ChopWood",
    "Craft", "Cook", "Enchant", "Talk", "Eat", "Drink", "FishCast",
    "NetCatch", "Pet", "Milk", "Shear",
})
ONE_SHOT_CLIPS = frozenset(
    name for name in CLIP_FRAMES
    if name not in {"Idle", "Walk", "Sprint", "Air", "Grapple", "Swim", "Fly", "Board", "Skiff",
                   "TwoHandIdle", "TwoHandWalk", "TwoHandSprint"}
)
ACTION_CLIP_SECONDS = {
    name: frames / ANIMATION_FPS
    for name, frames in CLIP_FRAMES.items()
    if name in ONE_SHOT_CLIPS
}


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _clamp(value: Any, low: float, high: float, default: float = 0.0) -> float:
    return max(low, min(high, _finite(value, default)))


def motion_state(
    horizontal_speed: Any,
    *,
    grounded: Any = True,
    sprinting: Any = False,
) -> str:
    """Classify motion with stable thresholds shared by UI and future assets."""
    if not bool(grounded):
        return "AIR"
    speed = max(0.0, _clamp(horizontal_speed, 0.0, MAX_SPEED_MPS))
    if speed <= 0.08:
        return "IDLE"
    if bool(sprinting) or speed >= WALK_SPEED_MPS * 1.12:
        return "SPRINT"
    return "WALK"


def build_pose(
    *,
    sim_time: Any,
    horizontal_speed: Any,
    grounded: Any = True,
    sprinting: Any = False,
    vertical_velocity: Any = 0.0,
    travelled_distance_m: Any = None,
    movement_mode: Any = "GROUND",
    vehicle_kind: Any = "NONE",
    jump_stage: Any = 0,
    double_jump_remaining_s: Any = 0.0,
    grappling: Any = False,
    stand_state: Any = 0,
) -> dict[str, Any]:
    """Return one bounded, render-friendly pose driven only by fixed-step data.

    ``bob_m`` and the small rotations are root-level accents for the current
    combined body mesh.  ``phase`` is intentionally exposed so a later
    skinned importer can drive feet, arms and additive animation from the same
    deterministic clock.
    """
    safe_time = max(0.0, _finite(sim_time))
    safe_speed = max(0.0, _clamp(horizontal_speed, 0.0, MAX_SPEED_MPS))
    safe_vertical = _clamp(vertical_velocity, -64.0, 64.0)
    mode = str(movement_mode or "GROUND").upper()
    vehicle = str(vehicle_kind or "NONE").upper()
    air_jump_stage = int(_clamp(jump_stage, 0.0, 2.0))
    # Swimming is in contact with water rather than the terrain, but should
    # still use one of the character's authored locomotion clips.  Reuse the
    # existing walk/sprint clips and add a small swim bob/lean below instead
    # of incorrectly selecting the airborne pose while the character floats.
    animation_grounded = bool(grounded) or mode == "SWIM" or vehicle == "BOAT"
    animation_speed = 0.0 if vehicle == "BOAT" else safe_speed
    state = motion_state(
        animation_speed,
        grounded=animation_grounded,
        sprinting=sprinting and vehicle != "BOAT",
    )

    if state == "AIR":
        cadence_hz = 0.0
        phase = 0.0
        bob_m = 0.0
        # A modest pitch makes a jump readable, while the clamp prevents a
        # malformed velocity from turning the avatar upside down.
        lean_deg = _clamp(-safe_vertical * 0.32, -8.0, 8.0)
        sway_deg = 0.0
        stride = 0.0
        squash = 0.0
    elif state == "IDLE":
        cadence_hz = 0.67
        phase = math.fmod(safe_time * cadence_hz * math.tau, math.tau)
        bob_m = 0.012 * math.sin(phase)
        lean_deg = 0.0
        sway_deg = 0.65 * math.sin(phase * 0.5)
        stride = 0.0
        squash = 0.004 * math.sin(phase * 2.0)
    else:
        sprint = state == "SPRINT"
        speed_ratio = _clamp(
            safe_speed / (SPRINT_SPEED_MPS if sprint else WALK_SPEED_MPS),
            0.0,
            1.0,
        )
        cadence_hz = (1.65 if not sprint else 2.15) + 0.35 * speed_ratio
        stride_length = 3.05 if sprint else 2.15
        if travelled_distance_m is None:
            phase = math.fmod(safe_time * cadence_hz * math.tau, math.tau)
        else:
            travelled = max(0.0, _finite(travelled_distance_m))
            phase = math.fmod(travelled * math.tau / stride_length, math.tau)
            cadence_hz = safe_speed / stride_length
        stride = math.sin(phase)
        # Keep the feet near the ground: the offset is positive and bounded,
        # unlike a full sine wave that would sink the mesh below the patch.
        bob_m = (0.010 if sprint else 0.006) + (
            0.026 if sprint else 0.018
        ) * abs(stride)
        lean_deg = -5.0 * speed_ratio if sprint else -2.5 * speed_ratio
        sway_deg = (2.2 if sprint else 1.6) * stride
        squash = (-0.014 if sprint else -0.008) * abs(stride)

    double_jump_active = (
        state == "AIR"
        and air_jump_stage >= 2
        and _clamp(
            double_jump_remaining_s,
            0.0,
            DOUBLE_JUMP_ANIMATION_SECONDS,
        ) > 0.0
    )
    locomotion = (
        "DOUBLE_JUMP"
        if double_jump_active
        else ("AIR" if state == "AIR" else state)
    )
    if mode == "SWIM" and vehicle == "NONE":
        locomotion = "SWIM"
        cadence_hz = _clamp(0.75 + safe_speed / 5.0, 0.65, 1.45, 0.85)
        bob_m = 0.018 + 0.025 * math.sin(phase)
        lean_deg = _clamp(lean_deg - 10.0, -18.0, 8.0)
        sway_deg = _clamp(sway_deg * 0.65, -4.0, 4.0)
    elif mode == "FLY":
        locomotion = "FLY"
        cadence_hz = _clamp(0.72 + safe_speed / 15.0, 0.65, 1.4, 0.8)
    elif vehicle == "HOVERBOARD":
        locomotion = (
            "HOVERBOARD_AIR"
            if not bool(grounded)
            else "HOVERBOARD"
        )
        cadence_hz = 1.05 if bool(grounded) else 1.25
        lean_deg = _clamp(lean_deg - 4.0, -12.0, 8.0)
    elif vehicle == "BOAT":
        locomotion = "BOAT"
        cadence_hz = 0.78
    if bool(grappling) and mode == "GROUND" and vehicle == "NONE":
        locomotion = "GRAPPLE"
        cadence_hz = _clamp(1.0 + safe_speed / 7.0, 0.9, 1.65, 1.0)
    if locomotion == "DOUBLE_JUMP":
        cadence_hz = 1.0 / DOUBLE_JUMP_ANIMATION_SECONDS
    if stand_state in (1,2,3,8) and mode=='GROUND' and vehicle=='NONE' and bool(grounded) and safe_speed<.08:
        state=locomotion={1:'SIT',2:'SIT',3:'SLEEP',8:'KNEEL'}[stand_state]
        cadence_hz=0.;phase=0.;bob_m=0.;lean_deg=0.;sway_deg=0.;stride=0.;squash=0.

    return {
        "schema": SCHEMA,
        "state": state,
        "locomotion": locomotion,
        "movement_mode": mode,
        "vehicle": vehicle,
        "jump_stage": air_jump_stage,
        "phase": round(phase, 5),
        "cadence_hz": round(cadence_hz, 4),
        "speed_mps": round(safe_speed, 3),
        "bob_m": round(bob_m, 4),
        "lean_deg": round(lean_deg, 3),
        "sway_deg": round(sway_deg, 3),
        "stride": round(stride, 4),
        "squash": round(squash, 4),
        "source": "FIXED_STEP_ROOT_POSE",
    }
