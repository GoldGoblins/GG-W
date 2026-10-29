"""Owned network cancellation bypasses busy RPC and ordinary UI action lanes.

Every Qt/engine scenario runs in a disposable subprocess and private state.
Only fresh loopback test nodes or RAM-only proposal sessions are stopped.
No live user application, arbitrary PID, endpoint or wallet is accepted.
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

ROOT = Path(__file__).resolve().parents[1]


def qt_pump(app, seconds=.03):
    from PySide6.QtCore import QEventLoop, QTimer, Qt
    loop = QEventLoop()
    timer = QTimer()
    timer.setTimerType(Qt.PreciseTimer)
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    timer.start(max(1, round(seconds*1000)))
    loop.exec()
    app.processEvents()


def wait_for(app, predicate, reason, timeout=5):
    deadline = time.monotonic()+timeout
    while not predicate() and time.monotonic() < deadline:
        qt_pump(app, .01)
    assert predicate(), reason


def owned_priority_fixture():
    sys.path.insert(0, str(ROOT))
    from PySide6.QtCore import QCoreApplication
    from backend import gg_testnet as node
    from backend.network_stop import NetworkStopRuntime
    from backend.network_telemetry import NetworkTelemetryRuntime

    app = QCoreApplication([])
    assert node.available(), 'Pinned owned Hardhat toolchain unavailable'
    lock_entered = threading.Event()
    lock_release = threading.Event()
    cleanup_entered = threading.Event()
    finished = []
    interrupts = []
    cleanups = []
    observations = []
    process = None
    runtime = None
    observer = None
    holder = None
    cleanup_worker = None

    def hold_rpc_lane():
        with node.LOCK:
            lock_entered.set()
            assert lock_release.wait(5), 'Owned RPC fixture release timed out'

    def interrupt(page):
        interrupts.append(page)
        node.request_stop()

    def cleanup(page):
        cleanups.append(page)
        cleanup_entered.set()
        node.stop()

    try:
        initial = node.start()
        process = node._process
        assert initial['state'] == 'RUNNING' and process.poll() is None
        observer = NetworkTelemetryRuntime()
        observer.updated.connect(lambda raw: observations.append(json.loads(raw)))
        observer.set_view('TESTNET')
        wait_for(app, lambda: len(observations) >= 8, 'Real observation worker did not read owned headers')
        holder = threading.Thread(target=hold_rpc_lane, name='owned-stop-test-rpc-lock')
        holder.start()
        assert lock_entered.wait(2)
        runtime = NetworkStopRuntime(interrupt_source=interrupt, cleanup_source=cleanup)
        runtime.finished.connect(lambda page, error: finished.append((page, error)))
        for invalid in ('', 'OTHER', 'testnet', 'TESTNET:1234', '../../DAG', 1234, None):
            assert runtime.request(invalid) is False
        assert interrupts == cleanups == []

        began = time.perf_counter()
        assert runtime.request('TESTNET') is True
        request_ms = (time.perf_counter()-began)*1000
        assert request_ms < 100, ('Priority request waited for the busy RPC lock', request_ms)
        assert cleanup_entered.wait(2)
        cleanup_worker = runtime._workers['TESTNET']
        assert cleanup_worker is not None and cleanup_worker.is_alive()
        for _ in range(20):
            assert runtime.request('TESTNET') is True
        assert interrupts == ['TESTNET'] and cleanups == ['TESTNET']
        process.wait(timeout=2)
        assert not lock_release.is_set() and holder.is_alive()
        assert process.poll() is not None, 'Owned child survived while RPC lane was blocked'
        assert node._stop_requested.is_set()
        assert not finished, 'Cleanup must still be waiting for the held RPC lock'
        qt_pump(app, .06)
        assert cleanup_worker.is_alive()
        lock_release.set()
        holder.join(timeout=2)
        wait_for(app, lambda: bool(finished), 'Owned priority cleanup did not complete')
        cleanup_worker.join(timeout=2)
        assert finished == [('TESTNET', '')], finished
        assert not holder.is_alive() and not cleanup_worker.is_alive()
        assert node._process is None and node.snapshot()['state'] == 'STOPPED'
        qt_pump(app, .08)
        assert node._process is None, 'Observation or cleanup automatically restarted the node'
        runtime.close()
        assert runtime.request('TESTNET') is False
        assert interrupts == ['TESTNET'] and cleanups == ['TESTNET']
        print(json.dumps({'status': 'PASS', 'real_owned_node': True,
                          'real_observer_packets_before_stop': len(observations),
                          'request_ms_while_rpc_lock_held': round(request_ms, 3),
                          'process_died_before_rpc_lock_release': True,
                          'duplicate_requests_cleanup_workers': len(cleanups),
                          'invalid_page_has_no_effect': True,
                          'automatic_restart': False,
                          'cleanup_worker_joined': True}))
    finally:
        lock_release.set()
        if holder is not None:
            holder.join(timeout=3)
        if observer is not None:
            observer.close()
        if runtime is not None:
            runtime.close()
        node.stop()
        if process is not None:
            assert process.poll() is not None
        if cleanup_worker is not None:
            cleanup_worker.join(timeout=2)
            assert not cleanup_worker.is_alive()


def dag_priority_fixture():
    sys.path.insert(0, str(ROOT))
    from PySide6.QtCore import QCoreApplication
    from backend import gg_parallel_dag as dag
    from backend.network_stop import NetworkStopRuntime

    app = QCoreApplication([])
    owned = dag.ParallelDag()
    release = threading.Event()
    entered = threading.Event()
    finished = []
    cleanups = []

    def cleanup(page):
        cleanups.append(page)
        entered.set()
        assert release.wait(3)
        dag.stop()

    runtime = NetworkStopRuntime(cleanup_source=cleanup)
    runtime.finished.connect(lambda page, error: finished.append((page, error)))
    try:
        with patch.object(dag, '_ENGINE', owned):
            owned.start_live(4, 0, 30)
            wait_for(app, lambda: owned.snapshot()['blocks_admitted'] >= 8,
                     'Owned real DAG did not produce signed proposals')
            assert runtime.request('DAG')
            assert owned._live_cancel.is_set(), 'Priority cancellation waited for cleanup'
            assert entered.wait(2)
            worker = runtime._workers['DAG']
            for _ in range(12):
                assert runtime.request('DAG')
            assert cleanups == ['DAG']
            release.set()
            wait_for(app, lambda: bool(finished), 'Owned DAG cleanup did not finish')
            worker.join(timeout=2)
            assert finished == [('DAG', '')] and not worker.is_alive()
            assert owned.snapshot()['state'] == 'STOPPED'
            qt_pump(app, .06)
            assert owned.snapshot()['state'] == 'STOPPED'
            assert not any(thread.name.startswith(('gg-dag-live', 'gg-dag-producer'))
                           for thread in threading.enumerate())
            print(json.dumps({'status': 'PASS', 'actual_signed_dag': True,
                              'cancel_before_cleanup': True, 'cleanup_workers': len(cleanups),
                              'owned_threads_joined': True, 'automatic_restart': False}))
    finally:
        release.set()
        runtime.close()
        owned.stop()


def qml_fixture(directory):
    sys.path.insert(0, str(ROOT))
    from PySide6.QtCore import QObject, QPointF, QUrl, Qt, Slot
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression, qmlContext
    from PySide6.QtQuick import QQuickItem, QSGRendererInterface
    from PySide6.QtTest import QTest
    from backend import gg_testnet as node
    from backend.chat_surface_host import ChatSurfaceHost
    from backend.crypto_ui_runtime import CryptoUiRuntime

    app = QGuiApplication([])
    app.setQuitOnLastWindowClosed(False)
    assert node.available(), 'Pinned owned Hardhat toolchain unavailable'
    engine = QQmlApplicationEngine()
    warnings = []
    engine.warnings.connect(lambda rows: warnings.extend(row.toString() for row in rows))
    blocked = threading.Event()
    release = threading.Event()
    process = None
    window = None

    def public_snapshot():
        return {'assets': [], 'selected_asset': '', 'testnet': node.snapshot()}

    class Host(ChatSurfaceHost):
        def __init__(self):
            # Keep actual production priority slots/signals. The real desktop
            # constructor owns user profiles/terminals and is deliberately not run.
            QObject.__init__(self)
            self._omni_ui = CryptoUiRuntime(self, snapshot=public_snapshot, ttl=.02)
            self._omni_ui.updated.connect(self.omniStatusUpdated)
            self.ordinary_actions = []
            self.priority_calls = []

        @Slot(str, str, result=str)
        def omniAction(self, name, raw):
            self.ordinary_actions.append((name, raw))
            return self._omni_ui.snapshot()

        @Slot(str, result=bool)
        def requestNetworkStop(self, page):
            began = time.perf_counter()
            result = super().requestNetworkStop(page)
            self.priority_calls.append((page, result, (time.perf_counter()-began)*1000))
            return result

    host = Host()
    assert not host.requestNetworkStop('1234')
    assert getattr(host, '_network_stop', None) is None
    host.priority_calls.clear()
    engine.rootContext().setContextProperty('ownedHost', host)
    native = os.name == 'nt'
    source = '''import QtQuick
import QtQuick.Controls
import COMPONENTS
ApplicationWindow {
    width:970; height:670; x:300; y:180; visible:true; color:'#111111'
    flags: Qt.Tool|Qt.FramelessWindowHint|Qt.WindowDoesNotAcceptFocus|Qt.WindowStaysOnTopHint
    OmniSurface {objectName:'ownedBusyHub'; anchors.fill:parent; page:'TESTNET'; surfaceHost:ownedHost}
}'''.replace('COMPONENTS', json.dumps((ROOT/'qml/components').as_uri()))
    try:
        assert node.start()['state'] == 'RUNNING'
        process = node._process
        engine.loadData(source.encode(), QUrl.fromLocalFile(str(directory/'priority-stop.qml')))
        assert engine.rootObjects(), warnings
        window = engine.rootObjects()[0]
        if native:
            assert QTest.qWaitForWindowExposed(window, 3000)
            assert window.rendererInterface().graphicsApi() == QSGRendererInterface.GraphicsApi.Direct3D11
        hub = window.findChild(QQuickItem, 'ownedBusyHub')
        assert hub is not None

        def js(text):
            expression = QQmlExpression(qmlContext(hub), hub, text)
            value = expression.evaluate()
            assert not expression.hasError(), expression.error().toString()
            return value[0] if isinstance(value, tuple) else value

        wait_for(app, lambda: bool(js('networkState.testnet && networkState.testnet.state === "RUNNING"')),
                 'Actual owned node did not reach the loaded dashboard')
        dashboard = window.findChild(QQuickItem, 'testnetDashboard')
        button = window.findChild(QQuickItem, 'testnetStop')
        assert dashboard is not None and button is not None

        def ordinary_busy_action():
            blocked.set()
            assert release.wait(6), 'Owned ordinary action lane release timed out'

        host._omni_ui.submit('owned-fixture-busy-action', ordinary_busy_action)
        wait_for(app, lambda: blocked.is_set() and js('busy'), 'Ordinary action did not become busy')
        assert dashboard.property('busy') and not dashboard.property('canAct')
        assert button.isEnabled(), 'Stop inherits the busy lock from ordinary actions'
        js('run("testnet_deploy",{})')
        assert host.ordinary_actions == [], 'Ordinary action bypassed its busy fence'
        point = button.mapToScene(QPointF(button.width()/2, button.height()/2)).toPoint()
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
        wait_for(app, lambda: bool(host.priority_calls), 'Actual stop button did not reach priority host slot')
        page, accepted, request_ms = host.priority_calls[0]
        assert page == 'TESTNET' and accepted and request_ms < 100, host.priority_calls
        wait_for(app, lambda: process.poll() is not None, 'Owned node remained alive after clicking Stop')
        assert not release.is_set() and host._omni_ui._running
        assert host.ordinary_actions == []
        wait_for(app, lambda: not host._network_stop._workers, 'Priority cleanup did not drain')
        release.set()
        wait_for(app, lambda: not host._omni_ui._running, 'Ordinary lane did not finish after release')
        wait_for(app, lambda: js('networkState.testnet.state === "STOPPED"'),
                 'A verified stopped snapshot did not reach the actual dashboard')
        assert not warnings, warnings
        print(json.dumps({'status': 'PASS', 'native_direct3d11': native,
                          'actual_host_priority_slot': True, 'actual_stop_button': True,
                          'stop_enabled_while_ordinary_lane_busy': True,
                          'ordinary_action_lane_still_blocked': True,
                          'priority_slot_ms': round(request_ms, 3),
                          'owned_process_stopped_before_ordinary_lane_release': True,
                          'qml_warnings': len(warnings)}))
    finally:
        release.set()
        runtime = getattr(host, '_network_stop', None)
        if runtime is not None:
            runtime.close()
        observer = getattr(host, '_network_telemetry', None)
        if observer is not None:
            observer.close()
        host._omni_ui.close()
        node.stop()
        if window is not None:
            window.close()
        engine.deleteLater()
        app.processEvents()
        if process is not None:
            assert process.poll() is not None


class PriorityNetworkStopTests(unittest.TestCase):
    def run_fixture(self, mode, native=False):
        with tempfile.TemporaryDirectory(prefix='gg-owned-network-priority-stop-') as temporary:
            directory = Path(temporary)
            env = dict(os.environ, GG_DESKTOP_STATE_ROOT=str(directory/'state'),
                       GG_DESKTOP_DATA_ROOT=str(directory/'data'),
                       QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software',
                       QT_QUICK_CONTROLS_STYLE='Basic')
            if native:
                env.pop('QT_QUICK_BACKEND', None)
                env.update(QT_QPA_PLATFORM='windows', QSG_RHI_BACKEND='d3d11')
            result = subprocess.run([sys.executable, '-X', 'utf8', '-B', str(Path(__file__).resolve()),
                                     '--fixture', mode, temporary],
                                    cwd=ROOT, env=env, capture_output=True, text=True,
                                    encoding='utf-8', timeout=35)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertIn('"status": "PASS"', result.stdout)
            print(result.stdout.strip())

    def test_owned_process_stops_without_waiting_for_busy_rpc_lock(self):
        self.run_fixture('priority')

    def test_actual_dag_cancellation_precedes_deduplicated_cleanup(self):
        self.run_fixture('dag')

    @unittest.skipUnless(os.name == 'nt', 'Native Direct3D11 on Windows')
    def test_native_stop_button_bypasses_busy_ordinary_action_lane(self):
        self.run_fixture('qml', native=True)


if __name__ == '__main__':
    if len(sys.argv) == 4 and sys.argv[1] == '--fixture':
        mode, directory = sys.argv[2], Path(sys.argv[3])
        if mode == 'priority':
            owned_priority_fixture()
        elif mode == 'dag':
            dag_priority_fixture()
        elif mode == 'qml':
            qml_fixture(directory)
        else:
            raise AssertionError('Unknown owned fixture')
    else:
        unittest.main()
