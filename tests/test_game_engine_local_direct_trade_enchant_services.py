"""Saved-player slot seven through actual Runtime commands and login switches."""
import copy
import json
import time
import unittest

from backend import game_engine_items as items, game_engine_enchants as enchants, game_engine_gear as gear
from tests import test_game_engine_local_direct_trade_services as fixture

GEAR = 'starter-iron-saber'
SCROLL = 'exact-provider-scroll-two'
ENCHANT = 'enchant.chromatic.red'


class SavedTradeEnchantServices(unittest.TestCase):
    switch = fixture.SharedDirectTradeServices.switch
    view = fixture.SharedDirectTradeServices.view
    command_row = fixture.SharedDirectTradeServices.command_row
    command = fixture.SharedDirectTradeServices.command
    money = fixture.SharedDirectTradeServices.money
    snapshot = fixture.SharedDirectTradeServices.snapshot

    def setUp(self):
        fixture.SharedDirectTradeServices.setUp(self)
        self.runtime._item_instances[GEAR]['bound_to'] = self.first

    def add_scrolls(self):
        used = {row.get('slot_index') for row in self.runtime._item_instances.values()
                if row.get('owner_id') == 'player' and row.get('location') == 'INVENTORY'}
        slots = sorted(set(range(items.MAX_INVENTORY_SLOTS)) - used)
        for slot, instance in zip(slots, ('other-provider-scroll-one', SCROLL)):
            row = items.make_instance(self.runtime._item_catalog, instance, 'item.enchant_scroll')
            row.update(slot_index=slot, scroll_enchant_id=ENCHANT)
            self.runtime._item_instances[instance] = items.normalize_instance(self.runtime._item_catalog, row)
        self.runtime._inventory = items.inventory_counts(list(self.runtime._item_instances.values()))
        self.runtime._ui_snapshot_base = None

    def set_gear(self):
        ref = copy.deepcopy(self.view()['trade']['gear_references'][GEAR])
        return self.command('TradeSet', slot=7, item=GEAR, shared_trade_item=ref)

    def service(self, *, scroll=SCROLL, replace=False, bind=False):
        ref = copy.deepcopy(self.view()['trade']['scroll_references'][scroll])
        return self.command('TradeEnchant', scroll=scroll, enchant_id=ENCHANT,
                            shared_trade_scroll=ref, replace=replace, bind=bind)

    def configure(self, *, old=False):
        if old:
            definition = enchants.definition('enchant.chromatic.blue')
            table = dict(self.runtime._gear_tables, enchantments=dict(self.runtime._gear_tables['enchantments'],
                          **{definition['id']: definition}))
            self.assertTrue(gear.apply_enchant(self.runtime._item_instances[GEAR]['gear'], definition['id'], table)[0])
        self.command('TradeOpen', target=self.second); self.set_gear()
        self.switch(self.second); self.command('TradeBegin'); self.add_scrolls()

    def test_exact_scroll_service_live_views_two_logins_accepts_keep_equipped_bound_owner(self):
        self.configure(); before_scroll = copy.deepcopy(self.runtime._item_instances['other-provider-scroll-one'])
        wallet = self.money(); live_actors = len(self.runtime._individual_state['individuals'])
        value = self.view()['trade']
        self.assertEqual(value['target_rows'][6]['instance_id'], GEAR)
        self.assertEqual(value['target_rows'][6]['location'], 'EQUIPPED')
        self.assertEqual(value['enchant_scrolls'][1]['instance_id'], SCROLL)
        self.assertIs(type(value['enchant_scrolls'][1]['binds']), bool)
        self.service(); self.command('TradeMoney', money=7)
        value = self.view()['trade']; self.assertEqual(value['target_rows'][6]['enchantment'], enchants.definition(ENCHANT)['name'])
        self.assertEqual(value['enchant_service']['scroll'], SCROLL)
        self.command('TradeAccept'); self.assertIn(SCROLL, self.runtime._item_instances)
        self.assertEqual(self.money(), wallet); self.switch(self.first)
        old = copy.deepcopy(self.runtime._item_instances[GEAR]); self.assertTrue(self.view()['trade']['target_accepted'])
        result = self.command('TradeAccept')
        self.assertTrue(any(row['event'] == 'UNIT_INVENTORY_CHANGED' for row in result['client_events']))
        actual = self.runtime._item_instances[GEAR]
        self.assertEqual({k: v for k, v in actual.items() if k != 'gear'}, {k: v for k, v in old.items() if k != 'gear'})
        self.assertEqual(actual['bound_to'], self.first); self.assertEqual(actual['location'], 'EQUIPPED')
        self.assertEqual(actual['gear']['enchantments'][0]['id'], ENCHANT)
        self.assertEqual(self.snapshot()['shared']['direct_trades'], {})
        self.assertEqual(len(self.runtime._individual_state['individuals']), live_actors)
        self.switch(self.second); self.assertNotIn(SCROLL, self.runtime._item_instances)
        self.assertEqual(self.runtime._item_instances['other-provider-scroll-one'], before_scroll)
        self.assertEqual(self.money(), wallet - 7)

    def test_armed_scroll_original_replace_prompt_only_publishes_service_after_confirmation(self):
        self.configure(old=True); old_terms = self.view()['trade']['shared_trade_terms']
        self.command('EnchantOpen', item=SCROLL, shared_trade=False)
        targeting = self.view()['item_targeting']
        pick = self.command_row('TradeEnchantPick', slot=7, target_generation=targeting['generation'],
            shared_trade_target=copy.deepcopy(self.view()['trade']['target_enchant_target_reference']),
            shared_trade_scroll=copy.deepcopy(self.view()['trade']['scroll_references'][SCROLL]))
        result = self.runtime.client_control(json.dumps(pick)); self.assertNotIn('error', result)
        self.assertEqual(result['client_events'], [dict(event='REPLACE_ENCHANT', args=['Glacier Edge', 'Crimson Ember'])])
        self.assertIsNone(self.view()['trade']['enchant_service']); self.assertEqual(self.view()['trade']['shared_trade_terms'], old_terms)
        self.assertIn(SCROLL, self.runtime._item_instances)
        cursor = self.view()['item_targeting']; self.assertTrue(cursor['shared_trade'])
        self.assertEqual(cursor['shared_trade_terms'], old_terms)
        result = self.command('EnchantReplaceConfirm', shared_trade=False, target_generation=cursor['generation'])
        self.assertTrue(any(event['event'] == 'TRADE_TARGET_ITEM_CHANGED' for event in result['client_events']))
        self.assertFalse(self.view()['item_targeting']['active']); self.assertIn(SCROLL, self.runtime._item_instances)
        self.assertTrue(self.view()['trade']['enchant_service']['replace'])
        self.assertEqual(self.view()['trade']['enchant_service']['old_enchant'], 'Glacier Edge')
        self.command('TradeAccept'); self.switch(self.first); self.command('TradeAccept')
        self.assertEqual([row['id'] for row in self.runtime._item_instances[GEAR]['gear']['enchantments']], [ENCHANT])

    def test_cursor_old_source_context_or_generation_cannot_rebind_new_physical_scroll(self):
        self.configure(old=True); self.command('EnchantOpen', item=SCROLL, shared_trade=False)
        targeting = self.view()['item_targeting']
        row = self.command_row('TradeEnchantPick', slot=7, target_generation=targeting['generation'],
            shared_trade_target=copy.deepcopy(self.view()['trade']['target_enchant_target_reference']),
            shared_trade_scroll=copy.deepcopy(self.view()['trade']['scroll_references'][SCROLL]))
        changed = copy.deepcopy(row); changed['target_generation'] -= 1
        result = self.runtime.client_control(json.dumps(changed)); self.assertIn('CURSOR_CHANGED', result['error'])
        self.runtime._item_instances[SCROLL]['condition'] = .5
        result = self.runtime.client_control(json.dumps(row)); self.assertIn('ITEM_CHANGED', result['error'])
        self.runtime._item_instances[SCROLL]['condition'] = 1.0
        # Create a fresh shown reference, then change immutable offer terms
        # while the genuine replace popup waits for its response.
        row['shared_trade_scroll'] = copy.deepcopy(self.view()['trade']['scroll_references'][SCROLL])
        result = self.runtime.client_control(json.dumps(row)); self.assertNotIn('error', result)
        generation = self.view()['item_targeting']['generation']; self.command('TradeMoney', money=11)
        result = self.runtime.client_control(json.dumps(self.command_row('EnchantReplaceConfirm', shared_trade=False,
                                              target_generation=generation)))
        self.assertIn('OFFER_CHANGED', result['error']); self.assertIn(SCROLL, self.runtime._item_instances)
        self.assertIsNone(self.view()['trade']['enchant_service']); self.command('EnchantCancel', shared_trade=False, target_generation=generation)

    def test_physical_scroll_pending_confirm_and_recipe_only_source_are_rejected(self):
        self.configure(); saved = self.snapshot()
        result = self.runtime.client_control(json.dumps(self.command_row('TradeEnchant', enchant_id=ENCHANT)))
        self.assertIn('SHOWN_SCROLL_CHANGED', result['error']); self.assertEqual(saved, self.snapshot())
        self.runtime._gift_wrap = dict(item=SCROLL, slot=self.runtime._item_instances[SCROLL]['slot_index'], expires=time.time() + 60)
        ref = copy.deepcopy(self.view()['trade']['scroll_references'][SCROLL])
        result = self.runtime.client_control(json.dumps(self.command_row('TradeEnchant', enchant_id=ENCHANT,
            scroll=SCROLL, shared_trade_scroll=ref, replace=False, bind=False)))
        self.assertIn('PENDING_CONFIRMATION', result['error']); self.assertIn(SCROLL, self.runtime._item_instances)
        self.runtime._clear_wrapping_locked(); self.command('TradeCancel')

    def test_actual_uncertain_final_save_recovers_exact_owner_gear_and_one_scroll_before_login(self):
        self.configure(); self.service(); self.command('TradeAccept'); self.switch(self.first)
        failed = False
        def fault(stage, name):
            nonlocal failed
            if not failed and stage == 'replaced' and name == self.first + '.json':
                failed = True; raise OSError('actual enchant two-save edge')
        self.runtime._local_custody_store.fault = fault
        self.command('TradeAccept'); self.assertTrue(failed)
        self.assertFalse((self.root / 'shared-custody.pending.json').exists())
        self.assertEqual(self.runtime._item_instances[GEAR]['gear']['enchantments'][0]['id'], ENCHANT)
        self.assertTrue(self.session.logout(), self.session.error); self.assertTrue(self.session.enter(self.second), self.session.error)
        self.assertNotIn(SCROLL, self.runtime._item_instances); self.assertIn('other-provider-scroll-one', self.runtime._item_instances)
        self.assertTrue(self.session.logout(), self.session.error)

    def test_saved_caster_own_bound_no_trade_scroll_view_consumes_exact_instance_without_transfer(self):
        self.configure(); self.runtime._item_instances[SCROLL]['bound_to'] = self.second
        self.runtime._item_catalog['items']['item.enchant_scroll'].update(tags=['NO_TRADE'], bonding=1)
        value = self.view()['trade']
        self.assertNotIn(SCROLL, value['inventory_references']); self.assertIn(SCROLL, value['scroll_references'])
        self.service(); self.command('TradeAccept'); self.switch(self.first); self.command('TradeAccept')
        self.assertEqual(self.runtime._item_instances[GEAR]['gear']['enchantments'][0]['id'], ENCHANT)
        self.switch(self.second); self.assertNotIn(SCROLL, self.runtime._item_instances)
        self.assertIn('other-provider-scroll-one', self.runtime._item_instances)

    def test_dead_or_taxi_caster_cannot_emit_cursor_confirmation_or_change_offer_terms(self):
        self.configure(old=True); self.command('EnchantOpen', item=SCROLL, shared_trade=False)
        generation = self.view()['item_targeting']['generation']; terms = self.view()['trade']['shared_trade_terms']
        row = self.command_row('TradeEnchantPick', slot=7, target_generation=generation,
            shared_trade_target=copy.deepcopy(self.view()['trade']['target_enchant_target_reference']),
            shared_trade_scroll=copy.deepcopy(self.view()['trade']['scroll_references'][SCROLL]))
        self.runtime._combat_state['actors']['player']['alive'] = False
        result = self.runtime.client_control(json.dumps(row)); self.assertEqual(result['error'], 'PLAYER_DEFEATED')
        self.assertEqual(result.get('client_events', []), [])
        self.runtime._combat_state['actors']['player']['alive'] = True
        origin = self.runtime._lifecycle_position_locked()
        destination = self.runtime._travel_nodes_locked()[0]
        self.runtime._services['taxi_flight'] = dict(destination=destination['id'], origin=origin,
            end=dict(x=destination['x'], y=origin['y'], z=destination['z']),
            elapsed=0., duration=20., pet_number=0)
        try:
            self.runtime._restore_travel_locked()
            result = self.runtime.client_control(json.dumps(row)); self.assertEqual(result['error'], 'TAXI_IN_PROGRESS')
            self.assertEqual(result.get('client_events', []), [])
        finally:
            self.runtime._services['taxi_flight'] = None
        self.assertEqual(self.view()['trade']['shared_trade_terms'], terms)
        self.assertIn(SCROLL, self.runtime._item_instances)
        self.assertEqual(self.view()['item_targeting']['stage'], 'SELECT')
        self.command('EnchantCancel', shared_trade=False, target_generation=generation)


if __name__ == '__main__':unittest.main()
