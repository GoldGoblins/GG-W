"""Real Loader creation order, retained live bindings and activation lifecycle."""
import json
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ.setdefault('QT_QUICK_BACKEND','software')

from PySide6.QtCore import QObject,Slot,QUrl,Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlEngine,QQmlComponent,QQmlExpression,qmlContext
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest,QSignalSpy

PROJECT=Path(__file__).resolve().parents[1]


class Host(QObject):
    chatTerminalOutput=Signal(str,str)
    def __init__(self):super().__init__();self.creations=0;self.setObjectName('FixtureHost')
    @Slot(result=int)
    def created(self):self.creations+=1;return self.creations

    @Slot(str,result=str)
    def researchCommand(self,_raw):return '{}'

    @Slot(result=str)
    def listSiteFiles(self):return '[]'

    @Slot(str,result=str)
    def startChatTerminal(self,_identity):return ''


class DeferredSurfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QGuiApplication.instance() or QGuiApplication([])

    def test_all_eleven_real_surface_types_accept_creation_properties(self):
        engine=QQmlEngine();warnings=[]
        engine.warnings.connect(lambda rows:warnings.extend(row.toString() for row in rows))
        component=QQmlComponent(engine)
        component.setData(('import QtQuick\nimport '+json.dumps((PROJECT/'qml/components').as_uri())+'\nDeferredSurface {width:970;height:680;active:false}').encode(),QUrl())
        self.assertTrue(component.isReady(),[error.toString() for error in component.errors()])
        loader=component.create();self.assertIsNotNone(loader)
        names=('CryptoSurface','MarketplaceSurface','TmogSurface','OsintSurface','MediaSurface','DrawSurface',
               'GameEngineSurface','NodeSurface','AgentFlowSurface','ResearchSurface','KnowledgeSurface')
        for name in names:
            loader.setProperty('active',False)
            properties={'surfaceHost':None,'frameBorder':'#454545','frameRadius':4,'objectName':'probe'+name}
            if name=='GameEngineSurface':properties['paneLive']=False
            loader.setProperty('surfaceProperties',properties)
            loader.setProperty('surfaceUrl',QUrl.fromLocalFile(str(PROJECT/'qml/components'/(name+'.qml'))))
            loader.setProperty('active',True);self.app.processEvents()
            item=loader.property('item')
            self.assertIsNotNone(item,(name,warnings))
            self.assertEqual(item.objectName(),'probe'+name)
            self.assertEqual(item.property('frameRadius'),4)
            self.assertEqual(item.property('frameBorder').name(),'#454545')
            self.assertEqual((item.width(),item.height()),(970,680))
        # This hostless creation-ABI probe has no optional authored game asset
        # library or backend data. Existing surface content can report those
        # missing inputs; the loader itself must never reject an input property.
        errors=[message for message in warnings if 'DeferredSurface.qml' in message
                or 'Cannot assign to non-existent property' in message or 'Required property' in message]
        self.assertFalse(errors,errors)
        loader.setProperty('active',False);loader.deleteLater();engine.deleteLater();self.app.processEvents()

    def test_initial_properties_precede_completion_and_live_bindings_do_not_recreate(self):
        with tempfile.TemporaryDirectory(prefix='gg-deferred-surface-') as temporary:
            directory=Path(temporary)
            (directory/'Probe.qml').write_text('''import QtQuick
Item {required property var surfaceHost;required property color frameBorder;required property int frameRadius
property bool embedded:false;property bool paneLive:false;property int creationToken:0;property var completionValues:({})
Component.onCompleted:{creationToken=surfaceHost.created();completionValues={host:surfaceHost.objectName,border:String(frameBorder),radius:frameRadius,embedded:embedded,live:paneLive}}
}''',encoding='utf-8')
            (directory/'fixture.qml').write_text('''import QtQuick
import COMPONENTS
Item {id:shell;width:640;height:400;property var backend:fixtureHost;property color edge:'#454545';property int radius:4;property bool embeddedFlag:true;property bool live:false
DeferredSurface {objectName:'loader';anchors.fill:parent;active:false;surfaceUrl:Qt.resolvedUrl('Probe.qml')
surfaceProperties:({surfaceHost:Qt.binding(function(){return shell.backend}),frameBorder:Qt.binding(function(){return shell.edge}),frameRadius:Qt.binding(function(){return shell.radius}),embedded:Qt.binding(function(){return shell.embeddedFlag}),paneLive:Qt.binding(function(){return shell.live})})}
}'''.replace('COMPONENTS',json.dumps((PROJECT/'qml/components').as_uri())),encoding='utf-8')
            host=Host();engine=QQmlEngine();warnings=[];engine.warnings.connect(lambda rows:warnings.extend(row.toString() for row in rows))
            engine.rootContext().setContextProperty('fixtureHost',host)
            component=QQmlComponent(engine,QUrl.fromLocalFile(str(directory/'fixture.qml')))
            self.assertTrue(component.isReady(),[error.toString() for error in component.errors()])
            root=component.create();self.assertIsNotNone(root,[error.toString() for error in component.errors()])
            loader=root.findChild(QQuickItem,'loader');QTest.qWait(30)
            self.assertIsNone(loader.property('item'));self.assertEqual(host.creations,0)
            root.setProperty('radius',7);loaded=QSignalSpy(loader.loaded);loader.setProperty('active',True);QTest.qWait(30)
            item=loader.property('item');self.assertIsNotNone(item,warnings)
            values=item.property('completionValues').toVariant()
            self.assertEqual(values,{'host':'FixtureHost','border':'#454545','radius':7,'embedded':True,'live':False})
            self.assertEqual((host.creations,loaded.count()),(1,1))
            self.assertEqual((item.width(),item.height()),(640,400))
            root.setProperty('radius',9);root.setProperty('edge','#ab12cd');root.setProperty('live',True);root.setProperty('embeddedFlag',False)
            for index in range(20):root.setWidth(640+index);root.setHeight(400+index)
            QTest.qWait(20)
            self.assertEqual(item.property('frameRadius'),9);self.assertEqual(item.property('frameBorder').name(),'#ab12cd')
            self.assertTrue(item.property('paneLive'));self.assertFalse(item.property('embedded'))
            self.assertEqual((host.creations,loaded.count()),(1,1))
            self.assertEqual((item.width(),item.height()),(659,419))
            loader.setProperty('active',False);QTest.qWait(10);self.assertIsNone(loader.property('item'))
            root.setProperty('radius',11);loader.setProperty('active',True);QTest.qWait(20)
            item=loader.property('item');self.assertEqual(item.property('completionValues').toVariant()['radius'],11)
            self.assertEqual((host.creations,loaded.count()),(2,2))
            self.assertFalse(warnings,warnings)
            root.deleteLater();engine.deleteLater();self.app.processEvents()

    def test_workspace_research_keepalive_and_pending_navigation(self):
        host=Host();engine=QQmlEngine();warnings=[]
        engine.warnings.connect(lambda rows:warnings.extend(row.toString() for row in rows))
        engine.rootContext().setContextProperty('fixtureHost',host)
        component=QQmlComponent(engine)
        component.setData(('''import QtQuick
import COMPONENTS
Window {width:1100;height:760;visible:false;property var surfaceHost:fixtureHost
WorkspaceSurface {objectName:'testWorkspace';anchors.fill:parent;hostKind:'CODE'}}'''.replace('COMPONENTS',json.dumps((PROJECT/'qml/components').as_uri()))).encode(),QUrl())
        self.assertTrue(component.isReady(),[error.toString() for error in component.errors()])
        window=component.create();workspace=window.findChild(QQuickItem,'testWorkspace')
        loader=workspace.findChild(QQuickItem,'workspaceResearchPane')
        self.assertIsNone(loader.property('item'))
        expression=QQmlExpression(qmlContext(workspace),workspace,"openResearch('EVIDENCE')")
        expression.evaluate();self.assertFalse(expression.hasError(),expression.error().toString());self.app.processEvents()
        research=loader.property('item');self.assertIsNotNone(research,warnings)
        self.assertEqual(research.property('page'),'EVIDENCE')
        self.assertEqual(workspace.property('pendingResearchSection'),'')
        research.setProperty('taskTitle','Keep this unfinished fixture')
        workspace.setProperty('hostKind','CODE');self.app.processEvents()
        self.assertIs(loader.property('item'),research);self.assertFalse(loader.isVisible())
        workspace.setProperty('hostKind','RESEARCH');self.app.processEvents()
        self.assertIs(loader.property('item'),research)
        self.assertEqual(research.property('taskTitle'),'Keep this unfinished fixture')
        self.assertFalse(warnings,warnings)
        window.deleteLater();engine.deleteLater();self.app.processEvents()


if __name__=='__main__':unittest.main()
