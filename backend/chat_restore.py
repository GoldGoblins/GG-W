"""Read a bounded, text-only checkpoint for a selected saved chat.

The checkpoint stays in RAM. It does not copy history, rewrite a rollout or
infer completion from a pause in the terminal stream.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import unicodedata

_TAIL_BYTES = 512 * 1024
_LINK = re.compile(r"\[([^\]]+)\]\([^\n)]*\)")


def normalized_display_text(text: str) -> str:
    # Rendered Markdown keeps the link label, while soft wraps and decoration
    # can change its spacing. Keep Unicode letters and digits for comparison.
    visible = _LINK.sub(r"\1", text)
    return "".join(char for char in unicodedata.normalize("NFKC", visible).casefold()
                   if char.isalnum())


def _content_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "\n".join(part["text"] for part in content
                     if isinstance(part, dict) and part.get("type")
                     in ("text", "Text", "input_text", "output_text")
                     and isinstance(part.get("text"), str))


def _visible_message(row: object) -> str:
    if not isinstance(row, dict):
        return ""
    payload = row.get("payload")
    if not isinstance(payload, dict):
        return ""
    kind = payload.get("type")
    if not isinstance(kind, str):
        return ""
    if row.get("type") == "response_item" and kind == "message":
        if payload.get("role") not in ("user", "assistant"):
            return ""
        if payload.get("phase") == "analysis":
            return ""
        return _content_text(payload.get("content"))
    if row.get("type") != "event_msg":
        return ""
    if kind == "task_complete":
        text = payload.get("last_agent_message")
        return text if isinstance(text, str) else ""
    if kind in {"agent_message", "user_message"} and payload.get("phase") != "analysis":
        text = payload.get("message")
        return text if isinstance(text, str) else ""
    if kind == "item_completed":
        item = payload.get("item")
        if (isinstance(item, dict) and item.get("type") in ("AgentMessage", "UserMessage")
                and item.get("phase") != "analysis"):
            return _content_text(item.get("content"))
    return ""


def codex_tail_marker(path: Path | None) -> str | None:
    """Return a visible tail marker; None means readiness is still unknown."""
    if path is None:
        return None
    try:
        if path.is_symlink():
            return None
        with path.open("rb") as stream:
            size = stream.seek(0, 2)
            offset = max(0, size - _TAIL_BYTES)
            stream.seek(offset)
            body = stream.read(_TAIL_BYTES)
    except OSError:
        return None
    lines = body.splitlines()
    if offset:
        lines = lines[1:]  # The first row can start in a large image/tool record.
    for line in reversed(lines):
        try:
            row = json.loads(line)
        except (ValueError, UnicodeError):
            continue
        text = normalized_display_text(_visible_message(row))
        if text:
            return text[-96:]
    return None
