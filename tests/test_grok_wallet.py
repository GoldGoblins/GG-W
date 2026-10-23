#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from backend.grok_wallet import format_tokens, parse_pty_wallet, snapshot


def main() -> int:
    if format_tokens(379627) != "379K":
        raise AssertionError("format 379627: " + format_tokens(379627))
    if format_tokens(500000) != "500K":
        raise AssertionError("format 500000")
    if format_tokens(2791033) != "2.79M":
        raise AssertionError("format millions")
    overlay = parse_pty_wallet("footer 379K / 500K  weekly 42%")
    if overlay.get("context_used") != 379000:
        raise AssertionError("pty ctx used: " + repr(overlay))
    chat = parse_pty_wallet("du har bara 31% av din weekly kvar")
    if chat.get("weekly_percent") is not None:
        raise AssertionError("chat weekly must not override billing")
    home = Path(tempfile.mkdtemp(prefix="gg-wallet-"))
    project = home / "sessions" / "%2Fhome%2FGG%2FGoldGoblins"
    outer = project / "outer-session"
    inner = project / "inner-session"
    older = project / "inner-older"
    for folder in (outer, inner, older):
        folder.mkdir(parents=True)
    (outer / "signals.json").write_text(
        json.dumps(
            {
                "contextTokensUsed": 379627,
                "contextWindowTokens": 500000,
                "totalTokensBeforeCompaction": 2791033,
                "compactionCount": 7,
            }
        ),
        encoding="utf-8",
    )
    (inner / "signals.json").write_text(
        json.dumps(
            {
                "contextTokensUsed": 5714,
                "contextWindowTokens": 500000,
                "totalTokensBeforeCompaction": 0,
                "compactionCount": 0,
            }
        ),
        encoding="utf-8",
    )
    (older / "signals.json").write_text(
        json.dumps(
            {
                "contextTokensUsed": 4000,
                "contextWindowTokens": 500000,
                "totalTokensBeforeCompaction": 1000,
                "compactionCount": 1,
            }
        ),
        encoding="utf-8",
    )
    (inner / "updates.jsonl").write_text(
        json.dumps(
            {
                "params": {
                    "update": {
                        "sessionUpdate": "turn_completed",
                        "usage": {"totalTokens": 16000, "outputTokens": 40},
                    }
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )
    os.utime(inner / "signals.json", None)
    (home / "active_sessions.json").write_text(
        json.dumps(
            [
                {
                    "session_id": "outer-session",
                    "pid": 1,
                    "cwd": "/home/GG/GoldGoblins",
                }
            ]
        ),
        encoding="utf-8",
    )
    index = home / "wallet-index.json"
    logs = home / "logs"
    logs.mkdir()
    (logs / "unified.jsonl").write_text(
        json.dumps(
            {
                "msg": "billing: fetched credits config",
                "ctx": {
                    "config": {"creditUsagePercent": 53.0},
                    "subscriptionTier": "SuperGrok",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    view = snapshot(
        home=home,
        live_base=1000,
        tui_pid=os.getpid(),
        index_path=index,
    )
    if view["context_label"] != "5K/500K":
        raise AssertionError("ctx label " + view["context_label"])
    if view["session"] and "outer-session" in view["session"]:
        raise AssertionError("outer konsole session leaked into wallet")
    spent = view["session_total"]
    if spent is None or spent < 5714:
        raise AssertionError("all spend " + str(spent))
    if spent >= 2791033:
        raise AssertionError("outer chat counted in ALL: " + str(spent))
    if view["turn_tokens"] != 16000:
        raise AssertionError("turn " + str(view["turn_tokens"]))
    if view["live_tokens"] != 4714:
        raise AssertionError("live " + str(view["live_tokens"]))
    if view["weekly_percent"] != 53:
        raise AssertionError("weekly from log " + str(view["weekly_percent"]))
    print("GROK_WALLET_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
