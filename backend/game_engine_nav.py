"""Bounded, deterministic tiled navigation over the shared terrain field.

This is deliberately a small navigation seam, not a replacement for a
production crowd solver.  It turns the same heightfield used by movement and
rendering into fixed-size walk tiles and provides a bounded A* query.  The
important contract is that cell streaming, terrain edits and path queries all
use the same world coordinates; there is no second, drifting copy of the
ground hidden inside the NPC system.
"""

from __future__ import annotations

import heapq
import math
from typing import Any, Iterable

from backend import game_engine_terrain as terrain
from backend import game_engine_world as world


SCHEMA = "gg.game-engine.nav.v1"
TILE_SIZE = 4.0
TILES_PER_CELL = max(1, int(round(world.CHUNK_SIZE / TILE_SIZE)))
# The default 7x7 world interest set contains 49 cells x 16 tiles.  Keep one
# bounded headroom tier so navigation covers the complete streamed surface
# instead of silently truncating the outer cells at the former 512-tile cap.
MAX_TILES = 1024
MAX_PATH_NODES = 128
MAX_EXPANDED_NODES = 256
MAX_STEP_HEIGHT = 1.25
MIN_GROUND_NORMAL_Y = 0.62
DEBUG_TILE_RADIUS = 2


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def tile_coord(value: Any) -> int:
    """Return the half-open tile owner for a world coordinate."""
    return math.floor(_finite(value) / TILE_SIZE)


def tile_key(x: int, z: int) -> str:
    """Use a distinct level in the shared key format for nav tiles."""
    return world.cell_key(int(x), int(z), level=1)


def tile_center(x: int, z: int) -> tuple[float, float]:
    return (
        (int(x) + 0.5) * TILE_SIZE,
        (int(z) + 0.5) * TILE_SIZE,
    )


def _cell_rows(loaded_cells: Iterable[dict[str, Any]]) -> list[tuple[int, int]]:
    result: set[tuple[int, int]] = set()
    for row in loaded_cells or ():
        if not isinstance(row, dict):
            continue
        try:
            result.add((int(row.get("x", 0)), int(row.get("z", 0))))
        except (TypeError, ValueError):
            continue
    return sorted(result, key=lambda value: (value[1], value[0]))


def _walkable(
    height: float,
    normal_y: float,
    movement_mode: str,
    water_level: float = terrain.SEA_LEVEL,
) -> bool:
    mode = world.normalize_movement_mode(movement_mode)
    if mode == "FLY":
        return True
    if mode == "SWIM":
        return height <= water_level + 0.35
    return height >= water_level and normal_y >= MIN_GROUND_NORMAL_Y


def build_nav_tiles(
    loaded_cells: Iterable[dict[str, Any]],
    *,
    world_seed: int = terrain.DEFAULT_WORLD_SEED,
    overrides: dict[str, Any] | None = None,
    movement_mode: str = "GROUND",
    include_blocked: bool = True,
) -> list[dict[str, Any]]:
    """Build a bounded tile set from currently loaded terrain cells."""
    mode = world.normalize_movement_mode(movement_mode)
    result: list[dict[str, Any]] = []
    for cell_x, cell_z in _cell_rows(loaded_cells):
        base_x = cell_x * TILES_PER_CELL
        base_z = cell_z * TILES_PER_CELL
        for local_z in range(TILES_PER_CELL):
            for local_x in range(TILES_PER_CELL):
                tile_x = base_x + local_x
                tile_z = base_z + local_z
                center_x, center_z = tile_center(tile_x, tile_z)
                height = terrain.height_at(
                    center_x,
                    center_z,
                    world_seed,
                    overrides=overrides,
                )
                normal = terrain.surface_normal_at(
                    center_x,
                    center_z,
                    world_seed,
                    overrides=overrides,
                )
                from backend.game_engine_landscape import water_at
                inland=water_at(center_x,center_z)
                water_level=inland['level_m'] if inland else terrain.SEA_LEVEL
                walkable = _walkable(height, normal[1], mode,water_level)
                if not include_blocked and not walkable:
                    continue
                slope_degrees = math.degrees(
                    math.acos(max(-1.0, min(1.0, float(normal[1]))))
                )
                result.append(
                    {
                        "key": tile_key(tile_x, tile_z),
                        "x": tile_x,
                        "z": tile_z,
                        "center_m": {
                            "x": round(center_x, 3),
                            "y": round(height, 3),
                            "z": round(center_z, 3),
                        },
                        "height_m": round(height, 3),
                        "normal_y": round(float(normal[1]), 4),
                        "slope_degrees": round(slope_degrees, 2),
                        "walkable": walkable,
                        "movement_mode": mode,
                        # Keep exact decisions before normal/height rounding.
                        # Changing locomotion needn't resample this terrain.
                        "_walkable_modes": tuple(_walkable(height,normal[1],m,water_level) for m in ('GROUND','FLY','SWIM')),
                        "terrain_cell": world.cell_key(cell_x, cell_z),
                    }
                )
                if len(result) >= MAX_TILES:
                    return result
    return result


def tiles_for_mode(tiles,movement_mode):
    """Reuse terrain samples while applying the exact locomotion policy."""
    mode=world.normalize_movement_mode(movement_mode);index=('GROUND','FLY','SWIM').index(mode)
    return [dict(tile,movement_mode=mode,walkable=tile['_walkable_modes'][index]) for tile in tiles]


def _tile_lookup(tiles: Iterable[dict[str, Any]]) -> dict[tuple[int, int], dict[str, Any]]:
    lookup: dict[tuple[int, int], dict[str, Any]] = {}
    for row in tiles or ():
        if not isinstance(row, dict) or not row.get("walkable"):
            continue
        try:
            key = (int(row.get("x", 0)), int(row.get("z", 0)))
        except (TypeError, ValueError):
            continue
        lookup[key] = row
    return lookup


def nearest_walkable_tile(
    tiles: Iterable[dict[str, Any]],
    x: float,
    z: float,
) -> dict[str, Any] | None:
    """Resolve a position to the nearest loaded walkable tile."""
    return _nearest_walkable_in_lookup(_tile_lookup(tiles), x, z)


def _nearest_walkable_in_lookup(
    lookup: dict[tuple[int, int], dict[str, Any]],
    x: float,
    z: float,
) -> dict[str, Any] | None:
    """Resolve a position without rebuilding an already prepared tile map."""
    if not lookup:
        return None
    wanted_x = _finite(x)
    wanted_z = _finite(z)
    return min(
        lookup.values(),
        key=lambda row: (
            (float(row["center_m"]["x"]) - wanted_x) ** 2
            + (float(row["center_m"]["z"]) - wanted_z) ** 2,
            int(row["z"]),
            int(row["x"]),
        ),
    )


def _neighbors(
    current: tuple[int, int],
    lookup: dict[tuple[int, int], dict[str, Any]],
) -> list[tuple[tuple[int, int], dict[str, Any]]]:
    x, z = current
    # Fixed order makes equal-cost routes and replays deterministic.
    coordinates = ((x, z - 1), (x + 1, z), (x, z + 1), (x - 1, z))
    result: list[tuple[tuple[int, int], dict[str, Any]]] = []
    origin = lookup[current]
    origin_height = float(origin.get("height_m", 0.0))
    movement_mode = world.normalize_movement_mode(
        origin.get("movement_mode", "GROUND")
    )
    for coordinate in coordinates:
        row = lookup.get(coordinate)
        if row is None:
            continue
        height_delta = abs(float(row.get("height_m", 0.0)) - origin_height)
        if movement_mode == "GROUND" and height_delta > MAX_STEP_HEIGHT:
            continue
        result.append((coordinate, row))
    return result


def plan_path(
    tiles: Iterable[dict[str, Any]],
    start_x: float,
    start_z: float,
    target_x: float,
    target_z: float,
    *,
    max_nodes: int = MAX_PATH_NODES,
) -> dict[str, Any]:
    """Plan a bounded four-connected path through loaded walk tiles."""
    safe_limit = max(1, min(MAX_PATH_NODES, int(max_nodes)))
    lookup = _tile_lookup(tiles)
    start = _nearest_walkable_in_lookup(lookup, start_x, start_z)
    goal = _nearest_walkable_in_lookup(lookup, target_x, target_z)
    if start is None or goal is None:
        return {
            "status": "NO_PATH",
            "reason": "NO_WALKABLE_TILE",
            "waypoints": [],
            "expanded": 0,
        }

    start_key = (int(start["x"]), int(start["z"]))
    goal_key = (int(goal["x"]), int(goal["z"]))
    if start_key == goal_key:
        return {
            "status": "READY",
            "reason": "ALREADY_THERE",
            "waypoints": [dict(start["center_m"])],
            "tiles": [start["key"]],
            "expanded": 0,
            "cost": 0.0,
        }

    def heuristic(coordinate: tuple[int, int]) -> float:
        return float(abs(coordinate[0] - goal_key[0]) + abs(coordinate[1] - goal_key[1]))

    queue: list[tuple[float, float, int, int]] = []
    heapq.heappush(queue, (heuristic(start_key), 0.0, start_key[1], start_key[0]))
    came_from: dict[tuple[int, int], tuple[int, int]] = {}
    cost_so_far = {start_key: 0.0}
    expanded = 0
    found = False
    while queue and expanded < MAX_EXPANDED_NODES:
        _priority, current_cost, current_z, current_x = heapq.heappop(queue)
        current = (current_x, current_z)
        if current_cost != cost_so_far.get(current):
            continue
        expanded += 1
        if current == goal_key:
            found = True
            break
        for neighbor, _row in _neighbors(current, lookup):
            next_cost = current_cost + 1.0
            if next_cost >= cost_so_far.get(neighbor, float("inf")):
                continue
            cost_so_far[neighbor] = next_cost
            came_from[neighbor] = current
            heapq.heappush(
                queue,
                (
                    next_cost + heuristic(neighbor),
                    next_cost,
                    neighbor[1],
                    neighbor[0],
                ),
            )

    if not found:
        return {
            "status": "NO_PATH",
            "reason": "LOADED_TILES_DISCONNECTED",
            "waypoints": [],
            "expanded": expanded,
        }

    coordinates = [goal_key]
    while coordinates[-1] != start_key and len(coordinates) < safe_limit:
        coordinates.append(came_from[coordinates[-1]])
    if coordinates[-1] != start_key:
        return {
            "status": "NO_PATH",
            "reason": "PATH_NODE_BUDGET",
            "waypoints": [],
            "expanded": expanded,
        }
    coordinates.reverse()
    waypoints = [dict(lookup[coordinate]["center_m"]) for coordinate in coordinates]
    return {
        "status": "READY",
        "reason": "ASTAR",
        "waypoints": waypoints,
        "tiles": [lookup[coordinate]["key"] for coordinate in coordinates],
        "expanded": expanded,
        "cost": round(float(cost_so_far[goal_key]), 3),
    }


def navmesh_view_from_tiles(
    tiles: list[dict[str, Any]],
    loaded_cells: Iterable[dict[str, Any]],
    player_position: tuple[float, float, float],
    movement_mode: str = "GROUND",
) -> dict[str, Any]:
    """Build the compact view from already-built tiles.

    Tile construction is the expensive part.  The host caches it until the
    loaded cell set, movement mode or terrain authoring revision changes, but
    the player tile/debug window can still update every UI snapshot.
    """
    mode = world.normalize_movement_mode(movement_mode)
    walkable_count = sum(1 for row in tiles if row.get("walkable"))
    blocked_count = max(0, len(tiles) - walkable_count)
    player_x = _finite(player_position[0])
    player_z = _finite(player_position[2])
    player_tile_x = tile_coord(player_x)
    player_tile_z = tile_coord(player_z)
    player_row = next(
        (
            row
            for row in tiles
            if int(row.get("x", 0)) == player_tile_x
            and int(row.get("z", 0)) == player_tile_z
        ),
        None,
    )
    debug_tiles = [
        row
        for row in tiles
        if abs(int(row.get("x", 0)) - player_tile_x) <= DEBUG_TILE_RADIUS
        and abs(int(row.get("z", 0)) - player_tile_z) <= DEBUG_TILE_RADIUS
    ][: (DEBUG_TILE_RADIUS * 2 + 1) ** 2]
    return {
        "schema": SCHEMA,
        "model": "TILED_HEIGHTFIELD_ASTAR",
        "movement_mode": mode,
        "tile_size_m": TILE_SIZE,
        "tiles_per_cell": TILES_PER_CELL,
        "streaming": {
            "source": "TERRAIN_INTEREST_CELLS",
            "loaded_cells": len(_cell_rows(loaded_cells)),
            "loaded_tiles": len(tiles),
            "capacity_tiles": MAX_TILES,
            "cross_cell": True,
        },
        "walkable_tiles": walkable_count,
        "blocked_tiles": blocked_count,
        "player_tile": {
            "x": player_tile_x,
            "z": player_tile_z,
            "key": tile_key(player_tile_x, player_tile_z),
            "walkable": bool(player_row and player_row.get("walkable")),
        },
        "limits": {
            "max_step_height_m": MAX_STEP_HEIGHT,
            "min_ground_normal_y": MIN_GROUND_NORMAL_Y,
            "max_expanded_nodes": MAX_EXPANDED_NODES,
            "max_path_nodes": MAX_PATH_NODES,
        },
        "integration": {
            "npc_query": "READY_BOUNDED_ASTAR_SEAM",
            "npc_runtime": "DIRECT_STEERING_BOUNDED",
            "crowd_solver": "NOT_CONNECTED",
            "server_authority": "LOCAL_PREVIEW",
        },
        "debug_tiles": debug_tiles,
    }


def build_navmesh_view(
    loaded_cells: Iterable[dict[str, Any]],
    player_position: tuple[float, float, float],
    movement_mode: str = "GROUND",
    *,
    world_seed: int = terrain.DEFAULT_WORLD_SEED,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build tiles and a view in one call for standalone consumers/tests."""
    cell_rows = list(loaded_cells or ())
    tiles = build_nav_tiles(
        cell_rows,
        world_seed=world_seed,
        overrides=overrides,
        movement_mode=movement_mode,
    )
    return navmesh_view_from_tiles(
        tiles,
        cell_rows,
        player_position,
        movement_mode,
    )
