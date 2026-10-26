"""Persistent, source-grounded local documents for the clickable raster atlas.

Import preserves bounded complete page text. Search and navigation use SQLite
and cached rasters; they never invoke a model or make network requests. The
automatic graph records literal word mentions, not inferred factual claims.
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import threading
import time
from typing import Any
import uuid

from backend.application_paths import PROJECT_ROOT, STATE_ROOT
from backend.platform_files import atomic_replace, is_link
from backend.platform_process import run_bounded
from backend.platform_support import local_file_path

SCHEMA = "gg.knowledge-atlas.v1"
ROOT = STATE_ROOT / "knowledge-atlas"
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_FILES = 32
MAX_SOURCES = 512
MAX_TEXT_CHARS = 2_000_000
MAX_TOTAL_CHARS = 32_000_000
MAX_STORE_BYTES = 512 * 1024 * 1024
MAX_PAGES = 512
MAX_NODES = 320
MAX_EDGES = 1024
MAX_TERMS = 48
TEXT_TYPES = {".md", ".txt", ".rst", ".json"}
IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".webp"}
SUPPORTED_TYPES = TEXT_TYPES | IMAGE_TYPES | {".pdf"}
SKIP_DIRS = {".git", ".ssh", ".aws", ".azure", ".codex", ".grok", ".env",
             ".venv", ".venv-windows", "node_modules", "__pycache__", ".runtime"}
_WORDS = re.compile(r"[^\W\d_][\w-]{2,}", re.UNICODE)
_SEARCH_WORDS = re.compile(r"\w+(?:-\w+)*", re.UNICODE)
_STOP = set((
    "the and for with that this from have has was were will can not but are you your "
    "into its their they them all any our out there when what which where who how "
    "also than then these those each only more most been being use used using "
    "och att för med som den det de till från har är ett en på inte eller kan ska "
    "vi du man sig sin sitt sina om av vad hur när denna detta dessa bara även "
    "under över mellan utan finns genom vara blir skulle måste vid inom "
    "true false null none self root property string import function return "
    "http https www com html json text file files source sources page pages"
).split())
_LOCK = threading.RLock()


def _result(status: str, **values: Any) -> dict[str, Any]:
    return {"schema": SCHEMA, "status": status, "model_calls": 0, **values}


def _root(root: Path | str | None) -> Path:
    target = Path(root if root is not None else ROOT).expanduser().absolute()
    if is_link(target):
        raise ValueError("LINKED_STORE_NOT_ALLOWED")
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    return target.resolve()


@contextmanager
def _db(root: Path | str | None):
    target = _root(root)
    database = target / "atlas.sqlite3"
    if is_link(database):
        raise ValueError("LINKED_STORE_NOT_ALLOWED")
    db = sqlite3.connect(database, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS sources(
            id TEXT PRIMARY KEY, origin TEXT UNIQUE NOT NULL, title TEXT NOT NULL,
            kind TEXT NOT NULL, suffix TEXT NOT NULL, blob TEXT NOT NULL,
            digest TEXT NOT NULL, revision TEXT NOT NULL, pages INTEGER NOT NULL,
            ocr_pages TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS pages(
            id INTEGER PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
            page INTEGER NOT NULL, text TEXT NOT NULL, width REAL NOT NULL,
            height REAL NOT NULL, UNIQUE(source_id,page)
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS page_fts USING fts5(
            text, content='pages', content_rowid='id', tokenize='unicode61 remove_diacritics 2'
        );
        CREATE TRIGGER IF NOT EXISTS page_insert AFTER INSERT ON pages BEGIN
            INSERT INTO page_fts(rowid,text) VALUES(new.id,new.text);
        END;
        CREATE TRIGGER IF NOT EXISTS page_delete AFTER DELETE ON pages BEGIN
            INSERT INTO page_fts(page_fts,rowid,text) VALUES('delete',old.id,old.text);
        END;
        CREATE TABLE IF NOT EXISTS concepts(
            id TEXT PRIMARY KEY, term TEXT UNIQUE NOT NULL, label TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS mentions(
            concept_id TEXT NOT NULL REFERENCES concepts(id),
            source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
            page INTEGER NOT NULL, count INTEGER NOT NULL,
            PRIMARY KEY(concept_id,source_id,page)
        );
        CREATE INDEX IF NOT EXISTS mention_source ON mentions(source_id,page);
    """)
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def _source(row: sqlite3.Row) -> dict[str, Any]:
    ocr = json.loads(row["ocr_pages"])
    return {"id": row["id"], "title": row["title"], "kind": row["kind"],
            "format": row["suffix"].lstrip(".").upper(), "pages": row["pages"],
            "origin": row["origin"], "needs_ocr": ocr,
            "status": "NEEDS_OCR" if ocr else "READY"}


def _source_node(source: dict[str, Any]) -> dict[str, Any]:
    return {"id": source["id"], "label": source["title"], "kind": source["kind"],
            "source_count": 1, "summary": ("Importerad bild, utan automatisk tolkning."
                if source["kind"] == "OBJECT" else "Importerad källa med sidreferenser."),
            "source_id": source["id"], "pages": source["pages"],
            "format": source["format"], "needs_ocr": source["needs_ocr"]}


def _valid_input(raw: str | Path) -> Path:
    text = str(raw)
    if not text or len(text) > 4096 or "\0" in text or text.startswith(("\\\\", "//")):
        raise ValueError("LOCAL_PATH_REQUIRED")
    if re.match(r"^[a-z][a-z0-9+.-]*://", text, re.I) and not text.lower().startswith("file:"):
        raise ValueError("LOCAL_PATH_REQUIRED")
    path = local_file_path(text).expanduser().absolute()
    if is_link(path) or any(is_link(parent) for parent in path.parents):
        raise ValueError("LINKED_INPUT_NOT_ALLOWED")
    if any(part.casefold() in SKIP_DIRS or part.casefold().startswith(".env")
           for part in path.parts):
        raise ValueError("PRIVATE_INPUT_NOT_ALLOWED")
    return path.resolve(strict=True)


def _paths(paths: list[str | Path]) -> list[Path]:
    if not isinstance(paths, (list, tuple)) or not 1 <= len(paths) <= MAX_FILES:
        raise ValueError("SELECT_ONE_TO_32_FILES")
    found: list[Path] = []
    scanned = 0
    for raw in paths:
        path = _valid_input(raw)
        if path.is_dir():
            for directory, dirs, files in os.walk(path, followlinks=False):
                dirs[:] = sorted(d for d in dirs if d.casefold() not in SKIP_DIRS
                                  and not d.startswith(".")
                                  and not is_link(Path(directory) / d))
                for name in sorted(files):
                    scanned += 1
                    if scanned > 5000:
                        raise ValueError("DIRECTORY_ENTRY_LIMIT")
                    candidate = Path(directory) / name
                    if name.startswith(".") or candidate.suffix.lower() not in SUPPORTED_TYPES:
                        continue
                    found.append(_valid_input(candidate))
                    if len(set(found)) > MAX_FILES:
                        raise ValueError("SELECT_A_SMALLER_FOLDER_MAX_32_FILES")
        elif path.is_file():
            found.append(path)
        else:
            raise ValueError("REGULAR_FILE_REQUIRED")
    return list(dict.fromkeys(found))


def _terms(text: str) -> Counter:
    return Counter(w.casefold() for w in _WORDS.findall(text)
                   if 3 <= len(w) <= 48 and w.casefold() not in _STOP)


def _worker(source: Path, *, output: Path | None = None, page: int | None = None,
            cancelled=None) -> dict[str, Any]:
    command = [sys.executable, "-B", "-m", "backend.knowledge_extract",
               "render" if output else "extract", str(source)]
    if output:
        command += ["--page", str(page), "--output", str(output)]
    env = {"PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1", "QT_QPA_PLATFORM": "offscreen"}
    code, stdout, _, trigger = run_bounded(command, cwd=PROJECT_ROOT, env=env,
        timeout=40, max_output_bytes=12 * 1024 * 1024, cancelled=cancelled)
    if trigger != "NONE":
        raise ValueError("PDF_" + trigger)
    try:
        result = json.loads(stdout)
    except (ValueError, UnicodeError):
        raise ValueError("PDF_WORKER_FAILED") from None
    if code or result.get("status") == "ERROR":
        raise ValueError(str(result.get("reason") or "PDF_WORKER_FAILED"))
    return result


def _extract(path: Path, blob: Path, data: bytes, cancelled=None) -> tuple[list[dict], list[int]]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        result = _worker(blob, cancelled=cancelled)
        return result["pages"], result["needs_ocr"]
    if suffix in IMAGE_TYPES:
        from PIL import Image
        try:
            with Image.open(blob) as picture:
                if picture.width * picture.height > 40_000_000:
                    raise ValueError("IMAGE_PIXEL_LIMIT")
                picture.verify()
                width, height = picture.size
        except (OSError, Image.DecompressionBombError) as exc:
            raise ValueError("INVALID_IMAGE") from exc
        return [{"page": 1, "text": path.stem, "width": width, "height": height}], []
    try:
        text = data.decode("utf-8-sig")
    except UnicodeError:
        raise ValueError("TEXT_MUST_BE_UTF8") from None
    if "\0" in text:
        raise ValueError("BINARY_TEXT_NOT_ALLOWED")
    if len(text) > MAX_TEXT_CHARS:
        raise ValueError("TEXT_CHARACTER_LIMIT")
    # Form feed retains explicit source pages; ordinary text remains one page.
    pages = text.split("\f")
    if len(pages) > MAX_PAGES:
        raise ValueError("TEXT_PAGE_LIMIT")
    return [{"page": i + 1, "text": value, "width": 0, "height": 0}
            for i, value in enumerate(pages)], []


def _import_file(path: Path, root: Path, cancelled=None) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_TYPES:
        raise ValueError("UNSUPPORTED_FILE_TYPE")
    if not 0 < path.stat().st_size <= MAX_FILE_BYTES:
        raise ValueError("FILE_SIZE_LIMIT")
    with path.open("rb") as handle:
        data = handle.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("FILE_SIZE_LIMIT")
    digest = hashlib.sha256(data).hexdigest()
    origin = str(path)
    with _LOCK, _db(root) as db:
        previous = db.execute("SELECT * FROM sources WHERE origin=?", (origin,)).fetchone()
        if (previous and previous["digest"] == digest
                and (root / "blobs" / previous["blob"]).is_file()
                and not is_link(root / "blobs" / previous["blob"])):
            return {"status": "CACHED", "source_id": previous["id"], "title": path.stem,
                    "pages": previous["pages"], "needs_ocr": json.loads(previous["ocr_pages"])}
        if not previous and db.execute("SELECT count(*) FROM sources").fetchone()[0] >= MAX_SOURCES:
            raise ValueError("SOURCE_COUNT_LIMIT")
    blobs = root / "blobs"
    blobs.mkdir(exist_ok=True, mode=0o700)
    if is_link(blobs):
        raise ValueError("LINKED_STORE_NOT_ALLOWED")
    if sum(p.stat().st_size for p in blobs.iterdir() if p.is_file()) + len(data) > MAX_STORE_BYTES:
        raise ValueError("LOCAL_STORAGE_LIMIT")
    blob = blobs / (uuid.uuid4().hex + suffix)
    blob.write_bytes(data)
    committed = False
    try:
        pages, ocr = _extract(path, blob, data, cancelled=cancelled)
        if cancelled and cancelled():
            raise ValueError("CANCELLED")
        if not pages:
            raise ValueError("SOURCE_EMPTY")
        source_id = previous["id"] if previous else "source-" + uuid.uuid4().hex
        now = time.time()
        kind = "OBJECT" if suffix in IMAGE_TYPES else "SOURCE"
        page_terms = [(p["page"], _terms(p["text"])) for p in pages]
        ranked = Counter()
        for _, counter in page_terms:
            ranked.update(counter)
        selected = {term for term, _ in ranked.most_common(MAX_TERMS)}
        with _LOCK, _db(root) as db:
            retained = db.execute("SELECT coalesce(sum(length(text)),0) FROM pages WHERE source_id<>?",
                                  (source_id,)).fetchone()[0]
            if retained + sum(len(p["text"]) for p in pages) > MAX_TOTAL_CHARS:
                raise ValueError("TOTAL_TEXT_LIMIT")
            if previous:
                db.execute("DELETE FROM sources WHERE id=?", (source_id,))
            db.execute("INSERT INTO sources VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (
                source_id, origin, path.stem, kind, suffix, blob.name, digest,
                uuid.uuid4().hex, len(pages), json.dumps(ocr),
                previous["created"] if previous else now, now))
            for item in pages:
                db.execute("INSERT INTO pages(source_id,page,text,width,height) VALUES(?,?,?,?,?)",
                    (source_id, item["page"], item["text"], item["width"], item["height"]))
            for term in sorted(selected):
                existing = db.execute("SELECT id FROM concepts WHERE term=?", (term,)).fetchone()
                concept = existing[0] if existing else "concept-" + uuid.uuid4().hex
                db.execute("INSERT OR IGNORE INTO concepts VALUES(?,?,?)", (concept, term, term))
                for number, counter in page_terms:
                    if counter[term]:
                        db.execute("INSERT INTO mentions VALUES(?,?,?,?)",
                                   (concept, source_id, number, counter[term]))
            db.execute("DELETE FROM concepts WHERE NOT EXISTS(SELECT 1 FROM mentions WHERE concept_id=concepts.id)")
        committed = True
        if previous:
            # A sharing lock on an old raster must not invalidate the new
            # committed source. Old assets are never returned after revision.
            try:
                (blobs / previous["blob"]).unlink(missing_ok=True)
                rasters = root / "rasters"
                if rasters.is_dir() and not is_link(rasters):
                    for stale in rasters.glob(source_id + "-*.png"):
                        stale.unlink(missing_ok=True)
            except OSError:
                pass
        return {"status": "IMPORTED", "source_id": source_id, "title": path.stem,
                "pages": len(pages), "needs_ocr": ocr}
    except BaseException:
        if not committed:
            blob.unlink(missing_ok=True)
        raise


def import_paths(paths, *, root=None, cancelled=None) -> dict[str, Any]:
    """Import only explicitly selected local files or a bounded selected folder."""
    try:
        target = _root(root)
        files = _paths(paths)
    except (ValueError, OSError) as exc:
        reason = str(exc) if isinstance(exc, ValueError) else "INPUT_UNAVAILABLE"
        return _result("ERROR", reason=reason, results=[])
    if not files:
        return _result("ERROR", reason="NO_SUPPORTED_FILES", results=[])
    results = []
    for path in files:
        if cancelled and cancelled():
            return _result("CANCELLED", results=results)
        try:
            results.append(_import_file(path, target, cancelled=cancelled))
        except (ValueError, OSError, sqlite3.Error) as exc:
            reason = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
            if cancelled and cancelled():
                return _result("CANCELLED", results=results)
            results.append({"status": "ERROR", "title": path.stem, "reason": reason})
    imported = sum(r["status"] == "IMPORTED" for r in results)
    cached = sum(r["status"] == "CACHED" for r in results)
    errors = len(results) - imported - cached
    return _result("IMPORTED" if imported or cached else "ERROR", results=results,
                   imported=imported, cached=cached, errors=errors)


def _excerpt(text: str, query: str = "", limit: int = 900) -> str:
    start = 0
    if query:
        matches = [text.casefold().find(word.casefold()) for word in _SEARCH_WORDS.findall(query)]
        found = [position for position in matches if position >= 0]
        if found:
            start = max(0, min(found) - 180)
    end = min(len(text), start + limit)
    return ("…" if start else "") + text[start:end] + ("…" if end < len(text) else "")


def snapshot(query="", kind="ALL", *, root=None) -> dict[str, Any]:
    """Return a bounded material map and full-text hits with exact page origins."""
    query = str(query or "").strip()
    kind = str(kind or "ALL").upper()
    if len(query) > 300 or "\0" in query or kind not in {"ALL", "SOURCE", "CONCEPT", "OBJECT"}:
        return _result("ERROR", reason="INVALID_FILTER")
    with _LOCK, _db(root) as db:
        all_sources = [_source(row) for row in db.execute("SELECT * FROM sources ORDER BY updated DESC")]
        hits = []
        words = _SEARCH_WORDS.findall(query)
        if words:
            expression = " AND ".join('"' + word.replace('"', '""') + '"' for word in words[:12])
            source_kind = kind if kind in {"SOURCE", "OBJECT"} else ""
            for row in db.execute("""SELECT p.source_id,p.page,p.text,s.title FROM page_fts f
                    JOIN pages p ON p.id=f.rowid JOIN sources s ON s.id=p.source_id
                    WHERE page_fts MATCH ? AND (?='' OR s.kind=?)
                    ORDER BY bm25(page_fts) LIMIT 32""", (expression, source_kind, source_kind)):
                hits.append({"node_id": row["source_id"], "source_id": row["source_id"],
                             "source_title": row["title"], "page": row["page"],
                             "text": _excerpt(row["text"], query)})
        source_ids = {h["source_id"] for h in hits}
        sources = [s for s in all_sources
                   if (kind not in {"SOURCE", "OBJECT"} or s["kind"] == kind)
                   and (not query or s["id"] in source_ids
                        or query.casefold() in s["title"].casefold())][:128]
        visible_sources = {s["id"] for s in sources}
        nodes = [_source_node(source) for source in sources] if kind in {"ALL", "SOURCE", "OBJECT"} else []
        if kind == "SOURCE":
            nodes = [node for node in nodes if node["kind"] == "SOURCE"]
        elif kind == "OBJECT":
            nodes = [node for node in nodes if node["kind"] == "OBJECT"]
        concepts = list(db.execute("""SELECT c.id,c.label,count(DISTINCT m.source_id) n,
                sum(m.count) occurrences FROM concepts c JOIN mentions m ON m.concept_id=c.id
                GROUP BY c.id ORDER BY n DESC,occurrences DESC,c.label LIMIT 192"""))
        if kind in {"ALL", "CONCEPT"}:
            for row in concepts:
                if query and not query.casefold() in row["label"].casefold():
                    in_sources = db.execute("SELECT source_id FROM mentions WHERE concept_id=?", (row["id"],))
                    if not any(r[0] in visible_sources for r in in_sources):
                        continue
                nodes.append({"id": row["id"], "label": row["label"], "kind": "CONCEPT",
                              "source_count": row["n"], "summary": "Ordet nämns i källmaterialet; ingen automatisk faktatolkning."})
        nodes = nodes[:MAX_NODES]
        node_ids = {n["id"] for n in nodes}
        edges = []
        for row in db.execute("SELECT concept_id,source_id,count(*) n FROM mentions GROUP BY concept_id,source_id"):
            if row["concept_id"] in node_ids and row["source_id"] in node_ids:
                edges.append({"source": row["concept_id"], "target": row["source_id"],
                              "label": "nämns i", "provenance": "EXTRACTED", "pages": row["n"]})
                if len(edges) >= MAX_EDGES:
                    break
        totals = {"sources": len(all_sources), "pages": sum(s["pages"] for s in all_sources),
                  "nodes": len(all_sources) + db.execute("SELECT count(*) FROM concepts").fetchone()[0],
                  "objects": sum(s["kind"] == "OBJECT" for s in all_sources)}
    notices = []
    ocr_count = sum(len(s["needs_ocr"]) for s in all_sources)
    if ocr_count:
        notices.append(f"{ocr_count} sidor saknar extraherbar text. Sidbilder finns; OCR har inte körts.")
    if totals["nodes"] > len(nodes) and not query and kind == "ALL":
        notices.append("Kartan visar ett urval. Sök för att hitta fler delar av materialet.")
    return _result("READY", nodes=nodes, edges=edges, sources=sources,
                   counts=totals, hits=hits, notices=notices,
                   limits={"files_per_import": MAX_FILES, "file_bytes": MAX_FILE_BYTES,
                           "pages_per_source": MAX_PAGES, "characters_per_source": MAX_TEXT_CHARS})


def detail(node_id, *, root=None) -> dict[str, Any]:
    node_id = str(node_id or "")
    if len(node_id) > 100:
        return _result("ERROR", reason="NODE_NOT_FOUND")
    with _LOCK, _db(root) as db:
        source_row = db.execute("SELECT * FROM sources WHERE id=?", (node_id,)).fetchone()
        if source_row:
            source = _source(source_row)
            records = list(db.execute("SELECT page,text FROM pages WHERE source_id=? ORDER BY page LIMIT 32", (node_id,)))
            passages = [{"source_id": node_id, "source_title": source["title"],
                         "page": r["page"], "text": _excerpt(r["text"], limit=2000)} for r in records]
            edges = [{"source": r["concept_id"], "target": node_id, "label": "nämns i",
                      "provenance": "EXTRACTED", "concept_label": r["label"]} for r in db.execute(
                        "SELECT DISTINCT m.concept_id,c.label FROM mentions m JOIN concepts c ON c.id=m.concept_id WHERE m.source_id=? ORDER BY c.label LIMIT 48", (node_id,))]
            return _result("DETAIL", node=_source_node(source), source_id=node_id,
                           pages=source["pages"], passages=passages, edges=edges,
                           total_passages=source["pages"], passages_limited=source["pages"] > 32,
                           needs_ocr=source["needs_ocr"])
        concept = db.execute("SELECT * FROM concepts WHERE id=?", (node_id,)).fetchone()
        if not concept:
            return _result("ERROR", reason="NODE_NOT_FOUND")
        records = list(db.execute("""SELECT m.source_id,m.page,p.text,s.title FROM mentions m
            JOIN pages p ON p.source_id=m.source_id AND p.page=m.page
            JOIN sources s ON s.id=m.source_id WHERE m.concept_id=? ORDER BY s.updated DESC,m.page""", (node_id,)))
        passages = [{"source_id": r["source_id"], "source_title": r["title"], "page": r["page"],
                     "text": _excerpt(r["text"], concept["label"], 1200)} for r in records[:32]]
        sources = list(dict.fromkeys(r["source_id"] for r in records))
        return _result("DETAIL", node={"id": node_id, "label": concept["label"], "kind": "CONCEPT",
            "source_count": len(sources), "summary": "Ordet nämns i dessa källor."}, passages=passages,
            edges=[{"source": node_id, "target": sid, "label": "nämns i", "provenance": "EXTRACTED"} for sid in sources],
            total_passages=len(records), passages_limited=len(records) > 32)


def page_image(source_id, page=1, *, root=None) -> dict[str, Any]:
    """Read an imported image or lazily rasterize one exact imported PDF page."""
    try:
        page = int(page)
        target = _root(root)
        with _LOCK, _db(target) as db:
            row = db.execute("SELECT * FROM sources WHERE id=?", (str(source_id),)).fetchone()
            if not row:
                return _result("ERROR", reason="SOURCE_NOT_FOUND")
            source = _source(row)
            if not 1 <= page <= row["pages"]:
                return _result("ERROR", reason="INVALID_PAGE")
            item = db.execute("SELECT text,width,height FROM pages WHERE source_id=? AND page=?", (source_id, page)).fetchone()
            blob = target / "blobs" / row["blob"]
            revision = row["revision"]
        if source["kind"] == "OBJECT":
            return _result("PAGE_READY", image_url=blob.as_uri(), source_id=source_id,
                           page=1, pages=1, width=item["width"], height=item["height"],
                           source_title=source["title"], cached=True)
        if row["suffix"] != ".pdf":
            return _result("TEXT_READY", source_id=source_id, page=page, pages=row["pages"],
                           source_title=source["title"], text=item["text"])
        rasters = target / "rasters"
        rasters.mkdir(exist_ok=True, mode=0o700)
        if is_link(rasters) or is_link(blob):
            raise ValueError("LINKED_STORE_NOT_ALLOWED")
        output = rasters / (source_id + "-" + revision[:12] + f"-p{page}.png")
        cached = output.is_file() and not is_link(output)
        if not cached:
            temporary = rasters / (uuid.uuid4().hex + ".png")
            try:
                _worker(blob, output=temporary, page=page)
                atomic_replace(temporary, output)
            finally:
                temporary.unlink(missing_ok=True)
        return _result("PAGE_READY", image_url=output.as_uri(), source_id=source_id,
                       source_title=source["title"], page=page, pages=row["pages"],
                       needs_ocr=page in source["needs_ocr"], cached=cached)
    except (OSError, ValueError, TypeError, sqlite3.Error) as exc:
        return _result("ERROR", reason=str(exc) if isinstance(exc, ValueError) else type(exc).__name__)


def source_page(source_id, page=1, *, root=None) -> dict[str, Any]:
    """Exact stored page text for citation validation, without excerpt clipping."""
    try:
        page = int(page)
        with _LOCK, _db(root) as db:
            row = db.execute("""SELECT p.text,p.page,s.id,s.title,s.pages,s.ocr_pages,s.revision
                FROM pages p JOIN sources s ON s.id=p.source_id
                WHERE p.source_id=? AND p.page=?""", (str(source_id), page)).fetchone()
            if not row:
                return _result("ERROR", reason="SOURCE_PAGE_NOT_FOUND")
            return _result("PAGE_TEXT", source_id=row["id"], source_title=row["title"],
                page=row["page"], pages=row["pages"], text=row["text"], revision=row["revision"],
                needs_ocr=page in json.loads(row["ocr_pages"]))
    except (OSError, ValueError, TypeError, sqlite3.Error) as exc:
        return _result("ERROR", reason=str(exc) if isinstance(exc, ValueError) else type(exc).__name__)
