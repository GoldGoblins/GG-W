"""Nearby lamp anchors come from the saved map, independently of the camera."""
import math
import json
from functools import lru_cache
from backend import game_engine_world_places as places
from backend import game_engine_planet as planet
from backend import game_engine_landscape as landscape

FX_CELL_M = 24.0
FX_RANGE_M = 42.0


@lru_cache(maxsize=1)
def _waterfalls():
    path=landscape.ASSETS/'waterfalls.catalog.json'
    return json.loads(path.read_text())['placements'] if path.exists() else []


def environment_anchors(x, z, height_at):
    """Fixed cosmetic pockets, sampled locally; they have no AI or lights.

    World-cell IDs seed the authored drift phases. Turning the camera neither
    moves nor respawns them. Distance changes visibility, never the positions.
    """
    rows = []
    cx, cz = math.floor(x / FX_CELL_M), math.floor(z / FX_CELL_M)
    for dz in range(-2, 3):
        for dx in range(-2, 3):
            gx, gz = cx + dx, cz + dz
            seed = ((gx * 73856093) ^ (gz * 19349663) ^ 0x47544731) & 0xffffffff
            # Sparse, irregular pockets leave the path and silhouette readable.
            if seed % 3:
                continue
            ax = (gx + .18 + ((seed >> 8) & 255) / 255 * .64) * FX_CELL_M
            az = (gz + .18 + ((seed >> 16) & 255) / 255 * .64) * FX_CELL_M
            distance = math.hypot(ax - x, az - z)
            if distance >= FX_RANGE_M:
                continue
            y = height_at(ax, az)
            if y <= .2:
                continue
            rows.append(dict(id=f"atmosphere:{gx}:{gz}", x=ax, y=y, z=az,
                             phase=(seed % 10000) * .013,
                             biome=planet.biome_at(ax, az),
                             distance_m=distance,
                             fade=min(1., (FX_RANGE_M - distance) / 14.)))
    rows.sort(key=lambda row: (row['distance_m'], row['id']))
    pockets=rows[:6]
    for waterfall in _waterfalls():
        a=math.radians(waterfall['yaw'])
        ax=waterfall['x']+math.sin(a)*waterfall['length_m']
        az=waterfall['z']+math.cos(a)*waterfall['length_m']
        distance=math.hypot(ax-x,az-z)
        if distance>=64:
            continue
        pockets.append(dict(id=waterfall['id']+':spray',kind='WATERFALL',x=ax,z=az,
                            y=waterfall['floor_m']-waterfall['drop_m']+.4,
                            phase=sum(map(ord,waterfall['id']))*.017,
                            distance_m=distance,fade=min(1.,(64-distance)/20.),
                            width_m=waterfall['width_m']))
    return pockets[:8]

def lamp_anchors(x,z,height_at):
    rows=[]
    for obj in places.catalog()['objects']:
        if obj['kind']!='lantern':continue
        distance=math.hypot(obj['x']-x,obj['z']-z)
        if distance>=48:continue
        rows.append(dict(id=obj['id'],x=obj['x'],z=obj['z'],
            y=height_at(obj['x'],obj['z'])+4.3*obj.get('scale',1),
            distance_m=distance,fade=max(0,min(1,(48-distance)/12))))
    return sorted(rows,key=lambda row:(row['distance_m'],row['id']))[:4]


@lru_cache(maxsize=1)
def _lamps():
    return tuple(obj for obj in places.catalog()['objects'] if obj['kind']=='lantern')


def lamp_beacons(view, range_m, height_at, limit=24, height_cache=None):
    """Saved lamp positions remain visible even when their mesh is unloaded.

    Native billboard depth testing owns occlusion. No distant PointLight or
    NPC simulation is created. The caller caches heights by terrain revision.
    """
    origin,forward,right,up,tangent,aspect,_=view
    rows=[];cache=height_cache if height_cache is not None else {}
    for obj in _lamps():
        dx,dz=obj['x']-origin[0],obj['z']-origin[2]
        distance=math.hypot(dx,dz)
        if distance<40 or distance>range_m:continue
        depth=dx*forward[0]+dz*forward[2]
        side=abs(dx*right[0]+dz*right[2])
        if depth < -12 or side>max(0,depth)*tangent*aspect+32:continue
        rows.append((distance,obj))
    result=[];budget=max(0,min(48,limit))
    ordered=sorted(rows,key=lambda row:(row[0],row[1]['id']))
    # Reserve a few sprites for sources beyond the ordinary terrain range.
    # Otherwise a nearby village can consume the complete beacon budget.
    far=[row for row in ordered if row[0]>view[-1]][:budget//4]
    far_ids={row[1]['id'] for row in far}
    selected=[row for row in ordered if row[1]['id'] not in far_ids][:budget-len(far)]+far
    for distance,obj in selected:
        if obj['id'] not in cache:
            cache[obj['id']]=height_at(obj['x'],obj['z'])+4.3*obj.get('scale',1)
        result.append(dict(id=obj['id'],kind='LAMP',x=obj['x'],y=cache[obj['id']],z=obj['z'],
                           color='#ffbf6c',light_radius_m=8.,light_energy=2.2,distance_m=distance))
    return result
