"""Original native asset readers and bounded conversion for Qt model panes."""
from __future__ import annotations
from backend.platform_support import native_directory, native_library_name
import base64,hashlib,json,os,struct,sys,tempfile,time
from pathlib import Path
from backend.game_engine_adapter_transport import BoundedWorker
from backend.game_engine_adapter_assets import PROJECT,asset_path
NATIVE=native_directory(PROJECT)
def available():
    try:
        binary=NATIVE/native_library_name('gg_engine_formats');receipt=json.loads((NATIVE/'engine-formats-build.json').read_text());digest=hashlib.sha256();root=PROJECT/'native/engine-formats'
        for path in sorted(root.rglob('*')):
            if path.is_file() and path.suffix in ('.rs','.h','.toml','.lock'):
                digest.update(path.relative_to(root).as_posix().encode());digest.update(path.read_bytes())
        return receipt['abi']==1 and digest.hexdigest()==receipt['source_sha256'] and hashlib.sha256(binary.read_bytes()).hexdigest()==receipt['binary_sha256']
    except (OSError,KeyError,ValueError):return False
class NativeFormats(BoundedWorker):
    def __init__(self,root=None):
        if not available():raise RuntimeError('Verified GgEngine asset readers unavailable')
        env=os.environ.copy();env['PYTHONDONTWRITEBYTECODE']='1';self.root=Path(root or PROJECT/'qml').resolve()
        self._start_worker([sys.executable,'-B',str(PROJECT/'backend/game_engine_adapter_asset_worker.py'),str(NATIVE/native_library_name('gg_engine_formats')),str(self.root)],env)
        self.request('ping',timeout=3)
    def decode(self,path,*,timeout=1,**kwargs):
        result=self.request('decode',path=str(path),timeout=timeout,**kwargs)
        return self._unpack(result)
    def pose(self,path,**kwargs):
        return self._unpack(self.request('pose',path=str(path),timeout=1,**kwargs))
    @staticmethod
    def _unpack(result):
        blob=base64.b64decode(result.pop('blob_base64',''),validate=True)
        if len(blob)!=result.get('blob_bytes',0):raise ValueError('Native asset blob size mismatch')
        return result,blob

def image_from_rgba(metadata,blob):
    from PySide6.QtGui import QImage
    w,h=int(metadata['width']),int(metadata['height'])
    if w<1 or h<1 or w*h*4!=len(blob) or len(blob)>8*1024*1024:raise ValueError('Invalid decoded texture')
    return QImage(blob,w,h,w*4,QImage.Format_RGBA8888).copy()

class AssetCache:
    def __init__(self):
        self.reader=None;self.directory=None;self.models={};self.live_models={};self.attachment_models={};self.creature_displays={};self.failures={};self.bytes=0;self.live_bytes=0;self.closed=False;self._adaptations=set();self.deadline=None;self.model_event_sink=None
        self.archive_source=None;self.archive_directory=None;self.archive_bytes=0;self.archive_entries={};self._mounted_reader=None;self._archive_discovered=False;self._effect_bindings={};self._effect_reader=None
        self.collision_restore=None;self._collision_reader=None
    @property
    def adaptations(self):
        return self._adaptations | {text for model in self.live_models.values() for text in model.limitations}
    def _reader(self):
        if self.closed:raise RuntimeError('Asset cache closed')
        if self.reader is None or self.reader.closed:self.reader=NativeFormats()
        if self.archive_source and self._mounted_reader is not self.reader:
            self.reader.request('mount_chain',path=str(self.archive_source),timeout=3);self._mounted_reader=self.reader
        if self.collision_restore and self._collision_reader is not self.reader:
            try:self.collision_restore(self.reader)
            except Exception:self.reader.close();raise
            self._collision_reader=self.reader
        return self.reader
    def mount_chain(self,directory):
        directory=asset_path(str(directory))
        if not directory.is_dir():raise ValueError('Archive chain directory unavailable')
        if self.archive_source and directory!=self.archive_source:raise ValueError('Close the asset cache before changing its archive target')
        self.archive_source=directory;self._archive_discovered=True;self._reader()
    def resolve(self,value):
        path=asset_path(value)
        if path.is_file():return path
        self.discover_chain()
        if not self.archive_source:return path
        root=Path(self.archive_directory.name) if self.archive_directory else PROJECT/'qml'
        raw=str(value).replace('\\','/')
        key=raw if raw.casefold().startswith('interface/addons/') else (path.relative_to(root) if path.is_relative_to(root) else path.relative_to(PROJECT/'qml')).as_posix()
        folded=key.casefold()
        if folded in self.archive_entries:return self.archive_entries[folded]
        if len(self.archive_entries)>=128:raise ValueError('Archive extraction entry capacity exceeded')
        meta,blob=NativeFormats._unpack(self._reader().request('chain_read',entry=key,timeout=1))
        if self.archive_bytes+len(blob)>64*1024*1024:raise ValueError('Archive extraction memory capacity exceeded')
        if self.archive_directory is None:self.archive_directory=tempfile.TemporaryDirectory(prefix='.gg-archive-',dir=PROJECT/'qml')
        output=Path(self.archive_directory.name)/key
        output.parent.mkdir(parents=True,exist_ok=True);output.write_bytes(blob)
        self.archive_bytes+=len(blob);self.archive_entries[folded]=output;return output
    def discover_chain(self):
        if not self._archive_discovered:
            self._archive_discovered=True;candidate=asset_path('game/Data')
            if candidate.is_dir() and any(p.suffix.casefold()=='.mpq' for p in candidate.iterdir()):self.mount_chain(candidate)
        return bool(self.archive_source)
    def archive_listing(self):
        return self._reader().request('chain_list',timeout=2) if self.discover_chain() else []
    def archive_read(self,value):
        # Source files stay in bounded memory, instead of consuming the model/texture disk cache.
        path=asset_path(value);raw=str(value).replace('\\','/')
        key=raw if not Path(raw).is_absolute() else path.relative_to(PROJECT/'qml').as_posix()
        if not self.discover_chain():raise ValueError('Archive chain not mounted')
        return NativeFormats._unpack(self._reader().request('chain_read',entry=key))[1]
    def texture_path(self,value):
        from backend.game_engine_adapter_assets import texture_path
        path=texture_path(value)
        if not path.suffix:
            for suffix in ('.blp','.tga','.png','.svg'):
                try:
                    candidate=self.resolve(str(path)+suffix)
                    if candidate.is_file():return candidate
                except ValueError as exc:
                    if 'not in patch chain' not in str(exc) and 'deleted from patch chain' not in str(exc):raise
        return self.resolve(path)
    def decode(self,path,**kwargs):
        if self.closed:raise RuntimeError('Asset cache closed')
        self._reader()
        if self.deadline is not None:
            remaining=self.deadline-time.monotonic()
            if remaining<=0:raise TimeoutError('Model conversion exceeded its time budget')
            kwargs['timeout']=min(kwargs.get('timeout',1),remaining)
        if kwargs.get('runtime'):
            if self._effect_reader is not self.reader:self._effect_bindings.clear();self._effect_reader=self.reader
            source=Path(path).resolve();stat=source.stat();key=(str(source),stat.st_mtime_ns,stat.st_size)
            if key not in self._effect_bindings:
                probe,_=self.reader.decode(source,runtime=True,timeout=kwargs.get('timeout',1))
                names=probe['facts'].get('particle_models',[])
                if len(names)>32:raise ValueError('Particle dependency capacity exceeded')
                bindings={name:str(self.attachment_path(name,source)) for name in names}
                if bindings:self.reader.request('bind_effect_models',path=str(source),bindings=bindings,timeout=kwargs.get('timeout',1))
                if len(self._effect_bindings)>=128:self._effect_bindings.pop(next(iter(self._effect_bindings)))
                self._effect_bindings[key]=bindings
        return self.reader.decode(path,**kwargs)
    def image(self,path):
        metadata,blob=self.decode(path)
        if metadata.get('blob_kind')!='rgba':raise ValueError('Native asset is not a texture')
        return image_from_rgba(metadata,blob)
    def character(self,appearance):
        if not isinstance(appearance,dict):raise ValueError('Character appearance must be an object')
        self.discover_chain()
        metadata,blob=NativeFormats._unpack(self._reader().request('character',character={**appearance,'mip_chain':True}))
        from backend.game_engine_adapter_mips import atlas
        image,_=atlas(metadata,blob);return metadata,image
    def creature_display(self,display_id):
        if isinstance(display_id,bool) or not isinstance(display_id,int) or not 0<display_id<=0xffffffff:raise ValueError('Invalid creature display id')
        if display_id not in self.creature_displays:
            self.discover_chain()
            result=self._reader().request('creature_display',display_id=display_id)
            if len(self.creature_displays)>=128:self.creature_displays.pop(next(iter(self.creature_displays)))
            self.creature_displays[display_id]=result
        # Callers may merge an override, never mutate the shared display defaults.
        return json.loads(json.dumps(self.creature_displays[display_id]))
    def live_model(self,path,row):
        path=Path(path).resolve();stat=path.stat();key=(str(path),row['id'],stat.st_mtime_ns,stat.st_size)
        failed=self.failures.get(key)
        if failed and time.monotonic()<failed[0]:raise ValueError(failed[1])
        try:
            result=self._live_model(path,row);self.failures.pop(key,None);return result
        except (ValueError,OSError,RuntimeError,TimeoutError) as exc:
            if len(self.failures)>=32:self.failures.pop(next(iter(self.failures)))
            self.failures[key]=(time.monotonic()+2,str(exc));raise
    def _live_model(self,path,row):
        from backend.game_engine_adapter_models import LiveModel
        if self.closed:raise RuntimeError('Asset cache closed')
        path=Path(path).resolve();stat=path.stat();key=(str(path),row['id'],stat.st_mtime_ns,stat.st_size)
        for old in list(self.live_models):
            if old[1]==row['id'] and old!=key:self.release_live_model(old)
        play=row.get('play') or {};options={'anim_id':play.get('anim_id'),'cursor_ms':row.get('raw_cursor_ms',play.get('cursor_ms',0)),'clock_ms':row.get('clock_ms',0),'camera':row.get('camera'),'instance':str(row['id']),'facing':row.get('facing',0),'model_scale':row.get('model_scale',1),'particle_density':row.get('particle_density',1)}
        if row.get('audio_world') is True:
            if not isinstance(row.get('world_anchor'),list) or len(row['world_anchor'])!=16:raise ValueError('World model audio requires the actual world anchor')
            options.update(world_instance=True,anchor=row['world_anchor'])
        from backend.game_engine_adapter_pane_anchor import anchor
        options['pane_anchor']=row.get('pane_anchor') or anchor(row)
        if key not in self.live_models:
            if len(self.live_models)>=8:raise ValueError('Live model capacity exceeded')
            try:
                metadata,blob=self.decode(path,runtime=True,**options)
                self.live_models[key]=LiveModel(self,path,metadata,blob)
            except Exception:
                # A decoded file can fail during Qt texture/buffer creation.
                # Release that provisional native slot too; eight broken assets
                # must not exhaust the reader and block a later valid model.
                if self.reader and not self.reader.closed:
                    try:
                        self.reader.request('release_instance',instance=str(row['id']))
                        if not self._uses_model(path):self.reader.request('unload',path=str(path))
                    except (OSError,ValueError,RuntimeError,TimeoutError):pass
                raise
        else:
            if self.reader is None or self.reader.closed:metadata,blob=self.decode(path,runtime=True,**options)
            else:
                try:metadata,blob=self.reader.pose(path,compact=True,**options)
                except ValueError as exc:
                    if 'not loaded' not in str(exc):raise
                    metadata,blob=self.decode(path,runtime=True,**options)
            self.live_models[key].update(metadata,blob)
        result=self.live_models[key];result.options=dict(options);result.instance=options['instance']
        result.audio_row={k:row[k] for k in ('id','audio_world','audio_actor_id','audio_world_space') if k in row}
        if self.model_event_sink:
            for events in result.take_model_events():self.model_event_sink(result.audio_row,events)
        return result
    def _uses_model(self,path):
        return any(model.path==path for model in (*self.live_models.values(),*self.attachment_models.values()))
    def attachment_path(self,value,parent):
        path=Path(str(value).replace('\\','/'))
        candidates=[path] if path.is_absolute() else [PROJECT/'qml'/path,Path(parent).parent/path]
        for candidate in candidates:
            for variant in ([candidate,candidate.with_suffix('.m2')] if candidate.suffix.lower()=='.mdx' else [candidate]):
                try:
                    result=self.resolve(variant)
                    if result.is_file():return result
                except ValueError as error:
                    if 'not in patch chain' not in str(error):raise
        raise ValueError('Attachment model missing: '+str(value)[:120])
    @staticmethod
    def _attachment_options(instance,options,anchor):
        # The original socket matrix already carries the parent world anchor.
        # This child owns the attachment namespace, even when its parent is a
        # world actor; native instances deliberately reject both flags at once.
        return {**options,'instance':instance,'attachment_instance':True,'world_instance':False,'anchor':anchor,'camera':None,'anim_id':0,'cursor_ms':options['clock_ms']}
    def create_attachment(self,path,instance,options,anchor):
        from backend.game_engine_adapter_models import LiveModel
        # Eight panes × eight committed parts, plus one complete staged outfit.
        if len(self.attachment_models)>=72:raise ValueError('Attachment instance capacity exceeded')
        try:
            metadata,blob=self.decode(path,runtime=True,**self._attachment_options(instance,options,anchor))
            model=LiveModel(self,path,metadata,blob);model.instance=instance
            # A replacement is staged under a different Python key until its outfit commits.
            self.attachment_models[id(model)]=model;return model
        except Exception:
            if self.reader and not self.reader.closed:
                try:
                    self.reader.request('release_instance',instance=instance)
                    if not self._uses_model(path):self.reader.request('unload',path=str(path))
                except (OSError,ValueError,RuntimeError,TimeoutError):pass
            raise
    def pose_attachment(self,model,options,anchor):
        native=self._attachment_options(model.instance,options,anchor)
        if self.reader is None or self.reader.closed:metadata,blob=self.decode(model.path,runtime=True,**native)
        else:
            try:metadata,blob=self.reader.pose(model.path,compact=True,**native)
            except ValueError as error:
                if 'not loaded' not in str(error):raise
                metadata,blob=self.decode(model.path,runtime=True,**native)
        model.update(metadata,blob)
    def release_attachment(self,model):
        self.attachment_models.pop(id(model),None);model.close()
        if self.reader and not self.reader.closed:
            try:
                if not any(m.instance==model.instance for m in self.attachment_models.values()):self.reader.request('release_instance',instance=model.instance)
                if not self._uses_model(model.path):self.reader.request('unload',path=str(model.path))
            except (OSError,ValueError,RuntimeError,TimeoutError):pass
    def reserve_live(self,size):
        if size<0 or self.bytes+self.live_bytes+size>64*1024*1024:raise ValueError('Live model memory capacity exceeded')
        self.live_bytes+=size
    def release_live_model(self,key):
        model=self.live_models.pop(key)
        if self.model_event_sink and model.audio_row:self.model_event_sink(model.audio_row,None)
        model.close()
        if self.reader and not self.reader.closed:
            try:self.reader.request('release_instance',instance=str(key[1]))
            except (OSError,ValueError,RuntimeError,TimeoutError):pass
        if self.reader and not self.reader.closed and not self._uses_model(Path(key[0])):
            try:self.reader.request('unload',path=key[0])
            except (OSError,ValueError,RuntimeError,TimeoutError):pass
    def retain_live_panes(self,ids):
        for key in list(self.live_models):
            if key[1] not in ids:self.release_live_model(key)
    def _texture(self,source,model):
        # Classic paths are often rooted at the data tree; authored files also
        # use a path relative to their model. Both stay in the approved tree.
        for value in (str(model.parent.relative_to(PROJECT/'qml')/source.replace('\\','/')),source):
            try:
                path=self.resolve(value)
                if path.is_file():return path
                if not path.suffix:
                    for suffix in ('.tga','.blp','.png'):
                        candidate=self.resolve(value+suffix)
                        if candidate.is_file():return candidate
            except ValueError as exc:
                if 'not in patch chain' not in str(exc) and 'deleted from patch chain' not in str(exc) and 'Escaping' not in str(exc):raise
        raise ValueError('Model texture missing: '+str(source))
    def model(self,path):
        if self.closed:raise RuntimeError('Asset cache closed')
        path=Path(path).resolve()
        stat=path.stat() if path.is_file() else None
        key=(str(path),stat.st_mtime_ns if stat else 0,stat.st_size if stat else 0)
        if key in self.models:return self.models[key]
        failed=self.failures.get(key)
        if failed and time.monotonic()<failed[0]:raise ValueError(failed[1])
        if len(self.models)>=32:raise ValueError('Model conversion cache capacity exceeded')
        self.deadline=time.monotonic()+3
        try:
            converted=self._model(path,key);self.failures.pop(key,None);return converted
        except (ValueError,OSError,RuntimeError,TimeoutError) as exc:
            if len(self.failures)>=32:self.failures.pop(next(iter(self.failures)))
            self.failures[key]=(time.monotonic()+2,str(exc));raise
        finally:self.deadline=None
    def _model(self,path,key):
        deadline=time.monotonic()+3
        data,_=self.decode(path,geometry=True)
        if data['format']=='WMO_ROOT':
            if data['groups']>32:raise ValueError('Model pane WMO group capacity exceeded')
            groups=[]
            for index in range(data['groups']):
                remaining=deadline-time.monotonic()
                if remaining<=0:raise TimeoutError('Model conversion exceeded its time budget')
                group=self.resolve(str(path.with_name(path.stem+'_'+str(index).zfill(3)+'.wmo')))
                geometry,_=self.decode(group,geometry=True,timeout=remaining);groups.append(geometry)
            geometries=[row['geometry'] for row in groups]
            materials=data['materials'];textures=[{'path':value,'wrap_u':True,'wrap_v':True} for value in data['textures']]
            for geometry,group in zip(geometries,groups):
                for primitive in geometry['primitives']:
                    index=primitive.get('material',-1)
                    if not 0<=index<len(materials):raise ValueError('WMO material index outside root')
                    primitive.update(materials[index])
                    # WMO EGxBlend uses different modulate indices than M2.
                    primitive['blend']={4:5,5:6}.get(primitive['blend'],primitive['blend'])
                    if group['flags']&0x48==0:
                        primitive['unlit']=False;self._adaptations.add('WMO interior baked lighting and portals are not yet connected')
                    if primitive['flags']&0x30:self._adaptations.add('WMO night emission and window lighting are not yet connected')
                if group['liquid']:self._adaptations.add('WMO liquid surfaces are parsed but not yet rendered in the model pane')
        else:geometries=[data.get('geometry')];textures=data.get('textures',[])
        if not all(geometry and geometry['positions'] and geometry['indices'] for geometry in geometries):raise ValueError('Model has no drawable geometry')
        for row in geometries:
            for primitive in row['primitives']:
                if primitive.get('blend',0) in (3,4,5,6):self._adaptations.add('Legacy additive/modulate material currently approximated in GLTF preview')
                if primitive.get('texture_stages',1)>1:self._adaptations.add('Legacy multiple texture stages currently use the first preview texture')
        if data.get('bone_count'):self._adaptations.add('M2 preview currently uses its static geometry; animated skinning is not yet connected')
        if data.get('camera_count'):self._adaptations.add('M2 authored cameras are parsed but not yet connected')
        if any(t.get('replaceable') for t in textures):self._adaptations.add('M2 replaceable textures need GG appearance data')
        payload=self._glb(geometries,textures,path)
        if len(self.models)>=32 or self.bytes+self.live_bytes+len(payload)>64*1024*1024:raise ValueError('Model conversion cache capacity exceeded')
        if self.directory is None:self.directory=tempfile.TemporaryDirectory(prefix='gg-engine-models-')
        output=Path(self.directory.name)/(str(len(self.models))+'.glb');output.write_bytes(payload)
        self.models[key]=output;self.bytes+=len(payload);return output
    def _glb(self,geometries,textures,model):
        gltf={'asset':{'version':'2.0','generator':'GG upstream reader bridge'},'buffers':[{'byteLength':0}],'bufferViews':[],'accessors':[],'meshes':[],'nodes':[],'scenes':[{'nodes':[]}],'scene':0,'materials':[],'images':[],'textures':[],'samplers':[],'extensionsUsed':['KHR_materials_unlit']};binary=bytearray();images={}
        def view(data):
            if self.bytes+self.live_bytes+len(binary)+len(data)+4>64*1024*1024:raise ValueError('Model conversion cache capacity exceeded')
            if self.deadline is not None and time.monotonic()>self.deadline:raise TimeoutError('Model conversion exceeded its time budget')
            binary.extend(b'\0'*((-len(binary))%4));offset=len(binary);binary.extend(data)
            gltf['bufferViews'].append({'buffer':0,'byteOffset':offset,'byteLength':len(data)});return len(gltf['bufferViews'])-1
        def accessor(rows,width,kind=5126):
            flat=[x for row in rows for x in row] if width>1 else rows
            blob=struct.pack('<'+('f' if kind==5126 else 'I')*len(flat),*flat)
            a={'bufferView':view(blob),'componentType':kind,'count':len(rows),'type':{1:'SCALAR',2:'VEC2',3:'VEC3'}[width]}
            if width==3:a['min']=[min(r[i] for r in rows) for i in range(3)];a['max']=[max(r[i] for r in rows) for i in range(3)]
            gltf['accessors'].append(a);return len(gltf['accessors'])-1
        def texture(index):
            if not isinstance(index,int) or not 0<=index<len(textures):return None
            source=textures[index]
            if source.get('replaceable') or not source.get('path'):return None
            if index not in images:
                from PySide6.QtGui import QImageReader
                from PySide6.QtCore import QBuffer,QByteArray,QIODevice
                path=self._texture(source['path'],model)
                if path.suffix.lower() in ('.blp','.tga'):image=self.image(path)
                else:
                    reader=QImageReader(str(path));size=reader.size()
                    if size.width()*size.height()>2*1024*1024:raise ValueError('Invalid model texture dimensions')
                    image=reader.read()
                if image.isNull() or image.width()*image.height()>2*1024*1024:raise ValueError('Invalid model texture')
                packet=QByteArray();buffer=QBuffer(packet);buffer.open(QIODevice.WriteOnly)
                if not image.save(buffer,'PNG'):raise ValueError('Texture encoding failed')
                buffer.close();gltf['images'].append({'bufferView':view(bytes(packet)),'mimeType':'image/png'})
                gltf['samplers'].append({'wrapS':10497 if source.get('wrap_u') else 33071,'wrapT':10497 if source.get('wrap_v') else 33071})
                gltf['textures'].append({'source':len(gltf['images'])-1,'sampler':len(gltf['samplers'])-1});images[index]=len(gltf['textures'])-1
            return {'index':images[index]}
        for row in geometries:
            positions=row['positions'];count=len(positions);attrs={'POSITION':accessor(positions,3)}
            if len(row['normals'])==count:attrs['NORMAL']=accessor(row['normals'],3)
            if len(row['uv'])==count:attrs['TEXCOORD_0']=accessor(row['uv'],2)
            primitives=[]
            for part in row['primitives'] or [{'start':0,'count':len(row['indices']),'two_sided':True}]:
                start,length=int(part['start']),int(part['count'])
                if start<0 or length<1 or length%3 or start+length>len(row['indices']):raise ValueError('Invalid model batch')
                material={'doubleSided':bool(part.get('two_sided',False)),'pbrMetallicRoughness':{'metallicFactor':0,'roughnessFactor':1}}
                tex=texture(part.get('texture'))
                if tex:material['pbrMetallicRoughness']['baseColorTexture']=tex
                if part.get('unlit'):material['extensions']={'KHR_materials_unlit':{}}
                if part.get('blend')==1:material.update(alphaMode='MASK',alphaCutoff=224/255)
                elif part.get('blend',0)>=2:material['alphaMode']='BLEND'
                gltf['materials'].append(material);primitives.append({'attributes':attrs,'indices':accessor(row['indices'][start:start+length],1,5125),'material':len(gltf['materials'])-1})
            gltf['meshes'].append({'primitives':primitives});gltf['nodes'].append({'mesh':len(gltf['meshes'])-1});gltf['scenes'][0]['nodes'].append(len(gltf['nodes'])-1)
        gltf['buffers'][0]['byteLength']=len(binary);binary.extend(b'\0'*((-len(binary))%4));document=json.dumps(gltf,separators=(',',':')).encode();document+=b' '*((-len(document))%4)
        return struct.pack('<III',0x46546c67,2,28+len(document)+len(binary))+struct.pack('<II',len(document),0x4e4f534a)+document+struct.pack('<II',len(binary),0x004e4942)+binary
    def close(self):
        if self.closed:return
        self.closed=True
        if self.reader:self.reader.close()
        for model in self.live_models.values():
            if self.model_event_sink and model.audio_row:self.model_event_sink(model.audio_row,None)
            model.close()
        self.live_models.clear()
        if self.directory:self.directory.cleanup()
        if self.archive_directory:self.archive_directory.cleanup()
        self.archive_directory=None;self.archive_entries.clear();self.archive_bytes=0
