"""Public presentation fixtures, never SDK/network/payment evidence.

Actual per-user Publisher files exercise source isolation and PID/freshness
checks. The separate offscreen Qt fixture clicks the real read-only selector.
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
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from backend import local_node_observation as observation


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def body(label, count):
    return {'state': 'RUNNING', 'mode': 'FINANCIAL_SDK_CERTIFIED_VIEW',
            'environment': 'TESTNET', 'chain_id': 'presentation-shared-chain',
            'network_id': digest('same-network'), 'genesis_hash': digest('same-genesis'),
            'node_key': digest('node-' + label), 'role': 'VALIDATOR',
            'certificate_height': None, 'state_root': None,
            'certified_blocks': str(count), 'certified_transactions': str(count * 3),
            'lan_setup': {'active': True, 'invites': []},
            'lan': {'scope': 'LOCAL_TESTNET_PROTOCOL_ACCEPTANCE', 'label': label,
                    'connection_state': 'UNOBSERVED', 'authenticated_peers': []},
            'block_graph': {'blocks': [], 'edges': [], 'stale': True},
            'protocol_network': {'mode': 'LOCAL_ACCEPTANCE', 'node_role': 'VALIDATOR',
                                 'source_profile': label, 'native_profile': label + 'Vote',
                                 'account_sources': [{'profile': label + 'Account', 'address': digest(label + '-account')}]},
            'own_financial_accounts': [{'profile': label + 'Account', 'address': digest(label + '-account'),
                                        'balance_atomic': str(count), 'nonce': '0'}]}


class ObservationSources(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='gg-observation-sources-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'observations'
        self.reader = observation.Reader(self.root)
        self.now = time.monotonic()
        self.clock = patch.object(observation.time, 'monotonic', side_effect=lambda: self.now)
        self.clock.start(); self.addCleanup(self.clock.stop)
        self.publishers = []
        self.addCleanup(lambda: [publisher.close() for publisher in self.publishers])

    def publish(self, label, count):
        publisher = observation.Publisher(self.root)
        publisher.publish(body(label, count)); self.publishers.append(publisher)
        return publisher

    def refresh(self, elapsed=.3):
        self.now += elapsed
        return self.reader.view()

    @staticmethod
    def handle(view, label):
        return next(row['handle'] for row in view['local_node_sources']['sources'] if row['source_profile'] == label)

    def test_two_real_same_pid_publishers_require_explicit_choice_and_never_sum(self):
        first = self.publish('WinA', 11); second = self.publish('WinB', 29)
        self.assertEqual(first.pid, second.pid)
        self.assertNotEqual(first.name, second.name)
        view = self.refresh()
        self.assertIsNone(view['parallel_dag'])
        self.assertEqual(view['local_node_sources']['state'], 'CHOICE_REQUIRED')
        self.assertEqual(len(view['local_node_sources']['sources']), 2)
        selected = self.reader.select_source(self.handle(view, 'WinA'))
        self.assertEqual(selected['parallel_dag']['certified_blocks'], '11')
        self.assertEqual(selected['parallel_dag']['own_financial_accounts'][0]['profile'], 'WinAAccount')
        selected = self.reader.select_source(self.handle(view, 'WinB'))
        self.assertEqual(selected['parallel_dag']['certified_blocks'], '29')
        self.assertEqual(selected['parallel_dag']['certified_transactions'], '87')
        self.assertEqual(len(selected['parallel_dag']['own_financial_accounts']), 1)
        self.assertEqual(selected['parallel_dag']['own_financial_accounts'][0]['profile'], 'WinBAccount')
        self.assertEqual(selected['parallel_dag']['observation']['source_handle'], self.handle(view, 'WinB'))
        selected['parallel_dag']['certified_blocks'] = 'injected'
        self.assertEqual(self.reader.snapshot()['certified_blocks'], '29')

    def test_single_fresh_automatic_view_still_works_then_two_sources_clear_it(self):
        self.publish('WinA', 11)
        view = self.refresh()
        self.assertEqual(view['parallel_dag']['certified_blocks'], '11')
        self.assertEqual(view['local_node_sources']['selection'], 'AUTOMATIC')
        self.publish('WinB', 29)
        self.assertIsNone(self.refresh()['parallel_dag'])

    def test_selected_close_and_reappearance_never_fall_back_or_resume_implicitly(self):
        first = self.publish('WinA', 11); self.publish('WinB', 29)
        initial = self.refresh(); old_handle = self.handle(initial, 'WinA')
        self.reader.select_source(old_handle); first.close()
        lost = self.refresh()
        self.assertIsNone(lost['parallel_dag'])
        self.assertEqual(lost['local_node_sources']['state'], 'UNAVAILABLE')
        self.assertEqual(lost['local_node_sources']['selected_handle'], old_handle)
        first.publish(body('WinA', 13))
        reappeared = self.refresh()
        self.assertIsNone(reappeared['parallel_dag'])
        new_handle = self.handle(reappeared, 'WinA')
        self.assertNotEqual(new_handle, old_handle)
        self.assertEqual(self.reader.select_source(new_handle)['parallel_dag']['certified_blocks'], '13')

    def test_selected_public_identity_changes_require_a_new_choice(self):
        cases = ('node_key', 'genesis_hash', 'network_id', 'chain_id', 'native_profile', 'account_sources')
        for field in cases:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary) / 'observations'; reader = observation.Reader(root)
                publisher = observation.Publisher(root)
                try:
                    original = body('WinA', 11); publisher.publish(original)
                    handle = self.handle(reader.view(), 'WinA'); reader.select_source(handle)
                    changed = deepcopy(original)
                    if field == 'native_profile': changed['protocol_network'][field] = 'OtherVote'
                    elif field == 'account_sources': changed['protocol_network'][field][0]['address'] = digest('different-account')
                    else: changed[field] = digest('different-' + field)
                    self.now += .3; publisher.publish(changed); self.now += .3
                    view = reader.view()
                    self.assertIsNone(view['parallel_dag'])
                    self.assertEqual(view['local_node_sources']['state'], 'UNAVAILABLE')
                    self.assertNotEqual(self.handle(view, 'WinA'), handle)
                finally: publisher.close()

    def test_balance_nonce_counter_updates_do_not_change_the_selected_source(self):
        publisher = self.publish('WinA', 11)
        view = self.refresh(); handle = self.handle(view, 'WinA')
        self.reader.select_source(handle)
        changed = body('WinA', 31); changed['own_financial_accounts'][0]['nonce'] = '9'
        self.now += .3; publisher.publish(changed)
        view = self.refresh()
        self.assertEqual(view['local_node_sources']['selected_handle'], handle)
        self.assertEqual(view['parallel_dag']['certified_blocks'], '31')
        self.assertEqual(view['parallel_dag']['own_financial_accounts'][0]['nonce'], '9')

    def test_stale_selected_source_is_labelled_and_expiry_never_selects_other_source(self):
        self.publish('WinA', 11); second = self.publish('WinB', 29)
        view = self.refresh(); self.reader.select_source(self.handle(view, 'WinA'))
        stale = self.refresh(6)
        self.assertTrue(stale['parallel_dag']['observation']['stale'])
        self.assertEqual(stale['parallel_dag']['lan']['connection_state'], 'STALE')
        second.publish(body('WinB', 30))
        expired = self.refresh(observation.RETAIN_SECONDS)
        self.assertIsNone(expired['parallel_dag'])
        self.assertEqual(expired['local_node_sources']['state'], 'UNAVAILABLE')

    def test_stopped_source_bad_handles_and_foreign_reader_handles_fail_closed(self):
        publisher = self.publish('WinA', 11)
        view = self.refresh(); selected = self.handle(view, 'WinA')
        self.reader.select_source(selected)
        for value in (None, '', '../file', selected + 'x', 'observation-' + '0' * 32):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.reader.select_source(value)
        other = observation.Reader(self.root)
        with self.assertRaises(ValueError): other.select_source(selected)
        self.now += .3; stopped = body('WinA', 11); stopped['state'] = 'STOPPED'; publisher.publish(stopped)
        self.assertIsNone(self.refresh()['parallel_dag'])
        self.assertEqual(self.reader.view()['local_node_sources']['state'], 'UNAVAILABLE')

    def test_pid_start_scope_secrets_and_size_guards_exclude_sources(self):
        publisher = self.publish('WinA', 11)
        raw = publisher.path.read_bytes(); original = json.loads(raw)
        mutations = [lambda value: value.update(process_started=value['process_started'] + 1),
                     lambda value: value.update(pid=value['pid'] + 1),
                     lambda value: value['body'].update(environment='MAINNET'),
                     lambda value: value['body'].update(password='must-never-escape')]
        for mutation in mutations:
            value = deepcopy(original); mutation(value)
            publisher.path.write_text(json.dumps(value), encoding='utf-8')
            self.assertEqual(self.refresh()['local_node_sources']['sources'], [])
        publisher.path.write_bytes(b' ' * (observation.MAX_BYTES + 1))
        self.assertEqual(self.refresh()['local_node_sources']['sources'], [])
        publisher.path.write_bytes(raw)
        with patch.object(observation, '_process_started', side_effect=ValueError('GG_NODE_OBSERVATION_OWNER')):
            self.assertEqual(self.refresh()['local_node_sources']['sources'], [])
        self.assertNotIn('must-never-escape', json.dumps(self.reader.view()))

    def test_root_symlink_and_source_budget_guards_remain_fail_closed(self):
        self.publish('WinA', 11)
        original = Path.is_symlink
        with patch.object(Path, 'is_symlink', side_effect=lambda: True):
            self.assertEqual(self.refresh()['local_node_sources']['sources'], [])
        self.assertFalse(original(self.root))
        for index in range(observation.MAX_SOURCES): self.publish('Extra' + str(index), index)
        self.assertEqual(self.refresh()['local_node_sources']['sources'], [])

    def test_posix_mode_and_uid_guards_remain_fail_closed(self):
        publisher = self.publish('WinA', 11)
        # The test is meaningful on both hosts: the exact POSIX guard is
        # exercised on a real file's actual stat, with only getuid as a seam.
        with patch.object(observation.os, 'name', 'posix'), patch.object(observation.os, 'getuid', return_value=publisher.path.stat().st_uid + 1, create=True):
            self.assertIsNone(self.reader._read(publisher.path, self.now))
        if os.name != 'nt':
            os.chmod(publisher.path, 0o644)
            self.assertIsNone(self.reader._read(publisher.path, self.now))
            os.chmod(publisher.path, 0o600)
            self.assertIsNotNone(self.reader._read(publisher.path, self.now))

    def test_backend_selection_api_is_read_only_and_respects_owned_desktop_node(self):
        from backend import lan_dag_runtime
        self.publish('WinA', 11); self.publish('WinB', 29)
        view = self.refresh(); handle = self.handle(view, 'WinB')
        with patch.object(observation, 'source_reader', return_value=self.reader), patch.object(lan_dag_runtime, 'active_manager', return_value=None):
            selected = observation.select_observation_source(handle)
        self.assertEqual(selected['parallel_dag']['certified_blocks'], '29')
        self.assertIs(selected['parallel_dag'], selected['lan_dag'])
        with patch.object(lan_dag_runtime, 'active_manager', return_value=object()):
            with self.assertRaisesRegex(ValueError, 'OWNED_NODE_ACTIVE'):
                observation.select_observation_source(handle)


    def test_active_legacy_pairing_with_idle_dag_remains_readable_without_finality(self):
        source=body('LegacyPairing',0)
        source.pop('protocol_network');source.pop('role')
        source.update(state='STOPPED',mode='LOCAL_PROPOSAL_DAG',
                      certified_blocks=None,certified_transactions=None)
        source['lan'].update(scope='PRIVATE_LAN_SESSION_EXPERIMENT',
            state='PAIRING',connection_state='PAIRING',authenticated_peers=[],
            participation={'consensus_validator':False,'producer':False})
        publisher=observation.Publisher(self.root);self.publishers.append(publisher)
        publisher.publish(source)
        view=self.refresh();metadata=view['local_node_sources']['sources'][0]
        self.assertTrue(metadata['available'])
        self.assertEqual(view['local_node_sources']['state'],'SELECTED')
        self.assertEqual(view['parallel_dag']['state'],'STOPPED')
        self.assertEqual(view['parallel_dag']['lan']['state'],'PAIRING')
        self.assertEqual(view['parallel_dag']['lan']['connection_state'],'PAIRING')
        self.assertEqual(view['parallel_dag']['lan']['authenticated_peers'],[])
        self.assertIsNone(view['parallel_dag']['certificate_height'])
        self.assertIsNone(view['parallel_dag']['state_root'])
        self.assertIsNone(view['parallel_dag']['certified_blocks'])
        self.assertIsNone(view['parallel_dag']['certified_transactions'])
        self.assertFalse(view['parallel_dag']['lan']['participation']['consensus_validator'])
        self.assertEqual(view['parallel_dag']['block_graph']['blocks'],[])
        # The explicit read-only choice has the same pairing projection. It
        # neither starts the DAG engine nor rewrites PAIRING into CONNECTED.
        selected=self.reader.select_source(metadata['handle'])
        self.assertEqual(selected['parallel_dag']['state'],'STOPPED')
        self.assertEqual(selected['parallel_dag']['lan']['connection_state'],'PAIRING')
        self.assertTrue(selected['parallel_dag']['observation']['read_only'])
        self.now+=.3;source['lan']['state']='STOPPED';publisher.publish(source)
        stopped=self.refresh()
        self.assertIsNone(stopped['parallel_dag'])
        self.assertEqual(stopped['local_node_sources']['state'],'UNAVAILABLE')

    def test_native_outer_stop_and_explicit_lan_stop_remain_unavailable(self):
        cases=(('native','LOCAL_TESTNET_PROTOCOL_ACCEPTANCE','STOPPED','RUNNING'),
               ('legacy','PRIVATE_LAN_SESSION_EXPERIMENT','RUNNING','STOPPED'))
        for kind,scope,outer_state,lan_state in cases:
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary)/'observations';reader=observation.Reader(root)
                publisher=observation.Publisher(root)
                try:
                    source=body('PUBLIC-stop-'+kind,0)
                    if kind=='legacy':source.pop('protocol_network')
                    source['lan'].update(scope=scope,state='RUNNING')
                    publisher.publish(source)
                    initial=reader.view();handle=initial['local_node_sources']['sources'][0]['handle']
                    reader.select_source(handle)
                    self.now+=.3;source['state']=outer_state;source['lan']['state']=lan_state
                    publisher.publish(source);self.now+=.3
                    stopped=reader.view()
                    self.assertIsNone(stopped['parallel_dag'])
                    self.assertEqual(stopped['local_node_sources']['state'],'UNAVAILABLE')
                    self.assertFalse(stopped['local_node_sources']['sources'][0]['available'])
                finally:publisher.close()


def qml_fixture():
    from PySide6.QtCore import QObject, Signal, Slot, QUrl, Qt, QPoint
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression, QQmlNetworkAccessManagerFactory, qmlContext
    from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
    from PySide6.QtQuick import QQuickItem
    from PySide6.QtTest import QTest
    from backend import omni_service, lan_dag_runtime
    app = QGuiApplication([]); app.setQuitOnLastWindowClosed(False)
    with tempfile.TemporaryDirectory(prefix='gg-source-picker-qml-') as temporary:
        root = Path(temporary) / 'observations'; reader = observation.Reader(root)
        first = observation.Publisher(root); second = observation.Publisher(root)
        literal = '<img src="https://invalid.example/never"> WinA'
        first.publish(body(literal, 11)); second.publish(body('WinB', 29))
        view = reader.view(); old_catalog = deepcopy(view['local_node_sources'])
        class Host(QObject):
            networkTelemetryUpdated = Signal(str)
            def __init__(self): super().__init__(); self.actions = []; self.selections = []
            @Slot(result=str)
            def omniStatus(self):
                current = reader.view()
                return json.dumps({'assets': [], 'ui_operation': {}, 'wallet_overview': {'unchanged': True}, **current})
            @Slot(str)
            def setNetworkTelemetryView(self, page): pass
            @Slot(str, result=str)
            def selectLocalNodeObservationSource(self, handle):
                self.selections.append(handle)
                with patch.object(observation, 'source_reader', return_value=reader), patch.object(lan_dag_runtime, 'active_manager', return_value=None):
                    return json.dumps(omni_service.select_observation_source(handle))
            @Slot(str, str, result=str)
            def omniAction(self, name, raw):
                self.actions.append(name); raise AssertionError('SOURCE_CHOICE_MUST_NOT_DISPATCH_ACTIONS')
        host = Host(); engine = QQmlApplicationEngine(); warnings = []; image_requests = []
        class OfflineManager(QNetworkAccessManager):
            def createRequest(self, operation, request, outgoing=None):
                image_requests.append(request.url().toString())
                return super().createRequest(operation, QNetworkRequest(QUrl('data:,blocked')), outgoing)
        class OfflineFactory(QQmlNetworkAccessManagerFactory):
            def __init__(self): super().__init__(); self.managers = []
            def create(self, parent):
                manager = OfflineManager(parent); self.managers.append(manager); return manager
        factory = OfflineFactory(); engine.setNetworkAccessManagerFactory(factory)
        engine.warnings.connect(lambda rows: warnings.extend(row.toString() for row in rows))
        engine.rootContext().setContextProperty('fixtureHost', host)
        source = '''import QtQuick
import QtQuick.Controls
import COMPONENTS
ApplicationWindow {width:1100;height:760;visible:true
OmniSurface {objectName:"sourceHub";anchors.fill:parent;surfaceHost:fixtureHost;page:"DAG"}}
'''.replace('COMPONENTS', json.dumps((ROOT / 'qml/components').as_uri()))
        engine.loadData(source.encode(), QUrl.fromLocalFile(str(ROOT / 'tests/source-picker-fixture.qml')))
        assert engine.rootObjects(), warnings
        window = engine.rootObjects()[0]
        hub = window.findChild(QQuickItem, 'sourceHub')
        dashboard = window.findChild(QQuickItem, 'parallelDagDashboard')
        picker = window.findChild(QQuickItem, 'dagObservationSourcePicker')
        assert hub and dashboard and picker
        def js(code, owner=hub):
            expression = QQmlExpression(qmlContext(owner), owner, code)
            value = expression.evaluate(); assert not expression.hasError(), expression.error().toString()
            value = value[0] if isinstance(value, tuple) else value
            return value.toVariant() if hasattr(value, 'toVariant') else value
        try:
            QTest.qWait(80)
            assert picker.property('visible') and picker.property('count') == 2
            assert picker.property('currentIndex') == -1
            assert js('sourceUnavailable', dashboard) is True
            assert js('producerCount', dashboard) == 0
            assert js('metricAt(0).value', dashboard) == '\u2014'
            # Open the actual ComboBox popup and choose with keyboard input,
            # through its real activated signal and the real Reader API.
            point = picker.mapToScene(picker.boundingRect().center())
            QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(int(point.x()), int(point.y())))
            QTest.qWait(30)
            assert js('popup.visible', picker) is True
            QTest.keyClick(window, Qt.Key.Key_Down)
            QTest.keyClick(window, Qt.Key.Key_Return)
            QTest.qWait(50)
            assert len(host.selections) == 1 and not host.actions
            chosen = reader.snapshot(); assert chosen is not None
            chosen_handle = chosen['observation']['source_handle']
            assert js('networkState.parallel_dag.observation.source_handle') == chosen_handle
            assert js('observerReadOnly', dashboard) is True
            assert js('contentItem.textFormat === Text.PlainText', picker) is True
            # Select the other actual delegate by pointer, not by invoking a
            # backend method or constructing a replacement UI body.
            target = next(row for row in reader.view()['local_node_sources']['sources'] if row['handle'] != chosen_handle)
            index = next(i for i, row in enumerate(reader.view()['local_node_sources']['sources']) if row['handle'] == target['handle'])
            QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(int(point.x()), int(point.y())))
            QTest.qWait(30)
            item = js('popup.contentItem.itemAtIndex(' + str(index) + ')', picker)
            assert isinstance(item, QQuickItem)
            item_point = item.mapToScene(item.boundingRect().center())
            QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(int(item_point.x()), int(item_point.y())))
            QTest.qWait(50)
            assert len(host.selections) == 2 and not host.actions
            selected = reader.snapshot()
            assert selected['observation']['source_handle'] == target['handle']
            assert js('networkState.parallel_dag.certified_blocks') == selected['certified_blocks']
            # An old queued same-chain source and an old full response cannot
            # restore another account after the explicit selection revision.
            old = body('old-source', 999)
            old['observation'] = {'source': 'LOCAL_CLI', 'read_only': True,
                                  'source_handle': 'old-handle', 'publication_sequence': 999}
            packet = {'network_page': 'DAG', 'observed_monotonic': time.monotonic(),
                      'local_node_sources': old_catalog, 'parallel_dag': old}
            js('applyTelemetry(' + json.dumps(json.dumps(packet)) + ')')
            assert js('networkState.parallel_dag.observation.source_handle') == target['handle']
            js('apply(' + json.dumps(json.dumps({'assets': [], 'local_node_sources': old_catalog, 'parallel_dag': old})) + ')')
            assert js('networkState.parallel_dag.observation.source_handle') == target['handle']
            # Closing the selected file clears the instruments and preserves
            # the visible unavailable selection, while the other file remains.
            selected_pub = first if selected['lan']['label'] == literal else second
            selected_pub.close(); reader._last_check = -float('inf')
            unavailable = reader.view()
            js('applyTelemetry(' + json.dumps(json.dumps({'network_page': 'DAG', 'observed_monotonic': time.monotonic() + 1, **unavailable})) + ')')
            assert js('networkState.parallel_dag') is None
            assert picker.property('visible') and js('sourceUnavailable', dashboard) is True
            assert js('producerCount', dashboard) == 0
            assert js('metricAt(0).value', dashboard) == '\u2014'
            assert not host.actions and not warnings and not image_requests, (warnings, image_requests)
            print(json.dumps({'status': 'PASS', 'actual_offscreen_QML': True,
                              'actual_two_publisher_selection': True, 'combo_mouse_and_keyboard': True,
                              'source_stop_clears_view': True, 'same_chain_account_mix_rejected': True,
                              'native_nodes_started': False, 'images_captured': False}))
        finally:
            first.close(); second.close(); window.close(); engine.setNetworkAccessManagerFactory(None); engine.deleteLater(); app.processEvents()


class ObservationSourceQML(unittest.TestCase):
    def test_actual_offscreen_source_picker(self):
        with tempfile.TemporaryDirectory(prefix='gg-source-picker-isolated-') as temporary:
            env = dict(os.environ, QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software',
                       QT_QUICK_CONTROLS_STYLE='Basic', GG_DESKTOP_STATE_ROOT=str(Path(temporary) / 'state'),
                       GG_DESKTOP_DATA_ROOT=str(Path(temporary) / 'data'))
            result = subprocess.run([sys.executable, '-X', 'utf8', '-B', str(Path(__file__).resolve()), '--qml-fixture'],
                                    cwd=ROOT, env=env, capture_output=True, text=True, encoding='utf-8', timeout=25)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    if len(sys.argv) == 2 and sys.argv[1] == '--qml-fixture': qml_fixture()
    else: unittest.main()
