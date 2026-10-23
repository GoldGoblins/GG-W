"""Original Lua gossip/quest bindings through the actual guarded GG simulation."""
import copy,json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
PROJECT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(PROJECT))
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import QObject,Signal
from PySide6.QtGui import QGuiApplication
from backend import game_engine_mmo as mmo,game_engine_character_creation as appearance
from backend.game_engine_presentation import Presentation
APP=QGuiApplication.instance() or QGuiApplication([])

class Bridge(QObject):
    snapshotPublished=Signal(object)
    def __init__(self,runtime):super().__init__();self.runtime=runtime
    def gameEngineNpcTalk(self,npc,choice):return json.dumps(self.runtime.talk_npc(npc,choice))
    def gameEngineGossipClose(self):return json.dumps(self.runtime.gossip_close())
    def gameEngineQuestDialogSelect(self,npc,quest):return json.dumps(self.runtime.quest_dialog_select(npc,quest))
    def gameEngineQuestDialogAction(self,npc,quest,panel,action,choice):return json.dumps(self.runtime.quest_dialog_action(npc,quest,panel,action,choice))
    def gameEngineQuestAbandon(self,quest):return json.dumps(self.runtime.abandon_quest(quest))

class LocalQuests(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        for context in [patch.dict(os.environ,{'XDG_STATE_HOME':directory.name}),
                        patch.object(mmo,'DEFAULT_STASH_PATH',Path(directory.name)/'stash.json'),
                        patch.object(appearance,'STATE_PATH',Path(directory.name)/'appearance.json')]:
            context.start();self.addCleanup(context.stop)
        from backend.game_engine_host import GameEngineRuntime
        self.runtime=GameEngineRuntime();self.addCleanup(self.runtime.shutdown)
        self.bridge=Bridge(self.runtime);self.presentation=Presentation(self.bridge,device=False);self.addCleanup(self.presentation.close)
        self.assertTrue(self.presentation.full_ui)
        self.ui=self.presentation.lua
        self.ui.execute("""questEvents={};errors={};qe=CreateFrame('Frame')
          for _,e in ipairs({'GOSSIP_SHOW','GOSSIP_CLOSED','QUEST_DETAIL','QUEST_PROGRESS','QUEST_COMPLETE','QUEST_FINISHED','QUEST_LOG_UPDATE','UI_ERROR_MESSAGE'}) do qe:RegisterEvent(e) end
          qe:SetScript('OnEvent',function() table.insert(questEvents,event);if event=='UI_ERROR_MESSAGE' then table.insert(errors,arg1) end end)
        """)
        self.near('npc-guardian-01');self.runtime.talk_npc('npc-guardian-01','');self.publish()
    def near(self,npc):
        index=self.runtime._npc_index_for_id_locked(npc);self.assertIsNotNone(index)
        self.runtime._x[0]=self.runtime._x[index]+1;self.runtime._z[0]=self.runtime._z[index]
        self.runtime._y[0]=self.runtime._terrain_height_locked(self.runtime._x[0],self.runtime._z[0])+.65
    def publish(self):
        self.presentation.last_update=0;self.presentation.update(self.runtime.ui_snapshot())
        self.assertFalse(self.presentation.errors,self.presentation.errors)
    def value(self,script):return self.ui.evaluate(script)[0]
    def run_lua(self,script):
        self.ui.execute(script);self.presentation._game_requests(self.ui.request('requests'));self.publish()
    def select(self,key,active=False):
        rows=self.presentation.gameplay_views.quest.active if active else self.presentation.gameplay_views.quest.available
        index=rows.index(key)+1
        self.run_lua(('SelectGossipActiveQuest' if active else 'SelectGossipAvailableQuest')+'('+str(index)+')')
    def ready(self,key):
        self.runtime._record_quest_event_locked({'kind':'DEFEAT','target_id':'npc-critter-01'});self.publish()
        self.assertEqual(self.runtime._quest_state['active'][key]['status'],'READY')

    def test_real_accept_progress_reward_and_repeat_cannot_duplicate_payment(self):
        self.assertTrue(self.value('return string.len(GetGossipText())>0'))
        self.select('quest.shoreline-first');self.assertEqual(self.value('return GetTitleText()'),'The First Ripple')
        self.run_lua('AcceptQuest()');self.assertIn('quest.shoreline-first',self.runtime._quest_state['active'])
        self.select('quest.shoreline-first',True)
        self.run_lua('CompleteQuest()');self.assertTrue(self.value('return table.getn(errors)>0'))
        self.assertEqual(self.runtime._engine_quest_panel['panel'],'PROGRESS')
        self.ready('quest.shoreline-first');self.run_lua('CompleteQuest()')
        self.assertEqual(self.runtime._engine_quest_panel['panel'],'REWARD')
        self.assertEqual(self.value('return GetRewardMoney()'),250000)
        self.assertEqual(self.value('return GetNumQuestRewards()'),1)
        gold=self.runtime._economy_state['wallet']['gold'];xp=self.runtime._progression['xp']
        self.run_lua('GetQuestReward()')
        self.assertEqual(self.runtime._economy_state['wallet']['gold'],gold+25)
        self.assertEqual(self.runtime._progression['xp'],xp+90)
        self.assertIn('quest.shoreline-first',self.runtime._quest_state['completed'])
        self.assertIn('quest.shoreline-report',self.presentation.gameplay_views.quest.available)
        self.run_lua('GetQuestReward()');self.assertEqual(self.runtime._economy_state['wallet']['gold'],gold+25)
        events=self.value('return table.concat(questEvents,",")').split(',')
        for expected in ('QUEST_DETAIL','QUEST_PROGRESS','QUEST_COMPLETE','QUEST_FINISHED'):self.assertIn(expected,events)

    def test_queued_reward_checks_real_giver_distance_and_same_session(self):
        self.select('quest.shoreline-first');self.run_lua('AcceptQuest()');self.ready('quest.shoreline-first')
        self.select('quest.shoreline-first',True);self.run_lua('CompleteQuest()')
        self.ui.execute('GetQuestReward()');requests=self.ui.request('requests')
        before=copy.deepcopy((self.runtime._economy_state,self.runtime._quest_state,self.runtime._progression))
        self.runtime._x[0]+=100
        self.presentation._game_requests(requests)
        self.assertEqual(before,(self.runtime._economy_state,self.runtime._quest_state,self.runtime._progression))
        self.assertIn('QUEST_PANEL_CHANGED_OR_CLOSED',self.value('return table.concat(errors,",")'))
        self.near('npc-guardian-01');self.publish();self.ui.execute('GetQuestReward()');requests=self.ui.request('requests')
        self.runtime.close_dialogue();self.presentation._game_requests(requests)
        self.assertEqual(before,(self.runtime._economy_state,self.runtime._quest_state,self.runtime._progression))
        self.publish();self.assertEqual(self.value('return GetTitleText()'),'')

    def test_decline_reopens_gossip_close_clears_session_and_option_uses_authored_effect(self):
        self.select('quest.shoreline-first');self.run_lua('DeclineQuest()')
        self.assertFalse(self.runtime._engine_quest_panel);self.assertTrue(self.presentation.gameplay_views.quest.options)
        self.assertNotIn('quest.shoreline-first',self.runtime._quest_state['active'])
        option=next(index for index,ref in self.presentation.gameplay_views.quest.options.items() if ref=='shoreline-duty')
        self.run_lua('SelectGossipOption('+str(option)+')')
        self.assertIn('quest.shoreline-first',self.runtime._quest_state['active'])
        self.run_lua('CloseGossip()');self.assertIsNone(self.value('return GetGossipText()'))
        self.assertFalse(self.runtime._dialogue_state['active']['npc_id'])

    def test_log_abandon_exact_id_and_selection_follows_original_quest_after_reorder(self):
        self.runtime.accept_quest('quest.shoreline-first');self.publish()
        self.ui.execute('SelectQuestLogEntry(1);AddQuestWatch(1)')
        self.runtime.accept_quest('quest.windmill-watch');self.publish()
        old=self.value('return GetQuestLogTitle(GetQuestLogSelection())')
        self.run_lua('SelectQuestLogEntry(2);SetAbandonQuest();AbandonQuest()')
        self.assertIn('quest.shoreline-first',self.runtime._quest_state['active'])
        self.assertNotIn('quest.windmill-watch',self.runtime._quest_state['active'])
        self.assertEqual(self.value('return GetQuestLogSelection()'),0)
        self.assertEqual(self.value('return GetNumQuestWatches()'),1)
        self.ui.execute('SelectQuestLogEntry(1)');self.runtime.accept_quest('quest.windmill-watch');self.publish()
        self.assertEqual(self.value('return GetQuestLogTitle(GetQuestLogSelection())'),old)
        count=self.value('return table.getn(questEvents)');self.publish();self.assertEqual(self.value('return table.getn(questEvents)'),count)

    def test_invented_giver_wrong_phase_and_choice_cannot_mutate_quest_state(self):
        before=copy.deepcopy(self.runtime._quest_state)
        self.assertTrue(self.runtime.quest_dialog_select('npc-wanderer-01','quest.shoreline-first').get('error'))
        self.select('quest.shoreline-first')
        self.assertTrue(self.runtime.quest_dialog_action('npc-guardian-01','quest.shoreline-first','REWARD','REWARD',0).get('error'))
        self.assertEqual(self.runtime._quest_state,before)
        self.run_lua('AcceptQuest()');self.ready('quest.shoreline-first');self.select('quest.shoreline-first',True);self.run_lua('CompleteQuest()')
        gold=self.runtime._economy_state['wallet']['gold'];self.run_lua('GetQuestReward(2)')
        self.assertEqual(self.runtime._economy_state['wallet']['gold'],gold)
        self.assertIn('quest.shoreline-first',self.runtime._quest_state['active'])

if __name__=='__main__':unittest.main()
