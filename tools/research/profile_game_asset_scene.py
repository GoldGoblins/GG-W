"""Measure one finite packaged-asset experiment with actual QtQuick3D counters.

Run a scene-profile plan created by gg-game-workflows asset-profile or GAMES.
No live world is altered; full, visibility and existing LOD are sampled in a
separate window. Graphics API and unavailable GPU counters remain explicit.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan")
    parser.add_argument("--store", help="Workflow store containing the plan")
    parser.add_argument("--samples", type=int, default=24)
    args = parser.parse_args()
    if args.store:
        os.environ["GG_GAME_WORKFLOWS_ROOT"] = str(Path(args.store).resolve())
    if not 3 <= args.samples <= 120:
        parser.error("samples must be 3..120")
    from backend import game_workflow_common as common, game_workflow_profile as profile
    plan = profile.load(args.plan)
    from PySide6.QtCore import QTimer, QUrl, QMetaObject, Q_RETURN_ARG
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuick import QQuickWindow
    import game_client_main
    app = QGuiApplication([])
    engine = QQmlApplicationEngine()
    samples, captures, screenshots, failures = [], [], {}, []
    state = {"stage": 0, "samples": 0, "waits": 0, "capture": False}
    qml_text = '''import QtQuick
import QtQuick.Window
import QtQuick3D
import QtQuick3D.AssetUtils
Window { id:win; width:800; height:600; visible:true; title:"GG asset scene measurement"
 property var assets:[]; property string stage:"FULL"
 function measurement() {
  var ready=0,shown=0;
  for(var i=0;i<models.count;i++){var n=models.objectAt(i);if(n.ready)ready++;if(n.visible)shown++;}
  return JSON.stringify({stage:stage,loaded_models:ready,visible_models:shown,
   frame_ms:view.renderStats.frameTime,sync_cpu_ms:view.renderStats.syncTime,
   render_cpu_ms:view.renderStats.renderTime,
   gpu_window_ms:view.renderStats.lastCompletedGpuTime>0?view.renderStats.lastCompletedGpuTime:null,
   draw_calls:view.renderStats.drawCallCount,render_passes:view.renderStats.renderPassCount,
   graphics_api:view.renderStats.graphicsApiName});
 }
 View3D { id:view;anchors.fill:parent
  Component.onCompleted:renderStats.extendedDataCollectionEnabled=true
  environment:SceneEnvironment {backgroundMode:SceneEnvironment.Color;clearColor:"#202b35"}
  PerspectiveCamera {position:Qt.vector3d(0,0,Math.max(6,win.assets.length*2.2));clipNear:.01;clipFar:200}
  DirectionalLight {eulerRotation:Qt.vector3d(-30,-25,0);brightness:1}
  Repeater3D {id:models;model:win.assets
   delegate:Node {required property var modelData;required property int index
    readonly property bool ready:loader.status===RuntimeLoader.Success
    readonly property real span:Math.max(.001,loader.bounds.maximum.y-loader.bounds.minimum.y)
    readonly property real unit:2/span
    visible:win.stage!=="VISIBILITY" || (win.assets.length>1 && index%2===0)
    position:Qt.vector3d((index-(win.assets.length-1)/2)*2.8,0,0)
    scale:Qt.vector3d(unit,unit,unit)
    RuntimeLoader {id:loader;source:win.stage==="LOD"?modelData.lod:modelData.full
     position:Qt.vector3d(-(bounds.maximum.x+bounds.minimum.x)/2,
                         -(bounds.maximum.y+bounds.minimum.y)/2,
                         -(bounds.maximum.z+bounds.minimum.z)/2)
    }
   }
  }
 }
 Text {anchors.left:parent.left;anchors.top:parent.top;anchors.margins:12;color:"white";text:"GG · "+win.stage+" · actual Qt counters"}
}'''
    with tempfile.TemporaryDirectory(prefix="gg-scene-profile-") as temporary:
        qml = Path(temporary) / "profile.qml"
        qml.write_text(qml_text)
        engine.setInitialProperties({"assets": [{"full": Path(row["full"]["path"]).as_uri(), "lod": Path(row["lod"]["path"]).as_uri()} for row in plan["assets"]]})
        engine.load(QUrl.fromLocalFile(str(qml)))
        if not engine.rootObjects():
            raise ValueError("QT_PROFILE_SCENE_LOAD_FAILED")
        window = engine.rootObjects()[0]
        # Force actual frames even when all imported models are static. Sampling
        # unchanged counters from the last frame is not a timing experiment.
        render_timer = QTimer()
        render_timer.setInterval(16)
        render_timer.timeout.connect(window.update)
        render_timer.start()
        name = common.digest(common.read_file(args.plan)[1])[:24]
        timer = QTimer()
        timer.setInterval(100)

        def advance():
            state["stage"] += 1
            state.update(samples=0, waits=0, capture=False)
            if state["stage"] == len(profile.STAGES):
                timer.stop()
                app.quit()
            else:
                window.setProperty("stage", profile.STAGES[state["stage"]])
                QTimer.singleShot(1200, timer.start)

        def tick():
            if state["capture"]:
                return
            row = json.loads(QMetaObject.invokeMethod(window, "measurement", Q_RETURN_ARG("QVariant")))
            if row["loaded_models"] != len(plan["assets"]):
                state["waits"] += 1
                if state["waits"] > 80:
                    failures.append("QT_PROFILE_MODEL_LOAD_TIMEOUT")
                    app.quit()
                return
            samples.append(row)
            state["samples"] += 1
            if state["samples"] == args.samples:
                state["capture"] = True
                timer.stop()
                stage = profile.STAGES[state["stage"]]
                # Capture into a temporary file, then use the owned-store quota.
                temporary_image = Path(temporary) / (stage + ".png")
                capture = game_client_main.capture_window_async(window, temporary_image)
                captures.append(capture)

                def captured():
                    if not temporary_image.exists():
                        failures.append("QT_PROFILE_SCREENSHOT_FAILED")
                        app.quit()
                        return
                    output = common.artifact("scene-profile-" + name + "-" + stage.lower(), temporary_image.read_bytes())
                    screenshots[stage] = {"path": str(output), "sha256": common.digest(output.read_bytes())}
                    advance()
                capture.ready.connect(captured)

        timer.timeout.connect(tick)
        QTimer.singleShot(1500, timer.start)
        def timeout():
            failures.append("QT_PROFILE_WALL_TIMEOUT")
            app.quit()
        QTimer.singleShot(55000, timeout)
        app.exec()
    if failures:
        raise ValueError(failures[0])
    result = profile.record(args.plan, samples, screenshots)
    print(json.dumps({"status": result["status"], "packet_path": result["packet_path"], "graphics_apis": result["graphics_apis"], "stages": result["stages"]}, indent=2))


if __name__ == "__main__":
    main()
