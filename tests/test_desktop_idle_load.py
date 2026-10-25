"""Idle editing stays cheap while real activity lamps keep updating unfocused."""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DesktopIdleTests(unittest.TestCase):
    def test_cursor_events_replace_buffer_scanning_and_background_lamps_stay_live(self):
        with tempfile.TemporaryDirectory(prefix="gg-desktop-idle-") as raw:
            env = os.environ.copy()
            env.update(QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software",
                       QT_QUICK_CONTROLS_STYLE="Basic",
                       QTWEBENGINE_CHROMIUM_FLAGS="--disable-gpu --disable-background-networking",
                       GG_DESKTOP_STATE_ROOT=str(Path(raw)/"state"))
            result = subprocess.run([sys.executable, "-B", "-c", SCRIPT], cwd=ROOT,
                                    env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        records = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["idle_cursor_recalculations"], 0)
        self.assertGreater(records[0]["background_meter_polls"], 12)
        self.assertGreater(records[0]["foreground_meter_polls"], 8)
        print(json.dumps(records[0]))


SCRIPT = r'''
from pathlib import Path
import json, os
from PySide6.QtCore import QObject, QMetaObject, QUrl, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlEngine, QQmlComponent
from PySide6.QtQuick import QQuickWindow
from PySide6.QtTest import QTest
from PySide6.QtWebEngineQuick import QtWebEngineQuick
QtWebEngineQuick.initialize()
app=QGuiApplication([])
class Probe(QObject):
    def __init__(self):
        super().__init__(); self.cursor=0; self.meters=0; self.chat_active=False
        self.sample={'cpu_busy':20,'gpu_busy':10,'net_rx_bps':2048,'disk_read_bps':2048}
    @Slot()
    def cursorTick(self): self.cursor+=1
    @Slot(result=str)
    def tmogPulse(self):
        self.meters+=1
        return json.dumps(self.sample)
    @Slot(result=bool)
    def chatIoActive(self): return self.chat_active
probe=Probe()
engine=QQmlEngine()
engine.rootContext().setContextProperty('idleProbe',probe)
path=Path('qml/components/WorkspaceSurface.qml').resolve()
source=path.read_text(encoding='utf8')
marker='function updateEditorCursor() {'
assert source.count(marker)==1
source=source.replace(marker,marker+'\n        idleProbe.cursorTick()',1)
component=QQmlComponent(engine)
component.setData(source.encode(),QUrl.fromLocalFile(str(path)))
assert component.isReady(),[e.toString() for e in component.errors()]
workspace=component.create()
assert workspace is not None,[e.toString() for e in component.errors()]
QTest.qWait(100)
editor=workspace.findChild(QObject,'workspaceCodeEditor')
assert editor is not None
workspace.setProperty('editorLoaded',True)
editor.setProperty('text',chr(10).join(('alpha','beta','gamma')))
editor.setProperty('cursorPosition',8)
app.processEvents()
assert workspace.property('editorLine')==2
assert workspace.property('editorColumn')==3
before=probe.cursor
QTest.qWait(350)
idle=probe.cursor-before
assert idle==0,('Idle editor repeatedly scanned unchanged text',idle)
editor.setProperty('cursorPosition',12)
app.processEvents()
assert workspace.property('editorLine')==3
assert workspace.property('editorColumn')==2
editor.setProperty('text',chr(10).join(('first','second')))
editor.setProperty('cursorPosition',7)
app.processEvents()
assert workspace.property('editorLine')==2
assert workspace.property('editorColumn')==2

path=Path('qml/components/ContextComposer.qml').resolve()
composer_component=QQmlComponent(engine,QUrl.fromLocalFile(str(path)))
assert composer_component.isReady(),[e.toString() for e in composer_component.errors()]
composer=composer_component.create()
assert composer is not None
window=QQuickWindow()
window.resize(720,130)
composer.setParentItem(window.contentItem())
composer.setProperty('surfaceHost',probe)
window.show();window.requestActivate()
QTest.qWait(250)
foreground=probe.meters
assert foreground>8,('Foreground meter update cadence lost',foreground)
cover=QQuickWindow();cover.resize(720,130);cover.show();cover.requestActivate()
QTest.qWait(50)
assert not window.isActive(),'Offscreen cover did not deactivate the GG fixture'
before=probe.meters
QTest.qWait(350)
background=probe.meters-before
assert background>12,('Background lamps stopped reading current data',background)
lamps=('cpuLampOn','gpuLampOn','netLampOn','diskLampOn','chatLampOn')
probe.sample={'cpu_busy':0,'gpu_busy':0,'net_rx_bps':0,'disk_read_bps':0}
QTest.qWait(80)
assert all(not composer.property(name) for name in lamps),'Inactive hardware lamps did not clear in background'
probe.sample={'cpu_busy':25,'gpu_busy':10,'net_rx_bps':4096,'disk_read_bps':4096}
probe.chat_active=True
observed={name:set() for name in lamps}
for index in range(12):
    QTest.qWait(17)
    for name in lamps:observed[name].add(composer.property(name))
assert all(states=={False,True} for states in observed.values()),('Background lamps froze',observed)
probe.sample={'cpu_busy':25,'gpu_busy':10,'net_rx_bps':4096,'disk_read_bps':4096,
              'sample_errors':{'cpu':'OSError','io':'OSError'}}
QTest.qWait(80)
assert all(not composer.property(name) for name in ('cpuLampOn','netLampOn','diskLampOn')), 'Failed probes replayed stale hardware activity'
probe.sample={'cpu_busy':25,'cpu_sample_age_ms':1500}
QTest.qWait(80)
assert not composer.property('cpuLampOn'), 'Expired CPU observation still looked active'
probe.sample={'pending':True}
QTest.qWait(80)
assert all(not composer.property(name) for name in lamps[:-1]),'Unavailable sensors showed stale activity'
window.showMinimized()
before=probe.meters
QTest.qWait(120)
assert probe.meters>before,'Minimized fixture stopped accepting fresh activity data'
composer.setProperty('visible',False)
before=probe.meters
QTest.qWait(100)
assert probe.meters==before
print(json.dumps({'status':'PASS','idle_cursor_recalculations':idle,
                  'foreground_meter_polls':foreground,'background_meter_polls':background,
                  'background_real_activity_changes':'PASS','cursor_text_events':'PASS'}))
composer.deleteLater(); workspace.deleteLater();cover.close();window.close();app.processEvents()
'''


if __name__ == "__main__":
    unittest.main(argv=[__file__])
