"""Offscreen activity colours preserve real activity and native off states.

Only disposable cosmetic preferences are used. No telemetry backend, network,
node, real user preference or native preview is opened by these fixtures.
"""
import json
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ.setdefault('QT_QUICK_BACKEND','software')
os.environ.setdefault('QT_QUICK_CONTROLS_STYLE','Basic')
from PySide6.QtCore import QPointF, Qt, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlComponent, QQmlEngine, QQmlExpression, qmlContext
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from backend.ui_color_customization import UiColorController

ROOT=Path(__file__).resolve().parents[1]


class ActivityColourBindings(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QGuiApplication.instance() or QGuiApplication([])

    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(prefix='gg-activity-colours-')
        self.addCleanup(self.temporary.cleanup)
        self.controller=UiColorController(path=Path(self.temporary.name)/'colours.json')
        self.engine=QQmlEngine();self.component=QQmlComponent(self.engine)
        self.engine.rootContext().setContextProperty('fixtureColours',self.controller)
        self.warnings=[];self.window=None
        self.engine.warnings.connect(lambda rows:self.warnings.extend(row.toString() for row in rows))

    def js(self,code,owner=None):
        owner=owner or self.window
        expression=QQmlExpression(qmlContext(owner),owner,code)
        result=expression.evaluate()
        self.assertFalse(expression.hasError(),expression.error().toString())
        self.app.processEvents()
        result=result[0] if isinstance(result,tuple) else result
        return result.toVariant() if hasattr(result,'toVariant') else result

    def create(self,body):
        source='''import QtQuick
import QtQuick.Controls
import COMPONENTS as GG
Window {
 id:window;width:900;height:650;visible:true
 property bool actualActivity:false
 Component.onCompleted:{GG.GGColorContext.backend=fixtureColours;GG.GGColorContext.hostOverlay=window.contentItem}
 BODY
}'''.replace('COMPONENTS',json.dumps((ROOT/'qml/components').as_uri())).replace('BODY',body)
        self.component.setData(source.encode(),QUrl.fromLocalFile(str(ROOT/'qml/activity-colour-fixture.qml')))
        self.assertTrue(self.component.isReady(),[error.toString() for error in self.component.errors()])
        self.window=self.component.create();self.assertIsNotNone(self.window)
        QTest.qWait(20)

    def find(self,name,owner=None):
        item=(owner or self.window).findChild(QQuickItem,name)
        self.assertIsNotNone(item,name);return item

    def tearDown(self):
        if self.window is not None:
            self.js('if(GG.GGColorContext.popup)GG.GGColorContext.popup.close();GG.GGColorContext.backend=null;GG.GGColorContext.hostOverlay=null')
            self.window.close();self.window.deleteLater()
        self.engine.deleteLater();self.app.processEvents()
        self.assertFalse(self.warnings,self.warnings)

    def test_colour_only_changes_on_hue_and_linked_series_not_off_state(self):
        self.create('''
 GG.TmogCard {objectName:'card';x:12;y:20;width:300;height:140;leftLegend:'CPU';lamp:true;lampOn:window.actualActivity;lampColorKey:'ui.chart.tmog.cpu';lampOnColor:'#00aa00';lampOffColor:'#112211'
  GG.TmogSpark {objectName:'curve';anchors.fill:parent;values:[10,20,30];yMax:100;seriesColorKey:'ui.chart.tmog.cpu';stroke:'#00aa00';fill:'#1c2a22'}
 }
 GG.TmogMeter {objectName:'meter';x:12;y:170;width:300;ratio:.5;segments:4;onColor:'#00aa00';offColor:'#141414';seriesColorKey:'ui.chart.tmog.cpu'}
 ''')
        lamp=self.find('tmogActivityLamp');curve=self.find('curve');meter=self.find('meter')
        self.assertEqual(self.js('String(color)',lamp),'#112211')
        self.assertTrue(self.controller.setColor('ui.chart.tmog.cpu','#ff0000'))
        self.app.processEvents()
        self.assertEqual(self.js('String(color)',lamp),'#112211','Picking a colour cannot turn on an inactive lamp')
        self.assertEqual(self.js('String(seriesStroke)',curve),'#ff0000')
        self.assertEqual(self.js('String(seriesOnColor)',meter),'#ff0000')
        self.assertAlmostEqual(self.js('seriesFill.a',curve),self.js('fill.a',curve),places=5)
        self.assertAlmostEqual(self.js('seriesFill.hslLightness',curve),self.js('fill.hslLightness',curve),places=3)
        for active in (True,False,True,False,True,False):
            self.window.setProperty('actualActivity',active);self.app.processEvents()
            self.assertEqual(self.js('String(color)',lamp),'#ff0000' if active else '#112211')
        # Right-clicking an inactive lamp edits its on hue and the same
        # semantic series, while leaving the actual activity false.
        point=lamp.mapToScene(QPointF(lamp.width()/2,lamp.height()/2)).toPoint()
        QTest.mouseClick(self.window,Qt.RightButton,Qt.NoModifier,point);QTest.qWait(20)
        self.assertEqual(self.js('GG.GGColorContext.popup.targetKey'),'ui.chart.tmog.cpu')
        self.assertFalse(self.window.property('actualActivity'))
        self.js('GG.GGColorContext.popup.close()')
        self.assertTrue(self.controller.reset('ui.chart.tmog.cpu'))
        for active in (True,False,True,False):
            self.window.setProperty('actualActivity',active);self.app.processEvents()
            self.assertEqual(self.js('String(color)',lamp),'#00aa00' if active else '#112211')
        self.assertEqual(self.js('String(seriesStroke)',curve),'#00aa00')
        self.assertEqual(self.js('String(seriesOnColor)',meter),'#00aa00')

    def test_summary_lamps_follow_valid_sample_activity_and_unknown_gpu_is_off(self):
        self.create("GG.TmogSurface {objectName:'tmog';width:850;height:600;visible:false}")
        tmog=self.find('tmog')
        payload={'cpu_busy':24,'gpu_busy':18,'net_rx_bps':32,'net_tx_bps':16,
                 'disk_read_bps':2048,'disk_write_bps':1024,'mem_total_kb':1000,'mem_used_kb':400}
        for tick,expected in ((0,True),(3,False),(6,True),(9,False)):
            self.js('liveTicks='+str(tick)+';applyPulse('+json.dumps(payload)+',1/60)',tmog)
            for key in ('cpuLampOn','gpuLampOn','networkLampOn','diskLampOn'):
                self.assertEqual(tmog.property(key),expected,key)
        missing=dict(payload,gpu_busy=None,unavailable=['gpu_busy'])
        self.js('liveTicks=12;applyPulse('+json.dumps(missing)+',1/60)',tmog)
        self.assertFalse(tmog.property('gpuLampOn'))
        inactive=dict(payload,cpu_busy=0,gpu_busy=0,net_rx_bps=0,net_tx_bps=0,disk_read_bps=0,disk_write_bps=0)
        self.js('liveTicks=18;applyPulse('+json.dumps(inactive)+',1/60)',tmog)
        for key in ('cpuLampOn','gpuLampOn','networkLampOn','diskLampOn'):
            self.assertFalse(tmog.property(key),key)

    def test_chat_footer_lamp_colours_never_override_activity_or_blink_off(self):
        self.create('''GG.ContextComposer {objectName:'composer';width:720;height:120;engineTarget:'LOCAL_QWEN';gpuLampPresent:true
          cpuLampOn:window.actualActivity;gpuLampOn:window.actualActivity;netLampOn:window.actualActivity;
          diskLampOn:window.actualActivity;chatLampOn:window.actualActivity}''')
        names=['chatCpuLamp','chatGpuLamp','chatNetworkLamp','chatDiskLamp','chatActivityLamp']
        keys=['ui.fill.ContextComposer.'+str(index) for index in range(1,5)]+['ui.activity.stream']
        lamps=[self.find(name) for name in names]
        for key in keys:self.assertTrue(self.controller.setColor(key,'#ff0000'))
        for active in (False,True,False,True,False,True,False):
            self.window.setProperty('actualActivity',active);self.app.processEvents()
            for lamp in lamps:self.assertEqual(self.js('String(color)',lamp),'#ff0000' if active else '#2a1515')
        for key in keys:self.assertTrue(self.controller.reset(key))
        self.app.processEvents()
        for lamp in lamps:self.assertEqual(self.js('String(color)',lamp),'#2a1515')


if __name__=='__main__':unittest.main()
