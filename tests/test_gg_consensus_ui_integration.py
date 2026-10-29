"""Actual QML -> asynchronous shared service -> four disposable Comet nodes."""
import json
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]


def fixture(directory):
    sys.path.insert(0,str(ROOT))
    import math
    import time
    from PySide6.QtCore import QObject,QPointF,Qt,QTimer,QUrl,Signal,Slot
    from PySide6.QtGui import QGuiApplication,QFont,QFontDatabase
    from PySide6.QtQml import QQmlApplicationEngine,QQmlExpression,qmlContext
    from PySide6.QtQuick import QQuickItem
    from PySide6.QtTest import QTest,QSignalSpy
    from backend import gg_consensus as node,omni_service
    from backend.crypto_ui_runtime import CryptoUiRuntime
    from startup import run_event_loop
    if not node.available():print(json.dumps({'status':'SKIP'}));return
    app=QGuiApplication([]);app.setQuitOnLastWindowClosed(False)
    if os.name=='nt':
        for filename in ('consola.ttf','consolab.ttf','seguisym.ttf'):
            QFontDatabase.addApplicationFont(str(Path(os.environ['SystemRoot'])/'Fonts'/filename))
    family='Consolas' if os.name=='nt' else 'DejaVu Sans Mono'
    QFont.insertSubstitution('monospace',family);app.setFont(QFont(family))
    class Host(QObject):
        omniStatusUpdated=Signal(str)
        def __init__(self):
            super().__init__();self.calls=[];self.copied=[]
            self.runtime=CryptoUiRuntime(self,snapshot=omni_service.snapshot,ttl=1.5)
            self.runtime.updated.connect(self.omniStatusUpdated)
        @Slot(result=str)
        def omniStatus(self):return self.runtime.snapshot()
        @Slot(str,str,result=str)
        def omniAction(self,name,raw):
            self.calls.append((name,json.loads(raw)))
            return self.runtime.submit(name,lambda:omni_service.action(name,raw))
        @Slot(str,result=str)
        def tmogCopy(self,value):self.copied.append(value);return value
    host=Host();engine=QQmlApplicationEngine();warnings=[]
    engine.warnings.connect(lambda rows:warnings.extend(r.toString() for r in rows))
    engine.rootContext().setContextProperty('fixtureHost',host)
    qml='''import QtQuick
import QtQuick.Controls
import COMPONENTS
ApplicationWindow {width:970;height:620;visible:true;color:'#111111'
OmniSurface {objectName:'hub';anchors.fill:parent;embedded:true;page:'CONSENSUS';surfaceHost:fixtureHost}}
'''.replace('COMPONENTS',json.dumps((ROOT/'qml/components').as_uri()))
    source=directory/'fixture.qml';source.write_text(qml,encoding='utf-8');engine.load(QUrl.fromLocalFile(str(source)))
    assert engine.rootObjects(),warnings
    window=engine.rootObjects()[0];window.requestActivate();hub=window.findChild(QQuickItem,'hub');children=[]
    def js(item,expression):
        query=QQmlExpression(qmlContext(item),item,expression);result=query.evaluate()
        assert not query.hasError(),query.error().toString()
        return result[0] if isinstance(result,tuple) else result
    def state():return json.loads(js(hub,'JSON.stringify(state.consensus || {})'))
    def visual_items(item):
        yield item
        for child in item.childItems():yield from visual_items(child)
    def named(name):
        # Repeater delegates have visual parents but can sit outside the
        # window's QObject ownership tree. Resolve the actual rendered control.
        matches=[item for item in visual_items(window.contentItem()) if item.objectName()==name]
        item=next((item for item in matches if item.isVisible()),matches[0] if matches else None)
        assert item is not None,name;return item
    def diagnostics(name):
        item=named(name);ancestors=[];current=item
        while current:
            ancestors.append({'name':current.objectName(),'type':current.metaObject().className(),
                'visible':current.isVisible(),'enabled':current.isEnabled(),'x':current.x(),'y':current.y(),
                'width':current.width(),'height':current.height(),'clip':current.clip()})
            current=current.parentItem()
        layout=named('consensusMainScroll');dashboard=named('consensusDashboard')
        result={'control':name,'ancestors':ancestors,'layout':{key:layout.property(key) for key in ('page','compact','split','stacked','formFocused')},
                'dashboard':{key:dashboard.property(key) for key in ('running','busy','canAct','editable','proofReady','quorumReady','hasReview')},
                'operation':str(js(hub,'JSON.stringify(operation)')),'state':state().get('state')}
        output=ROOT/'.runtime/network-v12-e2e';output.mkdir(parents=True,exist_ok=True)
        window.grabWindow().save(str(output/('consensus-'+name+'.png')))
        (output/('consensus-'+name+'.json')).write_text(json.dumps(result,indent=2),encoding='utf-8')
        return json.dumps(result)
    def settle():
        # Positioners receive service snapshots asynchronously. Complete native
        # polish before reading contentHeight or mapping a descendant's center.
        app.processEvents();window.grabWindow();QTest.qWait(10)
        time.sleep(.01);app.processEvents();window.grabWindow()
    def wait(predicate,label,timeout=20):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            settle()
            if predicate():return
        raise AssertionError(label+' '+str(state().get('state'))+' '+str(js(hub,'JSON.stringify(operation)'))+' '+str(warnings))
    def scroll_to(item):
        settle()
        parent=item.parentItem()
        while parent:
            if parent.objectName() in {'consensusMainScroll','consensusTelemetryScroll'} and not parent.property('noPageScroll'):
                point=item.mapToItem(parent.property('contentItem'),QPointF(item.width()/2,item.height()/2))
                assert math.isfinite(point.y()),'NONFINITE_SCROLL_TARGET '+item.objectName()
                maximum=max(0,float(parent.property('contentHeight'))-parent.height())
                parent.setProperty('contentY',max(0,min(maximum,point.y()-parent.height()/2)))
                settle()
            parent=parent.parentItem()
    def click(name):
        settle();item=named(name);assert item.isVisible() and item.isEnabled(),diagnostics(name)
        scroll_to(item);settle()
        point=item.mapToScene(QPointF(item.width()/2,item.height()/2))
        assert all(math.isfinite(value) for value in (point.x(),point.y())),'NONFINITE_CONTROL '+name
        assert 0<=point.x()<window.width() and 0<=point.y()<window.height(),'CONTROL_OUTSIDE_VIEWPORT '+name+' '+repr((point.x(),point.y(),window.width(),window.height()))
        parent=item.parentItem()
        while parent:
            if parent.clip():
                local=item.mapToItem(parent,QPointF(item.width()/2,item.height()/2))
                assert 0<=local.x()<parent.width() and 0<=local.y()<parent.height(),'CONTROL_CLIPPED '+name+' '+parent.objectName()
            parent=parent.parentItem()
        spy=QSignalSpy(item.clicked) if name.endswith('TransferTab') else None
        QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,point.toPoint());settle()
        if spy is not None:
            assert spy.count()==1,'TRANSFER_TAB_MOUSE_NOT_DELIVERED '+diagnostics(name)
            assert named('consensusMainScroll').property('page')==1,'TRANSFER_PAGE_NOT_SELECTED '+diagnostics(name)
    def choose(name,index):
        click(name);QTest.keyClick(window,Qt.Key_Home)
        for _ in range(index):QTest.keyClick(window,Qt.Key_Down)
        QTest.keyClick(window,Qt.Key_Return);settle()
        assert named(name).property('currentIndex')==index
    try:
        wait(lambda:state().get('state')=='STOPPED','initial snapshot')
        click('consensusStart');wait(lambda:not js(hub,'busy') and state().get('state')=='RUNNING','cluster started',35)
        children=[n['process'] for n in node._nodes]
        assert len(children)==4 and state()['proof']['verified']
        assert named('consensusMainScroll').property('noPageScroll') is True
        if not named('consensusMainScroll').property('stacked'):click('consensusTransferTab')
        choose('consensusSender',0);choose('consensusRecipient',1)
        click('consensusAmount');QTest.keyClick(window,Qt.Key_A,Qt.ControlModifier)
        for ch in '1.000001':QTest.keyClick(window,Qt.Key(ord(ch)))
        click('consensusPrepare');wait(lambda:not js(hub,'busy') and bool(state().get('review')),'review')
        draft=state()['review'];assert draft['amount']=='1.000001'
        assert not named('consensusAmount').isEnabled() and not named('consensusSender').isEnabled()
        click('consensusSend');wait(lambda:not js(hub,'busy') and state()['transactions'][0]['state']=='FINALIZED','execution verified')
        tx=state()['transactions'][0]
        assert tx['execution_verified'] and tx['certificate_height']==tx['height']+1
        assert state()['accounts'][0]['quantity']=='249998.999999' and state()['accounts'][1]['quantity']=='250001.000001'
        assert host.calls[-1]==('consensus_send',{'id':draft['id'],'review_digest':draft['review_digest']})
        assert named('consensusExportProof').isVisible(),'Desktop rail must expose proof controls directly'
        click('consensusExportProof');wait(lambda:not js(hub,'busy') and js(hub,'!!state.consensus_sample'),'public packet')
        click('consensusCopyProof');packet=json.loads(host.copied[-1]);assert packet['state']['height']>=2
        assert node._verify(packet)['account_proof_verified']
        chain=state()['chain_id'];click('consensusTestnetMode')
        wait(lambda:hub.property('page')=='TESTNET','EVM navigation')
        click('testnetValidatorMode');wait(lambda:hub.property('page')=='CONSENSUS','return to consensus')
        assert state()['chain_id']==chain and all(p.poll() is None for p in children)
        click('consensusStop');wait(lambda:not js(hub,'busy') and state().get('state')=='STOPPED','cluster stopped')
        assert all(p.poll() is not None for p in children)
        assert not warnings,warnings
        print(json.dumps({'status':'PASS','real_qml':True,'async_service':True,'validators':4,'exact_review':True,
                          'execution_verified':True,'public_proof_copy_verified':True,'navigation_preserves_session':True,
                          'owned_nodes_stopped':True,'warnings':0}))
    finally:
        host.runtime.close();node.stop()
        assert all(p.poll() is not None for p in children)
        until=time.monotonic()+3
        while host.runtime._running and time.monotonic()<until:settle()
        QTimer.singleShot(0,app.quit);assert run_event_loop(app,engine)==0


class ConsensusUiIntegration(unittest.TestCase):
    def test_real_qml_certified_transfer_and_public_proof(self):
        with tempfile.TemporaryDirectory(prefix='gg-consensus-e2e-') as temporary:
            env=os.environ.copy();env.update(QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software',QT_QUICK_CONTROLS_STYLE='Basic',
                GG_DESKTOP_STATE_ROOT=str(Path(temporary)/'state'),GG_DESKTOP_DATA_ROOT=str(Path(temporary)/'data'))
            result=subprocess.run([sys.executable,'-X','utf8','-B',str(Path(__file__).resolve()),'--fixture',temporary],
                cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',timeout=100)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            report=[json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')][-1]
            if report['status']=='SKIP':self.skipTest('Optional native consensus engine not installed')
            self.assertEqual(report['status'],'PASS');print(json.dumps(report))


class OwnedReadyPipeTests(unittest.TestCase):
    """Untrusted/malformed pipe data cannot substitute another process or node."""
    def setUp(self):
        from backend import gg_consensus
        self.node=gg_consensus
        self.expected={'schema':'gg.consensus.ready.v1','chain_id':'ggnet:'+'a'*24,
                       'node_id':'b'*40,'pid':1,'rpc_port':51001,'p2p_port':51002}

    def read(self,raw,replace_process=False):
        stream=io.BytesIO(raw);process=SimpleNamespace(stdout=stream)
        node={'process':object() if replace_process else process,'_ready':None}
        self.node._read_ready(node,process,self.expected)
        self.assertTrue(stream.closed)
        return node,process

    def test_accepts_only_exact_public_attestation_from_current_child(self):
        node,process=self.read(json.dumps(self.expected).encode()+b'\n')
        self.assertIs(node['_ready']['process'],process)
        stale,_=self.read(json.dumps(self.expected).encode()+b'\n',replace_process=True)
        self.assertIsNone(stale['_ready'])

    def test_rejects_wrong_identity_ports_schema_and_additional_fields(self):
        for key,value in [('chain_id','ggnet:'+'c'*24),('node_id','d'*40),('pid',2),
                          ('rpc_port',51003),('p2p_port',51004),('schema','foreign'),('extra','unexpected'),
                          ('pid',True),('rpc_port','51001')]:
            with self.subTest(key=key,value=value):
                changed={**self.expected,key:value}
                node,_=self.read(json.dumps(changed).encode()+b'\n')
                self.assertIsNone(node['_ready'])

    def test_rejects_truncated_oversize_invalid_and_duplicate_json(self):
        encoded=json.dumps(self.expected,separators=(',',':')).encode()
        duplicate=encoded.replace(b'"pid":1',b'"pid":2,"pid":1')
        for raw in [b'',encoded,b'not-json\n',b'[]\n',b'null\n',encoded+b'{}\n',
                    b' '*1025+b'\n',b'\xff\n',duplicate+b'\n']:
            with self.subTest(case='duplicate' if raw==duplicate+b'\n' else 'malformed'):
                node,_=self.read(raw)
                self.assertIsNone(node['_ready'])

    def test_pipe_error_closes_stream_without_marking_ready(self):
        class Broken(io.BytesIO):
            def readline(self,*args):raise OSError('synthetic pipe failure')
        stream=Broken();process=SimpleNamespace(stdout=stream);node={'process':process,'_ready':None}
        self.node._read_ready(node,process,self.expected)
        self.assertTrue(stream.closed);self.assertIsNone(node['_ready'])


if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--fixture':fixture(Path(sys.argv[2]))
    else:unittest.main()
