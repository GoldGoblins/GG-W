"""Purpose is independent of key custody; own moves reuse reviewed transfers."""
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

PROJECT=Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:sys.path.insert(0,str(PROJECT))
from backend import omni_assets as assets, wallet_account_roles as roles


class AccountRoleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='gg-wallet-roles-')
        self.directory=patch.object(assets,'ROOT',Path(self.temp.name)/'omni');self.directory.start()
        assets.bootstrap()
        self.a=assets.account('eip155:1','0x'+'1'*40,'Trading fixture')
        self.b=assets.account('eip155:56','0x'+'1'*40,'Storage fixture')

    def tearDown(self):self.directory.stop();self.temp.cleanup()

    def test_roles_persist_by_account_and_metadata_update_preserves_purpose(self):
        roles.set_role(self.a,'TRADING');saved=roles.set_role(self.b,'STORAGE')
        self.assertEqual(saved['roles'],{self.a:'TRADING',self.b:'STORAGE'})
        self.assertEqual(next(a for a in saved['accounts'] if a['account_id']==self.b)['storage_state'],'EXTERNAL_KEY_NOT_VERIFIED')
        assets.account('eip155:56','0x'+'1'*40,'Updated name')
        self.assertEqual(roles.snapshot(),saved)
        environment=os.environ.copy();environment['GG_DESKTOP_STATE_ROOT']=self.temp.name
        run=subprocess.run([sys.executable,'-X','utf8','-B','-c','import json;from backend.wallet_account_roles import snapshot;print(json.dumps(snapshot()))'],
            cwd=PROJECT,env=environment,capture_output=True,text=True,timeout=15)
        self.assertEqual(run.returncode,0,run.stderr);self.assertEqual(json.loads(run.stdout),saved)

    def test_storage_purpose_allows_local_keys_but_explicitly_reports_online_custody(self):
        with patch.object(roles.wallet_vault,'status',return_value=[{'account_id':self.a,'vault_available':True}]):
            data=roles.set_role(self.a,'STORAGE')
        row=next(row for row in data['accounts'] if row['account_id']==self.a)
        self.assertEqual(row['role'],'STORAGE');self.assertEqual(row['storage_state'],'LOCAL_KEY_ONLINE')
        self.assertEqual(row['signer_state'],'LOCAL_ENCRYPTED')
        with patch.object(roles.wallet_vault,'status',return_value=[{'account_id':self.a,'vault_available':False}]):
            row=next(row for row in roles.snapshot()['accounts'] if row['account_id']==self.a)
        self.assertEqual(row['storage_state'],'LOCAL_KEY_KNOWN_UNAVAILABLE')
        self.assertEqual(row['signer_state'],'LOCAL_KEY_UNAVAILABLE')

    def test_invalid_role_unknown_account_capacity_and_vault_failure_do_not_replace_existing_role(self):
        prior=roles.set_role(self.a,'TRADING')
        for account,role in (('Trading','STORAGE'),(self.a,'COLD'),(self.a,{})):
            with self.assertRaises(ValueError):roles.set_role(account,role)
            self.assertEqual(roles.snapshot(),prior)
        with patch.object(roles,'MAX_ROLES',1):
            with self.assertRaisesRegex(ValueError,'LIMIT'):roles.set_role(self.b,'STORAGE')
        with patch.object(roles.wallet_vault,'status',side_effect=OSError('Synthetic unavailable key metadata')):
            with self.assertRaises(OSError):roles.set_role(self.a,'STORAGE')
        self.assertEqual(roles.snapshot(),prior)


def ui_fixture(directory):
    from copy import deepcopy
    from PySide6.QtCore import QObject,QPointF,Qt,QUrl,Signal,Slot
    from PySide6.QtGui import QFont,QFontDatabase
    from PySide6.QtQml import QQmlApplicationEngine,QQmlExpression,qmlContext
    from PySide6.QtQuick import QQuickItem
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    app=QApplication([])
    if os.name=='nt':
        for face in ('consola.ttf','consolab.ttf','seguisym.ttf'):QFontDatabase.addApplicationFont(str(Path(os.environ['SystemRoot'])/'Fonts'/face))
    QFont.insertSubstitution('monospace','Consolas' if os.name=='nt' else 'DejaVu Sans Mono')
    assets.bootstrap();sol=assets.NATIVE_SOL.split('/')[0]
    addresses=['11111111111111111111111111111111','TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA','So11111111111111111111111111111111111111112','0x'+'1'*40]
    ids=[assets.account(sol,addresses[0],'Trading'),assets.account(sol,addresses[1],'Förvaring extern'),
         assets.account(sol,addresses[2],'Förvaring lokal'),assets.account('eip155:1',addresses[3],'Förvaring Ethereum')]
    keys=[{'account_id':ids[i],'pubkey':addresses[i],'chain_id':sol,'vault_available':True,'backed_up':True} for i in (0,2)]
    key_patch=patch.object(roles.wallet_vault,'status',return_value=keys);key_patch.start()
    for index,identifier in enumerate(ids):roles.set_role(identifier,'TRADING' if index==0 else 'STORAGE')
    registry=assets.snapshot();accounts=registry['accounts'];nets=[n for n in registry['networks'] if n['id'] in {sol,'eip155:1'}]
    wanted=[a for a in registry['assets'] if a['id'] in {assets.NATIVE_SOL,'eip155:1/native:ETH'}]
    rows=[]
    for i,identifier in enumerate(ids):
        account=next(a for a in accounts if a['id']==identifier);asset=next(a for a in wanted if a['chain_id']==account['chain_id'])
        rows.append(dict(id=asset['id']+'@'+identifier,account_id=identifier,asset_id=asset['id'],chain_id=account['chain_id'],
            network='Solana' if i<3 else 'Ethereum',symbol=asset['symbol'],name=asset['name'],quantity='1.000000001',atomic='1000000001',
            balance_state='VERIFIED_READ',balance_current=True,observed_at=1700000000,
            value_usd=['7.44','9007199254740993.01','0.02','1.00'][i],price_state='CURRENT',scope='PUBLIC_WATCH',
            signer_state='LOCAL_ENCRYPTED' if i in (0,2) else 'WATCH_ONLY',address=addresses[i],label=account['label'],
            price_source='Synthetic exact fixture',price_quality='FIXTURE',price_basis='Canonical asset',price_observed_at=1700000000,liquidity_usd='1000000.00'))
    payload={'assets':wanted,'networks':nets,'accounts':accounts,'selected_asset':assets.NATIVE_SOL,'ui_operation':{},'wallet_transfers':[],
        'wallet_overview':{'accounts':accounts,'networks':nets,'rows':rows,'lab_rows':[],'local_wallets':keys,
            'summary':{'known_value_usd':'9007199254741001.47','account_count':4,'network_count':2,'unpriced_count':0},'events':[]}}
    class Host(QObject):
        omniStatusUpdated=Signal(str);cryptoStatusUpdated=Signal(str);walletAccountRolesUpdated=Signal(str)
        def __init__(self):super().__init__();self.calls=[]
        @Slot(result=str)
        def omniStatus(self):return json.dumps(payload)
        @Slot(result=str)
        def cryptoStatus(self):return '{}'
        @Slot(result=str)
        def explorerStatus(self):return '{"rows":[],"networks":[],"settings":{"paused":true},"needs_refresh":false}'
        @Slot(result=str)
        def walletAccountRoles(self):return json.dumps(roles.snapshot())
        @Slot(str,str,result=str)
        def walletSetAccountRole(self,identifier,role):
            raw=json.dumps(roles.set_role(identifier,role));self.walletAccountRolesUpdated.emit(raw);return raw
        @Slot(str,str,result=str)
        def omniAction(self,name,raw):
            args=json.loads(raw);self.calls.append((name,args))
            if name=='prepare_transfer':
                account=next(a for a in accounts if a['id']==args['account_id'])
                payload['wallet_transfer']={'id':'public-fixture-review','state':'PREPARED','body':dict(account_id=args['account_id'],
                    asset_id=args['asset_id'],chain_id=account['chain_id'],amount=args['amount'],symbol='SOL',
                    to=args['recipient'],**{'from':account['address']},mint='',cost_sol='0.000005',simulation='PASSED',
                    review_digest='public-fixture-review-digest',expires_at=time.time()+90)}
            payload['ui_operation']={'state':'done','name':name};return json.dumps(payload)
    host=Host();engine=QQmlApplicationEngine();warnings=[]
    engine.warnings.connect(lambda values:warnings.extend(value.toString() for value in values));engine.rootContext().setContextProperty('fixtureHost',host)
    path=directory/'roles.qml';path.write_text('import QtQuick\nimport '+json.dumps((PROJECT/'qml/components').as_uri())+'\nWindow {width:400;height:760;visible:true;WalletPopup {objectName:"popup";x:18;y:18;visualWidth:360;visualHeight:720;surfaceHost:fixtureHost}}',encoding='utf-8')
    engine.load(QUrl.fromLocalFile(str(path)));assert engine.rootObjects(),warnings
    window=engine.rootObjects()[0];popup=window.findChild(QQuickItem,'popup')
    def items(item):
        yield item
        for child in item.childItems():yield from items(child)
    QTest.qWait(120);window.grabWindow();overview=next(item for item in items(popup) if item.property('compactPopup') is True)
    def find(name,owner=overview):
        item=owner.findChild(QQuickItem,name);assert item is not None,name;return item
    def js(owner,code):
        expression=QQmlExpression(qmlContext(owner),owner,code);value=expression.evaluate();assert not expression.hasError(),expression.error().toString()
        return value[0] if isinstance(value,tuple) else value
    def click(item):
        assert item.isVisible() and item.isEnabled(),item.objectName()
        QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,item.mapToScene(QPointF(item.width()/2,item.height()/2)).toPoint());QTest.qWait(30);window.grabWindow()
    scope=find('walletAccountFilter');scope.forceActiveFocus();QTest.keyClick(window,Qt.Key_Down);QTest.qWait(30)
    assert overview.property('accountRoleFilter')=='TRADING'
    assert find('walletPositionList').property('count')==1
    assert find('walletTotalValue').property('text')=='$7.44'
    assert json.loads(js(overview,'JSON.stringify(allocation.segments)'))[0]['fraction']==1
    scope.forceActiveFocus();QTest.keyClick(window,Qt.Key_Down);QTest.qWait(30)
    assert overview.property('accountRoleFilter')=='STORAGE'
    assert find('walletPositionList').property('count')==3
    assert js(overview,'summary.known_value_usd')=='9007199254740994.03','Role sum rounded through Number'
    find('walletAssetSearch').setProperty('text','Ethereum');QTest.qWait(20)
    assert find('walletPositionList').property('count')==1
    assert js(overview,'summary.known_value_usd')=='9007199254740994.03','Search changed scoped total'
    find('walletAssetSearch').setProperty('text','');js(overview,"selectAccountScope({id:'',role:'TRADING'})");QTest.qWait(20)
    click(find('walletSend'));actions=find('walletActions')
    assert actions.property('ownTargetRole')=='STORAGE' and actions.property('accountId')==ids[0]
    assert actions.property('internalAccountId')=='' and not actions.property('canPrepare'),'Destination was auto-selected'
    action_asset=find('walletActionAsset',actions);action_asset.forceActiveFocus();QTest.keyClick(window,Qt.Key_Down);QTest.qWait(20)
    assert actions.property('assetId')==assets.NATIVE_SOL
    targets=json.loads(js(actions,'JSON.stringify(internalAccounts.map(function(a){return a.id}))'))
    assert set(targets)==set(ids[1:3]) and ids[3] not in targets,'Cross-chain target included'
    find('walletSendAmount',actions).setProperty('text','0.000000001')
    actions.setProperty('internalAccountId',ids[3]);QTest.qWait(20)
    assert not actions.property('canPrepare') and actions.property('destination')==''
    js(actions,"run('prepare_transfer',{account_id:accountId,asset_id:assetId,recipient:'wrong-chain',amount:'0.000000001'})")
    assert not host.calls,'Invalid target reached transfer adapter'
    actions.setProperty('internalAccountId',ids[1]);QTest.qWait(20)
    assert actions.property('canPrepare')
    button=find('walletPrepareTransfer',actions);scroll=find('walletActionScroll',actions)
    content=scroll.property('contentItem');position=button.mapToItem(content,QPointF(0,0)).y()
    scroll.setProperty('contentY',max(0,min(position-80,scroll.property('contentHeight')-scroll.height())))
    QTest.qWait(25);window.grabWindow();click(button);QTest.qWait(25)
    assert host.calls==[('prepare_transfer',{'account_id':ids[0],'asset_id':assets.NATIVE_SOL,'recipient':addresses[1],'amount':'0.000000001'})]
    assert actions.property('page')=='review' and not find('walletSendTransfer',actions).isEnabled()
    assert not actions.property('reviewed') and js(actions,'draft.chain_id')==sol
    # Externally stored/watch-only funds cannot be signed by a purpose label.
    js(overview,'openRoleMove("TRADING",'+json.dumps(rows[1])+')');QTest.qWait(20)
    actions.setProperty('internalAccountId',ids[0]);find('walletSendAmount',actions).setProperty('text','0.01');QTest.qWait(20)
    assert not actions.property('canPrepare') and not actions.property('sourceKeyMatches')
    js(actions,"run('prepare_transfer',{})");assert len(host.calls)==1
    # A local STORAGE-purpose wallet is explicitly online and may use the
    # ordinary reviewed flow; purpose alone must not block its actual signer.
    js(overview,'openRoleMove("TRADING",'+json.dumps(rows[2])+')');QTest.qWait(20)
    actions.setProperty('internalAccountId',ids[0]);find('walletSendAmount',actions).setProperty('text','0.01');QTest.qWait(20)
    assert actions.property('canPrepare') and 'online' in find('walletSourceRoleStatus',actions).property('text')
    assert len(host.calls)==1,'Opening a move signed or submitted funds'
    js(overview,'actionOpen=false;openRoleManager()');QTest.qWait(20)
    overview.setProperty('roleManagerAccountId',ids[0]);QTest.qWait(20)
    manager=overview.findChild(QObject,'walletAccountRoleManager');manager_content=manager.property('contentItem')
    storage=find('walletAssignStorage',manager_content)
    assert storage.isEnabled();click(storage)
    assert roles.snapshot()['roles'][ids[0]]=='STORAGE'
    assert not warnings,warnings
    window.close();engine.deleteLater();app.processEvents();key_patch.stop()
    print(json.dumps({'status':'PASS','real_qml':True,'purpose_separate_from_signer':True,'exact_role_total':True,
        'same_chain_targets_only':True,'review_only_no_send':True,'external_signer_gate':True,'warnings':len(warnings)}))


class AccountRoleUI(unittest.TestCase):
    def test_actual_role_scope_exact_total_and_own_account_review(self):
        with tempfile.TemporaryDirectory(prefix='gg-role-ui-') as temporary:
            environment=os.environ.copy();environment.update(QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software',QT_QUICK_CONTROLS_STYLE='Basic',
                GG_DESKTOP_STATE_ROOT=str(Path(temporary)/'state'),GG_DESKTOP_DATA_ROOT=str(Path(temporary)/'data'))
            run=subprocess.run([sys.executable,'-X','utf8','-B',str(Path(__file__).resolve()),'--fixture',temporary],
                cwd=PROJECT,env=environment,capture_output=True,text=True,encoding='utf-8',timeout=25)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr);print(run.stdout.strip())


if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--fixture':ui_fixture(Path(sys.argv[2]))
    else:unittest.main()
