"""Independent authoritative availability and actual native VM lifecycle checks."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


class SpellLifecycle(unittest.TestCase):
    def setUp(self):
        isolated=tempfile.TemporaryDirectory(prefix='gg-spell-lifecycle-');self.addCleanup(isolated.cleanup)
        root=Path(isolated.name)
        env={'XDG_'+kind+'_HOME':str(root/kind.lower()) for kind in ('STATE','CONFIG','CACHE','DATA')}
        env['QT_QPA_PLATFORM']='offscreen'
        environment=patch.dict(os.environ,env);environment.start();self.addCleanup(environment.stop)
        from backend import game_engine_mmo as mmo,game_engine_character_creation as appearance
        for scoped in (patch.object(mmo,'DEFAULT_STASH_PATH',root/'stash.json'),patch.object(appearance,'STATE_PATH',root/'appearance.json')):
            scoped.start();self.addCleanup(scoped.stop)
        from backend.game_engine_host import GameEngineRuntime
        self.runtime=GameEngineRuntime();self.addCleanup(self.runtime.shutdown)
        with self.runtime._lock:
            self.runtime._ensure_combat_actors_locked()
            self.runtime._vx[0]=self.runtime._vy[0]=self.runtime._vz[0]=0.

    def target(self):
        r=self.runtime
        with r._lock:
            index=r._npc_indices[0];target=r._npc_ids[index]
            r._x[0]=r._x[index]+1.;r._y[0]=r._y[index];r._z[0]=r._z[index]
            r._combat_target_id=target
        return target

    def advance(self,seconds):
        with self.runtime._lock:
            self.runtime._sim_time+=seconds
            self.runtime._tick_spells_locked(seconds)

    def ui(self):
        from backend.game_engine_adapter_ui import GgEngineUI
        from backend.game_engine_adapter_gameplay import GameplayViews
        ui=GgEngineUI();self.addCleanup(ui.close)
        ui.views=GameplayViews()
        ui.execute("EVENTS={};MIRRORS={};F=CreateFrame('Frame');for _,e in ipairs({'SPELLCAST_START','SPELLCAST_STOP','SPELLCAST_CHANNEL_START','SPELLCAST_CHANNEL_STOP','MIRROR_TIMER_START','MIRROR_TIMER_STOP'}) do F:RegisterEvent(e) end;F:SetScript('OnEvent',function() if event=='MIRROR_TIMER_START' then table.insert(MIRRORS,tostring(arg1)..'|'..tostring(arg2)..'|'..tostring(arg3)..'|'..tostring(arg4)..'|'..tostring(arg5)..'|'..tostring(arg6)) else table.insert(EVENTS,event..'|'..tostring(arg1)..'|'..tostring(arg2)) end end)")
        return ui

    def publish(self,ui,survival=None):
        snapshot=self.runtime.snapshot();player=snapshot['player'];actor=snapshot['combat_live']['player']
        if survival is not None:player['client_controls']['survival']=survival
        ui.publish(player,False,actor['health'],snapshot['combat_live']['resource'],
            client_controls=player['client_controls'],**ui.views.update(snapshot))

    def events(self,ui):return ui.evaluate("return table.concat(EVENTS,',')")[0]

    def test_active_form_cancellation_does_not_report_an_energy_deficit(self):
        r=self.runtime
        self.assertIsNone(r.activate_ability('ability.reef_guard').get('error'))
        self.assertIsNone(r.action_bar_edit(json.dumps(dict(index=23,kind='ABILITY',ref='ability.reef_guard'))).get('error'))
        r._resource=0.;snapshot=r.snapshot()
        rows=[snapshot['actions']['slots'][23],next(a for a in snapshot['actions']['abilities'] if a['ref']=='ability.reef_guard')]
        for row in rows:
            self.assertTrue(row['usable']);self.assertTrue(row['current'])
            self.assertFalse(row['not_enough_resource'],'A free active-form cancel must not show the resource deficit flag')
        ui=self.ui();self.publish(ui)
        self.assertEqual(ui.evaluate('return IsUsableAction(24)'),[1,None])
        self.assertEqual(ui.evaluate('return GetActionCooldown(24)'),[0,0,1])
        self.assertEqual(ui.evaluate('return GetShapeshiftFormCooldown(1)'),[0,0,1])
        self.assertEqual(r.activate_ability('ability.reef_guard')['ability_result']['status'],'FORM_CANCELLED')

    def test_fresh_vm_bootstraps_actual_cast_remaining_and_never_replays_start(self):
        self.target();r=self.runtime
        self.assertEqual(r.activate_ability('ability.island_spark')['ability_result']['status'],'CASTING')
        self.advance(.75);ui=self.ui();self.publish(ui)
        self.assertEqual(self.events(ui),'SPELLCAST_START|Island Spark|750')
        self.publish(ui);self.assertEqual(self.events(ui),'SPELLCAST_START|Island Spark|750')
        self.advance(.75);self.publish(ui)
        self.assertEqual(self.events(ui),'SPELLCAST_START|Island Spark|750,SPELLCAST_STOP|nil|nil')

    def test_fresh_vm_bootstraps_actual_channel_remaining(self):
        self.assertEqual(self.runtime.activate_ability('ability.tide_mend')['ability_result']['status'],'CHANNELING')
        self.advance(1.25);ui=self.ui();self.publish(ui)
        self.assertEqual(self.events(ui),'SPELLCAST_CHANNEL_START|1750|Tide Mend')
        self.publish(ui);self.assertEqual(self.events(ui),'SPELLCAST_CHANNEL_START|1750|Tide Mend')

    def test_same_vm_epoch_stops_old_timers_before_synthesizing_the_new_cast(self):
        ui=self.ui();self.publish(ui)
        self.runtime.activate_ability('ability.tide_mend');self.publish(ui)
        self.assertEqual(self.events(ui),'SPELLCAST_CHANNEL_START|3000|Tide Mend')
        with self.runtime._lock:self.runtime._reset_spells_locked()
        self.runtime._ability_cooldowns.clear()
        self.runtime.activate_ability('ability.tide_mend');ui.execute('EVENTS={}')
        self.publish(ui)
        self.assertEqual(self.events(ui),'SPELLCAST_STOP|nil|nil,SPELLCAST_CHANNEL_STOP|nil|nil,MIRROR_TIMER_STOP|BREATH|nil,MIRROR_TIMER_STOP|EXHAUSTION|nil,SPELLCAST_CHANNEL_START|3000|Tide Mend')

    def test_authoritative_spell_damage_emits_structured_audio_compatible_attack_once(self):
        target=self.target();r=self.runtime;before=r._combat_state['actors'][target]['health']
        r.activate_ability('ability.island_spark');self.advance(1.5)
        hits=[e for e in r.snapshot()['event_journal']['events'] if e['kind']=='COMBAT_ATTACK' and e['subject_id']=='ability.island_spark']
        self.assertEqual(len(hits),1);event=hits[0]
        self.assertEqual((event['actor_id'],event['target_id']),('player',target))
        self.assertEqual((event['payload']['kind'],event['payload']['attacker_id'],event['payload']['defender_id']),('SPELL','player',target))
        self.assertEqual(event['payload']['damage'],before-r._combat_state['actors'][target]['health'])
        self.advance(5.)
        self.assertEqual(len([e for e in r.snapshot()['event_journal']['events'] if e['kind']=='COMBAT_ATTACK' and e['subject_id']=='ability.island_spark']),1)

    def test_fresh_mirror_contract_bootstraps_drain_refill_and_epoch_retires_both_timers(self):
        ui=self.ui()
        timers=[dict(kind='BREATH',remaining_ms=18000,max_ms=60000,scale=-1,label='Breath'),
                dict(kind='EXHAUSTION',remaining_ms=42000,max_ms=60000,scale=10,label='Fatigue')]
        self.publish(ui,dict(mirror_timers=timers))
        self.assertEqual(ui.evaluate("return table.concat(MIRRORS,',')"),['BREATH|18000|60000|-1|0|Breath,EXHAUSTION|42000|60000|10|0|Fatigue'])
        self.publish(ui,dict(mirror_timers=timers))
        self.assertEqual(ui.evaluate('return table.getn(MIRRORS)'),[2])
        with self.runtime._lock:self.runtime._reset_spells_locked()
        ui.execute('EVENTS={};MIRRORS={}')
        self.publish(ui,dict(mirror_timers=[dict(kind='BREATH',remaining_ms=30000,max_ms=60000,scale=10,label='Breath')]))
        self.assertEqual(self.events(ui),'SPELLCAST_STOP|nil|nil,SPELLCAST_CHANNEL_STOP|nil|nil,MIRROR_TIMER_STOP|BREATH|nil,MIRROR_TIMER_STOP|EXHAUSTION|nil')
        self.assertEqual(ui.evaluate("return table.concat(MIRRORS,',')"),['BREATH|30000|60000|10|0|Breath'])

    def test_invalid_mirror_contracts_are_bounded_and_do_not_consume_the_fresh_event_cursor(self):
        ui=self.ui();timer=dict(kind='BREATH',remaining_ms=18000,max_ms=60000,scale=-1,label='Breath')
        invalid=[[timer,timer],[timer,timer,timer],[dict(timer,kind='OXYGEN')],
                 [dict(timer,scale=0)],[dict(timer,max_ms=0)],[dict(timer,remaining_ms=60001)],
                 [dict(timer,remaining_ms=True)]]
        for rows in invalid:
            with self.subTest(rows=rows),self.assertRaisesRegex(ValueError,'mirror timer'):
                self.publish(ui,dict(mirror_timers=rows))
        self.publish(ui,dict(mirror_timers=[timer]))
        self.assertEqual(ui.evaluate("return table.concat(MIRRORS,',')"),['BREATH|18000|60000|-1|0|Breath'])


if __name__=='__main__':unittest.main()
