"""Original Lua petition verbs/getters over actual saved-character consent."""
import json
import unittest

from backend.game_engine_adapter_gameplay import GameplayViews
from backend.game_engine_adapter_ui import GgEngineUI
from tests import test_game_engine_local_petitions_services as fixture


class NativeSharedPetitions(unittest.TestCase):
    bind = fixture.SharedPetitions.bind
    switch = fixture.SharedPetitions.switch
    view = fixture.SharedPetitions.view
    near_registrar = fixture.SharedPetitions.near_registrar
    public = fixture.SharedPetitions.public
    buy = fixture.SharedPetitions.buy

    def setUp(self):
        fixture.SharedPetitions.setUp(self)
        self.ui = GgEngineUI(clock=100); self.addCleanup(self.ui.close)
        self.gameplay = GameplayViews(); self.publish()

    def publish(self):
        snapshot = self.runtime.snapshot(); data = self.gameplay.update(snapshot)
        self.ui.publish(snapshot['player'], False, 100, 100, name=self.runtime._local_character_name, **data)

    def call(self, source):
        self.ui.execute(source); requests = self.ui.request('requests')
        for request in requests.get('services', []):
            row = self.gameplay.services.route(request, self.gameplay.inventory_refs, self.gameplay.equipment_refs)
            result = self.runtime.client_control(json.dumps(row)); self.assertNotIn('error', result, result)
        self.publish()
        return requests

    def test_original_sign_and_getters_resolve_actual_owner_without_inventory_copy_then_rename_clears_consent(self):
        key = self.buy(); self.public('PetitionOffer', target=self.second)
        owner_name = self.session.rows[0]['name']
        self.switch(self.second); self.publish()
        self.assertEqual(self.ui.evaluate('return GetPetitionInfo()'), ['charter', 'Real Saved Guild', '', 3, owner_name, None])
        self.assertEqual(self.ui.evaluate('return CanSignPetition(),GetNumPetitionNames()'), [1, 0])
        self.call('SignPetition()')
        self.assertFalse(any(i['definition_id'] == 'item.guild_charter' for i in self.runtime._item_instances.values()))
        self.switch(self.first); self.public('PetitionOpen', item=key); self.publish()
        self.assertEqual(self.ui.evaluate('return GetNumPetitionNames(),GetPetitionNameInfo(1)'), [1, 'Second Hero'])
        self.call('RenamePetition("Original Lua New Terms")')
        self.assertEqual(self.ui.evaluate('return GetPetitionInfo()'), ['charter', 'Original Lua New Terms', '', 3, owner_name, 1])
        self.assertEqual(self.ui.evaluate('return GetNumPetitionNames()'), [0])
        self.switch(self.second); self.publish()
        self.assertFalse(self.view()['petition']['open'])

    def test_original_close_declines_actual_offer_and_new_login_cannot_revive_it(self):
        key = self.buy(); self.public('PetitionOffer', target=self.second)
        self.switch(self.second); self.publish()
        self.assertEqual(self.ui.evaluate('return CanSignPetition()'), [1])
        self.call('ClosePetition()')
        self.assertEqual(self.runtime._local_custody_store.snapshot()['shared']['petition_offers'], {})
        self.switch(self.first)
        self.assertEqual(self.runtime._item_instances[key]['petition']['signers'], [])
        self.switch(self.second); self.publish()
        self.assertFalse(self.view()['petition']['open'])

