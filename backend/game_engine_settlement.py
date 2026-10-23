"""Authored places, connected roads and routines for the starter settlement.

Only startup reads the map. Camera position never creates or moves a place.
Roads and fences are combined meshes, outside the moving NPC/physics pools.
"""
from functools import lru_cache
import copy
import json
import math
import struct
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1]/'qml/assets/authored/world/sandover-settlement.json'


@lru_cache(maxsize=1)
def catalog():
    if not SOURCE.is_file():
        # A desktop installation can have no authored project content yet.
        return {'schema':'gg.settlement.v1','id':'','coordinates':'metres',
                'places':[],'fixtures':[],'routines':[],'roads':[],'fences':[]}
    document=json.loads(SOURCE.read_text(encoding='utf-8'))
    if document['schema']!='gg.settlement.v1':raise ValueError('invalid settlement map')
    return document


def resident_spawns(existing):
    rows=copy.deepcopy(existing)
    by_id={row['id']:row for row in rows}
    for routine in catalog()['routines']:
        row=by_id.get(routine['id'])
        if row is None:
            row=dict(id=routine['id'],color='#9ab8aa',scale=(.85,1,.85),radius=1,sense_radius=3)
            rows.append(row)
        stops=[dict(x=p[0],z=p[1],wait_s=p[2],activity=p[3] if len(p)>3 else 'TRAVELING')
               for p in routine['stops']]
        row.update(role=routine['role'],route='AUTHORED_ROUTINE',waypoints=stops,
                   x=stops[0]['x'],z=stops[0]['z'],speed=routine['speed'],
                   route_offset_s=routine['offset_s'],activity_day='TRAVELING',
                   route_mode=routine.get('route_mode','LOOP'),
                   allow_promotion=bool(routine.get('allow_promotion',False)))
        if routine.get('name'):row['name']=routine['name']
    return rows


def _box(vertices,indices,center,half_size,pitch,color):
    """Data-only colored box ABI, shared by Blender export and Qt import."""
    cx,cy,cz=center;hx,hy,hz=half_size;s,c=math.sin(pitch),math.cos(pitch)
    faces=[((0,-1,0),[(-hx,-hy,-hz),(hx,-hy,-hz),(hx,-hy,hz),(-hx,-hy,hz)]),
           ((0,1,0),[(-hx,hy,-hz),(-hx,hy,hz),(hx,hy,hz),(hx,hy,-hz)]),
           ((0,0,-1),[(-hx,-hy,-hz),(-hx,hy,-hz),(hx,hy,-hz),(hx,-hy,-hz)]),
           ((0,0,1),[(-hx,-hy,hz),(hx,-hy,hz),(hx,hy,hz),(-hx,hy,hz)]),
           ((-1,0,0),[(-hx,-hy,hz),(-hx,hy,hz),(-hx,hy,-hz),(-hx,-hy,-hz)]),
           ((1,0,0),[(hx,-hy,-hz),(hx,hy,-hz),(hx,hy,hz),(hx,-hy,hz)])]
    for (nx,ny,nz),points in faces:
        base=len(vertices)//40
        for x,y,z in points:
            vertices.extend(struct.pack('<10f',cx+x,cy+y*c-z*s,cz+y*s+z*c,nx,ny*c-nz*s,ny*s+nz*c,*color))
        indices.extend([base,base+1,base+2,base,base+2,base+3])


def mesh_data(kind):
    """Pure world-space mesh data; Blender and the engine consume one source."""
    from backend import game_engine_world as world
    from backend.game_engine_terrain import height_at
    feel=world.ISLAND_LAYOUT_SCALE
    vertices=bytearray();indices=[]
    roads=kind.upper().endswith('ROADS')
    for route in catalog()['roads' if roads else 'fences']:
        points=[(p[0]*feel,p[1]*feel) for p in route['points']]
        for a,b in zip(points,points[1:]):
            dx,dz=b[0]-a[0],b[1]-a[1];length=math.hypot(dx,dz)
            count=max(1,math.ceil(length/(3.0 if roads else 2.5)))
            for n in range(count):
                x,z=a[0]+dx*n/count,a[1]+dz*n/count
                xx,zz=a[0]+dx*(n+1)/count,a[1]+dz*(n+1)/count
                if roads:
                    side_x,side_z=dz/length*route['width_m']/2,-dx/length*route['width_m']/2
                    positions=[(x-side_x,z-side_z),(xx-side_x,zz-side_z),
                               (xx+side_x,zz+side_z),(x+side_x,z+side_z)]
                    base=len(vertices)//40
                    color=(.49,.36,.22,1)
                    for px,pz in positions:
                        vertices.extend(struct.pack('<10f',px,height_at(px,pz)+.10,pz,0,1,0,*color))
                    indices.extend([base,base+1,base+2,base,base+2,base+3])
                else:
                    # Uprights and two rails; terrain slope tilts the rails.
                    color=(.43,.27,.13,1)
                    for px,pz in ((x,z),(xx,zz)):
                        _box(vertices,indices,(px,height_at(px,pz)+.75,pz),(.09,.75,.09),0,color)
                    y0,y1=height_at(x,z),height_at(xx,zz)
                    # Append each rail in a local frame, then rotate into the
                    # saved segment. Normals get the same yaw transformation.
                    for lift in (.5,1.12):
                        start=len(vertices)
                        _box(vertices,indices,(0,0,0),(.065,.07,math.hypot(length/count,y1-y0)/2),
                             -math.atan2(y1-y0,length/count),color)
                        sin_y,cos_y=dx/length,dz/length
                        for offset in range(start,len(vertices),40):
                            v=list(struct.unpack_from('<10f',vertices,offset))
                            vx,vz=v[0],v[2];nx,nz=v[3],v[5]
                            v[0]=(x+xx)/2+vx*cos_y+vz*sin_y
                            v[1]+=(y0+y1)/2+lift
                            v[2]=(z+zz)/2-vx*sin_y+vz*cos_y
                            v[3]=nx*cos_y+nz*sin_y;v[5]=-nx*sin_y+nz*cos_y
                            struct.pack_into('<10f',vertices,offset,*v)
    return vertices,indices


def build_geometry(kind):
    from backend.game_engine_geometry import _build_colored_geometry
    vertices,indices=mesh_data(kind)
    # A valid empty map has no mesh. Returning a null geometry also keeps an
    # exception from crossing a QObject-returning QML slot during creation.
    if not vertices or not indices:return None
    return _build_colored_geometry('gameSandover'+kind.title(),vertices,indices)
