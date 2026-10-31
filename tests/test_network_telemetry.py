"""Bounded real observation worker and native QML merge/view lifecycle.

Sources below are owned deterministic fixtures. No HTTP, node, wallet, secret,
user application or preference store is read or changed.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from copy import deepcopy

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def worker_fixture(directory):
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtTest import QTest
    from backend.network_telemetry import NetworkTelemetryRuntime,SAMPLE_SECONDS
    app=QCoreApplication([])
    def pump(milliseconds):
        # Release the Python GIL while retaining an actual Qt event loop.
        # A single long QTest.qWait can starve a Python worker on Windows.
        until=time.monotonic()+milliseconds/1000
        while time.monotonic()<until:
            app.processEvents();time.sleep(.004)
        app.processEvents()
    owner=threading.get_ident()
    calls=[];delivered=[];inflight=0;maximum=0

    def source(page):
        nonlocal inflight,maximum
        inflight+=1;maximum=max(maximum,inflight)
        calls.append((page,threading.get_ident(),time.monotonic()))
        inflight-=1
        return {'network_page':page,'revision':len(calls),'public_counter':len(calls)}

    runtime=NetworkTelemetryRuntime(source=source)
    runtime.updated.connect(lambda raw:delivered.append(json.loads(raw)))
    try:
        assert runtime._worker is None
        pump(40)
        assert not calls and not delivered
        runtime.set_view('NOT_A_NETWORK_PAGE')
        assert runtime._worker is None
        runtime.set_view('TESTNET')
        # Deliberately block this owned test event loop. The worker may read,
        # but notifications must coalesce into one latest queued value.
        time.sleep(.16)
        assert 3<=len(calls)<=int(.16/SAMPLE_SECONDS)+3,len(calls)
        assert all(thread!=owner for _,thread,_ in calls)
        assert len({thread for _,thread,_ in calls})==1 and maximum==1
        assert not delivered and runtime._notified and runtime._latest
        before=len(calls)
        app.processEvents()
        assert len(delivered)==1,delivered
        assert delivered[-1]['public_counter']>=before-1
        coalesced_reads=before
        runtime.set_view('')
        pump(35)
        paused=len(calls)
        pump(80)
        assert len(calls)==paused
        assert runtime._latest is None
        delivered.clear()
        # Cancelling a view while its notification is queued discards it.
        runtime.set_view('TESTNET')
        time.sleep(.04)
        runtime.set_view('')
        app.processEvents()
        assert not delivered
        runtime.set_view('DAG')
        pump(60)
        assert delivered and all(row['network_page']=='DAG' for row in delivered),(delivered,calls,runtime._notified,runtime._latest,runtime._worker.is_alive())
        worker=runtime._worker
    finally:
        runtime.close()
    assert worker is not None and not worker.is_alive()
    closed_calls=len(calls);closed_delivered=len(delivered)
    runtime.set_view('TESTNET')
    pump(45)
    assert len(calls)==closed_calls and len(delivered)==closed_delivered

    # Slow observations skip missed deadlines instead of building a queue or
    # running overlapping calls. A closed worker drains its sole current read.
    slow_calls=[];active=0;max_active=0
    def slow(page):
        nonlocal active,max_active
        active+=1;max_active=max(max_active,active)
        slow_calls.append(time.monotonic())
        time.sleep(.04)
        active-=1
        return {'network_page':page,'revision':len(slow_calls)}
    runtime=NetworkTelemetryRuntime(source=slow)
    try:
        runtime.set_view('TESTNET')
        pump(260)
    finally:runtime.close()
    assert 3<=len(slow_calls)<=6,slow_calls
    assert max_active==1
    gaps=[b-a for a,b in zip(slow_calls,slow_calls[1:])]
    assert all(gap>=.05 for gap in gaps),gaps
    assert not runtime._worker.is_alive()

    # A source read already in progress belongs to its captured generation;
    # switching views cannot relabel that result as the newly selected page.
    entered=threading.Event();release=threading.Event();generation_rows=[]
    def held(page):
        if page=='TESTNET':
            entered.set()
            assert release.wait(1),'Owned fixture release timed out'
        return {'network_page':page,'revision':1,'marker':page}
    runtime=NetworkTelemetryRuntime(source=held)
    runtime.updated.connect(lambda raw:generation_rows.append(json.loads(raw)))
    try:
        runtime.set_view('TESTNET')
        assert entered.wait(1)
        runtime.set_view('DAG')
        release.set();pump(75)
        assert generation_rows and all(row['network_page']=='DAG' for row in generation_rows)
        # An unchanged real snapshot is sent once, despite subsequent reads.
        assert len(generation_rows)==1,generation_rows
        pump(60)
        assert len(generation_rows)==1,generation_rows
    finally:
        release.set();runtime.close()

    # A later source failure is sanitized and deduplicated; normal observation
    # can recover without reusing another view's queued packet.
    mode=['healthy'];fail_calls=[];errors=[]
    def fallible(page):
        fail_calls.append(time.monotonic())
        if mode[0]=='private':raise RuntimeError('fixture confidential value must never leave source')
        if mode[0]=='code':raise ValueError('GG_FIXTURE_NODE_LOST')
        return {'network_page':page,'revision':('healthy',len(fail_calls))}
    runtime=NetworkTelemetryRuntime(source=fallible)
    runtime.updated.connect(lambda raw:errors.append(json.loads(raw)))
    try:
        runtime.set_view('TESTNET');pump(50)
        mode[0]='private';pump(80)
        private_errors=[row for row in errors if row.get('error')=='GG_NETWORK_OBSERVATION_FAILED']
        assert len(private_errors)==1,errors
        assert 'confidential' not in json.dumps(errors)
        mode[0]='code';pump(60)
        assert sum(row.get('error')=='GG_FIXTURE_NODE_LOST' for row in errors)==1
        mode[0]='healthy';pump(50)
        assert 'error' not in errors[-1]
    finally:runtime.close()
    # A real, unchanged proposal DAG still receives cheap cadence checks;
    # copying/encoding its complete retained graph 75 times/s is unnecessary.
    from backend import gg_parallel_dag
    owned_dag=gg_parallel_dag.ParallelDag()
    owned_dag.start()
    try:
        with patch.object(gg_parallel_dag,'_ENGINE',owned_dag), \
             patch.object(gg_parallel_dag,'snapshot',wraps=owned_dag.snapshot) as copies, \
             patch.object(gg_parallel_dag,'telemetry_revision',wraps=owned_dag.telemetry_revision) as revisions:
            runtime=NetworkTelemetryRuntime()
            actual_dag_packets=[]
            runtime.updated.connect(lambda raw:actual_dag_packets.append(json.loads(raw)))
            try:
                runtime.set_view('DAG');pump(170)
                assert revisions.call_count>=3,revisions.call_count
                assert 1<=copies.call_count<=2,copies.call_count
                before_copies=copies.call_count
                owned_dag.build_wave(2,0);pump(70)
                assert copies.call_count>before_copies
                assert actual_dag_packets[-1]['parallel_dag']['blocks_admitted']==2
                dag_revision_reads=revisions.call_count;dag_graph_copies=copies.call_count
            finally:runtime.close()
    finally:owned_dag.stop()
    report={'status':'PASS','source_thread_is_gui':False,'maximum_inflight':maximum,
            'queued_notifications_when_gui_blocked':1,'coalesced_actual_reads':coalesced_reads,
            'slow_source_maximum_inflight':max_active,'slow_source_reads':len(slow_calls),
            'minimum_slow_read_start_gap_ms':round(min(gaps)*1000,3),
            'hidden_reads_after_pause':0,'stale_generation_packets':0,
            'sanitized_failure_and_recovery':True,'closed_worker_alive':False,
            'cheap_dag_revision_reads':dag_revision_reads,'changed_dag_graph_copies':dag_graph_copies}
    print(json.dumps(report))


def qml_fixture(directory):
    from PySide6.QtCore import QObject,Signal,Slot,QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine,QQmlExpression,qmlContext
    from PySide6.QtQuick import QQuickItem
    from PySide6.QtTest import QTest
    app=QGuiApplication([])
    app.setQuitOnLastWindowClosed(False)
    initial={'assets':[],'ui_operation':{'state':'idle','name':'fixture-user-action'},
             'wallet_overview':{'fixture_preserved':'wallet-value'},
             'testnet':{'state':'RUNNING','session':'fixture-session-A','production':False,
                        'chain_number':31337,'binding':'LOOPBACK_ONLY','height':10,
                        'contract':'0x'+'a'*40,
                        'accounts':[{'address':'0x'+str(i)*40,'native':'1','token':'100'} for i in (1,2)],
                        'block_graph':{'observed_at':1000,'blocks':[],'edges':[]}}}
    class Host(QObject):
        networkTelemetryUpdated=Signal(str)
        def __init__(self):super().__init__();self.views=[];self.calls=0
        @Slot(result=str)
        def omniStatus(self):return json.dumps(initial)
        @Slot(str)
        def setNetworkTelemetryView(self,page):self.views.append(page)
        @Slot(str,str,result=str)
        def omniAction(self,name,raw):self.calls+=1;return json.dumps(initial)
    host=Host();engine=QQmlApplicationEngine();warnings=[]
    engine.warnings.connect(lambda rows:warnings.extend(row.toString() for row in rows))
    engine.rootContext().setContextProperty('fixtureHost',host)
    source='''import QtQuick
import QtQuick.Controls
import COMPONENTS
ApplicationWindow {id:shell;width:1100;height:700;visible:true
 property var savedFullState:null
 property int fullStateChanges:0
 Connections {target:hub;function onStateChanged(){shell.fullStateChanges++}}
 OmniSurface {id:hub;objectName:'hub';anchors.fill:parent;surfaceHost:fixtureHost;page:'TESTNET'}
}'''.replace('COMPONENTS',json.dumps((ROOT/'qml/components').as_uri()))
    engine.loadData(source.encode(),QUrl.fromLocalFile(str(directory/'fixture.qml')))
    assert engine.rootObjects(),warnings
    window=engine.rootObjects()[0];hub=window.findChild(QQuickItem,'hub');assert hub
    def js(code,owner=None):
        owner=owner or hub
        expression=QQmlExpression(qmlContext(owner),owner,code)
        result=expression.evaluate()
        assert not expression.hasError(),expression.error().toString()
        return result[0] if isinstance(result,tuple) else result
    def patch(body):
        host.networkTelemetryUpdated.emit(json.dumps(body));app.processEvents()
    def full(body):
        js('apply('+json.dumps(json.dumps(body))+')')
    try:
        QTest.qWait(50)
        assert host.views[-1]=='TESTNET'
        dashboard=window.findChild(QQuickItem,'testnetDashboard');assert dashboard
        # Select a distinct public recipient in the actual owned control.
        recipient=window.findChild(QQuickItem,'testnetRecipient');assert recipient
        recipient.setProperty('currentIndex',1)
        assert dashboard.property('canPrepare'),'Fixture must start with a valid disposable transfer form'
        js('savedFullState=hub.state',window)
        full_changes=window.property('fullStateChanges')
        patch({'network_page':'TESTNET','testnet':{'state':'RUNNING','session':'fixture-session-A',
              'height':20,'measurements':[{'operation':'rpc','elapsed_ms':3.0,'observed_at':time.time()}],
              'block_graph':{'observed_at':1002,'blocks':[],'edges':[]}}})
        assert js('networkState.testnet.height')==20
        # A high-rate observation lane must update only live instruments. The
        # full wallet/action snapshot and its JS reference remain unchanged.
        for i in range(20):
            patch({'network_page':'TESTNET','testnet':{'state':'RUNNING','session':'fixture-session-A',
                  'height':i+1,'block_graph':{'observed_at':1002.01+i/1000,'blocks':[],'edges':[]}}})
        assert js('networkState.testnet.height')==20
        assert js('hub.state===savedFullState',window)
        assert window.property('fullStateChanges')==full_changes
        assert js('state.testnet.height')==10
        assert js('state.ui_operation.name')=='fixture-user-action'
        assert js('state.wallet_overview.fixture_preserved')=='wallet-value'
        assert js('state.testnet.accounts.length')==2
        patch({'network_page':'DAG','parallel_dag':{'state':'RUNNING','chain_id':'wrong-page'}})
        assert js('networkState.testnet.height')==20
        patch({'network_page':'TESTNET','testnet':{'state':'RUNNING','session':'fixture-session-A',
              'height':9,'block_graph':{'observed_at':999,'blocks':[],'edges':[]}}})
        assert js('networkState.testnet.height')==20
        patch({'network_page':'TESTNET','testnet':{'state':'RUNNING','session':'fixture-session-B',
              'height':999,'block_graph':{'observed_at':5000,'blocks':[],'edges':[]}}})
        assert js('networkState.testnet.height')==20,'A different node session must not overwrite current state'
        patch({'network_page':'TESTNET','error':'GG_NETWORK_OBSERVATION_FAILED'})
        assert js('networkState.testnet.state')=='READ_FAILED','Failed observer must mark old data stale'
        assert js('networkState.testnet.block_graph.stale') is True
        assert js('state.testnet.state')=='RUNNING'
        assert js('hub.state===savedFullState',window)
        assert not dashboard.property('canPrepare'),'Observed read failure must disable the actual transfer control'
        assert dashboard.property('observedState')=='READ_FAILED'
        assert js('state.ui_operation.name')=='fixture-user-action'
        assert js('state.wallet_overview.fixture_preserved')=='wallet-value'
        failed_at=js('networkState.testnet.observation_at')
        assert failed_at>=time.time()-2
        # A full account/wallet response queued before the observer failure is
        # not evidence of recovery. Retain READ_FAILED and the stale graph.
        full(deepcopy(initial))
        assert js('networkState.testnet.state')=='READ_FAILED'
        assert js('networkState.testnet.block_graph.stale') is True
        assert js('networkState.testnet.height')==20

        # A genuinely newer full observation is valid recovery evidence too.
        # Its observation timestamp, rather than a cached graph timestamp,
        # orders the response after the independently observed failure.
        recovered_at=max(time.time(),failed_at+.001)
        recovered=deepcopy(initial)
        recovered['testnet'].update(state='RUNNING',height=21,error='',observation_at=recovered_at,
                                    block_graph={'observed_at':1003,'stale':False,'blocks':[],'edges':[]})
        full(recovered)
        assert js('networkState.testnet.state')=='RUNNING' and js('networkState.testnet.error')==''
        assert js('networkState.testnet.height')==21
        assert dashboard.property('canPrepare')
        full(deepcopy(initial))
        assert js('networkState.testnet.height')==21,'A queued old full response must not undo verified full recovery'
        assert js('networkState.testnet.state')=='RUNNING'
        patch({'network_page':'TESTNET','testnet':{'state':'RUNNING','session':'fixture-session-A',
              'height':22,'error':'','observation_at':recovered_at+.001,
              'block_graph':{'observed_at':1004,'stale':False,'blocks':[],'edges':[]}}})
        assert js('networkState.testnet.state')=='RUNNING' and js('networkState.testnet.error')==''

        hub.setVisible(False);QTest.qWait(30)
        assert host.views[-1]==''
        patch({'network_page':'TESTNET','testnet':{'state':'RUNNING','session':'fixture-session-A',
              'height':900,'block_graph':{'observed_at':9000,'blocks':[],'edges':[]}}})
        assert js('networkState.testnet.height')==22
        hub.setVisible(True);QTest.qWait(30)
        assert host.views[-1]=='TESTNET'
        window.showMinimized();QTest.qWait(30)
        assert host.views[-1]==''
        window.showNormal();QTest.qWait(30)
        assert host.views[-1]=='TESTNET'
        hub.setProperty('page','DAG');QTest.qWait(30)
        assert host.views[-1]=='DAG'
        before_wrong_page=js('networkState.testnet.height')
        patch({'network_page':'TESTNET','testnet':{'height':10000}})
        assert js('networkState.testnet.height')==before_wrong_page
        # A CLI that starts after Desktop is open must replace only the stopped
        # local view. Its public observer never acquires node-control authority.
        cli={'state':'RUNNING','chain_id':'fixture-cli-chain','producer_count':6,
             'blocks_admitted':3,'transactions_validated':24,
             'lan':{'state':'READY','label':'Linux CLI','connection_state':'CONNECTED'},
             'lan_setup':{'active':True,'coordinator':False},
             'observation':{'source':'LOCAL_CLI','read_only':True,'stale':False,
                            'publisher_started_at':123,'publication_sequence':3,'node_label':'Linux CLI'},
             'block_graph':{'topology':'MULTIPARENT_DAG','source':'LAN_SIGNED_PROPOSAL_DAG',
                            'producer_count':6,'blocks':[],'edges':[],'observed_at':1000}}
        patch({'network_page':'DAG','observed_monotonic':100,'parallel_dag':cli})
        assert js('networkState.parallel_dag.transactions_validated')==24
        dag=window.findChild(QQuickItem,'parallelDagDashboard');assert dag
        assert dag.property('observerReadOnly') and not dag.property('canAct')
        old_cli=json.loads(json.dumps(cli));old_cli['transactions_validated']=9999
        old_cli['observation']['publication_sequence']=2
        patch({'network_page':'DAG','observed_monotonic':101,'parallel_dag':old_cli})
        assert js('networkState.parallel_dag.transactions_validated')==24
        cli['observation']['stale']=True;cli['block_graph']['stale']=True
        cli['lan']['connection_state']='STALE'
        patch({'network_page':'DAG','observed_monotonic':102,'parallel_dag':cli})
        assert js('networkState.parallel_dag.observation.stale') is True
        protected=js('mergeTelemetry({parallel_dag:{state:"RUNNING",chain_id:"owned-desktop",lan_setup:{active:true}}},'+json.dumps({'network_page':'DAG','parallel_dag':cli})+').parallel_dag.chain_id')
        assert protected=='owned-desktop'
        patch({'network_page':'DAG','observed_monotonic':103,'parallel_dag':{'state':'STOPPED','chain_id':'','block_graph':{'blocks':[],'edges':[]}}})
        assert js('networkState.parallel_dag.state')=='STOPPED'
        patch({'network_page':'DAG','observed_monotonic':102,'parallel_dag':cli})
        assert js('networkState.parallel_dag.state')=='STOPPED','Late queued CLI data must not resurrect a closed source'
        hub.setProperty('page','WALLET');QTest.qWait(30)
        assert host.views[-1]==''
        assert host.calls==0
        assert not warnings,warnings
        print(json.dumps({'status':'PASS','real_qml':True,'wallet_and_operation_preserved':True,
                          'wrong_page_and_session_rejected':True,'older_graph_rejected':True,
                          'failure_marks_stale_and_recovers':True,'hide_minimize_view_cancel':True,
                          'queued_full_failure_and_recovery_ordering':True,
                          'fast_packets_preserve_full_state_reference':True,
                          'observed_failure_disables_prepare':True,
                          'node_actions':0,'warnings':len(warnings)}))
    finally:
        window.close();engine.deleteLater();app.processEvents()


class NetworkTelemetryTests(unittest.TestCase):
    def check_fixture(self,kind):
        with tempfile.TemporaryDirectory(prefix='gg-network-observer-fixture-') as directory:
            env=os.environ.copy();env.update(QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software',QT_QUICK_CONTROLS_STYLE='Basic',GG_DESKTOP_STATE_ROOT=str(Path(directory)/'state'),GG_DESKTOP_DATA_ROOT=str(Path(directory)/'data'))
            result=subprocess.run([sys.executable,'-X','utf8','-B',str(Path(__file__).resolve()),'--'+kind,directory],cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',timeout=25)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            print(result.stdout.strip())
    def test_worker_is_bounded_visible_only_and_failure_recovers(self):self.check_fixture('worker')
    def test_qml_merge_preserves_wallet_and_cancels_hidden_or_wrong_session(self):self.check_fixture('qml')


if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--worker':worker_fixture(Path(sys.argv[2]))
    elif len(sys.argv)==3 and sys.argv[1]=='--qml':qml_fixture(Path(sys.argv[2]))
    else:unittest.main()
