"""Retained Qt geometry driven by the supervised original M2 animation readers."""
import json,struct
from collections import deque
from copy import deepcopy
from pathlib import Path
from PySide6.QtCore import QObject,Property,Signal,QSize
from PySide6.QtGui import QImage,QImageReader,QVector3D
from PySide6.QtQuick3D import QQuick3DGeometry,QQuick3DTextureData

class Batch(QObject):
    changed=Signal()
    def __init__(self,cache,path,row,data,parent):
        super().__init__(parent);self.owner=parent;self.texture_bytes=0;self.texture_key=object();self.row={};self.geo=QQuick3DGeometry();self.tex=QQuick3DTextureData();self.instances=None
        self.mip_lookup=None
        self._authored_mip_sampling='layer' not in row and row.get('kind')!='liquid'
        QObject.setParent(self.geo,self);QObject.setParent(self.tex,self)
        self.stride=int(row.get('stride',32));self.capacity=int(row.get('capacity',row['vertices']));self.dynamic=bool(row.get('dynamic',self.stride==48))
        if self.stride not in (32,48) or self.capacity<row['vertices'] or self.capacity>65536:raise ValueError('Invalid model buffer capacity')
        self.index_capacity=int(row.get('index_capacity',self.capacity//4*6 if self.dynamic else len(row['indices'])))
        if not len(row['indices'])<=self.index_capacity<=393216:raise ValueError('Invalid model index capacity')
        parent.reserve((self.capacity*self.stride+self.index_capacity*4)*2)
        if row.get('instance_capacity'):
            from backend.game_engine_adapter_instances import InstanceTable,STRIDE
            self.instances=InstanceTable(row['instance_capacity'],self,transparent=int(row.get('blend',0))>1)
            parent.reserve(row['instance_capacity']*STRIDE*3)
        self.geo.setStride(self.stride);self.geo.setPrimitiveType(QQuick3DGeometry.PrimitiveType.Triangles)
        attribute=QQuick3DGeometry.Attribute
        for semantic,offset in ((attribute.PositionSemantic,0),(attribute.NormalSemantic,12),(attribute.TexCoordSemantic,24)):self.geo.addAttribute(semantic,offset,attribute.F32Type)
        if self.stride==48:self.geo.addAttribute(attribute.ColorSemantic,32,attribute.F32Type)
        self.geo.addAttribute(attribute.IndexSemantic,0,attribute.U32Type)
        self.geo.setIndexData(struct.pack('<'+str(len(row['indices']))+'I',*row['indices']))
        self.geo.setBounds(QVector3D(*row['bounds'][0]),QVector3D(*row['bounds'][1]))
        self.set_texture(cache,path,row.get('texture'));self.update(row,data)
    def set_texture(self,cache,path,source):
        texture=cache._texture(source,Path(path)) if source else None
        stat=texture.stat() if texture else None;key=(str(texture),stat.st_mtime_ns,stat.st_size) if texture else None
        if key==self.texture_key:return
        image=QImage(1,1,QImage.Format_RGBA8888);image.fill(0xffffffff)
        if source:
            if texture.suffix.lower()=='.blp' and self._authored_mip_sampling:
                from backend.game_engine_adapter_mips import atlas
                metadata,pixels=cache.decode(texture,mip_chain=True);image,levels=atlas(metadata,pixels)
                self.set_image(image,key,levels);return
            elif texture.suffix.lower() in ('.blp','.tga'):image=cache.image(texture)
            else:
                reader=QImageReader(str(texture));size=reader.size()
                if size.width()<1 or size.height()<1 or size.width()*size.height()>2*1024*1024:raise ValueError('Model texture dimensions exceeded')
                image=reader.read()
            if image.isNull():raise ValueError('Model texture unavailable')
        self.set_image(image,key)
    def set_image(self,image,key,levels=None):
        if key==self.texture_key:return
        if levels is None and image.text('GG_MIP_LEVELS'):levels=json.loads(image.text('GG_MIP_LEVELS'))
        image=image.convertToFormat(QImage.Format_RGBA8888);size=image.sizeInBytes()*2
        if image.isNull() or size>(32 if levels else 16)*1024*1024:raise ValueError('Invalid model image')
        if size>self.texture_bytes:self.owner.reserve(size-self.texture_bytes)
        elif size<self.texture_bytes:self.owner.release(self.texture_bytes-size)
        self.texture_bytes=size;self.tex.setSize(image.size());self.tex.setFormat(QQuick3DTextureData.Format.RGBA8);self.tex.setTextureData(bytes(image.constBits()));self.tex.setHasTransparency(True);self.texture_key=key
        self.row['mip_levels']=levels or [];self.changed.emit()
    @Property(QObject,constant=True)
    def geometry(self):return self.geo
    @Property(QObject,constant=True)
    def textureData(self):return self.tex
    @Property(QObject,constant=True)
    def mipTableData(self):return self.mip_lookup
    @Property(QObject,constant=True)
    def instancing(self):return self.instances
    @Property('QVariantMap',notify=changed)
    def state(self):return self.row
    def update(self,row,data):
        start=row['offset'];size=row['vertices']*self.stride
        if row['vertices']>self.capacity:raise ValueError('Runtime vertex capacity exceeded')
        if self.dynamic:
            indices=row['indices']
            if len(indices)>self.index_capacity or len(indices)%3 or any(i<0 or i>=row['vertices'] for i in indices):raise ValueError('Invalid particle index buffer')
            self.geo.setIndexData(struct.pack('<'+str(len(indices))+'I',*indices))
        if start<0 or size<1 or start+size>len(data):raise ValueError('Invalid runtime vertex buffer')
        vertices=data[start:start+size]
        if self.instances is None or bytes(self.geo.vertexData())!=vertices:self.geo.setVertexData(vertices)
        if self.instances is not None:
            offset=row['instance_offset'];count=row['instance_count'];end=offset+count*80
            if offset<0 or end>len(data):raise ValueError('Invalid instance buffer offset')
            update=self.instances.update_native if row.get('instances_finite') is True else self.instances.update
            update(data[offset:end],count)
        if 'bounds' in row:self.geo.setBounds(QVector3D(*row['bounds'][0]),QVector3D(*row['bounds'][1]))
        self.geo.update()
        state=dict(self.row);state.update({k:v for k,v in row.items() if k not in ('offset','vertices','indices','bounds')})
        if state!=self.row:self.row=state;self.changed.emit()

def rows_from(metadata):return metadata['rows']+metadata.get('effects',{}).get('rows',[])+metadata.get('ribbons',{}).get('rows',[])

class LiveModel(QObject):
    def __init__(self,cache,path,metadata,data):
        super().__init__();self.cache=cache;self.path=path;self.byte_size=0;self._batches=[];self.children={};self.attachment_limitations=[];self.attachments=metadata.get("attachments",{});self.options={};self.instance="";self.facts=metadata['facts'];self.camera=metadata['camera'];self.closed=False;self.base_limitations=tuple(metadata.get('limitations',()))+tuple(metadata.get('effects',{}).get('limitations',()))+tuple(metadata.get('ribbons',{}).get('limitations',()))
        self._model_events=deque(maxlen=4);self.audio_row=None;self._keep_model_events(metadata)
        self.mesh_count=len(metadata['rows']);self.character_key=None;self.character_metadata=None;self.character_image=None;self.character_bytes=0;self.effect_particles=metadata.get('effects',{}).get('live_particles',0);self.ribbon_edges=metadata.get('ribbons',{}).get('live_edges',0)
        try:
            for row in metadata['rows']+metadata.get('effects',{}).get('rows',[])+metadata.get('ribbons',{}).get('rows',[]):self._batches.append(Batch(cache,path,row,data,self))
        except Exception:self.close();raise
        if not self._batches:raise ValueError('Model has no visible batches')
        bounds_rows=metadata['rows'] or rows_from(metadata)
        self.bounds=([min(row['bounds'][0][i] for row in bounds_rows) for i in range(3)],[max(row['bounds'][1][i] for row in bounds_rows) for i in range(3)])
        raw=self.facts['bbox'];authored=([raw[0][0],raw[0][2],-raw[1][1]],[raw[1][0],raw[1][2],-raw[0][1]])
        if all(authored[0][i]<=authored[1][i] for i in range(3)) and any(authored[0][i]<authored[1][i] for i in range(3)):
            self.bounds=([min(self.bounds[0][i],authored[0][i]) for i in range(3)],[max(self.bounds[1][i],authored[1][i]) for i in range(3)])
    def update(self,metadata,data):
        rows=metadata['rows']+metadata.get('effects',{}).get('rows',[])+metadata.get('ribbons',{}).get('rows',[])
        self.effect_particles=metadata.get('effects',{}).get('live_particles',0);self.ribbon_edges=metadata.get('ribbons',{}).get('live_edges',0)
        if len(rows)!=len(self._batches):raise ValueError('Runtime model batch count changed')
        for batch,row in zip(self._batches,rows):
            batch.update(row,data)
            if 'bounds' in row:
                lo,hi=row['bounds'];batch.geo.setBounds(QVector3D(*lo),QVector3D(*hi))
        self.attachments=metadata.get('attachments',{});self.camera=metadata['camera'];self.base_limitations=tuple(metadata.get('limitations',()))+tuple(metadata.get('effects',{}).get('limitations',()))+tuple(metadata.get('ribbons',{}).get('limitations',()))
        self._keep_model_events(metadata)
    def _keep_model_events(self,metadata):
        events=metadata.get('events')
        if isinstance(events,dict) and isinstance(events.get('keys'),list) and len(events['keys'])<=64 and (events['keys'] or events.get('discarded_window') or events.get('dropped')):
            copy=deepcopy(events)
            if len(self._model_events)==self._model_events.maxlen:
                old=self._model_events.popleft();copy['dropped']=int(copy.get('dropped',0))+len(old['keys'])+int(old.get('dropped',0))
            self._model_events.append(copy)
    def take_model_events(self):
        events=list(self._model_events);self._model_events.clear();return events
    @property
    def batches(self):return self._batches+[batch for child in self.children.values() for batch in child.batches]
    def reserve(self,size):
        self.cache.reserve_live(size);self.byte_size+=size
    def release(self,size):self.cache.live_bytes-=size;self.byte_size-=size
    def appearance(self,row):
        appearance=row.get('appearance',row)
        if not isinstance(appearance,dict):raise ValueError('Model appearance must be an object')
        character=appearance.get('character')
        key=json.dumps(character,sort_keys=True,separators=(',',':')) if character is not None else None
        metadata,image=self.character_metadata,self.character_image
        if key!=self.character_key:metadata,image=self.cache.character(character) if character is not None else (None,None)
        if metadata:appearance={**appearance,'hair':metadata.get('hair'),'skin_extra':metadata.get('skin_extra'),'object':metadata.get('object') or appearance.get('object')}
        skins=appearance.get('skins',[None]*3)
        if not isinstance(skins,(list,tuple)) or len(skins)!=3:raise ValueError('Model appearance requires three skin slots')
        def source(value):
            if value is None or value=='':return None
            if not isinstance(value,str) or len(value.encode('utf-8'))>1024:raise ValueError('Model appearance texture path exceeded')
            return str(self.cache._texture(value,Path(self.path)))
        # Resolve every supplied path before touching a retained texture. Inactive
        # slots are checked too, so the accepted appearance never escapes the root.
        skins=[source(value) for value in skins]
        characters={name:source(appearance.get(key)) for name,key in (('Body','body'),('Object','object'),('Hair','hair'),('SkinExtra','skin_extra'))}
        size=image.sizeInBytes() if image is not None else 0
        cpu_growth=max(0,size-self.character_bytes) if key!=self.character_key else 0
        gpu_growth=sum(max(0,size*2-batch.texture_bytes) for batch in self._batches[:self.mesh_count] if image is not None and batch.row.get('char_slot')=='Body')
        # Reserve the new atlas before staging an outfit. Otherwise a valid set
        # of new parts could commit and then exhaust the budget on its body skin.
        self.reserve(cpu_growth+gpu_growth)
        try:self._attach(appearance,metadata)
        except Exception:self.release(cpu_growth+gpu_growth);raise
        self.release(gpu_growth) # set_image accounts for these bytes below.
        if key!=self.character_key:
            if size<self.character_bytes:self.release(self.character_bytes-size)
            self.character_metadata=metadata;self.character_image=image;self.character_key=key;self.character_bytes=size
        for batch in self._batches[:self.mesh_count]:
            geoset=batch.row.get('geoset') or 0
            visible=self.character_metadata is None or geoset>1700 or geoset in self.character_metadata['geosets']
            if batch.row.get('visible',True)!=visible:batch.row={**batch.row,'visible':visible};batch.changed.emit()
            if batch.row.get('char_slot')=='Body' and self.character_image is not None:
                batch.set_image(self.character_image,('character',self.character_key));continue
            original=batch.row.get('texture');skin=batch.row.get('skin_slot');character=batch.row.get('char_slot')
            if batch.row.get('icon_slot'):texture=row.get('icon') or original
            elif skin is not None:texture=skins[skin] or original
            elif character is not None:texture=characters[character] or original
            else:continue
            batch.set_texture(self.cache,self.path,texture)
    def _attach(self,appearance,metadata):
        import hashlib
        specs=appearance.get('attachments',metadata.get('attachments',[]) if metadata else [])
        if not isinstance(specs,list) or len(specs)>8:raise ValueError('Model requires at most eight attachments')
        planned=[];seen=set();limitations=[]
        for spec in specs:
            if not isinstance(spec,dict):raise ValueError('Invalid model attachment')
            slot=spec.get('id');model=spec.get('model');texture=spec.get('object');key=spec.get('key',slot)
            if isinstance(slot,bool) or not isinstance(slot,int) or not 0<=slot<=255:raise ValueError('Invalid attachment point')
            if not (type(key) is int and key==slot or isinstance(key,str) and key in ('main','off','ranged','helm','shL','shR','ammo','quiver')):raise ValueError('Invalid attachment slot key')
            if key in seen:raise ValueError('Invalid or duplicate attachment point')
            if not isinstance(model,str) or not model or len(model.encode())>1024:raise ValueError('Invalid attachment model')
            seen.add(key);anchor=self.attachments.get(str(slot))
            if anchor is None:limitations.append('M2 attachment point unavailable: '+str(slot));continue
            source=self.cache.attachment_path(model,self.path)
            if texture is not None:
                if not isinstance(texture,str) or len(texture.encode())>1024:raise ValueError('Invalid attachment texture')
                texture=str(self.cache._texture(texture,source))
            identity='attachment:'+hashlib.sha256(json.dumps([self.instance,key,str(source),texture],separators=(',',':')).encode()).hexdigest()
            planned.append((key,source,anchor,texture,identity))
        # Provisional new models are discarded on failure; the published outfit is retained.
        staged={};created=[]
        try:
            for slot,source,anchor,texture,identity in planned:
                child=self.children.get(slot)
                if child is None or child.path!=source or getattr(child,'attachment_texture',None)!=texture:
                    child=self.cache.create_attachment(source,identity,self.options,anchor);child.attachment_texture=texture;created.append(child)
                else:self.cache.pose_attachment(child,self.options,anchor)
                child.appearance({'appearance':{'object':texture}})
                staged[slot]=child
        except Exception:
            for child in created:self.cache.release_attachment(child)
            raise
        previous=self.children;self.children=staged;self.attachment_limitations=limitations
        for slot,child in previous.items():
            if staged.get(slot) is not child:self.cache.release_attachment(child)
    @property
    def limitations(self):
        missing=set()
        overlays=self.character_metadata.get('missing_candidates',[]) if self.character_metadata else []
        for batch in self.batches:
            if batch.texture_key is not None or batch.row.get('visible') is False:continue
            if batch.row.get('skin_slot') is not None:missing.add('Monster'+str(batch.row['skin_slot']+1))
            if batch.row.get('char_slot'):missing.add(batch.row['char_slot'])
        return list(self.base_limitations)+self.attachment_limitations+[text for child in self.children.values() for text in child.limitations]+(self.character_metadata.get('limitations',[]) if self.character_metadata else [])+(['Character overlay candidates unavailable: '+', '.join(overlays[:8])] if overlays else [])+(['Unbound M2 replaceable textures: '+', '.join(sorted(missing))] if missing else [])
    def close(self):
        if self.closed:return
        self.closed=True
        self._model_events.clear()
        for child in self.children.values():self.cache.release_attachment(child)
        self.children.clear()
        self.cache.live_bytes-=self.byte_size;self.byte_size=0;self.deleteLater()
