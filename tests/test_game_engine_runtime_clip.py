"""Offscreen regression for the real node-animation RuntimeLoader adapter."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QByteArray, QObject, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlComponent, QQmlContext, QQmlEngine
from PySide6.QtQuick import QQuickWindow

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))


def _timeline_rows(loader: QObject) -> list[tuple[str, bool, bool]]:
    rows: list[tuple[str, bool, bool]] = []
    for candidate in [loader, *loader.findChildren(QObject)]:
        if candidate.metaObject().className() != "QQuickTimelineAnimation":
            continue
        parent = candidate.parent()
        rows.append(
            (
                candidate.objectName(),
                bool(candidate.property("running")),
                bool(parent.property("enabled")) if parent is not None else False,
            )
        )
    return rows


def main() -> int:
    from backend.chat_surface_host import ChatSurfaceHost

    app = QGuiApplication.instance() or QGuiApplication([])
    engine = QQmlEngine()
    component = QQmlComponent(engine)
    source = QUrl.fromLocalFile(
        str(PROJECT / "qml" / "assets" / "third_party" / "kenney-blocky" / "character-a.glb")
    ).toString()
    qml = f"""
import QtQuick
import QtQuick3D
import QtQuick3D.AssetUtils
Item {{
    View3D {{
        anchors.fill: parent
        RuntimeLoader {{
            objectName: "probeLoader"
            source: "{source}"
        }}
    }}
}}
"""
    component.setData(
        QByteArray(qml.encode("utf-8")),
        QUrl.fromLocalFile(str(PROJECT / "runtime-clip-probe.qml")),
    )
    root = component.create(QQmlContext(engine.rootContext()))
    errors = component.errors()
    if root is None or errors:
        raise AssertionError([error.toString() for error in errors])

    window = QQuickWindow()
    window.resize(320, 240)
    root.setParentItem(window.contentItem())
    root.setWidth(320)
    root.setHeight(240)
    window.show()
    loader = root.findChildren(QObject, "probeLoader")
    assert len(loader) == 1
    runtime_loader = loader[0]

    for _ in range(500):
        app.processEvents()
    assert runtime_loader.property("errorString") == "Success!"

    from types import SimpleNamespace
    bridge = SimpleNamespace(_game_engine_runtime_clip_driver=None)
    before = _timeline_rows(runtime_loader)
    assert len(before) == 27
    assert ChatSurfaceHost.gameEngineRuntimeClip(bridge, runtime_loader, "walk") is True
    after = dict(
        (name, (running, enabled))
        for name, running, enabled in _timeline_rows(runtime_loader)
    )
    assert after["walk"] == (True, True)
    assert after["idle"] == (False, False)
    assert after["sprint"] == (False, False)
    assert sum(running or enabled for running, enabled in after.values()) == 1

    assert ChatSurfaceHost.gameEngineRuntimeClip(bridge, runtime_loader, "") is True
    stopped = _timeline_rows(runtime_loader)
    assert all(not running and not enabled for _, running, enabled in stopped)

    assert ChatSurfaceHost.gameEngineRuntimeClip(bridge, runtime_loader, 'walk')
    bridge._game_engine_runtime_clip_driver.close()
    bridge._game_engine_runtime_clip_driver.close()
    assert all(not running and not enabled for _, running, enabled in _timeline_rows(runtime_loader))
    assert not ChatSurfaceHost.gameEngineRuntimeClip(bridge, runtime_loader, 'idle')

    print("GAME_ENGINE_RUNTIME_CLIP_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
