"""Original travel verbs move the one saved local character and real coins."""
import copy
import math
import unittest
from unittest.mock import patch
import test_game_engine_adapter_services as service_tests

class Travel(unittest.TestCase):
    setUp=service_tests.Services.setUp
    publish=service_tests.Services.publish
    call=service_tests.Services.call
    control=service_tests.Services.control
    view=service_tests.Services.view
    service=service_tests.Services.service
    move_near_npc=service_tests.Services.move_near_npc

    def open_route(self):
        person=self.move_near_npc();self.assertIsNone(self.service('TaxiOpen',target=person).get('error'))
        self.publish()
        nodes=self.view()['travel']['nodes'];index=next(i for i,r in enumerate(nodes,1) if not r['current'])
        return index,nodes[index-1]

    def test_original_taxi_fare_motion_input_gate_reload_and_single_arrival(self):
        index,node=self.open_route();money=self.view()['money'];start=self.runtime._lifecycle_position_locked()
        self.ui.execute("controlEvents={};cf=CreateFrame('Frame');cf:RegisterEvent('PLAYER_CONTROL_LOST');cf:RegisterEvent('PLAYER_CONTROL_GAINED');cf:SetScript('OnEvent',function() table.insert(controlEvents,event) end)")
        self.assertEqual(self.ui.evaluate(f'return NumTaxiNodes(),TaxiNodeName({index}),TaxiNodeCost({index})'),[len(self.view()['travel']['nodes']),node['name'],node['cost']])
        self.call(f'TakeTaxiNode({index})');self.assertEqual(self.view()['money'],money-node['cost']);self.assertEqual(self.ui.evaluate('return UnitOnTaxi("player")'),[1])
        self.assertEqual(self.ui.evaluate('return table.concat(controlEvents,",")'),['PLAYER_CONTROL_LOST'])
        before=copy.deepcopy((self.runtime._item_instances,self.runtime._resource,self.runtime._economy_state,self.runtime._actions.auto_attack))
        for result in (self.runtime.attack(),self.runtime.activate_ability('ability.surge'),self.runtime.action_command('ATTACK'),self.runtime.action_use_item('item.gg_letter')):
            self.assertEqual(result.get('error'),'TAXI_IN_PROGRESS')
        self.assertEqual(before,(self.runtime._item_instances,self.runtime._resource,self.runtime._economy_state,self.runtime._actions.auto_attack))
        self.assertEqual(self.service('TaxiTake',destination=node['id'])['error'],'TAXI_IN_PROGRESS')
        with self.runtime._lock:
            duration=self.runtime._services['taxi_flight']['duration'];self.runtime._tick_travel_locked(duration/2)
        middle=self.runtime._lifecycle_position_locked();self.assertGreater(math.dist(tuple(middle.values()),tuple(start.values())),10)
        self.assertEqual(self.runtime._client_tick_input_locked(dict(forward=1.,turn=1.,grapple=True))['forward'],0.)
        self.assertEqual(self.runtime.set_movement_mode('GROUND')['error'],'TAXI_IN_PROGRESS')
        self.runtime.save_state();self.runtime.load_state();self.publish();self.assertEqual(self.ui.evaluate('return UnitOnTaxi("player")'),[1])
        with self.runtime._lock:self.runtime._tick_travel_locked(duration)
        self.publish();self.assertIsNone(self.runtime._services['taxi_flight']);self.assertEqual(self.ui.evaluate('return UnitOnTaxi("player")'),[None])
        end=self.runtime._lifecycle_position_locked();self.assertEqual((end['x'],end['z']),(node['x'],node['z']));self.assertEqual(self.runtime._movement_mode,'GROUND')
        self.assertEqual(self.view()['money'],money-node['cost']);self.assertEqual(self.service('TaxiArrive')['error'],'TAXI_NOT_AT_DESTINATION')
        self.runtime.load_state();self.assertEqual(end,self.runtime._lifecycle_position_locked())
        self.publish();self.assertEqual(self.ui.evaluate('return table.concat(controlEvents,",")'),['PLAYER_CONTROL_LOST,PLAYER_CONTROL_GAINED'])

    def test_failed_departure_keeps_wallet_position_and_map_and_far_provider_blocks(self):
        index,node=self.open_route();before=copy.deepcopy((self.runtime._services,self.runtime._economy_state,self.runtime._input,self.runtime._lifecycle_position_locked()))
        with patch.object(self.runtime._state_store,'save',side_effect=OSError('disk full')):
            self.assertEqual(self.service('TaxiTake',destination=node['id'])['error'],'SERVICE_SAVE_FAILED')
        current=copy.deepcopy(self.runtime._services);current['clock']=before[0]['clock']
        self.assertEqual(before,(current,self.runtime._economy_state,self.runtime._input,self.runtime._lifecycle_position_locked()));self.assertTrue(self.view()['travel']['open'])
        with self.runtime._lock:self.runtime._x[0]+=50
        self.assertEqual(self.service('TaxiTake',destination=node['id'])['error'],'TAXI_MAP_CLOSED')
        self.assertEqual(before[1],self.runtime._economy_state)

    def test_original_summon_requires_offer_group_and_expiry_and_no_duplicate_teleport(self):
        person=self.move_near_npc();self.assertEqual(self.service('SummonOffer',target=person)['error'],'SUMMON_GROUP_MEMBER_REQUIRED')
        self.service('GroupInvite',target=person);self.service('SummonOffer',target=person);self.publish()
        self.assertEqual(self.ui.evaluate('return GetSummonConfirmSummoner()'),[self.runtime._service_unit_locked(person)['name']])
        with self.runtime._lock:self.runtime._x[0]+=100
        self.call('ConfirmSummon()');point=self.runtime._lifecycle_position_locked();index=self.runtime._npc_index_for_id_locked(person)
        self.assertAlmostEqual(point['x'],self.runtime._x[index]+1)
        self.assertEqual(self.service('SummonConfirm')['error'],'SUMMON_OFFER_EXPIRED');self.assertEqual(point,self.runtime._lifecycle_position_locked())
        self.service('SummonOffer',target=person);self.runtime._service_windows['summon']['expires']=0.
        self.assertEqual(self.service('SummonConfirm')['error'],'SUMMON_OFFER_EXPIRED')

    def test_original_stuck_cast_is_delayed_cancelable_and_has_persisted_cooldown(self):
        self.move_near_npc();start=self.runtime._lifecycle_position_locked();self.call('Stuck()')
        self.assertIsNotNone(self.runtime._services['stuck_cast']);self.assertEqual(start,self.runtime._lifecycle_position_locked())
        self.call('SpellStopCasting()');self.assertIsNone(self.runtime._services['stuck_cast']);self.call('Stuck()')
        with self.runtime._lock:self.runtime._x[0]+=2;self.runtime._tick_travel_locked(.1)
        self.assertIsNone(self.runtime._services['stuck_cast']);self.call('Stuck()')
        with self.runtime._lock:self.runtime._tick_travel_locked(9)
        self.assertIsNotNone(self.runtime._services['stuck_cast'])
        with self.runtime._lock:self.runtime._tick_travel_locked(1)
        self.assertEqual(self.runtime._x[0],0.);self.assertEqual(self.runtime._z[0],0.)
        self.assertEqual(self.service('StuckStart')['error'],'STUCK_RECOVERY_COOLDOWN');self.runtime.load_state()
        self.assertEqual(self.service('StuckStart')['error'],'STUCK_RECOVERY_COOLDOWN')

    def test_one_companion_is_suspended_on_flight_and_ghost_and_restored_without_healing(self):
        from test_game_engine_adapter_social import Social
        from test_game_engine_adapter_lifecycle import Lifecycle
        pet=Social.tame(self);number=pet['number'];actor_id='pet:'+str(number)
        health=self.runtime._combat_state['actors'][actor_id]['max_health']*.5
        self.runtime._combat_state['actors'][actor_id]['health']=health
        index,node=self.open_route();self.call(f'TakeTaxiNode({index})')
        self.assertIsNone(self.runtime._active_pet_locked());self.assertEqual(len(self.runtime._services['pets']),1)
        self.runtime.save_state();self.runtime.load_state()
        with self.runtime._lock:self.runtime._tick_travel_locked(self.runtime._services['taxi_flight']['duration'])
        self.assertEqual(self.runtime._active_pet_locked()['number'],number);self.assertEqual(self.runtime._combat_state['actors'][actor_id]['health'],health)
        Lifecycle.die(self);self.call('RepopMe()');self.assertIsNone(self.runtime._active_pet_locked())
        self.assertEqual(self.service('PetAction',slot=3)['error'],'PLAYER_DEFEATED')
        with self.runtime._lock:
            death=self.runtime._services['death'];death['recover_at']=0.;self.runtime._lifecycle_move_locked(death['position'])
        self.call('RetrieveCorpse()');self.assertEqual(self.runtime._active_pet_locked()['number'],number)
        self.assertEqual(self.runtime._combat_state['actors'][actor_id]['health'],health);self.assertEqual(len(self.runtime._services['pets']),1)

if __name__=='__main__':unittest.main()
