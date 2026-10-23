"""Saved geology, water bodies and landmark footprints in shared game metres.

Authoring is offline. The renderer, physical terrain and atlas read one saved
document. Spatial bins bound sampling work; camera/time never move features.
"""
from __future__ import annotations
import json, math
from functools import lru_cache
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'qml/assets/authored/world/world-landscape.json'
ASSETS=ROOT/'qml/assets/authored/world/landscape'
BIN_M=256
SHAPE_KINDS={'PEAK','MESA','VALLEY','LAKE','BAY','ISLET','PENINSULA','RIVER','GROTTO','SEAT'}

def smooth(a,b,v):
    t=max(0.,min(1.,(v-a)/(b-a)));return t*t*(3-2*t)

@lru_cache(maxsize=1)
def catalog():
    if not SOURCE.exists():return {'schema':'gg.world-landscape.v1','features':[],'structures':[],'bridges':[]}
    doc=json.loads(SOURCE.read_text())
    if doc.get('schema')!='gg.world-landscape.v1':raise ValueError('invalid landscape schema')
    return doc

def bounds(row):
    if row['kind']=='BRIDGE':
        r=math.hypot(row['length_m']/2+64,row['width_m']/2+36)
        return row['x']-r,row['z']-r,row['x']+r,row['z']+r
    if 'points' in row:
        pad=float(row.get('bank_m',row.get('width_m',120)))
        return (min(p[0] for p in row['points'])-pad,min(p[1] for p in row['points'])-pad,
                max(p[0] for p in row['points'])+pad,max(p[1] for p in row['points'])+pad)
    rx,rz=row.get('radii_m',[row.get('radius_m',60)]*2);pad=row.get('extent',1.4)
    # Rotated ellipses use their enclosing circle, never omit a tilted end.
    r=max(rx,rz)*pad
    return row['x']-r,row['z']-r,row['x']+r,row['z']+r

@lru_cache(maxsize=1)
def index():
    bins={}
    for row in catalog()['features']+catalog()['bridges']:
        x0,z0,x1,z1=bounds(row)
        for cx in range(math.floor(x0/BIN_M),math.floor(x1/BIN_M)+1):
            for cz in range(math.floor(z0/BIN_M),math.floor(z1/BIN_M)+1):bins.setdefault((cx,cz),[]).append(row)
    return {k:tuple(v) for k,v in bins.items()}

def nearby(x,z):return index().get((math.floor(x/BIN_M),math.floor(z/BIN_M)),())

def enabled():
    from backend.game_engine_planet import MAP_REVISION
    return catalog().get('map_revision')==MAP_REVISION

def ellipse(row,x,z):
    dx,dz=x-row['x'],z-row['z'];a=math.radians(row.get('yaw',0));co,si=math.cos(a),math.sin(a)
    rx,rz=row.get('radii_m',[row.get('radius_m',60)]*2)
    u=(dx*co-dz*si)/rx;v=(dx*si+dz*co)/rz
    r=math.hypot(u,v)
    # Broad harmonic bays and lake shores, no trunk/terrain lattice.
    if row['kind'] in ('LAKE','BAY','ISLET'):
        t=math.atan2(v,u);r/=1+.065*math.sin(3*t+row.get('phase',0))+.035*math.cos(5*t)
    return r

def segment_sample(x,z,a,b):
    dx,dz=b[0]-a[0],b[1]-a[1];n=dx*dx+dz*dz
    t=max(0.,min(1.,((x-a[0])*dx+(z-a[1])*dz)/n)) if n else 0.
    return math.hypot(x-a[0]-t*dx,z-a[1]-t*dz),t

def line_sample(row,x,z):
    found=(float('inf'),0,0.)
    for i,(a,b) in enumerate(zip(row['points'],row['points'][1:])):
        d,t=segment_sample(x,z,a,b)
        if d<found[0]:found=(d,i,t)
    return found

@lru_cache(maxsize=1)
def protection_index():
    """Keep current house floors, road centres and saved routine anchors usable."""
    from backend.game_engine_world_places import catalog as place_catalog
    bins={}
    def add(row,x0,z0,x1,z1):
        for cx in range(math.floor(x0/BIN_M),math.floor(x1/BIN_M)+1):
            for cz in range(math.floor(z0/BIN_M),math.floor(z1/BIN_M)+1):bins.setdefault((cx,cz),[]).append(row)
    for place in place_catalog()['places']:
        x,z=place['x'],place['z'];r=150 if place['kind']=='TOWN' else 92
        add(('circle',x,z,r),x-r-180,z-r-180,x+r+180,z+r+180)
    for road in place_catalog()['roads']:
        for a,b in zip(road['points'],road['points'][1:]):
            pad=180+road['width_m']/2
            add(('line',a,b,road['width_m']/2+12),min(a[0],b[0])-pad,min(a[1],b[1])-pad,max(a[0],b[0])+pad,max(a[1],b[1])+pad)
    return {k:tuple(v) for k,v in bins.items()}

def protection(x,z):
    result=0.
    for shape,a,b,r in protection_index().get((math.floor(x/BIN_M),math.floor(z/BIN_M)),()):
        d=math.hypot(x-a,z-b) if shape=='circle' else segment_sample(x,z,a,b)[0]
        result=max(result,1-smooth(r,r+160,d))
        if result>=1:return 1.
    return result

def surface_height(x,z,base):
    if not enabled():return base
    rows=nearby(x,z)
    if not rows:return base
    height=base
    # Union/cut coast shapes precede relief and river carving.
    for row in rows:
        kind=row['kind']
        if kind not in SHAPE_KINDS:continue
        if kind in ('RIVER','PENINSULA'):
            d,i,t=line_sample(row,x,z)
            if kind=='PENINSULA':
                if d<row['width_m']:height=max(height,row['height_m']*(1-smooth(0,row['width_m'],d))-2)
            continue
        r=ellipse(row,x,z)
        if kind=='BAY' and r<1.3:
            height=height*smooth(.70,1.3,r)+(-row['depth_m'])*(1-smooth(.70,1.3,r))
        elif kind=='ISLET' and r<1.2:
            height=max(height,row['height_m']*max(0,1-r)**1.15-3)
        elif kind=='PEAK' and r<1 and base>0:
            theta=math.atan2(z-row['z'],x-row['x'])
            phase=row.get('phase',0)
            ridge=1+(.26*math.sin(3*theta+phase)+.11*math.cos(5*theta-phase))*smooth(.10,.80,r)
            height+=row['rise_m']*max(0,1-r**1.2*ridge)**1.85*smooth(0,8,base)
        elif kind=='MESA' and r<1:
            height+=row['rise_m']*(1-smooth(.40,1,r))
        elif kind=='VALLEY' and r<1.3:
            w=1-smooth(.12,1.3,r);height=height*(1-w)+row['floor_m']*w
    # Roads/towns retain their established floors. Water stays a separate bed.
    p=protection(x,z)
    height=height*(1-p)+base*p
    # Cut the river through the shore falloff, preserving the lake's own bed
    # inside its water boundary. Neither channel nor bank can fill the other.
    for row in sorted(rows,key=lambda r:{'LAKE':1,'RIVER':2}.get(r['kind'],0)):
        kind=row['kind']
        if kind=='LAKE':
            r=ellipse(row,x,z)
            if r<1.4:
                w=1-smooth(1.,1.4,r)
                bed=row['level_m']-row['depth_m']*(1-smooth(0,1.4,r))-.6
                height=height*(1-w)+bed*w
        elif kind=='RIVER':
            d,i,t=line_sample(row,x,z)
            if d<row['bank_m']:
                if any(q['kind']=='LAKE' and ellipse(q,x,z)<=1 for q in rows):continue
                level=row['levels_m'][i]*(1-t)+row['levels_m'][i+1]*t
                w=1-smooth(row['width_m']*.42,row['bank_m'],d)
                height=height*(1-w)+(level-row['depth_m'])*w
        elif kind in ('GROTTO','SEAT'):
            r=ellipse(row,x,z)
            if r<1.4:
                w=1-smooth(.7,1.4,r);height=height*(1-w)+row['floor_m']*w
    return height

def water_at(x,z):
    if not enabled():return None
    result=None
    for row in nearby(x,z):
        kind=row['kind']
        if kind=='LAKE' and ellipse(row,x,z)<=1:
            item={'id':row['id'],'kind':kind,'level_m':row['level_m'],'slope':{'x':0.,'z':0.},'current_mps':{'x':0.,'z':0.}}
        elif kind=='RIVER':
            d,i,t=line_sample(row,x,z)
            if d>row['width_m']/2:continue
            a,b=row['points'][i:i+2];dx,dz=b[0]-a[0],b[1]-a[1];n=dx*dx+dz*dz
            drop=row['levels_m'][i+1]-row['levels_m'][i];length=math.sqrt(n) or 1
            item={'id':row['id'],'kind':kind,'level_m':row['levels_m'][i]*(1-t)+row['levels_m'][i+1]*t,
                  'slope':{'x':drop*dx/n if n else 0.,'z':drop*dz/n if n else 0.},
                  'current_mps':{'x':dx/length*.6,'z':dz/length*.6}}
        else:continue
        if result is None or item['level_m']>result['level_m']:result=item
    return result

def biome_at(x,z):
    if not enabled():return None
    for row in reversed(nearby(x,z)):
        if row['kind'] in ('FOREST','PRAIRIE','FIELDS','MARSH','MOOR','MOSS') and ellipse(row,x,z)<1:
            return row['kind']
    return None

def tree_density(x,z,height):
    if not enabled():return 1.
    if height>650 or water_at(x,z):return 0.
    if any(r['kind'] in ('GROTTO','SEAT','ARCH','STONE_CIRCLE') and ellipse(r,x,z)<1.25 for r in nearby(x,z)):return 0.
    for row in nearby(x,z):
        if row['kind']=='BRIDGE':
            lx,lz=local(row,x,z)
            if abs(lx)<row['width_m']/2+36 and abs(lz)<row['length_m']/2+64:return 0.
    kind=biome_at(x,z)
    return {'FOREST':1.45,'PRAIRIE':.055,'FIELDS':0.,'MARSH':.3,'MOOR':.08,'MOSS':.5}.get(kind,1.)

def clutter_allowed(x,z):
    if water_at(x,z):return False
    for row in nearby(x,z):
        if row['kind']=='GROTTO':
            lx,lz=local(row,x,z)
            if abs(lx)<19 and -7<lz<45:return False
    return True

def coast_owner(x,z):
    if not enabled():return None
    for row in nearby(x,z):
        if row['kind'] in ('BAY','ISLET') and ellipse(row,x,z)<1.3:return row['region_id']
        if row['kind']=='PENINSULA' and line_sample(row,x,z)[0]<row['width_m']:return row['region_id']
    return None

def local(row,x,z):
    a=math.radians(row.get('yaw',0));dx,dz=x-row['x'],z-row['z']
    return dx*math.cos(a)-dz*math.sin(a),dx*math.sin(a)+dz*math.cos(a)

def cave_roof(row,lx,lz):
    if abs(lx)>14 or not -7<=lz<=42:return None
    return row['floor_m']+5+9*math.sqrt(max(0,1-(lx/14)**2))

def cave_outer_roof(row,lx,lz):
    if abs(lx)>19 or not -7<=lz<=45:return None
    return row['floor_m']+5+13*math.sqrt(max(0,1-(lx/19)**2))

def contact_height(x,z,root_y,terrain_height):
    if not enabled():return None
    for row in nearby(x,z):
        if row['kind']=='GROTTO':
            lx,lz=local(row,x,z);roof=cave_outer_roof(row,lx,lz)
            if roof is not None and root_y>=roof+.3:return roof+.65
    for bridge in catalog()['bridges']:
        lx,lz=local(bridge,x,z)
        if abs(lx)<=bridge['width_m']/2+.35 and abs(lz)<=bridge['length_m']/2+24:
            base=terrain_height(x,z) if callable(terrain_height) else terrain_height
            deck=road_height(x,z,base)+.65
            if root_y>=deck-.5:return deck
    return None

def cave_collision(x,z,root_y):
    """Enclosed grotto shell, open front entrance, solid side/back and ceiling."""
    if not enabled():return x,z,root_y
    for row in nearby(x,z):
        if row['kind']!='GROTTO':continue
        lx,lz=local(row,x,z);floor=row['floor_m']
        if not floor-.6<root_y<floor+19 or not -9<lz<45 or abs(lx)>20:continue
        outer=cave_outer_roof(row,lx,lz)
        if outer is not None and root_y>=outer+.25:continue
        roof=cave_roof(row,lx,lz)
        if -7<lz<42 and 13.5<abs(lx)<19:lx=math.copysign(13.5 if abs(lx)<16 else 19,lx)
        if 41.5<lz<45 and abs(lx)<19:lz=41.5 if lz<43 else 45
        if roof is not None and root_y<roof and root_y+1.7>roof:root_y=roof-1.7
        a=math.radians(row.get('yaw',0));x=row['x']+lx*math.cos(a)+lz*math.sin(a);z=row['z']-lx*math.sin(a)+lz*math.cos(a)
    return x,z,root_y

def road_height(x,z,base):
    if not enabled():return base
    for b in catalog()['bridges']:
        lx,lz=local(b,x,z)
        if abs(lx)<=b['width_m']/2+3 and abs(lz)<=b['length_m']/2+24:
            w=1-smooth(b['length_m']/2,b['length_m']/2+24,abs(lz));base=base*(1-w)+b['deck_m']*w
    return base

def clear_caches():
    catalog.cache_clear();index.cache_clear();protection_index.cache_clear()
