"""Original map feeds over GG's authored geography and canonical live positions.

The region and town catalog is GG content. Original installation DBC art,
exploration masks and POI world-state gates remain a separate corpus.
"""
from __future__ import annotations

import math
import json,re,struct
from functools import lru_cache
from pathlib import Path

from backend import game_engine_planet as planet, game_engine_world_places as places

MAP_ID = 0
UNRESOLVED_IMPORTED_MAP = 0xFFFFFFFF
SCHEMA = 'gg.game-engine.navigation.v1'
MAX_COORD = 2_000_000.


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('Invalid map coordinate')
    value = float(value)
    if not math.isfinite(value) or abs(value) > MAX_COORD:
        raise ValueError('Invalid map coordinate')
    return value


def _rect(left, right, top, bottom):
    left, right = sorted((_number(left), _number(right)))
    bottom, top = sorted((_number(bottom), _number(top)))
    if right <= left or top <= bottom:
        raise ValueError('Empty map bounds')
    return [left, right, top, bottom]


def project(rect, x, z):
    """UV from the displayed map's north-west; off-map points stay absent."""
    left, right, top, bottom = _rect(*rect)
    x, z = _number(x), _number(z)
    if not left <= x <= right or not bottom <= z <= top:
        return None
    return [(x-left)/(right-left), (top-z)/(top-bottom)]


@lru_cache(maxsize=1)
def catalog():
    contract = planet.map_contract()
    bounds = contract['bounds_m']
    world = _rect(bounds['min_x'], bounds['max_x'], bounds['max_z'], bounds['min_z'])
    continents = []
    landmarks = []
    for index, region in enumerate(contract['landmasses'], 1):
        coast = planet.coastline_points(region['id'], segments=96)
        rect = _rect(min(p[0] for p in coast), max(p[0] for p in coast),
                     max(p[1] for p in coast), min(p[1] for p in coast))
        uv0, uv1 = project(world, rect[0], rect[2]), project(world, rect[1], rect[3])
        area_id = 0x470000 + index * 128
        zones = [dict(name=region['name'], id=region['id'], area_id=area_id,
                      map_file='GG'+region['id'], rect=rect)]
        for place in places.catalog()['places']:
            if place['region_id'] != region['id']:
                continue
            radius = max(100., min(500., float(place.get('clearing_m', 100)) * 2))
            x, z = place['x'], place['z']
            # Zones intersect their owning continent's chart window.
            town_rect = _rect(max(rect[0], x-radius), min(rect[1], x+radius),
                              min(rect[2], z+radius), max(rect[3], z-radius))
            zones.append(dict(name=place['name'], id=place['id'],
                              area_id=area_id+len(zones), map_file='GG'+place['id'], rect=town_rect))
            landmarks.append(dict(name=place['name'], description=place['kind'], map=MAP_ID,
                                  position=[x, z], icons=[6, 6, 6]))
        continents.append(dict(name=region['name'], id=region['id'], map=MAP_ID,
                               map_file='GG'+region['id'], rect=rect,
                               world_rect=[uv0[0], uv0[1], uv1[0], uv1[1]], zones=zones))
    return dict(world_rect=world, continents=continents, landmarks=landmarks,
                source='GG_AUTHORED_GEOGRAPHY', revision=contract['map_revision'])


def navigation(snapshot, *, ui=None, ping=None, atlas=None, indoors=None):
    """Build a bounded feed without changing the simulation or persisting UI state."""
    player = snapshot.get('player') or {}
    x, z = _number(player.get('x', 0)), _number(player.get('z', 0))
    descriptor = player.get('world_map') or snapshot.get('world_map')
    direct = []
    map_id, instance_id = MAP_ID, 0
    player_zone = [0, 0]
    direct_id = None
    chosen_catalog=catalog()
    wow=False
    imported=player.get('engine_world')
    if isinstance(descriptor, dict) and descriptor.get('kind') == 'INSTANCE':
        map_id, instance_id = descriptor.get('id'), descriptor.get('instance_id', 0)
        if type(map_id) is not int or not 1 <= map_id < 2**32 or type(instance_id) is not int or instance_id < 0:
            raise ValueError('Invalid instance map identity')
        bounds = descriptor.get('bounds', {})
        rect = _rect(*(bounds.get(k) for k in ('left', 'right', 'top', 'bottom')))
        direct_id = map_id
        direct = [dict(id=map_id, map=map_id, area_id=map_id,
                       name=str(descriptor.get('name', 'GG Instance'))[:128], map_file='GGInstance'+str(map_id), rect=rect)]
    elif isinstance(imported,dict) and isinstance(atlas,dict) and atlas.get('selected_map'):
        chosen_catalog=atlas['catalog'];direct=atlas['direct'];wow=True
        map_id=atlas['selected_map']['id'];instance_id=int(imported.get('instance_id',0))
        area=next((a for a in atlas['areas'] if a['id']==imported.get('area_id')),None)
        top=area.get('top_zone') if area else None
        for ci,c in enumerate(chosen_catalog['continents'],1):
            if c['map']!=map_id:continue
            zi=next((i for i,a in enumerate(c['zones'],1) if a['area_id']==top),0)
            player_zone=[ci,zi];break
        else:direct_id=next((a['id'] for a in direct if a['map']==map_id),None)
    elif isinstance(imported,dict):
        # A mounted map name alone is not a Map.dbc identity or atlas rect.
        # Never reinterpret its coordinates as Sandover geography.
        map_id=UNRESOLVED_IMPORTED_MAP
        chosen_catalog=dict(source='UNAVAILABLE_ORIGINAL_DBC',coordinate_frame='WOW',revision=1,
            world_rect=catalog()['world_rect'],continents=[],landmarks=[])
    else:
        region = planet.region_at(x, z) or {}
        for ci, continent in enumerate(catalog()['continents'], 1):
            if continent['id'] != region.get('id'):
                continue
            zi = 1
            # Towns are resolved by the actual authored bounds, in catalog order.
            for index, zone in enumerate(continent['zones'][1:], 2):
                if project(zone['rect'], x, z) is not None:
                    zi = index
                    break
            player_zone = [ci, zi]
            break
    services = player.get('client_controls', {}).get('services', {})
    group = services.get('group', {})
    origin=atlas.get('origin',[0.,0.,0.]) if wow else [0.,0.,0.]
    def position(px,pz):return [_number(px)+origin[0],origin[1]-_number(pz)] if wow else [_number(px),_number(pz)]

    def point(row, *, default_map=UNRESOLVED_IMPORTED_MAP if wow else MAP_ID):
        if not isinstance(row, dict) or 'x' not in row or 'z' not in row:
            return None
        row_map, row_instance = row.get('map_id', default_map), row.get('instance_id', 0)
        if type(row_map) is not int or type(row_instance) is not int:
            return None
        return dict(map=row_map, instance=row_instance, position=position(row['x'],row['z']))

    life = services.get('lifecycle', {})
    corpse = point(life.get('position')) if life.get('dead') else None
    roster = group.get('roster', [])[:40]
    members = []
    for row in roster:
        if row.get('id') == 'player':
            members.append(dict(map=map_id, instance=instance_id, position=position(x,z)))
        else:
            members.append(point(row) if row.get('online') else None)
    party = members[1:5] if roster and roster[0].get('id') == 'player' else members[:4]
    yaw = _number(player.get('yaw', 0))
    from backend.game_engine_adapter_world import environment
    if indoors is None:indoors=environment(snapshot)['indoors']
    ping_uv=[0.,0.]
    if ping is not None and ui is not None and ping.get('owner') is ui:
        from backend.game_engine_adapter_minimap import ping_position
        zoom=ui.evaluate('return Minimap and Minimap:GetZoom() or 0')[0]
        value=ping_position(snapshot,ping,zoom,zoom,indoors,atlas=atlas)
        if value is not None:ping_uv=value
    explored=player.get('client_controls',{}).get('local_client',{}).get('explored_zones',[0]*64)
    if not isinstance(explored,list) or len(explored)!=64 or any(type(v)is not int or not 0<=v<2**32 for v in explored):raise ValueError('Invalid exploration bank')
    if wow:
        # Discovery and live world-state gates precede each original level flag.
        areas={a['id']:a for a in atlas['areas']};states=player.get('client_controls',{}).get('world_states',{})
        landmarks=[]
        for poi in atlas.get('pois',[])[:2048]:
            area=areas.get(poi['area']);bit=area.get('explore_bit',0) if area else 0
            if 0<poi['area']<2**31 and area and area['exploration_level']>=0 and (bit>=2048 or not explored[bit//32] & 1<<(bit%32)):continue
            if poi['world_state'] and not states.get(str(poi['world_state']),0):continue
            flags=poi['flags'];icon=poi['icon']
            if not 0<=icon<64:continue
            icons=[icon if flags&0x18==0x18 else None,icon if flags&8 else None,(icon if flags&0x80 else 15) if flags&4 else None]
            landmarks.append(dict(name=poi['name'][:128],description=poi['description'][:128],map=poi['map'],position=poi['position'],icons=icons))
        chosen_catalog={**chosen_catalog,'landmarks':landmarks}
    return dict(schema=SCHEMA, catalog=chosen_catalog, direct=direct, player_zone=player_zone,
                player_direct=direct_id, map=map_id, instance=instance_id, player=position(x,z),
                facing=yaw-math.pi/2 if wow else -yaw, indoors=indoors, ping=ping_uv, explored=explored, corpse=corpse, party=party,
                raid=members if group.get('raid') else [])


def imported_atlas(stream):
    """Read once per mounted stream, including a bounded memo of missing data."""
    config=getattr(stream,'config',None);cache=getattr(stream,'cache',None)
    if not isinstance(config,dict) or cache is None or not cache.archive_source:return None
    origin=config.get('origin',[0.,0.,0.]);key=(id(config),str(cache.archive_source),config['map'],tuple(origin))
    if getattr(stream,'_gg_navigation_key',None)==key:return getattr(stream,'_gg_navigation_atlas',None)
    stream._gg_navigation_key=key;stream._gg_navigation_atlas=None
    try:
        value=cache._reader().request('world_navigation',map_name=config['map'],timeout=3)
        if value.get('schema')!='gg.engine.imported-navigation.v1' or not value.get('selected_map'):raise ValueError('Mounted directory has no Map.dbc identity')
        if not isinstance(origin,list) or len(origin)!=3:raise ValueError('Mounted world has invalid origin')
        value['origin']=[_number(n) for n in origin]
        stream._gg_navigation_atlas=value;stream._gg_navigation_error=''
    except (OSError,ValueError,RuntimeError,TimeoutError) as exc:stream._gg_navigation_error=str(exc)[:240]
    return stream._gg_navigation_atlas


def explore_area(runtime,row):
    """Award a discovery bit only for the actual loaded area under this body."""
    area_id=row.get('area_id');stream=getattr(runtime,'_engine_world',None)
    if type(area_id)is not int or not 0<area_id<2**32 or stream is None:raise ValueError('EXPLORATION_AREA_UNAVAILABLE')
    atlas=getattr(stream,'_gg_navigation_atlas',None)
    if not isinstance(atlas,dict) or not atlas.get('selected_map'):raise ValueError('EXPLORATION_CATALOG_UNAVAILABLE')
    if str(getattr(stream,'config',{}).get('map','')).lower()!=atlas['selected_map']['directory'].lower():raise ValueError('EXPLORATION_CATALOG_MISMATCH')
    current=stream.query(runtime._x[0],runtime._y[0],runtime._z[0])
    area=next((a for a in atlas['areas'] if a['id']==area_id),None)
    if not current.get('loaded') or current.get('area_id')!=area_id or not area or area['map']!=atlas['selected_map']['id']:raise ValueError('EXPLORATION_AREA_MISMATCH')
    bit=area['explore_bit']
    if type(bit)is not int or not 0<=bit<2048:raise ValueError('EXPLORATION_BIT_UNAVAILABLE')
    bank=runtime._local_client['explored_zones'];word,offset=divmod(bit,32)
    if bank[word] & 1<<offset:return []
    bank[word] |= 1<<offset
    return [{'event':'WORLD_MAP_UPDATE','args':[]}]


def presentation_imported_navigation(presentation,snapshot,lua):
    """One host hook: cached catalogs, canonical feeds and bounded discovery."""
    stream=getattr(presentation.parent(),'_engine_world_stream',None)
    atlas=imported_atlas(stream) if stream is not None else None
    if stream is not None:minimap_translate(stream)
    inside=None
    if stream is not None and hasattr(stream,'pages') and snapshot.get('player',{}).get('engine_world'):
        inside=minimap_interior(stream,snapshot) is not None
    feed=navigation(snapshot,ui=lua,ping=getattr(presentation,'_minimap_ping',None),atlas=atlas,indoors=inside)
    player=snapshot.get('player',{});imported=player.get('engine_world') or {}
    if atlas and lua is presentation.lua and imported.get('world_loaded'):
        area_id=imported.get('area_id');area=next((a for a in atlas['areas'] if a['id']==area_id),None)
        bit=area.get('explore_bit') if area else None
        bank=feed['explored'];key=(id(lua),id(stream),area_id)
        if type(bit)is int and 0<=bit<2048 and not bank[bit//32] & 1<<(bit%32) and getattr(presentation,'_navigation_explore_attempt',None)!=key:
            from PySide6.QtCore import QTimer
            presentation._navigation_explore_attempt=key
            def discover():
                if presentation.lua is not lua or getattr(presentation.parent(),'_engine_world_stream',None)is not stream:return
                call=getattr(presentation.parent(),'gameEngineClientControl',None)
                if not callable(call):return
                try:
                    result=call(json.dumps({'kind':'local','op':'ExploreArea','area_id':area_id}))
                    if isinstance(result,str):result=json.loads(result)
                    if isinstance(result,dict) and result.get('error'):presentation._error(ValueError(result['error']))
                    presentation.last_update=0
                except (ValueError,RuntimeError,TypeError) as exc:presentation._error(exc)
            QTimer.singleShot(0,discover)
    return feed


def install(ui):
    """Install the GG map only when no loaded addon supplied WorldMapFrame."""
    ui.execute((Path(__file__).with_suffix('.lua')).read_text())
    ui.request('addon_bindings', name='GGNavigation', source='<Bindings><Binding name="GGTOGGLEWORLDMAP">ToggleWorldMap()</Binding></Bindings>')
    ui.execute('if GetBindingAction("M")=="" then SetBinding("M","GGTOGGLEWORLDMAP") end')


from backend.game_engine_adapter_navigation_art import navigation_texture_assets,atlas_texture


def parse_minimap_translate(blob):
    """Original CRLF/LF/tab grammar, with bounded safe hashed filenames."""
    if not isinstance(blob,bytes) or len(blob)>4*1024*1024:raise ValueError('Minimap translate capacity exceeded')
    result={};fold=str.maketrans('ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz')
    for raw in blob.decode('utf-8',errors='replace').split('\n'):
        line=raw.rstrip('\r').strip()
        if not line or line.startswith('dir:') or '\t' not in line:continue
        logical,hashed=line.split('\t',1)
        if len(logical)>512 or any(ord(c)<32 for c in logical) or '/' in logical or any(p in ('','.','..') for p in logical.split('\\')) or not re.fullmatch(r'[0-9a-fA-F]{32}\.blp',hashed,re.I):raise ValueError('Invalid minimap translate row')
        result[logical.translate(fold)]=hashed
        if len(result)>16384:raise ValueError('Minimap translate row capacity exceeded')
    return result


def minimap_translate(stream):
    """The mounted catalog, including one cached miss; never scan per frame."""
    config=getattr(stream,'config',None);cache=getattr(stream,'cache',None)
    if not isinstance(config,dict) or cache is None or not cache.archive_source:return None
    key=(id(config),str(cache.archive_source))
    if getattr(stream,'_gg_minimap_translate_key',None)==key:return getattr(stream,'_gg_minimap_translate',None)
    stream._gg_minimap_translate_key=key;stream._gg_minimap_translate=None
    try:
        result=parse_minimap_translate(cache.archive_read('textures/Minimap/md5translate.trs'))
        stream._gg_minimap_translate=result;stream._gg_minimap_translate_error=''
    except (OSError,ValueError,RuntimeError,TimeoutError) as exc:stream._gg_minimap_translate_error=str(exc)[:240]
    return stream._gg_minimap_translate


def minimap_tiles(stream,snapshot,extent):
    """Outdoor source quads in the original ADT north/west axis law."""
    config=getattr(stream,'config',None);player=snapshot.get('player',{})
    if not isinstance(config,dict) or not player.get('engine_world'):return []
    from backend.game_engine_adapter_world import environment
    inside=minimap_interior(stream,snapshot) is not None if hasattr(stream,'pages') else environment(snapshot)['indoors']
    if inside:return []
    table=minimap_translate(stream)
    if table is None:return []
    from backend.game_engine_adapter_streaming import TILE,tile_at
    x,z=_number(player.get('x',0)),_number(player.get('z',0));extent=_number(extent)
    if not 0<extent<=233.334:raise ValueError('Invalid original minimap radius')
    origin=config['origin'];wx,wy=x+origin[0],origin[1]-z
    lo=tile_at(x+extent,z-extent,origin);hi=tile_at(x-extent,z+extent,origin)
    result=[]
    for ty in range(lo[1],hi[1]+1):
        for tx in range(lo[0],hi[0]+1):
            logical=f"{config['map']}\\map{tx}_{ty}.blp".lower();hashed=table.get(logical)
            if hashed is None:continue
            north,west=(32-ty)*TILE,(32-tx)*TILE
            left=.5+(wy-west)/(2*extent);top=.5+(wx-north)/(2*extent);size=TILE/(2*extent)
            if left>=1 or top>=1 or left+size<=0 or top+size<=0:continue
            result.append(dict(path='textures/Minimap/'+hashed,rect=[left,top,size,size],tile=[tx,ty]))
    if len(result)>4:raise ValueError('Original minimap tile window capacity exceeded')
    return result


def _wmo_minimap_stem(stream,page):
    """Recover the logical mounted path, never guess it from a basename."""
    path=Path(page.path);archive=getattr(stream.cache,'archive_directory',None)
    roots=[Path(archive.name)] if archive is not None else []
    from backend.game_engine_adapter_formats import PROJECT
    roots.append(PROJECT/'qml')
    for root in roots:
        if not path.is_relative_to(root):continue
        logical=path.relative_to(root).as_posix().replace('/','\\').lower()
        if 'world\\' in logical and logical.endswith('.wmo'):return logical.split('world\\',1)[1][:-4]
    return None


def minimap_model_bounds(page):
    """Read the same retained root's original MOGI once, before transforms.

    Subtracting distant transformed Float32 corners can cross a bake grid's
    power-of-two threshold. The original raw bounding boxes avoid that loss.
    The memo retains only bbox numbers, not another world or source-byte cache.
    """
    if hasattr(page,'_gg_minimap_model_bounds'):
        if page._gg_minimap_model_bounds is None:raise ValueError(page._gg_minimap_bounds_error)
        return page._gg_minimap_model_bounds
    page._gg_minimap_model_bounds=None
    try:
        path=Path(page.path)
        if path.stat().st_size>16*1024*1024:raise ValueError('Indoor minimap WMO root capacity exceeded')
        source=path.read_bytes();offset=0;groups=len(page.metadata['groups'])
        if groups>4096:raise ValueError('Indoor minimap group directory capacity exceeded')
        while offset+8<=len(source):
            tag,size=struct.unpack_from('<4sI',source,offset);offset+=8
            if offset+size>len(source):raise ValueError('Truncated indoor minimap WMO root')
            if tag==b'IGOM':
                if size%32 or size<groups*32:raise ValueError('Incomplete original indoor minimap group bounds')
                result=[]
                for gi in range(groups):
                    bounds=struct.unpack_from('<6f',source,offset+gi*32+4)
                    if any(not math.isfinite(n) for n in bounds) or any(bounds[k]>bounds[k+3] for k in range(3)):raise ValueError('Invalid original indoor minimap bounds')
                    result.append(bounds)
                page._gg_minimap_model_bounds=tuple(result);return page._gg_minimap_model_bounds
            offset+=size
        raise ValueError('Original indoor minimap group bounds unavailable')
    except (OSError,ValueError) as exc:
        page._gg_minimap_bounds_error=str(exc)[:240];raise ValueError(page._gg_minimap_bounds_error) from exc


def minimap_interior(stream,snapshot):
    """Original feet-face indoor gate and lifted down-ray room seed.

    This uses the loaded page's actual collision, not render-bounds containment.
    A 0x40-only group is indoors here; 0x8 excludes it. Terrain races both rays.
    """
    player=snapshot.get('player',{});pages=getattr(stream,'pages',{})
    if not player.get('engine_world') or not pages:return None
    body=tuple(_number(player.get(k,0.)) for k in ('x','y','z'))
    key=(getattr(stream,'revision',0),tuple((k,id(p)) for k,p in pages.items()),body)
    if getattr(stream,'_gg_minimap_interior_key',None)==key:return stream._gg_minimap_interior
    stream._gg_minimap_interior_key=key;stream._gg_minimap_interior=None
    def terrain(eye):
        heights=[p.surface.down_ray(*eye,props=False)[0] for p in pages.values() if not p.metadata.get('groups') and not p.closed]
        return max((h for h in heights if h is not None),default=None)
    feet=(body[0],body[1]+.1,body[2]);floor=terrain(feet)
    claim=False
    for page in pages.values():
        groups=page.metadata.get('groups',[])
        if not groups or page.closed:continue
        height,row=page.surface.down_ray(*feet,props=False)
        gi=row.get('group') if row else None
        if type(gi)is int and 0<=gi<len(groups) and not groups[gi]['flags']&8 and groups[gi].get('wmo_id',0) and height is not None and feet[1]-height<=1000 and (floor is None or height>=floor):claim=True;break
    if not claim:return None
    from backend.game_engine_adapter_rooms import camera_seeds
    eye=(body[0],body[1]+1.7,body[2]);floor=terrain(eye)
    for page in pages.values():
        groups=page.metadata.get('groups',[])
        if not groups or page.closed or not groups[0].get('wmo_id',0):continue
        seed,_=camera_seeds(page,eye,floor)
        if seed is None:continue
        stem=_wmo_minimap_stem(stream,page)
        if stem is not None:
            stream._gg_minimap_interior=dict(page=page,seed=seed,stem=stem,body=body)
            return stream._gg_minimap_interior
    return None


def _minimap_group_corners(group):
    corners=group.get('corners')
    if not isinstance(corners,list) or len(corners)!=8 or any(not isinstance(p,list) or len(p)!=3 for p in corners):raise ValueError('Original indoor minimap requires ordered group corners')
    return [tuple(_number(n) for n in p) for p in corners]


def _minimap_group_axes(group,bounds=None,reference=None):
    points=_minimap_group_corners(group);axes=[];lengths=[]
    for index in (1,2,4):
        edge=[points[index][k]-points[0][k] for k in range(3)];length=math.sqrt(sum(n*n for n in edge));lengths.append(length)
        axes.append(tuple(n/length for n in edge) if length>1e-7 else None)
    if reference is not None:axes=[axis if axis is not None else reference[i] for i,axis in enumerate(axes)]
    for i in range(3):
        if axes[i] is not None:continue
        a,b=axes[(i+1)%3],axes[(i+2)%3]
        if a is not None and b is not None:axes[i]=(a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])
    if any(axis is None for axis in axes):raise ValueError('Degenerate indoor minimap group grid')
    if bounds is not None:lengths=[struct.unpack('<f',struct.pack('<f',bounds[k+3]-bounds[k]))[0] for k in range(3)]
    return points,axes,lengths


def minimap_group_selection(context,extent):
    """Original absolute-ID portal flood: XY gates recursion; Z gates portals."""
    page=context['page'];groups=page.metadata['groups'];body=context['body'];seed=context['seed']
    if any(group.get('id')!=i for i,group in enumerate(groups)):raise ValueError('Indoor minimap group directory must retain absolute IDs')
    lo=[body[0]-2*extent,body[1]-1.5*extent,body[2]-2*extent];hi=[body[0]+2*extent,body[1]+extent,body[2]+2*extent]
    portals=page.metadata.get('portals') or {};refs=portals.get('refs',[]);infos=portals.get('infos',[])
    visited=set();stack=[seed];drawable=[]
    while stack:
        gi=stack.pop()
        if gi in visited or not 0<=gi<len(groups):continue
        visited.add(gi);group=groups[gi]
        if group['flags']&8:continue
        corners=_minimap_group_corners(group)
        if any(min(p[k] for p in corners)>hi[k] or max(p[k] for p in corners)<lo[k] for k in (0,2)):continue
        if not group['flags']&0x88:drawable.append(gi)
        start=group['portal_start'];end=min(start+group['portal_count'],len(refs))
        for ref in refs[start:end]:
            nb=ref['group'];portal=ref['portal']
            if nb==0xffff or not 0<=nb<len(groups) or nb in visited or not 0<=portal<len(infos):continue
            poly=infos[portal]['points']
            if not poly:continue
            # Equivalent to ANDing the original six-plane outcodes.
            if not any(all(p[k]<lo[k] for p in poly) or all(p[k]>hi[k] for p in poly) for k in range(3)):stack.append(nb)
    return drawable


def _minimap_axis_grid(extent):
    px=max(1,math.ceil(extent/.5));px=max(32,min(256,1<<(px-1).bit_length()))
    return max(1,math.ceil(extent/128)),px*.5


def minimap_indoor_tiles(stream,context,extent):
    """Actual hashed WMO quads for the original 256², 1.5-radius target.

    U increases model X; V decreases model Y. Groups sort by model Z relative
    to the body, with the seed last. Grid cells bleed one yard at outer edges
    and stretch by W/(W-1), with W taken from the original .5-yard bake grid.
    """
    extent=_number(extent)
    if not 0<extent<=150:raise ValueError('Invalid original indoor minimap radius')
    table=minimap_translate(stream)
    if table is None:return []
    groups=context['page'].metadata['groups'];bounds=minimap_model_bounds(context['page']);body=context['body'];seed=context['seed'];units=128/(1.5*extent)
    drawable=minimap_group_selection(context,extent)
    if not drawable:return []
    reference=None
    for gi in [seed]+[g for g in range(len(groups)) if g!=seed]:
        try:reference=_minimap_group_axes(groups[gi])[1];break
        except ValueError:continue
    if reference is None:raise ValueError('Indoor minimap placement axes unavailable')
    def sort_key(gi):
        corners,axes,_=_minimap_group_axes(groups[gi],reference=reference);mid=[(corners[0][k]+corners[7][k])*.5 for k in range(3)]
        return math.inf if gi==seed else sum((mid[k]-body[k])*axes[2][k] for k in range(3))
    result=[];scanned=0
    for gi in sorted(drawable,key=sort_key):
        corners,axes,lengths=_minimap_group_axes(groups[gi],bounds[gi],reference);nx,twx=_minimap_axis_grid(lengths[0]);ny,twy=_minimap_axis_grid(lengths[1])
        scanned+=nx*ny
        if scanned>16384:raise ValueError('Indoor minimap grid capacity exceeded')
        # Match the original atan2 law even for a vertical model-X placement.
        rotation=math.atan2(-axes[0][0],axes[0][2])
        direction=[math.cos(rotation),math.sin(rotation)]
        for col in range(nx):
            for row in range(ny):
                x0=col*twx-(1 if col==0 else 0);x1=(col+1)*twx+(1 if col+1==nx else 0)
                y0=row*twy-(1 if row==0 else 0);y1=(row+1)*twy+(1 if row+1==ny else 0)
                local=[(x0+x1)*.5,(y0+y1)*.5,lengths[2]*.5]
                mid=[corners[0][k]+sum(axes[j][k]*local[j] for j in range(3)) for k in range(3)]
                centre=[128+(mid[2]-body[2])*units,128-(mid[0]-body[0])*units]
                if math.hypot(centre[0]-128,centre[1]-128)>128+max(twx,twy)*units:continue
                key=f"{context['stem']}_{gi:03}_{col:02}_{row:02}.blp";hashed=table.get(key)
                if hashed is None:continue
                wx,wy=twx/.5,twy/.5
                result.append(dict(path='textures/Minimap/'+hashed,group=gi,tile=[col,row],center=centre,
                    size=[(x1-x0)*units*wx/(wx-1),(y1-y0)*units*wy/(wy-1)],direction=direction))
                if len(result)>1024:raise ValueError('Indoor minimap composition capacity exceeded')
    return result
