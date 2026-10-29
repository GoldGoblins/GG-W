"""Ongoing point density and real-parent geometry in an owned public fixture.

The fixture header identifiers are deterministic test data, not network block
production. Actual RPC provenance is checked by test_network_live_provenance.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def fixture(directory):
    from PySide6.QtCore import QEventLoop, QTimer, QUrl, Qt, QPointF
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression, qmlContext
    from PySide6.QtQuick import QQuickItem, QSGRendererInterface
    from backend.gg_block_graph import BlockHistory, LIVE_HISTORY_LIMIT
    app = QGuiApplication([])
    app.setQuitOnLastWindowClosed(False)
    engine = QQmlApplicationEngine()
    warnings = []
    engine.warnings.connect(lambda rows: warnings.extend(row.toString() for row in rows))
    engine.loadData(('''import QtQuick
import QtQuick.Controls
import COMPONENTS
ApplicationWindow {
 id: shell; width: 700; height: 190; visible: true; x: 320; y: 240; color: '#111111'
 flags: Qt.Tool|Qt.FramelessWindowHint|Qt.WindowDoesNotAcceptFocus|Qt.WindowStaysOnTopHint
 property string packet: ''
 onPacketChanged: if(packet)graph.graph=JSON.parse(packet)
 BlockRelationsGraph {id: graph; objectName:'densityGraph'; x:10;y:10;width:680;height:170}
}'''.replace('COMPONENTS', json.dumps((ROOT/'qml/components').as_uri()))).encode(),
                    QUrl.fromLocalFile(str(directory/'density.qml')))
    assert engine.rootObjects(), warnings
    window = engine.rootObjects()[0]
    graph = window.findChild(QQuickItem, 'densityGraph')
    assert graph is not None
    native = os.environ.get('GG_DENSITY_NATIVE') == '1'
    if native:
        assert window.rendererInterface().graphicsApi() == QSGRendererInterface.GraphicsApi.Direct3D11

    def js(code):
        expression = QQmlExpression(qmlContext(graph), graph, code)
        result = expression.evaluate()
        assert not expression.hasError(), expression.error().toString()
        return result[0] if isinstance(result, tuple) else result

    def descendants(item):
        for child in item.childItems():
            yield child
            yield from descendants(child)

    def identifier(height):
        return hashlib.sha256(('owned-density-fixture-'+str(height)).encode()).hexdigest()

    history = BlockHistory('Owned public fixture', history_limit=LIVE_HISTORY_LIMIT)
    history.reset('owned-density-fixture')
    supplied = {}
    tip = [0]
    for height in range(128):
        row = {'height':height, 'hash':identifier(height), 'parent_hash':identifier(height-1) if height else '',
               'timestamp':1700000000+height//75, 'transaction_count':height%4}
        supplied[row['hash']] = row
        history.ingest([row], height, row['hash'])
    tip[0] = 127
    started = time.monotonic()
    # Monotonic elapsed fixture admissions provide the actual per-update
    # source rate independently of the presentation clock.
    snapshots = []
    failure = []
    render_samples = []
    timer = QTimer()
    timer.setTimerType(Qt.PreciseTimer)
    timer.setInterval(13)
    loop = QEventLoop()

    def publish():
        try:
            # Coalesced GUI packets may contain several independently known
            # source headers, just like the actual observer. A slow screen
            # callback must not redefine the independent source clock.
            wanted = 128+int((time.monotonic()-started)*75)
            admitted=[]
            for height in range(tip[0]+1,min(wanted,tip[0]+8)+1):
                row = {'height':height, 'hash':identifier(height), 'parent_hash':identifier(height-1),
                       'timestamp':1700000000+height//75, 'transaction_count':height%4}
                supplied[row['hash']] = row
                admitted.append(row);snapshots.append(height)
            if not admitted:return
            tip[0]=admitted[-1]['height']
            history.ingest(admitted,tip[0],admitted[-1]['hash'])
            body = history.snapshot()
            body['metrics']['bps'] = (tip[0]-127)/max(.001,time.monotonic()-started)
            window.setProperty('packet', json.dumps(body))
        except BaseException as error:
            failure.append(repr(error)); loop.quit()

    def inspect():
        if time.monotonic()-started < 1.5:
            return
        try:
            points = [item for item in descendants(graph) if item.objectName() == 'relationBlock']
            assert len(points) == 128, len(points)
            assert len({point.property('blockHash') for point in points}) == len(points)
            ordered = sorted(points, key=lambda point:point.property('blockHeight'))
            for point in points:
                row = supplied.get(point.property('blockHash'))
                assert row is not None and row['height'] == point.property('blockHeight')
            centers = sorted(point.mapToItem(graph,QPointF(point.width()/2,point.height()/2)).x() for point in points if point.opacity() >= .3)
            pitch = (graph.width()-58)/(len(points)-1)
            max_gap = max(b-a for a,b in zip(centers, centers[1:]))
            parent_gap = max(abs(child.x()-parent.x()) for parent,child in zip(ordered, ordered[1:]))
            newest=max(point.property('blockHeight') for point in points)
            tail_centers=sorted(point.mapToItem(graph,QPointF(point.width()/2,point.height()/2)).x()
                                for point in points if point.property('blockHeight')<=newest-24)
            tail_gap=max(b-a for a,b in zip(tail_centers,tail_centers[1:]))
            assert tail_gap<=max(12,pitch*3),('empty span in retained real tail',tail_gap,pitch)
            # Only the most recent real markers have local wire-endpoint
            # motion. Its bounded folds cannot create the old185px bridge.
            assert max_gap <= max(24, pitch*6), ('empty space without real points', max_gap, pitch,
                sorted([(point.property('blockHeight'),round(point.x(),2),round(point.opacity(),2),int(point.property('horizontalDuration'))) for point in points],key=lambda row:row[1]))
            assert parent_gap <= max(32, pitch*8), ('long adjacent-parent bridge', parent_gap, pitch)
            assert centers[0] <= graph.width()*.10 and centers[-1] >= graph.width()*.90, centers
            bins = {min(15, int(x/graph.width()*16)) for x in centers if 0 <= x <= graph.width()}
            assert all(index in bins for index in range(1,15)), bins
            assert int(js('horizontalMotionMs(shownCount-1)')) == 32
            render_samples.append({'max_gap':max_gap, 'tail_gap':tail_gap,'parent_gap':parent_gap, 'pitch':pitch,
                                   'left':centers[0], 'right':centers[-1]})
        except BaseException as error:
            failure.append(repr(error)); loop.quit()

    sampler = QTimer()
    sampler.setTimerType(Qt.PreciseTimer)
    sampler.setInterval(33)
    sampler.timeout.connect(inspect)
    timer.timeout.connect(publish)
    end = QTimer()
    end.setSingleShot(True)
    end.timeout.connect(loop.quit)
    try:
        publish(); timer.start(); sampler.start(); end.start(4200); loop.exec()
        timer.stop(); sampler.stop()
        assert not failure, failure
        assert len(snapshots) > 150, len(snapshots)
        assert len(render_samples) > 20, render_samples
        assert not warnings, warnings
        print(json.dumps({'status':'PASS', 'scope':'Owned deterministic public headers, not network block production',
                          'native':native, 'actual_fixture_admissions':len(snapshots), 'render_samples':len(render_samples),
                          'retained_actual_points':128,
                          'maximum_screen_gap_px':max(row['max_gap'] for row in render_samples),
                          'maximum_retained_tail_gap_px':max(row['tail_gap'] for row in render_samples),
                          'maximum_adjacent_parent_gap_px':max(row['parent_gap'] for row in render_samples),
                          'nominal_pitch_px':render_samples[-1]['pitch'], 'warnings':0}))
    finally:
        timer.stop(); sampler.stop(); window.close(); engine.deleteLater(); app.processEvents()


class LiveGraphDensityTests(unittest.TestCase):
    def check_fixture(self, native=False):
        with tempfile.TemporaryDirectory(prefix='gg-live-density-') as temporary:
            target = Path(temporary)
            env = dict(os.environ, QT_QUICK_CONTROLS_STYLE='Basic',
                       GG_DESKTOP_STATE_ROOT=str(target/'state'), GG_DESKTOP_DATA_ROOT=str(target/'data'))
            if native:
                env.pop('QT_QUICK_BACKEND', None)
                env.update(QT_QPA_PLATFORM='windows', QSG_RHI_BACKEND='d3d11', GG_DENSITY_NATIVE='1')
            else:
                env.update(QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software')
                env.pop('GG_DENSITY_NATIVE', None)
            result = subprocess.run([sys.executable,'-X','utf8','-B',str(Path(__file__).resolve()),'--fixture',temporary],
                                    cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',timeout=20)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            print(result.stdout.strip())

    def test_ongoing_actual_fixture_density_software(self):self.check_fixture()

    @unittest.skipUnless(os.name=='nt','Native Direct3D11 on Windows')
    def test_ongoing_actual_fixture_density_direct3d(self):self.check_fixture(True)


if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--fixture':fixture(Path(sys.argv[2]))
    else:unittest.main()
