"""Actual Qt recovery of an older persisted transfer; offline RPC reads only."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PROJECT=Path(__file__).resolve().parents[1]


def fixture(directory):
    sys.path.insert(0,str(PROJECT))
    import json
    import threading
    import time
    from unittest.mock import patch
    from PySide6.QtCore import QObject,Signal,Slot,QUrl,QPointF,Qt
    from PySide6.QtGui import QGuiApplication,QFontDatabase,QFont
    from PySide6.QtQml import QQmlApplicationEngine,QQmlExpression,qmlContext
    from PySide6.QtQuick import QQuickItem
    from PySide6.QtTest import QTest
    from solders.pubkey import Pubkey
    from backend import omni_assets as store,omni_service,omni_rpc,solana_transfers as transfers
    from backend.crypto_ui_runtime import CryptoUiRuntime

    app=QGuiApplication([])
    if os.name=='nt':
        for name in ('consola.ttf','consolab.ttf','seguisym.ttf'):
            QFontDatabase.addApplicationFont(str(Path(os.environ.get('SystemRoot','C:/Windows'))/'Fonts'/name))
    QFont.insertSubstitution('monospace','Consolas' if os.name=='nt' else 'DejaVu Sans Mono')
    app.setFont(QFont('Consolas' if os.name=='nt' else 'DejaVu Sans Mono'))
    store.bootstrap()
    address_a=str(Pubkey.from_bytes(bytes([11])*32));address_b=str(Pubkey.from_bytes(bytes([22])*32))
    account_a=store.account(transfers.SOL,address_a,'Older source')
    account_b=store.account(transfers.SOL,address_b,'Newer source')
    def body(account,source,destination,amount):
        return {'account_id':account,'asset_id':store.NATIVE_SOL,'from':source,'to':destination,
                'amount':amount,'symbol':'SOL','mint':'','cost_sol':'0.000005','simulation':'PASSED',
                'expires_at':time.time()+90,'review_digest':'offline-reviewed-fixture'}
    with store.db(True) as db:
        transfers._table(db)
        db.execute('INSERT INTO wallet_transfers(id,state,body,txid,error,updated_at) VALUES(?,?,?,?,?,?)',
                   ('older-uncertain','UNCERTAIN',store.pack(body(account_a,address_a,address_b,'0.1')),
                    'offline-public-signature','',time.time()-100))
        db.execute('INSERT INTO wallet_transfers(id,state,body,txid,error,updated_at) VALUES(?,?,?,?,?,?)',
                   ('newer-draft','PREPARED',store.pack(body(account_b,address_b,address_a,'0.2')),'','',time.time()))
    store.preference('selected_transfer','newer-draft')
    rpc_calls=[]
    def offline_rpc(url,payload=None,**kwargs):
        method=payload['method'];rpc_calls.append(method)
        if method=='getGenesisHash':result=transfers.MAINNET_GENESIS
        elif method=='getSignatureStatuses':
            assert payload['params'][0]==['offline-public-signature']
            result={'context':{'slot':1},'value':[{'slot':1,'confirmations':1,'err':None,'confirmationStatus':'confirmed'}]}
        else:raise AssertionError('Unexpected UI fixture RPC '+method)
        return {'jsonrpc':'2.0','id':1,'result':result}
    rpc_patch=patch.object(omni_rpc,'_json',side_effect=offline_rpc);rpc_patch.start()

    class Host(QObject):
        omniStatusUpdated=Signal(str)
        def __init__(self):
            super().__init__();self.runtime=CryptoUiRuntime(self,snapshot=omni_service.snapshot,ttl=.02)
            self.runtime.updated.connect(self.omniStatusUpdated);self.calls=[];self.gate=None
        @Slot(result=str)
        def omniStatus(self):return self.runtime.snapshot()
        @Slot(str,str,result=str)
        def omniAction(self,name,raw):
            self.calls.append((name,json.loads(raw)));gate=self.gate
            def work():
                if gate and not gate.wait(5):raise ValueError('OFFLINE_UI_GATE_TIMEOUT')
                return omni_service.action(name,raw)
            return self.runtime.submit(name,work)
    host=Host();engine=QQmlApplicationEngine();warnings=[]
    engine.warnings.connect(lambda errors:warnings.extend(e.toString() for e in errors))
    engine.rootContext().setContextProperty('testHost',host)
    qml='''import QtQuick
import QtQuick.Controls
import COMPONENTS
ApplicationWindow {width:900;height:850;visible:true;color:'#111111'
CryptoSpaceFrame {id:nativeSpace;anchors.fill:parent;section:'WALLET';title:'Översikt';context:'OFFLINE · LITESVM TESTDATA';surfaceHost:testHost;detailsAvailable:true;detailsChecked:testWallet.detailsVisible;onDetailsToggleRequested:testWallet.toggleDetails()}
OmniWalletPanel {id:testWallet;objectName:'testWallet';parent:nativeSpace.contentItem;anchors.fill:parent;dashboard:true;surfaceHost:testHost}
}'''.replace('COMPONENTS',json.dumps((PROJECT/'qml/components').as_uri()))
    path=directory/'fixture.qml';path.write_text(qml,encoding='utf-8');engine.load(QUrl.fromLocalFile(str(path)))
    assert engine.rootObjects(),warnings
    window=engine.rootObjects()[0];wallet=window.findChild(QQuickItem,'testWallet')
    receiver=wallet.findChild(QQuickItem,'walletActions')
    def js(item,expression):
        expr=QQmlExpression(qmlContext(item),item,expression);result=expr.evaluate()
        assert not expr.hasError(),expr.error().toString()
        return result[0] if isinstance(result,tuple) else result
    def wait_for(predicate):
        for _ in range(200):
            app.processEvents()
            if predicate():return
            QTest.qWait(20);time.sleep(.002)
        raise AssertionError('TRANSFER_UI_TIMEOUT '+js(receiver,'JSON.stringify({page:page,pendingAction:pendingAction,requestedTransferId:requestedTransferId,operation:operation,transferId:transfer.id,stateTransferId:(state.wallet_transfer || {}).id})')+' '+repr(warnings))
    def items(root):
        stack=[root]
        while stack:
            item=stack.pop();yield item;stack.extend(item.childItems())
    def click(item):
        QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,item.mapToScene(QPointF(item.width()/2,item.height()/2)).toPoint())
        QTest.qWait(20)
    def reveal(item):
        scroll=receiver.findChild(QQuickItem,'walletActionScroll')
        scroll.setProperty('contentY',max(0,item.mapToItem(scroll,QPointF(0,0)).y()+scroll.property('contentY')-scroll.height()+item.height()+24))
        QTest.qWait(30)
    wait_for(lambda:js(wallet,'!busy && transfers.length===2'))
    QTest.qWait(60)
    window.setWidth(1100);QTest.qWait(80)
    account_control=next(i for i in items(wallet) if i.objectName()=='walletRailAccount' and i.property('targetAccountId')==account_b)
    click(account_control)
    assert wallet.property('accountFilter')==account_b and js(wallet,'scopedAccounts.length===1 && rows.every(function(r){return r.account_id===accountFilter})')
    wallet.setProperty('accountFilter','');window.setWidth(900);QTest.qWait(60)
    assert js(receiver,'transfer.id==="newer-draft"')
    history=wallet.findChild(QQuickItem,'walletTransferHistory');assert history.isVisible();click(history)
    assert receiver.property('page')=='history'
    older=next(i for i in items(receiver) if i.objectName()=='walletOpenTransferReceipt' and i.property('transferId')=='older-uncertain')
    gate=threading.Event();host.gate=gate
    try:
        click(older)
        assert receiver.property('busy') and receiver.property('page')=='history'
        assert js(receiver,'transfer.id==="newer-draft" && requestedTransferId==="older-uncertain"')
    finally:
        host.gate=None;gate.set()
    wait_for(lambda:js(receiver,'!busy && page==="review" && transfer.id==="older-uncertain"'))
    assert receiver.property('accountId')==account_a and receiver.property('assetId')==store.NATIVE_SOL
    for width in (430,1100,1440):
        window.setWidth(width);QTest.qWait(80)
        form=receiver.findChild(QQuickItem,'walletActionScroll');rail=wallet.findChild(QQuickItem,'walletFactsRail')
        assert form.width()>250 and form.x()+form.width()==receiver.width()
        assert rail.isVisible()==wallet.property('railVisible')
        assert not wallet.findChild(QQuickItem,'walletOverviewHeader').isVisible()
        window.grabWindow().save(str(directory/('wallet-review-'+str(width)+'.png')))
    window.setWidth(900);QTest.qWait(60)
    check=receiver.findChild(QQuickItem,'walletCheckTransfer')
    assert check.isVisible() and not receiver.findChild(QQuickItem,'walletSendTransfer').isVisible()
    click(check)
    wait_for(lambda:js(receiver,'!busy && transfer.id==="older-uncertain" && transfer.state==="CONFIRMED"'))
    assert transfers.snapshot('newer-draft')['state']=='PREPARED'
    assert host.calls==[('select_transfer',{'id':'older-uncertain'}),('check_transfer',{'id':'older-uncertain'})]
    assert rpc_calls==['getGenesisHash','getSignatureStatuses']
    js(receiver,'closeRequested()');QTest.qWait(60);click(history)
    assert receiver.property('page')=='history'
    js(receiver,'selectTransfer("missing-fixture-transfer")')
    wait_for(lambda:js(receiver,'!busy && operation.state==="error"'))
    assert receiver.property('page')=='history'
    assert not warnings,warnings
    # Rich reference capture uses the existing local SVM transaction fixture,
    # an actual isolated DPAPI vault/backup, and balances read from that bank.
    from tests.test_crypto_solana_wallet import TransferTests
    from backend import wallet_vault as vault,crypto_explorer as market
    from backend import crypto_pump_accounts as spl
    from tests.test_crypto_explorer import coin,pair
    from solders.keypair import Keypair
    from solders.account import Account
    real_vault_status=vault.status
    rich=TransferTests('test_actual_signed_spl_round_trip_with_ata_creation_and_real_svm')
    rich.setUp()
    try:
        vault.status.side_effect=real_vault_status
        vault._save(rich.source,'GG · krypterad nyckel')
        vault.export_backup(str(rich.source.pubkey()),rich.root/'native-ui.ggwallet','isolated-ui-fixture-password')
        store.account(transfers.SOL,str(rich.recipient.pubkey()),'Extern · bevakning')
        prepared=rich.prepare()
        def bank_observations():
            for account in store.snapshot()['accounts']:
                for asset in store.snapshot()['assets']:
                    if asset['chain_id']!=transfers.SOL:continue
                    if asset['namespace']=='native':atomic=rich.bank.get_balance(rich.Pubkey.from_string(account['address'])) or 0
                    else:
                        token_address=spl.derive_ata(account['address'],asset['reference'])
                        info=rich.account_info(token_address)
                        atomic=spl.decode_token_account(info)['amount'] if info else 0
                    observation={'asset_id':asset['id'],'account_id':account['id'],'atomic':str(atomic),
                                 'quantity':store.format_atomic(atomic,asset['decimals']),
                                 'state':'VERIFIED_READ','observed_at':time.time(),'identity_level':'LOCAL_SVM_FIXTURE'}
                    with store.db(True) as db:db.execute('INSERT OR REPLACE INTO observations VALUES(?,?,?)',(asset['id'],account['id'],store.pack(observation)))
        native=coin('solana',162.4);native['symbol']='SOL';native['sparkline_in_7d']={'price':[159+i*.08 for i in range(48)]}
        market._save_rows(market.parse_coins([native]))
        bank_observations()
        wallet.setProperty('lastStatus','');js(wallet,'pull()')
        wait_for(lambda:js(wallet,'!busy && state.wallet_transfer && state.wallet_transfer.id==='+json.dumps(prepared['id'])))
        js(wallet,'run("select_transfer",{id:'+json.dumps(prepared['id'])+'})')
        wait_for(lambda:js(wallet,'!busy && operation.state==="done" && operation.name==="select_transfer"'))
        window.setWidth(1586);window.setHeight(992);QTest.qWait(100)
        wallet.setProperty('actionOpen',False);QTest.qWait(60)
        holding=next(i for i in items(wallet) if i.objectName()=='walletAssetRow' and i.property('accountTarget')==rich.source_id and i.property('assetTarget')==rich.asset['id'])
        click(holding)
        wait_for(lambda:js(wallet,'!busy && actionOpen && !detailOpen'))
        assert receiver.property('accountId')==rich.source_id and receiver.property('assetId')==rich.asset['id'] and receiver.property('page')=='receive'
        assert js(receiver,'sourceKeyMatches && localKey.vault_available && localKey.backed_up && adapterSupported')
        assert receiver.property('matchingPreview') and receiver.findChild(QQuickItem,'walletTransferPreview').isVisible()
        scroll=receiver.findChild(QQuickItem,'walletActionScroll')
        consent=receiver.findChild(QQuickItem,'walletReviewConsent')
        send=receiver.findChild(QQuickItem,'walletSendTransfer')
        assert scroll.property('contentY')==0 and send.mapToScene(QPointF(0,send.height())).y()<=window.height(),('wide receive review overflow',send.mapToScene(QPointF(0,send.height())).y(),window.height())
        scroll.setProperty('contentY',max(0,consent.mapToItem(scroll,QPointF(0,0)).y()-scroll.height()+consent.height()+12));QTest.qWait(40)
        click(consent)
        assert receiver.property('reviewedTransferId')==prepared['id'] and send.isEnabled()
        native_row=next(i for i in items(receiver) if i.objectName()=='walletGroupedAsset' and i.property('accountTarget')==rich.source_id and i.property('assetTarget')==store.NATIVE_SOL)
        click(native_row)
        assert receiver.property('assetId')==store.NATIVE_SOL and not receiver.property('reviewed') and not receiver.property('matchingPreview') and not send.isEnabled()
        token_row=next(i for i in items(receiver) if i.objectName()=='walletGroupedAsset' and i.property('accountTarget')==rich.source_id and i.property('assetTarget')==rich.asset['id'])
        click(token_row);assert not receiver.property('matchingPreview') and not receiver.property('reviewed') and not send.isEnabled()
        # The real holding reopens the same token workspace, rather than an old
        # detached detail card. Saved exact receipt preview is read-only until
        # the user explicitly consents again.
        wallet.setProperty('actionOpen',False);QTest.qWait(40);click(holding)
        wait_for(lambda:js(receiver,'!busy && page==="receive" && matchingPreview'))
        scroll.setProperty('contentY',0)
        for width in (1586,1100,900,430):
            window.setWidth(width);window.setHeight(992);QTest.qWait(100)
            window.grabWindow().save(str(directory/('wallet-reference-'+str(width)+'.png')))
        facts=receiver.findChild(QQuickItem,'walletFactsButton');click(facts)
        drawer=wallet.findChild(QObject,'walletFactsDrawer');assert drawer.property('visible')
        drawer_facts=wallet.findChild(QQuickItem,'walletDrawerTelemetry')
        assert js(drawer_facts,'localKey.vault_available && localKey.backed_up && selectedAccount.id==='+json.dumps(rich.source_id))
        window.grabWindow().save(str(directory/'wallet-facts-430.png'))
        click(wallet.findChild(QQuickItem,'walletCloseFacts'))
        assert not drawer.property('visible') and not rich.sent
        # External withdrawal and own-account transfer both use actual local
        # SVM preparation/simulation. Never click Signera & skicka.
        window.setWidth(1586);QTest.qWait(60);scroll.setProperty('contentY',0)
        click(receiver.findChild(QQuickItem,'walletModeSend'))
        assert receiver.property('page')=='send' and receiver.property('actionMode')=='send' and not receiver.property('matchingPreview') and not send.isEnabled()
        recipient=receiver.findChild(QQuickItem,'walletSendRecipient');amount=receiver.findChild(QQuickItem,'walletSendAmount')
        recipient.setProperty('text',str(rich.recipient.pubkey()));amount.setProperty('text','2.5');QTest.qWait(30)
        prepare=receiver.findChild(QQuickItem,'walletPrepareTransfer');assert prepare.isEnabled()
        for width in (1586,1100,900,430):
            window.setWidth(width);window.setHeight(992);scroll.setProperty('contentY',0);QTest.qWait(70)
            window.grabWindow().save(str(directory/('wallet-send-'+str(width)+'.png')))
        window.setWidth(1586);QTest.qWait(60)
        reveal(prepare);gate=threading.Event();host.gate=gate
        try:
            click(prepare);assert receiver.property('busy')
            js(wallet,'choose(rows.filter(function(r){return r.asset_id==='+json.dumps(store.NATIVE_SOL)+'})[0])')
            js(receiver,'setMode("receive")')
            assert receiver.property('assetId')==rich.asset['id'] and receiver.property('actionMode')=='send'
            assert not recipient.isEnabled() and not amount.isEnabled() and not receiver.findChild(QQuickItem,'walletModeInternal').isEnabled()
        finally:host.gate=None;gate.set()
        wait_for(lambda:js(receiver,'!busy && page==="review" && matchingPreview'))
        external_id=js(receiver,'transfer.id')
        assert external_id!=prepared['id'] and js(receiver,'draft.account_id==='+json.dumps(rich.source_id)+' && draft.asset_id==='+json.dumps(rich.asset['id'])+' && draft.to==='+json.dumps(str(rich.recipient.pubkey()))+' && draft.amount==="2.5" && draft.simulation==="PASSED"')
        reveal(consent);click(consent);assert send.isEnabled()
        recipient.setProperty('text',str(rich.source.pubkey()));QTest.qWait(20)
        assert not send.isEnabled() and not receiver.property('reviewed') and not receiver.property('matchingPreview')
        js(receiver,'selectTransfer('+json.dumps(external_id)+')')
        wait_for(lambda:js(receiver,'!busy && page==="review" && matchingPreview'))
        reveal(consent);click(consent);assert send.isEnabled()
        amount.setProperty('text','3');QTest.qWait(20)
        assert not send.isEnabled() and not receiver.property('reviewed') and not receiver.property('matchingPreview')
        scroll.setProperty('contentY',0);click(receiver.findChild(QQuickItem,'walletModeInternal'))
        assert receiver.property('actionMode')=='internal' and receiver.property('page')=='send' and not receiver.property('internalAccountId') and not prepare.isEnabled()
        assert js(receiver,'internalAccounts.length===1 && internalAccounts[0].id==='+json.dumps(rich.recipient_id)+' && !keyFor(internalAccounts[0].id).pubkey')
        target=receiver.findChild(QQuickItem,'walletInternalRecipient')
        js(target,'currentIndex=1;activated(1)');amount.setProperty('text','1.25');QTest.qWait(25)
        assert receiver.property('internalAccountId')==rich.recipient_id and js(receiver,'destination==='+json.dumps(str(rich.recipient.pubkey()))+' && canPrepare')
        for width in (1586,1100,900,430):
            window.setWidth(width);window.setHeight(992);scroll.setProperty('contentY',0);QTest.qWait(80)
            window.grabWindow().save(str(directory/('wallet-internal-'+str(width)+'.png')))
        window.setWidth(1586);QTest.qWait(60);reveal(prepare);click(prepare)
        wait_for(lambda:js(receiver,'!busy && page==="review" && matchingPreview'))
        internal_id=js(receiver,'transfer.id')
        assert internal_id!=external_id and js(receiver,'draft.to==='+json.dumps(str(rich.recipient.pubkey()))+' && draft.amount==="1.25" && draft.account_id==='+json.dumps(rich.source_id)+' && draft.simulation==="PASSED"')
        for width in (1586,1100,900,430):
            window.setWidth(width);window.setHeight(992);scroll.setProperty('contentY',0);QTest.qWait(70)
            window.grabWindow().save(str(directory/('wallet-review-simulated-'+str(width)+'.png')))
        window.setWidth(1586);QTest.qWait(60)
        reveal(consent);click(consent);assert send.isEnabled()
        # Formal pending approval locks the reviewed immutable context. A
        # holding click reopens it instead of replacing its source/token.
        locked_state=json.loads(js(wallet,'JSON.stringify(state)'));locked_state['ui_operation']={'state':'approval_required','name':'send_transfer'}
        wallet.setProperty('state',locked_state);QTest.qWait(40)
        assert receiver.property('approvalPending') and not receiver.findChild(QQuickItem,'walletModeReceive').isEnabled() and not consent.isEnabled()
        # Reading or hiding the context panel cannot change the immutable
        # approval target, release its lock, or dispatch another wallet action.
        details=window.findChild(QQuickItem,'spaceDetailsToggle');call_count=len(host.calls)
        original_target=js(receiver,'JSON.stringify({account:accountId,asset:assetId,id:transfer.id,digest:draft.review_digest,pending:pendingAction})')
        click(details);assert not wallet.property('railVisible')
        click(details);assert wallet.property('railVisible')
        js(wallet,'openActivity()');feed=wallet.findChild(QQuickItem,'walletActivityFeed')
        assert feed.isVisible() and not receiver.isVisible()
        close_activity=next(i for i in items(feed) if i.property('text')=='×')
        click(close_activity);assert receiver.isVisible() and not feed.isVisible()
        assert original_target==js(receiver,'JSON.stringify({account:accountId,asset:assetId,id:transfer.id,digest:draft.review_digest,pending:pendingAction})')
        assert receiver.property('approvalPending') and not consent.isEnabled() and len(host.calls)==call_count
        scroll.setProperty('contentY',0);QTest.qWait(30)
        window.grabWindow().save(str(directory/'wallet-approval-required-1586.png'))
        wallet.setProperty('actionOpen',False)
        js(wallet,'choose(rows.filter(function(r){return r.asset_id==='+json.dumps(store.NATIVE_SOL)+'})[0])')
        assert wallet.property('actionOpen') and receiver.property('assetId')==rich.asset['id'] and js(receiver,'transfer.id==='+json.dumps(internal_id))
        call_count=len(host.calls);js(wallet,'refreshOverview()');assert len(host.calls)==call_count
        locked_state['ui_operation']={'state':'cancelled','name':'send_transfer'};wallet.setProperty('state',locked_state);QTest.qWait(30)
        scroll.setProperty('contentY',0);click(receiver.findChild(QQuickItem,'walletModeReceive'))
        assert not receiver.property('reviewed') and not send.isEnabled()
        # Watch-only source remains useful for receive, but cannot prepare.
        js(receiver,'setMode("internal");accountId='+json.dumps(rich.recipient_id)+';assetId='+json.dumps(rich.asset['id']))
        assert not receiver.property('internalAccountId') and not prepare.isEnabled() and not receiver.property('sourceKeyMatches')
        # Guard-only state changes are isolated UI fixtures. Cross-chain and
        # self-address targets are never offered; missing vault/backup,
        # unsupported adapters and vanished destinations block preparation.
        guard_state=json.loads(js(wallet,'JSON.stringify(state)'))
        source_state=json.loads(json.dumps(guard_state))
        source_state['wallet_overview']['accounts'].append({'id':'cross-chain-ui-fixture','chain_id':'eip155:1','address':'0x'+'3'*40,'label':'Other chain'})
        source_state['wallet_overview']['accounts'].append({'id':'same-address-ui-fixture','chain_id':transfers.SOL,'address':str(rich.source.pubkey()),'label':'Same address'})
        wallet.setProperty('state',source_state);js(receiver,'accountId='+json.dumps(rich.source_id)+';assetId='+json.dumps(rich.asset['id'])+';setMode("internal")')
        assert js(receiver,'internalAccounts.length===1 && internalAccounts[0].id==='+json.dumps(rich.recipient_id))
        js(target,'currentIndex=1;activated(1)');amount.setProperty('text','1');QTest.qWait(20);assert prepare.isEnabled()
        for field in ('vault_available','backed_up'):
            blocked=json.loads(json.dumps(source_state));blocked['wallet_overview']['local_wallets'][0][field]=False
            wallet.setProperty('state',blocked);QTest.qWait(20);assert not prepare.isEnabled(),field
            wallet.setProperty('state',source_state);QTest.qWait(20);assert prepare.isEnabled(),field
        missing_target=json.loads(json.dumps(source_state));missing_target['wallet_overview']['accounts']=[a for a in missing_target['wallet_overview']['accounts'] if a['id']!=rich.recipient_id]
        wallet.setProperty('state',missing_target);QTest.qWait(20)
        assert not receiver.property('destination') and not prepare.isEnabled() and receiver.findChild(QQuickItem,'walletNoInternalRecipient').isVisible()
        wallet.setProperty('state',source_state);js(receiver,'accountId="cross-chain-ui-fixture";assetId="eip155:1/native:ETH"')
        assert not receiver.property('adapterSupported') and not prepare.isEnabled() and receiver.findChild(QQuickItem,'walletTransferAdapterStatus').isVisible()
        wallet.setProperty('state',guard_state);QTest.qWait(20)
        # An invalid account/asset tuple cannot open a different workspace.
        wallet.setProperty('actionOpen',False)
        js(wallet,'choose({account_id:"missing",asset_id:'+json.dumps(rich.asset['id'])+',chain_id:'+json.dumps(transfers.SOL)+'})')
        assert not wallet.property('actionOpen')
        wallet.setProperty('actionOpen',False)
        # Additional valid fixture mints make row density visible without
        # shipping sample holdings, prices or goods into the product.
        for index in range(2,10):
            mint=str(Keypair.from_seed(bytes([90+index])*32).pubkey())
            asset=store.register_asset(transfers.SOL,'token',mint,'TST'+str(index),'Local SVM fixture '+str(index),6,metadata='RPC_METADATA')
            mint_data=bytes([1,0,0,0])+bytes(rich.source.pubkey())+(10**12).to_bytes(8,'little')+bytes([6,1])+bytes(36)
            rich.bank.set_account(rich.Pubkey.from_string(mint),Account(rich.bank.minimum_balance_for_rent_exemption(82),mint_data,rich.Pubkey.from_string(spl.TOKEN_PROGRAM)))
            token_data=bytes(rich.Pubkey.from_string(mint))+bytes(rich.source.pubkey())+(index*100*10**6).to_bytes(8,'little')+bytes(36)+b'\x01'+bytes(12)+bytes(8)+bytes(36)
            rich.bank.set_account(rich.Pubkey.from_string(spl.derive_ata(str(rich.source.pubkey()),mint)),Account(rich.bank.minimum_balance_for_rent_exemption(165),token_data,rich.Pubkey.from_string(spl.TOKEN_PROGRAM)))
            quote=pair('solana',mint,str(index/10),pool='offline-svm-'+str(index));quote['baseToken'].update(symbol=asset['symbol'],name=asset['name'])
            rows=market.parse_pairs({'pairs':[quote]});rows[0]['sparkline']={'prices':[index/10*(1+j*.002) for j in range(48)],'period':'7D','source':'OFFLINE PROVIDER FIXTURE'}
            market._save_rows(rows)
            with store.db(True) as db:db.execute('INSERT OR REPLACE INTO explorer_bindings VALUES(?,?,?)',(asset['id'],rows[0]['id'],'LOCAL_SVM_FIXTURE_IDENTITY'))
        third=Keypair.from_seed(bytes([77])*32).pubkey();rich.bank.airdrop(third,200000000)
        store.account(transfers.SOL,str(third),'Reserver · bevakning')
        bank_observations();wallet.setProperty('lastStatus','');js(wallet,'pull()')
        wait_for(lambda:js(wallet,'!busy && wallet.accounts.length===3 && rows.length>=10'))
        for width in (1586,1100,900,430):
            window.setWidth(width);window.setHeight(992);QTest.qWait(100)
            window.grabWindow().save(str(directory/('overview-reference-'+str(width)+'.png')))
        assert not rich.sent and not warnings,warnings
    finally:
        host.runtime.close();rich.doCleanups()
    wallet.setProperty('actionOpen',True)
    js(receiver,'page="review";state=({wallet_transfer:{state:"FAILED",error:"WALLET_TRANSACTION_EXPIRED",txid:"fixture-expired-signature",body:{}},ui_operation:{state:"done",name:"check_transfer"}})')
    QTest.qWait(30)
    outcome=receiver.findChild(QQuickItem,'walletTransferOutcomeDetail')
    assert outcome.isVisible() and 'Ingen omsändning' in outcome.property('text')
    assert not receiver.findChild(QQuickItem,'walletSendTransfer').isVisible()
    destination=os.environ.get('GG_TRANSFER_UI_EVIDENCE')
    if destination:
        import shutil
        Path(destination).mkdir(parents=True,exist_ok=True)
        for image in directory.glob('*.png'):shutil.copy2(image,Path(destination)/image.name)
    print(json.dumps({'status':'PASS','older_persisted_transfer_recovered':True,'correct_receipt_before_review':True,
                      'read_only_status_check':True,'live_network':False,'warnings':len(warnings)}))
    host.runtime.close();window.close();engine.deleteLater();app.processEvents();rpc_patch.stop()


class TransferUi(unittest.TestCase):
    def test_recover_older_pending_transfer_and_check_exact_signature(self):
        with tempfile.TemporaryDirectory(prefix='gg-transfer-ui-') as temporary:
            directory=Path(temporary);env=os.environ.copy()
            env.update(QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software',QT_QUICK_CONTROLS_STYLE='Basic',
                       GG_DESKTOP_STATE_ROOT=str(directory/'state'),GG_DESKTOP_DATA_ROOT=str(directory/'data'))
            result=subprocess.run([sys.executable,'-B',str(Path(__file__).resolve()),'--fixture',temporary],
                                  cwd=PROJECT,env=env,capture_output=True,text=True,timeout=45)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr);print(result.stdout.strip())


if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--fixture':fixture(Path(sys.argv[2]))
    else:unittest.main()
