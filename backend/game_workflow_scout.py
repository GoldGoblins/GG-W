"""Incremental asset discovery, lexical retrieval and immutable visual evidence.

Workflow ideas: Dryxio/gta-scout (MIT). This implementation uses GG's own schema
and format adapters, and requires neither GTA data nor embedding downloads.
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import re
import sqlite3
import struct
import time

from backend import game_workflow_common as common, game_workflow_formats as formats
from backend import game_workflow_dependencies as dependencies

MAX_FILES = 2048
MAX_CATALOG = 8192
MAX_COLLECTIONS = 64
MAX_TOTAL_ROWS = MAX_CATALOG * MAX_COLLECTIONS
MAX_SCAN = 12000
MAX_SCAN_BYTES = 256 * 1024 * 1024
SKIP_DIRS = {".git", ".ssh", ".aws", ".config", "node_modules", "__pycache__", "target", ".venv"}
LEXICON = {"textur": "texture", "modell": "model", "figur": "character", "karaktär": "character",
           "träd": "tree", "hus": "house", "väg": "road", "vapen": "weapon", "rustning": "armor"}


def _db():
    common.ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = common.ROOT / "catalog.sqlite3"
    if path.is_symlink() or (path.exists() and path.stat().st_size > 256 * 1024 * 1024):
        raise ValueError("CATALOG_STORAGE_LIMIT")
    db = sqlite3.connect(path, timeout=5)
    db.row_factory = sqlite3.Row
    page_size = db.execute("PRAGMA page_size").fetchone()[0]
    db.execute("PRAGMA max_page_count=" + str(256 * 1024 * 1024 // page_size))
    db.executescript("""
      CREATE TABLE IF NOT EXISTS assets (
        key TEXT PRIMARY KEY, root TEXT NOT NULL, relative TEXT NOT NULL, game TEXT NOT NULL,
        hash TEXT NOT NULL, bytes INTEGER NOT NULL, format TEXT NOT NULL, kind TEXT NOT NULL,
        coverage TEXT NOT NULL, observation TEXT NOT NULL);
      CREATE INDEX IF NOT EXISTS assets_root ON assets(root);
      CREATE INDEX IF NOT EXISTS assets_hash ON assets(hash);
      CREATE TABLE IF NOT EXISTS annotations (key TEXT PRIMARY KEY, hash TEXT NOT NULL, tags TEXT NOT NULL, note TEXT NOT NULL);
      CREATE VIRTUAL TABLE IF NOT EXISTS asset_search USING fts5(key UNINDEXED, text, tokenize='unicode61');
      CREATE TABLE IF NOT EXISTS asset_search_keys (key TEXT PRIMARY KEY, search_rowid INTEGER NOT NULL UNIQUE);
      CREATE TABLE IF NOT EXISTS index_sessions (id TEXT PRIMARY KEY, root TEXT NOT NULL, game TEXT NOT NULL,
        manifest TEXT NOT NULL, position INTEGER NOT NULL, created REAL NOT NULL);
      CREATE TABLE IF NOT EXISTS staged_assets (session TEXT NOT NULL, key TEXT NOT NULL, row TEXT NOT NULL,
        PRIMARY KEY(session,key));
      CREATE TABLE IF NOT EXISTS asset_links (key TEXT NOT NULL, target TEXT NOT NULL, hash TEXT NOT NULL, role TEXT NOT NULL,
        PRIMARY KEY(key,target,role));
      CREATE INDEX IF NOT EXISTS asset_links_target ON asset_links(target);
    """)
    if "collection" not in {r[1] for r in db.execute("PRAGMA table_info(assets)")}:
        db.execute("ALTER TABLE assets ADD COLUMN collection TEXT NOT NULL DEFAULT ''")
        db.execute("UPDATE assets SET collection=root WHERE collection=''")
        db.commit()
    if db.execute("SELECT COUNT(*) FROM asset_search_keys").fetchone()[0] == 0:
        db.execute("INSERT OR REPLACE INTO asset_search_keys SELECT key,rowid FROM asset_search")
        db.commit()
    return db


def _key(root, relative):
    return common.digest((str(root) + "\0" + relative).encode())[:32]


def _text(row, annotation=None):
    observation = json.loads(row["observation"])
    names = observation.get("metadata", {}).get("names", [])
    metadata = observation.get("metadata", {})
    categories = []
    if metadata.get("skins", 0) or metadata.get("skin_controllers", 0):
        categories.extend(("rig", "rigg", "skeleton", "skin", "weights", "joints"))
    if metadata.get("coincident_material_layers", 0):
        categories.extend(("material_layers", "coincident_faces"))
    categories.extend(str(a) for a in metadata.get("attributes", []))
    extra = " ".join((annotation["tags"], annotation["note"])) if annotation and annotation["hash"] == observation.get("identity", row["hash"]) else ""
    return " ".join((row["relative"], row["game"], row["format"], row["kind"], *names, *categories, extra)).replace("_", " ").replace("-", " ")


def _reindex(db, row):
    # FTS5 key is UNINDEXED. Deleting by it scans every document for each row,
    # turning a corpus refresh into quadratic work. Keep a normal indexed map.
    previous = db.execute("SELECT search_rowid FROM asset_search_keys WHERE key=?", (row["key"],)).fetchone()
    if previous:
        db.execute("DELETE FROM asset_search WHERE rowid=?", (previous[0],))
    annotation = db.execute("SELECT * FROM annotations WHERE key=?", (row["key"],)).fetchone()
    inserted = db.execute("INSERT INTO asset_search(key,text) VALUES (?,?)", (row["key"], _text(row, annotation)))
    db.execute("INSERT OR REPLACE INTO asset_search_keys VALUES (?,?)", (row["key"], inserted.lastrowid))


def _row(path, relative, data, root, game, previous=None, cache=None, collection=None):
    fingerprint = common.digest(data)
    old = json.loads(previous["observation"]) if previous else {}
    unchanged = previous and previous["hash"] == fingerprint and old.get("adapter_revision") == dependencies.ADAPTER_REVISION
    try:
        observed = formats.inspect(data, path.suffix) if not unchanged else {k: old[k] for k in ("format", "kind", "coverage", "metadata", "limits")}
        observed.update(dependencies.observe(path, data, observed, dependencies.selected_root(path, root), cache))
    except (ValueError, OSError, SyntaxError, struct.error, KeyError, IndexError, TypeError, UnicodeError) as exc:
        observed = {"format": "MALFORMED_CANDIDATE", "kind": "unknown", "coverage": "INVALID", "metadata": {},
                    "adapter_revision": dependencies.ADAPTER_REVISION, "identity": fingerprint,
                    "dependencies": [], "dependency_edges": [], "dependency_status": "INVALID", "limits": [str(exc)[:200]]}
    return {"key": _key(root, relative), "root": str(root), "collection": collection or str(root), "relative": relative, "game": game,
            "hash": fingerprint, "bytes": len(data), "format": observed["format"], "kind": observed["kind"],
            "coverage": observed["coverage"], "observation": json.dumps(observed, ensure_ascii=False)}, bool(unchanged and old.get("identity") == observed["identity"])


def _capacity(db, root, count, collection=None):
    collection = collection or str(root)
    others = db.execute("SELECT COUNT(*) FROM assets WHERE collection!=?", (collection,)).fetchone()[0]
    roots = {r[0] for r in db.execute("SELECT DISTINCT collection FROM assets")}
    if count > MAX_CATALOG or others + count > MAX_TOTAL_ROWS or (collection not in roots and len(roots) >= MAX_COLLECTIONS):
        raise ValueError("CATALOG_COLLECTION_LIMIT")


def _replace(db, root, rows, collection=None):
    collection = collection or str(root)
    existing = {r["key"] for r in db.execute("SELECT key FROM assets WHERE collection=?", (collection,))}
    seen = set()
    for row in rows:
        seen.add(row["key"])
        db.execute("INSERT OR REPLACE INTO assets (key,root,relative,game,hash,bytes,format,kind,coverage,observation,collection) VALUES (:key,:root,:relative,:game,:hash,:bytes,:format,:kind,:coverage,:observation,:collection)", row)
        db.execute("DELETE FROM asset_links WHERE key=?", (row["key"],))
        for edge in json.loads(row["observation"]).get("dependency_edges", []):
            if edge["status"] == "LOCAL":
                db.execute("INSERT OR IGNORE INTO asset_links VALUES (?,?,?,?)", (row["key"], edge["path"], edge["hash"], edge["role"]))
        _reindex(db, row)
    for key in existing - seen:
        search = db.execute("SELECT search_rowid FROM asset_search_keys WHERE key=?", (key,)).fetchone()
        if search:
            db.execute("DELETE FROM asset_search WHERE rowid=?", (search[0],))
        for table in ("assets", "asset_search_keys", "annotations", "asset_links"):
            db.execute("DELETE FROM " + table + " WHERE key=?", (key,))
    return len(existing - seen)


def index(raw: str, game: str = "") -> dict:
    root = common.local_path(raw, directory=True)
    if root == Path.home() or root in Path.home().parents or str(root) in ("/usr", "/etc", "/var", "/tmp", "/home"):
        raise ValueError("SELECT_SPECIFIC_ASSET_DIRECTORY")
    game = str(game).strip()
    if len(game) > 120:
        raise ValueError("GAME_LABEL_TOO_LONG")
    began, scanned, total = time.monotonic(), 0, 0
    entries, skipped = [], []
    for directory, dirs, names in os.walk(root, followlinks=False):
        scanned += len(dirs) + len(names)
        if scanned > MAX_SCAN or time.monotonic() - began > 30:
            raise ValueError("ASSET_SCAN_LIMIT_PREVIOUS_CATALOG_PRESERVED")
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS and not (Path(directory) / d).is_symlink())
        for name in sorted(names):
            path = Path(directory) / name
            if path.is_symlink() or name.startswith(".") or re.search(r"(?i)secret|credential|private.key|service.account", name):
                continue
            relative = path.relative_to(root).as_posix()
            if len(entries) >= MAX_FILES:
                raise ValueError("ASSET_FILE_LIMIT_PREVIOUS_CATALOG_PRESERVED")
            try:
                _, data = common.read_file(path, root=root)
            except ValueError as exc:
                if str(exc) in ("FILE_TOO_LARGE", "REGULAR_FILE_REQUIRED"):
                    if len(skipped) < 64:
                        skipped.append({"path": relative, "reason": str(exc)})
                    continue
                raise
            total += len(data)
            if total > MAX_SCAN_BYTES or time.monotonic() - began > 30:
                raise ValueError("ASSET_BYTE_OR_TIME_LIMIT_PREVIOUS_CATALOG_PRESERVED")
            entries.append((path, relative, common.digest(data), len(data), data))
    db = _db()
    updated = unchanged = invalid = 0
    cache = {}
    try:
        with db:
            existing = {row["relative"]: dict(row) for row in db.execute("SELECT * FROM assets WHERE root=?", (str(root),))}
            _capacity(db, root, len(entries))
            rows = []
            for path, relative, fingerprint, size, data in entries:
                previous = existing.get(relative)
                row, same = _row(path, relative, data, root, game, previous, cache)
                unchanged += int(same)
                updated += int(not same)
                invalid += int(row["coverage"] == "INVALID")
                rows.append(row)
            removed = _replace(db, root, rows)
        return {"status": "INDEXED", "summary": f"{len(entries)} assets · {updated} changed · {unchanged} unchanged",
                "root": str(root), "game": game, "indexed": len(entries), "updated": updated, "unchanged": unchanged,
                "removed": removed, "invalid": invalid, "skipped": skipped,
                "limits": ["Indexing preserves source files. Game labels are searchable provenance, not decoder selectors.",
                           "Lexical search is available; semantic model weights are not installed by this workflow."]}
    finally:
        db.close()


def _fresh(row, cache=None, budget=None, *, complete=False):
    path, data = common.read_file(Path(row["root"]) / row["relative"], root=Path(row["root"]))
    if common.digest(data) != row["hash"]:
        raise ValueError("ASSET_CHANGED_REINDEX_REQUIRED")
    if budget is not None:
        budget[0] += len(data)
        if budget[0] > budget[1]:
            raise ValueError("FRESHNESS_BYTE_LIMIT")
    observation = json.loads(row["observation"])
    if observation.get("adapter_revision") != dependencies.ADAPTER_REVISION:
        raise ValueError("ADAPTER_UPDATED_REINDEX_REQUIRED")
    if complete and observation.get("dependency_status") != "COMPLETE":
        raise ValueError("ASSET_DEPENDENCIES_INCOMPLETE")
    if observation.get("dependency_status") in ("COMPLETE", "INCOMPLETE"):
        dependencies.fresh(observation, cache=cache, budget=budget, require_complete=complete)
    return path, data


def _public(row, db):
    value = dict(row)
    observed = json.loads(value.pop("observation"))
    annotation = db.execute("SELECT * FROM annotations WHERE key=?", (row["key"],)).fetchone()
    value.update(observed, path=str(Path(row["root"]) / row["relative"]),
                 freshness="BUNDLE_CURRENT" if observed.get("dependency_status") == "COMPLETE" else "DOCUMENT_CURRENT_DEPENDENCIES_INCOMPLETE",
                 duplicates=db.execute("SELECT COUNT(*) FROM assets WHERE hash=?", (row["hash"],)).fetchone()[0],
                 annotation={"tags": annotation["tags"], "note": annotation["note"]} if annotation and annotation["hash"] == observed.get("identity", row["hash"]) else None)
    return value


def search(query: str = "", game: str = "", kind: str = "", limit: int = 32) -> dict:
    query, game, kind = (str(item).strip() for item in (query, game, kind))
    limit = int(limit)
    if len(query) > 256 or not 1 <= limit <= 64:
        raise ValueError("QUERY_LIMIT")
    tokens = re.findall(r"[\w]+", query, re.UNICODE)[:24]
    expressions = []
    for word in tokens:
        alternatives = [word] + ([LEXICON[word.lower()]] if word.lower() in LEXICON else [])
        expressions.append("(" + " OR ".join('"' + item + '"*' for item in alternatives) + ")")
    params, clauses = [], []
    if game:
        clauses.append("a.game=?"); params.append(game)
    if kind:
        clauses.append("a.kind=?"); params.append(kind)
    if expressions:
        clauses.append("asset_search MATCH ?"); params.append(" AND ".join(expressions))
    join = "JOIN asset_search ON a.key=asset_search.key" if expressions else ""
    ordering = "bm25(asset_search),a.relative" if expressions else "a.relative"
    sql = "SELECT a.* FROM assets a " + join + (" WHERE " + " AND ".join(clauses) if clauses else "") + " ORDER BY " + ordering + " LIMIT 128"
    db = _db()
    try:
        hits, stale, budget, cache = [], 0, [0, MAX_SCAN_BYTES], {}
        for row in db.execute(sql, params).fetchall():
            if budget[0] + row["bytes"] > MAX_SCAN_BYTES:
                break
            try:
                _fresh(row, cache, budget)
            except (OSError, ValueError):
                stale += 1
                continue
            hits.append(_public(row, db))
            if len(hits) == limit:
                break
        return {"status": "READY", "summary": f"{len(hits)} current documents · {stale} stale matches excluded",
                "hits": hits, "stale_excluded": stale, "retrieval": "LEXICAL_FTS5", "game": game,
                "freshness_bytes": budget[0], "limits": ["Bundle freshness includes buffers and images. Incomplete dependencies remain explicitly marked on discovery results."]}
    finally:
        db.close()


def asset(key: str) -> dict:
    db = _db()
    try:
        row = db.execute("SELECT * FROM assets WHERE key=?", (str(key),)).fetchone()
        if row is None:
            raise ValueError("ASSET_NOT_IN_CATALOG")
        _fresh(row)
        return _public(row, db)
    finally:
        db.close()


def relations(key: str) -> dict:
    source = asset(key)
    db = _db()
    try:
        shared = []
        for resource in source.get("dependencies", []):
            count = db.execute("SELECT COUNT(DISTINCT key) FROM asset_links WHERE target=?", (resource["path"],)).fetchone()[0]
            owners = [dict(row) for row in db.execute("SELECT DISTINCT a.key,a.root,a.relative,a.game FROM asset_links l JOIN assets a ON a.key=l.key WHERE l.target=? ORDER BY a.root,a.relative LIMIT 64", (resource["path"],))]
            shared.append({**resource, "catalog_owners": count, "owners": owners, "owners_clipped": count > 64})
        return {"status": "READY", "summary": f"{len(shared)} resources with catalog ownership relations", "source": source,
                "resources": shared, "limits": ["Owner relations describe the committed catalog snapshot; each owner needs its own freshness check before use.",
                                                   "Variant families are filename candidates; shared resource hashes establish the actual buffer/rig/animation relationships."]}
    finally:
        db.close()


def annotate(key: str, tags: str, note: str = "") -> dict:
    if len(str(tags)) > 512 or len(str(note)) > 2048:
        raise ValueError("ANNOTATION_LIMIT")
    db = _db()
    try:
        row = db.execute("SELECT * FROM assets WHERE key=?", (key,)).fetchone()
        if row is None:
            raise ValueError("ASSET_NOT_IN_CATALOG")
        _fresh(row, complete=True)
        with db:
            identity = json.loads(row["observation"])["identity"]
            db.execute("INSERT OR REPLACE INTO annotations VALUES (?,?,?,?)", (key, identity, str(tags), str(note)))
            _reindex(db, row)
        return {"status": "ANNOTATED", "summary": "Annotation is bound to these exact source bytes.", "key": key}
    finally:
        db.close()


def contact_sheet(keys: list[str]) -> dict:
    from PIL import Image, ImageDraw
    if not isinstance(keys, list) or not 1 <= len(keys) <= 24 or len(keys) != len(set(keys)):
        raise ValueError("SELECT_1_TO_24_DISTINCT_ASSETS")
    rows = sorted((asset(str(key)) for key in keys), key=lambda row: (row["hash"], row["relative"]))
    width, height = 4 * 224, ((len(rows) + 3) // 4) * 192
    sheet = Image.new("RGB", (width, height), "#191919")
    draw = ImageDraw.Draw(sheet)
    manifest = []
    for index, row in enumerate(rows):
        _, data = common.read_file(row["path"], root=Path(row["root"]))
        if common.digest(data) != row["hash"]:
            raise ValueError("ASSET_CHANGED_REINDEX_REQUIRED")
        x, y = (index % 4) * 224, (index // 4) * 192
        preview = "UNAVAILABLE"
        if Path(row["path"]).suffix.lower() in formats.IMAGE_SUFFIXES:
            with Image.open(io.BytesIO(data)) as image:
                if image.width * image.height > formats.MAX_PIXELS:
                    raise ValueError("IMAGE_PIXEL_LIMIT")
                image.thumbnail((216, 152))
                converted = image.convert("RGBA")
                sheet.paste(converted, (x + 4, y + 4), converted)
                preview = "SOURCE_PIXELS"
        else:
            draw.text((x + 8, y + 32), row["format"] + "\nPreview requires adapter", fill="#b8b8b8")
        draw.text((x + 4, y + 160), f"{index + 1:02d}  " + Path(row["relative"]).name[:27], fill="#eeeeee")
        manifest.append({"ordinal": index + 1, "key": row["key"], "path": row["path"], "hash": row["hash"],
                         "preview": preview, "game": row["game"]})
    pixels = io.BytesIO()
    sheet.save(pixels, format="PNG")
    image_data = pixels.getvalue()
    record = {"schema": "gg.game-workflows.visual-evidence.v1", "rows": manifest, "image_sha256": common.digest(image_data),
              "ordering": "SOURCE_IDENTITY_NOT_SEARCH_RANK", "limits": ["No model render or inferred classification is substituted for missing pixel evidence."]}
    path = common.packet("visual", record)
    image_path = path.with_suffix(".png")
    if image_path.exists() and common.digest(common.read_file(image_path)[1]) != record["image_sha256"]:
        raise ValueError("VISUAL_EVIDENCE_IMAGE_CHANGED")
    if not image_path.exists():
        common.write_bytes(image_path, image_data)
    return {"status": "READY", "summary": f"{len(rows)} assets in a source-bound contact sheet", "packet_path": str(path),
            "image": image_path.as_uri(), "rows": manifest}
