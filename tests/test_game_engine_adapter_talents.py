"""Actual original Lua talent spending over durable GG progression rules."""
import copy,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import QObject,Signal
from PySide6.QtGui import QGuiApplication
from backend import game_engine_mmo as mmo,game_engine_character_creation as appearance
from backend.game_engine_presentation import Presentation
APP=QGuiApplication.instance() or QGuiApplication([])

class Bridge(QObject):
    snapshotPublished=Signal(object)
    def __init__(self,runtime):super().__init__();self.runtime=runtime
    def gameEngineTalent(self,key):return json.dumps(self.runtime.add_talent(key))
    def gameEngineClientControl(self,raw):return json.dumps(self.runtime.client_control(raw))

class Talents(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        for context in (patch.dict(os.environ,{'XDG_STATE_HOME':directory.name}),
                        patch.object(mmo,'DEFAULT_STASH_PATH',Path(directory.name)/'stash.json'),
                        patch.object(appearance,'STATE_PATH',Path(directory.name)/'appearance.json')):
            context.start();self.addCleanup(context.stop)
        from backend.game_engine_host import GameEngineRuntime
        self.runtime=GameEngineRuntime();self.addCleanup(self.runtime.shutdown)
        self.bridge=Bridge(self.runtime);self.presentation=Presentation(self.bridge,device=False);self.addCleanup(self.presentation.close)
        self.assertTrue(self.presentation.full_ui);self.ui=self.presentation.lua
        self.ui.execute("talentEvents=0;talentErrors={};f=CreateFrame('Frame');f:RegisterEvent('CHARACTER_POINTS_CHANGED');f:RegisterEvent('UI_ERROR_MESSAGE');f:SetScript('OnEvent',function() if event=='CHARACTER_POINTS_CHANGED' then talentEvents=talentEvents+1 else table.insert(talentErrors,arg1) end end)")
        self.publish()
    def publish(self):
        self.presentation.last_update=0;self.presentation.update(self.runtime.ui_snapshot())
        self.assertFalse(self.presentation.errors,self.presentation.errors)
    def action(self,script):
        self.ui.execute(script);self.presentation._ui_requests(self.ui.request('requests'));self.publish()
    def test_points_are_actually_spent_and_repeated_unknown_requests_do_not_mint(self):
        self.assertEqual(self.ui.evaluate("return GetNumTalentTabs(),GetNumTalents(1),UnitCharacterPoints('player')"),[1,3,2,0])
        self.assertEqual(self.ui.evaluate('return GetTalentInfo(1,1)')[0],'Trailblazer')
        gold=self.runtime._economy_state['wallet']['gold'];xp=self.runtime._progression['xp']
        self.action('LearnTalent(1,1);LearnTalent(1,1);LearnTalent(1,1);LearnTalent(2,99)')
        self.assertEqual(self.runtime._progression['talents']['trailblazer'],3)
        self.assertEqual(self.runtime._progression['talent_points'],0)
        self.assertEqual(self.ui.evaluate("return UnitCharacterPoints('player')"),[0,0])
        self.assertEqual((self.runtime._economy_state['wallet']['gold'],self.runtime._progression['xp']),(gold,xp))
        self.assertGreater(self.ui.evaluate('return table.getn(talentErrors)')[0],0)
        count=self.ui.evaluate('return talentEvents')[0];self.publish();self.assertEqual(self.ui.evaluate('return talentEvents')[0],count)
    def test_queued_index_resolves_the_shown_talent_after_state_reorder(self):
        self.ui.execute('LearnTalent(1,2)')
        self.runtime._progression['talents']={'skybound':0,'trailblazer':1,'tidewalker':0}
        # Normal update drains against the old visible rows before publishing
        # the reordered authoritative snapshot into the original Lua core.
        self.runtime._ui_snapshot_base=None;self.publish()
        self.assertEqual(self.runtime._progression['talents'],{'skybound':0,'trailblazer':1,'tidewalker':1})
        self.assertEqual(self.runtime._progression['talent_points'],1)
    def test_save_restore_and_respec_refund_preserve_real_point_budget(self):
        self.action('LearnTalent(1,3)');self.runtime.save_state()
        expected=copy.deepcopy(self.runtime._progression)
        self.action('ConfirmTalentWipe()')
        self.assertEqual(self.runtime._progression['talent_points'],expected['talent_points']+sum(expected['talents'].values()))
        self.assertTrue(all(v==0 for v in self.runtime._progression['talents'].values()))
        self.assertEqual(self.ui.evaluate('return table.getn(talentErrors)'),[0])
        self.runtime._progression['talents']['skybound']=0;self.runtime.load_state();self.publish()
        self.assertEqual(self.runtime._progression,expected)

if __name__=='__main__':unittest.main()
