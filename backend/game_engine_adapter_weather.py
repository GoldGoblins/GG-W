"""Real-time original weather on the world's bounded loader and retained Qt instances."""
import math,time
from pathlib import Path
from PySide6.QtCore import QObject,QTimer
from backend.game_engine_adapter_formats import NativeFormats
from backend.game_engine_adapter_models import Batch
TEXTURES=('raindrop01','raindropsplash01','snowflake01','snowflake01','snowmist01')
KINDS={'FINE':0,'RAIN':1,'SNOW':2,'SAND':3}
def settings(value):
    if value is None:return None
    if not isinstance(value,dict):raise ValueError('World weather must be an object')
    kind=value.get('kind','FINE');grade=value.get('grade',0);quality=value.get('quality',3);instant=value.get('instant',False);sound_id=value.get('sound_id',0)
    if isinstance(kind,str):kind=KINDS.get(kind.upper())
    if isinstance(kind,bool) or not isinstance(kind,int) or not 0<=kind<=0xffffffff:raise ValueError('Invalid weather type')
    if isinstance(grade,bool) or not isinstance(grade,(float,int)) or not math.isfinite(grade) or not 0<=grade<=1:raise ValueError('Invalid weather grade')
    if not isinstance(instant,bool) or isinstance(quality,bool) or not isinstance(quality,int) or not 0<=quality<=3:raise ValueError('Invalid weather quality/transition')
    if isinstance(sound_id,bool) or not isinstance(sound_id,int) or not 0<=sound_id<=0xffffffff:raise ValueError('Invalid weather sound kit')
    return {'kind':kind,'grade':grade,'quality':quality,'instant':instant,'sound_id':sound_id}

class Layer(QObject):
    def __init__(self,weather,row,data,image):
        super().__init__(weather.stream);self.weather=weather;self.bytes=0;self.closed=False;self.batch=None
        try:
            self.batch=Batch(weather.stream.cache,Path(weather.stream.config['directory']),row,data,self)
            self.batch.set_image(image,('weather',TEXTURES[row['layer']]))
            from backend.game_engine_adapter_mips import install_table
            install_table(self.batch,[self.batch.row.get('mip_levels',[])])
        except Exception:self.close();raise
    def reserve(self,n):
        s=self.weather.stream
        if s.bytes+n>s.budget_limit:raise ValueError('Weather buffers exceed world residency budget')
        s.bytes+=n;self.bytes+=n
    def release(self,n):self.weather.stream.bytes-=n;self.bytes-=n
    def close(self):
        if self.closed:return
        self.closed=True;self.weather.stream.bytes-=self.bytes;self.bytes=0;self.deleteLater()

class WeatherFrameRejected(ValueError):
    def __init__(self,message,commands):super().__init__(message);self.commands=list(commands)

class Weather:
    def __init__(self,stream):
        self.stream=stream;self.clock=time.monotonic;self.epoch=self.clock();self.future=None;self.config=None;self.pending=[];self.history=[];self.reader=None;self.layers={};self.images={};self.native_bytes=0;self.image_bytes=0;self.frames=0;self.next_ms=0;self.last_player=None;self.state={'kind':'FINE','density':0,'storm_blend':0,'counts':[0]*5,'pending':[0,0],'draw':False};self.error='';self.missing=[]
        self.timer=QTimer(stream);self.timer.setInterval(16);self.timer.timeout.connect(self._tick)
    def _tick(self):
        if self.stream.active:self.advance();self.stream.light.advance()
    def configure(self,value):
        value=settings(value)
        if value is not None:self.set(value)
    def now_ms(self):return max(0,int((self.clock()-self.epoch)*1000))
    def set(self,value):
        cfg=settings(value)
        if cfg is None:raise ValueError('Weather update requires a weather object')
        if len(self.pending)>=32:raise ValueError('Weather command queue capacity exceeded')
        command=(self.now_ms(),cfg);self.pending.append(command);self.history=(self.history+[command])[-2:];self.config=cfg;self.timer.start()
    def request(self,now):
        s=self.stream;player=s.position
        if self.last_player is None:speed=0
        else:
            old_ms,old=self.last_player;dt=(now-old_ms)/1000
            speed=min(200,math.hypot(player[0]-old[0],player[2]-old[2])/dt) if dt>0 else 0
        self.last_player=now,player
        view=s.view or {'eye':list(player),'forward':[0,0,-1],'up':[0,1,0],'fov':60}
        facing=view['forward']
        if s.player_motion is not None:speed=s.player_motion['speed'];facing=s.player_motion['facing']
        eye=view['eye'];claim=next((p for p in s.pages.values() if p.portal_status.get('room') is not None),None)
        sealed=claim is not None and claim.portal_status.get('mode')=='PORTAL_RECTANGLES' and not claim.portal_status.get('window_rects')
        water=s.water_sample(*eye);submerged=water['body_kind']!='NONE' and eye[1]<water['height_m']
        return {'now_ms':now,'view':view,'player':list(player),'facing':facing,'speed':speed,'collision_revision':s.revision,'draw':bool(s.camera and not sealed and not submerged),'fog':s.light.state.get('fog',{}).get('color',[0,0,0]) if s.light.state.get('fog') else [0,0,0]}
    def advance(self):
        self.finish();s=self.stream
        if self.config is None or self.future is not None or s.closed:return
        now=self.now_ms()
        if now<self.next_ms or s.pending is not None or s.horizon.future is not None or s.animations.future is not None or s.light.future is not None:return
        if s.light.config is not None and s.light.due():return
        if any(key not in s.pages and time.monotonic()>=s.errors.get(key,(0,''))[0] for key in s.desired(s.position[0],s.position[2])):return
        self.next_ms=now+16;commands,self.pending=self.pending,[];self.future=s.pool.submit(self._sample,self.request(now),commands,tuple(self.history))
    def _sample(self,value,commands,history):
        s=self.stream;reader=s.cache._reader()
        if self.reader is not None and reader is not self.reader:
            # A worker restart loses the ramp along with its transient particles.
            # Two endpoints reconstruct the original old-target law exactly,
            # including instant updates, while retaining the original epochs.
            commands=history
        reader.request('weather_checkpoint')
        try:
            for now,cfg in commands:reader.request('weather_set',now_ms=now,**cfg)
            packet=self._prepare(reader,value)
            state,packets,images,missing=packet
            image_cost=sum(image.sizeInBytes() for name,image in images.items() if name not in self.images)
            growth=0
            for key,row,data,image in packets:
                if key not in self.layers and row['instance_count']:
                    growth+=(row['vertices']*row['stride']+len(row['indices'])*4)*2+row['instance_capacity']*80*3+image.sizeInBytes()*2+16*16*2
            if self.stream.bytes+state['native_bytes']-self.native_bytes+image_cost+growth>self.stream.budget_limit:
                raise ValueError('Weather simulation and draw pages exceed world residency budget')
            reader.request('weather_commit');self.reader=reader
            return packet
        except Exception as exc:
            try:reader.request('weather_rollback')
            except Exception:reader.close()
            raise WeatherFrameRejected(str(exc),commands) from exc
    def _prepare(self,reader,value):
        s=self.stream
        state=reader.request('weather_frame',timeout=3,**value);packets=[];images={};missing=[]
        if state['draw']:
            for kind,count in enumerate(state['counts']):
                if not count:continue
                name=TEXTURES[kind];image=self.images.get(name)
                if image is None:
                    try:
                        from backend.game_engine_adapter_mips import atlas
                        texture=s.cache._texture('textures/weather/'+name+'.blp',Path(s.config['directory'])/'world.wdt')
                        metadata,pixels=s.cache.decode(texture,mip_chain=True);image,_=atlas(metadata,pixels)
                    except (OSError,ValueError) as exc:
                        from backend.game_engine_adapter_celestial import missing as unavailable
                        if unavailable(exc):missing.append(name);continue
                        raise
                    images[name]=image
                offset=0
                while True:
                    meta,data=NativeFormats._unpack(reader.request('weather_draw',kind=kind,offset=offset,limit=32768,generation=state['generation'],timeout=3));row=meta['row']
                    packets.append(((kind,offset),row,data,image))
                    if meta['next'] is None:break
                    offset=meta['next']
        return state,packets,images,missing
    def finish(self):
        if self.future is None or not self.future.done():return
        future,self.future=self.future,None;s=self.stream
        try:
            state,packets,images,missing=future.result()
            if s.closed:return
            image_cost=sum(image.sizeInBytes() for name,image in images.items() if name not in self.images)
            difference=state['native_bytes']-self.native_bytes+image_cost
            growth=0;staged={}
            for key,row,data,image in packets:
                count=row['instance_count'];offset=row['instance_offset'];layer=self.layers.get(key)
                capacity=layer.batch.instances.capacity if layer else row['instance_capacity']
                if not 0<=count<=capacity or offset<0 or offset+count*80>len(data):raise ValueError('Invalid weather instance page')
                if row['vertices']<1 or row['offset']<0 or row['offset']+row['vertices']*row['stride']>len(data):raise ValueError('Invalid weather mesh page')
                if layer is None and count:
                    growth+=(row['vertices']*row['stride']+len(row['indices'])*4)*2+capacity*80*3+image.sizeInBytes()*2+16*16*2
            if s.bytes+difference+growth>s.budget_limit:raise ValueError('Weather simulation and draw pages exceed world residency budget')
            # Allocate every new layer before changing existing instance tables,
            # images, model rows or the published state. A rejected frame keeps
            # the previously visible snapshot and all its Qt identities.
            s.bytes+=difference
            try:
                for key,row,data,image in packets:
                    if key not in self.layers and row['instance_count']:staged[key]=Layer(self,row,data,image)
            except Exception:
                for layer in staged.values():layer.close()
                s.bytes-=difference;raise
            self.native_bytes=state['native_bytes'];self.image_bytes+=image_cost;self.images.update(images);updated=set()
            for key,row,data,image in packets:
                layer=self.layers.get(key)
                if layer is None:
                    if row['instance_count']==0:continue
                    layer=staged[key];self.layers[key]=layer
                else:layer.batch.update(row,data)
                updated.add(key)
            if staged:s.weather_model.append([l.batch for l in staged.values()]);s.changed.emit()
            for key,layer in self.layers.items():
                if key not in updated:
                    layer.batch.instances.update(b'',0)
                    if layer.batch.row.get('visible'):layer.batch.row={**layer.batch.row,'visible':False};layer.batch.changed.emit()
            self.state=state;self.frames+=1;self.error='';self.missing=missing;s.statusChanged.emit()
        except (ValueError,OSError,RuntimeError,TimeoutError) as exc:
            if isinstance(exc,WeatherFrameRejected):self.pending=exc.commands+self.pending
            self.error=str(exc)[:240];self.next_ms=self.now_ms()+2000;s.statusChanged.emit()
    @property
    def batches(self):return [layer.batch for layer in self.layers.values()]
    def status(self):return {**self.state,'frames':self.frames,'bytes':self.native_bytes+self.image_bytes+sum(l.bytes for l in self.layers.values()),'queued_updates':len(self.pending),'sampling':self.future is not None,'error':self.error,'missing_textures':self.missing}
    def close(self):
        self.timer.stop()
        self.future=None
        self.stream.weather_model.clear()
        for layer in self.layers.values():layer.close()
        self.layers.clear();self.stream.bytes-=self.native_bytes+self.image_bytes;self.native_bytes=0;self.image_bytes=0;self.images.clear();self.pending=[];self.history=[];self.reader=None
