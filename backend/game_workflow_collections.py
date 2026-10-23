"""Finite collection planning and transactional, resumable asset batches."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import time
import uuid

from backend import game_workflow_common as common, game_workflow_scout as scout

MAX_ENTRIES = 65_536
MAX_BATCH_FILES = 256
MAX_BATCH_BYTES = 64 * 1024 * 1024
PRIORITY = {".glb": 0, ".gltf": 0, ".obj": 0, ".dae": 0, ".smd": 1, ".ggmesh": 1}


def _stamp(path):
    info = path.stat()
    return [info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def manifest(raw, recursive=True, partition=0, partitions=1):
    root = common.local_path(raw, directory=True)
    if root == Path.home() or root in Path.home().parents or str(root) in ("/usr", "/etc", "/var", "/tmp", "/home"):
        raise ValueError("SELECT_SPECIFIC_ASSET_DIRECTORY")
    rows, scanned, began = [], 0, time.monotonic()
    for directory, dirs, names in os.walk(root, followlinks=False):
        scanned += len(dirs) + len(names)
        if scanned > MAX_ENTRIES or time.monotonic() - began > 10:
            raise ValueError("COLLECTION_PLANNING_LIMIT")
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in scout.SKIP_DIRS and not (Path(directory) / d).is_symlink())
        if not recursive:
            dirs[:] = []
        for name in names:
            path = Path(directory) / name
            if path.is_symlink() or not path.is_file() or name.startswith(".") or re.search(r"(?i)secret|credential|private.key|service.account", name):
                continue
            relative = path.relative_to(root).as_posix()
            if int(common.digest(relative.encode())[:8], 16) % partitions == partition:
                rows.append([relative, _stamp(path)])
    return root, sorted(rows, key=lambda r: (PRIORITY.get(Path(r[0]).suffix.lower(), 2), r[0]))


def plan(raw):
    root, rows = manifest(raw)
    groups = {}
    # Partition at directory boundaries. Direct files are their own shallow
    # collection, so selecting it never inadvertently indexes child collections.
    for name, stamp in rows:
        parent = Path(name).parent
        prefix = Path(*parent.parts[:2]) if len(parent.parts) >= 2 else parent
        groups.setdefault(prefix.as_posix(), []).append((name, stamp))
    pending, result = list(sorted(groups.items())), []
    while pending:
        prefix, files = pending.pop(0)
        if len(files) > scout.MAX_CATALOG:
            depth, children = len(Path(prefix).parts), {}
            for name, stamp in files:
                parent = Path(name).parent
                child = Path(*parent.parts[:depth + 1]).as_posix()
                children.setdefault(child, []).append((name, stamp))
            if len(children) == 1 and prefix in children:
                # A large flat directory cannot be split into child roots.
                # Stable filename hash partitions keep admission bounded.
                partitions = math.ceil(len(files) / (scout.MAX_CATALOG * .75))
                for partition in range(partitions):
                    subset = [(n, s) for n, s in files if int(common.digest(Path(n).name.encode())[:8], 16) % partitions == partition]
                    if len(subset) > scout.MAX_CATALOG:
                        raise ValueError("COLLECTION_PARTITION_LIMIT")
                    result.append({"path": str(root / prefix), "relative": prefix + f" [{partition + 1}/{partitions}]", "files": len(subset),
                                   "bytes": sum(s[0] for _, s in subset), "oversize_files": sum(s[0] > common.MAX_FILE for _, s in subset),
                                   "partition": partition, "partitions": partitions, "recursive": False})
                continue
            pending.extend(sorted(children.items()))
            continue
        result.append({"path": str(root / prefix), "relative": prefix, "files": len(files),
                       "bytes": sum(s[0] for _, s in files), "oversize_files": sum(s[0] > common.MAX_FILE for _, s in files)})
        if len(result) + len(pending) > scout.MAX_COLLECTIONS:
            raise ValueError("COLLECTION_COUNT_LIMIT")
    for row in result:
        row.setdefault("partition", 0)
        row.setdefault("partitions", 1)
        row.setdefault("recursive", not any(other["path"] != row["path"] and Path(other["path"]).is_relative_to(Path(row["path"])) for other in result))
    return {"status": "READY", "summary": f"{len(rows)} files in {len(result)} bounded collections",
            "root": str(root), "collections": result,
            "limits": ["Each batch reads at most 256 files / 64 MiB. A collection replaces its prior catalog only after every batch and source-stamp check passes.",
                       "Files over the per-asset limit are identified and omitted explicitly; compiled runtime meshes remain separate from large authoring sources."]}


def batch(raw, game="", cursor="", batch_files=128, recursive=True, partition=0, partitions=1):
    game = str(game).strip()
    batch_files = int(batch_files)
    partition, partitions = int(partition), int(partitions)
    if len(game) > 120 or not 1 <= batch_files <= MAX_BATCH_FILES or not 0 <= partition < partitions <= 64:
        raise ValueError("COLLECTION_BATCH_ARGUMENT_LIMIT")
    db = scout._db()
    try:
        if cursor:
            if not re.fullmatch(r"[0-9a-f]{32}", str(cursor)):
                raise ValueError("INVALID_COLLECTION_CURSOR")
            session = db.execute("SELECT * FROM index_sessions WHERE id=?", (cursor,)).fetchone()
            if session is None or session["root"] != str(common.local_path(raw, directory=True)) or session["game"] != game:
                raise ValueError("COLLECTION_CURSOR_TARGET_CHANGED")
            saved = json.loads(session["manifest"])
            if (saved["recursive"], saved["partition"], saved["partitions"]) != (recursive, partition, partitions):
                raise ValueError("COLLECTION_CURSOR_MODE_CHANGED")
            root, rows, position = Path(session["root"]), saved["files"], session["position"]
        else:
            root, rows = manifest(raw, recursive, partition, partitions)
            if len(rows) > scout.MAX_CATALOG:
                raise ValueError("SELECT_A_PLANNED_COLLECTION")
            collection = str(root) + (f"#partition={partition}/{partitions};recursive={recursive}" if partitions > 1 or not recursive else "")
            scout._capacity(db, root, len(rows), collection)
            if db.execute("SELECT COUNT(*) FROM index_sessions").fetchone()[0] >= 8:
                raise ValueError("COLLECTION_SESSION_LIMIT_CANCEL_OLD_SESSION")
            cursor, position = uuid.uuid4().hex, 0
            with db:
                db.execute("INSERT INTO index_sessions VALUES (?,?,?,?,?,?)", (cursor, str(root), game, json.dumps({"files": rows, "recursive": recursive, "partition": partition, "partitions": partitions}), position, time.time()))
        collection = str(root) + (f"#partition={partition}/{partitions};recursive={recursive}" if partitions > 1 or not recursive else "")
        cache, processed, skipped, read_bytes, began = {}, [], [], 0, time.monotonic()
        start = position
        while position < len(rows) and position - start < batch_files:
            relative, stamp = rows[position]
            path = root / relative
            if _stamp(path) != stamp:
                raise ValueError("COLLECTION_CHANGED_RESTART_REQUIRED")
            if stamp[0] > common.MAX_FILE:
                skipped.append({"path": relative, "reason": "FILE_TOO_LARGE"})
                position += 1
                continue
            if read_bytes + stamp[0] > MAX_BATCH_BYTES or time.monotonic() - began > 20:
                break
            _, data = common.read_file(path, root=root)
            previous = db.execute("SELECT * FROM assets WHERE key=?", (scout._key(root, relative),)).fetchone()
            row, same = scout._row(path, relative, data, root, game, previous, cache, collection)
            processed.append(row)
            read_bytes += len(data)
            position += 1
        with db:
            for row in processed:
                db.execute("INSERT OR REPLACE INTO staged_assets VALUES (?,?,?)", (cursor, row["key"], json.dumps(row)))
            db.execute("UPDATE index_sessions SET position=? WHERE id=?", (position, cursor))
            if position == len(rows):
                _, now = manifest(str(root), recursive, partition, partitions)
                if now != rows:
                    raise ValueError("COLLECTION_CHANGED_RESTART_REQUIRED")
                staged = [json.loads(r[0]) for r in db.execute("SELECT row FROM staged_assets WHERE session=?", (cursor,))]
                for row in staged:
                    for dep in json.loads(row["observation"]).get("dependencies", []):
                        if _stamp(Path(dep["path"])) != dep["stamp"]:
                            raise ValueError("COLLECTION_DEPENDENCY_CHANGED_RESTART_REQUIRED")
                scout._capacity(db, root, len(staged), collection)
                removed = scout._replace(db, root, staged, collection)
                db.execute("DELETE FROM staged_assets WHERE session=?", (cursor,))
                db.execute("DELETE FROM index_sessions WHERE id=?", (cursor,))
                return {"status": "INDEXED", "summary": f"{len(staged)} assets committed as one collection", "root": str(root),
                        "indexed": len(staged), "removed": removed, "invalid": sum(r["coverage"] == "INVALID" for r in staged),
                        "oversize_files": sum(s[0] > common.MAX_FILE for _, s in rows), "skipped": skipped}
        return {"status": "STAGED", "summary": f"{position}/{len(rows)} files staged; previous collection remains available",
                "cursor": cursor, "root": str(root), "game": game, "processed": position, "total": len(rows), "batch_bytes": read_bytes, "skipped": skipped}
    finally:
        db.close()


def cancel(cursor):
    db = scout._db()
    try:
        with db:
            db.execute("DELETE FROM staged_assets WHERE session=?", (str(cursor),))
            removed = db.execute("DELETE FROM index_sessions WHERE id=?", (str(cursor),)).rowcount
        return {"status": "CANCELLED" if removed else "READY", "summary": "Staged collection discarded; committed assets preserved."}
    finally:
        db.close()
