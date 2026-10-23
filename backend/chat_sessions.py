from __future__ import annotations

from backend.application_paths import STATE_ROOT

import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from backend.platform_support import file_locks as fcntl

from backend.grok_worker_contract import ENGINE_GROK_TUI, GROK_CWD

CATALOG_PATH = Path(
    str(STATE_ROOT / 'chat-sessions.json')
)
SCHEMA = "gg.ai-desktop.chat-sessions.v1"
MEMORY = "GoldGoblins"

# Long GoldGoblins work chat (Konsole) — same memory, openable from CHATS.
PROJECT_SESSIONS = (
    ("01a01c8b-5b86-7150-bd01-be262a34eb0d", "GROK_TUI"),
)

ENGINE_LABEL = {
    "GROK_TUI": "GROK TUI",
    "GROK_WORKER": "GROK",
    "LOCAL_QWEN": "QWEN",
    "GPT_TUI": "GPTUI",
    "FLOW_TUI": "FLOW TUI",
}


def _empty() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "memory": MEMORY,
        "cwd": str(GROK_CWD),
        "sessions": [],
    }


def _read_catalog(target: Path) -> dict[str, Any]:
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return _empty()
    if not isinstance(payload, dict):
        return _empty()
    rows = payload.get("sessions")
    if not isinstance(rows, list):
        rows = []
    payload["schema"] = SCHEMA
    payload["memory"] = MEMORY
    payload["cwd"] = str(GROK_CWD)
    payload["sessions"] = [row for row in rows if isinstance(row, dict)]
    return payload


@contextmanager
def _catalog_lock(target: Path):
    """Serialize catalog read/modify/write operations across both motors."""
    handle = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        handle = (target.with_name(target.name + ".lock")).open(
            "a+", encoding="utf-8"
        )
    except OSError:
        # Preserve the old best-effort behavior if the state directory is not
        # writable. The caller's atomic write will still fail closed.
        yield
        return
    try:
        if fcntl is not None:
            fcntl.flock(handle, fcntl.LOCK_EX)
        yield
    finally:
        try:
            if fcntl is not None:
                fcntl.flock(handle, fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            handle.close()
        except OSError:
            pass


def _write_catalog_unlocked(payload: dict[str, Any], target: Path) -> None:
    """Atomically replace a catalog; caller owns the per-file lock."""
    target.parent.mkdir(parents=True, exist_ok=True)
    body = (json.dumps(payload, indent=2) + "\n").encode("utf-8")
    fd, temporary_name = tempfile.mkstemp(
        prefix="." + target.name + ".",
        dir=str(target.parent),
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
    finally:
        try:
            temporary.unlink()
        except OSError:
            pass


def load_catalog(path: Path | None = None) -> dict[str, Any]:
    target = path or CATALOG_PATH
    payload = _read_catalog(target)
    if target == CATALOG_PATH and _ensure_project_sessions(payload):
        # Re-read while holding the lock so a simultaneous GROK/GPT append is
        # never overwritten by the project-session seed write.
        with _catalog_lock(target):
            payload = _read_catalog(target)
            if _ensure_project_sessions(payload):
                try:
                    _write_catalog_unlocked(payload, target)
                except OSError:
                    pass
    return payload


def _ensure_project_sessions(catalog: dict[str, Any]) -> bool:
    original_count = len(catalog.get("sessions") or [])
    catalog["sessions"] = [
        row
        for row in catalog.get("sessions") or []
        if str(row.get("session_id") or "").strip() != "ws.tui.gpt"
    ]
    have = {
        str(row.get("session_id") or "").strip()
        for row in catalog.get("sessions") or []
    }
    next_n = 1
    for row in catalog.get("sessions") or []:
        try:
            n = int(row.get("n") or 0)
        except (TypeError, ValueError):
            n = 0
        if n >= next_n:
            next_n = n + 1
    changed = len(catalog["sessions"]) != original_count
    for sid, engine in PROJECT_SESSIONS:
        if sid in have:
            continue
        catalog.setdefault("sessions", []).append(
            {
                "n": next_n,
                "session_id": sid,
                "engine": engine,
            }
        )
        next_n += 1
        changed = True
    return changed


def save_catalog(payload: dict[str, Any], path: Path | None = None) -> None:
    target = path or CATALOG_PATH
    try:
        with _catalog_lock(target):
            _write_catalog_unlocked(payload, target)
    except OSError:
        return


def _remember_in_catalog(
    catalog: dict[str, Any],
    session_id: str,
    engine: str,
) -> bool:
    sid = str(session_id or "").strip()
    if not sid:
        return False
    for row in catalog["sessions"]:
        if str(row.get("session_id") or "") == sid:
            if not row.get("engine"):
                row["engine"] = engine
                return True
            return False
    next_n = 1
    for row in catalog["sessions"]:
        try:
            n = int(row.get("n") or 0)
        except (TypeError, ValueError):
            n = 0
        if n >= next_n:
            next_n = n + 1
    catalog["sessions"].append(
        {
            "n": next_n,
            "session_id": sid,
            "engine": engine,
        }
    )
    return True


def remember_session(
    session_id: str,
    engine: str = ENGINE_GROK_TUI,
    path: Path | None = None,
) -> dict[str, Any]:
    sid = str(session_id or "").strip()
    motor = str(engine or ENGINE_GROK_TUI).strip() or ENGINE_GROK_TUI
    target = path or CATALOG_PATH
    with _catalog_lock(target):
        catalog = _read_catalog(target)
        changed = False
        if target == CATALOG_PATH:
            changed = _ensure_project_sessions(catalog)
        changed = _remember_in_catalog(catalog, sid, motor) or changed
        if changed:
            try:
                _write_catalog_unlocked(catalog, target)
            except OSError:
                pass
    return catalog


def sync_owned(
    session_ids: set[str] | list[str],
    engine: str = ENGINE_GROK_TUI,
    path: Path | None = None,
) -> dict[str, Any]:
    target = path or CATALOG_PATH
    motor = str(engine or ENGINE_GROK_TUI).strip() or ENGINE_GROK_TUI
    with _catalog_lock(target):
        catalog = _read_catalog(target)
        changed = False
        if target == CATALOG_PATH:
            changed = _ensure_project_sessions(catalog)
        for sid in sorted({str(item) for item in session_ids}):
            changed = _remember_in_catalog(catalog, sid, motor) or changed
        if changed:
            try:
                _write_catalog_unlocked(catalog, target)
            except OSError:
                pass
    return catalog


def forget_session(
    session_id: str,
    path: Path | None = None,
) -> dict[str, Any]:
    """Remove one catalog pointer without touching the real session file."""
    sid = str(session_id or "").strip()
    target = path or CATALOG_PATH
    with _catalog_lock(target):
        catalog = _read_catalog(target)
        changed = False
        if target == CATALOG_PATH:
            changed = _ensure_project_sessions(catalog)
        rows = catalog.get("sessions") or []
        if sid:
            kept = [
                row
                for row in rows
                if str(row.get("session_id") or "").strip() != sid
            ]
            if len(kept) != len(rows):
                catalog["sessions"] = kept
                changed = True
        if changed:
            try:
                _write_catalog_unlocked(catalog, target)
            except OSError:
                pass
    return catalog


def list_for_ui(
    current_id: str = "",
    path: Path | None = None,
) -> list[dict[str, Any]]:
    catalog = load_catalog(path)
    current = str(current_id or "").strip()
    rows: list[dict[str, Any]] = []
    for row in catalog.get("sessions") or []:
        sid = str(row.get("session_id") or "").strip()
        if not sid:
            continue
        try:
            n = int(row.get("n") or 0)
        except (TypeError, ValueError):
            n = 0
        engine = str(row.get("engine") or ENGINE_GROK_TUI)
        label = ENGINE_LABEL.get(engine, engine.replace("_", " "))
        rows.append(
            {
                "n": n,
                "session_id": sid,
                "engine": engine,
                "label": "session " + str(n) + "  ·  " + label,
                "current": sid == current,
                "memory": MEMORY,
            }
        )
    rows.sort(key=lambda item: int(item["n"]), reverse=True)
    return rows
