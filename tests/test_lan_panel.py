"""Real offscreen input for the persistent LAN panel; no peers or sockets."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class LanPanelTests(unittest.TestCase):
    def test_chat_other_panels_drag_close_and_resize(self):
        script = r"""
import json, os, sys
from pathlib import Path
from PySide6.QtCore import QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest

app = QGuiApplication([])
if os.name == 'nt':
    QFontDatabase.addApplicationFont(str(Path(os.environ['SystemRoot'])/'Fonts/consola.ttf'))
    QFont.insertSubstitution('monospace', 'Consolas')
    app.setFont(QFont('Consolas', 10))
engine = QQmlApplicationEngine()
warnings = []
engine.warnings.connect(lambda rows: warnings.extend(row.toString() for row in rows))
path = Path(sys.argv[1]) / 'panel.qml'
path.write_text('''import QtQuick
import QtQuick.Controls
import COMPONENTS
ApplicationWindow {
    width:1280; height:850; visible:true; color:'#17394d'
    TextField {objectName:'chatInput';x:20;y:760;width:220;height:36;placeholderText:'Chat'}
    Button {objectName:'openSettings';x:20;y:14;width:100;text:'Settings';onClicked:settings.visible=true}
    Button {objectName:'openWallet';x:130;y:14;width:100;text:'Wallet';onClicked:wallet.visible=true}
    Item {x:300;y:60;width:900;height:740;clip:true
        GGParallelDagDashboard {objectName:'dashboard';anchors.fill:parent}
    }
    SettingsPopup {id:settings;objectName:'settings';z:9999;visible:false;x:16;y:80;width:760;height:650;onCloseRequested:visible=false}
    WalletPopup {id:wallet;objectName:'wallet';z:9999;visible:false;x:940;y:70;visualWidth:328;visualHeight:600;onRequestClose:visible=false}
}
'''.replace('COMPONENTS', json.dumps((Path.cwd()/'qml/components').as_uri())), encoding='utf-8')
engine.load(QUrl.fromLocalFile(str(path)))
assert engine.rootObjects(), warnings
window = engine.rootObjects()[0]
QTest.qWait(80)
dashboard = window.findChild(QQuickItem, 'dashboard')
panel = dashboard.findChild(QQuickItem, 'lanDagSetupPopup')
assert panel is not None and not panel.isVisible()
actions = []
dashboard.actionRequested.connect(lambda name, args: actions.append(name))

def item(name):
    found = window.findChild(QQuickItem, name)
    assert found is not None, name
    return found

def point(target):
    return target.mapToScene(QPointF(target.width()/2, target.height()/2)).toPoint()

def click(name):
    target = item(name)
    assert target.isVisible() and target.isEnabled(), name
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point(target))
    QTest.qWait(35)

def pixel(image, x, y):
    ratio = image.width()/window.width()
    return image.pixelColor(round(x*ratio), round(y*ratio)).rgba()

baseline = window.grabWindow()
click('dagLanSetup')
assert panel.isVisible()
assert panel.parentItem() == window.property('contentItem'), 'panel must escape clipped DAG ancestors'
opened = window.grabWindow()
assert pixel(opened, 30, 700) == pixel(baseline, 30, 700), 'LAN opening dimmed the chat'
assert pixel(opened, 1260, 810) == pixel(baseline, 1260, 810), 'LAN opening dimmed the app'
click('chatInput')
for character in 'chat stays usable':
    QTest.keyClick(window, Qt.Key(ord(character.upper())))
QTest.qWait(30)
assert item('chatInput').property('text') == 'chat stays usable'
assert item('chatInput').hasActiveFocus()
assert panel.isVisible(), 'chat click dismissed LAN'
QTest.keyClick(window, Qt.Key_Escape)
assert panel.isVisible(), 'Escape in chat must not dismiss LAN'
click('openSettings')
click('openWallet')
assert item('settings').isVisible() and item('wallet').isVisible() and panel.isVisible()
item('settings').setVisible(False)
item('wallet').setVisible(False)
QTest.qWait(30)

grip = item('lanDragHandle')
start = point(grip)
old_x, old_y = panel.x(), panel.y()
QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, start)
QTest.mouseMove(window, start+QPoint(-30, 10), 20)
QTest.mouseMove(window, start+QPoint(-300, 25), 40)
QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, start+QPoint(-300, 25))
QTest.qWait(40)
assert panel.x() < old_x-150, (old_x, panel.x())
assert panel.x() < 300, 'drag must reach beyond the DAG workspace'
assert panel.y() != old_y
dragged = (panel.x(), panel.y())
moved = window.grabWindow()
assert pixel(moved, panel.x()+4, panel.y()+60) != pixel(baseline, panel.x()+4, panel.y()+60)
evidence = os.environ.get('GG_LAN_PANEL_EVIDENCE')
if evidence:
    assert moved.save(evidence)
click('lanSetupCloseButton')
assert not panel.isVisible()
click('dagLanSetup')
assert panel.isVisible() and (panel.x(), panel.y()) == dragged, 'reopening lost the dragged position'
click('lanLabel')
QTest.keyClick(window, Qt.Key_Escape)
QTest.qWait(30)
assert not panel.isVisible(), 'Escape in LAN must close the panel'
click('dagLanSetup')
window.resize(640, 520)
QTest.qWait(50)
assert panel.isVisible() and panel.x() >= 0 and panel.y() >= 12
assert panel.x()+panel.width() <= window.width()
assert panel.y()+panel.height() <= window.height()
assert not actions, actions
assert not warnings, warnings
window.close()
print(json.dumps({'status':'PASS','chat_input':True,'undimmed':True,'coexisting_panels':True,
    'drag_outside_workspace':True,'position_retained':True,'explicit_close':True,'resize':True,
    'network_actions':0}))
"""
        environment = dict(os.environ, QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software',
                           QT_QUICK_CONTROLS_STYLE='Basic')
        with tempfile.TemporaryDirectory(prefix='gg-lan-panel-') as temporary:
            result = subprocess.run([sys.executable, '-X', 'utf8', '-B', '-c', script, temporary],
                                    cwd=ROOT, env=environment, capture_output=True, text=True,
                                    encoding='utf-8', timeout=25)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'PASS')


if __name__ == '__main__':
    unittest.main()
