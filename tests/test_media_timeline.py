"""Production UtilitySurface clock telemetry and real pointer/keyboard seeking."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

PROJECT = Path(__file__).resolve().parents[1]

PROBE = r'''
import json
from pathlib import Path
from PySide6.QtCore import QObject, QPoint, QPointF, Qt, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest

class Host(QObject):
    mediaStateChanged = Signal()
    def __init__(self):
        super().__init__()
        self.payload = dict(mode='TV', backend='qml', playing=True, paused=False,
            position=15.0, duration=120.0, clock='00:15', length='02:00',
            now={'id':'fixture', 'title':'Clock fixture'}, volume=70, spectrum=[])
        self.seeks=[]
    @Slot(result=str)
    def mediaLiveStatus(self): return json.dumps(self.payload)
    @Slot(float, result=str)
    def mediaSeek(self, seconds):
        self.seeks.append(seconds)
        # Simulate a decoder acknowledging after an old status tick. Optimistic
        # command replies must not be mistaken for its subsequent actual clock.
        return json.dumps(dict(self.payload, position=seconds))
    def update(self, **values):
        self.payload.update(values)
        self.mediaStateChanged.emit()
        QTest.qWait(25)

app=QGuiApplication([])
app.setQuitOnLastWindowClosed(False)
host=Host(); engine=QQmlApplicationEngine(); warnings=[]
engine.warnings.connect(lambda rows:warnings.extend(row.toString() for row in rows))
engine.rootContext().setContextProperty('clockHost',host)
base=(Path.cwd()/'qml/components').as_uri()
engine.loadData(('import QtQuick\nimport "'+base+'"\nWindow { width:1000;height:112;visible:true;'
    'UtilitySurface {anchors.fill:parent;surfaceHost:clockHost}}').encode())
assert engine.rootObjects(), warnings
window=engine.rootObjects()[0]; root=window.findChild(QObject,'utilitySurface')
track=root.findChild(QObject,'utilityTimeline')
handle=root.findChild(QObject,'utilityTimelineHandle')
fill=root.findChild(QObject,'utilityTimelineFill')
mouse=root.findChild(QObject,'utilityTimelineMouse')
QTest.qWait(60)
assert root.property('position')==15.0, root.property('position')
assert abs(root.property('progress')-.125)<.0001
initial_x=handle.property('x'); chrome=root.property('statusJson')
host.update(position=60.0,clock='01:00')
assert root.property('meterPosition')==60.0
assert root.property('position')==60.0
assert handle.property('x')>initial_x+200
assert abs(fill.property('width')-track.property('width')*.5)<1
assert root.property('statusJson')==chrome, 'Clock ticks rebuilt static chrome/EQ bindings'

# Paused media keeps an accurate stationary clock and can still be scrubbed.
host.update(playing=False,paused=True)
width=track.property('width')
def point(fraction):
    p=mouse.mapToScene(QPointF(width*fraction,mouse.property('height')/2))
    return QPoint(round(p.x()),round(p.y()))
QTest.mousePress(window,Qt.LeftButton,Qt.NoModifier,point(.2))
QTest.mouseMove(window,point(.45),10)
QTest.mouseMove(window,point(.75),10)
QTest.qWait(30)
assert root.property('timelineDragging')
assert not host.seeks, host.seeks
assert abs(root.property('position')-90)<1
host.update(position=60.0)
assert abs(root.property('position')-90)<1, 'Old clock overrode drag preview'
QTest.mouseRelease(window,Qt.LeftButton,Qt.NoModifier,point(.75))
QTest.qWait(30)
assert not root.property('timelineDragging')
assert len(host.seeks)==1, host.seeks
assert abs(host.seeks[-1]-90)<1, host.seeks
assert abs(root.property('position')-90)<1, 'Seek dot snapped to old decoder clock'
host.update(position=host.seeks[-1],clock='01:30')
assert root.property('seekPreview')==-1

QTest.keyClick(window,Qt.Key_Home)
QTest.qWait(20)
assert host.seeks[-1]==0, host.seeks
host.update(position=0,clock='00:00')
assert root.property('position')==0
QTest.keyClick(window,Qt.Key_Right)
QTest.qWait(20)
assert host.seeks[-1]==10,host.seeks
host.update(position=10)
QTest.keyClick(window,Qt.Key_End)
QTest.qWait(20)
assert host.seeks[-1]==120,host.seeks
host.update(position=120)
QTest.keyClick(window,Qt.Key_Left)
QTest.qWait(20)
assert host.seeks[-1]==110,host.seeks

# Switching programme during a drag cancels it; releasing cannot seek the new
# decoder or retain a preview from the previous programme.
QTest.mousePress(window,Qt.LeftButton,Qt.NoModifier,point(.2))
QTest.mouseMove(window,point(.4),10)
QTest.qWait(20)
assert root.property('timelineDragging')
prior_seeks=len(host.seeks)
host.update(now={'id':'next-fixture','title':'Next programme'},position=0)
assert root.property('seekPreview')==-1
assert not root.property('timelineDragging')
QTest.mouseRelease(window,Qt.LeftButton,Qt.NoModifier,point(.8))
assert len(host.seeks)==prior_seeks

host.update(position=0,duration=0,playing=False,paused=False,now={})
assert not root.property('seekable')
assert not track.property('visible')
assert root.property('position')==0
assert not warnings,warnings
print(json.dumps({'clock_updates':True,'drag_seeks':1,'keyboard':True,'warnings':warnings}))
window.close()
from shiboken6 import delete
delete(engine)
'''

class MediaTimelineTests(unittest.TestCase):
    def test_decoder_clock_drag_keyboard_and_zero_seek(self):
        env=os.environ.copy()
        env.update(QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software',
                   QT_QUICK_CONTROLS_STYLE='Basic',QML_DISABLE_DISK_CACHE='1')
        flags={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}
        result=subprocess.run([sys.executable,'-X','utf8','-B','-c',PROBE],cwd=PROJECT,
            env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=15,**flags)
        self.assertEqual(result.returncode,0,(result.stdout+'\n'+result.stderr)[-5000:])
        self.assertEqual(json.loads(result.stdout.strip().splitlines()[-1])['drag_seeks'],1)

if __name__=='__main__':
    unittest.main()
