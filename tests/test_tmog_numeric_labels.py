"""Verify TMOG labels and their card layout in an isolated, windowless QML engine."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TmogNumericLabelIntegrationTests(unittest.TestCase):
    def test_real_qml_labels_layout_and_approved_cpu_spring(self):
        env = os.environ.copy()
        # Windows' offscreen QPA supplies dummy10px glyph metrics even for a
        # requested10px font. Use its native font database without creating a
        # window, so legend fit is checked with the installed UI fonts.
        env.update(QT_QPA_PLATFORM="windows" if os.name == "nt" else "offscreen", QT_QUICK_BACKEND="software",
                   QT_QUICK_CONTROLS_STYLE="Basic", QML_DISABLE_DISK_CACHE="1")
        result = subprocess.run([sys.executable, "-B", "-c", SCRIPT], cwd=ROOT,
                                env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        records = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
        self.assertEqual(len(records), 1, result.stdout + result.stderr)
        self.assertEqual(records[0]["labels"], "PASS")
        self.assertEqual(records[0]["unavailable"], "PASS")
        self.assertEqual(records[0]["compact_legends"], "PASS")
        self.assertEqual(records[0]["graph_body_unchanged"], "PASS")
        self.assertEqual(records[0]["existing_cpu_spring"], "PASS")


SCRIPT = r'''
import json
from pathlib import Path
from PySide6.QtCore import QObject, QPointF, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickItem

app = QGuiApplication([])
engine = QQmlEngine()
path = Path("qml/components/TmogSurface.qml").resolve()
component = QQmlComponent(engine, QUrl.fromLocalFile(str(path)))
assert component.isReady(), [error.toString() for error in component.errors()]
meter = component.create()
assert meter is not None, [error.toString() for error in component.errors()]
meter.setProperty("visible", False)
meter.setProperty("width", 1200)
meter.setProperty("height", 800)
engine.globalObject().setProperty("meter", engine.newQObject(meter))

def js(expression):
    result = engine.evaluate(expression)
    assert not result.isError(), result.toString()
    return result.toVariant()

def visual_tree(item):
    for child in item.childItems():
        yield child
        yield from visual_tree(child)

def legend(left):
    cards = [child for child in visual_tree(meter)
             if child.property("leftLegend") == left]
    assert cards, ("Missing actual card", left)
    return cards[-1].property("rightLegend")

snapshot = {"cpu_busy": 10, "mhz": 1000,
            "cores": [{"id": 0, "pct": 100, "mhz":3000.345}, {"id": 1, "pct": 100, "mhz":3000.345}],
            "mem_cached_kb": None,
            "energy": {"watts": 30, "source": "AC"}}
meter.setProperty("statusJson", json.dumps(snapshot))
meter.setProperty("page", "PERFORMANCE")
meter.setProperty("liveTicks", 1)
result = js("""(function() {
    var pulse = {cpu_busy:80,cores:[45.5,0],mhz:3200.499,
        gpu_busy:null,temp_c:null,energy_w:0,energy_source:"BATTERY",
        mem_used_kb:1024,mem_total_kb:2048};
    meter.applyPulse(pulse, 1/60);
    return {cpu:meter.metricText("cpu_busy",1,"%"),
        core0:meter.coreText(0),core1:meter.coreText(1),
        mhz:meter.metricText("mhz",0," MHz"),
        gpu:meter.metricText("gpu_busy",1,"%"),
        temp:meter.metricText("temp_c",1," C"),
        cached:meter.metricKib("mem_cached_kb"),
        watts:meter.metricText("energy_w",1," W"),
        source:meter.energySource(),visualCpu:meter.liveCpu};
})()""")
assert result["cpu"] == "80.0%", result
assert result["core0"] == "45.5%" and result["core1"] == "0.0%", result
assert result["mhz"] == "3200 MHz", result
assert result["gpu"] == "--" and result["temp"] == "--", result
assert result["cached"] == "--", result
assert result["watts"] == "0.0 W" and result["source"] == "BATTERY", result
assert 0 < result["visualCpu"] < 10, result
app.processEvents()
assert legend("CPU 0") == "45.5%", legend("CPU 0")
assert legend("CPU 1") == "0.0%", legend("CPU 1")
assert legend("CPU") == "80.0%", legend("CPU")
meter.setProperty("perfKey", "ENERGY")
app.processEvents()
assert legend("ENERGY") == "0.0 W", legend("ENERGY")

meter.setProperty("page", "FREQ")
app.processEvents()
assert any(child.property("text") == "CPU 0   3000 MHz   45.5%" for child in visual_tree(meter))
js('meter.applyPulse({cpu_busy:80,cores:[45.5,0],mhz:3200.499,sample_errors:{frequency:"OSError"}},1/60)')
app.processEvents()
assert js('meter.metricText("mhz",0," MHz")') == "--"
assert any(child.property("text") == "CPU 0   --   45.5%" for child in visual_tree(meter)), "Core row leaked stale frequency"
meter.setProperty("page", "PERFORMANCE")
app.processEvents()

unavailable = js("""(function() {
    var cases = [
        {cpu_busy:80,cores:[45.5,0],error:"OSError"},
        {cpu_busy:80,cores:[45.5,0],cpu_sample_age_ms:1001},
        {cpu_busy:80,cores:[45.5,0],sample_errors:{cpu:"OSError"}}
    ];
    var results = [];
    for (var i=0; i<cases.length; ++i) {
        meter.applyPulse(cases[i], 1/60);
        results.push([meter.metricText("cpu_busy",1,"%"),meter.coreText(0)]);
    }
    return results;
})()""")
assert unavailable == [["--", "--"]] * 3, unavailable
app.processEvents()
assert legend("CPU 0") == "--", legend("CPU 0")
meter.setProperty("perfKey", "CPU")
app.processEvents()
assert legend("CPU") == "--", legend("CPU")

spring = js("""(function() {
    meter.liveCpu = 7;
    meter.cpuVelocity = 2;
    var expected = meter.springFollow(7,2,80,1/60);
    meter.applyPulse({cpu_busy:80,cores:[100]},1/60);
    var cpu = [meter.liveCpu,meter.cpuVelocity];
    meter.liveCoreHists = [];
    meter.coreVelocities = [];
    meter.applyPulse({cpu_busy:80,cores:[100]},1/60);
    var first = meter.liveCoreHists[0][0];
    var expectedCore = meter.springFollow(first,meter.coreVelocities[0],0,1/60);
    meter.applyPulse({cpu_busy:80,cores:[0]},1/60);
    var history = meter.liveCoreHists[0];
    return {expected:expected,cpu:cpu,first:first,expectedCore:expectedCore,
        core:[history[history.length-1],meter.coreVelocities[0]],length:history.length};
})()""")
assert all(abs(a-b) < 1e-10 for a,b in zip(spring["expected"],spring["cpu"])), spring
assert spring["first"] == 100 and spring["length"] == 2, spring
assert all(abs(a-b) < 1e-10 for a,b in zip(spring["expectedCore"],spring["core"])), spring
assert 0 < spring["core"][0] < 100, spring

card_source = b"""
import QtQuick
Item {
    width: 220; height: 120
    TmogCard {
        objectName: "compact"; width: 92; height: 56
        compactLegend: true; leftLegend: "CPU 15"; rightLegend: "100.0%"
        Rectangle { objectName: "compactBody"; anchors.fill: parent }
    }
    TmogCard {
        objectName: "normal"; x: 110; width: 92; height: 56
        leftLegend: "CPU 15"; rightLegend: "100.0%"
        Rectangle { objectName: "normalBody"; anchors.fill: parent }
    }
}
"""
cards_component = QQmlComponent(engine)
cards_component.setData(card_source, QUrl.fromLocalFile(str(path.parent / "TmogCardLabelTest.qml")))
assert cards_component.isReady(), [error.toString() for error in cards_component.errors()]
cards = cards_component.create()
assert cards is not None, [error.toString() for error in cards_component.errors()]
app.processEvents()
compact = cards.findChild(QObject,"compact")
normal = cards.findChild(QObject,"normal")
def text_item(card, text):
    found = [child for child in card.findChildren(QObject) if child.property("text") == text]
    assert len(found) == 1, (text,len(found))
    return found[0]
left = text_item(compact,"CPU 15")
right = text_item(compact,"100.0%")
left_at = left.mapToItem(compact,QPointF(0,0))
right_at = right.mapToItem(compact,QPointF(0,0))
assert left_at.x() + left.width() <= right_at.x(), (
    "Compact CPU card text overlaps",left_at.x(),left.width(),right_at.x(),right.width())
assert left_at.x() >= 0 and right_at.x() + right.width() <= compact.width(), "Legend exceeds card"
assert left.property("font").pixelSize() == 10 and right.property("font").pixelSize() == 10
assert text_item(normal,"CPU 15").property("font").pixelSize() == 12
assert text_item(normal,"100.0%").property("font").pixelSize() == 12
compact_body = cards.findChild(QObject,"compactBody")
normal_body = cards.findChild(QObject,"normalBody")
def body_geometry(body):
    return [body.parentItem().x(),body.parentItem().y(),body.width(),body.height()]
assert body_geometry(compact_body) == body_geometry(normal_body) == [10,16,72,32], (
    body_geometry(compact_body),body_geometry(normal_body))
print(json.dumps({"labels":"PASS","unavailable":"PASS","compact_legends":"PASS",
    "graph_body_unchanged":"PASS","existing_cpu_spring":"PASS"}))
cards.deleteLater()
meter.deleteLater()
app.processEvents()
'''


if __name__ == "__main__":
    unittest.main()
