"""Deterministic low-cost terrain, biome and water data for the GAME ENGINE.

The first island is intentionally generated from a tiny analytic function.  It
has no asset dependency and no Python ``hash`` calls, so the same cell always
produces the same result on every machine.  The output is a compact cell
contract: a future native renderer can replace the patch representation while
physics, networking and the in-game editor continue to consume the same data.
"""

from __future__ import annotations

from copy import deepcopy
import math
from typing import Any

from backend import game_engine_world as world
from backend import game_engine_planet as planet_contract


SCHEMA = "gg.game-engine.terrain.v1"
AUTHORING_SCHEMA = "gg.game-engine.terrain-authoring.v1"
AUTHORING_VERSION = 1
DEFAULT_WORLD_SEED = 0x47544731
CELL_SIZE = world.CHUNK_SIZE
SEA_LEVEL = 0.0
# The gameplay interest set remains small, but the renderer may receive a
# larger outer HLOD ring so the visible ground reaches the camera horizon.
# Radius 9 is 19x19 = 361 cells, with a bounded headroom tier for future
# camera presets and authored terrain patches.
MAX_TERRAIN_CELLS = 512
MAX_OVERRIDES = 64
MAX_BRUSH_STAMPS = 128
MAX_UNDO = 128
EDIT_OPERATIONS = ("RAISE", "LOWER", "LAND", "WATER", "REEF", "ISLAND", "CLEAR")
BRUSH_FALLOFFS = ("SMOOTH", "LINEAR", "SHARP", "GAUSSIAN")
MIN_BRUSH_RADIUS_M = 0.75
MAX_BRUSH_RADIUS_M = CELL_SIZE * 1.25
MAX_BRUSH_STRENGTH_M = 4.0

BIOMES = (
    "FIRST_ISLAND",
    "LAND",
    "BEACH",
    "CLIFF",
    "SHALLOW_WATER",
    "DEEP_WATER",
    "REEF",
    "TEMPERATE",
    "TUNDRA",
    "JUNGLE",
    "VOLCANIC",
    "ABYSS",
    "MAELSTROM",
)
LAND_BIOMES = {"FIRST_ISLAND", "LAND", "BEACH", "CLIFF", "TEMPERATE", "TUNDRA", "JUNGLE", "VOLCANIC"}
WATER_BIOMES = {"SHALLOW_WATER", "DEEP_WATER", "REEF", "ABYSS", "MAELSTROM"}

_LOD_GEOMETRY: dict[str, dict[str, int | str]] = {
    "NEAR": {
        "representation": "PATCH_MESH",
        "vertex_grid": 5,
        "triangles": 64,
        "base_triangles": 32,
        "seam_triangles": 32,
    },
    "MID": {
        "representation": "PATCH_MESH",
        "vertex_grid": 3,
        "triangles": 24,
        "base_triangles": 8,
        "seam_triangles": 16,
    },
    "HORIZON": {
        "representation": "HLOD_IMPOSTOR",
        "vertex_grid": 2,
        "triangles": 10,
        "base_triangles": 2,
        "seam_triangles": 8,
    },
    "ORBIT": {
        "representation": "POINT_DETAIL",
        "vertex_grid": 1,
        "triangles": 0,
    },
}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _gaussian_landform(
    x: float,
    z: float,
    center_x: float,
    center_z: float,
    radius_x: float,
    radius_z: float,
) -> float:
    dx = (x - center_x) / radius_x
    dz = (z - center_z) / radius_z
    return math.exp(-0.5 * (dx * dx + dz * dz))


def _smooth_unit(value: float) -> float:
    """Return a clamped cubic transition for authored terrain corridors."""
    amount = max(0.0, min(1.0, float(value)))
    return amount * amount * (3.0 - 2.0 * amount)


def _u32(value: int) -> int:
    return int(value) & 0xFFFFFFFF


def _mix32(value: int) -> int:
    """Small platform-independent integer mixer for cell-local randomness."""
    value = _u32(value ^ (value >> 16))
    value = _u32(value * 0x7FEB352D)
    value = _u32(value ^ (value >> 15))
    value = _u32(value * 0x846CA68B)
    return _u32(value ^ (value >> 16))


def cell_seed(
    x: int,
    z: int,
    world_seed: int = DEFAULT_WORLD_SEED,
) -> int:
    """Return a stable unsigned seed for a signed cell coordinate."""
    mixed = _u32(world_seed) ^ _u32(int(x) * 0x9E3779B1)
    mixed ^= _u32(int(z) * 0x85EBCA77)
    return _mix32(mixed ^ 0xA511E9B3)


def normalize_lod(value: Any, default: str = "ORBIT") -> str:
    lod = str(value or default).upper()
    return lod if lod in _LOD_GEOMETRY else default


def normalize_biome(value: Any, default: str = "") -> str:
    biome = str(value or default).upper()
    return biome if biome in BIOMES else default


def normalize_water_mode(value: Any, default: str = "AUTO") -> str:
    mode = str(value or default).upper()
    return mode if mode in {"AUTO", "LAND", "WATER"} else default


def normalize_brush_falloff(value: Any, default: str = "SMOOTH") -> str:
    falloff = str(value or default).upper()
    return falloff if falloff in BRUSH_FALLOFFS else default


def new_overrides() -> dict[str, Any]:
    """Return an isolated, bounded terrain-authoring document."""
    return {
        "schema": AUTHORING_SCHEMA,
        "version": AUTHORING_VERSION,
        "revision": 0,
        "cells": {},
        "stamps": [],
        "stamp_sequence": 0,
        "history": [],
        "last_action": "RESET",
    }


def _override_key(x: int, z: int) -> str:
    return world.cell_key(int(x), int(z))


def _coords_from_key(value: Any) -> tuple[int, int]:
    parts = str(value or "").split(":")
    if len(parts) < 3:
        raise ValueError("invalid terrain cell key")
    return int(parts[-2]), int(parts[-1])


def _normalized_override_row(
    x: int,
    z: int,
    value: Any,
) -> dict[str, Any]:
    row = value if isinstance(value, dict) else {}
    height_delta = max(-32.0, min(32.0, _safe_float(row.get("height_delta_m"))))
    biome = normalize_biome(row.get("biome"), "")
    water_mode = normalize_water_mode(row.get("water_mode"), "AUTO")
    return {
        "key": _override_key(x, z),
        "x": int(x),
        "z": int(z),
        "height_delta_m": round(height_delta, 3),
        "biome": biome,
        "water_mode": water_mode,
    }


def _normalized_brush_stamp(
    value: Any,
    fallback_id: str = "brush",
) -> dict[str, Any]:
    """Return one bounded, cell-anchored sub-cell height stamp."""
    row = value if isinstance(value, dict) else {}
    try:
        cell_x = int(row.get("cell_x", 0))
    except (TypeError, ValueError):
        cell_x = 0
    try:
        cell_z = int(row.get("cell_z", 0))
    except (TypeError, ValueError):
        cell_z = 0
    default_x = (cell_x + 0.5) * CELL_SIZE
    default_z = (cell_z + 0.5) * CELL_SIZE
    center_x = _safe_float(row.get("center_x_m"), default_x)
    center_z = _safe_float(row.get("center_z_m"), default_z)
    min_x = cell_x * CELL_SIZE
    max_x = (cell_x + 1) * CELL_SIZE
    min_z = cell_z * CELL_SIZE
    max_z = (cell_z + 1) * CELL_SIZE
    center_x = max(min_x, min(max_x, center_x))
    center_z = max(min_z, min(max_z, center_z))
    radius = max(
        MIN_BRUSH_RADIUS_M,
        min(MAX_BRUSH_RADIUS_M, _safe_float(row.get("radius_m"), 4.0)),
    )
    strength = max(
        -MAX_BRUSH_STRENGTH_M,
        min(MAX_BRUSH_STRENGTH_M, _safe_float(row.get("strength_m"), 1.0)),
    )
    stamp_id = str(row.get("id") or fallback_id)[:32]
    return {
        "id": stamp_id,
        "cell_x": cell_x,
        "cell_z": cell_z,
        "center_x_m": round(center_x, 3),
        "center_z_m": round(center_z, 3),
        "radius_m": round(radius, 3),
        "strength_m": round(strength, 3),
        "falloff": normalize_brush_falloff(row.get("falloff"), "SMOOTH"),
    }


def _brush_falloff_factor(normalized_distance: float, falloff: str) -> float:
    distance = max(0.0, min(1.0, float(normalized_distance)))
    if distance >= 1.0:
        return 0.0
    edge = 1.0 - distance
    curve = normalize_brush_falloff(falloff)
    if curve == "LINEAR":
        return edge
    if curve == "SHARP":
        return edge * edge * edge
    if curve == "GAUSSIAN":
        edge_value = math.exp(-4.0)
        return max(
            0.0,
            (math.exp(-4.0 * distance * distance) - edge_value)
            / (1.0 - edge_value),
        )
    return edge * edge * (1.0 + 2.0 * distance)


def _normalized_brush_stamps(
    overrides: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Normalize the bounded stamp list once for one terrain evaluation."""
    if not isinstance(overrides, dict):
        return []
    stamps = overrides.get("stamps")
    if not isinstance(stamps, list):
        return []
    result: list[dict[str, Any]] = []
    for index, value in enumerate(stamps[:MAX_BRUSH_STAMPS]):
        if isinstance(value, dict):
            result.append(
                _normalized_brush_stamp(value, f"brush-{index + 1:06d}")
            )
    return result


def _build_brush_index(
    stamps: list[dict[str, Any]],
) -> dict[tuple[int, int], tuple[dict[str, Any], ...]]:
    """Index stamps by touched cells so height samples do not scan all stamps."""
    buckets: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for stamp in stamps[:MAX_BRUSH_STAMPS]:
        center_x = float(stamp["center_x_m"])
        center_z = float(stamp["center_z_m"])
        radius = max(MIN_BRUSH_RADIUS_M, float(stamp["radius_m"]))
        min_cell_x = math.floor((center_x - radius) / CELL_SIZE)
        max_cell_x = math.floor((center_x + radius) / CELL_SIZE)
        min_cell_z = math.floor((center_z - radius) / CELL_SIZE)
        max_cell_z = math.floor((center_z + radius) / CELL_SIZE)
        for cell_x in range(min_cell_x, max_cell_x + 1):
            for cell_z in range(min_cell_z, max_cell_z + 1):
                buckets.setdefault((cell_x, cell_z), []).append(stamp)
    return {key: tuple(value) for key, value in buckets.items()}


def override_for(
    overrides: dict[str, Any] | None,
    x: int,
    z: int,
) -> dict[str, Any] | None:
    """Return one sanitized cell override without exposing internal storage."""
    if not isinstance(overrides, dict):
        return None
    cells = overrides.get("cells")
    if not isinstance(cells, dict):
        return None
    value = cells.get(_override_key(x, z))
    return (
        _normalized_override_row(int(x), int(z), value)
        if isinstance(value, dict)
        else None
    )


def apply_override(
    overrides: dict[str, Any],
    x: int,
    z: int,
    *,
    height_delta_m: float | None = None,
    biome: Any = None,
    water_mode: Any = None,
    clear: bool = False,
) -> tuple[bool, dict[str, Any]]:
    """Set or clear one bounded cell override and record it for undo."""
    if not isinstance(overrides, dict):
        return False, {"error": "TERRAIN_AUTHORING_DOCUMENT_INVALID"}
    cells = overrides.get("cells")
    history = overrides.get("history")
    if not isinstance(cells, dict) or not isinstance(history, list):
        return False, {"error": "TERRAIN_AUTHORING_DOCUMENT_INVALID"}
    key = _override_key(int(x), int(z))
    before_value = cells.get(key)
    before = (
        _normalized_override_row(int(x), int(z), before_value)
        if isinstance(before_value, dict)
        else None
    )
    if clear:
        after = None
    else:
        existing = before or _normalized_override_row(int(x), int(z), {})
        next_height = (
            existing["height_delta_m"]
            if height_delta_m is None
            else max(-32.0, min(32.0, _safe_float(height_delta_m)))
        )
        next_biome = (
            existing["biome"]
            if biome is None
            else normalize_biome(biome, "")
        )
        next_water_mode = (
            existing["water_mode"]
            if water_mode is None
            else normalize_water_mode(water_mode, "AUTO")
        )
        after = _normalized_override_row(
            int(x),
            int(z),
            {
                "height_delta_m": next_height,
                "biome": next_biome,
                "water_mode": next_water_mode,
            },
        )
        if (
            after["height_delta_m"] == 0.0
            and not after["biome"]
            and after["water_mode"] == "AUTO"
        ):
            after = None

    if before == after:
        return False, {"error": "TERRAIN_AUTHORING_NOOP", "key": key}
    if before is None and after is not None and len(cells) >= MAX_OVERRIDES:
        return False, {
            "error": "TERRAIN_AUTHORING_CELL_BUDGET",
            "capacity": MAX_OVERRIDES,
        }

    if after is None:
        cells.pop(key, None)
    else:
        cells[key] = after
    history.append({
        "kind": "CELL",
        "key": key,
        "before": before,
        "after": after,
    })
    del history[:-MAX_UNDO]
    overrides["revision"] = int(overrides.get("revision", 0)) + 1
    overrides["last_action"] = "CLEAR" if clear else "EDIT"
    return True, {
        "key": key,
        "before": before,
        "after": after,
        "revision": overrides["revision"],
    }


def apply_brush(
    overrides: dict[str, Any],
    x: int,
    z: int,
    *,
    center_x_m: float | None = None,
    center_z_m: float | None = None,
    radius_m: float = 4.0,
    strength_m: float = 1.0,
    falloff: Any = "SMOOTH",
) -> tuple[bool, dict[str, Any]]:
    """Append one bounded sub-cell height stamp to the authoring document."""
    if not isinstance(overrides, dict):
        return False, {"error": "TERRAIN_AUTHORING_DOCUMENT_INVALID"}
    stamps = overrides.get("stamps")
    history = overrides.get("history")
    if (
        not isinstance(overrides.get("cells"), dict)
        or not isinstance(stamps, list)
        or not isinstance(history, list)
    ):
        return False, {"error": "TERRAIN_AUTHORING_DOCUMENT_INVALID"}
    cell_x = int(x)
    cell_z = int(z)
    stamp = _normalized_brush_stamp(
        {
            "cell_x": cell_x,
            "cell_z": cell_z,
            "center_x_m": center_x_m,
            "center_z_m": center_z_m,
            "radius_m": radius_m,
            "strength_m": strength_m,
            "falloff": falloff,
        },
        fallback_id=f"brush-{len(stamps) + 1:06d}",
    )
    if abs(float(stamp["strength_m"])) < 0.000001:
        return False, {"error": "TERRAIN_AUTHORING_NOOP"}
    if len(stamps) >= MAX_BRUSH_STAMPS:
        return False, {
            "error": "TERRAIN_AUTHORING_BRUSH_BUDGET",
            "capacity": MAX_BRUSH_STAMPS,
        }
    try:
        sequence = max(0, int(overrides.get("stamp_sequence", 0))) + 1
    except (TypeError, ValueError):
        sequence = len(stamps) + 1
    stamp["id"] = f"brush-{sequence:06d}"
    stamps.append(stamp)
    history.append(
        {
            "kind": "BRUSH",
            "key": _override_key(cell_x, cell_z),
            "stamp": deepcopy(stamp),
        }
    )
    del history[:-MAX_UNDO]
    overrides["stamp_sequence"] = sequence
    overrides["revision"] = int(overrides.get("revision", 0)) + 1
    overrides["last_action"] = "BRUSH"
    return True, {
        "kind": "BRUSH",
        "key": _override_key(cell_x, cell_z),
        "stamp": deepcopy(stamp),
        "revision": overrides["revision"],
    }


def undo_override(overrides: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    """Undo the latest terrain edit without growing an unbounded log."""
    if not isinstance(overrides, dict):
        return False, {"error": "TERRAIN_AUTHORING_DOCUMENT_INVALID"}
    cells = overrides.get("cells")
    history = overrides.get("history")
    if not isinstance(cells, dict) or not isinstance(history, list):
        return False, {"error": "TERRAIN_AUTHORING_DOCUMENT_INVALID"}
    if not history:
        return False, {"error": "TERRAIN_AUTHORING_UNDO_EMPTY"}
    action = history.pop()
    if str(action.get("kind", "CELL")).upper() == "BRUSH":
        stamps = overrides.get("stamps")
        stamp = action.get("stamp")
        stamp_id = str(stamp.get("id", "")) if isinstance(stamp, dict) else ""
        if not isinstance(stamps, list) or not stamp_id:
            history.append(action)
            return False, {"error": "TERRAIN_AUTHORING_BRUSH_MISSING"}
        removed = None
        for index in range(len(stamps) - 1, -1, -1):
            candidate = stamps[index]
            if isinstance(candidate, dict) and str(candidate.get("id", "")) == stamp_id:
                removed = _normalized_brush_stamp(candidate, stamp_id)
                stamps.pop(index)
                break
        if removed is None:
            history.append(action)
            return False, {
                "error": "TERRAIN_AUTHORING_BRUSH_MISSING",
                "id": stamp_id,
            }
        overrides["revision"] = int(overrides.get("revision", 0)) + 1
        overrides["last_action"] = "UNDO"
        return True, {
            "kind": "BRUSH",
            "key": _override_key(
                int(removed["cell_x"]), int(removed["cell_z"])
            ),
            "stamp": removed,
            "revision": overrides["revision"],
        }
    key = str(action.get("key", ""))
    before = action.get("before")
    if isinstance(before, dict):
        cells[key] = _normalized_override_row(
            int(before.get("x", 0)),
            int(before.get("z", 0)),
            before,
        )
    else:
        cells.pop(key, None)
    overrides["revision"] = int(overrides.get("revision", 0)) + 1
    overrides["last_action"] = "UNDO"
    return True, {
        "key": key,
        "restored": deepcopy(cells.get(key)) if key in cells else None,
        "revision": overrides["revision"],
    }


def summary(overrides: dict[str, Any]) -> dict[str, Any]:
    """Return an inspector-safe terrain-authoring summary."""
    cells = overrides.get("cells", {}) if isinstance(overrides, dict) else {}
    rows: list[dict[str, Any]] = []
    if isinstance(cells, dict):
        for key in sorted(cells):
            value = cells[key]
            if not isinstance(value, dict):
                continue
            rows.append(
                _normalized_override_row(
                    int(value.get("x", 0)),
                    int(value.get("z", 0)),
                    value,
                )
            )
            if len(rows) >= MAX_OVERRIDES:
                break
    brush_rows: list[dict[str, Any]] = []
    stamps = overrides.get("stamps", []) if isinstance(overrides, dict) else []
    if isinstance(stamps, list):
        for index, value in enumerate(stamps[:MAX_BRUSH_STAMPS]):
            if not isinstance(value, dict):
                continue
            brush_rows.append(
                _normalized_brush_stamp(value, f"brush-{index + 1:06d}")
            )
    return {
        "schema": str(
            overrides.get("schema", AUTHORING_SCHEMA)
            if isinstance(overrides, dict)
            else AUTHORING_SCHEMA
        ),
        "version": int(
            overrides.get("version", AUTHORING_VERSION)
            if isinstance(overrides, dict)
            else AUTHORING_VERSION
        ),
        "revision": int(overrides.get("revision", 0)) if isinstance(overrides, dict) else 0,
        "cells": rows,
        "override_count": len(rows),
        "brushes": brush_rows,
        "brush_count": len(brush_rows),
        "undo_depth": min(
            MAX_UNDO,
            len(overrides.get("history", []))
            if isinstance(overrides, dict) and isinstance(overrides.get("history"), list)
            else 0,
        ),
        "last_action": str(overrides.get("last_action", ""))
        if isinstance(overrides, dict)
        else "",
        "budget": {
            "cells": MAX_OVERRIDES,
            "brushes": MAX_BRUSH_STAMPS,
            "undo": MAX_UNDO,
        },
    }


def clone_overrides(overrides: Any) -> dict[str, Any]:
    """Clone only bounded, normalized authoring data from memory state."""
    result = new_overrides()
    if not isinstance(overrides, dict):
        return result
    source_cells = overrides.get("cells", {})
    if isinstance(source_cells, dict):
        for key in sorted(source_cells):
            value = source_cells[key]
            if not isinstance(value, dict):
                continue
            try:
                key_x, key_z = _coords_from_key(key)
                cell_x = int(value.get("x", key_x))
                cell_z = int(value.get("z", key_z))
            except (TypeError, ValueError, IndexError):
                continue
            if len(result["cells"]) >= MAX_OVERRIDES:
                break
            result["cells"][_override_key(cell_x, cell_z)] = _normalized_override_row(
                cell_x, cell_z, value
            )
    source_stamps = overrides.get("stamps", [])
    if isinstance(source_stamps, list):
        for index, value in enumerate(source_stamps[:MAX_BRUSH_STAMPS]):
            if not isinstance(value, dict):
                continue
            stamp = _normalized_brush_stamp(value, f"brush-{index + 1:06d}")
            result["stamps"].append(stamp)
            stamp_id = str(stamp.get("id", ""))
            sequence_text = stamp_id.rsplit("-", 1)[-1]
            if sequence_text.isdigit():
                result["stamp_sequence"] = max(
                    int(result.get("stamp_sequence", 0)),
                    int(sequence_text),
                )
    try:
        result["stamp_sequence"] = max(
            int(result.get("stamp_sequence", 0)),
            int(overrides.get("stamp_sequence", 0)),
        )
    except (TypeError, ValueError):
        pass
    source_history = overrides.get("history", [])
    if isinstance(source_history, list):
        for action in source_history[-MAX_UNDO:]:
            if not isinstance(action, dict):
                continue
            if str(action.get("kind", "CELL")).upper() == "BRUSH":
                stamp_value = action.get("stamp")
                if not isinstance(stamp_value, dict):
                    continue
                stamp = _normalized_brush_stamp(
                    stamp_value,
                    f"brush-history-{len(result['history']) + 1:06d}",
                )
                result["history"].append(
                    {
                        "kind": "BRUSH",
                        "key": _override_key(
                            int(stamp["cell_x"]), int(stamp["cell_z"])
                        ),
                        "stamp": stamp,
                    }
                )
                continue
            key = str(action.get("key", ""))
            try:
                key_x, key_z = _coords_from_key(key)
            except (TypeError, ValueError, IndexError):
                continue
            before_value = action.get("before")
            after_value = action.get("after")
            before = (
                _normalized_override_row(
                    int(before_value.get("x", key_x)),
                    int(before_value.get("z", key_z)),
                    before_value,
                )
                if isinstance(before_value, dict)
                else None
            )
            after = (
                _normalized_override_row(
                    int(after_value.get("x", key_x)),
                    int(after_value.get("z", key_z)),
                    after_value,
                )
                if isinstance(after_value, dict)
                else None
            )
            result["history"].append({
                "kind": "CELL",
                "key": key,
                "before": before,
                "after": after,
            })
    result["revision"] = max(0, int(overrides.get("revision", 0)))
    result["last_action"] = str(overrides.get("last_action", "LOAD"))[:24]
    return result


def _height_delta_at(
    x: float,
    z: float,
    overrides: dict[str, Any] | None,
    *,
    brush_stamps: list[dict[str, Any]] | None = None,
    brush_index: dict[tuple[int, int], tuple[dict[str, Any], ...]] | None = None,
) -> float:
    """Evaluate cell edits and sub-cell stamps as one continuous field."""
    if not isinstance(overrides, dict):
        return 0.0
    cells = overrides.get("cells")
    brush_radius = CELL_SIZE * 1.25
    total = 0.0
    sample_x = _safe_float(x)
    sample_z = _safe_float(z)
    if isinstance(cells, dict):
        for key in sorted(cells):
            value = cells[key]
            if not isinstance(value, dict):
                continue
            try:
                key_x, key_z = _coords_from_key(key)
                cell_x = int(value.get("x", key_x))
                cell_z = int(value.get("z", key_z))
            except (TypeError, ValueError, IndexError):
                continue
            distance = math.hypot(
                sample_x - (cell_x + 0.5) * CELL_SIZE,
                sample_z - (cell_z + 0.5) * CELL_SIZE,
            )
            normalized_distance = distance / brush_radius
            if normalized_distance >= 1.0:
                continue
            # Complementary smoothstep: full strength at the brush center and
            # zero slope/strength at the support edge. Both sides of a cell
            # edge evaluate the same world function, so streamed patches stay
            # seamless.
            falloff = (1.0 - normalized_distance) ** 2 * (
                1.0 + 2.0 * normalized_distance
            )
            total += _safe_float(value.get("height_delta_m")) * falloff

    normalized_stamps = (
        brush_stamps
        if brush_stamps is not None
        else _normalized_brush_stamps(overrides)
    )
    candidates = normalized_stamps
    if len(candidates) > MAX_BRUSH_STAMPS:
        candidates = candidates[:MAX_BRUSH_STAMPS]
    if brush_index is not None:
        sample_cell = (
            math.floor(sample_x / CELL_SIZE),
            math.floor(sample_z / CELL_SIZE),
        )
        candidates = brush_index.get(sample_cell, ())
    for stamp in candidates:
        center_x = float(stamp["center_x_m"])
        center_z = float(stamp["center_z_m"])
        radius = max(MIN_BRUSH_RADIUS_M, float(stamp["radius_m"]))
        delta_x = sample_x - center_x
        delta_z = sample_z - center_z
        if abs(delta_x) >= radius or abs(delta_z) >= radius:
            continue
        distance = math.hypot(delta_x, delta_z)
        normalized_distance = distance / radius
        total += float(stamp["strength_m"]) * _brush_falloff_factor(
            normalized_distance,
            str(stamp["falloff"]),
        )
    return max(-64.0, min(64.0, total))


def _starter_island_height(
    x: float,
    z: float,
    world_seed: int = DEFAULT_WORLD_SEED,
    *,
    overrides: dict[str, Any] | None = None,
    brush_stamps: list[dict[str, Any]] | None = None,
    brush_index: dict[tuple[int, int], tuple[dict[str, Any], ...]] | None = None,
) -> float:
    """Return a cheap, continuous terrain height in local game metres.

    The island uses one deterministic shared field for rendering, movement,
    navigation and water depth.  Its uneven coast has a sheltered cove, a few
    broad headlands and a low village green between raised landmarks.  Every
    feature is wider than the coarsest terrain samples so cell LOD remains
    continuous instead of turning these forms into noisy bumps.
    """
    # Sample the compact authored island, then expand it. Brushes stay in
    # world metres so an editor stroke of +2 m is still +2 m after the scale.
    feel = world.WORLD_FEEL_SCALE if world.WORLD_FEEL_SCALE > 0.0 else 1.0
    world_x = _safe_float(x)
    world_z = _safe_float(z)
    local_x = world_x / world.ISLAND_LAYOUT_SCALE
    local_z = world_z / world.ISLAND_LAYOUT_SCALE
    seed = _u32(world_seed)
    phase = (seed & 0xFFFF) / 65535.0 * math.tau

    # The coast is an oblong, three-lobed shelf rather than a circular plate.
    # The low-frequency waves are large enough to make real coves and points
    # at the 16 m world-cell scale used by the renderer.
    distance = math.hypot(local_x * 0.94, local_z * 1.02)
    angle = math.atan2(local_z * 1.02, local_x * 0.94)
    coast_fade = min(1.0, distance / 11.0)
    coast_wave = (
        2.50 * math.sin(angle * 3.0 + phase)
        + 1.30 * math.sin(angle * 5.0 - phase * 0.7)
        + 0.62 * math.sin(angle * 2.0 + phase * 0.4)
    ) * coast_fade
    harbor_cove = 2.35 * math.exp(
        -0.5 * (((local_x - 1.0) / 6.0) ** 2 + ((local_z + 18.0) / 3.5) ** 2)
    )
    coast_distance = max(0.0, distance - coast_wave) + harbor_cove
    shorefall = (
        max(0.0, coast_distance - 10.0) * 0.045
        + max(0.0, coast_distance - 14.0) * 0.100
        + max(0.0, coast_distance - 17.0) * 0.180
        + max(0.0, coast_distance - 20.0) * 0.220
    )

    # The village sits on several overlapping grassy shelves. The middle
    # remains open enough for play, while the shoulders rise into separate
    # headlands instead of reading as one circular tabletop.
    plateau_t = max(0.0, min(1.0, (coast_distance - 13.0) / 3.5))
    plateau_t = plateau_t * plateau_t * (3.0 - 2.0 * plateau_t)
    island_plateau = 3.50 * (1.0 - plateau_t)

    # A walkable green anchors the homes.  Higher ground carries the windmill,
    # northern lookout and western headland, giving the island a readable
    # skyline while keeping each climb gradual enough for the shared nav grid.
    village_green = -0.95 * _gaussian_landform(
        local_x, local_z, 0.0, 0.0, 5.8, 5.2
    )
    headlands = (
        3.00
        * _gaussian_landform(
            local_x, local_z, -11.0, -10.0, 8.5, 7.5
        )
        + 2.25
        * _gaussian_landform(
            local_x, local_z, 4.0, 11.0, 8.0, 6.0
        )
        + 1.85
        * _gaussian_landform(
            local_x, local_z, -13.0, 1.0, 5.5, 7.5
        )
        + 1.80
        * _gaussian_landform(
            local_x, local_z, 12.0, 2.0, 5.8, 7.0
        )
        + 1.15
        * _gaussian_landform(
            local_x, local_z, 8.0, -9.5, 5.2, 4.2
        )
        + 0.85
        * _gaussian_landform(
            local_x, local_z, -3.5, 13.2, 5.0, 3.4
        )
    )
    settlement_shelves = (
        1.35 * _gaussian_landform(local_x, local_z, -5.5, 4.0, 3.6, 3.5)
        + 1.40 * _gaussian_landform(local_x, local_z, 5.8, 5.2, 4.5, 3.8)
        + 0.95 * _gaussian_landform(local_x, local_z, 5.2, -5.3, 4.0, 3.0)
        + 0.95 * _gaussian_landform(local_x, local_z, -5.7, -6.2, 3.6, 3.4)
        + 0.85 * _gaussian_landform(local_x, local_z, 0.0, 8.0, 4.0, 3.2)
    )
    ridge = 0.22 * (
        math.sin((local_x + local_z) * 0.075 + phase * 0.35)
        - math.sin(phase * 0.35)
    )
    fine = 0.08 * (
        math.sin(local_x * 0.21 + local_z * 0.17 + phase * 1.3)
        - math.sin(phase * 1.3)
    )

    height = (
        0.98
        + island_plateau
        - shorefall
        + village_green
        + headlands
        + settlement_shelves
        + ridge
        + fine
    )

    # A broad south approach descends from the village to the sheltered cove.
    # Its grade stays inside the ground-nav limit; the surrounding rim keeps
    # the steeper cliff profile rather than turning the whole island into a ramp.
    cove_depth = max(0.0, -local_z)
    ramp_start = max(0.0, min(1.0, (cove_depth - 10.5) / 1.5))
    ramp_start = ramp_start * ramp_start * (3.0 - 2.0 * ramp_start)
    ramp_end = max(0.0, min(1.0, (cove_depth - 18.5) / 2.0))
    ramp_end = ramp_end * ramp_end * (3.0 - 2.0 * ramp_end)
    ramp_x = math.exp(-0.5 * ((local_x + 2.0) / 4.2) ** 2)
    ramp_weight = ramp_start * (1.0 - ramp_end) * ramp_x
    ramp_height = 6.15 - max(0.0, cove_depth - 12.0) * 0.95
    height += (ramp_height - height) * ramp_weight

    # Grass-capped sandstone sea stacks break up the open-water silhouette.
    # They stay in the shared field, so rendering, swimming depth and ground
    # queries agree on the same ledges.
    east_distance = math.hypot(local_x - 24.0, local_z - 4.5)
    east_stack = 3.10 - max(0.0, east_distance - 2.0) * 1.02
    west_distance = math.hypot(local_x + 23.0, local_z + 4.0)
    west_stack = 2.65 - max(0.0, west_distance - 1.85) * 0.98
    south_distance = math.hypot(local_x - 4.0, local_z + 22.0)
    south_stack = 2.10 - max(0.0, south_distance - 1.55) * 0.92
    height = max(height, east_stack, west_stack, south_stack)

    # The south cove is a real walking route from the village to the beach.
    # Its centre drops 5.15 m over 18 m (about 0.29 m per metre), keeping a
    # 4 m navigation step below the existing 1.25 m step limit.  Past the
    # shoreline, the same corridor continues as a shallow underwater slope
    # and blends back into the seabed by z=-24, avoiding a hidden drop-off.
    # The profile is measured against the controller scale and jump apex; it
    # avoids turning the whole coast into a ramp.
    path_distance = abs(local_x + 2.0)
    if path_distance <= 3.5:
        path_width = 1.0
    elif path_distance >= 7.5:
        path_width = 0.0
    else:
        path_width = 1.0 - _smooth_unit((path_distance - 3.5) / 4.0)
    if local_z < 0.0:
        route_progress = max(0.0, min(1.0, -local_z / 18.0))
        path_height = 5.60 + (0.45 - 5.60) * route_progress
        seabed_progress = 0.0
        if local_z < -18.0:
            seabed_progress = max(0.0, min(1.0, (-local_z - 18.0) / 6.0))
            path_height += (height - path_height) * seabed_progress
        if path_distance <= 3.5:
            path_height += (
                0.018 * path_distance * path_distance * (1.0 - seabed_progress)
            )
        if local_z < -24.0:
            path_width *= 1.0 - _smooth_unit((-local_z - 24.0) / 2.0)
    else:
        path_height = 5.60
        path_width *= 1.0 - _smooth_unit(local_z / 3.0)
    height += (path_height - height) * path_width
    height = SEA_LEVEL + (height - SEA_LEVEL) * feel

    local_x = world_x
    local_z = world_z
    normalized_stamps = (
        brush_stamps
        if brush_stamps is not None
        else _normalized_brush_stamps(overrides)
    )
    normalized_index = (
        brush_index
        if brush_index is not None
        else _build_brush_index(normalized_stamps)
    )
    height += _height_delta_at(
        local_x,
        local_z,
        overrides,
        brush_stamps=normalized_stamps,
        brush_index=normalized_index,
    )
    return round(height, 6)


def height_at(
    x: float,
    z: float,
    world_seed: int = DEFAULT_WORLD_SEED,
    *,
    overrides: dict[str, Any] | None = None,
    brush_stamps: list[dict[str, Any]] | None = None,
    brush_index: dict[tuple[int, int], tuple[dict[str, Any], ...]] | None = None,
) -> float:
    """Sample the immutable planet terrain plus bounded authored edits.

    The starter cove keeps its established hand-shaped field. Outside it, the
    same cell-independent function produces continent coastlines and a bounded
    continental shelf that resolves into ridges, basins and trenches.
    """
    px, pz = _safe_float(x), _safe_float(z)
    distance = math.hypot(px, pz) / world.PLANET_LAYOUT_SCALE
    if distance <= 76.0:
        height = _starter_island_height(px, pz, world_seed)
    elif distance >= 232.0:
        height = planet_contract.surface_height(px, pz, int(world_seed))
    else:
        planet_height = planet_contract.surface_height(px, pz, int(world_seed))
        legacy = _starter_island_height(px, pz, world_seed)
        blend = _smooth_unit((distance - 76.0) / (232.0 - 76.0))
        height = legacy * (1.0 - blend) + planet_height * blend
    height += _height_delta_at(
        px,
        pz,
        overrides,
        brush_stamps=brush_stamps,
        brush_index=brush_index,
    )
    return round(height, 6)


def surface_normal_at(
    x: float,
    z: float,
    world_seed: int = DEFAULT_WORLD_SEED,
    *,
    overrides: dict[str, Any] | None = None,
    brush_stamps: list[dict[str, Any]] | None = None,
    brush_index: dict[tuple[int, int], tuple[dict[str, Any], ...]] | None = None,
) -> tuple[float, float, float]:
    """Approximate a local terrain normal with two deterministic samples."""
    local_x = _safe_float(x)
    local_z = _safe_float(z)
    epsilon = 1.0
    normalized_stamps = (
        brush_stamps
        if brush_stamps is not None
        else _normalized_brush_stamps(overrides)
    )
    normalized_index = (
        brush_index
        if brush_index is not None
        else _build_brush_index(normalized_stamps)
    )
    slope_x = height_at(
        local_x + epsilon,
        local_z,
        world_seed,
        overrides=overrides,
        brush_stamps=normalized_stamps,
        brush_index=normalized_index,
    ) - height_at(
        local_x - epsilon,
        local_z,
        world_seed,
        overrides=overrides,
        brush_stamps=normalized_stamps,
        brush_index=normalized_index,
    )
    slope_z = height_at(
        local_x,
        local_z + epsilon,
        world_seed,
        overrides=overrides,
        brush_stamps=normalized_stamps,
        brush_index=normalized_index,
    ) - height_at(
        local_x,
        local_z - epsilon,
        world_seed,
        overrides=overrides,
        brush_stamps=normalized_stamps,
        brush_index=normalized_index,
    )
    normal = (-slope_x, 2.0 * epsilon, -slope_z)
    length = math.sqrt(sum(value * value for value in normal)) or 1.0
    return tuple(round(value / length, 7) for value in normal)


def _cell_samples(
    x: int,
    z: int,
    world_seed: int,
    overrides: dict[str, Any] | None = None,
    *,
    brush_stamps: list[dict[str, Any]] | None = None,
    brush_index: dict[tuple[int, int], tuple[dict[str, Any], ...]] | None = None,
) -> tuple[list[float], float, float, float, float]:
    origin_x = int(x) * CELL_SIZE
    origin_z = int(z) * CELL_SIZE
    corner_points = (
        (origin_x, origin_z),
        (origin_x + CELL_SIZE, origin_z),
        (origin_x, origin_z + CELL_SIZE),
        (origin_x + CELL_SIZE, origin_z + CELL_SIZE),
    )
    samples = [
        height_at(
            sample_x,
            sample_z,
            world_seed,
            overrides=overrides,
            brush_stamps=brush_stamps,
            brush_index=brush_index,
        )
        for sample_x, sample_z in corner_points
    ]
    center_height = height_at(
        origin_x + CELL_SIZE * 0.5,
        origin_z + CELL_SIZE * 0.5,
        world_seed,
        overrides=overrides,
        brush_stamps=brush_stamps,
        brush_index=brush_index,
    )
    minimum = min(min(samples), center_height)
    maximum = max(max(samples), center_height)
    land_fraction = sum(1 for sample in samples if sample >= SEA_LEVEL) / 4.0
    return samples, center_height, minimum, maximum, land_fraction


def _height_grid(
    x: int,
    z: int,
    world_seed: int,
    vertex_grid: int,
    overrides: dict[str, Any] | None = None,
    *,
    brush_stamps: list[dict[str, Any]] | None = None,
    brush_index: dict[tuple[int, int], tuple[dict[str, Any], ...]] | None = None,
) -> list[float]:
    """Sample one compact patch grid for the native/QML terrain geometry."""
    grid_size = max(1, int(vertex_grid))
    if grid_size < 2:
        return []
    step = CELL_SIZE / float(grid_size - 1)
    origin_x = int(x) * CELL_SIZE
    origin_z = int(z) * CELL_SIZE
    return [
        round(
            height_at(
                origin_x + column * step,
                origin_z + row * step,
                world_seed,
                overrides=overrides,
                brush_stamps=brush_stamps,
                brush_index=brush_index,
            ),
            3,
        )
        for row in range(grid_size)
        for column in range(grid_size)
    ]


def _normal_grid(
    x: int,
    z: int,
    world_seed: int,
    vertex_grid: int,
    overrides: dict[str, Any] | None = None,
    *,
    brush_stamps: list[dict[str, Any]] | None = None,
    brush_index: dict[tuple[int, int], tuple[dict[str, Any], ...]] | None = None,
) -> list[float]:
    """Sample normals from the shared field, including across cell edges.

    Computing a normal from only the vertices inside one patch makes the
    first/last column use a one-sided derivative.  That is mathematically
    close, but it can create a visible lighting seam when adjacent cells have
    different LODs.  The heightfield is already global and deterministic, so
    sample its normal at the same world positions instead.
    """
    grid_size = max(1, int(vertex_grid))
    if grid_size < 2:
        return []
    step = CELL_SIZE / float(grid_size - 1)
    origin_x = int(x) * CELL_SIZE
    origin_z = int(z) * CELL_SIZE
    values: list[float] = []
    for row in range(grid_size):
        for column in range(grid_size):
            normal = surface_normal_at(
                origin_x + column * step,
                origin_z + row * step,
                world_seed,
                overrides=overrides,
                brush_stamps=brush_stamps,
                brush_index=brush_index,
            )
            values.extend(round(component, 7) for component in normal)
    return values


def _classify_biome(
    x: int,
    z: int,
    samples: list[float],
    minimum: float,
    maximum: float,
    land_fraction: float,
    world_seed: int,
) -> str:
    if int(x) == 0 and int(z) == 0:
        return "FIRST_ISLAND"
    center_x = (int(x) + 0.5) * CELL_SIZE
    center_z = (int(z) + 0.5) * CELL_SIZE
    geography = planet_contract.region_at(center_x, center_z, world_seed)
    if maximum >= SEA_LEVEL - 0.15 and land_fraction > 0.0:
        if minimum < SEA_LEVEL + 0.85 or land_fraction < 0.75:
            return "BEACH"
        if maximum - minimum >= 1.8:
            return "CLIFF"
        if geography:
            return str(geography["biome"])
        return "LAND"
    if maximum >= SEA_LEVEL - 0.65:
        return "REEF" if cell_seed(x, z, world_seed) % 7 == 0 else "SHALLOW_WATER"
    if land_fraction > 0.0 and cell_seed(x, z, world_seed) % 11 == 0:
        return "REEF"
    if planet_contract.biome_at(center_x, center_z, world_seed) == "MAELSTROM":
        return "MAELSTROM"
    if maximum <= -650.0:
        return "ABYSS"
    return "DEEP_WATER"


def _movement_modes_for_biome(biome: str, land_fraction: float) -> list[str]:
    if biome in LAND_BIOMES:
        return ["GROUND", "FLY"]
    if biome == "SHALLOW_WATER" and land_fraction >= 0.25:
        return ["GROUND", "SWIM", "FLY"]
    return ["SWIM", "FLY"]


def _effective_biome(
    base_biome: str,
    override: dict[str, Any] | None,
    x: int,
    z: int,
    minimum: float,
    maximum: float,
) -> str:
    if not override:
        return base_biome
    explicit_biome = normalize_biome(override.get("biome"), "")
    if explicit_biome:
        return explicit_biome
    water_mode = normalize_water_mode(override.get("water_mode"), "AUTO")
    if water_mode == "LAND":
        if int(x) == 0 and int(z) == 0:
            return "FIRST_ISLAND"
        return "CLIFF" if maximum - minimum >= 1.35 else "LAND"
    if water_mode == "WATER":
        return "SHALLOW_WATER" if maximum >= SEA_LEVEL - 1.5 else "DEEP_WATER"
    return base_biome


def _brush_count_for_cell(
    overrides: dict[str, Any] | None,
    x: int,
    z: int,
) -> int:
    if not isinstance(overrides, dict):
        return 0
    stamps = overrides.get("stamps")
    if not isinstance(stamps, list):
        return 0
    count = 0
    for value in stamps[:MAX_BRUSH_STAMPS]:
        if not isinstance(value, dict):
            continue
        try:
            if int(value.get("cell_x", 0)) == int(x) and int(
                value.get("cell_z", 0)
            ) == int(z):
                count += 1
        except (TypeError, ValueError):
            continue
    return count


def cell_view(
    x: int,
    z: int,
    *,
    lod: str = "ORBIT",
    world_seed: int = DEFAULT_WORLD_SEED,
    player_position: tuple[float, float, float] = (0.0, 0.0, 0.0),
    projected_error_px: float | None = None,
    overrides: dict[str, Any] | None = None,
    brush_stamps: list[dict[str, Any]] | None = None,
    brush_index: dict[tuple[int, int], tuple[dict[str, Any], ...]] | None = None,
) -> dict[str, Any]:
    """Build the bounded render/physics view for one world cell."""
    cell_x = int(x)
    cell_z = int(z)
    normalized_lod = normalize_lod(lod)
    normalized_stamps = (
        brush_stamps
        if brush_stamps is not None
        else _normalized_brush_stamps(overrides)
    )
    normalized_index = (
        brush_index
        if brush_index is not None
        else _build_brush_index(normalized_stamps)
    )
    samples, center_height, minimum, maximum, land_fraction = _cell_samples(
        cell_x,
        cell_z,
        int(world_seed),
        overrides,
        brush_stamps=normalized_stamps,
        brush_index=normalized_index,
    )
    geometry = dict(_LOD_GEOMETRY[normalized_lod])
    vertex_grid = int(geometry.get("vertex_grid", 1))
    height_grid = _height_grid(
        cell_x,
        cell_z,
        int(world_seed),
        vertex_grid,
        overrides,
        brush_stamps=normalized_stamps,
        brush_index=normalized_index,
    )
    normal_grid = _normal_grid(
        cell_x,
        cell_z,
        int(world_seed),
        vertex_grid,
        overrides,
        brush_stamps=normalized_stamps,
        brush_index=normalized_index,
    )
    if height_grid:
        minimum = min(minimum, min(height_grid))
        maximum = max(maximum, max(height_grid))
        land_fraction = sum(
            1 for sample in height_grid if sample >= SEA_LEVEL
        ) / float(len(height_grid))
    base_biome = _classify_biome(
        cell_x,
        cell_z,
        samples,
        minimum,
        maximum,
        land_fraction,
        int(world_seed),
    )
    cell_override = override_for(overrides, cell_x, cell_z)
    brush_count = _brush_count_for_cell(overrides, cell_x, cell_z)
    biome = _effective_biome(
        base_biome,
        cell_override,
        cell_x,
        cell_z,
        minimum,
        maximum,
    )
    origin_x = cell_x * CELL_SIZE
    origin_z = cell_z * CELL_SIZE
    center_x = origin_x + CELL_SIZE * 0.5
    center_z = origin_z + CELL_SIZE * 0.5
    player_x = _safe_float(player_position[0])
    player_z = _safe_float(player_position[2])
    distance = math.hypot(center_x - player_x, center_z - player_z)
    screen_error = (
        _safe_float(projected_error_px)
        if projected_error_px is not None
        else 64.0 / max(1.0, distance * distance)
    )
    region = planet_contract.region_at(center_x, center_z, int(world_seed))
    water_cell = biome in WATER_BIOMES
    surface_kind = "WATER" if water_cell else "LAND"

    if normalized_lod == "NEAR":
        simulation_policy = "FULL"
    elif normalized_lod == "MID":
        simulation_policy = "ACTORS_AND_PORTS"
    else:
        simulation_policy = "NO_LOCAL_PHYSICS"

    return {
        "key": world.cell_key(cell_x, cell_z),
        "level": 0,
        "x": cell_x,
        "z": cell_z,
        "lod": normalized_lod,
        "seed": cell_seed(cell_x, cell_z, int(world_seed)),
        "biome": biome,
        "region_id": str(region["id"]) if region else (
            "THE_MAELSTROM" if biome == "MAELSTROM" else "OCEAN"
        ),
        "surface": surface_kind,
        "center_m": {
            "x": round(center_x, 3),
            "y": round(center_height, 3),
            "z": round(center_z, 3),
        },
        "bounds_m": {
            "min_x": round(origin_x, 3),
            "max_x": round(origin_x + CELL_SIZE, 3),
            "min_z": round(origin_z, 3),
            "max_z": round(origin_z + CELL_SIZE, 3),
            "min_y": round(minimum, 3),
            "max_y": round(maximum, 3),
        },
        "height_samples_m": [round(value, 3) for value in samples],
        "height_grid_m": height_grid,
        "normal_grid": normal_grid,
        "surface_height_m": round(center_height, 3),
        "water_depth_m": round(max(0.0, SEA_LEVEL - center_height), 3),
        "land_fraction": round(land_fraction, 3),
        "movement_modes": _movement_modes_for_biome(biome, land_fraction),
        "authoring": {
            "overridden": cell_override is not None,
            "brush_count": brush_count,
            "height_delta_m": round(
                float(cell_override["height_delta_m"]) if cell_override else 0.0,
                3,
            ),
            "biome": str(cell_override["biome"]) if cell_override else "",
            "water_mode": (
                str(cell_override["water_mode"]) if cell_override else "AUTO"
            ),
        },
        "geometry": geometry,
        "visibility": {
            "loaded": True,
            "candidate": True,
            "render": True,
            "simulation": simulation_policy,
            "physics": normalized_lod in {"NEAR", "MID"},
            "shadow_caster": normalized_lod in {"NEAR", "MID"},
            "source": "CELL_INTEREST_RADIUS",
            "occlusion": "NATIVE_RENDERER_LATER",
            "distance_m": round(distance, 3),
            "screen_error_px": round(screen_error, 4),
        },
        "ports": {
            "north": "SEAMLESS_CELL_EDGE",
            "south": "SEAMLESS_CELL_EDGE",
            "east": "SEAMLESS_CELL_EDGE",
            "west": "SEAMLESS_CELL_EDGE",
            "water_surface": True,
            "air_column": True,
        },
    }


def build_terrain_view(
    loaded_cells: list[dict[str, Any]],
    player_position: tuple[float, float, float],
    movement_mode: str = "GROUND",
    *,
    world_seed: int = DEFAULT_WORLD_SEED,
    overrides: dict[str, Any] | None = None,
    cell_cache: dict[tuple[Any, ...], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the compact terrain contract for the current interest set.

    Cell height/normal fields are immutable for a given seed, LOD and terrain
    authoring revision.  The optional bounded cache reuses those fields while
    this function still refreshes player-relative distance, screen error and
    the current surface every call.  Rendering therefore avoids rebuilding
    all streamed geometry during ordinary movement without changing the
    authoritative terrain contract.
    """
    player_x = _safe_float(player_position[0])
    player_y = _safe_float(player_position[1])
    player_z = _safe_float(player_position[2])
    mode = world.normalize_movement_mode(movement_mode)
    safe_seed = int(world_seed)
    brush_stamps = _normalized_brush_stamps(overrides)
    brush_index = _build_brush_index(brush_stamps)

    cells: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for row in list(loaded_cells or []):
        if not isinstance(row, dict):
            continue
        try:
            cell_x = int(row.get("x", 0))
            cell_z = int(row.get("z", 0))
        except (TypeError, ValueError):
            continue
        key = world.cell_key(cell_x, cell_z)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        lod = normalize_lod(row.get("lod"), "ORBIT")
        projected_error = row.get("projected_error_px")
        cache_key = (
            cell_x,
            cell_z,
            lod,
            planet_contract.MAP_REVISION,
            safe_seed,
            int(_safe_float((overrides or {}).get("revision"), 0.0))
            if isinstance(overrides, dict)
            else 0,
        )
        cached = cell_cache.get(cache_key) if isinstance(cell_cache, dict) else None
        if isinstance(cached, dict):
            cell = dict(cached)
            visibility = dict(cached.get("visibility", {}))
            origin_x = cell_x * CELL_SIZE
            origin_z = cell_z * CELL_SIZE
            center_x = origin_x + CELL_SIZE * 0.5
            center_z = origin_z + CELL_SIZE * 0.5
            distance = math.hypot(center_x - player_x, center_z - player_z)
            screen_error = (
                _safe_float(projected_error)
                if projected_error is not None
                else 64.0 / max(1.0, distance * distance)
            )
            visibility["distance_m"] = round(distance, 3)
            visibility["screen_error_px"] = round(screen_error, 4)
            cell["visibility"] = visibility
        else:
            cell = cell_view(
                cell_x,
                cell_z,
                lod=lod,
                world_seed=safe_seed,
                player_position=(player_x, player_y, player_z),
                projected_error_px=(
                    _safe_float(projected_error)
                    if projected_error is not None
                    else None
                ),
                overrides=overrides,
                brush_stamps=brush_stamps,
                brush_index=brush_index,
            )
            if isinstance(cell_cache, dict):
                if len(cell_cache) >= 512:
                    cell_cache.clear()
                cell_cache[cache_key] = dict(cell)
        cells.append(cell)
        if len(cells) >= MAX_TERRAIN_CELLS:
            break

    player_cell_x = world.chunk_coord(player_x)
    player_cell_z = world.chunk_coord(player_z)
    player_key = world.cell_key(player_cell_x, player_cell_z)
    player_cell = next((row for row in cells if row["key"] == player_key), None)
    if player_cell is None:
        cache_key = (
            player_cell_x,
            player_cell_z,
            "NEAR",
            planet_contract.MAP_REVISION,
            safe_seed,
            int(_safe_float((overrides or {}).get("revision"), 0.0))
            if isinstance(overrides, dict)
            else 0,
        )
        cached = cell_cache.get(cache_key) if isinstance(cell_cache, dict) else None
        if isinstance(cached, dict):
            player_cell = dict(cached)
        else:
            player_cell = cell_view(
                player_cell_x,
                player_cell_z,
                lod="NEAR",
                world_seed=safe_seed,
                player_position=(player_x, player_y, player_z),
                overrides=overrides,
                brush_stamps=brush_stamps,
                brush_index=brush_index,
            )
            if isinstance(cell_cache, dict):
                if len(cell_cache) >= 512:
                    cell_cache.clear()
                cell_cache[cache_key] = dict(player_cell)

    surface_height = height_at(
        player_x,
        player_z,
        safe_seed,
        overrides=overrides,
        brush_stamps=brush_stamps,
        brush_index=brush_index,
    )
    water_depth = max(0.0, SEA_LEVEL - surface_height)
    if mode == "FLY":
        medium = "AIR"
    elif mode == "SWIM":
        medium = "WATER"
    elif surface_height < SEA_LEVEL and player_y <= SEA_LEVEL + 1.5:
        medium = "WATER"
    else:
        medium = "LAND"

    lod_counts: dict[str, int] = {}
    biome_counts: dict[str, int] = {}
    simulation_count = 0
    render_triangles = 0
    for row in cells:
        lod_name = str(row["lod"])
        biome_name = str(row["biome"])
        lod_counts[lod_name] = lod_counts.get(lod_name, 0) + 1
        biome_counts[biome_name] = biome_counts.get(biome_name, 0) + 1
        render_triangles += int(row["geometry"].get("triangles", 0))
        if row["visibility"]["physics"]:
            simulation_count += 1

    normal = surface_normal_at(
        player_x,
        player_z,
        safe_seed,
        overrides=overrides,
        brush_stamps=brush_stamps,
        brush_index=brush_index,
    )
    authoring_view = summary(overrides or new_overrides())
    return {
        "schema": SCHEMA,
        "world_seed": safe_seed,
        "coordinate_frame": "LOCAL_TANGENT_PATCH_METRES",
        "terrain_model": "SEEDED_CONTINENTS_WITH_STATIC_BATHYMETRY",
        "planet": planet_contract.map_contract(safe_seed),
        "water": {
            "sea_level_m": SEA_LEVEL,
            "surface_representation": "CELL_STREAMED_SHARED_SEA_LEVEL",
            "continuity": "SEAMLESS_CELL_EDGES",
            "zone_boundary": False,
            "depth_model": "SEA_LEVEL_MINUS_TERRAIN_HEIGHT",
            "bathymetry": "SEEDED_CONTINENTAL_SHELF_RIDGES_AND_ABYSSAL_TRENCHES",
            "underwater_representation": "SAME_WORLD_CELLS",
        },
        "authoring": authoring_view,
        "streaming": {
            "policy": "INVISIBLE_INTEREST_CELLS",
            "loaded_count": len(cells),
            "capacity": MAX_TERRAIN_CELLS,
            "render_candidates": len(cells),
            "simulation_cells": simulation_count,
            "render_triangles": render_triangles,
            "lod_counts": dict(sorted(lod_counts.items())),
            "biome_counts": dict(sorted(biome_counts.items())),
        },
        "player_cell": {
            "key": player_key,
            "x": player_cell_x,
            "z": player_cell_z,
            "biome": player_cell["biome"],
            "region_id": player_cell.get("region_id", ""),
            "lod": player_cell["lod"],
        },
        "player_surface": {
            "height_m": round(surface_height, 3),
            "water_depth_m": round(water_depth, 3),
            "biome": player_cell["biome"],
            "medium": medium,
            "movement_mode": mode,
            "normal": {
                "x": normal[0],
                "y": normal[1],
                "z": normal[2],
            },
        },
        "transition": {
            "seamless": True,
            "zone_boundary": False,
            "land_water_air": "ONE_MOVEMENT_AND_CELL_CONTRACT",
            "land_to_water": "SHARED_SEA_LEVEL_WITH_MODE_CHANGE",
            "water_to_air": "SHARED_CELL_AIR_COLUMN",
            "air_to_land": "SURFACE_HEIGHTFIELD_TARGET",
            "preview_control": "EXPLICIT_MOVEMENT_MODE",
        },
        "cells": cells,
    }
