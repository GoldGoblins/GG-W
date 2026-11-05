"""Actual offscreen QML: CLI certificates are shown without inventing block finality."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]


class ValidatorUiTests(unittest.TestCase):
    def test_cli_certificate_identity_readonly_and_explicit_genesis_binding(self):
        script=r'''
import json,sys
from pathlib import Path
from PySide6.QtCore import QUrl,QMetaObject,Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlEngine,QQmlComponent,QQmlExpression,qmlContext
from PySide6.QtQuick import QQuickItem,QQuickWindow
app=QGuiApplication([]);engine=QQmlEngine();warnings=[]
engine.warnings.connect(lambda rows:warnings.extend(row.toString() for row in rows))
component=QQmlComponent(engine)
component.setData(('import QtQuick\nimport '+json.dumps((Path.cwd()/'qml/components').as_uri())+'\nGGParallelDagDashboard {width:1250;height:820}').encode(),QUrl.fromLocalFile(str(Path(sys.argv[1])/'fixture.qml')))
assert component.isReady(),[row.toString() for row in component.errors()]
root=component.create();assert root is not None
window=QQuickWindow();root.setParentItem(window.contentItem())
def js(owner,code):
 expr=QQmlExpression(qmlContext(owner),owner,code);value=expr.evaluate();assert not expr.hasError(),expr.error().toString();return value[0] if isinstance(value,tuple) else value
def item(name):
 value=root.findChild(QQuickItem,name);assert value is not None,name;return value
members=[{'index':i,'label':label,'owner_label':owner,'local_owner':owner=='Linux','state':'RUNNING' if owner=='Linux' else 'UNOBSERVED'} for i,(label,owner) in enumerate([('Win1','Windows'),('Lin1','Linux'),('Win2','Windows'),('Lin2','Linux')])]
dag={'state':'RUNNING','lan_setup':{'active':True,'coordinator':False,'invites':[]},
 'lan':{'state':'READY','label':'Linux','connection_state':'CONNECTED','authenticated_peers':[]},
 'observation':{'source':'LOCAL_CLI','read_only':True,'stale':False},
 'dag_consensus':{'anchor_bound':True,'validator_count':4,'quorum_required':3,'own_running':2,
 'profiles':[{'profile':'Lin1'},{'profile':'Lin2'}],'members':members,'state':'WAITING_FOR_CERTIFICATE',
 'certificate_height':None,'certified_dag_blocks':None,'certified_dag_transactions':None},
 'block_graph':{'blocks':[],'metrics':{},'canonical_finalized':0},'live':{},'preview':{},'admission':{},'limits':{}}
def put():js(root,'state='+json.dumps({'parallel_dag':dag,'ui_operation':{}}));app.processEvents()
put()
assert 'Väntar' in item('dagConsensusCertificate').property('value')
assert 'Saknas' in item('dagConsensusCertifiedBlocks').property('value')
assert 'Lin1 · Linux · egen' in root.property('consensusMembers')
assert 'Win1 · Windows' in root.property('consensusMembers')
dag['dag_consensus'].update(state='CERTIFIED',certificate_height=27,certified_dag_blocks=1,certified_dag_transactions=5000);put()
assert item('dagConsensusCertificate').property('value')=='Höjd 27'
assert '5000' in item('dagConsensusCertifiedBlocks').property('value').replace(' ','').replace('\u00a0','')
assert dag['block_graph']['canonical_finalized']==0
popup=item('lanDagSetupPopup');js(popup,'open()');app.processEvents()
assert '27' in item('lanConsensusCertificateStatus').property('text')
assert not root.property('canAct')
events=[];popup.actionRequested.connect(lambda name,args:events.append(name))
js(popup,'run("lan_validator_start",{profile:"Lin1"})');assert events==[]
dag['observation']={};dag['lan']['state']='PAIRING';dag['lan_setup'].update(coordinator=True,allow_dag_transactions=True,validator_invite_count=4,
 invites=[{'allow_dag_transactions':True} for _ in range(3)])
dag['dag_consensus']={};put()
assert js(popup,'sessionOptions().enable_consensus===undefined')
item('lanConsensusOptIn').setProperty('checked',True)
assert js(popup,'sessionOptions().enable_consensus===true')
dag['lan_setup']['validator_invite_count']=3;put()
assert js(popup,'sessionOptions().enable_consensus===undefined')
assert not item('lanConsensusOptIn').property('enabled')
dag['dag_consensus'].update(anchor_bound=True,state='FAULT',validator_count=4,quorum_required=3);put()
assert item('dagConsensusCertificate').property('value')=='Verifieringsfel'
dag['lan_setup'].update(windows_profile_controls=True,ephemeral_keys=False);put()
item('lanValidatorProfile').setProperty('text','Desktop1');app.processEvents()
assert item('lanValidatorCreate').property('enabled')
QMetaObject.invokeMethod(item('lanValidatorCreate'),'clicked',Qt.DirectConnection)
assert events==['lan_validator_create']
dag['observation']={'source':'LOCAL_CLI','read_only':True};put()
assert not item('lanValidatorCreate').property('enabled')
js(popup,'run("lan_validator_create",{profile:"Desktop1"})');assert events==['lan_validator_create']
dag['dag_consensus']['state']='CERTIFIED'
dag['producer_count']=6
h0='a'*64;h1='b'*64
dag['block_graph'].update(topology='MULTIPARENT_DAG',source='LAN_SIGNED_PROPOSAL_DAG',producer_count=6,
 canonical_certificate_height=27,canonical_members=1,
 blocks=[{'hash':h0,'rank':0,'height':0,'parent_hashes':[],'state':'GENESIS','signature_verified':False,'proposer_index':-1},
         {'hash':h1,'rank':1,'height':1,'parent_hashes':[h0],'state':'ADMITTED_UNFINALIZED','signature_verified':True,'proposer_index':0,
          'producer_sequence':1,'admission_index':1,'transaction_count':5000}])
put();graph=item('dagBlockRelationsGraph')
assert js(graph,'lookup("'+h1+'").canonical_membership_verified===false')
assert item('dagCanonicalFinality').property('value')=='Kontrollpunkt krävs'
dag['canonical_finalized']=1
dag['block_graph']['blocks'][1].update(canonical_membership_verified=True,canonical_index=1);put()
assert js(graph,'lookup("'+h1+'").canonical_membership_verified===true')
assert item('dagCanonicalFinality').property('value')=='SDK-verifierat medlemskap'
dag['block_graph']['canonical_certificate_height']=0;put()
assert js(graph,'lookup("'+h1+'").canonical_membership_verified===false')
root.setParentItem(None);root.deleteLater();window.deleteLater();engine.deleteLater();app.processEvents()
assert not warnings,warnings
print('PASS')
'''
        with tempfile.TemporaryDirectory(prefix='gg-validator-ui-') as directory:
            result=subprocess.run([sys.executable,'-X','utf8','-B','-c',script,directory],cwd=ROOT,
                env=dict(os.environ,QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software',QT_QUICK_CONTROLS_STYLE='Basic'),
                capture_output=True,text=True,encoding='utf-8',timeout=25)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(result.stdout.strip(),'PASS')


if __name__=='__main__':unittest.main()
