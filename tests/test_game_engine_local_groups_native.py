"""Actual original Lua/native getters over durable local-character groups."""
import json
import unittest
from unittest.mock import patch

import test_game_engine_local_custody_services as fixture
import test_game_engine_local_groups_loot as loot_fixture
from backend.game_engine_adapter_gameplay import GameplayViews
from backend.game_engine_adapter_ui import GgEngineUI


class NativeLocalGroups(unittest.TestCase):
    bind=fixture.SharedServices.bind
    switch=fixture.SharedServices.switch
    view=fixture.SharedServices.view
    actual_source=loot_fixture.SavedGroupLoot.actual_source
    opened=loot_fixture.SavedGroupLoot.opened

    def setUp(self):
        fixture.SharedServices.setUp(self)
        self.ui=GgEngineUI(clock=100);self.addCleanup(self.ui.close)
        self.gameplay=GameplayViews();self.publish()

    def publish(self):
        snapshot=self.runtime.snapshot();data=self.gameplay.update(snapshot)
        self.ui.publish(snapshot['player'],False,100,100,name=self.runtime._local_character_name,**data)
        return snapshot

    def call(self,source):
        self.ui.execute(source);requests=self.ui.request('requests')
        for request in requests.get('services',[]):
            row=self.gameplay.services.route(request,self.gameplay.inventory_refs,self.gameplay.equipment_refs)
            result=self.runtime.client_control(json.dumps(row));self.assertNotIn('error',result,result)
        for request in requests.get('local_client',[]):
            result=self.runtime.client_control(json.dumps(dict(request,kind='local')));self.assertNotIn('error',result,result)
        for slot,candidate in requests.get('loot_master_gives',[]):
            frozen=self.gameplay.local.master_loot(slot,candidate)
            result=self.runtime.client_control(frozen['args'][0])
            self.assertIsNone(result.get('error'),result.get('error'))
        self.publish()
        return requests

    def join(self):
        self.call('InviteByName("Second Hero")')
        self.assertEqual(self.ui.evaluate('return GetNumPartyMembers()'),[0])
        self.switch(self.second);self.publish()
        offer=next(e for e in self.view()['shared_pending_events'] if e['event']=='PARTY_INVITE_REQUEST')
        self.assertEqual(offer['args'],[self.session.rows[0]['name']])
        self.call('AcceptGroup()')

    def test_original_invite_accept_and_offline_roster_getters_preserve_actual_identity(self):
        self.join();other=self.view()['group']['roster'][1]
        self.assertEqual(self.ui.evaluate('return GetNumPartyMembers(),UnitName("party1"),UnitInParty("party1"),UnitExists("party1")'),[1,other['name'],1,1])
        self.assertEqual(self.ui.evaluate('return UnitIsConnected("party1"),UnitIsVisible("party1"),UnitIsDead("party1"),UnitClass("party1")'),[None,None,None,other['class_name'],other['class_file']])
        self.assertEqual(self.runtime._services['group']['members'],[])

    def test_original_raid_ranks_unknown_offline_zone_and_leader_alone_in_subgroup(self):
        self.join();self.switch(self.first);self.publish()
        self.call('ConvertToRaid() PromoteToAssistant("Second Hero") SetRaidSubgroup(2,2)')
        self.assertEqual(self.ui.evaluate('return GetNumRaidMembers(),GetNumPartyMembers(),IsPartyLeader(),IsRaidLeader()'),[2,0,1,1])
        row=self.ui.evaluate('return GetRaidRosterInfo(2)')
        profile=self.view()['group']['roster'][1]
        self.assertEqual(row[:7],[profile['name'],1,2,profile['level'],profile['class_name'],profile['class_file'],None])
        self.assertEqual(row[7:],[None,None])
        self.assertEqual(self.ui.evaluate('return UnitInRaid("raid2"),UnitIsConnected("raid2"),UnitIsDead("raid2")'),[1,None,None])
        self.call('PromoteToPartyLeader("raid2")');self.switch(self.second);self.publish()
        self.assertEqual(self.ui.evaluate('return IsRaidLeader()'),[1])

    def test_original_party_raid_and_addon_sends_reach_actual_other_profile_before_ack(self):
        self.join()
        self.call('SendChatMessage("Party delivery","PARTY") SendAddonMessage("LOOT_OPENED","","PARTY")')
        self.switch(self.first);self.publish()
        pending=self.view()['shared_pending_events']
        message=next(e for e in pending if e['event']=='CHAT_MSG_PARTY')
        addon=next(e for e in pending if e['event']=='CHAT_MSG_ADDON')
        self.ui.execute('local f=CreateFrame("Frame");f:RegisterEvent("CHAT_MSG_PARTY");f:RegisterEvent("CHAT_MSG_ADDON"); f:SetScript("OnEvent",function() GG_RECEIVED=GG_RECEIVED or {}; table.insert(GG_RECEIVED,{event,arg1,arg2,arg3,arg4}) end)')
        for event in (message,addon):self.ui.event(event['event'],*event['args'])
        self.assertEqual(self.ui.evaluate('return GG_RECEIVED[1][1],GG_RECEIVED[1][2],GG_RECEIVED[1][3],GG_RECEIVED[2][1],GG_RECEIVED[2][2],GG_RECEIVED[2][3],GG_RECEIVED[2][4]'),
            ['CHAT_MSG_PARTY','Party delivery','Second Hero','CHAT_MSG_ADDON','LOOT_OPENED','','PARTY'])
        result=self.runtime.client_control(json.dumps(dict(kind='local',op='SharedChatAck',ids=[message['ack_id'],addon['ack_id']])))
        self.assertNotIn('error',result);self.assertFalse(any(e.get('ack_id') for e in self.view()['shared_pending_events']))

    def test_persisted_ready_deadline_restores_remaining_time_in_fresh_vm_and_resets_after_finish(self):
        moment=2_000_000_000.
        self.join();self.switch(self.first);self.publish();self.call('ConvertToRaid()')
        with patch('time.time',return_value=moment):self.call('DoReadyCheck()')
        # Explicit received answers are absent; offline people are not inferred ready.
        self.assertEqual(self.view()['group']['ready'],{'player':True})
        self.assertFalse(any(r['op']=='GroupReadyLine' for r in self.ui.request('requests')['services']))
        self.ui.close();self.ui=GgEngineUI(clock=500);self.addCleanup(self.ui.close)
        with patch('time.time',return_value=moment+21):self.publish()
        self.ui.request('clock',seconds=508);self.ui.execute('CheckReadyCheckTime()')
        self.assertFalse(any(r['op']=='GroupReadyLine' for r in self.ui.request('requests')['services']))
        self.ui.request('clock',seconds=510);self.ui.execute('CheckReadyCheckTime()')
        self.assertTrue(any(r['op']=='GroupReadyLine' for r in self.ui.request('requests')['services']))
        self.runtime._local_custody_store.settle(self.first,100,now=moment+31)
        self.runtime._local_custody_cache=None
        with patch('time.time',return_value=moment+31):self.publish()
        self.ui.request('clock',seconds=1000);self.ui.execute('CheckReadyCheckTime()')
        self.assertFalse(any(r['op']=='GroupReadyLine' for r in self.ui.request('requests')['services']))

    def test_original_all_loot_method_threshold_master_settings_survive_actual_character_switch(self):
        self.join();self.switch(self.first);self.publish()
        for index,method in enumerate(('freeforall','roundrobin','master','group','needbeforegreed')):
            threshold=2+index%3
            with self.subTest(method=method):
                self.call('SetLootMethod("'+method+'","Second Hero",'+str(threshold)+')')
                self.assertEqual(self.ui.evaluate('return (GetLootMethod()),GetLootThreshold()'),[method,threshold])
        self.call('SetLootMethod("master","Second Hero",4)')
        self.call('SetLootThreshold(3)')
        self.assertEqual(self.ui.evaluate('return GetLootThreshold()'),[3])
        self.call('SetLootThreshold(4)')
        self.assertEqual(self.ui.evaluate('local method,master=GetLootMethod();return method,master,GetLootThreshold()'),['master',1,4])
        self.switch(self.second);self.publish()
        self.assertEqual(self.ui.evaluate('local method,master=GetLootMethod();return method,master,GetLootThreshold()'),['master',0,4])
        self.switch(self.first);self.publish()
        self.assertEqual(self.ui.evaluate('local method,master=GetLootMethod();return method,master,GetLootThreshold()'),['master',1,4])
        self.assertEqual(self.runtime._services['group']['members'],[])
        self.assertNotIn(self.second,self.runtime._combat_state.get('actors',{}))

    def test_original_one_present_roll_bop_requires_real_confirmation_then_awards_once(self):
        self.join();self.switch(self.first);self.publish();self.call('SetLootMethod("group")')
        source,item,session=self.opened(bonding=1)
        picked=self.runtime.loot_slot(session,source['instance_id'],item['instance_id'])
        self.assertIsNone(picked.get('error'),picked.get('error'));self.publish()
        roll=self.runtime._services['loot_rolls'][0];key=roll['id']
        self.assertEqual(roll['eligible'],['player']);self.assertEqual(roll['votes'],{})
        self.assertGreater(self.ui.evaluate('return GetLootRollTimeLeft('+str(key)+')')[0],0)
        self.assertEqual(self.ui.evaluate('local _,_,_,_,bound=GetLootRollItemInfo('+str(key)+');return bound'),[1])
        self.call('RollOnLoot('+str(key)+',1)')
        self.assertEqual(roll['votes'],{});self.assertEqual(roll['confirmation']['vote'],1)
        self.assertEqual(self.runtime._item_instances[item['instance_id']]['location'],'CONTAINER')
        self.call('ConfirmLootRoll('+str(key)+',1)')
        self.assertEqual(self.runtime._item_instances[item['instance_id']]['bound_to'],self.first)
        self.assertEqual(self.runtime._item_instances[item['instance_id']]['owner_id'],'player')
        self.assertFalse(self.runtime._services['loot_rolls'])
        before=self.runtime._local_custody_store.snapshot()['characters']
        self.call('ConfirmLootRoll('+str(key)+',1)')
        self.assertEqual(self.runtime._local_custody_store.snapshot()['characters'],before)

    def test_original_master_candidate_subgroup_holes_are_only_actual_self_and_offline_master_cannot_proxy(self):
        self.join();self.switch(self.first);self.publish()
        self.call('ConvertToRaid() SetRaidSubgroup(1,3) SetLootMethod("master","'+self.runtime._local_character_name+'")')
        source,item,session=self.opened();self.publish()
        self.assertEqual(self.ui.evaluate('return GetMasterLootCandidate(11)'),[self.runtime._local_character_name])
        self.assertEqual(self.ui.evaluate('return GetMasterLootCandidate(1),GetMasterLootCandidate(12),GetMasterLootCandidate(40)'),[None,None,None])
        slot=list(self.runtime._engine_loot['ids']).index(item['instance_id'])+1
        self.call('GiveMasterLoot('+str(slot)+',11)')
        self.assertEqual(self.runtime._item_instances[item['instance_id']]['location'],'INVENTORY')
        self.call('SetLootMethod("master","Second Hero")')
        source,item,session=self.opened();self.publish()
        slot=list(self.runtime._engine_loot['ids']).index(item['instance_id'])+1
        before=self.runtime._local_custody_store.snapshot()['characters']
        self.ui.execute('GiveMasterLoot('+str(slot)+',11)')
        pair=self.ui.request('requests')['loot_master_gives'][0]
        frozen=self.gameplay.local.master_loot(*pair)
        denied=self.runtime.client_control(frozen['args'][0])
        self.assertEqual(denied.get('error'),'LOOT_MASTER_NOT_PRESENT')
        self.assertEqual(self.runtime._local_custody_store.snapshot()['characters'],before)
        self.assertEqual(self.runtime._item_instances[item['instance_id']]['location'],'CONTAINER')
        self.assertFalse(self.runtime._services['loot_rolls'])


if __name__=='__main__':unittest.main()
