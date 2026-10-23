"""Cast effects, cancellation and original Lua observe the canonical simulation."""
import copy,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from backend import game_engine_mmo as mmo,game_engine_character_creation as appearance


class Spells(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup);root=Path(directory.name)
        env={'XDG_'+kind+'_HOME':str(root/kind.lower()) for kind in ('STATE','CONFIG','CACHE','DATA')}
        for context in (patch.dict(os.environ,env),patch.object(mmo,'DEFAULT_STASH_PATH',root/'stash.json'),patch.object(appearance,'STATE_PATH',root/'appearance.json')):
            context.start();self.addCleanup(context.stop)
        from backend.game_engine_host import GameEngineRuntime
        self.runtime=GameEngineRuntime();self.addCleanup(self.runtime.shutdown)
        with self.runtime._lock:
            self.runtime._ensure_combat_actors_locked()
            self.runtime._vx[0]=self.runtime._vy[0]=self.runtime._vz[0]=0.

    def target(self):
        r=self.runtime
        with r._lock:
            identity=r._npc_ids[r._npc_indices[0]];index=r._npc_indices[0]
            r._x[0]=r._x[index]+1.;r._y[0]=r._y[index];r._z[0]=r._z[index]
            r._combat_target_id=identity
        return identity

    def advance(self,seconds,step=.05):
        r=self.runtime
        while seconds>1e-8:
            elapsed=min(step,seconds);seconds-=elapsed
            with r._lock:r._sim_time+=elapsed;r._tick_spells_locked(elapsed)

    def control(self,op,**fields):
        return self.runtime.client_control(json.dumps(dict(kind='spell',op=op,**fields)))

    def test_cast_spends_resource_and_damages_only_after_completion(self):
        target=self.target();r=self.runtime;before=r._combat_state['actors'][target]['health'];energy=r._resource
        result=r.activate_ability('ability.island_spark')
        self.assertIsNone(result.get('error'));self.assertEqual(result['ability_result']['status'],'CASTING')
        self.advance(1.4);self.assertEqual(r._combat_state['actors'][target]['health'],before);self.assertEqual(r._resource,energy)
        self.advance(.1)
        self.assertEqual(r._combat_state['actors'][target]['health'],before-28.)
        self.assertEqual(r._resource,energy-14.);self.assertEqual(r._ability_cooldowns['ability.island_spark'],2.)
        self.advance(2.)
        self.assertEqual(r._combat_state['actors'][target]['health'],before-28.)

    def test_movement_stop_and_target_death_cancel_without_spending(self):
        target=self.target();r=self.runtime;energy=r._resource
        self.assertIsNone(r.activate_ability('ability.island_spark').get('error'))
        r._input['forward']=1.;self.advance(.1);r._input['forward']=0.
        self.assertIsNone(r._spell_state['pending']);self.assertEqual(r._resource,energy)
        self.assertIsNone(r.activate_ability('ability.island_spark').get('error'))
        self.assertIsNone(self.control('Stop').get('error'));self.advance(2.)
        self.assertEqual(r._resource,energy)
        r.activate_ability('ability.island_spark');r._combat_state['actors'][target]['alive']=False
        self.advance(.1);self.assertIsNone(r._spell_state['pending']);self.assertEqual(r._resource,energy)

    def test_channel_heals_exactly_three_times_and_charges_once(self):
        r=self.runtime;actor=r._combat_state['actors']['player'];actor['health']=actor['max_health']-80.
        before=actor['health'];energy=r._resource
        self.assertIsNone(r.activate_ability('ability.tide_mend').get('error'))
        self.assertEqual(r._resource,energy-24.)
        self.advance(.9);self.assertEqual(actor['health'],before)
        self.advance(.1);self.assertEqual(actor['health'],before+16.)
        self.advance(2.);self.assertEqual(actor['health'],before+48.)
        self.assertIsNone(r._spell_state['pending']);self.advance(3.);self.assertEqual(actor['health'],before+48.)

    def test_pushback_extends_cast_but_reduces_channel(self):
        self.target();r=self.runtime;actor=r._combat_state['actors']['player']
        r.activate_ability('ability.island_spark');end=r._spell_state['pending']['end']
        actor['health']-=1.;self.advance(.1);self.assertAlmostEqual(r._spell_state['pending']['end'],end+.5)
        self.control('Stop');r.activate_ability('ability.tide_mend');end=r._spell_state['pending']['end']
        actor['health']-=1.;self.advance(.1);self.assertAlmostEqual(r._spell_state['pending']['end'],end-.5)

    def test_form_changes_real_armor_and_active_click_cancels_with_zero_energy(self):
        r=self.runtime;before=r._player_combat_profile_locked()['armor']
        self.assertIsNone(r.activate_ability('ability.reef_guard').get('error'))
        self.assertEqual(r._player_combat_profile_locked()['armor'],before+20.)
        r._resource=0.;self.assertIsNone(r.activate_ability('ability.reef_guard').get('error'))
        self.assertEqual(r._player_combat_profile_locked()['armor'],before)

    def test_ward_absorbs_real_combat_damage(self):
        from backend import game_engine_combat as combat
        r=self.runtime;actor=r._combat_state['actors']['player'];before=actor['health']
        self.assertIsNone(r.activate_ability('ability.watch_ward').get('error'))
        dealt,absorbed=combat.deal_damage(r._combat_state,actor,55.,'npc-wanderer-01',r._sim_time)
        self.assertEqual((dealt,absorbed),(15.,40.));self.assertEqual(actor['health'],before-15.)

    def test_invalid_definition_and_eligibility_have_no_effects(self):
        r=self.runtime;row=r._content['abilities']['ability.watch_ward'];before=copy.deepcopy((r._resource,r._combat_state,r._ability_cooldowns))
        row['resource_cost']=float('nan');self.assertEqual(r.activate_ability(row['id'])['error'],'SPELL_DEFINITION_INVALID')
        row['resource_cost']=18.;row['required_level']=60;self.assertEqual(r.activate_ability(row['id'])['error'],'SPELL_LEVEL_REQUIRED')
        row['required_level']=1;row['classes']=['absent'];self.assertEqual(r.activate_ability(row['id'])['error'],'SPELL_CLASSES_REQUIRED')
        self.assertEqual((r._resource,r._combat_state,r._ability_cooldowns),before)

    def test_target_cursor_can_be_cancelled_and_never_spends_before_target(self):
        r=self.runtime;r._combat_target_id='';energy=r._resource
        result=r.activate_ability('ability.island_spark');self.assertEqual(result['ability_result']['status'],'TARGETING')
        self.assertEqual(r._resource,energy);self.assertTrue(r._spells_view_locked()['targeting'])
        self.assertIsNone(self.control('StopTargeting').get('error'));self.assertFalse(r._spells_view_locked()['targeting'])
        self.assertEqual(self.control('Target',unit='player')['error'],'NO_SPELL_TARGETING')

    def test_load_does_not_replay_an_old_pending_cast_or_stance(self):
        self.target();r=self.runtime;r.activate_ability('ability.island_spark');epoch=r._spell_state['epoch']
        self.assertIsNone(r.save_state().get('error'));self.assertIsNone(r.load_state().get('error'))
        self.assertIsNone(r._spell_state['pending']);self.assertIsNone(r._spell_state['form']);self.assertGreater(r._spell_state['epoch'],epoch)

    def test_channel_target_death_cannot_repeat_defeat_rewards_during_catchup(self):
        target=self.target();r=self.runtime;definition=copy.deepcopy(r._content['abilities']['ability.tide_mend'])
        definition.update(id='ability.test_channel',name='Fixture channel',target='hostile',range_m=20.,resource_cost=0.)
        definition['effect']=dict(damage=100000.,particle_burst=0)
        r._content['abilities'][definition['id']]=definition
        with patch.object(r,'_handle_npc_defeat_locked',wraps=r._handle_npc_defeat_locked) as reward:
            self.assertIsNone(r.activate_ability(definition['id']).get('error'));self.advance(3.,step=3.)
            self.assertEqual(reward.call_count,1)
        self.assertFalse(r._combat_state['actors'][target]['alive']);self.assertIsNone(r._spell_state['pending'])

    def test_spell_hit_uses_canonical_animation_memory_and_combat_journal(self):
        target=self.target();r=self.runtime
        with patch.object(r,'_start_character_action_locked',wraps=r._start_character_action_locked) as animation, \
                patch('backend.game_engine_adapter_spells.identity.record_memory') as memory:
            self.assertIsNone(r.activate_ability('ability.island_spark').get('error'));self.advance(1.5)
            animation.assert_any_call(target,'HitReact')
            memory.assert_called_once()
            self.assertEqual(memory.call_args.args[1:4],(target,'PLAYER_ATTACK','player'))
        self.assertEqual(r._last_combat['kind'],'SPELL')
        self.assertEqual(r._last_combat['attacker_id'],'player')
        self.assertEqual(r._last_combat['defender_id'],target)
        event=next(e for e in reversed(r._event_journal['events']) if e.get('kind')=='COMBAT_ATTACK')
        self.assertEqual(event['payload']['kind'],'SPELL');self.assertEqual(event['payload']['damage'],28.)

    def test_lethal_mixed_effect_cannot_heal_or_attach_status_to_dead_target(self):
        target=self.target();r=self.runtime;row=copy.deepcopy(r._content['abilities']['ability.island_spark'])
        row.update(id='ability.test_lethal_mixed',cast_time_s=0.,resource_cost=0.)
        row['effect']=dict(damage=100000.,heal=100.,status='regen',amount=50.,duration_s=10.)
        r._content['abilities'][row['id']]=row
        self.assertIsNone(r.activate_ability(row['id']).get('error'))
        actor=r._combat_state['actors'][target]
        self.assertFalse(actor['alive']);self.assertEqual(actor['health'],0.)
        self.assertFalse(any(s.get('kind')=='regen' for s in actor.get('statuses',[])))


class OriginalLuaSpells(unittest.TestCase):
    setUp=Spells.setUp
    target=Spells.target
    def test_original_cast_form_and_target_cursor_feed_and_cancel(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtCore import QObject
        from backend.game_engine_presentation import Presentation
        self.app=QGuiApplication.instance() or QGuiApplication([])
        class Bridge(QObject):
            def gameEngineClientControl(owner,raw):return json.dumps(self.runtime.client_control(raw))
            def gameEngineAbility(owner,ref):return json.dumps(self.runtime.activate_ability(ref))
        self.bridge=Bridge();presentation=Presentation(self.bridge,device=False);self.addCleanup(presentation.close)
        def publish():presentation.last_update=0.;presentation.update(self.runtime.snapshot())
        def call(chunk):presentation.lua.execute(chunk);presentation._ui_requests(presentation.lua.request('requests'));publish()
        publish();ui=presentation.lua
        self.assertEqual(ui.evaluate('return GetNumShapeshiftForms()'),[1])
        call('CastShapeshiftForm(1)');self.assertEqual(ui.evaluate('local _,_,active=GetShapeshiftFormInfo(1);return active'),[1])
        call('CastShapeshiftForm(1)');self.assertEqual(ui.evaluate('local _,_,active=GetShapeshiftFormInfo(1);return active'),[None])
        self.runtime._spell_state['gcd_until']=0.
        call('CastSpellByName("Island Spark")');self.assertEqual(ui.evaluate('return SpellIsTargeting()'),[1])
        call('SpellStopTargeting()');self.assertEqual(ui.evaluate('return SpellIsTargeting()'),[None])
        self.target();publish()
        ui.execute("CAST_EVENTS={};CAST_F=CreateFrame('Frame');CAST_F:RegisterEvent('SPELLCAST_START');CAST_F:RegisterEvent('SPELLCAST_INTERRUPTED');CAST_F:SetScript('OnEvent',function() table.insert(CAST_EVENTS,event) end)")
        call('CastSpellByName("Island Spark")');self.assertEqual(ui.evaluate('return SpellStopCasting()'),[1])
        presentation._ui_requests(ui.request('requests'));publish()
        self.assertIsNone(self.runtime._spell_state['pending'])
        self.assertEqual(ui.evaluate("return table.concat(CAST_EVENTS,',')"),['SPELLCAST_START,SPELLCAST_INTERRUPTED'])


if __name__=='__main__':unittest.main()
