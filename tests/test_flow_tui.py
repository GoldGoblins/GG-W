#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from backend import flow_tui
from backend.grok_worker_contract import ENGINE_FLOW_TUI, ENGINE_TARGETS, normalize_engine_target


def main() -> int:
    if ENGINE_FLOW_TUI not in ENGINE_TARGETS:
        raise AssertionError("FLOW_TUI must be a first-class engine")
    if normalize_engine_target("FLOW_TUI") != ENGINE_FLOW_TUI:
        raise AssertionError("normalize FLOW_TUI")
    if flow_tui.PARALLEL_AGENT_BRAIN != "FORBIDDEN":
        raise AssertionError("flow tui must not spawn extra brains")

    empty = flow_tui.reset()
    if empty["engine"] != "FLOW_TUI":
        raise AssertionError("engine id")
    if empty["grok"]["motor"] != "GROK_TUI" or empty["gpt"]["motor"] != "GPT_TUI":
        raise AssertionError("two house motors")

    board = flow_tui.submit("koda FlowTuiHole.qml och testa test_flow_tui.py")
    if "qml" not in " ".join(board["grok"]["jobs"]).lower() and "house" not in " ".join(
        board["grok"]["jobs"]
    ).lower():
        raise AssertionError("GROK should keep house/qml work")
    if not board["gpt"]["jobs"]:
        raise AssertionError("GPTUI packet missing")
    if board["reflect"]["after"] != "reconverge":
        raise AssertionError("reflect must follow merge")
    if board["reflect"]["author"] == "DEV":
        raise AssertionError("critic must not be the author")
    if board["transcript"][0]["role"] != "YOU":
        raise AssertionError("transcript starts with the user")
    roles = [str(row.get("role") or "") for row in board["transcript"]]
    if "GROK TUI" not in roles or "GPTUI" not in roles:
        raise AssertionError("shared stream must name both motors")
    joined = "\n".join(str(row.get("text") or "") for row in board["transcript"])
    if "hold original intent" in joined.lower() or "do not rewrite the house layer" in joined.lower():
        raise AssertionError("FLOW must not post job lists as chat replies")
    if flow_tui.dispatch_texts()["grok"] != board["ask"]:
        raise AssertionError("dispatch must send the real ask, not a job packet")

    flow_tui.reset()
    talk = flow_tui.submit("hejsan")
    grok_blob = (
        '{"params":{"update":{"sessionUpdate":"agent_message_chunk",'
        '"content":{"type":"text","text":"hej, det är Grok"}}}}\n'
    )
    grok_text = flow_tui.extract_assistant_jsonl(grok_blob, role="GROK TUI")
    if grok_text != "hej, det är Grok":
        raise AssertionError("FLOW must read Grok assistant jsonl, got " + repr(grok_text))
    if flow_tui.extract_assistant_jsonl(
        '{"params":{"update":{"sessionUpdate":"tool_call","title":"todo_write"}}}\n',
        role="GROK TUI",
    ):
        raise AssertionError("FLOW must ignore tool-call jsonl")
    chrome = "Enter:send Alt+Enter:newline Shift+Tab:mode Ctrl+x:"
    if not flow_tui.is_chrome_reply(chrome):
        raise AssertionError("FLOW must drop TUI chrome")
    gpt_blob = (
        '{"payload":{"type":"message","role":"assistant","content":'
        '[{"type":"output_text","text":"hej från GPTUI"}]}}\n'
    )
    gpt_text = flow_tui.extract_assistant_jsonl(gpt_blob, role="GPTUI")
    if gpt_text != "hej från GPTUI":
        raise AssertionError("FLOW must read GPTUI assistant jsonl, got " + repr(gpt_text))
    gpt = flow_tui.set_motor_stream("GPTUI", gpt_text, done=True)
    shown = next(
        str(row.get("text") or "")
        for row in gpt["transcript"]
        if row.get("role") == "GPTUI"
    )
    if shown != "hej från GPTUI":
        raise AssertionError("GPTUI stream missing")
    if talk["transcript"][0]["text"] != "hejsan":
        raise AssertionError("talk transcript lost the user ask")

    main_qml = (PROJECT / "qml/Main.qml").read_text(encoding="utf-8")
    if 'leftLegend: "CHAT · UNIVERSAL OPERATIONAL STREAM"' not in main_qml:
        raise AssertionError("UOS chrome was changed")
    if 'objectName: "grokTuiHost"' not in main_qml or 'objectName: "gptTuiHost"' not in main_qml:
        raise AssertionError("existing TUI holes must remain")
    if 'objectName: "flowTuiHost"' not in main_qml:
        raise AssertionError("FLOW TUI hole missing")
    hole = (PROJECT / "qml/components/FlowTuiHole.qml").read_text(encoding="utf-8")
    if 'objectName: "flowTuiInputBar"' not in hole or 'anchors.bottom: parent.bottom' not in hole:
        raise AssertionError("FLOW TUI prompt must stay pinned to the bottom")
    if "ChatNode" not in hole:
        raise AssertionError("FLOW TUI must use the same chat bubbles as UOS")
    if "onFlowTuiChanged" not in hole:
        raise AssertionError("FLOW TUI must live-update when the motors answer")
    if "interval: 400" in hole:
        raise AssertionError("FLOW TUI must not poll the board on a hot timer")
    if "GROK TUI" in hole and 'text: "GROK TUI"' in hole and "ChatNode" in hole:
        pass
    if "motorRow" in hole:
        raise AssertionError("FLOW TUI must not be a two-column job board")
    workspace = (PROJECT / "qml/components/WorkspaceSurface.qml").read_text(
        encoding="utf-8"
    )
    hide = workspace[
        workspace.index("id: authoringSurface") : workspace.index("id: codeHost")
    ]
    if 'hostKind !== "FLOW"' not in hide:
        raise AssertionError("CODE editor still shows under FLOW")
    grok_at = main_qml.index('objectName: "grokTuiHost"')
    gpt_at = main_qml.index('objectName: "gptTuiHost"')
    flow_at = main_qml.index('objectName: "flowTuiHost"')
    if not (grok_at < gpt_at < flow_at):
        raise AssertionError("FLOW TUI must sit after GPTUI")

    composer = (PROJECT / "qml/components/ContextComposer.qml").read_text(encoding="utf-8")
    gpt_tab = composer.index('text: "GPTUI"')
    flow_tab = composer.index('text: "FLOW TUI"')
    if flow_tab < gpt_tab:
        raise AssertionError("composer FLOW TUI tab must follow GPTUI")

    settings = (PROJECT / "qml/components/SettingsChatModule.qml").read_text(
        encoding="utf-8"
    )
    if 'text: "FLOW TUI"' not in settings:
        raise AssertionError("settings chat missing FLOW TUI")

    host = (PROJECT / "backend/chat_surface_host.py").read_text(encoding="utf-8")
    for marker in (
        "def flowTuiSubmit",
        "def flowTuiStatus",
        "def flowTuiReset",
        "def _flow_tui_poll",
        "flowTuiChanged",
    ):
        if marker not in host:
            raise AssertionError("host slot missing: " + marker)
    if "flow_vt.feed" in host or "_flow_vt" in host or "def _flow_tui_ingest" in host:
        raise AssertionError("FLOW must not parse TUI screens on the PTY read path")
    if "if grid is None:\n            return False" in host.split("def _start_gpt_tui")[1].split("def ")[0]:
        raise AssertionError("FLOW must start GPTUI even when the GPT tab is hidden")
    print("test_flow_tui: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
