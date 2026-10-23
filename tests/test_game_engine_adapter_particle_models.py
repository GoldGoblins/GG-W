"""Geometry particles, original one-level child emitters and exact birth queries."""
import os,struct,tempfile,time,unittest
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtGui import QGuiApplication
from backend.game_engine_adapter_formats import PROJECT,NativeFormats,AssetCache
from tools.world import engine_format_fixtures as a,engine_world_fixtures as f
APP=QGuiApplication.instance() or QGuiApplication([])
class ParticleModels(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=PROJECT/'qml');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        (self.root/'gold.blp').write_bytes(a.blp());self.reader=NativeFormats(self.root);self.addCleanup(self.reader.close)
    def model(self,name,data):p=self.root/name;p.write_bytes(data);return p
    def pose(self,path,ms,instance='a',**options):return self.reader.decode(path,runtime=True,instance=instance,anim_id=7,clock_ms=ms,cursor_ms=ms,**options)
    def test_geometry_is_the_childs_actual_mesh_and_tumbles_with_colour(self):
        self.model('blade.m2',a.m2());path=self.model('effect.m2',a.particle_m2(geometry='blade.m2',flags=0x8010,rate=2,life=2,speed=0,tumble=1))
        m,data=self.pose(path,0);r=m['effects']['rows'][0];self.assertTrue(r['model_particle']);self.assertEqual(r['vertices'],3);self.assertEqual(r['capacity'],3)
        self.assertEqual(r['instance_capacity'],128)
        initial=data[r['instance_offset']:r['instance_offset']+r['instance_count']*80]
        mesh=data[r['offset']:r['offset']+r['vertices']*32]
        m,data=self.pose(path,250);self.assertEqual(m['effects']['model_particles'],2);r=m['effects']['rows'][0]
        self.assertNotEqual(initial,data[r['instance_offset']:r['instance_offset']+r['instance_count']*80])
        self.assertEqual(mesh,data[r['offset']:r['offset']+r['vertices']*32]);self.assertFalse(m['effects']['limitations'])
    def test_child_pool_births_expiry_and_single_level_recursion(self):
        self.model('child.m2',a.particle_m2(rate=80,life=.3,recursion='absent-grandchild.m2'))
        path=self.model('effect.m2',a.particle_m2(recursion='child.m2',flags=0x8010,rate=2,life=.2,speed=0))
        m,_=self.pose(path,0);self.assertEqual(len(m['effects']['rows']),2);m,_=self.pose(path,100)
        self.assertEqual(m['effects']['parent_particles'],2);self.assertGreater(m['effects']['child_particles'],0)
        self.pose(path,500);m,_=self.pose(path,700);self.assertEqual(m['effects']['live_particles'],0);self.assertFalse(m['effects']['limitations'])
    def test_geometry_and_child_dependencies_resolve_inside_MPQ_before_Qt_batches(self):
        entries={'GG/effect.m2':a.particle_m2(geometry='GG/blade.MDX',recursion='GG/child.m2',flags=0x8010,rate=2),'GG/blade.m2':a.m2(blend=2),'GG/child.m2':a.particle_m2(rate=50),'GG/gold.blp':a.blp()}
        data=self.root/'Data';data.mkdir();(data/'patch.MPQ').write_bytes(a.mpq(entries=entries))
        cache=AssetCache();self.addCleanup(cache.close);cache.mount_chain(data);path=cache.resolve('GG/effect.m2')
        row={'id':'effect','clock_ms':0,'play':{'anim_id':7}}
        live=cache.live_model(path,row);g=[b.geo for b in live.batches];memory=cache.live_bytes
        self.assertTrue(live.batches[1].row['model_particle']);self.assertEqual(len(g),3)
        instances=live.batches[1].instances;self.assertIsNotNone(instances);self.assertTrue(instances.depthSortingEnabled())
        live=cache.live_model(path,{**row,'clock_ms':100,'raw_cursor_ms':100})
        self.assertEqual(g,[b.geo for b in live.batches]);self.assertGreater(live.effect_particles,2);self.assertEqual(cache.live_bytes,memory)
        self.assertIs(instances,live.batches[1].instances)
        self.assertFalse(live.limitations);cache.close();self.assertEqual(cache.live_bytes,0)
    def test_ground_snap_hits_authored_hull_and_lifts_by_birth_size(self):
        ground=self.model('ground.m2',f.prop_m2());self.reader.decode(ground,world_scene=True,collision_key='floor',anchor=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1])
        path=self.model('effect.m2',a.particle_m2(flags=0xa000,rate=1,life=2,speed=0))
        anchor=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,5,1]
        m,data=self.pose(path,0,instance='world:ground',world_instance=True,anchor=anchor);r=m['effects']['rows'][0]
        # Hull top is Z=1, the symmetric quad's mean Y is 1 + birth half-size .12.
        heights=[struct.unpack_from('<f',data,r['offset']+i*48+4)[0] for i in range(4)]
        self.assertAlmostEqual(sum(heights)/4,1.12,places=5);self.assertFalse(m['effects']['limitations'])
        self.reader.request('release_collision',key='floor');m,_=self.pose(path,0,instance='world:ground',world_instance=True,anchor=anchor)
        self.assertTrue(any('collision' in note for note in m['effects']['limitations']))
    def test_releasing_parent_removes_model_dependencies_and_walking_pages(self):
        blade=self.model('blade.m2',a.m2());path=self.model('effect.m2',a.particle_m2(geometry='blade.m2'))
        self.pose(path,0);self.assertEqual(self.reader.request('stats')['models'],2)
        self.reader.request('unload',path=str(blade));self.assertEqual(self.reader.request('stats')['models'],2)
        self.reader.request('unload',path=str(path));stats=self.reader.request('stats')
        self.assertEqual(stats['models'],0);self.assertEqual(stats['effect_instances'],0)
    def test_dependency_cannot_escape_the_mounted_root(self):
        path=self.model('effect.m2',a.particle_m2(geometry='../escaped.m2'))
        with tempfile.TemporaryDirectory(dir=PROJECT/'qml') as other:
            outside=Path(other)/'escaped.m2';outside.write_bytes(a.m2());self.reader.decode(path,runtime=True)
            with self.assertRaisesRegex(ValueError,'outside'):self.reader.request('bind_effect_models',path=str(path),bindings={'../escaped.m2':str(outside)})
    def test_ground_snap_uses_imported_terrain_and_explicit_release(self):
        ground=self.model('Test_32_32.adt',f.terrain());self.reader.decode(ground,world_scene=True,collision_key='terrain')
        path=self.model('effect.m2',a.particle_m2(flags=0xa000,rate=1,life=2,speed=0))
        anchor=[1,0,0,0,0,1,0,0,0,0,1,0,-8,-12,5,1]
        m,data=self.pose(path,0,instance='world:terrain',world_instance=True,anchor=anchor);r=m['effects']['rows'][0]
        heights=[struct.unpack_from('<f',data,r['offset']+i*48+4)[0] for i in range(4)]
        self.assertAlmostEqual(sum(heights)/4,2.12,places=5)
        stats=self.reader.request('stats');self.assertEqual(stats['collision_pages'],1);self.assertGreater(stats['collision_bytes'],0)
        self.reader.request('release_collision',key='terrain');self.assertEqual(self.reader.request('stats')['collision_bytes'],0)
if __name__=='__main__':unittest.main()
