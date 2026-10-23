"""Original charter verbs settle the same paid instance, money and guild."""
import copy
import unittest
from unittest.mock import patch
import test_game_engine_adapter_services as services
from backend.game_engine_adapter_petitions import CHARTER_COST, SIGNATURES
from backend import game_engine_items as items


class Petitions(unittest.TestCase):
    setUp=services.Services.setUp
    publish=services.Services.publish
    call=services.Services.call
    control=services.Services.control
    service=services.Services.service
    view=services.Services.view
    move_near_npc=services.Services.move_near_npc

    def buy(self,name='Island Guild'):
        self.move_near_npc();self.service('PetitionRegistrarOpen',target='npc-wanderer-01');self.publish()
        self.call('BuyGuildCharter("'+name+'")')
        owned=self.view()['petition']['owned'];self.assertEqual(len(owned),1)
        self.service('PetitionOpen',item=owned[0]['item']);self.publish()
        return self.runtime._item_instances[owned[0]['item']]

    def near(self,target):
        with self.runtime._lock:
            index=self.runtime._npc_index_for_id_locked(target);self.assertIsNotNone(index)
            self.runtime._x[0]=self.runtime._x[index]+1;self.runtime._y[0]=self.runtime._y[index];self.runtime._z[0]=self.runtime._z[index]
            self.runtime._combat_state['actors'][target]['engaged_target']=''
            self.runtime._combat_target_id=target
        self.publish()

    def settle(self,advance=0):
        with self.runtime._lock:
            pending=self.runtime._services['petition_offer'];self.assertIsNotNone(pending)
            self.runtime._services['clock']=pending['ready']+.1+advance;self.runtime._service_next_tick=0
            self.runtime._settle_services_locked()
        self.publish()

    def candidates(self):
        return [p['id'] for p in self.view()['people'] if p['id'] in ('npc-wanderer-01','npc-guardian-01','npc-fisher-01')]

    def test_original_buy_offer_names_turnin_paid_once_and_same_saved_guild(self):
        self.move_near_npc();before=self.view()['money'];vendor=self.runtime._service_money_locked('npc-wanderer-01')
        charter=self.buy()
        self.assertEqual(self.view()['money'],before-CHARTER_COST);self.assertEqual(self.runtime._service_money_locked('npc-wanderer-01'),vendor+CHARTER_COST)
        self.assertEqual(self.ui.evaluate('return GetPetitionInfo()'),['charter','Island Guild','',SIGNATURES,'Gold Goblin',1])
        self.assertEqual(self.service('PetitionBuy',name='Duplicate')['error'],'PETITION_ALREADY_OWNED')
        charter=self.runtime._item_instances[charter['instance_id']]
        targets=self.candidates();self.assertEqual(len(targets),SIGNATURES)
        for target in targets:
            self.near(target);self.call('OfferPetition()');self.assertNotIn(target,charter['petition']['signers']);self.settle()
            self.assertIn(target,charter['petition']['signers'])
        self.assertEqual(self.ui.evaluate('return GetNumPetitionNames()'),[SIGNATURES])
        names=[self.runtime._service_unit_locked(p)['name'] for p in targets]
        self.assertEqual(self.ui.evaluate('return GetPetitionNameInfo(1),GetPetitionNameInfo(2),GetPetitionNameInfo(3)'),names)
        self.move_near_npc();self.call('TurnInGuildCharter()')
        self.assertNotIn(charter['instance_id'],self.runtime._item_instances)
        self.assertNotIn('item.guild_charter',self.runtime._inventory)
        self.assertEqual(set(self.view()['guild']['members']),set(['player']+targets))
        self.assertEqual(self.view()['money'],before-CHARTER_COST)
        self.call('TurnInGuildCharter()');self.assertEqual(self.view()['money'],before-CHARTER_COST)
        self.runtime.load_state();self.assertEqual(self.view()['guild']['name'],'Island Guild')

    def test_purchase_and_turnin_save_failures_restore_assets_and_original_session(self):
        self.move_near_npc();self.service('PetitionRegistrarOpen',target='npc-wanderer-01')
        before=copy.deepcopy((self.runtime._item_instances,self.runtime._inventory,self.runtime._economy_state,self.runtime._services))
        with patch.object(self.runtime,'save_state',side_effect=OSError('fixture disk')):
            self.assertEqual(self.service('PetitionBuy',name='Retained')['error'],'SERVICE_SAVE_FAILED')
        now=copy.deepcopy(self.runtime._services);now['clock']=before[-1]['clock'];self.assertEqual(before,(self.runtime._item_instances,self.runtime._inventory,self.runtime._economy_state,now))
        charter=self.buy();charter['petition']['signers']=self.candidates();self.runtime.save_state()
        before=copy.deepcopy((self.runtime._item_instances,self.runtime._inventory,self.runtime._economy_state,self.runtime._services))
        with patch.object(self.runtime,'save_state',side_effect=OSError('fixture disk')):
            self.assertEqual(self.service('PetitionTurnIn')['error'],'SERVICE_SAVE_FAILED')
        now=copy.deepcopy(self.runtime._services);now['clock']=before[-1]['clock'];self.assertEqual(before,(self.runtime._item_instances,self.runtime._inventory,self.runtime._economy_state,now))
        self.assertNotIn('error',self.service('PetitionTurnIn'))

    def test_offer_pending_out_of_range_expiry_repeat_and_failed_settlement(self):
        charter=self.buy();self.service('PetitionOffer',target='npc-wanderer-01')
        self.assertEqual(self.service('PetitionOffer',target='npc-wanderer-01')['error'],'PETITION_OFFER_PENDING')
        with patch.object(self.runtime,'save_state',side_effect=OSError('fixture disk')):self.settle()
        self.assertTrue(self.runtime._services['petition_offer']);self.assertFalse(self.runtime._item_instances[charter['instance_id']]['petition']['signers'])
        self.settle();charter=self.runtime._item_instances[charter['instance_id']]
        self.assertEqual(charter['petition']['signers'],['npc-wanderer-01'])
        self.assertEqual(self.service('PetitionOffer',target='npc-wanderer-01')['error'],'PETITION_ALREADY_SIGNED_OR_FULL')
        self.near('npc-guardian-01');self.service('PetitionOffer',target='npc-guardian-01');self.runtime._x[0]+=100;self.settle()
        self.assertEqual(charter['petition']['signers'],['npc-wanderer-01'])
        self.near('npc-guardian-01');self.service('PetitionOffer',target='npc-guardian-01');self.settle(advance=20)
        self.assertEqual(charter['petition']['signers'],['npc-wanderer-01'])

    def test_reopen_restore_rename_resets_consent_and_deleted_item_cannot_turnin(self):
        charter=self.buy();charter['petition']['signers']=['npc-guardian-01'];self.runtime.save_state();self.runtime.load_state()
        self.assertFalse(self.view()['petition']['open']);self.assertEqual(self.view()['petition']['owned'][0]['title'],'Island Guild')
        self.move_near_npc();self.service('PetitionOpen',item=charter['instance_id']);self.publish();self.call('RenamePetition("New Island Guild")')
        charter=self.runtime._item_instances[charter['instance_id']];self.assertEqual(charter['petition']['title'],'New Island Guild');self.assertFalse(charter['petition']['signers'])
        with self.runtime._lock:self.runtime._rebuild_content_runtime_locked()
        self.assertEqual(self.runtime._item_instances[charter['instance_id']]['petition']['title'],'New Island Guild')
        self.service('InventoryDestroy',item=charter['instance_id']);self.service('PetitionRegistrarOpen',target='npc-wanderer-01')
        self.assertEqual(self.service('PetitionTurnIn')['error'],'PETITION_NOT_IN_BACKPACK')

    def test_incoming_paid_npc_charter_sign_decline_and_no_player_self_sign(self):
        self.move_near_npc();before=self.view()['money'];npc_money=self.runtime._service_money_locked('npc-wanderer-01')
        self.assertNotIn('error',self.service('PetitionRequestOffer',target='npc-wanderer-01',name='Miras Guild'));self.publish()
        # The registrar owns this incoming charter and receives her own fee;
        # this must leave her wallet and the player's wallet unchanged.
        self.assertEqual(self.runtime._service_money_locked('npc-wanderer-01'),npc_money)
        self.assertEqual(self.ui.evaluate('return CanSignPetition()'),[1]);key=self.view()['petition']['record']['item']
        self.call('SignPetition() SignPetition()');self.assertEqual(self.runtime._item_instances[key]['petition']['signers'],['player'])
        self.assertEqual(self.view()['money'],before);self.assertEqual(self.ui.evaluate('return CanSignPetition()'),[None])
        self.call('ClosePetition()');self.assertFalse(self.view()['petition']['open'])
        self.runtime.load_state();self.assertEqual(self.runtime._item_instances[key]['petition']['signers'],['player'])
        self.assertEqual((self.runtime._item_instances[key]['owner_id'],self.runtime._item_instances[key]['location']),('npc-wanderer-01','POCKET'))

    def test_stale_registrar_range_and_bounded_duplicate_signature_restore(self):
        charter=self.buy();old=self.view()['session'];self.service('PetitionRegistrarClose');self.service('PetitionRegistrarOpen',target='npc-wanderer-01')
        self.assertEqual(self.control('service','PetitionBuy',session=old,name='Stale')['error'],'SERVICE_WINDOW_CHANGED_OR_CLOSED')
        self.runtime._x[0]+=100;self.assertEqual(self.service('PetitionTurnIn')['error'],'SERVICE_PERSON_OUT_OF_REACH')
        broken=copy.deepcopy(charter);broken['petition']['signers']=['npc-wanderer-01']*2
        self.assertNotIn('petition',items.normalize_instance(self.runtime._item_catalog,broken))

if __name__=='__main__':unittest.main()
