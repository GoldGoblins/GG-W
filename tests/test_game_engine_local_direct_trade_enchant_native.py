"""Original Lua slot-seven/cursor APIs through Presentation and real saves."""
import copy
import json
import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QObject
from PySide6.QtGui import QGuiApplication
APP = QGuiApplication.instance() or QGuiApplication([])

from backend import game_engine_enchants as enchants
from backend.game_engine_presentation import Presentation
from tests import test_game_engine_local_direct_trade_enchant_services as fixture


class Bridge(QObject):
    def __init__(self, runtime):
        super().__init__(); self.runtime = runtime; self.calls = []

    def gameEngineClientControl(self, raw):
        row = json.loads(raw); result = self.runtime.client_control(raw)
        self.calls.append((row, copy.deepcopy(result)))
        return json.dumps(result)

    def gameEngineContainerUseItem(self, definition, instance):
        return json.dumps(self.runtime.action_use_item(definition, instance))


class NativeSavedTradeEnchant(unittest.TestCase):
    switch = fixture.SavedTradeEnchantServices.switch
    view = fixture.SavedTradeEnchantServices.view
    command_row = fixture.SavedTradeEnchantServices.command_row
    command = fixture.SavedTradeEnchantServices.command
    money = fixture.SavedTradeEnchantServices.money
    snapshot = fixture.SavedTradeEnchantServices.snapshot
    add_scrolls = fixture.SavedTradeEnchantServices.add_scrolls

    def setUp(self):
        fixture.SavedTradeEnchantServices.setUp(self)
        self.bridge = Bridge(self.runtime); self.presentation = Presentation(self.bridge, device=False)
        self.addCleanup(self.presentation.close); self.ui = self.presentation.lua
        self.assertTrue(self.presentation.full_ui); self.assertIsNotNone(self.ui)
        self.ui.execute("ENCHANT_EVENTS={};TRADE_TEST_ERRORS={};local f=CreateFrame('Frame'); "
            "for _,e in ipairs({'BIND_ENCHANT','REPLACE_ENCHANT','UI_ERROR_MESSAGE','TRADE_TARGET_ITEM_CHANGED'}) do f:RegisterEvent(e) end; "
            "f:SetScript('OnEvent',function() if event=='UI_ERROR_MESSAGE' then table.insert(TRADE_TEST_ERRORS,arg1) "
            "else table.insert(ENCHANT_EVENTS,{event,arg1,arg2}) end end)")
        self.publish()

    def publish(self):
        self.presentation.last_update = 0; self.presentation.update(self.runtime.snapshot())

    def call(self, source):
        self.ui.execute(source); requests = self.ui.request('requests')
        self.presentation._ui_requests(requests); self.publish()
        return requests

    def begin(self, *, old=False, bound=True):
        if not bound:self.runtime._item_instances[fixture.GEAR].pop('bound_to', None)
        if old:
            from backend import game_engine_gear as gear
            definition = enchants.definition('enchant.chromatic.blue')
            tables = dict(self.runtime._gear_tables, enchantments=dict(self.runtime._gear_tables['enchantments'],
                          **{definition['id']: definition}))
            self.assertTrue(gear.apply_enchant(self.runtime._item_instances[fixture.GEAR]['gear'], definition['id'], tables)[0])
        self.command('TradeOpen', target=self.second); self.publish()
        self.call('PickupInventoryItem(16) ClickTradeButton(7)')
        self.assertEqual(self.ui.evaluate('local _,_,n=GetTradePlayerItemInfo(7);return n'), [1])
        self.assertEqual(self.runtime._item_instances[fixture.GEAR]['location'], 'EQUIPPED')
        self.switch(self.second); self.publish(); self.call('BeginTrade()'); self.add_scrolls(); self.publish()

    def arm(self):
        slot = self.runtime._item_instances[fixture.SCROLL]['slot_index'] + 1
        self.call('UseContainerItem(0,' + str(slot) + ')')
        self.assertEqual(self.runtime._item_target['scroll'], fixture.SCROLL)
        self.assertEqual(self.ui.evaluate('return SpellIsTargeting()'), [1])

    def test_original_equipment_slot7_exact_duplicate_scroll_and_both_saved_accepts(self):
        self.begin(); self.assertEqual(self.ui.evaluate('local _,_,n=GetTradeTargetItemInfo(7);return n'), [1])
        self.arm(); terms = self.view()['trade']['shared_trade_terms']
        requests = self.call('ClickTargetTradeButton(7)')
        self.assertEqual([row['op'] for row in requests['services']], ['TradeEnchantPick'])
        self.assertNotEqual(self.view()['trade']['shared_trade_terms'], terms)
        self.assertEqual(self.view()['trade']['enchant_service']['scroll'], fixture.SCROLL)
        self.assertEqual(self.ui.evaluate('local _,_,_,_,_,e=GetTradeTargetItemInfo(7);return e'), ['Crimson Ember'])
        self.assertIn(fixture.SCROLL, self.runtime._item_instances); self.call('AcceptTrade()')
        self.assertIn(fixture.SCROLL, self.runtime._item_instances)
        self.switch(self.first); self.publish()
        self.assertEqual(self.ui.evaluate('local _,_,_,_,e=GetTradePlayerItemInfo(7);return e'), ['Crimson Ember'])
        self.call('AcceptTrade()')
        item = self.runtime._item_instances[fixture.GEAR]
        self.assertEqual(item['bound_to'], self.first); self.assertEqual(item['location'], 'EQUIPPED')
        self.assertEqual(item['gear']['enchantments'][0]['id'], fixture.ENCHANT)
        self.assertEqual(self.snapshot()['shared']['direct_trades'], {})
        self.assertEqual(self.ui.evaluate('return GetTradePlayerItemInfo(7),GetTradeTargetItemInfo(7)'), [None, None])
        self.assertEqual(self.ui.evaluate('return table.getn(TRADE_TEST_ERRORS)'), [0])
        self.switch(self.second)
        self.assertNotIn(fixture.SCROLL, self.runtime._item_instances)
        self.assertIn('other-provider-scroll-one', self.runtime._item_instances)

    def test_original_bind_then_replace_prompts_publish_terms_before_both_consents(self):
        with patch.dict(enchants.CATALOG[fixture.ENCHANT], {'binds': True}):
            self.begin(old=True, bound=False); original = copy.deepcopy(self.view()['trade']['target_rows'][6]['gear'])
            self.arm(); terms = self.view()['trade']['shared_trade_terms']; self.ui.execute('ENCHANT_EVENTS={}')
            self.call('ClickTargetTradeButton(7)')
            self.assertEqual(self.ui.evaluate('return ENCHANT_EVENTS[1][1]'), ['BIND_ENCHANT'])
            self.assertEqual(self.view()['trade']['shared_trade_terms'], terms); self.assertIsNone(self.view()['trade']['enchant_service'])
            self.assertEqual(self.view()['trade']['target_rows'][6]['gear'], original)
            self.call('BindEnchant()')
            self.assertEqual(self.ui.evaluate('return ENCHANT_EVENTS[2][1],ENCHANT_EVENTS[2][2],ENCHANT_EVENTS[2][3]'),
                             ['REPLACE_ENCHANT', 'Glacier Edge', 'Crimson Ember'])
            self.assertIn(fixture.SCROLL, self.runtime._item_instances); self.call('ReplaceEnchant()')
            review = self.view()['trade']['enchant_service']; self.assertTrue(review['bind']); self.assertTrue(review['replace'])
            self.assertEqual(review['old_enchant'], 'Glacier Edge')
            self.assertEqual(self.view()['trade']['target_rows'][6]['gear'], original)
            self.call('AcceptTrade()'); self.switch(self.first); self.publish(); self.call('AcceptTrade()')
            actual = self.runtime._item_instances[fixture.GEAR]
            self.assertEqual(actual['bound_to'], self.first)
            self.assertEqual([row['id'] for row in actual['gear']['enchantments']], [fixture.ENCHANT])
            self.assertEqual(self.ui.evaluate('return table.getn(TRADE_TEST_ERRORS)'), [0])

    def test_same_drain_cursor_offer_and_accept_requires_a_new_explicit_accept(self):
        self.begin(); self.arm()
        requests = self.call('ClickTargetTradeButton(7) AcceptTrade()')
        self.assertEqual([row['op'] for row in requests['services']], ['TradeEnchantPick', 'TradeConfirmChanged'])
        self.assertFalse(self.view()['trade']['player_accepted']); self.assertIn(fixture.SCROLL, self.runtime._item_instances)
        self.assertEqual(self.ui.evaluate('return TRADE_TEST_ERRORS[1]'), ['TRADE_OFFER_CHANGED_ACCEPT_AGAIN'])
        self.call('AcceptTrade()'); self.assertTrue(self.view()['trade']['player_accepted'])
        self.assertIn(fixture.SCROLL, self.runtime._item_instances)

    def test_queued_native_pick_retains_shown_scroll_and_rejects_changed_condition(self):
        self.begin(); self.arm(); self.ui.execute('ClickTargetTradeButton(7)')
        request = self.ui.request('requests')
        self.runtime._item_instances[fixture.SCROLL]['condition'] = .2
        self.presentation._ui_requests(request); self.publish()
        self.assertIsNone(self.view()['trade']['enchant_service']); self.assertIn(fixture.SCROLL, self.runtime._item_instances)
        self.assertEqual(self.ui.evaluate('return TRADE_TEST_ERRORS[1]'), ['DIRECT_TRADE_ITEM_CHANGED'])
        self.call('SpellStopTargeting()'); self.assertFalse(self.view()['item_targeting']['active'])

    def test_original_cancel_waiting_replacement_preserves_old_gear_scroll_and_terms(self):
        self.begin(old=True); original = copy.deepcopy(self.view()['trade']['target_rows'][6]['gear'])
        self.arm(); terms = self.view()['trade']['shared_trade_terms']; self.call('ClickTargetTradeButton(7)')
        self.assertEqual(self.view()['item_targeting']['stage'], 'REPLACE')
        self.call('SpellStopTargeting()')
        self.assertFalse(self.view()['item_targeting']['active']); self.assertIsNone(self.view()['trade']['enchant_service'])
        self.assertEqual(self.view()['trade']['shared_trade_terms'], terms)
        self.assertEqual(self.view()['trade']['target_rows'][6]['gear'], original)
        self.assertIn(fixture.SCROLL, self.runtime._item_instances)

    def test_original_cursor_can_consume_caster_own_bound_no_trade_scroll_for_partner_gear(self):
        self.begin(); self.runtime._item_instances[fixture.SCROLL]['bound_to'] = self.second
        self.runtime._item_catalog['items']['item.enchant_scroll'].update(tags=['NO_TRADE'], bonding=1)
        self.publish(); self.arm(); self.call('ClickTargetTradeButton(7)')
        self.assertEqual(self.view()['trade']['enchant_service']['scroll'], fixture.SCROLL)
        self.assertIn(fixture.SCROLL, self.runtime._item_instances)
        self.call('AcceptTrade()'); self.switch(self.first); self.publish(); self.call('AcceptTrade()')
        self.assertEqual(self.runtime._item_instances[fixture.GEAR]['gear']['enchantments'][0]['id'], fixture.ENCHANT)
        self.switch(self.second); self.assertNotIn(fixture.SCROLL, self.runtime._item_instances)
        self.assertIn('other-provider-scroll-one', self.runtime._item_instances)


if __name__ == '__main__':unittest.main()
