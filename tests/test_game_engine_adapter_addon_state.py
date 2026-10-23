"""Original addon enable verbs with durable local choices and guarded reloads."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QObject
from PySide6.QtGui import QGuiApplication
from backend.game_engine_adapter_ui import GgEngineUI
from backend.game_engine_adapter_addon_state import SCHEMA

APP = QGuiApplication.instance() or QGuiApplication([])


class AddonState(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.addons = self.root/'addons'
        self.account = self.root/'account'
        self.addon('Main')

    def addon(self, name, directives='', source=None):
        folder = self.addons/name
        folder.mkdir(parents=True, exist_ok=True)
        (folder/(name+'.toc')).write_text('## Interface: 11200\n## Title: '+name+'\n'+directives+'main.lua\n')
        (folder/'main.lua').write_text(source or name+'Ran=true')

    def open(self, character='A'):
        ui = GgEngineUI()
        self.addCleanup(ui.close)
        ui.load_addons(self.addons, self.account, character_saved_root=self.root/character)
        return ui

    def test_clean_character_does_not_write_enable_defaults(self):
        ui = self.open()
        self.assertEqual(ui.evaluate("return MainRan,GetNumAddOns()"), [True, 1])
        ui.save()
        self.assertFalse((self.root/'A'/'addons.json').exists())

    def test_enable_choices_survive_restart_and_are_isolated_from_other_characters(self):
        ui = self.open()
        ui.execute("DisableAddOn('main');ResetDisabledAddOns()")
        self.assertTrue(ui.request('addon_status')[0]['enabled'])
        ui.save()
        self.assertFalse((self.root/'A'/'addons.json').exists())
        ui.execute("DisableAddOn('MAIN')")
        ui.save();ui.close()
        again = self.open()
        self.assertEqual(again.evaluate('return MainRan,IsAddOnLoaded("Main")'), [None, None])
        self.assertEqual(again.request('addon_status')[0]['reason'], 'DISABLED')
        other = self.open('B')
        self.assertEqual(other.evaluate('return MainRan'), [True])
        again.execute("EnableAllAddOns()")
        again.save();again.close()
        restored = self.open()
        self.assertEqual(restored.evaluate('return MainRan'), [True])

    def test_disabled_required_dependency_blocks_startup_without_breaking_sibling(self):
        self.addon('Base')
        self.addon('Dependent', '## Dependencies: Base\n')
        self.addon('Optional', '## OptionalDeps: Base\n')
        path = self.root/'A'/'addons.json'
        path.parent.mkdir()
        path.write_text(json.dumps({'schema': SCHEMA, 'rows': [['Base', False]]}))
        ui = self.open()
        self.assertEqual(ui.evaluate('return MainRan,BaseRan,DependentRan,OptionalRan'),
                         [True, None, None, True])
        status = {r['id']: r for r in ui.request('addon_status')}
        self.assertFalse(status['Dependent']['loaded'])
        self.assertEqual(status['Dependent']['reason'], 'DEP_DISABLED')

    def test_disabled_on_demand_addon_loads_only_after_original_enable_verb(self):
        self.addon('Demand', '## LoadOnDemand: 1\n## SavedVariablesPerCharacter: Saved\n',
                   'DemandRan=true;Saved=Saved or 0')
        path = self.root/'A'/'addons.json'
        path.parent.mkdir()
        path.write_text(json.dumps({'schema': SCHEMA, 'rows': [['Demand', False], ['Uninstalled', True]]}))
        ui = self.open()
        self.assertEqual(ui.evaluate("return LoadAddOn('Demand')"), [None, 'DISABLED'])
        ui.execute("EnableAddOn('Demand')")
        self.assertEqual(ui.evaluate("return LoadAddOn('Demand')"), [1, None])
        ui.execute('Saved=83')
        ui.save();ui.close()
        self.assertIn(['Uninstalled', True], json.loads(path.read_text())['rows'])
        restored = self.open()
        self.assertEqual(restored.evaluate('return DemandRan'), [None])
        self.assertEqual(restored.evaluate("return LoadAddOn('Demand'),Saved"), [1, 83])

    def test_failed_save_retains_both_enable_rows_and_binding_request_for_retry(self):
        ui = self.open()
        ui.execute("DisableAddOn('Main');SetBinding('ALT-P','PRIVATE');SaveBindings(2)")
        with patch.object(ui, '_write_saved', side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):ui.save()
        self.assertIsNotNone(ui._pending_addon_rows)
        self.assertTrue(ui._bindings_pending)
        ui.save();ui.close()
        restored = self.open()
        self.assertEqual(restored.evaluate('return MainRan'), [None])
        self.assertEqual(restored.evaluate("return GetBindingAction('ALT-P')"), ['PRIVATE'])

    def test_corrupt_enable_file_is_kept_and_cannot_erase_another_profile(self):
        path = self.root/'A'/'addons.json'
        path.parent.mkdir()
        before = '{"schema":"wrong","rows":[["Main",false]]}'
        path.write_text(before)
        ui = self.open()
        self.assertIn(path, ui.held_saves)
        ui.save()
        self.assertEqual(path.read_text(), before)
        ui.execute("DisableAddOn('Main')")
        with self.assertRaises(ValueError):ui.save()
        self.assertEqual(path.read_text(), before)
        self.assertEqual(self.open('B').evaluate('return MainRan'), [True])


class AddonPresentation(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        context = patch.dict(os.environ, {'XDG_STATE_HOME': directory.name})
        context.start();self.addCleanup(context.stop)
        from backend.game_engine_presentation import Presentation
        self.parent = QObject()
        self.presentation = Presentation(self.parent, device=False)
        self.addCleanup(self.presentation.close)
        self.assertTrue(self.presentation.full_ui)

    def test_own_ui_reload_keeps_profile_and_rejects_previous_character_buttons(self):
        p = self.presentation
        a, b = 'a'*32, 'b'*32
        self.assertTrue(p.set_character(a))
        generation = json.loads(p.addonsJson)['generation']
        self.assertTrue(p.setAddon('GGExplorer', False, generation))
        old = p.lua
        self.assertTrue(p.reloadAddons(generation))
        self.assertTrue(old.closed)
        self.assertEqual(p.character_key, a)
        self.assertEqual(p.lua.evaluate("return IsAddOnLoaded('GGExplorer')"), [None])
        self.assertFalse(p.setAddon('GGExplorer', True, generation))
        self.assertTrue(p.set_character(b))
        self.assertEqual(p.lua.evaluate("return IsAddOnLoaded('GGExplorer')"), [1])
        self.assertFalse(p.reloadAddons(generation))

    def test_failed_reload_leaves_current_vm_and_choice_available_for_retry(self):
        p = self.presentation
        self.assertTrue(p.set_character('c'*32))
        generation = json.loads(p.addonsJson)['generation']
        old = p.lua
        with patch('backend.game_engine_adapter_ui.GgEngineUI', side_effect=ValueError('prepare failed')):
            self.assertFalse(p.reloadAddons(generation))
        self.assertIs(p.lua, old)
        self.assertFalse(old.closed)
        self.assertTrue(p.reloadAddons(generation))

    def test_selection_vm_has_no_authority_to_change_addon_files(self):
        p = self.presentation
        p.local_character_mode = True
        p.lua.saving_enabled = False
        p.refreshAddons()
        self.assertFalse(json.loads(p.addonsJson)['can_edit'])
        self.assertFalse(p.setAddon('GGExplorer', False, p._ui_generation))
        self.assertFalse((self.root/'goldgoblins'/'gg-game'/'addons'/'addons.json').exists())


if __name__ == '__main__':
    unittest.main()
