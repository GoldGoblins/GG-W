"""Exercise the real eyes JavaScript and telemetry bindings without a window."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

PROJECT = Path(__file__).resolve().parents[1]


class LiveEyesStatusUiTests(unittest.TestCase):
    def run_probe(self, kind):
        environment = dict(os.environ, QT_QPA_PLATFORM="offscreen",
            QT_QUICK_BACKEND="software", QT_QUICK_CONTROLS_STYLE="Basic",
            PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
        options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        result = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()),
            "--probe", kind], cwd=PROJECT, env=environment, capture_output=True,
            text=True, encoding="utf-8", timeout=20, **options)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("LIVE_EYES_" + kind.upper() + "_PASS", result.stdout)

    def test_helper_states_and_frame_freshness_in_real_qml_engine(self):
        self.run_probe("helper")

    def test_telemetry_uses_actual_status_bindings_for_gptui(self):
        self.run_probe("telemetry")

    def test_main_header_uses_the_behavior_tested_shared_helper(self):
        source = (PROJECT / "qml/Main.qml").read_text(encoding="utf-8")
        self.assertIn('import "components/LiveEyesStatus.js" as EyesStatus', source)
        start = source.index('objectName: "liveEyesIndicator"')
        header = source[start:source.index("MouseArea {", start)]
        self.assertIn('visible: root.liveEyes.state !== "off"', header)
        self.assertIn("EyesStatus.title(root.liveEyes)", header)
        self.assertIn("EyesStatus.fresh(root.liveEyes)", header)
        self.assertIn("EyesStatus.tooltip(root.liveEyes)", header)


def probe(kind):
    from PySide6.QtCore import QObject, QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlComponent, QQmlEngine

    app = QGuiApplication([])
    engine = QQmlEngine()
    warnings = []
    engine.warnings.connect(lambda rows: warnings.extend(row.toString() for row in rows))
    component = QQmlComponent(engine)

    def require(condition, detail):
        if not condition:
            raise AssertionError(detail)

    def create():
        require(component.status() == QQmlComponent.Ready,
                "\n".join(error.toString() for error in component.errors()))
        item = component.create()
        require(item is not None, "QML object was not created")
        app.processEvents()
        return item

    if kind == "helper":
        component.setData(b'''import QtQml
import "LiveEyesStatus.js" as EyesStatus
QtObject {
    property string sampleJson: "{}"
    readonly property var sample: JSON.parse(sampleJson)
    readonly property string caption: EyesStatus.title(sample)
    readonly property string details: EyesStatus.details(sample)
    readonly property string hint: EyesStatus.tooltip(sample)
    readonly property bool fresh: EyesStatus.fresh(sample)
}''', QUrl.fromLocalFile(str(PROJECT / "qml/components/eyes-status-fixture.qml")))
        fixture = create()

        def apply(value):
            require(fixture.setProperty("sampleJson", json.dumps(value)), "Sample binding missing")
            app.processEvents()
            return {key: fixture.property(key) for key in ("caption", "details", "hint", "fresh")}

        state = apply({"state": "off"})
        require(not state["fresh"], state)
        for value in [
            {"state": "capturing", "frame_count": 0, "frame_age_ms": None, "received_fps": 0},
            {"state": "capturing", "frame_count": 0},
        ]:
            state = apply(value)
            require("FÅNGAR" in state["caption"] and not state["fresh"], state)
            require(" fps" not in state["details"] and "0 bilder" not in state["details"], state)
        state = apply({"state": "capturing", "frame_count": 5,
                       "frame_age_ms": 40, "received_fps": 25})
        require(state["fresh"] and "5 bilder · 25 fps" in state["details"], state)
        state = apply({"state":"capturing","observation_kind":"video","frame_count":2,
                       "frame_age_ms":20,"received_fps":0,"reason":"Avkodar videobilder."})
        require(state["caption"] == "ÖGON · VIDEO" and state["fresh"],state)
        require("Avkodar videobilder." in state["details"] and " fps" not in state["details"],state)
        state = apply({"state": "observed", "last_observation_frames": 50,
                       "last_observation_fps": 25, "last_delivered_age_ms": 1000,
                       "frame_age_ms": None, "received_fps": 0})
        require("NYSS" in state["caption"] and not state["fresh"], state)
        require("50 bilder hämtade · 1 s sedan" in state["details"], state)
        require("Ingen kontinuerlig fångst" in state["details"], state)
        require("25 fps" not in state["details"] and "rensa indikatorn" in state["hint"], state)
        state = apply({"state": "error", "reason": "Observationen misslyckades."})
        require("FEL" in state["caption"] and not state["fresh"], state)
        require("Observationen misslyckades." in state["details"], state)
        state = apply({"state": "stopping"})
        require("STOPPAR" in state["caption"] and not state["fresh"], state)
        live = {"state": "live", "received_fps": 25, "frame_age_ms": 20,
                "last_delivered_age_ms": 1000, "buffer_bytes": 8 * 1024**2}
        state = apply(live)
        require(state["caption"] == "ÖGON · 25 fps" and state["fresh"], state)
        require("Bild hämtad 1 s sedan" in state["details"] and "RAM 8.0 MiB" in state["details"], state)
        state = apply({**live, "last_delivered_age_ms": None})
        require("Ingen bild hämtad av AI ännu" in state["details"], state)
        for capture_state in ("live", "capturing"):
            for age in (None, -1, "0", True, 2001):
                state = apply({**live, "state": capture_state, "frame_age_ms": age})
                require(not state["fresh"], (capture_state, age, state))
            require(apply({**live, "state": capture_state, "frame_age_ms": 2000})["fresh"],
                    "Exact two-second boundary should remain fresh")
    elif kind == "telemetry":
        component.loadUrl(QUrl.fromLocalFile(str(PROJECT / "qml/components/TelemetryRail.qml")))
        fixture = create()
        fixture.setProperty("engineTarget", "GPT_TUI")
        fixture.setProperty("width", 220)
        fixture.setProperty("height", 900)
        indicator = fixture.findChild(QObject, "liveEyesTelemetry")
        require(indicator is not None, "Actual telemetry eyes label missing")

        def apply(value):
            require(fixture.setProperty("liveVisionStatusJson", json.dumps(value)), "Status binding missing")
            app.processEvents()
            return {"visible": indicator.property("visible"), "text": indicator.property("text"),
                    "color": indicator.property("color").name()}

        state = apply({"state": "off"})
        require(not state["visible"], state)
        state = apply({"state": "capturing", "frame_age_ms": None, "frame_count": 0})
        require(state["visible"] and "FÅNGAR" in state["text"], state)
        require(state["color"] == "#e4c06a", state)
        state = apply({"state": "capturing", "frame_age_ms": 50,
                       "frame_count": 3, "received_fps": 25})
        require(state["visible"] and "3 bilder · 25 fps" in state["text"], state)
        require(state["color"] == "#9ed5a4", state)
        state = apply({"state":"capturing","observation_kind":"video","frame_count":2,
                       "frame_age_ms":20,"received_fps":0,"reason":"Avkodar videobilder."})
        require(state["visible"] and "VIDEO" in state["text"] and " fps" not in state["text"],state)
        state = apply({"state": "observed", "last_observation_frames": 50,
                       "last_delivered_age_ms": 1000, "last_observation_fps": 25})
        require(state["visible"] and "NYSS" in state["text"], state)
        require("Ingen kontinuerlig fångst" in state["text"] and "25 fps" not in state["text"], state)
        require(state["color"] == "#e4c06a", state)
        state = apply({"state": "error", "reason": "Observationen misslyckades."})
        require(state["visible"] and "FEL" in state["text"], state)
        state = apply({"state": "stopping"})
        require(state["visible"] and "STOPPAR" in state["text"], state)
        live = {"state": "live", "received_fps": 25, "frame_age_ms": 10,
                "last_delivered_age_ms": 1000, "buffer_bytes": 8 * 1024**2}
        state = apply(live)
        require(state["visible"] and "25 fps" in state["text"], state)
        require("Bild hämtad 1 s sedan" in state["text"] and "RAM 8.0 MiB" in state["text"], state)
        require(state["color"] == "#9ed5a4", state)
        state = apply({**live, "frame_age_ms": None})
        require(state["color"] == "#e4c06a", "Null age falsely displayed as fresh: " + str(state))
        state = apply({"state": "off"})
        require(not state["visible"], "Finished telemetry did not hide: " + str(state))
    else:
        raise AssertionError("Unknown UI probe")

    require(not warnings, "QML warnings:\n" + "\n".join(warnings))
    fixture.deleteLater()
    app.processEvents()
    print("LIVE_EYES_" + kind.upper() + "_PASS")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--probe":
        probe(sys.argv[2])
    else:
        unittest.main()
