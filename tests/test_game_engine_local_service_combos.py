"""Actual retained Qt service pickers across independently authored snapshots.

Offscreen components exercise native ComboBox models and activation signals;
full LocalGameServices commands go through its real QML handler. No world/GPU.
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
from PySide6.QtQuick import QQuickItem  # Register the concrete Controls wrappers.
from PySide6.QtQuickControls2 import QQuickStyle
from shiboken6 import delete, isValid

PROJECT = Path(__file__).resolve().parents[1]
APP = QGuiApplication.instance() or QGuiApplication([])
QQuickStyle.setStyle('Basic')


class ServiceBridge(QObject):
    def __init__(self):
        super().__init__()
        self.commands = []

    @Slot(str, result=str)
    def gameEngineClientControl(self, encoded):
        self.commands.append(json.loads(encoded))
        return '{}'


class LocalServiceCombos(unittest.TestCase):
    def setUp(self):
        self.engine = QQmlEngine()
        self.components, self.roots, self.warnings = [], [], []
        self.engine.warnings.connect(lambda rows: self.warnings.extend(str(row) for row in rows))
        self.bridge = ServiceBridge()
        self.addCleanup(self.retire)

    def retire(self):
        for root in self.roots:
            if isValid(root): root.deleteLater()
        APP.processEvents()
        self.components.clear()
        self.roots.clear()
        self.engine.deleteLater()
        self.bridge.deleteLater()
        APP.processEvents()

    def component(self, name, properties):
        component = QQmlComponent(self.engine)
        component.loadUrl(QUrl.fromLocalFile(str(PROJECT / 'qml/components' / name)))
        self.assertEqual(component.errors(), [])
        root = component.createWithInitialProperties(properties)
        self.assertIsNotNone(root, str(component.errors()))
        self.components.append(component)
        self.roots.append(root)
        APP.processEvents()
        return root

    def picker(self, rows, *, role='instance_id'):
        return self.component('LocalServiceComboBox.qml',
                              dict(entries=rows, valueRole=role, textRole='name'))

    @staticmethod
    def row(picker):
        row = picker.property('selectedRow')
        return row.toVariant() if hasattr(row, 'toVariant') else row

    def activate(self, picker, index):
        # Native Controls commits currentIndex before emitting activated. Invoke
        # that actual Qt signal rather than calling the component's JS helper.
        picker.setProperty('currentIndex', index)
        self.assertTrue(QMetaObject.invokeMethod(picker, 'activated', Qt.DirectConnection,
                                                Q_ARG('int', index)))
        APP.processEvents()

    def click(self, panel, name):
        button = panel.findChild(QObject, name)
        self.assertIsNotNone(button, name)
        self.assertTrue(button.property('enabled'), name)
        self.assertTrue(QMetaObject.invokeMethod(button, 'clicked', Qt.DirectConnection))
        APP.processEvents()

    def panel(self, **properties):
        properties.setdefault('surfaceHost', self.bridge)
        properties['services'] = self.service_state(properties.get('services', {}))
        return self.component('LocalGameServices.qml', properties)

    @staticmethod
    def service_state(value):
        state = dict(trade=dict(open=False), petition=dict(registrar_open=False),
                     lifecycle=dict(dead=False, ghost=False), tabard=dict(open=False, can_save=False))
        state.update(value)
        return state

    def find(self, root, name):
        # Repeater delegates use visual parentage independently of QObject
        # custody. Search both actual trees, like the real client verifier.
        pending, seen = [root], {}
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
                    item = method.call([self.engine.toScriptValue(index)]).toQObject()
                    if item is not None: pending.append(item)
        return None

    def test_activation_survives_fresh_identical_rows_and_quantity_and_label_changes(self):
        rows = [dict(instance_id='bucket-1', name='Bucket', quantity=1),
                dict(instance_id='scroll-2', name='Scroll', quantity=1)]
        picker = self.picker(rows)
        self.activate(picker, 1)
        for quantity in (1, 1, 3, 2):
            updated = copy.deepcopy(rows)
            updated[1].update(name='Renamed scroll', quantity=quantity)
            picker.setProperty('entries', updated)
            APP.processEvents()
            self.assertEqual(picker.property('currentIndex'), 1)
            self.assertEqual(picker.property('selectedId'), 'scroll-2')
            self.assertEqual(picker.property('currentText'), 'Renamed scroll')
            self.assertEqual(self.row(picker)['quantity'], quantity)
        self.assertEqual(self.warnings, [])

    def test_selected_taxi_destination_removal_clears_controls_without_null_warnings(self):
        nodes = [dict(id='current-town', name='Here', current=True, cost=0),
                 dict(id='next-town', name='There', current=False, cost=100)]
        state = self.service_state(dict(travel=dict(open=True, riding=False, nodes=nodes)))
        panel = self.panel(services=state)
        picker = panel.findChild(QObject, 'localTaxiDestination')
        button = panel.findChild(QObject, 'localTaxiTake')
        self.activate(picker, 1)
        self.assertTrue(button.property('enabled'))
        for replacement in ([nodes[0]], [], [nodes[1]]):
            updated = copy.deepcopy(state)
            updated['travel']['nodes'] = replacement
            panel.setProperty('services', updated)
            APP.processEvents()
            self.assertIsNone(self.row(picker))
            self.assertEqual(picker.property('currentIndex'), -1)
            self.assertFalse(button.property('enabled'))
        self.assertEqual(self.warnings, [])

    def test_reorder_keeps_exact_person_even_with_duplicate_display_names(self):
        first, second = dict(id='first', name='Same name'), dict(id='second', name='Same name')
        picker = self.picker([first, second], role='id')
        picker.setProperty('currentIndex', 1)
        picker.setProperty('entries', [second.copy(), first.copy()])
        APP.processEvents()
        self.assertEqual(picker.property('currentIndex'), 0)
        self.assertEqual(picker.property('selectedId'), 'second')
        self.assertEqual(self.row(picker)['id'], 'second')

    def test_removed_identity_clears_and_returning_or_late_rows_do_not_implicitly_rebind(self):
        picker = self.picker([], role='id')
        rows = [dict(id='a', name='First'), dict(id='b', name='Second')]
        picker.setProperty('entries', rows)
        APP.processEvents()
        self.assertEqual(picker.property('currentIndex'), -1)
        self.activate(picker, 1)
        for updated in ([dict(id='replacement', name='Second')], [], rows):
            picker.setProperty('entries', updated)
            APP.processEvents()
            self.assertEqual(picker.property('currentIndex'), -1)
            self.assertIsNone(picker.property('selectedId'))
            self.assertIsNone(self.row(picker))
        picker.setProperty('currentIndex', 0)
        self.assertEqual(picker.property('selectedId'), 'a')

    def test_duplicate_semantic_ids_clear_an_ambiguous_refreshed_choice(self):
        picker = self.picker([dict(id='a', name='First')], role='id')
        self.activate(picker, 0)
        picker.setProperty('entries', [dict(id='a', name='First'), dict(id='a', name='Other')])
        APP.processEvents()
        self.assertEqual(picker.property('currentIndex'), -1)
        self.assertFalse(picker.property('hasSelection'))

    def test_explicit_no_attachment_row_retains_empty_string_identity(self):
        picker = self.picker([dict(instance_id='', name='Nothing'),
                              dict(instance_id='item', name='Item')])
        self.activate(picker, 0)
        picker.setProperty('entries', [dict(instance_id='', name='Nothing')])
        APP.processEvents()
        self.assertEqual(picker.property('selectedId'), '')
        self.assertTrue(picker.property('hasSelection'))
        self.assertEqual(picker.property('currentIndex'), 0)

    def test_real_mail_panel_sends_retained_attachment_after_two_inventory_refreshes(self):
        items = [dict(instance_id='bucket-1', name='Bucket'),
                 dict(instance_id='scroll-2', name='Scroll')]
        panel = self.panel(inventory=items, services=dict(session=12))
        picker = panel.findChild(QObject, 'localMailAttachment')
        panel.findChild(QObject, 'localMailSubject').setProperty('text', 'Authored mail')
        self.activate(picker, 2)
        for updated in (copy.deepcopy(items), [items[1].copy(), items[0].copy()]):
            panel.setProperty('inventory', updated)
            APP.processEvents()
        self.click(panel, 'localMailSend')
        self.assertEqual(self.bridge.commands[-1]['item'], 'scroll-2')
        self.assertEqual(self.bridge.commands[-1]['session'], 12)
        self.assertEqual(picker.property('selectedId'), '')
        self.assertEqual(self.warnings, [])

    def room(self, revision=4):
        return dict(name='Builders', shared_channel=True, channel_id='channel-fixture',
                    channel_revision=revision, player_id='self', can_manage=True, is_owner=True,
                    owner='self', owner_name='Hero', members=['self'], member_names=['Hero'],
                    moderators=[], muted=[], banned=[], announcements=True, moderated=False)

    def services(self, room=None):
        return self.service_state(dict(session=15, saved_recipients=[dict(id='saved-second', name='Second')],
                    channels=dict(shared_available=True, rows=[
                        dict(name='General - GG Island', builtin=True, members=['player'],
                             owner='', moderators=[]), room or self.room()])))

    def test_shown_shared_channel_revision_and_saved_target_survive_reorder_before_command(self):
        state = self.services()
        panel = self.panel(playerName='Hero', services=state,
                           people=[dict(id='npc-one', name='Actual NPC')])
        channel = panel.findChild(QObject, 'localChannelSelect')
        person = panel.findChild(QObject, 'localChannelPerson')
        self.activate(channel, 1)
        self.activate(person, 0)
        self.assertEqual(person.property('selectedId'), 'saved-second')
        refreshed = self.services(self.room(5))
        refreshed['channels']['rows'].reverse()
        panel.setProperty('services', refreshed)
        APP.processEvents()
        self.assertEqual(channel.property('currentIndex'), 0)
        self.click(panel, 'localChannelInvite')
        invite = self.bridge.commands[-1]
        self.assertEqual((invite['channel_id'], invite['channel_revision'], invite['player']),
                         ('channel-fixture', 5, 'saved-second'))
        self.assertIs(invite['shared_channel'], True)
        panel.findChild(QObject, 'localChannelMessage').setProperty('text', 'Exact shown room')
        self.click(panel, 'localChannelSend')
        message = self.bridge.commands[-1]
        self.assertEqual((message['name'], message['channel_id'], message['channel_revision'], message['text']),
                         ('Builders', 'channel-fixture', 5, 'Exact shown room'))
        self.assertEqual(self.warnings, [])

    def test_new_shared_password_opt_in_and_existing_original_zone_keep_distinct_routes(self):
        panel = self.panel(playerName='Hero', services=self.services())
        name = panel.findChild(QObject, 'localChannelName')
        password = panel.findChild(QObject, 'localChannelPassword')
        shared = panel.findChild(QObject, 'localChannelShared')
        shared.setProperty('checked', True)
        name.setProperty('text', 'Authored room')
        password.setProperty('text', 'fixture room password')
        self.click(panel, 'localChannelJoin')
        self.assertEqual(self.bridge.commands[-1]['password'], 'fixture room password')
        self.assertIs(self.bridge.commands[-1]['shared_channel'], True)
        self.assertEqual(password.property('text'), '')
        name.setProperty('text', 'General')
        self.click(panel, 'localChannelJoin')
        original = self.bridge.commands[-1]
        self.assertEqual(original['name'], 'General - GG Island')
        self.assertIs(original['shared_channel'], False)
        self.assertNotIn('channel_id', original)

    def test_actual_incoming_invite_selection_uses_displayed_room_revision_for_join(self):
        state = self.services()
        state['channels']['shared_invite'] = dict(name='Invited room', sender_name='Saved sender',
            shared_channel=True, channel_id='channel-invited', channel_revision=9)
        panel = self.panel(services=state)
        self.click(panel, 'localChannelInviteSelect')
        self.assertEqual(panel.findChild(QObject, 'localChannelName').property('text'), 'Invited room')
        self.click(panel, 'localChannelJoin')
        joined = self.bridge.commands[-1]
        self.assertEqual((joined['name'], joined['channel_id'], joined['channel_revision']),
                         ('Invited room', 'channel-invited', 9))
        self.assertIs(joined['shared_channel'], True)

    def test_recreated_loot_delegate_retains_exact_recipient_and_retires_removed_roll(self):
        roll = dict(id='roll-one', method='master', candidates=[dict(id='a', name='First'),
                    dict(id='b', name='Second')], attachment=dict(name='Authored loot'))
        panel = self.panel(services=dict(session=1, loot_rolls=[roll]))
        picker = self.find(panel, 'localLootRecipientroll-one')
        self.activate(picker, 1)
        refreshed = copy.deepcopy(roll)
        refreshed['candidates'].reverse()
        state = panel.property('services')
        baseline = dict(state.toVariant() if hasattr(state, 'toVariant') else state)
        baseline.update(session=1, loot_rolls=[refreshed])
        panel.setProperty('services', baseline)
        APP.processEvents()
        replacement = self.find(panel, 'localLootRecipientroll-one')
        self.assertEqual(replacement.property('selectedId'), 'b')
        self.assertEqual(replacement.property('currentIndex'), 0)
        baseline['loot_rolls'] = []
        panel.setProperty('services', baseline)
        APP.processEvents()
        baseline['loot_rolls'] = [roll]
        panel.setProperty('services', baseline)
        APP.processEvents()
        self.assertEqual(self.find(panel, 'localLootRecipientroll-one').property('currentIndex'), -1)
        self.assertEqual(self.warnings, [])


if __name__ == '__main__':
    unittest.main()
