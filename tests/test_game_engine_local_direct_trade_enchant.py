"""Real physical gear/scrolls compared with authoritative enchant calculations."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import game_engine_enchants as enchants, game_engine_gear as gear
from backend import game_engine_items as items, game_engine_mmo as mmo
from backend import game_engine_local_direct_trade as direct
from backend import game_engine_local_direct_trade_enchant as service
from backend.game_engine_local_characters import CharacterStore, atomic
from backend.game_engine_local_custody import LocalCustodyStore, RecoveryRequired, digest
from tests import test_game_engine_local_direct_trade as trade_fixture

A, B = 'a' * 32, 'b' * 32
ENCHANT = 'enchant.chromatic.red'
GEAR = 'starter-iron-saber'
SCROLL = 'exact-scroll-two'


class SavedEnchantLeaf(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'characters'
        self.catalog = items.catalog_from_content(); self.tables = gear.starter_tables()
        store = CharacterStore(self.root)
        for character in (A, B):
            rows = items.starter_instances(self.catalog)
            slot = 0
            for row in rows:
                if row['owner_id'] == 'player' and row['location'] == 'INVENTORY':
                    row['slot_index'] = slot; slot += 1
                if row['instance_id'] == GEAR:
                    row['bound_to'] = character
            for identifier in ('other-scroll-one', SCROLL):
                physical = items.make_instance(self.catalog, identifier, 'item.enchant_scroll')
                physical.update(slot_index=slot, scroll_enchant_id=ENCHANT); slot += 1; rows.append(physical)
            payload = mmo.persistent_payload(player={}, movement_mode='WALK',
                inventory=items.inventory_counts(rows), loot_items=[], progression={'level': 1},
                editor_document={}, item_instances=rows, economy_state={'wallet': {'gold': 250, 'copper': 0}})
            store.save(character, payload)
        atomic(self.root / 'characters.json', dict(schema='gg.local-characters.v1', characters=[
            dict(id=p, name='Actual ' + str(i), selection={}, level=1) for i, p in enumerate((A, B))]))
        self.store = LocalCustodyStore(self.root)
        self.characters = self.store.snapshot()['characters']; self.shared = self.store.snapshot()['shared']
        direct.apply(self.characters, self.shared, A, 1, dict(op='TradeOpen', target=B), now=100)
        self.offer = direct.find(self.shared, A)
        direct.apply(self.characters, self.shared, B, 1, dict(op='TradeJoin', **direct.context(self.offer)), now=100)

    def physical(self, owner, instance=GEAR):
        return next(row for row in self.characters[owner]['payload']['item_instances'] if row['instance_id'] == instance)

    def target(self, owner=A):
        return service.target_reference(self.characters[owner]['payload'], owner, GEAR,
                                        self.catalog, gear_tables=self.tables)

    def scroll(self, owner=B, instance=SCROLL):
        return direct.reference(self.characters[owner]['payload'], owner, instance, self.catalog)

    def configure(self, *, owner=A, provider=B, replace=False):
        service.set_target(self.characters, self.offer, owner, self.target(owner), self.catalog, gear_tables=self.tables)
        job = service.service_reference(self.characters, self.offer, provider, self.scroll(provider), ENCHANT,
                                        self.catalog, replace=replace, gear_tables=self.tables)
        service.set_service(self.characters, self.offer, provider, job, self.catalog, gear_tables=self.tables)
        self.offer['terms'] = direct.terms(self.offer)
        return job

    def accept(self):
        self.offer['accepts'] = {p: self.offer['terms'] for p in (A, B)}

    def test_non_transferred_equipped_bound_gear_uses_exact_second_duplicate_scroll(self):
        before = copy.deepcopy(self.characters); self.configure(); self.accept()
        actual_gear = copy.deepcopy(self.physical(A)['gear'])
        table = dict(self.tables, enchantments=dict(self.tables['enchantments'], **{ENCHANT: enchants.definition(ENCHANT)}))
        self.assertTrue(gear.apply_enchant(actual_gear, ENCHANT, table)[0])
        result = service.complete(self.characters, self.offer, self.catalog, gear_tables=self.tables)
        current = self.physical(A)
        original = next(row for row in before[A]['payload']['item_instances'] if row['instance_id'] == GEAR)
        self.assertEqual(current['gear'], actual_gear)
        self.assertEqual({k: v for k, v in current.items() if k != 'gear'},
                         {k: v for k, v in original.items() if k != 'gear'})
        self.assertEqual(current['location'], 'EQUIPPED'); self.assertEqual(current['bound_to'], A)
        self.assertEqual(result, [dict(owner=A, target=GEAR, provider=B, scroll=SCROLL, enchant_id=ENCHANT)])
        self.assertEqual(self.physical(B, 'other-scroll-one'), next(row for row in before[B]['payload']['item_instances']
                                                                if row['instance_id'] == 'other-scroll-one'))
        self.assertFalse(any(row['instance_id'] == SCROLL for row in self.characters[B]['payload']['item_instances']))
        self.assertEqual(self.characters[A]['payload']['economy_state'], before[A]['payload']['economy_state'])

    def test_single_accept_or_absent_recipient_join_cannot_mutate_real_assets(self):
        self.configure(); before = copy.deepcopy(self.characters)
        self.offer['accepts'][A] = self.offer['terms']
        with self.assertRaisesRegex(ValueError, 'CONSENT_REQUIRED'):
            service.complete(self.characters, self.offer, self.catalog)
        self.assertEqual(self.characters, before)
        self.accept(); self.offer['joined'] = False
        with self.assertRaisesRegex(ValueError, 'CONSENT_REQUIRED'):
            service.complete(self.characters, self.offer, self.catalog)
        self.assertEqual(self.characters, before)

    def test_no_trade_is_a_real_owner_service_but_foreign_binding_and_wrapped_target_reject(self):
        definition = self.catalog['items'][self.physical(A)['definition_id']]
        definition['tags'].append('NO_TRADE')
        self.assertEqual(self.target()['location'], 'EQUIPPED')
        original = copy.deepcopy(self.physical(A))
        for updates in (dict(bound_to=B), dict(owner_id='npc'), dict(location='GROUND'),
                        dict(definition_id='item.gg_wrapped_gift', gift={'original': original}), dict(quantity=2)):
            with self.subTest(updates=updates):
                row = self.physical(A); row.update(updates)
                with self.assertRaises(ValueError):self.target()
                row.clear(); row.update(copy.deepcopy(original))

    def test_target_reference_rejects_count_condition_equipment_and_instance_changes(self):
        ref = self.target(); original = copy.deepcopy(self.physical(A))
        for updates in (dict(quantity=2), dict(condition=.2), dict(equipped_slot='OFF_HAND'),
                        dict(instance_id='replacement-same-template')):
            with self.subTest(updates=updates):
                row = self.physical(A); row.update(updates)
                with self.assertRaises(ValueError):service.target_item(self.characters[A]['payload'], A, ref, self.catalog)
                row.clear(); row.update(copy.deepcopy(original))

    def test_exact_scroll_rejects_recipe_quantity_condition_and_foreign_source_changes(self):
        self.configure(); before = copy.deepcopy(self.physical(B, SCROLL))
        for updates in (dict(scroll_enchant_id='enchant.chromatic.blue'), dict(quantity=2),
                        dict(condition=.2), dict(owner_id='npc'), dict(slot_index=60), dict(bound_to=B)):
            with self.subTest(updates=updates):
                row = self.physical(B, SCROLL); row.update(updates)
                with self.assertRaises(ValueError):service.validate(self.characters, self.offer, self.catalog)
                row.clear(); row.update(copy.deepcopy(before))

    def test_scroll_and_target_cannot_also_be_transfer_slots(self):
        self.configure()
        self.offer['sides'][B]['slots']['1'] = self.scroll()
        with self.assertRaisesRegex(ValueError, 'ALREADY_OFFERED'):service.validate(self.characters, self.offer, self.catalog)
        self.offer['sides'][B]['slots'].clear()
        self.offer['sides'][A]['slots']['2'] = {'asset': self.target()['asset']}
        with self.assertRaisesRegex(ValueError, 'ALREADY_OFFERED'):service.validate(self.characters, self.offer, self.catalog)

    def test_legacy_sides_hash_stays_unchanged_until_service_is_explicitly_selected(self):
        previous = copy.deepcopy(self.offer); service.validate(self.characters, self.offer, self.catalog)
        self.assertEqual(previous, self.offer); self.assertEqual(previous['terms'], direct.terms(self.offer))
        self.assertFalse(service.selected(self.offer))
        service.set_target(self.characters, self.offer, A, self.target(), self.catalog)
        self.assertNotEqual(previous['terms'], direct.terms(self.offer)); self.assertTrue(service.selected(self.offer))

    def test_clear_own_target_removes_only_partner_service_and_preserves_six_slots(self):
        self.configure(); self.configure(owner=B, provider=A)
        self.offer['sides'][A]['slots']['1'] = self.scroll(A, 'other-scroll-one')
        before_service = copy.deepcopy(self.offer['sides'][A]['enchant_service'])
        service.clear_target(self.offer, A)
        self.assertIsNone(self.offer['sides'][A]['enchant_target'])
        self.assertIsNone(self.offer['sides'][B]['enchant_service'])
        self.assertEqual(self.offer['sides'][A]['enchant_service'], before_service)
        self.assertEqual(self.offer['sides'][A]['slots']['1'], self.scroll(A, 'other-scroll-one'))

    def test_category_duplicate_secondary_and_artifact_provider_level_use_authored_rules(self):
        service.set_target(self.characters, self.offer, A, self.target(), self.catalog)
        for key, expected in (('enchant.gear.vitality', 'SLOT_INVALID'),
                              ('enchant.chromatic.triad_flame', 'LEVEL_REQUIRED')):
            row = self.physical(B, SCROLL); row['scroll_enchant_id'] = key
            with self.assertRaisesRegex(ValueError, expected):
                service.service_reference(self.characters, self.offer, B, self.scroll(), key, self.catalog)
        self.physical(B, SCROLL)['scroll_enchant_id'] = ENCHANT
        target = self.physical(A); table = dict(self.tables, enchantments={ENCHANT: enchants.definition(ENCHANT),
                                       'enchant.chromatic.blue': enchants.definition('enchant.chromatic.blue')})
        self.assertTrue(gear.apply_enchant(target['gear'], ENCHANT, table)[0])
        service.set_target(self.characters, self.offer, A, self.target(), self.catalog)
        with self.assertRaisesRegex(ValueError, 'REPLACE_CONFIRMATION_REQUIRED'):
            service.service_reference(self.characters, self.offer, B, self.scroll(), ENCHANT, self.catalog)
        self.assertTrue(gear.apply_enchant(target['gear'], 'enchant.chromatic.blue', table)[0])
        service.set_target(self.characters, self.offer, A, self.target(), self.catalog)
        self.physical(B, SCROLL)['scroll_enchant_id'] = 'enchant.chromatic.blue'
        with self.assertRaisesRegex(ValueError, 'DUPLICATE'):
            service.service_reference(self.characters, self.offer, B, self.scroll(), 'enchant.chromatic.blue',
                                      self.catalog, replace=True)

    def test_permanent_replacement_must_match_the_exact_old_slot_before_any_mutation(self):
        service.set_target(self.characters, self.offer, A, self.target(), self.catalog)
        with self.assertRaisesRegex(ValueError, 'REPLACE_CONFIRMATION_REQUIRED'):
            service.service_reference(self.characters, self.offer, B, self.scroll(), ENCHANT,
                                      self.catalog, replace=True)
        table = dict(self.tables, enchantments={'enchant.chromatic.blue': enchants.definition('enchant.chromatic.blue')})
        self.assertTrue(gear.apply_enchant(self.physical(A)['gear'], 'enchant.chromatic.blue', table)[0])
        original = copy.deepcopy(self.physical(A)); service.set_target(self.characters, self.offer, A, self.target(), self.catalog)
        with self.assertRaisesRegex(ValueError, 'REPLACE_CONFIRMATION_REQUIRED'):
            service.service_reference(self.characters, self.offer, B, self.scroll(), ENCHANT, self.catalog)
        self.configure(replace=True); self.offer['accepts'][A] = self.offer['terms']
        with self.assertRaisesRegex(ValueError, 'CONSENT_REQUIRED'):
            service.complete(self.characters, self.offer, self.catalog)
        self.assertEqual(self.physical(A), original); self.assertEqual(self.physical(B, SCROLL)['quantity'], 1)

    def test_permanent_replacement_retains_secondary_and_actual_custom_socket_runeword(self):
        target = self.physical(A)
        self.tables['insertables']['rune.test_one'] = dict(id='rune.test_one', name='One', kind='RUNE', level=1,
                                                          socket_effects={'WEAPON': {'damage': 2.25, 'health': 3}})
        self.tables['insertables']['rune.test_two'] = dict(id='rune.test_two', name='Two', kind='RUNE', level=1,
                                                          socket_effects={'WEAPON': {'damage': 1.5}})
        self.tables['runewords']['runeword.custom'] = dict(id='runeword.custom', name='Actual Custom',
                sequence=['rune.test_one', 'rune.test_two'], socket_count=2, allowed_base_types=['SWORD'],
                bonuses={'crit': 3.75, 'damage': 2.5})
        for rune in ('rune.test_one', 'rune.test_two'):
            self.assertTrue(gear.insert_socket(target['gear'], rune, self.tables)[0])
        self.tables['enchantments'].update({key: enchants.definition(key) for key in
                                          ('enchant.chromatic.blue', 'enchant.chromatic.green')})
        for key in ('enchant.chromatic.blue', 'enchant.chromatic.green'):
            self.assertTrue(gear.apply_enchant(target['gear'], key, self.tables)[0])
        before = copy.deepcopy(target); self.configure(replace=True); self.accept()
        service.complete(self.characters, self.offer, self.catalog, gear_tables=self.tables)
        expected = copy.deepcopy(before['gear']); expected['enchantments'].pop(0)
        table = dict(self.tables, enchantments=dict(self.tables['enchantments'], **{ENCHANT: enchants.definition(ENCHANT)}))
        self.assertTrue(gear.apply_enchant(expected, ENCHANT, table)[0]); expected['enchantments'].insert(0, expected['enchantments'].pop())
        self.assertEqual(target['gear'], expected)
        self.assertEqual(target['gear']['sockets'], before['gear']['sockets'])
        self.assertEqual(target['gear']['runeword'], before['gear']['runeword'])
        self.assertEqual([row['id'] for row in target['gear']['enchantments']], [ENCHANT, 'enchant.chromatic.green'])

    def test_live_table_change_is_rejected_rather_than_changing_consented_socket_effects(self):
        self.assertTrue(gear.insert_socket(self.physical(A)['gear'], 'gem.ruby', self.tables)[0])
        self.configure()
        self.tables['insertables']['gem.ruby']['socket_effects']['WEAPON']['damage'] += 10
        with self.assertRaisesRegex(ValueError, 'GEAR_CHANGED'):
            service.validate(self.characters, self.offer, self.catalog, gear_tables=self.tables)

    def test_mutation_credit_covers_exact_two_assets_only_and_keeps_money_strict(self):
        before = copy.deepcopy(self.characters); self.configure(); self.accept()
        before_assets, before_money = self.store._validate(before, self.store.snapshot()['shared'])
        service.complete(self.characters, self.offer, self.catalog)
        after_assets, after_money = self.store._validate(self.characters, self.store.snapshot()['shared'])
        self.assertNotEqual(before_assets, after_assets); self.assertEqual(before_money, after_money)
        service.credit(before_assets, after_assets, before, self.characters, self.offer)
        self.assertEqual(before_assets, after_assets)
        # An unrelated physical loss remains uncovered by this bounded credit.
        unrelated = copy.deepcopy(after_assets); unrelated.pop(next(key for key in unrelated if key != self.target()['asset']))
        self.assertNotEqual(before_assets, unrelated)

    def test_two_real_services_consume_one_of_each_scroll_and_preserve_both_owners(self):
        self.configure(); self.configure(owner=B, provider=A); self.accept()
        result = service.complete(self.characters, self.offer, self.catalog, gear_tables=self.tables)
        self.assertEqual(len(result), 2)
        for owner in (A, B):
            self.assertEqual(self.physical(owner)['bound_to'], owner)
            self.assertEqual(self.physical(owner)['location'], 'EQUIPPED')
            self.assertEqual(self.physical(owner)['gear']['enchantments'][0]['id'], ENCHANT)
            self.assertEqual(self.physical(owner, 'other-scroll-one')['quantity'], 1)
            self.assertFalse(any(row['instance_id'] == SCROLL for row in self.characters[owner]['payload']['item_instances']))

    def test_authored_stackable_scroll_consumes_exactly_one_without_merging_or_losing_metadata(self):
        self.catalog['items']['item.enchant_scroll']['stack_limit'] = 3
        row = self.physical(B, SCROLL); row['quantity'] = 3; original = copy.deepcopy(row)
        self.configure(); self.accept(); service.complete(self.characters, self.offer, self.catalog)
        self.assertEqual(row, dict(original, quantity=2))
        self.assertEqual(self.physical(B, 'other-scroll-one')['quantity'], 1)

    def test_binding_recipe_requires_explicit_service_consequence_and_binds_only_actual_target_owner(self):
        definition = enchants.definition(ENCHANT); definition['binds'] = True
        self.physical(A).pop('bound_to'); real_definition = enchants.definition
        with patch.object(enchants, 'definition', side_effect=lambda key: copy.deepcopy(definition)
                          if key == ENCHANT else real_definition(key)):
            service.set_target(self.characters, self.offer, A, self.target(), self.catalog)
            with self.assertRaisesRegex(ValueError, 'BIND_CONFIRMATION_REQUIRED'):
                service.service_reference(self.characters, self.offer, B, self.scroll(), ENCHANT, self.catalog)
            job = service.service_reference(self.characters, self.offer, B, self.scroll(), ENCHANT,
                                            self.catalog, bind=True, gear_tables=self.tables)
            service.set_service(self.characters, self.offer, B, job, self.catalog)
            self.offer['terms'] = direct.terms(self.offer); self.accept()
            service.complete(self.characters, self.offer, self.catalog)
        self.assertEqual(self.physical(A)['bound_to'], A)
        self.assertEqual(self.physical(B)['bound_to'], B)

    def test_target_can_be_reselected_after_original_permanent_slot_modifier_order(self):
        table = dict(self.tables, enchantments={key: enchants.definition(key)
                                              for key in (ENCHANT, 'enchant.chromatic.blue')})
        target = self.physical(A)
        for key in ('enchant.chromatic.blue', ENCHANT):
            self.assertTrue(gear.apply_enchant(target['gear'], key, table)[0])
        target['gear']['enchantments'].insert(0, target['gear']['enchantments'].pop())
        self.assertEqual(self.target()['instance'], GEAR)

    def test_own_bound_no_trade_scroll_consumes_without_creating_transfer_authority(self):
        scroll = self.physical(B, SCROLL); scroll['bound_to'] = B
        self.catalog['items']['item.enchant_scroll'].update(tags=['NO_TRADE', 'CONSUMABLE'], bonding=1)
        with self.assertRaises(ValueError):direct.reference(self.characters[B]['payload'], B, SCROLL, self.catalog)
        ref = service.scroll_reference(self.characters[B]['payload'], B, SCROLL, self.catalog)
        self.assertEqual(set(ref), direct.REFERENCE_FIELDS)
        service.set_target(self.characters, self.offer, A, self.target(), self.catalog)
        job = service.service_reference(self.characters, self.offer, B, ref, ENCHANT, self.catalog)
        service.set_service(self.characters, self.offer, B, job, self.catalog)
        self.offer['terms'] = direct.terms(self.offer); self.accept()
        service.complete(self.characters, self.offer, self.catalog)
        self.assertEqual(self.physical(A)['gear']['enchantments'][0]['id'], ENCHANT)
        self.assertFalse(any(row['instance_id'] == SCROLL for row in self.characters[B]['payload']['item_instances']))
        self.assertEqual(self.physical(B, 'other-scroll-one')['quantity'], 1)

    def test_consumption_reference_rejects_foreign_bound_wrapped_and_non_scroll_sources(self):
        original = copy.deepcopy(self.physical(B, SCROLL))
        for updates in (dict(bound_to=A), dict(owner_id='npc'), dict(location='EQUIPPED'),
                        dict(definition_id='item.gg_wrapped_gift', gift={'original': original}), dict(kind='ITEM')):
            with self.subTest(updates=updates):
                row = self.physical(B, SCROLL); row.update(updates)
                with self.assertRaises(ValueError):service.scroll_reference(self.characters[B]['payload'], B, SCROLL, self.catalog)
                row.clear(); row.update(copy.deepcopy(original))


class SavedEnchantStore(unittest.TestCase):
    """The actual custody journal must prove both consent and exact mutation."""
    files = trade_fixture.DirectTrade.files
    payload = trade_fixture.DirectTrade.payload
    money = trade_fixture.DirectTrade.money
    offer = trade_fixture.DirectTrade.offer
    open = trade_fixture.DirectTrade.open
    joined = trade_fixture.DirectTrade.joined
    ref = trade_fixture.DirectTrade.ref
    replace = trade_fixture.DirectTrade.replace

    def setUp(self):
        self.tables = gear.starter_tables()
        trade_fixture.DirectTrade.setUp(self)

    def seed(self, root):
        trade_fixture.DirectTrade.seed(self, root)
        saves = CharacterStore(root)
        for owner in (A, B):
            payload = saves.load(owner)
            target = next(row for row in payload['item_instances'] if row['instance_id'] == GEAR)
            target['bound_to'] = owner
            for slot, instance in ((60, 'other-scroll-one'), (61, SCROLL)):
                row = items.make_instance(self.catalog, instance, 'item.enchant_scroll')
                row.update(slot_index=slot, scroll_enchant_id=ENCHANT)
                payload['item_instances'].append(row)
            payload['inventory'] = items.inventory_counts(payload['item_instances'])
            saves.save(owner, payload)

    def action(self, issuer, op, *, store=None, sequence=None, now=100, **fields):
        store = store or self.store
        if sequence is None:
            self.sequences[issuer] += 1; sequence = self.sequences[issuer]
        row = dict(op=op)
        if op != 'TradeOpen':row.update(direct.context(self.offer(store)))
        row.update(fields)
        return store.direct_trade_action(issuer, sequence, row, catalog=self.catalog,
                                         gear_tables=self.tables, now=now)

    def physical(self, owner, instance=GEAR, store=None):
        return next(row for row in self.payload(owner, store)['item_instances'] if row['instance_id'] == instance)

    def target(self, owner=A, store=None):
        return service.target_reference(self.payload(owner, store), owner, GEAR, self.catalog, gear_tables=self.tables)

    def configure(self, store=None, *, ordinary=False):
        self.joined(store)
        self.action(A, 'TradeSet', store=store, slot=7, item=self.target(A, store))
        self.action(B, 'TradeEnchant', store=store, enchant_id=ENCHANT,
                    scroll=self.ref(B, SCROLL, store), replace=False, bind=False)
        if ordinary:
            self.action(A, 'TradeSet', store=store, slot=1, item=self.ref(A, store=store))
            self.action(B, 'TradeSet', store=store, slot=6, item=self.ref(B, store=store))
            self.action(A, 'TradeMoney', store=store, money=123)
            self.action(B, 'TradeMoney', store=store, money=37)
        self.action(A, 'TradeAccept', store=store)

    def test_mixed_service_items_and_copper_commit_to_both_actual_save_files_once(self):
        gear_before = copy.deepcopy(self.physical(A)); other_scroll = copy.deepcopy(self.physical(B, 'other-scroll-one'))
        self.configure(ordinary=True); before = self.files(); context = direct.context(self.offer())
        self.assertEqual(self.physical(A), gear_before)
        result = self.action(B, 'TradeAccept')
        self.assertTrue(result['result']['completed']); self.assertEqual(len(result['result']['enchanted']), 1)
        self.assertNotEqual(before, self.files()); self.assertIsNone(self.offer())
        current = self.physical(A)
        self.assertEqual({k: v for k, v in current.items() if k != 'gear'}, {k: v for k, v in gear_before.items() if k != 'gear'})
        self.assertEqual(current['gear']['enchantments'][0]['id'], ENCHANT)
        self.assertEqual(self.physical(B, 'other-scroll-one'), other_scroll)
        self.assertFalse(any(row['instance_id'] == SCROLL for row in self.payload(B)['item_instances']))
        self.assertEqual(self.money(A), 999914); self.assertEqual(self.money(B), 1000087)
        saved = self.files(); final = dict(op='TradeAccept', **context)
        replay = self.store.direct_trade_action(B, self.sequences[B], final, catalog=self.catalog,
                                                gear_tables=self.tables, now=999)
        self.assertTrue(replay['replayed']); self.assertEqual(replay['result'], result['result']); self.assertEqual(saved, self.files())
        self.assertEqual(CharacterStore(self.root).load(A)['item_instances'], self.payload(A)['item_instances'])

    def test_changed_exact_scroll_invalidates_both_accepts_and_stale_terms_cannot_commit(self):
        self.configure(); stale = direct.context(self.offer()); unchanged_gear = copy.deepcopy(self.physical(A))
        self.action(B, 'TradeEnchant', enchant_id=ENCHANT, scroll=self.ref(B, 'other-scroll-one'), replace=False, bind=False)
        self.assertEqual(self.offer()['accepts'], {A: '', B: ''}); self.assertNotEqual(self.offer()['terms'], stale['terms'])
        saved = self.files()
        with self.assertRaisesRegex(ValueError, 'OFFER_CHANGED'):
            self.store.direct_trade_action(B, self.sequences[B] + 1, dict(op='TradeAccept', **stale),
                                          catalog=self.catalog, gear_tables=self.tables, now=100)
        self.assertEqual(saved, self.files()); self.assertEqual(self.physical(A), unchanged_gear)
        self.action(B, 'TradeAccept'); self.action(A, 'TradeAccept')
        self.assertFalse(any(row['instance_id'] == 'other-scroll-one' for row in self.payload(B)['item_instances']))
        self.assertEqual(self.physical(B, SCROLL)['quantity'], 1)

    def test_save_guard_pins_real_equipped_target_and_scroll_until_explicit_clear(self):
        self.configure(); saved = self.files()
        for owner, instance, updates in ((A, GEAR, dict(condition=.1)), (A, GEAR, dict(equipped_slot='OFF_HAND')),
                                          (B, SCROLL, dict(slot_index=59)), (B, SCROLL, dict(scroll_enchant_id='enchant.chromatic.blue'))):
            with self.subTest(owner=owner, updates=updates):
                with self.assertRaises(ValueError):
                    self.replace(owner, lambda payload: next(row for row in payload['item_instances']
                        if row['instance_id'] == instance).update(updates))
                self.assertEqual(saved, self.files())
        self.action(B, 'TradeEnchantClear')
        self.replace(B, lambda payload: next(row for row in payload['item_instances'] if row['instance_id'] == SCROLL).update(slot_index=59))
        self.action(A, 'TradeClear', slot=7)
        self.replace(A, lambda payload: next(row for row in payload['item_instances'] if row['instance_id'] == GEAR).update(condition=.1))

    def test_service_only_requires_both_fresh_accepts_and_slot_without_service_is_empty(self):
        self.joined(); self.action(A, 'TradeSet', slot=7, item=self.target()); saved = self.files()
        with self.assertRaisesRegex(ValueError, 'EMPTY_OFFER'):self.action(A, 'TradeAccept')
        self.assertEqual(saved, self.files())
        self.action(B, 'TradeEnchant', enchant_id=ENCHANT, scroll=self.ref(B, SCROLL), replace=False, bind=False)
        self.action(B, 'TradeAccept'); self.assertEqual(self.physical(A)['gear']['enchantments'], [])
        self.action(A, 'TradeAccept'); self.assertEqual(self.physical(A)['gear']['enchantments'][0]['id'], ENCHANT)

    def test_generic_transaction_cannot_use_enchant_mutation_credit(self):
        saved = self.files()
        def forged(payloads, shared):
            row = next(row for row in payloads[A]['item_instances'] if row['instance_id'] == GEAR)
            row['gear'] = service.canonical_gear(row, enchants.definition(ENCHANT))
            return dict(completed=True)
        with self.assertRaisesRegex(ValueError, 'ITEM_CONSERVATION'):
            self.store.transact(A, 1, dict(op='NOT_AN_ENCHANT_ENTITLEMENT'), [A], forged)
        self.assertEqual(saved, self.files())

    def test_precommit_rolls_back_and_every_durable_service_edge_recovers_once(self):
        precommit = [('before_write', 'shared-custody.pending.json'), ('file_synced', 'shared-custody.pending.json')]
        edges = precommit + [('replaced', 'shared-custody.pending.json'), ('directory_synced', 'shared-custody.pending.json')]
        edges += [(stage, name) for name in (A + '.json', B + '.json', 'shared-custody.json')
                  for stage in ('before_write', 'file_synced', 'replaced', 'directory_synced')]
        edges += [('before_clear', 'shared-custody.pending.json'), ('journal_removed', 'shared-custody.pending.json')]
        for index, edge in enumerate(edges):
            with self.subTest(edge=edge):
                root = Path(self.directory.name) / ('enchant-fault-' + str(index)); self.seed(root)
                store = LocalCustodyStore(root); self.sequences = {A: 0, B: 0, trade_fixture.C: 0}
                self.configure(store, ordinary=True)
                row = dict(op='TradeAccept', **direct.context(self.offer(store))); sequence = self.sequences[B] + 1
                before = self.files(root)
                def fault(stage, name):
                    if (stage, name) == edge:raise OSError('real enchant journal edge')
                store.fault = fault
                with self.assertRaises(OSError) as caught:
                    store.direct_trade_action(B, sequence, row, catalog=self.catalog, gear_tables=self.tables, now=101)
                committed = edge not in precommit; self.assertEqual(isinstance(caught.exception, RecoveryRequired), committed)
                if not committed:self.assertEqual(before, self.files(root))
                restarted = LocalCustodyStore(root); restarted.recover()
                result = restarted.direct_trade_action(B, sequence, row, catalog=self.catalog, gear_tables=self.tables, now=101)
                self.assertEqual(result['replayed'], committed); self.assertTrue(result['result']['completed'])
                self.assertIsNone(self.offer(restarted)); self.assertEqual(self.physical(A, store=restarted)['gear']['enchantments'][0]['id'], ENCHANT)
                self.assertEqual(self.physical(B, 'other-scroll-one', restarted)['quantity'], 1)
                self.assertFalse(any(item['instance_id'] == SCROLL for item in self.payload(B, restarted)['item_instances']))
                self.assertEqual(self.money(A, restarted), 999914); self.assertEqual(self.money(B, restarted), 1000087)
                self.assertFalse((root / 'shared-custody.pending.json').exists())

    def test_rehashed_journal_cannot_add_extra_enchant_consume_extra_scroll_or_change_owner(self):
        for index, kind in enumerate(('extra-enchant', 'extra-scroll', 'foreign-binding')):
            with self.subTest(kind=kind):
                root = Path(self.directory.name) / ('forged-enchant-' + str(index)); self.seed(root)
                store = LocalCustodyStore(root); self.sequences = {A: 0, B: 0, trade_fixture.C: 0}; self.configure(store)
                row = dict(op='TradeAccept', **direct.context(self.offer(store))); sequence = self.sequences[B] + 1
                def fault(stage, name):
                    if (stage, name) == ('replaced', 'shared-custody.pending.json'):raise OSError('retain actual committed journal')
                store.fault = fault
                with self.assertRaises(RecoveryRequired):
                    store.direct_trade_action(B, sequence, row, catalog=self.catalog, gear_tables=self.tables, now=101)
                path = root / 'shared-custody.pending.json'; journal = json.loads(path.read_text())
                targets = {target['name']: target for target in journal['targets']}
                gear_row = next(item for item in targets[A + '.json']['value']['payload']['item_instances'] if item['instance_id'] == GEAR)
                if kind == 'extra-enchant':gear_row['gear'] = service.canonical_gear(gear_row, enchants.definition('enchant.chromatic.blue'))
                elif kind == 'foreign-binding':gear_row['bound_to'] = B
                else:
                    payload = targets[B + '.json']['value']['payload']
                    payload['item_instances'] = [item for item in payload['item_instances'] if item['instance_id'] != 'other-scroll-one']
                    payload['inventory'] = items.inventory_counts(payload['item_instances'])
                receipt = targets['shared-custody.json']['value']['receipts'][B + ':' + str(sequence)]
                for name in (A + '.json', B + '.json'):
                    targets[name]['after'] = digest(targets[name]['value']); receipt['after'][name] = targets[name]['after']
                targets['shared-custody.json']['after'] = digest(targets['shared-custody.json']['value'])
                atomic(path, journal); unchanged = self.files(root)
                with self.assertRaises(RecoveryRequired) as caught:LocalCustodyStore(root).recover()
                self.assertIn('DIRECT_TRADE_ENTITLEMENT', str(caught.exception.__cause__))
                self.assertEqual(unchanged, self.files(root)); self.assertTrue(path.exists())

    def test_own_bound_scroll_recoverable_consumption_and_replay_leave_normal_transfer_guard_strict(self):
        self.replace(B, lambda payload: next(row for row in payload['item_instances']
            if row['instance_id'] == SCROLL).update(bound_to=B))
        self.catalog['items']['item.enchant_scroll'].update(tags=['NO_TRADE', 'CONSUMABLE'], bonding=1)
        self.joined(); self.action(A, 'TradeSet', slot=7, item=self.target())
        ref = service.scroll_reference(self.payload(B), B, SCROLL, self.catalog)
        unchanged = self.files()
        with self.assertRaisesRegex(ValueError, 'BOUND'):
            self.action(B, 'TradeSet', slot=1, item=ref)
        self.assertEqual(unchanged, self.files())
        self.action(B, 'TradeEnchant', enchant_id=ENCHANT, scroll=ref, replace=False, bind=False)
        self.action(A, 'TradeAccept'); request = dict(op='TradeAccept', **direct.context(self.offer()))
        sequence = self.sequences[B] + 1
        def fault(stage, name):
            if (stage, name) == ('replaced', 'shared-custody.pending.json'):raise OSError('bound scroll committed intent')
        self.store.fault = fault
        with self.assertRaises(RecoveryRequired):
            self.store.direct_trade_action(B, sequence, request, catalog=self.catalog, gear_tables=self.tables, now=101)
        restarted = LocalCustodyStore(self.root); restarted.recover()
        self.assertEqual(self.physical(A, store=restarted)['gear']['enchantments'][0]['id'], ENCHANT)
        self.assertFalse(any(row['instance_id'] == SCROLL for row in self.payload(B, restarted)['item_instances']))
        self.assertEqual(self.physical(B, 'other-scroll-one', restarted)['quantity'], 1)
        unchanged = self.files(); result = restarted.direct_trade_action(B, sequence, request,
            catalog=self.catalog, gear_tables=self.tables, now=102)
        self.assertTrue(result['replayed']); self.assertEqual(unchanged, self.files())


if __name__ == '__main__':unittest.main()
