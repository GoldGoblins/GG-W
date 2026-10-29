"""Owned real Hardhat headers through the real observer and native graph.

This is one disposable development node, not the user application or wallet.
Rendering cadence and observed block production are measured independently.
"""
from __future__ import annotations

from contextlib import ExitStack
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ('backend/gg_testnet.py', 'backend/network_telemetry.py',
           'backend/gg_block_graph.py', 'qml/components/BlockRelationsGraph.qml',
           'qml/components/GGStreamClock.qml', 'qml/components/GGTestnetDashboard.qml',
           'qml/components/GGMeasurementBar.qml', 'qml/components/GGText.qml',
           'qml/components/GGColorContext.qml')


def versions():
    return {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in SOURCES}


def fixture(directory):
    sys.path.insert(0, str(ROOT))
    import psutil
    from PySide6.QtCore import QObject, QEventLoop, QPointF, QTimer, QUrl, Qt
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression, qmlContext
    from PySide6.QtQuick import QQuickItem, QSGRendererInterface
    from PySide6.QtWidgets import QApplication
    from backend import gg_testnet as node
    from backend.network_telemetry import NetworkTelemetryRuntime

    source_versions = versions()
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    if os.name == 'nt':
        for name in ('consola.ttf', 'seguisym.ttf'):
            QFontDatabase.addApplicationFont(str(Path(os.environ['SystemRoot'])/'Fonts'/name))
    QFont.insertSubstitution('monospace', 'Consolas' if os.name == 'nt' else 'DejaVu Sans Mono')
    app.setFont(QFont('Consolas' if os.name == 'nt' else 'DejaVu Sans Mono'))
    engine = QQmlApplicationEngine()
    warnings = []
    engine.warnings.connect(lambda rows: warnings.extend(row.toString() for row in rows))
    source = '''import QtQuick
import QtQuick.Controls
import COMPONENTS
ApplicationWindow {
    id: testWindow; width: 950; height: 300; visible: true; color: '#111111'
    x: 320; y: 200
    flags: Qt.Tool | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus | (perfVisible ? Qt.WindowStaysOnTopHint : Qt.WindowStaysOnBottomHint)
    property real observedAt: NaN
    property int observedHeight: -1
    property int deliveryCount: 0
    property bool dashboardMode: false
    property bool perfVisible: false
    property var dashboardState: ({})
    property var dashboardObservation: ({})
    property string initialStateJson: ''
    onInitialStateJsonChanged: if(initialStateJson)dashboardState=JSON.parse(initialStateJson)
    property string latestPacket: ''
    property int appliedPacketCount: 0
    property real applyWorkTotalMs: 0
    property real applyWorkMaxMs: 0
    onLatestPacketChanged: if(dashboardMode)Qt.callLater(applyLatestPacket)
    function applyLatestPacket() {
        if(!dashboardMode || !latestPacket)return
        var began=Date.now()
        var packet=JSON.parse(latestPacket)
        dashboardObservation=packet.testnet||{}
        appliedPacketCount++
        var elapsed=Date.now()-began
        applyWorkTotalMs+=elapsed
        applyWorkMaxMs=Math.max(applyWorkMaxMs,elapsed)
    }
    GGStreamClock { id: clock; objectName: 'provenanceClock'; active: !testWindow.dashboardMode; observationTime: testWindow.observedAt; cadenceMs: 1000/75 }
    GGText { visible: !testWindow.dashboardMode; objectName: 'provenanceTitle'; x: 8; y: 8; width: parent.width-16; font.family: 'monospace'; font.pixelSize: 11; color: '#c5c5c5'; text: 'Owned real Hardhat headers | height ' + testWindow.observedHeight + ' | observations ' + testWindow.deliveryCount + ' | age ' + (isFinite(clock.ageSeconds) ? clock.ageSeconds.toFixed(3) + ' s' : 'unobserved') }
    BlockRelationsGraph { visible: !testWindow.dashboardMode; objectName: 'provenanceGraph'; x: 8; y: 33; width: parent.width-16; height: 240 }
    Rectangle { visible: !testWindow.dashboardMode; x: 8; y: parent.height-10; height: 2; width: (parent.width-16)*clock.phase; color: '#87afaf' }
    Loader { anchors.fill: parent; active: testWindow.dashboardMode; sourceComponent: Component { GGTestnetDashboard { state: testWindow.dashboardState; liveObservation: testWindow.dashboardObservation } } }
}'''.replace('COMPONENTS', json.dumps((ROOT/'qml/components').as_uri()))
    engine.loadData(source.encode(), QUrl.fromLocalFile(str(directory/'fixture.qml')))
    assert engine.rootObjects(), warnings
    window = engine.rootObjects()[0]
    graph = window.findChild(QQuickItem, 'provenanceGraph')
    clock = window.findChild(QQuickItem, 'provenanceClock')
    assert graph is not None and clock is not None

    def js(code):
        expression = QQmlExpression(qmlContext(graph), graph, code)
        value = expression.evaluate()
        assert not expression.hasError(), expression.error().toString()
        value = value[0] if isinstance(value, tuple) else value
        return value.toVariant() if hasattr(value, 'toVariant') else value

    def pump(seconds):
        if seconds <= 0:
            app.processEvents()
            return
        # Use Qt's actual event loop rather than Python polling. A manual
        # processEvents/sleep loop can miss a threaded renderer's next vsync
        # and itself throttle a native presentation benchmark to half rate.
        event_loop = QEventLoop()
        timer = QTimer()
        timer.setTimerType(Qt.PreciseTimer)
        timer.setSingleShot(True)
        timer.timeout.connect(event_loop.quit)
        timer.start(max(1, int(seconds*1000+.999)))
        event_loop.exec()
        app.processEvents()

    def descendants(item):
        for child in item.childItems():
            yield child
            yield from descendants(child)

    raw_headers = {}
    latest_rpc_replies = []
    raw_lock = threading.Lock()
    frames = []
    render_hashes = set()
    render_edges = set()
    deliveries = []
    failures = []
    resources = []
    observed_measurements = set()
    audit_each_delivery = [True]
    dashboard_active = [False]
    callback_work_ms = []
    retained_widgets = {}
    retention_verified = [False]
    retained_count = [0]
    full_start_delivery = 0
    tracked_names = {'testnetMetric', 'testnetMeasurementAxis', 'testnetAccountRow',
                     'testnetTransactionRow', 'testnetEventRow', 'testnetSelfTestCheck'}

    def widget_snapshot():
        import shiboken6
        return {(item.objectName(), item.property('index')): (shiboken6.getCppPointer(item)[0], item)
                for item in descendants(window.contentItem()) if item.objectName() in tracked_names}
    original_rpc, original_batch = node._rpc, node._rpc_batch

    def capture_header(value):
        if isinstance(value, dict) and all(key in value for key in ('number', 'hash', 'parentHash')):
            identifier = value['hash'].lower().removeprefix('0x')
            row = {'height': int(value['number'], 16),
                   'parent': value['parentHash'].lower().removeprefix('0x')}
            if row['height'] == 0:
                assert row['parent'] == '0'*64
                row['parent'] = ''  # The graph's explicit genesis has no parent edge.
            with raw_lock:
                prior = raw_headers.get(identifier)
                assert prior is None or prior == row, 'Owned header unexpectedly changed identity'
                raw_headers[identifier] = row

    def rpc(method, params=None):
        result = original_rpc(method, params)
        if method == 'eth_getBlockByNumber':
            capture_header(result)
            if params == ['latest', False]:
                latest_rpc_replies.append(time.monotonic())
        return result

    def batch(calls):
        result = original_batch(calls)
        for (method, _params), value in zip(calls, result):
            if method == 'eth_getBlockByNumber':
                capture_header(value)
        return result

    def rendered():
        rows, edges = js('_rows'), js('_edges')
        by_hash = {row['hash']: row for row in rows}
        with raw_lock:
            for row in rows:
                received = raw_headers.get(row['hash'])
                assert received is not None, 'Rendered block absent from actual RPC header replies'
                assert received['height'] == row['height']
                assert received['parent'] == row['parent_hash']
                render_hashes.add(row['hash'])
            for edge in edges:
                assert edge['from'] in by_hash and edge['to'] in by_hash
                assert raw_headers[edge['to']]['parent'] == edge['from'], 'Rendered edge has no received parent proof'
                assert raw_headers[edge['from']]['height']+1 == raw_headers[edge['to']]['height']
                render_edges.add((edge['from'], edge['to']))
        actual_items = [item for item in descendants(graph) if item.objectName() == 'relationBlock']
        assert {item.property('blockHash') for item in actual_items} == set(by_hash)
        assert len(actual_items) <= 128 and len(edges) <= 127
        assert not graph.property('geometryError')
        return rows, edges

    def deliver(raw):
        callback_started = time.perf_counter()
        try:
            packet = json.loads(raw)
            body = packet.get('testnet') or {}
            assert packet.get('network_page') == 'TESTNET' and body.get('state') == 'RUNNING', packet.get('error') or body.get('error')
            assert not body['block_graph'].get('stale')
            if not dashboard_active[0]:
                window.setProperty('observedAt', body['observation_at'])
                window.setProperty('observedHeight', body['height'])
                window.setProperty('deliveryCount', len(deliveries)+1)
                graph.setProperty('graph', body['block_graph'])
            else:
                window.setProperty('latestPacket', raw)
            if audit_each_delivery[0]:
                rendered()
            for sample in body.get('measurements') or []:
                if sample.get('operation') == 'rpc':
                    assert sample['state'] == 'PASS' and sample['elapsed_ms'] >= 0
                    observed_measurements.add((sample.get('observed_at'), sample.get('block_hash')))
            deliveries.append({'at': time.monotonic(), 'height': body['height'],
                               'headers': len(body['block_graph']['blocks']),
                               'observed_bps': body['block_graph'].get('metrics', {}).get('bps')})
            if dashboard_active[0] and not retention_verified[0] and len(deliveries)-full_start_delivery >= 30 and window.property('appliedPacketCount') >= 30:
                current = widget_snapshot()
                common = retained_widgets.keys() & current.keys()
                # ListView may finish filling its offscreen cache after the
                # first polish. Check existing slots rather than requiring
                # identical cache population at two different frame times.
                assert retained_widgets and all(any(key[0] == name for key in common) for name in tracked_names)
                assert all(prior[0] == current[key][0] for key, prior in retained_widgets.items() if key in common), 'Live observations recreated retained metric or book widgets'
                retained_count[0] = len(common)
                retention_verified[0] = True
        except Exception as error:
            import traceback
            if len(failures) < 3:
                failures.append(traceback.format_exc())
        finally:
            callback_work_ms.append((time.perf_counter()-callback_started)*1000)

    window.frameSwapped.connect(lambda: frames.append(time.perf_counter()))
    runtime = NetworkTelemetryRuntime()
    runtime.updated.connect(deliver)
    owned_process = None
    output = None
    try:
        pump(.12)
        if os.name == 'nt':
            assert window.rendererInterface().graphicsApi() == QSGRendererInterface.GraphicsApi.Direct3D11
        with ExitStack() as stack:
            stack.enter_context(patch.object(node, '_rpc', rpc))
            stack.enter_context(patch.object(node, '_rpc_batch', batch))
            initial = node.start()
            owned_process = node._process
            pid = owned_process.pid
            process = psutil.Process(pid)
            start_height = initial['height']
            frames.clear()
            started = time.monotonic()
            runtime.set_view('TESTNET')
            audit_seconds = max(2, min(8, int(os.environ.get('GG_PROVENANCE_AUDIT_SECONDS', '8'))))
            for index in range(audit_seconds):
                pump(max(0, started+index+1-time.monotonic()))
                resources.append(process.memory_info().rss)
                assert not failures, failures
            runtime.set_view('')
            pump(.05)
            duration = time.monotonic()-started
            assert deliveries and deliveries[-1]['height'] > start_height+50*audit_seconds
            assert len(deliveries) > 10*audit_seconds, 'Actual live observations must progress; no animation-only pass'
            assert len(observed_measurements) > 20*audit_seconds
            assert len(render_hashes) > 50*audit_seconds and len(render_edges) > 50*audit_seconds
            assert all(a['height'] <= b['height'] for a, b in zip(deliveries, deliveries[1:]))
            audited_frames = list(frames)
            audited_deliveries = len(deliveries)
            # A separate short presentation pass quantifies the cost of the
            # exhaustive Python/QML introspection above. It uses the same real
            # node/observer/graph, with the audit readback deferred until end.
            audit_each_delivery[0] = False
            graph_profiles = []
            renderer_profiles = () if os.environ.get('GG_PROVENANCE_QUICK') == '1' else (('GeometryRenderer', 1), ('CurveRenderer', 2))
            for renderer_name, renderer_type in renderer_profiles:
                graph.setProperty('edgeRendererType', renderer_type)
                graph.setProperty('inspectGeometry', False)
                begin_frames, begin_deliveries, begin_work = len(frames), len(deliveries), len(callback_work_ms)
                begin_time = time.monotonic()
                runtime.set_view('TESTNET')
                pump(2.0)
                runtime.set_view('')
                pump(.03)
                elapsed = time.monotonic()-begin_time
                work = callback_work_ms[begin_work:]
                graph_profiles.append({'renderer': renderer_name, 'geometry_diagnostics': False,
                    'seconds': elapsed, 'frame_swaps': len(frames)-begin_frames,
                    'actual_frame_hz': (len(frames)-begin_frames)/elapsed,
                    'actual_delivery_hz': (len(deliveries)-begin_deliveries)/elapsed,
                    'callback_ms_p50': statistics.median(work) if work else None,
                    'callback_ms_max': max(work) if work else None})
                rendered()
            full_start_delivery = len(deliveries)
            full_start_work = len(callback_work_ms)
            dashboard_active[0] = True
            initial = node.self_test()
            assert initial['last_test']['state'] == 'PASS' and len(initial['transactions']) >= 5
            # Match the production JSON wire. A Python dict here introduces
            # QVariantMap/List property wrappers and a very different access
            # cost from OmniSurface's actual JSON.parse object graph.
            window.setProperty('initialStateJson', json.dumps({'testnet': initial, 'ui_operation': {}}))
            window.setWidth(970)
            window.setHeight(620)
            window.setProperty('dashboardMode', True)
            pump(.20)
            graph = next(item for item in descendants(window.contentItem()) if item.objectName() == 'blockRelationsGraph')
            chosen_renderer = int(os.environ.get('GG_PROVENANCE_RENDERER', '1'))
            graph.setProperty('edgeRendererType', chosen_renderer)
            graph.setProperty('inspectGeometry', False)
            # The native full-width acceptance check requires an exposed
            # animation clock. An occluded bottommost window can suspend it.
            visible_presentation = os.name == 'nt' or os.environ.get('GG_PROVENANCE_VISIBLE') == '1'
            window.setProperty('perfVisible', visible_presentation)
            window.show()
            clock = window.findChild(QQuickItem, 'testnetStreamClock')
            assert graph is not None and clock is not None
            retained_widgets = widget_snapshot()
            assert all(any(key[0] == name for key in retained_widgets) for name in tracked_names), sorted(retained_widgets)
            presentation_frames_start = len(frames)
            presentation_started = time.monotonic()
            presentation_wall_started = time.time()
            rpc_http_before = node._rpc_stats['requests']
            dashboard_gui_rss_start = psutil.Process().memory_info().rss
            gui_cpu_start = psutil.Process().cpu_times()
            node_cpu_start = process.cpu_times()
            chart = window.findChild(QQuickItem, 'testnetMeasurements')
            assert chart is not None
            full_profiles = []
            runtime.set_view('TESTNET')
            input_profile = os.environ.get('GG_PROVENANCE_INPUT_PROFILE') == '1'
            profile_phases = os.environ.get('GG_PROVENANCE_PROFILE') == '1' or input_profile
            phases = (('normal', 'graph_data_detached', 'graph_measurements_detached', 'both_graph_inputs_detached', 'uninstrumented_normal')
                      if input_profile else ('normal', 'real_positions_without_interpolation', 'graph_hidden', 'real_graph_without_measurement_chart', 'uninstrumented_normal')
                      if profile_phases else ('normal', 'uninstrumented_normal'))
            live_extents = []
            dense_samples = []
            dense_failures = []
            density_work_ms = []
            density_started = [0.0]
            density_enabled = [False]

            def sample_real_dot_coverage():
                if not density_enabled[0] or time.monotonic()-density_started[0] < 1.0:
                    return
                sample_began = time.perf_counter()
                try:
                    # Read the actually retained point delegates while new
                    # headers keep arriving. Min/max extent alone passed the
                    # old split-animation bug: its single true parent edge
                    # crossed an empty ~185px interval with no block dots.
                    # One QML readback avoids recursively walking thousands
                    # of QObject children and crossing the Python/Qt boundary
                    # for each property. That diagnostic itself can stall the
                    # frame clock and is not a fair presentation measurement.
                    snapshot = js('''(function(){
                        var result=[];
                        var actualRows=_rows, actualEdges=_edges;
                        var first=actualRows.length?nodeItem(actualRows[0].hash):null;
                        var owner=first, ownerName=objectName;
                        while(owner && owner.objectName!==ownerName)owner=owner.parent;
                        var layer=first?first.parent:null;
                        var children=layer?layer.children:[];
                        var childCount=children.length;
                        for(var i=0;i<childCount;i++){
                            var n=children[i];
                            if(n.objectName==='relationBlock'){
                                var p=n.mapToItem(owner,n.width/2,n.height/2);
                                result.push([String(n.blockHash),Number(n.blockHeight),Number(p.x),Number(p.y),Number(n.opacity)]);
                            }
                        }
                        var links=[];
                        for(var j=0;j<actualEdges.length;j++)links.push([String(actualEdges[j].from),String(actualEdges[j].to)]);
                        return {points:result,edges:links,width:width,displayLimit:displayLimit,historyLength:graph.blocks.length};
                    })()''')
                    points = snapshot['points']
                    assert 48 < len(points) <= 128, ('More actual history must create more actual dots', len(points))
                    expected_points = min(snapshot['displayLimit'], snapshot['historyLength'])
                    assert len(points) == expected_points, ('Every retained eligible real block needs its own delegate', len(points), expected_points)
                    physical = {}
                    received_rows = {}
                    with raw_lock:
                        for identifier, height, x, y, opacity in points:
                            received = raw_headers.get(identifier)
                            assert received and received['height'] == height
                            received_rows[identifier] = received
                            assert math.isfinite(x) and math.isfinite(y)
                            physical[identifier] = (x, y, opacity)
                            render_hashes.add(identifier)
                        assert len(snapshot['edges']) == len(points)-1
                        for parent, child in snapshot['edges']:
                            assert parent in physical and child in physical
                            assert raw_headers[child]['parent'] == parent, 'A displayed live edge needs its actual received parent proof'
                            assert raw_headers[parent]['height']+1 == raw_headers[child]['height']
                            render_edges.add((parent, child))
                    assert len(physical) == len(points), 'No duplicate visual copies may stand in for real block history'
                    newest = sorted(received_rows, key=lambda identifier: received_rows[identifier]['height'])[-16:]
                    assert all(physical[identifier][2] >= .40 for identifier in newest), 'The newest real blocks must have visible dots, not only connecting lines'
                    width = snapshot['width']
                    nominal_pitch = max(1.0, (width-58)/max(1, len(points)-1))
                    visible_points = sorted((x, identifier, received_rows[identifier]['height'], opacity)
                                            for identifier, (x, _y, opacity) in physical.items() if opacity >= .15)
                    visible_x = [point[0] for point in visible_points]
                    assert len(visible_x) > 48, ('Count visible real dots, not only invisible delegates', len(visible_x))
                    interior = [x for x in visible_x if .05*width <= x <= .95*width]
                    gaps = [b-a for a, b in zip(interior, interior[1:])]
                    largest_gap = max(gaps, default=0.0)
                    limit = max(12.0, 3*nominal_pitch)
                    assert visible_x[0] <= .10*width and visible_x[-1] >= .90*width
                    pair = max(zip(visible_points, visible_points[1:]), key=lambda pair: pair[1][0]-pair[0][0])
                    assert largest_gap <= limit, ('Empty span between actual visible block dots', largest_gap, limit, len(points), pair)
                    bins = {min(15, max(0, int(x/width*16))) for x in visible_x}
                    assert all(index in bins for index in range(2, 14)), ('Empty interior graph bin', sorted(bins))
                    parent_gaps = []
                    for identifier, row in received_rows.items():
                        if row['parent'] in physical:
                            parent_gaps.append(abs(physical[identifier][0]-physical[row['parent']][0]))
                    largest_parent_gap = max(parent_gaps, default=0.0)
                    assert largest_parent_gap <= max(16.0, 4*nominal_pitch), ('A parent edge bridges an empty stretch', largest_parent_gap, nominal_pitch)
                    dense_samples.append({'seconds': round(time.monotonic()-density_started[0], 3),
                        'actual_points': len(points), 'visible_real_points': len(visible_x),
                        'minimum_newest_point_opacity': min(physical[identifier][2] for identifier in newest),
                        'plot_width': width, 'nominal_pitch': nominal_pitch,
                        'largest_visible_x_gap': largest_gap, 'largest_parent_x_gap': largest_parent_gap,
                        'occupied_interior_bins': sum(index in bins for index in range(2, 14)),
                        'all_point_hashes_and_parents_from_actual_rpc': True})
                except Exception:
                    import traceback
                    if len(dense_failures) < 3:
                        dense_failures.append(traceback.format_exc())
                finally:
                    density_work_ms.append((time.perf_counter()-sample_began)*1000)

            coverage_timer = QTimer()
            coverage_timer.setTimerType(Qt.PreciseTimer)
            coverage_timer.setInterval(100)
            coverage_timer.timeout.connect(sample_real_dot_coverage)
            for phase in phases:
                if input_profile:
                    detach_data = phase in ('graph_data_detached', 'both_graph_inputs_detached')
                    detach_measurements = phase in ('graph_measurements_detached', 'both_graph_inputs_detached')
                    js('''(function(){
                        var owner=parent;
                        while(owner && owner.objectName!=='testnetDashboard')owner=owner.parent;
                        if(!owner)throw new Error('Owned dashboard missing');
                        graph=DETACH_DATA?({}):Qt.binding(function(){return owner.observed.block_graph||owner.testnet.block_graph||({})});
                        measurements=DETACH_MEASUREMENTS?[]:Qt.binding(function(){return owner.measurements});
                    })()'''.replace('DETACH_DATA',str(detach_data).lower()).replace('DETACH_MEASUREMENTS',str(detach_measurements).lower()))
                graph.setProperty('animateChanges', phase in ('normal', 'uninstrumented_normal'))
                graph.setProperty('visible', phase != 'graph_hidden')
                chart.setProperty('visible', phase != 'real_graph_without_measurement_chart')
                begin_frames, begin_deliveries, begin_work = len(frames), len(deliveries), len(callback_work_ms)
                begin_time = time.monotonic()
                begin_cpu = psutil.Process().cpu_times()
                begin_applied = window.property('appliedPacketCount')
                if phase == 'normal':
                    density_started[0] = time.monotonic()
                    density_enabled[0] = True
                    coverage_timer.start()
                pump(3.0 if phase == 'uninstrumented_normal' else 2.0 if profile_phases else 8.0)
                coverage_timer.stop()
                density_enabled[0] = False
                elapsed = time.monotonic()-begin_time
                end_cpu = psutil.Process().cpu_times()
                if phase == 'normal':
                    # Inspect while new real headers are STILL arriving, not
                    # after the 420 ms animations have settled. The right-hand
                    # lightning keeps its original motion, but the older tail
                    # must occupy the left side of this same bounded graph.
                    live_points = [item for item in descendants(graph) if item.objectName() == 'relationBlock']
                    assert 48 < len(live_points) <= 128
                    extent = {'left_x': min(item.mapToItem(graph,QPointF(0,0)).x() for item in live_points),
                              'right_x': max(item.mapToItem(graph,QPointF(item.width(),0)).x() for item in live_points),
                              'plot_width': graph.width(), 'actual_points': len(live_points)}
                    assert extent['left_x'] <= .10*extent['plot_width'], extent
                    assert extent['right_x'] >= .90*extent['plot_width'], extent
                    live_extents.append(extent)
                phase_work = callback_work_ms[begin_work:]
                full_profiles.append({'phase': phase, 'seconds': elapsed,
                    'frame_swaps': len(frames)-begin_frames,
                    'actual_frame_hz': (len(frames)-begin_frames)/elapsed,
                    'actual_delivery_hz': (len(deliveries)-begin_deliveries)/elapsed,
                    'qml_applied_hz': (window.property('appliedPacketCount')-begin_applied)/elapsed,
                    'gui_cpu_seconds': end_cpu.user+end_cpu.system-begin_cpu.user-begin_cpu.system,
                    'callback_ms_p50': statistics.median(phase_work) if phase_work else None,
                    'callback_ms_max': max(phase_work) if phase_work else None})
            runtime.set_view('')
            assert not dense_failures, (dense_failures, full_profiles)
            assert len(dense_samples) >= (5 if profile_phases else 40), ('Inspect ongoing native frames throughout the real stream, not only after settling', len(dense_samples), statistics.mean(density_work_ms), max(density_work_ms), full_profiles)
            presentation_observation_ended = time.monotonic()
            presentation_wall_ended = time.time()
            rpc_http_after = node._rpc_stats['requests']
            pump(.03)
            presentation_seconds = time.monotonic()-presentation_started
            presentation_frames = frames[presentation_frames_start:]
            presentation_intervals = [(b-a)*1000 for a, b in zip(presentation_frames, presentation_frames[1:]) if 0 < b-a]
            presentation_deliveries = len(deliveries)-full_start_delivery
            full_observations = deliveries[full_start_delivery:]
            full_block_window = full_observations[-1]['at']-full_observations[0]['at'] if len(full_observations)>1 else 0
            full_block_delta = full_observations[-1]['height']-full_observations[0]['height'] if len(full_observations)>1 else 0
            full_work = callback_work_ms[full_start_work:]
            source_read_seconds = presentation_observation_ended-presentation_started
            full_latest_rpc_replies = sum(presentation_started <= stamp <= presentation_observation_ended for stamp in latest_rpc_replies)
            full_observed_rpc_samples = sum(presentation_wall_started <= stamp <= presentation_wall_ended for stamp, _identifier in observed_measurements)
            assert full_latest_rpc_replies/source_read_seconds >= 60, 'Actual loopback observation rate must meet this owned 60/s acceptance target'
            gui_cpu_end = psutil.Process().cpu_times()
            node_cpu_end = process.cpu_times()
            window.setProperty('perfVisible', False)
            graph.setProperty('visible', True)
            graph.setProperty('animateChanges', True)
            chart.setProperty('visible', True)
            assert not failures, failures
            assert retention_verified[0]
            paused_rows, paused_edges = rendered()
            label_loaders = [item for item in descendants(graph) if item.objectName() == 'relationBlockLabelLoader']
            assert label_loaders and all(not item.property('active') and item.property('item') is None for item in label_loaders)
            details_content = window.findChild(QObject, 'blockRelationsDetailsContent')
            assert details_content is not None and not details_content.property('active') and details_content.property('item') is None
            # ShapePath lives in the Shape's QML data list rather than its
            # QObject child tree. Inspect the actual visual Shape items and
            # their native path lists, not only the application edge model.
            native_shapes = [item for item in descendants(graph) if item.metaObject().className().startswith('QQuickShape')]
            native_path_count = 0
            for shape in native_shapes:
                expression = QQmlExpression(qmlContext(shape), shape, 'data.length')
                value = expression.evaluate()
                assert not expression.hasError(), expression.error().toString()
                native_path_count += int(value[0] if isinstance(value, tuple) else value)
            assert native_path_count == len(paused_edges), (native_path_count, len(paused_edges), len(native_shapes))
            paused_delivery_count = len(deliveries)
            paused_clock = clock.property('nowMillis')
            paused_frames = len(frames)
            pump(.55)
            after_rows, after_edges = rendered()
            assert (paused_rows, paused_edges) == (after_rows, after_edges), 'Animation fabricated or removed backend topology'
            assert len(deliveries) == paused_delivery_count
            assert clock.property('nowMillis') > paused_clock, 'Presentation clock did not run during fixed-topology test'
            assert len(frames) > paused_frames
            frozen_hashes = len(render_hashes)
            graph.setProperty('visible', False)
            clock.setProperty('active', False)
            pump(.12)
            idle_frames = len(frames)
            pump(.20)
            idle_frame_delta = len(frames)-idle_frames
            assert len(render_hashes) == frozen_hashes
            graph.setProperty('visible', True)
            pump(.05)
            evidence = Path(os.environ.get('GG_PROVENANCE_EVIDENCE', ROOT/'.runtime/dag-live'))
            evidence.mkdir(parents=True, exist_ok=True)
            assert window.grabWindow().save(str(evidence/'provenance-native.png'))
            intervals = [(b-a)*1000 for a, b in zip(audited_frames, audited_frames[1:]) if 0 < b-a < .2]
            real_bps = (deliveries[audited_deliveries-1]['height']-deliveries[0]['height'])/(deliveries[audited_deliveries-1]['at']-deliveries[0]['at'])
            output = {'status': 'PASS', 'scope': 'Owned disposable Hardhat 3, loopback only; no user node or wallet',
                      'renderer': 'Direct3D11' if os.name == 'nt' else 'software',
                      'seconds': duration, 'real_observed_height_delta': deliveries[audited_deliveries-1]['height']-deliveries[0]['height'],
                      'real_observed_bps': real_bps, 'actual_observation_deliveries': audited_deliveries,
                      'actual_observation_hz': audited_deliveries/duration,
                      'actual_rpc_measurements': len(observed_measurements),
                      'received_header_hashes': len(raw_headers), 'rendered_unique_header_hashes': len(render_hashes),
                      'rendered_unique_verified_parent_edges': len(render_edges),
                      'maximum_retained_visible_nodes': 128, 'all_rendered_topology_from_rpc_replies': True,
                      'native_retained_path_count': native_path_count,
                      'native_retained_shape_count': len(native_shapes),
                      'point_caption_trees_allocated': 0,
                      'closed_details_trees_allocated': 0,
                      'fixed_topology_presentation_seconds': .55, 'new_blocks_during_presentation_only': 0,
                      'frame_swaps': len(audited_frames), 'median_frame_interval_ms': statistics.median(intervals) if intervals else None,
                      'presentation_fps_reciprocal_median': 1000/statistics.median(intervals) if intervals else None,
                      'presentation_note': 'Measured owned fixture, not a whole-app or minimum-FPS guarantee',
                      'retained_widget_types': sorted(tracked_names),
                      'retained_widget_count_over_30_updates': retained_count[0],
                      'graph_renderer_profiles': graph_profiles,
                      'full_dashboard_profiles': full_profiles,
                      'full_width_tail_while_real_blocks_arrive': live_extents,
                      'ongoing_actual_dot_coverage': dense_samples,
                      'dot_coverage_readback_ms_mean': statistics.mean(density_work_ms),
                      'dot_coverage_readback_ms_max': max(density_work_ms),
                      'uninstrumented_native_presentation': next((row for row in full_profiles if row['phase'] == 'uninstrumented_normal'), None),
                      'maximum_visible_real_point_gap_px': max(row['largest_visible_x_gap'] for row in dense_samples),
                      'maximum_actual_parent_x_gap_px': max(row['largest_parent_x_gap'] for row in dense_samples),
                      'presentation_without_exhaustive_readback': {'seconds': presentation_seconds,
                          'actual_block_height_delta': full_block_delta,
                          'actual_block_window_seconds': full_block_window,
                          'actual_block_bps': full_block_delta/full_block_window if full_block_window>0 else None,
                          'component': 'Actual GGTestnetDashboard, 970x620, stable JSON base plus separate actual liveObservation',
                          'base_object_type': 'QML JSON.parse, plain JavaScript objects and arrays',
                          'edge_renderer': 'GeometryRenderer (production default)' if chosen_renderer == 1 else 'CurveRenderer (owned fixture override)',
                          'geometry_diagnostics': False,
                          'fixture_adapter_index_override': os.environ.get('QT_D3D_ADAPTER_INDEX'),
                          'window_placement': 'Nonfocusable topmost visible preview' if visible_presentation else 'Nonfocusable bottommost, possibly occluded',
                          'actual_deliveries': presentation_deliveries,
                          'source_observation_seconds': source_read_seconds,
                          'actual_latest_rpc_replies': full_latest_rpc_replies,
                          'actual_latest_rpc_observation_hz': full_latest_rpc_replies/source_read_seconds,
                          'unique_rpc_measurements_reaching_gui': full_observed_rpc_samples,
                          'unique_rpc_measurements_reaching_gui_hz': full_observed_rpc_samples/source_read_seconds,
                          'actual_http_rpc_requests': rpc_http_after-rpc_http_before,
                          'qml_applied_observations': window.property('appliedPacketCount'),
                          'qml_apply_mean_ms': window.property('applyWorkTotalMs')/max(1,window.property('appliedPacketCount')),
                          'qml_apply_max_ms': window.property('applyWorkMaxMs'),
                          'actual_delivery_hz': presentation_deliveries/presentation_seconds,
                          'frame_swaps': len(presentation_frames),
                          'actual_frame_hz': len(presentation_frames)/presentation_seconds,
                          'median_frame_interval_ms': statistics.median(presentation_intervals) if presentation_intervals else None,
                          'fps_reciprocal_median': 1000/statistics.median(presentation_intervals) if presentation_intervals else None,
                          'gui_rss_start_bytes': dashboard_gui_rss_start,
                          'gui_rss_end_bytes': psutil.Process().memory_info().rss,
                          'node_rss_end_bytes': process.memory_info().rss},
                      'full_dashboard_callback_ms_p50': statistics.median(full_work) if full_work else None,
                      'full_dashboard_callback_ms_max': max(full_work) if full_work else None,
                      'full_dashboard_gui_cpu_seconds': gui_cpu_end.user+gui_cpu_end.system-gui_cpu_start.user-gui_cpu_start.system,
                      'full_dashboard_node_cpu_seconds': node_cpu_end.user+node_cpu_end.system-node_cpu_start.user-node_cpu_start.system,
                      'idle_frame_swaps_over_200ms': idle_frame_delta,
                      'node_rss_peak_sampled_bytes': max(resources), 'qml_warnings': warnings}
    finally:
        runtime.close()
        node.stop()
        window.close()
        engine.deleteLater()
        app.processEvents()
    assert not warnings, warnings
    assert owned_process is not None and owned_process.poll() is not None
    assert not runtime._worker.is_alive()
    assert output is not None
    output['owned_node_stopped'] = True
    output['observer_stopped'] = True
    output['source_versions'] = source_versions
    output['source_changed'] = [name for name, value in versions().items() if source_versions[name] != value]
    if output['source_changed']:
        output['status'] = 'SOURCE_CHANGED_RECHECK_REQUIRED'
    evidence = Path(os.environ.get('GG_PROVENANCE_EVIDENCE', ROOT/'.runtime/dag-live'))
    (evidence/'provenance.json').write_text(json.dumps(output, indent=2)+'\n', encoding='utf-8')
    assert not output['source_changed'], output['source_changed']
    print(json.dumps(output))


class NetworkLiveProvenanceTests(unittest.TestCase):
    def test_owned_real_node_observer_and_rendered_topology_provenance(self):
        with tempfile.TemporaryDirectory(prefix='gg-real-network-provenance-') as temporary:
            directory = Path(temporary)
            env = os.environ.copy()
            env.update(QT_QUICK_CONTROLS_STYLE='Basic', GG_DESKTOP_STATE_ROOT=str(directory/'state'),
                       GG_DESKTOP_DATA_ROOT=str(directory/'data'))
            if os.name == 'nt':
                env.pop('QT_QUICK_BACKEND', None)
                env.update(QT_QPA_PLATFORM='windows', QSG_RHI_BACKEND='d3d11')
            else:
                env.update(QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software')
            result = subprocess.run([sys.executable, '-X', 'utf8', '-B', str(Path(__file__).resolve()),
                                     '--fixture', temporary], cwd=ROOT, env=env, capture_output=True,
                                    text=True, encoding='utf-8', timeout=45)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            print(result.stdout.strip())


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--fixture':
        fixture(Path(sys.argv[2]))
    else:
        unittest.main()
