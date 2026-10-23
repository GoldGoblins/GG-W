"""Bounded local GgEngine world pages shared by Quick3D and game physics.

All file decoding happens on one loader lane. Qt geometry is created on the GUI
thread; the simulation reads an immutable spatial index under its own lock.
"""
from __future__ import annotations
import json,math,struct,time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from PySide6.QtCore import QObject,Property,Signal,Slot,QCoreApplication,QAbstractListModel,QModelIndex,Qt,QByteArray
from PySide6.QtGui import QImage,QImageReader,QVector3D
from PySide6.QtQuick3D import QQuick3DTextureData
from backend.game_engine_adapter_assets import asset_path
from backend.game_engine_legacy import schema_matches, manifest_path
from backend.game_engine_adapter_formats import AssetCache
from backend.game_engine_adapter_models import Batch
from backend.game_engine_adapter_mips import image_levels,install_table
from backend.game_engine_adapter_liquids import LiquidIndex,prepare_atlas,validate_settings
from backend.game_engine_adapter_portals import PortalCamera,visibility
from backend.game_engine_adapter_props import prepare_props
from backend.game_engine_adapter_animation import WorldAnimations
from backend.game_engine_adapter_lighting import WorldLighting,settings as lighting_settings
from backend.game_engine_adapter_rooms import camera_seeds
from backend.game_engine_adapter_weather import Weather,settings as weather_settings
from backend.game_engine_adapter_horizon import Horizon,settings as horizon_settings
from backend.game_engine_adapter_wmo_windows import decode as decode_window,needed as window_needed,selected as select_window

TILE=struct.unpack('<f',struct.pack('<f',533.3333))[0]
LIMIT=96*1024*1024

def tile_at(x,z,origin):
    # Original world_to_tile: axes swap, Qt Z is negative original Y.
    wx,wy=x+origin[0],origin[1]-z
    return (max(0,min(63,int((32*TILE-wy)/TILE))),max(0,min(63,int((32*TILE-wx)/TILE))))

def triangle_height(a,b,c,x,z):
    d=(b[2]-c[2])*(a[0]-c[0])+(c[0]-b[0])*(a[2]-c[2])
    if abs(d)<1e-8:return None
    u=((b[2]-c[2])*(x-c[0])+(c[0]-b[0])*(z-c[2]))/d
    v=((c[2]-a[2])*(x-c[0])+(a[0]-c[0])*(z-c[2]))/d
    if u<-.00001 or v<-.00001 or u+v>1.00001:return None
    return u*a[1]+v*b[1]+(1-u-v)*c[1]

def segment_hit(a,b,c,start,end):
    d=[end[i]-start[i] for i in range(3)];ab=[b[i]-a[i] for i in range(3)];ac=[c[i]-a[i] for i in range(3)]
    cross=lambda p,q:(p[1]*q[2]-p[2]*q[1],p[2]*q[0]-p[0]*q[2],p[0]*q[1]-p[1]*q[0])
    dot=lambda p,q:sum(p[i]*q[i] for i in range(3))
    h=cross(d,ac);det=dot(ab,h)
    if abs(det)<1e-8:return False
    s=[start[i]-a[i] for i in range(3)];u=dot(s,h)/det
    if u<0 or u>1:return False
    q=cross(s,ab);v=dot(d,q)/det
    if v<0 or u+v>1:return False
    t=dot(ac,q)/det;return .0001<t<.9999

def ground_effect_at(row,x,z):
    """Sample retained original ADT predominant-layer metadata, in Qt axes."""
    origin=row.get('ground_effect_origin');span=row.get('ground_effect_span');ids=row.get('ground_effect_ids')
    if not isinstance(origin,list) or len(origin)!=3 or type(span) not in (int,float) or not math.isfinite(span) or span<=0 or not isinstance(ids,list) or len(ids)!=64:return None
    south=(origin[0]-x)/span;east=(z-origin[2])/span
    if not 0<=south<=1 or not 0<=east<=1:return None
    ident=ids[min(7,int(south*8))*8+min(7,int(east*8))]
    return ident if type(ident) is int and 0<=ident<0xffffffff else None

class Surface:
    """CPU triangles are exactly those decoded into the retained render page."""
    def __init__(self,metadata,blob,*,share_points=False):
        self.cells={};self.footprints=[];self.footprint_cells={};self.bytes=0;self.active_props=None
        point_cache={}
        for row in ([r for r in metadata['rows'] if r['kind']=='terrain']+metadata.get('collision',[]) if not metadata['groups'] else metadata['collision']):
            source=(row['offset'],row['vertices'],row.get('stride',32))
            if share_points and source in point_cache:points=point_cache[source]
            else:
                points=[struct.unpack_from('<3f',blob,row['offset']+i*row.get('stride',32)) for i in range(row['vertices'])]
                self.bytes+=len(points)*96
                if share_points:point_cache[source]=points
            if row.get('kind')=='terrain':
                self.footprints.append(row)
                lo=[math.floor((row['bounds'][0][k]-.01)/8) for k in (0,2)]
                hi=[math.floor((row['bounds'][1][k]+.01)/8) for k in (0,2)]
                if (hi[0]-lo[0]+1)*(hi[1]-lo[1]+1)>4096:raise ValueError('World footprint span exceeded')
                for cx in range(lo[0],hi[0]+1):
                    for cz in range(lo[1],hi[1]+1):
                        if (cx,cz) not in self.footprint_cells:self.footprint_cells[(cx,cz)]=[];self.bytes+=160
                        self.footprint_cells[(cx,cz)].append(row);self.bytes+=16
                if self.bytes>LIMIT:raise ValueError('World collision index capacity exceeded')
            indices=row['indices']
            if len(indices)%3 or any(i<0 or i>=len(points) for i in indices):raise ValueError('Invalid world collision indices')
            for i in range(0,len(indices),3):
                a,b,c=(points[j] for j in indices[i:i+3]);triangle=(a,b,c,row)
                lo=[math.floor(min(p[k] for p in (a,b,c))/8) for k in (0,2)]
                hi=[math.floor(max(p[k] for p in (a,b,c))/8) for k in (0,2)]
                if (hi[0]-lo[0]+1)*(hi[1]-lo[1]+1)>4096:raise ValueError('World collision triangle span exceeded')
                self.bytes+=220 # triangle tuple, native index ints and row metadata
                for cx in range(lo[0],hi[0]+1):
                    for cz in range(lo[1],hi[1]+1):
                        self.cells.setdefault((cx,cz),[]).append(triangle);self.bytes+=16
                if self.bytes>LIMIT:raise ValueError('World collision index capacity exceeded')
    def enabled(self,row):return not row.get('prop_key') or self.active_props is None or row['prop_key'] in self.active_props
    def sample(self,x,y,z,props=None):
        floor=None;hit=None
        for a,b,c,row in self.cells.get((math.floor(x/8),math.floor(z/8)),()):
            if not self.enabled(row) or props is not None and bool(row.get('prop_key'))!=props:continue
            h=triangle_height(a,b,c,x,z)
            if h is not None and h>y and row.get('kind')!='terrain' and (b[2]-a[2])*(c[0]-a[0])-(b[0]-a[0])*(c[2]-a[2])<=0:continue
            if h is not None and (row.get('kind')=='terrain' or h<=y+.8) and (floor is None or h>floor):floor,hit=h,row
        if hit is not None or props is True:return floor,hit
        footprint=next((r for r in self.footprint_cells.get((math.floor(x/8),math.floor(z/8)),()) if r['bounds'][0][0]-.01<=x<=r['bounds'][1][0]+.01 and r['bounds'][0][2]-.01<=z<=r['bounds'][1][2]+.01),None)
        return floor,footprint
    def down_ray(self,x,y,z,props=None):
        height=None;hit=None
        for a,b,c,row in self.cells.get((math.floor(x/8),math.floor(z/8)),()):
            if not self.enabled(row) or props is not None and bool(row.get('prop_key'))!=props:continue
            h=triangle_height(a,b,c,x,z)
            if h is not None and h<=y and (height is None or h>height):height,hit=h,row
        return height,hit
    def up_ray(self,x,y,z):
        height=None
        for a,b,c,row in self.cells.get((math.floor(x/8),math.floor(z/8)),()):
            if not self.enabled(row):continue
            h=triangle_height(a,b,c,x,z)
            if h is not None and h>=y and (height is None or h<height):height=h
        return height
    def walls(self,x,y,z,radius=.3):
        # Intersect walking triangles with a horizontal body slice. Only wall
        # triangles participate; original MOPY DETAIL filtering happened natively.
        for _ in range(2):
            candidates=[];seen=set()
            for cx in range(math.floor((x-radius)/8),math.floor((x+radius)/8)+1):
                for cz in range(math.floor((z-radius)/8),math.floor((z+radius)/8)+1):
                    for triangle in self.cells.get((cx,cz),()):
                        if id(triangle) not in seen:seen.add(id(triangle));candidates.append(triangle)
            for a,b,c,row in candidates:
                if not self.enabled(row) or 'group' not in row and not row.get('prop_key'):continue
                ab=[b[i]-a[i] for i in range(3)];ac=[c[i]-a[i] for i in range(3)]
                nx=ab[1]*ac[2]-ab[2]*ac[1];ny=ab[2]*ac[0]-ab[0]*ac[2];nz=ab[0]*ac[1]-ab[1]*ac[0]
                if abs(ny)>.5*math.sqrt(nx*nx+ny*ny+nz*nz):continue
                cut=[]
                for p,q in ((a,b),(b,c),(c,a)):
                    if abs(q[1]-p[1])<1e-8:continue
                    t=(y+.25-p[1])/(q[1]-p[1])
                    if 0<=t<=1:cut.append((p[0]+t*(q[0]-p[0]),p[2]+t*(q[2]-p[2])))
                if len(cut)<2:continue
                p,q=cut[:2];dx,dz=q[0]-p[0],q[1]-p[1];length=dx*dx+dz*dz
                if length<1e-12:continue
                t=max(0,min(1,((x-p[0])*dx+(z-p[1])*dz)/length));px,pz=p[0]+t*dx,p[1]+t*dz
                distance=math.hypot(x-px,z-pz)
                if distance<radius:
                    if distance<1e-8:x+=radius*dz/math.sqrt(length);z-=radius*dx/math.sqrt(length)
                    else:x+=(x-px)*(radius-distance)/distance;z+=(z-pz)*(radius-distance)/distance
        return x,z
    def line_of_sight(self,start,end):
        steps=math.ceil(max(abs(end[i]-start[i]) for i in (0,2))/4)+1
        if steps>256:return False
        cells={(math.floor((start[0]+(end[0]-start[0])*i/steps)/8),math.floor((start[2]+(end[2]-start[2])*i/steps)/8)) for i in range(steps+1)};seen=set()
        for cell in cells:
            for a,b,c,row in self.cells.get(cell,()):
                if not self.enabled(row):continue
                key=(id(a),id(b),id(c))
                if key in seen:continue
                seen.add(key)
                if len(seen)>8192:return False
                if segment_hit(a,b,c,start,end):return False
        return True

class WorldBatch(Batch):
    def set_image(self,image,key,levels=None):
        if key==self.texture_key:return
        if levels is None:levels=image_levels(image)
        image=image.convertToFormat(QImage.Format_RGBA8888);size=image.sizeInBytes()*(2 if levels else 3)
        if image.isNull():raise ValueError('World base image unavailable')
        if size>self.texture_bytes:self.owner.reserve(size-self.texture_bytes)
        elif size<self.texture_bytes:self.owner.release(self.texture_bytes-size)
        self.texture_bytes=size;self.tex.setSize(image.size());self.tex.setFormat(QQuick3DTextureData.Format.RGBA8)
        self.tex.setTextureData(bytes(image.constBits()));self.tex.setHasTransparency(True);self.texture_key=key
        self.row['mip_levels']=levels or [];self.changed.emit()
    def set_texture(self,cache,path,source):
        if self.liquid:
            key='liquid:'+self.liquid['liquid_kind']
            shared=self.owner.shared_textures.get(key)
            if shared is None:
                image=self.owner.prepared.get(key)
                if image is None:raise ValueError('Liquid atlas unavailable')
                self.set_image(image,key);self.owner.shared_textures[key]=self.tex
                self.owner.shared_mip_levels[key]=self.row.get('mip_levels',[])
            else:
                self.tex.deleteLater();self.tex=shared;self.texture_key=key
                self.row['mip_levels']=self.owner.shared_mip_levels.get(key,[])
            return
        texture=cache._texture(source,Path(path)) if source else None
        key=('mips:' if self._authored_mip_sampling else '')+str(texture) if texture else 'world:white'
        shared=self.owner.shared_textures.get(key)
        if shared is not None:
            self.tex.deleteLater();self.tex=shared;self.texture_key=key
            self.row['mip_levels']=self.owner.shared_mip_levels.get(key,[]);return
        image=self.owner.prepared.get(key) if texture else None
        if image is None:super().set_texture(cache,path,source)
        else:self.set_image(image,key)
        self.owner.shared_textures[key]=self.tex
        self.owner.shared_mip_levels[key]=self.row.get('mip_levels',[])
    def __init__(self,cache,path,row,blob,page):
        self.liquid=row if row['kind']=='liquid' else None
        super().__init__(cache,path,row,blob,page);self.extra=[]
        lo,hi=row['bounds']
        self.geo.setBounds(QVector3D(*(v-.01 for v in lo)),QVector3D(*(v+.01 for v in hi)))
        if row['kind']=='terrain':
            layers=row['layers'] or [None];chains=[self.row.get('mip_levels',[])]
            for source in (layers+[None]*4)[1:4]:
                texture=cache._texture(source,Path(path)) if source else None
                key='mips:'+str(texture) if texture else 'world:white'
                image=page.prepared.get(key) if texture else QImage(1,1,QImage.Format_RGBA8888)
                if image is None:
                    if texture.suffix.lower()=='.blp':
                        from backend.game_engine_adapter_mips import atlas
                        decoded,pixels=cache.decode(texture,mip_chain=True);image,_=atlas(decoded,pixels)
                    else:image=cache.image(texture)
                if not source:image.fill(0xffffffff)
                levels=image_levels(image);chains.append(levels)
                self.extra.append(self._image(image,mipmaps=not levels,key=key))
            for key in ('alpha_offset','shadow_offset'):
                offset=row[key];shadow=key=='shadow_offset';size=64*64*(1 if shadow else 4)
                if offset<0 or offset+size>len(blob):raise ValueError('Invalid terrain blend data')
                self.extra.append(self._image(QImage(blob[offset:offset+size],64,64,64 if shadow else 256,QImage.Format_Grayscale8 if shadow else QImage.Format_RGBA8888).copy()))
            install_table(self,chains,page.shared_mip_tables)
        elif self.liquid:install_table(self,[self.row.get('mip_levels',[])],page.shared_mip_tables)
    @Slot()
    def publish(self):
        # A newly bound Quick3D model needs a complete geometry publication.
        # Retain the object; publish vertices before the indexed draw buffer.
        from PySide6.QtQuick3D import QQuick3DGeometry
        vertices=bytes(self.geo.vertexData());indices=bytes(self.geo.indexData());lo=self.geo.boundsMin();hi=self.geo.boundsMax()
        for texture in [self.tex]+self.extra+([self.mip_lookup] if self.mip_lookup is not None else []):
            if texture in self.owner.published_textures:continue
            self.owner.published_textures.add(texture)
            data=bytes(texture.textureData());texture.setTextureData(b'');texture.setTextureData(data)
        self.geo.clear();self.geo.setStride(self.stride);self.geo.setPrimitiveType(QQuick3DGeometry.PrimitiveType.Triangles)
        a=QQuick3DGeometry.Attribute
        for semantic,offset in ((a.PositionSemantic,0),(a.NormalSemantic,12),(a.TexCoordSemantic,24)):self.geo.addAttribute(semantic,offset,a.F32Type)
        if self.stride==48:self.geo.addAttribute(a.ColorSemantic,32,a.F32Type)
        self.geo.addAttribute(a.IndexSemantic,0,a.U32Type);self.geo.setVertexData(vertices);self.geo.setIndexData(indices);self.geo.setBounds(lo,hi);self.geo.update()
    def _image(self,image,*,mipmaps=False,key=None):
        if key is not None and key in self.owner.shared_textures:return self.owner.shared_textures[key]
        image=image.convertToFormat(QImage.Format_RGBA8888)
        if image.isNull():raise ValueError('World layer image unavailable')
        self.owner.reserve(image.sizeInBytes()*(3 if mipmaps else 2));texture=QQuick3DTextureData();QObject.setParent(texture,self)
        texture.setSize(image.size());texture.setFormat(QQuick3DTextureData.Format.RGBA8);texture.setTextureData(bytes(image.constBits()))
        if key is not None:
            self.owner.shared_textures[key]=texture
            self.owner.shared_mip_levels[key]=image_levels(image)
        return texture
    @Property('QVariantList',constant=True)
    def stages(self):return self.extra

class Page(QObject):
    def __init__(self,stream,path,metadata,blob,surface=None,prepared=None,sight=None,liquids=None):
        super().__init__(stream);self.stream=stream;self.path=path;self.metadata=metadata;self.byte_size=0;self.batches=[];self.closed=False
        self.prepared=prepared or {};self.shared_textures={};self.shared_mip_levels={};self.shared_mip_tables={};self.published_textures=set();self.visibility_key=None;self.portal_status={}
        try:
            self.reserve(metadata.get('directory_bytes',0))
            self.reserve(metadata.get('native_collision_bytes',0))
            self.surface=surface or Surface(metadata,blob);self.reserve(self.surface.bytes)
            self.audio_surface=Surface({'rows':[],'groups':metadata['groups'],'collision':metadata['audio_surfaces']},blob,share_points=True) if metadata.get('audio_surfaces') else None
            if self.audio_surface:self.reserve(self.audio_surface.bytes)
            self.reserve(sum(len(row.get('ground_effect_ids',()))*16 for row in metadata['rows']))
            self.sight=sight or (Surface({**metadata,'collision':metadata.get('sight_collision',metadata['collision'])},blob) if metadata['groups'] else self.surface)
            if self.sight is not self.surface:self.reserve(self.sight.bytes)
            self.camera_only=Surface({**metadata,'collision':metadata['camera_only_collision']},blob) if metadata.get('camera_only_collision') else None
            if self.camera_only:self.reserve(self.camera_only.bytes)
            self.liquids=liquids or LiquidIndex(metadata,blob);self.reserve(self.liquids.bytes)
            for row in metadata['rows']:
                if row['indices']:self.batches.append(WorldBatch(stream.cache,path,row,blob,self))
            stream.animations.attach(self)
        except Exception:self.close();raise
        finally:self.prepared={}
    def reserve(self,size):
        if self.stream.bytes+size>LIMIT:raise ValueError('World residency memory capacity exceeded')
        self.stream.bytes+=size;self.byte_size+=size
    def release(self,size):self.stream.bytes-=size;self.byte_size-=size
    def close(self):
        if self.closed:return
        self.closed=True;self.stream.bytes-=self.byte_size;self.byte_size=0;self.batches=[];self.shared_textures={};self.shared_mip_levels={};self.shared_mip_tables={};self.published_textures.clear();self.deleteLater()

class WorldBatches(QAbstractListModel):
    """Insert/remove only changed pages; retained terrain delegates stay alive."""
    ROLE=Qt.UserRole+1
    def __init__(self,parent):super().__init__(parent);self.rows=[]
    def roleNames(self):return {self.ROLE:b'batchData'}
    def rowCount(self,parent=QModelIndex()):return 0 if parent.isValid() else len(self.rows)
    def data(self,index,role=Qt.DisplayRole):return self.rows[index.row()] if role==self.ROLE and index.isValid() else None
    def append(self,rows):
        if not rows:return
        first=len(self.rows);self.beginInsertRows(QModelIndex(),first,first+len(rows)-1);self.rows.extend(rows);self.endInsertRows()
    def remove(self,rows):
        wanted=set(rows)
        for i in range(len(self.rows)-1,-1,-1):
            if self.rows[i] in wanted:self.beginRemoveRows(QModelIndex(),i,i);self.rows.pop(i);self.endRemoveRows()
    def clear(self):
        if self.rows:self.beginRemoveRows(QModelIndex(),0,len(self.rows)-1);self.rows=[];self.endRemoveRows()

class WorldStream(QObject):
    changed=Signal()
    statusChanged=Signal()
    lightingChanged=Signal()
    def __init__(self,parent=None):
        super().__init__(parent);self.pages={};self.bytes=0;self.cache=AssetCache();self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='gg-world-page');self.pending=None;self.errors={};self.config=None;self.tiles=set();self.closed=False;self.revision=0;self.safe=None;self.last_query={};self.last_error='';self.position=(0.,0.,0.)
        self.render_model=WorldBatches(self)
        self.weather_model=WorldBatches(self)
        self.skybox_model=WorldBatches(self)
        self.camera=None;self.camera_key=None;self.view=None;self.player_motion=None;self.prop_owners={};self.clock_ms=0.;self.animations=WorldAnimations(self);self.retired_instances=set();self.native_sources=set()
        self._ffx_submersion='DRY'
        self.light=WorldLighting(self);self.horizon=Horizon(self);self.weather=Weather(self)
        from backend.game_engine_adapter_camera import CameraBoom
        self.camera_boom=CameraBoom()
        from backend.game_engine_adapter_collision_restore import restore
        self.collision_restores=0;self.restored_collision_pages=0;self.cache.collision_restore=lambda reader:restore(self,reader)
        app=QCoreApplication.instance()
        if app:app.aboutToQuit.connect(self.close)
    def configure(self,manifest):
        if self.config is not None:raise ValueError('Unload the world before selecting another map')
        path=asset_path(manifest_path(manifest))
        if not path.is_file() or path.stat().st_size>65536:raise ValueError('World manifest unavailable or too large')
        cfg=json.loads(path.read_text())
        if not isinstance(cfg,dict):raise ValueError('World manifest must be an object')
        name=cfg.get('map','')
        if not schema_matches(cfg.get('schema'),'gg.engine-world.v1') or not isinstance(name,str) or not name or len(name)>64 or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_' for c in name):raise ValueError('Invalid world manifest')
        origin=cfg.get('origin',[0,0,0]);spawn=cfg.get('spawn',[0,1,0])
        for vector in (origin,spawn):
            if not isinstance(vector,list) or len(vector)!=3 or any(isinstance(n,bool) or not isinstance(n,(int,float)) or not math.isfinite(n) or abs(n)>2_000_000 for n in vector):raise ValueError('Invalid world origin/spawn')
        radius=cfg.get('radius',1)
        if isinstance(radius,bool) or not isinstance(radius,int) or not 0<=radius<=1:raise ValueError('World radius must be 0 or 1 tile')
        directory=asset_path(cfg.get('directory',f'World/Maps/{name}'))
        if cfg.get('archive_directory'):self.cache.mount_chain(cfg['archive_directory'])
        wdt=self.cache.resolve(directory/(name+'.wdt'));metadata,_=self.cache.decode(wdt,timeout=3)
        fixed=cfg.get('wmos',[])
        if metadata.get('global_wmo_placement') and not fixed:fixed=[metadata['global_wmo_placement']]
        if not isinstance(fixed,list) or len(fixed)>16:raise ValueError('World WMO placement capacity exceeded')
        for w in fixed:
            if not isinstance(w,dict) or not isinstance(w.get('model'),str) or not w['model'].lower().endswith('.wmo'):raise ValueError('Invalid world WMO placement')
            asset_path(w['model'])
            ds=w.get('doodad_set',0)
            if isinstance(ds,bool) or not isinstance(ds,int) or not 0<=ds<=65535:raise ValueError('Invalid WMO doodad set')
            ns=w.get('name_set',0)
            if isinstance(ns,bool) or not isinstance(ns,int) or not 0<=ns<=65535:raise ValueError('Invalid WMO name set')
            for field in ('position','rotation'):
                vector=w.get(field)
                if vector is not None and (not isinstance(vector,list) or len(vector)!=3 or any(isinstance(n,bool) or not isinstance(n,(int,float)) or not math.isfinite(n) or abs(n)>2_000_000 for n in vector)):
                    raise ValueError('Invalid WMO position/rotation')
        if not isinstance(cfg.get('areas',{}),dict) or len(cfg.get('areas',{}))>4096 or any(not isinstance(n,str) or len(n)>128 for n in cfg.get('areas',{}).values()):raise ValueError('World area name capacity exceeded')
        validate_settings(cfg.get('liquids',{}),asset_path)
        lighting_settings(cfg.get('lighting'));horizon_settings(cfg.get('horizon'));weather_settings(cfg.get('weather'));self.light.configure(cfg.get('lighting'));self.horizon.configure(cfg.get('horizon'))
        import hashlib
        self.manifest_path=path.relative_to(Path(__file__).resolve().parents[1]/'qml').as_posix()
        self.manifest_digest=hashlib.sha256(path.read_bytes()).hexdigest()
        self.config={**cfg,'origin':origin,'spawn':spawn,'radius':radius,'directory':directory,'wmos':fixed};self.tiles={tuple(t) for t in metadata['tiles']};self.position=tuple(spawn);self.weather.configure(cfg.get('weather'));self.changed.emit()
    def _load(self,key,spec,position=None,previous=None):
        self.cache.deadline=time.monotonic()+8
        try:return self._load_page(key,spec,position,previous)
        finally:self.cache.deadline=None
    def _load_page(self,key,spec,position=None,previous=None):
        path=self.cache.resolve(spec['path']);options={'world_scene':True,'origin':self.config['origin'],'timeout':4,'collision_key':key}
        if not hasattr(self.cache,'world_collision_keys'):self.cache.world_collision_keys=set()
        self.cache.world_collision_keys.add(key)
        window=False
        if path.suffix.lower()=='.wmo':
            options.update(position=spec.get('position'),rotation=spec.get('rotation'),doodad_set=spec.get('doodad_set',0),name_set=spec.get('name_set',0))
            meta,_=self.cache.decode(path,timeout=3)
            window=meta['groups']>32
            if not window:
                for i in range(meta['groups']):
                    if time.monotonic()>self.cache.deadline:raise TimeoutError('World group preparation exceeded its time budget')
                    self.cache.resolve(Path(spec['path']).with_name(path.stem+f'_{i:03}.wmo'))
        if window:metadata,blob=decode_window(self.cache,path,spec,options,position or self.position,previous)
        else:metadata,blob=self.cache.decode(path,**options)
        blob=prepare_props(self.cache,path,metadata,blob)
        surface=Surface(metadata,blob);liquids=LiquidIndex(metadata,blob);prepared={};image_bytes=0;liquid_materials={}
        sight=Surface({**metadata,'collision':metadata.get('sight_collision',metadata['collision'])},blob) if metadata['groups'] else surface
        for row in metadata['rows']:
            if row['kind']=='liquid':
                kind=row['liquid_kind'];name='liquid:'+kind
                if name not in prepared:
                    image,material,notes=prepare_atlas(self.cache,path,kind,self.config.get('liquids',{}),staging_budget=32*1024*1024-image_bytes)
                    prepared[name]=image;liquid_materials[kind]=material;image_bytes+=image.sizeInBytes()
                    metadata.setdefault('limitations',[]).extend(notes)
                    if image_bytes>32*1024*1024:raise ValueError('World prepared image budget exceeded')
                row.update(liquid_materials[kind]);continue
            for source in ([row.get('texture')]+row.get('layers',[])):
                if time.monotonic()>self.cache.deadline:raise TimeoutError('World texture preparation exceeded its time budget')
                if not source:continue
                texture=self.cache._texture(source,path);mips=True;name='mips:'+str(texture)
                if name in prepared:continue
                if len(prepared)>=128:raise ValueError('World texture preparation capacity exceeded')
                if texture.suffix.lower()=='.blp' and mips:
                    from backend.game_engine_adapter_mips import atlas
                    decoded,pixels=self.cache.decode(texture,mip_chain=True);image,_=atlas(decoded,pixels)
                elif texture.suffix.lower() in ('.blp','.tga'):image=self.cache.image(texture)
                else:
                    reader=QImageReader(str(texture));size=reader.size()
                    if size.width()<1 or size.height()<1 or size.width()*size.height()>2*1024*1024:raise ValueError('World image dimensions exceeded')
                    image=reader.read()
                if image.isNull():raise ValueError('World layer image unavailable')
                image_bytes+=image.sizeInBytes()
                if image_bytes>32*1024*1024:raise ValueError('World prepared image budget exceeded')
                prepared[name]=image
        if liquid_materials and not self.light.config:metadata.setdefault('limitations',[]).append('Liquid swatches use manifest colors because this world has no Light.dbc binding')
        return key,path,metadata,blob,surface,prepared,sight,liquids
    def desired(self,x,z):
        cfg=self.config;cx,cy=tile_at(x,z,cfg['origin']);r=cfg['radius'];terrain={}
        for tx,ty in sorted(self.tiles,key=lambda t:((t[0]-cx)**2+(t[1]-cy)**2,t[1],t[0])):
            if abs(tx-cx)<=r and abs(ty-cy)<=r:terrain[f't:{tx}:{ty}']={'path':str(cfg['directory']/f'{cfg["map"]}_{tx}_{ty}.adt')}
        wmos={'w:fixed:'+str(i):{**spec,'path':spec['model']} for i,spec in enumerate(cfg['wmos'])}
        for key,page in self.pages.items():
            if key in terrain:
                for spec in page.metadata['placements']:
                    wmos['w:'+str(spec['id'])]={**spec,'path':spec['model']}
        current=f't:{cx}:{cy}';ranked=[]
        for key,spec in terrain.items():
            _,tx,ty=key.split(':');tx,ty=int(tx),int(ty)
            center=((31.5-ty)*TILE-cfg['origin'][0],cfg['origin'][1]-(31.5-tx)*TILE)
            distance=(center[0]-x)**2+(center[1]-z)**2
            ranked.append((-1 if key==current else distance,1,key,spec))
        for key,spec in wmos.items():
            position=spec.get('position') or [0,0,0]
            # Invalid placements still reach the supervised decoder and its
            # explicit error; they never break the GUI's residency selection.
            try:distance=(float(position[0])-cfg['origin'][0]-x)**2+(cfg['origin'][1]-float(position[1])-z)**2
            except (ValueError,TypeError,IndexError):distance=float('inf')
            if not math.isfinite(distance):distance=float('inf')
            ranked.append((distance,0,key,spec))
        ranked.sort(key=lambda row:row[:3])
        # Keep a neighbouring terrain candidate near the head even in a dense
        # town, so the avatar can reach a tile boundary without deadlocking
        # its prefetch behind dozens of nearby building placements.
        head=[]
        if current in terrain:head.append(next(row for row in ranked if row[2]==current))
        nearby=next((row for row in ranked if row[2].startswith('w:')),None)
        neighbour=next((row for row in ranked if row[2] in terrain and row[2]!=current),None)
        if nearby:head.append(nearby)
        if neighbour:head.append(neighbour)
        selected={row[2] for row in head};ordered=head+[row for row in ranked if row[2] not in selected]
        return {key:spec for _,_,key,spec in ordered[:25]}
    def update(self,x,y,z):
        if self.closed or self.config is None:return
        if any(not math.isfinite(n) or abs(n)>2_000_000 for n in (x,y,z)):raise ValueError('Invalid stream position')
        self.animations.finish();self.light.finish();self.horizon.finish();self.weather.finish();self.position=(x,y,z);wanted=self.desired(x,z);changed=False
        if self.pending is not None and self.pending.done():
            future=self.pending;self.pending=None
            try:
                key,path,metadata,blob,surface,prepared,sight,liquids=future.result()
                old_page=self.pages.get(key)
                ids=metadata.get('group_window')
                previous=old_page.metadata.get('group_window',()) if old_page else ()
                current=not ids or tuple(ids)==select_window(metadata['wmo_directory'],self.position,previous,len(ids))
                if key in wanted and current:
                    for spec in metadata.get('props',[]):
                        if not spec['prop_key'].startswith('mddf:'):continue
                        for old in self.pages.values():
                            for previous in old.metadata.get('props',[]):
                                if previous['prop_key']!=spec['prop_key']:continue
                                if previous['source']!=spec['source'] or any(abs(a-b)>1e-4 for a,b in zip(previous['anchor'],spec['anchor'])):raise ValueError('Conflicting world object placement ID across tiles')
                    camera_cost=Surface({**metadata,'collision':metadata['camera_only_collision']},blob).bytes if metadata.get('camera_only_collision') else 0
                    cost=surface.bytes+(sight.bytes if sight is not surface else 0)+liquids.bytes+camera_cost+metadata.get('native_collision_bytes',0)+metadata.get('directory_bytes',0);atlases=set();textures=set()
                    for row in metadata['rows']:
                        if not row['indices']:continue
                        capacity=row.get('capacity',row['vertices']);indices=row.get('index_capacity',capacity//4*6 if row.get('dynamic') else len(row['indices']))
                        cost+=(capacity*row['stride']+indices*4)*2
                        cost+=row.get('instance_capacity',0)*80*3
                        if row['kind']=='liquid':
                            cost+=16*16*2 # mip rectangle lookup, conservatively per draw
                            name='liquid:'+row['liquid_kind']
                            if name not in atlases:cost+=prepared[name].sizeInBytes()*3;atlases.add(name)
                            continue
                        for source in [row.get('texture')]+((row.get('layers',[])+[None]*4)[1:4] if row['kind']=='terrain' else []):
                            texture_key=('mips:'+str(self.cache._texture(source,path))) if source else 'world:white'
                            image=prepared.get(texture_key) if source else None
                            if texture_key in textures:continue
                            textures.add(texture_key)
                            cost+=(image.width()*image.height()*4 if image is not None else 4)*3
                        if row['kind']=='terrain':cost+=64*64*4*4+16*4*16*2
                    if cost>LIMIT:raise ValueError('World page exceeds residency budget')
                    rank={k:i for i,k in enumerate(wanted)}
                    for old in sorted(self.pages,key=lambda k:rank.get(k,999),reverse=True):
                        if self.bytes+cost<=LIMIT:break
                        if rank.get(old,999)>rank[key]:self._remove_page(old);changed=True
                    page=Page(self,path,metadata,blob,surface,prepared,sight,liquids)
                    try:
                        staging=metadata.get('collision_staging_key')
                        if staging:self.cache._reader().request('collision_move',**{'from':staging,'to':key})
                    except Exception:page.close();raise
                    if old_page:
                        clocks={p['prop_key']:p.get('animation_clock') for p in old_page.metadata.get('props',[])}
                        for spec in page.metadata.get('props',[]):
                            if clocks.get(spec['prop_key']) is not None:spec['animation_clock']=clocks[spec['prop_key']]
                        self._remove_page(key,preserve_instances={p['instance'] for p in page.metadata.get('props',[])})
                    self.pages[key]=page;self.render_model.append(page.batches);changed=True;self.errors.pop(key,None);self.last_error=''
            except Exception as exc:
                if len(self.errors)>=64:self.errors.pop(next(iter(self.errors)))
                self.last_error=str(exc)[:240];self.errors[self.pending_key]=(time.monotonic()+2,self.last_error)
            self.statusChanged.emit()
        for key in list(self.pages):
            if key not in wanted:self._remove_page(key);changed=True
        if changed:
            self._dedup_props()
            self.revision+=1;self.changed.emit()
        self._visibility(x,y,z)
        if self.pending is None and self.animations.future is None and self.light.future is None and self.horizon.future is None and self.weather.future is None:
            self._evict_extracted()
            self._evict_native()
            for key,spec in wanted.items():
                page=self.pages.get(key)
                if (page is None or window_needed(page,self.position)) and time.monotonic()>=self.errors.get(key,(0,''))[0]:
                    self.pending_key=key;self.pending=self.pool.submit(self._load,key,spec,self.position,page);self.statusChanged.emit();break
            if self.pending is None:self.horizon.schedule()
        # Terrain can arrive before the WMO on which the saved player stands.
        # Release the initial simulation hold only after all required collision
        # pages have committed; a partial floor must not pull a saved pose down.
        if getattr(self,'initial_collision_pending',False) and wanted and all(key in self.pages and not window_needed(self.pages[key],self.position) for key in wanted):
            self.initial_collision_pending=False;self.statusChanged.emit()
    def _evict_extracted(self):
        keep={Path(page.path) for page in self.pages.values()}
        keep.update(Path(art.path) for art in self.light.skyboxes.arts.values())
        # Original actors and their attachments share this cache with terrain.
        # Their asynchronous native poses still stat/read these extracted
        # sources even after Qt has retained the visible geometry/texture.
        retained={Path(model.path) for model in (*self.cache.live_models.values(),*self.cache.attachment_models.values()) if not model.closed}
        keep.update(retained)
        for key,bindings in self.cache._effect_bindings.items():
            if Path(key[0]) in retained:keep.update(Path(path) for path in bindings.values())
        for page in self.pages.values():
            keep.update(Path(p['source']) for p in page.metadata.get('props',[]))
            path=Path(page.path)
            if path.suffix.lower()=='.wmo':
                ids=page.metadata.get('group_window',[g['id'] for g in page.metadata['groups']])
                keep.update(path.with_name(path.stem+f'_{gi:03}.wmo') for gi in ids)
        # Texture bytes are owned by the retained Qt texture, not the extracted file.
        for key,path in list(self.cache.archive_entries.items()):
            if path not in keep:
                self.cache.archive_bytes-=path.stat().st_size;path.unlink();del self.cache.archive_entries[key]
    def _remove_page(self,key,preserve_instances=()):
        page=self.pages.pop(key);self.animations.detach(page,preserve_instances);self.retired_instances.update(p['instance'] for p in page.metadata.get('props',[]) if p.get('instance'));self.render_model.remove(page.batches);page.close()
    def _evict_native(self):
        if self.cache.reader is None or self.cache.reader.closed:return
        used={source for page in self.pages.values() for source in page.metadata.get('prop_sources',[])}
        instances={p['instance'] for page in self.pages.values() for p in page.metadata.get('props',[])}
        for model in (*self.cache.live_models.values(),*self.cache.attachment_models.values()):
            if not model.closed:
                used.add(str(model.path));instances.add(model.instance)
        for instance in getattr(self.cache,'world_instances',set())-instances:self.cache.reader.request('release_instance',instance=instance)
        self.retired_instances.clear()
        for source in getattr(self.cache,'world_sources',set())-used:self.cache.reader.request('unload',path=source)
        self.cache.world_sources=used;self.cache.world_instances=instances
        for key in getattr(self.cache,'world_collision_keys',set())-self.pages.keys():self.cache.reader.request('release_collision',key=key)
        self.cache.world_collision_keys=set(self.pages)
    def _dedup_props(self):
        """Keep one MDDF owner across resident overlapping tiles, until eviction."""
        candidates={}
        for key,page in self.pages.items():
            for spec in page.metadata.get('props',[]):
                if spec['prop_key'].startswith('mddf:'):candidates.setdefault(spec['prop_key'],[]).append(key)
        self.prop_owners={pid:self.prop_owners.get(pid) if self.prop_owners.get(pid) in keys else keys[0] for pid,keys in candidates.items()}
        for key,page in self.pages.items():
            active={p['prop_key'] for p in page.metadata.get('props',[]) if not p['prop_key'].startswith('mddf:') or self.prop_owners.get(p['prop_key'])==key}
            page.surface.active_props=active;page.sight.active_props=active
    def query(self,x,y,z):
        result={'height':None,'loaded':False,'indoors':False,'wmo_claim':False,'group':None,'area_id':0,'impassable':False,'page':'','ground_effect_id':None,'terrain_id':None}
        terrain_area=0;room_area=0
        for key,page in tuple(self.pages.items()):
            h,row=page.surface.sample(x,y,z,props=False)
            if row is None:continue
            if not page.metadata['groups']:
                result['loaded']=True;result['impassable']=bool(row.get('impassable'));terrain_area=row.get('area_id',0)
            if h is not None and (result['height'] is None or h>result['height'] or h==result['height'] and bool(page.metadata['groups'])):
                result.update(height=h,page=key,group=row.get('group'),indoors=False,wmo_claim=False)
                result.update(ground_effect_id=ground_effect_at(row,x,z) if row.get('kind')=='terrain' else None,terrain_id=None)
                room_area=0
                if 'group' in row:
                    group=page.metadata['groups'][row['group']]
                    result.update(indoors=bool(group['interior']) and y<row['bounds'][1][1],area_id=group['area_id'],loaded=True)
                    room_area=group['area_id'] if y<row['bounds'][1][1] else 0
                    result['wmo_claim']=not (group.get('flags',0)&8) and y<row['bounds'][1][1]
                    audio_surface=getattr(page,'audio_surface',None)
                    if audio_surface is not None:
                        _,audio_row=audio_surface.down_ray(x,y+.8,z,props=False)
                        if audio_row is not None and audio_row.get('group')==row['group']:result['terrain_id']=audio_row.get('terrain_id')
        result['area_id']=room_area or terrain_area
        # Object hulls change the walking floor, never the room/area classification.
        for page in tuple(self.pages.values()):
            h,_=page.surface.sample(x,y,z,props=True)
            if h is not None and (result['height'] is None or h>result['height']):result['height']=h
        return result
    def _visibility(self,x,y,z):
        self.last_query=self.query(x,y,z)
        eye_query=self.query(*self.camera.eye) if self.camera else self.last_query
        wet=self.liquid(*self.camera.eye,query=eye_query) if self.camera else None
        kind=wet[1] if wet and self.camera.eye[1]<wet[0][0] else 'DRY'
        if kind=='STILL':kind='WATER'
        if kind!=self._ffx_submersion:
            self._ffx_submersion=kind;self.lightingChanged.emit()
        terrain=None
        if self.camera:
            for terrain_page in self.pages.values():
                if terrain_page.metadata['groups']:continue
                h,_=terrain_page.surface.down_ray(*self.camera.eye,props=False)
                if h is not None and (terrain is None or h>terrain):terrain=h
        for key,page in self.pages.items():
            if not page.metadata['groups']:continue
            room,seeds=camera_seeds(page,self.camera.eye,terrain) if self.camera else (self.last_query['group'] if self.last_query['page']==key and self.last_query['wmo_claim'] else None,())
            signature=(self.camera_key,room,seeds,self.revision)
            if page.visibility_key==signature:continue
            page.visibility_key=signature;visible,page.portal_status=visibility(page.metadata,self.camera,room,seeds)
            page.portal_status.update(room=room,seeds=list(seeds),visible_groups=sorted(visible))
            for batch in page.batches:
                state=dict(batch.row);owners=state.get('owning_groups',[])
                shown=any(g in visible for g in owners) if state.get('prop_key') else state.get('group') in visible
                state['portal_visible']=shown and page.surface.enabled(state)
                state['visible']=state['portal_visible'] and state.get('effect_active',True)
                fog_groups=owners or [state.get('group')]
                fog=page.metadata['groups'][room]['fog'] if room is not None and (self.camera is None or any(g in page.portal_status.get('fogged',[]) for g in fog_groups)) else None
                state['fog']=fog
                if state!=batch.row:batch.row=state;batch.changed.emit()
        claim_key=next((key for key,page in self.pages.items() if page.portal_status.get('room') is not None),'') if self.camera else ''
        claim=self.pages.get(claim_key)
        restrict=claim is not None and claim.portal_status.get('mode')=='PORTAL_RECTANGLES'
        windows=claim.portal_status.get('window_rects',[]) if restrict else []
        for page in self.pages.values():
            if page.metadata['groups']:continue
            signature=(self.camera_key,claim_key if restrict else '',claim.portal_status['room'] if restrict else None,self.revision)
            if page.visibility_key==signature:continue
            page.visibility_key=signature
            for batch in page.batches:
                lo,hi=batch.geo.boundsMin(),batch.geo.boundsMax()
                corners=[(hi.x() if mask&1 else lo.x(),hi.y() if mask&2 else lo.y(),hi.z() if mask&4 else lo.z()) for mask in range(8)]
                portal=page.surface.enabled(batch.row) and (not restrict or any(self.camera.box_visible(corners,rect) for rect in windows))
                shown=portal and batch.row.get('effect_active',True)
                if batch.row.get('visible')!=shown or batch.row.get('portal_visible')!=portal:batch.row={**batch.row,'visible':shown,'portal_visible':portal};batch.changed.emit()
        for batch in self.horizon.batches:
            lo,hi=batch.geo.boundsMin(),batch.geo.boundsMax()
            corners=[(hi.x() if mask&1 else lo.x(),hi.y() if mask&2 else lo.y(),hi.z() if mask&4 else lo.z()) for mask in range(8)]
            shown=not restrict or any(self.camera.box_visible(corners,rect) for rect in windows)
            if batch.row.get('visible')!=shown:batch.row={**batch.row,'visible':shown};batch.changed.emit()
    @Slot('QVariantMap')
    def setView(self,view):
        if self.closed or not self.active:return
        try:
            signature=json.dumps(view,sort_keys=True,separators=(',',':'))
            if signature==self.camera_key:return
            camera=PortalCamera(view)
        except (ValueError,TypeError):return
        self.camera,self.camera_key,self.view=camera,signature,dict(view);self._visibility(*self.position)
    @Slot()
    def clearView(self):
        if self.closed:return
        self.camera=None;self.camera_key=None;self.view=None;self._visibility(*self.position)
    @Slot('QVariantMap',result=QVector3D)
    def solveCamera(self,view):
        from backend.game_engine_adapter_camera import solve
        if self.closed or not self.active:return QVector3D()
        try:return QVector3D(*solve(self,view))
        except (ValueError,TypeError,KeyError):
            self.camera_boom.status={'error':'Invalid camera view'}
            return QVector3D(*self.position)
    @Slot(float)
    def advance(self,delta):
        self.animations.advance(delta)
        if not self.closed and self.active:self.weather.advance();self.light.advance()
    @Property('QVariantMap',notify=lightingChanged)
    def lighting(self):return self.light.state
    @Property('QVariantMap',notify=lightingChanged)
    def ffx(self):
        from backend.game_engine_adapter_ffx import state
        presentation=getattr(self.parent(),'_game_presentation',None)
        switches={name:presentation.runtime_settings.get(name,'1')=='1' for name in ('ffx','ffxGlow','ffxDeath')} if presentation else {}
        return state({**self.light.state,'submersion':self._ffx_submersion if self.active else 'DRY'},switches)
    @property
    def budget_limit(self):return LIMIT
    @Slot('QVariantMap',result=bool)
    def setWeather(self,value):
        if self.closed or not self.active:return False
        try:self.weather.set(value);return True
        except (ValueError,TypeError):return False
    @Slot(QByteArray,result=bool)
    def weatherPacket(self,payload):
        """One decoded SMSG_WEATHER body (1.12.1), after the wire transport.

        This endpoint neither opens a socket nor handles authentication.
        """
        import struct
        if len(payload)!=13:return False
        kind,grade,sound_id,instant=struct.unpack('<IfIB',bytes(payload))
        return self.setWeather({'kind':kind,'grade':grade,'sound_id':sound_id,'instant':instant!=0})
    @Slot('QVariantMap',result=bool)
    def setPlayerMotion(self,value):
        if self.closed or not self.active or not isinstance(value,dict):return False
        facing=value.get('facing');speed=value.get('speed')
        if not isinstance(facing,(list,tuple)) or len(facing)!=3 or any(isinstance(n,bool) or not isinstance(n,(int,float)) or not math.isfinite(n) for n in facing):return False
        length=math.hypot(facing[0],facing[2])
        if length<1e-8 or isinstance(speed,bool) or not isinstance(speed,(int,float)) or not math.isfinite(speed) or not 0<=speed<=200:return False
        self.player_motion={'facing':[facing[0]/length,0.,facing[2]/length],'speed':float(speed)};return True
    @Property('QVariantList',notify=changed)
    def weatherBatches(self):return self.weather.batches
    @Property(QObject,constant=True)
    def weatherModel(self):return self.weather_model
    @Property('QVariantList',notify=changed)
    def horizonBatches(self):return self.horizon.batches
    @Property(float,notify=changed)
    def detailedFar(self):return self.horizon.config['far_clip'] if self.horizon.config['enabled'] else 0.
    @Property(QObject,notify=lightingChanged)
    def cloudGeometry(self):return self.light.clouds.geometry if self.light.clouds else None
    @Property(QObject,notify=lightingChanged)
    def cloudTexture(self):return self.light.clouds.texture if self.light.clouds else None
    @Property('QVariantList',notify=lightingChanged)
    def skySprites(self):return self.light.art.sprites if self.light.art else []
    @Property(QObject,constant=True)
    def skyboxModel(self):return self.skybox_model
    @Property(bool,notify=lightingChanged)
    def skyboxReplacesCelestial(self):return self.light.skyboxes.replaces_celestial
    @Property('QVariantList',notify=lightingChanged)
    def skyStars(self):return self.light.art.stars if self.light.art else []
    def liquid(self,x,y,z,query=None):
        query=query or self.query(x,y,z);inside=query['wmo_claim'];hit=None
        if inside:
            page=self.pages.get(query['page']);group=query['group']
            kind=page.metadata['groups'][group].get('flooded_kind') if page is not None and group is not None else None
            if kind:return ((3.4028234663852886e38,0.,0.),kind)
        for key,page in tuple(self.pages.items()):
            if inside and key!=query['page']:continue
            candidate=page.liquids.sample(x,y,z,inside)
            if candidate is not None and (hit is None or candidate[0][0]<hit[0][0]):hit=candidate
        return hit
    def water_sample(self,x,y,z):
        hit=self.liquid(x,y,z);height,sx,sz=hit[0] if hit else (-100001.,0.,0.);length=math.sqrt(1+sx*sx+sz*sz);volume=height>1e30
        return {'height_m':height,'slope':{'x':sx,'z':sz},'current_mps':{'x':0.,'z':0.},'vertical_velocity_mps':0.,
                'normal':{'x':-sx/length,'y':1/length,'z':-sz/length},'wave_height_m':0.,'has_surface':not volume,'surface_model':'GG_ENGINE_FLOODED_VOLUME' if volume else 'GG_ENGINE_WET_GRID' if hit else 'GG_ENGINE_NO_LIQUID','body_kind':hit[1] if hit else 'NONE'}
    def ground(self,x,y,z):
        q=self.query(x,y,z)
        if q['height'] is not None:return q['height']
        if q['loaded']:return -100000. # An authored hole has no replacement GG floor.
        return self.safe[1]-.65 if self.safe is not None else y-.65
    def collide(self,x,y,z):
        q=self.query(x,y,z)
        if not q['loaded'] or q['impassable']:
            return (self.safe[0],self.safe[2]) if self.safe else (self.config['spawn'][0],self.config['spawn'][2])
        for page in self.pages.values():x,z=page.surface.walls(x,y,z)
        self.safe=(x,y,z);return x,z
    def ceiling(self,x,y,z):
        values=[page.surface.up_ray(x,y,z) for page in self.pages.values()]
        return min((v for v in values if v is not None),default=None)
    def line_of_sight(self,start,end):return all(page.sight.line_of_sight(start,end) for page in self.pages.values())
    @Property('QVariantList',notify=changed)
    def batches(self):return [batch for page in self.pages.values() for batch in page.batches]
    @Property(QObject,constant=True)
    def model(self):return self.render_model
    @Property(bool,notify=changed)
    def active(self):return self.config is not None and not self.closed
    @Property(bool,notify=statusChanged)
    def loading(self):return self.pending is not None or getattr(self,'initial_collision_pending',False)
    @Property(str,notify=statusChanged)
    def error(self):return self.last_error
    def status(self):return {'schema':'gg.engine-stream.v1','active':self.active,'resident':list(self.pages),'pending':self.pending_key if self.pending else None,'budget_bytes':self.bytes,'budget_limit':LIMIT,'revision':self.revision,'error':self.last_error,'surface':self.query(*self.position),
        'liquid':self.water_sample(*self.position),'liquid_surfaces':sum(len(p.liquids.grids) for p in self.pages.values()),'portals':{k:p.portal_status for k,p in self.pages.items() if p.metadata['groups']},
        'world_objects':sum(len(page.metadata.get('props',[])) for page in self.pages.values()),'unique_ADT_objects':len(self.prop_owners),
        'wmo_windows':{key:{'groups':page.metadata['group_window'],'total':len(page.metadata['groups'])} for key,page in self.pages.items() if page.metadata.get('group_window')},
        'animation':{'clock_ms':int(self.clock_ms),'frames':self.animations.frames,'pending':self.animations.future is not None,'error':self.animations.error},
        'horizon':self.horizon.status(),'weather':self.weather.status(),'camera_arm':dict(self.camera_boom.status),'collision_recovery':{'restores':self.collision_restores,'pages':self.restored_collision_pages},
        'lighting':{'source':self.light.state['source'],'frames':self.light.frames,'error':self.light.error},'skybox':self.light.skyboxes.status(),
        'limitations':sorted({note for page in self.pages.values() for note in page.metadata.get('limitations',[])}|self.animations.notes)[:64]}
    def environment(self,x,y,z):
        q=self.query(x,y,z);names=self.config.get('areas',{});zone=str(self.config.get('name',self.config['map']))[:128];subzone=str(names.get(str(q['area_id']),''))[:128]
        water=self.water_sample(x,y,z)
        return {'zone':zone,'real_zone':zone,'subzone':subzone,'minimap':subzone or zone,'region_id':self.config['map'],'place_id':q['page'] if q['indoors'] else '',
                'biome':'WORLD','cell':q['page'],'indoors':q['indoors'],'area_id':q['area_id'],'wmo_group':q['group'] if q['group'] is not None else -1,'world_loaded':q['loaded'],'world_page':q['page'],
                'liquid_kind':water['body_kind'],'liquid_surface':water['height_m'],'submerged':y<water['height_m']}
    def interior_audio_at(self,x,y,z):
        q=self.query(x,y,z)
        if q['indoors'] and q['page'] in self.pages and q['group'] is not None:
            group=self.pages[q['page']].metadata['groups'][q['group']]
            return {k:group.get(k,0) for k in ('wmo_id','name_set','group_id')}
        return None
    def close(self):
        if self.closed:return
        from backend import game_engine_host
        runtime=game_engine_host._RUNTIME
        with runtime._lock:
            if getattr(runtime,'_engine_world',None) is self:runtime._engine_world=None
        self.closed=True
        if self.pending:
            try:self.pending.result(timeout=5)
            except Exception:pass
        self.pool.shutdown(wait=True,cancel_futures=True);self.pending=None
        self.light.finish()
        self.light.close()
        self.horizon.close()
        self.weather.close()
        self.render_model.clear()
        for page in self.pages.values():self.animations.detach(page,force=True);page.close()
        self.animations.finish();self.pages.clear();self.prop_owners.clear();self.cache.close();self.config=None;self.camera=None;self.camera_key=None;self.view=None;self.changed.emit()

def world_for(host):
    if not hasattr(host,'_engine_world_stream'):host._engine_world_stream=WorldStream(host)
    return host._engine_world_stream

def load_world(host,manifest,*,resume=None):
    from backend import game_engine_host
    from backend.game_engine_adapter_pet_world import begin,settle,leave,scope
    runtime=game_engine_host._RUNTIME;stream=world_for(host)
    if not manifest:
        with runtime._lock:
            from backend.game_engine_adapter_world_state import clear
            clear(runtime)
            if getattr(runtime,'_engine_world',None) is stream:
                runtime._engine_world=None
                if hasattr(stream,'return_position') and getattr(stream,'return_scope',scope(runtime))==scope(runtime):
                    if hasattr(stream,'return_pose'):
                        for key,value in stream.return_pose.items():getattr(runtime,'_'+key)[0]=value
                    else:runtime._x[0],runtime._y[0],runtime._z[0]=stream.return_position
                leave(runtime,stream)
                from backend.game_engine_adapter_spell_bindings import leave as leave_spells
                leave_spells(runtime,stream)
                runtime._ui_snapshot_base=None;runtime._render_snapshot_cache=None
            stream.close()
        # Keep the published QObject alive until existing QML bindings release it.
        del host._engine_world_stream
        return {'ok':True,'active':False}
    attached=False;previous=None
    try:
        with runtime._lock:
            if getattr(runtime,'_engine_world',None) is not None:raise ValueError('Another world provider is active')
        stream.configure(manifest)
        if resume and stream.manifest_digest!=resume['descriptor']['manifest_digest']:raise ValueError('Saved world manifest changed while loading')
        from backend.game_engine_adapter_spell_bindings import prepare,install
        with runtime._lock:
            definitions=json.loads(json.dumps(runtime._content.get('abilities',{})))
            level=runtime._progression.get('level',1)
            prepared_scope=scope(runtime)
        spell_bindings=prepare(stream.cache,stream.config.get('spell_bindings',[]),definitions,level)
        from backend.game_engine_adapter_triggers import prepare as prepare_triggers
        with runtime._lock:quests=json.loads(json.dumps(runtime._quest_catalog))
        trigger_rows=prepare_triggers(stream.cache,stream.config,quests)
        with runtime._lock:
            if scope(runtime)!=prepared_scope:raise ValueError('World character changed while loading')
            if getattr(runtime,'_engine_world',None) is not None:raise ValueError('Another world provider is active')
            previous=(runtime._x[0],runtime._y[0],runtime._z[0],runtime._vx[0],runtime._vy[0],runtime._vz[0])
            stream.return_position=previous[:3];stream.return_scope=scope(runtime)
            stream.return_pose={k:getattr(runtime,'_'+k)[0] for k in ('x','y','z','yaw','vx','vy','vz')}
            stream.initial_collision_pending=True
            runtime._engine_world=stream;attached=True
            if resume:
                if stream.config['map']!=resume['descriptor']['map']:raise ValueError('Saved world map identity changed')
                stream.return_pose=dict(resume['descriptor']['return_pose'])
                stream.return_position=tuple(stream.return_pose[k] for k in ('x','y','z'))
                for key,value in resume['player'].items():getattr(runtime,'_'+key)[0]=value
                # Collision during the initial async page load must hold the
                # saved pose, never send the player back to manifest spawn.
                stream.safe=(runtime._x[0],runtime._y[0],runtime._z[0])
            else:
                runtime._x[0],runtime._y[0],runtime._z[0]=stream.config['spawn'];runtime._vx[0]=0.;runtime._vy[0]=0.;runtime._vz[0]=0.
            try:stream.update(runtime._x[0],runtime._y[0],runtime._z[0])
            except (ValueError,OSError,RuntimeError,TimeoutError):
                runtime._engine_world=None
                runtime._x[0],runtime._y[0],runtime._z[0],runtime._vx[0],runtime._vy[0],runtime._vz[0]=previous
                attached=False;raise
            begin(runtime,stream);settle(runtime,stream)
            if resume:
                from backend.game_engine_adapter_pet_world import restore_saved
                restore_saved(runtime,stream,resume['descriptor'].get('pet_return'),resume.get('pet'))
            install(runtime,stream,spell_bindings)
            stream._trigger_rows=trigger_rows;stream._trigger_inside=None
            runtime._ui_snapshot_base=None;runtime._render_snapshot_cache=None
            from backend.game_engine_adapter_world_state import clear
            clear(runtime)
        return {'ok':True,'active':True,'map':stream.config['map']}
    except (ValueError,OSError,RuntimeError,TimeoutError) as exc:
        if attached:
            with runtime._lock:
                if getattr(runtime,'_engine_world',None) is stream:
                    runtime._engine_world=None
                    runtime._x[0],runtime._y[0],runtime._z[0],runtime._vx[0],runtime._vy[0],runtime._vz[0]=previous
                    leave(runtime,stream)
        if getattr(runtime,'_engine_world',None) is not stream:stream.close();del host._engine_world_stream
        return {'ok':False,'error':str(exc)[:240]}

def update_world(host):
    from backend import game_engine_host
    stream=getattr(host,'_engine_world_stream',None);runtime=game_engine_host._RUNTIME
    with runtime._lock:
        from backend.game_engine_adapter_world_state import resume_for
        pending=getattr(runtime,'_mounted_world_resume',None)
        if pending and getattr(runtime,'_engine_world',None) is None:
            if stream is not None:
                load_world(host,'')
                runtime._mounted_world_resume=pending
            resume_for(host,runtime)
            stream=getattr(host,'_engine_world_stream',None)
    if stream is not None and stream.active:
        with runtime._lock:
            from backend.game_engine_adapter_pet_world import scope,settle
            if hasattr(stream,'return_scope') and stream.return_scope!=scope(runtime):
                load_world(host,'');return
            try:
                speed=math.hypot(runtime._vx[0],runtime._vz[0])
                if runtime._vehicle_kind=='NONE' and runtime._movement_mode=='GROUND':
                    from backend import game_engine_controller as controller
                    inputs=runtime._input
                    forward=inputs.get('forward',inputs.get('throttle',0));strafe=inputs.get('strafe',0)
                    _,_,strength=controller.movement_direction(math.degrees(runtime._yaw[0]),forward,strafe)
                    speed=(controller.SPRINT_SPEED_MPS if inputs.get('boost') else controller.GROUND_SPEED_MPS)*strength if runtime._running else 0.
                stream.setPlayerMotion({'facing':[math.sin(runtime._yaw[0]),0.,math.cos(runtime._yaw[0])],'speed':min(200,speed)})
                stream.update(runtime._x[0],runtime._y[0],runtime._z[0])
                settle(runtime,stream)
            except (ValueError,OSError,RuntimeError,TimeoutError) as exc:
                stream.last_error=str(exc)[:240];stream.statusChanged.emit()
