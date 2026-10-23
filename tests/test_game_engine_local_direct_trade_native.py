"""Original Lua trade APIs over explicit real saved-character handoffs."""
import copy
import json
import unittest

from backend.game_engine_adapter_gameplay import GameplayViews
from backend.game_engine_adapter_ui import GgEngineUI
from tests import test_game_engine_local_direct_trade_services as fixture


class NativeSharedDirectTrade(unittest.TestCase):
    switch = fixture.SharedDirectTradeServices.switch
    view = fixture.SharedDirectTradeServices.view
    command_row = fixture.SharedDirectTradeServices.command_row
    command = fixture.SharedDirectTradeServices.command
    item = fixture.SharedDirectTradeServices.item
    money = fixture.SharedDirectTradeServices.money
    snapshot = fixture.SharedDirectTradeServices.snapshot

    def setUp(self):
        fixture.SharedDirectTradeServices.setUp(self)
        self.ui = GgEngineUI(clock=100); self.addCleanup(self.ui.close)
        self.gameplay = GameplayViews(); self.publish()

    def publish(self):
        snapshot = self.runtime.snapshot(); data = self.gameplay.update(snapshot)
        self.ui.publish(snapshot['player'], False, 100, 100, name=self.runtime._local_character_name, **data)
        return snapshot

    def call(self, source, errors=()):
        self.ui.execute(source); requests = self.ui.request('requests'); actual_errors = []
        for request in requests.get('services', []):
            row = self.gameplay.services.route(request, self.gameplay.inventory_refs, self.gameplay.equipment_refs)
            result = self.runtime.client_control(json.dumps(row))
            if 'error' in result:actual_errors.append(result['error'])
            else:self.gameplay.update(self.runtime.snapshot())
        self.assertEqual(actual_errors, list(errors))
        self.publish()
        return requests

    def open(self):
        self.command('TradeOpen', target=self.second); self.publish()

    def test_original_cursor_slot_six_getters_and_both_real_money_sides_then_exact_exchange(self):
        item = copy.deepcopy(self.item()); first_money = self.money()
        self.open()
        self.assertEqual(self.ui.evaluate('return UnitName("npc"),UnitExists("npc"),UnitIsConnected("npc"),UnitIsVisible("npc"),UnitIsDead("npc")'),
                         ['Second Hero', 1, None, None, None])
        target = self.view()['trade']['target_profile']
        self.assertEqual(self.ui.evaluate('return UnitLevel("npc"),UnitClass("npc")'),
                         [target['level'], target['class_name'], target['class_file']])
        self.assertEqual(self.ui.evaluate('return UnitIsPlayer("npc"),CheckInteractDistance("npc",2),UnitCanAttack("player","npc")'),
                         [1, None, None])
        self.call('PickupContainerItem(0,' + str(item['slot_index'] + 1) + ') ClickTradeButton(6)')
        self.assertEqual(self.ui.evaluate('local _,_,n=GetTradePlayerItemInfo(6); return n'), [item['quantity']])
        self.assertEqual(self.ui.evaluate('return GetTradePlayerItemInfo(1),GetTradePlayerItemInfo(7)'), [None, None])
        self.call('SetTradeMoney(23)')
        self.assertEqual(self.ui.evaluate('return GetPlayerTradeMoney(),GetTargetTradeMoney()'), [23, 0])
        self.switch(self.second); self.publish(); self.call('BeginTrade()')
        self.assertEqual(self.ui.evaluate('local _,_,n=GetTradeTargetItemInfo(6); return n'), [item['quantity']])
        self.assertEqual(self.ui.evaluate('return GetTradeTargetItemInfo(1),GetTradeTargetItemInfo(7)'), [None, None])
        self.assertEqual(self.ui.evaluate('return GetPlayerTradeMoney(),GetTargetTradeMoney()'), [0, 23])
        second_money = self.money(); self.call('SetTradeMoney(5)'); self.call('AcceptTrade()')
        self.assertEqual(self.money(), second_money)
        self.switch(self.first); self.publish()
        self.assertEqual(self.ui.evaluate('return GetPlayerTradeMoney(),GetTargetTradeMoney()'), [23, 5])
        self.call('AcceptTrade()')
        self.assertFalse(self.view()['trade']['open']); self.assertEqual(self.money(), first_money - 23 + 5)
        self.assertEqual(self.ui.evaluate('return GetPlayerTradeMoney(),GetTargetTradeMoney()'), [0, 0])
        self.assertEqual(self.ui.evaluate('return UnitName("npc"),UnitExists("npc")'), [None, None])
        self.assertEqual(self.snapshot()['shared']['direct_trades'], {})
        self.switch(self.second)
        received = next(i for i in self.runtime._item_instances.values() if i.get('custody_origin', {}).get('character') == self.first)
        self.assertEqual(received['quantity'], item['quantity']); self.assertEqual(self.money(), second_money + 23 - 5)

    def test_original_accept_event_receives_current_data_and_stable_publication_is_quiet(self):
        self.ui.execute('local f=CreateFrame("Frame"); f:RegisterEvent("TRADE_SHOW"); f:RegisterEvent("TRADE_ACCEPT_UPDATE"); '
            'f:SetScript("OnEvent",function() GG_TRADE_EVENTS=GG_TRADE_EVENTS or {}; '
            'table.insert(GG_TRADE_EVENTS,{event,arg1,arg2,GetPlayerTradeMoney(),GetTargetTradeMoney(),UnitName("npc")}) end)')
        self.open(); self.call('SetTradeMoney(31)')
        self.assertEqual(self.ui.evaluate('return GG_TRADE_EVENTS[1][1],GG_TRADE_EVENTS[1][6]'), ['TRADE_SHOW', 'Second Hero'])
        self.switch(self.second); self.publish(); self.call('BeginTrade()')
        self.ui.execute('GG_TRADE_EVENTS={}')
        self.call('AcceptTrade()')
        self.assertEqual(self.ui.evaluate('return GG_TRADE_EVENTS[1][1],GG_TRADE_EVENTS[1][2],GG_TRADE_EVENTS[1][3],GG_TRADE_EVENTS[1][4],GG_TRADE_EVENTS[1][5]'),
                         ['TRADE_ACCEPT_UPDATE', 1, 0, 0, 31])
        self.ui.execute('GG_TRADE_EVENTS={}')
        self.publish(); self.publish()
        self.assertEqual(self.ui.evaluate('return table.getn(GG_TRADE_EVENTS)'), [0])
        self.call('CancelTradeAccept()')
        self.assertEqual(self.ui.evaluate('return GG_TRADE_EVENTS[1][1],GG_TRADE_EVENTS[1][2],GG_TRADE_EVENTS[1][3]'), ['TRADE_ACCEPT_UPDATE', 0, 0])
        self.call('CancelTrade()'); self.assertEqual(self.snapshot()['shared']['direct_trades'], {})

    def test_original_coalesced_edit_accept_requires_later_explicit_confirmation(self):
        self.open(); self.switch(self.second); self.publish(); self.call('BeginTrade()')
        before = self.money()
        requests = self.call('SetTradeMoney(11) AcceptTrade()', errors=('TRADE_OFFER_CHANGED_ACCEPT_AGAIN',))
        self.assertEqual([r['op'] for r in requests['services']], ['TradeMoney', 'TradeConfirmChanged'])
        self.assertFalse(self.view()['trade']['player_accepted']); self.assertFalse(self.view()['trade']['target_accepted'])
        self.assertEqual(self.money(), before); self.call('AcceptTrade()')
        self.assertTrue(self.view()['trade']['player_accepted']); self.assertEqual(self.money(), before)
        self.call('CloseTrade()'); self.assertEqual(self.snapshot()['shared']['direct_trades'], {})

    def test_root_service_view_freezes_exact_cursor_reference_and_rejects_non_gear_slot_seven(self):
        self.open(); item = self.item()
        self.ui.execute('PickupContainerItem(0,' + str(item['slot_index'] + 1) + ') ClickTradeButton(1)')
        request = self.ui.request('requests')['services'][0]
        row = self.gameplay.services.route(request, self.gameplay.inventory_refs, self.gameplay.equipment_refs)
        self.assertEqual(row['shared_trade_item']['instance'], item['instance_id'])
        item['condition'] = .2
        result = self.runtime.client_control(json.dumps(row)); self.assertIn('ITEM_CHANGED', result['error'])
        self.publish(); before = copy.deepcopy(self.snapshot()['shared']['direct_trades'])
        self.call('PickupContainerItem(0,' + str(item['slot_index'] + 1) + ') ClickTradeButton(7)', errors=('DIRECT_TRADE_SHOWN_ITEM_CHANGED',))
        self.assertEqual(before, self.snapshot()['shared']['direct_trades']); self.call('CancelTrade()')


if __name__ == '__main__':unittest.main()
