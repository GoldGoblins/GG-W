"""Existing settings and world links survive the GG namespace migration."""
import unittest
from backend.game_engine_legacy import schema_matches, manifest_path
from backend.game_engine_adapter_assets import asset_path
from backend.game_engine_adapter_addon_state import enable_rows


class EngineLegacyTests(unittest.TestCase):
    def test_only_matching_legacy_schemas_are_accepted(self):
        for suffix in ('.macros.v1', '.addons.v1', '-world.v1', '-world-save.v1'):
            self.assertTrue(schema_matches('gg.benilla'+suffix, 'gg.engine'+suffix))
            self.assertFalse(schema_matches('gg.benilla'+suffix, 'gg.engine.other.v1'))
        for malformed in (None, {}, 1, 'gg.benilla.addons.v2', 'other.engine.addons.v1'):
            self.assertFalse(schema_matches(malformed, 'gg.engine.addons.v1'))

    def test_existing_addon_choices_keep_their_validation(self):
        self.assertEqual(enable_rows({'schema':'gg.benilla.addons.v1', 'rows':[]}), [])
        with self.assertRaises(ValueError):
            enable_rows({'schema':'gg.benilla.addons.v1', 'rows':'invalid'})

    def test_old_relative_and_file_urls_resolve_to_the_same_world(self):
        old='game/worlds/benilla-demo/world.json'
        new=asset_path('game/worlds/engine-demo/world.json')
        self.assertEqual(asset_path(old), new)
        self.assertEqual(asset_path('qml/'+old), new)
        previous=new.parent.with_name('benilla-demo')/new.name
        self.assertEqual(asset_path(previous.as_uri()), new)
        self.assertEqual(manifest_path('game/worlds/benilla-demo-copy/world.json'), 'game/worlds/benilla-demo-copy/world.json')
        with self.assertRaises(ValueError):asset_path('game/worlds/benilla-demo/../../../../../outside')
