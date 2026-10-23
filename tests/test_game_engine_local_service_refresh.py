"""Real Qt service delegates and physical input across fresh status snapshots."""
import copy
import json
import os
from pathlib import Path
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_CONTROLS_STYLE', 'Basic')
from PySide6.QtCore import QObject, QPoint, QPointF, Qt, QUrl, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickItem, QQuickWindow
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from shiboken6 import isValid

PROJECT = Path(__file__).resolve().parents[1]
APP = QGuiApplication.instance() or QGuiApplication([])
QQuickStyle.setStyle('Basic')

HARNESS = b'''
import QtQuick
import QtQuick.Controls
import "LocalServiceState.js" as LocalServiceState
Window {
    id: root
    width: 1000; height: 760; visible: true
    required property var bridge
    required property string initialJson
    property var state: JSON.parse(initialJson)
    property var lastState: null
    function apply(encoded) {
        lastState = state
        state = LocalServiceState.retain(state, JSON.parse(encoded))
    }
    function retained() {
        return {all: state === lastState,
                mail: state.mail === lastState.mail,
                rows: state.mail.rows === lastState.mail.rows,
                first: state.mail.rows[0] === lastState.mail.rows[0]}
    }
    LocalGameServices {
        id: panel
        surfaceHost: root.bridge
        services: root.state
        Component.onCompleted: open()
    }
}
'''


class Bridge(QObject):
    def __init__(self):
        super().__init__()
        self.commands = []

    @Slot(str, result=str)
    def gameEngineClientControl(self, value):
        self.commands.append(json.loads(value))
        return '{}'


class LocalServiceRefresh(unittest.TestCase):
    def setUp(self):
        self.engine = QQmlEngine()
        self.warnings = []
        self.engine.warnings.connect(lambda rows: self.warnings.extend(str(row) for row in rows))
        self.bridge = Bridge()
        self.component = QQmlComponent(self.engine)
        self.component.setData(HARNESS, QUrl.fromLocalFile(str(PROJECT / 'qml/components/RefreshTest.qml')))
        self.assertEqual(self.component.errors(), [])
        self.window = self.component.createWithInitialProperties(dict(bridge=self.bridge, initialJson=json.dumps(self.state())))
        self.assertIsNotNone(self.window, str(self.component.errors()))
        self.assertIsInstance(self.window, QQuickWindow)
        self.addCleanup(self.retire)
        QTest.qWait(35)
        self.bridge.commands.clear()

    def retire(self):
        if isValid(self.window):
            self.window.close()
            self.window.deleteLater()
        APP.processEvents()
        self.component = None
        self.window = None
        self.engine.deleteLater()
        self.bridge.deleteLater()
        APP.processEvents()

    @staticmethod
    def state():
        return dict(money=130, session=7, mail=dict(open=True, rows=[dict(
            id='authored-mail', subject='Token delivery', sender_name='Fixture sender',
            body='An authored mail fixture.', money=23, cod=0,
            attachment=dict(name='Scroll', quantity=2))]),
            trade=dict(open=False), petition=dict(registrar_open=False),
            lifecycle=dict(dead=False, ghost=False), tabard=dict(open=False, can_save=False))

    def call(self, name, *args):
        if name == 'apply': args = tuple(json.dumps(arg) for arg in args)
        result = self.engine.newQObject(self.window).property(name).call([
            self.engine.toScriptValue(arg) for arg in args])
        self.assertFalse(result.isError(), result.toString())
        APP.processEvents()
        return result.toVariant()

    def find(self, name=None, *, text=None):
        pending, seen = [self.window, self.window.contentItem()], {}
        while pending:
            node = pending.pop()
            if id(node) in seen: continue
            seen[id(node)] = node
            if name is not None and node.objectName() == name: return node
            if text is not None and node.property('text') == text: return node
            pending.extend(node.children())
            if isinstance(node, QQuickItem): pending.extend(node.childItems())
            if node.inherits('QQuickRepeater'):
                method = self.engine.newQObject(node).property('itemAt')
                for index in range(node.property('count')):
                    item = method.call([self.engine.toScriptValue(index)]).toQObject()
                    if item is not None: pending.append(item)
        return None

    def test_physical_mail_money_press_survives_two_snapshots_then_releases_once(self):
        button = self.find('localMailMoney')
        self.assertIsNotNone(button)
        point = button.mapToScene(QPointF(button.width() / 2, button.height() / 2)).toPoint()
        QTest.mousePress(self.window, Qt.LeftButton, Qt.NoModifier, point)
        APP.processEvents()
        self.assertTrue(button.property('pressed'))
        # A changing wallet forces the top-level binding to update. Mail itself
        # stays equal in independently allocated snapshots, twice.
        for money in (131, 132):
            incoming = copy.deepcopy(self.state())
            incoming['money'] = money
            self.call('apply', incoming)
            self.assertTrue(isValid(button))
            self.assertIs(self.find('localMailMoney'), button)
            self.assertTrue(button.property('pressed'))
            self.assertEqual(self.call('retained'), dict(all=False, mail=True, rows=True, first=True))
        QTest.mouseRelease(self.window, Qt.LeftButton, Qt.NoModifier, point)
        APP.processEvents()
        self.assertFalse(button.property('pressed'))
        self.assertEqual(self.bridge.commands, [dict(kind='service', op='MailMoney', session=7, id='authored-mail')])
        self.assertEqual(self.find('localServiceWallet').property('text'), '0 g 1 s 32 k')
        self.assertEqual(self.warnings, [])

    def test_changed_mail_money_attachment_and_removal_are_authoritative(self):
        incoming = self.state()
        incoming['mail']['rows'][0]['money'] = 0
        incoming['mail']['rows'][0]['attachment']['quantity'] = 5
        self.call('apply', incoming)
        button = self.find('localMailMoney')
        self.assertIsNotNone(button)
        self.assertFalse(button.property('enabled'))
        self.assertEqual(self.call('retained'), dict(all=False, mail=False, rows=False, first=False))
        self.assertIsNotNone(self.find(text='Scroll × 5'))
        incoming['mail']['rows'] = []
        self.call('apply', incoming)
        self.assertIsNone(self.find('localMailMoney'))
        self.assertEqual(self.bridge.commands, [])
        self.assertEqual(self.warnings, [])

    def test_equal_snapshot_is_same_root_and_changed_session_retains_only_mail(self):
        self.call('apply', copy.deepcopy(self.state()))
        self.assertEqual(self.call('retained'), dict(all=True, mail=True, rows=True, first=True))
        incoming = self.state()
        incoming['session'] = 8
        self.call('apply', incoming)
        self.assertEqual(self.call('retained'), dict(all=False, mail=True, rows=True, first=True))
        self.assertEqual(self.warnings, [])

if __name__ == '__main__':
    unittest.main()
