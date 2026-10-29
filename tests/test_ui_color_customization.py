"""Presentation colors use disposable fixtures; no wallet or user's settings."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')
from PySide6.QtCore import QObject, QPointF, Qt, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlComponent, QQmlEngine, QQmlExpression, qmlContext
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from shiboken6 import getCppPointer, wrapInstance
from backend import ui_color_customization as module

ROOT = Path(__file__).resolve().parents[1]
COLORS = frozenset({'#ff0000', '#ffffff', '#000000', '#87afd7'})


class ColorRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='gg-ui-color-fixture-')
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'ui-colors.json'
        self.registry = module.ColorRegistry(self.path, colors=COLORS)

    def test_semantic_whole_colors_persist_without_displayed_text(self):
        self.registry.set_color('ui.network.account.identity', '#FF0000')
        other = module.ColorRegistry(self.path, colors=COLORS)
        self.assertEqual(other.style('ui.network.account.identity', 'Konto 1')['color'], '#ff0000')
        self.assertEqual(other.style('ui.network.account.identity', 'Public test address')['color'], '#ff0000')
        self.assertNotIn('Public test address', self.path.read_text())
        other.reset('ui.network.account.identity')
        self.assertEqual(module.ColorRegistry(self.path, colors=COLORS).entries, {})

    def test_partial_utf16_emoji_selection_and_plain_text_are_preserved(self):
        text = 'A🟣B <tag>& test'
        self.registry.set_range('ui.public.label', text, 1, 3, '#ff0000')
        style = self.registry.style('ui.public.label', text)
        formatted = module.rich_text(text, style)
        self.assertEqual(formatted, 'A<font color="#ff0000">🟣</font>B &lt;tag&gt;&amp; test')
        self.assertEqual(style['ranges'], [{'start': 1, 'end': 3, 'color': '#ff0000'}])
        persisted = self.path.read_text()
        self.assertNotIn(text, persisted)
        self.assertNotIn('<tag>', persisted)
        self.assertEqual(module.ColorRegistry(self.path, colors=COLORS).style('ui.public.label', text), style)

    def test_clock_and_counter_colors_follow_ui_positions_when_values_change(self):
        self.registry.set_range('ui.public.clock', '12:34:56', 6, 8, '#ff0000')
        expected = [{'start': 6, 'end': 8, 'color': '#ff0000'}]
        self.assertEqual(self.registry.style('ui.public.clock', '12:34:57')['ranges'], expected)
        self.assertEqual(module.ColorRegistry(self.path, colors=COLORS).style('ui.public.clock', '22:00:00')['ranges'], expected)
        self.assertNotIn('12:34:56', self.path.read_text())
        self.assertNotIn('text_digest', self.path.read_text())
        self.registry.set_range('ui.public.count', '1000', 0, 2, '#ff0000')
        self.assertEqual(self.registry.style('ui.public.count', '2000')['ranges'], [{'start': 0, 'end': 2, 'color': '#ff0000'}])

    def test_changed_unicode_geometry_skips_invalid_slot_boundaries(self):
        self.registry.set_range('ui.public.counter', 'A🟣B', 1, 3, '#ff0000')
        self.assertEqual(self.registry.style('ui.public.counter', '🟣AB')['ranges'], [])
        self.assertEqual(self.registry.style('ui.public.counter', 'A')['ranges'], [])

    def test_legacy_digest_anchors_still_require_same_content(self):
        entry={'text_digest':module.text_digest('1000'),'ranges':[{'start':0,'end':2,'color':'#ff0000'}]}
        self.path.write_text(json.dumps({'schema':module.SCHEMA,'entries':{'ui.old':entry}}))
        old=module.ColorRegistry(self.path,colors=COLORS)
        self.assertEqual(len(old.style('ui.old','1000')['ranges']),1)
        self.assertEqual(old.style('ui.old','2000')['ranges'],[])

    def test_latest_overlap_splits_prior_color_without_changing_other_letters(self):
        text = 'ABCDEFGH'
        self.registry.set_range('ui.public.label', text, 0, 8, '#ff0000')
        self.registry.set_range('ui.public.label', text, 2, 5, '#ffffff')
        self.assertEqual(self.registry.style('ui.public.label', text)['ranges'], [
            {'start': 0, 'end': 2, 'color': '#ff0000'},
            {'start': 2, 'end': 5, 'color': '#ffffff'},
            {'start': 5, 'end': 8, 'color': '#ff0000'},
        ])

    def test_adjacent_equal_formats_merge_and_other_roles_keep_their_colors(self):
        self.registry.set_color('ui.first', '#000000')
        self.registry.set_color('ui.second', '#ffffff')
        self.registry.set_range('ui.first', 'ABCD', 0, 2, '#ff0000')
        self.registry.set_range('ui.first', 'ABCD', 2, 4, '#ff0000')
        self.assertEqual(self.registry.style('ui.first', 'ABCD')['ranges'], [{'start': 0, 'end': 4, 'color': '#ff0000'}])
        self.assertEqual(self.registry.style('ui.second')['color'], '#ffffff')

    def test_rejects_private_keys_noncanonical_colors_and_surrogate_splits(self):
        for key in ('ui.mnemonic.word', 'ui.chat.message', 'ui.password', '../escape', '', 'ui x'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.registry.set_color(key, '#ff0000')
        for color in ('#123456', 'red', '#ff000000', '<script>'):
            with self.subTest(color=color), self.assertRaises(ValueError):
                self.registry.set_color('ui.safe', color)
        for start, end in ((0, 2), (2, 3), (True, 3), (-1, 3), (1, 99)):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                self.registry.set_range('ui.safe', 'A🟣B', start, end, '#ff0000')
        self.assertFalse(self.path.exists())

    def test_failed_atomic_save_never_publishes_a_changed_style(self):
        self.registry.set_color('ui.safe', '#000000')
        before = self.path.read_bytes()
        with patch.object(module, 'atomic_replace', side_effect=OSError('fixture failure')):
            with self.assertRaises(OSError):
                self.registry.set_color('ui.safe', '#ff0000')
        self.assertEqual(self.registry.style('ui.safe')['color'], '#000000')
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(Path(self.temp.name).iterdir()), [self.path])

    def test_storage_entry_range_and_file_budgets_are_bounded(self):
        with patch.object(module, 'MAX_ENTRIES', 2):
            self.registry.set_color('ui.one', '#ff0000')
            self.registry.set_color('ui.two', '#ff0000')
            with self.assertRaisesRegex(ValueError, 'STORAGE_LIMIT'):
                self.registry.set_color('ui.three', '#ff0000')
        self.assertNotIn('ui.three', self.registry.entries)
        with patch.object(module, 'MAX_RANGES', 2):
            self.registry.set_range('ui.safe', 'ABCDEFG', 0, 1, '#ff0000')
            self.registry.set_range('ui.safe', 'ABCDEFG', 2, 3, '#ff0000')
            with self.assertRaisesRegex(ValueError, 'RANGE_LIMIT'):
                self.registry.set_range('ui.safe', 'ABCDEFG', 4, 5, '#ff0000')
        with patch.object(module, 'MAX_FILE_BYTES', 10):
            with self.assertRaisesRegex(ValueError, 'STORAGE_LIMIT'):
                self.registry.set_color('ui.safe', '#ffffff')

    def test_loading_malformed_untrusted_registry_filters_styles(self):
        self.path.write_text(json.dumps({'schema': module.SCHEMA, 'entries': {
            'ui.safe': {'color': '#FF0000', 'ranges': [{'start': True, 'end': 4, 'color': '#ff0000'}], 'text_digest': '0' * 64},
            'ui.password': {'color': '#ff0000'}, 'ui.fake': {'color': '#123456'},
        }}))
        self.assertEqual(module.ColorRegistry(self.path, colors=COLORS).entries, {'ui.safe': {'color': '#ff0000'}})
        self.path.write_text('{')
        self.assertEqual(module.ColorRegistry(self.path, colors=COLORS).entries, {})

    def test_word_range_unicode_numbers_and_individual_symbols(self):
        self.assertEqual(module.word_range('Konto 123', 2), (0, 5))
        self.assertEqual(module.word_range('Konto 123', 8), (6, 9))
        self.assertEqual(module.word_range('räkning: 5', 2), (0, 7))
        self.assertEqual(module.word_range('A🟣B', 1), (1, 3))
        self.assertEqual(module.word_range('A🟣B', 2), (1, 3))
        self.assertEqual(module.word_range('A B', 1), (-1, -1))

    def test_risk_progress_modes_and_unknown_values_are_predictable(self):
        controller=module.UiColorController(path=self.path,colors=COLORS)
        self.assertTrue(controller.setScale('ui.percent','risk'))
        self.assertEqual(controller.colorForValue('ui.percent','#87afd7',1),'#ff0000')
        self.assertEqual(controller.colorForValue('ui.percent','#87afd7',0.25),'#00ff87')
        self.assertEqual(controller.colorForValue('ui.percent','#87afd7',-1),'#005fff')
        self.assertEqual(controller.colorForValue('ui.percent','#87afd7',99),'#ff0000')
        for value in (None,float('nan'),float('inf'),'0.5',True):
            self.assertEqual(controller.colorForValue('ui.percent','#87afd7',value),'#87afd7')
        self.assertTrue(controller.setScale('ui.percent','progress'))
        self.assertEqual(controller.colorForValue('ui.percent','#87afd7',0.99),'#87d7ff')
        self.assertEqual(controller.colorForValue('ui.percent','#87afd7',1),'#afd7ff')
        self.assertEqual(module.ColorRegistry(self.path,colors=COLORS).style('ui.percent')['scale'],'progress')
        self.assertFalse(controller.setScale('ui.percent','unsupported'))

    def test_explicit_deadline_is_bounded_deterministic_and_expires_red(self):
        controller=module.UiColorController(path=self.path,colors=COLORS)
        self.assertTrue(controller.setDeadline('ui.clock',1000,11000))
        self.assertEqual(controller.latestDeadlineTime,11000)
        self.assertEqual(controller.deadlineColor('ui.clock','#ffffff',1000),'#005fff')
        self.assertEqual(controller.deadlineColor('ui.clock','#ffffff',11000),'#ff0000')
        self.assertEqual(controller.deadlineColor('ui.clock','#ffffff',99999),'#ff0000')
        self.assertEqual(controller.deadlineColor('ui.clock','#ffffff',float('nan')),'#ffffff')
        for start,end in ((True,5000),(0,0),(5000,4000),(-1,5000),(0,module.MAX_EPOCH_MS+1),(0,float('inf')),(0,3.5)):
            self.assertFalse(controller.setDeadline('ui.clock',start,end))
        restored=module.UiColorController(path=self.path,colors=COLORS)
        self.assertEqual(restored.deadlineColor('ui.clock','#ffffff',11000),'#ff0000')
        self.assertTrue(restored.setScale('ui.clock','solid'))
        self.assertEqual(restored.latestDeadlineTime,0)


class ColorPopupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='gg-ui-color-qml-')
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'styles.json'
        self.host = module.UiColorController(path=self.path)
        self.engine = QQmlEngine()
        self.engine.rootContext().setContextProperty('fixtureColors', self.host)
        self.warnings = []
        self.engine.warnings.connect(lambda values: self.warnings.extend(value.toString() for value in values))
        self.component = QQmlComponent(self.engine)
        source = '''import QtQuick
import QtQuick.Controls
import COMPONENTS
import COMPONENTS as C
Window {
    id: root; width:640; height:600; visible:true
    property int disabledClicks:0
    property var colorPopup:C.GGColorContext.popup
    Text {id:target;objectName:'publicTarget';text:'Public words';color:'#d8dee9';property bool percentageCapable:true;property bool finished:false;function finishColorSelection(){finished=true}}
    Item {objectName:'walletCreationWizard';Text{id:privateTarget;text:'never shown';}}
    Button {id:disabledButton;objectName:'disabledButton';x:20;y:200;width:220;height:34;enabled:false;text:'Stoppad knapp'
        contentItem:GGText {id:disabledCaption;objectName:'disabledCaption';colorKey:'ui.fixture.disabled';text:disabledButton.text;font:disabledButton.font;verticalAlignment:Text.AlignVCenter}
        onClicked:root.disabledClicks++
    }
    Popup {id:blockingPopup;objectName:'blockingPopup';x:20;y:190;width:240;height:60;modal:false;focus:true;closePolicy:Popup.NoAutoClose;contentItem:Text{text:'Annan meny'}}
    Component.onCompleted:{C.GGColorContext.backend=fixtureColors;C.GGColorContext.hostOverlay=Overlay.overlay}
    function openWord(){return C.GGColorContext.openFor(target,'ui.fixture.label',target.text,0,6,40,40,false)}
    function openPrivate(){return C.GGColorContext.openFor(privateTarget,'ui.fixture.label','unused',0,1,40,40,false)}
    function openWhole(){return C.GGColorContext.openWhole(target,'ui.fixture.label','#d8dee9',40,40)}
    function coverDisabled(){blockingPopup.open()}
}'''.replace('COMPONENTS', json.dumps((ROOT / 'qml/components').as_uri()))
        self.component.setData(source.encode(), QUrl.fromLocalFile(str(ROOT / 'qml/ui-color-public-fixture.qml')))
        self.assertTrue(self.component.isReady(), [error.toString() for error in self.component.errors()])
        self.window = self.component.create()
        self.assertIsNotNone(self.window)
        QTest.qWait(20)

    def tearDown(self):
        self.window.setVisible(False)
        self.window.deleteLater()
        self.engine.deleteLater()
        self.app.processEvents()
        self.assertFalse(self.warnings, self.warnings)

    def js(self, code):
        expression = QQmlExpression(qmlContext(self.window), self.window, code)
        result = expression.evaluate()
        if isinstance(result, tuple) and len(result) == 2 and type(result[1]) is bool:
            result = result[0]
        self.assertFalse(expression.hasError(), expression.error().toString())
        self.app.processEvents()
        return result

    def test_single_shared_popup_range_choice_and_whole_type_reset(self):
        self.assertTrue(self.js('openWord()'))
        self.assertEqual(self.js('colorPopup.palette.length'), 64)
        self.assertEqual(self.js('colorPopup.hasRange'), True)
        self.assertTrue(self.js('colorPopup.visible'))
        self.js("colorPopup.choose('#ff0000')")
        self.assertEqual(self.host.registry.style('ui.fixture.label', 'Public words')['ranges'], [{'start': 0, 'end': 6, 'color': '#ff0000'}])
        self.assertTrue(self.js('target.finished'))
        self.assertEqual(self.js("C.GGColorContext.formatted('ui.fixture.label','Public words')"), '<font color="#ff0000">Public</font> words')
        self.assertTrue(self.js('openWhole()'))
        self.js("colorPopup.choose('#ffffff')")
        self.assertEqual(self.host.registry.style('ui.fixture.label')['color'], '#ffffff')
        self.assertTrue(self.host.reset('ui.fixture.label'))
        self.assertEqual(self.host.registry.entries, {})

    def test_private_ancestor_is_excluded_and_controller_errors_do_not_mutate(self):
        self.assertFalse(self.js('openPrivate()'))
        self.assertFalse(self.path.exists())
        self.assertFalse(self.host.setColor('ui.password', '#ff0000'))
        self.assertEqual(self.host.revision, 0)
        self.assertEqual(self.host.error, 'UI_COLOR_PRESENTATION_KEY_REQUIRED')
        self.assertFalse(self.path.exists())

    def test_unconfigured_context_has_no_color_override(self):
        self.js('C.GGColorContext.backend=null')
        self.assertFalse(self.js("C.GGColorContext.hasColor('ui.fixture.label')"))
        self.assertEqual(self.js("C.GGColorContext.colorFor('ui.fixture.label','#87afd7')"),'#87afd7')

    def click_item(self, name, button):
        item=self.window.findChild(QObject,name)
        self.assertIsNotNone(item)
        if not isinstance(item,QQuickItem):item=wrapInstance(getCppPointer(item)[0],QQuickItem)
        point=item.mapToScene(QPointF(12,item.height()/2))
        QTest.mouseClick(self.window,button,Qt.NoModifier,point.toPoint())
        self.app.processEvents()

    def test_disabled_native_caption_right_click_color_preserves_disabled_actions(self):
        QTest.qWait(80)
        self.click_item('disabledCaption',Qt.RightButton)
        self.assertIsNone(self.js('colorPopup'))
        self.assertTrue(self.host.installWindow(self.window))
        self.assertTrue(self.host.installWindow(self.window))
        self.assertEqual(len(self.host._window_filters),1)
        self.click_item('disabledCaption',Qt.RightButton)
        self.assertTrue(self.js('colorPopup.visible'))
        self.assertEqual(self.js('colorPopup.targetKey'),'ui.fixture.disabled')
        self.js("colorPopup.choose('#ff0000')")
        self.assertTrue(self.host.registry.style('ui.fixture.disabled','Stoppad knapp')['ranges'])
        QTest.qWait(80)
        self.click_item('disabledCaption',Qt.LeftButton)
        self.assertEqual(self.js('disabledClicks'),0)
        self.assertFalse(self.window.findChild(QObject,'disabledButton').property('enabled'))

    def test_disabled_fallback_does_not_look_through_existing_native_popup(self):
        self.assertTrue(self.host.installWindow(self.window))
        self.js('coverDisabled()');QTest.qWait(80)
        self.click_item('disabledCaption',Qt.RightButton)
        self.assertIsNone(self.js('colorPopup'))
        self.assertEqual(self.js('disabledClicks'),0)
        self.assertFalse(self.path.exists())

    def test_left_button_never_runs_disabled_fallback_hit_testing(self):
        self.assertTrue(self.host.installWindow(self.window))
        listener=next(iter(self.host._window_filters.values()))
        with patch.object(listener,'_disabled_text_at',wraps=listener._disabled_text_at) as hit:
            self.click_item('disabledCaption',Qt.LeftButton)
            hit.assert_not_called()
        self.assertEqual(self.js('disabledClicks'),0)

    def test_actual_popup_scale_button_sets_gradient_and_reacts_to_value(self):
        self.assertTrue(self.js('openWhole()'))
        QTest.qWait(80)
        button=self.js("(function(){function find(item){if(item.objectName==='uiColorScale_risk')return item;var children=item.children||[];for(var i=0;i<children.length;i++){var found=find(children[i]);if(found)return found}return null}return find(colorPopup.contentItem)})()")
        if hasattr(button,'toQObject'):button=button.toQObject()
        self.assertIsNotNone(button)
        if not isinstance(button,QQuickItem):button=wrapInstance(getCppPointer(button)[0],QQuickItem)
        self.assertTrue(button.property('visible'))
        center=button.mapToScene(QPointF(button.property('width')/2,button.property('height')/2))
        QTest.mouseClick(self.window,Qt.LeftButton,Qt.NoModifier,center.toPoint())
        self.app.processEvents()
        self.assertEqual(self.host.scaleFor('ui.fixture.label','solid'),'risk')
        self.assertFalse(self.js('colorPopup.visible'))
        self.assertEqual(self.js("C.GGColorContext.colorForValue('ui.fixture.label','#ffffff',1)"),'#ff0000')

    def test_actual_deadline_editor_rejects_bad_date_and_stops_idle_timer(self):
        self.assertTrue(self.js('openWhole()'))
        self.js('colorPopup.showDeadlineEditor=true')
        date=self.window.findChild(QObject,'uiColorDeadlineDate')
        clock=self.window.findChild(QObject,'uiColorDeadlineTime')
        self.assertIsNotNone(date);self.assertIsNotNone(clock)
        date.setProperty('text','2026-02-31');clock.setProperty('text','23:00:00')
        self.assertFalse(self.js('colorPopup.saveDeadline()'))
        self.assertEqual(self.host.latestDeadlineTime,0)
        parts=json.loads(self.js("(function(){var d=new Date(Date.now()+86400000),p=function(v){return String(v).padStart(2,'0')};return JSON.stringify({date:d.getFullYear()+'-'+p(d.getMonth()+1)+'-'+p(d.getDate()),time:p(d.getHours())+':'+p(d.getMinutes())+':'+p(d.getSeconds())})})()"))
        date.setProperty('text',parts['date']);clock.setProperty('text',parts['time'])
        self.assertTrue(self.js('colorPopup.saveDeadline()'))
        self.assertTrue(self.js('C.GGColorContext.deadlineTimer.running'))
        self.js('C.GGColorContext.applicationVisible=false')
        self.assertFalse(self.js('C.GGColorContext.deadlineTimer.running'))
        self.js('C.GGColorContext.applicationVisible=true')
        self.assertTrue(self.host.reset('ui.fixture.label'))
        self.assertFalse(self.js('C.GGColorContext.deadlineTimer.running'))


if __name__ == '__main__':
    unittest.main()
