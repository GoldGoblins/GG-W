"""Atlas texture views borrow the active stream's bounded archive reader."""
import math
from collections import OrderedDict

GG_ATLAS_PATH='assets/authored/world/gg-first-planet-map.svg'
ATLAS_CACHE_BYTES=16*1024*1024
BLIP_CACHE_BYTES=16*1024*1024
BLIP_TEXTURES=frozenset('interface/minimap/'+name for name in ('poiicons','objecticons','rotating-minimaparrow','rotating-minimapgrouparrow','rotating-minimapcorpsearrow','rotating-minimapguidearrow'))


def blip_key(key):
    folded=key.replace('\\','/').casefold().removesuffix('.blp')
    return folded if folded in BLIP_TEXTURES else None


def atlas_texture(canvas,row,device_pixel_ratio=1.0):
    """Rasterize the selected GG vector crop at its destination resolution.

    The caller uses identity texture coordinates for this already cropped
    image. Original archive tiles and arbitrary addon texture UVs retain the
    ordinary renderer. One static source renderer and a bounded image LRU live
    with this canvas; selecting maps never creates large full-world rasters.
    """
    path=str(row.get('path') or '').replace('\\','/').casefold()
    if path!=GG_ATLAS_PATH:return None
    if row.get('tile') or row.get('desaturated') or tuple(row.get('color') or (1,1,1,1))!=(1,1,1,1):return None
    uv=row.get('uv') or [[0,0],[1,0],[1,1],[0,1]]
    if not isinstance(uv,list) or len(uv)!=4 or any(not isinstance(p,(list,tuple)) or len(p)!=2 for p in uv):return None
    values=[n for point in uv for n in point]
    if any(isinstance(n,bool) or not isinstance(n,(int,float)) or not math.isfinite(n) for n in values):return None
    u0,v0=uv[0];u1,v1=uv[2]
    if list(uv[1])!=[u1,v0] or list(uv[3])!=[u0,v1] or u1-u0<1e-6 or v1-v0<1e-6:return None
    dimensions=(row.get('width'),row.get('height'),device_pixel_ratio)
    if any(isinstance(n,bool) or not isinstance(n,(int,float)) or not math.isfinite(n) or n<=0 for n in dimensions):return None
    width=math.ceil(dimensions[0]*device_pixel_ratio);height=math.ceil(dimensions[1]*device_pixel_ratio)
    if width>2048 or height>2048:return None
    from backend.game_engine_adapter_assets import asset_path
    from PySide6.QtCore import QRectF,Qt
    from PySide6.QtGui import QImage,QPainter
    from PySide6.QtSvg import QSvgRenderer
    source=asset_path(GG_ATLAS_PATH)
    try:
        metadata=source.stat();stamp=(metadata.st_mtime_ns,metadata.st_size)
    except OSError:return None
    if getattr(canvas,'_gg_atlas_stamp',None)!=stamp:
        renderer=QSvgRenderer(str(source))
        if not renderer.isValid() or renderer.animated():return None
        renderer.setAspectRatioMode(Qt.IgnoreAspectRatio)
        canvas._gg_atlas_stamp=stamp;canvas._gg_atlas_renderer=renderer
        canvas._gg_atlas_images=OrderedDict();canvas._gg_atlas_bytes=0
    key=(u0,v0,u1,v1,width,height);cache=canvas._gg_atlas_images
    if key in cache:
        image=cache.pop(key);cache[key]=image;return image
    image=QImage(width,height,QImage.Format_RGBA8888_Premultiplied);image.fill(Qt.transparent)
    painter=QPainter(image)
    try:
        painter.setRenderHint(QPainter.Antialiasing);painter.setClipRect(QRectF(0,0,width,height))
        # Clip the source vector transform while preserving its SVG viewport.
        # Only the final crop is allocated, regardless of virtual map zoom.
        canvas._gg_atlas_renderer.render(painter,QRectF(-u0*width/(u1-u0),-v0*height/(v1-v0),width/(u1-u0),height/(v1-v0)))
    finally:painter.end()
    while cache and (len(cache)>=16 or canvas._gg_atlas_bytes+image.sizeInBytes()>ATLAS_CACHE_BYTES):
        _,old=cache.popitem(last=False);canvas._gg_atlas_bytes-=old.sizeInBytes()
    cache[key]=image;canvas._gg_atlas_bytes+=image.sizeInBytes()
    return image


class MapTextures:
    def __init__(self,canvas,stream):
        self.canvas=canvas;self.cache=stream.cache;self.folders=[];self.minimap=[];self.minimap_images={};self.minimap_paths={};self.missing=set()
        self.blips=[];self.blip_images={};self.blip_paths={};self.blip_bytes=0
    def forget(self,old,matches):
        canvas=self.canvas
        self.minimap_images.pop(old,None);self.minimap_paths.pop(old,None)
        image=self.blip_images.pop(old,None);self.blip_paths.pop(old,None)
        if image is not None:self.blip_bytes-=image.sizeInBytes()
        for name in list(canvas.images):
            raw=name[0] if isinstance(name,tuple) else name
            if isinstance(raw,str) and matches(raw.replace('\\','/').casefold()):del canvas.images[name]
        canvas.image_bytes=sum(image.sizeInBytes() for image in canvas.images.values())
        self.missing={p for p in self.missing if not matches(p)}
        # These are disposable MPQ extraction files, never original art.
        for name,path in list(self.cache.archive_entries.items()):
            if matches(name.replace('\\','/').casefold()):
                try:self.cache.archive_bytes-=path.stat().st_size;path.unlink()
                except FileNotFoundError:pass
                del self.cache.archive_entries[name]
    def touch(self,key):
        folded=key.replace('\\','/').casefold();parts=folded.split('/')
        old=None
        if blip_key(folded):
            folded=blip_key(folded)
            if folded in self.blips:self.blips.remove(folded)
            self.blips.append(folded)
            if len(self.blips)>8:old=self.blips.pop(0)
            matches=lambda raw:blip_key(raw)==old
        elif folded.startswith('textures/minimap/'):
            if folded in self.minimap:self.minimap.remove(folded)
            self.minimap.append(folded)
            if len(self.minimap)>16:old=self.minimap.pop(0)
            matches=lambda raw:raw==old
        else:
            folder='/'.join(parts[:3])+'/'
            if folder in self.folders:self.folders.remove(folder)
            self.folders.append(folder)
            if len(self.folders)>2:old=self.folders.pop(0)
            matches=lambda raw:raw.startswith(old)
        if old is not None:self.forget(old,matches)
        return folded
    def texture_path(self,key):
        folded=self.touch(key)
        if folded in self.missing:raise ValueError('Map texture unavailable in mounted archive')
        if folded in self.minimap_images:return self.minimap_paths[folded]
        if folded in self.blip_images:return self.blip_paths[folded]
        try:
            path=self.cache.texture_path(key)
            if folded.startswith('textures/minimap/'):self.minimap_paths[folded]=path
            elif folded in self.blips:self.blip_paths[folded]=path
            return path
        except (OSError,ValueError,RuntimeError,TimeoutError):
            if len(self.missing)<256:self.missing.add(folded)
            raise
    def image(self,path):
        key=next((key for key,value in self.blip_paths.items() if value==path),None)
        if key is not None:
            if key in self.blip_images:return self.blip_images[key]
            try:
                image=self.cache.image(path)
                if image.width()>1024 or image.height()>1024:raise ValueError('Original minimap icon dimensions exceed capacity')
            except (OSError,ValueError,RuntimeError,TimeoutError):
                if len(self.missing)<256:self.missing.add(key)
                raise
            while self.blip_images and self.blip_bytes+image.sizeInBytes()>BLIP_CACHE_BYTES:
                old=next(old for old in self.blips if old in self.blip_images)
                self.blips.remove(old);self.forget(old,lambda raw:blip_key(raw)==old)
            self.blip_images[key]=image;self.blip_bytes+=image.sizeInBytes();return image
        key='textures/minimap/'+path.name.casefold()
        if key not in self.minimap:return self.cache.image(path)
        if key in self.minimap_images:return self.minimap_images[key]
        try:
            image=self.cache.image(path)
            if any(n not in (32,64,128,256) for n in (image.width(),image.height())):raise ValueError('Original minimap tile must have 32..256 power-of-two dimensions')
            self.minimap_images[key]=image;return image
        except (OSError,ValueError,RuntimeError,TimeoutError):
            if len(self.missing)<256:self.missing.add(key)
            raise


def navigation_texture_assets(canvas,key):
    if not key.casefold().startswith(('interface/worldmap/','textures/minimap/')) and not blip_key(key):return None
    parent=getattr(canvas.runtime,'parent',None);host=parent() if callable(parent) else None
    stream=getattr(host,'_engine_world_stream',None)
    if stream is None or not getattr(stream.cache,'archive_source',None):return None
    identity=(id(stream),str(stream.cache.archive_source))
    if getattr(canvas,'_navigation_texture_identity',None)!=identity:
        for name in list(canvas.images):
            raw=name[0] if isinstance(name,tuple) else name
            if isinstance(raw,str) and (raw.replace('\\','/').casefold().startswith(('interface/worldmap/','textures/minimap/')) or blip_key(raw)):del canvas.images[name]
        canvas.image_bytes=sum(image.sizeInBytes() for image in canvas.images.values())
        canvas.missing={p for p in canvas.missing if not p.casefold().startswith(('interface/worldmap/','textures/minimap/')) and not blip_key(p)}
        canvas._navigation_texture_identity=identity;canvas._navigation_textures=MapTextures(canvas,stream)
    canvas._navigation_textures.touch(key)
    return canvas._navigation_textures
