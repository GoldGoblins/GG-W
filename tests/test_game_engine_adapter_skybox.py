"""Original authored sky model and camera/PVS/fog laws over own fixtures."""
import math,os,struct,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace as NS
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtGui import QGuiApplication
from backend.game_engine_adapter_formats import NativeFormats,PROJECT
from backend.game_engine_adapter_skybox import WmoCrossfade,wmo_sky,wmo_fog
from backend.game_engine_adapter_streaming import WorldStream
from tools.world import engine_skybox_fixtures as f
APP=QGuiApplication.instance() or QGuiApplication([])
class Skybox(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=PROJECT/'qml');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.manifest=f.make(self.root);self.reader=NativeFormats(self.root);self.addCleanup(self.reader.close)
    def test_native_preserves_authored_scale_offset_and_render_flags(self):
        metadata,data=NativeFormats._unpack(self.reader.request('skybox',path=str(self.root/'blue-sky.m2')))
        points=[struct.unpack_from('<3f',data,row['offset']+i*32) for row in metadata['rows'] for i in range(row['vertices'])]
        self.assertEqual((min(p[0] for p in points),max(p[0] for p in points)),(-93,107));self.assertTrue(metadata['rows'][0]['no_fog']);self.assertTrue(metadata['rows'][0]['two_sided'])
    def test_rigid_bone_spin_uses_original_global_clock_and_pivot(self):
        metadata,_=NativeFormats._unpack(self.reader.request('skybox',path=str(self.root/'spin.m2'),clock_ms=500))
        self.assertTrue(metadata['rows'][0]['spinning']);q=metadata['transforms'][0];self.assertAlmostEqual(q['translation'][0],4,places=4);self.assertAlmostEqual(q['translation'][2],4,places=4)
        sample,_=NativeFormats._unpack(self.reader.request('skybox',path=str(self.root/'spin.m2'),clock_ms=1500,geometry=False));self.assertEqual(sample['transforms'],metadata['transforms']);self.assertIsNone(sample['rows'])
        for clock in (-1,True,'oops'):
            with self.assertRaises(ValueError):self.reader.request('skybox',path=str(self.root/'spin.m2'),clock_ms=clock)
    def test_non_rotation_channel_does_not_spin(self):
        from tools.world.engine_format_fixtures import animated_m2
        path=self.root/'nonrigid.m2';path.write_bytes(animated_m2(camera=False));m,_=NativeFormats._unpack(self.reader.request('skybox',path=str(path),clock_ms=500));self.assertFalse(m['rows'][0]['spinning'])
    def test_wmo_sky_uses_flood_visible_flag_and_stable_min_path(self):
        pages={i:NS(metadata={'skybox':name,'groups':[{'id':0,'flags':0x40000}]},portal_status={'visible_groups':visible}) for i,(name,visible) in enumerate((('z.m2',[0]),('a.m2',[0]),('0.m2',[])))}
        self.assertEqual(wmo_sky(NS(pages=pages)),'a.m2');pages[1].portal_status['visible_groups']=[];self.assertEqual(wmo_sky(NS(pages=pages)),'z.m2')
    def test_fog_radius_fold_and_one_record_bail(self):
        def rec(color,end,inner,outer,position,flags=0):return dict(color=color,end=end,start_scalar=.25,radius_inner=inner,radius_outer=outer,position=position,flags=flags)
        records=[rec([0,0,0],200,0,0,[0,0,0],1),rec([1,0,0],100,0,10,[5,0,0]),rec([0,1,0],50,0,10,[2,0,0])]
        p=NS(metadata={'fog_records':records,'portals':{'refs':[1]},'groups':[{'interior':True,'fog_indices':[1,2]}]},portal_status={'room':0});s=NS(camera=NS(eye=[0,0,0]),pages={'w':p})
        target=wmo_fog(s);self.assertAlmostEqual(target['color'][0],.1);self.assertAlmostEqual(target['color'][1],.8);self.assertAlmostEqual(target['end'],70)
        p.metadata['fog_records']=records[:1];self.assertIsNone(wmo_fog(s))
    def test_fog_crossfade_latches_on_exit_and_freezes_underwater(self):
        fade=WmoCrossfade();scene={'near':30,'far':150,'color':[0,0,0]};target={'color':[1,0,0],'end':200,'start_scalar':.25}
        fade.advance(2000,target,True);self.assertEqual(fade.weight,.5);fog=fade.fog(scene,100);self.assertEqual(fog['far'],125);self.assertEqual(fog['near'],27.5)
        fade.advance(9000,None,False);self.assertEqual(fade.weight,.5);fade.advance(10000,None,True);self.assertEqual(fade.weight,.25);fade.advance(11000,None,True);self.assertEqual(fade.fog(scene,100),scene);self.assertIsNone(fade.staged)
    def test_real_world_wmo_and_ghost_slots_retain_geometry_and_release_memory(self):
        s=WorldStream();self.addCleanup(s.close);s.configure(str(self.manifest));view={'eye':[-8,4,12],'forward':[0,0,-1],'up':[0,1,0],'fov':60,'aspect':1,'near':.1,'far':100};s.setView(view)
        def wait(predicate):
            end=time.monotonic()+8
            while time.monotonic()<end:
                s.update(-8,3.65,12);s.advance(.1)
                if predicate():return
                time.sleep(.005)
            self.fail(str(s.status()))
        wait(lambda:s.skyboxReplacesCelestial);self.assertEqual(s.light.error,'');self.assertIn('blue-sky.m2',s.light.skyboxes.wanted);blue=next(iter(s.light.skyboxes.arts.values()));identity=[(b,b.geometry,b.textureData) for b in blue.batches]
        s.light.config['ghost']=True;s.light.next_ms=0;wait(lambda:'green-sky.m2' in (s.light.skyboxes.wanted or '') and s.skyboxReplacesCelestial)
        self.assertEqual(s.light.skyboxes.weight,1);self.assertEqual(len(s.light.skyboxes.arts),2)
        for b,g,t in identity:self.assertIs(b.geometry,g);self.assertIs(b.textureData,t);self.assertFalse(b.row['visible'])
        s.close();self.assertEqual(s.bytes,0)
if __name__=='__main__':unittest.main()
