#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from backend import idle_learn
from backend import long_memory


def main() -> int:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        empty = idle_learn.tick(tree_root=root)
        assert empty["status"] == "SKIPPED"
        assert empty["reason"] == "CATALOG_MISSING"
        assert empty["action_authority"] == "NONE"
        assert empty["parallel_agent_brain"] == "FORBIDDEN"

        catalog = {
            "schema": "gg.unique-source-catalog.v1",
            "files": [
                {
                    "path": "/home/GG/GoldGoblins/projects/gg-ai-desktop/backend/idle_learn.py",
                    "sha16": "aaaaaaaaaaaaaaaa",
                    "doc": "Bounded idle curriculum over the unique-source catalog.",
                    "symbols": [
                        {"name": "tick", "kind": "function", "line": 1},
                        {"name": "status", "kind": "function", "line": 2},
                    ],
                },
                {
                    "path": "/home/GG/GoldGoblins/projects/gg-ai-desktop/qml/terminal-hole/xterm.min.js",
                    "sha16": "bbbbbbbbbbbbbbbb",
                    "doc": "vendor",
                    "symbols": [],
                },
                {
                    "path": "/home/GG/GoldGoblins/projects/gg-ai-desktop/backend/long_memory.py",
                    "sha16": "cccccccccccccccc",
                    "doc": "Motor-independent long-term memory on the laser-Merkle FactStore.",
                    "symbols": [{"name": "capture", "kind": "function", "line": 10}],
                },
            ],
        }
        (root / idle_learn.CATALOG_NAME).write_text(
            json.dumps(catalog), encoding="utf-8"
        )
        first = idle_learn.tick(tree_root=root, limit=2)
        assert first["status"] == "LEARNED", first
        assert first["learned"] == 2
        assert first["parallel_agent_brain"] == "FORBIDDEN"
        hits = long_memory.recall("idle_learn catalog tick", tree_root=root)
        assert hits, hits
        again = idle_learn.tick(tree_root=root, limit=2)
        assert again["status"] == "IDLE"
        snap = idle_learn.status(tree_root=root)
        assert snap["seen"] == 2
        assert snap["action_authority"] == "NONE"

    host = (PROJECT / "backend/chat_surface_host.py").read_text(encoding="utf-8")
    for marker in (
        "self._idle_learn_timer",
        "def _idle_learn_tick",
        "def _idle_learn_work",
        "gg-idle-learn",
    ):
        if marker not in host:
            raise AssertionError("idle-learn host marker missing: " + marker)
    lex = Path("/home/GG/GoldGoblins/.grok/skills/selfdev-t/lexicon.txt").read_text(
        encoding="utf-8"
    )
    for token in ("learn", "idle", "catalog", "mem", "house"):
        if not any(line.startswith(token + "\t") for line in lex.splitlines()):
            raise AssertionError("lexicon token missing: " + token)

    print("test_idle_learn: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
