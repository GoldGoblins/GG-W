"""Hidden software controls require explicit test-token consent and exact units."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]


class LanTestTokenUiTests(unittest.TestCase):
    def test_opt_in_session_and_circle_controls_use_exact_tokens(self):
        script=r'''
import json,sys
from pathlib import Path
from PySide6.QtCore import QUrl,QMetaObject,Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlEngine,QQmlComponent,QQmlExpression,qmlContext
from PySide6.QtQuick import QQuickItem
app=QGuiApplication([]);engine=QQmlEngine();warnings=[]
engine.warnings.connect(lambda rows:warnings.extend(row.toString() for row in rows))
component=QQmlComponent(engine)
source='import QtQuick\nimport '+json.dumps((Path.cwd()/'qml/components').as_uri())+'\nLanDagSetupPopup {}'
component.setData(source.encode(),QUrl.fromLocalFile(str(Path(sys.argv[1])/'fixture.qml')))
assert component.isReady(),[error.toString() for error in component.errors()]
root=component.create();assert root is not None
actions=[]
root.actionRequested.connect(lambda name,args:actions.append((name,args.toVariant() if hasattr(args,'toVariant') else args)))
def js(code):
    expr=QQmlExpression(qmlContext(root),root,code);value=expr.evaluate();assert not expr.hasError(),expr.error().toString();return value[0] if isinstance(value,tuple) else value
def find(name):
    item=root.findChild(QQuickItem,name);assert item is not None,name;return item
def click(name):
    item=find(name);assert item.isEnabled(),name;assert QMetaObject.invokeMethod(item,'clicked',Qt.DirectConnection)
click('lanStart');assert actions[-1][0]=='lan_start' and actions[-1][1]['allow_test_tokens'] is False
find('lanAllowTestTokens').setProperty('checked',True)
click('lanStart');assert actions[-1][1]['allow_test_tokens'] is True
js('state={lan:{state:"PAIRING"},lan_setup:{active:true,coordinator:true,allow_test_tokens:true,invites:[{allow_test_tokens:true},{allow_test_tokens:true},{allow_test_tokens:false}]}}')
assert not find('lanCreateSession').isEnabled()
js('state={lan:{state:"PAIRING"},lan_setup:{active:true,coordinator:true,allow_test_tokens:true,invites:[{allow_test_tokens:true},{allow_test_tokens:true},{allow_test_tokens:true}]}}')
click('lanCreateSession');assert actions[-1][0]=='lan_session_create' and actions[-1][1]['enable_test_tokens'] is True
js('state={lan:{state:"READY",public_key:"a"},lan_setup:{active:true,coordinator:true},test_tokens:{enabled:true,decimals:6,accounts:[]},token_circle:{state:"IDLE"}}')
assert js('tokenAmount("1000000000")')=='1000'
assert js('tokenAmount("1000000001")')=='1000.000001'
assert js('wholeTokenAtomic()')=='1000000'
click('lanCircleStart');assert actions[-1]==('lan_circle_start',{'duration_ms':10000,'batch':1,'amount_atomic':'1000000'})
js('state={lan:{state:"READY"},lan_setup:{active:true,coordinator:true},test_tokens:{enabled:true,decimals:6},token_circle:{state:"RUNNING"}}')
assert not find('lanCircleStart').isEnabled();click('lanCircleStop');assert actions[-1][0]=='lan_circle_stop'
root.deleteLater();engine.deleteLater();app.processEvents();assert not warnings,warnings
'''
        with tempfile.TemporaryDirectory(prefix='gg-token-ui-') as temporary:
            environment=dict(os.environ,QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software',QT_QUICK_CONTROLS_STYLE='Basic')
            result=subprocess.run([sys.executable,'-X','utf8','-B','-c',script,temporary],cwd=ROOT,env=environment,
                capture_output=True,text=True,encoding='utf-8',timeout=15)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)


if __name__=='__main__':unittest.main()
