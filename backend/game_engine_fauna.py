"""World-anchored birds, fish and clouds for the whole playground.

The groups are the existing Blender flock, school and cloud bank, repeated
on a sliding window of world cells. Each cell keeps its own phase, size and
path, so travelling shows new life and coming back shows the same life.
Nothing here is a physics body. The renderer draws a fixed number of copies.
"""

from __future__ import annotations

import math
from typing import Any, Callable


SCHEMA = "gg.game-engine.fauna.v1"
BIRD_SLOTS = 3
FISH_SLOTS = 8
CLOUD_SLOTS = 2
BIRD_CELL_M = 96.0
FISH_CELL_M = 82.0
CLOUD_CELL_M = 150.0


def _hash_unit(cell_x: int, cell_z: int, salt: int) -> float:
    """Deterministic 0..1 value. Not Python's salted hash."""
    value = (
        int(cell_x) * 374761393
        + int(cell_z) * 668265263
        + int(salt) * 1442695041
    ) & 0xFFFFFFFF
    value = (value ^ (value >> 13)) * 1274126177 & 0xFFFFFFFF
    return (value & 0xFFFFFFFF) / 4294967295.0


def _nearest_cells(
    x: float,
    z: float,
    cell_m: float,
    count: int,
) -> list[tuple[int, int]]:
    cell = max(16.0, float(cell_m))
    center_x = math.floor(float(x) / cell)
    center_z = math.floor(float(z) / cell)
    found: list[tuple[int, int, int, int]] = []
    span = 3
    for dz in range(-span, span + 1):
        for dx in range(-span, span + 1):
            found.append((dx * dx + dz * dz, dz, center_x + dx, center_z + dz))
    found.sort()
    return [(row[2], row[3]) for row in found[: max(1, int(count))]]


def _push_to_water(
    x: float,
    z: float,
    *,
    sea_level: float,
    height_at: Callable[[float, float], float] | None,
    island_radius: float,
) -> tuple[float, float]:
    """Keep a school off the island mesh and over the sea."""
    if height_at is None:
        distance = math.hypot(x, z)
        if distance < island_radius:
            scale = (island_radius + 8.0) / max(distance, 0.5)
            return x * scale, z * scale
        return x, z
    for _ in range(6):
        try:
            ground = float(height_at(x, z))
        except (TypeError, ValueError):
            break
        if ground < sea_level + 0.35 and math.hypot(x, z) > island_radius * 0.92:
            return x, z
        distance = math.hypot(x, z)
        if distance < 1.0:
            x, z = island_radius, 0.0
            continue
        scale = (distance + max(18.0, island_radius * 0.18)) / distance
        x *= scale
        z *= scale
    return x, z


def _group(
    kind: str,
    cell_x: int,
    cell_z: int,
    cell_m: float,
    time_s: float,
    *,
    salt: int,
    sea_level: float,
    altitude: tuple[float, float],
    orbit: tuple[float, float],
    speed: tuple[float, float],
    scale: tuple[float, float],
    height_at: Callable[[float, float], float] | None = None,
    water_at: Callable[[float, float], float] | None = None,
    island_radius: float = 50.0,
    on_water: bool = False,
) -> dict[str, float | str]:
    drift = _hash_unit(cell_x, cell_z, salt)
    across = _hash_unit(cell_x, cell_z, salt + 17)
    lift = _hash_unit(cell_x, cell_z, salt + 29)
    size = _hash_unit(cell_x, cell_z, salt + 41)
    anchor_x = (cell_x + 0.15 + 0.70 * drift) * cell_m
    anchor_z = (cell_z + 0.15 + 0.70 * across) * cell_m
    radius = orbit[0] + (orbit[1] - orbit[0]) * lift
    rate = speed[0] + (speed[1] - speed[0]) * drift
    angle = time_s * rate + across * math.tau
    heading = math.atan2(-math.sin(angle), math.cos(angle))
    if kind == "BIRD":
        # Individual body bones fly independent routes inside the authored
        # asset. Moving its root in a circle makes every bird a rigid clump.
        x = anchor_x
        z = anchor_z
        heading = 0.0
    elif kind == "FISH":
        # The school meanders together; independent body bones supply the
        # local shoaling motion. Harmonics avoid the old circular carousel.
        offset = drift * math.tau
        x = anchor_x + radius * (
            0.76 * math.sin(angle) + 0.24 * math.sin(3.0 * angle + offset)
        )
        z = anchor_z + radius * (
            0.42 * math.sin(2.0 * angle + offset)
            + 0.18 * math.cos(angle)
        )
        velocity_x = radius * rate * (
            0.76 * math.cos(angle) + 0.72 * math.cos(3.0 * angle + offset)
        )
        velocity_z = radius * rate * (
            0.84 * math.cos(2.0 * angle + offset)
            - 0.18 * math.sin(angle)
        )
        if math.hypot(velocity_x, velocity_z) > 0.05:
            heading = math.atan2(velocity_x, velocity_z)
    else:
        x = anchor_x + math.cos(angle) * radius
        z = anchor_z + math.sin(angle) * radius
    if on_water:
        x, z = _push_to_water(
            x,
            z,
            sea_level=sea_level,
            height_at=height_at,
            island_radius=island_radius + (32.0 if kind == "FISH" else 0.0),
        )
    water_height = sea_level
    if on_water and water_at is not None:
        try:
            water_height = float(water_at(x, z))
        except (TypeError, ValueError):
            water_height = sea_level
        if not math.isfinite(water_height):
            water_height = sea_level
    y = water_height + altitude[0] + (altitude[1] - altitude[0]) * lift
    if kind != "BIRD":
        y += math.sin(time_s * (0.45 + rate) + drift * 4.0) * (0.35 if not on_water else 0.04)
    visual_scale = scale[0] + (scale[1] - scale[0]) * size
    result = {
        "kind": kind,
        "x": round(x, 3),
        "y": round(y, 3),
        "z": round(z, 3),
        "yaw": round(heading, 4),
        "scale": round(visual_scale, 3),
    }
    if kind == 'CLOUD':
        result['motion'] = {'anchor_x':anchor_x,'anchor_z':anchor_z,'radius':radius,
            'rate':rate,'phase':across*math.tau,
            'altitude':sea_level+altitude[0]+(altitude[1]-altitude[0])*lift,
            'bob_rate':.45+rate,'bob_phase':drift*4}
    return result


def build_groups(
    x: float,
    z: float,
    time_s: float,
    *,
    sea_level: float = 0.0,
    island_radius: float = 50.0,
    height_at: Callable[[float, float], float] | None = None,
    water_at: Callable[[float, float], float] | None = None,
) -> dict[str, Any]:
    """Return the fixed visual budget of birds, fish and clouds."""
    safe_time = float(time_s) if math.isfinite(float(time_s)) else 0.0
    birds = [
        _group(
            "BIRD",
            cell_x,
            cell_z,
            BIRD_CELL_M,
            safe_time,
            salt=3,
            sea_level=sea_level,
            altitude=(9.0, 18.0),
            orbit=(7.0, 16.0),
            speed=(0.28, 0.52),
            scale=(0.85, 1.25),
        )
        for cell_x, cell_z in _nearest_cells(x, z, BIRD_CELL_M, BIRD_SLOTS)
    ]
    fish = [
        _group(
            "FISH",
            cell_x,
            cell_z,
            FISH_CELL_M,
            safe_time,
            salt=11,
            sea_level=sea_level,
            # Member bones hold fish at several depths below this shared
            # surface anchor; the shallow shoal remains near the root.
            altitude=(-0.04, 0.02),
            orbit=(3.0, 7.0),
            speed=(0.12, 0.22),
            scale=(0.8, 1.2),
            height_at=height_at,
            water_at=water_at,
            island_radius=island_radius,
            on_water=True,
        )
        for cell_x, cell_z in _nearest_cells(x, z, FISH_CELL_M, FISH_SLOTS)
    ]
    clouds = [
        _group(
            "CLOUD",
            cell_x,
            cell_z,
            CLOUD_CELL_M,
            safe_time,
            salt=23,
            sea_level=sea_level,
            altitude=(20.0, 36.0),
            orbit=(12.0, 28.0),
            speed=(0.04, 0.09),
            scale=(1.15, 2.05),
        )
        for cell_x, cell_z in _nearest_cells(x, z, CLOUD_CELL_M, CLOUD_SLOTS)
    ]
    return {
        "schema": SCHEMA,
        "policy": "INDEPENDENT_BIRD_PATHS_WORLD_CELL_ANCHORED_SCHOOLS",
        "birds": birds,
        "fish": fish,
        "clouds": clouds,
    }
