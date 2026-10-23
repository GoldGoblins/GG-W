"""Native Qt integration check for the merged workspace and evidence workflow."""
import json
import faulthandler
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
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent, QJSValue
from PySide6.QtQuick import QQuickWindow
from PySide6.QtWebEngineQuick import QtWebEngineQuick
from backend import research_desk, research_lab, research_jobs, workbench_registry
from backend.chat_surface_host import ChatSurfaceHost


class Bridge(QObject):
    @Slot(str, result=str)
    def researchCommand(self, raw):
        return ChatSurfaceHost.researchCommand(self, raw)


def main():
    faulthandler.dump_traceback_later(25, exit=True)
    QtWebEngineQuick.initialize()
    app = QGuiApplication.instance() or QGuiApplication([])
    errors = []
    with tempfile.TemporaryDirectory(prefix="gg-research-workspace-") as raw:
        with patch.object(research_desk, "ROOT", Path(raw) / "desk"), patch.object(research_jobs, "ROOT", Path(raw) / "jobs"):
            bridge = Bridge()
            engine = QQmlApplicationEngine()
            engine.rootContext().setContextProperty("testBridge", bridge)
            qml = f'''import QtQuick
import QtQuick.Window
import "{(PROJECT / 'qml/components').as_uri()}" as GG
Window {{
    width: 1100; height: 760; visible: true
    property var surfaceHost: testBridge
    GG.WorkspaceSurface {{ objectName: "testWorkspace"; anchors.fill: parent; desktopShell: true }}
}}'''
            preview = Path(raw) / "preview.qml"
            preview.write_text(qml)
            component = QQmlComponent(engine, QUrl.fromLocalFile(str(preview)), QQmlComponent.Asynchronous)
            deadline = time.monotonic() + 10
            while component.isLoading() and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.005)
            assert component.isReady(), [e.toString() for e in component.errors()]
            window = component.create()
            assert window is not None, [e.toString() for e in component.errors()]
            qInstallMessageHandler(lambda _kind, _context, msg: errors.append(str(msg)))
            workspace = window.findChild(QObject, "testWorkspace")
            workspace.setProperty("hostKind", "RESEARCH")
            app.processEvents()
            research = next(obj for obj in workspace.findChildren(QObject, "workspaceResearchPane")
                            if obj.metaObject().indexOfProperty("taskTitle") >= 0)
            qip = research.findChild(QObject, "workspaceQipPane")
            reverse = research.findChild(QObject, "workspaceReversePane")
            assert qip is not None and reverse is not None
            games = research.findChild(QObject, "workspaceGameWorkflowsPane")
            assert games is not None
            assert len(workspace.findChildren(QObject, "workspaceKindResearch")) == 1
            assert workspace.findChild(QObject, "workspaceKindQIP") is None
            assert workbench_registry.extension_id_for_host_kind("QIP") == "gg.surface.research"
            kinds = [row["hostKind"] for row in workbench_registry.BUILTIN_EXTENSIONS]
            assert kinds[kinds.index("OSINT") + 1:kinds.index("OSINT") + 3] == ["RESEARCH", "MEDIA"]
            assert "QIP" not in kinds

            research.setProperty("taskTitle", "Keep my unfinished draft")
            qip.setProperty("modulePath", "file:///fixture.wasm")
            workspace.setProperty("hostKind", "CODE")
            app.processEvents()
            assert research.property("taskTitle") == "Keep my unfinished draft"
            workspace.setProperty("hostKind", "QIP")
            app.processEvents()
            assert workspace.property("hostKind") == "RESEARCH"
            assert research.property("page") == "WASM LAB"
            assert qip.property("modulePath") == "file:///fixture.wasm"
            assert research.property("taskTitle") == "Keep my unfinished draft"
            workspace.setProperty("settingsOpen", True)
            app.processEvents()
            workspace.setProperty("settingsOpen", False)
            app.processEvents()
            assert research.property("taskTitle") == "Keep my unfinished draft"

            target = Path(raw) / "component.js"
            target.write_text("export function render() { return 'observable'; }\n")
            research.setProperty("page", "GAMES")
            games.setProperty("stage", 1)
            games.setProperty("targetPath", target.as_uri())
            app.processEvents()
            assert games.property("visible")
            assert QMetaObject.invokeMethod(games.findChild(QObject, "gameOpenReverse"), "clicked")
            app.processEvents()
            assert research.property("page") == "REVERSE"
            assert json.loads(reverse.property("reportJson"))["path"] == str(target)
            invoke = engine.evaluate("(function(item, path) { item.inspectArtifact(path); })")
            result = invoke.call([engine.newQObject(reverse), QJSValue(target.as_uri())])
            assert not result.isError(), result.toString()
            assert json.loads(reverse.property("reportJson"))["status"] == "INSPECTED"
            reverse.findChild(QObject, "reverseFindingTitle").setProperty("text", "Renderer export")
            reverse.findChild(QObject, "reverseFindingText").setProperty("text", "The selected source contains a render export.")
            reverse.findChild(QObject, "reverseLessonText").setProperty("text", "Inspect the export\nTest behavior independently")
            assert QMetaObject.invokeMethod(reverse, "saveFinding")
            app.processEvents()
            assert research.property("page") == "EVIDENCE"
            saved = research_desk.snapshot()
            assert len(saved["evidence"]) == 1
            assert saved["methods"][0]["status"] == "PROPOSED"

            # Exercise the actual async dispatcher/worker and Qt event loop.
            if (research_lab.TOOLS_ROOT / "rea/node_modules/rea-agents/scripts/rea.mjs").is_file():
                research.setProperty("page", "REVERSE")
                assert QMetaObject.invokeMethod(reverse, "startAnalysis")
                deadline = time.monotonic() + 10
                while reverse.property("busy") and time.monotonic() < deadline:
                    app.processEvents()
                    time.sleep(0.01)
                assert reverse.property("jobState") == "COMPLETE", reverse.property("notice")
                report = json.loads(reverse.property("reportJson"))
                assert report["provenance"] == "LOCAL_ENGINE_STATIC_OBSERVATION"
                assert not (research_jobs._dir(reverse.property("jobId")) / "scratch").exists()
                assert QMetaObject.invokeMethod(reverse, "restoreLastReport")
                assert json.loads(reverse.property("reportJson"))["report_id"] == report["report_id"]
                reverse.findChild(QObject, "reverseFindingTitle").setProperty("text", "Engine renderer observation")
                assert QMetaObject.invokeMethod(reverse, "saveFinding")
                assert len(research_desk.snapshot()["evidence"]) == 2

            research.setProperty("page", "MEMORY")
            methods = research_desk.snapshot()["methods"]
            check = engine.evaluate("(function(item, id) { item.command('lab_verify', {method_id:id}); })")
            result = check.call([engine.newQObject(research), QJSValue(methods[0]['id'])])
            assert not result.isError(), result.toString()
            assert 'independent test' in research.property('notice')

            screenshots = Path(sys.argv[1]) if len(sys.argv) > 1 else None
            if screenshots:
                screenshots.mkdir(parents=True, exist_ok=True)
                for page in ["BACKLOG", "MEMORY", "WASM LAB", "REVERSE"]:
                    research.setProperty("page", page)
                    wait = QEventLoop()
                    QTimer.singleShot(100, wait.quit)
                    wait.exec()
                    assert window.grabWindow().save(str(screenshots / (page.replace(" ", "_") + ".png")))
                window.setWidth(720)
                wait = QEventLoop()
                QTimer.singleShot(100, wait.quit)
                wait.exec()
                assert window.grabWindow().save(str(screenshots / "REVERSE_NARROW.png"))
                # A real persisted native result verifies readable pseudocode.
                verification = Path("/home/GG/.local/state/goldgoblins/gg-ai-desktop/research-jobs")
                reports = sorted(verification.glob("*/report.json"), key=lambda p: p.stat().st_mtime, reverse=True)
                for path in reports:
                    report = json.loads(path.read_text())
                    if report.get("operation") == "decompile":
                        window.setWidth(1100)
                        research.setProperty("page", "REVERSE")
                        reverse.setProperty("reportJson", json.dumps(report))
                        reverse.setProperty("targetPath", report['path'])
                        reverse.findChild(QObject, "reverseOperation").setProperty("currentIndex", 3)
                        reverse.findChild(QObject, "reverseQuery").setProperty("text", "gg_stack_next")
                        reverse.findChild(QObject, "reverseFindingTitle").setProperty("text", "Known arithmetic observation")
                        reverse.findChild(QObject, "reverseFindingText").setProperty("text", "The fixture pseudocode returns value + 7.")
                        reverse.findChild(QObject, "reverseLessonText").setProperty("text", "Compare pseudocode with the known source.\nVerify new behavioral claims independently.")
                        wait = QEventLoop()
                        QTimer.singleShot(100, wait.quit)
                        wait.exec()
                        assert "return value + 7" in reverse.property("pseudocode")
                        assert window.grabWindow().save(str(screenshots / "NATIVE_PSEUDOCODE.png"))
                        break
            # Unchanged KDE controls and the pre-existing SettingsSurface title
            # emit upstream layout warnings in this reduced window fixture.
            unrelated = ("qrc:/qt/qml/org/kde/breeze/TextArea.qml:92:9:",
                         "qml/components/SettingsSurface.qml:118:17:")
            bad = [message for message in errors if not any(token in message for token in unrelated) and any(token in message for token in
                   ["ReferenceError", "TypeError", "Cannot assign", "Unable to assign", "is not a type", "Binding loop"])]
            assert not bad, bad
            window.close()
            engine.deleteLater()
            app.processEvents()
    qInstallMessageHandler(None)
    faulthandler.cancel_dump_traceback_later()
    print("RESEARCH_WORKSPACE_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
