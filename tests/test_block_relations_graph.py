"""Retained vectors: real edges, bounded view, selection and idle quiescence."""
from __future__ import annotations
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]


def identifier(height):return hashlib.sha256(('public-render-block-'+str(height)).encode()).hexdigest()


def fixture(directory):
    from PySide6.QtCore import QObject,QPoint,Qt,QUrl,Slot
    from PySide6.QtGui import QFont,QFontDatabase
    from PySide6.QtQml import QQmlApplicationEngine,QQmlExpression,qmlContext
    from PySide6.QtQuick import QQuickItem,QSGRendererInterface
    from PySide6.QtTest import QSignalSpy,QTest
    from PySide6.QtWidgets import QApplication
    app=QApplication([]);app.setQuitOnLastWindowClosed(False)
    if os.name=='nt':QFontDatabase.addApplicationFont(str(Path(os.environ['SystemRoot'])/'Fonts/consola.ttf'))
    QFont.insertSubstitution('monospace','Consolas' if os.name=='nt' else 'DejaVu Sans Mono')
    engine=QQmlApplicationEngine();warnings=[]
    engine.warnings.connect(lambda rows:warnings.extend(e.toString() for e in rows))
    class Host(QObject):
        def __init__(self):super().__init__();self.copied=[]
        @Slot(str)
        def tmogCopy(self,value):self.copied.append(value)
    host=Host();engine.rootContext().setContextProperty('fixtureHost',host)
    source=directory/'fixture.qml'
    source.write_text('''import QtQuick
import QtQuick.Controls
import COMPONENTS
ApplicationWindow {
    width:900;height:230;visible:true;color:'#111111'
    flags:Qt.Tool|Qt.FramelessWindowHint|Qt.WindowDoesNotAcceptFocus
    x:-10000;y:-10000
    BlockRelationsGraph {objectName:'graph';inspectGeometry:true;pointMode:false;x:8;y:8;width:parent.width-16;height:190;surfaceHost:fixtureHost}
}
'''.replace('COMPONENTS',json.dumps((ROOT/'qml/components').as_uri())),encoding='utf-8')
    engine.load(QUrl.fromLocalFile(str(source)));assert engine.rootObjects(),warnings
    window=engine.rootObjects()[0];graph=window.findChild(QQuickItem,'graph');assert graph
    native=os.environ.get('GG_BLOCK_NATIVE')=='1'
    # Offscreen native windows do not have a reliable animation clock. Native
    # geometry/topology is checked in reduced motion; software checks actual
    # animated transitions and idle quiescence below.
    if native:graph.setProperty('animateChanges',False)
    if native:assert window.rendererInterface().graphicsApi()==QSGRendererInterface.GraphicsApi.Direct3D11
    def js(code):
        expression=QQmlExpression(qmlContext(graph),graph,code);value=expression.evaluate()
        assert not expression.hasError(),expression.error().toString()
        value=value[0] if isinstance(value,tuple) else value
        return value.toVariant() if hasattr(value,'toVariant') else value
    def settle():
        QTest.qWait(700);app.processEvents()
        assert not graph.property('animationRunning')
        assert not graph.property('geometryError')
        assert not warnings,warnings
    def push(data):js('graph=JSON.parse('+json.dumps(json.dumps(data))+')');settle()
    def data(tip,proposers=False):
        rows=[{'height':h,'hash':identifier(h),'parent_hash':identifier(h-1) if h else '',
               'transaction_count':h%7,'timestamp':1700000000+h,'certificate_verified':h==tip,
               **({'proposer_index':h%4} if proposers else {})} for h in range(max(0,tip-47),tip+1)]
        return {'schema':'gg.block-graph.v1','topology':'CHAIN','blocks':rows,
                'edges':[{'from':a['hash'],'to':b['hash']} for a,b in zip(rows,rows[1:])],
                'history_limit':48,'tip_height':tip,'tip_hash':identifier(tip),'stale':False,'error':''}
    settle();assert graph.property('shownCount')==0
    lazy_details=window.findChild(QObject,'blockRelationsDetailsContent')
    assert lazy_details is not None and not lazy_details.property('active') and lazy_details.property('item') is None
    push(data(47));assert graph.property('retainedCount')==48
    assert graph.property('shownCount')==12 and graph.property('edgeCount')==11
    js('selectBlock('+json.dumps(identifier(37))+')')
    assert graph.property('highlightedCount')==8,'selected block plus at most7 real successors'
    js('measurements=JSON.parse('+json.dumps(json.dumps([{'block_height':37},{'block_hash':'0x'+identifier(47)},{}]))+')')
    mappings=graph.property('measurementColumns').toVariant()
    assert [m['known'] for m in mappings]==[True,True,False]
    assert mappings[0]['block_hash']==identifier(37)
    bad=deepcopy(data(47));bad['edges'][38]['from']=identifier(1)
    push(bad);assert graph.property('edgeCount')==10,'forged parent edge must not render'
    js('selectBlock('+json.dumps(identifier(37))+')');assert graph.property('highlightedCount')==2
    frames=[]
    window.frameSwapped.connect(lambda:frames.append(time.perf_counter()))
    push(data(48,True));assert graph.property('shownCount')==12
    animation_frames=list(frames)
    intervals=sorted((b-a)*1000 for a,b in zip(animation_frames,animation_frames[1:]))
    if not native:assert len(animation_frames)>2,'visible software fixture must animate then become idle'
    js('selectBlock('+json.dumps(identifier(46))+')')
    assert graph.property('highlightedCount')==3
    QTest.keyClick(window,Qt.Key_Right);assert graph.property('selectedHash')==identifier(47)
    details=window.findChild(QQuickItem,'blockRelationsDetails');assert details
    point=details.mapToScene(details.boundingRect().center()).toPoint()
    QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,point);QTest.qWait(40)
    popup=window.findChild(QObject,'blockRelationsPopup');assert popup.property('visible')
    assert lazy_details.property('active') and lazy_details.property('item') is not None
    area=window.findChild(QObject,'blockRelationsFullHash');assert area.property('text')==identifier(47)
    js('copySelected()');assert host.copied[-1]==identifier(47)
    QTest.keyClick(window,Qt.Key_Escape);QTest.qWait(50)
    assert not lazy_details.property('active') and lazy_details.property('item') is None
    for width in (360,430,900,1600):
        window.setWidth(width);settle()
        assert graph.property('shownCount')==graph.property('displayLimit')
        assert graph.property('edgeCount')==graph.property('shownCount')-1
        output=os.environ.get('GG_BLOCK_GRAPH_EVIDENCE')
        if output:
            destination=Path(output);destination.mkdir(parents=True,exist_ok=True)
            assert window.grabWindow().save(str(destination/('block-relations-'+str(width)+('-native' if native else '-software')+'.png')))
    # At the actual compact desktop size every boxed block remains in bounds
    # with all four real proposer lanes. No tiny invisible dots are substituted.
    window.setWidth(706);window.setHeight(124);graph.setHeight(108);push(data(49,True))
    def descendants(item):
        for child in item.childItems():
            yield child
            yield from descendants(child)
    cards=[item for item in descendants(graph) if item.objectName()=='relationBlock']
    assert len(cards)==12 and all(item.width()>=40 and item.height()>=30 for item in cards)
    assert graph.property('shownCount')==12 and not graph.property('geometryError')
    output=os.environ.get('GG_BLOCK_GRAPH_EVIDENCE')
    if output:
        destination=Path(output);destination.mkdir(parents=True,exist_ok=True)
        assert window.grabWindow().save(str(destination/('block-relations-compact-'+('native' if native else 'software')+'.png')))
    # The production default is a point map. Every observed block remains a
    # distinct selectable node and every edge still comes from the source.
    graph.setProperty('pointMode',True);settle()
    assert graph.property('shownCount')==48 and graph.property('edgeCount')==47
    points=[item for item in descendants(graph) if item.objectName()=='relationBlock']
    assert len(points)==48 and all(item.width()==10 and item.height()==10 for item in points)
    assert len({round(item.y(),1) for item in points})>8
    assert not graph.property('geometryError') and not graph.property('dagMode')
    if output:
        assert window.grabWindow().save(str(destination/('block-points-'+('native' if native else 'software')+'.png')))
    graph.setProperty('pointMode',False);settle()
    js('resumeLive()');assert graph.property('followTip')
    push(data(50,True));assert graph.property('selectedHash')==identifier(43)
    # A real Qt context property can supply QVariantList, which is array-like
    # but fails Array.isArray in QML. The same bounded public blocks must draw.
    graph.setProperty('graph',data(51,True));settle()
    assert graph.property('retainedCount')==48 and graph.property('shownCount')==12
    assert graph.property('edgeCount')==11
    stale=data(50);stale.update(stale=True,error='GG_BLOCK_GRAPH_READ_FAILED');push(stale)
    assert graph.property('stale')
    # Repeated identical status refresh must keep the scene idle. No timer or
    # endless float animation may mask a redraw cost in the new monitor.
    current_generation=graph.property('_nodeGeneration')
    js('graph=JSON.parse('+json.dumps(json.dumps(stale))+')');QTest.qWait(50)
    assert graph.property('_nodeGeneration')==current_generation
    swaps=QSignalSpy(window.frameSwapped);QTest.qWait(250)
    idle_swaps=swaps.count();assert idle_swaps==0,('idle repaint',idle_swaps)
    push({});assert graph.property('shownCount')==0
    assert not warnings,warnings
    print(json.dumps({'status':'PASS','native':native,'widths':[360,430,900,1600],
                      'real_parent_guards':True,'idle_swaps':idle_swaps,'warnings':0,'bounded_nodes':48,
                      'animation_frames':len(animation_frames),
                      'animation_median_frame_ms':round(intervals[len(intervals)//2],2) if intervals else None,
                      'native_fps_unmeasured_when_occluded':native}))
    window.close();engine.deleteLater();app.processEvents()


class BlockRelationsGraphTests(unittest.TestCase):
    def run_fixture(self,native=False):
        with tempfile.TemporaryDirectory(prefix='gg-block-render-') as temporary:
            environment=os.environ.copy();environment['QT_QUICK_CONTROLS_STYLE']='Basic'
            if native:
                environment.pop('QT_QUICK_BACKEND',None)
                environment.update(QT_QPA_PLATFORM='windows',QSG_RHI_BACKEND='d3d11',GG_BLOCK_NATIVE='1')
            else:
                environment.update(QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software');environment.pop('GG_BLOCK_NATIVE',None)
            result=subprocess.run([sys.executable,'-X','utf8','-B',str(Path(__file__).resolve()),'--fixture',temporary],
                cwd=ROOT,env=environment,capture_output=True,text=True,encoding='utf-8',timeout=35)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr);print(result.stdout.strip())
    def test_software_retained_graph(self):self.run_fixture()
    @unittest.skipUnless(os.name=='nt','Direct3D11 check requiresWindows')
    def test_native_retained_graph(self):self.run_fixture(True)


if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--fixture':fixture(Path(sys.argv[2]))
    else:unittest.main()
