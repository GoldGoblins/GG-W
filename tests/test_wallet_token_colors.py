"""Canonical cosmetic preferences and real compact-wallet color/allocation UI."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0,str(PROJECT))
from backend import omni_assets as assets, wallet_token_colors as colors
PALETTE = json.loads((PROJECT/'config/gg-palette.json').read_text(encoding='utf-8'))['colors']


class TokenColorPreferences(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='gg-color-preferences-')
        self.root = Path(self.temporary.name)
        self.patched = patch.object(assets, 'ROOT', self.root/'omni')
        self.patched.start()
        assets.bootstrap()
        self.a = assets.register_asset('eip155:1', 'erc20', '0x'+'1'*40, 'SAME', 'First', 18)
        self.b = assets.register_asset('eip155:56', 'erc20', '0x'+'1'*40, 'SAME', 'Second', 18)

    def tearDown(self):
        self.patched.stop()
        self.temporary.cleanup()

    def test_same_ticker_and_address_different_networks_persist_independently(self):
        colors.set_color(self.a['id'], PALETTE[2].upper())
        saved = colors.set_color(self.b['id'], PALETTE[3])
        self.assertEqual(saved['colors'], {self.a['id']: PALETTE[2], self.b['id']: PALETTE[3]})
        # Metadata re-registration uses INSERT OR REPLACE in the registry. It
        # must not cascade away this unrelated cosmetic preference.
        assets.register_asset('eip155:1', 'erc20', '0x'+'1'*40, 'SAME', 'Updated name', 18)
        self.assertEqual(colors.snapshot(),saved)
        environment = os.environ.copy()
        environment['GG_DESKTOP_STATE_ROOT'] = str(self.root)
        result = subprocess.run([sys.executable, '-X', 'utf8', '-B', '-c',
            'import json;from backend.wallet_token_colors import snapshot;print(json.dumps(snapshot()))'],
            cwd=PROJECT, env=environment, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), saved)

    def test_invalid_color_ticker_position_or_unknown_asset_cannot_change_preferences(self):
        expected = colors.set_color(self.a['id'], PALETTE[0])
        for identity, value in ((self.a['id'], '#123456'), (self.a['id'], 'red'),
                                (self.a['id'], PALETTE[0]+'\n'), ('SAME', PALETTE[1]),
                                (self.a['id']+'@account', PALETTE[1]),
                                ('eip155:999/erc20:0x'+'1'*40, PALETTE[1])):
            with self.subTest(identity=identity, value=value), self.assertRaises(ValueError):
                colors.set_color(identity, value)
            self.assertEqual(colors.snapshot(), expected)

    def test_prior64_hex_selection_survives_expanded_saturated_palette(self):
        legacy=json.loads((PROJECT/'config/gg-palette.json').read_text(encoding='utf-8'))['legacy_colors']
        # An existing stored color remains visible after canonical swatches
        # change. Preference identity is the asset and hex, never an index.
        previous=next(value for value in legacy if value not in PALETTE)
        with assets.db(True) as connection:
            colors._table(connection)
            connection.execute('INSERT INTO wallet_token_colors(asset_id,color) VALUES(?,?)',
                               (self.a['id'],previous))
        self.assertEqual(colors.snapshot()['colors'],{self.a['id']:previous})
        self.assertEqual(colors.set_color(self.a['id'],previous.upper())['colors'],{self.a['id']:previous})
        self.assertEqual(colors.set_color(self.a['id'],'#ff0000')['colors'],{self.a['id']:'#ff0000'})

    def test_bounded_preferences_allow_update_at_capacity_and_rollback_new_entry(self):
        with patch.object(colors, 'MAX_COLORS', 1):
            colors.set_color(self.a['id'], PALETTE[0])
            with self.assertRaisesRegex(ValueError, 'LIMIT'):
                colors.set_color(self.b['id'], PALETTE[1])
            expected = colors.set_color(self.a['id'], PALETTE[2])
            self.assertEqual(expected['colors'], {self.a['id']: PALETTE[2]})


def ui_fixture(directory):
    from PySide6.QtCore import QObject, QPointF, Qt, QUrl, Signal, Slot
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression, qmlContext
    from PySide6.QtQuick import QQuickItem
    from PySide6.QtTest import QTest, QSignalSpy
    from PySide6.QtWidgets import QApplication

    app = QApplication([])
    if os.name == 'nt':
        for face in ('consola.ttf', 'consolab.ttf', 'seguisym.ttf'):
            QFontDatabase.addApplicationFont(str(Path(os.environ['SystemRoot'])/'Fonts'/face))
    QFont.insertSubstitution('monospace', 'Consolas' if os.name=='nt' else 'DejaVu Sans Mono')
    assets.bootstrap()
    first = assets.register_asset('eip155:1', 'erc20', '0x'+'1'*40, 'SAME', 'Same ETH', 18)
    second = assets.register_asset('eip155:56', 'erc20', '0x'+'1'*40, 'SAME', 'Same BNB', 18)
    unpriced = assets.register_asset(assets.NATIVE_SOL.split('/')[0], 'token', '11111111111111111111111111111111', 'GGHB', 'GGHB fixture', 6)
    registry = assets.snapshot()
    wanted = [next(row for row in registry['assets'] if row['id']==assets.NATIVE_SOL), first, second, unpriced]
    accounts = [{'id':'a-'+str(i), 'chain_id':chain, 'address':'PublicFixtureAddress'+str(i), 'label':'Fixture '+str(i)}
                for i, chain in enumerate(dict.fromkeys(row['chain_id'] for row in wanted))]
    networks = [row for row in registry['networks'] if row['id'] in {a['chain_id'] for a in accounts}]
    rows = []
    for index, asset in enumerate(wanted):
        account = next(a for a in accounts if a['chain_id']==asset['chain_id'])
        network = next(n for n in networks if n['id']==asset['chain_id'])
        quantity = '31529284.463525' if index==3 else '1.234567890123456789'
        rows.append(dict(id=asset['id']+'@'+account['id'], asset_id=asset['id'], account_id=account['id'],
            chain_id=asset['chain_id'], network=network['name'], symbol=asset['symbol'], name=asset['name'],
            label=account['label'], address=account['address'], quantity=quantity, atomic='1',
            value_usd=['75.00','25.00','0.00',None][index], balance_state='VERIFIED_READ',
            balance_current=True, price_state='CURRENT', scope='PUBLIC_WATCH', signer_state='WATCH_ONLY'))
    summary = {'known_value_usd':'100.00','account_count':3,'network_count':3,'unpriced_count':1}
    payload = {'assets':wanted,'networks':networks,'accounts':accounts,'selected_asset':wanted[0]['id'],
        'wallet_overview':{'rows':rows,'accounts':accounts,'networks':networks,'summary':summary,
            'network_summaries':{'eip155:1':{'known_value_usd':'25.00','unpriced_count':0}},'lab_rows':[]}}
    colors.set_color(assets.NATIVE_SOL, PALETTE[0])
    colors.set_color(first['id'], PALETTE[2])
    colors.set_color(second['id'], PALETTE[3])

    class Host(QObject):
        omniStatusUpdated = Signal(str)
        cryptoStatusUpdated = Signal(str)
        walletTokenColorsUpdated = Signal(str)
        def __init__(self): super().__init__();self.actions=[];self.fail_next=False;self.saves=[]
        @Slot(result=str)
        def omniStatus(self): return json.dumps(payload)
        @Slot(result=str)
        def cryptoStatus(self): return '{}'
        @Slot(result=str)
        def explorerStatus(self): return '{"rows":[],"networks":[],"settings":{"paused":true},"needs_refresh":false}'
        @Slot(str, str, result=str)
        def omniAction(self, name, raw): self.actions.append(name);return json.dumps(payload)
        @Slot(result=str)
        def walletTokenColors(self): return json.dumps(colors.snapshot())
        @Slot(str, str, result=str)
        def walletSetTokenColor(self, identity, value):
            self.saves.append((identity,value))
            if self.fail_next: self.fail_next=False;return '{"error":"WALLET_TOKEN_COLOR_SAVE_FAILED"}'
            raw=json.dumps(colors.set_color(identity,value));self.walletTokenColorsUpdated.emit(raw);return raw

    from backend.ui_color_customization import UiColorController
    ui_colors=UiColorController(path=directory/'ui-colours.json')
    host=Host();engine=QQmlApplicationEngine();warnings=[]
    engine.warnings.connect(lambda values:warnings.extend(v.toString() for v in values))
    engine.rootContext().setContextProperty('fixtureHost', host)
    engine.rootContext().setContextProperty('fixtureUiColors', ui_colors)
    qml = directory/'wallet-colors.qml'
    qml.write_text('import QtQuick\nimport '+json.dumps((PROJECT/'qml/components').as_uri())+'\n'
        'Window {width:400;height:660;visible:false;color:"#111111";Component.onCompleted:{GGColorContext.backend=fixtureUiColors;GGColorContext.hostOverlay=contentItem}'
        'WalletPopup {objectName:"popup";x:18;y:20;visualWidth:360;visualHeight:600;surfaceHost:fixtureHost}'
        'OmniWalletPanel {objectName:"peer";visible:false;width:328;height:500;surfaceHost:fixtureHost}}',encoding='utf-8')
    engine.load(QUrl.fromLocalFile(str(qml)));assert engine.rootObjects(),warnings
    window=engine.rootObjects()[0]
    native=os.environ.get('GG_WALLET_COLOR_NATIVE')=='1'
    if native:
        screen=app.primaryScreen().availableGeometry()
        window.setFlags(window.flags()|Qt.WindowDoesNotAcceptFocus|Qt.WindowStaysOnBottomHint)
        window.setX(screen.right()-24);window.setY(screen.bottom()-24)
    window.show()
    def descendants(owner):
        from shiboken6 import isValid
        result=[];pending=list(owner.childItems())
        while pending:
            item=pending.pop()
            if not isinstance(item,QQuickItem) or not isValid(item):continue
            result.append(item);pending.extend(item.childItems())
        return result
    popup=window.findChild(QQuickItem,'popup')
    peer=window.findChild(QQuickItem,'peer')
    QTest.qWait(100);window.grabWindow()
    overview=next(item for item in descendants(popup) if item.property('compactPopup') is True)
    def js(owner, text):
        expression=QQmlExpression(qmlContext(owner),owner,text);value=expression.evaluate()
        assert not expression.hasError(),expression.error().toString()
        return value[0] if isinstance(value,tuple) else value
    def find(name, owner=overview):
        item=owner.findChild(QQuickItem,name);assert item is not None,name
        return item
    def click(item):
        assert item.isVisible() and item.isEnabled(),item.objectName()
        point=item.mapToScene(QPointF(item.width()/2,item.height()/2)).toPoint()
        QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,point);QTest.qWait(25);window.grabWindow()
    def row(identity): return next(item for item in descendants(overview) if item.objectName()=='walletAssetRow' and item.property('assetTarget')==identity)
    model=json.loads(js(overview,'JSON.stringify(allocation)'))
    assert sorted(round(r['fraction'],5) for r in model['segments'])==[.25,.75],model
    assert model['unpricedCount']==1 and 'ej prissatta' in model['description']
    assert find('walletTotalValue').property('text')=='$100.00'
    total=find('walletTotalValue');assert abs(total.mapToItem(popup,QPointF(total.width()/2,0)).x()-popup.width()/2)<1
    before=colors.snapshot()
    target_row=row(assets.NATIVE_SOL)
    dot=find('walletTokenColorDot',target_row);click(dot)
    picker=overview.findChild(QObject,'walletTokenColorPicker');assert picker.property('opened')
    assert not host.actions,'Color dot must not open transfer/select an asset'
    content=picker.property('contentItem')
    swatches=[item for item in descendants(content) if item.objectName()=='uiColorSwatch']
    assert len(swatches)==64
    # Cancellation must not save a value.
    QTest.keyClick(window,Qt.Key_Escape);QTest.qWait(20)
    assert colors.snapshot()==before and not host.saves
    click(dot);content=picker.property('contentItem')
    swatches=[item for item in descendants(content) if item.objectName()=='uiColorSwatch']
    assert len(swatches)==64
    assert picker.property('targetKey')=='ui.asset.'+assets.NATIVE_SOL
    next(item for item in swatches if item.property('index')==63).forceActiveFocus()
    QTest.keyClick(window,Qt.Key_Return);QTest.qWait(30)
    assert colors.snapshot()['colors'][assets.NATIVE_SOL]==PALETTE[63]
    assert colors.snapshot()['colors'][first['id']]==PALETTE[2]
    assert colors.snapshot()['colors'][second['id']]==PALETTE[3]
    assert js(peer,'tokenColors['+json.dumps(assets.NATIVE_SOL)+']')==PALETTE[63]
    assert js(overview,'tokenColor(wallet.rows[0])')==PALETTE[63]
    assert PALETTE[63] in [v['color'] for v in json.loads(js(overview,'JSON.stringify(allocation.segments)'))]
    # The shared UI preference key and the legacy asset registry are distinct
    # layers; a pre-existing per-asset choice remains a valid fallback.
    assert ui_colors.setColor('ui.asset.'+first['id'],PALETTE[5])
    QTest.qWait(20)
    assert js(overview,'tokenColor(wallet.rows[1])')==PALETTE[5]
    assert js(overview,'tokenColor(wallet.rows[2])')==PALETTE[3]
    assert colors.snapshot()['colors'][first['id']]==PALETTE[2]
    assert PALETTE[5] in [v['color'] for v in json.loads(js(overview,'JSON.stringify(allocation.segments)'))]
    assert ui_colors.reset('ui.asset.'+first['id'])
    QTest.qWait(20)
    assert js(overview,'tokenColor(wallet.rows[1])')==PALETTE[2]
    # Right-click is the same advanced menu as a left click. Reset updates
    # both preference layers, otherwise its legacy fallback would look stuck.
    point=dot.mapToScene(QPointF(dot.width()/2,dot.height()/2)).toPoint()
    QTest.mouseClick(window,Qt.RightButton,Qt.NoModifier,point);QTest.qWait(20)
    assert picker.property('opened')
    assert picker.property('targetKey')=='ui.asset.'+assets.NATIVE_SOL
    assert any(item.objectName()=='uiColorDeadlineOption' for item in descendants(picker.property('contentItem')))
    js(picker,'resetTarget()');QTest.qWait(20)
    native_default=js(overview,'RuntimeTheme.GGTheme.defaultColor('+json.dumps(assets.NATIVE_SOL)+')')
    assert colors.snapshot()['colors'][assets.NATIVE_SOL]==native_default
    assert js(overview,'tokenColor(wallet.rows[0])')==native_default
    allocation_before_search=json.loads(js(overview,'JSON.stringify(allocation.segments)'))
    overview.setProperty('query','GGHB');QTest.qWait(20)
    assert find('walletPositionList').property('count')==1
    assert json.loads(js(overview,'JSON.stringify(allocation.segments)'))==allocation_before_search,'Search is not portfolio scope'
    overview.setProperty('query','');overview.setProperty('chain','eip155:1');QTest.qWait(20)
    assert json.loads(js(overview,'JSON.stringify(allocation.segments)'))[0]['fraction']==1
    overview.setProperty('chain','');QTest.qWait(20)
    old=colors.snapshot();host.fail_next=True
    js(overview,'saveTokenColor('+json.dumps(assets.NATIVE_SOL)+','+json.dumps(PALETTE[1])+')')
    assert colors.snapshot()==old and find('walletOperationError').isVisible()
    overview.setProperty('tokenColorError','')
    destination=os.environ.get('GG_WALLET_COLOR_EVIDENCE')
    if destination:
        out=Path(destination);out.mkdir(parents=True,exist_ok=True)
        window.grabWindow().save(str(out/'wallet-allocation.png'))
        target_row=row(assets.NATIVE_SOL)
        dot=find('walletTokenColorDot',target_row)
        click(dot)
        window.grabWindow().save(str(out/'wallet-palette-64.png'))
        QTest.keyClick(window,Qt.Key_Escape);QTest.qWait(20)
    # Leave the row/picker hover and allow native tooltip close transitions and
    # queued compositor frames to finish before measuring static allocation.
    QTest.mouseMove(window,QPointF(200,530).toPoint())
    QTest.qWait(350);spy=QSignalSpy(window.frameSwapped);QTest.qWait(160)
    assert spy.count()==0,'Static allocation must not redraw on an idle timer'
    assert not warnings,warnings
    if native:
        from PySide6.QtQuick import QSGRendererInterface
        assert window.rendererInterface().graphicsApi()==QSGRendererInterface.GraphicsApi.Direct3D11
    js(window,'GGColorContext.backend=null;GGColorContext.hostOverlay=null')
    window.close();engine.deleteLater();app.processEvents()
    print(json.dumps({'status':'PASS','real_qml':True,'native':native,'canonical_identity':True,'persisted':True,
        'palette_sizes':[64],'shared_advanced_menu':True,'right_click_same_asset_key':True,'legacy_fallback_preserved':True,'meaningful_reset':True,'keyboard_choice':True,'cancel_unchanged':True,'known_value_allocation':True,'idle_swaps':spy.count(),'warnings':len(warnings)}))


class WalletTokenColorsUI(unittest.TestCase):
    def run_fixture(self,native=False):
        with tempfile.TemporaryDirectory(prefix='gg-wallet-color-ui-') as temporary:
            environment=os.environ.copy();environment.update(QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software',
                QT_QUICK_CONTROLS_STYLE='Basic',GG_DESKTOP_STATE_ROOT=str(Path(temporary)/'state'),GG_DESKTOP_DATA_ROOT=str(Path(temporary)/'data'))
            if native:
                environment.pop('QT_QUICK_BACKEND',None)
                environment.update(QT_QPA_PLATFORM='windows',QSG_RHI_BACKEND='d3d11',GG_WALLET_COLOR_NATIVE='1')
                if environment.get('GG_WALLET_COLOR_EVIDENCE'):
                    environment['GG_WALLET_COLOR_EVIDENCE']=str(Path(environment['GG_WALLET_COLOR_EVIDENCE'])/'native')
            result=subprocess.run([sys.executable,'-X','utf8','-B',str(Path(__file__).resolve()),'--fixture',temporary],
                cwd=PROJECT,env=environment,capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            print(result.stdout.strip())

    def test_real_dot_picker_keyboard_persistence_allocation_and_idle_rendering(self):self.run_fixture()

    @unittest.skipUnless(os.name=='nt','Windows native Direct3D11')
    def test_native_color_picker_and_shape_rendering(self):self.run_fixture(native=True)


if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--fixture':ui_fixture(Path(sys.argv[2]))
    else:unittest.main()
