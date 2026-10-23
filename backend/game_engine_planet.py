"""Deterministic macro geography for the first Sandover planet.

The coastlines, continental relief and seabed are pure functions of world
coordinates and one shared seed. Time-dependent water, weather and wildlife
stay in their existing simulation systems; they never move a coastline.
"""

from __future__ import annotations

import math
from typing import Any

from backend import game_engine_world as world


SCHEMA = "gg.game-engine.planet.v1"
PLANET_ID = "SANDOVER_PRIME"
MAP_REVISION = 3
LAYOUT_SCALE = world.PLANET_LAYOUT_SCALE
MAP_BOUNDS_M = {"min_x": -2_650.0 * LAYOUT_SCALE, "max_x": 2_650.0 * LAYOUT_SCALE, "min_z": -2_650.0 * LAYOUT_SCALE, "max_z": 2_650.0 * LAYOUT_SCALE}
MAP_CHART_LAYOUT = {
    "viewbox_width": 1_440.0,
    "viewbox_height": 1_020.0,
    "plot_x": 64.0,
    "plot_y": 82.0,
    "plot_width": 840.0,
    "plot_height": 840.0,
}
SEA_LEVEL_M = 0.0
OCEAN_DEPTH_RANGE_M = (-2_500.0, 0.0)

# Ellipses are only the macro silhouette. The sampler warps each coast with
# a stable, seed-derived harmonic; a second, finer field forms shelves, ridges,
# mountain chains and trenches without adding frame-time randomness.
_AUTHORED_LANDMASSES: tuple[dict[str, Any], ...] = (
    {
        "id": "WESTREACH", "name": "Westreach", "type": "CONTINENT",
        "center_m": (-1_470.0, 40.0), "radii_m": (770.0, 1_220.0),
        "rotation_rad": -0.11, "coast_seed": 17, "relief_seed": 29,
        "max_elevation_m": 142.0, "biome": "TEMPERATE",
        "mountain_spine": (0.16, -0.22, 122.0, 0.13),
        "map_color": "#598d62",
    },
    {
        "id": "EASTERN_CROWN", "name": "Eastern Crown", "type": "CONTINENT",
        "center_m": (1_440.0, 20.0), "radii_m": (665.0, 1_115.0),
        "rotation_rad": 0.08, "coast_seed": 31, "relief_seed": 43,
        "max_elevation_m": 168.0, "biome": "TEMPERATE",
        "mountain_spine": (-0.18, 0.08, 142.0, 0.16),
        "map_color": "#71905a",
    },
    {
        "id": "FROSTWARD", "name": "Frostward", "type": "CONTINENT",
        "center_m": (-20.0, 1_835.0), "radii_m": (1_080.0, 405.0),
        "rotation_rad": 0.04, "coast_seed": 53, "relief_seed": 61,
        "max_elevation_m": 188.0, "biome": "TUNDRA",
        "mountain_spine": (0.03, 0.30, 156.0, 0.12),
        "map_color": "#a7c7c1",
    },
    {
        "id": "SUNWARD", "name": "Sunward Reach", "type": "CONTINENT",
        "center_m": (10.0, -1_825.0), "radii_m": (955.0, 420.0),
        "rotation_rad": -0.03, "coast_seed": 71, "relief_seed": 83,
        "max_elevation_m": 152.0, "biome": "JUNGLE",
        "mountain_spine": (-0.12, -0.36, 113.0, 0.19),
        "map_color": "#4f9972",
    },
    {
        "id": "TIDEHOLD_NORTH", "name": "Tidehold", "type": "ISLAND",
        "center_m": (910.0, -1_330.0), "radii_m": (215.0, 118.0),
        "rotation_rad": -0.28, "coast_seed": 97, "relief_seed": 101,
        "max_elevation_m": 72.0, "biome": "TEMPERATE",
        "mountain_spine": (0.0, 0.0, 0.0, 1.0), "map_color": "#d0b77a",
    },
    {
        "id": "TIDEHOLD_EAST", "name": "Tidehold East", "type": "ISLAND",
        "center_m": (1_330.0, -1_185.0), "radii_m": (156.0, 244.0),
        "rotation_rad": 0.31, "coast_seed": 107, "relief_seed": 109,
        "max_elevation_m": 91.0, "biome": "TEMPERATE",
        "mountain_spine": (0.0, 0.0, 0.0, 1.0), "map_color": "#d0b77a",
    },
    {
        "id": "TIDEHOLD_SOUTH", "name": "Tidehold South", "type": "ISLAND",
        "center_m": (1_035.0, -1_650.0), "radii_m": (183.0, 126.0),
        "rotation_rad": -0.16, "coast_seed": 127, "relief_seed": 131,
        "max_elevation_m": 55.0, "biome": "JUNGLE",
        "mountain_spine": (0.0, 0.0, 0.0, 1.0), "map_color": "#6da26e",
    },
    {
        "id": "EMBER_ISLE", "name": "Ember Isle", "type": "ISLAND",
        "center_m": (-1_090.0, -1_205.0), "radii_m": (170.0, 214.0),
        "rotation_rad": 0.18, "coast_seed": 149, "relief_seed": 151,
        "max_elevation_m": 224.0, "biome": "VOLCANIC",
        "mountain_spine": (0.0, 0.0, 176.0, 0.11), "map_color": "#a85f4b",
    },
)

_AUTHORED_SEA_REGIONS: tuple[dict[str, Any], ...] = (
    {"id": "THE_MAELSTROM", "name": "The Maelstrom", "center_m": (75.0, -560.0), "radius_m": 205.0},
)

# Public geography uses game meters. Sampling keeps the original source frame,
# so scaling the baked mesh and querying terrain produce the same coast/relief.
LANDMASSES = tuple({**row,
    "center_m": tuple(value * LAYOUT_SCALE for value in row["center_m"]),
    "radii_m": tuple(value * LAYOUT_SCALE for value in row["radii_m"]),
} for row in _AUTHORED_LANDMASSES)
SEA_REGIONS = tuple({**row,
    "center_m": tuple(value * LAYOUT_SCALE for value in row["center_m"]),
    "radius_m": row["radius_m"] * LAYOUT_SCALE,
} for row in _AUTHORED_SEA_REGIONS)

_BIOME_COLORS = {
    "TEMPERATE": "#598d62",
    "TUNDRA": "#a7c7c1",
    "JUNGLE": "#4f9972",
    "VOLCANIC": "#a85f4b",
}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _smoothstep(low: float, high: float, value: float) -> float:
    if high <= low:
        return 1.0 if value >= high else 0.0
    amount = _clamp((value - low) / (high - low), 0.0, 1.0)
    return amount * amount * (3.0 - 2.0 * amount)


def _seed_phase(world_seed: int, salt: int) -> float:
    value = (int(world_seed) ^ (salt * 0x9E3779B1)) & 0xFFFFFFFF
    value ^= value >> 16
    value = (value * 0x7FEB352D) & 0xFFFFFFFF
    value ^= value >> 15
    return (value & 0xFFFF) / 65535.0 * math.tau


def _coast_boundary(theta: float, phase: float) -> float:
    return (
        1.0
        + 0.052 * math.sin(theta * 2.0 + phase)
        + 0.038 * math.sin(theta * 3.0 - phase * 0.47)
        + 0.021 * math.sin(theta * 5.0 + phase * 0.83)
        + 0.014 * math.sin(theta * 7.0 - phase * 1.21)
        + 0.008 * math.sin(theta * 11.0 + phase * 1.7)
    )


def _shape(row: dict[str, Any], x: float, z: float, world_seed: int) -> tuple[float, float, float, float]:
    center_x, center_z = row["center_m"]
    radius_x, radius_z = row["radii_m"]
    angle = float(row["rotation_rad"])
    dx, dz = x - center_x, z - center_z
    cosine, sine = math.cos(angle), math.sin(angle)
    local_x = cosine * dx + sine * dz
    local_z = -sine * dx + cosine * dz
    nx, nz = local_x / radius_x, local_z / radius_z
    theta = math.atan2(nz, nx)
    phase = _seed_phase(world_seed, int(row["coast_seed"]))
    boundary = _coast_boundary(theta, phase)
    radial = math.hypot(nx, nz) / boundary
    edge_m = (radial - 1.0) * min(radius_x, radius_z)
    return edge_m, radial, local_x, local_z


def coastline_points(
    region_id: str,
    world_seed: int = 0x47544731,
    segments: int = 96,
) -> list[tuple[float, float]]:
    """Trace the exact deterministic coast used by the terrain sampler."""
    row = next((item for item in LANDMASSES if item["id"] == str(region_id)), None)
    if str(region_id) == "START_ISLAND":
        # The first island keeps its older hand-shaped playable terrain. This
        # compact ellipse is its stable chart outline, not a replacement mesh.
        count = max(16, min(720, int(segments)))
        return [
            (57.2 * LAYOUT_SCALE * math.cos(math.tau * index / count), 48.9 * LAYOUT_SCALE * math.sin(math.tau * index / count))
            for index in range(count)
        ]
    if row is None:
        return []
    center_x, center_z = row["center_m"]
    radius_x, radius_z = row["radii_m"]
    angle = float(row["rotation_rad"])
    cosine, sine = math.cos(angle), math.sin(angle)
    phase = _seed_phase(world_seed, int(row["coast_seed"]))
    count = max(16, min(720, int(segments)))
    points: list[tuple[float, float]] = []
    for index in range(count):
        theta = math.tau * index / count
        boundary = _coast_boundary(theta, phase)
        local_x = radius_x * boundary * math.cos(theta)
        local_z = radius_z * boundary * math.sin(theta)
        points.append((
            center_x + cosine * local_x - sine * local_z,
            center_z + sine * local_x + cosine * local_z,
        ))
    return points


def _land_height(row: dict[str, Any], radial: float, local_x: float, local_z: float, world_seed: int) -> float:
    radius = min(float(row["radii_m"][0]), float(row["radii_m"][1]))
    interior = _clamp(1.0 - radial, 0.0, 1.0)
    phase = _seed_phase(world_seed, int(row["relief_seed"]))
    broad = (
        0.48 * math.sin(local_x * 0.0038 + phase)
        + 0.34 * math.sin(local_z * 0.0031 - phase * 0.7)
        + 0.18 * math.sin((local_x + local_z) * 0.0062 + phase * 1.3)
    )
    relief = (9.0 + float(row["max_elevation_m"]) * interior ** 0.68)
    relief *= 0.82 + 0.18 * broad
    spine_x, spine_z, spine_height, spine_width = row["mountain_spine"]
    if spine_height > 0.0:
        # A broad, bent continental backbone. It leaves valleys and low routes
        # on both sides instead of turning the whole interior into a wall.
        cross = local_x * spine_x + local_z * spine_z
        along = local_x * spine_z - local_z * spine_x
        bend = 0.13 * math.sin(along * 0.0018 + phase) * radius
        ridge = math.exp(-0.5 * ((cross - bend) / (radius * spine_width)) ** 2)
        ridge *= 0.35 + 0.65 * interior
        relief += float(spine_height) * ridge
    hills = 4.2 * math.sin(local_x * 0.012 + phase) * math.sin(local_z * 0.009 - phase)
    return max(2.0, relief + hills)


def _coast_edges(x: float, z: float, world_seed: int) -> list[tuple[float, dict[str, Any], float, float, float]]:
    result = []
    for row in _AUTHORED_LANDMASSES:
        edge, radial, local_x, local_z = _shape(row, x, z, world_seed)
        result.append((edge, row, radial, local_x, local_z))
    # The start island remains authored in game_engine_terrain; this circular
    # coast approximation only gives its surrounding seabed a continental shelf.
    start_edge = (math.hypot(x / 1.10, z / 0.94) - 52.0)
    result.append((start_edge, {"id": "START_ISLAND", "type": "ISLAND"}, 0.0, 0.0, 0.0))
    return result


def region_at(x: float, z: float, world_seed: int = 0x47544731) -> dict[str, Any] | None:
    """Return the stable named land region containing a game-space point."""
    from backend import game_engine_landscape as landscape
    owner=landscape.coast_owner(x,z)
    if owner:
        if surface_height(x,z,world_seed)<=0:return None
        row=next((r for r in LANDMASSES if r['id']==owner),None)
        if row:return {k:row[k] for k in ('id','name','type','biome')}
    inside = [row for row in _coast_edges(float(x) / LAYOUT_SCALE, float(z) / LAYOUT_SCALE, world_seed) if row[0] <= 0.0]
    if inside:
        edge, row, _radial, _local_x, _local_z = min(inside, key=lambda item: item[0])
        if row.get("id") == "START_ISLAND":
            return {"id": "START_ISLAND", "name": "Sandover", "type": "START_ISLAND", "biome": "FIRST_ISLAND"}
        return {"id": row["id"], "name": row["name"], "type": row["type"], "biome": row["biome"]}
    return None


def biome_at(x: float, z: float, world_seed: int = 0x47544731) -> str:
    region = region_at(x, z, world_seed)
    if region:
        return str(region["biome"])
    if any(math.hypot(x - row["center_m"][0], z - row["center_m"][1]) <= row["radius_m"] for row in SEA_REGIONS):
        return "MAELSTROM"
    return "ABYSS"


def base_surface_height(x: float, z: float, world_seed: int = 0x47544731) -> float:
    """Static land or seabed elevation; never depends on time or client state."""
    px, pz = float(x) / LAYOUT_SCALE, float(z) / LAYOUT_SCALE
    coast = _coast_edges(px, pz, world_seed)
    edge, row, radial, local_x, local_z = min(coast, key=lambda item: item[0])
    if edge <= 0.0 and row.get("id") != "START_ISLAND":
        land = _land_height(row, radial, local_x, local_z, world_seed)
        # Sea level crosses the authored coast exactly. The inner transition
        # forms a shallow beach, while the outer transition remains underwater.
        return land * _smoothstep(0.0, 22.0, -edge)

    distance_to_coast = max(0.0, edge)
    if distance_to_coast <= 20.0:
        return -distance_to_coast * 1.05
    shelf_depth = -21.0 - min(720.0, (distance_to_coast - 20.0) * 1.72)
    phase = _seed_phase(world_seed, 0x51A)
    broad_basin = 138.0 * math.sin(px * 0.0015 + phase) * math.cos(pz * 0.0011 - phase * 0.8)
    ridge_axis = pz - (0.21 * px + 310.0 * math.sin(px * 0.0009 + phase))
    mid_ocean_ridge = 285.0 * math.exp(-0.5 * (ridge_axis / 255.0) ** 2)
    trench_axis = px - (210.0 + 165.0 * math.sin(pz * 0.0008 - phase))
    abyssal_trench = -610.0 * math.exp(-0.5 * (trench_axis / 148.0) ** 2)
    deep_floor = _clamp(-1_440.0 + broad_basin + mid_ocean_ridge + abyssal_trench, -2_500.0, -520.0)
    deep_blend = _smoothstep(270.0, 520.0, distance_to_coast)
    floor = shelf_depth * (1.0 - deep_blend) + deep_floor * deep_blend
    for region in _AUTHORED_SEA_REGIONS:
        center_x, center_z = region["center_m"]
        distance = math.hypot(px - center_x, pz - center_z)
        radius = float(region["radius_m"])
        if distance > radius * 1.6:
            continue
        core = -1_280.0 - 680.0 * math.exp(-0.5 * (distance / (radius * 0.34)) ** 2)
        caldera_rim = 420.0 * math.exp(-0.5 * ((distance - radius * 0.72) / (radius * 0.12)) ** 2)
        maelstrom_floor = _clamp(core + caldera_rim, -2_500.0, -520.0)
        blend = 1.0 - _smoothstep(radius * 1.2, radius * 1.6, distance)
        floor = floor * (1.0 - blend) + maelstrom_floor * blend
    return floor


def surface_height(x: float, z: float, world_seed: int = 0x47544731) -> float:
    from backend.game_engine_landscape import surface_height as enrich
    return enrich(float(x),float(z),base_surface_height(x,z,world_seed))


def map_contract(world_seed: int = 0x47544731) -> dict[str, Any]:
    """Serializable atlas metadata shared by runtime, map UI and multiplayer."""
    regions = []
    for row in LANDMASSES:
        regions.append({
            "id": row["id"], "name": row["name"], "type": row["type"],
            "center_m": {"x": row["center_m"][0], "z": row["center_m"][1]},
            "radii_m": {"x": row["radii_m"][0], "z": row["radii_m"][1]},
            "biome": row["biome"], "color": row["map_color"],
            "coast": "SEED_LOCKED_HARMONIC", "height": "CONTINENTAL_RELIEF_FIELD",
        })
    regions.insert(0, {
        "id": "START_ISLAND", "name": "Sandover", "type": "START_ISLAND",
        "center_m": {"x": 0.0, "z": 0.0},
        "radii_m": {"x": 57.2 * LAYOUT_SCALE, "z": 48.9 * LAYOUT_SCALE},
        "biome": "FIRST_ISLAND", "color": "#c3a76e",
        "coast": "AUTHORED_START_ISLAND_CHART_OUTLINE",
        "height": "LEGACY_AUTHORED_STARTER_FIELD",
    })
    from backend.game_engine_world_places import catalog
    from backend.game_engine_landscape import catalog as landscape_catalog
    places=catalog()
    return {
        "schema": SCHEMA,
        "planet_id": PLANET_ID,
        "map_revision": MAP_REVISION,
        "horizontal_layout_scale": LAYOUT_SCALE,
        "world_seed": int(world_seed) & 0xFFFFFFFF,
        "seed_policy": "BUILD_MANIFEST_FIXED_SHARED_SEED",
        "coordinate_frame": "PLANET_LOCAL_GAME_METERS",
        "projection": "LOCAL_TANGENT_AT_START_ISLAND",
        "atlas_scope": "COMPLETE_AUTHORED_FIRST_WORLD_REGION_NOT_FULL_SPHERE",
        "bounds_m": dict(MAP_BOUNDS_M),
        "chart_layout": dict(MAP_CHART_LAYOUT),
        "sea_level_m": SEA_LEVEL_M,
        "ocean_depth_range_m": {"min": OCEAN_DEPTH_RANGE_M[0], "max": OCEAN_DEPTH_RANGE_M[1]},
        "landmasses": regions,
        "sea_regions": [dict(row) for row in SEA_REGIONS],
        "places": [{k:p[k] for k in ('id','name','region_id','kind','x','z','landmark')} for p in places['places']],
        "roads": places['roads'],
        "landscape": {"revision":landscape_catalog().get('revision',0),
                      "features":[{k:r[k] for k in ('id','name','region_id','kind','x','z')}
                                  for r in landscape_catalog()['features']],
                      "bridges":[{k:r[k] for k in ('id','name','x','z')} for r in landscape_catalog()['bridges']]},
        "dynamic_layers": ["TIDAL_SWELL", "WEATHER", "BIRDS", "FISH"],
        "static_layers": ["COASTLINES", "TERRAIN_RELIEF", "SEABED", "BIOMES", "REGION_IDS"],
    }
