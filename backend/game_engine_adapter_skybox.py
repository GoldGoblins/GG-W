"""Original PVS sky selection, MFOG selector and retained camera-anchored M2s."""
import math
from pathlib import Path
from PySide6.QtCore import QObject
from PySide6.QtGui import QImage
from backend.game_engine_adapter_models import Batch
from backend.game_engine_adapter_formats import NativeFormats

def wmo_sky(stream):
    candidates=[]
    for page in stream.pages.values():
        sky=page.metadata.get('skybox')
        visible=page.portal_status.get('visible_groups',[])
        if sky and any(g['flags']&0x40000 and g['id'] in visible for g in page.metadata['groups']):candidates.append(sky)
    return min(candidates,default=None)

def wmo_fog(stream):
    """The original one-record bail, default seed and four nearest radius folds."""
    if stream.camera is None:return None
    for page in stream.pages.values():
        room=page.portal_status.get('room');records=page.metadata.get('fog_records',[])
        if room is None or len(records)<2 or not page.metadata.get('portals',{}).get('refs'):continue
        group=page.metadata['groups'][room]
        if not group['interior']:continue
        seed=records[0];target={'color':list(seed['color']),'end':seed['end'],'start_scalar':seed['start_scalar']};candidates=[]
        for index in group.get('fog_indices',[]):
            if index>=len(records):continue
            row=records[index]
            if row['flags']&1:continue
            distance=math.dist(stream.camera.eye,row['position'])
            if distance<=row['radius_outer']:candidates.append((distance,row))
        for distance,row in sorted(candidates,key=lambda p:-p[0]):
            span=row['radius_outer']-row['radius_inner'];weight=max(0,min(1,1-(distance-row['radius_inner'])/span)) if span>0 else 1
            target['color']=[a+(b-a)*weight for a,b in zip(target['color'],row['color'])]
            for key in ('end','start_scalar'):target[key]+=(row[key]-target[key])*weight
        return target
    return None

class WmoCrossfade:
    def __init__(self):self.weight=0.;self.staged=None;self.last_ms=0.
    def advance(self,clock_ms,target,dry):
        dt=max(0,(clock_ms-self.last_ms)/1000);self.last_ms=clock_ms
        if not dry:return
        if target is not None:self.staged=target
        self.weight=max(0,min(1,self.weight+(1 if target is not None else -1)*.25*dt))
        if self.weight<=0:self.staged=None
    def fog(self,scene,far_clip):
        if not scene or not self.staged or self.weight<=0:return scene
        target=self.staged;end=min(target['end'],far_clip) if far_clip>0 else target['end'];start=end*target['start_scalar'];k=self.weight
        return {**scene,'color':[a+(b-a)*k for a,b in zip(scene['color'],target['color'])],
                'near':scene['near']+(start-scene['near'])*k,'far':scene['far']+(end-scene['far'])*k}

class SkyboxArt(QObject):
    def __init__(self,owner,name,path,metadata,data,images):
        super().__init__(owner.stream);self.owner=owner;self.stream=owner.stream;self.name=name;self.path=path;self.bytes=0;self.closed=False;self.batches=[]
        try:
            self.reserve(metadata['native_bytes'])
            for row in metadata['rows']:
                batch=Batch(self.stream.cache,path,{**row,'texture':None,'visible':False,'alpha':0,'tint':[1,1,1]},data,self)
                batch.row['authored_blend']=row['blend'];batch.set_image(images[row.get('texture')],('skybox',row.get('texture')));self.batches.append(batch)
        except Exception:self.close();raise
    def reserve(self,n):
        if self.stream.bytes+n>self.stream.budget_limit:raise ValueError('Skybox exceeds world residency budget')
        self.stream.bytes+=n;self.bytes+=n
    def release(self,n):self.stream.bytes-=n;self.bytes-=n
    def close(self):
        if self.closed:return
        self.closed=True;self.stream.bytes-=self.bytes;self.bytes=0;self.deleteLater()

class Skyboxes:
    def __init__(self,stream):self.stream=stream;self.arts={};self.failures={};self.wanted=None;self.weight=0.;self.error='';self.prepared=0
    def prepare(self,wanted,clock,known,available):
        """Only the existing single asset loader calls this method."""
        if not wanted:return None
        path=self.stream.cache.resolve(wanted);reader=self.stream.cache._reader();loaded=False
        try:
            metadata,data=NativeFormats._unpack(reader.request('skybox',path=str(path),clock_ms=clock,geometry=wanted not in known,timeout=3));loaded=True;images={}
            if wanted not in known:
                cost=metadata['native_bytes']
                for row in metadata['rows']:
                    cost+=(row['vertices']*32+len(row['indices'])*4)*2;source=row.get('texture')
                    if source not in images:
                        image=QImage(1,1,QImage.Format_RGBA8888);image.fill(0xffffffff)
                        if source:image=self.stream.cache.image(self.stream.cache._texture(source,path))
                        images[source]=image
                    # Each authored batch currently owns a texture, as the ordinary M2 lane does.
                    cost+=images[source].sizeInBytes()*2
                if cost>available:raise ValueError('Skybox exceeds world residency budget')
            return wanted,path,metadata,data,images
        except Exception:
            if loaded and wanted not in known:reader.request('skybox_unload',path=str(path))
            raise
    def finish(self,packet,wanted):
        if packet:
            name,path,metadata,data,images=packet;art=self.arts.get(name)
            if art is None:
                art=SkyboxArt(self,name,path,metadata,data,images);self.arts[name]=art;self.stream.skybox_model.append(art.batches);self.prepared+=1
            if len(metadata['transforms'])!=len(art.batches):raise ValueError('Skybox batch identity changed')
            for batch,transform in zip(art.batches,metadata['transforms']):
                batch.row={**batch.row,**transform};batch.changed.emit()
        self.wanted=wanted;self.apply(self.weight)
    def apply(self,weight):
        self.weight=weight
        for name,art in self.arts.items():
            for batch in art.batches:
                blend=batch.row['authored_blend'];show=name==self.wanted and weight>0
                state={**batch.row,'visible':show,'alpha':weight if show else 0,'blend':2 if weight<1 and blend<=1 else blend,'fade_key':weight<1 and blend==1}
                if state!=batch.row:batch.row=state;batch.changed.emit()
    def slot(self,light):
        ghost=light.get('skybox')
        if ghost:return ghost,1.
        name=wmo_sky(self.stream);return name,self.stream.light.crossfade.weight if name else 0.
    @property
    def replaces_celestial(self):return self.wanted in self.arts and self.weight>.99
    def status(self):return {'wanted':self.wanted,'weight':self.weight,'replaces_celestial':self.replaces_celestial,'resident':list(self.arts),'bytes':sum(a.bytes for a in self.arts.values()),'failures':dict(self.failures),'prepared':self.prepared}
    def close(self):
        self.stream.skybox_model.clear()
        for art in self.arts.values():art.close()
        self.arts.clear();self.failures.clear();self.wanted=None;self.weight=0
