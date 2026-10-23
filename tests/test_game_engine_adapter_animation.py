"""World clocks, inherited camera palettes, effects and eviction through the ABI."""
import json,math,os,struct,tempfile,time,unittest
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtGui import QGuiApplication
from backend.game_engine_adapter_formats import PROJECT,NativeFormats
from backend.game_engine_adapter_streaming import WorldStream
from tools.world import engine_format_fixtures as a,engine_world_fixtures as f
APP=QGuiApplication.instance() or QGuiApplication([])
VIEW={'eye':[0,4,20],'forward':[0,0,-1],'up':[0,1,0],'fov':60,'aspect':1,'near':.1,'far':100}
IDENTITY=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]
def idle(data):
    data=bytearray(data);at=struct.unpack_from('<I',data,0x20)[0];struct.pack_into('<H',data,at,0);return bytes(data)
def billboard(flags=8,child=False,pivot=(0,0,0)):
    data=bytearray(idle(a.animated_m2(camera=False)));at=struct.unpack_from('<I',data,0x38)[0]
    struct.pack_into('<I',data,at+4,flags);struct.pack_into('<3f',data,at+96,*pivot)
    if child:
        bone=bytes(data[at:at+108]);child_bone=bytearray(108);struct.pack_into('<iIh',child_bone,0,-1,0,0)
        for offset in (12,40,68):struct.pack_into('<h',child_bone,offset+2,-1)
        at=len(data);data.extend(bone+child_bone);struct.pack_into('<II',data,0x34,2,at)
        vertices=struct.unpack_from('<I',data,72)[0]
        for i in range(3):data[vertices+i*48+16]=1
    return bytes(data)
class Animation(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=PROJECT/'qml');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.manifest=f.make(self.root)
        self.reader=NativeFormats(self.root);self.addCleanup(self.reader.close)
    def model(self,data):
        p=self.root/'crate.m2';p.write_bytes(data);return p
    def stream(self,data,props=None):
        self.model(data);(self.root/'Test_32_32.adt').write_bytes(f.placed_objects(f.terrain(),props or [{}]))
        cfg=json.loads(self.manifest.read_text());cfg['wmos']=[];cfg['radius']=0;self.manifest.write_text(json.dumps(cfg))
        s=WorldStream();self.addCleanup(s.close);s.configure(str(self.manifest));end=time.monotonic()+10
        while time.monotonic()<end:
            s.update(-2,2.65,20)
            if s.last_error:self.fail(s.last_error)
            if s.pages and not s.pending:break
            time.sleep(.005)
        self.assertTrue(s.pages);return s
    def tick(self,s,delta):
        s.advance(delta);end=time.monotonic()+4
        while s.animations.future is not None and time.monotonic()<end:
            s.animations.finish();time.sleep(.002)
        self.assertIsNone(s.animations.future);self.assertEqual(s.animations.error,'');s._visibility(*s.position)
    def test_world_pose_advances_and_retains_geometry_textures_and_collision(self):
        s=self.stream(idle(a.animated_m2()));b=next(b for b in s.batches if b.row['kind']=='m2');g,t=b.geo,b.tex;initial=bytes(g.vertexData());memory=s.bytes;surface=s.pages['t:32:32'].surface
        self.tick(s,.5);after=bytes(g.vertexData());self.assertNotEqual(after,initial)
        self.assertAlmostEqual(struct.unpack_from('<f',after)[0]-struct.unpack_from('<f',initial)[0],.5)
        self.assertIs(b.geo,g);self.assertIs(b.tex,t);self.assertIs(s.pages['t:32:32'].surface,surface);self.assertEqual(s.bytes,memory)
    def test_two_placements_keep_independent_anchors_and_share_native_source(self):
        s=self.stream(idle(a.animated_m2()),[{'position':(-8,-12,2),'id':1},{'position':(-18,-12,2),'id':2}]);self.tick(s,.5)
        rows=[b for b in s.batches if b.row['kind']=='m2'];self.assertEqual(len(rows),2)
        self.assertAlmostEqual(struct.unpack_from('<f',rows[0].geo.vertexData())[0]-struct.unpack_from('<f',rows[1].geo.vertexData())[0],10)
        self.assertIs(rows[0].tex,rows[1].tex)
    def test_global_sequence_uses_scene_clock(self):
        s=self.stream(idle(a.animated_m2(global_sequence=True)));b=next(b for b in s.batches if b.row['kind']=='m2');self.tick(s,.75)
        self.assertAlmostEqual(struct.unpack_from('<f',b.geo.vertexData())[0],-8.25)
    def test_animated_material_drives_world_uniforms(self):
        s=self.stream(idle(a.material_m2()));self.tick(s,.5);b=next(b for b in s.batches if b.row['kind']=='m2')
        self.assertAlmostEqual(b.row['alpha'],.5);self.assertEqual(b.row['uv_scale'],[1.5,2]);self.assertEqual(b.row['uv_rotation'],[.5,.5])
    def test_world_uses_lookup_idle_instead_of_assuming_animation_zero(self):
        data=bytearray(a.animated_m2());at=len(data);data.extend(struct.pack('<HH',7,0));struct.pack_into('<II',data,0x2c,1,at)
        s=self.stream(bytes(data));self.tick(s,.5);b=next(b for b in s.batches if b.row['kind']=='m2')
        self.assertAlmostEqual(struct.unpack_from('<f',b.geo.vertexData())[0],-8.5)
    def test_explicit_sequence_rejects_invalid_slot_and_animation_mismatch(self):
        p=self.model(a.animated_m2())
        with self.assertRaisesRegex(ValueError,'unknown M2 sequence'):self.reader.decode(p,runtime=True,sequence_index=15)
        with self.assertRaisesRegex(ValueError,'mismatch'):self.reader.decode(p,runtime=True,sequence_index=0,anim_id=5)
    def test_particles_arm_and_become_visible_after_empty_initial_pose(self):
        s=self.stream(idle(a.particle_m2(flags=0x10,rate=20)));s.setView(VIEW);self.tick(s,.1);self.tick(s,.1)
        effects=[b for b in s.batches if b.row.get('effect')];self.assertEqual(len(effects),1)
        self.assertTrue(effects[0].row['visible']);self.assertGreater(len(effects[0].geo.vertexData()),192)
    def test_ribbons_advance_on_world_skeleton(self):
        s=self.stream(idle(a.ribbon_m2()));self.tick(s,.1);self.tick(s,.1)
        effects=[b for b in s.batches if b.row.get('effect')];self.assertEqual(len(effects),1);self.assertTrue(effects[0].row['effect_active'])
    def test_spherical_billboard_and_child_share_camera_basis(self):
        for child in (False,True):
            p=self.model(billboard(child=child));m,data=self.reader.decode(p,runtime=True,anim_id=0,view=VIEW)
            self.assertFalse(any('billboard' in note for note in m['limitations']));point=struct.unpack_from('<3f',data)
            # Original X points toward the eye; original Y points screen-right.
            for actual,want in zip(point,(0.,-1.,-1.)):self.assertAlmostEqual(actual,want,places=5)
    def test_billboard_keeps_transformed_pivot_with_rotated_scaled_anchor(self):
        p=self.model(billboard(pivot=(1,0,0)));anchor=[0,2,0,0,-2,0,0,0,0,0,2,0,10,20,30,1]
        _,data=self.reader.decode(p,runtime=True,anim_id=0,view=VIEW,anchor=anchor);point=struct.unpack_from('<3f',data)
        for actual,want in zip(point,(10.,28.,-26.)):self.assertAlmostEqual(actual,want,places=5)
    def test_locked_billboards_and_pole_camera_are_finite(self):
        p=self.root/'crate.m2'
        for flags in (0x10,0x20,0x40):
            for forward in ([0,0,-1],[0,-1,0]):
                p.write_bytes(billboard(flags));view={**VIEW,'forward':forward,'up':[0,0,1] if forward[1] else [0,1,0]}
                _,data=self.reader.decode(p,runtime=True,anim_id=0,view=view)
                self.assertTrue(all(math.isfinite(v) for v in struct.unpack('<'+str(len(data)//4)+'f',data)))
    def test_invalid_camera_basis_and_namespace_are_rejected(self):
        p=self.model(billboard());
        with self.assertRaisesRegex(ValueError,'degenerate'):self.reader.decode(p,runtime=True,view={**VIEW,'up':[0,0,-1]})
        with self.assertRaisesRegex(ValueError,'namespace'):self.reader.decode(p,runtime=True,instance='world:1')
    def test_native_pose_batch_matches_separate_samples_and_offset_packing(self):
        p=self.model(idle(a.animated_m2()));self.reader.decode(p,runtime=True)
        items=[{'path':str(p),'world_instance':True,'instance':'world:'+str(i),'anim_id':0,'cursor_ms':i*500,'clock_ms':i*500,'anchor':IDENTITY,'compact':True} for i in range(2)]
        m,data=NativeFormats._unpack(self.reader.request('pose_many',items=items,timeout=2));self.assertEqual(len(m['models']),2)
        for i,r in enumerate(m['models']):self.assertAlmostEqual(struct.unpack_from('<f',data,r['rows'][0]['offset'])[0],-1+i*.5)
    def test_native_batch_limits_are_explicit(self):
        with self.assertRaisesRegex(ValueError,'capacity'):self.reader.request('pose_many',items=[{}]*129)
    def test_worker_recovery_retains_live_world_buffers(self):
        s=self.stream(idle(a.animated_m2()));b=next(b for b in s.batches if b.row['kind']=='m2');g=b.geo;s.cache.reader.close();self.tick(s,.5);self.assertIs(b.geo,g)
    def test_evicted_page_cannot_be_updated_by_old_pose(self):
        s=self.stream(idle(a.animated_m2()));s.advance(.1);page=s.pages['t:32:32'];s._remove_page('t:32:32');self.tick(s,.1)
        self.assertTrue(page.closed);self.assertEqual(s.bytes,0);self.assertFalse(s.batches)
    def test_close_joins_animation_and_releases_residency(self):
        s=self.stream(idle(a.particle_m2()));s.advance(.1);s.close();self.assertEqual(s.bytes,0);self.assertTrue(s.cache.closed)
    def test_clock_input_is_finite_and_bounded(self):
        s=self.stream(idle(a.animated_m2()))
        for delta in (-1,float('nan'),float('inf'),11):
            with self.assertRaises(ValueError):s.advance(delta)
if __name__=='__main__':unittest.main()
