"""Transient continuity for the actual owned companion across a world handoff.

Call these helpers under the runtime lock. Neither the handoff nor its pending
placement belongs in the durable pet record. Real floor/hull queries decide
placement; this module never summons an animal or creates a combat actor.
"""
from dataclasses import dataclass
import math

_OFFSETS = ((1., 1.), (1., 0.), (0., 1.), (-1., 1.), (-1., 0.),
            (0., -1.), (1., -1.), (-1., -1.), (0., 0.))
_POSE = ('x', 'y', 'z', 'yaw', 'vx', 'vy', 'vz')


def scope(runtime):
    """Fence account, character, actual load/reset epoch and local map context."""
    state = getattr(runtime, '_services', {})
    active = state.get('instance_sessions', {}).get('active') or {}
    return (runtime, getattr(runtime, '_state_store', None),
            getattr(runtime, '_account_id', ''), getattr(runtime, '_persistence_key', ''),
            getattr(runtime, '_local_character_id', ''),
            getattr(runtime, '_spell_state', {}).get('epoch'), active.get('id'))


@dataclass
class _Transfer:
    scope: tuple
    number: int
    animal: str
    pose: dict
    phase: str = 'PENDING'
    unplaced: bool = True
    return_to_player: bool = False
    return_valid: bool = True
    resume_position: dict | None = None


def _canonical(runtime, transfer):
    if transfer.scope != scope(runtime):
        return None
    pet = runtime._active_pet_locked()
    if not pet or (pet.get('number'), pet.get('id')) != (transfer.number, transfer.animal):
        return None
    return pet


def _active(runtime, transfer):
    pet = _canonical(runtime, transfer)
    if pet is None:
        return None
    actor = getattr(runtime, '_combat_state', {}).get('actors', {}).get('pet:' + str(transfer.number))
    if not actor or not actor.get('alive') or actor.get('health', 0) <= 0 or pet.get('dead'):
        return None
    return pet


def _invalidate(runtime):
    runtime._companion_visual_stamp = None
    runtime._render_snapshot_cache = None
    runtime._ui_snapshot_base = None


def begin(runtime, stream):
    """After a successful player handoff, remember only this real pet's pose."""
    if getattr(runtime, '_engine_world', None) is not stream or stream.closed:
        return False
    previous = getattr(stream, '_pet_world_transfer', None)
    if previous is not None:
        return previous.phase != 'CANCELLED' and _active(runtime, previous) is not None
    pet = runtime._active_pet_locked()
    if not pet:
        return False
    transfer = _Transfer(scope(runtime), pet['number'], pet['id'],
                         {key: pet[key] for key in _POSE if key in pet})
    if _canonical(runtime, transfer) is None:
        return False
    stream._pet_world_transfer = transfer
    pet['target'] = ''
    if pet.get('command') == 2:
        pet['command'] = 1
    pet['vx'] = pet['vz'] = 0.
    actor_id = 'pet:' + str(pet['number'])
    actors = runtime._combat_state['actors']
    if actor_id in actors:
        actors[actor_id]['engaged_target'] = ''
    for actor in actors.values():
        if actor.get('engaged_target') == actor_id:
            actor['engaged_target'] = ''
    _invalidate(runtime)
    runtime._publish_companions_locked()
    return True


def pending(runtime, pet):
    """Read-only publication/movement guard, safe inside a rollback wrapper."""
    stream = getattr(runtime, '_engine_world', None)
    if pet is not None and getattr(runtime, '_mounted_world_resume', None):
        return True
    if (stream is not None and pet is not None
            and getattr(stream, 'return_scope', scope(runtime)) != scope(runtime)):
        # The provider is detached by update_world. Suppress the brief interval
        # between a real character load and that next update, without binding
        # this replacement companion to the previous character's capture.
        return True
    transfer = getattr(stream, '_pet_world_transfer', None)
    if transfer is None or not transfer.unplaced:
        return False
    # An unplaced corpse still belongs to the old map. Suppress its stale
    # coordinates too, including after settle has cancelled a dead transfer.
    current = _canonical(runtime, transfer)
    return current is not None and pet is current


def cancel(runtime, operation=None):
    """Call after a successful companion lifecycle operation, never before save."""
    stream = getattr(runtime, '_engine_world', None)
    transfer = getattr(stream, '_pet_world_transfer', None)
    if transfer is not None:
        transfer.phase = 'CANCELLED'
        transfer.return_valid = False
        _invalidate(runtime)
    if operation in ('StableTake', 'StableSwap', 'PetRevive', 'PetTame') and stream is not None:
        pet = runtime._active_pet_locked()
        if pet:
            fresh = _Transfer(scope(runtime), pet['number'], pet['id'], {}, return_to_player=True)
            if _active(runtime, fresh) is not None:
                # An explicit summon/revival is a new placement, not a replay
                # of the original pre-mount transform or old combat target.
                stream._pet_world_transfer = fresh
                pet['target'] = ''
                pet['vx'] = pet['vz'] = 0.
                actor_id = 'pet:' + str(pet['number'])
                actors = runtime._combat_state.get('actors', {})
                if actor_id in actors:
                    actors[actor_id]['engaged_target'] = ''
                for actor in actors.values():
                    if actor.get('engaged_target') == actor_id:
                        actor['engaged_target'] = ''
                _invalidate(runtime)
                runtime._publish_companions_locked()


def _floor(stream, x, y, z):
    query = stream.query(x, y, z)
    height = query.get('height')
    if (not query.get('loaded') or query.get('impassable')
            or type(height) not in (int, float) or not math.isfinite(height)):
        return None
    return height


def _placement(runtime, stream, preferred=None):
    if preferred:
        px,py,pz=(preferred[k] for k in ('x','y','z'))
        height=_floor(stream,px,py+.65,pz)
        if height is not None and abs(height-py)<=.75:
            corrected=(px,pz)
            for page in stream.pages.values():corrected=page.surface.walls(corrected[0],height,corrected[1])
            if math.hypot(corrected[0]-px,corrected[1]-pz)<.01:return px,height,pz
    x, y, z = runtime._x[0], runtime._y[0], runtime._z[0]
    floor = _floor(stream, x, y, z)
    if floor is None:
        return None
    surfaces = tuple(page.surface for page in stream.pages.values())
    for dx, dz in _OFFSETS:
        px, pz = x + dx, z + dz
        height = _floor(stream, px, y, pz)
        if height is None or abs(height - floor) > .75:
            continue
        for surface in surfaces:
            px, pz = surface.walls(px, height, pz)
        height = _floor(stream, px, y, pz)
        if height is None or abs(height - floor) > .75 or math.hypot(px - x, pz - z) > 2.:
            continue
        start, end = (x, floor + .35, z), (px, height + .35, pz)
        if any(not surface.line_of_sight(start, end) for surface in surfaces):
            continue
        # A clear segment is insufficient over an authored hole or a ledge.
        valid = True
        for fraction in (.25, .5, .75):
            sampled = _floor(stream, x + (px - x) * fraction, y, z + (pz - z) * fraction)
            if sampled is None or abs(sampled - floor) > .75:
                valid = False
                break
        if valid:
            return px, height, pz
    return None


def settle(runtime, stream):
    """Promote a pending pet only onto actual resident walking geometry."""
    transfer = getattr(stream, '_pet_world_transfer', None)
    if transfer is None or transfer.phase != 'PENDING':
        return False
    if getattr(runtime, '_engine_world', None) is not stream or stream.closed:
        transfer.phase = 'CANCELLED'
        return False
    pet = _canonical(runtime, transfer) if transfer.resume_position else _active(runtime, transfer)
    if pet is None:
        transfer.phase = 'CANCELLED'
        return False
    # Let the initial resident pages finish before a WMO can replace its
    # underlying terrain floor beneath the newly placed companion.
    if stream.pending is not None:
        return False
    point = _placement(runtime, stream, transfer.resume_position)
    if point is None:
        return False
    pet.update(x=point[0], y=point[1], z=point[2], vx=0., vz=0.)
    if transfer.resume_position:
        pet['yaw']=transfer.resume_position.get('yaw',pet.get('yaw',0.))
    transfer.phase = 'PLACED'
    transfer.unplaced = False
    _invalidate(runtime)
    runtime._publish_companions_locked()
    return True


def restore_saved(runtime, stream, saved, mounted_pose):
    """Rebind the same saved companion, preserving its real GG return capture."""
    pet=runtime._active_pet_locked()
    if not pet or not saved or (pet['number'],pet['id'])!=(saved['number'],saved['id']):return False
    transfer=getattr(stream,'_pet_world_transfer',None)
    if transfer is None:return False
    transfer.pose=dict(saved['pose'])
    if saved['placed'] and mounted_pose:transfer.resume_position=dict(mounted_pose)
    transfer.phase='PENDING';transfer.unplaced=True
    _invalidate(runtime)
    runtime._publish_companions_locked()
    return True


def leave(runtime, stream):
    """Restore the still-active pet/corpse's GG coordinates, never its health."""
    transfer = getattr(stream, '_pet_world_transfer', None)
    if transfer is None:
        return False
    del stream._pet_world_transfer
    if (not transfer.return_valid
            or getattr(runtime, '_engine_world', None) not in (None, stream)):
        return False
    # A corpse also has a real map/return pose. Restoring its coordinates must
    # preserve the actor's dead state and every progression/health field.
    pet = _canonical(runtime, transfer)
    if pet is None:
        return False
    if transfer.return_to_player:
        # load_world has already restored the actual GG player and detached
        # the imported provider. A newly retrieved companion has no previous
        # mounted-world return capture to reuse.
        if getattr(runtime, '_engine_world', None) is not None:
            return False
        x, z = runtime._x[0] + 1., runtime._z[0] + 1.
        height = runtime._terrain_height_locked(x, z)
        if type(height) not in (int, float) or not math.isfinite(height):
            return False
        pet.update(x=x, y=height, z=z, vx=0., vz=0.)
    else:
        pet.update(transfer.pose)
    pet['target'] = ''
    _invalidate(runtime)
    runtime._publish_companions_locked()
    return True
