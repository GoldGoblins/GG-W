"""Real owned animals observe current walking hulls and combatant sight/range."""
import copy,json,struct,tempfile,time,unittest
from pathlib import Path
import test_game_engine_adapter_services as fixture
from backend.game_engine_adapter_formats import PROJECT
from backend.game_engine_adapter_streaming import WorldStream,Page
from tools.world import engine_world_fixtures as world

class PetWorld(unittest.TestCase):
    setUp=fixture.Services.setUp
    publish=fixture.Services.publish
    call=fixture.Services.call
    control=fixture.Services.control
    view=fixture.Services.view
    service=fixture.Services.service
    tame=fixture.Services.tame
    def prepared(self):
        pet=self.tame();tmp=tempfile.TemporaryDirectory(dir=PROJECT/'qml');self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        manifest=world.make(self.root)
        # Equal floors isolate walking/sight masks from the separate ledge policy.
        (self.root/'Test_32_32.adt').write_bytes(world.terrain(position=(0,0,3)))
        stream=WorldStream();self.addCleanup(stream.close);stream.configure(str(manifest))
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            stream.update(-2,3.65,12)
            if stream.last_error:self.fail(stream.last_error)
            if len(stream.pages)==2 and stream.pending is None:break
            time.sleep(.005)
        else:self.fail('Actual original world pages did not settle')
        self.stream=stream;runtime=self.runtime
        with runtime._lock:
            runtime._engine_world=stream
            runtime._x[0],runtime._y[0],runtime._z[0]=-2.5,3.65,12
            identity='npc-wanderer-01';index=runtime._npc_index_for_id_locked(identity)
            runtime._x[index],runtime._y[index],runtime._z[index]=-3.5,3.65,12
            runtime._alive[index]=True
            pet.update(x=-4.5,y=3.,z=12.,vx=0.,vz=0.,target=identity,command=2)
            stream.safe=(-2.5,3.65,12)
        self.addCleanup(setattr,runtime,'_engine_world',None)
        return pet,index
    def tick(self,count=1,dt=1/60):
        with self.runtime._lock:
            for _ in range(count):
                self.runtime._tick+=1;self.runtime._sim_time+=dt;self.runtime._tick_services_locked(dt)
    def replace_wall_masks(self,flags):
        path=self.root/'rooms_000.wmo';data=bytearray(path.read_bytes());offset=data.index(b'YPOM')+8
        for face in (4,5):data[offset+face*2]=flags
        path.write_bytes(data)
        spec=self.stream.config['wmos'][0]
        result=self.stream.pool.submit(self.stream._load,'w:fixed:0',dict(spec,path=spec['model'])).result(timeout=10)
        key,path,metadata,blob,surface,prepared,sight,liquids=result
        old=self.stream.pages[key];page=Page(self.stream,path,metadata,blob,surface,prepared,sight,liquids)
        self.stream.pages[key]=page;old.close()
    def test_pet_cannot_hit_through_wall_that_player_can_see_around(self):
        pet,index=self.prepared();runtime=self.runtime;enemy=runtime._combat_state['actors'][pet['target']]
        with runtime._lock:self.assertTrue(runtime._npc_line_of_sight_locked(index))
        before=copy.deepcopy(enemy);xp=pet['xp'];self.tick(20)
        self.assertEqual(enemy,before);self.assertEqual(pet['xp'],xp)
        self.assertEqual(runtime._combat_state['actors']['pet:'+str(pet['number'])]['cooldown_until'],0)
        # Same actor, same range; actual newly decoded sight mask now admits it.
        self.replace_wall_masks(0x22);self.tick(90)
        self.assertLess(enemy['health'],before['health'])
    def test_pet_vertical_range_uses_actual_height_and_does_not_spend_attack(self):
        pet,index=self.prepared();pet.update(x=-3.5,z=12.)
        with self.runtime._lock:self.runtime._y[index]=15.
        enemy=self.runtime._combat_state['actors'][pet['target']];before=copy.deepcopy(enemy)
        self.tick(20);self.assertEqual(enemy,before)
        self.assertEqual(self.runtime._combat_state['actors']['pet:'+str(pet['number'])]['cooldown_until'],0)
    def test_owned_movement_stops_at_walking_hull_without_changing_player_safe_position(self):
        pet,index=self.prepared();safe=self.stream.safe
        with self.runtime._lock:
            moved=self.runtime._pet_move_locked(pet,-3.2,12)
        self.assertEqual(moved,(pet['x'],pet['y'],pet['z']));self.assertEqual(self.stream.safe,safe)
        self.replace_wall_masks(0x24) # Sight-only triangle must not become a walking wall.
        with self.runtime._lock:moved=self.runtime._pet_move_locked(pet,-3.2,12)
        self.assertAlmostEqual(moved[0],-3.2);self.assertEqual(moved[1],3.)
        self.assertEqual(self.stream.safe,safe)
    def test_owned_movement_holds_unloaded_floor_without_player_spawn_teleport(self):
        pet,index=self.prepared();safe=self.stream.safe
        with self.runtime._lock:moved=self.runtime._pet_move_locked(pet,20000,20000)
        self.assertEqual(moved,(pet['x'],pet['y'],pet['z']));self.assertEqual(self.stream.safe,safe)
    def test_retained_npc_sight_observes_wall_change_without_cached_player_result(self):
        pet,index=self.prepared();runtime=self.runtime
        with runtime._lock:
            start=(pet['x'],pet['y']+.35,pet['z']);end=(runtime._x[index],runtime._y[index]+.5,runtime._z[index])
            self.assertFalse(runtime._line_of_sight_locked(start,end,ignore_index=index))
        self.replace_wall_masks(0x22)
        with runtime._lock:self.assertTrue(runtime._line_of_sight_locked(start,end,ignore_index=index))

if __name__=='__main__':unittest.main()
