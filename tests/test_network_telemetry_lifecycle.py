"""Production host/OmniSurface lifecycle across real, disposable DAG sessions.

The source engine and observation worker are real. Only the broad wallet/full
snapshot is replaced with a small public fixture; no user profile is opened.
Unlike the native graph benchmark this exercises OmniSurface's actual merger,
the host slots, and more than one simultaneously instantiated surface.
"""
from __future__ import annotations

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


def fixture(directory: Path, mode: str) -> None:
    sys.path.insert(0, str(ROOT))
    from PySide6.QtCore import QObject, QEvent, QEventLoop, QTimer, QUrl, Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression, qmlContext
    from PySide6.QtQuick import QQuickItem
    from backend import gg_parallel_dag
    from backend.chat_surface_host import ChatSurfaceHost
    from backend.crypto_ui_runtime import CryptoUiRuntime
    from backend.network_telemetry import NetworkTelemetryRuntime

    app = QGuiApplication([])
    app.setQuitOnLastWindowClosed(False)
    owned = gg_parallel_dag.ParallelDag()
    calls = []

    def public_snapshot():
        return {'assets': [], 'selected_asset': '', 'parallel_dag': owned.snapshot()}

    def observation(page):
        calls.append((page, time.monotonic()))
        if page != 'DAG':
            return None
        body = owned.snapshot()
        return {'network_page': 'DAG',
                'revision': (body['state'], body['chain_id'], body['wave_count']),
                'parallel_dag': body}

    class Host(ChatSurfaceHost):
        def __init__(self):
            # Keep the real production slots/signals while omitting the large
            # desktop constructor, which owns terminals and private profiles.
            QObject.__init__(self)
            self._omni_ui = CryptoUiRuntime(self, snapshot=public_snapshot, ttl=.02)
            self._omni_ui.updated.connect(self.omniStatusUpdated)
            self._network_telemetry = NetworkTelemetryRuntime(self, source=observation)
            self._network_telemetry.updated.connect(self.networkTelemetryUpdated)

    host = Host()
    engine = QQmlApplicationEngine()
    warnings = []
    engine.warnings.connect(lambda rows: warnings.extend(row.toString() for row in rows))
    engine.rootContext().setContextProperty('ownedHost', host)
    source = '''import QtQuick
import QtQuick.Controls
import COMPONENTS
ApplicationWindow {
    id: shell; width: 970; height: 670; visible: true
    property bool otherLoaded: false
    property bool otherVisible: false
    property string otherPage: 'WALLET'
    OmniSurface { id: hub; objectName: 'ownedHub'; anchors.fill: parent; page: 'DAG'; surfaceHost: ownedHost }
    Loader {
        id: other; objectName: 'otherLoader'; active: shell.otherLoaded
        sourceComponent: Component {
            OmniSurface { objectName: 'otherHub'; width: 360; height: 600; page: shell.otherPage; visible: shell.otherVisible; surfaceHost: ownedHost }
        }
    }
}'''.replace('COMPONENTS', json.dumps((ROOT/'qml/components').as_uri()))

    def pump(seconds=.03):
        loop = QEventLoop()
        timer = QTimer()
        timer.setTimerType(Qt.PreciseTimer)
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        timer.start(max(1, round(seconds*1000)))
        loop.exec()
        app.processEvents()

    def js(code, item=None):
        item = item or hub
        expression = QQmlExpression(qmlContext(item), item, code)
        result = expression.evaluate()
        assert not expression.hasError(), expression.error().toString()
        result = result[0] if isinstance(result, tuple) else result
        return result.toVariant() if hasattr(result, 'toVariant') else result

    def wait_for(predicate, reason, seconds=4):
        deadline = time.monotonic()+seconds
        while time.monotonic() < deadline:
            if predicate():
                return
            pump(.015)
        assert predicate(), reason

    def other_ready(page):
        # This scenario tests reader ownership after a surface is present,
        # not cancellation of a still-incubating nested QML component. A
        # fixed sleep can expire before the real Loader completes on a busy
        # renderer, so wait for the actual object and its network dashboard.
        loader = window.findChild(QQuickItem, 'otherLoader')
        other = loader.property('item') if loader is not None else None
        if loader is None or not js('status === Loader.Ready', loader) or other is None or other.property('page') != page:
            return False
        if page != 'DAG':
            return True
        network = other.findChild(QQuickItem, 'omniNetworkLoader')
        return network is not None and js('status === Loader.Ready', network) and network.property('item') is not None

    with patch.object(gg_parallel_dag, '_ENGINE', owned):
        if mode == 'owners':
            owned.start_live()
        engine.loadData(source.encode(), QUrl.fromLocalFile(str(directory/'lifecycle.qml')))
        assert engine.rootObjects(), warnings
        window = engine.rootObjects()[0]
        hub = window.findChild(QQuickItem, 'ownedHub')
        assert hub is not None
        try:
            wait_for(lambda: js('state.parallel_dag !== undefined'), 'Initial full status missing')
            wait_for(lambda: js('telemetryPatch.parallel_dag !== undefined'), 'Actual observer packet missing')
            assert host._network_telemetry._view == 'DAG'
            if mode == 'start':
                assert js('networkState.parallel_dag.state') == 'STOPPED'
                assert js('telemetryPatch.parallel_dag.state') == 'STOPPED'
                js("run('dag_start',{})")
                wait_for(lambda: owned.snapshot()['wave_count'] >= 3,
                         'Actual owned backend did not create signed waves')
                wait_for(lambda: js('networkState.parallel_dag.state') == 'RUNNING',
                         'Stale STOPPED telemetry hid a successful real start')
                assert js('networkState.parallel_dag.chain_id') == owned.snapshot()['chain_id']
                assert js('networkState.parallel_dag.blocks_admitted') > 0
                assert js('networkState.parallel_dag.live.enabled')
                first_chain = owned.snapshot()['chain_id']
                old_running_packet = {'network_page': 'DAG', 'parallel_dag': owned.snapshot()}
                js("run('dag_stop',{})")
                wait_for(lambda: js('networkState.parallel_dag.state') == 'STOPPED',
                         'Explicit stop did not reach the visible surface')
                wait_for(lambda: js('!busy'), 'Stop action stayed busy')
                # A real packet captured before Stop can still be queued in
                # the GUI. It cannot resurrect an explicitly stopped engine.
                host.networkTelemetryUpdated.emit(json.dumps(old_running_packet))
                pump(.06)
                assert js('networkState.parallel_dag.state') == 'STOPPED'
                assert owned.snapshot()['state'] == 'STOPPED'
                js("run('dag_start',{})")
                wait_for(lambda: owned.snapshot()['state'] == 'RUNNING',
                         'Second owned session did not start')
                wait_for(lambda: js('networkState.parallel_dag.state') == 'RUNNING',
                         'Stopped previous session hid a new successful start')
                assert js('networkState.parallel_dag.chain_id') != first_chain
                assert js('networkState.parallel_dag.chain_id') == owned.snapshot()['chain_id']
                # The same real session must reject late observations from
                # the explicitly stopped session, including its STOPPED tail.
                stopped_tail = {'network_page': 'DAG', 'parallel_dag': {
                    'state': 'STOPPED', 'chain_id': first_chain,
                    'block_graph': {'observed_at': time.time()+1}}}
                host.networkTelemetryUpdated.emit(json.dumps(stopped_tail))
                pump(.05)
                assert js('networkState.parallel_dag.state') == 'RUNNING'
                assert js('networkState.parallel_dag.chain_id') == owned.snapshot()['chain_id']
                blank_stopped_tail = {'network_page': 'DAG', 'parallel_dag': {
                    'state': 'STOPPED', 'chain_id': '',
                    'block_graph': {'observed_at': time.time()+2}}}
                host.networkTelemetryUpdated.emit(json.dumps(blank_stopped_tail))
                pump(.05)
                assert js('networkState.parallel_dag.state') == 'RUNNING'
                assert js('networkState.parallel_dag.chain_id') == owned.snapshot()['chain_id']
                print(json.dumps({'status': 'PASS', 'real_host_slots': True,
                                  'real_signed_proposals': owned.snapshot()['blocks_admitted'],
                                  'stopped_to_started_sessions': 2,
                                  'late_previous_session_rejected': True,
                                  'old_running_packet_cannot_resurrect_stop': True,
                                  'blank_stopped_tail_cannot_stop_new_session': True}))
            elif mode == 'owners':
                assert js('networkState.parallel_dag.state') == 'RUNNING'
                before = len(calls)
                window.setProperty('otherLoaded', True)
                wait_for(lambda: other_ready('WALLET'), 'Hidden wallet surface did not finish loading')
                wait_for(lambda: len(calls) > before+2, 'Hidden wallet surface stopped the real observer worker')
                assert host._network_telemetry._view == 'DAG', 'Hidden wallet surface cancelled visible DAG observations'
                assert len(calls) > before+2, 'Hidden wallet surface stopped the real observer worker'
                window.setProperty('otherPage', 'NFT')
                wait_for(lambda: other_ready('NFT'), 'Hidden NFT surface did not finish loading')
                assert host._network_telemetry._view == 'DAG'
                window.setProperty('otherLoaded', False)
                pump(.05)
                assert host._network_telemetry._view == 'DAG', 'Unrelated surface destruction cancelled visible observer'
                # Two visible readers of one engine share the one source
                # worker. Releasing either must preserve the other owner.
                window.setProperty('otherPage', 'DAG')
                window.setProperty('otherVisible', True)
                window.setProperty('otherLoaded', True)
                wait_for(lambda: other_ready('DAG'), 'Second visible DAG reader did not finish loading')
                worker = host._network_telemetry._worker
                hub.setVisible(False)
                pump(.05)
                assert host._network_telemetry._view == 'DAG', 'One reader hid a different visible reader'
                assert host._network_telemetry._worker is worker
                window.setProperty('otherLoaded', False)
                pump(.05)
                assert host._network_telemetry._view == '', 'Last reader destruction left background sampling active'
                paused = len(calls)
                pump(.06)
                assert len(calls) == paused, 'Last hidden reader left backend reads running'
                hub.setVisible(True)
                wait_for(lambda: host._network_telemetry._view == 'DAG', 'Visible reader did not resume')
                assert host._network_telemetry._worker is worker
                # QObject destruction can run after the observer itself has
                # closed or its C++ wrapper has gone away during shutdown.
                # The retained destruction callback must never restart work
                # or access an already deleted Qt signal/object.
                shutdown_reads = []
                shutdown_runtime = NetworkTelemetryRuntime(source=lambda page: shutdown_reads.append(page))
                shutdown_owner = QObject()
                shutdown_runtime.set_owner(shutdown_owner, 'DAG')
                shutdown_worker = shutdown_runtime._worker
                shutdown_runtime.close()
                assert not shutdown_runtime._owners
                assert shutdown_worker is not None and not shutdown_worker.is_alive()
                shutdown_count = len(shutdown_reads)
                shutdown_runtime.deleteLater()
                app.sendPostedEvents(None, QEvent.DeferredDelete)
                shutdown_owner.deleteLater()
                app.sendPostedEvents(None, QEvent.DeferredDelete)
                pump(.03)
                assert len(shutdown_reads) == shutdown_count
                print(json.dumps({'status': 'PASS', 'real_host_slots': True,
                                  'hidden_or_destroyed_other_surface_cancels_reads': False,
                                  'visible_readers_share_one_worker': True,
                                  'last_reader_release_stops_sampling': True,
                                  'owner_destroy_after_observer_close_safe': True}))
            assert not warnings, warnings
        finally:
            window.close()
            engine.deleteLater()
            app.processEvents()
            host._network_telemetry.close()
            host._omni_ui.close()
            owned.stop()


class NetworkTelemetryLifecycleTests(unittest.TestCase):
    def check_fixture(self, mode):
        with tempfile.TemporaryDirectory(prefix='gg-network-lifecycle-') as directory:
            env = os.environ.copy()
            env.update(QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software',
                       QT_QUICK_CONTROLS_STYLE='Basic',
                       GG_DESKTOP_STATE_ROOT=str(Path(directory)/'state'),
                       GG_DESKTOP_DATA_ROOT=str(Path(directory)/'data'))
            result = subprocess.run([sys.executable, '-X', 'utf8', '-B', str(Path(__file__).resolve()),
                                     '--fixture', directory, mode], cwd=ROOT, env=env,
                                    capture_output=True, text=True, encoding='utf-8', timeout=25)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            print(result.stdout.strip())

    def test_real_start_survives_stopped_observer_and_previous_session(self):
        self.check_fixture('start')

    def test_hidden_or_destroyed_other_surface_cannot_cancel_visible_observer(self):
        self.check_fixture('owners')


if __name__ == '__main__':
    if len(sys.argv) == 4 and sys.argv[1] == '--fixture':
        fixture(Path(sys.argv[2]), sys.argv[3])
    else:
        unittest.main()
