"""Actual CRYPTO account dashboard -> market -> token -> wallet -> GG lab, offline."""
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
    import time
    import math
    import threading
    from unittest.mock import patch
    from PySide6.QtCore import QObject,Signal,Slot,QUrl,QPointF,Qt
    from PySide6.QtGui import QGuiApplication,QFontDatabase,QFont
    from PySide6.QtQml import QQmlApplicationEngine,QQmlExpression,qmlContext
    from PySide6.QtQuick import QQuickItem
    from PySide6.QtTest import QTest
    from backend import crypto_explorer as market,omni_service,omni_rpc,omni_lab,omni_assets as store,marketplace_host,marketplace_discovery,crypto_activity
    from backend.crypto_ui_runtime import CryptoUiRuntime
    from tests.test_crypto_explorer import coin,pair
    app=QGuiApplication([])
    if os.name=='nt':
        for name in ('consola.ttf','consolab.ttf','seguisym.ttf'):QFontDatabase.addApplicationFont(str(Path(os.environ.get('SystemRoot','C:/Windows'))/'Fonts'/name))
    QFont.insertSubstitution('monospace','Consolas' if os.name=='nt' else 'DejaVu Sans Mono');app.setFont(QFont('Consolas' if os.name=='nt' else 'DejaVu Sans Mono'))
    store.bootstrap();omni_lab.create()
    def public_response(url,payload=None,**kwargs):
        if '/nfts/list?' in url:return [{'id':'fixture-'+str(i),'name':'Publik testsamling '+str(i),'symbol':'NFT','contract_address':'0x'+'1'*40,'asset_platform_id':'ethereum'} for i in range(100)]
        if '/api/v3/nfts/fixture-' in url:return {'id':url.rsplit('/',1)[1],'name':'Publik testsamling','contract_address':'0x'+'1'*40,'asset_platform_id':'ethereum','image':{},'description':'Kontrollerad testdata för publik samlingskatalog.','floor_price':{'usd':12},'total_supply':100}
        if '/coins/markets?' in url:
            rows=[coin('bitcoin',100),coin('ethereum',20),coin('solana',3),coin('kaspa',.1)]+[coin('fixture-'+str(i),i+.2) for i in range(96)]
            for i,row in enumerate(rows):row['sparkline_in_7d']={'price':[max(.0001,row['current_price'])*(1+.025*math.sin(j/6)+(.001 if i%2==0 else -.001)*j) for j in range(168)]}
            rows[-1]['sparkline_in_7d']={'price':[]}
            from urllib.parse import urlparse,parse_qs
            identifiers=parse_qs(urlparse(url).query).get('ids')
            if identifiers:rows=[r for r in rows if r['id'] in identifiers[0].split(',')]
            return rows
        if '/api/v3/search?' in url:return {'coins':[coin('fixture-search',None)]}
        if '/api/v3/coins/bitcoin?' in url:return {'id':'bitcoin','platforms':{},'market_data':{'current_price':{'usd':100},'market_cap':{'usd':1000000}}}
        if '/api/v3/coins/solana?' in url:return {'id':'solana','platforms':{},'market_data':{'current_price':{'usd':3},'market_cap':{'usd':1000000}}}
        if '/market_chart?' in url:return {'prices':[[int((time.time()-86400*7+i*3600)*1000),100+i*.1] for i in range(168)]}
        if '/api/v3/coins/fixture-search?' in url:return {'id':'fixture-search','platforms':{'ethereum':'0x'+'1'*40},'market_data':{'current_price':{'usd':4}}}
        if '/latest/dex/search?' in url or '/token-pairs/' in url:return {'pairs':[pair(price='4'),pair('base',price='5')]}
        if payload:
            method=payload['method'];result=None
            if method=='eth_chainId':result='0x1'
            elif method=='eth_getCode':result='0x6000'
            elif method=='eth_call':
                selector=payload['params'][0]['data'][:10]
                if selector=='0x313ce567':result='0x12'
                elif selector=='0x95d89b41':result='0x'+b'SAME'.hex().ljust(64,'0')
                elif selector=='0x06fdde03':result='0x'+b'Fixture token'.hex().ljust(64,'0')
                elif selector=='0x70a08231':result=hex(42*10**18)
            elif method=='eth_getBalance':result=hex(5*10**18)
            if result is not None:return {'jsonrpc':'2.0','id':1,'result':result}
        raise ValueError('UNEXPECTED_TEST_PUBLIC_REQUEST')
    request_patch=patch.object(omni_rpc,'_json',side_effect=public_response);request_patch.start()
    provider_patch=patch.object(market,'PROVIDERS',{k:dict(v,spacing=0) for k,v in market.PROVIDERS.items()});provider_patch.start()
    image_patch=patch.object(marketplace_discovery,'_image',return_value=(PROJECT/'qml/assets/knowledge-cell.png').as_uri());image_patch.start()
    class Host(QObject):
        explorerStatusUpdated=Signal(str);omniStatusUpdated=Signal(str);cryptoStatusUpdated=Signal(str)
        spaceActivityUpdated=Signal(str)
        def __init__(self):
            super().__init__();self.explorer=CryptoUiRuntime(self,snapshot=market.snapshot,ttl=.02);self.omni=CryptoUiRuntime(self,snapshot=omni_service.snapshot,ttl=.02)
            self.explorer_gate=None;self.marketplace_gate=None;self.explorer_calls=[];self.marketplace_calls=[]
            self.explorer.updated.connect(self.explorerStatusUpdated);self.omni.updated.connect(self.omniStatusUpdated)
            self.mp=CryptoUiRuntime(self,snapshot=marketplace_host.status_payload,ttl=.02);self.activity=CryptoUiRuntime(self,snapshot=crypto_activity.snapshot,ttl=.02)
            self.activity.updated.connect(self.spaceActivityUpdated)
        @Slot(result=str)
        def explorerStatus(self):return self.explorer.snapshot()
        @Slot(str,str,result=str)
        def explorerAction(self,name,raw):
            self.explorer_calls.append((name,json.loads(raw)));gate=self.explorer_gate
            def work():
                if gate and not gate.wait(5):raise ValueError('OFFLINE_UI_GATE_TIMEOUT')
                return market.action(name,raw)
            return self.explorer.submit(name,work)
        @Slot(result=str)
        def omniStatus(self):return self.omni.snapshot()
        @Slot(str,str,result=str)
        def omniAction(self,name,raw):return self.omni.submit(name,lambda:omni_service.action(name,raw))
        @Slot(result=str)
        def cryptoStatus(self):return '{}'
        @Slot(result=str)
        def marketplaceStatus(self):return self.mp.snapshot()
        @Slot(str,result=str)
        def marketplaceDiscover(self,raw):
            self.marketplace_calls.append(json.loads(raw));gate=self.marketplace_gate
            def work():
                if gate and not gate.wait(5):raise ValueError('OFFLINE_UI_GATE_TIMEOUT')
                return marketplace_host.discover(raw)
            return self.mp.submit('market_discover',work)
        @Slot(str,result=str)
        def marketplaceSelect(self,identifier):return self.mp.submit('market_select',lambda:marketplace_host.select_listing(identifier))
        @Slot(result=str)
        def spaceActivityStatus(self):return self.activity.snapshot()
    host=Host();engine=QQmlApplicationEngine();warnings=[];engine.warnings.connect(lambda errors:warnings.extend(e.toString() for e in errors))
    engine.rootContext().setContextProperty('testHost',host)
    path=directory/'fixture.qml';path.write_text('''import QtQuick
import QtQuick.Controls
import COMPONENTS
ApplicationWindow {width:1100;height:900;visible:true;color:'#111111'
CryptoSurface {objectName:'testCrypto';anchors.fill:parent;anchors.margins:16;surfaceHost:testHost}
MarketPriceChart {objectName:'testSampleChart';visible:false;width:600;height:400}
MarketExplorer {objectName:'testPendingExplorer';visible:false;width:600;height:400}
WalletPopup {objectName:'testPopup';x:26;y:70;visualWidth:350;visualHeight:720;surfaceHost:testHost;visible:false}
}'''.replace('COMPONENTS',json.dumps((PROJECT/'qml/components').as_uri())),encoding='utf-8')
    engine.load(QUrl.fromLocalFile(str(path)));assert engine.rootObjects(),warnings
    window=engine.rootObjects()[0];pane=window.findChild(QQuickItem,'testCrypto');explorer=pane.findChild(QQuickItem,'cryptoMarketExplorer')
    def js(item,code):
        expr=QQmlExpression(qmlContext(item),item,code);result=expr.evaluate();assert not expr.hasError(),expr.error().toString()
        return result[0] if isinstance(result,tuple) else result
    def wait_for(predicate):
        for _ in range(250):
            app.processEvents()
            if predicate():return
            QTest.qWait(20);time.sleep(.005)
        raise AssertionError('UI_TIMEOUT '+repr(warnings))
    def items(root):
        stack=[root]
        while stack:
            item=stack.pop();yield item;stack.extend(item.childItems())
    wallet=pane.findChild(QQuickItem,'omniWalletOverview')
    wait_for(lambda:js(wallet,'!busy && publicNetworks.length>0'))
    assert pane.property('page')=='WALLET' and wallet.property('dashboard')
    assert js(wallet,'noAccounts && listVisible && !connectOpen && summary.known_value_usd===null')
    window.grabWindow().save(str(directory/'dashboard-empty-1100.png'))
    sample_chart=window.findChild(QQuickItem,'testSampleChart')
    js(sample_chart,'series=({kind:"OBSERVED_SAMPLES_NOT_OHLC",prices:[100],times:[1000]})');assert not sample_chart.property('plottable')
    js(sample_chart,'series=({kind:"OBSERVED_SAMPLES_NOT_OHLC",prices:[100,100],times:[1000,1001]})');assert not sample_chart.property('plottable')
    js(sample_chart,'series=({kind:"OBSERVED_SAMPLES_NOT_OHLC",prices:[100,100],times:[1000,1600]})');assert sample_chart.property('plottable')
    pending_explorer=window.findChild(QQuickItem,'testPendingExplorer')
    js(pending_explorer,'state=({settings:{paused:true},ui_operation:{state:"running",name:"select"}});pendingRow=({id:"dex:fixture",sparkline:{prices:[100,101],period:"OBSERVED",observed_from:1000,observed_to:1001}})')
    pending_chart=pending_explorer.findChild(QQuickItem,'assetChartStage')
    assert js(pending_explorer,'curve.kind==="OBSERVED_SAMPLES_NOT_OHLC"')
    assert pending_chart.property('period')=='Observerad historik' and not pending_chart.property('plottable')
    js(pending_explorer,'pendingRow=({});state=({settings:{paused:true},sources:[{name:"CoinGecko",state:"NOT_FETCHED"}],ui_operation:{state:"done",name:"configure"}})')
    app.processEvents()
    assert any(i.property('text')=='CoinGecko · ej hämtad' for i in items(pending_explorer))
    pane.setProperty('page','MARKET');wait_for(lambda:js(explorer,'rows.length===100 && !busy'))
    graph=next(i for i in items(explorer) if i.objectName()=='tokenSparkline' and i.property('available'))
    samples=graph.property('samples');assert len(samples.toVariant() if hasattr(samples,'toVariant') else samples)<=128
    panel=pane.property('panel');assert panel.red()==panel.green()==panel.blue()
    for width in (430,1100):
        window.setWidth(width);QTest.qWait(220);window.grabWindow().save(str(directory/('market-'+str(width)+'.png')))
        frame=pane.findChild(QQuickItem,'cryptoPrimarySpace')
        nav=next(i for i in items(frame.property('navigationItem')) if i.objectName()=='spaceNavMARKET')
        location=nav.mapToItem(frame,QPointF(0,0))
        assert nav.isVisible() and 0<=location.x() and nav.width()<=frame.property('navigationWidth')
        assert pane.findChild(QQuickItem,'marketTokenList').height()>window.height()*.7
    target=next(item for item in items(explorer) if item.objectName()=='marketTokenRow' and item.property('index')==0)
    gate=threading.Event();host.explorer_gate=gate
    try:
        js(explorer,'run("refresh",{force:true})');assert explorer.property('busy')
        QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,target.mapToScene(QPointF(90,20)).toPoint());QTest.qWait(20)
        assert not explorer.property('detailOpen') and not any(name=='select' for name,_ in host.explorer_calls)
        js(explorer,'openAsset("eip155:1/native:ETH");closeDetail()')
        assert js(explorer,'!queuedAssetId && !detailOpen')
        js(explorer,'chartDays=30;openAsset("eip155:1/native:ETH");openAsset("'+store.NATIVE_SOL+'")')
        assert explorer.property('queuedAssetId')==store.NATIVE_SOL
        assert js(explorer,'!requestedAssetId && selected.name==="Väntar på pågående jobb…"')
        assert not any(name=='open_asset' for name,_ in host.explorer_calls)
    finally:
        host.explorer_gate=None;gate.set()
    wait_for(lambda:js(explorer,'!busy && !queuedAssetId && selected.asset_id==="'+store.NATIVE_SOL+'"'))
    assert [(name,args) for name,args in host.explorer_calls if name=='open_asset']==[('open_asset',{'asset_id':store.NATIVE_SOL})]
    assert explorer.property('chartDays')==7
    js(explorer,'closeDetail()')
    target=next(item for item in items(explorer) if item.objectName()=='marketTokenRow' and item.property('index')==0)
    point=target.mapToScene(QPointF(90,20)).toPoint();QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,point)
    wait_for(lambda:js(explorer,"selected.id==='coingecko:bitcoin' && !busy"));assert store.preference('selected_asset').endswith('native:BTC')
    chart=explorer.findChild(QQuickItem,'assetChartStage');assert explorer.width()*.9<chart.width()<=explorer.width() and chart.height()>explorer.height()*.55
    frame.setProperty('activityVisible',True);wait_for(lambda:js(frame,'liveEvents.length>0'))
    window.grabWindow().save(str(directory/'token-detail-1100.png'));frame.setProperty('activityVisible',False)
    pane.setProperty('page','MARKETPLACE');mp=pane.findChild(QQuickItem,'workspaceMarketplacePane')
    assert not mp.property('showPublic'), 'The marketplace starts with its local object catalog'
    source=mp.findChild(QQuickItem,'marketPublicSource')
    QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,source.mapToScene(QPointF(source.width()/2,source.height()/2)).toPoint())
    wait_for(lambda:js(mp,'!operationBusy && ((status.public_catalog || {}).rows || []).length===100'))
    public=mp.findChild(QQuickItem,'publicMarketplace');assert public.isVisible()
    wait_for(lambda:js(public,'!busy && !(state.preview_job || {}).worker_active'))
    window.grabWindow().save(str(directory/'mp-public-1100.png'))
    row=next(item for item in items(public) if item.objectName()=='marketReceiptTile' and item.property('index')==0)
    gate=threading.Event();host.marketplace_gate=gate
    try:
        js(mp,'discover({action:"refresh",provider:"coingecko",page:1})');assert mp.property('operationBusy')
        QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,row.mapToScene(QPointF(60,20)).toPoint());QTest.qWait(20)
        assert not public.property('detailOpen')
        assert not any(call.get('action')=='select' for call in host.marketplace_calls)
    finally:
        host.marketplace_gate=None;gate.set()
    wait_for(lambda:not mp.property('operationBusy'))
    row=next(item for item in items(public) if item.objectName()=='marketReceiptTile' and item.property('index')==0)
    QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,row.mapToScene(QPointF(60,20)).toPoint())
    wait_for(lambda:js(public,'!busy && !!selected.image_url'))
    window.grabWindow().save(str(directory/'mp-collection-1100.png'))
    pane.setProperty('page','MARKET')
    js(explorer,"detailOpen=false;run('search',{query:'SAME'})")
    wait_for(lambda:js(explorer,'!busy && rows.length===3'))
    row_id='dex:ethereum:0x'+'1'*40
    js(explorer,'run("select",{id:'+json.dumps(row_id)+'})')
    wait_for(lambda:js(explorer,"!busy && selected.provider==='dexscreener'"))
    js(explorer,'importVariant("eip155:1","0x'+'1'*40+'")')
    wait_for(lambda:js(explorer,'!busy && selected.registered'))
    asset_id='eip155:1/erc20:0x'+'1'*40;assert store.preference('selected_asset')==asset_id
    pane.setProperty('page','WALLET');wallet=pane.findChild(QQuickItem,'omniWalletOverview')
    wait_for(lambda:js(wallet,'!busy && publicNetworks.length>0'))
    wallet.setProperty('connectOpen',True);wallet.setProperty('connectChainId','eip155:1');wallet.findChild(QQuickItem,'walletConnectAddress').setProperty('text','0x'+'2'*40)
    connect=wallet.findChild(QQuickItem,'walletReadAccount');QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,connect.mapToScene(QPointF(connect.width()/2,connect.height()/2)).toPoint())
    wait_for(lambda:js(wallet,'!busy && (wallet.accounts || []).length===1 && (wallet.rows || []).some(function(r){return r.quantity==="42"})'))
    account=store.snapshot()['accounts'][0]['id']
    js(wallet,'run("refresh_balance",{asset_id:'+json.dumps(asset_id)+',account_id:'+json.dumps(account)+'})')
    wait_for(lambda:js(wallet,'!busy && (wallet.rows || []).some(function(r){return r.quantity==="42"})'))
    assert js(wallet,'wallet.known_value_usd==="268.00"')
    assert js(wallet,'summary.account_count===1 && summary.network_count===1 && summary.nonzero_count===2 && listVisible')
    assert wallet.findChild(QQuickItem,'walletTotalValue').property('text')=='$268.00'
    wallet.setProperty('accountFilter',account);assert js(wallet,'summary.known_value_usd==="268.00"')
    wallet.setProperty('chain','eip155:8453');assert js(wallet,'summary.known_value_usd===undefined && rows.length===0')
    wallet.setProperty('chain','');wallet.setProperty('accountFilter','')
    refresh=wallet.findChild(QQuickItem,'walletRefreshOverview')
    QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,refresh.mapToScene(QPointF(refresh.width()/2,refresh.height()/2)).toPoint())
    wait_for(lambda:js(wallet,'!busy && operation.name==="refresh_wallet" && operation.state==="done"'))
    assert js(wallet,'summary.known_value_usd==="268.00" && (wallet.events || []).some(function(e){return e.kind==="OVERVIEW_READ_COMPLETED"})')
    for width in (430,820,900,1100,1586):
        window.setHeight(992 if width==1586 else 900)
        window.setWidth(width);QTest.qWait(100)
        rail=wallet.findChild(QQuickItem,'walletFactsRail');primary=wallet.findChild(QQuickItem,'walletPrimaryContent')
        overview_header=wallet.findChild(QQuickItem,'walletOverviewHeader')
        if wallet.width()>=820:
            assert rail.isVisible() and primary.x()+primary.width()+wallet.property('railGap')+rail.width()==wallet.width()
            assert rail.x()>=primary.width() and rail.x()+rail.width()==wallet.width()
            assert overview_header.height()<(200 if wallet.property('mainWidth')>=900 else 320)
        else:
            assert not rail.isVisible() and primary.width()+2*wallet.property('edgeInset')==wallet.width()
        assert wallet.findChild(QQuickItem,'walletPositionList').height()>window.height()*.4
        window.grabWindow().save(str(directory/('wallet-'+str(width)+'.png')))
    # Context facts are available directly, even in the normal 900px desktop
    # pane. Hiding the dock returns its space; narrow panes open the same facts
    # without squeezing the holdings list or hiding the control in a menu.
    details=pane.findChild(QQuickItem,'spaceDetailsToggle')
    window.setWidth(900);QTest.qWait(60)
    assert details.isVisible() and details.property('checked')
    compact_main=primary.width()
    QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,details.mapToScene(QPointF(details.width()/2,details.height()/2)).toPoint())
    QTest.qWait(30)
    assert not rail.isVisible() and primary.width()>compact_main+200 and not details.property('checked')
    QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,details.mapToScene(QPointF(details.width()/2,details.height()/2)).toPoint())
    assert rail.isVisible() and details.property('checked')
    window.setWidth(430);QTest.qWait(60)
    narrow_main=primary.width()
    QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,details.mapToScene(QPointF(details.width()/2,details.height()/2)).toPoint())
    QTest.qWait(40)
    drawer=wallet.findChild(QObject,'walletFactsDrawer')
    assert drawer.property('visible') and not rail.isVisible() and primary.width()==narrow_main
    QTest.keyClick(window,Qt.Key_Escape);QTest.qWait(30)
    assert not drawer.property('visible')
    window.setWidth(1100);QTest.qWait(60)
    js(wallet,'openActions("receive",rows[0])')
    receiver=wallet.findChild(QQuickItem,'walletActions');assert receiver.isVisible()
    assert receiver.findChild(QQuickItem,'walletReceiveAddress').property('text')=='0x'+'2'*40
    assert js(receiver,'assetId!=="" && balance.quantity==="42"')
    for width in (430,1100,1586):
        window.setWidth(width);QTest.qWait(100)
        form=receiver.findChild(QQuickItem,'walletActionScroll');lane=receiver.findChild(QQuickItem,'walletAccountLane')
        assert form.width()>250 and form.x()+form.width()==receiver.width()
        assert not wallet.findChild(QQuickItem,'walletOverviewHeader').isVisible()
        assert lane.isVisible()==receiver.property('accountLaneVisible')
        window.grabWindow().save(str(directory/('wallet-receive-'+str(width)+'.png')))
    window.setWidth(1100);QTest.qWait(60)
    read_receive=receiver.findChild(QQuickItem,'walletReadReceive')
    assert read_receive is not None, 'The native balance action must remain a QQuickItem after the facts drawer closes'
    scroll=receiver.findChild(QQuickItem,'walletActionScroll')
    scroll.setProperty('contentY',max(0,read_receive.mapToItem(scroll,QPointF(0,0)).y()-scroll.height()+read_receive.height()+25));QTest.qWait(40)
    QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,read_receive.mapToScene(QPointF(read_receive.width()/2,read_receive.height()/2)).toPoint())
    wait_for(lambda:js(wallet,'!busy && operation.name==="refresh_balance" && operation.state==="done"'))
    receiver.setProperty('watching',True);assert receiver.property('watching')
    window.grabWindow().save(str(directory/'wallet-receive-1100.png'))
    wallet.setProperty('actionOpen',False);QTest.qWait(25);assert not receiver.property('watching')
    js(wallet,'openActions("create")');QTest.qWait(40)
    wizard=receiver.findChild(QQuickItem,'walletCreationWizard')
    assert wizard is not None and wizard.isVisible()
    assert wizard.property('phase')=='SETUP' and wizard.property('method')=='PAPER'
    assert wizard.property('wordCount')==24 and wizard.property('revealedCount')==0
    assert not receiver.findChild(QQuickItem,'walletActionScroll').isVisible()
    # Capture only public setup, then verify the real warning gate. This
    # navigation fixture must never generate words, keys or a wallet account.
    window.grabWindow().save(str(directory/'wallet-create-1100.png'))
    next_step=wizard.findChild(QQuickItem,'mnemonicNext')
    QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,next_step.mapToScene(QPointF(next_step.width()/2,next_step.height()/2)).toPoint())
    QTest.qWait(30)
    assert wizard.property('phase')=='WARNING' and wizard.property('revealedCount')==0
    assert not wizard.property('_sessionId')
    wallet.setProperty('actionOpen',False)
    window.setWidth(430);QTest.qWait(220);assert wallet.findChild(QQuickItem,'walletPositionList').height()>200
    window.grabWindow().save(str(directory/'dashboard-430.png'));window.setWidth(1100);QTest.qWait(80)
    position_list=wallet.findChild(QQuickItem,'walletPositionList')
    position=next(i for i in items(position_list) if i.objectName()=='walletAssetRow' and i.property('index')==0)
    QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,position.mapToScene(QPointF(80,20)).toPoint());wait_for(lambda:js(wallet,'!busy && actionOpen && !detailOpen'))
    assert receiver.property('accountId')==position.property('accountTarget') and receiver.property('assetId')==position.property('assetTarget')
    assert receiver.property('page')=='receive' and receiver.findChild(QQuickItem,'walletActionModes').isVisible()
    window.grabWindow().save(str(directory/'wallet-asset-1100.png'))
    asset_market=receiver.findChild(QQuickItem,'walletShowAssetMarket')
    QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,asset_market.mapToScene(QPointF(asset_market.width()/2,asset_market.height()/2)).toPoint())
    wait_for(lambda:js(explorer,'!busy && detailOpen && selected.asset_id==="'+asset_id+'"'))
    assert pane.property('page')=='MARKET';pane.setProperty('page','WALLET')
    wallet.setProperty('showLab',True);wait_for(lambda:js(wallet,'rows.length===4'))
    js(wallet,'choose(rows[0])');assert wallet.property('detailOpen') and not wallet.property('actionOpen')
    wallet.setProperty('detailOpen',False)
    js(wallet,'selected=rows[0];run("lab_send",{sender:0,recipient:1,amount:"2"})');wait_for(lambda:js(wallet,'!busy && state.lab.pending===1'))
    js(wallet,'run("lab_commit",{})');wait_for(lambda:js(wallet,'!busy && state.lab.height===1'))
    public_holdings=wallet.findChild(QQuickItem,'walletPublicHoldings');QTest.qWait(40)
    QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,public_holdings.mapToScene(QPointF(public_holdings.width()/2,public_holdings.height()/2)).toPoint())
    assert not wallet.property('showLab')
    popup=window.findChild(QQuickItem,'testPopup');popup.setProperty('visible',True);QTest.qWait(50)
    assert popup.property('unifiedWallet') and not popup.property('legacyToolsOpen')
    QTest.qWait(200);window.grabWindow().save(str(directory/'wallet-popup-350.png'))
    assert not warnings,warnings
    destination=os.environ.get('GG_EXPLORER_UI_EVIDENCE')
    if destination:
        import shutil
        Path(destination).mkdir(parents=True,exist_ok=True)
        for image in directory.glob('*.png'):shutil.copy2(image,Path(destination)/image.name)
    print(json.dumps({'status':'PASS','default_account_dashboard':True,'tokens':100,'dex_same_symbol_two_networks':True,'wallet_quantity_exact':'42','gg_lab_transfer':True,'warnings':len(warnings)}))
    host.explorer.close();host.omni.close();host.mp.close();host.activity.close();window.close();engine.deleteLater();app.processEvents();request_patch.stop();provider_patch.stop();image_patch.stop()


class ExplorerUi(unittest.TestCase):
    def test_real_navigation_and_shared_wallet(self):
        with tempfile.TemporaryDirectory(prefix='gg-explorer-ui-') as temporary:
            directory=Path(temporary);env=os.environ.copy();env.update(QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software',QT_QUICK_CONTROLS_STYLE='Basic',GG_DESKTOP_STATE_ROOT=str(directory/'state'),GG_DESKTOP_DATA_ROOT=str(directory/'data'))
            result=subprocess.run([sys.executable,'-B',str(Path(__file__).resolve()),'--fixture',temporary],cwd=PROJECT,env=env,capture_output=True,text=True,timeout=40)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr);print(result.stdout.strip())


if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--fixture':fixture(Path(sys.argv[2]))
    else:unittest.main()
