"""Real Qt controls and asynchronous service integration at phone/desktop widths."""
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
    import threading
    from PySide6.QtCore import QObject,QPoint,QPointF,Slot,QUrl,Qt
    from PySide6.QtGui import QGuiApplication,QFontDatabase,QFont
    from PySide6.QtQml import QQmlApplicationEngine,QQmlExpression,qmlContext
    from PySide6.QtQuick import QQuickItem
    from PySide6.QtTest import QTest
    from backend import omni_service,omni_lab,marketplace_host
    from backend.crypto_ui_runtime import CryptoUiRuntime
    app=QGuiApplication([])
    if os.name=='nt':
        for name in ('consola.ttf','consolab.ttf','seguisym.ttf'):QFontDatabase.addApplicationFont(str(Path(os.environ.get('SystemRoot','C:/Windows'))/'Fonts'/name))
    QFont.insertSubstitution('monospace','Consolas' if os.name=='nt' else 'DejaVu Sans Mono')
    app.setFont(QFont('Consolas' if os.name=='nt' else 'DejaVu Sans Mono'))
    warnings=[];engine=QQmlApplicationEngine();engine.warnings.connect(lambda errors:warnings.extend(e.toString() for e in errors))
    omni_lab.create()
    class Host(QObject):
        def __init__(self):
            super().__init__();self.omni=CryptoUiRuntime(self,snapshot=omni_service.snapshot,ttl=.02);self.mp=CryptoUiRuntime(self,snapshot=marketplace_host.status_payload,ttl=.02)
            self.fast_image=False;self.select_gate=None;self.selected_calls=[]
        @Slot(result=str)
        def omniStatus(self):return self.omni.snapshot()
        @Slot(str,str,result=str)
        def omniAction(self,name,raw):return self.omni.submit(name,lambda:omni_service.action(name,raw))
        @Slot(result=str)
        def marketplaceStatus(self):return self.mp.snapshot()
        @Slot(str,result=str)
        def marketplaceList(self,raw):return self.mp.submit('market_list',lambda:marketplace_host.list_item(raw))
        @Slot(str,result=str)
        def marketplaceImportImage(self,source):
            raw=self.mp.submit('market_image',lambda:marketplace_host.import_image(source))
            if self.fast_image:
                # Force the valid scheduler case where the slot returns a
                # completed operation without QML seeing its running notice.
                until=time.monotonic()+3
                while self.mp._running and time.monotonic()<until:time.sleep(.001)
                assert not self.mp._running
                raw=self.mp.snapshot()
            return raw
        @Slot(str,result=str)
        def marketplaceSelect(self,identifier):
            self.selected_calls.append(identifier);gate=self.select_gate
            def work():
                if gate and not gate.wait(5):raise ValueError('OFFLINE_UI_GATE_TIMEOUT')
                return marketplace_host.select_listing(identifier)
            return self.mp.submit('market_select',work)
    host=Host();engine.rootContext().setContextProperty('testHost',host)
    qml='''import QtQuick
import QtQuick.Controls
import COMPONENTS
ApplicationWindow { width:900;height:800;visible:true;color:'#111111'
OmniSurface { objectName:'testHub';anchors.fill:parent;anchors.margins:16;surfaceHost:testHost }
MarketplaceSurface { objectName:'testMarket';anchors.fill:parent;surfaceHost:testHost;visible:false }
}'''.replace('COMPONENTS',json.dumps((PROJECT/'qml/components').as_uri()))
    path=directory/'fixture.qml';path.write_text(qml,encoding='utf-8');engine.load(QUrl.fromLocalFile(str(path)))
    assert engine.rootObjects(),warnings
    window=engine.rootObjects()[0];hub=window.findChild(QQuickItem,'testHub');market=window.findChild(QQuickItem,'testMarket')
    def wait_for(predicate):
        for _ in range(200):
            app.processEvents()
            if predicate():return
            QTest.qWait(25)
            time.sleep(.01)
        raise AssertionError('UI_TIMEOUT '+host.mp.snapshot()[-900:]+' FORM '+str(market.property('formError'))+' PAGE '+str(market.property('page'))+' WARNINGS '+repr(warnings))
    def js(item,expression):
        expr=QQmlExpression(qmlContext(item),item,expression);result=expr.evaluate()
        assert not expr.hasError(),expr.error().toString()
        return result[0] if isinstance(result,tuple) else result
    def items(root):
        stack=[root]
        while stack:
            item=stack.pop()
            if not isinstance(item,QQuickItem):continue
            yield item
            if hasattr(item,'childItems'):stack.extend(item.childItems())
    wait_for(lambda:len(hub.property('assets').toVariant())>=8)
    picker=hub.findChild(QQuickItem,'omniAssetPicker')
    point=picker.mapToScene(QPointF(picker.width()/2,picker.height()/2)).toPoint()
    QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,point);QTest.qWait(40)
    QTest.keyClick(window,Qt.Key_Home);QTest.keyClick(window,Qt.Key_Down);QTest.keyClick(window,Qt.Key_Return)
    wait_for(lambda:js(hub,'!busy && selectedId===assets[1].id'))
    for width in (360,900):
        window.setWidth(width);QTest.qWait(40)
        for page in ('WALLET','NFT','BOTS','NODE','LAB','ACTIVITY'):
            hub.setProperty('page',page);QTest.qWait(30)
            assert hub.width()==width-32
        hub.setProperty('page','LAB');QTest.qWait(30)
        window.grabWindow().save(str(directory/('omni-'+str(width)+'.png')))
    js(hub,"run('lab_send',{})");wait_for(lambda:js(hub,'!busy && lab.pending===1'))
    js(hub,"run('lab_commit',{})");wait_for(lambda:js(hub,'!busy && lab.height===1'))
    js(hub,"run('configure_lab',{participating:true})");wait_for(lambda:js(hub,'!busy && lab.participating'))
    js(hub,"run('transport_test',{loss:true})");wait_for(lambda:js(hub,'!busy && lab.retry_packets===1'))
    js(hub,"run('retry_transport',{})");wait_for(lambda:js(hub,'!busy && lab.pending===1'))
    hub.setProperty('visible',False);market.setProperty('visible',True)
    wait_for(lambda:js(market,'status.listings !== undefined'))
    # A real empty library still exposes the passport structure on a normal
    # desktop pane, without claiming that an object or receipt was registered.
    window.setWidth(950);window.setHeight(900);market.setProperty('catalogScope','LOCAL');market.setProperty('page','CATALOG');QTest.qWait(80)
    browser=market.findChild(QQuickItem,'marketVisualBrowser')
    visual_passport=browser.findChild(QQuickItem,'marketBrowserPassport')
    adjacent=browser.findChild(QQuickItem,'marketAdjacentObjectPass')
    assert browser.property('showPassport') and adjacent.isVisible()
    assert not visual_passport.property('hasReceipt')
    empty_tree=visual_passport.findChild(QQuickItem,'marketReceiptTree')
    assert js(empty_tree,"nodes.map(function(n){return n.key}).join(',')")=="contents,origin,receipt"
    assert js(empty_tree,"JSON.stringify(nodes).indexOf('Lokalt registrerat')<0")
    window.grabWindow().save(str(directory/'market-empty-950.png'))
    register_from_pass=browser.findChild(QQuickItem,'marketRegisterFromPass')
    js(adjacent,'contentY=Math.max(0,contentHeight-height)');QTest.qWait(30)
    QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,register_from_pass.mapToScene(QPointF(80,register_from_pass.height()/2)).toPoint())
    assert market.property('page')=='REGISTER'
    for width in (360,900):
        window.setWidth(width)
        for page in ('CATALOG','REGISTER','RECEIPT','OMNI'):
            market.setProperty('page',page);QTest.qWait(20)
    market.setProperty('page','REGISTER')
    title=market.findChild(QQuickItem,'marketTitleField');price=market.findChild(QQuickItem,'marketPriceField')
    source=(PROJECT/'qml/assets/knowledge-cell.png').as_uri()
    js(market,'importImage('+json.dumps(source)+')')
    wait_for(lambda:js(market,'!operationBusy && !!draftImage.id'))
    first_image=js(market,'draftImage.id')
    from PIL import Image
    replacement=directory/'replacement.png';Image.new('RGB',(4,4),(30,40,50)).save(replacement)
    host.fast_image=True
    js(market,'importImage('+json.dumps(replacement.as_uri())+')')
    assert js(market,'operation.state==="done" && draftImage.id===status.draft_media.id && !awaitingImage')
    assert js(market,'draftImage.id')!=first_image
    replacement_image=js(market,'draftImage.id')
    js(market,'draftImage=({});refresh()');assert js(market,'!draftImage.id')
    js(market,'importImage('+json.dumps(replacement.as_uri())+')')
    assert js(market,'draftImage.id')==replacement_image
    host.fast_image=False
    js(market,'importImage('+json.dumps(source)+')')
    wait_for(lambda:js(market,'!operationBusy && draftImage.id==='+json.dumps(first_image)))
    title.setProperty('text','Cellmodell · undervisningsmaterial');price.setProperty('text','1.000000000000000001');market.setProperty('settlementAssetId','eip155:56/native:BNB')
    market.setProperty('linkNft',True)
    source_chain=market.findChild(QQuickItem,'marketNftSourceChain')
    js(source_chain,"currentIndex=model.map(function(n){return n.id}).indexOf('eip155:1')")
    market.findChild(QQuickItem,'marketNftCollection').setProperty('text','0x'+'1'*40)
    market.findChild(QQuickItem,'marketNftTokenId').setProperty('text',str(2**200))
    market.findChild(QQuickItem,'marketMakerField').setProperty('text','Isolerad testverkstad')
    market.findChild(QQuickItem,'marketOriginField').setProperty('text','Deklarerad testkälla')
    js(market,"draftParts=[{id:'unavailable-part-fixture',symbol:'C',title:'Modellmaterial (test)',mass_g:150}];submitList()")
    wait_for(lambda:js(market,"!operationBusy && page==='RECEIPT' && status.listing_count===1"))
    assert js(market,"selected.price_label==='1.000000000000000001 BNB'")
    first_listing=js(market,'selected.id')
    assert js(market,"selected.nft_binding.chain_id==='eip155:1' && selected.network==='eip155:56'")
    js(market,"networkFilter='eip155:1';currencyFilter='eip155:56/native:BNB'")
    assert js(market,'listings.length===1')
    from backend import marketplace_protocols
    from unittest.mock import patch
    inspector=market.findChild(QQuickItem,'marketNftInspector')
    with patch.object(marketplace_protocols,'inspect',return_value={}) as inspect_call:
        market.setProperty('page','NFT')
        binding=js(market,'JSON.stringify(selected.nft_binding)')
        js(inspector,'inspectBinding('+binding+')')
        wait_for(lambda:js(inspector,'!busy && nftSourceChainId==="eip155:1"') and inspect_call.call_count==1)
        assert inspect_call.call_args.args[:4]==('eip155:1','erc721','0x'+'1'*40,str(2**200))
    market.setProperty('page','RECEIPT')
    assert title.property('text')==''
    passport=market.findChild(QQuickItem,'marketplaceVisualPassport')
    assert passport is not None
    for width in (360,900):
        window.setWidth(width);passport.setProperty('section','materials');QTest.qWait(150)
        window.grabWindow().save(str(directory/('passport-'+str(width)+'.png')))
    assert passport.property('section')=='materials'
    market.setProperty('page','CATALOG');window.setWidth(1600);window.setHeight(1000);QTest.qWait(160)
    browser=market.findChild(QQuickItem,'marketVisualBrowser')
    visual_passport=browser.findChild(QQuickItem,'marketBrowserPassport')
    assert browser is not None and browser.isVisible() and not market.property('catalogFiltersOpen')
    assert browser.property('showCategories') and browser.property('showPassport')
    adjacent=browser.findChild(QQuickItem,'marketAdjacentObjectPass');grid=browser.findChild(QQuickItem,'marketCatalogGrid')
    assert adjacent.isVisible() and grid.width()>adjacent.width()
    assert adjacent.mapToScene(QPointF(adjacent.width(),0)).x()<=market.mapToScene(QPointF(market.width(),0)).x()+1
    tree=visual_passport.findChild(QQuickItem,'marketReceiptTree')
    assert tree is not None and js(tree,"nodes.map(function(n){return n.key}).join(',')")=="contents,origin,receipt"
    before=js(tree,'visibleNodes.length')
    heading=next(i for i in items(tree) if i.objectName()=='marketTreeHeading' and js(i,'modelData.key')=='contents')
    QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,heading.mapToScene(QPointF(80,heading.height()/2)).toPoint());QTest.qWait(30)
    assert js(tree,'collapsed.contents===true && visibleNodes.length<'+str(before))
    js(market,'var value=JSON.parse(statusJson);value.visualTestRevision=1;statusJson=JSON.stringify(value)')
    assert js(tree,'collapsed.contents===true')
    heading=next(i for i in items(tree) if i.objectName()=='marketTreeHeading' and js(i,'modelData.key')=='contents')
    QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,heading.mapToScene(QPointF(80,heading.height()/2)).toPoint());QTest.qWait(30)
    assert js(tree,'!collapsed.contents && visibleNodes.length==='+str(before))
    assert js(tree,"JSON.stringify(nodes).indexOf('Deklarerad testkälla')>=0 && JSON.stringify(nodes).indexOf('Isolerad testverkstad')>=0")
    missing_part=next(i for i in items(tree) if i.objectName()=='marketTreeNode' and js(i,"modelData.node.label.indexOf('unavailable-part-fixture')>=0"))
    assert not missing_part.property('activeFocusOnTab')
    assert js(tree,"visibleNodes.every(function(entry){return entry.node.objectId!=='unavailable-part-fixture'})")
    calls_before=len(host.selected_calls)
    QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,missing_part.mapToScene(QPointF(70,missing_part.height()/2)).toPoint());QTest.qWait(30)
    assert len(host.selected_calls)==calls_before
    js(adjacent,'contentY=Math.max(0,contentHeight-height)');QTest.qWait(40)
    open_pass=browser.findChild(QQuickItem,'marketOpenObjectPass')
    QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,open_pass.mapToScene(QPointF(80,open_pass.height()/2)).toPoint())
    wait_for(lambda:js(market,'!operationBusy && page==="RECEIPT" && selected && selected.id==='+json.dumps(first_listing)))
    market.setProperty('page','CATALOG');js(adjacent,'contentY=0');QTest.qWait(40)
    window.grabWindow().save(str(directory/'market-atlas-1600.png'))
    tool=market.findChild(QQuickItem,'marketToolsButton')
    QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,tool.mapToScene(QPointF(tool.width()/2,tool.height()/2)).toPoint());QTest.qWait(30)
    tools=market.findChild(QObject,'marketToolsMenu');assert tools is not None and tools.property('visible')
    QTest.keyClick(window,Qt.Key_Escape);QTest.qWait(20)
    assert not tools.property('visible')
    market.setProperty('page','REGISTER');title.setProperty('text','Keep failed draft');price.setProperty('text','1.0000000000000000001');js(market,'submitList()')
    wait_for(lambda:js(market,'!operationBusy && formError.length>0'))
    assert title.property('text')=='Keep failed draft'
    second_payload=marketplace_host.list_item({'title':'Second isolated fixture','kind':'SERVICE','category':'SERVICE','material':'UNKNOWN','price':'0','settlement_asset_id':'eip155:56/native:BNB'})
    assert not second_payload.get('error'),second_payload.get('error')
    second_listing=second_payload['selected']['id']
    third_payload=marketplace_host.list_item({'title':'Wood tool fixture','kind':'OBJECT','category':'TOOL','material':'WOOD','price':'0','settlement_asset_id':'eip155:56/native:BNB'})
    assert not third_payload.get('error'),third_payload.get('error')
    js(market,'selectRow('+json.dumps(first_listing)+')')
    wait_for(lambda:js(market,'!operationBusy && selected && selected.id==='+json.dumps(first_listing)))
    js(market,'clearCatalogFilters();page="CATALOG";catalogScope="LOCAL"')
    QTest.qWait(100)
    assert js(browser,"categoryRows.map(function(r){return r.id}).sort().join(',')")=="ITEM,SERVICE,TOOL"
    material_choices=[i for i in items(browser) if i.objectName()=='marketMaterialChoice' and js(i,'modelData.id')=='WOOD']
    assert material_choices,'WOOD facet missing from actual registered fixture metadata'
    material=material_choices[0]
    QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,material.mapToScene(QPointF(material.width()/2,material.height()/2)).toPoint());QTest.qWait(30)
    assert js(market,'materialFilter==="WOOD" && listings.length===1 && listings[0].material==="WOOD"')
    js(market,'materialFilter=""')
    category=next(i for i in items(browser) if i.objectName()=='marketCategoryChoice' and js(i,'modelData.id')=='services-all')
    QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,category.mapToScene(QPointF(category.width()/2,category.height()/2)).toPoint());QTest.qWait(30)
    assert js(market,'facetKindFilter==="SERVICE" && listings.length===1 && listings[0].kind==="SERVICE"')
    js(market,'applyFacet("all","","")');QTest.qWait(30)
    facets=browser.findChild(QQuickItem,'marketCategoryNavigation')
    objects_group=next(i for i in items(facets) if i.objectName()=='marketFacetGroup' and js(i,'modelData.id')=='objects')
    facet_count=js(facets,'nodes.length')
    QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,objects_group.mapToScene(QPointF(60,objects_group.height()/2)).toPoint());QTest.qWait(30)
    assert js(facets,'collapsed.objects && nodes.length<'+str(facet_count))
    objects_group=next(i for i in items(facets) if i.objectName()=='marketFacetGroup' and js(i,'modelData.id')=='objects')
    QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,objects_group.mapToScene(QPointF(60,objects_group.height()/2)).toPoint());QTest.qWait(30)
    assert js(facets,'!collapsed.objects && nodes.length==='+str(facet_count))
    carbon=next(i for i in items(facets) if i.objectName()=='marketMaterialChoice' and js(i,'modelData.id')=='C')
    QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,carbon.mapToScene(QPointF(60,carbon.height()/2)).toPoint());QTest.qWait(30)
    assert js(market,'materialFilter==="C" && listings.length===1 && listings[0].id==='+json.dumps(first_listing))
    js(market,'applyFacet("all","","")');QTest.qWait(30)
    timeline=browser.findChild(QQuickItem,'marketLocalTimeline')
    assert js(timeline,'recent.length===3 && recent.every(function(e){return e.kind==="LIST"})')
    image_tile=next(i for i in items(browser) if i.objectName()=='marketReceiptTile' and js(i,'!!row.image_url'))
    card_image=image_tile.findChild(QQuickItem,'marketCardImage');declared_image=js(image_tile,'row.image_url')
    warnings_before=len(warnings)
    card_image.setProperty('source',QUrl.fromLocalFile(str(directory/'missing-object-image.png')))
    wait_for(lambda:js(card_image,'status===3'))
    placeholder=image_tile.findChild(QQuickItem,'marketImagePlaceholder')
    assert placeholder.isVisible() and placeholder.property('text')=='Bild kunde inte läsas'
    assert js(image_tile,'row.image_url')==declared_image
    assert all('missing-object-image.png' in message for message in warnings[warnings_before:]),warnings[warnings_before:]
    del warnings[warnings_before:]
    card_image.setProperty('source',QUrl(declared_image));wait_for(lambda:js(card_image,'status===1'))
    public_source=market.findChild(QQuickItem,'marketPublicSource');local_source=market.findChild(QQuickItem,'marketLocalSource')
    QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,public_source.mapToScene(QPointF(70,20)).toPoint());QTest.qWait(30)
    assert js(market,'showPublic && workspaceNetworkLabel==="PUBLIK LÄSNING"')
    assert market.findChild(QQuickItem,'publicMarketplace').isVisible()
    QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,local_source.mapToScene(QPointF(40,20)).toPoint());QTest.qWait(30)
    assert js(market,'!showPublic && listings.length===3')
    window.grabWindow().save(str(directory/'market-native-categories-1600.png'))
    for width in (900,1100):
        window.setWidth(width);QTest.qWait(100)
        assert browser.property('showPassport') and adjacent.isVisible()
        assert grid.width()>=360 and adjacent.width()>=238 and grid.property('columns')==3
        assert grid.mapToScene(QPointF(grid.width(),0)).x()<adjacent.mapToScene(QPointF(0,0)).x()
        window.grabWindow().save(str(directory/('market-atlas-'+str(width)+'.png')))
    window.setWidth(1600);QTest.qWait(50)
    gate=threading.Event();host.select_gate=gate
    try:
        js(market,'selectRow('+json.dumps(second_listing)+')')
        assert js(market,'operationBusy && selected===null')
        js(market,'page="CATALOG";catalogMode="GRID";catalogScope="LOCAL"')
        QTest.qWait(40)
        tile=next(i for i in items(market) if i.objectName()=='marketReceiptTile' and js(i,'row.id')==first_listing)
        QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,tile.mapToScene(QPointF(60,20)).toPoint());QTest.qWait(20)
        assert market.property('page')=='CATALOG' and market.property('requestedReceiptId')==second_listing
        assert host.selected_calls[-1]==second_listing
    finally:
        host.select_gate=None;gate.set()
    wait_for(lambda:js(market,'!operationBusy && selected && selected.id==='+json.dumps(second_listing)))
    js(market,'selectRow("missing-isolated-listing")')
    wait_for(lambda:js(market,'!operationBusy && operation.state==="error"'))
    assert js(market,'selected===null && requestedReceiptId==="missing-isolated-listing"')
    js(market,"formError=''; var value=JSON.parse(statusJson);var sample=value.listings[0];value.listings=[];for(var i=0;i<2000;i++)value.listings.push(Object.assign({},sample,{id:sample.id+'-fixture-'+i}));statusJson=JSON.stringify(value);catalogMode='GRID';page='CATALOG'")
    QTest.qWait(150)
    grid=browser.findChild(QQuickItem,'marketCatalogGrid')
    assert grid.property('count')==2000
    rendered=js(grid,"Array.prototype.filter.call(contentItem.children,function(i){return i.objectName==='marketReceiptTile'}).length")
    assert 0<rendered<60
    for width in (360,900,1600):
        window.setWidth(width);timeline.setProperty('expanded',width>=700);QTest.qWait(160);window.grabWindow().save(str(directory/('catalog-'+str(width)+'.png')))
        assert grid.mapToScene(QPointF(grid.width(),0)).x()<=market.mapToScene(QPointF(market.width(),0)).x()+1
        if width==360:
            assert not adjacent.isVisible()
            assert browser.findChild(QQuickItem,'marketCompactCategory').isVisible()
            assert js(market.findChild(QQuickItem,'marketCatalogRegister'),'!contentItem.truncated')
            compact=browser.findChild(QQuickItem,'marketCompactCategory')
            QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,compact.mapToScene(QPointF(60,compact.height()/2)).toPoint());QTest.qWait(30)
            assert browser.findChild(QObject,'marketFacetPopup').property('visible')
            QTest.keyClick(window,Qt.Key_Escape);QTest.qWait(20)
            toggle=browser.findChild(QQuickItem,'marketTimelineToggle')
            QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,toggle.mapToScene(QPointF(80,15)).toPoint());QTest.qWait(30)
            assert timeline.property('expanded') and timeline.height()>32
            QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,toggle.mapToScene(QPointF(80,15)).toPoint());QTest.qWait(30)
            assert not timeline.property('expanded')
    assert not warnings,warnings
    destination=os.environ.get('GG_OMNI_UI_EVIDENCE')
    if destination:
        import shutil
        Path(destination).mkdir(parents=True,exist_ok=True)
        for pattern in ('omni-*.png','passport-*.png','catalog-*.png','market-atlas-*.png','market-native-*.png','market-empty-*.png'):
            for image in directory.glob(pattern):shutil.copy2(image,Path(destination)/image.name)
    print(json.dumps({'status':'PASS','widths':[360,900,1600],'real_qml':True,'native_categories':True,'adjacent_object_pass':True,'virtual_catalog':2000,'async_actions':True,'draft_retained_on_error':True,'warnings':len(warnings)}))
    host.omni.close();host.mp.close();window.close();engine.deleteLater();app.processEvents()


class OmniUi(unittest.TestCase):
    def test_real_qml_service_and_marketplace(self):
        with tempfile.TemporaryDirectory(prefix='gg-omni-ui-') as temporary:
            directory=Path(temporary);env=os.environ.copy();env.update(QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software',QT_QUICK_CONTROLS_STYLE='Basic',GG_DESKTOP_STATE_ROOT=str(directory/'state'),GG_DESKTOP_DATA_ROOT=str(directory/'data'))
            result=subprocess.run([sys.executable,'-B',str(Path(__file__).resolve()),'--fixture',temporary],cwd=PROJECT,env=env,capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            print(result.stdout.strip())


if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--fixture':fixture(Path(sys.argv[2]))
    else:unittest.main()
