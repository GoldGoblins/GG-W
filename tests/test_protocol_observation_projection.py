"""Protocol CLI/Desktop integration and bounded certified-summary presentation.

The packet shapes below are presentation fixtures, never cryptographic evidence.
Native verification is the caller's prerequisite to _remember_block. These tests
exercise projection, process-owned observation I/O and the actual QML component.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from backend.gg_protocol_runtime import ProtocolRuntime
from backend import local_node_observation as observation
from backend import gg_local_history_status as history_status
from tests.test_local_history_status import report as history_report


def digest(label):return hashlib.sha256(label.encode()).hexdigest()


def projection_fixture():
    runtime=ProtocolRuntime();anchor=digest('presentation-genesis')
    owner=digest('owner');creator=digest('single-creator');other=digest('other-creator');worker=digest('separate-worker')
    public={'label':'Linux','public_keys':[owner,creator,other]}
    runtime.owner=SimpleNamespace(name='Linux',snapshot=lambda:{'enabled':True,'profile':'Linux'},descriptor=lambda:deepcopy(public))
    runtime.node=SimpleNamespace(anchor={'genesis_hash':anchor,'genesis':{
        'chain_id':'presentation-chain','financial_dag':{'network_id':digest('presentation-network')},
        'protocol':{'environment':'TESTNET'}}},node_key=digest('presentation-replica-node'),
        profile=SimpleNamespace(name='LinuxReplica'),role='REPLICA',settings={'peers':[]},_alive=lambda:True)
    runtime._view={'mode':'FINANCIAL_SDK_CERTIFIED_VIEW','state':'RUNNING','environment':'TESTNET','chain_id':'presentation-chain',
        'certificate_height':42,'state_root':digest('presentation-state'),'network_contact_at':time.time(),'connection_state':'CONNECTED',
        'peers':[{'node_id':digest('peer'),'label':'Windows'}],
        'certified_blocks':'9007199254740993','certified_transactions':'5000','rejected_transactions':'1','producer_count':6,
        'account_tree':{'count':'5001'},'economic_state':{'next_epoch':'7','issued_atomic':'18446744073709551615'},
        'producers':[{'index':0,'producer_key':creator,'owner_peer_key':owner,'node_key':worker,'display_name':'Linux <signed label>',
            'label':'Linux <signed label>','platform':'LINUX','record_height':41,'proposals':'23','transactions':'5001','certified_sequence':'23',
            'local':True,'local_signer_ready':False}], 'committee':[]}
    local_report=history_report();local_report['genesis_hash']=anchor
    runtime._view['local_history']=history_status.observation(local_report,anchor,'REPLICA',running=True,observed_at=time.time())
    observed_at=time.time()
    runtime.node.local_history_observation=lambda:history_status.observation(local_report,anchor,runtime.node.role,running=runtime.node._alive(),observed_at=observed_at)
    def packet(label,index,rank,parents,sequence='23',genesis=anchor,height=41):
        return {'genesis_hash':genesis,'state':{'height':height},'financial_block':{
            'context':{'block_hash':digest(label),'order_index':index},
            'creator':{'key':creator,'sequence':sequence,'rank':rank,'parents':parents,'worker_key':worker,'work_hash':digest('actual-work-'+label)},
            'summary':{'transactions':5000,'applied':4999,'rejected':1}}}
    # Arrival is deliberately newest-first: ancestor lookup arrives afterwards.
    newest=packet('child','9007199254740993','9007199254740993',[digest('parent')])
    older=packet('parent','9007199254740992','9007199254740992',[digest('unfetched-origin')],sequence='22')
    runtime._remember_block(newest);runtime._remember_block(older)
    runtime._observations.extend([(100.,100,10000),(102.,110,20000)])
    return runtime,packet


class ProtocolObservationProjection(unittest.TestCase):
    def test_all_foreground_protocol_roles_keep_exact_accounts_and_economics(self):
        from backend.terminal_cli import foreground_summary
        runtime,_=projection_fixture();body=runtime.snapshot()
        body['own_financial_accounts']=[{'address':digest('wallet'),'balance_atomic':'18446744073709551615','nonce':'9007199254740993'}]
        for command in ('protocol.run','protocol.node_start','protocol.light_start'):
            with self.subTest(command=command):
                result=foreground_summary(command,body)
                self.assertEqual(result['engine'],'DAGOBLIN_NATIVE_PROTOCOL')
                self.assertEqual(result['certified_blocks'],'9007199254740993')
                self.assertEqual(result['own_accounts'],body['own_financial_accounts'])
                self.assertEqual(result['economy'],body['economic_state'])
                self.assertEqual(result['local_history'],body['local_history'])
                self.assertEqual(result['local_history']['report']['verified_through'],'9007199254740993')
                self.assertNotIn('FIXED_PRIVATE_TEST_ALLOCATION',json.dumps(result))
                self.assertFalse(result['payments_executed_from_transport_ack'])

    def test_light_foreground_refresh_stays_in_the_started_protocol_runtime(self):
        from backend import terminal_cli
        runtime,_=projection_fixture();dispatch=Mock(side_effect=KeyboardInterrupt)
        with patch.object(terminal_cli.time,'sleep',return_value=None),patch('builtins.print'):
            with self.assertRaises(KeyboardInterrupt):
                terminal_cli.foreground_session(SimpleNamespace(dispatch=dispatch),'protocol.light_start',runtime.snapshot(),json_output=True)
        dispatch.assert_called_once_with('protocol.status',{})

    def test_summary_keeps_single_creator_separate_from_work_and_unknown_parents(self):
        runtime,_=projection_fixture();view=runtime.snapshot();graph=view['block_graph']
        self.assertEqual([row['canonical_index'] for row in graph['blocks']],['9007199254740992','9007199254740993'])
        self.assertEqual(graph['edges'],[{'from':digest('parent'),'to':digest('child')}])
        self.assertEqual({row['proposer_key'] for row in graph['blocks']},{digest('single-creator')})
        self.assertEqual({row['worker_key'] for row in graph['blocks']},{digest('separate-worker')})
        self.assertEqual([row['layout_rank'] for row in graph['blocks']],[0,1])
        self.assertTrue(all(row['canonical_membership_verified'] and row['sdk_admission_verified'] for row in graph['blocks']))
        self.assertFalse(any(row['payload_authenticated'] or row['signature_verified'] for row in graph['blocks']))
        self.assertEqual(graph['metrics']['bps'],5)
        self.assertEqual(graph['metrics']['tps'],5000)
        self.assertEqual(graph['metrics']['tps_basis'],'APPLIED_PAYMENTS')
        self.assertTrue(graph['partial_history']);self.assertEqual(graph['registered_producer_count'],6)

    def test_partial_poll_cannot_publish_future_or_other_network_blocks(self):
        runtime,packet=projection_fixture()
        runtime._remember_block(packet('future','9007199254740994','9007199254740994',[digest('child')],height=42))
        runtime._remember_block(packet('foreign','9007199254740995','9007199254740995',[digest('child')],genesis=digest('other-genesis')))
        view=runtime.snapshot()
        for rows in (view['block_graph']['blocks'],view['dag_proofs']['proven_blocks']):
            self.assertEqual({row['hash'] for row in rows},{digest('parent'),digest('child')})
        self.assertEqual(len(view['block_graph']['edges']),1)

    def test_root_certificate_persists_when_transport_contact_expires(self):
        runtime,_=projection_fixture();runtime._view['network_contact_at']=time.time()-6
        view=runtime.snapshot()
        self.assertEqual(view['lan']['connection_state'],'UNOBSERVED')
        self.assertEqual(view['lan']['authenticated_peers'],[])
        self.assertTrue(view['block_graph']['stale'])
        self.assertTrue(view['dag_proofs']['canonical_finality'])
        self.assertFalse(view['dag_proofs']['history_replayed'])
        self.assertEqual(view['dag_consensus']['certificate_height'],42)

    def test_missing_root_or_height_never_claims_certificate(self):
        for field in ('state_root','certificate_height'):
            runtime,_=projection_fixture();runtime._view[field]=None
            view=runtime.snapshot()
            self.assertFalse(view['dag_proofs']['canonical_finality'])
            self.assertEqual(view['dag_proofs']['proven_blocks'],[])
            self.assertEqual(view['block_graph']['blocks'],[])
            self.assertIsNone(view['dag_consensus']['certificate_height'])

    def test_new_source_reset_clears_observations_but_preserves_open_profiles(self):
        runtime,_=projection_fixture();runtime._account_views=[{'profile':'old-network','balance_atomic':'10'}]
        runtime._relay_views={'old-account':{'state':'DURABLE_RECEIVER_ORIGINALS'}}
        runtime._proof_pending.append((digest('pending-parent'),1));runtime._proof_phase=3
        account=object();runtime.accounts['protected-wallet']=account
        runtime._reset_observation()
        self.assertIsNone(runtime._view);self.assertEqual(runtime._account_views,[])
        self.assertEqual(runtime._proven_blocks,{});self.assertFalse(runtime._observations)
        self.assertFalse(runtime._proof_pending);self.assertEqual(runtime._proof_phase,0)
        self.assertEqual(runtime._relay_views,{});self.assertIs(runtime.accounts['protected-wallet'],account)

    def test_actual_protocol_snapshot_crosses_readonly_process_owned_observation(self):
        runtime,_=projection_fixture();source=runtime.snapshot()
        with tempfile.TemporaryDirectory() as temporary:
            publisher=observation.Publisher(Path(temporary)/'observations')
            try:
                publisher.publish(source);reader=observation.Reader(publisher.root);view=reader.snapshot()
                self.assertIsNotNone(view)
                self.assertTrue(view['observation']['read_only']);self.assertFalse(view['observation']['stale'])
                for field in ('block_graph','dag_proofs','own_financial_accounts','economic_state','protocol_network','local_history'):
                    self.assertEqual(view[field],source[field])
                packet=json.loads(publisher.path.read_bytes())
                with patch.object(observation.time,'monotonic',return_value=packet['published_monotonic']+6):
                    view=reader.snapshot()
                self.assertEqual(view['lan']['connection_state'],'STALE');self.assertTrue(view['block_graph']['stale'])
                self.assertTrue(view['dag_proofs']['canonical_finality'])
                self.assertEqual(view['local_history']['state'],'STALE')
                self.assertEqual(view['local_history']['report'],source['local_history']['report'])
                self.assertEqual(source['local_history']['state'],'READY')
            finally:publisher.close()

    def test_protocol_observation_scope_does_not_admit_other_mode_or_environment(self):
        runtime,_=projection_fixture();source=runtime.snapshot()
        variants=[('scope','OTHER_NETWORK'),('mode','OTHER_MODE'),('environment','MAINNET'),('protocol_mode','PUBLIC_NETWORK')]
        for field,value in variants:
            body=deepcopy(source)
            if field=='scope':body['lan']['scope']=value
            elif field=='protocol_mode':body['protocol_network']['mode']=value
            else:body[field]=value
            with self.subTest(field=field),tempfile.TemporaryDirectory() as temporary:
                publisher=observation.Publisher(Path(temporary)/'observations')
                try:
                    publisher.publish(body);self.assertIsNone(observation.Reader(publisher.root).snapshot())
                finally:publisher.close()

    def test_readonly_boundary_rejects_foreign_history_and_a_light_cannot_inherit_ready(self):
        for kind in ('foreign_genesis','malformed_schema','light_role','conflicting_role'):
            runtime,_=projection_fixture();body=runtime.snapshot()
            if kind=='foreign_genesis':body['local_history']['report']['genesis_hash']=digest('foreign-history')
            elif kind=='malformed_schema':body['local_history']['schema']='FOREIGN'
            elif kind=='light_role':body['protocol_network']['node_role']='LIGHT';body['role']='LIGHT'
            else:body['role']='LIGHT'
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as temporary:
                publisher=observation.Publisher(Path(temporary)/'observations')
                try:
                    publisher.publish(body);view=observation.Reader(publisher.root).snapshot()
                    self.assertIsNotNone(view)
                    self.assertEqual(view['local_history']['state'],'NOT_APPLICABLE' if kind=='light_role' else 'UNAVAILABLE')
                    self.assertIsNone(view['local_history']['report'])
                    self.assertEqual(view['certified_transactions'],body['certified_transactions'])
                finally:publisher.close()

    def test_malformed_publisher_clock_cannot_crash_the_readonly_source_reader(self):
        runtime,_=projection_fixture();body=runtime.snapshot()
        for field in ('published_monotonic','process_started'):
            with self.subTest(field=field),tempfile.TemporaryDirectory() as temporary:
                publisher=observation.Publisher(Path(temporary)/'observations')
                try:
                    publisher.publish(body);packet=json.loads(publisher.path.read_bytes())
                    packet[field]=10**1000;publisher.path.write_text(json.dumps(packet),encoding='utf-8')
                    self.assertIsNone(observation.Reader(publisher.root).snapshot())
                finally:publisher.close()


def qml_fixture():
    from PySide6.QtCore import QCoreApplication,QEvent,QObject,QUrl,Qt
    from PySide6.QtQml import QQmlApplicationEngine,QQmlExpression,QQmlNetworkAccessManagerFactory,qmlContext
    from PySide6.QtNetwork import QNetworkAccessManager,QNetworkRequest
    from PySide6.QtQuick import QQuickItem
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    runtime,_=projection_fixture();literal='<b>Linux</b><img src="https://invalid.example/x">'
    runtime._view['producers'][0].update(display_name=literal,label=literal)
    body=runtime.snapshot();body['observation']={'read_only':True,'stale':False}
    own_journal={'schema':'gg.protected.journal-status.v1','kind':'ACCOUNT_ORIGINALS',
        'total_records':'9007199254740993','active_records':'1','archived_records':'9007199254740992',
        'archive_segments':'4','active_payload_bytes':'18446744073709551615',
        'verification_scope':'OWN_SEALED_FULL_STREAMING_COLD_REPLAY',
        'warm_verification':'FILE_IDENTITY_INVENTORY_AND_AUTHENTICATED_RECORD_AT_USE',
        'snapshot_trust_used':False,'native_global_state_authority':False,'whole_disk_rollback_protection':False}
    body['protocol_network']['own_journals']={'schema':'gg.protected.journal-sources.v1',
        'accounts':[{'profile':'wallet','address':digest('wallet'),'signed_batches_exact':'9007199254740993','journal':own_journal}]}
    body['protocol_network']['pools']=[{'name':'pool','retained_events_exact':'9007199254740993',
        'own_journal':{**own_journal,'kind':'POOL_EVENTS'}}]
    # Exercise QML ordering independently of the canonical backend sort.
    body['dag_proofs']['proven_blocks'].reverse()
    app=QApplication([]);engine=QQmlApplicationEngine();warnings=[];image_requests=[]
    class OfflineManager(QNetworkAccessManager):
        def createRequest(self,operation,request,outgoing=None):
            image_requests.append(request.url().toString())
            # A regression cannot contact the supplied URL while being tested.
            return super().createRequest(operation,QNetworkRequest(QUrl('data:,blocked')),outgoing)
    class OfflineFactory(QQmlNetworkAccessManagerFactory):
        def __init__(self):super().__init__();self.managers=[]
        def create(self,parent):
            manager=OfflineManager(parent);self.managers.append(manager);return manager
    factory=OfflineFactory();engine.setNetworkAccessManagerFactory(factory)
    engine.warnings.connect(lambda rows:warnings.extend(row.toString() for row in rows))
    engine.rootContext().setContextProperty('projectionJSON',json.dumps({'parallel_dag':body,'ui_operation':{}}))
    source='''import QtQuick
import QtQuick.Controls
import COMPONENTS
ApplicationWindow {width:1100;height:760;visible:true
GGParallelDagDashboard {anchors.fill:parent;state:JSON.parse(projectionJSON)}}
'''.replace('COMPONENTS',json.dumps((ROOT/'qml/components').as_uri()))
    engine.loadData(source.encode(),QUrl.fromLocalFile(str(ROOT/'tests/protocol-projection-fixture.qml')))
    assert engine.rootObjects(),warnings
    window=engine.rootObjects()[0];dashboard=window.findChild(QQuickItem,'parallelDagDashboard');qt_references=[]
    def js(code):
        expression=QQmlExpression(qmlContext(dashboard),dashboard,code);value=expression.evaluate()
        assert not expression.hasError(),expression.error().toString()
        value=value[0] if isinstance(value,tuple) else value
        return value.toVariant() if hasattr(value,'toVariant') else value
    def find(name):
        found=window.findChild(QObject,name)
        if found is None and name=='dagProducerName':
            # A ListView owns delegates in its visual scene, outside the
            # ApplicationWindow QObject subtree. Ask the real view directly.
            view=window.findChild(QQuickItem,'dagProducersList')
            expression=QQmlExpression(qmlContext(view),view,'itemAtIndex(0)')
            delegate=expression.evaluate();delegate=delegate[0] if isinstance(delegate,tuple) else delegate
            assert not expression.hasError() and isinstance(delegate,QQuickItem)
            found=delegate.findChild(QObject,name)
            qt_references.extend((expression,delegate,found))
        if found is None and name.startswith(('dagOwnAccountJournal_','dagOwnPoolJournal_')):
            # Repeater delegates are real visual children; QObject.findChild
            # alone does not traverse their scene ownership consistently.
            repeater_name='dagOwnAccountJournals' if name.startswith('dagOwnAccountJournal_') else 'dagOwnPoolJournals'
            repeater=window.findChild(QQuickItem,repeater_name)
            assert repeater is not None and repeater.property('count')==1,repeater_name
            expression=QQmlExpression(qmlContext(repeater),repeater,'itemAt(0)')
            delegate=expression.evaluate();delegate=delegate[0] if isinstance(delegate,tuple) else delegate
            assert not expression.hasError() and isinstance(delegate,QQuickItem),repeater_name
            assert delegate.objectName()==name,delegate.objectName()
            found=delegate;qt_references.extend((expression,delegate))
        if found is None and name=='blockPlainTooltipLoader':
            graph_item=window.findChild(QQuickItem,'dagBlockRelationsGraph')
            expression=QQmlExpression(qmlContext(graph_item),graph_item,'_nodeItems[_nodeOrder[0]]')
            node=expression.evaluate();node=node[0] if isinstance(node,tuple) else node
            assert not expression.hasError() and isinstance(node,QQuickItem)
            found=node.findChild(QObject,name)
            qt_references.extend((expression,node,found))
        assert found is not None,name
        return found
    try:
        QTest.qWait(100)
        assert not dashboard.property('canAct')
        assert js('proofRows[0].canonical_index')=='9007199254740993'
        assert js('proofRows[1].canonical_index')=='9007199254740992'
        assert js('originalParentCount('+json.dumps(digest('child'))+')')==1
        assert js('metricAt(3).value')=='6' and 'inbjudna' not in js('metricAt(3).detail')
        assert js('producerKeyName('+json.dumps(digest('single-creator'))+')')==literal+' · egen'
        assert find('dagCanonicalFinality').property('value')=='SDK-certifierat tillstånd'
        assert find('dagConsensusCertificate').property('value')=='Höjd 42'
        assert find('dagLocalHistoryStatus').property('value')==js('localHistoryLabel()')
        assert find('dagLocalHistoryAudit').property('value')=='9007199254740993 / 9007199254740995'
        assert find('dagLocalHistoryActive').property('value')=='9007199254740997 byte'
        assert find('dagLocalHistoryArchive').property('value')=='4 segment \u00b7 9007199254740999 byte'
        assert js('localHistory.report.checkpoint_trusted') is False
        assert js('localHistory.is_sdk_certificate') is False
        assert js('localHistory.is_peer_contact') is False
        assert find('dagOwnAccountJournal_wallet').property('value')=='9007199254740993 batch \u00b7 4 arkiv'
        assert find('dagOwnPoolJournal_pool').property('value')=='9007199254740993 h\u00e4ndelser \u00b7 4 arkiv'
        assert '18446744073709551615' in js('ownJournalDetails(ownJournalAccounts[0].journal)')
        assert js('ownJournalCounter(undefined)')=='\u2014'
        assert js('ownJournalCounter(9007199254740992)')=='\u2014'
        graph=find('dagBlockRelationsGraph')
        assert graph.property('certifiedSummaryWindow') and graph.property('shownCount')==2 and graph.property('edgeCount')==1
        assert 'SDK-SUMMERINGAR' in find('blockRelationsScope').property('text')
        assert find('dagProducerTransactionColumn').property('text')=='TX-försök'
        assert 'Observerad' in find('dagObservedPaymentRate').property('name')
        assert 'Observerade' in graph.property('speedCaption')
        graph_expression=QQmlExpression(qmlContext(graph),graph,'_allRows[1].rank_text+" / "+_allRows[1].sequence_text')
        result=graph_expression.evaluate();result=result[0] if isinstance(result,tuple) else result
        assert not graph_expression.hasError() and result=='9007199254740993 / 23',result
        assert find('dagProducersList').property('count')==1
        producer=find('dagProducerName');producer.setProperty('tipDelay',0);producer.setProperty('tipActive',True)
        # Tooltips for graph points are created only on demand, preserving idle
        # point-map cost. Force the same loader that an actual hover activates.
        tooltip_loader=find('blockPlainTooltipLoader');assert not tooltip_loader.property('active')
        tooltip_loader.setProperty('active',True);QTest.qWait(80)
        for tooltip_name,text_name in (('dagPlainTooltip','dagPlainTooltipText'),('blockPlainTooltip','blockPlainTooltipText')):
            sources=[window,producer,graph,*[item for item in qt_references if isinstance(item,QQuickItem)]]
            tips=[tip for source in sources for tip in source.findChildren(QObject,tooltip_name) if literal in str(tip.property('text'))]
            assert tips,(tooltip_name,'literal tooltip missing')
            for tip in tips:
                text=tip.property('contentItem');assert text is not None and text.objectName()==text_name
                format_check=QQmlExpression(qmlContext(tip),tip,'contentItem.textFormat === Text.PlainText')
                plain=format_check.evaluate();plain=plain[0] if isinstance(plain,tuple) else plain
                assert not format_check.hasError() and plain is True
                assert text.property('text')==tip.property('text')
        # Archive work, completed audit and actual node readiness are distinct.
        # The public numeric strings must remain exact beyond JS safe integers.
        restoring=deepcopy(body);restoring['protocol_network']['node_role']='REPLICA'
        restoring['lan']['participation']['role']='replica'
        startup={'schema':'gg.owned.archive-start-observation.v1','phase':'FULL_ORIGINAL_AUDIT',
            'processed_height':'9007199254740993','verified_through':None,'last_error':'',
            'basis':'LOCAL_OWNED_NATIVE_PIPE_REPORT','node_ready':False,'full_original_audit_completed':False,
            'snapshot_trust_used':False,'certificate_is_network_liveness':False,
            'network_contact_asserted':False,'consensus_signing':False}
        restoring['protocol_network']['archive_startup']=startup
        def show_restore():
            js('state='+json.dumps({'parallel_dag':restoring,'ui_operation':{}}));QTest.qWait(20)
        show_restore()
        assert find('dagArchiveStartupStatus').property('visible')
        assert find('dagArchiveStartupStatus').property('value')=='Verifierar arkivets original'
        assert find('dagArchiveStartupProgress').property('value')=='9007199254740993 / \u2014'
        startup.update(phase='APPLICATION_RESTORED',processed_height='9007199254740995',
                       verified_through='9007199254740993',full_original_audit_completed=True)
        show_restore()
        assert find('dagArchiveStartupProgress').property('value')=='9007199254740995 / 9007199254740993'
        assert find('dagArchiveStartupStatus').property('value')=='Tillst\u00e5nd \u00e5terst\u00e4llt'
        startup.update(phase='READY',node_ready=False);show_restore()
        assert find('dagArchiveStartupStatus').property('value')=='Nodstart ej bekr\u00e4ftad'
        startup['node_ready']=True;show_restore()
        assert find('dagArchiveStartupStatus').property('value')=='Nodstart bekr\u00e4ftad'
        assert js('archiveStartup.network_contact_asserted') is False
        startup.update(phase='STOPPED',node_ready=False);show_restore()
        assert find('dagArchiveStartupStatus').property('value')=='Noden stoppad'
        startup.update(phase='UNAVAILABLE',processed_height=None,verified_through=None,
                       node_ready=False,full_original_audit_completed=False);show_restore()
        assert find('dagArchiveStartupStatus').property('value')=='Ej tillg\u00e4nglig'
        assert find('dagArchiveStartupProgress').property('value')=='\u2014 / \u2014'
        startup.update(phase='READY',processed_height='9007199254740995',verified_through='9007199254740993',
                       node_ready=True,full_original_audit_completed=True)
        startup['processed_height']=9007199254740993;show_restore()
        assert find('dagArchiveStartupStatus').property('value')=='Ej tillg\u00e4nglig'
        assert find('dagArchiveStartupProgress').property('value')=='\u2014 / \u2014'
        startup['processed_height']='9223372036854775808';show_restore()
        assert js('archiveStartupValid') is False
        startup['processed_height']='9007199254740995';restoring['observation']['stale']=True;show_restore()
        assert find('dagArchiveStartupStatus').property('value')=='\u00c4ldre CLI-data'
        restoring['observation']['stale']=False;restoring['protocol_network']['node_role']='LIGHT'
        restoring['lan']['participation']['role']='light';show_restore()
        assert not find('dagArchiveStartupStatus').property('visible')
        js('state='+json.dumps({'parallel_dag':body,'ui_operation':{}}));QTest.qWait(20)
        # Loss/staleness applies to the selected CLI source. Historical SDK
        # certificates may remain visible but cannot refresh local audit data.
        stale=deepcopy(body);stale['observation']['stale']=True
        js('state='+json.dumps({'parallel_dag':stale,'ui_operation':{}}));QTest.qWait(20)
        assert find('dagLocalHistoryStatus').property('value')=='\u00c4ldre CLI-data'
        light=deepcopy(body);light['local_history']=history_status.observation(history_report(),digest('ignored'),'LIGHT',running=True)
        js('state='+json.dumps({'parallel_dag':light,'ui_operation':{}}));QTest.qWait(20)
        assert not find('dagLocalHistoryAudit').property('visible')
        assert find('dagLocalHistoryStatus').property('value')=='L\u00e4ttklient \u00b7 ingen lokal replay'
        js('state='+json.dumps({'local_node_sources':{'sources':[],'selection':'EXPLICIT','view_available':True},'ui_operation':{}}));QTest.qWait(20)
        assert js('sourceUnavailable') is True
        assert js('hasLocalHistoryReport') is False
        assert js('localHistoryLabel()')=='Ingen vald CLI-k\u00e4lla'
        assert image_requests==[],image_requests
        assert not warnings,sorted(set(warnings))
        print(json.dumps({'status':'PASS','actual_QML':True,'exact_large_rank_and_position':True,'single_creator_separate_worker':True,
            'real_known_parent_edge':True,'literal_signed_identity':True,'image_fetch_requests':len(image_requests),
            'read_only':True,'active_app_touched':False,'images_captured':False,'warnings':0}))
    finally:
        window.close();engine.setNetworkAccessManagerFactory(None);engine.deleteLater()
        QCoreApplication.sendPostedEvents(engine,QEvent.Type.DeferredDelete);app.processEvents()


class ProtocolQMLProjection(unittest.TestCase):
    def test_actual_offscreen_protocol_projection(self):
        with tempfile.TemporaryDirectory() as temporary:
            env=dict(os.environ,QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software',QT_QUICK_CONTROLS_STYLE='Basic',
                GG_DESKTOP_STATE_ROOT=str(Path(temporary)/'state'),GG_DESKTOP_DATA_ROOT=str(Path(temporary)/'data'))
            run=subprocess.run([sys.executable,'-X','utf8','-B',str(Path(__file__).resolve()),'--qml-fixture'],cwd=ROOT,
                env=env,capture_output=True,text=True,encoding='utf-8',timeout=25)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr);print(run.stdout.strip())


if __name__=='__main__':
    if len(sys.argv)==2 and sys.argv[1]=='--qml-fixture':qml_fixture()
    else:unittest.main()
