"""Freeze the displayed physical gear and scroll before dispatching trade services."""
import copy
import unittest

from backend.game_engine_adapter_service_views import ServiceViews


class TradeSelection(unittest.TestCase):
    def setUp(self):
        self.views = ServiceViews(lambda value: value)
        self.gear = dict(asset='gear-asset', instance='equipped-blade', quantity=1,
                         location='EQUIPPED', slot=-1, equipped_slot='MAIN_HAND',
                         item_hash='shown-item', definition_hash='shown-definition')
        self.scroll = dict(asset='scroll-asset', instance='scroll-b', quantity=2,
                           location='INVENTORY', slot=8, item_hash='scroll-hash')
        self.views.value = dict(session=9, trade=dict(shared_trade=True,
            shared_trade_id='offer', shared_trade_owner='owner', shared_trade_recipient='recipient',
            shared_trade_revision=4, shared_trade_terms='shown-terms',
            gear_references={'equipped-blade': copy.deepcopy(self.gear)},
            inventory_references={'normal-stack': {'instance': 'normal-stack', 'slot': 2}},
            scroll_references={'scroll-a': dict(self.scroll, instance='scroll-a', slot=7),
                               'scroll-b': copy.deepcopy(self.scroll)},
            target_enchant_target_reference=dict(self.gear, instance='partner-blade')),
            item_targeting=dict(generation=12, scroll='scroll-b'))

    def route(self, **request):
        return self.views.route(request, {3: (0, 'normal-stack'), 9: (0, 'equipped-blade')},
                                {16: 'equipped-blade'})

    def test_equipped_slot_seven_keeps_both_equipment_identity_and_offer_pin(self):
        row = self.route(op='TradeSet', slot=7, source=[-100, 16])
        self.assertEqual(row['item'], 'equipped-blade')
        self.assertEqual(row['shared_trade_item'], self.gear)
        self.assertEqual((row['shared_trade_revision'], row['shared_trade_terms']), (4, 'shown-terms'))
        self.views.value['trade']['gear_references']['equipped-blade']['item_hash'] = 'changed'
        self.assertEqual(row['shared_trade_item']['item_hash'], 'shown-item')

    def test_backpack_slot_seven_uses_service_gear_reference(self):
        self.views.value['trade']['gear_references']['equipped-blade'].update(location='INVENTORY', slot=8)
        row = self.route(op='TradeSet', slot=7, source=[0, 9])
        self.assertEqual(row['shared_trade_item']['location'], 'INVENTORY')
        self.assertEqual(row['shared_trade_item']['slot'], 8)

    def test_equipped_gear_cannot_enter_the_six_transfer_slots(self):
        for slot in range(1, 7):
            with self.subTest(slot=slot), self.assertRaisesRegex(ValueError, 'SERVICE_BACKPACK_SOURCE_REQUIRED'):
                self.route(op='TradeSet', slot=slot, source=[-100, 16])
        row = self.route(op='TradeSet', slot=6, source=[0, 3])
        self.assertEqual(row['shared_trade_item'], {'instance': 'normal-stack', 'slot': 2})

    def test_same_recipe_scroll_choices_keep_exact_selected_physical_instance(self):
        row = self.route(op='TradeEnchant', scroll='scroll-b', enchant_id='same-recipe')
        self.assertEqual(row['shared_trade_scroll'], self.scroll)
        self.views.value['trade']['scroll_references']['scroll-b']['quantity'] = 1
        self.assertEqual(row['shared_trade_scroll']['quantity'], 2)
        missing = self.route(op='TradeEnchant', scroll='missing', enchant_id='same-recipe')
        self.assertIsNone(missing['shared_trade_scroll'])

    def test_armed_target_pick_freezes_partner_gear_scroll_and_cursor_generation(self):
        row = self.route(op='TradeEnchantPick', slot=7)
        self.assertEqual(row['target_generation'], 12)
        self.assertEqual(row['shared_trade_target']['instance'], 'partner-blade')
        self.assertEqual(row['shared_trade_scroll']['instance'], 'scroll-b')
        self.views.value['trade']['target_enchant_target_reference']['item_hash'] = 'later'
        self.assertEqual(row['shared_trade_target']['item_hash'], 'shown-item')

    def test_cursor_confirmation_retains_its_pending_offer_instead_of_new_displayed_offer(self):
        pending = self.views.value['item_targeting']
        pending.update(shared_trade=True, shared_trade_id='pending-offer', shared_trade_owner='pending-owner',
                       shared_trade_recipient='pending-recipient', shared_trade_revision=2, shared_trade_terms='pending-terms')
        for op in ('EnchantBindConfirm', 'EnchantReplaceConfirm', 'EnchantCancel'):
            row = self.route(op=op)
            self.assertEqual(row['target_generation'], 12)
            self.assertEqual((row['shared_trade_id'], row['shared_trade_revision'], row['shared_trade_terms']),
                             ('pending-offer', 2, 'pending-terms'))
        self.assertEqual(self.views.value['trade']['shared_trade_id'], 'offer')

    def test_original_owned_enchant_does_not_acquire_shared_trade_authority(self):
        row = self.route(op='EnchantPick', source=[-100, 16])
        self.assertEqual(row['item'], 'equipped-blade')
        self.assertEqual(row['target_generation'], 12)
        self.assertNotIn('shared_trade', row)
        self.assertNotIn('shared_trade_item', row)
        self.assertNotIn('shared_trade', self.route(op='EnchantReplaceConfirm'))


if __name__ == '__main__':
    unittest.main()
