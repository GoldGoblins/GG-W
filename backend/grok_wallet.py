from __future__ import annotations

from backend.application_paths import STATE_ROOT

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from backend.grok_worker_contract import DEV_GROK_HOME, GROK_CWD

WALLET_INDEX = Path(
    str(STATE_ROOT / 'grok-tui-wallet-sessions.json')
)

_CTX_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*([KkMm])\s*/\s*(\d+(?:\.\d+)?)\s*([KkMm])"
)
_WEEK_RE = re.compile(
    r"(?:weekly|week(?:ly)?\s*limit)[^\d%]{0,32}(\d{1,3})\s*%",
    re.IGNORECASE,
)
_WEEK_RE2 = re.compile(
    r"(\d{1,3})\s*%[^\n]{0,32}(?:weekly|week)",
    re.IGNORECASE,
)
_WEEK_RE3 = re.compile(
    r"(\d{1,3})\s*%\s*(?:used|SuperGrok)",
    re.IGNORECASE,
)
_LOG_PERCENT = re.compile(r'"creditUsagePercent"\s*:\s*(\d+(?:\.\d+)?)')
_TAIL_CACHE: dict[str, tuple[int, int, Any]] = {}
_DISCOVER_CACHE: tuple[float, tuple[Any, ...], Any] | None = None


def _tail_cached(path: Path, max_bytes: int) -> str:
    key = str(path)
    try:
        st = path.stat()
    except OSError:
        _TAIL_CACHE.pop(key, None)
        return ""
    stamp = (st.st_mtime_ns, st.st_size)
    hit = _TAIL_CACHE.get(key)
    if hit is not None and hit[0] == stamp[0] and hit[1] == stamp[1]:
        return hit[2]
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    if len(data) > max_bytes:
        data = data[-max_bytes:]
    text = data.decode("utf-8", errors="replace")
    _TAIL_CACHE[key] = (stamp[0], stamp[1], text)
    return text


def format_tokens(count: int | None) -> str:
    if count is None:
        return "—"
    value = int(count)
    if value < 0:
        return "—"
    if value >= 1_000_000:
        scaled = value / 1_000_000
        text = f"{scaled:.2f}M"
        return text.replace(".00M", "M")
    if value >= 1000:
        return f"{value // 1000}K"
    return str(value)


def _unit_to_tokens(number: float, unit: str) -> int:
    scale = 1_000_000 if unit.upper() == "M" else 1000
    return int(round(number * scale))


def parse_pty_wallet(text: str) -> dict[str, Any]:
    found: dict[str, Any] = {}
    if not text:
        return found
    match = _CTX_RE.search(text)
    if match:
        used = _unit_to_tokens(float(match.group(1)), match.group(2))
        window = _unit_to_tokens(float(match.group(3)), match.group(4))
        found["context_used"] = used
        found["context_window"] = window
    return found


def quote_cwd(cwd: Path) -> str:
    return str(cwd).replace("/", "%2F")


def read_active_rows(home: Path | None = None) -> list[dict[str, Any]]:
    path = (home or DEV_GROK_HOME) / "active_sessions.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return []
    if not isinstance(payload, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in payload:
        if isinstance(item, dict):
            rows.append(item)
    return rows


def descendant_pids(root_pid: int) -> set[int]:
    found = {int(root_pid)}
    stack = [int(root_pid)]
    while stack:
        pid = stack.pop()
        path = Path("/proc") / str(pid) / "task" / str(pid) / "children"
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for piece in text.split():
            try:
                child = int(piece)
            except ValueError:
                continue
            if child not in found:
                found.add(child)
                stack.append(child)
    return found


def process_start_time(pid: int) -> float | None:
    try:
        return (Path("/proc") / str(pid)).stat().st_ctime
    except OSError:
        return None


def load_wallet_index(path: Path | None = None) -> set[str]:
    target = path or WALLET_INDEX
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return set()
    if isinstance(payload, dict):
        ids = payload.get("session_ids")
    else:
        ids = payload
    if not isinstance(ids, list):
        return set()
    return {str(item) for item in ids if str(item).strip()}


def save_wallet_index(ids: set[str], path: Path | None = None) -> None:
    target = path or WALLET_INDEX
    if load_wallet_index(target) == set(ids):
        return
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps({"session_ids": sorted(ids)}, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError:
        return


def session_spend(signals: dict[str, Any]) -> int:
    try:
        used = int(signals.get("contextTokensUsed") or 0)
    except (TypeError, ValueError):
        used = 0
    try:
        before = int(signals.get("totalTokensBeforeCompaction") or 0)
    except (TypeError, ValueError):
        before = 0
    return max(0, before + used)


def discover_program_sessions(
    home: Path | None = None,
    tui_pid: int | None = None,
    index_path: Path | None = None,
) -> tuple[Path | None, list[Path], set[str]]:
    global _DISCOVER_CACHE
    now = time.monotonic()
    cache_key = (str(home or ""), tui_pid, str(index_path or ""))
    packed = _DISCOVER_CACHE
    if (
        home is None
        and packed is not None
        and packed[1] == cache_key
        and now - packed[0] < 15.0
    ):
        return packed[2]
    root = (home or DEV_GROK_HOME) / "sessions"
    index = load_wallet_index(index_path)
    tui_pids: set[int] = set()
    started: float | None = None
    if tui_pid is not None:
        tui_pids = descendant_pids(int(tui_pid))
        started = process_start_time(int(tui_pid))
    foreign: set[str] = set()
    for row in read_active_rows(home):
        sid = str(row.get("session_id") or "").strip()
        try:
            pid = int(row.get("pid"))
        except (TypeError, ValueError):
            pid = None
        if not sid:
            continue
        if pid is not None and pid in tui_pids:
            index.add(sid)
        elif pid is not None and tui_pids and pid not in tui_pids:
            foreign.add(sid)
        elif pid is not None and not tui_pids:
            foreign.add(sid)
    preferred = quote_cwd(GROK_CWD)
    current: Path | None = None
    current_score = -1.0
    collected: list[Path] = []
    if root.is_dir():
        for signals in root.rglob("signals.json"):
            parent = signals.parent
            sid = parent.name
            if sid in foreign:
                continue
            try:
                mtime = signals.stat().st_mtime
            except OSError:
                continue
            in_project = preferred in parent.as_posix()
            owned = sid in index
            if not owned and tui_pids and started is not None and mtime >= started - 2:
                owned = True
                index.add(sid)
            if not owned:
                continue
            collected.append(parent)
            score = mtime + (1_000_000_000 if in_project else 0)
            if score > current_score:
                current_score = score
                current = parent
    save_wallet_index(index, index_path)
    if index and index_path is None:
        from backend.chat_sessions import sync_owned

        sync_owned(index, engine="GROK_TUI")
    result = (current, collected, index)
    if home is None:
        _DISCOVER_CACHE = (now, cache_key, result)
    return result


def latest_session_dir(
    home: Path | None = None,
    tui_pid: int | None = None,
    index_path: Path | None = None,
) -> Path | None:
    current, _dirs, _ids = discover_program_sessions(
        home=home,
        tui_pid=tui_pid,
        index_path=index_path,
    )
    return current


def read_signals(session: Path) -> dict[str, Any]:
    path = session / "signals.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def read_weekly_from_logs(home: Path | None = None) -> int | None:
    path = (home or DEV_GROK_HOME) / "logs" / "unified.jsonl"
    text = _tail_cached(path, 393216)
    if not text:
        return None
    last: int | None = None
    for line in text.splitlines():
        if "creditUsagePercent" not in line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            match = _LOG_PERCENT.search(line)
            if match:
                last = int(round(float(match.group(1))))
            continue
        ctx = row.get("ctx") if isinstance(row, dict) else None
        config = ctx.get("config") if isinstance(ctx, dict) else None
        percent = None
        if isinstance(config, dict):
            percent = config.get("creditUsagePercent")
        if percent is None:
            match = _LOG_PERCENT.search(line)
            if match:
                percent = match.group(1)
        try:
            value = int(round(float(percent)))
        except (TypeError, ValueError):
            continue
        if 0 <= value <= 100:
            last = value
    return last


def last_turn_usage(session: Path) -> dict[str, Any]:
    path = session / "updates.jsonl"
    text = _tail_cached(path, 262144)
    if not text:
        return {}
    last: dict[str, Any] = {}
    for line in text.splitlines():
        if "turn_completed" not in line or "usage" not in line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        params = row.get("params") if isinstance(row, dict) else None
        update = params.get("update") if isinstance(params, dict) else None
        if not isinstance(update, dict):
            continue
        if update.get("sessionUpdate") != "turn_completed":
            continue
        usage = update.get("usage")
        if isinstance(usage, dict):
            last = usage
    return last


def snapshot(
    home: Path | None = None,
    pty_overlay: dict[str, Any] | None = None,
    live_base: int | None = None,
    tui_pid: int | None = None,
    index_path: Path | None = None,
) -> dict[str, Any]:
    session, owned, _ids = discover_program_sessions(
        home=home,
        tui_pid=tui_pid,
        index_path=index_path,
    )
    signals = read_signals(session) if session is not None else {}
    usage = last_turn_usage(session) if session is not None else {}
    overlay = pty_overlay or {}
    ctx_used = overlay.get("context_used")
    if ctx_used is None:
        ctx_used = signals.get("contextTokensUsed")
    ctx_window = overlay.get("context_window")
    if ctx_window is None:
        ctx_window = signals.get("contextWindowTokens")
    try:
        used_n = int(ctx_used) if ctx_used is not None else None
    except (TypeError, ValueError):
        used_n = None
    try:
        window_n = int(ctx_window) if ctx_window is not None else None
    except (TypeError, ValueError):
        window_n = None
    total = 0
    for folder in owned:
        total += session_spend(read_signals(folder))
    if not owned:
        total = None
    turn_total = usage.get("totalTokens")
    try:
        turn_n = int(turn_total) if turn_total is not None else None
    except (TypeError, ValueError):
        turn_n = None
    live_n = 0
    if used_n is not None and live_base is not None:
        live_n = max(0, used_n - int(live_base))
    weekly = read_weekly_from_logs(home)
    try:
        weekly_n = int(weekly) if weekly is not None else None
    except (TypeError, ValueError):
        weekly_n = None
    if weekly_n is not None and not 0 <= weekly_n <= 100:
        weekly_n = None
    return {
        "session": str(session) if session is not None else "",
        "context_used": used_n,
        "context_window": window_n,
        "context_label": (
            format_tokens(used_n) + "/" + format_tokens(window_n)
            if used_n is not None and window_n is not None
            else "—"
        ),
        "session_total": total,
        "session_total_label": format_tokens(total),
        "turn_tokens": turn_n,
        "turn_label": format_tokens(turn_n),
        "live_tokens": live_n,
        "live_label": format_tokens(live_n),
        "weekly_percent": weekly_n,
        "compactions": signals.get("compactionCount"),
        "owned_sessions": len(owned),
    }
