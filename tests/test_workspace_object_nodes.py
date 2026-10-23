#!/usr/bin/env python3
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


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def evaluate(root, source: str):
    from PySide6.QtQml import QQmlEngine, QQmlExpression

    context = QQmlEngine.contextForObject(root)
    require(context is not None, "QML context missing.")
    expression = QQmlExpression(context, root, source)
    value = expression.evaluate()
    require(not expression.hasError(), "QML expression failed: " + source)
    if isinstance(value, (tuple, list)) and value:
        value = value[0]
    if hasattr(value, "toVariant"):
        value = value.toVariant()
    elif hasattr(value, "toString") and not isinstance(value, str):
        value = value.toString()
    return value


def dump_nodes(root) -> list[dict[str, object]]:
    raw = evaluate(
        root,
        """
        (function() {
            var surface = workspace;
            var out = [];
            var rail = surface.children
                ? null
                : null;
            var count = 0;
            var snapshot = surface.contextSnapshot(32);
            return JSON.stringify({
                currentObjectId: String(surface.currentObjectId || ""),
                currentIndex: surface.currentIndex,
                showDemoFixtures: surface.showDemoFixtures === true,
                snapshot: snapshot
            });
        })()
        """,
    )
    require(isinstance(raw, str) and raw.strip(), "Node dump empty.")
    parsed = json.loads(raw)
    require(isinstance(parsed, dict), "Node dump is not an object.")
    return parsed


def visible_nodes(root) -> list[dict[str, str]]:
    raw = evaluate(
        root,
        """
        (function() {
            var rail = workspace.findChild
                ? null
                : null;
            var nodes = [];
            function walk(item) {
                if (item === undefined || item === null)
                    return;
                if (
                    item.objectName === "workspaceObjectNode"
                    && Number(item.width) > 0
                )
                    nodes.push({
                        objectId: String(item.objectId || ""),
                        title: String(item.title || ""),
                        provenanceClass: String(item.provenanceClass || ""),
                        activityState: String(item.activityState || ""),
                        current: item.current === true ? "true" : "false",
                        editorDirty: item.editorDirty === true ? "true" : "false"
                    });
                if (item.children === undefined)
                    return;
                for (var i = 0; i < item.children.length; ++i)
                    walk(item.children[i]);
            }
            walk(workspace);
            return JSON.stringify(nodes);
        })()
        """,
    )
    require(isinstance(raw, str) and raw.strip(), "Visible node dump empty.")
    parsed = json.loads(raw)
    require(isinstance(parsed, list), "Visible node dump is not a list.")
    return parsed


def main() -> int:
    from PySide6.QtCore import QObject, QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine

    import main as desktop

    config = desktop.load_config()
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    engine = QQmlApplicationEngine()
    engine.setInitialProperties(desktop.qml_initial_properties(config))
    engine.load(QUrl.fromLocalFile(str(desktop.QML_PATH)))
    roots = engine.rootObjects()
    require(bool(roots), "Real Main.qml failed to start.")
    root = roots[0]
    workspace = desktop.wait_for_workspace_surface(root)
    require(workspace is not None, "WorkspaceSurface missing.")
    rail = root.findChild(QObject, "workspaceObjectNodeRail")
    require(rail is not None, "workspaceObjectNodeRail missing.")

    require(
        str(workspace.property("currentObjectId") or "")
        == "ws.file.scratch.1",
        "Default @current is not the untitled CODE buffer.",
    )

    if hasattr(root, "setWidth"):
        root.setWidth(1920)
        root.setHeight(1080)
    else:
        require(
            bool(root.setProperty("width", 1920)),
            "Failed to set window width.",
        )
        require(
            bool(root.setProperty("height", 1080)),
            "Failed to set window height.",
        )
    if hasattr(root, "show"):
        root.show()
    app.processEvents()

    nodes = visible_nodes(root)
    require(len(nodes) == 0, "Living object cards must stay off the desk.")
    snapshot = dump_nodes(root)["snapshot"]
    require(
        [
            str(item.get("objectId") or "")
            for item in snapshot["objects"]
            if str(item.get("provenanceClass") or "") == "REAL_LOCAL_FILE"
        ]
        == [
            "ws.file.context-composer",
            "ws.file.grok-work-stream",
            "ws.file.chat-node",
            "ws.file.workspace-object-node",
        ],
        "Default desk is missing real workspace papers.",
    )
    require(
        "ws.terminal.user"
        in [
            str(item.get("objectId") or "")
            for item in snapshot["objects"]
        ],
        "User terminal host tab missing.",
    )
    require(
        "ws.app.external"
        in [
            str(item.get("objectId") or "")
            for item in snapshot["objects"]
        ],
        "External app stub tab missing.",
    )
    require(
        snapshot["currentObjectId"] == "ws.file.scratch.1",
        "Default @current is not the untitled CODE buffer.",
    )
    require(
        snapshot["objects"][0]["activityState"] == "IDLE",
        "Idle real tab claimed non-idle activity.",
    )

    require(
        bool(workspace.setProperty("engineTarget", "GROK_WORKER")),
        "Failed to set engineTarget GROK_WORKER.",
    )
    require(
        bool(workspace.setProperty("chatBusy", True)),
        "Failed to set chatBusy.",
    )
    app.processEvents()
    snapshot = dump_nodes(root)["snapshot"]
    require(
        snapshot["objects"][0]["activityState"] == "STREAMING",
        "Chat-busy grok did not mark the @current tab.",
    )
    require(
        bool(workspace.setProperty("chatBusy", False)),
        "Failed to clear chatBusy.",
    )
    require(
        bool(workspace.setProperty("engineTarget", "LOCAL_QWEN")),
        "Failed to restore engineTarget.",
    )
    app.processEvents()
    snapshot = dump_nodes(root)["snapshot"]
    require(
        snapshot["objects"][0]["activityState"] == "IDLE",
        "Cleared chat busy left a live workspace tab.",
    )

    snapshot = dump_nodes(root)["snapshot"]
    require(
        snapshot["currentObjectId"] == "ws.file.scratch.1",
        "Snapshot @current mismatch.",
    )
    require(
        snapshot["objects"][0]["activityState"] == "IDLE",
        "Snapshot activity is not bound idle.",
    )

    require(
        bool(workspace.setProperty("liveAidState", "RUNNING")),
        "Failed to set liveAidState.",
    )
    app.processEvents()
    snapshot = dump_nodes(root)["snapshot"]
    require(
        snapshot["objects"][0]["activityState"] == "RUNNING",
        "Real tab activity did not bind RUNNING.",
    )
    snapshot = dump_nodes(root)["snapshot"]
    require(
        snapshot["objects"][0]["activityState"] == "RUNNING",
        "Snapshot activity did not bind RUNNING.",
    )

    require(
        bool(workspace.setProperty("liveAidState", "WAITING_FOR_USER")),
        "Failed to set liveAidState WAITING_FOR_USER.",
    )
    app.processEvents()
    snapshot = dump_nodes(root)["snapshot"]
    require(
        snapshot["objects"][0]["activityState"] == "WAITING_FOR_USER",
        "Real tab activity did not bind WAITING_FOR_USER.",
    )

    require(
        bool(workspace.setProperty("showDemoFixtures", True)),
        "Failed to show demo fixtures.",
    )
    app.processEvents()
    nodes = visible_nodes(root)
    require(len(nodes) == 0, "Demo fixtures must not spawn living blocks.")
    snapshot = dump_nodes(root)["snapshot"]
    synthetic_ids = [
        str(item.get("objectId") or "")
        for item in snapshot["objects"]
        if str(item.get("provenanceClass") or "") == "SYNTHETIC_UI_FIXTURE"
    ]
    require(len(synthetic_ids) >= 1, "Synthetic tabs missing when demo shown.")

    activated = evaluate(
        root,
        'workspace.focusObject("ws.website.goldgoblins")',
    )
    require(activated is True or activated == True, "focusObject failed.")
    app.processEvents()
    require(
        str(workspace.property("currentObjectId") or "")
        == "ws.website.goldgoblins",
        "Node activation did not move @current.",
    )
    nodes = visible_nodes(root)
    require(len(nodes) == 0, "Tab change must not spawn living blocks.")
    snapshot = dump_nodes(root)["snapshot"]
    require(
        snapshot["currentObjectId"] == "ws.website.goldgoblins",
        "Activated tab is not @current.",
    )
    require(
        snapshot["objects"][snapshot["currentIndex"]]["activityState"] == "IDLE",
        "Synthetic current tab claimed live activity.",
    )
    snapshot = dump_nodes(root)["snapshot"]
    require(
        any(
            str(item.get("objectId") or "") == "ws.file.context-composer"
            for item in snapshot["objects"]
        ),
        "Real file tab disappeared after activation.",
    )

    focus = getattr(workspace, "focusObject", None)
    require(callable(focus), "focusObject missing.")
    focus("ws.terminal.user")
    app.processEvents()
    snapshot = dump_nodes(root)["snapshot"]
    require(
        snapshot["currentObjectId"] == "ws.terminal.user",
        "Terminal tab did not become @current surface.",
    )
    require(
        bool(evaluate(workspace, 'currentObjectType === "USER_TERMINAL"')),
        "Terminal host type mismatch.",
    )
    focus("ws.app.external")
    app.processEvents()
    require(
        bool(evaluate(workspace, 'currentObjectType === "EXTERNAL_APP"')),
        "External app stub type mismatch.",
    )
    set_kind = getattr(workspace, "setHostKind", None)
    require(callable(set_kind), "setHostKind missing.")
    set_kind("TERMINAL")
    app.processEvents()
    require(
        str(workspace.property("hostKind") or "") == "TERMINAL",
        "Host kind footer did not select TERMINAL.",
    )
    require(
        str(workspace.property("currentObjectId") or "") == "ws.terminal.user",
        "TERMINAL host kind did not focus user terminal.",
    )
    set_kind("CODE")
    app.processEvents()
    require(
        str(workspace.property("hostKind") or "") == "CODE",
        "Host kind footer did not select CODE.",
    )
    set_kind("SITE")
    app.processEvents()
    require(
        str(workspace.property("hostKind") or "") == "SITE",
        "Host kind footer did not select SITE.",
    )
    set_kind("TMOG")
    app.processEvents()
    require(
        str(workspace.property("hostKind") or "") == "TMOG",
        "Host kind footer did not select TMOG.",
    )
    set_kind("MEDIA")
    app.processEvents()
    require(
        str(workspace.property("hostKind") or "") == "MEDIA",
        "Host kind footer did not select MEDIA.",
    )
    set_kind("DRAW")
    app.processEvents()
    require(
        str(workspace.property("hostKind") or "") == "DRAW",
        "Host kind footer did not select DRAW.",
    )
    require(
        str(workspace.property("currentObjectId") or "") == "ws.site.current",
        "SITE host kind did not focus the site project.",
    )
    set_kind("CODE")
    app.processEvents()
    set_kind("TERMINAL")
    app.processEvents()
    spawn = getattr(workspace, "spawnHostInstance", None)
    require(callable(spawn), "spawnHostInstance missing.")
    spawn()
    app.processEvents()
    require(
        str(workspace.property("currentObjectId") or "") == "ws.terminal.user.2",
        "Second terminal instance did not become @current.",
    )
    require(
        bool(evaluate(workspace, 'currentObjectType === "USER_TERMINAL"')),
        "Spawned terminal type mismatch.",
    )
    close_instance = getattr(workspace, "closeHostInstance", None)
    require(callable(close_instance), "closeHostInstance missing.")
    close_instance(int(workspace.property("currentIndex")))
    app.processEvents()
    require(
        str(workspace.property("currentObjectId") or "") == "ws.terminal.user",
        "Closed spawned terminal did not return to the seed terminal.",
    )
    require(
        str(workspace.property("hostKind") or "") == "TERMINAL",
        "Closed spawned terminal did not keep TERMINAL host kind.",
    )
    seed_index = int(workspace.property("currentIndex"))
    close_instance(seed_index)
    app.processEvents()
    require(
        str(workspace.property("currentObjectId") or "") == "ws.terminal.user",
        "Seed terminal must not close.",
    )
    set_kind("WEB")
    app.processEvents()
    web_seed = int(workspace.property("currentIndex"))
    close_instance(web_seed)
    app.processEvents()
    require(
        str(workspace.property("currentObjectId") or "") == "ws.web.stub",
        "First WEB tab must remain as the blank stub.",
    )
    require(
        bool(
            evaluate(
                workspace,
                'workspaceObjects.get(currentIndex).sourcePath === "about:blank"',
            )
        ),
        "Closed first WEB tab must return to empty https:// bar.",
    )
    spawn()
    app.processEvents()
    require(
        str(workspace.property("currentObjectId") or "") == "ws.web.stub.3",
        "Second web instance did not become @current.",
    )
    set_kind("CODE")
    app.processEvents()
    spawn()
    app.processEvents()
    require(
        str(workspace.property("currentObjectId") or "") == "ws.file.scratch.4",
        "Scratch untitled instance did not become @current.",
    )
    close_instance(int(workspace.property("currentIndex")))
    app.processEvents()
    require(
        str(workspace.property("currentObjectId") or "") == "ws.file.scratch.1",
        "Closed extra scratch did not return to the default untitled buffer.",
    )
    focus("ws.file.context-composer")
    app.processEvents()

    print("WORKSPACE_OBJECT_NODES=PASS")
    print("WORKSPACE_OBJECT_NODE_ACTIVITY=BOUND_TO_REAL_OBJECT_STATE")
    print("SYNTHETIC_OBJECT_NODES=DEMO_SAMPLE_NO_EXECUTION")
    print("FAKE_PROGRESS=FORBIDDEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
