"""Real popup diagnostics/export checks, offscreen with no LAN runtime."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
import json,sys,time
from pathlib import Path
from PySide6.QtCore import QUrl
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
root.actionRequested.connect(lambda name,args:actions.append(name))
def js(code):
    expression=QQmlExpression(qmlContext(root),root,code);value=expression.evaluate()
    assert not expression.hasError(),expression.error().toString()
    return value[0] if isinstance(value,tuple) else value
def find(name):
    item=root.findChild(QQuickItem,name);assert item is not None,name
    return item
def text(name):return find(name).property('text')
def result():return json.loads(js('JSON.stringify(stressResultDocument())'))
def snapshot():
    return {'lan':{'state':'READY','transport':{'state':'ACTIVE','exhausted_reason':'',
        'connections_admitted':20,'active_handlers':0,
        'counters':{'failures':1,'expected_closures':2,'successes':12,
            'admission_drops':{'RATE':0,'HANDLERS':0,'SESSION':0,'BYTES':0}},'history':[]}},
        'lan_setup':{'active':True,'coordinator':True},
        'test_tokens':{'enabled':False,'decimals':6},
        'dag_stress':{'supported':True,'enabled':True,'local_opt_in':True,'role':'COORDINATOR',
            'can_start':True,'state':'COMPLETE','duration_ms':10000,'transactions_per_block':8,
            'interval_ms':1000,'blocks':48,'transactions':384,'elapsed_ms':9336,
            'all_peers_synced':True,'acknowledged_blocks':48,'acknowledged_transactions':384,
            'acknowledged_bps':5.141,'acknowledged_tps':41.13,'acknowledgement_basis':'STOP_AND_STATUS_OBSERVATIONS',
            'stop_reason':'DURATION','last_error':'','participants':[
                {'label':name,'state':'COMPLETE','opted_in':True} for name in ('Linux','Termux','GG Windows')],
            'limits':{'min_duration_ms':1000,'max_duration_ms':60000,'max_tx_per_block':32,
                'min_interval_ms':100,'max_interval_ms':60000}}}
def put(body):js('state='+json.dumps(body))
'''
CLEANUP = r'''
root.deleteLater();engine.deleteLater();app.processEvents()
assert not warnings,warnings
print(json.dumps({'status':'PASS','native_window_shown':False}))
'''


class LanTransportUiTests(unittest.TestCase):
    def check_offscreen(self, assertions):
        environment = dict(os.environ, QT_QPA_PLATFORM='offscreen',
            QT_QUICK_BACKEND='software', QT_QUICK_CONTROLS_STYLE='Basic')
        with tempfile.TemporaryDirectory(prefix='gg-lan-transport-ui-') as temporary:
            checked = subprocess.run([sys.executable, '-X', 'utf8', '-B', '-c',
                HARNESS + assertions + CLEANUP, temporary], cwd=ROOT, env=environment,
                capture_output=True, text=True, encoding='utf-8', timeout=20)
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertEqual(json.loads(checked.stdout)['status'], 'PASS')

    def test_sticky_failure_is_historical_and_expected_stop_does_not_claim_recovery(self):
        self.check_offscreen(r'''
body=snapshot();now=time.time()
body['lan'].update(last_error='GG_LAN_CONNECTION_RESET',last_error_at=now-125,
    last_error_details={'operation':'PAGE','stage':'RECEIVE','error_class':'ConnectionResetError'})
body['lan']['transport']['history']=[
    {'at':now-125,'operation':'PAGE','stage':'RECEIVE','code':'GG_LAN_CONNECTION_RESET',
        'peer_label':'Linux','expected':False,'reason':''},
    {'at':now-2,'operation':'INCOMING','stage':'RECEIVE','code':'GG_LAN_EOF',
        'peer_label':'Termux','expected':True,'reason':''}]
put(body)
assert 'Senast registrerat transportfel (2 min sedan): GG_LAN_CONNECTION_RESET' in text('lanSetupError')
assert 'Operation: PAGE' in text('lanSetupError')
assert 'Registrerat: fel 1' in text('lanTransportStatus')
assert 'väntade stängningar 2' in text('lanTransportStatus')
assert 'mottagning aktiv' in text('lanTransportStatus')
assert 'Registrerat fel · PAGE · RECEIVE · GG_LAN_CONNECTION_RESET · Linux' in text('lanTransportHistory')
assert 'Väntad stängning · INCOMING · RECEIVE · GG_LAN_EOF · Termux' in text('lanTransportHistory')
assert 'återställd' not in (text('lanTransportStatus')+text('lanTransportHistory'))
assert result()['transport_diagnostics']['last_failure']['code']=='GG_LAN_CONNECTION_RESET'
body['lan']['transport']['state']='STOPPED';put(body)
assert 'Transport · stoppad' in text('lanTransportStatus')
assert 'GG_LAN_CONNECTION_RESET' in text('lanSetupError')
del body['lan']['last_error_at'];put(body)
assert text('lanSetupError').startswith('Senast registrerat transportfel: GG_LAN_CONNECTION_RESET')
assert 'sedan' not in text('lanSetupError')
''')

    def test_exhausted_transport_blocks_new_trials_without_changing_success_or_disabled_features(self):
        self.check_offscreen(r'''
body=snapshot();put(body)
assert find('lanDagStressStart').isEnabled()
assert result()['failure']['reason']=='DURATION' and result()['failure']['code'] is None
assert result()['acknowledgement']['confirmed'] is True
for reason in ('SESSION','BYTES','FRAMES'):
    body['lan']['transport'].update(state='EXHAUSTED',exhausted_reason=reason)
    body['lan']['transport']['counters']['admission_drops']['SESSION']=3
    put(body)
    assert not find('lanDagStressStart').isEnabled()
    assert not find('lanCircleStart').isEnabled()
    js('run("lan_dag_stress_start",{});run("lan_circle_start",{})')
    assert actions==[]
    assert 'sessionsgräns nådd · '+reason in text('lanTransportStatus')
    assert 'SESSION 3' in text('lanTransportHistory')
    assert result()['state']=='COMPLETE' and result()['acknowledgement']['confirmed'] is True
    assert result()['failure']['reason']=='DURATION'
assert js('tokens.enabled') is False
assert text('lanDagStressStatus').startswith('DAG-prov · COMPLETE')
''')

    def test_export_keeps_exact_failure_and_ack_rules_but_excludes_untrusted_diagnostics(self):
        self.check_offscreen(r'''
body=snapshot();now=time.time();stress=body['dag_stress']
stress.update(state='TIME_BUDGET',all_peers_synced=False,last_error='GG_LAN_READ_DEADLINE',
    failure_phase='CONVERGENCE',last_error_details={'operation':'DAG_STRESS_STATUS','stage':'RECEIVE','error_class':'ValueError'})
transport=body['lan']['transport']
transport['history']=[{'at':now-i,'operation':'PAGE','stage':'RECEIVE','code':'GG_LAN_EOF',
    'peer_label':'Linux','expected':False,'reason':''} for i in range(40)]
put(body);exported=result()
assert exported['schema']=='gg.lan-dag-stress.result.v1'
assert exported['failure']=={'code':'GG_LAN_READ_DEADLINE','reason':'DURATION','phase':'CONVERGENCE',
    'transport':{'operation':'DAG_STRESS_STATUS','stage':'RECEIVE','error_class':'ValueError'}}
assert exported['acknowledgement']=={'confirmed':False,'basis':None,'blocks':None,'transactions':None,'bps':None,'tps':None}
assert len(exported['transport_diagnostics']['history'])==32
transport.update(exhausted_reason='PRIVATE_ENDPOINT_SENTINEL',connections_admitted=-1,active_handlers=5,
    endpoint='PRIVATE_ENDPOINT_SENTINEL',public_key='a'*64)
transport['counters'].update(failures='7',expected_closures=1.5,successes=2**53)
transport['counters']['admission_drops'].update(RATE=-1,HANDLERS='3')
transport['history']=[{'at':now,'operation':'PAGE\nPRIVATE_ENDPOINT_SENTINEL','stage':'<script>',
    'code':'GG_LAN_EOF','peer_label':'PRIVATE_ENDPOINT_SENTINEL:1234','expected':'false',
    'reason':'PRIVATE_ENDPOINT_SENTINEL','private_key':'PRIVATE_KEY_SENTINEL'},
    {'at':now,'operation':'GET','stage':'RECEIVE','code':'GG_'+'A'*64,'peer_label':'a'*64,'expected':False},
    {'at':-1,'operation':'GET','stage':'RECEIVE','code':'GG_LAN_EOF','peer_label':'Linux','expected':False},
    {'at':4102444801,'operation':'GET','stage':'RECEIVE','code':'GG_LAN_EOF','peer_label':'Linux','expected':False}]
body['lan'].update(last_error='GG_'+'A'*64,last_error_at=-1,
    last_error_details={'operation':'PRIVATE_ENDPOINT_SENTINEL','stage':'<script>','error_class':'PRIVATE_KEY_SENTINEL'})
stress['last_error']='GG_LAN_EOF\nPRIVATE_KEY_SENTINEL'
put(body)
js('state.lan.transport.counters.admission_drops.BYTES=Infinity')
exported=result();diagnostics=exported['transport_diagnostics']
assert 'A'*64 not in text('lanSetupError')
assert 'Okänd orsak' in text('lanSetupError')
assert exported['failure']['code'] is None
assert diagnostics['exhausted_reason'] is None
assert diagnostics['connections_admitted'] is None and diagnostics['active_handlers'] is None
assert diagnostics['counters']['failures'] is None and diagnostics['counters']['expected_closures'] is None
assert diagnostics['counters']['successes'] is None
assert diagnostics['counters']['admission_drops']['RATE'] is None
assert diagnostics['counters']['admission_drops']['HANDLERS'] is None
assert diagnostics['counters']['admission_drops']['BYTES'] is None
assert diagnostics['last_failure']['code'] is None and diagnostics['last_failure']['at'] is None
assert len(diagnostics['history'])==1
assert diagnostics['history'][0]=={'at':now,'operation':None,'stage':None,'code':'GG_LAN_EOF',
    'peer_label':'','expected':None,'reason':None}
serialized=json.dumps(exported)
for forbidden in ('PRIVATE_ENDPOINT_SENTINEL','PRIVATE_KEY_SENTINEL','<script>','a'*64,'A'*64,'public_key','endpoint','private_key'):
    assert forbidden not in serialized,forbidden
body['lan'].pop('transport');put(body)
assert result()['transport_diagnostics'] is None
''')


if __name__ == '__main__':
    unittest.main()
