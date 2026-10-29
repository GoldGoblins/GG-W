"""Actual QML for the four-process consensus dashboard, with synthetic data only."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

PROJECT=Path(__file__).resolve().parents[1]
SIZES=((360,360),(640,460),(970,460),(360,640),(430,700),(820,700),(970,620),(970,680),(1200,800),(1586,992))


def fixture(directory):
    from PySide6.QtCore import QObject,QPointF,Qt,QUrl,Slot
    from PySide6.QtGui import QFont,QFontDatabase
    from PySide6.QtQml import QQmlApplicationEngine,QQmlComponent,QQmlExpression,qmlContext
    from PySide6.QtQuick import QQuickItem,QSGRendererInterface
    from PySide6.QtTest import QSignalSpy,QTest
    from PySide6.QtWidgets import QApplication
    app=QApplication([]);app.setQuitOnLastWindowClosed(False)
    if os.name=='nt':
        for face in ('consola.ttf','consolab.ttf','seguisym.ttf'):QFontDatabase.addApplicationFont(str(Path(os.environ['SystemRoot'])/'Fonts'/face))
    family='Consolas' if os.name=='nt' else 'DejaVu Sans Mono'
    QFont.insertSubstitution('monospace',family);app.setFont(QFont(family))
    addresses=[str(i+1)*64 for i in range(4)]
    consensus={'state':'RUNNING','available':True,'engine':'CometBFT v0.40.0','chain_id':'ggnet-synthetic-public-chain',
        'height':13,'state_height':12,'online':4,'quorum_required':3,'unresolved':False,'error':'',
        'validators':[{'index':i,'node_id':str(i+1)*40,'public_key':str(i+1)*64,'alive':True,'identity_verified':True,
                       'peers':3,'height':13,'rpc_url':'http://127.0.0.1:'+str(20000+i),
                       'memory_private_bytes':100*1048576+i,'cpu_seconds':1.25+i} for i in range(4)],
        'accounts':[{'index':i,'address':a,'quantity':'249999.123456' if not i else '250000','atomic':str(250000*10**6),'nonce':i} for i,a in enumerate(addresses)],
        'proof':{'verified':True,'state_height':12,'certificate_height':13,'state_root':'a'*64,'account_root':'b'*64,
                 'validator_count':4,'quorum_required':3,'transaction_inclusion_verified':True,'execution_status_verified':True},
        'review':None,'transactions':[{'hash':'c'*64,'state':'FINALIZED','sender':addresses[0],'recipient':addresses[1],
                                    'amount':'1.000001','height':12,'certificate_height':13,'elapsed_ms':42.125}],
        'measurements':[{'operation':('verify','transfer','self_test')[i%3],'elapsed_ms':i+2.125,
                         'observed_at':1700000000+i,'state':'PASS'} for i in range(16)],
        'last_test':{'state':'PASS','checks':[{'name':name,'state':'PASS'} for name in ('Överföring fram','Överföring tillbaka','Saknat quorum','Återhämtning')],'observed_at':1700000000},
        'benchmark':{'state':'PASS','count':32,'successful':32,'tps':123.456,'p50_ms':13.5,'p95_ms':21.25,'p99_ms':27.75,
                     'elapsed_seconds':.2592,'validators':4,'physical_hosts':1,'scope':'LOCAL_FIXED_VALIDATORS'},
        'events':[{'ts':1700000000+i,'kind':'FINALIZED','message':'Isolerad syntetisk validatorhändelse '+str(i)} for i in range(48,0,-1)]}
    payload={'ui_operation':{},'consensus':consensus}
    class Host(QObject):
        def __init__(self):super().__init__();self.calls=[];self.copied=[]
        @Slot(str,str)
        def record(self,name,raw):self.calls.append((name,json.loads(raw)))
        @Slot(str,result=str)
        def tmogCopy(self,value):self.copied.append(value);return value
    host=Host();engine=QQmlApplicationEngine();warnings=[]
    engine.warnings.connect(lambda rows:warnings.extend(row.toString() for row in rows))
    engine.rootContext().setContextProperty('fixturePayload',payload)
    engine.rootContext().setContextProperty('fixtureHost',host)
    native=os.environ.get('GG_CONSENSUS_NATIVE')=='1'
    engine.rootContext().setContextProperty('nativeProbe',native)
    path=directory/'fixture.qml'
    path.write_text('''import QtQuick
import QtQuick.Controls
import COMPONENTS
ApplicationWindow {id:testWindow;width:970;height:680;visible:true;color:'#111111';x:nativeProbe?320:0;y:nativeProbe?200:0
flags:nativeProbe?(Qt.Tool|Qt.FramelessWindowHint|Qt.WindowDoesNotAcceptFocus|Qt.WindowStaysOnBottomHint):Qt.Window
property var payload:fixturePayload
GGConsensusDashboard {objectName:'consensusDashboard';anchors.fill:parent;state:testWindow.payload;surfaceHost:fixtureHost;onActionRequested:function(name,args){fixtureHost.record(name,JSON.stringify(args))}}
}'''.replace('COMPONENTS',json.dumps((PROJECT/'qml/components').as_uri())),encoding='utf-8')
    engine.load(QUrl.fromLocalFile(str(path)));assert engine.rootObjects(),warnings
    window=engine.rootObjects()[0];root=window.findChild(QQuickItem,'consensusDashboard')
    if native:
        window.lower();assert QTest.qWaitForWindowExposed(window,3000)
    QTest.qWait(100);window.grabWindow()
    if native:assert window.rendererInterface().graphicsApi()==QSGRendererInterface.GraphicsApi.Direct3D11
    def js(owner,text):
        expression=QQmlExpression(qmlContext(owner),owner,text);result=expression.evaluate()
        assert not expression.hasError(),expression.error().toString()
        return result[0] if isinstance(result,tuple) else result
    def items(owner):
        yield owner
        for child in owner.childItems():yield from items(child)
    def named(name):
        found=next((i for i in items(root) if i.objectName()==name),None)
        if found is None:found=root.findChild(QQuickItem,name)
        assert found is not None,name
        return found
    def settle():QTest.qWait(35);window.grabWindow()
    def push(data):window.setProperty('payload',deepcopy(data));settle()
    def scroll_to(item,rail=False):
        prefix='consensus'
        def beneath(child,ancestor):
            while child is not None:
                if child is ancestor:return True
                child=child.parentItem()
            return False
        def fits(child,viewport):
            top=child.mapToItem(viewport,QPointF(0,0)).y()
            return child.isVisible() and top>=-1 and top+child.height()<=viewport.height()+1
        railview=named(prefix+'TelemetryScroll')
        if rail or beneath(item,railview):
            count=int(js(railview,'sections.length'))
            for section in range(1,count+2):
                railview.setProperty('page',section);settle()
                if fits(item,railview):return
            raise AssertionError(('rail section does not expose control',item.objectName()))
        main=named(prefix+'MainScroll')
        books=root.findChild(QQuickItem,prefix+'Books')
        history=root.findChild(QQuickItem,'networkHistoryBooks')
        for page in (0,1,2):
            main.setProperty('page',page)
            for bookpage in (0,1):
                if books is not None:books.setProperty('bookPage',bookpage)
                if history is not None:history.setProperty('listPage',bookpage)
                settle()
                if fits(item,root):return
        raise AssertionError(('adaptive main section does not expose control',item.objectName()))
    def click(item):
        settle();assert item.isVisible() and item.isEnabled(),(item.objectName(),'not interactive')
        point=item.mapToScene(QPointF(item.width()/2,item.height()/2)).toPoint()
        assert 0<=point.x()<window.width() and 0<=point.y()<window.height(),(item.objectName(),point)
        QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,point);settle()
    def capture(name):
        target=os.environ.get('GG_CONSENSUS_UI_EVIDENCE')
        if target:
            out=Path(target)/('direct3d' if native else 'software');out.mkdir(parents=True,exist_ok=True)
            window.grabWindow().save(str(out/name))
    def ink(item):
        picture=window.grabWindow();scale=picture.width()/window.width();point=item.mapToScene(QPointF(0,0));count=0
        for y in range(round((point.y()+6)*scale),round((point.y()+item.height()-6)*scale)):
            for x in range(round((point.x()+6)*scale),round((point.x()+item.width()-6)*scale)):
                color=picture.pixelColor(x,y);count+=color.red()+color.green()+color.blue()>200
        assert count>8,('glyph or control vanished',item.objectName(),count)
    def toolbar_ink():
        ink(named('consensusRefresh'));ink(named('consensusValidatorMode'))
    for width,height in SIZES:
        window.setWidth(width);window.setHeight(height);settle()
        main=named('consensusMainScroll');main.setProperty('page',0);settle()
        assert abs(root.width()-width)<.1 and abs(root.height()-height)<.1
        assert root.property('dockAvailable')==(width>=820)
        assert abs(main.width()-(width-(root.property('railWidth') if width>=820 else 0)))<.1
        assert len([i for i in items(root) if i.objectName()=='consensusValidatorRow'])==4
        account_rows=[i for i in items(root) if i.objectName()=='consensusAccountRow'];assert len(account_rows)==4
        quantity=next(i for i in items(account_rows[0]) if i.objectName()=='consensusQuantity')
        assert quantity.property('text')=='249999.123456'
        assert '249999.123456' in js(quantity,'Accessible.name')
        assert js(quantity,'ToolTip.text')==quantity.property('text')
        assert len([i for i in items(root) if i.objectName()=='consensusMeasurementBar'])==16
        for row in account_rows:assert row.mapToItem(root,QPointF(row.width(),0)).x()<=main.width()+.1
        if width==970:
            prepare=named('consensusPrepare');scroll_to(prepare)
            assert prepare.mapToItem(root,QPointF(0,prepare.height())).y()<=height, 'Primary transfer action is below the fold'
        toolbar_ink();capture('consensus-'+str(width)+'.png')
        if height<=460:
            main.setProperty('page',1);settle()
            for control_name in ('consensusSender','consensusRecipient','consensusAmount','consensusPrepare'):
                control=named(control_name);ancestor=control.parentItem()
                assert control.isVisible(),control_name
                while ancestor is not None and ancestor is not root:
                    if ancestor.clip():
                        top=control.mapToItem(ancestor,QPointF(0,0)).y()
                        assert top>=-1 and top+control.height()<=ancestor.height()+1,(control_name,'clipped form',top,control.height(),ancestor.objectName(),ancestor.height(),ancestor.y(),main.property('formFocused'),main.height())
                    ancestor=ancestor.parentItem()
            main.setProperty('page',0);settle()
        if width<820:
            js(root,'toggleDetails()');settle();assert root.property('detailsVisible')
            scroll_to(named('consensusCopyStateRoot'),True);ink(named('consensusCopyStateRoot'))
            capture('consensus-'+str(width)+'-drawer.png')
            js(root,'toggleDetails()');settle();assert not root.property('detailsVisible')
        else:
            js(root,'toggleDetails()');settle();assert abs(main.width()-width)<.1
            js(root,'toggleDetails()');settle()
    window.setWidth(970);window.setHeight(680);settle();push(payload)
    main=named('consensusMainScroll');main.setProperty('page',0);settle()
    assert main.property('desktop') and not named('consensusTransferTab').isVisible()
    for section in ('Summary','Measurements','Relations','Accounts','History','Transfer'):
        panel=named('consensus'+section+'Viewport')
        assert panel.isVisible() and panel.height()>45
        assert panel.y()+panel.height()<=root.height()-30
    assert named('consensusSender').isVisible() and named('consensusAccountsList').isVisible()
    refresh=QSignalSpy(root.refreshRequested);pages=QSignalSpy(root.pageRequested)
    click(named('consensusRefresh'));assert refresh.count()==1
    click(named('consensusLabMode'));assert pages.at(0)[0]=='LAB'
    stop_node=next(i for i in items(root) if i.objectName()=='consensusStopNode')
    scroll_to(stop_node);click(stop_node);assert host.calls[-1]==('consensus_stop_node',{'index':0})
    root.setProperty('senderIndex',2);root.setProperty('recipientIndex',3)
    named('consensusAmount').setProperty('text','1.234567')
    prepare=named('consensusPrepare');scroll_to(prepare);click(prepare)
    assert host.calls[-1]==('consensus_prepare',{'sender':2,'recipient':addresses[3],'amount':'1.234567'})
    reviewed=deepcopy(payload)
    reviewed['consensus']['review']={'id':'immutable-consensus-review','review_digest':'f'*64,'chain_id':consensus['chain_id'],
        'sender_index':0,'sender':addresses[0],'recipient':addresses[1],'amount':'0.000001','symbol':'GG-NET-TEST','nonce':0,'expires_at':time.time()+120}
    initial_component=QQmlComponent(engine,QUrl.fromLocalFile(str(PROJECT/'qml/components/GGConsensusDashboard.qml')))
    initial_review=initial_component.createWithInitialProperties({'state':reviewed,'surfaceHost':host,'visible':False})
    assert initial_review is not None,[error.toString() for error in initial_component.errors()]
    assert initial_review.findChild(QQuickItem,'consensusAmount').property('text')=='0.000001'
    assert initial_review.findChild(QQuickItem,'consensusSender').property('currentIndex')==0
    initial_review.deleteLater();app.processEvents()
    push(reviewed)
    assert not named('consensusAmount').isEnabled() and not named('consensusSender').isEnabled()
    root.setProperty('senderIndex',3);root.setProperty('recipientIndex',2)
    assert named('consensusSender').property('currentIndex')==0 and named('consensusRecipient').property('currentIndex')==1
    assert named('consensusAmount').property('text')=='0.000001'
    send=named('consensusSend');scroll_to(send);capture('consensus-review.png');toolbar_ink();click(send)
    assert host.calls[-1]==('consensus_send',{'id':'immutable-consensus-review','review_digest':'f'*64})
    cancel=named('consensusCancel');click(cancel);assert host.calls[-1]==('consensus_cancel',{})
    invalid_review=deepcopy(reviewed);invalid_review['consensus']['review']['chain_id']='different-chain';push(invalid_review)
    assert not named('consensusSend').isEnabled()
    expired=deepcopy(reviewed);expired['consensus']['review']['expires_at']=time.time()-1;push(expired)
    assert not named('consensusSend').isEnabled()
    missing_chain=deepcopy(reviewed);missing_chain['consensus']['review'].pop('chain_id');push(missing_chain)
    assert not named('consensusSend').isEnabled()
    push(reviewed);js(root,'review.expires_at = 0')
    before=len(host.calls);js(root,'send()');assert len(host.calls)==before, 'Expiry must be checked at the click, without an idle timer'
    unresolved=deepcopy(reviewed);unresolved['consensus']['unresolved']=True;push(unresolved)
    assert not named('consensusSend').isEnabled() and not named('consensusPrepare').isEnabled()
    for mode in ('NO_QUORUM','READ_FAILED'):
        blocked=deepcopy(payload);blocked['consensus']['state']=mode
        if mode=='NO_QUORUM':
            blocked['consensus']['online']=2
            for v in blocked['consensus']['validators'][2:]:v['alive']=False
        push(blocked);before=len(host.calls)
        js(root,"run('consensus_prepare',{})");assert len(host.calls)==before
        assert not named('consensusPrepare').isEnabled()
        if mode=='NO_QUORUM':
            restart=next(i for i in items(root) if i.objectName()=='consensusRestartNode')
            scroll_to(restart);click(restart);assert host.calls[-1]==('consensus_restart_node',{'index':2})
        capture('consensus-'+mode.lower()+'.png')
    missing=deepcopy(payload);missing['consensus']['proof']={};push(missing)
    assert not root.property('running') and not named('consensusPrepare').isEnabled()
    approval=deepcopy(payload);approval['ui_operation']={'state':'approval_required'};push(approval)
    before=len(host.calls);js(root,"run('consensus_stop',{})");assert len(host.calls)==before
    assert not named('consensusStop').isEnabled()
    push(payload);test=named('consensusSelfTest');scroll_to(test,True);click(test)
    assert host.calls[-1]==('consensus_self_test',{})
    bench=named('consensusBenchmark');scroll_to(bench,True);click(bench)
    assert host.calls[-1]==('consensus_benchmark',{'count':32})
    assert named('consensusBenchmarkTps').property('value')=='123.46'
    empty_benchmark=deepcopy(payload);empty_benchmark['consensus']['benchmark']={};push(empty_benchmark)
    assert named('consensusBenchmarkTps').property('value')=='Ej uppmätt'
    push(payload);all_events=named('consensusAllEvents');scroll_to(all_events,True);click(all_events)
    assert root.findChild(QQuickItem,'consensusAllEventsList').property('count')==48
    QTest.keyClick(window,Qt.Key_Escape);settle()
    stopped=deepcopy(payload);stopped['consensus'].update(state='STOPPED',validators=[],accounts=[],proof={},measurements=[],transactions=[],review=None,online=0)
    push(stopped);named('consensusMainScroll').setProperty('page',0);settle()
    assert named('consensusStart').isEnabled() and not named('consensusPrepare').isEnabled()
    click(named('consensusStart'));assert host.calls[-1]==('consensus_start',{})
    capture('consensus-stopped.png')
    missing_tool=deepcopy(stopped);missing_tool['consensus']['available']=False;push(missing_tool)
    assert not named('consensusStart').isEnabled()
    before=len(host.calls);click(named('consensusInstallHelp'));assert len(host.calls)==before
    assert root.findChild(QObject,'consensusSetupHelp').property('visible')
    QTest.keyClick(window,Qt.Key_Escape);push(payload)
    swaps=QSignalSpy(window.frameSwapped);QTest.qWait(150);assert swaps.count()<=1,('unnecessary idle repaint',swaps.count())
    assert not warnings,warnings
    print(json.dumps({'status':'PASS','geometry_cases':len(SIZES),'native':native,'warnings':len(warnings),'exact_review':True,'proof_and_quorum_guards':True}))
    window.close();engine.deleteLater();app.processEvents()


class ConsensusDashboardUi(unittest.TestCase):
    def run_fixture(self,native=False):
        with tempfile.TemporaryDirectory(prefix='gg-consensus-ui-') as temporary:
            env=os.environ.copy();env.update(QT_QUICK_CONTROLS_STYLE='Basic',GG_DESKTOP_STATE_ROOT=str(Path(temporary)/'state'),GG_DESKTOP_DATA_ROOT=str(Path(temporary)/'data'))
            if native:
                env.pop('QT_QUICK_BACKEND',None);env.update(QT_QPA_PLATFORM='windows',QSG_RHI_BACKEND='d3d11',GG_CONSENSUS_NATIVE='1')
            else:
                env.update(QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software');env.pop('GG_CONSENSUS_NATIVE',None)
            result=subprocess.run([sys.executable,'-X','utf8','-B',str(Path(__file__).resolve()),'--fixture',temporary],cwd=PROJECT,env=env,capture_output=True,text=True,encoding='utf-8',timeout=60)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr);print(result.stdout.strip())
    def test_software_consensus_dashboard(self):self.run_fixture()
    @unittest.skipUnless(os.name=='nt','Native Direct3D11 is a Windows check')
    def test_native_direct3d_consensus_dashboard(self):self.run_fixture(True)


if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--fixture':fixture(Path(sys.argv[2]))
    else:unittest.main()
