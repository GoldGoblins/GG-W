"""Real local-network QML: truthful states, exact review/actions and native geometry.

Fixtures contain public synthetic identities only. No test starts a real node,
uses a key, touches the user's wallet, or sends a network request.
"""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

PROJECT = Path(__file__).resolve().parents[1]
SIZES = ((360, 360), (640, 460), (970, 460), (360, 640), (430, 700), (820, 700), (970, 620), (970, 680), (1200, 800), (1586, 992))


def fixture(directory: Path):
    from PySide6.QtCore import QObject, QPointF, Qt, QUrl, Slot
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression, qmlContext
    from PySide6.QtQuick import QQuickItem, QSGRendererInterface
    from PySide6.QtTest import QSignalSpy, QTest
    from PySide6.QtWidgets import QApplication

    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    if os.name == 'nt':
        for name in ('consola.ttf', 'consolab.ttf', 'seguisym.ttf'):
            QFontDatabase.addApplicationFont(str(Path(os.environ['SystemRoot']) / 'Fonts' / name))
    family = 'Consolas' if os.name == 'nt' else 'DejaVu Sans Mono'
    QFont.insertSubstitution('monospace', family)
    app.setFont(QFont(family))
    addresses = ['0x' + str(index + 1) * 40 for index in range(4)]
    contract = '0x' + 'a' * 40
    testnet = {
        'state': 'RUNNING', 'available': True, 'engine': 'Hardhat 3',
        'chain_id': 'eip155:31337', 'chain_number': 31337, 'binding': 'LOOPBACK_ONLY',
        'production': False, 'native_symbol': 'DEV', 'symbol': 'GG-TEST', 'decimals': 6,
        'rpc_url': 'http://127.0.0.1:8875', 'contract': contract, 'height': 5, 'peer_count': 0,
        'accounts': [{'index': i, 'address': address, 'native': '9999.999999999999123456' if not i else '10000',
                      'token': '999999.123456' if not i else '0', 'nonce': i} for i, address in enumerate(addresses)],
        'session_transactions': 5, 'transaction_limit': 256, 'review': None, 'unresolved': False,
        'transactions': [{'kind': 'TRANSFER', 'sender': addresses[0], 'recipient': addresses[1],
                          'asset': 'GG-TEST', 'symbol': 'GG-TEST', 'amount': '10.123456', 'txid': '0x' + 'b' * 64,
                          'state': 'CONFIRMED', 'block': 5, 'gas_used': '52341', 'observed_at': 1700000000}],
        'measurements': [{'operation': ('rpc', 'transaction', 'self_test')[i % 3],
                          'elapsed_ms': (40, 80, 220)[i % 3] + i * 2, 'observed_at': 1700000000 + i,
                          'state': 'PASS'} for i in range(16)],
        'events': [{'ts': 1700000000 + i, 'kind': 'CONFIRMED', 'message': 'Isolerad syntetisk testhändelse ' + str(i)} for i in range(48, 0, -1)],
        'last_test': {'state': 'PASS', 'checks': [{'asset': asset, 'from': source, 'to': target, 'state': 'PASS'}
                      for asset in ('GG-TEST', 'NATIVE') for source, target in ((0, 1), (1, 0))],
                      'token_balances_restored': True, 'supply_verified': True},
        'error': '', 'gas_used': '52341', 'gas_limit': '30000000', 'base_fee_atomic': '7421436',
        'resource_metrics': {'memory_committed_bytes': 134217728, 'memory_resident_bytes': 145000000, 'cpu_seconds': 75},
        'resource_limits': {'provider': 'WINDOWS_JOB_OBJECT', 'verified': True, 'memory_bytes': 536870912,
                            'cpu_seconds': 300, 'active_process_limit': 1, 'kill_on_close': True},
    }
    lab = {
        'state': 'ACTIVE_SESSION', 'chain_id': 'gglab:synthetic-public-session', 'height': 12, 'pending': 1,
        'enabled': [True] * 4, 'participating': True, 'retry_packets': 1,
        'participants': [{'address': 'SyntheticPublicParticipant' + str(i), 'balance': '249999.123456' if not i else '250000', 'enabled': True} for i in range(4)],
        'config': {'preset': 'mobile', 'role': 'light'}, 'verification': {'state': 'VERIFIED', 'blocks': 12},
        'economics': {'burn_bps': 1000, 'holder_bps': 2000, 'contributor_bps': 7000},
        'transport': {'received_bytes': 1800, 'accepted_bytes': 1700, 'delivered': 2, 'rejected': 1,
                      'duplicates': 2, 'expired': 0, 'signature_checks': 2, 'queued': 1,
                      'storage_used': 1100, 'storage_limit': 65536, 'global_credit': 6400, 'bytes_per_minute': 8192},
        'dashboard': {
            'limits': {'pending': 64, 'blocks': 256, 'recent_blocks': 16, 'measurements': 32},
            'quorum': {'enabled': 4, 'total': 4, 'required': 3, 'missing': 0, 'last_signatures': 3},
            'conservation': {'state': 'BALANCED', 'supply_atomic': '1000000000000', 'balances_atomic': '999999988000',
                             'burned_atomic': '1000', 'contributor_pool_atomic': '11000', 'accounted_atomic': '1000000000000', 'decimals': 6, 'symbol': 'GG-LAB'},
            'pending_transactions': [{'index': 0, 'txid': 'c' * 64, 'sender_index': 0, 'recipient_index': 1, 'amount': '1.123456', 'fee': '0.001', 'nonce': 3}],
            'recent_blocks': [{'height': 12, 'txid': 'd' * 64, 'sender_index': 1, 'recipient_index': 0, 'amount': '2.000001', 'fee': '0.001', 'signatures': 3}],
            'measurements': [{'operation': ('verify', 'commit', 'transport_test')[i % 3], 'elapsed_ms': i + 1.25,
                              'observed_at': 1700000000 + i, 'state': 'PASS'} for i in range(12)]},
    }
    payload = {'assets': [], 'ui_operation': {}, 'testnet': testnet, 'lab': lab,
               'events': [{'ts': 1700000000, 'scope': 'lab', 'kind': 'FINALIZED', 'message': 'Isolerad syntetisk labbhändelse'}],
               'web_node': {'state': 'STOPPED', 'private_keys': False}, 'web_sample': {'schema': 'synthetic-public-sample'}}

    class Host(QObject):
        def __init__(self):
            super().__init__()
            self.calls = []
            self.copied = []
        @Slot(str, str)
        def record(self, name, raw): self.calls.append((name, json.loads(raw)))
        @Slot(str, result=str)
        def tmogCopy(self, value): self.copied.append(value); return value
    host = Host()
    engine = QQmlApplicationEngine()
    warnings = []
    phase = ['initial component load']
    def record_warnings(rows):
        messages = [row.toString() for row in rows]
        warnings.extend(messages)
        print(json.dumps({'warning_phase': phase[0], 'messages': messages}), flush=True)
    engine.warnings.connect(record_warnings)
    engine.rootContext().setContextProperty('fixtureHost', host)
    engine.rootContext().setContextProperty('fixturePayload', payload)
    engine.rootContext().setContextProperty('nativeNetworkProbe', os.environ.get('GG_NETWORK_NATIVE') == '1')
    path = directory / 'fixture.qml'
    path.write_text('''import QtQuick
import QtQuick.Controls
import COMPONENTS
ApplicationWindow {
    id: testWindow; width:970; height:680; visible:true; color:'#111111'
    x:nativeNetworkProbe?320:0; y:nativeNetworkProbe?200:0
    flags:nativeNetworkProbe?(Qt.Tool|Qt.FramelessWindowHint|Qt.WindowDoesNotAcceptFocus|Qt.WindowStaysOnBottomHint):Qt.Window
    property var fixtureData:fixturePayload
    property bool testnetMode:true
    Loader {id:dashboardLoader;objectName:'dashboardLoader';anchors.fill:parent;sourceComponent:testWindow.testnetMode?testnetComponent:labComponent}
    Component {id:testnetComponent; GGTestnetDashboard {state:testWindow.fixtureData;surfaceHost:fixtureHost;onActionRequested:function(name,args){fixtureHost.record(name,JSON.stringify(args))}}}
    Component {id:labComponent; NetworkDashboard {state:testWindow.fixtureData;surfaceHost:fixtureHost;onActionRequested:function(name,args){fixtureHost.record(name,JSON.stringify(args))}}}
}'''.replace('COMPONENTS', json.dumps((PROJECT / 'qml/components').as_uri())), encoding='utf-8')
    engine.load(QUrl.fromLocalFile(str(path)))
    assert engine.rootObjects(), warnings
    window = engine.rootObjects()[0]
    QTest.qWait(100)
    if os.environ.get('GG_NETWORK_NATIVE') == '1':
        # Windows can return an incompletely retained RHI capture for a window
        # wholly outside the desktop. Keep this owned, non-focusable probe
        # exposed behind other windows to exercise the real compositor path.
        window.lower()
        assert QTest.qWaitForWindowExposed(window, 3000)
    window.grabWindow()
    if os.environ.get('GG_NETWORK_NATIVE') == '1':
        assert window.rendererInterface().graphicsApi() == QSGRendererInterface.GraphicsApi.Direct3D11

    def js(owner, text):
        expression = QQmlExpression(qmlContext(owner), owner, text)
        value = expression.evaluate()
        assert not expression.hasError(), expression.error().toString()
        return value[0] if isinstance(value, tuple) else value
    def items(owner):
        yield owner
        for child in owner.childItems(): yield from items(child)
    def named(owner, name):
        item = next((item for item in items(owner) if item.objectName() == name), None)
        if item is None: item = owner.findChild(QQuickItem, name)
        assert item is not None, name + ' missing'
        return item
    drained_incubations = []
    def drain_incubation():
        # The native probe is non-focusable and may be occluded. Its frame
        # controller can therefore leave nested delegate incubation pending
        # even after the outer Loader reports Ready. Complete that real Qt
        # work before inspecting or replacing the component's context.
        controller = engine.incubationController()
        if controller is None:
            return
        pending = controller.incubatingObjectCount()
        if pending:
            drained_incubations.append(pending)
        deadline = time.monotonic()+5
        while controller.incubatingObjectCount() and time.monotonic() < deadline:
            controller.incubateFor(5)
            app.processEvents()
        assert controller.incubatingObjectCount() == 0, ('nested dashboard incubation did not finish', phase[0])
    def settle():
        QTest.qWait(35)
        window.grabWindow()  # Polish native unexposed-window geometry too.
        drain_incubation()
    def wait_dashboard(testnet_mode):
        loader = named(window.contentItem(), 'dashboardLoader')
        expected = 'testnetDashboard' if testnet_mode else 'networkDashboard'
        expression = 'status === Loader.Ready && item !== null && item.objectName === '+json.dumps(expected)
        deadline = time.monotonic()+5
        while not js(loader, expression) and time.monotonic() < deadline:
            QTest.qWait(5)
        assert js(loader, expression), ('dashboard component did not finish incubation', expected, warnings)
        return loader.property('item')
    def choose_mode(testnet_mode):
        # This fixture checks fully created workspaces. Looking up a named
        # descendant after a fixed sleep can return a partially incubated
        # object on a busy native renderer; replacing it again destroys the
        # still-active creation context rather than testing its ready UI.
        phase[0] = 'wait current dashboard before switching to '+str(testnet_mode)
        wait_dashboard(window.property('testnetMode'))
        drain_incubation()
        phase[0] = 'replace dashboard source with '+str(testnet_mode)
        window.setProperty('testnetMode', testnet_mode)
        phase[0] = 'wait dashboard after switching to '+str(testnet_mode)
        dashboard = wait_dashboard(testnet_mode)
        drain_incubation()
        phase[0] = 'reset full payload after switching to '+str(testnet_mode)
        window.setProperty('fixtureData', deepcopy(payload))
        phase[0] = 'settle ready dashboard '+str(testnet_mode)
        settle()
        return dashboard
    def push(data):
        window.setProperty('fixtureData', deepcopy(data)); settle()
    def scroll_to(root, item, rail=False):
        prefix = 'testnet' if root.objectName() == 'testnetDashboard' else 'network'
        def beneath(child,ancestor):
            while child is not None:
                if child is ancestor:return True
                child=child.parentItem()
            return False
        def fits(child,viewport):
            top=child.mapToItem(viewport,QPointF(0,0)).y()
            return child.isVisible() and top>=-1 and top+child.height()<=viewport.height()+1
        railview=named(root,prefix+'TelemetryScroll')
        if rail or beneath(item,railview):
            count=int(js(railview,'sections.length'))
            for section in range(1,count+2):
                railview.setProperty('page',section);settle()
                if fits(item,railview):return
            raise AssertionError(('rail section does not expose control',item.objectName()))
        main=named(root,prefix+'MainScroll')
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
        settle()
        assert item.isVisible() and item.isEnabled(), (item.objectName(), 'not interactive')
        point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
        settle()
    def capture(name):
        target = os.environ.get('GG_NETWORK_UI_EVIDENCE')
        if target:
            out = Path(target) / ('direct3d' if os.environ.get('GG_NETWORK_NATIVE') == '1' else 'software')
            out.mkdir(parents=True, exist_ok=True)
            window.grabWindow().save(str(out / name))
    def assert_glyph(item):
        image = window.grabWindow()
        scale = image.width() / window.width()
        point = item.mapToScene(QPointF(0, 0))
        ink = 0
        for y in range(round((point.y() + 6) * scale), round((point.y() + item.height() - 6) * scale)):
            for x in range(round((point.x() + 6) * scale), round((point.x() + item.width() - 6) * scale)):
                color = image.pixelColor(x, y)
                # Quiet controls intentionally use opacity .65; software
                # antialiasing can cap their line pixels near RGB(102,102,102).
                ink += color.red() + color.green() + color.blue() > 200
        assert ink > 8, ('native glyph missing', item.objectName(), ink)
    def assert_title():
        prefix='testnet' if root.objectName()=='testnetDashboard' else 'network'
        toolbar=named(root,prefix+'Toolbar')
        assert toolbar.isVisible() and 0<toolbar.height()<=64
        assert named(root,prefix+'MainScroll').property('noPageScroll')
    geometry = []
    for testnet_mode in (True, False):
        root = choose_mode(testnet_mode)
        prefix = 'testnet' if testnet_mode else 'network'
        for width, height in SIZES:
            phase[0] = prefix+' geometry '+str(width)+'x'+str(height)
            window.setWidth(width); window.setHeight(height); settle()
            main = named(root, prefix + 'MainScroll')
            main.setProperty('page', 0); settle()
            assert root.width() == width and root.height() == height
            assert root.property('dockAvailable') == (width >= 820)
            expected_main = width - (root.property('railWidth') if width >= 820 else 0)
            assert abs(main.width() - expected_main) < .1
            rows = [item for item in items(root) if item.objectName() == prefix + ('AccountRow' if testnet_mode else 'ParticipantRow')]
            assert len(rows) == 4
            for row in rows:
                assert row.mapToItem(root, QPointF(row.width(), 0)).x() <= main.width() + .1
            if testnet_mode:
                assert len([item for item in items(root) if item.objectName() == 'testnetMeasurementBar']) == 16
                native = next(item for item in items(rows[0]) if item.objectName() == 'testnetNativeBalance')
                assert '9999.999999999999123456' in native.property('text')
                assert '9999.999999999999123456' in js(native,'Accessible.name')
                assert js(native,'ToolTip.text')==native.property('text')
                if width == 970:
                    scroll_to(root,named(root,'testnetPrepare'))
                    form = named(root, 'testnetTransferForm')
                    bottom = form.mapToItem(root, QPointF(0, form.height())).y()
                    assert bottom <= height, ('transfer inputs below fold', bottom, height)
                    prepare = named(root, 'testnetPrepare')
                    assert prepare.mapToItem(root, QPointF(0, prepare.height())).y() <= height
                    assert not prepare.property('contentItem').property('truncated')
            capture(prefix + '-' + str(width) + '.png')
            assert_title()
            if height <= 460:
                main.setProperty('page',1);settle()
                if testnet_mode and width==360:
                    root.setProperty('externalRecipient',True);settle()
                names = ['testnetSender','testnetRecipient','testnetAsset','testnetAmount','testnetPrepare'] if testnet_mode else ['networkSender','networkRecipient','networkAmount','networkQueueTransfer']
                if testnet_mode and width==360:names.append('testnetExternalAddress')
                for control_name in names:
                    control=named(root,control_name);ancestor=control.parentItem()
                    assert control.isVisible(),control_name
                    while ancestor is not None and ancestor is not root:
                        if ancestor.clip():
                            top=control.mapToItem(ancestor,QPointF(0,0)).y()
                            assert top>=-1 and top+control.height()<=ancestor.height()+1,(control_name,'clipped form',top,control.height(),ancestor.objectName(),ancestor.height(),ancestor.y(),main.property('formFocused'),main.height())
                        ancestor=ancestor.parentItem()
                if testnet_mode:root.setProperty('externalRecipient',False)
                main.setProperty('page',0);settle()
            if testnet_mode and width < 1100:
                assert_glyph(named(root, 'testnetRefresh'))
            if width < 820:
                js(root, 'toggleDetails()'); settle()
                assert root.property('detailsVisible')
                if testnet_mode:
                    scroll_to(root,named(root,'testnetCopyRpc'),True)
                    assert_glyph(named(root, 'testnetCopyRpc'))
                capture(prefix + '-' + str(width) + '-drawer.png')
                js(root, 'toggleDetails()'); settle()
                assert not root.property('detailsVisible')
            else:
                js(root, 'toggleDetails()'); settle()
                assert abs(main.width() - width) < .1
                js(root, 'toggleDetails()'); settle()
            geometry.append({'mode': prefix, 'size': [width, height], 'main_width': round(main.width(), 1)})

    window.setWidth(970); window.setHeight(680)
    root = choose_mode(True)
    main=named(root,'testnetMainScroll');main.setProperty('page',0);settle()
    assert main.property('desktop') and not named(root,'testnetTransferTab').isVisible()
    for section in ('Summary','Measurements','Relations','Accounts','History','Transfer'):
        panel=named(root,'testnet'+section+'Viewport')
        assert panel.isVisible() and panel.height()>45
        assert panel.y()+panel.height()<=root.height()-30
    assert named(root,'testnetSender').isVisible()
    assert named(root,'testnetAccountsList').isVisible()
    assert abs(named(root, 'testnetMemoryBar').property('fraction') - .25) < 1e-9
    assert abs(named(root, 'testnetCpuBar').property('fraction') - .25) < 1e-9
    refresh = QSignalSpy(root.refreshRequested)
    page = QSignalSpy(root.pageRequested)
    click(named(root, 'testnetRefresh')); assert refresh.count() == 1
    click(named(root, 'testnetLabMode')); assert page.at(0)[0] == 'LAB'
    copy = next(item for item in items(root) if item.objectName() == 'testnetCopyAccount')
    scroll_to(root,copy);click(copy); assert host.copied[-1] == addresses[0]
    root.setProperty('senderIndex', 2); root.setProperty('recipientIndex', 3)
    amount = named(root, 'testnetAmount'); amount.setProperty('text', '1.234567')
    prepare = named(root, 'testnetPrepare'); scroll_to(root, prepare); click(prepare)
    assert host.calls[-1] == ('testnet_prepare', {'sender': 2, 'recipient': addresses[3], 'amount': '1.234567', 'asset': 'GG-TEST'})
    # The review is deliberately different from the editable draft. Confirmation
    # must bind solely to the immutable backend review, never reconstructed UI.
    reviewed = deepcopy(payload)
    reviewed['testnet']['review'] = {'id': 'synthetic-review-id', 'review_digest': 'e' * 64,
        'sender_index': 0, 'sender': addresses[0], 'recipient': addresses[1], 'amount': '0.000001',
        'asset': 'GG-TEST', 'symbol': 'GG-TEST', 'chain_id': 'eip155:31337', 'contract': contract,
        'max_fee': '0.000123456789123456'}
    push(reviewed)
    for name in ('testnetSender', 'testnetRecipient', 'testnetAsset', 'testnetAmount', 'testnetPrepare'):
        assert not named(root, name).isEnabled(), name
    assert named(root, 'testnetReview').isVisible()
    send = named(root, 'testnetSend'); scroll_to(root, send); capture('testnet-review.png'); click(send)
    # Retained clipping must preserve the fixed toolbar after a native RHI
    # scroll. This catches a viewport-offset error not visible in software.
    assert_title()
    assert host.calls[-1] == ('testnet_send', {'id': 'synthetic-review-id', 'review_digest': 'e' * 64})
    cancel = named(root, 'testnetCancel'); click(cancel); assert host.calls[-1] == ('testnet_cancel', {})
    blocked = deepcopy(reviewed); blocked['ui_operation'] = {'state': 'approval_required'}; push(blocked)
    before = len(host.calls)
    js(root, 'send()')
    assert len(host.calls) == before
    assert not named(root, 'testnetSend').isEnabled()
    # Cancelling an already-owned node must remain available while another
    # action is waiting for approval. It grants no new send/start operation.
    assert named(root, 'testnetStop').isEnabled()
    js(root, "run('testnet_stop',{})")
    assert host.calls[before:] == [('testnet_stop', {})]
    # Read failures preserve cached account data but permit no state-changing
    # operation except stopping the owned node. Bytecode is no longer current.
    failed = deepcopy(payload); failed['testnet']['state'] = 'READ_FAILED'; failed['testnet']['error'] = 'GG_TESTNET_READ_FAILED'; push(failed)
    for name in ('testnetDeploy', 'testnetPrepare', 'testnetSelfTest'):
        assert not named(root, name).isEnabled(), name
    assert named(root, 'testnetStop').isEnabled()
    assert 'äldre' in named(root, 'testnetOperationNotice').property('text')
    main = named(root, 'testnetMainScroll'); main.setProperty('page', 0); settle(); capture('testnet-read-failed.png')
    before = len(host.calls); js(root, "run('testnet_self_test',{})"); assert len(host.calls) == before
    uncertain = deepcopy(payload); uncertain['testnet']['unresolved'] = True; push(uncertain)
    assert not named(root, 'testnetPrepare').isEnabled() and not named(root, 'testnetSelfTest').isEnabled()
    # Missing dependencies produce only a read-only help dialog, never a hidden
    # network installer or synthetic successful start.
    stopped = deepcopy(payload)
    stopped['testnet'].update(state='STOPPED', available=False, accounts=[], contract='', height=None,
                              transactions=[], measurements=[], events=[], last_test=None, review=None)
    push(stopped)
    assert len([item for item in items(root) if item.objectName() == 'testnetMeasurementBar']) == 0
    assert not named(root, 'testnetStart').isEnabled()
    missing_resources = deepcopy(stopped)
    missing_resources['testnet']['resource_metrics'] = {'memory_committed_bytes': None, 'cpu_seconds': None}
    missing_resources['testnet']['resource_limits'] = {'verified': False, 'provider': 'UNAVAILABLE', 'memory_bytes': None, 'cpu_seconds': None}
    push(missing_resources)
    assert not named(root, 'testnetMemoryBar').property('sampled')
    assert not named(root, 'testnetCpuBar').property('sampled')
    main.setProperty('page', 0); settle(); before = len(host.calls); click(named(root, 'testnetInstall'))
    assert len(host.calls) == before
    assert root.findChild(QObject, 'testnetSetupHelp').property('visible')
    QTest.keyClick(window, Qt.Key_Escape); settle()
    stopped['testnet']['available'] = True; push(stopped)
    assert named(root, 'testnetStart').isEnabled()
    click(named(root, 'testnetStart')); assert host.calls[-1] == ('testnet_start', {})
    capture('testnet-stopped.png')
    push(payload)
    all_events = named(root, 'testnetAllEvents'); scroll_to(root, all_events, rail=True); click(all_events)
    listing = root.findChild(QQuickItem, 'testnetAllEventsList')
    assert listing is not None and listing.property('count') == 48
    QTest.keyClick(window, Qt.Key_Escape); settle()
    # Lab mode retains its real actions and rejects unavailable signing states.
    root = choose_mode(False)
    root.setProperty('senderIndex', 2); root.setProperty('recipientIndex', 3)
    named(root, 'networkAmount').setProperty('text', '1.000001')
    queue = named(root, 'networkQueueTransfer'); scroll_to(root, queue); click(queue)
    assert host.calls[-1] == ('lab_send', {'sender': 2, 'recipient': 3, 'amount': '1.000001'})
    commit = named(root, 'networkCommit'); scroll_to(root, commit); click(commit); assert host.calls[-1] == ('lab_commit', {})
    loss = named(root, 'networkLossTest'); scroll_to(root, loss); click(loss); assert host.calls[-1] == ('transport_test', {'loss': True})
    invalid = deepcopy(payload); invalid['lab']['state'] = 'INVALID_SESSION'; invalid['lab']['verification'] = {'state': 'INVALID'}; push(invalid)
    assert 'Ogiltig' in root.property('sessionLabel')
    for name in ('networkQueueTransfer', 'networkCommit', 'networkLossTest'):
        assert not named(root, name).isEnabled(), name
    sealed = deepcopy(payload); sealed['lab']['state'] = 'SEALED_SESSION'; push(sealed)
    assert not named(root, 'networkQueueTransfer').isEnabled()
    missing = deepcopy(payload); missing['lab']['dashboard']['quorum']['enabled'] = 2; push(missing)
    assert not named(root, 'networkCommit').isEnabled()
    blocked = deepcopy(payload); blocked['ui_operation'] = {'state': 'approval_required'}; push(blocked)
    before = len(host.calls); js(root, "run('lab_send',{})"); assert len(host.calls) == before
    assert not named(root, 'networkQueueTransfer').isEnabled()
    push(payload)
    settle()
    swaps = QSignalSpy(window.frameSwapped)
    QTest.qWait(150)
    assert swaps.count() <= 1, ('idle dashboard is repainting continuously', swaps.count())
    assert not warnings, warnings
    print(json.dumps({'status': 'PASS', 'geometry_cases': len(geometry), 'native': os.environ.get('GG_NETWORK_NATIVE') == '1',
                      'exact_review': True, 'real_qml': True, 'warnings': len(warnings),
                      'nested_incubation_drains': drained_incubations}))
    window.close(); engine.deleteLater(); app.processEvents()


class NetworkDashboardUi(unittest.TestCase):
    def run_fixture(self, native=False):
        with tempfile.TemporaryDirectory(prefix='gg-network-dashboard-test-') as temporary:
            directory = Path(temporary)
            env = os.environ.copy()
            env.update(QT_QUICK_CONTROLS_STYLE='Basic', GG_DESKTOP_STATE_ROOT=str(directory / 'state'),
                       GG_DESKTOP_DATA_ROOT=str(directory / 'data'))
            if native:
                env.pop('QT_QUICK_BACKEND', None)
                env.update(QT_QPA_PLATFORM='windows', QSG_RHI_BACKEND='d3d11', GG_NETWORK_NATIVE='1')
            else:
                env.update(QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software')
                env.pop('GG_NETWORK_NATIVE', None)
            result = subprocess.run([sys.executable, '-X', 'utf8', '-B', str(Path(__file__).resolve()), '--fixture', temporary],
                                    cwd=PROJECT, env=env, capture_output=True, text=True, encoding='utf-8', timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            print(result.stdout.strip())

    def test_software_network_workspaces(self): self.run_fixture()

    @unittest.skipUnless(os.name == 'nt', 'Native Direct3D11 is a Windows check')
    def test_native_direct3d_network_workspaces(self): self.run_fixture(native=True)


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--fixture': fixture(Path(sys.argv[2]))
    else: unittest.main()
