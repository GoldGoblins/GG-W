"""Declarative raster scenes with exact page citations and immutable images."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import uuid

from PIL import Image

from backend.application_paths import STATE_ROOT
from backend import knowledge_atlas
from backend.platform_files import is_link

SCHEMA = "gg.knowledge-scene.v1"
MAX_SCENES = 100
MAX_HOTSPOTS = 64
MAX_PIXELS = 24_000_000


def _root(root=None) -> Path:
    path = Path(root) if root is not None else STATE_ROOT / "knowledge-atlas"
    if is_link(path) or is_link(path / "scenes"):
        raise ValueError("LINKED_STORE_NOT_ALLOWED")
    return path


def _text(value, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit or "\x00" in value:
        raise ValueError("SCENE_TEXT_INVALID")
    return value.strip()


def _citation(raw: dict, root=None) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("CITATION_INVALID")
    source_id = _text(raw.get("source_id"), 160)
    page = raw.get("page")
    if type(page) is not int or not 1 <= page <= 1000:
        raise ValueError("CITATION_PAGE_INVALID")
    quote = _text(raw.get("quote"), 4000)
    source = knowledge_atlas.source_page(source_id, page, root=root)
    if source.get("status") != "PAGE_TEXT":
        raise ValueError("CITATION_SOURCE_NOT_FOUND")
    if raw.get("revision") and raw["revision"] != source.get("revision"):
        raise ValueError("CITATION_SOURCE_CHANGED")
    normalize = lambda text: " ".join(str(text).split()).casefold()
    if normalize(quote) not in normalize(source.get("text", "")):
        raise ValueError("CITATION_QUOTE_NOT_ON_PAGE")
    return {"source_id": source_id, "source_title": source["source_title"], "page": page,
            "quote": quote, "revision": source.get("revision", "")}


def publish(payload: dict, *, root=None) -> dict:
    """Copy an explicitly selected raster and validate every sourced hotspot.

    This validates citation identity, not whether an illustration accurately
    depicts a physical object. That distinction remains visible in the UI.
    """
    try:
        if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
            raise ValueError("SCENE_SCHEMA_INVALID")
        title = _text(payload.get("title"), 160)
        image_path = Path(_text(payload.get("image_path"), 4096)).expanduser()
        if image_path.is_symlink() or not image_path.is_file():
            raise ValueError("SCENE_IMAGE_MISSING")
        if image_path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise ValueError("SCENE_IMAGE_FORMAT_INVALID")
        if image_path.stat().st_size > 32 * 1024 * 1024:
            raise ValueError("SCENE_IMAGE_TOO_LARGE")
        with Image.open(image_path) as picture:
            if picture.width * picture.height > MAX_PIXELS or picture.width < 32 or picture.height < 32:
                raise ValueError("SCENE_IMAGE_SIZE_INVALID")
            picture.verify()
        illustrative = payload.get("illustrative") is True
        rows = payload.get("hotspots")
        if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_HOTSPOTS:
            raise ValueError("SCENE_HOTSPOTS_REQUIRED")
        hotspots, used = [], set()
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise ValueError("HOTSPOT_INVALID")
            label = _text(row.get("label"), 120)
            key = str(row.get("id") or "part-" + str(index + 1))
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", key) or key in used:
                raise ValueError("HOTSPOT_ID_INVALID")
            used.add(key)
            x, y = row.get("x"), row.get("y")
            if any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in (x, y)):
                raise ValueError("HOTSPOT_POSITION_INVALID")
            citations = row.get("citations", [])
            if not isinstance(citations, list) or len(citations) > 8:
                raise ValueError("CITATION_LIST_INVALID")
            if not illustrative and not citations:
                raise ValueError("SOURCED_HOTSPOT_NEEDS_CITATION")
            checked = [_citation(citation, root) for citation in citations]
            hotspots.append({"id": key, "label": label, "x": x, "y": y,
                             "summary": _text(row.get("summary"), 2000), "citations": checked,
                             "node_id": checked[0]["source_id"] if checked else ""})
        folder = _root(root) / "scenes"
        folder.mkdir(parents=True, exist_ok=True)
        existing = list(folder.glob("*.json"))
        if len(existing) >= MAX_SCENES:
            raise ValueError("SCENE_LIBRARY_FULL")
        image_bytes = image_path.read_bytes()
        digest = hashlib.sha256(image_bytes).hexdigest()
        asset = folder / (digest + image_path.suffix.lower())
        if not asset.exists():
            temp_asset = folder / (uuid.uuid4().hex + ".tmp")
            temp_asset.write_bytes(image_bytes)
            temp_asset.replace(asset)
        scene_id = "scene-" + uuid.uuid4().hex
        scene = {"schema": SCHEMA, "id": scene_id, "title": title,
                 "image_url": asset.resolve().as_uri(), "illustrative": illustrative,
                 "hotspots": hotspots, "model_calls": 0}
        destination = folder / (scene_id + ".json")
        temporary = destination.with_suffix(".new")
        temporary.write_text(json.dumps(scene, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        temporary.replace(destination)
        return {"status": "SCENE_PUBLISHED", "scene_id": scene_id, "hotspots": len(hotspots)}
    except (OSError, ValueError, TypeError, SyntaxError, Image.DecompressionBombError) as exc:
        return {"status": "ERROR", "reason": str(exc) if isinstance(exc, ValueError) else type(exc).__name__}


def read(scene_id: str, *, root=None) -> dict:
    if not re.fullmatch(r"scene-[0-9a-f]{32}", str(scene_id)):
        return {"status": "ERROR", "reason": "SCENE_NOT_FOUND"}
    try:
        path = _root(root) / "scenes" / (scene_id + ".json")
        if path.is_symlink() or path.stat().st_size > 1_000_000:
            raise ValueError("SCENE_INVALID")
        scene = json.loads(path.read_text(encoding="utf-8"))
        stale = False
        for hotspot in scene["hotspots"]:
            for citation in hotspot.get("citations", []):
                try:
                    _citation(citation, root)
                except ValueError:
                    stale = True
        scene["stale"] = stale
        if stale:
            scene["notice"] = "Källmaterialet har ändrats. Kontrollera bildens hänvisningar på nytt."
        return {"status": "SCENE_READY", "scene": scene}
    except (OSError, ValueError, TypeError, KeyError):
        return {"status": "ERROR", "reason": "SCENE_NOT_FOUND"}


def list_scenes(*, root=None) -> list[dict]:
    try:
        folder = _root(root) / "scenes"
    except ValueError:
        return []
    rows = []
    for path in sorted(folder.glob("scene-*.json"))[:MAX_SCENES]:
        try:
            if path.is_symlink() or path.stat().st_size > 1_000_000:
                continue
            scene = json.loads(path.read_text(encoding="utf-8"))
            rows.append({"id": scene["id"], "title": scene["title"],
                         "illustrative": scene["illustrative"], "hotspot_count": len(scene["hotspots"])})
        except (OSError, ValueError, TypeError, KeyError):
            continue
    return rows
