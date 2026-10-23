"""Original reset/LFG APIs over owned places, actual encounters and item custody."""
import copy
import time
import unittest
from unittest.mock import patch
import test_game_engine_adapter_services as services
from backend import game_engine_combat as combat,game_engine_items as items


class InstanceSessions(unittest.TestCase):
    setUp=services.Services.setUp
    publish=services.Services.publish
    call=services.Services.call
    control=services.Services.control
    service=services.Services.service
    view=services.Services.view

    def entrance(self):
        place=next(r for r in self.runtime._expedition_places_locked().values() if r['kind']=='RUINS')
        x,z=place['x']+40.,place['z']
        self.runtime._lifecycle_move_locked(dict(x=x,y=self.runtime._ground_contact_height_locked(x,z),z=z))
        return place

    def test_pending_companion_search_cancels_when_another_real_party_forms_even_after_leadership_changes(self):
        place=self.entrance();owner='npc-guardian-01';index=self.runtime._instance_npc_index_locked(owner)
        self.runtime._x[index]=self.runtime._x[0]+1.;self.runtime._y[index]=self.runtime._y[0];self.runtime._z[index]=self.runtime._z[0]
        self.assertIsNone(self.service('MeetingStoneJoin',ref=place['id']).get('error'))
        self.assertIsNone(self.service('GroupInvite',target=owner).get('error'))
        self.assertIsNone(self.service('GroupLeader',target=owner).get('error'))
        group=copy.deepcopy(self.runtime._services['group'])
        self.runtime._tick_instance_sessions_locked();self.publish()
        self.assertIsNone(self.runtime._services['instance_sessions']['meeting'])
        self.assertEqual(self.runtime._services['group'],group)
        self.runtime.load_state();self.assertIsNone(self.runtime._services['instance_sessions']['meeting'])

    def enter(self):
        place=self.entrance();origin=self.runtime._lifecycle_position_locked()
        self.assertIsNone(self.service('InstanceEnter',ref=place['id']).get('error'))
        self.publish();self.assertEqual(self.ui.evaluate('return IsInInstance()'),[1,'party'])
        return place,origin

    def defeat(self):
        owner='npc-guardian-01';index=self.runtime._instance_npc_index_locked(owner)
        self.runtime._x[index]=self.runtime._x[0]+1.;self.runtime._y[index]=self.runtime._y[0];self.runtime._z[index]=self.runtime._z[0]
        actor=self.runtime._combat_state['actors'][owner];actor['health']=1.
        result=combat.resolve_attack(self.runtime._combat_state,attacker_id='player',defender_id=owner,
            attacker_profile=self.runtime._player_combat_profile_locked(),defender_profile=self.runtime._npc_combat_profile_locked(owner),sim_time=self.runtime._sim_time+10)
        self.assertTrue(result['defeated']);self.runtime._handle_npc_defeat_locked(owner,index,result)
        self.assertFalse(self.runtime._combat_state['actors']['player']['engaged_target'])
        self.runtime._tick_instance_sessions_locked();self.publish()
        self.assertEqual(self.runtime._expedition_record_locked()['defeated'],[owner])
        return owner

    def test_owned_session_original_getters_real_defeat_reset_and_no_acquired_item_loss(self):
        place,origin=self.enter();owner=self.defeat()
        record=self.runtime._expedition_record_locked();key=record['id']
        drops=[i for i in self.runtime._item_instances.values() if i.get('source_actor_id')==owner]
        self.assertTrue(drops)
        acquired=drops[0];self.runtime._move_item_locked(acquired,'INVENTORY',owner_id='player')
        self.publish();acquired_before=copy.deepcopy(self.runtime._item_instance_locked(acquired['instance_id']))
        self.assertTrue(acquired_before['loot_claimed'])
        unclaimed=items.make_instance(self.runtime._item_catalog,'unclaimed-expedition-drop','item.sea_salt',location='GROUND')
        unclaimed.update(source_actor_id=owner,loot_claimed=False);self.runtime._item_instances[unclaimed['instance_id']]=unclaimed
        self.call('ResetInstances()');self.assertEqual(self.runtime._services['instance_sessions']['active']['id'],key)
        self.assertFalse(self.runtime._combat_state['actors'][owner]['alive'])
        self.assertIsNone(self.service('InstanceExit').get('error'));self.publish()
        self.assertEqual(self.runtime._lifecycle_position_locked(),origin)
        self.assertEqual(self.ui.evaluate('return CanShowResetInstances(),GetNumSavedInstances()'),[1,1])
        self.call('ResetInstances();ResetInstances()')
        self.assertFalse(self.runtime._services['instance_sessions']['lockouts'])
        self.assertTrue(self.runtime._combat_state['actors'][owner]['alive'])
        self.assertEqual(self.runtime._item_instance_locked(acquired['instance_id']),acquired_before)
        self.assertEqual(self.runtime._item_instance_locked(unclaimed['instance_id'])['location'],'DESTROYED')
        self.assertEqual(self.ui.evaluate('return IsInInstance(),GetNumSavedInstances()'),[None,0])
        self.assertEqual(self.ui.request('requests')['unimplemented'],[])

    def test_failed_reset_save_rolls_back_dead_encounter_lockout_and_unclaimed_drop_then_retries(self):
        place,origin=self.enter();self.defeat();self.assertIsNone(self.service('InstanceExit').get('error'))
        before=copy.deepcopy((self.runtime._services['instance_sessions'],self.runtime._combat_state,self.runtime._item_instances))
        with patch.object(self.runtime,'save_state',side_effect=OSError('disk full')):
            self.assertEqual(self.service('InstanceReset')['error'],'SERVICE_SAVE_FAILED')
        self.assertEqual(before,(self.runtime._services['instance_sessions'],self.runtime._combat_state,self.runtime._item_instances))
        self.assertIsNone(self.service('InstanceReset').get('error'))

    def test_private_raid_lock_and_unowned_place_do_not_reset_other_sessions(self):
        place,origin=self.enter();self.service('InstanceExit')
        row=self.runtime._services['instance_sessions']['lockouts'][0]
        row['type']=2
        self.assertEqual(self.service('InstanceReset',ref=place['id'])['error'],'INSTANCE_RAID_LOCKED')
        row=self.runtime._services['instance_sessions']['lockouts'][0];row['type']=1
        self.runtime._x[0]=place['x'];self.runtime._z[0]=place['z']
        # The overworld shares authored geometry, but it cannot occupy an
        # isolated map merely because its player has the same coordinates.
        self.assertFalse(self.runtime._instance_occupied_locked(row))
        self.assertEqual(self.service('InstanceReset',ref='no-such-place')['error'],'INSTANCE_NOT_OWNED')
        self.assertEqual(len(self.runtime._services['instance_sessions']['lockouts']),1)
        self.assertIsNone(self.service('InstanceReset',ref=place['id']).get('error'))
        self.assertFalse(self.runtime._services['instance_sessions']['lockouts'])

    def test_real_lfg_offer_needs_accept_and_original_cancel_preserves_party_and_items(self):
        place=self.entrance();index=self.runtime._instance_npc_index_locked('npc-guardian-01')
        self.runtime._x[index]=self.runtime._x[0]+1.;self.runtime._z[index]=self.runtime._z[0];self.runtime._y[index]=self.runtime._y[0]
        before=copy.deepcopy((self.runtime._item_instances,self.runtime._inventory,self.runtime._economy_state))
        self.service('MeetingStoneJoin',ref=place['id']);self.publish()
        self.assertEqual(self.ui.evaluate('return IsInMeetingStoneQueue()'),[1])
        self.call('CancelMeetingStoneRequest()');self.assertFalse(self.runtime._services['group']['members'])
        self.assertEqual(self.ui.evaluate('return IsInMeetingStoneQueue()'),[None])
        self.assertEqual(before,(self.runtime._item_instances,self.runtime._inventory,self.runtime._economy_state))
        self.service('MeetingStoneJoin',ref=place['id'])
        self.runtime._services['instance_sessions']['meeting']['created_at']=time.time()-4.
        self.runtime._tick_instance_sessions_locked();self.publish()
        self.assertFalse(self.runtime._services['group']['members'])
        self.assertIn('ready',self.ui.evaluate('return GetMeetingStoneStatusText()')[0])
        self.assertIsNone(self.service('MeetingStoneAccept').get('error'))
        self.assertIn('npc-guardian-01',self.runtime._services['group']['members'])
        self.assertEqual(self.runtime._services['group']['leader'],'player')
        self.assertEqual(before,(self.runtime._item_instances,self.runtime._inventory,self.runtime._economy_state))

    def test_saved_session_lockout_and_claim_marker_restore_and_walked_exit_is_detected(self):
        place,origin=self.enter();self.defeat();key=self.runtime._services['instance_sessions']['active']['id']
        self.runtime.save_state();self.runtime.load_state();self.publish()
        self.assertEqual(self.runtime._services['instance_sessions']['active']['id'],key)
        self.assertEqual(self.ui.evaluate('return GetNumSavedInstances()'),[1])
        self.runtime._x[0]=place['x']+80.;self.runtime._tick_instance_sessions_locked();self.publish()
        self.assertIsNone(self.runtime._services['instance_sessions']['active'])
        self.assertEqual(self.ui.evaluate('return IsInInstance()'),[None,'none'])

    def test_absent_entrance_dead_player_and_reset_request_flood_preserve_the_registry(self):
        before=copy.deepcopy((self.runtime._item_instances,self.runtime._inventory))
        self.assertIn('error',self.service('InstanceEnter',ref='unknown'))
        self.assertEqual(self.service('InstanceReset',requests=17)['error'],'INSTANCE_REQUEST_CAPACITY')
        self.runtime._combat_state['actors']['player']['alive']=False
        self.assertEqual(self.service('InstanceEnter',ref=next(iter(self.runtime._expedition_places_locked())))['error'],'PLAYER_DEFEATED')
        self.assertEqual(before,(self.runtime._item_instances,self.runtime._inventory))

    def test_background_companion_offer_notifies_original_reader_once_without_polling(self):
        place=self.entrance();index=self.runtime._instance_npc_index_locked('npc-guardian-01')
        self.runtime._x[index]=self.runtime._x[0]+1.;self.runtime._y[index]=self.runtime._y[0];self.runtime._z[index]=self.runtime._z[0]
        self.service('MeetingStoneJoin',ref=place['id']);self.publish()
        self.ui.execute("MEETING_EVENTS={};MEETING_FRAME=CreateFrame('Frame');MEETING_FRAME:RegisterEvent('MEETINGSTONE_CHANGED');MEETING_FRAME:SetScript('OnEvent',function() table.insert(MEETING_EVENTS,GetMeetingStoneStatusText()) end)")
        self.runtime._services['instance_sessions']['meeting']['created_at']=time.time()-4.
        self.runtime._tick_instance_sessions_locked();self.publish()
        self.assertEqual(self.ui.evaluate('return table.getn(MEETING_EVENTS)'),[1])
        self.assertIn('ready',self.ui.evaluate('return MEETING_EVENTS[1]')[0])
        self.publish();self.publish();self.assertEqual(self.ui.evaluate('return table.getn(MEETING_EVENTS)'),[1])


if __name__=='__main__':unittest.main()
