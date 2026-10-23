from __future__ import annotations

import json
import os
import sys
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))


STUB_SOURCE = '''from __future__ import annotations

import json
import sys

SCHEMA = "gg.workbench.resident-chat-event.v1"


def emit(kind: str, **fields: object) -> None:
    payload = {"schema": SCHEMA, "event": kind, **fields}
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\\n")
    sys.stdout.flush()


def main() -> int:
    emit("SESSION_STARTING")
    emit("SESSION_READY")
    for raw_line in sys.stdin:
        request = json.loads(raw_line)
        request_id = str(request["request_id"])
        emit("TURN_START", request_id=request_id)
        emit("DELTA", request_id=request_id, text="Hej")
        emit("DELTA", request_id=request_id, text=" fran")
        emit("DELTA", request_id=request_id, text=" resident stream.")
        emit("COMPLETE", request_id=request_id, chars=28)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def dump_chat(root) -> list[dict[str, str]]:
    from PySide6.QtQml import QQmlEngine, QQmlExpression

    context = QQmlEngine.contextForObject(root)
    require(context is not None, "QML context missing.")
    expression = QQmlExpression(
        context,
        root,
        """
        (function() {
            var out = [];
            for (var i = 0; i < chatModel.count; i++) {
                var item = chatModel.get(i);
                out.push({
                    authorLabel: String(item.authorLabel || ""),
                    nodeKind: String(item.nodeKind || ""),
                    stateLabel: String(item.stateLabel || ""),
                    taskId: String(item.taskId || ""),
                    bodyText: String(item.bodyText || "")
                });
            }
            return JSON.stringify(out);
        })()
        """,
    )
    value = expression.evaluate()
    require(not expression.hasError(), "Chat dump failed.")
    if isinstance(value, (tuple, list)) and value:
        value = value[0]
    if hasattr(value, "toVariant"):
        raw = value.toVariant()
    elif hasattr(value, "toString"):
        raw = value.toString()
    else:
        raw = value
    if isinstance(raw, (tuple, list)) and raw and isinstance(raw[0], str):
        raw = raw[0]
    require(isinstance(raw, str) and raw.strip(), "Chat dump empty.")
    parsed = json.loads(raw)
    require(isinstance(parsed, list), "Chat dump is not a list.")
    return parsed


def bind_stub_server(transport, stub_path: Path) -> None:
    from PySide6.QtCore import QProcess

    def ensure_server() -> None:
        process = transport._process
        if (
            process is not None
            and process.state() != QProcess.ProcessState.NotRunning
        ):
            return
        process = QProcess(transport)
        process.setProgram(sys.executable)
        process.setArguments(["-B", str(stub_path)])
        process.setWorkingDirectory(str(PROJECT))
        process.setProcessChannelMode(QProcess.SeparateChannels)
        process.readyReadStandardOutput.connect(transport._stdout_ready)
        process.readyReadStandardError.connect(transport._stderr_ready)
        process.finished.connect(transport._finished)
        transport._process = process
        process.start()
        if not process.waitForStarted(5000):
            error = process.errorString()
            process.deleteLater()
            transport._process = None
            raise RuntimeError("Stub resident runner failed to start: " + error)

    transport._ensure_server = ensure_server


def main() -> int:
    from PySide6.QtCore import QEventLoop, QObject, QTimer, QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine

    import main as desktop

    stub_path = Path("/tmp/gg-resident-chat-live-ui-stub.py")
    stub_path.write_text(STUB_SOURCE, encoding="utf-8")
    stub_path.chmod(0o700)

    config = desktop.load_config()
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    engine = QQmlApplicationEngine()
    engine.setInitialProperties(desktop.qml_initial_properties(config))
    engine.load(QUrl.fromLocalFile(str(desktop.QML_PATH)))
    roots = engine.rootObjects()
    require(bool(roots), "Real Main.qml failed to start.")
    root = roots[0]
    require(
        str(root.property("title") or "").startswith("GG AI Desktop"),
        "Unexpected desktop window title.",
    )

    workspace_surface = desktop.wait_for_workspace_surface(root)
    require(workspace_surface is not None, "WorkspaceSurface missing.")
    live_aid_bridge = desktop.LiveAidQtBridge(desktop.REPO_ROOT, app)
    require(
        bool(workspace_surface.setProperty("liveAidBackend", live_aid_bridge)),
        "Live Aid bind failed.",
    )

    bridge = desktop.ChatBridge(root, app)
    # The persisted desktop preference may select GPT_TUI.  This test owns a
    # resident-chat stub, so bind the transport to the local resident path
    # after ChatBridge has hydrated desktop settings.
    require(
        bool(root.setProperty("engineTarget", "LOCAL_QWEN")),
        "Could not bind LOCAL_QWEN for resident-chat UI test.",
    )
    root.bridgeSubmit.connect(bridge.submit)
    root.contextSnapshotSync.connect(bridge.syncContextSnapshot)
    root.bridgeStop.connect(bridge.stopActive)
    root.bridgeAssignmentSet.connect(bridge._setOrchestratorAssignment)
    root.bridgeAssignmentClear.connect(bridge._clearOrchestratorAssignment)
    bind_stub_server(bridge._resident_chat, stub_path)
    seen_states: list[str] = []
    bodies: list[str] = []
    original_update = bridge._resident_chat._update_node

    def track_update(text: str, state: str) -> None:
        seen_states.append(state)
        bodies.append(text)
        original_update(text, state)

    bridge._resident_chat._update_node = track_update

    snapshot = root.buildContextSnapshotJson()
    root.contextSnapshotSync.emit(snapshot)
    root.appendRealNode(
        "YOU",
        "REQUEST",
        "Svara med exakt ordet PING och inget mer.",
        "@current · ws.file.chat-node",
        "SUBMITTED",
        0,
        "",
    )
    bridge.submit(
        "Svara med exakt ordet PING och inget mer.",
        "@current",
        "ws.file.chat-node",
    )

    loop = QEventLoop()

    def observe() -> bool:
        nodes = dump_chat(root)
        responses = [
            node for node in nodes if node.get("nodeKind") == "STREAM"
        ]
        require(len(responses) == 1, "Expected exactly one STREAM node.")
        state = str(responses[0]["stateLabel"])
        return state in {"PASS", "FAIL", "CANCELLED"}

    ticks = {"n": 0}

    def poll() -> None:
        ticks["n"] += 1
        if observe() or ticks["n"] >= 40:
            loop.quit()
            return
        QTimer.singleShot(50, poll)

    QTimer.singleShot(20, poll)
    QTimer.singleShot(4000, loop.quit)
    loop.exec()

    nodes = dump_chat(root)
    responses = [node for node in nodes if node.get("nodeKind") == "STREAM"]
    require(len(responses) == 1, "STREAM node cardinality drifted.")
    response = responses[0]
    require(response["stateLabel"] == "PASS", "Stream did not reach PASS.")
    require("STARTING" in seen_states, "STARTING state missing.")
    require("GENERATING" in seen_states, "GENERATING state missing.")
    require("STREAMING" in seen_states, "Incremental STREAMING state missing.")
    require(
        seen_states[-4:]
        == ["STREAMING", "STREAMING", "STREAMING", "PASS"],
        "Same-node stream tail mismatch: " + ">".join(seen_states),
    )
    require(
        bodies[-4:]
        == [
            "Hej",
            "Hej fran",
            "Hej fran resident stream.",
            "Hej fran resident stream.",
        ],
        "Streamed body was not applied incrementally.",
    )
    require(
        response["bodyText"] == "Hej fran resident stream.",
        "Same-node streamed body mismatch.",
    )
    require(response["taskId"].startswith("chat-"), "Missing chat request id.")
    require(
        not bridge._resident_chat.busy(),
        "Resident transport stayed busy after PASS.",
    )

    bridge._resident_chat.shutdown()
    print("LIVE_UI_E2E_RESIDENT_STREAM=PASS")
    print("GUI_START=PASS")
    print("SAME_CHAT_NODE_INCREMENTAL_UPDATE=PASS")
    print("STREAM_STATES=" + ">".join(seen_states))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
