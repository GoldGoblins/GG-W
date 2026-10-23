"""Real character envelopes/items, durable custody, and deterministic crashes."""
import copy
import fcntl
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import game_engine_items as items, game_engine_mmo as mmo
from backend.game_engine_local_characters import CharacterStore, atomic
from backend.game_engine_local_custody import LocalCustodyStore, RecoveryRequired, asset_id, digest

A = 'a' * 32
B = 'b' * 32
C = 'c' * 32
ITEM = 'starter-sea-salt'


class ProcessCrash(BaseException):
    pass


class Custody(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name) / 'characters'
        self.catalog = items.catalog_from_content()
        self.seed(self.root)
        self.store = LocalCustodyStore(self.root)

    def seed(self, root):
        store = CharacterStore(root)
        roster = []
        for index, character in enumerate((A, B, C)):
            rows = items.starter_instances(self.catalog)
            for slot, row in enumerate(rows):
                if row['location'] == 'INVENTORY':row['slot_index'] = slot
            payload = mmo.persistent_payload(player={}, movement_mode='WALK',
                inventory=items.inventory_counts(rows), loot_items=[], progression={'level': 1},
                editor_document={}, item_instances=rows,
                economy_state={'wallet': {'gold': 100, 'copper': index, 'revision': 0}})
            payload['character_appearance'] = {'own_character': character}
            store.save(character, payload)
            roster.append({'id': character, 'name': 'Hero ' + str(index), 'selection': {}, 'level': 1})
        atomic(root / 'characters.json', {'schema': 'gg.local-characters.v1', 'characters': roster})

    def payload(self, character, store=None):
        return (store or self.store).snapshot()['characters'][character]['payload']

    def money(self, character, store=None):
        return LocalCustodyStore._money(self.payload(character, store))

    def send(self, sequence=1, store=None, **kwargs):
        return (store or self.store).send_mail(A, sequence, B, catalog=self.catalog,
                                              item_id=ITEM, subject='Actual parcel', **kwargs)

    def files(self, root=None):
        root = root or self.root
        return {path.name: path.read_bytes() for path in root.glob('*.json')}

    def debit_two(self, payloads, shared):
        self.store._money(payloads[A], -123)
        self.store._money(payloads[B], 123)
        return {'copper': 123}

    def test_identical_starter_ids_are_two_real_assets_and_transfer_collision_preserves_both(self):
        before = self.store.snapshot()
        first = next(i for i in before['characters'][A]['payload']['item_instances'] if i['instance_id'] == ITEM)
        second = next(i for i in before['characters'][B]['payload']['item_instances'] if i['instance_id'] == ITEM)
        self.assertNotEqual(asset_id(A, first), asset_id(B, second))
        sent = self.send(money=123)
        self.assertEqual(self.money(A), 1_000_000 - 153)
        held = self.store.snapshot()['shared']['escrow'][sent['result']['asset']]
        self.assertEqual((held['definition_id'], held['quantity'], held['location'], held['owner_id']),
                         (first['definition_id'], first['quantity'], 'MAIL', B))
        claimed = self.store.collect_mail(B, 1, sent['result']['mail'])
        received = claimed['result']['item']
        self.assertNotEqual(received, ITEM)
        rows = self.payload(B)['item_instances']
        self.assertEqual(len([i for i in rows if i['instance_id'] in (ITEM, received)]), 2)
        moved = next(i for i in rows if i['instance_id'] == received)
        self.assertEqual(asset_id(B, moved), asset_id(A, first))
        self.assertEqual(self.money(B), 1_000_001 + 123)
        self.assertNotIn(ITEM, [i['instance_id'] for i in self.payload(A)['item_instances']])
        self.assertEqual(self.store.snapshot()['shared']['escrow'], {})
        self.assertEqual(self.payload(B)['character_appearance'], {'own_character': B})
        loaded = CharacterStore(self.root).load(B)
        self.assertEqual(loaded['item_instances'], rows)

    def test_exact_replay_returns_receipt_without_second_debit_or_attachment(self):
        result = self.send(money=123)
        before = self.files()
        replay = self.send(money=123)
        self.assertTrue(replay['replayed'])
        self.assertEqual(result['result'], replay['result'])
        self.assertEqual(before, self.files())

    def test_same_receipt_changed_full_command_is_rejected(self):
        self.send(money=123)
        before = self.files()
        with self.assertRaisesRegex(ValueError, 'REPLAY_CHANGED'):self.send(money=124)
        self.assertEqual(before, self.files())

    def test_expected_revision_is_part_of_replay_and_stale_observation_is_rejected(self):
        self.send(expected_revision=1)
        before = self.files()
        with self.assertRaisesRegex(ValueError, 'REPLAY_CHANGED'):self.send(expected_revision=2)
        with self.assertRaisesRegex(ValueError, 'REVISION_CHANGED'):
            self.store.send_mail(A, 2, B, catalog=self.catalog, subject='Text', expected_revision=1)
        self.assertEqual(before, self.files())

    def test_cod_payment_remains_actual_money_escrow_until_sender_collects(self):
        sent = self.send(cod=201)
        self.store.collect_mail(B, 1, sent['result']['mail'], collect='ITEM')
        self.assertEqual(self.money(B), 1_000_001 - 201)
        mail = self.store.snapshot()['shared']['mail']
        cod_id = next(k for k, row in mail.items() if row['recipient'] == A and row['money'] == 201)
        self.store.collect_mail(A, 2, cod_id, collect='MONEY')
        self.assertEqual(self.money(A), 1_000_000 - 30 + 201)
        self.assertEqual(self.store.snapshot()['shared']['money_sinks'], 30)

    def test_collect_money_separately_keeps_actual_attachment(self):
        sent = self.send(money=100)
        self.store.collect_mail(B, 1, sent['result']['mail'], collect='MONEY')
        shared = self.store.snapshot()['shared']
        self.assertIn(sent['result']['asset'], shared['escrow'])
        self.assertEqual(shared['mail'][sent['result']['mail']]['money'], 0)

    def test_actual_full_bag_with_legacy_unassigned_cells_cannot_collect_or_pay_cod(self):
        payload = CharacterStore(self.root).load(B)
        payload['item_instances'] = [items.make_instance(self.catalog, 'finite-salt-' + str(i), 'item.sea_salt')
                                     for i in range(items.MAX_INVENTORY_SLOTS)]
        payload['inventory'] = items.inventory_counts(payload['item_instances'])
        CharacterStore(self.root).save(B, payload)
        sent = self.send(cod=100)
        before = self.files()
        with self.assertRaisesRegex(ValueError, 'INVENTORY_FULL'):
            self.store.collect_mail(B, 1, sent['result']['mail'])
        self.assertEqual(before, self.files())

    def test_full_wallet_cannot_collect_actual_money_and_leave_partial_item_claim(self):
        payload = CharacterStore(self.root).load(B)
        payload['economy_state']['wallet'].update(gold=2_000_000_000, copper=9999)
        CharacterStore(self.root).save(B, payload)
        sent = self.send(money=100)
        before = self.files()
        with self.assertRaises(ValueError):self.store.collect_mail(B, 1, sent['result']['mail'])
        self.assertEqual(before, self.files())

    def test_item_lineage_survives_second_character_sending_same_physical_item_again(self):
        sent = self.send()
        received = self.store.collect_mail(B, 1, sent['result']['mail'])['result']['item']
        second = self.store.send_mail(B, 2, C, catalog=self.catalog, item_id=received)
        self.assertEqual(second['result']['asset'], sent['result']['asset'])
        self.store.collect_mail(C, 1, second['result']['mail'])
        self.assertEqual(len(self.store.snapshot()['shared']['escrow']), 0)
        self.assertNotIn(received, [i['instance_id'] for i in self.payload(B)['item_instances']])

    def test_auction_buyout_moves_actual_item_and_coins_with_single_commission(self):
        posted = self.store.post_auction(A, 1, ITEM, catalog=self.catalog, min_bid=100, buyout=500)
        self.assertEqual(self.money(A), 1_000_000 - 5)
        self.store.bid_auction(B, 1, posted['result']['auction'], 999)
        shared = self.store.snapshot()['shared']
        self.assertEqual(shared['auctions'], {})
        self.assertEqual(self.money(B), 1_000_001 - 500)
        self.assertEqual(shared['money_sinks'], 25)
        seller_mail = next(k for k, m in shared['mail'].items() if m['recipient'] == A and m['money'])
        buyer_mail = next(k for k, m in shared['mail'].items() if m['recipient'] == B and m['asset'])
        self.store.collect_mail(A, 2, seller_mail)
        self.store.collect_mail(B, 2, buyer_mail)
        self.assertEqual(self.money(A), 1_000_000 + 475)
        self.assertEqual(self.store.snapshot()['shared']['escrow'], {})

    def test_outbid_refunds_actual_previous_bid_and_own_bid_consumes_only_difference(self):
        posted = self.store.post_auction(A, 1, ITEM, catalog=self.catalog, min_bid=100)
        auction = posted['result']['auction']
        self.store.bid_auction(B, 1, auction, 100)
        self.store.bid_auction(B, 2, auction, 105)
        self.assertEqual(self.money(B), 1_000_001 - 105)
        self.store.bid_auction(C, 1, auction, 111)
        shared = self.store.snapshot()['shared']
        refund = next(k for k, m in shared['mail'].items() if m['recipient'] == B and m['money'] == 105)
        self.store.collect_mail(B, 3, refund)
        self.assertEqual(self.money(B), 1_000_001)

    def test_cancelled_auction_refunds_bid_and_returns_physical_item_with_deposit_sink(self):
        auction = self.store.post_auction(A, 1, ITEM, catalog=self.catalog, min_bid=100)['result']['auction']
        self.store.bid_auction(B, 1, auction, 100)
        self.store.finish_auction(A, 2, auction, cancel=True)
        shared = self.store.snapshot()['shared']
        self.assertEqual(shared['money_sinks'], 5)
        self.assertEqual(len(shared['escrow']), 1)
        self.assertEqual(sum(m['money'] for m in shared['mail'].values()), 100)

    def test_shared_guild_has_stable_local_member_ids_and_conserved_creation_cost(self):
        guild = self.store.create_guild(A, 1, 'Gold Goblins')['result']['guild']
        self.store.invite_guild_member(A, 2, guild, B)
        self.assertNotIn(B, self.store.snapshot()['shared']['guilds'][guild]['members'])
        self.store.answer_guild_invite(B, 1, True)
        shared = LocalCustodyStore(self.root).snapshot()['shared']
        self.assertEqual({k:v['rank'] for k,v in shared['guilds'][guild]['members'].items()}, {A: 0, B: 4})
        self.assertEqual(shared['money_sinks'], 10000)
        self.assertEqual(self.money(A), 990000)
        with self.assertRaisesRegex(ValueError, 'GUILD_PERMISSION'):
            self.store.invite_guild_member(B, 2, guild, C)

    def test_no_character_can_belong_to_two_shared_guilds(self):
        guild = self.store.create_guild(A, 1, 'Gold Goblins')['result']['guild']
        self.store.create_guild(B, 1, 'Silver Goblins')
        before = self.files()
        with self.assertRaisesRegex(ValueError, 'GUILD_MEMBERSHIP'):
            self.store.invite_guild_member(A, 2, guild, B)
        self.assertEqual(before, self.files())

    def test_two_real_character_files_commit_transfer_and_preserve_each_appearance(self):
        result = self.store.transact(A, 1, {'op': 'COIN_TRANSFER', 'amount': 123}, [A, B], self.debit_two,
                                     expected_revisions={A: 1, B: 2})
        self.assertEqual(result['status'], 'COMMITTED')
        self.assertEqual(self.money(A), 1_000_000 - 123)
        self.assertEqual(self.money(B), 1_000_001 + 123)
        self.assertEqual(self.payload(A)['character_appearance'], {'own_character': A})
        self.assertEqual(self.payload(B)['character_appearance'], {'own_character': B})

    def test_ordinary_precommit_failure_leaves_every_file_identical(self):
        for stage in ('before_write', 'file_synced'):
            with self.subTest(stage=stage):
                before = self.files()
                def fault(current, name):
                    if current == stage and name == 'shared-custody.pending.json':raise OSError('disk unavailable')
                self.store.fault = fault
                with self.assertRaises(OSError) as caught:self.send()
                self.assertNotIsInstance(caught.exception, RecoveryRequired)
                self.assertEqual(before, self.files())
        self.store.fault = None

    def test_every_post_intent_fault_has_explicit_committed_outcome_and_recovery(self):
        positions = [('replaced', 'shared-custody.pending.json'), ('directory_synced', 'shared-custody.pending.json')]
        positions += [(stage, name) for name in (A + '.json', B + '.json', 'shared-custody.json')
                      for stage in ('before_write', 'file_synced', 'replaced', 'directory_synced')]
        positions += [('before_clear', 'shared-custody.pending.json'), ('journal_removed', 'shared-custody.pending.json')]
        for index, position in enumerate(positions):
            with self.subTest(position=position):
                root = Path(self.directory.name) / ('fault-' + str(index));self.seed(root)
                def fault(stage, name):
                    if (stage, name) == position:raise OSError('injected durable edge')
                store = LocalCustodyStore(root, fault=fault)
                with self.assertRaises(RecoveryRequired) as caught:
                    store.transact(A, 1, {'op': 'COIN_TRANSFER', 'amount': 123}, [A, B], self.debit_two)
                self.assertTrue(caught.exception.committed)
                self.assertEqual(caught.exception.receipt, A + ':1')
                restarted = LocalCustodyStore(root)
                restarted.recover()
                self.assertEqual(self.money(A, restarted), 999877)
                self.assertEqual(self.money(B, restarted), 1000124)
                replay = restarted.transact(A, 1, {'op': 'COIN_TRANSFER', 'amount': 123}, [A, B], self.debit_two)
                self.assertTrue(replay['replayed'])
                self.assertFalse((root / 'shared-custody.pending.json').exists())

    def test_real_directory_fsync_failure_after_journal_replace_is_not_failed_rollback(self):
        real_sync = os.fsync
        failed = False
        def sync(fd):
            nonlocal failed
            if not failed and os.path.isdir('/proc/self/fd/' + str(fd)):
                failed = True;raise OSError('directory fsync failed after intent replace')
            return real_sync(fd)
        with patch('backend.game_engine_local_custody.os.fsync', side_effect=sync):
            with self.assertRaises(RecoveryRequired):self.send(money=123)
        self.assertTrue(failed)
        self.assertTrue((self.root / 'shared-custody.pending.json').exists())
        self.store.recover()
        self.assertEqual(self.money(A), 999847)

    def test_process_crash_after_first_character_write_recovers_forward_once(self):
        def crash(stage, name):
            if (stage, name) == ('replaced', A + '.json'):raise ProcessCrash()
        self.store.fault = crash
        with self.assertRaises(ProcessCrash):
            self.store.transact(A, 1, {'op': 'COIN_TRANSFER', 'amount': 123}, [A, B], self.debit_two)
        self.assertEqual(CharacterStore(self.root).load(A)['economy_state']['wallet']['copper'], 9877)
        self.assertEqual(CharacterStore(self.root).load(B)['economy_state']['wallet']['copper'], 1)
        restarted = LocalCustodyStore(self.root)
        restarted.recover();restarted.recover()
        self.assertEqual(self.money(B, restarted), 1000124)

    def test_unrelated_writer_change_blocks_recovery_without_overwriting_any_other_target(self):
        def fault(stage, name):
            if (stage, name) == ('replaced', 'shared-custody.pending.json'):raise OSError('stop before images')
        self.store.fault = fault
        with self.assertRaises(RecoveryRequired):
            self.store.transact(A, 1, {'op': 'COIN_TRANSFER', 'amount': 123}, [A, B], self.debit_two)
        changed = CharacterStore(self.root).load(B);changed['progression']['level'] = 2
        CharacterStore(self.root).save(B, changed)
        before = self.files()
        restarted = LocalCustodyStore(self.root)
        with self.assertRaises(RecoveryRequired) as caught:restarted.recover()
        self.assertRegex(str(caught.exception.__cause__), 'RECOVERY_CONFLICT')
        self.assertEqual(before, self.files())

    def test_borrowed_existing_session_lock_is_reused_and_never_released(self):
        fd = os.open(self.root / '.session.lock', os.O_RDWR | os.O_CREAT, 0o600)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with self.assertRaisesRegex(ValueError, 'SESSION_BUSY'):self.store.snapshot()
        borrowed = LocalCustodyStore(self.root, session_lock=fd)
        self.send(store=borrowed)
        with self.assertRaisesRegex(ValueError, 'SESSION_BUSY'):self.store.snapshot()

    def test_wrong_borrowed_lock_descriptor_is_rejected(self):
        fd = os.open(Path(self.directory.name) / 'unrelated.lock', os.O_RDWR | os.O_CREAT, 0o600)
        self.addCleanup(os.close, fd)
        with self.assertRaisesRegex(ValueError, 'LOCK_INVALID'):
            LocalCustodyStore(self.root, session_lock=fd).snapshot()

    def test_character_shared_journal_and_lock_symlinks_are_rejected(self):
        for name in (A + '.json', 'shared-custody.json', 'shared-custody.pending.json', '.session.lock'):
            with self.subTest(name=name):
                root = Path(self.directory.name) / ('symlink-' + name);self.seed(root)
                target = Path(self.directory.name) / ('target-' + name);target.write_text('{}')
                path = root / name
                if path.exists():path.unlink()
                path.symlink_to(target)
                with self.assertRaises((ValueError, RecoveryRequired)):LocalCustodyStore(root).snapshot()
                self.assertEqual(target.read_text(), '{}')

    def test_symlink_parent_directory_is_rejected(self):
        link = Path(self.directory.name) / 'linked';link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'SYMLINK'):LocalCustodyStore(link).snapshot()

    def test_invalid_identity_boolean_money_and_sequence_never_touch_files(self):
        before = self.files()
        for argument in ({'money': True}, {'cod': True}, {'money': -1}):
            with self.assertRaises(ValueError):self.send(**argument)
        for sequence in (True, 0, -1, 2**63):
            with self.assertRaises(ValueError):self.send(sequence)
        with self.assertRaises(ValueError):self.store.send_mail(A, 1, '../outside', catalog=self.catalog)
        self.assertEqual(before, self.files())

    def test_oversized_nonfinite_command_and_payload_are_rejected(self):
        before = self.files()
        for request in ({'value': float('nan')}, {'body': 'x' * 65537}):
            with self.assertRaises(ValueError):self.store.transact(A, 1, request, [], lambda p, s: {})
        def expand(payloads, shared):payloads[A]['oversized'] = 'x' * (8 * 1024 * 1024);return {}
        with self.assertRaises(ValueError):self.store.transact(A, 1, {'op': 'SIZE'}, [A], expand)
        self.assertEqual(before, self.files())

    def test_duplicate_local_item_or_duplicate_global_origin_fail_closed(self):
        original = CharacterStore(self.root).load(B)
        for alteration in ('local_id', 'origin'):
            payload = copy.deepcopy(original)
            if alteration == 'local_id':payload['item_instances'].append(copy.deepcopy(payload['item_instances'][0]))
            else:payload['item_instances'][0]['custody_origin'] = {'character': A, 'instance': payload['item_instances'][0]['instance_id']}
            CharacterStore(self.root).save(B, payload)
            with self.assertRaises(ValueError):self.store.snapshot()
        CharacterStore(self.root).save(B, original)

    def test_mutator_cannot_mint_money_items_or_legacy_count_inventory(self):
        before = self.files()
        def mint_money(payloads, shared):self.store._money(payloads[A], 1);return {}
        def mint_item(payloads, shared):payloads[A]['item_instances'][0]['quantity'] += 1;self.store._sync_inventory(payloads[A]);return {}
        def mint_count(payloads, shared):payloads[A]['inventory']['item.sea_salt'] += 1;return {}
        for mutator in (mint_money, mint_item, mint_count):
            with self.assertRaises(ValueError):self.store.transact(A, 1, {'op': 'FORGE'}, [A], mutator)
            self.assertEqual(before, self.files())

    def test_active_appearance_decorator_cannot_overwrite_inactive_character(self):
        before = self.files()
        def decorate(payloads, shared):payloads[B]['character_appearance'] = {'own_character': A};return {}
        with self.assertRaisesRegex(ValueError, 'APPEARANCE_CHANGED'):
            self.store.transact(A, 1, {'op': 'DECORATE'}, [B], decorate)
        self.assertEqual(before, self.files())

    def test_reserved_receipt_revision_fields_cannot_be_mutated(self):
        before = self.files()
        def alter(payloads, shared):shared['sequences'][A] = 500;return {}
        with self.assertRaisesRegex(ValueError, 'RESERVED_FIELD_CHANGED'):
            self.store.transact(A, 1, {'op': 'FORGE'}, [], alter)
        self.assertEqual(before, self.files())

    def test_bound_item_and_unknown_recipient_keep_wallet_and_physical_item(self):
        payload = CharacterStore(self.root).load(A)
        next(i for i in payload['item_instances'] if i['instance_id'] == ITEM)['bound_to'] = A
        CharacterStore(self.root).save(A, payload)
        before = self.files()
        with self.assertRaisesRegex(ValueError, 'BOUND'):self.send()
        with self.assertRaisesRegex(ValueError, 'RECIPIENT_UNAVAILABLE'):
            self.store.send_mail(A, 1, 'd' * 32, catalog=self.catalog, money=1)
        self.assertEqual(before, self.files())

    def test_finite_receipt_retention_rejects_evicted_sequence_instead_of_replaying(self):
        with patch('backend.game_engine_local_custody.MAX_RECEIPTS', 2):
            for sequence in (1, 2, 3):
                self.store.transact(A, sequence, {'op': 'NOOP'}, [], lambda p, s: {})
            before = self.files()
            with self.assertRaisesRegex(ValueError, 'RECEIPT_EXPIRED'):
                self.store.transact(A, 1, {'op': 'NOOP'}, [], lambda p, s: {})
            self.assertEqual(before, self.files())

    def test_receipt_eviction_uses_commit_order_across_issuers_after_sorted_json_reload(self):
        with patch('backend.game_engine_local_custody.MAX_RECEIPTS', 2):
            for issuer, sequence in ((B, 1), (A, 10), (A, 11)):
                self.store.transact(issuer, sequence, {'op': 'NOOP'}, [], lambda p, s: {})
            receipts = self.store.snapshot()['shared']['receipts']
            self.assertEqual(set(receipts), {A + ':10', A + ':11'})
            with self.assertRaisesRegex(ValueError, 'RECEIPT_EXPIRED'):
                self.store.transact(B, 1, {'op': 'NOOP'}, [], lambda p, s: {})

    def test_recomputed_after_hash_cannot_hide_item_minting_in_pending_intent(self):
        def fault(stage, name):
            if (stage, name) == ('replaced', 'shared-custody.pending.json'):raise OSError('stop')
        self.store.fault = fault
        with self.assertRaises(RecoveryRequired):self.send()
        path = self.root / 'shared-custody.pending.json'
        value = json.loads(path.read_text())
        target = value['targets'][-1]
        next(iter(target['value']['escrow'].values()))['quantity'] += 1
        target['after'] = digest(target['value'])
        atomic(path, value)
        before = self.files()
        with self.assertRaises(RecoveryRequired) as caught:LocalCustodyStore(self.root).recover()
        self.assertRegex(str(caught.exception.__cause__), 'CONSERVATION')
        self.assertEqual(before, self.files())

    def test_two_character_limit_and_mailbox_capacity_are_preflighted(self):
        before = self.files()
        with self.assertRaisesRegex(ValueError, 'TRANSACTION_CAPACITY'):
            self.store.transact(A, 1, {'op': 'NOOP'}, [A, B, C], lambda p, s: {})
        with patch('backend.game_engine_local_custody.MAX_MAIL', 1):
            self.store.send_mail(A, 1, B, catalog=self.catalog, subject='One')
            before = self.files()
            with self.assertRaisesRegex(ValueError, 'MAILBOX_FULL'):
                self.store.send_mail(A, 2, B, catalog=self.catalog, subject='Two')
            self.assertEqual(before, self.files())

    def test_corrupted_pending_intent_is_explicit_recovery_required(self):
        (self.root / 'shared-custody.pending.json').write_text('{broken')
        with self.assertRaises(RecoveryRequired):self.store.recover()

    def test_auction_duration_deposit_and_deadline_match_actual_local_service_policy(self):
        auction = self.store.post_auction(A, 1, ITEM, catalog=self.catalog, min_bid=100,
                                          duration=480,now=100)['result']['auction']
        row = self.store.snapshot()['shared']['auctions'][auction]
        self.assertEqual((row['duration'],row['deposit'],row['expires']), (480,20,100+480*60))
        before = self.files()
        with self.assertRaisesRegex(ValueError, 'NOT_EXPIRED'):
            self.store.finish_auction(A, 2, auction, now=101)
        with self.assertRaisesRegex(ValueError, 'DURATION'):
            self.store.post_auction(B, 1, ITEM, catalog=self.catalog, min_bid=100,duration=240,now=101)
        self.assertEqual(before,self.files())
        self.store.finish_auction(A,2,auction,now=row['expires'])
        self.assertEqual(self.store.snapshot()['shared']['auctions'],{})

    def test_expired_auction_rejects_new_bid_and_settles_once_with_real_invoice(self):
        auction = self.store.post_auction(A,1,ITEM,catalog=self.catalog,min_bid=100,now=100)['result']['auction']
        self.store.bid_auction(B,1,auction,100,now=101)
        with self.assertRaisesRegex(ValueError,'EXPIRED'):self.store.bid_auction(C,1,auction,200,now=7300)
        self.store.settle(C,1,now=7300)
        shared=self.store.snapshot()['shared']
        proceeds=next(m for m in shared['mail'].values() if m['invoice'])
        self.assertEqual(proceeds['invoice']['consignment'],5)
        self.assertEqual(proceeds['invoice']['player_name'],B)
        self.store.settle(C,1,now=7300)
        self.assertEqual(shared,self.store.snapshot()['shared'])

    def test_guild_offer_requires_correct_recipient_consent_and_expires_durably(self):
        guild=self.store.create_guild(A,1,'Gold Goblins')['result']['guild']
        self.store.invite_guild_member(A,2,guild,B,now=100)
        with self.assertRaisesRegex(ValueError,'INVITATION_EXPIRED'):
            self.store.answer_guild_invite(C,1,True,now=101)
        self.store.answer_guild_invite(B,1,False,now=101)
        self.assertNotIn(B,self.store.snapshot()['shared']['guilds'][guild]['members'])
        self.store.invite_guild_member(A,3,guild,B,now=102)
        with self.assertRaisesRegex(ValueError,'INVITATION_EXPIRED'):
            self.store.answer_guild_invite(B,2,True,now=162)
        self.store.settle(A,4,now=162)
        self.assertEqual(self.store.snapshot()['shared']['guild_invites'],{})

    def test_shared_mail_read_return_delete_and_expiry_preserve_real_escrow(self):
        sent=self.send(now=100,cod=100)
        mail_id=sent['result']['mail']
        self.store.mail_action(B,1,mail_id,'READ',now=101)
        self.assertTrue(self.store.snapshot()['shared']['mail'][mail_id]['read'])
        with self.assertRaisesRegex(ValueError,'UNCOLLECTED'):
            self.store.mail_action(B,2,mail_id,'DELETE',now=102)
        self.store.settle(A,2,now=100+30*86400)
        row=self.store.snapshot()['shared']['mail'][mail_id]
        self.assertTrue(row['returned']);self.assertEqual((row['recipient'],row['cod']),(A,0))
        with self.assertRaisesRegex(ValueError,'CANNOT_RETURN'):
            self.store.mail_action(A,3,mail_id,'RETURN',now=100+30*86400)
        self.store.collect_mail(A,3,mail_id,now=100+30*86400)
        self.store.mail_action(A,4,mail_id,'DELETE',now=100+30*86400)
        self.assertEqual(self.store.snapshot()['shared']['escrow'],{})

    def test_delete_guard_reports_all_durable_references_without_modifying_any_file(self):
        self.assertTrue(self.store.can_delete(C)['allowed'])
        self.send()
        guild=self.store.create_guild(A,2,'Gold Goblins')['result']['guild']
        self.store.invite_guild_member(A,3,guild,C)
        before=self.files()
        blockers=self.store.can_delete(A)['blockers']
        self.assertTrue({'MAIL','ESCROW','GUILD','GUILD_INVITATION','TRANSACTION_HISTORY'} <= set(blockers))
        self.assertFalse(self.store.can_delete(C)['allowed'])
        self.assertEqual(before,self.files())

    def test_confirmed_history_only_delete_retires_namespace_without_touching_other_profiles(self):
        self.store.transact(C,1,{'op':'OBSERVED'},[C],lambda payloads,shared:{'observed':True})
        self.assertFalse(self.store.can_delete(C)['allowed'])
        self.assertTrue(self.store.can_delete(C,include_history=False)['allowed'])
        before=self.files()
        result=self.store.delete_character(C)
        self.assertEqual(result['status'],'COMMITTED')
        self.assertEqual([r['id'] for r in result['rows']],[A,B])
        self.assertFalse((self.root/(C+'.json')).exists())
        for character in (A,B):self.assertEqual(before[character+'.json'],self.files()[character+'.json'])
        shared=self.store.snapshot()['shared']
        self.assertNotIn(C,shared['sequences']);self.assertFalse(any(k.startswith(C+':') for k in shared['receipts']))
        self.assertEqual(shared['retired'][C]['sequence'],1)
        current=self.files()
        self.assertTrue(self.store.delete_character(C)['replayed'])
        self.assertEqual(current,self.files())

    def test_confirmed_delete_rejects_active_references_before_any_write(self):
        self.send()
        before=self.files()
        for character in (A,B):
            with self.subTest(character=character),self.assertRaisesRegex(ValueError,'DELETE_REFERENCES'):
                self.store.delete_character(character)
            self.assertEqual(before,self.files())

    def test_last_character_delete_keeps_empty_roster_and_retired_namespaces_recoverable(self):
        for character in (C,B,A):self.store.delete_character(character)
        snapshot=self.store.snapshot()
        self.assertEqual(snapshot['characters'],{})
        self.assertEqual(self.store.roster(),[])
        self.assertEqual(set(snapshot['shared']['retired']),{A,B,C})
        self.assertTrue(LocalCustodyStore(self.root).delete_character(A)['replayed'])

    def test_deleted_character_id_cannot_be_reused_to_resurrect_assets_or_old_receipts(self):
        envelope=json.loads((self.root/(C+'.json')).read_text())
        registry=json.loads((self.root/'characters.json').read_text())
        self.store.delete_character(C)
        atomic(self.root/(C+'.json'),envelope);atomic(self.root/'characters.json',registry)
        before=self.files()
        with self.assertRaisesRegex(ValueError,'RETIRED_CHARACTER_REUSED'):self.store.snapshot()
        self.assertEqual(before,self.files())

    def test_delete_precommit_failure_leaves_roster_history_and_profile_identical(self):
        for stage in ('before_write','file_synced'):
            with self.subTest(stage=stage):
                before=self.files()
                def fail(current,name):
                    if (current,name)==(stage,'shared-custody.pending.json'):raise OSError('before durable intent')
                self.store.fault=fail
                with self.assertRaises(OSError) as caught:self.store.delete_character(C)
                self.assertNotIsInstance(caught.exception,RecoveryRequired)
                self.assertEqual(before,self.files())
        self.store.fault=None

    def test_every_delete_post_intent_fault_recovers_roster_ledger_and_profile_unlink_once(self):
        positions=[('replaced','shared-custody.pending.json'),('directory_synced','shared-custody.pending.json')]
        positions += [(stage,name) for name in ('shared-custody.json','characters.json')
                      for stage in ('before_write','file_synced','replaced','directory_synced')]
        positions += [(stage,C+'.json') for stage in ('before_delete','deleted','directory_synced')]
        positions += [(stage,'shared-custody.pending.json') for stage in ('before_clear','journal_removed')]
        for index,position in enumerate(positions):
            with self.subTest(position=position):
                root=Path(self.directory.name)/('retire-fault-'+str(index));self.seed(root)
                before=self.files(root)
                def fail(stage,name):
                    if (stage,name)==position:raise OSError('interrupted deletion edge')
                store=LocalCustodyStore(root,fault=fail)
                with self.assertRaises(RecoveryRequired) as caught:store.delete_character(C)
                self.assertTrue(caught.exception.committed)
                self.assertEqual(str(caught.exception),'LOCAL_CUSTODY_RECOVERY_REQUIRED')
                restarted=LocalCustodyStore(root);restarted.recover()
                self.assertEqual([r['id'] for r in restarted.roster()],[A,B])
                self.assertFalse((root/(C+'.json')).exists())
                self.assertTrue(restarted.delete_character(C)['replayed'])
                for character in (A,B):self.assertEqual(before[character+'.json'],self.files(root)[character+'.json'])
                self.assertFalse((root/'shared-custody.pending.json').exists())

    def test_real_directory_fsync_failure_after_profile_unlink_has_committed_recovery(self):
        real_sync=os.fsync;failed=False
        def sync(fd):
            nonlocal failed
            if not failed and not (self.root/(C+'.json')).exists() and os.path.isdir('/proc/self/fd/'+str(fd)):
                failed=True;raise OSError('directory fsync after unlink')
            return real_sync(fd)
        with patch('backend.game_engine_local_custody.os.fsync',side_effect=sync):
            with self.assertRaises(RecoveryRequired):self.store.delete_character(C)
        self.assertTrue(failed)
        result=LocalCustodyStore(self.root).recover()
        self.assertEqual(result['character_deleted'],C)
        self.assertEqual([r['id'] for r in result['rows']],[A,B])
        self.assertTrue(self.store.delete_character(C)['replayed'])

    def test_process_crash_after_roster_replace_recovers_before_loading_missing_profile(self):
        def crash(stage,name):
            if (stage,name)==('replaced','characters.json'):raise ProcessCrash()
        self.store.fault=crash
        with self.assertRaises(ProcessCrash):self.store.delete_character(C)
        self.assertTrue((self.root/(C+'.json')).exists())
        restarted=LocalCustodyStore(self.root)
        self.assertEqual(set(restarted.snapshot()['characters']),{A,B})
        self.assertFalse((self.root/(C+'.json')).exists())

    def test_delete_recovery_conflict_does_not_overwrite_roster_ledger_or_profile(self):
        def fail(stage,name):
            if (stage,name)==('replaced','shared-custody.pending.json'):raise OSError('stop before files')
        self.store.fault=fail
        with self.assertRaises(RecoveryRequired):self.store.delete_character(C)
        registry=json.loads((self.root/'characters.json').read_text());registry['characters'][0]['name']='Changed elsewhere'
        atomic(self.root/'characters.json',registry)
        before=self.files()
        with self.assertRaises(RecoveryRequired) as caught:LocalCustodyStore(self.root).recover()
        self.assertRegex(str(caught.exception.__cause__),'RECOVERY_CONFLICT')
        self.assertEqual(before,self.files())

    def test_real_permanent_letter_entitlement_materializes_once_and_recovers_after_partial_commit(self):
        self.catalog['items']['item.gg_letter']=dict(id='item.gg_letter',name='Letter',kind='ITEM',rarity='COMMON',stack_limit=1,tags=['NO_TRADE'],equip_slots=[])
        sent=self.store.send_mail(A,1,B,catalog=self.catalog,subject='A message',body='Actual persisted text')
        def fail(stage,name):
            if (stage,name)==('replaced',B+'.json'):raise OSError('interrupted materialization')
        self.store.fault=fail
        with self.assertRaises(RecoveryRequired):
            self.store.save_mail_text(B,1,sent['result']['mail'],catalog=self.catalog)
        restarted=LocalCustodyStore(self.root);restarted.recover()
        replay=restarted.save_mail_text(B,1,sent['result']['mail'],catalog=self.catalog)
        self.assertTrue(replay['replayed'])
        letters=[i for i in self.payload(B,restarted)['item_instances'] if i['definition_id']=='item.gg_letter']
        self.assertEqual(len(letters),1);self.assertEqual(letters[0]['letter']['body'],'Actual persisted text')
        with self.assertRaisesRegex(ValueError,'ENTITLEMENT'):
            restarted.save_mail_text(B,2,sent['result']['mail'],catalog=self.catalog)

    def test_shared_guild_reuses_actual_rank_permissions_and_leader_transfer_without_forced_member_join(self):
        guild=self.store.create_guild(A,1,'Gold Goblins')['result']['guild']
        self.store.invite_guild_member(A,2,guild,B);self.store.answer_guild_invite(B,1,True)
        self.store.guild_action(A,3,guild,{'op':'GuildPublicNote','target':B,'text':'Own note'})
        self.store.guild_action(A,4,guild,{'op':'GuildLeader','target':B})
        record=self.store.snapshot()['shared']['guilds'][guild]
        self.assertEqual(record['leader'],B);self.assertEqual(record['members'][B]['note'],'Own note')
        self.store.guild_action(A,5,guild,{'op':'GuildLeave'})
        self.assertEqual(set(self.store.snapshot()['shared']['guilds'][guild]['members']),{B})
        self.store.guild_action(B,2,guild,{'op':'GuildDisband'})
        self.assertEqual(self.store.snapshot()['shared']['guilds'],{})

    def test_journal_tampering_with_wrong_after_hash_is_rejected_without_touching_targets(self):
        def fault(stage, name):
            if (stage, name) == ('replaced', 'shared-custody.pending.json'):raise OSError('stop')
        self.store.fault = fault
        with self.assertRaises(RecoveryRequired):self.send()
        path = self.root / 'shared-custody.pending.json'
        value = json.loads(path.read_text());value['targets'][0]['value']['payload']['progression']['level'] = 2
        atomic(path, value)
        before = self.files()
        with self.assertRaises(RecoveryRequired):LocalCustodyStore(self.root).recover()
        self.assertEqual(before, self.files())

    def shared_guild(self):
        guild=self.store.create_guild(A,1,'Gold Goblins')['result']['guild']
        self.store.invite_guild_member(A,2,guild,B);self.store.answer_guild_invite(B,1,True)
        return guild

    def test_shared_guild_chat_is_durable_to_actual_members_once_with_no_item_or_money_change(self):
        self.shared_guild();before=self.store.snapshot()['characters']
        outcome=self.store.send_chat(A,3,'GUILD','A real guild message',now=100)
        self.assertEqual(outcome['result']['recipients'],[B])
        shared=LocalCustodyStore(self.root).snapshot()['shared']
        self.assertNotIn(A,shared['chat']);self.assertNotIn(C,shared['chat'])
        self.assertEqual(len(shared['chat'][B]),1)
        self.assertEqual(shared['chat'][B][0]['text'],'A real guild message')
        files=self.files();self.assertTrue(self.store.send_chat(A,3,'GUILD','A real guild message',now=101)['replayed'])
        self.assertEqual(files,self.files())
        after=self.store.snapshot()['characters']
        for key in before:
            for field in ('item_instances','inventory','economy_state','character_appearance'):
                self.assertEqual(before[key]['payload'][field],after[key]['payload'][field])

    def test_shared_officer_chat_uses_actual_send_and_receive_rank_rights(self):
        guild=self.shared_guild()
        before=self.files()
        with self.assertRaisesRegex(ValueError,'GUILD_PERMISSION_DENIED'):
            self.store.send_chat(B,2,'OFFICER','Not authorized')
        self.assertEqual(before,self.files())
        self.assertEqual(self.store.send_chat(A,3,'OFFICER','Officers only')['result']['recipients'],[])
        self.store.guild_action(A,4,guild,{'op':'GuildSaveRank','rank_index':4,'name':'Initiate','rights':7})
        self.assertEqual(self.store.send_chat(A,5,'OFFICER','Readable officers')['result']['recipients'],[B])
        with self.assertRaisesRegex(ValueError,'GUILD_PERMISSION_DENIED'):
            self.store.send_chat(B,2,'OFFICER','Still cannot send')

    def test_shared_whisper_honors_recipient_real_saved_ignore_list(self):
        payload=CharacterStore(self.root).load(B)
        payload['player']['client_controls']={'local_client':{'ignores':['hERO 0']}}
        CharacterStore(self.root).save(B,payload)
        outcome=self.store.send_chat(A,1,'WHISPER','Ignored actual message',recipient=B)
        self.assertEqual(outcome['result']['recipients'],[])
        self.assertEqual(self.store.snapshot()['shared']['chat'],{})

    def test_shared_chat_ack_is_recipient_scoped_replay_safe_and_never_debits_money(self):
        self.store.send_chat(A,1,'WHISPER','Direct real message',recipient=B)
        key=self.store.snapshot()['shared']['chat'][B][0]['id']
        before=self.files()
        with self.assertRaisesRegex(ValueError,'MESSAGE_CHANGED'):self.store.acknowledge_chat(C,1,[key])
        self.assertEqual(before,self.files())
        wallets={c:self.money(c) for c in (A,B,C)}
        self.store.acknowledge_chat(B,1,[key])
        self.assertEqual(self.store.snapshot()['shared']['chat'],{})
        files=self.files();self.assertTrue(self.store.acknowledge_chat(B,1,[key])['replayed'])
        self.assertEqual(files,self.files())
        self.assertEqual(wallets,{c:self.money(c) for c in (A,B,C)})

    def test_shared_chat_full_inbox_rejects_without_dropping_previous_messages(self):
        with patch('backend.game_engine_local_custody.MAX_CHAT_INBOX',2):
            self.store.send_chat(A,1,'WHISPER','First',recipient=B)
            self.store.send_chat(A,2,'WHISPER','Second',recipient=B)
            before=self.files()
            with self.assertRaisesRegex(ValueError,'CHAT_INBOX_FULL'):
                self.store.send_chat(A,3,'WHISPER','Third',recipient=B)
            self.assertEqual(before,self.files())
        self.assertEqual([m['text'] for m in self.store.snapshot()['shared']['chat'][B]],['First','Second'])

    def test_shared_chat_committed_send_and_ack_recover_once_after_partial_disk_failure(self):
        def fail(stage,name):
            if (stage,name)==('replaced',A+'.json'):raise OSError('partial chat send')
        self.store.fault=fail
        with self.assertRaises(RecoveryRequired):self.store.send_chat(A,1,'WHISPER','Actual message',recipient=B)
        restarted=LocalCustodyStore(self.root);restarted.recover()
        self.assertTrue(restarted.send_chat(A,1,'WHISPER','Actual message',recipient=B)['replayed'])
        queue=restarted.snapshot()['shared']['chat'][B];self.assertEqual(len(queue),1)
        def fail_ack(stage,name):
            if (stage,name)==('replaced','shared-custody.json'):raise OSError('partial ack')
        restarted.fault=fail_ack
        with self.assertRaises(RecoveryRequired):restarted.acknowledge_chat(B,1,[queue[0]['id']])
        recovered=LocalCustodyStore(self.root);recovered.recover()
        self.assertEqual(recovered.snapshot()['shared']['chat'],{})
        self.assertTrue(recovered.acknowledge_chat(B,1,[queue[0]['id']])['replayed'])

    def test_character_deletion_waits_for_actual_queued_chat_delivery_ack(self):
        self.store.send_chat(A,1,'WHISPER','Actual waiting message',recipient=B)
        self.assertIn('CHAT',self.store.can_delete(A,include_history=False)['blockers'])
        self.assertIn('CHAT',self.store.can_delete(B,include_history=False)['blockers'])
        with self.assertRaisesRegex(ValueError,'DELETE_REFERENCES'):self.store.delete_character(A)
        key=self.store.snapshot()['shared']['chat'][B][0]['id']
        self.store.acknowledge_chat(B,1,[key])
        self.assertTrue(self.store.can_delete(A,include_history=False)['allowed'])
        self.assertEqual(self.store.delete_character(A)['status'],'COMMITTED')

    def test_invalid_chat_kind_text_ack_ids_and_unknown_recipient_do_not_write(self):
        before=self.files()
        for kind,message,recipient in (('SAY','Message',B),('WHISPER','',B),('WHISPER','Bad\ntext',B),('WHISPER','Unknown','d'*32)):
            with self.subTest(kind=kind,message=message),self.assertRaises(ValueError):
                self.store.send_chat(A,1,kind,message,recipient=recipient)
            self.assertEqual(before,self.files())
        for ids in ([],[True],[{}],['fake'],['chat-'+'a'*32]*2):
            with self.subTest(ids=ids),self.assertRaises(ValueError):self.store.acknowledge_chat(A,1,ids)
            self.assertEqual(before,self.files())

    def test_existing_shared_ledger_without_chat_field_upgrades_at_actual_chat_transaction(self):
        self.store.send_mail(A,1,B,catalog=self.catalog,subject='Text')
        shared=json.loads((self.root/'shared-custody.json').read_text());shared.pop('chat')
        atomic(self.root/'shared-custody.json',shared)
        self.assertNotIn('chat',self.store.snapshot()['shared'])
        self.store.send_chat(A,2,'WHISPER','New message',recipient=B)
        self.assertEqual(len(self.store.snapshot()['shared']['chat'][B]),1)


if __name__ == '__main__':unittest.main()
