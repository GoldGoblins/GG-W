"""Offscreen regression for the terminal-style QML presentation fallback."""

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


class FallbackHost(QObject):
    """Small bridge sufficient for the shared GameEngineSurface component."""

    def __init__(self) -> None:
        super().__init__()
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

    @Slot(result=QObject)
    def gameEngineCharacterGeometry(self) -> QObject:
        from backend.game_engine_geometry import build_character_geometry

        geometry = build_character_geometry()
        geometry.setParent(self)
        QQmlEngine.setObjectOwnership(geometry, QQmlEngine.CppOwnership)
        return geometry

    @Slot(str, float, result=QObject)
    def gameEngineCharacterGeometryForPose(
        self,
        motion_state: str,
        phase: float,
    ) -> QObject:
        from backend.game_engine_geometry import (
            CHARACTER_POSE_BUCKETS,
            build_character_geometry,
            character_pose_key,
        )

        key = character_pose_key(motion_state, phase)
        geometry = build_character_geometry(
            key[0],
            key[1] / float(CHARACTER_POSE_BUCKETS) * 6.283185307179586,
        )
        geometry.setParent(self)
        QQmlEngine.setObjectOwnership(geometry, QQmlEngine.CppOwnership)
        return geometry


def main() -> int:
    from backend.game_engine_host import GameEngineRuntime

    app = QGuiApplication.instance() or QGuiApplication([])
    runtime = GameEngineRuntime()
    host = FallbackHost()
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

    def settle() -> None:
        for _ in range(24):
            app.processEvents()

    try:
        rich_snapshot = runtime.snapshot()
        root.setProperty("statusJson", json.dumps(rich_snapshot))
        settle()
        assert root.property("dosFallbackActive") is False
        fallback_layer = root.findChildren(QObject, "gameEngineDosFallback")
        assert fallback_layer and fallback_layer[0].property("visible") is False

        dos_snapshot = runtime.set_presentation_mode("DOS_2D")
        root.setProperty("statusJson", json.dumps(dos_snapshot))
        settle()
        assert root.property("presentationMode") == "DOS_2D"
        assert root.property("dosFallbackActive") is True
        assert fallback_layer[0].property("visible") is True
        canvas = root.findChildren(QObject, "gameEngineDosFallbackCanvas")
        assert canvas and canvas[0].property("visible") is True

        restored = runtime.set_presentation_mode("RICH_3D")
        root.setProperty("statusJson", json.dumps(restored))
        settle()
        assert root.property("presentationMode") == "RICH_3D"
        assert root.property("dosFallbackActive") is False
        assert fallback_layer[0].property("visible") is False
    finally:
        window.close()
        root.setParentItem(None)
        root.deleteLater()
        host.deleteLater()
        runtime.shutdown()
        app.processEvents()

    print("GAME_ENGINE_QML_FALLBACK_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
