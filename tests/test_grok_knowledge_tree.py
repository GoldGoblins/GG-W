#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))
BACKEND = PROJECT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def main() -> int:
    from backend.grok_knowledge_tree import (
        ACTION_AUTHORITY,
        CANONICAL_POLICY_CHANGE,
        HEAD_RELATIVE,
        HEAD_SNAPSHOT,
        SCHEMA,
        call_hashes,
        extract_call_codes,
        load_head,
        lookup,
        observe_event,
        record,
    )

    head = load_head()
    assert head["head_relative"] == HEAD_RELATIVE
    assert len(head["head_sha256"]) == 64
    assert "backend/solver_router.py" in head["files"]

    result = lookup("laser merkle neighborhood compiled focus knowledge")
    assert result["schema"] == SCHEMA
    assert result["status"] == "READY", result
    assert result["action_authority"] == ACTION_AUTHORITY
    assert result["canonical_policy_change"] is CANONICAL_POLICY_CHANGE
    assert result["head_sha256"] == head["head_sha256"]
    laser = result["laser"]
    assert isinstance(laser["handle_id"], str) and len(laser["handle_id"]) == 64
    sources = result["neighborhood"]["sources"]
    assert sources, result
    dumped = json.dumps(result)
    assert "def " not in dumped
    assert "class " not in dumped
    for item in sources:
        assert len(item["sha256"]) == 64
        assert item["path"].startswith("projects/gg-ai-desktop/")

    same = lookup("laser merkle neighborhood compiled focus knowledge")
    assert same["laser"]["handle_id"] == laser["handle_id"]
    assert (
        same["neighborhood"]["handle_id"]
        == result["neighborhood"]["handle_id"]
    )
    assert result["neighborhood"]["origin"] == "QUERY"

    chat = lookup("vad pratade vi om i forra sessionen")
    assert chat["status"] == "READY", chat
    assert chat["neighborhood"]["sources"]
    assert chat["neighborhood"]["origin"] in {"QUERY", "WORKPLACE_DEFAULT"}
    assert chat["laser"]["handle_id"]
    again = lookup("vad pratade vi om i forra sessionen")
    assert again["laser"]["handle_id"] == chat["laser"]["handle_id"]
    blank = lookup("zzzzzy nnnnqqq mmmmvvv")
    assert blank["status"] == "READY", blank
    assert blank["neighborhood"]["origin"] == "WORKPLACE_DEFAULT"
    assert blank["neighborhood"]["sources"]

    router_sha = head["files"]["backend/solver_router.py"]
    called = call_hashes([router_sha[:16]])
    assert called["status"] == "READY", called
    assert called["action_authority"] == ACTION_AUTHORITY
    assert called["calls"][0]["sha256"] == router_sha
    assert any(
        item["name"] == "SolverRouter" for item in called["calls"][0]["symbols"]
    )
    composed = call_hashes(
        [
            router_sha[:16],
            head["files"]["backend/grok_knowledge_tree.py"][:16],
        ]
    )
    assert composed["status"] == "READY", composed
    assert len(composed["calls"]) == 2
    missing = call_hashes(["deadbeefdeadbeef"])
    assert missing["status"] == "MISS_CLOSED"
    hashed_lookup = lookup("sha call kod = " + router_sha[:16])
    assert hashed_lookup["status"] == "READY", hashed_lookup
    assert hashed_lookup["neighborhood"]["origin"] == "CALL"
    assert hashed_lookup["calls"][0]["sha256"] == router_sha
    assert extract_call_codes("sha call kod = " + router_sha[:12]) == (
        router_sha[:12],
    )

    with tempfile.TemporaryDirectory() as tmp:
        recorded = record(
            "laser merkle neighborhood compiled focus knowledge",
            relative_path="projects/gg-ai-desktop/backend/solver_router.py",
            kind="code",
            tree_root=Path(tmp),
        )
        assert recorded["status"] == "RECORDED", recorded
        assert recorded["action_authority"] == ACTION_AUTHORITY
        assert recorded["canonical_policy_change"] is False
        assert recorded["source_sha256"] == head["files"]["backend/solver_router.py"]
        assert (Path(tmp) / "index.jsonl").is_file()

        drifted = record(
            "laser merkle neighborhood compiled focus knowledge",
            relative_path="projects/gg-ai-desktop/backend/solver_router.py",
            kind="action",
            tree_root=Path(tmp),
            project_root=PROJECT,
        )
        # Same live bytes as manifest: second record is still RECORDED, not drift.
        assert drifted["status"] == "RECORDED"

        started = observe_event(
            {"hookEventName": "session_start"},
            tree_root=Path(tmp),
        )
        assert started["status"] == "READY"
        assert started["laser"]["handle_id"]
        assert started["neighborhood"]["sources"]
        assert (Path(tmp) / HEAD_SNAPSHOT).is_file()
        start_snap = json.loads(
            (Path(tmp) / HEAD_SNAPSHOT).read_text(encoding="utf-8")
        )
        assert start_snap["laser_handle"]
        assert start_snap["sources"]

        prompt = observe_event(
            {
                "hookEventName": "user_prompt_submit",
                "prompt": "vad pratade vi om i forra sessionen",
            },
            tree_root=Path(tmp),
        )
        assert prompt["status"] == "READY", prompt
        snapshot = json.loads(
            (Path(tmp) / HEAD_SNAPSHOT).read_text(encoding="utf-8")
        )
        assert snapshot["laser_handle"] == prompt["laser"]["handle_id"]
        assert snapshot["sources"]
        assert snapshot["recent"]
        assert snapshot["query"] == "vad pratade vi om i forra sessionen"

        wrote = observe_event(
            {
                "hookEventName": "post_tool_use",
                "toolName": "search_replace",
                "toolInput": {
                    "file_path": str(
                        PROJECT / "backend/solver_router.py"
                    )
                },
                "prompt": "always-on tree write",
            },
            tree_root=Path(tmp),
        )
        assert wrote["status"] == "RECORDED", wrote
        assert wrote["call_code"] == head["files"]["backend/solver_router.py"][:16]
        assert wrote["symbol_fact_ids"]
        skipped = observe_event(
            {
                "hookEventName": "post_tool_use",
                "toolName": "read_file",
                "toolInput": {
                    "target_file": str(
                        PROJECT / "backend/solver_router.py"
                    )
                },
            },
            tree_root=Path(tmp),
        )
        assert skipped["status"] == "SKIPPED"

    print("GROK_KNOWLEDGE_TREE_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
