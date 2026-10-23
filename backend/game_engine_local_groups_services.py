"""Original local loot flow for the one present member of a saved group.

Items stay in the existing character world registry and existing service
transaction. This adds no remote escrow, offline actors or automatic votes.
NPC groups continue through the existing SocialServicesMixin unchanged.
"""
from __future__ import annotations

from backend import game_engine_items as items
from backend import game_engine_local_groups as groups
from backend.game_engine_adapter_social import QUALITY, event
from backend.game_engine_adapter_loot_sources import CanonicalLootSourcesMixin, ground_signature


class SharedLocalGroupLootMixin(CanonicalLootSourcesMixin):
    def _shared_group_loot_context_locked(self):
        snapshot = self._shared_custody_locked()
        if snapshot is None:
            return None
        character = self._local_character_id
        key, group = self._local_custody_store._group_for(snapshot['shared'], character)
        # These arrays belong to the actual loaded player, not a saved roster
        # projection. The canonical combat/lifecycle guard also excludes ghosts.
        present = (str(self._persistence_key) == character and len(self._x) > 0 and
                   bool(self._alive[0]) and not self._player_defeated_locked())
        return groups.world_loot_context(key, group, character, present=present)

    def _loot_view_locked(self):
        value = super()._loot_view_locked()
        context = self._shared_group_loot_context_locked()
        if context is not None and value.get('open'):
            value['master_candidates'] = groups.master_candidates(
                context, getattr(self, '_local_character_name', 'Gold Goblin'))
        return value

    def _loot_pickup_command_locked(self, command):
        context = self._shared_group_loot_context_locked()
        if context is None or context['loot_method'] == 'freeforall':
            return super()._loot_pickup_command_locked(command)
        if command['op'] == 'LootBindCancel':
            return super()._loot_pickup_command_locked(command)
        if command['op'] != 'LootPickup':
            # A former solo bind prompt cannot bypass a subsequently selected
            # group method. The current canonical row initiates that policy.
            raise ValueError('LOOT_GROUP_WINDOW_REQUIRED')
        source = self._loot_source_locked(); shown = self._engine_loot
        identity = command.get('item'); item = self._item_instance_locked(identity)
        if (not source or (shown.get('session'), shown.get('container_id')) !=
                (command.get('loot_session'), command.get('source'))):
            raise ValueError('LOOT_SOURCE_CHANGED_OR_CLOSED')
        if not item or identity not in shown['ids'] or not self._loot_item_at_source_locked(item, source):
            raise ValueError('LOOT_SLOT_EMPTY_OR_CHANGED')
        return self._group_loot_route_locked(item, source) or []

    def _group_loot_route_locked(self, instance, source):
        context = self._shared_group_loot_context_locked()
        if context is None:
            return super()._group_loot_route_locked(instance, source)
        existing = next((r for r in self._services['loot_rolls'] if r['item'] == instance['instance_id']), None)
        if existing:
            raise ValueError('LOOT_AWAITING_GROUP_DISTRIBUTION')
        method = context['loot_method']
        if method == 'freeforall':
            return None
        if context['eligible'] != ['player']:
            raise ValueError('LOOT_NO_PRESENT_ELIGIBLE_PLAYER')
        if instance['instance_id'] in self._services['free_loot']:
            self._award_group_item_locked(instance, source, 'player')
            self._services['free_loot'].remove(instance['instance_id'])
            return []
        definition = items.definition(self._item_catalog, instance['definition_id']) or {}
        quality = QUALITY.get(definition.get('rarity'), 1)
        if method == 'roundrobin' or quality < context['threshold']:
            self._services['loot_turn'] += 1
            self._award_group_item_locked(instance, source, 'player')
            return event('LOOT_SLOT_CLEARED', list(self._engine_loot['ids']).index(instance['instance_id']) + 1)
        if method == 'master' and context['master'] != 'player':
            raise ValueError('LOOT_MASTER_NOT_PRESENT')
        if len(self._services['loot_rolls']) >= 64:
            raise ValueError('LOOT_ROLL_CAPACITY')
        roll = dict(id=self._service_id_locked(), item=instance['instance_id'], source=source['instance_id'],
                    method=method, master=context['master'], eligible=['player'], votes={},
                    expires=self._service_now_locked() + 60,
                    bind=definition.get('bonding') == 1 or definition.get('bind_on_pickup', False),
                    shared_group=context['shared_id'])
        if source.get('kind') != 'CONTAINER':
            roll.update(source_kind='GROUND', ground_signature=ground_signature(instance))
        self._services['loot_rolls'].append(roll)
        return event('LOOT_MASTER_LIST') if method == 'master' else event('START_LOOT_ROLL', roll['id'], 60000)

    def _loot_roll_command_locked(self, row):
        roll = next((r for r in self._services['loot_rolls'] if r['id'] == row.get('id')), None)
        if roll and roll.get('shared_group') and row['op'] == 'LootMasterGive':
            context = self._shared_group_loot_context_locked()
            if (context is None or context['shared_id'] != roll['shared_group'] or
                    context['master'] != 'player' or context['eligible'] != ['player']):
                raise ValueError('LOOT_MASTER_REQUIRED')
        return super()._loot_roll_command_locked(row)
