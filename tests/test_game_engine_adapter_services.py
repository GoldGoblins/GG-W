"""Original Lua services against canonical local custody and durable saves."""
import copy
import json
import math
import unittest
from unittest.mock import patch
import test_game_engine_adapter_controls as control_tests
from backend import game_engine_items as items
from backend.game_engine_adapter_services import MAX_MAIL


class Services(unittest.TestCase):
    setUp = control_tests.Controls.setUp
    publish = control_tests.Controls.publish
    call = control_tests.Controls.call
    control = control_tests.Controls.control

    def view(self):
        return self.runtime.snapshot()['player']['client_controls']['services']

    def service(self, op, **fields):
        value = dict(session=self.view()['session'], **fields)
        return self.control('service', op, **value)

    def inventory(self):
        from backend.game_engine_trade import tradeable_definition
        self.runtime.snapshot()
        return [r for r in self.runtime._item_instances.values() if r.get('owner_id') == 'player'
                and r.get('location') == 'INVENTORY'
                and tradeable_definition(items.definition(self.runtime._item_catalog, r['definition_id']))[0]]

    def move_near_npc(self):
        with self.runtime._lock:
            index = self.runtime._npc_index_for_id_locked('npc-wanderer-01')
            self.runtime._x[0] = self.runtime._x[index] + 1
            self.runtime._z[0] = self.runtime._z[index]
            self.runtime._y[0] = self.runtime._y[index]
        return 'npc-wanderer-01'

    def test_mail_money_attachment_exact_once_and_original_views(self):
        self.service('MailOpen');item = self.inventory()[0]
        before = self.view()['money']
        sent = self.service('MailSend', target='player', subject='Parcel', body='A real letter', item=item['instance_id'], money=12345)
        self.assertNotIn('error', sent)
        self.assertEqual(item['location'], 'MAIL')
        self.assertEqual(self.view()['money'], before - 12345 - 30)
        self.publish()
        self.assertEqual(self.ui.evaluate('return GetInboxNumItems()'), [1])
        header = self.ui.evaluate('return GetInboxHeaderInfo(1)')
        self.assertIn('Parcel', header)
        self.call('TakeInboxMoney(1) TakeInboxItem(1)')
        self.assertEqual(self.runtime._item_instance_locked(item['instance_id'])['location'], 'INVENTORY')
        self.assertEqual(self.view()['money'], before - 30)
        after = copy.deepcopy((self.runtime._item_instances, self.runtime._economy_state))
        self.call('TakeInboxMoney(1) TakeInboxItem(1)')
        self.assertEqual(after, (self.runtime._item_instances, self.runtime._economy_state))
        self.call('DeleteInboxItem(1)')
        self.assertFalse(self.view()['mail']['rows'])

    def test_original_send_mail_and_success_clears_compose_attachment(self):
        self.service('MailOpen');self.publish()
        self.call('SetSendMailMoney(101) SendMail("Gold Goblin","Hello","World")')
        self.assertEqual(len(self.view()['mail']['rows']), 1)
        self.assertEqual(self.view()['mail']['rows'][0]['money'], 101)
        self.assertEqual(self.ui.evaluate('return GetSendMailMoney(),GetSendMailCOD()'), [0, 0])

    def test_mail_failures_custody_capacity_stale_session_and_save(self):
        self.service('MailOpen');item = self.inventory()[0]
        self.service('MailSend', target='player', subject='Keep', item=item['instance_id'])
        before = copy.deepcopy((self.runtime._item_instances, self.runtime._economy_state, self.runtime._services))
        self.assertIn('error', self.service('MailDelete', id=self.view()['mail']['rows'][0]['id']))
        current = copy.deepcopy(self.runtime._services);current['clock'] = before[2]['clock']
        self.assertEqual(before, (self.runtime._item_instances, self.runtime._economy_state, current))
        old = self.view()['session'];self.service('MailClose');self.service('MailOpen')
        result = self.control('service', 'MailItem', session=old, id=self.view()['mail']['rows'][0]['id'])
        self.assertEqual(result['error'], 'SERVICE_WINDOW_CHANGED_OR_CLOSED')
        saved = copy.deepcopy(self.runtime._services)
        self.runtime.save_state();self.runtime.load_state()
        self.assertEqual(saved['mail'], self.runtime._services['mail'])
        self.assertFalse(self.view()['mail']['open'])
        self.assertEqual(self.runtime._item_instance_locked(item['instance_id'])['location'], 'MAIL')
        with self.runtime._lock:self.runtime._assert_service_custody_locked()

    def test_cod_npc_delivery_returns_money_without_inventing_it(self):
        self.service('MailOpen');item = self.inventory()[0];owner = 'npc-wanderer-01'
        before = self.view()['money'];vendor = self.runtime._economy_state['vendors']['vendor.mira']['gold'] * 10000
        sent = self.service('MailSend', target=owner, subject='COD', item=item['instance_id'], cod=20001)
        self.assertNotIn('error', sent)
        with self.runtime._lock:
            self.runtime._service_next_tick = 0;self.runtime._settle_services_locked()
        self.assertEqual(item['location'], 'POCKET');self.assertEqual(item['owner_id'], owner)
        account = self.runtime._economy_state['vendors']['vendor.mira']
        self.assertEqual(account['gold'] * 10000 + account.get('copper', 0), vendor - 20001)
        incoming = self.view()['mail']['rows'][0]
        self.service('MailMoney', id=incoming['id'])
        self.assertEqual(self.view()['money'], before + 20001 - 30)
        self.runtime.load_state()
        self.assertEqual(self.view()['money'], before + 20001 - 30)
        account = self.runtime._economy_state['vendors']['vendor.mira']
        self.assertEqual(account['gold'] * 10000 + account.get('copper', 0), vendor - 20001)

    def test_auction_original_buyout_escrow_mail_commission_and_repeat(self):
        self.assertNotIn('error', self.service('AuctionOpen'));self.publish()
        self.assertEqual(self.ui.evaluate('return GetNumAuctionItems("list")'), [1, 1])
        listing = self.view()['auction']['lists'][0]['rows'][0];before = self.view()['money']
        self.call('PlaceAuctionBid("list",1,' + str(listing['buyout']) + ')')
        self.assertEqual(self.view()['money'], before - listing['buyout'])
        self.assertFalse(self.view()['auction']['lists'][0]['rows'])
        self.assertEqual(self.runtime._item_instance_locked(listing['item'])['location'], 'MAIL')
        after = copy.deepcopy((self.runtime._item_instances, self.runtime._economy_state))
        self.call('PlaceAuctionBid("list",1,' + str(listing['buyout']) + ')')
        self.assertEqual(after, (self.runtime._item_instances, self.runtime._economy_state))
        self.service('MailOpen');mail = self.view()['mail']['rows'][0]
        self.service('MailItem', id=mail['id'])
        self.assertEqual(self.runtime._item_instance_locked(listing['item'])['location'], 'INVENTORY')

    def test_post_cancel_and_offline_expiry_preserve_instance(self):
        self.service('AuctionOpen');item = self.inventory()[0];money = self.view()['money']
        posted = self.service('AuctionStart', item=item['instance_id'], min_bid=10001, buyout=20001, duration=120)
        self.assertNotIn('error', posted)
        auction = self.view()['auction']['lists'][2]['rows'][0]
        self.assertEqual(item['location'], 'AUCTION');self.assertEqual(self.view()['money'], money - 500)
        self.runtime.save_state();self.runtime.load_state()
        with self.runtime._lock:
            self.runtime._services['clock'] = auction['expires'] + 1
            self.runtime._service_next_tick = 0;self.runtime._settle_services_locked()
            self.runtime._assert_service_custody_locked()
        self.assertEqual(self.runtime._item_instance_locked(item['instance_id'])['location'], 'MAIL')
        self.assertFalse(self.view()['auction']['lists'][2]['rows'])
        self.assertEqual(self.view()['money'], money - 500)

    def test_trade_original_cursor_atomic_exchange_and_changed_offer(self):
        identity = self.move_near_npc();item = self.inventory()[0]
        self.service('TradeOpen', target=identity);self.publish()
        slot = item['slot_index'] + 1
        self.call(f'PickupContainerItem(0,{slot}) ClickTradeButton(1) AcceptTrade()')
        self.assertEqual(item['location'], 'INVENTORY')
        self.assertTrue(self.view()['trade']['open'])
        self.call('AcceptTrade()')
        self.assertEqual(self.runtime._item_instance_locked(item['instance_id'])['owner_id'], identity)
        self.assertFalse(self.view()['trade']['open'])
        self.assertEqual(self.runtime._last_trade['policy'], 'ITEM_FOR_ITEM_WHOLE_INSTANCE')

    def test_group_native_roster_targeting_chat_follow_and_reload(self):
        identity = self.move_near_npc();self.publish()
        name = self.runtime._service_unit_locked(identity)['name']
        self.call('InviteByName(' + json.dumps(name) + ')')
        self.assertEqual(self.ui.evaluate('return GetNumPartyMembers(),UnitName("party1"),UnitInParty("party1")'), [1, name, 1])
        self.call('TargetNearestPartyMember()')
        self.assertEqual(self.runtime._combat_target_id, identity)
        self.call('SendChatMessage("Team hello","PARTY")')
        self.assertTrue(any('Team hello' in e['text'] for e in self.runtime.snapshot()['event_journal']['events']))
        with self.runtime._lock:
            index = self.runtime._npc_index_for_id_locked(identity)
            before = math.hypot(self.runtime._x[index] - self.runtime._x[0], self.runtime._z[index] - self.runtime._z[0])
            self.runtime._x[0] += 8;self.runtime._running = True
            try:
                for _ in range(60):self.runtime._tick_locked(1/60)
            finally:self.runtime._running = False
        self.assertGreater(math.hypot(self.runtime._vx[index], self.runtime._vz[index]), 0)
        self.runtime.save_state();self.runtime.load_state();self.publish()
        self.assertEqual(self.ui.evaluate('return GetNumPartyMembers()'), [1])
        self.call('ConvertToRaid()');self.assertEqual(self.ui.evaluate('return GetNumRaidMembers()'), [2])
        self.call('LeaveParty()');self.assertEqual(self.ui.evaluate('return GetNumPartyMembers(),GetNumRaidMembers()'), [0, 0])

    def test_pet_real_animal_one_visual_follow_stable_and_reload(self):
        with self.runtime._lock:
            self.runtime._refresh_nature_locked()
            from backend.game_engine_nature_catalog import ANIMALS, SPECIES
            animal = next(a for a in self.runtime._nature.rows if a['species'] in ANIMALS and SPECIES[a['species']]['domain'] == 'LAND')
            self.runtime._x[0] = animal['x'];self.runtime._z[0] = animal['z'];self.runtime._y[0] = animal['y'] + .65
        result = self.service('PetTame', id=animal['id']);self.assertNotIn('error', result);self.publish()
        self.assertEqual(self.ui.evaluate('return HasPetUI(),PetHasActionBar(),UnitName("pet")')[0:2], [1, 1])
        self.call('PetRename("Copper") PetWait()');self.assertEqual(self.view()['pet']['name'], 'Copper')
        self.assertEqual(self.runtime._active_pet_locked()['command'], 0)
        self.call('PetFollow()')
        with self.runtime._lock:
            pet = self.runtime._active_pet_locked();self.runtime._x[0] += 8
            old = pet['x'];self.runtime._tick_services_locked(.5)
            self.assertNotEqual(old, pet['x'])
            self.runtime._refresh_nature_locked()
            self.assertEqual(sum(r['id'] == pet['id'] for r in self.runtime._nature.rows), 1)
        money = self.view()['money'];self.service('StableOpen');self.publish()
        self.call('BuyStableSlot()');self.assertEqual(self.view()['money'], money - 10000)
        number = self.view()['pet']['number'];self.call('StablePet()')
        self.assertIsNone(self.view()['pet'])
        self.call('UnstablePet(' + str(number) + ')');self.assertEqual(self.view()['pet']['number'], number)
        self.runtime.save_state();self.runtime.load_state();self.publish()
        self.assertEqual(self.ui.evaluate('return (UnitName("pet"))'), ['Copper'])

    def tame(self):
        from backend.game_engine_nature_catalog import ANIMALS,SPECIES
        with self.runtime._lock:
            self.runtime._refresh_nature_locked()
            animal=next(a for a in self.runtime._nature.rows if a['species'] in ANIMALS and SPECIES[a['species']]['domain']=='LAND' and not a.get('dead'))
            self.runtime._x[0]=animal['x'];self.runtime._z[0]=animal['z'];self.runtime._y[0]=animal['y']+.65
        self.assertNotIn('error',self.service('PetTame',id=animal['id']))
        return self.runtime._active_pet_locked()

    def test_transfers_checkpoint_and_failed_save_rolls_back_whole_transaction(self):
        self.service('MailOpen');item=self.inventory()[0]
        before=copy.deepcopy((self.runtime._item_instances,self.runtime._economy_state,self.runtime._services['mail']))
        with patch.object(self.runtime._state_store,'save',side_effect=OSError('disk full')):
            result=self.service('MailSend',target='player',subject='Fail',item=item['instance_id'],money=123)
        self.assertEqual(result['error'],'SERVICE_SAVE_FAILED')
        self.assertEqual(before,(self.runtime._item_instances,self.runtime._economy_state,self.runtime._services['mail']))
        revision=self.runtime._persistence_revision
        self.assertNotIn('error',self.service('MailSend',target='player',subject='Commit',item=item['instance_id'],money=123))
        self.assertGreater(self.runtime._persistence_revision,revision)
        self.runtime.load_state()
        self.assertEqual(self.view()['mail']['rows'][0]['subject'],'Commit')
        self.assertEqual(self.runtime._item_instance_locked(item['instance_id'])['location'],'MAIL')

    def test_bounded_large_mailbox_survives_normal_save_load(self):
        self.service('MailOpen');item=self.inventory()[0]
        self.service('MailSend',target='player',subject='Attachment',item=item['instance_id'])
        with self.runtime._lock:
            for i in range(70):self.runtime._service_mail_locked('player','player',str(i),'x'*4096)
        self.runtime.save_state();self.runtime.load_state()
        self.assertEqual(len(self.runtime._services['mail']),71)
        with self.runtime._lock:self.runtime._assert_service_custody_locked()

    def test_companion_attack_audio_uses_existing_mixer_once_per_journal_event(self):
        from unittest.mock import Mock,call
        mixer=Mock();self.presentation.audio=mixer
        view=self.runtime.snapshot();base=self.presentation.last_sequence or 0
        view['state']='RUNNING';view['event_journal']['events']=[{'sequence':base+1,'kind':'GROUP_ATTACK','text':'Assist'},
                                                             {'sequence':base+2,'kind':'PET_HIT','text':'Hit'}]
        for _ in range(2):self.presentation.last_update=0;self.presentation.update(view)
        self.assertEqual([c for c in mixer.play.call_args_list if c.kwargs.get('gain')==.3],[call(4,gain=.3),call(5,gain=.3)])
        view['state']='PAUSED';view['event_journal']['events']=[{'sequence':base+3,'kind':'PET_ATTACK','text':'Paused'}]
        self.presentation.last_update=0;self.presentation.update(view)
        self.assertEqual(len(mixer.play.call_args_list),2)

    def test_saved_letter_reloads_and_original_reader_opens_and_closes(self):
        self.service('MailOpen');self.service('MailSend',target='player',subject='Letter',body='Keep this text')
        self.publish();self.call('TakeInboxTextItem(1)')
        letter=next(i for i in self.runtime._item_instances.values() if i['definition_id']=='item.gg_letter')
        self.runtime.load_state()
        letter=self.runtime._item_instance_locked(letter['instance_id']);self.assertEqual(letter['letter']['body'],'Keep this text')
        self.assertNotIn('error',self.runtime.action_use_item('item.gg_letter',letter['instance_id']))
        self.publish();self.assertEqual(self.ui.evaluate('return ItemTextGetItem(),ItemTextGetText(),ItemTextGetPage()'),['Letter','Keep this text',1])
        self.call('CloseItemText()');self.assertIsNone(self.runtime._service_text)

    def test_local_auction_buyer_uses_actual_budget_and_delivers_both_sides(self):
        self.service('AuctionOpen');item=self.inventory()[0]
        self.assertNotIn('error',self.service('AuctionStart',item=item['instance_id'],min_bid=1,buyout=2,duration=120))
        with self.runtime._lock:
            old=self.runtime._service_money_locked('npc-wanderer-01')
            self.runtime._services['clock']+=31;self.runtime._service_next_tick=0;self.runtime._settle_services_locked()
            self.assertEqual(self.runtime._service_money_locked('npc-wanderer-01'),old-2)
            self.assertFalse(any(a['owner']=='player' for a in self.runtime._services['auctions']))
            self.runtime._services['clock']+=2;self.runtime._service_next_tick=0;self.runtime._settle_services_locked()
        self.assertEqual(self.runtime._item_instance_locked(item['instance_id'])['owner_id'],'npc-wanderer-01')
        self.assertEqual(self.runtime._item_instance_locked(item['instance_id'])['location'],'POCKET')
        self.runtime.load_state();self.assertFalse(any(a['owner']=='player' for a in self.runtime._services['auctions']))

    def test_multi_item_trade_money_failure_and_commit_are_atomic(self):
        npc=self.move_near_npc();self.service('TradeOpen',target=npc)
        offered=self.inventory()[:2]
        for slot,item in enumerate(offered,1):self.service('TradeSet',slot=slot,item=item['instance_id'])
        self.service('TradeMoney',money=103)
        before=copy.deepcopy((self.runtime._item_instances,self.runtime._economy_state,self.runtime._individual_state))
        revision=self.view()['trade']['offer_revision']
        with patch.object(self.runtime,'_npc_add_inventory_ref_locked',return_value=False):
            result=self.service('TradeAccept',offer_revision=revision)
        self.assertEqual(result['error'],'TRADE_TARGET_INVENTORY_FULL')
        self.assertEqual(before,(self.runtime._item_instances,self.runtime._economy_state,self.runtime._individual_state))
        self.assertNotIn('error',self.service('TradeAccept',offer_revision=revision))
        for item in offered:self.assertEqual(self.runtime._item_instance_locked(item['instance_id'])['owner_id'],npc)
        self.assertEqual(self.view()['money'],before[1]['wallet']['gold']*10000+before[1]['wallet'].get('copper',0)-103)

    def test_pet_spell_damage_retaliation_death_revive_and_no_duplicate_visual(self):
        from backend.game_engine_adapter_services import PET_STRIKE
        pet=self.tame();self.publish()
        self.assertEqual(self.ui.evaluate('return GetSpellName(1,"pet")')[0],'Strike')
        self.service('PetAutocast',spell_id=PET_STRIKE);self.assertTrue(self.view()['pet']['autocast'])
        target='npc-wanderer-01'
        with self.runtime._lock:
            index=self.runtime._npc_index_for_id_locked(target)
            self.runtime._combat_target_id=target;pet.update(x=self.runtime._x[index],y=self.runtime._y[index],z=self.runtime._z[index])
            actor=self.runtime._combat_state['actors'][target];before=actor['health']
        self.assertNotIn('error',self.service('PetSpell',spell_id=PET_STRIKE))
        with self.runtime._lock:
            for _ in range(120):self.runtime._tick+=1;self.runtime._sim_time+=1/60;self.runtime._tick_services_locked(1/60)
            self.assertLess(self.runtime._combat_state['actors'][target]['health'],before)
            pet_actor=self.runtime._combat_state['actors']['pet:'+str(pet['number'])]
            self.assertLess(pet_actor['health'],pet_actor['max_health'])
            pet_actor.update(alive=False,health=0);self.runtime._publish_companions_locked()
            self.assertEqual(sum(r['id']==pet['id'] for r in self.runtime._nature.rows),1)
            self.assertTrue(next(r for r in self.runtime._nature.rows if r['id']==pet['id'])['dead'])
        self.service('StableOpen');money=self.view()['money']
        self.assertNotIn('error',self.service('PetRevive'));self.assertGreater(self.view()['pet']['health'],0)
        self.assertEqual(self.view()['money'],money-100000)

    def test_pet_failed_checkpoint_restores_wild_animal_and_full_stable_native_view(self):
        from backend.game_engine_nature_catalog import ANIMALS,SPECIES
        with self.runtime._lock:
            self.runtime._refresh_nature_locked()
            animal=next(a for a in self.runtime._nature.rows if a['species'] in ANIMALS and SPECIES[a['species']]['domain']=='LAND')
            self.runtime._x[0]=animal['x'];self.runtime._z[0]=animal['z'];self.runtime._y[0]=animal['y']+.65
        with patch.object(self.runtime._state_store,'save',side_effect=OSError('disk full')):
            self.assertEqual(self.service('PetTame',id=animal['id'])['error'],'SERVICE_SAVE_FAILED')
        self.assertFalse(self.runtime._services['pets']);self.assertLess(self.runtime._nature.states.get(animal['id'],{}).get('hidden_until',0),1e10)
        first=self.tame();self.service('StableOpen');self.service('StableBuy');self.service('StableBuy');self.service('StableStore')
        second=self.tame();self.service('StableStore');third=self.tame();self.service('PetDismiss');self.publish()
        self.assertEqual(self.ui.evaluate('return GetNumStableSlots()'),[2])
        self.assertEqual(len(self.runtime._services['pets']),3)
        self.runtime.load_state();self.publish();self.assertIsNone(self.view()['pet'])
        self.service('StableOpen');self.service('StableTake',number=first['number']);self.publish()
        self.assertEqual(self.view()['pet']['number'],first['number'])

    def test_group_marks_original_ready_and_hostile_assist(self):
        npc=self.move_near_npc();self.service('GroupInvite',target=npc);self.publish()
        self.call('ConvertToRaid() SetRaidTarget("raid2",8) DoReadyCheck()')
        self.assertEqual(self.ui.evaluate('return GetRaidTargetIndex("raid2")'),[8])
        enemy=next(v for v in self.runtime._individual_state['individuals'] if v!=npc and self.runtime._npc_index_for_id_locked(v) is not None)
        with self.runtime._lock:
            friend=self.runtime._npc_index_for_id_locked(npc);target=self.runtime._npc_index_for_id_locked(enemy)
            self.runtime._x[friend]=self.runtime._x[target];self.runtime._z[friend]=self.runtime._z[target]
            self.runtime._combat_state['actors']['player']['engaged_target']=enemy
            before=self.runtime._combat_state['actors'][enemy]['health']
            with patch.object(self.runtime,'_npc_line_of_sight_locked',return_value=True):
                for _ in range(90):self.runtime._tick+=1;self.runtime._sim_time+=1/60;self.runtime._tick_group_combat_locked()
            self.assertLess(self.runtime._combat_state['actors'][enemy]['health'],before)
        self.assertEqual(self.runtime.attack(npc)['error'],'COMBAT_FRIENDLY_GROUP_TARGET')

    def test_service_queue_overflow_and_bad_sources_never_partially_commit(self):
        self.service('MailOpen');before = copy.deepcopy(self.runtime._economy_state)
        self.presentation._ui_requests({'services':[{'op':'MailSend','target':'player','subject':'X','money':10}]*129})
        self.assertFalse(self.view()['mail']['rows']);self.assertEqual(before, self.runtime._economy_state)
        self.presentation._ui_requests({'services':[{'op':'MailSend','target':'player','subject':'X','source':[1,1]}]})
        self.assertFalse(self.view()['mail']['rows']);self.assertEqual(before, self.runtime._economy_state)

    def test_implicit_attack_skips_group_member_and_original_target_reports_friend(self):
        npc=self.move_near_npc();self.service('GroupInvite',target=npc)
        with self.runtime._lock:
            index=self.runtime._npc_index_for_id_locked(npc);self.runtime._combat_target_id=''
            actor=self.runtime._combat_state['actors'][npc];hp=actor['health']
            original=list(self.runtime._npc_indices);self.runtime._npc_indices=[index]
            try:self.assertEqual(self.runtime.attack()['error'],'COMBAT_TARGET_REQUIRED')
            finally:self.runtime._npc_indices=original
            self.assertEqual(actor['health'],hp)
            self.runtime._combat_target_id=npc
        self.publish()
        self.assertEqual(self.ui.evaluate('return UnitCanAttack("player","target"),UnitIsFriend("player","target")'),[None,1])


if __name__ == '__main__':
    unittest.main()
