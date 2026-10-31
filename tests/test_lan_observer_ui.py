"""Native Qt offscreen: the Desktop shows CLI data but cannot control its node."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]


class ObserverUiTests(unittest.TestCase):
    def test_observed_account_node_names_and_freshness_in_real_qml(self):
        script=r'''
import json,sys
from pathlib import Path
from PySide6.QtCore import QObject,QUrl,QMetaObject,Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlEngine,QQmlComponent,QQmlExpression,qmlContext
from PySide6.QtQuick import QQuickItem,QQuickWindow
app=QGuiApplication([]);engine=QQmlEngine();warnings=[]
engine.warnings.connect(lambda rows:warnings.extend(row.toString() for row in rows))
component=QQmlComponent(engine)
component.setData(('import QtQuick\nimport '+json.dumps((Path.cwd()/'qml/components').as_uri())+'\nGGParallelDagDashboard {width:1250;height:820}').encode(),QUrl.fromLocalFile(str(Path(sys.argv[1])/'fixture.qml')))
assert component.isReady(),[e.toString() for e in component.errors()]
root=component.create();assert root is not None
window=QQuickWindow();root.setParentItem(window.contentItem())
owners=[{'index':i,'display_name':name+' · '+str(i%2+1),'node_label':name,'local':name=='Linux'} for i,name in enumerate(['Termux','Termux','Windows','Windows','Linux','Linux'])]
h0='a'*64;h1='b'*64
blocks=[{'hash':h0,'height':0,'rank':0,'parent_hashes':[],'transaction_count':0,'state':'GENESIS','signature_verified':False,'proposer_index':-1},
 {'hash':h1,'height':1,'rank':1,'parent_hashes':[h0],'transaction_count':5000,'state':'ADMITTED_UNFINALIZED','signature_verified':True,'proposer_index':4,'producer_sequence':1,'admission_index':1}]
dag={'state':'RUNNING','chain_id':'test-shared-chain','producer_count':6,'worker_count':0,
 'blocks_admitted':1,'transactions_validated':5000,
 'producers':[{'index':i,'proposals':1 if i==4 else 0,'transactions':5000 if i==4 else 0} for i in range(6)],
 'lan_setup':{'active':True,'coordinator':False,'invites':[]},
 'lan':{'state':'READY','label':'Linux','connection_state':'CONNECTED','producer_identities':owners,'authenticated_peers':[{'label':'Windows'},{'label':'Termux'}],'configured_peers':3,'traffic_bytes':12345,
        'peer_status':[{'label':'Windows','state':'CONNECTED','age_seconds':.2},{'label':'Termux','state':'CONNECTED','age_seconds':.3}]},
 'block_graph':{'schema':'gg.block-graph.v1','topology':'MULTIPARENT_DAG','source':'LAN_SIGNED_PROPOSAL_DAG','producer_count':6,'producer_identities':owners,'blocks':blocks,'edges':[{'from':h0,'to':h1}],'metrics':{},'stale':False},
 'observation':{'source':'LOCAL_CLI','read_only':True,'stale':False,'node_label':'Linux','age_seconds':.3},
 'test_accounts':[{'producer_index':4,'display_name':'Linux · 1','local':True,'balance_atomic':'999999999999999999','nonce':5000}],
 'dag_stress':{'supported':True,'enabled':True,'local_opt_in':True,'role':'PARTICIPANT','state':'RUNNING','limits':{'min_duration_ms':1000,'max_duration_ms':600000,'min_interval_ms':0,'max_interval_ms':60000,'max_tx_per_block':50000}},
 'live':{'enabled':False},'preview':{},'admission':{},'limits':{}}
def js(owner,code):
 expr=QQmlExpression(qmlContext(owner),owner,code);v=expr.evaluate();assert not expr.hasError(),expr.error().toString();return v[0] if isinstance(v,tuple) else v
def put():
 js(root,'state='+json.dumps({'parallel_dag':dag,'ui_operation':{}}));app.processEvents()
put();events=[];root.actionRequested.connect(lambda name,args:events.append(name))
assert root.property('observerReadOnly') and root.property('lanOwned')
assert not root.property('canAct')
assert root.findChild(QQuickItem,'dagObservationSource').property('visible')
assert 'CLI-noden Linux' in root.findChild(QQuickItem,'dagObservationSource').property('text')
assert js(root,'producerName(4)')=='Linux · 1 · egen'
assert js(root,'producerName(0)')=='Termux · 1'
assert js(root,'producerName(2)')=='Windows · 1'
assert js(root,'metricAt(1).value')=='5000'
assert '999999999999999999' in js(root,'producerAccountText(4)')
start=root.findChild(QQuickItem,'dagStart');stop=root.findChild(QQuickItem,'dagStop')
assert not start.isEnabled() and not stop.isEnabled()
js(root,'run("dag_stop",{})');js(root,'run("lan_dag_stress_start",{})');assert events==[]
popup=root.findChild(QObject,'lanDagSetupPopup');assert popup is not None
assert not popup.findChild(QQuickItem,'lanPriorityStop').isEnabled()
graph=root.findChild(QQuickItem,'dagBlockRelationsGraph');assert graph is not None
js(graph,'refresh()');app.processEvents()
assert js(graph,'producerName(4)')=='Linux · 1 · egen'
assert js(graph,'_allRows.filter(function(b){return b.hash==="'+h1+'"})[0].transaction_count')==5000
dag['dag_stress'].update(state='COMPLETE',blocks=1,transactions=5000,all_peers_synced=False);put()
assert root.property('liveLabel')=='DAG-prov · Lokal del klar'
assert 'Lokal del klar' in popup.findChild(QQuickItem,'lanDagStressStatus').property('text')
assert 'Lokal del klar' in root.findChild(QQuickItem,'dagOperationNotice').property('text')
assert 'nätkvittens ej bekräftad' in root.findChild(QQuickItem,'dagOperationNotice').property('text')
dag['dag_stress'].update(role='COORDINATOR',all_peers_synced=True,acknowledged_blocks=1,acknowledged_transactions=5000);put()
assert root.property('liveLabel')=='DAG-prov · COMPLETE'
assert 'nätkvittens från alla tre' in root.findChild(QQuickItem,'dagOperationNotice').property('text')

work={'local':{'transactions':32,'sign_ms':12.5,'verify_ms':44.5,'wall_ms':58.0,'age_seconds':.2},
      'relay':{'transactions':32,'cpu_ms':300.0,'wall_ms':450.0,'age_seconds':.3},'private_key':'MUST_NOT_EXPORT'}
dag['dag_stress'].update(state='TIME_BUDGET',all_peers_synced=False,workload=work,
    participants=[{'label':'Linux','local':True,'state':'COMPLETE','workload':work},
                  {'label':'Termux','state':'COMPLETE','workload':work}],
    convergence={'before_deadline':{'remaining_ms':42.0,'peers':[{'label':'Termux','matched':False,
        'blocks':99,'transactions':3168,'pending':['state_root','worker','MUST_NOT_EXPORT']}]},
        'cleanup':{'peers':[{'label':'Termux','matched':True}]}});put()
assert 'saknade tillstånd, stoppad producent' in popup.findChild(QQuickItem,'lanDagConvergenceChecks').property('text')
assert 'vid städning matchade' in popup.findChild(QQuickItem,'lanDagConvergenceChecks').property('text')
assert 'CPU 300' in popup.findChild(QQuickItem,'lanDagNodeWorkloads').property('text')
exported=json.loads(js(popup,'JSON.stringify(stressResultDocument())'))
assert exported['convergence']['peers'][0]['pending']==['state_root','worker']
assert exported['convergence']['peers'][0]['cleanup_matched'] is True
assert exported['acknowledgement']['confirmed'] is False
assert exported['workload']['relay']['transactions']==32
assert 'MUST_NOT_EXPORT' not in json.dumps(exported)
assert len(json.dumps(exported,ensure_ascii=False,separators=(',',':')))<4000
saved_stress=json.loads(json.dumps(dag['dag_stress']))
names=[('Very long public node name '+str(i)+' ')*3 for i in range(3)]
names=[name[:64] for name in names]
pending=['observation','run','worker','state','peer_error','proof_format','chain_id','blocks','transactions','blockset_digest','state_root','producer_blocks','producer_transactions']
dag['dag_stress']['participants']=[{'label':name,'state':'COMPLETE','workload':work} for name in names]
dag['dag_stress']['convergence']={'before_deadline':{'remaining_ms':99999.123,'peers':[
    {'label':name,'matched':False,'blocks':4095,'transactions':123456789,'pending':pending} for name in names]},
    'cleanup':{'peers':[{'label':name,'matched':True} for name in names]}}
put();largest=js(popup,'JSON.stringify(stressResultDocument())')
assert len(largest)<=4000,len(largest)
dag['dag_stress']=saved_stress;put()

dag['lan']['last_error']='GG_LAN_READ_DEADLINE';put()
assert root.property('activeTransportError') is False
assert 'Senaste transportfel:' in root.property('notice')
dag['lan']['connection_state']='DEGRADED';put()
assert root.property('activeTransportError') is True
dag['observation']['stale']=True;dag['lan']['connection_state']='STALE';dag['block_graph']['stale']=True;put()
assert root.property('connectionState')=='STALE'
assert 'ÄLDRE DATA' in root.findChild(QQuickItem,'dagObservationSource').property('text')
assert graph.property('stale')
root.setParentItem(None);root.deleteLater();window.deleteLater();engine.deleteLater();app.processEvents()
assert not warnings,warnings
print(json.dumps({'status':'PASS','same_cli_account_and_graph':True,'readonly_controls':True,'named_producers':6,'large_block_tx':5000,'stale_visible':True,'native_window_shown':False}))
'''
        with tempfile.TemporaryDirectory(prefix='gg-cli-desktop-ui-') as temporary:
            env=dict(os.environ,QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software',QT_QUICK_CONTROLS_STYLE='Basic')
            result=subprocess.run([sys.executable,'-X','utf8','-B','-c',script,temporary],cwd=ROOT,env=env,
                                  capture_output=True,text=True,encoding='utf-8',timeout=25)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'],'PASS')


if __name__=='__main__':unittest.main()
