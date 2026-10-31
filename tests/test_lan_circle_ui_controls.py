"""Exercise the real LAN popup offscreen without a runtime or physical peers."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class LanCircleUiControlsTests(unittest.TestCase):
    def test_circle_bounds_actions_and_finished_failure_feedback(self):
        script = r'''
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
    expr=QQmlExpression(qmlContext(root),root,code);value=expr.evaluate()
    assert not expr.hasError(),expr.error().toString()
    return value[0] if isinstance(value,tuple) else value
def find(name):
    item=root.findChild(QQuickItem,name);assert item is not None,name;return item
def click(name):
    item=find(name);assert item.isEnabled(),name
    assert QMetaObject.invokeMethod(item,'clicked',Qt.DirectConnection)
def state(circle,coordinator=True):
    body={'lan':{'state':'READY'},'lan_setup':{'active':True,'coordinator':coordinator},
        'test_tokens':{'enabled':True,'decimals':6},'token_circle':circle}
    js('state='+json.dumps(body))
duration=find('lanCircleDuration');batch=find('lanCircleBatch');start=find('lanCircleStart')
state({'state':'IDLE'})
assert duration.property('text')=='10' and batch.property('text')=='1'
for label,python in [('Termux','python'),('Linux','python3')]:
    command=js('command('+json.dumps(label)+')')
    assert command.startswith(python+' gg-cli.py --foreground')
    assert 'lan.start label='+label+' auto_produce=false' in command
assert 'Redo' in find('lanCircleSync').property('text')
click('lanCircleStart')
assert actions[-1]==('lan_circle_start',{'duration_ms':10000,'batch':1,'amount_atomic':'1000000'})
for seconds,count in [('1','1'),('60','16')]:
    duration.setProperty('text',seconds);batch.setProperty('text',count)
    assert start.isEnabled()
    assert seconds+' s' in start.property('text') and 'batch '+count in start.property('text')
    click('lanCircleStart')
    assert actions[-1][1]=={'duration_ms':int(seconds)*1000,'batch':int(count),'amount_atomic':'1000000'}
for field,valid,invalid in [(duration,'10',['','0','61','-1','1.']),
                           (batch,'1',['','0','17','-1','1.'])]:
    duration.setProperty('text','10');batch.setProperty('text','1')
    for value in invalid:
        field.setProperty('text',value);assert not start.isEnabled(),(field.objectName(),value)
    field.setProperty('text',valid);assert start.isEnabled()
for phase in ['RUNNING','STOPPING']:
    state({'state':phase,'transactions':16,'all_peers_synced':False})
    assert not start.isEnabled() and not duration.isEnabled() and not batch.isEnabled()
    assert 'Pågår' in find('lanCircleSync').property('text')
    click('lanCircleStop');assert actions[-1][0]=='lan_circle_stop'
state({'state':'RUNNING','all_peers_synced':True})
assert 'slutkontroll återstår' in find('lanCircleSync').property('text')
state({'state':'ERROR','transactions':16,'completed_rounds':0,'all_peers_synced':False,
    'last_error':'GG_LAN_CIRCLE_FAILED','stop_reason':'FAILED'})
assert start.isEnabled() and duration.isEnabled() and batch.isEnabled()
assert '16 TX' in find('lanCircleStatus').property('text') and '0 varv' in find('lanCircleStatus').property('text')
details=find('lanCircleDetails');sync=find('lanCircleSync')
assert details.property('text')=='Fel: GG_LAN_CIRCLE_FAILED · Stopporsak: FAILED'
assert 'Avslutat' in sync.property('text') and 'delresultat' in sync.property('text')
assert 'när provet avslutas' not in sync.property('text')
state({'state':'ERROR','transactions':16,'all_peers_synced':False,
    'last_error':'GG_LAN_CIRCLE_FAILED','stop_reason':'FAILED',
    'last_error_details':{'operation':'CIRCLE_SIGN','stage':'read_frame','error_class':'TimeoutError'}})
assert 'Operation: CIRCLE_SIGN · Steg: read_frame · Felklass: TimeoutError' in details.property('text')
state({'state':'TIME_BUDGET','transactions':0,'all_peers_synced':False,'stop_reason':'DURATION'})
assert 'kunde inte bekräftas' in sync.property('text')
assert details.property('text')=='Stopporsak: DURATION'
state({'state':'COMPLETE','transactions':3,'all_peers_synced':True,'stop_reason':'DURATION'})
assert 'Avslutat' in sync.property('text') and 'alla tre peers har bekräftat' in sync.property('text')
state({'state':'STOPPED','transactions':1,'all_peers_synced':False,
    'last_error':'<img src=x>\nsecret=example','stop_reason':'FAILED\x00',
    'last_error_details':{'operation':'<img>','stage':'read\nsecret=example','error_class':'X'*49}})
assert details.property('text')=='Fel: Okänd orsak · Stopporsak: Okänd orsak'
state({'state':'IDLE'})
assert details.property('text')==''
state({'state':'IDLE'},coordinator=False)
assert not start.isEnabled() and not duration.isEnabled() and not batch.isEnabled()
setup_error=find('lanSetupError')
js('state={lan:{state:"READY",last_error:"GG_LAN_TOKEN_RPC",last_error_details:{operation:"CIRCLE_SIGN",stage:"read_frame",error_class:"TimeoutError"}},token_circle:{state:"ERROR",last_error:"GG_LAN_CIRCLE_FAILED",stop_reason:"FAILED"}}')
assert setup_error.property('text')=='Senast registrerat transportfel: GG_LAN_TOKEN_RPC · Operation: CIRCLE_SIGN · Steg: read_frame · Felklass: TimeoutError'
assert 'Fel: GG_LAN_CIRCLE_FAILED' in details.property('text')
js('formError="Kontrollera längden";operationError="Operationen misslyckades"')
assert setup_error.property('text')=='Kontrollera längden'
js('formError=""')
assert setup_error.property('text')=='Operationen misslyckades'
js('operationError="";state={lan:{last_error:"<img>\\nsecret=example",last_error_details:{operation:"<img>",stage:"read\\nsecret=example",error_class:"X".repeat(49)}}}')
assert setup_error.property('text')=='Senast registrerat transportfel: Okänd orsak'
js('state={lan:{last_error:"GG_LAN_WIRE"}}')
assert setup_error.property('text')=='Senast registrerat transportfel: GG_LAN_WIRE'
js('state={lan:{}}')
assert setup_error.property('text')==''
root.deleteLater();engine.deleteLater();app.processEvents();assert not warnings,warnings
print(json.dumps({'status':'PASS','native_window_shown':False,'bounds_checked':True}))
'''
        with tempfile.TemporaryDirectory(prefix='gg-circle-ui-') as temporary:
            environment = dict(os.environ, QT_QPA_PLATFORM='offscreen',
                QT_QUICK_BACKEND='software', QT_QUICK_CONTROLS_STYLE='Basic')
            result = subprocess.run([sys.executable, '-X', 'utf8', '-B', '-c', script, temporary],
                cwd=ROOT, env=environment, capture_output=True, text=True,
                encoding='utf-8', timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'PASS')


if __name__ == '__main__':
    unittest.main()
