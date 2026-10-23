"""Original realm inheritance over actual saved LocalCharacters, without Lua workers."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtGui import QGuiApplication
APP = QGuiApplication.instance() or QGuiApplication([])

from backend import game_engine_character_creation as appearance
from backend.game_engine_adapter_addon_state import (
    SCHEMA, bind_local_roster, load_enabled, save_enabled,
)
from backend.game_engine_adapter_ui import GgEngineUI
from tests import test_game_engine_local_custody_services as custody_fixture


class SavedUI:
    """Use the real bounded disk reader/writer; no native worker is started."""
    _saved_json = GgEngineUI._saved_json
    _write_saved = GgEngineUI._write_saved

    def __init__(self, account, identity):
        self.saved_root = account
        self.character_saved_root = account/'characters'/identity
        self.held_saves = set()
        self.errors = []
        self._pending_addon_rows = None


class LocalAddonInheritance(unittest.TestCase):
    # Reuse setup methods only, never inherit the fixture's unrelated tests.
    bind = custody_fixture.SharedServices.bind
    switch = custody_fixture.SharedServices.switch

    def setUp(self):
        custody_fixture.SharedServices.setUp(self)
        self.account = Path(self.directory.name)/'addon-account'

    def ui(self, identity, account=None):
        ui = SavedUI(account or self.account, identity)
        bind_local_roster(ui, ui.saved_root, identity, self.session)
        return ui

    def write(self, identity, rows, account=None):
        path = (account or self.account)/'characters'/identity/'addons.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'schema': SCHEMA, 'rows': rows}))
        return path

    @staticmethod
    def addons(**defaults):
        return {name.casefold(): ({'name': name, 'enabled': enabled}, {})
                for name, enabled in defaults.items()}

    def test_actual_switch_clean_character_inherits_unanimous_disable_without_copying_rows(self):
        first = self.write(self.first, [['MAIN', False]])
        before = first.read_bytes()
        self.switch(self.second)
        ui = self.ui(self.second)
        addons = self.addons(Main=True)
        self.assertEqual(load_enabled(ui, addons), [])
        self.assertFalse(addons['main'][0]['enabled'])
        save_enabled(ui, None)
        self.assertFalse((ui.character_saved_root/'addons.json').exists())
        self.assertEqual(first.read_bytes(), before)

    def test_explicit_conflict_uses_both_original_defaultstate_outcomes_for_new_character(self):
        self.assertTrue(self.session.logout(), self.session.error)
        self.assertTrue(self.session.create('Fresh Hero', appearance.catalog()['defaults']), self.session.error)
        fresh = self.session.rows[-1]['id']
        self.write(self.first, [['Plain', False], ['OptIn', True]])
        self.write(self.second, [['plain', True], ['optin', False]])
        self.assertTrue(self.session.enter(fresh), self.session.error)
        ui = self.ui(fresh)
        # Native TOC parser already supplies these original DefaultState bits.
        addons = self.addons(Plain=True, OptIn=False)
        self.assertEqual(load_enabled(ui, addons), [])
        self.assertTrue(addons['plain'][0]['enabled'])
        self.assertFalse(addons['optin'][0]['enabled'])
        self.assertFalse((ui.character_saved_root/'addons.json').exists())

    def test_own_explicit_choice_wins_and_failed_save_keeps_only_own_native_rows(self):
        other = self.write(self.first, [['Main', False], ['Inherited', False]])
        own = self.write(self.second, [['MAIN', False], ['main', True], ['RemovedAddon', True]])
        before = other.read_bytes()
        ui = self.ui(self.second)
        addons = self.addons(Main=False, Inherited=True)
        rows = load_enabled(ui, addons)
        self.assertTrue(addons['main'][0]['enabled'])
        self.assertFalse(addons['inherited'][0]['enabled'])
        self.assertEqual(rows, [['MAIN', False], ['main', True], ['RemovedAddon', True]])
        with patch.object(ui, '_write_saved', side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):
                save_enabled(ui, rows)
        self.assertEqual(ui._pending_addon_rows, rows)
        save_enabled(ui, None)
        self.assertIsNone(ui._pending_addon_rows)
        self.assertEqual(json.loads(own.read_text())['rows'], rows)
        self.assertEqual(other.read_bytes(), before)
        self.assertNotIn('Inherited', str(json.loads(own.read_text())['rows']))

    def test_deleted_saved_character_and_orphan_ui_directory_do_not_supply_an_aggregate(self):
        self.assertTrue(self.session.logout(), self.session.error)
        self.assertTrue(self.session.create('Retired Hero', appearance.catalog()['defaults']), self.session.error)
        retired = self.session.rows[-1]['id']
        orphan = self.write(retired, [['Main', False]])
        self.assertTrue(self.session.delete(retired, 'Retired Hero'), self.session.error)
        self.assertTrue(orphan.exists(), 'retirement leaves this separate UI file untouched')
        self.assertTrue(self.session.enter(self.second), self.session.error)
        ui = self.ui(self.second)
        addons = self.addons(Main=True)
        self.assertEqual(load_enabled(ui, addons), [])
        self.assertTrue(addons['main'][0]['enabled'])

    def test_account_boundary_rejects_changed_scope_and_never_reads_other_account(self):
        self.write(self.first, [['Main', False]])
        other = Path(self.directory.name)/'other-addon-account'
        ui = self.ui(self.second, other)
        addons = self.addons(Main=True)
        load_enabled(ui, addons)
        self.assertTrue(addons['main'][0]['enabled'])
        ui.saved_root = self.account
        ui.character_saved_root = self.account/'characters'/self.second
        with self.assertRaisesRegex(ValueError, 'scope changed'):
            load_enabled(ui, self.addons(Main=True))

    def test_profile_directory_links_cannot_redirect_inherited_choices(self):
        first = self.write(self.first, [['Main', False]])
        other = self.account/'characters'/self.second
        other.symlink_to(first.parent, target_is_directory=True)
        ui = SavedUI(self.account, self.first)
        bind_local_roster(ui, self.account, self.first, self.session)
        with self.assertRaisesRegex(ValueError, 'profile scope'):
            load_enabled(ui, self.addons(Main=True))
        self.assertEqual(json.loads(first.read_text())['rows'], [['Main', False]])

    def test_binding_refuses_malformed_registry_missing_save_unlocked_or_closed_sessions(self):
        ui = SavedUI(self.account, self.first)
        cases = [
            ('_registry_valid', False), ('_closed', True), ('phase', 'LOGIN'),
            ('_session_lock', None), ('rows', []), ('rows', [{}]),
            ('rows', [self.session.rows[0]]*11),
            ('rows', [self.session.rows[0], self.session.rows[0]]),
            ('rows', [{'id': '../outside'}]),
            ('rows', [{'id': 'e'*32}]),
        ]
        for attribute, value in cases:
            with self.subTest(attribute=attribute, value_type=type(value).__name__):
                with patch.object(self.session, attribute, value):
                    with self.assertRaises(ValueError):
                        bind_local_roster(ui, self.account, self.first, self.session)
        with tempfile.TemporaryFile() as unrelated_lock:
            with patch.object(self.session, '_session_lock', unrelated_lock):
                with self.assertRaisesRegex(ValueError, 'character lock'):
                    bind_local_roster(ui, self.account, self.first, self.session)
        with self.assertRaises(ValueError):
            bind_local_roster(ui, self.account, self.first, {'rows': self.session.rows})
        with self.assertRaises(ValueError):
            bind_local_roster(ui, self.account, 'f'*32, self.session)

    def test_bound_load_revalidates_roster_and_lock_after_binding(self):
        ui = self.ui(self.second)
        with patch.object(self.session, 'rows', [self.session.rows[0]]):
            with self.assertRaisesRegex(ValueError, 'absent from the roster'):
                load_enabled(ui, self.addons(Main=True))
        with patch.object(self.session, '_session_lock', None):
            with self.assertRaisesRegex(ValueError, 'not locked'):
                load_enabled(ui, self.addons(Main=True))

    def test_corrupt_other_profile_is_preserved_and_does_not_become_an_explicit_choice(self):
        other = self.write(self.first, [['Main', False]])
        bad = '{"schema":"bad","rows":[["Main",false]]}'
        other.write_text(bad)
        ui = self.ui(self.second)
        addons = self.addons(Main=True)
        self.assertEqual(load_enabled(ui, addons), [])
        self.assertTrue(addons['main'][0]['enabled'])
        self.assertIn(other, ui.held_saves)
        save_enabled(ui, None)
        self.assertEqual(other.read_text(), bad)

    def test_unbound_standalone_profile_keeps_its_existing_isolation(self):
        self.write(self.first, [['Main', False]])
        ui = SavedUI(self.account, self.second)
        addons = self.addons(Main=True)
        self.assertEqual(load_enabled(ui, addons), [])
        self.assertTrue(addons['main'][0]['enabled'])


class OriginalAddonInheritance(unittest.TestCase):
    """The unchanged real Lua/TOC loader consumes the same canonical realm bits."""
    setUp = LocalAddonInheritance.setUp
    bind = LocalAddonInheritance.bind
    switch = LocalAddonInheritance.switch
    write = LocalAddonInheritance.write

    def addon(self, name, directives=''):
        folder = self.account.parent/'native-addons'/name
        folder.mkdir(parents=True)
        (folder/(name+'.toc')).write_text('## Interface: 11200\n'+directives+'main.lua\n')
        (folder/'main.lua').write_text(name+'Ran=true')

    def native_ui(self, identity):
        ui = GgEngineUI()
        self.addCleanup(ui.close)
        bind_local_roster(ui, self.account, identity, self.session)
        ui.load_addons(self.account.parent/'native-addons', self.account,
                       character_saved_root=self.account/'characters'/identity)
        return ui

    def test_original_lua_inherited_disable_gates_real_dependency_and_saves_only_own_toggle(self):
        self.addon('Main')
        self.addon('Dependent', '## Dependencies: Main\n')
        self.addon('Other')
        first = self.write(self.first, [['main', False]])
        before = first.read_bytes()
        self.switch(self.second)
        ui = self.native_ui(self.second)
        self.assertEqual(ui.evaluate('return MainRan,DependentRan,OtherRan'), [None, None, True])
        status = {row['id']: row for row in ui.request('addon_status')}
        self.assertEqual(status['Main']['reason'], 'DISABLED')
        self.assertEqual(status['Dependent']['reason'], 'DEP_DISABLED')
        ui.save()
        self.assertFalse((ui.character_saved_root/'addons.json').exists())
        ui.execute("DisableAddOn('Other')")
        ui.save()
        self.assertEqual(json.loads((ui.character_saved_root/'addons.json').read_text())['rows'],
                         [['Other', False]])
        self.assertEqual(first.read_bytes(), before)
        ui.close()
        restored = self.native_ui(self.second)
        self.assertEqual(restored.evaluate('return MainRan,OtherRan'), [None, None])

    def test_original_toc_defaultstate_resolves_conflicts_without_writing_fresh_rows(self):
        self.addon('Plain')
        self.addon('OptIn', '## DefaultState: disabled\n')
        self.write(self.first, [['Plain', False], ['OptIn', True]])
        self.write(self.second, [['Plain', True], ['OptIn', False]])
        self.assertTrue(self.session.logout(), self.session.error)
        self.assertTrue(self.session.create('Fresh Hero', appearance.catalog()['defaults']), self.session.error)
        fresh = self.session.rows[-1]['id']
        self.assertTrue(self.session.enter(fresh), self.session.error)
        ui = self.native_ui(fresh)
        self.assertEqual(ui.evaluate('return PlainRan,OptInRan'), [True, None])
        status = {row['id']: row for row in ui.request('addon_status')}
        self.assertTrue(status['Plain']['enabled'])
        self.assertFalse(status['OptIn']['enabled'])
        self.assertEqual(status['OptIn']['reason'], 'DISABLED')
        ui.save()
        self.assertFalse((ui.character_saved_root/'addons.json').exists())

    def test_real_local_character_enter_automatically_binds_presentation_inheritance(self):
        from PySide6.QtCore import QObject
        from backend.game_engine_presentation import Presentation
        self.write(self.first, [['GGExplorer', False]])
        self.native_parent = QObject()
        self.native_parent._local_characters = self.session
        self.session.setParent(self.native_parent)
        def roots(identity):
            return self.account, self.account/'characters'/identity if identity else self.account
        with patch.object(Presentation, '_addon_roots', staticmethod(roots)):
            presentation = Presentation(self.native_parent, device=False)
            self.native_parent._game_presentation = presentation
            self.addCleanup(presentation.close)
            self.assertTrue(presentation.full_ui)
            self.assertTrue(presentation.set_character(self.first, initial_snapshot=self.runtime.ui_snapshot()))
            self.assertEqual(presentation.lua.evaluate("return IsAddOnLoaded('GGExplorer')"), [None])
            self.assertTrue(self.session.logout(), self.session.error)
            self.assertTrue(self.session.enter(self.second), self.session.error)
            self.assertEqual(presentation.character_key, self.second)
            self.assertEqual(presentation.lua.evaluate("return IsAddOnLoaded('GGExplorer')"), [None])
            presentation.lua.save()
            self.assertFalse((presentation.lua.character_saved_root/'addons.json').exists())
            self.assertTrue(self.session.logout(), self.session.error)
            # Keep teardown inside the same test-only profile scope.
            presentation.close()


if __name__ == '__main__':
    unittest.main()
