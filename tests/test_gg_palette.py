"""Actual QML palette, terminal provenance, readable roles and caller overrides."""
from __future__ import annotations

import json
import os
from pathlib import Path
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_BACKEND', 'software')

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlComponent, QQmlEngine
from backend.mini_vt import PALETTE

ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads((ROOT/'config/gg-palette.json').read_text(encoding='utf-8'))


def luminance(value):
    channels = [int(value[i:i+2], 16)/255 for i in (1, 3, 5)]
    linear = [channel/12.92 if channel <= .04045 else ((channel+.055)/1.055)**2.4 for channel in channels]
    return sum(channel*weight for channel, weight in zip(linear, (.2126, .7152, .0722)))


def identity_color(identity):
    raw = identity.encode('utf-16-le')
    result = 2166136261
    for position in range(0, len(raw), 2):
        unit = int.from_bytes(raw[position:position+2], 'little')
        result = ((result ^ unit)*16777619) & 0xffffffff
    return DATA['colors'][result % DATA['identity_color_count']]


class PaletteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def create(self, body):
        engine = QQmlEngine()
        warnings = []
        engine.warnings.connect(lambda rows: warnings.extend(row.toString() for row in rows))
        source = ('import QtQuick\nimport '
                  + json.dumps((ROOT/'qml/components/GGPalette.js').as_uri()) + ' as Palette\n'
                  + 'import ' + json.dumps((ROOT/'qml/components/LedgerTheme.js').as_uri()) + ' as Ledger\n'
                  + 'import ' + json.dumps((ROOT/'qml/components').as_uri()) + '\nItem {'+body+'}')
        component = QQmlComponent(engine)
        component.setData(source.encode(), QUrl.fromLocalFile(str(ROOT/'qml/palette-fixture.qml')))
        self.assertTrue(component.isReady(), [error.toString() for error in component.errors()])
        item = component.create()
        self.assertIsNotNone(item, [error.toString() for error in component.errors()])
        item.setParent(engine)
        self.app.processEvents()
        self.assertFalse(warnings, warnings)
        return engine, item

    def test_all_swatches_have_exact_terminal_provenance_and_stable_indices(self):
        colors = DATA['colors']
        self.assertEqual(len(colors), 64)
        self.assertEqual(len(set(colors)), 64)
        self.assertEqual(colors, ['#%02x%02x%02x' % PALETTE[index] for index in DATA['xterm_indices']])
        # These anchors are persisted token-color selections. Reordering the
        # canonical palette is a migration, not an aesthetic refactor.
        self.assertEqual(colors[:8], ['#87afd7','#87afaf','#af87d7','#d78787',
                                     '#d7af87','#87af87','#d7d787','#d787af'])
        self.assertEqual(colors[16:32],['#5f87d7','#5fafaf','#8787d7','#d75f5f',
            '#d7875f','#87af5f','#d7d75f','#d75f87','#87d7ff','#87ffaf','#af87ff',
            '#d7afff','#949494','#d0d0d0','#ffaf5f','#ffd7af'])
        self.assertEqual(len(DATA['legacy_colors']),32)
        self.assertTrue({'#ff0000','#ff5f5f','#d70000','#000000','#ffffff',
                         '#121212','#262626','#444444','#808080','#eeeeee'}<=set(colors))

    def test_text_and_semantic_roles_remain_readable_on_dark_surfaces(self):
        roles = DATA['roles']
        for foreground in ('bright', 'text', 'muted', 'blue', 'cyan', 'purple',
                           'positive', 'negative', 'warning', 'orange', 'pink'):
            for background in ('base', 'panel', 'raised'):
                with self.subTest(foreground=foreground, background=background):
                    values = sorted((luminance(roles[foreground]), luminance(roles[background])))
                    self.assertGreaterEqual((values[1]+.05)/(values[0]+.05), 4.5)

    def test_actual_qml_js_roles_prefixes_and_returned_arrays_match_canonical_source(self):
        engine, item = self.create('''property string result: JSON.stringify({
            sixteen:Palette.swatches(16),thirtytwo:Palette.colors(32),sixtyfour:Palette.colors(64),
            fallback:Palette.colors(17),color:Palette.color(40),invalid:Palette.color(-1),
            roles:{accent:Ledger.accent,positive:Ledger.positive,negative:Ledger.negative,
                   info:Ledger.info,warning:Ledger.warning,purple:Ledger.purple,text:Ledger.text},
            noSharedArray:(function(){var values=Palette.colors(16);values[0]="#000000";
                                       return Palette.colors(16)[0]===Palette.color(0)})()})''')
        result = json.loads(item.property('result'))
        for name, count in (('sixteen',16),('thirtytwo',32),('sixtyfour',64),('fallback',16)):
            self.assertEqual(result[name], DATA['colors'][:count])
        self.assertTrue(result['noSharedArray'])
        self.assertEqual(result['color'], DATA['colors'][40])
        self.assertEqual(result['invalid'], DATA['roles']['accent'])
        self.assertEqual(result['roles'], {key:DATA['roles'][key] for key in result['roles']})
        item.deleteLater(); engine.deleteLater(); self.app.processEvents()

    def test_token_defaults_bind_identity_and_validation_accepts_only_palette_colors(self):
        identities = ['eip155:1/native:ETH','eip155:10/native:ETH',
                      'solana:mainnet/native:SOL','solana:mainnet/spl:GGHB', 'test:åäö/🧪']
        engine, item = self.create('''property string result: JSON.stringify({
            defaults:''' + json.dumps(identities, ensure_ascii=True) + '''.map(function(key){
                         return Palette.defaultTokenColor(key)}),
            valid:Palette.validColor(Palette.color(5).toUpperCase()),
            legacy:Palette.validColor("#005faf"),
            invalid:Palette.validColor("#123456"),injection:Palette.validColor("red; alert(1)")})''')
        result = json.loads(item.property('result'))
        self.assertEqual(result['defaults'], [identity_color(identity) for identity in identities])
        self.assertTrue(result['valid']); self.assertFalse(result['invalid']); self.assertFalse(result['injection'])
        self.assertTrue(result['legacy'])
        self.assertNotEqual(result['defaults'][0], result['defaults'][1])
        item.deleteLater(); engine.deleteLater(); self.app.processEvents()

    def test_shared_controls_use_palette_and_keep_explicit_caller_overrides(self):
        engine, item = self.create('''property color customPanel:frame.backgroundColor
            property color customText:field.color
            property color defaultFrame:defaultFrame.backgroundColor
            GgFrame{id:frame;backgroundColor:"#123456";width:200;height:70}
            GgFrame{id:defaultFrame;y:80;width:200;height:70}
            GgField{id:field;color:"#abcdef";y:160}
            GgButton{text:"Test";y:200}
            GgSwitch{y:240}
        ''')
        self.assertEqual(item.property('customPanel').name(), '#123456')
        self.assertEqual(item.property('customText').name(), '#abcdef')
        self.assertEqual(item.property('defaultFrame').name(), DATA['roles']['panel'])
        item.deleteLater(); engine.deleteLater(); self.app.processEvents()


if __name__ == '__main__':
    unittest.main()
