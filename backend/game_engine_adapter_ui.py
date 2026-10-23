"""Qt-facing owner of the full native GgEngine UI, isolated from the game process."""
from __future__ import annotations
from backend.platform_support import native_directory, native_library_name

from backend.platform_files import sync_directory
import hashlib,json,os,sys,tempfile,time
from pathlib import Path
from backend.game_engine_adapter_transport import BoundedWorker
from backend.game_engine_adapter_addon_sources import addon_sources,wire_source
from backend.game_engine_adapter_addon_state import load_enabled,save_enabled
from backend.game_engine_legacy import schema_matches
PROJECT=Path(__file__).resolve().parents[1]
NATIVE=native_directory(PROJECT)
MAX_MESSAGE=16*1024*1024

def available():
    try:
        binary=NATIVE/native_library_name('gg_engine_ui');manifest=json.loads((NATIVE/'engine-ui-build.json').read_text())
        d=hashlib.sha256();source=PROJECT/'native/engine-ui'
        for p in sorted(source.rglob('*')):
            if p.is_file() and p.suffix in ('.rs','.c','.h','.toml','.lock','.tsv'):
                d.update(p.relative_to(source).as_posix().encode());d.update(p.read_bytes())
        return manifest['abi']==1 and d.hexdigest()==manifest['source_sha256'] and hashlib.sha256(binary.read_bytes()).hexdigest()==manifest['binary_sha256']
    except (OSError,ValueError,KeyError):return False

class GgEngineUI(BoundedWorker):
    def __init__(self,*,clock=None):
        if not available():raise RuntimeError('Verified GgEngine UI build unavailable')
        env=os.environ.copy();env['PYTHONDONTWRITEBYTECODE']='1'
        self._start_worker([sys.executable,'-B',str(PROJECT/'backend/game_engine_adapter_worker.py'),str(NATIVE/native_library_name('gg_engine_ui'))],env)
        self.memory_bytes=0;self.rows=[];self.warnings=[];self.errors=[];self.closed=False
        self._size=(1280.,720.);self.loaded=[];self.core_files=[];self.saved_root=None;self.held_saves=set();self._saved_stage=None;self.saved_bindings={};self._macros_generation=None
        self.character_saved_root=None
        self.saving_enabled=True
        self._pending_addon_rows=None
        self._bindings_pending=False
        self._ui_cache_pending=None;self._ui_cache_changed_at=0.
        self.request('draw',timeout=3)
        if clock is not None:self.request('clock',seconds=float(clock))

    def request(self,op,*,timeout=.3,**kwargs):
        result=super().request(op,timeout=timeout,**kwargs)
        if isinstance(result,dict) and 'quads' in result:
            self.rows=result['quads'];self.memory_bytes=result['memory_bytes']
            self.errors=(self.errors+result.get('errors',[]))[-32:];self.warnings=(self.warnings+result.get('warnings',[]))[-32:]
        if op=='requests' and isinstance(result.get('ui_cache'),dict):
            # Keep the drained state before any macro/cache disk write can fail.
            self._ui_cache_pending=result['ui_cache'];self._ui_cache_changed_at=time.monotonic()
        if op=='requests' and self.saving_enabled and self.saved_root and isinstance(result.get('macros'),dict):
            packet=result['macros']
            if packet['generation']!=self._macros_generation:
                rows=packet['rows'];state={'schema':'gg.engine.macros.v1',
                    'account':[{k:r[k] for k in ('name','texture','body','local_only')} for r in rows if r['index']<=18],
                    'character':[{k:r[k] for k in ('name','texture','body','local_only')} for r in rows if r['index']>18]}
                self._save_scoped_json('macros.json',state)
                self._macros_generation=packet['generation']
        if op=='requests':
            if self.saving_enabled and self.saved_root and time.monotonic()-self._ui_cache_changed_at>=1.:
                self._save_ui_cache()
        return result
    def execute(self,source,name='GG'):
        if not isinstance(source,(str,bytes)):raise ValueError('Text Lua required')
        return self.request('exec',source=wire_source(source),name=name,timeout=1)
    def evaluate(self,source):return self.request('eval',source=source)
    def xml(self,source,path='',files=None):return self.request('xml',source=wire_source(source),path=path,files={k:wire_source(v) for k,v in (files or {}).items()},timeout=1)
    def resize(self,width,height):
        size=(float(width),float(height))
        if size!=self._size:self.request('size',width=size[0],height=size[1]);self._size=size
    def event(self,event,*args):return self.request('event',event=event,args=list(args))
    def publish(self,player,running,health,resource,**state):
        data={k:player.get(k,0) for k in ('x','y','z','yaw','time_s','speed')}
        data.update(cell=str(player.get('cell','')),biome=str(player.get('biome','')),running=bool(running),health=health,resource=resource,**state)
        return self.request('snapshot',**data)
    def tick(self,elapsed):return self.request('tick',elapsed=min(1.,max(0.,elapsed)))
    def frames(self):self.request('draw');return self.rows
    def pointer(self,action,x=0,y=0,button='LeftButton',**kwargs):return self.request('mouse',action=action,x=x,y=y,button=button,**kwargs)
    def click(self,name):
        row=next((r for r in self.frames() if r['kind']=='Frame' and r.get('owner')==name),None)
        if not row:raise ValueError('Unknown GgEngine frame')
        x=row['x']+row['width']/2;y=row['y']+row['height']/2
        self.pointer('move',x,y);self.pointer('press',x,y);self.pointer('release',x,y)
    def memory(self):return self.memory_bytes
    def census(self):return self.request('census',timeout=2)

    def _scope_root(self,kind):
        return self.character_saved_root if kind=='character' else self.saved_root

    def _saved_json(self,path,root):
        try:
            if not path.exists():return None
            if not path.resolve().is_relative_to(root) or path.stat().st_size>65536:raise ValueError('Invalid saved UI state')
            value=json.loads(path.read_text())
            if not isinstance(value,dict):raise ValueError('Invalid saved UI state object')
            return value
        except (OSError,ValueError,TypeError) as exc:
            self.held_saves.add(path);self.errors=(self.errors+[str(exc)])[-32:];return None

    def _load_scoped_json(self,name,defaults):
        state=dict(defaults);found=False
        for kind in ('account','character'):
            root=self._scope_root(kind)
            if root is None:continue
            path=root/name
            if path.exists():found=True
            value=self._saved_json(path,root)
            if value is not None and name=='macros.json' and not schema_matches(value.get('schema'),'gg.engine.macros.v1'):
                self.held_saves.add(path);self.errors=(self.errors+['Invalid saved macro schema'])[-32:];value=None
            if value is not None and kind in value:state[kind]=value[kind]
        return state if found else None

    def _save_scoped_json(self,name,state):
        if self.saved_root==self.character_saved_root:
            path=self.saved_root/name
            if path not in self.held_saves:self._write_saved(path,json.dumps(state,ensure_ascii=False))
            return
        for kind in ('account','character'):
            root=self._scope_root(kind);path=root/name
            previous=self._saved_json(path,root) or {}
            if path in self.held_saves:continue
            # Preserve flat legacy character data in the account file; scoped
            # local characters never load that field as their own profile.
            previous[kind]=state.get(kind)
            if 'schema' in state:previous['schema']=state['schema']
            self._write_saved(path,json.dumps(previous,ensure_ascii=False))

    def load_addons(self,root,saved_root=None,*,assets=None,archive_addons=(),core_root=None,character_saved_root=None):
        """Use the original parser and loader with bounded loose/archive source bytes."""
        root=Path(root).resolve();self.saved_root=Path(saved_root).resolve() if saved_root else None
        self.character_saved_root=Path(character_saved_root).resolve() if character_saved_root else self.saved_root
        addons,files,core=addon_sources(self,root,assets,archive_addons,core_root)
        self.addon_defaults={info['name']:bool(info.get('enabled',True)) for info,_ in addons.values()}
        self._pending_addon_rows=None
        addon_enable=load_enabled(self,addons)
        # The native loader restores settings after scripts and before ADDON_LOADED.
        # It sees only these bounded copies, including future LoadOnDemand files.
        if self._saved_stage:self._saved_stage.cleanup()
        self._saved_stage=tempfile.TemporaryDirectory(prefix='gg-addon-saved-')
        stage=Path(self._saved_stage.name)
        for kind in ('account','character'):(stage/kind).mkdir()
        staged_bytes=0
        for info,_ in addons.values():
            for kind,key in (('account','saved_variables'),('character','saved_variables_per_character')):
                if not self.saved_root or not info[key]:continue
                scope=self._scope_root(kind);path=scope/info['name']/(kind+'.lua')
                try:
                    if not path.exists():continue
                    if not path.resolve().is_relative_to(scope) or path.stat().st_size>1024*1024:raise ValueError('Invalid saved variables file')
                    data=path.read_bytes();staged_bytes+=len(data)
                    if staged_bytes>8*1024*1024:raise ValueError('Saved variables tree capacity exceeded')
                    (stage/kind/(info['name']+'.lua')).write_bytes(data)
                except (OSError,ValueError) as exc:
                    self.held_saves.add(path);self.errors=(self.errors+[info['name']+': '+str(exc)])[-32:]
        self.request('registry',addons=[i for i,_ in addons.values()],files={k:wire_source(v) for k,v in files.items()},saved_account=str(stage/'account'),saved_character=str(stage/'character'),addon_enable=addon_enable,timeout=3)
        # Macros are client state, loaded before addon events just like bindings.
        macros=self.saved_root/'macros.json' if self.saved_root else None
        macro_state=self._load_scoped_json('macros.json',{'schema':'gg.engine.macros.v1','account':[],'character':[]})
        if macro_state is not None:
            try:
                self.request('macros_load',state=macro_state)
            except (OSError,ValueError,TypeError) as exc:
                for kind in ('account','character'):self.held_saves.add(self._scope_root(kind)/'macros.json')
                self.errors=(self.errors+[str(exc)])[-32:]
        elif self.saved_root:
            sources={}
            for kind in ('account','character'):
                scope=self._scope_root(kind);path=scope/'macros'/kind/'macros-cache.txt'
                try:
                    if path.exists():
                        if not path.resolve().is_relative_to(scope) or path.stat().st_size>65536:raise ValueError('Invalid macro cache')
                        sources[kind]=path.read_text(encoding='utf-8-sig')
                except (OSError,ValueError) as exc:self.held_saves.add(path);self.errors=(self.errors+[str(exc)])[-32:]
            if sources:
                try:self.request('macros_import',account=sources.get('account',''),character=sources.get('character',''))
                except ValueError as exc:
                    for kind in sources:
                        self.held_saves.add(self._scope_root(kind)/'macros.json')
                        self.held_saves.add(self._scope_root(kind)/'macros'/kind/'macros-cache.txt')
                    self.errors=(self.errors+[str(exc)])[-32:]
        if assets and assets.discover_chain():
            try:self.request('macro_icons',icons=assets._reader().request('macro_icons',timeout=2))
            except (OSError,ValueError,RuntimeError,TimeoutError) as exc:self.warnings=(self.warnings+['Macro icons: '+str(exc)])[-32:]
        else:
            # GG's own chooser uses the shipped icons; these are visible assets.
            icons=PROJECT/'qml/assets/authored/items/icons'
            self.request('macro_icons',icons=[p.resolve().as_uri() for p in sorted(icons.glob('*.png'))[:4096] if p.resolve().is_relative_to(PROJECT/'qml')])
        if core:
            for path in core['files']:
                try:
                    body=next((v for k,v in files.items() if k.casefold()==path.casefold()),None)
                    if body is None:raise ValueError('Missing core source: '+path)
                    if path.casefold().endswith('.lua'):self.execute(body,path)
                    elif path.casefold().endswith('.xml'):
                        report=self.xml(body,path,files)
                        self.errors=(self.errors+report['errors'])[-32:];self.warnings=(self.warnings+report['warnings']+report['missing_files'])[-32:]
                    else:raise ValueError('Unsupported core entry: '+path)
                    self.core_files.append(path)
                except ValueError as exc:self.errors=(self.errors+[path+': '+str(exc)])[-32:]
            if core['bindings']:self.request('addon_bindings',name='FrameXML',source=wire_source(files[core['bindings']]))
        binding_state=self._load_scoped_json('bindings.json',{'account':None,'character':None})
        if binding_state is not None:
            try:
                self.saved_bindings=binding_state;self.request('bindings_load',**self.saved_bindings)
            except (OSError,ValueError,TypeError) as exc:
                for kind in ('account','character'):self.held_saves.add(self._scope_root(kind)/'bindings.json')
                self.errors=(self.errors+[str(exc)])[-32:]
        registered=self.saved_root/'registered.lua' if self.saved_root else None
        if registered and registered.exists():
            try:
                if not registered.resolve().is_relative_to(self.saved_root) or registered.stat().st_size>1024*1024:raise ValueError('Invalid registered variables file')
                self.execute(registered.read_text(),'Saved/registered')
            except (OSError,ValueError) as exc:self.held_saves.add(registered);self.errors=(self.errors+[str(exc)])[-32:]
        loading=set();loaded=set()
        def load(key):
            if key in loaded:return
            if key in loading:return
            if key not in addons:raise ValueError('Missing addon dependency: '+key)
            loading.add(key);info,sources=addons[key]
            verdict=self.request('addon_startup',name=info['name'])
            if not verdict['loadable']:
                loading.remove(key)
                raise ValueError('Addon '+info['name']+': '+str(verdict['reason']))
            def verify_dependencies(k,seen):
                if k in seen:return
                seen.add(k)
                for dep in addons[k][0]['dependencies']:
                    if dep.casefold() not in addons:raise ValueError('Missing addon dependency: '+dep)
                    verify_dependencies(dep.casefold(),seen)
            verify_dependencies(key,set())
            if not info['load_on_demand']:self.request('loaded',name=info['name'])
            for dep in info['dependencies']:load(dep.casefold())
            for dep in info['optional_dependencies']:
                if dep.casefold() in addons and addons[dep.casefold()][0].get('enabled',True):
                    try:load(dep.casefold())
                    except ValueError as exc:self.errors=(self.errors+[str(exc)])[-32:]
            if info['load_on_demand']:
                result=self.request('addon_load',name=info['name'],timeout=1)
                if not result or not result[0]:raise ValueError('Addon '+info['name']+': '+str(result[1:] if result else 'load failed'))
            else:
                for entry in info['files']:
                    rel=info['name']+'/'+entry
                    text=next((s for name,s in sources.items() if name.casefold()==rel.casefold()),None)
                    try:
                        if text is None:raise ValueError('Missing addon source: '+rel)
                        if entry.casefold().endswith('.xml'):
                            report=self.xml(text,rel,{**files,**{k[len('Interface/AddOns/'):]:v for k,v in files.items() if k.casefold().startswith('interface/addons/')}})
                            self.errors=(self.errors+report['errors'])[-32:];self.warnings=(self.warnings+report['warnings']+report['missing_files'])[-32:]
                        elif entry.casefold().endswith('.lua'):self.execute(text,'Interface/AddOns/'+rel)
                        else:raise ValueError('Unsupported addon entry: '+rel)
                    except ValueError as exc:self.errors=(self.errors+[info['name']+': '+str(exc)])[-32:]
                binding=next((s for name,s in sources.items() if name.casefold()==(info['name']+'/bindings.xml').casefold()),None)
                if binding:
                    try:self.request('addon_bindings',name=info['name'],source=wire_source(binding))
                    except ValueError as exc:self.errors=(self.errors+[str(exc)])[-32:]
                self.request('addon_finish',name=info['name'],timeout=1)
            loading.remove(key)
            loaded.add(key)
        for key,(info,_) in addons.items():
            if info.get('enabled',True) and not info['load_on_demand']:
                try:load(key)
                except ValueError as exc:self.errors=(self.errors+[str(exc)])[-32:]
        self.loaded=[{'id':i['name'],'title':i['title']} for i,_ in addons.values() if self.evaluate('return IsAddOnLoaded('+json.dumps(i['name'])+')')[0]]
        if self.character_saved_root:
            path=self.character_saved_root/'ui-cache.json';state=self._saved_json(path,self.character_saved_root)
            if state is not None:
                try:self.request('ui_cache_load',state=state)
                except (ValueError,RuntimeError) as exc:self.held_saves.add(path);self.errors=(self.errors+[str(exc)])[-32:]
        for event in ('VARIABLES_LOADED','PLAYER_LOGIN','PLAYER_ENTERING_WORLD'):self.event(event)
        self.tick(0)
        return self.loaded

    def save(self):
        if self.closed or not self.saving_enabled or not self.saved_root:return
        saved=self.request('saved')
        # Capture every drained request before the first disk operation. A
        # failed SavedVariables write must not drop a queued binding save.
        for change in saved.get('bindings',[]):
            self.saved_bindings['account' if change['set']==1 else 'character']=change['keys']
            if change['set']==1:self.saved_bindings['character']=None
            self._bindings_pending=True
        save_enabled(self,saved.get('addon_enable'))
        for name,values in saved['addons'].items():
            for index,kind in enumerate(('account','character')):
                source=values[kind]
                p=self._scope_root(kind)/name/(kind+'.lua')
                if p in self.held_saves or values.get('held',[False,False])[index]:continue
                self._write_saved(p,source)
        path=self.saved_root/'registered.lua'
        if path not in self.held_saves:self._write_saved(path,saved['registered'])
        self._save_scoped_json('macros.json',saved['macros'])
        self._ui_cache_pending=self.request('ui_cache');self._save_ui_cache()
        files=self.request('macro_files')
        for kind in ('account','character'):
            path=self._scope_root(kind)/'macros'/kind/'macros-cache.txt'
            if path not in self.held_saves:self._write_saved(path,files[kind])
        if self._bindings_pending:
            self._save_scoped_json('bindings.json',self.saved_bindings)
            self._bindings_pending=False
    def _save_ui_cache(self):
        if self._ui_cache_pending is None or not self.character_saved_root:return
        path=self.character_saved_root/'ui-cache.json'
        if path in self.held_saves:return
        source=json.dumps(self._ui_cache_pending,ensure_ascii=False)
        if len(source.encode())>65536:raise ValueError('UI cache capacity exceeded')
        self._write_saved(path,source);self._ui_cache_pending=None

    def _write_saved(self,path,source):
        if len(source.encode())>1024*1024:raise ValueError('Saved variables capacity exceeded')
        # Choose the intended scope before resolving: a character symlink
        # must never redirect its writes into even the shared account root.
        scope=self.character_saved_root if self.character_saved_root and path.is_relative_to(self.character_saved_root) else self.saved_root
        if not scope or not path.resolve().is_relative_to(scope):raise ValueError('Escaping saved variables path')
        path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,prefix='.gg-save-',delete=False) as f:
            temporary=Path(f.name);f.write(source);f.flush();os.fsync(f.fileno())
        try:
            os.replace(temporary,path)
            sync_directory(path.parent)
        finally:temporary.unlink(missing_ok=True)
    def close(self):
        if self.closed:return
        super().close()
        if self._saved_stage:self._saved_stage.cleanup();self._saved_stage=None
