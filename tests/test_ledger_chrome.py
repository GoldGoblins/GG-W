"""Pixel/idle checks for transparent, retained desktop chrome (synthetic UI only)."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]


def fixture(directory: Path):
    from PySide6.QtCore import QPointF, QUrl
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression, qmlContext
    from PySide6.QtQuick import QQuickItem
    from PySide6.QtTest import QSignalSpy, QTest
    from PySide6.QtWidgets import QApplication

    app = QApplication([])
    if os.name == 'nt':
        QFontDatabase.addApplicationFont(str(Path(os.environ['SystemRoot']) / 'Fonts/consola.ttf'))
    QFont.insertSubstitution('monospace', 'Consolas' if os.name == 'nt' else 'DejaVu Sans Mono')
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty('nativeHardware', os.environ.get('GG_LEDGER_HARDWARE') == '1')
    warnings = []
    engine.warnings.connect(lambda rows: warnings.extend(e.toString() for e in rows))
    path = directory / 'fixture.qml'
    path.write_text('''import QtQuick
import QtQuick.Controls
import COMPONENTS
import "GEOMETRY" as Geometry
ApplicationWindow {
    id: window; width:1000; height:800; visible:true; color:'#111111'
    x:nativeHardware?-10000:0;y:nativeHardware?-10000:0
    flags:nativeHardware?(Qt.Tool|Qt.FramelessWindowHint|Qt.WindowDoesNotAcceptFocus):Qt.Window
    property bool sampleVisible:true
    property bool gallery:false
    property var geometryProbe: Geometry.segments(0,100,[{start:-9,end:12},{start:35,end:55},{start:20,end:40},{start:90,end:150},{start:70,end:70}])
    Repeater {model:32; Rectangle {required property int index;x:index*32;width:32;height:window.height;color:index%2?'#263645':'#39452c';visible:!window.gallery}}
    GgFrame {
        id: sample; objectName:'sample';x:32;y:40;width:window.width-64;height:150
        visible:window.sampleVisible&&!window.gallery
        backgroundColor:'transparent';borderColor:'#ffffff'
        leftLegend:'CHAT · TEST';rightLegend:'BRIDGE · CONNECTED'
        bottomLeftLegend:'CODE | CRYPTO | TMOG';bottomRightLegend:'READY'
        topGaps:[{start:240,end:310},{start:275,end:325}]
        bottomGaps:[{start:270,end:340}]
    }
    Item {
        visible:window.gallery;anchors.fill:parent
        GgFrame {x:12;y:20;width:window.width-24;height:60;leftLegend:'GG AI DESKTOP · ALPHA';rightLegend:'−   □   ×'}
        GgFrame {x:12;y:102;width:window.width*.40-20;height:300;leftLegend:'CHAT · UNIVERSAL OPERATIONAL STREAM';rightLegend:'BRIDGE · CONNECTED'}
        GgFrame {x:window.width*.40+8;y:102;width:window.width*.60-20;height:300;leftLegend:'CRYPTO';rightLegend:'ALLA NÄTVERK · PUBLIK DATA'
            Text {text:'Isolerad ritkontroll · inga konton eller nätverksanrop';color:'#a3a3a3';font.family:'monospace';font.pixelSize:11}
        }
        TmogCard {objectName:'modelCard';x:12;y:430;width:window.width*.48-20;height:100;leftLegend:'MODEL';rightLegend:'READY'}
        TmogCard {objectName:'tabCard';x:window.width*.48+8;y:430;width:window.width*.52-20;height:100;tabs:[{id:'CPU',label:'CPU'},{id:'RAM',label:'RAM'}];activeTab:'CPU';rightLegend:'TEST'}
        TmogRail {objectName:'bridgeRail';x:12;y:554;width:window.width-24;leftLegend:'BRIDGE';rightLegend:'CONNECTED'}
        UtilitySurface {objectName:'mediaUtility';x:12;y:600;width:window.width-24;height:150}
        Row {objectName:'glyphRow';x:24;y:462;spacing:14
            Repeater {model:['lock','shield','backup','copy','clock','endpoint','network','refresh','key','document'];LedgerGlyph {required property string modelData;name:modelData;width:20;height:20}}
        }
    }
    SettingsPopup {objectName:'settings';visible:false;x:20;y:30;width:760;height:700}
    WalletPopup {objectName:'wallet';visible:false;x:20;y:30;width:460;height:700}
}
'''.replace('COMPONENTS', json.dumps((PROJECT/'qml/components').as_uri()))
       .replace('GEOMETRY', (PROJECT/'qml/components/LedgerGeometry.js').as_uri()), encoding='utf-8')
    engine.load(QUrl.fromLocalFile(str(path)))
    assert engine.rootObjects(), warnings
    window = engine.rootObjects()[0]
    QTest.qWait(150)
    sample = window.findChild(QQuickItem, 'sample')
    assert sample is not None
    # Merging/clamping is also exercised by the native pixels below.
    probe = window.property('geometryProbe').toVariant()
    assert probe == [{'start':12,'end':20},{'start':55,'end':90}], probe
    window.setProperty('sampleVisible', False)
    QTest.qWait(50)
    baseline = window.grabWindow()
    window.setProperty('sampleVisible', True)
    QTest.qWait(80)
    painted = window.grabWindow()
    # Offscreen Qt can return physical pixels with image DPR metadata of1.
    dpr = painted.width() / window.width()

    def pixel(image, x, y):
        return image.pixelColor(int(x*dpr), int(y*dpr)).name()

    # A patterned parent must show through the caption clearance, not a plate.
    for name in ('frameLeftCaption','frameRightCaption','frameBottomLeftCaption','frameBottomRightCaption'):
        caption = sample.findChild(QQuickItem, name)
        assert caption is not None and caption.width() > 0
        point = caption.mapToScene(QPointF(2, 2))
        assert pixel(painted, point.x(), point.y()) == pixel(baseline, point.x(), point.y()), name
        assert caption.property('color') is None, name
    for x, y in ((32+250,40),(32+315,40),(32+300,189)):
        assert pixel(painted,x,y) == pixel(baseline,x,y), (x,y,'gap painted')
    assert pixel(painted,32+210,40) != pixel(baseline,32+210,40), 'surviving edge missing'
    assert pixel(painted,32,100) != pixel(baseline,32,100), 'side missing'
    assert any(pixel(painted,32+x,40+y)!=pixel(baseline,32+x,40+y)
               for x in (1,2,3) for y in (1,2,3)), 'rounded corner missing'
    # Longer live status text updates its own opening; the two captions cannot collide.
    for width in (180,320,820,1586):
        sample.setWidth(width)
        sample.setProperty('leftLegend','CHAT · UNIVERSAL OPERATIONAL STREAM')
        sample.setProperty('rightLegend','BRIDGE · CONNECTED · TEST STATUS')
        QTest.qWait(15)
        left=sample.findChild(QQuickItem,'frameLeftCaption');right=sample.findChild(QQuickItem,'frameRightCaption')
        assert left.x()+left.width() <= right.x()+0.1, (width,left.width(),right.x())
    sample.setWidth(window.width()-64)
    QTest.qWait(80)
    swaps=QSignalSpy(window.frameSwapped)
    QTest.qWait(250)
    idle_swaps=swaps.count()
    assert idle_swaps == 0, ('idle chrome continuously rendered',idle_swaps)
    from PySide6.QtQuick import QSGRendererInterface
    api=window.rendererInterface().graphicsApi()
    if os.environ.get('GG_LEDGER_HARDWARE')=='1':
        assert api==QSGRendererInterface.GraphicsApi.Direct3D11, str(api)
    output=os.environ.get('GG_LEDGER_UI_EVIDENCE')
    if output:
        out=Path(output);out.mkdir(parents=True,exist_ok=True)
        window.grabWindow().save(str(out/('ledger-transparent-'+os.environ.get('QT_SCALE_FACTOR','1')+'.png')))
    window.setProperty('gallery',True)
    # Actual custom panels, including compact labels and overflowed clickable tabs.
    for name,left_name,right_name in (
        ('modelCard','tmogCardLeftCaption','tmogCardRightCaption'),
        ('tabCard','tmogCardTabsCaption','tmogCardRightCaption'),
        ('bridgeRail','tmogRailLeftCaption','tmogRailRightCaption'),
        ('mediaUtility','utilityLeftCaption','utilityRightCaption')):
        panel=window.findChild(QQuickItem,name)
        for width in (120,168,430):
            panel.setWidth(width)
            if name=='modelCard':panel.setProperty('compactLegend',width==120)
            QTest.qWait(15)
            left=panel.findChild(QQuickItem,left_name);right=panel.findChild(QQuickItem,right_name)
            assert left.x()>=0 and right.x()+right.width()<=width+0.1,(name,width,'bounds')
            assert left.x()+left.width()<=right.x()+0.1,(name,width,'collision')
        # Restore its gallery layout binding for the render.
        ratio={'modelCard':'.48-20','tabCard':'.52-20','bridgeRail':'-24','mediaUtility':'-24'}[name]
        expression=QQmlExpression(qmlContext(panel),panel,'width = Qt.binding(function() { return parent.width'+('*'+ratio if ratio.startswith('.') else ratio)+' })')
        expression.evaluate();assert not expression.hasError(),expression.error().toString()
    if output:
        for width in (820,1586):
            window.setWidth(width);QTest.qWait(100)
            window.grabWindow().save(str(out/('ledger-gallery-'+str(width)+'-'+os.environ.get('QT_SCALE_FACTOR','1')+'.png')))
    QTest.qWait(100)
    icon_frame=window.grabWindow()
    icon_ratio=icon_frame.width()/window.width()
    for index in range(10):
        pixels=[icon_frame.pixelColor(int(x*icon_ratio),int(y*icon_ratio)).name()
                for x in range(24+index*34,44+index*34) for y in range(462,482)]
        assert any(p not in ('#161616','#141414','#111111') for p in pixels), ('vector icon missing',index,str(api))
    if output:
        for name in ('settings','wallet'):
            popup=window.findChild(QQuickItem,name);popup.setVisible(True);QTest.qWait(100)
            window.grabWindow().save(str(out/('ledger-'+name+'-'+os.environ.get('QT_SCALE_FACTOR','1')+'.png')))
            popup.setVisible(False)
    assert not warnings,warnings
    window.close()
    engine.deleteLater();app.processEvents()
    print(json.dumps({'status':'PASS','scale':os.environ.get('QT_SCALE_FACTOR','1'),'idle_swaps':idle_swaps,'qml_warnings':0,'graphics_api':str(api)}))


class LedgerChromeTests(unittest.TestCase):
    def test_real_gaps_transparency_dynamic_fit_and_idle_at_display_scales(self):
        for scale in ('1','1.25','1.5','2'):
            with self.subTest(scale=scale), tempfile.TemporaryDirectory(prefix='gg-ledger-chrome-') as temporary:
                env=os.environ.copy()
                env.update(QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software',QT_QUICK_CONTROLS_STYLE='Basic',
                           QT_SCALE_FACTOR=scale,GG_DESKTOP_STATE_ROOT=str(Path(temporary)/'state'),GG_DESKTOP_DATA_ROOT=str(Path(temporary)/'data'))
                result=subprocess.run([sys.executable,'-B',str(Path(__file__).resolve()),'--fixture',temporary],cwd=PROJECT,
                                      env=env,capture_output=True,text=True,encoding='utf-8',timeout=25)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                print(result.stdout.strip())

    @unittest.skipUnless(os.name=='nt','Windows native Direct3D11 coverage')
    def test_retained_chrome_on_native_direct3d(self):
        with tempfile.TemporaryDirectory(prefix='gg-ledger-d3d-') as temporary:
            env=os.environ.copy()
            env.pop('QT_QUICK_BACKEND',None)
            env.update(QT_QPA_PLATFORM='windows',QSG_RHI_BACKEND='d3d11',QT_QUICK_CONTROLS_STYLE='Basic',QT_SCALE_FACTOR='1',
                       GG_LEDGER_HARDWARE='1',GG_DESKTOP_STATE_ROOT=str(Path(temporary)/'state'),GG_DESKTOP_DATA_ROOT=str(Path(temporary)/'data'))
            destination=env.get('GG_LEDGER_UI_EVIDENCE')
            if destination:env['GG_LEDGER_UI_EVIDENCE']=str(Path(destination)/'direct3d')
            result=subprocess.run([sys.executable,'-B',str(Path(__file__).resolve()),'--fixture',temporary],cwd=PROJECT,
                                  env=env,capture_output=True,text=True,encoding='utf-8',timeout=25)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            print(result.stdout.strip())


if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--fixture':fixture(Path(sys.argv[2]))
    else:unittest.main()
