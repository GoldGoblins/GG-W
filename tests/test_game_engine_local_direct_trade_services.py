"""Public runtime commands with actual saved-character switching and recovery."""
import copy
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication
from backend import game_engine_mmo as mmo, game_engine_character_creation as appearance
from backend.game_engine_local_characters import LocalCharacters
from backend.game_engine_local_custody import LocalCustodyStore, RecoveryRequired
from backend import game_engine_local_direct_trade as direct

APP = QCoreApplication.instance() or QCoreApplication([])


class SharedDirectTradeServices(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name) / 'characters'
        env = patch.dict(os.environ, {key: self.directory.name + '/' + key for key in
                                     ('XDG_STATE_HOME', 'XDG_CONFIG_HOME', 'XDG_CACHE_HOME', 'XDG_DATA_HOME')})
        env.start(); self.addCleanup(env.stop)
        for module, attribute, value in ((mmo, 'DEFAULT_STASH_PATH', Path(self.directory.name) / 'stash.json'),
                                         (appearance, 'STATE_PATH', Path(self.directory.name) / 'appearance.json')):
            mocked = patch.object(module, attribute, value); mocked.start(); self.addCleanup(mocked.stop)
        from backend.game_engine_host import GameEngineRuntime
        self.runtime = GameEngineRuntime(); self.addCleanup(self.runtime.shutdown)
        self.session = LocalCharacters(root=self.root, runtime=self.runtime); self.addCleanup(self.session.close)
        self.assertTrue(self.session.open(), self.session.error)
        self.first = self.session.rows[0]['id']
        self.assertTrue(self.session.create('Second Hero', appearance.catalog()['defaults']), self.session.error)
        self.second = self.session.rows[1]['id']
        self.assertTrue(self.session.enter(self.first), self.session.error)
        self.runtime._ensure_inventory_slots_locked()

    def switch(self, character):
        self.assertTrue(self.session.logout(), self.session.error)
        self.assertTrue(self.session.enter(character), self.session.error)
        self.runtime._ensure_inventory_slots_locked()

    def view(self):
        return self.runtime._services_view_locked()

    def command_row(self, op, **fields):
        row = dict(op=op, kind='service', session=self.runtime._service_generation, shared_trade=True)
        if op != 'TradeOpen':
            value = self.view()['trade']
            row.update({key: copy.deepcopy(value[key]) for key in value if key.startswith('shared_trade_')})
        row.update(fields)
        return row

    def command(self, op, **fields):
        result = self.runtime.client_control(json.dumps(self.command_row(op, **fields)))
        self.assertNotIn('error', result)
        return result

    def item(self):
        return next(i for i in self.runtime._item_instances.values() if i['owner_id'] == 'player'
                    and i['location'] == 'INVENTORY' and i['definition_id'] == 'item.sea_salt')

    def set_item(self, slot=1):
        physical = self.item(); ref = copy.deepcopy(self.view()['trade']['inventory_references'][physical['instance_id']])
        return self.command('TradeSet', slot=slot, item=physical['instance_id'], shared_trade_item=ref)

    def money(self):
        return self.runtime._service_money_locked()

    def snapshot(self):
        return self.runtime._local_custody_store.snapshot()

    def test_saved_recipient_switch_join_two_accepts_transfer_actual_item_and_money(self):
        before_item = copy.deepcopy(self.item()); origin_character = self.first
        first_money = self.money(); original_actor_count = len(self.runtime._individual_state['individuals'])
        self.command('TradeOpen', target='Second Hero'); self.set_item(slot=6); self.command('TradeMoney', money=51)
        self.assertTrue(self.view()['trade']['open']); self.assertFalse(self.view()['trade']['pending'])
        self.assertIn(before_item['instance_id'], self.runtime._item_instances)
        self.switch(self.second)
        pending = self.view()['trade']; self.assertTrue(pending['pending']); self.assertFalse(pending['open'])
        self.assertIsNone(pending['target_rows'][0]); self.assertEqual(pending['target_rows'][5]['quantity'], before_item['quantity'])
        second_money = self.money(); self.command('TradeBegin')
        self.assertTrue(self.view()['trade']['open']); self.assertFalse(self.view()['trade']['pending'])
        self.command('TradeMoney', money=7); self.command('TradeAccept')
        self.assertTrue(self.view()['trade']['player_accepted']); self.assertFalse(self.view()['trade']['target_accepted'])
        self.switch(self.first)
        self.assertTrue(self.view()['trade']['target_accepted']); self.assertEqual(self.view()['trade']['target_money'], 7)
        result = self.command('TradeAccept')
        self.assertTrue(any(e['event'] == 'TRADE_CLOSED' for e in result['client_events']))
        self.assertNotIn(before_item['instance_id'], self.runtime._item_instances)
        self.assertEqual(self.money(), first_money - 51 + 7)
        self.assertEqual(self.snapshot()['shared']['direct_trades'], {})
        self.assertEqual(len(self.runtime._individual_state['individuals']), original_actor_count)
        self.switch(self.second)
        received = next(i for i in self.runtime._item_instances.values() if i.get('custody_origin', {}).get('character') == origin_character)
        self.assertEqual((received['definition_id'], received['quantity'], received['gear']),
                         (before_item['definition_id'], before_item['quantity'], before_item['gear']))
        self.assertEqual(self.money(), second_money + 51 - 7)
        self.assertNotEqual(received['instance_id'], before_item['instance_id'])
        self.assertTrue(self.session.logout(), self.session.error)

    def test_current_active_recipient_session_required_and_offer_edits_clear_both_accepts(self):
        self.command('TradeOpen', target=self.second); self.command('TradeMoney', money=9)
        request = self.command_row('TradeAccept')
        result = self.runtime.client_control(json.dumps(request)); self.assertIn('CONSENT_REQUIRED', result['error'])
        self.switch(self.second); self.command('TradeJoin'); self.command('TradeAccept')
        self.switch(self.first); old = self.command_row('TradeAccept')
        self.command('TradeMoney', money=11)
        self.assertFalse(self.view()['trade']['player_accepted']); self.assertFalse(self.view()['trade']['target_accepted'])
        result = self.runtime.client_control(json.dumps(old)); self.assertIn('OFFER_CHANGED', result['error'])
        bad = self.command_row('TradeAccept'); bad['session'] -= 1
        result = self.runtime.client_control(json.dumps(bad)); self.assertIn('WINDOW_CHANGED', result['error'])
        self.command('TradeCancel')

    def test_frozen_shown_source_pending_binding_and_invalid_enchant_sources_reject_without_transfer(self):
        self.command('TradeOpen', target=self.second)
        row = self.command_row('TradeSet', slot=1, item=self.item()['instance_id'],
            shared_trade_item=copy.deepcopy(self.view()['trade']['inventory_references'][self.item()['instance_id']]))
        self.item()['condition'] = .25
        result = self.runtime.client_control(json.dumps(row)); self.assertIn('ITEM_CHANGED', result['error'])
        current = self.command_row('TradeSet', slot=1, item=self.item()['instance_id'],
            shared_trade_item=copy.deepcopy(self.view()['trade']['inventory_references'][self.item()['instance_id']]))
        self.runtime._gift_wrap = dict(item=self.item()['instance_id'], slot=self.item()['slot_index'], expires=time.time() + 60)
        result = self.runtime.client_control(json.dumps(current)); self.assertIn('ITEM_PENDING_CONFIRMATION', result['error'])
        self.runtime._clear_wrapping_locked()
        before = self.snapshot()
        for op, fields, expected in (('TradeSet', dict(slot=7, item=self.item()['instance_id']), 'SHOWN_ITEM_CHANGED'),
                           ('TradeEnchant', dict(enchant_id='fake'), 'SHOWN_SCROLL_CHANGED'),
                           ('TradeTarget', dict(item=self.item()['instance_id']), 'SAVED_ITEMS_ONLY')):
            with self.subTest(op=op):
                result = self.runtime.client_control(json.dumps(self.command_row(op, **fields)))
                self.assertIn(expected, result['error'])
        self.assertEqual(before, self.snapshot()); self.command('TradeCancel')

    def test_public_replay_does_not_restore_older_player_position_or_duplicate_final_exchange(self):
        self.command('TradeOpen', target=self.second); self.command('TradeMoney', money=13)
        self.switch(self.second); self.command('TradeJoin'); self.command('TradeAccept')
        self.switch(self.first)
        sequence = self.snapshot()['shared']['sequences'].get(self.first, 0) + 1
        final = self.command_row('TradeAccept', custody_sequence=sequence)
        result = self.runtime.client_control(json.dumps(final)); self.assertNotIn('error', result)
        before_money = self.money(); before_files = {p.name: p.read_bytes() for p in self.root.glob('*.json')}
        self.runtime._x[0] = 36.
        replay = self.runtime.client_control(json.dumps(final)); self.assertNotIn('error', replay)
        self.assertEqual(replay.get('client_events', []), []); self.assertEqual(self.money(), before_money); self.assertEqual(self.runtime._x[0], 36.)
        self.assertEqual(before_files, {p.name: p.read_bytes() for p in self.root.glob('*.json')})
        self.assertEqual(self.snapshot()['shared']['direct_trades'], {})

    def test_durable_partial_exchange_recovers_before_save_and_switch(self):
        self.command('TradeOpen', target=self.second); self.set_item(); self.command('TradeMoney', money=15)
        self.switch(self.second); self.command('TradeJoin'); self.command('TradeAccept'); self.switch(self.first)
        failed = False
        def fault(stage, name):
            nonlocal failed
            if not failed and stage == 'replaced' and name == self.first + '.json':
                failed = True; raise OSError('actual shared trade partial-save edge')
        self.runtime._local_custody_store.fault = fault
        result = self.command('TradeAccept'); self.assertTrue(failed)
        self.assertTrue(any(e['event'] == 'TRADE_CLOSED' for e in result['client_events']))
        self.assertFalse((self.root / 'shared-custody.pending.json').exists()); self.assertEqual(self.snapshot()['shared']['direct_trades'], {})
        self.assertTrue(self.session.logout(), self.session.error)
        self.assertTrue(self.session.enter(self.second), self.session.error)
        self.assertEqual(sum(i.get('custody_origin', {}).get('character') == self.first for i in self.runtime._item_instances.values()), 1)

    def test_explicit_shared_selector_rejects_npc_while_original_npc_window_path_remains_usable(self):
        result = self.runtime.client_control(json.dumps(self.command_row('TradeOpen', target='npc-does-not-exist')))
        self.assertIn('OTHER_CHARACTER_REQUIRED', result['error'])
        self.assertIsNone(direct.find(self.snapshot()['shared'], self.first))
        with self.runtime._lock:
            self.assertIsNone(self.runtime._shared_direct_trade_command_locked(dict(op='TradeOpen', target='npc'), self.runtime._shared_custody_locked()))
        self.command('TradeOpen', target=self.second)
        result = self.runtime.client_control(json.dumps(dict(kind='service', op='TradeOpen',
            session=self.runtime._service_generation, target='npc')))
        self.assertIn('OTHER_OFFER_PENDING', result['error'])
        self.command('TradeCancel')


if __name__ == '__main__':unittest.main()
