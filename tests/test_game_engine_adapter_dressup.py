"""Original dressing-room verbs change a render look without moving any item."""
import copy
import unittest
from unittest.mock import patch
import test_game_engine_adapter_services as services
from backend.game_engine_adapter_gameplay import identity


class Dressup(unittest.TestCase):
    publish=services.Services.publish
    call=services.Services.call
    control=services.Services.control
    service=services.Services.service
    view=services.Services.view

    def setUp(self):
        services.Services.setUp(self)
        self.ui.execute("DressUpModel=CreateFrame('DressUpModel','DressUpModel')")

    def room(self):return self.view()['dressup']
    def try_on(self,ref):self.call('DressUpModel:TryOn('+str(identity(ref))+')')

    def test_original_set_unit_try_on_and_reset_change_only_the_shared_render_descriptor(self):
        before=copy.deepcopy((self.runtime._inventory,self.runtime._item_instances,self.runtime._economy_state,self.runtime._item_counter))
        with patch.object(self.runtime,'save_state',wraps=self.runtime.save_state) as save:
            self.call("DressUpModel:SetUnit('player')")
            self.assertTrue(self.room()['open'])
            self.try_on('item.tideguard_jacket')
            jacket=next(r for r in self.room()['equipment'] if r['equipped_slot']=='CHEST')
            self.assertEqual(jacket['definition_id'],'item.tideguard_jacket');self.assertTrue(jacket['preview_only'])
            self.assertNotIn(jacket['instance_id'],self.runtime._item_instances)
            self.assertTrue(jacket['visual']['asset_id'])
            self.call('DressUpModel:Dress()')
            self.assertFalse(any(r['definition_id']=='item.tideguard_jacket' for r in self.room()['equipment']))
            self.assertFalse(save.called)
        self.assertEqual(before,(self.runtime._inventory,self.runtime._item_instances,self.runtime._economy_state,self.runtime._item_counter))

    def test_undress_preserves_held_items_and_try_on_replays_original_held_eviction(self):
        self.call('DressUpModel:Dress();DressUpModel:Undress()')
        self.assertEqual({r['equipped_slot'] for r in self.room()['equipment']},{'MAIN_HAND','OFF_HAND'})
        self.try_on('item.weapon_bow')
        self.assertEqual([(r['definition_id'],r['equipped_slot']) for r in self.room()['equipment']],[('item.weapon_bow','RANGED')])
        self.try_on('item.weapon_wand')
        self.assertEqual([(r['definition_id'],r['equipped_slot']) for r in self.room()['equipment']],[('item.weapon_wand','RANGED')])
        self.try_on('item.iron_saber')
        self.assertEqual([(r['definition_id'],r['equipped_slot']) for r in self.room()['equipment']],[('item.iron_saber','MAIN_HAND')])
        self.assertEqual(self.runtime._item_instances['starter-iron-saber']['location'],'EQUIPPED')

    def test_nonwearable_unknown_templates_and_world_hidden_cloak_do_not_grant_items(self):
        self.runtime._player_display['cloak']=False
        self.call('DressUpModel:Dress()')
        self.assertFalse(any(r['equipped_slot']=='BACK' for r in self.room()['equipment']))
        self.try_on('item.drift_cloak')
        self.assertTrue(any(r['equipped_slot']=='BACK' for r in self.room()['equipment']))
        before=copy.deepcopy(self.room()['equipment']);self.try_on('material.fiber')
        self.assertEqual(before,self.room()['equipment'])
        self.assertEqual(self.service('DressupTryOn',id=1)['error'],'DRESSUP_TEMPLATE_UNKNOWN')
        self.assertEqual(before,self.room()['equipment'])

    def test_rotation_close_and_character_restore_leave_no_preview_custody_or_saved_outfit(self):
        self.call('DressUpModel:Dress();DressUpModel:SetRotation(0.61)')
        self.assertAlmostEqual(self.room()['angle'],0.61*180/3.141592653589793,places=4)
        self.assertEqual(self.service('DressupRotate',angle=float('nan'))['error'],'DRESSUP_ANGLE_INVALID')
        self.assertIsNone(self.service('DressupClose').get('error'))
        self.assertFalse(self.room()['open']);self.assertFalse(self.room()['equipment'])
        self.call('DressUpModel:Dress()');self.try_on('item.weapon_bow')
        self.runtime.save_state();self.runtime.load_state();self.publish()
        self.assertFalse(self.room()['open'])
        self.assertFalse(any(r['instance_id'].startswith('dressup-') for r in self.runtime._item_instances.values()))

if __name__=='__main__':unittest.main()
