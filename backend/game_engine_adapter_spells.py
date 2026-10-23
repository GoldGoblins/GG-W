"""Local authoritative cast/channel/stance lifecycle for GG ability definitions.

The retained original Lua bar reads this lifecycle. All effects use the host's
existing combat actors, resource, cooldowns, defeat rewards and particles.
Definitions are GG-authored; this is not an invented original Spell.dbc corpus.
"""
from __future__ import annotations
import copy
import math
from backend import game_engine_combat as combat
from backend import game_engine_factions as factions,game_engine_npc_identity as identity


def authored_abilities():
    return {
        'ability.island_spark': dict(id='ability.island_spark', name='Island Spark', kind='SPELL',
            description='Cast a spark at a hostile target.', cast_time_s=1.5, range_m=24.,
            cooldown_s=2., resource_cost=14., target='hostile', required_level=1,
            effect=dict(damage=28., particle_burst=18)),
        'ability.tide_mend': dict(id='ability.tide_mend', name='Tide Mend', kind='SPELL',
            description='Channel three healing pulses. Movement interrupts the channel.',
            channel_time_s=3., channel_ticks=3, range_m=20., cooldown_s=6.,
            resource_cost=24., target='self', required_level=1,
            effect=dict(heal=16., particle_burst=10)),
        'ability.watch_ward': dict(id='ability.watch_ward', name='Watch Ward', kind='SPELL',
            description='Absorb up to 40 damage for eight seconds.', range_m=0.,
            cooldown_s=12., resource_cost=18., target='self', required_level=1,
            effect=dict(status='ward', amount=40., duration_s=8., particle_burst=8)),
        'ability.reef_guard': dict(id='ability.reef_guard', name='Reef Guard', kind='FORM',
            description='A defensive stance granting 20 armor. Activate again to cancel.',
            range_m=0., cooldown_s=1., resource_cost=8., target='self', required_level=1,
            effect=dict(armor_bonus=20., particle_burst=8)),
    }


def number(row, key, low=0., high=100000., default=0.):
    value=row.get(key, default)
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not low<=value<=high:
        raise ValueError('SPELL_DEFINITION_INVALID')
    return float(value)


class SpellsMixin:
    def _reset_spells_locked(self):
        epoch=getattr(self,'_spell_state',{}).get('epoch',0)+1
        self._spell_state=dict(epoch=epoch, serial=0, events=[], pending=None, targeting=None,
                               form=None, gcd_until=0., last_result={})

    def _spell_event_locked(self, name, *args):
        state=self._spell_state;state['serial']+=1
        state['events']=(state['events']+[dict(id=state['serial'],event=name,args=list(args))])[-32:]

    def _cancel_spell_locked(self, reason='INTERRUPTED'):
        state=self._spell_state;pending=state.get('pending')
        state['targeting']=None
        if not pending:return []
        self._spell_presentation_stage_locked(pending['ref'],pending['definition'],'STOP',pending['target'])
        state['pending']=None
        event='SPELLCAST_CHANNEL_STOP' if pending['channel'] else 'SPELLCAST_INTERRUPTED'
        self._spell_event_locked(event)
        state['last_result']=dict(ok=False,status=reason,ability_id=pending['ref'])
        self._append_event_locked('SPELL_INTERRUPT',pending['name']+': '+reason)
        return [dict(event=event,args=[])]

    def _spell_presentation_stage_locked(self,ref,ability,stage,target):
        visual=ability.get('original_visual')
        if not isinstance(visual,dict):return
        actor='player' if stage!='impact' else target
        index=0 if actor=='player' else self._npc_index_for_id_locked(actor)
        if index is None:return
        kit_id=visual.get(stage,0);kit=visual.get('kits',{}).get(str(kit_id),{})
        self._append_event_locked('SPELL_VISUAL_STAGE',ability['name']+': '+stage,actor_id=actor,subject_id=ref,
            target_id=target,payload=dict(stage=stage,spell_id=ability['original_spell_id'],kit_id=kit_id,
                sound_id=kit.get('sound_id'),position=[self._x[index],self._y[index],self._z[index]]))

    def _spell_definition_locked(self, ref):
        ability=self._content.get('abilities',{}).get(ref)
        if not isinstance(ability,dict) or ability.get('kind') not in ('SPELL','FORM'):
            raise ValueError('CONTENT_ABILITY_NOT_FOUND')
        if not isinstance(ability.get('name'),str) or not ability['name'] or len(ability['name'])>96:
            raise ValueError('SPELL_DEFINITION_INVALID')
        for key,limit in (('resource_cost',100),('cooldown_s',300),('range_m',100),('cast_time_s',30),('channel_time_s',30)):
            number(ability,key,high=limit)
        if number(ability,'cast_time_s',high=30) and number(ability,'channel_time_s',high=30):
            raise ValueError('SPELL_DEFINITION_INVALID')
        level=ability.get('required_level',1)
        if type(level) is not int or not 1<=level<=60:raise ValueError('SPELL_DEFINITION_INVALID')
        if self._progression.get('level',1)<level:raise ValueError('SPELL_LEVEL_REQUIRED')
        for key,selection in (('classes','class_id'),('races','race_id')):
            allowed=ability.get(key)
            if allowed is not None:
                if not isinstance(allowed,list) or not 1<=len(allowed)<=32 or any(not isinstance(v,str) or len(v)>64 for v in allowed):
                    raise ValueError('SPELL_DEFINITION_INVALID')
                if (self._character_creation or {}).get(selection,self._progression.get(selection)) not in allowed:
                    raise ValueError('SPELL_'+key.upper()+'_REQUIRED')
        effect=ability.get('effect')
        if not isinstance(effect,dict):raise ValueError('SPELL_DEFINITION_INVALID')
        for key in ('damage','heal','amount','armor_bonus'):number(effect,key)
        number(effect,'duration_s',high=15)
        number(effect,'particle_burst',high=96)
        if 'status' in effect and effect['status'] not in ('ward','regen','burn','poison','slow','snare','weaken','attack_slow'):
            raise ValueError('SPELL_DEFINITION_INVALID')
        if effect.get('status') in ('slow','weaken','attack_slow') and number(effect,'amount')>.8:
            raise ValueError('SPELL_DEFINITION_INVALID')
        target=ability.get('target','self')
        if target not in ('self','hostile','friendly'):raise ValueError('SPELL_DEFINITION_INVALID')
        if effect.get('damage') and target!='hostile':raise ValueError('SPELL_DEFINITION_INVALID')
        if ability.get('channel_time_s'):
            ticks=ability.get('channel_ticks',3)
            if type(ticks) is not int or not 1<=ticks<=30:raise ValueError('SPELL_DEFINITION_INVALID')
        return ability

    def _spell_target_locked(self, ability, target=None):
        target='player' if ability.get('target','self')=='self' else (target or self._combat_target_id)
        if not target:return None
        self._ensure_combat_actors_locked()
        actor=self._combat_state['actors'].get(target)
        if not actor or not actor.get('alive'):raise ValueError('SPELL_TARGET_INVALID')
        index=0 if target=='player' else self._npc_index_for_id_locked(target)
        if index is None:raise ValueError('SPELL_TARGET_INVALID')
        # Use the same faction/party eligibility as original target and inspect getters.
        # The real player already passed the actor/alive checks above. Its
        # self/friendly eligibility requires no world roster or sight rays.
        unit=next((r for r in self._legacy_units_locked() if r['id']==target),None) if target!='player' else None
        policy=ability.get('target','self')
        if policy=='hostile' and (target=='player' or not unit or not unit.get('can_attack')):
            raise ValueError('SPELL_HOSTILE_TARGET_REQUIRED')
        if policy=='friendly' and target!='player' and (not unit or not unit.get('friend')):
            raise ValueError('SPELL_FRIENDLY_TARGET_REQUIRED')
        distance=math.sqrt(sum((values[index]-values[0])**2 for values in (self._x,self._y,self._z)))
        if distance>number(ability,'range_m',high=100)+.35:raise ValueError('SPELL_TARGET_OUT_OF_RANGE')
        if index and distance+.0001<number(ability,'min_range_m',high=100):raise ValueError('SPELL_TARGET_TOO_CLOSE')
        if index and not self._npc_line_of_sight_locked(index):raise ValueError('SPELL_TARGET_NOT_IN_SIGHT')
        return target

    def _spell_ready_locked(self, ref, ability):
        if not self._combat_state.get('actors',{}).get('player',{}).get('alive',True):raise ValueError('COMBAT_PLAYER_DEFEATED')
        if self._services.get('taxi_flight'):raise ValueError('TAXI_IN_PROGRESS')
        if self._spell_state['pending']:raise ValueError('SPELL_ALREADY_CASTING')
        if self._spell_state['gcd_until']>self._sim_time+1e-8:raise ValueError('SPELL_GLOBAL_COOLDOWN')
        if self._ability_cooldowns.get(ref,0)>0:raise ValueError('ABILITY_ON_COOLDOWN')
        if self._resource<number(ability,'resource_cost',high=100):raise ValueError('ABILITY_RESOURCE_MISSING')

    def _start_spell_locked(self, ref, target=None):
        if not hasattr(self,'_spell_state'):self._reset_spells_locked()
        try:
            ability=self._spell_definition_locked(ref)
            self._ensure_combat_actors_locked()
            # Original active-form clicks cancel before checking cast resource.
            if ability['kind']=='FORM' and self._spell_state['form']==ref:
                if not ability.get('silent_cancel',False):
                    self._spell_state['form']=None;self._spell_event_locked('UPDATE_SHAPESHIFT_FORM')
                    self._append_event_locked('SPELL_FORM','Defensive stance cancelled.')
                return True,dict(ability_id=ref,status='FORM_ACTIVE' if ability.get('silent_cancel',False) else 'FORM_CANCELLED')
            self._spell_ready_locked(ref,ability)
            selected=self._spell_target_locked(ability,target)
            if selected is None:
                self._spell_state['targeting']=ref
                return True,dict(ability_id=ref,status='TARGETING')
            self._spell_state['targeting']=None
            cast=number(ability,'cast_time_s',high=30);channel=number(ability,'channel_time_s',high=30)
            if cast or channel:
                if self._spell_moving_locked():raise ValueError('SPELL_CANNOT_CAST_WHILE_MOVING')
                actor=self._combat_state['actors']['player'];now=self._sim_time
                pending=dict(ref=ref,name=ability['name'],target=selected,definition=copy.deepcopy(ability),
                    start=now,end=now+max(cast,channel),duration=max(cast,channel),channel=bool(channel),
                    ticks_done=0,ticks=ability.get('channel_ticks',3),position=[self._x[0],self._y[0],self._z[0]],
                    health=actor['health'],pushbacks=0)
                self._spell_state['pending']=pending
                if channel:
                    self._spell_commit_cost_locked(ref,ability)
                    self._spell_event_locked('SPELLCAST_CHANNEL_START',round(channel*1000),ability['name'])
                else:self._spell_event_locked('SPELLCAST_START',ability['name'],round(cast*1000))
                self._start_character_action_locked('player','Cast')
                self._spell_presentation_stage_locked(ref,ability,'channel' if channel else 'precast',selected)
                result=dict(ability_id=ref,status='CHANNELING' if channel else 'CASTING',remaining_s=max(cast,channel))
            else:
                self._spell_commit_cost_locked(ref,ability)
                result=self._spell_apply_locked(ref,ability,selected)
                self._spell_event_locked('SPELLCAST_STOP')
            self._spell_state['last_result']=result
            return True,result
        except (ValueError,TypeError,OverflowError) as exc:
            error=str(exc) if isinstance(exc,ValueError) else 'SPELL_DEFINITION_INVALID'
            self._spell_state['last_result']=dict(ok=False,error=error,ability_id=ref)
            return False,dict(error=error,ability_id=ref)

    def _spell_moving_locked(self):
        return (self._legacy_autorun or bool(self._legacy_held&{'MoveForward','MoveBackward','StrafeLeft','StrafeRight','Jump'})
            or any(abs(float(self._input.get(k,0)))>.01 for k in ('forward','strafe','throttle','vertical'))
            or bool(self._input.get('jump')) or math.hypot(self._vx[0],self._vz[0])>.3)

    def _spell_commit_cost_locked(self, ref, ability):
        self._resource-=number(ability,'resource_cost',high=100)
        self._ability_cooldowns[ref]=number(ability,'cooldown_s',high=300)
        self._spell_state['gcd_until']=self._sim_time+1.
        self._last_ability=ref;self._last_ability_status='FIRED';self._last_ability_time=self._sim_time

    def _spell_apply_locked(self, ref, ability, target):
        effect=ability['effect'];actor=self._combat_state['actors'][target]
        index=0 if target=='player' else self._npc_index_for_id_locked(target)
        result=dict(ok=True,status='FIRED',ability_id=ref,target=target)
        if not (self._spell_state.get('pending') or {}).get('channel'):
            self._spell_presentation_stage_locked(ref,ability,'STOP',target)
            self._spell_presentation_stage_locked(ref,ability,'cast',target)
        if ability['kind']=='FORM':
            self._spell_state['form']=ref;self._spell_event_locked('UPDATE_SHAPESHIFT_FORM')
            result['status']='FORM_ACTIVE'
        damage=number(effect,'damage')
        if damage:
            dealt,absorbed=combat.deal_damage(self._combat_state,actor,damage,'player',self._sim_time)
            result.update(damage=dealt,absorbed=absorbed,defeated=not actor['alive'])
            actor['engaged_target']='player' if actor['alive'] else ''
            self._start_character_action_locked(target,'Death' if not actor['alive'] else 'HitReact')
            result['faction']=factions.adjust_person(self._faction_state,target,-30,
                source='PLAYER_ATTACK',sim_time=self._sim_time)
            person=self._individual_state.get('individuals',{}).get(target)
            if isinstance(person,dict):
                identity.record_memory(self._individual_state,target,'PLAYER_ATTACK','player',self._sim_time,
                    text='The player attacked me with a spell.',weight=.92)
            self._last_combat=dict(result,attacker_id='player',defender_id=target,action_id=ref,
                kind='SPELL',time_s=self._sim_time,defender_health=actor['health'],defender_max_health=actor['max_health'])
            self._append_event_locked('COMBAT_ATTACK',ability['name']+' hit '+target,
                actor_id='player',subject_id=ref,target_id=target,payload=copy.deepcopy(self._last_combat))
            if not actor['alive']:self._handle_npc_defeat_locked(target,index,self._last_combat)
        heal=number(effect,'heal')
        if heal and actor['alive']:
            actual=min(heal,actor['max_health']-actor['health']);actor['health']+=actual;result['healing']=actual
        if effect.get('status') and actor['alive']:
            combat.apply_status(actor,dict(kind=effect['status'],amount=number(effect,'amount'),
                duration_s=number(effect,'duration_s',high=15),source_id=ref),'player',self._sim_time)
        self._combat_state['revision']+=1
        burst=int(number(effect,'particle_burst',high=96))
        if burst:self._burst_locked(self._x[index],self._y[index]+.5,self._z[index],burst,owner='player' if index==0 else '')
        self._append_event_locked('SPELL_EFFECT',ability['name']+' → '+target,
            actor_id='player',subject_id=ref,target_id=target,payload=result)
        self._spell_presentation_stage_locked(ref,ability,'impact',target)
        return result

    def _tick_spells_locked(self, dt):
        state=self._spell_state;pending=state['pending']
        actor=self._combat_state.get('actors',{}).get('player',{})
        if not actor.get('alive',True):
            self._cancel_spell_locked('DEFEATED')
            if state['form']:state['form']=None;self._spell_event_locked('UPDATE_SHAPESHIFT_FORM')
            return
        if not pending:return
        now=self._sim_time
        if (self._spell_moving_locked() or self._services.get('taxi_flight')
                or max(abs(v[0]-old) for v,old in zip((self._x,self._y,self._z),pending['position']))>.3):
            self._cancel_spell_locked('MOVEMENT');return
        try:
            ability=pending['definition'];self._spell_definition_locked(pending['ref'])
            self._spell_target_locked(ability,pending['target'])
        except ValueError:
            self._cancel_spell_locked('TARGET_INVALID');return
        if actor.get('health',0)<pending['health'] and pending['pushbacks']<2:
            pending['pushbacks']+=1
            if pending['channel']:
                pending['end']=max(now,pending['end']-.5)
                self._spell_event_locked('SPELLCAST_CHANNEL_UPDATE',round(max(0,pending['end']-now)*1000))
            else:
                pending['end']+=.5;self._spell_event_locked('SPELLCAST_DELAYED',500)
        pending['health']=actor.get('health',0)
        if pending['channel']:
            interval=pending['duration']/pending['ticks']
            while pending['ticks_done']<pending['ticks'] and pending['start']+(pending['ticks_done']+1)*interval<=min(now,pending['end'])+1e-8:
                if not self._combat_state['actors'].get(pending['target'],{}).get('alive'):
                    self._cancel_spell_locked('TARGET_INVALID');return
                pending['ticks_done']+=1
                state['last_result']=self._spell_apply_locked(pending['ref'],ability,pending['target'])
            if now+1e-8>=pending['end']:
                self._spell_presentation_stage_locked(pending['ref'],ability,'STOP',pending['target'])
                state['pending']=None;self._spell_event_locked('SPELLCAST_CHANNEL_STOP')
        elif now+1e-8>=pending['end']:
            state['pending']=None
            if self._resource<number(ability,'resource_cost',high=100):
                self._spell_event_locked('SPELLCAST_FAILED');state['last_result']=dict(error='ABILITY_RESOURCE_MISSING')
                return
            self._spell_commit_cost_locked(pending['ref'],ability)
            state['last_result']=self._spell_apply_locked(pending['ref'],ability,pending['target'])
            self._spell_event_locked('SPELLCAST_STOP')

    def _spell_control_locked(self, row):
        op=row.get('op')
        if op=='Stop':self._cancel_spell_locked('PLAYER_CANCELLED')
        elif op=='StopTargeting':self._spell_state['targeting']=None
        elif op=='Cast':
            ref=row.get('ref')
            if not isinstance(ref,str) or len(ref)>128:raise ValueError('CONTENT_ABILITY_NOT_FOUND')
            ok,result=self._start_spell_locked(ref,'player' if row.get('on_self') is True else None)
            if not ok:raise ValueError(result['error'])
        elif op=='Target':
            ref=self._spell_state['targeting']
            if not ref:raise ValueError('NO_SPELL_TARGETING')
            target=self._legacy_unit_locked(row.get('unit',''))
            if not target:raise ValueError('SPELL_TARGET_INVALID')
            ok,result=self._start_spell_locked(ref,target)
            if not ok:raise ValueError(result['error'])
        else:raise ValueError('SPELL_CONTROL_INVALID')

    def _spell_armor_bonus_locked(self):
        ref=getattr(self,'_spell_state',{}).get('form')
        ability=self._content.get('abilities',{}).get(ref,{})
        return float(ability.get('effect',{}).get('armor_bonus',0)) if ref else 0.

    def _spell_availability_locked(self,ref,ability):
        if ability.get('kind') not in ('SPELL','FORM'):return {}
        reason='';in_range=None
        try:
            ability=self._spell_definition_locked(ref)
            if not (ability['kind']=='FORM' and self._spell_state['form']==ref):
                self._spell_ready_locked(ref,ability)
                if (ability.get('cast_time_s') or ability.get('channel_time_s')) and self._spell_moving_locked():
                    raise ValueError('SPELL_CANNOT_CAST_WHILE_MOVING')
                in_range=self._spell_target_locked(ability) is not None
        except ValueError as exc:reason=str(exc);in_range=False
        value=dict(usable=not reason,reason=reason,in_range=in_range,
            current=ability.get('kind')=='FORM' and self._spell_state['form']==ref)
        if value['current']:
            value.update(not_enough_resource=False,cooldown_s=0.,cooldown_duration_s=0.)
            return value
        if not self._ability_cooldowns.get(ref,0) and self._spell_state['gcd_until']>self._sim_time:
            value.update(cooldown_s=self._spell_state['gcd_until']-self._sim_time,cooldown_duration_s=1.)
        return value

    def _spells_view_locked(self):
        state=self._spell_state;pending=copy.deepcopy(state['pending'])
        if pending:
            pending.pop('definition',None);pending['remaining_s']=max(0.,pending['end']-self._sim_time)
        forms=[]
        for ref,ability in self._content.get('abilities',{}).items():
            if ability.get('kind')!='FORM':continue
            try:self._spell_definition_locked(ref)
            except ValueError:continue
            availability=self._spell_availability_locked(ref,ability)
            forms.append(dict(ref=ref,name=ability['name'],active=state['form']==ref,
                castable=availability['usable'],
                cooldown_s=availability.get('cooldown_s',self._ability_cooldowns.get(ref,0)),
                cooldown_duration_s=availability.get('cooldown_duration_s',ability.get('cooldown_s',0))))
        targets=[]
        if state['targeting']:
            try:
                ability=self._spell_definition_locked(state['targeting'])
                for row in self._legacy_units_locked()[:64]:
                    try:
                        if self._spell_target_locked(ability,row['id']):targets.append(self._service_unit_locked(row['id'])['guid'])
                    except ValueError:continue
                if ability.get('target') in ('self','friendly'):targets.append(1)
            except ValueError:pass
        return dict(epoch=state['epoch'],events=copy.deepcopy(state['events']),casting=pending is not None,
            pending=pending,targeting=state['targeting'] is not None,target_guids=targets,form=state['form'],forms=forms,
            global_cooldown_s=max(0.,state['gcd_until']-self._sim_time),last_result=copy.deepcopy(state['last_result']))
