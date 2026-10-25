"""Offline real-QML refresh/binding regressions and chart content semantics."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]


class CryptoUiRefreshTests(unittest.TestCase):
    def test_real_qml_shared_wallet_polling_retry_and_chart_budget(self):
        with tempfile.TemporaryDirectory(prefix='gg-crypto-refresh-ui-') as temporary:
            env = os.environ.copy()
            env.update(QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software',
                       QT_QUICK_CONTROLS_STYLE='Basic',
                       QTWEBENGINE_CHROMIUM_FLAGS='--disable-gpu --disable-background-networking',
                       GG_DESKTOP_STATE_ROOT=str(Path(temporary) / 'state'),
                       GG_DESKTOP_DATA_ROOT=str(Path(temporary) / 'data'))
            if os.name == 'nt' and os.environ.get('GG_TEST_CRYPTO_NATIVE_FRAMES') == '1':
                env.pop('QT_QUICK_BACKEND', None)
                env.update(QT_QPA_PLATFORM='windows', QSG_RHI_BACKEND='d3d11', QSG_RENDER_LOOP='threaded')
            script = r"""
import ctypes, json, math, os, statistics, time
from pathlib import Path
from PySide6.QtCore import QObject, QMetaObject, QPointF, QTimer, QUrl, Qt, Signal, Slot
from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression, qmlContext
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from PySide6.QtWebEngineQuick import QtWebEngineQuick
QtWebEngineQuick.initialize()
native = os.name == 'nt' and os.environ.get('GG_TEST_CRYPTO_NATIVE_FRAMES') == '1'
foreground_before = ctypes.windll.user32.GetForegroundWindow() if native else None
app = QGuiApplication([])
app.setQuitOnLastWindowClosed(False)
if os.name == 'nt':
    for name in ('consola.ttf', 'consolab.ttf'):
        QFontDatabase.addApplicationFont(str(Path(os.environ.get('SystemRoot', 'C:/Windows'))/'Fonts'/name))
    QFont.insertSubstitution('monospace', 'Consolas')
    app.setFont(QFont('Consolas'))
def variant(value):
    return value.toVariant() if hasattr(value, 'toVariant') else value
def fixture(key='fixture-public-address-00000001'):
    return {'legend':'LOCALNET','wallet':{'pubkey':key,'balance_sol':'2','label':'WALLET · '+key},
        'holdings':[], 'accounts':[], 'lab':{'label':'LAB OFF'}, 'portfolio':{'asset':'SOL'},
        'chart':{'closes':[100,101,102], 'times':[1700000000,1700000060,1700000120],
                 'stale':False,'source':'offline-fixture','interval':'1m'}, 'ui_operation':{}}
class Host(QObject):
    cryptoStatusUpdated = Signal(str)
    def __init__(self):
        super().__init__(); self.payload=fixture(); self.calls=0; self.chart_calls=0
    @Slot(result=str)
    def cryptoStatus(self):
        self.calls += 1
        return json.dumps(self.payload)
    @Slot(result=str)
    def cryptoRefreshChart(self):
        self.chart_calls += 1
        return json.dumps(self.payload)
    @Slot(result=str)
    def cryptoRefreshKasChart(self):
        return json.dumps(self.payload)
host = Host()
engine = QQmlApplicationEngine()
warnings=[]
engine.warnings.connect(lambda rows: warnings.extend(row.toString() for row in rows))
engine.rootContext().setContextProperty('fixtureHost',host)
engine.rootContext().setContextProperty('initialSnapshot',json.dumps(host.payload))
qml = '''import QtQuick
import QtQuick.Window
import "''' + (Path('qml/components').resolve().as_uri()) + '''"
Window {
    id: shell; width:1100; height:760; visible:true
    flags: Qt.Window | Qt.WindowDoesNotAcceptFocus | Qt.WindowStaysOnBottomHint
    property bool benchmarkActive:false
    property real animationPhase:0
    property string sharedStatus: initialSnapshot
    readonly property var sharedSnapshot: JSON.parse(sharedStatus)
    Connections { target:fixtureHost; function onCryptoStatusUpdated(raw) { shell.sharedStatus=raw } }
    CryptoSurface { objectName:"fixturePane"; anchors.fill:parent; surfaceHost:fixtureHost }
    WalletPopup {
        objectName:"fixtureWallet"; x:760; y:40; visible:false
        surfaceHost:fixtureHost; externallyManagedStatus:true
        statusJson:shell.sharedStatus; statusSnapshot:shell.sharedSnapshot
        onWalletStatusUpdated: function(raw) { shell.sharedStatus=raw }
    }
    TelemetryRail { objectName:"fixtureRail"; width:168; height:720; visible:false
        cryptoStatusJson:shell.sharedStatus; cryptoSnapshot:shell.sharedSnapshot }
    Rectangle { width:8; height:3; y:0; x:shell.animationPhase*(shell.width-8); color:"#c8a97e" }
    NumberAnimation on animationPhase { from:0; to:1; duration:1200; loops:Animation.Infinite; running:shell.benchmarkActive }
}'''
engine.loadData(qml.encode(), QUrl('file:///gg-crypto-refresh-fixture.qml'))
assert engine.rootObjects(), warnings
window=engine.rootObjects()[0]
pane=window.findChild(QQuickItem,'fixturePane')
popup=window.findChild(QQuickItem,'fixtureWallet')
rail=window.findChild(QQuickItem,'fixtureRail')
QTest.qWait(80)
popup.setVisible(True)
QMetaObject.invokeMethod(popup,'pull')
host.payload=fixture('fixture-public-address-00000002')
QMetaObject.invokeMethod(popup,'pull')
external=fixture('fixture-public-address-00000003')
window.setProperty('sharedStatus',json.dumps(external))
assert popup.property('pubkey') == external['wallet']['pubkey'], 'Popup detached its shared status binding'
host.payload=fixture('fixture-public-address-00000004')
host.cryptoStatusUpdated.emit(json.dumps(host.payload))
app.processEvents()
assert popup.property('pubkey') == host.payload['wallet']['pubkey']
assert variant(pane.property('wallet'))['pubkey'] == host.payload['wallet']['pubkey']
assert variant(rail.property('crypto'))['wallet']['pubkey'] == host.payload['wallet']['pubkey']
popup.setVisible(False)
host.payload.update(backtest_job={'state':'running'}, strategy_factory_job={'state':'running'},
                    desk_job={'state':'running'},paper_jobs={'trader':{'state':'running'}})
host.cryptoStatusUpdated.emit(json.dumps(host.payload))
app.processEvents()
start=host.calls
QTest.qWait(2200)
polled=host.calls-start
assert 1 <= polled <= 3, ('Overlapping jobs duplicated status polls', polled)
pane.setVisible(False)
start=host.calls
QTest.qWait(1150)
assert host.calls==start, 'Hidden CRYPTO pane kept polling'
host.payload=fixture()
host.payload['chart']={'closes':[], 'times':[], 'error':'OFFLINE_FIXTURE', 'stale':True}
pane.setProperty('statusJson',json.dumps(host.payload))
pane.setVisible(True)
QTest.qWait(50)
start=host.chart_calls
pane.setProperty('lastSolChartRequest',0)
QMetaObject.invokeMethod(pane,'refresh')
QTest.qWait(30)
assert host.chart_calls>start, 'Identical missing snapshot suppressed retry'
retry=pane.findChild(QQuickItem,'cryptoChartRetryArea')
assert retry is not None and retry.isVisible()
point=retry.mapToScene(QPointF(retry.width()/2,retry.height()/2)).toPoint()
start=host.chart_calls
QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,point)
QTest.qWait(30)
assert host.chart_calls==start+1, 'Retry control did not reach its host'
n=20000
host.payload=fixture()
values=[100+math.sin(i/9) for i in range(n)]
values[7013]=1000; values[13021]=1
host.payload['chart'].update(closes=values,times=[1700000000+i*60 for i in range(n)])
host.cryptoStatusUpdated.emit(json.dumps(host.payload))
QTest.qWait(60)
canvas=pane.findChild(QQuickItem,'cryptoPortfolioCanvas')
assert canvas is not None
canvas.setProperty('viewReady',True)
canvas.setProperty('viewFrom',0)
canvas.setProperty('viewTo',n-1)
app.processEvents()
indices=variant(canvas.property('renderIndices'))
columns=max(1,int(canvas.width()-76))
assert len(indices)<=2*columns+2, (len(indices), columns)
assert 7013 in indices and 13021 in indices, 'Pixel admission lost a real extremum'
assert len(variant(canvas.property('series')))==n, 'Downsampling modified source/hover data'
strategy=QQmlExpression(qmlContext(canvas),canvas,'renderStrategy === Canvas.Threaded').evaluate()
assert (strategy[0] if isinstance(strategy,tuple) else strategy), 'Canvas is not using private threaded rasterization'
expression=QQmlExpression(qmlContext(canvas),canvas,
    '(function(){var began=Date.now(); for(var i=0;i<10000;i++) indexAt(i%width); return Date.now()-began;})()')
metric=expression.evaluate()
assert not expression.hasError(), expression.error().toString()
print(json.dumps({'status':'PASS','coalesced_polls_2_2s':polled,'source_samples':n,
                  'paint_samples':len(indices),'hover_10000_ms':variant(metric[0] if isinstance(metric,tuple) else metric)}))
if native:
    frames=[]; interactions=[]; pulses=[0]
    exposures=[]
    def swapped(): frames.append(time.perf_counter())
    # Python callbacks stay on the GUI lane; a direct render-thread callback
    # can wait for the GIL while Qt synchronizes that same GUI thread.
    window.frameSwapped.connect(swapped,Qt.QueuedConnection)
    def pulse():
        began=time.perf_counter()
        pulses[0]+=1
        exposures.append(window.isExposed())
        canvas.setProperty('hoverIndex',(pulses[0]*37)%n)
        if pulses[0]%12==0:
            QQmlExpression(qmlContext(canvas),canvas,'panBy(3)').evaluate()
        if pulses[0]%45==0:
            QQmlExpression(qmlContext(canvas),canvas,'zoomAt(width*.5,true)').evaluate()
            window.resize(1000 if window.width()==1100 else 1100,
                          720 if window.height()==760 else 760)
        interactions.append((time.perf_counter()-began)*1000)
    timer=QTimer();timer.setTimerType(Qt.PreciseTimer);timer.setInterval(16);timer.timeout.connect(pulse)
    window.setProperty('benchmarkActive',True);timer.start()
    QTimer.singleShot(5200,app.quit)
    app.exec()
    timer.stop();window.setProperty('benchmarkActive',False)
    window.frameSwapped.disconnect(swapped)
    gaps=sorted((b-a)*1000 for a,b in zip(frames,frames[1:]))
    def percentile(rows,p): return rows[min(len(rows)-1,math.floor((len(rows)-1)*p))] if rows else None
    ordered=sorted(interactions)
    assert len(frames)>90, 'Native fixture did not produce enough rendered frames'
    assert ctypes.windll.user32.GetForegroundWindow()==foreground_before, 'Native benchmark changed user foreground'
    print(json.dumps({'native_render':'PASS','platform':QGuiApplication.platformName(),
        'graphics_api':window.rendererInterface().graphicsApi().name,'exposed_during_measurement':any(exposures),
        'screen_refresh_hz':window.screen().refreshRate(),
        'frames':len(frames),'duration_seconds':round(frames[-1]-frames[0],3),
        'observed_hz':round((len(frames)-1)/(frames[-1]-frames[0]),2),
        'frame_gap_p95_ms':round(percentile(gaps,.95),3),'frame_gap_p99_ms':round(percentile(gaps,.99),3),
        'frame_gap_max_ms':round(max(gaps),3),'interaction_p95_ms':round(percentile(ordered,.95),3),
        'interaction_max_ms':round(max(interactions),3),'foreground_preserved':True}))
assert not warnings, warnings
window.close()
"""
            result = subprocess.run([sys.executable, '-B', '-c', script], cwd=PROJECT,
                                    env=env, capture_output=True, text=True, timeout=45)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            print(result.stdout.strip())

    def test_optional_web_chart_detects_corrections_and_preserves_zoom(self):
        import re
        from PySide6.QtCore import QCoreApplication
        from PySide6.QtQml import QJSEngine
        app = QCoreApplication.instance() or QCoreApplication([])
        engine = QJSEngine()
        html = (PROJECT / 'qml/crypto-hole/index.html').read_text(encoding='utf-8')
        script = re.findall(r'<script>([\s\S]+?)</script>', html)[0]
        stub = r'''
var window=this;
var host={clientWidth:800,clientHeight:300};
var document={getElementById:function(){return host;}};
var stats={sets:0,updates:0,markers:0,equitySets:0,fits:0};
var plot={applyOptions:function(){},setData:function(rows){stats.sets++;},
    update:function(row){stats.updates++;},setMarkers:function(rows){stats.markers++;}};
var eqPlot={setData:function(rows){stats.equitySets++;},update:function(){}};
var scale={fitContent:function(){stats.fits++;}};
var LightweightCharts={CrosshairMode:{Magnet:1},createChart:function(){return {
    addAreaSeries:function(){return plot;},addLineSeries:function(){return eqPlot;},
    resize:function(){},timeScale:function(){return scale;},
    priceScale:function(){return {applyOptions:function(){}};}};}};
'''
        result = engine.evaluate(stub + script)
        self.assertFalse(result.isError(), result.toString())
        assertions = r'''
function check(value, message){if(!value)throw new Error(message);}
var data={points:[{time:1700000000,value:100},{time:1700000060,value:101},{time:1700000120,value:102}],
    equity:[{time:1700000000,value:200},{time:1700000060,value:201},{time:1700000120,value:202}],
    markers:[{time:1700000060,color:'red'}]};
setTape(data);
check(stats.sets===1 && stats.equitySets===1 && stats.fits===1,'Initial chart');
data.points[1].value=500; setTape(data);
check(stats.sets===2,'Historical correction ignored');
var markerCount=stats.markers;
data.markers[0].color='green'; setTape(data);
check(stats.markers===markerCount+1,'Changed marker ignored');
data.points.push({time:1700000180,value:103}); setTape(data);
check(stats.sets===2 && stats.updates>0,'Append replaced entire series');
data.equity[1].value=700; setTape(data);
check(stats.equitySets===2,'Historical equity correction ignored');
host.clientWidth=900; fitTape();
check(stats.fits===1,'Resize discarded user zoom');
check(uniqPoints([{time:Infinity,value:1},{time:1700000000,value:Infinity}]).length===0,'Nonfinite chart data');
'''
        result = engine.evaluate(assertions)
        self.assertFalse(result.isError(), result.toString())


if __name__ == '__main__':
    unittest.main(argv=[__file__])
