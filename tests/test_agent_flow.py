#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from backend import agent_flow


def main() -> int:
    empty = agent_flow.reset()
    if empty["parallel_agent_brain"] != "FORBIDDEN":
        raise AssertionError("flow must not spawn a second brain")
    if empty["action_authority"] != "NONE":
        raise AssertionError("flow must not grant authority")
    if empty.get("verifier_context") != "FRESH":
        raise AssertionError("verifier must not share the worker context")
    if (empty.get("diamond") or {}).get("verify") != "TEST":
        raise AssertionError("verify in code, not in chat")
    if [row["id"] for row in empty["stages"]] != list(agent_flow.STAGES):
        raise AssertionError("stage order")

    talk = agent_flow.run("hejsan")
    kinds = [row["kind"] for row in talk["packets"]]
    if kinds != list(agent_flow.STAGES):
        raise AssertionError("every run must emit the full packet chain")
    reflect = next(row for row in talk["packets"] if row["kind"] == "REFLECT")
    build = next(row for row in talk["packets"] if row["kind"] == "BUILD")
    if reflect["from"] == build["from"]:
        raise AssertionError("reviewer must not be the author")
    if reflect.get("author_is_builder") is not False:
        raise AssertionError("critic flag missing")
    tools = next(row for row in talk["packets"] if row["kind"] == "TOOLS")
    if tools.get("grants") != "NONE":
        raise AssertionError("tool packet must not grant")
    if not talk["user_gates"]:
        raise AssertionError("user must see every stage")

    work = agent_flow.run("koda agent_flow.py och testa test_agent_flow.py")
    if work["front_man"]["light"] not in {"GO", "SPLIT", "HOLD"}:
        raise AssertionError("front man missing")
    tool_row = next(row for row in work["packets"] if row["kind"] == "TOOLS")
    if "READ" not in (tool_row.get("tools") or []):
        raise AssertionError("work should name house tools")

    red = agent_flow.run("öppna wp-admin och skriv lösenord")
    if red["front_man"]["risk"] != "RED":
        raise AssertionError("red effect must stay red")
    if not any(gate.get("needs_chat_ja") for gate in red["user_gates"]):
        raise AssertionError("red work must still ask in chat")

    qml = (PROJECT / "qml/components/AgentFlowSurface.qml").read_text(encoding="utf-8")
    if "FOUR PATTERNS, ONE GRAPH" not in qml:
        raise AssertionError("surface title missing")
    workspace = (PROJECT / "qml/components/WorkspaceSurface.qml").read_text(
        encoding="utf-8"
    )
    if 'hostKind === "FLOW"' not in workspace:
        raise AssertionError("FLOW tab missing")
    host = (PROJECT / "backend/chat_surface_host.py").read_text(encoding="utf-8")
    for marker in ("def agentFlowRun", "def agentFlowStatus", "def agentFlowReset"):
        if marker not in host:
            raise AssertionError("host slot missing: " + marker)
    print("test_agent_flow: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
