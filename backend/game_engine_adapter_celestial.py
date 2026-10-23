"""Retained celestial art, original fallbacks, and original flare terrain march."""
import math,struct
from pathlib import Path
from PySide6.QtCore import QObject,Property,QSize
from PySide6.QtGui import QImage,QVector3D
from PySide6.QtQuick3D import QQuick3DGeometry,QQuick3DTextureData
from backend.game_engine_adapter_formats import NativeFormats,PROJECT
from backend.game_engine_adapter_models import Batch

def radial(size,core,edge):
    data=bytearray(size*size*4);c=(size-1)*.5
    for y in range(size):
        for x in range(size):
            r=math.hypot((x-c)/c,(y-c)/c);t=max(0,min(1,(r-core)/(edge-core)));a=1-t*t*(3-2*t);i=(y*size+x)*4;data[i:i+4]=bytes((255,255,255,int(a*255)))
    return QImage(data,size,size,size*4,QImage.Format_RGBA8888).copy()

SPRITES={'sun':('Textures/sunCenter.blp',128,.55,.95),'sun_glare':('Textures/sunGlare.blp',128,0,1),'moon':('Textures/moon.blp',128,.7,.97),'moon_glare':('Textures/moonglare.blp',64,0,1),'moon02':('Textures/moon02.blp',128,.7,.97)}
def missing(exc):return any(word in str(exc).casefold() for word in ('not in patch chain','not found','missing','unavailable','deleted from patch chain'))
def resources(cache):
    """Runs on the existing loader: QImages, bytes and metadata only."""
    images={};fallbacks=[]
    for name,(source,size,core,edge) in SPRITES.items():
        try:
            path=cache.resolve(source)
            if not path.is_file():raise ValueError('Sprite unavailable')
            image=cache.image(path)
        except (OSError,ValueError) as exc:
            if not missing(exc):raise
            image=radial(size,core,edge);fallbacks.append(name)
        images[name]=image
    try:
        source=cache.resolve('Environments/Stars/Stars.m2')
        if not source.is_file():raise ValueError('Star model unavailable')
        metadata,data=NativeFormats._unpack(cache._reader().request('sky_stars',path=str(source),timeout=2))
    except (OSError,ValueError) as exc:
        if not missing(exc):raise
        metadata,data=NativeFormats._unpack(cache._reader().request('sky_stars',timeout=2));fallbacks.append('stars')
    for row in metadata['rows']:
        source=row.get('texture')
        if source in images:continue
        image=None
        if source:
            try:
                path=cache.resolve(source)
                if path.is_file():image=cache.image(path)
            except (OSError,ValueError) as exc:
                if not missing(exc):raise
        if image is None:
            image=radial(32,.2,1) if not source else QImage(1,1,QImage.Format_RGBA8888)
            if source:image.fill(0xffffffff);fallbacks.append(source)
        images[source]=image
    return metadata,data,images,fallbacks

class SkySprite(QObject):
    def __init__(self,art,name,texture):super().__init__(art);self.art=art;self.name=name;self.texture=texture
    @Property(QObject,constant=True)
    def geometry(self):return self.art.geometry
    @Property(QObject,constant=True)
    def textureData(self):return self.texture
    @Property(str,constant=True)
    def spriteName(self):return self.name

class SkyArt(QObject):
    def __init__(self,stream,packet):
        super().__init__(stream);self.stream=stream;self.byte_size=0;self.closed=False;self.stars=[];self.sprites=[];self.textures=[];self.geometry=None
        metadata,data,images,self.fallbacks=packet;self.authored=metadata['authored']
        try:
            vertex=b''.join(struct.pack('<8f',x,y,0,0,0,1,u,v) for x,y,u,v in ((-.5,-.5,0,1),(.5,-.5,1,1),(.5,.5,1,0),(-.5,.5,0,0)));index=struct.pack('<6I',0,1,2,0,2,3);self.reserve((len(vertex)+len(index))*2)
            self.geometry=QQuick3DGeometry();QObject.setParent(self.geometry,self);g=self.geometry;g.setStride(32);g.setPrimitiveType(QQuick3DGeometry.PrimitiveType.Triangles);A=QQuick3DGeometry.Attribute
            for sem,at,kind in ((A.PositionSemantic,0,A.F32Type),(A.NormalSemantic,12,A.F32Type),(A.TexCoord0Semantic,24,A.F32Type),(A.IndexSemantic,0,A.U32Type)):g.addAttribute(sem,at,kind)
            g.setVertexData(vertex);g.setIndexData(index);g.setBounds(QVector3D(-3,-3,-3),QVector3D(3,3,3))
            for name in SPRITES:
                image=images[name];self.reserve(image.sizeInBytes()*3);texture=QQuick3DTextureData();QObject.setParent(texture,self);texture.setSize(image.size());texture.setFormat(QQuick3DTextureData.Format.RGBA8);texture.setTextureData(bytes(image.constBits()));texture.setHasTransparency(True);self.textures.append(texture);self.sprites.append(SkySprite(self,name,texture))
            for row in metadata['rows']:
                batch=Batch(stream.cache,PROJECT/'qml',{**row,'texture':None,'visible':True},data,self);self.stars.append(batch);batch.set_image(images[row.get('texture')],('sky-star',row.get('texture')))
        except Exception:self.close();raise
    def reserve(self,size):
        if self.stream.bytes+size>self.stream.budget_limit:raise ValueError('Celestial art exceeds world residency budget')
        self.stream.bytes+=size;self.byte_size+=size
    def release(self,size):self.stream.bytes-=size;self.byte_size-=size
    def close(self):
        if self.closed:return
        self.closed=True;self.stream.bytes-=self.byte_size;self.byte_size=0;self.stars=[];self.sprites=[];self.textures=[];self.deleteLater()

def flare_visibility(stream,light):
    """Original 4x4 quad rays and 48 quadratic terrain samples out to 2800 yd."""
    if not stream.camera or light.get('submersion')!='DRY':return [0,0]
    eye=stream.camera.eye;result=[]
    for name,multiplier in (('sun',1),('moon',1.75)):
        body=light.get('bodies',{}).get(name)
        if not body or body.get('flare',0)<=0:result.append(0);continue
        d=body['direction'];length=math.sqrt(sum(p*p for p in d));d=[p/length for p in d]
        r=[-d[2],0,d[0]];length=math.hypot(r[0],r[2]);r=[p/length for p in r] if length>1e-6 else [1,0,0];up=[r[1]*d[2]-r[2]*d[1],r[2]*d[0]-r[0]*d[2],r[0]*d[1]-r[1]*d[0]]
        half=math.atan(.5*.0833*multiplier*body['scale']);clear=0
        for cell in range(16):
            u=(cell//4+.5)/4-.5;v=(cell%4+.5)/4-.5;ray=[d[i]+r[i]*(u*2*half)+up[i]*(v*2*half) for i in range(3)];length=math.sqrt(sum(p*p for p in ray));ray=[p/length for p in ray];blocked=False
            for k in range(1,49):
                distance=2800*(k/48)**2;p=[eye[i]+ray[i]*distance for i in range(3)]
                fine=False
                for page in stream.pages.values():
                    if page.metadata['groups']:continue
                    h,row=page.surface.sample(p[0],p[1],p[2],props=False)
                    if row and row.get('kind')=='terrain' and h is not None:
                        fine=True
                        if h>p[1]:blocked=True;break
                if not blocked and not fine:
                    h=stream.horizon.height(p[0],p[2])
                    if h is not None and h>p[1]+stream.config['origin'][2]:blocked=True
                if blocked:break
            clear+=not blocked
        result.append(clear/16)
    return result
