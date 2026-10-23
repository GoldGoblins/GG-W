#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from backend import node_flow
from backend import machine_graph as G


def main() -> int:
    node_flow.reset()
    snap = node_flow.snapshot()
    assert snap["schema"] == node_flow.SCHEMA
    assert snap["parallel_agent_brain"] == "FORBIDDEN"
    assert len(snap["blocks"]) == 8
    assert len(snap["wires"]) == 9
    assert snap["eval"]["stream"] > 0
    before = snap["eval"]["contrast"]

    cut = node_flow.disconnect("wire-risk-fm")
    assert all(row["edge_id"] != "wire-risk-fm" for row in cut["wires"])
    assert cut["eval"]["contrast"] != before or cut["eval"]["stream"] != snap["eval"]["stream"]

    again = node_flow.connect("RISK", "out", "FRONT_MAN", "in_risk")
    assert any(row["edge_id"].endswith("FRONT_MAN-in_risk") for row in again["wires"])

    low = node_flow.set_param("FRONT_MAN", "loops", 1.0)
    high = node_flow.set_param("FRONT_MAN", "loops", 3.0)
    assert high["eval"]["contrast"] >= low["eval"]["contrast"]

    moved = node_flow.move("CHAT", 800, 200)
    chat = next(row for row in moved["blocks"] if row["node_id"] == "CHAT")
    assert chat["x"] == 800
    assert chat["y"] == 200

    try:
        node_flow.set_param("CHAT", "nope", 1.0)
        raise AssertionError("unknown param was accepted")
    except G.MachineGraphError:
        pass

    qml = (PROJECT / "qml/components/NodeSurface.qml").read_text(encoding="utf-8")
    workspace = (PROJECT / "qml/components/WorkspaceSurface.qml").read_text(
        encoding="utf-8"
    )
    for marker in (
        'objectName: "workspaceNodePane"',
        "nodeFlowConnect",
        "nodeFlowDisconnect",
        "nodeFlowSetParam",
        "GAIN",
        "MIX",
    ):
        if marker not in qml:
            raise AssertionError("NodeSurface marker missing: " + marker)
    for marker in (
        'hostKind === "NODES"',
        'text: "NODES"',
        "NodeSurface {",
        'objectName: "workspaceKindNodes"',
    ):
        if marker not in workspace:
            raise AssertionError("Workspace NODES marker missing: " + marker)

    host = (PROJECT / "backend/chat_surface_host.py").read_text(encoding="utf-8")
    for marker in (
        "def nodeFlowStatus",
        "def nodeFlowConnect",
        "def nodeFlowDisconnect",
        "def nodeFlowSetParam",
        "def nodeFlowReset",
    ):
        if marker not in host:
            raise AssertionError("Qt bridge node-flow marker missing: " + marker)

    print("test_node_flow: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
