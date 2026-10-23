"""Durable mounted-map identity, return poses and bounded automatic resumption.

The descriptor belongs to the same character save. Loading it never starts an
archive worker on the simulation thread; the existing Qt world update owns that
one attempt. A missing/changed map leaves the character on its actual GG return
position and retains a retryable descriptor instead of interpreting map axes as
GG coordinates. No sockets, external paths or new companion instances are used.
"""
from __future__ import annotations
import copy
import hashlib
import math
from pathlib import Path
from backend.game_engine_adapter_assets import PROJECT, asset_path
from backend.game_engine_legacy import schema_matches, manifest_path

SCHEMA = 'gg.engine-world-save.v1'
POSE = ('x', 'y', 'z', 'yaw', 'vx', 'vy', 'vz')


def _pose(value):
    if not isinstance(value, dict) or not {'x','y','z'} <= set(value) or set(value) - set(POSE):
        raise ValueError('WORLD_SAVE_POSE_INVALID')
    result = {}
    for key in POSE:
        number = value.get(key, 0.)
        limit = 2_000_000 if key in ('x', 'y', 'z', 'yaw') else 1000
        if type(number) not in (int, float) or not math.isfinite(number) or abs(number) > limit:
            raise ValueError('WORLD_SAVE_POSE_INVALID')
        result[key] = float(number)
    return result


def read(payload):
    content = payload.get('content_state')
    value = content.get('mounted_world') if isinstance(content, dict) else None
    if value is None:
        return None
    if not isinstance(value, dict) or not schema_matches(value.get('schema'), SCHEMA):
        raise ValueError('WORLD_SAVE_DESCRIPTOR_INVALID')
    if set(value) - {'schema', 'manifest', 'manifest_digest', 'map', 'return_pose', 'mounted_pose', 'pet_return'}:
        raise ValueError('WORLD_SAVE_DESCRIPTOR_INVALID')
    manifest = value.get('manifest')
    if not isinstance(manifest, str) or not 0 < len(manifest) <= 512 or '\x00' in manifest:
        raise ValueError('WORLD_SAVE_MANIFEST_INVALID')
    path = asset_path(manifest_path(manifest))
    if path.suffix.casefold() != '.json':
        raise ValueError('WORLD_SAVE_MANIFEST_INVALID')
    digest = value.get('manifest_digest')
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
        raise ValueError('WORLD_SAVE_MANIFEST_INVALID')
    name = value.get('map')
    if not isinstance(name, str) or not 0 < len(name) <= 64 or any(not(c.isascii() and (c.isalnum() or c == '_')) for c in name):
        raise ValueError('WORLD_SAVE_MAP_INVALID')
    result = dict(schema=SCHEMA, manifest=path.relative_to(PROJECT/'qml').as_posix(),
                  manifest_digest=digest, map=name, return_pose=_pose(value.get('return_pose')),
                  mounted_pose=_pose(value.get('mounted_pose')))
    pet = value.get('pet_return')
    if pet is not None:
        if (not isinstance(pet, dict) or set(pet) != {'number', 'id', 'pose', 'mounted_pose', 'placed'}
                or type(pet.get('number')) is not int or not 0 < pet['number'] <= 2**31-1
                or not isinstance(pet.get('id'), str) or not 0 < len(pet['id']) <= 256
                or type(pet.get('placed')) is not bool):
            raise ValueError('WORLD_SAVE_PET_INVALID')
        result['pet_return'] = dict(number=pet['number'], id=pet['id'],
                                   pose=_pose(pet['pose']), mounted_pose=_pose(pet['mounted_pose']), placed=pet['placed'])
    return result


def capture(runtime):
    from backend.game_engine_adapter_pet_world import scope
    stream = getattr(runtime, '_engine_world', None)
    if stream is None:
        pending = getattr(runtime, '_mounted_world_resume', None)
        deferred = getattr(runtime, '_mounted_world_deferred', None)
        return copy.deepcopy((pending or {}).get('descriptor') or deferred)
    if (stream.closed or not getattr(stream, 'manifest_path', None)
            or getattr(stream, 'return_scope', None) != scope(runtime)):
        return None
    pose = getattr(stream, 'return_pose', None)
    if pose is None:
        pose = dict(zip(('x', 'y', 'z'), stream.return_position))
    result = dict(schema=SCHEMA, manifest=stream.manifest_path,
                  manifest_digest=stream.manifest_digest, map=stream.config['map'],
                  return_pose=_pose(pose), mounted_pose=_pose({k:getattr(runtime,'_'+k)[0] for k in POSE}))
    transfer = getattr(stream, '_pet_world_transfer', None)
    pet = runtime._active_pet_locked()
    if transfer and transfer.return_valid and pet and (pet['number'], pet['id']) == (transfer.number, transfer.animal):
        return_pose = transfer.pose
        if transfer.return_to_player:
            x, z = result['return_pose']['x']+1., result['return_pose']['z']+1.
            # Imported provider must not determine the saved GG return floor.
            old = runtime._engine_world
            try:
                runtime._engine_world = None
                height = runtime._terrain_height_locked(x, z)
            finally:
                runtime._engine_world = old
            return_pose = dict(x=x, y=height, z=z)
        result['pet_return'] = dict(number=pet['number'], id=pet['id'],
                                    pose=_pose(return_pose), mounted_pose=_pose({k:pet.get(k,0.) for k in POSE}),
                                    placed=not transfer.unplaced)
    return result


def view(runtime):
    stream=getattr(runtime,'_engine_world',None)
    if stream is not None:
        loading=getattr(stream,'initial_collision_pending',False) or getattr(stream,'pending',None) is not None or getattr(stream,'pages',None)=={}
        return dict(status='LOADING' if loading else 'ACTIVE',map=(getattr(stream,'config',None) or {}).get('map',''),message='Laddar karta…' if loading else '')
    pending=getattr(runtime,'_mounted_world_resume',None)
    if pending:return dict(status='LOADING',map=pending['descriptor']['map'],message='Återupptar sparad karta…')
    deferred=getattr(runtime,'_mounted_world_deferred',None)
    if deferred:return dict(status='UNAVAILABLE',map=deferred['map'],message='Den sparade kartan kunde inte återupptas. Välj kartan igen för att fortsätta där.')
    return dict(status='GG',map='',message='')


def detach_for_load(runtime):
    stream=getattr(runtime,'_engine_world',None)
    if stream is not None:
        from backend.game_engine_adapter_spell_bindings import leave
        leave(runtime,stream)
    # The Qt owner's next update closes its obsolete QObject. Do not restore
    # previous-character positions and do not destroy render objects off-thread.
    runtime._engine_world = None
    runtime._mounted_world_resume = None
    runtime._mounted_world_deferred = None
    runtime._mounted_world_resume_error = ''


def arm(runtime, descriptor, player):
    from backend.game_engine_adapter_pet_world import scope
    if descriptor is None:
        return
    mounted_pose = descriptor['mounted_pose']
    return_pose = descriptor['return_pose']
    for key in POSE:
        getattr(runtime, '_'+key)[0] = return_pose[key]
    pet = runtime._active_pet_locked()
    pet_return = descriptor.get('pet_return')
    mounted_pet = copy.deepcopy(pet_return['mounted_pose']) if pet and pet_return else None
    if pet and pet_return and (pet['number'], pet['id']) == (pet_return['number'], pet_return['id']):
        pet.update(pet_return['pose'], target='', command=1)
    runtime._mounted_world_resume = dict(scope=scope(runtime), descriptor=copy.deepcopy(descriptor),
                                        player=mounted_pose, pet=mounted_pet)
    runtime._companion_visual_stamp = None
    runtime._render_snapshot_cache = None
    runtime._ui_snapshot_base = None
    runtime._publish_companions_locked()


def verified_manifest(descriptor):
    path = asset_path(descriptor['manifest'])
    if not path.is_file() or path.stat().st_size > 65536:
        raise ValueError('Saved world manifest is unavailable')
    if hashlib.sha256(path.read_bytes()).hexdigest() != descriptor['manifest_digest']:
        raise ValueError('Saved world manifest has changed; select it explicitly before continuing')
    return path


def clear(runtime):
    runtime._mounted_world_resume = None
    runtime._mounted_world_deferred = None
    runtime._mounted_world_resume_error = ''


def resume_for(host, runtime):
    from backend.game_engine_adapter_pet_world import scope
    pending = getattr(runtime, '_mounted_world_resume', None)
    if not pending:
        return False
    if pending['scope'] != scope(runtime):
        clear(runtime)
        return False
    from backend.game_engine_adapter_streaming import load_world
    try:
        verified_manifest(pending['descriptor'])
        result = load_world(host, pending['descriptor']['manifest'], resume=pending)
        if not result.get('ok'):
            raise ValueError(result.get('error', 'Saved world could not be resumed'))
    except (ValueError, OSError, RuntimeError, TimeoutError) as exc:
        runtime._mounted_world_resume = None
        runtime._mounted_world_deferred = copy.deepcopy(pending['descriptor'])
        runtime._mounted_world_resume_error = str(exc)[:240]
        runtime._publish_companions_locked()
        return False
    clear(runtime)
    return True
