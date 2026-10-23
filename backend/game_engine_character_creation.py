"""Local race/class/appearance selection for the first finished character."""
from __future__ import annotations

import copy
import json
import os
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
ASSETS=ROOT/'qml/assets/authored/characters/squirrel-fox'
STATE_PATH=(Path(os.environ.get('XDG_STATE_HOME') or Path.home()/'.local/state')
            /'goldgoblins/gg-ai-desktop/game/character-appearance.json')
SCHEMA='gg.character-creation.v1'


@lru_cache(maxsize=1)
def catalog() -> dict[str, Any]:
    try:
        data=json.loads((ASSETS/'catalog.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {'schema':SCHEMA,'races':[],'classes':[],'fur_colors':[],
                'eye_colors':[],'defaults':{},'error':'Karaktärsbanken saknas.'}
    if not isinstance(data,dict) or data.get('schema')!=SCHEMA:
        return {'schema':SCHEMA,'races':[],'classes':[],'fur_colors':[],
                'eye_colors':[],'defaults':{},'error':'Karaktärsbanken är ogiltig.'}
    return data


def normalize(value: Any) -> dict[str, str]:
    if not isinstance(value,dict):raise ValueError('Välj ras, klass, päls och ögon.')
    data=catalog();out={}
    for key,section in [('race_id','races'),('class_id','classes'),('fur_id','fur_colors'),('eye_id','eye_colors')]:
        wanted=str(value.get(key,''))
        row=next((r for r in data.get(section,[]) if r['id']==wanted),None)
        if not row or row.get('ready',True) is not True:
            raise ValueError('Det valet är inte färdigställt ännu.')
        out[key]=wanted
    race=next(r for r in data['races'] if r['id']==out['race_id'])
    if out['fur_id'] not in race['fur_options'] or out['eye_id'] not in race['eye_options']:
        raise ValueError('Färgen finns inte för den här rasen.')
    return out


def source(value: dict[str,str]) -> Path:
    return ASSETS/f"{value['class_id']}-{value['fur_id']}-{value['eye_id']}.gltf"


@lru_cache(maxsize=150)
def descriptor(class_id: str,fur_id: str,eye_id: str) -> dict[str,Any]:
    from backend import game_engine_assets
    value=normalize({'race_id':'squirrel_fox','class_id':class_id,'fur_id':fur_id,'eye_id':eye_id})
    path=source(value)
    admitted=game_engine_assets.inspect_asset(path,f'squirrel-fox-{class_id}-{fur_id}-{eye_id}')
    if admitted.get('status')!='READY':
        raise ValueError('Modellen kunde inte laddas: '+str(admitted.get('error','ogiltig asset')))
    doc=json.loads(path.read_text(encoding='utf-8'))
    return {'source':path.as_uri(),'clips':[a['name'] for a in doc.get('animations',[])],
            'triangles':sum(doc['accessors'][p['indices']]['count']//3 for m in doc['meshes'] for p in m['primitives']),
            'gear':[n['name'] for n in doc['nodes'] if n.get('extras',{}).get('gear_part')],
            'id':f'squirrel-fox-{class_id}-{fur_id}-{eye_id}'}


def preview(value: Any) -> dict[str,Any]:
    selection=normalize(value)
    data=descriptor(selection['class_id'],selection['fur_id'],selection['eye_id'])
    return dict(data,selection=selection)


def load_selection() -> dict[str,str] | None:
    try:
        data=json.loads(STATE_PATH.read_text(encoding='utf-8'))
        if not isinstance(data,dict) or data.get('schema')!=SCHEMA:return None
        selection=normalize(data.get('selection'))
        if source(selection).is_file():
            preview(selection)  # Admit and warm the descriptor before simulation ticks.
            return selection
    except (OSError,ValueError,TypeError):pass
    return None


def save_selection(value: Any) -> dict[str,str]:
    selection=normalize(value);preview(selection)
    STATE_PATH.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(prefix='.character-appearance-',dir=STATE_PATH.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            json.dump({'schema':SCHEMA,'selection':selection},f,ensure_ascii=False)
            f.flush();os.fsync(f.fileno())
        os.replace(temp,STATE_PATH)
    finally:
        if os.path.exists(temp):os.unlink(temp)
    return selection


def view(selection: Any=None) -> dict[str,Any]:
    return {'schema':SCHEMA,'catalog':copy.deepcopy(catalog()),
            'selection':copy.deepcopy(selection or catalog().get('defaults',{})),
            'active':bool(selection)}


def binding(selection: Any,previous: dict[str,Any],motion: Any,clip_override: str='') -> dict[str,Any]:
    if not selection:return previous
    data=descriptor(selection['class_id'],selection['fur_id'],selection['eye_id'])
    requested=clip_override or {'IDLE':'Idle','WALK':'Walk','SPRINT':'Sprint','RUN':'Sprint',
                               'AIR':'Air','JUMP':'Air','LAND':'Air'}.get(str(motion).upper(),'Idle')
    clip=requested if requested in data['clips'] else ''
    result=dict(previous)
    result.update(id=data['id'],source=data['source'],mode='AUTHORED_SKINNED',
                  editor_model=True,root_offset_m=-.65,clip=clip,runtime_clip=clip,
                  clip_status='READY' if clip else 'ROOT_POSE_ONLY',animation_mode='SKINNED',
                  race_id=selection['race_id'],class_id=selection['class_id'],
                  fur_id=selection['fur_id'],eye_id=selection['eye_id'],attachment_sockets={})
    # These are the actual imported bones. Existing equipped inventory items
    # can bind to the new race instead of looking for the crew rig's sockets.
    for slot,node in [('MAIN_HAND','Armature_Rhand'),('OFF_HAND','Armature_Lhand'),
                      ('HEAD','Armature_head_001'),('CHEST','Armature_chest_001'),
                      ('BACK','Armature_chest_001'),('FEET','Armature_hips_001')]:
        result['attachment_sockets'][slot]={'id':slot,'node':node,'rest':[0,0,0]}
    return result
