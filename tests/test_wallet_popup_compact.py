"""Compact production WalletPopup: native geometry/actions with synthetic data only."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]


def fixture(directory: Path, mode: str):
    from copy import deepcopy
    from decimal import Decimal
    from PySide6.QtCore import QObject, QPointF, Qt, QUrl, Signal, Slot
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression, qmlContext
    from PySide6.QtQuick import QQuickItem
    from PySide6.QtTest import QSignalSpy, QTest
    from PySide6.QtWidgets import QApplication

    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    if os.name == 'nt':
        for face in ('consola.ttf', 'consolab.ttf', 'seguisym.ttf'):
            QFontDatabase.addApplicationFont(str(Path(os.environ['SystemRoot']) / 'Fonts' / face))
    QFont.insertSubstitution('monospace', 'Consolas' if os.name == 'nt' else 'DejaVu Sans Mono')
    app.setFont(QFont('Consolas' if os.name == 'nt' else 'DejaVu Sans Mono'))
    sol = 'solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp'
    eth = 'eip155:1'
    networks = [{'id': sol, 'name': 'Solana', 'family': 'solana', 'endpoint': 'https://rpc.example.invalid/solana'},
                {'id': eth, 'name': 'Ethereum', 'family': 'evm', 'endpoint': 'https://rpc.example.invalid/ethereum'}]
    accounts = [{'id': 'watch-sol-fixture', 'chain_id': sol, 'label': 'Bevakning Solana',
                 'address': 'SyntheticPublicSolanaWatchAddress000000000000'},
                {'id': 'watch-eth-fixture', 'chain_id': eth, 'label': 'Bevakning Ethereum',
                 'address': '0x' + '1' * 40}]
    assets = []
    rows = []
    for index, symbol in enumerate(('SOL', 'GGHB', 'TST2', 'TST3', 'TST4', 'TST5', 'TST6', 'TST7', 'TST8', 'TST9')):
        account = accounts[0 if index < 7 else 1]
        native = index == 0
        asset_id = account['chain_id'] + ('/native:SOL' if native else '/token:synthetic-' + str(index))
        quantity = '31529284.463525' if index == 1 else str(index + 1) + '.2500'
        value = None if index == 1 else format(Decimal(quantity) * Decimal(index + 2), '.2f')
        assets.append({'id': asset_id, 'chain_id': account['chain_id'], 'symbol': symbol,
                       'name': 'Native test SOL' if native else 'Synthetic ' + symbol,
                       'namespace': 'native' if native else 'token', 'reference': 'SOL' if native else 'synthetic-' + str(index)})
        rows.append({'id': 'fixture-position-' + str(index), 'account_id': account['id'],
                     'asset_id': asset_id, 'chain_id': account['chain_id'], 'symbol': symbol,
                     'name': assets[-1]['name'], 'network': 'Solana' if index < 7 else 'Ethereum',
                     'label': account['label'], 'address': account['address'], 'quantity': quantity,
                     'atomic': '31529284463525' if index == 1 else str((index + 1) * 1000000 + 250000),
                     'price_usd': None if index == 1 else index + 2, 'value_usd': value,
                     'price_state': 'MISSING' if index == 1 else 'CURRENT',
                     'balance_state': 'VERIFIED_READ', 'balance_current': True,
                     'scope': 'PUBLIC', 'signer_state': 'WATCH_ONLY',
                     'sparkline': {'prices': [] if index==1 else [index+2+(j%5)*.1-j*.012 for j in range(40)],'period':'7D','source':'Isolated synthetic history'}})
    known = format(sum((Decimal(row['value_usd']) for row in rows if row['value_usd'] is not None), Decimal(0)), '.2f')
    def summary(selected):
        return {'known_value_usd': format(sum((Decimal(row['value_usd']) for row in selected if row['value_usd'] is not None), Decimal(0)), '.2f'),
                'account_count': len({row['account_id'] for row in selected}),
                'network_count': len({row['chain_id'] for row in selected}),
                'unpriced_count': sum(row['value_usd'] is None for row in selected), 'last_read_at': 1700000000}
    state = {'assets': assets, 'networks': networks, 'accounts': accounts,
             'selected_asset': assets[0]['id'], 'ui_operation': {}, 'wallet_transfers': [],
             'wallet_overview': {'accounts': accounts, 'networks': networks, 'rows': rows, 'lab_rows': [], 'local_wallets': [],
                 'summary': summary(rows),
                 'account_summaries': {a['id']: summary([r for r in rows if r['account_id'] == a['id']]) for a in accounts},
                 'network_summaries': {n['id']: summary([r for r in rows if r['chain_id'] == n['id']]) for n in networks},
                 'events': [{'ts': 1700000000, 'kind': 'BALANCE_READ', 'message': 'Isolerad syntetisk saldoavläsning.'}]}}

    class Host(QObject):
        omniStatusUpdated = Signal(str)
        cryptoStatusUpdated = Signal(str)
        def __init__(self):
            super().__init__()
            self.payload = deepcopy(state)
            self.calls = []
        @Slot(result=str)
        def cryptoStatus(self): return '{}'
        @Slot(result=str)
        def omniStatus(self): return json.dumps(self.payload)
        @Slot(result=str)
        def explorerStatus(self): return json.dumps({'rows': [], 'networks': [], 'settings': {'paused': True}, 'needs_refresh': False})
        @Slot(str, str, result=str)
        def omniAction(self, name, raw):
            args = json.loads(raw)
            self.calls.append((name, args))
            if name == 'select_asset': self.payload['selected_asset'] = args['id']
            self.payload['ui_operation'] = {'name': name, 'state': 'done'}
            return json.dumps(self.payload)
        @Slot(str, result=str)
        def tmogCopy(self, value): return value
        def push(self, payload):
            self.payload = deepcopy(payload)
            self.omniStatusUpdated.emit(json.dumps(self.payload))

    host = Host()
    engine = QQmlApplicationEngine()
    warnings = []
    engine.warnings.connect(lambda errors: warnings.extend(error.toString() for error in errors))
    engine.rootContext().setContextProperty('fixtureHost', host)
    engine.rootContext().setContextProperty('nativeWalletProbe', os.environ.get('GG_WALLET_NATIVE')=='1')
    path = directory / 'fixture.qml'
    path.write_text('''import QtQuick
import QtQuick.Controls
import COMPONENTS
ApplicationWindow {width:560;height:760;visible:true;color:'#111111'
x:nativeWalletProbe?-10000:0;y:nativeWalletProbe?-10000:0
flags:nativeWalletProbe?(Qt.Tool|Qt.FramelessWindowHint|Qt.WindowDoesNotAcceptFocus):Qt.Window
WalletPopup {objectName:'compactPopupTest';x:20;y:30;visualWidth:328;visualHeight:600;surfaceHost:fixtureHost}
}'''.replace('COMPONENTS', json.dumps((PROJECT / 'qml/components').as_uri())), encoding='utf-8')
    engine.load(QUrl.fromLocalFile(str(path)))
    assert engine.rootObjects(), warnings
    window = engine.rootObjects()[0]
    popup = window.findChild(QQuickItem, 'compactPopupTest')

    def items(owner):
        yield owner
        for child in owner.childItems(): yield from items(child)
    def js(owner, source):
        expression = QQmlExpression(qmlContext(owner), owner, source)
        value = expression.evaluate()
        assert not expression.hasError(), expression.error().toString()
        return value[0] if isinstance(value, tuple) else value
    def find(name, owner=None):
        item = (owner or popup).findChild(QQuickItem, name)
        assert item is not None, name + ' missing'
        return item
    def click(item):
        # The native probe window is outside the desktop. Explicit grabs polish
        # its layout even when the OS does not expose it for normal frames.
        window.grabWindow()
        assert item.isVisible() and item.property('enabled'), (item.objectName(), 'not interactive')
        point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
        QTest.qWait(35)
        window.grabWindow()
    def capture(name):
        destination = os.environ.get('GG_WALLET_POPUP_EVIDENCE')
        if destination:
            out = Path(destination); out.mkdir(parents=True, exist_ok=True)
            window.grabWindow().save(str(out / name))
    QTest.qWait(150)
    overview = next((item for item in items(popup) if item.property('compactPopup') is True), None)
    assert overview is not None, 'Popup must opt into compact mode without changing desktop dashboard defaults'
    assert not overview.property('dashboard')
    listing = find('walletPositionList', overview)
    body = find('walletBodyScroll')

    if mode == 'geometry':
        records = []
        for width, height in ((328, 520), (328, 600), (360, 520), (360, 600), (430, 520), (430, 600)):
            popup.setProperty('visualWidth', width); popup.setProperty('visualHeight', height)
            QTest.qWait(70); window.grabWindow()
            js(listing, 'positionViewAtBeginning(); forceLayout()'); QTest.qWait(20); window.grabWindow()
            rendered = [item for item in items(listing) if item.objectName() == 'walletAssetRow']
            first = min(rendered, key=lambda item: item.property('index'))
            first_y = first.mapToItem(popup, QPointF(0, 0)).y()
            assert first_y <= 220, (width, height, 'holdings too low', first_y)
            assert 48 <= first.height() <= 56, (width, height, 'oversized holdings', first.height())
            assert listing.height() >= 200, (width, height, 'list viewport', listing.height())
            for name in ('walletAccountFilter', 'walletReceive', 'walletRefreshOverview', 'walletAssetSearch', 'walletTools'):
                control = find(name, overview)
                assert 24 <= control.height() <= 28, (name, control.height())
                point = control.mapToItem(popup, QPointF(0, 0))
                assert point.x() >= 0 and point.x()+control.width() <= popup.width()+.1, (name, width, 'overflow')
            assert body.property('contentHeight') <= body.height()+.1, (width, height, 'nested outer scroll')
            footer = find('walletCompactFooter', overview)
            footer_y = footer.mapToItem(popup, QPointF(0, 0)).y()
            assert footer.isVisible() and footer_y+footer.height() <= popup.height()+.1
            capture('wallet-popup-'+str(width)+'x'+str(height)+'.png')
            js(listing, 'positionViewAtEnd(); forceLayout()'); QTest.qWait(30)
            assert listing.property('contentY') > 0
            assert footer.mapToItem(popup, QPointF(0, 0)).y() == footer_y, 'Footer moved with assets'
            long_row = next(item for item in items(listing) if item.objectName() == 'walletAssetRow'
                            and item.property('assetTarget') == assets[1]['id'])
            quantity = next((item for item in items(long_row) if item.isVisible() and item.property('text') == '31 529 284.463525'), None)
            assert quantity is not None and not quantity.property('truncated'), (width, 'exact quantity truncated')
            for row in (i for i in items(listing) if i.objectName()=='walletAssetRow'):
                spark=row.findChild(QQuickItem,'walletTokenSparkline')
                assert spark is not None
                missing=row.property('assetTarget')==assets[1]['id']
                assert spark.isVisible() is not missing, ('chart availability',width,row.property('assetTarget'))
                if not missing:
                    assert spark.width()>=28 and spark.x()+spark.width()<=row.width()-8
            capture('wallet-popup-'+str(width)+'x'+str(height)+'-scrolled.png')
            records.append({'popup': [width, height], 'first_row_y': first_y, 'row_height': first.height(), 'list_height': listing.height()})
        # Historical samples can exist even when the current quote is missing.
        # The chart must then shrink around the full, exact long quantity.
        popup.setProperty('visualWidth',328); QTest.qWait(40); window.grabWindow()
        with_history=deepcopy(state)
        with_history['wallet_overview']['rows'][1]['sparkline']={'prices':[1+j*.02 for j in range(20)],'period':'7D','source':'Synthetic long quantity test'}
        host.push(with_history); QTest.qWait(30); window.grabWindow()
        js(listing,'positionViewAtEnd(); forceLayout()'); QTest.qWait(20); window.grabWindow()
        row=next(i for i in items(listing) if i.objectName()=='walletAssetRow' and i.property('assetTarget')==assets[1]['id'])
        spark=row.findChild(QQuickItem,'walletTokenSparkline');quantity=row.findChild(QQuickItem,'walletCompactQuantity')
        assert spark.isVisible() and spark.width()>=28 and not quantity.property('truncated')
        quantity_left=quantity.mapToItem(row,QPointF(0,0)).x()+quantity.width()-quantity.property('implicitWidth')
        assert spark.x()+spark.width()<=quantity_left-4, 'Sparkline overlaps exact quantity'
        capture('wallet-popup-long-history.png')
        print(json.dumps({'status': 'PASS', 'synthetic_only': True, 'geometry': records, 'exact_quantity': True}))
    elif mode == 'detail':
        # Reproduce the user's long GGHB balance in the production action view.
        # Public synthetic watch-only identities; no network or signing.
        records=[]
        for width,height in ((328,520),(360,600),(430,600)):
            popup.setProperty('visualWidth',width);popup.setProperty('visualHeight',height)
            js(overview,'openActions("receive",wallet.rows.filter(function(r){return r.symbol==="GGHB"})[0])')
            QTest.qWait(60);window.grabWindow()
            actions=find('walletActions',overview);scroll=find('walletActionScroll',actions)
            quantity=find('walletReceiveExactQuantity',actions);balance_box=find('walletReceiveBalanceBox',actions)
            refresh=find('walletReadReceive',actions)
            capture('wallet-detail-'+str(width)+'x'+str(height)+'.png')
            assert quantity.property('text')=='31 529 284.463525'
            assert not quantity.property('truncated') and quantity.height()<=30
            assert js(quantity,'wrapMode===0'), 'Exact quantity must remain on one line'
            quantity_bottom=quantity.mapToItem(actions,QPointF(0,quantity.height())).y()
            refresh_top=refresh.mapToItem(actions,QPointF(0,0)).y()
            assert quantity_bottom<refresh_top, 'Refresh control overlaps long balance'
            assert balance_box.height()<=82 and refresh.height()==28
            assert scroll.property('contentHeight')<=scroll.height()+.1,(width,height,scroll.property('contentHeight'),scroll.height())
            assert refresh_top+refresh.height()<=scroll.height(), 'Essential refresh below viewport'
            click(refresh)
            assert host.calls[-1]==('refresh_balance',{'account_id':accounts[0]['id'],'asset_id':assets[1]['id']})
            records.append({'size':[width,height],'content_height':scroll.property('contentHeight'),'viewport':scroll.height(),'quantity_bottom':quantity_bottom,'refresh_top':refresh_top})
        quoted=deepcopy(state)
        quoted['wallet_overview']['rows'][1].update(price_usd='0.00000307286146988998',value_usd='96.88',price_source='Synthetic public reserve fixture',price_quality='BONDING_CURVE_SPOT')
        host.push(quoted);QTest.qWait(40)
        assert find('walletReceiveValuation',actions).property('text')=='$96.88'
        assert 'Synthetic public reserve fixture' in find('walletReceivePriceSource',actions).property('text')
        click(find('walletModeSend',actions))
        amount_label=find('walletSendExactQuantity',actions)
        assert amount_label.property('text')=='31 529 284.463525 GGHB' and not amount_label.property('truncated')
        assert not actions.property('canPrepare')
        assert not any(name in ('prepare_transfer','send_transfer') for name,args in host.calls)
        print(json.dumps({'status':'PASS','synthetic_only':True,'long_balance_detail':records,'exact_quantity':True,'quote_provenance':True,'no_send':True}))
    else:
        # Query and selectors operate on the same account/network model as CRYPTO.
        search = find('walletAssetSearch', overview)
        search.setProperty('text', 'Synthetic GGHB'); QTest.qWait(30)
        assert listing.property('count') == 1 and js(overview, 'rows[0].symbol') == 'GGHB'
        search.setProperty('text', ''); QTest.qWait(20)
        account = find('walletAccountFilter', overview)
        account.forceActiveFocus(); QTest.keyClick(window, Qt.Key_Down); QTest.qWait(25)
        assert overview.property('accountFilter') == accounts[0]['id'], 'Account selector did not activate'
        assert js(overview, 'rows.every(function(r){return r.account_id===accountFilter})')
        network = find('walletNetworkFilter', overview)
        network.forceActiveFocus(); QTest.keyClick(window, Qt.Key_Down); QTest.qWait(25)
        assert overview.property('chain') == sol, 'Network selector did not activate'
        assert js(overview, 'rows.every(function(r){return r.chain_id===chain})')
        overview.setProperty('accountFilter', ''); overview.setProperty('chain', '')
        click(find('walletRefreshOverview', overview))
        assert host.calls[-1] == ('refresh_wallet', {'account_ids': [a['id'] for a in accounts]})
        click(find('walletReceive', overview))
        actions = find('walletActions', overview)
        assert actions.isVisible() and actions.property('page') == 'receive'
        js(actions, 'closeRequested()'); QTest.qWait(20)
        click(find('walletSend', overview))
        assert actions.isVisible() and actions.property('page')=='send' and not actions.property('canPrepare')
        js(actions, 'closeRequested()'); QTest.qWait(20)
        search.setProperty('text', 'Native test SOL'); QTest.qWait(20); js(listing, 'forceLayout()')
        token_row = next(item for item in items(listing) if item.objectName() == 'walletAssetRow' and item.isVisible())
        click(token_row)
        assert actions.isVisible() and actions.property('accountId') == accounts[0]['id'] and actions.property('assetId') == assets[0]['id']
        click(find('walletModeSend', actions))
        find('walletSendRecipient', actions).setProperty('text', 'SyntheticDestinationAddress0000000000000000')
        find('walletSendAmount', actions).setProperty('text', '1')
        assert not actions.property('canPrepare') and not find('walletPrepareTransfer', actions).property('enabled')
        assert all(name not in ('prepare_transfer', 'send_transfer') for name, _ in host.calls)
        js(actions, 'closeRequested()'); search.setProperty('text', ''); QTest.qWait(25)
        click(find('walletActivityTab', overview))
        assert overview.property('showActivity') and find('walletActivityFeed', overview).isVisible()
        click(find('walletAssetsTab', overview))
        assert not overview.property('showActivity') and listing.isVisible()
        click(find('walletTools', overview))
        menu = popup.findChild(QObject, 'walletToolsMenu')
        assert menu is not None and menu.property('visible')
        entry=next(i for i in items(menu.property('contentItem')) if i.property('text')=='Konton / token')
        click(entry)
        assert popup.property('omniOpen') and find('walletPopupBack').isVisible()
        click(find('walletPopupBack'))
        assert not popup.property('omniOpen') and listing.isVisible()
        assert body.property('contentHeight')<=body.height()+.1
        click(find('walletAddAccount', overview))
        menu = popup.findChild(QObject, 'walletAccountMenu')
        assert menu is not None and menu.property('visible')
        QTest.keyClick(window, Qt.Key_Escape); QTest.qWait(20)
        expanded = QSignalSpy(popup.openDesk)
        click(find('walletOverviewExpand', overview))
        assert expanded.count() == 1
        # Missing values, failed reads and pending approvals are never presented as success.
        failed = deepcopy(state)
        failed['wallet_overview']['rows'][0].update(balance_state='READ_FAILED', balance_current=False)
        failed['ui_operation'] = {'name': 'refresh_wallet', 'state': 'done', 'error': 'OMNI_WALLET_REFRESH_PARTIAL'}
        host.push(failed); QTest.qWait(30)
        assert find('walletOperationError', overview).isVisible()
        assert 'misslyckades' in js(overview, 'balanceLabel(wallet.rows[0])').lower()
        capture('wallet-popup-read-error.png')
        failed['ui_operation'] = {'name': 'send_transfer', 'state': 'approval_required'}
        host.push(failed); QTest.qWait(25)
        assert overview.property('approvalPending') and not find('walletRefreshOverview', overview).property('enabled')
        empty = deepcopy(state)
        empty['assets'] = []; empty['accounts'] = []
        empty['wallet_overview'].update(accounts=[], rows=[], local_wallets=[], summary={'known_value_usd': None, 'account_count': 0, 'network_count': 0, 'unpriced_count': 0})
        host.push(empty); QTest.qWait(30)
        assert overview.property('noAccounts') and find('walletTotalValue', overview).property('text') == '—'
        capture('wallet-popup-empty.png')
        frame=window.grabWindow();ratio=frame.width()/window.width()
        # Leaving the action view must remove its retained glyph nodes too.
        assert all(frame.pixelColor(int(x*ratio),int(y*ratio)).name()=='#111111'
                   for x in range(25,95) for y in range(640,710)), 'Hidden action glyph leaked outside popup'
        print(json.dumps({'status': 'PASS', 'synthetic_only': True, 'filter_selectors': True, 'receive_and_token_context': True,
                          'watch_account_cannot_prepare': True, 'menus_activity_expand': True, 'honest_empty_error_approval': True}))
    assert not warnings, warnings
    if os.environ.get('GG_WALLET_NATIVE')=='1':
        from PySide6.QtQuick import QSGRendererInterface
        assert window.rendererInterface().graphicsApi()==QSGRendererInterface.GraphicsApi.Direct3D11
    window.close(); engine.deleteLater(); app.processEvents()


class WalletPopupCompact(unittest.TestCase):
    def run_fixture(self, mode, native=False):
        with tempfile.TemporaryDirectory(prefix='gg-wallet-popup-') as temporary:
            env = os.environ.copy()
            env.update(QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software', QT_QUICK_CONTROLS_STYLE='Basic',
                       GG_DESKTOP_STATE_ROOT=str(Path(temporary)/'state'), GG_DESKTOP_DATA_ROOT=str(Path(temporary)/'data'))
            if native:
                env.pop('QT_QUICK_BACKEND',None)
                env.update(QT_QPA_PLATFORM='windows',QSG_RHI_BACKEND='d3d11',GG_WALLET_NATIVE='1')
                if env.get('GG_WALLET_POPUP_EVIDENCE'):
                    env['GG_WALLET_POPUP_EVIDENCE']=str(Path(env['GG_WALLET_POPUP_EVIDENCE'])/'direct3d')
            run = subprocess.run([sys.executable, '-X', 'utf8', '-B', str(Path(__file__).resolve()), '--fixture', temporary, mode],
                                 cwd=PROJECT, env=env, capture_output=True, text=True, encoding='utf-8', timeout=35)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            print(run.stdout.strip())

    def test_popup_proportions_exact_quantities_and_single_scrolling_viewport(self): self.run_fixture('geometry')
    def test_popup_filters_navigation_and_watch_only_action_guards(self): self.run_fixture('actions')
    def test_long_token_detail_fits_without_overlap_and_reads_exact_selected_asset(self):self.run_fixture('detail')
    @unittest.skipUnless(os.name=='nt','Windows Direct3D11 renderer')
    def test_native_direct3d_geometry_actions_and_clipping(self):
        self.run_fixture('geometry',native=True)
        self.run_fixture('actions',native=True)
        self.run_fixture('detail',native=True)


if __name__ == '__main__':
    if len(sys.argv) == 4 and sys.argv[1] == '--fixture': fixture(Path(sys.argv[2]), sys.argv[3])
    else: unittest.main()
