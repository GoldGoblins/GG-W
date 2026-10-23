"""Transient visual feedback from completed canonical events, never a replay log."""
from __future__ import annotations
import math,re
from backend.game_engine_adapter_text import plain_text

MAX_BUBBLES=64
MAX_FLOATS=48


def _state(runtime):
    active=getattr(runtime,'_services',{}).get('instance_sessions',{}).get('active') or {}
    scope=(getattr(runtime,'_spell_state',{}).get('epoch'),getattr(runtime,'_local_character_id',''),
           id(getattr(runtime,'_engine_world',None)),active.get('id'))
    state=getattr(runtime,'_world_feedback',None)
    if state is None or state['scope']!=scope:
        state=dict(scope=scope,bubbles={},floating=[]);runtime._world_feedback=state
    return state


def _position(runtime,identity):
    if identity=='player':
        return (runtime._x[0],runtime._y[0],runtime._z[0])
    index=runtime._npc_index_for_id_locked(identity)
    if index is not None and runtime._alive[index]:return (runtime._x[index],runtime._y[index],runtime._z[index])
    if identity.startswith('pet:'):
        pet=runtime._active_pet_locked()
        if pet and identity=='pet:'+str(pet['number']):
            from backend.game_engine_adapter_pet_world import pending
            if not pending(runtime,pet):return (pet['x'],pet['y']+.65,pet['z'])
    return None


def observe(runtime,event):
    state=_state(runtime);now=runtime._sim_time;payload=event.get('payload') or {}
    if not isinstance(payload,dict):return
    kind=event.get('kind','');identity=event.get('actor_id','')
    if kind=='CHAT' and payload.get('channel') in ('SAY','YELL','PARTY','MONSTER_SAY','MONSTER_YELL'):
        text=plain_text(payload.get('message') or event.get('text','').partition(': ')[2])[:255]
        if not text or _position(runtime,identity) is None:return
        words=len(re.findall(r'[^ \t]+',text));own=identity=='player'
        duration=(1.5+.5*max(0,words-1)) if own else (2.75+.75*max(0,words-1))
        state['bubbles'].pop(identity,None)
        state['bubbles'][identity]=dict(id='bubble:'+identity,kind='BUBBLE',actor=identity,text=text,
            channel=payload['channel'],start=now,end=now+duration)
        while len(state['bubbles'])>MAX_BUBBLES:state['bubbles'].pop(next(iter(state['bubbles'])))
    amount=payload.get('damage',0);healing=payload.get('healing',0)
    # Spell damage already generated COMBAT_ATTACK. Its concluding presentation
    # event adds only healing, so one completed hit creates one floating number.
    if kind=='SPELL_EFFECT':amount=0
    if kind not in ('COMBAT_ATTACK','NPC_COMBAT_ATTACK','COMBAT_STATUS','PET_ATTACK','PET_FALL_DAMAGE','NPC_FALL_DAMAGE','SPELL_EFFECT'):return
    target=event.get('target_id') or payload.get('defender_id') or payload.get('target') or identity
    value=healing if healing else amount
    if type(value) not in (int,float) or not math.isfinite(value) or value<=0 or _position(runtime,target) is None:return
    critical=payload.get('critical',False) is True
    state['floating'].append(dict(id='combat:'+str(event['sequence']),kind='HEAL' if healing else 'DAMAGE',
        actor=target,text=('+' if healing else '')+str(round(value)),critical=critical,start=now,end=now+1.5))
    state['floating']=state['floating'][-MAX_FLOATS:]


def view(runtime):
    state=_state(runtime);now=runtime._sim_time;result=[]
    state['bubbles']={key:row for key,row in state['bubbles'].items() if row['end']>now}
    state['floating']=[row for row in state['floating'] if row['end']>now]
    for row in (*state['bubbles'].values(),*state['floating']):
        position=_position(runtime,row['actor'])
        if position is None:continue
        actor=runtime._combat_state.get('actors',{}).get(row['actor'],{})
        if row['kind']=='BUBBLE' and (not actor.get('alive',True) or math.dist(position,(runtime._x[0],runtime._y[0],runtime._z[0]))>20*.9144):continue
        age=max(0.,now-row['start']);remaining=row['end']-now
        result.append(dict(row,x=position[0],y=position[1]+(1.85 if row['kind']=='BUBBLE' else .7),z=position[2],age=age,
                           alpha=max(0.,min(1.,age/.25,remaining/.25))))
    return result
