"""Original shared quests use separate companion progress, never rewards."""
import copy
import unittest
from unittest.mock import patch
import test_game_engine_adapter_services as services


class PartyQuests(unittest.TestCase):
    setUp=services.Services.setUp
    call=services.Services.call
    control=services.Services.control
    publish=services.Services.publish
    service=services.Services.service
    view=services.Services.view
    move_near_npc=services.Services.move_near_npc

    def quest(self):
        key='quest.shoreline-first';person=self.move_near_npc()
        self.assertIsNone(self.service('GroupInvite',target=person).get('error'))
        from backend import game_engine_quests as quests
        quests.accept(self.runtime._quest_state,self.runtime._quest_catalog,key,self.runtime._sim_time)
        self.publish();self.call('SelectQuestLogEntry(1)');return key,person

    def test_original_share_separate_progress_save_restore_and_no_copied_rewards(self):
        key,person=self.quest();wallet=copy.deepcopy(self.runtime._economy_state);items=copy.deepcopy(self.runtime._item_instances)
        self.call('SelectQuestLogEntry(1)');self.assertEqual(self.ui.evaluate('return GetQuestLogPushable()'),[1])
        self.call('QuestLogPushQuest()')
        state=self.runtime._services['party_quests'][person]
        self.assertEqual(state['active'][key]['status'],'ACTIVE')
        self.assertIsNot(state['active'][key],self.runtime._quest_state['active'][key])
        with self.runtime._lock:self.runtime._record_quest_event_locked(dict(kind='DEFEAT',target_id='npc-critter-01'))
        self.assertEqual(state['active'][key]['status'],'READY');self.assertEqual(wallet,self.runtime._economy_state);self.assertEqual(items,self.runtime._item_instances)
        saved=copy.deepcopy(state);self.runtime.save_state();self.runtime.load_state()
        self.assertEqual(saved,self.runtime._services['party_quests'][person]);self.assertNotIn('quest_invite',self.runtime._service_windows)

    def test_real_companion_offer_original_confirm_expiry_and_replay(self):
        key,person=self.quest();self.call('QuestLogPushQuest()');self.runtime._quest_state['active'].pop(key)
        self.assertIsNone(self.service('QuestShareOffer',quest=key,target=person).get('error'))
        self.call('ConfirmAcceptQuest()');self.assertIn(key,self.runtime._quest_state['active'])
        self.assertEqual(self.service('QuestShareConfirm')['error'],'QUEST_INVITATION_EXPIRED')
        self.runtime._quest_state['active'].pop(key);self.service('QuestShareOffer',quest=key,target=person)
        self.runtime._service_windows['quest_invite']['expires']=0.
        self.assertEqual(self.service('QuestShareConfirm')['error'],'QUEST_INVITATION_EXPIRED');self.assertNotIn(key,self.runtime._quest_state['active'])

    def test_range_eligibility_dead_state_and_save_failure_restore_both_ledgers(self):
        key,person=self.quest();before=copy.deepcopy((self.runtime._services,self.runtime._quest_state))
        with patch.object(self.runtime._state_store,'save',side_effect=OSError('disk full')):
            self.assertEqual(self.service('QuestShare',quest=key)['error'],'SERVICE_SAVE_FAILED')
        current=copy.deepcopy(self.runtime._services);current['clock']=before[0]['clock']
        self.assertEqual(before,(current,self.runtime._quest_state))
        self.runtime._x[0]+=100;self.service('QuestShare',quest=key)
        self.assertFalse(self.runtime._services['party_quests'])
        self.move_near_npc();self.runtime._quest_catalog[key]['shareable']=False
        self.assertEqual(self.service('QuestShare',quest=key)['error'],'QUEST_NOT_SHAREABLE')
        self.runtime._combat_state['actors']['player']['alive']=False
        self.assertEqual(self.service('QuestShare',quest=key)['error'],'PLAYER_DEFEATED')

if __name__=='__main__':unittest.main()
