"""CLI ownership gates, same-user publication, and actual Qt offscreen projection."""
from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock,patch

from backend import terminal_cli as cli,terminal_service as service
from backend import local_node_observation as observation,portable_wallet_vault as vault
from tests.test_local_node_observation import body


def observers():
    return {'schema':'gg.native.observer-controls.v1','own_running':1,'own_connected':1,'validator_votes':0,
        'certificate_is_network_liveness':False,'profiles':[{
        'profile':'PhoneFull','display_name':'Termux full observer','role':'native_full_observer','state':'RUNNING',
        'native_node_key':'a'*64,'owner_peer_key':'b'*64,'delegating_producer_key':'c'*64,
        'consensus_signing':False,'voting_power':0,'owned_native_process':True,
        'local_state_read_from_owned_sdk':True,'certificate_verified':True,'certificate_height':91,
        'certificate_is_network_liveness':False,'last_error':'',
        'enrollment':{'state':'ACKNOWLEDGED','owners_acknowledged':2,'receipt_is_native_connectivity':False},
        'native_connection':{'state':'CONNECTED','connected':True,'stale':False,'peer_count':4,
            'latest_height':'92','received_bytes':'9007199254740993','sent_bytes':'1000'}}]}


class ObserverCliProjectionTests(unittest.TestCase):
    def test_portable_password_is_prompted_only_for_unlock_and_never_for_priority_stop(self):
        with patch.object(service.assets,'bootstrap'):terminal=service.TerminalService(secret=Mock(return_value='public disposable observer password'))
        self.addCleanup(terminal.close);terminal._portable=True;runtime=Mock();runtime.observer_unlocked.return_value=False
        prior=vault._password.get()
        def dispatch(command,args):
            self.assertIsNotNone(vault._password.get());return {'state':'OPEN'}
        runtime.dispatch.side_effect=dispatch
        with patch.object(terminal,'_lan',return_value=runtime):
            terminal.dispatch('lan.observer_open',{'profile':'PhoneFull'})
            self.assertIs(vault._password.get(),prior);self.assertEqual(terminal.secret.call_count,1)
            runtime.observer_unlocked.return_value=True
            runtime.dispatch.side_effect=lambda command,args:{'state':'RUNNING'}
            terminal.dispatch('lan.observer_start',{'profile':'PhoneFull'})
            runtime.observer_unlocked.return_value=False
            terminal.dispatch('lan.observer_stop',{'profile':'PhoneFull'})
            self.assertEqual(terminal.secret.call_count,1)

    def test_foreground_observer_request_waits_for_real_signed_anchor_and_is_consumed_once(self):
        terminal=Mock();terminal.dispatch.return_value={'dag_consensus':{'anchor_bound':True},'lan':{'state':'READY'}}
        with redirect_stdout(io.StringIO()),patch.object(cli.time,'sleep',side_effect=[None,None,KeyboardInterrupt]):
            with self.assertRaises(KeyboardInterrupt):
                cli.foreground_session(terminal,'lan.resume',{'dag_consensus':{'anchor_bound':False}},json_output=True,
                    observer_profiles=['New','Old'],observer_create=['New'])
        self.assertEqual([row.args[0] for row in terminal.dispatch.call_args_list],
            ['lan.status','lan.observer_create','lan.observer_start','lan.observer_open','lan.observer_start','lan.status'])

    def test_main_passes_owned_foreground_options_and_refuses_other_modes_before_service(self):
        terminal=Mock();terminal.dispatch.return_value={'lan':{'state':'PAIRING'}}
        with redirect_stdout(io.StringIO()),patch.object(cli,'foreground_session',side_effect=KeyboardInterrupt) as run:
            result=cli.main(['--json','--foreground','--command','lan.resume profile=Termux',
                '--observer-profile','Old','--observer-create','New'],lambda:terminal)
        self.assertEqual(result,130);self.assertEqual(run.call_args.kwargs['observer_profiles'],['Old','New'])
        self.assertEqual(run.call_args.kwargs['observer_create'],['New'])
        factory=Mock()
        for arguments in (['--json','--command','lan.status','--observer-profile','A'],
                ['--json','--foreground','--command','lan.start','--observer-create','A'],
                ['--json','--foreground','--command','lan.resume profile=Termux','--observer-profile','A','--observer-create','A']):
            with redirect_stdout(io.StringIO()):self.assertEqual(cli.main(arguments,factory),1)
        factory.assert_not_called()

    def test_real_publication_preserves_exact_native_identity_and_invalidates_stale_contact(self):
        with tempfile.TemporaryDirectory(prefix='gg-observer-view-') as temporary:
            root=Path(temporary);publisher=observation.Publisher(root);self.addCleanup(publisher.close)
            source=body();source['native_observers']=observers();publisher.publish(source)
            reader=observation.Reader(root);result=reader.snapshot()
            self.assertEqual(result['native_observers'],source['native_observers'])
            self.assertEqual(cli.foreground_summary('lan.resume',source)['native_observers'],source['native_observers'])
            packet=json.loads(publisher.path.read_text(encoding='utf-8'));packet['published_monotonic']=time.monotonic()-7
            publisher.path.write_text(json.dumps(packet),encoding='utf-8');reader._last_check=-1e30
            old=reader.snapshot()['native_observers'];row=old['profiles'][0]
            self.assertEqual(old['own_connected'],0);self.assertEqual(row['native_connection']['state'],'STALE')
            self.assertIsNone(old['own_running']);self.assertIsNone(row['owned_native_process'])
            self.assertFalse(row['native_connection']['connected']);self.assertFalse(row['local_state_read_from_owned_sdk'])
            self.assertTrue(row['certificate_verified']);self.assertEqual(row['certificate_height'],91)
            self.assertTrue(source['native_observers']['profiles'][0]['native_connection']['connected'])

    def test_real_Qt_displays_native_sync_fault_and_staleness_separately_from_certificate(self):
        script=r'''
import json,sys
from pathlib import Path
from PySide6.QtCore import QObject,QUrl,Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlEngine,QQmlComponent,QQmlExpression,qmlContext
from PySide6.QtQuick import QQuickItem,QQuickWindow
from tests.test_observer_cli_ui import observers
app=QGuiApplication([]);engine=QQmlEngine();warnings=[]
engine.warnings.connect(lambda rows:warnings.extend(row.toString() for row in rows))
component=QQmlComponent(engine)
component.setData(('import QtQuick\nimport '+json.dumps((Path.cwd()/'qml/components').as_uri())+'\nGGParallelDagDashboard {width:1250;height:820}').encode(),QUrl.fromLocalFile(str(Path(sys.argv[1])/'fixture.qml')))
assert component.isReady(),[row.toString() for row in component.errors()]
root=component.create();assert root is not None
window=QQuickWindow();root.setParentItem(window.contentItem())
dag={'state':'RUNNING','native_observers':observers(),'lan_setup':{'active':True},'lan':{},'observation':{'read_only':True,'stale':False}}
def js(code):
 expression=QQmlExpression(qmlContext(root),root,code);value=expression.evaluate();assert not expression.hasError(),expression.error().toString()
 return value[0] if isinstance(value,tuple) else value
repeater=root.findChild(QObject,'dagNativeObservers');assert repeater is not None
def put():
 js('state='+json.dumps({'parallel_dag':dag}));app.processEvents()
 expression=QQmlExpression(qmlContext(repeater),repeater,'itemAt(0)');value=expression.evaluate();assert not expression.hasError()
 return value[0] if isinstance(value,tuple) else value
row=put();assert row is not None
assert row.property('name')=='PhoneFull' and row.property('value')=='Ansluten'
tip=row.findChild(QObject,'dagNativeObserverInfo');assert tip is not None
format_check=QQmlExpression(qmlContext(tip),tip,'contentItem.textFormat === Text.PlainText')
format_value=format_check.evaluate();assert not format_check.hasError()
assert (format_value[0] if isinstance(format_value,tuple) else format_value) is True
details=js('nativeObserverDetails(nativeObserverRows[0])')
assert 'Termux full observer' in details and '0 röster' in details and '9007199254740993' in details
assert not root.property('canAct')
dag['native_observers']['profiles'][0]['native_connection']['state']='SYNCING';row=put()
assert row.property('value')=='Synkar · höjd 92'
dag['native_observers']['profiles'][0]['state']='FAULT';row=put()
assert row.property('value')=='Process- eller verifieringsfel'
dag['observation']['stale']=True;row=put();assert row.property('value')=='Äldre data'
assert dag['native_observers']['profiles'][0]['certificate_verified']
root.setParentItem(None);root.deleteLater();window.deleteLater();engine.deleteLater();app.processEvents()
assert not warnings,warnings
print('PASS_ACTUAL_OFFSCREEN_QML_NATIVE_OBSERVER_PROJECTION')
'''
        with tempfile.TemporaryDirectory(prefix='gg-observer-ui-') as temporary:
            env=dict(os.environ,QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software',QT_QUICK_CONTROLS_STYLE='Basic')
            result=subprocess.run([sys.executable,'-X','utf8','-B','-c',script,temporary],cwd=Path(__file__).resolve().parents[1],
                env=env,capture_output=True,text=True,encoding='utf-8',timeout=60)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('PASS_ACTUAL_OFFSCREEN',result.stdout)


if __name__=='__main__':unittest.main()
