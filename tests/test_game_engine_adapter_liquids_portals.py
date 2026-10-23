"""Native wet grids, authoritative swim transitions and camera portal decisions."""
import json,math,os,struct,tempfile,time,unittest
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtGui import QGuiApplication
from backend.game_engine_adapter_formats import PROJECT,NativeFormats
from backend.game_engine_adapter_streaming import WorldStream,Surface
from backend.game_engine_adapter_liquids import LiquidGrid,LiquidIndex,prepare_atlas
from backend.game_engine_adapter_portals import PortalCamera,visibility,clip_sides,portal_rect,on_portal
from tools.world import engine_world_fixtures as f
APP=QGuiApplication.instance() or QGuiApplication([])
STEP=533.3333/128

def view(eye=(-8,4,12),forward=(-1,0,0),**extra):
    return {'eye':list(eye),'forward':list(forward),'up':[0,1,0],'fov':60,'aspect':1,'near':.1,'far':100,**extra}

class LiquidsPortalsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=PROJECT/'qml');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.manifest=f.make(self.root)
        self.reader=NativeFormats(self.root);self.addCleanup(self.reader.close)
    def decode_terrain(self,**liquid):
        path=self.root/'Test_32_32.adt';path.write_bytes(f.terrain(liquid=liquid))
        return self.reader.decode(path,world_scene=True)
    def stream(self,**cfg):
        data=json.loads(self.manifest.read_text());data.update(liquids={kind:{'frames':['white.blp']} for kind in ('STILL','RAPIDS','OCEAN','MAGMA','SLIME')});data.update(cfg)
        self.manifest.write_text(json.dumps(data));s=WorldStream();self.addCleanup(s.close);s.configure(str(self.manifest));return s
    def settle(self,s,*,count=1,position=(-2,2.65,20)):
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            s.update(*position)
            if s.last_error:self.fail(s.last_error)
            if len(s.pages)==count and s.pending is None:return
            time.sleep(.005)
        self.fail('World loading deadline exceeded')
    def portal_world(self):
        (self.root/'rooms.wmo').write_bytes(f.root(portal_geometry=True));s=self.stream();self.settle(s,count=2);return s
    def test_native_liquid_uses_original_grid_and_preserves_ground(self):
        m,b=self.decode_terrain();row=m['rows'][1]
        self.assertEqual(row['kind'],'liquid');self.assertEqual(row['grid'],[9,9]);self.assertEqual(len(row['indices']),384)
        self.assertEqual(row['stride'],48);self.assertEqual(row['liquid_kind'],'STILL');self.assertEqual(row['liquid_path'],0)
        self.assertAlmostEqual(struct.unpack_from('<f',b,row['offset']+44)[0],1.)
        self.assertEqual(Surface(m,b).sample(-2,2.65,2)[0],2.)
        self.assertEqual(LiquidIndex(m,b).sample(-2,3,2,False)[0][0],5.)
    def test_shared_WMO_cells_draw_once_and_keep_both_physical_grids(self):
        for g in range(3):
            liquid={'shared':[True,False]} if g<2 else None
            (self.root/f'rooms_{g:03}.wmo').write_bytes(f.room(g,liquid=liquid))
        m,b=self.reader.decode(self.root/'rooms.wmo',world_scene=True);rows=[r for r in m['rows'] if r['kind']=='liquid']
        self.assertEqual([len(r['indices']) for r in rows],[12,6]);self.assertEqual([r['wet'] for r in rows],[[True,True],[True,True]])
        self.assertEqual(len(LiquidIndex(m,b).grids),2)
    def test_nonplanar_height_is_bilinear_not_max_or_triangle(self):
        heights=[4.]*81
        for i,h in ((0,4),(1,6),(9,8),(10,12)):heights[i]=h
        m,b=self.decode_terrain(heights=heights);g=LiquidGrid(m['rows'][1],b)
        height,sx,sz=g.sample(-STEP*.25,STEP*.25)
        self.assertAlmostEqual(height,5.625,places=5)
        self.assertAlmostEqual(sx,-4.5/STEP,places=5);self.assertAlmostEqual(sz,2.5/STEP,places=5)
    def test_dry_cells_and_far_edge_ownership(self):
        wet=[True]*64;wet[0]=False;m,b=self.decode_terrain(wet=wet);g=LiquidGrid(m['rows'][1],b)
        self.assertIsNone(g.sample(-2,2));self.assertIsNotNone(g.sample(-2,6))
        self.assertIsNotNone(g.sample(-STEP*8,STEP*8));self.assertIsNone(g.sample(-100,2))
        self.assertEqual(len(m['rows'][1]['indices']),378)
    def test_all_dry_grid_has_no_surface(self):
        m,b=self.decode_terrain(wet=[False]*64);self.assertEqual(len(m['rows']),1);self.assertEqual(LiquidIndex(m,b).grids,[])
    def test_original_liquid_kinds_and_opaque_magma(self):
        for nibble,kind in ((0,'STILL'),(1,'OCEAN'),(2,'MAGMA')):
            with self.subTest(kind=kind):
                m,b=self.decode_terrain(nibble=nibble);row=m['rows'][1]
                self.assertEqual(row['liquid_kind'],kind);self.assertEqual(row['blend'],0 if kind=='MAGMA' else 2);self.assertEqual(row['fullbright'],kind=='MAGMA')
    def test_world_origin_rebases_liquid_and_ground_together(self):
        self.decode_terrain();m,b=self.reader.decode(self.root/'Test_32_32.adt',world_scene=True,origin=[100,200,1]);g=LiquidGrid(m['rows'][1],b)
        self.assertEqual(g.sample(-102,202)[0],4.);self.assertEqual(Surface(m,b).sample(-102,4,202)[0],1.)
    def test_wmo_pool_material_color_floor_and_instance_scope(self):
        (self.root/'rooms_000.wmo').write_bytes(f.room(liquid={}))
        s=self.stream();self.settle(s,count=2)
        sample=s.water_sample(-9,4,12);self.assertEqual(sample['height_m'],5.);self.assertEqual(sample['body_kind'],'STILL')
        self.assertEqual(s.water_sample(-9,2,12)['body_kind'],'NONE')
        self.assertEqual(s.water_sample(-9,7,12)['body_kind'],'NONE')
        row=next(r for r in s.pages['w:fixed:0'].metadata['rows'] if r['kind']=='liquid');self.assertEqual(row['liquid_path'],2)
        m,b=self.reader.decode(self.root/'rooms.wmo',world_scene=True,position=[40,20,5]);row=next(r for r in m['rows'] if r['kind']=='liquid')
        self.assertEqual(LiquidGrid(row,b).sample(31,-8)[0],10.);self.assertEqual(row['pool_floor'],8.)
        rgb=struct.unpack_from('<3f',b,row['offset']+32)
        for actual,expected in zip(rgb,(0x12/255,0x34/255,0x56/255)):self.assertAlmostEqual(actual,expected)
    def test_indoor_claim_excludes_terrain_water_overhead(self):
        self.decode_terrain(heights=[20.]*81);s=self.stream();self.settle(s,count=2)
        self.assertEqual(s.water_sample(-2,3,20)['height_m'],20.)
        self.assertEqual(s.water_sample(-8,4,12)['body_kind'],'NONE')
    def test_wmo_liquid_variants_select_scroll_and_exterior_path(self):
        path=self.root/'rooms_000.wmo'
        for nibble,kind in ((1,'OCEAN'),(2,'MAGMA'),(3,'SLIME'),(4,'STILL'),(6,'MAGMA'),(7,'SLIME'),(8,'RAPIDS')):
            with self.subTest(nibble=nibble):
                path.write_bytes(f.room(liquid={'nibble':nibble},flags=0x40))
                m,b=self.reader.decode(self.root/'rooms.wmo',world_scene=True);row=next(r for r in m['rows'] if r['kind']=='liquid')
                self.assertEqual(row['liquid_kind'],kind);self.assertEqual(row['liquid_path'],1)
                self.assertEqual(row['scroll'],nibble in (6,7));self.assertEqual(row['fullbright'],kind in ('MAGMA','SLIME'))
    def test_lowest_stacked_surface_wins(self):
        (self.root/'rooms_000.wmo').write_bytes(f.room(liquid={'heights':[5.]*6}))
        (self.root/'rooms_001.wmo').write_bytes(f.room(1,liquid={'heights':[4.]*6}))
        s=self.stream();self.settle(s,count=2);self.assertEqual(s.water_sample(-9,3.65,12)['height_m'],4.)
    def test_shared_atlas_retains_geometry_and_is_budgeted_once(self):
        self.decode_terrain();s=self.stream(wmos=[]);self.settle(s)
        page=s.pages['t:32:32'];liquid=page.batches[1];texture=liquid.tex;geometry=liquid.geo;size=s.bytes
        s.update(-2,3,20);s.setView(view(eye=(-2,8,20),forward=(0,-1,-1)))
        self.assertIs(liquid.geo,geometry);self.assertIs(liquid.tex,texture);self.assertEqual(s.bytes,size)
        self.assertEqual(liquid.row['frames'],1);self.assertEqual(liquid.row['atlas_grid'],[1,1]);self.assertLess(size,96*1024*1024)
        s.close();self.assertEqual(s.bytes,0)
    def test_atlas_preserves_rgb_in_transparent_detail_pixels(self):
        from tools.world.engine_format_fixtures import blp
        from backend.game_engine_adapter_formats import AssetCache
        (self.root/'transparent.blp').write_bytes(blp(levels=[bytes((20,80,100,0))*4]))
        cache=AssetCache();self.addCleanup(cache.close);cache.deadline=time.monotonic()+5
        atlas,material,notes=prepare_atlas(cache,self.root/'Test_32_32.adt','STILL',{'STILL':{'frames':['white.blp','transparent.blp']}})
        self.assertEqual(tuple(bytes(atlas.constBits())[8:12]),(100,80,20,0));self.assertEqual(material['frames'],2)
    def test_two_liquid_surfaces_share_one_retained_atlas(self):
        first=f.terrain(liquid={});second=f.terrain(position=(-533.3333/16,0,2),index=(0,1),liquid={})
        (self.root/'Test_32_32.adt').write_bytes(first+second[second.index(b'KNCM'):])
        s=self.stream(wmos=[]);self.settle(s);batches=[b for b in s.pages['t:32:32'].batches if b.row['kind']=='liquid']
        self.assertEqual(len(batches),2);self.assertIs(batches[0].tex,batches[1].tex)
        self.assertGreater(batches[0].texture_bytes,0);self.assertEqual(batches[1].texture_bytes,0)
        s.close();self.assertEqual(s.bytes,0)
    def test_corrupt_liquid_frame_fails_without_replacing_resident_page(self):
        s=self.stream(wmos=[],radius=1);self.settle(s,count=2)
        original=s.pages['t:32:32'];(self.root/'Test_33_32.adt').write_bytes(f.terrain(position=(0,-533.3333,2),liquid={}))
        s._remove_page('t:33:32');s.config['liquids']['STILL']['frames']=['missing.blp']
        deadline=time.monotonic()+5
        while time.monotonic()<deadline and not s.last_error:s.update(-2,3,20);time.sleep(.005)
        self.assertIn('frame unavailable',s.last_error);self.assertIs(s.pages['t:32:32'],original);self.assertNotIn('t:33:32',s.pages)
    def test_material_configuration_rejects_escaping_or_unbounded_inputs(self):
        for settings in ({'NONE':{}},{'STILL':{'frames':[]}},{'STILL':{'frames':['/etc/passwd']}},{'STILL':{'deep':[0,0,0,float('nan')]}},{'STILL':{'frames':['white.blp']*31}}):
            with self.subTest(settings=settings),self.assertRaises((ValueError,OSError)):self.stream(liquids=settings)
            f.make(self.root)
    def test_authoritative_swim_entry_and_dry_exit_do_not_teleport(self):
        from backend import game_engine_host as host
        self.decode_terrain(wet=[False]+[True]*63);s=self.stream(wmos=[]);self.settle(s)
        r=host.GameEngineRuntime();self.addCleanup(r.shutdown)
        with r._lock:
            r._engine_world=s;r._x[0],r._y[0],r._z[0]=-2,2.65,20;r._movement_mode='GROUND';r._vehicle_kind='NONE';r._grapple_anchor=None;r._vx[0]=r._vy[0]=r._vz[0]=0.;r._grounded=True;r._running=True
            try:
                r._tick_locked(host.FIXED_DT);self.assertEqual(r._movement_mode,'SWIM');self.assertAlmostEqual(r._y[0],5.18,places=4)
                r._ui_snapshot_base={'player':{'medium':'LAND','grounded':True},'terrain_surface':{'height_m':999,'medium':'LAND'}}
                ui=r.ui_snapshot_locked();self.assertEqual(ui['player']['medium'],'WATER');self.assertFalse(ui['player']['grounded'])
                self.assertEqual(ui['terrain_surface']['height_m'],2.);self.assertEqual(ui['terrain_surface']['medium'],'WATER')
                from backend.game_engine_adapter_world import environment
                facts=environment(ui);self.assertTrue(facts['swimming']);self.assertEqual(facts['medium'],'WATER');self.assertFalse(facts['grounded'])
                self.assertEqual(r._water_sample_locked(-2,20)['surface_model'],'GG_ENGINE_WET_GRID')
                r._x[0]=-2;r._z[0]=2;before=r._y[0]
                r._tick_locked(host.FIXED_DT);self.assertEqual(r._movement_mode,'GROUND');self.assertFalse(r._grounded)
                self.assertLess(abs(r._y[0]-before),.1);self.assertGreater(r._y[0],5)
            finally:r._engine_world=None
    def test_falling_above_water_does_not_start_swimming_in_air(self):
        from backend import game_engine_host as host
        self.decode_terrain();s=self.stream(wmos=[]);self.settle(s)
        r=host.GameEngineRuntime();self.addCleanup(r.shutdown)
        with r._lock:
            r._engine_world=s;r._x[0],r._y[0],r._z[0]=-2,10,20;r._movement_mode='GROUND';r._vehicle_kind='NONE';r._grapple_anchor=None;r._vx[0]=r._vy[0]=r._vz[0]=0.;r._grounded=False;r._running=True
            try:r._tick_locked(host.FIXED_DT);self.assertEqual(r._movement_mode,'GROUND');self.assertGreater(r._y[0],9.8)
            finally:r._engine_world=None
    def test_lua_sees_original_liquid_kind_and_submersion(self):
        from backend.game_engine_adapter_ui import GgEngineUI
        self.decode_terrain(nibble=2);s=self.stream(wmos=[]);self.settle(s);facts=s.environment(-2,4,20)
        self.assertTrue(facts['submerged']);lua=GgEngineUI();self.addCleanup(lua.close)
        lua.publish({'x':-2,'y':4,'z':20},True,100,100,world=facts)
        lua.execute("assert(GG_GetWorldState().liquid_kind=='MAGMA') assert(GG_GetWorldState().submerged) assert(GG_GetWorldState().liquid_surface==5)")
    def test_native_portal_polygon_and_plane_follow_placement(self):
        (self.root/'rooms.wmo').write_bytes(f.root(portal_geometry=True))
        m,b=self.reader.decode(self.root/'rooms.wmo',world_scene=True,position=[40,20,5]);info=m['portals']['infos'][0]
        self.assertEqual(info['plane'],[1.,0.,0.,-28.]);self.assertEqual(info['points'][0],[28.,8.,-6.])
    def test_camera_facing_door_or_away_changes_group_visibility(self):
        s=self.portal_world();s.update(-8,3.65,12);s.setView(view())
        batches=s.pages['w:fixed:0'].batches;self.assertEqual([b.row['visible'] for b in batches],[True,True,False]);ids=[id(b.geo) for b in batches]
        s.setView(view(forward=(1,0,0)));self.assertEqual([b.row['visible'] for b in batches],[True,False,False]);self.assertEqual([id(b.geo) for b in batches],ids)
        self.assertEqual(s.pages['w:fixed:0'].portal_status['mode'],'PORTAL_RECTANGLES')
    def test_camera_room_is_independent_of_player_room(self):
        s=self.portal_world();s.update(-8,3.65,12);s.setView(view(eye=(-16,4,12),forward=(-1,0,0)))
        self.assertEqual(s.last_query['group'],0);self.assertEqual([b.row['visible'] for b in s.pages['w:fixed:0'].batches],[False,True,False])
    def test_sealed_interior_hides_exterior_meshes_but_retains_collision(self):
        self.decode_terrain(heights=[20.]*81);s=self.portal_world();s.setView(view())
        self.assertFalse(any(b.row['visible'] for b in s.pages['t:32:32'].batches))
        self.assertEqual(s.ground(-2,3,20),2.);self.assertEqual(s.water_sample(-2,3,20)['height_m'],20.)
        s.setView(view(eye=(-2,25,20),forward=(0,-1,0),up=[0,0,1]))
        self.assertTrue(all(b.row['visible'] for b in s.pages['t:32:32'].batches))
    def test_on_plane_guard_and_front_side_gate(self):
        s=self.portal_world();m=s.pages['w:fixed:0'].metadata;info=m['portals']['infos'][0]
        self.assertTrue(on_portal(info,(-12,4,12)));self.assertFalse(on_portal(info,(-12,10,12)))
        self.assertEqual(portal_rect(info,PortalCamera(view(eye=(-12,4,12),forward=(1,0,0)))),(-1.,-1.,1.,1.))
        visible,status=visibility(m,PortalCamera(view(eye=(-13,4,12),forward=(1,0,0))),0)
        self.assertEqual(visible,{0}) # Wrong half-space must not leak through the door.
    def test_side_clip_rejects_behind_and_keeps_eye_straddle(self):
        self.assertEqual(clip_sides([(-.1,-.1,0,-1),(.1,-.1,0,-1),(0,.1,0,-1)]),[])
        self.assertTrue(clip_sides([(-.1,-.1,0,1),(.1,-.1,0,1),(0,.1,0,-.1)]))
    def test_invalid_camera_cannot_poison_published_visibility(self):
        s=self.portal_world();s.setView(view());before=s.camera
        for invalid in (view(fov=float('nan')),view(forward=(0,0,0)),view(near=100,far=10)):
            s.setView(invalid);self.assertIs(s.camera,before)
    def test_callback_and_exterior_window_passes(self):
        s=self.portal_world();m=s.pages['w:fixed:0'].metadata
        m['groups'][1]['flags']=8;m['groups'][2]['flags']=8
        visible,status=visibility(m,PortalCamera(view()),0)
        self.assertEqual(visible,{0,1,2});self.assertEqual(status['windows'],1)
        m['groups'][2]['flags']=0x10000
        visible,status=visibility(m,PortalCamera(view()),0);self.assertIn(2,visible)
        visible,status=visibility(m,PortalCamera(view(forward=(1,0,0))),0);self.assertEqual(visible,{0})
    def test_pathological_portal_graph_fails_open_with_a_bounded_walk(self):
        s=self.portal_world();m=s.pages['w:fixed:0'].metadata;refs=[]
        for gi,group in enumerate(m['groups']):
            group['portal_start']=len(refs);group['portal_count']=64
            refs.extend({'portal':0,'group':(gi+1)%3,'side':1} for _ in range(64))
        m['portals']['refs']=refs;start=time.perf_counter();visible,status=visibility(m,PortalCamera(view()),0)
        self.assertEqual(status['mode'],'BOUNDED_FALLBACK');self.assertEqual(visible,{0,1,2});self.assertLess(time.perf_counter()-start,.25)

if __name__=='__main__':unittest.main()
