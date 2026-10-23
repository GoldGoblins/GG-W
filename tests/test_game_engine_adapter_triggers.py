"""Original volume geometry, map boundaries, real quest credit and loaded teleport."""
import copy,json,struct,unittest
from tests import test_game_engine_adapter_game_data as metadata
from tests import test_game_engine_adapter_pet_world_transition as fixture
from tools.world import engine_game_data_fixtures as data
from tools.world.engine_format_fixtures import table_dbc,mpq
from backend import game_engine_adapter_triggers as triggers


class TriggerData(unittest.TestCase):
    setUp=metadata.NativeGameplayData.setUp
    mount=metadata.NativeGameplayData.mount
    healthy=metadata.NativeGameplayData.healthy

    def test_original_file_order_pages_and_real_3d_sphere_and_rotated_box(self):
        self.mount(data.trigger_entries(),'Triggers')
        result=self.data.triggers(limit=2);sphere,box=result['rows']
        self.assertEqual([row['id'] for row in result['rows']],[72,61]);self.assertEqual(result['next_offset'],2)
        self.assertEqual([row['ordinal'] for row in result['rows']],[0,1])
        self.assertTrue(triggers.contains(sphere,(10,20,33)));self.assertFalse(triggers.contains(sphere,(10,20,33.01)))
        self.assertTrue(triggers.contains(box,(10,23,30)));self.assertFalse(triggers.contains(box,(12,20,30)))
        self.assertFalse(triggers.contains(box,(10,20,32)))
        self.assertIs(result['execution_authority'],False)
        self.assertEqual(self.data.triggers([999])['missing_ids'],[999])

    def test_bad_trigger_data_rejects_and_remount_changes_geometry(self):
        entries=data.trigger_entries();raw=bytearray(entries['DBFilesClient/AreaTrigger.dbc']);struct.pack_into('<f',raw,28,float('inf'));entries['DBFilesClient/AreaTrigger.dbc']=bytes(raw)
        self.mount(entries,'Bad')
        with self.assertRaisesRegex(ValueError,'non-finite'):self.data.triggers()
        self.healthy();self.mount(data.trigger_entries(),'Good')
        self.assertEqual(self.data.triggers([72])['rows'][0]['radius_yards'],3.)


class TriggerRuntime(unittest.TestCase):
    setUp=fixture.PetTransitions.setUp
    bind=fixture.PetTransitions.bind
    service=fixture.PetTransitions.service
    tame=fixture.PetTransitions.tame
    configure=fixture.PetTransitions.configure
    load=fixture.PetTransitions.load
    unload=fixture.PetTransitions.unload
    settle=fixture.PetTransitions.settle
    distinct_floor=fixture.PetTransitions.distinct_floor

    def authored(self,action=None,origin=None):
        self.distinct_floor();entries=data.trigger_entries()
        origin=origin or [0,0,0]
        center=[-2.+origin[0],origin[1]-20.,100.+origin[2]]
        entries['DBFilesClient/AreaTrigger.dbc']=table_dbc([[72,7,*center,2.,0.,0.,0.,0.],[61,7,*center,2.,0.,0.,0.,0.]],10)
        chain=self.assets/'Data';chain.mkdir();(chain/'model.MPQ').write_bytes(mpq(entries=entries))
        from tools.world import engine_world_fixtures as world
        (self.assets/'Test_32_32.adt').write_bytes(world.terrain(position=(origin[0],origin[1],100+origin[2])))
        self.configure(archive_directory=str(chain),origin=origin,map_id=7,trigger_bindings=[dict(trigger_id=61,action=dict(kind='EVENT')),
            dict(trigger_id=72,action=action or dict(kind='EVENT'))])
        # A nonzero origin is exercised by transforming the immutable volume, not by inventing a second world scale.
        return center

    def events(self):return [row for row in self.runtime._event_journal['events'] if row['kind']=='WORLD_TRIGGER']

    def test_original_first_volume_latches_once_and_rearms_after_exit(self):
        self.authored();stream=self.load();self.settle()
        with self.runtime._lock:
            for _ in range(10):triggers.tick(self.runtime)
            self.assertEqual(len(self.events()),1);self.assertEqual(self.events()[0]['subject_id'],'72')
            self.runtime._x[0]=-10;triggers.tick(self.runtime)
            self.runtime._x[0]=-2;triggers.tick(self.runtime)
            self.assertEqual(len(self.events()),2)
            self.runtime._spell_state['epoch']+=1;triggers.tick(self.runtime)
            self.assertEqual(len(self.events()),2)

    def test_actual_visit_quest_progress_has_no_direct_reward_or_item_creation(self):
        self.authored(dict(kind='QUEST_VISIT',quest_id='quest.windmill-watch'))
        with self.runtime._lock:
            index=self.runtime._npc_index_for_id_locked('npc-guardian-01')
            self.runtime._x[0],self.runtime._y[0],self.runtime._z[0]=self.runtime._x[index],self.runtime._y[index],self.runtime._z[index]
        self.assertNotIn('error',self.runtime.accept_quest('quest.windmill-watch'))
        before=copy.deepcopy((self.runtime._economy_state,self.runtime._inventory,self.runtime._progression))
        self.load();self.settle()
        with self.runtime._lock:triggers.tick(self.runtime)
        self.assertEqual(self.runtime._quest_state['active']['quest.windmill-watch']['status'],'READY')
        self.assertEqual(before,(self.runtime._economy_state,self.runtime._inventory,self.runtime._progression))

    def test_teleport_requires_real_loaded_floor_and_obeys_combat_travel_gate(self):
        self.authored(dict(kind='TELEPORT',position=[-8.,100.65,20.]))
        stream=self.load();self.settle()
        with self.runtime._lock:
            self.runtime._combat_state['actors']['player']['engaged_target']='npc-wanderer-01'
            before=(self.runtime._x[0],self.runtime._y[0],self.runtime._z[0]);triggers.tick(self.runtime)
            self.assertEqual(before,(self.runtime._x[0],self.runtime._y[0],self.runtime._z[0]))
            self.assertEqual(self.events()[-1]['payload']['status'],'TRAVEL_OUT_OF_COMBAT_REQUIRED')
            self.runtime._combat_state['actors']['player']['engaged_target']='';self.runtime._x[0]=-10;triggers.tick(self.runtime)
            self.runtime._x[0]=-2;triggers.tick(self.runtime)
            self.assertEqual((self.runtime._x[0],self.runtime._y[0],self.runtime._z[0]),(-8.,100.65,20.))
            self.assertEqual(self.events()[-1]['payload']['status'],'TELEPORTED')
            triggers.tick(self.runtime)
            stream._trigger_rows[0]['action']['position']=(20000.,100.65,20000.)
            self.runtime._x[0]=-2;triggers.tick(self.runtime)
            self.assertEqual(self.events()[-1]['payload']['status'],'WORLD_TRIGGER_DESTINATION_NOT_READY')
            self.assertEqual(self.runtime._x[0],-2.)

    def test_actual_page_origin_and_original_axes_use_one_coordinate_transform(self):
        self.authored(origin=[-100.,-100.,-1000.]);self.load();self.settle()
        with self.runtime._lock:triggers.tick(self.runtime)
        self.assertEqual(len(self.events()),1);self.assertEqual(self.events()[0]['subject_id'],'72')

    def test_missing_map_or_quest_binding_fails_before_attachment_or_pose_change(self):
        self.authored();self.configure(map_id=8);before=(self.runtime._x[0],self.runtime._y[0],self.runtime._z[0])
        from backend.game_engine_adapter_streaming import load_world
        result=load_world(self.bridge,str(self.manifest));self.assertFalse(result['ok']);self.assertIn('another map',result['error'])
        self.assertIsNone(self.runtime._engine_world);self.assertEqual(before,(self.runtime._x[0],self.runtime._y[0],self.runtime._z[0]))


if __name__=='__main__':unittest.main()
