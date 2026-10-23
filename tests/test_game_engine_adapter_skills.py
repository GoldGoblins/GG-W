"""Skill removal really gates crafting; local training transfers existing money."""
import copy
import unittest
from unittest.mock import patch
import test_game_engine_adapter_services as services
from backend.game_engine_adapter_gameplay import identity
from backend.game_engine_adapter_skills import TRAINING_COST
from backend import game_engine_enchants as enchants


class Skills(unittest.TestCase):
    setUp=services.Services.setUp
    publish=services.Services.publish
    call=services.Services.call
    control=services.Services.control
    service=services.Services.service
    view=services.Services.view
    move_near_npc=services.Services.move_near_npc

    def abandon(self,key):
        return self.service('SkillAbandon',skill_id=identity('profession.'+key))

    def test_original_skill_rows_removal_and_paid_trainer_relearn_same_profession(self):
        self.assertEqual(self.ui.evaluate('return GetNumSkillLines()'),[6])
        self.call('CollapseSkillHeader(1)');self.assertEqual(self.ui.evaluate('return GetNumSkillLines()'),[1])
        self.call('ExpandSkillHeader(1)')
        self.call('for i=1,GetNumSkillLines() do if GetSkillLineInfo(i)=="Blacksmithing" then AbandonSkill(i) end end')
        self.assertFalse(self.runtime._profession_known_locked('BLACKSMITHING'))
        self.assertEqual(self.ui.evaluate('return GetNumSkillLines()'),[5])
        target=self.move_near_npc();self.service('TrainerOpen',mode='PROFESSION',target=target);self.publish()
        before=self.view()['money'];vendor=self.runtime._service_money_locked(owner=target)
        self.call('for i=1,GetNumTrainerServices() do if GetTrainerServiceInfo(i)=="Blacksmithing" then BuyTrainerService(i) end end')
        self.assertTrue(self.runtime._profession_known_locked('BLACKSMITHING'))
        self.assertEqual(self.view()['money'],before-TRAINING_COST)
        self.assertEqual(self.runtime._service_money_locked(owner=target),vendor+TRAINING_COST)
        self.assertEqual(self.ui.evaluate('return GetNumSkillLines()'),[6])
        self.call('for i=1,GetNumTrainerServices() do if GetTrainerServiceInfo(i)=="Blacksmithing" then BuyTrainerService(i) end end')
        self.assertEqual(self.view()['money'],before-TRAINING_COST)

    def test_abandoned_profession_blocks_direct_craft_recipe_book_and_survives_save(self):
        self.runtime._profession_state['BLACKSMITHING'].update(level=17,xp=43)
        self.assertNotIn('error',self.abandon('BLACKSMITHING'))
        before=copy.deepcopy((self.runtime._item_instances,self.runtime._inventory))
        recipe=next((k for k,r in self.runtime._gear_tables['recipes'].items() if r.get('profession')=='BLACKSMITHING'))
        station=self.runtime._gear_tables['recipes'][recipe]['station_id']
        self.assertEqual(self.runtime.craft_gear(recipe,station)['error'],'PROFESSION_NOT_KNOWN')
        self.assertEqual(before,(self.runtime._item_instances,self.runtime._inventory))
        self.runtime.save_state();self.runtime.load_state();self.publish()
        self.assertFalse(self.runtime._profession_known_locked('BLACKSMITHING'))
        self.assertEqual(self.runtime._profession_state['BLACKSMITHING']['level'],0)
        with self.runtime._lock:self.runtime._rebuild_content_runtime_locked()
        self.assertFalse(self.runtime._profession_known_locked('BLACKSMITHING'))
        self.assertNotIn(recipe,self.runtime.snapshot()['crafting']['gear_recipes'])
        with self.runtime._lock:
            self.runtime._engine_craft_book={'book':'TRADE_SKILL','station_id':station,'session':1}
            with patch.object(self.runtime,'_station_reachable_locked',return_value=True):
                self.assertNotIn(recipe,[r['ref'] for r in self.runtime._craft_book_view_locked()['rows']])
        self.assertNotIn('error',self.abandon('SURVIVAL'))
        self.assertFalse(self.runtime.snapshot()['crafting']['recipes'])
        self.assertEqual(self.runtime.craft_recipe('recipe.field_ration')['error'],'PROFESSION_NOT_KNOWN')
        self.assertNotIn('error',self.abandon('ENCHANTING'))
        enchant=next(iter(enchants.CATALOG))
        self.assertEqual(self.runtime.craft_gear('recipe.enchant_scroll.'+enchant,'station.enchanting_altar')['error'],'PROFESSION_NOT_KNOWN')

    def test_failed_skill_save_restores_profession_and_pending_crafting(self):
        self.runtime._engine_craft_repeat={'ref':'recipe.field_ration','remaining':2,'wait_s':.1,'session':1}
        before=copy.deepcopy((self.runtime._profession_state,self.runtime._engine_craft_repeat,self.runtime._economy_state))
        with patch.object(self.runtime,'save_state',side_effect=OSError('fixture unavailable')):
            self.assertEqual(self.abandon('SURVIVAL')['error'],'SERVICE_SAVE_FAILED')
        self.assertEqual(before,(self.runtime._profession_state,self.runtime._engine_craft_repeat,self.runtime._economy_state))
        self.assertNotIn('error',self.abandon('SURVIVAL'));self.assertFalse(self.runtime._engine_craft_repeat)

    def test_trainer_identity_range_frozen_session_and_failed_payment_are_atomic(self):
        self.abandon('LEATHERWORKING');target=self.move_near_npc()
        self.assertNotIn('error',self.service('TrainerOpen',mode='PROFESSION',target=target));session=self.view()['session']
        before=copy.deepcopy((self.runtime._profession_state,self.runtime._economy_state))
        skill=identity('profession.LEATHERWORKING')
        with patch.object(self.runtime,'save_state',side_effect=OSError('fixture unavailable')):
            self.assertEqual(self.service('TrainerBuy',spell_id=skill)['error'],'SERVICE_SAVE_FAILED')
        self.assertEqual(before,(self.runtime._profession_state,self.runtime._economy_state))
        self.runtime._x[0]+=100
        self.assertEqual(self.service('TrainerBuy',spell_id=skill)['error'],'SERVICE_PERSON_OUT_OF_REACH')
        self.assertEqual(before,(self.runtime._profession_state,self.runtime._economy_state))
        self.move_near_npc();self.service('TrainerClose');self.service('TrainerOpen',mode='PROFESSION',target=target)
        self.assertEqual(self.control('service','TrainerBuy',session=session,spell_id=skill)['error'],'SERVICE_WINDOW_CHANGED_OR_CLOSED')
        self.assertEqual(self.service('TrainerOpen',mode='PROFESSION',target='player')['error'],'PROFESSION_TRAINER_REQUIRED')

if __name__=='__main__':unittest.main()
