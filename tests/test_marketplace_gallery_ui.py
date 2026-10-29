"""Native MP must keep the frozen catalog topology for local and public data.

The concept's illustration regions are supplied by an in-memory test image
provider. They are never registered as real goods or installed as sample data.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PROJECT=Path(__file__).resolve().parents[1]


def fixture(directory):
    import json
    from PySide6.QtCore import QObject,Slot,QUrl,QPointF,QRect,QSize,Qt
    from PySide6.QtGui import QGuiApplication,QFont,QFontDatabase,QImage
    from PySide6.QtQml import QQmlApplicationEngine,QQmlExpression,qmlContext
    from PySide6.QtQuick import QQuickItem,QQuickImageProvider
    from PySide6.QtTest import QTest
    app=QGuiApplication([])
    if os.name=='nt':
        for font in ('consola.ttf','consolab.ttf','seguisym.ttf'):
            QFontDatabase.addApplicationFont(str(Path(os.environ.get('SystemRoot','C:/Windows'))/'Fonts'/font))
    QFont.insertSubstitution('monospace','Consolas' if os.name=='nt' else 'DejaVu Sans Mono')
    app.setFont(QFont('Consolas' if os.name=='nt' else 'DejaVu Sans Mono'))
    class ConceptProvider(QQuickImageProvider):
        def __init__(self):
            super().__init__(QQuickImageProvider.ImageType.Image)
            self.reference=QImage(str(PROJECT/'knowledge/design/crypto-space-v1/marketplace.png'))
            assert not self.reference.isNull()
        def requestImage(self,identifier,size,requestedSize):
            regions=[(265,183,266,246),(551,182,280,247),(854,184,289,244),
                     (266,506,266,218),(556,508,276,216),(854,507,288,215)]
            image=self.reference.copy(QRect(*regions[int(identifier)%len(regions)]))
            size.setWidth(image.width());size.setHeight(image.height())
            return image
    names=['Björkstol','Snickarhammare','Svensk flora','Cykelvev','Kaffekopp','Cykelservice']
    materials=['WOOD','METAL','FABRIC','METAL','STONE','UNKNOWN']
    local=[{'id':'visual-fixture-'+str(i),'title':name,'kind':'SERVICE' if i==5 else 'OBJECT',
            'category':'SERVICE' if i==5 else 'TOOL' if i in (1,3) else 'ITEM','material':materials[i],
            'image_url':'image://concept/'+str(i),'price_label':'Illustrativt prov','origin':'Deklarerad testkälla',
            'maker':'Illustrativ fixtur','owner':'Ej verifierad','composition':[],'previous_lives':[],
            'status':'LISTED','description':'Illustrativt kontrollmaterial, inget verkligt försäljningsobjekt.'} for i,name in enumerate(names)]
    public=[{'id':'coingecko:visual-'+str(i),'provider_id':'visual-'+str(i),'provider':'coingecko',
             'name':'Illustrativ samling '+str(i+1),'symbol':'TEST','platform':'ethereum' if i<3 else 'solana',
             'chain_id':'eip155:1' if i<3 else 'solana:test-fixture','collection':'0x'+str(i+1)*40,
             'kind':'COLLECTION','image_url':'image://concept/'+str(i),'source':'OFFLINE · illustrativ källa',
             'floor_usd':None,'total_supply':'','volume_24h_usd':None,'can_inspect':False} for i in range(6)]
    class Host(QObject):
        def __init__(self):
            super().__init__();self.calls=[]
            self.data={'listings':local,'listing_count':len(local),'selected':local[0],
                'ledger':[{'ts':1700000000+i,'kind':'READ','listing_id':row['id']} for i,row in enumerate(local)],
                'public_catalog':{'provider':'coingecko','page':1,'rows':public,'selected':None,'source_state':'CURRENT',
                    'observed_at':1700000000,'events':[{'ts':1700000000,'kind':'PUBLIC_DIRECTORY_READ','message':'Illustrativ katalog läst.'}],
                    'preview_job':{'state':'idle','worker_active':False}},'ui_operation':{}}
        @Slot(result=str)
        def marketplaceStatus(self):return json.dumps(self.data)
        @Slot(str,result=str)
        def marketplaceSelect(self,identifier):
            self.calls.append(('local',identifier));self.data['selected']=next(r for r in local if r['id']==identifier)
            return self.marketplaceStatus()
        @Slot(str,result=str)
        def marketplaceDiscover(self,raw):
            args=json.loads(raw);self.calls.append(('public',args))
            if args['action']=='select':self.data['public_catalog']['selected']=next(r for r in public if r['id']==args['id'])
            if args['action']=='stop_previews':self.data['public_catalog']['preview_job']={'state':'cancelled','worker_active':False}
            return self.marketplaceStatus()
        @Slot(str,result=str)
        def tmogCopy(self,value):return ''
    host=Host();engine=QQmlApplicationEngine();warnings=[]
    engine.warnings.connect(lambda errors:warnings.extend(e.toString() for e in errors))
    provider=ConceptProvider();engine.addImageProvider('concept',provider);engine.rootContext().setContextProperty('testHost',host)
    path=directory/'fixture.qml'
    path.write_text('''import QtQuick
import QtQuick.Controls
import COMPONENTS
ApplicationWindow {width:970;height:700;visible:true;color:'#111111'
MarketplaceSurface {objectName:'gallerySurface';anchors.fill:parent;surfaceHost:testHost}
}'''.replace('COMPONENTS',json.dumps((PROJECT/'qml/components').as_uri())),encoding='utf-8')
    engine.load(QUrl.fromLocalFile(str(path)));assert engine.rootObjects(),warnings
    window=engine.rootObjects()[0];market=window.findChild(QQuickItem,'gallerySurface')
    def js(item,code):
        expression=QQmlExpression(qmlContext(item),item,code);value=expression.evaluate()
        assert not expression.hasError(),expression.error().toString()
        return value[0] if isinstance(value,tuple) else value
    def walk(item):
        yield item
        for child in item.childItems():yield from walk(child)
    def click(item):
        QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,item.mapToScene(QPointF(item.width()/2,item.height()/2)).toPoint());QTest.qWait(50)
    QTest.qWait(180);assert not market.property('showPublic')
    records=[];source_x={}
    for scope in ('LOCAL','PUBLIC'):
        market.setProperty('catalogScope',scope);QTest.qWait(100)
        browser=market.findChild(QQuickItem,'marketVisualBrowser' if scope=='LOCAL' else 'publicCollectionBrowser')
        grid=browser.findChild(QQuickItem,'marketCatalogGrid');adjacent=browser.findChild(QQuickItem,'marketAdjacentObjectPass')
        timeline=browser.findChild(QQuickItem,'marketLocalTimeline')
        for width,height in ((970,700),(1586,992),(360,700)):
            window.setWidth(width);window.setHeight(height);QTest.qWait(180)
            assert grid.isVisible() and grid.property('count')==6
            source_row=market.findChild(QQuickItem,'marketSearchSourceRow')
            if width>=970:
                source_x[(scope,width)]=market.findChild(QQuickItem,'marketSourceSegment').mapToScene(QPointF(0,0)).x()
                assert source_row.height()==34, (scope,width,source_row.height())
                assert browser.property('showCategories') and adjacent.isVisible()
                assert grid.property('columns')==3
                assert grid.height()>=2*grid.property('cellHeight')-12, (scope,width,grid.height(),grid.property('cellHeight'))
                assert timeline.property('expanded') and timeline.height()>=94
                assert grid.mapToScene(QPointF(grid.width(),0)).x()<adjacent.mapToScene(QPointF(0,0)).x()
                assert adjacent.mapToScene(QPointF(adjacent.width(),0)).x()<=window.width()
                assert timeline.width()<browser.width()-adjacent.width()
                images=[item for item in walk(grid) if item.objectName()=='marketCardImage']
                for _ in range(30):
                    app.processEvents()
                    if all(js(item,'status===1') for item in images):break
                    QTest.qWait(20)
                assert all(js(item,'status===1') for item in images),[(str(item.property('source')),js(item,'status')) for item in images]
            else:
                assert not adjacent.isVisible() and browser.findChild(QQuickItem,'marketCompactCategory').isVisible()
            tile=next(item for item in walk(grid) if item.objectName()=='marketReceiptTile' and item.property('index')==1)
            if width==360:js(grid,'positionViewAtIndex(1,0)');QTest.qWait(70)
            click(tile)
            if scope=='PUBLIC':
                assert market.property('page')=='CATALOG' and grid.isVisible()
                assert js(market.findChild(QQuickItem,'publicMarketplace'),'selected.id==="coingecko:visual-1"')
                popup=browser.findChild(QObject,'marketCompactPassport')
                if width==360:assert popup.property('visible')
                photo_root=popup.property('contentItem') if width==360 else browser
                for _ in range(40):
                    app.processEvents()
                    photos=[i for i in walk(photo_root) if i.objectName()=='publicPassportImage' and i.isVisible()]
                    if photos and all(js(i,'status===1') for i in photos):break
                    QTest.qWait(20)
                assert photos and all(js(i,'status===1') for i in photos), (scope,width,[(str(i.property('source')),js(i,'status')) for i in photos])
                if width==360:
                    assert browser.findChild(QObject,'marketCompactPassport').property('visible')
                    window.grabWindow().save(str(directory/'mp-public-pass-360.png'))
                    QTest.keyClick(window,Qt.Key_Escape);QTest.qWait(30)
            else:
                if width==360:market.setProperty('page','CATALOG');QTest.qWait(50)
            window.grabWindow().save(str(directory/('mp-reference-'+scope.lower()+'-'+str(width)+'.png')))
            if width==360:
                click(browser.findChild(QQuickItem,'marketCompactCategory'))
                assert browser.findChild(QObject,'marketFacetPopup').property('visible')
                window.grabWindow().save(str(directory/('mp-categories-'+scope.lower()+'-360.png')))
                QTest.keyClick(window,Qt.Key_Escape);QTest.qWait(30)
            records.append({'scope':scope,'window':[width,height],'columns':grid.property('columns'),
                            'catalog_width':round(grid.width(),1),'pass_width':round(adjacent.width(),1),
                            'log_expanded':timeline.property('expanded')})
    assert source_x[('LOCAL',970)]==source_x[('PUBLIC',970)] and source_x[('LOCAL',1586)]==source_x[('PUBLIC',1586)]
    # Hiding the pane while another operation occupies its UI lane must retain
    # the stop request. Its bounded timer can finish cancellation while hidden.
    host.data['ui_operation']={'name':'market_discover','state':'running'}
    host.data['public_catalog']['preview_job']={'state':'running','worker_active':True,'completed':2,'total':6,'images':2,'failed':0}
    js(market,'applyRaw('+json.dumps(json.dumps(host.data))+')');QTest.qWait(30)
    before=len(host.calls);market.setVisible(False);QTest.qWait(40)
    assert market.property('stopPreviewsPending') and len(host.calls)==before
    host.data['ui_operation']={'name':'market_discover','state':'done'}
    for _ in range(30):
        app.processEvents();QTest.qWait(30)
        if not market.property('stopPreviewsPending'):break
    assert not market.property('stopPreviewsPending')
    assert host.calls[before:]==[('public',{'action':'stop_previews'})]
    assert host.data['public_catalog']['preview_job']['state']=='cancelled'
    assert not warnings,warnings
    destination=os.environ.get('GG_MP_GALLERY_EVIDENCE')
    if destination:
        import shutil
        Path(destination).mkdir(parents=True,exist_ok=True)
        for image in directory.glob('mp-*.png'):shutil.copy2(image,Path(destination)/image.name)
    print(json.dumps({'status':'PASS','real_qml':True,'reference_geometry':records,'warnings':len(warnings),'fixture_only':True}))
    window.close();engine.deleteLater();app.processEvents()


class MarketplaceGalleryUi(unittest.TestCase):
    def test_local_and_public_keep_reference_gallery_and_adjacent_pass(self):
        with tempfile.TemporaryDirectory(prefix='gg-mp-gallery-') as temporary:
            env=os.environ.copy();env.update(QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software',QT_QUICK_CONTROLS_STYLE='Basic')
            result=subprocess.run([sys.executable,'-B',str(Path(__file__).resolve()),'--fixture',temporary],cwd=PROJECT,env=env,capture_output=True,text=True,timeout=40)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr);print(result.stdout.strip())


if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--fixture':fixture(Path(sys.argv[2]))
    else:unittest.main()
