"""Retained original world actors, sharing the world's bounded reader lane.

Only an explicit canonical original display ID opts in. The original catalog
resolves the model/appearance; unavailable files remain explicit failures.
Native poses transform both Qt geometry and event keys through one world
anchor. The existing EntityAudio and zone mixer own all voices.
"""
from __future__ import annotations
import json
import math
import time
from pathlib import Path
from copy import deepcopy
from PySide6.QtCore import QObject, Property, Signal
from PySide6.QtGui import QQuaternion, QVector3D
from backend.game_engine_adapter_formats import NativeFormats
from backend.game_engine_adapter_entity_audio import ident, point

MAX_ACTORS = 4
# Original anim_data.rs and models/mat_anim.rs identify these stock IDs.
# Other actions require a real explicit animation ID, never a guessed clip.
LOCOMOTION = {'IDLE': 0, 'STAND': 0, 'WALK': 4, 'WALKING': 4,
              'RUN': 5, 'RUNNING': 5, 'DEAD': 1, 'DEATH': 1, 'CORPSE': 1}


def scalar(value, default=0., low=-2_000_000., high=2_000_000.):
    value = default if value is None else value
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError('Original world actor transform invalid')
    return float(value)


def world_anchor(row, scale=1.):
    """Qt world-meter transform expressed in the original M2 coordinate basis.

    Native output uses Qt=(X,Z,-Y), so each column is converted through that
    same basis. Qt entity yaw is radians; pitch/roll are degrees.
    """
    at = point(row)
    if at is None:
        raise ValueError('Original world actor position invalid')
    asset = row.get('asset') or {}
    rotation = QQuaternion.fromEulerAngles(scalar(row.get('pitch'), low=-360., high=360.),
                                         math.degrees(scalar(row.get('yaw'), low=-10000., high=10000.)),
                                         scalar(row.get('roll'), low=-360., high=360.))
    sx, sy, sz = (scalar(row.get(k), 1., .001, 64.) * scalar(scale, 1., .001, 64.) for k in ('sx', 'sy', 'sz'))
    columns = []
    for vector in (QVector3D(sx, 0, 0), QVector3D(0, 0, -sz), QVector3D(0, sy, 0)):
        p = rotation.rotatedVector(vector)
        columns.extend((p.x(), -p.z(), p.y(), 0.))
    columns.extend((at[0], -at[2], at[1] + scalar(asset.get('root_offset_m'), 0., -64., 64.), 1.))
    return columns


class WorldActors(QObject):
    changed = Signal()

    def __init__(self, parent=None, *, clock=time.monotonic):
        super().__init__(parent)
        self.clock = clock
        self.cache = self.pool = self.audio = None
        self.scope = None
        self.records = {}
        self.future = None
        self.refs = []
        self.generation = 0
        self.serial = 0
        self.next_ms = 0
        self._requested = []
        self.failures = {}
        self.errors = []
        self.frames = 0
        self.running = False
        self.time_ms = None

    @Property('QVariantList', notify=changed)
    def batches(self):
        return [batch for record in self.records.values() for batch in record['model'].batches]

    @Property('QVariantList', notify=changed)
    def actorIds(self):
        return list(self.records)

    @Property('QVariantList', notify=changed)
    def requestedIds(self):
        # A missing original model must not silently display an invented GLB.
        return list(self._requested)

    @Property(str, notify=changed)
    def diagnostics(self):
        return json.dumps(dict(actors=len(self.records), capacity=MAX_ACTORS, pending=self.future is not None,
                               frames=self.frames, requested=self._requested, errors=self.errors,
                               limitations=['Stock Stand/Walk/Run/Death or explicit original animation IDs',
                                            'Original model/DBC corpus must exist in the mounted world archive',
                                            'Original full unit animation/action fallback graph remains partial']), ensure_ascii=False)

    def _error(self, identity, error):
        message = identity + ': ' + str(error)[:240]
        if message not in self.errors:
            self.errors = (self.errors + [message])[-16:]
            self.changed.emit()

    def bound_snapshot(self, snapshot, stream):
        """A mounted manifest can bind existing canonical actors to originals.

        Bindings change presentation only. They never create an actor, change
        gameplay identity, or mutate the canonical runtime/editor snapshot.
        """
        if not getattr(stream, 'active', False) or getattr(getattr(stream, 'cache', None), 'archive_source', None) is None:
            return snapshot
        bindings = (getattr(stream, 'config', None) or {}).get('actor_bindings', [])
        if not bindings:
            return snapshot
        try:
            if not isinstance(bindings, list) or len(bindings) > MAX_ACTORS:
                raise ValueError('Original actor bindings require at most four records')
            checked = {}
            for binding in bindings:
                if not isinstance(binding, dict) or set(binding) - {'actor_id', 'display_id', 'animation_ids', 'appearance'}:
                    raise ValueError('Original actor binding fields invalid')
                key = binding.get('actor_id')
                if not isinstance(key, str) or not 1 <= len(key) <= 80 or key in checked or ident(binding.get('display_id')) is None:
                    raise ValueError('Original actor binding identity/display invalid or duplicate')
                clips = binding.get('animation_ids', {})
                if not isinstance(clips, dict) or len(clips) > 16 or any(not isinstance(k, str) or not 1 <= len(k) <= 64 or k != k.upper() or type(v) is not int or not 0 <= v <= 0xffffffff for k, v in clips.items()):
                    raise ValueError('Original actor binding animation IDs invalid')
                appearance = binding.get('appearance', {})
                if not isinstance(appearance, dict) or set(appearance) - {'character', 'skins', 'body', 'object', 'hair', 'skin_extra', 'attachments'} or len(json.dumps(appearance, allow_nan=False)) > 16384:
                    raise ValueError('Original actor binding appearance invalid or too large')
                checked[key] = (binding['display_id'], clips, appearance)
            rows = snapshot.get('render', {}).get('entities', [])
            if not isinstance(rows, list):
                return snapshot
            result = []
            for row in rows[:128]:
                if not isinstance(row, dict):
                    result.append(row)
                    continue
                person = row.get('individual') if isinstance(row.get('individual'), dict) else {}
                keys = ['player'] if row.get('kind') == 'PLAYER' else [str(person.get('id') or row.get('actor_id') or row.get('npc_id') or row.get('id') or '')]
                keys.append(str(row.get('id') or ''))
                bound = next((checked[k] for k in keys if k in checked), None)
                if bound is None:
                    result.append(row)
                    continue
                display, clips, appearance = bound
                row = dict(row)
                asset = dict(row.get('asset') or {})
                current = dict(asset.get('appearance') or {})
                animation = row.get('animation') if isinstance(row.get('animation'), dict) else {}
                state = str(animation.get('locomotion') or row.get('motion_state') or animation.get('state') or 'IDLE').upper()
                current.update(deepcopy(appearance))
                current['display_id'] = display
                if state in clips:
                    current['animation_id'] = clips[state]
                asset['appearance'] = current
                row['asset'] = asset
                result.append(row)
            # All other runtime rows survive unchanged; only this consumer's
            # bounded first 128 actor rows receive original bindings.
            result.extend(rows[128:])
            return {**snapshot, 'render': {**snapshot.get('render', {}), 'entities': result}}
        except (TypeError, ValueError, OverflowError) as exc:
            self._error('bindings', exc)
            return snapshot

    def _audio(self, record, events):
        if self.audio is not None:
            # A new character/map epoch may reuse the canonical player key.
            # Retiring an old model must not retire that new actor's voices.
            if self.audio._actor(record['audio_row']['audio_actor_id']) is not record['actor']:
                return False
            return self.audio.model_events(record['audio_row'], events)
        return False

    def _retire(self, identity):
        record = self.records.pop(identity)
        self._audio(record, None)
        if self.cache and not self.cache.closed:
            for key in list(self.cache.live_models):
                if key[1] == record['owner']:
                    self.cache.release_live_model(key)

    def close(self):
        visible_changed = bool(self.records or self._requested or self.future is not None)
        self.generation += 1
        if self.future is not None:
            self.future.cancel()
        self.future = None
        self.refs = []
        for identity in list(self.records):
            self._retire(identity)
        self.cache = self.pool = self.audio = None
        self.scope = None
        self._requested = []
        self.failures.clear()
        self.running = False
        self.time_ms = None
        if visible_changed:
            self.changed.emit()

    @staticmethod
    def _animation(row):
        asset = row['asset']
        appearance = asset.get('appearance') if isinstance(asset.get('appearance'), dict) else {}
        explicit = appearance.get('animation_id', asset.get('animation_id'))
        if explicit is not None:
            if type(explicit) is not int or not 0 <= explicit <= 0xffffffff:
                raise ValueError('Original world animation ID invalid')
            return explicit
        animation = row.get('animation') or {}
        if not isinstance(animation, dict):
            raise ValueError('Original world animation state invalid')
        state = str(animation.get('locomotion') or row.get('motion_state') or animation.get('state') or 'IDLE').upper()
        if state not in LOCOMOTION:
            raise ValueError('Original world animation requires an explicit ID for ' + state[:64])
        return LOCOMOTION[state]

    def _options(self, record, row, now):
        animation = self._animation(row)
        action = str((row.get('animation') or {}).get('action_serial', ''))[:128]
        key = (animation, action)
        if record.get('clip_key') != key or now < record.get('last_ms', now):
            record['clip_key'] = key
            record['armed_ms'] = now
        record['last_ms'] = now
        return dict(instance=record['owner'], world_instance=True, anchor=world_anchor(row, record['scale']),
                    anim_id=animation, cursor_ms=max(0, now - record['armed_ms']), clock_ms=now,
                    particle_density=record['particle_density'])

    def finish(self):
        if self.future is None or not self.future.done():
            return False
        future, refs = self.future, self.refs
        self.future, self.refs = None, []
        try:
            metadata, blob = future.result()
            models = metadata['models']
            if len(models) != len(refs) or len(blob) > 6 * 1024 * 1024:
                raise ValueError('Original actor pose result capacity exceeded')
            for (identity, record, generation, options), model in zip(refs, models):
                if generation != self.generation or self.records.get(identity) is not record or not self.running:
                    continue
                record['model'].update(model, blob)
                record['model'].options = dict(options)
                # Existing attachment/appearance code uses the newly sampled
                # parent attachment matrices, not an invented socket position.
                record['model'].appearance({'appearance': record['appearance']})
                for events in record['model'].take_model_events():
                    self._audio(record, events)
                self._alpha(record)
            self.frames += 1
        except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
            self._error('pose', exc)
        return True

    @staticmethod
    def _alpha(record):
        for batch in record['model'].batches:
            batch.row = {**batch.row, 'world_actor_id': record['identity'], 'world_actor_kind': record['kind'],
                         'alpha': batch.row.get('alpha', 1.) * record['alpha']}
            batch.changed.emit()

    def update(self, snapshot, stream, entity_audio, *, scope=None, running=True, particle_density=1.):
        cache = getattr(stream, 'cache', None)
        pool = getattr(stream, 'pool', None)
        if (not isinstance(snapshot, dict) or not getattr(stream, 'active', False) or cache is None
                or pool is None or cache.closed or cache.archive_source is None):
            if self.cache is not None:
                self.close()
            return
        if cache is not self.cache or scope != self.scope or entity_audio is not self.audio:
            self.close()
            self.cache, self.pool, self.audio, self.scope = cache, pool, entity_audio, scope
        now = round(scalar(snapshot.get('player', {}).get('time_s'), 0., 0., 1e12) * 1000)
        if self.running and not running or self.time_ms is not None and now < self.time_ms:
            self.generation += 1
            for record in self.records.values():
                self._audio(record, None)
                record['clip_key'] = None
            self.next_ms = 0
        self.time_ms = now
        self.running = bool(running)
        rows = snapshot.get('render', {}).get('entities', [])
        if not isinstance(rows, list):
            rows = []
        wanted = {}
        for row in rows[:128]:
            if not isinstance(row, dict) or row.get('hidden') or row.get('kind') not in ('PLAYER', 'NPC', 'ACTOR', 'PET', 'CREATURE'):
                continue
            asset = row.get('asset')
            if not isinstance(asset, dict):
                continue
            appearance = asset.get('appearance') if isinstance(asset.get('appearance'), dict) else {}
            display = ident(appearance.get('display_id', asset.get('display_id')))
            identity = row.get('id')
            if display is None or not isinstance(identity, str) or not identity or len(identity) > 80:
                continue
            wanted[identity] = (row, display, appearance)
        requested = list(wanted)
        if requested != self._requested:
            self._requested = requested
            self.changed.emit()
        changed = False
        for identity, record in list(self.records.items()):
            if (identity not in wanted or wanted[identity][1] != record['display']
                    or self.audio._actor(record['audio_row']['audio_actor_id']) is not record['actor']
                    or json.dumps({k: v for k, v in wanted[identity][2].items() if k != 'animation_id'}, sort_keys=True) != record['appearance_input']):
                self._retire(identity)
                changed = True
        # Removal/source replacement precedes late pose delivery. An evicted
        # actor must not emit one last footstep from its completed worker job.
        self.finish()
        for identity, (row, display, appearance) in wanted.items():
            if identity in self.records:
                continue
            if len(self.records) >= MAX_ACTORS:
                self._error(identity, 'Original world actor capacity exceeded')
                continue
            signature = (identity, display, json.dumps(appearance, sort_keys=True, separators=(',', ':')))
            if self.clock() < self.failures.get(signature, 0.):
                continue
            owner = None
            try:
                resolved = cache.creature_display(display)
                source = resolved['source']
                if not isinstance(source, str) or Path(source.replace('\\', '/')).suffix.lower() not in ('.m2', '.mdx'):
                    raise ValueError('Original display did not resolve an M2 model')
                path = cache.resolve(source)
                canonical = 'player' if row['kind'] == 'PLAYER' else identity
                self.serial += 1
                owner = 'world:actor:' + str(self.generation) + ':' + str(self.serial) + ':' + identity
                audio_row = dict(id=owner, audio_world=True, audio_actor_id=canonical, audio_world_space=True)
                record = dict(owner=owner, display=display, path=path, scale=resolved['scale'], alpha=resolved['alpha'],
                              identity=identity, kind=row['kind'],
                              appearance={**resolved['appearance'], **appearance}, audio_row=audio_row,
                              actor=self.audio._actor(canonical),
                              appearance_input=json.dumps({k: v for k, v in appearance.items() if k != 'animation_id'}, sort_keys=True),
                              particle_density=scalar(particle_density, 1., 0., 1.))
                options = self._options(record, row, now)
                model_row = dict(id=owner, play=dict(anim_id=options['anim_id'], cursor_ms=0), clock_ms=now,
                                 world_anchor=options['anchor'], particle_density=record['particle_density'], **{k: v for k, v in audio_row.items() if k != 'id'})
                model = cache.live_model(path, model_row)
                record['model'] = model
                model.appearance({'appearance': record['appearance']})
                if not any(clip['anim_id'] == options['anim_id'] for clip in model.facts.get('sequences', [])):
                    raise ValueError('Original model lacks the requested animation ID')
                self.records[identity] = record
                self._alpha(record)
                if running:
                    self._audio(record, {'keys': []})
                self.failures.pop(signature, None)
                changed = True
            except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
                if len(self.failures) >= 32:
                    self.failures.pop(next(iter(self.failures)))
                self.failures[signature] = self.clock() + 2.
                self._error(identity, exc)
                # A failed appearance/animation must release its provisional
                # native slot as well as the Qt buffers.
                for key in list(cache.live_models):
                    if owner is not None and key[1] == owner:
                        cache.release_live_model(key)
        if changed:
            self.changed.emit()
        if not running or self.future is not None or now < self.next_ms or not self.records:
            return
        refs, items, estimate = [], [], 0
        for identity, record in self.records.items():
            try:
                options = self._options(record, wanted[identity][0], now)
                if not any(c['anim_id'] == options['anim_id'] for c in record['model'].facts.get('sequences', [])):
                    raise ValueError('Original model lacks the requested animation ID')
                cost = sum(batch.capacity * batch.stride + (batch.instances.capacity * 80 if batch.instances is not None else 0) for batch in record['model'].batches)
                if estimate + cost > 6 * 1024 * 1024:
                    raise ValueError('Original actor pose byte budget exceeded')
                estimate += cost
                items.append(dict(path=str(record['path']), **options))
                refs.append((identity, record, self.generation, options))
                self._audio(record, {'keys': []})
            except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
                self._error(identity, exc)
                self._audio(record, None)
        if items:
            if len(json.dumps(items)) > 60000:
                self._error('pose', 'Original actor request capacity exceeded')
                return
            self.refs = refs
            self.next_ms = now + 33
            self.future = pool.submit(self._sample, cache, items)

    @staticmethod
    def _sample(cache, items):
        return NativeFormats._unpack(cache._reader().request('pose_many', items=items, defaults={'compact': True}, timeout=2))
