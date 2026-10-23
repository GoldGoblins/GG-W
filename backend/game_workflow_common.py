"""Bounded, data-only primitives for the game-independent research workflows."""
from __future__ import annotations

from backend.application_paths import STATE_ROOT
from backend.platform_files import secure_open, NOFOLLOW, CLOEXEC, NONBLOCK, sync_directory

import hashlib
import json
import os
import re
from pathlib import Path
import stat
import tempfile
from urllib.parse import unquote, urlparse

ROOT = Path(os.environ.get("GG_GAME_WORKFLOWS_ROOT", str(STATE_ROOT / 'game-workflows')))
MAX_FILE = 32 * 1024 * 1024
MAX_JSON = 4 * 1024 * 1024
SCHEMA = "gg.game-workflows.v1"


def local_path(raw: str, *, directory: bool = False) -> Path:
    value = str(raw or "").strip()
    if value.startswith("file:"):
        parsed = urlparse(value)
        if parsed.netloc not in ("", "localhost") or parsed.query or parsed.fragment:
            raise ValueError("LOCAL_PATH_REQUIRED")
        value = unquote(parsed.path)
    elif "://" in value:
        raise ValueError("LOCAL_PATH_REQUIRED")
    if not value or "\0" in value:
        raise ValueError("SELECT_LOCAL_PATH")
    path = Path(value).expanduser()
    if path.is_symlink():
        raise ValueError("SYMLINK_NOT_SUPPORTED")
    path = path.resolve(strict=True)
    if directory and not path.is_dir():
        raise ValueError("DIRECTORY_REQUIRED")
    return path


def read_file(raw: str | Path, limit: int = MAX_FILE, *, root: Path | None = None) -> tuple[Path, bytes]:
    path = local_path(str(raw))
    if root is not None and not path.is_relative_to(root.resolve()):
        raise ValueError("PATH_OUTSIDE_SELECTED_ROOT")
    descriptor = secure_open(path, os.O_RDONLY | NOFOLLOW | NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("REGULAR_FILE_REQUIRED")
        if before.st_size > limit:
            raise ValueError("FILE_TOO_LARGE")
        data = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
        if len(data) > limit or len(data) != before.st_size:
            raise ValueError("FILE_SIZE_CHANGED")
        if (before.st_mtime_ns, before.st_ctime_ns) != (after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError("FILE_CHANGED_DURING_READ")
    return path, data


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _pairs(items):
    value = {}
    for key, item in items:
        if key in value:
            raise ValueError("DUPLICATE_JSON_KEY")
        value[key] = item
    return value


def parse_json(data: bytes, *, max_nodes: int = 100000) -> dict:
    def invalid(_):
        raise ValueError("NON_FINITE_JSON")
    try:
        value = json.loads(data, object_pairs_hook=_pairs, parse_constant=invalid)
    except (RecursionError, UnicodeError) as exc:
        raise ValueError("INVALID_JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("JSON_OBJECT_REQUIRED")
    stack = [(value, 0)]
    count = 0
    while stack:
        item, depth = stack.pop()
        count += 1
        if count > min(max_nodes, 250000) or depth > 24:
            raise ValueError("JSON_STRUCTURE_LIMIT")
        if isinstance(item, dict):
            stack.extend((v, depth + 1) for v in item.values())
        elif isinstance(item, list):
            stack.extend((v, depth + 1) for v in item)
    return value


def read_json(raw: str | Path) -> tuple[Path, dict, str]:
    path, data = read_file(raw, MAX_JSON)
    return path, parse_json(data), digest(data)


def write_bytes(path: Path, data: bytes, *, limit: int = MAX_FILE) -> Path:
    """Only generated workflow state is writable; original assets stay read-only."""
    root = ROOT.resolve()
    path = path.resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError("OUTPUT_OUTSIDE_WORKFLOW_STORE")
    if len(data) > limit:
        raise ValueError("OUTPUT_TOO_LARGE")
    packet_root = (ROOT / "packets").resolve()
    if path.is_relative_to(packet_root):
        files = list(packet_root.iterdir()) if packet_root.exists() else []
        if len(files) >= 512 and not path.exists():
            raise ValueError("PACKET_COUNT_LIMIT_ARCHIVE_EXISTING_EVIDENCE")
        total = sum(p.stat().st_size for p in files if p.is_file() and not p.is_symlink() and p != path)
        if total + len(data) > 64 * 1024 * 1024:
            raise ValueError("PACKET_BYTE_LIMIT_ARCHIVE_EXISTING_EVIDENCE")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return path


def write_json(path: Path, value: dict) -> Path:
    data = (json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2) + "\n").encode()
    return write_bytes(path, data, limit=MAX_JSON)


def packet(kind: str, value: dict) -> Path:
    data = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()
    path = ROOT / "packets" / (kind + "-" + digest(data)[:24] + ".json")
    if path.exists():
        _, existing, _ = read_json(path)
        stored = json.dumps(existing, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()
        if stored != data:
            raise ValueError("PACKET_CONTENT_CHANGED")
        return path
    return write_json(path, value)


def artifact(kind: str, data: bytes, suffix: str = ".png") -> Path:
    """Content-addressed binary evidence; repeated captures never overwrite it."""
    if not re.fullmatch(r"[a-z0-9_-]{1,80}", kind) or suffix not in (".png", ".glb", ".bin"):
        raise ValueError("INVALID_ARTIFACT_KIND")
    path = ROOT / "packets" / (kind + "-" + digest(data)[:24] + suffix)
    if path.exists():
        if digest(read_file(path)[1]) != digest(data):
            raise ValueError("BINARY_EVIDENCE_CHANGED")
        return path
    return write_bytes(path, data)


def error(exc: Exception) -> dict:
    return {"schema": SCHEMA, "status": "ERROR", "reason": str(exc) if isinstance(exc, ValueError) else type(exc).__name__}
