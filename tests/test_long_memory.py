#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from backend import long_memory
from backend.omni_gpt_profiles import build_context
from backend import thought_desk
from backend import node_flow


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        skipped = long_memory.capture("hi", tree_root=root)
        assert skipped["status"] == "SKIPPED"
        assert skipped["action_authority"] == "NONE"

        secret = long_memory.capture(
            "the live password is hunter2 for sftp login",
            tree_root=root,
        )
        assert secret["status"] == "SKIPPED"
        assert secret["reason"] == "SECRET_BLOCKED"

        first = long_memory.capture(
            "sftp live cookie banner three buttons and GA4 id G-JFSYDYPM44",
            motor="GROK_TUI",
            kind="procedural",
            note="Live cookie banner is snippet 159 three-button; GA4 is G-JFSYDYPM44",
            tree_root=root,
        )
        assert first["status"] == "RECORDED", first
        assert first["hit"] == "NEW"
        assert first["action_authority"] == "NONE"
        assert first["canonical_policy_change"] is False
        assert first["promotion_authority"] == "NONE"

        again = long_memory.capture(
            "sftp live cookie banner three buttons and GA4 id G-JFSYDYPM44",
            motor="GPT_TUI",
            kind="procedural",
            note="Live cookie banner is snippet 159 three-button; GA4 is G-JFSYDYPM44",
            tree_root=root,
        )
        assert again["status"] == "RECORDED"
        assert again["hit"] == "IDENTITY"
        assert again["support"] == 2
        assert again["lesson_id"] == first["lesson_id"]

        other = long_memory.capture(
            "paper crypto desk garch hmm keep revert graveyard on factory",
            motor="GROK_TUI",
            kind="semantic",
            note="CRYPTO DESK stays paper; FACTORY KEEP/REVERT, never a second brain",
            tree_root=root,
        )
        assert other["status"] == "RECORDED"
        assert other["lesson_id"] != first["lesson_id"]

        hits = long_memory.recall(
            "cookie banner on the live sftp site",
            tree_root=root,
        )
        assert hits, hits
        assert hits[0]["lesson_id"] == first["lesson_id"]
        assert "cookie" in hits[0]["statement"].casefold()
        dumped = " ".join(item["statement"] for item in hits)
        assert "def " not in dumped
        assert "class " not in dumped
        assert "5a19dddc" not in dumped

        cached = long_memory.recall(
            "cookie banner on the live sftp site",
            tree_root=root,
        )
        assert [item["lesson_id"] for item in cached] == [
            item["lesson_id"] for item in hits
        ]

        crypto = long_memory.recall("garch hmm factory keep revert", tree_root=root)
        assert crypto
        assert crypto[0]["lesson_id"] == other["lesson_id"]

        merged = long_memory.consolidate(tree_root=root)
        assert merged["status"] == "CONSOLIDATED"
        working = Path(merged["path"])
        assert working.is_file()
        body = working.read_text(encoding="utf-8")
        assert "schema=" + long_memory.SCHEMA in body
        assert "cookie" in body.casefold() or "garch" in body.casefold()
        assert len(body.splitlines()) <= long_memory.MAX_WORKING_LINES + 8

        block = long_memory.render(
            "cookie banner live sftp",
            budget=400,
            tree_root=root,
        )
        assert block.startswith("[GG LONG MEMORY]")
        assert "[/GG LONG MEMORY]" in block
        assert len(block) <= 400
        assert long_memory.ACTION_AUTHORITY == "NONE"
        assert long_memory.density(tree_root=root) > 0

        tiny = long_memory.render("cookie", budget=40, tree_root=root)
        assert tiny == ""

        for index in range(40):
            long_memory.capture(
                "web pane load watchdog sixty seconds tab " + str(index).zfill(2),
                motor="SHARED",
                kind="episodic",
                note="WEB one tab; 60s watchdog; halt background engine",
                tree_root=root,
            )
        fill = long_memory.density(tree_root=root)
        assert 0 < fill <= 1.0
        web = long_memory.recall("web pane watchdog halt engine", tree_root=root)
        assert web
        assert "watchdog" in web[0]["statement"].casefold() or "tab" in web[
            0
        ]["statement"].casefold() or "WEB" in web[0]["statement"]

    board = thought_desk.sit("koda long_memory.py och testa test_long_memory.py")
    assert board["seats"]["memory"]["id"] == "MEMORY"
    assert board["seats"]["memory"]["retrieval"] == "LASER_IDENTITY"
    assert "MEMORY hits=" in board["text"]
    assert board["parallel_agent_brain"] == "FORBIDDEN"

    compact = build_context(
        "Jag har en idé om en GPT och vill förstå vad jag menar",
        max_chars=2200,
        include_registry=False,
    )
    assert len(compact) <= 2200
    assert "[SAME_TASK_DESK]" in compact
    assert "MEMORY hits=" in compact

    node_flow.reset()
    snap = node_flow.evaluate()
    assert snap["values"]["MEMORY"] > 0
    assert snap["parallel_agent_brain"] == "FORBIDDEN"

    print("test_long_memory: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
