"""Small software-only LAN pairing UI; no shown window, sockets or settings."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]


class LanUiTests(unittest.TestCase):
    def test_pairing_stop_bypasses_busy_and_preserves_local_control_fences(self):
        script=r'''
import json,sys
from pathlib import Path
from PySide6.QtCore import QUrl,QObject
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlEngine,QQmlComponent,QQmlExpression,qmlContext
from PySide6.QtQuick import QQuickItem,QQuickWindow
app=QGuiApplication([]);engine=QQmlEngine();warnings=[]
engine.warnings.connect(lambda rows:warnings.extend(row.toString() for row in rows))
component=QQmlComponent(engine)
source='import QtQuick\nimport '+json.dumps((Path.cwd()/'qml/components').as_uri())+'\nGGParallelDagDashboard {width:970;height:650}'
component.setData(source.encode(),QUrl.fromLocalFile(str(Path(sys.argv[1])/'fixture.qml')))
assert not component.isError(),[row.toString() for row in component.errors()]
root=component.create();assert root is not None,[row.toString() for row in component.errors()]
window=QQuickWindow();root.setParentItem(window.contentItem())
events=[];root.actionRequested.connect(lambda name,args:events.append(name))
def js(code):
 expr=QQmlExpression(qmlContext(root),root,code);value=expr.evaluate();assert not expr.hasError(),expr.error().toString();return value[0] if isinstance(value,tuple) else value
js('state={parallel_dag:{state:"STOPPED",producer_count:0,lan:{state:"PAIRING",authenticated_peers:[]},lan_setup:{active:true,coordinator:true,invites:[]}},ui_operation:{state:"running"}}')
assert root.property('lanOwned') and root.property('busy')
stop=root.findChild(QQuickItem,'dagStop');start=root.findChild(QQuickItem,'dagStart');assert stop and start
assert stop.isEnabled() and not start.isEnabled()
popup=root.findChild(QObject,'lanDagSetupPopup');assert popup is not None
priority=popup.findChild(QQuickItem,'lanPriorityStop');assert priority and priority.isEnabled()
js('run("dag_start",{})');js('run("dag_wave",{})');js('run("lan_produce",{})');assert events==[]
js('run("dag_stop",{})');assert events==['dag_stop']
js('state={parallel_dag:{state:"RUNNING",producer_count:6,lan:{state:"READY",authenticated_peers:[],configured_peers:3},lan_setup:{active:true,coordinator:true,invites:[]}},ui_operation:{}}')
assert not start.isEnabled();js('run("dag_start",{})');js('run("dag_wave",{})');assert events==['dag_stop']
js('state={parallel_dag:{state:"STOPPED"},ui_operation:{}}');assert start.isEnabled()
root.setParentItem(None);root.deleteLater();window.deleteLater();app.processEvents()
assert not warnings,warnings
print(json.dumps({'status':'PASS','native_window_shown':False,'pairing_priority_stop':True}))
'''
        with tempfile.TemporaryDirectory(prefix='gg-lan-ui-') as temporary:
            environment=dict(os.environ,QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software',QSG_RHI_BACKEND='software')
            result=subprocess.run([sys.executable,'-X','utf8','-B','-c',script,temporary],cwd=ROOT,env=environment,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'],'PASS')


if __name__=='__main__':unittest.main()
