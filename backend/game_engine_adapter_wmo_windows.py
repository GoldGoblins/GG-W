"""Bounded geometry windows over a complete original WMO ownership directory.

The directory retains all portal, area, fog and doodad ownership metadata.
Only selected groups are extracted and decoded. A replacement uses a separate
native collision key until the GUI has constructed its complete render page.
"""
import copy,hashlib,json,math,time
from pathlib import Path
from backend.game_engine_adapter_assets import PROJECT
from backend.game_engine_adapter_formats import NativeFormats

WINDOW=8
HYSTERESIS=8.

def selected(directory,position,previous=(),count=WINDOW):
    """Distance to transformed group bounds, with resident-group hysteresis."""
    previous=set(previous);rank=[]
    for group in directory['groups']:
        corners=group.get('corners')
        if not corners:raise ValueError('WMO window requires original group bounds')
        lo=[min(p[i] for p in corners) for i in range(3)]
        hi=[max(p[i] for p in corners) for i in range(3)]
        distance=math.sqrt(sum(max(lo[i]-position[i],0.,position[i]-hi[i])**2 for i in range(3)))
        score=max(0.,distance-HYSTERESIS) if group['id'] in previous else distance
        rank.append((score,0 if group['id'] in previous else 1,group['id']))
    return tuple(sorted(row[2] for row in sorted(rank)[:count]))

def needed(page,position):
    window=page.metadata.get('group_window')
    return bool(window and selected(page.metadata['wmo_directory'],position,window,len(window))!=tuple(window))

def _archive_entry(cache,spec):
    raw=str(spec['path']).replace('\\','/')
    if not Path(raw).is_absolute():return raw.removeprefix('qml/')
    path=Path(raw)
    if cache.archive_directory and path.is_relative_to(Path(cache.archive_directory.name)):
        return path.relative_to(cache.archive_directory.name).as_posix()
    return path.relative_to(PROJECT/'qml').as_posix()

def decode(cache,path,spec,options,position,previous=None):
    directory=previous.metadata['wmo_directory'] if previous is not None else spec.get('_wmo_directory')
    if directory is None:
        kwargs={k:v for k,v in options.items() if k not in ('world_scene','collision_key','timeout')}
        if cache.archive_source:kwargs['archive_entry']=_archive_entry(cache,spec)
        directory,blob=NativeFormats._unpack(cache._reader().request('wmo_directory',path=str(path),timeout=4,**kwargs))
        if blob or directory['rows'] or directory['collision']:raise ValueError('Invalid WMO directory geometry')
    previous_ids=previous.metadata.get('group_window',()) if previous is not None else ()
    count=len(previous_ids) or WINDOW
    # Metadata has a conservative retained Python-object charge. It is counted
    # again during replacement, because the old page remains available.
    memory=len(json.dumps(directory,separators=(',',':')).encode())*4
    while True:
        ids=selected(directory,position,previous_ids,count)
        for gi in ids:
            if time.monotonic()>cache.deadline:raise TimeoutError('World group window preparation exceeded its time budget')
            cache.resolve(Path(spec['path']).with_name(path.stem+f'_{gi:03}.wmo'))
        signature=hashlib.sha256((options['collision_key']+':'+','.join(map(str,ids))).encode()).hexdigest()[:16]
        provisional='wmo-window:'+signature
        cache.world_collision_keys.add(provisional)
        try:
            metadata,blob=cache.decode(path,**{**options,'collision_key':provisional,'groups_selected':list(ids),'skip_props':True})
        except ValueError as exc:
            if count<=1 or not any(s in str(exc) for s in ('world page capacity exceeded','WMO source capacity exceeded','native walking collision capacity exceeded')):raise
            count=max(1,count//2);continue
        # Selected native rows keep absolute group IDs. Physics, PVS, light and
        # audio use the complete original directory, never a compact list index.
        groups=list(directory['groups'])
        for group in metadata['groups']:groups[group['id']]=group
        metadata.update(groups=groups,wmo_directory=directory,directory_bytes=memory,
                        group_window=list(ids),collision_staging_key=provisional)
        metadata['props']=[copy.deepcopy(p) for p in directory.get('props',[]) if any(g in ids for g in p['owning_groups'])]
        metadata['limitations']=list(dict.fromkeys(directory.get('limitations',[])+metadata.get('limitations',[])))
        if count<WINDOW:metadata['limitations'].append(f'WMO geometry window reduced to {count} groups by the page capacity')
        return metadata,blob
