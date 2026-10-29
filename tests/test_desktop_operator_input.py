"""Actual offscreen Qt input: no user windows, node, network or app state."""
from pathlib import Path
import json
import os
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DesktopInputTests(unittest.TestCase):
    def test_root_window_and_timestamped_popup_click(self):
        script = r'''
import ast,json,os,time
from pathlib import Path
from types import MethodType,SimpleNamespace
from unittest.mock import patch
from PySide6.QtCore import QObject,QPointF,QUrl,QMetaObject,Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem,QQuickWindow
from PySide6.QtTest import QTest

# Compile only the production methods under test: constructing the application
# host would start unrelated services and touch the current user's state.
tree=ast.parse(Path('backend/chat_surface_host.py').read_text(encoding='utf-8'))
host_class=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='ChatSurfaceHost')
methods=[n for n in host_class.body if isinstance(n,ast.FunctionDef) and n.name in {'_desk_window','_desk_send_click'}]
scope={'os':os,'time':time}
exec(compile(ast.Module(body=methods,type_ignores=[]),'<production desktop input>','exec'),scope)
app=QGuiApplication([]);engine=QQmlApplicationEngine();warnings=[]
engine.warnings.connect(lambda rows:warnings.extend(row.toString() for row in rows))
source="""import QtQuick
import QtQuick.Controls
import "components"
ApplicationWindow {
 id:window;width:1706;height:912;visible:true
 GGParallelDagDashboard {objectName:"probeDashboard";x:546;y:71;width:974;height:695}
}
"""
engine.loadData(source.encode(),QUrl(Path.cwd().as_uri()+'/qml/desktop-input-probe.qml'))
assert engine.rootObjects(),warnings
window=engine.rootObjects()[0];QTest.qWait(80)
host=SimpleNamespace(_qml_root=window,_external_embed=None,_tui_hole=lambda:None)
host._desk_window=MethodType(scope['_desk_window'],host)
host._desk_send_click=MethodType(scope['_desk_send_click'],host)
hidden=QQuickWindow();hidden.setFlags(Qt.Popup);hidden.setVisible(False)
with patch.object(QGuiApplication,'topLevelWindows',return_value=[hidden,window]):
 assert host._desk_window() is window,'explicit ApplicationWindow lost to hidden popup'
 host._qml_root=None
 assert host._desk_window() is window,'fallback selected hidden popup'
 with patch.object(QGuiApplication,'topLevelWindows',return_value=[hidden]):
  assert host._desk_window() is None,'hidden window became an input target'
 item=QQuickItem(window.contentItem());host._qml_root=item
 assert host._desk_window() is window,'QQuickItem owner window was lost'
host._qml_root=window
dashboard=window.findChild(QObject,'probeDashboard')
popup=window.findChild(QObject,'lanDagSetupPopup');assert popup is not None
QMetaObject.invokeMethod(popup,'open');QTest.qWait(40)
button=window.findChild(QQuickItem,'lanStart');assert button and button.isEnabled()
point=button.mapToItem(window.contentItem(),QPointF(button.width()/2,button.height()/2))
seen=[];dashboard.actionRequested.connect(lambda name,args:seen.append(name))
host._desk_send_click(round(point.x()),round(point.y()),'left');QTest.qWait(40)
assert seen==['lan_start'],('popup ScrollView swallowed the click',seen)
assert host._desk_last_input_timestamp>0
host._desk_send_click(round(point.x()),round(point.y()),'left');QTest.qWait(40)
assert seen==['lan_start','lan_start'],('repeat click lost',seen)
assert not warnings,warnings
print(json.dumps({'status':'PASS','native_window_shown':False,'window_selection':True,'popup_real_clicks':len(seen)}))
'''
        environment = dict(os.environ, QT_QPA_PLATFORM='offscreen',
                           QT_QUICK_CONTROLS_STYLE='Basic',
                           QT_QUICK_BACKEND='software', QSG_RHI_BACKEND='software')
        result = subprocess.run([sys.executable, '-X', 'utf8', '-B', '-c', script],
                                cwd=ROOT, env=environment, capture_output=True,
                                text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'PASS')


if __name__ == '__main__':
    unittest.main()
