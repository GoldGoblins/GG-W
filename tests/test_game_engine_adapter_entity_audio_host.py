"""Actual canonical identity and committed event forwarding, without portraits."""
from copy import deepcopy
import unittest
from backend.game_engine_adapter_entity_audio import EntityAudio,context

class Zone:
    def __init__(self):self.events=[];self.removed=[];self.moves=[];self.models=[]
    def entity_event(self,owner,event,c):self.events.append((owner,event,dict(c)));return True
    def release_model(self,owner):self.removed.append(owner)
    def update_entity(self,owner,position):self.moves.append((owner,position))
    def model_events(self,owner,events,c):self.models.append((owner,events,c));return True

class Stream:
    active=True
    def query(self,*at):return {'terrain_id':4,'ground_effect_id':None}
    def water_sample(self,*at):return {'height_m':.2,'body_kind':'STILL'}

def snapshot(sequence=1,events=None):
    return {'player':{'time_s':0.,'grounded':True,'vehicle':'NONE'},'combat_live':{'player':{'dead':False}},
        'render':{'entities':[
            {'id':'e-0000','kind':'PLAYER','x':0.,'y':0.,'z':0.,'asset':{'appearance':{'display_id':100}},'motion_state':'RUN','equipment':[{'slot':'CHEST','material':2}]},
            {'id':'e-0012','kind':'NPC','x':0.,'y':0.,'z':-2.,'asset':{'display_id':101,'foley_material':1,'collision_height':3.},'individual':{'id':'mira'},'motion_state':'IDLE'},
        ]},'event_journal':{'events':events or [{'sequence':sequence,'kind':'PLAY'}]}}

class EntityAudioHost(unittest.TestCase):
    def setUp(self):self.zone=Zone();self.now=0.;self.helper=EntityAudio(clock=lambda:self.now);self.addCleanup(self.helper.close)
    def update(self,s,**kw):self.helper.update(self.zone,s,Stream(),scope='character-one',**kw)
    def test_only_explicit_display_ids_claim_original_audio(self):
        s=snapshot();self.update(s);self.assertTrue(self.helper.player_claimed);self.assertEqual(len(self.helper.actors),2)
        s['render']['entities'][0]['asset']={};self.update(s);self.assertFalse(self.helper.player_claimed)
        self.assertIn('entity:player',self.zone.removed)
        for invalid in (None,True,0,-1,2**32):
            s['render']['entities'][0]['asset']={'display_id':invalid};self.assertIsNone(context(s,s['render']['entities'][0],Stream()))
    def test_actual_surface_and_equipped_material_feed_player_and_npc(self):
        s=snapshot();player=context(s,s['render']['entities'][0],Stream());npc=context(s,s['render']['entities'][1],Stream())
        self.assertEqual((player['terrain_id'],player['material_id'],player['water_depth']),(4,2,.2))
        self.assertEqual((npc['material_id'],npc['collision_height']),(1,3.))
    def test_canonical_lifecycle_ghost_and_alive_flags_are_respected(self):
        s=snapshot();s['player']['client_controls']={'services':{'lifecycle':{'ghost':True}}};s['combat_live']['player']['alive']=False
        self.assertTrue(context(s,s['render']['entities'][0],Stream())['ghost'])
        self.update(s);self.assertTrue(self.helper.actors['player']['dead'])
        self.assertFalse(any(o=='entity:player' for o,e,c in self.zone.events))
    def test_committed_combat_routes_canonical_identity_once_without_historical_replay(self):
        old={'sequence':1,'kind':'COMBAT_ATTACK','actor_id':'player','target_id':'mira','payload':{'damage':2}}
        s=snapshot(events=[old]);self.update(s);self.zone.events.clear()
        s['event_journal']['events'].append({**old,'sequence':2,'payload':{'damage':3,'critical':True}})
        self.update(s);self.update(s)
        self.assertEqual([(o,e) for o,e,c in self.zone.events],[('entity:player','exertion'),('entity:mira','injury')])
        self.assertTrue(all(c['critical'] for o,e,c in self.zone.events))
    def test_zero_damage_and_paused_transitions_do_not_produce_hits(self):
        s=snapshot();self.update(s);self.zone.events.clear()
        e={'sequence':2,'kind':'COMBAT_ATTACK','actor_id':'player','target_id':'mira','payload':{'damage':0}}
        s['event_journal']['events'].append(e);self.update(s);self.assertFalse(self.zone.events)
        s['event_journal']['events'].append({**e,'sequence':3,'payload':{'damage':5}});self.update(s,running=False);self.update(s)
        self.assertFalse(self.zone.events)
    def test_spell_damage_preserves_original_voices_without_a_weapon_swing(self):
        s=snapshot();s['render']['entities'][0]['asset']['swing_type']=0
        self.update(s);self.zone.events.clear()
        event={'sequence':2,'kind':'COMBAT_ATTACK','actor_id':'player','target_id':'mira','payload':{'kind':'SPELL','damage':5,'critical':True}}
        s['event_journal']['events'].append(event);self.update(s)
        self.assertEqual([(o,e) for o,e,c in self.zone.events],[('entity:player','exertion'),('entity:mira','injury')])
        self.assertTrue(all(c['critical'] for o,e,c in self.zone.events))
        self.zone.events.clear();s['event_journal']['events'].append({**event,'sequence':3,'payload':{'kind':'MELEE','damage':5}})
        self.update(s);self.assertEqual([e for o,e,c in self.zone.events],['exertion','swing','injury'])
    def test_removed_target_retains_only_bounded_final_death_context(self):
        s=snapshot();self.update(s);self.zone.events.clear();s['render']['entities']=s['render']['entities'][:1]
        s['event_journal']['events'].append({'sequence':2,'kind':'COMBAT_DEFEAT','actor_id':'player','target_id':'mira'})
        self.update(s);self.assertEqual([(o,e) for o,e,c in self.zone.events],[('entity:mira','death')])
        self.assertEqual(len(self.helper.retired),1);self.now=6.;self.update(s);self.assertFalse(self.helper.retired)
    def test_sequence_rollback_and_new_character_scope_retire_previous_owners(self):
        s=snapshot(sequence=100);self.update(s);self.zone.events.clear();s['event_journal']['events']=[{'sequence':1,'kind':'COMBAT_DEFEAT','target_id':'mira'}]
        self.update(s);self.assertFalse(self.zone.events)
        self.helper.update(self.zone,s,Stream(),scope='character-two');self.assertIn('entity:mira',self.zone.removed)
        self.assertEqual(self.helper.sequence,1)
    def test_movement_emits_actual_step_once_and_teleport_does_not(self):
        s=snapshot();self.update(s);self.zone.events.clear();s['player']['time_s']=.25;s['render']['entities'][0]['x']=1.5
        self.update(s);self.assertEqual([e for o,e,c in self.zone.events],['footstep'])
        s['player']['time_s']=.5;s['render']['entities'][0]['x']=50.;self.update(s);self.assertEqual(len(self.zone.events),1)
    def test_portrait_tags_are_never_world_footsteps_and_explicit_world_consumer_drains(self):
        s=snapshot();self.update(s);events={'keys':[{'tag':'$FSD','data':0,'position':[0,0,0]}]}
        self.assertFalse(self.helper.model_events({'id':3,'unit':'player'},events));self.assertFalse(self.zone.models)
        self.assertFalse(self.helper.model_events({'audio_world':True,'audio_actor_id':'player'},events));self.assertFalse(self.helper.actors['player']['model_driven'])
        self.assertTrue(self.helper.model_events({'audio_world':True,'audio_actor_id':'player','audio_world_space':True},events))
        self.assertEqual(len(self.zone.models),1);self.assertTrue(self.helper.actors['player']['model_driven'])
        self.helper.model_events({'audio_world':True,'audio_actor_id':'player'},None);self.assertFalse(self.helper.actors['player']['model_driven'])
    def test_actor_and_journal_bounds_are_enforced(self):
        s=snapshot();base=s['render']['entities'][1];s['render']['entities']=[{**deepcopy(base),'id':f'e-{i}','individual':{'id':f'person-{i}'}} for i in range(500)]
        self.update(s);self.assertEqual(len(self.helper.actors),128)
        s['render']['entities']=[];self.update(s);self.assertLessEqual(len(self.helper.retired),32)
    def test_model_changes_and_source_replacement_release_pending_actor_audio(self):
        s=snapshot();self.update(s);s['render']['entities'][0]['asset']['appearance']['display_id']=101;self.update(s)
        self.assertIn('entity:player',self.zone.removed)
        old=self.zone;self.zone=Zone();self.update(s);self.assertIn('entity:mira',old.removed)

if __name__=='__main__':unittest.main()
