"""Actual offscreen source2 graph projection; no active-app screen capture."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]


class SegmentedOriginalGraphUiTests(unittest.TestCase):
    def test_actual_graph_renders_only_authenticated_originals_and_preserves_large_rank_and_sequence(self):
        script=r'''
import json,sys
from pathlib import Path
from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlEngine,QQmlComponent,QQmlExpression,qmlContext
from PySide6.QtQuick import QQuickWindow,QQuickItem
app=QGuiApplication([]);engine=QQmlEngine();warnings=[]
engine.warnings.connect(lambda rows:warnings.extend(row.toString() for row in rows))
component=QQmlComponent(engine)
component.setData(('import QtQuick\nimport '+json.dumps((Path.cwd()/'qml/components').as_uri())+'\nBlockRelationsGraph {width:1000;height:210;animateChanges:false}').encode(),QUrl.fromLocalFile(str(Path(sys.argv[1])/'fixture.qml')))
assert component.isReady(),[row.toString() for row in component.errors()]
root=component.create();assert root is not None
window=QQuickWindow();root.setParentItem(window.contentItem())
def js(code):
 expr=QQmlExpression(qmlContext(root),root,code);value=expr.evaluate();assert not expr.hasError(),expr.error().toString();return value[0] if isinstance(value,tuple) else value
def update(graph):
 js('graph='+json.dumps(graph));app.processEvents();js('refresh()');app.processEvents()
first={'hash':'a'*64,'rank':'9007199254740993','height':'9007199254740993','layout_rank':0,'admission_index':0,
 'producer_sequence':'9007199254740993','proposer_index':0,'transaction_count':5000,'canonical_index':'9007199254740993',
 'certificate_height':'9007199254740994','parent_hashes':['d'*64],'signature_verified':True,'canonical_membership_verified':True,'payload_authenticated':True,'state':'SDK_CERTIFIED'}
second={**first,'hash':'b'*64,'rank':'9007199254740994','height':'9007199254740994','layout_rank':1,'admission_index':1,
 'producer_sequence':'9007199254740994','canonical_index':'9007199254740994','parent_hashes':['a'*64,'e'*64]}
graph={'topology':'CERTIFIED_ORIGINAL_DAG_WINDOW','producer_count':6,'blocks':[first,second],
 'producer_identities':[{'index':0,'display_name':'Termux · 1'}],
 'edges':[{'from':'a'*64,'to':'b'*64},{'from':'e'*64,'to':'b'*64}]}
update(graph)
assert root.property('certifiedWindow') is True and root.property('dagMode') is True
assert root.property('shownCount')==2 and root.property('edgeCount')==1
assert js('lookup("'+first['hash']+'").rank_text')=='9007199254740993'
assert js('rankLabel(1)')=='9007199254740994'
assert js('_nodeData["'+first['hash']+'"].producerSequenceText')=='9007199254740993'
assert js('lookup("'+'e'*64+'")===null')
js('selectBlock("'+first['hash']+'")');app.processEvents()
texts=js('JSON.stringify(_rows.map(function(r){return r.rank_text}))');assert '9007199254740993' in texts
graph['blocks'][1]['payload_authenticated']=False;update(graph)
assert root.property('shownCount')==1 and root.property('edgeCount')==0
assert not warnings,warnings
root.setParentItem(None);root.deleteLater();window.deleteLater();engine.deleteLater();app.processEvents()
print('PASS')
'''
        with tempfile.TemporaryDirectory(prefix='gg-source2-graph-') as directory:
            result=subprocess.run([sys.executable,'-X','utf8','-B','-c',script,directory],cwd=ROOT,
                env=dict(os.environ,QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software',QT_QUICK_CONTROLS_STYLE='Basic'),
                capture_output=True,text=True,encoding='utf-8',timeout=25)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr);self.assertEqual(result.stdout.strip(),'PASS')


if __name__=='__main__':unittest.main()
