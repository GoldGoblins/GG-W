"""Exercise the real QML buttons, desktop dispatcher and supervised workers."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-background-networking")
PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from PySide6.QtCore import QObject, QMetaObject, QUrl, Slot, qInstallMessageHandler, QEventLoop, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlEngine, QQmlComponent, QJSValue
from PySide6.QtQuick import QQuickWindow
from backend import game_workflow_common as common
from backend.chat_surface_host import ChatSurfaceHost


class Bridge(QObject):
    @Slot(str, result=str)
    def researchCommand(self, request):
        return ChatSurfaceHost.researchCommand(self, request)


def main():
    app = QGuiApplication.instance() or QGuiApplication([])
    errors = []
    qInstallMessageHandler(lambda _kind, _context, message: errors.append(str(message)))
    with tempfile.TemporaryDirectory(prefix="gg-game-workflow-ui-") as temporary, patch.object(common, "ROOT", Path(temporary) / "state"):
        root = Path(temporary)
        assets = root / "assets"
        assets.mkdir()
        from PIL import Image
        Image.new("RGB", (8, 4), (60, 140, 240)).save(assets / "stone.png")
        engine = QQmlEngine()
        bridge = Bridge()
        engine.rootContext().setContextProperty("workflowBridge", bridge)
        source = f'''import QtQuick
import QtQuick.Window
import "{(PROJECT / 'qml/components').as_uri()}" as GG
Window {{ width:1100; height:760; visible:true
  GG.ResearchGamesSurface {{ anchors.fill:parent; anchors.margins:10; surfaceHost:workflowBridge }}
}}'''
        component = QQmlComponent(engine)
        component.setData(source.encode(), QUrl.fromLocalFile(str(root / "preview.qml")))
        deadline = time.monotonic() + 10
        while component.isLoading() and time.monotonic() < deadline:
            app.processEvents(); time.sleep(.01)
        assert component.isReady(), [error.toString() for error in component.errors()]
        window = component.create()
        assert window is not None, [error.toString() for error in component.errors()]
        pane = window.findChild(QObject, "workspaceGameWorkflowsPane")
        def frame():
            loop = QEventLoop()
            QTimer.singleShot(120, loop.quit)
            loop.exec()
        def settle():
            deadline = time.monotonic() + 15
            while pane.property("busy") and time.monotonic() < deadline:
                app.processEvents(); time.sleep(.01)
            assert not pane.property("busy"), pane.property("notice")
            assert pane.property("jobState") == "COMPLETE", pane.property("notice")
            return json.loads(pane.property("resultJson"))
        def click(name):
            button = pane.findChild(QObject, name)
            assert button is not None and button.property("enabled"), name
            assert QMetaObject.invokeMethod(button, "clicked")
            return settle()
        pane.setProperty("sourcePath", assets.as_uri())
        pane.setProperty("gameLabel", "Sly / GG fixture")
        assert click("gameScoutCollections")["collections"][0]["files"] == 1
        assert click("gameScoutIndex")["indexed"] == 1
        pane.setProperty("query", "stone")
        result = click("gameScoutSearch")
        assert len(result["hits"]) == 1
        snapshots = Path(sys.argv[1]) if len(sys.argv) > 1 else None
        if snapshots:
            snapshots.mkdir(parents=True, exist_ok=True)
            frame()
            assert window.grabWindow().save(str(snapshots / "SCOUT.png"))

        target = assets / "original.bin"
        target.write_bytes(b"A selected title-independent original artifact")
        export = root / "function.json"
        export.write_text(json.dumps({"name": "f", "address": "ram:00100000", "pseudocode": "int f(int x) { return 7; }",
                                      "cfg": {"blocks": [{"id": 0}]}}))
        pane.setProperty("stage", 1)
        invoke = engine.evaluate("(function(pane, payload) { pane.run('context_export', JSON.parse(payload)); })")
        assert not invoke.call([engine.newQObject(pane), QJSValue(json.dumps({"path": str(export), "target": str(target), "query": "f"}))]).isError()
        result = settle()
        assert result["context"]["provenance"] == "EXTERNAL_EXPORT_UNVERIFIED"
        assert pane.property("contextPath") == result["packet_path"]
        if snapshots:
            frame()
            assert window.grabWindow().save(str(snapshots / "CONTEXT.png"))

        candidate = root / "candidate.c"
        candidate.write_text("int f(int x) { return 7; }")
        pane.setProperty("candidatePath", str(candidate))
        pane.setProperty("stage", 2)
        result = click("gameCandidateReview")
        assert result["acceptance"] == "UNKNOWN"
        assert target.read_bytes() == b"A selected title-independent original artifact"
        if snapshots:
            frame()
            assert window.grabWindow().save(str(snapshots / "VERIFY.png"))

        original = PROJECT / "qml/assets/authored/world/sandover-settlement.json"
        pane.setProperty("stage", 3)
        pane.setProperty("flowPath", original.as_uri())
        result = click("gameFlowImport")
        assert result["oracle"]["valid"]
        result = click("gameFlowCheck")
        assert result["oracle"]["valid"]
        assert not click("gameFlowExport")["changed"]
        if snapshots:
            frame()
            assert window.grabWindow().save(str(snapshots / "FLOW.png"))
        from tests.test_game_asset_workflow_improvements import fixture_dae, fixture_smd
        dae, smd = root / "mesh.dae", root / "clip.smd"
        dae.write_bytes(fixture_dae()); smd.write_bytes(fixture_smd())
        pane.setProperty("stage", 4)
        pane.setProperty("targetPath", dae.as_uri())
        pane.setProperty("animationPath", smd.as_uri())
        assert not pane.findChild(QObject, "gameRigTrial").property("enabled")
        pane.setProperty("rigFps", "30")
        pane.setProperty("rigBasis", "SMD_LOCAL")
        result = click("gameRigTrial")
        assert result["status"] == "REVIEW_REQUIRED" and result["matched_joints"] == 1
        assert dae.read_bytes() == fixture_dae()
        if snapshots:
            frame()
            assert window.grabWindow().save(str(snapshots / "RIG.png"))
        pane.setProperty("stage", 5)
        pane.setProperty("targetPath", (PROJECT / "qml/assets/authored/characters/gg-crew-briarstride-articulated.glb").as_uri())
        pane.setProperty("profileLodPath", (PROJECT / "qml/assets/authored/characters/gg-crew-briarstride-compact.glb").as_uri())
        result = click("gameAssetProfile")
        assert result["assets"][0]["has_lod"] and result["status"] == "READY"
        assert pane.property("profilePlan") == result["packet_path"]
        assert pane.findChild(QObject, "gameSceneMeasure").property("enabled")
        if snapshots:
            frame()
            assert window.grabWindow().save(str(snapshots / "PROFILE.png"))
            window.setWidth(720)
            pane.setProperty("stage", 0)
            frame()
            assert window.grabWindow().save(str(snapshots / "SCOUT_NARROW.png"))
        bad = [message for message in errors if any(token in message for token in
               ("ReferenceError", "TypeError", "Cannot assign", "Unable to assign", "is not a type", "Binding loop"))]
        assert not bad, bad
        window.close()
        engine.deleteLater()
        app.processEvents()
    qInstallMessageHandler(None)
    print("GAME_WORKFLOWS_UI=PASS")


if __name__ == "__main__":
    main()
