"""Canonical loot sources without manufacturing a container for a real drop."""
from __future__ import annotations

import hashlib
import json
import math

from backend import game_engine_items as items


def ground_signature(instance):
    """Freeze persisted physical terms, including ownership and actual position."""
    keys = ('instance_id', 'definition_id', 'kind', 'quantity', 'location',
            'owner_id', 'position', 'source_actor_id', 'custody_origin', 'gear',
            'affixes', 'enchantments', 'gift', 'letter', 'petition', 'seed',
            'craft_quality', 'scroll_enchant_id')
    value = {key: instance.get(key) for key in keys}
    value.update(container_id=instance.get('container_id', ''),
                 bound_to=instance.get('bound_to', ''),
                 condition=instance.get('condition', 1.),
                 loot_claimed=bool(instance.get('loot_claimed', False)))
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def validate_roll_source(roll):
    kind = roll.get('source_kind', 'CONTAINER')
    if kind not in ('CONTAINER', 'GROUND'):
        raise ValueError('LOOT_ROLL_SAVE_SOURCE')
    signature = roll.get('ground_signature')
    if kind == 'GROUND':
        if (roll.get('item') != roll.get('source') or not isinstance(signature, str)
                or len(signature) != 64 or any(c not in '0123456789abcdef' for c in signature)):
            raise ValueError('LOOT_ROLL_SAVE_SOURCE')
    elif signature is not None:
        raise ValueError('LOOT_ROLL_SAVE_SOURCE')


class CanonicalLootSourcesMixin:
    def _ground_loot_reachable_locked(self, source):
        if (not source or source.get('location') != 'GROUND' or source.get('kind') == 'CONTAINER'
                or self._player_defeated_locked()):
            return False
        actual, _ = self._nearest_item_locked(source['instance_id'])
        if actual is not source:
            return False
        position = source.get('position', {})
        return math.dist((self._x[0], self._y[0], self._z[0]),
                         tuple(float(position.get(k, 0)) for k in ('x', 'y', 'z'))) <= items.INTERACTION_RADIUS_M

    def _loot_item_at_source_locked(self, instance, source):
        if not instance or not source or instance.get('kind') == 'CONTAINER':
            return False
        if source.get('kind') == 'CONTAINER':
            return (instance.get('location') == 'CONTAINER'
                    and instance.get('container_id') == source['instance_id'])
        return (instance is source and instance.get('location') == 'GROUND'
                and instance.get('instance_id') == source.get('instance_id'))

    def _loot_roll_source_matches_locked(self, roll, instance, source):
        if not self._loot_item_at_source_locked(instance, source):
            return False
        if roll.get('source_kind', 'CONTAINER') == 'GROUND':
            return (self._ground_loot_reachable_locked(source)
                    and ground_signature(instance) == roll.get('ground_signature'))
        return source.get('kind') == 'CONTAINER'

    def _loot_source_locked(self):
        session = getattr(self, '_engine_loot', {})
        if session.get('source_kind') != 'GROUND':
            return super()._loot_source_locked()
        source = self._item_instances.get(session['container_id'])
        if (not self._ground_loot_reachable_locked(source)
                or ground_signature(source) != session.get('ground_signature')):
            self._engine_loot = {}
            return None
        return source

    def _open_loot_locked(self, source):
        if source.get('kind') == 'CONTAINER':
            return super()._open_loot_locked(source)
        if not self._ground_loot_reachable_locked(source):
            raise ValueError('LOOT_SOURCE_CHANGED_OR_CLOSED')
        signature = ground_signature(source)
        previous = getattr(self, '_engine_loot', {})
        if (previous.get('source_kind') == 'GROUND' and previous.get('container_id') == source['instance_id']
                and previous.get('ground_signature') == signature):
            return
        self._engine_loot_generation = getattr(self, '_engine_loot_generation', 0) + 1
        self._engine_loot = dict(container_id=source['instance_id'], source_kind='GROUND',
            ground_signature=signature, session=self._engine_loot_generation,
            ids=(source['instance_id'],))

    def _open_shared_group_loot_source_locked(self, source):
        """Host pickup/bulk callers pass the actual nearby registry row, under lock."""
        if source.get('kind') == 'CONTAINER':
            return self.open_container(source['instance_id'])
        try:
            if self._services.get('taxi_flight'):
                raise ValueError('TAXI_IN_PROGRESS')
            self._open_loot_locked(source)
        except (ValueError, TypeError, OverflowError) as exc:
            return self._local_action_error_locked(str(exc))
        self._ui_snapshot_base = None
        result = self.snapshot_locked()
        # Native publishes LOOT_OPENED from this genuine session change itself.
        result['item_result'] = dict(action='OPEN', source_kind='GROUND',
            source_id=source['instance_id'], count=0)
        return result

    def _refresh_loot_container_locked(self, source):
        if source.get('kind') == 'CONTAINER':
            source['contents'] = [row['instance_id'] for row in self._item_instances.values()
                if row.get('location') == 'CONTAINER' and row.get('container_id') == source['instance_id']]

    def _settle_group_loot_locked(self, now):
        # A vanished or changed real drop cancels its pending distribution. It
        # never turns an invalid source into an automatic pass or a new item.
        for roll in list(self._services['loot_rolls']):
            if roll.get('source_kind') != 'GROUND':
                continue
            instance = self._item_instances.get(roll['item'])
            source = self._item_instances.get(roll['source'])
            if not self._loot_roll_source_matches_locked(roll, instance, source):
                self._services['loot_rolls'].remove(roll)
                self._services['revision'] += 1
        return super()._settle_group_loot_locked(now)

