#!/usr/bin/env python3
"""Host-only LIVE_UI_E2E_RESIDENT_STREAM controller.

WHY
    Prove ordinary assistant chat through the real desktop:
    Main.qml → ChatBridge → ResidentChatTransport → resident_chat_runner
    --serve → locked llama/Qwen → same ChatNode bound to this submit's
    request/taskId, ordered STARTING→GENERATING→STREAMING→PASS.

SOURCE_STATE_ORDER
    backend/resident_chat_qt.py:
      beginStreamingResponse → STARTING
      SESSION_STARTING → STARTING
      SESSION_READY → GENERATING
      TURN_START → GENERATING
      DELTA → STREAMING
      COMPLETE → PASS
    Consecutive duplicates are ignored. That is the required success chain.

STATE_BASE
    HEAD 31c9321f9394e452ee1e49a54be2f207a1e598ea, dirty worktree allowed.
    This controller does not mutate product source.

WRITES
    /run/user/<uid>/gg-resident-chat.* evidence (product contract).
    No /tmp runtime fallback. No git mutation. No network.

SUDO
    NONE

MODEL_INFERENCE
    YES — localhost/gg-llama-cpp-vulkan:b10182 + Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf

PODMAN
    Existing locked image, --pull=never, --network=none, --read-only,
    --cap-drop=all, no-new-privileges. Controller does not change flags.
    `podman info` / `image exists` have a bounded timeout.

DISPLAY
    Prefer existing Wayland/X11. Offscreen still counts as REAL_RUNTIME_PASS
    for the stream path. VISIBLE_ACCEPTED remains a human step.

DONE_WHEN
    Bound RESPONSE.taskId == this submit's request id,
    collapsed states STARTING>GENERATING>STREAMING>PASS,
    non-empty body, no <think> markers,
    busy()==False and active_request_id()=="" after PASS,
    then separate shutdown/cleanup.

STOP
    Do not weaken security, do not invent Grok-only product paths.
    If /run/user or rootless podman is denied, classify SANDBOX/HARNESS
    and exit 70. That is not a product FAIL.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[3]
REPO = PROJECT.parents[1]
os.environ.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

USER_TEXT = "Hej, fungerar du som en vanlig assistent i workbenchen?"
TURN_TIMEOUT_MS = 180000
PODMAN_PREFLIGHT_TIMEOUT_SECONDS = 20.0
REQUIRED_STATE_CHAIN = ("STARTING", "GENERATING", "STREAMING", "PASS")


def emit(key: str, value: object = "") -> None:
    if value == "":
        print(key, flush=True)
        return
    if isinstance(value, str):
        print(f"{key}={value}", flush=True)
        return
    print(
        key
        + "="
        + json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        flush=True,
    )


def collapse_states(states: list[str]) -> list[str]:
    collapsed: list[str] = []
    for state in states:
        if not collapsed or collapsed[-1] != state:
            collapsed.append(state)
    return collapsed


def run_podman(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/usr/bin/podman", *argv],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=PODMAN_PREFLIGHT_TIMEOUT_SECONDS,
    )


def classify_preflight() -> str:
    runtime = Path(f"/run/user/{os.getuid()}")
    probe = runtime / ("gg-resident-host-preflight." + os.urandom(4).hex())
    try:
        probe.mkdir(mode=0o700)
        probe.rmdir()
    except OSError as exc:
        emit("PREFLIGHT", "SANDBOX")
        emit("REASON", "EVIDENCE_RUNTIME_UNWRITABLE:" + type(exc).__name__)
        return "SANDBOX"

    try:
        podman = run_podman(["info"])
    except subprocess.TimeoutExpired:
        emit("PREFLIGHT", "HARNESS")
        emit("REASON", "PODMAN_INFO_TIMEOUT")
        return "HARNESS"
    if podman.returncode != 0:
        err = podman.stderr[-400:]
        sandbox = (
            "Permission denied" in err or "Operation not permitted" in err
        )
        emit("PREFLIGHT", "SANDBOX" if sandbox else "RUNTIME")
        emit("REASON", "PODMAN_UNAVAILABLE:" + err.replace("\n", " ")[:300])
        return "SANDBOX" if sandbox else "RUNTIME"

    from backend.resident_chat_runner import MODEL_PATH, RUNTIME_IMAGE

    if not MODEL_PATH.is_file():
        emit("PREFLIGHT", "RUNTIME")
        emit("REASON", "MODEL_PATH_INVALID")
        return "RUNTIME"
    try:
        inspect = run_podman(["image", "exists", RUNTIME_IMAGE])
    except subprocess.TimeoutExpired:
        emit("PREFLIGHT", "HARNESS")
        emit("REASON", "PODMAN_IMAGE_EXISTS_TIMEOUT")
        return "HARNESS"
    if inspect.returncode != 0:
        emit("PREFLIGHT", "RUNTIME")
        emit("REASON", "RUNTIME_IMAGE_MISSING")
        return "RUNTIME"
    emit("PREFLIGHT", "HOST")
    return "HOST"


def choose_platform() -> str:
    forced = os.environ.get("QT_QPA_PLATFORM", "").strip()
    if forced:
        return forced
    runtime = Path(os.environ["XDG_RUNTIME_DIR"])
    if (runtime / "wayland-0").exists():
        return "wayland"
    if Path("/tmp/.X11-unix/X0").exists():
        return "xcb"
    return "offscreen"


def dump_chat(root):
    from PySide6.QtQml import QQmlEngine, QQmlExpression

    context = QQmlEngine.contextForObject(root)
    expression = QQmlExpression(
        context,
        root,
        """
        (function() {
            var out = [];
            for (var i = 0; i < chatModel.count; i++) {
                var item = chatModel.get(i);
                out.push({
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
    if isinstance(value, (tuple, list)) and value:
        value = value[0]
    if hasattr(value, "toVariant"):
        raw = value.toVariant()
    elif hasattr(value, "toString"):
        raw = value.toString()
    else:
        raw = value
    if isinstance(raw, (tuple, list)) and raw:
        raw = raw[0]
    return json.loads(str(raw))


def response_for_task(root, request_task_id: str) -> dict[str, str] | None:
    matches = [
        node
        for node in dump_chat(root)
        if node.get("nodeKind") == "STREAM"
        and node.get("taskId") == request_task_id
    ]
    if len(matches) != 1:
        return None
    return matches[0]


def run_gui() -> int:
    from PySide6.QtCore import QTimer, QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine

    import main as desktop

    platform = choose_platform()
    os.environ["QT_QPA_PLATFORM"] = platform
    emit("QT_QPA_PLATFORM", platform)

    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    emit("QT_PLATFORM_NAME", app.platformName())
    engine = QQmlApplicationEngine()
    engine.setInitialProperties(desktop.qml_initial_properties(desktop.load_config()))
    engine.load(QUrl.fromLocalFile(str(desktop.QML_PATH)))
    roots = engine.rootObjects()
    if not roots:
        emit("GUI_START", "FAIL")
        return 72
    root = roots[0]
    emit("GUI_START", "PASS")
    emit("TITLE", str(root.property("title") or ""))

    workspace = desktop.wait_for_workspace_surface(root)
    if workspace is None:
        emit("REASON", "WORKSPACE_SURFACE_MISSING")
        return 72
    live = desktop.LiveAidQtBridge(desktop.REPO_ROOT, app)
    if not workspace.setProperty("liveAidBackend", live):
        emit("REASON", "LIVE_AID_BIND_FAILED")
        return 72
    bridge = desktop.ChatBridge(root, app)
    if not root.setProperty("engineTarget", "LOCAL_QWEN"):
        emit("REASON", "LOCAL_QWEN_BIND_FAILED")
        return 72
    root.bridgeSubmit.connect(bridge.submit)
    root.contextSnapshotSync.connect(bridge.syncContextSnapshot)
    root.bridgeStop.connect(bridge.stopActive)
    seen: list[str] = []
    bound = {"request_task_id": ""}
    original = bridge._resident_chat._update_node

    def track(text: str, state: str) -> None:
        active = bridge._resident_chat.active_request_id() or bound["request_task_id"]
        if bound["request_task_id"] and active and active != bound["request_task_id"]:
            original(text, state)
            return
        if not seen or seen[-1] != state:
            seen.append(state)
        original(text, state)

    bridge._resident_chat._update_node = track

    preexisting = {
        str(node.get("taskId", ""))
        for node in dump_chat(root)
        if node.get("nodeKind") == "STREAM" and node.get("taskId")
    }
    root.contextSnapshotSync.emit(root.buildContextSnapshotJson())
    root.appendRealNode(
        "YOU",
        "REQUEST",
        USER_TEXT,
        "@current · ws.file.chat-node",
        "SUBMITTED",
        0,
        "",
    )
    bridge.submit(USER_TEXT, "@current", "ws.file.chat-node")
    emit("SUBMIT", "PASS")

    request_task_id = bridge._resident_chat.active_request_id()
    if not request_task_id:
        created = [
            str(node.get("taskId", ""))
            for node in dump_chat(root)
            if node.get("nodeKind") == "STREAM"
            and node.get("taskId")
            and node.get("taskId") not in preexisting
        ]
        if len(created) == 1:
            request_task_id = created[0]
    bound["request_task_id"] = request_task_id
    emit("REQUEST_TASK_ID", request_task_id or "MISSING")
    if not request_task_id:
        emit("REASON", "REQUEST_TASK_ID_UNBOUND")
        emit("LIVE_UI_E2E_RESIDENT_STREAM", "FAIL")
        return 72

    def emit_idle_receipts() -> bool:
        busy = bool(bridge._resident_chat.busy())
        active = bridge._resident_chat.active_request_id()
        emit("RESIDENT_BUSY_AFTER_TURN", "YES" if busy else "NO")
        emit(
            "RESIDENT_ACTIVE_REQUEST_AFTER_TURN",
            active if active else "NONE",
        )
        idle = (not busy) and (not active)
        emit("RUNTIME_IDLE_AFTER_PASS", "PASS" if idle else "FAIL")
        return idle

    def finish(code: int) -> None:
        response = response_for_task(root, request_task_id)
        response_task_id = (
            str(response.get("taskId", "")) if response is not None else "MISSING"
        )
        body = str(response.get("bodyText", "")) if response is not None else ""
        collapsed = collapse_states(seen)
        same_task = response_task_id == request_task_id and bool(request_task_id)
        state_order = collapsed == list(REQUIRED_STATE_CHAIN)
        nonempty = bool(body.strip())
        private = (
            "<think>" in body.lower() or "</think>" in body.lower()
        )
        emit("RESPONSE_TASK_ID", response_task_id)
        emit("SAME_TASK_ID", "PASS" if same_task else "FAIL")
        emit("STREAM_STATES", ">".join(collapsed))
        emit("STATE_ORDER", "PASS" if state_order else "FAIL")
        emit("RESPONSE_BODY_NONEMPTY", "PASS" if nonempty else "FAIL")
        emit("PRIVATE_REASONING_VISIBLE", "YES" if private else "NO")
        idle = emit_idle_receipts()
        passed = (
            same_task
            and state_order
            and nonempty
            and not private
            and idle
            and response is not None
            and response.get("stateLabel") == "PASS"
        )
        emit(
            "LIVE_UI_E2E_RESIDENT_STREAM",
            "REAL_RUNTIME_PASS" if passed else "FAIL",
        )
        emit("VISIBLE_ACCEPTED", "HUMAN_PENDING")
        try:
            bridge._resident_chat.shutdown()
        except Exception as exc:
            emit("SHUTDOWN", type(exc).__name__ + ":" + str(exc))
        app.exit(0 if passed else code)

    ticks = {"n": 0}
    max_ticks = max(1, TURN_TIMEOUT_MS // 250)

    def poll() -> None:
        ticks["n"] += 1
        response = response_for_task(root, request_task_id)
        if response is not None and response.get("stateLabel") in {
            "PASS",
            "FAIL",
            "CANCELLED",
        }:
            finish(0 if response.get("stateLabel") == "PASS" else 72)
            return
        if ticks["n"] >= max_ticks:
            emit("REASON", "TURN_TIMEOUT")
            finish(73)
            return
        QTimer.singleShot(250, poll)

    QTimer.singleShot(250, poll)
    return app.exec()


def main() -> int:
    emit("CONTROLLER", "LIVE_UI_E2E_RESIDENT_STREAM_HOST")
    emit("REPO", str(REPO))
    emit("PROJECT", str(PROJECT))
    layer = classify_preflight()
    if layer != "HOST":
        emit("LIVE_UI_E2E_RESIDENT_STREAM", "NOT_PROVABLE_HERE")
        emit("FAULT_LAYER", layer)
        return 70
    try:
        return run_gui()
    except Exception as exc:
        emit("PROBE_CRASH", type(exc).__name__ + ":" + str(exc))
        emit("FAULT_LAYER", "HARNESS")
        return 72


if __name__ == "__main__":
    raise SystemExit(main())
