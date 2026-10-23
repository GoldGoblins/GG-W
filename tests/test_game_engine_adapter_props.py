"""Placed original-format M2 art, room lights, hulls and atomic world residency."""
import json,math,os,struct,tempfile,time,unittest
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtGui import QGuiApplication
from backend.game_engine_adapter_formats import PROJECT,NativeFormats
from backend.game_engine_adapter_streaming import WorldStream,Surface
from tools.world import engine_world_fixtures as f
from tools.world import engine_format_fixtures as assets
APP=QGuiApplication.instance() or QGuiApplication([])

def evaluate(probe,n):
    x,y,z=n;q=(x*y,y*z,z*z,x*z)
    return [sum(probe[ch][i]*(*n,1)[i] for i in range(4))+sum(probe[ch+3][i]*q[i] for i in range(4))+probe[6][ch]*(x*x-y*y) for ch in range(3)]

class WorldPropsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=PROJECT/'qml');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.manifest=f.make(self.root)
        (self.root/'crate.m2').write_bytes(f.prop_m2())
        self.reader=NativeFormats(self.root);self.addCleanup(self.reader.close)
    def stream(self,**cfg):
        v=json.loads(self.manifest.read_text());v.update(cfg);self.manifest.write_text(json.dumps(v));s=WorldStream();self.addCleanup(s.close);s.configure(str(self.manifest));return s
    def settle(self,s,count=1,position=(-2,2.65,20)):
        end=time.monotonic()+10
        while time.monotonic()<end:
            s.update(*position)
            if s.last_error:self.fail(s.last_error)
            if len(s.pages)==count and s.pending is None:return
            time.sleep(.005)
        self.fail('World object pages did not settle')
    def terrain(self,props,tx=32):
        path=self.root/f'Test_{tx}_32.adt';path.write_bytes(f.placed_objects(f.terrain(position=(0,-(tx-32)*533.3333,2)),props));return path
    def building(self,props,sets=None,refs=((0,),(),()),lights=None,light_refs=((),(),()),flags=None):
        (self.root/'rooms.wmo').write_bytes(f.root(props=props,sets=sets,lights=lights,flags=flags,portal_geometry=True))
        for g in range(3):(self.root/f'rooms_{g:03}.wmo').write_bytes(f.room(g,props=refs[g],lights=light_refs[g],flags=(flags or [0]*3)[g]))
        return self.root/'rooms.wmo'
    def test_MDDF_identity_scale_normalization_and_origin(self):
        path=self.terrain([{'model':'CRATE.MDX','position':(-8,-12,2),'scale':2048,'id':900}])
        m,_=self.reader.decode(path,world_scene=True,origin=[100,200,1]);p=m['props'][0]
        self.assertEqual(p['model'],'CRATE.m2');self.assertEqual(p['prop_key'],'mddf:900')
        self.assertEqual(p['anchor'][12:15],[-108,-212,1]);self.assertEqual(p['anchor'][0],2)
        model,b=self.reader.decode(self.root/'crate.m2',world_scene=True,anchor=p['anchor']);r=model['rows'][0]
        self.assertEqual(r['bounds'],[[-109,1,211],[-107,3,213]])
        for i in range(r['vertices']):
            n=struct.unpack_from('<3f',b,r['offset']+i*32+12);self.assertAlmostEqual(sum(v*v for v in n),1,places=5)
    def test_heading_rotation_applies_to_art_and_hull(self):
        path=self.terrain([{'position':(-8,-12,2),'rotation':(0,270,0)}]);m,_=self.reader.decode(path,world_scene=True)
        model,b=self.reader.decode(self.root/'crate.m2',world_scene=True,anchor=m['props'][0]['anchor']);r=model['rows'][0]
        v=struct.unpack_from('<3f',b,r['offset']);self.assertAlmostEqual(v[0],-7.5);self.assertAlmostEqual(v[2],12.5)
        hull=model['collision'][0];s=Surface(model,b);self.assertEqual(hull['kind'],'prop_collision');self.assertAlmostEqual(s.sample(-8,2.65,12)[0],3)
    def test_shadow_class_uses_the_original_MCSH_sample(self):
        path=self.root/'Test_32_32.adt';path.write_bytes(f.placed_objects(f.terrain(shadow=True),[{}]));m,_=self.reader.decode(path,world_scene=True)
        self.assertEqual(m['props'][0]['light']['shade'],.5)
    def test_MODS_base_selected_range_and_overlap_dedup(self):
        path=self.building([{}, {'position':(-16,-12,3)}, {'position':(-24,-12,3)}],[(0,1),(1,1),(0,2)],refs=((0,),(1,),(2,)))
        for ds,expected in ((0,['modd:0']),(1,['modd:0','modd:1']),(2,['modd:0','modd:1']),(99,['modd:0'])):
            with self.subTest(set=ds):
                m,_=self.reader.decode(path,world_scene=True,doodad_set=ds);self.assertEqual([p['prop_key'] for p in m['props']],expected)
    def test_unreferenced_MODD_is_not_instantiated(self):
        path=self.building([{},{}],refs=((),(),()));m,_=self.reader.decode(path,world_scene=True);self.assertEqual(m['props'],[])
    def test_shared_MODR_instance_uses_any_room_and_exterior_wins(self):
        path=self.building([{}],refs=((0,0),(0,),()),flags=[0,8,0]);m,_=self.reader.decode(path,world_scene=True)
        self.assertEqual(len(m['props']),1);p=m['props'][0];self.assertEqual(p['owning_groups'],[0,1]);self.assertFalse(p['light']['interior'])
    def test_MODD_quaternion_parent_translation_and_scale(self):
        q=math.sqrt(.5);path=self.building([{'position':(-8,-12,3),'orientation':(0,0,q,q),'scale':2}]);m,_=self.reader.decode(path,world_scene=True,position=[10,20,2],origin=[2,3,1])
        p=m['props'][0];model,b=self.reader.decode(self.root/'crate.m2',world_scene=True,anchor=p['anchor']);v=struct.unpack_from('<3f',b)
        for a,want in zip(v,(1,4,-4)):self.assertAlmostEqual(a,want,places=5)
    def test_baked_color_words_and_probe_match_original_closed_form(self):
        path=self.building([{'color':(80,120,200,255)}]);m,_=self.reader.decode(path,world_scene=True);l=m['props'][0]['light']
        for a,w in zip(l['ambient'],[39/255,58/255,96/255]):self.assertAlmostEqual(a,w,places=6)
        for a,w in zip(evaluate(l['probe'],(0,1,0)),[39/255+.869118*80/255,58/255+.869118*120/255,96/255+.869118*200/255]):self.assertAlmostEqual(a,w,places=5)
        path=self.building([{'color':(0,0,0,255)}]);m,_=self.reader.decode(path,world_scene=True);self.assertEqual(evaluate(m['props'][0]['light']['probe'],(0,1,0)),[0,0,0])
    def test_MOLR_owner_lights_distance_window_and_omni_dispatch(self):
        path=self.building([{'color':(0,0,0,255)}],lights=[{'position':(-8,-12,5),'near':0,'far':4,'color':0xffff0000},{'type':1}],light_refs=((0,1),(),()))
        m,_=self.reader.decode(path,world_scene=True);l=m['props'][0]['light'];self.assertEqual(l['MOLR_lobes'],1)
        c=evaluate(l['probe'],(0,1,0));self.assertAlmostEqual(c[0],.5,places=5);self.assertEqual(c[1:],[0,0])
        path=self.building([{'color':(0,0,0,255)}],lights=[{}],light_refs=((),(),()));m,_=self.reader.decode(path,world_scene=True);self.assertEqual(m['props'][0]['light']['MOLR_lobes'],0)
    def test_hull_is_separate_from_art_and_absent_hull_is_not_faked(self):
        self.terrain([{'position':(-8,-12,2)}]);(self.root/'crate.m2').write_bytes(f.prop_m2(hull=False));s=self.stream(wmos=[]);self.settle(s)
        self.assertEqual(s.query(-8,2.65,12)['height'],2);self.assertTrue(s.line_of_sight((-10,2.5,12),(-6,2.5,12)))
    def test_real_hull_floor_walls_LOS_preserve_room(self):
        self.building([{}]);s=self.stream();self.settle(s,count=2);q=s.query(-8,3.65,12)
        self.assertEqual(q['height'],4);self.assertTrue(q['indoors']);self.assertEqual(q['area_id'],1000);self.assertEqual(q['group'],0)
        self.assertLessEqual(s.collide(-8.6,3.65,12)[0],-8.79);self.assertFalse(s.line_of_sight((-10,3.5,12),(-6,3.5,12)))
        s.update(-8,4.65,12);self.assertTrue(s.last_query['indoors']);self.assertEqual(s.last_query['group'],0)
    def test_retained_geometry_and_shared_textures_across_objects(self):
        self.terrain([{'position':(-8,-12,2),'id':1},{'position':(-12,-12,2),'id':2}]);s=self.stream(wmos=[]);self.settle(s);props=[b for b in s.batches if b.row['kind']=='m2']
        self.assertEqual(len(props),2);self.assertIs(props[0].tex,props[1].tex);geo=[b.geo for b in props];budget=s.bytes
        for i in range(5):s.update(-2-i*.1,2.65,20)
        self.assertEqual([b.geo for b in props],geo);self.assertEqual(s.bytes,budget);s.close();self.assertEqual(s.bytes,0)
    def test_authoritative_player_stands_on_imported_object_hull(self):
        from backend import game_engine_host as host
        self.building([{}]);s=self.stream();self.settle(s,count=2)
        runtime=host.GameEngineRuntime();self.addCleanup(runtime.shutdown)
        try:
            with runtime._lock:
                runtime._engine_world=s;runtime._x[0],runtime._y[0],runtime._z[0]=-8,4.65,12
                runtime._movement_mode='GROUND';runtime._vehicle_kind='NONE';runtime._grapple_anchor=None
                runtime._vx[0]=runtime._vy[0]=runtime._vz[0]=0.;runtime._grounded=True;runtime._running=True
                for _ in range(30):runtime._tick_locked(host.FIXED_DT)
                self.assertTrue(runtime._grounded);self.assertAlmostEqual(runtime._y[0],4.65,places=3)
                self.assertTrue(s.environment(-8,runtime._y[0],12)['indoors'])
        finally:runtime._engine_world=None
    def test_terrain_layer_images_are_shared_but_alpha_maps_are_local(self):
        path=self.root/'Test_32_32.adt';path.write_bytes(f.full_tile());s=self.stream(wmos=[]);self.settle(s)
        a,b=s.batches[:2];self.assertIs(a.tex,b.tex)
        for i in range(3):self.assertIs(a.stages[i],b.stages[i])
        self.assertIsNot(a.stages[3],b.stages[3]);self.assertIsNot(a.stages[4],b.stages[4])
    def test_overlapping_tiles_dedup_draw_and_collision_then_transfer_owner(self):
        specs=[{'position':(-8,-12,2),'id':77}]
        for tx in (32,33):self.terrain(specs,tx)
        s=self.stream(wmos=[],radius=1);self.settle(s,count=2);old=s.pages['t:32:32'];new=s.pages['t:33:32']
        self.assertEqual(sum(b.row['visible'] for b in s.batches if b.row['kind']=='m2'),1)
        self.assertIsNone(new.surface.sample(-8,2.65,12,props=True)[0]);self.assertEqual(old.surface.sample(-8,2.65,12,props=True)[0],3)
        s.config['radius']=0;self.settle(s,position=(-2,2.65,550));self.assertTrue(old.closed);self.assertEqual(new.surface.sample(-8,2.65,12,props=True)[0],3)
        self.assertTrue(next(b for b in new.batches if b.row['kind']=='m2').row['visible'])
    def test_conflicting_shared_ID_rejects_incoming_page_atomically(self):
        self.terrain([{'id':77}],32);self.terrain([{'id':77,'position':(-10,-12,2)}],33);s=self.stream(wmos=[],radius=1)
        end=time.monotonic()+5
        while not s.last_error and time.monotonic()<end:s.update(-2,2.65,20);time.sleep(.005)
        self.assertIn('Conflicting',s.last_error);self.assertEqual(list(s.pages),['t:32:32']);self.assertTrue(s.pages['t:32:32'].batches[-1].row['visible'])
    def test_missing_model_retains_existing_resident_page(self):
        self.terrain([{}]);self.terrain([{'model':'missing.mdx'}],33);s=self.stream(wmos=[]);self.settle(s);page=s.pages['t:32:32'];s.config['radius']=1
        end=time.monotonic()+5
        while not s.last_error and time.monotonic()<end:s.update(-2,2.65,20);time.sleep(.005)
        self.assertIn('missing',s.last_error.lower());self.assertIs(s.pages['t:32:32'],page);self.assertFalse(page.closed)
    def test_original_archive_namespace_and_owned_extraction_cleanup(self):
        path=self.terrain([{'model':'CRATE.MDX'}]);data=self.root/'Data';data.mkdir()
        entries={p.name:p.read_bytes() for p in self.root.iterdir() if p.is_file() and p.suffix in ('.wdt','.adt','.blp','.m2')}
        (data/'patch.MPQ').write_bytes(assets.mpq(entries=entries))
        for p in list(self.root.iterdir()):
            if p.is_file() and p.suffix in ('.wdt','.adt','.blp','.m2'):p.unlink()
        s=self.stream(wmos=[],directory=str(PROJECT/'qml'),archive_directory=str(data));self.settle(s)
        self.assertEqual(s.status()['world_objects'],1);s.close();self.assertEqual(s.cache.archive_bytes,0)
    def test_world_animation_is_armed_on_the_native_runtime(self):
        self.terrain([{}]);(self.root/'crate.m2').write_bytes(assets.animated_m2());s=self.stream(wmos=[]);self.settle(s)
        self.assertTrue(s.pages['t:32:32'].metadata['props'][0]['runtime'])
        self.assertFalse(any('continuous world animation' in note for note in s.status()['limitations']))
    def test_camera_detach_removes_old_portal_gate(self):
        self.building([{}]);s=self.stream();self.settle(s,count=2)
        s.setView({'eye':[-8,4,12],'forward':[1,0,0],'up':[0,1,0],'fov':60,'aspect':1,'near':.1,'far':100})
        self.assertIsNotNone(s.camera);s.update(-2,2.65,20);s.clearView();self.assertIsNone(s.camera)
        self.assertTrue(all(b.row['visible'] for b in s.pages['w:fixed:0'].batches))
    def test_unique_source_cap_preserves_empty_page_on_failure(self):
        specs=[]
        for i in range(33):
            name=f'prop{i}.m2';(self.root/name).write_bytes(f.prop_m2());specs.append({'model':name,'id':i})
        self.terrain(specs);s=self.stream(wmos=[]);end=time.monotonic()+8
        while not s.last_error and time.monotonic()<end:s.update(-2,2.65,20);time.sleep(.005)
        self.assertIn('source capacity',s.last_error);self.assertEqual(s.pages,{});self.assertEqual(s.bytes,0)
    def test_invalid_source_path_quaternion_scale_and_refs_rejected(self):
        for prop,refs,pattern in (({'orientation':(0,0,0,0)},((0,),(),()),'orientation'),({'scale':0},((0,),(),()),'scale'),({},((99,),(),()),'MODR')):
            path=self.building([prop],refs=refs)
            with self.subTest(prop=prop),self.assertRaisesRegex(ValueError,pattern):self.reader.decode(path,world_scene=True)
        self.terrain([{'model':'/etc/passwd.mdx'}]);s=self.stream(wmos=[])
        end=time.monotonic()+5
        while not s.last_error and time.monotonic()<end:s.update(-2,2.65,20);time.sleep(.005)
        self.assertIn('Escaping',s.last_error);self.assertEqual(s.pages,{})
    def test_invalid_MOLR_and_MODS_bounds_fail_without_worker_loss(self):
        for options,pattern in (({'lights':[], 'light_refs':((0,),(),())},'MOLR'),({'sets':[(0,2)]},'MODS')):
            path=self.building([{}],**options)
            with self.subTest(options=options),self.assertRaisesRegex(ValueError,pattern):self.reader.decode(path,world_scene=True)
            self.assertEqual(self.reader.request('ping'),{'abi':1})
    def test_object_limits_and_manifest_set_validation(self):
        path=self.terrain([{'id':i} for i in range(129)])
        with self.assertRaisesRegex(ValueError,'capacity'):self.reader.decode(path,world_scene=True)
        for ds in (True,-1,65536,1.5):
            with self.subTest(set=ds),self.assertRaises(ValueError):self.stream(wmos=[{'model':str(self.root/'rooms.wmo'),'doodad_set':ds}])
            with self.subTest(native_set=ds),self.assertRaises(ValueError):self.reader.decode(self.root/'rooms.wmo',world_scene=True,doodad_set=ds)

if __name__=='__main__':unittest.main()
