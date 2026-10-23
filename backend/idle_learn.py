"""Bounded idle curriculum over the unique-source catalog.

This is SELFDEV's cheap next round, not a second agent brain. While the
desktop is up and chat is quiet, a host timer feeds compact file lessons
into long_memory. It never grants authority, never touches the network,
and never writes repository source.
"""

from __future__ import annotations

from backend.application_paths import HOME, WORKSPACE_ROOT

import json
import os
from pathlib import Path
from typing import Any

from backend import long_memory


SCHEMA = "gg.idle-learn.v1"
ACTION_AUTHORITY = "NONE"
PROMOTION_AUTHORITY = "NONE"
CANONICAL_POLICY_CHANGE = False
PARALLEL_AGENT_BRAIN = "FORBIDDEN"
FILES_PER_TICK = 3
CONSOLIDATE_EVERY = 8
CATALOG_NAME = "UNIQUE-SOURCE-CATALOG.json"
CURSOR_NAME = "idle-learn-cursor.json"
SKIP_SUFFIX = frozenset(
    {".min.js", ".lock.json", ".png", ".jpg", ".gguf", ".zip"}
)
SKIP_NAME = frozenset({"maplibre-gl.js", "xterm.min.js", "lightweight-charts.min.js"})


def _tree(tree_root: Path | None = None) -> Path:
    return Path(tree_root) if tree_root is not None else long_memory.TREE_ROOT


def _catalog_path(root: Path) -> Path:
    return root / CATALOG_NAME


def _cursor_path(root: Path) -> Path:
    return root / CURSOR_NAME


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _skip(row: dict[str, Any]) -> bool:
    path = str(row.get("path") or "")
    name = Path(path).name
    if name in SKIP_NAME:
        return True
    lower = path.lower()
    return any(lower.endswith(suffix) for suffix in SKIP_SUFFIX)


def _statement(row: dict[str, Any]) -> str:
    path = str(row.get("path") or "")
    short = path.replace(str(WORKSPACE_ROOT), "").replace(str(HOME), "")
    doc = str(row.get("doc") or "").strip()
    names = [
        str(item.get("name") or "")
        for item in (row.get("symbols") or [])[:6]
        if isinstance(item, dict)
    ]
    bits = [short]
    if doc:
        bits.append(doc)
    if names:
        bits.append("symbols " + ", ".join(names))
    return long_memory._compact(" · ".join(bits), long_memory.MAX_STATEMENT)


def status(*, tree_root: Path | None = None) -> dict[str, Any]:
    root = _tree(tree_root)
    catalog = _load_json(_catalog_path(root))
    cursor = _load_json(_cursor_path(root))
    files = catalog.get("files") if isinstance(catalog.get("files"), list) else []
    return {
        "schema": SCHEMA,
        "status": "READY" if files else "CATALOG_MISSING",
        "files": len(files),
        "cursor": int(cursor.get("index") or 0),
        "seen": len(cursor.get("seen") or []),
        "ticks": int(cursor.get("ticks") or 0),
        "action_authority": ACTION_AUTHORITY,
        "parallel_agent_brain": PARALLEL_AGENT_BRAIN,
        "canonical_policy_change": CANONICAL_POLICY_CHANGE,
    }


def tick(
    *,
    tree_root: Path | None = None,
    limit: int = FILES_PER_TICK,
) -> dict[str, Any]:
    """Learn the next few unique source files. Safe to call from a host timer."""
    try:
        cap = max(1, min(int(limit), 8))
    except (TypeError, ValueError):
        cap = FILES_PER_TICK
    root = _tree(tree_root)
    catalog = _load_json(_catalog_path(root))
    files = catalog.get("files")
    if not isinstance(files, list) or not files:
        return {
            "schema": SCHEMA,
            "status": "SKIPPED",
            "reason": "CATALOG_MISSING",
            "action_authority": ACTION_AUTHORITY,
            "parallel_agent_brain": PARALLEL_AGENT_BRAIN,
        }

    cursor = _load_json(_cursor_path(root))
    seen = set(cursor.get("seen") or [])
    index = int(cursor.get("index") or 0)
    ticks = int(cursor.get("ticks") or 0)
    learned: list[str] = []
    scanned = 0
    while len(learned) < cap and scanned < len(files):
        if index >= len(files):
            index = 0
        row = files[index]
        index += 1
        scanned += 1
        if not isinstance(row, dict) or _skip(row):
            continue
        sha16 = str(row.get("sha16") or "")
        if sha16 and sha16 in seen:
            continue
        note = _statement(row)
        if len(note) < long_memory.MIN_QUERY:
            continue
        query = "house file " + Path(str(row.get("path") or "file")).name
        recorded = long_memory.capture(
            query,
            motor="SHARED",
            kind="semantic",
            note=note,
            tree_root=root,
            force=True,
        )
        if recorded.get("status") != "RECORDED":
            continue
        if sha16:
            seen.add(sha16)
        learned.append(note[:80])
        if len(seen) > 800:
            seen = set(list(seen)[-600:])

    ticks += 1
    _write_json(
        _cursor_path(root),
        {
            "schema": SCHEMA,
            "index": index,
            "seen": sorted(seen)[-800:],
            "ticks": ticks,
        },
    )
    consolidated = False
    if ticks % CONSOLIDATE_EVERY == 0 and learned:
        long_memory.consolidate(tree_root=root)
        consolidated = True
    return {
        "schema": SCHEMA,
        "status": "LEARNED" if learned else "IDLE",
        "learned": len(learned),
        "cursor": index,
        "ticks": ticks,
        "consolidated": consolidated,
        "action_authority": ACTION_AUTHORITY,
        "promotion_authority": PROMOTION_AUTHORITY,
        "canonical_policy_change": CANONICAL_POLICY_CHANGE,
        "parallel_agent_brain": PARALLEL_AGENT_BRAIN,
        "model_inference": False,
        "network": "NONE",
    }
