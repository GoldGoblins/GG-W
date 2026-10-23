"""Local arena: original queue/score APIs, actual combat and saved bonus honor."""
import copy
import time
import unittest
from unittest.mock import patch
import test_game_engine_adapter_services as services
from backend.game_engine_adapter_battlefields import MAP_ID


class Battlefields(unittest.TestCase):
    publish=services.Services.publish
    call=services.Services.call
    control=services.Services.control
    service=services.Services.service
    view=services.Services.view
    setUp=services.Services.setUp

    def enter(self):
        self.assertIsNone(self.service('BattlefieldList',map=MAP_ID).get('error'))
        self.publish();self.call('JoinBattlefield(1,false)')
        queued=self.runtime._services['battlefields']['queue'][0]
        queued['ready_at']=time.time()-1
        self.runtime._tick_battlefields_locked();self.publish()
        self.assertEqual(self.ui.evaluate('return GetBattlefieldStatus(1)')[0],'confirm')
        self.call('AcceptBattlefieldPort(1,true)')
        active=self.runtime._services['battlefields']['active'];self.assertIsNotNone(active)
        return active,queued['id']

    def win(self,active):
        self.runtime._services['duel']['deadline']=time.time()-1
        self.runtime._tick_lifecycle_locked()
        self.runtime._combat_state['actors'][active['opponent']]['health']=2.
        result=self.runtime.attack(active['opponent'])
        self.assertIsNone(result.get('error'))
        self.runtime._tick_lifecycle_locked()

    def test_original_queue_port_real_nonlethal_combat_and_score_never_mint_items_or_player_kills(self):
        before=copy.deepcopy((self.runtime._item_instances,self.runtime._inventory,self.runtime._economy_state,self.runtime._progression))
        active,key=self.enter();self.assertEqual(self.ui.evaluate('return GetBattlefieldStatus(1)')[0],'active')
        self.assertEqual(self.ui.evaluate('return IsInInstance()'),[1,'pvp'])
        self.win(active);self.runtime._tick_battlefields_locked();self.publish()
        self.assertEqual(active['state'],'ENDED');self.assertEqual(active['winner'],1)
        self.assertTrue(self.runtime._combat_state['actors'][active['opponent']]['alive'])
        self.assertEqual(self.runtime._combat_state['actors'][active['opponent']]['health'],1.)
        self.assertEqual(self.ui.evaluate('return GetBattlefieldWinner(),GetNumBattlefieldScores()'),[1,2])
        self.assertEqual(self.ui.evaluate('return GetPVPThisWeekStats()'),[0,10])
        self.assertEqual(self.ui.evaluate('return GetPVPLifetimeStats()')[:2],[0,0])
        self.assertEqual(before,(self.runtime._item_instances,self.runtime._inventory,self.runtime._economy_state,self.runtime._progression))
        self.call('RequestBattlefieldScoreData();LeaveBattlefield();LeaveBattlefield()')
        self.assertIsNone(self.runtime._services['battlefields']['active'])
        self.assertEqual(self.ui.evaluate('return GetBattlefieldStatus(1)')[0],'none')
        self.assertEqual(self.ui.evaluate('return IsInInstance()'),[None,'none'])
        self.assertEqual(self.ui.request('requests')['unimplemented'],[])

    def test_pending_offer_decline_expiry_and_old_slot_cannot_accept_another_queue(self):
        self.service('BattlefieldList',map=MAP_ID);self.publish();self.call('JoinBattlefield(0,false)')
        queued=self.runtime._services['battlefields']['queue'][0];old=queued['id']
        queued['ready_at']=time.time()-1;self.runtime._tick_battlefields_locked();self.publish()
        self.call('AcceptBattlefieldPort(1,false)')
        self.assertFalse(self.runtime._services['battlefields']['queue'])
        self.call('JoinBattlefield(0,false)')
        current=self.runtime._services['battlefields']['queue'][0]
        self.assertNotEqual(current['id'],old)
        self.assertEqual(self.service('BattlefieldPort',slot=1,queue_id=old,accept=True)['error'],'BATTLEFIELD_QUEUE_CHANGED')
        current=self.runtime._services['battlefields']['queue'][0]
        current.update(status=2,deadline=time.time()-1);self.runtime._tick_battlefields_locked()
        self.assertFalse(self.runtime._services['battlefields']['queue']);self.assertIsNone(self.runtime._services['duel'])

    def test_failed_start_and_failed_reward_save_preserve_custody_queue_and_retry_one_bonus(self):
        self.service('BattlefieldList',map=MAP_ID);self.publish()
        before=copy.deepcopy(self.runtime._services['battlefields'])
        with patch.object(self.runtime,'save_state',side_effect=OSError('disk full')):
            self.assertEqual(self.service('BattlefieldJoin',map=MAP_ID,instance=1,as_group=False)['error'],'SERVICE_SAVE_FAILED')
        self.assertEqual(before,self.runtime._services['battlefields'])
        active,key=self.enter();session=self.view()['session'];self.win(active)
        ledger=copy.deepcopy(self.runtime._services['honor_ledger'])
        with patch.object(self.runtime,'save_state',side_effect=OSError('disk full')):
            self.assertEqual(self.control('service','BattlefieldFinish',session=session)['error'],'SERVICE_SAVE_FAILED')
        self.assertEqual(ledger,self.runtime._services['honor_ledger'])
        self.assertEqual(self.runtime._services['battlefields']['active']['state'],'ACTIVE')
        # An original UI intent carries its frozen displayed service session.
        # The convenience service() helper takes a fresh snapshot first, which
        # can correctly auto-settle a pending result before this retry arrives.
        self.assertIsNone(self.control('service','BattlefieldFinish',session=session).get('error'))
        self.assertEqual(self.service('BattlefieldFinish')['error'],'BATTLEFIELD_RESULT_REQUIRED')
        self.publish();self.assertEqual(self.ui.evaluate('return GetPVPThisWeekStats()'),[0,10])
        self.runtime.load_state();self.publish()
        self.assertIsNone(self.runtime._services['battlefields']['active'])
        self.assertEqual(self.ui.evaluate('return GetPVPThisWeekStats()'),[0,10])

    def test_failed_reward_retries_from_due_actual_snapshot_settlement_and_awards_one_bonus(self):
        active,key=self.enter();session=self.view()['session'];self.win(active)
        ledger=copy.deepcopy(self.runtime._services['honor_ledger'])
        with patch.object(self.runtime,'save_state',side_effect=OSError('disk full')):
            self.assertEqual(self.control('service','BattlefieldFinish',session=session)['error'],'SERVICE_SAVE_FAILED')
        self.assertEqual(self.runtime._services['honor_ledger'],ledger)
        self.assertEqual(self.runtime._services['battlefields']['active']['state'],'ACTIVE')
        # The ordinary authoritative snapshot services a due real settlement.
        # No invented result or successful Finish command is supplied here.
        self.runtime._service_next_tick=0.
        self.runtime.snapshot()
        self.assertEqual(self.runtime._services['battlefields']['active']['state'],'ENDED')
        settled=copy.deepcopy(self.runtime._services['honor_ledger'])
        self.publish();self.publish()
        self.assertEqual(self.ui.evaluate('return GetPVPThisWeekStats()'),[0,10])
        self.assertEqual(self.runtime._services['honor_ledger'],settled)
        self.assertEqual(self.control('service','BattlefieldFinish',session=session)['error'],'BATTLEFIELD_RESULT_REQUIRED')
        self.runtime.load_state();self.publish()
        self.assertEqual(self.ui.evaluate('return GetPVPThisWeekStats()'),[0,10])

    def test_login_cancels_unfinished_match_and_never_awards_saved_pending_combat(self):
        active,key=self.enter();owner=active['opponent'];origin=copy.deepcopy(active['opponent_origin'])
        self.runtime.save_state();self.runtime.load_state();self.publish()
        self.assertIsNone(self.runtime._services['battlefields']['active']);self.assertFalse(self.runtime._services['battlefields']['queue'])
        self.assertIsNone(self.runtime._services['duel']);self.assertEqual(self.ui.evaluate('return GetPVPThisWeekStats()'),[0,0])
        index=self.runtime._npc_index_for_id_locked(owner)
        self.assertEqual({axis:getattr(self.runtime,'_'+axis)[index] for axis in ('x','y','z')},origin)
        self.assertEqual([getattr(self.runtime,'_'+axis)[index] for axis in ('vx','vy','vz')],[0.,0.,0.])
        self.assertEqual(self.runtime._combat_state['actors'][owner]['engaged_target'],'')

    def test_no_player_kill_or_bonus_for_forfeit_and_no_dead_taxi_or_unled_group_join(self):
        self.runtime._combat_state['actors']['player']['alive']=False
        self.assertEqual(self.service('BattlefieldJoin',map=MAP_ID)['error'],'PLAYER_DEFEATED')
        self.runtime._combat_state['actors']['player']['alive']=True
        self.assertEqual(self.service('BattlefieldJoin',map=MAP_ID,as_group=True)['error'],'BATTLEFIELD_GROUP_LEADER_REQUIRED')
        active,key=self.enter();self.call('CancelDuel()');self.runtime._tick_battlefields_locked();self.publish()
        self.assertEqual(self.ui.evaluate('return GetPVPThisWeekStats()'),[0,0])
        self.assertEqual(self.ui.evaluate('return GetBattlefieldWinner()'),[0])

    def test_unknown_map_and_premature_result_fail_without_ledger_changes(self):
        before=copy.deepcopy(self.runtime._services['honor_ledger'])
        self.assertEqual(self.service('BattlefieldList',map=489)['error'],'BATTLEFIELD_MAP_NOT_LOCAL')
        self.assertEqual(self.service('BattlefieldFinish')['error'],'BATTLEFIELD_RESULT_REQUIRED')
        self.assertEqual(before,self.runtime._services['honor_ledger'])

    def test_background_offer_updates_original_listener_readers_without_polling_or_countdown_event_storm(self):
        self.service('BattlefieldList',map=MAP_ID);self.publish();self.call('JoinBattlefield(1,false)')
        self.ui.execute("STATUS_EVENTS={};STATUS_FRAME=CreateFrame('Frame');STATUS_FRAME:RegisterEvent('UPDATE_BATTLEFIELD_STATUS');STATUS_FRAME:SetScript('OnEvent',function() local status=GetBattlefieldStatus(arg1);table.insert(STATUS_EVENTS,status) end)")
        queued=self.runtime._services['battlefields']['queue'][0];queued['ready_at']=time.time()-1
        self.runtime._tick_battlefields_locked();self.publish()
        self.assertEqual(self.ui.evaluate('return STATUS_EVENTS[1],table.getn(STATUS_EVENTS)'),['confirm',1])
        self.publish();self.publish()
        self.assertEqual(self.ui.evaluate('return table.getn(STATUS_EVENTS)'),[1])

    def test_original_inspect_honor_uses_same_nearby_party_owner_then_clears_on_move_away(self):
        active,key=self.enter();opponent=active['opponent'];self.win(active)
        self.runtime._tick_battlefields_locked();self.service('BattlefieldLeave')
        index=self.runtime._npc_index_for_id_locked(opponent)
        self.runtime._x[0]=self.runtime._x[index]+1.;self.runtime._y[0]=self.runtime._y[index];self.runtime._z[0]=self.runtime._z[index]
        self.service('GroupInvite',target=opponent)
        self.assertIsNone(self.service('Inspect',unit=opponent).get('error'));self.publish()
        self.ui.execute("HONOR_EVENTS=0;HONOR_FRAME=CreateFrame('Frame');HONOR_FRAME:RegisterEvent('INSPECT_HONOR_UPDATE');HONOR_FRAME:SetScript('OnEvent',function() HONOR_EVENTS=HONOR_EVENTS+1 end)")
        self.call('RequestInspectHonorData()')
        self.assertEqual(self.ui.evaluate('return HasInspectHonorData(),HONOR_EVENTS'),[1,1])
        self.assertEqual(self.ui.evaluate('return GetInspectHonorData()')[4:6],[0,0])
        self.runtime._x[0]+=100.;self.publish()
        self.assertEqual(self.ui.evaluate('return HasInspectHonorData()'),[None])

    def test_consented_party_opponent_keeps_membership_and_friendly_fire_block_returns_after_match(self):
        owner=self.runtime._battlefield_opponent_locked();index=self.runtime._npc_index_for_id_locked(owner)
        self.runtime._x[0]=self.runtime._x[index]+1.;self.runtime._y[0]=self.runtime._y[index];self.runtime._z[0]=self.runtime._z[index]
        self.assertIsNone(self.service('GroupInvite',target=owner).get('error'))
        group=copy.deepcopy(self.runtime._services['group'])
        self.assertEqual(self.runtime.attack(owner)['error'],'COMBAT_FRIENDLY_GROUP_TARGET')
        active,key=self.enter();self.assertEqual(active['opponent'],owner)
        self.assertTrue(next(r for r in self.runtime._target_rows_locked() if r['id']==owner)['can_attack'])
        self.win(active);self.runtime._tick_battlefields_locked();self.service('BattlefieldLeave');self.publish()
        self.assertEqual(self.runtime._services['group'],group)
        self.assertEqual(self.runtime.attack(owner)['error'],'COMBAT_FRIENDLY_GROUP_TARGET')


if __name__=='__main__':unittest.main()
