"""Real LocalCharacters switch/consent and canonical public service commands."""
import copy
import json
import unittest
from unittest.mock import patch

from backend import game_engine_character_creation as appearance
from backend.game_engine_adapter_petitions import CHARTER_COST, REGISTRAR
from backend.game_engine_local_custody import RecoveryRequired
from tests import test_game_engine_local_custody_services as fixture


class SharedPetitions(unittest.TestCase):
    setUp = fixture.SharedServices.setUp
    bind = fixture.SharedServices.bind
    switch = fixture.SharedServices.switch
    view = fixture.SharedServices.view

    def near_registrar(self):
        with self.runtime._lock:
            self.runtime._ensure_combat_actors_locked()
            index = self.runtime._npc_index_for_id_locked(REGISTRAR)
            self.runtime._x[0] = self.runtime._x[index] + 1
            self.runtime._y[0] = self.runtime._y[index]
            self.runtime._z[0] = self.runtime._z[index]
            self.runtime._combat_state['actors'][REGISTRAR]['engaged_target'] = ''

    def public(self, op, *, expect_error=None, refs=None, **fields):
        row = dict(kind='service', op=op, session=self.runtime._service_generation, **fields)
        if op in ('PetitionOffer', 'PetitionSign', 'PetitionClose', 'PetitionRename', 'PetitionTurnIn'):
            petition = self.view()['petition']
            record = refs if refs is not None else (petition['owned'][0] if op == 'PetitionTurnIn' else petition.get('record') or {})
            row.update({k:record[k] for k in ('petition_owner', 'petition_asset', 'petition_terms', 'petition_offer') if k in record})
        with patch('time.time', return_value=2_000_000_000.):
            result = self.runtime.client_control(json.dumps(row))
        if expect_error is None:self.assertNotIn('error', result, result)
        else:self.assertEqual(result.get('error'), expect_error, result)
        return result

    def buy(self, name='Real Saved Guild'):
        self.runtime._economy_state['wallet']['gold'] = 100
        self.near_registrar(); before = self.view()['money']
        self.public('PetitionRegistrarOpen', target=REGISTRAR)
        self.public('PetitionBuy', name=name)
        owned = self.view()['petition']['owned'][0]
        self.assertEqual(self.view()['money'], before - CHARTER_COST)
        self.public('PetitionOpen', item=owned['item'])
        return owned['item']

    def test_real_paid_charter_offer_switch_explicit_sign_logout_and_owner_reload_preserve_actual_consent(self):
        key = self.buy(); paid = self.view()['money']
        self.public('PetitionOffer', target=self.second)
        self.assertEqual(self.runtime._item_instances[key]['petition']['signers'], [])
        owner_name = self.session.rows[0]['name']; self.switch(self.second)
        incoming = self.view()['petition']
        self.assertTrue(incoming['open']); self.assertTrue(incoming['can_sign'])
        self.assertEqual(incoming['record']['owner_name'], owner_name)
        self.assertFalse(any(i['definition_id'] == 'item.guild_charter' for i in self.runtime._item_instances.values()))
        self.public('PetitionSign')
        self.assertFalse(self.view()['petition']['open'])
        self.switch(self.first)
        self.assertEqual(self.runtime._item_instances[key]['petition']['signers'], [self.second])
        self.public('PetitionOpen', item=key)
        self.assertEqual(self.view()['petition']['record']['signer_names'], ['Second Hero'])
        self.assertEqual(self.view()['money'], paid)

    def test_three_actual_saved_signers_form_existing_shared_guild_for_one_real_charter_fee(self):
        self.assertTrue(self.session.logout(), self.session.error)
        for name in ('Third Hero', 'Fourth Hero'):
            self.assertTrue(self.session.create(name, appearance.catalog()['defaults']), self.session.error)
        self.assertTrue(self.session.enter(self.first), self.session.error)
        self.bind(self.first)
        recipients = [row['id'] for row in self.session.rows if row['id'] != self.first]
        self.runtime._local_custody_cache = None
        key = self.buy(); paid = self.view()['money']
        for recipient in recipients:
            self.public('PetitionOffer', target=recipient)
            self.switch(recipient); self.public('PetitionSign'); self.switch(self.first)
            self.public('PetitionOpen', item=key)
        self.near_registrar(); self.public('PetitionRegistrarOpen', target=REGISTRAR)
        refs = copy.deepcopy(self.view()['petition']['owned'][0])
        self.public('PetitionTurnIn', refs=refs, custody_sequence=20)
        self.assertNotIn(key, self.runtime._item_instances)
        self.assertEqual(self.view()['money'], paid)
        self.assertEqual(self.view()['guild']['name'], 'Real Saved Guild')
        self.assertEqual(len(self.view()['guild']['roster']), 4)
        self.assertEqual(self.runtime._services['guild'], {})
        self.public('PetitionTurnIn', refs=refs, custody_sequence=20)
        self.assertEqual(self.view()['money'], paid)
        self.switch(recipients[0])
        self.assertEqual(self.view()['guild']['name'], 'Real Saved Guild')
        self.assertEqual(len(self.view()['guild']['roster']), 4)

    def test_real_recipient_decline_and_bounded_expiry_never_invent_signatures(self):
        key = self.buy(); self.public('PetitionOffer', target=self.second)
        self.switch(self.second); self.public('PetitionClose')
        self.assertFalse(self.view()['petition']['open'])
        self.switch(self.first); self.public('PetitionOpen', item=key)
        self.assertEqual(self.runtime._item_instances[key]['petition']['signers'], [])
        self.public('PetitionOffer', target=self.second)
        self.runtime._local_custody_store.settle(self.first, 30, now=2_000_000_061.)
        self.runtime._local_custody_cache = None
        self.switch(self.second)
        self.assertFalse(self.view()['petition']['open'])
        self.switch(self.first)
        self.assertEqual(self.runtime._item_instances[key]['petition']['signers'], [])

    def test_rename_resets_saved_signature_and_frozen_old_offer_cannot_sign_new_terms(self):
        key = self.buy(); self.public('PetitionOffer', target=self.second)
        self.switch(self.second); old = copy.deepcopy(self.view()['petition']['record'])
        self.public('PetitionSign'); self.switch(self.first); self.public('PetitionOpen', item=key)
        self.public('PetitionRename', name='New Explicit Terms')
        self.assertEqual(self.runtime._item_instances[key]['petition']['signers'], [])
        self.public('PetitionOffer', target=self.second)
        self.switch(self.second)
        self.public('PetitionSign', refs=old, expect_error='PETITION_SHOWN_REFERENCE_CHANGED')
        self.assertEqual(self.view()['petition']['record']['title'], 'New Explicit Terms')
        self.public('PetitionSign')

    def test_exact_shared_sign_replay_preserves_live_gameplay_and_cannot_add_second_signature(self):
        self.buy(); self.public('PetitionOffer', target=self.second)
        self.switch(self.second); refs = copy.deepcopy(self.view()['petition']['record'])
        self.public('PetitionSign', refs=refs, custody_sequence=50)
        self.runtime._economy_state['wallet']['gold'] += 1
        live = copy.deepcopy(self.runtime._economy_state)
        self.public('PetitionSign', refs=refs, custody_sequence=50)
        self.assertEqual(self.runtime._economy_state, live)
        self.switch(self.first)
        self.assertEqual(self.runtime._owned_charters_locked()[0]['petition']['signers'], [self.second])

    def test_registered_destroy_uses_one_journal_and_releases_real_offers_and_delete_blocker(self):
        key = self.buy(); self.public('PetitionOffer', target=self.second)
        before = self.runtime._local_custody_store.snapshot()['shared']['revision']
        self.public('InventoryDestroy', item=key)
        after = self.runtime._local_custody_store.snapshot()
        self.assertEqual(after['shared']['revision'], before + 1)
        self.assertEqual(after['shared']['petition_offers'], {})
        self.assertNotIn(key, self.runtime._item_instances)
        self.assertTrue(self.runtime._local_custody_store.can_delete(self.second, include_history=False)['allowed'])
        self.assertTrue(self.session.logout(), self.session.error)

    def test_actual_failed_checkpoint_has_no_signature_and_committed_recovery_preserves_live_systems(self):
        self.buy(); self.public('PetitionOffer', target=self.second)
        self.switch(self.second); refs = copy.deepcopy(self.view()['petition']['record'])
        with patch.object(self.runtime, 'save_state', side_effect=OSError('actual checkpoint unavailable')):
            self.public('PetitionSign', refs=refs, expect_error='LOCAL_CUSTODY_SAVE_FAILED')
        self.assertTrue(self.view()['petition']['can_sign'])
        self.runtime._ensure_combat_actors_locked(); self.runtime._x[0] = 41.
        before = copy.deepcopy((self.runtime._combat_state, self.runtime._spell_state, self.runtime._services))
        store = self.runtime._local_custody_store
        fired = []
        def fault(stage, name):
            if stage == 'replaced' and name == self.first + '.json' and not fired:
                fired.append(True); raise OSError('actual owner commit uncertain')
        store.fault = fault
        try:self.public('PetitionSign', refs=refs)
        finally:store.fault = None
        self.assertEqual(self.runtime._x[0], 41.)
        self.assertEqual((self.runtime._combat_state, self.runtime._spell_state, self.runtime._services), before)

    def test_repeated_views_do_not_read_profiles_write_or_send_synthetic_petition_events(self):
        self.buy(); self.public('PetitionOffer', target=self.second); self.switch(self.second)
        initial = self.view()['petition']; store = self.runtime._local_custody_store
        with patch.object(store, 'snapshot', side_effect=AssertionError('paint reads profiles')):
            with patch.object(store, 'roster', side_effect=AssertionError('paint reads roster')):
                with patch.object(self.runtime, 'save_state', side_effect=AssertionError('paint saves')):
                    for _ in range(12):self.assertEqual(self.view()['petition'], initial)
        self.assertFalse(any(e['event'] == 'PETITION_SHOW' for e in self.view()['shared_pending_events']))

    def test_npc_offer_path_stays_physical_and_mixed_saved_npc_consent_is_rejected(self):
        key = self.buy()
        self.public('PetitionOffer', target=REGISTRAR)
        pending = self.runtime._services['petition_offer']
        self.assertIsNotNone(pending)
        self.public('PetitionOffer', target=self.second, expect_error='PETITION_OFFER_PENDING')
        with self.runtime._lock:
            self.runtime._services['clock'] = pending['ready'] + .1
            self.runtime._service_next_tick = 0
            self.runtime._settle_services_locked()
        self.assertEqual(self.runtime._item_instances[key]['petition']['signers'], [REGISTRAR])
        self.public('PetitionOffer', target=self.second, expect_error='PETITION_MIXED_SIGNATURES')

    def test_pending_shared_offer_does_not_capture_original_npc_sign_or_close_window(self):
        self.buy(); self.public('PetitionOffer', target=self.second); self.switch(self.second)
        self.near_registrar()
        self.public('PetitionRequestOffer', target=REGISTRAR, name='Actual NPC Petition')
        record = self.view()['petition']['record']
        self.assertNotIn('petition_offer', record)
        key = record['item']; self.public('PetitionSign')
        self.assertEqual(self.runtime._item_instances[key]['petition']['signers'], ['player'])
        self.public('PetitionClose')
        self.assertEqual(self.view()['petition']['record']['petition_owner'], self.first)
        self.public('PetitionSign')

    def test_expired_reserved_shared_sequence_cannot_enter_original_npc_offer_path(self):
        key = self.buy(); self.public('PetitionOffer', target=self.second, custody_sequence=11)
        before = copy.deepcopy(self.runtime._services['petition_offer'])
        self.public('PetitionOffer', target=REGISTRAR, custody_sequence=11, expect_error='LOCAL_CUSTODY_REPLAY_CHANGED')
        self.assertEqual(self.runtime._services['petition_offer'], before)
        self.assertEqual(self.runtime._item_instances[key]['petition']['signers'], [])

    def test_registered_destroy_exact_replay_cannot_consume_another_actual_item(self):
        key = self.buy(); self.public('PetitionOffer', target=self.second)
        self.public('InventoryDestroy', item=key, custody_sequence=13)
        self.public('InventoryDestroy', item=key, custody_sequence=13)
        other = next(i['instance_id'] for i in self.runtime._item_instances.values() if i['owner_id']=='player' and i['location']=='INVENTORY')
        self.public('InventoryDestroy', item=other, custody_sequence=13, expect_error='LOCAL_CUSTODY_REPLAY_CHANGED')
        self.assertIn(other, self.runtime._item_instances)

    def test_real_saved_character_named_target_does_not_replace_original_world_target(self):
        self.assertTrue(self.session.logout(), self.session.error)
        self.assertTrue(self.session.create('Target', appearance.catalog()['defaults']), self.session.error)
        self.assertTrue(self.session.enter(self.first), self.session.error); self.bind(self.first)
        self.buy(); self.runtime._combat_target_id = REGISTRAR
        self.public('PetitionOffer', target='target')
        self.assertEqual(self.runtime._services['petition_offer']['target'], REGISTRAR)
        self.assertEqual(self.runtime._local_custody_store.snapshot()['shared'].get('petition_offers', {}), {})

    def test_actual_shared_guild_membership_blocks_parallel_original_npc_charter_signing(self):
        self.near_registrar(); self.public('PetitionRequestOffer', target=REGISTRAR, name='NPC Unsigned Charter')
        key = self.view()['petition']['record']['item']
        self.runtime._economy_state['wallet']['gold'] = 100
        self.public('GuildCreate', name='Actual Shared Membership')
        self.assertFalse(self.view()['petition']['can_sign'])
        self.public('PetitionSign', expect_error='GUILD_ALREADY_MEMBER')
        self.assertEqual(self.runtime._item_instances[key]['petition']['signers'], [])
        self.assertEqual(self.runtime._services['guild'], {})

