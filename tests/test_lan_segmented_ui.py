"""Actual offscreen QML and CLI projections, separate from SDK quorum tests."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from backend.terminal_cli import foreground_summary

ROOT=Path(__file__).resolve().parents[1]


class SegmentedUiTests(unittest.TestCase):
    def test_cli_keeps_exact_certified_counters_and_does_not_claim_local_replay(self):
        body={'mode':'SEGMENTED_SDK_CERTIFIED_VIEW','lan':{'state':'READY','participation':{'role':'producer'}},
            'certified_blocks':'9007199254740993','certified_transactions':'9223372036854775807','local_full_history_replayed':False}
        result=foreground_summary('lan.resume',body)['segmented']
        self.assertEqual(result['certified_blocks'],body['certified_blocks']);self.assertEqual(result['certified_transactions'],body['certified_transactions'])
        self.assertFalse(result['client_full_history_replayed'])
        body['certified_transactions']='9223372036854775808'
        self.assertIsNone(foreground_summary('lan.resume',body)['segmented']['certified_transactions'])

    def test_actual_qml_names_real_creator_and_keeps_membership_positions_separate_from_parent_links(self):
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
dag={'state':'CERTIFIED','mode':'SEGMENTED_SDK_CERTIFIED_VIEW','producer_count':6,'canonical_finalized':'3','certified_blocks':'3','certified_transactions':'5002',
 'blocks_admitted':None,'transactions_validated':None,'local_full_history_replayed':False,
 'observation':{'source':'LOCAL_CLI','read_only':True},'lan_setup':{'active':True},
 'lan':{'state':'READY','label':'Linux','participation':{'producer':True,'replica':False,'light_client':False,'role':'producer'},
 'producer_identities':[{'index':0,'display_name':'Termux · 1','local':False},{'index':2,'display_name':'Linux · 1','local':True}]},
 'producers':[{'index':0,'proposals':'2','transactions':'5001','certified_sequence':'2'}],
 'dag_proofs':{'source':'AUTHENTICATED_LAN_SEGMENTED_SDK_PROOFS','state':'CERTIFIED','canonical_finality':True,
 'dag_segmented_commitment':{'epoch':'3'},'proven_blocks':[{'hash':'b'*64,'index':1,'global_index':'3','producer_index':0,'sequence':'2','transactions':1}]},
 'dag_consensus':{'state':'CERTIFIED'},'block_graph':{'topology':'CERTIFIED_ACTIVE_SEGMENT_MEMBERSHIP','producer_count':6,'blocks':[],'edges':[]},
 'dag_production':{'supported':True,'state':'IDLE','worker_active':False,'enabled':True,'can_start':True},
 'dag_stress':{'enabled':True,'supported':False},'live':{},'preview':{},'admission':{},'limits':{}}
js('state='+json.dumps({'parallel_dag':dag,'ui_operation':{}}));app.processEvents()
assert root.property('segmentedSource') is True and root.property('lightOnly') is False
assert root.property('membershipOnly') is True and root.property('canAct') is False
assert js('metricAt(0).value')=='3' and js('metricAt(1).value')=='5002'
assert js('metricAt(1).name')=='SDK-VALDA DAG-TX' and js('metricAt(2).value')=='3'
assert root.property('participationLabel')=='Producent · SDK-bevis'
assert root.findChild(QQuickItem,'dagCanonicalFinality').property('value')=='SDK-certifierat tillstånd'
assert root.findChild(QQuickItem,'dagProposalsList').property('count')==1
assert js('proofRows[0].canonical_index')=='3'
assert js('producerName(proofRows[0].proposer_index)')=='Termux · 1'
assert js('producerRows[0].sequence')=='2'
assert js('proofRows[0].parent_hashes===undefined') and js('graph.edges.length')==0
assert 'originalblocken' in root.findChild(QQuickItem,'dagSparseProofScope').property('text')
assert js('number("9007199254740993")')=='9007199254740993'
assert js('number("9223372036854775807")')=='9223372036854775807'
assert js('number("9223372036854775808")')=='—'
dag['lan']['participation'].update(producer=False,role='replica')
js('state='+json.dumps({'parallel_dag':dag,'ui_operation':{}}));app.processEvents()
assert root.property('primaryActionText')=='Observatör'
assert root.property('participationLabel')=='Observatör · SDK-bevis'
assert root.property('primaryActionEnabled') is False
assert not warnings,warnings
root.setParentItem(None);root.deleteLater();window.deleteLater();engine.deleteLater();app.processEvents()
print('PASS')
'''
        with tempfile.TemporaryDirectory(prefix='gg-segmented-ui-') as directory:
            result=subprocess.run([sys.executable,'-X','utf8','-B','-c',script,directory],cwd=ROOT,
                env=dict(os.environ,QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software',QT_QUICK_CONTROLS_STYLE='Basic'),
                capture_output=True,text=True,encoding='utf-8',timeout=25)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr);self.assertEqual(result.stdout.strip(),'PASS')


if __name__=='__main__':unittest.main()
