"""Following actual fixture headers must not steal a transfer field's focus.

This is a small software-only focus regression, not a throughput benchmark or
network simulation. It starts no node and uses no user application or wallet.
"""
from pathlib import Path
import hashlib,json,os,subprocess,sys,tempfile,unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def fixture(directory):
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine,QQmlExpression,qmlContext
    from PySide6.QtQuick import QQuickItem
    from backend.gg_block_graph import BlockHistory
    app=QGuiApplication([])
    engine=QQmlApplicationEngine();warnings=[]
    engine.warnings.connect(lambda rows:warnings.extend(row.toString() for row in rows))
    source='''import QtQuick
import QtQuick.Controls
import COMPONENTS
ApplicationWindow {
 id: shell; width:480;height:220;visible:true
 property string packet:''
 onPacketChanged:if(packet)graph.graph=JSON.parse(packet)
 TextField {id:amount;objectName:'transferAmount';x:10;y:10;width:200;text:'1.25'}
 BlockRelationsGraph {id:graph;objectName:'focusGraph';x:10;y:55;width:460;height:150;animateChanges:false}
}'''.replace('COMPONENTS',json.dumps((ROOT/'qml/components').as_uri()))
    engine.loadData(source.encode(),QUrl.fromLocalFile(str(directory/'focus.qml')))
    assert engine.rootObjects(),warnings
    window=engine.rootObjects()[0]
    amount=window.findChild(QQuickItem,'transferAmount')
    graph=window.findChild(QQuickItem,'focusGraph')
    assert amount is not None and graph is not None
    history=BlockHistory('Owned focus fixture');history.reset('focus-fixture')
    def identifier(height):return hashlib.sha256(('focus-fixture-'+str(height)).encode()).hexdigest()
    def add(height):
        row={'height':height,'hash':identifier(height),'parent_hash':identifier(height-1) if height else '',
             'timestamp':1700000000+height,'transaction_count':0}
        history.ingest([row],height,row['hash'])
        body=history.snapshot();body['metrics']['bps']=75
        window.setProperty('packet',json.dumps(body));app.processEvents();app.processEvents()
    try:
        for height in range(16):add(height)
        amount.forceActiveFocus();app.processEvents()
        assert window.activeFocusItem() is amount
        old_selection=graph.property('selectedHash')
        for height in range(16,36):
            add(height)
            assert window.activeFocusItem() is amount,('Follow-tip stole transfer focus',height)
            assert amount.property('text')=='1.25'
        assert graph.property('selectedHash')!=old_selection,'Fixture must follow genuinely new source headers'
        selected=identifier(28)
        expression=QQmlExpression(qmlContext(graph),graph,'selectBlock('+json.dumps(selected)+')')
        expression.evaluate();assert not expression.hasError(),expression.error().toString()
        app.processEvents()
        focused=window.activeFocusItem()
        assert focused is not None and focused.property('blockHash')==selected,'Explicit block selection must retain keyboard navigation'
        assert not warnings,warnings
        print(json.dumps({'status':'PASS','software_only':True,'known_fixture_headers':36,
                          'new_header_updates_with_form_focus_retained':20,
                          'typed_amount_preserved':True,'explicit_block_selection_still_focuses':True,
                          'node_started':False,'warnings':0}))
    finally:
        window.close();engine.deleteLater();app.processEvents()


class BlockGraphFocusTests(unittest.TestCase):
    def test_follow_tip_keeps_typed_transfer_field_focus(self):
        with tempfile.TemporaryDirectory(prefix='gg-block-focus-') as temporary:
            target=Path(temporary)
            env=dict(os.environ,QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software',
                     QT_QUICK_CONTROLS_STYLE='Basic',GG_DESKTOP_STATE_ROOT=str(target/'state'),
                     GG_DESKTOP_DATA_ROOT=str(target/'data'))
            result=subprocess.run([sys.executable,'-X','utf8','-B',str(Path(__file__).resolve()),'--fixture',temporary],
                                   cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',timeout=12)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            print(result.stdout.strip())


if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--fixture':fixture(Path(sys.argv[2]))
    else:unittest.main()
