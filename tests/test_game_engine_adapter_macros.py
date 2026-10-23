"""Client macros through original native Lua, persistence and the real GG runtime."""
import json, os, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
PROJECT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(PROJECT))
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import QObject
from PySide6.QtGui import QGuiApplication
from backend import game_engine_mmo as mmo, game_engine_items as items
from backend.game_engine_adapter_ui import GgEngineUI
from backend.game_engine_presentation import Presentation, use_action_for
APP=QGuiApplication.instance() or QGuiApplication([])

class Bridge(QObject):
    def __init__(self,runtime):super().__init__();self.runtime=runtime
    def gameEngineActionBarEdit(self,raw):return self.runtime.action_bar_edit(raw)
    def gameEngineActionUse(self,index):return use_action_for(self,self.runtime,index)
    def gameEngineAbility(self,ref):return self.runtime.activate_ability(ref)
    def gameEngineContainerUseItem(self,ref,instance):return self.runtime.action_use_item(ref,instance)
    def gameEngineActionCommand(self,command):return self.runtime.action_command(command)
    def gameEngineTargetClear(self):return self.runtime.clear_target()
    def gameEngineMacroState(self,raw):return self.runtime.set_client_macros(raw)
    def gameEngineClientControl(self,raw):return self.runtime.client_control(raw)

class Macros(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(mmo,'DEFAULT_STASH_PATH',Path(directory)/'unused.json'):
                from backend.game_engine_host import GameEngineRuntime
                cls.Runtime=GameEngineRuntime
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        environment=patch.dict(os.environ,{'XDG_STATE_HOME':self.directory.name});environment.start();self.addCleanup(environment.stop)
        with patch.object(mmo,'DEFAULT_STASH_PATH',Path(self.directory.name)/'stash.json'):self.runtime=self.Runtime()
        self.addCleanup(self.runtime.shutdown)
        self.bridge=Bridge(self.runtime);self.p=Presentation(self.bridge,device=False)
        self.bridge._game_presentation=self.p;self.addCleanup(self.p.close)
        self.ui=self.p.lua;self.assertTrue(self.p.full_ui)
        self.refresh()
    def refresh(self):self.p.last_update=0;self.p.update(self.runtime.snapshot())
    def drain(self):self.p._game_requests(self.ui.request('requests'))
    def create(self,name,body,slot=24,character=False):
        code='local id=CreateMacro('+json.dumps(name)+',1,'+json.dumps(body)+',nil,'+('1' if character else 'nil')+') assert(id) assert(PickupMacro(id)) PlaceAction('+str(slot)+')'
        self.ui.execute(code);self.drain();self.refresh()
    def test_command_ids_do_not_alias_macro_and_cursor_move_roundtrips(self):
        self.create('Real macro','/script ran=(ran or 0)+1')
        attack=self.p.gameplay_views.update(self.runtime.snapshot())['actions'][0]
        self.assertGreater(attack['action_id'],36)
        self.assertEqual(self.runtime._actions.slots[23],{'kind':'MACRO','ref':'1'})
        self.assertEqual(self.ui.evaluate('return GetActionTexture(24),HasAction(24)')[1],1)
        self.ui.execute('PickupAction(24) PlaceAction(23) ClearCursor()');self.drain();self.refresh()
        self.assertEqual(self.runtime._actions.slots[22],{'kind':'MACRO','ref':'1'})
        self.assertFalse(self.runtime._actions.slots[23])
        self.ui.execute('UseAction(23)');self.drain()
        self.assertEqual(self.ui.evaluate('return ran'),[1])
        self.assertFalse(self.p.unsupported_requests,self.p.unsupported_requests)
    def test_direct_host_key_cast_changes_actual_energy_and_cooldown(self):
        ref='ability.surge';name=self.runtime._content['abilities'][ref]['name']
        # Prove the book carries live state even with no standalone ability slot.
        for i,row in enumerate(self.runtime._actions.slots):
            if row.get('ref')==ref:self.runtime._actions.slots[i]={}
        self.refresh();self.create('Cast', '/cast '+name)
        before=self.runtime._resource
        result=self.bridge.gameEngineActionUse(23)
        self.assertNotIn('error',result)
        self.assertLess(self.runtime._resource,before)
        self.assertGreater(self.runtime._ability_cooldowns[ref],0)
        self.refresh()
        usable=self.ui.evaluate('return IsUsableAction(24),GetActionCooldown(24)')
        self.assertIsNone(usable[0]);self.assertGreater(usable[3],0)
        row=self.runtime.snapshot()['actions']['slots'][23]
        self.assertEqual(row['name'],'Cast');self.assertGreater(row['cooldown_s'],0)
    def test_original_last_slot_and_tenth_page_survive_save(self):
        self.create('Last','/script lastSlot=true',slot=120)
        self.assertEqual(self.runtime._actions.slots[119],{'kind':'MACRO','ref':'1'})
        self.ui.execute('UseAction(120)');self.drain()
        self.assertEqual(self.ui.evaluate('return lastSlot'),[True])
        self.runtime.action_bar_edit('{"verb":"PAGE","page":9}')
        self.runtime.save_state();self.runtime._actions.slots[119]={};self.runtime._actions.page=0
        self.runtime.load_state();self.assertEqual(self.runtime._actions.page,9)
        self.assertEqual(self.runtime._actions.slots[119]['ref'],'1')
    def test_events_aliases_addon_slash_and_windows_line_order(self):
        self.ui.execute("""
            macroEvents='' slashArg=nil local f=CreateFrame('Frame')
            f:RegisterEvent('EXECUTE_CHAT_LINE') f:SetScript('OnEvent',function() macroEvents=macroEvents..'['..arg1..']' end)
            SlashCmdList={GGTEST=function(s) slashArg=s end} SLASH_GGTEST1='/custom'
        """)
        self.create('Lines','\r\n /custom hello \r\n\n/script sequence=1\n/script sequence=sequence+1')
        self.assertTrue(self.p.run_macro(1)['ok'])
        self.assertEqual(self.ui.evaluate('return slashArg,sequence,macroEvents'),[
            'hello',2,'[/custom hello][/script sequence=1][/script sequence=sequence+1]'])
    def test_dense_deletion_character_base_edit_and_automatic_save(self):
        self.create('First','/script marker=1')
        self.ui.execute("CreateMacro('Second',1,'/script marker=2') DeleteMacro(1) EditMacro(1,'Edited',nil,'/script marker=3')")
        self.drain();self.refresh()
        self.assertEqual(self.ui.evaluate('local n,t,b=GetMacroInfo(1) return n,b'),['Edited','/script marker=3'])
        self.assertTrue(self.p.run_macro(1)['ok']);self.assertEqual(self.ui.evaluate('return marker'),[3])
        self.create('Character','/script characterMarker=19',slot=22,character=True)
        self.assertEqual(self.runtime._actions.slots[21]['ref'],'19')
        path=self.ui.saved_root/'macros.json';self.assertTrue(path.is_file())
        with GgEngineOwner() as restored:
            empty=Path(self.directory.name)/'empty';empty.mkdir()
            restored.load_addons(empty,self.ui.saved_root)
            self.assertEqual(restored.evaluate('local a,c=GetNumMacros() local n=GetMacroInfo(19) return a,c,n'),[1,1,'Character'])
        self.runtime.save_state();self.runtime._actions.slots[21]={};self.runtime.load_state()
        self.assertEqual(self.runtime._actions.slots[21],{'kind':'MACRO','ref':'19'})
    def test_script_failure_recursion_and_many_intents_are_drained(self):
        self.create('Loop','/script UseAction(24)')
        self.assertEqual(self.p.run_macro(1)['error'],'MACRO_RECURSION_LIMIT')
        self.assertFalse(self.ui.request('requests')['calls'])
        self.ui.execute("EditMacro(1,nil,nil,'/script for i=1,300 do UseAction(24) end')")
        self.assertEqual(self.p.run_macro(1)['error'],'MACRO_INTENT_LIMIT')
        self.assertFalse(self.ui.request('requests')['calls'])
        self.ui.execute("EditMacro(1,nil,nil,'/script UseAction(24) error(\"stop\")')")
        self.assertEqual(self.p.run_macro(1)['error'],'MACRO_SCRIPT_FAILED')
        self.assertFalse(self.ui.request('requests')['calls'])
    def test_unknown_cast_is_grey_but_script_without_cast_stays_usable(self):
        self.create('Missing','/cast ability that does not exist')
        self.assertIsNone(self.ui.evaluate('return IsUsableAction(24)')[0])
        self.ui.execute("EditMacro(1,nil,nil,'/script marker=42')");self.refresh();self.refresh()
        self.assertEqual(self.ui.evaluate('return IsUsableAction(24)')[0],1)
        self.ui.execute('DeleteMacro(1)');self.refresh();self.refresh()
        self.assertEqual(self.p.run_macro(1)['error'],'MACRO_NOT_FOUND')
        self.assertIsNone(self.ui.evaluate('return IsUsableAction(24)')[0])
    def test_use_consumes_real_item_and_unsupported_line_does_not_succeed(self):
        food=next(ref for ref,row in self.runtime._item_catalog['items'].items() if 'RECOVERY' in row.get('tags',[]))
        self.runtime._item_instances['macro-food']=items.make_instance(self.runtime._item_catalog,'macro-food',food,quantity=3)
        self.runtime._inventory=items.inventory_counts(self.runtime._item_instances.values())
        self.runtime._combat_state['actors']['player']['health']-=30;self.refresh()
        self.create('Food','/use '+food)
        self.assertTrue(self.p.run_macro(1)['ok']);self.assertEqual(self.runtime._item_instances['macro-food']['quantity'],2)
        self.ui.execute("EditMacro(1,nil,nil,'/missingcommand')")
        self.assertEqual(self.p.run_macro(1)['error'],'MACRO_COMMAND_UNSUPPORTED')
    def test_local_macro_target_follow_posture_chat_and_roll_use_actual_runtime(self):
        with self.runtime._lock:target=self.runtime._legacy_units_locked()[0]
        self.create('Local', '/targetexact '+target['name']+'\n/follow\n/sit\n/say Local macro message\n/roll 3 3')
        self.assertTrue(self.p.run_macro(1)['ok'])
        self.assertEqual(self.runtime._combat_target_id,target['id'])
        self.assertEqual(self.runtime._follow_id,target['id']);self.assertEqual(self.runtime._stand_state,1)
        self.assertEqual(self.runtime._player_display['sheath'],0)
        messages=[v['text'] for v in self.runtime._events]
        self.assertTrue(any('Local macro message' in v for v in messages))
        self.assertTrue(any('rolls 3 (3-3)' in v for v in messages))
        self.ui.execute("EditMacro(1,nil,nil,'/stand\\n/stopfollow\\n/cleartarget')")
        self.assertTrue(self.p.run_macro(1)['ok'])
        self.assertEqual(self.runtime._stand_state,0);self.assertFalse(self.runtime._follow_id);self.assertFalse(self.runtime._combat_target_id)
        before=len(self.runtime._events)
        self.ui.execute("EditMacro(1,nil,nil,'/roll bad\\n/say must not run')")
        self.assertEqual(self.p.run_macro(1)['error'],'MACRO_INVALID_ROLL')
        self.assertEqual(len(self.runtime._events),before)
    def test_malformed_saved_macros_are_held_and_cannot_erase_existing_file(self):
        root=Path(self.directory.name)/'held';root.mkdir();path=root/'macros.json'
        source='{"schema":"wrong","account":[],"character":[]}'
        path.write_text(source)
        with GgEngineOwner() as ui:
            empty=Path(self.directory.name)/'empty';empty.mkdir()
            ui.load_addons(empty,root)
            ui.execute("CreateMacro('Keep held','Icon','/script keep=true')")
            ui.request('requests');ui.save()
            self.assertEqual(path.read_text(),source)
            self.assertTrue(ui.errors)
    def test_original_macro_cache_import_and_export_use_original_parser(self):
        root=Path(self.directory.name)/'import';path=root/'macros/account/macros-cache.txt'
        path.parent.mkdir(parents=True)
        path.write_text('MACRO 3 "Second" Ability_Ambush\r\n/script second=true\r\nEND\r\nMACRO 1 "First" Ability_BackStab\r\n/script first=true\r\nEND\r\n')
        with GgEngineOwner() as ui:
            empty=Path(self.directory.name)/'empty';empty.mkdir()
            ui.load_addons(empty,root)
            self.assertEqual(ui.evaluate('local a=GetMacroInfo(1) local b=GetMacroInfo(2) return a,b'),['First','Second'])
            self.assertEqual(ui.request('macros')['rows'][0]['texture'],'Interface\\Icons\\Ability_BackStab')
            ui.save();self.assertTrue(path.read_text().startswith('MACRO 1 "First" Ability_BackStab\n'))
            self.assertTrue((root/'macros.json').is_file())

class GgEngineOwner:
    def __enter__(self):self.ui=GgEngineUI();return self.ui
    def __exit__(self,*args):self.ui.close()

if __name__=='__main__':unittest.main()
