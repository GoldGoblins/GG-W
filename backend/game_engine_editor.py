"""Bounded, data-only scene editing primitives for the GAME ENGINE preview.

The editor is intentionally a document operation layer.  It does not know
about QtQuick3D or the simulation entity pool, which means the same commands
can later be driven by a developer tool, a player-facing builder or a packed
server-side content compiler.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


SCHEMA = "gg.game-engine.editor.v1"
EDITOR_VERSION = 1
MAX_PLACEMENTS = 128
MAX_ESTIMATED_TRIANGLES = 8192
EDITOR_KINDS = ("PROP", "RAMP", "LIGHT", "SPAWN", "NPC")


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number == number and abs(number) != float("inf") else default


def _vector(value: Any, default: tuple[float, float, float]) -> tuple[float, float, float]:
    if isinstance(value, dict):
        values = (value.get("x"), value.get("y"), value.get("z"))
    elif isinstance(value, (list, tuple)) and len(value) >= 3:
        values = (value[0], value[1], value[2])
    else:
        return default
    return tuple(_safe_float(item, fallback) for item, fallback in zip(values, default))


def normalize_kind(value: Any, default: str = "PROP") -> str:
    kind = str(value or default).upper()
    return kind if kind in EDITOR_KINDS else default


def new_document() -> dict[str, Any]:
    """Return an isolated, versioned editor document."""
    return {
        "schema": SCHEMA,
        "version": EDITOR_VERSION,
        "revision": 0,
        "placements": [],
        "undo_depth": 0,
        "last_action": "RESET",
    }


def _placement_cost(kind: str) -> int:
    return {
        "PROP": 12,
        "RAMP": 24,
        "LIGHT": 6,
        "SPAWN": 4,
        "NPC": 20,
    }.get(kind, 12)


def _estimated_triangles(document: dict[str, Any]) -> int:
    return sum(_placement_cost(normalize_kind(row.get("kind"))) for row in document.get("placements", []))


def place(
    document: dict[str, Any],
    kind: str,
    position: Any,
    scale: Any = (1.0, 1.0, 1.0),
    color: str = "#8fa8a0",
    *,
    entity_id: str = "",
) -> tuple[bool, dict[str, Any]]:
    """Place one bounded object and return a command result."""
    placements = document.get("placements")
    if not isinstance(placements, list):
        return False, {"error": "EDITOR_DOCUMENT_INVALID"}
    if len(placements) >= MAX_PLACEMENTS:
        return False, {"error": "EDITOR_PLACEMENT_BUDGET"}
    normalized = normalize_kind(kind, "")
    if not normalized:
        return False, {"error": "EDITOR_KIND_INVALID", "allowed": list(EDITOR_KINDS)}
    if _estimated_triangles(document) + _placement_cost(normalized) > MAX_ESTIMATED_TRIANGLES:
        return False, {"error": "EDITOR_TRIANGLE_BUDGET"}

    document["revision"] = int(document.get("revision", 0)) + 1
    placement_id = f"placement-{document['revision']:04d}"
    px, py, pz = _vector(position, (0.0, 0.65, 0.0))
    sx, sy, sz = _vector(scale, (1.0, 1.0, 1.0))
    row = {
        "id": placement_id,
        "kind": normalized,
        "x": px,
        "y": py,
        "z": pz,
        "sx": max(0.05, min(12.0, abs(sx))),
        "sy": max(0.05, min(12.0, abs(sy))),
        "sz": max(0.05, min(12.0, abs(sz))),
        "color": str(color or "#8fa8a0")[:16],
        "entity_id": str(entity_id or ""),
    }
    placements.append(row)
    document["undo_depth"] = len(placements)
    document["last_action"] = "PLACE"
    return True, {"placement": deepcopy(row)}


def attach_entity(document: dict[str, Any], placement_id: str, entity_id: str) -> bool:
    """Attach a runtime entity handle without coupling the document to it."""
    wanted = str(placement_id)
    for row in document.get("placements", []):
        if isinstance(row, dict) and str(row.get("id")) == wanted:
            row["entity_id"] = str(entity_id or "")
            return True
    return False


def undo(document: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    """Undo the latest placement; editor history is bounded by the document."""
    placements = document.get("placements")
    if not isinstance(placements, list) or not placements:
        return False, {"error": "EDITOR_UNDO_EMPTY"}
    row = deepcopy(placements.pop())
    document["revision"] = int(document.get("revision", 0)) + 1
    document["undo_depth"] = len(placements)
    document["last_action"] = "UNDO"
    return True, {"placement": row}


def summary(document: dict[str, Any]) -> dict[str, Any]:
    """Return a compact inspector-safe representation of the document."""
    placements = document.get("placements", [])
    if not isinstance(placements, list):
        placements = []
    counts = {kind: 0 for kind in EDITOR_KINDS}
    for row in placements:
        if isinstance(row, dict):
            kind = normalize_kind(row.get("kind"))
            counts[kind] = counts.get(kind, 0) + 1
    return {
        "schema": str(document.get("schema", SCHEMA)),
        "version": int(document.get("version", EDITOR_VERSION)),
        "revision": int(document.get("revision", 0)),
        "placements": deepcopy(placements[-MAX_PLACEMENTS:]),
        "placement_count": len(placements),
        "by_kind": counts,
        "undo_depth": len(placements),
        "last_action": str(document.get("last_action", "")),
        "budget": {
            "placements": MAX_PLACEMENTS,
            "estimated_triangles": MAX_ESTIMATED_TRIANGLES,
            "used_estimated_triangles": _estimated_triangles(document),
        },
        "authoring": "DEVELOPER_OR_USER_COMMANDS_SHARE_DOCUMENT",
    }


def clone_document(document: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(document)
