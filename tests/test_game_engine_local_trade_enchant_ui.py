"""Actual Qt trade controls using physical-item DTOs and canonical gear previews.

Authored saved-trade envelopes exercise the QML command boundary; custody and
settlement are independently verified by the real direct-trade kernel suite.
"""
import copy
import json
import os
from pathlib import Path
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_CONTROLS_STYLE', 'Basic')
from PySide6.QtCore import QObject, QMetaObject, Qt, Q_ARG, QUrl, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickItem
from PySide6.QtQuickControls2 import QQuickStyle
from shiboken6 import isValid

from backend import game_engine_enchants as enchants, game_engine_gear as gear
from backend import game_engine_items as items

PROJECT = Path(__file__).resolve().parents[1]
APP = QGuiApplication.instance() or QGuiApplication([])
QQuickStyle.setStyle('Basic')
ENCHANT = 'enchant.chromatic.red'


class Bridge(QObject):
    def __init__(self):
        super().__init__()
        self.commands = []

    @Slot(str, result=str)
    def gameEngineClientControl(self, encoded):
        self.commands.append(json.loads(encoded))
        return '{}'


class LocalTradeEnchantUI(unittest.TestCase):
    def setUp(self):
        self.engine = QQmlEngine()
        self.warnings = []
        self.engine.warnings.connect(lambda rows: self.warnings.extend(str(row) for row in rows))
        self.bridge = Bridge()
        self.component = QQmlComponent(self.engine)
        self.component.loadUrl(QUrl.fromLocalFile(str(PROJECT / 'qml/components/LocalGameServices.qml')))
        self.assertEqual(self.component.errors(), [])
        self.state = self.fixture()
        self.panel = self.component.createWithInitialProperties(dict(
            surfaceHost=self.bridge, services=self.state, inventory=[]))
        self.assertIsNotNone(self.panel, str(self.component.errors()))
        self.addCleanup(self.retire)
        APP.processEvents()

    def retire(self):
        if isValid(self.panel): self.panel.deleteLater()
        APP.processEvents()
        self.panel = self.component = None
        self.engine.deleteLater(); self.bridge.deleteLater()
        APP.processEvents()

    @staticmethod
    def fixture():
        catalog = items.catalog_from_content()
        original = next(row for row in items.starter_instances(catalog)
                        if row['instance_id'] == 'starter-iron-saber')
        before = copy.deepcopy(original['gear'])
        table = dict(gear.starter_tables(), enchantments={
            'enchant.chromatic.blue': enchants.definition('enchant.chromatic.blue'),
            ENCHANT: enchants.definition(ENCHANT)})
        assert gear.apply_enchant(before, 'enchant.chromatic.blue', table)[0]
        after = copy.deepcopy(before)
        after['enchantments'].pop(0)
        assert gear.apply_enchant(after, ENCHANT, table)[0]
        own = items.instance_view(catalog, original, include_visual=False)
        own.update(instance_id='own-equipped', name='Own equipped blade', bound=True, gear=before)
        partner = copy.deepcopy(own)
        partner.update(instance_id='partner-equipped', name='Partner equipped blade', bound=False)
        references = {row['instance_id']: dict(asset='fixture-asset-'+row['instance_id'],
            instance=row['instance_id'], quantity=1, location=row['location'], slot=-1,
            equipped_slot=row['equipped_slot'], item_hash='gear-hash-'+row['instance_id'],
            definition_hash='fixture-definition') for row in (own, partner)}
        scrolls, scroll_refs = [], {}
        for identifier in ('scroll-first', 'scroll-second'):
            ref = dict(asset='fixture-asset-'+identifier, instance=identifier, quantity=1,
                       item_hash='scroll-hash-'+identifier, definition_hash='fixture-scroll-definition')
            scroll_refs[identifier] = ref
            scrolls.append(dict(id=identifier, instance_id=identifier, enchant_id=ENCHANT,
                name=enchants.definition(ENCHANT)['name'], quantity=2, required_level=1,
                binds=False, reference=copy.deepcopy(ref)))
        service = dict(provider='self', owner='partner', target=partner['instance_id'],
            scroll='scroll-second', quantity=1, enchant_id=ENCHANT,
            name=enchants.definition(ENCHANT)['name'], required_level=1,
            replace=True, bind=False, old_enchant='Glacier Edge', preview=after)
        incoming = copy.deepcopy(service)
        incoming.update(provider='partner', owner='self', target=own['instance_id'],
                        scroll='partner-physical-scroll', bind=True)
        trade = dict(open=True, shared_trade=True, shared_trade_id='fixture-trade',
            shared_trade_owner='self', shared_trade_recipient='partner',
            shared_trade_revision=3, shared_trade_terms='fixture-frozen-terms',
            offer_revision=3, target_name='Other saved hero',
            slots={'1': 'ordinary-own'}, gear_items=[own],
            gear_references={own['instance_id']: references[own['instance_id']]},
            inventory_references={own['instance_id']: {'wrong': 'ordinary-transfer-reference'}},
            player_rows={'1': dict(name='Ordinary own item', quantity=2), '7': own},
            target_rows=[dict(name='Ordinary partner item', quantity=3), None, None, None, None, None, partner],
            enchant_target_reference=references[own['instance_id']],
            target_enchant_target_reference=references[partner['instance_id']],
            enchant_scrolls=scrolls, scroll_references=scroll_refs,
            enchant_service=service, target_enchant_service=incoming)
        return dict(session=9, trade=trade, petition=dict(registrar_open=False),
            lifecycle=dict(dead=False, ghost=False), tabard=dict(open=False, can_save=False))

    def find(self, name):
        pending, seen = [self.panel], {}
        while pending:
            node = pending.pop()
            if id(node) in seen: continue
            seen[id(node)] = node
            if node.objectName() == name: return node
            pending.extend(node.children())
            if isinstance(node, QQuickItem): pending.extend(node.childItems())
            if node.inherits('QQuickRepeater'):
                method = self.engine.newQObject(node).property('itemAt')
                for index in range(node.property('count')):
                    row = method.call([self.engine.toScriptValue(index)]).toQObject()
                    if row is not None: pending.append(row)
        return None

    def control(self, name):
        row = self.find(name)
        self.assertIsNotNone(row, name)
        return row

    def activate(self, name, index):
        picker = self.control(name)
        picker.setProperty('currentIndex', index)
        self.assertTrue(QMetaObject.invokeMethod(picker, 'activated', Qt.DirectConnection, Q_ARG('int', index)))
        APP.processEvents()
        return picker

    def click(self, name):
        control = self.control(name)
        self.assertTrue(control.property('enabled'), name)
        self.assertTrue(QMetaObject.invokeMethod(control, 'clicked', Qt.DirectConnection))
        APP.processEvents()
        return self.bridge.commands[-1]

    def publish(self, state):
        self.state = state
        self.panel.setProperty('services', state)
        APP.processEvents()

    def assert_context(self, command):
        trade = self.state['trade']
        self.assertTrue(command['shared_trade'])
        self.assertEqual(command['session'], self.state['session'])
        for key in ('id', 'owner', 'recipient', 'revision', 'terms'):
            self.assertEqual(command['shared_trade_'+key], trade['shared_trade_'+key])

    def test_nontransferred_equipped_gear_is_separate_from_both_transfer_summaries(self):
        self.assertEqual(self.control('localTradeGiveRow1').property('text'), 'Ordinary own item × 2')
        self.assertIsNone(self.find('localTradeGiveRow7'))
        summary = self.control('localTradeReceiveSummary').property('text')
        self.assertIn('Ordinary partner item × 3', summary)
        self.assertNotIn('Partner equipped blade', summary)
        self.assertIn('Own equipped blade', self.control('localTradeOwnGear').property('text'))
        self.assertIn('utrustad', self.control('localTradeOwnGear').property('text'))
        self.assertIn('Partner equipped blade', self.control('localTradePartnerGear').property('text'))
        outgoing = self.control('localTradeOutgoingEnchant').property('text')
        incoming = self.control('localTradeIncomingEnchant').property('text')
        self.assertIn('ersätter Glacier Edge', outgoing)
        self.assertIn('Crimson Ember', outgoing)
        self.assertIn('scroll-second × 1', outgoing)
        self.assertIn('ingen ny bindning', outgoing)
        self.assertIn('binder utrustningen till ägaren', incoming)
        self.assertIn('partner-physical-scroll × 1', incoming)
        self.assertIn('egenskaper:', incoming)
        self.assert_context(self.click('localTradeAccept'))
        self.assertEqual(self.warnings, [])

    def test_equipped_selection_uses_latest_gear_reference_and_slot_seven_clear(self):
        self.activate('localTradeEnchantGear', 0)
        updated = copy.deepcopy(self.state)
        updated['trade']['gear_references']['own-equipped']['item_hash'] = 'fresh-gear-hash'
        self.publish(updated)
        command = self.click('localTradeSetEnchantGear')
        self.assertEqual((command['op'], command['slot'], command['item']), ('TradeSet', 7, 'own-equipped'))
        self.assertEqual(command['shared_trade_item'], updated['trade']['gear_references']['own-equipped'])
        self.assertNotIn('wrong', command['shared_trade_item'])
        self.assert_context(command)
        command = self.click('localTradeClearEnchantGear')
        self.assertEqual((command['op'], command['slot']), ('TradeClear', 7))
        self.assert_context(command)
        self.assertEqual(self.warnings, [])

    def test_second_duplicate_scroll_survives_reorder_and_routes_exact_current_reference(self):
        picker = self.activate('localTradeEnchantScroll', 1)
        for quantity in (2, 1):
            updated = copy.deepcopy(self.state)
            updated['trade']['enchant_scrolls'].reverse()
            chosen = next(row for row in updated['trade']['enchant_scrolls'] if row['id'] == 'scroll-second')
            chosen['quantity'] = quantity
            updated['trade']['scroll_references']['scroll-second']['item_hash'] = 'current-scroll-'+str(quantity)
            self.publish(updated)
            self.assertEqual(picker.property('selectedId'), 'scroll-second')
        self.control('localTradeEnchantReplace').setProperty('checked', True)
        command = self.click('localTradeSetEnchant')
        self.assertEqual((command['op'], command['enchant_id'], command['scroll']),
                         ('TradeEnchant', ENCHANT, 'scroll-second'))
        self.assertTrue(command['replace']); self.assertFalse(command['bind'])
        self.assertEqual(command['shared_trade_scroll'], self.state['trade']['scroll_references']['scroll-second'])
        self.assert_context(command)
        self.assert_context(self.click('localTradeClearEnchant'))
        self.assertEqual(self.bridge.commands[-1]['op'], 'TradeEnchantClear')
        self.assertEqual(self.warnings, [])

    def test_binding_confirmation_expires_on_target_change_and_removed_choices_never_rebind(self):
        updated = copy.deepcopy(self.state)
        updated['trade']['enchant_scrolls'][1]['binds'] = True
        self.publish(updated)
        self.activate('localTradeEnchantScroll', 1)
        button, confirm = self.control('localTradeSetEnchant'), self.control('localTradeEnchantBind')
        self.assertFalse(button.property('enabled')); self.assertTrue(confirm.property('enabled'))
        confirm.setProperty('checked', True)
        self.assertFalse(button.property('enabled'))
        self.control('localTradeEnchantReplace').setProperty('checked', True)
        self.assertTrue(self.click('localTradeSetEnchant')['bind'])
        updated = copy.deepcopy(self.state)
        updated['trade']['target_enchant_target_reference']['item_hash'] = 'changed-target-hash'
        self.publish(updated)
        self.assertFalse(confirm.property('checked')); self.assertFalse(button.property('enabled'))
        for target_rows in ([None]*7, self.state['trade']['target_rows']):
            updated = copy.deepcopy(self.state)
            updated['trade']['target_rows'] = target_rows
            self.publish(updated)
            self.assertFalse(button.property('enabled'))
        updated = copy.deepcopy(self.state)
        updated['trade']['enchant_scrolls'] = updated['trade']['enchant_scrolls'][:1]
        self.publish(updated)
        self.assertFalse(button.property('enabled'))
        self.assertIsNone(self.control('localTradeEnchantScroll').property('selectedId'))
        self.assertEqual(self.warnings, [])

    def test_missing_custody_or_binding_policy_disables_offer_instead_of_guessing(self):
        self.activate('localTradeEnchantGear', 0)
        self.activate('localTradeEnchantScroll', 1)
        self.control('localTradeEnchantReplace').setProperty('checked', True)
        self.assertTrue(self.control('localTradeSetEnchant').property('enabled'))
        updated = copy.deepcopy(self.state)
        updated['trade']['gear_references'] = {}
        updated['trade']['scroll_references'] = {}
        self.publish(updated)
        self.assertFalse(self.control('localTradeSetEnchantGear').property('enabled'))
        self.assertFalse(self.control('localTradeSetEnchant').property('enabled'))
        updated = copy.deepcopy(self.state)
        updated['trade']['scroll_references'] = self.fixture()['trade']['scroll_references']
        del updated['trade']['enchant_scrolls'][1]['binds']
        self.publish(updated)
        self.control('localTradeEnchantReplace').setProperty('checked', True)
        self.assertFalse(self.control('localTradeSetEnchant').property('enabled'))
        self.assertEqual(self.warnings, [])

    def test_empty_permanent_slot_needs_no_replacement_and_already_bound_needs_no_new_binding(self):
        updated = copy.deepcopy(self.state)
        updated['trade']['target_rows'][6]['gear']['enchantments'] = []
        updated['trade']['target_rows'][6]['bound'] = True
        updated['trade']['enchant_scrolls'][1]['binds'] = True
        updated['trade']['target_enchant_target_reference']['item_hash'] = 'empty-bound-gear'
        self.publish(updated)
        self.activate('localTradeEnchantScroll', 1)
        self.assertFalse(self.control('localTradeEnchantReplace').property('enabled'))
        self.assertFalse(self.control('localTradeEnchantBind').property('enabled'))
        command = self.click('localTradeSetEnchant')
        self.assertFalse(command['replace']); self.assertFalse(command['bind'])
        self.assertEqual(command['scroll'], 'scroll-second')
        self.assertEqual(self.warnings, [])

    def test_original_npc_enchantment_selection_keeps_its_existing_recipe_command(self):
        updated = copy.deepcopy(self.state)
        updated['trade']['shared_trade'] = False
        updated['trade']['enchant_scrolls'] = [dict(id='original-scroll', enchant_id=ENCHANT,
                                                   name='Original physical scroll')]
        self.publish(updated)
        self.panel.setProperty('inventory', [self.state['trade']['player_rows']['7']])
        APP.processEvents()
        self.activate('localTradeEnchantGear', 0)
        command = self.click('localTradeSetEnchantGear')
        self.assertEqual((command['op'], command['slot'], command['item']), ('TradeSet', 7, 'own-equipped'))
        self.assertNotIn('shared_trade_item', command)
        self.activate('localTradeEnchantScroll', 0)
        command = self.click('localTradeSetEnchant')
        self.assertEqual(command, dict(kind='service', op='TradeEnchant', session=9, enchant_id=ENCHANT))
        self.assertEqual(self.warnings, [])


if __name__ == '__main__':
    unittest.main()
