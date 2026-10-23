"""Explicit mounted DBC bindings over existing GG learned ability definitions.

The selected manifest names both identities. A catalog query alone changes no
learned state. Bindings reuse canonical cast/combat/cooldown behavior and are
removed with the owning map/character generation, including interrupted casts.
"""
from __future__ import annotations
import copy,math
from backend.game_engine_adapter_game_data import GameplayData


def prepare(cache,rows,abilities,level):
    if not isinstance(rows,list) or len(rows)>64:raise ValueError('Spell binding capacity exceeded')
    if not rows:return {}
    seen=set();ids=[]
    for row in rows:
        if not isinstance(row,dict) or set(row)-{'spell_id','ability_id','timing','range','cost','effects'}:raise ValueError('Invalid spell binding')
        identity=row.get('spell_id');ref=row.get('ability_id')
        if type(identity) is not int or not 1<=identity<=0xffffffff or not isinstance(ref,str) or ref in seen:raise ValueError('Invalid spell binding identity')
        if not isinstance(abilities.get(ref),dict) or abilities[ref].get('kind') not in ('SPELL','FORM'):raise ValueError('Spell binding requires an existing GG ability')
        if any(type(row.get(key,default)) is not bool for key,default in (('timing',True),('range',True),('cost',False),('effects',False))):raise ValueError('Invalid spell binding flag')
        seen.add(ref)
        if identity not in ids:ids.append(identity)
    result=GameplayData(cache._reader()).spells(ids,joins=True,level=level)
    if result['missing_ids']:raise ValueError('Bound spell identity missing')
    metadata={s['id']:s for s in result['rows']};prepared={}
    for row in rows:
        ref=row['ability_id'];s=metadata[row['spell_id']];ability=copy.deepcopy(abilities[ref])
        if not isinstance(s['name'],str) or not 1<=len(s['name'])<=96:raise ValueError('Bound spell name invalid')
        ability.update(name=s['name'],description=s['description'],original_spell_id=s['id'],original_spell_rank=s['rank'])
        if s.get('icon'):ability['icon']=s['icon']
        if s.get('visual'):ability['original_visual']=s['visual']
        ability['required_level']=max(ability.get('required_level',1),s['spell_level'])
        if not 1<=ability['required_level']<=60:raise ValueError('Bound spell level invalid')
        if row.get('timing',True):
            timing=s['casting_time'];duration=s['duration']
            if timing is None and s['casting_time_index']:raise ValueError('Bound spell casting time missing')
            cast=max(0,timing['resolved_ms'])/1000 if timing else 0.
            if cast>30:raise ValueError('Bound spell casting time exceeds local capacity')
            if ability.get('channel_time_s'):
                if not duration or duration['permanent'] or duration['per_level_ms']:raise ValueError('Bound channel duration unsupported')
                channel=duration['base_ms']/1000
                if not 0<channel<=30 or cast:raise ValueError('Bound channel duration invalid')
                ability['channel_time_s']=channel
            else:ability['cast_time_s']=cast
            cooldown=max(s['recovery_ms'],s['category_recovery_ms'])/1000
            if cooldown>300:raise ValueError('Bound spell cooldown exceeds local capacity')
            ability['cooldown_s']=cooldown
        if row.get('range',True):
            distance=s['range']
            if distance is None and s['range_index']:raise ValueError('Bound spell range missing')
            if distance and distance['melee']:raise ValueError('Bound melee spell needs combat-reach policy')
            minimum=distance['min_yards']*.9144 if distance else 0.;maximum=distance['max_yards']*.9144 if distance else 0.
            if not 0<=minimum<=maximum<=100:raise ValueError('Bound spell range invalid')
            ability['min_range_m']=minimum;ability['range_m']=maximum
        if row.get('cost',False):
            if s['power_type']!=0 or s['mana_per_second']:raise ValueError('Bound spell resource policy unsupported')
            cost=s['mana_cost']+s['mana_cost_per_level']*max(0,level-s['base_level'])+s['mana_cost_percent']
            if not 0<=cost<=100:raise ValueError('Bound spell resource cost exceeds local capacity')
            ability['resource_cost']=cost
        if row.get('effects',False):
            effects=[e for e in s['effects'] if e['effect']]
            if len(effects)!=1 or effects[0]['effect'] not in (2,10):raise ValueError('Bound spell effect requires an explicit local implementation')
            e=effects[0]
            if (e['die_sides']>1 or e['base_dice']>1 or e['chain_targets'] or e['trigger_spell']
                    or e['radius_index'] or s['max_affected_targets']>1 or any(any(pair) for pair in s['reagents']) or any(s['totems'])):
                raise ValueError('Bound spell multi-target/random/reagent effect unsupported')
            amount=e['base_points']+1+max(0,level-s['base_level'])*e['real_points_per_level']
            if not math.isfinite(amount) or not 0<=amount<=100000:raise ValueError('Bound spell effect amount invalid')
            ability['effect']={('damage' if e['effect']==2 else 'heal'):amount,'particle_burst':ability.get('effect',{}).get('particle_burst',0)}
            if e['effect']==2 and ability.get('target')!='hostile':raise ValueError('Bound damage spell target policy invalid')
        prepared[ref]=ability
    return prepared


def install(runtime,stream,prepared):
    if not prepared:return
    from backend.game_engine_adapter_pet_world import scope
    stream._spell_binding_scope=scope(runtime)
    stream._spell_binding_originals={ref:runtime._content['abilities'][ref] for ref in prepared}
    stream._spell_binding_values=prepared
    runtime._content['abilities'].update(prepared)
    runtime._ui_snapshot_base=None;runtime._render_snapshot_cache=None


def leave(runtime,stream):
    originals=getattr(stream,'_spell_binding_originals',None)
    if not originals:return
    del stream._spell_binding_originals
    from backend.game_engine_adapter_pet_world import scope
    owned={ref:value for ref,value in originals.items()
           if runtime._content['abilities'].get(ref) is getattr(stream,'_spell_binding_values',{}).get(ref)}
    if not owned:return
    pending=runtime._spell_state.get('pending')
    if pending and pending['ref'] in originals:runtime._cancel_spell_locked('WORLD_CHANGED')
    if runtime._spell_state.get('targeting') in originals:runtime._spell_state['targeting']=None
    runtime._content['abilities'].update(owned)
    runtime._ui_snapshot_base=None;runtime._render_snapshot_cache=None
