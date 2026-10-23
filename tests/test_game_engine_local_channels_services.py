"""Original public controls over real LocalCharacters login/saved custody."""
import copy
import json
import unittest
from unittest.mock import patch

import test_game_engine_local_custody_services as fixture
from backend import game_engine_local_channels as channels


class LocalChannels(unittest.TestCase):
    setUp = fixture.SharedServices.setUp
    bind = fixture.SharedServices.bind
    switch = fixture.SharedServices.switch
    view = fixture.SharedServices.view

    def command(self, op, **fields):
        result = self.runtime.client_control(json.dumps(dict(kind='service', op=op,
            session=self.runtime._service_generation, **fields)))
        self.assertIsNone(result.get('error'), result.get('error'))
        return result

    def chat(self, text, target='Builders', **fields):
        result = self.runtime.client_control(json.dumps(dict(kind='local', op='Chat',
            chat_type='CHANNEL', target=target, text=text, **fields)))
        self.assertIsNone(result.get('error'), result.get('error'))
        return result

    def room(self):
        return next(row for row in self.view()['channels']['rows'] if row.get('shared_channel'))

    def join(self):
        self.command('ChannelJoin', name='Builders', password='channel test pass', shared_channel=True)
        self.command('ChannelInvite', name='Builders', player='Second Hero')
        self.switch(self.second)
        offer = self.view()['channels']['shared_invite']
        self.assertEqual(offer['name'], 'Builders')
        self.assertEqual(self.view()['channels']['rows'], [])
        self.command('ChannelJoin', name='Builders', password='channel test pass')

    def test_real_invite_switch_explicit_join_chat_switch_delivery_ack_leave_reload(self):
        self.join()
        self.assertEqual(self.room()['members'], [self.first, self.second])
        sent = self.chat('Bridge plans ready', target='1')
        self.assertEqual(sent['client_events'][0]['event'], 'CHAT_MSG_CHANNEL')
        self.switch(self.first)
        pending = next(e for e in self.view()['shared_pending_events'] if e['event'] == 'CHAT_MSG_CHANNEL')
        self.assertEqual(pending['args'][0:4], ['Bridge plans ready', 'Second Hero', 'GG', 'Builders'])
        self.assertEqual(pending['args'][7], 1)
        self.assertEqual(sum(e.get('ack_id') == pending['ack_id'] for e in self.view()['shared_pending_events']), 1)
        ack = self.runtime.client_control(json.dumps(dict(kind='local', op='SharedChatAck', ids=[pending['ack_id']])))
        self.assertNotIn('error', ack)
        self.assertFalse(any(e['event'] == 'CHAT_MSG_CHANNEL' for e in self.view()['shared_pending_events']))
        self.command('ChannelLeave', name='Builders')
        self.assertEqual(self.view()['channels']['slots'], [None] * 10)
        self.switch(self.second)
        self.assertEqual(self.room()['owner'], self.second)
        self.assertEqual(self.room()['owner_name'], 'Second Hero')
        self.switch(self.second)
        self.assertEqual(self.room()['members'], [self.second])

    def test_original_npc_zone_join_after_shared_join_reserves_distinct_slot_and_survives_switch(self):
        self.command('ChannelJoin', name='Builders', shared_channel=True)
        self.command('ChannelJoin', name='General', password='')
        self.assertEqual(self.view()['channels']['slots'][:2], ['Builders', 'General - GG Island'])
        self.assertEqual(self.runtime._services['channel_slots'][:2], [None, 'general - gg island'])
        self.chat('Shared self echo', target='1')
        self.chat('Actual NPC echo', target='2')
        self.switch(self.first)
        self.assertEqual(self.view()['channels']['slots'][:2], ['Builders', 'General - GG Island'])
        self.assertEqual(len([r for r in self.view()['channels']['rows'] if r.get('builtin')]), 1)

    def test_view_cache_never_reads_all_profiles_or_emits_save_events_for_repeated_getters(self):
        self.join(); self.view()
        store = self.runtime._local_custody_store
        with (patch.object(store, 'snapshot', side_effect=AssertionError('paint cannot read profiles')),
             patch.object(store, 'roster', side_effect=AssertionError('paint cannot read roster')),
             patch.object(self.runtime, 'save_state', side_effect=AssertionError('paint cannot checkpoint'))):
            for _ in range(20):
                self.view(); self.runtime.ui_snapshot()

    def test_shared_operation_preserves_actual_player_cast_position_combat_and_npc_services(self):
        self.runtime._ensure_combat_actors_locked()
        self.runtime._x[0] = 37.
        self.assertNotIn('error', self.runtime.activate_ability('ability.tide_mend'))
        before = {key: copy.deepcopy(getattr(self.runtime, key)) for key in ('_combat_state', '_spell_state', '_services', '_local_client')}
        self.command('ChannelJoin', name='Builders', shared_channel=True)
        self.assertEqual(self.runtime._x[0], 37.)
        for key, value in before.items():
            if key == '_services': value['clock'] = self.runtime._services['clock']
            self.assertEqual(getattr(self.runtime, key), value, key)

    def test_expired_offer_and_original_replay_cannot_fall_back_into_npc_membership_or_chat(self):
        self.command('ChannelJoin', name='Builders', shared_channel=True, custody_sequence=1)
        self.command('ChannelInvite', name='Builders', player='Second Hero', custody_sequence=2)
        self.switch(self.second); expires = self.view()['channels']['shared_invite']['expires']
        with patch('time.time', return_value=expires + 1):
            self.runtime._tick_shared_custody_locked()
            self.assertIsNone(self.view()['channels']['shared_invite'])
        self.command('ChannelJoin', name='Builders', shared_channel=True)
        self.chat('One actual message', custody_sequence=3)
        self.command('ChannelLeave', name='Builders', custody_sequence=4)
        replay = self.chat('One actual message', custody_sequence=3)
        self.assertEqual(replay.get('client_events', []), [])
        changed = self.runtime.client_control(json.dumps(dict(kind='local', op='Chat', chat_type='CHANNEL',
            target='Builders', text='Changed old receipt', custody_sequence=3)))
        self.assertIn('REPLAY_CHANGED', changed['error'])
        self.assertEqual(self.runtime._services['channels'], [])

    def test_remote_saved_member_is_never_a_world_actor_or_npc_registry_entry(self):
        self.join()
        self.assertNotIn(self.first, self.runtime._individual_state['individuals'])
        self.assertNotIn(self.first, self.runtime._combat_state.get('actors', {}))
        self.assertFalse(any(r['id'] == self.first for r in self.view()['people']))
        row = self.room()
        self.assertEqual(row['member_names'], [self.session.rows[0]['name'], 'Second Hero'])
        self.assertNotIn('password', row); self.assertNotIn('online', row)

    def test_reserved_world_token_cannot_resolve_saved_character_invite_and_frozen_selection_rejects(self):
        self.command('ChannelJoin', name='Builders', shared_channel=True)
        selected = self.room(); self.command('ChannelModerate', name='Builders')
        bad = self.runtime.client_control(json.dumps(dict(kind='service', op='ChannelInvite',
            session=self.runtime._service_generation, name='Builders', player='Second Hero',
            channel_id=selected['channel_id'], channel_revision=selected['channel_revision'], shared_channel=True)))
        self.assertEqual(bad['error'], 'CHANNEL_CHANGED')
        target = self.runtime.client_control(json.dumps(dict(kind='service', op='ChannelInvite',
            session=self.runtime._service_generation, name='Builders', player='target', shared_channel=True)))
        self.assertEqual(target['error'], 'CHANNEL_SAVED_CHARACTER_REQUIRED')

    def test_same_name_npc_and_shared_rooms_keep_distinct_numeric_slots_and_explicit_selectors(self):
        self.command('ChannelJoin', name='Builders', shared_channel=False)
        self.command('ChannelJoin', name='Builders', shared_channel=True)
        view = self.view()['channels']; self.assertTrue(view['shared_available'])
        self.assertEqual(view['slots'][:2], ['Builders', 'Builders'])
        shared = self.room()
        self.assertEqual(shared['slot'], 2); self.assertEqual(shared['player_id'], self.first)
        self.assertTrue(shared['can_manage']); self.assertTrue(shared['is_owner'])
        self.chat('Actual NPC room', target='1')
        self.chat('Actual saved room', target='2')
        self.command('ChannelLeave', name='Builders', shared_channel=False)
        self.assertEqual(self.view()['channels']['slots'][:2], [None, 'Builders'])
        self.assertEqual(self.room()['members'], [self.first])
        result = self.runtime.client_control(json.dumps(dict(kind='service', op='ChannelLeave',
            name='Builders', shared_channel=False, channel_id=shared['channel_id'],
            channel_revision=shared['channel_revision'], session=self.runtime._service_generation)))
        self.assertEqual(result['error'], 'CHANNEL_CHANGED')
        self.command('ChannelLeave', name='Builders', shared_channel=True)
        result = self.runtime.client_control(json.dumps(dict(kind='service', op='ChannelLeave',
            name='Other room', shared_channel=True, channel_id=shared['channel_id'],
            channel_revision=shared['channel_revision'], session=self.runtime._service_generation)))
        self.assertEqual(result['error'], 'CHANNEL_CHANGED')

    def test_explicit_npc_selector_cannot_downgrade_or_replay_shared_chat_receipt(self):
        self.command('ChannelJoin', name='Builders', shared_channel=True, custody_sequence=1)
        self.chat('Original shared message', custody_sequence=2)
        result = self.runtime.client_control(json.dumps(dict(kind='local', op='Chat', chat_type='CHANNEL',
            target='Builders', text='Original shared message', shared_channel=False, custody_sequence=2)))
        self.assertEqual(result['error'], 'CHANNEL_CHANGED')

    def test_mixed_real_channel_then_party_chat_preserves_durable_inbox_order_in_lua_projection(self):
        self.join(); self.switch(self.first)
        self.command('GroupInvite', target='Second Hero')
        self.switch(self.second); self.command('GroupAccept'); self.switch(self.first)
        self.chat('First channel message')
        result = self.runtime.client_control(json.dumps(dict(kind='local', op='Chat', chat_type='PARTY',
                                                            text='Second party message')))
        self.assertIsNone(result.get('error'), result.get('error'))
        self.switch(self.second)
        inbox = self.runtime._local_custody_store.snapshot()['shared']['chat'][self.second]
        expected = [m['id'] for m in inbox]
        pending = [e for e in self.view()['shared_pending_events'] if e.get('ack_id')]
        self.assertEqual([e['ack_id'] for e in pending], expected)
        self.assertEqual([e['event'] for e in pending if e['event'] != 'CHAT_MSG_CHANNEL_NOTICE'],
                         ['CHAT_MSG_CHANNEL', 'CHAT_MSG_PARTY'])
        row = self.room()
        result = self.runtime.client_control(json.dumps(dict(kind='local', op='Chat', chat_type='CHANNEL',
            target='Builders', text='Frozen downgrade', shared_channel=False,
            channel_id=row['channel_id'], channel_revision=row['channel_revision'])))
        self.assertEqual(result['error'], 'CHANNEL_CHANGED')

    def test_frozen_numeric_chat_replay_after_leave_and_slot_reuse_has_no_second_delivery(self):
        self.join(); selected = self.room()
        saved = dict(kind='local', op='Chat', chat_type='CHANNEL', target='1',
                     text='Exact saved numeric replay', shared_channel=True,
                     channel_id=selected['channel_id'], channel_revision=selected['channel_revision'],
                     custody_sequence=2)
        sent = self.runtime.client_control(json.dumps(saved))
        self.assertIsNone(sent.get('error'), sent.get('error'))
        self.command('ChannelLeave', name='Builders', custody_sequence=3)
        for reuse in (False, True):
            if reuse:
                self.command('ChannelJoin', name='Replacement', shared_channel=True, custody_sequence=4)
                self.assertEqual(self.view()['channels']['slots'][0], 'Replacement')
            before = self.runtime._local_custody_store.snapshot()['shared']
            replay = self.runtime.client_control(json.dumps(saved))
            self.assertIsNone(replay.get('error'), replay.get('error'))
            self.assertEqual(replay.get('client_events', []), [])
            self.assertEqual(self.runtime._local_custody_store.snapshot()['shared'], before)
        for field, value in (('target', '2'), ('text', 'Changed message'),
                             ('channel_id', channels.channel_id('Replacement')),
                             ('channel_revision', selected['channel_revision'] + 1)):
            with self.subTest(field=field):
                changed = self.runtime.client_control(json.dumps(dict(saved, **{field: value})))
                self.assertEqual(changed.get('error'), 'LOCAL_CUSTODY_REPLAY_CHANGED')
        self.switch(self.first)
        messages = [e for e in self.view()['shared_pending_events']
                    if e['event'] == 'CHAT_MSG_CHANNEL' and e['args'][0] == saved['text']]
        self.assertEqual(len(messages), 1)

    def test_direct_numeric_message_and_leave_replay_bind_prior_receipt_before_current_slot(self):
        self.join(); selected = self.room()
        message = dict(kind='service', op='ChannelMessage', name='1', text='Direct numeric message',
                       shared_channel=True, channel_id=selected['channel_id'],
                       channel_revision=selected['channel_revision'], custody_sequence=2,
                       session=self.runtime._service_generation)
        sent = self.runtime.client_control(json.dumps(message))
        self.assertIsNone(sent.get('error'), sent.get('error'))
        selected = self.room()
        leave = dict(kind='service', op='ChannelLeave', name='1', shared_channel=True,
                     channel_id=selected['channel_id'], channel_revision=selected['channel_revision'],
                     custody_sequence=3, session=self.runtime._service_generation)
        left = self.runtime.client_control(json.dumps(leave))
        self.assertIsNone(left.get('error'), left.get('error'))
        for reuse in (False, True):
            if reuse:
                self.command('ChannelJoin', name='Replacement', shared_channel=True, custody_sequence=4)
            before = self.runtime._local_custody_store.snapshot()['shared']
            for saved in (message, leave):
                replay = self.runtime.client_control(json.dumps(saved))
                self.assertIsNone(replay.get('error'), replay.get('error'))
                self.assertEqual(replay.get('client_events', []), [])
            self.assertEqual(self.runtime._local_custody_store.snapshot()['shared'], before)
        for saved in (message, leave):
            for field, value in (('name', '2'), ('channel_id', channels.channel_id('Replacement')),
                                 ('channel_revision', saved['channel_revision'] + 1),
                                 ('op', 'ChannelModerate'), ('op', 'ChannelListAll')):
                with self.subTest(op=saved['op'], field=field, value=value):
                    changed = self.runtime.client_control(json.dumps(dict(saved, **{field: value})))
                    self.assertEqual(changed.get('error'), 'LOCAL_CUSTODY_REPLAY_CHANGED')
        changed = self.runtime.client_control(json.dumps(dict(message, text='Changed direct message')))
        self.assertEqual(changed.get('error'), 'LOCAL_CUSTODY_REPLAY_CHANGED')


if __name__ == '__main__': unittest.main()
