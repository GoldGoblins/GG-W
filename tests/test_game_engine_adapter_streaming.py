"""Original ABI, retained layers, asynchronous residency and real physics/Lua."""
import json,os,struct,tempfile,time,unittest
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtGui import QGuiApplication
from backend.game_engine_adapter_formats import PROJECT,NativeFormats
from backend.game_engine_adapter_streaming import WorldStream,Surface,Page,tile_at,load_world,world_for
from tools.world import engine_world_fixtures as f
APP=QGuiApplication.instance() or QGuiApplication([])

class StreamingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=PROJECT/'qml');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.manifest=f.make(self.root)
        self.reader=NativeFormats(self.root);self.addCleanup(self.reader.close)
    def stream(self,**cfg):
        v=json.loads(self.manifest.read_text());v.update(cfg);self.manifest.write_text(json.dumps(v));s=WorldStream();self.addCleanup(s.close);s.configure(str(self.manifest));return s
    def settle(self,s,x=-2,y=2.65,z=20,count=1):
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            s.update(x,y,z)
            if len(s.pages)==count and s.pending is None:return
            if s.last_error:self.fail(s.last_error)
            time.sleep(.005)
        self.fail('World stream failed to settle')
    def terrain(self,**options):
        path=self.root/'Test_32_32.adt';path.write_bytes(f.terrain(**options));return self.reader.decode(path,world_scene=True)
    def test_original_lattice_four_layers_shadow_and_packed_geometry(self):
        m,b=self.terrain(alpha=(15,8,4),shadow=True);r=m['rows'][0]
        self.assertEqual(r['vertices'],145);self.assertEqual(len(r['indices']),768);self.assertEqual(len(r['layers']),4)
        self.assertEqual(b[r['alpha_offset']:r['alpha_offset']+4],bytes((255,136,68,255)))
        self.assertEqual(b[r['shadow_offset']:r['shadow_offset']+4],bytes((255,255,255,255)))
        self.assertEqual(Surface(m,b).sample(-16,2.65,16)[0],2.)
    def test_full_256_chunk_tile_fits_packet_and_residency(self):
        path=self.root/'Test_32_32.adt';path.write_bytes(f.full_tile());m,b=self.reader.decode(path,world_scene=True,timeout=4)
        self.assertEqual(len(m['rows']),256);self.assertEqual(sum(r['vertices'] for r in m['rows']),37120);self.assertLess(len(b),8*1024*1024)
        s=self.stream(wmos=[]);self.settle(s);self.assertEqual(len(s.batches),256);self.assertLess(s.bytes,96*1024*1024)
        self.assertAlmostEqual(s.query(-500,2.65,500)['height'],2.)
    def test_authored_hole_has_no_fake_floor(self):
        m,b=self.terrain(holes=1);s=Surface(m,b)
        self.assertIsNone(s.sample(-2,3,2)[0]);self.assertEqual(s.sample(-15,3,15)[0],2.)
        self.assertEqual(len(m['rows'][0]['indices']),720)
    def test_completely_holed_chunk_remains_loaded(self):
        m,b=self.terrain(holes=65535);s=Surface(m,b)
        self.assertIsNone(s.sample(-2,3,2)[0]);self.assertIsNotNone(s.sample(-2,3,2)[1])
    def test_impassable_original_flag(self):
        m,b=self.terrain(impassable=True);self.assertTrue(Surface(m,b).sample(-16,3,16)[1]['impassable'])
    def test_original_axis_swap_and_recentering(self):
        self.assertEqual(tile_at(-2,20,[0,0,0]),(32,32));self.assertEqual(tile_at(-2,550,[0,0,0]),(33,32))
        m,b=self.reader.decode(self.root/'Test_32_32.adt',world_scene=True,origin=[100,200,1])
        self.assertEqual(Surface(m,b).sample(-102,3,202)[0],1.)
    def test_wmo_floor_ceiling_original_vertex_color_and_portals(self):
        m,b=self.reader.decode(self.root/'rooms.wmo',world_scene=True);s=Surface(m,b)
        self.assertEqual(len(m['groups']),3);self.assertEqual(m['groups'][0]['area_id'],1000)
        r=m['rows'][0];self.assertEqual(r['wmo_class'],2);self.assertEqual(r['stride'],48);self.assertFalse(r['dynamic'])
        self.assertEqual(s.sample(-8,3.65,12)[0],3.);self.assertIsNone(s.sample(-1,3.65,12)[0])
        colors=struct.unpack_from('<4f',b,r['offset']+32);self.assertAlmostEqual(colors[0],80/255);self.assertEqual(colors[3],0.)
        self.assertEqual(m['portals']['refs'][0]['group'],1)
    def test_wmo_transformed_floor_and_collision(self):
        m,b=self.reader.decode(self.root/'rooms.wmo',world_scene=True,position=[40,20,5]);s=Surface(m,b)
        self.assertEqual(s.sample(32,8.65,-8)[0],8.)
        x,z=s.walls(35.9,8.65,-8);self.assertLess(x,35.71);self.assertAlmostEqual(z,-8)
    def test_wmo_only_wdt_uses_original_global_placement(self):
        (self.root/'Test.wdt').write_bytes(f.dungeon_wdt(self.root/'rooms.wmo'))
        s=self.stream(wmos=[]);self.settle(s,x=-8,y=3.65,z=12)
        self.assertEqual(list(s.pages),['w:fixed:0']);self.assertEqual(s.query(-8,3.65,12)['height'],3.);self.assertTrue(s.query(-8,3.65,12)['indoors'])
    def test_original_wmo_sight_triangles_block_wall_and_leave_room_open(self):
        s=self.stream();self.settle(s,count=2)
        self.assertTrue(s.line_of_sight((-10,4,12),(-6,4,12)))
        self.assertFalse(s.line_of_sight((-6,4,12),(-2,4,12)))
    def test_original_walking_and_sight_masks_are_independent(self):
        path=self.root/'rooms_000.wmo';original=path.read_bytes();offset=original.index(b'YPOM')+8
        for flags,walking,sight in ((0x22,True,False),(0x24,False,True)):
            with self.subTest(flags=flags):
                data=bytearray(original)
                for face in (4,5):data[offset+face*2]=flags
                path.write_bytes(data);m,b=self.reader.decode(self.root/'rooms.wmo',world_scene=True)
                walk=Surface(m,b);camera=Surface({**m,'collision':m['sight_collision']},b)
                self.assertEqual(walk.walls(-4.1,3.65,12)[0]<-4.29,walking)
                self.assertEqual(not camera.line_of_sight((-6,4,12),(-2,4,12)),sight)
    def test_archive_extraction_evicts_inactive_pages(self):
        from tools.world.engine_format_fixtures import mpq
        entries={p.name:p.read_bytes() for p in self.root.iterdir() if p.suffix in ('.wdt','.adt','.blp')}
        data=self.root/'Data';data.mkdir();(data/'patch.MPQ').write_bytes(mpq(entries=entries))
        for p in list(self.root.iterdir()):
            if p.suffix in ('.wdt','.adt','.blp'):p.unlink()
        s=self.stream(wmos=[],directory=str(PROJECT/'qml'),archive_directory=str(data));self.settle(s)
        first=s.pages['t:32:32'].path;self.assertTrue(first.is_file());self.settle(s,z=550)
        self.assertFalse(first.exists());self.assertLess(len(s.cache.archive_entries),3);s.close();self.assertEqual(s.cache.archive_bytes,0)
    def test_wmo_rejects_missing_groups_without_partial_page(self):
        (self.root/'rooms_001.wmo').unlink()
        with self.assertRaises(ValueError):self.reader.decode(self.root/'rooms.wmo',world_scene=True)
        self.assertEqual(self.reader.request('ping'),{'abi':1})
    def test_wmo_rejects_escaping_group_symlink(self):
        path=self.root/'rooms_001.wmo';path.unlink();path.symlink_to('/etc/passwd')
        with self.assertRaisesRegex(ValueError,'outside permitted'):self.reader.decode(self.root/'rooms.wmo',world_scene=True)
    def test_async_priority_residency_and_eviction(self):
        s=self.stream(wmos=[]);self.settle(s);first=s.pages['t:32:32'];geometry=first.batches[0].geo;budget=s.bytes
        s.update(-2,2.65,20);self.assertIs(s.pages['t:32:32'].batches[0].geo,geometry)
        self.settle(s,z=550);self.assertEqual(list(s.pages),['t:33:32']);self.assertTrue(first.closed)
        replacement=s.pages['t:33:32']
        self.assertEqual(s.bytes-budget,replacement.metadata.get('native_collision_bytes',0)-first.metadata.get('native_collision_bytes',0)+replacement.surface.bytes-first.surface.bytes)
        self.assertEqual(s.cache.reader.request('stats')['collision_pages'],1)
        self.assertLess(s.bytes,96*1024*1024);s.close();self.assertEqual(s.bytes,0)
    def test_nearby_wmo_precedes_distant_prefetch_and_dense_placements_are_bounded(self):
        s=self.stream(radius=1);s.tiles={(x,y) for x in (31,32,33) for y in (31,32,33)}
        keys=list(s.desired(-2,20));self.assertEqual(keys[:2],['t:32:32','w:fixed:0'])
        m,b=self.terrain();m['placements']=[{'id':i,'model':str(self.root/'rooms.wmo'),'position':[i,0,0]} for i in range(100)]
        page=Page(s,self.root/'Test_32_32.adt',m,b);s.pages['t:32:32']=page
        selected=s.desired(-2,20);self.assertEqual(len(selected),25);self.assertIn('w:0',selected);self.assertNotIn('w:99',selected)
        self.assertTrue(list(selected)[2].startswith('t:'))
    def test_retained_texture_stages_and_static_wmo_indices(self):
        s=self.stream();self.settle(s,count=2);terrain=s.pages['t:32:32'].batches[0];wmo=s.pages['w:fixed:0'].batches[0]
        self.assertEqual(len(terrain.stages),5);self.assertGreater(len(bytes(wmo.geo.indexData())),0)
        self.assertEqual(len(bytes(wmo.geo.vertexData())),8*48)
    def test_room_classification_and_connected_group_visibility(self):
        s=self.stream();self.settle(s,count=2);s.update(-8,3.65,12);q=s.query(-8,3.65,12)
        self.assertTrue(q['indoors']);self.assertEqual(q['group'],0);self.assertEqual(q['height'],3.)
        roof=s.query(-8,6.65,12);self.assertEqual(roof['height'],6.);self.assertFalse(roof['indoors'])
        self.assertEqual([b.row['visible'] for b in s.pages['w:fixed:0'].batches],[True,True,False])
        self.assertFalse(s.query(-1,3.65,12)['indoors']);s.update(-1,3.65,12)
        self.assertTrue(all(b.row['visible'] for b in s.pages['w:fixed:0'].batches))
    def test_hold_unloaded_cells_and_authored_hole_drop(self):
        s=self.stream(wmos=[]);self.settle(s);s.collide(-2,2.65,20)
        self.assertEqual(s.collide(-2,2.65,550),(-2,20))
        m,b=self.terrain(holes=1);old=s.pages.pop('t:32:32');old.close();s.pages['t:32:32']=Page(s,self.root/'Test_32_32.adt',m,b)
        self.assertEqual(s.ground(-2,2.65,2),-100000.)
    def test_authoritative_player_falls_through_hole_without_teleporting(self):
        from backend import game_engine_host as host
        self.terrain(holes=1);s=self.stream(wmos=[]);self.settle(s)
        runtime=host.GameEngineRuntime();self.addCleanup(runtime.shutdown)
        try:
            with runtime._lock:
                runtime._engine_world=s;runtime._x[0],runtime._y[0],runtime._z[0]=-2,2.65,2
                runtime._movement_mode='GROUND';runtime._vehicle_kind='NONE';runtime._grapple_anchor=None
                runtime._vx[0]=runtime._vy[0]=runtime._vz[0]=0.;runtime._grounded=True;runtime._running=True
                for _ in range(18):runtime._tick_locked(host.FIXED_DT)
                self.assertFalse(runtime._grounded);self.assertLess(runtime._y[0],2.4);self.assertGreater(runtime._y[0],-5)
        finally:runtime._engine_world=None
    def test_failed_page_does_not_replace_retained_geometry(self):
        s=self.stream(wmos=[]);self.settle(s);page=s.pages['t:32:32'];(self.root/'Test_33_32.adt').write_bytes(b'broken')
        self.settle(s) # Current page remains valid before travel.
        s.config['radius']=1
        deadline=time.monotonic()+3
        while time.monotonic()<deadline and not s.last_error:s.update(-2,2.65,550);time.sleep(.005)
        self.assertTrue(s.last_error);self.assertIs(s.pages['t:32:32'],page);self.assertFalse(page.closed);self.assertLess(len(s.errors),4);s.close();self.assertEqual(s.bytes,0)
    def test_manifest_bounds_and_untrusted_paths(self):
        for cfg in ({'radius':2},{'origin':[float('nan'),0,0]},{'directory':'/etc'},{'map':'../escape'},{'areas':[]},{'wmos':[{'model':str(self.root/'rooms.wmo'),'position':[1e300,0,0]}]}):
            with self.subTest(cfg=cfg),self.assertRaises((ValueError,OSError)):self.stream(**cfg)
            f.make(self.root)
    def test_memory_failure_releases_provisional_page(self):
        import backend.game_engine_adapter_streaming as module
        s=self.stream(wmos=[]);m,b=self.terrain();old=module.LIMIT;module.LIMIT=10
        try:
            with self.assertRaises(ValueError):Page(s,self.root/'Test_32_32.adt',m,b)
            self.assertEqual(s.bytes,0)
        finally:module.LIMIT=old
    def test_game_runtime_ground_walls_and_original_lua_world_facts(self):
        from backend import game_engine_host as host
        from backend.game_client_host import GameClientHost
        from backend.game_engine_adapter_world import environment
        from backend.game_engine_adapter_ui import GgEngineUI
        bridge=GameClientHost();self.addCleanup(bridge.deleteLater)
        self.assertTrue(json.loads(bridge.gameEngineLoadImportedWorld(str(self.manifest)))['ok']);self.addCleanup(load_world,bridge,'')
        s=world_for(bridge);self.settle(s,count=2);r=host._RUNTIME
        with r._lock:
            r._x[0],r._y[0],r._z[0]=-8,3.65,12
            self.assertEqual(r._build_spatial_grid_locked(),{})
            self.assertEqual(r._ground_contact_height_locked(-8,12),3.65)
            r._x[0]=-4.1;r._tick_house_walls_locked();self.assertLess(r._x[0],-4.29)
            npc=r._npc_indices[0];old_npc=(r._x[npc],r._y[npc],r._z[npc]);old_player=(r._x[0],r._y[0],r._z[0])
            try:
                r._x[npc],r._y[npc],r._z[npc]=-6,3.5,12
                r._x[0],r._y[0],r._z[0]=-2,3.5,12;self.assertFalse(r._npc_line_of_sight_locked(npc))
                r._x[0]=-10;self.assertTrue(r._npc_line_of_sight_locked(npc))
            finally:
                r._x[npc],r._y[npc],r._z[npc]=old_npc;r._x[0],r._y[0],r._z[0]=old_player
            snapshot=r.ui_snapshot_locked();facts=environment(snapshot)
        self.assertTrue(facts['indoors']);self.assertEqual(facts['subzone'],'Workshop')
        lua=GgEngineUI();self.addCleanup(lua.close);lua.publish(snapshot['player'],True,100,100,world=facts)
        lua.execute("assert(GetZoneText()=='GG Original World Probe') assert(GetSubZoneText()=='Workshop') assert(GG_GetWorldState().indoors) assert(GG_GetWorldState().wmo_group==0)")
        self.assertTrue(json.loads(bridge.gameEngineLoadImportedWorld(''))['ok']);self.assertEqual(s.bytes,0)
        self.assertNotIn('engine_world',r.ui_snapshot()['player'])

if __name__=='__main__':unittest.main()
