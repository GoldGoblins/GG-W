"""Mounted original trigger volumes and explicit local GG gameplay actions.

Tables load before world attachment. Fixed steps perform bounded volume tests
over immutable rows, with no file or native-worker calls on the simulation lane.
"""
from __future__ import annotations
import math
from backend.game_engine_adapter_game_data import GameplayData


def contains(row,point):
    delta=[point[i]-row['position_yards'][i] for i in range(3)]
    radius=row['radius_yards']
    if radius:return sum(value*value for value in delta)<=radius*radius
    yaw=-row['box_yaw_radians'];sine,cosine=math.sin(yaw),math.cos(yaw)
    local=(delta[0]*cosine-delta[1]*sine,delta[0]*sine+delta[1]*cosine,delta[2])
    return all(-size/2<value<size/2 for value,size in zip(local,row['box_size_yards']))


def prepare(cache,config,quests):
    bindings=config.get('trigger_bindings',[])
    if not isinstance(bindings,list) or len(bindings)>64:raise ValueError('World trigger binding capacity exceeded')
    if not bindings:return []
    map_id=config.get('map_id')
    if type(map_id) is not int or not 0<=map_id<=0xffffffff:raise ValueError('Bound world trigger map identity required')
    ids=[];actions={}
    for binding in bindings:
        if not isinstance(binding,dict) or set(binding)!={'trigger_id','action'}:raise ValueError('Invalid world trigger binding')
        identity=binding['trigger_id'];action=binding['action']
        if type(identity) is not int or not 1<=identity<=0xffffffff or identity in actions:raise ValueError('Invalid world trigger identity')
        if not isinstance(action,dict):raise ValueError('Invalid world trigger action')
        if action.get('kind')=='QUEST_VISIT':
            if set(action)!={'kind','quest_id'}:raise ValueError('Invalid world trigger quest binding')
            definition=quests.get(action['quest_id']) if isinstance(action.get('quest_id'),str) else None
            if not isinstance(definition,dict) or definition.get('objective',{}).get('kind')!='VISIT':raise ValueError('World trigger requires an existing visit quest')
            action={**action,'target_id':definition['objective'].get('target_id','')}
        elif action.get('kind')=='TELEPORT':
            point=action.get('position')
            if set(action)!={'kind','position'} or not isinstance(point,list) or len(point)!=3 or any(type(n) not in (int,float) or not math.isfinite(n) or abs(n)>2_000_000 for n in point):raise ValueError('Invalid world trigger destination')
            action={**action,'position':tuple(point)}
        elif action!={'kind':'EVENT'}:raise ValueError('Unknown world trigger action')
        ids.append(identity);actions[identity]=action
    data=GameplayData(cache._reader()).triggers(ids)
    if data['missing_ids']:raise ValueError('Bound world trigger identity missing')
    if any(row['map_id']!=map_id for row in data['rows']):raise ValueError('Bound world trigger belongs to another map')
    return [dict(row,action=actions[row['id']]) for row in sorted(data['rows'],key=lambda row:row['ordinal'])]


def tick(runtime):
    stream=getattr(runtime,'_engine_world',None)
    rows=getattr(stream,'_trigger_rows',None)
    if not rows:return
    from backend.game_engine_adapter_pet_world import scope
    if scope(runtime)!=getattr(stream,'return_scope',None):return
    if runtime._services.get('taxi_flight') or runtime._opening_cinematic or runtime._vehicle_kind!='NONE':return
    if runtime._player_defeated_locked():return
    origin=stream.config['origin']
    # Retained scene vertices use (X,Z,-Y), without a second unit conversion.
    point=(runtime._x[0]+origin[0],origin[1]-runtime._z[0],runtime._y[0]-.65+origin[2])
    if not stream.query(runtime._x[0],runtime._y[0],runtime._z[0]).get('loaded'):return
    previous=getattr(stream,'_trigger_inside',None)
    if previous is not None and contains(previous,point):return
    stream._trigger_inside=None
    row=next((row for row in rows if contains(row,point)),None)
    if row is None:return
    stream._trigger_inside=row
    action=row['action'];status='ENTERED'
    try:
        if action['kind']=='QUEST_VISIT':
            runtime._record_quest_event_locked(dict(kind='VISIT',target_id=action['target_id'],
                movement_mode=runtime._movement_mode,x=runtime._x[0],z=runtime._z[0]))
        elif action['kind']=='TELEPORT':
            runtime._travel_idle_locked()
            x,y,z=action['position'];floor=stream.query(x,y,z)
            if not floor.get('loaded') or floor.get('impassable') or not math.isfinite(floor.get('height',math.nan)) or abs(y-.65-floor['height'])>.75:
                raise ValueError('WORLD_TRIGGER_DESTINATION_NOT_READY')
            runtime._cancel_spell_locked('WORLD_CHANGED')
            runtime._x[0],runtime._y[0],runtime._z[0]=x,floor['height']+.65,z
            runtime._vx[0]=runtime._vy[0]=runtime._vz[0]=0.;runtime._grounded=True
            stream.safe=(runtime._x[0],runtime._y[0],runtime._z[0]);status='TELEPORTED'
    except ValueError as exc:status=str(exc)
    runtime._append_event_locked('WORLD_TRIGGER','World trigger '+str(row['id'])+': '+status,
        actor_id='player',subject_id=str(row['id']),payload=dict(map_id=row['map_id'],action=action['kind'],status=status))
    runtime._ui_snapshot_base=None;runtime._render_snapshot_cache=None
