"""Bound native stages, actual PCM mixer, cancellation and generation fences."""
import copy,json,unittest
from tests import test_game_engine_adapter_spell_bindings as binding
from tests import test_game_engine_adapter_entity_audio as audio
from tools.world import engine_game_data_fixtures as data
from tools.world.engine_format_fixtures import mpq,table_dbc
from backend.game_engine_adapter_spell_audio import SpellAudio


def visual_audio_entries():
    entries=data.visual_entries();stages=data.row(16,{0:71,1:81,2:82,3:83,5:84})
    rows=data.spell_rows();rows[0][18]=10;rows[0][29]=1;rows[0][30]=21;rows[0][36]=4;rows[0][115]=71
    entries['DBFilesClient/Spell.dbc']=table_dbc(rows,173)
    entries['DBFilesClient/SpellVisual.dbc']=table_dbc([stages],16)
    kits=[]
    for identity,sound in ((81,160),(82,161),(83,162),(84,175)):
        kit=data.row(35,{0:identity,13:sound,15:-1,16:-1,17:-1,18:-1})
        for index in range(19,35):kit[index]=0.
        kits.append(kit)
    entries['DBFilesClient/SpellVisualKit.dbc']=table_dbc(kits,35)
    entries.update(audio.entity_entries());return entries


class NativeSpellAudio(unittest.TestCase):
    setUp=audio.EntityAudio.setUp
    step=audio.EntityAudio.step
    until=audio.EntityAudio.until
    loaded=audio.EntityAudio.loaded

    def feed(self,events,*,scope='one',running=True):
        self.helper.update(self.zone,dict(event_journal=dict(events=events)),scope=scope,running=running)

    def prepared(self):
        (self.data/'model.MPQ').write_bytes(mpq(entries=visual_audio_entries()))
        self.helper=SpellAudio(clock=lambda:self.now);self.addCleanup(self.helper.close)
        self.audio.gain(1,1,0,0,True);self.feed([])

    def event(self,sequence,stage='cast',kit=161):
        return dict(sequence=sequence,kind='SPELL_VISUAL_STAGE',subject_id='ability.island_spark',
            actor_id='player',payload=dict(stage=stage,sound_id=kit,position=[0.,0.,-2.]))

    def test_actual_original_join_selected_kit_decodes_pcm_and_has_measurable_samples(self):
        self.prepared()
        from backend.game_engine_adapter_formats import NativeFormats
        from backend.game_engine_adapter_game_data import GameplayData
        reader=NativeFormats(self.data.parent);self.addCleanup(reader.close);reader.request('mount_chain',path='Data')
        visual=GameplayData(reader).spells([9001],joins=True)['rows'][0]['visual']
        sound=visual['kits'][str(visual['cast'])]['sound_id'];self.assertEqual(sound,161)
        event=self.event(1,kit=sound);self.feed([event])
        self.until(lambda:self.loaded(161));self.assertGreater(self.step(8),0.)
        self.assertEqual(self.helper.played,1);self.feed([event]);self.assertEqual(self.helper.played,1)

    def test_channel_loop_stops_on_committed_stop_and_old_journal_cannot_replay(self):
        self.prepared();event=self.event(1,'channel',175);self.feed([event])
        self.until(lambda:self.loaded(175));self.assertGreater(self.step(10),0.)
        stop=self.event(2,'STOP',None);self.feed([event,stop])
        self.assertFalse(self.helper.owners);self.assertFalse(self.zone.entity_voices)
        self.step(50)
        self.assertLess(self.step(5),1e-9)
        self.feed([event,stop],scope='second');self.assertEqual(self.helper.played,1)
        self.feed([event,stop,self.event(3)],scope='second',running=False)
        self.feed([event,stop,self.event(3)],scope='second');self.assertEqual(self.helper.played,1)

    def test_owner_retirement_cancels_queued_decode_before_old_character_can_be_heard(self):
        self.prepared();self.feed([self.event(1,'precast',160)])
        self.assertEqual(len(self.zone.sound_queue),1)
        self.feed([],scope='second');self.assertFalse(self.zone.sound_queue)
        self.assertFalse(self.zone.model_owners);self.assertEqual(self.helper.played,1)


class RuntimeSpellStages(unittest.TestCase):
    setUp=binding.SpellBindings.setUp
    bind=binding.SpellBindings.bind
    service=binding.SpellBindings.service
    tame=binding.SpellBindings.tame
    configure=binding.SpellBindings.configure
    load=binding.SpellBindings.load
    unload=binding.SpellBindings.unload
    settle=binding.SpellBindings.settle
    distinct_floor=binding.SpellBindings.distinct_floor

    def prepared(self):
        self.distinct_floor();entries=visual_audio_entries();chain=self.assets/'Data';chain.mkdir();(chain/'model.MPQ').write_bytes(mpq(entries=entries))
        self.configure(archive_directory=str(chain),spell_bindings=[dict(spell_id=9001,ability_id='ability.island_spark')])
        self.load();self.settle();runtime=self.runtime
        target=runtime._npc_ids[runtime._npc_indices[0]];index=runtime._npc_indices[0]
        runtime._x[index],runtime._y[index],runtime._z[index]=-10.,100.65,20.;runtime._combat_target_id=target
        return target

    def stages(self):return [row['payload']['stage'] for row in self.runtime._event_journal['events'] if row['kind']=='SPELL_VISUAL_STAGE']

    def test_only_accepted_start_and_completed_actual_cast_emit_original_stages(self):
        target=self.prepared();runtime=self.runtime
        with runtime._lock:
            health=runtime._combat_state['actors'][target]['health'];resource=runtime._resource
            ok,result=runtime._start_spell_locked('ability.island_spark');self.assertTrue(ok,result);self.assertEqual(self.stages(),['precast'])
            runtime._sim_time+=.4;runtime._tick_spells_locked(.4);self.assertEqual(self.stages(),['precast'])
            runtime._sim_time+=1.;runtime._tick_spells_locked(1.)
            self.assertEqual(self.stages(),['precast','STOP','cast','impact'])
            self.assertEqual(runtime._combat_state['actors'][target]['health'],health-28.)
            self.assertEqual(runtime._resource,resource-14.)

    def test_cancelled_bound_cast_retires_precast_without_impact_payment_or_damage(self):
        target=self.prepared();runtime=self.runtime
        with runtime._lock:
            before=copy.deepcopy((runtime._combat_state['actors'][target],runtime._resource))
            self.assertTrue(runtime._start_spell_locked('ability.island_spark')[0]);runtime._cancel_spell_locked('PLAYER_CANCELLED')
            self.assertEqual(self.stages(),['precast','STOP'])
            runtime._sim_time+=10.;runtime._tick_spells_locked(10.)
            self.assertEqual(before,(runtime._combat_state['actors'][target],runtime._resource))


if __name__=='__main__':unittest.main()
