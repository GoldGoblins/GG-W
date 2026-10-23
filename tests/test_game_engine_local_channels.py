"""Real saved members, strict custom-room policy and durable channel delivery."""
import copy
import json
import unittest
from pathlib import Path

import test_game_engine_local_custody as fixture
from backend import game_engine_local_channels as channels
from backend.game_engine_local_custody import LocalCustodyStore, RecoveryRequired, digest
from backend.game_engine_local_characters import CharacterStore, atomic

A, B, C = fixture.A, fixture.B, fixture.C
NAMES = {A: 'Hero 0', B: 'Hero 1', C: 'Hero 2'}


ChannelStore = LocalCustodyStore


class Channels(unittest.TestCase):
    seed = fixture.Custody.seed
    payload = fixture.Custody.payload
    files = fixture.Custody.files

    def setUp(self):
        fixture.Custody.setUp(self)
        self.store = ChannelStore(self.root)
        self.sequences = {A: 0, B: 0, C: 0}

    def action(self, issuer, op, name='Builders', *, sequence=None, now=1000, **fields):
        if sequence is None:
            self.sequences[issuer] += 1; sequence = self.sequences[issuer]
        return self.store.channel_action(issuer, sequence, dict(op=op, name=name, **fields), now=now)

    def room(self, name='Builders'):
        return self.store.snapshot()['shared']['shared_channels'][channels.channel_id(name)]

    def inbox(self, character):
        return self.store.snapshot()['shared']['chat'].get(character, [])

    def pair(self, password=''):
        self.action(A, 'ChannelJoin', password=password)
        self.action(B, 'ChannelJoin', password=password)

    def clear(self, character):
        inbox = self.inbox(character)
        if inbox:
            self.sequences[character] += 1
            self.store.acknowledge_chat(character, self.sequences[character], [m['id'] for m in inbox])

    def save_controls(self, character, services=None, client=None):
        value = self.payload(character)
        controls = value.setdefault('player', {}).setdefault('client_controls', {})
        if services is not None: controls['services'] = services
        if client is not None: controls['local_client'] = client
        CharacterStore(self.root).save(character, value)

    def test_actual_join_does_not_invent_other_characters_or_world_actors(self):
        before = self.store.snapshot()['characters']
        self.action(A, 'ChannelJoin', password='test channel password')
        room = self.room()
        self.assertEqual(room['members'], [A]); self.assertEqual(room['slots'], {A: 1})
        self.assertEqual(room['owner'], A)
        self.assertEqual(self.store.snapshot()['characters'], before)
        self.assertEqual(room['password']['salt'].__len__(), 32)
        self.assertNotIn(b'test channel password', (self.root / 'shared-custody.json').read_bytes())

    def test_invite_is_offline_notification_and_only_explicit_join_adds_actual_recipient(self):
        self.action(A, 'ChannelJoin')
        sent = self.action(A, 'ChannelInvite', target=B)
        self.assertEqual(self.room()['members'], [A])
        offer = self.store.snapshot()['shared']['channel_invites'][B]
        self.assertEqual(offer['expires'], 1060)
        self.assertEqual(sent['result']['recipients'], [B])
        self.assertEqual(self.inbox(B)[0]['notice'], 'INVITE')
        self.assertEqual(self.inbox(B)[0]['channel_slot'], 0)
        self.action(B, 'ChannelJoin')
        self.assertEqual(self.room()['members'], [A, B])
        self.assertNotIn(B, self.store.snapshot()['shared']['channel_invites'])
        self.assertFalse(any(m.get('notice') == 'INVITE' for m in self.inbox(B)))

    def test_joining_another_custom_room_does_not_accept_or_delete_unrelated_invitation(self):
        self.action(A, 'ChannelJoin'); self.action(A, 'ChannelInvite', target=B)
        self.action(B, 'ChannelJoin', name='Other room')
        self.assertEqual(self.room()['members'], [A])
        self.assertIn(B, self.store.snapshot()['shared']['channel_invites'])
        self.assertEqual(self.inbox(B)[0]['notice'], 'INVITE')

    def test_protected_invitation_still_requires_real_correct_password(self):
        self.action(A, 'ChannelJoin', password='correct channel pass')
        self.action(A, 'ChannelInvite', target=B)
        before = self.files()
        with self.assertRaisesRegex(ValueError, 'CHANNEL_PASSWORD_INVALID'):
            self.action(B, 'ChannelJoin', password='wrong')
        self.assertEqual(before, self.files())
        self.action(B, 'ChannelJoin', password='correct channel pass')
        self.assertIn(B, self.room()['members'])

    def test_chat_delivers_once_to_actual_members_in_their_actual_local_slot(self):
        self.save_controls(B, services={'channel_slots': ['general - gg island', None] + [None] * 8})
        self.pair(); self.clear(A)
        result = self.action(A, 'ChannelMessage', text='Built the bridge')
        self.assertEqual(result['result']['recipients'], [B])
        message = self.inbox(B)[0]
        self.assertEqual(message['kind'], 'CHANNEL'); self.assertEqual(message['channel_slot'], 2)
        self.assertEqual(message['expires'], message['sent'] + channels.MESSAGE_SECONDS)
        event = channels.message_event(message, 'Hero 0')
        self.assertEqual(event['event'], 'CHAT_MSG_CHANNEL')
        self.assertEqual(event['args'], ['Built the bridge', 'Hero 0', 'GG', 'Builders', 'Hero 0', '', 0, 2, 'Builders', 2])
        self.assertEqual(self.inbox(A), [])
        self.assertEqual(self.inbox(C), [])
        self.action(A, 'ChannelMessage', text='Built the bridge', sequence=self.sequences[A])
        self.assertEqual(len(self.inbox(B)), 1)

    def test_ack_removes_only_successfully_published_actual_recipient_messages(self):
        self.pair(); self.clear(A)
        self.action(A, 'ChannelMessage', text='first'); self.action(A, 'ChannelMessage', text='second')
        ids = [m['id'] for m in self.inbox(B)]
        self.store.acknowledge_chat(B, 2, [ids[0]])
        self.assertEqual([m['id'] for m in self.inbox(B)], [ids[1]])
        self.store.acknowledge_chat(B, 2, [ids[0]])
        self.assertEqual([m['id'] for m in self.inbox(B)], [ids[1]])
        with self.assertRaisesRegex(ValueError, 'REPLAY_CHANGED'):
            self.store.acknowledge_chat(B, 2, [ids[1]])

    def test_ignore_suppresses_real_channel_chat_and_invite_without_fake_delivery(self):
        self.save_controls(B, client={'ignores': ['Hero 0']})
        self.pair(); self.clear(A)
        result = self.action(A, 'ChannelMessage', text='ignored')
        self.assertEqual(result['result']['recipients'], [])
        self.assertEqual(self.inbox(B), [])
        self.action(B, 'ChannelLeave'); before = self.files()
        with self.assertRaisesRegex(ValueError, 'CHANNEL_INVITE_IGNORED'):
            self.action(A, 'ChannelInvite', target=B)
        self.assertEqual(before, self.files())

    def test_moderated_mute_unmute_and_owner_policy_use_actual_saved_authority(self):
        self.pair(); self.clear(A)
        self.action(A, 'ChannelModerate')
        with self.assertRaisesRegex(ValueError, 'CHANNEL_MUTED'):
            self.action(B, 'ChannelMessage', text='not a moderator')
        self.action(A, 'ChannelModerator', target=B)
        self.action(B, 'ChannelMessage', text='moderator speaks')
        self.action(A, 'ChannelMute', target=B)
        with self.assertRaisesRegex(ValueError, 'CHANNEL_MUTED'):
            self.action(B, 'ChannelMessage', text='muted moderator')
        self.action(A, 'ChannelUnmute', target=B)
        self.action(B, 'ChannelMessage', text='unmuted')
        with self.assertRaisesRegex(ValueError, 'CHANNEL_OWNER_REQUIRED'):
            self.action(B, 'ChannelModerate')
        with self.assertRaisesRegex(ValueError, 'CHANNEL_OWNER_PROTECTED'):
            self.action(B, 'ChannelKick', target=A)

    def test_member_cannot_moderate_or_reassign_owner(self):
        self.pair(); before = self.files()
        for op, fields in [('ChannelMute', {'target': A}), ('ChannelSetOwner', {'target': B}),
                           ('ChannelSetPassword', {'password': 'new'}), ('ChannelToggleAnnouncements', {})]:
            with self.subTest(op=op), self.assertRaisesRegex(ValueError, 'CHANNEL_MODERATOR_REQUIRED'):
                self.action(B, op, **fields)
        self.assertEqual(before, self.files())

    def test_ban_removes_actual_slot_and_prevents_rejoin_until_explicit_unban(self):
        self.pair(); self.clear(A)
        self.action(A, 'ChannelBan', target=B)
        self.assertNotIn(B, self.room()['slots']); self.assertEqual(self.room()['banned'], [B])
        self.assertEqual(self.inbox(B)[0]['notice'], 'PLAYER_BANNED')
        self.assertEqual(self.inbox(B)[0]['channel_slot'], 1)
        with self.assertRaisesRegex(ValueError, 'CHANNEL_BANNED'):
            self.action(B, 'ChannelJoin')
        self.action(A, 'ChannelUnban', target=B); self.action(B, 'ChannelJoin')
        self.assertIn(B, self.room()['members'])

    def test_owner_leave_transfers_to_actual_join_order_and_preserves_room_password(self):
        self.pair('kept secret'); self.action(C, 'ChannelJoin', password='kept secret')
        password = self.room()['password']
        self.action(A, 'ChannelLeave')
        self.assertEqual(self.room()['owner'], B); self.assertEqual(self.room()['members'], [B, C])
        self.action(B, 'ChannelLeave'); self.action(C, 'ChannelLeave')
        self.assertEqual(self.room()['owner'], ''); self.assertEqual(self.room()['slots'], {})
        self.assertEqual(self.room()['password'], password)
        self.action(A, 'ChannelJoin', password='kept secret')
        self.assertEqual(self.room()['owner'], A)

    def test_frozen_room_revision_rejects_mutated_selection_without_saving(self):
        self.pair(); revision = self.room()['revision']; self.action(A, 'ChannelModerate')
        before = self.files()
        with self.assertRaisesRegex(ValueError, 'CHANNEL_CHANGED'):
            self.action(A, 'ChannelInvite', target=C, channel_revision=revision)
        self.assertEqual(before, self.files())

    def test_password_change_and_replay_bind_actual_password_without_plaintext_storage(self):
        self.pair(); self.action(A, 'ChannelSetPassword', password='actual replacement pass')
        seq = self.sequences[A]
        self.action(A, 'ChannelSetPassword', password='actual replacement pass', sequence=seq)
        before = self.files()
        with self.assertRaisesRegex(ValueError, 'REPLAY_CHANGED'):
            self.action(A, 'ChannelSetPassword', password='changed replay', sequence=seq)
        self.assertEqual(before, self.files())
        self.assertNotIn(b'actual replacement pass', (self.root / 'shared-custody.json').read_bytes())
        with self.assertRaisesRegex(ValueError, 'CHANNEL_PASSWORD_INVALID'):
            self.action(C, 'ChannelJoin', password='')
        self.action(C, 'ChannelJoin', password='actual replacement pass')

    def test_ten_combined_npc_and_shared_slots_never_alias(self):
        self.save_controls(A, services={'channel_slots': ['general - gg island'] + [None] * 9})
        for index in range(9): self.action(A, 'ChannelJoin', name='Room ' + str(index))
        self.assertEqual(channels.reserved_slots(self.store.snapshot()['shared'], A), set(range(2, 11)))
        before = self.files()
        with self.assertRaisesRegex(ValueError, 'CHANNEL_JOIN_CAPACITY'):
            self.action(A, 'ChannelJoin', name='Room ten')
        self.assertEqual(before, self.files())
        self.action(A, 'ChannelLeave', name='Room 3')
        self.action(A, 'ChannelJoin', name='Replacement')
        self.assertEqual(self.room('Replacement')['slots'][A], 5)

    def test_overwriting_shared_slot_from_legacy_checkpoint_is_rejected_before_write(self):
        self.action(A, 'ChannelJoin')
        value = self.payload(A)
        value['player'].setdefault('client_controls', {})['services'] = {'channel_slots': ['local shadow'] + [None] * 9}
        with self.assertRaisesRegex(ValueError, 'CHANNEL_JOIN_CAPACITY'):
            self.store.validate_save(A, value)

    def test_original_zone_and_numeric_names_cannot_create_shared_fake_world_channels(self):
        before = self.files()
        for name in ('General', 'Trade - GG Island', '1', '', ' Names ', 'Room\nName'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.action(A, 'ChannelJoin', name=name)
        self.assertEqual(before, self.files())

    def test_unknown_saved_targets_self_invite_and_duplicate_offer_do_not_mutate(self):
        self.action(A, 'ChannelJoin')
        for target in (A, 'd' * 32, 'npc-wanderer-01'):
            before = self.files()
            with self.subTest(target=target), self.assertRaises(ValueError):
                self.action(A, 'ChannelInvite', target=target)
            self.assertEqual(before, self.files())
        self.action(A, 'ChannelInvite', target=B)
        before = self.files()
        with self.assertRaisesRegex(ValueError, 'CHANNEL_INVITE_PENDING'):
            self.action(A, 'ChannelInvite', target=B)
        self.assertEqual(before, self.files())

    def test_offline_notification_expiry_never_autojoins_and_real_chat_expiry_prunes(self):
        self.action(A, 'ChannelJoin'); self.action(A, 'ChannelInvite', target=B)
        self.store.settle(A, 3, now=1061)
        self.assertNotIn(B, self.store.snapshot()['shared']['channel_invites'])
        self.assertEqual(self.room()['members'], [A]); self.assertEqual(self.inbox(B), [])
        self.sequences[A] = 3
        self.action(B, 'ChannelJoin', now=1062); self.clear(A)
        self.action(A, 'ChannelMessage', text='queued', now=1063)
        self.store.settle(A, self.sequences[A] + 1, now=1063 + channels.MESSAGE_SECONDS)
        self.assertEqual(self.inbox(B), [])

    def test_outstanding_social_custody_blocks_character_deletion_until_explicit_cleanup(self):
        self.action(A, 'ChannelJoin'); self.action(A, 'ChannelInvite', target=B)
        self.assertIn('CHANNEL_MEMBERSHIP', self.store.can_delete(A, include_history=False)['blockers'])
        self.assertIn('CHANNEL_INVITE', self.store.can_delete(B, include_history=False)['blockers'])
        self.action(A, 'ChannelLeave'); self.store.settle(A, 4, now=1061)
        self.assertTrue(self.store.can_delete(A, include_history=False)['allowed'])
        self.assertTrue(self.store.can_delete(B, include_history=False)['allowed'])

    def test_full_recipient_inbox_rejects_entire_multirecipient_send(self):
        self.pair(); self.action(C, 'ChannelJoin'); self.clear(A); self.clear(B)
        for index in range(64): self.action(A, 'ChannelMessage', text='message ' + str(index))
        before = self.files()
        with self.assertRaisesRegex(ValueError, 'CHAT_INBOX_FULL'):
            self.action(A, 'ChannelMessage', text='sixty five')
        self.assertEqual(before, self.files())
        self.assertEqual(len(self.inbox(B)), 64); self.assertEqual(len(self.inbox(C)), 64)

    def test_message_shape_clock_slot_sender_and_duplicate_tampering_rejected(self):
        self.pair(); self.clear(A); self.action(A, 'ChannelMessage', text='real')
        value = self.store.snapshot(); message = value['shared']['chat'][B][0]
        mutations = [dict(channel_slot=0), dict(channel_name='Other room'), dict(sender=B),
                     dict(expires=1001), dict(text=''), dict(password='plaintext')]
        for mutation in mutations:
            bad = copy.deepcopy(value['shared']); bad['chat'][B][0].update(mutation)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.store._validate(value['characters'], bad)
        bad = copy.deepcopy(value['shared']); bad['chat'][B].append(copy.deepcopy(message))
        with self.assertRaisesRegex(ValueError, 'CHAT_INVALID'):
            self.store._validate(value['characters'], bad)

    def test_room_role_and_npc_slot_tampering_rejected(self):
        self.pair(); value = self.store.snapshot(); key = channels.channel_id('Builders')
        mutations = [dict(owner=C), dict(moderators=[C]), dict(muted=[A]), dict(banned=[B]),
                     dict(members=[A, A]), dict(slots={A: 0, B: 1}), dict(revision=True)]
        for mutation in mutations:
            bad = copy.deepcopy(value['shared']); bad['shared_channels'][key].update(mutation)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.store._validate(value['characters'], bad)

    def test_exact_transition_proof_rejects_unrequested_other_ledger_and_result_change(self):
        self.pair(); before = self.store.snapshot(); request = channels.canonical_request(
            dict(op='ChannelMessage', name='Builders', text='proved'), before['shared'], A, 2)
        shared = copy.deepcopy(before['shared']); result = channels.apply(before['characters'], shared,
            A, 2, request, now=1000, names=NAMES)
        command = dict(op='CHANNEL_ACTION', row=request)
        channels.prove(before['characters'], before['characters'], before['shared'], shared,
                       A, 2, command, names=NAMES, result=result)
        bad = copy.deepcopy(shared); bad['money_sinks'] += 1
        with self.assertRaisesRegex(ValueError, 'CHANNEL_ENTITLEMENT'):
            channels.prove(before['characters'], before['characters'], before['shared'], bad,
                           A, 2, command, names=NAMES, result=result)
        with self.assertRaisesRegex(ValueError, 'CHANNEL_ENTITLEMENT'):
            channels.prove(before['characters'], before['characters'], before['shared'], shared,
                           A, 2, command, names=NAMES, result=dict(result, recipients=[]))

    def test_recovered_committed_intent_preserves_password_chat_and_actual_assets(self):
        self.pair(); self.clear(A); before = self.store.snapshot()['characters']; failed = False
        def fault(stage, name):
            nonlocal failed
            if not failed and (stage, name) == ('replaced', 'shared-custody.pending.json'):
                failed = True; raise OSError('fixture directory fsync')
        self.store.fault = fault
        with self.assertRaises(RecoveryRequired):
            self.action(A, 'ChannelMessage', text='committed')
        self.assertTrue((self.root / 'shared-custody.pending.json').exists())
        self.store.fault = None; result = ChannelStore(self.root).recover()
        self.assertEqual(result['status'], 'COMMITTED')
        self.assertEqual(self.store.snapshot()['characters'], before)
        self.assertEqual(len(self.inbox(B)), 1)
        replay = self.action(A, 'ChannelMessage', text='committed', sequence=self.sequences[A])
        self.assertTrue(replay['replayed']); self.assertEqual(len(self.inbox(B)), 1)

    def test_fault_boundaries_leave_either_no_intent_or_forward_only_recoverable_delivery(self):
        stages = [('before_write', 'shared-custody.pending.json'), ('file_synced', 'shared-custody.pending.json'),
                  ('replaced', 'shared-custody.pending.json'), ('directory_synced', 'shared-custody.pending.json'),
                  ('before_write', 'shared-custody.json'), ('file_synced', 'shared-custody.json'),
                  ('replaced', 'shared-custody.json'), ('directory_synced', 'shared-custody.json'),
                  ('before_clear', 'shared-custody.pending.json'), ('journal_removed', 'shared-custody.pending.json')]
        for index, point in enumerate(stages):
            with self.subTest(point=point):
                root = Path(self.directory.name) / ('fault-' + str(index)); self.seed(root)
                store = ChannelStore(root)
                store.channel_action(A, 1, dict(op='ChannelJoin', name='Fault room'), now=1000)
                store.channel_action(B, 1, dict(op='ChannelJoin', name='Fault room'), now=1000)
                failed = False
                def fault(stage, name):
                    nonlocal failed
                    if not failed and (stage, name) == point:
                        failed = True; raise OSError('bounded fixture fault')
                store.fault = fault
                with self.assertRaises(OSError):
                    store.channel_action(A, 2, dict(op='ChannelMessage', name='Fault room', text='durable'), now=1000)
                fresh = ChannelStore(root); fresh.recover()
                result = fresh.channel_action(A, 2, dict(op='ChannelMessage', name='Fault room', text='durable'), now=1000)
                self.assertTrue(result['result']['recipients'] == [B])
                self.assertEqual(len(fresh.snapshot()['shared']['chat'][B]), 1)

    def test_recovery_rejects_rehashed_unrequested_mode_and_changed_or_null_receipt_result(self):
        for index, mutation in enumerate(('mode', 'recipients', 'null_result')):
            with self.subTest(mutation=mutation):
                root = Path(self.directory.name) / ('tampered-' + str(index)); self.seed(root)
                store = ChannelStore(root)
                store.channel_action(A, 1, dict(op='ChannelJoin', name='Verified room'), now=1000)
                store.channel_action(B, 1, dict(op='ChannelJoin', name='Verified room'), now=1000)
                def fault(stage, name):
                    if (stage, name) == ('replaced', 'shared-custody.pending.json'):
                        raise OSError('fixture committed intent')
                store.fault = fault
                with self.assertRaises(RecoveryRequired):
                    store.channel_action(A, 2, dict(op='ChannelMessage', name='Verified room', text='exact consent'), now=1000)
                path = root / 'shared-custody.pending.json'; journal = json.loads(path.read_text())
                target = journal['targets'][-1]; shared = target['value']
                if mutation == 'mode':
                    shared['shared_channels'][channels.channel_id('Verified room')]['moderated'] = True
                elif mutation == 'recipients':
                    shared['receipts'][A + ':2']['result']['recipients'] = []
                else:
                    shared['receipts'][A + ':2']['result'] = None
                target['after'] = digest(shared); atomic(path, journal)
                before = {p.name: p.read_bytes() for p in root.glob('*.json')}
                with self.assertRaises(RecoveryRequired) as error:
                    ChannelStore(root).recover()
                self.assertEqual(str(error.exception.__cause__), 'LOCAL_CUSTODY_CHANNEL_ENTITLEMENT')
                self.assertEqual(before, {p.name: p.read_bytes() for p in root.glob('*.json')})


if __name__ == '__main__': unittest.main()
