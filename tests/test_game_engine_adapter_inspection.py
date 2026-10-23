"""Actual equipment descriptors, combat-status cancellation and spell text."""
import copy
import unittest
from unittest.mock import patch
import test_game_engine_adapter_services as service_tests
from backend import game_engine_combat as combat, game_engine_items as items
from backend.game_engine_adapter_gameplay import identity


class Inspection(unittest.TestCase):
    setUp=service_tests.Services.setUp
    publish=service_tests.Services.publish
    call=service_tests.Services.call
    control=service_tests.Services.control
    view=service_tests.Services.view
    service=service_tests.Services.service
    move_near_npc=service_tests.Services.move_near_npc

    def test_original_friendly_inspect_exact_equipment_and_range_invalidation(self):
        person=self.move_near_npc();self.service('GroupInvite',target=person)
        with self.runtime._lock:
            state=self.runtime._individual_state['individuals'][person]
            for old in list(self.runtime._npc_equipped_instances_locked(person)):
                if old.get('equipped_slot')=='MAIN_HAND':
                    self.runtime._npc_remove_equipment_ref_locked(state,old['definition_id']);self.runtime._npc_add_inventory_ref_locked(state,old['definition_id'])
                    items.transition_instance(old,'POCKET',owner_id=person)
            sword=items.make_instance(self.runtime._item_catalog,'inspect-fixture','item.weapon_sword',location='EQUIPPED',owner_id=person,equipped_slot='MAIN_HAND')
            self.runtime._item_instances[sword['instance_id']]=sword;self.runtime._npc_add_equipment_ref_locked(state,sword['definition_id'])
        self.publish();self.assertEqual(self.ui.evaluate('return CanInspect("party1"),CheckInteractDistance("party1",1)'),[1,1])
        self.call('NotifyInspect("party1")')
        link=self.ui.evaluate('return GetInventoryItemLink("party1",16)')[0]
        self.assertIn(str(identity('item.weapon_sword')),link)
        before=copy.deepcopy(self.runtime._item_instances);self.call('ClearInspectPlayer()');self.assertFalse(self.view()['inspection']['open']);self.assertEqual(before,self.runtime._item_instances)
        self.call('NotifyInspect("party1")')
        with self.runtime._lock:self.runtime._x[0]+=30
        self.publish();self.assertEqual(self.ui.evaluate('return CanInspect("party1")'),[None]);self.assertFalse(self.view()['inspection']['open'])

    def test_original_helpful_aura_cancel_changes_live_effect_and_survives_load(self):
        with self.runtime._lock:
            actor=self.runtime._combat_state['actors']['player']
            combat.apply_status(actor,dict(kind='ward',amount=10.,duration_s=12.,source_id='enchant.test'),'player',self.runtime._sim_time)
            combat.apply_status(actor,dict(kind='poison',amount=1.,duration_s=12.,source_id='enchant.poison'),'npc-wanderer-01',self.runtime._sim_time)
        self.publish();self.assertEqual(self.ui.evaluate('return (UnitBuff("player",1)),(UnitDebuff("player",1))'),['Interface\\Icons\\Spell_Nature_Rejuvenation','Interface\\Icons\\Spell_Nature_CorrosiveBreath'])
        self.call('CancelPlayerBuff(GetPlayerBuff(0,"HELPFUL"))')
        statuses=self.runtime._combat_state['actors']['player']['statuses'];self.assertEqual([s['kind'] for s in statuses],['poison'])
        self.assertEqual(self.service('AuraCancel',id=identity('aura:enchant.poison:poison'))['error'],'AURA_NOT_CANCELABLE')
        self.runtime.load_state();self.assertEqual([s['kind'] for s in self.runtime._combat_state['actors']['player']['statuses']],['poison'])

    def test_failed_aura_commit_preserves_effect(self):
        with self.runtime._lock:
            actor=self.runtime._combat_state['actors']['player'];combat.apply_status(actor,dict(kind='regen',amount=3.,duration_s=12.,source_id='enchant.regen'),'player',self.runtime._sim_time)
        before=copy.deepcopy(self.runtime._combat_state)
        with patch.object(self.runtime._state_store,'save',side_effect=OSError('disk full')):
            result=self.service('AuraCancel',id=identity('aura:enchant.regen:regen'))
        self.assertEqual(result['error'],'SERVICE_SAVE_FAILED');self.assertEqual(before,self.runtime._combat_state)

    def test_original_spell_tooltip_has_actual_energy_cost_and_effect(self):
        self.ui.execute('GGTip=CreateFrame("GameTooltip","GGAbilityTip");GGTip:SetSpell(1,"spell")')
        self.assertGreaterEqual(self.ui.evaluate('return GGTip:NumLines()')[0],4)
        asks=self.ui.request('requests');self.assertFalse(any(r['feature']=='tooltip_spell' for r in asks['unimplemented']))

if __name__=='__main__':unittest.main()
