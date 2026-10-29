"""Small isolated software view: one real percentage bar and a dated reset."""
import json
import os
from pathlib import Path
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
os.environ.setdefault('QT_QUICK_CONTROLS_STYLE', 'Basic')
from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication, QFont, QFontDatabase
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickItem

ROOT = Path(__file__).resolve().parents[1]


class ModelLimitUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])
        if os.name == 'nt':
            for name in ('consola.ttf', 'consolab.ttf', 'segoeui.ttf', 'seguisym.ttf'):
                QFontDatabase.addApplicationFont(str(Path(os.environ.get('SystemRoot', 'C:/Windows'))/'Fonts'/name))
            QFont.insertSubstitution('monospace', 'Consolas')

    def setUp(self):
        self.engine = QQmlEngine()
        self.warnings = []
        self.engine.warnings.connect(lambda errors: self.warnings.extend(error.toString() for error in errors))
        self.component = QQmlComponent(self.engine, QUrl.fromLocalFile(str(ROOT/'qml/components/TelemetryRail.qml')))
        self.assertTrue(self.component.isReady(), [error.toString() for error in self.component.errors()])
        self.rail = self.component.create()
        self.assertIsNotNone(self.rail)
        self.rail.setProperty('width', 168)
        self.rail.setProperty('height', 800)
        self.rail.setProperty('engineTarget', 'GPT_TUI')

    def tearDown(self):
        self.rail.deleteLater()
        self.engine.deleteLater()
        self.app.processEvents()
        self.assertFalse(self.warnings, self.warnings)

    def item(self, name):
        item = self.rail.findChild(QQuickItem, name)
        self.assertIsNotNone(item, name)
        return item

    def push(self, body, engine='GPT_TUI'):
        self.rail.setProperty('engineTarget', engine)
        self.rail.setProperty('gptWalletJson' if engine == 'GPT_TUI' else 'grokWalletJson', json.dumps(body))
        self.app.processEvents()

    def test_provider_changes_update_same_bar_and_keep_time_and_date(self):
        fill = self.item('modelLimitFill')
        track = self.item('modelLimitTrack')
        self.push({'limit_percent': 82, 'live_reset_label': '10:16 · 4 nov'})
        self.assertEqual(self.item('modelLimitLabel').property('text'), 'LIMIT 82%')
        self.assertEqual(self.item('modelLimitReset').property('text'), 'RESET 10:16 · 4 nov')
        reset = self.item('modelLimitReset')
        self.assertFalse(reset.property('truncated'))
        self.assertLessEqual(reset.property('paintedWidth'), reset.width())
        self.assertAlmostEqual(fill.width()/track.width(), .82)
        self.push({'limit_percent': 86, 'live_reset_label': '10:16 · 4 nov'})
        self.assertIs(fill, self.item('modelLimitFill'))
        self.assertAlmostEqual(fill.width()/track.width(), .86)
        labels = [str(item.property('text') or '') for item in self.rail.findChildren(QQuickItem) if item.metaObject().indexOfProperty('text') >= 0]
        self.assertFalse(any(label.startswith(('LIVE ', 'WEEK ')) for label in labels))
        bars = [item for item in self.rail.findChildren(QQuickItem) if item.inherits('QQuickRectangle') and item.height() == 6 and item.width() > 0]
        self.assertEqual(len(bars), 2)  # One track and its fill.

    def test_unknown_limit_is_not_zero_and_grok_tokens_are_not_a_percentage(self):
        self.push({'limit_percent': None, 'live_label': '0%', 'live_tokens': 0})
        self.assertEqual(self.item('modelLimitLabel').property('text'), 'LIMIT —')
        self.assertEqual(self.item('modelLimitFill').width(), 0)
        self.push({'live_tokens': 4714, 'live_label': '4K', 'weekly_percent': 53}, engine='GROK_TUI')
        self.assertEqual(self.item('modelLimitLabel').property('text'), 'LIMIT 53%')
        self.assertAlmostEqual(self.item('modelLimitFill').width()/self.item('modelLimitTrack').width(), .53)


if __name__ == '__main__':
    unittest.main()
