"""Real offscreen QML: participant-owned work does not require coordinator UI."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]


class IndependentNodeUiTests(unittest.TestCase):
    def test_local_start_stop_and_readonly_cli_observation(self):
        script=r'''
import copy,json,sys
from pathlib import Path
from PySide6.QtCore import QUrl,QObject
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlEngine,QQmlComponent,QQmlExpression,qmlContext
from PySide6.QtQuick import QQuickItem
app=QGuiApplication([]);engine=QQmlEngine();warnings=[]
engine.warnings.connect(lambda items:warnings.extend(item.toString() for item in items))
component=QQmlComponent(engine)
component.setData(('import QtQuick\nimport '+json.dumps((Path.cwd()/'qml/components').as_uri())+'\nGGParallelDagDashboard {width:1250;height:820}').encode(),QUrl.fromLocalFile(str(Path(sys.argv[1])/'fixture.qml')))
assert component.isReady(),[e.toString() for e in component.errors()]
root=component.create();assert root is not None
limits={'min_duration_ms':1000,'max_duration_ms':600000,'min_interval_ms':0,'max_interval_ms':60000,'max_tx_per_block':50000}
dag={'state':'RUNNING','producer_count':6,'worker_count':0,'blocks_admitted':0,'transactions_validated':0,
 'lan_setup':{'active':True,'coordinator':False,'invites':[]},
 'lan':{'state':'READY','label':'Linux','configured_peers':3,'authenticated_peers':[],'connection_state':'DISCONNECTED'},
 'dag_stress':{'supported':True,'enabled':True,'local_opt_in':True,'role':'PARTICIPANT','state':'IDLE','can_start':False,'limits':limits},
 'dag_production':{'supported':True,'enabled':True,'can_start':True,'worker_active':False,'selected':False,'state':'IDLE','limits':limits},
 'block_graph':{'blocks':[],'edges':[],'metrics':{}},'live':{'enabled':False},'admission':{},'preview':{},'limits':{}}
def js(owner,code):
 expr=QQmlExpression(qmlContext(owner),owner,code);v=expr.evaluate();assert not expr.hasError(),expr.error().toString();return v[0] if isinstance(v,tuple) else v
def put():js(root,'state='+json.dumps({'parallel_dag':dag,'ui_operation':{}}));app.processEvents()
put();events=[];root.actionRequested.connect(lambda name,args:events.append((name,args.toVariant() if hasattr(args,'toVariant') else args)))
dag['lan']['peer_status']=[{'label':'Termux','state':'CONNECTED','sync':{'state':'CATCHING_UP','remote_records':20,'received_records':12,'pending_records':8}}]
dag['lan']['participation']={'producer':True,'replica':True,'consensus_validator':False,'mining':False}
put();assert root.property('syncSummary')=='1 / 1 · max 8 kvar'
assert root.property('participationLabel')=='Producent + replika'
assert '12 / 20' in root.property('connectionDetails')
assert '12 / 20' in root.findChild(QQuickItem,'lanPeerSyncStatus').property('text')
dag['lan']['peer_status'][0]['sync'].update(state='SCANNED_WITH_REFUSALS',remote_records=20,received_records=20,pending_records=0,validated_prefix=12,declined_records=1,unresolved_records=1)
put();assert '1 ej validerade' in root.property('syncSummary')
assert '20 / 20 lästa' in root.property('connectionDetails')
assert '12 sammanhängande validerade' in root.property('connectionDetails')
assert '1 ej validerade' in js(root.findChild(QObject,'lanDagSetupPopup'),'peerSyncText()')
dag['dag_proofs']={'payload_recovery':{'enabled':True,'state':'IDLE','pending':0,'recovered_blocks':1,'recovered_bytes':2464461,'last_error':''}}
put();assert '1 block' in root.findChild(QQuickItem,'dagPayloadRecovery').property('value')
assert '2.35 MiB' in root.findChild(QQuickItem,'dagPayloadRecovery').property('value')
dag['dag_proofs']['payload_recovery'].update(last_error='GG_PAYLOAD_WIRE_DIGEST')
put();assert 'Väntar på giltig data' in root.findChild(QQuickItem,'dagPayloadRecovery').property('value')
dag['dag_proofs']['payload_recovery'].update(state='RECOVERING',pending=3)
put();assert '3 väntar' in root.findChild(QQuickItem,'dagPayloadRecovery').property('value')
dag['dag_proofs']['payload_recovery'].update(phase='DOWNLOADING',partial_downloaded_bytes=1048576,partial_reserved_bytes=2464461,recovered_blocks=0,recovered_bytes=0)
put();value=root.findChild(QQuickItem,'dagPayloadRecovery').property('value');assert '1.00 MiB / 2.35 MiB' in value and '3 väntar' in value
dag['dag_proofs']['payload_recovery'].update(phase='VALIDATING')
put();assert root.findChild(QQuickItem,'dagPayloadRecovery').property('value')=='Validerar hämtat block'
dag['dag_proofs']['payload_recovery'].update(phase='DOWNLOADING',partial_downloaded_bytes=2464462)
put();assert 'MiB /' not in root.findChild(QQuickItem,'dagPayloadRecovery').property('value')

dag['lan']['storage']={'enabled':True,'profile':'LinuxNode','restored':True,'records':3}
dag['lan_setup'].update(ephemeral_keys=False,new_pairing_after_restart=False)
put();assert root.findChild(QQuickItem,'dagNodeStorage').property('value')=='Profil LinuxNode · återläst'
assert root.property('primaryActionEnabled'),'A participant must not need coordinator UI or online peers to start its own worker'
js(root,'triggerPrimary()');assert events[-1]==('lan_dag_produce_start',{'duration_ms':60000,'transactions_per_block':1,'interval_ms':1000})
popup=root.findChild(QObject,'lanDagSetupPopup');assert popup is not None
assert popup.findChild(QQuickItem,'lanOwnProductionStart').isEnabled()
assert not popup.findChild(QQuickItem,'lanDagStressStart').isEnabled()
dag['dag_production'].update(state='RUNNING',worker_active=True,can_start=False,selected=True,duration_ms=60000,
 production={'basis':'LOCAL_OWN_PRODUCTION_NOT_NETWORK_CAPACITY','state':'RUNNING','blocks':3,'transactions':96,'elapsed_ms':1000,'bps':3,'tps':96})
put();assert root.property('primaryActionEnabled')
assert root.property('liveLabel')=='Egen nod · RUNNING'
assert js(root,'productionRate("tps")')=='96.0'
js(root,'triggerPrimary()');assert events[-1]==('lan_dag_produce_stop',{})
assert not popup.findChild(QQuickItem,'lanOwnProductionStart').isEnabled()
assert popup.findChild(QQuickItem,'lanOwnProductionStop').isEnabled()
dag['observation']={'read_only':True,'source':'LOCAL_CLI','node_label':'Linux','stale':False};put()
before=len(events);js(root,'triggerPrimary()');js(root,'run("lan_dag_produce_stop",{})')
js(popup,'run("lan_dag_produce_stop",{})');assert len(events)==before
assert not root.property('primaryActionEnabled')
assert not popup.findChild(QQuickItem,'lanOwnProductionStop').isEnabled()
assert '96.0 TX/s' in popup.findChild(QQuickItem,'lanOwnProductionStatus').property('text')
dag.pop('observation');dag['lan']['participation'].update(role='replica',producer=False,replica=True,local_producer_count=0,eligible_network_producers=4)
dag['producers']=[{'index':i,'producer_enabled':i<4,'proposals':0,'transactions':0} for i in range(6)]
dag['dag_production'].update(enabled=False,can_start=False,worker_active=False,selected=False,state='IDLE')
put();assert root.property('participationLabel')=='Replika · full verifiering'
assert root.property('eligibleProducerCount')==4 and root.property('localProducerCount')==0
assert js(root,'producerRows.length')==4
assert not root.property('primaryActionEnabled') and root.property('primaryActionText')=='Replika'
assert not popup.findChild(QQuickItem,'lanOwnProductionStart').isEnabled()
before=len(events);js(root,'triggerPrimary()');assert len(events)==before
root.deleteLater();engine.deleteLater();app.processEvents();assert not warnings,warnings
print('PASS')
'''
        with tempfile.TemporaryDirectory(prefix='gg-owned-node-qml-') as directory:
            env=dict(os.environ,QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software',QT_QUICK_CONTROLS_STYLE='Basic')
            result=subprocess.run([sys.executable,'-X','utf8','-B','-c',script,directory],cwd=ROOT,env=env,
                capture_output=True,text=True,encoding='utf-8',timeout=25)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(result.stdout.strip(),'PASS')


if __name__=='__main__':unittest.main()
