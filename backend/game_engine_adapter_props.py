"""Prepare placed M2 art and authored collision on the existing world loader lane.

The native adapter owns coordinate conversion and original-format parsing. A
page commits art and physics together; no Qt objects are made on this lane.
"""
import time,hashlib

def prepare_props(cache,path,metadata,blob):
    specs=metadata.get('props',[])
    if len(specs)>128:raise ValueError('World object placement capacity exceeded (128)')
    packet=bytearray(blob);sources=set();source_bytes=0;seen={};accepted=[]
    for spec in specs:
        if time.monotonic()>cache.deadline:raise TimeoutError('World object preparation exceeded its time budget')
        key=spec['prop_key'];identity=(spec['model'],spec['anchor'])
        if key in seen:
            if seen[key]!=identity:raise ValueError('Conflicting world object placement ID')
            continue
        seen[key]=identity
        source=cache.attachment_path(spec['model'],path)
        spec['source']=str(source)
        if source not in sources:
            sources.add(source);source_bytes+=source.stat().st_size
            if len(sources)>32 or source_bytes>64*1024*1024:raise ValueError('World object source capacity exceeded')
        spec['instance']='world:'+hashlib.sha256((str(path)+':'+key).encode()).hexdigest()[:24]
        if not hasattr(cache,'world_sources'):cache.world_sources=set();cache.world_instances=set()
        cache.world_sources.add(str(source));cache.world_instances.add(spec['instance'])
        child,data=cache.decode(source,world_scene=True,runtime=True,world_instance=True,instance=spec['instance'],anchor=spec['anchor'],timeout=2)
        for dependency in cache._effect_bindings.get((str(source),source.stat().st_mtime_ns,source.stat().st_size),{}).values():
            if dependency not in {str(p) for p in sources}:sources.add(type(source)(dependency));source_bytes+=type(source)(dependency).stat().st_size;cache.world_sources.add(dependency)
        if len(sources)>32 or source_bytes>64*1024*1024:raise ValueError('World object source capacity exceeded')
        metadata['native_collision_bytes']=metadata.get('native_collision_bytes',0)+child.get('native_collision_bytes',0)
        spec['runtime']=bool(child.get('facts',{}).get('dynamic'));spec['facts']=child.get('facts',{})
        offset=len(packet)
        if offset+len(data)>8*1024*1024:raise ValueError('World object page packet capacity exceeded')
        packet.extend(data)
        for category in ('rows','collision','sight_collision'):
            for i,item in enumerate(child[category]):
                row={**item,'offset':item['offset']+offset,'prop_key':key,'owning_groups':spec['owning_groups'],'prop_light':spec['light']}
                if 'instance_offset' in row:row['instance_offset']+=offset
                if category=='rows':row.update(runtime_index=i,effect_active=item.get('visible',True))
                row['texture']=str(cache._texture(row['texture'],source)) if row.get('texture') else None
                metadata[category].append(row)
        metadata.setdefault('limitations',[]).extend(child['limitations'])
        for row in child['rows']:
            if row.get('texture') is None and (row.get('skin_slot') is not None or row.get('char_slot')):
                metadata['limitations'].append('World M2 replaceable texture requires a display binding: '+spec['model'])
        accepted.append(spec)
        if len(metadata['rows'])>512 or sum(r['vertices'] for r in metadata['rows'])>65536:raise ValueError('World object draw capacity exceeded')
    metadata['props']=accepted
    metadata['prop_sources']=[str(p) for p in sorted(sources)]
    metadata['blob_bytes']=len(packet)
    metadata['limitations']=list(dict.fromkeys(metadata.get('limitations',[])))
    return bytes(packet)
