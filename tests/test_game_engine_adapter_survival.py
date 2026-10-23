"""Actual liquid contact, canonical damage/custody and mirror timer edges."""
import copy,os,unittest
from pathlib import Path
from unittest.mock import patch
import test_game_engine_adapter_spells as spells


class Survival(unittest.TestCase):
    setUp=spells.Spells.setUp

    def test_natural_fresh_runtime_first_step_without_eager_combat_actor_is_safe(self):
        from backend.game_engine_host import GameEngineRuntime
        fresh=GameEngineRuntime();self.addCleanup(fresh.shutdown)
        self.assertNotIn('player',fresh._combat_state['actors'])
        fresh._survival.update(breath_s=12.,fatigue_s=23.)
        snapshot=fresh.step()
        self.assertIsInstance(snapshot,dict);self.assertNotIn('error',snapshot)
        self.assertEqual((fresh._survival['breath_s'],fresh._survival['fatigue_s']),(12.,23.))

    def test_cleared_canonical_actor_suspends_contact_without_inventing_actor_or_resetting_balances(self):
        r=self.runtime;r._combat_state['actors'].pop('player')
        before=copy.deepcopy(r._combat_state)
        r._survival.update(breath_s=12.,fatigue_s=23.,breath_rate=-1,fatigue_rate=10,
                           submerged=True,fatigued=True,hazard='MAGMA',next_damage=1.,
                           next_fatigue_damage=1.,next_hazard_damage=1.)
        with patch.object(r,'_water_sample_locked',side_effect=AssertionError('no actor to query')):
            r._tick_survival_locked(2.)
        self.assertEqual(r._combat_state,before)
        self.assertEqual((r._survival['breath_s'],r._survival['fatigue_s']),(12.,23.))
        self.assertEqual(r._survival_view_locked()['mirror_timers'],[])
        self.assertEqual((r._survival['next_damage'],r._survival['next_fatigue_damage'],r._survival['next_hazard_damage']),(0.,0.,0.))
        self.assertEqual([(event['event'],event['args']) for event in r._spell_state['events']],
                         [('MIRROR_TIMER_STOP',['BREATH']),('MIRROR_TIMER_STOP',['EXHAUSTION'])])
    def advance(self,seconds,*,submerged=True,step=.1):
        r=self.runtime
        sample=dict(has_surface=True,height_m=r._y[0]+(2. if submerged else -.5),body_kind='WATER')
        with patch.object(r,'_water_sample_locked',return_value=sample):
            while seconds>1e-8:
                dt=min(step,seconds);seconds-=dt
                with r._lock:r._sim_time+=dt;r._tick_survival_locked(dt)

    def liquid(self,seconds,kind='MAGMA',*,contact=True,step=.1,**fields):
        r=self.runtime
        sample=dict(has_surface=True,height_m=r._y[0]+(.1 if contact else -.75),body_kind=kind)
        sample.update(fields)
        with patch.object(r,'_water_sample_locked',return_value=sample):
            while seconds>1e-8:
                dt=min(step,seconds);seconds-=dt
                with r._lock:r._sim_time+=dt;r._tick_survival_locked(dt)

    def test_body_contact_does_not_count_as_head_submersion(self):
        self.advance(10,submerged=False)
        self.assertEqual(self.runtime._survival['breath_s'],60.)
        self.assertFalse(self.runtime._survival['submerged'])

    def test_depleted_breath_causes_real_damage_at_two_second_boundaries(self):
        r=self.runtime;actor=r._combat_state['actors']['player'];health=actor['health']
        self.advance(60.)
        self.assertEqual(actor['health'],health)
        self.advance(1.9);self.assertEqual(actor['health'],health)
        self.advance(.1);self.assertAlmostEqual(actor['health'],health-actor['max_health']*.1)
        self.assertEqual(r._last_combat['attacker_id'],'environment:drowning')

    def test_surface_refill_stops_bar_and_does_not_keep_dealing_damage(self):
        r=self.runtime;self.advance(62.);health=r._combat_state['actors']['player']['health']
        self.advance(6.,submerged=False)
        self.assertEqual(r._survival['breath_s'],60.);self.assertFalse(r._survival['submerged'])
        self.assertEqual(r._combat_state['actors']['player']['health'],health)
        events=[e['event'] for e in r._spell_state['events']]
        self.assertEqual(events,['MIRROR_TIMER_START','MIRROR_TIMER_START','MIRROR_TIMER_STOP'])
        self.assertEqual([e['args'][3] for e in r._spell_state['events'] if e['event']=='MIRROR_TIMER_START'],[-1,10])

    def test_saved_breath_does_not_refill_on_load_and_no_damage_replays(self):
        r=self.runtime;self.advance(42.);breath=r._survival['breath_s']
        self.assertIsNone(r.save_state().get('error'));r._survival['breath_s']=60.
        self.assertIsNone(r.load_state().get('error'))
        self.assertAlmostEqual(r._survival['breath_s'],breath)
        health=r._combat_state['actors']['player']['health'];self.advance(1.)
        self.assertEqual(r._combat_state['actors']['player']['health'],health)

    def test_dead_ghost_and_vehicle_never_receive_drowning_damage(self):
        r=self.runtime;actor=r._combat_state['actors']['player'];actor['alive']=False;actor['health']=0.
        self.advance(90.);self.assertEqual(actor['health'],0.)
        actor['alive']=True;actor['health']=actor['max_health'];r._vehicle_kind='BOAT'
        self.advance(90.);self.assertEqual(actor['health'],actor['max_health'])

    def test_lifecycle_elapsed_time_is_independent_of_update_cadence(self):
        r=self.runtime;initial=copy.deepcopy((r._survival,r._combat_state,r._spell_state));self.advance(65.)
        expected=(round(r._survival['breath_s'],5),r._combat_state['actors']['player']['health'])
        r._survival,r._combat_state,r._spell_state=copy.deepcopy(initial);r._sim_time=0.
        self.advance(65.,step=1.)
        self.assertEqual((round(r._survival['breath_s'],5),r._combat_state['actors']['player']['health']),expected)

    def test_magma_and_slime_require_actual_body_contact_and_pulse_every_two_seconds(self):
        r=self.runtime;actor=r._combat_state['actors']['player'];health=actor['health']
        self.liquid(5.,contact=False)
        self.assertEqual(actor['health'],health);self.assertEqual(r._survival['hazard'],'')
        self.liquid(1.9);self.assertEqual(actor['health'],health)
        self.liquid(.1);self.assertAlmostEqual(actor['health'],health-actor['max_health']*.2)
        self.assertEqual(r._last_combat['status'],'LAVA')
        self.assertEqual(r._last_combat['policy'],'GG_AUTHORED_SURVIVAL_POLICY')
        self.assertFalse(r._survival['submerged']);self.assertEqual(r._survival['breath_s'],60.)
        self.liquid(2.,kind='SLIME')
        self.assertAlmostEqual(actor['health'],health-actor['max_health']*.3)
        self.assertEqual(r._last_combat['attacker_id'],'environment:slime')
        self.assertFalse(r._spell_state['events'])  # Environmental is not an invented client timer.

    def test_leaving_hazard_or_switching_liquid_resets_the_live_damage_interval(self):
        r=self.runtime;actor=r._combat_state['actors']['player'];health=actor['health']
        self.liquid(1.9);self.liquid(.1,contact=False)
        self.liquid(1.9);self.assertEqual(actor['health'],health)
        self.liquid(.1);health=actor['health']
        self.liquid(1.,kind='SLIME');self.assertEqual(actor['health'],health)
        self.liquid(.9,kind='SLIME');self.assertEqual(actor['health'],health)
        self.liquid(.1,kind='SLIME');self.assertAlmostEqual(actor['health'],health-actor['max_health']*.1)

    def test_actual_spell_ward_absorbs_canonical_lava_damage(self):
        r=self.runtime;actor=r._combat_state['actors']['player'];health=actor['health']
        self.assertNotIn('error',r.activate_ability('ability.watch_ward'))
        self.liquid(2.)
        damage=actor['max_health']*.2
        self.assertAlmostEqual(r._last_combat['absorbed'],min(40.,damage))
        self.assertAlmostEqual(actor['health'],health-max(0.,damage-40.))

    def test_hazard_defeat_uses_real_corpse_gear_and_cast_lifecycle_once(self):
        r=self.runtime;actor=r._combat_state['actors']['player'];actor['health']=1.
        registry=copy.deepcopy(r._item_instances)
        self.assertNotIn('error',r.activate_ability('ability.tide_mend'))
        self.liquid(2.)
        self.assertFalse(r._combat_state['actors']['player']['alive'])
        self.assertIsNone(r._spell_state['pending']);self.assertIsNotNone(r._services['death'])
        self.assertFalse(r._services['death']['ghost'])
        self.assertEqual(r._services['death']['position'],r._lifecycle_position_locked())
        self.assertEqual(set(registry),set(r._item_instances))
        for identity,before in registry.items():
            after=r._item_instances[identity]
            self.assertEqual(after['owner_id'],before['owner_id'])
            self.assertEqual(after['quantity'],before['quantity'])
            expected=max(0.,before['condition']-.1) if before['location']=='EQUIPPED' and before['owner_id']=='player' and before['kind'] in ('WEAPON','ARMOR') else before['condition']
            self.assertAlmostEqual(after['condition'],expected)
        self.assertEqual(r._survival_view_locked()['mirror_timers'],[])
        count=r._combat_state['actors']['player']['defeated_count']
        self.liquid(30.,kind='SLIME');self.assertEqual(r._combat_state['actors']['player']['defeated_count'],count)

    def test_ghost_and_real_local_vehicle_protection_skip_all_environment_damage(self):
        r=self.runtime;actor=r._combat_state['actors']['player'];health=actor['health']
        for vehicle in ('BOAT','HOVERBOARD'):
            r._vehicle_kind=vehicle;self.liquid(30.)
            self.assertEqual(actor['health'],health);self.assertEqual(r._survival['hazard'],'')
        r._vehicle_kind='NONE'
        # Even an inconsistent alive flag must not make a released ghost burn.
        r._services['death']={'ghost':True};self.liquid(30.,kind='SLIME')
        self.assertEqual(actor['health'],health);self.assertFalse(r._spell_state['events'])

    def test_no_surface_dry_or_nonfinite_liquid_never_causes_damage(self):
        r=self.runtime;actor=r._combat_state['actors']['player'];health=actor['health']
        for fields in ({'has_surface':False},{'body_kind':'NONE'},
                       {'height_m':float('nan')},{'height_m':float('inf')},{'height_m':True}):
            self.liquid(10.,**fields)
            self.assertEqual(actor['health'],health)
        self.assertFalse(r._spell_state['events'])

    def test_native_flooded_volume_is_real_submersion_and_has_no_fake_surface(self):
        r=self.runtime
        self.liquid(1.,kind='STILL',has_surface=False,height_m=1e38,surface_model='GG_ENGINE_FLOODED_VOLUME')
        self.assertTrue(r._survival['submerged']);self.assertAlmostEqual(r._survival['breath_s'],59.)
        self.assertEqual(r._survival['hazard'],'')

    def test_surface_refill_restates_rate_once_stops_at_full_and_reentry_reverses(self):
        r=self.runtime;self.advance(2.);self.advance(.1,submerged=False)
        edges=r._spell_state['events']
        self.assertEqual([(e['event'],e['args'][3]) for e in edges],[('MIRROR_TIMER_START',-1),('MIRROR_TIMER_START',10)])
        timers=r._survival_view_locked()['mirror_timers']
        self.assertEqual(len(timers),1);self.assertEqual(timers[0]['scale'],10)
        self.advance(.05,submerged=False);self.assertEqual(len(r._spell_state['events']),2)
        self.advance(.1);self.assertEqual(r._spell_state['events'][-1]['args'][3],-1)
        self.advance(1.,submerged=False)
        self.assertEqual(r._spell_state['events'][-1]['event'],'MIRROR_TIMER_STOP')
        self.assertEqual(r._survival_view_locked()['mirror_timers'],[])

    def test_gg_sea_and_original_ocean_kind_never_guess_deep_water_fatigue(self):
        r=self.runtime;actor=r._combat_state['actors']['player'];health=actor['health']
        for kind,model in (('SEA','LAYERED_GERSTNER_SWELLS_PLUS_TIDE'),('OCEAN','GG_ENGINE_WET_GRID')):
            self.liquid(90.,kind=kind,surface_model=model)
            self.assertEqual(r._survival['fatigue_s'],60.);self.assertFalse(r._survival['fatigued'])
            self.assertFalse(r._survival['fatigue_supported']);self.assertEqual(actor['health'],health)

    def test_explicit_original_provider_flag_drives_fatigue_and_real_damage_without_head_submersion(self):
        r=self.runtime;actor=r._combat_state['actors']['player'];health=actor['health']
        with patch.object(r,'_engine_world',object(),create=True):
            self.liquid(60.,kind='OCEAN',surface_model='GG_ENGINE_WET_GRID',deep_water_fatigue=True)
            self.assertTrue(r._survival['fatigue_supported']);self.assertEqual(r._survival['fatigue_s'],0.)
            self.assertFalse(r._survival['submerged']);self.assertEqual(actor['health'],health)
            self.liquid(2.,kind='OCEAN',surface_model='GG_ENGINE_WET_GRID',deep_water_fatigue=True)
            self.assertAlmostEqual(actor['health'],health-actor['max_health']*.1)
            self.assertEqual(r._last_combat['status'],'FATIGUE')
            self.liquid(6.,kind='OCEAN',surface_model='GG_ENGINE_WET_GRID',deep_water_fatigue=False)
        self.assertEqual(r._survival['fatigue_s'],60.);self.assertEqual(r._survival_view_locked()['mirror_timers'],[])
        self.assertEqual([e['args'][0] for e in r._spell_state['events']],['EXHAUSTION']*3)
        self.assertEqual([e['args'][3] for e in r._spell_state['events'] if e['event']=='MIRROR_TIMER_START'],[-1,10])

    def test_finite_balances_restore_without_transient_damage_deadlines_or_replayed_hazard(self):
        r=self.runtime;r._survival.update(breath_s=12.,fatigue_s=23.,hazard='MAGMA',next_hazard_damage=1.)
        saved=r._survival_save_locked();self.assertEqual(saved,{'breath_s':12.,'fatigue_s':23.})
        r._restore_survival_locked(saved)
        self.assertEqual(r._survival['breath_s'],12.);self.assertEqual(r._survival['fatigue_s'],23.)
        self.assertEqual(r._survival['hazard'],'');self.assertEqual(r._survival_view_locked()['mirror_timers'],[])
        for value in (True,-1.,61.,float('inf'),float('nan'),'1'):
            r._restore_survival_locked({'breath_s':value,'fatigue_s':value})
            self.assertEqual((r._survival['breath_s'],r._survival['fatigue_s']),(60.,60.))

    def test_actual_atomic_save_preserves_both_balances_but_does_not_resume_old_damage(self):
        from backend.game_engine_local_characters import CharacterStore
        r=self.runtime;r._state_store=CharacterStore(Path(os.environ['XDG_STATE_HOME'])/'survival-save')
        r._persistence_key='0'*32
        r._survival.update(breath_s=12.,fatigue_s=23.,hazard='MAGMA',next_hazard_damage=.1)
        r.save_state(snapshot=False)
        r._survival.update(breath_s=0.,fatigue_s=0.,next_damage=.1,next_fatigue_damage=.1)
        self.assertNotIn('error',r.load_state())
        self.assertEqual((r._survival['breath_s'],r._survival['fatigue_s']),(12.,23.))
        self.assertEqual(r._survival['next_hazard_damage'],0.);self.assertEqual(r._survival['hazard'],'')
        health=r._combat_state['actors']['player']['health'];self.advance(1.)
        self.assertEqual(r._combat_state['actors']['player']['health'],health)

    def test_failed_atomic_save_keeps_live_balances_and_the_previous_real_save(self):
        from backend.game_engine_local_characters import CharacterStore
        r=self.runtime;r._state_store=CharacterStore(Path(os.environ['XDG_STATE_HOME'])/'survival-save')
        r._persistence_key='0'*32;r._survival.update(breath_s=12.,fatigue_s=23.)
        r.save_state(snapshot=False);saved=r._state_store.load(r._persistence_key)
        r._survival.update(breath_s=7.,fatigue_s=8.);before=copy.deepcopy(r._survival)
        with patch.object(r._state_store,'save',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):r.save_state(snapshot=False)
        self.assertEqual(r._survival,before);self.assertEqual(r._state_store.load(r._persistence_key),saved)

    def test_large_tick_is_bounded_and_does_not_replay_a_stalled_damage_backlog(self):
        r=self.runtime;actor=r._combat_state['actors']['player'];health=actor['health']
        self.liquid(100.,kind='SLIME',step=100.)
        self.assertAlmostEqual(actor['health'],health-actor['max_health']*.4)
        self.liquid(.1,kind='SLIME');self.assertAlmostEqual(actor['health'],health-actor['max_health']*.4)
        self.liquid(1.9,kind='SLIME');self.assertAlmostEqual(actor['health'],health-actor['max_health']*.5)
        before=copy.deepcopy((r._survival,r._combat_state,r._spell_state))
        for elapsed in (True,-1.,0.,float('nan'),float('inf'),'1'):
            r._tick_survival_locked(elapsed)
            self.assertEqual((r._survival,r._combat_state,r._spell_state),before)

    def test_hazard_elapsed_time_is_independent_of_update_cadence(self):
        r=self.runtime;initial=copy.deepcopy((r._survival,r._combat_state,r._spell_state));start=r._sim_time
        self.liquid(5.,kind='SLIME')
        expected=r._combat_state['actors']['player']['health']
        r._survival,r._combat_state,r._spell_state=copy.deepcopy(initial);r._sim_time=start
        self.liquid(5.,kind='SLIME',step=1.)
        self.assertEqual(r._combat_state['actors']['player']['health'],expected)


if __name__=='__main__':unittest.main()
