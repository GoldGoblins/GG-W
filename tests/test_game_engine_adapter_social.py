"""Original Lua guild/roll/trainer calls, shared custody and durable saves."""
import copy
import unittest
from unittest.mock import patch
import test_game_engine_adapter_services as service_tests
from backend import game_engine_items as items
from backend.game_engine_adapter_pet_training import BITE

class Social(unittest.TestCase):
    setUp=service_tests.Services.setUp
    publish=service_tests.Services.publish
    call=service_tests.Services.call
    control=service_tests.Services.control
    view=service_tests.Services.view
    service=service_tests.Services.service
    move_near_npc=service_tests.Services.move_near_npc
    tame=service_tests.Services.tame

    def test_original_drop_food_feeds_once_and_failed_commit_keeps_cursor(self):
        self.tame()
        with self.runtime._lock:
            food=items.make_instance(self.runtime._item_catalog,'drop-feed-fixture','item.field_ration',quantity=3,location='GROUND')
            self.runtime._item_instances[food['instance_id']]=food
            ok,result=self.runtime._move_item_locked(food,'INVENTORY',owner_id='player');self.assertTrue(ok,result)
        self.publish();slot=food['slot_index']+1
        self.call(f'PickupContainerItem(0,{slot}) DropItemOnUnit("pet") DropItemOnUnit("pet")')
        self.assertEqual(food['quantity'],2);self.assertFalse(self.ui.evaluate('return CursorHasItem()')[0])
        self.call(f'PickupContainerItem(0,{slot})')
        before=copy.deepcopy((self.runtime._item_instances,self.runtime._services['pets']))
        with patch.object(self.runtime._state_store,'save',side_effect=OSError('disk full')):
            self.ui.execute('DropItemOnUnit("pet")');self.presentation._ui_requests(self.ui.request('requests'))
        self.assertEqual(before,(self.runtime._item_instances,self.runtime._services['pets']));self.assertEqual(self.ui.evaluate('return CursorHasItem()'),[1])

    def test_original_drop_on_party_member_opens_trade_without_transferring_item(self):
        person=self.move_near_npc();self.service('GroupInvite',target=person);self.publish()
        with self.runtime._lock:
            item=items.make_instance(self.runtime._item_catalog,'drop-trade-fixture','item.weapon_sword',location='GROUND')
            self.runtime._item_instances[item['instance_id']]=item
            ok,result=self.runtime._move_item_locked(item,'INVENTORY',owner_id='player');self.assertTrue(ok,result)
        self.publish()
        self.call(f'PickupContainerItem(0,{item["slot_index"]+1}) DropItemOnUnit("party1")')
        self.assertTrue(self.view()['trade']['open']);self.assertEqual(self.runtime._service_trade['target'],person)
        self.assertEqual(self.runtime._service_trade['slots']['1'],item['instance_id']);self.assertEqual(item['location'],'INVENTORY')
        self.assertFalse(self.ui.evaluate('return CursorHasItem()')[0])

    def test_original_guild_membership_roster_notes_rank_and_chat_roundtrip(self):
        identity=self.move_near_npc();money=self.view()['money']
        self.assertNotIn('error',self.service('GuildCreate',name='Gold Crew'));self.publish()
        self.assertEqual(self.view()['money'],money-10000)
        self.assertEqual(self.ui.evaluate('return IsInGuild(),IsGuildLeader(),GuildControlGetNumRanks()'),[1,1,5])
        self.assertEqual(self.ui.evaluate('return (GetGuildInfo("player"))'),['Gold Crew'])
        name=self.runtime._service_unit_locked(identity)['name']
        self.call('GuildInviteByName("'+name+'") GuildSetMOTD("Gather at the dock")')
        self.assertEqual(len(self.view()['guild']['roster']),2)
        self.assertEqual(self.ui.evaluate('return GetGuildRosterMOTD()'),['Gather at the dock'])
        self.call('GuildPromoteByName("'+name+'")')
        self.assertEqual(self.runtime._services['guild']['members'][identity]['rank'],3)
        index=next(i for i,r in enumerate(self.view()['guild']['roster'],1) if r['id']==identity)
        self.call(f'GuildRosterSetPublicNote({index},"Scout") SendChatMessage("Hello crew","GUILD")')
        self.assertEqual(self.runtime._services['guild']['members'][identity]['note'],'Scout')
        self.assertTrue(any('Hello crew' in e['text'] for e in self.runtime.snapshot()['event_journal']['events']))
        self.runtime.load_state();self.publish()
        self.assertEqual(self.ui.evaluate('return GetNumGuildMembers()'),[2])

    def test_guild_rights_and_failed_save_restore_membership_and_money(self):
        before=copy.deepcopy(self.runtime._economy_state)
        with patch.object(self.runtime._state_store,'save',side_effect=OSError('disk full')):
            result=self.service('GuildCreate',name='Rollback')
        self.assertEqual(result['error'],'SERVICE_SAVE_FAILED')
        self.assertEqual(before,self.runtime._economy_state);self.assertFalse(self.runtime._services['guild'])
        self.service('GuildCreate',name='Bounded');identity=self.move_near_npc()
        self.service('GuildInvite',target=identity);self.service('GuildLeader',target=identity)
        result=self.service('GuildDisband');self.assertEqual(result['error'],'GUILD_MASTER_REQUIRED')
        self.assertEqual(self.runtime._services['guild']['members'][identity]['rank'],0)

    def open_rare_loot(self,method):
        self.service('GroupInvite',target=self.move_near_npc())
        self.service('GroupLoot',method=method,master='player',threshold=2)
        with self.runtime._lock:
            source=next(r for r in self.runtime._item_instances.values() if r.get('kind')=='CONTAINER'
                and r.get('location')=='GROUND' and any(c.get('container_id')==r['instance_id'] and c.get('location')=='CONTAINER'
                    for c in self.runtime._item_instances.values()))
            p=source['position'];self.runtime._x[0]=p['x'];self.runtime._z[0]=p['z'];self.runtime._y[0]=p['y']+.65
            original=next(r for r in self.runtime._item_instances.values() if r.get('container_id')==source['instance_id'] and r.get('location')=='CONTAINER')
            items.definition(self.runtime._item_catalog,original['definition_id'])['rarity']='RARE'
            original['rarity']='RARE'
        self.assertNotIn('error',self.runtime.open_container(source['instance_id']));self.publish()
        return source,original,self.runtime._engine_loot['session']

    def test_original_need_vote_awards_exact_instance_once_and_survives_reload(self):
        source,item,session=self.open_rare_loot('group')
        result=self.runtime.loot_slot(session,source['instance_id'],item['instance_id']);self.assertNotIn('error',result);self.publish()
        roll=self.view()['loot_rolls'][0]
        self.assertGreater(self.ui.evaluate('return GetLootRollTimeLeft('+str(roll['id'])+')')[0],0)
        self.call('RollOnLoot('+str(roll['id'])+',1)')
        self.assertEqual(self.runtime._item_instance_locked(item['instance_id'])['location'],'INVENTORY')
        before=copy.deepcopy(self.runtime._item_instances);self.call('RollOnLoot('+str(roll['id'])+',1)')
        self.assertEqual(before,self.runtime._item_instances)
        self.runtime.load_state();self.assertEqual(self.runtime._item_instance_locked(item['instance_id'])['owner_id'],'player')

    def test_master_distribution_and_failed_save_do_not_consume_pending_loot(self):
        source,item,session=self.open_rare_loot('master')
        self.runtime.loot_slot(session,source['instance_id'],item['instance_id']);self.publish()
        roll=self.view()['loot_rolls'][0]
        with patch.object(self.runtime._state_store,'save',side_effect=OSError('disk full')):
            result=self.service('LootMasterGive',id=roll['id'],target='player')
        self.assertEqual(result['error'],'SERVICE_SAVE_FAILED')
        self.assertEqual(self.runtime._item_instance_locked(item['instance_id'])['location'],'CONTAINER')
        self.assertEqual(len(self.view()['loot_rolls']),1)
        self.assertNotIn('error',self.service('LootMasterGive',id=roll['id'],target='player'))
        self.assertEqual(self.runtime._item_instance_locked(item['instance_id'])['location'],'INVENTORY')

    def test_pet_feed_real_food_training_original_book_and_reload(self):
        pet=self.tame();identity=self.move_near_npc()
        with self.runtime._lock:
            self.runtime._progression['level']=3;pet['level']=3;pet['loyalty']=2;pet['happiness']=100000
            food=items.make_instance(self.runtime._item_catalog,'pet-feed-fixture','item.field_ration',quantity=2,location='GROUND')
            self.runtime._item_instances[food['instance_id']]=food
            ok,result=self.runtime._move_item_locked(food,'INVENTORY',owner_id='player');self.assertTrue(ok,result)
            before=self.runtime._inventory['item.field_ration']
        self.assertNotIn('error',self.service('PetFeed',item=food['instance_id']))
        self.assertEqual(self.runtime._inventory.get('item.field_ration',0),before-1)
        self.assertEqual(pet['happiness'],450000)
        self.assertNotIn('error',self.service('TrainerOpen',target=identity));self.publish()
        money=self.view()['money']
        self.call('for i=1,GetNumTrainerServices() do if GetTrainerServiceInfo(i)=="Bite" then BuyTrainerService(i) end end')
        self.assertIn(str(BITE),self.runtime._active_pet_locked()['learned'])
        self.assertEqual(self.view()['money'],money-1000)
        self.assertEqual(self.ui.evaluate('return GetPetTrainingPoints()'),[3,1])
        self.runtime.load_state();self.publish()
        self.assertIn(str(BITE),self.runtime._active_pet_locked()['learned'])

    def test_passive_pet_training_and_negative_loyalty_survive_save_load(self):
        from backend.game_engine_adapter_pet_training import GUARD
        pet=self.tame();identity=self.move_near_npc()
        pet.update(level=3,loyalty=2,happiness=100000);self.runtime._progression['level']=3
        before=self.runtime._pet_profile_locked(pet)['armor']
        self.service('TrainerOpen',target=identity);self.service('TrainerBuy',spell_id=GUARD);self.publish()
        self.assertEqual(self.runtime._pet_profile_locked(pet)['armor'],before+3)
        self.assertEqual(self.ui.evaluate('return IsSpellPassive(2,"pet"),GetSpellAutocast(2,"pet")'),[1,None,None])
        self.call('CastSpell(2,"pet")');self.assertFalse(self.runtime._active_pet_locked()['target'])
        self.assertEqual(self.service('PetAutocast',spell_id=GUARD)['error'],'PET_SPELL_PASSIVE')
        self.assertEqual(self.service('PetSpell',spell_id=GUARD)['error'],'PET_SPELL_PASSIVE')
        with self.runtime._lock:
            pet=self.runtime._active_pet_locked();self.runtime._tick_pet_training_locked(pet,.5)
        self.assertLess(pet['loyalty_progress'],0)
        self.runtime.save_state();self.runtime.load_state();pet=self.runtime._active_pet_locked()
        self.assertIn(str(GUARD),pet['learned']);self.assertLess(pet['loyalty_progress'],0)

    def test_corrupt_new_guild_record_does_not_discard_existing_mail(self):
        self.service('MailOpen');self.service('MailSend',target='player',subject='Keep')
        raw=copy.deepcopy(self.runtime._services);raw['guild']={'name':'broken'}
        with self.runtime._lock:self.runtime._restore_services_locked(raw)
        self.assertFalse(self.runtime._services['guild']);self.assertEqual(len(self.runtime._services['mail']),1)

    def test_original_invitation_accept_decline_and_rank_permissions(self):
        identity=self.move_near_npc()
        self.service('GroupRequestInvite',target=identity);self.call('DeclineGroup()')
        self.assertFalse(self.view()['group']['members']);self.assertIsNone(self.runtime._services['group_invite'])
        self.service('GroupRequestInvite',target=identity);self.call('AcceptGroup()')
        self.assertEqual(self.view()['group']['leader'],identity)
        self.assertEqual(self.view()['group']['members'],[identity])
        self.service('GuildRequestInvite',target=identity,name='Mira Crew');self.call('DeclineGuild()')
        self.assertFalse(self.runtime._services['guild'])
        self.service('GuildRequestInvite',target=identity,name='Mira Crew');self.call('AcceptGuild()')
        self.assertEqual(self.ui.evaluate('return IsInGuild(),IsGuildLeader()'),[1,None])
        self.assertEqual(self.service('GuildInvite',target=identity)['error'],'GUILD_PERMISSION_DENIED')

    def test_original_master_loot_uses_frozen_candidate_and_no_transfer_repeats(self):
        source,item,session=self.open_rare_loot('master')
        slot=list(self.runtime._engine_loot['ids']).index(item['instance_id'])+1
        self.call(f'GiveMasterLoot({slot},1)')
        self.assertEqual(self.runtime._item_instance_locked(item['instance_id'])['owner_id'],'player')
        self.assertEqual(self.runtime._item_instance_locked(item['instance_id'])['location'],'INVENTORY')
        before=copy.deepcopy(self.runtime._item_instances);self.call(f'GiveMasterLoot({slot},1)')
        self.assertEqual(before,self.runtime._item_instances)

    def test_trade_enchant_slot_retains_ownership_and_consumes_one_actual_scroll(self):
        identity=self.move_near_npc()
        with self.runtime._lock:
            target=next(i for i in self.runtime._item_instances.values() if i.get('owner_id')=='player'
                and i.get('location') in ('INVENTORY','EQUIPPED') and isinstance(i.get('gear'),dict) and i['gear'].get('base_type')=='SWORD')
            scroll=items.make_instance(self.runtime._item_catalog,'enchant-trade-probe','item.enchant_scroll',location='GROUND')
            scroll['scroll_enchant_id']='enchant.chromatic.red';self.runtime._item_instances[scroll['instance_id']]=scroll
            ok,result=self.runtime._move_item_locked(scroll,'INVENTORY',owner_id='player');self.assertTrue(ok,result)
            owner=target['owner_id'];location=target['location']
        self.service('TradeOpen',target=identity)
        self.assertNotIn('error',self.service('TradeSet',slot=7,item=target['instance_id']))
        self.assertNotIn('error',self.service('TradeEnchant',enchant_id='enchant.chromatic.red'));self.publish()
        self.assertEqual(self.ui.evaluate('return (GetTradePlayerItemInfo(7))'),[target['name']])
        self.call('AcceptTrade()')
        saved=self.runtime._item_instance_locked(target['instance_id'])
        self.assertEqual((saved['owner_id'],saved['location']),(owner,location))
        self.assertIn('enchant.chromatic.red',[e['id'] for e in saved['gear']['enchantments']])
        self.assertNotIn(scroll['instance_id'],self.runtime._item_instances)
        self.runtime.load_state();self.assertIn('enchant.chromatic.red',[e['id'] for e in self.runtime._item_instance_locked(target['instance_id'])['gear']['enchantments']])

    def test_barter_has_one_durable_commit_and_failed_save_restores_npc_counters(self):
        identity=self.move_near_npc();item=service_tests.Services.inventory(self)[0]
        self.service('TradeOpen',target=identity);self.service('TradeSet',slot=1,item=item['instance_id'])
        revision=self.view()['trade']['offer_revision'];counts=copy.deepcopy(self.runtime._npc_interaction_count)
        before=copy.deepcopy((self.runtime._services,self.runtime._item_instances,self.runtime._individual_state))
        with patch.object(self.runtime._state_store,'save',side_effect=OSError('disk full')) as save:
            result=self.service('TradeAccept',offer_revision=revision)
        self.assertEqual(result['error'],'SERVICE_SAVE_FAILED');self.assertEqual(save.call_count,1)
        current=copy.deepcopy(self.runtime._services);current['clock']=before[0]['clock']
        self.assertEqual(before,(current,self.runtime._item_instances,self.runtime._individual_state));self.assertEqual(counts,self.runtime._npc_interaction_count)
        with patch.object(self.runtime._state_store,'save',wraps=self.runtime._state_store.save) as save:
            self.assertNotIn('error',self.service('TradeAccept',offer_revision=revision))
        self.assertEqual(save.call_count,1);self.runtime.load_state()
        self.assertEqual(self.runtime._item_instance_locked(item['instance_id'])['owner_id'],identity)

    def test_invalid_new_pet_training_record_preserves_existing_mail_and_companion(self):
        pet=self.tame();self.service('MailOpen');self.service('MailSend',target='player',subject='Keep with pet')
        raw=copy.deepcopy(self.runtime._services);raw['pets'][0]['learned']={'invalid':True}
        with self.runtime._lock:self.runtime._restore_services_locked(raw)
        self.assertEqual(len(self.runtime._services['mail']),1);self.assertEqual(self.runtime._active_pet_locked()['id'],pet['id'])

if __name__=='__main__':unittest.main()
