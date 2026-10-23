"""Private GG expedition maps over one canonical character and item registry.

Authored place geometry is reused deliberately, as separate maps in a game can
share a mesh. NPC transforms, encounter health, ground custody and lockouts are
map-local. Owned items, player progression and consenting companions cross the
boundary once. Dormant NPC slots remain reserved, rather than becoming free
pool slots that unrelated spawns could overwrite.
"""
import copy
import math

from backend import game_engine_combat as combat
from backend import game_engine_npc_identity as people
from backend.game_engine_npc import MAX_NPCS
from backend.game_engine_items import MAX_WORLD_INSTANCES


MAP_BASE = 0x4800
RADIUS = 24.
NUMBER_FIELDS = ('_x', '_y', '_z', '_vx', '_vy', '_vz', '_yaw',
    '_npc_home_x', '_npc_home_z', '_npc_target_x', '_npc_target_z',
    '_npc_phase', '_npc_state_time', '_npc_decision_speed',
    '_npc_perception_radius', '_npc_target_distance', '_npc_last_seen_x',
    '_npc_last_seen_z', '_npc_last_seen_age')
TEXT_FIELDS = ('_npc_state', '_npc_reason', '_npc_stimulus')
WORLD_FIELDS = NUMBER_FIELDS + TEXT_FIELDS + ('_npc_line_of_sight',)
PATH_FIELDS = ('_npc_path', '_npc_path_index', '_npc_path_status',
    '_npc_path_goal_tile', '_npc_path_navigation_key', '_npc_path_attempt_tick')
SESSION_ROLLBACK_ATTRIBUTES = ('_npc_indices', '_active_entity_indices',
    '_entity_count', '_combat_target_id', '_actions') + WORLD_FIELDS + PATH_FIELDS


def _world_shape(world):
    if not isinstance(world, dict) or set(world) != {'npcs', 'actors', 'people', 'dispositions'}:
        raise ValueError('INSTANCE_WORLD_INVALID')
    for key in world:
        if not isinstance(world[key], dict) or len(world[key]) > MAX_NPCS:
            raise ValueError('INSTANCE_WORLD_CAPACITY')
    if set(world['actors']) != set(world['npcs']):
        raise ValueError('INSTANCE_ACTOR_REGISTRY_INVALID')
    if not set(world['people']) <= set(world['npcs']) or not set(world['dispositions']) <= set(world['people']):
        raise ValueError('INSTANCE_IDENTITY_REGISTRY_INVALID')
    for owner, row in world['npcs'].items():
        if not isinstance(owner, str) or not 1 <= len(owner) <= 64 or not isinstance(row, dict) or set(row) != set(WORLD_FIELDS):
            raise ValueError('INSTANCE_NPC_INVALID')
        for key in NUMBER_FIELDS:
            value = row[key]
            if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 1_000_000:
                raise ValueError('INSTANCE_NPC_POSITION_INVALID')
        if any(not isinstance(row[key], str) or len(row[key]) > 96 for key in TEXT_FIELDS) or type(row['_npc_line_of_sight']) is not bool:
            raise ValueError('INSTANCE_NPC_STATE_INVALID')
        actor = world['actors'][owner]
        normalized = combat.normalize_state(dict(version=1, actors={owner: actor}))['actors'].get(owner)
        if not isinstance(actor, dict) or normalized is None or normalized != actor:
            raise ValueError('INSTANCE_COMBAT_INVALID')
    for owner, person in world['people'].items():
        if not isinstance(person, dict) or person.get('id') != owner or people.normalize_individual(person) is None:
            raise ValueError('INSTANCE_IDENTITY_INVALID')
    for owner, disposition in world['dispositions'].items():
        if not isinstance(disposition, dict) or disposition.get('identity_id') != owner:
            raise ValueError('INSTANCE_DISPOSITION_INVALID')


class PrivateWorldMixin:
    def _instance_map_descriptor_locked(self):
        record = self._expedition_record_locked()
        if not record or not record.get('world'):
            return None
        places = self._expedition_places_locked()
        place = places[record['ref']]
        return dict(id=MAP_BASE + sorted(places).index(record['ref']),
            name=place['name'], kind='INSTANCE', instance_id=record['id'],
            place_ref=record['ref'], center=dict(x=place['x'], z=place['z']),
            bounds=dict(left=place['x']-RADIUS, right=place['x']+RADIUS,
                        top=place['z']-RADIUS, bottom=place['z']+RADIUS),
            geometry='GG_AUTHORED_PLACE')

    def _instance_private_locked(self):
        state = getattr(self, '_services', {}).get('instance_sessions', {})
        return bool(state.get('active') and state.get('overworld'))

    def _instance_register_world_items_locked(self):
        state = self._services['instance_sessions']
        active = state['active']
        current = active['id'] if self._instance_private_locked() else 0
        maps = state.setdefault('item_maps', {})
        for key in list(maps):
            if key not in self._item_instances or self._item_instances[key].get('location') not in ('GROUND','CONTAINER'):
                del maps[key]
        # Register ownership before the next render, interaction or save. The
        # map ledger is orthogonal to custody: pickup never copies an item.
        for key, item in self._item_instances.items():
            if item.get('location') in ('GROUND', 'CONTAINER'):
                maps.setdefault(key, current)

    def _instance_item_transition_locked(self, item, previous_location):
        state=self._services['instance_sessions'];maps=state['item_maps']
        key=item['instance_id'];location=item.get('location')
        if location not in ('GROUND','CONTAINER'):
            maps.pop(key,None)
        elif previous_location not in ('GROUND','CONTAINER'):
            maps[key]=state['active']['id'] if self._instance_private_locked() else 0

    def _instance_item_visible_locked(self, item):
        if not isinstance(item, dict):
            return False
        if item.get('location') not in ('GROUND', 'CONTAINER'):
            return True
        state = self._services['instance_sessions']
        current = state['active']['id'] if self._instance_private_locked() else 0
        return state['item_maps'].setdefault(item['instance_id'], current) == current

    def _instance_visible_item_rows_locked(self):
        self._instance_register_world_items_locked()
        state = self._services['instance_sessions']
        current = state['active']['id'] if self._instance_private_locked() else 0
        maps = state['item_maps']
        return [row for key, row in self._item_instances.items()
                if row.get('location') not in ('GROUND', 'CONTAINER') or maps.get(key, 0) == current]

    def _instance_capture_world_locked(self, *, identities=()):
        world = dict(npcs={}, actors={}, people={}, dispositions={})
        actors = self._combat_state['actors']
        for index in self._npc_indices:
            owner = self._npc_ids[index]
            if not self._alive[index] or not owner:
                continue
            world['npcs'][owner] = {key: copy.deepcopy(getattr(self, key)[index]) for key in WORLD_FIELDS}
            actor = combat.ensure_actor(self._combat_state, owner, self._npc_combat_profile_locked(owner))
            world['actors'][owner] = copy.deepcopy(actor)
        for owner in identities:
            person = self._individual_state['individuals'].get(owner)
            if owner in world['npcs'] and isinstance(person, dict):
                world['people'][owner] = copy.deepcopy(person)
                disposition = self._faction_state.get('people', {}).get(owner)
                if isinstance(disposition, dict):
                    world['dispositions'][owner] = copy.deepcopy(disposition)
        return world

    def _instance_apply_world_locked(self, world):
        _world_shape(world)
        all_indices = {owner: index for index, owner in enumerate(self._npc_ids)
                       if owner and self._alive[index]}
        missing = set(world['npcs']) - set(all_indices)
        if missing:
            raise ValueError('INSTANCE_NPC_SLOT_MISSING')
        # Removing dormant rows from both the simulator and renderer reserves
        # their _alive slots while making them physically absent in this map.
        old_npcs = set(all_indices.values())
        self._active_entity_indices = [i for i in self._active_entity_indices if i not in old_npcs]
        self._npc_indices = [all_indices[owner] for owner in world['npcs']]
        self._active_entity_indices = sorted(set(self._active_entity_indices) | set(self._npc_indices))
        self._entity_count = len(self._active_entity_indices)
        for owner, row in world['npcs'].items():
            index = all_indices[owner]
            for key in WORLD_FIELDS:
                getattr(self, key)[index] = copy.deepcopy(row[key])
            self._npc_path[index] = []
            self._npc_path_index[index] = 0
            self._npc_path_status[index] = 'NOT_REQUESTED'
            self._npc_path_goal_tile[index] = None
            self._npc_path_navigation_key[index] = None
            self._npc_path_attempt_tick[index] = -60
        actors = self._combat_state['actors']
        for owner in all_indices:
            actors.pop(owner, None)
            self._character_actions.pop(owner, None)
        actors.update(copy.deepcopy(world['actors']))
        self._individual_state['individuals'].update(copy.deepcopy(world['people']))
        self._faction_state.setdefault('people', {}).update(copy.deepcopy(world['dispositions']))
        self._combat_target_id = ''
        self._actions.auto_attack = False
        self._clear_local_ui_sessions_locked()
        if hasattr(self, '_cancel_spell_locked'):
            self._cancel_spell_locked('WORLD_CHANGED')
        self._ui_snapshot_base = None
        self._render_snapshot_cache = None
        self._render_snapshot_signature = None

    def _instance_enter_world_locked(self, record):
        state = self._services['instance_sessions']
        if state.get('overworld'):
            raise ValueError('INSTANCE_ALREADY_ACTIVE')
        self._instance_register_world_items_locked()
        crew = ['player'] + ([] if self._is_ghost_locked() else list(self._services['group']['members']))
        candidates = [self._npc_ids[i] for i in self._npc_indices
            if self._alive[i] and self._npc_ids[i] not in crew
            and self._individual_state['individuals'].get(self._npc_ids[i], {}).get('role') == 'GUARDIAN']
        if not candidates:
            raise ValueError('INSTANCE_ENCOUNTER_TEMPLATE_REQUIRED')
        # One authored guardian encounter per local place. This is an actual
        # combat actor, not a fabricated claim of original dungeon contents.
        encounters = list(record.get('world', {}).get('people', {})) if record.get('world') else candidates[:1]
        overworld = self._instance_capture_world_locked(identities=encounters)
        if any(owner not in overworld['npcs'] for owner in crew[1:] + encounters):
            raise ValueError('INSTANCE_COMPANION_NOT_PRESENT')
        if any(not overworld['actors'][owner].get('alive', True) or overworld['actors'][owner].get('engaged_target') for owner in crew[1:]):
            raise ValueError('INSTANCE_COMPANION_NOT_READY')
        if record.get('world'):
            private = copy.deepcopy(record['world'])
            # Prior party members return to their own shared-world identities;
            # entering now transfers exactly the current consenting roster.
            for owner in list(private['npcs']):
                if owner not in encounters:
                    private['npcs'].pop(owner);private['actors'].pop(owner)
        else:
            private = dict(npcs={}, actors={}, people={}, dispositions={})
            for owner in encounters:
                for key in private:
                    if owner in overworld[key]:private[key][owner] = copy.deepcopy(overworld[key][owner])
                temporary = combat.new_state()
                private['actors'][owner] = combat.ensure_actor(temporary, owner, self._npc_combat_profile_locked(owner))
        place = self._expedition_places_locked()[record['ref']]
        for ordinal, owner in enumerate(encounters + crew[1:]):
            if owner not in encounters:
                private['npcs'][owner] = copy.deepcopy(overworld['npcs'][owner])
                private['actors'][owner] = copy.deepcopy(overworld['actors'][owner])
            row = private['npcs'][owner]
            x = place['x'] + (6. if owner in encounters else 16.)
            z = place['z'] + (ordinal % 5 - 2) * 2.
            row.update(_x=x, _y=self._ground_contact_height_locked(x, z), _z=z,
                _vx=0., _vy=0., _vz=0., _npc_home_x=x, _npc_home_z=z,
                _npc_target_x=x, _npc_target_z=z, _npc_reason='INSTANCE_SESSION')
        record['participants'] = crew
        record['world'] = private
        state['overworld'] = overworld
        self._instance_apply_world_locked(private)

    def _instance_checkpoint_world_locked(self):
        self._instance_register_world_items_locked()
        if not self._instance_private_locked():return
        record = self._expedition_record_locked()
        if not record:raise ValueError('INSTANCE_ACTIVE_INVALID')
        identities = list(record['world']['people'])
        record['world'] = self._instance_capture_world_locked(identities=identities)

    def _instance_exit_world_locked(self):
        state = self._services['instance_sessions']
        if not self._instance_private_locked():return
        self._instance_checkpoint_world_locked()
        record = self._expedition_record_locked()
        current = record['world']
        overworld = copy.deepcopy(state['overworld'])
        # A transferred companion keeps their current health/status/cooldown;
        # returning to the entrance never heals or clones them.
        for owner in record['participants'][1:]:
            if owner in current['actors'] and owner in overworld['actors']:
                overworld['actors'][owner] = copy.deepcopy(current['actors'][owner])
                overworld['actors'][owner]['engaged_target'] = ''
            current['npcs'].pop(owner, None);current['actors'].pop(owner, None)
        self._instance_apply_world_locked(overworld)
        state['overworld'] = None

    def _instance_loaded_locked(self):
        state = self._services['instance_sessions']
        self._instance_register_world_items_locked()
        if self._instance_private_locked():
            record = self._expedition_record_locked()
            if not record or not record.get('world'):raise ValueError('INSTANCE_ACTIVE_INVALID')
            self._instance_apply_world_locked(record['world'])

    def _instance_prepare_load_locked(self):
        if not self._instance_private_locked():return
        indices=[i for i,owner in enumerate(self._npc_ids) if owner and self._alive[i]]
        self._npc_indices=indices
        self._active_entity_indices=sorted(set(self._active_entity_indices)|set(indices))
        self._entity_count=len(self._active_entity_indices)

    def _instance_validate_worlds_locked(self, state, known):
        state.setdefault('overworld', None);state.setdefault('item_maps', {})
        maps = state['item_maps']
        if not isinstance(maps, dict) or len(maps) > MAX_WORLD_INSTANCES:
            raise ValueError('INSTANCE_ITEM_MAP_CAPACITY')
        keys = {r['id'] for r in state['lockouts']}
        for key, value in maps.items():
            if not isinstance(key, str) or not 1 <= len(key) <= 96 or type(value) is not int or value not in keys | {0}:
                raise ValueError('INSTANCE_ITEM_MAP_INVALID')
        for record in state['lockouts']:
            if record.get('world') is not None:
                _world_shape(record['world'])
                if not 1 <= len(record['world']['people']) <= 3:
                    raise ValueError('INSTANCE_ENCOUNTER_CAPACITY')
                if not set(record['world']['npcs']) <= set(record['participants']) | set(record['world']['people']):
                    raise ValueError('INSTANCE_WORLD_PARTICIPANTS_INVALID')
        if state['overworld'] is not None:
            _world_shape(state['overworld'])
            if not state['active']:
                raise ValueError('INSTANCE_RETURN_WORLD_INVALID')
            record = next((r for r in state['lockouts'] if r['id'] == state['active']['id']), None)
            if not record or not record.get('world'):
                raise ValueError('INSTANCE_ACTIVE_WORLD_INVALID')

