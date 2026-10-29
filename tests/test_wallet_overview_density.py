"""Real Qt overview proportions and exact quantities at desktop/mobile widths.

Every account, balance, quote and history sample here is synthetic test data.
No application wallet or external provider is accessed.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PROJECT=Path(__file__).resolve().parents[1]


def fixture(directory):
    from decimal import Decimal
    from PySide6.QtCore import QObject,Slot,QUrl,QPointF
    from PySide6.QtGui import QGuiApplication,QFont,QFontDatabase
    from PySide6.QtQml import QQmlApplicationEngine,QQmlExpression,qmlContext
    from PySide6.QtQuick import QQuickItem
    from PySide6.QtTest import QTest
    app=QGuiApplication([])
    if os.name=='nt':
        for name in ('consola.ttf','consolab.ttf','seguisym.ttf'):
            QFontDatabase.addApplicationFont(str(Path(os.environ.get('SystemRoot','C:/Windows'))/'Fonts'/name))
    QFont.insertSubstitution('monospace','Consolas' if os.name=='nt' else 'DejaVu Sans Mono')
    app.setFont(QFont('Consolas' if os.name=='nt' else 'DejaVu Sans Mono'))
    sol='solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp';eth='eip155:1';btc='bip122:000000000019d6689c085ae165831e93'
    networks=[{'id':sol,'name':'Solana','family':'solana','endpoint':'https://rpc.example.test/solana'},
              {'id':eth,'name':'Ethereum','family':'evm','endpoint':'https://rpc.example.test/ethereum'},
              {'id':btc,'name':'Bitcoin','family':'utxo','endpoint':'https://rpc.example.test/bitcoin'}]
    accounts=[{'id':'test-'+str(i),'label':['Huvudkonto','Trading','Sparande'][i],
               'chain_id':network['id'],'address':'synthetic-public-account-'+str(i)} for i,network in enumerate(networks)]
    assets=[];rows=[]
    for index,symbol in enumerate(('SOL','ETH','BTC','TST1','TST2','TST3','TST4','TST5','TST6','ZTEST')):
        account=accounts[index if index<3 else 0];chain=account['chain_id']
        identifier=chain+'/native:'+symbol if index<3 else chain+'/token:synthetic-'+str(index)
        assets.append({'id':identifier,'symbol':symbol,'name':'Synthetic '+symbol,'chain_id':chain,
                       'namespace':'native' if index<3 else 'token','reference':symbol if index<3 else 'synthetic-'+str(index)})
        unknown=index==9;quantity='12345678.123456' if unknown else str(index+1)+'.2500'
        price=None if unknown else index+2
        value=None if unknown else format(Decimal(quantity)*Decimal(price),'.2f')
        rows.append({'id':'position-'+str(index),'account_id':account['id'],'asset_id':identifier,'symbol':symbol,
                     'name':'Synthetic '+symbol,'chain_id':chain,'network':networks[index if index<3 else 0]['name'],
                     'quantity':quantity,'atomic':'12345678123456' if unknown else str((index+1)*10000+2500),
                     'price_usd':price,'value_usd':value,'price_state':'MISSING' if unknown else 'CURRENT',
                     'balance_state':'VERIFIED_READ','balance_current':True,'scope':'PUBLIC',
                     'change_24h':None if unknown else (index-4)/3,
                     'sparkline':{'prices':[] if unknown else [price*(1+((j%7)-3)*.002+j*.001) for j in range(48)],
                                  'period':'7D','source':'OFFLINE SYNTHETIC FIXTURE'}})
    known=sum((Decimal(row['value_usd']) for row in rows if row['value_usd'] is not None),Decimal(0))
    summaries={account['id']:{'known_value_usd':format(sum((Decimal(row['value_usd']) for row in rows if row['account_id']==account['id'] and row['value_usd'] is not None),Decimal(0)),'.2f'),
                              'last_read_at':1700000000} for account in accounts}
    payload={'assets':assets,'selected_asset':assets[0]['id'],'ui_operation':{},'wallet_transfers':[],
             'wallet_overview':{'accounts':accounts,'networks':networks,'rows':rows,'local_wallets':[],
                 'summary':{'known_value_usd':format(known,'.2f'),'account_count':3,'network_count':3,'unpriced_count':1},
                 'account_summaries':summaries,'network_summaries':{network['id']:{'last_read_at':1700000000} for network in networks},
                 'events':[{'ts':1700000000+i,'kind':'BALANCE_READ','asset_id':row['asset_id'],'message':'Saldo från isolerad testfixtur.'} for i,row in enumerate(rows)]}}
    class Host(QObject):
        @Slot(result=str)
        def omniStatus(self):return json.dumps(payload)
        @Slot(result=str)
        def explorerStatus(self):return json.dumps({'rows':[],'settings':{'paused':True},'needs_refresh':False,'networks':[]})
        @Slot(result=str)
        def cryptoStatus(self):return '{}'
        @Slot(result=str)
        def marketplaceStatus(self):return json.dumps({'listings':[],'listing_count':0,'public_catalog':{'rows':[],'source_state':'NOT_FETCHED'}})
    host=Host();engine=QQmlApplicationEngine();warnings=[]
    engine.warnings.connect(lambda errors:warnings.extend(error.toString() for error in errors));engine.rootContext().setContextProperty('testHost',host)
    path=directory/'fixture.qml';path.write_text('''import QtQuick
import QtQuick.Controls
import COMPONENTS
ApplicationWindow {width:970;height:700;visible:true;color:'#111111'
CryptoSurface {objectName:'testCrypto';anchors.fill:parent;surfaceHost:testHost}
}'''.replace('COMPONENTS',json.dumps((PROJECT/'qml/components').as_uri())),encoding='utf-8')
    engine.load(QUrl.fromLocalFile(str(path)));assert engine.rootObjects(),warnings
    window=engine.rootObjects()[0];pane=window.findChild(QQuickItem,'testCrypto');wallet=pane.findChild(QQuickItem,'omniWalletOverview')
    def js(item,code):
        expression=QQmlExpression(qmlContext(item),item,code);value=expression.evaluate()
        assert not expression.hasError(),expression.error().toString()
        return value[0] if isinstance(value,tuple) else value
    def items(item):
        yield item
        for child in item.childItems():yield from items(child)
    QTest.qWait(220);assert pane.property('page')=='WALLET'
    records=[]
    for width,height in ((970,700),(1586,992),(430,700),(820,700)):
        window.setWidth(width);window.setHeight(height);QTest.qWait(160)
        listing=wallet.findChild(QQuickItem,'walletPositionList');js(listing,'forceLayout()')
        header=wallet.findChild(QQuickItem,'walletOverviewHeader');total=wallet.findChild(QQuickItem,'walletTotalValue')
        rendered=[item for item in items(listing) if item.objectName()=='walletAssetRow']
        first=min(rendered,key=lambda item:item.property('index'));first_y=first.mapToScene(QPointF(0,0)).y()
        if width==970:
            assert wallet.property('tableWide') and 28<=total.property('font').pixelSize()<=32
            assert header.height()<=115 and first_y<=225, (header.height(),first_y)
            assert 40<=first.height()<=44 and listing.height()>=10*first.height(), (listing.height(),first.height())
            controls=[wallet.findChild(QQuickItem,name) for name in ('walletAccountFilter','walletReceive','walletRefreshOverview')]
            assert max(item.mapToScene(QPointF(0,0)).y() for item in controls)-min(item.mapToScene(QPointF(0,0)).y() for item in controls)<1
            for control in controls:
                assert control.mapToScene(QPointF(0,0)).x()>total.mapToScene(QPointF(0,0)).x()+total.width()
                assert not js(control,'contentItem.truncated'),control.objectName()
                assert 26<=control.height()<=28
            long_row=next(item for item in rendered if item.property('assetTarget')==assets[-1]['id'])
            quantity=long_row.findChild(QQuickItem,'walletRowBalance');price=long_row.findChild(QQuickItem,'walletRowPrice')
            assert quantity.isVisible() and quantity.property('text')=='12 345 678.123456' and not quantity.property('truncated')
            assert price.isVisible() and price.property('text')=='Ej prissatt'
            spark=long_row.findChild(QQuickItem,'tokenSparkline');assert spark.isVisible() and not spark.property('available')
            sparks=[item for item in items(listing) if item.objectName()=='tokenSparkline']
            assert sum(item.isVisible() and item.property('available') for item in sparks)==9
            for heading in ('TILLGÅNG / NÄTVERK','SALDO','PRIS','VÄRDE','7 DAGAR / 24 H'):
                assert any(item.isVisible() and item.property('text')==heading for item in items(wallet)),heading
        elif width==1586:
            assert first.height()==66 and total.property('font').pixelSize()==48
        else:
            assert not wallet.property('tableWide') and listing.height()>=200
        for control in (wallet.findChild(QQuickItem,name) for name in ('walletAccountFilter','walletReceive','walletRefreshOverview','walletAssetSearch','walletTools')):
            point=control.mapToItem(wallet,QPointF(0,0))
            assert point.x()>=0 and point.x()+control.width()<=wallet.property('edgeInset')+wallet.property('mainWidth')+.1
        records.append({'window':[width,height],'first_row_y':first_y,'row_height':first.height(),
                        'header_height':header.height(),'list_height':listing.height(),'full_table':wallet.property('tableWide')})
        assert window.grabWindow().save(str(directory/('overview-'+str(width)+'.png')))
    assert not warnings,warnings
    destination=os.environ.get('GG_OVERVIEW_DENSITY_EVIDENCE')
    if destination:
        import shutil
        Path(destination).mkdir(parents=True,exist_ok=True)
        for image in directory.glob('overview-*.png'):shutil.copy2(image,Path(destination)/image.name)
    print(json.dumps({'status':'PASS','real_qml':True,'geometry':records,'exact_quantity':True,'warnings':len(warnings),'fixture_only':True}))
    window.close();engine.deleteLater();app.processEvents()


class WalletOverviewDensity(unittest.TestCase):
    def test_reference_proportions_full_desktop_columns_and_exact_long_quantity(self):
        with tempfile.TemporaryDirectory(prefix='gg-overview-density-') as temporary:
            env=os.environ.copy();env.update(QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software',QT_QUICK_CONTROLS_STYLE='Basic')
            result=subprocess.run([sys.executable,'-B',str(Path(__file__).resolve()),'--fixture',temporary],cwd=PROJECT,env=env,capture_output=True,text=True,timeout=35)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr);print(result.stdout.strip())


if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--fixture':fixture(Path(sys.argv[2]))
    else:unittest.main()
