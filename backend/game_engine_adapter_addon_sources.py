"""Byte-preserving, bounded addon discovery for the original native loader."""
from pathlib import Path,PurePosixPath

def wire_source(value):
    if isinstance(value,bytes):
        try:return value.decode('utf-8')
        except UnicodeDecodeError:return {'hex':value.hex()}
    return value

def addon_sources(ui,root,assets=None,archive_addons=(),core_root=None):
    root=Path(root).resolve();addons={};files={};total=0;count=0;raw={};core=None
    def source(key,data):
        nonlocal total,count
        folded=key.casefold()
        if folded in raw:return raw[folded]
        if len(data)>1024*1024:raise ValueError('Addon file capacity exceeded')
        total+=len(data);count+=1
        if total>8*1024*1024 or count>2048:raise ValueError('Addon tree capacity exceeded')
        raw[folded]=data;return data
    def manifest(name,data):
        if not name or name in ('.','..') or '/' in name or '\\' in name:raise ValueError('Invalid addon name')
        if len(addons)>=128:raise ValueError('Addon count exceeded')
        if len(data)>65536:raise ValueError('Addon manifest capacity exceeded')
        parsed=ui.request('toc',source=wire_source(data));directives={k.casefold():v for k,v in parsed['directives']}
        version=parsed['interface']
        if version not in (0,1,11200):raise ValueError('Addon interface mismatch: '+name)
        return {'name':name,'title':directives.get('title',name),'interface':11200,
            'notes':directives.get('notes'),'url':directives.get('url'),'secure':directives.get('secure')=='1',
            'directives':parsed['directives'],**{k:parsed[k] for k in ('dependencies','optional_dependencies','saved_variables','saved_variables_per_character','load_on_demand','enabled')},
            'files':[p.replace('\\','/') for p in parsed['files']]}
    def archive_file(path,optional=False):
        key=path.casefold()
        if key in raw:return raw[key]
        try:return source(path,assets.archive_read(path))
        except ValueError as exc:
            if optional and ('not in patch chain' in str(exc) or 'deleted from patch chain' in str(exc)):return None
            raise
    mounted=bool(assets and assets.discover_chain())
    # The original core TOC is a boot program, not an addon. It must run before
    # addon scripts and their SavedVariables / ADDON_LOADED notifications.
    prefix='Interface/FrameXML/'
    toc=archive_file(prefix+'FrameXML.toc',optional=True) if mounted else None
    loose_core=Path(core_root).resolve() if core_root else None
    use_archive=toc is not None
    if not use_archive and loose_core and loose_core.is_dir():
        path=next((p for p in loose_core.iterdir() if p.name.casefold()=='framexml.toc'),None)
        if path:
            if not path.resolve().is_relative_to(loose_core):raise ValueError('Escaping core manifest')
            if path.stat().st_size>65536:raise ValueError('Core manifest capacity exceeded')
            toc=path.read_bytes()
    if toc is not None:
        info=manifest('FrameXML',toc);core={'files':[prefix+p for p in info['files']], 'bindings':None}
        queue=core['files']+[prefix+'Bindings.xml'];visited=set()
        while queue:
            current=queue.pop(0).replace('\\','/');folded=current.casefold()
            if folded in visited:continue
            visited.add(folded)
            if len(visited)>2048:raise ValueError('Core source count exceeded')
            if any(p=='..' for p in PurePosixPath(current).parts) or not folded.startswith('interface/'):raise ValueError('Escaping core source')
            if use_archive:body=archive_file(current,optional=True)
            else:
                if not folded.startswith(prefix.casefold()):raise ValueError('Escaping loose core source')
                relative=current[len(prefix):];path=loose_core
                # Match the original case-insensitive virtual paths on Linux too.
                for part in PurePosixPath(relative).parts:
                    path=next((p for p in path.iterdir() if p.name.casefold()==part.casefold()),None) if path.is_dir() else None
                    if path is None:break
                    if not path.resolve().is_relative_to(loose_core):raise ValueError('Escaping core source')
                if path is None or not path.is_file():body=None
                else:
                    if path.stat().st_size>1024*1024:raise ValueError('Core file capacity exceeded')
                    body=source(current,path.read_bytes())
            if body is None:continue
            files[current]=body
            if folded== (prefix+'Bindings.xml').casefold():core['bindings']=current
            elif folded.endswith('.xml'):queue.extend(ui.request('xml_refs',source=wire_source(body),path=current))
    if mounted:
        listing=assets.archive_listing();manifests=[]
        for entry in listing:
            path=entry['name'].replace('\\','/');parts=path.split('/')
            if len(parts)==4 and '/'.join(parts[:2]).casefold()=='interface/addons' and parts[3].casefold()==(parts[2]+'.toc').casefold():manifests.append((parts[2],path))
        for name in archive_addons:manifests.append((name,'Interface/AddOns/'+name+'/'+name+'.toc'))
        for name,path in manifests:
            if name.casefold() in addons:continue
            data=archive_file(path,optional=True)
            if data is None:continue
            info=manifest(name,data);sources={};prefix='Interface/AddOns/'+name+'/'
            queue=[prefix+p for p in info['files']]+[prefix+'Bindings.xml']
            queue.extend(e['name'].replace('\\','/') for e in listing if e['name'].replace('\\','/').casefold().startswith(prefix.casefold()) and Path(e['name']).suffix.casefold() in ('.xml','.lua'))
            visited=set()
            while queue:
                current=queue.pop(0).replace('\\','/')
                if current.casefold() in visited:continue
                if len(visited)>=2048:raise ValueError('Addon source count exceeded')
                visited.add(current.casefold())
                if any(p=='..' for p in PurePosixPath(current).parts) or not current.casefold().startswith('interface/'):raise ValueError('Escaping addon source')
                body=archive_file(current,optional=True)
                if body is None:continue
                files[current]=body
                if current.casefold().startswith(prefix.casefold()):sources[name+'/'+current[len(prefix):]]=body
                if current.casefold().endswith('.xml') and Path(current).name.casefold()!='bindings.xml':
                    queue.extend(ui.request('xml_refs',source=wire_source(body),path=current))
            addons[name.casefold()]=(info,sources)
    if root.is_dir():
        for folder in sorted(root.iterdir(),key=lambda p:p.name.casefold()):
            if not folder.is_dir() or folder.is_symlink() or folder.name.casefold() in addons:continue
            toc=next((p for p in folder.iterdir() if p.name.casefold()==(folder.name+'.toc').casefold()),None)
            if not toc:continue
            if not toc.resolve().is_relative_to(root):raise ValueError('Escaping addon manifest')
            if toc.stat().st_size>65536:raise ValueError('Addon manifest capacity exceeded')
            info=manifest(folder.name,toc.read_bytes());sources={}
            for path in sorted(folder.rglob('*')):
                if not path.is_file() or path.suffix.casefold() not in ('.lua','.xml'):continue
                if not path.resolve().is_relative_to(root):raise ValueError('Escaping addon source')
                if path.stat().st_size>1024*1024:raise ValueError('Addon file capacity exceeded')
                rel=path.relative_to(root).as_posix();data=source('Interface/AddOns/'+rel,path.read_bytes())
                sources[rel]=data;files['Interface/AddOns/'+rel]=data
            addons[folder.name.casefold()]=(info,sources)
    # XML's caller may use either loader-relative or install-rooted paths.
    return addons,files,core
