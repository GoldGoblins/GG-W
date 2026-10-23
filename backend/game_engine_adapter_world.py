"""Actual GG areas/environment and unit assets for the original Lua/model API."""
import math
from backend import game_engine_planet as planet
from backend import game_engine_world_places as places
from backend.game_engine_world_style import cottage_roof_y

def environment(snapshot):
    player=snapshot['player']
    x,y,z=(float(player.get(k,0)) for k in ('x','y','z'))
    if any(not math.isfinite(n) or abs(n)>2_000_000 for n in (x,y,z)):raise ValueError('Invalid world position')
    region=planet.region_at(x,z) or {}
    biome=str(player.get('biome',''))[:64]
    real=str(region.get('name') or biome or 'GG World')[:128]
    nearby=[p for p in places.catalog()['places'] if math.hypot(x-p['x'],z-p['z'])<=float(p.get('clearing_m',0))]
    place=min(nearby,key=lambda p:math.hypot(x-p['x'],z-p['z'])) if nearby else {}
    indoors=False
    for building in places.building_index().get((math.floor(x/64),math.floor(z/64)),()):
        lx,lz,_,_=places.building_local(building,x,z)
        if abs(lx)>4.2 or abs(lz)>3.2:continue
        base=planet.surface_height(building['x'],building['z'])
        roof=base+cottage_roof_y(lx,lz)*building['scale']+.65
        if base-.5<=y<roof-.12:indoors=True;break
    actor=snapshot.get('combat_live',{}).get('player',{})
    hot=bool(actor.get('engaged_target')) and not bool(actor.get('dead'))
    result={'zone':real,'real_zone':real,'subzone':str(place.get('name',''))[:128],
            'minimap':str(place.get('name') or real)[:128],'region_id':str(region.get('id',''))[:64],
            'place_id':str(place.get('id',''))[:64],'biome':biome,'medium':str(player.get('medium','LAND'))[:16],
            'indoors':indoors,'grounded':bool(player.get('grounded')),'swimming':player.get('movement_mode')=='SWIM','in_combat':hot,
            'x':x,'y':y,'z':z,'cell':str(player.get('cell_key',''))[:64]}
    imported=player.get('engine_world')
    if isinstance(imported,dict):result.update(imported)
    return result

def unit_asset(snapshot,token):
    if token=='player':
        entity=next((e for e in snapshot.get('render',{}).get('entities',[]) if e.get('kind')=='PLAYER'),{})
    elif token=='target':
        selected=snapshot.get('targeting',{}).get('selected') or {}
        wanted=selected.get('entity_id') or selected.get('id')
        entity=next((e for e in snapshot.get('render',{}).get('entities',[]) if wanted is not None and e.get('id')==wanted),{})
    else:entity={}
    asset=entity.get('asset',{})
    return asset if isinstance(asset,dict) else {}
