"""Actual local signed proposal DAG through real native QML controls.

Only disposable ephemeral test keys/state; no wallet, network or user node.
"""
from pathlib import Path
import json,os,subprocess,sys,tempfile,time,unittest
ROOT=Path(__file__).resolve().parents[1]


def fixture(directory):
    sys.path.insert(0,str(ROOT))
    from PySide6.QtCore import QObject,Slot,QUrl,QPointF,Qt,QEventLoop,QTimer
    from PySide6.QtGui import QFont,QFontDatabase
    from PySide6.QtQml import QQmlApplicationEngine,QQmlExpression,qmlContext
    from PySide6.QtQuick import QQuickItem,QSGRendererInterface
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest,QSignalSpy
    from backend import gg_parallel_dag as node
    app=QApplication([]);app.setQuitOnLastWindowClosed(False)
    for font in ('consola.ttf','consolab.ttf','seguisym.ttf'):
        if os.name=='nt':QFontDatabase.addApplicationFont(str(Path(os.environ['SystemRoot'])/'Fonts'/font))
    QFont.insertSubstitution('monospace','Consolas' if os.name=='nt' else 'DejaVu Sans Mono')
    app.setFont(QFont('Consolas' if os.name=='nt' else 'DejaVu Sans Mono'))
    class Host(QObject):
        def __init__(self):super().__init__();self.calls=[];self.wave_times=[];self.window=None
        @Slot(str,str)
        def record(self,name,args):
            args=json.loads(args);self.calls.append((name,args))
            if name=='dag_start':body=node.start()
            elif name=='dag_wave':self.wave_times.append(time.monotonic());body=node.build_wave(**args)
            elif name=='dag_live_start':body=node.start_live(**args)
            elif name=='dag_live_stop':body=node.stop_live()
            elif name=='dag_stop':body=node.stop()
            else:raise AssertionError('UNKNOWN_DAG_TEST_ACTION')
            self.window.setProperty('fixtureData',{'parallel_dag':body,'ui_operation':{}})
        @Slot(str,result=str)
        def tmogCopy(self,value):return value
    host=Host();engine=QQmlApplicationEngine();warnings=[]
    engine.warnings.connect(lambda rows:warnings.extend(row.toString() for row in rows))
    engine.rootContext().setContextProperty('fixtureHost',host)
    engine.rootContext().setContextProperty('nativeProbe',os.environ.get('GG_DAG_NATIVE')=='1')
    engine.rootContext().setContextProperty('initialJSON',json.dumps({'parallel_dag':node.snapshot(),'ui_operation':{}}))
    source='''import QtQuick
import QtQuick.Controls
import COMPONENTS
ApplicationWindow {id:testWindow;width:970;height:620;visible:true;color:'#111111';property var fixtureData:JSON.parse(initialJSON)
property string livePacket:'';onLivePacketChanged:if(livePacket)fixtureData=JSON.parse(livePacket)
x:nativeProbe?320:0;y:nativeProbe?200:0;flags:nativeProbe?(Qt.Tool|Qt.FramelessWindowHint|Qt.WindowDoesNotAcceptFocus|Qt.WindowStaysOnBottomHint):Qt.Window
GGParallelDagDashboard {id:dashboard;anchors.fill:parent;state:testWindow.fixtureData;surfaceHost:fixtureHost;onActionRequested:function(name,args){fixtureHost.record(name,JSON.stringify(args))}}}'''.replace('COMPONENTS',json.dumps((ROOT/'qml/components').as_uri()))
    engine.loadData(source.encode(),QUrl.fromLocalFile(str(directory/'fixture.qml')))
    assert engine.rootObjects(),warnings
    window=engine.rootObjects()[0];host.window=window
    def items(item):
        yield item
        for child in item.childItems():yield from items(child)
    root=window.findChild(QQuickItem,'parallelDagDashboard')
    def named(name):
        item=next((item for item in items(root) if item.objectName()==name),None)
        assert item is not None,name
        return item
    def js(owner,source):
        exp=QQmlExpression(qmlContext(owner),owner,source);value=exp.evaluate()
        assert not exp.hasError(),exp.error().toString()
        return value[0] if isinstance(value,tuple) else value
    def settle():QTest.qWait(60);window.grabWindow()
    def click(name):
        settle()
        item=named(name);assert item.isVisible() and item.isEnabled(),name
        point=item.mapToScene(QPointF(item.width()/2,item.height()/2)).toPoint()
        QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,point);settle()
    def capture(name):
        target=os.environ.get('GG_DAG_UI_EVIDENCE')
        if target:
            out=Path(target)/('direct3d' if os.environ.get('GG_DAG_NATIVE')=='1' else 'software');out.mkdir(parents=True,exist_ok=True)
            window.grabWindow().save(str(out/name))
    try:
        settle()
        if os.environ.get('GG_DAG_NATIVE')=='1':
            window.lower();assert QTest.qWaitForWindowExposed(window,3000)
            assert window.rendererInterface().graphicsApi()==QSGRendererInterface.GraphicsApi.Direct3D11
        assert not named('dagCreateWave').isEnabled()
        click('dagStart');assert node.snapshot()['state']=='RUNNING'
        deadline=time.monotonic()+3
        while node.snapshot()['blocks_admitted']==0 and time.monotonic()<deadline:QTest.qWait(20)
        live_body=node.snapshot();assert live_body['blocks_admitted']>0 and live_body['live']['enabled']
        window.setProperty('fixtureData',{'parallel_dag':live_body,'ui_operation':{}});settle()
        assert not named('dagCreateWave').isEnabled()
        assert named('dagWaveBlocks').property('text')==str(live_body['live']['blocks'])
        assert named('dagLiveInterval').property('text')==str(live_body['live']['interval_ms'])
        assert len([item for item in items(root) if item.objectName()=='dagMeasurementGroup'])==len(live_body['measurements'])
        assert len([item for item in items(root) if item.objectName()=='dagMeasurementBar'])==3*len(live_body['measurements'])
        assert named('dagMainLayout').property('noPageScroll') and named('dagTelemetryLayout').property('noPageScroll')
        # Real signed parallel waves, updated through Qt's native event loop.
        # A full-width tail is checked DURING arrivals; waiting for animations
        # to settle hid the old permanent right-side compression at high rates.
        if os.environ.get('GG_DAG_NATIVE')=='1':
            # An occluded native tool window may suspend its animation clock.
            # This short nonfocusable preview measures visible motion rather
            # than waiting on an invisible bottommost fixture's frozen x.
            window.setFlags(Qt.Tool|Qt.FramelessWindowHint|Qt.WindowDoesNotAcceptFocus|Qt.WindowStaysOnTopHint);window.show()
        updater=QTimer();updater.setTimerType(Qt.PreciseTimer);updater.setInterval(16)
        live_revision=[None];known_live_headers={row['hash']:row for row in live_body['block_graph']['blocks']}
        def observe_live():
            revision=node.telemetry_revision()
            if revision!=live_revision[0]:
                live_revision[0]=revision
                current=node.snapshot()
                known_live_headers.update({row['hash']:row for row in current['block_graph']['blocks']})
                window.setProperty('livePacket',json.dumps({'parallel_dag':current,'ui_operation':{}}))
        updater.timeout.connect(observe_live)
        live_loop=QEventLoop();live_end=QTimer();live_end.setSingleShot(True);live_end.timeout.connect(live_loop.quit)
        import psutil
        live_frames=[];frame_slot=lambda:live_frames.append(time.monotonic())
        window.frameSwapped.connect(frame_slot)
        live_started=time.monotonic();live_cpu=psutil.Process().cpu_times();live_before=node.snapshot()['blocks_admitted']
        updater.start();live_end.start(2600);live_loop.exec();updater.stop()
        live_seconds=time.monotonic()-live_started;live_end_cpu=psutil.Process().cpu_times()
        window.frameSwapped.disconnect(frame_slot)
        live_performance={'seconds':live_seconds,'frames':len(live_frames),'frame_hz':len(live_frames)/live_seconds,
                          'actual_new_proposals':node.snapshot()['blocks_admitted']-live_before,
                          'gui_cpu_seconds':live_end_cpu.user+live_end_cpu.system-live_cpu.user-live_cpu.system,
                          'inspection_during_timing':False,'wire':'JSON.parse actual changed proposal waves'}
        print(json.dumps({'live_native_phase':live_performance}),flush=True)
        graph=named('dagBlockRelationsGraph')
        live_points=[item for item in items(graph) if item.objectName()=='relationBlock']
        assert 48<len(live_points)<=128 and len(live_points)==graph.property('shownCount'),len(live_points)
        live_extent={'left_x':min(item.mapToItem(graph,QPointF(0,0)).x() for item in live_points),'right_x':max(item.mapToItem(graph,QPointF(item.width(),0)).x() for item in live_points),'plot_width':graph.width(),'actual_points':len(live_points)}
        assert live_extent['left_x']<=.10*live_extent['plot_width'],live_extent
        assert live_extent['right_x']>=.90*live_extent['plot_width'],live_extent
        assert js(graph,'horizontalMotionMs(shownCount-1)')==js(graph,'horizontalMotionMs(0)'),'All real proposals share the same horizontal flow clock'
        assert js(graph,'coherentFlow'),'The high-rate actual proposal stream uses one shared flow offset'
        assert all(point.property('blockHash') in known_live_headers for point in live_points)
        visible_x=sorted(point.mapToItem(graph,QPointF(point.width()/2,point.height()/2)).x() for point in live_points if point.opacity()>=.4)
        gaps=[b-a for a,b in zip(visible_x,visible_x[1:])]
        assert max(gaps)<=max(16,3*float(graph.property('pointPitch'))),(max(gaps),graph.property('pointPitch'))
        capture('dag-live-970.png')
        if os.environ.get('GG_DAG_NATIVE')=='1':
            window.setFlags(Qt.Tool|Qt.FramelessWindowHint|Qt.WindowDoesNotAcceptFocus|Qt.WindowStaysOnBottomHint);window.show();window.lower()
        click('dagLiveToggle');assert not node.snapshot()['live']['enabled']
        before=len(host.calls)
        named('dagWaveBlocks').setProperty('text','33');settle()
        assert not named('dagCreateWave').isEnabled();js(root,'wave()');assert len(host.calls)==before
        named('dagWaveBlocks').setProperty('text','24')
        named('dagTxPerBlock').setProperty('text','128');settle()
        assert not named('dagCreateWave').isEnabled()
        named('dagTxPerBlock').setProperty('text','8');settle()
        click('dagCreateWave');assert host.calls[-1]==('dag_wave',{'blocks':24,'transactions_per_block':8})
        click('dagCreateWave');QTest.qWait(100)
        graph=named('dagBlockRelationsGraph')
        deadline=time.monotonic()+3
        while graph.property('animationRunning') and time.monotonic()<deadline:QTest.qWait(25)
        assert not graph.property('animationRunning')
        body=node.snapshot();assert body['transactions_validated']==384 and body['canonical_finalized']==0
        assert body['finality']=='EXPLICIT_CHECKPOINT_REQUIRED'
        graph=named('dagBlockRelationsGraph')
        assert graph.property('retainedCount')>24
        assert graph.property('edgeCount')>0
        assert not graph.property('geometryError')
        assert named('dagProposalsList').property('count')>24
        assert any(len(row.get('parent_hashes',[]))==7 for row in body['block_graph']['blocks'])
        import shiboken6
        retained_names={'dagMetric','dagMeasurementAxis','dagProducerRow','dagProposalRow','dagEventRow'}
        def retained_items():
            return {(item.objectName(),item.property('index')):shiboken6.getCppPointer(item)[0]
                    for item in items(root) if item.objectName() in retained_names}
        retained=retained_items()
        assert all(any(key[0]==name for key in retained) for name in retained_names)
        for _ in range(30):
            window.setProperty('fixtureData',{'parallel_dag':node.snapshot(),'ui_operation':{}})
            app.processEvents()
            assert retained==retained_items(),'Unchanged slot counts must retain actual native widget identities'
        default_fields=(named('dagWaveBlocks').property('text'),named('dagTxPerBlock').property('text'))
        for width,height in ((970,620),(1200,800),(430,640),(360,360)):
            window.setWidth(width);window.setHeight(height);QTest.qWait(60)
            if width<970:click('dagTransferTab')
            deadline=time.monotonic()+3
            while graph.property('animationRunning') and time.monotonic()<deadline:QTest.qWait(25)
            for key in ('dagWaveBlocks','dagTxPerBlock','dagCreateWave'):
                item=named(key);top=item.mapToItem(root,QPointF(0,0)).y()
                assert item.isVisible() and top>=0 and top+item.height()<=height,(key,width,height,top,item.height())
            assert default_fields==(named('dagWaveBlocks').property('text'),named('dagTxPerBlock').property('text'))
            if width>=970:
                for key in ('dagSummaryViewport','dagMeasurementsViewport','dagRelationsViewport','dagAccountsViewport','dagHistoryViewport','dagTransferViewport'):
                    panel=named(key);assert panel.isVisible() and panel.height()>50
            capture('dag-'+str(width)+'.png')
        window.setWidth(970);window.setHeight(620);settle()
        capped=json.loads(json.dumps(body));capped['live'].update(state='LIMIT_REACHED',enabled=False,stop_reason='GG_DAG_RECORD_LIMIT')
        window.setProperty('fixtureData',{'parallel_dag':capped,'ui_operation':{}});settle()
        assert named('dagLimitNotice').isVisible() and not named('dagLiveToggle').isEnabled()
        assert not named('dagCreateWave').isEnabled()
        window.setProperty('fixtureData',{'parallel_dag':body,'ui_operation':{}});settle()
        blocked={'parallel_dag':body,'ui_operation':{'state':'approval_required'}};window.setProperty('fixtureData',blocked);settle()
        assert not named('dagCreateWave').isEnabled() and named('dagStop').isEnabled(),'Stopping an already-owned producer remains available during a pending action'
        before=len(host.calls);js(root,'wave()');assert len(host.calls)==before
        window.setProperty('fixtureData',{'parallel_dag':body,'ui_operation':{}});settle()
        named('dagWaveBlocks').setProperty('text','4');named('dagTxPerBlock').setProperty('text','2');settle()
        count=len(host.wave_times);click('dagTimedWaves')
        deadline=time.monotonic()+9
        while root.property('sequenceRunning') and time.monotonic()<deadline:QTest.qWait(25)
        assert not root.property('sequenceRunning')
        timed=host.wave_times[count:];assert len(timed)==3,timed
        assert all(b-a>=1.95 for a,b in zip(timed,timed[1:])),timed
        count=len(host.wave_times);click('dagTimedWaves');assert len(host.wave_times)==count+1
        root.setVisible(False);QTest.qWait(2300)
        assert not root.property('sequenceRunning') and len(host.wave_times)==count+1
        root.setVisible(True);settle()
        count=len(host.wave_times);click('dagTimedWaves');assert len(host.wave_times)==count+1
        body=node.snapshot();window.setProperty('fixtureData',{'parallel_dag':body,'ui_operation':{'state':'approval_required'}});QTest.qWait(2100)
        assert not root.property('sequenceRunning') and len(host.wave_times)==count+1
        window.setProperty('fixtureData',{'parallel_dag':body,'ui_operation':{}});settle()
        click('dagStop');assert node.snapshot()['state']=='STOPPED'
        assert not named('dagCreateWave').isEnabled()
        assert not warnings,sorted(set(warnings))
        print(json.dumps({'status':'PASS','real_qml':True,'automatic_signed_empty_live_proposals':True,'live_tail_extent':live_extent,'shared_live_motion_ms':32,'bounded_new_point_entrance_ms':420,'live_performance':live_performance,'live_pause_keeps_history':True,'bounded_real_measurement_history':True,'visible_quota_stop':True,'no_page_scroll':True,'retained_widget_types':sorted(retained_names),'retained_widgets_over_30_updates':len(retained),'actual_parallel_signed_waves':2,'signed_transactions':384,'multiple_parents':True,'canonical_finalized':0,'sizes':4,'timed_waves':3,'minimum_dispatch_gap_seconds':round(min(b-a for a,b in zip(timed,timed[1:])),3),'hide_and_approval_cancel':True,'warnings':len(warnings)}))
    finally:
        node.stop();window.close();engine.deleteLater();app.processEvents()


class ParallelDagDashboardUi(unittest.TestCase):
    def check_fixture(self,native=False):
        with tempfile.TemporaryDirectory(prefix='gg-real-dag-ui-') as directory:
            env=os.environ.copy();env.update(QT_QUICK_CONTROLS_STYLE='Basic',GG_DESKTOP_STATE_ROOT=str(Path(directory)/'state'),GG_DESKTOP_DATA_ROOT=str(Path(directory)/'data'))
            if native:env.pop('QT_QUICK_BACKEND',None);env.update(QT_QPA_PLATFORM='windows',QSG_RHI_BACKEND='d3d11',GG_DAG_NATIVE='1')
            else:env.update(QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software');env.pop('GG_DAG_NATIVE',None)
            result=subprocess.run([sys.executable,'-X','utf8','-B',str(Path(__file__).resolve()),'--fixture',directory],cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',timeout=60)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr);print(result.stdout.strip())
    def test_real_signed_dag_in_software_qml(self):self.check_fixture()
    @unittest.skipUnless(os.name=='nt','Native Direct3D11 on Windows')
    def test_real_signed_dag_in_direct3d_qml(self):self.check_fixture(True)

if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--fixture':fixture(Path(sys.argv[2]))
    else:unittest.main()

