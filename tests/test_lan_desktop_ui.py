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
from PySide6.QtCore import QUrl,QObject,QMetaObject,Qt
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
js('state={parallel_dag:{state:"RUNNING",producer_count:6,worker_count:0,blocks_admitted:7,transactions_validated:0,live:{enabled:false,state:"PAUSED"},lan:{state:"READY",authenticated_peers:[],configured_peers:3},lan_setup:{active:true,coordinator:true,invites:[]},test_tokens:{enabled:true,sequence:999},token_circle:{transactions:999,tps:777}},ui_operation:{}}')
assert start.isEnabled() and start.property('text')=='▷ Kör egna 2'
assert stop.property('text')=='■ Stoppa LAN-peer'
assert QMetaObject.invokeMethod(start,'clicked',Qt.DirectConnection)
assert events==['dag_stop','lan_produce']
js('run("dag_start",{})');js('run("dag_wave",{})');assert events==['dag_stop','lan_produce']
assert js('metricAt(0).value')=='7' and js('metricAt(1).value')=='0'
assert js('metricAt(1).name')=='VALIDERAD DAG-TX'
assert js('metricAt(3).detail')=='2 egna · 3 parade apparater'
assert 'lokal validering' in root.findChild(QQuickItem,'dagSummaryScope').property('text')
assert 'en dator' not in root.findChild(QQuickItem,'dagProducerScope').property('text')
assert 'mottagning och verifiering fortsätter' in root.property('notice')
for width in [360,600,970]:
    root.setWidth(width);app.processEvents()
    controls=root.findChild(QQuickItem,'dagPrimaryControls');modes=root.findChild(QQuickItem,'dagModeControls')
    assert controls.x()>=0 and controls.x()+controls.width()<=width,(width,controls.x(),controls.width())
    assert modes.y()>=controls.y()+controls.height() or modes.x()+modes.width()<=controls.x(),width
root.setWidth(970)
js('state={parallel_dag:{state:"RUNNING",producer_count:6,live:{enabled:true},lan:{state:"READY",configured_peers:3},lan_setup:{active:true}},ui_operation:{}}')
assert start.isEnabled() and start.property('text')=='Ⅱ Pausa egna 2'
assert QMetaObject.invokeMethod(start,'clicked',Qt.DirectConnection)
assert events[-1]=='lan_pause'
assert root.findChild(QQuickItem,'dagLanProduce').property('text')=='Ⅱ Pausa egna 2'
js('state={parallel_dag:{state:"RUNNING",producer_count:6,lan:{state:"READY",last_error:"GG_LAN_FRAME_REPLAY_OR_DOMAIN"},lan_setup:{active:true}},ui_operation:{}}')
assert root.property('notice')=='GG_LAN_FRAME_REPLAY_OR_DOMAIN'
js('state={parallel_dag:{state:"RUNNING",producer_count:6,lan:{state:"READY"},lan_setup:{active:true}},ui_operation:{state:"approval_required"}}')
assert not start.isEnabled() and stop.isEnabled()
js('state={parallel_dag:{state:"STOPPED"},ui_operation:{}}');assert start.isEnabled()
assert start.property('text')=='▷ Starta' and stop.property('text')=='■ Stoppa'
assert QMetaObject.invokeMethod(start,'clicked',Qt.DirectConnection)
assert events[-1]=='dag_start'
root.setParentItem(None);root.deleteLater();window.deleteLater();app.processEvents()
assert not warnings,warnings
print(json.dumps({'status':'PASS','native_window_shown':False,'pairing_priority_stop':True}))
'''
        with tempfile.TemporaryDirectory(prefix='gg-lan-ui-') as temporary:
            environment=dict(os.environ,QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software',QSG_RHI_BACKEND='software')
            result=subprocess.run([sys.executable,'-X','utf8','-B','-c',script,temporary],cwd=ROOT,env=environment,capture_output=True,text=True,encoding='utf-8',timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'],'PASS')

    def test_local_producer_cadence_matches_backend_bounds(self):
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
component.setData(('import QtQuick\nimport '+json.dumps((Path.cwd()/'qml/components').as_uri())+'\nLanDagSetupPopup {}').encode(),QUrl.fromLocalFile(str(Path(sys.argv[1])/'fixture.qml')))
assert component.isReady(),[error.toString() for error in component.errors()]
root=component.create();assert root is not None
actions=[];root.actionRequested.connect(lambda name,args:actions.append((name,args.toVariant() if hasattr(args,'toVariant') else args)))
expr=QQmlExpression(qmlContext(root),root,'state={lan:{state:"READY"},lan_setup:{active:true},live:{enabled:false}}');expr.evaluate();assert not expr.hasError()
cadence=root.findChild(QQuickItem,'lanInterval');produce=root.findChild(QQuickItem,'lanProduce')
assert cadence.property('text')=='250' and produce.isEnabled()
for value in ['','10','99','60001','-100','100.5']:
    cadence.setProperty('text',value);assert not produce.isEnabled(),value
for value in ['100','250','60000']:
    cadence.setProperty('text',value);assert produce.isEnabled(),value
    assert QMetaObject.invokeMethod(produce,'clicked',Qt.DirectConnection)
    assert actions[-1]==('lan_produce',{'interval_ms':int(value)})
root.deleteLater();engine.deleteLater();app.processEvents();assert not warnings,warnings
print(json.dumps({'status':'PASS','native_window_shown':False}))
'''
        with tempfile.TemporaryDirectory(prefix='gg-lan-cadence-ui-') as temporary:
            environment=dict(os.environ,QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software',QT_QUICK_CONTROLS_STYLE='Basic')
            result=subprocess.run([sys.executable,'-X','utf8','-B','-c',script,temporary],cwd=ROOT,env=environment,
                capture_output=True,text=True,encoding='utf-8',timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'],'PASS')

    def test_dag_stress_consent_finite_actions_and_local_vs_acknowledged_metrics(self):
        script=r'''
import copy,json,sys
from pathlib import Path
from PySide6.QtCore import QUrl,QObject,QMetaObject,Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlEngine,QQmlComponent,QQmlExpression,qmlContext
from PySide6.QtQuick import QQuickItem,QQuickWindow
app=QGuiApplication([]);engine=QQmlEngine();warnings=[]
engine.warnings.connect(lambda rows:warnings.extend(row.toString() for row in rows))
component=QQmlComponent(engine)
component.setData(('import QtQuick\nimport '+json.dumps((Path.cwd()/'qml/components').as_uri())+'\nGGParallelDagDashboard {width:970;height:650}').encode(),QUrl.fromLocalFile(str(Path(sys.argv[1])/'fixture.qml')))
assert component.isReady(),[error.toString() for error in component.errors()]
root=component.create();assert root is not None
window=QQuickWindow();root.setParentItem(window.contentItem())
popup=root.findChild(QObject,'lanDagSetupPopup');assert popup is not None
actions=[];root.actionRequested.connect(lambda name,args:actions.append((name,args.toVariant() if hasattr(args,'toVariant') else args)))
def js(owner,code):
    expr=QQmlExpression(qmlContext(owner),owner,code);value=expr.evaluate()
    assert not expr.hasError(),expr.error().toString()
    return value[0] if isinstance(value,tuple) else value
def put(dag):
    js(root,'state='+json.dumps({'parallel_dag':dag,'ui_operation':{}}));app.processEvents()
def find(owner,name):
    item=owner.findChild(QQuickItem,name);assert item is not None,name;return item
def click(owner,name):
    item=find(owner,name);assert item.isEnabled(),name
    assert QMetaObject.invokeMethod(item,'clicked',Qt.DirectConnection)
limits={'min_duration_ms':1000,'max_duration_ms':60000,'min_interval_ms':100,'max_interval_ms':60000,'max_tx_per_block':128}
capability={'supported':True,'enabled':False,'local_opt_in':False,'role':'COORDINATOR','can_start':False,
    'limits':limits,'state':'IDLE','participants':[],'duration_ms':10000,'transactions_per_block':1,'interval_ms':250,
    'elapsed_ms':0,'blocks':0,'transactions':0,'all_peers_synced':False,'acknowledged_blocks':None,
    'acknowledged_transactions':None,'acknowledged_bps':None,'acknowledged_tps':None,'stop_reason':'','last_error':''}
stopped={'state':'STOPPED','producer_count':0,'lan':{'state':'STOPPED'},'lan_setup':{'active':False},'dag_stress':copy.deepcopy(capability)}
legacy=copy.deepcopy(stopped);legacy.pop('dag_stress');put(legacy)
assert not popup.property('stressSupported') and not find(popup,'lanAllowDagTransactions').isEnabled()
click(popup,'lanStart');assert 'allow_dag_transactions' not in actions[-1][1]
put(stopped)
opt_in=find(popup,'lanAllowDagTransactions');assert opt_in.isEnabled() and opt_in.property('checked') is False
click(popup,'lanStart');assert 'allow_dag_transactions' not in actions[-1][1]
find(popup,'lanAllowTestTokens').setProperty('checked',True)
opt_in.setProperty('checked',True)
assert find(popup,'lanAllowTestTokens').property('checked') is False
click(popup,'lanStart');assert actions[-1][0]=='lan_start' and actions[-1][1]['allow_dag_transactions'] is True
js(popup,'joinBootstrap("gg-lan-bootstrap.json")')
assert actions[-1][0]=='lan_join_file' and actions[-1][1]['allow_dag_transactions'] is True
put(legacy);click(popup,'lanStart');assert 'allow_dag_transactions' not in actions[-1][1]
opt_in.setProperty('checked',False)
roster=[{'label':'Windows','local':True,'allow_dag_transactions':True},
    {'label':'Linux','allow_dag_transactions':True},{'label':'Termux','allow_dag_transactions':True}]
pairing=copy.deepcopy(stopped);pairing['lan']['state']='PAIRING'
pairing['lan_setup']={'active':True,'coordinator':True,'allow_dag_transactions':True,'invites':copy.deepcopy(roster)}
pairing['lan_setup']['invites'][2]['allow_dag_transactions']=False;put(pairing)
assert not find(popup,'lanCreateSession').isEnabled()
assert '3 DAG-TX-val' in find(popup,'lanCreateSession').property('text')
pairing['lan_setup']['invites'][2]['allow_dag_transactions']=True;put(pairing)
click(popup,'lanCreateSession');assert actions[-1][1]['enable_dag_transactions'] is True
assert actions[-1][1]['enable_test_tokens'] is False
pairing['lan_setup']['allow_test_tokens']=True
for peer in pairing['lan_setup']['invites']:peer['allow_test_tokens']=True
put(pairing);click(popup,'lanCreateSession')
assert actions[-1][1]['enable_dag_transactions'] is True and actions[-1][1]['enable_test_tokens'] is False
pairing['lan_setup'].pop('allow_test_tokens')
for peer in pairing['lan_setup']['invites']:peer.pop('allow_test_tokens')
put(pairing)
for label in ['Linux','Termux']:
    assert 'allow_dag_transactions=true' in js(popup,'command('+json.dumps(label)+')')
pairing['lan_setup']['allow_dag_transactions']=False;put(pairing)
click(popup,'lanCreateSession');assert 'enable_dag_transactions' not in actions[-1][1]
assert 'allow_dag_transactions' not in js(popup,'command("Termux")')
pairing['lan_setup']['coordinator']=False;put(pairing)
assert not find(popup,'lanCreateSession').isEnabled()
participants=[{'label':'Windows','local':True,'opted_in':True},{'label':'Linux','local':False,'opted_in':True},{'label':'Termux','local':False,'opted_in':True}]
ready=copy.deepcopy(pairing);ready['lan'].update(state='READY',configured_peers=3)
ready['lan_setup'].update(coordinator=True,allow_dag_transactions=True,invites=roster)
ready.update(state='RUNNING',producer_count=6,blocks_admitted=12,transactions_validated=48,
    test_tokens={'enabled':True,'sequence':999},token_circle={'transactions':999,'tps':777},
    block_graph={'schema':'gg.block-graph.v1','topology':'MULTIPARENT_DAG','producer_count':6,
        'blocks':[{'hash':'a'*64,'parent_hashes':[],'height':0,'rank':0,'proposer_index':-1,'producer_sequence':0,'transaction_count':0,'state':'GENESIS'},
            {'hash':'b'*64,'parent_hashes':['a'*64],'height':1,'rank':1,'proposer_index':0,'producer_sequence':1,'transaction_count':4,'state':'ADMITTED_UNFINALIZED','signature_verified':True}],
        'edges':[{'from':'a'*64,'to':'b'*64}],'metrics':{'bps':2,'tps':8}})
ready['dag_stress'].update(enabled=True,local_opt_in=True,can_start=True,participants=participants,blocks=3,transactions=12)
put(ready)
start=find(popup,'lanDagStressStart');stop=find(popup,'lanDagStressStop')
duration=find(popup,'lanDagStressDuration');transactions=find(popup,'lanDagStressTransactions');interval=find(popup,'lanDagStressInterval')
assert start.isEnabled() and not stop.isEnabled()
click(popup,'lanDagStressStart')
assert actions[-1]==('lan_dag_stress_start',{'duration_ms':10000,'transactions_per_block':1,'interval_ms':250})
for field,valid,invalid in [(duration,'10',['','0','61','1.5']),
        (transactions,'1',['','0','129','-1','1.5']),
        (interval,'250',['','99','60001','100.5'])]:
    for value in invalid:
        field.setProperty('text',value);assert not start.isEnabled(),(field.objectName(),value)
    field.setProperty('text',valid);assert start.isEnabled()
for seconds,tx,cadence in [('1','1','100'),('60','128','60000')]:
    duration.setProperty('text',seconds);transactions.setProperty('text',tx);interval.setProperty('text',cadence)
    assert start.isEnabled()
    click(popup,'lanDagStressStart')
    assert actions[-1][1]=={'duration_ms':int(seconds)*1000,'transactions_per_block':int(tx),'interval_ms':int(cadence)}
duration.setProperty('text','10');transactions.setProperty('text','1');interval.setProperty('text','250')
for key,value in [('can_start',False),('local_opt_in',False),('enabled',False),('supported',False),('role','PARTICIPANT')]:
    denied=copy.deepcopy(ready);denied['dag_stress'][key]=value;put(denied);assert not start.isEnabled(),key
mixed=copy.deepcopy(ready);mixed['dag_stress']['participants'][2]['opted_in']=False;put(mixed);assert not start.isEnabled()
mixed['dag_stress']['participants'].pop();put(mixed);assert not start.isEnabled()
put(ready)
assert js(root,'metricAt(0).value')=='12' and js(root,'metricAt(1).value')=='48'
assert js(root,'graph.blocks[1].hash')=='b'*64 and js(root,'graph.edges.length')==1
assert find(popup,'lanDagStressLocal').property('text')=='Lokalt verifierat under provet: 3 förslag · 12 DAG-TX'
assert '2.0 block/s · 4.0 TX/block under provet · 8.0 TX/s' in find(popup,'lanDagStressRates').property('text')
assert '999' not in find(popup,'lanDagStressLocal').property('text')
for phase in ['STARTING','RUNNING','STOPPING']:
    running=copy.deepcopy(ready);running['dag_stress'].update(state=phase,can_start=False,elapsed_ms=2500)
    put(running)
    assert not start.isEnabled() and not duration.isEnabled() and stop.isEnabled()
    assert root.property('dagStressRunning')
    count=len(actions);js(root,'run("lan_produce",{})');js(root,'run("lan_pause",{})');assert len(actions)==count
    click(popup,'lanDagStressStop');assert actions[-1]==('lan_dag_stress_stop',{})
    assert phase in find(popup,'lanDagStressStatus').property('text')
popup.setProperty('width',360);app.processEvents()
assert QMetaObject.invokeMethod(find(popup,'lanDagStressActions'),'forceLayout',Qt.DirectConnection)
assert start.x()>=0 and start.x()+start.width()<=start.parentItem().width()
assert stop.x()>=0 and stop.x()+stop.width()<=stop.parentItem().width()
popup.setProperty('width',720);app.processEvents()
complete=copy.deepcopy(ready);complete['dag_stress'].update(state='COMPLETE',stop_reason='DURATION',
    acknowledged_blocks=999,acknowledged_transactions=999,acknowledged_bps=999,acknowledged_tps=999)
put(complete)
assert 'COMPLETE' in find(popup,'lanDagStressStatus').property('text')
assert not stop.isEnabled() and 'DURATION' in find(popup,'lanDagStressDetails').property('text')
assert 'ännu inte bekräftad' in find(popup,'lanDagStressAcknowledged').property('text')
assert not root.property('hasDagAcknowledgement') and js(root,'acknowledgedRate("acknowledged_tps")')=='—'
failed=copy.deepcopy(complete);failed['dag_stress'].update(state='ERROR',last_error='GG_LAN_DAG_STRESS_FAILED',stop_reason='FAILED')
put(failed)
assert root.property('notice')=='GG_LAN_DAG_STRESS_FAILED'
assert find(popup,'lanDagStressDetails').property('text')=='Fel: GG_LAN_DAG_STRESS_FAILED · Stopporsak: FAILED'
assert '3 förslag · 12 DAG-TX' in find(popup,'lanDagStressLocal').property('text')
proven=copy.deepcopy(complete);proven['dag_stress'].update(all_peers_synced=True,acknowledged_blocks=3,acknowledged_transactions=12,acknowledged_bps=.3,acknowledged_tps=1.2)
put(proven)
assert root.property('hasDagAcknowledgement') and js(root,'acknowledgedRate("acknowledged_tps")')=='1.2'
assert 'Nätkvittens från alla tre: 3 förslag · 12 DAG-TX · 0.3 förslag/s · 1.2 TX/s'==find(popup,'lanDagStressAcknowledged').property('text')
proven['dag_stress']['acknowledged_transactions']=None;put(proven)
assert not root.property('hasDagAcknowledgement') and 'ännu inte bekräftad' in find(popup,'lanDagStressAcknowledged').property('text')
expanded=copy.deepcopy(ready);expanded['dag_stress']['limits']['max_tx_per_block']=4096;put(expanded)
transactions.setProperty('text','1000');assert start.isEnabled(),'UI follows advertised limits without claiming this capacity has been measured'
transactions.setProperty('text','4097');assert not start.isEnabled()
root.setParentItem(None);root.deleteLater();window.deleteLater();engine.deleteLater();app.processEvents()
assert not warnings,warnings
print(json.dumps({'status':'PASS','native_window_shown':False,'fixture_only':True,'no_physical_peers':True}))
'''
        with tempfile.TemporaryDirectory(prefix='gg-dag-stress-ui-') as temporary:
            environment=dict(os.environ,QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software',QT_QUICK_CONTROLS_STYLE='Basic')
            result=subprocess.run([sys.executable,'-X','utf8','-B','-c',script,temporary],cwd=ROOT,env=environment,
                capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'],'PASS')


    def test_v3_primary_and_lower_toggles_use_finite_probe_and_preserve_results(self):
        script=r'''
import copy,json,sys
from pathlib import Path
from PySide6.QtCore import QUrl,QObject
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlEngine,QQmlComponent,QQmlExpression,qmlContext
from PySide6.QtQuick import QQuickItem,QQuickWindow
from backend.gg_lan_dag import dag_stress_capabilities
capability=dag_stress_capabilities()
capability.update(enabled=True,local_opt_in=True,role='COORDINATOR',can_start=True,state='IDLE',
    participants=[{'label':'Windows','local':True,'opted_in':True},{'label':'Linux','local':False,'opted_in':True},{'label':'Termux','local':False,'opted_in':True}],
    blocks=0,transactions=0,elapsed_ms=0,all_peers_synced=False,acknowledged_blocks=None,acknowledged_transactions=None,
    acknowledged_bps=None,acknowledged_tps=None,stop_reason='',last_error='')
ready={'state':'RUNNING','producer_count':6,'worker_count':0,'blocks_admitted':0,'transactions_validated':0,
    'lan':{'state':'READY','configured_peers':3},'lan_setup':{'active':True,'coordinator':True,'allow_dag_transactions':True},
    'live':{'enabled':False},'dag_stress':capability}
app=QGuiApplication([]);engine=QQmlEngine();warnings=[]
engine.warnings.connect(lambda rows:warnings.extend(row.toString() for row in rows))
engine.rootContext().setContextProperty('initialPacket',json.dumps({'parallel_dag':ready,'ui_operation':{}}))
component=QQmlComponent(engine)
source="""import QtQuick
import COMPONENTS
GGParallelDagDashboard {id:fixture;width:970;height:650;state:JSON.parse(initialPacket)
    function fixtureControl(name){
        var pending=[fixture]
        for(var i=0;i<pending.length;i++){
            var item=pending[i]
            if(item.objectName===name)return item
            var items=item.children||[]
            for(var j=0;j<items.length;j++)pending.push(items[j])
        }
        return null
    }
    function fixtureClick(name){var item=fixtureControl(name);if(!item||!item.enabled)return false;item.clicked();return true}
}""".replace('COMPONENTS',json.dumps((Path.cwd()/'qml/components').as_uri()))
component.setData(source.encode(),QUrl.fromLocalFile(str(Path(sys.argv[1])/'fixture.qml')))
assert component.isReady(),[error.toString() for error in component.errors()]
root=component.create();assert root is not None
window=QQuickWindow();root.setParentItem(window.contentItem())
popup=root.findChild(QObject,'lanDagSetupPopup');assert popup is not None
actions=[];root.actionRequested.connect(lambda name,args:actions.append((name,args.toVariant() if hasattr(args,'toVariant') else args)))
def js(owner,code):
    expr=QQmlExpression(qmlContext(owner),owner,code);value=expr.evaluate()
    assert not expr.hasError(),expr.error().toString()
    return value[0] if isinstance(value,tuple) else value
def put(dag,operation=None):
    js(root,'state='+json.dumps({'parallel_dag':dag,'ui_operation':operation or {}}));app.processEvents()
def enabled(name):return js(root,'fixtureControl('+json.dumps(name)+').enabled')
def text(name):return js(root,'fixtureControl('+json.dumps(name)+').text')
def click(name):assert js(root,'fixtureClick('+json.dumps(name)+')'),name
for name in ['dagStart','dagLanProduce']:
    put(ready);assert enabled(name) and 'DAG-prov' in text(name)
    click(name)
    assert actions[-1]==('lan_dag_stress_start',{'duration_ms':10000,'transactions_per_block':16,'interval_ms':100})
assert not popup.findChild(QQuickItem,'lanProduce').isEnabled()
assert not popup.findChild(QQuickItem,'lanPause').isEnabled()
assert 'tidsbegränsat prov' in popup.findChild(QQuickItem,'lanProducerModeNote').property('text')
before=len(actions)
for owner in [root,popup]:
    js(owner,'run("lan_produce",{})');js(owner,'run("lan_pause",{})')
assert len(actions)==before,'V3 cannot call the legacy producer API even while idle'
clamped=copy.deepcopy(ready)
clamped['dag_stress']['limits'].update(max_duration_ms=5000,max_tx_per_block=8,min_interval_ms=250)
put(clamped);click('dagStart')
assert actions[-1]==('lan_dag_stress_start',{'duration_ms':5000,'transactions_per_block':8,'interval_ms':250})
for key,value in [('can_start',False),('local_opt_in',False),('role','PARTICIPANT')]:
    denied=copy.deepcopy(ready);denied['dag_stress'][key]=value;put(denied)
    assert not enabled('dagStart') and not enabled('dagLanProduce'),key
    before=len(actions);js(root,'triggerPrimary()');assert len(actions)==before
mixed=copy.deepcopy(ready);mixed['dag_stress']['participants'][2]['opted_in']=False;put(mixed)
assert not enabled('dagStart') and not enabled('dagLanProduce')
missing=copy.deepcopy(ready);missing['dag_stress'].pop('limits');put(missing)
assert not enabled('dagStart') and not enabled('dagLanProduce')
for phase in ['STARTING','RUNNING']:
    active=copy.deepcopy(ready);active['worker_count']=1
    active['dag_stress'].update(state=phase,can_start=False,worker_count=1,worker_active=True,blocks=3,transactions=48)
    put(active)
    for name in ['dagStart','dagLanProduce']:
        assert enabled(name) and 'Stoppa DAG-prov' in text(name)
        click(name);assert actions[-1]==('lan_dag_stress_stop',{})
    assert root.property('liveLabel')=='DAG-prov · '+phase
    assert '3 förslag / 48 DAG-TX lokalt' in root.property('notice')
stopping=copy.deepcopy(active);stopping['dag_stress']['state']='STOPPING';put(stopping)
assert not enabled('dagStart') and not enabled('dagLanProduce')
participant=copy.deepcopy(active);participant['lan_setup']['coordinator']=False;participant['dag_stress']['role']='PARTICIPANT';put(participant)
assert not enabled('dagStart') and not enabled('dagLanProduce')
assert not popup.findChild(QQuickItem,'lanDagStressStop').isEnabled()
complete=copy.deepcopy(active);complete['worker_count']=0;complete['dag_stress'].update(state='COMPLETE',worker_count=0,worker_active=False,stop_reason='DURATION')
put(complete)
assert root.property('liveLabel')=='DAG-prov · COMPLETE'
assert 'COMPLETE' in root.property('notice') and '3 förslag / 48 DAG-TX lokalt' in root.property('notice')
assert 'nätkvittens ej bekräftad' in root.property('notice') and 'pausade' not in root.property('notice')
complete['dag_stress'].update(all_peers_synced=True,acknowledged_blocks=3,acknowledged_transactions=48)
put(complete);assert 'nätkvittens från alla tre' in root.property('notice')
put(active,{'state':'approval_required'})
assert not enabled('dagStart') and enabled('dagStop')
click('dagStop');assert actions[-1][0]=='dag_stop'
legacy=copy.deepcopy(ready);legacy['dag_stress']['enabled']=False;put(legacy)
click('dagStart');assert actions[-1]==('lan_produce',{})
legacy['live']['enabled']=True;put(legacy)
click('dagLanProduce');assert actions[-1]==('lan_pause',{})
root.setParentItem(None);root.deleteLater();window.deleteLater();engine.deleteLater();app.processEvents()
assert not warnings,warnings
print(json.dumps({'status':'PASS','native_window_shown':False,'fixture_only':True,'physical_peers':0}))
'''
        with tempfile.TemporaryDirectory(prefix='gg-dag-v3-toggle-ui-') as temporary:
            environment=dict(os.environ,QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software',QT_QUICK_CONTROLS_STYLE='Basic')
            result=subprocess.run([sys.executable,'-X','utf8','-B','-c',script,temporary],cwd=ROOT,env=environment,
                capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'],'PASS')


    def test_first_start_uses_sibling_runtime_capability_without_changing_local_dag(self):
        script=r'''
import copy,json,sys
from pathlib import Path
from PySide6.QtCore import QUrl,QObject,QMetaObject,Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlEngine,QQmlComponent,QQmlExpression,qmlContext
from PySide6.QtQuick import QQuickItem,QQuickWindow
from backend import gg_parallel_dag
from backend.lan_dag_runtime import LanDagRuntime
local=gg_parallel_dag.snapshot();lan=LanDagRuntime().snapshot()
assert local['state']=='STOPPED' and 'dag_stress' not in local
assert lan['dag_stress']['supported'] is True
packet={'parallel_dag':local,'lan_dag':lan,'ui_operation':{}}
app=QGuiApplication([]);engine=QQmlEngine();warnings=[]
engine.warnings.connect(lambda rows:warnings.extend(row.toString() for row in rows))
engine.rootContext().setContextProperty('initialPacket',json.dumps(packet))
component=QQmlComponent(engine)
source='import QtQuick\nimport '+json.dumps((Path.cwd()/'qml/components').as_uri())+'\nGGParallelDagDashboard {width:970;height:650;state:JSON.parse(initialPacket)}'
component.setData(source.encode(),QUrl.fromLocalFile(str(Path(sys.argv[1])/'fixture.qml')))
assert component.isReady(),[error.toString() for error in component.errors()]
root=component.create();assert root is not None
window=QQuickWindow();root.setParentItem(window.contentItem())
popup=root.findChild(QObject,'lanDagSetupPopup');assert popup is not None
opt_in=popup.findChild(QQuickItem,'lanAllowDagTransactions');start=popup.findChild(QQuickItem,'lanStart')
assert opt_in is not None and start is not None
actions=[];root.actionRequested.connect(lambda name,args:actions.append((name,args.toVariant() if hasattr(args,'toVariant') else args)))
def js(owner,code):
    expr=QQmlExpression(qmlContext(owner),owner,code);value=expr.evaluate()
    assert not expr.hasError(),expr.error().toString()
    return value[0] if isinstance(value,tuple) else value
def assert_local_unchanged():
    assert json.loads(js(root,'JSON.stringify(graph)'))==local['block_graph']
    assert js(root,'metricAt(0).value')==str(local['blocks_admitted'])
    assert js(root,'metricAt(1).value')==str(local['transactions_validated'])
    assert not root.property('lanOwned') and js(root,'dag.dag_stress===undefined')
assert popup.property('stressSupported') and opt_in.isEnabled() and opt_in.property('checked') is False
assert_local_unchanged()
opt_in.setProperty('checked',True)
assert start.isEnabled() and QMetaObject.invokeMethod(start,'clicked',Qt.DirectConnection)
assert actions[-1][0]=='lan_start' and actions[-1][1]['allow_dag_transactions'] is True
# Fast telemetry replaces only the local parallel-DAG lane. The full-state
# sibling remains the capability source, without becoming displayed graph data.
js(root,'state=Object.assign({},state,{parallel_dag:'+json.dumps(gg_parallel_dag.snapshot())+'})')
assert popup.property('stressSupported') and opt_in.isEnabled()
assert_local_unchanged()
legacy={'parallel_dag':gg_parallel_dag.snapshot(),'ui_operation':{}}
js(root,'state='+json.dumps(legacy))
assert not popup.property('stressSupported') and not opt_in.isEnabled()
assert QMetaObject.invokeMethod(start,'clicked',Qt.DirectConnection)
assert actions[-1][0]=='lan_start' and 'allow_dag_transactions' not in actions[-1][1]
assert_local_unchanged()
# Capability may arrive with a later full snapshot; the inert fallback reacts.
js(root,'state='+json.dumps(packet))
assert popup.property('stressSupported') and opt_in.isEnabled()
assert_local_unchanged()
# An owned legacy LAN peer cannot inherit stopped setup capability support.
owned_legacy=copy.deepcopy(packet);owned_legacy['parallel_dag']['lan_setup']={'active':True}
js(root,'state='+json.dumps(owned_legacy))
assert not popup.property('stressSupported') and not opt_in.isEnabled()
root.setParentItem(None);root.deleteLater();window.deleteLater();engine.deleteLater();app.processEvents()
assert not warnings,warnings
print(json.dumps({'status':'PASS','actual_stopped_backend_snapshots':True,'native_window_shown':False,'physical_peers':0}))
'''
        with tempfile.TemporaryDirectory(prefix='gg-lan-first-start-ui-') as temporary:
            environment=dict(os.environ,QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software',QT_QUICK_CONTROLS_STYLE='Basic')
            result=subprocess.run([sys.executable,'-X','utf8','-B','-c',script,temporary],cwd=ROOT,env=environment,
                capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'],'PASS')


if __name__=='__main__':unittest.main()
