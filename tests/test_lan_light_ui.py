"""Actual QML/CLI: a proof-only account must not masquerade as full replay."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from backend.terminal_cli import foreground_summary

ROOT=Path(__file__).resolve().parents[1]


class LightUiTests(unittest.TestCase):
    def test_cli_keeps_role_proof_scope_and_actual_canonical_count(self):
        body={'lan':{'state':'READY','participation':{'role':'light','producer':False,'replica':False,'light_client':True,
              'verification_scope':'SDK_CERTIFICATES_AND_RELEVANT_MEMBERSHIP'}},'dag_proofs':{'role':'light','state':'CERTIFIED'},
              'canonical_finalized':0,'certified_test_accounts':[{'display_name':'Termux · 1','balance_atomic':'1000005000','nonce':0,'verification_scope':'SDK_CERTIFIED_MEMBERSHIP'}]}
        result=foreground_summary('lan.resume',body)
        self.assertEqual(result['participation']['role'],'light');self.assertEqual(result['proofs']['state'],'CERTIFIED')
        self.assertEqual(result['certified_test_accounts'][0]['balance_atomic'],'1000005000')
        body['canonical_finalized']=35
        self.assertEqual(foreground_summary('lan.resume',body)['canonical_finalized'],35)

    def test_real_qml_separates_recent_membership_from_unfetched_block_payloads(self):
        script=r'''
import json,sys
from pathlib import Path
from PySide6.QtCore import QUrl
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
def js(code):
 expr=QQmlExpression(qmlContext(root),root,code);value=expr.evaluate();assert not expr.hasError(),expr.error().toString();return value[0] if isinstance(value,tuple) else value
account={'producer_index':0,'display_name':'Termux · 1','local':True,'balance_atomic':'1000005000','nonce':0,'verification_scope':'SDK_CERTIFIED_MEMBERSHIP'}
dag={'state':'RUNNING','producer_count':6,'canonical_finalized':0,'blocks_admitted':0,'transactions_validated':0,
 'observation':{'source':'LOCAL_CLI','read_only':True},'lan_setup':{'active':True},
 'lan':{'state':'READY','label':'Termux','participation':{'producer':False,'replica':False,'light_client':True,'role':'light'},
 'producer_identities':[{'index':0,'display_name':'Termux · 1','local':True}]},
 'dag_proofs':{'state':'CERTIFIED','role':'light','proven_blocks':[{'hash':'b'*64,'index':35,'producer_index':2,'sequence':34,'transactions':1}]},
 'certified_test_accounts':[account],'test_accounts':[account],
 'block_graph':{'topology':'MULTIPARENT_DAG','producer_count':6,'blocks':[],'metrics':{}},'live':{},'preview':{},'admission':{},'limits':{}}
js('state='+json.dumps({'parallel_dag':dag,'ui_operation':{}}));app.processEvents()
assert root.property('lightOnly') is True and root.property('canAct') is False
assert root.property('primaryActionText')=='Lättklient' and root.property('primaryActionEnabled') is False
assert root.property('participationLabel')=='Lättklient · SDK-bevis'
assert 'Lättklient' in root.property('notice')
assert 'SDK-verifierat medlemskap' in js('producerAccountText(0)')
assert root.findChild(QQuickItem,'dagCanonicalFinality').property('value')=='SDK-verifierat medlemskap'
assert '1000005000' in root.findChild(QQuickItem,'dagCertifiedAccount').property('value')
assert root.findChild(QQuickItem,'dagProposalsList').property('count')==1
assert js('proofRows[0].parent_hashes===undefined') and js('graph.blocks.length')==0
root.setParentItem(None);root.deleteLater();window.deleteLater();engine.deleteLater();app.processEvents()
assert not warnings,warnings
print('PASS')
'''
        with tempfile.TemporaryDirectory(prefix='gg-light-ui-') as directory:
            result=subprocess.run([sys.executable,'-X','utf8','-B','-c',script,directory],cwd=ROOT,
                env=dict(os.environ,QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software',QT_QUICK_CONTROLS_STYLE='Basic'),
                capture_output=True,text=True,encoding='utf-8',timeout=25)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(result.stdout.strip(),'PASS')


if __name__=='__main__':unittest.main()
