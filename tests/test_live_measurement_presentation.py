"""Real scene-graph clock and retained bars; no RPC, node or user preferences.

The display cadence is measured, never equated with blockchain throughput.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


def fixture(directory):
    from PySide6.QtCore import QUrl
    from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression, qmlContext
    from PySide6.QtQuick import QQuickItem, QSGRendererInterface
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from shiboken6 import getCppPointer
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    engine = QQmlApplicationEngine()
    warnings = []
    engine.warnings.connect(lambda rows: warnings.extend(row.toString() for row in rows))
    native = os.environ.get('GG_TIMING_NATIVE') == '1'
    engine.rootContext().setContextProperty('nativeFixture', native)
    source = '''import QtQuick
import QtQuick.Controls
import COMPONENTS as GG
ApplicationWindow {
 id: window; width: 700; height: 180; visible: true; color: '#111111'
 x: nativeFixture ? 200 : 0; y: nativeFixture ? 200 : 0
 flags: nativeFixture ? (Qt.Tool|Qt.FramelessWindowHint|Qt.WindowDoesNotAcceptFocus|Qt.WindowStaysOnBottomHint) : Qt.Window
 property bool live: false
 property real sampleTime: Date.now()/1000
 property real measuredFraction: .25
 property int observationCount: 1
 property bool showDashboard: false
 property var fixtureState: ({})
 property int actionCount: 0
 GG.GGStreamClock { id: clock; objectName: 'clock'; active: window.live; observationTime: window.sampleTime; cadenceMs: 2000 }
 Item { id: panel; objectName: 'panel'; anchors.fill: parent; visible: !window.showDashboard
  Row { x: -clock.phase*20; y: 12; spacing: 3; height: 100
   Repeater { model: 32
    GG.GGMeasurementBar { required property int index; objectName: 'sampleBar'; width: 17; height: 100; fraction: window.measuredFraction; barColor: '#87afd7' }
   }
  }
  Rectangle { y: 135; height: 2; width: clock.phase*parent.width; color: '#87d7ff' }
 }
 GG.GGTestnetDashboard { objectName: 'dashboard'; anchors.fill: parent; visible: window.showDashboard; state: window.fixtureState; onActionRequested:window.actionCount++;onRefreshRequested:window.actionCount++ }
}'''.replace('COMPONENTS', json.dumps((ROOT/'qml/components').as_uri()))
    engine.loadData(source.encode(), QUrl.fromLocalFile(str(directory/'fixture.qml')))
    assert engine.rootObjects(), warnings
    window = engine.rootObjects()[0]
    clock = window.findChild(QQuickItem, 'clock')
    panel = window.findChild(QQuickItem, 'panel')
    assert clock and panel

    def js(owner, code):
        expression = QQmlExpression(qmlContext(owner), owner, code)
        result = expression.evaluate()
        assert not expression.hasError(), expression.error().toString()
        return result[0] if isinstance(result, tuple) else result

    def bars():
        def visit(item):
            yield item
            for child in item.childItems():
                yield from visit(child)
        return [item for item in visit(window.contentItem()) if item.objectName() == 'sampleBar']

    def named_items(name):
        def visit(item):
            yield item
            for child in item.childItems():
                yield from visit(child)
        return [item for item in visit(window.contentItem()) if item.objectName() == name]

    try:
        if native:
            window.lower()
            assert QTest.qWaitForWindowExposed(window, 3000)
            assert window.rendererInterface().graphicsApi() == QSGRendererInterface.GraphicsApi.Direct3D11
        QTest.qWait(100)
        samples = []
        clock.nowMillisChanged.connect(lambda: samples.append(time.perf_counter()))
        frames = []
        window.frameSwapped.connect(lambda: frames.append(time.perf_counter()))
        identities = [getCppPointer(bar)[0] for bar in bars()]
        assert len(identities) == 32
        window.setProperty('sampleTime', time.time())
        window.setProperty('live', True)
        QTest.qWait(700)
        assert clock.property('rendering')
        assert len(samples) >= 12, ('No native frame-paced updates', len(samples))
        assert .55 <= clock.property('ageSeconds') <= 1.5
        assert .2 < clock.property('phase') < .8
        assert [getCppPointer(bar)[0] for bar in bars()] == identities
        assert window.property('observationCount') == 1, 'Presentation must not invent observations'
        active_ticks = len(samples)
        intervals = sorted((b-a)*1000 for a,b in zip(samples,samples[1:]))

        # Actual new sample, not the clock, changes the measured fractions.
        bar = bars()[0]
        window.setProperty('measuredFraction', .9)
        QTest.qWait(50)
        assert .25 < bar.property('renderedFraction') < .9
        QTest.qWait(250)
        assert abs(bar.property('renderedFraction')-.9) < .001

        # A stopped source must become idle; hidden/minimized views pause.
        window.setProperty('live', False)
        QTest.qWait(50)
        stopped = len(samples)
        QTest.qWait(180)
        assert len(samples) == stopped
        frame_start = len(frames)
        QTest.qWait(180)
        idle_frames = len(frames)-frame_start
        assert idle_frames == 0, ('Inactive chart should not repaint', idle_frames)
        window.setProperty('live', True)
        QTest.qWait(50)
        window.setVisible(False)
        QTest.qWait(50)
        hidden = len(samples)
        assert not clock.property('rendering')
        QTest.qWait(180)
        assert len(samples) == hidden
        window.setVisible(True)
        QTest.qWait(100)
        assert clock.property('rendering')
        window.showMinimized()
        QTest.qWait(50)
        minimized=len(samples)
        assert not clock.property('rendering')
        QTest.qWait(100)
        assert len(samples)==minimized
        window.showNormal()
        if native: window.lower()
        QTest.qWait(100)
        assert clock.property('rendering')
        js(window, 'GG.GGColorContext.applicationVisible=false')
        QTest.qWait(40)
        hidden = len(samples)
        QTest.qWait(100)
        assert not clock.property('rendering') and len(samples) == hidden
        js(window, 'GG.GGColorContext.applicationVisible=true')

        # Unknown timestamps disable rather than fabricate a clock history.
        js(clock, 'observationTime=NaN')
        QTest.qWait(40)
        assert not clock.property('hasObservation') and not clock.property('rendering')
        assert clock.property('phase') == 0
        assert [getCppPointer(item)[0] for item in bars()] == identities

        # The production dashboard keeps the same 32 delegates when the actual
        # bounded history changes, preserving series coloring and hit targets.
        window.setWidth(1100);window.setHeight(700)
        observed=time.time()
        history=[{'operation':('rpc','transaction','self_test')[i%3],
                  'elapsed_ms':float(i+1),'observed_at':observed-(31-i)/60,
                  'state':'PASS'} for i in range(32)]
        data={'testnet':{'state':'RUNNING','production':False,'chain_number':31337,
                        'binding':'LOOPBACK_ONLY','measurements':history,
                        'observation_interval_ms':1000/60}}
        window.setProperty('fixtureState',data)
        window.setProperty('showDashboard',True)
        QTest.qWait(100)
        dashboard_clock=named_items('testnetStreamClock')[0]
        delegates=named_items('testnetMeasurementBar')
        dashboard_ids=[getCppPointer(item)[0] for item in delegates]
        assert len(dashboard_ids)==32 and dashboard_clock.property('rendering')
        history=history[1:]+[dict(history[-1],elapsed_ms=77.0,observed_at=time.time())]
        data['testnet']['measurements']=history
        window.setProperty('fixtureState',data)
        QTest.qWait(100)
        assert [getCppPointer(item)[0] for item in named_items('testnetMeasurementBar')]==dashboard_ids
        dashboard=named_items('dashboard')[0]
        assert js(dashboard,'measurements.length')==32
        assert js(dashboard,'measurements[31].elapsed_ms')==77
        assert window.property('actionCount')==0, 'Presentation must not request RPCs or node actions'
        dashboard.setVisible(False)
        QTest.qWait(40)
        assert not dashboard_clock.property('rendering')
        assert not warnings, warnings
        report = {'status':'PASS','native_direct3d11':native,'actual_observations':1,
                  'retained_bars':32,'active_clock_ticks_in_700ms':active_ticks,
                  'median_clock_interval_ms':round(intervals[len(intervals)//2],3),
                  'inactive_frames_in_180ms':idle_frames,'hidden_clock_ticks':0,'minimized_clock_ticks':0,
                  'dashboard_retained_delegates':32,'dashboard_actions':0,
                  'writes_network_or_block_production':False,'warnings':len(warnings)}
        evidence = os.environ.get('GG_TIMING_EVIDENCE')
        if evidence:
            target = Path(evidence)
            target.mkdir(parents=True,exist_ok=True)
            (target/('direct3d.json' if native else 'software.json')).write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report))
    finally:
        window.close()
        engine.deleteLater()
        app.processEvents()


class LiveMeasurementPresentationTests(unittest.TestCase):
    def check_fixture(self,native=False):
        with tempfile.TemporaryDirectory(prefix='gg-live-measurement-fixture-') as directory:
            env=os.environ.copy()
            env.update(QT_QUICK_CONTROLS_STYLE='Basic',GG_DESKTOP_STATE_ROOT=str(Path(directory)/'state'),GG_DESKTOP_DATA_ROOT=str(Path(directory)/'data'))
            if native:
                env.pop('QT_QUICK_BACKEND',None)
                env.update(QT_QPA_PLATFORM='windows',QSG_RHI_BACKEND='d3d11',GG_TIMING_NATIVE='1')
            else:
                env.update(QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software')
                env.pop('GG_TIMING_NATIVE',None)
            result=subprocess.run([sys.executable,'-X','utf8','-B',str(Path(__file__).resolve()),'--fixture',directory],cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            print(result.stdout.strip())

    def test_actual_clock_and_retained_bars_software(self): self.check_fixture()

    @unittest.skipUnless(os.name=='nt','Native Direct3D11 on Windows')
    def test_actual_clock_and_retained_bars_direct3d(self): self.check_fixture(True)


if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--fixture': fixture(Path(sys.argv[2]))
    else: unittest.main()
