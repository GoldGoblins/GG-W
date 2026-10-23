"""World-scale primitives shared by the local GAME ENGINE preview.

The preview deliberately keeps simulation coordinates small and easy to
inspect.  This module defines the seam we will use when the world grows from
one local scene into a seamless planet: stable cell keys, movement modes,
camera-relative rendering and a planet frame that can retain double-precision
global coordinates without sending those coordinates to the GPU directly.

It is data-only on purpose.  Rendering, networking, AI and the in-game editor
can all consume the same world view without importing a renderer or a server.
"""

from __future__ import annotations

import math
from typing import Any


SCHEMA = "gg.game-engine.world.v1"
WORLD_ID = "GG_FIRST_ISLAND_PREVIEW"
CHUNK_SIZE = 16.0
# Layout, terrain relief and architecture use separate scales. Expand distances
# and buildings around the origin while keeping the avatar, controls and sea
# level stable. WORLD_FEEL_SCALE remains the original vertical terrain scale.
WORLD_FEEL_SCALE = 1.85  # Preserve the authored terrain's vertical relief.
PLANET_LAYOUT_SCALE = 5.0
ISLAND_LAYOUT_SCALE = WORLD_FEEL_SCALE * PLANET_LAYOUT_SCALE
WORLD_PROP_SCALE = WORLD_FEEL_SCALE * 2.0
ISLAND_AUTHORED_HALF_EXTENT_M = 27.0
# Unscaled visual metres from a prop's ground contact to a palm crown. Hut
# roofs are matched to this before WORLD_PROP_SCALE is applied.
PALM_CROWN_CLEARANCE_M = 4.10
HOUSE_ROOF_CLEARANCE_M = PALM_CROWN_CLEARANCE_M


def island_half_extent_m() -> float:
    """Gameplay radius of the Blender island after the world-feel scale."""
    return ISLAND_AUTHORED_HALF_EXTENT_M * ISLAND_LAYOUT_SCALE


def roof_clearance_m() -> float:
    """Height of a hut roof and a palm crown above the ground they stand on."""
    return HOUSE_ROOF_CLEARANCE_M * WORLD_PROP_SCALE


# Keep simulation interest and visual coverage separate.  A radius of three is
# a 7x7 cell gameplay set; the renderer gets a larger deterministic HLOD set
# so the horizon does not collapse when the player moves.  Only the former is
# used for local physics, NPC navigation and network interest.
DEFAULT_INTEREST_RADIUS = 3
DEFAULT_RENDER_RADIUS = 10
DEFAULT_CAMERA_DISTANCE_M = 6.0
CAMERA_PIVOT_OFFSET_M = 0.8
DEFAULT_CAMERA_CLIP_NEAR_M = 0.1
DEFAULT_CAMERA_CLIP_FAR_M = 360.0

# This is a provisional game-world radius, not a claim about Earth scale.
# Local gameplay remains metre-like while the renderer can later reveal
# curvature as the camera climbs through the world-scale tiers.
DEFAULT_PLANET_RADIUS_METERS = 1_000_000.0

MOVEMENT_MODES = ("GROUND", "SWIM", "FLY")
LOD_TIERS = ("NEAR", "MID", "HORIZON", "ORBIT")


def normalize_movement_mode(value: Any, default: str = "GROUND") -> str:
    mode = str(value or default).upper()
    return mode if mode in MOVEMENT_MODES else default


def chunk_coord(value: float, chunk_size: float = CHUNK_SIZE) -> int:
    """Return a stable signed cell coordinate for a local position."""
    size = float(chunk_size)
    if not math.isfinite(size) or size <= 0.0:
        size = CHUNK_SIZE
    return math.floor(float(value) / size)


def cell_key(x: int, z: int, level: int = 0) -> str:
    """Return a version-stable key suitable for caches and network interest."""
    return f"{int(level)}:{int(x)}:{int(z)}"


def interest_cells(
    center_x: float,
    center_z: float,
    radius: int = DEFAULT_INTEREST_RADIUS,
) -> list[dict[str, int | float | str]]:
    """Return nearby cells in deterministic nearest-first order."""
    center_cell_x = chunk_coord(center_x)
    center_cell_z = chunk_coord(center_z)
    safe_radius = max(0, min(32, int(radius)))
    cells: list[tuple[int, int, int]] = []
    for dz in range(-safe_radius, safe_radius + 1):
        for dx in range(-safe_radius, safe_radius + 1):
            distance = dx * dx + dz * dz
            cells.append((distance, dz, dx))
    cells.sort(key=lambda row: (row[0], row[1], row[2]))
    return [
        {
            "x": center_cell_x + dx,
            "z": center_cell_z + dz,
            "level": 0,
            "key": cell_key(center_cell_x + dx, center_cell_z + dz),
            "projected_error_px": round(
                64.0 / max(1.0, float(_distance + 1) ** 2), 4
            ),
            "lod": lod_tier_for_screen_error(
                64.0 / max(1.0, float(_distance + 1) ** 2)
            ),
        }
        for _distance, dz, dx in cells
    ]


def lod_tier_for_screen_error(projected_error_px: float) -> str:
    """Choose an LOD from projected error, not a hard-coded world distance."""
    error = float(projected_error_px)
    if not math.isfinite(error):
        error = 0.0
    if error >= 48.0:
        return "NEAR"
    if error >= 8.0:
        return "MID"
    if error >= 1.0:
        return "HORIZON"
    return "ORBIT"


def camera_relative(
    position: tuple[float, float, float],
    camera: tuple[float, float, float],
) -> tuple[float, float, float]:
    """Convert a global/local position into a camera-relative render vector."""
    return (
        float(position[0]) - float(camera[0]),
        float(position[1]) - float(camera[1]),
        float(position[2]) - float(camera[2]),
    )


def orbit_camera_position(
    player_position: tuple[float, float, float],
    *,
    yaw: float = 0.0,
    pitch: float = -8.0,
    distance: float = DEFAULT_CAMERA_DISTANCE_M,
) -> tuple[float, float, float]:
    """Return a small local camera position for the over-shoulder frame."""
    x, y, z = (float(value) for value in player_position)
    safe_distance = max(0.0, float(distance))
    pitch_radians = math.radians(max(-75.0, min(75.0, float(pitch))))
    yaw_radians = math.radians(float(yaw))
    horizontal = safe_distance * math.cos(pitch_radians)
    return (
        x + math.sin(yaw_radians) * horizontal,
        y + CAMERA_PIVOT_OFFSET_M - math.sin(pitch_radians) * safe_distance,
        z + math.cos(yaw_radians) * horizontal,
    )


def local_to_planet(
    local_x: float,
    local_y: float,
    local_z: float,
    radius: float = DEFAULT_PLANET_RADIUS_METERS,
) -> tuple[float, float, float]:
    """Map a local tangent-frame position onto a spherical planet preview.

    The local frame starts at the positive X equator: local X is east, local
    Z is north and local Y is radial/up.  This is intentionally a small,
    deterministic helper rather than a complete geodesy implementation.  It
    gives the renderer a real planetary frame while physics can keep using
    cheap local coordinates inside one cell.
    """
    safe_radius = float(radius)
    if not math.isfinite(safe_radius) or safe_radius <= 0.0:
        safe_radius = DEFAULT_PLANET_RADIUS_METERS
    east = float(local_x)
    north = float(local_z)
    radial = safe_radius + float(local_y)
    if radial <= 0.0:
        radial = safe_radius
    horizontal_sq = east * east + north * north
    axis_sq = max(0.0, radial * radial - horizontal_sq)
    return (math.sqrt(axis_sq), east, north)


def build_world_view(
    player_position: tuple[float, float, float],
    *,
    movement_mode: str = "GROUND",
    camera_yaw: float = 0.0,
    camera_pitch: float = -8.0,
    camera_distance: float = DEFAULT_CAMERA_DISTANCE_M,
    interest_radius: int = DEFAULT_INTEREST_RADIUS,
    render_radius: int = DEFAULT_RENDER_RADIUS,
    planet_radius: float = DEFAULT_PLANET_RADIUS_METERS,
) -> dict[str, Any]:
    """Build the compact world contract consumed by UI and future systems."""
    x, y, z = (float(value) for value in player_position)
    mode = normalize_movement_mode(movement_mode)
    radius = float(planet_radius)
    if not math.isfinite(radius) or radius <= 0.0:
        radius = DEFAULT_PLANET_RADIUS_METERS
    safe_interest_radius = max(0, min(32, int(interest_radius)))
    safe_render_radius = max(
        safe_interest_radius,
        min(32, int(render_radius)),
    )
    cells = interest_cells(x, z, safe_interest_radius)
    render_cells = interest_cells(x, z, safe_render_radius)
    player_x = chunk_coord(x)
    player_z = chunk_coord(z)
    planet_position = local_to_planet(x, y, z, radius)
    camera_position = orbit_camera_position(
        (x, y, z),
        yaw=camera_yaw,
        pitch=camera_pitch,
        distance=camera_distance,
    )
    camera_planet_position = local_to_planet(*camera_position, radius)
    normal_length = math.sqrt(sum(value * value for value in planet_position)) or 1.0
    surface_normal = tuple(value / normal_length for value in planet_position)

    return {
        "schema": SCHEMA,
        "world_id": WORLD_ID,
        "coordinate_frame": {
            "global": "PLANET_DOUBLE_PRECISION",
            "local": "CHUNK_FLOAT32",
            "render": "CAMERA_RELATIVE_FLOAT32",
            "unit": "GAME_METERS",
        },
        "planet": {
            "model": "ELLIPSOID_PREVIEW",
            "radius_m": round(radius, 3),
            "global_position_m": {
                "x": round(planet_position[0], 3),
                "y": round(planet_position[1], 3),
                "z": round(planet_position[2], 3),
            },
            "surface_mode": "LOCAL_TANGENT" if mode != "FLY" else "PLANET_NORMAL",
            "curvature_visible_at": "WORLD_SCALE_CAMERA",
        },
        "feel": {
            "scale": WORLD_FEEL_SCALE,
            "layout_scale": ISLAND_LAYOUT_SCALE,
            "prop_scale": WORLD_PROP_SCALE,
            "planet_layout_scale": PLANET_LAYOUT_SCALE,
            "environment_revision": 2,
            "island_half_extent_m": round(island_half_extent_m(), 3),
            "roof_clearance_m": round(roof_clearance_m(), 3),
            "policy": "SEPARATE_LAYOUT_ARCHITECTURE_AND_TERRAIN_RELIEF",
        },
        "player_cell": {
            "x": player_x,
            "z": player_z,
            "key": cell_key(player_x, player_z),
        },
        "streaming": {
            "policy": "INVISIBLE_CELL_STREAMING",
            "visible_zones": False,
            "terrain_is_reachable": True,
            "interest_radius": safe_interest_radius,
            "coverage_diameter_m": round(
                (2.0 * safe_interest_radius + 1.0) * CHUNK_SIZE,
                3,
            ),
            "loaded_cells": cells,
            # Render-only HLOD cells are intentionally not part of gameplay
            # interest.  They carry the same deterministic terrain contract
            # but never expand physics, NPC pathing or network authority.
            "render_radius": safe_render_radius,
            "render_coverage_diameter_m": round(
                (2.0 * safe_render_radius + 1.0) * CHUNK_SIZE,
                3,
            ),
            "render_cells": render_cells,
        },
        "camera": {
            "movement_mode": mode,
            "yaw": round(float(camera_yaw), 4),
            "pitch": round(float(camera_pitch), 4),
            "distance": round(max(0.0, float(camera_distance)), 3),
            "projection": "PERSPECTIVE",
            "clip_near_m": DEFAULT_CAMERA_CLIP_NEAR_M,
            "clip_far_m": DEFAULT_CAMERA_CLIP_FAR_M,
            "near_representation": "MESH_AND_SIMULATION",
            "far_representation": "HLOD_IMPOSTOR_POINT_DETAIL",
            "local_position_m": {
                "x": round(camera_position[0], 3),
                "y": round(camera_position[1], 3),
                "z": round(camera_position[2], 3),
            },
            "planet_position_m": {
                "x": round(camera_planet_position[0], 3),
                "y": round(camera_planet_position[1], 3),
                "z": round(camera_planet_position[2], 3),
            },
            "player_relative_m": {
                "x": round(camera_relative((x, y, z), camera_position)[0], 3),
                "y": round(camera_relative((x, y, z), camera_position)[1], 3),
                "z": round(camera_relative((x, y, z), camera_position)[2], 3),
            },
            "surface_normal": {
                "x": round(surface_normal[0], 7),
                "y": round(surface_normal[1], 7),
                "z": round(surface_normal[2], 7),
            },
        },
        "lod": {
            "policy": "PROJECTED_SCREEN_ERROR",
            "tiers": list(LOD_TIERS),
            "morphing": True,
        },
    }
