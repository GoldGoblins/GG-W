"""Exercise real QML key edges through the standalone bridge and simulation."""
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("XDG_STATE_HOME", "/tmp/gg-qml-targeting-state")
PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlComponent, QQmlEngine, QQmlExpression
from backend import game_engine_host
from backend.game_client_host import GameClientHost


def main():
    app = QGuiApplication([])
    engine = QQmlEngine()
    host = GameClientHost()
    component = QQmlComponent(engine, QUrl.fromLocalFile(
        str(PROJECT / "qml/components/GameEngineSurface.qml")))
    root = component.create()
    assert root is not None, [e.toString() for e in component.errors()]
    root.setProperty("surfaceHost", host)
    root.setProperty("statusJson", host.gameEngineStatus())
    root.setProperty("page", "PLAY")
    runtime = game_engine_host._RUNTIME
    for index,(x,z) in zip(runtime._npc_indices[:2],[(10.0,12.0),(-12.0,10.0)]):
        runtime._x[index],runtime._z[index]=x,z
        runtime._y[index]=runtime._terrain_height_locked(x,z)+.65
    # TAB considers hostile living units; friendly villagers remain click targets.
    runtime._ecology_view_locked()
    runtime._nature.rows=[]
    for index in runtime._npc_indices[:2]:
        identity=runtime._npc_ids[index]
        runtime._faction_state['people'][identity]={'standing':-75,'disposition':'HOSTILE'}
    root.setProperty("statusJson", host.gameEngineStatus())

    def evaluate(source):
        expression = QQmlExpression(engine.rootContext(), root, source)
        result, undefined = expression.evaluate()
        assert not expression.hasError(), expression.error().toString()
        return result

    def key(code, pressed):
        return evaluate(f"setKeyState({int(code)}, {str(pressed).lower()})")

    def selected():
        return json.loads(root.property("renderStatusJson"))["targeting"]["selected"]

    try:
        assert key(Qt.Key_Tab, True)
        first = selected()
        assert first and first["distance_m"] <= 64
        key(Qt.Key_Tab, True)  # Keyboard repeat must not cycle targets.
        assert selected()["id"] == first["id"]
        key(Qt.Key_Tab, False)
        key(Qt.Key_Tab, True)
        second = selected()
        assert second["id"] != first["id"]
        key(Qt.Key_Tab, False)
        key(Qt.Key_Shift, True)
        key(Qt.Key_Backtab, True)
        assert selected()["id"] == first["id"]
        key(Qt.Key_Backtab, False)
        key(Qt.Key_Shift, False)
        health = runtime._combat_state["actors"][first["id"]]["health"]
        key(Qt.Key_T, True)
        assert runtime._actions.auto_attack
        key(Qt.Key_T, True)  # Repeat does not toggle auto attack off.
        assert runtime._actions.auto_attack
        assert runtime._combat_state["actors"][first["id"]]["health"] == health
        key(Qt.Key_T, False)
        key(Qt.Key_T, True)
        assert not runtime._actions.auto_attack
        key(Qt.Key_T, False)
        key(Qt.Key_V, True)
        assert runtime._vehicle_kind == "HOVERBOARD"
        assert runtime._combat_state["actors"][first["id"]]["health"] == health
        key(Qt.Key_V, False)
        key(Qt.Key_V, True)
        assert runtime._vehicle_kind == "NONE"
        key(Qt.Key_V, False)
        key(Qt.Key_Escape, True)
        assert not selected()
        assert root.property("page") == "PLAY"
        assert root.property("frustumCullingEnabled") is True
        evaluate("exploreRegion('WESTREACH')")
        assert runtime._x[0] == -7350 and runtime._movement_mode == "FLY"
        assert root.property("page") == "PLAY"
    finally:
        root.deleteLater()
        app.processEvents()
    print("GAME_ENGINE_QML_TARGETING_TEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
