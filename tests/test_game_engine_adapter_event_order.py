"""Original Lua callbacks must read the state of the committed action."""
import json
import unittest
import test_game_engine_adapter_services as services
from backend.game_engine_adapter_battlefields import MAP_ID


class EventOrder(unittest.TestCase):
    setUp=services.Services.setUp
    publish=services.Services.publish
    call=services.Services.call
    control=services.Services.control
    service=services.Services.service
    view=services.Services.view
    move_near_npc=services.Services.move_near_npc

    def test_original_party_callback_never_reads_the_old_roster_on_invite_or_leave(self):
        owner=self.move_near_npc();self.publish()
        name=self.runtime._service_unit_locked(owner)['name']
        self.ui.execute("ROSTER_EVENTS={};ROSTER_FRAME=CreateFrame('Frame');ROSTER_FRAME:RegisterEvent('PARTY_MEMBERS_CHANGED');ROSTER_FRAME:SetScript('OnEvent',function() table.insert(ROSTER_EVENTS,GetNumPartyMembers()) end)")
        self.call('InviteByName('+json.dumps(name)+')')
        counts=self.ui.evaluate("return table.concat(ROSTER_EVENTS,',')")[0].split(',')
        self.assertTrue(counts and all(n=='1' for n in counts),str(counts))
        self.ui.execute('ROSTER_EVENTS={}')
        self.call('LeaveParty()');counts=self.ui.evaluate("return table.concat(ROSTER_EVENTS,',')")[0].split(',')
        self.assertTrue(counts and all(n=='0' for n in counts),str(counts))

    def test_original_arena_callback_never_reads_no_queue_after_a_successful_join(self):
        self.assertIsNone(self.service('BattlefieldList',map=MAP_ID).get('error'));self.publish()
        self.ui.execute("QUEUE_EVENTS={};QUEUE_FRAME=CreateFrame('Frame');QUEUE_FRAME:RegisterEvent('UPDATE_BATTLEFIELD_STATUS');QUEUE_FRAME:SetScript('OnEvent',function() local status=GetBattlefieldStatus(1);table.insert(QUEUE_EVENTS,status) end)")
        self.call('JoinBattlefield(1,false)')
        states=self.ui.evaluate("return table.concat(QUEUE_EVENTS,',')")[0].split(',')
        self.assertTrue(states and all(s=='queued' for s in states),str(states))


if __name__=='__main__':unittest.main()
