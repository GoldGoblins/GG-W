"""Original channel APIs: confirmed slots, delivery, rights and durable records."""
import copy
import unittest
from unittest.mock import patch
import test_game_engine_adapter_services as service_tests


class Channels(unittest.TestCase):
    setUp=service_tests.Services.setUp
    publish=service_tests.Services.publish
    call=service_tests.Services.call
    control=service_tests.Services.control
    view=service_tests.Services.view
    service=service_tests.Services.service
    move_near_npc=service_tests.Services.move_near_npc

    def test_original_channel_join_message_slots_leave_and_roundtrip(self):
        self.call('JoinChannelByName("Builders") JoinChannelByName("General")')
        self.assertEqual(self.ui.evaluate('return GetChannelName("Builders"),GetChannelName("General - GG Island")'),[1,2,'General - GG Island',0])
        self.call('SendChatMessage("Gather at the dock","CHANNEL",nil,"1")')
        journal=self.runtime.snapshot()['event_journal']['events']
        self.assertTrue(any('Gather at the dock' in e['text'] and e.get('payload',{}).get('channel')=='Builders' for e in journal))
        self.call('LeaveChannelByName("Builders") JoinChannelByName("Raiding")')
        self.assertEqual(self.ui.evaluate('return GetChannelList()'),[1,'Raiding',2,'General - GG Island'])
        self.runtime.load_state();self.publish();self.assertEqual(self.ui.evaluate('return GetChannelList()'),[1,'Raiding',2,'General - GG Island'])

    def test_actual_membership_ban_mute_owner_transfer_and_server_permissions(self):
        identity=self.move_near_npc();name=self.runtime._service_unit_locked(identity)['name']
        self.call('JoinChannelByName("Crew") ChannelInvite("Crew","'+name+'") ChannelModerator("Crew","'+name+'")')
        channel=self.runtime._services['channels'][0];self.assertIn(identity,channel['members']);self.assertIn(identity,channel['moderators'])
        self.call('ChannelBan("Crew","'+name+'")');self.assertIn(identity,channel['banned']);self.assertNotIn(identity,channel['members'])
        self.assertEqual(self.service('ChannelInvite',name='Crew',player=name)['error'],'CHANNEL_BANNED')
        self.call('ChannelUnban("Crew","'+name+'") ChannelInvite("Crew","'+name+'") SetChannelOwner("Crew","'+name+'")')
        self.assertEqual(self.service('ChannelBan',name='Crew',player=name)['error'],'CHANNEL_MODERATOR_REQUIRED')
        self.assertEqual(self.runtime._services['channels'][0]['owner'],identity)

    def test_channel_password_not_published_and_wrong_password_cannot_rejoin(self):
        self.call('JoinChannelByName("Private","test-channel-pass") LeaveChannelByName("Private")')
        raw=self.runtime._client_controls_save_locked();self.assertNotIn('test-channel-pass',str(raw))
        self.assertEqual(self.service('ChannelJoin',name='Private',password='wrong')['error'],'CHANNEL_PASSWORD_INVALID')
        self.assertFalse(any(self.runtime._services['channel_slots']))
        self.call('JoinChannelByName("Private","test-channel-pass")');self.assertEqual(self.ui.evaluate('return (GetChannelName("Private"))'),[1])
        self.assertNotIn('password',self.view()['channels']['rows'][0])
        self.runtime.load_state();self.publish();self.assertEqual(self.ui.evaluate('return (GetChannelName("Private"))'),[1])

    def test_membership_limits_builtin_permissions_and_failed_commit(self):
        before=copy.deepcopy(self.runtime._services)
        with patch.object(self.runtime._state_store,'save',side_effect=OSError('disk full')):
            self.assertEqual(self.service('ChannelJoin',name='Rollback')['error'],'SERVICE_SAVE_FAILED')
        current=copy.deepcopy(self.runtime._services);current['clock']=before['clock'];self.assertEqual(before,current)
        self.call('JoinChannelByName("General")')
        self.assertEqual(self.service('ChannelModerate',name='General')['error'],'CHANNEL_MODERATOR_REQUIRED')
        for i in range(9):self.service('ChannelJoin',name='Extra'+str(i))
        self.assertEqual(self.service('ChannelJoin',name='Over')['error'],'CHANNEL_JOIN_CAPACITY')
        self.assertEqual(len([v for v in self.runtime._services['channel_slots'] if v]),10)

    def test_original_guild_recruitment_cascade_and_manual_leave(self):
        self.call('SetGuildRecruitmentMode(1)')
        self.assertIn('GuildRecruitment - GG Island',self.view()['channels']['slots'])
        self.assertEqual(self.ui.evaluate('return GetGuildRecruitmentMode()'),[1])
        self.call('LeaveChannelByName("GuildRecruitment")')
        self.assertEqual(self.ui.evaluate('return GetGuildRecruitmentMode()'),[0])

if __name__=='__main__':unittest.main()
