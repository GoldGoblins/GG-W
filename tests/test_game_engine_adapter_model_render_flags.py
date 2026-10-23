"""Original M2 flags and live Lua texture policy through retained Qt materials.

Independently authored binary fixtures; these are CPU/API proofs, not GPU pixels.
"""
import os,struct,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import QObject,Property,QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlComponent,QQmlEngine
from backend.game_engine_adapter_formats import AssetCache,PROJECT
from backend.game_engine_presentation import Presentation
from tools.world import engine_format_fixtures as f
APP=QGuiApplication.instance() or QGuiApplication([])

def model_bytes(flags,texture='tint.tga',blend=2):
    data=bytearray(f.animated_m2(blend=blend,camera=False))
    material=struct.unpack_from('<II',data,0x84)[1]
    struct.pack_into('<HH',data,material,flags,blend)
    # Use a real fallback image without an authored BLP mip chain.
    old=b'gold.blp\0';new=texture.encode()+b'\0'
    if len(new)!=len(old):raise ValueError('Fixture texture name must be eight bytes')
    at=data.index(old);data[at:at+len(old)]=new
    return bytes(data)

class Provider(QObject):
    def __init__(self,rows):super().__init__();self.rows=rows
    @Property('QVariantList',constant=True)
    def batches(self):return self.rows

def number(value):return value.value if hasattr(value,'value') else int(value)

class ModelRenderFlags(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=PROJECT/'qml');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.cache=AssetCache();self.addCleanup(self.cache.close)
        (self.root/'tint.tga').write_bytes(f.tga())
    def live(self,flags,tag):
        path=self.root/(tag+'.m2');path.write_bytes(model_bytes(flags))
        return self.cache.live_model(path,{'id':tag,'clock_ms':0,'play':{'anim_id':7,'cursor_ms':0}})
    def test_original_flags_remain_independent_of_alpha_blend_and_compact_pose(self):
        for flags in (1,5,9,17,29):
            with self.subTest(flags=flags):
                live=self.live(flags,str(flags));batch=live.batches[0]
                expected={'blend':2,'two_sided':bool(flags&4),'no_depth_test':bool(flags&8),'no_depth_write':bool(flags&16)}
                self.assertEqual({key:batch.row[key] for key in expected},expected)
                geo=batch.geo;before=bytes(geo.vertexData())
                again=self.cache.live_model(live.path,{'id':str(flags),'clock_ms':500,'play':{'anim_id':7,'cursor_ms':500}})
                self.assertIs(again,live);self.assertIs(batch.geo,geo)
                self.assertNotEqual(bytes(geo.vertexData()),before)
                self.assertEqual({key:batch.row[key] for key in expected},expected)
    def presentation(self):
        self.state=tempfile.TemporaryDirectory();self.addCleanup(self.state.cleanup)
        self.env=patch.dict(os.environ,{'XDG_STATE_HOME':self.state.name});self.env.start();self.addCleanup(self.env.stop)
        self.bridge=QObject();p=Presentation(self.bridge,device=False);self.addCleanup(p.close)
        return p
    @staticmethod
    def set_filter(p,value):
        p.lua.execute("SetCVar('trilinear',"+repr(value)+")")
        p._ui_requests(p.lua.request('requests'))
    def test_original_lua_filter_validation_notify_and_fresh_vm(self):
        p=self.presentation();self.assertTrue(p.textureTrilinear)
        self.assertEqual(p.lua.evaluate("return GetCVar('trilinear')"),['1'])
        events=[];p.textureSettingsChanged.connect(lambda:events.append(p.textureTrilinear))
        self.set_filter(p,0);self.assertFalse(p.textureTrilinear)
        self.assertEqual(events,[False]);self.assertEqual(p.lua.evaluate("return GetCVar('trilinear')"),['0'])
        for value in (0,2,'nan','inf'):
            self.set_filter(p,value);self.assertFalse(p.textureTrilinear)
            self.assertEqual(p.lua.evaluate("return GetCVar('trilinear')"),['0'])
        self.assertEqual(events,[False])
        old=p.lua;self.assertTrue(p._reload_ui());self.assertIsNot(old,p.lua)
        self.assertFalse(p.textureTrilinear);self.assertEqual(p.lua.evaluate("return GetCVar('trilinear')"),['0'])
        self.set_filter(p,1);self.assertEqual(events,[False,True])
        self.assertEqual({key:p.runtime_settings[key] for key in ('ChatBubbles','ChatBubblesParty')},
                         {'ChatBubbles':'1','ChatBubblesParty':'0'})
        self.assertLessEqual(len(p.runtime_settings)+len(p.volumes),16)
    def test_actual_actor_materials_depth_sides_and_fallback_sampler_change(self):
        rows=[self.live(flags,str(flags)).batches[0] for flags in (1,5,21)]
        # An original transparent effect card has no explicit M2 depth flag.
        card=self.live(5,'card').batches[0];card.row.pop('no_depth_write');rows.append(card)
        (self.root/'gold.blp').write_bytes(f.blp(width=8,height=8,levels=[bytes(c)*(8>>i)**2 for i,c in enumerate(((0,0,255,255),(0,255,0,255),(255,0,0,255)))]))
        authored=self.root/'authored.m2';authored.write_bytes(model_bytes(5,texture='gold.blp'))
        rows.append(self.cache.live_model(authored,{'id':'authored','play':{}}).batches[0])
        p=self.presentation();provider=Provider(rows);engine=QQmlEngine()
        engine.rootContext().setContextProperty('ActorTestProvider',provider)
        engine.rootContext().setContextProperty('FilterSettings',p)
        component=QQmlComponent(engine);component.setData(b'''import QtQuick
import QtQuick3D
import "components"
Item { View3D { visible:false
    GgEngineWorldActorsPage { provider: ActorTestProvider; textureTrilinear: FilterSettings.textureTrilinear }
}}''',QUrl.fromLocalFile(str(PROJECT/'qml/render-flags-test.qml')))
        self.assertEqual(component.errors(),[])
        root=component.create();self.assertIsNotNone(root,str(component.errors()))
        try:
            APP.processEvents()
            materials=[obj for obj in root.findChildren(QObject) if obj.metaObject().indexOfProperty('uTrilinear')>=0]
            self.assertEqual(len(materials),5)
            # Qt Material enum: AlwaysDepthDraw=1, NeverDepthDraw=2.
            self.assertEqual([engine.newQObject(obj).property('depthDrawMode').toInt() for obj in materials],[1,1,2,2,1])
            # Qt Material culling enum: BackFaceCulling=1, NoCulling=3.
            self.assertEqual([engine.newQObject(obj).property('cullMode').toInt() for obj in materials],[1,3,3,3,3])
            textures=[obj for obj in root.findChildren(QObject) if obj.metaObject().indexOfProperty('mipFilter')>=0 and obj.metaObject().indexOfProperty('generateMipmaps')>=0 and obj.property('generateMipmaps')]
            self.assertEqual(len(textures),4)
            self.assertTrue(all(engine.newQObject(obj).property('mipFilter').toInt()==2 for obj in textures))
            self.assertEqual(materials[-1].property('uMipCount'),3)
            atlas_textures=[obj for obj in materials[-1].findChildren(QObject) if obj.metaObject().indexOfProperty('mipFilter')>=0 and obj.property('textureData') is not None]
            self.assertEqual(len(atlas_textures),1)
            self.assertFalse(atlas_textures[0].property('generateMipmaps'))
            self.assertEqual(engine.newQObject(atlas_textures[0]).property('mipFilter').toInt(),0)
            self.set_filter(p,0);APP.processEvents()
            self.assertTrue(all(obj.property('uTrilinear') is False for obj in materials))
            self.assertTrue(all(engine.newQObject(obj).property('mipFilter').toInt()==1 for obj in textures))
            self.assertEqual(materials[-1].property('uMipCount'),3)
        finally:
            root.setParent(None);root.deleteLater();APP.processEvents();engine.deleteLater();APP.processEvents()
    def test_portrait_material_uses_same_live_texture_policy(self):
        row=self.live(5,'portrait').batches[0];p=self.presentation();provider=Provider([row]);engine=QQmlEngine()
        engine.rootContext().setContextProperty('PortraitRows',provider)
        engine.rootContext().setContextProperty('FilterSettings',p)
        component=QQmlComponent(engine);component.setData(b'''import QtQuick
import "components"
GgEngineModelPane { width:128; height:128; originalRows:PortraitRows.batches; textureSettings:FilterSettings }
''',QUrl.fromLocalFile(str(PROJECT/'qml/portrait-filter-test.qml')))
        self.assertEqual(component.errors(),[]);root=component.create();self.assertIsNotNone(root,str(component.errors()))
        try:
            APP.processEvents()
            materials=[obj for obj in root.findChildren(QObject) if obj.metaObject().indexOfProperty('uTrilinear')>=0]
            self.assertEqual(len(materials),1)
            textures=[obj for obj in materials[0].findChildren(QObject) if obj.metaObject().indexOfProperty('mipFilter')>=0 and obj.property('textureData') is not None]
            self.assertEqual(len(textures),1);self.assertTrue(textures[0].property('generateMipmaps'))
            self.set_filter(p,0);APP.processEvents()
            self.assertFalse(materials[0].property('uTrilinear'))
            self.assertEqual(engine.newQObject(textures[0]).property('mipFilter').toInt(),1)
        finally:
            root.deleteLater();APP.processEvents();engine.deleteLater();APP.processEvents()

if __name__=='__main__':unittest.main()
