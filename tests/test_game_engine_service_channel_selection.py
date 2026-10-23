"""Original intent keeps the exact displayed channel lane and slot identity."""
import copy
import unittest

from backend.game_engine_adapter_service_views import ServiceViews


class ChannelSelection(unittest.TestCase):
    def setUp(self):
        self.views=ServiceViews(lambda value: value)
        self.room=dict(name='Builders',shared_channel=True,channel_id='saved-room',channel_revision=4,slot=2)
        self.views.value=dict(session=7,channels=dict(shared_available=True,rows=[],slots=[None]*10,
            shared_invite=copy.deepcopy(self.room)))

    def route(self, **row):
        return self.views.route(row,{})

    def test_explicit_original_join_does_not_accept_same_name_saved_invitation(self):
        result=self.route(op='ChannelJoin',name='Builders',shared_channel=False,password='')
        self.assertIs(result['shared_channel'],False)
        self.assertNotIn('channel_id',result)
        self.assertNotIn('channel_revision',result)

    def test_original_invited_join_freezes_exact_saved_offer(self):
        result=self.route(op='ChannelJoin',name='Builders',password='')
        self.assertIs(result['shared_channel'],True)
        self.assertEqual((result['channel_id'],result['channel_revision']),('saved-room',4))
        self.assertEqual(self.views.value['channels']['shared_invite'],self.room)

    def test_builtin_and_unbound_profile_do_not_create_saved_custom_room(self):
        for name in ('General','General - GG Island','GuildRecruitment'):
            self.assertNotIn('shared_channel',self.route(op='ChannelJoin',name=name))
        self.views.value['channels']['shared_available']=False
        self.assertNotIn('shared_channel',self.route(op='ChannelJoin',name='NewRoom'))

    def test_new_original_custom_join_uses_available_saved_account_only(self):
        self.assertIs(self.route(op='ChannelJoin',name='NewRoom')['shared_channel'],True)
        self.assertIs(self.route(op='ChannelJoin',name='NewRoom',shared_channel=False)['shared_channel'],False)
        self.assertNotIn('channel_id',self.route(op='ChannelJoin',name='NewRoom'))

    def test_duplicate_names_still_freeze_actual_numeric_slot(self):
        channels=self.views.value['channels']
        channels['rows']=[dict(name='Builders',slot=1),copy.deepcopy(self.room)]
        channels['slots'][:2]=['Builders','Builders']
        one=self.route(op='Chat',chat_type='CHANNEL',target='1',text='Original')
        two=self.route(op='Chat',chat_type='CHANNEL',target='2',text='Saved')
        self.assertIs(one['shared_channel'],False)
        self.assertNotIn('channel_id',one)
        self.assertIs(two['shared_channel'],True)
        self.assertEqual((two['channel_id'],two['channel_revision']),('saved-room',4))
        self.assertEqual((one['target'],two['target']),('1','2'))

    def test_explicit_named_lane_keeps_original_and_saved_rooms_distinct(self):
        self.views.value['channels']['rows']=[dict(name='Builders',slot=1),copy.deepcopy(self.room)]
        original=self.route(op='ChannelLeave',name='Builders',shared_channel=False)
        saved=self.route(op='ChannelLeave',name='Builders',shared_channel=True)
        self.assertIs(original['shared_channel'],False)
        self.assertIs(saved['shared_channel'],True)
        self.assertEqual((saved['channel_id'],saved['channel_revision']),('saved-room',4))


if __name__=='__main__':unittest.main()
