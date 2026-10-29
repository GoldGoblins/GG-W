"""Real QML group coloring, bounded temporary preferences and no network/node.

The dashboard receives public synthetic state. Mouse operations only exercise
the color popup. Any financial/action signal is counted and must remain zero.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ.setdefault('QT_QUICK_BACKEND','software')
os.environ.setdefault('QT_QUICK_CONTROLS_STYLE','Basic')
from PySide6.QtCore import QObject,QPointF,Qt,QUrl
from PySide6.QtGui import QGuiApplication,QFont,QFontDatabase
from PySide6.QtQml import QQmlComponent,QQmlEngine,QQmlExpression,qmlContext
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from shiboken6 import getCppPointer,wrapInstance
from backend.ui_color_customization import UiColorController

ROOT=Path(__file__).resolve().parents[1]


class UiColorGroupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QGuiApplication.instance() or QGuiApplication([])
        family='Consolas' if os.name=='nt' else 'DejaVu Sans Mono'
        if os.name=='nt':
            for name in ('consola.ttf','consolab.ttf','seguisym.ttf'):
                QFontDatabase.addApplicationFont(str(Path(os.environ.get('SystemRoot','C:/Windows'))/'Fonts'/name))
        QFont.insertSubstitution('monospace',family);cls.app.setFont(QFont(family))

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='gg-color-groups-fixture-')
        self.addCleanup(self.temp.cleanup)
        self.controller=UiColorController(path=Path(self.temp.name)/'colors.json')
        self.engine=QQmlEngine();self.engine.rootContext().setContextProperty('fixtureColors',self.controller)
        self.warnings=[]
        self.engine.warnings.connect(lambda values:self.warnings.extend(value.toString() for value in values))
        self.component=QQmlComponent(self.engine)
        self.window=None

    def tearDown(self):
        if self.window is not None:
            self.js(self.window,'GG.GGColorContext.backend=null;GG.GGColorContext.hostOverlay=null')
            self.window.setVisible(False);self.window.deleteLater()
        self.engine.deleteLater();self.app.processEvents()
        self.assertFalse(self.warnings,self.warnings)

    def js(self,item,code):
        expression=QQmlExpression(qmlContext(item),item,code);value=expression.evaluate()
        self.assertFalse(expression.hasError(),expression.error().toString())
        self.app.processEvents()
        return value[0] if isinstance(value,tuple) and len(value)==2 and isinstance(value[1],bool) else value

    def create(self,body):
        source='''import QtQuick
import QtQuick.Controls
import COMPONENTS as GG
Window {
 id:window;width:1200;height:800;visible:true
 property int actionCount:0
 property var fixtureState:({})
 property color probeBaseColor:'#87afd7'
 property real probeFraction:0.25
 Component.onCompleted:{GG.GGColorContext.backend=fixtureColors;GG.GGColorContext.hostOverlay=window.contentItem}
 BODY
}'''.replace('COMPONENTS',json.dumps((ROOT/'qml/components').as_uri())).replace('BODY',body)
        self.component.setData(source.encode('utf-8'),QUrl.fromLocalFile(str(ROOT/'qml/ui-color-group-fixture.qml')))
        self.assertTrue(self.component.isReady(),[error.toString() for error in self.component.errors()])
        self.window=self.component.create();self.assertIsNotNone(self.window)
        self.settle();return self.window

    def settle(self):QTest.qWait(30);self.app.processEvents()

    @staticmethod
    def as_item(value):
        return value if isinstance(value,QQuickItem) else wrapInstance(getCppPointer(value)[0],QQuickItem)

    def visual_items(self,start=None):
        pending=[start or self.window.contentItem()];result=[];seen=set()
        while pending:
            current=self.as_item(pending.pop())
            key=getCppPointer(current)[0]
            if key in seen:continue
            seen.add(key);result.append(current);pending.extend(current.childItems())
        return result

    def item(self,name):
        found=[item for item in self.visual_items() if item.objectName()==name]
        self.assertTrue(found,name);return found[0]

    def click(self,item,button=Qt.LeftButton,x=None,y=None):
        item=self.as_item(item)
        self.assertTrue(item.isVisible() and item.isEnabled(),item.objectName())
        point=item.mapToScene(QPointF(item.width()/2 if x is None else x,item.height()/2 if y is None else y))
        QTest.mouseClick(self.window,button,Qt.NoModifier,point.toPoint());self.settle()

    def popup(self):return self.js(self.window,'GG.GGColorContext.popup')

    def popup_item(self,name):
        content=self.js(self.window,'GG.GGColorContext.popup.contentItem')
        found=[item for item in self.visual_items(content) if item.objectName()==name]
        self.assertTrue(found,name);return found[0]

    def choose(self,color):
        popup=self.popup();self.assertTrue(popup.property('visible'))
        content=self.js(self.window,'GG.GGColorContext.popup.contentItem')
        cells=[item for item in self.visual_items(content)
               if item.objectName()=='uiColorSwatch' and item.property('modelData')==color]
        self.assertEqual(len(cells),1);self.click(cells[0])
        self.assertFalse(popup.property('visible'))

    def group_targets(self,key):
        return [item for item in self.visual_items() if item.property('resolvedKey')==key]

    def fill_color(self,target):
        return target.property('target').property('color').name()

    @staticmethod
    def state():
        return {'testnet':{
            'state':'RUNNING','available':True,'production':False,'chain_number':31337,
            'binding':'LOOPBACK_ONLY','height':8,'session_transactions':0,'transaction_limit':256,
            'engine':'Hardhat','accounts':[
                {'address':'0x'+str(i)*40,'native':'10000','token':'0'} for i in range(1,5)],
            'contract':'0x'+'a'*40,'gas_used':21000,'gas_limit':30000000,'base_fee_wei':'1',
            'measurements':[
                {'operation':kind,'elapsed_ms':elapsed,'observed_at':1,'state':'PASS'}
                for kind,elapsed in (('rpc',2),('transaction',7),('rpc',4),('self_test',5),('rpc',3))],
            'transactions':[],'events':[],'block_graph':{},
            'resource_metrics':{'memory_committed_bytes':128*1048576,'cpu_seconds':3},
            'resource_limits':{'verified':True,'memory_bytes':512*1048576,'cpu_seconds':300}}}

    def test_actual_dashboard_rpc_legend_colors_group_and_text_range_stays_separate(self):
        self.create('''GG.GGTestnetDashboard {
 id:dashboard;objectName:'fixtureDashboard';anchors.fill:parent;state:window.fixtureState
 onActionRequested:window.actionCount++
}''')
        self.window.setProperty('fixtureState',self.state());self.settle()
        key='ui.chart.testnet.rpc'
        group=self.group_targets(key);self.assertEqual(len(group),4)
        baseline=[self.fill_color(target) for target in group]
        legend=min(group,key=lambda target:target.width())
        self.assertEqual(legend.width(),5)
        self.click(legend,Qt.RightButton)
        self.assertEqual(self.popup().property('targetKey'),key)
        self.choose('#ff0000')
        self.assertEqual([self.fill_color(target) for target in group],['#ff0000']*4)
        other=self.group_targets('ui.chart.testnet.transaction')
        self.assertEqual(len(other),2)
        self.assertTrue(all(self.fill_color(target)!='#ff0000' for target in other))
        legend_row=self.as_item(legend.property('target')).parentItem()
        labels=[item for item in self.visual_items(legend_row) if item.property('text')=='RPC' and item.property('effectiveColorKey')]
        self.assertEqual(len(labels),1);label=labels[0]
        self.click(label,Qt.RightButton)
        self.assertTrue(self.popup().property('hasRange'))
        self.assertEqual((self.popup().property('rangeStart'),self.popup().property('rangeEnd')),(0,3))
        self.choose('#ffffff')
        styled=json.loads(self.controller.styleFor(label.property('effectiveColorKey'),'RPC'))
        self.assertEqual(styled['ranges'],[{'start':0,'end':3,'color':'#ffffff'}])
        self.assertEqual(styled['color'],'')
        self.assertEqual(label.property('text'),'RPC')
        category_labels=[item for item in self.visual_items()
                         if str(item.property('colorKey') or '').startswith('ui.chartlabel.testnet.')]
        self.assertEqual(len({item.property('effectiveColorKey') for item in category_labels}),3)
        for peer in category_labels:
            if peer is not label:
                self.assertEqual(json.loads(self.controller.styleFor(peer.property('effectiveColorKey'),peer.property('text')))['ranges'],[])
        self.assertEqual([self.fill_color(target) for target in group],['#ff0000']*4)
        self.click(legend,Qt.RightButton);self.click(self.popup_item('uiColorReset'))
        self.assertEqual([self.fill_color(target) for target in group],baseline)
        self.assertEqual(self.window.property('actionCount'),0)

    def test_actual_dashboard_percentage_mode_tracks_known_fraction_and_unknown_is_neutral(self):
        self.create('''GG.GGTestnetDashboard {
 objectName:'fixtureDashboard';anchors.fill:parent;state:window.fixtureState
 onActionRequested:window.actionCount++
}''')
        state=self.state();self.window.setProperty('fixtureState',state);self.settle()
        key='ui.meter.testnet.testnetMemoryBar'
        targets=self.group_targets(key);self.assertEqual(len(targets),1);target=targets[0]
        self.assertAlmostEqual(target.property('fraction'),0.25)
        self.click(target,Qt.RightButton)
        self.assertTrue(self.popup().property('percentageCapable'))
        self.click(self.popup_item('uiColorScale_risk'))
        self.assertEqual(self.fill_color(target),'#00ff87')
        state=deepcopy(state);state['testnet']['resource_metrics']['memory_committed_bytes']=512*1048576
        self.window.setProperty('fixtureState',state);self.settle()
        self.assertEqual(self.fill_color(target),'#ff0000')
        state=deepcopy(state);state['testnet']['resource_metrics']['memory_committed_bytes']=None
        self.window.setProperty('fixtureState',state);self.settle()
        self.assertEqual(self.fill_color(target),'#858585')
        self.click(target,Qt.RightButton);self.click(self.popup_item('uiColorScale_progress'))
        state=deepcopy(state);state['testnet']['resource_metrics']['memory_committed_bytes']=512*1048576
        self.window.setProperty('fixtureState',state);self.settle()
        self.assertEqual(self.fill_color(target),'#afd7ff')
        self.assertEqual(self.window.property('actionCount'),0)

    def test_target_reset_restores_native_binding_and_gradient_has_no_static_override(self):
        self.create('''Rectangle {
 id:probe;objectName:'probe';x:20;y:20;width:400;height:30;color:window.probeBaseColor
 GG.GGColorTarget {objectName:'probeColorTarget';colorKey:'ui.fixture.meter';percentageCapable:true;fraction:window.probeFraction}
}''')
        target=self.item('probeColorTarget');probe=self.item('probe')
        self.assertFalse(target.property('customized'))
        self.assertEqual(probe.property('color').name(),'#87afd7')
        self.click(target,Qt.RightButton);self.choose('#ff0000')
        self.assertEqual(probe.property('color').name(),'#ff0000')
        self.window.setProperty('probeBaseColor','#ffffff');self.settle()
        self.assertEqual(probe.property('color').name(),'#ff0000')
        self.click(target,Qt.RightButton);self.click(self.popup_item('uiColorReset'))
        self.assertFalse(target.property('customized'))
        self.assertEqual(probe.property('color').name(),'#ffffff')
        self.window.setProperty('probeBaseColor','#000000');self.settle()
        self.assertEqual(probe.property('color').name(),'#000000')
        self.click(target,Qt.RightButton);self.click(self.popup_item('uiColorScale_risk'))
        self.assertEqual(probe.property('color').name(),'#00ff87')
        self.window.setProperty('probeFraction',1.0);self.settle()
        self.assertEqual(probe.property('color').name(),'#ff0000')
        self.window.setProperty('probeFraction',float('nan'));self.settle()
        self.assertEqual(probe.property('color').name(),'#858585')
        self.click(target,Qt.RightButton);self.click(self.popup_item('uiColorReset'))
        self.assertEqual(probe.property('color').name(),'#000000')
        self.assertFalse(self.controller.registry.entries)


if __name__=='__main__':unittest.main()
