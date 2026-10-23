"""Cinematic composition contracts for the low-cost diorama direction."""

from __future__ import annotations

from typing import Any

from backend import game_engine_world as world


SCHEMA = "gg.game-engine.cinematic.v1"
PRESETS = ("FIRST_ISLAND_DIORAMA", "OVER_SHOULDER_PLAY", "ORBIT_WORLD_SCALE")


def normalize_preset(value: Any, default: str = "FIRST_ISLAND_DIORAMA") -> str:
    preset = str(value or default).upper()
    return preset if preset in PRESETS else default


def build_view(
    preset: str,
    *,
    movement_mode: str = "GROUND",
    camera_distance: float = world.DEFAULT_CAMERA_DISTANCE_M,
) -> dict[str, Any]:
    name = normalize_preset(preset)
    if name == "ORBIT_WORLD_SCALE":
        camera_mode = "PLANET_ORBIT"
        focal_length = 58
        horizon = "HLOD_IMPOSTOR_POINT_DETAIL"
    elif name == "OVER_SHOULDER_PLAY":
        camera_mode = "OVER_SHOULDER_FOLLOW"
        focal_length = 48
        horizon = "CELL_HLOD"
    else:
        camera_mode = "OVER_SHOULDER_DIORAMA"
        focal_length = 52
        horizon = "BAKED_BACKDROP_PLUS_CELL_HLOD"
    return {
        "schema": SCHEMA,
        "preset": name,
        "camera": {
            "mode": camera_mode,
            "distance_m": round(max(4.0, min(160.0, float(camera_distance))), 2),
            "focal_length_mm": focal_length,
            "movement_mode": str(movement_mode),
            "perspective": "PERSPECTIVE_NEAR_FLAT_FAR_CURVED",
        },
        "composition": {
            "foreground": "PLAYABLE_INTERACTIVE_MESH",
            "midground": "CELL_MESH_INSTANCES_AND_BAKED_LIGHT",
            "horizon": horizon,
            "orbit": "SPHERICAL_WORLD_FRAME",
        },
        "lighting": {
            "key": "BAKED_SUNLIGHT",
            "fill": "LOW_COST_SKY_AMBIENT",
            "dynamic": "PLAYER_AND_ABILITY_CONTACT_ONLY",
        },
        "post": {
            "tone_mapping": "FILMIC_SOFT_CONTRAST",
            "depth_of_field": "CINEMATIC_OPTIONAL",
            "motion_blur": "OFF_BY_DEFAULT",
            "anti_aliasing": "RENDER_PROFILE_CONTROLLED",
        },
        "asset_rule": "COMPOSITION_AND_LIGHTING_CREATE_CINEMATIC_FEEL_BEFORE_POLYGON_COUNT",
    }
