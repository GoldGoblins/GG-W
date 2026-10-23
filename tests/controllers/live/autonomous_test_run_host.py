#!/usr/bin/env python3
"""Host-only REAL_UI_AUTONOMOUS_TEST_RUN_PROOF.

WHY
    User asks naturally to verify. Qwen emits GG_TOOL_REQUEST TEST or RUN.
    Existing GREEN Safe Tool path executes. TOOL nodes share the request
    taskId. Same RESPONSE continues to PASS. No slash. No WRITE/GIT.

WRITES
    /run/user/<uid>/gg-resident-chat.* and gg-safe-tool.* only.

DONE_WHEN
    SAME taskId, TOOL TEST or RUN, STREAMING>PASS, idle, no <think>
    REAL_UI_AUTONOMOUS_TEST_RUN_PROOF=PASS
    VISIBLE_ACCEPTED=HUMAN_PENDING
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(PROJECT))
os.environ.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

# Do not mention "safe-tool": Laser binds that to tool.safe.dispatch
# (CONTROLLED_PROFILE) and ChatBridge returns before resident submit.
USER_TEXT = (
    "Kan du kontrollera att kontraktet fortfarande håller?"
)
TURN_TIMEOUT_MS = 300000


def proof_process_exit_code(passed: bool, requested_code: int) -> int:
    if passed:
        return 0
    if requested_code:
        return requested_code
    return 72


def run_gui() -> int:
    import resident_stream_host as host
    from PySide6.QtCore import QObject, QTimer, QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine

    import main as desktop

    platform = host.choose_platform()
    os.environ["QT_QPA_PLATFORM"] = platform
    host.emit("QT_QPA_PLATFORM", platform)
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    engine = QQmlApplicationEngine()
    engine.setInitialProperties(desktop.qml_initial_properties(desktop.load_config()))
    engine.load(QUrl.fromLocalFile(str(desktop.QML_PATH)))
    roots = engine.rootObjects()
    if not roots:
        host.emit("GUI_START", "FAIL")
        return 72
    root = roots[0]
    host.emit("GUI_START", "PASS")
    workspace = root.findChild(QObject, "workspaceSurface")
    live = desktop.LiveAidQtBridge(desktop.REPO_ROOT, app)
    workspace.setProperty("liveAidBackend", live)
    bridge = desktop.ChatBridge(root, app)
    root.bridgeSubmit.connect(bridge.submit)
    root.contextSnapshotSync.connect(bridge.syncContextSnapshot)
    root.bridgeStop.connect(bridge.stopActive)

    seen: list[str] = []
    bound = {"request_task_id": ""}
    original = bridge._resident_chat._update_node

    def track(text: str, state: str) -> None:
        active = (
            bridge._resident_chat.active_request_id() or bound["request_task_id"]
        )
        if bound["request_task_id"] and active and active != bound["request_task_id"]:
            original(text, state)
            return
        if not seen or seen[-1] != state:
            seen.append(state)
        original(text, state)

    bridge._resident_chat._update_node = track
    preexisting = {
        str(node.get("taskId", ""))
        for node in host.dump_chat(root)
        if node.get("nodeKind") == "RESPONSE" and node.get("taskId")
    }
    root.contextSnapshotSync.emit(root.buildContextSnapshotJson())
    root.appendRealNode(
        "YOU",
        "REQUEST",
        USER_TEXT,
        "@current · ws.file.context-composer",
        "SUBMITTED",
        0,
        "",
    )
    host.emit("USER_TEXT", USER_TEXT)
    host.emit("SLASH_IN_USER", "YES" if USER_TEXT.lstrip().startswith("/") else "NO")
    bridge.submit(USER_TEXT, "@current", "ws.file.context-composer")
    request_task_id = bridge._resident_chat.active_request_id()
    if not request_task_id:
        created = [
            str(node.get("taskId", ""))
            for node in host.dump_chat(root)
            if node.get("nodeKind") == "RESPONSE"
            and node.get("taskId")
            and node.get("taskId") not in preexisting
        ]
        if len(created) == 1:
            request_task_id = created[0]
    bound["request_task_id"] = request_task_id
    host.emit("REQUEST_TASK_ID", request_task_id or "MISSING")
    if not request_task_id:
        nodes = host.dump_chat(root)
        host.emit("CHAT_NODE_COUNT", str(len(nodes)))
        for index, node in enumerate(nodes[:12]):
            body = str(node.get("bodyText", "")).replace("\n", " ")[:160]
            host.emit(
                "CHAT_NODE_" + str(index),
                str(node.get("nodeKind", ""))
                + "|"
                + str(node.get("stateLabel", ""))
                + "|"
                + str(node.get("taskId", ""))
                + "|"
                + body,
            )
        host.emit("REAL_UI_AUTONOMOUS_TEST_RUN_PROOF", "FAIL")
        return 72

    def finish(code: int) -> None:
        nodes = host.dump_chat(root)
        response = host.response_for_task(root, request_task_id)
        tools = [
            node
            for node in nodes
            if node.get("nodeKind") == "TOOL"
            and node.get("taskId") == request_task_id
        ]
        tool_text = " ".join(str(node.get("bodyText", "")) for node in tools)
        used_verify = (
            "TEST" in tool_text
            or "RUN" in tool_text
            or "Verification tool" in tool_text
        )
        collapsed = host.collapse_states(seen)
        same = bool(response) and response.get("taskId") == request_task_id
        body = str(response.get("bodyText", "")) if response else ""
        private = "<think>" in body.lower() or "</think>" in body.lower()
        busy = bool(bridge._resident_chat.busy())
        active = bridge._resident_chat.active_request_id()
        idle = (not busy) and (not active)
        passed = (
            same
            and used_verify
            and collapsed[-1:] == ["PASS"]
            and "STREAMING" in collapsed
            and bool(body.strip())
            and not private
            and idle
            and response.get("stateLabel") == "PASS"
        )
        host.emit(
            "RESPONSE_TASK_ID",
            str(response.get("taskId", "MISSING") if response else "MISSING"),
        )
        host.emit("SAME_TASK_ID", "PASS" if same else "FAIL")
        host.emit("TOOL_NODES", str(len(tools)))
        host.emit("AUTONOMOUS_TEST_RUN", "PASS" if used_verify else "FAIL")
        host.emit("STREAM_STATES", ">".join(collapsed))
        host.emit("RESPONSE_BODY_NONEMPTY", "PASS" if body.strip() else "FAIL")
        host.emit("RESPONSE_BODY", body.replace("\n", " ")[:240])
        host.emit("PRIVATE_REASONING_VISIBLE", "YES" if private else "NO")
        host.emit("RESIDENT_BUSY_AFTER_TURN", "YES" if busy else "NO")
        host.emit(
            "RESIDENT_ACTIVE_REQUEST_AFTER_TURN",
            active if active else "NONE",
        )
        host.emit("RUNTIME_IDLE_AFTER_PASS", "PASS" if idle else "FAIL")
        host.emit(
            "REAL_UI_AUTONOMOUS_TEST_RUN_PROOF",
            "PASS" if passed else "FAIL",
        )
        host.emit("VISIBLE_ACCEPTED", "HUMAN_PENDING")
        try:
            bridge._resident_chat.shutdown()
        except Exception as exc:
            host.emit("SHUTDOWN", type(exc).__name__ + ":" + str(exc))
        app.exit(proof_process_exit_code(passed, code))

    ticks = {"n": 0}
    max_ticks = max(1, TURN_TIMEOUT_MS // 250)

    def poll() -> None:
        ticks["n"] += 1
        response = host.response_for_task(root, request_task_id)
        if response is not None and response.get("stateLabel") in {
            "PASS",
            "FAIL",
            "CANCELLED",
        }:
            finish(72)
            return
        if ticks["n"] >= max_ticks:
            host.emit("REASON", "TURN_TIMEOUT")
            finish(73)
            return
        QTimer.singleShot(250, poll)

    QTimer.singleShot(250, poll)
    return app.exec()


def main() -> int:
    import resident_stream_host as host

    host.emit("CONTROLLER", "REAL_UI_AUTONOMOUS_TEST_RUN_PROOF")
    layer = host.classify_preflight()
    if layer != "HOST":
        host.emit("REAL_UI_AUTONOMOUS_TEST_RUN_PROOF", "NOT_PROVABLE_HERE")
        host.emit("FAULT_LAYER", layer)
        return 70
    try:
        return run_gui()
    except Exception as exc:
        host.emit("PROBE_CRASH", type(exc).__name__ + ":" + str(exc))
        return 72


if __name__ == "__main__":
    raise SystemExit(main())
