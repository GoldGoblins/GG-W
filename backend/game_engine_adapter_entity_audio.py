"""Committed GG actors feed the existing original-catalog audio owner.

Only explicit imported display/model IDs carry original entity audio. Journal
sequences prevent polling replay. Portrait widgets never become world actors.
"""
from __future__ import annotations
import math,time

MAX_ACTORS=128

def ident(value):
    return value if type(value) is int and 0<value<=0xffffffff else None

def point(row):
    values=tuple(row.get(k) for k in ('x','y','z'))
    return values if all(type(v) in (int,float) and math.isfinite(v) and abs(v)<=2_000_000 for v in values) else None

def context(snapshot,row,stream=None):
    asset=row.get('asset')
    if not isinstance(asset,dict):return None
    appearance=asset.get('appearance') if isinstance(asset.get('appearance'),dict) else {}
    display=ident(appearance.get('display_id',asset.get('display_id')))
    if display is None:return None
    at=point(row)
    if at is None:return None
    raw_kind=str(row.get('kind','')).upper()
    kind='player' if raw_kind=='PLAYER' else 'gameobject' if raw_kind=='GAMEOBJECT' else 'creature' if raw_kind in ('NPC','PET','CREATURE','ACTOR') else asset.get('audio_kind')
    if kind not in ('player','creature','gameobject'):return None
    result={'kind':kind,'display_id':display,'position':at,'self_player':kind=='player'}
    for key in ('model_id','material_id','collision_height','swing_type','weapon_subclass','target_slot','metal'):
        value=appearance.get(key,asset.get(key))
        if value is not None:result[key]=value
    # The original model catalog exports the creature's foley material. A
    # player's material comes from the real equipped chest, never this field.
    if kind!='player' and 'material_id' not in result:
        material=appearance.get('foley_material',asset.get('foley_material'))
        if type(material) is int and 0<=material<=0xffffffff:result['material_id']=material
    if kind=='player':
        player=snapshot.get('player',{})
        death=player.get('client_controls',{}).get('services',{}).get('lifecycle',snapshot.get('death',{}))
        result.update(ghost=bool(death.get('ghost',player.get('ghost',False))),stealth=bool(player.get('stealth',False)),hover=bool(player.get('hover',False)),swimming=player.get('movement_mode')=='SWIM')
        for item in row.get('equipment',[])[:19]:
            if not isinstance(item,dict) or str(item.get('slot','')).upper() not in ('CHEST','CHESTSLOT'):continue
            material=item.get('material',item.get('Material'))
            if type(material) is int and 0<=material<=0xffffffff:result['material_id']=material
    if stream is not None and getattr(stream,'active',False):
        surface=stream.query(*at)
        for key in ('terrain_id','ground_effect_id'):
            value=surface.get(key)
            if type(value) is int and 0<=value<0xffffffff:result[key]=value
        water=stream.water_sample(*at)
        if water.get('body_kind') in ('STILL','WATER','RAPIDS','OCEAN'):
            depth=water.get('height_m')
            if type(depth) in (int,float) and math.isfinite(depth):result['water_depth']=max(0.,depth-at[1])
    return result

class EntityAudio:
    def __init__(self,*,clock=time.monotonic):
        self.clock=clock;self.zone=None;self.scope=None;self.actors={};self.retired={};self.aliases={};self.sequence=None;self.player_claimed=False;self.events=0;self.dropped=0
    def close(self):
        if self.zone:
            for actor in (*self.actors.values(),*self.retired.values()):self.zone.release_model(actor['owner'])
        self.actors.clear();self.retired.clear();self.aliases.clear();self.zone=None;self.scope=None;self.sequence=None;self.player_claimed=False
    def _emit(self,actor,event,**values):
        if self.zone.entity_event(actor['owner'],event,{**actor['context'],**values}):self.events+=1;return True
        return False
    def _actor(self,key):
        key=self.aliases.get(str(key),str(key))
        return self.actors.get(key) or self.retired.get(key)
    def update(self,zone,snapshot,stream=None,*,scope=None,running=True):
        if zone is not self.zone or scope!=self.scope:
            self.close();self.zone=zone;self.scope=scope
        if zone is None:self.player_claimed=False;return
        now=self.clock()
        for key in list(self.retired):
            if now>=self.retired[key]['expires']:zone.release_model(self.retired.pop(key)['owner'])
        rows=snapshot.get('render',{}).get('entities',[])
        if not isinstance(rows,list):rows=[]
        seen=set();aliases={};player=snapshot.get('player',{});time_s=player.get('time_s',0.)
        if type(time_s) not in (int,float) or not math.isfinite(time_s):time_s=0.
        for row in rows[:MAX_ACTORS]:
            if not isinstance(row,dict) or row.get('hidden'):continue
            c=context(snapshot,row,stream)
            if c is None:continue
            render_id=str(row.get('id',''))[:80]
            person=row.get('individual') if isinstance(row.get('individual'),dict) else {}
            key='player' if c['kind']=='player' else str(person.get('id') or row.get('actor_id') or row.get('npc_id') or render_id)[:80]
            if not key or key in seen:continue
            seen.add(key);aliases[render_id]=key;aliases[key]=key
            signature=(c['kind'],c['display_id'],c.get('model_id'))
            actor=self.actors.get(key)
            if actor and actor['signature']!=signature:
                zone.release_model(actor['owner']);self.actors.pop(key);actor=None
            state=str(row.get('motion_state',row.get('animation',{}).get('locomotion',''))).upper()
            combat_player=snapshot.get('combat_live',{}).get('player',{})
            dead=state in ('DEAD','DEATH','CORPSE') or key=='player' and (bool(combat_player.get('dead')) or combat_player.get('alive') is False)
            grounded=bool(player.get('grounded')) if key=='player' else state in ('WALK','WALKING','RUN','RUNNING','IDLE','STAND')
            if actor is None:
                if key in self.retired:zone.release_model(self.retired.pop(key)['owner'])
                actor={'owner':'entity:'+key,'context':c,'signature':signature,'at':c['position'],'time':time_s,'distance':0.,'grounded':grounded,'dead':dead,'model_driven':False}
                self.actors[key]=actor
                if running and not dead:self._emit(actor,'body_loop')
            else:
                previous=actor['at'];dt=time_s-actor['time'];distance=math.hypot(c['position'][0]-previous[0],c['position'][2]-previous[2]);actor['context']=c
                if running and not dead:
                    if dead!=actor['dead']:self._emit(actor,'body_loop')
                    if not actor['model_driven'] and grounded and (key!='player' or str(player.get('vehicle','NONE'))=='NONE') and 0<dt<=.5 and distance<5:
                        actor['distance']+=distance
                        if actor['distance']>=1.4:
                            actor['distance']=math.fmod(actor['distance'],1.4);self._emit(actor,'footstep')
                    elif not grounded or distance>=5 or not 0<dt<=.5:actor['distance']=0.
                    # Own GG physics provides the jump transition. Animation
                    # driven actors use their original tagged event stream.
                    if not actor['model_driven'] and key=='player' and actor['grounded'] and not grounded and player.get('movement_mode') in ('JUMP','JUMPING'):
                        self._emit(actor,'jump_start')
                    elif not actor['model_driven'] and grounded and not actor['grounded']:self._emit(actor,'jump_end')
                actor.update(at=c['position'],time=time_s,grounded=grounded,dead=dead)
            zone.update_entity(actor['owner'],c['position'])
        for key in set(self.actors)-seen:
            actor=self.actors.pop(key);zone.release_model(actor['owner']);actor['expires']=now+5.;self.retired[key]=actor
        while len(self.retired)>32:
            key=next(iter(self.retired));zone.release_model(self.retired.pop(key)['owner'])
        self.aliases=aliases;self.player_claimed='player' in self.actors
        journal=snapshot.get('event_journal',{}).get('events',[])
        if not isinstance(journal,list):return
        journal=sorted((e for e in journal[-256:] if isinstance(e,dict) and type(e.get('sequence')) is int),key=lambda e:e['sequence'])
        latest=max((e['sequence'] for e in journal),default=self.sequence or 0)
        if self.sequence is None or latest<self.sequence or not running:self.sequence=latest;return
        pending=[e for e in journal if e['sequence']>self.sequence]
        self.sequence=latest
        if len(pending)>64:self.dropped+=len(pending)-64;pending=pending[-64:]
        for event in pending:self._journal(event)
    def _journal(self,event):
        kind=event.get('kind');actor=self._actor(event.get('actor_id'));target=self._actor(event.get('target_id'));payload=event.get('payload',{})
        if not isinstance(payload,dict):payload={}
        critical=payload.get('critical') is True;crushing=payload.get('crushing') is True
        if kind in ('COMBAT_ATTACK','NPC_COMBAT_ATTACK','PET_ATTACK','GROUP_ATTACK','PET_HIT','GROUP_HIT'):
            damage=payload.get('damage')
            if type(damage) not in (int,float) or not math.isfinite(damage) or damage<=0:return
            if actor:
                self._emit(actor,'exertion',critical=critical)
                if payload.get('kind')!='SPELL' and 'swing_type' in actor['context']:self._emit(actor,'swing',critical=critical)
            if target:self._emit(target,'injury',critical=critical,crushing=crushing)
        elif kind in ('COMBAT_DEFEAT','NPC_COMBAT_DEFEAT') and target:self._emit(target,'death')
        elif kind in ('NPC_AGGRO','AI_HOSTILE') and actor:self._emit(actor,'aggro')
        elif kind=='AI_ALERT' and actor:self._emit(actor,'alert')
        elif kind in ('GAMEOBJECT_OPEN','GAMEOBJECT_CLOSE','GAMEOBJECT_DESTROY') and (target or actor):self._emit(target or actor,kind.removeprefix('GAMEOBJECT_').lower())
        elif kind in ('PET_ORDER','PET_DISMISS','PET_ATTACK_ORDER') and actor:self._emit(actor,{'PET_ORDER':'pet_order','PET_DISMISS':'pet_dismiss','PET_ATTACK_ORDER':'pet_attack'}[kind])
    def model_events(self,row,events):
        """Explicit world consumer; portrait/unit preview rows cannot opt in."""
        if not self.zone or not isinstance(row,dict) or row.get('audio_world') is not True:return False
        actor=self._actor(row.get('audio_actor_id'))
        if actor is None:return False
        if events is None:self.zone.release_model(actor['owner']);actor['model_driven']=False;return True
        if not isinstance(events,dict):return False
        keys=events.get('keys',[])
        if not isinstance(keys,list) or len(keys)>64:return False
        # World pose keys are already in world space. A future local-space
        # renderer must transform them before calling this explicit hook.
        if row.get('audio_world_space') is not True:return False
        actor['model_driven']=True
        return self.zone.model_events(actor['owner'],events,actor['context'])
    def diagnostics(self):
        return {'actors':len(self.actors),'retired_actors':len(self.retired),'events':self.events,'dropped_journal_events':self.dropped,'sequence':self.sequence,'player_claimed':self.player_claimed,
                'limitations':['Own GG movement cadence is used without an actual world M2 tagged event consumer','Complete original voice, spell, vehicle and pet event graphs remain partial']}
