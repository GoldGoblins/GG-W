"""Real QML/authoritative simulation regression for crew migration and mouse steering."""
from __future__ import annotations
import json
import math
import os
import sys
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("XDG_STATE_HOME", "/tmp/gg-camera-test-state")
PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from PySide6.QtCore import QObject, Qt, QUrl, QCoreApplication, QEvent
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

    def js(source):
        expression = QQmlExpression(engine.rootContext(), root, source)
        result, undefined = expression.evaluate()
        assert not expression.hasError(), expression.error().toString()
        return result

    def close(actual, expected, tolerance=0.02):
        assert abs(actual-expected) < tolerance, (actual, expected)

    def key(code, pressed):
        js(f"setKeyState({int(code)}, {str(pressed).lower()})")

    try:
        initial = math.degrees(runtime._yaw[0])
        # LMB leaves character facing untouched, and Smart follow keeps an idle view.
        js("beginCameraLook(Qt.LeftButton); dragCameraLook(120, 0)")
        close(root.property("cameraHeading"), initial-27)
        close(math.degrees(runtime._yaw[0]), initial)
        js("endCameraLook(Qt.LeftButton); followCamera(1)")
        close(root.property("orbitYaw"), -27)
        key(Qt.Key_W, True)
        js("followCamera(0.5)")
        close(root.property("orbitYaw"), 0)
        key(Qt.Key_W, False)
        # Drag right steers right in the rendered coordinate frame (forward is +Z).
        js("beginCameraLook(Qt.RightButton); dragCameraLook(80, 0)")
        close(math.degrees(runtime._yaw[0]), initial-18)
        close(root.property("cameraHeading"), initial-18)
        key(Qt.Key_D, True)
        assert runtime._input["turn"] == 0 and runtime._input["strafe"] == 1
        key(Qt.Key_D, False)
        js("endCameraLook(Qt.RightButton)")
        close(root.property("orbitYaw"), 0)
        close(root.property("cameraHeading"), math.degrees(runtime._yaw[0]))
        assert not runtime._input["mouse_look"]
        key(Qt.Key_W, True)
        x, z = runtime._x[0], runtime._z[0]
        with runtime._lock:
            runtime._running = True
            for _ in range(20): runtime._tick_locked(game_engine_host.FIXED_DT)
            runtime._running = False
        assert runtime._x[0] < x and runtime._z[0] > z, "Forward must follow the new facing"
        key(Qt.Key_W, False)
        # Both-button movement and transitions preserve the last view without a jump.
        js("beginCameraLook(Qt.LeftButton); beginCameraLook(Qt.RightButton); dragCameraLook(40, 10)")
        assert runtime._input["forward"] == 1
        heading = root.property("cameraHeading")
        js("endCameraLook(Qt.RightButton)")
        close(root.property("cameraHeading"), heading)
        assert runtime._input["forward"] == 0
        js("endCameraLook(Qt.LeftButton)")
        close(root.property("cameraHeading"), heading)
        # Losing capture/focus/menu ownership cannot leave a both-button autorun behind.
        js("beginCameraLook(Qt.LeftButton); beginCameraLook(Qt.RightButton); clearMovementInput()")
        assert not runtime._input["mouse_look"] and runtime._input["forward"] == 0
        assert not root.property("mouseLeftHeld") and not root.property("mouseRightHeld")
        # Wrap-around never flips the view on release.
        js("mouseLookHeading=179; beginCameraLook(Qt.RightButton); mouseLookHeading=179; dragCameraLook(-20, 0)")
        close(math.degrees(runtime._yaw[0]), -176.5)
        js("endCameraLook(Qt.RightButton)")
        close(root.property("cameraHeading"), -176.5)
        # A recorded mouse packet restores facing at the same simulation boundary.
        runtime._replaying = True
        runtime._replay_inputs = [{"mouse_look": True, "facing_yaw": 37, "camera_distance": 2}]
        runtime._replay_index = 0
        runtime._set_replay_input_locked()
        close(math.degrees(runtime._yaw[0]), 37)
        assert runtime._camera_distance == 2
        runtime._replaying = False
        # Every historical source and missing/fallback metadata resolves to approved GLBs.
        ids = ["gg-codex-original", "gg-codex-character-flow", "gg-codex-cartoon-flow",
               "gg-codex-art-flow", "gg-codex-sculpt-flow", "gg-codex-style-flow",
               "gg-codex-riftclaw", "gg-codex-briarstride", "gg-codex-mossjaw"]
        names = ["brinekip", "copperwake", "glassfin", "mosswake", "tideclaw",
                 "reefrunner", "riftclaw", "briarstride", "mossjaw"]
        for asset_id, name in zip(ids, names):
            path = js("crewSource(" + json.dumps({"id":asset_id,"source":"old-ball.glb"}) + ", 'npc', 'NPC')").toString()
            assert path.endswith("gg-crew-"+name+"-articulated.glb"), path
        assert js("crewSource({}, 'player', 'PLAYER')").toString().endswith("gg-crew-brinekip-articulated.glb")
        for source in ("gg-crew-brinekip-v35.glb", "gg-crew-brinekip-animated-v35.glb"):
            resolved = js("crewSource(" + json.dumps({"source":source}) + ", 'npc', 'NPC')").toString()
            assert resolved.endswith("variants/characters/gg-crew-brinekip-articulated-v35.glb"), resolved
        assert "gg-crew-" in js("crewSource({source:'old-ball.glb'}, 'villager', 'NPC')").toString()
        for asset in ({'source':'gg-crew-mossjaw-compact-v18.glb'},
                      {'source':'gg-crew-mossjaw-animated-v18.glb','instance_rank':8}):
            resolved=js('crewSource('+json.dumps(asset)+", 'npc', 'NPC')").toString()
            assert resolved.endswith('gg-crew-mossjaw-compact-v18.glb'),resolved
        # Inject a complete stale snapshot; verify instantiated loaders, not just backend metadata.
        stale = game_engine_host.render_status_payload()
        for row in stale["render"]["entities"]:
            if row.get("kind") in ("PLAYER", "NPC", "ACTOR") or "NPC" in row.get("kind", ""):
                row["asset"] = {"mode":"PROCEDURAL", "source":"old-ball.glb", "instance_rank":0, "instance_budget":8}
        js("installRenderStatus(" + json.dumps(json.dumps(stale)) + ")")
        for _ in range(25): app.processEvents()
        assert not root.findChildren(QObject, "gameCharacterBodyModel")
        loaders = root.findChildren(QObject, "gameAuthoredAssetLoader")
        assert len(loaders) >= 9, len(loaders)
        for loader in loaders:
            source = loader.property("source").toString()
            assert "/gg-crew-" in source and source.endswith(".glb"), source
        # Physical boom has a head/torso pivot and no former elevated default.
        js("orbitPitch=-8; cameraDistance=6")
        player = json.loads(root.property("renderStatusJson"))["player"]
        close(root.property("renderCameraY")-player["y"], .8+6*math.sin(math.radians(8)))
        dx = root.property("renderCameraX")-player["x"]
        dz = root.property("renderCameraZ")-player["z"]
        close(math.hypot(dx,dz), 6*math.cos(math.radians(8)))
        # A world interaction uses its real authored tool at the palm and
        # stows hand weapons without changing equipped inventory ownership.
        from backend import game_engine_items as item_state
        weapon = item_state.make_instance(runtime._item_catalog, "world-action-grip-test", "item.weapon_sword",
                                         location="EQUIPPED", owner_id="player", equipped_slot="MAIN_HAND")
        runtime._item_instances[weapon["instance_id"]] = weapon
        frame = game_engine_host.render_status_payload()
        player_row = next(row for row in frame["render"]["entities"] if row["kind"] == "PLAYER")
        player_row["animation"].update(action="FishCast", action_serial=991,
                                       world_interaction=True, interaction_tool="rod")
        player_row["asset"]["runtime_clip"] = "FishCast"
        js("installRenderStatus(" + json.dumps(json.dumps(frame)) + ")")
        for _ in range(300):
            app.processEvents()
            QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)
        tools = [node for node in root.findChildren(QObject, "gameWorldActionTool")
                 if node.property("tool") == "rod"]
        assert len(tools) == 1 and tools[0].property("active")
        mesh = tools[0].property("item")
        assert mesh and mesh.property("errorString") == "Success!"
        assert mesh.property("source").toString().endswith("tool-rod.glb")
        assert tools[0].property("grip").objectName().startswith("SOCKET_MAIN_HAND")
        hand_gear = [node for node in root.findChildren(QObject, "gameEquippedItemModel")
                     if node.property("socketNode") == tools[0].property("grip")]
        assert hand_gear and all(not node.property("visible") for node in hand_gear)
    finally:
        runtime.shutdown()
        root.deleteLater()
        app.processEvents()
    print("GAME_ENGINE_QML_CAMERA_TEST=PASS")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
