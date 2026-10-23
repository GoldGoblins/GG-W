"""Nearby support and produce points from the saved, actually rendered trees.

Upper leaf triangles are one-way surfaces: walking underneath never snaps a
player upwards. Barycentric heights follow the exported near mesh, including
its folds, yaw and scale. No collision or harvesting work runs on far trees.
"""
from functools import lru_cache
from pathlib import Path
import gzip,json,math
from backend.game_engine_botanical_designs import tree_variant

AUTH=Path(__file__).resolve().parents[1]/'qml/assets/authored'
CELL=128

@lru_cache(maxsize=1)
def recipes():
    path=AUTH/'variants/biodiversity.catalog.json'
    if not path.is_file():return {}
    result={key.split('/',1)[1]:row['variants'] for key,row in json.loads(path.read_text())['families'].items()
            if key.startswith('flora/') and row['variants'][0].get('canopy_triangles')}
    for variants in result.values():
        for model in variants:
            model['min_support_y']=min((p[1] for tri in model['canopy_triangles'] for p in tri),default=float('inf'))
    return result

@lru_cache(maxsize=8)
def _sector(sx,sz):
    path=AUTH/'world/trees'/f'{sx}_{sz}.json.gz'
    if not path.is_file():return {}
    grid={}
    for row in json.loads(gzip.decompress(path.read_bytes())):
        grid.setdefault((math.floor(row['x']/CELL),math.floor(row['z']/CELL)),[]).append(row)
    return grid

def nearby(x,z,radius=100):
    # Tree pages are 2048m wide, matching the existing editable map catalog.
    cx,cz=math.floor(x/CELL),math.floor(z/CELL);rows=[]
    n=math.ceil(radius/CELL)
    for dx in range(-n,n+1):
        for dz in range(-n,n+1):
            gx,gz=cx+dx,cz+dz
            page=_sector(math.floor(gx*CELL/2048),math.floor(gz*CELL/2048))
            rows.extend(row for row in page.get((gx,gz),()) if math.hypot(row['x']-x,row['z']-z)<radius)
    return rows

def local_point(row,x,z):
    angle=math.radians(row['yaw']);c,s=math.cos(angle),math.sin(angle)
    dx,dz=(x-row['x'])/row['scale'],(z-row['z'])/row['scale']
    return c*dx-s*dz,s*dx+c*dz

def point_height(triangle,x,z):
    a,b,c=triangle
    if not min(a[0],b[0],c[0])<=x<=max(a[0],b[0],c[0]) or not min(a[2],b[2],c[2])<=z<=max(a[2],b[2],c[2]):return None
    det=(b[2]-c[2])*(a[0]-c[0])+(c[0]-b[0])*(a[2]-c[2])
    if abs(det)<1e-9:return None
    u=((b[2]-c[2])*(x-c[0])+(c[0]-b[0])*(z-c[2]))/det
    v=((c[2]-a[2])*(x-c[0])+(a[0]-c[0])*(z-c[2]))/det
    if u<-.00001 or v<-.00001 or u+v>1.00001:return None
    return u*a[1]+v*b[1]+(1-u-v)*c[1]

def contact_height(x,z,root_y,height_at):
    from backend.game_engine_mobility import PLAYER_ROOT_HEIGHT_M
    highest=None;bank=recipes()
    for row in nearby(x,z):
        variants=bank.get(row['species'])
        if not variants:continue
        model=variants[tree_variant(row['id'],row['species'])];lx,lz=local_point(row,x,z)
        base=height_at(row['x'],row['z'])-.06
        if root_y+.12<base+model['min_support_y']*row['scale']+PLAYER_ROOT_HEIGHT_M:continue
        for triangle in model['canopy_triangles']:
            h=point_height(triangle,lx,lz)
            if h is None:continue
            support=base+h*row['scale']+PLAYER_ROOT_HEIGHT_M
            if root_y>=support-.12 and (highest is None or support>highest):highest=support
    return highest

def produce_anchors(x,z,height_at):
    bank=recipes();out=[]
    for row in nearby(x,z,100):
        variants=bank.get(row['species'])
        if not variants:continue
        points=variants[tree_variant(row['id'],row['species'])].get('produce_points',())
        angle=math.radians(row['yaw']);c,s=math.cos(angle),math.sin(angle);scale=row['scale']
        for i,point in enumerate(points):
            px,py,pz=point['point'];wx=row['x']+scale*(c*px+s*pz);wz=row['z']+scale*(-s*px+c*pz)
            if math.hypot(wx-x,wz-z)>88:continue
            out.append(dict(id='nature:produce:'+row['id']+':'+str(i),species=point['species'],
                anchor_x=wx,anchor_z=wz,ground_height_m=height_at(row['x'],row['z'])-.06+py*scale,
                phase=0,scale=min(2.5,scale*.5),tint=1))
    return sorted(out,key=lambda r:(math.hypot(r['anchor_x']-x,r['anchor_z']-z),r['id']))[:72]
