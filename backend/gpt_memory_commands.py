"""Local GPT TUI memory commands.

These commands deliberately run in the desktop host.  They do not start or
forward to another TUI, so a GPT session can maintain the shared workspace
memory on its own.
"""

from __future__ import annotations

from backend.application_paths import HOME, USER_CODEX_HOME, WORKSPACE_ROOT, STATE_ROOT, private_runtime_path

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.codex_wallet import (
    CODEX_SESSIONS,
    CODEX_SESSION_STATE,
    DESKTOP_CODEX_SESSION_STATE,
    DESKTOP_CODEX_SESSIONS,
    load_session_id,
    session_path,
)

# Keep the shared notes in the workspace so both TUI motors can read them and
# the desktop remains usable under the managed filesystem policy.
ROOT = Path(str(WORKSPACE_ROOT / '.grok/shared-memory'))
GROK_WORKSPACE_MEMORY = private_runtime_path("grok_workspace_memory", STATE_ROOT / "shared-memory")


def _session_path() -> Path | None:
    # GPTUI owns the desktop pointer, but Codex 0.153.x may still place the
    # corresponding rollout JSONL in the canonical ~/.codex/sessions root.
    # Search both roots for the explicit pointer before considering any
    # legacy/global pointer; otherwise /flush can write the parent session.
    for state in (DESKTOP_CODEX_SESSION_STATE, CODEX_SESSION_STATE):
        active = load_session_id(state)
        if not active:
            continue
        for sessions_root in (DESKTOP_CODEX_SESSIONS, CODEX_SESSIONS):
            selected = session_path(active, sessions_root=sessions_root)
            if selected is not None:
                return selected
        # An explicit GPTUI pointer that has not materialized yet is safer
        # than silently flushing a different conversation.
        if state == DESKTOP_CODEX_SESSION_STATE:
            return None
    for sessions_root in (DESKTOP_CODEX_SESSIONS, CODEX_SESSIONS):
        try:
            rows = list(sessions_root.rglob("*.jsonl"))
        except OSError:
            continue
        if rows:
            return max(rows, key=lambda path: path.stat().st_mtime)
    return None


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(_text(item) for item in value)
    if isinstance(value, dict):
        return _text(value.get("text") or value.get("content") or "")
    return ""


def _write_root() -> Path:
    """Use Grok's indexed workspace memory when writable, else repo memory."""
    try:
        GROK_WORKSPACE_MEMORY.mkdir(mode=0o700, parents=True, exist_ok=True)
        probe = GROK_WORKSPACE_MEMORY / ".gpt-write-probe"
        probe.touch(exist_ok=True)
        probe.unlink(missing_ok=True)
        return GROK_WORKSPACE_MEMORY
    except OSError:
        return ROOT


def _memory_roots() -> list[Path]:
    roots = [GROK_WORKSPACE_MEMORY, ROOT]
    return list(dict.fromkeys(path for path in roots if path.exists()))


def _messages(session: Path) -> tuple[list[str], list[str]]:
    prompts: list[str] = []
    replies: list[str] = []
    with session.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            try:
                row = json.loads(line)
            except (TypeError, ValueError):
                continue
            payload = row.get("payload") if isinstance(row, dict) else {}
            if not isinstance(payload, dict):
                continue
            kind = str(payload.get("type") or "")
            role = str(payload.get("role") or "")
            body = _text(
                payload.get("message")
                or payload.get("content")
                or payload.get("text")
            ).strip()
            if not body:
                continue
            if kind in {"user_message", "user_prompt"} or (
                kind == "message" and role == "user"
            ):
                prompts.append(body)
            elif kind in {"assistant_message", "assistant_output"} or (
                kind == "message" and role == "assistant"
            ):
                replies.append(body)
    return prompts, replies


def flush() -> str:
    """Persist the current Codex transcript as a shared memory note."""
    session = _session_path()
    if session is None:
        return "[GPT memory] /flush: no Codex session found"
    try:
        prompts, replies = _messages(session)
    except OSError as exc:
        return f"[GPT memory] /flush failed: {exc}"
    stamp = datetime.now().astimezone()
    root = _write_root()
    target = root / "sessions" / f"{stamp:%Y-%m-%d-%H%M%S}-gpt.md"
    try:
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        lines = [f"# GPT session flush — {stamp.isoformat()}", "", f"Source: `{session}`", ""]
        if prompts:
            lines += ["## User prompts", ""] + [f"- {item[:4000]}" for item in prompts[-40:]] + [""]
        if replies:
            lines += ["## GPT replies", ""] + [f"- {item[:4000]}" for item in replies[-20:]] + [""]
        target.write_text("\n".join(lines), encoding="utf-8")
    except OSError as exc:
        return f"[GPT memory] /flush failed: {exc}"
    last_prompt = prompts[-1] if prompts else ""
    _sync_long_memory(
        last_prompt,
        kind="episodic",
        note="GPT session flush: " + (last_prompt[:160] if last_prompt else target.name),
        motor="GPT_TUI",
        consolidate_after=True,
    )
    return f"[GPT memory] /flush saved {target.name} ({len(prompts)} prompts, {len(replies)} replies)"


def _sync_long_memory(
    query: str,
    *,
    kind: str,
    note: str = "",
    motor: str = "GPT_TUI",
    consolidate_after: bool = False,
    force: bool = False,
) -> None:
    try:
        from backend import long_memory

        recorded = long_memory.capture(
            query,
            motor=motor,
            kind=kind,
            note=note,
            force=force,
        )
        if consolidate_after and recorded.get("status") == "RECORDED":
            long_memory.consolidate()
    except Exception:
        return


def run(command: str) -> str:
    text = str(command or "").strip()
    name, _, arg = text.partition(" ")
    if name == "/flush":
        return flush()
    if name == "/memory":
        files: list[Path] = []
        for root in _memory_roots():
            try:
                files.extend((root / "sessions").glob("*.md"))
            except OSError:
                pass
        files = sorted(set(files), key=lambda path: path.stat().st_mtime)
        return "[GPT memory] " + (", ".join(p.name for p in files[-10:]) or "empty")
    if name == "/remember" and arg.strip():
        try:
            root = _write_root()
            root.mkdir(mode=0o700, parents=True, exist_ok=True)
            with (root / "MEMORY.md").open("a", encoding="utf-8") as stream:
                stream.write(f"\n- {arg.strip()}\n")
            _sync_long_memory(
                arg.strip(),
                kind="semantic",
                note=arg.strip(),
                motor="GPT_TUI",
                force=True,
            )
            return "[GPT memory] remembered"
        except OSError as exc:
            return f"[GPT memory] /remember failed: {exc}"
    if name == "/dream":
        files: list[Path] = []
        for root in _memory_roots():
            files.extend((root / "sessions").glob("*.md"))
        if not files:
            return "[GPT memory] /dream: no session memories to consolidate"
        target = _write_root() / "DREAM.md"
        headings: list[str] = []
        for path in sorted(set(files), key=lambda item: item.stat().st_mtime):
            try:
                title = path.read_text(encoding="utf-8", errors="replace").splitlines()[0]
            except (OSError, IndexError):
                title = path.stem
            headings.append(f"- {title.lstrip('# ').strip()} — `{path.name}`")
        try:
            target.write_text("# Consolidated session memory\n\n" + "\n".join(headings) + "\n", encoding="utf-8")
        except OSError as rec:
            return f"[GPT memory] /dream failed: {rec}"
        _sync_long_memory(
            "consolidate session memory",
            kind="procedural",
            note="GPT /dream merged " + str(len(headings)) + " session files",
            motor="GPT_TUI",
            consolidate_after=True,
            force=True,
        )
        return f"[GPT memory] /dream consolidated {len(headings)} session files"
    if name == "/skills":
        names: set[str] = set()
        for root in (Path(str(WORKSPACE_ROOT / '.grok/skills')), Path(str(HOME / '.grok/skills')), Path(str(USER_CODEX_HOME / 'skills'))):
            try:
                names.update(path.parent.name for path in root.glob("*/SKILL.md"))
            except OSError:
                pass
        return "[GPT skills] " + (", ".join(sorted(names)) or "none")
    if name == "/plugins":
        names: set[str] = set()
        for root in (Path(str(WORKSPACE_ROOT / '.grok/plugins')), Path(str(HOME / '.grok/plugins')), Path(str(USER_CODEX_HOME / 'plugins'))):
            try:
                names.update(path.name for path in root.iterdir() if path.is_dir())
            except OSError:
                pass
        return "[GPT plugins] " + (", ".join(sorted(names)) or "none")
    if name == "/hooks-list":
        hooks: list[str] = []
        for root in (Path(str(WORKSPACE_ROOT / '.grok/hooks')), Path(str(HOME / '.grok/hooks'))):
            try:
                hooks.extend(str(path) for path in sorted(root.glob("*.json")))
            except OSError:
                pass
        return "[GPT hooks] " + (", ".join(hooks) or "none")
    if name in {"/hooks-trust", "/hooks-add"}:
        return f"[GPT hooks] {name} requires a direct ja in chat for this task"
    return ""
