"""Lifecycle verification through the original VM and real saved world."""
import copy
import json
import time
import unittest
from unittest.mock import patch
import test_game_engine_adapter_services as service_tests
from backend import game_engine_combat as combat


class Lifecycle(unittest.TestCase):
    setUp=service_tests.Services.setUp
    publish=service_tests.Services.publish
    call=service_tests.Services.call
    control=service_tests.Services.control
    view=service_tests.Services.view
    service=service_tests.Services.service
    move_near_npc=service_tests.Services.move_near_npc

    def die(self):
        with self.runtime._lock:
            self.runtime._ensure_combat_actors_locked()
            self.runtime._combat_state['actors']['player'].update(alive=False,health=0,respawn_at=self.runtime._sim_time+8)
        result=self.service('DeathEnter');self.assertNotIn('error',result);self.publish()

    def test_original_release_delay_nearby_reclaim_and_fresh_load(self):
        self.move_near_npc();self.die();corpse=copy.deepcopy(self.runtime._services['death']['position'])
        self.assertEqual(self.ui.evaluate('return UnitIsDead("player"),UnitIsGhost("player")'),[1,None])
        with self.runtime._lock:
            self.runtime._sim_time+=20;self.runtime._tick=3;self.runtime._tick_combat_locked()
        self.assertFalse(self.runtime._combat_state['actors']['player']['alive'])
        self.call('RepopMe()');self.assertTrue(self.runtime._services['death']['ghost'])
        self.assertEqual(self.ui.evaluate('return UnitIsGhost("player")'),[1])
        self.assertEqual(self.service('DeathRetrieveCorpse')['error'],'CORPSE_RECOVERY_DELAY')
        self.runtime.load_state();self.publish();self.assertTrue(self.runtime._services['death']['ghost'])
        self.runtime._services['death']['recover_at']=time.time()-1
        with self.runtime._lock:self.runtime._lifecycle_move_locked(dict(corpse,x=corpse['x']+100))
        self.assertEqual(self.service('DeathRetrieveCorpse')['error'],'CORPSE_OUT_OF_REACH')
        with self.runtime._lock:self.runtime._lifecycle_move_locked(corpse)
        self.call('RetrieveCorpse()');self.assertIsNone(self.runtime._services['death'])
        actor=self.runtime._combat_state['actors']['player'];self.assertTrue(actor['alive']);self.assertAlmostEqual(actor['health'],actor['max_health']*.5)
        after=copy.deepcopy(actor);self.call('RetrieveCorpse()');self.assertEqual(after,self.runtime._combat_state['actors']['player'])

    def test_failed_release_restores_position_and_corpse_and_blocks_self_res_without_item(self):
        self.move_near_npc();self.die();before=copy.deepcopy((self.runtime._services,self.runtime._x,self.runtime._y,self.runtime._z))
        with patch.object(self.runtime._state_store,'save',side_effect=OSError('disk full')):
            self.assertEqual(self.service('DeathRepop')['error'],'SERVICE_SAVE_FAILED')
        current=copy.deepcopy(self.runtime._services);current['clock']=before[0]['clock']
        self.assertEqual(before,(current,self.runtime._x,self.runtime._y,self.runtime._z))
        self.assertEqual(self.service('DeathUseSoulstone')['error'],'SELF_RESURRECT_ITEM_REQUIRED')
        self.assertFalse(self.runtime._combat_state['actors']['player']['alive'])

    def test_corpse_is_fixed_render_row_and_ghost_cannot_modify_items_or_fly(self):
        import math
        self.move_near_npc();self.runtime._yaw[0]=math.radians(45);self.die();self.call('RepopMe()')
        death=self.runtime._services['death'];position=copy.deepcopy(death['position'])
        rendered=self.runtime.render_snapshot()['render']['entities']
        corpse=[r for r in rendered if r['id']=='corpse-player'];self.assertEqual(len(corpse),1)
        self.assertEqual({k:corpse[0][k] for k in position},position);self.assertEqual(corpse[0]['animation']['action'],'Death')
        self.assertAlmostEqual(corpse[0]['yaw'],45.)
        self.assertNotIn('corpse-player',self.runtime._item_instances)
        before=copy.deepcopy((self.runtime._inventory,self.runtime._item_instances))
        for action,args in ((self.runtime.pickup_item,()),(self.runtime.equip_item,()),(self.runtime.drop_item,()),
                            (self.runtime.open_container,()),(self.runtime.loot_container,()),(self.runtime.unequip_item,('unknown',)),
                            (self.runtime.move_inventory_slot,('unknown',0)),(self.runtime.transfer_inventory_stack,('unknown',0,1))):
            self.assertEqual(action(*args)['error'],'PLAYER_DEFEATED')
        self.assertFalse(self.runtime._stash_access_locked());self.assertEqual(self.runtime.set_movement_mode('FLY')['error'],'PLAYER_DEFEATED')
        self.runtime.set_input(json.dumps(dict(movement_mode='FLY',forward=1.,boost=True,grapple=True)))
        self.assertEqual(self.runtime._movement_mode,'GROUND');input=self.runtime._client_tick_input_locked(self.runtime._input)
        self.assertEqual(input['forward'],1.);self.assertFalse(input['boost']);self.assertFalse(input['grapple'])
        self.assertEqual(before,(self.runtime._inventory,self.runtime._item_instances))
        with self.runtime._lock:
            self.runtime._lifecycle_move_locked(position);death['recover_at']=time.time()-1
        self.service('DeathRetrieveCorpse');self.assertFalse(any(r['id']=='corpse-player' for r in self.runtime.render_snapshot()['render']['entities']))

    def test_saved_duel_does_not_resume_without_new_consent(self):
        identity=self.move_near_npc();self.call('StartDuelUnit("'+identity+'")')
        self.runtime._services['duel']['deadline']=time.time()-1
        with self.runtime._lock:
            self.runtime._tick_lifecycle_locked()
            self.runtime._combat_state['actors']['player']['engaged_target']=identity
            self.runtime._combat_state['actors'][identity]['engaged_target']='player'
        self.runtime.save_state();self.runtime.load_state()
        self.assertIsNone(self.runtime._services['duel']);self.assertNotIn('duel',self.runtime._combat_state)
        self.assertFalse(self.runtime._combat_state['actors']['player']['engaged_target']);self.assertFalse(self.runtime._combat_state['actors'][identity]['engaged_target'])

    def test_original_binder_range_gate_and_bound_release(self):
        identity=self.move_near_npc();self.service('BinderOpen',target=identity);self.publish()
        self.assertEqual(self.ui.evaluate('return CheckBinderDist()'),[True])
        with self.runtime._lock:self.runtime._x[0]+=100
        self.assertEqual(self.service('BinderConfirm')['error'],'BINDER_OUT_OF_REACH')
        self.move_near_npc();self.call('ConfirmBinder()');bound=copy.deepcopy(self.runtime._services['bind']['position'])
        self.runtime.load_state();self.assertEqual(bound,self.runtime._services['bind']['position'])
        self.die();self.call('RepopMe()');self.assertEqual(bound,self.runtime._lifecycle_position_locked())

    def test_spirit_healer_applies_real_durability_and_sickness_without_changing_xp(self):
        identity=self.move_near_npc();self.runtime._progression['level']=20;self.die();self.call('RepopMe()');self.move_near_npc()
        self.service('DeathHealerOpen',target=identity);self.publish();self.assertEqual(self.ui.evaluate('return CheckSpiritHealerDist(),GetResSicknessDuration()'),[True,'10'])
        gear=next(i for i in self.runtime._item_instances.values() if i.get('owner_id')=='player' and i.get('kind')=='WEAPON')
        condition=gear['condition'];xp=self.runtime._progression['xp'];profile=self.runtime._player_combat_profile_locked()
        self.call('AcceptXPLoss()');self.assertTrue(self.runtime._combat_state['actors']['player']['alive'])
        self.assertEqual(xp,self.runtime._progression['xp']);self.assertAlmostEqual(self.runtime._item_instance_locked(gear['instance_id'])['condition'],max(0.,condition-.25))
        self.assertAlmostEqual(self.runtime._player_combat_profile_locked()['damage'],max(1.,profile['damage']*.25))

    def test_original_duel_countdown_nonlethal_and_no_rewards_or_item_changes(self):
        identity=self.move_near_npc();self.call('StartDuelUnit("'+identity+'")')
        self.assertEqual(self.runtime._services['duel']['state'],'COUNTDOWN')
        with self.runtime._lock:
            profile=self.runtime._player_combat_profile_locked();other=self.runtime._npc_combat_profile_locked(identity,self.runtime._individual_state['individuals'][identity])
            result=combat.resolve_attack(self.runtime._combat_state,attacker_id='player',defender_id=identity,attacker_profile=profile,defender_profile=other,sim_time=self.runtime._sim_time)
            self.assertEqual(result['status'],'DUEL_COUNTDOWN')
            self.runtime._services['duel']['deadline']=time.time()-1;self.runtime._tick_lifecycle_locked()
            self.runtime._combat_state['actors'][identity]['health']=2
            before=copy.deepcopy((self.runtime._inventory,self.runtime._item_instances,self.runtime._progression))
            result=combat.resolve_attack(self.runtime._combat_state,attacker_id='player',defender_id=identity,attacker_profile=profile,defender_profile=other,sim_time=self.runtime._sim_time+10)
            self.assertTrue(result['ok']);self.assertFalse(result['defeated']);self.assertEqual(self.runtime._combat_state['actors'][identity]['health'],1)
            self.runtime._tick_lifecycle_locked()
        self.assertIsNone(self.runtime._services['duel']);self.assertTrue(self.runtime._combat_state['actors'][identity]['alive'])
        self.assertEqual(before,(self.runtime._inventory,self.runtime._item_instances,self.runtime._progression))
        self.call('CancelDuel()');self.assertIsNone(self.runtime._services['duel'])

    def test_original_incoming_duel_decline_accept_and_out_of_bounds(self):
        identity=self.move_near_npc();self.service('DuelRequest',target=identity);self.call('CancelDuel()');self.assertIsNone(self.runtime._services['duel'])
        self.service('DuelRequest',target=identity);self.call('AcceptDuel()');self.assertEqual(self.runtime._services['duel']['state'],'COUNTDOWN')
        self.runtime._services['duel']['deadline']=time.time()-1
        with self.runtime._lock:
            self.runtime._tick_lifecycle_locked();self.runtime._x[0]+=100;self.runtime._tick_lifecycle_locked()
            self.runtime._services['duel']['bounds_at']=time.time()-1;self.runtime._tick_lifecycle_locked()
        self.assertIsNone(self.runtime._services['duel']);self.assertNotIn('duel',self.runtime._combat_state)

if __name__=='__main__':unittest.main()
