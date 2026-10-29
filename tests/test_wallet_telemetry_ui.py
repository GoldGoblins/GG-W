"""Actual narrow/wide wallet facts, verified key identity and honest status UI."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PROJECT=Path(__file__).resolve().parents[1]


def fixture(directory):
    from PySide6.QtCore import QUrl,QPointF,Qt
    from PySide6.QtGui import QGuiApplication,QFont,QFontDatabase
    from PySide6.QtQml import QQmlApplicationEngine,QQmlExpression,qmlContext
    from PySide6.QtQuick import QQuickItem
    from PySide6.QtTest import QTest,QSignalSpy
    app=QGuiApplication([])
    if os.name=='nt':
        for font in ('consola.ttf','consolab.ttf','seguisym.ttf'):
            QFontDatabase.addApplicationFont(str(Path(os.environ.get('SystemRoot','C:/Windows'))/'Fonts'/font))
    QFont.insertSubstitution('monospace','Consolas' if os.name=='nt' else 'DejaVu Sans Mono')
    app.setFont(QFont('Consolas' if os.name=='nt' else 'DejaVu Sans Mono'))
    engine=QQmlApplicationEngine();warnings=[]
    engine.warnings.connect(lambda errors:warnings.extend(e.toString() for e in errors))
    path=directory/'fixture.qml'
    path.write_text('''import QtQuick
import QtQuick.Controls
import COMPONENTS
ApplicationWindow {width:280;height:900;visible:true;color:'#111111'
WalletTelemetry {objectName:'testRail';anchors.fill:parent;accounts:(state.wallet_overview || {}).accounts || []}
}'''.replace('COMPONENTS',json.dumps((PROJECT/'qml/components').as_uri())),encoding='utf-8')
    engine.load(QUrl.fromLocalFile(str(path)));assert engine.rootObjects(),warnings
    window=engine.rootObjects()[0];rail=window.findChild(QQuickItem,'testRail')
    def js(code):
        expression=QQmlExpression(qmlContext(rail),rail,code);result=expression.evaluate()
        assert not expression.hasError(),expression.error().toString()
        return result[0] if isinstance(result,tuple) else result
    def items(item):
        yield item
        for child in item.childItems():yield from items(child)
    def click(item):
        QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,item.mapToScene(QPointF(item.width()/2,item.height()/2)).toPoint())
        QTest.qWait(30)
    def texts():return [i.property('text') for i in items(rail) if i.isVisible() and i.property('text') is not None]
    state={'assets':[{'id':'test-sol','symbol':'SOL'}],'ui_operation':{},'wallet_overview':{
        'accounts':[{'id':'main','label':'Huvudkonto','address':'public-fixture-address-main','chain_id':'test:sol'},
                    {'id':'saving','label':'Sparande med längre kontonamn','address':'public-fixture-address-saving','chain_id':'test:eth'}],
        'networks':[{'id':'test:sol','name':'Solana mainnet','endpoint':'https://rpc.example.test/solana/public'},
                    {'id':'test:eth','name':'Ethereum','endpoint':'https://rpc.example.test/ethereum/public'}],
        'account_summaries':{'main':{'known_value_usd':'1248.00','last_read_at':1700000000},
                             'saving':{'known_value_usd':None,'failed_count':1}},
        'network_summaries':{'test:sol':{'last_read_at':1700000000},'test:eth':{'failed_count':1}},
        'local_wallets':[{'account_id':'main','pubkey':'wrong-public-fixture-address','vault_available':True,'backed_up':True}],
        'events':[{'ts':1700000000,'kind':'BALANCE_READ','asset_id':'test-sol','message':'Saldo läst från konfigurerad källa.'},
                  {'ts':1700000001,'kind':'TRANSFER_PREPARED','asset_id':'test-sol','message':'Överföringen är simulerad och väntar på din granskning.'},
                  {'ts':1700000002,'kind':'TRANSFER_CONFIRMED','asset_id':'test-sol','message':'Nätverket rapporterar att transaktionen är bekräftad.'}]}}
    def apply():js('state='+json.dumps(state,ensure_ascii=False));QTest.qWait(40)
    apply()
    modes=0
    for mode in ('overview','wallet'):
        rail.setProperty('showAccounts',mode=='overview');rail.setProperty('accountId','' if mode=='overview' else 'main')
        for width in (250,280,360):
            window.setWidth(width);QTest.qWait(50)
            scroll=rail.findChild(QQuickItem,'walletTelemetryScroll')
            assert scroll.width()==width-2*rail.property('inset') and scroll.width()>=218
            assert scroll.property('contentWidth')==scroll.width()
            messages=[i for i in items(rail) if i.objectName()=='walletEventMessage']
            assert len(messages)==3
            for message in messages:
                assert message.width()>=scroll.width()-(20 if mode=='wallet' else 0)
                assert not message.property('truncated') and message.height()==message.property('implicitHeight')
            if mode=='wallet':
                assert not rail.property('localVaultAvailable') and 'Windows DPAPI' not in texts()
                endpoint=next(i for i in items(rail) if i.objectName()=='walletEndpointValue')
                assert endpoint.property('text')=='https://rpc.example.test/solana/public'
                assert not endpoint.property('truncated') and endpoint.width()==scroll.width()
            window.grabWindow().save(str(directory/(mode+'-'+str(width)+'.png')));modes+=1
    state['wallet_overview']['local_wallets'][0]['pubkey']='public-fixture-address-main';apply()
    assert rail.property('localVaultAvailable') and 'Windows DPAPI' in texts()
    state['wallet_overview']['local_wallets'][0]['vault_available']=False;apply()
    assert not rail.property('localVaultAvailable') and 'Windows DPAPI' not in texts() and 'Valv saknas' in texts()
    state['wallet_overview']['local_wallets'][0]['vault_available']=True;apply()
    protection=rail.findChild(QQuickItem,'walletProtectionSectionToggle')
    click(protection);assert not rail.property('protectionExpanded')
    assert 'Windows DPAPI' not in texts()
    click(protection);assert rail.property('protectionExpanded') and 'Windows DPAPI' in texts()
    assert js('endpointText("https://example.test/rpc?example_token=fixture")')=='Skyddad eller ogiltig endpoint'
    assert js('endpointText("https://fixture@example.test/rpc")')=='Skyddad eller ogiltig endpoint'
    assert js('endpointText("https://example.test/v2/fixture-key")')=='https://example.test/…'
    assert js('eventColor("TRANSFER_CONFIRMED")')==js('eventColor("BALANCE_READ")')
    assert js('eventColor("TRANSFER_UNCERTAIN")')!=js('eventColor("TRANSFER_CONFIRMED")')
    assert js('eventColor("BALANCE_READ_FAILED")')!=js('eventColor("TRANSFER_CONFIRMED")')
    operation=rail.findChild(QQuickItem,'walletCurrentOperation')
    assert not operation.isVisible()
    state['ui_operation']={'state':'approval_required','name':'send_transfer'};apply()
    assert operation.isVisible() and 'Godkänn eller avvisa i chatten för att fortsätta.' in texts()
    state['ui_operation']={'state':'failed','name':'refresh_balance','error':'OFFLINE_FIXTURE_READ_FAILED'};apply()
    assert operation.isVisible() and 'OFFLINE_FIXTURE_READ_FAILED' in texts()
    state['ui_operation']={};apply()
    rail.setProperty('showAccounts',True);rail.setProperty('accountId','');QTest.qWait(40)
    account_spy=QSignalSpy(rail.accountRequested)
    account=next(i for i in items(rail) if i.objectName()=='walletRailAccount' and i.property('targetAccountId')=='main')
    click(account);assert account_spy.count()==1 and account_spy.at(0)==['main']
    scroll=rail.findChild(QQuickItem,'walletTelemetryScroll')
    all_events=rail.findChild(QQuickItem,'walletRailAllEvents')
    scroll.setProperty('contentY',all_events.mapToItem(scroll,QPointF(0,0)).y()+scroll.property('contentY')-30);QTest.qWait(30)
    event_spy=QSignalSpy(rail.activityRequested);click(all_events);assert event_spy.count()==1
    assert not warnings,warnings
    destination=os.environ.get('GG_WALLET_TELEMETRY_EVIDENCE')
    if destination:
        import shutil
        Path(destination).mkdir(parents=True,exist_ok=True)
        for image in directory.glob('*.png'):shutil.copy2(image,Path(destination)/image.name)
    print(json.dumps({'status':'PASS','rail_geometry_cases':modes,'qml_warnings':len(warnings)}))
    window.close();engine.deleteLater();app.processEvents()


class WalletTelemetryUi(unittest.TestCase):
    def test_compact_facts_key_identity_status_and_section_controls(self):
        with tempfile.TemporaryDirectory(prefix='gg-wallet-telemetry-') as temporary:
            env=os.environ.copy();env.update(QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software',QT_QUICK_CONTROLS_STYLE='Basic')
            result=subprocess.run([sys.executable,'-B',str(Path(__file__).resolve()),'--fixture',temporary],cwd=PROJECT,env=env,capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            print(result.stdout.strip())


if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--fixture':fixture(Path(sys.argv[2]))
    else:unittest.main()
