"""Read the local Codex session usage records for the telemetry rail."""

from __future__ import annotations

from backend.application_paths import STATE_ROOT, USER_CODEX_HOME, WORKSPACE_ROOT

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

CODEX_SESSIONS = Path(str(USER_CODEX_HOME / 'sessions'))
CODEX_SESSION_STATE = Path(
    str(STATE_ROOT / 'codex-tui-session.json')
)
DESKTOP_CODEX_HOME = Path(
    str(STATE_ROOT / 'codex-gpt-tui')
)
DESKTOP_CODEX_SESSIONS = DESKTOP_CODEX_HOME / "sessions"
DESKTOP_CODEX_SESSION_STATE = DESKTOP_CODEX_HOME / "active-session.json"
_SESSION_ID_RE = re.compile(r"^[0-9a-fA-F-]{36}$")
_SESSION_PATH_CACHE: dict[tuple[str, str], Path] = {}
_SNAPSHOT_CACHE: dict[str, tuple[int, int, dict[str, Any]]] = {}


def _fmt(value: int | None) -> str:
    if value is None or value < 0:
        return "—"
    if value >= 1_000_000:
        text = f"{value / 1_000_000:.2f}M"
        return text.replace(".00M", "M")
    if value >= 1000:
        return f"{value // 1000}K"
    return str(value)


def _reset_label(value: Any) -> str:
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return "—"
    if timestamp <= 0:
        return "—"
    try:
        return datetime.fromtimestamp(timestamp).astimezone().strftime("%H:%M")
    except (OverflowError, OSError, ValueError):
        return "—"


def _latest_session(sessions_root: Path = CODEX_SESSIONS) -> Path | None:
    try:
        rows = list(sessions_root.rglob("*.jsonl"))
    except OSError:
        return None
    if not rows:
        return None
    return max(rows, key=lambda path: path.stat().st_mtime)


def _session_meta(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8", errors="replace") as stream:
            row = json.loads(stream.readline())
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    payload = row.get("payload") if isinstance(row, dict) else None
    return payload if isinstance(payload, dict) else {}


def session_id_from_file(path: Path) -> str:
    meta = _session_meta(path)
    sid = str(meta.get("session_id") or meta.get("id") or "").strip()
    return sid if _SESSION_ID_RE.fullmatch(sid) else ""


def session_path(
    session_id: str,
    sessions_root: Path = CODEX_SESSIONS,
) -> Path | None:
    sid = str(session_id or "").strip()
    if _SESSION_ID_RE.fullmatch(sid) is None:
        return None
    cache_key = (str(sessions_root), sid)
    cached = _SESSION_PATH_CACHE.get(cache_key)
    if cached is not None:
        try:
            if cached.is_file():
                return cached
        except OSError:
            pass
        _SESSION_PATH_CACHE.pop(cache_key, None)
    try:
        paths = sessions_root.rglob("*.jsonl")
        for path in paths:
            if session_id_from_file(path) == sid:
                _SESSION_PATH_CACHE[cache_key] = path
                return path
    except OSError:
        return None
    return None


def discover_sessions(
    cwd: str = str(WORKSPACE_ROOT),
    sessions_root: Path = CODEX_SESSIONS,
) -> list[str]:
    """Return real saved Codex sessions for this workspace, newest first."""
    rows: list[tuple[float, str]] = []
    try:
        paths = sessions_root.rglob("*.jsonl")
    except OSError:
        return []
    for path in paths:
        meta = _session_meta(path)
        if str(meta.get("cwd") or "") != cwd:
            continue
        sid = session_id_from_file(path)
        if sid:
            try:
                rows.append((path.stat().st_mtime, sid))
            except OSError:
                pass
    rows.sort(reverse=True)
    return list(dict.fromkeys(sid for _mtime, sid in rows))


def load_session_id(path: Path = CODEX_SESSION_STATE) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return ""
    sid = str(payload.get("session_id") or "") if isinstance(payload, dict) else ""
    return sid if _SESSION_ID_RE.fullmatch(sid) else ""


def save_session_id(session_id: str, path: Path = CODEX_SESSION_STATE) -> str:
    sid = str(session_id or "").strip()
    if not _SESSION_ID_RE.fullmatch(sid):
        return ""
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.write_text(json.dumps({"session_id": sid}) + "\n", encoding="utf-8")
    except OSError:
        return ""
    return sid


def clear_session_id(path: Path = CODEX_SESSION_STATE) -> bool:
    """Clear only the active-session pointer, preserving all session files."""
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
    except OSError:
        return False
    return True


def snapshot(
    session: Path | None = None,
    sessions_root: Path = CODEX_SESSIONS,
) -> dict[str, Any]:
    path = session or _latest_session(sessions_root)
    stamp: tuple[int, int] | None = None
    if path is not None:
        try:
            stat = path.stat()
            stamp = (int(stat.st_mtime_ns), int(stat.st_size))
        except OSError:
            path = None
        if stamp is not None:
            cached = _SNAPSHOT_CACHE.get(str(path))
            if cached is not None and cached[:2] == stamp:
                return dict(cached[2])
    latest_tokens: dict[str, Any] = {}
    latest_turn: dict[str, Any] = {}
    latest_limits: dict[str, Any] = {}
    if path is not None:
        try:
            with path.open(encoding="utf-8", errors="replace") as stream:
                for line in stream:
                    try:
                        row = json.loads(line)
                    except (json.JSONDecodeError, TypeError):
                        continue
                    payload = row.get("payload") if isinstance(row, dict) else None
                    if not isinstance(payload, dict):
                        continue
                    if payload.get("type") == "token_count":
                        info = payload.get("info") or {}
                        usage = info.get("total_token_usage")
                        if isinstance(usage, dict):
                            latest_tokens = usage
                        turn_usage = info.get("last_token_usage")
                        if isinstance(turn_usage, dict):
                            latest_turn = turn_usage
                        window = info.get("model_context_window")
                        if window is not None:
                            latest_tokens["model_context_window"] = window
                    limits = payload.get("rate_limits")
                    if isinstance(limits, dict):
                        latest_limits = limits
        except OSError:
            pass

    total = latest_tokens.get("total_tokens")
    context_used = latest_turn.get("input_tokens")
    context_window = latest_tokens.get("model_context_window")
    turn = latest_turn.get("total_tokens")
    primary = latest_limits.get("primary") or {}
    secondary = latest_limits.get("secondary") or {}
    try:
        total_n = int(total) if total is not None else None
    except (TypeError, ValueError):
        total_n = None
    try:
        context_n = int(context_used) if context_used is not None else None
    except (TypeError, ValueError):
        context_n = None
    try:
        window_n = int(context_window) if context_window is not None else None
    except (TypeError, ValueError):
        window_n = None
    try:
        turn_n = int(turn) if turn is not None else None
    except (TypeError, ValueError):
        turn_n = None
    try:
        weekly = float(secondary.get("used_percent"))
        weekly_n = int(round(weekly)) if 0 <= weekly <= 100 else None
    except (TypeError, ValueError):
        weekly_n = None
    try:
        live = float(primary.get("used_percent"))
        live_n = int(round(live)) if 0 <= live <= 100 else 0
    except (TypeError, ValueError):
        live_n = 0
    live_reset_at = primary.get("resets_at")
    result = {
        "session": str(path) if path else "",
        "context_label": _fmt(context_n) + "/" + _fmt(window_n) if context_n is not None and window_n is not None else "—",
        "session_total_label": _fmt(total_n),
        "turn_label": _fmt(turn_n),
        "live_tokens": live_n,
        "live_label": str(live_n) + "%",
        "live_reset_at": live_reset_at,
        "live_reset_label": _reset_label(live_reset_at),
        "weekly_percent": weekly_n,
        "context_used": context_n,
        "context_window": window_n,
        "session_total": total_n,
        "turn_tokens": turn_n,
    }
    if path is not None and stamp is not None:
        _SNAPSHOT_CACHE[str(path)] = (stamp[0], stamp[1], result)
    return result
