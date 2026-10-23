"""Keep bitmaps out of durable Codex rollouts, including compaction copies.

Only closed on-disk history is changed. Active Codex history stays untouched.
Image content items become valid input_text items with a small description;
existing paths/text are retained. No new bitmap cache is created.

Closed logs are published atomically under Codex's session writer lock. Their
derived history projection is invalidated before changing any byte offsets.
The recovery reader remains compatible with older image-cleanup journals.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from backend.platform_support import file_locks as fcntl
import gzip
import json
import os
from pathlib import Path
import re
import select
import shutil
import signal
import sqlite3
import stat
import subprocess
import sys
import time

_URI = re.compile(r"data:(image/[A-Za-z0-9.+-]+);base64,([A-Za-z0-9+/=]+)")
_COPY = 1024 * 1024


def image_note(mime: str, encoded: str) -> str:
    size = len(encoded) * 3 // 4 - len(encoded) + len(encoded.rstrip("="))
    return (f"[Image in live conversation: {mime}, {size} bytes. "
            "Bitmap omitted from saved history. Reopen the original image "
            "file from the surrounding messages if it is still available.]")


def strip_images(value):
    """Replace image payloads without dropping surrounding messages or calls."""
    if isinstance(value, list):
        return [strip_images(item) for item in value]
    if isinstance(value, dict):
        if value.get("type") == "input_image":
            uri = value.get("image_url")
            match = _URI.fullmatch(uri) if isinstance(uri, str) else None
            if match:
                return {"type": "input_text", "text": image_note(*match.groups())}
        if value.get("type") == "image" and isinstance(value.get("data"), str):
            return {"type": "text", "text": image_note(
                str(value.get("mimeType") or "image/unknown"), value["data"])}
        return {key: strip_images(item) for key, item in value.items()}
    if isinstance(value, str) and "data:image/" in value:
        return _URI.sub(lambda match: image_note(*match.groups()), value)
    return value


def transformed(line: bytes) -> tuple[bytes, int]:
    # Ordinary lines stay byte-for-byte identical, including session metadata.
    if b"data:image/" not in line and b'"mimeType"' not in line:
        json.loads(line)  # Refuse partial or corrupt logs before publishing.
        return line, 0
    original = json.loads(line)
    cleaned = strip_images(original)
    if cleaned == original:
        return line, 0
    result = (json.dumps(cleaned, ensure_ascii=False, separators=(",", ":"))
              + "\n").encode("utf-8")
    return result, len(line) - len(result)


def _identity(pid: int) -> str:
    # /proc/stat's command can contain spaces; starttime is field 22.
    fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    return fields[19]


def writers(path: Path) -> list[tuple[int, str, bool]]:
    """Identify every local writable FD on this inode, not merely its name."""
    if os.name == "nt":
        raise RuntimeError("Windows history maintenance cannot verify all active writers.")
    target = path.stat()
    found = {}
    for proc in Path("/proc").glob("[0-9]*"):
        try:
            for fd in (proc / "fd").iterdir():
                info = (proc / "fdinfo" / fd.name).read_text()
                flags = int(re.search(r"^flags:\s+(\d+)", info, re.M)[1], 8)
                if flags & os.O_ACCMODE == os.O_RDONLY:
                    continue
                meta = fd.stat()
                if (meta.st_dev, meta.st_ino) != (target.st_dev, target.st_ino):
                    continue
                pid = int(proc.name)
                executable = Path(os.readlink(proc / "exe")).name
                allowed = (executable == "codex" and bool(flags & os.O_APPEND)
                           and meta.st_size < 2 * 1024**3)
                found[pid] = (pid, _identity(pid), allowed)
        except (OSError, ValueError, TypeError):
            continue
    return list(found.values())


def _resume(owners) -> None:
    for pid, start, _ in owners:
        try:
            if _identity(pid) == start:
                os.kill(pid, signal.SIGCONT)
        except (OSError, ValueError):
            pass


def _restore(path: Path, backup: Path, inode: int) -> None:
    if path.stat().st_ino != inode:
        raise RuntimeError("Recovery inode changed")
    with gzip.open(backup, "rb") as source, path.open("r+b") as output:
        shutil.copyfileobj(source, output, _COPY)
        output.truncate()
        output.flush()
        os.fsync(output.fileno())


def _sync_directory(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def watchdog(fd: int, path: Path, backup: Path, inode: int, owners, parent: int):
    """Restore a paused writer's log if its maintenance process dies mid-commit."""
    try:
        ready, _, _ = select.select([fd], [], [], 20)
        if ready and os.read(fd, 16) == b"done":
            return
        if not ready:
            # Prevent the parent continuing a timed-out write during recovery.
            try:
                os.kill(parent, signal.SIGKILL)
            except ProcessLookupError:
                pass
        # The journal is complete before this marker is created. Before it,
        # the original file has not been overwritten and needs no restore.
        marker = path.with_name("." + path.name + ".image-commit")
        if marker.exists():
            _restore(path, backup, inode)
            marker.unlink()
        backup.unlink(missing_ok=True)
    finally:
        _resume(owners)
        os.close(fd)


def _session_root(path: Path) -> Path:
    root = next((parent for parent in path.parents
                 if parent.name in {"sessions", "archived_sessions"}), None)
    if root is None:
        raise RuntimeError("Unknown session root")
    return root


def _session_metadata(path: Path) -> tuple[dict, Path]:
    with path.open("rb") as source:
        record = json.loads(source.readline())
    if record.get("type") != "session_meta":
        raise ValueError("Missing session metadata")
    return record["payload"], _session_root(path)


def _repair_projection(path: Path, *, force: bool = False) -> bool:
    """Discard only this thread's derived cache; Codex replays its log.

    Normal validation also works for a daemon-held append-only history: freeze
    the SQLite checkpoint, then read only its immutable JSONL prefix. Forced
    invalidation requires the caller to own the session writer lock.
    Actual task_complete/turn_aborted records are never changed.
    """
    metadata, root = _session_metadata(path)
    database = root.parent / "thread_history_1.sqlite"
    if not database.exists():
        return False
    sid = str(metadata.get("session_id") or metadata.get("id") or "")
    paginated = metadata.get("history_mode") == "paginated"
    tables = ("thread_items", "thread_realtime_items", "thread_turns",
              "thread_history_projection_state")
    # mode=rw must not create an empty replacement database if it disappears.
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=rw",
                                 uri=True, timeout=2)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        available = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        required = set(tables) - {"thread_realtime_items"}
        if not required <= available:
            raise RuntimeError("Unsupported history projection schema")
        state = connection.execute(
            "SELECT next_rollout_byte_offset, next_rollout_ordinal "
            "FROM thread_history_projection_state WHERE thread_id=?", (sid,)
        ).fetchone()
        connection.row_factory = sqlite3.Row
        projected = {row["turn_id"]: dict(row) for row in connection.execute(
            "SELECT * FROM thread_turns WHERE thread_id=?", (sid,))}
        invalid = force
        if not force and paginated:
            if state is None:
                invalid = bool(projected) or any(connection.execute(
                    f"SELECT 1 FROM {table} WHERE thread_id=? LIMIT 1", (sid,)
                ).fetchone() for table in tables if table in available)
            else:
                cursor, next_ordinal = state
                # Appending new records cannot alter this prefix. Projection
                # writes wait on our transaction, so the checkpoint cannot
                # race forward while its source records are being validated.
                events = []
                ordinal_count = 0
                with path.open("rb") as source:
                    while source.tell() < cursor:
                        offset = source.tell()
                        line = source.readline()
                        if (not line or not line.endswith(b"\n")
                                or source.tell() > cursor):
                            invalid = True
                            break
                        record = json.loads(line)
                        ordinal = record.get("ordinal")
                        if type(ordinal) is not int or ordinal != ordinal_count:
                            raise ValueError("Invalid paginated history ordinal")
                        ordinal_count += 1
                        payload = record.get("payload", {})
                        if (record.get("type") == "event_msg"
                                and payload.get("type") in {
                                    "task_started", "task_complete", "turn_aborted"}):
                            events.append((offset, source.tell(), ordinal, payload))
                    invalid |= (source.tell() != cursor
                                or ordinal_count != next_ordinal)
                expected = {}
                for offset, end, ordinal, payload in events:
                    tid = payload.get("turn_id")
                    if not tid:
                        continue
                    turn = expected.setdefault(tid, {})
                    kind = payload["type"]
                    if kind == "task_started":
                        turn.update(status="inProgress", rollout_ordinal=ordinal,
                                    rollout_byte_offset=offset)
                    elif kind == "task_complete":
                        turn.update(status="failed" if payload.get("error")
                                    else "completed", rollout_end_ordinal=ordinal,
                                    rollout_end_byte_offset=end)
                    else:
                        turn.update(status="interrupted")
                invalid |= set(expected) != set(projected)
                invalid |= any(
                    projected.get(tid, {}).get(key) != value
                    for tid, turn in expected.items() for key, value in turn.items())
        if not invalid:
            return False
        changed = False
        for table in tables:
            if table in available:
                result = connection.execute(
                    f"DELETE FROM {table} WHERE thread_id=?", (sid,))
                changed |= result.rowcount > 0
        # A crash after this commit and before publishing a cleaned log is
        # safe: Codex can rebuild from either complete version of the log.
        return changed


def _writer_gate(path: Path):
    """Use Codex's own session lock so opening a closed log cannot race us."""
    try:
        with path.open("rb") as source:
            payload = json.loads(source.readline()).get("payload", {})
    except (ValueError, UnicodeError):
        # A recovery journal can exist while the first line was being copied.
        match = re.search(r"-([0-9a-fA-F-]{36})\.jsonl$", path.name)
        payload = {"id": match[1] if match else ""}
    sid = str(payload.get("session_id") or payload.get("id") or "")
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", sid):
        raise RuntimeError("Unknown session metadata")
    root = _session_root(path)
    directory = root.parent / "thread-writer-locks"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock = (directory / (sid + ".lock")).open("a+b")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        return None
    return lock


def clean_session(path: Path, *, live: bool = False) -> dict:
    # `live` is accepted for old callers, but no active history may be changed.
    gate = _writer_gate(path)
    try:
        if gate is None:
            return {"status": "busy"}
        return _clean_session(path)
    finally:
        if gate is not None:
            gate.close()


def _clean_session(path: Path) -> dict:
    """Migrate a closed JSONL and discard its old derived byte offsets."""
    original = path.stat()
    if not stat.S_ISREG(original.st_mode) or path.is_symlink():
        return {"status": "skipped"}
    if writers(path):
        return {"status": "busy"}
    stage = path.with_name("." + path.name + ".image-stage")
    backup = path.with_name("." + path.name + ".image-recovery.gz")
    saved = records = 0
    # An old recovery file must be handled before generating another backup.
    if backup.exists():
        return {"status": "recovery_pending"}
    try:
        with path.open("rb") as source, stage.open("wb") as output:
            os.chmod(stage, 0o600)
            # A session writer must stay excluded for the entire publication.
            end = original.st_size
            while source.tell() < end:
                line = source.readline()
                if not line.endswith(b"\n"):
                    return {"status": "partial"}
                clean, difference = transformed(line)
                saved += difference
                records += 1
                output.write(clean)
            if (path.stat().st_size != original.st_size
                    or path.stat().st_mtime_ns != original.st_mtime_ns
                    or writers(path)):
                return {"status": "busy"}
            if not saved:
                repaired = _repair_projection(path)
                return {"status": "unchanged", "records": records,
                        "repaired": int(repaired)}
            output.flush()
            os.fsync(output.fileno())
        repaired = _repair_projection(path, force=True)
        os.chmod(stage, stat.S_IMODE(original.st_mode))
        os.utime(stage, ns=(original.st_atime_ns, original.st_mtime_ns))
        os.replace(stage, path)
        _sync_directory(path.parent)
        return {"status": "cleaned", "saved": saved, "records": records,
                "repaired": int(repaired)}
    finally:
        stage.unlink(missing_ok=True)


def _recover_pending(root: Path) -> None:
    for backup in root.rglob(".*.jsonl.image-recovery.gz"):
        path = backup.with_name(backup.name[1:-len(".image-recovery.gz")])
        marker = path.with_name("." + path.name + ".image-commit")
        gate = _writer_gate(path)
        if gate is None:
            if marker.exists():
                raise RuntimeError("Session recovery is already in progress")
            continue
        try:
            if writers(path):
                if marker.exists():
                    raise RuntimeError("Session recovery still has an active writer")
                continue
            if marker.exists():
                inode = json.loads(marker.read_text())["inode"]
                _restore(path, backup, inode)
                _repair_projection(path, force=True)
                marker.unlink()
            backup.unlink()
            _sync_directory(path.parent)
        finally:
            gate.close()


def maintain(root: Path, *, live: bool = False, stamps=None) -> dict:
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    totals = {"cleaned": 0, "saved": 0, "repaired": 0, "busy": 0, "errors": 0}
    with (root / ".image-storage.lock").open("a+b") as lock:
        os.chmod(lock.name, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return totals
        # A power interruption can leave the durable journal behind. Repair
        # closed logs before any later Codex launch can read them.
        _recover_pending(root)
        for path in sorted(root.rglob("*.jsonl"), key=lambda p: p.stat().st_size):
            try:
                meta = path.stat()
                stamp = (meta.st_size, meta.st_mtime_ns)
                if stamps is not None and stamps.get(path) == stamp:
                    continue
                result = clean_session(path, live=live)
                status = result["status"]
                totals["repaired"] += result.get("repaired", 0)
                if status == "cleaned":
                    totals["cleaned"] += 1
                    totals["saved"] += result["saved"]
                elif status in {"busy", "partial", "recovery_pending"}:
                    totals["busy"] += 1
                if stamps is not None and status in {"cleaned", "unchanged"}:
                    current = path.stat()
                    stamps[path] = (current.st_size, current.st_mtime_ns)
            except (OSError, ValueError, RuntimeError, sqlite3.Error):
                totals["errors"] += 1
    return totals


def prepare_resume(path: Path) -> dict:
    """Validate a selected session before Codex reloads its paginated history.

    A shared daemon can retain a writer after its TUI closes. In that case only
    repair the transactional cache; never rewrite or interrupt the live log.
    """
    if os.name == "nt":
        _session_metadata(path)
        if path.is_symlink() or path.with_name("." + path.name + ".image-commit").exists():
            raise RuntimeError("Session requires Linux history recovery before resuming.")
        with path.open("rb") as source:
            for line in source:
                json.loads(line)
        return {"status": "unchanged", "history_maintenance": "UNAVAILABLE_WINDOWS"}
    root = _session_root(path)
    with (root / ".image-storage.lock").open("a+b") as lock:
        deadline = time.monotonic() + 2
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    return {"status": "busy"}
                time.sleep(0.02)
        _recover_pending(root)
        result = clean_session(path)
        if result["status"] == "busy":
            repaired = _repair_projection(path)
            return {"status": "unchanged", "repaired": int(repaired),
                    "active_history": True}
        return result


def start_guard(root: Path, owner_pid: int):
    """A storage worker bound to this desktop process, not a free agent."""
    if os.name == "nt":
        raise RuntimeError("Windows history maintenance is not supported; history stays unchanged.")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Repair a power-interrupted transaction before the TUI opens history.
    if any(root.rglob(".*.jsonl.image-commit")):
        with (root / ".image-storage.lock").open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            _recover_pending(root)
    return subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "guard", "--root",
         str(root), "--parent", str(owner_pid), "--owner-start", _identity(owner_pid)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, start_new_session=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("migrate", "guard", "watchdog"))
    parser.add_argument("--root", type=Path)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--parent", type=int)
    parser.add_argument("--owner-start")
    parser.add_argument("--fd", type=int)
    parser.add_argument("--path", type=Path)
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--inode", type=int)
    parser.add_argument("--owners")
    args = parser.parse_args()
    if args.mode == "watchdog":
        watchdog(args.fd, args.path, args.backup, args.inode,
                 json.loads(args.owners), args.parent)
    elif args.mode == "migrate":
        print(json.dumps(maintain(args.root, live=args.live)))
    else:
        # One guard per home, even if two desktop windows share the home.
        with (args.root.parent / ".image-storage-guard.lock").open("a+b") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return
            stamps = {}
            while True:
                try:
                    if _identity(args.parent) != args.owner_start:
                        break
                except (OSError, ValueError):
                    break
                try:
                    totals = maintain(args.root, stamps=stamps)
                except (OSError, ValueError, RuntimeError, sqlite3.Error):
                    totals = {"cleaned": 0, "saved": 0, "repaired": 0,
                              "busy": 0, "errors": 1}
                # Small operational status, never images or conversation text.
                status = args.root.parent / "image-storage-status.json"
                temporary = status.with_suffix(".tmp")
                temporary.write_text(json.dumps({
                    "policy": "references-only-closed-history",
                    "updated_at": time.time(),
                    **totals}), encoding="utf-8")
                os.chmod(temporary, 0o600)
                os.replace(temporary, status)
                time.sleep(30)


if __name__ == "__main__":
    main()
