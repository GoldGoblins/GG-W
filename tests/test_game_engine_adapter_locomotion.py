"""Actual native walking walls, movement, cache invalidation and bounded search."""
import copy,time,unittest
from tests import test_game_engine_adapter_pet_world as fixture
from backend.game_engine_adapter_locomotion import plan,edge,routes,MAX_EXPANDED


class Walking(unittest.TestCase):
    setUp=fixture.PetWorld.setUp
    publish=fixture.PetWorld.publish
    call=fixture.PetWorld.call
    control=fixture.PetWorld.control
    view=fixture.PetWorld.view
    service=fixture.PetWorld.service
    tame=fixture.PetWorld.tame
    prepared=fixture.PetWorld.prepared
    tick=fixture.PetWorld.tick
    replace_wall_masks=fixture.PetWorld.replace_wall_masks

    def test_actual_wmo_wall_requires_real_detour_and_every_route_edge_is_walkable(self):
        pet,index=self.prepared();start=(pet['x'],pet['y'],pet['z']);goal=(-2.5,3.,12.)
        before=self.stream.safe
        result=plan(self.stream,start,goal)
        self.assertEqual(result['status'],'READY',result)
        self.assertGreater(len(result['route']),1)
        self.assertLessEqual(result['expanded'],MAX_EXPANDED)
        current=start
        for waypoint in result['route']:
            self.assertTrue(edge(self.stream,current,waypoint));current=waypoint
        self.assertEqual(current,goal);self.assertEqual(self.stream.safe,before)

    def test_same_pet_physically_walks_around_wall_without_crossing_it_or_creating_animal(self):
        pet,index=self.prepared();pet.update(target='',command=1,reaction=0,autocast=False)
        identity=pet['id'];number=pet['number'];last=(pet['x'],pet['y'],pet['z']);before=self.stream.safe
        moved=False
        for _ in range(230):
            self.tick(dt=.05)
            current=(pet['x'],pet['y'],pet['z'])
            self.assertTrue(edge(self.stream,last,current));last=current
            if pet['x']>-3.9:moved=True
        self.assertTrue(moved,(pet['x'],pet['z'],routes(self.stream).last_status))
        self.assertEqual((pet['id'],pet['number']),(identity,number))
        self.assertEqual(self.stream.safe,before)
        self.assertEqual(sum(row['id']==identity for row in self.runtime._nature.rows),1)

    def test_replaced_collision_page_invalidates_cached_wall_route_even_without_revision_change(self):
        pet,index=self.prepared();nav=routes(self.stream);start=(pet['x'],pet['y'],pet['z']);goal=(-2.5,3.,12.)
        first=nav.waypoint('owned',start,goal,0.)
        self.assertNotEqual(first,goal)
        self.replace_wall_masks(0x24)
        self.assertEqual(nav.waypoint('owned',start,goal,.1),goal)
        self.assertEqual(nav.last_status,'DIRECT')

    def test_unloaded_destination_has_no_fabricated_route_and_cannot_change_player_safe(self):
        pet,index=self.prepared();before=self.stream.safe
        result=plan(self.stream,(pet['x'],pet['y'],pet['z']),(20000,3,20000))
        self.assertEqual(result['status'],'UNLOADED');self.assertEqual(result['route'],[])
        self.assertEqual(self.stream.safe,before)
        with self.assertRaises(ValueError):plan(self.stream,(0,3,0),(1,3,1),max_expanded=MAX_EXPANDED+1)

    def test_real_lower_floor_integrates_fall_and_applies_damage_once_without_resetting_xp(self):
        pet,index=self.prepared();pet.update(x=-2.5,z=20.,y=14.,command=0,target='',reaction=0,autocast=False)
        actor=self.runtime._combat_state['actors']['pet:'+str(pet['number'])]
        health=actor['health'];xp=pet['xp'];self.tick(dt=.05)
        self.assertGreater(pet['y'],3.);self.assertLess(pet['y'],14.)
        for _ in range(120):self.tick(dt=.05)
        self.assertEqual(pet['y'],3.)
        self.assertLess(actor['health'],health)
        after=actor['health']
        self.tick(40,dt=.05);self.assertEqual(actor['health'],after)
        self.assertEqual(pet['xp'],xp)

    def test_many_actors_share_search_budget_and_deferred_actor_retries_next_step(self):
        pet,index=self.prepared();nav=routes(self.stream);start=(pet['x'],pet['y'],pet['z']);goal=(-2.5,3.,12.)
        before=self.stream.safe
        for identity in range(20):nav.waypoint(str(identity),start,goal,1.)
        self.assertLessEqual(nav.plans,2);self.assertGreaterEqual(nav.expansion_budget,0)
        self.assertEqual(nav.last_status,'DEFERRED')
        for step in range(1,241):
            waypoint=nav.waypoint('19',start,goal,1.+step*.05)
            if nav.last_status!='DEFERRED':break
        self.assertEqual(nav.last_status,'READY');self.assertNotEqual(waypoint,start)
        self.assertEqual(self.stream.safe,before)

    def test_npc_fall_uses_own_health_once_without_player_xp_or_free_teleport(self):
        pet,index=self.prepared();runtime=self.runtime
        saved=runtime._npc_indices;runtime._npc_indices=[index];self.addCleanup(setattr,runtime,'_npc_indices',saved)
        with runtime._lock:
            runtime._x[index],runtime._y[index],runtime._z[index]=-2.5,14.65,20.
            runtime._npc_home_x[index],runtime._npc_home_z[index]=-2.5,20.
            runtime._npc_target_x[index],runtime._npc_target_z[index]=-2.5,20.
            runtime._vx[index]=runtime._vy[index]=runtime._vz[index]=0.;runtime._tick=1
            actor=runtime._combat_state['actors'][runtime._npc_ids[index]];health=actor['health'];xp=runtime._progression['xp']
            runtime._tick_npcs_locked(.05);self.assertGreater(runtime._y[index],3.65);self.assertLess(runtime._y[index],14.65)
            for _ in range(120):runtime._sim_time+=.05;runtime._tick_npcs_locked(.05)
            self.assertEqual(runtime._y[index],3.65);self.assertLess(actor['health'],health)
            after=actor['health']
            for _ in range(30):runtime._sim_time+=.05;runtime._tick_npcs_locked(.05)
            self.assertEqual(actor['health'],after);self.assertEqual(runtime._progression['xp'],xp)

    def test_fully_flooded_original_wmo_holds_pet_at_real_depth_without_fltmax_teleport(self):
        pet,index=self.prepared()
        from tools.world import engine_world_fixtures as world
        from backend.game_engine_adapter_streaming import Page
        (self.root/'rooms_000.wmo').write_bytes(world.room(group_liquid=0))
        self.stream.config['liquids']={'STILL':dict(frames=[str(self.root/'white.blp')])}
        spec=self.stream.config['wmos'][0]
        result=self.stream.pool.submit(self.stream._load,'w:fixed:0',dict(spec,path=spec['model'])).result(timeout=10)
        key,path,metadata,blob,surface,prepared,sight,liquids=result
        old=self.stream.pages[key];self.stream.pages[key]=Page(self.stream,path,metadata,blob,surface,prepared,sight,liquids);old.close()
        pet.update(x=-8.,y=4.,z=12.,command=0,target='',reaction=0,autocast=False)
        self.assertFalse(self.stream.water_sample(-8,4,12)['has_surface']);self.assertTrue(self.runtime._pet_swimming_locked(pet))
        health=self.runtime._combat_state['actors']['pet:'+str(pet['number'])]['health']
        self.tick(100,dt=.05)
        self.assertEqual(pet['y'],4.);self.assertEqual(pet['vy'],0.)
        self.assertEqual(self.runtime._combat_state['actors']['pet:'+str(pet['number'])]['health'],health)

    def test_same_npc_walks_actual_detour_and_holds_unloaded_destination(self):
        pet,index=self.prepared();runtime=self.runtime;before=self.stream.safe
        with runtime._lock:
            saved=runtime._npc_indices;runtime._npc_indices=[index]
            self.addCleanup(setattr,runtime,'_npc_indices',saved)
            runtime._x[index],runtime._y[index],runtime._z[index]=-4.5,3.65,12.
            runtime._npc_home_x[index],runtime._npc_home_z[index]=-4.5,12.
            runtime._npc_target_x[index],runtime._npc_target_z[index]=-2.5,12.
            runtime._npc_decision_speed[index]=3.;runtime._npc_path[index]=[];runtime._npc_path_index[index]=0
            runtime._vx[index]=runtime._vz[index]=0.;runtime._tick=1
            last=(-4.5,3.,12.)
            for _ in range(230):
                runtime._sim_time+=.05;runtime._tick_npcs_locked(.05)
                current=(runtime._x[index],runtime._y[index]-.65,runtime._z[index])
                self.assertTrue(edge(self.stream,last,current));last=current
            self.assertGreater(runtime._x[index],-3.9)
            runtime._npc_target_x[index]=20000.;runtime._npc_target_z[index]=20000.
            held=(runtime._x[index],runtime._y[index],runtime._z[index])
            runtime._tick_npcs_locked(.05)
            self.assertEqual((runtime._x[index],runtime._y[index],runtime._z[index]),held)
            self.assertEqual(runtime._vx[index],0.);self.assertEqual(runtime._vz[index],0.)
        self.assertEqual(self.stream.safe,before)

    def test_pet_swims_across_real_authored_liquid_without_snapping_to_bed(self):
        pet,index=self.prepared()
        from tools.world import engine_world_fixtures as terrain
        from backend.game_engine_adapter_streaming import Page
        path=self.root/'Test_32_32.adt';path.write_bytes(terrain.terrain(position=(0,0,3),liquid=dict(heights=[6.]*81)))
        self.stream.config['liquids']={'STILL':dict(frames=[str(self.root/'white.blp')])}
        result=self.stream.pool.submit(self.stream._load,'t:32:32',dict(path=str(path))).result(timeout=10)
        key,path,metadata,blob,surface,prepared,sight,liquids=result
        old=self.stream.pages[key];self.stream.pages[key]=Page(self.stream,path,metadata,blob,surface,prepared,sight,liquids);old.close()
        pet.update(x=-10.,y=5.55,z=20.,target='',command=1,reaction=0,autocast=False)
        with self.runtime._lock:self.runtime._x[0],self.runtime._y[0],self.runtime._z[0]=-14.,6.2,20.
        self.assertTrue(self.runtime._pet_swimming_locked(pet))
        health=self.runtime._combat_state['actors']['pet:'+str(pet['number'])]['health'];xp=pet['xp'];before=self.stream.safe
        self.tick(30,dt=.05)
        self.assertLess(pet['x'],-10.2);self.assertAlmostEqual(pet['y'],5.55)
        self.assertEqual(self.runtime._combat_state['actors']['pet:'+str(pet['number'])]['health'],health)
        self.assertEqual(pet['xp'],xp);self.assertEqual(self.stream.safe,before)
        runtime=self.runtime;saved=runtime._npc_indices;runtime._npc_indices=[index];self.addCleanup(setattr,runtime,'_npc_indices',saved)
        with runtime._lock:
            runtime._x[index],runtime._y[index],runtime._z[index]=-10.,6.2,20.
            runtime._npc_home_x[index],runtime._npc_home_z[index]=-10.,20.
            runtime._npc_target_x[index],runtime._npc_target_z[index]=-14.,20.
            runtime._npc_decision_speed[index]=3.;runtime._npc_path[index]=[];runtime._tick=1
            runtime._vx[index]=runtime._vy[index]=runtime._vz[index]=0.
            for _ in range(30):runtime._sim_time+=.05;runtime._tick_npcs_locked(.05)
            self.assertLess(runtime._x[index],-10.2);self.assertAlmostEqual(runtime._y[index],6.2)


if __name__=='__main__':unittest.main()
