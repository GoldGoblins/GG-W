"""Offscreen regression for the lightweight QML movement-input seam."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QUrl, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlComponent, QQmlContext, QQmlEngine
from PySide6.QtQuick import QQuickWindow

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))


class MovementHost(QObject):
    """Minimal host that records which input transport QML selected."""

    def __init__(self, runtime) -> None:
        super().__init__()
        self.runtime = runtime
        self.full_input_calls = 0
        self.render_input_calls = 0
        self.geometry = None
        self.sphere_geometry = None

    @Slot(result=QObject)
    def gameEngineLowPolySphereGeometry(self) -> QObject:
        if self.sphere_geometry is None:
            from backend.game_engine_geometry import build_low_poly_sphere_geometry

            self.sphere_geometry = build_low_poly_sphere_geometry()
            self.sphere_geometry.setParent(self)
            QQmlEngine.setObjectOwnership(
                self.sphere_geometry,
                QQmlEngine.CppOwnership,
            )
        return self.sphere_geometry

    def _character_geometry(self):
        if self.geometry is None:
            from backend.game_engine_geometry import build_character_geometry

            self.geometry = build_character_geometry()
            self.geometry.setParent(self)
            QQmlEngine.setObjectOwnership(self.geometry, QQmlEngine.CppOwnership)
        return self.geometry

    @Slot(result=QObject)
    def gameEngineCharacterGeometry(self) -> QObject:
        return self._character_geometry()

    @Slot(str, float, result=QObject)
    def gameEngineCharacterGeometryForPose(
        self,
        motion_state: str,
        phase: float,
    ) -> QObject:
        return self._character_geometry()

    @Slot(str, result=str)
    def gameEngineInput(self, raw: str) -> str:
        self.full_input_calls += 1
        return json.dumps(self.runtime.set_input(raw), separators=(",", ":"))

    @Slot(str, result=str)
    def gameEngineInputRender(self, raw: str) -> str:
        self.render_input_calls += 1
        return json.dumps(
            self.runtime.set_input_render(raw), separators=(",", ":")
        )


def main() -> int:
    from backend.game_engine_host import GameEngineRuntime

    app = QGuiApplication.instance() or QGuiApplication([])
    runtime = GameEngineRuntime()
    host = MovementHost(runtime)
    engine = QQmlEngine()
    component = QQmlComponent(
        engine,
        QUrl.fromLocalFile(
            str(PROJECT / "qml" / "components" / "GameEngineSurface.qml")
        ),
    )
    root = component.create(QQmlContext(engine.rootContext()))
    errors = component.errors()
    if root is None or errors:
        raise AssertionError([error.toString() for error in errors])

    window = QQuickWindow()
    window.resize(640, 480)
    root.setParentItem(window.contentItem())
    root.setWidth(640)
    root.setHeight(480)
    root.setProperty("surfaceHost", host)
    window.show()

    try:
        baseline = runtime.snapshot()
        baseline_json = json.dumps(baseline, separators=(",", ":"))
        root.setProperty("statusJson", baseline_json)
        for _ in range(50):
            app.processEvents()

        before_render = host.render_input_calls
        before_full = host.full_input_calls
        root.setProperty("throttle", 1.0)
        root.sendInput()
        for _ in range(20):
            app.processEvents()

        assert host.render_input_calls == before_render + 1
        assert host.full_input_calls == before_full
        assert root.property("statusJson") == baseline_json
        render_status = json.loads(root.property("renderStatusJson"))
        assert render_status["schema"] == "gg.game-engine.render-snapshot.v1"
        assert runtime.snapshot()["input"]["throttle"] == 1.0
    finally:
        window.close()
        root.setParentItem(None)
        root.deleteLater()
        runtime.shutdown()
        host.deleteLater()
        app.processEvents()

    print("GAME_ENGINE_QML_MOVEMENT_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
