"""Private map boundaries preserve real custody and survive durable reloads."""
import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import game_engine_combat as combat, game_engine_items as items
from backend import game_engine_mmo as mmo, game_engine_character_creation as appearance
from backend.game_engine_adapter_private_world import _world_shape
from backend.game_engine_local_characters import CharacterStore


class PrivateWorld(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);root=Path(temp.name)
        environment={'XDG_'+key+'_HOME':str(root/key.lower()) for key in ('STATE','CONFIG','CACHE','DATA')}
        for context in (patch.dict(os.environ,environment),patch.object(mmo,'DEFAULT_STASH_PATH',root/'stash.json'),patch.object(appearance,'STATE_PATH',root/'appearance.json')):
            context.start();self.addCleanup(context.stop)
        from backend.game_engine_host import GameEngineRuntime
        self.runtime=GameEngineRuntime()
        self.addCleanup(self.runtime.shutdown)
        self.state_path=root/'characters'
        self.runtime._state_store=CharacterStore(self.state_path)
        self.runtime._persistence_key='0'*32
        self.runtime._ensure_combat_actors_locked()

    def command(self,op,**fields):
        with self.runtime._lock:return self.runtime._service_command_locked(dict(op=op,**fields))

    def entrance(self,offset=0):
        place=list(self.runtime._expedition_places_locked().values())[offset]
        x,z=place['x']+40.,place['z']
        self.runtime._lifecycle_move_locked(dict(x=x,y=self.runtime._ground_contact_height_locked(x,z),z=z))
        return place

    def enter(self,offset=0):
        place=self.entrance(offset);self.command('InstanceEnter',ref=place['id']);return place

    def encounter(self):
        record=self.runtime._expedition_record_locked()
        return next(iter(record['world']['people']))

    def kill(self):
        owner=self.encounter();index=self.runtime._instance_npc_index_locked(owner)
        actor=self.runtime._combat_state['actors'][owner];actor['health']=1.
        result=combat.resolve_attack(self.runtime._combat_state,attacker_id='player',defender_id=owner,
            attacker_profile=self.runtime._player_combat_profile_locked(),defender_profile=self.runtime._npc_combat_profile_locked(owner),sim_time=self.runtime._sim_time+10)
        self.assertTrue(result.get('defeated'));self.runtime._handle_npc_defeat_locked(owner,index,result)
        self.command('InstanceEncounter',target=owner)
        return owner,next(row for row in self.runtime._item_instances.values() if row.get('source_actor_id')==owner and row.get('location')=='GROUND')

    def test_real_private_map_hides_original_npcs_ground_and_direct_pickup(self):
        original_indices=list(self.runtime._npc_indices)
        original_items=[row for row in self.runtime._item_instances.values() if row['location']=='GROUND']
        before=copy.deepcopy(self.runtime._item_instances)
        self.enter()
        self.assertTrue(self.runtime._instance_private_locked())
        descriptor=self.runtime._instance_map_descriptor_locked()
        self.assertGreater(descriptor['instance_id'],0);self.assertEqual(descriptor['kind'],'INSTANCE')
        self.assertEqual(len(self.runtime._npc_indices),1)
        for row in original_items:
            self.assertFalse(self.runtime._instance_item_visible_locked(row))
            self.assertIsNone(self.runtime._nearest_item_locked(row['instance_id'])[0])
        for index in set(original_indices)-set(self.runtime._npc_indices):
            self.assertTrue(self.runtime._alive[index]);self.assertNotIn(index,self.runtime._active_entity_indices)
        self.command('InstanceExit')
        self.assertFalse(self.runtime._instance_private_locked())
        self.assertEqual(self.runtime._npc_indices,original_indices)
        self.assertEqual(self.runtime._item_instances,before)
        self.assertTrue(all(self.runtime._instance_item_visible_locked(row) for row in original_items))

    def test_private_kill_does_not_defeat_or_mutate_original_resident_and_custody_crosses_once(self):
        original_actor=copy.deepcopy(self.runtime._combat_state['actors']['npc-guardian-01'])
        original_person=copy.deepcopy(self.runtime._individual_state['individuals']['npc-guardian-01'])
        self.enter();owner,drop=self.kill();key=drop['instance_id']
        self.assertTrue(self.runtime._instance_item_visible_locked(drop))
        ok,_=self.runtime._move_item_locked(drop,'INVENTORY',owner_id='player');self.assertTrue(ok)
        acquired=copy.deepcopy(drop);registry=set(self.runtime._item_instances)
        self.command('InstanceExit')
        self.assertEqual(self.runtime._combat_state['actors'][owner],original_actor)
        self.assertEqual(self.runtime._individual_state['individuals'][owner],original_person)
        self.assertEqual(self.runtime._item_instances[key],acquired)
        self.assertEqual(set(self.runtime._item_instances),registry)
        self.command('InstanceReset')
        self.assertEqual(self.runtime._item_instances[key],acquired)
        self.assertEqual(set(self.runtime._item_instances),registry)

    def test_private_encounter_and_unclaimed_drop_resume_on_fresh_runtime_and_restore_originals(self):
        place=self.enter();owner,drop=self.kill();key=drop['instance_id'];map_id=self.runtime._instance_map_descriptor_locked()['id']
        self.runtime.save_state(snapshot=False)
        from backend.game_engine_host import GameEngineRuntime
        fresh=GameEngineRuntime();self.addCleanup(fresh.shutdown);fresh._state_store=CharacterStore(self.state_path);fresh._persistence_key='0'*32;self.runtime=fresh
        result=fresh.load_state();self.assertIsNone(result.get('error'))
        self.assertTrue(fresh._instance_private_locked());self.assertEqual(len(fresh._npc_indices),1)
        self.assertEqual(fresh._instance_map_descriptor_locked()['id'],map_id)
        self.assertFalse(fresh._combat_state['actors'][owner]['alive'])
        self.assertTrue(fresh._instance_item_visible_locked(fresh._item_instances[key]))
        self.command('InstanceExit')
        self.assertTrue(fresh._combat_state['actors'][owner]['alive'])
        self.assertFalse(fresh._instance_item_visible_locked(fresh._item_instances[key]))
        self.entrance();self.command('InstanceEnter',ref=place['id'])
        self.assertFalse(fresh._combat_state['actors'][owner]['alive'])
        self.assertTrue(fresh._instance_item_visible_locked(fresh._item_instances[key]))

    def test_two_maps_have_independent_encounters_and_drop_visibility(self):
        place=self.enter(0);owner,drop=self.kill();first=copy.deepcopy(self.runtime._instance_map_descriptor_locked())
        self.command('InstanceExit');second_place=self.enter(1)
        second=self.runtime._instance_map_descriptor_locked()
        self.assertNotEqual(first['id'],second['id']);self.assertNotEqual(first['instance_id'],second['instance_id'])
        self.assertTrue(self.runtime._combat_state['actors'][owner]['alive'])
        self.assertFalse(self.runtime._instance_item_visible_locked(drop))
        self.command('InstanceExit');self.entrance(0);self.command('InstanceEnter',ref=place['id'])
        self.assertFalse(self.runtime._combat_state['actors'][owner]['alive'])
        self.assertTrue(self.runtime._instance_item_visible_locked(drop))

    def test_actual_companion_transfers_without_heal_and_returns_to_original_position(self):
        place=self.entrance();owner='npc-wanderer-01';index=self.runtime._npc_index_for_id_locked(owner)
        self.runtime._x[index]=self.runtime._x[0]+1.;self.runtime._y[index]=self.runtime._y[0];self.runtime._z[index]=self.runtime._z[0]
        self.command('GroupInvite',target=owner)
        origin=(self.runtime._x[index],self.runtime._y[index],self.runtime._z[index])
        self.runtime._combat_state['actors'][owner]['health']=17.
        self.command('InstanceEnter',ref=place['id'])
        self.assertIn(owner,[self.runtime._npc_ids[i] for i in self.runtime._npc_indices])
        self.assertEqual(self.runtime._combat_state['actors'][owner]['health'],17.)
        self.runtime._combat_state['actors'][owner]['health']=9.
        self.command('InstanceExit')
        self.assertEqual(self.runtime._combat_state['actors'][owner]['health'],9.)
        self.assertEqual((self.runtime._x[index],self.runtime._y[index],self.runtime._z[index]),origin)
        self.assertEqual(self.runtime._services['group']['members'],[owner])

    def test_failed_enter_save_restores_exact_pool_actors_custody_and_lockout(self):
        place=self.entrance()
        attrs=('_npc_indices','_active_entity_indices','_x','_y','_z','_combat_state','_individual_state','_faction_state','_services','_item_instances')
        before={key:copy.deepcopy(getattr(self.runtime,key)) for key in attrs}
        with patch.object(self.runtime,'save_state',side_effect=OSError('disk full')):
            with self.assertRaisesRegex(ValueError,'SERVICE_SAVE_FAILED'):self.command('InstanceEnter',ref=place['id'])
        self.assertTrue(all(getattr(self.runtime,key)==value for key,value in before.items()),'failed enter changed canonical world state')
        self.command('InstanceEnter',ref=place['id']);self.assertTrue(self.runtime._instance_private_locked())

    def test_failed_exit_save_restores_private_context_then_retries(self):
        self.enter();self.kill()
        attrs=('_npc_indices','_active_entity_indices','_x','_y','_z','_combat_state','_individual_state','_services','_item_instances')
        before={key:copy.deepcopy(getattr(self.runtime,key)) for key in attrs}
        with patch.object(self.runtime,'save_state',side_effect=OSError('disk full')):
            with self.assertRaisesRegex(ValueError,'SERVICE_SAVE_FAILED'):self.command('InstanceExit')
        self.assertTrue(all(getattr(self.runtime,key)==value for key,value in before.items()),'failed exit changed canonical world state')
        self.command('InstanceExit');self.assertFalse(self.runtime._instance_private_locked())

    def test_reset_only_destroys_this_map_unclaimed_ground_and_overworld_position_does_not_occupy_it(self):
        place=self.enter();owner,drop=self.kill();original_ground=next(row for row in self.runtime._item_instances.values()
            if row['location']=='GROUND' and self.runtime._services['instance_sessions']['item_maps'].get(row['instance_id'])==0)
        untouched=copy.deepcopy(original_ground);self.command('InstanceExit')
        self.runtime._x[0]=place['x'];self.runtime._z[0]=place['z']
        self.command('InstanceReset',ref=place['id'])
        self.assertEqual(drop['location'],'DESTROYED');self.assertEqual(original_ground,untouched)
        self.assertTrue(self.runtime._combat_state['actors'][owner]['alive'])

    def test_owned_ground_left_in_private_map_prevents_reset_then_can_be_recovered(self):
        place=self.enter();owner,drop=self.kill()
        self.assertTrue(self.runtime._move_item_locked(drop,'INVENTORY',owner_id='player')[0])
        self.assertTrue(self.runtime._move_item_locked(drop,'GROUND',owner_id='',position=self.runtime._lifecycle_position_locked())[0])
        self.command('InstanceExit')
        with self.assertRaisesRegex(ValueError,'INSTANCE_OWNED_ITEMS_LEFT_BEHIND'):self.command('InstanceReset')
        self.entrance();self.command('InstanceEnter',ref=place['id'])
        drop=self.runtime._item_instances[drop['instance_id']]
        self.assertTrue(self.runtime._instance_item_visible_locked(drop))
        self.assertTrue(self.runtime._move_item_locked(drop,'INVENTORY',owner_id='player')[0])
        self.command('InstanceExit');self.command('InstanceReset')
        self.assertEqual(self.runtime._item_instances[drop['instance_id']]['location'],'INVENTORY')

    def test_copy_of_encounter_cannot_sell_original_residents_equipment(self):
        self.enter();owner=self.encounter();index=self.runtime._instance_npc_index_locked(owner)
        self.runtime._x[0]=self.runtime._x[index]+1.;self.runtime._y[0]=self.runtime._y[index];self.runtime._z[0]=self.runtime._z[index]
        before=copy.deepcopy(self.runtime._item_instances)
        with self.assertRaisesRegex(ValueError,'INSTANCE_ENCOUNTER_SERVICE_UNAVAILABLE'):self.command('TradeOpen',target=owner)
        self.assertEqual(self.runtime._item_instances,before)

    def test_invalid_saved_private_world_rejected_with_bounded_validation(self):
        self.enter();world=copy.deepcopy(self.runtime._expedition_record_locked()['world'])
        owner=next(iter(world['npcs']))
        world['npcs'][owner]['_x']=float('nan')
        with self.assertRaisesRegex(ValueError,'INSTANCE_NPC_POSITION_INVALID'):_world_shape(world)
        world=copy.deepcopy(self.runtime._expedition_record_locked()['world']);world['actors'].clear()
        with self.assertRaisesRegex(ValueError,'INSTANCE_ACTOR_REGISTRY_INVALID'):_world_shape(world)

    def test_private_death_releases_at_portal_and_corpse_recovery_needs_the_same_map(self):
        place=self.enter();record=self.runtime._expedition_record_locked();instance_id=record['id']
        self.runtime._x[0]=place['x']+6.;self.runtime._z[0]=place['z']
        actor=self.runtime._combat_state['actors']['player'];actor.update(alive=False,health=0.,engaged_target='')
        self.command('DeathEnter');death=copy.deepcopy(self.runtime._services['death'])
        self.assertEqual(death['instance_id'],instance_id)
        self.command('DeathRepop')
        self.assertTrue(self.runtime._instance_private_locked());self.assertTrue(self.runtime._is_ghost_locked())
        self.assertAlmostEqual(self.runtime._x[0],place['x']+18.)
        self.runtime._services['clock']=death['recover_at']+1.
        self.command('InstanceExit');self.assertFalse(self.runtime._instance_private_locked())
        self.runtime._lifecycle_move_locked(death['position'])
        with self.assertRaisesRegex(ValueError,'CORPSE_IN_ANOTHER_MAP'):self.command('DeathRetrieveCorpse')
        self.assertFalse(any(row['id']=='corpse-player' for row in self.runtime.render_snapshot()['render']['entities']))
        self.entrance();self.command('InstanceEnter',ref=place['id'])
        self.runtime._lifecycle_move_locked(death['position'])
        self.command('DeathRetrieveCorpse')
        self.assertTrue(self.runtime._combat_state['actors']['player']['alive']);self.assertIsNone(self.runtime._services['death'])
        self.command('InstanceExit')

    def test_ghost_cannot_open_unowned_private_map_and_resumes_own_corpse_after_reload(self):
        place=self.enter();actor=self.runtime._combat_state['actors']['player'];actor.update(alive=False,health=0.,engaged_target='')
        self.command('DeathEnter');self.command('DeathRepop');self.command('InstanceExit')
        self.runtime.save_state(snapshot=False);self.runtime.load_state()
        another=self.entrance(1)
        with self.assertRaisesRegex(ValueError,'CORPSE_INSTANCE_REQUIRED'):self.command('InstanceEnter',ref=another['id'])
        self.entrance();self.command('InstanceEnter',ref=place['id'])
        self.assertTrue(self.runtime._is_ghost_locked());self.assertTrue(self.runtime._instance_private_locked())

    def test_cross_map_taxi_stuck_arena_and_exploration_cannot_bypass_private_exit(self):
        self.enter();before=copy.deepcopy(self.runtime._services['instance_sessions'])
        for op,fields in (('TaxiOpen',dict(target=self.encounter())),('StuckStart',{}),('BattlefieldJoin',dict(map=0x4701,instance=1,as_group=False))):
            with self.subTest(op=op),self.assertRaisesRegex(ValueError,'INSTANCE_EXIT_REQUIRED'):self.command(op,**fields)
        result=self.runtime.explore_region('LAND')
        self.assertEqual(result.get('error'),'INSTANCE_EXIT_REQUIRED')
        self.assertEqual(self.runtime._services['instance_sessions'],before)


if __name__=='__main__':unittest.main()
