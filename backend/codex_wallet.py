"""Read the local Codex session usage records for the telemetry rail."""

from __future__ import annotations

from backend.application_paths import STATE_ROOT, USER_CODEX_HOME, WORKSPACE_ROOT

import json
import os
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
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
_MONTHS_SV = ("jan", "feb", "mars", "apr", "maj", "juni", "juli", "aug", "sep", "okt", "nov", "dec")


@dataclass
class _UsageRecord:
    identity: tuple[int, int]
    stamp: tuple[int, int] = (-1, -1)
    offset: int = 0
    anchor: bytes = b""
    tokens: dict[str, Any] = field(default_factory=dict)
    turn: dict[str, Any] = field(default_factory=dict)
    primary: dict[str, Any] = field(default_factory=dict)
    secondary: dict[str, Any] = field(default_factory=dict)
    limit_id: str | None = None
    result: dict[str, Any] = field(default_factory=dict)


_SNAPSHOT_CACHE: OrderedDict[str, _UsageRecord] = OrderedDict()
_SNAPSHOT_LOCK = threading.RLock()


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
    if isinstance(value, bool):
        return "—"
    try:
        timestamp = int(value)
    except (TypeError, ValueError, OverflowError):
        return "—"
    if timestamp <= 0:
        return "—"
    try:
        local = datetime.fromtimestamp(timestamp).astimezone()
        return local.strftime("%H:%M") + f" · {local.day} {_MONTHS_SV[local.month - 1]}"
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
    *,
    allow_latest: bool = True,
) -> dict[str, Any]:
    """Read provider records; unchanged polls do no JSONL reads.

    The first scan is streamed. Subsequent polls read only appended complete
    lines. An unfinished final line is retried after append; replacing or
    truncating the file discards the previous session's accumulated values.
    This function belongs in the host's background telemetry lane.
    """
    path = session or (_latest_session(sessions_root) if allow_latest else None)
    if path is None:
        return _result(None, _UsageRecord((0, 0)))
    with _SNAPSHOT_LOCK:
        try:
            stat = path.stat()
        except OSError:
            return _result(None, _UsageRecord((0, 0)))
        stamp = (int(stat.st_mtime_ns), int(stat.st_size))
        identity = (int(stat.st_dev), int(stat.st_ino))
        key = str(path)
        record = _SNAPSHOT_CACHE.get(key)
        if record is not None and record.identity == identity and record.stamp == stamp:
            _SNAPSHOT_CACHE.move_to_end(key)
            return dict(record.result)
        try:
            with path.open("rb") as stream:
                opened = os.fstat(stream.fileno())
                opened_identity = (int(opened.st_dev), int(opened.st_ino))
                opened_stamp = (int(opened.st_mtime_ns), int(opened.st_size))
                append = (record is not None and record.identity == opened_identity
                          and opened_stamp[1] > record.stamp[1] and opened_stamp[1] >= record.offset)
                if append and record.anchor:
                    stream.seek(record.offset - len(record.anchor))
                    append = stream.read(len(record.anchor)) == record.anchor
                if not append:
                    record = _UsageRecord(opened_identity)
                stream.seek(record.offset)
                while True:
                    line = stream.readline()
                    if not line or not line.endswith(b"\n"):
                        break
                    record.offset = stream.tell()
                    try:
                        row = json.loads(line)
                    except (ValueError, TypeError, UnicodeError, RecursionError):
                        continue
                    payload = row.get("payload") if isinstance(row, dict) else None
                    if isinstance(payload, dict):
                        _consume(record, payload)
                stream.seek(max(0, record.offset - 128))
                record.anchor = stream.read(min(128, record.offset))
                record.stamp = opened_stamp
        except OSError:
            return dict(record.result) if record is not None and record.result else _result(path, _UsageRecord(identity))
        record.result = _result(path, record)
        _SNAPSHOT_CACHE[key] = record
        _SNAPSHOT_CACHE.move_to_end(key)
        while len(_SNAPSHOT_CACHE) > 8:
            _SNAPSHOT_CACHE.popitem(last=False)
        return dict(record.result)


def _integer(value: Any, *, positive: bool = False) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
        if float(value) != number or number < (1 if positive else 0):
            return None
        return number
    except (TypeError, ValueError, OverflowError):
        return None


def _percent(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if 0 <= number <= 100 else None
    except (TypeError, ValueError, OverflowError):
        return None


def _consume(record: _UsageRecord, payload: dict[str, Any]) -> None:
    if payload.get("type") == "token_count":
        info = payload.get("info")
        if isinstance(info, dict):
            for source, target, fields in ((info.get("total_token_usage"), record.tokens, ("total_tokens",)),
                                           (info.get("last_token_usage"), record.turn, ("input_tokens", "total_tokens"))):
                if isinstance(source, dict):
                    for name in fields:
                        value = _integer(source.get(name))
                        if value is not None:
                            target[name] = value
            window = _integer(info.get("model_context_window"), positive=True)
            if window is not None:
                record.tokens["model_context_window"] = window
    limits = payload.get("rate_limits")
    if not isinstance(limits, dict):
        return
    limit_id = limits.get("limit_id")
    if isinstance(limit_id, str) and 0 < len(limit_id) <= 128:
        if record.limit_id is not None and record.limit_id != limit_id:
            record.primary.clear()
            record.secondary.clear()
        record.limit_id = limit_id
    for name in ("primary", "secondary"):
        incoming = limits.get(name)
        if not isinstance(incoming, dict):
            continue
        current = getattr(record, name)
        window = _integer(incoming.get("window_minutes"), positive=True)
        if window is not None:
            if current.get("window_minutes") is not None and current["window_minutes"] != window:
                current.clear()
            current["window_minutes"] = window
        percentage = _percent(incoming.get("used_percent"))
        reset_at = _integer(incoming.get("resets_at"), positive=True)
        if reset_at is not None and _reset_label(reset_at) != "—":
            if current.get("resets_at") is not None and current["resets_at"] != reset_at and percentage is None:
                # An explicitly different period cannot borrow the previous
                # period's percent when this provider update omits usage.
                current.pop("used_percent", None)
            current["resets_at"] = reset_at
        if percentage is not None:
            current["used_percent"] = percentage


def _result(path: Path | None, record: _UsageRecord) -> dict[str, Any]:
    total_n = record.tokens.get("total_tokens")
    context_n = record.turn.get("input_tokens")
    window_n = record.tokens.get("model_context_window")
    turn_n = record.turn.get("total_tokens")
    primary = record.primary
    secondary = record.secondary
    live = primary.get("used_percent")
    live_n = int(round(live)) if live is not None else None
    weekly = secondary.get("used_percent")
    weekly_n = int(round(weekly)) if weekly is not None else None
    live_reset_at = primary.get("resets_at")
    label = str(live_n) + "%" if live_n is not None else "—"
    return {
        "session": str(path) if path is not None else "",
        "context_label": _fmt(context_n) + "/" + _fmt(window_n) if context_n is not None and window_n is not None else "—",
        "session_total_label": _fmt(total_n),
        "turn_label": _fmt(turn_n),
        "live_tokens": live_n,
        "live_label": label,
        "live_reset_at": live_reset_at,
        "live_reset_label": _reset_label(live_reset_at),
        "weekly_percent": weekly_n,
        "limit_percent": live,
        "limit_label": label,
        "limit_reset_at": live_reset_at,
        "limit_reset_label": _reset_label(live_reset_at),
        "limit_window_minutes": primary.get("window_minutes"),
        "context_used": context_n,
        "context_window": window_n,
        "session_total": total_n,
        "turn_tokens": turn_n,
    }
