"""The GUI verifier provisions loadable real items before any custody pins."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QUICK_CONTROLS_STYLE', 'Basic')
from PySide6.QtGui import QGuiApplication
from backend import game_engine_mmo as mmo, game_engine_character_creation as appearance
from backend import game_engine_enchants as enchants, game_engine_gear as gear
from backend.game_engine_local_characters import LocalCharacters, CharacterStore
from backend.game_engine_local_custody import LocalCustodyStore
from tools.world.verify_local_trade_enchant_client import (
    prepare_saved_fixture, GEAR, FIRST_SCROLL, SELECTED_SCROLL, OLD_ENCHANT, NEW_ENCHANT)

APP = QGuiApplication.instance() or QGuiApplication([])


class EnchantVerifierFixture(unittest.TestCase):
    def test_canonical_equipped_bound_source_and_distinct_scrolls_survive_saved_login_and_fresh_disk(self):
        with tempfile.TemporaryDirectory(prefix='gg-enchant-verifier-test-') as directory:
            root = Path(directory)
            environment = {'XDG_'+name+'_HOME': str(root / name.lower())
                           for name in ('STATE', 'DATA', 'CONFIG', 'CACHE')}
            with patch.dict(os.environ, environment), \
                    patch.object(mmo, 'DEFAULT_STASH_PATH', root / 'stash.json'), \
                    patch.object(appearance, 'STATE_PATH', root / 'appearance.json'):
                from backend.game_engine_host import GameEngineRuntime
                runtime = GameEngineRuntime()
                session = LocalCharacters(root=root / 'characters', runtime=runtime)
                try:
                    self.assertTrue(session.open(), session.error)
                    owner = session.rows[0]['id']
                    self.assertTrue(session.create('Actual fixture provider', appearance.catalog()['defaults']), session.error)
                    provider = session.rows[1]['id']
                    originals = {key: session.store.load(key) for key in (owner, provider)}
                    fixture = prepare_saved_fixture(session, owner, provider,
                                                    runtime._item_catalog, runtime._gear_tables)
                    original = next(row for row in originals[owner]['item_instances'] if row['instance_id'] == GEAR)
                    expected = copy.deepcopy(original)
                    table = dict(runtime._gear_tables, enchantments=dict(runtime._gear_tables['enchantments'],
                        **{OLD_ENCHANT: enchants.definition(OLD_ENCHANT)}))
                    self.assertTrue(gear.apply_enchant(expected['gear'], OLD_ENCHANT, table)[0])
                    expected['bound_to'] = owner
                    self.assertTrue(session.enter(owner), session.error)
                    runtime.pause()
                    self.assertEqual(runtime._item_instances[GEAR], expected)
                    self.assertEqual(runtime._item_instances[GEAR]['location'], 'EQUIPPED')
                    self.assertTrue(session.logout(), session.error)
                    self.assertTrue(session.enter(provider), session.error)
                    runtime.pause()
                    physical = {identifier: copy.deepcopy(runtime._item_instances[identifier])
                                for identifier in (FIRST_SCROLL, SELECTED_SCROLL)}
                    self.assertEqual(physical[FIRST_SCROLL]['name'], physical[SELECTED_SCROLL]['name'])
                    for row in physical.values():
                        self.assertEqual(row['quantity'], 1)
                        self.assertEqual(row['scroll_enchant_id'], NEW_ENCHANT)
                        self.assertEqual(row['owner_id'], 'player')
                        self.assertEqual(row['location'], 'INVENTORY')
                    self.assertNotEqual(physical[FIRST_SCROLL]['slot_index'], physical[SELECTED_SCROLL]['slot_index'])
                    self.assertTrue(session.close(), session.error)
                    fresh = LocalCustodyStore(session.root).snapshot()
                    self.assertFalse(fresh['shared'].get('direct_trades'))
                    disk = CharacterStore(session.root)
                    own = {row['instance_id']: row for row in disk.load(owner)['item_instances']}
                    provided = {row['instance_id']: row for row in disk.load(provider)['item_instances']}
                    self.assertEqual(own[GEAR], expected)
                    self.assertEqual({identifier: provided[identifier] for identifier in physical}, physical)
                    self.assertEqual(fixture['owner']['inventory'], originals[owner]['inventory'])
                finally:
                    session.close()
                    runtime.shutdown()


if __name__ == '__main__':
    unittest.main()
