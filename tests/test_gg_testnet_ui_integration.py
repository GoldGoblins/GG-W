"""Real QML controls -> asynchronous OMNI -> owned disposable EVM node.

The child isolates application state/data, uses only newly generated development
accounts and stops its node before Qt teardown. The optional screenshots contain
only this ephemeral test session's public information.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PROJECT=Path(__file__).resolve().parents[1]


def fixture(directory: Path):
    sys.path.insert(0,str(PROJECT))
    import math
    import socket
    import time
    from PySide6.QtCore import QObject,QPointF,Qt,QTimer,QUrl,Signal,Slot
    from PySide6.QtGui import QFont,QFontDatabase,QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine,QQmlExpression,qmlContext
    from PySide6.QtQuick import QQuickItem
    from PySide6.QtTest import QTest,QSignalSpy
    from backend import gg_testnet,omni_service
    from backend.crypto_ui_runtime import CryptoUiRuntime
    from startup import run_event_loop

    if not gg_testnet.available():
        print(json.dumps({'status':'SKIP','reason':'GG_TESTNET_TOOLCHAIN_REQUIRED'}));return
    app=QGuiApplication([])
    app.setQuitOnLastWindowClosed(False)
    if os.name=='nt':
        for name in ('consola.ttf','consolab.ttf','seguisym.ttf'):
            QFontDatabase.addApplicationFont(str(Path(os.environ['SystemRoot'])/'Fonts'/name))
    family='Consolas' if os.name=='nt' else 'DejaVu Sans Mono'
    QFont.insertSubstitution('monospace',family);app.setFont(QFont(family))
    class Host(QObject):
        omniStatusUpdated=Signal(str)
        def __init__(self):
            super().__init__();self.calls=[]
            # Match the production OMNI cache; very small fixture TTLs can
            # queue redundant full snapshots between genuine user actions.
            self.runtime=CryptoUiRuntime(self,snapshot=omni_service.snapshot,ttl=1.5)
            self.runtime.updated.connect(self.omniStatusUpdated)
        @Slot(result=str)
        def omniStatus(self):return self.runtime.snapshot()
        @Slot(str,str,result=str)
        def omniAction(self,name,raw):
            self.calls.append((name,json.loads(raw)))
            return self.runtime.submit(name,lambda:omni_service.action(name,raw))
        @Slot(str,result=str)
        def tmogCopy(self,value):return value
    host=Host();engine=QQmlApplicationEngine();warnings=[]
    engine.warnings.connect(lambda rows:warnings.extend(row.toString() for row in rows))
    engine.rootContext().setContextProperty('e2eHost',host)
    qml='''import QtQuick
import QtQuick.Controls
import COMPONENTS
ApplicationWindow { width:970;height:620;visible:true;color:'#111111'
OmniSurface { objectName:'e2eHub';anchors.fill:parent;embedded:true;page:'TESTNET';surfaceHost:e2eHost }
}'''.replace('COMPONENTS',json.dumps((PROJECT/'qml/components').as_uri()))
    source=directory/'e2e.qml';source.write_text(qml,encoding='utf-8')
    engine.load(QUrl.fromLocalFile(str(source)))
    assert engine.rootObjects(),'QML_LOAD_FAILED '+repr(warnings)
    window=engine.rootObjects()[0];window.requestActivate();hub=window.findChild(QQuickItem,'e2eHub')
    started=time.monotonic();deadline=started+26;phases=[]
    def js(item,expression):
        query=QQmlExpression(qmlContext(item),item,expression);result=query.evaluate()
        assert not query.hasError(),query.error().toString()
        return result[0] if isinstance(result,tuple) else result
    def state():return json.loads(js(hub,'JSON.stringify(state.testnet || {})'))
    def visual_items(item):
        yield item
        for child in item.childItems():yield from visual_items(child)
    def named(name):
        matches=[item for item in visual_items(window.contentItem()) if item.objectName()==name]
        item=next((item for item in matches if item.isVisible()),matches[0] if matches else None)
        assert item is not None,'MISSING_CONTROL '+name
        return item
    def diagnostics(name):
        item=named(name);ancestors=[];current=item
        while current:
            ancestors.append({'name':current.objectName(),'type':current.metaObject().className(),
                'visible':current.isVisible(),'enabled':current.isEnabled(),'x':current.x(),'y':current.y(),
                'width':current.width(),'height':current.height(),'clip':current.clip()})
            current=current.parentItem()
        layout=named('testnetMainScroll');dashboard=named('testnetDashboard')
        result={'control':name,'ancestors':ancestors,'layout':{key:layout.property(key) for key in ('page','compact','split','stacked','formFocused')},
                'dashboard':{key:dashboard.property(key) for key in ('running','busy','canAct','editable','hasReview','unresolved')},
                'operation':str(js(hub,'JSON.stringify(operation)')),'state':state().get('state')}
        output=PROJECT/'.runtime/network-v12-e2e';output.mkdir(parents=True,exist_ok=True)
        window.grabWindow().save(str(output/('testnet-'+name+'.png')))
        (output/('testnet-'+name+'.json')).write_text(json.dumps(result,indent=2),encoding='utf-8')
        return json.dumps(result)
    def settle():
        app.processEvents();window.grabWindow();QTest.qWait(10);app.processEvents()
    def wait_for(predicate,label,timeout=10):
        began=time.monotonic();until=min(deadline,began+timeout)
        while time.monotonic()<until:
            # State delivery needs Qt events, not a bitmap copy on every poll.
            # Geometry and screenshot checkpoints still force native polish.
            app.processEvents();QTest.qWait(10);app.processEvents()
            # QtTest can retain Python's GIL while waiting. Yield explicitly
            # so the real Python service worker can perform its RPC/SQL work.
            time.sleep(.01)
            if predicate():
                phases.append({'phase':label,'elapsed_seconds':round(time.monotonic()-began,2)});return
        public=state()
        raise AssertionError('E2E_TIMEOUT '+label+' '+json.dumps({'state':public.get('state'),'operation':js(hub,'JSON.stringify(operation)'),
                              'has_review':bool(public.get('review')),'phases':phases,'warnings':warnings[-8:]},ensure_ascii=False))
    def scroll_to(item):
        current=item.parentItem()
        while current is not None:
            if current.objectName() in {'testnetMainScroll','testnetTelemetryScroll'} and not current.property('noPageScroll'):
                content=current.property('contentItem')
                point=item.mapToItem(content,QPointF(item.width()/2,item.height()/2))
                assert math.isfinite(point.y())
                maximum=max(0,float(current.property('contentHeight'))-current.height())
                current.setProperty('contentY',max(0,min(maximum,point.y()-current.height()/2)))
                settle()
            current=current.parentItem()
    def click(name):
        item=named(name);assert item.isVisible() and item.isEnabled(),diagnostics(name)
        scroll_to(item);settle()
        point=item.mapToScene(QPointF(item.width()/2,item.height()/2))
        assert all(math.isfinite(n) for n in (point.x(),point.y())),'NONFINITE_CONTROL '+name
        assert 0<=point.x()<window.width() and 0<=point.y()<window.height(),'CONTROL_OUTSIDE_VIEWPORT '+name
        spy=QSignalSpy(item.clicked) if name.endswith('TransferTab') else None
        QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,point.toPoint());settle()
        if spy is not None:
            assert spy.count()==1,'TRANSFER_TAB_MOUSE_NOT_DELIVERED '+diagnostics(name)
            assert named('testnetMainScroll').property('page')==1,'TRANSFER_PAGE_NOT_SELECTED '+diagnostics(name)
    def choose(name,index):
        click(name);QTest.keyClick(window,Qt.Key_Home)
        for _ in range(index):QTest.keyClick(window,Qt.Key_Down)
        QTest.keyClick(window,Qt.Key_Return);settle()
        assert named(name).property('currentIndex')==index,'PICKER_NOT_SELECTED '+name
    def amount(value):
        click('testnetAmount');QTest.keyClick(window,Qt.Key_A,Qt.ControlModifier)
        for character in value:QTest.keyClick(window,Qt.Key(ord(character)))
        settle();assert named('testnetAmount').property('text')==value,'AMOUNT_INPUT_FAILED'
    evidence=os.environ.get('GG_NETWORK_E2E_EVIDENCE')
    if evidence:
        evidence_path=Path(evidence).resolve()
        assert evidence_path.is_relative_to((PROJECT/'.runtime').resolve()),'EVIDENCE_MUST_STAY_IN_RUNTIME'
        evidence_path.mkdir(parents=True,exist_ok=True)
    def capture(name):
        if evidence:
            settle();assert window.grabWindow().save(str(evidence_path/name))
    def prepare_and_send(source_index,target_index):
        choose('testnetSender',source_index);choose('testnetRecipient',target_index);amount('1.234567')
        click('testnetPrepare')
        wait_for(lambda:not js(hub,'busy') and bool(state().get('review')),'prepared review')
        review=state()['review'];identity=(review['id'],review['review_digest'])
        assert review['sender_index']==source_index and review['recipient']==state()['accounts'][target_index]['address']
        assert review['amount']=='1.234567' and review['atomic']=='1234567'
        assert not named('testnetSender').isEnabled() and not named('testnetAmount').isEnabled()
        assert not named('testnetPrepare').isEnabled()
        settle();assert (state()['review']['id'],state()['review']['review_digest'])==identity
        capture('testnet-e2e-review-'+str(source_index)+'-'+str(target_index)+'.png')
        click('testnetSend')
        wait_for(lambda:not js(hub,'busy') and not state().get('review') and state()['transactions'][0]['state']=='CONFIRMED','confirmed transfer')
        assert host.calls[-1]==('testnet_send',{'id':identity[0],'review_digest':identity[1]})
        return state()
    process=None;port=0
    try:
        wait_for(lambda:state().get('state')=='STOPPED' and bool(js(hub,'state.assets && state.assets.length')),'initial snapshot')
        click('testnetStart')
        wait_for(lambda:not js(hub,'busy') and state().get('state')=='RUNNING','owned node running')
        process=gg_testnet._process;port=gg_testnet._port
        assert process is not None and gg_testnet._owns_listener()
        assert named('testnetMainScroll').property('noPageScroll') is True
        if not named('testnetMainScroll').property('stacked'):click('testnetTransferTab')
        click('testnetDeploy')
        wait_for(lambda:not js(hub,'busy') and bool(state().get('contract')),'deployed token')
        assert state()['accounts'][0]['token']=='1000000'
        capture('testnet-e2e-deployed.png')
        forward=prepare_and_send(0,1)
        assert forward['accounts'][0]['token']=='999998.765433' and forward['accounts'][1]['token']=='1.234567'
        reverse=prepare_and_send(1,0)
        assert reverse['accounts'][0]['token']=='1000000' and reverse['accounts'][1]['token']=='0'
        assert named('testnetSelfTest').isVisible(),'Desktop rail must expose the functional test directly'
        click('testnetSelfTest')
        wait_for(lambda:not js(hub,'busy') and (state().get('last_test') or {}).get('state')=='PASS','round-trip self test',timeout=20)
        tested=state();assert len(tested['last_test']['checks'])==4
        assert tested['last_test']['token_balances_restored'] and tested['last_test']['supply_verified']
        capture('testnet-e2e-self-test.png')
        session=tested['session'];click('testnetLabMode')
        wait_for(lambda:hub.property('page')=='LAB' and window.findChild(QQuickItem,'networkDashboard') is not None,'signed lab navigation')
        assert gg_testnet._process is process and gg_testnet._owns_listener()
        click('networkTestnetMode')
        wait_for(lambda:hub.property('page')=='TESTNET' and window.findChild(QQuickItem,'testnetDashboard') is not None,'return to testnet')
        assert state()['session']==session
        click('testnetStop')
        wait_for(lambda:not js(hub,'busy') and state().get('state')=='STOPPED','node stopped')
        assert gg_testnet._process is None and process.poll() is not None
        with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as probe:
            probe.settimeout(.5);assert probe.connect_ex(('127.0.0.1',port))!=0,'LISTENER_SURVIVED_STOP'
        assert [name for name,_ in host.calls]==['testnet_start','testnet_deploy','testnet_prepare','testnet_send',
                                               'testnet_prepare','testnet_send','testnet_self_test','testnet_stop']
        assert not warnings,repr(warnings)
        print(json.dumps({'status':'PASS','real_qml':True,'async_service':True,'owned_node':True,'exact_roundtrip':True,
                          'self_test_checks':4,'ui_actions':len(host.calls),'node_stopped':True,'warnings':len(warnings),
                          'elapsed_seconds':round(time.monotonic()-started,2),'phases':phases}))
    finally:
        host.runtime.close();gg_testnet.stop()
        if process is not None:assert process.poll() is not None
        until=time.monotonic()+3
        while host.runtime._running and time.monotonic()<until:app.processEvents();QTest.qWait(10)
        QTimer.singleShot(0,app.quit)
        assert run_event_loop(app,engine)==0


class GGTestnetUiIntegration(unittest.TestCase):
    def test_real_controls_async_service_and_owned_node(self):
        with tempfile.TemporaryDirectory(prefix='gg-network-e2e-') as temporary:
            directory=Path(temporary);environment=os.environ.copy()
            environment.update(QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software',QT_QUICK_CONTROLS_STYLE='Basic',
                               GG_DESKTOP_STATE_ROOT=str(directory/'state'),GG_DESKTOP_DATA_ROOT=str(directory/'data'),PYTHONUTF8='1')
            result=subprocess.run([sys.executable,'-X','utf8','-B',str(Path(__file__).resolve()),'--fixture',temporary],
                                  cwd=PROJECT,env=environment,capture_output=True,text=True,encoding='utf-8',timeout=35)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            reports=[json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
            self.assertTrue(reports,result.stdout+result.stderr)
            if reports[-1]['status']=='SKIP':self.skipTest(reports[-1]['reason'])
            self.assertEqual(reports[-1]['status'],'PASS')
            print(json.dumps(reports[-1]))


if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--fixture':fixture(Path(sys.argv[2]))
    else:unittest.main()
