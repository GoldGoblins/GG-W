"""Real original Lua settings with shared account and isolated local characters."""
import copy, json, os, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QObject
from PySide6.QtGui import QGuiApplication
from backend.game_engine_adapter_ui import GgEngineUI

APP = QGuiApplication.instance() or QGuiApplication([])


class ScopedState(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.addons = self.root/'addons'
        folder = self.addons/'Scopes'
        folder.mkdir(parents=True)
        (folder/'Scopes.toc').write_text('## Interface: 11200\n## SavedVariables: SharedCounter\n## SavedVariablesPerCharacter: PersonalCounter\nmain.lua\n')
        (folder/'main.lua').write_text("SharedCounter=SharedCounter or 0;PersonalCounter=PersonalCounter or 0;f=CreateFrame('Frame');f:RegisterEvent('ADDON_LOADED');f:SetScript('OnEvent',function() if arg1=='Scopes' then loadedShared=SharedCounter;loadedPersonal=PersonalCounter end end);Placed=CreateFrame('Frame','Placed');Placed:SetMovable(true);Placed:SetResizable(true);Placed:SetWidth(50);Placed:SetHeight(30);Placed:SetPoint('TOPLEFT',UIParent,'TOPLEFT',1,-2)")
        self.account = self.root/'account'

    def open(self, name=None):
        ui = GgEngineUI()
        self.addCleanup(ui.close)
        ui.load_addons(self.addons, self.account,
                       character_saved_root=self.root/name if name else None)
        return ui

    def test_addon_variables_macros_and_keys_follow_exact_character_after_restart(self):
        a = self.open('A')
        self.assertEqual(a.evaluate('return loadedShared,loadedPersonal'), [0, 0])
        a.execute("SharedCounter=7;PersonalCounter=11;CreateMacro('Shared',1,'/script shared=1');CreateMacro('PrivateA',1,'/script personal=1',nil,1);SetBinding('CTRL-G','SHARED');SaveBindings(1)")
        a.save()  # original binding saves snapshot keys at the host drain
        a.execute("SetBinding('ALT-J','PRIVATE_A');SaveBindings(2)")
        a.request('requests')  # normal generation-driven macro persistence
        a.save();a.close()
        b = self.open('B')
        self.assertEqual(b.evaluate('return loadedShared,loadedPersonal'), [7, 0])
        self.assertEqual(b.evaluate('return GetNumMacros()'), [1, 0])
        self.assertEqual(b.evaluate("return GetBindingAction('CTRL-G')"), ['SHARED'])
        self.assertNotEqual(b.evaluate("return GetBindingAction('ALT-J')"), ['PRIVATE_A'])
        b.execute("SharedCounter=9;PersonalCounter=22;CreateMacro('PrivateB',1,'/script personal=2',nil,1);SetBinding('ALT-J','PRIVATE_B');SaveBindings(2)")
        b.save();b.close()
        again = self.open('A')
        self.assertEqual(again.evaluate('return loadedShared,loadedPersonal'), [9, 11])
        self.assertEqual(again.evaluate('return GetNumMacros()'), [1, 1])
        self.assertEqual(again.evaluate('return GetMacroInfo(19)')[0], 'PrivateA')
        self.assertEqual(again.evaluate("return GetBindingAction('ALT-J')"), ['PRIVATE_A'])
        self.assertEqual(again.evaluate("return GetMacroIndexByName('PrivateB')"), [0])

    def test_scoped_saves_preserve_flat_legacy_character_macros(self):
        legacy = self.open()
        legacy.execute("CreateMacro('Legacy',1,'/script legacy=1',nil,1)")
        legacy.save();legacy.close()
        scoped = self.open('A')
        self.assertEqual(scoped.evaluate('return GetNumMacros()'), [0, 0])
        scoped.execute("CreateMacro('OwnA',1,'/script own=1',nil,1)")
        scoped.save();scoped.close()
        restored = self.open()
        self.assertEqual(restored.evaluate('return GetMacroInfo(19)')[0], 'Legacy')
        self.assertEqual(restored.evaluate("return GetMacroIndexByName('OwnA')"), [0])

    def test_original_chat_colors_windows_and_multiple_anchors_restore_per_character(self):
        a=self.open('A')
        a.execute("ChangeChatColor('SAY',0.25,0.5,0.75);SetChatWindowName(1,'A chat');SetChatWindowSize(1,18);Placed:SetUserPlaced(true);Placed:SetWidth(121);Placed:SetHeight(72);Placed:ClearAllPoints();Placed:SetPoint('TOPLEFT',UIParent,'TOPLEFT',13,-17);Placed:SetPoint('BOTTOMRIGHT',UIParent,'BOTTOMRIGHT',-23,31)")
        packet=a.request('requests');self.assertIsInstance(packet['ui_cache'],dict)
        state=packet['ui_cache'];self.assertEqual(len(state['frames'][0]['points']),2)
        placed=a.evaluate('return Placed:GetWidth(),Placed:GetHeight(),Placed:GetNumPoints(),Placed:IsUserPlaced()')
        # Two opposite anchors determine resolved size; the saved authored
        # width/height must still be preserved for later anchor edits.
        self.assertEqual(state['frames'][0]['width'],121)
        a.save();a.close()
        b=self.open('B');self.assertEqual(b.evaluate('return GetChatWindowInfo(1)')[0],'')
        self.assertEqual(b.evaluate('return Placed:GetWidth(),Placed:GetNumPoints()'),[50,1]);b.close()
        again=self.open('A');self.assertEqual(again.evaluate('return GetChatWindowInfo(1)')[0],'A chat')
        self.assertEqual(again.evaluate('return Placed:GetWidth(),Placed:GetHeight(),Placed:GetNumPoints(),Placed:IsUserPlaced()'),placed)
        self.assertEqual(again.request('ui_cache')['colors'],state['colors'])
        self.assertEqual(again.request('ui_cache')['frames'],state['frames'])
        self.assertIsNone(again.request('requests')['ui_cache'])

    def test_invalid_ui_cache_is_atomic_and_held_file_is_not_overwritten(self):
        a=self.open('A');before=a.request('ui_cache');bad=copy.deepcopy(before)
        bad['colors'][0]['rgb']=[10,20,30];bad['frames']=[dict(name='Placed',width=999,height=999,points=[dict(point='TOPLEFT',relative_to=None,relative_point='TOPLEFT',x=1000001,y=0)])]
        with self.assertRaises(ValueError):a.request('ui_cache_load',state=bad)
        self.assertEqual(a.request('ui_cache'),before);a.close()
        path=self.root/'A'/'ui-cache.json';source='{"schema":"invalid","frames":[]}'
        path.parent.mkdir(exist_ok=True);path.write_text(source)
        held=self.open('A');held.execute("SetChatWindowName(1,'Must not erase')");held.request('requests');held.save();held.close()
        self.assertEqual(path.read_text(),source);self.assertTrue(held.errors)

    def test_failed_macro_write_keeps_drained_ui_cache_for_retry(self):
        a=self.open('A');a.execute("CreateMacro('Pending',1,'/script pending=true');SetChatWindowName(1,'Retry chat')")
        with patch.object(a,'_write_saved',side_effect=OSError('injected cache write failure')):
            with self.assertRaises(OSError):a.request('requests')
        self.assertIsNotNone(a._ui_cache_pending)
        a._ui_cache_changed_at=0;a.request('requests')
        path=self.root/'A'/'ui-cache.json';self.assertEqual(json.loads(path.read_text())['windows'][0]['name'],'Retry chat')

    def test_corrupt_character_file_is_held_without_breaking_other_profile(self):
        path = self.root/'A'/'macros.json'
        path.parent.mkdir()
        original = '{"schema":"wrong","account":[],"character":[]}'
        path.write_text(original)
        a = self.open('A')
        a.execute("CreateMacro('Cannot erase',1,'/script held=1',nil,1)")
        a.request('requests');a.save();a.close()
        self.assertEqual(path.read_text(), original)
        b = self.open('B')
        self.assertEqual(b.evaluate('return GetNumMacros()'), [0, 0])
        self.assertNotIn(self.root/'B'/'macros.json', b.held_saves)

    def test_character_link_cannot_load_or_overwrite_outside_scope(self):
        outside = self.root/'outside.json'
        outside.write_text('{"schema":"gg.engine.macros.v1","account":[],"character":[]}')
        profile = self.root/'A'
        profile.mkdir()
        (profile/'macros.json').symlink_to(outside)
        a = self.open('A')
        a.execute("CreateMacro('Cannot escape',1,'/script held=1',nil,1)")
        before = outside.read_bytes()
        a.request('requests');a.save()
        self.assertEqual(outside.read_bytes(), before)
        self.assertIn(profile/'macros.json', a.held_saves)

    def test_inactive_stale_vm_cannot_overwrite_shared_state(self):
        a = self.open('A')
        inactive = self.open()
        inactive.saving_enabled = False
        a.execute("SharedCounter=99;CreateMacro('Current shared',1,'/script current=1')")
        a.save()
        path = self.account/'macros.json'
        before = path.read_bytes()
        inactive.execute("SharedCounter=2;CreateMacro('Stale shared',1,'/script stale=1')")
        inactive.request('requests');inactive.save();inactive.close()
        self.assertEqual(path.read_bytes(), before)
        restored = self.open('B')
        self.assertEqual(restored.evaluate('return loadedShared'), [99])
        self.assertEqual(restored.evaluate("return GetMacroIndexByName('Stale shared')"), [0])


class CharacterUi(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        from backend import game_engine_mmo as mmo,game_engine_character_creation as appearance
        for context in (patch.dict(os.environ, {'XDG_STATE_HOME': directory.name}),
                        patch.object(mmo, 'DEFAULT_STASH_PATH', self.root/'stash.json'),
                        patch.object(appearance, 'STATE_PATH', self.root/'appearance.json')):
            context.start();self.addCleanup(context.stop)
        from backend.game_engine_host import GameEngineRuntime
        from backend.game_engine_presentation import Presentation
        from backend.game_engine_local_characters import LocalCharacters
        self.runtime = GameEngineRuntime()
        self.addCleanup(self.runtime.shutdown)
        self.bridge = QObject()
        self.bridge._game_presentation = Presentation(self.bridge, device=False)
        self.presentation = self.bridge._game_presentation
        self.addCleanup(self.presentation.close)
        self.session = LocalCharacters(self.bridge, root=self.root/'characters', runtime=self.runtime)
        self.addCleanup(self.session.close)
        self.assertTrue(self.session.open(), self.session.error)
        self.a = self.session.rows[0]['id']
        self.assertTrue(self.session.create('Andra', appearance.catalog()['defaults']), self.session.error)
        self.b = next(r['id'] for r in self.session.rows if r['name'] == 'Andra')

    def test_actual_selection_replaces_vm_and_transient_sessions_and_restores_macros(self):
        self.assertTrue(self.session.enter(self.a), self.session.error)
        first = self.presentation.lua
        first.execute("unsavedMarker='A';CreateMacro('PrivateA',1,'/script a=1',nil,1)")
        self.runtime.open_crafting()
        self.assertTrue(self.session.logout(), self.session.error)
        self.assertTrue(first.closed)
        self.assertFalse(self.runtime._engine_craft_book)
        self.assertTrue(self.session.enter(self.b), self.session.error)
        self.assertEqual(self.presentation.lua.evaluate('return unsavedMarker,GetNumMacros()'), [None, 0, 0])
        self.presentation.lua.execute("CreateMacro('PrivateB',1,'/script b=1',nil,1)")
        self.assertTrue(self.session.logout(), self.session.error)
        self.assertTrue(self.session.enter(self.a), self.session.error)
        self.assertEqual(self.presentation.lua.evaluate('return GetMacroInfo(19)')[0], 'PrivateA')
        self.assertEqual(self.presentation.lua.evaluate("return GetMacroIndexByName('PrivateB')"), [0])

    def test_failed_ui_save_blocks_close_and_failed_next_vm_retains_previous(self):
        self.assertTrue(self.session.enter(self.a), self.session.error)
        previous = self.presentation.lua
        with patch.object(previous, 'save', side_effect=OSError('injected disk failure')):
            self.assertFalse(self.session.close())
        self.assertEqual(self.session.active_id, self.a)
        self.assertIs(self.presentation.lua, previous)
        self.assertFalse(previous.closed)
        self.assertTrue(self.session.logout(), self.session.error)
        previous = self.presentation.lua
        with patch.object(GgEngineUI, 'load_addons', side_effect=ValueError('injected loader failure')):
            self.assertFalse(self.session.enter(self.b))
        self.assertIs(self.presentation.lua, previous)
        self.assertFalse(previous.closed)
        self.assertEqual(self.session.phase, 'CHARACTERS')
        self.assertEqual(self.session.active_id, '')
        self.assertIsNone(self.presentation.character_key)
        self.assertTrue(self.session.enter(self.b), self.session.error)

    def test_addons_see_selected_character_in_files_login_events_and_ui_reload(self):
        folder=self.root/'qml/game/framexml/LoginProbe'
        folder.mkdir(parents=True)
        (folder/'LoginProbe.toc').write_text('## Interface: 11200\nmain.lua\n')
        (folder/'main.lua').write_text("""
            seen={};fileName=UnitName('player');fileMoney=GetMoney()
            local f=CreateFrame('Frame')
            for _,e in ipairs({'ADDON_LOADED','PLAYER_LOGIN','PLAYER_ENTERING_WORLD'}) do f:RegisterEvent(e) end
            f:SetScript('OnEvent',function()
                seen[event]={UnitName('player'),GetMoney(),UnitXP('player'),GetContainerNumSlots(0)}
            end)
        """)
        def check():
            snapshot=self.runtime.ui_snapshot()
            from backend.game_engine_adapter_gameplay import GameplayViews
            data=GameplayViews().update(snapshot)
            name=snapshot['player']['name'];money=data['money_copper']
            self.assertEqual(self.presentation.lua.evaluate('return fileName,fileMoney'),[name,money])
            for event in ('ADDON_LOADED','PLAYER_LOGIN','PLAYER_ENTERING_WORLD'):
                observed=self.presentation.lua.evaluate('return unpack(seen['+json.dumps(event)+'])')
                self.assertEqual(observed[:3],[name,money,snapshot['progression']['xp']])
                self.assertGreater(observed[3],0)
        with patch('backend.game_engine_presentation.PROJECT',self.root):
            self.assertTrue(self.session.enter(self.a),self.session.error);check()
            self.runtime._economy_state['wallet']['gold']=891;self.runtime._progression['xp']=77
            self.assertTrue(self.session.logout(),self.session.error)
            self.assertTrue(self.session.enter(self.b),self.session.error);check()
            self.assertTrue(self.session.logout(),self.session.error)
            self.assertTrue(self.session.enter(self.a),self.session.error);check()
            self.assertEqual(self.runtime._economy_state['wallet']['gold'],891)
            self.assertTrue(self.presentation._reload_ui());check()


if __name__ == '__main__':unittest.main()
