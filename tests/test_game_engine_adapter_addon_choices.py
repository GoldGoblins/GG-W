"""Actual roster choices: tri-state, cancel, per-file retry and stale-session refusal."""
import json,unittest
from unittest.mock import patch
from tests import test_game_engine_adapter_addon_inheritance as fixture
from backend.game_engine_adapter_addon_choices import AddonChoices
from backend.game_engine_adapter_addon_state import SCHEMA


class Choices(unittest.TestCase):
    setUp=fixture.LocalAddonInheritance.setUp
    bind=fixture.LocalAddonInheritance.bind
    switch=fixture.LocalAddonInheritance.switch
    ui=fixture.LocalAddonInheritance.ui
    write=fixture.LocalAddonInheritance.write

    def editor(self):
        ui=self.ui(self.first);ui.addon_defaults={'Main':True,'OptIn':False}
        return AddonChoices(ui)

    def test_all_view_real_mixed_state_all_toggle_and_original_unknown_rows_preserved(self):
        self.write(self.first,[['MAIN',False],['Removed',True]])
        self.write(self.second,[['main',True]])
        editor=self.editor();editor.select('')
        view=editor.view([dict(id='Main'),dict(id='OptIn')])
        self.assertTrue(view['rows'][0]['mixed']);self.assertFalse(view['rows'][1]['enabled'])
        editor.set('Main',False);self.assertFalse(editor.view([dict(id='Main')])['rows'][0]['mixed'])
        editor.save()
        for identity in (self.first,self.second):
            rows=json.loads((self.account/'characters'/identity/'addons.json').read_text())['rows']
            self.assertEqual(rows[-1],['Main',False])
        self.assertIn(['Removed',True],json.loads((self.account/'characters'/self.first/'addons.json').read_text())['rows'])

    def test_selected_other_character_and_cancel_never_change_active_or_write_draft(self):
        first=self.write(self.first,[['Main',True]]);before=first.read_bytes()
        editor=self.editor();editor.select(self.second);editor.set('Main',False)
        self.assertEqual(first.read_bytes(),before);self.assertFalse((self.account/'characters'/self.second/'addons.json').exists())
        fresh=self.editor();fresh.select(self.second);self.assertTrue(fresh.view([dict(id='Main')])['rows'][0]['enabled'])
        editor.save();self.assertEqual(first.read_bytes(),before)
        self.assertFalse(json.loads((self.account/'characters'/self.second/'addons.json').read_text())['rows'][0][1])

    def test_failed_later_file_keeps_remaining_draft_and_retry_does_not_rewrite_saved_file(self):
        editor=self.editor();editor.select('');editor.set('Main',False)
        original=editor.ui._write_saved;calls=[]
        def write(path,source):
            calls.append(path)
            if path.parent.name==self.second:raise OSError('Authored disk failure')
            original(path,source)
        with patch.object(editor.ui,'_write_saved',side_effect=write):
            with self.assertRaises(OSError):editor.save()
        self.assertNotIn(self.first,editor.pending);self.assertIn(self.second,editor.pending)
        first=self.account/'characters'/self.first/'addons.json';before=first.read_bytes();stamp=first.stat().st_mtime_ns
        editor.save();self.assertEqual(first.read_bytes(),before);self.assertEqual(first.stat().st_mtime_ns,stamp);self.assertFalse(editor.pending)

    def test_concurrent_external_choice_and_character_switch_cannot_overwrite_frozen_target(self):
        path=self.write(self.first,[['Main',True]]);editor=self.editor();editor.set('Main',False)
        path.write_text(json.dumps(dict(schema=SCHEMA,rows=[['Main',True],['OptIn',True]])));before=path.read_bytes()
        with self.assertRaisesRegex(ValueError,'changed while'):editor.save()
        self.assertEqual(path.read_bytes(),before)
        self.switch(self.second)
        with self.assertRaisesRegex(ValueError,'scope changed'):editor.save()
        self.assertEqual(path.read_bytes(),before)

    def test_malformed_held_file_is_preserved_and_unknown_selection_never_creates_profile(self):
        path=self.write(self.second,[['Main',True]]);path.write_text('not json');before=path.read_bytes()
        with self.assertRaisesRegex(ValueError,'repair'):self.editor()
        self.assertEqual(path.read_bytes(),before)
        path.write_text(json.dumps(dict(schema=SCHEMA,rows=[])));editor=self.editor()
        with self.assertRaises(ValueError):editor.select('unregistered')
        self.assertFalse((self.account/'characters'/'unregistered').exists())


if __name__=='__main__':unittest.main()
