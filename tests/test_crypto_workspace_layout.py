"""Native tab content must fill its real GgFrame viewport at every supported size."""
import os
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

PROJECT=Path(__file__).resolve().parents[1]


def fixture(directory):
    from PySide6.QtCore import QObject,Slot,Signal,QUrl
    from PySide6.QtGui import QGuiApplication,QFont,QFontDatabase
    from PySide6.QtQml import QQmlApplicationEngine,QQmlExpression,qmlContext
    from PySide6.QtQuick import QQuickItem
    from PySide6.QtTest import QTest
    root=PROJECT
    app=QGuiApplication([])
    if os.name=='nt':
        for name in ('consola.ttf','consolab.ttf','seguisym.ttf'):
            QFontDatabase.addApplicationFont(str(Path(os.environ.get('SystemRoot','C:/Windows'))/'Fonts'/name))
    QFont.insertSubstitution('monospace','Consolas' if os.name=='nt' else 'DejaVu Sans Mono')
    app.setFont(QFont('Consolas' if os.name=='nt' else 'DejaVu Sans Mono'))
    class Host(QObject):
        chatTerminalOutput=Signal(str,str)
        @Slot(str,result=str)
        def startChatTerminal(self,identity):return ''
        @Slot(result=str)
        def listSiteFiles(self):return '[]'
        @Slot(result=str)
        def cryptoStatus(self):return '{}'
        @Slot(result=str)
        def explorerStatus(self):return json.dumps({'schema':'gg.explorer.v1','rows':[],'settings':{'view':'overview','paused':True},'needs_refresh':False,'networks':[]})
        @Slot(result=str)
        def omniStatus(self):return json.dumps({'assets':[],'wallet_overview':{'rows':[],'accounts':[],'networks':[],'summary':{'known_value_usd':None},'local_wallets':[]},'wallet_transfers':[]})
        @Slot(result=str)
        def marketplaceStatus(self):return json.dumps({'catalog':[],'listing_count':0,'public_catalog':{'rows':[],'source_state':'NOT_FETCHED','provider':'coingecko','page':1}})
    host=Host();engine=QQmlApplicationEngine();warnings=[];engine.warnings.connect(lambda es:warnings.extend(e.toString() for e in es));engine.rootContext().setContextProperty('testHost',host)
    with tempfile.TemporaryDirectory(prefix='gg-native-workspace-') as temporary:
        path=Path(temporary)/'fixture.qml'
        path.write_text('''import QtQuick
    import QtQuick.Controls
    import COMPONENTS
    ApplicationWindow {width:1200;height:850;visible:true;color:'#111111';property var surfaceHost:testHost
    WorkspaceSurface {objectName:'nativeWorkspaceTest';anchors.fill:parent;hostKind:'CRYPTO'}
    }'''.replace('COMPONENTS',json.dumps((root/'qml/components').as_uri())),encoding='utf-8')
        engine.load(QUrl.fromLocalFile(str(path)));assert engine.rootObjects(),warnings
        window=engine.rootObjects()[0];QTest.qWait(300);surface=window.findChild(QQuickItem,'nativeWorkspaceTest')
        out=directory
        records=[]
        for kind in ('CRYPTO','MARKETPLACE'):
            surface.setProperty('hostKind',kind);QTest.qWait(180)
            for width,height in ((430,700),(820,850),(860,850),(900,850),(1000,850),(1200,850),(1586,992)):
                window.setWidth(width);window.setHeight(height);QTest.qWait(80)
                frame=surface.findChild(QQuickItem,'workspaceNativeFrame');body=surface.findChild(QQuickItem,'workspaceTabContent');viewport=frame.property('contentItem')
                assert body.parentItem()==viewport
                assert abs(body.width()-viewport.width())<.1 and abs(body.height()-viewport.height())<.1
                assert surface.property('hostKind')=='CRYPTO'
                pane=next(i for i in body.childItems() if i.objectName()=='workspaceCryptoPane')
                crypto=pane.findChild(QQuickItem,'workspaceCryptoPane')
                assert crypto is not None
                if kind=='MARKETPLACE':assert crypto.property('page')=='MARKETPLACE'
                assert abs(pane.width()-body.width())<.1 and abs(pane.height()-body.height())<.1
                frame_content=pane.findChild(QQuickItem, 'cryptoPrimarySpace')
                assert frame_content is not None
                assert frame_content.x()==0 and frame_content.y()==0
                assert frame_content.width()==pane.width() and frame_content.height()==pane.height()
                if width>=820:
                    nav_viewport=frame_content.findChild(QQuickItem,'spaceNavigationViewport')
                    from PySide6.QtCore import QPointF
                    for destination in ('WALLET','MARKET','MARKETPLACE','BOTS','NETWORK'):
                        pending=[frame_content];nav=None
                        while pending:
                            item=pending.pop()
                            if item.objectName()=='spaceNav'+destination:nav=item;break
                            pending.extend(item.childItems())
                        assert nav is not None
                        if destination=='MARKETPLACE':
                            assert nav.property('text')=='MARKETPLACE'
                            assert not nav.property('contentItem').property('truncated')
                        point=nav.mapToItem(nav_viewport,QPointF(0,0))
                        assert point.x()>=0 and point.x()+nav.width()<=nav_viewport.width()+.1, (kind,width,destination,point.x(),nav.width(),nav_viewport.width())
                if width==430:
                    pending=[frame_content];nav=None
                    while pending:
                        item=pending.pop()
                        if item.objectName()=='spaceNavWALLET':nav=item;break
                        pending.extend(item.childItems())
                    assert nav is not None
                    assert not nav.property('contentItem').property('truncated')
                records.append({'kind':kind,'window':[width,height],'viewport':[round(viewport.width(),1),round(viewport.height(),1)],'pane':[round(pane.width(),1),round(pane.height(),1)]})
                window.grabWindow().save(str(out/('native-workspace-'+kind.lower()+'-'+str(width)+'.png')))
        # Legacy commands still select the embedded marketplace when the
        # CRYPTO host already exists, as well as through direct host changes.
        crypto.setProperty('page','WALLET')
        expression=QQmlExpression(qmlContext(surface),surface,"setHostKind('MARKETPLACE')")
        expression.evaluate();assert not expression.hasError(),expression.error().toString()
        QTest.qWait(100)
        assert surface.property('hostKind')=='CRYPTO' and crypto.property('page')=='MARKETPLACE'
        expression=QQmlExpression(qmlContext(surface),surface,"openCrypto('WALLET')")
        expression.evaluate();assert not expression.hasError(),expression.error().toString()
        QTest.qWait(50)
        assert surface.property('hostKind')=='CRYPTO' and crypto.property('page')=='WALLET'
        assert not surface.property('pendingCryptoSection')
        assert not warnings,warnings
        destination=os.environ.get('GG_WORKSPACE_UI_EVIDENCE')
        if destination:
            import shutil
            Path(destination).mkdir(parents=True,exist_ok=True)
            for image in out.glob('native-workspace-*.png'):shutil.copy2(image,Path(destination)/image.name)
        (out/'workspace-geometry.json').write_text(json.dumps({'status':'PASS','records':records,'qml_warnings':warnings},indent=2)+'\n',encoding='utf-8')
        print(json.dumps({'status':'PASS','workspace_geometry_cases':len(records),'qml_warnings':len(warnings)}))
        window.close();engine.deleteLater();app.processEvents()


class NativeWorkspaceLayout(unittest.TestCase):
    def test_real_workspace_viewport_geometry_and_qml_connections(self):
        with tempfile.TemporaryDirectory(prefix='gg-native-workspace-test-') as temporary:
            directory=Path(temporary);env=os.environ.copy()
            env.update(QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software',QT_QUICK_CONTROLS_STYLE='Basic',
                       GG_DESKTOP_STATE_ROOT=str(directory/'state'),GG_DESKTOP_DATA_ROOT=str(directory/'data'))
            result=subprocess.run([sys.executable,'-B',str(Path(__file__).resolve()),'--fixture',temporary],
                                  cwd=PROJECT,env=env,capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            print(result.stdout.strip())


if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--fixture':fixture(Path(sys.argv[2]))
    else:unittest.main()
