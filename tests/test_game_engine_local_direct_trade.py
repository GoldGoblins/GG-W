"""Physical saved characters, consent, conservation and durable crash edges."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from backend import game_engine_items as items, game_engine_mmo as mmo
from backend import game_engine_local_direct_trade as direct
from backend.game_engine_local_characters import CharacterStore, atomic
from backend.game_engine_local_custody import LocalCustodyStore, RecoveryRequired, asset_id, digest

A, B, C = ('a' * 32, 'b' * 32, 'c' * 32)
ITEM = 'starter-sea-salt'


IsolatedDirectStore = LocalCustodyStore


class DirectTrade(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name) / 'characters'
        self.catalog = items.catalog_from_content()
        self.seed(self.root)
        self.store = IsolatedDirectStore(self.root)
        self.sequences = {A: 0, B: 0, C: 0}

    def seed(self, root):
        character_store = CharacterStore(root); roster = []
        for index, character in enumerate((A, B, C)):
            rows = items.starter_instances(self.catalog)
            slot = 0
            for row in rows:
                if row['location'] == 'INVENTORY' and row['owner_id'] == 'player':
                    row['slot_index'] = slot; slot += 1
                if row['instance_id'] == ITEM:row['quantity'] = 3
            payload = mmo.persistent_payload(player={}, movement_mode='WALK',
                inventory=items.inventory_counts(rows), loot_items=[], progression={'level': 1},
                editor_document={}, item_instances=rows,
                economy_state={'wallet': {'gold': 100, 'copper': index, 'revision': 0}})
            payload['character_appearance'] = {'own_character': character}
            character_store.save(character, payload)
            roster.append(dict(id=character, name='Hero ' + str(index), selection={}, level=1))
        atomic(root / 'characters.json', dict(schema='gg.local-characters.v1', characters=roster))

    def payload(self, character, store=None):
        return (store or self.store).snapshot()['characters'][character]['payload']

    def money(self, character, store=None):
        return LocalCustodyStore._money(self.payload(character, store))

    def files(self, root=None):
        return {p.name: p.read_bytes() for p in (root or self.root).glob('*.json')}

    def offer(self, store=None):
        return direct.find((store or self.store).snapshot()['shared'], A)

    def action(self, issuer, op, *, store=None, sequence=None, now=100, **fields):
        store = store or self.store
        if sequence is None:
            self.sequences[issuer] += 1; sequence = self.sequences[issuer]
        row = dict(op=op)
        if op != 'TradeOpen':row.update(direct.context(self.offer(store)))
        row.update(fields)
        return store.direct_trade_action(issuer, sequence, row, catalog=self.catalog, now=now)

    def open(self, store=None):
        return self.action(A, 'TradeOpen', store=store, target=B)

    def joined(self, store=None):
        self.open(store); self.action(B, 'TradeJoin', store=store)

    def ref(self, character, instance=ITEM, store=None):
        return direct.reference(self.payload(character, store), character, instance, self.catalog)

    def configure_exchange(self, store=None):
        self.joined(store)
        self.action(A, 'TradeSet', store=store, slot=1, item=self.ref(A, store=store))
        self.action(A, 'TradeMoney', store=store, money=123)
        self.action(B, 'TradeSet', store=store, slot=2, item=self.ref(B, store=store))
        self.action(B, 'TradeMoney', store=store, money=37)
        self.action(A, 'TradeAccept', store=store)

    def replace(self, character, change):
        store = CharacterStore(self.root, before_save=self.store.validate_save)
        payload = store.load(character); change(payload)
        store.save(character, payload)

    def test_recipient_explicit_join_required_and_offers_do_not_move_custody(self):
        before = {p: self.payload(p) for p in (A, B, C)}
        self.open(); self.action(A, 'TradeSet', slot=1, item=self.ref(A))
        saved = self.files()
        for issuer, op, fields in ((A, 'TradeAccept', {}), (B, 'TradeAccept', {}),
                                   (B, 'TradeSet', dict(slot=1, item=self.ref(B))), (A, 'TradeJoin', {})):
            with self.subTest(issuer=issuer, op=op):
                with self.assertRaisesRegex(ValueError, 'CONSENT_REQUIRED'):
                    self.action(issuer, op, **fields)
                self.assertEqual(saved, self.files())
        for p in before:self.assertEqual(before[p], self.payload(p))
        self.assertEqual(self.store.snapshot()['shared']['escrow'], {})
        self.action(B, 'TradeJoin')
        self.assertTrue(self.offer()['joined'])

    def test_two_consenting_saved_characters_exchange_exact_stacks_and_copper_once(self):
        originals = {p: next(i for i in self.payload(p)['item_instances'] if i['instance_id'] == ITEM) for p in (A, B)}
        total = sum(self.money(p) for p in (A, B, C))
        before_assets, before_money = self.store._validate(**{
            'characters': self.store.snapshot()['characters'], 'shared': self.store.snapshot()['shared']})
        self.configure_exchange()
        saved_context = direct.context(self.offer())
        self.assertEqual(self.money(A), 1_000_000)
        result = self.action(B, 'TradeAccept')
        self.assertTrue(result['result']['completed']); self.assertIsNone(self.offer())
        self.assertEqual(self.money(A), 1_000_000 - 123 + 37)
        self.assertEqual(self.money(B), 1_000_001 + 123 - 37)
        self.assertEqual(total, sum(self.money(p) for p in (A, B, C)))
        after = self.store.snapshot(); after_assets, after_money = self.store._validate(after['characters'], after['shared'])
        self.assertEqual((before_assets, before_money), (after_assets, after_money))
        for receiver, source in ((A, B), (B, A)):
            moved = next(i for i in self.payload(receiver)['item_instances'] if asset_id(receiver, i) == asset_id(source, originals[source]))
            self.assertEqual((moved['definition_id'], moved['quantity'], moved['gear']),
                             (originals[source]['definition_id'], originals[source]['quantity'], originals[source]['gear']))
            self.assertEqual(moved['owner_id'], 'player'); self.assertEqual(moved['location'], 'INVENTORY')
            self.assertEqual(CharacterStore(self.root).load(receiver)['item_instances'], self.payload(receiver)['item_instances'])
            self.assertEqual(self.payload(receiver)['character_appearance'], {'own_character': receiver})
        files = self.files(); request = dict(op='TradeAccept', **saved_context)
        replay = self.store.direct_trade_action(B, self.sequences[B], request, catalog=self.catalog, now=999)
        self.assertTrue(replay['replayed']); self.assertEqual(result['result'], replay['result']); self.assertEqual(files, self.files())
        changed = dict(request, terms='0' * 64)
        with self.assertRaisesRegex(ValueError, 'REPLAY_CHANGED'):
            self.store.direct_trade_action(B, self.sequences[B], changed, catalog=self.catalog, now=999)
        with self.assertRaisesRegex(ValueError, 'OFFER_CHANGED_OR_EXPIRED'):
            self.store.direct_trade_action(A, self.sequences[A] + 1, request, catalog=self.catalog, now=101)

    def test_changed_offer_resets_both_accepts_and_rejects_older_terms(self):
        self.joined(); self.action(A, 'TradeMoney', money=4); self.action(A, 'TradeAccept')
        stale = direct.context(self.offer()); self.assertEqual(self.offer()['accepts'][A], stale['terms'])
        self.action(B, 'TradeMoney', money=2)
        current = self.offer(); self.assertEqual(current['accepts'], {A: '', B: ''})
        files = self.files()
        with self.assertRaisesRegex(ValueError, 'OFFER_CHANGED_OR_EXPIRED'):
            self.store.direct_trade_action(B, self.sequences[B] + 1, dict(op='TradeAccept', **stale), catalog=self.catalog, now=101)
        self.assertEqual(files, self.files()); self.action(B, 'TradeAccept')
        self.assertFalse(all(self.offer()['accepts'].values()))
        self.action(A, 'TradeAccept'); self.assertEqual(self.money(A), 999998); self.assertEqual(self.money(B), 1000003)

    def test_exact_row_reference_does_not_rebind_same_template_or_changed_count(self):
        ref = self.ref(A); self.joined()
        def change(payload):
            item = next(i for i in payload['item_instances'] if i['instance_id'] == ITEM)
            item['quantity'] -= 1; payload['inventory'] = items.inventory_counts(payload['item_instances'])
        self.replace(A, change)
        files = self.files()
        with self.assertRaisesRegex(ValueError, 'ITEM_CHANGED'):
            self.action(A, 'TradeSet', slot=1, item=ref)
        self.assertEqual(files, self.files())
        foreign = self.ref(B)
        with self.assertRaisesRegex(ValueError, 'ITEM_CHANGED'):
            self.action(A, 'TradeSet', slot=1, item=foreign)

    def test_offer_pins_physical_rows_and_budget_through_actual_character_save_guard(self):
        self.joined(); self.action(A, 'TradeSet', slot=1, item=self.ref(A)); self.action(A, 'TradeMoney', money=999999)
        files = self.files()
        for change in (
                lambda p: next(i for i in p['item_instances'] if i['instance_id'] == ITEM).update(slot_index=62),
                lambda p: next(i for i in p['item_instances'] if i['instance_id'] == ITEM).update(bound_to=A),
                lambda p: LocalCustodyStore._money(p, -2)):
            with self.subTest(change=change):
                with self.assertRaisesRegex(ValueError, 'DIRECT_TRADE_(ITEM|MONEY)_CHANGED'):
                    self.replace(A, change)
                self.assertEqual(files, self.files())
        self.action(A, 'TradeClear', slot=1); self.action(A, 'TradeMoney', money=0)
        self.replace(A, lambda p: next(i for i in p['item_instances'] if i['instance_id'] == ITEM).update(slot_index=62))
        self.assertEqual(next(i for i in self.payload(A)['item_instances'] if i['instance_id'] == ITEM)['slot_index'], 62)

    def test_bounds_duplicate_whole_stack_seventh_requires_gear_and_no_partial_transfer(self):
        self.joined(); self.action(A, 'TradeSet', slot=6, item=self.ref(A))
        files = self.files()
        with self.assertRaisesRegex(ValueError, 'ALREADY_OFFERED'):
            self.action(A, 'TradeSet', slot=1, item=self.ref(A))
        for slot in (0, 7, True):
            with self.subTest(slot=slot):
                with self.assertRaises(ValueError):self.action(A, 'TradeSet', slot=slot, item=self.ref(A))
        ref = self.ref(B); ref['quantity'] = 1
        with self.assertRaisesRegex(ValueError, 'ITEM_CHANGED'):self.action(B, 'TradeSet', slot=1, item=ref)
        with self.assertRaises(ValueError):self.action(A, 'TradeMoney', money=direct.MAX_COPPER + 1)
        self.assertEqual(files, self.files())

    def test_missing_self_third_party_duplicate_pending_and_empty_offer_rejected(self):
        for target in (A, 'd' * 32, 'NPC'):
            with self.subTest(target=target):
                with self.assertRaises(ValueError):self.action(A, 'TradeOpen', target=target)
        self.joined(); files = self.files()
        with self.assertRaisesRegex(ValueError, 'EMPTY_OFFER'):self.action(A, 'TradeAccept')
        with self.assertRaisesRegex(ValueError, 'ALREADY_PENDING'):self.action(C, 'TradeOpen', target=B)
        with self.assertRaisesRegex(ValueError, 'OFFER_CHANGED_OR_EXPIRED'):self.action(C, 'TradeCancel')
        self.assertEqual(files, self.files()); self.assertEqual(direct.delete_blockers(B, {}, self.store.snapshot()['shared']), ['DIRECT_TRADE'])
        self.action(B, 'TradeCancel'); self.assertIsNone(self.offer())

    def test_bound_equipped_no_trade_and_hidden_wrapped_restrictions(self):
        payload = self.payload(A); original = next(i for i in payload['item_instances'] if i['instance_id'] == ITEM)
        for updates in (dict(bound_to=A), dict(location='EQUIPPED', equipped_slot='UTILITY'), dict(owner_id='npc')):
            candidate = copy.deepcopy(payload); next(i for i in candidate['item_instances'] if i['instance_id'] == ITEM).update(updates)
            with self.subTest(updates=updates):
                with self.assertRaises(ValueError):direct.reference(candidate, A, ITEM, self.catalog)
        definition = self.catalog['items'][original['definition_id']]
        for updates in (dict(tags=['NO_TRADE']), dict(tags=['safe'] * 17 + ['NO_TRADE']), dict(bonding=1)):
            catalog = copy.deepcopy(self.catalog); catalog['items'][original['definition_id']].update(updates)
            with self.subTest(updates=updates):
                with self.assertRaises(ValueError):direct.reference(payload, A, ITEM, catalog)
        original = items.make_instance(self.catalog, 'wrapped-inner', 'item.weapon_pistol'); original['slot_index'] = 63
        gift = items.make_instance(self.catalog, 'gift-physical', 'item.gg_wrapped_gift'); gift['slot_index'] = 63
        gift['gift'] = dict(original=original, sender='Hero 0'); payload['item_instances'].append(gift)
        self.assertEqual(direct.reference(payload, A, gift['instance_id'], self.catalog)['quantity'], 1)
        for change in (lambda i: i.update(bound_to=A), lambda i: i.update(quantity=2), lambda i: i.update(definition_id='item.gg_wrapped_gift')):
            candidate = copy.deepcopy(payload); change(candidate['item_instances'][-1]['gift']['original'])
            with self.subTest(change=change):
                with self.assertRaises(ValueError):direct.reference(candidate, A, gift['instance_id'], self.catalog)

    def test_unbound_inventory_gear_and_valid_wrapped_original_survive_whole_transfer(self):
        physical = items.make_instance(self.catalog, 'physical-gear', 'item.weapon_pistol'); physical['slot_index'] = 61
        gift = items.make_instance(self.catalog, 'gift-physical', 'item.gg_wrapped_gift'); gift['slot_index'] = 62
        gift['gift'] = dict(original=copy.deepcopy(physical), sender='Hero 0')
        def add(payload):
            payload['item_instances'] += [copy.deepcopy(physical), copy.deepcopy(gift)]
            payload['inventory'] = items.inventory_counts(payload['item_instances'])
        self.replace(A, add); self.joined()
        self.action(A, 'TradeSet', slot=1, item=self.ref(A, 'physical-gear'))
        self.action(A, 'TradeSet', slot=2, item=self.ref(A, 'gift-physical'))
        self.action(A, 'TradeAccept'); self.action(B, 'TradeAccept')
        rows = {i['instance_id']: i for i in self.payload(B)['item_instances']}
        self.assertEqual(rows['physical-gear']['gear'], physical['gear'])
        self.assertEqual(rows['gift-physical']['gift'], gift['gift'])
        self.assertFalse(rows['physical-gear'].get('bound_to'))

    def test_catalog_policy_change_requires_new_offer_not_old_acceptance(self):
        self.joined(); self.action(A, 'TradeSet', slot=1, item=self.ref(A)); self.action(A, 'TradeAccept')
        files = self.files()
        definition = next(i for i in self.payload(A)['item_instances'] if i['instance_id'] == ITEM)['definition_id']
        self.catalog['items'][definition]['tags'] += ['PRICE_POLICY_CHANGED']
        with self.assertRaisesRegex(ValueError, 'DEFINITION_CHANGED'):self.action(B, 'TradeAccept')
        self.assertEqual(files, self.files())
        self.action(A, 'TradeSet', slot=1, item=self.ref(A))
        self.assertEqual(self.offer()['accepts'], {A: '', B: ''})

    def test_insufficient_destination_space_leaves_both_assets_unchanged(self):
        def fill(payload):
            rows = payload['item_instances']; inventory = [i for i in rows if i['owner_id'] == 'player' and i['location'] == 'INVENTORY']
            used = {i['slot_index'] for i in inventory}
            for slot in sorted(set(range(items.MAX_INVENTORY_SLOTS)) - used):
                row = items.make_instance(self.catalog, 'full-' + str(slot), 'item.sea_salt'); row['slot_index'] = slot; rows.append(row)
            payload['inventory'] = items.inventory_counts(rows)
        self.replace(B, fill); self.joined(); self.action(A, 'TradeSet', slot=1, item=self.ref(A)); self.action(A, 'TradeAccept')
        files = self.files()
        with self.assertRaisesRegex(ValueError, 'INVENTORY_FULL'):self.action(B, 'TradeAccept')
        self.assertEqual(files, self.files()); self.assertEqual(self.offer()['accepts'][B], '')

    def test_receiving_wallet_cannot_overflow_even_with_real_offered_copper(self):
        self.replace(B, lambda p: p['economy_state']['wallet'].update(gold=2_000_000_000, copper=9999))
        self.joined(); self.action(A, 'TradeMoney', money=1); self.action(A, 'TradeAccept')
        files = self.files()
        with self.assertRaises(ValueError):self.action(B, 'TradeAccept')
        self.assertEqual(files, self.files()); self.assertEqual(self.offer()['accepts'][B], '')

    def test_expired_offer_cannot_commit_and_new_explicit_offer_releases_old_pins(self):
        self.configure_exchange(); stale = direct.context(self.offer()); files = self.files()
        with self.assertRaisesRegex(ValueError, 'OFFER_CHANGED_OR_EXPIRED'):
            self.store.direct_trade_action(B, self.sequences[B] + 1, dict(op='TradeAccept', **stale), catalog=self.catalog, now=701)
        self.assertEqual(files, self.files())
        result = self.action(A, 'TradeOpen', target=B, now=701)
        self.assertNotEqual(result['result']['trade'], stale['id']); self.assertFalse(self.offer()['joined'])
        self.assertEqual(self.money(A), 1_000_000)

    def test_precommit_fault_rolls_back_and_every_durable_edge_recovers_exactly_once(self):
        precommit = [('before_write', 'shared-custody.pending.json'), ('file_synced', 'shared-custody.pending.json')]
        for index, edge in enumerate(precommit + [('replaced', 'shared-custody.pending.json'), ('directory_synced', 'shared-custody.pending.json')]
                + [(stage, name) for name in (A + '.json', B + '.json', 'shared-custody.json')
                   for stage in ('before_write', 'file_synced', 'replaced', 'directory_synced')]
                + [('before_clear', 'shared-custody.pending.json'), ('journal_removed', 'shared-custody.pending.json')]):
            with self.subTest(edge=edge):
                root = Path(self.directory.name) / ('fault-' + str(index)); self.seed(root)
                store = IsolatedDirectStore(root); self.sequences = {A: 0, B: 0, C: 0}; self.configure_exchange(store)
                row = dict(op='TradeAccept', **direct.context(self.offer(store))); seq = self.sequences[B] + 1
                before = self.files(root)
                def fault(stage, name):
                    if (stage, name) == edge:raise OSError('deterministic direct-trade disk edge')
                store.fault = fault
                with self.assertRaises(OSError) as caught:
                    store.direct_trade_action(B, seq, row, catalog=self.catalog, now=101)
                committed = edge not in precommit
                self.assertEqual(isinstance(caught.exception, RecoveryRequired), committed)
                if not committed:self.assertEqual(before, self.files(root))
                restarted = IsolatedDirectStore(root); restarted.recover()
                result = restarted.direct_trade_action(B, seq, row, catalog=self.catalog, now=101)
                self.assertEqual(result['replayed'], committed)
                self.assertEqual(self.money(A, restarted), 999914); self.assertEqual(self.money(B, restarted), 1000087)
                self.assertIsNone(self.offer(restarted)); self.assertFalse((root / 'shared-custody.pending.json').exists())

    def test_proof_rejects_a_conserving_wrong_recipient_exchange(self):
        self.configure_exchange(); before = self.store.snapshot(); row = dict(op='TradeAccept', **direct.context(self.offer()))
        self.action(B, 'TradeAccept'); after = self.store.snapshot()
        request = dict(op='DIRECT_TRADE_ACTION', row=row)
        direct.prove(before['characters'], after['characters'], before['shared'], after['shared'], B, self.sequences[B], request)
        wrong = copy.deepcopy(after['characters'])
        LocalCustodyStore._money(wrong[B]['payload'], -10); LocalCustodyStore._money(wrong[C]['payload'], 10)
        # Global conservation alone would accept this; the precise transition
        # proof must reject a different recipient or different consented terms.
        self.assertEqual(self.store._validate(after['characters'], after['shared'])[1], self.store._validate(wrong, after['shared'])[1])
        with self.assertRaisesRegex(ValueError, 'DIRECT_TRADE_ENTITLEMENT'):
            direct.prove(before['characters'], wrong, before['shared'], after['shared'], B, self.sequences[B], request)

    def test_recovery_rejects_a_rehashed_conserving_but_unconsented_journal_image(self):
        self.configure_exchange(); row = dict(op='TradeAccept', **direct.context(self.offer())); sequence = self.sequences[B] + 1
        def fault(stage, name):
            if (stage, name) == ('replaced', 'shared-custody.pending.json'):raise OSError('stop before final images')
        self.store.fault = fault
        with self.assertRaises(RecoveryRequired):self.store.direct_trade_action(B, sequence, row, catalog=self.catalog, now=101)
        path = self.root / 'shared-custody.pending.json'; journal = json.loads(path.read_text())
        targets = {t['name']: t for t in journal['targets']}
        LocalCustodyStore._money(targets[A + '.json']['value']['payload'], -10)
        LocalCustodyStore._money(targets[B + '.json']['value']['payload'], 10)
        receipt = targets['shared-custody.json']['value']['receipts'][B + ':' + str(sequence)]
        for name in (A + '.json', B + '.json'):
            targets[name]['after'] = digest(targets[name]['value']); receipt['after'][name] = targets[name]['after']
        targets['shared-custody.json']['after'] = digest(targets['shared-custody.json']['value'])
        atomic(path, journal); before = self.files()
        with self.assertRaises(RecoveryRequired) as caught:LocalCustodyStore(self.root).recover()
        self.assertIn('DIRECT_TRADE_ENTITLEMENT', str(caught.exception.__cause__))
        self.assertEqual(before, self.files()); self.assertTrue(path.exists())

    def test_six_physical_slots_each_side_and_full_backpacks_can_exchange_without_merging(self):
        def fill(payload):
            used = {i.get('slot_index') for i in payload['item_instances'] if i['owner_id'] == 'player' and i['location'] == 'INVENTORY'}
            for slot in sorted(set(range(items.MAX_INVENTORY_SLOTS)) - used):
                physical = items.make_instance(self.catalog, 'full-' + str(slot), 'item.sea_salt')
                physical['slot_index'] = slot; payload['item_instances'].append(physical)
            payload['inventory'] = items.inventory_counts(payload['item_instances'])
        for character in (A, B):self.replace(character, fill)
        self.joined()
        sources = {}
        for character in (A, B):
            eligible = [i for i in self.payload(character)['item_instances'] if i['owner_id'] == 'player' and i['location'] == 'INVENTORY'][:6]
            sources[character] = {asset_id(character, i): copy.deepcopy(i) for i in eligible}
            for slot, physical in enumerate(eligible, 1):
                self.action(character, 'TradeSet', slot=slot, item=self.ref(character, physical['instance_id']))
        self.action(A, 'TradeAccept'); self.action(B, 'TradeAccept')
        for recipient, source in ((A, B), (B, A)):
            rows = self.payload(recipient)['item_instances']
            self.assertEqual(sum(i['owner_id'] == 'player' and i['location'] == 'INVENTORY' for i in rows), items.MAX_INVENTORY_SLOTS)
            for key, original in sources[source].items():
                physical = next(i for i in rows if asset_id(recipient, i) == key)
                self.assertEqual((physical['quantity'], physical['definition_id'], physical['gear']),
                                 (original['quantity'], original['definition_id'], original['gear']))
        self.assertEqual(self.store.snapshot()['shared']['escrow'], {})

    def test_actual_delete_guard_and_generic_settlement_release_only_expired_trade(self):
        self.configure_exchange()
        self.assertIn('DIRECT_TRADE', self.store.can_delete(B, include_history=False)['blockers'])
        files = self.files()
        with self.assertRaisesRegex(ValueError, 'DELETE_REFERENCES'):self.store.delete_character(B)
        self.assertEqual(files, self.files())
        self.store.settle(C, 1, now=700)
        self.assertIsNone(self.offer()); self.assertNotIn('DIRECT_TRADE', self.store.can_delete(B, include_history=False)['blockers'])
        self.assertEqual(self.money(A), 1_000_000); self.assertEqual(self.money(B), 1_000_001)


if __name__ == '__main__':unittest.main()
