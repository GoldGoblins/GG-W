from __future__ import annotations

from typing import Any

from backend.media_contract import which_first


SCHEMA = "gg.ai-desktop.draw-status.v1"
EDITORS: tuple[dict[str, Any], ...] = (
    {
        "id": "krita",
        "label": "KRITA",
        "kind": "paint",
        "detail": "Raster paint. Closest local Photoshop/painting desk.",
        "bins": ("krita",),
        "tokens": ("krita",),
    },
    {
        "id": "gimp",
        "label": "GIMP",
        "kind": "photo",
        "detail": "Photo composite. Local Photoshop-class raster editor.",
        "bins": ("gimp",),
        "tokens": ("gimp",),
    },
    {
        "id": "inkscape",
        "label": "INKSCAPE",
        "kind": "vector",
        "detail": "SVG vectors. Local Illustrator-class drawing.",
        "bins": ("inkscape",),
        "tokens": ("inkscape",),
    },
    {
        "id": "darktable",
        "label": "DARKTABLE",
        "kind": "raw",
        "detail": "RAW develop. Local Lightroom-class darkroom.",
        "bins": ("darktable",),
        "tokens": ("darktable",),
    },
    {
        "id": "kolourpaint",
        "label": "KOLOURPAINT",
        "kind": "paint",
        "detail": "Simple bitmap paint. Installed KDE editor.",
        "bins": ("kolourpaint",),
        "tokens": ("kolourpaint",),
    },
)


def probe_editor(spec: dict[str, Any]) -> dict[str, Any]:
    path = which_first(tuple(spec["bins"]))
    return {
        "id": spec["id"],
        "label": spec["label"],
        "kind": spec["kind"],
        "detail": spec["detail"],
        "present": bool(path),
        "path": path,
        "tokens": list(spec["tokens"]),
    }


def probe_editors() -> list[dict[str, Any]]:
    return [probe_editor(spec) for spec in EDITORS]


def editor_by_id(editor_id: str) -> dict[str, Any] | None:
    wanted = str(editor_id or "").strip().lower()
    for spec in EDITORS:
        if spec["id"] == wanted:
            row = probe_editor(spec)
            if row["present"]:
                return row
            return None
    return None


def default_editor_id() -> str:
    for row in probe_editors():
        if row["present"]:
            return str(row["id"])
    return "sketch"


def status_payload() -> dict[str, Any]:
    rows = probe_editors()
    chosen = default_editor_id()
    return {
        "schema": SCHEMA,
        "editors": rows,
        "default": chosen,
        "sketch": True,
    }
