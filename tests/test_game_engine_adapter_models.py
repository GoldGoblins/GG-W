"""Original animation/camera readers through the installed C ABI and retained Qt geometry."""
import json,math,os,struct,sys,tempfile,unittest
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
PROJECT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(PROJECT))
from tools.world import engine_format_fixtures as assets
from backend.game_engine_adapter_formats import NativeFormats,AssetCache
from backend.game_engine_adapter_ui import GgEngineUI
from PySide6.QtGui import QGuiApplication
APP=QGuiApplication.instance() or QGuiApplication([])
def replaceable_m2(texture_type,embedded=False):
    data=bytearray(assets.animated_m2());texture=struct.unpack_from('<I',data,0x60)[0]
    struct.pack_into('<I',data,texture,texture_type)
    if not embedded:struct.pack_into('<II',data,texture+8,0,0)
    return bytes(data)
class Models(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory(dir=PROJECT/'qml');self.root=Path(self.directory.name);self.addCleanup(self.directory.cleanup)
        self.reader=NativeFormats(self.root);self.addCleanup(self.reader.close)
        (self.root/'gold.blp').write_bytes(assets.blp())
    def load(self,**kwargs):
        path=self.root/'animated.m2';path.write_bytes(assets.animated_m2(**kwargs));self.reader.decode(path,runtime=True);return path
    def vertex(self,path,**kwargs):
        meta,blob=self.reader.pose(path,**kwargs);return meta,struct.unpack_from('<8f',blob)
    def test_translation_loop_clamp_global_and_step(self):
        path=self.load();meta,v=self.vertex(path,anim_id=7,cursor_ms=500,camera=0)
        self.assertEqual(v[:3],(-.5,-1.,0.));self.assertEqual(meta['facts']['bbox'],[[-1.,0.,-1.],[2.,0.,1.]])
        self.assertAlmostEqual(meta['camera']['position'][0],.5);self.assertAlmostEqual(meta['camera']['position'][2],4.2,places=5)
        self.assertEqual(self.vertex(path,anim_id=7,cursor_ms=1250)[1][:3],(-.75,-1.,0.))
        path=self.load(looping=False);self.assertEqual(self.vertex(path,anim_id=7,cursor_ms=1500)[1][:3],(0.,-1.,0.))
        path=self.load(step=True);self.assertEqual(self.vertex(path,anim_id=7,cursor_ms=500)[1][:3],(-1.,-1.,0.))
        path=self.load(global_sequence=True);self.assertEqual(self.vertex(path,clock_ms=1250)[1][:3],(-.75,-1.,0.))
    def test_rotation_slerp_preserves_normals_and_shortest_arc(self):
        path=self.load(rotation=True);meta,v=self.vertex(path,anim_id=7,cursor_ms=500)
        self.assertAlmostEqual(v[0],0,places=5);self.assertAlmostEqual(v[1],-1,places=5);self.assertAlmostEqual(v[2],1,places=5)
        self.assertAlmostEqual(sum(x*x for x in v[3:6]),1,places=5)
        data=bytearray(path.read_bytes());bone=struct.unpack_from('<I',data,0x38)[0];keys=struct.unpack_from('<I',data,bone+40+24)[0]
        struct.pack_into('<8f',data,keys,0,0,0,1,0,0,0,-1);path.write_bytes(data);self.reader.decode(path,runtime=True)
        self.assertEqual(self.vertex(path,anim_id=7,cursor_ms=500)[1][:3],(-1.,-1.,0.))
    def test_cyclic_skeleton_and_invalid_geometry_rejected_worker_survives(self):
        data=bytearray(assets.animated_m2());bone=struct.unpack_from('<I',data,0x38)[0];struct.pack_into('<h',data,bone+8,0)
        path=self.root/'cycle.m2';path.write_bytes(data)
        with self.assertRaisesRegex(ValueError,'cyclic'):self.reader.decode(path,runtime=True)
        path.write_bytes(assets.m2(invalid_index=True))
        with self.assertRaisesRegex(ValueError,'skin vertex'):self.reader.decode(path,runtime=True)
        self.assertEqual(self.reader.request('ping'),{'abi':1})
    def test_nonfinite_runtime_bounds_and_camera_rejected(self):
        for target in ('bounds','camera'):
            data=bytearray(assets.animated_m2());offset=0xb4 if target=='bounds' else struct.unpack_from('<I',data,0x128)[0]+4
            struct.pack_into('<f',data,offset,float('nan'));path=self.root/'bad-float.m2';path.write_bytes(data)
            with self.assertRaisesRegex(ValueError,'non-finite'):self.reader.decode(path,runtime=True,anim_id=7,camera=0)
            self.assertEqual(self.reader.request('ping'),{'abi':1})
    def test_seven_original_blends_and_address_modes(self):
        for blend in range(7):
            path=self.load(blend=blend);meta,_=self.vertex(path)
            self.assertEqual(meta['rows'][0]['blend'],blend);self.assertTrue(meta['rows'][0]['wrap_u']);self.assertFalse(meta['rows'][0]['wrap_v'])
            self.assertEqual(meta['rows'][0]['uv_rotation'],[1,0]);self.assertEqual(meta['limitations'],[])
    def test_animated_alpha_rgb_and_raw_uv_rotation(self):
        path=self.root/'material.m2';path.write_bytes(assets.material_m2());self.reader.decode(path,runtime=True)
        meta,_=self.vertex(path,anim_id=7,cursor_ms=500);row=meta['rows'][0]
        self.assertAlmostEqual(row['alpha'],.5);self.assertEqual(row['tint'],[1,.75,.5])
        self.assertEqual(row['uv_scale'],[1.5,2]);self.assertEqual(row['uv_rotation'],[.5,.5])
        self.assertAlmostEqual(row['uv_offset'][0],.2);self.assertAlmostEqual(row['uv_offset'][1],.1)
        compact,_=self.reader.pose(path,compact=True,anim_id=7,cursor_ms=250)
        self.assertNotIn('indices',compact['rows'][0]);self.assertAlmostEqual(compact['rows'][0]['alpha'],.75)
    def test_parent_arm_preserves_child_pivot(self):
        original=bytearray(assets.animated_m2(rotation=True));old=struct.unpack_from('<I',original,0x38)[0]
        for flags,expected in ((2,(0,-1,0)),(4,(-4,-2,-2)),(6,(-2,-1,-2)),(3,(0,-1,1))):
            data=bytearray(original);bone=bytes(data[old:old+108]);child=bytearray(108);struct.pack_into('<iIh',child,0,-1,flags,0);struct.pack_into('<3f',child,96,1,0,0)
            for offset in (12,40,68):struct.pack_into('<h',child,offset+2,-1)
            at=len(data);data.extend(bone+child);struct.pack_into('<II',data,0x34,2,at)
            rot=struct.unpack_from('<I',data,at+40+24)[0];q=math.sqrt(.5);struct.pack_into('<8f',data,rot,0,0,q,q,0,0,q,q)
            track=at+68;times=len(data);data.extend(struct.pack('<II',0,1000));keys=len(data);data.extend(struct.pack('<6f',2,2,2,2,2,2));struct.pack_into('<II',data,track+12,2,times);struct.pack_into('<II',data,track+20,2,keys)
            vertices=struct.unpack_from('<I',data,72)[0]
            for i in range(3):data[vertices+i*48+16]=1
            path=self.root/'parent.m2';path.write_bytes(data);self.reader.decode(path,runtime=True)
            vertex=self.vertex(path,anim_id=7,cursor_ms=500)[1]
            for actual,want in zip(vertex[:3],expected):self.assertAlmostEqual(actual,want,places=5)
    def test_icon_replacement_and_reflection_metadata(self):
        data=bytearray(assets.m2());texture=struct.unpack_from('<I',data,0x60)[0];struct.pack_into('<I',data,texture,14)
        unit=struct.unpack_from('<I',data,0xa0)[0];struct.pack_into('<H',data,unit,0xffff)
        path=self.root/'icon.m2';path.write_bytes(data);(self.root/'blue.tga').write_bytes(assets.tga())
        cache=AssetCache();self.addCleanup(cache.close);live=cache.live_model(path,{'id':'icon'});batch=live.batches[0]
        self.assertTrue(batch.row['env_map']);self.assertTrue(batch.row['icon_slot']);before=cache.live_bytes
        live.appearance({'icon':str(self.root/'blue.tga')});self.assertEqual(bytes(batch.tex.textureData())[:4],bytes([50,160,220,255]))
        live.appearance({'icon':str(self.root/'blue.tga')});self.assertEqual(cache.live_bytes,before)
        live.appearance({});self.assertEqual(bytes(batch.tex.textureData())[:4],bytes([240,176,36,255]))
    def test_replaceable_slots_native_metadata_and_compact_retention(self):
        for kind,skin,character in ((11,0,None),(12,1,None),(13,2,None),(1,None,'Body'),(2,None,'Object'),(6,None,'Hair'),(8,None,'SkinExtra')):
            with self.subTest(kind=kind):
                path=self.root/'replaceable.m2';path.write_bytes(replaceable_m2(kind));metadata,_=self.reader.decode(path,runtime=True)
                row=metadata['rows'][0];self.assertEqual(row['skin_slot'],skin);self.assertEqual(row['char_slot'],character)
                self.assertIsNone(row['texture']);self.assertEqual(metadata['limitations'],[])
                compact,_=self.reader.pose(path,compact=True);self.assertNotIn('skin_slot',compact['rows'][0]);self.assertNotIn('char_slot',compact['rows'][0])
    def test_per_instance_skin_rebind_reset_paths_and_budget(self):
        path=self.root/'creature.m2';path.write_bytes(replaceable_m2(11))
        for name,pixel in (('red',(255,0,0,255)),('blue',(0,0,255,255)),('green',(0,255,0,255))):
            (self.root/(name+'.blp')).write_bytes(assets.blp(levels=[bytes((pixel[2],pixel[1],pixel[0],pixel[3]))*4]))
        cache=AssetCache();self.addCleanup(cache.close);a=cache.live_model(path,{'id':'a'});b=cache.live_model(path,{'id':'b'});geometry=a.batches[0].geo;texture=a.batches[0].tex
        self.assertEqual(a.limitations,['Unbound M2 replaceable textures: Monster1'])
        def appearance(name):return {'appearance':{'skins':[str(self.root/(name+'.blp')),None,None]}}
        a.appearance(appearance('red'));b.appearance(appearance('blue'));memory=cache.live_bytes
        self.assertEqual(a.limitations,[]);self.assertEqual(b.limitations,[])
        self.assertEqual(bytes(a.batches[0].tex.textureData())[:4],bytes((255,0,0,255)));self.assertEqual(bytes(b.batches[0].tex.textureData())[:4],bytes((0,0,255,255)))
        a=cache.live_model(path,{'id':'a','play':{'anim_id':7,'cursor_ms':500}});a.appearance(appearance('green'))
        self.assertIs(a.batches[0].geo,geometry);self.assertIs(a.batches[0].tex,texture);self.assertEqual(cache.live_bytes,memory)
        self.assertEqual(a.batches[0].row['skin_slot'],0);self.assertEqual(bytes(a.batches[0].tex.textureData())[:4],bytes((0,255,0,255)))
        self.assertEqual(bytes(b.batches[0].tex.textureData())[:4],bytes((0,0,255,255)))
        before=bytes(texture.textureData())
        with self.assertRaisesRegex(ValueError,'Model texture missing'):a.appearance({'appearance':{'skins':['/etc/passwd',None,None]}})
        self.assertEqual(bytes(texture.textureData()),before)
        for invalid in ({'skins':['red.blp']},{'skins':[None,None,None],'hair':17},{'body':'x'*1025}):
            with self.assertRaises(ValueError):a.appearance({'appearance':invalid})
        a.appearance({});self.assertEqual(bytes(texture.textureData())[:4],bytes((255,255,255,255)))
        self.assertEqual(a.limitations,['Unbound M2 replaceable textures: Monster1']);self.assertEqual(b.limitations,[])
        a.appearance(appearance('red'));self.assertEqual(a.limitations,[])
        cache.close();self.assertEqual(cache.live_bytes,0)
    def test_character_slot_binding_and_embedded_fallback(self):
        (self.root/'blue.tga').write_bytes(assets.tga());cache=AssetCache();self.addCleanup(cache.close)
        for kind,key in ((1,'body'),(2,'object'),(6,'hair'),(8,'skin_extra')):
            with self.subTest(kind=kind):
                path=self.root/(key+'.m2');path.write_bytes(replaceable_m2(kind,embedded=True));live=cache.live_model(path,{'id':key});batch=live.batches[0]
                self.assertEqual(live.limitations,[]);live.appearance({'appearance':{key:str(self.root/'blue.tga')}})
                self.assertEqual(bytes(batch.tex.textureData())[:4],bytes((50,160,220,255)))
                live.appearance({});self.assertEqual(bytes(batch.tex.textureData())[:4],bytes((240,176,36,255)));self.assertEqual(live.limitations,[])
    def test_original_lua_model_clock_hide_and_finish(self):
        path=self.load(looping=False);facts,_=self.reader.decode(path,runtime=True)
        ui=GgEngineUI(clock=0);self.addCleanup(ui.close);source=json.dumps(path.relative_to(PROJECT/'qml').as_posix())
        ui.execute(f"finished=0 m=CreateFrame('Model','Animated',UIParent) m:SetWidth(100) m:SetHeight(100) m:SetPoint('TOPLEFT',UIParent,'TOPLEFT',0,0) m:SetModel({source}) m:SetSequence(7) m:SetScript('OnAnimFinished',function() finished=finished+1 end)")
        ui.request('model_facts',path=json.loads(source),facts=facts['facts']);ui.tick(.5)
        row=next(r for r in ui.frames() if r['kind']=='ModelPane');self.assertEqual(row['play'],{'anim_id':7,'cursor_ms':500})
        ui.execute('m:Hide()');ui.tick(.5);ui.execute('m:Show()');row=next(r for r in ui.frames() if r['kind']=='ModelPane');self.assertEqual(row['play']['cursor_ms'],500)
        ui.tick(.6);self.assertEqual(ui.evaluate('return finished'),[1]);ui.tick(.5);self.assertEqual(ui.evaluate('return finished'),[1])
        ui.execute('m:SetSequenceTime(7,250)');row=next(r for r in ui.frames() if r['kind']=='ModelPane');self.assertEqual(row['play']['cursor_ms'],250)
        self.assertEqual(ui.errors,[])
    def test_independent_panes_retained_geometry_recovery_eviction_memory(self):
        path=self.load();cache=AssetCache();self.addCleanup(cache.close)
        a=cache.live_model(path,{'id':'a','play':{'anim_id':7,'cursor_ms':0}});b=cache.live_model(path,{'id':'b','play':{'anim_id':7,'cursor_ms':500}})
        self.assertIsNot(a,b);self.assertEqual(struct.unpack_from('<3f',a.batches[0].geo.vertexData().data()),(-1,-1,0));self.assertEqual(struct.unpack_from('<3f',b.batches[0].geo.vertexData().data()),(-.5,-1,0))
        cache.reader.close();again=cache.live_model(path,{'id':'a','play':{'anim_id':7,'cursor_ms':250}});self.assertIs(again,a)
        self.assertEqual(struct.unpack_from('<3f',a.batches[0].geo.vertexData().data()),(-.75,-1,0))
        cache.retain_live_panes({'b'});self.assertTrue(a.closed);self.assertFalse(b.closed);self.assertGreater(cache.live_bytes,0)
        # Failed allocation releases every reservation, and subsequent assets still work.
        cache.live_bytes=64*1024*1024
        with self.assertRaisesRegex(ValueError,'memory capacity'):cache.live_model(path,{'id':'c'})
        self.assertEqual(cache.live_bytes,64*1024*1024);cache.live_bytes=b.byte_size
        cache.close();self.assertEqual(cache.live_bytes,0);self.assertTrue(b.closed)
if __name__=='__main__':unittest.main()
