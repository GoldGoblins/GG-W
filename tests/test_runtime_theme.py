"""Real settings clicks, reactive shared consumers and isolated persistence."""
import json,os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ.setdefault('QT_QUICK_BACKEND','software')
from PySide6.QtCore import QObject,QPointF,Qt,QUrl,Slot
from PySide6.QtGui import QGuiApplication,QFont,QFontDatabase
from PySide6.QtQml import QQmlComponent,QQmlEngine,QQmlExpression,qmlContext
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from backend import desktop_settings as settings

ROOT=Path(__file__).resolve().parents[1]
DATA=json.loads((ROOT/'config/gg-palette.json').read_text())

class RoleSettingsTests(unittest.TestCase):
    def test_roles_are_bounded_to_known_keys_and_canonical64_without_mutating_input(self):
        raw={'positive':DATA['colors'][2].upper(),'negative':'#123456','info':DATA['colors'][16],
             'frameBorder':'#ffffff','__proto__':'#ff0000','accent':17}
        saved=json.dumps(raw)
        result=settings.normalize_settings({'paletteRoles':raw,'frameBorder':'#123456','frameRadius':7})
        self.assertEqual(result['paletteRoles'],{'positive':DATA['colors'][2],'info':DATA['colors'][16]})
        self.assertEqual(result['frameBorder'],'#123456');self.assertEqual(result['frameRadius'],7)
        self.assertEqual(json.dumps(raw),saved)
        for invalid in (None,[],42,'positive'):
            self.assertEqual(settings.normalize_settings({'paletteRoles':invalid})['paletteRoles'],{})
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'settings.json'
            one=settings.load_settings(path);one['paletteRoles']['positive']=DATA['colors'][2]
            self.assertEqual(settings.load_settings(path)['paletteRoles'],{})
    def test_all64_swatch_values_and_legacy_values_roundtrip(self):
        for value in DATA['colors']+DATA['legacy_colors']:
            with self.subTest(color=value):
                raw={'paletteRoles':{'negative':value.upper()}}
                self.assertEqual(settings.normalize_settings(raw)['paletteRoles'],{'negative':value})
        for value in ('#ff0000','#ffffff','#000000','#121212','#eeeeee'):
            self.assertIn(value,DATA['colors'])

class Host(QObject):
    def __init__(self,path):super().__init__();self.path=path;self.saves=0
    @Slot(str,result=str)
    def save(self,raw):self.saves+=1;return settings.save_settings(json.loads(raw),self.path)
    @Slot(result=str)
    def load(self):return json.dumps(settings.load_settings(self.path))

class RuntimeThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QGuiApplication.instance() or QGuiApplication([])
        if os.name=='nt':
            for name in ('consola.ttf','consolab.ttf','seguisym.ttf'):
                QFontDatabase.addApplicationFont(str(Path(os.environ.get('SystemRoot','C:/Windows'))/'Fonts'/name))
        family='Consolas' if os.name=='nt' else 'DejaVu Sans Mono'
        QFont.insertSubstitution('monospace',family);cls.app.setFont(QFont(family))
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='gg-runtime-theme-fixture-');self.addCleanup(self.temp.cleanup)
        self.host=Host(Path(self.temp.name)/'settings.json');self.engines=[];self.components=[];self.windows=[];self.warnings=[]
    def tearDown(self):
        for window in self.windows:window.setVisible(False);window.deleteLater()
        for engine in self.engines:engine.deleteLater()
        self.app.processEvents()
        self.assertFalse(self.warnings,self.warnings)
    def js(self,item,code):
        call=QQmlExpression(qmlContext(item),item,code);value=call.evaluate()
        self.assertFalse(call.hasError(),call.error().toString());self.app.processEvents()
        return value[0] if isinstance(value,tuple) and len(value)==2 and isinstance(value[1],bool) else value
    def create(self):
        engine=QQmlEngine();self.engines.append(engine);engine.rootContext().setContextProperty('fixtureHost',self.host)
        engine.warnings.connect(lambda rows:self.warnings.extend(r.toString() for r in rows))
        component=QQmlComponent(engine)
        self.components.append(component)
        source='''import QtQuick
import COMPONENTS
import COMPONENTS as RuntimeTheme
Window {
    id:controller;width:800;height:660;visible:true
    property var paletteRoles:JSON.parse(fixtureHost.load()).paletteRoles || ({})
    onPaletteRolesChanged:RuntimeTheme.GGTheme.setOverrides(paletteRoles)
    function persist(){fixtureHost.save(JSON.stringify({paletteRoles:paletteRoles,frameBorder:'#777777',frameRadius:6}))}
    Text {objectName:'successConsumer';color:RuntimeTheme.GGTheme.positive;text:'Public synthetic success'}
    Text {objectName:'errorConsumer';color:RuntimeTheme.GGTheme.negative}
    Text {objectName:'infoConsumer';color:RuntimeTheme.GGTheme.info}
    SettingsPopup {id:popup;objectName:'popup';width:760;height:620;visible:true;page:'APPEARANCE'
        paletteRoles:controller.paletteRoles;frameBorder:'#777777';frameRadius:6
        onPaletteRolesChangedByUser:function(value){controller.paletteRoles=value;controller.persist()}
        onAccentColorChangedByUser:function(value){RuntimeTheme.GGTheme.legacyAccent=value}
    }
}'''.replace('COMPONENTS',json.dumps((ROOT/'qml/components').as_uri()))
        component.setData(source.encode(),QUrl.fromLocalFile(str(ROOT/'qml/runtime-theme-public-fixture.qml')))
        self.assertTrue(component.isReady(),[r.toString() for r in component.errors()])
        window=component.create();self.assertIsNotNone(window);self.windows.append(window)
        QTest.qWait(90);self.app.processEvents();return window
    def item(self,window,name):
        item=window.findChild(QQuickItem,name);self.assertIsNotNone(item,name);return item
    def click(self,window,item):
        self.assertTrue(item.isVisible() and item.isEnabled())
        QTest.mouseClick(window,Qt.LeftButton,Qt.NoModifier,item.mapToScene(QPointF(item.width()/2,item.height()/2)).toPoint());QTest.qWait(20)
    def test_actual_settings_role_click_repaints_live_persists_reloads_and_resets(self):
        window=self.create();module=self.item(window,'settingsAppearanceModule')
        selector=self.item(window,'appearanceRoleSelector');swatches=self.item(window,'appearanceSwatches')
        cells=swatches.findChildren(QQuickItem,'appearanceRoleSwatch')
        # Repeater delegates are visual children, not always QObject children.
        if len(cells)!=64:
            cells=[i for i in swatches.childItems() if i.objectName()=='appearanceRoleSwatch']
        self.assertEqual(len(cells),64)
        cells.sort(key=lambda i:i.property('index'))
        good=self.item(window,'successConsumer');bad=self.item(window,'errorConsumer');info=self.item(window,'infoConsumer')
        defaults=(good.property('color').name(),bad.property('color').name(),info.property('color').name())
        self.assertEqual(defaults,('#87af87','#d78787','#87afd7'))
        self.click(window,cells[2]);self.assertEqual(good.property('color').name(),DATA['colors'][2])
        self.assertEqual(bad.property('color').name(),defaults[1]);self.assertEqual(self.host.saves,1)
        self.assertEqual(settings.load_settings(self.host.path)['paletteRoles'],{'positive':DATA['colors'][2]})
        evidence=os.environ.get('GG_THEME_EVIDENCE')
        if evidence:
            directory=Path(evidence);directory.mkdir(parents=True,exist_ok=True)
            self.assertTrue(window.grabWindow().save(str(directory/'appearance-semantic-64.png')))
        selector.setProperty('currentIndex',4);self.app.processEvents();self.click(window,cells[0])
        self.assertEqual(bad.property('color').name(),DATA['colors'][0]);self.assertEqual(good.property('color').name(),DATA['colors'][2])
        QTest.keyClick(window,Qt.Key_Right);QTest.keyClick(window,Qt.Key_Space);QTest.qWait(20)
        self.assertEqual(bad.property('color').name(),DATA['colors'][1])
        other=self.create()
        self.assertEqual(self.item(other,'successConsumer').property('color').name(),DATA['colors'][2])
        self.assertEqual(self.item(other,'errorConsumer').property('color').name(),DATA['colors'][1])
        popup=self.item(other,'popup');self.assertEqual(popup.property('frameBorder').name(),'#777777');self.assertEqual(popup.property('frameRadius'),6)
        self.click(other,self.item(other,'appearanceResetRole'))
        self.assertEqual(self.item(other,'successConsumer').property('color').name(),defaults[0])
        self.assertEqual(self.item(other,'errorConsumer').property('color').name(),DATA['colors'][1])
        self.click(other,self.item(other,'appearanceResetRoles'))
        self.assertEqual(self.item(other,'errorConsumer').property('color').name(),defaults[1])
        self.assertEqual(settings.load_settings(self.host.path)['paletteRoles'],{})
        self.assertEqual(popup.property('frameBorder').name(),'#777777');self.assertEqual(popup.property('frameRadius'),6)
    def test_runtime_alias_rejects_unknown_roles_and_off_palette_override(self):
        window=self.create()
        self.js(window,"RuntimeTheme.GGTheme.setOverrides({positive:'#123456',negative:'#87AFD7',badRole:'#87af87'})")
        self.assertEqual(self.item(window,'successConsumer').property('color').name(),'#87af87')
        self.assertEqual(self.item(window,'errorConsumer').property('color').name(),'#87afd7')
    def test_saturated_and_neutral_colors_update_consumer_and_actual_role_list_swatches(self):
        window=self.create();selector=self.item(window,'appearanceRoleSelector')
        swatches=self.item(window,'appearanceSwatches')
        cells=[i for i in swatches.childItems() if i.objectName()=='appearanceRoleSwatch']
        cells.sort(key=lambda i:i.property('index'))
        selector.setProperty('currentIndex',4);self.app.processEvents()
        for color in ('#ff0000','#ffffff','#000000'):
            self.click(window,cells[DATA['colors'].index(color)])
            self.assertEqual(self.item(window,'errorConsumer').property('color').name(),color)
            self.assertEqual(self.item(window,'appearanceRoleCurrentSwatch').property('color').name(),color)
        self.js(selector,'popup.open()');QTest.qWait(60)
        # Popup delegates are visual children of its ListView and are not
        # guaranteed to be QObject descendants of the main Window.
        options=[self.js(selector,'popup.contentItem.itemAtIndex('+str(i)+')') for i in range(10)]
        self.assertTrue(all(options))
        for index,option in enumerate(options):
            dot=self.js(selector,'popup.contentItem.itemAtIndex('+str(index)+').contentItem.children.filter(function(item){return item.objectName==="appearanceRoleOptionSwatch"})[0]')
            self.assertIsNotNone(dot)
            expected='#000000' if index==4 else DATA['roles'][('accent','info','positive','warning','negative','blue','cyan','purple','orange','pink')[index]]
            self.assertEqual(dot.property('color').name(),expected)
        evidence=os.environ.get('GG_THEME_EVIDENCE')
        if evidence:
            directory=Path(evidence);directory.mkdir(parents=True,exist_ok=True)
            self.assertTrue(window.grabWindow().save(str(directory/'appearance-role-menu-64.png')))
        self.click(window,options[2]);self.assertEqual(selector.property('currentIndex'),2)
        self.assertEqual(self.item(window,'appearanceRoleCurrentSwatch').property('color').name(),DATA['roles']['positive'])
        other=self.create();self.assertEqual(self.item(other,'errorConsumer').property('color').name(),'#000000')

if __name__=='__main__':unittest.main()
