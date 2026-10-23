"""Regression test for the single shared low-poly character model in QML."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlComponent, QQmlContext, QQmlEngine
from PySide6.QtQuick import QQuickWindow

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))


def _status(motion_state: str, phase: float) -> str:
    pose_values = {
        "IDLE": (0.035, 1.0, -1.5, 0.0),
        "WALK": (0.075, 3.0, -5.0, -0.02),
        "SPRINT": (0.11, 5.0, -9.0, -0.04),
    }
    bob_m, lean_deg, sway_deg, squash = pose_values.get(
        motion_state,
        (0.0, 0.0, 0.0, 0.0),
    )
    row = {
        "id": "e-0000",
        "kind": "PLAYER",
        "x": 0.0,
        "y": 0.0,
        "z": 0.0,
        "yaw": 0.0,
        "sx": 1.0,
        "sy": 1.0,
        "sz": 1.0,
        "color": "#d38a45",
        "animation": {
            "state": motion_state,
            "phase": phase,
            "bob_m": bob_m,
            "lean_deg": lean_deg,
            "sway_deg": sway_deg,
            "squash": squash,
        },
    }
    return json.dumps(
        {
            "state": "RUNNING",
            "render": {"entities": [row], "particles": []},
            "terrain": {"cells": []},
            "player": {"x": 0.0, "y": 0.0, "z": 0.0},
            "cinematic": {},
            "replay": {},
            "simulation": {},
            "input": {},
            "controller": {},
            "physics": {},
            "npc": {},
            "addons": {},
            "network": {},
            "content": {},
            "combat": {},
            "inventory": {},
            "crafting": {},
            "progression": {},
            "editor": {},
            "navigation": {},
        }
    )


def main() -> int:
    app = QGuiApplication.instance() or QGuiApplication([])
    host = QObject()
    engine = QQmlEngine()
    component = QQmlComponent(
        engine,
        QUrl.fromLocalFile(
            str(PROJECT / "qml" / "components" / "GameEngineSurface.qml")
        ),
    )
    context = QQmlContext(engine.rootContext())
    root = component.create(context)
    errors = component.errors()
    if root is None:
        raise AssertionError([error.toString() for error in errors])
    if errors:
        raise AssertionError([error.toString() for error in errors])

    window = QQuickWindow()
    window.resize(320, 240)
    root.setParentItem(window.contentItem())
    root.setWidth(320)
    root.setHeight(240)
    root.setProperty("surfaceHost", host)
    window.show()

    try:
        rectangle_model = None
        for motion_state, phase in (
            ("IDLE", 0.0),
            ("WALK", 1.5707963267948966),
            ("SPRINT", 3.141592653589793),
        ):
            root.setProperty("statusJson", _status(motion_state, phase))
            for _ in range(12):
                app.processEvents()
            figures = root.findChildren(QObject, "gameEntityFigure")
            assert len(figures) == 1
            figure = figures[0]
            assert figure.property("entityKind") == "PLAYER"
            assert figure.property("authoredAssetVisible") is False
            body_models = figure.findChildren(QObject, "gameCharacterBodyModel")
            assert len(body_models) == 1
            body = body_models[0]
            assert body.property("visible") is True
            assert body.property("source") == ""
            assert not figure.findChildren(QObject, "gamePreviewHead")
            if rectangle_model is None:
                rectangle_model = body
            else:
                assert body is rectangle_model
            position = body.property("position")
            assert position.y() > 0.0
            rotation = body.property("eulerRotation")
            assert abs(rotation.x()) > 0.0
            assert abs(rotation.y()) > 0.0
    finally:
        window.close()
        root.setParentItem(None)
        root.deleteLater()
        host.deleteLater()
        app.processEvents()

    print("GAME_ENGINE_QML_POSE_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
