"""Mounted original spell metadata drives real casts and retires on map/epoch change."""
import copy,json,unittest
from tests import test_game_engine_adapter_pet_world_transition as fixture
from tools.world import engine_game_data_fixtures as data
from tools.world.engine_format_fixtures import table_dbc,mpq


class SpellBindings(unittest.TestCase):
    setUp=fixture.PetTransitions.setUp
    bind=fixture.PetTransitions.bind
    service=fixture.PetTransitions.service
    tame=fixture.PetTransitions.tame
    configure=fixture.PetTransitions.configure
    load=fixture.PetTransitions.load
    unload=fixture.PetTransitions.unload
    settle=fixture.PetTransitions.settle
    distinct_floor=fixture.PetTransitions.distinct_floor

    def authored(self,**binding):
        self.distinct_floor();entries=data.joined_entries();rows=data.spell_rows()
        first=rows[0];first[18]=10;first[29]=1;first[30]=21;first[36]=4;first[64]=1;first[67]=0;first[70]=0;first[73]=0.;first[74]=0.;first[75]=0.;first[76]=27;first[82]=6;first[88]=0;first[89]=0;first[90]=0;first[109]=0;first[110]=0;first[111]=0
        entries['DBFilesClient/Spell.dbc']=table_dbc(rows,173)
        entries['DBFilesClient/SpellRange.dbc']=table_dbc([data.row(22,{0:4,1:0.,2:30.,3:0})],22)
        chain=self.assets/'Data';chain.mkdir();(chain/'model.MPQ').write_bytes(mpq(entries=entries))
        self.configure(archive_directory=str(chain),spell_bindings=[dict(spell_id=9001,ability_id='ability.island_spark',**binding)])

    def test_actual_native_time_and_effect_drive_same_runtime_and_original_lua_view(self):
        self.authored(effects=True);runtime=self.runtime;original=copy.deepcopy(runtime._content['abilities']['ability.island_spark'])
        self.load();self.settle();ability=runtime._content['abilities']['ability.island_spark']
        self.assertEqual(ability['original_spell_id'],9001);self.assertEqual(ability['cast_time_s'],1.2)
        self.assertAlmostEqual(ability['range_m'],27.432)
        with runtime._lock:
            target=runtime._npc_ids[runtime._npc_indices[0]];index=runtime._npc_indices[0]
            runtime._x[index],runtime._y[index],runtime._z[index]=-1.,100.65,20.;runtime._combat_target_id=target
            health=runtime._combat_state['actors'][target]['health'];resource=runtime._resource
            ok,result=runtime._start_spell_locked('ability.island_spark')
            self.assertTrue(ok,result);self.assertEqual(result['status'],'CASTING')
            runtime._sim_time+=1.19;runtime._tick_spells_locked(1.19)
            self.assertEqual(runtime._combat_state['actors'][target]['health'],health)
            runtime._sim_time+=.01;runtime._tick_spells_locked(.01)
            self.assertEqual(runtime._combat_state['actors'][target]['health'],health-28.)
            self.assertEqual(runtime._resource,resource-original['resource_cost'])
            from backend.game_engine_adapter_gameplay import GameplayViews
            view=GameplayViews().update(runtime.ui_snapshot_locked())
            shown=next(row for row in view['spells'] if row['ref']=='ability.island_spark')
            self.assertEqual(shown['name'],'GG Spark');self.assertEqual(shown['cast_time_s'],1.2)
        self.unload();self.assertEqual(runtime._content['abilities']['ability.island_spark'],original)

    def test_unload_interrupts_uncompleted_bound_cast_without_spending_or_replaying(self):
        self.authored();self.load();self.settle();runtime=self.runtime
        with runtime._lock:
            target=runtime._npc_ids[runtime._npc_indices[0]];index=runtime._npc_indices[0]
            runtime._x[index],runtime._y[index],runtime._z[index]=-1.,100.65,20.;runtime._combat_target_id=target
            health=runtime._combat_state['actors'][target]['health'];resource=runtime._resource
            self.assertTrue(runtime._start_spell_locked('ability.island_spark')[0])
        self.unload()
        with runtime._lock:
            runtime._sim_time+=3.;runtime._tick_spells_locked(3.)
        self.assertIsNone(runtime._spell_state['pending']);self.assertEqual(runtime._resource,resource)
        self.assertEqual(runtime._combat_state['actors'][target]['health'],health)

    def test_invalid_or_unsupported_binding_leaves_original_abilities_and_character_untouched(self):
        self.authored(effects=True);value=json.loads(self.manifest.read_text());value['spell_bindings'][0]['spell_id']=9004;self.manifest.write_text(json.dumps(value))
        before=copy.deepcopy(self.runtime._content['abilities']);pose=(self.runtime._x[0],self.runtime._y[0],self.runtime._z[0])
        from backend.game_engine_adapter_streaming import load_world
        result=load_world(self.bridge,str(self.manifest))
        self.assertFalse(result['ok']);self.assertEqual(self.runtime._content['abilities'],before)
        self.assertEqual((self.runtime._x[0],self.runtime._y[0],self.runtime._z[0]),pose)
        self.assertIsNone(self.runtime._engine_world)

    def test_real_character_switch_cannot_keep_previous_characters_bound_spell(self):
        self.authored();original=copy.deepcopy(self.runtime._content['abilities']['ability.island_spark'])
        self.load();self.settle()
        self.assertEqual(self.runtime._content['abilities']['ability.island_spark']['name'],'GG Spark')
        self.assertTrue(self.session.logout(),self.session.error)
        self.assertTrue(self.session.enter(self.second),self.session.error);self.bind(self.second)
        self.assertEqual(self.runtime._content['abilities']['ability.island_spark'],original)


if __name__=='__main__':unittest.main()
