"""Retained map objects sharing the camera's terrain far plane.

The game reads saved placements, not a tree scatter algorithm. Sector/species
instance buffers are compiled offline and uploaded once, under a frame budget.
Three shared meshes use Qt's native instance distance filters; the placements
and GPU table persist across camera moves and detail changes.
"""
from __future__ import annotations

import gzip
import io
import json
import math
import time
from pathlib import Path

from PySide6.QtCore import QAbstractListModel, QByteArray, QModelIndex, Qt, QTimer

from backend.game_engine_ecology import TREE_SPECIES
from backend.game_engine_ecology_render import FloraInstances, FloraRenderCache, instance_bytes
from backend.game_engine_native_world import SectorIndex

ASSETS = Path(__file__).resolve().parents[1]/'qml/assets/authored/world/trees'
UPLOAD_BUDGET_S = .003
UPLOAD_BATCH_CAP = 2
CACHE_GRACE_S = 30


def sector_in_view(sector, view, padding=None):
    """Conservative sphere/frustum test; Qt clips to the exact camera planes."""
    origin, forward, right, up, tangent, aspect, far = view
    if padding is None:padding=192+far*.06
    low, high = sector['min'], sector['max']
    center = tuple((a+b)*.5 for a,b in zip(low,high))
    radius = math.sqrt(sum(((b-a)*.5)**2 for a,b in zip(low,high)))+padding
    delta = tuple(a-b for a,b in zip(center,origin))
    depth = sum(a*b for a,b in zip(delta,forward))
    side = abs(sum(a*b for a,b in zip(delta,right)))
    vertical = abs(sum(a*b for a,b in zip(delta,up)))
    tx = tangent*aspect
    return (depth >= -radius and depth <= far+radius
            and side <= max(0,depth)*tx+radius*math.sqrt(1+tx*tx)
            and vertical <= max(0,depth)*tangent+radius*math.sqrt(1+tangent*tangent))


def sector_in_range(sector, view, padding=256):
    """Keep a full camera-independent neighbourhood resident.

    A perspective far plane includes its corners beyond the scalar far
    distance. Use their enclosing sphere, plus movement/boom hysteresis, so
    rotation cannot remove a sector or create another native upload queue.
    Qt's camera still clips the already resident instances to exact planes.
    """
    origin,_,_,_,tangent,aspect,far=view
    distance=math.sqrt(sum(max(a-o,0,o-b)**2 for o,a,b in zip(origin,sector['min'],sector['max'])))
    return distance <= far*math.sqrt(1+tangent*tangent*(1+aspect*aspect))+padding


def affected_sectors(document, sector_m):
    """Include the falloff of old cell edits and all brush stamps."""
    from backend.game_engine_terrain import CELL_SIZE, _coords_from_key
    result=set()
    bounds=[]
    for key,row in document.get('cells',{}).items():
        if not isinstance(row,dict):continue
        cx,cz=_coords_from_key(key)
        bounds.append(((cx+.5)*CELL_SIZE,(cz+.5)*CELL_SIZE,CELL_SIZE*1.25))
    bounds.extend((float(s['center_x_m']),float(s['center_z_m']),float(s['radius_m']))
                  for s in document.get('stamps',[]))
    for x,z,radius in bounds:
        for cx in range(math.floor((x-radius)/sector_m),math.floor((x+radius)/sector_m)+1):
            for cz in range(math.floor((z-radius)/sector_m),math.floor((z+radius)/sector_m)+1):
                result.add(f'{cx}:{cz}')
    return result


class WorldTreeModel(QAbstractListModel):
    ROLE_NAMES = {Qt.UserRole+1:b'treeGeometry',Qt.UserRole+2:b'treeInstances',
                  Qt.UserRole+3:b'treeLod',Qt.UserRole+4:b'treeCount',Qt.UserRole+5:b'treeKey',
                  Qt.UserRole+6:b'treeResident'}

    def __init__(self,parent=None,*,assets=ASSETS,catalog_name='world-trees.catalog.json',schema='gg.world-tree-catalog.v1'):
        super().__init__(parent)
        self.assets=assets
        catalog_path=assets/catalog_name
        from backend import game_engine_planet as planet
        from backend.game_engine_terrain import DEFAULT_WORLD_SEED
        self.assets_available=catalog_path.is_file()
        # Private authored catalogs are optional in an exported desktop.
        # Existing malformed or stale catalogs still fail their validation.
        self.catalog=json.loads(catalog_path.read_text(encoding='utf-8')) if self.assets_available else dict(
            schema=schema,instance_stride=80,planet_id=planet.PLANET_ID,
            map_revision=planet.MAP_REVISION,seed=DEFAULT_WORLD_SEED,sectors={},meshes=[],
            source='NOT_INSTALLED',tree_count=0,place_count=0,object_count=0,sector_m=1024)
        if self.catalog['schema']!=schema or self.catalog['instance_stride']!=80:
            raise ValueError('invalid world tree catalog')
        if (self.catalog['planet_id']!=planet.PLANET_ID or self.catalog['map_revision']!=planet.MAP_REVISION
                or self.catalog['seed']!=DEFAULT_WORLD_SEED):
            raise ValueError('world tree catalog needs rebuilding for this map')
        self.file=(assets/self.catalog.get('data_file','world-trees.instances')).open('rb') if self.assets_available else io.BytesIO()
        self.destroyed.connect(lambda:self.file.close())
        self._indexed_sectors=self.catalog['sectors']
        self._sector_index=SectorIndex(self._indexed_sectors)
        index=self._sector_index
        self.destroyed.connect(lambda:index.close())
        species=self.catalog.get('meshes',TREE_SPECIES)
        self.meshes=FloraRenderCache(self,assets=assets if schema!='gg.world-tree-catalog.v1' else Path(__file__).resolve().parents[1]/'qml/assets/authored/flora',
                                    keys=tuple(f'{s}:{lod}' for s in species for lod in (0,1,2)),
                                    max_vertices=200000 if schema!='gg.world-tree-catalog.v1' else 10000)
        self.rows=[];self.cached={};self.wanted={};self.pending=[];self.signature=None
        self.document={};self.edited=set();self.edit_job=None
        self.upload_ticks=0;self.max_upload_ms=0.;self.max_batches_per_tick=0
        self.max_selection_ms=0.
        self.timer=QTimer(self);self.timer.setInterval(16);self.timer.timeout.connect(self.drain)
        self.expiry_timer=QTimer(self);self.expiry_timer.setInterval(1000)
        self.expiry_timer.timeout.connect(self._expire);self.expiry_timer.start()

    def roleNames(self):return self.ROLE_NAMES
    def rowCount(self,parent=QModelIndex()):return 0 if parent.isValid() else len(self.rows)
    def data(self,index,role=Qt.DisplayRole):
        if not index.isValid() or not 0<=index.row()<len(self.rows):return None
        row=self.rows[index.row()];entry=self.cached[row['base']]
        return {Qt.UserRole+1:entry['geometries'][row['lod']],Qt.UserRole+2:entry['table'],
                Qt.UserRole+3:row['lod'],Qt.UserRole+4:entry['count'],Qt.UserRole+5:row['key'],
                Qt.UserRole+6:row['key'] in self.wanted}.get(role)

    def set_terrain(self,document):
        new=affected_sectors(document,self.catalog['sector_m'])
        changed=new|self.edited
        self.document=document;self.edited=new;self.edit_job=None;self.signature=None
        for i in reversed(range(len(self.rows))):
            if self.rows[i]['sector'] in changed:self._remove(i)
        for key,entry in list(self.cached.items()):
            if entry['sector'] in changed:
                entry['table'].deleteLater();del self.cached[key]

    def _remove(self,index):
        self.beginRemoveRows(QModelIndex(),index,index);self.rows.pop(index);self.endRemoveRows()

    def set_view(self,view,profile='PS2_CLASSIC'):
        editor = getattr(self,"asset_editor",None)
        if editor is not None:
            editor.refresh_native(self)
        origin,forward,right,up,tangent,aspect,far=view
        # Residency depends on travel/range, never the camera's heading or
        # pitch. Native frustum/instance LOD filters handle camera turns.
        # A boom rotates by at most 12m without changing its residency anchor.
        signature=(tuple(math.floor((v+32)/64) for v in origin),tangent,aspect,
                   math.ceil(far/128),profile)
        if signature==self.signature:return
        started=time.perf_counter()
        self.signature=signature
        near,mid=(128,512) if profile=='POTATO' else (256,1024)
        wanted={}
        sectors=self.catalog['sectors']
        selected=self._sector_index.select(view,self.catalog.get('residency_padding_m',256),
                                          allowed=sectors if sectors is not self._indexed_sectors else None)
        for sector,distance in selected:
            meta=sectors[sector]
            for species,group in meta['groups'].items():
                base=sector+'/'+species
                # Qt filters individual instances by camera distance. Only
                # sectors that can contain a near/mid instance get those
                # extra models; distant sectors use one cheap shared mesh.
                lods=[2]+([1] if distance<mid+192 else [])+([0] if distance<near+192 else [])
                if self.catalog.get('single_lod'):lods=[0]
                if species.startswith('road-'):
                    # A kilometre-wide road page's instance origin is not
                    # the distance to the road under the player's feet.
                    # Keep its ground-following mesh; camera frustum/range
                    # still clip it. Origin-based LOD makes nearby paving
                    # use the coarse far mesh and intersect the terrain.
                    lods=[0]
                for lod in lods:
                    # Four actual near silhouettes share one coarse far table.
                    # This preserves the distant-world draw-call budget instead
                    # of multiplying every horizon sector by four.
                    choices=group.get('variants',()) if lod<2 else ()
                    if lod==0 and 'near_variants' in group:choices=group['near_variants']
                    if lod==1 and group.get('shared_mid'):choices=()
                    if not choices:choices=[dict(offset=group['offset'],count=group['count'],mesh_species=species)]
                    for choice in choices:
                        if not choice['count']:continue
                        if 'chunk' in choice or choice.get('near_distance_bounds'):
                            d=math.sqrt(sum(max(a-o,0,o-b)**2 for o,a,b in zip(origin,choice['min'],choice['max'])))
                            if d>near+64:continue
                        local=base+('/v'+str(choice['variant']) if 'variant' in choice else '')
                        if 'chunk' in choice:local+='/c'+ '_'.join(map(str,choice['chunk']))
                        key=local+'@'+str(lod)
                        wanted[key]=dict(base=local,sector=sector,species=species,lod=lod,distance=distance,**choice)
        old_wanted=set(self.wanted)
        old_bases={s['base'] for s in self.wanted.values()}
        new_bases={s['base'] for s in wanted.values()}
        for base in old_bases-new_bases:
            if base in self.cached:self.cached[base]['unused_since']=time.monotonic()
        self.wanted=wanted
        # Keep the Qt scene node attached when a sector leaves render range.
        # Detaching the last Model can invalidate Qt's cached instancing GPU
        # resource even though the Python buffer/count stays intact. Invisible
        # retained nodes do no visual work and reappear without reconstruction.
        changed=[i for i,row in enumerate(self.rows)
                 if (row['key'] in wanted)!=(row['key'] in old_wanted)]
        if changed:
            self.dataChanged.emit(self.index(changed[0]),self.index(changed[-1]),[Qt.UserRole+6])
        active={row['key'] for row in self.rows}
        self.pending=sorted((key for key in wanted if key not in active),key=lambda k:(wanted[k]['distance'],wanted[k]['lod'],k))
        if self.edit_job is not None and (not self.pending or self.edit_job[0]!=self.pending[0]):self.edit_job=None
        if self.pending:self.timer.start()
        else:self.timer.stop()
        self._expire()
        self.max_selection_ms=max(self.max_selection_ms,(time.perf_counter()-started)*1000)

    def _expire(self):
        now=time.monotonic()
        wanted_bases={s['base'] for s in self.wanted.values()}
        retained_bases={row['base'] for row in self.rows}
        for key,entry in list(self.cached.items()):
            if key not in retained_bases and key not in wanted_bases and now-entry.get('unused_since',now)>=CACHE_GRACE_S:
                entry['table'].deleteLater();del self.cached[key]

    def _edited_buffer(self,key):
        """A bounded iterator for terrain edits; x/z and identities never move."""
        from backend import game_engine_terrain as terrain, game_engine_world as world
        spec=self.wanted[key];sector=spec['sector']
        rows=json.loads(gzip.decompress((self.assets/(sector.replace(':','_')+'.json.gz')).read_bytes()))
        stamps=terrain._normalized_brush_stamps(self.document)
        brush_index=terrain._build_brush_index(stamps)
        buffer=bytearray();count=0
        for row in rows:
            if row['species']!=spec['species']:continue
            if 'chunk' in spec and [math.floor(row['x']/128),math.floor(row['z']/128)]!=spec['chunk']:continue
            if 'variant' in spec:
                from backend.game_engine_botanical_designs import tree_variant
                if tree_variant(row['id'],row['species'])!=spec['variant']:continue
            if row.get('preserve_origin'):
                buffer.extend(instance_bytes(row));count+=1;yield None;continue
            h=terrain.height_at(row['x'],row['z'],overrides=self.document,brush_stamps=stamps,brush_index=brush_index)
            if h>=1.2:
                r=world.DEFAULT_PLANET_RADIUS_METERS;x,z=row['x'],row['z']
                row['y']=math.sqrt(max(1,(r+h)**2-x*x-z*z))-r+row.get('ground_offset_m',-.06)
                buffer.extend(instance_bytes(row));count+=1
            yield None
        yield bytes(buffer),count

    def drain(self):
        started=time.perf_counter();uploaded=0
        while self.pending and uploaded<UPLOAD_BATCH_CAP and time.perf_counter()-started<UPLOAD_BUDGET_S:
            key=self.pending[0];spec=self.wanted[key]
            base=spec['base']
            if base not in self.cached:
                if spec['sector'] in self.edited:
                    if self.edit_job is None:self.edit_job=(key,self._edited_buffer(key))
                    result=next(self.edit_job[1])
                    if result is None:continue
                    buffer,count=result;self.edit_job=None
                else:
                    self.file.seek(spec['offset']);buffer=self.file.read(spec['count']*80);count=spec['count']
                    if len(buffer)!=count*80:raise ValueError('truncated world tree instance buffer')
                table=FloraInstances(self)
                table._buffer=QByteArray(buffer);table._count=count;table.revision=0;table.markDirty()
                self.cached[base]=dict(sector=spec['sector'],species=spec['species'],
                                      mesh_species=spec.get('mesh_species',spec['species']),
                                      variant=spec.get('variant'),table=table,count=count,geometries={})
                editor = getattr(self,"asset_editor",None)
                if editor is not None:
                    editor.refresh_native(self,force=True)
            entry=self.cached[base]
            # Quick3D drops a scene resource when its last Model detaches.
            # A retained Python/Qt object is not itself a retained GPU node.
            # Re-publish the compiled buffer before attaching a cached table
            # after travel; otherwise all counts are valid but nothing draws.
            if 'unused_since' in entry:
                entry['table'].markDirty()
                entry.pop('unused_since',None)
                for geometry in entry['geometries'].values():geometry.update()
            entry['geometries'][spec['lod']]=self.meshes.geometry(f"{entry['mesh_species']}:{spec['lod']}")
            index=len(self.rows);self.beginInsertRows(QModelIndex(),index,index)
            self.rows.append(dict(key=key,base=base,sector=spec['sector'],lod=spec['lod']));self.endInsertRows()
            self.pending.pop(0);uploaded+=1
        self.upload_ticks+=1
        self.max_upload_ms=max(self.max_upload_ms,(time.perf_counter()-started)*1000)
        self.max_batches_per_tick=max(self.max_batches_per_tick,uploaded)
        if not self.pending:self.timer.stop()

    def measurements(self):
        active={(self.wanted[r['key']]['sector'],self.wanted[r['key']]['species']) for r in self.rows if r['key'] in self.wanted}
        return dict(source=self.catalog['source'],map_trees=self.catalog['tree_count'],
                    visible_batches=sum(r['key'] in self.wanted for r in self.rows),
                    retained_batches=len(self.rows),instances=sum(self.catalog['sectors'][s]['groups'][species]['count'] for s,species in active),
                    instance_count_scope='RESIDENT_MAP_OBJECTS_BEFORE_NATIVE_FRUSTUM_AND_LOD',
                    pending_batches=len(self.pending),cached_batches=len(self.cached),
                    cached_bytes=sum(e['count']*80 for e in self.cached.values()),
                    max_upload_ms=self.max_upload_ms,max_batches_per_tick=self.max_batches_per_tick,
                    max_selection_ms=self.max_selection_ms,
                    selection_backend='CPP' if self._sector_index.native else 'PYTHON',
                    range_policy='TERRAIN_CAMERA_FAR_PLANE',
                    residency_policy='POSITION_AND_RANGE_NOT_CAMERA_DIRECTION',far_lod_triangles_max=self.catalog.get('far_lod_triangles_max',40))


def update_world_trees(bridge,view):
    """Shared seam for both the standalone client and the desktop preview."""
    from copy import deepcopy
    from backend import game_engine_host
    model=getattr(bridge,'_world_tree_model',None)
    if model is None:return
    runtime=game_engine_host._RUNTIME
    doc=runtime._terrain_overrides
    signature=(id(doc),doc.get('revision',0))
    if signature!=getattr(bridge,'_world_tree_terrain_signature',None):
        with runtime._lock:
            document=deepcopy(runtime._terrain_overrides)
        model.set_terrain(document)
        bridge._world_tree_terrain_signature=signature
    model.set_view(view,runtime._render_profile)
