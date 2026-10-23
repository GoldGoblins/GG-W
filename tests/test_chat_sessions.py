#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from backend.chat_sessions import list_for_ui, remember_session, sync_owned


def main() -> int:
    folder = Path(tempfile.mkdtemp(prefix="gg-chats-"))
    catalog = folder / "chat-sessions.json"
    first = remember_session("aaa-1", engine="GROK_TUI", path=catalog)
    second = remember_session("bbb-2", engine="GROK_TUI", path=catalog)
    again = remember_session("aaa-1", engine="GROK_TUI", path=catalog)
    if len(first["sessions"]) != 1:
        raise AssertionError("first remember")
    if len(second["sessions"]) != 2:
        raise AssertionError("second remember")
    if len(again["sessions"]) != 2:
        raise AssertionError("duplicate remember")
    rows = list_for_ui(current_id="bbb-2", path=catalog)
    if rows[0]["label"] != "session 2  ·  GROK TUI":
        raise AssertionError("newest first " + rows[0]["label"])
    if rows[0]["current"] is not True:
        raise AssertionError("current flag")
    if rows[1]["label"] != "session 1  ·  GROK TUI":
        raise AssertionError("older below " + rows[1]["label"])
    payload = json.loads(catalog.read_text(encoding="utf-8"))
    if payload["memory"] != "GoldGoblins":
        raise AssertionError("shared memory missing")
    from backend.chat_sessions import PROJECT_SESSIONS, load_catalog

    seeded = load_catalog()
    ids = {
        str(row.get("session_id") or "")
        for row in seeded.get("sessions") or []
    }
    for sid, _engine in PROJECT_SESSIONS:
        if sid not in ids:
            raise AssertionError("project chat missing from CHATS: " + sid)
    # A 27-row catalog models the live GoldGoblins catalog without writing
    # outside the temporary test directory.
    seeded_rows = [
        {"n": n, "session_id": "grok-" + str(n), "engine": "GROK_TUI"}
        for n in range(1, 28)
    ]
    seeded_rows.append(
        {"n": 28, "session_id": "01a0724a-b286-7bf2-bb44-07abd60be740", "engine": "GPT_TUI"}
    )
    catalog.write_text(
        json.dumps({"sessions": seeded_rows}), encoding="utf-8"
    )
    rows = list_for_ui(path=catalog)
    if not any(
        row["n"] == 28
        and row["engine"] == "GPT_TUI"
        and row["label"] == "session 28  ·  GPTUI"
        for row in rows
    ):
        raise AssertionError("GPTUI session 28 missing")
    remember_session("gpt-new", engine="GPT_TUI", path=catalog)
    rows = list_for_ui(path=catalog)
    if not any(
        row["n"] == 29
        and row["session_id"] == "gpt-new"
        and row["label"] == "session 29  ·  GPTUI"
        for row in rows
    ):
        raise AssertionError("new GPTUI session did not receive next number")
    sync_owned(["gpt-bulk-3", "gpt-bulk-2", "gpt-bulk-2"], engine="GPT_TUI", path=catalog)
    payload = json.loads(catalog.read_text(encoding="utf-8"))
    bulk = [
        row for row in payload["sessions"]
        if row.get("session_id", "").startswith("gpt-bulk-")
    ]
    if len(bulk) != 2 or len({row["session_id"] for row in bulk}) != 2:
        raise AssertionError("bulk session sync duplicated or dropped rows")
    leaked = [
        path for path in folder.glob(".chat-sessions.json.*")
        if path.name != ".chat-sessions.json.lock"
    ]
    if leaked:
        raise AssertionError("atomic catalog temporary file leaked")
    print("CHAT_SESSIONS_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
