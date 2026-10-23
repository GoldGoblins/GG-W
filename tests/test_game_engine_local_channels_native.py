"""Actual original Lua channel verbs/getters and durable before-ACK events."""
import json
import unittest

import test_game_engine_local_custody_services as fixture
from backend.game_engine_adapter_gameplay import GameplayViews
from backend.game_engine_adapter_ui import GgEngineUI


class NativeLocalChannels(unittest.TestCase):
    bind = fixture.SharedServices.bind
    switch = fixture.SharedServices.switch
    view = fixture.SharedServices.view

    def setUp(self):
        fixture.SharedServices.setUp(self)
        self.ui = GgEngineUI(clock=100); self.addCleanup(self.ui.close)
        self.gameplay = GameplayViews(); self.publish()

    def publish(self):
        snapshot = self.runtime.snapshot(); data = self.gameplay.update(snapshot)
        self.ui.publish(snapshot['player'], False, 100, 100, name=self.runtime._local_character_name, **data)
        return snapshot

    def call(self, source):
        self.ui.execute(source); requests = self.ui.request('requests')
        for request in requests.get('services', []):
            row = self.gameplay.services.route(request, self.gameplay.inventory_refs, self.gameplay.equipment_refs)
            result = self.runtime.client_control(json.dumps(row))
            self.assertIsNone(result.get('error'), result.get('error'))
        for request in requests.get('local_client', []):
            self.gameplay.services.freeze_channel(request)
            result = self.runtime.client_control(json.dumps(dict(request, kind='local')))
            self.assertIsNone(result.get('error'), result.get('error'))
        self.publish()
        return requests

    def join(self):
        self.call('JoinChannelByName("SavedBuilders","native channel pass")')
        self.call('ChannelInvite("SavedBuilders","Second Hero")')
        self.switch(self.second); self.publish()
        self.assertEqual(self.ui.evaluate('return GetChannelList()'), [])
        invitation = next(e for e in self.view()['shared_pending_events'] if e['event'] == 'CHAT_MSG_CHANNEL_NOTICE')
        self.assertEqual(invitation['args'][0], 'INVITE')
        self.assertEqual(self.runtime._services['channels'], [])
        self.call('JoinChannelByName("SavedBuilders","native channel pass")')

    def room(self):
        return next(r for r in self.view()['channels']['rows'] if r.get('shared_channel'))

    def test_original_join_invite_actual_accept_message_recipient_lua_ack_leave_and_reload(self):
        self.join()
        self.assertEqual(self.ui.evaluate('return GetChannelList()'), [1, 'SavedBuilders'])
        self.assertEqual(self.ui.evaluate('return (GetChannelName("SavedBuilders"))'), [1])
        self.call('SendChatMessage("Original channel delivery","CHANNEL",nil,"1")')
        self.switch(self.first); self.publish()
        message = next(e for e in self.view()['shared_pending_events'] if e['event'] == 'CHAT_MSG_CHANNEL')
        self.ui.execute('local f=CreateFrame("Frame");f:RegisterEvent("CHAT_MSG_CHANNEL");f:SetScript("OnEvent",function() GG_CHANNEL_RECEIVED={event,arg1,arg2,arg4,arg8,arg9} end)')
        self.ui.event(message['event'], *message['args'])
        self.assertEqual(self.ui.evaluate('return unpack(GG_CHANNEL_RECEIVED)'),
                         ['CHAT_MSG_CHANNEL', 'Original channel delivery', 'Second Hero', 'SavedBuilders', 1, 'SavedBuilders'])
        self.assertTrue(any(e.get('ack_id') == message['ack_id'] for e in self.view()['shared_pending_events']))
        result = self.runtime.client_control(json.dumps(dict(kind='local', op='SharedChatAck', ids=[message['ack_id']])))
        self.assertIsNone(result.get('error'), result.get('error'))
        self.assertFalse(any(e['event'] == 'CHAT_MSG_CHANNEL' for e in self.view()['shared_pending_events']))
        self.call('LeaveChannelByName("SavedBuilders")')
        self.assertEqual(self.ui.evaluate('return GetChannelList()'), [])
        self.switch(self.second); self.publish()
        self.assertEqual(self.ui.evaluate('return GetChannelList()'), [1, 'SavedBuilders'])
        self.assertEqual(self.room()['owner'], self.second)

    def test_original_saved_moderation_and_builtin_slot_keep_truthful_paths(self):
        self.join(); self.switch(self.first); self.publish()
        self.call('JoinChannelByName("General")')
        self.assertEqual(self.ui.evaluate('return GetChannelList()'), [1, 'SavedBuilders', 2, 'General - GG Island'])
        self.call('ChannelModerator("SavedBuilders","Second Hero")')
        self.assertIn(self.second, self.room()['moderators'])
        self.call('ChannelMute("SavedBuilders","Second Hero")')
        self.switch(self.second); self.publish()
        self.ui.execute('SendChatMessage("Muted should not deliver","CHANNEL",nil,"1")')
        request = self.ui.request('requests')['local_client'][0]
        result = self.runtime.client_control(json.dumps(dict(request, kind='local')))
        self.assertEqual(result['error'], 'CHANNEL_MUTED')
        self.switch(self.first); self.publish()
        self.call('ChannelUnmute("SavedBuilders","Second Hero")')
        self.call('SetChannelOwner("SavedBuilders","Second Hero")')
        self.assertEqual(self.room()['owner'], self.second)
        self.switch(self.second); self.publish()
        self.call('ChannelBan("SavedBuilders","'+self.session.rows[0]['name']+'")')
        self.assertEqual(self.room()['members'], [self.second])
        self.call('ChannelUnban("SavedBuilders","'+self.session.rows[0]['name']+'")')

    def test_original_join_space_name_gate_and_same_name_exact_numeric_selection_and_stale_freeze(self):
        self.assertEqual(self.ui.evaluate('return JoinChannelByName("two words")'), [None])
        self.assertEqual(self.ui.request('requests')['services'], [])
        self.call('JoinChannelByName("Builders")')
        result = self.runtime.client_control(json.dumps(dict(kind='service', op='ChannelJoin',
            name='Builders', shared_channel=False, session=self.runtime._service_generation)))
        self.assertIsNone(result.get('error'), result.get('error')); self.publish()
        self.assertEqual(self.ui.evaluate('return GetChannelList()'), [1, 'Builders', 2, 'Builders'])
        for slot, expected_shared in ((1, True), (2, False)):
            self.ui.execute('SendChatMessage("Exact slot '+str(slot)+'","CHANNEL",nil,"'+str(slot)+'")')
            request = self.ui.request('requests')['local_client'][0]
            self.gameplay.services.freeze_channel(request)
            self.assertIs(request['shared_channel'], expected_shared)
            result = self.runtime.client_control(json.dumps(dict(request, kind='local')))
            self.assertIsNone(result.get('error'), result.get('error'))
        self.publish()
        frozen = self.gameplay.services.route(dict(op='ChannelToggleAnnouncements', name='1'),
                                              self.gameplay.inventory_refs, self.gameplay.equipment_refs)
        self.call('ChannelToggleAnnouncements("1")')
        stale = self.runtime.client_control(json.dumps(frozen))
        self.assertEqual(stale['error'], 'CHANNEL_CHANGED')
        self.call('LeaveChannelByName("2")')
        self.assertEqual(self.ui.evaluate('return GetChannelList()'), [1, 'Builders'])

    def test_original_numeric_chat_frozen_receipt_replay_after_leave_and_slot_reuse_delivers_once(self):
        self.join()
        self.ui.execute('SendChatMessage("Frozen original numeric replay","CHANNEL",nil,"1")')
        request = self.ui.request('requests')['local_client'][0]
        self.gameplay.services.freeze_channel(request)
        self.assertIs(request['shared_channel'], True)
        sequence = self.runtime._local_custody_store.snapshot()['shared']['sequences'][self.second] + 1
        saved = dict(request, kind='local', custody_sequence=sequence)
        sent = self.runtime.client_control(json.dumps(saved))
        self.assertIsNone(sent.get('error'), sent.get('error')); self.publish()
        self.call('LeaveChannelByName("SavedBuilders")')
        self.call('JoinChannelByName("Replacement")')
        self.assertEqual(self.ui.evaluate('return GetChannelList()'), [1, 'Replacement'])
        before = self.runtime._local_custody_store.snapshot()['shared']
        replay = self.runtime.client_control(json.dumps(saved))
        self.assertIsNone(replay.get('error'), replay.get('error'))
        self.assertEqual(replay.get('client_events', []), [])
        self.assertEqual(self.runtime._local_custody_store.snapshot()['shared'], before)
        changed = self.runtime.client_control(json.dumps(dict(saved, text='Changed original receipt')))
        self.assertEqual(changed.get('error'), 'LOCAL_CUSTODY_REPLAY_CHANGED')
        self.switch(self.first); self.publish()
        pending = [e for e in self.view()['shared_pending_events']
                   if e['event'] == 'CHAT_MSG_CHANNEL' and e['args'][0] == saved['text']]
        self.assertEqual(len(pending), 1)
        self.ui.execute('GG_CHANNEL_REPLAY_COUNT=0;local f=CreateFrame("Frame");f:RegisterEvent("CHAT_MSG_CHANNEL");f:SetScript("OnEvent",function() GG_CHANNEL_REPLAY_COUNT=GG_CHANNEL_REPLAY_COUNT+1 end)')
        self.ui.event(pending[0]['event'], *pending[0]['args'])
        self.assertEqual(self.ui.evaluate('return GG_CHANNEL_REPLAY_COUNT'), [1])
        ack = self.runtime.client_control(json.dumps(dict(kind='local', op='SharedChatAck', ids=[pending[0]['ack_id']])))
        self.assertIsNone(ack.get('error'), ack.get('error'))
        self.assertFalse(any(e['event'] == 'CHAT_MSG_CHANNEL' for e in self.view()['shared_pending_events']))


if __name__ == '__main__': unittest.main()
