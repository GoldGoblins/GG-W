"""Original WDL heights and an eight-tile loader on the world's existing lane."""
import math,struct,time
from PySide6.QtCore import QObject
from backend.game_engine_adapter_formats import NativeFormats,PROJECT
from backend.game_engine_adapter_models import Batch

TILE=struct.unpack('<f',struct.pack('<f',533.3333))[0]
HEIGHT_BYTES=545*2
def settings(value):
    if value is None:value={}
    if isinstance(value,bool):value={'enabled':value}
    if not isinstance(value,dict):raise ValueError('World horizon must be an object or boolean')
    enabled=value.get('enabled',True);far=value.get('far_clip',350)
    if not isinstance(enabled,bool) or isinstance(far,bool) or not isinstance(far,(int,float)) or not math.isfinite(far) or not 177<=far<=777:raise ValueError('Invalid horizon view distance')
    return {'enabled':enabled,'far_clip':float(far)}

class Heights:
    """Compact full-map oracle with the original centre-fan interpolation."""
    def __init__(self,metadata,data):
        tiles=metadata['tiles']
        if len(tiles)>4096 or len(data)!=len(tiles)*HEIGHT_BYTES:raise ValueError('Invalid WDL height buffer')
        self.data=data;self.offsets={}
        for i,row in enumerate(tiles):
            x,y,offset=row['x'],row['y'],row['offset']
            if any(isinstance(n,bool) or not isinstance(n,int) for n in (x,y,offset)) or not 0<=x<64 or not 0<=y<64 or offset!=i*HEIGHT_BYTES or (x,y) in self.offsets:raise ValueError('Invalid WDL height tile')
            self.offsets[x,y]=offset
    def sample(self,x,y):
        # The original height_at takes f32 world coordinates, then uses f64 for
        # its lattice. Keep that boundary, including at negative coordinates.
        x,y=(struct.unpack('<f',struct.pack('<f',n))[0] for n in (x,y))
        cs=float(TILE)/16;gr=(32*TILE-x)/cs;gc=(32*TILE-y)/cs
        if not 0<=gr<1024 or not 0<=gc<1024:return None
        rr,cc=int(gr),int(gc);offset=self.offsets.get((cc//16,rr//16))
        if offset is None:return None
        r,c=rr%16,cc%16
        def h(r,c):return struct.unpack_from('<h',self.data,offset+2*(r*17+c))[0]
        tl,tr,bl,br=h(r,c),h(r,c+1),h(r+1,c),h(r+1,c+1)
        ctr=struct.unpack_from('<h',self.data,offset+2*(289+r*16+c))[0];v,u=gr-rr,gc-cc
        if v<=u and v<=1-u:a,b,t,s=tl,tr,u,v
        elif v>=u and v>=1-u:a,b,t,s=bl,br,u,1-v
        elif u<v:a,b,t,s=tl,bl,v,u
        else:a,b,t,s=tr,br,v,1-u
        if s>=.5:result=ctr
        else:
            edge=a+(b-a)*(t-s)/(1-2*s);result=edge+(ctr-edge)*s*2
        return struct.unpack('<f',struct.pack('<f',result))[0]

class Tile(QObject):
    def __init__(self,horizon,row,data):
        super().__init__(horizon.stream);self.horizon=horizon;self.bytes=0;self.closed=False;self.batch=None
        try:self.batch=Batch(horizon.stream.cache,PROJECT/'qml',row,data,self)
        except Exception:self.close();raise
    def reserve(self,n):
        stream=self.horizon.stream
        if stream.bytes+n>stream.budget_limit:raise ValueError('WDL ring exceeds world residency budget')
        stream.bytes+=n;self.bytes+=n
    def release(self,n):self.horizon.stream.bytes-=n;self.bytes-=n
    def close(self):
        if self.closed:return
        self.closed=True;self.horizon.stream.bytes-=self.bytes;self.bytes=0;self.deleteLater()

class Horizon:
    def __init__(self,stream):
        self.stream=stream;self.config=settings(False);self.future=None;self.stage='OFF';self.error='';self.heights=None;self.tiles={};self.desired=set();self.bytes=0;self.frames=0;self.retry=0
    def configure(self,value):
        self.config=settings(value);self.stage='WAITING' if self.config['enabled'] else 'OFF'
    def _load(self):
        s=self.stream
        if s.cache.archive_source is None:return None
        try:return NativeFormats._unpack(s.cache._reader().request('wdl_load',map=s.config['map'],timeout=4))
        except ValueError as exc:
            from backend.game_engine_adapter_celestial import missing
            if missing(exc):return None
            raise
    def _mesh(self,tiles):
        s=self.stream
        return NativeFormats._unpack(s.cache._reader().request('wdl_tiles',tiles=tiles,origin=s.config['origin'],timeout=2))
    def finish(self):
        if self.future is None or not self.future.done():return
        future,self.future=self.future,None;s=self.stream
        try:
            packet=future.result()
            if s.closed:return
            if self.stage=='LOADING':
                if packet is None:self.stage='UNAVAILABLE';return
                meta,data=packet;heights=Heights(meta,data);cost=meta['native_bytes']+len(data)
                if s.bytes+cost>s.budget_limit:raise ValueError('WDL map exceeds world residency budget')
                self.heights=heights;self.bytes=cost;s.bytes+=cost;self.stage='READY'
            else:
                meta,data=packet
                for row in meta['rows']:
                    key=tuple(row['tile'])
                    if key in self.desired and key not in self.tiles:self.tiles[key]=Tile(self,row,data)
                self.frames+=1
            self.error='';s.changed.emit();s._visibility(*s.position)
        except (ValueError,OSError,RuntimeError,TimeoutError) as exc:
            self.error=str(exc)[:240];self.retry=time.monotonic()+2
            if self.stage=='LOADING':
                self.stage='ERROR'
                if s.cache.reader is not None and not s.cache.reader.closed:
                    try:s.cache.reader.request('wdl_release')
                    except (ValueError,OSError,RuntimeError,TimeoutError):pass
        s.statusChanged.emit()
    def schedule(self):
        s=self.stream;self.finish()
        if s.closed or not self.config['enabled'] or self.future is not None:return
        if self.stage=='WAITING':
            if s.cache.archive_source is None:self.stage='UNAVAILABLE';return
            self.stage='LOADING';self.future=s.pool.submit(self._load);return
        if self.stage!='READY':return
        from backend.game_engine_adapter_streaming import tile_at
        eye=s.camera.eye if s.camera else s.position;cx,cy=tile_at(eye[0],eye[2],s.config['origin'])
        self.desired={key for key in self.heights.offsets if abs(key[0]-cx)<=5 and abs(key[1]-cy)<=5}
        removed=False
        for key in list(self.tiles):
            if key not in self.desired:self.tiles.pop(key).close();removed=True
        if removed:s.changed.emit()
        missing=sorted(self.desired-self.tiles.keys(),key=lambda p:((p[0]-cx)**2+(p[1]-cy)**2,p[1],p[0]))[:8]
        if missing and time.monotonic()>=self.retry:self.future=s.pool.submit(self._mesh,missing)
    def height(self,x,z):
        if self.heights is None:return None
        origin=self.stream.config['origin'];return self.heights.sample(x+origin[0],origin[1]-z)
    @property
    def batches(self):return [tile.batch for tile in self.tiles.values()]
    def status(self):return {'stage':self.stage,'tiles':len(self.tiles),'map_tiles':len(self.heights.offsets) if self.heights else 0,'bytes':self.bytes+sum(t.bytes for t in self.tiles.values()),'frames':self.frames,'pending':self.future is not None,'error':self.error}
    def close(self):
        self.future=None
        for tile in self.tiles.values():tile.close()
        self.tiles.clear();self.stream.bytes-=self.bytes;self.bytes=0;self.heights=None;self.stage='OFF'
